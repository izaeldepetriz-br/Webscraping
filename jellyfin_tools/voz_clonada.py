"""Voz CLONADA da dublagem: a "réplica de voz" do Gemini (Voice Replication), sem placa de vídeo.

Só com a voz de quem AUTORIZOU: a sua, ou de alguém que gravou a frase de consentimento. Nunca a voz de atores,
de famosos ou de quem não sabe. O próprio Google confere isso ao criar a voz:

    1. o áudio de REFERÊNCIA: a pessoa lendo um texto qualquer, com calma (de 10 a 30 s, sem música nem eco)
    2. o áudio de CONSENTIMENTO: a MESMA pessoa, no mesmo lugar e microfone, dizendo a frase (em inglês):
       "I am the owner of this voice and I consent to Google using this voice to create a synthetic voice model."
    -> o Google confere se a frase foi dita e se as duas gravações são da mesma voz (e recusa voz de IA)

Como uma chave de casa: o Google devolve uma CHAVE da voz ("voicekey_..."), que fica só neste PC
(vozes_clonadas.json, na pasta de configurações) e não fica guardada no Google (store=False). A dublagem usa a voz
como "clone:Nome", no lugar de uma voz pronta ("Kore"); na hora de pedir o áudio, o motor troca pelo valor da chave.
"""

from __future__ import annotations

import base64
import json
import re
import subprocess
import wave
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from .dublagem import ErroDublagem

PREFIXO = "clone:"
FRASE_CONSENTIMENTO = ("I am the owner of this voice and I consent to Google using this voice to create a "
                       "synthetic voice model.")
FRASE_TRADUCAO = ("Eu sou o dono desta voz e autorizo o Google a usar esta voz para criar um modelo de voz "
                  "sintética.")
# Para a gravação de referência: um texto em português com perguntas, exclamação e números (~20 s lido com calma).
TEXTO_REFERENCIA = ("Hoje o dia começou nublado, mas à tarde o sol apareceu. Fui até a padaria, comprei dois pães e "
                    "um café. Você acredita que encontrei um amigo que não via há dez anos? Conversamos bastante, "
                    "rimos das histórias antigas e combinamos de nos ver de novo no sábado. Que surpresa boa!")
TAXA = 24000                 # o Google recomenda WAV 24 kHz, mono, 16 bits
MINIMO_REFERENCIA = 6.0      # segundos (menos que isso o Google recusa ou a voz fica pobre)
MAXIMO_REFERENCIA = 60.0
MINIMO_CONSENTIMENTO = 3.0
MAXIMO_CONSENTIMENTO = 30.0
PROIBIDOS = '()[]:"/\\'      # o nome aparece nos menus como "Clonada: Nome (autorizada por ...)"


@dataclass
class VozClonada:
    nome: str                # como aparece nos menus ("Izael")
    autorizada_por: str      # quem é o dono da voz e gravou o consentimento
    chave: str               # "voicekey_..." devolvida pelo Google (só neste PC)
    criada_em: str = ""      # "2026-10-11 14:30"
    expira_em: str = ""      # se o Google disser quando a chave vence (ISO); vazio = não informado
    modelo: str = ""
    gravacoes: str = ""      # pasta com as gravações guardadas (opção "Guardar as gravações"); vazio = apagadas

    @property
    def valor(self) -> str:
        """O valor usado na dublagem: "clone:Izael"."""
        return PREFIXO + self.nome

    def _fim(self) -> datetime | None:
        if not self.expira_em:
            return None
        try:
            return datetime.fromisoformat(self.expira_em.replace("Z", "+00:00"))
        except ValueError:
            return None

    def vencida(self, agora: datetime | None = None) -> bool:
        fim = self._fim()
        return fim is not None and (agora or datetime.now(fim.tzinfo)) >= fim

    def dias_para_vencer(self, agora: datetime | None = None) -> int | None:
        """Quantos dias faltam (0 = vence hoje); None = o Google não disse quando vence."""
        fim = self._fim()
        if fim is None:
            return None
        return max(0, (fim - (agora or datetime.now(fim.tzinfo))).days)

    def tem_gravacoes(self) -> bool:
        return bool(self.gravacoes) and all((Path(self.gravacoes) / f"{n}.wav").is_file()
                                            for n in ("referencia", "consentimento"))


def e_clonada(voz: str) -> bool:
    return isinstance(voz, str) and voz.startswith(PREFIXO)


def nome_da_voz(voz: str) -> str:
    """"clone:Izael" -> "Izael"."""
    return voz[len(PREFIXO):] if e_clonada(voz) else voz


def texto_do_menu(v: VozClonada) -> str:
    """'Clonada: Izael (autorizada por Izael)'; o caminho de volta é valor_do_menu()."""
    return f"Clonada: {v.nome} (autorizada por {v.autorizada_por})"


