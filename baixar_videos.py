#!/usr/bin/env python3
"""
Baixador de vídeos PÚBLICOS a partir de uma página de listagem.

Baseado no script original, com as mesmas etapas:
  1. CONFIGURAÇÃO  2. CRIAR PASTA  3. REQUISIÇÃO  4. PARSE  5. EXTRAÇÃO  6. DOWNLOAD

Uso:
  python baixar_videos.py https://exemplo.com/videos/acao
  python baixar_videos.py https://exemplo.com/videos/acao -p meus_videos -s "a.video-link" -e 3

Baixe apenas conteúdo que você tem direito de baixar (público/autorizado).
"""

import argparse
import os
import re
import sys
import time
from urllib import robotparser
from urllib.parse import unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

# 1. CONFIGURAÇÃO (valores padrão; podem ser trocados pela linha de comando)
URL = "https://exemplo.com/videos/acao"
PASTA = "videos_baixados"
SELETOR = "a.video-link"      # seletor CSS dos links (equivale a find_all("a", class_="video-link"))
ESPERA = 2.0                  # segundos entre downloads
TIMEOUT = 20                  # segundos máximos esperando o servidor responder
USER_AGENT = "BaixadorVideos/1.0 (projeto educacional)"
EXTENSOES = (".mp4", ".webm", ".mkv", ".mov", ".m4v", ".avi")


def nome_seguro(texto, padrao):
    """Limpa o título para virar nome de arquivo (remove / \\ : * ? " < > | etc.)."""
    limpo = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", texto or "")
    limpo = re.sub(r"\s+", " ", limpo).strip(" .")
    return limpo[:120] or padrao


def extensao_da_url(url):
    """Pega a extensão do arquivo na URL (.mp4, .webm...). Se não tiver, usa .mp4."""
    ext = os.path.splitext(urlparse(url).path)[1].lower()
    return ext if ext in EXTENSOES else ".mp4"


def caminho_livre(pasta, base, ext):
    """Se 'aula.mp4' já existe, devolve 'aula (2).mp4' em vez de sobrescrever."""
    caminho = os.path.join(pasta, base + ext)
    n = 2
    while os.path.exists(caminho):
        caminho = os.path.join(pasta, f"{base} ({n}){ext}")
        n += 1
    return caminho


def robots_permite(sessao, url):
    """Consulta o robots.txt do site. Sem robots.txt = liberado."""
    p = urlparse(url)
    rp = robotparser.RobotFileParser()
    try:
        r = sessao.get(f"{p.scheme}://{p.netloc}/robots.txt", timeout=TIMEOUT)
        if r.status_code != 200:
            return True
        rp.parse(r.text.splitlines())
    except requests.RequestException:
        return True
    return rp.can_fetch(USER_AGENT, url)


def extrair_videos(html, url_base, seletor):
    """Devolve lista de (titulo, url_absoluta). `html` pode ser bytes (preferível: o
    BeautifulSoup detecta a codificação) ou str."""
    soup = BeautifulSoup(html, "html.parser")
    achados, vistos = [], set()
    for link in soup.select(seletor):
        href = link.get("href")
        if not href or href.startswith(("javascript:", "#", "mailto:")):
            continue
        url_video = urljoin(url_base, href)      # trata links relativos (/v/1.mp4)
        if urlparse(url_video).scheme not in ("http", "https") or url_video in vistos:
            continue
        vistos.add(url_video)
        achados.append((link.get_text(strip=True), url_video))
    return achados


