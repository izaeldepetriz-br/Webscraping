"""O que acontece com cada filme DEPOIS de organizado (usado pelo script e pela janela):

  1. legenda pt-BR, se ainda não houver          (legendas.py)
  2. poster.jpg / backdrop.jpg, se faltarem       (metadados.py, API do TMDB)
  3. Nome (Ano).nfo                               (metadados.py)
  4. aviso no Discord/Telegram                    (notificacoes.py)
  e, no fim do lote, UM scan da biblioteca        (servidor_jellyfin.py)

Cada filme roda dentro do próprio try/except: um erro vai para o log e o próximo segue.

Velocidade: quase todo o tempo é ESPERA pela internet. Por isso vários filmes são processados
ao mesmo tempo (ConfigPos.trabalhadores, padrão 4). As LEGENDAS continuam uma de cada vez
(trava), por educação com os sites de legenda, que bloqueiam muitos pedidos simultâneos.
Avisos e andamento saem na ordem dos filmes.
"""

from __future__ import annotations

import contextlib
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from .legendas import (ResultadoLegenda, baixar_legenda, baixar_legenda_episodio, normalizar_idiomas,
                       pastas_de_filmes)
from .metadados import ClienteTMDB, ResultadoMetadados, enriquecer_filme
from .nomes import eh_video, ler_nome_jellyfin
from .notificacoes import Notificador
from .registro import obter_logger
from .servidor_jellyfin import ErroJellyfin, atualizar_biblioteca


@dataclass
class ConfigPos:
    provedores: list = field(default_factory=list)       # fontes de legenda (vazio = não busca)
    idioma: str = "pt-BR"                                  # um idioma, ou vários: "pt-BR, en, es"
    idiomas: list | None = None                            # se preenchido, vale no lugar de `idioma`
    tmdb: ClienteTMDB | None = None                        # None = sem pôster/backdrop/.nfo
    imagens: bool = True
    nfo: bool = True
    notificador: Notificador | None = None
    notificar: bool = True
    limite_avisos: int = 10                                # acima disso, um resumo só
    jellyfin_url: str = ""
    jellyfin_api_key: str = ""                             # vazio = não pede o scan
    trabalhadores: int = 4                                 # filmes processados ao mesmo tempo


    @property
    def lista_idiomas(self) -> list[str]:
        return normalizar_idiomas(self.idiomas or self.idioma) or ["pt-BR"]


@dataclass
class ResultadoItem:
    nome: str
    legenda: ResultadoLegenda | None = None                # a do 1º idioma (o principal)
    legendas: dict = field(default_factory=dict)           # idioma -> ResultadoLegenda
    metadados: ResultadoMetadados | None = None
    erro: str = ""


@dataclass
class ItemBiblioteca:
    """Um filme que já está organizado (imita o Movimento que o organizador devolve)."""
    destino: Path
    filme: object = None
    episodio: tuple | None = None


def itens_da_biblioteca(pasta_filmes: Path, log=None) -> list[tuple[ItemBiblioteca, str]]:
    """Pastas 'Nome (Ano)' com vídeo dentro -> itens para pos_processar()."""
    log = log or obter_logger()
    itens = []
    for pasta in pastas_de_filmes(pasta_filmes):
        if not ler_nome_jellyfin(pasta.name):
            log.warning("Pasta fora do padrão 'Nome (Ano)', pulada: %s", pasta.name)
            continue
        videos = sorted(v for v in pasta.iterdir() if v.is_file() and eh_video(v))
        video = next((v for v in videos if v.stem == pasta.name), videos[0])   # o de mesmo nome da pasta
        itens.append((ItemBiblioteca(video), pasta.name))
    return itens


