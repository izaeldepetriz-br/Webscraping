"""Pasta vigiada: só o que terminou de baixar é organizado."""
import os
import time

from jellyfin_tools import CatalogoLocal, organizar_pasta
from jellyfin_tools.vigia import filtro_prontos, pronto

HORA = 3600


def _video(caminho, idade_s=0):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_bytes(b"v")
    antigo = time.time() - idade_s
    os.utime(caminho, (antigo, antigo))
    return caminho


def test_pronto_so_depois_de_parar_e_sem_download_em_andamento(tmp_path):
    parado = _video(tmp_path / "Matrix.1999" / "Matrix.1999.mkv", idade_s=HORA)
    assert pronto(parado, espera=120)
    novo = _video(tmp_path / "Dark" / "Dark.S01E01.mkv", idade_s=10)           # ainda sendo escrito
    assert not pronto(novo, espera=120)
    em_andamento = _video(tmp_path / "Creed" / "Creed.II.2018.mkv", idade_s=HORA)
    (tmp_path / "Creed" / "Creed.II.2018.parte2.mkv.!qB").write_bytes(b"x")     # outro arquivo ainda baixando
    assert not pronto(em_andamento, espera=120)


def test_organizar_so_os_prontos(tmp_path):
    origem = tmp_path / "Downloads"
    _video(origem / "Matrix.1999.mkv", idade_s=HORA)
    _video(origem / "Cidade.de.Deus.2002.mkv", idade_s=5)
    movs = organizar_pasta(origem, tmp_path / "Filmes", CatalogoLocal.padrao(), aplicar=True,
                           filtro=filtro_prontos(120))
    assert [m.origem.name for m in movs] == ["Matrix.1999.mkv"]
    assert (tmp_path / "Filmes" / "Matrix (1999)" / "Matrix (1999).mkv").exists()
    assert (origem / "Cidade.de.Deus.2002.mkv").exists()                        # ainda baixando: fica


def test_script_vigiar_uma_volta(tmp_path, monkeypatch):
    import organizar_jellyfin as script
    origem, filmes = tmp_path / "Downloads", tmp_path / "Filmes"
    _video(origem / "Matrix.1999.mkv", idade_s=HORA)
    _video(origem / "Cidade.de.Deus.2002.mkv", idade_s=5)
    for nome, valor in {"PASTA_ENTRADA": origem, "PASTA_FILMES": filmes, "PRONTO_APOS_MIN": "2",
                        "ARQUIVO_LOG": tmp_path / "log" / "j.log"}.items():
        monkeypatch.setenv(nome, str(valor))
    monkeypatch.setattr(script, "montar_catalogo", CatalogoLocal.padrao)
    monkeypatch.setattr(script, "pos_processar_lote", lambda itens, log, notificar=True: [])
    log = script.configurar_log(tmp_path / "log" / "j.log", no_terminal=False)
    pausas = []
    assert script.vigiar(log, ciclos=2, dormir=pausas.append) == 0
    assert (filmes / "Matrix (1999)" / "Matrix (1999).mkv").exists()
    assert (origem / "Cidade.de.Deus.2002.mkv").exists()
    assert pausas == [5 * 60]                                                   # VIGIAR_A_CADA_MIN, entre as voltas
    assert "terminaram de baixar" in (tmp_path / "log" / "j.log").read_text(encoding="utf-8")


def test_pasta_misturada_separa_filmes_e_series(tmp_path):
    from jellyfin_tools.organizador import eh_episodio_de_serie, organizar_misto
    for nome, serie in (("Dark.S01E02.mkv", True), ("The Office 3x07.avi", True), ("HunterXHunter 01.mp4", True),
                        ("Matrix.1999.1080p.mkv", False), ("Rocky.II.1979.mkv", False)):
        assert eh_episodio_de_serie(tmp_path / nome) is serie, nome
    downloads = tmp_path / "uTorrent"
    for nome in ("Filmes/Matrix.1999.1080p.mkv", "Series/Dark.S01E02.mkv", "Misturada/Breaking.Bad.S02E05.mkv",
                 "Misturada/Cidade.de.Deus.2002.mkv"):
        _video(downloads / nome, idade_s=HORA)
    movs = organizar_misto(downloads, tmp_path / "Filmes", tmp_path / "Series", CatalogoLocal.padrao(),
                           filtro=filtro_prontos(120), aplicar=True)
    assert sorted(m.destino.relative_to(tmp_path).as_posix() for m in movs) == [
        "Filmes/Cidade de Deus (2002)/Cidade de Deus (2002).mkv", "Filmes/Matrix (1999)/Matrix (1999).mkv",
        "Series/Breaking Bad (2008)/Season 02/Breaking Bad S02E05.mkv", "Series/Dark (2017)/Season 01/Dark S01E02.mkv"]
    assert all(m.status == "movido" for m in movs)


def test_sem_biblioteca_de_series_os_episodios_ficam(tmp_path):
    from jellyfin_tools.organizador import organizar_misto
    _video(tmp_path / "d" / "Dark.S01E02.mkv", idade_s=HORA)
    _video(tmp_path / "d" / "Matrix.1999.mkv", idade_s=HORA)
    movs = organizar_misto(tmp_path / "d", tmp_path / "Filmes", None, CatalogoLocal.padrao(), aplicar=True)
    assert [m.origem.name for m in movs] == ["Matrix.1999.mkv"] and (tmp_path / "d" / "Dark.S01E02.mkv").exists()


def test_script_vigia_as_pastas_do_utorrent(tmp_path, monkeypatch):
    import organizar_jellyfin as script
    torrent_filmes, torrent_series = tmp_path / "uTorrent" / "Filmes", tmp_path / "uTorrent" / "Series"
    _video(torrent_filmes / "Matrix.1999.1080p" / "Matrix.1999.1080p.mkv", idade_s=HORA)
    _video(torrent_series / "Dark.S01" / "Dark.S01E02.mkv", idade_s=HORA)
    _video(torrent_series / "Dark.S01" / "Dark.S01E03.mkv", idade_s=5)                 # ainda baixando
    for nome, valor in {"VIGIAR_PASTAS": f"{torrent_filmes};{torrent_series}", "PASTA_ENTRADA": tmp_path,
                        "PASTA_FILMES": tmp_path / "Jellyfin" / "Filmes", "PASTA_SERIES": tmp_path / "Jellyfin" / "Series",
                        "ARQUIVO_LOG": tmp_path / "log" / "j.log"}.items():
        monkeypatch.setenv(nome, str(valor))
    assert script.cfg("VIGIAR_PASTAS") == [str(torrent_filmes), str(torrent_series)]
    monkeypatch.setattr(script, "montar_catalogo", CatalogoLocal.padrao)
    processados = []
    monkeypatch.setattr(script, "pos_processar_lote", lambda itens, log, notificar=True: processados.extend(itens))
    log = script.configurar_log(tmp_path / "log" / "j.log", no_terminal=False)
    assert script.vigiar(log, ciclos=1) == 0
    jellyfin = tmp_path / "Jellyfin"
    assert sorted(p.relative_to(jellyfin).as_posix() for p in jellyfin.rglob("*.mkv")) == [
        "Filmes/Matrix (1999)/Matrix (1999).mkv", "Series/Dark (2017)/Season 01/Dark S01E02.mkv"]
    assert (torrent_series / "Dark.S01" / "Dark.S01E03.mkv").exists()
    assert sorted(nome for _, nome in processados) == ["Dark S01E02", "Matrix (1999)"]   # legendas/pôster/aviso
