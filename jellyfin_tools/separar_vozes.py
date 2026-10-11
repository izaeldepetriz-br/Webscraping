"""Separa as VOZES do FUNDO (música e efeitos) de um vídeo, para a dublagem "de verdade".

Sem isto, a dublagem fica no estilo "voice-over" (documentário): a voz sintética entra por cima do áudio original,
que só abaixa enquanto ela fala, e as vozes originais continuam lá, baixinhas. Com isto, um modelo de IA tira as
vozes originais e a dublagem entra sobre a música e os efeitos limpos, como num estúdio de dublagem.

O modelo é o UVR-MDX-NET-Inst_HQ_3 (licença MIT, do Ultimate Vocal Remover), em ONNX: roda no onnxruntime, que o
Maestro já usa por causa do Whisper. É baixado na 1ª vez (~67 MB) e fica guardado. Roda no PC, grátis.

Como funciona (o mesmo cálculo do UVR, em numpy):
1. o ffmpeg entrega o áudio em 44,1 kHz estéreo, aos pedaços (um filme de 2 h não cabe todo na memória);
2. cada bloco de ~6 s vira um espectrograma (STFT: quanto de cada frequência há em cada instante);
3. o modelo devolve o espectrograma só do fundo; a STFT inversa volta a ser som;
4. os blocos se sobrepõem um pouco (as bordas são descartadas) e o resultado vai, aos pedaços, para um .flac.
"""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

MODELO = "UVR-MDX-NET-Inst_HQ_3.onnx"
URL_MODELO = "https://github.com/TRvlvr/model_repo/releases/download/all_public_uvr_models/" + MODELO
SHA256_MODELO = "317554b07fe1ea5279a77f2b1520a41ea4b93432560c4ffd08792c30fddf9adc"
TAXA = 44100
N_FFT = 6144
SALTO = 1024                     # hop: um quadro do espectrograma a cada 1024 amostras
DIM_F = 3072                     # faixas de frequência que o modelo vê (as mais agudas ficam de fora)
DIM_T = 256                      # quadros por bloco
COMPENSAR = 1.022                # ajuste de volume do fundo (valor do UVR para este modelo)
BLOCO = SALTO * (DIM_T - 1)      # 261.120 amostras (~5,9 s) entram no modelo de cada vez
BORDA = N_FFT // 2               # o começo e o fim de cada bloco saem piores: são descartados
UTIL = BLOCO - 2 * BORDA         # o que sobra de cada bloco (~5,8 s)
SEM_JANELA = {"creationflags": subprocess.CREATE_NO_WINDOW} if hasattr(subprocess, "CREATE_NO_WINDOW") else {}


class ErroSeparacao(Exception):
    pass


def disponivel() -> bool:
    """O onnxruntime e o numpy estão instalados (no .exe, sim: vêm com o Whisper)."""
    try:
        import numpy  # noqa: F401
        import onnxruntime  # noqa: F401
        return True
    except ImportError:
        return False


def preparar_modelo(pasta: str | Path, baixar=None, ao_progresso=None) -> Path:
    """O arquivo do modelo (baixa na 1ª vez e confere o SHA-256, para não usar um download pela metade)."""
    destino = Path(pasta) / MODELO
    if destino.is_file() and destino.stat().st_size > 1_000_000:
        return destino
    destino.parent.mkdir(parents=True, exist_ok=True)
    if baixar is None:
        from .dublagem import _baixar as baixar
    parcial = destino.with_name(destino.name + ".part")
    baixar(URL_MODELO, parcial, ao_progresso)
    soma = hashlib.sha256()
    with open(parcial, "rb") as arquivo:
        for pedaco in iter(lambda: arquivo.read(1 << 20), b""):
            soma.update(pedaco)
    if soma.hexdigest() != SHA256_MODELO:
        parcial.unlink(missing_ok=True)
        raise ErroSeparacao("o modelo que separa as vozes veio corrompido; tente de novo")
    parcial.replace(destino)
    return destino


def _janela():
    import numpy as np
    return (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(N_FFT) / N_FFT)).astype(np.float32)   # Hann "periódica"


