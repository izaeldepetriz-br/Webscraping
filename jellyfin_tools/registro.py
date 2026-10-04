"""Melhoria 4a: log detalhado em arquivo (jellyfin_organizer.log) com a biblioteca `logging`.

Cada linha: data | nível | mensagem. Níveis: INFO (sucesso), WARNING (aviso), ERROR (falha
de um filme, o processamento segue) e CRITICAL (falha que impede o processo inteiro).
O arquivo "gira" ao chegar em 5 MB (guarda os 3 últimos), para nunca encher o disco.

Além do log geral, cada AÇÃO (Pré-visualizar, Organizar, Completar...) grava também um arquivo só
dela em logs/ ('2026-10-04_13-24-05_Organizando.log'): é esse que o botão "Abrir log" abre.
Ficam os ACOES_GUARDADAS mais recentes.
"""

from __future__ import annotations

import logging
import re
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

NOME_LOGGER = "jellyfin_organizer"
FORMATO = logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s", "%Y-%m-%d %H:%M:%S")
ACOES_GUARDADAS = 200


def configurar_log(arquivo: str | Path = "jellyfin_organizer.log", nivel: int = logging.INFO,
                   no_terminal: bool = True) -> logging.Logger:
    """Cria (ou reconfigura) o logger do organizador. Pode ser chamada mais de uma vez."""
    logger = logging.getLogger(NOME_LOGGER)
    logger.setLevel(logging.DEBUG)
    for handler in list(logger.handlers):             # evita linhas duplicadas se chamar de novo
        logger.removeHandler(handler)
        handler.close()
    formato = FORMATO

    caminho = Path(arquivo)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    arquivo_log = RotatingFileHandler(caminho, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    arquivo_log.setFormatter(formato)
    arquivo_log.setLevel(logging.DEBUG)               # no arquivo vai tudo, inclusive detalhes
    logger.addHandler(arquivo_log)

    if no_terminal and sys.stderr is not None:
        terminal = logging.StreamHandler(sys.stderr)
        terminal.setFormatter(logging.Formatter("%(levelname)-8s %(message)s"))
        terminal.setLevel(nivel)
        logger.addHandler(terminal)
    logger.propagate = False
    return logger


def obter_logger() -> logging.Logger:
    return logging.getLogger(NOME_LOGGER)


def iniciar_log_da_acao(acao: str, pasta: str | Path) -> tuple[logging.Handler, Path]:
    """Passa a gravar TAMBÉM num arquivo só desta ação: <pasta>/2026-10-04_13-24-05_Organizando.log.
    Devolve (handler, caminho); chame encerrar_log_da_acao(handler) quando a ação terminar."""
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    nome = re.sub(r"[^\w-]+", "-", acao, flags=re.UNICODE).strip("-") or "acao"
    caminho = pasta / f"{datetime.now():%Y-%m-%d_%H-%M-%S}_{nome}.log"
    n = 2
    while caminho.exists():                           # duas ações no mesmo segundo
        caminho = caminho.with_name(f"{datetime.now():%Y-%m-%d_%H-%M-%S}_{nome}-{n}.log")
        n += 1
    handler = logging.FileHandler(caminho, encoding="utf-8")
    handler.setFormatter(FORMATO)
    handler.setLevel(logging.DEBUG)
    obter_logger().addHandler(handler)
    for antigo in sorted(pasta.glob("*.log"))[:-ACOES_GUARDADAS]:     # os mais antigos saem
        try:
            antigo.unlink()
        except OSError:
            pass
    return handler, caminho


def encerrar_log_da_acao(handler: logging.Handler | None) -> None:
    if handler is not None:
        obter_logger().removeHandler(handler)
        handler.close()
