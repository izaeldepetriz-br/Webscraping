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


def test_ultima_versao_e_baixar_o_zip(api_falsa, tmp_path):
    import pytest
    rota = "/repos/izaeldepetriz-br/Webscraping/releases/latest"
    api_falsa.rotas[rota] = lambda q: (200, {"tag_name": "v1.6", "html_url": "https://github.com/x/v1.6", "assets": [
        {"name": "videoscraper-windows.zip", "browser_download_url": api_falsa.base + "/zip"}]})
    api_falsa.rotas["/zip"] = lambda q: (200, b"PK" + b"x" * 300_000, {"Content-Type": "application/zip"})
    nova = atualizacao.ultima_versao(api=api_falsa.base)
    assert (nova.versao, nova.arquivo_nome) == ("v1.6", "videoscraper-windows.zip")
    passos = []
    arquivo = atualizacao.baixar(nova, tmp_path, ao_progresso=lambda f, t: passos.append((f, t)))
    assert arquivo.name == "videoscraper-windows-v1.6.zip" and arquivo.stat().st_size == 300_002
    assert passos[-1] == (300_002, 300_002) and not list(tmp_path.glob("*.part"))
    with pytest.raises(atualizacao.ErroAtualizacao, match="interrompido"):
        atualizacao.baixar(nova, tmp_path / "b", parar=lambda: True)
    assert not list((tmp_path / "b").glob("*"))                       # nada pela metade
    api_falsa.rotas[rota] = lambda q: (500, {})
    with pytest.raises(atualizacao.ErroAtualizacao, match="HTTP 500"):
        atualizacao.ultima_versao(api=api_falsa.base)


def test_script_de_instalacao_espera_fechar_e_troca_os_arquivos():
    from pathlib import Path
    texto = atualizacao.script_de_instalacao(Path(r"C:\Users\Ana\Downloads\v.zip"), Path(r"C:\Prog's\videoscraper"),
                                             4321, r"C:\Prog's\videoscraper\videoscraper.exe")
    assert "Wait-Process -Id 4321" in texto                            # espera o programa fechar
    assert "Expand-Archive" in texto and "robocopy" in texto
    assert "'C:\\Prog''s\\videoscraper'" in texto                     # aspas do PowerShell escapadas
    assert "Start-Process -FilePath 'C:\\Prog''s\\videoscraper\\videoscraper.exe'" in texto
    assert "(não reabre)" in atualizacao.script_de_instalacao(Path("a.zip"), Path("p"), 1, "")
