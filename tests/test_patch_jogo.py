"""Patch de fãs na ISO do disco (aba 🎮 Jogos): ler o código do jogo, a impressão digital, o leia-me, aplicar .ppf
(1.0, 2.0 e 3.0) e .xdelta (o xdelta3 de verdade, quando instalado) numa cópia, e criar o patch da sua tradução."""
import hashlib
import io
import shutil
import struct
import zipfile
import zlib
from pathlib import Path

import pytest

from jellyfin_tools import patch_jogo as pj

XDELTA = shutil.which("xdelta3")


def _registro(nome: bytes, lba: int, tamanho: int, pasta: bool = False) -> bytes:
    corpo = struct.pack("<BB", 0, 0) + struct.pack("<I", lba) + struct.pack(">I", lba) + \
        struct.pack("<I", tamanho) + struct.pack(">I", tamanho) + bytes(7) + bytes([2 if pasta else 0, 0, 0]) + \
        struct.pack("<H", 1) + struct.pack(">H", 1) + bytes([len(nome)]) + nome
    if len(nome) % 2 == 0:
        corpo += b"\x00"
    return bytes([len(corpo)]) + corpo[1:]


def iso_de_teste(caminho: Path, boot: str = "SLUS_209.46", volume: str = "MEU_JOGO", semente: int = 1,
                 setores_de_dados: int = 40, bin_2352: bool = False) -> Path:
    """Uma ISO 9660 pequena de "PS2": o SYSTEM.CNF (BOOT2) e um DADOS.BIN com bytes do jogo."""
    cnf = f"BOOT2 = cdrom0:\\{boot};1\r\nVER = 1.00\r\nVMODE = NTSC\r\n".encode()
    dados = bytes((i * 7 + semente * 13) % 251 for i in range(setores_de_dados * 2048))
    total = 20 + setores_de_dados
    pvd = bytearray(2048)
    pvd[0:7] = b"\x01CD001\x01"
    pvd[40:72] = volume.encode().ljust(32)
    pvd[80:88] = struct.pack("<I", total) + struct.pack(">I", total)
    raiz = _registro(b"\x00", 18, 2048, True) + _registro(b"\x01", 18, 2048, True) + \
        _registro(b"SYSTEM.CNF;1", 19, len(cnf)) + _registro(b"DADOS.BIN;1", 20, len(dados))
    pvd[156:156 + 34] = _registro(b"\x00", 18, 2048, True)
    fim = bytearray(2048)
    fim[0:7] = b"\xffCD001\x01"
    setores = [bytes(2048)] * 16 + [bytes(pvd), bytes(fim), raiz.ljust(2048, b"\x00"), cnf.ljust(2048, b"\x00")]
    setores += [dados[i:i + 2048] for i in range(0, len(dados), 2048)]
    with open(caminho, "wb") as f:
        for s in setores:
            f.write((bytes(24) + s + bytes(280)) if bin_2352 else s)
    return caminho


def test_ler_o_codigo_do_jogo(tmp_path):
    info = pj.ler_info(iso_de_teste(tmp_path / "Meu Jogo.iso"))
    assert (info.id_jogo, info.arquivo_boot, info.sistema, info.volume, info.versao, info.regiao) == (
        "SLUS-20946", "SLUS_209.46", "PS2", "MEU_JOGO", "1.00", "EUA")
    assert "SLUS-20946 · EUA · PS2" in info.descrever()
    assert pj.ler_info(iso_de_teste(tmp_path / "e.iso", "SLES_512.34")).regiao == "Europa"
    assert pj.ler_info(iso_de_teste(tmp_path / "j.bin", "SLPM_650.01", bin_2352=True)).id_jogo == "SLPM-65001"
    (tmp_path / "nada.iso").write_bytes(bytes(100_000))
    with pytest.raises(pj.ErroPatch, match="não parece uma imagem de disco"):
        pj.ler_info(tmp_path / "nada.iso")
    assert pj.normalizar_id("slus_209.46") == pj.normalizar_id("SLUS20946") == "SLUS-20946"


