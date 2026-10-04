"""archive.org pela API OFICIAL (em vez de raspar a página).

Por quê: a página de uma coleção mostra os itens aos poucos (rolagem infinita) e cheia de links de
menu; a API devolve TODOS os itens de uma vez e, para cada um, a lista exata de arquivos.

  1. advancedsearch.php -> identificadores dos itens (coleção, busca ou um item só)
  2. /metadata/<item>   -> arquivos do item; escolhemos o melhor arquivo de vídeo
  3. o link final é https://archive.org/download/<item>/<arquivo>

Confira a licença de cada item (muitas coleções são de domínio público; nem todas).
"""

from __future__ import annotations

import re
import sys
from urllib.parse import parse_qs, quote, urlparse

from .extracao import LinkVideo
from .rede import ClienteHTTP

HOSTS = ("archive.org", "www.archive.org")
EXTENSOES = (".mp4", ".mkv", ".avi", ".mov", ".m4v", ".mpeg", ".mpg", ".ogv", ".webm")
POR_PAGINA = 500                 # itens por consulta (menos pedidos em buscas grandes)


def reconhece(url: str) -> bool:
    """Links de coleção (/details/X), item (/details/X) ou busca (/search?query=...) do archive.org."""
    p = urlparse(url)
    return p.netloc.lower() in HOSTS and (p.path.startswith("/details/") or p.path.startswith("/search"))


def _base(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"


def melhor_arquivo(arquivos: list[dict]) -> dict | None:
    """O original (melhor qualidade) se for vídeo; senão o maior derivado .mp4."""
    videos = [a for a in arquivos if str(a.get("name", "")).lower().endswith(EXTENSOES)]
    if not videos:
        return None
    originais = [a for a in videos if a.get("source") == "original"]
    candidatos = originais or [a for a in videos if a["name"].lower().endswith(".mp4")] or videos

    def tamanho(a):
        try:
            return int(a.get("size") or 0)
        except ValueError:
            return 0
    return max(candidatos, key=tamanho)


def _json(cliente: ClienteHTTP, url: str, params: dict | None = None) -> dict | None:
    if not cliente.permitido(url):
        print(f"  ⛔ robots.txt não permite: {url}", file=sys.stderr)
        return None
    cliente.pausar()
    try:
        r = cliente.sessao.get(url, params=params, timeout=cliente.timeout)
        r.raise_for_status()
        return r.json()
    except Exception as erro:                      # rede, HTTP de erro ou JSON inválido
        print(f"  ❌ archive.org: {erro}", file=sys.stderr)
        return None


def _consulta(cliente: ClienteHTTP, url: str) -> tuple[str | None, dict | None]:
    """Devolve (consulta para o advancedsearch, metadados se a URL for de um item só)."""
    p = urlparse(url)
    if p.path.startswith("/search"):
        termo = (parse_qs(p.query).get("query") or [""])[0].strip()
        return (f"({termo}) AND mediatype:movies" if termo else None), None
    identificador = p.path.split("/")[2] if len(p.path.split("/")) > 2 else ""
    if not identificador:
        return None, None
    meta = _json(cliente, f"{_base(url)}/metadata/{quote(identificador)}")
    if not meta:
        return None, None
    if (meta.get("metadata") or {}).get("mediatype") == "collection":
        return f'collection:"{identificador}" AND mediatype:movies', None
    return None, meta                                # é um item só


def licenca_legivel(url_licenca) -> str:
    """'http://creativecommons.org/licenses/by-sa/4.0/' -> 'CC BY-SA 4.0';
    '.../publicdomain/mark/1.0/' -> 'Domínio público'; vazio -> '' (o item não informa a licença)."""
    texto = str(url_licenca or "").strip().lower()
    if not texto:
        return ""
    if "publicdomain" in texto:
        return "Domínio público"
    if m := re.search(r"creativecommons\.org/licenses/([a-z-]+)/([\d.]+)", texto):
        return f"CC {m.group(1).upper()} {m.group(2)}"
    return "outra licença"


def _ano(metadata: dict) -> int | None:
    for chave in ("year", "date"):
        if m := re.match(r"\s*(1[89]\d\d|20\d\d)", str(metadata.get(chave) or "")):
            return int(m.group(1))
    return None


def _link_do_item(base: str, identificador: str, meta: dict, titulo: str = "") -> LinkVideo | None:
    arquivo = melhor_arquivo(meta.get("files") or [])
    if not arquivo:
        return None
    metadata = meta.get("metadata") or {}
    titulo = titulo or str(metadata.get("title") or identificador)
    return LinkVideo(url=f"{base}/download/{quote(identificador)}/{quote(arquivo['name'])}",
                     origem=f"{base}/details/{identificador}", tipo="archive.org", titulo=titulo,
                     licenca=licenca_legivel(metadata.get("licenseurl")), ano=_ano(metadata))


def buscar(cliente: ClienteHTTP, url: str, limite: int = 100, parar=None,
           bloqueadas: list | None = None) -> list[LinkVideo]:
    """Todos os vídeos (até `limite` itens) da coleção/busca/item apontado por `url`."""
    base = _base(url)
    consulta, meta_item = _consulta(cliente, url)
    if meta_item is not None:                        # link de um item só
        link = _link_do_item(base, urlparse(url).path.split("/")[2], meta_item)
        return [link] if link else []
    if not consulta:
        if bloqueadas is not None and not cliente.permitido(f"{base}/metadata/x"):
            bloqueadas.append(url)
        return []

    itens: list[tuple[str, str]] = []
    pagina = 1
    while len(itens) < limite:
        dados = _json(cliente, f"{base}/advancedsearch.php",
                      {"q": consulta, "fl[]": ["identifier", "title"], "rows": POR_PAGINA,
                       "page": pagina, "output": "json"})
        if dados is None:
            if bloqueadas is not None and not cliente.permitido(f"{base}/advancedsearch.php"):
                bloqueadas.append(url)
            break
        resposta = dados.get("response") or {}
        docs = resposta.get("docs") or []
        itens += [(d["identifier"], str(d.get("title") or d["identifier"])) for d in docs if d.get("identifier")]
        print(f"archive.org: {len(itens)} de {resposta.get('numFound', '?')} item(ns) listados", file=sys.stderr)
        if len(docs) < POR_PAGINA:
            break
        pagina += 1
    itens = itens[:limite]

    links = []
    for i, (identificador, titulo) in enumerate(itens, 1):
        if parar and parar():
            print("⏹  Busca interrompida.", file=sys.stderr)
            break
        print(f"[{i}/{len(itens)}] {titulo}", file=sys.stderr)
        meta = _json(cliente, f"{base}/metadata/{quote(identificador)}")
        link = _link_do_item(base, identificador, meta, titulo) if meta else None
        if link:
            links.append(link)
        else:
            print("   (sem arquivo de vídeo neste item)", file=sys.stderr)
    return links
