"""Pasta vigiada: só o que terminou de baixar é organizado."""
import os
import time

from jellyfin_tools import CatalogoLocal, organizar_pasta
from jellyfin_tools.vigia import filtro_prontos, pronto

HORA = 3600


def _video(caminho, idade_s=0):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_bytes(b"v")
    antigo = time.time() - idade_s
    os.utime(caminho, (antigo, antigo))
    return caminho


def test_pronto_so_depois_de_parar_e_sem_download_em_andamento(tmp_path):
    parado = _video(tmp_path / "Matrix.1999" / "Matrix.1999.mkv", idade_s=HORA)
    assert pronto(parado, espera=120)
    novo = _video(tmp_path / "Dark" / "Dark.S01E01.mkv", idade_s=10)           # ainda sendo escrito
    assert not pronto(novo, espera=120)
    em_andamento = _video(tmp_path / "Creed" / "Creed.II.2018.mkv", idade_s=HORA)
    (tmp_path / "Creed" / "Creed.II.2018.parte2.mkv.!qB").write_bytes(b"x")     # outro arquivo ainda baixando
    assert not pronto(em_andamento, espera=120)


def test_organizar_so_os_prontos(tmp_path):
    origem = tmp_path / "Downloads"
    _video(origem / "Matrix.1999.mkv", idade_s=HORA)
    _video(origem / "Cidade.de.Deus.2002.mkv", idade_s=5)
    movs = organizar_pasta(origem, tmp_path / "Filmes", CatalogoLocal.padrao(), aplicar=True,
                           filtro=filtro_prontos(120))
    assert [m.origem.name for m in movs] == ["Matrix.1999.mkv"]
    assert (tmp_path / "Filmes" / "Matrix (1999)" / "Matrix (1999).mkv").exists()
    assert (origem / "Cidade.de.Deus.2002.mkv").exists()                        # ainda baixando: fica


def test_script_vigiar_uma_volta(tmp_path, monkeypatch):
    import organizar_jellyfin as script
    origem, filmes = tmp_path / "Downloads", tmp_path / "Filmes"
    _video(origem / "Matrix.1999.mkv", idade_s=HORA)
    _video(origem / "Cidade.de.Deus.2002.mkv", idade_s=5)
    for nome, valor in {"PASTA_ENTRADA": origem, "PASTA_FILMES": filmes, "PRONTO_APOS_MIN": "2",
                        "ARQUIVO_LOG": tmp_path / "log" / "j.log"}.items():
        monkeypatch.setenv(nome, str(valor))
    monkeypatch.setattr(script, "montar_catalogo", CatalogoLocal.padrao)
    monkeypatch.setattr(script, "pos_processar_lote", lambda itens, log, notificar=True: [])
    log = script.configurar_log(tmp_path / "log" / "j.log", no_terminal=False)
    pausas = []
    assert script.vigiar(log, ciclos=2, dormir=pausas.append) == 0
    assert (filmes / "Matrix (1999)" / "Matrix (1999).mkv").exists()
    assert (origem / "Cidade.de.Deus.2002.mkv").exists()
    assert pausas == [5 * 60]                                                   # VIGIAR_A_CADA_MIN, entre as voltas
    assert "terminaram de baixar" in (tmp_path / "log" / "j.log").read_text(encoding="utf-8")
