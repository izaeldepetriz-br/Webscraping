"""TMDB: teste de conexão, buscas em paralelo com cache, de onde veio o nome ("Nome via"),
nomes dos episódios de séries e o andamento (%) da análise."""
import threading
import time

import pytest

from jellyfin_tools import CatalogoEmCadeia, CatalogoLocal, CatalogoTMDB, ErroCatalogo, organizar_pasta
from jellyfin_tools.nomes import nome_episodio_jellyfin


def _tmdb(api, chave="chave123"):
    return CatalogoTMDB(chave, base_url=api.base + "/3")


def _pedidos(api, caminho):
    return [p for p in api.pedidos if p["caminho"] == caminho]


def _filmes_falsos(api, atraso=0.0):
    """search/movie que devolve o próprio título pesquisado, com o ano pedido."""
    def busca(q):
        time.sleep(atraso)
        titulo, ano = q["query"][0], q.get("year", ["2000"])[0]
        return 200, {"results": [{"id": abs(hash(titulo)) % 10**6, "title": titulo.title(),
                                  "original_title": titulo, "release_date": f"{ano}-01-01"}]}
    api.rotas["/3/search/movie"] = busca


# ------------------------------------------------------------------ teste de conexão
def test_testar_conexao_ok_e_chave_recusada(api_falsa):
    api_falsa.rotas["/3/configuration"] = lambda q: (
        (200, {"images": {}}) if q.get("api_key") == ["boa"] else (401, {"status_message": "Invalid API key"}))
    assert "conectado ao TMDB" in _tmdb(api_falsa, "boa").testar()
    with pytest.raises(ErroCatalogo, match="recusou a chave"):
        _tmdb(api_falsa, "errada").testar()


def test_token_v4_vai_no_cabecalho_tambem_no_teste(api_falsa):
    api_falsa.rotas["/3/configuration"] = lambda q: (200, {})
    assert "token de leitura" in _tmdb(api_falsa, "eyJtoken").testar()
    pedido = _pedidos(api_falsa, "/3/configuration")[-1]
    assert pedido["headers"]["Authorization"] == "Bearer eyJtoken" and "api_key" not in pedido["query"]


def test_sem_internet_no_teste():
    with pytest.raises(ErroCatalogo, match="fora do ar ou sem internet"):
        CatalogoTMDB("k", base_url="http://127.0.0.1:9/3", timeout=2).testar()


# ------------------------------------------------------------------ paralelo + cache
def test_pre_buscar_em_paralelo_e_cache_evita_repetir(api_falsa):
    _filmes_falsos(api_falsa, atraso=0.2)
    consultas = [(f"filme {n}", 2000 + n, "filme") for n in range(18)]
    inicio = time.perf_counter()
    _tmdb(api_falsa).pre_buscar(consultas + consultas[:5])        # repetidas contam uma vez só
    gasto = time.perf_counter() - inicio
    assert len(_pedidos(api_falsa, "/3/search/movie")) == 18
    assert gasto < 18 * 0.2 / 3, f"não paralelizou: {gasto:.2f}s"   # sequencial seria 3,6 s

    outro = _tmdb(api_falsa)                                        # nova instância (o Organizar)
    filme = outro.buscar("filme 3", 2003)
    assert filme.titulo == "Filme 3" and filme.fonte == "TMDB"
    assert len(_pedidos(api_falsa, "/3/search/movie")) == 18        # veio do cache


def test_erro_grave_nao_insiste_em_cada_filme(api_falsa):
    api_falsa.rotas["/3/search/movie"] = lambda q: (401, {"status_message": "Invalid API key"})
    tmdb = _tmdb(api_falsa, "errada")
    tmdb.pre_buscar([(f"filme {n}", 2000, "filme") for n in range(40)])
    assert len(_pedidos(api_falsa, "/3/search/movie")) <= CatalogoTMDB.TRABALHADORES   # não 40
    assert "recusou a chave" in tmdb.erro
    with pytest.raises(ErroCatalogo):
        tmdb.buscar("outro", 2001)


