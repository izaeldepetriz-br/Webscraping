"""O botão "Parar" vale na hora em todas as tarefas longas."""
import time

import pytest

from jellyfin_tools import CatalogoLocal, desfazer, organizar_pasta
from jellyfin_tools import organizador
from jellyfin_tools.organizador import mover_com_progresso, ultimo_log
from videoscraper import archive_org
from videoscraper.rede import ClienteHTTP


def _contador(depois_de: int):
    chamadas = [0]

    def parar():
        chamadas[0] += 1
        return chamadas[0] > depois_de
    return parar


def test_previa_para_no_meio_e_devolve_o_que_analisou(tmp_path):
    for n in range(50):
        (tmp_path / f"Filme Numero {n} ({1950 + n}).mkv").write_bytes(b"v")
    movs = organizar_pasta(tmp_path, tmp_path / "Filmes", CatalogoLocal.padrao(), parar=_contador(10))
    assert 0 < len(movs) < 50


def test_organizar_para_depois_do_arquivo_atual_e_da_para_desfazer(tmp_path):
    origem = tmp_path / "Downloads"
    origem.mkdir()
    for n in range(5):
        (origem / f"Filme Numero {n} ({1990 + n}).mkv").write_bytes(b"v")
    apertou = []                                                        # "Parar" logo depois do 1º arquivo
    movs = organizar_pasta(origem, tmp_path / "Filmes", CatalogoLocal.padrao(), aplicar=True,
                           ao_progresso=lambda i, m, f: f >= 1.0 and apertou.append(True), parar=lambda: bool(apertou))
    movidos = [m for m in movs if m.status == "movido"]
    assert 0 < len(movidos) < 5
    desfazer(ultimo_log(tmp_path / "Filmes"))                          # o que moveu volta normalmente
    assert len(list(origem.glob("*.mkv"))) == 5


def test_copia_grande_entre_discos_para_no_meio_sem_deixar_pedaco(tmp_path, monkeypatch):
    monkeypatch.setattr(organizador, "_mesmo_disco", lambda a, b: False)
    monkeypatch.setattr(organizador, "BLOCO_COPIA", 1024)
    de, para = tmp_path / "grande.mkv", tmp_path / "destino" / "grande.mkv"
    de.write_bytes(b"x" * 20_000)
    para.parent.mkdir()
    with pytest.raises(InterruptedError):
        mover_com_progresso(de, para, parar=_contador(3))
    assert de.stat().st_size == 20_000 and not para.exists() and not list(para.parent.glob("*.part"))


def test_pausa_entre_pedidos_para_na_hora():
    cliente = ClienteHTTP(espera=30)
    cliente._ultimo = time.monotonic()
    inicio = time.monotonic()
    cliente.parar = lambda: time.monotonic() - inicio > 0.3
    cliente.pausar()
    assert time.monotonic() - inicio < 1.5                              # não esperou os 30 s


def test_busca_do_archive_org_para_ao_listar_as_paginas(api_falsa):
    cliente = ClienteHTTP(espera=0, respeitar_robots=False)
    links = archive_org.buscar(cliente, api_falsa.base + "/search?query=filmes", limite=1000, parar=lambda: True)
    assert links == [] and not any("advancedsearch" in p["caminho"] for p in api_falsa.pedidos)
