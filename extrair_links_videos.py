#!/usr/bin/env python3
"""
Extrator de links de vídeos PÚBLICOS.

O que ele faz:
  1. Baixa uma página web (e, opcionalmente, páginas linkadas por ela).
  2. Procura nela links de vídeo: <video>, <source>, <iframe> (YouTube/Vimeo...),
     <a href="...mp4">, meta tags (og:video), JSON-LD (VideoObject) e URLs
     soltas dentro de scripts (.mp4, .m3u8, .webm...).
  3. Salva o resultado em TXT, CSV ou JSON.

Boas práticas embutidas:
  - Respeita o robots.txt do site (pode desligar com --ignorar-robots,
    mas só faça isso em sites seus ou com autorização).
  - Espera um tempo entre requisições (--espera) para não sobrecarregar o servidor.
  - Não baixa os vídeos, só coleta os endereços.

Uso rápido:
  python extrair_links_videos.py https://exemplo.com/videos
  python extrair_links_videos.py https://exemplo.com --profundidade 2 --saida links.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from collections import deque
from dataclasses import asdict, dataclass
from urllib import robotparser
from urllib.parse import urldefrag, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Configurações
# ---------------------------------------------------------------------------

USER_AGENT = "ExtratorLinksVideos/1.0 (projeto educacional)"

# Extensões que identificam um arquivo de vídeo/streaming.
EXTENSOES_VIDEO = (".mp4", ".webm", ".mkv", ".mov", ".avi", ".m4v", ".ogv", ".m3u8", ".mpd", ".ts")

# Sites que hospedam vídeos e que costumam aparecer dentro de <iframe>.
HOSTS_EMBED = (
    "youtube.com", "youtube-nocookie.com", "youtu.be",
    "vimeo.com", "dailymotion.com", "twitch.tv",
    "facebook.com/plugins/video", "streamable.com", "wistia.com", "player.",
)

# Regex que encontra URLs de vídeo "soltas" em scripts/JSON dentro do HTML.
# Ex.: var src = "https://cdn.site.com/aula1.mp4?token=abc";
_ext_regex = "|".join(re.escape(e.lstrip(".")) for e in EXTENSOES_VIDEO)
REGEX_URL_VIDEO = re.compile(
    rf"""https?:(?:\\?/){{2}}(?:[^\s"'<>\\]|\\/)+?\.(?:{_ext_regex})(?:\?[^\s"'<>\\]*)?""",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class LinkVideo:
    """Um link encontrado, com a página de origem e o 'tipo' de onde veio."""
    url: str
    origem: str   # página onde foi encontrado
    tipo: str     # video_tag, source_tag, iframe, link, meta, json_ld, script


# ---------------------------------------------------------------------------
# Funções auxiliares
# ---------------------------------------------------------------------------

def parece_video(url: str) -> bool:
    """True se o caminho da URL termina com uma extensão de vídeo conhecida."""
    caminho = urlparse(url).path.lower()
    return caminho.endswith(EXTENSOES_VIDEO)


def eh_embed_de_video(url: str) -> bool:
    """True se a URL aponta para um player conhecido (YouTube, Vimeo...)."""
    baixa = url.lower()
    return any(h in baixa for h in HOSTS_EMBED)


def normalizar(base: str, valor: str | None) -> str | None:
    """Transforma um link relativo em absoluto e descarta lixo (data:, javascript:)."""
    if not valor:
        return None
    valor = valor.strip().replace("\\/", "/")
    if valor.startswith(("data:", "javascript:", "blob:", "mailto:", "#")):
        return None
    absoluta = urljoin(base, valor)
    if urlparse(absoluta).scheme not in ("http", "https"):
        return None
    return urldefrag(absoluta)[0]


# ---------------------------------------------------------------------------
# Extração de uma página
# ---------------------------------------------------------------------------

def extrair_links_do_html(html: str, url_pagina: str) -> list[LinkVideo]:
    """Recebe o HTML de UMA página e devolve os links de vídeo encontrados."""
    sopa = BeautifulSoup(html, "lxml")
    achados: dict[str, LinkVideo] = {}  # dict evita duplicatas (chave = url)

    def adicionar(valor: str | None, tipo: str) -> None:
        url = normalizar(url_pagina, valor)
        if url and url not in achados:
            achados[url] = LinkVideo(url=url, origem=url_pagina, tipo=tipo)

    # <video src="..."> e <video><source src="..."></video>
    for tag in sopa.find_all("video"):
        adicionar(tag.get("src"), "video_tag")
    for tag in sopa.find_all("source"):
        adicionar(tag.get("src"), "source_tag")

    # <iframe src="https://www.youtube.com/embed/ID">
    for tag in sopa.find_all("iframe"):
        src = tag.get("src") or tag.get("data-src")
        url = normalizar(url_pagina, src)
        if url and (eh_embed_de_video(url) or parece_video(url)):
            adicionar(url, "iframe")

    # <a href="aula.mp4">
    for tag in sopa.find_all("a", href=True):
        url = normalizar(url_pagina, tag["href"])
        if url and parece_video(url):
            adicionar(url, "link")

    # <meta property="og:video" content="...">
    for tag in sopa.find_all("meta"):
        chave = (tag.get("property") or tag.get("name") or "").lower()
        if chave in {"og:video", "og:video:url", "og:video:secure_url", "twitter:player:stream"}:
            adicionar(tag.get("content"), "meta")

    # JSON-LD: {"@type": "VideoObject", "contentUrl": "...", "embedUrl": "..."}
    for tag in sopa.find_all("script", type="application/ld+json"):
        try:
            dados = json.loads(tag.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        for obj in _percorrer_json(dados):
            if str(obj.get("@type", "")).lower() == "videoobject":
                adicionar(obj.get("contentUrl"), "json_ld")
                adicionar(obj.get("embedUrl"), "json_ld")

    # URLs soltas em qualquer texto do HTML (scripts inline, atributos data-*)
    for casamento in REGEX_URL_VIDEO.findall(html):
        adicionar(casamento, "script")

    return list(achados.values())


def _percorrer_json(no):
    """Gera todos os dicionários dentro de uma estrutura JSON aninhada."""
    if isinstance(no, dict):
        yield no
        for v in no.values():
            yield from _percorrer_json(v)
    elif isinstance(no, list):
        for item in no:
            yield from _percorrer_json(item)


def extrair_links_de_pagina(html: str, url_pagina: str) -> list[str]:
    """Links <a> da página, usados para navegar (crawl) quando profundidade > 0."""
    sopa = BeautifulSoup(html, "lxml")
    urls = []
    for tag in sopa.find_all("a", href=True):
        url = normalizar(url_pagina, tag["href"])
        if url and not parece_video(url):
            urls.append(url)
    return urls


# ---------------------------------------------------------------------------
# Rede: download educado
# ---------------------------------------------------------------------------

class Baixador:
    """Faz requisições HTTP com User-Agent, timeout, tentativas e robots.txt."""

    def __init__(self, espera: float = 1.0, timeout: float = 15.0,
                 tentativas: int = 3, respeitar_robots: bool = True):
        self.espera = espera
        self.timeout = timeout
        self.tentativas = tentativas
        self.respeitar_robots = respeitar_robots
        self.sessao = requests.Session()
        self.sessao.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"})
        self._robots: dict[str, robotparser.RobotFileParser | None] = {}
        self._ultimo_acesso = 0.0

    def permitido(self, url: str) -> bool:
        if not self.respeitar_robots:
            return True
        p = urlparse(url)
        raiz = f"{p.scheme}://{p.netloc}"
        if raiz not in self._robots:
            rp = robotparser.RobotFileParser()
            try:
                resp = self.sessao.get(f"{raiz}/robots.txt", timeout=self.timeout)
                if resp.status_code == 200:
                    rp.parse(resp.text.splitlines())
                    self._robots[raiz] = rp
                else:
                    self._robots[raiz] = None  # sem robots.txt = tudo liberado
            except requests.RequestException:
                self._robots[raiz] = None
        rp = self._robots[raiz]
        return True if rp is None else rp.can_fetch(USER_AGENT, url)

    def baixar(self, url: str) -> str | None:
        """Devolve o HTML ou None se falhar / não for HTML / robots proibir."""
        if not self.permitido(url):
            print(f"  [robots.txt bloqueou] {url}", file=sys.stderr)
            return None
        for tentativa in range(1, self.tentativas + 1):
            # Pausa para não sobrecarregar o servidor.
            sobra = self.espera - (time.monotonic() - self._ultimo_acesso)
            if sobra > 0:
                time.sleep(sobra)
            self._ultimo_acesso = time.monotonic()
            try:
                resp = self.sessao.get(url, timeout=self.timeout)
                if resp.status_code in (429, 500, 502, 503, 504):
                    raise requests.HTTPError(f"HTTP {resp.status_code}")
                resp.raise_for_status()
                if "html" not in resp.headers.get("Content-Type", "").lower():
                    return None
                resp.encoding = resp.encoding or resp.apparent_encoding
                return resp.text
            except requests.RequestException as erro:
                print(f"  [tentativa {tentativa}/{self.tentativas}] {url}: {erro}", file=sys.stderr)
                time.sleep(2 ** tentativa)  # espera 2s, 4s, 8s...
        return None


# ---------------------------------------------------------------------------
# Rastreamento (crawl) e saída
# ---------------------------------------------------------------------------

def rastrear(url_inicial: str, profundidade: int, max_paginas: int,
             mesmo_dominio: bool, baixador: Baixador) -> list[LinkVideo]:
    """Busca em largura: visita a página inicial e depois as páginas linkadas."""
    dominio = urlparse(url_inicial).netloc
    fila = deque([(url_inicial, 0)])
    visitadas: set[str] = set()
    resultados: dict[str, LinkVideo] = {}

    while fila and len(visitadas) < max_paginas:
        url, nivel = fila.popleft()
        if url in visitadas:
            continue
        visitadas.add(url)
        print(f"[{len(visitadas)}/{max_paginas}] nível {nivel}: {url}", file=sys.stderr)

        html = baixador.baixar(url)
        if html is None:
            continue

        for link in extrair_links_do_html(html, url):
            resultados.setdefault(link.url, link)

        if nivel < profundidade:
            for prox in extrair_links_de_pagina(html, url):
                if mesmo_dominio and urlparse(prox).netloc != dominio:
                    continue
                if prox not in visitadas:
                    fila.append((prox, nivel + 1))

    return list(resultados.values())


def salvar(links: list[LinkVideo], caminho: str) -> None:
    """Salva em .csv, .json ou .txt conforme a extensão do arquivo."""
    if caminho.lower().endswith(".json"):
        with open(caminho, "w", encoding="utf-8") as f:
            json.dump([asdict(l) for l in links], f, ensure_ascii=False, indent=2)
    elif caminho.lower().endswith(".csv"):
        with open(caminho, "w", encoding="utf-8", newline="") as f:
            escritor = csv.DictWriter(f, fieldnames=["url", "origem", "tipo"])
            escritor.writeheader()
            escritor.writerows(asdict(l) for l in links)
    else:
        with open(caminho, "w", encoding="utf-8") as f:
            f.write("\n".join(l.url for l in links) + ("\n" if links else ""))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Extrai links de vídeos públicos de páginas web.")
    ap.add_argument("url", help="URL inicial (ex.: https://exemplo.com/videos)")
    ap.add_argument("-p", "--profundidade", type=int, default=0,
                    help="quantos níveis de links seguir a partir da página inicial (padrão: 0)")
    ap.add_argument("-m", "--max-paginas", type=int, default=50, help="limite de páginas visitadas (padrão: 50)")
    ap.add_argument("--qualquer-dominio", action="store_true",
                    help="permite seguir links para outros domínios (padrão: só o mesmo domínio)")
    ap.add_argument("-e", "--espera", type=float, default=1.0, help="segundos entre requisições (padrão: 1.0)")
    ap.add_argument("-s", "--saida", help="arquivo de saída (.txt, .csv ou .json). Sem isso, imprime na tela")
    ap.add_argument("--ignorar-robots", action="store_true",
                    help="NÃO respeitar robots.txt (use só em sites seus/autorizados)")
    args = ap.parse_args(argv)

    if urlparse(args.url).scheme not in ("http", "https"):
        ap.error("a URL precisa começar com http:// ou https://")

    baixador = Baixador(espera=args.espera, respeitar_robots=not args.ignorar_robots)
    links = rastrear(args.url, args.profundidade, args.max_paginas,
                     not args.qualquer_dominio, baixador)

    print(f"\n{len(links)} link(s) de vídeo encontrado(s).", file=sys.stderr)
    if args.saida:
        salvar(links, args.saida)
        print(f"Salvo em {args.saida}", file=sys.stderr)
    else:
        for l in links:
            print(f"{l.url}\t[{l.tipo}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
