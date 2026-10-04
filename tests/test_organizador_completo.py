"""Script organizar_jellyfin.py de ponta a ponta, com TMDB, Jellyfin, Discord e Telegram FALSOS."""
import json
import xml.etree.ElementTree as ET

import pytest

import organizar_jellyfin as script
from jellyfin_tools import CatalogoLocal
from jellyfin_tools.metadados import ClienteTMDB, escolher_backdrop, escolher_poster, gerar_nfo
from jellyfin_tools.notificacoes import Notificador
from jellyfin_tools.servidor_jellyfin import ErroJellyfin, atualizar_biblioteca

MB = 1024 * 1024
CREED = "Creed.II.2018.1080p.BluRay.6CH.x264.DUAL-WWW.BLUDV.TV-TioKennedy.mkv"
VELHOS = "Velhos.Bandidos.2026.1080p.WEB-DL.NACIONAL.5.1.mkv"
IMG_POSTER, IMG_FUNDO = b"\xff\xd8poster-pt", b"\xff\xd8backdrop-hd"


def detalhes_tmdb(tmdb_id, titulo, ano):
    return {"id": tmdb_id, "title": titulo, "original_title": titulo, "release_date": f"{ano}-11-21",
            "overview": f"Sinopse em português de {titulo}.", "runtime": 130, "tagline": "",
            "genres": [{"name": "Drama"}, {"name": "Ação"}], "poster_path": "/padrao.jpg",
            "backdrop_path": "/fundo-padrao.jpg", "external_ids": {"imdb_id": "tt0000001"},
            "images": {"posters": [{"file_path": "/poster_en.jpg", "iso_639_1": "en", "vote_average": 9},
                                   {"file_path": "/poster_pt.jpg", "iso_639_1": "pt", "vote_average": 5}],
                       "backdrops": [{"file_path": "/fundo_texto.jpg", "iso_639_1": "en", "width": 3840},
                                     {"file_path": "/fundo_hd.jpg", "iso_639_1": None, "width": 3840,
                                      "vote_average": 6},
                                     {"file_path": "/fundo_baixo.jpg", "iso_639_1": None, "width": 1280}]}}


@pytest.fixture
def servicos(api_falsa, monkeypatch, tmp_path):
    """Liga o script aos serviços falsos e a pastas temporárias."""
    ids = {"Creed II": 480530, "Velhos Bandidos": 999}
    api_falsa.rotas["/3/search/movie"] = lambda q: (200, {"results": (
        [{"id": ids[q["query"][0]]}] if q["query"][0] in ids else [])})
    api_falsa.rotas["/3/movie/480530"] = lambda q: (200, detalhes_tmdb(480530, "Creed II", 2018))
    api_falsa.rotas["/3/movie/999"] = lambda q: (200, detalhes_tmdb(999, "Velhos Bandidos", 2026))
    api_falsa.rotas["/img/poster_pt.jpg"] = lambda q: (200, IMG_POSTER)
    api_falsa.rotas["/img/fundo_hd.jpg"] = lambda q: (200, IMG_FUNDO)
    api_falsa.rotas["/Library/Refresh"] = lambda q: (204, b"")
    api_falsa.rotas["/discord"] = lambda q: (204, b"")
    api_falsa.rotas["/botTOKEN/sendMessage"] = lambda q: (200, {"ok": True})

    base = api_falsa.base
    monkeypatch.setattr(script, "ClienteTMDB",
                        lambda chave: ClienteTMDB(chave, base_url=base + "/3", base_imagens=base + "/img"))
    monkeypatch.setattr(script, "montar_catalogo", CatalogoLocal.padrao)
    monkeypatch.setattr(script, "Notificador",
                        lambda d, t, c: Notificador(d, t, c, telegram_base=base))
    variaveis = {"PASTA_ENTRADA": tmp_path / "Downloads", "PASTA_FILMES": tmp_path / "Filmes",
                 "TMDB_API_KEY": "chave-tmdb", "USAR_SITE_DEMO_LEGENDAS": "1",
                 "JELLYFIN_URL": base, "JELLYFIN_API_KEY": "chave-jellyfin",
                 "DISCORD_WEBHOOK_URL": base + "/discord", "TELEGRAM_BOT_TOKEN": "TOKEN",
                 "TELEGRAM_CHAT_ID": "42", "ARQUIVO_LOG": tmp_path / "logs" / "jellyfin_organizer.log"}
    for nome, valor in variaveis.items():
        monkeypatch.setenv(nome, str(valor))
    (tmp_path / "Downloads").mkdir()
    return api_falsa


def _video(caminho, tamanho=101 * MB):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, "wb") as f:
        f.truncate(tamanho)


def _criar_exemplos(tmp_path):
    torrent = tmp_path / "Downloads" / "Creed.II.2018-BLUDV"
    _video(torrent / CREED)
    for nome in ("BLUDV.TV.url", "Leia.txt", "Creed.II-backdrop.jpg", "Creed.II-poster.jpg"):
        (torrent / nome).write_bytes(b"local")
    (torrent / "Creed.II.FORCED.srt").write_text("1\n00:00:01,000 --> 00:00:02,000\nForçada\n", encoding="utf-8")
    _video(tmp_path / "Downloads" / VELHOS)


