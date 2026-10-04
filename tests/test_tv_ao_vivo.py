"""Canais ao vivo: lista .m3u, conferência dos links e cadastro no Jellyfin (servidor falso)."""
import json

from jellyfin_tools.tv_ao_vivo import (Canal, ClienteTV, carregar_canais, conferir_canais, gerar_m3u, ler_m3u,
                                       mensagem_fora_do_ar, publicar, salvar_canais)

LISTA = """#EXTM3U
#EXTINF:-1 tvg-id="tvcultura.br" tvg-logo="https://x/cultura.png" group-title="Abertos",TV Cultura
https://exemplo.org/cultura/index.m3u8
#EXTINF:-1,Rádio Pública
http://exemplo.org/radio.mp3
"""


def test_le_e_gera_m3u(tmp_path):
    canais = ler_m3u(LISTA)
    assert [(c.nome, c.grupo, c.id_guia, c.url) for c in canais] == [
        ("TV Cultura", "Abertos", "tvcultura.br", "https://exemplo.org/cultura/index.m3u8"),
        ("Rádio Pública", "", "", "http://exemplo.org/radio.mp3")]
    texto = gerar_m3u(canais, guia="https://exemplo.org/guia.xml")
    assert texto.startswith('#EXTM3U url-tvg="https://exemplo.org/guia.xml"')
    assert ler_m3u(texto) == canais                                     # ida e volta sem perder nada
    salvar_canais(tmp_path / "canais.json", canais)
    assert carregar_canais(tmp_path / "canais.json") == canais


def test_conferir_canais(api_falsa):
    api_falsa.rotas["/ok.m3u8"] = lambda q: (200, b"#EXTM3U\n#EXT-X-VERSION:3\n", {"Content-Type": "application/x-mpegURL"})
    api_falsa.rotas["/vazia.m3u8"] = lambda q: (200, b"<html>erro</html>", {"Content-Type": "text/html"})
    api_falsa.rotas["/radio.mp3"] = lambda q: (200, b"ID3" + b"x" * 100, {"Content-Type": "audio/mpeg"})
    api_falsa.rotas["/pagina"] = lambda q: (200, b"<html></html>", {"Content-Type": "text/html"})
    api_falsa.rotas["/login.ts"] = lambda q: (403, b"", {})
    b = api_falsa.base
    canais = [Canal("A", b + "/ok.m3u8"), Canal("B", b + "/vazia.m3u8"), Canal("C", b + "/radio.mp3"),
              Canal("D", b + "/pagina"), Canal("E", b + "/login.ts"), Canal("F", b + "/sumiu.ts"),
              Canal("G", b + "/ok.m3u8?token=abc")]
    situacoes = {c.nome: s for c, s in conferir_canais(canais)}
    assert [n for n, s in situacoes.items() if s.ok] == ["A", "C", "G"]
    assert "não é uma transmissão" in situacoes["B"].detalhe and "é uma página" in situacoes["D"].detalhe
    assert "login" in situacoes["E"].detalhe and "HTTP 404" in situacoes["F"].detalhe
    assert "temporário" in situacoes["G"].detalhe
    discord, telegram = mensagem_fora_do_ar([(c, s) for c, s in conferir_canais(canais[:2]) if not s.ok])
    assert "1 canal(is) ao vivo fora do ar" in discord and "• B" in discord and "<b>" in telegram


def test_publicar_cadastra_sintonizador_guia_e_antena_sem_duplicar(tmp_path, api_falsa):
    config = {"TunerHosts": [], "ListingProviders": []}

    def tuner(q):
        corpo = json.loads(api_falsa.pedidos[-1]["corpo"])
        config["TunerHosts"] = [t for t in config["TunerHosts"] if t["Url"] != corpo["Url"]] + [{**corpo, "Id": "t1"}]
        return 200, {**corpo, "Id": "t1"}

    def guia(q):
        corpo = json.loads(api_falsa.pedidos[-1]["corpo"])
        config["ListingProviders"] = [corpo]
        return 200, corpo

    api_falsa.rotas["/System/Configuration/livetv"] = lambda q: (200, config)
    api_falsa.rotas["/LiveTv/TunerHosts"] = tuner
    api_falsa.rotas["/LiveTv/ListingProviders"] = guia
    api_falsa.rotas["/ScheduledTasks"] = lambda q: (200, [{"Key": "RefreshGuide", "Id": "abc"}])
    api_falsa.rotas["/ScheduledTasks/Running/abc"] = lambda q: (204, b"")
    canais = ler_m3u(LISTA)
    cliente = ClienteTV(api_falsa.base, "chave")
    feito = publicar(canais, tmp_path / "TV", "E:\\TV\\canais.m3u", "https://exemplo.org/guia.xml", cliente,
                     antena="192.168.0.50")
    assert (tmp_path / "TV" / "canais.m3u").read_text(encoding="utf-8").count("#EXTINF") == 2
    assert any("sintonizador M3U -> E:\\TV\\canais.m3u" in f for f in feito)
    assert [(t["Type"], t["Url"]) for t in config["TunerHosts"]] == [("m3u", "E:\\TV\\canais.m3u"),
                                                                      ("hdhomerun", "192.168.0.50")]
    assert config["ListingProviders"][0]["Path"] == "https://exemplo.org/guia.xml"
    assert any(p["caminho"] == "/ScheduledTasks/Running/abc" for p in api_falsa.pedidos)
    assert all(p["headers"].get("X-Emby-Token") == "chave" for p in api_falsa.pedidos)
    publicar(canais, tmp_path / "TV", "E:\\TV\\canais.m3u", "", cliente)          # de novo: atualiza, não duplica
    assert len(config["TunerHosts"]) == 2


def test_script_confere_canais_e_avisa(tmp_path, monkeypatch, api_falsa):
    import organizar_jellyfin as script
    api_falsa.rotas["/discord"] = lambda q: (204, b"")
    salvar_canais(tmp_path / "canais.json", [Canal("Canal Sumido", api_falsa.base + "/sumiu.m3u8")])
    for nome, valor in {"PASTA_FILMES": tmp_path / "nao_existe", "PASTA_SERIES": "",
                        "ARQUIVO_CANAIS": tmp_path / "canais.json", "DISCORD_WEBHOOK_URL": api_falsa.base + "/discord",
                        "ARQUIVO_LOG": tmp_path / "log" / "j.log"}.items():
        monkeypatch.setenv(nome, str(valor))
    assert script.main(["--conferir-espelhos"]) == 0
    avisos = [json.loads(p["corpo"])["content"] for p in api_falsa.pedidos if p["caminho"] == "/discord"]
    assert len(avisos) == 1 and "Canal Sumido" in avisos[0]
