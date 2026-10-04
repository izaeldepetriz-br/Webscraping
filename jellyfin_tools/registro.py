"""Melhoria 4a: log detalhado em arquivo (jellyfin_organizer.log) com a biblioteca `logging`.

Cada linha: data | nível | mensagem. Níveis: INFO (sucesso), WARNING (aviso), ERROR (falha
de um filme, o processamento segue) e CRITICAL (falha que impede o processo inteiro).
O arquivo "gira" ao chegar em 5 MB (guarda os 3 últimos), para nunca encher o disco.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

NOME_LOGGER = "jellyfin_organizer"


def configurar_log(arquivo: str | Path = "jellyfin_organizer.log", nivel: int = logging.INFO,
                   no_terminal: bool = True) -> logging.Logger:
    """Cria (ou reconfigura) o logger do organizador. Pode ser chamada mais de uma vez."""
    logger = logging.getLogger(NOME_LOGGER)
    logger.setLevel(logging.DEBUG)
    for handler in list(logger.handlers):             # evita linhas duplicadas se chamar de novo
        logger.removeHandler(handler)
        handler.close()
    formato = logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s", "%Y-%m-%d %H:%M:%S")

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
