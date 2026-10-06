"""Memória dos vídeos já baixados (aba Vídeos): guarda, reconhece em outra busca, esquece e limpa por período."""
from datetime import datetime, timedelta

from videoscraper.extracao import LinkVideo
from videoscraper.memoria_downloads import MemoriaDownloads, texto_quando


def _link(n, pagina="https://archive.org/details/serie", titulo=None):
    return LinkVideo(f"https://archive.org/download/serie/ep{n}.mkv", pagina, "archive.org",
                     titulo if titulo is not None else f"Episódio {n}")


def test_guarda_e_reconhece_em_outra_sessao(tmp_path):
    arquivo = tmp_path / "baixados.json"
    memoria = MemoriaDownloads(arquivo)
    assert memoria.baixado(_link(1)) is None and len(memoria) == 0
    memoria.registrar(_link(1), "C:/videos/ep1.mkv", quando=datetime(2026, 10, 5, 22, 0))
    outra = MemoriaDownloads(arquivo)                                   # programa aberto de novo
    registro = outra.baixado(_link(1))
    assert registro["arquivo"] == "C:/videos/ep1.mkv" and texto_quando(registro) == "05/10/2026"
    assert outra.baixado(_link(2)) is None
    # site que muda o link a cada visita (?token=): vale a página de origem + o título
    com_token = LinkVideo("https://cdn.site/x.mp4?token=novo", "https://archive.org/details/serie", "link", "Episódio 1")
    assert outra.baixado(com_token) is not None
    sem_titulo = LinkVideo("https://cdn.site/y.mp4?token=1", "https://archive.org/details/serie", "link", "")
    assert outra.baixado(sem_titulo) is None                           # sem título: só o link vale
    assert outra.baixado(LinkVideo(_link(1).url + "#t=10", "", "link")) is not None   # #âncora não conta


def test_esquecer_e_limpar_por_periodo(tmp_path):
    memoria = MemoriaDownloads(tmp_path / "baixados.json")
    agora = datetime(2026, 10, 6, 12, 0)
    for n, dias in ((1, 400), (2, 100), (3, 40), (4, 5)):
        memoria.registrar(_link(n), quando=agora - timedelta(days=dias))
    assert [memoria.quantos_antigos(d, agora) for d in (30, 90, 365, 0)] == [3, 2, 1, 4]
    assert memoria.esquecer([_link(4)]) == 1 and memoria.baixado(_link(4)) is None
    assert memoria.esquecer_antigos(90, agora) == 2                       # os de 400 e 100 dias
    assert [n for n in (1, 2, 3) if memoria.baixado(_link(n))] == [3]
    assert MemoriaDownloads(tmp_path / "baixados.json").baixado(_link(3)) is not None   # gravou
    assert memoria.esquecer_antigos(0, agora) == 1 and len(memoria) == 0
    assert memoria.tamanho() > 0


def test_arquivo_estragado_nao_derruba(tmp_path):
    arquivo = tmp_path / "baixados.json"
    arquivo.write_text("{nao é json", encoding="utf-8")
    memoria = MemoriaDownloads(arquivo)
    assert memoria.baixado(_link(1)) is None
    memoria.registrar(_link(1))
    assert MemoriaDownloads(arquivo).baixado(_link(1)) is not None
