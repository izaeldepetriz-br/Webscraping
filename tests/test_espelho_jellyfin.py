"""Espelhar links no Jellyfin com .strm: classificação, nomes, licença e legendas."""
import csv

from jellyfin_tools import CatalogoLocal, ConfigSite, ProvedorSiteHTML
from jellyfin_tools.espelho import aplicar_espelho, classificar, licenca_aberta, planejar_espelho
from videoscraper.archive_org import licenca_legivel
from videoscraper.cli import salvar
from videoscraper.extracao import LinkVideo
from videoscraper.rede import ClienteHTTP

BASE = "https://archive.org/download/item/"


def _link(titulo, arquivo="video.mp4", licenca="", ano=None):
    return LinkVideo(BASE + arquivo, "https://archive.org/details/item", "archive.org", titulo, licenca, ano)


def test_classificar_filme_serie_e_outro():
    assert classificar(_link("Anjos Da Noite 2003 (Underworld) (Dual Audio) PT-BR")) == "filme"
    assert classificar(_link("Minha Mae E Uma Peca DVD", ano=2013)) == "filme"          # ano dos metadados
    assert classificar(_link("Dark", "Dark.S01E02.mkv")) == "serie"                     # marca no arquivo
    assert classificar(_link("Initial D - Completo - Legendado")) == "outro"
    assert classificar(_link("Star Wars Episode 4 1977")) == "filme"                    # não é série


def test_planejar_e_criar_strm_com_nomes_do_jellyfin(tmp_path):
    links = [_link("Anjos Da Noite 2003 (Underworld) (Dual Audio) PT-BR", "anjos.mkv"),
             _link("A Viagem de Chihiro (R4BR DVDISO)", "chihiro.mp4", ano=2001),
             _link("Dark episódio", "Dark.S01E02.WEBRip.mkv"),
             _link("Initial D - Completo - Legendado"),
             _link("Matrix 1999 copia", "outra.mp4")]                                  # mesmo destino do 1º Matrix?
    links.insert(0, _link("Matrix (1999)", "matrix.mkv"))
    itens = planejar_espelho(links, tmp_path / "Filmes", tmp_path / "Series", CatalogoLocal.padrao())
    assert [(i.tipo, i.status) for i in itens] == [("filme", "criar"), ("filme", "criar"), ("filme", "criar"),
                                                   ("serie", "criar"), ("outro", "ignorado"),
                                                   ("filme", "ja_existe")]             # duas cópias do Matrix
    aplicar_espelho(itens)
    criados = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*.strm"))
    assert criados == ["Filmes/A Viagem de Chihiro (2001)/A Viagem de Chihiro (2001).strm",
                       "Filmes/Anjos Da Noite (2003)/Anjos Da Noite (2003).strm",
                       "Filmes/Matrix (1999)/Matrix (1999).strm",
                       "Series/Dark (2017)/Season 01/Dark S01E02.strm"]
    assert (tmp_path / "Filmes/Matrix (1999)/Matrix (1999).strm").read_text(encoding="utf-8") == BASE + "matrix.mkv\n"
    # de novo: nada é sobrescrito
    de_novo = planejar_espelho(links[:1], tmp_path / "Filmes", tmp_path / "Series")
    assert de_novo[0].status == "ja_existe"


def test_video_baixado_na_biblioteca_nao_ganha_strm(tmp_path):
    pasta = tmp_path / "Filmes" / "Matrix (1999)"
    pasta.mkdir(parents=True)
    (pasta / "Matrix (1999).mkv").write_bytes(b"v")
    [item] = planejar_espelho([_link("Matrix (1999)")], tmp_path / "Filmes", tmp_path / "Series")
    assert item.status == "tem_video"


def test_so_licenca_aberta(tmp_path):
    assert licenca_legivel("http://creativecommons.org/licenses/by-sa/4.0/") == "CC BY-SA 4.0"
    assert licenca_legivel("https://creativecommons.org/publicdomain/mark/1.0/") == "Domínio público"
    assert licenca_aberta("CC BY 4.0") and licenca_aberta("Domínio público") and not licenca_aberta("")
    links = [_link("Nosferatu 1922", licenca="Domínio público"), _link("Anjos Da Noite 2003")]
    itens = planejar_espelho(links, tmp_path / "F", tmp_path / "S", so_licenca_aberta=True)
    assert [i.status for i in itens] == ["criar", "sem_licenca"]


