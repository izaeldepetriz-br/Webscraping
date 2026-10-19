"""As VOZES de um jogo dubladas no PC (o passo 3 do modo "Traduzir e dublar (no PC)" da aba 🎮 Jogos) e a entrega
(o passo 4): grátis, com o XTTS-v2 e as vozes genéricas dele (ou a SUA voz importada), nunca a voz dos atores.

    achar_falas(pasta, roteiro)   as falas gravadas do jogo (WAV, VAG, ADS) e, pelo roteiro, o texto de cada uma
                                  (a coluna "audio", ou o id igual ao nome do arquivo)
    medir(falas)                  pelo som da original: homem ou mulher (o tom) e gritando ou sussurrando (o
                                  volume comparado com as outras falas do jogo): a voz e a emoção seguem a original
    ouvir(falas, transcritor)     as falas sem texto no roteiro: o Whisper ouve a original (o jogo de corrida com o
                                  locutor da rádio não tem as falas escritas em lugar nenhum)
    elenco(falas, voz)            uma voz para cada personagem (o mesmo esquema dos filmes: sem repetir voz perto)
    dublar(falas, motor, saida)   gera cada fala e grava no FORMATO e na DURAÇÃO exatos da original
                                  (audio_jogo.gravar_como): o jogo toca no lugar da antiga sem travar nem cortar
    entregar(roteiro, falas)      roteiro_ptbr (as mesmas colunas) + audio_ptbr\\ (os mesmos nomes de arquivo) +
                                  o relatório do que conferir

Retoma de onde parou: a fala já dublada com o mesmo texto e a mesma voz não é gerada de novo.
"""

from __future__ import annotations

import json
import shutil
import wave
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import audio_jogo, genero_local
from .personagens import Personagem, catalogo_xtts, distribuir_vozes
from .roteiro_jogo import ResumoTraducao, Roteiro, gravar_roteiro, para_falar, traduzir_textos

EXTENSOES_SOM = (".wav", ".vag", ".ads")
PASTA_SAIDA_AUDIO = "audio_ptbr"
PASTA_TRABALHO = ".maestro"                 # dentro da pasta de entrega: as vozes geradas e o que já foi feito
ARQUIVO_FEITAS = "dubladas.json"
ARQUIVO_OUVIDAS = "ouvidas.json"
OUTROS = "Outros"                           # as falas sem personagem no roteiro
AUTOMATICA = "automática (pelo tom da original)"
NOTAS = {genero_local.TOM_GRITO: "Nesta fala: gritando, com força.",
         genero_local.TOM_SUSSURRO: "Nesta fala: sussurrando, em voz baixa."}
LOTE = 20                                   # falas por vez no motor (o Parar e o progresso respondem a cada lote)
SEGUNDOS_POR_LINHA = 5.0                    # o roteiro costuma vir na ordem das cenas: ~9 falas seguidas = 1 cena


@dataclass
class FalaJogo:
    arquivo: Path                           # a original, na pasta extraída
    relativo: str                           # "SOUND/KAEL_001.vag" (o mesmo caminho na entrega)
    formato: audio_jogo.Formato | None = None
    erro: str = ""                          # o formato que o Maestro não lê
    entrada: object = None                  # a Entrada do roteiro (se o roteiro tem o texto dela)
    texto: str = ""                         # o original (do roteiro ou ouvido pelo Whisper)
    ouvida: bool = False
    traducao: str = ""
    avisos: list = field(default_factory=list)
    personagem: str = ""
    genero: str = "?"                       # pelo tom da original
    tom: str = ""                           # genero_local.TOM_GRITO, TOM_SUSSURRO ou ""
    voz: str = ""
    feito: dict = field(default_factory=dict)

    @property
    def rotulo(self) -> str:
        return self.personagem or OUTROS


# ----------------------------------------------------------------- achar e medir
def _chave(nome: str) -> str:
    return nome.replace("\\", "/").strip().lower()