def _pedidos(api, caminho):
    return [p for p in api.pedidos if p["caminho"] == caminho]


def test_fluxo_completo(servicos, tmp_path):
    _criar_exemplos(tmp_path)
    assert script.main(["--aplicar"]) == 0
    creed, velhos = tmp_path / "Filmes" / "Creed II (2018)", tmp_path / "Filmes" / "Velhos Bandidos (2026)"

    # Fase 1 + melhoria 3: pasta do Creed com as imagens DO TORRENT (não sobrescritas) e o .nfo
    assert sorted(p.name for p in creed.iterdir()) == [
        "Creed II (2018).mkv", "Creed II (2018).nfo", "Creed II (2018).pt-BR.forced.srt", "backdrop.jpg", "poster.jpg"]
    assert (creed / "poster.jpg").read_bytes() == b"local"
    nfo = ET.parse(creed / "Creed II (2018).nfo").getroot()
    assert nfo.tag == "movie" and nfo.findtext("title") == "Creed II" and nfo.findtext("year") == "2018"
    assert nfo.findtext("plot") == "Sinopse em português de Creed II." and nfo.findtext("runtime") == "130"
    assert [g.text for g in nfo.findall("genre")] == ["Drama", "Ação"]

    # Melhoria 2: Velhos Bandidos não tinha imagens -> pôster pt-BR e backdrop HD do TMDB
    assert (velhos / "poster.jpg").read_bytes() == IMG_POSTER          # o em "pt", não o "en" mais votado
    assert (velhos / "backdrop.jpg").read_bytes() == IMG_FUNDO         # sem texto e maior resolução
    assert (velhos / "Velhos Bandidos (2026).pt-BR.srt").exists()       # legenda faltante baixada
    assert not (tmp_path / "Downloads" / "Creed.II.2018-BLUDV").exists()  # lixo apagado, pasta sumiu

    # Melhoria 1: UM scan no fim do lote, com a chave no cabeçalho
    [scan] = _pedidos(servicos, "/Library/Refresh")
    assert scan["metodo"] == "POST" and scan["headers"]["X-Emby-Token"] == "chave-jellyfin"
    assert 'MediaBrowser Token="chave-jellyfin"' in scan["headers"]["Authorization"]

    # Melhoria 4: um aviso por filme no Discord e no Telegram + log em arquivo
    discord = [json.loads(p["corpo"])["content"] for p in _pedidos(servicos, "/discord")]
    assert discord == ["\U0001F37F **Novo filme adicionado ao Jellyfin:** Creed II (2018)",
                       "\U0001F37F **Novo filme adicionado ao Jellyfin:** Velhos Bandidos (2026)"]
    telegram = [json.loads(p["corpo"]) for p in _pedidos(servicos, "/botTOKEN/sendMessage")]
    assert telegram[0]["chat_id"] == "42" and telegram[0]["parse_mode"] == "HTML"
    assert telegram[0]["text"] == "\U0001F37F <b>Novo filme adicionado ao Jellyfin:</b> Creed II (2018)"
    log = (tmp_path / "logs" / "jellyfin_organizer.log").read_text(encoding="utf-8")
    for trecho in ("| INFO     | [movido] " + CREED, "apagado: Leia.txt", "Jellyfin: escaneamento",
                   "Processado: Velhos Bandidos (2026)", "=== Fim: 2 movido(s), 0 com erro, 2 processado(s)"):
        assert trecho in log


def test_erro_em_um_filme_nao_para_os_outros(servicos, tmp_path):
    _criar_exemplos(tmp_path)
    servicos.rotas["/3/movie/480530"] = lambda q: (500, {"erro": "TMDB caiu"})   # Creed falha no TMDB
    assert script.main(["--aplicar"]) == 0
    assert not (tmp_path / "Filmes" / "Creed II (2018)" / "Creed II (2018).nfo").exists()
    assert (tmp_path / "Filmes" / "Velhos Bandidos (2026)" / "Velhos Bandidos (2026).nfo").exists()
    log = (tmp_path / "logs" / "jellyfin_organizer.log").read_text(encoding="utf-8")
    assert "| ERROR    | Metadados de Creed II (2018) falharam: TMDB respondeu HTTP 500" in log
    assert len(_pedidos(servicos, "/discord")) == 2                     # os dois foram organizados


def test_simulacao_nao_mexe_nem_chama_servicos(servicos, tmp_path):
    _criar_exemplos(tmp_path)
    assert script.main([]) == 0
    assert not (tmp_path / "Filmes").exists()
    assert not [p for p in servicos.pedidos if p["caminho"] in ("/Library/Refresh", "/discord")]
    assert "seria apagado: Leia.txt" in (tmp_path / "logs" / "jellyfin_organizer.log").read_text(encoding="utf-8")