def test_429_espera_e_tenta_de_novo(api_falsa):
    vezes = []

    def busca(q):
        vezes.append(1)
        if len(vezes) == 1:
            return 429, {"status_message": "calma"}
        return 200, {"results": [{"id": 1, "title": "Matrix", "release_date": "1999-03-31"}]}
    api_falsa.rotas["/3/search/movie"] = busca
    assert _tmdb(api_falsa).buscar("Matrix", 1999).titulo == "Matrix"
    assert len(vezes) == 2


# ------------------------------------------------------------------ "Nome via"
def test_fonte_do_nome_tmdb_catalogo_e_arquivo(api_falsa, tmp_path):
    origem = tmp_path / "Downloads"
    origem.mkdir()
    for nome in ("Matrix.1999.mkv", "Filme.Caseiro.2020.mkv", "Interestelar.2014.mkv", "sem ano.mkv"):
        (origem / nome).write_bytes(b"v")
    matrix = {"results": [{"id": 603, "title": "Matrix", "original_title": "The Matrix",
                           "release_date": "1999-03-31"}]}
    api_falsa.rotas["/3/search/movie"] = lambda q: (200, matrix if q["query"] == ["Matrix"] else {"results": []})
    catalogo = CatalogoEmCadeia(_tmdb(api_falsa), CatalogoLocal.padrao())      # TMDB primeiro
    fontes = {m.origem.name: m.fonte_nome for m in organizar_pasta(origem, tmp_path / "F", catalogo)}
    assert fontes == {"Matrix.1999.mkv": "TMDB",
                      "Interestelar.2014.mkv": "catálogo",     # o TMDB falso não conhece; o local sim
                      "Filme.Caseiro.2020.mkv": "arquivo",     # ninguém conhece: nome do próprio arquivo
                      "sem ano.mkv": ""}                       # não identificado: sem nome novo


# ------------------------------------------------------------------ andamento (%) da análise
def test_andamento_da_analise_sem_e_com_tmdb(api_falsa, tmp_path):
    origem = tmp_path / "Downloads"
    origem.mkdir()
    for n in range(250):
        (origem / f"Filme.Numero.{n}.{1950 + n % 70}.mkv").write_bytes(b"v")

    avisos = []
    organizar_pasta(origem, tmp_path / "F", CatalogoLocal.padrao(), ao_analisar=lambda f, t: avisos.append((f, t)))
    fracoes = [f for f, _ in avisos]
    assert fracoes == sorted(fracoes) and fracoes[-1] == 1.0
    assert len(avisos) <= 130                                   # ~100 avisos, não 250: não trava a janela
    assert avisos[-1][1].startswith("Analisando: 250 de 250")

    _filmes_falsos(api_falsa)
    avisos.clear()
    organizar_pasta(origem, tmp_path / "F", _tmdb(api_falsa), ao_analisar=lambda f, t: avisos.append((f, t)))
    fracoes = [f for f, _ in avisos]
    assert fracoes == sorted(fracoes) and fracoes[-1] == 1.0
    textos = [t for _, t in avisos]
    assert textos[0] == "Consultando o TMDB..." and "Consultando o TMDB: 250 de 250" in textos
    assert any(f == pytest.approx(0.9) for f, t in avisos if t.startswith("Consultando o TMDB: 250"))


def test_aviso_vem_de_outra_thread_sem_travar(api_falsa, tmp_path):
    """A janela recebe os avisos por fila; aqui só garante que o callback pode ser chamado de threads."""
    origem = tmp_path / "o"
    origem.mkdir()
    (origem / "Matrix.1999.mkv").write_bytes(b"v")
    _filmes_falsos(api_falsa)
    threads = set()
    organizar_pasta(origem, tmp_path / "F", _tmdb(api_falsa),
                    ao_analisar=lambda f, t: threads.add(threading.current_thread().name))
    assert threads


# ------------------------------------------------------------------ nomes dos episódios
def _series_falsas(api):
    api.rotas["/3/search/tv"] = lambda q: (200, {"results": [
        {"id": 70523, "name": "Dark", "original_name": "Dark", "first_air_date": "2017-12-01"}]})
    api.rotas["/3/tv/70523/season/1"] = lambda q: (200, {"episodes": [
        {"episode_number": 1, "name": "Segredos"},
        {"episode_number": 2, "name": "Mentiras: parte 1/2"},     # ':' e '/' não podem ir no nome do arquivo
        {"episode_number": 3, "name": "Episódio 3"}]})            # ainda sem tradução: fica só o número
    api.rotas["/3/tv/70523/season/2"] = lambda q: (404, {"status_message": "not found"})


