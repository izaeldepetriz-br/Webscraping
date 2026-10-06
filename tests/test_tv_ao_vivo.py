import pytest
"""Canais ao vivo: lista .m3u, conferência dos links e cadastro no Jellyfin (servidor falso)."""
import json
from pathlib import Path

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
        config["ListingProviders"] = [g for g in config["ListingProviders"] if g["Path"] != corpo["Path"]] + [corpo]
        return 200, corpo

    api_falsa.rotas["/System/Configuration/livetv"] = lambda q: (200, config)
    api_falsa.rotas["/LiveTv/TunerHosts"] = tuner
    api_falsa.rotas["/LiveTv/ListingProviders"] = guia
    api_falsa.rotas["/ScheduledTasks"] = lambda q: (200, [{"Key": "RefreshGuide", "Id": "abc"}])
    api_falsa.rotas["/ScheduledTasks/Running/abc"] = lambda q: (204, b"")
    api_falsa.rotas["/guia.xml"] = lambda q: (200, b"<tv></tv>", {"Content-Type": "application/xml"})
    url_guia = api_falsa.base + "/guia.xml"
    canais = ler_m3u(LISTA)
    cliente = ClienteTV(api_falsa.base, "chave")
    feito = publicar(canais, tmp_path / "TV", "E:\\TV\\canais.m3u", url_guia, cliente,
                     antena="192.168.0.50")
    assert (tmp_path / "TV" / "canais.m3u").read_text(encoding="utf-8").count("#EXTINF") == 2
    assert any("sintonizador M3U -> E:\\TV\\canais.m3u" in f for f in feito)
    assert [(t["Type"], t["Url"]) for t in config["TunerHosts"]] == [("m3u", "E:\\TV\\canais.m3u"),
                                                                      ("hdhomerun", "192.168.0.50")]
    assert [g["Path"] for g in config["ListingProviders"]] == [url_guia,
                                                               "E:\\TV\\guia_categorias.xml"]   # o de categorias por último
    assert any(p["caminho"] == "/ScheduledTasks/Running/abc" for p in api_falsa.pedidos)
    assert all(p["headers"].get("X-Emby-Token") == "chave" for p in api_falsa.pedidos
               if p["caminho"] != "/guia.xml")
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
    import socket
    import time
    livre = socket.socket()
    livre.bind(("127.0.0.1", 0))
    porta = livre.getsockname()[1]
    livre.close()                                                       # porta que acabou de fechar: recusa na hora
    canais = [Canal(f"C{n}", f"http://127.0.0.1:{porta}/canal{n}.m3u8") for n in range(60)]
    inicio = time.monotonic()
    situacoes = conferir_canais(canais)
    assert len(situacoes) == 60 and not any(s.ok for _, s in situacoes)
    # o que importa: a maioria nem é tentada (antes: os 60 esperavam a vez, um por um)
    assert sum("não responde (outros canais dele já falharam)" in s.detalhe for _, s in situacoes) >= 40
    assert time.monotonic() - inicio < 20                               # folga para máquina carregada (prazo: 15 s)


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
        assert time.monotonic() - inicio < 25                      # 1 ou 2 rodadas de 10 s; antes: 40 x 8 s / 6 = ~53 s
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
    dados = json.loads(exportar_tabela(linhas, tmp_path / "c.json").read_text(encoding="utf-8"))
    assert [{k: d[k] for k in linhas[0]} for d in dados] == linhas and dados[0]["numero"] == ""
    exportar_tabela(linhas, tmp_path / "c.csv")
    tabela = list(csv.reader((tmp_path / "c.csv").open(encoding="utf-8-sig"), delimiter=";"))
    assert tabela[0] == ["Nº", "Canal", "Grupo", "Idioma", "Programação", "Situação", "No ar", "Últimas", "Link"]
    assert tabela[1][6] == "sim" and tabela[2][6] == ""
    texto = exportar_tabela(linhas, tmp_path / "c.txt").read_text(encoding="utf-8").splitlines()
    assert texto[1].split("\t") == ["", "TV Cultura", "Abertos", "", "", "no ar", "sim", "", "https://a.org/1.m3u8"]
    with pytest.raises(ValueError):
        exportar_tabela(linhas, tmp_path / "c.xls")