def achar_falas(pasta: str | Path, roteiro: Roteiro | None = None) -> list[FalaJogo]:
    """As falas gravadas na pasta extraída (fora a pasta de entrega) e o texto de cada uma pelo roteiro."""
    pasta = Path(pasta)
    por_nome: dict[str, object] = {}
    if roteiro is not None:
        for e in roteiro.entradas:
            for nome in ([e.audio, Path(e.audio).name, Path(e.audio).stem] if e.audio else []) + [e.chave]:
                if nome:
                    por_nome.setdefault(_chave(nome), e)
    falas = []
    for arquivo in sorted(pasta.rglob("*")):
        if not arquivo.is_file() or arquivo.suffix.lower() not in EXTENSOES_SOM:
            continue
        relativo = arquivo.relative_to(pasta).as_posix()
        if relativo.split("/")[0] in (PASTA_SAIDA_AUDIO, PASTA_TRABALHO):
            continue
        fala = FalaJogo(arquivo, relativo)
        try:
            fala.formato = audio_jogo.ler_formato(arquivo)
        except audio_jogo.ErroAudioJogo as erro:
            fala.erro = str(erro)
        entrada = next((por_nome[k] for k in (_chave(relativo), _chave(arquivo.name), _chave(arquivo.stem))
                        if k in por_nome), None)
        if entrada is not None:
            fala.entrada, fala.texto, fala.personagem = entrada, entrada.texto, entrada.personagem
        falas.append(fala)
    return falas


def medir(falas: list[FalaJogo], parar=None, ao_progresso=None) -> Counter:
    """O gênero (pelo tom) e a emoção pelo volume (gritando/sussurrando, comparado com as outras falas do jogo) de
    cada fala, ouvindo a original. Devolve a contagem {"m": .., "f": .., "?": .., TOM_GRITO: .., TOM_SUSSURRO: ..}."""
    medidas = []
    for i, fala in enumerate(falas):
        if parar and parar():
            break
        if fala.formato is None:
            medidas.append(None)
            continue
        try:
            som, taxa = audio_jogo.ler_som(fala.arquivo)
        except (audio_jogo.ErroAudioJogo, OSError, ValueError):
            medidas.append(None)
            continue
        if taxa != genero_local.TAXA and len(som):            # a medida é em 8 kHz
            som = np.interp(np.arange(int(len(som) * genero_local.TAXA / taxa)) * taxa / genero_local.TAXA,
                            np.arange(len(som)), som).astype(np.float32)
        medidas.append(genero_local.medir(som))
        if ao_progresso:
            ao_progresso((i + 1) / max(1, len(falas)))
    volumes = [m[1] for m in medidas if m and m[1] is not None and m[1] > genero_local.SILENCIO_DB]
    normal = float(np.median(volumes)) if len(volumes) >= genero_local.FALAS_PARA_COMPARAR else None
    conta = Counter()
    for fala, m in zip(falas, medidas):
        if not m:
            continue
        f0, volume, vozeado = m
        fala.tom = genero_local.tom_pelo_volume(volume, normal, vozeado, fala.texto)
        fala.genero = genero_local.genero_pelo_tom(f0, gritando=fala.tom == genero_local.TOM_GRITO)
        conta[fala.genero] += 1
        if fala.tom:
            conta[fala.tom] += 1
    return conta


