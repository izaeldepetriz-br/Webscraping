"""Modo séries: Séries/Nome (Ano)/Season 01/Nome S01E02.ext e legendas por episódio."""
import pytest

from jellyfin_tools import (CatalogoLocal, CatalogoTMDB, ConfigSite, ProvedorOpenSubtitles, ProvedorSiteHTML,
                            baixar_legenda_episodio, baixar_legendas_series, desfazer, extrair_episodio,
                            organizar_pasta)
from jellyfin_tools.organizador import ultimo_log
from videoscraper.rede import ClienteHTTP


@pytest.mark.parametrize("nome, esperado", [
    ("Breaking.Bad.2008.S02E05.720p.mkv", ("Breaking Bad", 2, 5, 2008)),
    ("dark_episodio_03_dublado.mp4", ("dark", 1, 3, None)),
    ("The Office 3x07.avi", ("The Office", 3, 7, None)),
    ("Dark - Temporada 2 Episodio 4.mkv", ("Dark", 2, 4, None)),
    ("Dark.S01.E08.WEB-DL.mkv", ("Dark", 1, 8, None)),
    ("Cidade.dos.Homens.Ep.07.mkv", ("Cidade dos Homens", 1, 7, None)),
    ("The.Expanse.S03E10.1080p.x265-GRUPO.mkv", ("The Expanse", 3, 10, None)),
    ("Matrix.1999.mkv", None),                 # filme, não episódio
    ("Blade.Runner.2049.2017.mkv", None),
    ("S01E01.mkv", None),                      # sem nome da série
])
def test_extrair_episodio(nome, esperado):
    assert extrair_episodio(nome) == esperado


def test_catalogo_separa_filmes_de_series():
    c = CatalogoLocal.padrao()
    assert c.buscar("dark", None, "serie").titulo == "Dark"
    assert c.buscar("Matrix", 1999, "serie") is None
    assert c.buscar("Breaking Bad", None, "filme") is None


ARQUIVOS = {
    "Breaking.Bad.2008.S02E05.720p.mkv": "Breaking Bad (2008)/Season 02/Breaking Bad S02E05.mkv",
    "dark_episodio_01_dublado.mp4": "Dark (2017)/Season 01/Dark S01E01.mp4",
    "Dark.S01E02.WEBRip.mkv": "Dark (2017)/Season 01/Dark S01E02.mkv",
    "Serie.Caseira.S01E01.mkv": "Serie Caseira/Season 01/Serie Caseira S01E01.mkv",   # fora do catálogo
}


def _criar(pasta, nomes):
    pasta.mkdir(parents=True, exist_ok=True)
    for n in nomes:
        (pasta / n).write_bytes(b"video")


def test_organiza_series_e_desfaz_sem_apagar_a_biblioteca(tmp_path):
    origem, series = tmp_path / "Downloads", tmp_path / "Series"
    _criar(origem, list(ARQUIVOS) + ["Matrix.1999.mkv"])
    (origem / "Dark.S01E02.WEBRip.pt-BR.srt").write_text("1\n00:00 --> 00:01\noi\n")
    movs = {m.origem.name: m for m in organizar_pasta(origem, series, CatalogoLocal.padrao(),
                                                       aplicar=True, modo="series")}
    for arquivo, destino in ARQUIVOS.items():
        assert movs[arquivo].status == "movido" and (series / destino).is_file()
    assert movs["Dark.S01E02.WEBRip.mkv"].destino_curto == "Dark (2017)/Season 01/Dark S01E02.mkv"
    assert movs["Dark.S01E02.WEBRip.mkv"].episodio == (1, 2)
    assert movs["Matrix.1999.mkv"].status == "nao_identificado"             # filme no modo séries
    assert (series / "Dark (2017)/Season 01/Dark S01E02.pt-BR.srt").is_file()  # legenda foi junto

    desfazer(ultimo_log(series))
    assert sorted(p.name for p in origem.iterdir()) == sorted(
        list(ARQUIVOS) + ["Matrix.1999.mkv", "Dark.S01E02.WEBRip.pt-BR.srt"])
    assert series.is_dir()                                                   # a biblioteca fica
    assert [p.name for p in series.iterdir()] == [".organizador"]           # Season/Série vazias saem


