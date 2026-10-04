"""Extração de links de vídeo a partir de HTML. Não acessa a internet."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib.parse import urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup

# Extensões de arquivos de vídeo e de "listas" de streaming (.m3u8 = HLS, .mpd = DASH).
# Obs.: ".ts" ficou de fora de propósito: também é extensão de arquivo TypeScript.
EXTENSOES_VIDEO = (".mp4", ".webm", ".mkv", ".mov", ".avi", ".m4v", ".ogv", ".m3u8", ".mpd")
EXTENSOES_STREAMING = (".m3u8", ".mpd")

# Players conhecidos que aparecem dentro de <iframe>.
HOSTS_EMBED = (
    "youtube.com", "youtube-nocookie.com", "youtu.be",
    "vimeo.com", "dailymotion.com", "twitch.tv",
    "facebook.com/plugins/video", "streamable.com", "wistia.com", "player.",
)

# Tipos de conteúdo (Content-Type) que indicam vídeo/streaming numa resposta de rede.
# Pedaços de streaming (video/mp2t, .m4s) são ignorados: interessa a lista, não os pedaços.
TIPOS_MIDIA = ("video/mp4", "video/webm", "video/quicktime", "video/x-matroska", "video/ogg",
               "application/vnd.apple.mpegurl", "application/x-mpegurl", "application/dash+xml")

_ext_regex = "|".join(re.escape(e.lstrip(".")) for e in EXTENSOES_VIDEO)
# Acha URLs de vídeo "soltas" em scripts. Aceita barras escapadas do JSON (https:\/\/...).
REGEX_URL_VIDEO = re.compile(
    rf"""https?:(?:\\?/){{2}}(?:[^\s"'<>\\]|\\/)+?\.(?:{_ext_regex})(?:\?[^\s"'<>\\]*)?""",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class LinkVideo:
    """Um link encontrado: o endereço, a página de origem e de onde ele veio."""
    url: str
    origem: str
    tipo: str      # video_tag, source_tag, iframe, link, meta, json_ld, script, rede, seletor
    titulo: str = ""


def parece_video(url: str) -> bool:
    """True se o caminho da URL termina com extensão de vídeo/streaming."""
    return urlparse(url).path.lower().endswith(EXTENSOES_VIDEO)


def eh_streaming(url: str) -> bool:
    """True para listas HLS/DASH (.m3u8/.mpd), que precisam do ffmpeg para virar um arquivo."""
    return urlparse(url).path.lower().endswith(EXTENSOES_STREAMING)


def eh_embed_de_video(url: str) -> bool:
    """True se a URL é de um player conhecido (YouTube, Vimeo...)."""
    baixa = url.lower()
    return any(h in baixa for h in HOSTS_EMBED)


def eh_resposta_de_midia(url: str, content_type: str | None) -> bool:
    """Usado no modo navegador: esta resposta de rede é um vídeo (ou lista de streaming)?"""
    tipo = (content_type or "").split(";")[0].strip().lower()
    return tipo in TIPOS_MIDIA or parece_video(url)


def normalizar(base: str, valor: str | None) -> str | None:
    """Link relativo -> absoluto. Descarta data:, javascript:, blob:, mailto: e âncoras."""
    if not valor:
        return None
    valor = valor.strip().replace("\\/", "/")
    if valor.startswith(("data:", "javascript:", "blob:", "mailto:", "#")):
        return None
    absoluta = urljoin(base, valor)
    if urlparse(absoluta).scheme not in ("http", "https"):
        return None
    return urldefrag(absoluta)[0]


def extrair_links_do_html(html: str | bytes, url_pagina: str) -> list[LinkVideo]:
    """Procura vídeos em <video>, <source>, <iframe>, <a>, meta og:video, JSON-LD e scripts."""
    sopa = BeautifulSoup(html, "lxml")
    texto = html if isinstance(html, str) else str(sopa)
    achados: dict[str, LinkVideo] = {}   # dict = sem duplicatas (a chave é a url)

    def adicionar(valor, tipo, titulo=""):
        url = normalizar(url_pagina, valor)
        if url and url not in achados:
            achados[url] = LinkVideo(url, url_pagina, tipo, titulo)

    for tag in sopa.find_all("video"):
        adicionar(tag.get("src"), "video_tag", tag.get("title") or "")
    for tag in sopa.find_all("source"):
        adicionar(tag.get("src"), "source_tag")

    for tag in sopa.find_all("iframe"):
        url = normalizar(url_pagina, tag.get("src") or tag.get("data-src"))
        if url and (eh_embed_de_video(url) or parece_video(url)):
            adicionar(url, "iframe", tag.get("title") or "")

    for tag in sopa.find_all("a", href=True):
        url = normalizar(url_pagina, tag["href"])
        if url and parece_video(url):
            adicionar(url, "link", tag.get_text(strip=True))

    for tag in sopa.find_all("meta"):
        chave = (tag.get("property") or tag.get("name") or "").lower()
        if chave in {"og:video", "og:video:url", "og:video:secure_url", "twitter:player:stream"}:
            adicionar(tag.get("content"), "meta")

    for tag in sopa.find_all("script", type="application/ld+json"):
        try:
            dados = json.loads(tag.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        for obj in _percorrer_json(dados):
            if str(obj.get("@type", "")).lower() == "videoobject":
                nome = str(obj.get("name") or "")
                adicionar(obj.get("contentUrl"), "json_ld", nome)
                adicionar(obj.get("embedUrl"), "json_ld", nome)

    for casamento in REGEX_URL_VIDEO.findall(texto):
        adicionar(casamento, "script")

    return list(achados.values())


def extrair_por_seletor(html: str | bytes, url_pagina: str, seletor: str) -> list[LinkVideo]:
    """Modo 'seletor CSS': pega o href (ou src) de cada elemento que casa com o seletor."""
    sopa = BeautifulSoup(html, "lxml")
    achados: dict[str, LinkVideo] = {}
    for tag in sopa.select(seletor):
        url = normalizar(url_pagina, tag.get("href") or tag.get("src"))
        if url and url not in achados:
            achados[url] = LinkVideo(url, url_pagina, "seletor", tag.get_text(strip=True))
    return list(achados.values())


def extrair_links_de_navegacao(html: str | bytes, url_pagina: str) -> list[str]:
    """Links <a> para OUTRAS páginas (usados para navegar quando profundidade > 0)."""
    sopa = BeautifulSoup(html, "lxml")
    urls = []
    for tag in sopa.find_all("a", href=True):
        url = normalizar(url_pagina, tag["href"])
        if url and not parece_video(url):
            urls.append(url)
    return urls


def _percorrer_json(no):
    """Gera todos os dicionários de uma estrutura JSON aninhada."""
    if isinstance(no, dict):
        yield no
        for v in no.values():
            yield from _percorrer_json(v)
    elif isinstance(no, list):
        for item in no:
            yield from _percorrer_json(item)
