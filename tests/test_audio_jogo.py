"""A fala dublada no formato do jogo (WAV, VAG, ADS) e com a duração exata da original: o PS-ADPCM (ida e volta),
os formatos lidos de arquivos de verdade e o encaixe (acelera até 35%, corta com fim suave, completa com silêncio)."""
import struct
import wave

import numpy as np
import pytest

from jellyfin_tools import audio_jogo as aj
from tests.test_voz_clonada import FFMPEG

TAXA = 24000


def tom(segundos: float, taxa: int = TAXA, freq: float = 220.0) -> np.ndarray:
    t = np.arange(int(taxa * segundos)) / taxa
    return (8000 * np.sin(2 * np.pi * freq * t) + 2500 * np.sin(2 * np.pi * 3 * freq * t)).astype(np.int16)


def wav(caminho, som, taxa=TAXA, canais=1):
    with wave.open(str(caminho), "wb") as w:
        w.setnchannels(canais)
        w.setsampwidth(2)
        w.setframerate(taxa)
        w.writeframes(np.repeat(som, canais).astype("<i2").tobytes())
    return caminho


def vag(caminho, som, taxa=22050, nome=b"KRATOS_01", vazio=True, fim07=True):
    corpo = aj.codificar_adpcm(som, inicio_vazio=vazio)
    if fim07:
        corpo += bytes([0, 7]) + bytes([0x77]) * 14
    cab = bytearray(48)
    cab[0:4], cab[4:8] = b"VAGp", struct.pack(">I", 0x20)
    struct.pack_into(">I", cab, 12, len(corpo))
    struct.pack_into(">I", cab, 16, taxa)
    cab[32:32 + len(nome)] = nome
    caminho.write_bytes(bytes(cab) + corpo)
    return caminho


def ads(caminho, som, taxa=48000, canais=2, intercalado=0x400, enchimento=b""):
    canal = aj.codificar_adpcm(som)
    canal = canal.ljust(-(-len(canal) // intercalado) * intercalado, b"\x00")
    dados = b"".join(canal[p:p + intercalado] * canais for p in range(0, len(canal), intercalado))
    cab = b"SShd" + struct.pack("<IIIIIII", 0x18, 0x10, taxa, canais, intercalado, 0, 0xFFFFFFFF) + \
        b"SSbd" + struct.pack("<I", len(dados))
    caminho.write_bytes(cab + dados + enchimento)
    return caminho


def test_ps_adpcm_ida_e_volta():
    som = tom(1.0)
    cod = aj.codificar_adpcm(som)
    assert len(cod) == -(-len(som) // 28) * 16 and cod[-15] == 1               # o último bloco marca o fim
    dec = aj.decodificar_adpcm(cod)[:len(som)].astype(float)
    erro = som.astype(float) - dec
    assert 10 * np.log10((som.astype(float) ** 2).mean() / (erro ** 2).mean()) > 35   # fiel (dB)
    assert aj.codificar_adpcm(np.zeros(28, np.int16), inicio_vazio=True)[:16] == bytes(16)
    silencio = aj.decodificar_adpcm(aj.codificar_adpcm(np.zeros(56, np.int16)))
    assert not silencio.any()


def test_ler_os_formatos(tmp_path):
    f = aj.ler_formato(wav(tmp_path / "fala.wav", tom(1.5, 32000), 32000, 2))
    assert (f.tipo, f.taxa, f.canais, f.amostras) == ("wav", 32000, 2, 48000)
    f = aj.ler_formato(vag(tmp_path / "fala.vag", tom(1.0, 22050)))
    assert (f.tipo, f.taxa, f.canais) == ("vag", 22050, 1) and f.extra["vazio"] and f.extra["fim07"]
    assert f.amostras == -(-22050 // 28) * 28 and "VAG · 22050 Hz · mono" in f.descrever()
    f = aj.ler_formato(ads(tmp_path / "cena.ads", tom(0.5, 48000)))
    assert (f.tipo, f.taxa, f.canais, f.extra["intercalado"]) == ("ads", 48000, 2, 0x400)
    (tmp_path / "x.adx").write_bytes(b"\x80\x00" + bytes(100))
    with pytest.raises(aj.ErroAudioJogo, match="WAV, VAG e ADS"):
        aj.ler_formato(tmp_path / "x.adx")


@pytest.mark.skipif(not FFMPEG, reason="sem ffmpeg")
def test_encaixar_na_duracao_exata(tmp_path):
    longa = wav(tmp_path / "longa.wav", tom(3.0))                    # 3 s para caber em 2 s: acelera 1,35 e corta
    som, info = aj.encaixar_na_duracao(longa, 2 * 22050, 22050, FFMPEG)
    assert len(som) == 44100 and info["acelerada"] == 1.35 and 0.1 < info["cortada"] < 0.4
    assert abs(int(som[-1])) < 50                                     # o fim suave (sem estalo)
    som, info = aj.encaixar_na_duracao(wav(tmp_path / "um_pouco.wav", tom(2.2)), 2 * 22050, 22050, FFMPEG)
    assert len(som) == 44100 and 1.05 < info["acelerada"] < 1.15 and info["cortada"] < 0.02
    som, info = aj.encaixar_na_duracao(wav(tmp_path / "curta.wav", tom(1.0)), 2 * 22050, 22050, FFMPEG)
    assert len(som) == 44100 and info["acelerada"] == 1.0 and abs(info["completada"] - 1.0) < 0.01
    assert not som[-1000:].any()                                       # completada com silêncio


@pytest.mark.skipif(not FFMPEG, reason="sem ffmpeg")
@pytest.mark.parametrize("tipo", ["wav", "vag", "ads"])
def test_gravar_igual_a_original_do_jogo(tmp_path, tipo):
    """O jogo recebe o mesmo formato, a mesma duração e (VAG/ADS) o mesmo tamanho em bytes."""
    if tipo == "wav":
        original = wav(tmp_path / "orig.wav", tom(2.0, 32000), 32000, 2)
    elif tipo == "vag":
        original = vag(tmp_path / "orig.vag", tom(2.0, 22050))
    else:
        original = ads(tmp_path / "orig.ads", tom(1.2, 48000), enchimento=bytes(300))
    dublada = wav(tmp_path / "dublada.wav", tom(2.6, 24000, 330))      # a voz do XTTS-v2 (24 kHz), mais comprida
    destino = tmp_path / f"novo.{tipo}"
    info = aj.gravar_como(original, dublada, destino, FFMPEG)
    antes, depois = aj.ler_formato(original), aj.ler_formato(destino)
    assert (depois.tipo, depois.taxa, depois.canais, depois.amostras) == (antes.tipo, antes.taxa, antes.canais,
                                                                        antes.amostras)
    assert info["acelerada"] > 1.0 and antes.tipo.upper() in info["formato"]
    if tipo != "wav":
        assert destino.stat().st_size == original.stat().st_size      # cabe no mesmo lugar do disco
    if tipo == "vag":
        assert destino.read_bytes()[32:41] == b"KRATOS_01" and depois.extra["vazio"] and depois.extra["fim07"]
        voz = aj.decodificar_adpcm(destino.read_bytes()[48 + 16:-16])
        assert np.abs(voz.astype(float)).mean() > 1000                 # tem som de verdade (não silêncio)