def test_playlist_que_o_servidor_manda_como_pagina_ou_com_bom_esta_no_ar(api_falsa):
    """Caso real: o canal toca no navegador, mas o servidor diz que a playlist é "text/html" ou
    "text/plain" (ou começa com a marca BOM). O que vale é o conteúdo (#EXTM3U)."""
    api_falsa.rotas["/a/index.m3u8"] = lambda q: (200, b"#EXTM3U\n#EXT-X-VERSION:3\n", {"Content-Type": "text/html"})
    api_falsa.rotas["/b/index.m3u8"] = lambda q: (200, b"\xef\xbb\xbf\r\n#EXTM3U\n", {"Content-Type": "text/plain"})
    api_falsa.rotas["/c/live"] = lambda q: (200, b"#EXTM3U\n", {"Content-Type": "text/html; charset=utf-8"})
    api_falsa.rotas["/d/live"] = lambda q: (200, b"<html>login</html>", {"Content-Type": "text/html"})
    b = api_falsa.base
    situacoes = {c.nome: s for c, s in conferir_canais([Canal("A", b + "/a/index.m3u8"), Canal("B", b + "/b/index.m3u8"),
                                                        Canal("C", b + "/c/live"), Canal("D", b + "/d/live")])}
    assert [n for n, s in situacoes.items() if s.ok] == ["A", "B", "C"]
    assert "é uma página" in situacoes["D"].detalhe
    assert "Chrome" in api_falsa.pedidos[-1]["headers"].get("User-Agent", "")      # parece um navegador


def test_poucos_canais_sao_todos_tentados_mesmo_com_o_servidor_falhando():
    """Conferindo poucos (ex.: os selecionados), não desiste do servidor: cada canal é tentado."""
    canais = [Canal(f"C{n}", f"http://127.0.0.1:9/canal{n}.m3u8") for n in range(8)]   # porta fechada
    situacoes = conferir_canais(canais)
    assert not any("outros canais dele já falharam" in s.detalhe for _, s in situacoes)


def _jellyfin_falso(api_falsa, limpa_sozinho: bool):
    """Jellyfin falso: sintonizadores, tarefa do guia e a lista de canais. limpa_sozinho=True: ao atualizar o
    guia ele relê o .m3u e tira os que saíram; False: guarda os antigos do sintonizador (o caso que o usuário viu)."""
    hosts, proximo, canais_jf = [], [0], {}

    def tuner(q):
        pedido = api_falsa.pedidos[-1]
        if pedido["metodo"] == "DELETE":
            hosts[:] = [h for h in hosts if h["Id"] != q["id"][0]]
            for chave in [k for k in canais_jf if k[0] == q["id"][0]]:
                del canais_jf[chave]
            return 204, b""
        corpo = json.loads(pedido["corpo"])
        if not corpo.get("Id"):
            proximo[0] += 1
            corpo["Id"] = f"t{proximo[0]}"
        hosts[:] = [h for h in hosts if h["Id"] != corpo["Id"]] + [corpo]
        return 200, corpo

    def atualizar_guia(q):
        for h in hosts:
            if h.get("Type") != "m3u" or not Path(h["Url"]).is_file():
                continue                                                # antena, lista da internet...
            lidos = {c.nome for c in ler_m3u(Path(h["Url"]).read_text(encoding="utf-8"))}
            if limpa_sozinho:
                for chave in [k for k in canais_jf if k[0] == h["Id"] and k[1] not in lidos]:
                    del canais_jf[chave]
            canais_jf.update({(h["Id"], n): True for n in lidos})
        return 204, b""

    api_falsa.rotas["/System/Configuration/livetv"] = lambda q: (200, {"TunerHosts": hosts, "ListingProviders": []})
    api_falsa.rotas["/LiveTv/TunerHosts"] = tuner
    api_falsa.rotas["/ScheduledTasks"] = lambda q: (200, [{"Key": "RefreshGuide", "Id": "abc"}])
    api_falsa.rotas["/ScheduledTasks/Running/abc"] = atualizar_guia
    api_falsa.rotas["/ScheduledTasks/abc"] = lambda q: (200, {"State": "Idle"})
    api_falsa.rotas["/LiveTv/Channels"] = lambda q: (200, {"Items": [{"Name": n} for _, n in canais_jf],
                                                           "TotalRecordCount": len(canais_jf)})
    return hosts, canais_jf


