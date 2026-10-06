"""Vídeos que só carregam com um clique no poster/play: o navegador clica no centro do player e espera (até
espera_midia s) a mídia começar a carregar. Os testes com o Chromium são pulados se ele não estiver disponível."""
import os
import time

import pytest

from videoscraper.navegador import Navegador
from videoscraper.rede import eh_plataforma_protegida


def test_mudanca_de_estado_da_midia():
    parado = [[0, 1, "", 0]]                         # readyState 0, networkState 1 (IDLE), sem buffer
    assert not Navegador._carregando(parado, [[0, 1, "", 0]])
    assert Navegador._carregando(parado, [[1, 1, "", 0]])               # chegaram os metadados
    assert Navegador._carregando(parado, [[0, 2, "", 0]])               # começou a baixar (LOADING)
    assert Navegador._carregando(parado, [[0, 1, "http://a/v.mp4", 0]])  # ganhou endereço
    assert Navegador._carregando(parado, [[0, 1, "", 1]])               # pedaços no buffer
    assert Navegador._carregando([], [[0, 0, "", 0]])                   # um <video> novo apareceu
    assert not Navegador._carregando([[4, 2, "x", 1]], [[4, 2, "x", 1]])


def test_plataformas_protegidas_por_endereco_ou_site():
    assert eh_plataforma_protegida("https://rr3---sn-abc.googlevideo.com/videoplayback?x=1")
    assert eh_plataforma_protegida("https://www.youtube.com/watch?v=1") and eh_plataforma_protegida("youtu.be")
    assert not eh_plataforma_protegida("https://meusite.com.br/videos/aula.mp4")
    assert not eh_plataforma_protegida("http://127.0.0.1:8000/m/x.mp4")


def _chromium_disponivel():
    try:
        with Navegador(perfil=os.path.join(os.environ.get("TMPDIR", "/tmp"), "vs-teste-perfil")):
            return True
    except Exception:
        return False


com_chromium = pytest.mark.skipif(not _chromium_disponivel(), reason="Playwright/Chromium indisponível")


@com_chromium
def test_clica_no_play_e_espera_o_video_carregar(servidor, tmp_path):
    with Navegador(perfil=str(tmp_path / "p"), espera_extra=0) as nav:
        html, _, _, midias = nav.renderizar(servidor.base + "/clique-cria-video")      # o <video> nasce no clique
        assert servidor.base + "/m/clicado.mp4" in midias and "<video" in html          # chegou pela rede
        _, _, _, midias = nav.renderizar(servidor.base + "/poster-sobreposto")          # camada por cima do poster
        assert servidor.base + "/m/poster.mp4" in midias                                # carregou de verdade (rede)


@com_chromium
def test_sem_ativar_nada_carrega_e_link_por_cima_nao_e_clicado(servidor, tmp_path):
    with Navegador(perfil=str(tmp_path / "p"), espera_extra=0, ativar_midias=False) as nav:
        html, _, _, midias = nav.renderizar(servidor.base + "/clique-cria-video")
        assert "<video" not in html and not midias                                      # ninguém clicou
    with Navegador(perfil=str(tmp_path / "p"), espera_extra=0) as nav:
        _, url_final, _, midias = nav.renderizar(servidor.base + "/poster-com-link")
        assert url_final == servidor.base + "/poster-com-link"                          # não saiu da página
        assert servidor.base + "/m/linkado.mp4" not in midias                           # e não tocou


@com_chromium
def test_espera_tem_limite_quando_o_play_nao_faz_nada(servidor, tmp_path):
    with Navegador(perfil=str(tmp_path / "p"), espera_extra=0, espera_midia=1.0) as nav:
        inicio = time.monotonic()
        _, _, _, midias = nav.renderizar(servidor.base + "/play-mudo")
        assert not midias and time.monotonic() - inicio < 1.0 + 20                      # 1 s de espera, não para sempre
        pagina = nav.contexto.new_page()
        try:
            pagina.goto(servidor.base + "/play-mudo")
            inicio = time.monotonic()
            assert nav._ativar_midias(pagina, []) == 0
            assert 0.9 <= time.monotonic() - inicio < 4                                  # esperou o limite e seguiu
        finally:
            pagina.close()
