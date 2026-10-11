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
import json
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


def provedores_disponiveis() -> list[str]:
    try:
        import onnxruntime as ort
        return list(ort.get_available_providers())
    except ImportError:
        return []


def criar_sessao(modelo: str | Path, usar_gpu: bool = True, avisar=None, cronometro=None):
    """(sessão do onnxruntime, dispositivo). A placa de vídeo vem do DirectML (o .exe do Windows traz o
    onnxruntime-directml: NVIDIA, AMD ou Intel com DirectX 12). Num PC SEM placa de vídeo, o DirectML ainda "funciona"
    pelo driver de software do Windows, mais lento que o processador; por isso há uma corrida: um bloco de teste em
    cada um, e fica o mais rápido. `dispositivo`: "placa de vídeo" ou "processador" (+ os tempos da corrida)."""
    import time

    import numpy as np
    import onnxruntime as ort
    cronometro = cronometro or time.perf_counter

    def opcoes(gpu: bool):
        o = ort.SessionOptions()
        o.log_severity_level = 3
        if gpu:                                # o DirectML pede estas duas
            o.enable_mem_pattern = False
            o.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        return o
    cpu = ort.InferenceSession(str(modelo), opcoes(False), providers=["CPUExecutionProvider"])
    if not (usar_gpu and "DmlExecutionProvider" in provedores_disponiveis()):
        return cpu, "processador"
    try:
        gpu = ort.InferenceSession(str(modelo), opcoes(True),
                                   providers=["DmlExecutionProvider", "CPUExecutionProvider"])
        if "DmlExecutionProvider" not in gpu.get_providers():
            return cpu, "processador"
        bloco = {cpu.get_inputs()[0].name: np.zeros((1, 4, DIM_F, DIM_T), dtype=np.float32)}

        def tempo(sessao) -> float:
            sessao.run(None, bloco)            # a 1ª vez prepara (na placa de vídeo, compila): não conta
            inicio = cronometro()
            sessao.run(None, bloco)
            return cronometro() - inicio
        t_gpu, t_cpu = tempo(gpu), tempo(cpu)
        corrida = f"placa de vídeo {t_gpu:.2f} s x processador {t_cpu:.2f} s por bloco"
        if t_gpu < t_cpu * 0.9:
            return gpu, f"placa de vídeo ({corrida})"
        return cpu, f"processador ({corrida}: a placa de vídeo não ganhou)"
    except Exception as erro:                  # driver antigo, sem DirectX 12...
        if avisar:
            avisar(f"a placa de vídeo não deu certo ({erro}); usando o processador")
        return cpu, "processador"


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


# ----------------------------------------------------------------- ambientação da voz dublada
# Enquanto separa, mede as VOZES ORIGINAIS (o que o modelo tirou do fundo): o tom (graves e agudos, por oitava),
# o volume das falas e quanto a sala "ecoa" quando a pessoa para de falar. A voz dublada recebe o mesmo: assim ela
# parece estar na cena, e não colada por cima. É uma ambientação geral do vídeo (não cena por cena).
BANDAS = (125, 250, 500, 1000, 2000, 4000, 8000)         # centros das oitavas (Hz)
EQ_MAXIMO = 4.0                                           # dB: mais que isso deixa a voz estranha
EQ_PARTE = 0.4          # copia só 40% da diferença de tom: parte dela é da PESSOA (voz grave x aguda), não da sala
BANDAS_DO_TOM = (250, 500, 1000, 2000, 4000, 8000)        # os 125 Hz dependem de a voz ser grave ou aguda: ficam
GANHO_MAXIMO = 12.0


def _bandas_de(frequencias):
    """Para cada oitava, quais posições do espectro entram nela."""
    import numpy as np
    return [np.where((frequencias >= c / 2 ** 0.5) & (frequencias < c * 2 ** 0.5))[0] for c in BANDAS]


