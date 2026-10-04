"""Servidor HTTP local de mentira (sem internet) usado por todos os testes."""

import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Chromium pré-instalado em alguns ambientes (ex.: CI); no seu PC o Playwright usa o dele.
if not os.environ.get("VIDEOSCRAPER_CHROME") and Path("/opt/pw-browsers/chromium").exists():
    os.environ["VIDEOSCRAPER_CHROME"] = "/opt/pw-browsers/chromium"

# Os testes não consultam o GitHub ao abrir a janela (o aviso de versão nova é testado à parte).
os.environ.setdefault("VIDEOSCRAPER_SEM_ATUALIZACAO", "1")

VIDEO = b"\x00\x00\x00\x18ftypmp42" + b"x" * 5000

ESTATICA = """<html><head>
<meta property="og:video" content="/m/og.mp4">
<script type="application/ld+json">{"@type":"VideoObject","name":"LD","contentUrl":"https://cdn.x.com/ld.webm"}</script>
</head><body>
<video src="/m/a.mp4"></video>
<video><source src="b.m3u8"></video>
<iframe src="https://www.youtube.com/embed/abc123"></iframe>
<iframe src="https://anuncio.com/banner"></iframe>
<a href="/m/c.mkv">baixar</a><a href="/sub">outra página</a><a href="javascript:void(0)">x</a>
<script src="/app.ts"></script>
<script>var u = "https:\\/\\/cdn.x.com\\/inline.mp4?t=1";</script>
</body></html>"""

SUB = '<html><body><video src="/m/sub.mp4"></video></body></html>'

LISTA = """<html><body>
<a class="video-link" href="/m/um.mp4">Filme: Ação/1?</a>
<a class="video-link" href="/m/um.mp4">duplicado</a>
<a class="video-link" href="/m/quebrado.mp4">Quebrado</a>
<a class="outra" href="/m/x.mp4">ignorado</a></body></html>"""

# A lista só existe depois que o JavaScript roda: o HTML 'cru' não tem nenhum vídeo.
COM_JS = """<html><body><div id="lista"></div>
<script>
fetch('/api/lista.json').then(r => r.json()).then(d => {
  for (const v of d.videos) {
    const a = document.createElement('a');
    a.className = 'video-link'; a.href = v.url; a.textContent = v.titulo;
    document.getElementById('lista').appendChild(a);
  }
  fetch(d.stream);   // simula o player pedindo a lista HLS
});
</script></body></html>"""

LISTA_JSON = '{"videos":[{"titulo":"Aula JS","url":"/m/js.mp4"}],"stream":"/hls/master.m3u8"}'

# Busca feita com Web Components: os resultados ficam DENTRO de shadow DOMs (como no archive.org).
BUSCA_SHADOW = """<html><body><app-busca></app-busca>
<script>
customElements.define('cartao-item', class extends HTMLElement {
  connectedCallback() {
    this.attachShadow({mode: 'open'}).innerHTML =
      `<a href="/item/${this.getAttribute('id-item')}">${this.getAttribute('titulo')}</a>`;
  }
});
customElements.define('app-busca', class extends HTMLElement {
  connectedCallback() {
    this.attachShadow({mode: 'open'}).innerHTML =
      '<cartao-item id-item="1" titulo="Filme Livre"></cartao-item>' +
      '<cartao-item id-item="2" titulo="Documentario Livre"></cartao-item>';
  }
});
</script></body></html>"""

# Página de um item: o vídeo vem na meta og:video (como nas páginas /details/ do archive.org).
def ITEM(n):
    return f'<html><head><meta property="og:video" content="/m/item{n}.mp4"></head><body>item</body></html>'

# Página com MENU (links únicos) antes dos resultados (links no mesmo formato), como no archive.org.
MENU_E_RESULTADOS = ("<html><body><nav>" + "".join(f'<a href="/menu{i}">Menu {i}</a>' for i in range(20))
                     + "</nav><main>" + "".join(f'<a href="/item/{i}">Item {i}</a>' for i in range(1, 9))
                     + "</main></body></html>")

AREA_LOGADA = '<html><body><a class="video-link" href="/privado/v.mp4">Exclusivo</a></body></html>'


def _gerar_hls(pasta: Path):
    try:
        import imageio_ffmpeg
        ff = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return False
    r = subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-y",
                        "-f", "lavfi", "-i", "testsrc=duration=2:size=160x120:rate=10",
                        "-f", "lavfi", "-i", "sine=duration=2", "-c:v", "libx264", "-c:a", "aac",
                        "-f", "hls", "-hls_time", "1", "-hls_playlist_type", "vod",
                        str(pasta / "master.m3u8")], capture_output=True)
    return r.returncode == 0


