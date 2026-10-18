"""Interface moderna (CustomTkinter): a View sozinha e o app ligado ao motor.
Precisa de customtkinter e de uma tela (no Linux sem monitor: xvfb-run python -m pytest)."""
import logging
import os
import time
from pathlib import Path

import pytest

pytest.importorskip("tkinter")
ctk = pytest.importorskip("customtkinter")
if os.name != "nt" and not os.environ.get("DISPLAY"):
    pytest.skip("sem tela (DISPLAY) para abrir janelas", allow_module_level=True)

from videoscraper import app_moderna  # noqa: E402
from videoscraper.gui_moderna import CampoNumerico, JanelaModerna, tamanho_inicial  # noqa: E402
from videoscraper.servico import MENSAGEM_ROBOTS  # noqa: E402


# ------------------------------------------------------------------ só a View
def test_view_sozinha_tem_placeholders_e_api():
    j = JanelaModerna()
    try:
        for nome in ("ao_buscar", "ao_baixar_selecionados", "ao_baixar_todos", "ao_fazer_login", "ao_parar",
                     "ao_abrir_link", "ao_copiar_link", "ao_salvar_lista", "ao_abrir_pasta"):
            assert getattr(j, nome)() is None                 # placeholder: não faz nada, não quebra
        j.bt_buscar.invoke()                                  # clique de verdade no CTA

        j.adicionar_video("0", 1, "", "Aula", "link", "https://x/a.mp4")
        j.adicionar_video("1", 2, "", "Aula 2", "link", "https://x/b.mp4")
        assert j.lb_contador.cget("text") == "2"
        j.atualizar_situacao("0", "baixado", "ok")
        assert j.tabela.item("0", "values")[1] == "✓  baixado"

        j.escrever_log("tudo certo\nErro: falhou\n")
        assert j.log.tag_ranges("erro") and "falhou" in j.log.get(*j.log.tag_ranges("erro")[:2])
        assert "tudo certo" not in j.log.get(*j.log.tag_ranges("erro")[:2])   # só a linha do erro

        j.definir_ocupado(True)
        assert j.bt_buscar.cget("state") == "disabled" and j.bt_parar.cget("state") == "normal"
        j.definir_ocupado(False)
        assert j.bt_parar.cget("state") == "disabled"

        j.var_pausar.set(True)
        j._ajustar_checks()
        o = j.obter_opcoes()
        assert o.navegador and o.visivel and o.pausar and o.espera == 5.0 and o.max_paginas == 30
    finally:
        j.destroy()


def test_campo_numerico_respeita_limites():
    j = JanelaModerna()
    try:
        c = CampoNumerico(j, 1.5, 0.5, 10, 0.5, decimal=True)
        c._somar(1)
        assert c.get() == 2.0
        c.var.set("99")
        assert c.get() == 10                    # passou do máximo: trava no limite
        c.var.set("abc")
        assert c.get() == 0.5                   # texto inválido: volta ao mínimo
        n = CampoNumerico(j, 0, 0, 5, 1)
        n._somar(-1)
        assert n.get() == 0 and n.var.get() == "0"
    finally:
        j.destroy()


# ------------------------------------------------------------------ app completo (motor ligado)
@pytest.fixture
def app(monkeypatch, tmp_path):
    from videoscraper import config
    monkeypatch.setattr(config, "ARQUIVO", tmp_path / "config" / "config.json")   # não mexe no seu
    monkeypatch.setattr(app_moderna, "PERFIL_PADRAO", str(tmp_path / "perfil"))
    a = app_moderna.AppModerna()
    a.caixas = []
    a.mostrar_mensagem = lambda t, m, tipo="info": a.caixas.append((tipo, t, m))   # responde OK sozinho
    a.perguntar = lambda t, m: True
    a.escolher = lambda t, m, opcoes, **k: opcoes[0]        # escolhe o botão principal sozinho
    a._pedir_o_que_completar = lambda pasta, padrao, series: dict(padrao)   # "Completar": a escolha padrão
    a.escolher_da_lista = lambda *args, **k: None           # lista de opções: "Cancelar"
    a._pedir_pasta = lambda titulo, inicial="": ""          # janela de pastas: "Cancelar"
    a.ao_previas = lambda: None                             # janela das prévias: "Fechar"
    a.campo_espera.set(0.5)
    a.var_pasta.set(str(tmp_path / "videos"))
    yield a
    a.trabalhando = False
    try:
        a.fechar()
    except Exception:
        pass


def esperar(app, limite=90):
    """Espera a tarefa acabar. Se outra começar logo em seguida (ex.: "procurar filmes" -> confirmar -> "dublar"),
    espera essa também: antes, ela começava durante as últimas atualizações da tela e o teste acusava
    "não terminou a tempo" sem ter esperado nada (falhava só às vezes, conforme a velocidade da máquina)."""
    fim = time.time() + limite
    while True:
        app.update()
        while app.trabalhando and time.time() < fim:
            app.update()
            time.sleep(0.05)
        for _ in range(5):
            app.update()
            time.sleep(0.12)
        if not app.trabalhando or time.time() >= fim:
            break
    assert not app.trabalhando, "a tarefa não terminou a tempo"


def titulos(app):
    return [app.tabela.item(i, "values")[2] for i in app.tabela.get_children()]


def test_buscar_selecionar_e_baixar(app, servidor):
    app.redirecionar_saida()        # o pytest troca o sys.stdout entre as fases do teste
    app.definir_url(servidor.base + "/lista")
    app.var_seletor.set("a.video-link")
    app.bt_buscar.invoke()
    esperar(app)
    assert titulos(app) == ["Filme: Ação/1?", "Quebrado"]
    assert app.var_status.get() == "Pronto. 2 vídeo(s) na lista."

    app.tabela.selection_set("0")
    app.bt_baixar_sel.invoke()
    esperar(app)
    assert app.tabela.item("0", "values")[1].endswith("baixado")
    assert os.listdir(app.var_pasta.get()) == ["Filme Ação 1.mp4"]
    assert app.caixas[-1][:2] == ("sucesso", "Downloads concluídos")
    assert "Filme" in app.log.get("1.0", "end")

    # memória: numa busca nova, o baixado aparece como "já baixado" e "Baixar" pergunta antes
    assert app.memoria_downloads.baixado(app.links[0])["arquivo"].endswith("Filme Ação 1.mp4")
    app.bt_buscar.invoke()
    esperar(app)
    assert "já baixado (" in app.tabela.item("0", "values")[1] and app.tabela.item("1", "values")[1] == ""
    perguntas = []
    app.escolher = lambda t, m, opcoes, **k: (perguntas.append(t), None)[1]   # Cancelar
    app.tabela.selection_set("0")
    app.bt_baixar_sel.invoke()
    assert perguntas == ["Já baixados"] and not app.trabalhando



def test_baixar_so_os_selecionados_e_baixar_todos_com_selecao_pergunta(app, servidor):
    """Pedido: "mesmo selecionando, está baixando todos". Selecionados com clique de verdade: só eles são
    baixados; e o "Baixar todos" com alguns selecionados pergunta antes (só eles ou todos)."""
    app.redirecionar_saida()
    app.definir_url(servidor.base + "/")
    app.bt_buscar.invoke()
    esperar(app)
    for iid in ("0", "4"):                                             # clique, como a pessoa faz
        x, y, _, _ = app.tabela.bbox(iid, "titulo")
        app.tabela.event_generate("<Button-1>", x=x + 5, y=y + 5)
        app.update()
    assert app.tabela.selection() == ("0", "4")
    perguntas = []
    app.escolher = lambda t, m, opcoes, **k: (perguntas.append((t, m, opcoes)), opcoes[0])[1]
    app.bt_baixar_todos.invoke()
    esperar(app)
    assert perguntas[0][0] == "Baixar todos?" and perguntas[0][2] == ("Só os 2 selecionados", "Todos os 7")
    assert sorted(os.listdir(app.var_pasta.get())) == ["a.mp4", "og.mp4"]
    situacoes = [app.tabela.item(i, "values")[1] for i in app.tabela.get_children()]
    assert [n for n, s in enumerate(situacoes) if s] == [0, 4]                  # só as 2 linhas mudaram
    assert "Baixar selecionados: 2 de 7 (#1, #5)" in app.log.get("1.0", "end")


def test_baixar_todos_com_falha_e_robots(app, servidor):
    app.definir_url(servidor.base + "/lista")
    app.var_seletor.set("a.video-link")
    app.bt_baixar_todos.invoke()                         # sem buscar antes: busca e baixa
    esperar(app)
    assert app.tabela.item("1", "values")[1].endswith("erro")
    assert app.caixas[-1][0] == "erro"

    app.var_seletor.set("")
    app.definir_url(servidor.base + "/proibido/videos")
    perguntas = []
    app.escolher = lambda t, m, opcoes, **k: (perguntas.append((t, m)), None)[1]   # "Não, respeitar"
    app.bt_buscar.invoke()
    esperar(app)
    assert perguntas[0][0] == "robots.txt do site" and "127.0.0.1" in perguntas[0][1]
    assert ("aviso", "Acesso não permitido", MENSAGEM_ROBOTS) in app.caixas
    app.bt_buscar.invoke()                               # disse "não": nesta sessão não pergunta de novo
    esperar(app)
    assert len(perguntas) == 1 and not app.links


def test_robots_ignorado_so_no_site_que_a_pessoa_confirma(app, servidor):
    from videoscraper.rede import site_de
    app.definir_url(servidor.base + "/proibido/videos")
    perguntas = []
    app.escolher = lambda t, m, opcoes, **k: (perguntas.append(t), opcoes[0])[1]   # "Sim, o site é meu"
    app.bt_buscar.invoke()
    esperar(app)
    esperar(app)                                         # busca de novo sozinha, agora sem o robots.txt
    assert perguntas == ["robots.txt do site"]
    assert app.sites_sem_robots == {site_de(servidor.base)}
    assert [lk.url for lk in app.links] == [servidor.base + "/m/meu-video.mp4"]
    app.bt_buscar.invoke()                               # o site já foi liberado: não pergunta mais
    esperar(app)
    assert perguntas == ["robots.txt do site"] and len(app.links) == 1



def test_opcao_geral_ignorar_robots_confirma_a_cada_vez(app, servidor):
    app.definir_url(servidor.base + "/proibido/videos")
    app.var_ignorar_robots.set(True)
    perguntas, resposta = [], [None]
    app.escolher = lambda t, m, opcoes, **k: (perguntas.append((t, m)), resposta[0](opcoes) if resposta[0] else None)[1]
    app.bt_buscar.invoke()                                             # Cancelar: nem começa
    assert [t for t, _ in perguntas] == ["Ignorar o robots.txt?"] and not app.trabalhando
    assert "127.0.0.1" in perguntas[0][1]
    resposta[0] = lambda opcoes: opcoes[2]                             # "Respeitar o robots.txt"
    app.bt_buscar.invoke()
    esperar(app)
    assert len(perguntas) == 2 and not app.links                       # sem a 2ª pergunta (do fim)
    assert ("aviso", "Acesso não permitido", MENSAGEM_ROBOTS) in app.caixas
    resposta[0] = lambda opcoes: opcoes[0]                             # "Ignorar nesta vez"
    app.bt_buscar.invoke()
    esperar(app)
    assert len(perguntas) == 3 and [lk.url for lk in app.links] == [servidor.base + "/m/meu-video.mp4"]
    assert app.sites_sem_robots == set()                               # vale só para esta vez
    app.bt_baixar_todos.invoke()                                       # o download pergunta de novo (1 vez)
    esperar(app)
    assert [t for t, _ in perguntas].count("Ignorar o robots.txt?") == 4
    assert app.tabela.item("0", "values")[1].endswith("baixado")
    resposta[0] = lambda opcoes: opcoes[1]                             # "Ignorar sempre (até fechar o Maestro)"
    app.bt_buscar.invoke()
    esperar(app)
    assert [t for t, _ in perguntas].count("Ignorar o robots.txt?") == 5 and len(app.links) == 1
    for _ in range(2):                                                 # confirmação geral: não pergunta mais
        app.bt_buscar.invoke()
        esperar(app)
        assert [t for t, _ in perguntas].count("Ignorar o robots.txt?") == 5 and len(app.links) == 1
    app.var_ignorar_robots.set(False)
    app.bt_buscar.invoke()                                             # desmarcada: respeita e não pergunta antes
    esperar(app)
    assert [t for t, _ in perguntas].count("Ignorar o robots.txt?") == 5 and not app.links
    app.var_ignorar_robots.set(True)                                   # marcou de novo: a geral acabou, pergunta
    resposta[0] = None
    app.bt_buscar.invoke()
    assert [t for t, _ in perguntas].count("Ignorar o robots.txt?") == 6

def test_sem_endereco_e_sem_selecao(app):
    app.bt_buscar.invoke()
    app.bt_baixar_sel.invoke()
    assert [c[1] for c in app.caixas] == ["Falta o endereço", "Nada selecionado"]
    app.definir_url("site.com/videos")
    url, _ = app._validar()
    assert url == "https://site.com/videos"


def _tem_chromium():
    from test_modo_navegador import _chromium_disponivel
    return _chromium_disponivel()


@pytest.mark.skipif(not _tem_chromium(), reason="Playwright/Chromium indisponível")
def test_navegador_pausa_e_login(app, servidor):
    app.definir_url(servidor.base + "/js")
    app.var_pausar.set(True)
    app._ajustar_checks()
    app.bt_buscar.invoke()
    esperar(app)
    assert any(c[1] == "Sua vez" for c in app.caixas)
    assert "Aula JS" in titulos(app)

    app.var_pausar.set(False)
    app.var_visivel.set(False)
    app.definir_url(servidor.base + "/login-cookie")
    app.bt_login.invoke()
    esperar(app)
    assert app.var_nav.get()
    app.definir_url(servidor.base + "/area-logada")
    app.var_seletor.set("a.video-link")
    app.bt_buscar.invoke()
    esperar(app)
    assert titulos(app) == ["Exclusivo"]


# ------------------------------------------------------------------ aba Jellyfin
FILMES = {"Matrix.1999.1080p.BluRay.x264-VERSAO.mp4": "Matrix (1999)/Matrix (1999).mp4",
          "interestellar_filme_completo_dublado_2014.mkv": "Interestelar (2014)/Interestelar (2014).mkv",
          "O.Poderoso.Chefao.1972.Bluray.mkv": "O Poderoso Chefão (1972)/O Poderoso Chefão (1972).mkv"}


def _linhas_jf(app):
    return [app.tabela_jf.item(i, "values") for i in app.tabela_jf.get_children()]


def _preparar(app, tmp_path, nomes, modo="Filmes"):
    origem = tmp_path / "Downloads"
    origem.mkdir()
    for n in nomes:
        (origem / n).write_bytes(b"video")
    app.seletor_aba.set("Jellyfin")
    app.mostrar_aba("Jellyfin")
    if modo == "Séries":
        app.seletor_modo.set("Séries")
        app._ao_trocar_modo("Séries")
    app.var_jf_origem.set(str(origem))
    app.var_jf_destino.set(str(tmp_path / modo))
    return origem, tmp_path / modo


def test_jellyfin_previa_organizar_legendas_e_desfazer(app, tmp_path):
    origem, filmes = _preparar(app, tmp_path, FILMES)
    assert app.bt_organizar.cget("state") == "disabled"          # sem prévia, não organiza

    app.bt_previa.invoke()
    esperar(app)
    assert {l[1] for l in _linhas_jf(app)} == {"vai mover"}
    assert not filmes.exists()                                    # prévia não move nada
    assert app.bt_organizar.cget("state") == "normal"

    app.bt_organizar.invoke()
    esperar(app)
    for destino in FILMES.values():
        assert (filmes / destino).is_file()
        pasta = (filmes / destino).parent
        assert (pasta / f"{pasta.name}.pt-BR.srt").is_file()      # legenda do site de demonstração
    assert all(l[1].endswith("movido") and l[4].endswith("baixada") for l in _linhas_jf(app))
    assert app.caixas[-1][:2] == ("sucesso", "Organização concluída")
    assert app.bt_organizar.cget("state") == "disabled"           # precisa de nova prévia

    app.bt_desfazer.invoke()
    esperar(app)
    assert sorted(p.name for p in origem.iterdir()) == sorted(FILMES)
    assert app.caixas[-1][1] == "Desfeito"


def test_jellyfin_series_e_opcoes_mudadas_exigem_nova_previa(app, tmp_path):
    origem, series = _preparar(app, tmp_path, ["Dark.S01E02.WEBRip.mkv", "sem_numero.mp4"], modo="Séries")
    app.bt_previa.invoke()
    esperar(app)
    linhas = {l[2]: l for l in _linhas_jf(app)}
    assert linhas["Dark.S01E02.WEBRip.mkv"][3].startswith("Dark S01E02.mkv")   # só o nome, sem repetir a pasta
    assert linhas["sem_numero.mp4"][1].endswith("não identificado")

    app.var_jf_destino.set(str(tmp_path / "OutraPasta"))         # mudou depois da prévia
    app.ao_organizar()
    assert app.caixas[-1][1] == "Pré-visualize de novo" and not (tmp_path / "OutraPasta").exists()

    app.var_jf_destino.set(str(series))
    app.bt_previa.invoke()
    esperar(app)
    app.bt_organizar.invoke()
    esperar(app)
    assert (series / "Dark (2017)/Season 01/Dark S01E02.pt-BR.srt").is_file()
    assert (origem / "sem_numero.mp4").exists()                  # não identificado fica onde está


def test_jellyfin_baixar_legendas_que_faltam(app, tmp_path):
    filmes = tmp_path / "Filmes"
    for nome in ("Matrix (1999)", "Cidade de Deus (2002)"):
        (filmes / nome).mkdir(parents=True)
        (filmes / nome / f"{nome}.mkv").write_bytes(b"v")
    app.mostrar_aba("Jellyfin")
    app.var_jf_destino.set(str(filmes))
    app.bt_legendas.invoke()
    esperar(app)
    legendas = {l[2]: l[4] for l in _linhas_jf(app)}
    assert legendas["Matrix (1999)"].endswith("baixada")
    assert legendas["Cidade de Deus (2002)"].endswith("não encontrada")


def test_jellyfin_validacoes_e_config(app, tmp_path):
    from videoscraper import config
    app.mostrar_aba("Jellyfin")
    app.var_jf_origem.set(str(tmp_path / "nao-existe"))
    app.bt_previa.invoke()
    assert app.caixas[-1][1] == "Pasta de origem"
    (tmp_path / "o").mkdir()
    app.var_jf_origem.set(str(tmp_path / "o"))
    app.var_jf_destino.set(str(tmp_path / "F"))
    app.var_jf_tmdb.set(True)
    app.bt_previa.invoke()
    assert app.caixas[-1][1] == "Chave do TMDB"

    app.var_jf_tmdb.set(False)
    app.var_jf_fonte.set(app.FONTES_LEGENDA[1])                  # OpenSubtitles sem chave
    app.var_jf_chave_os.set("")
    (tmp_path / "F").mkdir()
    app.bt_legendas.invoke()
    assert app.caixas[-1][1] == "Legendas"

    app.var_jf_chave_os.set("segredo")
    app._salvar_config()
    salvo = config.carregar()["jellyfin"]
    assert salvo["destino_filmes"] == str(tmp_path / "F") and "chave_opensubtitles" not in salvo
    app.var_jf_lembrar.set(True)
    app._salvar_config()
    assert config.carregar()["jellyfin"]["chave_opensubtitles"] == "segredo"


def test_jellyfin_mesma_pasta_nos_dois_campos(app, tmp_path):
    biblioteca = tmp_path / "Filmes_Organizados"
    (biblioteca / "Matrix (1999)").mkdir(parents=True)
    (biblioteca / "Matrix (1999)" / "Matrix (1999).mp4").write_bytes(b"v")         # já organizado
    (biblioteca / "O.Poderoso.Chefao.1972.Bluray.mkv").write_bytes(b"v")           # bagunçado
    app.mostrar_aba("Jellyfin")
    app.var_jf_origem.set(str(biblioteca))
    app.var_jf_destino.set(str(biblioteca))
    app.var_jf_legendas.set(False)
    app.bt_previa.invoke()
    esperar(app)
    situacoes = {l[2]: l[1] for l in _linhas_jf(app)}
    assert situacoes["Matrix (1999).mp4"].endswith("já organizado")
    assert situacoes["O.Poderoso.Chefao.1972.Bluray.mkv"] == "vai mover"
    assert "1 para mover, 1 já organizado(s)" in app.var_status.get()
    app.bt_organizar.invoke()
    esperar(app)
    assert (biblioteca / "O Poderoso Chefão (1972)" / "O Poderoso Chefão (1972).mkv").is_file()


def test_jellyfin_limpeza_de_torrent_pela_interface(app, tmp_path):
    torrent = tmp_path / "Downloads" / "Creed.II.2018-BLUDV"
    torrent.mkdir(parents=True)
    with open(torrent / "Creed.II.2018.1080p.BluRay.6CH.x264.DUAL-WWW.BLUDV.TV-TioKennedy.mkv", "wb") as f:
        f.truncate(101 * 1024 * 1024)       # "101 MB" sem ocupar disco (passa do limite de trailer)
    for nome in ("BLUDV.TV.url", "Leia.txt", "Creed.II-poster.jpg", "Creed.II.FORCED.srt"):
        (torrent / nome).write_bytes(b"x")
    app.mostrar_aba("Jellyfin")
    app.var_jf_origem.set(str(tmp_path / "Downloads"))
    app.var_jf_destino.set(str(tmp_path / "Filmes"))
    app.var_jf_legendas.set(False)
    app.bt_previa.invoke()
    esperar(app)
    [linha] = _linhas_jf(app)
    assert linha[3].startswith("Creed II (2018).mkv ")                       # só o nome, sem a pasta
    assert "+1 legenda(s), 1 imagem(ns); apagar 2" in linha[3]
    perguntas = []
    app.perguntar = lambda t, m: perguntas.append(m) or True
    app.bt_organizar.invoke()
    esperar(app)
    assert "2 arquivo(s) de lixo" in perguntas[0] and "não tem como desfazer" in perguntas[0]
    assert sorted(p.name for p in (tmp_path / "Filmes" / "Creed II (2018)").iterdir()) == \
        ["Creed II (2018).mkv", "Creed II (2018).pt-BR.forced.srt", "poster.jpg"]
    assert not torrent.exists()


def test_jellyfin_progresso_por_pasta_total_e_antes_depois(app, tmp_path):
    origem, filmes = _preparar(app, tmp_path, FILMES)
    app.bt_previa.invoke()
    esperar(app)
    app.tabela_jf.selection_set("0")
    app.update()
    assert app.lb_detalhe_titulo.cget("text").startswith("Antes → Depois  (Selecionado: #1)")
    assert app.var_antes_pasta.get() == str(origem)
    assert app.var_antes_arquivo.get() in FILMES
    assert app.var_depois_pasta.get().startswith(str(filmes))
    assert app.var_depois_arquivo.get().endswith((".mkv", ".mp4"))

    app.bt_organizar.invoke()
    esperar(app)
    for linha in _linhas_jf(app):
        assert linha[5].endswith("100%") and linha[5].startswith("█" * 10)
    rotulo, barra = app._progresso_total[1]                              # console da aba Jellyfin
    assert rotulo.cget("text").startswith("Concluído: 3 movido(s), 3 legenda(s)")
    assert barra.get() == 1.0
    app.bt_previa.invoke()                                              # nova prévia esconde o total
    esperar(app)
    assert rotulo.cget("text") == ""


# ------------------------------------------------------------------ melhorias: TMDB, Jellyfin, avisos, log
@pytest.fixture
def servicos_gui(app, api_falsa, monkeypatch):
    from test_organizador_completo import IMG_FUNDO, IMG_POSTER, detalhes_tmdb
    from jellyfin_tools.metadados import ClienteTMDB
    from jellyfin_tools.notificacoes import Notificador
    base = api_falsa.base
    api_falsa.rotas["/3/search/movie"] = lambda q: (200, {"results": [{"id": 999}]})
    api_falsa.rotas["/3/movie/999"] = lambda q: (200, detalhes_tmdb(999, "Velhos Bandidos", 2026))
    api_falsa.rotas["/img/poster_pt.jpg"] = lambda q: (200, IMG_POSTER)
    api_falsa.rotas["/img/fundo_hd.jpg"] = lambda q: (200, IMG_FUNDO)
    api_falsa.rotas["/Library/Refresh"] = lambda q: (204, b"")
    api_falsa.rotas["/System/Info"] = lambda q: (200, {"ServerName": "Casa", "Version": "10.10.0"})
    api_falsa.rotas["/discord"] = lambda q: (204, b"")
    monkeypatch.setattr(app_moderna, "ClienteTMDB",
                        lambda chave: ClienteTMDB(chave, base_url=base + "/3", base_imagens=base + "/img"))
    monkeypatch.setattr(app_moderna, "Notificador", lambda d, t, c: Notificador(d, t, c, telegram_base=base))
    app.mostrar_aba("Jellyfin")
    app.var_jf_chave_tmdb.set("chave-tmdb")
    app.var_jf_url.set(base)
    app.var_jf_chave_jellyfin.set("chave-jellyfin")
    app.var_jf_discord.set(base + "/discord")
    return api_falsa


def _corpos(api, caminho):
    import json
    return [json.loads(p["corpo"]) if p["corpo"] else None for p in api.pedidos if p["caminho"] == caminho]


def test_melhorias_ao_organizar(app, servicos_gui, tmp_path):
    origem, filmes = tmp_path / "Downloads", tmp_path / "Filmes"
    origem.mkdir()
    with open(origem / "Velhos.Bandidos.2026.1080p.WEB-DL.NACIONAL.5.1.mkv", "wb") as f:
        f.truncate(101 * 1024 * 1024)
    app.var_jf_origem.set(str(origem))
    app.var_jf_destino.set(str(filmes))
    app.bt_previa.invoke()
    esperar(app)
    app.bt_organizar.invoke()
    esperar(app)
    pasta = filmes / "Velhos Bandidos (2026)"
    assert sorted(p.name for p in pasta.iterdir()) == [
        "Velhos Bandidos (2026).mkv", "Velhos Bandidos (2026).nfo", "Velhos Bandidos (2026).pt-BR.srt",
        "backdrop.jpg", "poster.jpg"]
    assert [c["content"] for c in _corpos(servicos_gui, "/discord")] == [
        "\U0001F37F **Novo filme adicionado ao Jellyfin:** Velhos Bandidos (2026)"]
    assert len(_corpos(servicos_gui, "/Library/Refresh")) == 1
    assert "Pôster/backdrop/.nfo: 1" in app.caixas[-1][2]
    log = app.arquivo_log.read_text(encoding="utf-8")
    assert "Processado: Velhos Bandidos (2026)" in log and "Jellyfin: escaneamento" in log
    assert "Processado: Velhos Bandidos (2026)" in app.logs[1].get("1.0", "end")   # também no console


def test_botoes_de_teste_e_completar_biblioteca(app, servicos_gui, tmp_path):
    app.bt_testar_jellyfin.invoke()
    esperar(app)
    assert app.caixas[-1] == ("sucesso", "Jellyfin conectado", "Tudo certo: Casa (versão 10.10.0).")
    app.var_jf_chave_jellyfin.set("")
    app.bt_testar_jellyfin.invoke()
    esperar(app)
    assert app.caixas[-1][0] == "erro"
    app.var_jf_chave_jellyfin.set("chave-jellyfin")

    app.bt_testar_avisos.invoke()
    esperar(app)
    assert app.caixas[-1][1:] == ("Avisos", "Aviso de teste enviado. Confira o Discord/Telegram.")

    pasta = tmp_path / "Filmes" / "Velhos Bandidos (2026)"
    pasta.mkdir(parents=True)
    (pasta / "Velhos Bandidos (2026).mkv").write_bytes(b"v")
    app.var_jf_destino.set(str(tmp_path / "Filmes"))
    avisos_antes = len(_corpos(servicos_gui, "/discord"))
    app.bt_legendas.invoke()                                            # "Completar biblioteca"
    esperar(app)
    assert {"poster.jpg", "backdrop.jpg", "Velhos Bandidos (2026).nfo",
            "Velhos Bandidos (2026).pt-BR.srt"} <= {p.name for p in pasta.iterdir()}
    assert len(_corpos(servicos_gui, "/discord")) == avisos_antes      # completar não avisa
    assert _linhas_jf(app)[0][4].endswith("baixada")


def test_segredos_so_sao_salvos_se_pedir(app, servicos_gui):
    from videoscraper import config
    app._salvar_config()
    salvo = config.carregar()["jellyfin"]
    for segredo in app_moderna.SEGREDOS:
        assert segredo not in salvo
    assert salvo["jellyfin_url"] == servicos_gui.base                 # o endereço não é segredo
    app.var_jf_lembrar.set(True)
    app._salvar_config()
    assert config.carregar()["jellyfin"]["jellyfin_api_key"] == "chave-jellyfin"


def test_erro_interno_nao_congela_a_janela(app):
    def quebrado(*a):
        raise RuntimeError("bug de teste")
    app.adicionar_linha_jf = quebrado
    app.fila.put(("jf_alvos", [("a", "b")]))                           # vai dar erro ao tratar
    app._rodar("Testando...", lambda: None)                             # e a tarefa termina normalmente
    esperar(app)
    assert "bug de teste" in app.arquivo_log.read_text(encoding="utf-8")


# ------------------------------------------------------------------ filtro, idiomas e apagar pasta
def _video_grande(caminho, mb=101):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, "wb") as f:
        f.truncate(mb * 1024 * 1024)


def test_filtro_por_situacao(app, tmp_path):
    from videoscraper import config
    biblioteca = tmp_path / "Filmes"
    _video_grande(biblioteca / "Matrix (1999)" / "Matrix (1999).mkv")            # já organizado
    _video_grande(biblioteca / "Cidade.de.Deus.2002.1080p.mkv")                    # vai mover
    _video_grande(biblioteca / "video_sem_ano.mp4")                                # não identificado
    app.mostrar_aba("Jellyfin")
    app.var_jf_origem.set(str(biblioteca))
    app.var_jf_destino.set(str(biblioteca))
    app.var_jf_legendas.set(False)
    app.bt_previa.invoke()
    esperar(app)
    assert len(_linhas_jf(app)) == 3

    app.vars_filtro_jf["organizado"].set(False)                                   # desmarca "Já organizado"
    app.aplicar_filtro_jf()
    assert [l[2] for l in _linhas_jf(app)] == ["Cidade.de.Deus.2002.1080p.mkv", "video_sem_ano.mp4"]
    assert app._extras_tabela[str(app.tabela_jf)][0].cget("text") == "2 de 3"     # contador "visíveis de total"

    app.vars_filtro_jf["mover"].set(False)                                        # esconde quem vai mover
    app.aplicar_filtro_jf()
    perguntas, avisos = [], []
    app.perguntar = lambda t, m: perguntas.append(m) or True
    app.mostrar_mensagem = lambda t, m, tipo="info": avisos.append(m)
    app.bt_organizar.invoke()
    assert perguntas == [] and "à vista" in avisos[0]                            # escondido não é movido
    assert (biblioteca / "Cidade.de.Deus.2002.1080p.mkv").exists()
    app.vars_filtro_jf["mover"].set(True)
    app.aplicar_filtro_jf()
    app.bt_organizar.invoke()
    esperar(app)
    assert (biblioteca / "Cidade de Deus (2002)" / "Cidade de Deus (2002).mkv").exists()
    app.vars_filtro_jf["movido"].set(False)                                       # "movido" também some
    app.aplicar_filtro_jf()
    assert [l[2] for l in _linhas_jf(app)] == ["video_sem_ano.mp4"]

    app._salvar_config()                                                          # o filtro é lembrado
    assert set(config.carregar()["jellyfin"]["filtros_ocultos"]) == {"organizado", "movido"}


def test_varios_idiomas_pela_janela(app, tmp_path):
    origem = tmp_path / "Downloads"
    _video_grande(origem / "Matrix.1999.1080p.mkv")
    app.mostrar_aba("Jellyfin")
    app.var_jf_origem.set(str(origem))
    app.var_jf_destino.set(str(tmp_path / "Filmes"))
    app.vars_idioma_jf["en"].set(True)
    app.var_jf_outros_idiomas.set("francês")
    assert app.idiomas_jf() == "pt-BR, en, fr"
    app.bt_previa.invoke()
    esperar(app)
    app.bt_organizar.invoke()
    esperar(app)
    pasta = tmp_path / "Filmes" / "Matrix (1999)"
    assert (pasta / "Matrix (1999).pt-BR.srt").exists() and (pasta / "Matrix (1999).en.srt").exists()
    assert not (pasta / "Matrix (1999).fr.srt").exists()                          # o site não tem francês
    assert _linhas_jf(app)[0][4] == "pt-BR ✓ · en ✓ · fr ✕"

    app.definir_idiomas_jf("es, de")                                              # carregar do config
    assert app.vars_idioma_jf["es"].get() and not app.vars_idioma_jf["pt-BR"].get()
    assert app.var_jf_outros_idiomas.get() == "de"


def test_apagar_pasta_do_torrent_pela_janela(app, tmp_path):
    torrent = tmp_path / "Downloads" / "Matrix.1999.1080p-GRUPO"
    _video_grande(torrent / "Matrix.1999.1080p.mkv")
    (torrent / "Screens").mkdir()
    (torrent / "Screens" / "cena.png").write_bytes(b"x")
    app.mostrar_aba("Jellyfin")
    app.var_jf_origem.set(str(tmp_path / "Downloads"))
    app.var_jf_destino.set(str(tmp_path / "Filmes"))
    app.var_jf_legendas.set(False)
    app.var_jf_apagar_pasta.set(True)
    app.bt_previa.invoke()
    esperar(app)
    assert "apagar a pasta" in _linhas_jf(app)[0][3]
    app.tabela_jf.selection_set("0")
    app.update()
    assert "Apagar a pasta inteira:" in app.lb_detalhe_extras.cget("text")
    perguntas = []
    app.perguntar = lambda t, m: perguntas.append(m) or True
    app.bt_organizar.invoke()
    esperar(app)
    assert "1 pasta(s) de torrent serão APAGADAS" in perguntas[0]
    assert not torrent.exists() and (tmp_path / "Downloads").exists()
    assert (tmp_path / "Filmes" / "Matrix (1999)" / "Matrix (1999).mkv").exists()


# ------------------------------------------------------------------ TMDB: teste, "Nome via", episódios, %
@pytest.fixture
def tmdb_gui(app, api_falsa, monkeypatch):
    from jellyfin_tools.catalogo import CatalogoTMDB
    base = api_falsa.base + "/3"

    class TMDBFalso(CatalogoTMDB):
        def __init__(self, chave, **kw):
            super().__init__(chave, base_url=base)

    monkeypatch.setattr(app_moderna, "CatalogoTMDB", TMDBFalso)
    monkeypatch.setattr(app_moderna.automacao, "CatalogoTMDB", TMDBFalso)     # o catálogo da prévia
    api_falsa.rotas["/3/configuration"] = lambda q: (
        (200, {}) if q.get("api_key") == ["boa"] else (401, {"status_message": "Invalid API key"}))
    matrix = {"results": [{"id": 603, "title": "Matrix", "original_title": "The Matrix",
                           "release_date": "1999-03-31"}]}
    api_falsa.rotas["/3/search/movie"] = lambda q: (
        (401, {}) if q.get("api_key") != ["boa"] else (200, matrix if q["query"] == ["Matrix"] else {"results": []}))
    api_falsa.rotas["/3/search/tv"] = lambda q: (200, {"results": [
        {"id": 70523, "name": "Dark", "original_name": "Dark", "first_air_date": "2017-12-01"}]})
    api_falsa.rotas["/3/tv/70523/season/1"] = lambda q: (200, {"episodes": [
        {"episode_number": 1, "name": "Segredos"}, {"episode_number": 2, "name": "Mentiras"}]})
    return api_falsa


def test_botao_testar_conexao_com_o_tmdb(app, tmdb_gui):
    app.mostrar_aba("Jellyfin")
    app.var_jf_chave_tmdb.set("")
    app.bt_testar_tmdb.invoke()
    assert app.caixas[-1][:2] == ("aviso", "TMDB")                     # sem chave: nem tenta

    app.var_jf_chave_tmdb.set("errada")
    app.bt_testar_tmdb.invoke()
    esperar(app)
    assert app.caixas[-1][0] == "erro" and "recusou a chave" in app.caixas[-1][2]
    assert app.lb_estado_tmdb.cget("text").startswith("✕  Sem conexão")

    app.var_jf_chave_tmdb.set("boa")
    app.var_jf_tmdb.set(True)
    app.bt_testar_tmdb.invoke()
    esperar(app)
    assert app.caixas[-1][:2] == ("sucesso", "TMDB conectado") and "TMDB ✓" in app.caixas[-1][2]
    assert app.lb_estado_tmdb.cget("text") == "✓  TMDB conectado"


def test_coluna_nome_via_e_porcentagem_na_previa(app, tmdb_gui, tmp_path):
    _preparar(app, tmp_path, ["Matrix.1999.mkv", "Interestelar.2014.mkv", "Filme.Caseiro.2020.mkv"])
    estados = []
    original = app.definir_progresso_rodape

    def espiar(fracao, texto=""):
        original(fracao, texto)
        estados.append((app.var_status.get(), app.barra.get()))
    app.definir_progresso_rodape = espiar

    app.var_jf_chave_tmdb.set("boa")
    app.var_jf_tmdb.set(True)
    app.bt_previa.invoke()
    esperar(app)
    via = {l[2]: l[6] for l in _linhas_jf(app)}
    assert via == {"Matrix.1999.mkv": "TMDB ✓", "Interestelar.2014.mkv": "TMDB ✕ (catálogo)",
                   "Filme.Caseiro.2020.mkv": "TMDB ✕ (arquivo)"}
    assert "TMDB identificou 1 de 3." in app.var_status.get()
    # o rodapé mostrou a porcentagem (e a barra acompanhou) durante a prévia
    assert any(s.startswith("Pré-visualizando... 100%  ·  Analisando: 3 de 3") for s, _ in estados)
    assert estados[-1][1] == pytest.approx(1.0)

    app.var_jf_tmdb.set(False)                                         # sem TMDB: só a origem do nome
    app.bt_previa.invoke()
    esperar(app)
    assert sorted(l[6] for l in _linhas_jf(app)) == ["arquivo", "catálogo", "catálogo"]


def test_tmdb_fora_do_ar_avisa_na_previa(app, tmdb_gui, tmp_path):
    _preparar(app, tmp_path, ["Matrix.1999.mkv"])
    app.var_jf_chave_tmdb.set("errada")
    app.var_jf_tmdb.set(True)
    app.bt_previa.invoke()
    esperar(app)
    assert app.caixas[-1][:2] == ("aviso", "TMDB não respondeu")
    assert _linhas_jf(app)[0][6] == "TMDB ✕ (catálogo)"                # o catálogo local salvou o nome
    assert app.lb_estado_tmdb.cget("text").startswith("✕  Sem resposta na prévia")


def test_series_com_nome_do_episodio_pela_janela(app, tmdb_gui, tmp_path):
    origem, series = _preparar(app, tmp_path, ["Dark.S01E01.1080p.mkv", "Dark.S01E02.mkv"], modo="Séries")
    app.var_jf_chave_tmdb.set("boa")
    app.var_jf_tmdb.set(True)
    assert app.var_jf_nomes_ep.get()                                    # vem marcado
    app.bt_previa.invoke()
    esperar(app)
    novos = sorted(l[3] for l in _linhas_jf(app))
    assert novos == ["Dark S01E01 - Segredos.mkv", "Dark S01E02 - Mentiras.mkv"]
    app.bt_organizar.invoke()
    esperar(app)
    assert sorted(p.name for p in (series / "Dark (2017)" / "Season 01").glob("*.mkv")) == [
        "Dark S01E01 - Segredos.mkv", "Dark S01E02 - Mentiras.mkv"]

    app.var_jf_nomes_ep.set(False)                                      # desmarcado: só o número
    (origem / "Dark.S01E03.mkv").write_bytes(b"v")
    app.bt_previa.invoke()
    esperar(app)
    assert [l[3] for l in _linhas_jf(app) if l[2] == "Dark.S01E03.mkv"] == ["Dark S01E03.mkv"]


# ------------------------------------------------------------------ Completar com "substituir", lista ampliada
def test_completar_biblioteca_escolhe_o_que_completar(app, servicos_gui, tmp_path, monkeypatch):
    pasta = tmp_path / "Filmes" / "Velhos Bandidos (2026)"
    pasta.mkdir(parents=True)
    (pasta / "Velhos Bandidos (2026).mkv").write_bytes(b"v")
    (pasta / "Velhos Bandidos (2026).pt-BR.srt").write_text("antiga", encoding="utf-8")
    (pasta / "poster.png").write_bytes(b"antigo")
    app.var_jf_destino.set(str(tmp_path / "Filmes"))
    padroes = []

    def responder(resposta):
        monkeypatch.setattr(app, "_pedir_o_que_completar",
                            lambda pasta_, padrao, series: (padroes.append(padrao), resposta)[1])

    responder(None)                                                      # Cancelar: nada acontece
    app.bt_legendas.invoke()
    esperar(app)
    assert (pasta / "poster.png").read_bytes() == b"antigo" and not (pasta / "poster.jpg").exists()

    responder({"legendas": True, "imagens": True, "nfo": True, "substituir": False})   # só o que falta
    app.bt_legendas.invoke()
    esperar(app)
    assert (pasta / "Velhos Bandidos (2026).pt-BR.srt").read_text(encoding="utf-8") == "antiga"
    assert (pasta / "poster.png").exists() and not (pasta / "poster.jpg").exists()
    assert _linhas_jf(app)[0][4].endswith("já existia")

    # o caso do usuário: SÓ as imagens, trocando as que existem; a legenda não é tocada
    responder({"legendas": False, "imagens": True, "nfo": False, "substituir": True})
    app.bt_legendas.invoke()
    esperar(app)
    assert (pasta / "Velhos Bandidos (2026).pt-BR.srt").read_text(encoding="utf-8") == "antiga"
    assert (pasta / "poster.jpg").is_file() and not (pasta / "poster.png").exists()   # trocou, sem duplicar
    assert "legenda" not in app.var_status.get() and "1 filme(s) com pôster/.nfo" in app.var_status.get()
    assert app.var_jf_sobrescrever.get()                                  # a caixa acompanha a escolha

    responder({"legendas": True, "imagens": False, "nfo": False, "substituir": True})
    app.bt_legendas.invoke()
    esperar(app)
    assert (pasta / "Velhos Bandidos (2026).pt-BR.srt").read_text(encoding="utf-8") != "antiga"
    assert padroes[-1]["legendas"] is False and padroes[-1]["imagens"] is True   # lembrou a escolha anterior


def test_janela_completar_nao_deixa_completar_nada(app):
    from videoscraper.gui_moderna import DialogoCompletar
    d = DialogoCompletar(app, "E:/Series", {"legendas": False, "imagens": False}, series=True)
    assert d.vars["nfo"].get() is False                                  # séries: .nfo não se aplica
    d._ok()
    assert d.resultado is None and "Marque pelo menos uma" in app.caixas[-1][2]
    d.vars["imagens"].set(True)
    d._ok()
    assert d.resultado == {"legendas": False, "imagens": True, "nfo": False, "substituir": False}


def test_ampliar_lista_esconde_painel_e_console(app):
    app.mostrar_aba("Jellyfin")
    app.update()
    for i in range(40):
        app.adicionar_linha_jf(str(i), i + 1, "vai mover", None, f"a{i}.mkv", f"A {i}.mkv")
    app.update()
    detalhe, console = app.partes_visiveis_jf()                    # o que cabe nesta tela
    assert app._cartao_detalhe_jf.winfo_ismapped() == detalhe and app._cartao_console_jf.winfo_ismapped() == console
    altura = app.tabela_jf.winfo_height()
    app.bt_ampliar_jf.invoke()
    app.update()
    assert not app._cartao_console_jf.winfo_ismapped() and not app._cartao_detalhe_jf.winfo_ismapped()
    assert app._corpo_jf.grid_rowconfigure(2)["minsize"] == 0      # o espaço do console vai para a lista
    if detalhe or console:
        assert app.tabela_jf.winfo_height() > altura
    assert app.bt_ampliar_jf.cget("text").endswith("Reduzir lista")
    app.bt_ampliar_jf.invoke()
    app.update()
    assert app._cartao_detalhe_jf.winfo_ismapped() == detalhe and app.bt_ampliar_jf.cget("text").endswith("Ampliar lista")


def test_aba_jellyfin_mostra_so_o_que_cabe(app):
    """Notebook: antes, lista + painel + console pediam mais altura do que a janela tinha; o Tk espremia tudo, a
    lista ficava com ~5 linhas e o console cortado. Agora sai o que não cabe e a lista cresce."""
    assert app.partes_visiveis_jf(536) == (False, False)          # janela de 700 px (tela 1366x768)
    assert app.partes_visiveis_jf(736) == (True, False)           # janela de 900 px (Full HD): lista + Antes → Depois
    assert app.partes_visiveis_jf(900) == (True, True)            # tela alta: tudo
    app.mostrar_aba("Jellyfin")
    app.geometry("1320x700")
    for _ in range(20):
        app.update()
    assert not app._cartao_detalhe_jf.winfo_ismapped() and not app._cartao_console_jf.winfo_ismapped()
    assert app.tabela_jf.winfo_height() > 156                        # antes: 156 px em qualquer tamanho
    corpo = app._corpo_jf
    filhos = [w for w in corpo.winfo_children() if w.winfo_ismapped()]
    assert all(w.winfo_y() + w.winfo_height() <= corpo.winfo_height() + 2 for w in filhos)   # nada cortado embaixo


def test_sobras_de_antes_aparecem_e_sao_apagadas_pela_janela(app, tmp_path):
    import json
    raiz = tmp_path / "The Office"
    sobra = raiz / "Vida de Escritorio 2005 - 1a Temporada WWW.BLUDV.TV"
    sobra.mkdir(parents=True)
    with open(sobra / "BLUDV.TV.mp4", "wb") as f:
        f.truncate(52 * 1024 * 1024)
    (sobra / "The.Office.S01E01.720p-poster.jpg").write_bytes(b"jpg")
    novo = raiz / "The Office (2005)" / "Season 01" / "The Office S01E01 - Piloto.mkv"
    novo.parent.mkdir(parents=True)
    novo.write_bytes(b"v")
    (raiz / ".organizador").mkdir()
    (raiz / ".organizador" / "log-1.json").write_text(json.dumps({"raiz": str(raiz), "itens": [
        {"de": str(sobra / "The.Office.S01E01.720p.mkv"), "para": str(novo)}]}), encoding="utf-8")
    app.mostrar_aba("Jellyfin")
    app.seletor_modo.set("Séries")
    app._ao_trocar_modo("Séries")
    app.var_jf_origem.set(str(raiz))
    app.var_jf_destino.set(str(raiz))
    app.var_jf_apagar_pasta.set(True)
    app.var_jf_legendas.set(False)
    app.bt_previa.invoke()
    esperar(app)
    linha = next(l for l in _linhas_jf(app) if l[2] == sobra.name)
    assert linha[1] == "vai apagar a pasta" and "1 imagem(ns)" in linha[3]
    assert app.bt_organizar.cget("state") == "normal"                    # só limpeza já libera
    assert "1 pasta(s) que sobraram de antes" in app.var_status.get()
    app.bt_organizar.invoke()
    esperar(app)
    assert not sobra.exists()
    assert (novo.parent / "The Office S01E01 - Piloto-thumb.jpg").is_file()
    linha = next(l for l in _linhas_jf(app) if l[2] == sobra.name)
    assert linha[1].endswith("pasta apagada")
    assert "Pastas de torrent apagadas: 1" in app.caixas[-1][2]


def test_maximos_dos_campos_aceitam_valores_grandes():
    j = JanelaModerna()
    try:
        j.campo_limite.var.set("50000")
        j.campo_maxp.var.set("80000")
        o = j.obter_opcoes()
        assert (o.limite, o.max_paginas) == (50000, 80000)        # antes travava em 1000 e 2000
        j.campo_limite.var.set("999999")
        assert j.campo_limite.get() == 100_000                    # novo máximo
    finally:
        j.destroy()


def test_caminho_colado_e_avisado_antes_da_previa(app, tmp_path, monkeypatch):
    from jellyfin_tools import organizador
    monkeypatch.setattr(organizador, "WINDOWS", True)                    # regras de nome do Windows
    origem, _ = _preparar(app, tmp_path, ["Matrix.1999.mkv"])
    colado = r"E:\Series_OE:\Series_Organizadas\Series"
    app.var_jf_destino.set(colado)
    perguntas = []
    app.perguntar = lambda t, m: (perguntas.append(m), False)[1]          # "Cancelar"
    app.bt_previa.invoke()
    esperar(app)
    assert "no meio" in perguntas[-1] and r"E:\Series_Organizadas\Series" in perguntas[-1]
    assert app.var_jf_destino.get() == colado and not _linhas_jf(app)     # nada rodou

    app.var_jf_destino.set(r"E:\Filmes?")                                 # sem sugestão: só avisa
    app.bt_previa.invoke()
    assert app.caixas[-1][0] == "aviso" and "não aceita" in app.caixas[-1][2]

    app.var_jf_destino.set(colado)
    app.perguntar = lambda t, m: True                                     # "Continuar": corrige o campo
    app.ao_validar = app._validar_jellyfin(precisa_origem=True)
    assert app.var_jf_destino.get() == r"E:\Series_Organizadas\Series"
    assert app.ao_validar is not None and app.ao_validar.destino == r"E:\Series_Organizadas\Series"


def test_registro_por_acao_no_console(app, tmp_path):
    _preparar(app, tmp_path, ["Matrix.1999.mkv"])
    app.var_jf_legendas.set(False)
    app.bt_previa.invoke()
    esperar(app)
    app.bt_organizar.invoke()
    esperar(app)
    console = app.logs[1]
    nomes = app._menus_registro[1].cget("values")
    assert "Organizando" in nomes[0] and "Pré-visualizando" in nomes[1]       # o mais novo primeiro
    assert len(app._registros) == 3                                          # Início + as duas ações
    texto_organizar = console.get("1.0", "end")
    assert "===== Organizando =====" in texto_organizar and "Pré-visualizando (" not in texto_organizar

    app._ao_escolher_registro(nomes[1])                                      # ver a prévia
    texto_previa = console.get("1.0", "end")
    assert "Pré-visualizando (filmes)" in texto_previa and "===== Organizando" not in texto_previa
    app.escrever_log("linha nova da ação atual\n")                           # não mistura na prévia
    assert "linha nova" not in console.get("1.0", "end")
    app._ao_escolher_registro(nomes[0])
    assert "linha nova da ação atual" in console.get("1.0", "end")

    app.limpar_log()                                                         # limpa só o que está à mostra
    assert console.get("1.0", "end").strip() == "" and app._registros[1]["partes"]
    log = app.arquivo_log.read_text(encoding="utf-8")
    assert "===== Pré-visualizando =====" in log and "===== Organizando =====" in log


def test_previa_em_filmes_com_episodios_oferece_modo_series(app, tmp_path):
    from test_jellyfin_series import BIG_BANG
    origem, destino = _preparar(app, tmp_path, BIG_BANG)                 # modo Filmes (o padrão)
    perguntas = []
    app.perguntar = lambda t, m: (perguntas.append((t, m)), False)[1]     # "Cancelar"
    app.bt_previa.invoke()
    esperar(app)
    assert perguntas and perguntas[-1][0] == "Parece série" and "3 de 3" in perguntas[-1][1]
    assert app._modo_atual == "Filmes"
    assert all("use o modo Séries" in l[3] for l in _linhas_jf(app))

    app.perguntar = lambda t, m: (perguntas.append((t, m)), True)[1]      # "Continuar"
    app.bt_previa.invoke()
    esperar(app)
    esperar(app)                                                         # a 2ª prévia, já em Séries
    assert app._modo_atual == "Séries" and app.var_jf_destino.get() == str(destino)
    assert sorted(l[3] for l in _linhas_jf(app)) == ["Big Bang - A Teoria S01E02.mkv",
                                                     "Big Bang - A Teoria S05E19.mkv",
                                                     "Big Bang - A Teoria S11E24.mkv"]
    assert app.bt_organizar.cget("state") == "normal"


def test_abrir_log_abre_so_a_acao_escolhida(app, tmp_path):
    _preparar(app, tmp_path, ["Matrix.1999.mkv"])
    app.var_jf_legendas.set(False)
    abertos = []
    app._abrir_no_sistema = abertos.append
    app.bt_previa.invoke()
    esperar(app)
    app.bt_organizar.invoke()
    esperar(app)
    app.bt_abrir_log.invoke()                                            # à mostra: o Organizar
    organizar = Path(abertos[-1]).read_text(encoding="utf-8")
    assert Path(abertos[-1]).parent == app.pasta_logs and abertos[-1].endswith("_Organizando.log")
    assert "===== Organizando =====" in organizar and "Pré-visualizando (" not in organizar
    assert "[movido] Matrix.1999.mkv" in organizar

    app._ao_escolher_registro(app._menus_registro[1].cget("values")[1])  # escolhe a prévia
    app.bt_abrir_log.invoke()
    previa = Path(abertos[-1]).read_text(encoding="utf-8")
    assert abertos[-1].endswith("_Pré-visualizando.log") and "Pré-visualizando (filmes)" in previa
    assert "===== Organizando" not in previa

    app._ao_escolher_registro(app._menus_registro[1].cget("values")[-1])  # "Início": sem arquivo próprio
    app.bt_abrir_log.invoke()
    assert abertos[-1] == str(app.arquivo_log) and app.caixas[-1][1] == "Log"


def test_subdl_na_janela_como_fonte_e_como_reserva(app):
    from jellyfin_tools import ProvedorOpenSubtitles, ProvedorSubDL
    app.mostrar_aba(app.ABA_CONFIG)                                     # as chaves ficam em Configurações
    app.mostrar_config("Chaves de API")
    app.var_jf_fonte.set("OpenSubtitles (API)")
    app._mostrar_campos_jf()
    app.update()
    assert app.campo_chave_subdl.winfo_ismapped() and "reserva" in app.rot_chave_subdl.cget("text")
    app.var_jf_chave_os.set("chave-os")
    with app._provedores(app.obter_opcoes_jellyfin()) as provedores:      # sem chave do SubDL: só o OS
        assert [type(p) for p in provedores] == [ProvedorOpenSubtitles]
    app.var_jf_chave_subdl.set("chave-subdl")
    with app._provedores(app.obter_opcoes_jellyfin()) as provedores:      # com ela: OS e, depois, o SubDL
        assert [type(p) for p in provedores] == [ProvedorOpenSubtitles, ProvedorSubDL]

    app.var_jf_fonte.set("SubDL (API)")
    app._mostrar_campos_jf()
    app.update()
    assert app.rot_chave_subdl.cget("text") == "SubDL"                   # só o SubDL: não é mais a reserva
    app.var_jf_chave_subdl.set("")
    assert "SubDL" in app._problema_legendas(app.obter_opcoes_jellyfin())
    assert "chave_subdl" in app_moderna.SEGREDOS                         # só é salva se pedir


def test_espelhar_links_no_jellyfin_pela_janela(app, tmp_path, monkeypatch):
    from jellyfin_tools.espelho import Verificacao
    from videoscraper.extracao import LinkVideo
    monkeypatch.setattr(app_moderna, "verificar_links",                 # sem internet nos testes
                        lambda urls, **k: {u: Verificacao(True, tempo=0.2) for u in urls})
    base = "https://archive.org/download/x/"
    links = [LinkVideo(base + "nosferatu.mp4", "o", "archive.org", "Nosferatu (1922)", "Domínio público"),
             LinkVideo(base + "anjos.mkv", "o", "archive.org", "Anjos Da Noite 2003 (Dual Audio) PT-BR"),
             LinkVideo(base + "Dark.S01E02.mkv", "o", "archive.org", "Dark episódio 2"),
             LinkVideo(base + "x.mp4", "o", "archive.org", "Initial D - Completo")]
    app._mostrar_links(links)
    tipos = [app.tabela.item(i, "values")[5:] for i in app.tabela.get_children()]
    assert tipos == [("Filme", "Domínio público"), ("Filme", "—"), ("Série", "—"), ("—", "—")]

    app.ao_espelhar_jellyfin()                                       # sem bibliotecas: avisa
    assert app.caixas[-1][0] == "aviso" and "Filmes e de Séries" in app.caixas[-1][2]
    app._destinos.update({"Filmes": str(tmp_path / "Filmes"), "Séries": str(tmp_path / "Series")})
    app.var_jf_destino.set(str(tmp_path / "Filmes"))
    app.var_jf_legendas.set(False)
    perguntas = []
    # vídeos comuns: "Deixar de fora"; depois "Só domínio público / CC"
    app.escolher = lambda t, m, opcoes: (perguntas.append(m), opcoes[-1] if t == "Vídeos comuns" else opcoes[0])[1]
    app.ao_espelhar_jellyfin()
    esperar(app)
    assert "2 filme(s), 1 episódio(s), 1 vídeo(s) comum(ns) (sem ano/episódio: ficam de fora)" in perguntas[-1]
    assert sorted(p.name for p in tmp_path.rglob("*.strm")) == ["Nosferatu (1922).strm"]
    situacoes = [app.tabela.item(i, "values")[1] for i in app.tabela.get_children()]
    assert situacoes[0].endswith("espelhado") and situacoes[1].endswith("sem licença aberta")
    assert app.caixas[-1][1] == "Espelho no Jellyfin" and "Criados: 1 (1 filme(s), 0 episódio(s)" in app.caixas[-1][2]

    app.escolher = lambda t, m, opcoes: opcoes[-1] if t == "Vídeos comuns" else opcoes[1]   # "Todos os identificados"
    app.ao_espelhar_jellyfin()
    esperar(app)
    assert sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*.strm")) == [
        "Filmes/Anjos Da Noite (2003)/Anjos Da Noite (2003).strm", "Filmes/Nosferatu (1922)/Nosferatu (1922).strm",
        "Series/Dark (2017)/Season 01/Dark S01E02.strm"]
    assert app.tabela.item("0", "values")[1].endswith("já espelhado")



def test_espelhar_videos_comuns_numa_pasta_escolhida(app, tmp_path, monkeypatch):
    from jellyfin_tools.espelho import Verificacao
    from videoscraper.extracao import LinkVideo
    monkeypatch.setattr(app_moderna, "verificar_links", lambda urls, **k: {u: Verificacao(True) for u in urls})
    base = "https://meusite.com.br/videos/"
    app._mostrar_links([LinkVideo(base + "aula1.mp4", "o", "meusite", "Aula 1: Variáveis"),
                        LinkVideo(base + "clipe.mp4", "o", "meusite", "Clipe da viagem"),
                        LinkVideo(base + "nosferatu.mp4", "o", "meusite", "Nosferatu (1922)")])
    app._destinos.update({"Filmes": str(tmp_path / "Filmes"), "Séries": str(tmp_path / "Series")})
    app.var_jf_destino.set(str(tmp_path / "Filmes"))
    app.var_jf_legendas.set(False)
    comuns = tmp_path / "Videos comuns"
    perguntas, respostas = [], {"Vídeos comuns": "Escolher a pasta...", "Espelhar no Jellyfin": "Todos os identificados"}
    app.escolher = lambda t, m, opcoes, **k: (perguntas.append((t, opcoes)), respostas.get(t))[1]

    app.ao_espelhar_jellyfin()                                         # fechou a janela de pastas: nada acontece
    assert [t for t, _ in perguntas] == ["Vídeos comuns"] and not list(tmp_path.rglob("*.strm"))
    app._pedir_pasta = lambda titulo, inicial="": str(comuns)          # escolheu uma pasta nova
    app.ao_espelhar_jellyfin()
    esperar(app)
    assert perguntas[-2][1] == ("Escolher a pasta...", "Deixar de fora")
    assert sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*.strm")) == [
        "Filmes/Nosferatu (1922)/Nosferatu (1922).strm", "Videos comuns/Aula 1 Variáveis.strm",
        "Videos comuns/Clipe da viagem.strm"]
    assert (comuns / "Clipe da viagem.strm").read_text(encoding="utf-8").strip() == base + "clipe.mp4"
    assert app.pasta_videos_comuns == str(comuns)                      # lembrada para a próxima vez
    assert "0 episódio(s), 2 vídeo(s) comum(ns))" in app.caixas[-1][2]

    respostas["Vídeos comuns"] = "Usar esta pasta"                     # de novo: oferece a pasta de sempre
    app.ao_espelhar_jellyfin()
    esperar(app)
    assert perguntas[-2][1] == ("Usar esta pasta", "Escolher outra pasta...", "Deixar de fora")
    assert len(list(comuns.glob("*.strm"))) == 2                       # já existiam: não duplica
    assert str(comuns) in app._bibliotecas() and app._bibliotecas()[str(comuns)] == "Vídeos comuns"

    app.ao_desfazer()                                                  # o último espelho, nas DUAS pastas
    esperar(app)
    assert not list(comuns.glob("*.strm")) and not list(tmp_path.rglob("*.strm"))

    app._mostrar_links([LinkVideo(base + "clipe.mp4", "o", "meusite", "Clipe da viagem")])
    respostas["Vídeos comuns"] = "Deixar de fora"                      # só vídeos comuns e "de fora": avisa
    app.ao_espelhar_jellyfin()
    assert "nada a espelhar" in app.caixas[-1][2]


def test_modo_hibrido_espelha_em_vez_de_baixar_e_clicar_no_play(app, tmp_path, monkeypatch):
    from jellyfin_tools.espelho import Verificacao
    from videoscraper import servico
    from videoscraper.extracao import LinkVideo
    monkeypatch.setattr(app_moderna, "verificar_links", lambda urls, **k: {u: Verificacao(True) for u in urls})
    base = "https://meusite.com.br/videos/"
    app._mostrar_links([LinkVideo(base + "nosferatu.mp4", "o", "meusite", "Nosferatu (1922)"),
                        LinkVideo(base + "metropolis.mp4", "o", "meusite", "Metropolis (1927)")])
    app._destinos.update({"Filmes": str(tmp_path / "Filmes"), "Séries": str(tmp_path / "Series")})
    app.var_jf_destino.set(str(tmp_path / "Filmes"))
    app.var_jf_legendas.set(False)
    app.escolher = lambda t, m, opcoes, **k: opcoes[1]                 # "Todos os identificados"
    assert app.bt_baixar_todos.cget("text") == "Baixar todos"
    app.var_espelhar.set(True)
    app._ajustar_botoes_baixar()
    assert (app.bt_baixar_sel.cget("text"), app.bt_baixar_todos.cget("text")) == ("Espelhar selecionados",
                                                                                 "Espelhar todos")
    app.tabela.selection_set("1")
    app.bt_baixar_sel.invoke()                                         # só o selecionado vira .strm
    esperar(app)
    assert [p.name for p in tmp_path.rglob("*.strm")] == ["Metropolis (1927).strm"]
    app.bt_baixar_todos.invoke()                                       # e "todos" espelha o resto
    esperar(app)
    assert sorted(p.name for p in tmp_path.rglob("*.strm")) == ["Metropolis (1927).strm", "Nosferatu (1922).strm"]
    assert not (tmp_path / "videos").exists() or not any((tmp_path / "videos").iterdir())   # nada foi baixado
    app.var_espelhar.set(False)
    app._ajustar_botoes_baixar()
    assert app.bt_baixar_todos.cget("text") == "Baixar todos"          # desmarcado: o download de sempre

    criados = []

    class NavegadorFalso:                                              # sem abrir o Chromium no teste
        def __init__(self, **k):
            criados.append(k)

        def abrir(self):
            pass

        def fechar(self):
            pass
    monkeypatch.setattr(servico, "Navegador", NavegadorFalso)
    app.var_nav.set(True)
    assert app.obter_opcoes().clicar_play is True                      # marcada por padrão
    app._novo_trabalho(app.obter_opcoes()).fechar()
    app.var_clicar_play.set(False)
    app._novo_trabalho(app.obter_opcoes()).fechar()
    assert [k["ativar_midias"] for k in criados] == [True, False]


def test_espelhar_links_temporarios_pergunta_e_lembra(app, tmp_path, monkeypatch):
    from jellyfin_tools.espelho import AVISO_TEMPORARIO, Verificacao
    from videoscraper.extracao import LinkVideo
    aceitou = []

    def verificar(urls, aceitar_temporarios=False, **k):
        aceitou.append(aceitar_temporarios)
        return {u: (Verificacao(True, aviso=AVISO_TEMPORARIO) if aceitar_temporarios or "token" not in u
                    else Verificacao(False, "link temporário (expira; o .strm pararia de funcionar)")) for u in urls}
    monkeypatch.setattr(app_moderna, "verificar_links", verificar)
    base = "https://cdn.meusite.com.br/"
    app._mostrar_links([LinkVideo(base + "nosferatu.mp4?token=abc&expires=9", "o", "meusite", "Nosferatu (1922)"),
                        LinkVideo(base + "metropolis.mp4", "o", "meusite", "Metropolis (1927)")])
    app._destinos.update({"Filmes": str(tmp_path / "Filmes"), "Séries": str(tmp_path / "Series")})
    app.var_jf_destino.set(str(tmp_path / "Filmes"))
    app.var_jf_legendas.set(False)
    perguntas, respostas = [], {"Espelhar no Jellyfin": "Todos os identificados", "Links temporários": None}
    app.escolher = lambda t, m, opcoes, **k: (perguntas.append((t, m, opcoes)), respostas.get(t))[1]

    app.ao_espelhar_jellyfin()                                         # Cancelar: nada acontece
    assert perguntas[-1][0] == "Links temporários" and "1 link(s) são temporários" in perguntas[-1][1]
    assert not app.trabalhando and not list(tmp_path.rglob("*.strm"))
    respostas["Links temporários"] = "Deixar de fora"                  # como antes: só o permanente
    app.ao_espelhar_jellyfin()
    esperar(app)
    assert aceitou[-1] is False and [p.name for p in tmp_path.rglob("*.strm")] == ["Metropolis (1927).strm"]
    respostas["Links temporários"] = "Sempre criar (até fechar o Maestro)"
    app.ao_espelhar_jellyfin()
    esperar(app)
    assert aceitou[-1] is True
    assert sorted(p.name for p in tmp_path.rglob("*.strm")) == ["Metropolis (1927).strm", "Nosferatu (1922).strm"]
    assert next(tmp_path.rglob("Nosferatu*.strm")).read_text(encoding="utf-8").strip().endswith("token=abc&expires=9")
    for arquivo in tmp_path.rglob("*.strm"):
        arquivo.unlink()
    antes = len([p for p in perguntas if p[0] == "Links temporários"])
    app.ao_espelhar_jellyfin()                                         # confirmação geral: não pergunta de novo
    esperar(app)
    assert len([p for p in perguntas if p[0] == "Links temporários"]) == antes and aceitou[-1] is True


def test_traduzir_legendas_com_ia_pela_janela(app, tmp_path, monkeypatch):
    from jellyfin_tools.traducao import Tradutor, ler_srt
    from tests.test_traducao import SRT, ClienteFalso
    filmes = tmp_path / "Filmes"
    for nome in ("A (2001)", "B (2002)"):
        (filmes / nome).mkdir(parents=True)
        (filmes / nome / f"{nome}.mkv").write_bytes(b"\0" * 2_000_000)
        (filmes / nome / f"{nome}.en.srt").write_text(SRT, encoding="utf-8")
    (filmes / "B (2002)" / "B (2002).pt-BR.srt").write_text(SRT, encoding="utf-8")   # B já tem
    app._destinos.update({"Filmes": str(filmes), "Séries": ""})
    app.var_jf_destino.set(str(filmes))
    assert app.obter_opcoes_jellyfin().modelo_traducao == "claude-sonnet-4-6"   # o padrão
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    app.ao_traduzir_legendas()                                         # sem chave: explica onde criar
    assert "console.anthropic.com" in app.caixas[-1][2]
    app.var_jf_chave_claude.set("sk-ant-teste")
    criados = []

    def tradutor_falso(**k):
        criados.append(k)
        return Tradutor(cliente=ClienteFalso(), **k)
    monkeypatch.setattr(app_moderna, "Tradutor", tradutor_falso)
    monkeypatch.setattr(app_moderna.automacao, "Tradutor", tradutor_falso)  # quem cria o tradutor (tradutor_para)
    perguntas = []
    app.escolher = lambda t, m, opcoes, **k: (perguntas.append(m), opcoes[0])[1]
    app.ao_traduzir_legendas()
    esperar(app)
    esperar(app)
    assert "1 vídeo(s) têm legenda só em outro idioma" in perguntas[0] and "A (2001).en.srt" in perguntas[0]
    assert "claude-sonnet-4-6" in perguntas[0] and "US$" in perguntas[0]
    assert criados == [{"chave": "sk-ant-teste", "modelo": "claude-sonnet-4-6", "idioma": "pt-BR"}]
    traduzida = filmes / "A (2001)" / "A (2001).pt-BR.srt"
    assert ler_srt(traduzida.read_text(encoding="utf-8"))[0].texto == "PT: Hello, how are you?"
    assert app.caixas[-1][1] == "Traduzir legendas" and "Traduzidas: 1 de 1" in app.caixas[-1][2]
    app.ao_traduzir_legendas()                                         # de novo: nada mais a fazer
    esperar(app)
    esperar(app)
    assert "Nada a traduzir" in app.caixas[-1][2]


def test_criar_legenda_pelo_audio_pela_janela(app, tmp_path, monkeypatch):
    from jellyfin_tools import transcricao
    from jellyfin_tools.traducao import Tradutor, ler_srt
    from tests.test_traducao import ClienteFalso
    from tests.test_transcricao import WhisperFalso
    filmes = tmp_path / "Filmes"
    for nome in ("Sem Legenda (2001)", "Com Legenda (2002)"):
        (filmes / nome).mkdir(parents=True)
        (filmes / nome / f"{nome}.mkv").write_bytes(b"\0" * 2_000_000)
    (filmes / "Com Legenda (2002)" / "Com Legenda (2002).en.srt").write_text("1\n00:00:01,000 --> 00:00:02,000\nx\n")
    app._destinos.update({"Filmes": str(filmes), "Séries": ""})
    app.var_jf_destino.set(str(filmes))
    assert app.MODELOS_WHISPER == transcricao.MODELOS                  # a janela e o motor com a mesma lista
    o = app.obter_opcoes_jellyfin()
    assert (o.modelo_whisper, o.whisper_gpu) == ("small", False)
    monkeypatch.setattr(app_moderna, "videos_sem_legenda",
                        lambda *p, **k: transcricao.videos_sem_legenda(*p, sondar_arquivo=lambda v: (3600.0, set()), **k))
    abertos = []
    monkeypatch.setattr(app_moderna, "Transcritor",
                        lambda **k: (abertos.append(k), transcricao.Transcritor(motor=WhisperFalso(), **k))[1])
    monkeypatch.setattr(app_moderna, "Tradutor", lambda **k: Tradutor(cliente=ClienteFalso(), **k))
    monkeypatch.setattr(app_moderna.automacao, "Tradutor", lambda **k: Tradutor(cliente=ClienteFalso(), **k))
    app.var_jf_chave_claude.set("sk-ant-teste")
    app.var_jf_modelo_whisper.set("medium")
    perguntas = []
    app.escolher = lambda t, m, opcoes, **k: (perguntas.append(m), opcoes[0])[1]
    app.bt_legendar_audio.invoke()
    esperar(app)
    esperar(app)
    assert "1 vídeo(s) sem nenhuma legenda (cerca de 1.0 h de áudio)" in perguntas[0]
    assert "Sem Legenda (2001).mkv" in perguntas[0] and "Com Legenda" not in perguntas[0]
    assert 'modelo "medium"' in perguntas[0] and "US$" in perguntas[0]
    assert abertos[0]["modelo"] == "medium" and abertos[0]["pasta_modelos"].endswith("modelos_whisper")
    pasta = filmes / "Sem Legenda (2001)"
    assert ler_srt((pasta / "Sem Legenda (2001).en.srt").read_text(encoding="utf-8"))[0].texto == "Hello, how are you?"
    assert ler_srt((pasta / "Sem Legenda (2001).pt-BR.srt").read_text(encoding="utf-8"))[0].texto.startswith("PT: ")
    assert app.caixas[-1][1] == "Criar legenda pelo áudio" and "traduzidas pelo Claude: 1" in app.caixas[-1][2]
    app.bt_legendar_audio.invoke()                                     # de novo: o vídeo já tem legenda
    esperar(app)
    esperar(app)
    assert "Nenhum vídeo sem legenda" in app.caixas[-1][2]



def test_dublar_filmes_pela_janela(app, tmp_path, monkeypatch):
    app.var_jf_dublagem_no_original.set(False)                   # este teste: o arquivo à parte
    from jellyfin_tools import dublagem
    from tests.test_dublagem import FFMPEG, SRT, VozFalsa, faixas, video_de_teste
    if not FFMPEG:
        pytest.skip("sem ffmpeg")
    filmes = tmp_path / "Filmes"
    (filmes / "Nosferatu (1922)").mkdir(parents=True)
    video = video_de_teste(filmes / "Nosferatu (1922)" / "Nosferatu (1922).mkv")
    (filmes / "Nosferatu (1922)" / "Nosferatu (1922).pt-BR.srt").write_text(SRT, encoding="utf-8")
    app._destinos.update({"Filmes": str(filmes), "Séries": ""})
    app.var_jf_destino.set(str(filmes))
    assert app.obter_opcoes_jellyfin().voz_dublagem == "faber" and app.VOZES_DUBLAGEM == tuple(dublagem.VOZES)
    preparados = []
    from videoscraper import automacao
    monkeypatch.setattr(automacao, "preparar_piper", lambda pasta, **k: preparados.append(pasta) or Path("piper"))
    monkeypatch.setattr(automacao, "preparar_voz", lambda voz, pasta, **k: preparados.append(voz) or Path("v.onnx"))
    voz = VozFalsa()
    monkeypatch.setattr(automacao, "MotorPiper", lambda exe, modelo: voz)
    app.var_jf_chave_claude.set("")                                    # sem a chave: falas longas só aceleram
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(app_moderna, "videos_para_dublar",
                        lambda *p, **k: dublagem.videos_para_dublar(*p, **{**k, "sondar": lambda v: (6.0, ["eng"])}))
    perguntas = []
    app.escolher = lambda t, m, opcoes, **k: (perguntas.append(m), opcoes[0])[1]
    app.bt_dublar.invoke()
    esperar(app)
    esperar(app)
    assert "1 filme(s) com legenda em português" in perguntas[0] and "Nosferatu (1922).mkv (2 falas)" in perguntas[0]
    assert "faber" in perguntas[0] and "O arquivo original não é tocado" in perguntas[0]
    assert preparados[1] == "faber" and str(preparados[0]).endswith("piper")
    dublado = filmes / "Nosferatu (1922)" / "Nosferatu (1922) - Dublado IA.mkv"
    assert dublado.is_file() and "(por)" in [l for l in faixas(dublado) if "Audio" in l][0]
    assert app.caixas[-1][1] == "Dublar filmes" and "Dublados: 1 de 1" in app.caixas[-1][2]
    app.bt_dublar.invoke()                                             # de novo: já tem a versão dublada
    esperar(app)
    esperar(app)
    assert "Nada para dublar" in app.caixas[-1][2]


def test_botao_testar_chaves_das_legendas(app, api_falsa, monkeypatch):
    from jellyfin_tools import ProvedorOpenSubtitles, ProvedorSubDL
    base = api_falsa.base
    monkeypatch.setattr(app_moderna, "ProvedorOpenSubtitles", lambda k: ProvedorOpenSubtitles(k, base_url=base + "/os"))
    monkeypatch.setattr(app_moderna, "ProvedorSubDL", lambda k: ProvedorSubDL(k, base_url=base + "/api/v1"))
    api_falsa.rotas["/os/subtitles"] = lambda q: (200, {"total_count": 7, "data": []})
    api_falsa.rotas["/api/v1/subtitles"] = lambda q: (403, {"status": False, "error": "invalid api key"})
    app.mostrar_aba(app.ABA_CONFIG)                                     # Configurações > Chaves de API
    app.mostrar_config("Chaves de API")
    app.var_jf_fonte.set("OpenSubtitles (API)")
    app._mostrar_campos_jf()
    app.update()
    assert app.bt_testar_legendas.winfo_ismapped()
    app.bt_testar_legendas.invoke()
    assert app.caixas[-1][:2] == ("aviso", "Legendas")                     # sem chaves: nem tenta
    app.var_jf_chave_os.set("os-boa")
    app.var_jf_chave_subdl.set("subdl-errada")
    app.bt_testar_legendas.invoke()
    esperar(app)
    estado = app.lb_estado_legendas.cget("text")
    assert estado == ("✓  OpenSubtitles: chave aceita (7 legenda(s) de teste encontradas)\n"
                      "✕  SubDL: SubDL recusou a chave da API")
    assert app.caixas[-1][0] == "erro"
    app.mostrar_config("Legendas")
    app.var_jf_fonte.set("Site de busca (URL)")
    app._mostrar_campos_jf()
    app.update()
    assert app.campo_url_site.winfo_ismapped()                          # site de busca: o endereço dele
    app.var_jf_fonte.set("Site de demonstração")
    app._mostrar_campos_jf()
    app.update()
    assert not app.campo_url_site.winfo_ismapped()                      # o site demo não precisa de nada


def test_conferir_espelhos_e_desfazer_pela_janela(app, tmp_path, api_falsa, monkeypatch):
    from jellyfin_tools import espelho
    api_falsa.rotas["/ok.mp4"] = lambda q: (206, b"x", {"Content-Type": "video/mp4", "Accept-Ranges": "bytes"})
    api_falsa.rotas["/sumiu.mp4"] = lambda q: (404, b"", {})
    filmes = tmp_path / "Filmes"
    for nome, url in (("Bom (2000)", "/ok.mp4"), ("Quebrado (2001)", "/sumiu.mp4")):
        (filmes / nome).mkdir(parents=True)
        (filmes / nome / f"{nome}.strm").write_text(api_falsa.base + url + "\n", encoding="utf-8")
    original = espelho.verificar_links
    monkeypatch.setattr(espelho, "verificar_links", lambda urls, **k: original(urls, **{**k, "respeitar_robots": False}))
    app.mostrar_aba("Jellyfin")
    app.var_jf_destino.set(str(filmes))
    perguntas = []
    app.perguntar = lambda t, m: (perguntas.append(t), True)[1]
    app.mostrar_aba("Jellyfin Espelhos")                                 # os espelhos têm aba própria
    painel = app.janela_espelhos
    arvore = painel.arvore

    def situacoes():
        return {arvore.item(i, "text").strip(): arvore.set(i, "situacao")
                for g in arvore.get_children() for i in arvore.get_children(g)}
    assert situacoes() == {"Bom (2000)": "não conferido", "Quebrado (2001)": "não conferido"}
    painel.bt_conferir.invoke()
    esperar(app)
    esperar(app)                                                         # a remoção oferecida no fim
    assert "Espelhos quebrados" in perguntas
    assert not (filmes / "Quebrado (2001)" / "Quebrado (2001).strm").exists()
    assert (filmes / "Bom (2000)" / "Bom (2000).strm").exists()
    app.update()
    assert list(situacoes()) == ["Bom (2000)"] and situacoes()["Bom (2000)"].startswith("funcionando")
    app.bt_desfazer.invoke()                                              # volta o removido
    esperar(app)
    assert (filmes / "Quebrado (2001)" / "Quebrado (2001).strm").exists()
    painel.bt_atualizar.invoke()
    assert situacoes()["Quebrado (2001)"].startswith("quebrado")         # a coluna Situação lembra o Conferir
    assert "1 quebrado(s)" in painel.lb_resumo.cget("text")


def test_vigia_organiza_sozinho_o_que_terminou(app, tmp_path):
    origem, filmes = tmp_path / "Downloads", tmp_path / "Filmes"
    origem.mkdir()
    for nome, idade in (("Matrix.1999.mkv", 3600), ("Cidade.de.Deus.2002.mkv", 5)):
        (origem / nome).write_bytes(b"v")
        os.utime(origem / nome, (time.time() - idade, time.time() - idade))
    app.mostrar_aba("Jellyfin")
    app.var_jf_origem.set(str(origem))
    app.var_jf_destino.set(str(filmes))
    app.var_jf_legendas.set(False)
    caixas_antes = len(app.caixas)
    app.var_jf_vigiar.set(True)
    app.ao_alternar_vigia()
    assert app._vigia_agendada and app.lb_estado_vigia.cget("text").startswith("Ligada: próxima conferência")
    fim = time.time() + 30
    while not (filmes / "Matrix (1999)" / "Matrix (1999).mkv").exists() and time.time() < fim:
        app.update()
        time.sleep(0.05)
    esperar(app)
    assert (filmes / "Matrix (1999)" / "Matrix (1999).mkv").exists()
    assert (origem / "Cidade.de.Deus.2002.mkv").exists()                  # ainda baixando: fica
    assert len(app.caixas) == caixas_antes                               # automático: nenhuma caixa
    assert "Organizando (pasta vigiada)" in app._menus_registro[1].cget("values")[0]
    app.var_jf_vigiar.set(False)
    app.ao_alternar_vigia()
    assert app._vigia_agendada is None and app.lb_estado_vigia.cget("text") == "Desligada."


def test_vigia_com_pastas_do_utorrent_separa_filmes_e_series(app, tmp_path):
    torrent = tmp_path / "uTorrent"
    for nome in ("Filmes/Matrix.1999.mkv", "Series/Dark.S01E02.mkv"):
        (torrent / nome).parent.mkdir(parents=True, exist_ok=True)
        (torrent / nome).write_bytes(b"v")
        os.utime(torrent / nome, (time.time() - 3600, time.time() - 3600))
    app.mostrar_aba("Jellyfin")
    app._destinos.update({"Filmes": str(tmp_path / "Jellyfin" / "Filmes"), "Séries": str(tmp_path / "Jellyfin" / "Series")})
    app.var_jf_destino.set(str(tmp_path / "Jellyfin" / "Filmes"))
    app.var_jf_origem.set(str(tmp_path / "outra"))                       # sem uso: há pastas vigiadas
    app.definir_pastas_vigiadas([str(torrent / "Filmes"), str(torrent / "Series")])
    assert app.obter_opcoes_jellyfin().pastas_vigiadas == (str(torrent / "Filmes"), str(torrent / "Series"))
    app.var_jf_vigia_no_lugar.set(False)                                  # do uTorrent PARA as bibliotecas
    app.var_jf_legendas.set(False)
    app.var_jf_vigiar.set(True)
    app.ao_alternar_vigia()
    esperado = [tmp_path / "Jellyfin/Filmes/Matrix (1999)/Matrix (1999).mkv",
                tmp_path / "Jellyfin/Series/Dark (2017)/Season 01/Dark S01E02.mkv"]
    fim = time.time() + 30
    while not all(p.exists() for p in esperado) and time.time() < fim:
        app.update()
        time.sleep(0.05)
    esperar(app)
    assert all(p.exists() for p in esperado)
    assert "1 filme(s) e 1 episódio(s)" in app.var_status.get()
    app.var_jf_vigiar.set(False)
    app.ao_alternar_vigia()
    app._salvar_config()                                                  # as pastas ficam lembradas
    from videoscraper import config
    assert config.carregar()["jellyfin"]["pastas_vigiadas"] == [str(torrent / "Filmes"), str(torrent / "Series")]


def test_espelho_pula_o_que_ja_esta_no_jellyfin(app, tmp_path, api_falsa, monkeypatch):
    from jellyfin_tools.espelho import Verificacao
    from test_espelho_jellyfin import _jellyfin_falso
    from videoscraper.extracao import LinkVideo
    _jellyfin_falso(api_falsa)
    monkeypatch.setattr(app_moderna, "verificar_links", lambda urls, **k: {u: Verificacao(True) for u in urls})
    base = "https://archive.org/download/x/"
    app._mostrar_links([LinkVideo(base + "n.mp4", "o", "archive.org", "Nosferatu (1922)", "Domínio público"),
                        LinkVideo(base + "m.mp4", "o", "archive.org", "Metropolis (1927)", "Domínio público")])
    app._destinos.update({"Filmes": str(tmp_path / "Filmes"), "Séries": str(tmp_path / "Series")})
    app.var_jf_destino.set(str(tmp_path / "Filmes"))
    app.var_jf_url.set(api_falsa.base)
    app.var_jf_chave_jellyfin.set("chave")
    app.var_jf_atualizar.set(False)
    app.var_jf_legendas.set(False)
    app.escolher = lambda t, m, opcoes: opcoes[0]
    app.ao_espelhar_jellyfin()
    esperar(app)
    assert [p.name for p in tmp_path.rglob("*.strm")] == ["Metropolis (1927).strm"]
    assert app.tabela.item("0", "values")[1].endswith("já no Jellyfin")
    assert "Já estavam no Jellyfin (pulados): 1" in app.caixas[-1][2]


def test_relatorio_pela_janela(app, tmp_path):
    filmes, series = tmp_path / "Filmes", tmp_path / "Series"
    for caminho in (filmes / "Matrix (1999)" / "Matrix (1999).mkv", series / "Dark (2017)" / "Season 02" / "Dark S02E01.mkv",
                    series / "Dark (2017)" / "Season 02" / "Dark S02E03.mkv"):
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_bytes(b"v")
    app.mostrar_aba("Jellyfin")
    app._destinos.update({"Filmes": str(filmes), "Séries": str(series)})
    app.var_jf_destino.set(str(filmes))
    app.bt_relatorio.invoke()
    esperar(app)
    linhas = [(l[1].split("  ")[-1], l[2], l[3]) for l in _linhas_jf(app)]
    assert ("falta legenda pt-BR", "Matrix (1999)", "Matrix (1999).mkv") in linhas
    assert ("falta pôster", "Matrix (1999)", "sem poster.jpg na pasta") in linhas
    assert ("falta episódios", "Dark (2017) S02", "E02") in linhas
    from videoscraper import config
    planilhas = list((config.ARQUIVO.parent / "relatorios").glob("relatorio-*.csv"))
    assert len(planilhas) == 1 and str(planilhas[0]) in app.caixas[-1][2]


def test_conferencia_automatica_dos_espelhos(app, tmp_path, api_falsa, monkeypatch):
    import json
    from jellyfin_tools import espelho
    api_falsa.rotas["/sumiu.mp4"] = lambda q: (404, b"", {})
    api_falsa.rotas["/discord"] = lambda q: (204, b"")
    original = espelho.verificar_links
    monkeypatch.setattr(espelho, "verificar_links", lambda urls, **k: original(urls, **{**k, "respeitar_robots": False}))
    monkeypatch.setattr(app, "PAUSA_APOS_TAREFA", 0)                     # sem esperar a janela ficar quieta
    filmes = tmp_path / "Filmes"
    (filmes / "Quebrado (2001)").mkdir(parents=True)
    (filmes / "Quebrado (2001)" / "Quebrado (2001).strm").write_text(api_falsa.base + "/sumiu.mp4\n", encoding="utf-8")
    app.mostrar_aba("Jellyfin")
    app.var_jf_destino.set(str(filmes))
    app.var_jf_discord.set(api_falsa.base + "/discord")
    app.campo_conferir_a_cada.set(12)
    app.var_jf_conferir_unidade.set("horas")
    caixas = len(app.caixas)
    app.var_jf_conferir_auto.set(True)
    app.ao_alternar_conferencia()                                        # nunca conferiu: confere já
    esperar(app)
    avisos = [json.loads(p["corpo"])["content"] for p in api_falsa.pedidos if p["caminho"] == "/discord"]
    assert len(avisos) == 1 and "Quebrado (2001)" in avisos[0]
    assert len(app.caixas) == caixas                                     # automático: nenhuma caixa
    assert app.var_jf_ultima_conferencia.get()
    assert "1 quebrado(s)" in app.lb_estado_conferencia.cget("text")
    from videoscraper import config
    salvo = config.carregar()["jellyfin"]
    assert (salvo["conferir_auto"], salvo["conferir_a_cada"], salvo["conferir_unidade"]) == (True, 12, "horas")
    app._verificar_conferencia()                                         # antes de 12 h: não confere de novo
    esperar(app)
    assert len([p for p in api_falsa.pedidos if p["caminho"] == "/discord"]) == 1
    assert "Próxima:" in app.lb_estado_conferencia.cget("text")
    # em minutos: 30 min depois da última, confere de novo
    from datetime import datetime, timedelta
    app.campo_conferir_a_cada.set(30)
    app.var_jf_conferir_unidade.set("minutos")
    app.var_jf_ultima_conferencia.set((datetime.now() - timedelta(minutes=31)).isoformat(timespec="seconds"))
    app._verificar_conferencia()
    esperar(app)
    assert len([p for p in api_falsa.pedidos if p["caminho"] == "/discord"]) == 2
    assert config.carregar()["jellyfin"]["conferir_unidade"] == "minutos"


def test_conferencia_automatica_nao_emenda_no_conferir_selecionados(app, monkeypatch):
    """"Só conferi 1, mas o sistema verificou todos os canais": era a conferência automática (espelhos + TODOS
    os canais) começando logo depois. Agora ela espera a janela TV ao vivo fechar e a janela ficar quieta."""
    import time as relogio
    from types import SimpleNamespace
    comecou = []
    monkeypatch.setattr(app, "_rodar", lambda status, tarefa: comecou.append(status))
    app.var_jf_conferir_auto.set(True)
    app.var_jf_ultima_conferencia.set("")                               # nunca conferiu: estaria na hora
    monkeypatch.setattr(app, "janela_canais", SimpleNamespace(winfo_exists=lambda: True))
    app._verificar_conferencia()
    assert not comecou and "espera a janela TV ao vivo fechar" in app.lb_estado_conferencia.cget("text")
    monkeypatch.setattr(app, "janela_canais", None)
    monkeypatch.setattr(app, "_fim_da_tarefa", relogio.monotonic())    # o "Conferir 1" acabou agora
    app._verificar_conferencia()
    assert not comecou
    app.var_jf_conferir_auto.set(False)


def test_espelhos_remover_qualquer_espelhamento_pela_janela(app, tmp_path, api_falsa):
    from test_espelho_jellyfin import _tres_espelhamentos
    filmes, series, temporada = _tres_espelhamentos(tmp_path)
    api_falsa.rotas["/Library/Refresh"] = lambda q: (204, b"")
    app.mostrar_aba("Jellyfin")
    app.var_jf_destino.set(str(filmes))
    app._destinos["Séries"] = str(series)
    app.var_jf_url.set(api_falsa.base)
    app.var_jf_chave_jellyfin.set("chave")
    perguntas = []
    app.perguntar = lambda t, m: perguntas.append(m) or True
    app.ao_gerenciar_espelhos()                                      # o atalho antigo leva à aba
    assert app.aba_atual() == "Jellyfin Espelhos"
    janela = app.janela_espelhos
    arvore = janela.arvore
    titulos = [arvore.item(g, "text") for g in arvore.get_children()]
    assert [t.split(" — ")[0] for t in titulos] == ["Espelhamento 1", "Espelhamento 2", "Espelhamento 3"]
    primeiro = arvore.get_children()[0]
    assert [arvore.item(i, "text").strip() for i in arvore.get_children(primeiro)] == ["Dark S01E02",
                                                                                        "Nosferatu (1922)"]
    assert [arvore.set(i, "biblioteca") for i in arvore.get_children(primeiro)] == ["Séries", "Filmes"]

    arvore.selection_set(primeiro)                                   # o 1º espelhamento inteiro
    janela.bt_remover.invoke()
    esperar(app)
    assert "Nosferatu (1922)" in perguntas[-1] and "Dark S01E02" in perguntas[-1]
    assert [arvore.item(g, "text").split(" — ")[0] for g in arvore.get_children()] == ["Espelhamento 2",
                                                                                      "Espelhamento 3"]
    assert not (filmes / "Nosferatu (1922)").exists()
    assert (temporada / "Dark S01E01.mkv").exists()
    assert any(p["caminho"] == "/Library/Refresh" for p in api_falsa.pedidos)   # Jellyfin avisado

    janela.var_busca.set("chíhiro")                                  # um filme específico (sem acento também)
    app.update()
    visiveis = [i for g in arvore.get_children() for i in arvore.get_children(g)]
    assert [arvore.item(i, "text").strip() for i in visiveis] == ["A Viagem de Chihiro (2001)"]
    arvore.selection_set(visiveis)
    janela.bt_remover.invoke()
    esperar(app)
    janela.var_busca.set("")
    app.update()
    assert [arvore.item(i, "text").strip() for g in arvore.get_children() for i in arvore.get_children(g)] == [
        "Metropolis (1927)", "Matrix (1999)"]

    janela.bt_desfazer.invoke()                                      # volta só a última remoção
    esperar(app)
    nomes = [arvore.item(i, "text").strip() for g in arvore.get_children() for i in arvore.get_children(g)]
    assert nomes == ["A Viagem de Chihiro (2001)", "Metropolis (1927)", "Matrix (1999)"]
    assert not (filmes / "Nosferatu (1922)").exists()


def test_caixas_de_selecao_nas_abas_de_tv_e_de_espelhos(app, tmp_path):
    """☐/☑ ao lado de cada linha (canais e espelhos): um clique marca/desmarca sem perder os outros; no espelhamento,
    marca todos os itens dele; "todos", "nenhum", "inverter", "os quebrados"/"os fora do ar". O nome não muda."""
    from test_espelho_jellyfin import _tres_espelhamentos
    from jellyfin_tools.tv_ao_vivo import Canal, Situacao
    filmes, series, _ = _tres_espelhamentos(tmp_path)
    app.mostrar_aba("Jellyfin")
    app.var_jf_destino.set(str(filmes))
    app._destinos["Séries"] = str(series)
    strm = sorted(str(p) for p in filmes.rglob("*.strm"))[0]
    app._situacao_espelhos = {strm: (False, "quebrado: HTTP 404")}
    app.mostrar_aba("Jellyfin Espelhos")
    painel = app.janela_espelhos
    arvore, caixas = painel.arvore, painel.caixas
    app.update()
    folhas = caixas.folhas()
    assert len(folhas) == 5 and all(str(arvore.item(i, "image")[0]) == str(caixas.vazia) for i in folhas)
    primeiro = arvore.get_children()[0]

    def clicar(iid):
        arvore.see(iid)
        app.update()
        x, y, largura, altura = arvore.bbox(iid, "#0")
        arvore.event_generate("<Button-1>", x=x + largura // 2, y=y + altura // 2)
        app.update()
    clicar(primeiro)                                                    # o espelhamento: os 2 itens dele
    assert set(painel.selecionados()) == set(arvore.get_children(primeiro))
    assert str(arvore.item(primeiro, "image")[0]) == str(caixas.cheia)
    clicar(arvore.get_children(arvore.get_children()[1])[0])            # mais um, sem perder os outros
    assert len(painel.selecionados()) == 3 and "3 selecionado(s)" in painel.lb_resumo.cget("text")
    painel.bt_inverter.invoke()
    assert len(painel.selecionados()) == 2
    painel.bt_selecionar_nenhum.invoke()
    assert painel.selecionados() == []
    painel.bt_selecionar_quebrados.invoke()
    assert [arvore.item(i, "text").strip() for i in painel.selecionados()] == [Path(strm).stem]
    painel.bt_selecionar_todos.invoke()
    assert len(painel.selecionados()) == 5
    # a lista de canais (aba Jellyfin TV)
    app.mostrar_aba("Jellyfin TV")
    tv = app.janela_canais
    app._canais = [Canal("TV Cultura", "https://a.org/1.m3u8"), Canal("Rádio", "https://b.net/r.mp3"),
                   Canal("TV Brasil", "https://a.org/2.m3u8")]
    app._situacao_canais = {app._canais[1].url: Situacao(False, "fora do ar (HTTP 404)")}
    app._mostrar_canais()
    app.update()
    assert [tv.tabela.item(i, "text") for i in tv.tabela.get_children()] == ["TV Cultura", "Rádio", "TV Brasil"]
    tv.caixas.marcar(["0"])
    tv.bt_inverter.invoke()
    assert tv.selecionados() == ["1", "2"] and str(tv.tabela.item("1", "image")[0]) == str(tv.caixas.cheia)
    assert tv.bt_conferir.cget("text") == "Conferir 2 selecionado(s)"
    tv.bt_selecionar_nenhum.invoke()
    assert tv.selecionados() == [] and tv.bt_conferir.cget("text") == "Conferir todos"
    tv.bt_selecionar_fora.invoke()
    assert tv.selecionados() == ["1"]


def test_espelhos_sem_selecao_avisa(app, tmp_path):
    from test_espelho_jellyfin import _tres_espelhamentos
    filmes, series, _ = _tres_espelhamentos(tmp_path)
    app.mostrar_aba("Jellyfin")
    app.var_jf_destino.set(str(filmes))
    app.ao_gerenciar_espelhos()
    app.janela_espelhos.bt_remover.invoke()
    assert app.caixas[-1][1] == "Nada selecionado"
    assert len(list(filmes.rglob("*.strm"))) == 4


def test_anime_numerado_no_modo_filmes_oferece_series_na_pasta_certa(app, tmp_path):
    """Caso real: origem e biblioteca = 'Series_Organizadas/Animes/Samurai X', modo Filmes, arquivos
    'Samurai X - 01 Dual Audio.avi'. Tem de perguntar e usar 'Animes' como biblioteca de Séries."""
    animes = tmp_path / "Series_Organizadas" / "Animes"
    pasta = animes / "Samurai X"
    pasta.mkdir(parents=True)
    for n in (1, 2, 3):
        (pasta / f"Samurai X - {n:02d} Dual Audio.avi").write_bytes(b"video")
    app.seletor_aba.set("Jellyfin")
    app.mostrar_aba("Jellyfin")
    app.var_jf_origem.set(str(pasta))
    app.var_jf_destino.set(str(pasta))
    perguntas = []
    app.perguntar = lambda t, m: (perguntas.append((t, m)), True)[1]       # "Continuar"
    app.bt_previa.invoke()
    esperar(app)
    esperar(app)                                                           # a 2ª prévia, já em Séries
    titulo, texto = perguntas[0]
    assert titulo == "Parece série" and "3 de 3" in texto and "numeração contínua" in texto
    assert f"Biblioteca de Séries: {animes}" in texto and "pasta da própria série" in texto
    assert app._modo_atual == "Séries" and app.var_jf_destino.get() == str(animes)
    assert sorted(l[3] for l in _linhas_jf(app)) == [f"Samurai X S01E0{n}.avi" for n in (1, 2, 3)]


def test_totais_nos_filtros_e_conferir_espelhos_com_filtro_desmarcado(app, tmp_path, api_falsa):
    app.mostrar_aba("Jellyfin")
    for i, categoria in enumerate(("mover", "nao_identificado", "nao_identificado", "ignorado")):
        app.adicionar_linha_jf(str(i), i + 1, categoria, None, f"a{i}.mkv", "", categoria=categoria)
    app.update()
    time.sleep(0.2)
    app.update()
    textos = {c: app.checks_filtro_jf[c].cget("text") for c in ("mover", "nao_identificado", "movido")}
    assert textos == {"mover": "Vai mover (1)", "nao_identificado": "Não identificado (2)", "movido": "Movido (0)"}
    for chave in ("mover", "movido", "organizado"):                 # como na imagem: só pendências
        app.vars_filtro_jf[chave].set(False)
    app.aplicar_filtro_jf()
    assert len(app.tabela_jf.get_children()) == 3

    api_falsa.rotas["/ok.mp4"] = lambda q: (206, b"x", {"Content-Type": "video/mp4", "Accept-Ranges": "bytes"})
    filmes = tmp_path / "Filmes"
    (filmes / "Bom (2000)").mkdir(parents=True)
    (filmes / "Bom (2000)" / "Bom (2000).strm").write_text(api_falsa.base + "/ok.mp4\n", encoding="utf-8")
    app.var_jf_destino.set(str(filmes))
    import jellyfin_tools.espelho as espelho
    original = espelho.verificar_links
    espelho.verificar_links = lambda urls, **k: original(urls, **{**k, "respeitar_robots": False})
    try:
        app.ao_conferir_espelhos()
        esperar(app)
    finally:
        espelho.verificar_links = original
    assert len(_linhas_jf(app)) == 3                                  # a tabela da aba Jellyfin não é trocada
    app.mostrar_aba("Jellyfin Espelhos")                              # o resultado fica na aba dos espelhos
    arvore = app.janela_espelhos.arvore
    itens = [i for g in arvore.get_children() for i in arvore.get_children(g)]
    assert len(itens) == 1 and arvore.set(itens[0], "situacao").startswith("funcionando")


def test_selecionar_todos_e_so_filmes_e_series_na_aba_videos(app):
    app.mostrar_aba("Vídeos")
    for i, tipo in enumerate(("Filme", "—", "Série")):
        app.adicionar_video(str(i), i + 1, "", f"Video {i}", "API", f"https://x/{i}.mp4", tipo)
    app.selecionar_filmes_e_series()
    app.update()
    assert app.selecionados() == ["0", "2"] and app.lb_selecao.cget("text") == "2 de 3 selecionado(s)"
    app.tabela.focus_force()
    app.update()
    app.tabela.event_generate("<Control-a>")                             # Ctrl+A na lista
    app.update()
    assert len(app.selecionados()) == 3
    app.limpar_selecao()
    app.update()
    assert app.lb_selecao.cget("text") == app.DICA_SELECAO               # nada selecionado: a dica
    app.bt_selecionar_todos.invoke()
    assert len(app.selecionados()) == 3


def test_botao_abrir_relatorio(app, tmp_path):
    abertos, perguntas = [], []
    app._abrir_no_sistema = abertos.append
    app.perguntar = lambda t, m: perguntas.append(m) or True              # "Gerar agora?" -> sim
    series = tmp_path / "Series"
    (series / "Dark (2017)" / "Season 01").mkdir(parents=True)
    (series / "Dark (2017)" / "Season 01" / "Dark S01E02.mkv").write_bytes(b"v")
    app.mostrar_aba("Jellyfin")
    app._destinos.update({"Séries": str(series)})
    app.var_jf_destino.set(str(series))
    app.bt_abrir_relatorio.invoke()                                      # nenhum ainda: oferece gerar
    esperar(app)
    assert "Ainda não há relatório" in perguntas[0] and not abertos
    assert "Abrir relatório" in app.caixas[-1][2]
    app.bt_abrir_relatorio.invoke()                                      # agora abre a planilha
    assert len(abertos) == 1 and abertos[0].endswith(".csv") and abertos[0] == str(app.ultimo_relatorio())


def test_pastas_protegidas_pela_janela(app, tmp_path):
    origem = tmp_path / "Downloads"
    sonarr = origem / "Sonarr"
    sonarr.mkdir(parents=True)
    (sonarr / "Dark.S01E02.mkv").write_bytes(b"v")
    (origem / "Matrix.1999.mkv").write_bytes(b"v")
    app.mostrar_aba("Jellyfin")
    app.var_jf_origem.set(str(origem))
    app.var_jf_destino.set(str(tmp_path / "Filmes"))
    app.definir_pastas_protegidas([str(sonarr)])
    app.bt_previa.invoke()
    esperar(app)
    assert [l[2] for l in _linhas_jf(app)] == ["Matrix.1999.mkv"]
    app._salvar_config()
    from videoscraper import config
    assert config.carregar()["jellyfin"]["pastas_protegidas"] == [str(sonarr)]


def test_corrigir_nome_pela_janela(app, tmp_path):
    """Não identificado -> 'Corrigir nome...' -> regra salva -> a prévia de novo já com o nome."""
    origem = tmp_path / "Downloads" / "Pasta Estranha"
    origem.mkdir(parents=True)
    for nome in ("Ep 14.mp4", "Ep 15.mp4"):
        (origem / nome).write_bytes(b"v")
    app.seletor_aba.set("Jellyfin")
    app.mostrar_aba("Jellyfin")
    app.seletor_modo.set("Séries")
    app._ao_trocar_modo("Séries")
    app.var_jf_origem.set(str(origem))
    app.var_jf_destino.set(str(tmp_path / "Series"))
    app.bt_previa.invoke()
    esperar(app)
    assert all("Pasta Estranha" in l[3] for l in _linhas_jf(app))          # sem regra: o nome da pasta
    pedidos = []
    app.pedir_nome = lambda tipo, sugestao, onde, atual="": (pedidos.append((tipo, sugestao, onde)),
                                                              {"titulo": "Breaking Bad", "ano": 2008, "temporada": 5})[1]
    app.tabela_jf.selection_set("0")
    app.bt_corrigir_nome.invoke()
    esperar(app)
    assert pedidos[0][0] == "serie" and str(origem) in pedidos[0][2]
    assert sorted(l[3] for l in _linhas_jf(app)) == ["Breaking Bad S05E14.mp4", "Breaking Bad S05E15.mp4"]
    from jellyfin_tools.regras import carregar_regras
    assert [r.descricao() for r in carregar_regras(app.arquivo_regras)] == ["Breaking Bad (2008), temporada 5"]
    app.pedir_nome = lambda *a, **k: {"esquecer": True}                   # "Esquecer a regra"
    app.tabela_jf.selection_set("0")
    app.bt_corrigir_nome.invoke()
    esperar(app)
    assert carregar_regras(app.arquivo_regras) == []


def test_resolver_conflitos_pela_janela(app, tmp_path):
    from test_conflitos import _video
    origem, filmes = tmp_path / "Downloads", tmp_path / "Filmes"
    _video(origem / "Matrix.1999.1080p.BluRay.mp4", 1080)
    _video(origem / "Matrix.1999.720p.WEB-DL.mp4", 720)
    app.mostrar_aba("Jellyfin")
    app.var_jf_origem.set(str(origem))
    app.var_jf_destino.set(str(filmes))
    app.bt_previa.invoke()
    esperar(app)
    assert sorted(l[1].split("  ")[-1] for l in _linhas_jf(app)) == ["conflito", "vai mover"]
    perguntas = []
    app.perguntar = lambda t, m: perguntas.append(m) or True
    app.bt_resolver_conflitos.invoke()
    for _ in range(4):                                  # compara -> confirma -> tira -> pré-visualiza de novo
        esperar(app)
    assert "fica: Matrix.1999.1080p.BluRay.mp4" in perguntas[-1] and "sai:  Matrix.1999.720p.WEB-DL.mp4" in perguntas[-1]
    assert not (origem / "Matrix.1999.720p.WEB-DL.mp4").exists()
    assert [l[1].split("  ")[-1] for l in _linhas_jf(app)] == ["vai mover"]   # a prévia nova, sem conflito


def test_aviso_de_versao_nova_uma_vez_por_versao(app, monkeypatch):
    from videoscraper import atualizacao
    nova = atualizacao.VersaoNova("v9.9", "https://github.com/x/releases/tag/v9.9", "Novidades")
    monkeypatch.setattr(atualizacao, "verificar", lambda *a, **k: nova)
    abertos, escolhas = [], []
    monkeypatch.setattr(app_moderna.webbrowser, "open", abertos.append)
    app.escolher = lambda t, m, opcoes, **k: (escolhas.append(m), opcoes[0])[1]
    app.verificar_versao_nova()
    for _ in range(40):
        app.update()
        time.sleep(0.05)
    assert len(escolhas) == 1 and "v9.9" in escolhas[0] and abertos == [nova.url]
    app.verificar_versao_nova()                                         # a mesma versão: não avisa de novo
    for _ in range(20):
        app.update()
        time.sleep(0.05)
    assert len(escolhas) == 1
    from videoscraper import config
    assert config.carregar()["jellyfin"]["versao_avisada"] == "v9.9"


def test_bandeja_fechar_e_iniciar_com_o_windows(app, monkeypatch):
    """X com "continuar perto do relógio": a janela some e o ícone aparece; "Abrir" e "Sair" no ícone."""
    from videoscraper import bandeja, inicializacao

    class IconeFalso:
        def __init__(self, dono):
            self.rodando = False
            icones.append(self)

        def run_detached(self):
            self.rodando = True

        def stop(self):
            self.rodando = False

    icones = []
    monkeypatch.setattr(bandeja, "disponivel", lambda: True)
    original = bandeja.Bandeja
    monkeypatch.setattr(app_moderna.bandeja, "Bandeja",
                        lambda pedir, titulo: original(pedir, titulo, fabrica=IconeFalso))
    app.var_jf_fechar_bandeja.set(True)
    app.fechar()                                                       # o X
    app.update()
    assert app.state() == "withdrawn" and icones[-1].rodando
    app._bandeja.pedir("abrir")                                        # clique em "Abrir" (vem pela fila)
    for _ in range(5):
        app.update()
        time.sleep(0.05)
    assert app.state() == "normal" and not icones[-1].rodando

    registro = {}

    class RegistroFalso:                                               # winreg de mentira
        HKEY_CURRENT_USER, REG_SZ = 1, 1

        class _Chave:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

        def CreateKey(self, *a):
            return self._Chave()

        OpenKey = CreateKey

        def SetValueEx(self, chave, nome, _, tipo, valor):
            registro[nome] = valor

        def DeleteValue(self, chave, nome):
            registro.pop(nome)

        def QueryValueEx(self, chave, nome):
            if nome not in registro:
                raise FileNotFoundError(nome)
            return registro[nome], 1

    falso = RegistroFalso()
    monkeypatch.setattr(inicializacao, "_registro", lambda: falso)
    app.var_jf_fechar_bandeja.set(False)
    app.var_jf_iniciar_windows.set(True)
    app.ao_alternar_inicializacao()
    assert registro["videoscraper"].endswith("--minimizado") and "iniciar.py" in registro["videoscraper"]
    assert app.var_jf_fechar_bandeja.get() and inicializacao.ativo()
    app.var_jf_iniciar_windows.set(False)
    app.ao_alternar_inicializacao()
    assert registro == {} and not inicializacao.ativo()


def test_tv_ao_vivo_pela_janela(app, tmp_path, api_falsa):
    """Adicionar, importar lista, conferir e enviar ao Jellyfin (servidor falso)."""
    import json
    api_falsa.rotas["/cultura.m3u8"] = lambda q: (200, b"#EXTM3U\n", {"Content-Type": "application/x-mpegURL"})
    api_falsa.rotas["/lista.m3u"] = lambda q: (200, f"#EXTM3U\n#EXTINF:-1 group-title=\"Abertos\",Rádio\n"
                                                     f"{api_falsa.base}/radio.mp3\n".encode(), {"Content-Type": "audio/x-mpegurl"})
    api_falsa.rotas["/radio.mp3"] = lambda q: (404, b"", {})
    tuners = []
    api_falsa.rotas["/System/Configuration/livetv"] = lambda q: (200, {"TunerHosts": tuners, "ListingProviders": []})
    api_falsa.rotas["/LiveTv/TunerHosts"] = lambda q: (tuners.append(json.loads(api_falsa.pedidos[-1]["corpo"])),
                                                       (200, tuners[-1]))[1]
    api_falsa.rotas["/ScheduledTasks"] = lambda q: (200, [])
    app.mostrar_aba("Jellyfin")
    app.var_jf_url.set(api_falsa.base)
    app.var_jf_chave_jellyfin.set("chave")
    app.mostrar_aba("Jellyfin TV")
    janela = app.janela_canais
    janela.var_nome.set("TV Cultura")
    janela.var_link.set(api_falsa.base + "/cultura.m3u8")
    app._adicionar_canal()
    janela.var_link.set(api_falsa.base + "/lista.m3u")                      # uma LISTA: importa todos
    app._adicionar_canal()
    esperar(app)
    assert [janela.tabela.item(i, "text") for i in janela.tabela.get_children()] == ["TV Cultura", "Rádio"]
    app._conferir_canais()
    esperar(app)
    situacoes = [janela.tabela.set(i, "situacao") for i in janela.tabela.get_children()]
    assert situacoes[0] == "no ar" and "HTTP 404" in situacoes[1]
    assert "1 fora do ar" in janela.lb_resumo.cget("text")
    janela.var_pasta.set(str(tmp_path / "TV"))
    app._publicar_canais()
    esperar(app)
    assert (tmp_path / "TV" / "canais.m3u").exists()
    assert [(t["Type"], t["Url"]) for t in tuners] == [("m3u", str(tmp_path / "TV" / "canais.m3u"))]
    assert "sintonizador M3U" in app.caixas[-1][2]
    from jellyfin_tools.tv_ao_vivo import carregar_canais
    assert len(carregar_canais(app.arquivo_canais)) == 2                    # a lista fica guardada


def test_tv_ao_vivo_selecionar_fora_do_ar_e_remover_todos(app, api_falsa):
    from jellyfin_tools.tv_ao_vivo import Canal
    api_falsa.rotas["/ok.m3u8"] = lambda q: (200, b"#EXTM3U\n", {"Content-Type": "application/x-mpegURL"})
    api_falsa.rotas["/pagina"] = lambda q: (200, b"<!DOCTYPE html><html><head></head></html>", {"Content-Type": "text/html"})
    app.mostrar_aba("Jellyfin")
    app.mostrar_aba("Jellyfin TV")
    janela = app.janela_canais
    janela.var_link.set(api_falsa.base + "/pagina")                    # uma página, não uma lista
    app._importar_canais_endereco()
    esperar(app)
    assert "não é uma lista de canais" in app.caixas[-1][2] and not app._canais
    app._juntar_canais([Canal("Bom", api_falsa.base + "/ok.m3u8"), Canal("Ruim 1", api_falsa.base + "/sumiu.m3u8"),
                        Canal("Ruim 2", api_falsa.base + "/pagina")])
    app._conferir_canais()
    esperar(app)
    janela.selecionar_fora_do_ar()
    assert [janela.tabela.item(i, "text") for i in janela.selecionados()] == ["Ruim 1", "Ruim 2"]
    app.perguntar = lambda t, m: True
    janela.bt_remover.invoke()
    assert [c.nome for c in app._canais] == ["Bom"]
    janela.selecionar_todos()
    assert len(janela.selecionados()) == 1
    janela.bt_remover_todos.invoke()
    assert app._canais == [] and janela.tabela.get_children() == ()


def test_botao_verificar_atualizacoes_em_tempo_real(app, monkeypatch, tmp_path, api_falsa):
    from videoscraper import atualizacao
    api_falsa.rotas["/zip"] = lambda q: (200, b"PK" + b"x" * 1000, {"Content-Type": "application/zip"})

    def esperar_fila(vezes=40):
        for _ in range(vezes):
            app.update()
            time.sleep(0.05)

    monkeypatch.setattr(atualizacao, "versao_atual", lambda: "v1.5.1")
    mesma = atualizacao.VersaoNova("v1.5.1", "https://github.com/x/v1.5.1")
    monkeypatch.setattr(atualizacao, "ultima_versao", lambda *a, **k: mesma)
    app.bt_atualizacoes.invoke()
    esperar_fila()
    assert app.caixas[-1][1:] == ("Verificar atualizações", "Você já está na versão mais nova (v1.5.1).")
    nova = atualizacao.VersaoNova("v1.6", "https://github.com/x/v1.6", "", api_falsa.base + "/zip",
                                  "videoscraper-windows.zip")
    monkeypatch.setattr(atualizacao, "ultima_versao", lambda *a, **k: nova)
    monkeypatch.setattr(atualizacao, "pasta_downloads", lambda: tmp_path)
    escolhas, abertos = [], []
    app.escolher = lambda t, m, opcoes, **k: (escolhas.append((t, opcoes)), opcoes[0])[1]
    app._abrir_no_sistema = abertos.append
    app.bt_atualizacoes.invoke()
    esperar_fila()
    esperar(app)
    esperar_fila(10)
    assert escolhas[0] == ("Versão nova", ("Baixar agora", "Abrir a página de download"))
    assert (tmp_path / "videoscraper-windows-v1.6.zip").exists()
    assert escolhas[-1][0] == "Atualização baixada" and abertos == [str(tmp_path)]
    def sem_internet(*a, **k):
        raise atualizacao.ErroAtualizacao("sem conexão com o GitHub (ConnectionError)")
    monkeypatch.setattr(atualizacao, "ultima_versao", sem_internet)
    app.bt_atualizacoes.invoke()
    esperar_fila()
    assert "sem conexão" in app.caixas[-1][2] and app.bt_atualizacoes.cget("state") == "normal"


def test_atualizacao_baixada_avisa_que_precisa_fechar(app, monkeypatch, tmp_path):
    from videoscraper import atualizacao
    nova = atualizacao.VersaoNova("v1.6", "https://github.com/x/v1.6")
    arquivo = tmp_path / "videoscraper-windows-v1.6.zip"
    monkeypatch.setattr(atualizacao, "pode_instalar_sozinho", lambda: True)
    instalados, mensagens = [], []
    monkeypatch.setattr(atualizacao, "instalar_ao_fechar", lambda z, reabrir=True: instalados.append((z, reabrir)))
    app.escolher = lambda t, m, opcoes, **k: (mensagens.append((t, m, opcoes)), "Atualizar quando eu fechar")[1]
    app._atualizacao_baixada(nova, arquivo)
    titulo, texto, opcoes = mensagens[-1]
    assert titulo == "Atualização pronta para instalar" and "PRECISA SER FECHADO" in texto
    assert opcoes == ("Atualizar e reiniciar agora", "Atualizar quando eu fechar")
    assert not instalados                                               # ainda não: só quando fechar
    destruida = []
    monkeypatch.setattr(app, "destroy", lambda: destruida.append(True))
    app.fechar()
    assert instalados == [(arquivo, False)] and destruida
    vars(app).pop("destroy", None)          # no fim do teste o app fecha de verdade (senão fica uma 2ª janela Tk)


def test_aba_jellyfin_tv_com_a_tv_ao_vivo_e_o_servidor(app):
    """A TV ao vivo virou a aba "Jellyfin TV" (entre Jellyfin e Avulsos): a lista de canais, o guia, a antena, a pasta
    e o servidor do Jellyfin (endereço e chave: as MESMAS opções de Configurações > Jellyfin). O botão "TV ao
    vivo..." saiu da aba Jellyfin."""
    assert not hasattr(app, "bt_tv_ao_vivo") and app.janela_canais is None       # monta na 1ª vez que abre
    app.ao_tv_ao_vivo()                                                # o atalho antigo leva à aba
    assert app.aba_atual() == "Jellyfin TV" and app.lb_titulo.cget("text") == "TV ao vivo no Jellyfin"
    painel = app.janela_canais
    app.update()
    assert painel.winfo_ismapped() and painel.master is app.aba_tv
    # as MESMAS opções de Configurações > Jellyfin (o campo mostra a variável da tela; o texto do campo não é
    # conferido: com outra janela Tk de um teste anterior ainda aberta, as variáveis ficam nela)
    assert painel.campo_url_jellyfin.cget("textvariable") is app.var_jf_url
    assert painel.campo_chave_jellyfin.cget("textvariable") is app.var_jf_chave_jellyfin
    assert painel.campo_chave_jellyfin.cget("show") == "•"
    painel.var_antena.set("192.168.0.50")
    app._guardar_opcoes_tv()
    from videoscraper import config
    assert config.carregar()["tv"]["antena"] == "192.168.0.50"
    app.mostrar_aba("Avulsos")
    app.mostrar_aba("Jellyfin TV")
    assert app.janela_canais is painel                                 # o mesmo painel (não monta de novo)


def test_tv_ao_vivo_filtro_por_coluna(app):
    """Clique no título da coluna: escolher um ou vários valores (Situação, Grupo, Link pelo site)."""
    from jellyfin_tools.tv_ao_vivo import Canal, Situacao
    app.mostrar_aba("Jellyfin")
    app.mostrar_aba("Jellyfin TV")
    janela = app.janela_canais
    app._canais = [Canal("TV Cultura", "https://a.org/1.m3u8", "Abertos"), Canal("TV Brasil", "https://a.org/2.m3u8", "Abertos"),
                   Canal("Rádio", "https://b.net/r.mp3", "Rádios"), Canal("Velho", "https://b.net/v.m3u8", "Abertos"),
                   Canal("Novo", "https://c.com/n.m3u8")]
    app._situacao_canais = {app._canais[0].url: Situacao(True, "no ar"), app._canais[1].url: Situacao(True, "no ar"),
                            app._canais[2].url: Situacao(False, "fora do ar (HTTP 404)"),
                            app._canais[3].url: Situacao(False, "é uma página, não o sinal do canal")}
    app._mostrar_canais()
    nomes = lambda: [janela.tabela.item(i, "text") for i in janela.tabela.get_children()]   # noqa: E731
    assert janela.valores_da_coluna("situacao") == [("(não conferido)", 1), ("é uma página, não o sinal do canal", 1),
                                                    ("fora do ar (HTTP 404)", 1), ("no ar", 2)]
    janela.aplicar_filtro("situacao", ["fora do ar (HTTP 404)", "é uma página, não o sinal do canal"])   # duas situações
    assert nomes() == ["Rádio", "Velho"] and len(janela.selecionados()) == 2
    assert "2 de 5" in janela.lb_resumo.cget("text") and "(filtro)" in janela.tabela.heading("situacao", "text")
    janela.aplicar_filtro("grupo", ["Abertos"])                         # mais uma coluna: as duas valem juntas
    assert nomes() == ["Velho"]
    janela.limpar_filtros()
    janela.aplicar_filtro("url", ["a.org"])                             # o link conta pelo site
    assert nomes() == ["TV Cultura", "TV Brasil"]
    app.perguntar = lambda t, m: True
    janela.bt_remover.invoke()                                          # remove os filtrados (selecionados)
    assert [c.nome for c in app._canais] == ["Rádio", "Velho", "Novo"]
    janela.limpar_filtros()
    janela.abrir_filtro("grupo")                                        # a janelinha: digitar e/ou marcar
    app.update()
    assert janela._janela_filtro.winfo_exists()
    texto, marcados, aplicar = janela._filtro_aberto
    texto.set("RADI")                                                   # digitou (sem acento e maiúsculas valem)
    aplicar()
    assert nomes() == ["Rádio"] and not janela._janela_filtro.winfo_exists()
    janela.abrir_filtro("grupo")
    texto, marcados, aplicar = janela._filtro_aberto
    assert marcados == {"Rádios"}                                       # lembra o filtro de antes
    marcados.update({"Abertos"})                                        # marcou mais um (sem digitar nada)
    aplicar()
    assert nomes() == ["Rádio", "Velho"]
    janela.limpar_filtros()
    janela.abrir_filtro("#0")
    janela._filtro_aberto[0].set("zzz")                                 # nada contém isso: nenhum canal
    janela._filtro_aberto[2]()
    assert nomes() == [] and "0 de 3" in janela.lb_resumo.cget("text")
    janela.limpar_filtros()
    janela.aplicar_filtro("grupo", ["(sem grupo)", "Abertos", "Rádios"])   # todos marcados = sem filtro
    assert len(nomes()) == 3 and "filtro" not in janela.lb_resumo.cget("text")


def test_parar_a_conferencia_de_canais_e_imediato(app, api_falsa):
    """Caso real: 11.393 canais e o Parar seguia consultando. Agora volta em ~1 s, com o que já conferiu."""
    from jellyfin_tools.tv_ao_vivo import Canal

    def devagar(q):
        time.sleep(0.5)
        return 200, b"#EXTM3U\n", {"Content-Type": "application/x-mpegURL"}
    api_falsa.rotas["/lento.m3u8"] = devagar
    app.mostrar_aba("Jellyfin")
    app.mostrar_aba("Jellyfin TV")
    app._canais = [Canal(f"C{n}", f"{api_falsa.base}/lento.m3u8?n={n}") for n in range(400)]
    app._conferir_canais()
    fim = time.time() + 15                                               # espera a condição (máquina ocupada)
    while time.time() < fim and "/s" not in app.var_status.get():
        app.update()
        time.sleep(0.05)
    assert "/s" in app.var_status.get()                                  # mostra a velocidade
    parou_em = time.time()
    app.ao_parar()
    esperar(app)
    assert time.time() - parou_em < 2.5                                 # antes: ~400 x 0,5 s / 8 = 25 s
    assert "Parado:" in app.var_status.get() and " de 400 conferidos" in app.var_status.get()


def test_parar_a_previsualizacao_e_imediato(app, tmp_path, monkeypatch):
    from jellyfin_tools import organizador
    origem = tmp_path / "Downloads"
    origem.mkdir()
    for n in range(300):
        (origem / f"Filme Numero {n} ({1900 + n % 120}).mkv").write_bytes(b"v")
    original = organizador.planejar
    monkeypatch.setattr(organizador, "planejar", lambda *a, **k: (time.sleep(0.02), original(*a, **k))[1])
    app.mostrar_aba("Jellyfin")
    app.var_jf_origem.set(str(origem))
    app.var_jf_destino.set(str(tmp_path / "Filmes"))
    app.bt_previa.invoke()
    fim = time.time() + 0.6
    while time.time() < fim:
        app.update()
        time.sleep(0.05)
    parou_em = time.time()
    app.ao_parar()
    esperar(app)
    assert time.time() - parou_em < 2                                   # antes: os 300 arquivos (~6 s)
    assert "Pré-visualização parada" in app.var_status.get()
    assert 0 < len(_linhas_jf(app)) < 300 and app.bt_organizar.cget("state") == "disabled"


def test_tv_ao_vivo_exportar_o_que_esta_na_tabela(app, tmp_path, monkeypatch):
    import json
    from jellyfin_tools.tv_ao_vivo import Canal, Situacao
    app.mostrar_aba("Jellyfin")
    app.mostrar_aba("Jellyfin TV")
    janela = app.janela_canais
    app._canais = [Canal("TV Cultura", "https://a.org/1.m3u8", "Abertos"), Canal("Rádio", "https://b.net/r.mp3", "Rádios")]
    app._situacao_canais = {app._canais[1].url: Situacao(False, "fora do ar (HTTP 404)")}
    app._mostrar_canais()
    assert janela.exportar(tmp_path / "todos.json") == 2
    dados = json.loads((tmp_path / "todos.json").read_text(encoding="utf-8"))
    assert dados[0] == {"numero": "", "canal": "TV Cultura", "grupo": "Abertos", "idioma": "", "programacao": "",
                        "situacao": "", "no_ar": None, "historico": "", "link": "https://a.org/1.m3u8"}
    janela.aplicar_filtro("grupo", ["Rádios"])                          # com filtro: só os filtrados
    from videoscraper import gui_moderna
    monkeypatch.setattr(gui_moderna.filedialog, "asksaveasfilename", lambda **k: str(tmp_path / "filtrados.csv"))
    janela.bt_exportar.invoke()
    linhas = (tmp_path / "filtrados.csv").read_text(encoding="utf-8-sig").splitlines()
    assert len(linhas) == 2 and linhas[1].startswith(";Rádio;Rádios;;;fora do ar (HTTP 404);não;")
    assert "1 canal(is) (só os do filtro)" in app.caixas[-1][2]


def test_conferencia_grande_nao_enche_o_console(app):
    from jellyfin_tools.tv_ao_vivo import Canal, Situacao
    linhas = []
    app._log.addHandler(type("H", (logging.Handler,), {"emit": lambda self, r: linhas.append(r)})(logging.INFO))
    poucos = [(Canal(f"C{n}", f"http://x/{n}"), Situacao(True, "no ar")) for n in range(3)]
    app._registrar_canais(poucos)
    assert len(linhas) == 3
    linhas.clear()
    app._registrar_canais(poucos * 200)                                  # 600 canais: um resumo só no console
    assert len(linhas) == 1 and "600 canais conferidos" in linhas[0].getMessage()


def test_conferir_so_os_canais_selecionados(app, api_falsa):
    """Antes "Conferir" lia a lista inteira mesmo com uma faixa selecionada."""
    from jellyfin_tools.tv_ao_vivo import Canal, Situacao
    api_falsa.rotas["/ok.m3u8"] = lambda q: (200, b"#EXTM3U\n", {"Content-Type": "text/html"})
    app.mostrar_aba("Jellyfin")
    app.mostrar_aba("Jellyfin TV")
    janela = app.janela_canais
    app._canais = [Canal(f"C{n}", f"{api_falsa.base}/ok.m3u8?n={n}") for n in range(10)]
    app._situacao_canais = {app._canais[0].url: Situacao(False, "fora do ar (HTTP 404)")}
    app._mostrar_canais()
    assert janela.bt_conferir.cget("text") == "Conferir todos"
    janela.tabela.selection_set(["3", "4", "5"])
    app.update()
    assert janela.bt_conferir.cget("text") == "Conferir 3 selecionado(s)"
    antes = len(api_falsa.pedidos)
    janela.bt_conferir.invoke()
    esperar(app)
    assert len(api_falsa.pedidos) - antes == 3                          # só os 3 selecionados
    assert {c.nome for c in app._canais if app._situacao_canais.get(c.url, Situacao(False)).ok} == {"C3", "C4", "C5"}
    assert app._situacao_canais[app._canais[0].url].detalhe == "fora do ar (HTTP 404)"   # os outros ficam como estavam
    assert set(janela.selecionados()) == {"3", "4", "5"}                # a seleção continua


def test_enviar_lista_vazia_pergunta_e_tira_do_jellyfin(app, tmp_path):
    from jellyfin_tools.tv_ao_vivo import Canal
    app.mostrar_aba("Jellyfin")
    app.mostrar_aba("Jellyfin TV")
    janela = app.janela_canais
    janela.var_pasta.set(str(tmp_path / "TV"))
    app._juntar_canais([Canal("TV Cultura", "https://a.org/1.m3u8")])
    app._publicar_canais()
    esperar(app)
    assert (tmp_path / "TV" / "canais.m3u").read_text(encoding="utf-8").count("#EXTINF") == 1
    janela.bt_remover_todos.invoke()
    perguntas = []
    app.perguntar = lambda t, m: (perguntas.append(m), False)[1]          # respondeu "não"
    app._publicar_canais()
    esperar(app)
    assert "TIRA do Jellyfin" in perguntas[-1]
    assert (tmp_path / "TV" / "canais.m3u").read_text(encoding="utf-8").count("#EXTINF") == 1   # nada mudou
    app.perguntar = lambda t, m: True                                     # agora "sim"
    app._publicar_canais()
    esperar(app)
    assert "#EXTINF" not in (tmp_path / "TV" / "canais.m3u").read_text(encoding="utf-8")
    assert "1 canal(is) saíram da lista" in app.caixas[-1][2]


def _abrir_tv(app, canais):
    app.mostrar_aba("Jellyfin")
    app.mostrar_aba("Jellyfin TV")
    app._canais = list(canais)
    app._guardar_canais()
    return app.janela_canais


def test_tv_desfazer_remocao_volta_cada_canal_para_o_lugar(app):
    from jellyfin_tools.tv_ao_vivo import Canal
    janela = _abrir_tv(app, [Canal(f"C{n}", f"https://a.org/{n}.m3u8") for n in range(5)])
    assert janela.bt_desfazer.cget("state") == "disabled"                 # nada para desfazer ainda
    janela.tabela.selection_set(["1", "3"])
    janela.bt_remover.invoke()
    assert [c.nome for c in app._canais] == ["C0", "C2", "C4"]
    janela.bt_remover_todos.invoke()
    assert app._canais == [] and janela.bt_desfazer.cget("state") == "normal"
    janela.bt_desfazer.invoke()                                         # desfaz o "Remover todos"
    assert [c.nome for c in app._canais] == ["C0", "C2", "C4"]
    janela.bt_desfazer.invoke()                                         # e a remoção de antes
    assert [c.nome for c in app._canais] == ["C0", "C1", "C2", "C3", "C4"]
    assert "2 canal(is) voltaram" in app.caixas[-1][2]
    assert janela.bt_desfazer.cget("state") == "disabled"                 # nada mais para desfazer
    app._desfazer_remocao_canais()
    assert "Não há remoção" in app.caixas[-1][2]


def test_tv_selecionar_repetidos_deixa_um_de_cada(app):
    from jellyfin_tools.tv_ao_vivo import Canal, Situacao
    janela = _abrir_tv(app, [Canal("TV Cultura (720p)", "https://a.org/1.m3u8"), Canal("Band", "https://a.org/2.m3u8"),
                             Canal("TV Cultura HD", "https://b.org/1.m3u8"), Canal("tv cultura", "https://c.org/1.m3u8")])
    app._situacao_canais = {"https://b.org/1.m3u8": Situacao(True, "no ar")}
    app._mostrar_canais()
    assert janela.selecionar_duplicados() == 2
    assert sorted(janela.selecionados()) == ["0", "3"]                 # fica a cópia que está no ar (a 2)
    app._canais = [Canal("A", "https://a.org/a"), Canal("B", "https://a.org/b")]
    app._mostrar_canais()
    assert janela.selecionar_duplicados() == 0 and "Nenhum canal repetido" in app.caixas[-1][2]


def test_tv_historico_das_conferencias_e_os_que_sempre_falham(app):
    from jellyfin_tools.tv_ao_vivo import Canal, Situacao, carregar_historico
    canais = [Canal("Sempre", "https://a.org/1"), Canal("Às vezes", "https://a.org/2"), Canal("Morto", "https://a.org/3")]
    janela = _abrir_tv(app, canais)
    for rodada in range(3):
        app._tratar_mensagem("canais_conferidos", [(canais[0], Situacao(True, "no ar")),
                                                   (canais[1], Situacao(rodada == 1, "fora do ar (HTTP 404)")),
                                                   (canais[2], Situacao(False, "sem resposta"))])
    ultimas = {janela.tabela.item(i, "text"): janela.tabela.set(i, "historico") for i in janela.tabela.get_children()}
    assert ultimas == {"Sempre": "✓✓✓  sempre no ar", "Às vezes": "✕✓✕  2 de 3 falharam",
                       "Morto": "✕✕✕  3 de 3 falharam"}
    assert janela.selecionar_mortos() == 1 and janela.selecionados() == ["2"]   # o "Not 24/7" não entra
    assert carregar_historico(app.arquivo_historico_canais)["https://a.org/2"] == [False, True, False]
    assert janela.valores_da_coluna("historico")[-1] == ("sempre no ar", 1)


def test_tv_editar_canal_com_duplo_clique(app, monkeypatch):
    from jellyfin_tools.tv_ao_vivo import Canal, Situacao, ler_m3u
    janela = _abrir_tv(app, [Canal("Cultura", "https://a.org/1.m3u8"), Canal("Band", "https://a.org/2.m3u8")])
    app._situacao_canais = {"https://a.org/1.m3u8": Situacao(False, "fora do ar (HTTP 404)")}
    pedidos = []
    monkeypatch.setattr(app, "_pedir_dados_canal", lambda dados: (pedidos.append(dados), {
        **dados, "nome": "TV Cultura", "numero": "2", "grupo": "Abertos", "url": "https://novo.org/c.m3u8"})[1])
    app.update()
    janela.tabela.see("0")
    x, y, _, _ = janela.tabela.bbox("0", "#0")
    from types import SimpleNamespace
    janela._ao_duplo_clique(SimpleNamespace(x=x + 10, y=y + 5), app._editar_canal)   # o duplo clique na linha
    assert pedidos and pedidos[0]["nome"] == "Cultura"
    assert app._canais[0] == Canal("TV Cultura", "https://novo.org/c.m3u8", "Abertos", numero="2")
    assert "https://a.org/1.m3u8" not in app._situacao_canais          # outro link: situação antiga sai
    assert janela.tabela.set("0", "numero") == "2"
    monkeypatch.setattr(app, "_pedir_dados_canal", lambda dados: {**dados, "url": "https://a.org/2.m3u8"})
    app._editar_canal("0")                                              # link de outro canal: recusa
    assert "já está em outro canal" in app.caixas[-1][2] and app._canais[0].url == "https://novo.org/c.m3u8"
    monkeypatch.setattr(app, "_pedir_dados_canal", lambda dados: {**dados, "numero": "dois"})
    app._editar_canal("0")
    assert "precisa ser um número" in app.caixas[-1][2]
    from videoscraper.gui_moderna import DialogoCanal
    dialogo = DialogoCanal(janela, {"nome": "X", "url": "https://x"})   # a janelinha abre e devolve
    dialogo.vars["numero"].set("7")
    dialogo._salvar()
    assert dialogo.resultado["numero"] == "7" and dialogo.resultado["nome"] == "X"
    from jellyfin_tools.tv_ao_vivo import gerar_m3u
    assert ler_m3u(gerar_m3u(app._canais))[0].numero == "2"                 # o número vai no tvg-chno



def test_tv_botao_editar_um_ou_varios_canais(app, monkeypatch):
    from jellyfin_tools.tv_ao_vivo import Canal
    janela = _abrir_tv(app, [Canal("Cultura", "https://a.org/1", "Abertos"), Canal("Band", "https://a.org/2", "Abertos"),
                             Canal("CNN", "https://a.org/3", "Notícias", idioma="English")])
    janela.tabela.selection_set([])
    janela.bt_editar.invoke()                                          # nada selecionado: explica
    assert "Selecione na lista" in app.caixas[-1][2]
    pedidos = []
    monkeypatch.setattr(app, "_pedir_dados_canal", lambda dados, *a, **k: (pedidos.append((dados, a)), {
        **dados, "nome": "TV Cultura", "url": "https://novo.org/1"})[1])
    janela.tabela.selection_set(["0"])
    janela.bt_editar.invoke()                                          # um: o diálogo completo
    assert pedidos[-1][0]["nome"] == "Cultura" and pedidos[-1][1] == ()
    assert app._canais[0].nome == "TV Cultura" and app._canais[0].url == "https://novo.org/1"
    monkeypatch.setattr(app, "_pedir_dados_canal", lambda dados, *a, **k: (pedidos.append((dados, a)), {
        "grupo": "Religiosos", "idioma": "pt"})[1])
    janela.tabela.selection_set(["0", "1", "2"])
    janela.bt_editar.invoke()                                          # vários: só grupo e idioma
    dados, extras = pedidos[-1]
    assert dados == {"grupo": "", "idioma": ""} and extras[1] == ("grupo", "idioma")
    assert [(c.grupo, c.idioma) for c in app._canais] == [("Religiosos", "Português")] * 3
    assert [c.nome for c in app._canais] == ["TV Cultura", "Band", "CNN"]  # nome e link não mudam
    monkeypatch.setattr(app, "_pedir_dados_canal", lambda dados, *a, **k: {"grupo": "", "idioma": "English"})
    janela.tabela.selection_set(["1", "2"])
    janela.bt_editar.invoke()                                          # campo vazio = fica como está
    assert [(c.grupo, c.idioma) for c in app._canais[1:]] == [("Religiosos", "English")] * 2
    from videoscraper.gui_moderna import DialogoCanal
    dialogo = DialogoCanal(janela, {"grupo": "X"}, "Editar 2 canais", ("grupo", "idioma"), "vale para todos")
    assert set(dialogo.vars) == {"grupo", "idioma"}
    dialogo._salvar()
    assert dialogo.resultado == {"grupo": "X", "idioma": ""}


def test_tv_programacao_monta_o_channels_xml_e_liga_o_coletor(app, monkeypatch, tmp_path):
    from jellyfin_tools import epg_iptv
    from jellyfin_tools.tv_ao_vivo import Canal
    janela = _abrir_tv(app, [Canal("Agro Mais", "https://a.org/1", id_guia="AgroMais.br"),
                             Canal("Nenhum", "https://a.org/2", idioma="Português")])
    janela.var_pasta.set(str(tmp_path / "TV"))
    janela.var_guia.set("https://outro.org/epg.xml")
    mapa = [{"channel": "AgroMais.br", "feed": None, "site": "mi.tv", "site_id": "br#agromais",
             "site_name": "AgroMais", "lang": "pt"}]
    monkeypatch.setattr(epg_iptv, "baixar_mapa", lambda cache: mapa)
    monkeypatch.setattr(epg_iptv, "achar_docker", lambda: "docker")
    iniciados = []
    monkeypatch.setattr(epg_iptv, "iniciar_container", lambda arquivo: iniciados.append(arquivo))
    textos = []
    app.escolher = lambda t, m, opcoes, **k: (textos.append(m), opcoes[0])[1]   # "Iniciar o coletor no Docker"
    janela.bt_programacao.invoke()
    esperar(app)
    esperar(app)
    assert "1 de 2 canal(is) têm programação" in textos[0] and "Nenhum" in textos[0]
    arquivo = tmp_path / "TV" / "channels.xml"
    assert 'site_id="br#agromais"' in arquivo.read_text(encoding="utf-8")
    assert iniciados == [str(arquivo)]
    assert janela.var_guia.get() == "http://localhost:3000/guide.xml; https://outro.org/epg.xml"
    assert "coletor está rodando" in app.caixas[-1][2]


def test_tv_conferir_programacao_preenche_a_coluna(app, monkeypatch, tmp_path):
    from jellyfin_tools import epg_iptv
    from jellyfin_tools.tv_ao_vivo import Canal
    canais = [Canal("Agro Mais", "https://a.org/1", id_guia="AgroMais.br"),
              Canal("Globo News", "https://a.org/2", idioma="Português"),
              Canal("Sem Guia", "https://a.org/3", idioma="Português")]
    janela = _abrir_tv(app, canais)
    janela.var_pasta.set(str(tmp_path / "TV"))
    janela.bt_conferir_programacao.invoke()                            # sem coletor montado: explica
    assert "Programação dos canais..." in app.caixas[-1][2]
    mapa = [{"channel": "AgroMais.br", "feed": None, "site": "mi.tv", "site_id": "1", "site_name": "AgroMais",
             "lang": "pt"},
            {"channel": "GloboNews.br", "feed": None, "site": "meuguia.tv", "site_id": "2", "site_name": "Globo News",
             "lang": "pt"}]
    epg_iptv.gravar_channels_xml(canais, tmp_path / "TV", mapa)
    janela.var_guia.set(epg_iptv.URL_GUIA_LOCAL)
    monkeypatch.setattr(epg_iptv, "estado_do_coletor", lambda: "rodando")
    monkeypatch.setattr(epg_iptv, "ler_guia", lambda: None)           # 1ª coleta ainda não terminou
    janela.bt_conferir_programacao.invoke()
    esperar(app)
    coluna = {janela.tabela.item(i, "text"): janela.tabela.set(i, "programacao") for i in janela.tabela.get_children()}
    assert coluna == {"Agro Mais": "aguardando coleta · mi.tv", "Globo News": "aguardando coleta · meuguia.tv",
                      "Sem Guia": "só categoria"}
    assert "ainda não respondeu" in app.caixas[-1][2] and "rodando ✓" in app.caixas[-1][2]
    from datetime import datetime, timedelta, timezone
    agora = datetime.now(timezone.utc)
    grade = {"AgroMais.br": [epg_iptv.Programa(agora - timedelta(minutes=10), agora + timedelta(minutes=20),
                                               "Campo e Lavoura"),
                             epg_iptv.Programa(agora + timedelta(minutes=20), agora + timedelta(hours=1), "Rural News")]
             + [epg_iptv.Programa(agora + timedelta(hours=n), None, f"P{n}") for n in range(2, 48)],
             "GloboNews.br": []}
    monkeypatch.setattr(epg_iptv, "ler_guia", lambda: grade)
    app.ao_conferir_programacao(avisar=False)                          # em segundo plano: só a coluna
    for _ in range(40):
        app.update()
        if janela.tabela.set("0", "programacao").startswith("✓"):
            break
        time.sleep(0.05)
    assert janela.tabela.set("0", "programacao") == "✓ 48 programas · mi.tv"
    assert janela.tabela.set("1", "programacao") == "sem programas · meuguia.tv"
    ate = (agora + timedelta(minutes=20)).astimezone().strftime("%H:%M")
    assert janela.tabela.set("0", "agora") == f"Campo e Lavoura (até {ate}) → Rural News"   # agora passando
    assert janela.tabela.set("1", "agora") == "—"
    assert dict(janela.valores_da_coluna("agora")) == {"Campo e Lavoura": 1, "(sem grade agora)": 2}
    assert dict(janela.valores_da_coluna("programacao")) == {"com programação · mi.tv": 1,
                                                             "sem programas · meuguia.tv": 1, "só categoria": 1}
    destino = tmp_path / "canais.csv"
    janela.exportar(destino)
    assert "Programação" in destino.read_text(encoding="utf-8-sig") and "✓ 48 programas" in destino.read_text(
        encoding="utf-8-sig")


def test_tv_tipos_dos_grupos_e_envio_com_andamento(app, monkeypatch, tmp_path):
    from jellyfin_tools.tv_ao_vivo import Canal
    from videoscraper import tv_moderna
    from videoscraper.gui_moderna import DialogoTipos
    janela = _abrir_tv(app, [Canal("A", "https://a.org/1", "Entertainment"), Canal("B", "https://a.org/2", "Movies"),
                             Canal("C", "https://a.org/3", "Entertainment")])
    pedidos = []
    monkeypatch.setattr(app, "_pedir_tipos", lambda grupos, atual: (pedidos.append((grupos, atual)),
                                                                    {"Entertainment": "series"})[1])
    janela.bt_tipos.invoke()
    assert pedidos[0] == ([("Entertainment", 2, None), ("Movies", 1, "movie")], {})   # do maior para o menor
    assert app.tipos_dos_grupos == {"Entertainment": "series"} and "Salvar e enviar" in app.caixas[-1][2]

    dialogo = DialogoTipos(janela, pedidos[0][0], {"Entertainment": "series"})   # a janelinha de verdade
    assert dialogo.vars["Entertainment"].get() == "Séries"
    assert dialogo.vars["Movies"].get() == "Automático (Filmes)"
    dialogo.vars["Movies"].set("Nenhum")
    dialogo._salvar()
    assert dialogo.resultado == {"Entertainment": "series", "Movies": ""}

    recebidos = {}

    def publicar_falso(canais, pasta, *a, **k):
        recebidos.update(k)
        k["ao_andamento"](0.5, "4/5 Jellyfin atualizando o guia: 50%")
        return ["lista salva"]
    monkeypatch.setattr(tv_moderna, "publicar_canais", publicar_falso)
    janela.var_pasta.set(str(tmp_path / "TV"))
    rodape = []
    original = app.definir_progresso_total
    monkeypatch.setattr(app, "definir_progresso_total", lambda f, t="": (rodape.append(t), original(f, t)))
    app._publicar_canais()                                             # "Salvar e enviar ao Jellyfin"
    esperar(app)
    assert recebidos["mapa_tipos"] == {"Entertainment": "series"}
    assert "4/5 Jellyfin atualizando o guia: 50%" in rodape

def test_tv_numerar_em_ordem(app):
    from jellyfin_tools.tv_ao_vivo import Canal
    janela = _abrir_tv(app, [Canal(f"C{n}", f"https://a.org/{n}") for n in range(4)])
    janela.bt_numerar.invoke()
    assert [c.numero for c in app._canais] == ["1", "2", "3", "4"]
    app._canais.append(Canal("Novo", "https://a.org/novo"))
    app._guardar_canais()
    janela.tabela.selection_set(["4"])
    janela.bt_numerar.invoke()                                          # só o selecionado: continua do maior
    assert app._canais[-1].numero == "5" and [c.numero for c in app._canais[:4]] == ["1", "2", "3", "4"]


def test_tv_enviar_com_filtro_ligado_pergunta_e_manda_so_os_filtrados(app, tmp_path):
    from jellyfin_tools.tv_ao_vivo import Canal
    janela = _abrir_tv(app, [Canal("A", "https://a.org/1", "Abertos"), Canal("B", "https://a.org/2", "Rádios"),
                             Canal("C", "https://a.org/3", "Abertos")])
    janela.var_pasta.set(str(tmp_path / "TV"))
    janela.aplicar_filtro("grupo", ["Abertos"])
    perguntas = []
    app.escolher = lambda t, m, opcoes, **k: (perguntas.append((m, opcoes)), opcoes[0])[1]   # "só os filtrados"
    app._publicar_canais()
    esperar(app)
    assert "o filtro só esconde" in perguntas[0][0] and perguntas[0][1][0] == "Enviar só os 2 filtrados"
    assert [c.nome for c in app._canais] == ["A", "C"] and not janela._filtros
    assert (tmp_path / "TV" / "canais.m3u").read_text(encoding="utf-8").count("#EXTINF") == 2
    janela.bt_desfazer.invoke()                                         # o que saiu pode voltar
    assert [c.nome for c in app._canais] == ["A", "B", "C"]


def test_tv_oferece_tirar_os_outros_sintonizadores_do_jellyfin(app, tmp_path, api_falsa):
    import json
    from jellyfin_tools.tv_ao_vivo import Canal
    hosts = [{"Id": "manual", "Type": "m3u", "FriendlyName": "iptv", "Url": "https://iptv-org.github.io/iptv/index.m3u"}]

    def tuner(q):
        pedido = api_falsa.pedidos[-1]
        if pedido["metodo"] == "DELETE":
            hosts[:] = [h for h in hosts if h["Id"] != q["id"][0]]
            return 204, b""
        corpo = {**json.loads(pedido["corpo"]), "Id": "nosso"}
        hosts[:] = [h for h in hosts if h["Id"] != "nosso"] + [corpo]
        return 200, corpo
    api_falsa.rotas["/System/Configuration/livetv"] = lambda q: (200, {"TunerHosts": hosts, "ListingProviders": []})
    api_falsa.rotas["/LiveTv/TunerHosts"] = tuner
    api_falsa.rotas["/ScheduledTasks"] = lambda q: (200, [])
    app.var_jf_url.set(api_falsa.base)
    app.var_jf_chave_jellyfin.set("chave")
    janela = _abrir_tv(app, [Canal("A", "https://a.org/1")])
    janela.var_pasta.set(str(tmp_path / "TV"))
    perguntas = []
    app.escolher = lambda t, m, opcoes, **k: (perguntas.append(m), opcoes[0])[1]
    app._publicar_canais()
    esperar(app)
    for _ in range(20):                                                 # a pergunta vem depois do "fim"
        app.update()
        time.sleep(0.03)
    esperar(app)
    assert any("iptv-org.github.io" in m and "cadastrados fora do programa" in m for m in perguntas)
    assert [h["Id"] for h in hosts] == ["nosso"]                        # o de fora saiu, o nosso ficou
    assert "1 sintonizador(es) retirado(s)" in app.caixas[-1][2]


def test_pastas_vigiadas_aceitam_virgula_e_avisam_o_que_esta_errado(app, tmp_path):
    from videoscraper.gui_moderna import dividir_pastas
    assert dividir_pastas("E:\\Series, E:\\Filmes; D:\\Down\nC:\\Filmes, Séries") == \
        ["E:\\Series", "E:\\Filmes", "D:\\Down", "C:\\Filmes, Séries"]          # vírgula no nome continua no nome
    downloads, filmes = tmp_path / "Downloads", tmp_path / "Filmes"
    downloads.mkdir()
    filmes.mkdir()
    app.mostrar_aba("Jellyfin")
    app.var_jf_destino.set(str(filmes))
    app.txt_pastas_vigiadas.delete("1.0", "end")
    app.txt_pastas_vigiadas.insert("1.0", f"{downloads}, {filmes}; {tmp_path / 'nao_existe'}")
    app.atualizar_aviso_vigiadas(arrumar=True)                          # ao sair do campo: uma por linha
    assert app.txt_pastas_vigiadas.get("1.0", "end").strip().splitlines() == \
        [str(downloads), str(filmes), str(tmp_path / "nao_existe")]
    aviso = app.lb_aviso_vigiadas.cget("text")
    assert "Não existe" in aviso and "biblioteca" not in aviso and app.lb_aviso_vigiadas.winfo_manager()
    alvos = app._alvos_da_vigia(app.obter_opcoes_jellyfin())
    assert [a[0] for a in alvos] == [str(downloads), str(filmes)]       # a biblioteca também pode ser vigiada
    app.definir_pastas_vigiadas([str(downloads)])
    assert app.lb_aviso_vigiadas.cget("text") == "" and not app.lb_aviso_vigiadas.winfo_manager()


def test_atualizar_sozinho_baixa_espera_ficar_livre_e_reinicia(app, monkeypatch, tmp_path):
    """Opção "Atualizar sozinho": versão nova -> baixa sem perguntar -> espera a tarefa acabar -> reinicia."""
    from videoscraper import atualizacao
    nova = atualizacao.VersaoNova("v9.9", "https://github.com/x/v9.9", arquivo_url="https://x/v.zip")
    arquivo = tmp_path / "videoscraper-windows-v9.9.zip"
    monkeypatch.setattr(atualizacao, "pode_instalar_sozinho", lambda: True)
    monkeypatch.setattr(atualizacao, "baixar", lambda n, **k: (arquivo.write_bytes(b"zip"), arquivo)[1])
    instalados, reinicios = [], []
    monkeypatch.setattr(atualizacao, "instalar_ao_fechar", lambda z, reabrir=True: instalados.append((z, reabrir)))
    monkeypatch.setattr(app, "sair_de_vez", lambda: reinicios.append(app._instalar_ao_sair))
    app.escolher = lambda *a, **k: pytest.fail("não deveria perguntar nada")
    app.SEGUNDOS_PARA_REINICIAR = 2
    app.var_jf_atualizar_sozinho.set(True)
    app._avisar_versao_nova(nova)
    fim = time.time() + 10
    while not reinicios and time.time() < fim:
        app.update()
        time.sleep(0.05)
    assert reinicios == [(arquivo, True)]                                # fecha, troca e ABRE de novo
    assert app.var_jf_versao_avisada.get() == "v9.9"


def test_atualizar_sozinho_desmarcado_cancela_o_reinicio(app, monkeypatch, tmp_path):
    from videoscraper import atualizacao
    nova = atualizacao.VersaoNova("v9.9", "https://github.com/x/v9.9", arquivo_url="https://x/v.zip")
    monkeypatch.setattr(atualizacao, "pode_instalar_sozinho", lambda: True)
    reinicios = []
    monkeypatch.setattr(app, "sair_de_vez", lambda: reinicios.append(True))
    app.SEGUNDOS_PARA_REINICIAR = 2
    app.var_jf_atualizar_sozinho.set(True)
    app._atualizacao_baixada(nova, tmp_path / "v.zip", sozinho=True)
    assert "reinicia sozinho em 2 s" in app.var_status.get()
    app.var_jf_atualizar_sozinho.set(False)                             # mudou de ideia
    fim = time.time() + 4
    while time.time() < fim:
        app.update()
        time.sleep(0.05)
    assert not reinicios and "Reinício cancelado" in app.var_status.get()
    assert app._instalar_ao_sair == (tmp_path / "v.zip", False)         # instala quando fechar, sem reabrir


def test_idiomas_das_legendas_quantos_quiser(app):
    """Vários idiomas por vírgula, ponto e vírgula ou espaço, pelo nome ou código; e a lista "Mais idiomas"."""
    app.mostrar_aba("Jellyfin")
    app.var_jf_outros_idiomas.set("francês; coreano, russo xyz jp")
    assert app.idiomas_jf() == "pt-BR, fr, ko, ru, ja"
    texto = app.lb_idiomas_entendidos.cget("text")
    assert "Entendi: Francês (fr), Coreano (ko), Russo (ru), Japonês (ja)" in texto and "Não reconheci: xyz" in texto
    app.var_jf_outros_idiomas.set("fr")
    app.abrir_mais_idiomas()
    busca, marcados, aplicar = app._idiomas_abertos
    assert marcados == {"fr"}
    busca.set("core")                                                  # procura
    marcados.update({"ko", "ar"})
    aplicar()
    assert app.var_jf_outros_idiomas.get() == "fr, ko, ar" and not app._janela_idiomas.winfo_exists()
    assert "⚠" not in app.lb_idiomas_entendidos.cget("text")


def _vigia_nas_bibliotecas(app, tmp_path, filmes_escolhida=True, no_lugar=False):
    """O jeito do usuário: os arquivos caem DENTRO das bibliotecas e a vigia arruma no lugar."""
    import os
    series, filmes = tmp_path / "Series_Organizadas", tmp_path / "Filmes_Organizados"
    app.var_jf_vigia_no_lugar.set(no_lugar)
    for p in (series / "Animes" / "Ashita no Joe 2 - 01 ~ 47" / "[Erai-raws] Ashita no Joe 2 - 14 [720p].mkv",
              filmes / "Matrix (1999)" / "Matrix (1999).mkv", filmes / "Interestelar.2014.1080p.BluRay.x264.mkv"):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"v" * 2048)
        os.utime(p, (time.time() - 3600, time.time() - 3600))      # terminou de baixar
    app.mostrar_aba("Jellyfin")
    app._destinos["Filmes"], app._destinos["Séries"] = (str(filmes) if filmes_escolhida else ""), str(series)
    app.var_jf_destino.set(app._destinos[app._modo_atual])
    app.var_jf_legendas.set(False)
    app.definir_pastas_vigiadas([str(series), str(filmes)])
    app.var_jf_vigiar.set(True)
    app.ao_alternar_vigia()
    fim = time.time() + 60
    while (app._vigia_conferindo or app.trabalhando) and time.time() < fim:
        app.update()
        time.sleep(0.05)
    esperar(app)
    app.var_jf_vigiar.set(False)
    app.ao_alternar_vigia()
    return series, filmes


def test_vigia_nas_proprias_bibliotecas_organiza_filmes_e_series(app, tmp_path):
    series, filmes = _vigia_nas_bibliotecas(app, tmp_path)
    assert (filmes / "Interestelar (2014)" / "Interestelar (2014).mkv").is_file()       # o filme foi organizado
    assert (series / "Ashita no Joe 2" / "Season 01" / "Ashita no Joe 2 S01E14.mkv").is_file()
    assert (filmes / "Matrix (1999)" / "Matrix (1999).mkv").is_file()                 # já estava: fica
    assert "1 filme(s) e 1 episódio(s)" in app.var_status.get()


def test_vigia_organiza_cada_pasta_dentro_dela_mesma(app, tmp_path):
    """Opção ligada: E:/Series_Organizadas/NOVELAS se arruma lá dentro, mesmo com a biblioteca de Séries da tela
    apontando para outra pasta (o caso do usuário: Séries = E:/Filmes_Organizados)."""
    import os
    filmes, novelas = tmp_path / "Filmes_Organizados", tmp_path / "Series_Organizadas" / "NOVELAS"
    for p in (filmes / "Interestelar.2014.1080p.BluRay.x264.mkv", novelas / "Pantanal" / "Pantanal.S01E03.mkv"):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"v" * 2048)
        os.utime(p, (time.time() - 3600, time.time() - 3600))
    app.mostrar_aba("Jellyfin")
    app._destinos["Filmes"], app._destinos["Séries"] = str(filmes), str(filmes)        # a tela "errada"
    app.var_jf_destino.set(app._destinos[app._modo_atual])
    app.var_jf_origem.set(str(filmes))
    app.var_jf_legendas.set(False)
    app.definir_pastas_vigiadas([str(filmes), str(novelas)])
    assert app.var_jf_vigia_no_lugar.get()                              # já vem marcada
    assert app._bibliotecas_faltando() == []
    app.var_jf_vigiar.set(True)
    app.ao_alternar_vigia()
    fim = time.time() + 60
    while (app._vigia_conferindo or app.trabalhando) and time.time() < fim:
        app.update()
        time.sleep(0.05)
    esperar(app)
    app.var_jf_vigiar.set(False)
    app.ao_alternar_vigia()
    assert (filmes / "Interestelar (2014)" / "Interestelar (2014).mkv").is_file()
    assert (novelas / "Pantanal" / "Season 01" / "Pantanal S01E03.mkv").is_file()   # ficou nas NOVELAS
    assert not list(filmes.rglob("Pantanal*"))                          # nada foi para a pasta de origem
    assert "1 filme(s) e 1 episódio(s)" in app.var_status.get()


def test_vigia_sem_biblioteca_de_filmes_avisa_em_vez_de_ignorar_calada(app, tmp_path):
    series, filmes = _vigia_nas_bibliotecas(app, tmp_path, filmes_escolhida=False)
    estados = []
    app.definir_estado_vigia = lambda texto, ligada: estados.append(texto)
    app.var_jf_vigiar.set(True)
    app.ao_alternar_vigia()                                             # o estado da vigia já avisa
    assert "Sem biblioteca de Filmes: esses ficam parados" in estados[-1]
    app.var_jf_vigiar.set(False)
    app.ao_alternar_vigia()
    assert "Filmes: biblioteca não escolhida, ficaram onde estão" in app.var_status.get()
    assert (filmes / "Interestelar.2014.1080p.BluRay.x264.mkv").is_file()             # parado, mas avisado


def test_vigia_pede_o_scan_do_jellyfin_no_fim(app, tmp_path, api_falsa):
    api_falsa.rotas["/Library/Refresh"] = lambda q: (204, b"")
    app.var_jf_url.set(api_falsa.base)
    app.var_jf_chave_jellyfin.set("chave")
    app.var_jf_atualizar.set(True)
    _vigia_nas_bibliotecas(app, tmp_path)
    assert [p["caminho"] for p in api_falsa.pedidos].count("/Library/Refresh") == 1
    assert "Jellyfin: biblioteca atualizando (scan pedido)" in app.var_status.get()


def test_vigia_sem_chave_avisa_que_o_jellyfin_nao_foi_atualizado(app, tmp_path):
    """Caso real: sem "Lembrar as chaves", a chave some ao reiniciar e o scan deixava de ser pedido calado."""
    app.var_jf_url.set("http://localhost:8096")
    app.var_jf_chave_jellyfin.set("")
    app.var_jf_atualizar.set(True)
    estados = []
    original = app.definir_estado_vigia
    app.definir_estado_vigia = lambda texto, ligada: (estados.append(texto), original(texto, ligada))
    _vigia_nas_bibliotecas(app, tmp_path)
    assert "scan NÃO pedido (falta a chave de API" in app.var_status.get()
    assert any("o Jellyfin NÃO é avisado para atualizar a biblioteca" in e for e in estados)


def test_botao_atualizar_a_biblioteca_agora(app, api_falsa, monkeypatch):
    """O botão acompanha o scan até o fim e mostra o que mudou (antes só sabia que o pedido foi aceito)."""
    from jellyfin_tools import servidor_jellyfin
    monkeypatch.setattr(servidor_jellyfin, "INTERVALO_SCAN", 0.05)
    estado = {"pedido": False, "olhadas": 0}

    def refresh(q):
        estado["pedido"] = True
        return 204, b""

    def tarefa(q):                                                      # roda 2 olhadas e termina
        if estado["pedido"]:
            estado["olhadas"] += 1
        if estado["pedido"] and estado["olhadas"] <= 2:
            return 200, {"State": "Running", "CurrentProgressPercentage": 50.0 * estado["olhadas"]}
        fim = "2026-10-06T10:00:00Z" if estado["olhadas"] > 2 else "2026-10-05T03:00:00Z"
        return 200, {"State": "Idle", "LastExecutionResult": {"Status": "Completed", "EndTimeUtc": fim}}
    api_falsa.rotas["/Library/Refresh"] = refresh
    api_falsa.rotas["/ScheduledTasks"] = lambda q: (200, [{"Key": "RefreshLibrary", "Id": "scan1", **tarefa(q)[1]}])
    api_falsa.rotas["/ScheduledTasks/scan1"] = tarefa
    api_falsa.rotas["/Items/Counts"] = lambda q: (200, {"MovieCount": 10 + (3 if estado["olhadas"] > 2 else 0),
                                                        "SeriesCount": 4,
                                                        "EpisodeCount": 100 + (12 if estado["olhadas"] > 2 else 0)})
    app.mostrar_aba("Jellyfin")
    app.var_jf_url.set("")
    app.bt_scan_jellyfin.invoke()
    assert "Preencha o endereço e a chave" in app.caixas[-1][2]
    app.var_jf_url.set(api_falsa.base)
    app.var_jf_chave_jellyfin.set("chave")
    app.bt_scan_jellyfin.invoke()
    esperar(app)
    assert any(p["caminho"] == "/Library/Refresh" for p in api_falsa.pedidos)
    tipo, titulo, texto = app.caixas[-1]
    assert tipo == "sucesso" and "Escaneamento concluído" in texto
    assert "+3 filme(s), +12 episódio(s)" in texto and "Agora: 13 filme(s), 4 série(s), 112 episódio(s)" in texto


def _programa_falso(pasta):
    (pasta / "_internal").mkdir(parents=True)
    (pasta / "videoscraper.exe").write_bytes(b"exe")
    (pasta / "_internal" / "base_library.zip").write_bytes(b"lib")
    return pasta


def test_instalar_no_lugar_fixo_copia_cria_atalhos_e_reabre_de_la(app, monkeypatch, tmp_path):
    from videoscraper import atualizacao, inicializacao, instalacao
    downloads = _programa_falso(tmp_path / "Downloads" / "videoscraper")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.setattr(atualizacao, "pode_instalar_sozinho", lambda: True)
    monkeypatch.setattr(atualizacao, "pasta_do_programa", lambda: downloads)
    atalhos, abertos, saiu, registro = [], [], [], []
    monkeypatch.setattr(instalacao, "criar_atalhos", lambda exe: atalhos.append(Path(exe)))
    monkeypatch.setattr(instalacao, "abrir", lambda exe: abertos.append(Path(exe)))
    monkeypatch.setattr(inicializacao, "ativo", lambda: True)
    monkeypatch.setattr(inicializacao, "ativar", lambda ligar, executavel=None: registro.append(executavel))
    monkeypatch.setattr(app, "sair_de_vez", lambda: saiu.append(True))
    perguntas = []
    app.escolher = lambda t, m, opcoes, **k: (perguntas.append(m), opcoes[0])[1]
    app._mostrar_pasta_programa()
    assert str(downloads) in app.lb_pasta_programa.cget("text") and app.bt_instalar_fixo.winfo_manager()
    app._conferir_instalacao()                                          # ao abrir: oferece
    assert "Instalar num lugar FIXO" in perguntas[0] and str(tmp_path / "Local" / "Programs" / "videoscraper") in perguntas[0]
    esperar(app)
    for _ in range(20):
        app.update()
        time.sleep(0.03)
    fixo = tmp_path / "Local" / "Programs" / "videoscraper" / "videoscraper.exe"
    assert fixo.is_file() and (fixo.parent / "_internal" / "base_library.zip").is_file()
    assert atalhos == [fixo] and registro == [fixo] and abertos == [fixo] and saiu
    assert "Use o atalho" in app.caixas[-1][2]


def test_no_lugar_fixo_nao_pergunta_e_refaz_atalhos_uma_vez_por_versao(app, monkeypatch, tmp_path):
    from videoscraper import atualizacao, config, instalacao
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    fixo = _programa_falso(tmp_path / "Local" / "Programs" / "videoscraper")
    monkeypatch.setattr(atualizacao, "pode_instalar_sozinho", lambda: True)
    monkeypatch.setattr(atualizacao, "pasta_do_programa", lambda: fixo)
    atalhos = []
    monkeypatch.setattr(instalacao, "criar_atalhos", lambda exe: atalhos.append(exe))
    app.escolher = lambda *a, **k: pytest.fail("no lugar fixo não pergunta nada")
    app._mostrar_pasta_programa()
    assert "(lugar fixo ✓)" in app.lb_pasta_programa.cget("text") and not app.bt_instalar_fixo.winfo_manager()
    for _ in range(2):                                                  # 2ª vez na mesma versão: não refaz
        app._conferir_instalacao()
        fim = time.time() + 3
        while time.time() < fim and len(atalhos) < 1:
            app.update()
            time.sleep(0.03)
        for _ in range(10):
            app.update()
            time.sleep(0.02)
    assert len(atalhos) == 1
    assert config.carregar()["instalacao"]["atalhos_versao"] == atualizacao.versao_atual()


def test_nao_perguntar_de_novo(app, monkeypatch, tmp_path):
    from videoscraper import atualizacao, config
    monkeypatch.setattr(atualizacao, "pode_instalar_sozinho", lambda: True)
    monkeypatch.setattr(atualizacao, "pasta_do_programa", lambda: tmp_path / "Downloads")
    app.escolher = lambda t, m, opcoes, **k: "Não perguntar de novo"
    app._conferir_instalacao()
    assert config.carregar()["instalacao"]["nao_perguntar"] is True
    app.escolher = lambda *a, **k: pytest.fail("não pergunta mais")
    app._conferir_instalacao()


def test_tv_com_canais_a_mais_no_jellyfin_oferece_limpar_e_reenviar(app, tmp_path, api_falsa):
    """Caso real: enviou 144 e o Jellyfin seguia com 11.129, sem nenhum sintonizador "de fora"."""
    import json
    from jellyfin_tools.tv_ao_vivo import Canal
    hosts, total = [], {"n": 11129}

    def tuner(q):
        pedido = api_falsa.pedidos[-1]
        if pedido["metodo"] == "DELETE":
            hosts[:] = [h for h in hosts if h["Id"] != q["id"][0]]
            total["n"] = 0                                              # sem a lista, os velhos somem
            return 204, b""
        corpo = {**json.loads(pedido["corpo"]), "Id": "nosso"}
        hosts[:] = [corpo]
        return 200, corpo

    def rodar(q):
        if hosts:
            total["n"] = 1 if total["n"] == 0 else total["n"]
        return 204, b""
    api_falsa.rotas["/System/Configuration/livetv"] = lambda q: (200, {"TunerHosts": hosts, "ListingProviders": []})
    api_falsa.rotas["/LiveTv/TunerHosts"] = tuner
    api_falsa.rotas["/ScheduledTasks"] = lambda q: (200, [{"Key": "RefreshGuide", "Id": "abc"}])
    api_falsa.rotas["/ScheduledTasks/Running/abc"] = rodar
    api_falsa.rotas["/ScheduledTasks/abc"] = lambda q: (200, {"State": "Idle"})
    api_falsa.rotas["/LiveTv/Channels"] = lambda q: (200, {"Items": [], "TotalRecordCount": total["n"]})
    app.var_jf_url.set(api_falsa.base)
    app.var_jf_chave_jellyfin.set("chave")
    janela = _abrir_tv(app, [Canal("A", "https://a.org/1")])
    janela.var_pasta.set(str(tmp_path / "TV"))
    perguntas = []
    app.escolher = lambda t, m, opcoes, **k: (perguntas.append((t, m)), opcoes[0])[1]
    app._publicar_canais()                                              # envio -> pergunta -> limpeza (2 tarefas)
    fim = time.time() + 60
    while time.time() < fim and not any("Com a lista de novo" in c[2] for c in app.caixas):
        app.update()
        time.sleep(0.05)
    titulo, texto = next((t, m) for t, m in perguntas if "canais a mais" in t)
    assert "11129 canais, mas a lista enviada tem 1" in texto and "videoscraper" in texto
    assert "Com a lista de novo: agora TV ao vivo tem 1 canal(is)" in app.caixas[-1][2]


def test_nao_identificados_por_pasta_corrige_o_grupo_inteiro(app, tmp_path, monkeypatch):
    origem = tmp_path / "Downloads"
    for nome in ("Pasta A/abc_xyz_1.mkv", "Pasta A/abc_xyz_2.mkv", "Pasta A/abc_xyz_3.mkv", "Pasta B/zzz.mkv",
                 "Matrix.1999.mkv"):
        (origem / nome).parent.mkdir(parents=True, exist_ok=True)
        (origem / nome).write_bytes(b"v")
    app.mostrar_aba("Jellyfin")
    app.seletor_modo.set("Filmes")
    app._ao_trocar_modo("Filmes")
    app.var_jf_exigir.set(True)                                         # nome que o catálogo não conhece: sem nome
    app.var_jf_origem.set(str(origem))
    app.var_jf_destino.set(str(tmp_path / "Filmes"))
    app.bt_previa.invoke()
    esperar(app)
    app.bt_nao_identificados.invoke()
    janela = app.janela_nao_identificados
    linhas = [(janela.tabela.item(i, "text"), janela.tabela.set(i, "quantos")) for i in janela.tabela.get_children()]
    assert linhas == [(str(origem / "Pasta A"), "3"), (str(origem / "Pasta B"), "1")]   # o maior grupo primeiro
    selecionados = []
    monkeypatch.setattr(app, "ao_corrigir_nome", lambda: selecionados.append(set(app.tabela_jf.selection())))
    janela.tabela.selection_set(["0"])
    janela.bt_corrigir.invoke()
    nomes = {app._movimentos_previa[int(i)].origem.name for i in selecionados[0]}
    assert nomes == {"abc_xyz_1.mkv", "abc_xyz_2.mkv", "abc_xyz_3.mkv"} and not janela.winfo_exists()


def test_painel_de_saude_numa_linha(app, tmp_path):
    filmes = tmp_path / "Filmes"
    filmes.mkdir()
    app.mostrar_aba("Jellyfin")
    app._destinos["Séries"] = ""
    app.var_jf_destino.set(str(filmes))
    app.var_jf_chave_jellyfin.set("")
    app._ciclo_saude()
    texto = app.lb_saude.cget("text")
    assert "✓ Filmes" in texto and "⚠ Séries: biblioteca não escolhida" in texto
    assert "⚠ Jellyfin: sem a chave de API" in texto and "○ Vigia desligada" in texto and "Versão" in texto
    assert app.lb_saude.winfo_manager()                                 # aparece na aba Jellyfin
    app.mostrar_aba("Vídeos")
    assert not app.lb_saude.winfo_manager()                             # e some na aba Vídeos


def test_lixeira_com_mais_de_30_dias_pergunta_e_apaga(app, tmp_path):
    import os
    from videoscraper import config
    filmes = tmp_path / "Filmes"
    velho = filmes / ".organizador" / "removidos" / "20250101-101500-000001"
    novo = filmes / ".organizador" / "removidos" / time.strftime("%Y%m%d-%H%M%S-000002")
    for pasta in (velho, novo):
        (pasta / "Matrix (1999)").mkdir(parents=True)
        (pasta / "Matrix (1999)" / "Matrix.720p.mkv").write_bytes(b"x" * 4096)
    app.mostrar_aba("Jellyfin")
    app.var_jf_destino.set(str(filmes))
    perguntas = []
    app.escolher = lambda t, m, opcoes, **k: (perguntas.append(m), "Apagar de vez")[1]
    app._conferir_lixeira(sempre=True)
    fim = time.time() + 10
    while time.time() < fim and velho.exists():
        app.update()
        time.sleep(0.05)
    esperar(app)
    assert not velho.exists() and novo.exists()                         # só o de mais de 30 dias
    assert "1 lote(s)" in perguntas[0] and "20250101" in perguntas[0]
    assert config.carregar()["lixeira"]["perguntado"]
    app.escolher = lambda *a, **k: pytest.fail("pergunta no máximo uma vez por semana")
    app._conferir_lixeira()
    os.sync() if hasattr(os, "sync") else None


def test_tv_limpeza_que_nao_resolve_mostra_o_diagnostico(app, tmp_path, api_falsa):
    """Caso real: mesmo sem a lista, o Jellyfin seguia com 11.129 canais (outra fonte, ou ele não limpa)."""
    import json
    from jellyfin_tools.tv_ao_vivo import Canal
    hosts = []

    def tuner(q):
        pedido = api_falsa.pedidos[-1]
        if pedido["metodo"] == "DELETE":
            hosts.clear()
            return 204, b""
        corpo = {**json.loads(pedido["corpo"]), "Id": "nosso"}
        hosts[:] = [corpo]
        return 200, corpo
    api_falsa.rotas["/System/Configuration/livetv"] = lambda q: (200, {"TunerHosts": hosts, "ListingProviders": []})
    api_falsa.rotas["/LiveTv/TunerHosts"] = tuner
    api_falsa.rotas["/LiveTv/Info"] = lambda q: (200, {"Services": [{"Name": "IPTV Plugin", "Status": "Ok"}]})
    api_falsa.rotas["/ScheduledTasks"] = lambda q: (200, [{"Key": "RefreshGuide", "Id": "abc"}])
    api_falsa.rotas["/ScheduledTasks/Running/abc"] = lambda q: (204, b"")
    api_falsa.rotas["/ScheduledTasks/abc"] = lambda q: (200, {"State": "Idle"})
    api_falsa.rotas["/LiveTv/Channels"] = lambda q: (200, {"Items": [{"Name": "Canal X", "ServiceName": "IPTV Plugin"}],
                                                           "TotalRecordCount": 11129})
    app.var_jf_url.set(api_falsa.base)
    app.var_jf_chave_jellyfin.set("chave")
    janela = _abrir_tv(app, [Canal("A", "https://a.org/1")])
    janela.var_pasta.set(str(tmp_path / "TV"))
    perguntas = []
    app.escolher = lambda t, m, opcoes, **k: (perguntas.append((t, m)), opcoes[0])[1]   # limpa e copia
    app._publicar_canais()
    fim = time.time() + 60
    while time.time() < fim and not any("diagnóstico" in t for t, _ in perguntas):
        app.update()
        time.sleep(0.05)
    titulo, texto = next((t, m) for t, m in perguntas if "diagnóstico" in t)
    assert "Sem a lista: o Jellyfin ficou com 11129" in texto and "IPTV Plugin" in texto
    assert "Canal X  [serviço: IPTV Plugin]" in app.clipboard_get()
    janela.bt_diagnostico.invoke()                                      # o botão faz o mesmo, sem limpar
    esperar(app)
    for _ in range(10):
        app.update()
        time.sleep(0.03)
    assert sum("diagnóstico" in t for t, _ in perguntas) == 2


def test_baixar_do_archive_sem_licenca_pergunta_so_livres_ou_todos(app):
    from videoscraper.extracao import LinkVideo
    app.mostrar_aba("Vídeos")
    app.definir_url("https://archive.org/download/item")
    sem = LinkVideo("https://archive.org/download/item/ep1.mkv", "https://archive.org/details/item", "archive.org", "ep1")
    livre = LinkVideo("https://archive.org/download/pd/ep1.mkv", "https://archive.org/details/pd", "archive.org", "ep1",
                      licenca="Domínio público")
    cc = LinkVideo("https://archive.org/download/cc/a.mp4", "https://archive.org/details/cc", "archive.org", "a",
                   licenca="CC BY 4.0")
    perguntas, baixados, avisos = [], [], []
    resposta = [None]
    app.escolher = lambda t, m, opcoes, cancelar="Cancelar": (perguntas.append(m), resposta[0])[1]
    app.mostrar_mensagem = lambda t, m, tipo="info": avisos.append(m)
    rodar_original = app._rodar
    app._rodar = lambda status, tarefa: baixados.append(status)        # não baixa de verdade no teste

    app._baixar([sem, livre])                                          # cancelou: nada
    assert "1 com domínio público" in perguntas[0] and "certeza" in perguntas[0] and baixados == []

    app.trabalhando = False
    resposta[0] = app.OPCOES_LICENCA[0]                                # "Só domínio público / CC"
    filtrados = app._filtrar_por_licenca([sem, livre, cc])
    assert filtrados == [livre, cc]
    assert app._filtrar_por_licenca([sem]) is None and "nada foi baixado" in avisos[-1]

    resposta[0] = app.OPCOES_LICENCA[1]                                # "Todos (tenho certeza)"
    assert app._filtrar_por_licenca([sem, livre]) == [sem, livre]

    perguntas.clear()
    assert app._filtrar_por_licenca([livre, cc]) == [livre, cc] and perguntas == []   # todos livres: nem pergunta
    app._baixar([livre])
    assert baixados == ["Baixando vídeos..."]
    app._rodar = rodar_original

    # "Baixar" sem buscar antes: a busca acha os vídeos e a pergunta vem no fim (com a janela livre)
    chamados = []
    app._baixar = lambda lista: chamados.append(lista)
    app.trabalhando = True
    app.fila.put(("baixar_depois", [sem, livre]))
    app.fila.put(("fim", None))
    for _ in range(20):
        app.update()
        time.sleep(0.02)
    assert chamados == [[sem, livre]]


def test_seletor_da_lista_de_videos(app):
    """☐/☑ na coluna #, um clique marca sem perder os outros, título "☐ #" marca todos e o campo "1-3, 5"."""
    from videoscraper.gui_moderna import numeros_do_texto
    assert numeros_do_texto("1-3, 5") == {1, 2, 3, 5} and numeros_do_texto("2 a 4") == {2, 3, 4}
    assert numeros_do_texto("1x0") is None
    app.mostrar_aba("Vídeos")
    app.limpar_tabela()
    for i in range(6):
        app.adicionar_video(str(i), i + 1, "", f"Episodio 1x0{i + 1}", "archive.org", f"https://a/{i}.mkv")
    app.update()
    assert app.tabela.set("0", "n") == "☐ 1"

    class Clique:
        def __init__(self, iid, estado=0):
            x, y, _, h = app.tabela.bbox(iid, "titulo")
            self.x, self.y, self.state = x + 5, y + h // 2, estado
    app.tabela.see("0")
    app.update()
    assert app._ao_clicar_tabela(Clique("0")) == "break"
    assert app._ao_clicar_tabela(Clique("2")) == "break"
    app.update()
    assert set(app.tabela.selection()) == {"0", "2"}                  # sem Ctrl: os dois ficam marcados
    assert app.tabela.set("0", "n") == "☑ 1" and app.tabela.set("1", "n") == "☐ 2"
    assert "2 de 6 selecionado" in app.lb_selecao.cget("text")
    app._ao_clicar_tabela(Clique("0"))                                 # clicar de novo desmarca
    app.update()
    assert app.tabela.selection() == ("2",) and app.tabela.set("0", "n") == "☐ 1"
    assert app._ao_clicar_tabela(Clique("4", estado=0x1)) is None     # Shift: o Treeview cuida (intervalo)

    assert app.marcar_por_texto("4-5") == 2
    app.update()
    assert set(app.tabela.selection()) == {"2", "3", "4"}
    assert app.marcar_por_texto("1x06") == 1                           # pelo nome
    assert app.marcar_por_texto("nada disso") == 0 and "Nada com" in app.lb_selecao.cget("text")

    app.alternar_todos()                                               # título "☐ #": todos
    app.update()
    assert len(app.tabela.selection()) == 6 and app.tabela.heading("n", "text") == "☑ #"
    app.alternar_todos()                                               # de novo: nenhum
    app.update()
    assert app.tabela.selection() == () and app.tabela.set("5", "n") == "☐ 6"


def test_arquivos_seletor_filtro_por_coluna_e_so_o_que_esta_a_vista_muda(app, tmp_path):
    """Tela de Arquivos: ☑/☐ por linha, filtro em cada coluna e o Organizar só mexe no marcado E à vista."""
    origem = tmp_path / "Baixados"
    _video_grande(origem / "Cidade.de.Deus.2002.1080p.mkv")
    _video_grande(origem / "Matrix.1999.1080p.mkv")
    _video_grande(origem / "Up.2009.1080p.mkv")
    filmes = tmp_path / "Filmes"
    filmes.mkdir()
    app.mostrar_aba("Jellyfin")
    app.seletor_modo.set("Filmes")
    app._ao_trocar_modo("Filmes")
    app.var_jf_origem.set(str(origem))
    app.var_jf_destino.set(str(filmes))
    app.var_jf_legendas.set(False)
    app.bt_previa.invoke()
    esperar(app)
    atuais = {app.tabela_jf.set(i, "atual"): i for i in app._ordem_jf if app._categoria_jf.get(i) == "mover"}
    matrix, cidade = atuais["Matrix.1999.1080p.mkv"], atuais["Cidade.de.Deus.2002.1080p.mkv"]
    assert app.tabela_jf.set(matrix, "n").startswith("☑")

    # 1) individual: clique na caixa da coluna #
    app.tabela_jf.see(matrix)
    app.update()
    x, y, _, h = app.tabela_jf.bbox(matrix, "n")

    class Clique:
        state = 0
    Clique.x, Clique.y = x + 4, y + h // 2
    assert app._ao_clicar_tabela_jf(Clique) == "break"
    assert app.tabela_jf.set(matrix, "n").startswith("☐") and app.nao_mover_jf() == [matrix]

    # 2) filtro numa coluna (Arquivo atual): digitar "cidade" e aplicar
    valores = dict(app.valores_jf("atual"))
    assert valores["Cidade.de.Deus.2002.1080p.mkv"] >= 1 and "▾" in app.tabela_jf.heading("atual", "text")
    app.abrir_filtro_jf("atual")
    texto, marcados, aplicar = app._filtro_aberto_jf
    texto.set("cidade")
    aplicar()
    app.update()
    assert cidade in app.visiveis_jf() and matrix not in app.visiveis_jf() and \
        all("Cidade" in app.tabela_jf.set(i, "atual") for i in app.visiveis_jf()) and "(filtro)" in app.tabela_jf.heading("atual", "text")
    assert app.valor_jf("status", cidade) == "vai mover"                    # sem o símbolo, para o filtro

    perguntas = []
    app.perguntar = lambda t, m: perguntas.append(m) or True
    app.bt_organizar.invoke()
    esperar(app)
    assert "Mover 1 arquivo(s)" in perguntas[0] and "escondido(s) pelo filtro" in perguntas[0]
    assert (filmes / "Cidade de Deus (2002)" / "Cidade de Deus (2002).mkv").exists()
    assert "1 desmarcado(s) (☐) e 1 escondido(s) pelo filtro" in perguntas[0]
    assert (origem / "Matrix.1999.1080p.mkv").exists()                      # desmarcado: ficou
    assert (origem / "Up.2009.1080p.mkv").exists()                          # escondido pelo filtro: ficou

    # 3) "Mostrar todos" tira o filtro das colunas
    app.mostrar_todos_jf()
    assert "▾" in app.tabela_jf.heading("atual", "text") and not app._filtros_col_jf


def test_arquivos_marcar_todos_e_proteger_a_pasta(app, tmp_path):
    origem = tmp_path / "Baixados"
    for n in (1, 2):
        _video_grande(origem / "Tom and Jerry" / "Season 1" / f"Tom and Jerry S01E0{n}.mkv")
    _video_grande(origem / "Pica-Pau" / "Pica-Pau S01E01.mkv")
    series = tmp_path / "Series"
    series.mkdir()
    app.mostrar_aba("Jellyfin")
    app.seletor_modo.set("Séries")
    app._ao_trocar_modo("Séries")
    app.var_jf_origem.set(str(origem))
    app.var_jf_destino.set(str(series))
    app.var_jf_legendas.set(False)
    app.definir_pastas_protegidas([])
    app.bt_previa.invoke()
    esperar(app)
    mover = [i for i in app._ordem_jf if app._categoria_jf.get(i) == "mover"]
    app.alternar_mover_visiveis_jf()                                         # título "☑ #": desmarca todos
    assert set(app.nao_mover_jf()) == set(mover)
    app.alternar_mover_visiveis_jf()                                         # de novo: marca todos
    assert app.nao_mover_jf() == []
    app.tabela_jf.selection_set([mover[0]])
    app.marcar_mover_jf(app.tabela_jf.selection(), False)                     # "☐ Não mover selecionados"
    assert app.nao_mover_jf() == [mover[0]]
    app.marcar_mover_jf(app.tabela_jf.selection(), True)

    tom = next(i for i in mover if "Tom" in app.tabela_jf.set(i, "atual"))
    app.tabela_jf.selection_set([tom])
    perguntas = []
    app.perguntar = lambda t, m: perguntas.append(m) or True
    app.ao_proteger_pasta_jf()
    assert str(origem / "Tom and Jerry") in perguntas[0]                     # a pasta da série, não a "Season 1"
    assert app.pastas_protegidas() == [str(origem / "Tom and Jerry")]
    dos_tom = [i for i in mover if "Tom" in app.tabela_jf.set(i, "atual")]
    assert len(dos_tom) == 2 and set(app.nao_mover_jf()) == set(dos_tom)


def test_sobra_desmarcada_nao_e_apagada(app, tmp_path):
    """'vai apagar a pasta' desmarcado (☐): a pasta fica, sem nenhuma alteração."""
    import json
    raiz = tmp_path / "The Office"
    sobra = raiz / "Vida de Escritorio 2005 - 1a Temporada WWW.BLUDV.TV"
    sobra.mkdir(parents=True)
    with open(sobra / "BLUDV.TV.mp4", "wb") as f:
        f.truncate(52 * 1024 * 1024)
    (sobra / "The.Office.S01E01.720p-poster.jpg").write_bytes(b"jpg")
    novo = raiz / "The Office (2005)" / "Season 01" / "The Office S01E01 - Piloto.mkv"
    novo.parent.mkdir(parents=True)
    novo.write_bytes(b"v")
    (raiz / ".organizador").mkdir()
    (raiz / ".organizador" / "log-1.json").write_text(json.dumps({"raiz": str(raiz), "itens": [
        {"de": str(sobra / "The.Office.S01E01.720p.mkv"), "para": str(novo)}]}), encoding="utf-8")
    app.mostrar_aba("Jellyfin")
    app.seletor_modo.set("Séries")
    app._ao_trocar_modo("Séries")
    app.var_jf_origem.set(str(raiz))
    app.var_jf_destino.set(str(raiz))
    app.var_jf_apagar_pasta.set(True)
    app.var_jf_legendas.set(False)
    app.bt_previa.invoke()
    esperar(app)
    iid = next(i for i in app._ordem_jf if app.tabela_jf.set(i, "atual") == sobra.name)
    assert app.marcar_mover_jf([iid], False) == 1
    avisos = []
    app.mostrar_mensagem = lambda t, m, tipo="info": avisos.append(m)
    app.bt_organizar.invoke()
    esperar(app)
    assert "Nenhum arquivo marcado" in avisos[0]
    assert (sobra / "BLUDV.TV.mp4").exists() and (sobra / "The.Office.S01E01.720p-poster.jpg").exists()


def test_saude_da_tv_no_painel_e_diagnostico_sem_texto_generico(app, api_falsa):
    from jellyfin_tools.tv_ao_vivo import Canal
    total = [11129]
    api_falsa.rotas["/LiveTv/Info"] = lambda q: (200, {"Services": [{"Name": "Emby", "Status": "Ok"}]})
    api_falsa.rotas["/LiveTv/Channels"] = lambda q: (200, {"Items": [{"Name": "A"}], "TotalRecordCount": total[0]})
    api_falsa.rotas["/Plugins"] = lambda q: (200, [])
    api_falsa.rotas["/System/Configuration/livetv"] = lambda q: (200, {"TunerHosts": [], "ListingProviders": []})
    api_falsa.rotas["/ScheduledTasks"] = lambda q: (200, [])
    app.var_jf_url.set(api_falsa.base)
    app.var_jf_chave_jellyfin.set("chave")
    app._canais = [Canal("A", "https://a.org/1"), Canal("B", "https://a.org/2")]
    assert app.item_saude_tv() is None                                   # ainda não consultou: nada
    assert app.conferir_saude_tv(agora=1000.0)
    fim = time.time() + 10
    while time.time() < fim and app._saude_tv_rodando:
        time.sleep(0.05)
    assert app.item_saude_tv() == ("TV: 11129 canais no Jellyfin, a lista tem 2", False)
    assert ("TV: 11129 canais no Jellyfin, a lista tem 2", False) in app.itens_saude()
    assert not app.conferir_saude_tv(agora=1000.0 + 60)                  # 30 min entre consultas
    total[0] = 2
    assert app.conferir_saude_tv(agora=1000.0 + 31 * 60)
    fim = time.time() + 10
    while time.time() < fim and app._saude_tv_rodando:
        time.sleep(0.05)
    assert app.item_saude_tv() == ("TV: 2 canais (os da sua lista)", True)

    mensagens = []
    app.escolher = lambda t, m, opcoes, **k: (mensagens.append((m, opcoes)), None)[1]
    app.ao_diagnostico_tv()
    esperar(app)
    for _ in range(20):
        app.update()
        time.sleep(0.03)
    texto, opcoes = next((m, o) for m, o in mensagens if "Tudo certo" in m)
    assert "Se os canais não são da sua lista" not in texto and opcoes == ("Copiar o diagnóstico",)



def test_coletor_de_programacao_no_painel_de_saude_e_aviso_quando_para(app, monkeypatch, tmp_path):
    from jellyfin_tools import epg_iptv
    from jellyfin_tools.notificacoes import Notificador
    from videoscraper import config

    def consultar(agora):
        assert app.conferir_saude_coletor(agora=agora)
        fim = time.time() + 10
        while time.time() < fim and app._saude_coletor_rodando:
            time.sleep(0.02)
        return app.item_saude_coletor()
    assert not app.conferir_saude_coletor(agora=1.0) and app.item_saude_coletor() is None   # sem coletor montado
    pasta = tmp_path / "tv"
    pasta.mkdir()
    (pasta / "channels.xml").write_text("<channels/>", encoding="utf-8")
    tudo = config.carregar()
    tudo["tv"] = {"pasta": str(pasta)}
    config.salvar(tudo)
    app.var_jf_discord.set("https://discord.example/webhook")
    avisos = []
    monkeypatch.setattr(Notificador, "enviar", lambda self, discord, telegram: avisos.append(discord) or True)
    estado, programas = ["rodando"], [None]
    monkeypatch.setattr(epg_iptv, "estado_do_coletor", lambda: estado[0])
    monkeypatch.setattr(epg_iptv, "programas_do_guia", lambda: programas[0])
    assert consultar(1000.0) == ("Programação: coletando (o guia ainda não respondeu)", None)
    assert not app.conferir_saude_coletor(agora=1000.0 + 60)            # 30 min entre consultas
    programas[0] = {"A.br": 10, "B.br": 0}
    assert consultar(1000.0 + 31 * 60) == ("Programação: coletor ok (2 canais)", True)
    assert ("Programação: coletor ok (2 canais)", True) in app.itens_saude()
    estado[0] = "Docker fechado"
    assert consultar(1000.0 + 62 * 60) == ("Programação: Docker fechado (abra o Docker Desktop)", False)
    assert len(avisos) == 1 and "parou" in avisos[0] and "Docker fechado" in avisos[0]   # avisa quando PARA
    consultar(1000.0 + 93 * 60)
    assert len(avisos) == 1                                             # continua parado: não repete

def test_desmarcados_continuam_desmarcados_ao_previsualizar_de_novo(app, tmp_path):
    origem = tmp_path / "Baixados"
    for nome in ("Cidade.de.Deus.2002.1080p.mkv", "Matrix.1999.1080p.mkv", "Up.2009.1080p.mkv"):
        _video_grande(origem / nome)
    filmes = tmp_path / "Filmes"
    filmes.mkdir()
    app.mostrar_aba("Jellyfin")
    app.seletor_modo.set("Filmes")
    app._ao_trocar_modo("Filmes")
    app.var_jf_origem.set(str(origem))
    app.var_jf_destino.set(str(filmes))
    app.var_jf_legendas.set(False)

    def linha(nome):
        return next(i for i in app._ordem_jf if app.tabela_jf.set(i, "atual") == nome)
    app.bt_previa.invoke()
    esperar(app)
    app.marcar_mover_jf([linha("Matrix.1999.1080p.mkv"), linha("Up.2009.1080p.mkv")], False)
    app.bt_previa.invoke()                                             # de novo: continuam ☐
    esperar(app)
    assert {app.tabela_jf.set(i, "atual") for i in app.nao_mover_jf()} == {"Matrix.1999.1080p.mkv", "Up.2009.1080p.mkv"}
    app.marcar_mover_jf([linha("Up.2009.1080p.mkv")], True)              # marcou de novo: esquece
    app.limpar_tabela_jf()                                             # (ex.: abriu o Relatório)
    app.bt_previa.invoke()
    esperar(app)
    assert [app.tabela_jf.set(i, "atual") for i in app.nao_mover_jf()] == ["Matrix.1999.1080p.mkv"]


def test_escolher_no_tmdb_quando_ha_series_com_o_mesmo_nome(app, tmdb_gui, tmp_path):
    """Três 'Tom and Jerry' no TMDB: a pessoa escolhe a de 1940, a escolha vira regra e a prévia refaz."""
    def busca(q):
        resultados = [
            {"id": 230000, "name": "Tom e Jerry na Singapura", "original_name": "Tom and Jerry",
             "first_air_date": "2023-05-01", "overview": "Em Singapura."},
            {"id": 2000, "name": "Tom and Jerry", "original_name": "Tom and Jerry", "first_air_date": "1940-02-10",
             "overview": "Os curtas clássicos."},
            {"id": 3000, "name": "O Show de Tom e Jerry", "original_name": "The Tom and Jerry Show",
             "first_air_date": "2014-04-09"}]
        ano = q.get("first_air_date_year", [None])[0]
        return 200, {"results": [r for r in resultados if not ano or r["first_air_date"].startswith(ano)]}
    tmdb_gui.rotas["/3/search/tv"] = busca
    origem, series = tmp_path / "Baixados", tmp_path / "Series"
    series.mkdir()
    _video_grande(origem / "Tom and Jerry" / "Tom and Jerry EP37 Professor Tom.mkv")     # sem o ano: vai na 2023
    app.mostrar_aba("Jellyfin")
    app.seletor_modo.set("Séries")
    app._ao_trocar_modo("Séries")
    app.var_jf_origem.set(str(origem))
    app.var_jf_destino.set(str(series))
    app.var_jf_legendas.set(False)
    app.var_jf_tmdb.set(True)
    app.var_jf_chave_tmdb.set("boa")
    app.bt_previa.invoke()
    esperar(app)
    assert "Tom e Jerry na Singapura" in app._movimentos_previa[0].destino_curto

    listas = []
    app.escolher_da_lista = lambda titulo, msg, itens, botao="", marcado=None, **k: (
        listas.append((itens, marcado)), next(n for n, i in enumerate(itens) if "(1940)" in i))[1]
    app.tabela_jf.selection_set(["0"])
    app.ao_escolher_no_tmdb()
    esperar(app)
    fim = time.time() + 20
    while time.time() < fim and (not listas or app.trabalhando or "1940" not in app._movimentos_previa[0].destino_curto):
        app.update()
        time.sleep(0.05)
    itens, marcado = listas[0]
    assert len(itens) == 3 and "← a de agora" in itens[marcado] and "Singapura" in itens[marcado]
    assert any("original: The Tom and Jerry Show" in i for i in itens)
    assert app._movimentos_previa[0].destino_curto == \
        "Tom and Jerry (1940)/Season 01/Tom and Jerry S01E37 - Professor Tom.mkv"
    regra = app.regras_de_nome()[0]
    assert (regra.titulo, regra.ano, regra.caminho) == ("Tom and Jerry", 1940, str(origem / "Tom and Jerry"))


def test_escolher_no_tmdb_sem_selecao_ou_sem_chave(app):
    app.mostrar_aba("Jellyfin")
    app.ao_escolher_no_tmdb()
    assert app.caixas[-1][1] == "Escolher no TMDB" and "Pré-visualize" in app.caixas[-1][2]


def test_conferencia_semanal_dos_canais_avisa_os_que_sempre_falham(app, api_falsa):
    from datetime import datetime, timedelta
    from jellyfin_tools.tv_ao_vivo import Canal
    from videoscraper import config
    api_falsa.rotas["/bom.m3u8"] = lambda q: (200, b"#EXTM3U\n#EXT-X-VERSION:3\nseg.ts\n",
                                              {"Content-Type": "application/vnd.apple.mpegurl"})
    api_falsa.rotas["/morto.m3u8"] = lambda q: (404, b"nao")
    bom, morto = api_falsa.base + "/bom.m3u8", api_falsa.base + "/morto.m3u8"
    from jellyfin_tools.tv_ao_vivo import salvar_canais
    app._canais = [Canal("Bom", bom), Canal("Morto", morto)]
    salvar_canais(app.arquivo_canais, app._canais)
    app._historico_canais = {morto: [False, False]}                  # já falhou nas 2 últimas
    agora = datetime(2026, 10, 6, 3, 0)
    assert not app.conferencia_semanal_tv(agora=agora, relogio=1.0)  # opção desligada: nada
    tudo = config.carregar()
    tudo["tv"] = {"semanal": True}
    config.salvar(tudo)
    assert not app.conferencia_semanal_tv(agora=agora, relogio=2.0)  # olhou há pouco: espera 10 min
    perguntas = []
    app.escolher = lambda t, m, opcoes, **k: (perguntas.append(m), opcoes[0])[1]
    assert app.conferencia_semanal_tv(agora=agora, relogio=1000.0)
    fim = time.time() + 30
    while time.time() < fim and app._semanal_resultado is None:
        app.update()
        time.sleep(0.05)
    assert app._semanal_resultado == (2, 1, 1)
    assert app.historico_canais[morto] == [False, False, False]
    assert "1 canal(is) falharam em TODAS" in perguntas[0]
    for _ in range(20):
        app.update()
        time.sleep(0.03)
    janela = app.janela_canais                                        # abriu com o morto selecionado
    assert [janela.tabela.item(i, "text") for i in janela.tabela.selection()] == ["Morto"]
    assert app.item_saude_tv() == ("TV: 1 sempre falham", False)
    assert config.carregar()["tv_semanal"]["quando"] == agora.isoformat(timespec="seconds")
    assert config.carregar()["tv"]["semanal"] is True                 # a janela aberta não apagou a opção
    assert not app.conferencia_semanal_tv(agora=agora + timedelta(days=3), relogio=5000.0)   # só depois de 7 dias
    assert app.conferencia_semanal_tv(agora=agora + timedelta(days=7), relogio=9000.0)
    fim = time.time() + 30
    while time.time() < fim and app._semanal_rodando:
        time.sleep(0.05)


def test_videos_memoria_de_downloads_e_filtro_por_coluna(app):
    from datetime import datetime, timedelta
    from videoscraper.extracao import LinkVideo
    app.mostrar_aba("Vídeos")
    app.definir_url("https://archive.org/details/serie")
    links = [LinkVideo(f"https://archive.org/download/serie/ep{n}.mkv", "https://archive.org/details/serie",
                       "archive.org", f"Episódio 1x0{n}", licenca="Domínio público" if n < 4 else "") for n in range(1, 6)]
    app.memoria_downloads.registrar(links[0], "C:/v/ep1.mkv", quando=datetime.now() - timedelta(days=200))
    app.memoria_downloads.registrar(links[1], "C:/v/ep2.mkv")
    app._mostrar_links(links)
    assert app.tabela.set("0", "status").endswith("já baixado (" + (datetime.now() - timedelta(days=200)).strftime("%d/%m/%Y") + ")")
    assert app.valor_video("status", "0") == "já baixado" and app.valor_video("status", "2") == "(não baixado)"

    # baixar: pergunta se pula os já baixados
    perguntas, baixou = [], []
    respostas = iter(["Pular os 2 já baixados"])
    app.escolher = lambda t, m, opcoes, **k: (perguntas.append((t, m)), next(respostas))[1]
    app._rodar = lambda status, tarefa: baixou.append(status)
    app._filtrar_por_licenca = lambda lista: lista                     # (a licença tem teste próprio)
    escolhidos = app._filtrar_ja_baixados(links[:3])
    assert escolhidos == [links[2]] and "2 de 3 vídeo(s) já foram baixados" in perguntas[0][1]

    # filtro por coluna: só os "(não baixado)" da Situação e a Licença
    assert "▾" in app.tabela.heading("status", "text")
    app.abrir_filtro_videos("status")
    texto, marcados, aplicar = app._filtro_aberto_videos
    marcados.discard("já baixado")
    aplicar()
    app.update()
    assert app.visiveis_videos() == ["2", "3", "4"] and app.tabela.heading("status", "text") == "Situação ▼"
    assert app._extras_tabela[str(app.tabela)][0].cget("text") == "3 de 5"
    app.aplicar_filtro_videos("licenca", {"Domínio público"})
    assert app.visiveis_videos() == ["2"]
    app.tabela.selection_set(["2"])
    perguntas.clear()
    app.escolher = lambda t, m, opcoes, **k: (perguntas.append((t, m)), opcoes[0])[1]
    app.ao_baixar_todos()                                              # com filtro: só o que está à vista
    assert baixou == ["Baixando vídeos..."] and perguntas == []
    app.atualizar_situacao("0", "baixado", "ok")                       # linha escondida: não quebra
    app.tirar_filtros_videos()
    assert app.visiveis_videos() == ["0", "1", "2", "3", "4"] and "▾" in app.tabela.heading("licenca", "text")

    # memória por período: apaga os de mais de 90 dias (o ep1, de 200 dias)
    app.escolher_da_lista = lambda t, m, itens, botao="", marcado=None, **k: next(
        n for n, i in enumerate(itens) if "mais de 90 dias" in i)
    app.ao_memoria_downloads()
    assert app.memoria_downloads.baixado(links[0]) is None and app.memoria_downloads.baixado(links[1]) is not None
    assert "já baixado" not in app.tabela.set("0", "status") and "já baixado" in app.tabela.set("1", "status")
    # selecionados: esquece o ep2
    app.tabela.selection_set(["1"])
    app.escolher_da_lista = lambda t, m, itens, botao="", marcado=None, **k: (
        0 if itens[0].startswith("Esquecer os 1 selecionado") else None)
    app.ao_memoria_downloads()
    assert app.memoria_downloads.baixado(links[1]) is None and app.tabela.set("1", "status") == ""
    app._mostrar_links(links)                                          # busca nova: nenhum filtro sobra
    assert len(app.visiveis_videos()) == 5


def test_vigia_nao_mexe_no_que_voce_desmarcou(app, tmp_path):
    origem, filmes = tmp_path / "Downloads", tmp_path / "Filmes"
    origem.mkdir()
    for nome in ("Matrix.1999.mkv", "Up.2009.mkv"):
        (origem / nome).write_bytes(b"v")
        os.utime(origem / nome, (time.time() - 3600, time.time() - 3600))
    app.mostrar_aba("Jellyfin")
    app.seletor_modo.set("Filmes")
    app._ao_trocar_modo("Filmes")
    app.var_jf_origem.set(str(origem))
    app.var_jf_destino.set(str(filmes))
    app.var_jf_legendas.set(False)
    app.bt_previa.invoke()
    esperar(app)
    up = next(i for i in app._ordem_jf if app.tabela_jf.set(i, "atual") == "Up.2009.mkv")
    app.marcar_mover_jf([up], False)                                   # ☐ Up: não mexer
    app.var_jf_vigiar.set(True)
    app.ao_alternar_vigia()
    fim = time.time() + 30
    while not (filmes / "Matrix (1999)" / "Matrix (1999).mkv").exists() and time.time() < fim:
        app.update()
        time.sleep(0.05)
    esperar(app)
    app.var_jf_vigiar.set(False)
    app.ao_alternar_vigia()
    assert (filmes / "Matrix (1999)" / "Matrix (1999).mkv").exists()
    assert (origem / "Up.2009.mkv").exists() and not (filmes / "Up (2009)").exists()


def test_pasta_dos_videos_nunca_cai_na_pasta_do_windows(app, tmp_path, monkeypatch):
    """Caso real: aberto pelo "Iniciar com o Windows", a pasta atual é C:\\Windows\\System32 e o download dava
    PermissionError em C:\\WINDOWS\\system32\\videos_baixados."""
    windows = tmp_path / "WINDOWS"
    monkeypatch.setenv("SystemRoot", str(windows))
    padrao = app_moderna.PASTA_PADRAO
    assert os.path.isabs(padrao)                                           # nunca relativo à pasta atual
    assert app_moderna.pasta_segura(str(windows / "system32" / "videos_baixados"), padrao) == padrao
    assert app_moderna.pasta_segura(str(windows), padrao) == padrao
    assert app_moderna.pasta_segura("", padrao) == padrao
    assert app_moderna.pasta_segura("filmes", padrao) == str(Path.home() / "Videos" / "filmes")   # relativo
    assert app_moderna.pasta_segura(str(tmp_path / "WINDOWS2" / "x"), padrao) == str(tmp_path / "WINDOWS2" / "x")
    boa = str(tmp_path / "meus_videos")
    assert app_moderna.pasta_segura(boa, padrao) == boa

    app.var_pasta.set(str(windows / "system32" / "videos_baixados"))
    o = app.obter_opcoes()
    assert o.pasta == padrao and app.var_pasta.get() == padrao              # trocou, e a tela mostra
    app.var_pasta.set(boa)
    assert app.obter_opcoes().pasta == boa
    from videoscraper import config
    assert config.carregar()["videos"]["pasta"] == boa                       # lembrada para a próxima vez
    app.var_pasta.set("")
    app._carregar_config()                                                  # ao abrir de novo
    assert app.var_pasta.get() == boa

    tudo = config.carregar()
    tudo.setdefault("jellyfin", {})["origem"] = str(windows / "system32" / "videos_baixados")
    config.salvar(tudo)
    app._carregar_config()
    assert app.var_jf_origem.get() == padrao                                 # a origem salva também é consertada


def test_escolher_no_tmdb_procura_outro_nome_e_vincula_todos_os_arquivos(app, tmdb_gui, tmp_path):
    """Caso real: 'Juni Lee S01E04.mkv' (nome curto) = 'A Vida e Aventuras de Juniper Lee'. A busca por "Juni Lee"
    não acha; procurando "Juniper Lee" na própria lista acha. A escolha vale para TODOS os "Juni Lee" (a pasta da
    série inteira, e só o arquivo solto na pasta misturada) e só eles são analisados de novo."""
    juniper = {"id": 1100, "name": "A Vida e Aventuras de Juniper Lee",
               "original_name": "The Life and Times of Juniper Lee", "first_air_date": "2005-05-30"}

    def busca(q):
        termo = q["query"][0].lower()
        if "juniper" in termo:
            return 200, {"results": [juniper]}
        if "pica" in termo:
            return 200, {"results": [{"id": 77, "name": "Pica-Pau", "original_name": "Woody Woodpecker",
                                      "first_air_date": "1957-10-03"}]}
        return 200, {"results": []}
    tmdb_gui.rotas["/3/search/tv"] = busca
    origem, series = tmp_path / "DESENHOS", tmp_path / "Series"
    series.mkdir()
    for nome in ("Juni Lee S01E04.mkv", "Juni Lee S01E05.mkv"):
        _video_grande(origem / "Juni Lee" / "Season 01" / nome)
    _video_grande(origem / "Juni Lee S01E06.mkv")                       # solto, junto com outra série
    _video_grande(origem / "Pica-Pau S01E01.mkv")
    app.mostrar_aba("Jellyfin")
    app.seletor_modo.set("Séries")
    app._ao_trocar_modo("Séries")
    app.var_jf_origem.set(str(origem))
    app.var_jf_destino.set(str(series))
    app.var_jf_legendas.set(False)
    app.var_jf_tmdb.set(True)
    app.var_jf_chave_tmdb.set("boa")
    app.bt_previa.invoke()
    esperar(app)
    linha = next(str(i) for i, m in enumerate(app._movimentos_previa) if m.origem.name == "Juni Lee S01E04.mkv")

    vistos = []

    def escolher(titulo, msg, itens, botao="", marcado=None, procurar=None, termo=""):
        vistos.append((msg, list(itens), termo))
        novos = procurar("Juniper Lee")                                  # o campo "Procurar" da lista
        vistos.append(novos)
        return 0
    app.escolher_da_lista = escolher
    app.tabela_jf.selection_set([linha])                                  # só UM selecionado
    app.ao_escolher_no_tmdb()
    esperar(app)
    fim = time.time() + 20
    while time.time() < fim and (len(vistos) < 2 or app.trabalhando or "analisados de novo" not in app.var_status.get()):
        app.update()
        time.sleep(0.05)
    msg, itens, termo = vistos[0]
    assert termo == "Juni Lee" and itens == [] and "não achou nada" in msg and "3 arquivo(s)" in msg
    assert vistos[1][0].startswith("A Vida e Aventuras de Juniper Lee (2005)")
    destinos = {m.origem.name: m.destino_curto for m in app._movimentos_previa}
    for ep in ("04", "05", "06"):
        assert destinos[f"Juni Lee S01E{ep}.mkv"].startswith("A Vida e Aventuras de Juniper Lee (2005)/Season 01/")
    assert destinos["Pica-Pau S01E01.mkv"].startswith("Pica-Pau (1957)/")    # a outra série não mudou
    assert "3 arquivo(s) analisados de novo" in app.var_status.get()
    caminhos = sorted(r.caminho for r in app.regras_de_nome())
    assert caminhos == sorted([str(origem / "Juni Lee" / "Season 01"), str(origem / "Juni Lee S01E06.mkv")])


def test_dialogo_lista_procura_sem_travar(app):
    from videoscraper.gui_moderna import DialogoLista
    pedidos = []

    def procurar(texto):
        pedidos.append(texto)
        time.sleep(0.2)                                               # como uma consulta ao TMDB
        return [f"{texto} (2005)", f"{texto} (2010)"]
    dialogo = DialogoLista(app, "Escolher no TMDB", "nada achado", [], procurar=procurar, termo="Juni Lee")
    assert dialogo.var_termo.get() == "Juni Lee" and dialogo.lista.size() == 0
    dialogo.var_termo.set("Juniper Lee")
    dialogo.procurar()
    assert dialogo.bt_procurar.cget("state") == "disabled"             # procurando (a janela continua viva)
    fim = time.time() + 5
    while time.time() < fim and dialogo.lista.size() == 0:
        app.update()
        time.sleep(0.03)
    assert pedidos == ["Juniper Lee"] and dialogo.lista.get(0) == "Juniper Lee (2005)"
    assert "2 opção(ões)" in dialogo.lb_mensagem.cget("text") and dialogo.bt_procurar.cget("state") == "normal"
    dialogo._ok()
    assert dialogo.resposta == 0


def test_tv_coluna_idioma_com_filtro_e_numerar_por_idioma(app):
    from jellyfin_tools.tv_ao_vivo import Canal
    janela = _abrir_tv(app, [Canal("CNN", "https://a.org/1", "News", id_guia="CNN.us"),
                             Canal("Globo Brasil", "https://a.org/2", "Abertos"),
                             Canal("Canal Sur", "https://a.org/3", "General", idioma="spa"),
                             Canal("Record (Brazil)", "https://a.org/4", "Abertos")])
    assert janela.tabela.set("0", "idioma") == "English" and janela.tabela.set("2", "idioma") == "Español"
    assert dict(janela.valores_da_coluna("idioma")) == {"English": 1, "Español": 1, "Português": 2}
    janela.aplicar_filtro("idioma", {"Português"})                      # filtrar por idioma
    assert [janela.tabela.item(i, "text") for i in janela.tabela.get_children()] == ["Globo Brasil", "Record (Brazil)"]
    janela.limpar_filtros()
    app.escolher = lambda t, m, opcoes, **k: next(o for o in opcoes if o.startswith("Por idioma"))
    janela.bt_numerar.invoke()
    assert [(c.nome, c.numero) for c in app._canais] == [("Globo Brasil", "1"), ("Record (Brazil)", "2"),
                                                         ("CNN", "101"), ("Canal Sur", "201")]


def test_exportar_e_importar_configuracoes_pela_janela(app, tmp_path):
    app.var_jf_origem.set(str(tmp_path / "Downloads"))
    app.var_jf_chave_tmdb.set("chave-secreta")
    destino = tmp_path / "exportado.zip"
    app._pedir_arquivo_zip = lambda salvar: str(destino)
    app.escolher = lambda t, m, opcoes, **k: opcoes[0]                  # "Sem as chaves"
    app.bt_exportar_config.invoke()
    assert app.caixas[-1][:2] == ("sucesso", "Exportar configurações") and destino.is_file()
    import json
    import zipfile
    with zipfile.ZipFile(destino) as z:
        dados = json.loads(z.read("config.json"))["jellyfin"]
    assert dados["origem"] == str(tmp_path / "Downloads") and "chave_tmdb" not in dados
    app.var_jf_origem.set("outra coisa")
    app.bt_importar_config.invoke()                                     # perguntar() devolve True no teste
    assert app.var_jf_origem.get() == str(tmp_path / "Downloads")      # voltou o da exportação
    assert app.caixas[-1][:2] == ("sucesso", "Importar configurações") and "backups" in app.caixas[-1][2]


def test_agendar_tarefa_pela_janela(app, monkeypatch):
    from videoscraper import agendador
    feitos = []
    monkeypatch.setattr(agendador, "listar", lambda: [])
    monkeypatch.setattr(agendador, "agendar", lambda c, f, h: feitos.append((c, f, h)) or agendador.nome_da_tarefa(c))
    app.pedir_agendamento = lambda c, e, f: {"acao": "agendar", "comandos": ["--conferir-canais"],
                                             "frequencia": "Todo dia", "hora": "22:00"}
    app.bt_agendar.invoke()
    assert feitos == [("--conferir-canais", "Todo dia", "22:00")]
    assert app.caixas[-1][0] == "sucesso" and "Maestro\\conferir-canais" in app.caixas[-1][2]
    # VÁRIAS de uma vez: a mesma frequência, uma a cada 15 min (a das 23:45 passa da meia-noite)
    feitos.clear()
    app.pedir_agendamento = lambda c, e, f: {"acao": "agendar", "comandos": ["--organizar", "--conferir-canais",
                                                                              "--traduzir-legendas"],
                                             "frequencia": "Todo dia", "hora": "23:00"}
    app.bt_agendar.invoke()
    assert feitos == [("--organizar", "Todo dia", "23:00"), ("--conferir-canais", "Todo dia", "23:15"),
                      ("--traduzir-legendas", "Todo dia", "23:30")]
    assert app.caixas[-1][0] == "sucesso" and "23:15  Conferir os canais" in app.caixas[-1][2]
    assert agendador.escalonar("23:45", 2) == ["23:45", "00:00"]
    # tirar várias de uma vez
    tirados = []
    monkeypatch.setattr(agendador, "remover", lambda c: tirados.append(c))
    app.pedir_agendamento = lambda c, e, f: {"acao": "tirar", "comandos": ["--organizar", "--dublar"],
                                             "frequencia": "Todo dia", "hora": "06:00"}
    app.bt_agendar.invoke()
    assert tirados == ["--organizar", "--dublar"] and "Saíram do agendamento" in app.caixas[-1][2]


def test_janela_agendar_caixas_e_botoes(app):
    """A janela de verdade: caixas de marcar, "Marcar todas", "Marcar as já agendadas" e os botões com a contagem."""
    from videoscraper import agendador
    from videoscraper.gui_moderna import DialogoAgendar
    janela = DialogoAgendar(app, agendador.COMANDOS, {"--dublar": "11/10/2026 06:00:00"}, agendador.FREQUENCIAS)
    assert janela.bt_agendar.cget("state") == "disabled" and janela.bt_tirar.cget("state") == "disabled"
    janela.bt_marcar_todas.invoke()
    assert janela.marcados() == list(agendador.COMANDOS)
    assert janela.bt_agendar.cget("text") == f"Agendar {len(agendador.COMANDOS)} marcada(s)"
    assert janela.bt_tirar.cget("text") == "Tirar 1 do agendamento"
    assert "uma a cada 15 minutos" in janela.lb_resumo.cget("text")
    janela.bt_desmarcar.invoke()
    assert janela.marcados() == []
    janela.bt_marcar_agendadas.invoke()
    assert janela.marcados() == ["--dublar"]
    janela.vars["--organizar"].set(True)
    janela.var_frequencia.set(agendador.FREQUENCIAS[1])
    janela.var_hora.set("21:30")
    janela.bt_agendar.invoke()
    assert janela.resultado == {"acao": "agendar", "comandos": ["--organizar", "--dublar"],
                                "frequencia": agendador.FREQUENCIAS[1], "hora": "21:30"}
    janela = DialogoAgendar(app, agendador.COMANDOS, {"--dublar": "amanhã"}, agendador.FREQUENCIAS)
    janela.bt_marcar_todas.invoke()
    janela.bt_tirar.invoke()                                            # só as que estão agendadas saem
    assert janela.resultado["acao"] == "tirar" and janela.resultado["comandos"] == ["--dublar"]


def test_resumo_do_dia_pela_janela(app, api_falsa):
    import json as _json
    from datetime import datetime as _dt
    api_falsa.rotas["/discord"] = lambda q: (204, b"")
    app.var_jf_discord.set(api_falsa.base + "/discord")
    app.resumo_diario.registrar("organizados", 2, _dt(2026, 10, 10, 10))
    assert not app.enviar_resumo_diario(_dt(2026, 10, 10, 22))           # opção desligada: não manda
    app.var_jf_resumo_diario.set(True)
    assert not app.enviar_resumo_diario(_dt(2026, 10, 10, 20))           # antes das 21h
    assert app.enviar_resumo_diario(_dt(2026, 10, 10, 22))
    fim = time.time() + 5
    while not [p for p in api_falsa.pedidos if p["caminho"] == "/discord"] and time.time() < fim:
        time.sleep(0.05)
    [pedido] = [p for p in api_falsa.pedidos if p["caminho"] == "/discord"]
    assert "2 filme(s)/episódio(s) organizado(s)" in _json.loads(pedido["corpo"])["content"]
    assert not app.enviar_resumo_diario(_dt(2026, 10, 10, 23))           # uma vez por dia


def test_sincronizar_legendas_pela_janela(app, tmp_path, monkeypatch):
    np = pytest.importorskip("numpy")  # noqa: F841
    from jellyfin_tools.sincronia import deslocar, regua_da_legenda
    from jellyfin_tools.traducao import gerar_srt
    from tests.test_sincronia import falas_aleatorias
    falas, total = falas_aleatorias()
    filmes = tmp_path / "Filmes" / "A (2001)"
    filmes.mkdir(parents=True)
    (filmes / "A (2001).mkv").write_bytes(b"\0" * 2_000_000)
    (filmes / "A (2001).pt-BR.srt").write_text(gerar_srt(deslocar(falas, 1.5)), encoding="utf-8")
    app._destinos.update({"Filmes": str(tmp_path / "Filmes"), "Séries": ""})
    app.var_jf_destino.set(str(tmp_path / "Filmes"))
    audio = regua_da_legenda(falas, int(total / 0.01))
    monkeypatch.setattr(app_moderna, "sincronizar",
                        lambda leg, vid: __import__("jellyfin_tools.sincronia", fromlist=["x"]).sincronizar(
                            leg, vid, ouvir=lambda v: audio))
    app.escolher = lambda t, m, opcoes, **k: opcoes[0]
    app.bt_sincronizar.invoke()
    esperar(app)
    esperar(app)
    assert app.caixas[-1][1] == "Sincronizar legendas" and "Corrigidas: 1" in app.caixas[-1][2]
    assert "-1.50 s" in app.caixas[-1][2] and (filmes / "A (2001).pt-BR.srt.original").exists()
    app.bt_sincronizar.invoke()                                        # de novo: já conferida
    esperar(app)
    esperar(app)
    assert "Nenhuma legenda nova" in app.caixas[-1][2]


def test_traducao_economica_em_lote_pela_janela(app, tmp_path, monkeypatch):
    from jellyfin_tools.traducao import Tradutor, ler_srt
    from tests.test_traducao import SRT, ClienteFalso
    from tests.test_traducao_lote import LoteFalso
    filmes = tmp_path / "Filmes" / "A (2001)"
    filmes.mkdir(parents=True)
    (filmes / "A (2001).mkv").write_bytes(b"\0" * 2_000_000)
    (filmes / "A (2001).en.srt").write_text(SRT, encoding="utf-8")
    app._destinos.update({"Filmes": str(tmp_path / "Filmes"), "Séries": ""})
    app.var_jf_destino.set(str(tmp_path / "Filmes"))
    app.var_jf_chave_claude.set("sk-ant-teste")
    cliente = ClienteFalso()
    cliente.batches = LoteFalso(cliente)
    monkeypatch.setattr(app_moderna, "Tradutor", lambda **k: Tradutor(cliente=cliente, **k))
    perguntas = []
    app.escolher = lambda t, m, opcoes, **k: (perguntas.append((m, opcoes)), opcoes[1])[1]   # "Econômico"
    app.bt_traduzir_legendas.invoke()
    esperar(app)
    esperar(app)
    assert perguntas[0][1][1] == "Econômico (metade do preço)" and "metade do preço (~US$" in perguntas[0][0]
    assert "modo econômico" in app.caixas[-1][2] and not cliente.pedidos
    assert any("Tradução em lote: 1 aguardando" in texto for texto, _ in app.itens_saude())
    assert app.conferir_lotes(agora=1e9)                                   # ainda processando
    fim = time.time() + 5
    while app._lotes_rodando and time.time() < fim:
        time.sleep(0.05)
    assert not (filmes / "A (2001).pt-BR.srt").exists()
    cliente.batches.terminado = True
    assert not app.conferir_lotes(agora=1e9 + 60)                          # espera 10 min entre conferências
    assert app.conferir_lotes(agora=1e9 + 700)
    while app._lotes_rodando and time.time() < fim + 5:
        time.sleep(0.05)
    assert ler_srt((filmes / "A (2001).pt-BR.srt").read_text(encoding="utf-8"))[0].texto == "PT: Hello, how are you?"
    assert not any("Tradução em lote" in texto for texto, _ in app.itens_saude())


def test_testar_chave_da_anthropic_e_painel_de_saude(app, monkeypatch):
    from jellyfin_tools.traducao import ErroTraducao
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    app.var_jf_chave_claude.set("")
    assert ("Claude (API): sem chave", None) in app.itens_saude()
    app.bt_testar_claude.invoke()
    assert app.caixas[-1][0] == "aviso" and "console.anthropic.com" in app.caixas[-1][2]
    app.var_jf_chave_claude.set("sk-ant-teste")
    assert ("Claude (API): chave não testada", None) in app.itens_saude()
    monkeypatch.setattr(app_moderna, "testar_chave", lambda chave, modelo: "Claude Sonnet 4.6")
    app.bt_testar_claude.invoke()
    esperar(app)
    assert ("Claude (API) ativa", True) in app.itens_saude()
    assert "API ativa · Claude Sonnet 4.6" in app.lb_estado_claude.cget("text")
    assert "Claude (API) ativa" in app.lb_saude.cget("text")

    def recusada(chave, modelo):
        raise ErroTraducao("a chave de API foi recusada (confira em console.anthropic.com)")
    monkeypatch.setattr(app_moderna, "testar_chave", recusada)
    app.bt_testar_claude.invoke()
    esperar(app)
    assert ("Claude (API): chave recusada", False) in app.itens_saude() and app.caixas[-1][0] == "erro"
    assert any(t.startswith("Whisper (baixa na 1ª vez) · Piper (baixa na 1ª vez)") for t, _ in app.itens_saude())


def test_cadastrou_o_cartao_do_gemini_vale_na_hora_e_avisa_se_o_google_ainda_diz_gratis(app, monkeypatch, tmp_path):
    """Configurações > Gastos: escolher "Paga" vale na hora (sem salvar) e esquece a resposta antiga do Google; se o
    Google responder de novo como chave grátis, o painel de saúde avisa. O link abre a página do faturamento."""
    from jellyfin_tools import gastos
    abertos = []
    monkeypatch.setattr(app_moderna.webbrowser, "open", abertos.append)
    monkeypatch.setattr(app_moderna.automacao, "arquivo_gastos", lambda: tmp_path / "gastos.json")
    app.var_jf_plano_gemini.set(app.PLANOS_GEMINI[1])
    app.ao_escolher_plano_gemini(app.PLANOS_GEMINI[1])
    assert gastos.atual().plano_gemini == "gratis"
    gastos.anotar_gemini_gratis()                                       # o limite da camada grátis, hoje
    assert not gastos.atual().aviso_do_plano()                          # grátis com grátis: bate
    app.var_jf_plano_gemini.set(app.PLANOS_GEMINI[2])
    app.ao_escolher_plano_gemini(app.PLANOS_GEMINI[2])                  # acabou de cadastrar o cartão
    assert gastos.atual().plano_gemini == "pago" and not gastos.atual().aviso_do_plano()
    gastos.anotar_gemini_gratis()                                       # mas o Google ainda responde como grátis
    item = app.item_saude_gastos()
    assert item[1] is False and "ainda trata a chave como grátis" in item[0]
    app.atualizar_gastos()
    assert "faturamento ainda não está ativo" in app.lb_cotas.cget("text")
    app.ao_ativar_faturamento_gemini()
    assert abertos == ["https://aistudio.google.com/apikey"] and "Set up billing" in app.caixas[-1][2]


def test_quanto_resta_hoje_do_gemini_gratis_em_gastos_e_no_painel(app, monkeypatch, tmp_path):
    """Chave grátis do Gemini: Configurações > Gastos mostra quanto resta HOJE (com "Atualizar") e o painel do topo
    resume ("Gemini grátis hoje: voz 3/15 (restam ~12)"), vermelho quando o limite do dia acaba."""
    from jellyfin_tools import gastos
    monkeypatch.setattr(app_moderna.automacao, "arquivo_gastos", lambda: tmp_path / "gastos.json")
    app.var_jf_plano_gemini.set(app.PLANOS_GEMINI[1])
    app.ao_escolher_plano_gemini(app.PLANOS_GEMINI[1])
    assert "Nenhum pedido ao Gemini hoje" in app.lb_gemini_hoje.cget("text")
    assert not any(t.startswith("Gemini grátis hoje") for t, _ in app.itens_saude())
    for _ in range(3):
        gastos.contar_pedido_gemini("voz")
    gastos.anotar_limite_gemini("voz", por_dia=15)
    app.bt_atualizar_gemini_hoje.invoke()
    assert "Gemini (voz): 3 de 15 pedidos grátis hoje; restam ~12" in app.lb_gemini_hoje.cget("text")
    assert ("Gemini grátis hoje: voz 3/15 (restam ~12)", None) in app.itens_saude()
    gastos.anotar_limite_gemini("voz", esgotou=True)
    assert any(t.startswith("Gemini grátis hoje: voz ACABOU") and ok is False for t, ok in app.itens_saude())
    assert "o limite do dia ACABOU" in app.lb_gemini_hoje.cget("text")
    assert "Chave grátis do Gemini hoje:" in app.texto_do_teste([], 0.0, "/v/Filme.mkv")


def test_pergunta_antes_do_teste_quando_o_saldo_do_gemini_nao_da(app, monkeypatch, tmp_path):
    """Chave grátis com o limite do dia acabado: antes do teste a janela avisa e pergunta; "não" = não começa."""
    from jellyfin_tools import gastos
    monkeypatch.setattr(app_moderna.automacao, "arquivo_gastos", lambda: tmp_path / "gastos.json")
    app.var_jf_motor_voz.set(app.MOTORES_VOZ[1])
    app.var_jf_plano_gemini.set(app.PLANOS_GEMINI[1])
    app.ao_escolher_plano_gemini(app.PLANOS_GEMINI[1])
    o = app.obter_opcoes_jellyfin()
    perguntas = []
    app.perguntar = lambda titulo, texto: perguntas.append(texto) or False
    assert app._saldo_do_gemini_da(o, 30, "Fazer o teste mesmo assim?") is True and not perguntas   # sem limite
    gastos.anotar_limite_gemini("voz", por_dia=15, esgotou=True)
    assert app._saldo_do_gemini_da(o, 30, "Fazer o teste mesmo assim?") is False
    assert "já acabou hoje" in perguntas[0] and perguntas[0].endswith("Fazer o teste mesmo assim?")


def test_opcao_camada_de_emocao(app):
    """Configurações > Dublagem: "Camada de emoção" (ligada por padrão) vai para as opções da dublagem."""
    assert app.var_jf_camada_de_emocao.get() is True and app.obter_opcoes_jellyfin().camada_de_emocao is True
    app.var_jf_camada_de_emocao.set(False)
    assert app.obter_opcoes_jellyfin().camada_de_emocao is False


def test_link_embaixo_de_cada_chave_abre_o_site_certo(app, monkeypatch):
    """Configurações > Chaves de API: cada nome tem, embaixo, o link do site onde se cria a chave; o do Jellyfin abre
    a página das chaves no servidor do campo (e pede o endereço se estiver vazio)."""
    abertos = []
    monkeypatch.setattr(app_moderna.webbrowser, "open", abertos.append)
    assert set(app.links_das_chaves) == {"tmdb", "os", "subdl", "claude", "gemini", "cloud", "jellyfin"}
    assert all(l.cget("text").endswith("↗") for l in app.links_das_chaves.values())
    assert not hasattr(app, "bt_criar_chave_gemini")                  # o botão solto embaixo da lista saiu
    for chave in ("tmdb", "os", "subdl", "claude", "cloud"):
        app.ao_abrir_site_da_chave(chave)
    assert abertos == ["https://www.themoviedb.org/settings/api", "https://www.opensubtitles.com/consumers",
                       "https://subdl.com/panel/api", "https://console.anthropic.com/settings/keys",
                       "https://console.cloud.google.com/apis/credentials"]
    app.ao_abrir_site_da_chave("gemini")
    assert abertos[-1] == "https://aistudio.google.com/apikey" and "Create API key" in app.caixas[-1][2]
    app.var_jf_url.set("http://192.168.0.10:8096/")
    app.ao_abrir_site_da_chave("jellyfin")
    assert abertos[-1] == "http://192.168.0.10:8096/web/#/dashboard/keys"
    app.var_jf_url.set("")
    app.ao_abrir_site_da_chave("jellyfin")
    assert len(abertos) == 7 and app.caixas[-1][0] == "aviso" and "endereço do Jellyfin" in app.caixas[-1][2]
    app.mostrar_aba(app.ABA_CONFIG)                                     # o clique de verdade no link (à vista)
    app.mostrar_config("Chaves de API")
    app.update()
    link = app.links_das_chaves["tmdb"]
    assert link.winfo_ismapped()
    link._label.event_generate("<Button-1>", x=2, y=2)
    app.update()
    assert abertos[-1] == "https://www.themoviedb.org/settings/api"


def test_simular_a_vigia_mostra_sem_mover_nada(app, tmp_path):
    """Botão "O que a vigia faria agora?": a mesma conta da vigia, mas nada sai do lugar."""
    import os
    filmes = tmp_path / "Filmes_Organizados"
    pronto, baixando = filmes / "Interestelar.2014.1080p.mkv", filmes / "Duna.2021.mkv"
    for p, idade in ((pronto, 3600), (baixando, 0)):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"v" * 2048)
        os.utime(p, (time.time() - idade, time.time() - idade))
    app.mostrar_aba("Jellyfin")
    app.var_jf_legendas.set(False)
    app.definir_pastas_vigiadas([str(filmes)])
    app.bt_simular_vigia.invoke()
    esperar(app)
    assert pronto.is_file() and not (filmes / "Interestelar (2014)").exists()          # nada foi movido
    assert "Simulação da vigia: 1 seriam movidos" in app.var_status.get() and "NADA foi movido" in app.var_status.get()
    linhas = [app.tabela_jf.item(i, "values") for i in app.tabela_jf.get_children()]
    assert any("Interestelar (2014)" in " ".join(map(str, v)) for v in linhas)
    assert not any("Duna" in " ".join(map(str, v)) for v in linhas)                    # ainda baixando: fica fora
    assert app.bt_organizar.cget("state") == "disabled"                                 # simulação não libera
    pronto.unlink()
    app.bt_simular_vigia.invoke()
    esperar(app)
    esperar(app)
    assert "a vigia não moveria nada" in app.caixas[-1][2]


def test_voz_premium_do_gemini_pela_janela(app, tmp_path, monkeypatch):
    app.var_jf_dublagem_no_original.set(False)                   # este teste: o arquivo à parte
    from jellyfin_tools import dublagem, voz_gemini
    from tests.test_dublagem import FFMPEG, SRT, VozFalsa, video_de_teste
    from videoscraper import automacao
    if not FFMPEG:
        pytest.skip("sem ffmpeg")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    app.mostrar_aba("Jellyfin")
    # testar a chave (não gera áudio)
    app.var_jf_chave_gemini.set("")
    app.bt_testar_gemini.invoke()
    assert "Cole a chave do Google AI Studio" in app.caixas[-1][2]
    monkeypatch.setattr(voz_gemini, "testar_chave", lambda chave: f"Gemini 3.8 Flash TTS ({chave})")
    app.var_jf_chave_gemini.set("AIza-teste")
    app.var_jf_motor_voz.set(app.MOTORES_VOZ[1])
    app.var_jf_voz_gemini.set("Kore (feminina, firme)")
    app.bt_testar_gemini.invoke()
    esperar(app)
    assert "Voz premium ativa" in app.lb_estado_gemini.cget("text")
    assert ("Gemini (voz) ativa", True) in app.itens_saude()
    o = app.obter_opcoes_jellyfin()
    assert (o.motor_voz, o.voz_gemini, o.chave_gemini) == (app.MOTORES_VOZ[1], "Kore", "AIza-teste")
    # dublar com o Gemini: a confirmação mostra a estimativa e o motor é o do Gemini
    filmes = tmp_path / "Filmes"
    (filmes / "Nosferatu (1922)").mkdir(parents=True)
    video_de_teste(filmes / "Nosferatu (1922)" / "Nosferatu (1922).mkv")
    (filmes / "Nosferatu (1922)" / "Nosferatu (1922).pt-BR.srt").write_text(SRT, encoding="utf-8")
    app._destinos.update({"Filmes": str(filmes), "Séries": ""})
    app.var_jf_destino.set(str(filmes))
    criados, voz = [], VozFalsa()
    monkeypatch.setattr(voz_gemini, "MotorGemini", lambda chave, nome, **k: criados.append((chave, nome)) or voz)
    monkeypatch.setattr(app_moderna, "videos_para_dublar",
                        lambda *p, **k: dublagem.videos_para_dublar(*p, **{**k, "sondar": lambda v: (6.0, ["eng"])}))
    falas_longas = []

    class Adaptar:                                                   # o Claude, de mentira
        tradutor = type("T", (), {"pedidos": 1, "custo": 0.01})()

        def __call__(self, itens):
            falas_longas.extend(itens)
            return {}
    monkeypatch.setattr(automacao, "adaptador", lambda o, titulo: Adaptar())
    perguntas = []
    app.escolher = lambda t, m, opcoes, **k: (perguntas.append(m), opcoes[0])[1]
    app.bt_dublar.invoke()
    esperar(app)
    esperar(app)
    assert "voz premium \"Kore\" do Gemini" in perguntas[0] and "US$" in perguntas[0]
    assert criados == [("AIza-teste", "Kore")] and voz.textos
    assert (filmes / "Nosferatu (1922)" / "Nosferatu (1922) - Dublado IA.mkv").is_file()
    # sem a chave: avisa e não começa
    (filmes / "Nosferatu (1922)" / "Nosferatu (1922) - Dublado IA.mkv").unlink()
    app.var_jf_chave_gemini.set("")
    criados.clear()
    app.bt_dublar.invoke()
    esperar(app)
    esperar(app)
    assert "precisa da chave do Google AI Studio" in app.caixas[-1][2] and not criados


def test_voz_por_personagem_pela_janela(app, tmp_path, monkeypatch):
    """Ouvir (Gemini) -> tabela "Pessoa -> Voz" -> dublar com uma voz por fala; o progresso fica guardado."""
    app.var_jf_dublagem_no_original.set(False)                   # este teste: o arquivo à parte
    from jellyfin_tools import dublagem, personagens, voz_gemini
    from tests.test_dublagem import FFMPEG, SRT_APERTADA, gravar_tom, video_de_teste
    from videoscraper import automacao
    if not FFMPEG:
        pytest.skip("sem ffmpeg")
    filmes = tmp_path / "Filmes"
    (filmes / "Nosferatu (1922)").mkdir(parents=True)
    video_de_teste(filmes / "Nosferatu (1922)" / "Nosferatu (1922).mkv")
    (filmes / "Nosferatu (1922)" / "Nosferatu (1922).pt-BR.srt").write_text(SRT_APERTADA, encoding="utf-8")
    app.mostrar_aba("Jellyfin")
    app._destinos.update({"Filmes": str(filmes), "Séries": ""})
    app.var_jf_destino.set(str(filmes))
    app.var_jf_motor_voz.set(app.MOTORES_VOZ[1])
    app.var_jf_chave_gemini.set("AIza-teste")
    app.var_jf_voz_por_personagem.set(True)
    app.var_jf_encurtar_falas.set(False)
    monkeypatch.setattr(app_moderna, "videos_para_dublar",
                        lambda *p, **k: dublagem.videos_para_dublar(*p, **{**k, "sondar": lambda v: (6.0, ["eng"])}))
    monkeypatch.setattr(voz_gemini, "_cliente", lambda chave, avisar=None: object())
    ouvidos = []

    def ouvir(o, video, falas, cliente=None, ao_progresso=None, parar=None, serie=""):
        ouvidos.append([t for _, t in falas])
        return [personagens.Personagem("Conde", "m", "voz grave", falas=[0, 1, 2]),
                personagens.Personagem("Ellen", "f", "", falas=[3, 4, 5])]
    monkeypatch.setattr(automacao, "ouvir_personagens", ouvir)

    class Voz:                                                       # o Gemini, de mentira: anota a voz de cada fala
        pedidos = 1

        def __init__(self):
            self.vozes = {}

        def sintetizar(self, pedidos, parar=None, ao_progresso=None):
            for texto, wav, *voz in pedidos:
                self.vozes[texto] = voz[0] if voz else "principal"
                gravar_tom(Path(wav), 0.05 * len(texto))
    voz = Voz()
    monkeypatch.setattr(voz_gemini, "MotorGemini", lambda chave, nome, **k: voz)
    tabelas, perguntas = [], []
    app.escolher = lambda t, m, opcoes, **k: (perguntas.append(m), opcoes[0])[1]
    # a falas 0-2 são do Conde e 3-5 da Ellen, mas a legenda só tem 3 falas: a Ellen não chega a falar
    app.pedir_vozes = lambda filme, linhas, rotulos, sugestao: tabelas.append((filme, linhas, rotulos, sugestao)) or \
        {"Conde": "Orus", "Ellen": "Kore"}
    app.bt_dublar.invoke()
    for _ in range(3):
        esperar(app)
    assert "uma voz para cada personagem" in perguntas[0] and "pedido(s) de voz" in perguntas[0]
    assert ouvidos == [["Olá!", "Uma fala comprida demais para caber nesse pedacinho de tempo.", "Tchau."]]
    filme, linhas, rotulos, sugestao = tabelas[0]
    assert filme == "Nosferatu (1922)" and rotulos == ["Conde", "Ellen"]
    assert sugestao["Conde"] in voz_gemini.VOZES_MASCULINAS and sugestao["Ellen"] in voz_gemini.VOZES_FEMININAS
    assert linhas[0].startswith('Conde (homem, voz grave) · 3 falas')
    assert set(voz.vozes.values()) == {"Orus"}                          # as 3 falas são do Conde -> Orus
    assert (filmes / "Nosferatu (1922)" / "Nosferatu (1922) - Dublado IA.mkv").is_file()
    assert "Pedidos de voz ao Gemini" in app.caixas[-1][2]


def test_janela_vozes_dos_personagens(app):
    from jellyfin_tools import voz_gemini
    from videoscraper.gui_moderna import DialogoVozes
    assert [v.split()[0] for v in app.VOZES_GEMINI] == list(voz_gemini.VOZES)      # o menu e o motor batem
    assert all(v == voz_gemini.texto_da_voz(v.split()[0]) for v in app.VOZES_GEMINI)
    janela = DialogoVozes(app, "Filme", ["Pessoa 1 (homem) · 30 falas", "Ana (mulher) · 12 falas"],
                          ["Pessoa 1", "Ana"], {"Pessoa 1": "Orus", "Ana": "Kore"}, app.VOZES_GEMINI)
    assert janela.vars["Ana"].get() == "Kore (feminina, firme)"
    janela.vars["Ana"].set("Leda (feminina, jovem)")
    janela.bt_dublar.invoke()
    assert janela.resultado == {"Pessoa 1": "Orus", "Ana": "Leda"}
    janela = DialogoVozes(app, "Filme", ["x"], ["Pessoa 1"], {}, app.VOZES_GEMINI)
    janela.bt_uma_voz.invoke()
    assert janela.resultado == {}                                       # uma voz só para todos


def test_dublagem_mista_por_filme_e_figurantes(app, tmp_path, monkeypatch):
    """Mista: só os filmes marcados vão com o Gemini (os outros com o Piper) e, na tabela de vozes, os figurantes
    aparecem com a voz do Piper."""
    app.var_jf_dublagem_no_original.set(False)                   # este teste: o arquivo à parte
    from jellyfin_tools import dublagem, voz_gemini
    from tests.test_dublagem import FFMPEG, SRT, VozFalsa, video_de_teste
    from videoscraper import automacao
    from videoscraper.gui_moderna import DialogoMarcar, valor_da_voz
    if not FFMPEG:
        pytest.skip("sem ffmpeg")
    assert valor_da_voz("Piper faber (grátis, no PC)") == "piper:faber" and valor_da_voz("Kore (feminina, firme)") == "Kore"
    filmes = tmp_path / "Filmes"
    for nome in ("Metropolis (1927)", "Nosferatu (1922)"):
        (filmes / nome).mkdir(parents=True)
        video_de_teste(filmes / nome / f"{nome}.mkv")
        (filmes / nome / f"{nome}.pt-BR.srt").write_text(SRT, encoding="utf-8")
    app.mostrar_aba("Jellyfin")
    app._destinos.update({"Filmes": str(filmes), "Séries": ""})
    app.var_jf_destino.set(str(filmes))
    app.var_jf_motor_voz.set(app.MOTORES_VOZ[1])
    app.var_jf_chave_gemini.set("AIza-teste")
    app.var_jf_encurtar_falas.set(False)
    monkeypatch.setattr(app_moderna, "videos_para_dublar",
                        lambda *p, **k: dublagem.videos_para_dublar(*p, **{**k, "sondar": lambda v: (6.0, ["eng"])}))
    gemini, piper = VozFalsa(), type("PiperFalso", (VozFalsa,), {})()      # motores diferentes: o banco de frases não mistura
    monkeypatch.setattr(voz_gemini, "MotorGemini", lambda chave, nome, **k: gemini)
    monkeypatch.setattr(automacao, "motor_piper", lambda o, voz="", **k: piper)
    perguntas = []
    app.pedir_marcados = lambda titulo, msg, itens, marcados, botao="": perguntas.append((itens, marcados)) or [1]
    app.bt_dublar.invoke()
    for _ in range(2):
        esperar(app)
    itens, marcados = perguntas[0]
    assert itens[0].startswith("Metropolis (1927)") and marcados == {0, 1}      # todos marcados de início
    assert gemini.textos and piper.textos and len(gemini.textos) == len(piper.textos)   # 1 filme em cada motor
    assert all((filmes / n / f"{n} - Dublado IA.mkv").is_file() for n in ("Metropolis (1927)", "Nosferatu (1922)"))
    # a janela de marcar, de verdade
    janela = DialogoMarcar(app, "Voz premium", "msg", ["A", "B", "C"], {0, 1, 2}, "Dublar")
    janela._todos(False)
    janela.vars[2].set(True)
    janela.bt_ok.invoke()
    assert janela.resultado == [2]
    # figurantes: a sugestão da tabela manda quem fala pouco para o Piper, e a tabela tem as vozes do Piper
    from jellyfin_tools import personagens
    app.var_jf_figurantes_piper.set(True)
    o = app.obter_opcoes_jellyfin()
    assert automacao.figurante(o) == "piper:faber"
    sugestao = personagens.distribuir_vozes([personagens.Personagem("Conde", "m", falas=list(range(30))),
                                             personagens.Personagem("Guarda", "m", falas=[30, 31, 32])],
                                            o.voz_gemini, automacao.figurante(o))
    from videoscraper.gui_moderna import DialogoVozes
    vozes = app.VOZES_GEMINI + tuple(f"Piper {v} (grátis, no PC)" for v in app.VOZES_DUBLAGEM)
    tabela = DialogoVozes(app, "Filme", ["Conde", "Guarda"], ["Conde", "Guarda"], sugestao, vozes)
    assert tabela.vars["Guarda"].get() == "Piper faber (grátis, no PC)"
    tabela.bt_dublar.invoke()
    assert tabela.resultado == {"Conde": "Charon", "Guarda": "piper:faber"}


def test_tela_de_configuracoes(app):
    """⚙ Configurações: menu por categoria, os 3 modos da dublagem, resumo na aba Jellyfin e salvar ao sair."""
    from videoscraper import config
    assert app.seletor_aba.cget("values")[-1] == app.ABA_CONFIG
    app.mostrar_aba(app.ABA_CONFIG)
    assert app.aba_config.winfo_manager() and not app.aba_jellyfin.winfo_manager()
    todas = [n for _, nomes in app.GRUPOS_CONFIG for n in nomes]
    assert set(todas) == set(app._secoes_config)                         # cada categoria tem a sua tela
    app._botoes_config["Dublagem"].invoke()
    app.update()
    assert app.config_atual() == "Dublagem" and app._secoes_config["Dublagem"].winfo_ismapped()
    assert not app._secoes_config["Nomes e TMDB"].winfo_ismapped()
    # os cartões Piper / Gemini / Misto mudam o motor e os figurantes...
    for modo, motor, figurantes in (("misto", app.MOTORES_VOZ[1], True), ("gemini", app.MOTORES_VOZ[1], False),
                                    ("piper", app.MOTORES_VOZ[0], False)):
        app.var_jf_modo_voz.set(modo)
        app._ao_escolher_modo_voz()
        assert (app.var_jf_motor_voz.get(), app.var_jf_figurantes_piper.get()) == (motor, figurantes)
    # ...e o contrário (config.json antigo, ou mudado por código) marca o cartão certo
    app.var_jf_motor_voz.set(app.MOTORES_VOZ[1])
    app.var_jf_figurantes_piper.set(True)
    assert app.var_jf_modo_voz.get() == "misto"
    assert app._cartoes_modo_voz["misto"].cget("border_color") == app_moderna.Tema.PRIMARIA
    app.campo_limite_figurante.set(12)
    app.var_jf_robo_so_piper.set(True)
    o = app.obter_opcoes_jellyfin()
    assert (o.limite_figurante, o.robo_so_piper, o.perguntar_filmes) == (12, True, True)
    # sair das Configurações já salva; na aba Jellyfin, o resumo do que está ligado
    app.var_jf_tmdb.set(True)
    app.mostrar_aba("Jellyfin")
    salvo = config.carregar()["jellyfin"]
    assert salvo["limite_figurante"] == 12 and salvo["figurantes_piper"] is True
    resumo = app.lb_resumo_config.cget("text")
    assert "TMDB ✓" in resumo and "Dublagem: Misto (Gemini + Piper)" in resumo and "Legendas: pt-BR" in resumo
    # as opções que eram do painel lateral continuam funcionando (agora em Configurações)
    assert app.bt_simular_vigia.master is app._secoes_config["Vigia (automático)"]
    assert app.bt_testar_gemini.master.master is app._secoes_config["Chaves de API"]


def test_coleta_de_lixo_so_na_linha_da_janela(app):
    """Com a janela aberta, a coleta automática fica desligada e roda pela própria janela (a cada 2 s): uma fonte
    do Tk apagada numa thread de tarefa travava a thread segurando a trava de importação (e as outras tarefas)."""
    import gc
    assert not gc.isenabled() and app._coleta_agendada
    antes = getattr(app, "_coletas", 0)
    app._coletar_lixo()
    assert app._coletas == antes + 1 and not gc.isenabled()


def test_clonar_voz_pela_janela(app, tmp_path, monkeypatch):
    """Configurações > Dublagem > "Clonar uma voz": grava a referência (microfone de mentira), escolhe o arquivo do
    consentimento, confirma a autorização; o Google (de mentira) devolve a chave, que fica só no PC. A voz aparece
    nos menus, vira "clone:Nome" nas opções e pode ser removida."""
    import math
    from array import array
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace

    from jellyfin_tools import voz_clonada, voz_gemini
    from tests.test_voz_clonada import FFMPEG, VozesFalsas, wav
    from videoscraper import automacao, gui_moderna
    if not FFMPEG:
        pytest.skip("sem ffmpeg")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    app.mostrar_aba(app.ABA_CONFIG)
    app._botoes_config["Dublagem"].invoke()
    assert "Nenhuma voz clonada" in app.lb_vozes_clonadas.cget("text")
    assert app.bt_remover_voz_clonada.cget("state") == "disabled"
    # sem a chave do Gemini: avisa e nem abre a janela
    app.var_jf_chave_gemini.set("")
    app.bt_clonar_voz.invoke()
    assert "chave do Google AI Studio" in app.caixas[-1][2]
    app.var_jf_chave_gemini.set("AIza-teste")

    class Microfone:                                                 # 12 s de "voz"
        segundos, nivel = 0.0, 0.5

        def iniciar(self):
            pass

        def parar(self):
            return array("h", (int(9000 * math.sin(i / 10)) for i in range(24000 * 12))).tobytes()
    monkeypatch.setattr(app, "_gravador", lambda: (Microfone(), ""))
    consentimento = tmp_path / "consentimento.m4a.wav"
    consentimento.write_bytes(wav(6))
    monkeypatch.setattr(gui_moderna.filedialog, "askopenfilename", lambda **k: str(consentimento))
    janelas = []

    def preencher(pasta, gravador, motivo):                          # a pessoa usando a janela de verdade
        d = gui_moderna.DialogoClonarVoz(app, pasta, gravador, motivo, [])
        janelas.append(d)
        d.confirmar()                                                # nada preenchido: avisa e não fecha
        assert "nome" in d.lb_aviso.cget("text") and d.resultado is None
        d.var_nome.set("Izael")
        d.var_dono.set("Izael Depetriz")
        d.alternar_gravacao("referencia")
        assert d.bt_gravar["referencia"].cget("text").startswith("⏹")
        d.alternar_gravacao("referencia")                            # Parar
        assert "gravado: 12 s" in d.status["referencia"].cget("text")
        d.escolher_arquivo("consentimento")
        d.confirmar()
        assert "confirmação" in d.lb_aviso.cget("text")              # falta marcar a autorização
        d.var_autorizo.set(True)
        d.confirmar()
        return d.resultado
    monkeypatch.setattr(app, "pedir_clonagem", preencher)
    vozes = VozesFalsas()
    monkeypatch.setattr(voz_gemini, "_cliente", lambda chave, avisar=None: SimpleNamespace(voices=vozes))
    app.bt_clonar_voz.invoke()
    esperar(app)
    assert app.caixas[-1][0] == "sucesso" and "Izael" in app.caixas[-1][2]
    assert vozes.pedidos[0]["store"] is False
    salvas = voz_clonada.carregar(automacao.arquivo_vozes_clonadas())
    assert [(v.nome, v.autorizada_por, v.chave) for v in salvas] == [("Izael", "Izael Depetriz", "voicekey_abc123")]
    assert not (automacao.arquivo_vozes_clonadas().parent / "gravacoes" / "referencia.wav").exists()   # apagada
    assert consentimento.exists()                                   # o arquivo escolhido pela pessoa fica
    menu = "Clonada: Izael (autorizada por Izael Depetriz)"
    assert menu in app.menu_voz_gemini.cget("values") and "Izael" in app.lb_vozes_clonadas.cget("text")
    app.var_jf_voz_gemini.set(menu)
    assert app.obter_opcoes_jellyfin().voz_gemini == "clone:Izael"
    assert gui_moderna.valor_da_voz(menu) == "clone:Izael"
    assert app.bt_reclonar_voz.cget("state") == "disabled"          # gravações apagadas: não dá para refazer
    # ouvir a frase de teste com a voz clonada (o Gemini de mentira "fala"; o tocar é trocado)
    from jellyfin_tools import microfone
    from tests.test_voz_gemini import GeminiFalso
    falso, tocados = GeminiFalso(), []
    monkeypatch.setattr(voz_gemini, "_cliente", lambda chave, avisar=None: falso)
    monkeypatch.setattr(microfone, "tocar", lambda arquivo: tocados.append(Path(arquivo)))
    app.bt_ouvir_voz.invoke()
    esperar(app)
    assert tocados and tocados[0].is_file()
    assert falso.pedidos[0]["generation_config"]["speech_config"] == [{"voice": "voicekey_abc123"}]
    # a chave vencendo aparece no painel de saúde
    perto = voz_clonada.VozClonada("Izael", "Izael Depetriz", "voicekey_abc123",
                                   expira_em=(datetime.now(timezone.utc) + timedelta(days=3, hours=1)).isoformat())
    app.atualizar_vozes_clonadas([perto])
    assert ("Voz clonada Izael: vence em 3 dia(s)", False) in app.itens_saude()
    # clonar de novo com as gravações guardadas (opção marcada): sem gravar outra vez
    app.atualizar_vozes_clonadas(salvas)
    app.var_jf_guardar_gravacoes.set(True)
    vozes = VozesFalsas()
    monkeypatch.setattr(voz_gemini, "_cliente", lambda chave, avisar=None: SimpleNamespace(voices=vozes))
    app.bt_clonar_voz.invoke()                                      # a mesma janela de antes, preenchida de novo
    esperar(app)
    salvas = voz_clonada.carregar(automacao.arquivo_vozes_clonadas())
    assert salvas[0].tem_gravacoes() and app.bt_reclonar_voz.cget("state") == "normal"
    vozes.pedidos.clear()
    app.bt_reclonar_voz.invoke()
    esperar(app)
    assert len(vozes.pedidos) == 1 and "chave nova" in app.caixas[-1][2]
    # remover: a voz some dos menus (e as gravações do PC) e a escolhida volta para uma voz pronta
    pasta = Path(salvas[0].gravacoes)
    app.escolher_da_lista = lambda *a, **k: 0
    app.bt_remover_voz_clonada.invoke()
    assert voz_clonada.carregar(automacao.arquivo_vozes_clonadas()) == [] and not pasta.exists()
    assert menu not in app.menu_voz_gemini.cget("values")
    assert app.var_jf_voz_gemini.get() == app.VOZES_GEMINI[0]


def _dublagem_falsa(monkeypatch):
    """Piper de mentira (tom por letra) e vídeos de teste com áudio em inglês: nada baixa, nada vai para a internet."""
    from jellyfin_tools import dublagem
    from tests.test_dublagem import VozFalsa
    from videoscraper import automacao
    voz = VozFalsa()
    monkeypatch.setattr(automacao, "motor_piper", lambda o, voz_="", **k: voz)
    monkeypatch.setattr(automacao, "preparar_motor", lambda o, **k: voz)
    monkeypatch.setattr(automacao, "adaptador", lambda o, titulo="": None)
    sondar = lambda v: (6.0, ["eng"])                               # noqa: E731
    monkeypatch.setattr(app_moderna, "videos_para_dublar",
                        lambda *p, **k: dublagem.videos_para_dublar(*p, **{**k, "sondar": sondar}))
    monkeypatch.setattr(app_moderna, "episodios_para_dublar",
                        lambda *p, **k: dublagem.episodios_para_dublar(*p, sondar=sondar, **k))
    return voz


def test_amostra_de_1_minuto_antes_de_dublar(app, tmp_path, monkeypatch):
    app.var_jf_dublagem_no_original.set(False)                   # este teste: o arquivo à parte
    from jellyfin_tools import dublagem
    from tests.test_dublagem import FFMPEG, SRT, video_de_teste
    from videoscraper import automacao
    if not FFMPEG:
        pytest.skip("sem ffmpeg")
    voz = _dublagem_falsa(monkeypatch)
    filmes = tmp_path / "Filmes"
    (filmes / "Nosferatu (1922)").mkdir(parents=True)
    video = video_de_teste(filmes / "Nosferatu (1922)" / "Nosferatu (1922).mkv")
    (filmes / "Nosferatu (1922)" / "Nosferatu (1922).pt-BR.srt").write_text(SRT, encoding="utf-8")
    app.mostrar_aba("Jellyfin")
    app._destinos.update({"Filmes": str(filmes), "Séries": ""})
    app.var_jf_destino.set(str(filmes))
    abertos = []
    app._abrir_no_sistema = lambda caminho: abertos.append(caminho)
    app.escolher = lambda t, m, opcoes, **k: app.botao_amostra() if app.botao_amostra() in opcoes else opcoes[0]
    app.bt_dublar.invoke()
    esperar(app)
    esperar(app)
    teste = automacao.testes_feitos()[0]
    amostra = Path(teste["amostra"])
    assert amostra.is_file() and abertos == [str(amostra)] and teste["aba"] == "jellyfin"
    assert "o teste de" in app.caixas[-1][2].lower() and app.caixas[-1][0] == "sucesso"
    assert not dublagem.caminho_dublado(video).exists()             # a biblioteca não muda
    pedidas = list(voz.textos)
    app.escolher = lambda t, m, opcoes, **k: opcoes[0]              # agora o filme inteiro
    app.bt_dublar.invoke()
    esperar(app)
    esperar(app)
    assert dublagem.caminho_dublado(video).is_file()
    assert not set(pedidas) & set(voz.textos[len(pedidas):])        # as falas da amostra não foram pedidas de novo


def test_dublar_episodios_na_pasta_irma(app, tmp_path, monkeypatch):
    app.var_jf_dublagem_no_original.set(False)                   # este teste: o arquivo à parte
    from jellyfin_tools import dublagem
    from tests.test_dublagem import FFMPEG, SRT, video_de_teste
    if not FFMPEG:
        pytest.skip("sem ffmpeg")
    _dublagem_falsa(monkeypatch)
    series = tmp_path / "Séries"
    temporada = series / "Show (2010)" / "Season 01"
    temporada.mkdir(parents=True)
    video = video_de_teste(temporada / "Show (2010) S01E01.mkv")
    (temporada / "Show (2010) S01E01.pt-BR.srt").write_text(SRT, encoding="utf-8")
    app.mostrar_aba("Jellyfin")
    app._destinos.update({"Filmes": "", "Séries": str(series)})
    mensagens = []
    app.escolher = lambda t, m, opcoes, **k: (mensagens.append(m), opcoes[0])[1]
    app.bt_dublar.invoke()
    esperar(app)
    esperar(app)
    destino = tmp_path / "Séries (Dublado IA)" / "Show (2010)" / "Season 01" / "Show (2010) S01E01.mkv"
    assert destino.is_file() and destino == dublagem.destino_episodio(video, series)
    assert not dublagem.caminho_dublado(video).exists()             # nada repetido na biblioteca de séries
    assert "Séries (Dublado IA)" in mensagens[0]


def test_aba_avulsos_olhar_adicionar_e_processar(app, tmp_path, monkeypatch):
    """Aba própria (como Vídeos e Jellyfin): a caixa de entrada + vídeos de outras pastas; Olhar mostra o que falta
    em cada um; Processar pergunta e dubla; depois a lista mostra tudo pronto."""
    from jellyfin_tools import dublagem
    from tests.test_dublagem import FFMPEG, SRT, video_de_teste
    if not FFMPEG:
        pytest.skip("sem ffmpeg")
    voz = _dublagem_falsa(monkeypatch)
    from videoscraper import automacao
    monkeypatch.setattr(automacao, "videos_para_dublar", app_moderna.videos_para_dublar)
    assert app.seletor_aba.cget("values") == ["Vídeos", "Jellyfin", "Jellyfin TV", "Jellyfin Espelhos", "Avulsos",
                                              "🎧 Áudio", app.ABA_CONFIG]
    assert not hasattr(app, "bt_avulsos")                          # saiu da barra da aba Jellyfin
    caixa = tmp_path / "Para Dublar"
    caixa.mkdir()
    video = video_de_teste(caixa / "Palestra.mkv")
    (caixa / "Palestra.pt-BR.srt").write_text(SRT, encoding="utf-8")
    outra = tmp_path / "Outra"
    outra.mkdir()
    sem_legenda = video_de_teste(outra / "Aula.mkv")
    app.mostrar_aba("Avulsos")
    assert app.aba_avulsos.winfo_manager() and app.lb_titulo.cget("text") == "Legendar e dublar vídeos avulsos"
    # sem pasta e sem vídeos: Processar pede para escolher
    app.var_jf_pasta_avulsos.set("")
    app.bt_av_processar.invoke()
    assert "Escolha a caixa de entrada" in app.caixas[-1][2] and app.linhas_avulsos() == []
    # a caixa de entrada + um vídeo de outra pasta
    app.var_jf_pasta_avulsos.set(str(caixa))
    app._pedir_arquivos_video = lambda: (str(sem_legenda),)
    app.bt_av_adicionar.invoke()
    esperar(app)
    assert sorted(app.linhas_avulsos()) == sorted([
        ("Palestra.mkv", "✓ ao lado (.srt)", "Dublar → pôr a legenda no vídeo", str(caixa)),
        ("Aula.mkv", "nenhuma", "Criar a legenda pelo áudio → dublar → pôr a legenda no vídeo", str(outra))])
    assert app.lb_resumo_av.cget("text") == "2 com algo a fazer · 0 pronto(s)"
    assert app.var_jf_avulsos_legendar.get() and app.var_jf_dublagem_previa.get()          # os padrões
    # "Tirar os adicionados": fica só a caixa de entrada
    app.bt_av_limpar.invoke()
    esperar(app)
    assert [linha[0] for linha in app.linhas_avulsos()] == ["Palestra.mkv"]
    # Processar (fase de teste): uma PRÉVIA para ouvir; o original não muda e a janela das prévias abre
    abertas = []
    app.ao_previas = lambda: abertas.append(len(automacao.previas_pendentes()))
    antes = video.read_bytes()
    app.bt_av_processar.invoke()
    esperar(app)
    esperar(app)
    assert voz.textos and video.read_bytes() == antes and not dublagem.caminho_dublado(video).exists()
    assert app.caixas[-1][0] == "sucesso" and "1 prévia(s) para ouvir e aprovar" in app.caixas[-1][2]
    assert abertas == [1] and app.bt_previas_av.cget("text") == "🎧 Prévias (1)"
    assert app.linhas_avulsos() == [("Palestra.mkv", "✓ ao lado (.srt)", "Ouvir a prévia e aprovar", str(caixa))]
    # aprovar: a dublagem e a legenda entram no original (sem dublar de novo); o .srt sai
    app.mostrar_aba("Avulsos")
    app._aprovar_previa(automacao.previas_pendentes()[0])
    esperar(app)
    from tests.test_dublagem import faixas
    linhas = faixas(video)
    assert len([l for l in linhas if "Audio" in l]) == 2 and len([l for l in linhas if "Subtitle" in l]) == 1
    assert not (caixa / "Palestra.pt-BR.srt").exists() and automacao.previas_pendentes() == []
    assert app.caixas[-1][0] == "sucesso" and "Português (dublagem IA)" in app.caixas[-1][2]
    assert app.linhas_avulsos() == [("Palestra.mkv", "✓ dentro do vídeo", "✓ Nada: já está pronto", str(caixa))]
    # de novo: nada a fazer
    app.bt_av_processar.invoke()
    esperar(app)
    assert "Nada a fazer" in app.caixas[-1][2]
    # ⚙ Opções leva às Configurações > Vídeos avulsos
    app.mostrar_opcoes_avulsos()
    assert app.aba_atual() == app.ABA_CONFIG and app.config_atual() == "Vídeos avulsos"


def test_avulsos_selecao_filtro_e_processar_os_marcados(app, tmp_path, monkeypatch):
    """Lista dos Avulsos: ☐/☑ na coluna #, filtro por coluna, "Só os que falta algo" e o campo "1-3, nome".
    Processar e Testar usam os marcados (com um filtro e nada marcado: os à vista; sem nada: todos)."""
    from types import SimpleNamespace
    from videoscraper import automacao
    caixa = tmp_path / "Caixa"
    caixa.mkdir()
    a, b, c = caixa / "A.mkv", caixa / "B.mkv", tmp_path / "C.mkv"
    linhas = [(a, "nenhuma", "Criar a legenda pelo áudio → dublar", False),
              (b, "✓ ao lado (.srt)", "Dublar", False), (c, "✓ dentro do vídeo", "Nada: já está pronto", True)]
    app.mostrar_aba("Avulsos")
    app.mostrar_avulsos(linhas)
    t, sel = app.tabela_av, app.seletor_av
    assert [t.set(i, "n") for i in t.get_children()] == ["☐ 1", "☐ 2", "☐ 3"] and t.heading("n", "text") == "☐ #"
    assert app.bt_av_processar.cget("text") == "Processar" and app.bt_av_testar.cget("text") == "🧪 Testar"
    assert app.video_avulso_escolhido() == a                            # nada marcado: o 1º com algo a fazer
    sel.botoes_selecao["Só os que falta algo"].invoke()
    assert sel.marcados() == ["0", "1"] and t.set("0", "n") == "☑ 1" and t.set("2", "n") == "☐ 3"
    assert app.bt_av_processar.cget("text") == "Processar 2 marcados"
    assert app.bt_av_testar.cget("text") == "🧪 Testar o marcado"
    app.mostrar_avulsos(linhas)                                         # Olhar de novo: os marcados continuam
    assert sel.marcados() == ["0", "1"]
    planejados = []

    def planejar(o, pasta="", arquivos=(), sondar=None):
        planejados.append((pasta, tuple(arquivos)))
        return SimpleNamespace(vazio=True, previas=[], videos=len(arquivos), traduzir=[], pelo_audio=[], dublar=[])
    monkeypatch.setattr(automacao, "planejar_avulsos", planejar)
    app.bt_av_processar.invoke()
    esperar(app)
    for _ in range(20):                                                 # a pergunta vem 50 ms depois do "fim"
        app.update()
        time.sleep(0.02)
    assert planejados == [("", (str(a), str(b)))]                       # só os marcados
    assert "Nada a fazer em 2 vídeo(s) marcado(s)" in app.caixas[-1][2]
    assert len(t.get_children()) == 3                                    # a lista inteira continua na tela
    # filtro: só os com a legenda ao lado; nada marcado: Processar usa os à vista
    sel.desmarcar_todos()
    sel.aplicar_filtro("legenda", {"✓ ao lado (.srt)"})
    assert t.get_children() == ("1",) and t.heading("legenda", "text") == "Legenda em português ▼"
    assert app.bt_av_processar.cget("text") == "Processar o 1 à vista" and app.video_avulso_escolhido() == b
    planejados.clear()
    app.bt_av_processar.invoke()
    esperar(app)
    assert planejados == [("", (str(b),))]
    sel.tirar_filtros()
    assert sel.marcar_por_texto("1, 3") == 2 and sel.marcados() == ["0", "2"]
    assert sel.marcar_por_texto("b.mkv") == 1 and sel.marcados() == ["0", "1", "2"]
    assert t.heading("n", "text") == "☑ #"
    sel.inverter()
    assert sel.marcados() == [] and app.bt_av_processar.cget("text") == "Processar"


def test_painel_automatico_mostra_quem_faz_e_liga_as_mesmas_opcoes(app):
    """"🤖 Automático" (Jellyfin e Avulsos): o que é feito sozinho, quem faz e o custo. Com o Piper, o que é só do
    Gemini fica apagado (com o motivo); as caixas são as MESMAS opções de Configurações; no Jellyfin, os robôs."""
    sons = "Ouvir os sons sem fala (bocejo, risada, choro, gemido) e trazer do original"
    app.var_jf_motor_voz.set(app.MOTORES_VOZ[0])                       # Piper
    app.var_jf_chave_gemini.set("AIza-teste")
    app.var_jf_separar_vozes.set(True)
    app.var_jf_manter_sons.set(True)
    app.mostrar_aba("Avulsos")
    app.bt_automatico_av.invoke()
    painel = app._painel_automatico
    assert "aba Avulsos" in painel.lb_titulo.cget("text") and "voz do Piper" in painel.lb_voz.cget("text")
    linhas = {linha["oque"]: linha for linha in painel.linhas if "oque" in linha}
    emocao = linhas["Emoção da cena (a voz repete a interpretação)"]
    assert not emocao["ativo"] and "só com a voz do Gemini" in emocao["situacao"]
    assert "var_jf_emocao_da_cena" not in painel.caixas                  # apagada: não dá para ligar com o Piper
    assert linhas[sons]["ativo"] and linhas[sons]["quem"] == "Gemini (escuta)"
    assert linhas["Criar a legenda pelo áudio (vídeo sem nenhuma legenda)"]["quem"] == "Whisper (no seu PC)"
    assert "Robôs" not in " ".join(linha.get("titulo", "") for linha in painel.linhas)
    painel.caixas["var_jf_manter_sons"].toggle()                         # a mesma opção de Configurações
    assert app.var_jf_manter_sons.get() is False
    app.update()
    assert painel.caixas["var_jf_manter_sons"].get() == 0                # montado de novo, ainda desligado
    painel.fechar()
    app.var_jf_motor_voz.set(app.MOTORES_VOZ[1])                       # Gemini: libera a emoção e os personagens
    app.mostrar_aba("Jellyfin")
    app.bt_automatico_jf.invoke()
    painel = app._painel_automatico
    assert "aba Jellyfin" in painel.lb_titulo.cget("text")
    assert {"var_jf_emocao_da_cena", "var_jf_voz_por_personagem", "var_jf_robo_so_piper", "var_jf_vigiar",
            "var_jf_legendas"} <= set(painel.caixas)
    assert any(linha.get("titulo", "").startswith("Robôs agendados") for linha in painel.linhas)
    app.var_jf_chave_gemini.set("")
    painel.recarregar()
    assert "var_jf_emocao_da_cena" not in painel.caixas and "Sem a chave do Gemini" in painel.lb_nota.cget("text")
    painel.fechar()
    app.var_jf_motor_voz.set(app.MOTORES_VOZ[0])


def test_gastos_do_mes_na_tela(app):
    from jellyfin_tools import gastos
    app.mostrar_aba(app.ABA_CONFIG)
    app._botoes_config["Gastos (APIs pagas)"].invoke()
    app.var_jf_moeda_gastos.set(app.MOEDAS_GASTOS[1])              # em dólar, como as APIs cobram
    app.campo_teto_gastos.set(5)
    app.mostrar_aba("Jellyfin")                                     # sair das Configurações salva (e liga o teto)
    atual = gastos.atual()
    assert atual is not None and atual.teto == 5 and atual.fator is None
    gastos.registrar("Claude", 1.0)
    gastos.registrar("Gemini", 3.2)
    assert ("Gastos do mês: US$ 4.20 de US$ 5.00", False) in app.itens_saude()      # passou de 80%: aviso
    assert app.lb_gastos_mes.cget("text") == "US$ 4.20 (Claude 1.00 · Gemini 3.20) de US$ 5.00"
    assert app.obter_opcoes_jellyfin().teto_gastos == 5
    # em reais (o padrão): cotação fixa 5,00 + IOF 3,5% -> US$ 4,20 = R$ 21,73; teto de R$ 30
    app.mostrar_aba(app.ABA_CONFIG)
    app.var_jf_moeda_gastos.set(app.MOEDAS_GASTOS[0])
    app.campo_cotacao_dolar.set(5.0)
    app.campo_teto_gastos.set(30)
    app.mostrar_aba("Jellyfin")
    atual = gastos.atual()
    assert atual.teto == 30 and atual.fator == pytest.approx(5.175)
    assert app.lb_gastos_mes.cget("text") == "R$ 21,73 (Claude R$ 5,17 · Gemini R$ 16,56) de R$ 30,00"
    assert app.lb_cotacao.cget("text") == "US$ 1 = R$ 5,00 (cotação fixa) + IOF 3,5%"
    assert (app.campo_cotacao_dolar.var.get(), app.campo_iof.var.get()) == ("5,00", "3,5")    # jeito brasileiro
    app.campo_cotacao_dolar.var.set("5,44")                          # digitado com vírgula
    assert app.campo_cotacao_dolar.get() == pytest.approx(5.44)
    assert ("Gastos do mês: R$ 21,73 de R$ 30,00", True) in app.itens_saude()       # 72% do teto: ainda ok


def test_google_cloud_tts_pela_janela(app, tmp_path, monkeypatch):
    """Cartão "Google Cloud TTS": tipo e voz, Validar (lista as vozes da conta), frase de teste, cota no painel e a
    dublagem com o motor do Cloud (não com o Piper)."""
    app.var_jf_dublagem_no_original.set(False)                   # este teste: o arquivo à parte
    from jellyfin_tools import dublagem, gastos, microfone, voz_cloud
    from tests.test_dublagem import FFMPEG, SRT, VozFalsa, video_de_teste
    from tests.test_voz_cloud import GoogleFalso
    from videoscraper import automacao
    if not FFMPEG:
        pytest.skip("sem ffmpeg")
    monkeypatch.delenv("GOOGLE_TTS_API_KEY", raising=False)
    app.mostrar_aba(app.ABA_CONFIG)
    app._botoes_config["Dublagem"].invoke()
    app.var_jf_modo_voz.set("cloud")
    app._ao_escolher_modo_voz()
    assert app.var_jf_motor_voz.get() == app.MOTORES_VOZ[2] and not app.var_jf_figurantes_piper.get()
    # tipo Studio: só as vozes B e C; a letra escolhida (B) continua
    app.var_jf_tipo_cloud.set(app.texto_tipo_cloud("Studio"))
    app._ao_trocar_tipo_cloud()
    assert app.menu_voz_cloud.cget("values") == ["pt-BR-Studio-B (masculina)", "pt-BR-Studio-C (feminina)"]
    assert app.var_jf_voz_cloud.get() == "pt-BR-Studio-B (masculina)"
    app.var_jf_tipo_cloud.set(app.texto_tipo_cloud("Neural2"))
    app._ao_trocar_tipo_cloud()
    o = app.obter_opcoes_jellyfin()
    assert (o.tipo_cloud, o.voz_cloud) == ("Neural2", "pt-BR-Neural2-B")
    assert ("Cloud TTS: sem chave", False) in app.itens_saude()
    # Validar: a lista da conta (com mais vozes) entra no menu
    app.var_jf_chave_cloud.set("AIza-cloud")
    monkeypatch.setattr(voz_cloud, "listar_vozes", lambda chave: ["pt-BR-Neural2-A", "pt-BR-Neural2-B",
                                                                  "pt-BR-Neural2-C", "pt-BR-Wavenet-E"])
    app.bt_testar_cloud.invoke()
    esperar(app)
    assert "Ativa · 4 vozes" in app.lb_estado_cloud.cget("text") and ("Cloud TTS ativa", True) in app.itens_saude()
    app.var_jf_tipo_cloud.set(app.texto_tipo_cloud("WaveNet"))
    app._ao_trocar_tipo_cloud()
    assert app.menu_voz_cloud.cget("values") == ["pt-BR-Wavenet-E (masculina)"]
    app.var_jf_tipo_cloud.set(app.texto_tipo_cloud("Neural2"))
    app._ao_trocar_tipo_cloud()
    app.var_jf_voz_cloud.set("pt-BR-Neural2-B (masculina)")
    # frase de teste: o Google (de mentira) lê, o som toca, a cota conta
    app._salvar_config()
    google, tocados = GoogleFalso(), []
    monkeypatch.setattr(voz_cloud, "_post", google)
    monkeypatch.setattr(microfone, "tocar", lambda arquivo: tocados.append(arquivo))
    app.bt_ouvir_cloud.invoke()
    esperar(app)
    assert tocados and google.pedidos[0][2]["voice"]["name"] == "pt-BR-Neural2-B"
    assert gastos.atual().caracteres()["Neural2"] == len(automacao.voz_gemini.FRASE_DE_TESTE)
    assert "Cota grátis do mês (Neural2)" in app.lb_cota_cloud.cget("text")
    # dublar: vai pelo motor do Cloud, não pelo Piper
    filmes = tmp_path / "Filmes"
    (filmes / "Nosferatu (1922)").mkdir(parents=True)
    video = video_de_teste(filmes / "Nosferatu (1922)" / "Nosferatu (1922).mkv")
    (filmes / "Nosferatu (1922)" / "Nosferatu (1922).pt-BR.srt").write_text(SRT, encoding="utf-8")
    app.mostrar_aba("Jellyfin")
    app._destinos.update({"Filmes": str(filmes), "Séries": ""})
    app.var_jf_destino.set(str(filmes))
    monkeypatch.setattr(app_moderna, "videos_para_dublar",
                        lambda *p, **k: dublagem.videos_para_dublar(*p, **{**k, "sondar": lambda v: (6.0, ["eng"])}))
    monkeypatch.setattr(automacao, "motor_piper", lambda *a, **k: pytest.fail("com o Cloud, o Piper não entra"))
    monkeypatch.setattr(automacao, "adaptador", lambda o, titulo="": None)
    cloud = VozFalsa()
    monkeypatch.setattr(automacao, "motor_cloud", lambda o: cloud)
    perguntas = []
    app.escolher = lambda t, m, opcoes, **k: (perguntas.append(m), opcoes[0])[1]
    app.bt_dublar.invoke()
    esperar(app)
    esperar(app)
    assert "Google Cloud TTS (Neural2)" in perguntas[0] and "cabe na cota" in perguntas[0]
    assert cloud.textos and dublagem.caminho_dublado(video).is_file()


def test_traducao_local_pela_janela(app, tmp_path, monkeypatch):
    """Configurações > Tradução > Local: sem chave da Anthropic, traduz no PC (modelo de mentira), sem custo."""
    from jellyfin_tools import traducao_local
    from tests.test_traducao_local import Internet, ModeloFalso
    from videoscraper import automacao
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    filmes = tmp_path / "Filmes"
    (filmes / "Filme (2003)").mkdir(parents=True)
    (filmes / "Filme (2003)" / "Filme (2003).mkv").write_bytes(b"")
    (filmes / "Filme (2003)" / "Filme (2003).en.srt").write_text(
        "1\n00:00:01,000 --> 00:00:02,000\nHello.\n\n", encoding="utf-8")
    app.mostrar_aba("Jellyfin")
    app._destinos.update({"Filmes": str(filmes), "Séries": ""})
    app.var_jf_destino.set(str(filmes))
    app.var_jf_chave_claude.set("")
    app.bt_traduzir_legendas.invoke()                               # Claude sem chave: avisa
    assert "Tradução" in app.caixas[-1][2] and "Local" in app.caixas[-1][2]
    app.var_jf_motor_traducao.set(app.MOTORES_TRADUCAO[1])
    assert app.obter_opcoes_jellyfin().motor_traducao == "Local"
    original = traducao_local.TradutorLocal
    monkeypatch.setattr(traducao_local, "TradutorLocal",
                        lambda pasta, idioma, **k: original(pasta, idioma, obter=Internet(), carregar=ModeloFalso))
    perguntas = []
    app.escolher = lambda t, m, opcoes, **k: (perguntas.append((t, m, opcoes)), opcoes[0])[1]
    app.bt_traduzir_legendas.invoke()
    esperar(app)
    esperar(app)
    titulo, mensagem, opcoes = perguntas[0]
    assert "grátis" in titulo and "NO SEU PC" in mensagem and len(opcoes) == 1        # sem modo econômico
    feita = filmes / "Filme (2003)" / "Filme (2003).pt-BR.srt"
    assert feita.is_file() and "[pt] Hello." in feita.read_text(encoding="utf-8")
    assert automacao.pasta_traducao_local().name == "traducao_local"


@pytest.mark.parametrize("largura, altura, escala", [(1920, 1080, 1.0), (1920, 1080, 1.25), (1920, 1080, 1.5),
                                                     (1366, 768, 1.0), (1280, 720, 1.25), (2560, 1440, 1.0)])
def test_janela_cabe_na_tela_mesmo_com_o_zoom_do_windows(largura, altura, escala):
    """O CTk multiplica a largura e a altura pela escala (125% = 1,25): a janela (e o rodapé) tem de caber na tela,
    descontando a barra de tarefas. Antes, em 1080 px com 125%, ela pedia 1125 px e a parte de baixo sumia."""
    l, a, x, y, (min_l, min_a) = tamanho_inicial(largura, altura, escala)
    assert x + l * escala <= largura and y + a * escala + 30 <= altura - 40     # 30: barra de título
    assert min_l <= l and min_a <= a
    assert tamanho_inicial(1920, 1080, 1.0)[:2] == (1320, 900)                    # tela comum: como antes


def test_menu_das_configuracoes_rola_e_atalho_das_opcoes_de_busca(app):
    """As opções de busca ficam em Configurações > VÍDEOS > Opções de busca (1º item do menu), e o botão
    '⚙ Opções da busca' da aba Vídeos leva direto lá. Em tela baixa, o menu rola até o item escolhido
    (antes os últimos itens ficavam escondidos, sem barra de rolagem)."""
    assert isinstance(app.menu_config, ctk.CTkScrollableFrame)
    assert app.GRUPOS_CONFIG[0] == ("VÍDEOS", ("Opções de busca",))
    app.minsize(600, 400)
    app.geometry("1100x480")
    app.update()
    app.bt_opcoes_videos.invoke()
    app.update()
    assert app.aba_atual() == app.ABA_CONFIG and app.config_atual() == "Opções de busca"
    assert app._secoes_config["Opções de busca"].winfo_ismapped()
    canvas = app.menu_config._parent_canvas

    def visivel(nome):
        botao, total = app._botoes_config[nome], app.menu_config.winfo_height()
        topo = canvas.yview()[0] * total
        return topo <= botao.winfo_y() and botao.winfo_y() + botao.winfo_height() <= topo + canvas.winfo_height() + 1
    assert canvas.yview()[0] == 0 and visivel("Opções de busca")
    app._botoes_config["Geral, backup e versão"].invoke()          # o último item: o menu rola até ele
    app.update()
    assert canvas.yview()[0] > 0 and visivel("Geral, backup e versão")
    app.bt_opcoes_videos.invoke()                                   # e volta para cima
    app.update()
    assert canvas.yview()[0] == 0


def test_aba_jellyfin_com_o_zoom_do_windows(app, monkeypatch):
    """Com 125%, a aba tem 744 px = 595 pontos: o painel Antes → Depois não cabe e sai (antes a conta usava os
    pixels como se fossem pontos, o painel ficava e a lista sumia, só com o cabeçalho)."""
    monkeypatch.setattr(app.aba_jellyfin, "winfo_height", lambda: 744)
    monkeypatch.setattr(app, "_pontos", lambda: 1.0)
    assert app.partes_visiveis_jf() == (True, False)
    monkeypatch.setattr(app, "_pontos", lambda: 1.25)
    assert app.partes_visiveis_jf() == (False, False)


def test_janela_das_previas(app, tmp_path):
    """Ouvir abre a prévia; Descartar pergunta e apaga; Aprovar fecha a janela com a escolha."""
    from videoscraper.gui_moderna import JanelaPrevias
    itens = [{"video": str(tmp_path / "Filme (2000).mkv"), "previa": "p1.mkv", "criada": "2026-10-11T18:00"},
             {"video": str(tmp_path / "Aula.mp4"), "previa": "p2.mkv", "criada": "2026-10-11T18:05"}]
    ouvidos, descartados = [], []
    janela = JanelaPrevias(app, lambda: list(itens), ouvidos.append,
                           lambda item: (descartados.append(item), itens.remove(item)))
    app.update()
    assert janela.tabela.item("0", "values")[:2] == ("Filme (2000).mkv", "2026-10-11 18:00")
    janela.bt_ouvir.invoke()
    assert ouvidos == [itens[0]]
    janela.bt_descartar.invoke()
    assert [Path(d["video"]).name for d in descartados] == ["Filme (2000).mkv"]
    assert len(janela.tabela.get_children()) == 1
    janela.bt_aprovar.invoke()
    assert janela.escolha == ("aprovar", itens[0]) and not janela.winfo_exists()
    vazia = JanelaPrevias(app, lambda: [], ouvidos.append, descartados.append)
    app.update()
    assert vazia.bt_aprovar.cget("state") == "disabled"
    vazia.destroy()


def test_opcoes_da_dublagem_nova(app):
    """Configurações > Dublagem: natural, dentro do vídeo e fase de teste (que só vale com 'dentro do vídeo')."""
    o = app.obter_opcoes_jellyfin()
    assert o.separar_vozes and o.dublagem_no_original and o.dublagem_previa and o.avulsos_legendar
    assert o.ambientar_voz and o.separar_gpu
    app.var_jf_separar_vozes.set(False)                     # sem a dublagem natural: ambientar e a placa não valem
    app._ao_trocar_separar_vozes()
    assert app.cb_ambientar_voz.cget("state") == "disabled" and app.cb_separar_gpu.cget("state") == "disabled"
    app.var_jf_separar_vozes.set(True)
    app._ao_trocar_separar_vozes()
    app.var_jf_dublagem_no_original.set(False)
    app._ao_trocar_dublagem_no_original()
    assert app.cb_dublagem_previa.cget("state") == "disabled"
    app._salvar_config()
    from videoscraper import automacao
    salvo, _ = automacao.opcoes_salvas()
    assert salvo.dublagem_no_original is False and salvo.separar_vozes is True


def test_botoes_de_correcao_visiveis_mesmo_sem_o_painel_antes_depois(app, monkeypatch):
    """Em tela baixa o painel Antes -> Depois sai; os botões Resolver conflitos / Corrigir nome / Escolher no TMDB /
    Não identificados ficam na linha "Seleção:" da lista (antes sumiam junto com o painel)."""
    app.mostrar_aba("Jellyfin")
    monkeypatch.setattr(app, "partes_visiveis_jf", lambda altura=None: (False, False))
    app._ajustar_altura_jf()
    app.update()
    assert not app._cartao_detalhe_jf.winfo_ismapped()
    for botao in (app.bt_resolver_conflitos, app.bt_corrigir_nome, app.bt_escolher_tmdb, app.bt_nao_identificados):
        assert botao.master is app.acoes_selecao_jf and botao.winfo_ismapped()


def test_resumo_mostra_se_a_pasta_do_download_fica(app):
    """"Propaganda do torrent" e "Pasta do download" são duas opções diferentes: o resumo mostra as duas."""
    app.var_jf_lixo.set(True)
    app.var_jf_apagar_pasta.set(False)
    app.atualizar_resumo_config()
    texto = app.lb_resumo_config.cget("text")
    assert "Propaganda do torrent: apaga" in texto and "Pasta do download: fica" in texto
    app.var_jf_apagar_pasta.set(True)
    app.atualizar_resumo_config()
    assert "Pasta do download: apaga" in app.lb_resumo_config.cget("text")



def test_testar_alguns_minutos_na_aba_avulsos(app, tmp_path, monkeypatch):
    """"🧪 Testar": legenda e dubla só alguns minutos do vídeo escolhido, num vídeo curto à parte (o original e o
    .srt ao lado não mudam); a duração vem de Configurações > Dublagem."""
    from jellyfin_tools import dublagem
    from tests.test_dublagem import FFMPEG, SRT, faixas, video_de_teste
    if not FFMPEG:
        pytest.skip("sem ffmpeg")
    voz = _dublagem_falsa(monkeypatch)
    from videoscraper import automacao
    monkeypatch.setattr(automacao, "videos_para_dublar", app_moderna.videos_para_dublar)
    caixa = tmp_path / "Avulsos"
    caixa.mkdir()
    video = video_de_teste(caixa / "Aula.mkv")
    legenda = caixa / "Aula.pt-BR.srt"
    legenda.write_text(SRT, encoding="utf-8")
    antes = video.read_bytes()
    app.campo_minutos_teste.set(1)
    app.mostrar_aba("Avulsos")
    assert app.bt_av_testar.cget("text") == "🧪 Testar" and app.var_minutos_teste().get() == "1"   # o campo ao lado
    app.var_jf_pasta_avulsos.set(str(caixa))
    app.bt_av_olhar.invoke()
    esperar(app)
    abertos = []
    app._abrir_no_sistema = lambda caminho: abertos.append(caminho)
    app.bt_av_testar.invoke()
    esperar(app)
    esperar(app)
    teste = automacao.testes_feitos()[0]
    amostra = Path(teste["amostra"])
    assert amostra.is_file() and abertos == [str(amostra)] and voz.textos and teste["aba"] == "avulsos"
    assert Path(teste["legenda"]).parent == amostra.parent / "legendas"     # a legenda DESTE teste fica guardada
    linhas = faixas(amostra)
    assert len([l for l in linhas if "Audio" in l]) == 2 and [l for l in linhas if "Subtitle" in l]   # + a legenda
    assert video.read_bytes() == antes and legenda.exists() and automacao.previas_pendentes() == []
    assert app.caixas[-1][0] == "sucesso" and "o teste de aula" in app.caixas[-1][2].lower()


def test_figurantes_no_google_cloud_na_tela(app, monkeypatch):
    """Modo misto: a opção dos figurantes no Google Cloud (cota grátis) muda a voz sugerida e a tabela."""
    from videoscraper import automacao
    from videoscraper.gui_moderna import valor_da_voz
    monkeypatch.delenv("GOOGLE_TTS_API_KEY", raising=False)
    app.var_jf_motor_voz.set(app.MOTORES_VOZ[1])
    app.var_jf_figurantes_piper.set(True)
    app.var_jf_figurantes_cloud.set(True)
    o = app.obter_opcoes_jellyfin()
    assert o.figurantes_cloud and automacao.figurante(o) == "piper:faber"      # sem a chave do Cloud: Piper
    app.var_jf_chave_cloud.set("AIza-cloud")
    o = app.obter_opcoes_jellyfin()
    assert automacao.figurante(o) == f"cloud:{o.tipo_cloud}"
    assert valor_da_voz("Google Cloud pt-BR-Neural2-B (cota grátis)") == "cloud:pt-BR-Neural2-B"
    capturado = {}

    class Dialogo:
        def __init__(self, master, filme, linhas, rotulos, sugestao, vozes):
            capturado["vozes"], self.resultado = vozes, {}
    monkeypatch.setattr("videoscraper.gui_moderna.DialogoVozes", Dialogo)
    monkeypatch.setattr(app, "wait_window", lambda janela: None)
    app.pedir_vozes("Filme", [], [], {})
    assert "Google Cloud pt-BR-Neural2-B (cota grátis)" in capturado["vozes"]


def test_roteiro_na_aba_avulsos_e_vozes_sem_tabela(app, tmp_path, monkeypatch):
    """"📜 Roteiro": grava 'Nome.roteiro.txt' ao lado do vídeo escolhido e diz quanto casou com a legenda.
    "Escolher as vozes sozinho": o Dublar não abre a tabela."""
    from types import SimpleNamespace
    from jellyfin_tools import personagens
    from tests.test_roteiro import EN, PT, ROTEIRO
    from videoscraper import automacao
    caixa = tmp_path / "Avulsos"
    caixa.mkdir()
    (caixa / "Farol.mkv").write_bytes(b"")
    (caixa / "Farol.en.srt").write_text(EN, encoding="utf-8")
    (caixa / "Farol.pt-BR.srt").write_text(PT, encoding="utf-8")
    arquivo = tmp_path / "baixado.txt"
    arquivo.write_text(ROTEIRO * 4, encoding="utf-8")
    monkeypatch.setattr(app, "video_avulso_escolhido", lambda: caixa / "Farol.mkv")
    pedidos = []
    monkeypatch.setattr(app, "pedir_roteiro", lambda video, ja_tem: pedidos.append((video, ja_tem)) or str(arquivo))
    app.mostrar_aba("Avulsos")
    app.bt_av_roteiro.invoke()
    esperar(app)
    assert (caixa / "Farol.roteiro.txt").is_file() and pedidos == [(caixa / "Farol.mkv", None)]
    assert app.caixas[-1][0] == "info" and "75% das falas" in app.caixas[-1][2], app.caixas[-1]
    # Configurações: as duas opções novas são salvas
    app.var_jf_vozes_sem_tabela.set(True)
    app.var_jf_usar_roteiro.set(False)
    o = app.obter_opcoes_jellyfin()
    assert o.vozes_sem_tabela and not o.usar_roteiro
    o.usar_roteiro = True
    item = SimpleNamespace(video=caixa / "Farol.mkv", legenda=caixa / "Farol.pt-BR.srt", serie="", destino=None)
    lista = [personagens.Personagem("Leo", "m", falas=[0, 3, 5]), personagens.Personagem("Mara", "f", falas=[1, 2, 7])]
    monkeypatch.setattr(app, "pedir_vozes", lambda *a, **k: pytest.fail("não devia abrir a tabela"))
    dublados = []
    monkeypatch.setattr(app, "_dublar", lambda itens, o, vozes=None, premium=None: dublados.append(vozes))
    app._escolher_vozes([(item, automacao.falas_da_legenda(item.legenda), lista)], o)
    vozes = dublados[0][str(item.video)]
    assert vozes[0] == vozes[3] and vozes[1] == vozes[2] and vozes[0] != vozes[1]   # cada um com a sua voz


def test_janela_do_roteiro(app, tmp_path):
    from videoscraper.gui_moderna import DialogoRoteiro
    janela = DialogoRoteiro(app, tmp_path / "Farol.mkv", tmp_path / "Farol.roteiro.txt")
    janela.bt_ok.invoke()
    assert janela.resultado is None and janela.winfo_exists()             # sem link: não fecha
    janela.var_link.set("  https://exemplo.com/roteiro.html ")
    janela.bt_ok.invoke()
    assert janela.resultado == "https://exemplo.com/roteiro.html"



def test_minutos_do_teste_ao_lado_dos_botoes_e_jellyfin(app, tmp_path, monkeypatch):
    """Os minutos do teste: um valor só, editável ao lado do "🧪 Testar" (Jellyfin e Avulsos) e nas Configurações.
    O "🧪 Testar" da aba Jellyfin vai direto para o teste; o "📜 Roteiro..." escolhe o filme na biblioteca."""
    from types import SimpleNamespace
    app.campo_jf_minutos.winfo_children()[0].set(7)                  # o campo da aba Jellyfin
    assert app.campo_minutos_teste.get() == 7 and app.var_minutos_teste().get() == "7"
    assert app.campo_av_minutos.winfo_children()[0].get() == 7          # o da aba Avulsos é o mesmo
    assert app.obter_opcoes_jellyfin().minutos_teste == 7 and app.botao_amostra() == "Testar 7 min (amostra)"
    app.campo_minutos_teste.set(99)                                     # passa do máximo: fica em 60
    assert app.var_minutos_teste().get() == "60"
    inicio_jf = app.campo_jf_minutos.winfo_children()[2]               # "a partir de" ao lado dos minutos
    assert inicio_jf.get() == "auto"                                    # o Maestro escolhe o trecho
    inicio_jf.delete(0, "end")
    inicio_jf.insert(0, "12:30")
    assert app.campo_av_minutos.winfo_children()[2].get() == "12:30"    # o mesmo valor na aba Avulsos
    assert app.obter_opcoes_jellyfin().inicio_teste == "12:30" and app.texto_inicio_teste() == " a partir de 12:30"
    assert app.obter_opcoes_jellyfin().emocao_da_cena
    app.var_inicio_teste().set("")
    assert app.texto_inicio_teste() == ""
    filmes = tmp_path / "Filmes"
    filmes.mkdir()
    app._destinos.update({"Filmes": str(filmes), "Séries": ""})
    app.var_jf_destino.set(str(filmes))
    item = SimpleNamespace(video=filmes / "A.mkv", legenda=filmes / "A.pt-BR.srt", falas=10, serie="", destino=None)
    monkeypatch.setattr(app_moderna, "videos_para_dublar", lambda *a, **k: [item])
    monkeypatch.setattr(app_moderna, "episodios_para_dublar", lambda *a, **k: [])
    testes = []
    monkeypatch.setattr(app, "_amostra", lambda itens, o: testes.append(itens))
    monkeypatch.setattr(app, "escolher", lambda *a, **k: pytest.fail("o Testar não pergunta se é para dublar tudo"))
    app.mostrar_aba("Jellyfin")
    app.bt_testar_jf.invoke()
    esperar(app)
    for _ in range(20):                                                 # a pergunta vem 50 ms depois do "fim"
        app.update()
        time.sleep(0.02)
    assert testes == [[item]]
    from jellyfin_tools.dublagem import MARCA_DUBLADO
    (filmes / "A.mkv").write_bytes(b"x")
    (filmes / f"A{MARCA_DUBLADO}.mkv").write_bytes(b"x")                 # a versão dublada não entra na lista
    listas = []
    monkeypatch.setattr(app, "_pedir_arquivos_video", lambda *a, **k: pytest.fail("não pede o vídeo pelo Windows"))
    monkeypatch.setattr(app, "pedir_roteiro_da_lista", lambda videos, pasta="": listas.append((videos, pasta)))
    app.bt_roteiro_jf.invoke()
    esperar(app)
    for _ in range(20):                                                 # a janela vem 50 ms depois do "fim"
        app.update()
        time.sleep(0.02)
    assert listas == [([(filmes / "A.mkv", "Filmes", False)], str(filmes))]


def test_janela_do_roteiro_com_a_lista_da_biblioteca(app, tmp_path):
    """Aba Jellyfin: a janela do roteiro traz a lista dos filmes e episódios (com busca) e o link/arquivo, como nos
    Avulsos; "Outro vídeo..." pega um de fora da lista."""
    from videoscraper.gui_moderna import DialogoRoteiro
    videos = [(tmp_path / "Duna (2021).mkv", "Filmes", True), (tmp_path / "Show S01E01.mkv", "Séries · Show", False),
              (tmp_path / "Show S01E02.mkv", "Séries · Show", False)]
    outro = tmp_path / "outra" / "Aula.mp4"
    janela = DialogoRoteiro(app, None, videos=videos, outro_video=lambda: (str(outro),))
    assert janela.lista.size() == 3 and janela.video is None
    janela.var_link.set("https://exemplo.com/roteiro.html")
    janela.bt_ok.invoke()
    assert janela.resultado is None and "Escolha primeiro" in janela.lb_video.cget("text")   # falta o vídeo
    janela.var_busca.set("duna")
    janela.mostrar()
    assert janela.lista.size() == 1 and janela.video == videos[0][0]            # achou um só: já escolhido
    assert "já tem roteiro" in janela.lb_video.cget("text")
    janela.var_busca.set("série")                                               # sem acento também acha
    janela.mostrar()
    janela.lista.selection_set(1)
    janela._ao_escolher()
    assert janela.lista.size() == 2 and janela.video == videos[2][0]
    janela.bt_outro.invoke()
    assert janela.video == outro and janela.lista.get(0).startswith("Aula.mp4")
    janela.bt_ok.invoke()
    assert janela.resultado == "https://exemplo.com/roteiro.html" and janela.video == outro
    app.update()


def test_parar_libera_a_janela_mesmo_com_uma_etapa_presa(app, monkeypatch):
    """Uma etapa presa (ex.: esperando um serviço da internet) que não confere o Parar: depois da espera, a janela é
    liberada, e o que a etapa mandar depois não aparece na tela."""
    import threading
    monkeypatch.setattr(app, "ESPERA_PARAR_MS", 200)
    soltar, viu_parar = threading.Event(), []

    def presa():
        soltar.wait(10)                                  # não confere o Parar enquanto espera
        viu_parar.append(app.evento_parar.is_set())
        app.fila.put(("msg", ("Atrasada", "não devia aparecer", "info")))
    caixas = len(app.caixas)
    app._rodar("Etapa presa...", presa)
    assert app.trabalhando
    app.ao_parar()
    fim = time.time() + 5
    while app.trabalhando and time.time() < fim:
        app.update()
        time.sleep(0.02)
    assert not app.trabalhando                           # a janela voltou sem esperar a etapa
    app._rodar("Outra tarefa...", lambda: time.sleep(0.3))   # a próxima tarefa não "desliga" o Parar da antiga
    soltar.set()
    esperar(app)
    for _ in range(10):
        app.update()
        time.sleep(0.02)
    assert viu_parar == [True] and len(app.caixas) == caixas   # a antiga viu "parar" e não mexeu na tela


def test_previas_e_testes_abrem_no_vlc(app, tmp_path, monkeypatch):
    """Prévias e testes abrem no VLC (o "Filmes e TV" do Windows às vezes recusa o .mkv com várias faixas); sem o
    VLC, no programa padrão; "Outro programa..." vale um .exe qualquer."""
    from videoscraper import automacao
    vlc = tmp_path / "vlc.exe"
    vlc.write_bytes(b"")
    abertos, padrao = [], []
    monkeypatch.setattr(app_moderna.subprocess, "Popen", lambda args, **k: abertos.append(args))
    monkeypatch.setattr(app, "_abrir_no_sistema", lambda caminho: padrao.append(caminho))
    monkeypatch.setattr(automacao, "localizar_vlc", lambda: str(vlc))
    assert app.obter_opcoes_jellyfin().player_video == "vlc"               # o padrão é o VLC
    app.abrir_video(str(tmp_path / "previa.mkv"))
    assert abertos == [[str(vlc), str(tmp_path / "previa.mkv")]] and not padrao
    app.var_jf_player_video.set(app.PLAYERS[1])                             # "Programa padrão do Windows"
    app.abrir_video("b.mkv")
    assert padrao == ["b.mkv"] and app.obter_opcoes_jellyfin().player_video == "padrao"
    outro = tmp_path / "mpc-hc64.exe"
    outro.write_bytes(b"")
    monkeypatch.setattr(app_moderna.filedialog if hasattr(app_moderna, "filedialog") else __import__(
        "videoscraper.gui_moderna", fromlist=["filedialog"]).filedialog, "askopenfilename", lambda **k: str(outro))
    app.ao_escolher_player()
    assert app.obter_opcoes_jellyfin().player_video == str(outro)
    app.abrir_video("c.mkv")
    assert abertos[-1] == [str(outro), "c.mkv"]
    app.definir_player("vlc")
    monkeypatch.setattr(automacao, "localizar_vlc", lambda: None)            # sem o VLC instalado
    app.abrir_video("d.mkv")
    assert padrao[-1] == "d.mkv"


def test_testes_feitos_ficam_para_abrir_de_novo(app, tmp_path, monkeypatch):
    """"🧪 Testes feitos": cada teste fica guardado (vários do mesmo vídeo também, mesmo depois que o filme inteiro é
    dublado) para abrir de novo, abrir a pasta (outro player) ou apagar um, vários ou todos. Abre mostrando os testes
    da aba de onde veio."""
    from datetime import datetime
    from videoscraper import automacao
    from videoscraper.gui_moderna import JanelaTestes
    from jellyfin_tools import dublagem
    video = tmp_path / "Farol (2020).mkv"
    primeiro = dublagem.caminho_amostra(automacao.pasta_dublagem(), video, datetime(2026, 10, 13, 14, 54, 10))
    assert primeiro.parent.name == "testes" and primeiro.name.endswith(" - 2026-10-13 14h54m10s.mkv")
    primeiro.parent.mkdir(parents=True, exist_ok=True)
    primeiro.write_bytes(b"x")
    automacao.registrar_teste(video, primeiro, (75.0, 195.0))           # sem legenda: um teste antigo dos Avulsos
    lista = automacao._ler_testes()
    del lista[0]["aba"]                                                  # antes da v2.18.12 a aba não era guardada
    automacao._gravar_testes(lista)
    segundo = dublagem.caminho_amostra(automacao.pasta_dublagem(), video, datetime(2026, 10, 13, 14, 54, 10))
    assert segundo != primeiro and segundo.name.endswith("(2).mkv")      # o 2º teste não apaga o 1º
    segundo.write_bytes(b"yy")
    automacao.registrar_teste(video, segundo, (300.0, 420.0), custo=0.0, aba="avulsos")
    filme = tmp_path / "Filmes" / "Duna (2021).mkv"
    filme.parent.mkdir()
    legenda = filme.with_name("Duna (2021).pt-BR.srt")
    legenda.write_text("1\n00:00:01,000 --> 00:00:02,000\nOi\n", encoding="utf-8")
    do_jellyfin = dublagem.caminho_amostra(automacao.pasta_dublagem(), filme)
    do_jellyfin.write_bytes(b"zzz")
    automacao.registrar_teste(filme, do_jellyfin, (0.0, 60.0), legenda, custo=0.05, aba="jellyfin")
    assert [t["aba"] for t in automacao.testes_feitos()] == ["jellyfin", "avulsos", "avulsos"]
    assert automacao.testes_feitos()[0]["legenda"] == str(legenda)       # a do Jellyfin fica onde está
    abertos, pastas, perguntas = [], [], []
    monkeypatch.setattr(app, "abrir_video", lambda caminho: abertos.append(caminho))
    monkeypatch.setattr(app, "_abrir_no_sistema", lambda caminho: pastas.append(caminho))
    monkeypatch.setattr(app, "perguntar", lambda titulo, texto, *a, **k: (perguntas.append(texto), True)[1])
    app.mostrar_aba("Avulsos")
    app.bt_testes_av.invoke()
    janela = next(w for w in app.winfo_children() if isinstance(w, JanelaTestes))
    t = janela.tabela
    assert t.get_children() == ("1", "2") and janela.seletor.ocultos == {"0"}       # só os dos Avulsos
    assert t.heading("aba", "text") == "Aba ▼" and "aba Avulsos: 2 de 3" in janela.lb_filtro.cget("text")
    assert t.item("1", "values")[:4] == ("☑ 2", "Avulsos", "Farol (2020).mkv", "5:00 a 7:00")    # o mais novo
    assert t.item("2", "values")[:4] == ("☐ 3", "Avulsos", "Farol (2020).mkv", "1:15 a 3:15")
    assert t.item("1", "values")[4] == "grátis" and t.item("2", "values")[4] == "-"              # antigo: sem custo
    janela.bt_abrir.invoke()
    janela.bt_pasta.invoke()
    assert abertos == [str(segundo)] and pastas == [str(segundo.parent)]
    janela.seletor.marcar(["2"], somar=False)                           # o antigo
    app.caixas.clear()
    janela.bt_ajustar.invoke()                                           # teste antigo: não dá para ajustar
    assert app.caixas and "versão anterior" in app.caixas[-1][2]
    janela.seletor.alternar_todos()                                      # o título "☐ #": marca os 2 à vista
    assert janela.seletor.marcados() == ["1", "2"] and t.heading("n", "text") == "☑ #"
    assert janela.bt_apagar.cget("text") == "✕  Apagar marcados (2)"
    janela.bt_apagar.invoke()
    assert "Apagar os 2 testes marcados?" in perguntas[-1]
    assert not primeiro.exists() and not segundo.exists() and do_jellyfin.exists()
    assert t.get_children() == () and len(janela.seletor.ordem) == 1                 # o do Jellyfin, escondido
    janela.seletor.tirar_filtros()
    assert t.get_children() == ("0",) and t.item("0", "values")[1:3] == ("Jellyfin", "Duna (2021).mkv")
    janela.seletor.abrir_filtro("video")                                 # o filtro por coluna, como na lista
    assert janela.seletor.filtro_aberto is not None
    janela.seletor._janela_filtro.destroy()
    janela.bt_apagar_todos.invoke()
    assert "Apagar o teste de Duna (2021).mkv" in perguntas[-1]
    assert not do_jellyfin.exists() and automacao.testes_feitos() == [] and not t.get_children()
    assert janela.bt_apagar_todos.cget("state") == "disabled" and janela.bt_abrir.cget("state") == "disabled"
    assert legenda.exists()                                              # a legenda do filme não é apagada
    janela.destroy()


def test_teste_dos_avulsos_guarda_a_propria_legenda(tmp_path):
    """A legenda do teste dos Avulsos ('teste.pt-BR.srt', no progresso do vídeo) muda a cada teste: uma cópia fica
    com o teste ("Ajustar falas" de um teste antigo usa as falas DELE) e sai quando o teste é apagado."""
    from videoscraper import automacao
    from jellyfin_tools import dublagem
    video = tmp_path / "Aula.mp4"
    pasta = dublagem.pasta_do_filme(automacao.pasta_dublagem(), video)
    pasta.mkdir(parents=True)
    legenda = pasta / "teste.pt-BR.srt"
    legenda.write_text("primeiro", encoding="utf-8")
    amostra = dublagem.caminho_amostra(automacao.pasta_dublagem(), video)
    amostra.parent.mkdir(parents=True, exist_ok=True)
    amostra.write_bytes(b"x")
    automacao.registrar_teste(video, amostra, (0, 60), legenda, aba="avulsos")
    legenda.write_text("segundo teste", encoding="utf-8")               # o próximo teste reescreve a legenda
    teste = automacao.testes_feitos()[0]
    copia = Path(teste["legenda"])
    assert copia.parent.name == "legendas" and copia.read_text(encoding="utf-8") == "primeiro"
    assert copia.name == f"{amostra.stem}.pt-BR.srt"
    assert automacao.tamanho_dos_testes([teste]) == 1
    assert automacao.apagar_testes([teste]) == 1
    assert not copia.exists() and not amostra.exists() and legenda.exists()


def test_ajustar_falas_escolhe_a_fala_e_o_que_trocar(app, monkeypatch):
    """A janela "Ajustar falas": a fala escolhida, o texto (só se mudou), a voz e o tom; o app refaz só ela."""
    from videoscraper import automacao
    from videoscraper.gui_moderna import DialogoAjustarFalas
    linhas = [(3, "00:00:26", "Sou Agatha.", "Kore", ""), (4, "00:00:29", "Prazer, Sra. Johnson.", "", "")]
    vozes = list(app.vozes_gemini_do_menu())
    d = DialogoAjustarFalas(app, "Filme", linhas, vozes)
    assert d.var_texto.get() == "Sou Agatha." and d.var_voz.get().startswith("Kore")   # a 1ª já escolhida
    d.tabela.selection_set("1")
    d._preencher()
    d.var_texto.set("Prazer em conhecer, senhora.")
    d.var_voz.set(next(v for v in vozes if v.startswith("Leda")))
    d.var_tom.set("tímida, baixo")
    d.bt_refazer.invoke()
    assert d.resultado == (4, "Prazer em conhecer, senhora.", "Leda", "tímida, baixo")
    d2 = DialogoAjustarFalas(app, "Filme", linhas, [])                     # Piper: sem escolher a voz
    assert d2.menu_voz.cget("state") == "disabled"
    d2.bt_refazer.invoke()
    assert d2.resultado == (3, "", "", "")                                # nada mudou: só uma tomada nova
    pedidos = []
    teste = {"video": "/v/Filme.mkv", "amostra": "/t/Filme.mkv", "trecho": [20, 80], "legenda": "/v/Filme.srt"}
    monkeypatch.setattr(automacao, "falas_do_teste", lambda t: linhas)
    monkeypatch.setattr(app, "pedir_ajuste_de_fala", lambda nome, l, v: (4, "", "", "com raiva"))
    monkeypatch.setattr(app, "_rodar", lambda texto, tarefa: pedidos.append(texto))
    app._ajustar_teste(teste)
    assert pedidos == ["Refazendo 1 fala do teste..."]


def test_gastos_mostra_as_cotas_e_guarda_plano_e_flex(app, tmp_path):
    """Configurações > Gastos: a situação de cada API (cota grátis, créditos) e as opções da chave do Gemini e do
    modo Flex (metade do preço)."""
    from jellyfin_tools import gastos, voz_gemini
    from videoscraper import automacao
    app.var_jf_gemini_flex.set(True)
    app.var_jf_plano_gemini.set(app.PLANOS_GEMINI[1])                   # grátis: o Flex desliga (nada a economizar)
    assert app.var_jf_gemini_flex.get() is False and app.cx_gemini_flex.cget("state") == "disabled"
    assert "Troque para \"Paga\"" in app.lb_plano_gemini.cget("text")
    o = app.obter_opcoes_jellyfin()
    assert (o.plano_gemini, o.gemini_flex) == ("gratis", False)
    automacao.configurar_gastos(o, consultar=False)
    assert voz_gemini._flex["ligado"] is False and gastos.atual().plano_gemini == "gratis"
    gastos.marcar_cota("Claude", "créditos acabaram")
    app.atualizar_gastos()
    texto = app.lb_cotas.cget("text")
    assert "Gemini: chave GRÁTIS" in texto and "créditos ACABARAM" in texto
    app.var_jf_plano_gemini.set(app.PLANOS_GEMINI[2])                   # cadastrou o cartão: paga, Flex à escolha
    assert app.cx_gemini_flex.cget("state") == "normal" and "teto" in app.lb_plano_gemini.cget("text")
    app.var_jf_gemini_flex.set(True)
    o = app.obter_opcoes_jellyfin()
    assert (o.plano_gemini, o.gemini_flex) == ("pago", True)
    automacao.configurar_gastos(o, consultar=False)
    assert voz_gemini._flex["ligado"] is True and gastos.atual().plano_gemini == "pago"
    assert "Claude" in app.item_saude_gastos()[0] and app.item_saude_gastos()[1] is False
    voz_gemini.usar_flex(False)


# ------------------------------------------------------------------ aba 🎧 Áudio (trocar o áudio entre versões)
class _PlayerFalso:
    """O VLC "de mentira": guarda o que a aba pediu (tocar, pausar, trocar a faixa de áudio)."""

    def __init__(self):
        self.chamadas, self.tocando, self.faixa, self.janela = [], False, None, None

    def set_media(self, media):
        self.media = media

    def set_hwnd(self, janela):
        self.janela = janela

    set_xwindow = set_nsobject = set_hwnd

    def play(self):
        self.tocando = True
        self.chamadas.append("play")

    def pause(self):
        self.tocando = not self.tocando
        self.chamadas.append("pause")

    def stop(self):
        self.tocando = False
        self.chamadas.append("stop")

    def release(self):
        self.chamadas.append("release")

    def is_playing(self):
        return self.tocando

    def get_time(self):
        return 12000

    def get_length(self):
        return 30000

    def get_state(self):
        return "State.Playing"

    def set_time(self, ms):
        self.chamadas.append(("set_time", ms))

    def audio_get_track_description(self):
        return [(-1, b"Disable"), (1, b"Track 1"), (2, b"Track 2")]

    def audio_set_track(self, faixa):
        self.faixa = faixa


class _VlcFalso:
    def __init__(self):
        self.players = []

    def media_player_new(self):
        self.players.append(_PlayerFalso())
        return self.players[-1]

    def media_new(self, caminho):
        return caminho


def test_aba_audio_textos_do_ajuste():
    from videoscraper.painel_audio import ids_das_faixas, numero_do_texto, segundos_do_texto, texto_segundos
    assert numero_do_texto("−4,30") == -4.3 and numero_do_texto("+5,8 dB") == 5.8 and numero_do_texto("x") is None
    assert segundos_do_texto("58:10") == 3490 and segundos_do_texto("1:02:03") == 3723
    assert segundos_do_texto("auto") is None and segundos_do_texto("") is None and segundos_do_texto("1:2:3:4") is None
    assert texto_segundos(-4.3) == "−4,30" and texto_segundos(1.5) == "+1,50" and texto_segundos(0.001) == "0,00"
    assert ids_das_faixas([(-1, b"Disable"), (3, b"a"), (5, b"b")]) == [3, 5] and ids_das_faixas(None) == []


def _esperar_ondas(app, painel, limite=30):
    fim = time.time() + limite
    while painel._ondas is None and time.time() < fim:
        app.update()
        time.sleep(0.05)
    for _ in range(5):
        app.update()
    assert painel._ondas is not None, "as ondas não chegaram"


def test_aba_audio_ler_conferir_ver_e_inserir(app, tmp_path, monkeypatch):
    """A aba inteira: origem (faixas e legendas marcáveis, idioma descoberto/corrigido), destino ("Já tem"),
    conferir o encaixe (versão europeia com atraso, volume mais baixo), as ondas (arrastar = atraso manual),
    o vídeo de 30 s tocando na aba (troca Faixa nova/Original), Amostras feitas, inserir numa cópia e dentro do
    destino e o histórico (Trocas feitas)."""
    from tests.test_troca_audio import FFMPEG, _par
    if not FFMPEG:
        pytest.skip("sem ffmpeg")
    from videoscraper import audio_moderna, automacao
    from videoscraper.gui_moderna import JanelaTestes
    from videoscraper.painel_audio import JanelaTrocas
    origem, destino = _par(tmp_path, atraso=-4.3, fator=25 / 23.976, legenda=True, volume_origem=0.4, duracao=90)
    monkeypatch.setattr(app, "_detectar_idiomas",       # o Whisper "ouve" a faixa sem idioma: espanhol
                        lambda ffmpeg, info, faixas, o: [setattr(f, "idioma", "spa") or setattr(f, "detectado", True)
                                                         for f in faixas])
    abertos = []
    monkeypatch.setattr(app, "abrir_video", lambda caminho: abertos.append(caminho))
    vlc = _VlcFalso()
    monkeypatch.setattr(audio_moderna, "_VLC", {"instancia": vlc})

    app.mostrar_aba("🎧 Áudio")
    assert app.lb_titulo.cget("text") == "Trocar o áudio entre versões de um filme"
    p = app.painel_audio
    assert p is not None and app.seletor_aba.get() == "🎧 Áudio"
    assert p.bt_conferir.cget("state") == "disabled" and p.bt_inserir.cget("state") == "disabled"
    assert p.bt_ouvir.cget("text") == "🎬 Ver 30 s"

    p.definir_caminho("origem", str(origem))
    app.audio_ler("origem")
    esperar(app)
    t = p.tabela_audios
    assert t.item("a0", "values")[:3] == ("☑ 1", "Português (por)", "AC3")
    assert t.item("a1", "values")[1] == "Espanhol (detectado)" and "Whisper" in t.item("a1", "values")[5]
    assert p.sel_audios.marcados() == ["a0"]                         # a em português já vem marcada
    assert p.tabela_legendas.item("s0", "values")[1:4] == ("Português (por)", "texto (SRT)", "sim")
    assert p.sel_legendas.marcados() == ["s0"]                       # a forçada de texto também
    assert p.bt_conferir.cget("state") == "disabled"                 # falta o destino
    p.definir_idioma(p.info["origem"].audios[1], "ita")              # duplo clique no idioma: corrige
    assert t.item("a1", "values")[1] == "Italiano (ita)"
    p.definir_idioma(p.info["origem"].audios[1], "spa")

    p.definir_caminho("destino", str(destino))
    app.audio_ler("destino")
    esperar(app)
    assert "Já tem: áudio Inglês" in p.lb_ja_tem.cget("text") and p.var_comparar.get().startswith("1. Inglês")
    assert p.bt_conferir.cget("state") == "normal" and p.bt_inserir.cget("text") == "Inserir 1 faixa"

    p.bt_conferir.invoke()
    esperar(app)
    e = p.encaixe
    assert e is not None and e.situacao == "ajuste" and not e.manual
    assert p.var_atraso.get() == "−4,30" and "25 → 23,976" in p.lb_achou.cget("text")
    assert "Encaixa com o ajuste automático" in p.lb_res_titulo.cget("text")
    assert "velocidade 25 → 23,976" in p.lb_res_detalhe.cget("text")
    assert len(p.quadro_pontos.winfo_children()) == 12                # 3 títulos + 3 pontos × 3 colunas
    assert p.var_volume.get() == "Igualar ao áudio original do destino"        # a origem está ~8 dB mais baixa
    assert p.ganho() > 5 and "mais baixa" in p.lb_medido.cget("text")
    assert p.var_ver.get().startswith("30 s em ")                    # as ondas: o trecho do meio
    _esperar_ondas(app, p)
    assert p.tela.find_withtag("nova") and p.tela.find_withtag("verde")
    p.mudar_zoom(1)
    assert p._zoom == 1 and p.tela.find_withtag("destino")

    p.arrastar_atraso(0.5)                                           # arrastou a onda de baixo: ajuste manual
    assert p.var_modo.get() == "Manual" and p.var_atraso.get() == "−3,80" and not p.encaixe_valido
    assert "mudou depois da conferência" in p.lb_res_aviso.cget("text")
    p.voltar_ao_automatico()
    assert p.var_modo.get() == "Automático" and p.var_atraso.get() == "−4,30" and p.encaixe_valido

    p.var_inicio.set("0:40")
    p.bt_ouvir.invoke()                                              # 🎬 Ver 30 s: toca dentro da aba
    esperar(app)
    for _ in range(5):
        app.update()
    teste = automacao.testes_feitos()[0]
    assert teste["aba"] == "audio" and teste["trecho"] == [40.0, 70.0] and "atraso −4,30 s" in teste["detalhe"]
    assert Path(teste["amostra"]).is_file() and abertos == []        # não abriu o player de fora
    player = vlc.players[-1]
    assert player.media == teste["amostra"] and player.tocando and player.janela == p.previa.tela.winfo_id()
    p.previa.seg_ouvir.set("Original")
    p.previa.ouvir("Original")                                       # o áudio original, no mesmo ponto
    assert player.faixa == 2
    p.previa.ouvir("Faixa nova")
    assert player.faixa == 1
    p.previa.alternar()
    assert not player.tocando                                        # ⏸
    p.previa.abrir_no_player()
    assert abertos == [teste["amostra"]]

    p.bt_amostras.invoke()                                           # 📂 Amostras feitas: só as da aba Áudio
    janela = next(w for w in app.winfo_children() if isinstance(w, JanelaTestes))
    assert janela.seletor.filtros["aba"] == {"Áudio"} and janela.tabela.item("0", "values")[6].startswith("Português")
    assert janela.bt_ajustar.cget("state") == "disabled"             # a amostra da aba Áudio não tem falas
    janela.bt_apagar.invoke()                                        # apagar: o vídeo da aba solta o arquivo antes
    assert "release" in player.chamadas and not Path(teste["amostra"]).exists()
    janela.destroy()

    monkeypatch.setattr(audio_moderna, "_VLC", {"instancia": None})  # sem o VLC no PC: abre no player
    p.bt_ouvir.invoke()
    esperar(app)
    for _ in range(5):
        app.update()
    assert len(abertos) == 2 and "instale o VLC" in p.previa.lb_tela.cget("text")

    p.var_onde.set(p.menu_onde.cget("values")[1])                    # numa cópia à parte
    p.bt_inserir.invoke()
    esperar(app)
    copia = destino.with_name("Filme 1080p - com áudio Português.mkv")
    assert copia.is_file() and any("A cópia com a faixa nova" in c[2] for c in app.caixas)
    from jellyfin_tools import troca_audio as ta
    feita = ta.ler_arquivo(FFMPEG, copia)
    assert [a.idioma for a in feita.audios] == ["eng", "por"] and "25 → 23,976" in feita.audios[1].titulo
    assert [(s.idioma, s.forcada) for s in feita.legendas] == [("por", True)]

    p.var_onde.set(p.menu_onde.cget("values")[0])                    # dentro do próprio destino
    p.bt_inserir.invoke()
    esperar(app)
    for _ in range(30):                                              # lê o destino de novo, sozinho
        app.update()
        time.sleep(0.05)
    esperar(app)
    assert "Português" in p.lb_ja_tem.cget("text") and len(p.info["destino"].audios) == 2

    p.bt_trocas.invoke()                                             # 📜 Trocas feitas
    trocas = next(w for w in app.winfo_children() if isinstance(w, JanelaTrocas))
    assert len(trocas.seletor.ordem) == 2
    assert trocas.tabela.item("1", "values")[2:] == ("Filme 1080p.mkv", "Português",
                                                      "atraso −4,30 s · 25 → 23,976 · " + trocas.tabela.item(
                                                          "1", "values")[4].split(" · ")[-1], "cópia à parte")
    assert trocas.tabela.item("0", "values")[5] == "no próprio arquivo"
    trocas.bt_abrir.invoke()
    assert abertos[-1] == str(destino)
    trocas.seletor.marcar_todos()
    trocas.bt_tirar.invoke()
    assert ta.trocas_feitas(app.arquivo_trocas) == [] and copia.exists()    # tirar do histórico não apaga nada
    trocas.destroy()


def test_aba_audio_versoes_diferentes_desligam_inserir(app, tmp_path, monkeypatch):
    from tests.test_troca_audio import FFMPEG, _par
    if not FFMPEG:
        pytest.skip("sem ffmpeg")
    origem, destino = _par(tmp_path, atraso=2.0, corte=(40.0, 6.0))
    app.mostrar_aba("🎧 Áudio")
    p = app.painel_audio
    for lado, caminho in (("origem", origem), ("destino", destino)):
        p.definir_caminho(lado, str(caminho))
        app.audio_ler(lado)
        esperar(app)
    p.sel_audios.marcar(["a0"], somar=False)
    p.bt_conferir.invoke()
    esperar(app)
    assert p.encaixe.situacao == "cortes" and "Versões diferentes" in p.lb_res_titulo.cget("text")
    assert p.bt_inserir.cget("state") == "disabled" and "fica desligado" in p.lb_res_aviso.cget("text")
    assert p.bt_extrair.cget("state") == "normal"
    app.audio_inserir()                                              # mesmo chamando direto: não insere
    assert any("versões são diferentes" in c[2] for c in app.caixas)
    assert len(app.painel_audio.info["destino"].audios) == 1


def test_importar_voz_pelas_configuracoes(app, tmp_path, monkeypatch):
    """Configurações > Dublagem > "Importar voz": um modelo do Piper vira uma voz do menu, com o nome, o gênero e a
    idade; vídeo é recusado; uma gravação (só com a declaração, sem consentimento) fica guardada para o XTTS-v2;
    remover apaga a voz e a escolhida volta para a padrão."""
    from tests.test_voz_clonada import FFMPEG, wav
    from tests.test_vozes_importadas import modelo_piper
    from videoscraper import automacao, config, gui_moderna
    app.mostrar_aba(app.ABA_CONFIG)
    app._botoes_config["Dublagem"].invoke()
    assert "Nenhuma voz importada" in app.lb_vozes_importadas.cget("text")
    assert app.bt_remover_voz_importada.cget("state") == "disabled"
    assert not hasattr(app, "var_imp_consentimento")                 # a importação não pede consentimento
    app.bt_importar_voz.invoke()                                     # sem arquivo: avisa
    assert "Escolha o arquivo" in app.caixas[-1][2]
    app.var_imp_arquivo.set(str(tmp_path / "Filme (2020).mkv"))     # áudio de vídeo: nunca (voz de atores)
    app.bt_importar_voz.invoke()
    assert app.caixas[-1][0] == "aviso" and "atores" in app.caixas[-1][2]
    # um modelo do Piper: escolher o arquivo sugere o nome; gênero e idade vão junto
    onnx = modelo_piper(tmp_path)
    monkeypatch.setattr(gui_moderna.filedialog, "askopenfilename", lambda **k: str(onnx))
    app.var_imp_nome.set("")
    app.ao_escolher_arquivo_voz()
    assert app.var_imp_nome.get() == "Cadu"
    app.var_imp_genero.set("Masculina")
    app.var_imp_idade.set("Jovem")
    app.bt_importar_voz.invoke()
    assert app.caixas[-1][0] == "sucesso" and "Voz do Piper" in app.caixas[-1][2]
    assert "cadu" in app.menu_voz_piper.cget("values") and app.var_imp_arquivo.get() == ""
    assert (config.ARQUIVO.parent / "vozes" / "cadu.onnx").is_file()
    assert automacao.vozes_importadas()[0].perfil == "masculina, jovem"
    app.var_jf_voz_dublagem.set("cadu")
    assert app.obter_opcoes_jellyfin().voz_dublagem == "cadu"
    if FFMPEG:                                                       # uma gravação: só a declaração
        referencia = tmp_path / "minha voz.wav"
        referencia.write_bytes(wav(12))
        app.var_imp_arquivo.set(str(referencia))
        app.var_imp_nome.set("Izael")
        app.var_imp_genero.set("Masculina")
        app.var_imp_idade.set("Adulta")
        app.bt_importar_voz.invoke()
        esperar(app)
        assert "declaração" in app.caixas[-1][2]                     # falta marcar a declaração
        app.var_imp_autorizo.set(True)
        app.bt_importar_voz.invoke()
        esperar(app)
        assert app.caixas[-1][0] == "sucesso" and "masculina, adulta" in app.caixas[-1][2]
        assert "Izael: gravação para clonar · masculina, adulta" in app.lb_vozes_importadas.cget("text")
    # remover o modelo do Piper: some do menu, os arquivos saem do PC e a voz escolhida volta para a padrão
    app.escolher_da_lista = lambda *a, **k: 0
    app.bt_remover_voz_importada.invoke()
    assert "cadu" not in app.menu_voz_piper.cget("values") and app.var_jf_voz_dublagem.get() == "faber"
    assert not (config.ARQUIVO.parent / "vozes" / "cadu.onnx").exists()
