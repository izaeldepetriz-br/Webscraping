"""Gênero de quem fala pelo tom da voz (no PC, sem o Gemini): a medida da altura e a leitura das falas."""
from types import SimpleNamespace

import numpy as np

from jellyfin_tools import genero_local as gl


def voz(f0: float, segundos: float = 1.5, taxa: int = gl.TAXA) -> np.ndarray:
    """Um som com a altura f0 e os harmônicos de uma voz (mais um pouco de chiado)."""
    t = np.arange(int(taxa * segundos)) / taxa
    som = sum(np.sin(2 * np.pi * f0 * h * t) / h for h in range(1, 15))
    return 0.3 * som / np.abs(som).max() + 0.01 * np.random.default_rng(1).standard_normal(len(t))


def test_tom_medio_e_genero():
    for f0, genero in ((105, "m"), (130, "m"), (172, "?"), (215, "f"), (250, "f")):
        medido = gl.tom_medio(voz(f0))
        assert abs(medido - f0) < f0 * 0.04 and gl.genero_pelo_tom(medido) == genero
    assert gl.tom_medio(np.zeros(gl.TAXA)) is None                                   # silêncio
    assert gl.tom_medio(np.random.default_rng(2).standard_normal(gl.TAXA) * 0.3) is None   # chiado sem voz
    assert gl.genero_pelo_tom(None) == "?"


def test_ouvir_generos_le_em_blocos_e_guarda(tmp_path):
    falas = [(SimpleNamespace(tempo="00:00:01,000 --> 00:00:02,500"), "Oi."),
             (SimpleNamespace(tempo="00:00:03,000 --> 00:00:04,500"), "Olá."),
             (SimpleNamespace(tempo="00:03:00,000 --> 00:03:01,500"), "Tchau.")]
    lidos = []

    def ler(ffmpeg, video, inicio, duracao):          # o "vídeo": homem, mulher e, 3 min depois, homem de novo
        lidos.append((round(inicio, 1), round(duracao, 1)))
        partes = {1.0: np.concatenate([voz(120), np.zeros(gl.TAXA // 2), voz(220), np.zeros(gl.TAXA // 10)]),
                  180.0: np.concatenate([voz(120), np.zeros(gl.TAXA // 10)])}
        return partes[round(inicio, 1)]
    arquivo = tmp_path / "generos.json"
    ouvidas = gl.ouvir_generos("filme.mkv", falas, [2, 0, 1], "ffmpeg", arquivo, ler=ler)
    assert {k: o.genero for k, o in ouvidas.items()} == {0: "m", 1: "f", 2: "m"}
    assert lidos == [(1.0, 3.6), (180.0, 1.6)]                                       # 2 blocos, não 3 leituras
    lidos.clear()
    assert gl.ouvir_generos("filme.mkv", falas, [0, 1, 2], "ffmpeg", arquivo, ler=ler)[1].genero == "f"
    assert lidos == []                                                               # tudo do que foi guardado
