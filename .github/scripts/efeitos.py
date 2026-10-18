"""O "original" da cena de exemplo: o grito mais alto e o sussurro (a voz sem a vibração das cordas vocais)."""
import numpy as np
from scipy.signal import lfilter


def levinson(r, ordem):
    a = np.zeros(ordem + 1)
    a[0], erro = 1.0, r[0]
    for i in range(1, ordem + 1):
        k = -(r[i] + np.dot(a[1:i], r[i - 1:0:-1])) / erro
        a[1:i] = a[1:i] + k * a[i - 1:0:-1]
        a[i] = k
        erro *= (1 - k * k)
    return a, erro


def sussurrar(som, taxa=24000, ordem=18, semente=5):
    """O mesmo "formato de boca" (LPC) de cada pedacinho, mas soprado com ruído no lugar da voz: um sussurro."""
    n = int(0.025 * taxa)
    passo, janela = n // 2, np.hanning(n)
    saida = np.zeros(len(som) + n)
    rng = np.random.default_rng(semente)
    for i in range(0, len(som) - n, passo):
        q = som[i:i + n] * janela
        r = np.correlate(q, q, "full")[n - 1:n + ordem]
        if r[0] <= 1e-9:
            continue
        a, erro = levinson(r, ordem)
        ruido = rng.standard_normal(n) * np.sqrt(max(erro, 0.0) / n)
        saida[i:i + n] += lfilter([1.0], a, ruido) * janela
    return saida[:len(som)]


def no_volume(som, rms):
    return som * (rms / (np.sqrt(np.mean(som ** 2)) + 1e-12))
