"""Gênero de quem fala, medido NO PC pelo tom da voz (a altura média, F0): grátis, sem mandar nada para fora.

A voz é uma vibração que se repete: a de homem costuma repetir de 85 a 160 vezes por segundo (Hz), a de mulher de
185 a 255 (crianças, mais ainda). Para cada fala da legenda, o Maestro pega o trecho do áudio original, procura em
cada pedacinho de 40 ms o "intervalo que se repete" (autocorrelação) e tira a mediana: abaixo de 160 Hz, voz de
homem; acima de 185 Hz, de mulher; no meio (homem gritando e mulher de voz grave se encontram aí), ou com música alta
e sem voz clara, não sabe e a fala fica com a voz principal. Na fala GRITADA (pelo volume, abaixo) a régua sobe: a
voz do homem gritando chega a 200-300 Hz. É o que o Gemini fazia ouvindo o filme, mas sem custo.
É uma aproximação: confira no teste antes de dublar o filme inteiro.

A EMOÇÃO que dá para medir assim (com a "Emoção da cena" ligada): o VOLUME de cada fala comparado com o das outras do
mesmo filme. Bem mais alta que o normal (e com voz): gritando. Bem mais baixa e quase sem "vibração" (o sussurro não
tem tom, é só ar): sussurrando. Raiva e alegria no mesmo volume o volume não separa; essas vêm do Gemini ou de
"Refazer esta fala". O tom vira a nota de direção ("Nesta fala: gritando...") que escolhe a gravação de emoção ou o
Chatterbox (emocoes.py).

    {número da fala: tom.Ouvida(genero="m" | "f" | "?", tom="gritando, com força" | "sussurrando..." | "")}
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .dublagem import SEM_JANELA, ErroDublagem, horarios
from .tom import Ouvida

TAXA = 8000                     # amostras por segundo: sobra para vozes de até 400 Hz
QUADRO, PASSO = 0.04, 0.02      # pedacinhos de 40 ms, a cada 20 ms
F0_MIN, F0_MAX = 70.0, 400.0
LIMITE_HOMEM, LIMITE_MULHER = 160.0, 185.0
# gritando, a voz sobe (o homem gritando chega a 200-300 Hz, a mulher passa de 300): a régua do grito é outra
LIMITE_HOMEM_GRITO, LIMITE_MULHER_GRITO = 230.0, 300.0
FORCA_MINIMA = 0.5              # quão "repetido" o pedacinho precisa ser para contar como voz (0 a 1)
BLOCO = 120.0                   # segundos de áudio lidos de uma vez do vídeo
# a emoção pelo volume (dB comparados com a mediana das falas do filme)
GRITO_DB, GRITO_DB_EXCLAMACAO = 9.0, 6.0     # mais alta que isso: gritando (com "!" no texto, basta menos)
SUSSURRO_DB, SUSSURRO_VOZEADO = 10.0, 0.35   # mais baixa que isso e com pouca "vibração": sussurrando
SILENCIO_DB = -55.0                          # mais baixo que isso não é fala (é o silêncio da cena)
FALAS_PARA_COMPARAR = 8                      # com menos falas medidas, não dá para saber o "normal" do filme
TOM_GRITO, TOM_SUSSURRO = "gritando, com força", "sussurrando, em voz baixa"


def medir(amostras, taxa: int = TAXA) -> tuple[float | None, float | None, float]:
    """(altura média da voz em Hz ou None, volume em dB ou None, quanto do som tem "vibração" de voz, 0 a 1).
    A altura é None sem voz clara (silêncio, música, ruído, sussurro); o volume, None no silêncio."""
    import numpy as np
    amostras = np.asarray(amostras, dtype=np.float32)
    n, passo = int(QUADRO * taxa), int(PASSO * taxa)
    if len(amostras) < n:
        return None, None, 0.0
    quadros = np.lib.stride_tricks.sliding_window_view(amostras, n)[::passo].astype(np.float32)
    quadros = quadros - quadros.mean(axis=1, keepdims=True)
    energia = np.sqrt((quadros ** 2).mean(axis=1))
    if not len(energia) or energia.max() <= 1e-4:
        return None, None, 0.0
    com_som = energia > energia.max() * 0.15                   # só os pedacinhos com som de verdade
    volume = float(20 * np.log10(np.percentile(energia[com_som], 90) + 1e-12))
    quadros = quadros[com_som]
    espectro = np.fft.rfft(quadros, 2 * n, axis=1)
    auto = np.fft.irfft(np.abs(espectro) ** 2, axis=1)[:, :n]
    auto = auto / np.maximum(auto[:, :1], 1e-12) * (n / (n - np.arange(n)))   # 1 = repete perfeitamente
    menor, maior = int(taxa / F0_MAX), int(taxa / F0_MIN)
    janela = auto[:, menor:maior + 1]
    forca = janela.max(axis=1)
    bons = forca >= FORCA_MINIMA
    vozeado = float(bons.mean())
    if bons.sum() < 3:
        return None, volume, vozeado
    # o PRIMEIRO pico forte (não o dobro do intervalo: senão a voz de mulher parece de homem, uma oitava abaixo)
    primeiro = np.argmax(janela[bons] >= forca[bons, None] * 0.85, axis=1)
    return float(np.median(taxa / (primeiro + menor))), volume, vozeado


def tom_medio(amostras, taxa: int = TAXA) -> float | None:
    """A altura média da voz (Hz) num trecho, ou None se não há voz clara (silêncio, música, ruído)."""
    return medir(amostras, taxa)[0]


def tom_pelo_volume(volume: float | None, normal: float | None, vozeado: float, texto: str = "") -> str:
    """A nota de emoção pelo volume da fala comparado com o normal do filme: TOM_GRITO, TOM_SUSSURRO ou ""."""
    if volume is None or normal is None or volume < SILENCIO_DB:
        return ""
    if vozeado >= SUSSURRO_VOZEADO and (volume >= normal + GRITO_DB or
                                        ("!" in texto and volume >= normal + GRITO_DB_EXCLAMACAO)):
        return TOM_GRITO
    if volume <= normal - SUSSURRO_DB and vozeado < SUSSURRO_VOZEADO:
        return TOM_SUSSURRO
    return ""


def genero_pelo_tom(f0: float | None, gritando: bool = False) -> str:
    if f0 is None:
        return "?"
    homem, mulher = (LIMITE_HOMEM_GRITO, LIMITE_MULHER_GRITO) if gritando else (LIMITE_HOMEM, LIMITE_MULHER)
    if f0 < homem:
        return "m"
    return "f" if f0 > mulher else "?"


def ler_audio(ffmpeg: str, video: str | Path, inicio: float, duracao: float, executar=subprocess.run):
    """O trecho do áudio do vídeo em 8 kHz, mono (números de -1 a 1)."""
    import numpy as np
    comando = [ffmpeg, "-hide_banner", "-loglevel", "error", "-ss", f"{max(0.0, inicio):.3f}", "-t",
               f"{duracao:.3f}", "-i", str(video), "-vn", "-ac", "1", "-ar", str(TAXA), "-f", "s16le", "pipe:1"]
    try:
        r = executar(comando, capture_output=True, timeout=300, **SEM_JANELA)
    except (OSError, subprocess.SubprocessError) as erro:
        raise ErroDublagem(f"o ffmpeg não conseguiu ler o áudio do vídeo: {erro}") from erro
    if r.returncode != 0:
        detalhe = (r.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        raise ErroDublagem(f"o ffmpeg não conseguiu ler o áudio do vídeo{': ' + detalhe[-1] if detalhe else ''}")
    dados = r.stdout[:len(r.stdout) // 2 * 2]
    return np.frombuffer(dados, dtype=np.int16).astype(np.float32) / 32768.0


def ouvir_generos(video: str | Path, falas: list, ids: list[int], ffmpeg: str, arquivo: str | Path | None = None,
                  parar=None, ler=ler_audio, emocao: bool = False) -> dict[int, Ouvida]:
    """{número da fala: Ouvida(genero[, tom])} das falas `ids`. falas: [(Fala, texto)] (dublagem.falas_da_legenda).
    arquivo: onde guardar o que já foi medido (a fala com outro texto é medida de novo). emocao: também o tom pelo
    volume (gritando / sussurrando), comparando com as outras falas medidas do filme."""
    arquivo = Path(arquivo) if arquivo else None
    guardado = {}
    if arquivo and arquivo.is_file():
        try:
            guardado = json.loads(arquivo.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            guardado = {}
    resultado: dict[int, Ouvida] = {}
    faltam = []
    for k in ids:
        anterior = guardado.get(str(k))
        if isinstance(anterior, dict) and anterior.get("texto") == falas[k][1] and "db" in anterior:
            resultado[k] = Ouvida(genero=anterior.get("genero", "?"))
        else:
            faltam.append(k)
    faltam.sort(key=lambda k: horarios(falas[k][0].tempo)[0])
    while faltam:                                    # lê o vídeo em blocos de até 2 minutos
        if parar and parar():
            raise ErroDublagem("interrompido (botão Parar)")
        inicio = horarios(falas[faltam[0]][0].tempo)[0]
        grupo = [k for k in faltam if horarios(falas[k][0].tempo)[1] <= inicio + BLOCO] or faltam[:1]
        fim = max(horarios(falas[k][0].tempo)[1] for k in grupo)
        audio = ler(ffmpeg, video, inicio, fim - inicio + 0.1)
        for k in grupo:
            a, b = horarios(falas[k][0].tempo)
            f0, volume, vozeado = medir(audio[int((a - inicio) * TAXA):int((b - inicio) * TAXA)])
            # quase sem "vibração" (sussurro, ruído): o tom que sobra é de pedacinhos soltos e engana (um homem
            # sussurrando "virava" mulher): não sabe, e a fala fica com a voz principal
            resultado[k] = Ouvida(genero=genero_pelo_tom(f0) if vozeado >= SUSSURRO_VOZEADO else "?")
            guardado[str(k)] = {"texto": falas[k][1], "genero": resultado[k].genero,
                                "f0": round(f0, 1) if f0 else None, "db": round(volume, 1) if volume else None,
                                "vozeado": round(vozeado, 2)}
        faltam = [k for k in faltam if k not in grupo]
    if emocao:
        volumes = sorted(g["db"] for g in guardado.values() if isinstance(g, dict) and g.get("db") is not None
                         and g["db"] >= SILENCIO_DB)
        normal = volumes[len(volumes) // 2] if len(volumes) >= FALAS_PARA_COMPARAR else None
        for k in list(resultado):
            medido = guardado.get(str(k), {})
            tom = tom_pelo_volume(medido.get("db"), normal, medido.get("vozeado", 0.0), falas[k][1])
            if tom:
                genero = resultado[k].genero
                if tom == TOM_GRITO:              # o homem gritando não vira mulher (a voz sobe no grito)
                    genero = genero_pelo_tom(medido.get("f0"), gritando=True)
                resultado[k] = Ouvida(genero=genero, tom=tom)
    if arquivo:
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        arquivo.write_text(json.dumps(guardado, ensure_ascii=False), encoding="utf-8")
    return resultado
