"""Criar a legenda a partir do ÁUDIO: o Whisper ouve (no seu PC) e o Claude traduz.

Para que serve: o vídeo não tem NENHUMA legenda (nem em outro idioma) e por isso o "Traduzir legendas com IA" não
tem de onde partir. Aqui o próprio áudio vira legenda:

    Filme (2003).mkv  --Whisper, no PC-->  Filme (2003).en.srt  --Claude-->  Filme (2003).pt-BR.srt
                      (se o áudio já é português, sai direto o Filme (2003).pt-BR.srt, sem gastar com a API)

O Whisper (faster-whisper, código aberto) roda no seu computador: grátis, mas demora (o processador trabalha bastante;
com uma placa de vídeo NVIDIA é bem mais rápido). Na 1ª vez ele baixa o modelo escolhido (de dezenas de MB no "tiny"
a mais de 1 GB no "large-v3") e guarda para as próximas.

Ele devolve trechos com o horário de cada PALAVRA; o programa monta falas do tamanho de uma legenda (no máximo 2
linhas de 42 letras e 6 segundos), cortando de preferência no fim de uma frase ou numa pausa.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from .legendas import nome_do_idioma
from .nomes import eh_video_da_biblioteca
from .traducao import _PORTUGUES, MAX_LINHA, Fala, ErroTraducao, gerar_srt, quebrar_linhas, traduzir_arquivo

MODELOS = ("tiny", "base", "small", "medium", "large-v3", "turbo")
MODELO_PADRAO = "small"            # bom equilíbrio entre acerto e tempo no processador
MAX_CARACTERES = 2 * MAX_LINHA     # 2 linhas por fala
MAX_DURACAO = 6.0                  # segundos que uma fala fica na tela, no máximo
PAUSA = 0.8                        # silêncio entre palavras que vira um corte de fala
LETRAS_POR_SEGUNDO = 6             # média de um filme (só para a estimativa de custo da tradução)
EXTENSOES_LEGENDA = (".srt", ".ass", ".ssa", ".vtt", ".sub", ".idx")
MARCA_DUBLADO = " - Dublado IA"    # versões dubladas (fase 2): não são legendadas de novo


class ErroTranscricao(Exception):
    """Mensagem já em português, pronta para mostrar."""


# ----------------------------------------------------------------- trechos do Whisper -> falas de legenda
def tempo_srt(segundos: float) -> str:
    ms = max(0, int(round(segundos * 1000)))
    return f"{ms // 3_600_000:02d}:{ms // 60_000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def _fecha_frase(palavra: str) -> bool:
    return palavra.rstrip().endswith((".", "?", "!", "…", '."', '?"', '!"'))


def falas_dos_segmentos(segmentos) -> list[Fala]:
    """Trechos do Whisper (com .start, .end, .text e .words) -> falas do tamanho de uma legenda."""
    falas: list[Fala] = []

    def fechar(bloco):
        texto = "".join(p.word for p in bloco).strip()
        if texto:
            falas.append(Fala(f"{tempo_srt(bloco[0].start)} --> {tempo_srt(bloco[-1].end)}", quebrar_linhas(texto)))

    for s in segmentos:
        palavras = [p for p in (getattr(s, "words", None) or []) if p.word.strip()]
        if not palavras:                                     # sem horário por palavra: divide por frases
            partes = [p for p in re.split(r"(?<=[.?!…])\s+", " ".join(s.text.split())) if p] or []
            total = sum(len(p) for p in partes) or 1
            inicio = s.start
            for p in partes:
                fim = inicio + (s.end - s.start) * len(p) / total
                falas.append(Fala(f"{tempo_srt(inicio)} --> {tempo_srt(fim)}", quebrar_linhas(p)))
                inicio = fim
            continue
        bloco = []
        for p in palavras:
            if bloco:
                tamanho = len("".join(x.word for x in bloco + [p]).strip())
                if (tamanho > MAX_CARACTERES or p.end - bloco[0].start > MAX_DURACAO
                        or p.start - bloco[-1].end > PAUSA
                        or (_fecha_frase(bloco[-1].word) and tamanho > MAX_LINHA)):
                    fechar(bloco)
                    bloco = []
            bloco.append(p)
        if bloco:
            fechar(bloco)
    return falas


# ----------------------------------------------------------------- o Whisper
@dataclass
class Transcritor:
    modelo: str = MODELO_PADRAO
    usar_gpu: bool = False
    pasta_modelos: str | None = None   # onde os modelos ficam guardados (None = a pasta padrão do Hugging Face)
    motor: object = None               # o WhisperModel (nos testes, um falso)
    aviso: str = ""                    # ex.: "sem placa de vídeo: usando o processador"

    def _abrir(self, gpu: bool):
        try:
            from faster_whisper import WhisperModel
        except ImportError as erro:
            raise ErroTranscricao("falta a biblioteca faster-whisper (pip install faster-whisper)") from erro
        try:
            return WhisperModel(self.modelo, device="cuda" if gpu else "cpu",
                                compute_type="float16" if gpu else "int8", download_root=self.pasta_modelos)
        except Exception as erro:          # sem internet na 1ª vez, disco cheio, nome de modelo errado...
            if gpu:
                raise
            raise ErroTranscricao(f"não deu para carregar o modelo \"{self.modelo}\" do Whisper (na 1ª vez ele é "
                                  f"baixado da internet): {str(erro)[:200]}") from erro

    def _carregar(self) -> None:
        if self.motor is not None:
            return
        if self.usar_gpu:
            try:
                self.motor = self._abrir(gpu=True)
                return
            except ErroTranscricao:
                raise
            except Exception as erro:
                self.aviso = f"placa de vídeo indisponível ({str(erro)[:80]}): usando o processador"
                self.usar_gpu = False
        self.motor = self._abrir(gpu=False)

    def transcrever(self, video: str | Path, idioma: str | None = None, parar=None,
                    ao_progresso=None) -> tuple[str, float, list[Fala]]:
        """(idioma do áudio, duração em segundos, falas). ao_progresso(fração 0-1) a cada trecho ouvido."""
        self._carregar()
        try:
            segmentos, info = self.motor.transcribe(str(video), language=idioma, vad_filter=True,
                                                    word_timestamps=True, beam_size=5)
            ouvidos = []
            for s in segmentos:                         # o Whisper trabalha enquanto os trechos são lidos
                if parar and parar():
                    raise ErroTranscricao("interrompido (botão Parar)")
                ouvidos.append(s)
                if ao_progresso and info.duration:
                    ao_progresso(min(s.end / info.duration, 1.0))
        except ErroTranscricao:
            raise
        except Exception as erro:
            if self.usar_gpu:                           # a placa só falha na hora de usar (falta cuDNN...)
                self.aviso = f"placa de vídeo falhou ({str(erro)[:80]}): usando o processador"
                self.usar_gpu, self.motor = False, None
                return self.transcrever(video, idioma, parar, ao_progresso)
            raise ErroTranscricao(f"não deu para ouvir o áudio: {str(erro)[:200]}") from erro
        return (info.language or "").lower(), float(info.duration or 0), falas_dos_segmentos(ouvidos)


# ----------------------------------------------------------------- o que legendar na biblioteca
@dataclass
class SemLegenda:
    video: Path
    duracao: float | None = None       # segundos (None = não deu para ler)


def sondar(video: Path) -> tuple[float | None, set[str]]:
    """(duração em segundos, idiomas das legendas DENTRO do arquivo). Sem o PyAV ou arquivo ruim: (None, {})."""
    try:
        import av
        with av.open(str(video)) as arquivo:
            duracao = arquivo.duration / 1_000_000 if arquivo.duration else None
            idiomas = {(s.metadata.get("language") or "").lower() for s in arquivo.streams.subtitles}
        return duracao, idiomas
    except Exception:
        return None, set()


def videos_sem_legenda(*pastas, idioma: str = "pt-BR", sondar_arquivo=sondar) -> list[SemLegenda]:
    """Os vídeos das bibliotecas SEM nenhuma legenda ao lado (nem em outro idioma: essas o "Traduzir legendas" já
    resolve) e sem legenda embutida no idioma pedido."""
    alvo = {idioma.lower(), idioma.lower().split("-")[0]} | (_PORTUGUES if idioma.lower().startswith("pt") else set())
    achados, vistos = [], set()
    for pasta in pastas:
        if not pasta or not Path(pasta).is_dir():
            continue
        for video in sorted(Path(pasta).rglob("*")):
            if ".organizador" in video.parts or not video.is_file() or not eh_video_da_biblioteca(video):
                continue
            if video.stem.endswith(MARCA_DUBLADO) or (chave := str(video.resolve()).lower()) in vistos:
                continue
            vistos.add(chave)
            if any(a.is_file() and a.name.startswith(video.stem + ".") and a.suffix.lower() in EXTENSOES_LEGENDA
                   for a in video.parent.iterdir()):
                continue
            duracao, embutidas = sondar_arquivo(video)
            if embutidas & alvo:
                continue
            achados.append(SemLegenda(video, duracao))
    return achados


def estimar(itens: list[SemLegenda]) -> tuple[float, int, int]:
    """(horas de áudio, letras e falas prováveis), para a estimativa de custo da tradução."""
    segundos = sum(i.duracao or 0 for i in itens)
    return segundos / 3600, int(segundos * LETRAS_POR_SEGUNDO), int(segundos / 3.5)


# ----------------------------------------------------------------- um vídeo
@dataclass
class ResultadoAudio:
    video: Path
    status: str                        # "criada", "traduzida", "so_original", "ja_existe", "sem_fala", "erro"
    detalhe: str = ""
    idioma_audio: str = ""
    original: Path | None = None       # a legenda no idioma do áudio ('Nome.en.srt')
    destino: Path | None = None        # a legenda no idioma pedido ('Nome.pt-BR.srt')
    falas: int = 0
    segundos: float = 0.0              # quanto tempo levou
    avisos: list[str] = field(default_factory=list)


def legendar_pelo_audio(video: str | Path, transcritor: Transcritor, tradutor=None, idioma: str = "pt-BR",
                        parar=None, ao_progresso=None) -> ResultadoAudio:
    """Ouve o vídeo e grava a legenda. Se o áudio não está no idioma pedido e há tradutor, traduz com o Claude.
    Nunca sobrescreve uma legenda que já existe."""
    video = Path(video)
    destino = video.with_name(f"{video.stem}.{idioma}.srt")
    if destino.exists():
        return ResultadoAudio(video, "ja_existe", "a legenda já existe", destino=destino)
    inicio = time.monotonic()
    fatia = 0.8 if tradutor is not None else 1.0         # a tradução fica com o fim da barra

    def andamento(fracao: float) -> None:
        if ao_progresso:
            ao_progresso(fracao)
    try:
        lingua, _, falas = transcritor.transcrever(video, parar=parar, ao_progresso=lambda f: andamento(f * fatia))
    except ErroTranscricao as erro:
        return ResultadoAudio(video, "erro", str(erro), avisos=[transcritor.aviso] if transcritor.aviso else [])
    r = ResultadoAudio(video, "sem_fala", "nenhuma fala reconhecida no áudio", lingua, falas=len(falas),
                       avisos=[transcritor.aviso] if transcritor.aviso else [])
    if not falas:
        return r
    no_idioma = lingua in {idioma.lower(), idioma.lower().split("-")[0]} or (
        idioma.lower().startswith("pt") and lingua in _PORTUGUES)
    original = destino if no_idioma else video.with_name(f"{video.stem}.{lingua or 'und'}.srt")
    try:
        if not original.exists():
            parcial = original.with_name(original.name + ".part")
            parcial.write_text(gerar_srt(falas), encoding="utf-8")
            parcial.replace(original)
    except OSError as erro:
        r.status, r.detalhe = "erro", f"não deu para gravar a legenda: {erro}"
        return r
    r.original, r.segundos = original, time.monotonic() - inicio
    if no_idioma:
        r.status, r.detalhe, r.destino = "criada", "", destino
    elif tradutor is None:
        r.status, r.detalhe = "so_original", f"legenda em {nome_do_idioma(lingua) or lingua} (sem tradução)"
    else:
        t = traduzir_arquivo(original, destino, tradutor, titulo=video.stem, parar=parar,
                             ao_progresso=lambda feitas, todas: andamento(fatia + (1 - fatia) * feitas / max(todas, 1)))
        r.status = {"traduzida": "traduzida", "ja_existe": "ja_existe"}.get(t.status, "erro")
        r.detalhe = t.detalhe if r.status == "erro" else ""
        r.destino = destino if r.status != "erro" else None
    r.segundos = time.monotonic() - inicio
    andamento(1.0)
    return r


__all__ = ["MODELOS", "MODELO_PADRAO", "ErroTranscricao", "ErroTraducao", "ResultadoAudio", "SemLegenda",
           "Transcritor", "estimar", "falas_dos_segmentos", "legendar_pelo_audio", "quebrar_linhas", "sondar",
           "tempo_srt", "videos_sem_legenda"]