def test_modo_invalido(tmp_path):
    with pytest.raises(ValueError):
        organizar_pasta(tmp_path, tmp_path / "x", modo="novelas")


def _provedor(site):
    return ProvedorSiteHTML(ConfigSite(site.base + "/busca?q={consulta}", nome="demo"), ClienteHTTP(espera=0))


def _episodio(raiz, serie, temporada, nome):
    pasta = raiz / serie / f"Season {temporada:02d}"
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / nome).write_bytes(b"video")
    return pasta / nome


def test_legenda_do_episodio_certo(tmp_path, site_legendas):
    video = _episodio(tmp_path, "Dark (2017)", 1, "Dark S01E02.mkv")
    r = baixar_legenda_episodio(video, [_provedor(site_legendas)])
    assert r.status == "baixada" and r.caminho == video.with_name("Dark S01E02.pt-BR.srt")
    assert "Dark S01E02" in r.caminho.read_text(encoding="utf-8")       # não pegou o E01 nem o inglês

    sem = _episodio(tmp_path, "Dark (2017)", 3, "Dark S03E09.mkv")
    assert baixar_legenda_episodio(sem, [_provedor(site_legendas)]).status == "nao_encontrada"


def test_legendas_de_toda_a_biblioteca_de_series(tmp_path, site_legendas):
    _episodio(tmp_path, "Dark (2017)", 1, "Dark S01E01.mkv")
    _episodio(tmp_path, "Dark (2017)", 1, "Dark S01E02.mkv")
    _episodio(tmp_path, "Breaking Bad (2008)", 2, "Breaking Bad S02E05.mkv")       # vem em .zip
    vistos = []
    resultados = baixar_legendas_series(tmp_path, [_provedor(site_legendas)], catalogo=CatalogoLocal.padrao(),
                                        ao_terminar=lambda i, r: vistos.append(i))
    assert [r.status for r in resultados] == ["baixada"] * 3 and vistos == [0, 1, 2]
    assert (tmp_path / "Breaking Bad (2008)/Season 02/Breaking Bad S02E05.pt-BR.srt").is_file()


def test_tmdb_series_e_opensubtitles_episodio(tmp_path, api_falsa):
    api_falsa.rotas["/3/search/tv"] = lambda q: (200, {"results": [
        {"id": 70523, "name": "Dark", "original_name": "Dark", "first_air_date": "2017-12-01"}]})
    serie = CatalogoTMDB("k", base_url=api_falsa.base + "/3").buscar("dark", None, "serie")
    assert (serie.titulo, serie.ano, serie.tmdb_id, serie.tipo) == ("Dark", 2017, 70523, "serie")

    api_falsa.rotas["/api/v1/subtitles"] = lambda q: (200, {"data": [
        {"attributes": {"language": "pt-br", "download_count": 9, "files": [{"file_id": 1}],
                        "feature_details": {"parent_title": "Dark", "season_number": 1, "episode_number": 1}}},
        {"attributes": {"language": "pt-br", "download_count": 5, "files": [{"file_id": 2}],
                        "feature_details": {"parent_title": "Dark", "season_number": 1, "episode_number": 2}}}]})
    api_falsa.rotas["/api/v1/download"] = lambda q: (200, {"link": api_falsa.base + "/s.srt"})
    api_falsa.rotas["/s.srt"] = lambda q: (200, b"1\n00:00:01,000 --> 00:00:02,000\nOi\n")
    video = _episodio(tmp_path, "Dark (2017)", 1, "Dark S01E02.mkv")
    r = baixar_legenda_episodio(video, [ProvedorOpenSubtitles("k", base_url=api_falsa.base + "/api/v1")])
    assert r.status == "baixada"
    busca = next(p for p in api_falsa.pedidos if p["caminho"] == "/api/v1/subtitles")
    assert busca["query"]["type"] == ["episode"] and busca["query"]["episode_number"] == ["2"]
    download = next(p for p in api_falsa.pedidos if p["caminho"] == "/api/v1/download")
    assert b'"file_id": 2' in download["corpo"]                       # o do episódio 2, não o mais baixado