def test_removidos_saem_e_os_favoritos_ficam_quando_o_jellyfin_limpa_sozinho(tmp_path, api_falsa):
    hosts, canais_jf = _jellyfin_falso(api_falsa, limpa_sozinho=True)
    cliente = ClienteTV(api_falsa.base, "chave")
    canais = ler_m3u(LISTA)
    publicar(canais, tmp_path, cliente=cliente)
    assert [h["Id"] for h in hosts] == ["t1"] and len(canais_jf) == 2
    feito = publicar(canais[:1], tmp_path, cliente=cliente)                 # tirou um canal
    assert [h["Id"] for h in hosts] == ["t1"]                              # o mesmo sintonizador: favoritos ficam
    assert any("removidos saíram (os favoritos foram mantidos)" in f for f in feito)
    assert any("agora TV ao vivo tem 1 canal(is)" in f for f in feito)


def test_removidos_saem_mesmo_quando_o_jellyfin_guarda_os_antigos(tmp_path, api_falsa):
    """Caso real: removia os canais, clicava em "Salvar e enviar" e o Jellyfin continuava com os antigos."""
    hosts, canais_jf = _jellyfin_falso(api_falsa, limpa_sozinho=False)
    cliente = ClienteTV(api_falsa.base, "chave")
    canais = ler_m3u(LISTA)
    publicar(canais, tmp_path, cliente=cliente)
    feito = publicar(canais[:1], tmp_path, cliente=cliente)
    assert (tmp_path / "canais.m3u").read_text(encoding="utf-8").count("#EXTINF") == 1
    assert [h["Id"] for h in hosts] == ["t2"]                              # recriado: o Jellyfin esquece o antigo
    assert [n for _, n in canais_jf] == ["TV Cultura"]
    assert any("1 canal(is) saíram" in f for f in feito) and any("recriado" in f for f in feito)
    feito = publicar(canais[:1], tmp_path, cliente=cliente)                 # nada mudou: só atualiza
    assert [h["Id"] for h in hosts] == ["t2"] and not any("recriado" in f for f in feito)
    feito = publicar([], tmp_path, cliente=cliente)                         # "Remover todos" e enviar
    assert "#EXTINF" not in (tmp_path / "canais.m3u").read_text(encoding="utf-8")
    assert hosts == [] and any("sintonizador M3U retirado" in f for f in feito)


def test_tirar_uma_copia_repetida_confere_pela_conta(tmp_path, api_falsa):
    """O nome continua na lista (era uma cópia): confere pelo total de canais."""
    hosts, canais_jf = _jellyfin_falso(api_falsa, limpa_sozinho=False)
    cliente = ClienteTV(api_falsa.base, "chave")
    canais = [Canal("TV Cultura", "http://a.org/1.m3u8"), Canal("TV Cultura", "http://b.org/1.m3u8"),
              Canal("Rádio", "http://a.org/r.mp3")]
    publicar(canais, tmp_path, cliente=cliente)
    feito = publicar([canais[0], canais[2]], tmp_path, cliente=cliente)
    assert any("recriado" in f for f in feito) or any("mantidos" in f for f in feito)


def test_outros_sintonizadores_sao_os_que_nao_sao_desta_lista(tmp_path, api_falsa):
    hosts, _ = _jellyfin_falso(api_falsa, limpa_sozinho=True)
    cliente = ClienteTV(api_falsa.base, "chave")
    publicar(ler_m3u(LISTA), tmp_path, cliente=cliente, antena="192.168.0.50")
    hosts.append({"Id": "manual", "Type": "m3u", "FriendlyName": "iptv", "Url": "https://iptv-org.github.io/iptv/index.m3u"})
    outros = cliente.outros_sintonizadores(str(tmp_path / "canais.m3u"))
    assert [h["Id"] for h in outros] == ["manual"]                  # a nossa lista e a nossa antena não entram
    from jellyfin_tools.tv_ao_vivo import descrever_sintonizador
    assert descrever_sintonizador(outros[0]) == 'M3U "iptv": https://iptv-org.github.io/iptv/index.m3u'


