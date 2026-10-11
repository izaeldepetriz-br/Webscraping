"""Dublagem por IA (voz sintética): a legenda em português é LIDA por uma voz do Piper e vira uma faixa de áudio nova.

    Filme (2003).pt-BR.srt  --Piper, no PC-->  um .wav por fala  --ffmpeg-->  Filme (2003) - Dublado IA.mkv

Como fica: estilo "voice-over" de documentário. A voz original continua lá, mais baixa enquanto a dublada fala (o
ffmpeg abaixa sozinho, como um DJ que abaixa a música quando fala no microfone). A boca dos atores não acompanha.

O que o programa faz:
  1. Piper (código aberto, roda no PC, sem custo): lê cada fala da legenda e grava um .wav. Na 1ª vez baixa o
     programa do Piper (GitHub, ~25 MB) e a voz escolhida (~60 MB). Vozes GENÉRICAS: nada de imitar a voz de atores.
  2. Monta uma trilha do tamanho do filme: cada fala começa no horário da legenda. Fala que não cabe no tempo dela
     é REESCRITA mais curta pela IA (opcional, ver adaptacao.py: como um tradutor de dublagem) e lida de novo; se
     ainda passar, é acelerada um pouco (até ACELERAR_MAX) e, por último, cortada quando a próxima começa.
  3. ffmpeg: grava 'Nome - Dublado IA.mkv' com o vídeo COPIADO (sem perder qualidade), a faixa dublada como a 1ª
     e padrão, e o áudio original logo depois. O arquivo original não é tocado. O Jellyfin mostra os dois como
     VERSÕES do mesmo filme ("Dublado IA" aparece na escolha de versão).

Por isso só FILMES por enquanto: em séries, a versão nova apareceria como um episódio repetido.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import wave
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from .legendas import ErroLegenda, extrair_srt
from .nomes import eh_video_da_biblioteca
from .traducao import _PORTUGUES, ler_srt
from .transcricao import MARCA_DUBLADO

VERSAO_PIPER = "2023.11.14-2"
URL_PIPER = "https://github.com/rhasspy/piper/releases/download/" + VERSAO_PIPER + "/"
ARQUIVOS_PIPER = {"win32": "piper_windows_amd64.zip", "linux": "piper_linux_x86_64.tar.gz",
                  "darwin": "piper_macos_x64.tar.gz"}
URL_VOZES = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/"
VOZES = {"faber": "pt/pt_BR/faber/medium/pt_BR-faber-medium",          # masculina, qualidade média
         "edresson": "pt/pt_BR/edresson/low/pt_BR-edresson-low"}       # masculina, mais leve
VOZ_PADRAO = "faber"
ACELERAR_MAX = 1.35          # fala longa: até 35% mais rápida (mais que isso fica difícil de entender)
FOLGA = 0.3                  # segundos que uma fala pode invadir a próxima antes de ser cortada
SEM_JANELA = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


class ErroDublagem(Exception):
    """Mensagem já em português, pronta para mostrar."""


def localizar_ffmpeg() -> str | None:
    """O ffmpeg do sistema; se não houver, o que vem no pacote imageio-ffmpeg."""
    caminho = shutil.which("ffmpeg")
    if caminho:
        return caminho
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


# ----------------------------------------------------------------- baixar o Piper e a voz (só na 1ª vez)
def _baixar(url: str, destino: Path, ao_progresso=None) -> None:
    import requests
    parcial = destino.with_name(destino.name + ".part")
    try:
        with requests.get(url, stream=True, timeout=60) as r:
            if r.status_code != 200:
                raise ErroDublagem(f"não deu para baixar {url.rsplit('/', 1)[-1]} (HTTP {r.status_code})")
            total, feito = int(r.headers.get("Content-Length") or 0), 0
            with open(parcial, "wb") as saida:
                for bloco in r.iter_content(1 << 16):
                    saida.write(bloco)
                    feito += len(bloco)
                    if ao_progresso and total:
                        ao_progresso(feito / total)
        parcial.replace(destino)
    except requests.RequestException as erro:
        raise ErroDublagem(f"sem conexão para baixar {url.rsplit('/', 1)[-1]}: {erro}") from erro
    finally:
        parcial.unlink(missing_ok=True)


def executavel_piper(pasta: str | Path, sistema: str = sys.platform) -> Path:
    return Path(pasta) / "piper" / ("piper.exe" if sistema == "win32" else "piper")


def preparar_piper(pasta: str | Path, sistema: str = sys.platform, baixar=_baixar, ao_progresso=None) -> Path:
    """O programa do Piper (baixa e extrai na 1ª vez). Devolve o caminho do executável."""
    exe = executavel_piper(pasta, sistema)
    if exe.is_file():
        return exe
    arquivo = ARQUIVOS_PIPER.get(sistema)
    if not arquivo:
        raise ErroDublagem(f"o Piper não tem versão pronta para este sistema ({sistema})")
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    pacote = pasta / arquivo
    baixar(URL_PIPER + arquivo, pacote, ao_progresso)
    try:
        if arquivo.endswith(".zip"):
            with zipfile.ZipFile(pacote) as z:
                z.extractall(pasta)
        else:
            with tarfile.open(pacote) as t:
                t.extractall(pasta, filter="data")
    except (OSError, zipfile.BadZipFile, tarfile.TarError) as erro:
        raise ErroDublagem(f"o pacote do Piper veio com defeito: {erro}") from erro
    finally:
        pacote.unlink(missing_ok=True)
    if not exe.is_file():
        raise ErroDublagem("o pacote do Piper não tinha o programa esperado")
    if sistema != "win32":
        exe.chmod(0o755)
    return exe


def preparar_voz(nome: str, pasta: str | Path, baixar=_baixar, ao_progresso=None) -> Path:
    """O modelo da voz (.onnx + .onnx.json; baixa na 1ª vez). Devolve o caminho do .onnx."""
    if nome not in VOZES:
        raise ErroDublagem(f"voz desconhecida: {nome} (opções: {', '.join(VOZES)})")
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    modelo = pasta / (VOZES[nome].rsplit("/", 1)[-1] + ".onnx")
    for alvo, url in ((modelo.with_name(modelo.name + ".json"), URL_VOZES + VOZES[nome] + ".onnx.json"),
                      (modelo, URL_VOZES + VOZES[nome] + ".onnx")):
        if not alvo.is_file():
            baixar(url, alvo, ao_progresso)
    return modelo


def voz_pronta(nome: str, pasta_piper: str | Path, pasta_vozes: str | Path) -> bool:
    """O Piper e a voz já estão no PC? (senão, são baixados na 1ª dublagem)"""
    if nome not in VOZES or not executavel_piper(pasta_piper).is_file():
        return False
    modelo = Path(pasta_vozes) / (VOZES[nome].rsplit("/", 1)[-1] + ".onnx")
    return modelo.is_file() and modelo.with_name(modelo.name + ".json").is_file()


# ----------------------------------------------------------------- falar (texto -> .wav)
def texto_para_falar(texto: str) -> str:
    """Tira o que é só de legenda: <i>, {\\an8}, ♪, travessão de diálogo, [risos], quebras de linha."""
    texto = re.sub(r"<[^>]+>|\{[^}]*\}|\[[^\]]*\]|\([^)]*\)|[♪♫#]", " ", texto)
    texto = re.sub(r"(^|\n)\s*[-–—]\s*", r"\1", texto)
    return " ".join(texto.split())


class MotorPiper:
    """Chama o programa do Piper: uma vez só para todas as falas (o modelo da voz carrega uma vez)."""

    def __init__(self, executavel: str | Path, modelo: str | Path):
        self.executavel, self.modelo = str(executavel), str(modelo)

    def _rodar(self, argumentos: list[str], entrada: str, timeout: float) -> subprocess.CompletedProcess:
        return subprocess.run([self.executavel, "--model", self.modelo, *argumentos], input=entrada.encode("utf-8"),
                              capture_output=True, timeout=timeout, cwd=str(Path(self.executavel).parent), **SEM_JANELA)

    def sintetizar(self, pedidos: list[tuple[str, Path]], parar=None, ao_progresso=None) -> None:
        """pedidos: [(texto, .wav de destino)]. Em lotes de 50 (dá para acompanhar e parar no meio)."""
        lote = 50
        for i in range(0, len(pedidos), lote):
            if parar and parar():
                raise ErroDublagem("interrompido (botão Parar)")
            parte = pedidos[i:i + lote]
            parte = [(p[0], p[1]) for p in parte]           # (texto, wav[, voz]): o Piper usa a voz do modelo dele
            linhas = "\n".join(json.dumps({"text": t, "output_file": str(w)}, ensure_ascii=False) for t, w in parte)
            r = self._rodar(["--json-input"], linhas + "\n", timeout=60 + 20 * len(parte))
            faltando = [(t, w) for t, w in parte if not Path(w).is_file()]
            for texto, wav in faltando:                       # versão que não aceita --json-input: uma por vez
                r = self._rodar(["--output_file", str(wav)], texto + "\n", timeout=120)
                if not Path(wav).is_file():
                    detalhe = (r.stderr or b"").decode("utf-8", "replace").strip()[-300:]
                    raise ErroDublagem(f"o Piper não gerou a voz ({detalhe or f'código {r.returncode}'})")
            if ao_progresso:
                ao_progresso(min(i + lote, len(pedidos)) / len(pedidos))


# ----------------------------------------------------------------- montar a trilha (todas as falas no horário)
def _segundos(tempo: str) -> float:
    h, m, resto = tempo.strip().replace(".", ",").split(":")
    s, ms = resto.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")[:3]) / 1000


def horarios(tempo: str) -> tuple[float, float]:
    ini, fim = tempo.split("-->")
    return _segundos(ini), _segundos(fim)


def acelerar_com_ffmpeg(ffmpeg: str):
    """Devolve a função que acelera um .wav (sem mudar o tom da voz: filtro atempo)."""
    def acelerar(wav: Path, fator: float) -> Path:
        saida = wav.with_name(wav.stem + "-rapido.wav")
        subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(wav),
                        "-filter:a", f"atempo={fator:.3f}", str(saida)], capture_output=True, **SEM_JANELA)
        return saida if saida.is_file() else wav
    return acelerar


def vagas(clipes: list[tuple[float, float, Path]], duracao: float) -> list[float]:
    """Quanto tempo cada fala tem: do início dela até a próxima começar (ou até o fim da legenda, se for mais)."""
    return [max((clipes[k + 1][0] if k + 1 < len(clipes) else max(duracao, fim)) - inicio, fim - inicio, 0.2)
            for k, (inicio, fim, _) in enumerate(clipes)]


def duracao_wav(wav: Path) -> float:
    with wave.open(str(wav), "rb") as w:
        return w.getnframes() / w.getframerate()


def reamostrar_com_ffmpeg(ffmpeg: str):
    """Devolve a função que converte um .wav para outra taxa (mono, 16 bits): na dublagem mista, as falas do Piper
    (22.050 ou 16.000 Hz) e as do Gemini (24.000 Hz) entram na mesma trilha."""
    def reamostrar(wav: Path, taxa: int) -> Path:
        saida = wav.with_name(f"{wav.stem}-{taxa}.wav")
        if not saida.is_file():
            subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(wav), "-ac", "1",
                            "-ar", str(taxa), "-sample_fmt", "s16", str(saida)], capture_output=True, **SEM_JANELA)
        return saida if saida.is_file() else wav
    return reamostrar


PREFIXO_PIPER = "piper:"      # voz de uma fala na dublagem mista: "piper:faber" = essa fala vai para o Piper


class MotorMisto:
    """Dublagem mista: as falas com voz "piper:..." (figurantes) vão para o Piper, grátis; as outras para o motor
    premium (Gemini). piper(voz) devolve o MotorPiper daquela voz (preparado só quando aparece)."""

    def __init__(self, premium, piper):
        self.premium, self._fabrica, self._pipers = premium, piper, {}

    @property
    def pedidos(self) -> int:
        return getattr(self.premium, "pedidos", 0)

    def sintetizar(self, pedidos: list, parar=None, ao_progresso=None) -> None:
        def voz(p):
            return p[2] if len(p) > 2 and p[2] else ""
        baratos: dict[str, list] = {}
        for p in pedidos:
            if voz(p).startswith(PREFIXO_PIPER):
                baratos.setdefault(voz(p)[len(PREFIXO_PIPER):], []).append((p[0], p[1]))
        for nome, lista in baratos.items():
            if nome not in self._pipers:
                self._pipers[nome] = self._fabrica(nome)
            self._pipers[nome].sintetizar(lista, parar=parar)
        caros = [p for p in pedidos if not voz(p).startswith(PREFIXO_PIPER)]
        if caros:
            self.premium.sintetizar(caros, parar=parar, ao_progresso=ao_progresso)
        elif ao_progresso:
            ao_progresso(1.0)


def montar_trilha(clipes: list[tuple[float, float, Path]], duracao: float, destino: Path, acelerar=None,
                  reamostrar=None) -> dict:
    """clipes: [(início, fim da fala na legenda, .wav)] em ordem. Grava 'destino' (mono, 16 bits) do tamanho do
    vídeo, com cada fala no horário. Devolve {"aceleradas": n, "cortadas": n}. reamostrar(wav, taxa): converte a
    fala que vier noutra taxa (dublagem mista); sem ele, taxas diferentes são erro."""
    contas = {"aceleradas": 0, "cortadas": 0}
    if not clipes:
        raise ErroDublagem("nenhuma fala para montar a trilha")
    with wave.open(str(clipes[0][2]), "rb") as primeiro:
        taxa, largura = primeiro.getframerate(), primeiro.getsampwidth()
    if reamostrar is not None:                               # mista: a trilha fica na MELHOR taxa entre as falas
        for _, _, wav in clipes:
            with wave.open(str(wav), "rb") as w:
                taxa = max(taxa, w.getframerate())
    silencio_1s = b"\0" * taxa * largura
    with wave.open(str(destino), "wb") as saida:
        saida.setnchannels(1)
        saida.setsampwidth(largura)
        saida.setframerate(taxa)
        cursor = 0                                            # em amostras

        def silencio(n: int) -> None:
            while n > 0:
                pedaco = min(n, taxa)
                saida.writeframes(silencio_1s[:pedaco * largura])
                n -= pedaco

        for k, ((inicio, fim, wav), vaga) in enumerate(zip(clipes, vagas(clipes, duracao))):
            proximo = clipes[k + 1][0] if k + 1 < len(clipes) else max(duracao, fim)
            with wave.open(str(wav), "rb") as w:
                n, taxa_fala = w.getnframes(), w.getframerate()
            if taxa_fala != taxa and reamostrar is not None:
                wav = reamostrar(Path(wav), taxa)
                with wave.open(str(wav), "rb") as w:
                    n = w.getnframes()
            if n / taxa > vaga and acelerar is not None:
                fator = min(n / taxa / vaga, ACELERAR_MAX)
                if fator > 1.02:
                    wav = acelerar(Path(wav), fator)
                    contas["aceleradas"] += 1
            with wave.open(str(wav), "rb") as w:
                if w.getframerate() != taxa or w.getnchannels() != 1:
                    raise ErroDublagem("as falas vieram em formatos diferentes")
                amostras = w.readframes(w.getnframes())
            comeco = max(int(inicio * taxa), cursor)
            limite = int((proximo + FOLGA) * taxa) - comeco
            if len(amostras) // largura > limite > 0:
                amostras = amostras[:limite * largura]
                contas["cortadas"] += 1
            silencio(comeco - cursor)
            saida.writeframes(amostras)
            cursor = comeco + len(amostras) // largura
        silencio(int(duracao * taxa) - cursor)
    return contas


# ----------------------------------------------------------------- juntar ao vídeo
def faixas_de_audio(video: Path) -> tuple[float | None, list[str]]:
    """(duração, idiomas das faixas de áudio). Sem o PyAV: (None, [""]) = supõe uma faixa sem idioma."""
    try:
        import av
        with av.open(str(video)) as arquivo:
            duracao = arquivo.duration / 1_000_000 if arquivo.duration else None
            return duracao, [(s.metadata.get("language") or "").lower() for s in arquivo.streams.audio]
    except Exception:
        return None, [""]


FILTRO_VOICE_OVER = ("[0:a:0]aresample=48000,aformat=channel_layouts=stereo[orig];"
                     "[1:a]aresample=48000,aformat=channel_layouts=stereo,volume=1.5,asplit=2[voz][chave];"
                     "[orig][chave]sidechaincompress=threshold=0.02:ratio=8:attack=20:release=400[abaixada];"
                     "[abaixada][voz]amix=inputs=2:duration=first:normalize=0[dub]")
# Com as vozes originais separadas: a dublagem entra sobre a música e os efeitos (o fundo só abaixa um pouco)
FILTRO_SEM_VOZES = ("[2:a]aresample=48000,aformat=channel_layouts=stereo[fundo];"
                    "[1:a]aresample=48000,aformat=channel_layouts=stereo,volume=1.5,asplit=2[voz][chave];"
                    "[fundo][chave]sidechaincompress=threshold=0.05:ratio=3:attack=20:release=300[abaixado];"
                    "[abaixado][voz]amix=inputs=2:duration=first:normalize=0[dub]")
TITULO_LEGENDA = "Português"


def comando_mixar(ffmpeg: str, video: Path, trilha: Path, saida: Path, faixas: int, legendas: bool,
                  trecho: tuple[float, float] | None = None, fundo: Path | None = None,
                  legenda_nova: Path | None = None, formato: str = "matroska") -> list[str]:
    """O comando do ffmpeg: vídeo copiado, a dublagem como 1ª faixa (padrão) e as originais depois.
    trecho (início, fim): só esse pedaço (a AMOSTRA); aí o vídeo é recodificado, para começar no ponto exato e a voz
    não ficar adiantada (copiando, o corte cai no quadro-chave anterior, até alguns segundos antes).
    fundo: a música e os efeitos SEM as vozes originais (separar_vozes): a dublagem fica "de verdade".
    legenda_nova: a legenda em português também entra como faixa (a 1ª legenda do arquivo).
    formato: "matroska" (.mkv) ou "mp4" (o .mp4 original continua .mp4)."""
    corte = ["-ss", f"{trecho[0]:.3f}", "-t", f"{trecho[1] - trecho[0]:.3f}"] if trecho else []
    comando = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", *corte, "-i", str(video), "-i", str(trilha)]
    if fundo:
        comando += ["-i", str(fundo)]
    indice_legenda = 3 if fundo else 2
    if legenda_nova and not trecho:
        comando += ["-i", str(legenda_nova)]
    comando += ["-filter_complex", FILTRO_SEM_VOZES if fundo else FILTRO_VOICE_OVER,
                "-map", "0:v:0?" if trecho else "0:v?", "-map", "[dub]", "-map", "0:a"]
    if legenda_nova and not trecho:
        comando += ["-map", f"{indice_legenda}:0"]           # a nova antes das outras: é a legenda nº 0 do arquivo
    if legendas and not trecho:                     # do .mkv (ou .mp4 -> .mp4) dá para copiar as legendas como estão
        comando += ["-map", "0:s?"] + (["-map", "0:t?"] if formato == "matroska" else [])
    comando += ["-c", "copy"]
    if trecho:
        comando += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23"]
    if formato == "mp4" and (legenda_nova or legendas) and not trecho:
        comando += ["-c:s", "mov_text"]
    comando += ["-c:a:0", "aac", "-b:a:0", "192k",
                "-metadata:s:a:0", "language=por", "-metadata:s:a:0", "title=Português (dublagem IA)",
                "-disposition:a:0", "default"]
    for i in range(faixas):
        comando += [f"-disposition:a:{i + 1}", "0"]
    if legenda_nova and not trecho:
        comando += ["-metadata:s:s:0", "language=por", "-metadata:s:s:0", f"title={TITULO_LEGENDA}",
                    "-disposition:s:0", "0"]               # com a dublagem, a legenda não liga sozinha
    return comando + ["-progress", "pipe:1", "-nostats", "-f", formato, str(saida)]


def _rodar_ffmpeg(comando: list[str], duracao: float | None, parar=None, ao_progresso=None,
                  erro_padrao: str = "o ffmpeg não conseguiu juntar o áudio") -> None:
    processo = subprocess.Popen(comando, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                encoding="utf-8", errors="replace", **SEM_JANELA)
    try:
        for linha in processo.stdout:                 # "out_time_us=12345678" enquanto grava
            if parar and parar():
                processo.kill()
                raise ErroDublagem("interrompido (botão Parar)")
            if linha.startswith("out_time_us=") and ao_progresso and duracao:
                try:
                    ao_progresso(min(int(linha.split("=", 1)[1]) / 1_000_000 / duracao, 1.0))
                except ValueError:
                    pass
        erro = processo.stderr.read()
        if processo.wait() != 0:
            detalhe = erro.strip()[-300:] or (f"o ffmpeg fechou sozinho (código {processo.returncode})"
                                              if processo.returncode < 0 else "sem detalhes")
            raise ErroDublagem(f"{erro_padrao}: {detalhe}")
    finally:
        if processo.poll() is None:
            processo.kill()


def mixar(ffmpeg: str, video: Path, trilha: Path, destino: Path, duracao: float, faixas: int = 1,
          parar=None, ao_progresso=None, trecho: tuple[float, float] | None = None, fundo: Path | None = None,
          legenda_nova: Path | None = None, formato: str = "matroska") -> None:
    parcial = destino.with_name(destino.name + ".part")
    copiar = video.suffix.lower() == ".mkv" or (formato == "mp4" and video.suffix.lower() in MESMO_MP4)
    comando = comando_mixar(ffmpeg, video, trilha, parcial, max(faixas, 1), copiar, trecho, fundo, legenda_nova,
                            formato)
    try:
        _rodar_ffmpeg(comando, duracao, parar, ao_progresso)
        if not parcial.is_file():
            raise ErroDublagem("o ffmpeg não conseguiu juntar o áudio: sem detalhes")
        parcial.replace(destino)
    finally:
        parcial.unlink(missing_ok=True)


# ----------------------------------------------------------------- a faixa DENTRO do arquivo original
MESMO_MP4 = (".mp4", ".m4v", ".mov")        # continuam .mp4/.m4v/.mov; os outros (.avi, .wmv, .ts...) viram .mkv


@dataclass
class Faixas:
    duracao: float | None
    video: int = 0
    audio: int = 0
    legenda: int = 0
    idiomas_audio: list = field(default_factory=list)       # um por faixa ("" = sem idioma marcado)
    idiomas_legenda: list = field(default_factory=list)

    def tem_audio_portugues(self) -> bool:
        return bool(set(self.idiomas_audio) & _PORTUGUES)

    def tem_legenda_portugues(self) -> bool:
        return bool(set(self.idiomas_legenda) & _PORTUGUES)


def inspecionar(ffmpeg: str, arquivo: Path) -> Faixas:
    """Duração e quantas faixas de cada tipo, pelo próprio ffmpeg (sem precisar do ffprobe nem do PyAV)."""
    r = subprocess.run([ffmpeg, "-hide_banner", "-i", str(arquivo)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", **SEM_JANELA)
    texto = r.stderr
    achado = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", texto)
    duracao = (int(achado[1]) * 3600 + int(achado[2]) * 60 + float(achado[3])) if achado else None
    faixas = re.findall(r"Stream #\d+:\d+(?:\[\w+\])?(?:\((\w+)\))?.*?: (Video|Audio|Subtitle):", texto)
    tipos = [tipo for _, tipo in faixas]

    def idiomas(tipo):
        return [("" if idioma == "und" else idioma.lower()) for idioma, t in faixas if t == tipo]
    return Faixas(duracao, tipos.count("Video"), tipos.count("Audio"), tipos.count("Subtitle"),
                  idiomas("Audio"), idiomas("Subtitle"))


def destino_no_original(video: Path) -> tuple[Path, str]:
    """(arquivo final, formato): o .mkv e o .mp4 continuam com o mesmo nome; os outros viram .mkv."""
    if video.suffix.lower() == ".mkv":
        return video, "matroska"
    if video.suffix.lower() in MESMO_MP4:
        return video, "mp4"
    return video.with_suffix(".mkv"), "matroska"


def temporario_no_original(video: Path) -> Path:
    """Onde a cópia é gravada antes de trocar: ao lado, com um nome que o Jellyfin não pega como vídeo."""
    return video.with_name(video.name + ".maestro-tmp")


def trocar_original(ffmpeg: str, video: Path, copia: Path, final: Path, audios_a_mais: int, legendas: int | None,
                    inspecionar_=None) -> Path:
    """Confere a cópia (mesma duração, as faixas de antes e as novas) e só então troca o original por ela.
    legendas: quantas faixas de legenda a cópia deve ter (None: não confere). Se algo não bater, apaga a cópia e o
    original fica como estava."""
    inspecionar_ = inspecionar_ or (lambda arquivo: inspecionar(ffmpeg, arquivo))
    antes, depois = inspecionar_(video), inspecionar_(copia)
    problemas = []
    if antes.duracao is None or depois.duracao is None:
        problemas.append("não deu para ler a duração")
    elif abs(antes.duracao - depois.duracao) > max(2.0, antes.duracao * 0.01):
        problemas.append(f"a duração mudou ({antes.duracao:.0f}s -> {depois.duracao:.0f}s)")
    if depois.video != antes.video:
        problemas.append(f"faixas de vídeo: {antes.video} -> {depois.video}")
    if depois.audio != antes.audio + audios_a_mais:
        problemas.append(f"faixas de áudio: {antes.audio} -> {depois.audio}")
    if legendas is not None and depois.legenda != legendas:
        problemas.append(f"faixas de legenda: {antes.legenda} -> {depois.legenda}")
    if problemas:
        copia.unlink(missing_ok=True)
        raise ErroDublagem("a cópia não ficou igual ao original (" + "; ".join(problemas) + "); o original não foi "
                           "alterado")
    os.replace(copia, final)                       # na mesma pasta: troca de uma vez (nunca fica pela metade)
    if final != video:
        video.unlink(missing_ok=True)              # .avi -> .mkv: o antigo sai (o novo tem tudo dele e a dublagem)
    return final


def aprovar_previa(ffmpeg: str, video: str | Path, previa: str | Path, legenda: str | Path | None = None,
                   parar=None, inspecionar_=None) -> Path:
    """Fase de teste aprovada: a faixa dublada da prévia (a 1ª) entra no ORIGINAL, com a legenda se pedida.
    Só junta (não dubla nem separa as vozes de novo); a cópia é conferida antes de trocar. A prévia é apagada."""
    video, previa = Path(video), Path(previa)
    legenda = Path(legenda) if legenda and Path(legenda).is_file() else None
    if not previa.is_file():
        raise ErroDublagem("a prévia não existe mais (dublar de novo)")
    final, formato = destino_no_original(video)
    copia = temporario_no_original(video)
    copiar = video.suffix.lower() == ".mkv" or (formato == "mp4" and video.suffix.lower() in MESMO_MP4)
    olhar = inspecionar_ or (lambda a: inspecionar(ffmpeg, a))
    antes = olhar(video)
    comando = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(video), "-i", str(previa)]
    if legenda:
        comando += ["-i", str(legenda)]
    comando += ["-map", "0:v?", "-map", "1:a:0", "-map", "0:a"]
    if legenda:
        comando += ["-map", "2:0"]
    if copiar:
        comando += ["-map", "0:s?"] + (["-map", "0:t?"] if formato == "matroska" else [])
    comando += ["-c", "copy"] + (["-c:s", "mov_text"] if formato == "mp4" and (legenda or copiar) else [])
    comando += ["-metadata:s:a:0", "language=por", "-metadata:s:a:0", "title=Português (dublagem IA)",
                "-disposition:a:0", "default"]
    for i in range(antes.audio):
        comando += [f"-disposition:a:{i + 1}", "0"]
    if legenda:
        comando += ["-metadata:s:s:0", "language=por", "-metadata:s:s:0", f"title={TITULO_LEGENDA}",
                    "-disposition:s:0", "0"]
    comando += ["-progress", "pipe:1", "-nostats", "-f", formato, str(copia)]
    try:
        _rodar_ffmpeg(comando, antes.duracao, parar, erro_padrao="o ffmpeg não conseguiu pôr a dublagem no vídeo")
        final = trocar_original(ffmpeg, video, copia, final, 1,
                                (antes.legenda if copiar else 0) + (1 if legenda else 0),
                                lambda a: antes if Path(a) == video else olhar(a))
    finally:
        copia.unlink(missing_ok=True)
    if legenda:
        legenda.unlink(missing_ok=True)            # está dentro do vídeo (senão apareceria duas vezes)
    previa.unlink(missing_ok=True)
    with contextlib.suppress(OSError):
        previa.parent.rmdir()                      # a pasta da prévia, se ficou vazia
    return final


def embutir_legenda(ffmpeg: str, video: str | Path, legenda: str | Path, apagar_srt: bool = True, parar=None,
                    inspecionar_=None) -> Path:
    """Só a legenda (sem dublar): ela entra como faixa 'Português' dentro do próprio vídeo. Devolve o arquivo final.
    apagar_srt: o .srt ao lado sai (está dentro do vídeo; senão o Jellyfin mostraria a mesma legenda duas vezes)."""
    video, legenda = Path(video), Path(legenda)
    final, formato = destino_no_original(video)
    copia = temporario_no_original(video)
    copiar = video.suffix.lower() == ".mkv" or (formato == "mp4" and video.suffix.lower() in MESMO_MP4)
    antes = (inspecionar_ or (lambda a: inspecionar(ffmpeg, a)))(video)
    comando = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(video), "-i", str(legenda),
               "-map", "0:v?", "-map", "0:a?", "-map", "1:0"]
    if copiar:
        comando += ["-map", "0:s?"] + (["-map", "0:t?"] if formato == "matroska" else [])
    comando += ["-c", "copy"] + (["-c:s", "mov_text"] if formato == "mp4" else [])
    comando += ["-metadata:s:s:0", "language=por", "-metadata:s:s:0", f"title={TITULO_LEGENDA}",
                "-disposition:s:0", "default", "-progress", "pipe:1", "-nostats", "-f", formato, str(copia)]
    try:
        _rodar_ffmpeg(comando, antes.duracao, parar, erro_padrao="o ffmpeg não conseguiu pôr a legenda no vídeo")
        trocar_original(ffmpeg, video, copia, final, 0, (antes.legenda if copiar else 0) + 1, inspecionar_)
    finally:
        copia.unlink(missing_ok=True)
    if apagar_srt:
        legenda.unlink(missing_ok=True)
    return final


# ----------------------------------------------------------------- o que dublar na biblioteca
@dataclass
class ParaDublar:
    video: Path
    legenda: Path                  # 'Nome.pt-BR.srt'
    falas: int = 0
    duracao: float | None = None
    tamanho: int = 0               # bytes do vídeo (a versão dublada ocupa quase o mesmo)
    destino: Path | None = None    # onde grava a versão dublada (None = 'Nome - Dublado IA.mkv' ao lado)
    serie: str = ""                # episódio: o nome da série (o elenco e as vozes valem para todos os episódios)


def caminho_dublado(video: Path) -> Path:
    return video.with_name(video.stem + MARCA_DUBLADO + ".mkv")


SUFIXO_SERIES_DUBLADAS = " (Dublado IA)"


def pasta_series_dubladas(raiz_series: str | Path) -> Path:
    """Os episódios dublados ficam numa pasta IRMÃ da biblioteca de séries ('Séries (Dublado IA)'), com as mesmas
    subpastas: na mesma pasta, o Jellyfin mostraria o episódio repetido. No Jellyfin, adicione-a como outra
    biblioteca de séries."""
    raiz = Path(raiz_series)
    return raiz.parent / (raiz.name + SUFIXO_SERIES_DUBLADAS)


def destino_episodio(video: Path, raiz_series: str | Path) -> Path:
    """'Séries/Show/Season 01/Show S01E01.mp4' -> 'Séries (Dublado IA)/Show/Season 01/Show S01E01.mkv'."""
    relativo = Path(video).relative_to(Path(raiz_series))
    return pasta_series_dubladas(raiz_series) / relativo.with_suffix(".mkv")


def nome_da_serie(video: Path, raiz_series: str | Path) -> str:
    """A 1ª pasta dentro da biblioteca de séries ('Show (2010)'); vídeo solto na raiz: o próprio nome."""
    partes = Path(video).relative_to(Path(raiz_series)).parts
    return partes[0] if len(partes) > 1 else Path(video).stem


def episodios_para_dublar(raiz_series: str | Path, idioma: str = "pt-BR", sondar=faixas_de_audio,
                          no_original: bool = False) -> list[ParaDublar]:
    """Os episódios com legenda em português e sem áudio em português, com o destino na pasta irmã e a série.
    no_original: a dublagem vira uma faixa do próprio episódio (não precisa da pasta irmã)."""
    if not raiz_series or not Path(raiz_series).is_dir():
        return []
    itens = videos_para_dublar(raiz_series, idioma=idioma, sondar=sondar, no_original=no_original,
                               destino_de=None if no_original else (lambda v: destino_episodio(v, raiz_series)))
    for item in itens:
        item.serie = nome_da_serie(item.video, raiz_series)
    return itens


def videos_para_dublar(*pastas, idioma: str = "pt-BR", sondar=faixas_de_audio, destino_de=None,
                       no_original: bool = False) -> list[ParaDublar]:
    """Filmes com legenda no idioma pedido, sem versão dublada e sem áudio em português. destino_de(vídeo): onde
    fica a versão dublada (séries: a pasta irmã); sem ele, ao lado ('Nome - Dublado IA.mkv').
    no_original: a dublagem vira uma faixa do próprio vídeo (destino None); "já dublado" = já tem áudio em português."""
    if no_original:
        destino_de = (lambda v: None)
    destino_de = destino_de or caminho_dublado
    portugues = _PORTUGUES | {idioma.lower(), idioma.lower().split("-")[0]}
    achados, vistos = [], set()
    for pasta in pastas:
        if not pasta or not Path(pasta).is_dir():
            continue
        for video in sorted(Path(pasta).rglob("*")):
            if ".organizador" in video.parts or not video.is_file() or not eh_video_da_biblioteca(video):
                continue
            if video.stem.endswith(MARCA_DUBLADO) or (not no_original and destino_de(video).exists()):
                continue
            if (chave := str(video.resolve()).lower()) in vistos:
                continue
            vistos.add(chave)
            legenda = next((video.with_name(f"{video.stem}.{c}.srt") for c in (idioma, "pt-BR", "pt", "por")
                            if video.with_name(f"{video.stem}.{c}.srt").is_file()), None)
            if legenda is None:
                continue
            duracao, idiomas = sondar(video)
            if set(idiomas) & portugues:
                continue                                  # já tem áudio em português
            try:
                falas = sum(1 for f in ler_srt(extrair_srt(legenda.read_bytes())) if texto_para_falar(f.texto))
            except (OSError, ErroLegenda):
                continue
            if falas:
                achados.append(ParaDublar(video, legenda, falas, duracao, video.stat().st_size, destino_de(video)))
    return achados


# ----------------------------------------------------------------- amostra (ouvir antes de pagar o filme inteiro)
AMOSTRA = 60.0                     # segundos


def trecho_de_amostra(falas: list, segundos: float = AMOSTRA) -> tuple[float, float]:
    """(início, fim) do minuto com MAIS falas: a amostra mostra bem a voz, o ritmo e a tradução."""
    inicios = [horarios(f.tempo)[0] for f, _ in falas]
    if not inicios:
        raise ErroDublagem("a legenda não tem nenhuma fala")
    melhor, quantas, fim = inicios[0], 0, 0
    for k, comeco in enumerate(inicios):
        while fim < len(inicios) and inicios[fim] < comeco + segundos:
            fim += 1
        if fim - k > quantas:
            melhor, quantas = comeco, fim - k
    inicio = max(0.0, melhor - 0.5)
    return inicio, inicio + segundos


def caminho_amostra(pasta_cache: str | Path, video: Path) -> Path:
    """A amostra fica junto do progresso guardado do filme (fora da biblioteca: o Jellyfin não a mostra)."""
    return pasta_do_filme(pasta_cache, video) / "amostra.mkv"


# ----------------------------------------------------------------- um filme
@dataclass
class ResultadoDublagem:
    video: Path
    status: str                    # "dublado", "ja_existe", "erro"
    detalhe: str = ""
    destino: Path | None = None
    falas: int = 0
    aceleradas: int = 0
    cortadas: int = 0
    adaptadas: int = 0             # falas que a IA reescreveu mais curtas para caber no tempo
    retomadas: int = 0             # falas que já estavam prontas de uma vez anterior (não pediu de novo)


def falas_da_legenda(legenda: str | Path) -> list:
    """[(Fala, texto para falar)] só das falas com texto: a MESMA lista (e numeração) na dublagem e na voz por
    personagem."""
    falas = [(f, texto_para_falar(f.texto)) for f in ler_srt(extrair_srt(Path(legenda).read_bytes()))]
    return [(f, t) for f, t in falas if t]


def pasta_do_filme(pasta_cache: str | Path, video: str | Path) -> Path:
    """Onde fica o progresso guardado de um filme (as falas já geradas): some quando a dublagem termina."""
    video = Path(video)
    marca = hashlib.sha1(str(video.resolve()).encode("utf-8")).hexdigest()[:8]
    nome = re.sub(r"[^\w() -]", "_", video.stem)[:60]
    return Path(pasta_cache) / f"{nome}-{marca}"


def _nome_wav(k: int, texto: str, voz: str, sufixo: str = "") -> str:
    """O nome muda se o texto ou a voz mudarem: o que foi guardado só é reaproveitado se for o mesmo."""
    return f"{k:05d}{sufixo}-{hashlib.sha1(f'{voz}|{texto}'.encode('utf-8')).hexdigest()[:10]}.wav"


def _pronto(wav: Path) -> bool:
    try:
        with wave.open(str(wav), "rb") as w:
            return w.getnframes() > 0
    except (OSError, EOFError, wave.Error):
        return False


def _sintetizar(motor, pedidos, parar, ao_progresso=None) -> None:
    """Só as falas que ainda não estão prontas; a voz vai junto só quando há uma por personagem."""
    faltando = [(t, w, v) if v else (t, w) for t, w, v in pedidos if not _pronto(w)]
    if faltando:
        motor.sintetizar(faltando, parar=parar, ao_progresso=ao_progresso)


def dublar_video(video: str | Path, legenda: str | Path, motor, ffmpeg: str | None = None,
                 pasta_trabalho: str | Path | None = None, parar=None, ao_progresso=None,
                 sondar=faixas_de_audio, adaptar=None, avisar=None, vozes: dict | None = None,
                 pasta_cache: str | Path | None = None, trecho: tuple[float, float] | None = None,
                 destino: str | Path | None = None, separar=None, no_original: bool = False,
                 legenda_no_video: bool = False, previa: str | Path | None = None) -> ResultadoDublagem:
    """Lê a legenda com a voz, monta a trilha e grava 'Nome - Dublado IA.mkv' (o original não é tocado) ou, com
    no_original, acrescenta a faixa 'Português (dublagem IA)' no PRÓPRIO arquivo (a cópia é conferida antes de trocar).
    separar(vídeo, destino.flac, trecho, duração, parar, ao_progresso): tira as vozes originais (separar_vozes) e a
    dublagem entra sobre a música e os efeitos; sem ele, fica o "voice-over" (o original só abaixa).
    legenda_no_video: a legenda em português também entra como faixa (e o .srt ao lado sai, se for no original).
    previa (com no_original): a FASE DE TESTE. Grava a versão dublada nesse arquivo (fora da biblioteca) e NÃO mexe
    no original; status "previa". Depois de ouvir, aprovar_previa() põe a faixa no original (rápido: não dubla de
    novo) ou a prévia é descartada.
    adaptar([(id, texto, máx. letras, fala anterior)]) -> {id: texto mais curto}: as falas que não cabem no tempo
    são reescritas (ver adaptacao.py) e lidas de novo. Se falhar, segue sem adaptar. avisar(texto): para o log.
    vozes: {número da fala: voz} (uma voz por personagem; ver personagens.py).
    pasta_cache: guarda as falas já geradas (e as reescritas) por filme. Se parar no meio (limite do Gemini, sem
    internet, botão Parar), a próxima vez continua de onde parou, sem pedir (nem pagar) de novo.
    trecho (início, fim) + destino: só as falas desse pedaço, num vídeo curto (a AMOSTRA). As falas ficam no mesmo
    progresso guardado: o filme inteiro, depois, não paga de novo por elas."""
    video, legenda = Path(video), Path(legenda)
    no_original = no_original and not trecho                        # a amostra é sempre um vídeo à parte
    if no_original and previa:                                       # fase de teste: o original não é tocado
        no_original, destino = False, Path(previa)
        Path(previa).unlink(missing_ok=True)                         # uma prévia antiga deste vídeo é refeita
    eh_previa = previa is not None and destino == Path(previa)
    final, formato = destino_no_original(video) if no_original else (None, "matroska")
    destino = (temporario_no_original(video) if no_original else
               Path(destino) if destino else caminho_dublado(video))
    destino.parent.mkdir(parents=True, exist_ok=True)               # episódio: a pasta irmã da série
    if destino.exists() and not trecho and not no_original:
        return ResultadoDublagem(video, "ja_existe", "a versão dublada já existe", destino)
    ffmpeg = ffmpeg or localizar_ffmpeg()
    if not ffmpeg:
        return ResultadoDublagem(video, "erro", "falta o ffmpeg (pip install imageio-ffmpeg)")

    def andamento(fracao: float) -> None:
        if ao_progresso:
            ao_progresso(fracao)
    try:
        falas = falas_da_legenda(legenda)
    except (OSError, ErroLegenda) as erro:
        return ResultadoDublagem(video, "erro", f"não deu para ler a legenda: {erro}")
    if not falas:
        return ResultadoDublagem(video, "erro", "a legenda não tem nenhuma fala")
    duracao, idiomas = sondar(video)
    if not idiomas:
        return ResultadoDublagem(video, "erro", "o vídeo não tem áudio")
    if no_original and set(idiomas) & _PORTUGUES:
        return ResultadoDublagem(video, "ja_existe", "o vídeo já tem áudio em português", video)
    duracao = duracao or horarios(falas[-1][0].tempo)[1] + 2
    vozes = vozes or {}
    indices = list(range(len(falas)))
    inicio = 0.0
    if trecho:
        inicio, duracao = trecho[0], trecho[1] - trecho[0]
        indices = [k for k, (f, _) in enumerate(falas) if trecho[0] <= horarios(f.tempo)[0] < trecho[1]]
        if not indices:
            return ResultadoDublagem(video, "erro", "nenhuma fala nesse trecho")
    if pasta_cache:
        lugar = contextlib.nullcontext(pasta_do_filme(pasta_cache, video))
    else:
        lugar = tempfile.TemporaryDirectory(prefix="maestro-dublagem-", dir=pasta_trabalho)
    with lugar as pasta:
        pasta = Path(pasta)
        pasta.mkdir(parents=True, exist_ok=True)
        pedidos = [(falas[k][1], pasta / _nome_wav(k, falas[k][1], vozes.get(k, "")), vozes.get(k, ""))
                   for k in indices]
        retomadas = sum(1 for _, w, _ in pedidos if _pronto(w))
        # com a separação das vozes, as etapas dividem a barra de outro jeito (separar demora)
        fatias = ((0.4, 0.45, 0.5, 0.8) if separar else (0.5, 0.6, 0.7, 0.7))   # falas, adaptar, trilha, separar
        try:
            _sintetizar(motor, pedidos, parar, lambda f: andamento(fatias[0] * f))
            clipes = [(a - inicio, b - inicio, w) for k, (_, w, _) in zip(indices, pedidos)
                      for a, b in [horarios(falas[k][0].tempo)]]
            adaptadas = 0
            if adaptar is not None:
                clipes, adaptadas = _adaptar(clipes, [t for _, t in falas], duracao, motor, adaptar, parar, avisar,
                                             vozes, pasta, indices)
            andamento(fatias[1])
            contas = montar_trilha(clipes, duracao, pasta / "trilha.wav", acelerar_com_ffmpeg(ffmpeg),
                                   reamostrar_com_ffmpeg(ffmpeg))
            andamento(fatias[2])
            fundo = None
            if separar:
                nome = f"fundo-{int(trecho[0])}-{int(trecho[1])}.flac" if trecho else "fundo.flac"
                fundo = separar(video, pasta / nome, trecho, duracao, parar,
                                lambda f: andamento(fatias[2] + (fatias[3] - fatias[2]) * f))
            andamento(fatias[3])
            antes = inspecionar(ffmpeg, video) if no_original else None
            nova = legenda if legenda_no_video and not trecho else None
            mixar(ffmpeg, video, pasta / "trilha.wav", destino, duracao, len(idiomas), parar,
                  lambda f: andamento(fatias[3] + (1 - fatias[3]) * f), trecho, fundo, nova, formato)
            if no_original:
                copiou = video.suffix.lower() == ".mkv" or (formato == "mp4" and video.suffix.lower() in MESMO_MP4)
                destino = trocar_original(ffmpeg, video, destino, final, 1,
                                          (antes.legenda if copiou else 0) + (1 if nova else 0),
                                          lambda arquivo: antes if arquivo == video else inspecionar(ffmpeg, arquivo))
                if nova:
                    legenda.unlink(missing_ok=True)      # está dentro do vídeo (senão apareceria duas vezes)
        except (ErroDublagem, OSError, wave.Error, subprocess.SubprocessError) as erro:
            if no_original:
                temporario_no_original(video).unlink(missing_ok=True)
            detalhe = str(erro) if isinstance(erro, ErroDublagem) or type(erro).__name__ == "ErroSeparacao" \
                else f"{type(erro).__name__}: {erro}"
            if pasta_cache:
                prontas = sum(1 for _, w, _ in pedidos if _pronto(w))
                detalhe += (f" — {prontas} de {len(pedidos)} falas já prontas e guardadas: dublar de novo continua "
                            "de onde parou")
            return ResultadoDublagem(video, "erro", detalhe, falas=len(falas), retomadas=retomadas)
        if pasta_cache:
            (pasta / "trilha.wav").unlink(missing_ok=True)
    if pasta_cache and not trecho:
        shutil.rmtree(pasta_do_filme(pasta_cache, video), ignore_errors=True)      # pronto: o progresso não serve mais
    andamento(1.0)
    return ResultadoDublagem(video, "previa" if eh_previa else "dublado", "", destino, len(indices),
                             contas["aceleradas"], contas["cortadas"], adaptadas, retomadas)


def _adaptar(clipes, textos, duracao, motor, adaptar, parar, avisar, vozes, pasta, indices=None):
    """Reescreve (IA) as falas que só caberiam muito aceleradas e as lê de novo. Fica a versão que soar MAIS CURTA.
    As reescritas ficam guardadas (adaptadas.json) pelo número da fala NO FILME: ao continuar um filme (ou depois
    de uma amostra), não se paga de novo por elas. indices: o número de cada clipe no filme (amostra)."""
    ids = list(indices) if indices is not None else list(range(len(clipes)))
    posicao = {k: pos for pos, k in enumerate(ids)}
    from .adaptacao import NATURAL, limite_de_letras
    arquivo = Path(pasta) / "adaptadas.json"
    try:
        guardadas = {int(k): v for k, v in json.loads(arquivo.read_text(encoding="utf-8")).items()}
    except (OSError, ValueError):
        guardadas = {}
    longas = []
    for pos, ((_, _, wav), vaga) in enumerate(zip(clipes, vagas(clipes, duracao))):
        k = ids[pos]
        dur = duracao_wav(wav)
        if dur / vaga > NATURAL and k not in guardadas:
            longas.append((k, textos[k], limite_de_letras(textos[k], dur, vaga), textos[k - 1] if k else ""))
    if longas:
        try:
            guardadas.update(adaptar(longas))
        except Exception as erro:                             # sem crédito, sem internet...: segue sem adaptar
            if avisar:
                avisar(f"falas longas não adaptadas ({str(erro)[:150]}): ficam aceleradas como antes")
        try:
            arquivo.write_text(json.dumps(guardadas, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
    if not guardadas:
        return clipes, 0
    usar = [(k, texto) for k, texto in guardadas.items() if k in posicao]
    pedidos = [(texto, Path(pasta) / _nome_wav(k, texto, vozes.get(k, ""), "-curta"), vozes.get(k, ""))
               for k, texto in usar]
    _sintetizar(motor, pedidos, parar)
    clipes, adaptadas = list(clipes), 0
    for (k, _), (_, wav, _) in zip(usar, pedidos):
        pos = posicao[k]
        if _pronto(wav) and duracao_wav(wav) < duracao_wav(clipes[pos][2]):
            clipes[pos] = (clipes[pos][0], clipes[pos][1], wav)
            adaptadas += 1
    return clipes, adaptadas
