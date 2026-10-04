"""Comandos de terminal.

  python -m videoscraper links  URL [opções]   -> lista os links de vídeo
  python -m videoscraper baixar URL [opções]   -> baixa os vídeos
  python -m videoscraper login  URL            -> abre o navegador para você entrar na sua conta

Opção-chave: --navegador (usa Chrome de verdade: JavaScript, login, iframes, vídeos da rede).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import asdict
from urllib.parse import urlparse

from .extracao import LinkVideo
from .navegador import PERFIL_PADRAO, PlaywrightAusente
from .servico import MENSAGEM_ROBOTS, Trabalho, fazer_login


def _opcoes_comuns() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("url", help="endereço da página (http:// ou https://)")
    g = p.add_argument_group("acesso")
    g.add_argument("-e", "--espera", type=float, default=1.5, help="segundos entre pedidos (padrão 1.5)")
    g.add_argument("--ignorar-robots", action="store_true", help="não consultar robots.txt (só em sites seus)")
    n = p.add_argument_group("navegador (sites com JavaScript / login)")
    n.add_argument("-n", "--navegador", action="store_true", help="usar Chrome de verdade (Playwright)")
    n.add_argument("--visivel", action="store_true", help="mostrar a janela do navegador")
    n.add_argument("--pausar", action="store_true",
                   help="parar em cada página para VOCÊ resolver login/verificação na janela")
    n.add_argument("--perfil", default=PERFIL_PADRAO, help="pasta onde a sessão/login fica salva")
    n.add_argument("--chrome", help="caminho de um Chrome/Chromium já instalado (opcional)")
    return p


def _opcoes_busca(p: argparse.ArgumentParser) -> None:
    p.add_argument("-p", "--profundidade", type=int, default=0,
                   help="quantos níveis de links seguir (0 = só a página informada)")
    p.add_argument("-m", "--max-paginas", type=int, default=30, help="limite de páginas visitadas")
    p.add_argument("--qualquer-dominio", action="store_true", help="seguir links para outros sites")
    p.add_argument("--seletor", help="seletor CSS dos links (ex.: 'a.video-link'). Sem ele, detecta sozinho")
    p.add_argument("--filtro-links", default="",
                   help="ao seguir links, só os que contêm este texto (ex.: '/details/')")


def criar_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="videoscraper", description="Encontra e baixa vídeos públicos.")
    sub = ap.add_subparsers(dest="comando", required=True)
    comum = _opcoes_comuns()

    links = sub.add_parser("links", parents=[comum], help="listar links de vídeo")
    _opcoes_busca(links)
    links.add_argument("-s", "--saida", help="salvar em .txt, .csv ou .json")

    baixar = sub.add_parser("baixar", parents=[comum], help="baixar os vídeos")
    _opcoes_busca(baixar)
    baixar.add_argument("-d", "--pasta", default="videos_baixados", help="pasta de destino")
    baixar.add_argument("-l", "--limite", type=int, default=0, help="máximo de vídeos (0 = todos)")
    baixar.add_argument("--so-listar", action="store_true", help="mostra o que seria baixado, sem baixar")

    login = sub.add_parser("login", help="abrir o navegador para entrar na sua conta (fica salvo)")
    login.add_argument("url")
    login.add_argument("--perfil", default=PERFIL_PADRAO)
    login.add_argument("--chrome")
    return ap


def salvar(links: list[LinkVideo], caminho: str) -> None:
    if caminho.lower().endswith(".json"):
        with open(caminho, "w", encoding="utf-8") as f:
            json.dump([asdict(l) for l in links], f, ensure_ascii=False, indent=2)
    elif caminho.lower().endswith(".csv"):
        with open(caminho, "w", encoding="utf-8-sig", newline="") as f:   # -sig: Excel lê acentos
            w = csv.DictWriter(f, fieldnames=["url", "origem", "tipo", "titulo"])
            w.writeheader()
            w.writerows(asdict(l) for l in links)
    else:
        with open(caminho, "w", encoding="utf-8") as f:
            f.write("".join(l.url + "\n" for l in links))


def _cmd_login(args) -> int:
    fazer_login(args.url, perfil=args.perfil, chrome=args.chrome)
    print("Agora use --navegador nos comandos 'links' e 'baixar' para aproveitar o login.")
    return 0


def _cmd_buscar(args) -> int:
    with Trabalho(espera=args.espera, ignorar_robots=args.ignorar_robots, navegador=args.navegador,
                  visivel=args.visivel, pausar=args.pausar, perfil=args.perfil,
                  chrome=args.chrome) as t:
        print("📥 Acessando" + (" com navegador..." if t.usa_navegador else "..."), file=sys.stderr)
        links = t.buscar(args.url, args.profundidade, args.max_paginas,
                         not args.qualquer_dominio, args.seletor, args.filtro_links)
        print(f"\n📋 {len(links)} link(s) de vídeo encontrado(s).", file=sys.stderr)
        if t.bloqueadas and not links:
            print("\n" + MENSAGEM_ROBOTS, file=sys.stderr)
        elif not links and not t.usa_navegador:
            print("   Dica: se a página monta a lista com JavaScript ou exige login, "
                  "tente de novo com --navegador.", file=sys.stderr)

        if args.comando == "links":
            if args.saida:
                salvar(links, args.saida)
                print(f"💾 Salvo em {args.saida}", file=sys.stderr)
            else:
                for l in links:
                    print(f"{l.url}\t[{l.tipo}]")
            return 0

        if args.limite:
            links = links[:args.limite]
        if args.so_listar:
            for i, l in enumerate(links, 1):
                print(f"\n[{i}/{len(links)}] {l.titulo or l.url}\n   {l.url}  [{l.tipo}]")
            return 0
        return 2 if t.baixar(links, args.pasta).falhas else 0


def main(argv: list[str] | None = None) -> int:
    args = criar_parser().parse_args(argv)
    if urlparse(args.url).scheme not in ("http", "https"):
        print("❌ A URL precisa começar com http:// ou https://")
        return 1
    try:
        return _cmd_login(args) if args.comando == "login" else _cmd_buscar(args)
    except PlaywrightAusente as erro:
        print(f"❌ {erro}")
        return 1
    except KeyboardInterrupt:
        print("\nInterrompido.")
        return 130