def test_esperar_o_guia_nao_conta_antes_da_tarefa_terminar(api_falsa):
    """Caso real: logo depois do pedido a tarefa ainda está "parada" (nem começou) e o programa achava que já
    tinha terminado: contava os canais ANTIGOS (11.129)."""
    import time
    estado = {"pedido": None, "fim": "2026-10-05T10:00:00Z"}

    def tarefa(q):
        if estado["pedido"] is None:
            return 200, {"State": "Idle", "LastExecutionResult": {"EndTimeUtc": estado["fim"], "Status": "Completed"}}
        passou = time.monotonic() - estado["pedido"]
        if passou < 1.5:                                                 # ainda na fila: "parada", fim antigo
            return 200, {"State": "Idle", "LastExecutionResult": {"EndTimeUtc": estado["fim"], "Status": "Completed"}}
        if passou < 3:
            return 200, {"State": "Running", "LastExecutionResult": {"EndTimeUtc": estado["fim"]}}
        return 200, {"State": "Idle", "LastExecutionResult": {"EndTimeUtc": "2026-10-05T10:05:00Z",
                                                              "Status": "Failed", "ErrorMessage": "XMLTV inválido"}}

    def rodar(q):
        estado["pedido"] = time.monotonic()
        return 204, b""
    api_falsa.rotas["/ScheduledTasks"] = lambda q: (200, [{"Key": "RefreshGuide", "Id": "abc"}])
    api_falsa.rotas["/ScheduledTasks/abc"] = tarefa
    api_falsa.rotas["/ScheduledTasks/Running/abc"] = rodar
    cliente = ClienteTV(api_falsa.base, "chave")
    inicio = time.monotonic()
    assert cliente.esperar_tarefa(cliente.atualizar_guia(), limite=20, intervalo=0.2)
    assert time.monotonic() - inicio >= 3                                # esperou ela rodar e terminar de verdade
    assert cliente.erro_da_tarefa == "XMLTV inválido"


def test_listas_antigas_do_programa_saem_ao_enviar(tmp_path, api_falsa):
    """Outro "videoscraper" apontando para OUTRO arquivo (pasta antiga, lista velha de 11 mil canais)."""
    hosts, canais_jf = _jellyfin_falso(api_falsa, limpa_sozinho=True)
    for n in (1, 2):
        hosts.append({"Id": f"velho{n}", "Type": "m3u", "FriendlyName": "videoscraper",
                      "Url": str(tmp_path / f"antiga{n}.m3u")})
    cliente = ClienteTV(api_falsa.base, "chave")
    feito = publicar(ler_m3u(LISTA), tmp_path / "nova", cliente=cliente)
    assert [h["Url"] for h in hosts] == [str(tmp_path / "nova" / "canais.m3u")]   # só um, no arquivo de agora
    assert any("1 lista(s) antiga(s) do programa retirada(s)" in f for f in feito)   # o 1º foi reaproveitado


def test_limpar_e_reenviar_e_canais_a_mais(tmp_path, api_falsa):
    from jellyfin_tools.tv_ao_vivo import canais_a_mais, limpar_e_reenviar
    hosts, canais_jf = _jellyfin_falso(api_falsa, limpa_sozinho=False)
    cliente = ClienteTV(api_falsa.base, "chave")
    canais = ler_m3u(LISTA)
    publicar(canais, tmp_path, cliente=cliente)
    canais_jf.update({("t1", f"Velho {n}"): True for n in range(500)})   # o Jellyfin guardou canais velhos
    assert canais_a_mais(cliente.quantos_canais(), canais) and not canais_a_mais(2, canais)
    assert not canais_a_mais(9999, canais, antena="192.168.0.5")          # com antena não dá para saber
    feito = limpar_e_reenviar(cliente, str(tmp_path / "canais.m3u"))
    assert "agora TV ao vivo tem 2 canal(is)" in feito[-1] and len(hosts) == 1


def test_lista_gerada_nao_repete_tvg_id_nem_numero():
    """O mesmo tvg-id em dois canais (HD e SD) pode dar erro na atualização do guia; com erro, o Jellyfin não
    apaga os canais velhos."""
    canais = [Canal("Cultura HD", "http://a/1", id_guia="Cultura.br", numero="2"),
              Canal("Cultura SD", "http://a/2", id_guia="cultura.br", numero="2"), Canal("Band", "http://a/3", numero="4")]
    lidos = ler_m3u(gerar_m3u(canais))
    assert [c.id_guia for c in lidos] == ["Cultura.br", "", ""] and [c.numero for c in lidos] == ["2", "", "4"]
    assert [c.url for c in lidos] == ["http://a/1", "http://a/2", "http://a/3"]       # nenhum canal some


