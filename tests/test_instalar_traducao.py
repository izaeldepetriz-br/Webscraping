"""Instalar a tradução no Switch (o mod) e no PC (os arquivos por cima da pasta do jogo), desfazer, e criar a sua
(o mod .zip e o pacote .zip). Arquivos de mentira: nenhum jogo de verdade."""
import zipfile

import pytest

from jellyfin_tools import instalar_traducao as it
from jellyfin_tools.patch_jogo import ErroPatch

TID = "0100ABCD12340000"


def mod_zip(tmp_path):
    caminho = tmp_path / "Meu Jogo PT-BR v1.1.zip"
    with zipfile.ZipFile(caminho, "w") as z:
        z.writestr(f"Meu Jogo PT-BR/atmosphere/contents/{TID}/romfs/Message/Main.msbt", b"OLA")
        z.writestr(f"Meu Jogo PT-BR/atmosphere/contents/{TID}/romfs/Font/fonte.bfttf", b"F" * 10)
        z.writestr(f"Meu Jogo PT-BR/atmosphere/contents/{TID}/exefs/main.npdm", b"E")
        z.writestr("Meu Jogo PT-BR/LEIA-ME.txt", "Para a versão 1.2.0 do jogo. Créditos: Grupo Exemplo")
    return caminho


def test_mod_do_switch_no_emulador_e_no_sd(tmp_path):
    pacote = it.ler_mod(mod_zip(tmp_path))
    assert (pacote.title_id, pacote.partes, len(pacote.arquivos)) == (TID, ["exefs", "romfs"], 3)
    assert "versão 1.2.0" in pacote.leia_me and pacote.nome == "Meu Jogo PT-BR v1.1"
    mods = tmp_path / "Ryujinx" / "mods" / "contents"
    mods.mkdir(parents=True)                                    # a pasta de mods do emulador já existe
    destino = it.destino_do_mod(pacote, it.EMULADOR, mods)
    assert destino == mods / TID / "Meu Jogo PT-BR v1.1"
    feito = it.instalar(pacote, destino, "SWITCH")
    assert (destino / "romfs" / "Message" / "Main.msbt").read_bytes() == b"OLA" and len(feito.criados) == 3
    assert it.destino_do_mod(pacote, it.SD, tmp_path / "SD") == tmp_path / "SD" / "atmosphere" / "contents" / TID
    it.desfazer(feito)
    assert not (mods / TID).exists() and mods.is_dir()          # só o que o Maestro copiou saiu
    with pytest.raises(ErroPatch, match="TitleID"):
        it.destino_do_mod(it.Pacote(tmp_path / "x.zip"), it.EMULADOR, mods)
    sem_romfs = tmp_path / "sem.zip"
    with zipfile.ZipFile(sem_romfs, "w") as z:
        z.writestr("leia.txt", "nada")
    with pytest.raises(ErroPatch, match="romfs"):
        it.ler_mod(sem_romfs)


def test_traducao_do_pc_com_copia_de_seguranca_e_desfazer(tmp_path):
    jogo = tmp_path / "Meu Jogo"
    (jogo / "data").mkdir(parents=True)
    (jogo / "data" / "textos.json").write_text('{"oi": "hello"}')
    (jogo / "jogo.exe").write_bytes(b"EXE")
    traducao = tmp_path / "Traducao PT-BR"
    (traducao / "Meu Jogo PT-BR" / "data").mkdir(parents=True)
    (traducao / "Meu Jogo PT-BR" / "data" / "textos.json").write_text('{"oi": "olá"}')
    (traducao / "Meu Jogo PT-BR" / "data" / "fonte_pt.ttf").write_bytes(b"F")
    (traducao / "Meu Jogo PT-BR" / "LEIA-ME.txt").write_text("Tradução PT-BR v1.0")
    pacote = it.ler_pacote_pc(traducao, jogo)
    assert pacote.raiz == "Meu Jogo PT-BR/" and pacote.leia_me == "Tradução PT-BR v1.0" and len(pacote.arquivos) == 2
    registro = tmp_path / "traducoes_instaladas.json"
    feito = it.instalar(pacote, jogo, "PC")
    it.registrar(registro, feito)
    assert (jogo / "data" / "textos.json").read_text() == '{"oi": "olá"}' and (jogo / "data" / "fonte_pt.ttf").is_file()
    assert feito.trocados == ["data/textos.json"] and feito.criados == ["data/fonte_pt.ttf"]
    lista = it.carregar(registro)
    assert [i.nome for i in lista] == ["Traducao PT-BR"]
    it.desfazer(lista[0])
    it.esquecer(registro, lista[0])
    assert (jogo / "data" / "textos.json").read_text() == '{"oi": "hello"}' and not (jogo / "data" / "fonte_pt.ttf").exists()
    assert not (jogo / it.COPIA_SEGURANCA).exists() and it.carregar(registro) == [] and (jogo / "jogo.exe").is_file()
    # criar o pacote da sua tradução: só o que mudou em relação ao jogo
    copia = tmp_path / "Meu Jogo (traduzido)"
    (copia / "data").mkdir(parents=True)
    (copia / "data" / "textos.json").write_text('{"oi": "olá"}')
    (copia / "jogo.exe").write_bytes(b"EXE")
    saida = it.criar_pacote(copia, tmp_path / "Meu Jogo PT-BR.zip", jogo, "Meu Jogo PT-BR v1.0")
    with zipfile.ZipFile(saida) as z:
        assert sorted(z.namelist()) == ["LEIA-ME.txt", "data/textos.json"]