def test_impressao_digital_e_o_leia_me(tmp_path):
    iso = iso_de_teste(tmp_path / "jogo.iso")
    conteudo = iso.read_bytes()
    andamento = []
    d = pj.impressao_digital(iso, andamento.append)
    assert d.crc32 == f"{zlib.crc32(conteudo):08X}" and d.md5 == hashlib.md5(conteudo).hexdigest().upper()
    assert d.sha1 == hashlib.sha1(conteudo).hexdigest().upper() and andamento[-1] == 1.0
    pasta = tmp_path / "patch"
    pasta.mkdir()
    patch = pasta / "Meu Jogo PT-BR.ppf"
    patch.write_bytes(b"PPF10\x00" + b"x" * 50)
    (pasta / "LEIA-ME.txt").write_text(
        f"Meu Jogo PT-BR v1.2 (SLUS_209.46)\nISO original:\n  CRC32: {d.crc32.lower()}\n  MD5: {d.md5.lower()}\n"
        "ISO traduzida:\n  CRC32 (traduzida): 0BADF00D\nSHA-256 (não conta): " + "ab" * 32 + "\n", encoding="utf-8")
    esperado = pj.esperado_do_leia_me(patch)
    assert d.crc32 in esperado.crc32 and "0BADF00D" in esperado.crc32 and esperado.md5 == {d.md5}
    assert esperado.ids == {"SLUS-20946"} and esperado.arquivos == ["LEIA-ME.txt"] and not esperado.sha1
    assert esperado.confere(d) and not esperado.confere(pj.Digital("12345678", "0" * 32, "0" * 40))


def ppf(versao: int, trocas: list[tuple[int, bytes]], iso: Path | None = None, bloco: bool = True,
        desfazer: bool = False, diz: str = "") -> bytes:
    """Um .ppf de teste (1.0, 2.0 ou 3.0); o bloco de conferência vem da ISO certa."""
    cab = f"PPF{versao}0".encode() + bytes([versao - 1]) + b"Meu Jogo PT-BR".ljust(50)
    original = iso.read_bytes() if iso else b""
    if versao == 2:
        cab += struct.pack("<I", len(original)) + original[0x9320:0x9320 + 1024]
    elif versao == 3:
        cab += bytes([0, 1 if bloco else 0, 1 if desfazer else 0, 0])
        if bloco:
            cab += original[0x9320:0x9320 + 1024]
    corpo = b""
    for onde, dados in trocas:
        corpo += (struct.pack("<Q", onde) if versao == 3 else struct.pack("<I", onde)) + bytes([len(dados)]) + dados
        if desfazer:
            corpo += original[onde:onde + len(dados)]
    rabo = b""
    if diz:
        texto = diz.encode("latin-1")
        rabo = b"@BEGIN_FILE_ID.DIZ" + texto + b"@END_FILE_ID.DIZ" + \
            (struct.pack("<H", len(texto)) if versao == 3 else struct.pack("<I", len(texto)))
    return cab + corpo + rabo


@pytest.mark.parametrize("versao", [1, 2, 3])
def test_aplicar_ppf_numa_copia(tmp_path, versao):
    iso = iso_de_teste(tmp_path / "jogo.iso")
    original = iso.read_bytes()
    trocas = [(41000 + 10, b"OLA MUNDO"), (60000, bytes(range(200))), (len(original) - 4, b"FIM!")]
    patch = tmp_path / "trad.ppf"
    patch.write_bytes(ppf(versao, trocas, iso, desfazer=versao == 3, diz="Traducao PT-BR\nCRC32: 0BADF00D"))
    info = pj.ler_ppf(patch)
    assert info.versao == versao and info.descricao == "Meu Jogo PT-BR"
    if versao > 1:
        assert info.diz.startswith("Traducao PT-BR") and "0BADF00D" in pj.esperado_do_leia_me(patch).crc32
    andamento = []
    r = pj.aplicar(iso, patch, tmp_path / "saida" / "Meu Jogo PT-BR.iso", tmp_path / "ferramentas",
                   ao_progresso=andamento.append)
    nova = r.destino.read_bytes()
    assert iso.read_bytes() == original                                  # a ISO original não muda
    assert nova[41010:41019] == b"OLA MUNDO" and nova[60000:60200] == bytes(range(200)) and nova[-4:] == b"FIM!"
    assert len(nova) == len(original) and r.info.id_jogo == "SLUS-20946" and r.tipo == pj.PPF
    assert andamento[-1] == 1.0 and not list((tmp_path / "saida").glob("*.parcial"))
    assert r.conferido == ("sem como conferir" if versao == 1 else "o próprio patch conferiu")


