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
    ep = extrair_episodio(nome)
    assert (tuple(ep[:4]) if ep else None) == esperado


@pytest.mark.parametrize("nome, absoluto", [
    ("Breaking.Bad.2008.S02E05.720p.mkv", False), ("The Office 3x07.avi", False),
    ("dark_episodio_03_dublado.mp4", True), ("Dragon Ball 153 - 1280x960.mkv", True), ("HunterXHunter 01.mp4", True)])
def test_marca_numeracao_continua(nome, absoluto):
    assert extrair_episodio(nome).absoluto is absoluto


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


def test_completar_series_usa_o_mesmo_motor_do_organizar(tmp_path, site_legendas):
    """Completar biblioteca (séries) = pós-processamento do Organizar, sem mover: legenda de cada
    episódio em cada idioma, título original pelo catálogo (1 consulta por série)."""
    from jellyfin_tools.pos_processamento import ConfigPos, itens_de_series, pos_processar
    temporada = tmp_path / "Dark (2017)" / "Season 01"
    temporada.mkdir(parents=True)
    for nome in ("Dark S01E01 - Segredos.mkv", "Dark S01E02.mkv", "extra sem numero.mkv"):
        (temporada / nome).write_bytes(b"v")

    class Contador(CatalogoLocal):
        consultas = 0

        def buscar(self, *a, **k):
            Contador.consultas += 1
            return super().buscar(*a, **k)
    itens = itens_de_series(tmp_path, Contador(CatalogoLocal.padrao().filmes))
    assert [(m.destino.name, m.episodio) for m, _ in itens] == [("Dark S01E01 - Segredos.mkv", (1, 1)),
                                                                 ("Dark S01E02.mkv", (1, 2))]
    assert Contador.consultas == 1 and itens[0][0].filme.titulo == "Dark"
    resultados = pos_processar(itens, ConfigPos(provedores=[_provedor(site_legendas)], idioma="pt-BR"))
    assert [r.legenda.status for r in resultados] == ["baixada", "baixada"]
    assert (temporada / "Dark S01E01 - Segredos.pt-BR.srt").is_file()


BIG_BANG = ["The.Big.Bang.Theory.S01E02.720p.BluRay.x264.DUAL-WWW.BLUDV.TV.mkv",
            "The.Big.Bang.Theory.S05E19.720p.BluRay.x264.DUAL-WWW.BLUDV.TV.mkv",
            "Big.Bang.Theory.S11E24.720p.WEB-DL.x264.DUAL-WWW.BLUDV.COM.mkv"]


def test_modo_filmes_reconhece_episodio_e_nao_consulta_como_filme(tmp_path):
    from jellyfin_tools import organizar_pasta
    from jellyfin_tools.nomes import marca_de_episodio
    assert marca_de_episodio(BIG_BANG[1]) == "S05E19"
    assert marca_de_episodio("Star.Wars.Episode.4.1977.mkv") is None            # filme, não episódio
    origem = tmp_path / "o"
    origem.mkdir()
    for nome in BIG_BANG + ["Matrix.1999.mkv"]:
        (origem / nome).write_bytes(b"v")
    consultas = []

    class Espiao(CatalogoLocal):
        def buscar(self, titulo, ano, tipo="filme"):
            consultas.append(titulo)
            return super().buscar(titulo, ano, tipo)
    movs = {m.origem.name: m for m in organizar_pasta(origem, tmp_path / "F", Espiao(CatalogoLocal.padrao().filmes))}
    assert movs[BIG_BANG[1]].status == "nao_identificado"
    assert movs[BIG_BANG[1]].detalhe == "é episódio de série (S05E19): use o modo Séries"
    assert movs["Matrix.1999.mkv"].status == "simulado" and consultas == ["Matrix"]


