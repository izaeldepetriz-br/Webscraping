"""🔎 Meus jogos: achar os jogos que você já tem (ISO de PS2/PS1/PSP, GameCube, ROM, NSP do Switch, Steam), guardar o
que foi lido (da 2ª vez, só o que mudou), o Redump, a tradução na comunidade e o que você já traduziu pelo Maestro.
Arquivos de mentira: nenhum jogo de verdade."""
import struct
import time
from pathlib import Path

from jellyfin_tools import comunidade as cm
from jellyfin_tools import meus_jogos as mj
from jellyfin_tools.instalar_traducao import Instalacao
from tests.test_consoles import sfo
from tests.test_iso_jogo import iso_de_jogo
from tests.test_patch_jogo import iso_de_teste


def biblioteca(pasta: Path) -> Path:
    """Uma pasta de jogos como a de quem usa o Maestro (com subpastas, o pendrive do OPL e lixo)."""
    jogos = pasta / "Jogos"
    (jogos / "PS2").mkdir(parents=True)
    iso_de_teste(jogos / "PS2" / "Burnout 3 - Takedown (USA).iso", boot="SLUS_210.50", volume="BURNOUT3")
    iso_de_teste(jogos / "PS2" / "SLUS_209.46.Aventura no Castelo.iso", semente=2)
    ps1 = iso_de_teste(jogos / "PS1" / "Lendas do Dragao (USA).bin", boot="SLUS_012.34", semente=3) \
        if (jogos / "PS1").mkdir() is None else None
    ps1.write_bytes(ps1.read_bytes().replace(b"BOOT2 = ", b"BOOT  = "))           # (o PS1 usa BOOT, sem o 2)
    (jogos / "PSP").mkdir()
    iso_de_jogo(jogos / "PSP" / "Herois Portateis (USA).iso", {
        "UMD_DATA.BIN": b"ULUS-10041|0001|G|" + b"\0" * 70000,
        "PSP_GAME/PARAM.SFO": sfo({"DISC_ID": "ULUS10041", "TITLE": "Herois Portateis", "DISC_VERSION": "1.01"})})
    (jogos / "PSP" / "Herois Portateis (USA).iso").write_bytes(
        (jogos / "PSP" / "Herois Portateis (USA).iso").read_bytes().replace(b"BOOT2", b"XXXXX"))   # (sem SYSTEM.CNF)
    gc = bytearray(0x20000)
    gc[0:6] = b"GMJE01"
    gc[0x1C:0x20] = struct.pack(">I", 0xC2339F3D)
    gc[0x20:0x31] = b"Ilha do Tesouro"
    (jogos / "GC").mkdir()
    (jogos / "GC" / "Ilha do Tesouro.iso").write_bytes(bytes(gc))
    snes = bytearray(512 * 1024)
    snes[0x7FC0:0x7FD5] = b"MEU JOGO DE AVENTURA "
    snes[0x7FC0 + 0x19] = 1
    struct.pack_into("<HH", snes, 0x7FC0 + 0x1C, 0x1234 ^ 0xFFFF, 0x1234)
    (jogos / "SNES").mkdir()
    (jogos / "SNES" / "Meu Jogo de Aventura (USA).sfc").write_bytes(bytes(snes))
    (jogos / "Switch").mkdir()
    (jogos / "Switch" / "Reino Distante [0100ABCD12340000][v0].nsp").write_bytes(b"PFS0" + b"\0" * 100)
    # o que não é jogo (ou não deve ser aberto): um .bin pequeno, a lixeira, a cópia de segurança do Maestro
    (jogos / "PS2" / "config.bin").write_bytes(b"x" * 100)
    (jogos / "$RECYCLE.BIN").mkdir()
    iso_de_teste(jogos / "$RECYCLE.BIN" / "apagado.iso", semente=9)
    (jogos / ".maestro_original").mkdir()
    (jogos / "Documento.txt").write_text("nada")
    return jogos


def steam(pasta: Path) -> Path:
    apps = pasta / "SteamLibrary" / "steamapps"
    (apps / "common" / "Meu Jogo Indie").mkdir(parents=True)
    (apps / "common" / "Meu Jogo Indie" / "dados.bin").write_bytes(b"\0" * 200000)   # (não é disco: nem é aberto)
    (apps / "appmanifest_123450.acf").write_text('"AppState"\n{\n\t"appid"\t\t"123450"\n\t"name"\t\t"Meu Jogo Indie"\n'
                                                 '\t"installdir"\t\t"Meu Jogo Indie"\n\t"SizeOnDisk"\t\t"200000"\n}\n')
    (apps / "appmanifest_228980.acf").write_text('"AppState"\n{\n"appid" "228980"\n"name" "Steamworks Common '
                                                 'Redistributables"\n"installdir" "Steamworks Shared"\n}\n')
    return apps / "common"


