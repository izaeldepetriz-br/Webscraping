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
    a.escolher = lambda t, m, opcoes, **k: opcoes[0]        # escolhe o botão principal sozinho
    a._pedir_o_que_completar = lambda pasta, padrao, series: dict(padrao)   # "Completar": a escolha padrão
    a.escolher_da_lista = lambda *args, **k: None           # lista de opções: "Cancelar"
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
    app.ao_gerenciar_espelhos()
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
    linhas = _linhas_jf(app)
    assert len(linhas) == 1 and "funcionando" in linhas[0][1]        # antes: "0 de 1", tela vazia
    assert all(v.get() for v in app.vars_filtro_jf.values())


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
    app.bt_tv_ao_vivo.invoke()
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
    app.bt_tv_ao_vivo.invoke()
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


def test_tv_ao_vivo_filtro_por_coluna(app):
    """Clique no título da coluna: escolher um ou vários valores (Situação, Grupo, Link pelo site)."""
    from jellyfin_tools.tv_ao_vivo import Canal, Situacao
    app.mostrar_aba("Jellyfin")
    app.bt_tv_ao_vivo.invoke()
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
    app.bt_tv_ao_vivo.invoke()
    app._canais = [Canal(f"C{n}", f"{api_falsa.base}/lento.m3u8?n={n}") for n in range(400)]
    app._conferir_canais()
    fim = time.time() + 1.2
    while time.time() < fim:
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
    app.bt_tv_ao_vivo.invoke()
    janela = app.janela_canais
    app._canais = [Canal("TV Cultura", "https://a.org/1.m3u8", "Abertos"), Canal("Rádio", "https://b.net/r.mp3", "Rádios")]
    app._situacao_canais = {app._canais[1].url: Situacao(False, "fora do ar (HTTP 404)")}
    app._mostrar_canais()
    assert janela.exportar(tmp_path / "todos.json") == 2
    dados = json.loads((tmp_path / "todos.json").read_text(encoding="utf-8"))
    assert dados[0] == {"numero": "", "canal": "TV Cultura", "grupo": "Abertos", "situacao": "", "no_ar": None,
                        "historico": "", "link": "https://a.org/1.m3u8"}
    janela.aplicar_filtro("grupo", ["Rádios"])                          # com filtro: só os filtrados
    from videoscraper import gui_moderna
    monkeypatch.setattr(gui_moderna.filedialog, "asksaveasfilename", lambda **k: str(tmp_path / "filtrados.csv"))
    janela.bt_exportar.invoke()
    linhas = (tmp_path / "filtrados.csv").read_text(encoding="utf-8-sig").splitlines()
    assert len(linhas) == 2 and linhas[1].startswith(";Rádio;Rádios;fora do ar (HTTP 404);não;")
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
    app.bt_tv_ao_vivo.invoke()
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
    app.bt_tv_ao_vivo.invoke()
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
    app.bt_tv_ao_vivo.invoke()
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
    pastas, _, _ = app._alvos_da_vigia(app.obter_opcoes_jellyfin())
    assert pastas == [str(downloads), str(filmes)]                      # a biblioteca também pode ser vigiada
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


def _vigia_nas_bibliotecas(app, tmp_path, filmes_escolhida=True):
    """O jeito do usuário: os arquivos caem DENTRO das bibliotecas e a vigia arruma no lugar."""
    import os
    series, filmes = tmp_path / "Series_Organizadas", tmp_path / "Filmes_Organizados"
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


def test_botao_atualizar_a_biblioteca_agora(app, api_falsa):
    api_falsa.rotas["/Library/Refresh"] = lambda q: (204, b"")
    app.mostrar_aba("Jellyfin")
    app.var_jf_url.set("")
    app.bt_scan_jellyfin.invoke()
    assert "Preencha o endereço e a chave" in app.caixas[-1][2]
    app.var_jf_url.set(api_falsa.base)
    app.var_jf_chave_jellyfin.set("chave")
    app.bt_scan_jellyfin.invoke()
    esperar(app)
    assert any(p["caminho"] == "/Library/Refresh" for p in api_falsa.pedidos)
    assert "está escaneando as bibliotecas" in app.caixas[-1][2]


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
    app.escolher_da_lista = lambda titulo, msg, itens, botao="", marcado=None: (
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
    app.escolher_da_lista = lambda t, m, itens, botao="", marcado=None: next(
        n for n, i in enumerate(itens) if "mais de 90 dias" in i)
    app.ao_memoria_downloads()
    assert app.memoria_downloads.baixado(links[0]) is None and app.memoria_downloads.baixado(links[1]) is not None
    assert "já baixado" not in app.tabela.set("0", "status") and "já baixado" in app.tabela.set("1", "status")
    # selecionados: esquece o ep2
    app.tabela.selection_set(["1"])
    app.escolher_da_lista = lambda t, m, itens, botao="", marcado=None: (
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
