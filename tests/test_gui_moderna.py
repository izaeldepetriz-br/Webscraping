"""Interface moderna (CustomTkinter): a View sozinha e o app ligado ao motor.
Precisa de customtkinter e de uma tela (no Linux sem monitor: xvfb-run python -m pytest)."""
import os
import time

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
    assert linhas["Dark.S01E02.WEBRip.mkv"][3] == "Dark (2017)/Season 01/Dark S01E02.mkv"
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