class _Medidor:
    """Junta, quadro a quadro, a energia de cada oitava e o volume (média dos quadrados) de um sinal."""

    def __init__(self, frequencias, normalizar: float):
        self.indices = _bandas_de(frequencias)
        self.normalizar = normalizar           # potência do espectro -> média dos quadrados no tempo (Parseval)
        self.quadros_bandas, self.quadros_nivel = [], []

    def somar(self, potencia):
        """potencia: (quadros, frequências) = |X|² de cada quadro."""
        import numpy as np
        self.quadros_bandas.append(np.stack([potencia[:, i].sum(axis=1) for i in self.indices], axis=1)
                                   .astype(np.float32))
        self.quadros_nivel.append((2 * potencia.sum(axis=1) / self.normalizar).astype(np.float32))

    def perfil(self, periodo: float) -> dict | None:
        """{nivel: dB, bandas: [dB], eco: 0..1, quadros_com_fala}. Só os quadros com fala contam."""
        import numpy as np
        if not self.quadros_nivel:
            return None
        nivel = np.concatenate(self.quadros_nivel)
        bandas = np.concatenate(self.quadros_bandas)
        db = 10 * np.log10(nivel + 1e-12)
        if not len(db) or db.max() < -80:
            return None
        topo = np.percentile(db, 95)
        fala = db > topo - 25
        if fala.sum() < 5:
            return None
        forte = db > topo - 10           # o volume = o das partes fortes da fala (não depende de quanto silêncio há)
        return {"nivel": float(10 * np.log10(nivel[forte].mean() + 1e-12)),
                "bandas": [float(10 * np.log10(b + 1e-12)) for b in bandas[fala].mean(axis=0)],
                "eco": estimar_eco(db, periodo), "quadros_com_fala": int(fala.sum())}


def estimar_eco(db, periodo: float) -> float:
    """0 (voz seca, de estúdio) a 1 (sala grande), pela QUEDA MAIS RÁPIDA do volume da voz: numa sala com eco, nem o
    fim mais brusco de uma fala cai mais rápido que o eco some. Mede a inclinação (dB por segundo) em janelas de
    ~170 ms que começam nas partes fortes da fala e pega as 5% mais íngremes; 60 dB divididos por ela = o tempo de
    reverberação (RT60). Calibrado nas vozes SEPARADAS de uma mistura com música (a sobra de música deixa a queda um
    pouco mais lenta): voz seca ≈ 0,43 s -> eco 0; sala de 0,6 s ≈ 0,78 s -> 0,33; sala de 1 s ≈ 1,34 s -> 0,89."""
    import numpy as np
    db = np.asarray(db, dtype=float)
    k = max(3, round(0.17 / periodo))
    if len(db) < k + 5:
        return 0.0
    topo = np.percentile(db, 95)
    x = np.arange(k) * periodo
    x = x - x.mean()
    janelas = np.lib.stride_tricks.sliding_window_view(db, k)
    validas = janelas[janelas[:, 0] > topo - 15]
    if len(validas) < 10:
        return 0.0
    inclinacoes = (validas - validas.mean(axis=1, keepdims=True)) @ x / (x @ x)      # regressão de cada janela
    mais_ingreme = np.percentile(inclinacoes, 5)
    if mais_ingreme >= 0:
        return 0.0
    rt60 = 60 / -mais_ingreme
    return float(np.clip((rt60 - 0.45) / 1.0, 0.0, 1.0))


def perfil_de_sinal(amostras, taxa: int) -> dict | None:
    """O mesmo perfil para a voz dublada (a trilha das falas, mono)."""
    import numpy as np
    n, salto = 2048, 512
    x = np.asarray(amostras, dtype=np.float32)
    if len(x) < n:
        return None
    janela = (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(n) / n)).astype(np.float32)
    medidor = _Medidor(np.fft.rfftfreq(n, 1 / taxa), n * float((janela ** 2).sum()))
    for inicio in range(0, len(x) - n, salto * 512):                  # aos pedaços (filme longo)
        bloco = x[inicio:inicio + salto * 512 + n]
        quadros = np.lib.stride_tricks.sliding_window_view(bloco, n)[::salto] * janela
        medidor.somar(np.abs(np.fft.rfft(quadros, axis=1)) ** 2)
    return medidor.perfil(salto / taxa)


def ambiente(perfil_voz: dict | None, perfil_dublada: dict | None) -> dict | None:
    """O ajuste da voz dublada: {ganho_db, eq: [(Hz, dB)], eco}. None: não há fala bastante para medir."""
    if not perfil_voz or not perfil_dublada:
        return None
    import numpy as np
    ganho = float(np.clip(perfil_voz["nivel"] - perfil_dublada["nivel"] + 1.0, -GANHO_MAXIMO, GANHO_MAXIMO))
    original = np.array(perfil_voz["bandas"]) - np.mean(perfil_voz["bandas"])
    dublada = np.array(perfil_dublada["bandas"]) - np.mean(perfil_dublada["bandas"])
    diferenca = np.clip(EQ_PARTE * (original - dublada), -EQ_MAXIMO, EQ_MAXIMO)
    forte = max(perfil_dublada["bandas"])
    eq = [(f, round(float(g), 1)) for f, g in zip(BANDAS, diferenca)
          if f in BANDAS_DO_TOM and abs(g) >= 0.5
          and perfil_dublada["bandas"][BANDAS.index(f)] > forte - 40]   # onde a voz dublada quase não tem som: não
    return {"ganho_db": round(ganho, 1), "eq": eq, "eco": round(float(perfil_voz.get("eco", 0.0)), 2)}


