"""A INTERPRETAÇÃO das falas com emoção, depois do motor de vozes (XTTS-v2 ou Chatterbox).

O motor de vozes põe a emoção "de leve": o Chatterbox fala mais forte, mas o choro não treme e a raiva não rasga. Aqui
entra o que o ator faz com a voz (o que se mede na fala emocionada):

- choro: a voz TREME (o tom oscila 5 a 7 vezes por segundo, irregular e mais forte no fim de cada frase), sobe, sai
  com ar, falha (a voz "embarga") e puxa o ar nas pausas, entrecortado (o soluço);
- raiva: a voz fica FORÇADA e RASGADA (os agudos de 2 a 4 kHz sobem, a aspereza das pregas vocais apertadas, a
  saturação), mais aguda e mais alta, com as sílabas fortes ainda mais fortes; no grito, tudo isso mais forte;
- medo: treme rápido, com ar, e falha;
- tristeza: um tremor leve, mais grave e mais escura;
- alegria: mais aguda e brilhante;
- sussurro: a voz vira ar (o mesmo "formato de boca" de cada pedacinho, sem a vibração da voz).

A duração da fala não muda (o encaixe no tempo da cena continua o mesmo). Tudo com numpy; o ffmpeg só sobe ou desce o
tom (sem ele, o tom fica como está).
"""

from __future__ import annotations

import subprocess
import wave
import zlib
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np

from .emocoes import NORMAL

LIMITE = 0.97                    # o pico mais alto (sem estourar)


@dataclass(frozen=True)
class Receita:
    """Como cada emoção muda a voz (na força 1, "Forte")."""
    semitons: float = 0.0        # o tom sobe (+) ou desce (-), em semitons
    tremor: float = 0.0          # cents (100 = meio tom) da oscilação do tom
    tremor_hz: float = 5.5       # quantas vezes por segundo (irregular, ±20%)
    quebras: float = 0.0         # por segundo de voz: a voz que "quebra" para o agudo por um instante (o choro)
    acento: float = 0.0          # cents: o tom sobe nas sílabas fortes e desce nas fracas (a fala de quem briga)
    pulso: float = 0.0           # 0-1: o volume tremendo junto
    ar: float = 0.0              # 0-1: a voz soprada (o ar junto da voz)
    falhas: float = 0.0          # falhas por segundo de voz (a voz que embarga)
    soluco: float = 0.0          # 0-1: a inspiração entrecortada nas pausas
    presenca: float = 0.0        # dB nos 2-4 kHz (a voz forçada)
    brilho: float = 0.0          # dB acima de 4,5 kHz (+ brilhante, - escura)
    aspereza: float = 0.0        # 0-1: a voz rasgada
    saturacao: float = 0.0       # 0-1: o "estouro" do grito
    enfase: float = 0.0          # 0-1: as sílabas fortes ainda mais fortes
    volume: float = 0.0          # dB no fim
    sussurro: float = 0.0        # 0-1: quanto da voz vira ar


RECEITAS: dict[str, Receita] = {
    "choro": Receita(semitons=1.5, tremor=90, tremor_hz=6.0, quebras=0.5, pulso=0.4, ar=0.35, falhas=0.5,
                     soluco=1.0, brilho=-1.5),
    "triste": Receita(semitons=-0.8, tremor=25, tremor_hz=5.0, pulso=0.15, ar=0.15, falhas=0.15, soluco=0.4,
                      brilho=-3.0),
    "medo": Receita(semitons=1.0, tremor=50, tremor_hz=8.0, quebras=0.2, pulso=0.25, ar=0.3, falhas=0.3,
                    soluco=0.6),
    "brava": Receita(semitons=1.0, acento=180, presenca=6.0, aspereza=0.4, saturacao=0.5, enfase=0.5, volume=3.0),
    "grito": Receita(semitons=2.0, acento=250, ar=0.15, presenca=8.0, brilho=1.5, aspereza=0.55, saturacao=0.8,
                     enfase=0.6, volume=5.0),
    "alegre": Receita(semitons=1.2, acento=120, presenca=2.0, brilho=2.0, enfase=0.25),
    "sussurro": Receita(sussurro=0.9, brilho=1.0, volume=-8.0),
}


