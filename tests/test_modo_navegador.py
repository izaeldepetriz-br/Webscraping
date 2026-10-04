"""Modo --navegador (Playwright). Pulado se o Playwright/Chromium não estiver disponível."""
import os

import pytest

from videoscraper import cli
from videoscraper.coleta import FonteNavegador, rastrear
from videoscraper.navegador import Navegador
from videoscraper.rede import ClienteHTTP


def _chromium_disponivel():
    try:
        with Navegador(perfil=os.path.join(os.environ.get("TMPDIR", "/tmp"), "vs-teste-perfil")):
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _chromium_disponivel(), reason="Playwright/Chromium indisponível")


def test_navegador_ve_conteudo_de_javascript_e_da_rede(servidor, tmp_path):
    fonte = FonteNavegador(ClienteHTTP(espera=0), Navegador(perfil=str(tmp_path / "p"), espera_extra=0.5))
    try:
        links = {l.url: l for l in rastrear(fonte, servidor.base + "/js")}
    finally:
        fonte.fechar()
    assert links[servidor.base + "/m/js.mp4"].titulo == "Aula JS"      # veio do DOM montado por JS
    if servidor.tem_hls:
        assert links[servidor.base + "/hls/master.m3u8"].tipo == "rede"  # capturado na rede


def test_baixar_arquivo_e_streaming_pelo_navegador(servidor, tmp_path):
    if not servidor.tem_hls:
        pytest.skip("ffmpeg indisponível para gerar HLS de teste")
    pasta = tmp_path / "v"
    codigo = cli.main(["baixar", servidor.base + "/js", "--navegador", "--perfil", str(tmp_path / "p"),
                       "-d", str(pasta), "-e", "0"])
    assert codigo == 0
    nomes = sorted(a.name for a in pasta.iterdir())
    assert nomes == ["Aula JS.mp4", "master.mp4"]
    assert (pasta / "master.mp4").read_bytes()[4:8] == b"ftyp"          # mp4 válido montado pelo ffmpeg


def test_sessao_de_login_fica_salva_e_vale_para_o_download(servidor, tmp_path):
    perfil = str(tmp_path / "perfil")
    pasta = tmp_path / "v"
    # Sem login: a área logada não mostra nada.
    cli.main(["baixar", servidor.base + "/area-logada", "--navegador", "--perfil", perfil,
              "--seletor", "a.video-link", "-d", str(pasta), "-e", "0"])
    assert not pasta.exists() or not any(pasta.iterdir())
    # 'Login' (no app real é você na janela; aqui o servidor só entrega o cookie).
    with Navegador(perfil=perfil, espera_extra=0) as nav:
        nav.renderizar(servidor.base + "/login-cookie")
    # Nova execução, mesmo perfil: o login continua valendo, inclusive no download via requests.
    codigo = cli.main(["baixar", servidor.base + "/area-logada", "--navegador", "--perfil", perfil,
                       "--seletor", "a.video-link", "-d", str(pasta), "-e", "0"])
    assert codigo == 0
    assert (pasta / "Exclusivo.mp4").read_bytes().startswith(b"\x00\x00\x00\x18ftyp")


def test_busca_com_shadow_dom_e_profundidade(servidor, tmp_path):
    """Como a busca do archive.org: resultados em shadow DOM, vídeo só na página de cada item."""
    from videoscraper.coleta import FonteRequests
    simples = FonteRequests(ClienteHTTP(espera=0))
    assert rastrear(simples, servidor.base + "/busca-shadow", profundidade=1) == []   # HTML cru: nada

    fonte = FonteNavegador(ClienteHTTP(espera=0), Navegador(perfil=str(tmp_path / "p"), espera_extra=0.3))
    try:
        so_busca = rastrear(fonte, servidor.base + "/busca-shadow", profundidade=0)
        com_itens = rastrear(fonte, servidor.base + "/busca-shadow", profundidade=1)
    finally:
        fonte.fechar()
    assert so_busca == []                                   # nível 0: a busca em si não tem vídeo
    assert sorted(l.url for l in com_itens) == [servidor.base + "/m/item1.mp4", servidor.base + "/m/item2.mp4"]