def test_big_bang_no_modo_series_vira_uma_serie_so(tmp_path):
    from jellyfin_tools import organizar_pasta
    origem = tmp_path / "The Big Bang a Teoria" / "Big Bang - A Teoria 2006 - 1ª Temporada WWW.BLUDV.TV"
    origem.mkdir(parents=True)
    for nome in BIG_BANG:
        (origem / nome).write_bytes(b"v")
    movs = organizar_pasta(tmp_path, tmp_path / "Series", CatalogoLocal.padrao(), modo="series")
    assert sorted(m.destino_curto for m in movs) == [
        "Big Bang - A Teoria (2007)/Season 01/Big Bang - A Teoria S01E02.mkv",
        "Big Bang - A Teoria (2007)/Season 05/Big Bang - A Teoria S05E19.mkv",
        "Big Bang - A Teoria (2007)/Season 11/Big Bang - A Teoria S11E24.mkv"]   # "The ..." e sem "The": a mesma


def test_um_maluco_no_pedaco_1x_entre_parenteses(tmp_path):
    from jellyfin_tools import organizar_pasta
    pasta = tmp_path / "Um Maluco no Pedaço" / "Um Maluco no pedaço 1ª Temporada"
    pasta.mkdir(parents=True)
    for nome in ("Um maluco no pedaço 1x (1).avi", "Um maluco no pedaço 1x (11).avi", "Um Maluco no Pedaço 6x (9).avi"):
        (pasta / nome).write_bytes(b"v")
    movs = organizar_pasta(tmp_path, tmp_path / "Series", CatalogoLocal.padrao(), modo="series")
    assert sorted(m.destino_curto for m in movs) == [
        "Um Maluco no Pedaço (1990)/Season 01/Um Maluco no Pedaço S01E01.avi",
        "Um Maluco no Pedaço (1990)/Season 01/Um Maluco no Pedaço S01E11.avi",
        "Um Maluco no Pedaço (1990)/Season 06/Um Maluco no Pedaço S06E09.avi"]


@pytest.mark.parametrize("nome, serie, temporada, episodio", [
    ("HunterXHunter 01.mp4", "Hunter X Hunter", 1, 1),
    ("HunterXHunter 62.mp4", "Hunter X Hunter", 1, 62),
    ("[SubsPlease] Hunter x Hunter - 01 (1080p) [A1B2].mkv", "Hunter x Hunter", 1, 1),
    ("Dragon Ball 001 - 1280x960.mkv", "Dragon Ball", 1, 1),
    ("Dragon.Ball.Z.045.1920x1080.mkv", "Dragon Ball Z", 1, 45),
    ("One.Piece.1071.1080p.mkv", "One Piece", 1, 1071)])
def test_anime_com_numeracao_absoluta(nome, serie, temporada, episodio):
    ep = extrair_episodio(nome)
    assert (ep.serie, ep.temporada, ep.episodio) == (serie, temporada, episodio)


@pytest.mark.parametrize("nome", ["Matrix.1999.mkv", "Filme Caseiro 2019.mkv", "BLUDV.mp4", "Clique Aqui Agora.mp4"])
def test_nao_viram_episodio(nome):
    assert extrair_episodio(nome) is None


def test_ano_da_pasta_escolhe_hunter_x_hunter_1999(tmp_path, api_falsa):
    """Há duas séries 'Hunter x Hunter' (1999 e 2011); a pasta 'hunter-x-hunter-1999' decide."""
    from jellyfin_tools import organizar_pasta

    def busca(q):
        series = [{"id": 46298, "name": "Hunter x Hunter", "first_air_date": "2011-10-02"},
                  {"id": 2153, "name": "Hunter x Hunter", "first_air_date": "1999-10-16"}]
        ano = q.get("first_air_date_year", [None])[0]
        return 200, {"results": [s for s in series if not ano or s["first_air_date"].startswith(ano)]}
    api_falsa.rotas["/3/search/tv"] = busca
    pasta = tmp_path / "Animes" / "hunter-x-hunter-1999 Ranking"
    pasta.mkdir(parents=True)
    for e in (1, 62):
        (pasta / f"HunterXHunter {e:02d}.mp4").write_bytes(b"v")
    tmdb = CatalogoTMDB("k", base_url=api_falsa.base + "/3")
    movs = organizar_pasta(pasta, tmp_path / "Series", tmdb, modo="series")
    assert sorted(m.destino_curto for m in movs) == [
        "Hunter x Hunter (1999)/Season 01/Hunter x Hunter S01E01.mp4",
        "Hunter x Hunter (1999)/Season 01/Hunter x Hunter S01E62.mp4"]


