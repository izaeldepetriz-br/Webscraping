import pytest
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


def test_pagina_de_site_nao_vira_lista_de_canais(api_falsa, tmp_path):
    """Caso real: 'Importar do link' com https://github.io (uma página) virou 256 "canais" de HTML."""
    import pytest
    from jellyfin_tools.tv_ao_vivo import NaoEhLista, importar
    pagina = '<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8"/>\n<title>GitHub Pages</title>\n'
    api_falsa.rotas["/pagina"] = lambda q: (200, pagina.encode(), {"Content-Type": "text/html"})
    with pytest.raises(NaoEhLista, match="página de site"):
        importar(api_falsa.base + "/pagina")
    assert ler_m3u(pagina) == []                                       # nenhuma linha de HTML vira canal
    misturado = LISTA + "<html>lixo</html>\nhttps://ok.org/a.m3u8\n"
    assert [c.url for c in ler_m3u(misturado)][-1] == "https://ok.org/a.m3u8"
    (tmp_path / "vazia.m3u").write_text("#EXTM3U\n", encoding="utf-8")
    with pytest.raises(NaoEhLista, match="nenhum canal"):
        importar(str(tmp_path / "vazia.m3u"))


def test_parar_e_imediato_e_devolve_so_os_conferidos():
    import time
    from jellyfin_tools.paralelo import em_paralelo
    inicio = time.monotonic()
    feitos = em_paralelo(list(range(500)), lambda n: time.sleep(0.3) or n, trabalhadores=8,
                         parar=lambda: time.monotonic() - inicio > 0.5)
    assert time.monotonic() - inicio < 1.5                              # antes: 500 x 0,3 s / 8 = ~19 s
    assert 0 < len(feitos) < 500 and all(feitos[i] == i for i in feitos)


def test_servidor_que_nao_conecta_nao_e_tentado_de_novo():
    import time
    canais = [Canal(f"C{n}", f"http://127.0.0.1:9/canal{n}.m3u8") for n in range(60)]   # porta fechada
    inicio = time.monotonic()
    situacoes = conferir_canais(canais)
    assert len(situacoes) == 60 and not any(s.ok for _, s in situacoes)
    assert sum("não responde (outros canais dele já falharam)" in s.detalhe for _, s in situacoes) >= 40
    assert time.monotonic() - inicio < 10


def test_muitos_canais_no_mesmo_servidor_vao_rapido_sem_sobrecarregar(api_falsa):
    import threading
    import time
    ao_mesmo_tempo, maximo, trava = [0], [0], threading.Lock()

    def devagar(q):
        with trava:
            ao_mesmo_tempo[0] += 1
            maximo[0] = max(maximo[0], ao_mesmo_tempo[0])
        time.sleep(0.2)
        with trava:
            ao_mesmo_tempo[0] -= 1
        return 200, b"#EXTM3U\n", {"Content-Type": "application/x-mpegURL"}
    api_falsa.rotas["/lento.m3u8"] = devagar
    canais = [Canal(f"C{n}", f"{api_falsa.base}/lento.m3u8?n={n}") for n in range(60)]
    inicio = time.monotonic()
    situacoes = conferir_canais(canais)
    assert all(s.ok for _, s in situacoes)
    assert time.monotonic() - inicio < 60 * 0.2 / 2                     # bem mais rápido que um por vez
    assert maximo[0] <= 6                                               # no máximo 6 no mesmo servidor


def test_em_paralelo_prazo_nao_deixa_um_item_segurar_a_fila():
    import time
    from jellyfin_tools.paralelo import em_paralelo

    def consulta(n):
        time.sleep(30 if n % 10 == 0 else 0.01)                  # 1 em cada 10 "fica preso"
        return n
    inicio = time.monotonic()
    feitos = em_paralelo(list(range(50)), consulta, trabalhadores=4, prazo=0.5, ao_estourar=lambda n: f"estourou {n}")
    assert time.monotonic() - inicio < 5                          # antes: os presos seguravam tudo
    assert len(feitos) == 50 and feitos[10] == "estourou 10" and feitos[11] == 11