def test_texto_do_diagnostico():
    from jellyfin_tools.tv_ao_vivo import texto_diagnostico
    d = {"info": {"Services": [{"Name": "Emby", "Status": "Ok"}, {"Name": "IPTV Plugin", "Status": "Ok"}]},
         "config": {"TunerHosts": [{"Type": "m3u", "FriendlyName": "videoscraper", "Url": "C:/tv/canais.m3u"}],
                    "ListingProviders": [{"Type": "xmltv", "Path": "https://guia/epg.xml"}]},
         "canais": {"TotalRecordCount": 11129, "Items": [{"Name": "TV Cultura", "ServiceName": "Emby"},
                                                         {"Name": "Canal X", "ServiceName": "IPTV Plugin"}]},
         "tarefas": [{"Key": "RefreshGuide", "LastExecutionResult": {"Status": "Completed", "EndTimeUtc": "2026-10-05"}}]}
    texto = texto_diagnostico(d, {"TV Cultura"})
    assert "Serviços de TV ao vivo: 2" in texto and "IPTV Plugin: Ok" in texto
    assert 'M3U "videoscraper": C:/tv/canais.m3u' in texto and "xmltv: https://guia/epg.xml" in texto
    assert "Canais no Jellyfin: 11129 (amostra de 2: 1 são da sua lista)" in texto
    assert "Canal X  [serviço: IPTV Plugin]" in texto and 'Última "Atualizar o guia": Completed' in texto


DIAGNOSTICO_REAL = {   # o diagnóstico que o usuário mandou (11.129 canais que não saem nem com "Limpar e reenviar")
    "info": {"Services": [{"Name": "Next Pvr", "Status": "Ok"}, {"Name": "TVHclient LiveTvService", "Status": "Ok"},
                          {"Name": "Emby", "Status": "Ok"}]},
    "config": {"TunerHosts": [{"Type": "m3u", "FriendlyName": "videoscraper",
                               "Url": r"C:\Users\x\.videoscraper\tv\canais.m3u"}], "ListingProviders": []},
    "canais": {"TotalRecordCount": 11129, "Items": [{"Name": "&TV HD (1080p)"}]},
    "plugins": [{"Name": "NextPVR", "Version": "9.0.0.0", "Id": "p-nextpvr", "Status": "Active"},
                {"Name": "TVHeadend", "Version": "12.0.0.0", "Id": "p-tvh", "Status": "Active"},
                {"Name": "TMDb", "Version": "10.10.0.0", "Id": "p-tmdb", "Status": "Active"}]}


def test_plugins_de_tv_do_diagnostico_real():
    from jellyfin_tools.tv_ao_vivo import plugins_de_tv, texto_diagnostico
    plugins, sem_plugin = plugins_de_tv(DIAGNOSTICO_REAL)
    assert [p["Id"] for p in plugins] == ["p-nextpvr", "p-tvh"] and sem_plugin == []   # "Emby" é o do Jellyfin
    assert "Plugins de TV ao vivo além do Jellyfin: NextPVR 9.0.0.0, TVHeadend 12.0.0.0" in texto_diagnostico(
        DIAGNOSTICO_REAL)
    desligados = {**DIAGNOSTICO_REAL, "plugins": [{**p, "Status": "Disabled"} for p in DIAGNOSTICO_REAL["plugins"]]}
    assert plugins_de_tv(desligados) == ([], [])                       # já desativados: nada a fazer
    sem_lista = {**DIAGNOSTICO_REAL, "plugins": {"erro": "HTTP 403"}}
    assert plugins_de_tv(sem_lista) == ([], ["Next Pvr", "TVHclient LiveTvService"])
    assert plugins_de_tv({"info": {"Services": [{"Name": "Emby"}]}}) == ([], [])


