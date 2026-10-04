"""Melhoria 1: avisa o servidor Jellyfin para escanear a biblioteca (POST /Library/Refresh).

A chave de API se cria em: Painel do Jellyfin -> Avançado -> Chaves de API -> "+".
JELLYFIN_URL é o endereço que você abre no navegador, ex.: http://localhost:8096
"""

from __future__ import annotations

import requests

from .registro import obter_logger

log = obter_logger()


class ErroJellyfin(Exception):
    pass


def _cabecalhos(api_key: str) -> dict:
    # Formato atual do Jellyfin ("MediaBrowser Token=") + o antigo (X-Emby-Token), para versões mais velhas.
    return {"Authorization": f'MediaBrowser Token="{api_key}", Client="jellyfin-tools", Version="1.0"',
            "X-Emby-Token": api_key}


def atualizar_biblioteca(jellyfin_url: str, api_key: str, timeout: float = 20,
                         sessao: requests.Session | None = None) -> None:
    """Dispara o scan das bibliotecas. Lança ErroJellyfin com uma explicação se não der."""
    if not jellyfin_url or not api_key:
        raise ErroJellyfin("JELLYFIN_URL e JELLYFIN_API_KEY precisam estar preenchidos")
    url = jellyfin_url.rstrip("/") + "/Library/Refresh"
    try:
        r = (sessao or requests).post(url, headers=_cabecalhos(api_key), timeout=timeout)
    except requests.RequestException as erro:
        raise ErroJellyfin(f"não consegui falar com o Jellyfin em {jellyfin_url}: {erro}") from erro
    if r.status_code in (401, 403):
        raise ErroJellyfin("o Jellyfin recusou a chave de API (confira JELLYFIN_API_KEY)")
    if r.status_code == 404:
        raise ErroJellyfin(f"endereço errado? {url} não existe (confira JELLYFIN_URL)")
    if not r.ok:
        raise ErroJellyfin(f"o Jellyfin respondeu HTTP {r.status_code}")
    log.info("Jellyfin: escaneamento da biblioteca iniciado (%s)", jellyfin_url)