@pytest.fixture(scope="session")
def servidor(tmp_path_factory):
    hls = tmp_path_factory.mktemp("hls")
    tem_hls = _gerar_hls(hls)

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            caminho = self.path.split("?")[0]
            logado = "sessao=ok" in (self.headers.get("Cookie") or "")
            extra = []
            if caminho == "/robots.txt":
                r = (200, "text/plain", b"User-agent: *\nDisallow: /proibido\n")
            elif caminho in ("/", "/estatica"):
                r = (200, "text/html", ESTATICA.encode())
            elif caminho == "/sub":
                r = (200, "text/html", SUB.encode())
            elif caminho == "/lista":
                r = (200, "text/html", LISTA.encode())        # sem charset de propósito
            elif caminho == "/js":
                r = (200, "text/html; charset=utf-8", COM_JS.encode())
            elif caminho == "/api/lista.json":
                r = (200, "application/json", LISTA_JSON.encode())
            elif caminho == "/busca-shadow":
                r = (200, "text/html; charset=utf-8", BUSCA_SHADOW.encode())
            elif caminho == "/menu-e-resultados":
                r = (200, "text/html", MENU_E_RESULTADOS.encode())
            elif caminho.startswith("/menu"):
                r = (200, "text/html", b"<html><body>pagina de menu</body></html>")
            elif caminho.startswith("/item/"):
                r = (200, "text/html", ITEM(caminho.rsplit("/", 1)[1]).encode())
            elif caminho == "/login-cookie":
                r = (200, "text/html", b"<html><body>logado!</body></html>")
                extra.append(("Set-Cookie", "sessao=ok; Path=/"))
            elif caminho == "/area-logada":
                r = (200, "text/html", AREA_LOGADA.encode() if logado else b"<p>entre</p>")
            elif caminho == "/privado/v.mp4":
                r = (200, "video/mp4", VIDEO) if logado else (200, "text/html", b"<p>login</p>")
            elif caminho.startswith("/m/") and "quebrado" not in caminho:
                r = (200, "video/mp4", VIDEO)
            elif caminho.startswith("/hls/") and tem_hls and (hls / caminho[5:]).exists():
                tipo = "application/vnd.apple.mpegurl" if caminho.endswith(".m3u8") else "video/mp2t"
                r = (200, tipo, (hls / caminho[5:]).read_bytes())
            else:
                r = (404, "text/plain", b"nao achei")
            self.send_response(r[0])
            self.send_header("Content-Type", r[1])
            self.send_header("Content-Length", str(len(r[2])))
            for k, v in extra:
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(r[2])

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    srv.base = f"http://127.0.0.1:{srv.server_port}"
    srv.tem_hls = tem_hls
    yield srv
    srv.shutdown()


@pytest.fixture
def api_falsa():
    """API JSON falsa: defina api_falsa.rotas['/caminho'] = lambda query: (status, dict_ou_bytes[, cabeçalhos]).
    Cada pedido fica registrado em api_falsa.pedidos (caminho, query, headers, corpo)."""
    import json as _json
    from urllib.parse import parse_qs, urlparse

    rotas, pedidos = {}, []

    class H(BaseHTTPRequestHandler):
        def _responder(self, corpo_pedido=b""):
            url = urlparse(self.path)
            query = parse_qs(url.query)
            pedidos.append({"metodo": self.command, "caminho": url.path, "query": query,
                            "headers": dict(self.headers), "corpo": corpo_pedido})
            rota = rotas.get(url.path)
            resposta = rota(query) if rota else (404, {"erro": "rota inexistente"})
            status, corpo = resposta[:2]
            extras = dict(resposta[2]) if len(resposta) > 2 else {}        # cabeçalhos opcionais
            if isinstance(corpo, (dict, list)):
                dados, tipo = _json.dumps(corpo).encode(), "application/json"
            else:
                dados, tipo = corpo, "application/octet-stream"
            self.send_response(status)
            self.send_header("Content-Type", extras.pop("Content-Type", tipo))
            for nome, valor in extras.items():
                self.send_header(nome, valor)
            self.send_header("Content-Length", str(len(dados)))
            self.end_headers()
            self.wfile.write(dados)

        def do_GET(self):
            self._responder()

        def do_POST(self):
            tamanho = int(self.headers.get("Content-Length", 0))
            self._responder(self.rfile.read(tamanho))

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    srv.base = f"http://127.0.0.1:{srv.server_port}"
    srv.rotas, srv.pedidos = rotas, pedidos
    yield srv
    srv.shutdown()


@pytest.fixture
def site_legendas():
    from jellyfin_tools.site_demo import iniciar_site_demo
    srv, base = iniciar_site_demo()
    srv.base = base
    yield srv
    srv.shutdown()


@pytest.fixture(autouse=True)
def _cache_tmdb_limpo():
    """O CatalogoTMDB guarda as respostas entre execuções: cada teste começa do zero."""
    from jellyfin_tools.catalogo import CatalogoTMDB
    CatalogoTMDB.limpar_cache()
    yield
    CatalogoTMDB.limpar_cache()
