"""Testes com servidor HTTP local (sem internet). Rodar: python -m pytest -q"""
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import baixar_videos as bv

LISTA = """<a class="video-link" href="/v/um.mp4">Filme: Ação/1?</a>
<a class="video-link" href="/v/um.mp4">duplicado</a>
<a class="video-link" href="/v/quebrado.mp4">Quebrado</a>
<a class="outra" href="/v/x.mp4">ignorado</a>"""
VIDEO = b"\x00\x01fakevideo" * 1000


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/acao":
            corpo, tipo, cod = LISTA.encode(), "text/html", 200
        elif self.path == "/v/um.mp4":
            corpo, tipo, cod = VIDEO, "video/mp4", 200
        else:
            corpo, tipo, cod = b"nao", "text/plain", 404
        self.send_response(cod)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def log_message(self, *a):
        pass


def test_nome_seguro():
    assert bv.nome_seguro('Filme: Ação/1?', "x") == "Filme Ação 1"
    assert bv.nome_seguro("???", "padrao") == "padrao"


def test_extrair_videos_relativo_e_duplicado():
    v = bv.extrair_videos(LISTA, "http://h/acao", "a.video-link")
    assert [u for _, u in v] == ["http://h/v/um.mp4", "http://h/v/quebrado.mp4"]


def test_download_completo(tmp_path):
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        saida = tmp_path / "v"
        codigo = bv.main([f"http://127.0.0.1:{srv.server_port}/acao", "-p", str(saida), "-e", "0"])
        assert codigo == 2                                   # 1 falha (404)
        arquivos = list(saida.iterdir())
        assert [a.name for a in arquivos] == ["Filme Ação 1.mp4"]
        assert arquivos[0].read_bytes() == VIDEO             # sem sobra de .part
    finally:
        srv.shutdown()