def test_legendas_e_completar_biblioteca_com_strm(tmp_path, site_legendas):
    """O .strm faz o papel do vídeo: a legenda ganha o mesmo nome e o Completar enxerga o .strm."""
    from jellyfin_tools.pos_processamento import ConfigPos, itens_da_biblioteca, pos_processar
    provedor = ProvedorSiteHTML(ConfigSite(site_legendas.base + "/busca?q={consulta}"), ClienteHTTP(espera=0))
    itens = aplicar_espelho(planejar_espelho([_link("Matrix (1999)")], tmp_path, tmp_path / "S"))
    [r] = pos_processar([itens[0].como_item_da_biblioteca()], ConfigPos(provedores=[provedor]))
    assert r.legenda.status == "baixada"
    assert (tmp_path / "Matrix (1999)" / "Matrix (1999).pt-BR.srt").is_file()
    assert [nome for _, nome in itens_da_biblioteca(tmp_path)] == ["Matrix (1999)"]


def test_salvar_lista_csv_com_licenca_e_ano(tmp_path):
    destino = tmp_path / "lista.csv"
    salvar([_link("Nosferatu", licenca="Domínio público", ano=1922)], str(destino))
    with open(destino, encoding="utf-8-sig", newline="") as f:
        [linha] = list(csv.DictReader(f))
    assert (linha["licenca"], linha["ano"]) == ("Domínio público", "1922")


# ------------------------------------------------------------------ o link serve para .strm? (outros sites)
def _site_de_videos(api):
    video = {"Content-Type": "video/mp4", "Accept-Ranges": "bytes"}
    api.rotas["/ok.mp4"] = lambda q: (206, b"x", video)
    api.rotas["/sem_avanco.mp4"] = lambda q: (200, b"x", {"Content-Type": "video/mp4"})
    api.rotas["/pagina"] = lambda q: (200, b"<html></html>", {"Content-Type": "text/html; charset=utf-8"})
    api.rotas["/privado.mp4"] = lambda q: (403, b"", {})
    api.rotas["/sumiu.mp4"] = lambda q: (404, b"", {})
    api.rotas["/bloqueado/filme.mp4"] = lambda q: (206, b"x", video)
    api.rotas["/robots.txt"] = lambda q: (200, b"User-agent: *\nDisallow: /bloqueado\n", {"Content-Type": "text/plain"})


def test_verificar_links_de_outros_sites(api_falsa):
    from jellyfin_tools.espelho import verificar_links
    _site_de_videos(api_falsa)
    b = api_falsa.base
    r = verificar_links([b + "/ok.mp4", b + "/sem_avanco.mp4", b + "/pagina", b + "/privado.mp4", b + "/sumiu.mp4",
                         b + "/bloqueado/filme.mp4", b + "/ok.mp4?Expires=1700000000&Signature=abc",
                         "http://127.0.0.1:9/fora.mp4"])
    resumo = {url.replace(b, ""): (v.ok, v.problema or v.aviso) for url, v in r.items()}
    assert resumo == {
        "/ok.mp4": (True, ""),
        "/sem_avanco.mp4": (True, "o servidor não deixa avançar o vídeo"),
        "/pagina": (False, "é uma página, não o arquivo do vídeo"),
        "/privado.mp4": (False, "exige login ou permissão (o Jellyfin não tem o seu acesso)"),
        "/sumiu.mp4": (False, "arquivo não encontrado (removido?)"),
        "/bloqueado/filme.mp4": (False, "o robots.txt do site não permite"),
        "/ok.mp4?Expires=1700000000&Signature=abc": (False, "link temporário (expira; o .strm pararia de funcionar)"),
        "http://127.0.0.1:9/fora.mp4": (False, "servidor fora do ar ou sem conexão")}
    assert r[b + "/ok.mp4"].tempo is not None
    pedido = next(p for p in api_falsa.pedidos if p["caminho"] == "/ok.mp4")
    assert pedido["headers"]["Range"] == "bytes=0-0"                     # pede só 1 byte, não o filme


def test_verificar_links_em_paralelo(api_falsa):
    import time
    from jellyfin_tools.espelho import verificar_links

    def devagar(q):
        time.sleep(0.3)
        return 206, b"x", {"Content-Type": "video/mp4", "Accept-Ranges": "bytes"}
    api_falsa.rotas["/lento.mp4"] = devagar
    urls = [f"{api_falsa.base}/lento.mp4?n={n}" for n in range(8)]
    inicio = time.perf_counter()
    r = verificar_links(urls, respeitar_robots=False)
    assert all(v.ok for v in r.values()) and time.perf_counter() - inicio < 8 * 0.3 / 2   # não um por vez


