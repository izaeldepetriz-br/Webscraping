"""Exportar e importar as configurações (levar o Maestro para outro computador)."""
import json
import zipfile

import pytest

from videoscraper import config


@pytest.fixture
def pasta(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ARQUIVO", tmp_path / "cfg" / "config.json")
    config.salvar({"jellyfin": {"origem": "D:/Downloads", "chave_tmdb": "segredo-tmdb"}, "tv": {"pasta": "E:/TV"}})
    (tmp_path / "cfg" / "canais.json").write_text('[{"nome": "TV Brasil", "url": "http://x/1.m3u8"}]', encoding="utf-8")
    return tmp_path


def test_exportar_sem_e_com_as_chaves(pasta):
    nomes = config.exportar(pasta / "sem.zip", segredos=("chave_tmdb",))
    assert nomes == ["config.json", "canais.json"]
    with zipfile.ZipFile(pasta / "sem.zip") as z:
        dados = json.loads(z.read("config.json"))
    assert "chave_tmdb" not in dados["jellyfin"] and dados["jellyfin"]["origem"] == "D:/Downloads"
    config.exportar(pasta / "com.zip", segredos=("chave_tmdb",), incluir_chaves=True)
    with zipfile.ZipFile(pasta / "com.zip") as z:
        assert json.loads(z.read("config.json"))["jellyfin"]["chave_tmdb"] == "segredo-tmdb"


def test_importar_troca_e_guarda_copia_das_antigas(pasta):
    with zipfile.ZipFile(pasta / "outro.zip", "w") as z:
        z.writestr("config.json", json.dumps({"jellyfin": {"origem": "F:/Torrents"}}))
        z.writestr("regras_nomes.json", "[]")
        z.writestr("../../fora.txt", "nunca deve sair do zip")                  # ignorado (só nomes conhecidos)
    nomes, copia = config.importar(pasta / "outro.zip")
    assert sorted(nomes) == ["config.json", "regras_nomes.json"] and not (pasta / "fora.txt").exists()
    assert config.carregar()["jellyfin"]["origem"] == "F:/Torrents"
    assert (pasta / "cfg" / "canais.json").exists()                              # o que não veio no zip fica
    with zipfile.ZipFile(copia) as z:
        assert json.loads(z.read("config.json"))["jellyfin"]["origem"] == "D:/Downloads"
    with zipfile.ZipFile(pasta / "ruim.zip", "w") as z:
        z.writestr("qualquer.txt", "x")
    with pytest.raises(ValueError, match="não é uma exportação do Maestro"):
        config.importar(pasta / "ruim.zip")
