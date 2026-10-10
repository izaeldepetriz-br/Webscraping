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
from dataclasses import dataclass
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


def montar_trilha(clipes: list[tuple[float, float, Path]], duracao: float, destino: Path, acelerar=None) -> dict:
    """clipes: [(início, fim da fala na legenda, .wav)] em ordem. Grava 'destino' (mono, 16 bits) do tamanho do
    vídeo, com cada fala no horário. Devolve {"aceleradas": n, "cortadas": n}."""
    contas = {"aceleradas": 0, "cortadas": 0}
    if not clipes:
        raise ErroDublagem("nenhuma fala para montar a trilha")
    with wave.open(str(clipes[0][2]), "rb") as primeiro:
        taxa, largura = primeiro.getframerate(), primeiro.getsampwidth()
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


def comando_mixar(ffmpeg: str, video: Path, trilha: Path, saida: Path, faixas: int, legendas: bool) -> list[str]:
    """O comando do ffmpeg: vídeo copiado, a dublagem como 1ª faixa (padrão) e as originais depois."""
    filtro = ("[0:a:0]aresample=48000,aformat=channel_layouts=stereo[orig];"
              "[1:a]aresample=48000,aformat=channel_layouts=stereo,volume=1.5,asplit=2[voz][chave];"
              "[orig][chave]sidechaincompress=threshold=0.02:ratio=8:attack=20:release=400[abaixada];"
              "[abaixada][voz]amix=inputs=2:duration=first:normalize=0[dub]")
    comando = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(video), "-i", str(trilha),
               "-filter_complex", filtro, "-map", "0:v?", "-map", "[dub]", "-map", "0:a"]
    if legendas:                                    # do .mkv dá para copiar as legendas embutidas como estão
        comando += ["-map", "0:s?", "-map", "0:t?"]
    comando += ["-c", "copy", "-c:a:0", "aac", "-b:a:0", "192k",
                "-metadata:s:a:0", "language=por", "-metadata:s:a:0", "title=Português (dublagem IA)",
                "-disposition:a:0", "default"]
    for i in range(faixas):
        comando += [f"-disposition:a:{i + 1}", "0"]
    return comando + ["-progress", "pipe:1", "-nostats", "-f", "matroska", str(saida)]


def mixar(ffmpeg: str, video: Path, trilha: Path, destino: Path, duracao: float, faixas: int = 1,
          parar=None, ao_progresso=None) -> None:
    parcial = destino.with_name(destino.name + ".part")
    comando = comando_mixar(ffmpeg, video, trilha, parcial, max(faixas, 1), video.suffix.lower() == ".mkv")
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
        if processo.wait() != 0 or not parcial.is_file():
            detalhe = erro.strip()[-300:] or (f"o ffmpeg fechou sozinho (código {processo.returncode})"
                                              if processo.returncode < 0 else "sem detalhes")
            raise ErroDublagem(f"o ffmpeg não conseguiu juntar o áudio: {detalhe}")
        parcial.replace(destino)
    finally:
        if processo.poll() is None:
            processo.kill()
        parcial.unlink(missing_ok=True)


# ----------------------------------------------------------------- o que dublar na biblioteca
@dataclass
class ParaDublar:
    video: Path
    legenda: Path                  # 'Nome.pt-BR.srt'
    falas: int = 0
    duracao: float | None = None
    tamanho: int = 0               # bytes do vídeo (a versão dublada ocupa quase o mesmo)


def caminho_dublado(video: Path) -> Path:
    return video.with_name(video.stem + MARCA_DUBLADO + ".mkv")