def test_link_que_nao_serve_nao_vira_strm(tmp_path):
    from jellyfin_tools.espelho import Verificacao
    links = [_link("Nosferatu (1922)", "n.mp4"), _link("Metropolis (1927)", "m.mp4")]
    verificacoes = {links[0].url: Verificacao(False, "é uma página, não o arquivo do vídeo"),
                    links[1].url: Verificacao(True, aviso="resposta lenta (4.2 s)")}
    itens = aplicar_espelho(planejar_espelho(links, tmp_path / "F", tmp_path / "S", verificacoes=verificacoes))
    assert [(i.status, i.detalhe) for i in itens] == [
        ("link_ruim", "é uma página, não o arquivo do vídeo"),
        ("criado", "não confirmado no catálogo: confira o nome; resposta lenta (4.2 s)")]


# ------------------------------------------------------------------ desfazer e conferir espelhos
def test_desfazer_espelho_apaga_o_que_criou(tmp_path):
    from jellyfin_tools import desfazer
    from jellyfin_tools.organizador import ultimo_log
    serie = tmp_path / "Series" / "Dark (2017)" / "Season 01"
    serie.mkdir(parents=True)
    (serie / "Dark S01E01.mkv").write_bytes(b"v")                       # já existia: não pode sumir
    links = [_link("Nosferatu (1922)", "n.mp4"), _link("Dark", "Dark.S01E02.mkv")]
    aplicar_espelho(planejar_espelho(links, tmp_path / "Filmes", tmp_path / "Series", CatalogoLocal.padrao()))
    (serie / "Dark S01E02.pt-BR.srt").write_text("legenda", encoding="utf-8")   # baixada depois
    (tmp_path / "Filmes" / "Nosferatu (1922)" / "poster.jpg").write_bytes(b"jpg")
    desfazer(ultimo_log(tmp_path / "Filmes"))
    desfazer(ultimo_log(tmp_path / "Series"))
    assert not (tmp_path / "Filmes" / "Nosferatu (1922)").exists()      # pasta criada pelo espelho: some
    assert sorted(p.name for p in serie.iterdir()) == ["Dark S01E01.mkv"]   # o resto da série fica


def test_conferir_e_remover_espelhos_quebrados(tmp_path, api_falsa):
    from jellyfin_tools import desfazer
    from jellyfin_tools.espelho import conferir_espelhos, remover_espelhos
    from jellyfin_tools.organizador import ultimo_log
    api_falsa.rotas["/ok.mp4"] = lambda q: (206, b"x", {"Content-Type": "video/mp4", "Accept-Ranges": "bytes"})
    api_falsa.rotas["/sumiu.mp4"] = lambda q: (404, b"", {})
    filmes = tmp_path / "Filmes"
    for nome, url in (("Bom (2000)", "/ok.mp4"), ("Quebrado (2001)", "/sumiu.mp4")):
        (filmes / nome).mkdir(parents=True)
        (filmes / nome / f"{nome}.strm").write_text(api_falsa.base + url + "\n", encoding="utf-8")
    resultado = conferir_espelhos(filmes, tmp_path / "Series", respeitar_robots=False)
    assert [(a.name, v.ok) for _, a, _, v in resultado] == [("Bom (2000).strm", True), ("Quebrado (2001).strm", False)]
    quebrados = [r for r in resultado if not r[3].ok]
    assert remover_espelhos(quebrados) == 1
    assert not (filmes / "Quebrado (2001)" / "Quebrado (2001).strm").exists()
    desfazer(ultimo_log(filmes))                                         # arrependeu: volta
    assert (filmes / "Quebrado (2001)" / "Quebrado (2001).strm").read_text(encoding="utf-8").strip().endswith("/sumiu.mp4")


# ------------------------------------------------------------------ o que o Jellyfin já tem
def _jellyfin_falso(api, exigir_usuario=False):
    filmes = [{"Name": "Nosferatu", "ProductionYear": 1922, "ProviderIds": {"Tmdb": "653"}},
              {"Name": "Anjos da Noite", "ProductionYear": 2003, "ProviderIds": {}}]
    series = [{"Id": "s1", "Name": "Dark", "ProviderIds": {"Tmdb": "70523"}}]
    episodios = [{"SeriesId": "s1", "SeriesName": "Dark", "ParentIndexNumber": 1, "IndexNumber": 2}]
    por_tipo = {"Movie": filmes, "Series": series, "Episode": episodios}

    def itens(q):
        if q.get("api_key"):
            return 401, {}
        return 200, {"Items": por_tipo[q["IncludeItemTypes"][0]]}
    if exigir_usuario:                                                   # Jellyfin antigo
        api.rotas["/Items"] = lambda q: (400, {})
        api.rotas["/Users"] = lambda q: (200, [{"Id": "u1", "Name": "admin"}])
        api.rotas["/Users/u1/Items"] = itens
    else:
        api.rotas["/Items"] = itens


