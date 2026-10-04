#!/usr/bin/env python3
"""Organizador completo da biblioteca do Jellyfin.

FASE 1 (já existente no pacote jellyfin_tools):
  1. Limpa nomes de torrent e cria  Filmes/Nome do Filme (Ano)/Nome do Filme (Ano).ext
  2. Legendas locais (.pt-BR.srt / .pt-BR.forced.srt) e imagens locais (poster.jpg, backdrop.jpg...)
  3. Apaga lixo (.url, .txt de propaganda, trailers < 100 MB)
  4. Baixa a legenda pt-BR que faltar

FASE 2 (novas melhorias):
  1. Avisa o Jellyfin para escanear a biblioteca (POST /Library/Refresh)
  2. Pôster em pt-BR e backdrop em alta resolução pelo TMDB (se o torrent não trouxe)
  3. Arquivo 'Nome do Filme (Ano).nfo' com título, ano, sinopse em português e duração
  4. Log em jellyfin_organizer.log + aviso no Discord e/ou Telegram

Uso:
  python organizar_jellyfin.py                         # SIMULAÇÃO: mostra o que faria
  python organizar_jellyfin.py --aplicar               # faz de verdade
  python organizar_jellyfin.py --completar-biblioteca  # só baixa o que falta (pôster, .nfo, legenda)
                                                       # nos filmes que JÁ estão organizados
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# =============================================================================================
#                                    CONFIGURAÇÕES
# Preencha aqui OU crie variáveis de ambiente com o MESMO nome (recomendado para tokens/chaves:
# assim eles não ficam escritos no arquivo e não vão parar no GitHub por engano).
# =============================================================================================
PASTA_ENTRADA = r"C:\Users\Voce\Downloads"        # onde estão os arquivos bagunçados
PASTA_FILMES = r"E:\Filmes_Organizados"           # biblioteca de Filmes do Jellyfin (pode ser a mesma)
MODO = "filmes"                                   # "filmes" ou "series"
APLICAR = False                                   # False = só simula (mude para True ou use --aplicar)
APAGAR_LIXO = True                                # .url, .txt de propaganda e trailers pequenos
APAGAR_PASTA_ORIGEM = False                       # apagar a pasta do torrent inteira depois de transferir
LIMITE_TRAILER_MB = 100

# TMDB (nomes corretos, pôster pt-BR, backdrop, sinopse): https://www.themoviedb.org/settings/api
TMDB_API_KEY = ""
NOMES_EPISODIOS = True                            # séries: "Dark S01E01 - Segredos.mkv" (precisa do TMDB)
BAIXAR_IMAGENS_TMDB = True
GERAR_NFO = True

# Legendas: use UMA ou mais fontes. Ficam vazias = não busca legenda.
IDIOMAS_LEGENDA = "pt-BR"                         # um ou vários: "pt-BR, en, es" (um .srt por idioma)
OPENSUBTITLES_API_KEY = ""                        # https://www.opensubtitles.com/consumers
SITE_LEGENDAS_URL = ""                            # ex.: "https://site/busca?q={consulta}" (que permita robôs)
USAR_SITE_DEMO_LEGENDAS = False                   # site SIMULADO local, só para testar

# Jellyfin: Painel -> Avançado -> Chaves de API
JELLYFIN_URL = "http://localhost:8096"
JELLYFIN_API_KEY = ""

# Notificações (opcionais)
DISCORD_WEBHOOK_URL = ""
TELEGRAM_BOT_TOKEN = ""
TELEGRAM_CHAT_ID = ""
NOTIFICAR_CADA_FILME_ATE = 10                     # acima disso, manda um resumo só (evita spam)

ARQUIVO_LOG = "jellyfin_organizer.log"
TRABALHOS_SIMULTANEOS = 4                         # filmes processados ao mesmo tempo (TMDB/legendas)
# =============================================================================================

from jellyfin_tools import (CatalogoEmCadeia, CatalogoLocal, CatalogoTMDB, ConfigSite,  # noqa: E402
                            ProvedorOpenSubtitles, ProvedorSiteHTML, organizar_pasta)
from jellyfin_tools.metadados import ClienteTMDB  # noqa: E402
from jellyfin_tools.notificacoes import Notificador  # noqa: E402
from jellyfin_tools.pos_processamento import (ConfigPos, itens_da_biblioteca, itens_de_series,  # noqa: E402
                                              pos_processar)
from jellyfin_tools.registro import configurar_log  # noqa: E402
from jellyfin_tools.site_demo import iniciar_site_demo  # noqa: E402

NIVEL_POR_STATUS = {"movido": "info", "simulado": "info", "organizado": "info", "ignorado": "info",
                    "conflito": "warning", "nao_identificado": "warning", "erro": "error"}


def cfg(nome: str):
    """Valor da configuração: a variável de ambiente (se existir) vence o valor escrito no topo."""
    padrao = globals()[nome]
    valor = os.environ.get(nome)
    if valor is None:
        return padrao
    if isinstance(padrao, bool):
        return valor.strip().lower() in ("1", "true", "sim", "yes")
    if isinstance(padrao, (int, float)) and not isinstance(padrao, bool):
        return type(padrao)(valor)
    return valor


# ----------------------------------------------------------------------------- montagem
def montar_catalogo():
    local = CatalogoLocal.padrao()
    # Com chave, o TMDB vem primeiro (fonte oficial); o catálogo local fica de reserva (sem internet).
    return CatalogoEmCadeia(CatalogoTMDB(cfg("TMDB_API_KEY")), local) if cfg("TMDB_API_KEY") else local


def montar_provedores_legenda(log) -> tuple[list, list]:
    """Devolve (provedores, servidores para desligar no fim)."""
    provedores, desligar = [], []
    if cfg("OPENSUBTITLES_API_KEY"):
        provedores.append(ProvedorOpenSubtitles(cfg("OPENSUBTITLES_API_KEY")))
    if cfg("SITE_LEGENDAS_URL"):
        provedores.append(ProvedorSiteHTML(ConfigSite(cfg("SITE_LEGENDAS_URL"))))
    if cfg("USAR_SITE_DEMO_LEGENDAS"):
        servidor, base = iniciar_site_demo()
        desligar.append(servidor)
        provedor = ProvedorSiteHTML(ConfigSite(f"{base}/busca?q={{consulta}}", nome="site demo"))
        provedor.cliente.espera = 0                    # é local: não precisa de pausa entre pedidos
        provedores.append(provedor)
    if not provedores:
        log.info("Legendas: nenhuma fonte configurada (OPENSUBTITLES_API_KEY / SITE_LEGENDAS_URL)")
    return provedores, desligar


# ----------------------------------------------------------------------------- pós-processamento
def montar_config_pos(log, notificar: bool = True) -> tuple[ConfigPos, list]:
    """Junta as configurações do topo num ConfigPos (legendas, TMDB, avisos, Jellyfin)."""
    tmdb = ClienteTMDB(cfg("TMDB_API_KEY")) if cfg("TMDB_API_KEY") else None
    if tmdb is None:
        log.info("TMDB_API_KEY vazio: pôster, backdrop e .nfo do TMDB não serão baixados")
    provedores, desligar = montar_provedores_legenda(log)
    config = ConfigPos(provedores=provedores, idioma=cfg("IDIOMAS_LEGENDA"), tmdb=tmdb,
                       imagens=cfg("BAIXAR_IMAGENS_TMDB"), nfo=cfg("GERAR_NFO"),
                       notificador=Notificador(cfg("DISCORD_WEBHOOK_URL"), cfg("TELEGRAM_BOT_TOKEN"),
                                               cfg("TELEGRAM_CHAT_ID")),
                       notificar=notificar, limite_avisos=cfg("NOTIFICAR_CADA_FILME_ATE"),
                       jellyfin_url=cfg("JELLYFIN_URL"), jellyfin_api_key=cfg("JELLYFIN_API_KEY"),
                       trabalhadores=cfg("TRABALHOS_SIMULTANEOS"))
    return config, desligar


def pos_processar_lote(itens, log, notificar: bool = True) -> list:
    config, desligar = montar_config_pos(log, notificar)
    try:
        return pos_processar(itens, config, log)
    finally:
        for servidor in desligar:
            servidor.shutdown()


# ----------------------------------------------------------------------------- fluxo principal
def organizar(aplicar: bool, log) -> int:
    entrada, filmes = Path(cfg("PASTA_ENTRADA")).expanduser(), Path(cfg("PASTA_FILMES")).expanduser()
    if not entrada.is_dir():
        log.critical("PASTA_ENTRADA não existe: %s", entrada)
        return 1
    log.info("=== Início (%s) | %s -> %s | modo %s ===", "APLICANDO" if aplicar else "SIMULAÇÃO",
             entrada, filmes, cfg("MODO"))
    try:
        movimentos = organizar_pasta(entrada, filmes, montar_catalogo(), aplicar=aplicar, modo=cfg("MODO"),
                                     limpar_lixo=cfg("APAGAR_LIXO"), limite_trailer_mb=cfg("LIMITE_TRAILER_MB"),
                                     apagar_pasta_origem=cfg("APAGAR_PASTA_ORIGEM"),
                                     nomes_episodios=cfg("NOMES_EPISODIOS"))
    except Exception as erro:
        log.critical("Falha ao organizar a pasta: %s", erro, exc_info=True)
        return 1
    for m in movimentos:
        getattr(log, NIVEL_POR_STATUS.get(m.status, "info"))("%s", m)
        for lixo in (m.apagar or []) if m.status in ("movido", "simulado") else []:
            log.info("    %s: %s", "apagado" if aplicar else "seria apagado", lixo.name)
        if m.pasta_apagar:
            log.info("    pasta de origem %s: %s", "apagada" if aplicar and not m.pasta_apagar.exists()
                     else "seria apagada" if not aplicar else "mantida", m.pasta_apagar)
    if not aplicar:
        log.info("Simulação concluída: nada foi movido. Rode com --aplicar (ou APLICAR = True).")
        return 0

    movidos = [m for m in movimentos if m.status == "movido"]
    novos = pos_processar_lote([(m, m.destino.stem) for m in movidos], log)
    erros = sum(m.status == "erro" for m in movimentos)
    log.info("=== Fim: %d movido(s), %d com erro, %d processado(s) ===", len(movidos), erros, len(novos))
    return 1 if erros else 0


def completar_biblioteca(log) -> int:
    """Para filmes JÁ organizados: baixa só o que falta (legenda, pôster, backdrop, .nfo)."""
    filmes = Path(cfg("PASTA_FILMES")).expanduser()
    if not filmes.is_dir():
        log.critical("PASTA_FILMES não existe: %s", filmes)
        return 1
    if cfg("MODO") == "series":                     # episódios: legendas (o Jellyfin cuida dos metadados)
        itens = itens_de_series(filmes, montar_catalogo(), log)
    else:
        itens = itens_da_biblioteca(filmes, log)
    log.info("=== Completar biblioteca: %d item(ns) em %s ===", len(itens), filmes)
    resultados = pos_processar_lote(itens, log, notificar=False)
    log.info("=== Fim: %d filme(s) verificados ===", len(resultados))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Organiza filmes para o Jellyfin (veja as CONFIGURAÇÕES no topo).")
    ap.add_argument("--aplicar", action="store_true", help="mover de verdade (sem isso, só simula)")
    ap.add_argument("--completar-biblioteca", action="store_true",
                    help="não move nada: completa legenda/pôster/.nfo dos filmes já organizados")
    ap.add_argument("--entrada", help="sobrescreve PASTA_ENTRADA")
    ap.add_argument("--filmes", help="sobrescreve PASTA_FILMES")
    args = ap.parse_args(argv)
    if args.entrada:
        os.environ["PASTA_ENTRADA"] = args.entrada
    if args.filmes:
        os.environ["PASTA_FILMES"] = args.filmes

    log = configurar_log(cfg("ARQUIVO_LOG"))
    try:
        if args.completar_biblioteca:
            return completar_biblioteca(log)
        return organizar(args.aplicar or cfg("APLICAR"), log)
    except KeyboardInterrupt:
        log.warning("Interrompido pelo usuário")
        return 130
    except Exception as erro:                       # último recurso: registra e sai com código de erro
        log.critical("Erro inesperado: %s", erro, exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
