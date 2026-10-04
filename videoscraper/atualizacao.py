"""Aviso de versão nova: ao abrir, consulta a página Releases do GitHub (uma chamada, ~1 KB).

    versão deste programa: o .exe gerado pelo GitHub traz 'versao_build.txt' (ex.: v1.5); rodando pelo
    Python, vale o __version__ do pacote.
    versão mais nova: GET https://api.github.com/repos/<dono>/<repo>/releases/latest -> tag_name

Nada é baixado nem instalado sozinho: o programa só avisa e abre a página da versão nova.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

import requests

from . import __version__

REPOSITORIO = "izaeldepetriz-br/Webscraping"
API = "https://api.github.com"


def versao_atual() -> str:
    """A versão deste programa (a do .exe, gravada pelo GitHub ao gerar; senão a do código)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    for arquivo in (base / "videoscraper" / "versao_build.txt", Path(__file__).with_name("versao_build.txt")):
        try:
            texto = arquivo.read_text(encoding="utf-8").strip()
            if texto:
                return texto
        except OSError:
            continue
    return __version__


def numeros(versao: str) -> tuple[int, ...]:
    """'v1.10.2' -> (1, 10, 2): compara número por número (1.10 é mais nova que 1.9)."""
    return tuple(int(n) for n in re.findall(r"\d+", versao)[:4]) or (0,)


@dataclass
class VersaoNova:
    versao: str
    url: str
    notas: str = ""


def verificar(atual: str | None = None, api: str = API, repositorio: str = REPOSITORIO,
              timeout: float = 6) -> VersaoNova | None:
    """A versão mais nova publicada, se for mais nova que esta; None se não houver (ou sem internet)."""
    atual = atual or versao_atual()
    try:
        r = requests.get(f"{api.rstrip('/')}/repos/{repositorio}/releases/latest", timeout=timeout,
                         headers={"Accept": "application/vnd.github+json"})
        if not r.ok:
            return None
        dados = r.json()
    except (requests.RequestException, ValueError):
        return None
    tag = str(dados.get("tag_name") or "")
    if not tag or numeros(tag) <= numeros(atual):
        return None
    notas = str(dados.get("body") or "").strip()
    return VersaoNova(tag, str(dados.get("html_url") or f"https://github.com/{repositorio}/releases/latest"),
                      notas[:600])
