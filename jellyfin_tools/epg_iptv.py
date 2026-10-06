"""Programação de verdade dos canais (o que passa ao longo do dia), pelo projeto iptv-org/epg.

Ninguém publica pronto um guia (XMLTV) para os canais brasileiros. O projeto iptv-org/epg (código aberto, o
mesmo time das listas de canais) tem um "coletor" que busca a programação nos sites de guia de TV (mi.tv,
meuguia.tv...) todo dia e entrega um guide.xml. Ele roda num container do Docker:

    docker run -d --name maestro-guia -p 3000:3000 -v <channels.xml>:/epg/public/channels.xml ghcr.io/iptv-org/epg:master
    -> http://localhost:3000/guide.xml  (é esse endereço que vai no campo "Guia de programação")

O coletor precisa de um channels.xml dizendo DE QUAL site buscar CADA canal. Montar à mão para 144 canais não dá:
aqui o programa baixa o mapa da iptv-org (que canal tem guia em qual site), acha os canais da sua lista e grava
o channels.xml. A cada "Salvar e enviar" ele é regravado: canais novos entram sozinhos (o coletor lê o arquivo
de novo na próxima coleta).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

import requests

ARQUIVO_CANAIS_EPG = "channels.xml"
URL_GUIA_LOCAL = "http://localhost:3000/guide.xml"
NOME_CONTAINER = "maestro-guia"
IMAGEM = "ghcr.io/iptv-org/epg:master"
URLS_MAPA = ("https://iptv-org.github.io/api/guides.json",
             "https://raw.githubusercontent.com/iptv-org/api/gh-pages/guides.json")
DIAS_DO_CACHE = 7
# sites que costumam funcionar bem para canais brasileiros (desempate)
SITES_PREFERIDOS = ("mi.tv", "meuguia.tv", "claro.com.br", "nostv.pt", "meo.pt")


class ErroEPG(Exception):
    pass


def baixar_mapa(cache: str | Path, sessao=None, agora: float | None = None, timeout: float = 120) -> list[dict]:
    """O mapa "canal -> site de guia" da iptv-org (~25 MB). Guardado em `cache` por 7 dias, só com o que
    interessa (as entradas ligadas a um canal)."""
    cache = Path(cache)
    agora = time.time() if agora is None else agora
    try:
        if cache.is_file() and agora - cache.stat().st_mtime < DIAS_DO_CACHE * 86400:
            return json.loads(cache.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    erros = []
    for url in URLS_MAPA:
        try:
            r = (sessao or requests).get(url, timeout=timeout)
            if not r.ok:
                erros.append(f"{url}: HTTP {r.status_code}")
                continue
            dados = r.json()
        except (requests.RequestException, ValueError) as erro:
            erros.append(f"{url}: {erro}")
            continue
        enxuto = [{k: g.get(k) for k in ("channel", "feed", "site", "site_id", "site_name", "lang")}
                  for g in dados if isinstance(g, dict) and g.get("channel") and g.get("site") and g.get("site_id")]
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(enxuto, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
        return enxuto
    if cache.is_file():                                # sem internet: o cache velho serve
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    raise ErroEPG("não deu para baixar o mapa de guias da iptv-org (" + "; ".join(erros)[:300] + ")")


def _simples(texto: str) -> str:
    import unicodedata
    texto = re.sub(r"\([^)]*\)|\[[^\]]*\]|\b(?:fhd|uhd|hd|sd|4k|h265|hevc)\b", " ", (texto or "").lower())
    texto = "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]", "", texto)


def _id_sem_pais(canal_id: str) -> str:
    """'AgroMais.br' -> 'agromais'."""
    return _simples(canal_id.split("@")[0].rsplit(".", 1)[0])


_CODIGO_DO_IDIOMA = {"Português": "pt", "English": "en", "Español": "es", "Français": "fr", "Italiano": "it",
                     "Deutsch": "de"}


def achar_guias(canais, mapa: list[dict]) -> list[tuple[object, dict | None]]:
    """Para cada canal da lista, a melhor entrada do mapa (ou None): pelo tvg-id (sem o @feed); senão pelo nome
    (sem enfeites como "(720p)"). Desempate: o idioma do canal, depois os sites que funcionam melhor."""
    from .tv_ao_vivo import idioma_do_canal
    por_id: dict[str, list[dict]] = {}
    por_nome: dict[str, list[dict]] = {}
    for g in mapa:
        por_id.setdefault(g["channel"].split("@")[0].lower(), []).append(g)
        for nome in {_simples(g.get("site_name") or ""), _id_sem_pais(g["channel"])} - {""}:
            por_nome.setdefault(nome, []).append(g)
    resultado = []
    for c in canais:
        opcoes = por_id.get((c.id_guia or "").split("@")[0].lower(), []) if c.id_guia else []
        if not opcoes:
            opcoes = por_nome.get(_simples(c.nome), [])
        lingua = _CODIGO_DO_IDIOMA.get(idioma_do_canal(c), "")
        if lingua and not (c.id_guia and opcoes and opcoes[0]["channel"].split("@")[0].lower()
                           == c.id_guia.split("@")[0].lower()):
            opcoes = [g for g in opcoes if g.get("lang") == lingua]   # pelo nome: só no idioma do canal

        def nota(g):
            site = g.get("site") or ""
            return (g.get("lang") == lingua, -SITES_PREFERIDOS.index(site) if site in SITES_PREFERIDOS else -99)
        resultado.append((c, max(opcoes, key=nota) if opcoes else None))
    return resultado


def gerar_channels_xml(achados: list[tuple[object, dict | None]]) -> str:
    """O channels.xml do coletor. Cada canal da lista vira uma entrada com o MESMO id/nome que ele tem no
    Jellyfin (tvg-id da lista ou, sem ele, o nome): é assim que o Jellyfin liga a programação ao canal."""
    from .tv_ao_vivo import _ids_e_numeros
    canais = [c for c, _ in achados]
    ids = {id(c): id_guia for c, (id_guia, _) in zip(canais, _ids_e_numeros(canais))}
    linhas = ['<?xml version="1.0" encoding="UTF-8"?>', "<channels>"]
    for n, (c, g) in enumerate(achados, 1):
        if g is None:
            continue
        xmltv_id = ids.get(id(c)) or g["channel"] + (f"@{g['feed']}" if g.get("feed") else "")
        linhas.append(f"  <channel site={quoteattr(g['site'])} lang={quoteattr(g.get('lang') or '')} "
                      f"xmltv_id={quoteattr(xmltv_id)} site_id={quoteattr(g['site_id'])}>{escape(c.nome)}</channel>")
    linhas.append("</channels>")
    return "\n".join(linhas) + "\n"


def gravar_channels_xml(canais, pasta: str | Path, mapa: list[dict]) -> tuple[Path, int, list]:
    """Grava <pasta>/channels.xml. Devolve (arquivo, quantos têm programação, os que não têm)."""
    achados = achar_guias(canais, mapa)
    arquivo = Path(pasta) / ARQUIVO_CANAIS_EPG
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    arquivo.write_text(gerar_channels_xml(achados), encoding="utf-8")
    return arquivo, sum(1 for _, g in achados if g), [c for c, g in achados if g is None]


# ----------------------------------------------------------------- Docker
def achar_docker() -> str | None:
    """O docker.exe (no PATH ou no lugar padrão do Docker Desktop)."""
    if caminho := shutil.which("docker"):
        return caminho
    padrao = Path(r"C:\Program Files\Docker\Docker\resources\bin\docker.exe")
    return str(padrao) if sys.platform == "win32" and padrao.is_file() else None


def comando_docker(channels_xml: str | Path, docker: str = "docker", dias: int = 3) -> list[str]:
    """O container do coletor: busca a programação ao ligar e todo dia às 06:00 UTC, guarda `dias` dias e fica
    no ar sozinho (--restart unless-stopped: volta quando o Docker Desktop abre)."""
    return [docker, "run", "-d", "--name", NOME_CONTAINER, "--restart", "unless-stopped", "-p", "3000:3000",
            "-v", f"{channels_xml}:/epg/public/{ARQUIVO_CANAIS_EPG}", "-e", f"DAYS={dias}",
            "-e", "CRON_SCHEDULE=0 6 * * *", "-e", "MAX_CONNECTIONS=2", "-e", "RUN_AT_STARTUP=true", IMAGEM]


def iniciar_container(channels_xml: str | Path, rodar=subprocess.run, docker: str | None = None) -> str:
    """Tira o container antigo (se houver) e cria o novo. Devolve o que o Docker respondeu; ErroEPG se falhar."""
    docker = docker or achar_docker()
    if not docker:
        raise ErroEPG("o Docker não foi encontrado (instale e abra o Docker Desktop)")
    extra = {"creationflags": 0x08000000} if sys.platform == "win32" else {}      # sem janela preta
    rodar([docker, "rm", "-f", NOME_CONTAINER], capture_output=True, text=True, timeout=120, **extra)
    r = rodar(comando_docker(channels_xml, docker), capture_output=True, text=True, timeout=900, **extra)
    if r.returncode != 0:
        raise ErroEPG((r.stderr or r.stdout or "o Docker recusou").strip()[:400])
    return (r.stdout or "").strip()