def test_jellyfin_fora_do_ar_e_pasta_inexistente(servicos, tmp_path, monkeypatch):
    _video(tmp_path / "Downloads" / VELHOS)
    servicos.rotas["/Library/Refresh"] = lambda q: (401, {"erro": "nao autorizado"})
    assert script.main(["--aplicar"]) == 0                               # o filme foi organizado mesmo assim
    log = (tmp_path / "logs" / "jellyfin_organizer.log").read_text(encoding="utf-8")
    assert "Scan do Jellyfin não disparado: o Jellyfin recusou a chave de API" in log
    monkeypatch.setenv("PASTA_ENTRADA", str(tmp_path / "nao-existe"))
    assert script.main(["--aplicar"]) == 1
    assert "CRITICAL | PASTA_ENTRADA não existe" in (tmp_path / "logs" / "jellyfin_organizer.log").read_text(
        encoding="utf-8")


def test_completar_biblioteca_ja_organizada(servicos, tmp_path):
    pasta = tmp_path / "Filmes" / "Velhos Bandidos (2026)"
    _video(pasta / "Velhos Bandidos (2026).mkv", 10)
    assert script.main(["--completar-biblioteca"]) == 0
    assert sorted(p.name for p in pasta.iterdir()) == [
        "Velhos Bandidos (2026).mkv", "Velhos Bandidos (2026).nfo", "Velhos Bandidos (2026).pt-BR.srt",
        "backdrop.jpg", "poster.jpg"]
    assert not _pedidos(servicos, "/discord")                           # completar não notifica
    assert len(_pedidos(servicos, "/Library/Refresh")) == 1


# ------------------------------------------------------------------------ peças isoladas
def test_nfo_e_escolha_de_imagens():
    d = detalhes_tmdb(1, "Filme & Cia <teste>", 2020)
    raiz = ET.fromstring(gerar_nfo(d))
    assert raiz.findtext("title") == "Filme & Cia <teste>"                # caracteres especiais escapados
    assert [u.get("type") for u in raiz.findall("uniqueid")] == ["tmdb", "imdb"]
    assert escolher_poster(d) == "/poster_pt.jpg" and escolher_backdrop(d) == "/fundo_hd.jpg"
    assert escolher_poster({"poster_path": "/p.jpg", "images": {"posters": []}}) == "/p.jpg"


def test_notificador_resumo_e_limite(api_falsa):
    tentativas = []

    def discord(q):
        tentativas.append(1)
        return (429, {"retry_after": 0.1}) if len(tentativas) == 1 else (204, b"")

    api_falsa.rotas["/d"] = discord
    n = Notificador(api_falsa.base + "/d")
    n.novo_filme("Matrix (1999)")
    assert len(tentativas) == 2                                         # esperou e tentou de novo
    n.resumo([f"Filme {i}" for i in range(15)], ja_avisados=10)
    corpo = json.loads(_pedidos(api_falsa, "/d")[-1]["corpo"])["content"]
    assert corpo.startswith("\U0001F37F **5 filmes adicionados ao Jellyfin:**") and "Filme 14" in corpo
    assert not Notificador().ativo


def test_atualizar_biblioteca_erros(api_falsa):
    with pytest.raises(ErroJellyfin, match="precisam estar preenchidos"):
        atualizar_biblioteca("", "")
    with pytest.raises(ErroJellyfin, match="não existe"):
        atualizar_biblioteca(api_falsa.base + "/caminho-errado", "k")
    with pytest.raises(ErroJellyfin, match="não consegui falar"):
        atualizar_biblioteca("http://127.0.0.1:1", "k", timeout=2)


def test_varios_filmes_ao_mesmo_tempo_mas_uma_legenda_por_vez(tmp_path):
    """Pós-processamento paralelo: resultados na ordem dos filmes e legendas nunca simultâneas."""
    import threading
    import time
    from jellyfin_tools.legendas import ResultadoLegenda
    from jellyfin_tools.pos_processamento import ConfigPos, itens_da_biblioteca, pos_processar

    for i in range(8):
        pasta = tmp_path / f"Filme {i} ({2000 + i})"
        pasta.mkdir()
        (pasta / f"{pasta.name}.mkv").write_bytes(b"v")

    agora, maximo, trava = [0], [0], threading.Lock()

    class ProvedorLento:                      # conta quantas buscas de legenda acontecem juntas
        nome = "lento"

        def buscar(self, titulo, ano, idioma, **kw):
            with trava:
                agora[0] += 1
                maximo[0] = max(maximo[0], agora[0])
            time.sleep(0.05)
            with trava:
                agora[0] -= 1
            return []

    vistos = []
    t = time.perf_counter()
    resultados = pos_processar(itens_da_biblioteca(tmp_path), ConfigPos(provedores=[ProvedorLento()], trabalhadores=4),
                               ao_item=lambda i, r: vistos.append(i))
    assert [r.nome for r in resultados] == [f"Filme {i} ({2000 + i})" for i in range(8)]
    assert vistos == list(range(8))                                     # andamento na ordem
    assert maximo[0] == 1                                               # uma legenda por vez
    assert all(isinstance(r.legenda, ResultadoLegenda) for r in resultados)
    assert time.perf_counter() - t < 5
