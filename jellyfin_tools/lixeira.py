"""A "lixeira" do organizador: <biblioteca>/.organizador/removidos/<data>/...

O que sai num "Resolver conflitos" (a cópia pior) ou num "remover espelho" não é apagado na hora: vai para
essa pasta, e o "Desfazer" põe de volta. Só que ela só crescia. Aqui: achar os lotes com mais de N dias e
apagá-los de vez (o programa pergunta antes; depois disso o "Desfazer" daquele lote não funciona mais).
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from .organizador import PASTA_LOGS

DIAS_PADRAO = 30


@dataclass
class LoteRemovido:
    pasta: Path
    data: datetime
    tamanho: int                 # bytes


def _data_do_lote(pasta: Path) -> datetime:
    """O nome da pasta é a data ('20260905-101500-123456'); sem isso, a data da própria pasta."""
    try:
        return datetime.strptime(pasta.name[:15], "%Y%m%d-%H%M%S")
    except ValueError:
        return datetime.fromtimestamp(pasta.stat().st_mtime)


def _tamanho(pasta: Path) -> int:
    total = 0
    for raiz, _, arquivos in os.walk(pasta):
        for nome in arquivos:
            try:
                total += (Path(raiz) / nome).stat().st_size
            except OSError:
                pass
    return total


def lotes_antigos(raizes, dias: int = DIAS_PADRAO, agora: datetime | None = None) -> list[LoteRemovido]:
    """Os lotes com mais de `dias` dias em <raiz>/.organizador/removidos de cada raiz (sem repetir)."""
    limite = (agora or datetime.now()) - timedelta(days=dias)
    vistos, lotes = set(), []
    for raiz in raizes:
        if not raiz:
            continue
        base = Path(raiz) / PASTA_LOGS / "removidos"
        try:
            pastas = sorted(p for p in base.iterdir() if p.is_dir())
        except OSError:
            continue
        for pasta in pastas:
            chave = os.path.normcase(str(pasta.resolve()))
            if chave in vistos:
                continue
            vistos.add(chave)
            data = _data_do_lote(pasta)
            if data < limite:
                lotes.append(LoteRemovido(pasta, data, _tamanho(pasta)))
    return lotes


def apagar_lotes(lotes: list[LoteRemovido]) -> tuple[int, list[str]]:
    """Apaga de vez. Devolve (quantos apagados, erros)."""
    apagados, erros = 0, []
    for lote in lotes:
        try:
            shutil.rmtree(lote.pasta)
            apagados += 1
        except OSError as erro:
            erros.append(f"{lote.pasta}: {erro}")
    return apagados, erros


def tamanho_legivel(total: int) -> str:
    return f"{total / 1024 ** 3:.1f} GB" if total >= 1024 ** 3 else f"{total / 1024 ** 2:.0f} MB"