def test_acha_e_separa_por_console(tmp_path):
    jogos = biblioteca(tmp_path)
    comum = steam(tmp_path)
    achados, lidos, ignorados = mj.varrer([jogos, comum])
    por_titulo = {j.titulo: j for j in achados}
    assert sorted(por_titulo) == ["Aventura no Castelo", "Burnout 3 - Takedown", "Herois Portateis",
                                  "Ilha do Tesouro", "Lendas do Dragao", "Meu Jogo Indie", "Meu Jogo de Aventura",
                                  "Reino Distante"], sorted(por_titulo)
    assert lidos == 8 and [Path(i.caminho).name for i in ignorados] == ["config.bin"]   # (a Steam: nada aberto)
    b = por_titulo["Burnout 3 - Takedown"]
    assert (b.console, b.sistema, b.codigo, b.regiao, b.rotulo) == ("PS2", "PS2", "SLUS-21050", "EUA", "PlayStation 2")
    assert (por_titulo["Lendas do Dragao"].console, por_titulo["Lendas do Dragao"].codigo) == ("PS1", "SLUS-01234")
    assert (por_titulo["Herois Portateis"].console, por_titulo["Herois Portateis"].codigo) == ("PSP", "ULUS-10041")
    assert (por_titulo["Ilha do Tesouro"].console, por_titulo["Ilha do Tesouro"].sistema) == ("GCWII", "GC")
    assert (por_titulo["Meu Jogo de Aventura"].console, por_titulo["Meu Jogo de Aventura"].rotulo) == ("NINTENDO",
                                                                                                    "Super NES")
    r = por_titulo["Reino Distante"]
    assert (r.console, r.codigo) == ("SWITCH", "0100ABCD12340000")
    pc = por_titulo["Meu Jogo Indie"]
    assert (pc.console, pc.codigo, pc.caminho) == ("PC", "Steam 123450", str(comum / "Meu Jogo Indie"))
    assert b.texto_copia() == "não conferida" and por_titulo["Meu Jogo de Aventura"].texto_copia().startswith(
        "— cartucho") and pc.texto_copia() == "— (jogo de PC)"
    assert b.texto_traducao() == "— não procurada"
    assert mj.contar(achados) == {"PS2": 2, "PS1": 1, "PSP": 1, "NINTENDO": 1, "GCWII": 1, "SWITCH": 1, "PC": 1}
    # o disco inteiro escolhido: a biblioteca da Steam numa subpasta também entra (sem abrir os arquivos do jogo)
    tudo, _, _ = mj.varrer([tmp_path])
    assert sorted(j.titulo for j in tudo) == sorted(por_titulo) and len(tudo) == 8
    pastas = mj.por_pasta(achados, [jogos, comum])
    assert pastas[str(jogos)][0] == 7 and pastas[str(jogos)][1].startswith("PS2 (2), ")
    assert pastas[str(comum)] == (1, "PC (1)")


def test_guarda_e_so_le_o_que_mudou(tmp_path):
    jogos = biblioteca(tmp_path)
    arquivo = tmp_path / "meus_jogos.json"
    achados, _, ignorados = mj.varrer([jogos])
    achados[0].traducao = {"quando": time.time(), "achados": [], "aviso": ""}
    mj.salvar(arquivo, achados + ignorados)
    abertos = []

    def contar_aberturas(caminho):
        abertos.append(caminho.name)
        return mj.identificar(caminho)
    novos, lidos, _ = mj.varrer([jogos], mj.carregar(arquivo), identificar_=contar_aberturas)
    assert lidos == 0 and abertos == [] and len(novos) == 7                     # nada mudou: nada aberto
    assert novos[0].traducao["achados"] == [] and not novos[0].procurando       # (a busca guardada vem junto)
    iso = jogos / "PS2" / "Burnout 3 - Takedown (USA).iso"
    iso.write_bytes(iso.read_bytes() + b"\0" * 2048)                           # mudou: abre de novo
    iso_de_teste(jogos / "PS2" / "Jogo Novo (USA).iso", semente=5)
    novos, lidos, _ = mj.varrer([jogos], mj.carregar(arquivo), identificar_=contar_aberturas)
    assert sorted(abertos) == ["Burnout 3 - Takedown (USA).iso", "Jogo Novo (USA).iso"] and lidos == 2


