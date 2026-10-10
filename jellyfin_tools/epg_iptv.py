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

import gzip
import io
import json
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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


# ----------------------------------------------------------------- conferir: o coletor está funcionando?
def estado_do_coletor(rodar=subprocess.run, docker: str | None = None) -> str:
    """O container do coletor: 'rodando', 'parado (...)', 'não criado', 'Docker fechado' ou 'sem Docker'."""
    docker = docker or achar_docker()
    if not docker:
        return "sem Docker"
    extra = {"creationflags": 0x08000000} if sys.platform == "win32" else {}      # sem janela preta
    try:
        r = rodar([docker, "inspect", "-f", "{{.State.Status}}", NOME_CONTAINER], capture_output=True, text=True,
                  timeout=30, **extra)
    except (OSError, subprocess.SubprocessError):
        return "Docker fechado"
    if r.returncode != 0:
        return "não criado" if "no such" in (r.stderr or r.stdout or "").lower() else "Docker fechado"
    situacao = (r.stdout or "").strip()
    return "rodando" if situacao == "running" else f"parado ({situacao or '?'})"


@dataclass(frozen=True, order=True)
class Programa:
    inicio: datetime
    fim: datetime | None
    titulo: str


_RE_HORA = re.compile(r"(\d{14})\s*([+-]\d{4})?")


def _quando(texto: str | None) -> datetime | None:
    """'20261006143000 -0300' -> datetime com fuso (sem fuso = UTC, como manda o XMLTV)."""
    if not (m := _RE_HORA.match((texto or "").strip())):
        return None
    try:
        hora = datetime.strptime(m.group(1), "%Y%m%d%H%M%S")
    except ValueError:
        return None
    if m.group(2):
        sinal = 1 if m.group(2)[0] == "+" else -1
        fuso = timezone(sinal * timedelta(hours=int(m.group(2)[1:3]), minutes=int(m.group(2)[3:5])))
    else:
        fuso = timezone.utc
    return hora.replace(tzinfo=fuso)


def ler_guia(endereco: str = URL_GUIA_LOCAL, sessao=None, timeout: float = 30) -> dict[str, list[Programa]] | None:
    """{id do canal: [programas]} do guia que o coletor entrega. None = o guia ainda não está lá (o coletor está
    desligado ou não terminou a 1ª coleta)."""
    try:
        r = (sessao or requests).get(endereco, timeout=timeout)
    except requests.RequestException:
        return None
    if r.status_code != 200 or not r.content:
        return None
    dados = r.content
    if dados[:2] == b"\x1f\x8b":                                   # .xml.gz
        try:
            dados = gzip.decompress(dados)
        except OSError:
            return None
    grade: dict[str, list[Programa]] = {}
    try:
        for _, el in ET.iterparse(io.BytesIO(dados), events=("end",)):
            if el.tag == "programme" and el.get("channel"):
                inicio = _quando(el.get("start"))
                if inicio is not None:
                    titulo = (el.findtext("title") or "").strip() or "(sem título)"
                    grade.setdefault(el.get("channel"), []).append(Programa(inicio, _quando(el.get("stop")), titulo))
                el.clear()
            elif el.tag == "channel" and el.get("id"):
                grade.setdefault(el.get("id"), [])
                el.clear()
    except ET.ParseError:
        return None
    return {canal: sorted(lista) for canal, lista in grade.items()} or None    # vazio = ainda não coletou


def programas_do_guia(endereco: str = URL_GUIA_LOCAL, sessao=None, timeout: float = 30) -> dict[str, int] | None:
    """{id do canal: quantos programas} no guia que o coletor entrega (None = o guia ainda não está lá)."""
    grade = ler_guia(endereco, sessao, timeout)
    return None if grade is None else {canal: len(lista) for canal, lista in grade.items()}


def agora_por_canal(canais, entradas: list[tuple[str, str, str]], grade: dict[str, list[Programa]] | None,
                    agora: datetime | None = None) -> dict[str, str]:
    """{link do canal: "Jornal Hoje (até 14:00) → Sessão da Tarde"}: o que passa agora e o que vem depois, no
    horário DESTE computador. Canais sem grade ficam de fora."""
    if not grade:
        return {}
    agora = agora or datetime.now(timezone.utc)
    por_nome: dict[str, str] = {}
    for nome, xmltv_id, _ in entradas:
        por_nome.setdefault(nome, xmltv_id)
    resultado = {}
    for c in canais:
        lista = grade.get(por_nome.get(c.nome, ""), [])
        atual = next((p for p in lista if p.inicio <= agora and (p.fim is None or agora < p.fim)), None)
        proximo = next((p for p in lista if p.inicio > agora), None)
        if atual:
            ate = f" (até {atual.fim.astimezone():%H:%M})" if atual.fim else ""
            resultado[c.url] = f"{atual.titulo}{ate}" + (f" → {proximo.titulo}" if proximo else "")
        elif proximo:
            resultado[c.url] = f"às {proximo.inicio.astimezone():%H:%M}: {proximo.titulo}"
    return resultado


