"""Parte 1: leitura de nomes, catálogo e organização no padrão do Jellyfin."""

import pytest

from jellyfin_tools import (CatalogoEmCadeia, CatalogoLocal, CatalogoTMDB, ErroCatalogo, Filme,
                            desfazer, extrair_titulo_e_ano, nome_jellyfin, organizar_pasta)
from jellyfin_tools.nomes import formatar_titulo, ler_nome_jellyfin
from jellyfin_tools.organizador import ultimo_log

# Os 3 casos do enunciado: arquivo -> pasta/arquivo esperados
CASOS = {
    "Matrix.1999.1080p.BluRay.x264-VERSAO.mp4": "Matrix (1999)/Matrix (1999).mp4",
    "interestellar_filme_completo_dublado_2014.mkv": "Interstellar (2014)/Interstellar (2014).mkv",
    "O.Poderoso.Chefao.1972.Bluray.mkv": "O Poderoso Chefão (1972)/O Poderoso Chefão (1972).mkv",
}


@pytest.mark.parametrize("nome, titulo, ano", [
    ("Matrix.1999.1080p.BluRay.x264-VERSAO.mp4", "Matrix", 1999),
    ("interestellar_filme_completo_dublado_2014.mkv", "interestellar", 2014),
    ("O.Poderoso.Chefao.1972.Bluray.mkv", "O Poderoso Chefao", 1972),
    ("Blade.Runner.2049.2017.2160p.mkv", "Blade Runner 2049", 2017),     # 2049 é título, não ano
    ("1917.2019.mkv", "1917", 2019),
    ("1917.mkv", "1917", None),
    ("Duna.Parte.Dois.1080p.WEB-DL.mkv", "Duna Parte Dois", None),       # corta no 1080p
    ("Star Wars - Episode IV [1977] (Dublado).avi", "Star Wars Episode IV", 1977),
    ("Filme.de.Terror.2010.Dublado.mkv", "Filme de Terror", 2010),        # 'Filme' é o título aqui
])
def test_extrair_titulo_e_ano(nome, titulo, ano):
    assert extrair_titulo_e_ano(nome) == (titulo, ano)


def test_nomes_no_padrao_jellyfin():
    assert nome_jellyfin("Missão: Impossível", 1996) == "Missão - Impossível (1996)"
    assert nome_jellyfin("Matrix", 1999, 603, incluir_tmdbid=True) == "Matrix (1999) [tmdbid-603]"
    assert nome_jellyfin('Que?/Filme*"', 2000) == "QueFilme (2000)"
    assert ler_nome_jellyfin("Matrix (1999) [tmdbid-603]") == ("Matrix", 1999)
    assert formatar_titulo("o senhor dos aneis") == "O Senhor dos Aneis"


def test_catalogo_corrige_digitacao_acentos_e_respeita_o_ano():
    c = CatalogoLocal.padrao()
    assert c.buscar("interestellar", 2014).titulo == "Interstellar"
    assert c.buscar("O Poderoso Chefao", 1972).titulo == "O Poderoso Chefão"
    assert c.buscar("The Godfather", 1972).titulo == "O Poderoso Chefão"    # pelo título original
    assert c.buscar("Matrix", 2021) is None                                 # outro filme
    assert c.buscar("Filme Que Nao Existe", 2001) is None


def _criar(pasta, nomes):
    pasta.mkdir(parents=True, exist_ok=True)
    for n in nomes:
        (pasta / n).write_bytes(b"video")


def test_simulacao_nao_mexe_em_nada(tmp_path):
    _criar(tmp_path / "bagunca", CASOS)
    movs = organizar_pasta(tmp_path / "bagunca", tmp_path / "Filmes", CatalogoLocal.padrao())
    assert {m.status for m in movs} == {"simulado"}
    assert not (tmp_path / "Filmes").exists()
    assert sorted(p.name for p in (tmp_path / "bagunca").iterdir()) == sorted(CASOS)


def test_organiza_os_3_arquivos_do_enunciado_e_desfaz(tmp_path):
    origem, filmes = tmp_path / "bagunca", tmp_path / "Filmes"
    _criar(origem, CASOS)
    (origem / "Matrix.1999.1080p.BluRay.x264-VERSAO.pt-BR.srt").write_text("1\n00:00 --> 00:01\noi\n")
    movs = organizar_pasta(origem, filmes, CatalogoLocal.padrao(), aplicar=True)
    assert {m.status for m in movs} == {"movido"}
    for esperado in CASOS.values():
        assert (filmes / esperado).is_file()
    assert (filmes / "Matrix (1999)" / "Matrix (1999).pt-BR.srt").is_file()   # legenda foi junto

    mensagens = desfazer(ultimo_log(filmes))
    assert sorted(p.name for p in origem.iterdir()) == sorted(
        list(CASOS) + ["Matrix.1999.1080p.BluRay.x264-VERSAO.pt-BR.srt"])
    assert not any(p.is_dir() for p in filmes.iterdir() if not p.name.startswith("."))
    assert all(m.startswith("voltou") for m in mensagens)


