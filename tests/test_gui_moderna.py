"""Interface moderna (CustomTkinter): a View sozinha e o app ligado ao motor.
Precisa de customtkinter e de uma tela (no Linux sem monitor: xvfb-run python -m pytest)."""
import os
import time
from pathlib import Path

import pytest

pytest.importorskip("tkinter")
ctk = pytest.importorskip("customtkinter")
if os.name != "nt" and not os.environ.get("DISPLAY"):
    pytest.skip("sem tela (DISPLAY) para abrir janelas", allow_module_level=True)

from videoscraper import app_moderna  # noqa: E402
from videoscraper.gui_moderna import CampoNumerico, JanelaModerna  # noqa: E402
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
        assert o.navegador and o.visivel and o.pausar and o.espera == 1.5 and o.max_paginas == 30
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
    a.escolher = lambda t, m, opcoes: opcoes[0]             # escolhe o botão principal sozinho
    a.campo_espera.set(0.5)
    a.var_pasta.set(str(tmp_path / "videos"))
    yield a
    a.trabalhando = False
    try:
        a.fechar()
    except Exception:
        pass


def esperar(app, limite=90):
    fim = time.time() + limite
    app.update()
    while app.trabalhando and time.time() < fim:
        app.update()
        time.sleep(0.05)
    for _ in range(5):
        app.update()
        time.sleep(0.12)
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


def test_baixar_todos_com_falha_e_robots(app, servidor):
    app.definir_url(servidor.base + "/lista")
    app.var_seletor.set("a.video-link")
    app.bt_baixar_todos.invoke()                         # sem buscar antes: busca e baixa
    esperar(app)
    assert app.tabela.item("1", "values")[1].endswith("erro")
    assert app.caixas[-1][0] == "erro"

    app.var_seletor.set("")
    app.definir_url(servidor.base + "/proibido/videos")
    app.bt_buscar.invoke()
    esperar(app)
    assert ("aviso", "Acesso não permitido", MENSAGEM_ROBOTS) in app.caixas


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
    perguntas = []
    app.perguntar = lambda t, m: perguntas.append(m) or True
    app.bt_organizar.invoke()
    esperar(app)
    assert "1 deles estão escondidos pelo filtro" in perguntas[0]                 # avisa antes de mover
    assert (biblioteca / "Cidade de Deus (2002)" / "Cidade de Deus (2002).mkv").exists()
    app.vars_filtro_jf["movido"].set(False)                                       # "movido" também some
    app.aplicar_filtro_jf()
    assert [l[2] for l in _linhas_jf(app)] == ["video_sem_ano.mp4"]

    app._salvar_config()                                                          # o filtro é lembrado
    assert set(config.carregar()["jellyfin"]["filtros_ocultos"]) == {"organizado", "mover", "movido"}


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
def test_completar_biblioteca_pergunta_se_substitui(app, servicos_gui, tmp_path):
    pasta = tmp_path / "Filmes" / "Velhos Bandidos (2026)"
    pasta.mkdir(parents=True)
    (pasta / "Velhos Bandidos (2026).mkv").write_bytes(b"v")
    (pasta / "Velhos Bandidos (2026).pt-BR.srt").write_text("antiga", encoding="utf-8")
    (pasta / "poster.png").write_bytes(b"antigo")
    app.var_jf_destino.set(str(tmp_path / "Filmes"))
    perguntas = []

    def responder(resposta):
        app.escolher = lambda t, m, opcoes: (perguntas.append(opcoes), resposta)[1]

    responder(None)                                                      # Cancelar: nada acontece
    app.bt_legendas.invoke()
    esperar(app)
    assert (pasta / "poster.png").read_bytes() == b"antigo" and not (pasta / "poster.jpg").exists()
    assert perguntas[-1] == ("Só o que falta", "Substituir o que já existe")

    responder("Só o que falta")
    app.bt_legendas.invoke()
    esperar(app)
    assert (pasta / "Velhos Bandidos (2026).pt-BR.srt").read_text(encoding="utf-8") == "antiga"
    assert (pasta / "poster.png").exists() and not (pasta / "poster.jpg").exists()
    assert _linhas_jf(app)[0][4].endswith("já existia")

    responder("Substituir o que já existe")
    app.bt_legendas.invoke()
    esperar(app)
    assert (pasta / "Velhos Bandidos (2026).pt-BR.srt").read_text(encoding="utf-8") != "antiga"
    assert (pasta / "poster.jpg").is_file() and not (pasta / "poster.png").exists()   # trocou, sem duplicar
    assert _linhas_jf(app)[0][4].endswith("baixada")
    assert app.var_jf_sobrescrever.get()                                  # a caixa acompanha a escolha
    app.bt_legendas.invoke()
    esperar(app)
    assert perguntas[-1][0] == "Substituir o que já existe"              # e vira a opção principal