def test_desativar_plugins_reinicia_e_os_canais_velhos_saem(tmp_path, api_falsa):
    """Com um plugin de TV dando erro, o Jellyfin pula a limpeza; desativado (e reiniciado), os velhos saem."""
    from jellyfin_tools.tv_ao_vivo import desativar_plugins_e_limpar, plugins_de_tv
    hosts, canais_jf = _jellyfin_falso(api_falsa, limpa_sozinho=True)
    plugins = [dict(p) for p in DIAGNOSTICO_REAL["plugins"]]
    estado = {"pendentes": set(), "fora_do_ar": 0}
    guia_original = api_falsa.rotas["/ScheduledTasks/Running/abc"]

    def atualizar_guia(q):
        if any(p["Status"] == "Active" and p["Id"] != "p-tmdb" for p in plugins):
            return 204, b""                                             # erro no plugin: não limpa nada
        canais_jf.clear()
        return guia_original(q)

    def desativar(id_):
        def rota(q):
            estado["pendentes"].add(id_)
            return 204, b""
        return rota

    def reiniciar(q):
        estado["fora_do_ar"] = 2
        for p in plugins:
            if p["Id"] in estado["pendentes"]:
                p["Status"] = "Disabled"
        return 204, b""

    def info_publica(q):
        if estado["fora_do_ar"]:
            estado["fora_do_ar"] -= 1
            return 503, b"reiniciando"
        return 200, {"ServerName": "jf"}

    api_falsa.rotas["/ScheduledTasks/Running/abc"] = atualizar_guia
    api_falsa.rotas["/Plugins"] = lambda q: (200, plugins)
    for p in plugins:
        api_falsa.rotas[f"/Plugins/{p['Id']}/{p['Version']}/Disable"] = desativar(p["Id"])
    api_falsa.rotas["/System/Restart"] = reiniciar
    api_falsa.rotas["/System/Info/Public"] = info_publica

    cliente = ClienteTV(api_falsa.base, "chave")
    publicar(ler_m3u(LISTA), tmp_path, cliente=cliente)
    canais_jf.update({("velho", f"&TV {n}"): True for n in range(500)})
    a_desativar, _ = plugins_de_tv({"info": DIAGNOSTICO_REAL["info"], "plugins": cliente.plugins()})
    feito, total = desativar_plugins_e_limpar(cliente, a_desativar)
    assert total == 2 and "tinha 500 canal(is), agora tem 2" in feito[-1]
    assert [p["Status"] for p in plugins] == ["Disabled", "Disabled", "Active"]   # o TMDb não é de TV: fica
    assert "Plugin desativado: NextPVR 9.0.0.0" in feito[0] and "Jellyfin reiniciado." in feito


def test_esperar_voltar_desiste_se_o_jellyfin_nao_volta(api_falsa):
    relogio = [0.0]
    api_falsa.rotas["/System/Info/Public"] = lambda q: (503, b"fora")
    cliente = ClienteTV(api_falsa.base, "chave")
    assert not cliente.esperar_voltar(60, dormir=lambda s: relogio.__setitem__(0, relogio[0] + s),
                                      agora=lambda: relogio[0])
    assert relogio[0] >= 60


def test_resumo_tv_tudo_certo_ou_atencao():
    from jellyfin_tools.tv_ao_vivo import resumo_tv, texto_diagnostico
    certo = {"info": {"Services": [{"Name": "Emby", "Status": "Ok"}]}, "plugins": [],
             "canais": {"TotalRecordCount": 144, "Items": [{"Name": "ADB TV (1080p)"}]}}
    assert resumo_tv(certo, 144) == (True, "144 canais (os da sua lista)")
    assert texto_diagnostico(certo, {"ADB TV (1080p)"}, 144).startswith("✓ Tudo certo: 144 canais")
    assert resumo_tv(DIAGNOSTICO_REAL, 144)[0] is False and "NextPVR" in resumo_tv(DIAGNOSTICO_REAL, 144)[1]
    a_mais = {**certo, "canais": {"TotalRecordCount": 11129}}
    assert resumo_tv(a_mais, 144) == (False, "11129 canais no Jellyfin, a lista tem 144")
    assert texto_diagnostico(a_mais, set(), 144).startswith("⚠ Atenção: 11129 canais")
    assert resumo_tv({**certo, "canais": {"erro": "HTTP 500"}}, 144)[0] is None
    assert resumo_tv({**certo, "canais": {"TotalRecordCount": 150}}, 144)[0] is True      # folga pequena


def test_estado_leve_para_o_painel(api_falsa):
    api_falsa.rotas["/LiveTv/Info"] = lambda q: (200, {"Services": [{"Name": "Emby"}]})
    api_falsa.rotas["/LiveTv/Channels"] = lambda q: (200, {"Items": [], "TotalRecordCount": 144})
    api_falsa.rotas["/Plugins"] = lambda q: (200, [])
    d = ClienteTV(api_falsa.base, "chave").estado()
    assert d["canais"]["TotalRecordCount"] == 144
    assert [p["query"].get("Limit") for p in api_falsa.pedidos if p["caminho"] == "/LiveTv/Channels"] == [["0"]]