def test_dragon_ball_com_propaganda_bludv(tmp_path):
    from jellyfin_tools import organizar_pasta
    pasta = tmp_path / "Dragon Ball"
    pasta.mkdir()
    for e in (1, 2):
        with open(pasta / f"Dragon Ball 00{e} - 1280x960.mkv", "wb") as f:
            f.truncate(3 * 1024 * 1024)
    (pasta / "BLUDV.mp4").write_bytes(b"p")
    movs = organizar_pasta(tmp_path, tmp_path / "Series", CatalogoLocal.padrao(), modo="series", limite_trailer_mb=1)
    assert sorted(m.status for m in movs) == ["simulado", "simulado"]       # BLUDV.mp4 não é pendência
    assert [a.name for m in movs for a in m.apagar or []] == ["BLUDV.mp4"]


@pytest.mark.parametrize("pasta, arquivo, esperado", [
    ("hunter-x-hunter-1999 Ranking", "HunterXHunter 01.mp4", "Hunter x Hunter (1999)/Season 01/Hunter x Hunter S01E01.mp4"),
    ("hunter-x-hunter-2011", "HunterXHunter 01.mp4", "Hunter x Hunter (2011)/Season 01/Hunter x Hunter S01E01.mp4"),
    ("Tenchi Muyo/Tenchi Muyo! (Tenchi! Universe) [1995]", "Tenchi Muyo Universe 04.mkv",
     "Tenchi Universe (1995)/Season 01/Tenchi Universe S01E04.mkv"),
    ("Samurai X", "Samurai X - 01 Dual Audio.avi", "Samurai X (1996)/Season 01/Samurai X S01E01.avi"),
    ("Dragon Ball", "Dragon Ball 001 - 1280x960.mkv", "Dragon Ball (1986)/Season 01/Dragon Ball S01E01.mkv")])
def test_animes_dos_exemplos_sao_identificados(tmp_path, pasta, arquivo, esperado):
    from jellyfin_tools import organizar_pasta
    (tmp_path / "Animes" / pasta).mkdir(parents=True)
    (tmp_path / "Animes" / pasta / arquivo).write_bytes(b"v")
    [m] = organizar_pasta(tmp_path / "Animes", tmp_path / "Series", CatalogoLocal.padrao(), modo="series")
    assert (m.status, m.destino_curto, m.fonte_nome) == ("simulado", esperado, "catálogo")


def test_anime_com_numeracao_continua_no_modo_filmes_avisa_que_e_serie(tmp_path):
    """'Samurai X - 01 Dual Audio.avi' não tem S01E01 nem ano: no modo Filmes era só "não achei o ano".
    Com outros números da mesma série na pasta, é episódio (e a janela oferece o modo Séries)."""
    from jellyfin_tools.organizador import DETALHE_EPISODIO
    pasta = tmp_path / "Samurai X"
    pasta.mkdir()
    for n in (1, 2, 3):
        (pasta / f"Samurai X - {n:02d} Dual Audio.avi").write_bytes(b"v")
    sozinho = tmp_path / "Avulsos"
    sozinho.mkdir()
    (sozinho / "Rocky 2.avi").write_bytes(b"v")                      # um filme sem ano, sozinho: não é série
    movs = organizar_pasta(pasta, tmp_path / "Filmes", CatalogoLocal.padrao())
    assert [m.detalhe for m in movs] == [
        f"{DETALHE_EPISODIO} (episódio {n:02d}, numeração contínua): use o modo Séries" for n in (1, 2, 3)]
    rocky = organizar_pasta(sozinho, tmp_path / "Filmes", CatalogoLocal.padrao())
    assert rocky[0].status == "nao_identificado" and not rocky[0].detalhe.startswith(DETALHE_EPISODIO)
