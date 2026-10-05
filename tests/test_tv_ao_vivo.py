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
    assert tabela[0] == ["Nº", "Canal", "Grupo", "Situação", "No ar", "Últimas", "Link"]
    assert tabela[1][4] == "sim" and tabela[2][4] == ""
    texto = exportar_tabela(linhas, tmp_path / "c.txt").read_text(encoding="utf-8").splitlines()
    assert texto[1].split("\t") == ["", "TV Cultura", "Abertos", "no ar", "sim", "", "https://a.org/1.m3u8"]
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
