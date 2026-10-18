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


def test_emocao_pelo_volume_grito_e_sussurro(tmp_path):
    """Comparada com as outras falas do filme: bem mais alta = gritando; bem mais baixa e sem "vibração" = sussurro."""
    normais = [(SimpleNamespace(tempo=f"00:00:{2 * i:02d},000 --> 00:00:{2 * i + 1:02d},500"), f"Fala {i}.")
               for i in range(10)]
    falas = normais + [(SimpleNamespace(tempo="00:00:30,000 --> 00:00:31,500"), "Sai daqui!"),
                       (SimpleNamespace(tempo="00:00:40,000 --> 00:00:41,500"), "Fala baixo."),
                       (SimpleNamespace(tempo="00:00:50,000 --> 00:00:51,500"), "Agora!")]
    trechos = {k: voz(130 + 7 * k) for k in range(10)}
    trechos[10] = voz(150) * 3.5                                       # ~11 dB acima: grito
    trechos[11] = np.random.default_rng(3).standard_normal(int(gl.TAXA * 1.5)) * 0.02   # baixo e só "ar"
    trechos[12] = voz(140) * 2.2                                       # ~7 dB acima, com "!": também grito

    def ler(ffmpeg, video, inicio, duracao):
        som = np.zeros(int((duracao + 1) * gl.TAXA), dtype=np.float32)
        for k, (fala, _) in enumerate(falas):
            a = float(fala.tempo[6:8]) - inicio
            if 0 <= a < duracao:
                trecho = trechos[k]
                som[int(a * gl.TAXA):int(a * gl.TAXA) + len(trecho)] = trecho
        return som
    ouvidas = gl.ouvir_generos("filme.mkv", falas, list(range(13)), "ffmpeg", tmp_path / "g.json", ler=ler,
                               emocao=True)
    assert (ouvidas[10].tom, ouvidas[11].tom, ouvidas[12].tom) == (gl.TOM_GRITO, gl.TOM_SUSSURRO, gl.TOM_GRITO)
    assert all(ouvidas[k].tom == "" for k in range(10)) and ouvidas[10].genero == "m"
    assert "Nesta fala: gritando" in ouvidas[10].nota()
    sem = gl.ouvir_generos("filme.mkv", falas, [10, 11], "ffmpeg", tmp_path / "g.json", ler=ler)   # desligada
    assert sem[10].tom == "" and sem[11].tom == ""


def test_tom_pelo_volume_precisa_de_falas_para_comparar():
    assert gl.tom_pelo_volume(-10.0, None, 0.9) == ""                       # sem o "normal" do filme
    assert gl.tom_pelo_volume(-70.0, -20.0, 0.0) == ""                      # silêncio não é sussurro
    assert gl.tom_pelo_volume(-15.0, -20.0, 0.9, "Oi!") == ""               # só 5 dB: não é grito
    assert gl.tom_pelo_volume(-13.0, -20.0, 0.9, "Oi!") == gl.TOM_GRITO     # 7 dB com "!": é
    assert gl.tom_pelo_volume(-31.0, -20.0, 0.8) == ""                      # baixo, mas com voz: fala baixa normal