def test_categoria_pelo_grupo_e_guia_de_categorias():
    """O Jellyfin só põe canal em Filmes/Esportes/Notícias/Infantil/Séries pela programação do guia: sem guia
    de verdade, o programa gera um com a categoria tirada do Grupo."""
    import xml.etree.ElementTree as ET
    from datetime import datetime, timezone
    from jellyfin_tools.tv_ao_vivo import caminho_irmao, categoria_do_grupo, gerar_guia_categorias
    assert [categoria_do_grupo(g) for g in ("Sports", "Filmes;Ação", "Notícias", "Desenhos Animados", "Séries",
                                            "Religious", "")] == ["sports", "movie", "news", "kids", "series", None, None]
    canais = [Canal("ESPN & Co", "http://a/1", "Sports", id_guia="ESPN.br"), Canal("ESPN 2", "http://a/2", "Sports",
              id_guia="espn.br"), Canal("Rede Fé", "http://a/3", "Religious"), Canal("Série X", "http://a/4", "Séries")]
    xml = ET.fromstring(gerar_guia_categorias(canais, agora=datetime(2026, 10, 6, 15, tzinfo=timezone.utc), dias=2))
    ids = [c.get("id") for c in xml.findall("channel")]
    assert ids == ["ESPN.br", "maestro.2", "maestro.3", "maestro.4"]          # tvg-id repetido: liga pelo nome
    espn = [p for p in xml.findall("programme") if p.get("channel") == "ESPN.br"]
    assert len(espn) == 3 and espn[0].get("start") == "20261005000000 +0000"   # de ontem a +2 dias
    assert [c.text for c in espn[0].findall("category")] == ["sports", "Sports", "Português"]   # .br
    fe = next(p for p in xml.findall("programme") if p.get("channel") == "maestro.3")
    assert [c.text for c in fe.findall("category")] == ["Religious"]           # sem categoria do Jellyfin: só o gênero
    serie = next(p for p in xml.findall("programme") if p.get("channel") == "maestro.4")
    assert serie.find("episode-num") is not None                               # o Jellyfin marca "Séries" assim
    assert caminho_irmao(r"E:\TV\canais.m3u", "guia_categorias.xml") == r"E:\TV\guia_categorias.xml"


def test_publicar_sem_guia_cadastra_o_de_categorias_e_tira_quando_ha_guia_de_verdade(tmp_path, api_falsa):
    hosts, canais_jf = _jellyfin_falso(api_falsa, limpa_sozinho=True)
    guias, apagados, proximo = [], [], [0]

    def provedores(q):
        pedido = api_falsa.pedidos[-1]
        if pedido["metodo"] == "DELETE":
            apagados.append(q["id"][0])
            guias[:] = [g for g in guias if g["Id"] != q["id"][0]]
            return 204, b""
        proximo[0] += 1
        corpo = {**json.loads(pedido["corpo"]), "Id": f"g{proximo[0]}"}
        guias.append(corpo)
        return 200, corpo
    api_falsa.rotas["/LiveTv/ListingProviders"] = provedores
    api_falsa.rotas["/System/Configuration/livetv"] = lambda q: (200, {"TunerHosts": hosts, "ListingProviders": guias})
    cliente = ClienteTV(api_falsa.base, "chave")
    canais = [Canal("ESPN", "http://a/1", "Sports"), Canal("Globo", "http://a/2", "Abertos")]
    feito = publicar(canais, tmp_path, caminho_no_servidor=r"E:\TV\canais.m3u", cliente=cliente)
    assert (tmp_path / "guia_categorias.xml").is_file()
    assert [g["Path"] for g in guias] == [r"E:\TV\guia_categorias.xml"]       # como o SERVIDOR enxerga
    assert any("1 de 2 canal(is) com" in f for f in feito)
    for nome in ("epg.xml", "epg2.xml.gz"):
        api_falsa.rotas[f"/{nome}"] = lambda q: (200, b"<tv></tv>", {"Content-Type": "application/xml"})
    um, dois = api_falsa.base + "/epg.xml", api_falsa.base + "/epg2.xml.gz"
    feito = publicar(canais, tmp_path, caminho_no_servidor=r"E:\TV\canais.m3u", guia=f"{um}; {dois}", cliente=cliente)
    # vários guias de verdade, e o de categorias sempre POR ÚLTIMO (o Jellyfin usa o 1º que tem o canal)
    assert [g["Path"] for g in guias] == [um, dois, r"E:\TV\guia_categorias.xml"]
    assert apagados == ["g1"] and any("por último" in f for f in feito)
    # o coletor do Docker antes da 1ª coleta (404): não é cadastrado (um guia com erro trava a limpeza)
    feito = publicar(canais, tmp_path, caminho_no_servidor=r"E:\TV\canais.m3u",
                     guia=api_falsa.base + "/ainda_nao.xml", cliente=cliente)
    assert any("NÃO cadastrado agora (HTTP 404)" in f for f in feito)
    assert api_falsa.base + "/ainda_nao.xml" not in [g["Path"] for g in guias]
    publicar([], tmp_path, caminho_no_servidor=r"E:\TV\canais.m3u", cliente=cliente)          # lista vazia: sai
    assert [g["Path"] for g in guias] == [um, dois]