def test_em_paralelo_devolve_o_erro_e_aguenta_lista_enorme():
    import time
    from jellyfin_tools.paralelo import em_paralelo

    def falha(n):
        raise ValueError("deu ruim")
    with pytest.raises(ValueError, match="deu ruim"):
        em_paralelo([1, 2, 3], falha)
    avisos = []
    inicio = time.monotonic()
    feitos = em_paralelo(list(range(20000)), lambda n: n * 2, trabalhadores=32, ao_progresso=lambda f, t: avisos.append(f))
    assert len(feitos) == 20000 and feitos[19999] == 39998 and avisos[-1] == 20000
    assert len(avisos) < 2000                                      # o progresso não sai a cada item (a janela agradece)
    assert time.monotonic() - inicio < 20


def test_servidor_mudo_e_desistido_logo():
    """O servidor aceita a ligação e não responde nada: antes cada canal esperava a vez e o tempo todo."""
    import socket
    import time
    mudo = socket.socket()
    mudo.bind(("127.0.0.1", 0))
    mudo.listen(200)
    porta = mudo.getsockname()[1]
    try:
        canais = [Canal(f"C{n}", f"http://127.0.0.1:{porta}/c{n}.m3u8") for n in range(40)]
        inicio = time.monotonic()
        situacoes = conferir_canais(canais)
        assert time.monotonic() - inicio < 20                      # antes: 40 x 8 s / 6 = ~53 s
        assert not any(s.ok for _, s in situacoes)
        assert sum("não responde (outros canais dele já falharam)" in s.detalhe for _, s in situacoes) >= 25
    finally:
        mudo.close()


def test_servidor_que_nao_existe_sai_sem_consultar_canal_por_canal(monkeypatch, api_falsa):
    import socket
    import requests
    original = socket.getaddrinfo
    procurados = []

    def dns(nome, *a, **k):
        procurados.append(nome)
        if str(nome).endswith(".invalid"):
            raise socket.gaierror("não existe")
        return original(nome, *a, **k)
    monkeypatch.setattr(socket, "getaddrinfo", dns)
    monkeypatch.setattr(requests.utils, "getproxies", lambda: {})
    api_falsa.rotas["/ok.m3u8"] = lambda q: (200, b"#EXTM3U\n", {"Content-Type": "application/x-mpegURL"})
    canais = [Canal(f"Velho {n}", f"http://canal{n % 3}.invalid/{n}.m3u8") for n in range(30)]
    canais.insert(5, Canal("Bom", api_falsa.base + "/ok.m3u8"))
    situacoes = conferir_canais(canais)
    assert [c.nome for c, _ in situacoes] == [c.nome for c in canais]                # mesma ordem da lista
    assert dict((c.nome, s.ok) for c, s in situacoes)["Bom"] is True
    assert all("não existe mais" in s.detalhe for c, s in situacoes if c.nome != "Bom")
    assert sum(n.endswith(".invalid") for n in procurados) == 3                   # uma vez por servidor


def test_primeiros_bytes_nao_fica_preso_num_servidor_que_pinga():
    import time
    from jellyfin_tools.tv_ao_vivo import _primeiros_bytes

    class Pinga:                                                    # 1 byte a cada 0,3 s, para sempre
        def read1(self, n, decode_content=True):
            time.sleep(0.3)
            return b"#"
    resposta = type("R", (), {"raw": Pinga()})()
    inicio = time.monotonic()
    assert _primeiros_bytes(resposta, 2048, prazo=1).startswith(b"#")
    assert time.monotonic() - inicio < 2


def test_exportar_tabela(tmp_path):
    import csv
    import json
    from jellyfin_tools.tv_ao_vivo import exportar_tabela
    linhas = [{"canal": "TV Cultura", "grupo": "Abertos", "situacao": "no ar", "no_ar": True, "link": "https://a.org/1.m3u8"},
              {"canal": "Rádio", "grupo": "", "situacao": "", "no_ar": None, "link": "https://b.net/r.mp3"}]
    assert json.loads(exportar_tabela(linhas, tmp_path / "c.json").read_text(encoding="utf-8")) == linhas
    exportar_tabela(linhas, tmp_path / "c.csv")
    tabela = list(csv.reader((tmp_path / "c.csv").open(encoding="utf-8-sig"), delimiter=";"))
    assert tabela[0] == ["Canal", "Grupo", "Situação", "No ar", "Link"] and tabela[1][3] == "sim" and tabela[2][3] == ""
    texto = exportar_tabela(linhas, tmp_path / "c.txt").read_text(encoding="utf-8").splitlines()
    assert texto[1].split("\t") == ["TV Cultura", "Abertos", "no ar", "sim", "https://a.org/1.m3u8"]
    with pytest.raises(ValueError):
        exportar_tabela(linhas, tmp_path / "c.xls")
