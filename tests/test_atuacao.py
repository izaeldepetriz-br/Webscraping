"""A interpretação das falas com emoção (atuacao.py), medida numa "voz" de mentira (um tom com harmônicos, em
sílabas e pausas): o choro treme e soluça nas pausas, a raiva fica com mais agudos e mais densa, o sussurro perde a
vibração, e a duração nunca muda."""
import shutil
import wave

import numpy as np
import pytest

from jellyfin_tools import atuacao as at
from jellyfin_tools import emocoes as em
from tests.test_voz_clonada import FFMPEG

TAXA = 24000


def voz_falsa(f0: float = 150.0) -> np.ndarray:
    """3 sílabas, uma pausa de 0,6 s e mais 2 sílabas: a "fala" com harmônicos (como a voz) e o volume de cada sílaba."""
    partes = []
    for duracao, pausa in ((0.35, 0.05), (0.3, 0.05), (0.4, 0.6), (0.35, 0.05), (0.45, 0.2)):
        t = np.arange(int(duracao * TAXA)) / TAXA
        som = sum(np.sin(2 * np.pi * f0 * h * t) / h for h in range(1, 12))
        partes += [som * np.hanning(len(t)) ** 0.3 * 0.25, np.zeros(int(pausa * TAXA))]
    return np.concatenate(partes)


def f0_por_quadro(som: np.ndarray, centro: float = 150.0) -> np.ndarray:
    """O tom de cada pedacinho de 30 ms com voz (pela autocorrelação, perto do tom esperado)."""
    n, passo, saida = int(0.03 * TAXA), int(0.005 * TAXA), []
    menor, maior = int(TAXA / (centro * 1.6)), int(TAXA / (centro / 1.6))
    for i in range(0, len(som) - n - maior, passo):
        a = som[i:i + n]
        if np.sqrt(np.mean(a ** 2)) < 0.02:
            continue
        c = [np.dot(a, som[i + k:i + k + n]) / (np.linalg.norm(a) * np.linalg.norm(som[i + k:i + k + n]) + 1e-12)
             for k in range(menor, maior)]
        k = int(np.argmax(c))
        if c[k] > 0.6:
            saida.append(TAXA / (menor + k))
    return np.array(saida)


def agudos(som: np.ndarray) -> float:
    espectro, f = np.abs(np.fft.rfft(som)) ** 2, np.fft.rfftfreq(len(som), 1 / TAXA)
    return 10 * np.log10(espectro[(f >= 2000) & (f < 4000)].sum() / espectro[(f >= 100) & (f < 1000)].sum())


def crista(som: np.ndarray) -> float:
    return 20 * np.log10(np.abs(som).max() / np.sqrt(np.mean(som ** 2)))


def test_choro_treme_quebra_e_solua_nas_pausas():
    som = voz_falsa()
    novo, feito = at.interpretar_som(som, TAXA, "choro", 1.0, ffmpeg=None, semente=3)
    assert len(novo) == len(som) and np.abs(novo).max() <= at.LIMITE + 1e-9
    antes, depois = f0_por_quadro(som), f0_por_quadro(novo)
    assert np.std(1200 * np.log2(antes / 150)) < 5                         # a voz de mentira é reta
    assert np.std(1200 * np.log2(depois / np.median(depois))) > 35         # chorando, o tom oscila
    assert {"tremor", "quebras", "ar", "soluços"} <= set(feito) and "semitons" not in feito   # (sem o ffmpeg)
    pausa = slice(int(1.25 * TAXA), int(1.65 * TAXA))                       # o meio da pausa de 0,6 s
    assert not som[pausa].any() and np.sqrt(np.mean(novo[pausa] ** 2)) > 0.005   # puxa o ar na pausa
    assert "tremor 90 cents" in at.resumo(feito) and "soluço" in at.resumo(feito)


def test_raiva_e_grito_forcados_e_rasgados():
    som = voz_falsa()
    for emocao, mais_agudos in (("brava", 3), ("grito", 4)):
        novo, feito = at.interpretar_som(som, TAXA, emocao, 1.0, ffmpeg=None, semente=1)
        assert len(novo) == len(som) and "rasgada" in feito and "acento" in feito
        assert agudos(novo) > agudos(som) + mais_agudos                    # a voz forçada (2-4 kHz)
        assert crista(novo) < crista(som) - 1                              # saturada: mais densa
        assert np.sqrt(np.mean(novo ** 2)) > np.sqrt(np.mean(som ** 2))     # e mais alta


def test_sussurro_sem_a_vibracao_da_voz():
    som = voz_falsa()
    novo, feito = at.interpretar_som(som, TAXA, "sussurro", 1.0, semente=2)
    trecho = slice(int(0.05 * TAXA), int(0.3 * TAXA))
    periodo = round(TAXA / 150)

    def vibracao(x):
        a, b = x[trecho], x[trecho.start + periodo:trecho.stop + periodo]
        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))
    assert vibracao(som) > 0.9 and vibracao(novo) < 0.5 and feito["sussurro"] == 0.9
    assert np.sqrt(np.mean(novo ** 2)) < np.sqrt(np.mean(som ** 2)) / 2     # e baixinho


def test_forca_e_receitas():
    assert em.forca_do_menu("Leve") == 0.45 and em.forca_do_menu("???") == 1.0
    assert set(em.FORCAS) == {"Desligada", "Leve", "Média", "Forte"} and em.FORCA_PADRAO == "Forte"
    assert at.receita("choro", 0.5).tremor == 45 and at.receita("choro", 0.5).tremor_hz == 6.0
    assert at.receita("normal") is None and at.receita("choro", 0) is None and at.receita("???") is None
    assert set(at.RECEITAS) == set(em.EMOCOES)                             # toda emoção tem a sua interpretação
    assert em.intensidade_chatterbox("choro") == em.CHATTERBOX["choro"]     # força 0: como na v2.20
    assert em.intensidade_chatterbox("brava", 1.0) == (round(1.1 * 1.35, 2), 0.4)
    assert em.intensidade_chatterbox("grito", 1.0)[0] == em.EXAGERO_MAX     # sem passar do limite


