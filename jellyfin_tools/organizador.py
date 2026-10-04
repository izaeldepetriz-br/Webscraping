"""Move e renomeia vídeos para o padrão do Jellyfin:

    Filmes:  <pasta_filmes>/Nome do Filme (Ano)/Nome do Filme (Ano).ext
    Séries:  <pasta_series>/Nome da Série (Ano)/Season 01/Nome da Série S01E02.ext

A origem pode ser uma pasta separada (ex.: Downloads) OU a própria biblioteca: nesse caso
o que já está no padrão aparece como 'organizado' e fica onde está.

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
from .nomes import (EXTENSOES_ACOMPANHANTES, eh_video, extrair_episodio, extrair_titulo_e_ano,
                    formatar_titulo, nome_episodio_jellyfin, nome_jellyfin, normalizar, pasta_temporada)

PASTA_LOGS = ".organizador"
MODOS = ("filmes", "series")


@dataclass
class Movimento:
    origem: Path
    destino: Path | None
    status: str          # simulado | movido | organizado | conflito | nao_identificado | ignorado | erro
    detalhe: str = ""
    filme: Filme | None = None
    acompanhantes: list[tuple[Path, Path]] | None = None   # legendas/nfo que vão junto
    episodio: tuple[int, int] | None = None                # (temporada, episódio), só em séries

    def __str__(self) -> str:
        destino = f" -> {self.destino_curto}" if self.destino else ""
        detalhe = f" ({self.detalhe})" if self.detalhe else ""
        return f"[{self.status}] {self.origem.name}{destino}{detalhe}"

    @property
    def destino_curto(self) -> str:
        """Filmes: 'Matrix (1999)/Matrix (1999).mkv'.  Séries: 'Dark (2017)/Season 01/Dark S01E01.mkv'."""
        if not self.destino:
            return ""
        partes = self.destino.parts[-3:] if self.episodio else self.destino.parts[-2:]
        return "/".join(partes)


def _acompanhantes(video: Path, novo_nome: str, pasta_destino: Path) -> list[tuple[Path, Path]]:
    """'Matrix.1999.x264.pt-BR.srt' (ao lado de 'Matrix.1999.x264.mp4') -> 'Matrix (1999).pt-BR.srt'."""
    pares = []
    for irmao in video.parent.iterdir():
        if (irmao.is_file() and irmao != video and irmao.suffix.lower() in EXTENSOES_ACOMPANHANTES
                and irmao.name.startswith(video.stem + ".")):
            resto = irmao.name[len(video.stem):]          # ex.: ".pt-BR.srt"
            pares.append((irmao, pasta_destino / f"{novo_nome}{resto}"))
    return pares


def _consultar(catalogo: Catalogo | None, titulo: str, ano: int | None, tipo: str):
    """Devolve (Filme ou None, detalhe do erro)."""
    if catalogo is None:
        return None, ""
    try:
        return catalogo.buscar(titulo, ano, tipo), ""
    except ErroCatalogo as erro:
        return None, f"catálogo indisponível: {erro}"


def _finalizar(video: Path, pasta: Path, nome_arquivo: str, detalhe: str, filme, episodio=None) -> Movimento:
    destino = pasta / f"{nome_arquivo}{video.suffix.lower()}"
    if _mesmo_arquivo(destino, video):
        return Movimento(video, destino, "organizado", "já está no padrão do Jellyfin", filme, None, episodio)
    mov = Movimento(video, destino, "simulado", detalhe, filme, _acompanhantes(video, nome_arquivo, pasta),
                    episodio)
    if destino.exists() and not _mesmo_arquivo(destino, video):
        mov.status, mov.detalhe = "conflito", "já existe um arquivo com esse nome no destino"
    return mov


def planejar(video: Path, pasta_filmes: Path, catalogo: Catalogo | None = None,
             incluir_tmdbid: bool = False, exigir_catalogo: bool = False, modo: str = "filmes") -> Movimento:
    """Decide PARA ONDE o vídeo vai, sem mover nada."""
    if "sample" in normalizar(video.stem).split():
        return Movimento(video, None, "ignorado", "arquivo de amostra (sample)")
    if modo == "series":
        return _planejar_episodio(video, pasta_filmes, catalogo, incluir_tmdbid, exigir_catalogo)

    extraido = extrair_titulo_e_ano(video.name)
    filme, detalhe = _consultar(catalogo, extraido.titulo, extraido.ano, "filme")
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
    return _finalizar(video, pasta_filmes / nome, nome, detalhe, filme)


def _planejar_episodio(video: Path, pasta_series: Path, catalogo: Catalogo | None,
                       incluir_tmdbid: bool, exigir_catalogo: bool) -> Movimento:
    ep = extrair_episodio(video.name)
    if not ep:
        return Movimento(video, None, "nao_identificado",
                         "não achei temporada/episódio no nome (ex.: S01E02, 1x02, Episodio 3)")
    serie, detalhe = _consultar(catalogo, ep.serie, ep.ano, "serie")
    if serie:
        nome, ano = serie.titulo, serie.ano
    elif exigir_catalogo:
        return Movimento(video, None, "nao_identificado", detalhe or f"série '{ep.serie}' não está no catálogo")
    else:
        nome, ano = formatar_titulo(ep.serie), ep.ano
        detalhe = detalhe or "série não confirmada no catálogo: confira o nome"
    pasta_serie = pasta_series / nome_jellyfin(nome, ano, serie.tmdb_id if serie else None, incluir_tmdbid)
    pasta = pasta_serie / pasta_temporada(ep.temporada)
    return _finalizar(video, pasta, nome_episodio_jellyfin(nome, ep.temporada, ep.episodio), detalhe, serie,
                      (ep.temporada, ep.episodio))


def _mesmo_arquivo(a: Path, b: Path) -> bool:
    """Mesmo caminho? (no Windows, 'matrix (1999)' e 'Matrix (1999)' são a mesma pasta)"""
    try:
        return a.exists() and b.exists() and a.samefile(b)
    except OSError:
        return False


def _dentro(filho: Path, pai: Path) -> bool:
    try:
        filho.resolve().relative_to(pai.resolve())
        return True
    except ValueError:
        return False


def _listar_videos(origem: Path, pasta_filmes: Path, recursivo: bool) -> list[Path]:
    """Vídeos da origem. Se a origem fica FORA da biblioteca, o que estiver dentro da biblioteca
    é ignorado (ex.: origem E:/ e biblioteca E:/Filmes). Se a origem É a biblioteca (ou uma pasta
    dela), olha tudo: o que já estiver no padrão vira 'organizado' no planejar()."""
    no_lugar = _dentro(origem, pasta_filmes)
    padrao = "**/*" if recursivo else "*"
    videos = []
    for arquivo in sorted(origem.glob(padrao)):
        if not arquivo.is_file() or not eh_video(arquivo):
            continue
        if PASTA_LOGS in arquivo.relative_to(origem).parts:
            continue
        if not no_lugar and _dentro(arquivo, pasta_filmes):
            continue
        videos.append(arquivo)
    return videos


def _apagar_pastas_que_esvaziaram(pastas: set[Path], origem: Path) -> None:
    """Depois de mover, apaga as pastas de origem que ficaram vazias (ex.: 'Matrix.1999.1080p/').
    Só pastas DENTRO da origem e só se estiverem vazias; a própria origem nunca é apagada."""
    raiz = origem.resolve()
    for pasta in sorted(pastas, key=lambda p: len(p.parts), reverse=True):
        atual = pasta
        while atual.exists() and atual.resolve() != raiz and raiz in atual.resolve().parents:
            try:
                if any(atual.iterdir()):
                    break
                atual.rmdir()
            except OSError:
                break
            atual = atual.parent


def organizar_pasta(origem: str | Path, pasta_filmes: str | Path, catalogo: Catalogo | None = None,
                    aplicar: bool = False, recursivo: bool = True, incluir_tmdbid: bool = False,
                    exigir_catalogo: bool = False, modo: str = "filmes") -> list[Movimento]:
    """Organiza todos os vídeos de `origem` na biblioteca `pasta_filmes` (no modo "series",
    a pasta de séries do Jellyfin). Devolve o que fez (ou faria)."""
    if modo not in MODOS:
        raise ValueError(f"modo deve ser um de {MODOS}")
    origem, pasta_filmes = Path(origem).expanduser(), Path(pasta_filmes).expanduser()
    if not origem.is_dir():
        raise NotADirectoryError(f"pasta de origem não existe: {origem}")

    movimentos = [planejar(v, pasta_filmes, catalogo, incluir_tmdbid, exigir_catalogo, modo)
                  for v in _listar_videos(origem, pasta_filmes, recursivo)]
    _marcar_destinos_repetidos(movimentos)
    if not aplicar:
        return movimentos

    feitos = []
    pastas_de_onde_sairam: set[Path] = set()
    for mov in movimentos:
        if mov.status != "simulado":
            continue
        pastas_de_onde_sairam.add(mov.origem.parent)
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
        _apagar_pastas_que_esvaziaram(pastas_de_onde_sairam, origem)
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
    log.write_text(json.dumps({"raiz": str(pasta_filmes),
                               "itens": [{"de": str(a), "para": str(b)} for a, b in feitos]},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    return log


def ultimo_log(pasta_filmes: str | Path) -> Path | None:
    logs = sorted((Path(pasta_filmes) / PASTA_LOGS).glob("log-*.json"))
    return logs[-1] if logs else None


def desfazer(log: str | Path) -> list[str]:
    """Devolve os arquivos de um log para onde estavam. Remove pastas que ficaram vazias."""
    log = Path(log)
    dados = json.loads(log.read_text(encoding="utf-8"))
    if isinstance(dados, list):                     # formato antigo (só a lista)
        dados = {"raiz": str(log.parent.parent), "itens": dados}
    raiz, itens = Path(dados["raiz"]).resolve(), dados["itens"]
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
            _remover_pastas_vazias(para.parent, raiz, itens, mensagens)
        except OSError as erro:
            mensagens.append(f"erro em {para}: {erro}")
    log.rename(log.with_suffix(".desfeito.json"))
    return mensagens


def _remover_pastas_vazias(pasta: Path, raiz: Path, itens: list, mensagens: list) -> None:
    """Sobe a partir de `pasta` apagando pastas vazias, mas NUNCA a própria biblioteca (raiz)."""
    while pasta.exists() and pasta.resolve() != raiz and raiz in pasta.resolve().parents:
        if any(pasta.iterdir()):
            ainda_vai_mexer = any(Path(i["para"]).exists() and pasta in Path(i["para"]).parents for i in itens)
            if not ainda_vai_mexer and not any(p.is_dir() for p in pasta.iterdir()):
                mensagens.append(f"pasta mantida (tem arquivos que o organizador não moveu, "
                                 f"ex.: legenda baixada): {pasta}")
            return
        pasta.rmdir()
        pasta = pasta.parent
