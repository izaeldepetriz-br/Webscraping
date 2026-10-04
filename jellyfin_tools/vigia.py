"""Pasta vigiada: organizar sozinho o que TERMINOU de baixar.

Um vídeo está pronto quando:
  - não muda há `espera` segundos (o programa de download não está mais escrevendo nele); e
  - não há, na mesma pasta, marca de download em andamento (.part, .!qB, .crdownload...).
Dica para o qBittorrent: em Opções > Downloads, marque "Acrescentar a extensão .!qB a arquivos
incompletos" (assim um download PAUSADO também não é confundido com um terminado).

A organização usa as mesmas regras (nunca sobrescreve, grava o log para o 'Desfazer última').
"""

from __future__ import annotations

import os
import time
from pathlib import Path

MARCAS_INCOMPLETO = {".part", ".!qb", ".!ut", ".crdownload", ".tmp", ".partial", ".download", ".aria2",
                     ".bc!", ".opdownload", ".xltd"}
ESPERA_PADRAO = 120          # segundos sem mudar para considerar "terminado"


def download_em_andamento(pasta: Path) -> bool:
    try:
        with os.scandir(pasta) as itens:
            return any(Path(i.name).suffix.lower() in MARCAS_INCOMPLETO for i in itens)
    except OSError:
        return False


def pronto(video: Path, espera: float = ESPERA_PADRAO, agora: float | None = None) -> bool:
    """O vídeo terminou de baixar? (parado há `espera` s e sem download em andamento na pasta)."""
    try:
        idade = (agora if agora is not None else time.time()) - video.stat().st_mtime
    except OSError:
        return False
    return idade >= espera and not download_em_andamento(video.parent)


def filtro_prontos(espera: float = ESPERA_PADRAO):
    """Para organizar_pasta(filtro=...): só os vídeos que já terminaram de baixar."""
    pastas_ocupadas: dict[Path, bool] = {}
    agora = time.time()

    def filtro(video: Path) -> bool:
        if video.parent not in pastas_ocupadas:
            pastas_ocupadas[video.parent] = download_em_andamento(video.parent)
        if pastas_ocupadas[video.parent]:
            return False
        try:
            return agora - video.stat().st_mtime >= espera
        except OSError:
            return False
    return filtro
