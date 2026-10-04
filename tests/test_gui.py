"""Testa a janela 'clicando' nos botões pelo código. Precisa de Tkinter e de uma tela
(no Linux sem monitor: xvfb-run python -m pytest). Pulado automaticamente se não houver."""
import os
import time

import pytest

tk = pytest.importorskip("tkinter")
if os.name != "nt" and not os.environ.get("DISPLAY"):
    pytest.skip("sem tela (DISPLAY) para abrir janelas", allow_module_level=True)

from videoscraper import gui  # noqa: E402
from videoscraper.servico import MENSAGEM_ROBOTS  # noqa: E402


@pytest.fixture
def app(monkeypatch, tmp_path):
    caixas = []   # mensagens que apareceriam em caixas de diálogo (respondemos OK sozinhos)
    for nome in ("showinfo", "showwarning", "showerror"):
        monkeypatch.setattr(gui.messagebox, nome, lambda t, m, n=nome: caixas.append((n, t, m)))
    monkeypatch.setattr(gui.messagebox, "askokcancel", lambda *a: True)
    monkeypatch.setattr(gui, "PERFIL_PADRAO", str(tmp_path / "perfil"))
    raiz = tk.Tk()
    a = gui.App(raiz)
    a.caixas = caixas
    a.var_espera.set(0.5)
    a.var_pasta.set(str(tmp_path / "videos"))
    yield a
    if raiz.winfo_exists():
        a.trabalhando = False
        a.fechar()


def esperar(app, limite=90):
    fim = time.time() + limite
    app.raiz.update()
    while app.trabalhando and time.time() < fim:
        app.raiz.update()
        time.sleep(0.05)
    for _ in range(5):          # processa o que sobrou na fila
        app.raiz.update()
        time.sleep(0.12)
    assert not app.trabalhando, "a tarefa não terminou a tempo"


def linhas(app):
    return [app.tabela.item(i, "values") for i in app.tabela.get_children()]


def test_buscar_selecionar_e_baixar(app, servidor):
    app.redirecionar_saida()        # o pytest troca o sys.stdout entre as fases do teste
    app.var_url.set(servidor.base + "/lista")
    app.var_seletor.set("a.video-link")
    app.buscar()
    esperar(app)
    assert [l[2] for l in linhas(app)] == ["Filme: Ação/1?", "Quebrado"]

    app.tabela.selection_set("0")
    app.baixar(so_selecionados=True)
    esperar(app)
    assert linhas(app)[0][1] == "baixado"
    assert os.listdir(app.var_pasta.get()) == ["Filme Ação 1.mp4"]
    assert app.caixas[-1][1] == "Downloads concluídos"
    assert "Filme" in app.log.get("1.0", "end")         # o 'print' foi parar no log da janela


def test_endereco_sem_https_e_robots_bloqueado(app, servidor):
    app.var_url.set(servidor.base.replace("http://", "") + "/proibido/videos")
    app.buscar()
    esperar(app)
    assert app.var_url.get().startswith("https://")      # completou o endereço sozinho
    # https num servidor http falha; testamos o bloqueio com o endereço certo:
    app.var_url.set(servidor.base + "/proibido/videos")
    app.buscar()
    esperar(app)
    assert ("showwarning", "Acesso não permitido", MENSAGEM_ROBOTS) in app.caixas


def test_baixar_todos_sem_buscar_antes(app, servidor):
    app.var_url.set(servidor.base + "/sub")
    app.baixar(so_selecionados=False)
    esperar(app)
    assert os.listdir(app.var_pasta.get()) == ["sub.mp4"]


def _tem_chromium():
    from test_modo_navegador import _chromium_disponivel
    return _chromium_disponivel()


@pytest.mark.skipif(not _tem_chromium(), reason="Playwright/Chromium indisponível")
def test_navegador_com_pausa_e_login(app, servidor):
    # Página com JavaScript + pausa (janela visível): o programa pede "Sua vez" e espera o OK.
    app.var_url.set(servidor.base + "/js")
    app.var_pausar.set(True)
    app._ajustar_checks()
    assert app.var_nav.get() and app.var_visivel.get()
    app.buscar()
    esperar(app)
    assert any(c[1] == "Sua vez" for c in app.caixas)
    assert "Aula JS" in [l[2] for l in linhas(app)]

    # Login: abre o site, 'você' entra (o servidor entrega o cookie), clica OK; depois a área logada aparece.
    app.var_pausar.set(False)
    app.var_visivel.set(False)
    app.var_url.set(servidor.base + "/login-cookie")
    app.login()
    esperar(app)
    assert app.var_nav.get()                              # marcou 'Usar navegador' sozinho
    app.var_url.set(servidor.base + "/area-logada")
    app.var_seletor.set("a.video-link")
    app.buscar()
    esperar(app)
    assert [l[2] for l in linhas(app)] == ["Exclusivo"]