def test_conflitos_amostras_e_nao_identificados(tmp_path):
    origem, filmes = tmp_path / "bagunca", tmp_path / "Filmes"
    _criar(origem, ["Matrix.1999.mkv", "Matrix.1999.sample.mkv", "video_sem_ano.mp4", "Filme.Caseiro.2010.mp4"])
    _criar(origem / "sub", ["The.Matrix.1999.720p.mkv"])
    _criar(filmes / "Cidade de Deus (2002)", ["Cidade de Deus (2002).mkv"])
    _criar(origem, ["Cidade.de.Deus.2002.mkv"])
    status = {m.origem.name: (m.status, m.destino) for m in
              organizar_pasta(origem, filmes, CatalogoLocal.padrao(), aplicar=True)}
    assert status["Matrix.1999.mkv"][0] == "movido"
    assert status["The.Matrix.1999.720p.mkv"][0] == "conflito"       # mesmo filme, mesmo destino
    assert status["Matrix.1999.sample.mkv"][0] == "ignorado"
    assert status["video_sem_ano.mp4"][0] == "nao_identificado"
    assert status["Cidade.de.Deus.2002.mkv"][0] == "conflito"        # já existia na biblioteca
    assert status["Filme.Caseiro.2010.mp4"] == ("movido", filmes / "Filme Caseiro (2010)" / "Filme Caseiro (2010).mp4")
    assert (origem / "Cidade.de.Deus.2002.mkv").exists()             # nada foi sobrescrito


def test_exigir_catalogo_e_pasta_inexistente(tmp_path):
    _criar(tmp_path / "o", ["Filme.Caseiro.2010.mp4"])
    [m] = organizar_pasta(tmp_path / "o", tmp_path / "F", CatalogoLocal.padrao(), exigir_catalogo=True)
    assert m.status == "nao_identificado"
    with pytest.raises(NotADirectoryError):
        organizar_pasta(tmp_path / "nao-existe", tmp_path / "F")


def test_catalogo_json_invalido(tmp_path):
    (tmp_path / "c.json").write_text("[{\"titulo\": \"X\"}]")
    with pytest.raises(ErroCatalogo):
        CatalogoLocal.de_json(tmp_path / "c.json")


# ----------------------------------------------------------------- TMDB (servidor falso, sem internet)
def test_tmdb_com_servidor_falso(api_falsa):
    api_falsa.rotas["/3/search/movie"] = lambda q: (200, {"results": [
        {"id": 238, "title": "O Poderoso Chefão", "original_title": "The Godfather", "release_date": "1972-03-14"},
        {"id": 240, "title": "O Poderoso Chefão: Parte II", "original_title": "The Godfather Part II",
         "release_date": "1974-12-20"}]})
    tmdb = CatalogoTMDB("chave123", base_url=api_falsa.base + "/3")
    filme = tmdb.buscar("O Poderoso Chefao", 1972)
    assert filme == Filme("O Poderoso Chefão", 1972, "The Godfather", 238)
    pedido = api_falsa.pedidos[-1]
    assert pedido["query"]["api_key"] == ["chave123"] and pedido["query"]["language"] == ["pt-BR"]

    CatalogoTMDB("eyJtoken", base_url=api_falsa.base + "/3").buscar("O Poderoso Chefao", 1972)
    assert api_falsa.pedidos[-1]["headers"]["Authorization"] == "Bearer eyJtoken"


def test_tmdb_erros_e_cadeia(api_falsa):
    api_falsa.rotas["/3/search/movie"] = lambda q: (401, {"status_message": "Invalid API key"})
    tmdb = CatalogoTMDB("errada", base_url=api_falsa.base + "/3")
    with pytest.raises(ErroCatalogo, match="401"):
        tmdb.buscar("Matrix", 1999)
    # Em cadeia: o local responde antes; se só o TMDB falhar, não derruba o programa.
    cadeia = CatalogoEmCadeia(CatalogoLocal.padrao(), tmdb)
    assert cadeia.buscar("Matrix", 1999).titulo == "Matrix"
    assert cadeia.buscar("Desconhecido", 2001) is None
    with pytest.raises(ErroCatalogo):
        CatalogoTMDB("")