def gerar_sala(destino: str | Path, eco: float, taxa: int = 48000, semente: int = 7) -> Path:
    """A "resposta da sala" para a convolução: ruído que some exponencialmente (estéreo, um pouco diferente em cada
    lado). Sala pequena (eco baixo) = cauda curta; sala grande = cauda longa."""
    import wave
    import numpy as np
    rt60 = 0.25 + 1.0 * eco
    n = int(taxa * min(rt60, 1.2))
    t = np.arange(n) / taxa
    gerador = np.random.default_rng(semente)
    queda = np.exp(-6.9 * t / rt60)
    canais = [gerador.standard_normal(n) * queda for _ in range(2)]
    for c in canais:
        c[: int(0.004 * taxa)] = 0                     # 4 ms até a 1ª reflexão
    sinal = np.stack(canais, axis=1)
    sinal /= np.abs(sinal).max() + 1e-9
    destino = Path(destino)
    with wave.open(str(destino), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(taxa)
        w.writeframes((sinal * 0.9 * 32767).astype("<i2").tobytes())
    return destino


def filtro_da_voz(amb: dict | None) -> str:
    """Os filtros do ffmpeg para a voz dublada (tom e volume). Sem ambiente: o volume fixo de antes."""
    if not amb:
        return "volume=1.5"
    partes = [f"equalizer=f={f}:t=o:w=1:g={g}" for f, g in amb["eq"]]
    return ",".join(partes + [f"volume={amb['ganho_db']}dB"])


def usa_sala(amb: dict | None) -> bool:
    return bool(amb) and amb.get("eco", 0) >= 0.05


class Separador:
    """separar(entrada_pcm, gravar): lê o áudio (int16 estéreo, 44,1 kHz) aos pedaços e grava o fundo aos pedaços.
    usar_gpu: tenta a placa de vídeo (DirectML, no Windows: NVIDIA, AMD ou Intel com DirectX 12); se não der, o
    processador. `dispositivo` diz qual ficou. `perfil()`: as vozes originais medidas (ambientação)."""

    def __init__(self, modelo: str | Path, lote: int = 2, sessao=None, usar_gpu: bool = True, avisar=None):
        import numpy as np
        self.np = np
        self.lote = lote
        self.dispositivo = "processador"
        if sessao is None:
            sessao, self.dispositivo = criar_sessao(modelo, usar_gpu, avisar)
        self.sessao = sessao
        self.entrada = sessao.get_inputs()[0].name
        self.janela = _janela()
        frequencias = np.arange(DIM_F) * TAXA / N_FFT
        self.medidor = _Medidor(frequencias, N_FFT * float((self.janela ** 2).sum()))

    def _rodar(self, blocos):
        espectro = stft(blocos, self.janela)
        previsto = self.sessao.run(None, {self.entrada: espectro})[0]
        self._medir_vozes(espectro, previsto)
        return istft(previsto, self.janela)[:, :, BORDA:BORDA + UTIL] * COMPENSAR

    def _medir_vozes(self, espectro, previsto) -> None:
        """As vozes originais = a mistura menos o fundo. Só os quadros do meio de cada bloco (as bordas se repetem)."""
        vozes = espectro - previsto * COMPENSAR
        potencia = (vozes[:, 0] ** 2 + vozes[:, 1] ** 2 + vozes[:, 2] ** 2 + vozes[:, 3] ** 2) / 2   # (n, F, T)
        inicio = BORDA // SALTO
        meio = potencia[:, :, inicio:inicio + UTIL // SALTO]
        self.medidor.somar(meio.transpose(0, 2, 1).reshape(-1, DIM_F))

    def perfil(self) -> dict | None:
        return self.medidor.perfil(SALTO / TAXA)

    def recomecar_medida(self) -> None:
        frequencias = self.np.arange(DIM_F) * TAXA / N_FFT
        self.medidor = _Medidor(frequencias, N_FFT * float((self.janela ** 2).sum()))

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


def caminho_perfil(fundo: str | Path) -> Path:
    """'fundo.flac' -> 'fundo.voz.json' (o perfil das vozes originais, medido junto com a separação)."""
    return Path(fundo).with_suffix(".voz.json")


def ler_perfil(fundo: str | Path) -> dict | None:
    try:
        return json.loads(caminho_perfil(fundo).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


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
    separador.recomecar_medida()
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
        perfil = separador.perfil()
        if perfil:                                  # as vozes originais medidas: para a ambientação
            caminho_perfil(destino).write_text(json.dumps(perfil), encoding="utf-8")
        return destino
    finally:
        for processo in (entrada, saida):
            if processo.poll() is None:
                processo.kill()
        parcial.unlink(missing_ok=True)