def test_ampliar_lista_esconde_painel_e_console(app):
    app.mostrar_aba("Jellyfin")
    app.update()
    for i in range(40):
        app.adicionar_linha_jf(str(i), i + 1, "vai mover", None, f"a{i}.mkv", f"A {i}.mkv")
    app.update()
    altura = app.tabela_jf.winfo_height()
    assert app._cartao_console_jf.winfo_ismapped() and app._cartao_detalhe_jf.winfo_ismapped()
    app.bt_ampliar_jf.invoke()
    app.update()
    assert not app._cartao_console_jf.winfo_ismapped() and not app._cartao_detalhe_jf.winfo_ismapped()
    assert app.tabela_jf.winfo_height() > altura and app.bt_ampliar_jf.cget("text").endswith("Reduzir lista")
    app.bt_ampliar_jf.invoke()
    app.update()
    assert app._cartao_console_jf.winfo_ismapped() and app.bt_ampliar_jf.cget("text").endswith("Ampliar lista")


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
    app.mostrar_aba("Jellyfin")
    app.var_jf_fonte.set("OpenSubtitles (API)")
    app._mostrar_campos_jf()
    app.update()
    assert app.campo_chave_subdl.winfo_ismapped() and "Reserva" in app.rot_chave_subdl.cget("text")
    app.var_jf_chave_os.set("chave-os")
    with app._provedores(app.obter_opcoes_jellyfin()) as provedores:      # sem chave do SubDL: só o OS
        assert [type(p) for p in provedores] == [ProvedorOpenSubtitles]
    app.var_jf_chave_subdl.set("chave-subdl")
    with app._provedores(app.obter_opcoes_jellyfin()) as provedores:      # com ela: OS e, depois, o SubDL
        assert [type(p) for p in provedores] == [ProvedorOpenSubtitles, ProvedorSubDL]

    app.var_jf_fonte.set("SubDL (API)")
    app._mostrar_campos_jf()
    app.update()
    assert not app.campo_chave_os.winfo_ismapped() and app.rot_chave_subdl.cget("text") == "Chave da API do SubDL:"
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
    app.escolher = lambda t, m, opcoes: (perguntas.append(m), opcoes[0])[1]   # "Só domínio público / CC"
    app.ao_espelhar_jellyfin()
    esperar(app)
    assert "2 filme(s), 1 episódio(s), 1 sem ano/episódio" in perguntas[-1]
    assert sorted(p.name for p in tmp_path.rglob("*.strm")) == ["Nosferatu (1922).strm"]
    situacoes = [app.tabela.item(i, "values")[1] for i in app.tabela.get_children()]
    assert situacoes[0].endswith("espelhado") and situacoes[1].endswith("sem licença aberta")
    assert app.caixas[-1][1] == "Espelho no Jellyfin" and "Criados: 1 (1 filme(s), 0 episódio(s))" in app.caixas[-1][2]

    app.escolher = lambda t, m, opcoes: opcoes[1]                    # "Todos os identificados"
    app.ao_espelhar_jellyfin()
    esperar(app)
    assert sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*.strm")) == [
        "Filmes/Anjos Da Noite (2003)/Anjos Da Noite (2003).strm", "Filmes/Nosferatu (1922)/Nosferatu (1922).strm",
        "Series/Dark (2017)/Season 01/Dark S01E02.strm"]
    assert app.tabela.item("0", "values")[1].endswith("já espelhado")


def test_botao_testar_chaves_das_legendas(app, api_falsa, monkeypatch):
    from jellyfin_tools import ProvedorOpenSubtitles, ProvedorSubDL
    base = api_falsa.base
    monkeypatch.setattr(app_moderna, "ProvedorOpenSubtitles", lambda k: ProvedorOpenSubtitles(k, base_url=base + "/os"))
    monkeypatch.setattr(app_moderna, "ProvedorSubDL", lambda k: ProvedorSubDL(k, base_url=base + "/api/v1"))
    api_falsa.rotas["/os/subtitles"] = lambda q: (200, {"total_count": 7, "data": []})
    api_falsa.rotas["/api/v1/subtitles"] = lambda q: (403, {"status": False, "error": "invalid api key"})
    app.mostrar_aba("Jellyfin")
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
    app.var_jf_fonte.set("Site de demonstração")
    app._mostrar_campos_jf()
    app.update()
    assert not app.bt_testar_legendas.winfo_ismapped()                    # o site demo não tem chave


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
    app.bt_conferir_espelhos.invoke()
    esperar(app)
    esperar(app)                                                         # a remoção oferecida no fim
    assert [l[1].split()[-1] for l in _linhas_jf(app)] == ["funcionando", "quebrado"]
    assert "Espelhos quebrados" in perguntas
    assert not (filmes / "Quebrado (2001)" / "Quebrado (2001).strm").exists()
    assert (filmes / "Bom (2000)" / "Bom (2000).strm").exists()
    app.bt_desfazer.invoke()                                              # volta o removido
    esperar(app)
    assert (filmes / "Quebrado (2001)" / "Quebrado (2001).strm").exists()


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