def test_nome_episodio_jellyfin_mantem_o_numero():
    assert nome_episodio_jellyfin("Dark", 1, 1) == "Dark S01E01"
    assert nome_episodio_jellyfin("Dark", 1, 1, "Segredos") == "Dark S01E01 - Segredos"
    assert nome_episodio_jellyfin("Dark", 1, 2, "Mentiras: parte 1/2") == "Dark S01E02 - Mentiras - parte 12"


def test_series_ganham_o_nome_do_episodio(api_falsa, tmp_path):
    _series_falsas(api_falsa)
    origem, series = tmp_path / "Downloads", tmp_path / "Series"
    origem.mkdir()
    for nome in ("Dark.S01E01.1080p.mkv", "Dark.S01E01.1080p.srt", "Dark.S01E02.mkv", "Dark.S01E03.mkv",
                 "Dark.S02E01.mkv"):
        (origem / nome).write_bytes(b"v")
    movimentos = organizar_pasta(origem, series, _tmdb(api_falsa), modo="series", nomes_episodios=True)
    novos = {m.origem.name: m.destino_curto for m in movimentos}
    assert novos == {
        "Dark.S01E01.1080p.mkv": "Dark (2017)/Season 01/Dark S01E01 - Segredos.mkv",
        "Dark.S01E02.mkv": "Dark (2017)/Season 01/Dark S01E02 - Mentiras - parte 12.mkv",
        "Dark.S01E03.mkv": "Dark (2017)/Season 01/Dark S01E03.mkv",              # nome genérico: só o número
        "Dark.S02E01.mkv": "Dark (2017)/Season 02/Dark S02E01.mkv"}              # temporada sem dados
    m1 = next(m for m in movimentos if m.origem.name == "Dark.S01E01.1080p.mkv")
    assert [novo.name for _, novo in m1.acompanhantes] == ["Dark S01E01 - Segredos.pt-BR.srt"]
    assert len(_pedidos(api_falsa, "/3/tv/70523/season/1")) == 1                # UM pedido por temporada
    assert len(_pedidos(api_falsa, "/3/search/tv")) == 1                         # a série, uma vez

    sem = organizar_pasta(origem, series, _tmdb(api_falsa), modo="series", nomes_episodios=False)
    assert {m.destino.name for m in sem} >= {"Dark S01E01.mkv", "Dark S01E02.mkv"}


def test_episodios_ja_organizados_sao_renomeados_e_titulo_nao_some(api_falsa, tmp_path):
    _series_falsas(api_falsa)
    temporada = tmp_path / "Series" / "Dark (2017)" / "Season 01"
    temporada.mkdir(parents=True)
    (temporada / "Dark S01E01.mkv").write_bytes(b"v")                 # só o número: ganha o nome
    (temporada / "Dark S01E02 - Mentira.mkv").write_bytes(b"v")       # nome diferente: vale o do TMDB
    (temporada / "Dark S01E03 - Meu Titulo.mkv").write_bytes(b"v")    # TMDB sem nome: mantém o que tem
    series = tmp_path / "Series"
    movimentos = organizar_pasta(series, series, _tmdb(api_falsa), modo="series", nomes_episodios=True,
                                 aplicar=True)
    assert sorted(p.name for p in temporada.iterdir()) == ["Dark S01E01 - Segredos.mkv",
                                                           "Dark S01E02 - Mentiras - parte 12.mkv",
                                                           "Dark S01E03 - Meu Titulo.mkv"]
    assert sorted(m.status for m in movimentos) == ["movido", "movido", "organizado"]

    # TMDB fora do ar depois: o nome que o arquivo já tem continua (não volta para 'S01E01')
    CatalogoTMDB.limpar_cache()
    fora = CatalogoTMDB("k", base_url="http://127.0.0.1:9/3", timeout=1)
    local = CatalogoLocal.padrao()
    outra = organizar_pasta(series, series, CatalogoEmCadeia(fora, local), modo="series", nomes_episodios=True)
    assert {m.status for m in outra} == {"organizado"}