def test_separar_guias():
    from jellyfin_tools.tv_ao_vivo import separar_guias
    assert separar_guias("https://a/epg.xml; https://b/x.xml.gz\nE:\\TV\\g.xml") == [
        "https://a/epg.xml", "https://b/x.xml.gz", "E:\\TV\\g.xml"]
    assert separar_guias("https://a/epg.xml https://b/2.xml") == ["https://a/epg.xml", "https://b/2.xml"]
    assert separar_guias("") == [] and separar_guias("https://a/epg.xml;https://a/epg.xml") == ["https://a/epg.xml"]


def test_idioma_do_canal_e_numerar_por_idioma():
    from jellyfin_tools.tv_ao_vivo import idioma_do_canal, nome_do_idioma, numerar_por_idioma
    assert [nome_do_idioma(t) for t in ("por", "pt", "Portuguese", "Português", "spa", "eng", "Klingon", "")] == [
        "Português", "Português", "Português", "Português", "Español", "English", "Klingon", ""]
    canais = [Canal("A&E Latin America Brazil (720p)", "http://170.83.16.50/AeE/index.m3u8", "Entertainment"),
              Canal("ADB TV (1080p)", "https://live-tv.waytv.pt/adbtv/playlist.m3u8", "Religious"),
              Canal("AMC Latin America (720p)", "http://1.2.3.4/amc.m3u8", "Movies"),
              Canal("CNN", "http://1.2.3.4/cnn.m3u8", "News", id_guia="CNN.us"),
              Canal("Canal Sur", "http://1.2.3.4/sur.m3u8", "General", idioma="spa"),
              Canal("Misterioso", "http://1.2.3.4/x.m3u8", "General")]
    assert [idioma_do_canal(c) for c in canais] == ["Português", "Português", "Español", "English", "Español", ""]
    ordem = numerar_por_idioma(canais)
    assert [(c.nome.split(" (")[0], c.numero) for c in ordem] == [
        ("A&E Latin America Brazil", "1"), ("ADB TV", "2"),               # empate 2 x 2: Português primeiro
        ("Canal Sur", "101"), ("AMC Latin America", "102"),               # dentro do idioma: por grupo
        ("CNN", "201"), ("Misterioso", "301")]                             # sem idioma: por último
    lidos = ler_m3u('#EXTINF:-1 tvg-language="Portuguese;English" group-title="News",X\nhttp://a/b\n')
    assert lidos[0].idioma == "Português" and 'tvg-language="Português"' in gerar_m3u(lidos)


def test_texto_do_scan_conferido():
    from jellyfin_tools.servidor_jellyfin import texto_do_scan_conferido
    base = {"antes": {"filmes": 5, "series": 2, "episodios": 30}, "depois": {"filmes": 5, "series": 2, "episodios": 30}}
    assert "nada novo" in texto_do_scan_conferido({**base, "terminou": True, "status": "Completed", "erro": "",
                                                   "segundos": 40})
    assert "terminou com ERRO (Failed): disco" in texto_do_scan_conferido({**base, "terminou": True, "status": "Failed",
                                                                          "erro": "disco", "segundos": 40})
    assert "ainda está escaneando (30 min" in texto_do_scan_conferido({**base, "terminou": False, "status": "",
                                                                      "erro": "", "segundos": 1800})
