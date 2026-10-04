"""Relatório da biblioteca: o que está faltando.

  Filmes: legenda em cada idioma escolhido e pôster (poster.jpg/folder.jpg na pasta do filme).
  Séries: episódios faltando (buracos na numeração: "Dark (2017) S02: falta E05") e, com o TMDB,
          também o fim da temporada e temporadas inteiras; e episódios sem legenda.

Complementa o Sonarr (que já acompanha episódios): olha também legendas, pôsteres e os .strm.
Vale para vídeos baixados e para os .strm do espelho.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .extras import EXTENSOES_LEGENDA
from .nomes import eh_video_da_biblioteca, extrair_episodio, ler_nome_jellyfin
from .registro import obter_logger

IMAGENS_POSTER = ("poster", "folder", "cover")


@dataclass
class Pendencia:
    tipo: str          # "filme" | "serie"
    item: str          # "Matrix (1999)" ou "Dark (2017) S02"
    falta: str         # "legenda pt-BR", "pôster", "episódios", "temporada inteira"
    detalhe: str       # "E05, E07–E09"
    pasta: Path


def faixas(numeros) -> str:
    """[5, 7, 8, 9, 12] -> 'E05, E07–E09, E12'."""
    numeros = sorted(set(numeros))
    partes, i = [], 0
    while i < len(numeros):
        j = i
        while j + 1 < len(numeros) and numeros[j + 1] == numeros[j] + 1:
            j += 1
        partes.append(f"E{numeros[i]:02d}" + (f"–E{numeros[j]:02d}" if j > i else ""))
        i = j + 1
    return ", ".join(partes)


def _tem_legenda(video: Path, idioma: str, arquivos: list[Path]) -> bool:
    """'Nome.pt-BR.srt' (ou .ass/.vtt...); a .forced não conta (só traduz as falas em outra língua)."""
    prefixo = f"{video.stem}.{idioma}.".lower()
    return any(a.name.lower().startswith(prefixo) and a.suffix.lower() in EXTENSOES_LEGENDA
               and ".forced." not in a.name.lower() for a in arquivos)


def _arquivos(pasta: Path) -> list[Path]:
    try:
        return [a for a in pasta.iterdir() if a.is_file()]
    except OSError:
        return []


def relatorio_filmes(pasta_filmes: str | Path, idiomas: list[str]) -> list[Pendencia]:
    pendencias = []
    for pasta in sorted(p for p in Path(pasta_filmes).iterdir() if p.is_dir() and not p.name.startswith(".")):
        arquivos = _arquivos(pasta)
        videos = sorted(a for a in arquivos if eh_video_da_biblioteca(a))
        if not videos:
            continue
        video = next((v for v in videos if v.stem == pasta.name), videos[0])
        for idioma in idiomas:
            if not _tem_legenda(video, idioma, arquivos):
                pendencias.append(Pendencia("filme", pasta.name, f"legenda {idioma}", video.name, pasta))
        if not any(a.stem.lower() in IMAGENS_POSTER or a.stem.lower().endswith("-poster")
                   for a in arquivos if a.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")):
            pendencias.append(Pendencia("filme", pasta.name, "pôster", "sem poster.jpg na pasta", pasta))
    return pendencias


def relatorio_series(pasta_series: str | Path, idiomas: list[str], catalogo=None) -> list[Pendencia]:
    """Buracos na numeração de cada temporada e episódios sem legenda. Com `catalogo` (TMDB), compara
    com a quantidade de episódios de cada temporada (o fim da temporada e temporadas inteiras)."""
    log = obter_logger()
    pendencias = []
    for pasta_serie in sorted(p for p in Path(pasta_series).iterdir() if p.is_dir() and not p.name.startswith(".")):
        episodios: dict[int, dict[int, Path]] = {}
        for video in pasta_serie.rglob("*"):
            if video.is_file() and eh_video_da_biblioteca(video) and (ep := extrair_episodio(video.name)):
                episodios.setdefault(ep.temporada, {})[ep.episodio] = video
        if not episodios:
            continue
        esperados: dict[int, int] = {}
        lido = ler_nome_jellyfin(pasta_serie.name)
        if catalogo is not None and lido:
            try:
                serie = catalogo.buscar(lido.titulo, lido.ano, "serie")
                esperados = dict(getattr(catalogo, "temporadas", lambda s: None)(serie) or []) if serie else {}
            except Exception as erro:             # TMDB fora do ar: fica só a conferência local
                log.warning("Relatório: TMDB indisponível para %s: %s", pasta_serie.name, erro)
        for temporada in sorted(set(episodios) | {t for t, n in esperados.items() if n > 0}):
            item = f"{pasta_serie.name} S{temporada:02d}"
            presentes = episodios.get(temporada, {})
            if not presentes:
                pendencias.append(Pendencia("serie", item, "temporada inteira",
                                            f"{esperados[temporada]} episódio(s) no TMDB", pasta_serie))
                continue
            ultimo = max(esperados.get(temporada, 0), max(presentes))
            faltando = [n for n in range(1, ultimo + 1) if n not in presentes]
            if faltando:
                pendencias.append(Pendencia("serie", item, "episódios", faixas(faltando), pasta_serie))
            pastas = {v.parent: _arquivos(v.parent) for v in presentes.values()}   # cada pasta lida uma vez
            for idioma in idiomas:
                sem = [n for n, video in presentes.items() if not _tem_legenda(video, idioma, pastas[video.parent])]
                if sem:
                    pendencias.append(Pendencia("serie", item, f"legenda {idioma}",
                                                f"{len(sem)} episódio(s): {faixas(sem)}", pasta_serie))
    return pendencias


def gerar_relatorio(pasta_filmes=None, pasta_series=None, idiomas=("pt-BR",), catalogo=None) -> list[Pendencia]:
    pendencias = []
    if pasta_filmes and Path(pasta_filmes).is_dir():
        pendencias += relatorio_filmes(pasta_filmes, list(idiomas))
    if pasta_series and Path(pasta_series).is_dir():
        pendencias += relatorio_series(pasta_series, list(idiomas), catalogo)
    return pendencias


def resumo(pendencias: list[Pendencia]) -> str:
    """'3 filme(s) sem legenda pt-BR; 1 sem pôster; 2 temporada(s) com episódios faltando...'"""
    contagem: dict[str, int] = {}
    for p in pendencias:
        chave = f"{'filme(s)' if p.tipo == 'filme' else 'temporada(s)'} – falta {p.falta}"
        contagem[chave] = contagem.get(chave, 0) + 1
    return "; ".join(f"{n} {c}" for c, n in sorted(contagem.items())) or "nada faltando"


def salvar_csv(pendencias: list[Pendencia], pasta: str | Path) -> Path:
    """relatorio-2026-10-04_19-30.csv (abre no Excel com acentos)."""
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    arquivo = pasta / f"relatorio-{datetime.now():%Y-%m-%d_%H-%M-%S}.csv"
    with open(arquivo, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["tipo", "item", "falta", "detalhe", "pasta"])
        for p in pendencias:
            w.writerow([p.tipo, p.item, p.falta, p.detalhe, str(p.pasta)])
    return arquivo
