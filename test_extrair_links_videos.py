"""Testes: sobem um servidor HTTP local de mentira, sem depender da internet.
Rodar:  python -m pytest -q   (ou: python test_extrair_links_videos.py)
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import extrair_links_videos as ev

PAGINA = """<html><head>
<meta property="og:video" content="/media/og.mp4">
<script type="application/ld+json">{"@type":"VideoObject","contentUrl":"https://cdn.x.com/ld.webm"}</script>
</head><body>
<video src="/media/a.mp4"></video>
<video><source src="b.m3u8"></video>
<iframe src="https://www.youtube.com/embed/abc123"></iframe>
<iframe src="https://anuncio.com/banner"></iframe>
<a href="/media/c.mkv">baixar</a><a href="/sub">outra página</a><a href="javascript:void(0)">x</a>
<script>var u = "https:\\/\\/cdn.x.com\\/inline.mp4?t=1";</script>
</body></html>"""

SUB = '<html><body><video src="/media/sub.mp4"></video></body></html>'


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        corpo, tipo = {
            "/": (PAGINA, "text/html"),
            "/sub": (SUB, "text/html"),
            "/robots.txt": ("User-agent: *\nDisallow: /privado\n", "text/plain"),
        }.get(self.path, ("nao achei", "text/plain"))
        self.send_response(200 if self.path in ("/", "/sub", "/robots.txt") else 404)
        self.send_header("Content-Type", tipo)
        self.end_headers()
        self.wfile.write(corpo.encode())

    def log_message(self, *a):
        pass


def _servidor():
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_port}"


def test_extracao_html():
    urls = {l.url for l in ev.extrair_links_do_html(PAGINA, "http://h/")}
    assert urls == {
        "http://h/media/og.mp4", "https://cdn.x.com/ld.webm", "http://h/media/a.mp4",
        "http://h/b.m3u8", "https://www.youtube.com/embed/abc123", "http://h/media/c.mkv",
        "https://cdn.x.com/inline.mp4?t=1",
    }


def test_rastreamento_e_saida(tmp_path):
    srv, base = _servidor()
    try:
        b = ev.Baixador(espera=0)
        assert len(ev.rastrear(base + "/", 0, 10, True, b)) == 7
        links = ev.rastrear(base + "/", 1, 10, True, b)
        assert any(l.url.endswith("/media/sub.mp4") for l in links)
        for nome in ("l.txt", "l.csv", "l.json"):
            ev.salvar(links, str(tmp_path / nome))
        assert len(json.loads((tmp_path / "l.json").read_text())) == len(links)
    finally:
        srv.shutdown()


def test_robots_bloqueia():
    srv, base = _servidor()
    try:
        assert not ev.Baixador(espera=0).permitido(base + "/privado/x")
        assert ev.Baixador(espera=0).permitido(base + "/")
    finally:
        srv.shutdown()


if __name__ == "__main__":
    import pytest, sys
    sys.exit(pytest.main([__file__, "-q"]))
