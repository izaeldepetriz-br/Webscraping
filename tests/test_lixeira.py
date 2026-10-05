"""Lixeira do organizador (.organizador/removidos) e não identificados por pasta."""
from datetime import datetime
from pathlib import Path

from jellyfin_tools.lixeira import apagar_lotes, lotes_antigos, tamanho_legivel
from jellyfin_tools.organizador import Movimento, agrupar_nao_identificados


def test_lotes_antigos_pela_data_no_nome_e_sem_repetir(tmp_path):
    base = tmp_path / "Filmes" / ".organizador" / "removidos"
    for nome in ("20250101-101500-000001", "20250301-090000-000002", "20260920-120000-000003"):
        (base / nome).mkdir(parents=True)
        (base / nome / "a.mkv").write_bytes(b"x" * 1000)
    agora = datetime(2026, 10, 5)
    lotes = lotes_antigos([tmp_path / "Filmes", tmp_path / "Filmes", tmp_path / "nao_existe"], dias=30, agora=agora)
    assert [lote.pasta.name for lote in lotes] == ["20250101-101500-000001", "20250301-090000-000002"]
    assert all(lote.tamanho == 1000 for lote in lotes)
    assert apagar_lotes(lotes) == (2, [])
    assert [p.name for p in base.iterdir()] == ["20260920-120000-000003"]
    assert tamanho_legivel(3 * 1024 ** 3) == "3.0 GB" and tamanho_legivel(5 * 1024 ** 2) == "5 MB"


def test_agrupar_nao_identificados_por_pasta():
    def m(caminho, status="nao_identificado"):
        return Movimento(Path(caminho), None, status)
    movimentos = [m("/d/B/1.mkv"), m("/d/A/1.mkv"), m("/d/A/2.mkv"), m("/d/A/3.mkv", "simulado"), m("/d/A/4.mkv")]
    assert agrupar_nao_identificados(movimentos) == [(Path("/d/A"), [1, 2, 4]), (Path("/d/B"), [0])]