def ler_channels_xml(arquivo: str | Path) -> list[tuple[str, str, str]]:
    """[(nome do canal, xmltv_id, site)] do channels.xml montado pelo programa."""
    try:
        raiz = ET.parse(arquivo).getroot()
    except (OSError, ET.ParseError):
        return []
    return [((c.text or "").strip(), c.get("xmltv_id") or "", c.get("site") or "") for c in raiz.iter("channel")]


def programacao_por_canal(canais, entradas: list[tuple[str, str, str]],
                          programas: dict[str, int] | None) -> dict[str, str]:
    """{link do canal: o que mostrar na coluna Programação}:
        "✓ 57 programas · mi.tv"      o guia do coletor tem a grade desse canal
        "aguardando coleta · mi.tv"    o canal está no channels.xml, mas o guia ainda não chegou
        "sem programas · mi.tv"        o guia chegou, mas o site não trouxe nada para esse canal
        "só categoria"                 nenhum site de guia tem esse canal (fica com o guia de categorias)"""
    por_nome: dict[str, tuple[str, str]] = {}
    for nome, xmltv_id, site in entradas:
        por_nome.setdefault(nome, (xmltv_id, site))
    resultado = {}
    for c in canais:
        if c.nome not in por_nome:
            resultado[c.url] = "só categoria"
            continue
        xmltv_id, site = por_nome[c.nome]
        if programas is None:
            resultado[c.url] = f"aguardando coleta · {site}"
        elif programas.get(xmltv_id):
            resultado[c.url] = f"✓ {programas[xmltv_id]} programas · {site}"
        else:
            resultado[c.url] = f"sem programas · {site}"
    return resultado


def resumo_do_coletor(estado: str, programas: dict[str, int] | None, por_canal: dict[str, str],
                      guia_no_campo: bool, guia_no_jellyfin: bool | None) -> str:
    """O texto do "Conferir programação": o que está funcionando e o que falta fazer."""
    linhas = []
    dicas = {"rodando": "rodando ✓", "não criado": "não existe ainda: clique em \"Programação dos canais...\" e "
             "em \"Iniciar o coletor no Docker\"", "Docker fechado": "o Docker Desktop está fechado: abra-o (o "
             "coletor volta sozinho)", "sem Docker": "o Docker não foi encontrado neste PC"}
    linhas.append(f"1. Coletor no Docker: {dicas.get(estado, estado + ': abra o Docker Desktop e confira')}")
    if programas is None:
        linhas.append(f"2. Guia em {URL_GUIA_LOCAL}: ainda não respondeu" + (
            " (a 1ª coleta leva de alguns minutos até 1 hora; acompanhe no Docker Desktop > Containers > "
            f"{NOME_CONTAINER} > Logs)" if estado == "rodando" else ""))
    else:
        linhas.append(f"2. Guia em {URL_GUIA_LOCAL}: {len(programas)} canal(is), "
                      f"{sum(programas.values())} programa(s) ✓")
    valores = list(por_canal.values())
    com = sum(v.startswith("✓") for v in valores)
    aguardando = sum(v.startswith("aguardando") for v in valores)
    sem = sum(v.startswith("sem programas") for v in valores)
    categoria = sum(v == "só categoria" for v in valores)
    linhas.append(f"3. Seus {len(valores)} canais: {com} com programação, {aguardando} aguardando a coleta, "
                  f"{sem} sem programas no site, {categoria} só com o guia de categorias")
    if not guia_no_campo:
        linhas.append(f"4. O endereço {URL_GUIA_LOCAL} NÃO está no campo \"Guia de programação\": coloque-o lá")
    elif guia_no_jellyfin is False:
        linhas.append("4. Jellyfin: o guia do coletor ainda não está cadastrado" + (
            ": clique em \"Salvar e enviar ao Jellyfin\"" if programas is not None else
            " (envie depois que o guia responder)"))
    elif guia_no_jellyfin:
        linhas.append("4. Jellyfin: o guia do coletor está cadastrado ✓ (ele relê a grade todo dia)")
    return "\n".join(linhas) + "\n\nA coluna \"Programação\" mostra a situação de cada canal (dá para filtrar)."