def test_ppf_de_outra_versao_nao_aplica(tmp_path):
    certa = iso_de_teste(tmp_path / "eua.iso")
    outra = iso_de_teste(tmp_path / "europa.iso", "SLES_512.34", semente=9)
    with open(outra, "r+b") as f:                     # outra versão: o pedaço que o .ppf confere (0x9320) muda
        f.seek(0x9320 + 100)
        f.write(b"OUTRA EDICAO")
    for versao in (2, 3):
        patch = tmp_path / f"v{versao}.ppf"
        patch.write_bytes(ppf(versao, [(41000, b"X")], certa))
        with pytest.raises(pj.ErroPatch, match="outra versão do jogo"):
            pj.aplicar(outra, patch, tmp_path / "nova.iso", tmp_path)
        assert not (tmp_path / "nova.iso").exists() and not (tmp_path / "nova.iso.parcial").exists()
    longe = tmp_path / "longe.ppf"
    longe.write_bytes(ppf(1, [(10 ** 9, b"X")]))
    with pytest.raises(pj.ErroPatch, match="depois do fim da sua ISO"):
        pj.aplicar(certa, longe, tmp_path / "nova.iso", tmp_path)


def test_confere_o_leia_me_antes_de_aplicar(tmp_path):
    iso = iso_de_teste(tmp_path / "jogo.iso")
    patch = tmp_path / "trad.ppf"
    patch.write_bytes(ppf(1, [(41000, b"X")]))
    esperado = pj.esperado_no_texto("CRC32: 0BADF00D\nMD5: " + "1" * 32)
    digital = pj.impressao_digital(iso)
    with pytest.raises(pj.ErroPatch, match=r"não é a versão do patch: o leia-me pede CRC32 0BADF00D.*sua é CRC32"):
        pj.aplicar(iso, patch, tmp_path / "nova.iso", tmp_path, digital=digital, esperado=esperado)
    esperado.crc32.add(digital.crc32)                                # agora bate (a original está no leia-me)
    r = pj.aplicar(iso, patch, tmp_path / "nova.iso", tmp_path, digital=digital, esperado=esperado)
    assert r.conferido == "bateu com o leia-me"
    with pytest.raises(pj.ErroPatch, match="outro nome"):
        pj.aplicar(iso, patch, iso, tmp_path)


def test_o_que_nao_e_patch(tmp_path):
    (tmp_path / "jogo.iso").write_bytes(b"\x00" * 1000)
    with pytest.raises(pj.ErroPatch, match="jogo inteiro"):
        pj.tipo_do_patch(tmp_path / "jogo.iso")
    (tmp_path / "trad.rar").write_bytes(b"Rar!\x1a\x07")
    with pytest.raises(pj.ErroPatch, match="extraia antes"):
        pj.tipo_do_patch(tmp_path / "trad.rar")
    (tmp_path / "trad.xdelta").write_bytes(pj.MAGICA_VCDIFF + b"\x00" * 10)
    assert pj.tipo_do_patch(tmp_path / "trad.xdelta") == pj.XDELTA


@pytest.mark.skipif(not XDELTA, reason="sem o xdelta3 (apt install xdelta3)")
def test_criar_e_aplicar_xdelta_de_verdade(tmp_path):
    """O caminho de ida e volta: criar o .xdelta da tradução e aplicar na ISO do disco (o xdelta3 de verdade)."""
    original = iso_de_teste(tmp_path / "jogo.iso")
    modificada = tmp_path / "jogo PT-BR.iso"
    conteudo = bytearray(original.read_bytes())
    conteudo[41000:41009] = b"OLA MUNDO"
    conteudo[70000:70100] = bytes(100)
    modificada.write_bytes(bytes(conteudo))
    andamento = []
    patch = pj.criar_patch(original, modificada, tmp_path / "patch" / "Meu Jogo PT-BR.xdelta", tmp_path,
                           "Meu Jogo PT-BR v1.0", ao_progresso=andamento.append)
    assert pj.tipo_do_patch(patch) == pj.XDELTA and patch.stat().st_size < 4096 and andamento[-1] == 1.0
    leia_me = patch.with_name("Meu Jogo PT-BR - leia-me.txt").read_text(encoding="utf-8")
    assert "SLUS-20946" in leia_me and "não contém o jogo" in leia_me
    esperado = pj.esperado_do_leia_me(patch)                         # quem recebe confere pelo leia-me
    digital = pj.impressao_digital(original)
    assert esperado.confere(digital) and esperado.ids == {"SLUS-20946"}
    r = pj.aplicar(original, patch, tmp_path / "nova.iso", tmp_path, digital=digital, esperado=esperado)
    assert r.destino.read_bytes() == bytes(conteudo) and r.conferido == "bateu com o leia-me"
    outra = iso_de_teste(tmp_path / "europa.iso", "SLES_512.34", semente=9)   # outra versão: o xdelta3 recusa
    with pytest.raises(pj.ErroPatch, match="outra versão do jogo"):
        pj.aplicar(outra, patch, tmp_path / "nova2.iso", tmp_path)
    assert not (tmp_path / "nova2.iso").exists() and not (tmp_path / "nova2.iso.parcial").exists()


