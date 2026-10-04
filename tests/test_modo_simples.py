"""Modo padrão (requests, sem navegador)."""
import json

from videoscraper import cli
from videoscraper.coleta import FonteRequests, rastrear
from videoscraper.rede import ClienteHTTP


def _fonte():
    return FonteRequests(ClienteHTTP(espera=0))


def test_rastreio_e_profundidade(servidor):
    assert len(rastrear(_fonte(), servidor.base + "/estatica")) == 7
    links = rastrear(_fonte(), servidor.base + "/estatica", profundidade=1)
    assert any(l.url.endswith("/m/sub.mp4") for l in links)


def test_robots_bloqueia(servidor):
    c = ClienteHTTP(espera=0)
    assert not c.permitido(servidor.base + "/proibido/x")
    assert c.permitido(servidor.base + "/estatica")


def test_salvar_formatos(servidor, tmp_path, capsys):
    for nome in ("l.txt", "l.csv", "l.json"):
        assert cli.main(["links", servidor.base + "/estatica", "-e", "0", "-s", str(tmp_path / nome)]) == 0
    assert len(json.loads((tmp_path / "l.json").read_text(encoding="utf-8"))) == 7
    assert (tmp_path / "l.csv").read_text(encoding="utf-8-sig").startswith("url,origem,tipo,titulo")


def test_baixar_por_seletor_com_acentos(servidor, tmp_path):
    pasta = tmp_path / "v"
    codigo = cli.main(["baixar", servidor.base + "/lista", "--seletor", "a.video-link",
                       "-d", str(pasta), "-e", "0"])
    assert codigo == 2                                         # 1 falha (404)
    assert [a.name for a in pasta.iterdir()] == ["Filme Ação 1.mp4"]   # sem sobra de .part


def test_baixar_detectando_sozinho_pula_youtube(servidor, tmp_path, capsys):
    cli.main(["baixar", servidor.base + "/sub", "-d", str(tmp_path), "-e", "0"])
    assert (tmp_path / "sub.mp4").exists()


def test_pagina_com_javascript_nao_aparece_no_modo_simples(servidor, capsys):
    assert rastrear(_fonte(), servidor.base + "/js") == []
    cli.main(["links", servidor.base + "/js", "-e", "0"])
    assert "--navegador" in capsys.readouterr().err            # dá a dica certa
