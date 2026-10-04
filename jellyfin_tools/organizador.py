"""Move e renomeia vídeos para o padrão de filmes do Jellyfin:

    <pasta_filmes>/Nome do Filme (Ano)/Nome do Filme (Ano).ext

Segurança:
  - Por padrão só SIMULA (aplicar=False): mostra o que faria, sem mexer em nada.
  - Nunca sobrescreve: se o destino já existe, o arquivo fica onde está (status 'conflito').
  - Ao aplicar, grava um log JSON; desfazer(log) devolve tudo para o lugar original.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .catalogo import Catalogo, ErroCatalogo, Filme
from .nomes import (EXTENSOES_ACOMPANHANTES, eh_video, extrair_titulo_e_ano, formatar_titulo,
                    nome_jellyfin, normalizar)

PASTA_LOGS = ".organizador"


@dataclass
class Movimento:
    origem: Path
    destino: Path | None
    status: str          # simulado | movido | conflito | nao_identificado | ignorado | erro
    detalhe: str = ""
    filme: Filme | None = None
    acompanhantes: list[tuple[Path, Path]] | None = None   # legendas/nfo que vão junto

    def __str__(self) -> str:
        # Mostra só "Pasta do Filme/arquivo.ext", que é o que interessa.
        destino = f" -> {self.destino.parent.name}/{self.destino.name}" if self.destino else ""
        detalhe = f" ({self.detalhe})" if self.detalhe else ""
        return f"[{self.status}] {self.origem.name}{destino}{detalhe}"


def _acompanhantes(video: Path, novo_nome: str, pasta_destino: Path) -> list[tuple[Path, Path]]:
    """'Matrix.1999.x264.pt-BR.srt' (ao lado de 'Matrix.1999.x264.mp4') -> 'Matrix (1999).pt-BR.srt'."""
    pares = []
    for irmao in video.parent.iterdir():
        if (irmao.is_file() and irmao != video and irmao.suffix.lower() in EXTENSOES_ACOMPANHANTES
                and irmao.name.startswith(video.stem + ".")):
            resto = irmao.name[len(video.stem):]          # ex.: ".pt-BR.srt"
            pares.append((irmao, pasta_destino / f"{novo_nome}{resto}"))
    return pares


def planejar(video: Path, pasta_filmes: Path, catalogo: Catalogo | None = None,
             incluir_tmdbid: bool = False, exigir_catalogo: bool = False) -> Movimento:
    """Decide PARA ONDE o vídeo vai, sem mover nada."""
    if "sample" in normalizar(video.stem).split():
        return Movimento(video, None, "ignorado", "arquivo de amostra (sample)")

    extraido = extrair_titulo_e_ano(video.name)
    filme, detalhe = None, ""
    if catalogo is not None:
        try:
            filme = catalogo.buscar(extraido.titulo, extraido.ano)
        except ErroCatalogo as erro:
            detalhe = f"catálogo indisponível: {erro}"
    if filme:
        titulo, ano = filme.titulo, filme.ano
    elif exigir_catalogo:
        return Movimento(video, None, "nao_identificado",
                         detalhe or f"'{extraido.titulo}' ({extraido.ano}) não encontrado no catálogo")
    elif extraido.titulo and extraido.ano:
        titulo, ano = formatar_titulo(extraido.titulo), extraido.ano
        detalhe = detalhe or "não confirmado no catálogo: confira o nome"
    else:
        return Movimento(video, None, "nao_identificado",
                         detalhe or "não achei o ano no nome; renomeie à mão ou use o TMDB")

    nome = nome_jellyfin(titulo, ano, filme.tmdb_id if filme else None, incluir_tmdbid)
    pasta = pasta_filmes / nome
    destino = pasta / f"{nome}{video.suffix.lower()}"
    mov = Movimento(video, destino, "simulado", detalhe, filme, _acompanhantes(video, nome, pasta))
    if destino.exists() and destino.resolve() != video.resolve():
        mov.status, mov.detalhe = "conflito", "já existe um arquivo com esse nome no destino"
    return mov


def _listar_videos(origem: Path, pasta_filmes: Path, recursivo: bool) -> list[Path]:
    padrao = "**/*" if recursivo else "*"
    videos = []
    for arquivo in sorted(origem.glob(padrao)):
        if not arquivo.is_file() or not eh_video(arquivo):
            continue
        try:
            arquivo.resolve().relative_to(pasta_filmes.resolve())
            continue                     # já está dentro da biblioteca: não mexe
        except ValueError:
            videos.append(arquivo)
    return videos


def organizar_pasta(origem: str | Path, pasta_filmes: str | Path, catalogo: Catalogo | None = None,
                    aplicar: bool = False, recursivo: bool = True, incluir_tmdbid: bool = False,
                    exigir_catalogo: bool = False) -> list[Movimento]:
    """Organiza todos os vídeos de `origem` em `pasta_filmes`. Devolve o que fez (ou faria)."""
    origem, pasta_filmes = Path(origem).expanduser(), Path(pasta_filmes).expanduser()
    if not origem.is_dir():
        raise NotADirectoryError(f"pasta de origem não existe: {origem}")

    movimentos = [planejar(v, pasta_filmes, catalogo, incluir_tmdbid, exigir_catalogo)
                  for v in _listar_videos(origem, pasta_filmes, recursivo)]
    _marcar_destinos_repetidos(movimentos)
    if not aplicar:
        return movimentos

    feitos = []
    for mov in movimentos:
        if mov.status != "simulado":
            continue
        try:
            mov.destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(mov.origem), str(mov.destino))   # funciona até entre discos (C: -> D:)
            feitos.append((mov.origem, mov.destino))
            mov.status = "movido"
            for antigo, novo in mov.acompanhantes or []:
                if novo.exists():
                    continue
                shutil.move(str(antigo), str(novo))
                feitos.append((antigo, novo))
        except OSError as erro:                               # sem permissão, disco cheio, arquivo em uso...
            mov.status, mov.detalhe = "erro", str(erro)
    if feitos:
        _gravar_log(pasta_filmes, feitos)
    return movimentos


def _marcar_destinos_repetidos(movimentos: list[Movimento]) -> None:
    """Dois arquivos que virariam o mesmo nome (ex.: 2 cópias do Matrix): só o 1º vai."""
    vistos = set()
    for mov in movimentos:
        if mov.status != "simulado":
            continue
        chave = str(mov.destino).lower()
        if chave in vistos:
            mov.status, mov.detalhe = "conflito", "outro arquivo já vai para esse mesmo nome"
        vistos.add(chave)


def _gravar_log(pasta_filmes: Path, feitos: list[tuple[Path, Path]]) -> Path:
    pasta = pasta_filmes / PASTA_LOGS
    pasta.mkdir(parents=True, exist_ok=True)
    log = pasta / f"log-{datetime.now():%Y%m%d-%H%M%S-%f}.json"
    log.write_text(json.dumps([{"de": str(a), "para": str(b)} for a, b in feitos],
                              ensure_ascii=False, indent=2), encoding="utf-8")
    return log


def ultimo_log(pasta_filmes: str | Path) -> Path | None:
    logs = sorted((Path(pasta_filmes) / PASTA_LOGS).glob("log-*.json"))
    return logs[-1] if logs else None


def desfazer(log: str | Path) -> list[str]:
    """Devolve os arquivos de um log para onde estavam. Remove pastas que ficaram vazias."""
    log = Path(log)
    itens = json.loads(log.read_text(encoding="utf-8"))
    mensagens = []
    for item in reversed(itens):
        de, para = Path(item["de"]), Path(item["para"])
        if not para.exists():
            mensagens.append(f"não encontrado (já mexido?): {para}")
            continue
        if de.exists():
            mensagens.append(f"não desfeito, já existe: {de}")
            continue
        try:
            de.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(para), str(de))
            mensagens.append(f"voltou: {de}")
            if para.parent.exists():
                if not any(para.parent.iterdir()):
                    para.parent.rmdir()
                elif not any(Path(i["para"]).parent == para.parent and Path(i["para"]).exists() for i in itens):
                    mensagens.append(f"pasta mantida (tem arquivos que o organizador não moveu, "
                                     f"ex.: legenda baixada): {para.parent}")
        except OSError as erro:
            mensagens.append(f"erro em {para}: {erro}")
    log.rename(log.with_suffix(".desfeito.json"))
    return mensagens
