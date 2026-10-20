"""Os consoles da aba 🎮 Jogos: o código e o título lidos de dentro de cada tipo de jogo (a ISO do PSP, o disco de
GameCube/Wii, as ROMs da Nintendo), o nome da cópia traduzida e o emulador de cada um. Arquivos de mentira."""
import struct
from pathlib import Path

import pytest

from jellyfin_tools import consoles as cs
from jellyfin_tools import patch_jogo as pj
from tests.test_iso_jogo import iso_de_jogo


def sfo(campos: dict) -> bytes:
    """Um PARAM.SFO (o arquivo de informações do PSP)."""
    chaves, valores, entradas = b"", b"", b""
    for nome, valor in campos.items():
        bruto = valor.encode() + b"\0"
        entradas += struct.pack("<HHIII", len(chaves), 0x0204, len(bruto), len(bruto), len(valores))
        chaves += nome.encode() + b"\0"
        valores += bruto
    inicio_chaves = 20 + len(entradas)
    return b"\0PSF" + struct.pack("<IIII", 0x101, inicio_chaves, inicio_chaves + len(chaves), len(campos)) + \
        entradas + chaves + valores


def test_cada_console_le_o_proprio_jogo(tmp_path):
    # PSP: o código e o título do PARAM.SFO (dentro da pasta PSP_GAME)
    umd = iso_de_jogo(tmp_path / "Meu Jogo PSP.iso", {
        "UMD_DATA.BIN": b"ULUS-10041|0001|G|",
        "PSP_GAME/PARAM.SFO": sfo({"DISC_ID": "ULUS10041", "TITLE": "Meu Jogo Portatil", "DISC_VERSION": "1.01"})})
    info = cs.identificar(umd, "PSP")
    assert (info.id_jogo, info.volume, info.regiao, info.versao, info.sistema) == (
        "ULUS-10041", "Meu Jogo Portatil", "EUA", "1.01", "PSP")
    # GameCube: o código, o título e a região do cabeçalho do disco
    gc = bytearray(0x2000)
    gc[0:6], gc[7] = b"GMJE01", 1
    gc[0x1C:0x20] = struct.pack(">I", 0xC2339F3D)
    gc[0x20:0x31] = b"Meu Jogo de Disco"
    (tmp_path / "jogo.iso").write_bytes(bytes(gc))
    info = cs.identificar(tmp_path / "jogo.iso", "GCWII")
    assert (info.sistema, info.id_jogo, info.volume, info.regiao, info.versao) == ("GC", "GMJE01", "Meu Jogo de Disco",
                                                                                   "EUA", "1")
    # Wii em WBFS (o disco começa no setor 0x200)
    wbfs = bytearray(0x1000)
    wbfs[:4] = b"WBFS"
    wbfs[0x200:0x206] = b"RMJP01"
    wbfs[0x218:0x21C] = struct.pack(">I", 0x5D1C9EA3)
    (tmp_path / "jogo.wbfs").write_bytes(bytes(wbfs))
    assert (cs.identificar(tmp_path / "jogo.wbfs", "GCWII").sistema, cs.identificar(
        tmp_path / "jogo.wbfs", "GCWII").regiao) == ("Wii", "Europa")
    with pytest.raises(pj.ErroPatch, match="GameCube ou Wii"):
        cs.identificar(umd, "GCWII")
    # SNES (LoROM, com a soma de conferência), GBA, Nintendo 64 em .v64 (bytes trocados) e DS
    snes = bytearray(512 * 1024)
    snes[0x7FC0:0x7FD5] = b"MEU JOGO DE AVENTURA "
    snes[0x7FC0 + 0x19] = 1
    struct.pack_into("<HH", snes, 0x7FC0 + 0x1C, 0x1234 ^ 0xFFFF, 0x1234)
    (tmp_path / "jogo.sfc").write_bytes(bytes(snes))
    info = cs.identificar(tmp_path / "jogo.sfc", "NINTENDO")
    assert (info.sistema, info.volume, info.regiao) == ("SNES", "MEU JOGO DE AVENTURA", "EUA")
    gba = bytearray(0x200)
    gba[0xA0:0xAC], gba[0xAC:0xB0] = b"MEUJOGO\0\0\0\0\0", b"BMJP"
    (tmp_path / "jogo.gba").write_bytes(bytes(gba))
    info = cs.identificar(tmp_path / "jogo.gba", "NINTENDO")
    assert (info.sistema, info.volume, info.id_jogo, info.regiao) == ("GBA", "MEUJOGO", "AGB-BMJP", "Europa")
    z64 = bytearray(0x1000)
    z64[:4] = b"\x80\x37\x12\x40"
    z64[0x20:0x34] = b"MEU JOGO 64".ljust(20)
    z64[0x3B:0x3F] = b"NMJE"
    v64 = bytearray(z64)
    v64[0::2], v64[1::2] = z64[1::2], z64[0::2]
    (tmp_path / "jogo.v64").write_bytes(bytes(v64))
    info = cs.identificar(tmp_path / "jogo.v64", "NINTENDO")
    assert (info.sistema, info.volume, info.id_jogo, info.regiao) == ("N64", "MEU JOGO 64", "NUS-NMJE", "EUA")
    nds = bytearray(0x200)
    nds[0:12], nds[0x0C:0x10] = b"MEUJOGODS\0\0\0", b"AMJJ"
    (tmp_path / "jogo.nds").write_bytes(bytes(nds))
    assert cs.descrever(cs.identificar(tmp_path / "jogo.nds", "NINTENDO")).startswith("NTR-AMJJ · MEUJOGODS · "
                                                                                       "Nintendo DS · Japão")
    with pytest.raises(pj.ErroPatch, match="não conheço essa ROM"):
        cs.identificar(umd, "NINTENDO")


