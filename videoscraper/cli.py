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
import os
import sys
from dataclasses import asdict
from urllib.parse import urlparse

from .coleta import FonteNavegador, FonteRequests, rastrear
from .download import NaoBaixavel, baixar_video
from .extracao import LinkVideo
from .navegador import PERFIL_PADRAO, Navegador, PlaywrightAusente
from .rede import ClienteHTTP


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


def _criar_fonte(args, cliente):
    if not args.navegador and not args.visivel and not args.pausar:
        return FonteRequests(cliente)
    nav = Navegador(perfil=args.perfil, visivel=args.visivel, pausar=args.pausar,
                    executavel=args.chrome)
    return FonteNavegador(cliente, nav)


def _cmd_login(args) -> int:
    with Navegador(perfil=args.perfil, visivel=True, executavel=args.chrome) as nav:
        nav.login_manual(args.url)
    print("Agora use --navegador nos comandos 'links' e 'baixar' para aproveitar o login.")
    return 0


def _cmd_buscar(args) -> int:
    cliente = ClienteHTTP(espera=args.espera, respeitar_robots=not args.ignorar_robots)
    fonte = _criar_fonte(args, cliente)
    try:
        print("📥 Acessando" + (" com navegador..." if isinstance(fonte, FonteNavegador) else "..."),
              file=sys.stderr)
        links = rastrear(fonte, args.url, args.profundidade, args.max_paginas,
                         not args.qualquer_dominio, args.seletor)
        print(f"\n📋 {len(links)} link(s) de vídeo encontrado(s).", file=sys.stderr)
        if not links and isinstance(fonte, FonteRequests):
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
        fonte.sincronizar_cookies()           # downloads usam a mesma sessão (login) do navegador
        return _baixar_todos(cliente, links, args)
    finally:
        fonte.fechar()


def _baixar_todos(cliente, links, args) -> int:
    if not args.so_listar:
        os.makedirs(args.pasta, exist_ok=True)
    ok = pulados = falhas = 0
    for i, link in enumerate(links, 1):
        print(f"\n[{i}/{len(links)}] {link.titulo or link.url}\n   {link.url}  [{link.tipo}]")
        if args.so_listar:
            continue
        try:
            destino = baixar_video(cliente, link, args.pasta, i)
            print(f"✅ Salvo em {destino}")
            ok += 1
        except NaoBaixavel as motivo:
            print(f"⏭  Pulado: {motivo}")
            pulados += 1
        except Exception as erro:            # um vídeo com erro não derruba os outros
            print(f"❌ Erro: {erro}")
            falhas += 1
    if not args.so_listar:
        print(f"\n🎉 Pronto! {ok} baixado(s), {pulados} pulado(s), {falhas} falha(s).")
    return 2 if falhas else 0


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
