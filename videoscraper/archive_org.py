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
    """Links de coleção (/details/X), item (/details/X ou a lista de arquivos /download/X) ou busca
    (/search?query=...) do archive.org."""
    p = urlparse(url)
    return p.netloc.lower() in HOSTS and p.path.startswith(("/details/", "/download/", "/search"))


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
    if cliente.parar and cliente.parar():
        return None
    try:
        r = cliente.sessao.get(url, params=params, timeout=cliente.timeout)
        r.raise_for_status()
        return r.json()
    except Exception as erro:                      # rede, HTTP de erro ou JSON inválido
        print(f"  ❌ archive.org: {erro}", file=sys.stderr)
        return None


def _ordem_natural(texto: str):
    """'Episódio 1x02' antes de 'Episódio 1x10' (os números contam como números)."""
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", texto)]


def videos_do_item(arquivos: list[dict]) -> list[dict]:
    """TODOS os vídeos de um item (ex.: os episódios de uma série), um por nome: quando o mesmo episódio vem
    em mais de um arquivo (o .mkv original e o .mp4 que o archive.org gera), fica o original; empatando, o
    maior. Em ordem natural (1x02 antes de 1x10)."""
    def tamanho(a):
        try:
            return int(a.get("size") or 0)
        except ValueError:
            return 0
    grupos: dict[str, list[dict]] = {}
    for a in arquivos:
        nome = str(a.get("name", ""))
        if nome.lower().endswith(EXTENSOES) and "/" not in nome.strip("/"):   # sem miniaturas/subpastas
            grupos.setdefault(nome.rsplit(".", 1)[0].lower(), []).append(a)
    escolhidos = [max(g, key=lambda a: (a.get("source") == "original", tamanho(a))) for g in grupos.values()]
    return sorted(escolhidos, key=lambda a: _ordem_natural(a["name"]))


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
    if meta_item is not None:                        # link de um item só: TODOS os vídeos dele (ex.: episódios)
        identificador = urlparse(url).path.split("/")[2]
        videos = videos_do_item(meta_item.get("files") or [])
        if len(videos) <= 1:
            link = _link_do_item(base, identificador, meta_item)
            return [link] if link else []
        metadata = meta_item.get("metadata") or {}
        licenca, ano = licenca_legivel(metadata.get("licenseurl")), _ano(metadata)
        print(f"archive.org: {len(videos)} vídeo(s) no item {identificador}", file=sys.stderr)
        return [LinkVideo(url=f"{base}/download/{quote(identificador)}/{quote(a['name'])}",
                          origem=f"{base}/details/{identificador}", tipo="archive.org",
                          titulo=a["name"].rsplit(".", 1)[0], licenca=licenca, ano=ano)
                for a in videos[:limite]]
    if not consulta:
        if bloqueadas is not None and not cliente.permitido(f"{base}/metadata/x"):
            bloqueadas.append(url)
        return []

    itens: list[tuple[str, str]] = []
    pagina = 1
    while len(itens) < limite:
        if parar and parar():                        # "Parar" também na fase de listar as páginas
            print("⏹  Busca interrompida.", file=sys.stderr)
            return []
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