def videos_para_dublar(*pastas, idioma: str = "pt-BR", sondar=faixas_de_audio) -> list[ParaDublar]:
    """Filmes com legenda no idioma pedido, sem versão dublada e sem áudio em português."""
    portugues = _PORTUGUES | {idioma.lower(), idioma.lower().split("-")[0]}
    achados, vistos = [], set()
    for pasta in pastas:
        if not pasta or not Path(pasta).is_dir():
            continue
        for video in sorted(Path(pasta).rglob("*")):
            if ".organizador" in video.parts or not video.is_file() or not eh_video_da_biblioteca(video):
                continue
            if video.stem.endswith(MARCA_DUBLADO) or caminho_dublado(video).exists():
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
                achados.append(ParaDublar(video, legenda, falas, duracao, video.stat().st_size))
    return achados


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
                 pasta_cache: str | Path | None = None) -> ResultadoDublagem:
    """Lê a legenda com a voz, monta a trilha e grava 'Nome - Dublado IA.mkv'. O original não é tocado.
    adaptar([(id, texto, máx. letras, fala anterior)]) -> {id: texto mais curto}: as falas que não cabem no tempo
    são reescritas (ver adaptacao.py) e lidas de novo. Se falhar, segue sem adaptar. avisar(texto): para o log.
    vozes: {número da fala: voz} (uma voz por personagem; ver personagens.py).
    pasta_cache: guarda as falas já geradas (e as reescritas) por filme. Se parar no meio (limite do Gemini, sem
    internet, botão Parar), a próxima vez continua de onde parou, sem pedir (nem pagar) de novo."""
    video, legenda = Path(video), Path(legenda)
    destino = caminho_dublado(video)
    if destino.exists():
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
    duracao = duracao or horarios(falas[-1][0].tempo)[1] + 2
    vozes = vozes or {}
    if pasta_cache:
        lugar = contextlib.nullcontext(pasta_do_filme(pasta_cache, video))
    else:
        lugar = tempfile.TemporaryDirectory(prefix="maestro-dublagem-", dir=pasta_trabalho)
    with lugar as pasta:
        pasta = Path(pasta)
        pasta.mkdir(parents=True, exist_ok=True)
        pedidos = [(t, pasta / _nome_wav(k, t, vozes.get(k, "")), vozes.get(k, "")) for k, (_, t) in enumerate(falas)]
        retomadas = sum(1 for _, w, _ in pedidos if _pronto(w))
        try:
            _sintetizar(motor, pedidos, parar, lambda f: andamento(0.5 * f))
            clipes = [(*horarios(f.tempo), w) for (f, _), (_, w, _) in zip(falas, pedidos)]
            adaptadas = 0
            if adaptar is not None:
                clipes, adaptadas = _adaptar(clipes, [t for _, t in falas], duracao, motor, adaptar, parar, avisar,
                                             vozes, pasta)
            andamento(0.6)
            contas = montar_trilha(clipes, duracao, pasta / "trilha.wav", acelerar_com_ffmpeg(ffmpeg))
            andamento(0.7)
            mixar(ffmpeg, video, pasta / "trilha.wav", destino, duracao, len(idiomas), parar,
                  lambda f: andamento(0.7 + 0.3 * f))
        except (ErroDublagem, OSError, wave.Error, subprocess.SubprocessError) as erro:
            detalhe = str(erro) if isinstance(erro, ErroDublagem) else f"{type(erro).__name__}: {erro}"
            if pasta_cache:
                prontas = sum(1 for _, w, _ in pedidos if _pronto(w))
                detalhe += (f" — {prontas} de {len(pedidos)} falas já prontas e guardadas: dublar de novo continua "
                            "de onde parou")
            return ResultadoDublagem(video, "erro", detalhe, falas=len(falas), retomadas=retomadas)
        if pasta_cache:
            (pasta / "trilha.wav").unlink(missing_ok=True)
    if pasta_cache:
        shutil.rmtree(pasta_do_filme(pasta_cache, video), ignore_errors=True)      # pronto: o progresso não serve mais
    andamento(1.0)
    return ResultadoDublagem(video, "dublado", "", destino, len(falas), contas["aceleradas"], contas["cortadas"],
                             adaptadas, retomadas)


def _adaptar(clipes, textos, duracao, motor, adaptar, parar, avisar, vozes, pasta):
    """Reescreve (IA) as falas que só caberiam muito aceleradas e as lê de novo. Fica a versão que soar MAIS CURTA.
    As reescritas ficam guardadas (adaptadas.json): ao continuar um filme, não se paga de novo por elas."""
    from .adaptacao import NATURAL, limite_de_letras
    arquivo = Path(pasta) / "adaptadas.json"
    try:
        guardadas = {int(k): v for k, v in json.loads(arquivo.read_text(encoding="utf-8")).items()}
    except (OSError, ValueError):
        guardadas = {}
    longas = []
    for k, ((_, _, wav), vaga) in enumerate(zip(clipes, vagas(clipes, duracao))):
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
    pedidos = [(texto, Path(pasta) / _nome_wav(k, texto, vozes.get(k, ""), "-curta"), vozes.get(k, ""))
               for k, texto in guardadas.items() if k < len(clipes)]
    _sintetizar(motor, pedidos, parar)
    clipes, adaptadas = list(clipes), 0
    for (k, _), (_, wav, _) in zip(((k, t) for k, t in guardadas.items() if k < len(clipes)), pedidos):
        if _pronto(wav) and duracao_wav(wav) < duracao_wav(clipes[k][2]):
            clipes[k] = (clipes[k][0], clipes[k][1], wav)
            adaptadas += 1
    return clipes, adaptadas