def gravar(caminho, som, largura=2):
    with wave.open(str(caminho), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(largura)
        w.setframerate(TAXA)
        if largura == 2:
            w.writeframes((som * 32767).astype("<i2").tobytes())
        else:
            w.writeframes(((som + 1) * 127).astype(np.uint8).tobytes())
    return caminho


def test_interpretar_o_arquivo(tmp_path):
    som = voz_falsa()
    a, b = gravar(tmp_path / "fala_07.wav", som), tmp_path / "copia" / "fala_07.wav"
    b.parent.mkdir()
    shutil.copy(a, b)
    original = a.read_bytes()
    assert at.interpretar(a, "normal") == {} and at.interpretar(a, "choro", 0.0) == {}
    assert a.read_bytes() == original                                      # normal ou desligada: nada muda
    feito = at.interpretar(a, "choro", 1.0)
    assert feito and a.read_bytes() != original and not list(tmp_path.glob("*.interpretada.wav"))
    assert at.interpretar(b, "choro", 1.0) == feito and b.read_bytes() == a.read_bytes()   # a mesma fala, igual
    with wave.open(str(a)) as w:
        assert w.getnframes() == len(som) and w.getframerate() == TAXA
    oito = gravar(tmp_path / "oito_bits.wav", som, largura=1)
    antes = oito.read_bytes()
    assert at.interpretar(oito, "choro") == {} and oito.read_bytes() == antes      # não sabe ler: fica como está
    (tmp_path / "quebrado.wav").write_bytes(b"RIFF")
    assert at.interpretar(tmp_path / "quebrado.wav", "brava") == {}


@pytest.mark.skipif(not FFMPEG, reason="sem ffmpeg")
def test_tom_sobe_sem_mudar_a_duracao():
    som = voz_falsa()
    novo = at.mudar_tom(som, TAXA, 2.0, FFMPEG)
    assert len(novo) == len(som)
    assert abs(np.median(f0_por_quadro(novo, 170)) / 150 - 2 ** (2 / 12)) < 0.03
    assert at.mudar_tom(som, TAXA, 2.0, None) is som                       # sem o ffmpeg, fica como está
    novo, feito = at.interpretar_som(som, TAXA, "grito", 1.0, FFMPEG)
    assert feito["semitons"] == 2.0 and len(novo) == len(som)


def vogal(f0: float = 140.0, segundos: float = 1.0) -> np.ndarray:
    """Um "a" de mentira: os harmônicos do tom com as ressonâncias da boca (formantes em 700, 1200 e 2600 Hz)."""
    t = np.arange(int(segundos * TAXA)) / TAXA
    som = np.zeros(len(t))
    for h in range(1, int(11000 / f0)):
        amp = sum(a / (1 + ((f0 * h - F) / B) ** 2) for F, B, a in ((700, 90, 1.0), (1200, 110, 0.6), (2600, 160, 0.3)))
        som += amp * np.sin(2 * np.pi * f0 * h * t)
    return som / np.abs(som).max() * 0.5


def centro_dos_formantes(som: np.ndarray, f0: float) -> float:
    """O "centro" do envelope (medido nos harmônicos): sobe quando a garganta fica menor."""
    espectro, f = np.abs(np.fft.rfft(som * np.hanning(len(som)))), np.fft.rfftfreq(len(som), 1 / TAXA)
    harmonicos = np.arange(3, int(3500 / f0)) * f0
    amps = np.array([espectro[np.argmin(abs(f - h))] for h in harmonicos])
    return float((harmonicos * amps ** 2).sum() / (amps ** 2).sum())


def test_garganta_menor_ou_maior_sem_mudar_o_tom():
    som = vogal()
    antes = centro_dos_formantes(som, 140)
    menor, maior = at.mudar_formantes(som, TAXA, 1.10), at.mudar_formantes(som, TAXA, 0.94)
    assert len(menor) == len(som) and at.mudar_formantes(som, TAXA, 1.0) is som
    assert centro_dos_formantes(menor, 140) / antes > 1.04 and centro_dos_formantes(maior, 140) / antes < 0.985
    for x in (menor, maior):                                                 # o tom continua 140 Hz
        assert abs(np.median(f0_por_quadro(x * 0.5 / np.abs(x).max(), 140)) - 140) < 3


@pytest.mark.skipif(not FFMPEG, reason="sem ffmpeg")
def test_variante_jovem_sobe_o_tom_e_a_garganta(tmp_path):
    som = vogal()
    jovem = at.variar_som(som, TAXA, 3.0, 1.10, FFMPEG)
    assert len(jovem) == len(som) and abs(np.sqrt(np.mean(jovem ** 2)) / np.sqrt(np.mean(som ** 2)) - 1) < 0.05
    assert abs(np.median(f0_por_quadro(jovem, 166)) / 140 - 2 ** (3 / 12)) < 0.03
    wav = gravar(tmp_path / "fala.wav", som)
    assert at.variar(wav, -2.5, 0.93, FFMPEG) and at.ler_wav(wav)[0].shape == som.shape
    (tmp_path / "quebrado.wav").write_bytes(b"RIFF")
    assert not at.variar(tmp_path / "quebrado.wav", 2.0, 1.04, FFMPEG)
