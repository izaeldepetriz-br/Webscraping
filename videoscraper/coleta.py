"""Junta as peças: obtém páginas (requests OU navegador), navega entre elas e acha os vídeos."""

from __future__ import annotations

import sys
from collections import Counter, deque
from dataclasses import dataclass, field
from urllib.parse import urlparse

from .extracao import (LinkVideo, extrair_links_de_navegacao, extrair_links_do_html,
                       extrair_por_seletor)
from .rede import ClienteHTTP


@dataclass
class Pagina:
    url: str
    html: str | bytes
    frames: list[tuple[str, str]] = field(default_factory=list)   # iframes já renderizados
    midias: list[str] = field(default_factory=list)               # vídeos vistos na rede


class FonteRequests:
    """Rápida e leve: baixa só o HTML. Não executa JavaScript."""

    def __init__(self, cliente: ClienteHTTP):
        self.cliente = cliente
        self.bloqueadas: list[str] = []          # páginas que o robots.txt proibiu

    def obter(self, url: str) -> Pagina | None:
        if not self.cliente.permitido(url):
            print(f"  ⛔ robots.txt não permite: {url}", file=sys.stderr)
            self.bloqueadas.append(url)
            return None
        resultado = self.cliente.obter_html(url)
        return Pagina(url=resultado[1], html=resultado[0]) if resultado else None

    def sincronizar_cookies(self) -> None:
        pass

    def fechar(self) -> None:
        pass


class FonteNavegador:
    """Mais lenta, mas vê a página como você vê: com JavaScript, login e iframes."""

    def __init__(self, cliente: ClienteHTTP, navegador):
        self.cliente = cliente
        self.navegador = navegador
        self.bloqueadas: list[str] = []
        self.navegador.abrir()

    def obter(self, url: str) -> Pagina | None:
        if not self.cliente.permitido(url):
            print(f"  ⛔ robots.txt não permite: {url}", file=sys.stderr)
            self.bloqueadas.append(url)
            return None
        self.cliente.pausar()
        try:
            html, url_final, frames, midias = self.navegador.renderizar(url)
        except Exception as erro:
            print(f"  ❌ navegador falhou em {url}: {erro}", file=sys.stderr)
            return None
        return Pagina(url_final, html, frames, midias)

    def sincronizar_cookies(self) -> None:
        """Downloads usam requests; passamos a ele os cookies do navegador (ex.: login)."""
        self.cliente.importar_cookies(self.navegador.cookies())

    def fechar(self) -> None:
        self.navegador.fechar()


def links_da_pagina(pagina: Pagina, seletor: str | None = None) -> list[LinkVideo]:
    """Todos os links de vídeo de uma página (incluindo iframes e o que passou pela rede)."""
    partes = [(pagina.url, pagina.html)] + list(pagina.frames)
    achados: dict[str, LinkVideo] = {}
    for url_base, html in partes:
        if seletor:
            novos = extrair_por_seletor(html, url_base, seletor)
        else:
            novos = extrair_links_do_html(html, url_base)
        for link in novos:
            achados.setdefault(link.url, link)
    if not seletor:
        for url in pagina.midias:
            achados.setdefault(url, LinkVideo(url, pagina.url, "rede"))
    return list(achados.values())


def _formato(url: str) -> str:
    """O "formato" do link, sem a parte que varia:
       'https://site/details/abc' -> 'site/details/*'   (resultados: muitos com o mesmo formato)
       'https://site/about'       -> 'site/about'       (menu: um nível só, cada um é único)"""
    p = urlparse(url)
    partes = [x for x in p.path.split("/") if x]
    if len(partes) >= 2:
        return p.netloc + "/" + "/".join(partes[:-1]) + "/*"
    return p.netloc + "/" + "/".join(partes)


def priorizar(links: list[str]) -> list[str]:
    """Resultados de busca/listas se repetem no MESMO formato (centenas de /details/...);
    links de menu são únicos (/about, /donate). Visita primeiro os formatos mais repetidos,
    para o limite de páginas não ser gasto com o menu do site."""
    contagem = Counter(_formato(u) for u in links)
    return sorted(links, key=lambda u: -contagem[_formato(u)])     # sorted é estável: mantém a ordem


def rastrear(fonte, url_inicial: str, profundidade: int = 0, max_paginas: int = 50,
             mesmo_dominio: bool = True, seletor: str | None = None,
             parar=None, filtro_links: str = "") -> list[LinkVideo]:
    """Busca em largura: a página inicial, depois as páginas que ela linka, e assim por diante.
    `parar` (opcional) é uma função que devolve True quando o usuário pediu para interromper.
    `filtro_links`: se preenchido, só segue links cujo endereço contém esse texto (ex.: "/details/")."""
    dominio = urlparse(url_inicial).netloc
    fila = deque([(url_inicial, 0)])
    visitadas: set[str] = set()
    resultados: dict[str, LinkVideo] = {}

    while fila and len(visitadas) < max_paginas:
        if parar and parar():
            print("⏹  Busca interrompida.", file=sys.stderr)
            break
        url, nivel = fila.popleft()
        if url in visitadas:
            continue
        visitadas.add(url)
        print(f"[{len(visitadas)}/{max_paginas}] nível {nivel}: {url}", file=sys.stderr)

        pagina = fonte.obter(url)
        if pagina is None:
            continue
        visitadas.add(pagina.url)                 # evita revisitar após redirecionamento

        for link in links_da_pagina(pagina, seletor):
            resultados.setdefault(link.url, link)

        if nivel < profundidade:
            proximos = []
            for prox in dict.fromkeys(extrair_links_de_navegacao(pagina.html, pagina.url)):
                if mesmo_dominio and urlparse(prox).netloc != dominio:
                    continue
                if filtro_links and filtro_links not in prox:
                    continue
                if prox not in visitadas:
                    proximos.append(prox)
            fila.extend((prox, nivel + 1) for prox in priorizar(proximos))

    return list(resultados.values())