def processar_item(m, cfg: ConfigPos, log=None, trava_legendas=None) -> ResultadoItem:
    """Legenda + metadados de UM filme. Cada etapa tem o próprio try/except.
    `trava_legendas`: com vários filmes ao mesmo tempo, só um busca legenda por vez."""
    log = log or obter_logger()
    pasta, nome_base = m.destino.parent, m.destino.stem
    resultado = ResultadoItem(nome_base)
    originais = [m.filme.titulo_original] if m.filme and getattr(m.filme, "titulo_original", "") else []

    if cfg.provedores:
        for idioma in cfg.lista_idiomas:                       # um arquivo por idioma
            try:
                with trava_legendas or contextlib.nullcontext():
                    r = _legenda(m, cfg, pasta, originais, idioma)
                resultado.legendas[idioma] = r
                resultado.legenda = resultado.legenda or r
                nivel = log.info if r.status in ("baixada", "ja_existe") else log.warning
                nivel("Legenda %s de %s: %s%s", idioma, nome_base, r.status, f" ({r.detalhe})" if r.detalhe else "")
            except Exception as erro:
                log.error("Legenda %s de %s falhou: %s", idioma, nome_base, erro, exc_info=True)
                resultado.erro = str(erro)

    if cfg.tmdb is not None and not m.episodio and (cfg.imagens or cfg.nfo):   # séries: o Jellyfin cuida
        lido = ler_nome_jellyfin(pasta.name)
        if m.filme:
            titulo, ano, tmdb_id = m.filme.titulo, m.filme.ano, m.filme.tmdb_id
        else:
            titulo, ano, tmdb_id = (lido.titulo, lido.ano, None) if lido else (nome_base, None, None)
        try:
            resultado.metadados = enriquecer_filme(pasta, nome_base, cfg.tmdb, titulo, ano, tmdb_id,
                                                   imagens=cfg.imagens, nfo=cfg.nfo)
        except Exception as erro:
            log.error("Metadados de %s falharam: %s", nome_base, erro, exc_info=True)
            resultado.erro = str(erro)
    return resultado


def _legenda(m, cfg: ConfigPos, pasta: Path, originais: list[str], idioma: str) -> ResultadoLegenda:
    if m.episodio:
        return baixar_legenda_episodio(m.destino, cfg.provedores, idioma=idioma, titulos_alternativos=originais)
    return baixar_legenda(pasta, cfg.provedores, idioma=idioma, titulos_alternativos=originais)


def pos_processar(itens: list, cfg: ConfigPos, log=None, ao_item=None, parar=None) -> list[ResultadoItem]:
    """Processa todos os itens [(movimento, nome)], avisa e pede UM scan ao Jellyfin no fim.
    ao_item(indice, resultado) mostra o andamento; parar() devolvendo True interrompe."""
    log = log or obter_logger()
    resultados: list[ResultadoItem] = []
    avisos = cfg.notificador if (cfg.notificar and cfg.notificador and cfg.notificador.ativo) else None
    trava_legendas = threading.Lock()

    def tarefa(m, nome):
        if parar and parar():
            return None                                        # interrompido: nem começa
        try:
            resultado = processar_item(m, cfg, log, trava_legendas)
            log.info("Processado: %s", nome)
            return resultado
        except Exception as erro:                              # segue para o próximo filme
            log.error("Erro ao processar %s: %s", nome, erro, exc_info=True)
            return ResultadoItem(nome, erro=str(erro))

    with ThreadPoolExecutor(max_workers=max(1, cfg.trabalhadores)) as executor:
        futuros = [executor.submit(tarefa, m, nome) for m, nome in itens]
        for indice, futuro in enumerate(futuros):              # na ordem dos filmes
            resultado = futuro.result()
            if resultado is None:
                continue
            if avisos and len(resultados) < cfg.limite_avisos:     # o filme foi organizado: avisa
                avisos.novo_filme(itens[indice][1])
            resultados.append(resultado)
            if ao_item:
                ao_item(indice, resultado)
    if parar and parar():
        log.warning("Interrompido pelo usuário depois de %d item(ns)", len(resultados))

    nomes = [r.nome for r in resultados]
    if avisos and len(nomes) > cfg.limite_avisos:
        avisos.resumo(nomes, cfg.limite_avisos)
    if nomes and cfg.jellyfin_api_key:
        try:
            atualizar_biblioteca(cfg.jellyfin_url, cfg.jellyfin_api_key)
        except ErroJellyfin as erro:
            log.error("Scan do Jellyfin não disparado: %s", erro)
    elif nomes:
        log.info("Sem chave do Jellyfin: faça o scan da biblioteca pelo painel do Jellyfin")
    return resultados
