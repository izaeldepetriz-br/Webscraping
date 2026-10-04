from videoscraper.download import caminho_livre, nome_seguro
from videoscraper.extracao import (eh_resposta_de_midia, extrair_links_de_navegacao,
                                   extrair_links_do_html, extrair_por_seletor)

from conftest import ESTATICA, LISTA


def test_detecta_todos_os_tipos():
    urls = {l.url for l in extrair_links_do_html(ESTATICA, "http://h/")}
    assert urls == {
        "http://h/m/og.mp4", "https://cdn.x.com/ld.webm", "http://h/m/a.mp4", "http://h/b.m3u8",
        "https://www.youtube.com/embed/abc123", "http://h/m/c.mkv", "https://cdn.x.com/inline.mp4?t=1",
    }   # sem o banner e sem /app.ts (TypeScript, não vídeo)


def test_seletor_relativo_sem_duplicata_e_com_titulo():
    links = extrair_por_seletor(LISTA, "http://h/lista", "a.video-link")
    assert [(l.url, l.titulo) for l in links] == [
        ("http://h/m/um.mp4", "Filme: Ação/1?"), ("http://h/m/quebrado.mp4", "Quebrado")]


def test_links_de_navegacao_ignoram_videos_e_javascript():
    assert extrair_links_de_navegacao(ESTATICA, "http://h/") == ["http://h/sub"]


def test_resposta_de_midia():
    assert eh_resposta_de_midia("http://h/x", "application/vnd.apple.mpegurl")
    assert eh_resposta_de_midia("http://h/v.mp4?tk=1", None)
    assert not eh_resposta_de_midia("http://h/seg1.ts", "video/mp2t")   # pedaço, não o vídeo
    assert not eh_resposta_de_midia("http://h/app.js", "text/javascript")


def test_nomes_de_arquivo(tmp_path):
    assert nome_seguro("Filme: Ação/1?", "x") == "Filme Ação 1"
    assert nome_seguro("???", "padrao") == "padrao"
    (tmp_path / "a.mp4").write_bytes(b"")
    assert caminho_livre(str(tmp_path), "a", ".mp4").endswith("a (2).mp4")
