"""Comandos:

  python -m jellyfin_tools demo
      Demonstração completa com os 3 arquivos de exemplo e o site de legendas simulado.

  python -m jellyfin_tools organizar ORIGEM PASTA_FILMES [--aplicar] [--legendas-demo | --site-legendas URL | --opensubtitles]
      Sem --aplicar só mostra o que faria (nada é movido).

      Com --series: organiza episódios em Séries/Nome (Ano)/Season 01/Nome S01E01.ext

  python -m jellyfin_tools legendas PASTA_FILMES [--series] [--legendas-demo | --site-legendas URL | --opensubtitles]
  python -m jellyfin_tools desfazer PASTA_FILMES        (desfaz a última organização)

Chaves de API (opcionais) por variável de ambiente: TMDB_API_KEY, OPENSUBTITLES_API_KEY, SUBDL_API_KEY.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

from .catalogo import CatalogoEmCadeia, CatalogoLocal, CatalogoTMDB, ErroCatalogo
from .legendas import (ConfigSite, ErroLegenda, ProvedorOpenSubtitles, ProvedorSiteHTML, ProvedorSubDL,
                       baixar_legenda, baixar_legenda_episodio, baixar_legendas_biblioteca,
                       baixar_legendas_series)
from .organizador import desfazer, organizar_pasta, ultimo_log
from .site_demo import iniciar_site_demo

ARQUIVOS_DEMO = ["Matrix.1999.1080p.BluRay.x264-VERSAO.mp4",
                 "interestellar_filme_completo_dublado_2014.mkv",
                 "O.Poderoso.Chefao.1972.Bluray.mkv"]


def _opcoes_legendas(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("legendas")
    g.add_argument("--legendas-demo", action="store_true", help="usar o site de legendas simulado (local)")
    g.add_argument("--site-legendas", metavar="URL",
                   help="URL de busca de um site que permite robôs, com {consulta}. Ex.: https://site/busca?q={consulta}")
    g.add_argument("--opensubtitles", action="store_true", help="API oficial (precisa de OPENSUBTITLES_API_KEY)")
    g.add_argument("--subdl", action="store_true", help="API do SubDL (precisa de SUBDL_API_KEY); com "
                   "--opensubtitles, entra quando ele não acha ou atinge o limite")
    g.add_argument("--idioma", default="pt-BR")
    g.add_argument("--sobrescrever", action="store_true", help="trocar legendas que já existem")


def _criar_provedores(args, desligar: list) -> list:
    provedores = []
    if args.legendas_demo:
        servidor, base = iniciar_site_demo()
        desligar.append(servidor)
        provedores.append(ProvedorSiteHTML(ConfigSite(f"{base}/busca?q={{consulta}}", nome="site demo")))
    if args.site_legendas:
        if "{consulta}" not in args.site_legendas:
            raise SystemExit("--site-legendas precisa conter {consulta} no lugar do termo pesquisado")
        provedores.append(ProvedorSiteHTML(ConfigSite(args.site_legendas)))
    if args.opensubtitles:
        provedores.append(ProvedorOpenSubtitles(os.environ.get("OPENSUBTITLES_API_KEY", "")))
    if args.subdl:                                   # depois do OpenSubtitles: a reserva
        provedores.append(ProvedorSubDL(os.environ.get("SUBDL_API_KEY", "")))
    return provedores


def _criar_catalogo(args):
    local = CatalogoLocal.de_json(args.catalogo) if args.catalogo else CatalogoLocal.padrao()
    if args.tmdb:
        return CatalogoEmCadeia(local, CatalogoTMDB(os.environ.get("TMDB_API_KEY", "")))
    return local


def arvore(pasta: Path, prefixo: str = "") -> str:
    """Desenha a pasta como árvore (ignora a pasta de logs)."""
    linhas = []
    itens = sorted(p for p in pasta.iterdir() if not p.name.startswith("."))
    for i, item in enumerate(itens):
        ultimo = i == len(itens) - 1
        linhas.append(f"{prefixo}{'└── ' if ultimo else '├── '}{item.name}{'/' if item.is_dir() else ''}")
        if item.is_dir():
            linhas.append(arvore(item, prefixo + ("    " if ultimo else "│   ")))
    return "\n".join(l for l in linhas if l)


def _organizar(args) -> int:
    desligar: list = []
    try:
        movimentos = organizar_pasta(args.origem, args.pasta_filmes, _criar_catalogo(args),
                                     aplicar=args.aplicar, recursivo=not args.sem_subpastas,
                                     incluir_tmdbid=args.tmdbid, exigir_catalogo=args.exigir_catalogo,
                                     modo="series" if args.series else "filmes",
                                     limpar_lixo=not args.manter_lixo,
                                     limite_trailer_mb=args.limite_trailer_mb)
        for m in movimentos:
            print(m)
        if not args.aplicar:
            print("\n(simulação: nada foi movido. Rode de novo com --aplicar para valer.)")
            return 0
        provedores = _criar_provedores(args, desligar)
        for m in movimentos:
            if m.status == "movido" and provedores:
                originais = [m.filme.titulo_original] if m.filme and m.filme.titulo_original else []
                if m.episodio:
                    print(baixar_legenda_episodio(m.destino, provedores, idioma=args.idioma,
                                                  sobrescrever=args.sobrescrever, titulos_alternativos=originais))
                else:
                    print(baixar_legenda(m.destino.parent, provedores, idioma=args.idioma,
                                         sobrescrever=args.sobrescrever, titulos_alternativos=originais))
        return 1 if any(m.status == "erro" for m in movimentos) else 0
    finally:
        for s in desligar:
            s.shutdown()


def _legendas(args) -> int:
    desligar: list = []
    try:
        provedores = _criar_provedores(args, desligar)
        if not provedores:
            print("Escolha uma fonte: --legendas-demo, --site-legendas URL ou --opensubtitles")
            return 1
        funcao = baixar_legendas_series if args.series else baixar_legendas_biblioteca
        resultados = funcao(args.pasta_filmes, provedores, args.idioma, args.sobrescrever,
                            catalogo=CatalogoLocal.padrao())
        return 1 if any(r.status == "erro" for r in resultados) else 0
    finally:
        for s in desligar:
            s.shutdown()


def _desfazer(args) -> int:
    alvo = Path(args.alvo)
    log = alvo if alvo.is_file() else ultimo_log(alvo)
    if not log:
        print("Nenhuma organização para desfazer.")
        return 1
    for mensagem in desfazer(log):
        print(mensagem)
    return 0


def _demo(args) -> int:
    raiz = Path(args.pasta).resolve()
    if raiz.exists():
        if not (raiz / ".demo").exists():
            print(f"{raiz} já existe e não é uma pasta de demonstração; escolha outra com --pasta.")
            return 1
        shutil.rmtree(raiz)
    downloads, filmes = raiz / "Downloads", raiz / "Filmes"
    downloads.mkdir(parents=True)
    (raiz / ".demo").touch()
    for nome in ARQUIVOS_DEMO:
        (downloads / nome).write_bytes(b"video ficticio de demonstracao")

    print("ANTES:\n" + raiz.name + "/\n" + arvore(raiz))
    print("\n1) Simulação (nada é movido ainda):")
    for m in organizar_pasta(downloads, filmes, CatalogoLocal.padrao()):
        print("  ", m)
    print("\n2) Organizando de verdade...")
    for m in organizar_pasta(downloads, filmes, CatalogoLocal.padrao(), aplicar=True):
        print("  ", m)
    print("\n3) Baixando legendas do site simulado...")
    servidor, base = iniciar_site_demo()
    try:
        provedor = ProvedorSiteHTML(ConfigSite(f"{base}/busca?q={{consulta}}", nome="site demo"))
        provedor.cliente.espera = 0.2
        baixar_legendas_biblioteca(filmes, [provedor], catalogo=CatalogoLocal.padrao())
    finally:
        servidor.shutdown()
    print("\nDEPOIS:\n" + raiz.name + "/\n" + arvore(raiz))
    print(f"\nAbra a pasta para conferir: {raiz}")
    print(f"Para desfazer:  python -m jellyfin_tools desfazer \"{filmes}\"")
    return 0


def _demo_torrent(args) -> int:
    """Os dois exemplos do pedido: Creed II (com propaganda) e Velhos Bandidos (sem legenda)."""
    from .pipeline import organizar_e_legendar
    raiz = Path(args.pasta).resolve()
    if raiz.exists():
        if not (raiz / ".demo").exists():
            print(f"{raiz} já existe e não é uma pasta de demonstração; escolha outra com --pasta.")
            return 1
        shutil.rmtree(raiz)
    torrent = raiz / "Downloads" / "Creed.II.2018.1080p.BluRay-BLUDV"
    torrent.mkdir(parents=True)
    (raiz / ".demo").touch()

    def video(caminho, mb):
        with open(caminho, "wb") as f:
            f.truncate(int(mb * 1024 * 1024))       # tamanho "de mentira": não ocupa o disco de verdade

    video(torrent / "Creed.II.2018.1080p.BluRay.6CH.x264.DUAL-WWW.BLUDV.TV-TioKennedy.mkv", 1500)
    video(torrent / "BLUDV.TV-Trailer.mp4", 12)
    for nome in ("BLUDV.TV.url", "Leia.txt", "Creed.II-backdrop.jpg", "Creed.II-poster.jpg", "Creed.II.FORCED.srt"):
        (torrent / nome).write_bytes(b"1\n00:00:01,000 --> 00:00:02,000\nForcada\n" if nome.endswith(".srt") else b"x")
    video(raiz / "Downloads" / "Velhos.Bandidos.2026.1080p.WEB-DL.NACIONAL.5.1.mkv", 900)

    print("ANTES:\n" + raiz.name + "/\n" + arvore(raiz))
    servidor, base = iniciar_site_demo()
    try:
        provedor = ProvedorSiteHTML(ConfigSite(f"{base}/busca?q={{consulta}}", nome="site demo"))
        provedor.cliente.espera = 0.2
        print("\nPré-visualização:")
        previa, _ = organizar_e_legendar(raiz / "Downloads", raiz / "Filmes", CatalogoLocal.padrao())
        for m in previa:
            print("  ", m)
            for lixo in m.apagar or []:
                print("      apagar:", lixo.name)
        print("\nAplicando...")
        movimentos, legendas = organizar_e_legendar(raiz / "Downloads", raiz / "Filmes", CatalogoLocal.padrao(),
                                                    [provedor], aplicar=True)
        for r in legendas:
            print("  ", r)
    finally:
        servidor.shutdown()
    print("\nDEPOIS:\n" + raiz.name + "/\n" + arvore(raiz))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="jellyfin_tools", description="Organiza filmes e baixa legendas para o Jellyfin.")
    sub = ap.add_subparsers(dest="comando", required=True)

    d = sub.add_parser("demo", help="demonstração com arquivos fictícios")
    d.add_argument("--pasta", default="demo_jellyfin")
    dt = sub.add_parser("demo-torrent", help="demonstração: torrent com propaganda, imagens e legenda FORCED")
    dt.add_argument("--pasta", default="demo_torrent")

    o = sub.add_parser("organizar", help="mover/renomear vídeos para o padrão do Jellyfin")
    o.add_argument("origem")
    o.add_argument("pasta_filmes")
    o.add_argument("--aplicar", action="store_true", help="mover de verdade (sem isso, só simula)")
    o.add_argument("--catalogo", help="arquivo JSON com seus filmes (padrão: catalogo_filmes.json)")
    o.add_argument("--tmdb", action="store_true", help="também consultar o TMDB (precisa de TMDB_API_KEY)")
    o.add_argument("--tmdbid", action="store_true", help="incluir [tmdbid-XXX] no nome da pasta")
    o.add_argument("--exigir-catalogo", action="store_true", help="só mover filmes confirmados no catálogo")
    o.add_argument("--sem-subpastas", action="store_true", help="não procurar dentro de subpastas")
    o.add_argument("--manter-lixo", action="store_true",
                   help="não apagar .url/.txt de propaganda nem trailers pequenos")
    o.add_argument("--limite-trailer-mb", type=float, default=100,
                   help="vídeo menor que isso, ao lado do filme e com cara de propaganda, é trailer (padrão 100)")
    o.add_argument("--series", action="store_true",
                   help="organizar episódios de séries (PASTA_FILMES = pasta de séries do Jellyfin)")
    _opcoes_legendas(o)

    le = sub.add_parser("legendas", help="baixar legendas que faltam na biblioteca")
    le.add_argument("pasta_filmes")
    le.add_argument("--series", action="store_true", help="a pasta é a biblioteca de séries")
    _opcoes_legendas(le)

    de = sub.add_parser("desfazer", help="desfazer a última organização")
    de.add_argument("alvo", help="pasta de filmes (usa o último log) ou um arquivo de log")

    args = ap.parse_args(argv)
    acoes = {"demo": _demo, "demo-torrent": _demo_torrent, "organizar": _organizar, "legendas": _legendas,
             "desfazer": _desfazer}
    try:
        return acoes[args.comando](args)
    except (ErroCatalogo, ErroLegenda, NotADirectoryError) as erro:
        print(f"Erro: {erro}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
