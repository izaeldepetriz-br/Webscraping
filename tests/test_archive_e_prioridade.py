"""archive.org pela API oficial e prioridade dos links ao seguir páginas (sem internet)."""
from videoscraper import archive_org
from videoscraper.coleta import FonteRequests, priorizar, rastrear
from videoscraper.rede import ClienteHTTP
from videoscraper.servico import Trabalho


def test_priorizar_poe_resultados_antes_do_menu():
    links = ["https://s/about", "https://s/donate", "https://s/details/a", "https://s/blog",
             "https://s/details/b", "https://s/details/c"]
    assert priorizar(links) == ["https://s/details/a", "https://s/details/b", "https://s/details/c",
                                "https://s/about", "https://s/donate", "https://s/blog"]


def test_menu_nao_gasta_o_limite_de_paginas(servidor):
    """20 links de menu antes de 8 itens e limite de 10 páginas: antes achava 0 vídeos."""
    fonte = FonteRequests(ClienteHTTP(espera=0))
    links = rastrear(fonte, servidor.base + "/menu-e-resultados", profundidade=1, max_paginas=10)
    assert len(links) == 8                     # 1 página da lista + 8 itens (sobra 1 para o menu)
    filtrado = rastrear(fonte, servidor.base + "/menu-e-resultados", profundidade=1, max_paginas=5,
                        filtro_links="/item/")
    assert len(filtrado) == 4                  # com filtro, nenhuma visita ao menu


def _archive_falso(api, n_itens=250):
    """Coleção com n itens; cada item tem um original .mkv e um derivado .mp4."""
    def busca(q):
        assert q["q"] == ['collection:"Comedy_Films" AND mediatype:movies'] and q["output"] == ["json"]
        pagina, linhas = int(q["page"][0]), int(q["rows"][0])
        inicio = (pagina - 1) * linhas
        docs = [{"identifier": f"filme{i}", "title": f"Filme {i}"} for i in range(inicio, min(inicio + linhas, n_itens))]
        return 200, {"response": {"numFound": n_itens, "start": inicio, "docs": docs}}

    def metadata_item(i):
        return lambda q: (200, {"metadata": {"mediatype": "movies", "title": f"Filme {i}"}, "files": [
            {"name": f"filme{i}.mkv", "source": "original", "size": "900000000"},
            {"name": f"filme{i}.mp4", "source": "derivative", "size": "300000000"},
            {"name": f"filme{i}.thumbs/1.jpg", "source": "derivative"}]})

    api.rotas["/advancedsearch.php"] = busca
    api.rotas["/metadata/Comedy_Films"] = lambda q: (200, {"metadata": {"mediatype": "collection"}, "files": []})
    for i in range(n_itens):
        api.rotas[f"/metadata/filme{i}"] = metadata_item(i)
    api.rotas["/metadata/sem_video"] = lambda q: (200, {"metadata": {"mediatype": "movies"},
                                                        "files": [{"name": "capa.jpg"}]})


def test_colecao_inteira_pela_api(api_falsa, monkeypatch):
    _archive_falso(api_falsa, 250)
    monkeypatch.setattr(archive_org, "HOSTS", archive_org.HOSTS + (api_falsa.base.split("//")[1],))
    assert archive_org.POR_PAGINA == 500                        # lote padrão (buscas grandes, menos pedidos)
    monkeypatch.setattr(archive_org, "POR_PAGINA", 100)        # lote menor aqui, para testar várias páginas
    url = api_falsa.base + "/details/Comedy_Films"
    assert archive_org.reconhece(url)

    with Trabalho(espera=0) as t:
        links = t.buscar(url, max_paginas=250)
    assert len(links) == 250                                    # todos, não só os da tela
    assert links[0].url == api_falsa.base + "/download/filme0/filme0.mkv"   # o original
    assert links[0].titulo == "Filme 0" and links[0].tipo == "archive.org"
    paginas = [p["query"]["page"] for p in api_falsa.pedidos if p["caminho"] == "/advancedsearch.php"]
    assert paginas == [["1"], ["2"], ["3"]]                     # 100 + 100 + 50


def test_limite_item_unico_e_sem_video(api_falsa, monkeypatch):
    _archive_falso(api_falsa, 30)
    monkeypatch.setattr(archive_org, "HOSTS", archive_org.HOSTS + (api_falsa.base.split("//")[1],))
    cliente = ClienteHTTP(espera=0)
    assert len(archive_org.buscar(cliente, api_falsa.base + "/details/Comedy_Films", limite=12)) == 12
    [um] = archive_org.buscar(cliente, api_falsa.base + "/details/filme7")
    assert um.url.endswith("/download/filme7/filme7.mkv")
    assert archive_org.buscar(cliente, api_falsa.base + "/details/sem_video") == []


def test_melhor_arquivo():
    assert archive_org.melhor_arquivo([{"name": "a.mp4", "size": "10"}, {"name": "b.mp4", "size": "50"}])["name"] == "b.mp4"
    assert archive_org.melhor_arquivo([{"name": "capa.jpg"}]) is None
    assert not archive_org.reconhece("https://archive.org/about/")
    assert archive_org.reconhece("https://archive.org/search?query=filmes")
