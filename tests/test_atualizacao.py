"""Aviso de versão nova (página Releases do GitHub), com um servidor falso no lugar do GitHub."""
from videoscraper import atualizacao


def test_compara_numero_por_numero():
    assert atualizacao.numeros("v1.10") > atualizacao.numeros("v1.9")
    assert atualizacao.numeros("1.5.0") == (1, 5, 0) and atualizacao.numeros("sem número") == (0,)


def test_avisa_so_quando_ha_versao_mais_nova(api_falsa):
    rota = "/repos/izaeldepetriz-br/Webscraping/releases/latest"
    api_falsa.rotas[rota] = lambda q: (200, {"tag_name": "v1.6", "html_url": "https://github.com/x/releases/tag/v1.6",
                                             "body": "Canais ao vivo"})
    nova = atualizacao.verificar("v1.5", api=api_falsa.base)
    assert (nova.versao, nova.url, nova.notas) == ("v1.6", "https://github.com/x/releases/tag/v1.6", "Canais ao vivo")
    assert atualizacao.verificar("v1.6", api=api_falsa.base) is None              # já é a mais nova
    assert atualizacao.verificar("v2.0", api=api_falsa.base) is None
    api_falsa.rotas[rota] = lambda q: (404, {})
    assert atualizacao.verificar("v1.5", api=api_falsa.base) is None              # sem versão publicada
    assert atualizacao.verificar("v1.5", api="http://127.0.0.1:9", timeout=1) is None   # sem internet: quieto


def test_versao_do_exe_vem_do_arquivo_gravado_pelo_github(tmp_path, monkeypatch):
    monkeypatch.setattr(atualizacao.sys, "_MEIPASS", str(tmp_path), raising=False)
    (tmp_path / "videoscraper").mkdir()
    (tmp_path / "videoscraper" / "versao_build.txt").write_text("v1.7", encoding="utf-8")
    assert atualizacao.versao_atual() == "v1.7"