def receita(emocao: str, forca: float = 1.0) -> Receita | None:
    """A receita da emoção na força pedida (None: nada a fazer). O tremor_hz não muda com a força."""
    base = RECEITAS.get(emocao)
    if base is None or emocao == NORMAL or forca <= 0:
        return None
    campos = {nome: getattr(base, nome) * forca for nome in base.__dataclass_fields__ if nome != "tremor_hz"}
    return replace(base, **campos)


# ----------------------------------------------------------------- ler e gravar
def ler_wav(caminho: str | Path) -> tuple[np.ndarray, int]:
    """O WAV de 16 bits (o que os motores gravam) como números de -1 a 1, em mono."""
    with wave.open(str(caminho)) as w:
        canais, largura, taxa = w.getnchannels(), w.getsampwidth(), w.getframerate()
        dados = w.readframes(w.getnframes())
    if largura != 2:
        raise ValueError(f"WAV de {8 * largura} bits (a interpretação lê o de 16)")
    som = np.frombuffer(dados, "<i2").astype(np.float64) / 32768
    if canais > 1:
        som = som[:len(som) // canais * canais].reshape(-1, canais).mean(axis=1)
    return som, taxa


def gravar_wav(caminho: str | Path, som: np.ndarray, taxa: int) -> None:
    with wave.open(str(caminho), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(taxa)
        w.writeframes((np.clip(som, -1, 1) * 32767).astype("<i2").tobytes())


# ----------------------------------------------------------------- as medidas
def _curva(n: int, taxa: int, hz: float, rng) -> np.ndarray:
    """Uma curva suave e irregular, de -1 a 1, que muda umas `hz` vezes por segundo."""
    pontos = max(2, int(n / taxa * hz) + 2)
    valores = rng.uniform(-1, 1, pontos)
    x = np.linspace(0, pontos - 1, n)
    i = np.minimum(x.astype(int), pontos - 2)
    f = (1 - np.cos(np.pi * (x - i))) / 2
    return valores[i] * (1 - f) + valores[i + 1] * f


def _envelope(som: np.ndarray, taxa: int, janela: float = 0.02) -> np.ndarray:
    """O volume (RMS) de cada pedacinho, amostra por amostra."""
    n = max(1, int(janela * taxa))
    quadrado = np.convolve(som ** 2, np.ones(n) / n, mode="same")
    return np.sqrt(np.maximum(quadrado, 0))


def _voz_e_pausas(som: np.ndarray, taxa: int, pausa_min: float = 0.2) -> tuple[np.ndarray, list[tuple[int, int]]]:
    """(onde tem voz, amostra por amostra; as pausas (início, fim) de pelo menos `pausa_min` segundos)."""
    env = _envelope(som, taxa, 0.03)
    voz = env > env.max() * 10 ** (-32 / 20) if env.max() > 0 else np.zeros(len(som), bool)
    if not voz.any():
        return voz, []
    primeira = int(np.argmax(voz))                       # o silêncio antes da 1ª palavra não é pausa
    pausas = [(a, b) for a, b in _trechos(~voz) if a >= primeira and b - a >= pausa_min * taxa]
    return voz, pausas


def _trechos(voz: np.ndarray) -> list[tuple[int, int]]:
    """Os trechos (início, fim) onde `voz` é verdadeiro."""
    bordas = np.flatnonzero(np.diff(np.r_[0, voz.astype(np.int8), 0]))
    return [(int(a), int(b)) for a, b in zip(bordas[::2], bordas[1::2])]


def _crescendo(voz: np.ndarray, taxa: int) -> np.ndarray:
    """De 0,6 a 1,25 dentro de cada trecho com voz: o choro treme mais no fim da frase."""
    curva = np.ones(len(voz))
    for a, b in _trechos(voz):
        curva[a:b] = np.linspace(0.6, 1.25, b - a)
    n = max(1, int(0.05 * taxa))
    return np.convolve(curva, np.ones(n) / n, mode="same")


def _rms(som: np.ndarray, voz: np.ndarray | None = None) -> float:
    trecho = som[voz] if voz is not None and voz.any() else som
    return float(np.sqrt(np.mean(trecho ** 2))) if len(trecho) else 0.0


# ----------------------------------------------------------------- o que muda na voz
def mudar_tom(som: np.ndarray, taxa: int, semitons: float, ffmpeg: str | None,
              executar=subprocess.run) -> np.ndarray:
    """O tom sobe ou desce sem mudar a duração (pelo ffmpeg: asetrate + atempo). Sem o ffmpeg, fica como está."""
    if not ffmpeg or abs(semitons) < 0.05 or not len(som):
        return som
    k = 2 ** (semitons / 12)
    filtro = f"asetrate={taxa * k:.3f},aresample={taxa},atempo={1 / k:.6f}"
    try:
        r = executar([ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "s16le", "-ar", str(taxa), "-ac", "1",
                      "-i", "pipe:0", "-af", filtro, "-f", "s16le", "-ac", "1", "pipe:1"],
                     input=(np.clip(som, -1, 1) * 32767).astype("<i2").tobytes(), capture_output=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return som
    if r.returncode != 0 or not r.stdout:
        return som
    novo = np.frombuffer(r.stdout[:len(r.stdout) // 2 * 2], "<i2").astype(np.float64) / 32768
    return np.pad(novo, (0, max(0, len(som) - len(novo))))[:len(som)]


def _quebras(n: int, taxa: int, voz: np.ndarray, por_segundo: float, rng) -> np.ndarray:
    """Cents: a voz que "quebra" para o agudo por um instante (60-100 ms, 2 a 4 semitons), no fim das frases."""
    curva = np.zeros(n)
    trechos = [(a, b) for a, b in _trechos(voz) if b - a > 0.3 * taxa]
    segundos = voz.sum() / taxa
    quantas = int(round(por_segundo * segundos))
    if por_segundo > 0 and segundos >= 0.8:
        quantas = max(1, quantas)
    for _ in range(quantas if trechos else 0):
        a, b = trechos[int(rng.integers(len(trechos)))]
        centro = int(a + (b - a) * rng.uniform(0.5, 0.95))
        largura = rng.uniform(0.06, 0.1) * taxa
        x = (np.arange(n) - centro) / (largura / 2.5)
        curva += rng.uniform(200, 400) * np.exp(-0.5 * x ** 2)
    return curva


def _acentos(som: np.ndarray, taxa: int, voz: np.ndarray, cents: float) -> np.ndarray:
    """Cents: o tom acompanha a força de cada sílaba (sobe nas fortes, desce nas fracas; a média fica no lugar)."""
    env = _envelope(som, taxa, 0.08)
    if not voz.any() or env.max() <= 0:
        return np.zeros(len(som))
    db = 20 * np.log10(np.maximum(env, env.max() * 1e-3) / np.median(env[voz]))
    curva = np.clip(db / 6, -1, 1.5) * cents * voz
    return curva - curva[voz].mean() * voz


def mexer_no_tom(som: np.ndarray, taxa: int, desvio: np.ndarray) -> np.ndarray:
    """O tom muda amostra por amostra (`desvio` em cents): a fala é lida um pouco mais rápido (mais agudo) e mais
    devagar (mais grave), como uma fita. Com a média perto de zero, a duração e o ritmo não mudam."""
    n = len(som)
    tempo = np.concatenate([[0.0], np.cumsum(2 ** (desvio[:-1] / 1200))])
    return np.interp(np.clip(tempo, 0, n - 1), np.arange(n), som)


def tremor(n: int, taxa: int, cents: float, hz: float, voz: np.ndarray, rng) -> tuple[np.ndarray, np.ndarray]:
    """(cents, fase): o tom oscila umas `hz` vezes por segundo, irregular, mais no fim das frases e com o
    tremidinho rápido da voz instável (como a voz de quem chora)."""
    freq = hz * (1 + 0.25 * _curva(n, taxa, 1.5, rng))
    fase = 2 * np.pi * np.cumsum(freq) / taxa + rng.uniform(0, 2 * np.pi)
    profundidade = cents * (0.8 + 0.3 * _curva(n, taxa, 2.0, rng)) * _crescendo(voz, taxa)
    return profundidade * np.sin(fase) + cents * 0.25 * _curva(n, taxa, 14.0, rng), fase


def _levinson(r: np.ndarray, ordem: int) -> tuple[np.ndarray, float]:
    a, erro = np.zeros(ordem + 1), float(r[0])
    a[0] = 1.0
    for i in range(1, ordem + 1):
        k = -(r[i] + np.dot(a[1:i], r[i - 1:0:-1])) / erro
        a[1:i] = a[1:i] + k * a[i - 1:0:-1]
        a[i] = k
        erro *= max(1e-6, 1 - k * k)
    return a, erro


def ar_da_voz(som: np.ndarray, taxa: int, rng, ordem: int = 18) -> np.ndarray:
    """O sopro com o mesmo "formato de boca" (LPC) de cada pedacinho da fala, sem a vibração da voz: o sussurro dela
    (e o ar que se mistura na voz soprada)."""
    n = int(0.025 * taxa)
    passo, janela, tamanho = n // 2, np.hanning(n), 4 * n
    saida = np.zeros(len(som) + n)
    for i in range(0, max(0, len(som) - n) + 1, passo):
        q = som[i:i + n]
        if len(q) < n:
            break
        q = q * janela
        r = np.correlate(q, q, "full")[n - 1:n + ordem]
        if r[0] <= 1e-10:
            continue
        a, erro = _levinson(r, ordem)
        espectro = np.fft.rfft(rng.standard_normal(n), tamanho) / np.fft.rfft(a, tamanho)
        saida[i:i + n] += np.fft.irfft(espectro, tamanho)[:n] * np.sqrt(max(erro, 0.0) / n) * janela
    return saida[:len(som)]


def equalizar(som: np.ndarray, taxa: int, presenca: float = 0.0, brilho: float = 0.0, graves: float = 0.0
              ) -> np.ndarray:
    """dB a mais (ou a menos) nos 2-4 kHz (presença: a voz forçada), acima de 4,5 kHz (brilho) e abaixo de 180 Hz."""
    if not (presenca or brilho or graves) or not len(som):
        return som
    f = np.fft.rfftfreq(len(som), 1 / taxa)
    oitavas = np.log2(np.maximum(f, 1) / 2900)
    db = presenca * np.exp(-0.5 * (oitavas / 0.6) ** 2)
    db += brilho / (1 + np.exp(-(f - 4500) / 600))
    db += graves / (1 + np.exp((f - 180) / 40))
    return np.fft.irfft(np.fft.rfft(som) * 10 ** (db / 20), len(som))


def _ruido_de_inspiracao(n: int, taxa: int, rng) -> np.ndarray:
    """O som do ar entrando pela boca aberta (o "hhh" do soluço): ruído com as ressonâncias da boca."""
    f = np.fft.rfftfreq(n, 1 / taxa)
    forma = sum(alt * np.exp(-0.5 * ((f - centro) / largura) ** 2)
                for centro, largura, alt in ((700, 250, 0.6), (1300, 400, 1.0), (2600, 700, 0.8), (4200, 1200, 0.4)))
    forma = (forma + 0.04) * (f > 300)
    ruido = np.fft.irfft(np.fft.rfft(rng.standard_normal(n)) * forma, n)
    return ruido / (np.sqrt(np.mean(ruido ** 2)) + 1e-12)


def solucar(som: np.ndarray, taxa: int, pausas: list[tuple[int, int]], nivel: float, rng) -> tuple[np.ndarray, int]:
    """Nas pausas, a inspiração do choro (às vezes entrecortada, em 2 ou 3 puxadas), logo antes de voltar a falar (e
    logo depois da última frase). (som, quantas)"""
    saida, quantas = som.copy(), 0
    for inicio, fim in pausas:
        tamanho = min(0.45, (fim - inicio) / taxa - 0.07)
        if tamanho < 0.15:
            continue
        g = int(tamanho * taxa)
        ponta = fim - int(0.03 * taxa) if fim < len(som) else inicio + int(0.06 * taxa) + g
        ponta = min(ponta, len(som))
        if ponta - g < inicio:
            continue
        t = np.linspace(0, 1, g)
        if tamanho >= 0.3 and rng.random() < 0.6:          # entrecortada: 2 ou 3 puxadas curtas
            puxadas = int(rng.integers(2, 4))
            envelope = np.clip(np.sin(np.pi * (t * puxadas % 1)), 0, None) ** 0.8 * (0.6 + 0.4 * t)
        else:                                               # uma puxada só, que cresce e para de repente
            envelope = t ** 1.3 * np.minimum(1, (1 - t) / 0.15)
        envelope *= 1 + 0.15 * _curva(g, taxa, 25, rng)
        saida[ponta - g:ponta] += _ruido_de_inspiracao(g, taxa, rng) * envelope * nivel
        quantas += 1
    return saida, quantas


def embargar(som: np.ndarray, taxa: int, voz: np.ndarray, por_segundo: float, ar: np.ndarray, rng
             ) -> tuple[np.ndarray, int]:
    """A voz que falha (embarga) por um instante, de preferência no fim das frases: some a voz e fica o ar."""
    segundos = voz.sum() / taxa
    quantas = int(round(por_segundo * segundos))
    if por_segundo > 0 and segundos >= 0.8:
        quantas = max(1, quantas)
    trechos = [(a, b) for a, b in _trechos(voz) if b - a > 0.3 * taxa]
    if not quantas or not trechos:
        return som, 0
    saida, feitas = som.copy(), 0
    for _ in range(quantas):
        a, b = trechos[int(rng.integers(len(trechos)))]
        centro = int(a + (b - a) * rng.uniform(0.45, 0.92))
        largura = int(rng.uniform(0.05, 0.09) * taxa)
        rampa = max(1, int(0.012 * taxa))
        inicio, fim = max(0, centro - largura // 2), min(len(som), centro + largura // 2)
        if fim - inicio <= 2 * rampa:
            continue
        g = np.ones(fim - inicio)
        g[:rampa] = np.cos(np.linspace(0, np.pi / 2, rampa)) ** 2 * 0.92 + 0.08
        g[rampa:-rampa] = 0.08
        g[-rampa:] = np.sin(np.linspace(0, np.pi / 2, rampa)) ** 2 * 0.92 + 0.08
        saida[inicio:fim] = saida[inicio:fim] * g + ar[inicio:fim] * (1 - g) * 0.6
        feitas += 1
    return saida, feitas


def enfatizar(som: np.ndarray, taxa: int, voz: np.ndarray, quanto: float) -> np.ndarray:
    """As sílabas fortes mais fortes e as fracas mais fracas (a fala "batida" de quem briga)."""
    if quanto <= 0:
        return som
    env = _envelope(som, taxa, 0.12)
    ref = np.percentile(env[voz], 70) if voz.any() else env.max()
    if ref <= 0:
        return som
    return som * np.clip((env / ref) ** (0.8 * quanto), 0.45, 1.8)


def rasgar(som: np.ndarray, taxa: int, aspereza: float, saturacao: float, voz: np.ndarray, rng) -> np.ndarray:
    """A voz rasgada: o volume treme muito rápido e irregular (35-65 vezes por segundo: a aspereza das pregas vocais
    apertadas) e a saturação do grito (tanh: os picos achatam e nascem os harmônicos agudos)."""
    saida = som
    if aspereza > 0:
        n = len(som)
        freq = 50 * (1 + 0.3 * _curva(n, taxa, 6, rng))
        fase = 2 * np.pi * np.cumsum(freq) / taxa
        forte = np.clip(_envelope(som, taxa, 0.03) / (_rms(som, voz) + 1e-12), 0, 1.5)
        saida = som * (1 - aspereza * 0.5 * (1 + np.sin(fase)) * np.minimum(1, forte))
    if saturacao > 0:
        pico = np.abs(saida).max()
        if pico > 0:
            drive = 1 + 5 * saturacao
            saida = np.tanh(drive * saida / pico) / np.tanh(drive) * pico
            f = np.fft.rfftfreq(len(saida), 1 / taxa)            # sem o chiado digital dos harmônicos lá no alto
            saida = np.fft.irfft(np.fft.rfft(saida) / (1 + (f / 7500) ** 6), len(saida))
    return saida


def _limitar(som: np.ndarray) -> np.ndarray:
    """Sem passar de LIMITE: os picos dobram suave (tanh) em vez de estourar."""
    pico = np.abs(som).max() if len(som) else 0
    if pico <= LIMITE:
        return som
    acima = np.abs(som) > LIMITE * 0.8
    saida = som.copy()
    joelho = LIMITE * 0.8
    folga = LIMITE - joelho
    excesso = (np.abs(som[acima]) - joelho) / folga
    saida[acima] = np.sign(som[acima]) * (joelho + folga * np.tanh(excesso))
    return saida


def mudar_formantes(som: np.ndarray, taxa: int, fator: float, voltas: int = 8) -> np.ndarray:
    """A "garganta" menor (fator > 1: voz mais jovem) ou maior (< 1: mais encorpada): o envelope do espectro (os
    formantes, que dizem o tamanho de quem fala) estica ou encolhe no eixo das frequências; o tom (os harmônicos)
    fica onde está. O envelope de cada pedacinho de ~43 ms é o "envelope verdadeiro" (o cepstro alisado que, volta a
    volta, sobe até encostar nos picos dos harmônicos)."""
    if abs(fator - 1) < 0.005 or len(som) < 64:
        return som
    n = 1024 if taxa >= 16000 else 512
    passo, corte = n // 4, max(8, int(taxa / 700))            # (o tom de até ~350 Hz fica fora do envelope)
    janela = np.hanning(n + 1)[:-1]
    x = np.pad(som, (n, n))
    quadros = np.lib.stride_tricks.sliding_window_view(x, n)[::passo] * janela
    espectro = np.fft.rfft(quadros, axis=1)
    medido = np.log(np.abs(espectro) + 1e-9)
    alvo = medido
    for _ in range(voltas):
        cepstro = np.fft.irfft(alvo, n, axis=1)
        cepstro[:, corte:n - corte + 1] = 0
        envelope = np.fft.rfft(cepstro, axis=1).real
        alvo = np.maximum(medido, envelope)
    faixas = envelope.shape[1]
    onde = np.clip(np.arange(faixas) / fator, 0, faixas - 1)
    i = np.minimum(onde.astype(int), faixas - 2)
    f = onde - i
    novo_envelope = envelope[:, i] * (1 - f) + envelope[:, i + 1] * f
    saida_quadros = np.fft.irfft(espectro * np.exp(novo_envelope - envelope), n, axis=1) * janela
    saida, pesos = np.zeros(len(x)), np.zeros(len(x))
    for k, quadro in enumerate(saida_quadros):
        saida[k * passo:k * passo + n] += quadro
        pesos[k * passo:k * passo + n] += janela ** 2
    saida = saida / np.maximum(pesos, 1e-3)
    return saida[n:n + len(som)]


def variar_som(som: np.ndarray, taxa: int, semitons: float, formantes: float, ffmpeg: str | None = None,
               executar=subprocess.run) -> np.ndarray:
    """A VARIANTE de uma voz: outro tom (semitons) e outra "garganta" (formantes: 1,10 = 10% menor). O ffmpeg sobe o
    tom e a garganta juntos; a garganta é acertada depois. Sem o ffmpeg, muda só a garganta. Mesma duração e volume."""
    if not len(som) or not np.abs(som).max():
        return som
    tom = mudar_tom(som, taxa, semitons, ffmpeg, executar)
    ja_subiu = 2 ** (semitons / 12) if tom is not som else 1.0
    saida = mudar_formantes(tom, taxa, formantes / ja_subiu)
    saida = saida * (_rms(som) / (_rms(saida) + 1e-12))
    return _limitar(saida)


def variar(wav: str | Path, semitons: float, formantes: float, ffmpeg: str | None = None,
           executar=subprocess.run) -> bool:
    """A variante na fala gravada em `wav` (no lugar). False se não deu para ler (fica como está)."""
    wav = Path(wav)
    try:
        som, taxa = ler_wav(wav)
    except (OSError, EOFError, ValueError, wave.Error):
        return False
    temporario = wav.with_name(wav.stem + ".variante.wav")
    gravar_wav(temporario, variar_som(som, taxa, semitons, formantes, ffmpeg, executar), taxa)
    temporario.replace(wav)
    return True


# ----------------------------------------------------------------- tudo junto
def interpretar_som(som: np.ndarray, taxa: int, emocao: str, forca: float = 1.0, ffmpeg: str | None = None,
                    semente: int = 0, executar=subprocess.run) -> tuple[np.ndarray, dict]:
    """A fala com a interpretação da emoção (a mesma duração). (som novo, o que foi feito)"""
    r = receita(emocao, forca)
    if r is None or not len(som) or not np.abs(som).max():
        return som, {}
    rng = np.random.default_rng(semente)
    voz, pausas = _voz_e_pausas(som, taxa)
    rms_antes = _rms(som, voz)
    feito: dict = {"emocao": emocao, "forca": round(forca, 2)}
    saida = mudar_tom(som, taxa, r.semitons, ffmpeg, executar)
    if r.semitons and saida is not som:
        feito["semitons"] = round(r.semitons, 2)
    if r.sussurro > 0:
        ar = ar_da_voz(saida, taxa, rng)
        ar *= _rms(saida, voz) / (_rms(ar, voz) + 1e-12)
        saida = saida * (1 - r.sussurro) + ar * r.sussurro
        feito["sussurro"] = round(r.sussurro, 2)
    desvio, fase = np.zeros(len(saida)), None
    if r.tremor > 0:
        desvio, fase = tremor(len(saida), taxa, r.tremor, r.tremor_hz, voz, rng)
        feito["tremor"] = f"{r.tremor:.0f} cents, {r.tremor_hz:g} Hz"
    if r.quebras > 0:
        desvio = desvio + _quebras(len(saida), taxa, voz, r.quebras, rng)
        feito["quebras"] = True
    if r.acento > 0:
        desvio = desvio + _acentos(som, taxa, voz, r.acento)
        feito["acento"] = round(r.acento)
    if desvio.any():
        saida = mexer_no_tom(saida, taxa, desvio)
    if fase is not None and r.pulso > 0:
        saida = saida * (1 - r.pulso * 0.5 * (1 + np.sin(fase + 0.6)))
    if r.ar > 0 or r.falhas > 0:
        ar = ar_da_voz(saida, taxa, rng)
        ar = equalizar(ar, taxa, brilho=6.0, graves=-12.0)          # o ar da voz é mais agudo que ela
        ar *= _rms(saida, voz) / (_rms(ar, voz) + 1e-12)
        if r.ar > 0:
            saida = saida * (1 - 0.3 * r.ar) + ar * r.ar * 0.6
            feito["ar"] = round(r.ar, 2)
        if r.falhas > 0:
            saida, quantas = embargar(saida, taxa, voz, r.falhas, ar, rng)
            if quantas:
                feito["falhas"] = quantas
    saida = equalizar(saida, taxa, r.presenca, r.brilho, graves=-4.0 * min(1.0, r.presenca / 6))
    if r.enfase > 0:
        saida = enfatizar(saida, taxa, voz, r.enfase)
    if r.aspereza > 0 or r.saturacao > 0:
        saida = rasgar(saida, taxa, r.aspereza, r.saturacao, voz, rng)
        feito["rasgada"] = round(max(r.aspereza, r.saturacao), 2)
    saida *= rms_antes / (_rms(saida, voz) + 1e-12) * 10 ** (r.volume / 20)
    if r.soluco > 0:
        saida, quantas = solucar(saida, taxa, pausas, rms_antes * 0.3 * r.soluco, rng)
        if quantas:
            feito["soluços"] = quantas
    return _limitar(saida), feito


def interpretar(wav: str | Path, emocao: str, forca: float = 1.0, ffmpeg: str | None = None,
                executar=subprocess.run) -> dict:
    """Interpreta a fala gravada em `wav` (no lugar). {} se não mudou nada (emoção normal, força 0, WAV que não é de
    16 bits). A mesma fala sai sempre igual (a "sorte" das falhas e dos soluços vem do nome do arquivo)."""
    wav = Path(wav)
    if receita(emocao, forca) is None:
        return {}
    try:
        som, taxa = ler_wav(wav)
    except (OSError, EOFError, ValueError, wave.Error):
        return {}
    novo, feito = interpretar_som(som, taxa, emocao, forca, ffmpeg, zlib.crc32(wav.name.encode()), executar)
    if not feito:
        return {}
    temporario = wav.with_name(wav.stem + ".interpretada.wav")
    gravar_wav(temporario, novo, taxa)
    temporario.replace(wav)
    return feito


def resumo(feito: dict) -> str:
    """'tremor 75 cents, 6 Hz · 2 falha(s) · 3 soluço(s)' (o que a interpretação fez, para o registro)."""
    partes = []
    if "semitons" in feito:
        s = feito["semitons"]
        partes.append(f"tom {s:+g} {'semitom' if abs(s) == 1 else 'semitons'}".replace(".", ","))
    if "tremor" in feito:
        partes.append(f"tremor {feito['tremor']}")
    if "quebras" in feito:
        partes.append("voz quebrando")
    if "acento" in feito:
        partes.append("tom batendo nas sílabas fortes")
    if "ar" in feito:
        partes.append("voz soprada")
    if "falhas" in feito:
        partes.append(f"{feito['falhas']} falha(s) na voz")
    if "soluços" in feito:
        partes.append(f"{feito['soluços']} soluço(s)")
    if "rasgada" in feito:
        partes.append("voz rasgada")
    if "sussurro" in feito:
        partes.append("sussurrada")
    return " · ".join(partes)