def test_nome_da_copia_e_o_emulador(tmp_path, monkeypatch):
    rom = pj.InfoISO(Path("D:/Jogos/Meu Jogo (USA).sfc"), 1)
    assert cs.nome_final("NINTENDO", rom, "Meu Jogo PT-BR") == "Meu Jogo PT-BR.sfc"
    ps2 = pj.InfoISO(Path("x.iso"), 1, "SLUS-20946", "SLUS_209.46")
    assert cs.nome_final("PS2", ps2, "Meu Jogo PT-BR", opl=True) == "SLUS_209.46.Meu Jogo PT-BR.iso"
    assert cs.nome_final("PS1", ps2, "Meu Jogo PT-BR.iso") == "Meu Jogo PT-BR.iso"
    assert [c.nome for c in cs.CONSOLES.values()] == ["PlayStation 2", "PlayStation 1", "PSP", "Nintendo clássicos",
                                                      "GameCube / Wii", "Nintendo Switch", "PC"]
    assert cs.console("PS2").opl and not cs.console("PS1").opl and cs.INSTALAR in cs.console("SWITCH").modos
    assert cs.DUBLAR in cs.console("PS1").modos and cs.DUBLAR not in cs.console("PSP").modos
    # o emulador: no PATH (fora do Windows, o nome sem .exe) ou o escolhido antes
    pasta = tmp_path / "bin"
    pasta.mkdir()
    (pasta / "duckstation-qt").write_text("#!/bin/sh\n")
    (pasta / "duckstation-qt").chmod(0o755)
    monkeypatch.setenv("PATH", str(pasta))
    assert cs.achar_emulador("PS1", sistema="linux") == pasta / "duckstation-qt"
    assert cs.achar_emulador("PSP", sistema="linux") is None
    escolhido = tmp_path / "PPSSPPWindows64.exe"
    escolhido.write_text("")
    assert cs.achar_emulador("PSP", str(escolhido), sistema="linux") == escolhido