def stft(blocos, janela):
    """blocos (n, 2, BLOCO) -> entrada do modelo (n, 4, DIM_F, DIM_T): real e imaginário de cada canal.
    Igual ao torch.stft(center=True, pad_mode="reflect") que o UVR usa."""
    import numpy as np
    n = blocos.shape[0]
    x = np.pad(blocos, ((0, 0), (0, 0), (BORDA, BORDA)), mode="reflect")
    indices = np.arange(DIM_T)[:, None] * SALTO + np.arange(N_FFT)[None, :]
    quadros = x[:, :, indices] * janela                       # (n, 2, DIM_T, N_FFT)
    espectro = np.fft.rfft(quadros, axis=-1)[..., :DIM_F]     # (n, 2, DIM_T, DIM_F)
    espectro = np.swapaxes(espectro, 2, 3)                    # (n, 2, DIM_F, DIM_T)
    saida = np.empty((n, 4, DIM_F, DIM_T), dtype=np.float32)
    saida[:, 0::2] = espectro.real
    saida[:, 1::2] = espectro.imag
    return saida


def istft(espectros, janela):
    """Saída do modelo (n, 4, DIM_F, DIM_T) -> som (n, 2, BLOCO). As frequências cortadas voltam como zero."""
    import numpy as np
    n = espectros.shape[0]
    completo = np.zeros((n, 2, N_FFT // 2 + 1, DIM_T), dtype=np.complex64)
    completo[:, :, :DIM_F] = espectros[:, 0::2] + 1j * espectros[:, 1::2]
    quadros = np.fft.irfft(np.swapaxes(completo, 2, 3), n=N_FFT, axis=-1) * janela   # (n, 2, DIM_T, N_FFT)
    total = N_FFT + SALTO * (DIM_T - 1)
    som = np.zeros((n, 2, total), dtype=np.float32)
    envelope = np.zeros(total, dtype=np.float32)
    for t in range(DIM_T):                                    # soma as janelas sobrepostas
        som[:, :, t * SALTO:t * SALTO + N_FFT] += quadros[:, :, t]
        envelope[t * SALTO:t * SALTO + N_FFT] += janela ** 2
    som /= np.maximum(envelope, 1e-8)
    return som[:, :, BORDA:BORDA + BLOCO]


class Separador:
    """separar(entrada_pcm, gravar): lê o áudio (int16 estéreo, 44,1 kHz) aos pedaços e grava o fundo aos pedaços."""

    def __init__(self, modelo: str | Path, lote: int = 2, sessao=None):
        import numpy as np
        self.np = np
        self.lote = lote
        if sessao is None:
            import onnxruntime as ort
            opcoes = ort.SessionOptions()
            opcoes.log_severity_level = 3
            sessao = ort.InferenceSession(str(modelo), opcoes, providers=["CPUExecutionProvider"])
        self.sessao = sessao
        self.entrada = sessao.get_inputs()[0].name
        self.janela = _janela()

    def _rodar(self, blocos):
        espectro = stft(blocos, self.janela)
        previsto = self.sessao.run(None, {self.entrada: espectro})[0]
        return istft(previsto, self.janela)[:, :, BORDA:BORDA + UTIL] * COMPENSAR

    def separar(self, ler, gravar, total_amostras: int | None = None, parar=None, ao_progresso=None) -> int:
        """ler(n) -> até n amostras estéreo (array (k, 2) float32, k=0 no fim); gravar(array (k, 2)).
        Devolve quantas amostras gravou (as mesmas que leu)."""
        np = self.np
        # o mesmo enchimento do UVR: BORDA de silêncio no começo; o fim é completado com silêncio
        buffer = np.zeros((2, BORDA), dtype=np.float32)
        lidas = gravadas = 0
        fim = False
        while True:
            while not fim and buffer.shape[1] < BORDA + UTIL * self.lote + BORDA:
                pedaco = ler(UTIL * self.lote)
                if pedaco is None or len(pedaco) == 0:
                    fim = True
                    break
                lidas += len(pedaco)
                buffer = np.concatenate([buffer, pedaco.T.astype(np.float32)], axis=1)
            if buffer.shape[1] <= BORDA:
                break
            if fim:                                               # o último lote: completa com silêncio
                blocos_que_faltam = -(-(buffer.shape[1] - BORDA) // UTIL)      # arredondado para cima
                falta = blocos_que_faltam * UTIL + 2 * BORDA - buffer.shape[1]
                if falta > 0:
                    buffer = np.concatenate([buffer, np.zeros((2, falta), dtype=np.float32)], axis=1)
            quantos = min(self.lote, (buffer.shape[1] - 2 * BORDA) // UTIL)
            if quantos <= 0:
                break
            if parar and parar():
                raise ErroSeparacao("interrompido (botão Parar)")
            blocos = np.stack([buffer[:, k * UTIL:k * UTIL + BLOCO] for k in range(quantos)])
            fundo = self._rodar(blocos)                            # (quantos, 2, UTIL)
            saida = np.concatenate(list(fundo), axis=1)            # (2, quantos * UTIL)
            restam = lidas - gravadas if fim else saida.shape[1]
            saida = saida[:, :max(0, min(saida.shape[1], restam))]
            gravar(saida.T)
            gravadas += saida.shape[1]
            buffer = buffer[:, quantos * UTIL:]
            if ao_progresso and total_amostras:
                ao_progresso(min(gravadas / total_amostras, 1.0))
            if fim and gravadas >= lidas:
                break
        return gravadas


def separar_fundo(ffmpeg: str, video: str | Path, destino: str | Path, modelo: str | Path,
                  trecho: tuple[float, float] | None = None, duracao: float | None = None, parar=None,
                  ao_progresso=None, separador=None) -> Path:
    """Grava em `destino` (.flac) só a música e os efeitos do 1º áudio do vídeo (sem as vozes).
    trecho (início, fim): só esse pedaço (a amostra de 1 minuto). Se `destino` já existir, usa o que está lá."""
    import numpy as np
    destino = Path(destino)
    if destino.is_file() and destino.stat().st_size > 0:
        return destino
    separador = separador or Separador(modelo)
    corte = ["-ss", f"{trecho[0]:.3f}", "-t", f"{trecho[1] - trecho[0]:.3f}"] if trecho else []
    entrada = subprocess.Popen(
        [ffmpeg, "-hide_banner", "-loglevel", "error", *corte, "-i", str(video), "-map", "0:a:0", "-vn",
         "-ac", "2", "-ar", str(TAXA), "-f", "s16le", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, **SEM_JANELA)
    parcial = destino.with_name(destino.name + ".part")
    saida = subprocess.Popen(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "f32le", "-ar", str(TAXA), "-ac", "2", "-i", "-",
         "-c:a", "flac", "-f", "flac", str(parcial)],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, **SEM_JANELA)

    def ler(n: int):
        dados = entrada.stdout.read(n * 4)
        if len(dados) % 4:
            dados = dados[:len(dados) - len(dados) % 4]
        return np.frombuffer(dados, dtype=np.int16).reshape(-1, 2).astype(np.float32) / 32768.0

    def gravar(amostras) -> None:
        saida.stdin.write(np.ascontiguousarray(amostras, dtype=np.float32).tobytes())

    total = int((trecho[1] - trecho[0] if trecho else duracao or 0) * TAXA) or None
    try:
        gravadas = separador.separar(ler, gravar, total, parar, ao_progresso)
        saida.stdin.close()
        erro = saida.stderr.read().decode("utf-8", "replace").strip()
        if saida.wait() != 0 or entrada.wait() != 0 or not gravadas or not parcial.is_file():
            raise ErroSeparacao("não deu para separar as vozes do fundo"
                                + (f": {erro[-200:]}" if erro else " (o vídeo tem áudio?)"))
        parcial.replace(destino)
        return destino
    finally:
        for processo in (entrada, saida):
            if processo.poll() is None:
                processo.kill()
        parcial.unlink(missing_ok=True)