def baixar_arquivo(sessao, url, destino):
    """Baixa em blocos de 1 MB (não carrega o vídeo inteiro na memória)."""
    parcial = destino + ".part"                  # só vira o nome final se terminar OK
    try:
        with sessao.get(url, stream=True, timeout=TIMEOUT) as r:
            r.raise_for_status()                 # erro 404/500 vira exceção
            tipo = r.headers.get("Content-Type", "").lower()
            if "text/html" in tipo:
                raise ValueError("a URL devolveu uma página HTML, não um vídeo")
            total = int(r.headers.get("Content-Length", 0))
            baixado = 0
            with open(parcial, "wb") as f:
                for bloco in r.iter_content(chunk_size=1024 * 1024):
                    f.write(bloco)
                    baixado += len(bloco)
                    if total:
                        print(f"\r   {baixado / total:5.1%} ({baixado / 1e6:.1f}/{total / 1e6:.1f} MB)",
                              end="", flush=True)
        if total:
            print()
        os.replace(parcial, destino)
    finally:
        if os.path.exists(parcial):
            os.remove(parcial)                   # limpa arquivo incompleto em caso de erro


def main(argv=None):
    ap = argparse.ArgumentParser(description="Baixa vídeos públicos listados em uma página.")
    ap.add_argument("url", nargs="?", default=URL, help=f"página de listagem (padrão: {URL})")
    ap.add_argument("-p", "--pasta", default=PASTA, help=f"pasta de destino (padrão: {PASTA})")
    ap.add_argument("-s", "--seletor", default=SELETOR, help=f"seletor CSS dos links (padrão: {SELETOR})")
    ap.add_argument("-e", "--espera", type=float, default=ESPERA, help="segundos entre downloads")
    ap.add_argument("-l", "--limite", type=int, default=0, help="máximo de vídeos (0 = todos)")
    ap.add_argument("--so-listar", action="store_true", help="apenas mostra os links, sem baixar")
    ap.add_argument("--ignorar-robots", action="store_true", help="não consultar robots.txt (só em sites seus)")
    args = ap.parse_args(argv)

    sessao = requests.Session()
    sessao.headers["User-Agent"] = USER_AGENT

    # 2. CRIAR PASTA
    if not args.so_listar:
        os.makedirs(args.pasta, exist_ok=True)

    # 3. REQUISIÇÃO
    print("📥 Acessando site...")
    if not args.ignorar_robots and not robots_permite(sessao, args.url):
        print("⛔ O robots.txt do site não permite acessar esta página.")
        return 1
    try:
        resposta = sessao.get(args.url, timeout=TIMEOUT)
        resposta.raise_for_status()
    except requests.RequestException as erro:
        print(f"❌ Não consegui acessar a página: {erro}")
        return 1

    # 4. PARSE + 5. EXTRAÇÃO
    print("🔍 Analisando HTML e 📋 encontrando vídeos...")
    videos = extrair_videos(resposta.content, resposta.url, args.seletor)
    if args.limite:
        videos = videos[:args.limite]
    print(f"   {len(videos)} vídeo(s) encontrado(s) com o seletor '{args.seletor}'.")
    if not videos:
        print("   Dica: confira o seletor (-s) inspecionando o HTML da página.")
        return 0

    # 6. DOWNLOAD
    ok = falhas = 0
    for i, (titulo, url_video) in enumerate(videos, 1):
        padrao = unquote(os.path.splitext(os.path.basename(urlparse(url_video).path))[0]) or f"video_{i}"
        print(f"\n[{i}/{len(videos)}] {titulo or padrao}\n   {url_video}")
        if args.so_listar:
            continue
        if not args.ignorar_robots and not robots_permite(sessao, url_video):
            print("⛔ robots.txt não permite este arquivo, pulando.")
            falhas += 1
            continue
        destino = caminho_livre(args.pasta, nome_seguro(titulo, padrao), extensao_da_url(url_video))
        try:
            baixar_arquivo(sessao, url_video, destino)
            print(f"✅ Salvo em {destino}")
            ok += 1
        except Exception as erro:                # um vídeo com erro não derruba os outros
            print(f"❌ Erro: {erro}")
            falhas += 1
        if i < len(videos):
            time.sleep(args.espera)              # respeita o servidor

    print(f"\n🎉 Pronto! {ok} baixado(s), {falhas} falha(s).")
    return 0 if falhas == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