def test_criar_o_mod_do_switch(tmp_path):
    romfs = tmp_path / "minha traducao" / "romfs" / "Message"
    romfs.mkdir(parents=True)
    (romfs / "Main.msbt").write_bytes(b"OLA")
    saida = it.criar_mod(tmp_path / "minha traducao", TID.lower(), tmp_path / "Meu Jogo PT-BR.zip")
    with zipfile.ZipFile(saida) as z:
        assert f"atmosphere/contents/{TID}/romfs/Message/Main.msbt" in z.namelist()
    pacote = it.ler_mod(saida)
    assert pacote.title_id == TID and pacote.partes == ["romfs"]
    solto = tmp_path / "so os arquivos"
    solto.mkdir()
    (solto / "Main.msbt").write_bytes(b"OLA")                  # sem a pasta romfs: o Maestro põe
    with zipfile.ZipFile(it.criar_mod(solto, TID, tmp_path / "b.zip")) as z:
        assert f"atmosphere/contents/{TID}/romfs/Main.msbt" in z.namelist()


def test_zip_do_windows_lixo_do_mac_e_somente_leitura(tmp_path):
    """O .zip feito por programa antigo do Windows (com "\\" nos caminhos) e com o lixo do Mac; o arquivo do jogo
    "somente leitura" é trocado e volta como era (com o "somente leitura") no Desfazer."""
    import stat
    jogo = tmp_path / "Meu Jogo"
    (jogo / "data").mkdir(parents=True)
    fala = jogo / "data" / "fala 01.ogg"
    fala.write_bytes(b"ORIGINAL")
    fala.chmod(stat.S_IREAD)
    caminho = tmp_path / "Tradução PT-BR.zip"
    with zipfile.ZipFile(caminho, "w") as z:
        for nome, dados in (("Meu Jogo PT-BR\\data\\fala 01.ogg", b"DUBLADA"), ("Meu Jogo PT-BR\\data\\textos.json",
                                                                                b"{}"),
                            ("__MACOSX/Meu Jogo PT-BR/._textos.json", b"x"), ("Meu Jogo PT-BR/Thumbs.db", b"x"),
                            ("Meu Jogo PT-BR/LEIA-ME.txt", b"Traducao v1")):
            info = zipfile.ZipInfo("x")
            info.filename = nome                       # (o zipfile trocaria a "\\"; o programa antigo não troca)
            z.writestr(info, dados)
    pacote = it.ler_pacote_pc(caminho, jogo)
    assert sorted(pacote.arquivos) == ["Meu Jogo PT-BR/data/fala 01.ogg", "Meu Jogo PT-BR/data/textos.json"]
    assert pacote.raiz == "Meu Jogo PT-BR/" and pacote.leia_me == "Traducao v1"
    feito = it.instalar(pacote, jogo, "PC")
    assert fala.read_bytes() == b"DUBLADA" and (jogo / "data" / "textos.json").read_bytes() == b"{}"
    it.desfazer(feito)
    assert fala.read_bytes() == b"ORIGINAL" and not fala.stat().st_mode & stat.S_IWRITE
    assert not (jogo / it.COPIA_SEGURANCA).exists() and not (jogo / "data" / "textos.json").exists()