def test_indice_do_jellyfin_e_espelho_sem_duplicar(tmp_path, api_falsa):
    from jellyfin_tools.servidor_jellyfin import indice_da_biblioteca
    _jellyfin_falso(api_falsa)
    indice = indice_da_biblioteca(api_falsa.base, "chave")
    assert indice.tem_filme(["Nosferatu"], 1922) and indice.tem_filme(["outro nome"], None, tmdb_id=653)
    assert indice.tem_episodio(["Dark"], 1, 2) and not indice.tem_episodio(["Dark"], 1, 3)
    pedido = next(p for p in api_falsa.pedidos if p["caminho"] == "/Items")
    assert pedido["headers"]["X-Emby-Token"] == "chave"
    links = [_link("Nosferatu (1922)", "n.mp4"), _link("Anjos Da Noite 2003 (Dual Audio)", "a.mkv"),
             _link("Dark", "Dark.S01E02.mkv"), _link("Dark", "Dark.S01E03.mkv"), _link("Metropolis (1927)", "m.mp4")]
    itens = planejar_espelho(links, tmp_path / "F", tmp_path / "S", CatalogoLocal.padrao(), indice_jellyfin=indice)
    assert [i.status for i in itens] == ["no_jellyfin", "no_jellyfin", "no_jellyfin", "criar", "criar"]


def test_indice_do_jellyfin_antigo_com_usuario(api_falsa):
    from jellyfin_tools.servidor_jellyfin import indice_da_biblioteca
    _jellyfin_falso(api_falsa, exigir_usuario=True)
    indice = indice_da_biblioteca(api_falsa.base, "chave")
    assert indice.total == 3 and indice.tem_filme(["Nosferatu"], 1922)


def test_indice_do_jellyfin_chave_errada(api_falsa):
    import pytest
    from jellyfin_tools.servidor_jellyfin import ErroJellyfin, indice_da_biblioteca
    api_falsa.rotas["/Items"] = lambda q: (401, {})
    with pytest.raises(ErroJellyfin, match="recusou"):
        indice_da_biblioteca(api_falsa.base, "errada")


# ------------------------------------------------------------------ conferência automática com aviso
def test_intervalo_em_horas_ou_dias():
    import pytest
    from jellyfin_tools.espelho import intervalo_em_segundos
    assert intervalo_em_segundos("12h") == 12 * 3600 and intervalo_em_segundos("7d") == 7 * 86400
    assert intervalo_em_segundos("7") == 7 * 86400 and intervalo_em_segundos(6, "horas") == 6 * 3600
    assert intervalo_em_segundos("30min") == 30 * 60 and intervalo_em_segundos(45, "minutos") == 45 * 60
    assert intervalo_em_segundos("1 minuto") == 5 * 60 and intervalo_em_segundos(2, "minutos") == 5 * 60  # mínimo
    with pytest.raises(ValueError):
        intervalo_em_segundos("toda semana")


def test_conferir_e_avisar_no_discord_e_remover(tmp_path, api_falsa):
    import json
    from jellyfin_tools.espelho import conferir_e_avisar
    from jellyfin_tools.notificacoes import Notificador
    api_falsa.rotas["/ok.mp4"] = lambda q: (206, b"x", {"Content-Type": "video/mp4", "Accept-Ranges": "bytes"})
    api_falsa.rotas["/sumiu.mp4"] = lambda q: (404, b"", {})
    api_falsa.rotas["/discord"] = lambda q: (204, b"")
    filmes = tmp_path / "Filmes"
    for nome, url in (("Bom (2000)", "/ok.mp4"), ("Quebrado (2001)", "/sumiu.mp4")):
        (filmes / nome).mkdir(parents=True)
        (filmes / nome / f"{nome}.strm").write_text(api_falsa.base + url + "\n", encoding="utf-8")
    avisos = Notificador(api_falsa.base + "/discord", "", "")
    todos, quebrados, removidos = conferir_e_avisar(filmes, notificador=avisos, remover=True, respeitar_robots=False)
    assert (len(todos), len(quebrados), removidos) == (2, 1, 1)
    [aviso] = [json.loads(p["corpo"])["content"] for p in api_falsa.pedidos if p["caminho"] == "/discord"]
    assert aviso.startswith("\U0001F517 **1 espelho(s) quebrado(s) no Jellyfin**")
    assert "• Quebrado (2001) — arquivo não encontrado (removido?)" in aviso and "Desfazer última" in aviso
    assert not (filmes / "Quebrado (2001)" / "Quebrado (2001).strm").exists()
    api_falsa.pedidos.clear()
    conferir_e_avisar(filmes, notificador=avisos, respeitar_robots=False)          # tudo ok: sem aviso
    assert not [p for p in api_falsa.pedidos if p["caminho"] == "/discord"]