def test_baixar_o_xdelta3_no_windows_confere_a_impressao(tmp_path, monkeypatch):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xdelta3-3.1.0-x86_64.exe", b"MZ programa")
    pacote = buf.getvalue()
    baixados = []

    def baixar(url, destino, progresso):
        baixados.append(url)
        Path(destino).write_bytes(pacote)
    with pytest.raises(pj.ErroPatch, match="não é o oficial"):
        pj.programa_xdelta(tmp_path, "win32", baixar)
    monkeypatch.setattr(pj, "SHA256_XDELTA", hashlib.sha256(pacote).hexdigest())
    exe = pj.programa_xdelta(tmp_path, "win32", baixar)
    assert exe == tmp_path / "xdelta3" / "xdelta3.exe" and exe.read_bytes() == b"MZ programa"
    assert pj.programa_xdelta(tmp_path, "win32", baixar) == exe and baixados == [pj.URL_XDELTA] * 2
    assert not list((tmp_path / "xdelta3").glob("*.zip"))


def test_nome_do_opl_e_busca_na_comunidade(tmp_path):
    info = pj.ler_info(iso_de_teste(tmp_path / "jogo.iso"))
    assert pj.nome_para_o_opl(info, "Meu Jogo: Edição PT-BR") == "SLUS_209.46.Meu Jogo  Edição PT-BR.iso"
    assert len(pj.nome_para_o_opl(info, "x" * 80)) == len("SLUS_209.46.") + 32 + len(".iso")
    url = pj.busca_na_comunidade(info, "Meu Jogo")
    assert url.startswith("https://www.google.com/search?q=") and "SLUS-20946" in url and "romhackers.org" in url
    assert pj.tamanho_legivel(4_700_000_000) == "4,38 GB"


def _numero(n: int) -> bytes:
    """O número do BPS (o contrário de patch_jogo._numero_bps)."""
    saida = bytearray()
    while True:
        x = n & 0x7F
        n >>= 7
        if n == 0:
            saida.append(0x80 | x)
            return bytes(saida)
        saida.append(x)
        n -= 1


def bps(original: bytes, nova: bytes, acoes: list) -> bytes:
    """Um .bps de verdade: acoes = [(0, n) mesmo pedaço | (1, bytes) novos | (2, desloc, n) da original |
    (3, desloc, n) do que já saiu]."""
    corpo = b"BPS1" + _numero(len(original)) + _numero(len(nova)) + _numero(0)
    for acao in acoes:
        if acao[0] == 0:
            corpo += _numero(((acao[1] - 1) << 2) | 0)
        elif acao[0] == 1:
            corpo += _numero(((len(acao[1]) - 1) << 2) | 1) + acao[1]
        else:
            tipo, desloc, n = acao
            corpo += _numero(((n - 1) << 2) | tipo) + _numero((abs(desloc) << 1) | (1 if desloc < 0 else 0))
    corpo += struct.pack("<II", zlib.crc32(original), zlib.crc32(nova))
    return corpo + struct.pack("<I", zlib.crc32(corpo))