def ouvir(falas: list[FalaJogo], transcritor, pasta_trabalho: str | Path, idioma: str | None = None, parar=None,
          ao_progresso=None) -> int:
    """O Whisper ouve as falas que o roteiro não tem escritas (guardado: não ouve de novo). Devolve quantas ouviu."""
    pasta = Path(pasta_trabalho)
    arquivo = pasta / ARQUIVO_OUVIDAS
    try:
        guardadas = json.loads(arquivo.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        guardadas = {}
    sem_texto = [f for f in falas if not f.texto.strip() and f.formato is not None]
    ouvidas = 0
    for i, fala in enumerate(sem_texto):
        if parar and parar():
            break
        marca = f"{fala.relativo}|{fala.formato.tamanho}"
        if marca not in guardadas:
            wav = audio_jogo.para_wav(fala.arquivo, pasta / "ouvir.wav")
            transcritor._carregar()
            segmentos, _ = transcritor.motor.transcribe(str(wav), language=idioma, beam_size=5, vad_filter=True)
            guardadas[marca] = " ".join(s.text.strip() for s in segmentos).strip()
            ouvidas += 1
            if ouvidas % 10 == 0:
                _gravar_json(arquivo, guardadas)
        fala.texto, fala.ouvida = guardadas[marca], True
        if ao_progresso:
            ao_progresso((i + 1) / max(1, len(sem_texto)))
    _gravar_json(arquivo, guardadas)
    (pasta / "ouvir.wav").unlink(missing_ok=True)
    return ouvidas


def traduzir_ouvidas(falas: list[FalaJogo], tradutor, glossario: tuple = (), tirar_acentos: bool = False,
                     memoria: dict | None = None, parar=None, ao_progresso=None) -> ResumoTraducao:
    """A tradução das falas que vieram do Whisper (as do roteiro já se traduzem com ele)."""
    alvo = [f for f in falas if f.ouvida and f.texto.strip()]
    traduzidas, avisos, resumo = traduzir_textos([f.texto for f in alvo], tradutor, None, glossario, tirar_acentos,
                                                 memoria, "falas do jogo", parar, ao_progresso)
    for fala, texto, aviso in zip(alvo, traduzidas, avisos):
        fala.traducao, fala.avisos = texto, aviso
    return resumo


def ligar_traducoes(falas: list[FalaJogo]) -> None:
    """As falas do roteiro recebem a tradução (e os avisos) da Entrada delas."""
    for fala in falas:
        if fala.entrada is not None:
            fala.traducao, fala.avisos = fala.entrada.traducao, list(fala.entrada.avisos)


# ----------------------------------------------------------------- as vozes
def elenco(falas: list[FalaJogo], voz_principal: str, fixas: dict | None = None,
           vozes_genero: dict | None = None) -> dict[str, str]:
    """{personagem: voz}. Os personagens do roteiro pelo mesmo esquema dos filmes (quem mais fala com a voz
    principal, os outros sem repetir voz perto). As falas sem personagem ("Outros"): pelo gênero do tom da original
    (vozes_genero {"m": voz, "f": voz}), a não ser que a tabela escolha uma voz para todas."""
    fixas = dict(fixas or {})
    por_nome: dict[str, list[int]] = {}
    for i, fala in enumerate(falas):
        if fala.personagem:
            por_nome.setdefault(fala.personagem, []).append(i)
    personagens = []
    for nome, indices in sorted(por_nome.items(), key=lambda x: -len(x[1])):
        generos = Counter(falas[i].genero for i in indices if falas[i].genero in ("m", "f"))
        personagens.append(Personagem(nome, generos.most_common(1)[0][0] if generos else "?", falas=indices))
    mapa = distribuir_vozes(personagens, voz_principal, fixas={k: v for k, v in fixas.items() if k in por_nome},
                            catalogo=catalogo_xtts(), tempos={i: i * SEGUNDOS_POR_LINHA for i in range(len(falas))}) \
        if personagens else {}
    mapa.update({k: v for k, v in fixas.items() if k in por_nome})
    vozes_genero = vozes_genero or {"m": voz_principal, "f": voz_principal}
    outros = fixas.get(OUTROS, "")
    for fala in falas:
        if fala.personagem:
            fala.voz = mapa.get(fala.personagem, voz_principal)
        else:
            fala.voz = outros or vozes_genero.get(fala.genero, voz_principal)
    if outros:
        mapa[OUTROS] = outros
    return mapa


def tabela_do_elenco(falas: list[FalaJogo]) -> list[tuple[str, int, str, str]]:
    """[(personagem, falas, voz, emoção)] para a tela: quem mais fala primeiro; "Outros" no fim."""
    grupos: dict[str, list[FalaJogo]] = {}
    for fala in falas:
        if fala.formato is not None:
            grupos.setdefault(fala.rotulo, []).append(fala)
    linhas = []
    for nome, lista in sorted(grupos.items(), key=lambda x: (x[0] == OUTROS, -len(x[1]))):
        vozes = Counter(f.voz for f in lista)
        voz = vozes.most_common(1)[0][0] if len(vozes) == 1 else AUTOMATICA
        tons = Counter(f.tom for f in lista if f.tom)
        emocao = ", ".join(f"{n} {'gritando' if t == genero_local.TOM_GRITO else 'sussurrando'}"
                           for t, n in tons.most_common()) or "—"
        linhas.append((nome, len(lista), voz, emocao))
    return linhas


# ----------------------------------------------------------------- dublar
@dataclass
class ResumoDublagem:
    dubladas: int = 0
    puladas: int = 0                        # já estavam prontas (mesmo texto e mesma voz)
    sem_traducao: int = 0
    aceleradas: int = 0
    cortadas: int = 0
    completadas: int = 0
    erros: list = field(default_factory=list)   # [(fala, motivo)]


def _gravar_json(arquivo: Path, dados) -> None:
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    temporario = arquivo.with_suffix(".tmp")
    temporario.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
    temporario.replace(arquivo)


def destino_da_fala(fala: FalaJogo, pasta_saida: str | Path, exato: bool = True) -> Path:
    destino = Path(pasta_saida) / PASTA_SAIDA_AUDIO / fala.relativo
    return destino if exato else destino.with_suffix(".wav")


def dublar(falas: list[FalaJogo], motor, pasta_saida: str | Path, ffmpeg: str, exato: bool = True,
           com_emocao: bool = True, refazer: bool = False, so: list | None = None, parar=None,
           ao_progresso=None) -> ResumoDublagem:
    """Gera as falas traduzidas com o motor (XTTS-v2) e grava cada uma em audio_ptbr\\ no formato e na duração da
    original (exato) ou num WAV comum do tamanho natural (para ouvir e editar). so: só estas falas (o teste)."""
    pasta_saida = Path(pasta_saida)
    trabalho = pasta_saida / PASTA_TRABALHO
    arquivo_feitas = trabalho / ARQUIVO_FEITAS
    try:
        feitas = json.loads(arquivo_feitas.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        feitas = {}
    resumo = ResumoDublagem()
    pendentes = []
    for fala in (so if so is not None else falas):
        if fala.formato is None:
            continue
        texto = para_falar(fala.traducao)
        if not texto:
            resumo.sem_traducao += 1
            continue
        destino = destino_da_fala(fala, pasta_saida, exato)
        assinatura = f"{texto}|{fala.voz}|{fala.tom if com_emocao else ''}|{'exato' if exato else 'natural'}"
        if not refazer and destino.is_file() and feitas.get(fala.relativo, {}).get("assinatura") == assinatura:
            fala.feito = feitas[fala.relativo]
            resumo.puladas += 1
            continue
        pendentes.append((fala, texto, destino, assinatura))
    total = max(1, len(pendentes))
    for inicio in range(0, len(pendentes), LOTE):
        if parar and parar():
            break
        lote = pendentes[inicio:inicio + LOTE]
        pedidos = []
        for fala, texto, _, _ in lote:
            wav = trabalho / "vozes" / (fala.relativo + ".wav")
            wav.parent.mkdir(parents=True, exist_ok=True)
            wav.unlink(missing_ok=True)
            pedidos.append((texto, wav, fala.voz, NOTAS.get(fala.tom, "") if com_emocao else ""))
        motor.sintetizar(pedidos, parar=parar, ao_progresso=(lambda f, base=inicio: ao_progresso(
            (base + f * len(lote)) / total)) if ao_progresso else None)
        for (fala, texto, destino, assinatura), pedido in zip(lote, pedidos):
            wav = Path(pedido[1])
            if not wav.is_file() or wav.stat().st_size <= 44:
                resumo.erros.append((fala.relativo, "a voz não foi gerada"))
                continue
            destino.parent.mkdir(parents=True, exist_ok=True)
            try:
                if exato:
                    feito = audio_jogo.gravar_como(fala.arquivo, wav, destino, ffmpeg)
                else:
                    shutil.copyfile(wav, destino)
                    feito = {"formato": "WAV natural"}
            except (audio_jogo.ErroAudioJogo, OSError) as erro:
                resumo.erros.append((fala.relativo, str(erro)))
                continue
            fala.feito = {**feito, "assinatura": assinatura, "voz": fala.voz}
            feitas[fala.relativo] = fala.feito
            resumo.dubladas += 1
            resumo.aceleradas += int(feito.get("acelerada", 1.0) > 1.0)
            resumo.cortadas += int(feito.get("cortada", 0.0) > 0)
            resumo.completadas += int(feito.get("completada", 0.0) > 0.05)
        _gravar_json(arquivo_feitas, feitas)
    return resumo


def amostra(falas: list[FalaJogo], pasta_saida: str | Path, destino: str | Path, quantas: int = 5,
            exato: bool = True) -> Path | None:
    """Um WAV para ouvir: de cada uma das primeiras falas dubladas, a original e logo depois a dublada."""
    pares = []
    for fala in falas:
        dublada = destino_da_fala(fala, pasta_saida, exato)
        if fala.formato is not None and dublada.is_file():
            pares.append((fala.arquivo, dublada))
        if len(pares) >= quantas:
            break
    if not pares:
        return None
    taxa, partes = 24000, []
    silencio = np.zeros(int(0.5 * taxa), dtype=np.float32)
    for original, dublada in pares:
        for arquivo in (original, dublada):
            try:
                som, t = audio_jogo.ler_som(arquivo)
            except (audio_jogo.ErroAudioJogo, OSError, ValueError):
                continue
            if t != taxa and len(som):
                som = np.interp(np.arange(int(len(som) * taxa / t)) * t / taxa, np.arange(len(som)), som)
            partes += [som.astype(np.float32), silencio]
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(destino), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(taxa)
        w.writeframes(np.clip(np.rint(np.concatenate(partes) * 32767), -32768, 32767).astype("<i2").tobytes())
    return destino


# ----------------------------------------------------------------- entregar
def entregar(roteiro: Roteiro | None, falas: list[FalaJogo], pasta_saida: str | Path) -> list[Path]:
    """roteiro_ptbr (as mesmas colunas do original), falas_ouvidas.csv (as que o Whisper ouviu, para revisar) e o
    relatório. As vozes já estão em audio_ptbr\\ (com os mesmos nomes de arquivo)."""
    pasta_saida = Path(pasta_saida)
    pasta_saida.mkdir(parents=True, exist_ok=True)
    feitos = []
    if roteiro is not None and roteiro.traduzidas():
        feitos.append(gravar_roteiro(roteiro, pasta_saida / f"{roteiro.arquivo.stem}_ptbr{roteiro.arquivo.suffix}"))
    ouvidas = [f for f in falas if f.ouvida]
    if ouvidas:
        import csv
        arquivo = pasta_saida / "falas_ouvidas.csv"
        with open(arquivo, "w", encoding="utf-8-sig", newline="") as saida:
            escritor = csv.writer(saida, delimiter=";")
            escritor.writerow(["arquivo", "original (ouvido pelo Whisper)", "tradução", "voz", "conferir"])
            for f in ouvidas:
                escritor.writerow([f.relativo, f.texto, f.traducao, f.voz, "; ".join(f.avisos)])
        feitos.append(arquivo)
    linhas = ["Tradução e dublagem do jogo (Maestro)", ""]
    if roteiro is not None:
        linhas += [f"Roteiro: {roteiro.arquivo.name} · {len(roteiro.com_texto)} textos · {roteiro.traduzidas()} "
                   f"traduzidos · {roteiro.ajustes()} para conferir"]
    dubladas = [f for f in falas if f.feito]
    linhas += [f"Vozes: {len(falas)} falas gravadas · {len(dubladas)} dubladas (em {PASTA_SAIDA_AUDIO}\\, com os "
               "mesmos nomes de arquivo)", ""]
    conferir = [(e.chave, e.texto, e.traducao, "; ".join(e.avisos)) for e in (roteiro.entradas if roteiro else [])
                if e.avisos]
    conferir += [(f.relativo, f.texto, f.traducao, "; ".join(f.avisos)) for f in ouvidas if f.avisos]
    if conferir:
        linhas.append("Para conferir (a tradução passou do espaço do jogo ou perdeu um código):")
        linhas += [f"  {chave}: \"{texto}\" -> \"{traducao}\" ({aviso})" for chave, texto, traducao, aviso in conferir]
        linhas.append("")
    cortadas = [f for f in dubladas if f.feito.get("cortada", 0) > 0]
    if cortadas:
        linhas.append("Falas dubladas que não couberam no tempo da original (cortadas no fim: encurte o texto e "
                      "duble de novo):")
        linhas += [f"  {f.relativo}: sobraram {f.feito['cortada']:.2f} s".replace(".", ",") for f in cortadas]
        linhas.append("")
    linhas += ["Próximo passo: a ferramenta do jogo põe roteiro_ptbr e audio_ptbr de volta numa CÓPIA da ISO (ou o "
               "Maestro, se as falas saíram da ISO por ele: \"Montar a ISO em português\"). Depois, \"Criar o patch "
               "(.xdelta)\" para compartilhar sem compartilhar o jogo."]
    relatorio = pasta_saida / "relatorio_traducao.txt"
    relatorio.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    feitos.append(relatorio)
    return feitos