def valor_do_menu(texto: str) -> str | None:
    """'Clonada: Izael (autorizada por ...)' -> 'clone:Izael'; outro texto -> None."""
    if not texto.startswith("Clonada: "):
        return None
    return PREFIXO + texto[len("Clonada: "):].split(" (")[0].strip()


def validar_nome(nome: str, existentes: list[VozClonada] = ()) -> str:
    """O nome limpo, ou ErroDublagem com o motivo."""
    nome = " ".join(nome.split())
    if not nome:
        raise ErroDublagem("dê um nome para a voz (ex.: o seu nome)")
    if len(nome) > 40:
        raise ErroDublagem("o nome da voz pode ter até 40 letras")
    if any(c in nome for c in PROIBIDOS):
        raise ErroDublagem(f"o nome da voz não pode ter estes sinais: {' '.join(PROIBIDOS)}")
    if any(v.nome.lower() == nome.lower() for v in existentes):
        raise ErroDublagem(f"já existe uma voz clonada chamada \"{nome}\" (remova a antiga ou use outro nome)")
    return nome


# ----------------------------------------------------------------- guardar neste PC
def carregar(arquivo: Path) -> list[VozClonada]:
    try:
        dados = json.loads(Path(arquivo).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    campos = set(VozClonada.__dataclass_fields__)
    return [VozClonada(**{k: v for k, v in d.items() if k in campos}) for d in dados.get("vozes", [])
            if isinstance(d, dict) and d.get("nome") and d.get("chave")]


def salvar(vozes: list[VozClonada], arquivo: Path) -> None:
    arquivo = Path(arquivo)
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    temporario = arquivo.with_suffix(".tmp")
    temporario.write_text(json.dumps({"vozes": [asdict(v) for v in vozes]}, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    temporario.replace(arquivo)


AVISAR_DIAS = 7              # o painel de saúde avisa quando falta isso (ou menos) para a chave vencer


def aviso_de_validade(v: VozClonada, agora: datetime | None = None) -> str:
    """"" se está tudo certo; senão, o aviso para o painel de saúde."""
    if v.vencida(agora):
        return f"Voz clonada {v.nome}: venceu (clone de novo)"
    dias = v.dias_para_vencer(agora)
    if dias is not None and dias <= AVISAR_DIAS:
        return f"Voz clonada {v.nome}: vence {'hoje' if dias == 0 else f'em {dias} dia(s)'}"
    return ""


def pasta_das_gravacoes(base: Path, nome: str) -> Path:
    """Onde ficam as gravações guardadas de uma voz (nome sem sinais que o Windows recusa em pastas)."""
    return Path(base) / (re.sub(r"[^\w\- ]", "_", nome).strip() or "voz")


def guardar_gravacoes(pasta: Path, referencia: bytes, consentimento: bytes) -> Path:
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "referencia.wav").write_bytes(referencia)
    (pasta / "consentimento.wav").write_bytes(consentimento)
    return pasta


def ler_gravacoes(v: VozClonada) -> tuple[bytes, bytes]:
    if not v.tem_gravacoes():
        raise ErroDublagem(f"as gravações da voz \"{v.nome}\" não estão guardadas neste PC: clone gravando de novo")
    pasta = Path(v.gravacoes)
    return (pasta / "referencia.wav").read_bytes(), (pasta / "consentimento.wav").read_bytes()


def apagar_gravacoes(v: VozClonada) -> None:
    import shutil
    if v.gravacoes and Path(v.gravacoes).is_dir():
        shutil.rmtree(v.gravacoes, ignore_errors=True)


def chaves(vozes: list[VozClonada]) -> dict[str, str]:
    """{"clone:Izael": "voicekey_..."} para o motor do Gemini."""
    return {v.valor: v.chave for v in vozes}


# ----------------------------------------------------------------- os áudios
def duracao(wav: bytes) -> float:
    import io
    with wave.open(io.BytesIO(wav)) as w:
        return w.getnframes() / float(w.getframerate() or 1)


def preparar_audio(origem: Path, ffmpeg: str, executar=subprocess.run) -> bytes:
    """Qualquer áudio (wav, mp3, m4a do celular, ogg do WhatsApp...) -> WAV 24 kHz, mono, 16 bits, sem o silêncio
    do começo e do fim (o Google confere a frase palavra por palavra; um clique de microfone atrapalha)."""
    origem = Path(origem)
    if not origem.is_file():
        raise ErroDublagem(f"não achei o áudio: {origem}")
    corte = ("silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.15,areverse,"
             "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.15,areverse")
    comando = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(origem), "-vn", "-af", corte,
               "-ar", str(TAXA), "-ac", "1", "-sample_fmt", "s16", "-f", "wav", "pipe:1"]
    try:
        resultado = executar(comando, capture_output=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as erro:
        raise ErroDublagem(f"o ffmpeg não conseguiu ler o áudio: {erro}") from erro
    if resultado.returncode != 0 or not resultado.stdout:
        erro = (resultado.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        raise ErroDublagem(f"o ffmpeg não conseguiu ler o áudio{': ' + erro[-1] if erro else ''}")
    return _corrigir_tamanho(resultado.stdout)


def _corrigir_tamanho(wav: bytes) -> bytes:
    """Pelo pipe, o ffmpeg não sabe o tamanho final e grava o cabeçalho com 0 (ou -1): refaz o cabeçalho."""
    import io
    try:
        inicio = wav.index(b"data") + 8
    except ValueError as erro:
        raise ErroDublagem("o áudio convertido veio sem dados") from erro
    amostras = wav[inicio:]
    amostras = amostras[:len(amostras) // 2 * 2]
    saida = io.BytesIO()
    with wave.open(saida, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(TAXA)
        w.writeframes(amostras)
    return saida.getvalue()


def conferir_duracoes(referencia: bytes, consentimento: bytes) -> None:
    ref, con = duracao(referencia), duracao(consentimento)
    if ref < MINIMO_REFERENCIA:
        raise ErroDublagem(f"a gravação de referência tem {ref:.0f} s (sem os silêncios); grave pelo menos "
                           f"{MINIMO_REFERENCIA:.0f} s lendo o texto com calma (o ideal é de 10 a 30 s)")
    if ref > MAXIMO_REFERENCIA:
        raise ErroDublagem(f"a gravação de referência tem {ref:.0f} s; use no máximo {MAXIMO_REFERENCIA:.0f} s")
    if con < MINIMO_CONSENTIMENTO:
        raise ErroDublagem(f"a gravação do consentimento tem {con:.0f} s: diga a frase inteira, sem pressa")
    if con > MAXIMO_CONSENTIMENTO:
        raise ErroDublagem(f"a gravação do consentimento tem {con:.0f} s; grave só a frase (até "
                           f"{MAXIMO_CONSENTIMENTO:.0f} s)")


def gravar_wav(amostras: bytes, destino: Path, taxa: int = TAXA) -> None:
    """Amostras de 16 bits mono (do microfone) -> arquivo .wav."""
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(destino), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(taxa)
        w.writeframes(amostras)


# ----------------------------------------------------------------- criar no Google
def _explicar_recusa(erro: Exception) -> str:
    from .voz_gemini import _codigo, _explicar
    texto = str(erro)
    if _codigo(erro) in (400, 403, 412) and any(p in texto.lower() for p in ("consent", "speaker", "similar",
                                                                            "verif", "synthetic", "spoof")):
        return ("o Google recusou a voz: a frase de consentimento não foi reconhecida inteira, ou as duas gravações "
                "não parecem da mesma pessoa (ou parecem voz de IA). Grave as duas no mesmo lugar e microfone, "
                "devagar, sem barulho, e diga a frase exatamente como está escrita")
    return _explicar(erro)


def criar(cliente, nome: str, autorizada_por: str, referencia: bytes, consentimento: bytes,
          modelo: str = "") -> VozClonada:
    """Manda as duas gravações (WAV 24 kHz) e devolve a voz com a chave (não fica guardada no Google)."""
    from .voz_gemini import MODELO_PADRAO
    if not autorizada_por.strip():
        raise ErroDublagem("diga quem é o dono da voz (quem autorizou e gravou o consentimento)")
    conferir_duracoes(referencia, consentimento)
    modelo = modelo or MODELO_PADRAO

    def audio(dados: bytes) -> dict:
        return {"data": base64.b64encode(dados).decode(), "mime_type": "audio/wav"}
    try:
        resposta = cliente.voices.create(store=False, voice={
            "model": modelo, "type": "replicated", "display_name": nome, "language_code": "pt-BR",
            "replicated": {"source_audio": audio(referencia), "consent_audio": audio(consentimento)}})
    except ErroDublagem:
        raise
    except Exception as erro:
        raise ErroDublagem(_explicar_recusa(erro)) from erro
    chave = getattr(resposta, "key", None) or getattr(resposta, "id", None)
    if not chave:
        raise ErroDublagem("o Google não devolveu a chave da voz")
    expira = getattr(resposta, "expire_time", None)
    return VozClonada(nome=nome, autorizada_por=" ".join(autorizada_por.split()), chave=chave,
                      criada_em=f"{datetime.now():%Y-%m-%d %H:%M}",
                      expira_em=expira.isoformat() if hasattr(expira, "isoformat") else str(expira or ""),
                      modelo=modelo)


def descrever(v: VozClonada) -> str:
    """Uma linha para a lista em Configurações > Dublagem."""
    partes = [f"🎙 {v.nome}", f"autorizada por {v.autorizada_por}"]
    if v.criada_em:
        partes.append(f"criada em {v.criada_em}")
    if v.vencida():
        partes.append("VENCIDA: clone de novo")
    elif v.expira_em:
        partes.append(f"vale até {v.expira_em[:10]}")
    if v.tem_gravacoes():
        partes.append("gravações guardadas")
    return " · ".join(partes)