def test_ips_e_bps(tmp_path):
    iso = iso_de_teste(tmp_path / "Meu Jogo.iso")
    original = iso.read_bytes()
    # IPS: uma troca normal e uma sequência do mesmo byte (RLE)
    ips = b"PATCH" + (41000).to_bytes(3, "big") + (9).to_bytes(2, "big") + b"OLA MUNDO" + \
        (42000).to_bytes(3, "big") + (0).to_bytes(2, "big") + (300).to_bytes(2, "big") + b"\x2a" + b"EOF"
    (tmp_path / "p").mkdir()
    patch = tmp_path / "p" / "Meu Jogo PT-BR.ips"
    patch.write_bytes(ips)
    assert pj.tipo_do_patch(patch) == pj.IPS
    r = pj.aplicar(iso, patch, tmp_path / "ips.iso", tmp_path / "ferramentas")
    nova = r.destino.read_bytes()
    assert nova[41000:41009] == b"OLA MUNDO" and nova[42000:42300] == b"\x2a" * 300 and len(nova) == len(original)
    assert r.conferido == "sem como conferir" and iso.read_bytes() == original
    # BPS: todas as ações (igual, novo, da original em outro lugar, repetindo o que já saiu)
    alvo = bytearray(original)
    alvo[41000:41009] = b"OLA MUNDO"
    alvo[41009:41012] = original[100:103]
    alvo[41012:41018] = b"ABABAB"
    acoes = [(0, 41000), (1, b"OLA MUNDO"), (2, 100, 3), (1, b"AB"), (3, 41012, 4),
             (0, len(original) - 41018)]
    patch_bps = tmp_path / "p" / "Meu Jogo PT-BR.bps"
    patch_bps.write_bytes(bps(original, bytes(alvo), acoes))
    assert pj.tipo_do_patch(patch_bps) == pj.BPS and pj.info_bps(patch_bps)["destino"] == len(alvo)
    r = pj.aplicar(iso, patch_bps, tmp_path / "bps.iso", tmp_path / "ferramentas")
    assert r.destino.read_bytes() == bytes(alvo) and r.conferido == "o próprio patch conferiu"
    outra = iso_de_teste(tmp_path / "Outra.iso", semente=7)                  # outra versão: não aplica
    with pytest.raises(pj.ErroPatch, match="não é a versão do patch"):
        pj.aplicar(outra, patch_bps, tmp_path / "bps2.iso", tmp_path / "ferramentas")
    assert not (tmp_path / "bps2.iso").exists()


def test_leia_me_o_que_traz_e_creditos(tmp_path):
    pasta = tmp_path / "patch"
    pasta.mkdir()
    patch = pasta / "Meu Jogo PT-BR v1.2.xdelta"
    patch.write_bytes(pj.MAGICA_VCDIFF + bytes(20))
    (pasta / "LEIA-ME.txt").write_text("Meu Jogo - Tradução PT-BR\nTradução por: Grupo Exemplo\nVersão 1.2\n"
                                       "Traduzimos os textos e os menus, com acentuação completa, e a dublagem "
                                       "das cenas.\nCRC32: 1A2B3C4D\n", encoding="utf-8")
    info = pj.leia_me(patch)
    assert info.arquivo.name == "LEIA-ME.txt"
    assert info.o_que_traz == ["textos", "menus", "vozes dubladas", "letras com ç e acentos"]
    assert info.creditos == "Grupo Exemplo · versão 1.2"


def test_pcsx2_e_patches_aplicados(tmp_path, monkeypatch):
    exe = tmp_path / "PCSX2" / "pcsx2-qt.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"")
    assert pj.achar_pcsx2(str(exe)) == exe
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    monkeypatch.setattr(pj.shutil, "which", lambda nome: None)
    assert pj.achar_pcsx2("", sistema="win32") == exe and pj.achar_pcsx2("", sistema="linux") is None
    abertos = []
    pj.abrir_no_pcsx2(tmp_path / "jogo.iso", exe, abrir=abertos.append)
    assert abertos == [[str(exe), str(tmp_path / "jogo.iso")]]
    arquivo = tmp_path / "aplicados.json"
    pj.registrar_aplicado(arquivo, Path("a.iso"), Path("p.xdelta"), Path("A PT.iso"), "bateu com o leia-me")
    lista = pj.registrar_aplicado(arquivo, Path("b.iso"), Path("q.ppf"), Path("B PT.iso"), "sem como conferir")
    pj.registrar_aplicado(arquivo, Path("a.iso"), Path("p2.xdelta"), Path("A PT.iso"), "o próprio patch conferiu")
    lista = pj.carregar_aplicados(arquivo)
    assert [d["destino"] for d in lista] == ["A PT.iso", "B PT.iso"] and lista[0]["patch"] == "p2.xdelta"