def test_redump_traducao_e_o_que_voce_ja_traduziu(tmp_path):
    jogos = biblioteca(tmp_path)
    achados, _, _ = mj.varrer([jogos])
    por_titulo = {j.titulo: j for j in achados}
    burnout, aventura = por_titulo["Burnout 3 - Takedown"], por_titulo["Aventura no Castelo"]
    # o Redump: a impressão digital uma vez só, e o nome no banco
    pedidos = []

    def indice(sistema, pasta):
        pedidos.append(sistema)
        return {"md5": {}, "crc": {}}
    indices = {}
    mj.conferir_redump(burnout, indices, tmp_path, indice_=indice,
                       procurar_=lambda i, md5, crc, t: "Burnout 3 - Takedown (USA, Canada)")
    mj.conferir_redump(aventura, indices, tmp_path, indice_=indice, procurar_=lambda i, md5, crc, t: None)
    mj.conferir_redump(por_titulo["Meu Jogo de Aventura"], indices, tmp_path, indice_=indice)   # cartucho: nada
    assert pedidos == ["PS2"] and burnout.md5 and burnout.texto_copia() == "✓ perfeita (Redump)"
    assert aventura.texto_copia() == "⚠ não está no Redump"
    # a tradução na comunidade (só patches): o nome do Redump vai na busca
    buscas = []

    def procurar(termos, info, pasta, onde, quer, crc32="", sistema=""):
        buscas.append((termos, sistema, info.id_jogo if info else None, crc32))
        r = cm.Resultado()
        if "Aventura" in termos:
            r.achados = [cm.Achado("PO.B.R.E", "Aventura no Castelo (Grupo Exemplo)", traz=["textos", "dublagem"],
                                   encaixa="✓ encaixa: o mesmo código do disco")]
        return r
    for jogo in (burnout, aventura, por_titulo["Reino Distante"]):
        jogo.procurando = True
        assert jogo.texto_traducao() == "… procurando" and mj.precisa_procurar(jogo)
        mj.procurar_traducao(jogo, tmp_path, procurar_=procurar)
    assert buscas[0] == ("Burnout 3 - Takedown", "PS2", "SLUS-21050", burnout.crc32)
    assert buscas[2][:3] == ("Reino Distante", "Switch", None)
    assert burnout.texto_traducao() == "✗ não tem → 🗣 traduzir e dublar" and not mj.precisa_procurar(burnout)
    assert aventura.texto_traducao() == "✓ 1 patch · textos e dublagem" and aventura.tem_traducao()
    # o que você já traduziu pelo Maestro: a cópia aplicada, o original dela e a tradução instalada
    copia = jogos / "PS2" / "SLUS_209.46.Aventura no Castelo PT-BR.iso"
    copia.write_bytes((jogos / "PS2" / "SLUS_209.46.Aventura no Castelo.iso").read_bytes())
    achados, _, _ = mj.varrer([jogos])
    aplicados = [{"iso": aventura.caminho, "destino": str(copia), "patch": "x.ppf", "conferido": ""}]
    instaladas = [Instalacao("SWITCH", "mod", str(tmp_path / "mods" / "0100ABCD12340000" / "PT-BR"))]
    mj.marcar_traduzidos(achados, aplicados, instaladas)
    por_caminho = {Path(j.caminho).name: j for j in achados}
    assert por_caminho["SLUS_209.46.Aventura no Castelo PT-BR.iso"].texto_traducao().startswith("✓ já traduzida")
    assert por_caminho["SLUS_209.46.Aventura no Castelo PT-BR.iso"].texto_copia() == "· modificada (já traduzida)"
    assert por_caminho["SLUS_209.46.Aventura no Castelo.iso"].texto_traducao() == "✓ você já tem a cópia traduzida"
    assert por_caminho["Reino Distante [0100ABCD12340000][v0].nsp"].texto_traducao().startswith("✓ instalada")
    assert not mj.precisa_procurar(por_caminho["Reino Distante [0100ABCD12340000][v0].nsp"])
    assert mj.resumo(achados).startswith("3 com tradução (3 já traduzidos por você)")
