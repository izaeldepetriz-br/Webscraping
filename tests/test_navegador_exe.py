"""Modo navegador no programa empacotado (.exe): onde o Chromium é procurado e baixado."""
import os
import sys

import pytest

from videoscraper import navegador


@pytest.mark.skipif(sys.platform == "darwin", reason="no Mac a pasta fica em ~/Library/Caches")
def test_exe_procura_e_instala_o_chromium_na_mesma_pasta(monkeypatch, tmp_path):
    """No .exe (sys.frozen), o Playwright procurava o Chromium DENTRO da pasta do programa, mas o
    instalador baixava na pasta do usuário ("Executable doesn't exist"). Agora os dois usam a do usuário."""
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))      # Linux
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))        # Windows
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    _, ambiente = navegador.comando_instalar_chromium()       # o instalador...
    pasta = str(tmp_path / "ms-playwright")
    assert ambiente["PLAYWRIGHT_BROWSERS_PATH"] == pasta
    assert os.environ["PLAYWRIGHT_BROWSERS_PATH"] == pasta    # ... e quem abre o navegador: a mesma pasta


def test_pasta_escolhida_pelo_usuario_e_respeitada(monkeypatch, tmp_path):
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path / "meus"))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    navegador.fixar_pasta_dos_navegadores()
    assert os.environ["PLAYWRIGHT_BROWSERS_PATH"] == str(tmp_path / "meus")


def test_fora_do_exe_nao_mexe_na_pasta_do_playwright(monkeypatch):
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    monkeypatch.delattr(sys, "frozen", raising=False)
    navegador.fixar_pasta_dos_navegadores()
    assert "PLAYWRIGHT_BROWSERS_PATH" not in os.environ
