"""Site de legendas SIMULADO (roda no seu PC, sem internet), para demonstração e testes.

Estrutura (parecida com sites reais):
  /busca?q=matrix+1999  -> lista <li class="resultado" data-idioma="pt-BR"> com <a class="titulo">
  /legenda/<id>         -> página do item com <a class="download" href="/download/<id>">
  /download/<id>        -> o arquivo: .srt em UTF-8, .srt em Windows-1252 ou .zip com o .srt

Rodar sozinho:  python -m jellyfin_tools.site_demo   (abre em http://127.0.0.1:8765)
"""

from __future__ import annotations

import html
import io
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .nomes import normalizar


def _srt(titulo: str, idioma: str) -> str:
    falas = {"pt-BR": ("Olá! Esta é uma legenda de demonstração.", f"Filme: {titulo}. Ação, emoção e acentuação."),
             "en": ("Hello! This is a demo subtitle.", f"Movie: {titulo}.")}[idioma]
    return (f"1\n00:00:01,000 --> 00:00:04,000\n{falas[0]}\n\n"
            f"2\n00:00:05,000 --> 00:00:08,000\n{falas[1]}\n")


# id, título exibido, ano, idioma, downloads, formato
LEGENDAS = [
    (1, "Matrix (1999) BluRay 1080p", 1999, "pt-BR", 1520, "srt"),
    (2, "Matrix (1999) DVDRip", 1999, "pt-BR", 310, "srt"),
    (3, "Matrix (1999) BluRay", 1999, "en", 9000, "srt"),
    (4, "Matrix Resurrections (2021) WEB-DL", 2021, "pt-BR", 800, "srt"),
    (5, "Interstellar (2014) 1080p BluRay", 2014, "pt-BR", 2200, "zip"),
    (6, "O Poderoso Chefão (1972) Remastered", 1972, "pt-BR", 1800, "cp1252"),
    (7, "O Poderoso Chefão Parte II (1974)", 1974, "pt-BR", 900, "srt"),
    (8, "Dark S01E01 WEBRip", 2017, "pt-BR", 700, "srt"),
    (9, "Dark S01E02 WEBRip", 2017, "pt-BR", 650, "srt"),
    (10, "Dark S01E02 1080p", 2017, "en", 3000, "srt"),
    (11, "Breaking Bad S02E05 720p", 2008, "pt-BR", 1200, "zip"),
    (12, "Velhos Bandidos (2026) WEB-DL", 2026, "pt-BR", 430, "srt"),
]


def _arquivo(item) -> tuple[bytes, str, str]:
    _id, titulo, _ano, idioma, _d, formato = item
    texto = _srt(titulo, idioma)
    if formato == "zip":
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("LEIA-ME.txt", "legendas de demonstracao")
            z.writestr(f"{titulo}.srt", texto.encode("utf-8"))
        return buf.getvalue(), "application/zip", f"legenda{_id}.zip"
    codificacao = "cp1252" if formato == "cp1252" else "utf-8"
    return texto.encode(codificacao), "application/x-subrip", f"legenda{_id}.srt"


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        url = urlparse(self.path)
        partes = url.path.strip("/").split("/")
        if url.path == "/robots.txt":
            return self._enviar(200, "text/plain", b"User-agent: *\nDisallow: /admin\n")
        if url.path == "/busca":
            termos = normalizar(parse_qs(url.query).get("q", [""])[0]).split()
            achados = [i for i in LEGENDAS if termos and all(t in normalizar(i[1]) for t in termos)]
            itens = "".join(
                f'<li class="resultado" data-idioma="{i[3]}">'
                f'<a class="titulo" href="/legenda/{i[0]}">{html.escape(i[1])}</a> '
                f'<span class="downloads">{i[4]}</span> downloads</li>' for i in achados)
            pagina = f"<html><body><h1>Resultados</h1><ul>{itens}</ul></body></html>"
            return self._enviar(200, "text/html; charset=utf-8", pagina.encode())
        if len(partes) == 2 and partes[0] in ("legenda", "download") and partes[1].isdigit():
            item = next((i for i in LEGENDAS if i[0] == int(partes[1])), None)
            if item and partes[0] == "legenda":
                pagina = (f"<html><body><h1>{html.escape(item[1])}</h1>"
                          f'<a class="download" href="/download/{item[0]}">Baixar legenda</a></body></html>')
                return self._enviar(200, "text/html; charset=utf-8", pagina.encode())
            if item:
                corpo, tipo, nome = _arquivo(item)
                return self._enviar(200, tipo, corpo, {"Content-Disposition": f'attachment; filename="{nome}"'})
        self._enviar(404, "text/plain", b"nao encontrado")

    def _enviar(self, codigo, tipo, corpo, extra=None):
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(corpo)

    def log_message(self, *args):
        pass


def iniciar_site_demo(porta: int = 0) -> tuple[ThreadingHTTPServer, str]:
    """Liga o site em segundo plano. Devolve (servidor, url_base). Desligue com servidor.shutdown()."""
    servidor = ThreadingHTTPServer(("127.0.0.1", porta), _Handler)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    return servidor, f"http://127.0.0.1:{servidor.server_port}"


if __name__ == "__main__":
    srv, base = iniciar_site_demo(8765)
    print(f"Site de legendas de demonstração em {base}/busca?q=matrix  (Ctrl+C para sair)")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        srv.shutdown()
