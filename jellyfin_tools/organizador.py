"""Move e renomeia vídeos para o padrão do Jellyfin:

    Filmes:  <pasta_filmes>/Nome do Filme (Ano)/Nome do Filme (Ano).ext
    Séries:  <pasta_series>/Nome da Série (Ano)/Season 01/Nome da Série S01E02.ext

A origem pode ser uma pasta separada (ex.: Downloads) OU a própria biblioteca: nesse caso
o que já está no padrão aparece como 'organizado' e fica onde está.

Arquivos que vêm junto (ver extras.py): legendas (inclusive "FORCED" e outros idiomas), imagens
de arte (poster.jpg, backdrop.jpg...) e .nfo vão com o vídeo; lixo de torrent (.url, .txt de
propaganda, trailers pequenos) é apagado ao aplicar, se limpar_lixo=True.

Segurança:
  - Por padrão só SIMULA (aplicar=False): mostra o que faria, sem mexer em nada.
  - Nunca sobrescreve: se o destino já existe, o arquivo fica onde está (status 'conflito').
  - Ao aplicar, grava um log JSON; desfazer(log) devolve tudo para o lugar original.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .catalogo import Catalogo, ErroCatalogo, Filme
from .extras import LIMITE_TRAILER_MB, eh_trailer, limpar_cache, lixo_da_pasta, planejar_extras
from .nomes import (eh_video, extrair_episodio, extrair_titulo_e_ano, formatar_titulo, nome_episodio_jellyfin,
                    nome_jellyfin, normalizar, pasta_temporada)

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
    apagar: list[Path] | None = None                       # lixo da pasta de origem (.url, .txt, trailers)
    pasta_apagar: Path | None = None                       # pasta do torrent a apagar inteira no fim

    def __str__(self) -> str:
        destino = f" -> {self.destino_curto}" if self.destino else ""
        partes = [p for p in (self.detalhe, self.resumo_extras) if p]
        detalhe = f" ({'; '.join(partes)})" if partes else ""
        return f"[{self.status}] {self.origem.name}{destino}{detalhe}"

    @property
    def resumo_extras(self) -> str:
        """Ex.: '+1 legenda, 2 imagens; apagar 2'."""
        legendas = sum(1 for _, novo in self.acompanhantes or [] if novo.suffix.lower() in
                       {".srt", ".ass", ".ssa", ".sub", ".idx", ".vtt"})
        imagens = sum(1 for _, novo in self.acompanhantes or [] if novo.suffix.lower() in
                      {".jpg", ".png", ".webp"})
        juntos = [t for n, t in ((legendas, f"{legendas} legenda(s)"), (imagens, f"{imagens} imagem(ns)")) if n]
        texto = ("+" + ", ".join(juntos)) if juntos else ""
        if self.apagar:
            texto += ("; " if texto else "") + f"apagar {len(self.apagar)}"
        if self.pasta_apagar:
            texto += ("; " if texto else "") + "apagar a pasta"
        return texto

    @property
    def fonte_nome(self) -> str:
        """De onde veio o nome novo: 'TMDB', 'catálogo' (lista local), 'arquivo' (o nome do próprio
        arquivo, sem confirmação) ou '' (não vai ter nome novo)."""
        if self.filme is not None:
            return self.filme.fonte
        return "arquivo" if self.destino else ""

    @property
    def destino_curto(self) -> str:
        """Filmes: 'Matrix (1999)/Matrix (1999).mkv'.  Séries: 'Dark (2017)/Season 01/Dark S01E01.mkv'."""
        if not self.destino:
            return ""
        partes = self.destino.parts[-3:] if self.episodio else self.destino.parts[-2:]
        return "/".join(partes)


def _consultar(catalogo: Catalogo | None, titulo: str, ano: int | None, tipo: str):
    """Devolve (Filme ou None, detalhe do erro)."""
    if catalogo is None:
        return None, ""
    try:
        return catalogo.buscar(titulo, ano, tipo), ""
    except ErroCatalogo as erro:
        return None, f"catálogo indisponível: {erro}"


def _finalizar(video: Path, pasta: Path, nome_arquivo: str, detalhe: str, filme, episodio=None,
               raiz: Path | None = None, limite_mb: float = LIMITE_TRAILER_MB) -> Movimento:
    destino = pasta / f"{nome_arquivo}{video.suffix.lower()}"
    if _mesmo_arquivo(destino, video):
        return Movimento(video, destino, "organizado", "já está no padrão do Jellyfin", filme, None, episodio)
    extras = planejar_extras(video, nome_arquivo, pasta, raiz, "series" if episodio else "filmes", limite_mb)
    mov = Movimento(video, destino, "simulado", detalhe, filme, extras.mover, episodio)
    if destino.exists() and not _mesmo_arquivo(destino, video):
        mov.status, mov.detalhe = "conflito", "já existe um arquivo com esse nome no destino"
    return mov


def planejar(video: Path, pasta_filmes: Path, catalogo: Catalogo | None = None,
             incluir_tmdbid: bool = False, exigir_catalogo: bool = False, modo: str = "filmes",
             raiz: Path | None = None, limite_mb: float = LIMITE_TRAILER_MB,
             nomes_episodios: bool = False) -> Movimento:
    """Decide PARA ONDE o vídeo vai (e o que vai junto), sem mover nada.
    `raiz` é a pasta de origem da varredura (para saber se o vídeo está numa pasta só dele).
    nomes_episodios: séries ganham o nome do episódio, se o catálogo souber (TMDB):
    'Dark S01E01 - Segredos.mkv'. Sem o nome, fica só o número ('Dark S01E01.mkv')."""
    if "sample" in normalizar(video.stem).split():
        return Movimento(video, None, "ignorado", "arquivo de amostra (sample)")
    if modo == "series":
        return _planejar_episodio(video, pasta_filmes, catalogo, incluir_tmdbid, exigir_catalogo, raiz, limite_mb,
                                  nomes_episodios)

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
    return _finalizar(video, pasta_filmes / nome, nome, detalhe, filme, None, raiz, limite_mb)


def _planejar_episodio(video: Path, pasta_series: Path, catalogo: Catalogo | None,
                       incluir_tmdbid: bool, exigir_catalogo: bool, raiz: Path | None = None,
                       limite_mb: float = LIMITE_TRAILER_MB, nomes_episodios: bool = False) -> Movimento:
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
    titulo_ep = ""
    if nomes_episodios and serie is not None and catalogo is not None:
        titulo_ep = getattr(catalogo, "nome_episodio", lambda *a: None)(serie, ep.temporada, ep.episodio) or ""
    if not titulo_ep:                    # já tem nome ('Dark S01E01 - Segredos'): não tira, mesmo sem TMDB
        so_numero = nome_episodio_jellyfin(nome, ep.temporada, ep.episodio)
        if video.stem.lower().startswith(so_numero.lower() + " - "):
            titulo_ep = video.stem[len(so_numero) + 3:]
    return _finalizar(video, pasta, nome_episodio_jellyfin(nome, ep.temporada, ep.episodio, titulo_ep), detalhe, serie,
                      (ep.temporada, ep.episodio), raiz, limite_mb)


def _consultas(videos: list[Path], modo: str) -> list[tuple[str, int | None, str]]:
    """As mesmas buscas que o planejar() vai fazer, para o catálogo adiantar de uma vez."""
    consultas = []
    for v in videos:
        if "sample" in normalizar(v.stem).split():
            continue
        if modo == "series":
            ep = extrair_episodio(v.name)
            if ep:
                consultas.append((ep.serie, ep.ano, "serie"))
        else:
            extraido = extrair_titulo_e_ano(v.name)
            consultas.append((extraido.titulo, extraido.ano, "filme"))
    return consultas


def _temporadas(videos: list[Path], catalogo: Catalogo) -> list[tuple[Filme, int]]:
    """(série, temporada) de cada episódio, para buscar os nomes de uma temporada inteira de uma vez."""
    pedidos = []
    for v in videos:
        ep = extrair_episodio(v.name)
        if ep:
            serie, _ = _consultar(catalogo, ep.serie, ep.ano, "serie")      # já está no cache
            if serie:
                pedidos.append((serie, ep.temporada))
    return list(dict.fromkeys(pedidos))


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
    # Só precisa conferir arquivo por arquivo se a biblioteca for uma subpasta da origem.
    biblioteca_dentro = not no_lugar and _dentro(pasta_filmes, origem)
    biblioteca = pasta_filmes.resolve()
    videos = []
    for pasta, subpastas, arquivos in os.walk(origem):
        subpastas[:] = sorted(d for d in subpastas if d != PASTA_LOGS)   # não entra no log
        if not recursivo:
            subpastas[:] = []
        if biblioteca_dentro and (Path(pasta).resolve() == biblioteca or biblioteca in Path(pasta).resolve().parents):
            continue
        videos += [Path(pasta) / nome for nome in arquivos if eh_video(Path(nome))]
    return sorted(videos)


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
                    exigir_catalogo: bool = False, modo: str = "filmes", limpar_lixo: bool = True,
                    limite_trailer_mb: float = LIMITE_TRAILER_MB,
                    ao_planejar=None, ao_progresso=None,
                    apagar_pasta_origem: bool = False, ao_analisar=None,
                    nomes_episodios: bool = False) -> list[Movimento]:
    """Organiza todos os vídeos de `origem` na biblioteca `pasta_filmes` (no modo "series",
    a pasta de séries do Jellyfin). Devolve o que fez (ou faria).
    limpar_lixo: ao aplicar, apaga .url/.txt de propaganda e trailers pequenos (< limite_trailer_mb).
    ao_planejar(movimentos): chamado com o plano, antes de mover (para mostrar a lista).
    ao_progresso(indice, movimento, fracao): andamento de cada item (0.0 a 1.0) enquanto move.
    apagar_pasta_origem: no fim, apaga a pasta do torrent INTEIRA (com o que sobrou nela), se for
    seguro (ver _planejar_pastas_a_apagar). Irreversível: a pré-visualização mostra quais.
    ao_analisar(fracao, texto): andamento da ANÁLISE (consultas ao TMDB + planejamento), 0.0 a 1.0.
    nomes_episodios: no modo séries, acrescenta o nome do episódio (TMDB) depois do número;
    episódios já organizados só com o número também são renomeados."""
    if modo not in MODOS:
        raise ValueError(f"modo deve ser um de {MODOS}")
    limpar_cache()                       # os arquivos podem ter mudado desde a última execução
    origem, pasta_filmes = Path(origem).expanduser(), Path(pasta_filmes).expanduser()
    if not origem.is_dir():
        raise NotADirectoryError(f"pasta de origem não existe: {origem}")

    videos = _listar_videos(origem, pasta_filmes, recursivo)
    # Trailers/propagandas pequenos não são filmes: ficam fora do planejamento (e viram lixo).
    trailers = {v for v in videos if modo == "filmes" and eh_trailer(v, origem, limite_trailer_mb)}
    analisar = [v for v in videos if v not in trailers]
    avisar_analise = ao_analisar or (lambda *a: None)
    # Com o TMDB, as consultas pela internet são quase todo o tempo da análise: são feitas antes,
    # em paralelo, e ocupam 90% da barra. Sem TMDB, a análise é só local (rápida).
    peso_tmdb = 0.9 if getattr(catalogo, "usa_tmdb", False) and analisar else 0.0
    if peso_tmdb:
        avisar_analise(0.0, "Consultando o TMDB...")
        com_episodios = nomes_episodios and modo == "series"
        peso_nomes = peso_tmdb / 2 if com_episodios else peso_tmdb       # séries: metade busca a série,
        catalogo.pre_buscar(_consultas(analisar, modo),                   # metade os nomes dos episódios
                            lambda feitas, total: avisar_analise(peso_nomes * feitas / total,
                                                                 f"Consultando o TMDB: {feitas} de {total}"))
        if com_episodios:
            catalogo.pre_buscar_episodios(
                _temporadas(analisar, catalogo),
                lambda feitas, total: avisar_analise(peso_nomes + (peso_tmdb - peso_nomes) * feitas / total,
                                                     f"Nomes dos episódios: temporada {feitas} de {total}"))
    movimentos = []
    passo = max(1, len(analisar) // 100)                 # no máximo ~100 avisos (não trava a janela)
    for n, v in enumerate(analisar, 1):
        movimentos.append(planejar(v, pasta_filmes, catalogo, incluir_tmdbid, exigir_catalogo, modo,
                                   origem, limite_trailer_mb, nomes_episodios))
        if n % passo == 0 or n == len(analisar):
            avisar_analise(peso_tmdb + (1 - peso_tmdb) * n / len(analisar),
                           f"Analisando: {n} de {len(analisar)} – {v.name}")
    _marcar_destinos_repetidos(movimentos)
    if limpar_lixo:
        _planejar_lixo(movimentos, origem, modo, limite_trailer_mb)
    if apagar_pasta_origem:
        _planejar_pastas_a_apagar(movimentos, origem, pasta_filmes, trailers)
    if not aplicar:
        return movimentos
    if ao_planejar:
        ao_planejar(movimentos)
    avisar = ao_progresso or (lambda *a: None)

    feitos = []
    apagados: list[Path] = []
    pastas_de_onde_sairam: set[Path] = set()
    for indice, mov in enumerate(movimentos):
        if mov.status != "simulado":
            continue
        pastas_de_onde_sairam.add(mov.origem.parent)
        avisar(indice, mov, 0.0)
        try:
            mov.destino.parent.mkdir(parents=True, exist_ok=True)
            # o vídeo é 95% do trabalho; legendas, imagens e lixo são o resto
            mover_com_progresso(mov.origem, mov.destino, lambda f, i=indice, m=mov: avisar(i, m, f * 0.95))
            feitos.append((mov.origem, mov.destino))
            mov.status = "movido"
            for antigo, novo in mov.acompanhantes or []:
                if novo.exists() or not antigo.exists():
                    continue
                shutil.move(str(antigo), str(novo))
                feitos.append((antigo, novo))
        except OSError as erro:                               # sem permissão, disco cheio, arquivo em uso...
            mov.status, mov.detalhe = "erro", str(erro)
            avisar(indice, mov, 1.0)
            continue
        for lixo in mov.apagar or []:
            try:
                lixo.unlink()
                apagados.append(lixo)
            except FileNotFoundError:
                pass
            except OSError as erro:                           # arquivo em uso: não impede o resto
                mov.detalhe = f"não consegui apagar {lixo.name}: {erro}"
        avisar(indice, mov, 1.0)
    pastas_apagadas = _apagar_pastas_de_origem(movimentos, trailers, origem) if apagar_pasta_origem else []
    if feitos or apagados or pastas_apagadas:
        _gravar_log(pasta_filmes, feitos, apagados, pastas_apagadas)
        _apagar_pastas_que_esvaziaram(pastas_de_onde_sairam, origem)
    return movimentos


# ----------------------------------------------------------------- apagar a pasta do torrent
def _pasta_do_torrent(video: Path, origem: Path) -> Path | None:
    """A subpasta de 1º nível da origem onde o vídeo está (None se ele está solto na origem)."""
    try:
        relativo = video.parent.resolve().relative_to(origem.resolve())
    except ValueError:
        return None
    return origem / relativo.parts[0] if relativo.parts else None


def _videos_que_ficariam(pasta: Path, saem: set[Path]) -> list[Path]:
    """Vídeos dentro da pasta (e subpastas) que NÃO estão saindo dela."""
    sobra = []
    for raiz, _, arquivos in os.walk(pasta):
        for nome in arquivos:
            arquivo = Path(raiz) / nome
            if eh_video(arquivo) and arquivo.resolve() not in saem:
                sobra.append(arquivo)
    return sobra


def _descartaveis(movimentos: list[Movimento], trailers: set[Path]) -> set[Path]:
    """Vídeos que podem sumir junto com a pasta: amostras ('sample') e trailers pequenos."""
    return {p.resolve() for p in trailers} | {m.origem.resolve() for m in movimentos if m.status == "ignorado"}


def _planejar_pastas_a_apagar(movimentos: list[Movimento], origem: Path, biblioteca: Path,
                              trailers: set[Path]) -> None:
    """Marca (no 1º filme de cada pasta) as pastas de torrent que é SEGURO apagar inteiras:
       - é uma subpasta da origem (nunca a origem nem a biblioteca);
       - nenhum destino fica dentro dela (no modo 'mesma pasta', a pasta do filme não some);
       - não sobra nenhum vídeo nela além dos que estão sendo movidos, amostras e trailers."""
    destinos = [m.destino.resolve() for m in movimentos if m.destino]
    bib = biblioteca.resolve()
    saem = {m.origem.resolve() for m in movimentos if m.status == "simulado"} | _descartaveis(movimentos, trailers)
    por_pasta: dict[Path, list[Movimento]] = {}
    for m in movimentos:
        if m.status == "simulado" and (pasta := _pasta_do_torrent(m.origem, origem)):
            por_pasta.setdefault(pasta, []).append(m)
    for pasta, movs in por_pasta.items():
        p = pasta.resolve()
        if p == bib or p in bib.parents:
            continue                                         # a biblioteca está dentro dela
        if any(d == p or p in d.parents for d in destinos):
            continue                                         # algum filme vai ficar aqui dentro
        if _videos_que_ficariam(pasta, saem):
            continue                                         # tem vídeo que não está saindo
        movs[0].pasta_apagar = pasta


def _apagar_pastas_de_origem(movimentos: list[Movimento], trailers: set[Path], origem: Path) -> list[Path]:
    """Depois de mover tudo: apaga as pastas marcadas, conferindo de novo antes (só se todos os
    filmes dela foram movidos e nenhum vídeo sobrou)."""
    apagadas = []
    saem_ok = _descartaveis(movimentos, trailers)
    por_pasta: dict[Path, list[Movimento]] = {}               # agrupa UMA vez (antes: n x n)
    for m in movimentos:
        if m.status in ("movido", "erro", "simulado") and (pasta := _pasta_do_torrent(m.origem, origem)):
            por_pasta.setdefault(pasta, []).append(m)
    for mov in movimentos:
        pasta = mov.pasta_apagar
        if not pasta or not pasta.exists():
            continue
        da_pasta = por_pasta.get(pasta, [])
        if any(m.status != "movido" for m in da_pasta):
            mov.detalhe = "pasta de origem mantida: um filme dela não foi movido"
            continue
        if _videos_que_ficariam(pasta, saem_ok):
            mov.detalhe = "pasta de origem mantida: ainda tem vídeo dentro"
            continue
        try:
            if sys.version_info >= (3, 12):                 # o parâmetro mudou de nome no 3.12
                shutil.rmtree(pasta, onexc=_tirar_somente_leitura)
            else:
                shutil.rmtree(pasta, onerror=_tirar_somente_leitura)
            apagadas.append(pasta)
        except OSError as erro:
            mov.detalhe = f"não consegui apagar a pasta {pasta.name}: {erro}"
    return apagadas


def _tirar_somente_leitura(funcao, caminho, _excecao) -> None:
    """No Windows, arquivo 'somente leitura' impede apagar: tira o atributo e tenta de novo."""
    os.chmod(caminho, 0o700)
    funcao(caminho)


BLOCO_COPIA = 8 * 1024 * 1024


def _mesmo_disco(arquivo: Path, pasta: Path) -> bool:
    try:
        return arquivo.stat().st_dev == pasta.stat().st_dev
    except OSError:
        return False


def mover_com_progresso(de: Path, para: Path, ao_progresso=None) -> None:
    """Move um arquivo avisando o andamento (0.0 a 1.0).
    Mesmo disco: só troca o nome (instantâneo). Discos diferentes: copia em blocos de 8 MB
    (para a porcentagem andar de verdade), confere o tamanho e só então apaga o original."""
    avisar = ao_progresso or (lambda f: None)
    if para.exists():
        raise FileExistsError(f"já existe: {para}")       # nunca sobrescreve
    if _mesmo_disco(de, para.parent):
        os.rename(de, para)
        avisar(1.0)
        return
    total = de.stat().st_size or 1
    parcial = para.with_name(para.name + ".part")
    copiado = 0
    try:
        with open(de, "rb") as origem, open(parcial, "wb") as destino:
            while bloco := origem.read(BLOCO_COPIA):
                destino.write(bloco)
                copiado += len(bloco)
                avisar(min(copiado / total, 0.999))
        shutil.copystat(de, parcial)
        if parcial.stat().st_size != de.stat().st_size:
            raise OSError("a cópia ficou com tamanho diferente do original")
        os.rename(parcial, para)
    except BaseException:
        parcial.unlink(missing_ok=True)                   # não deixa arquivo pela metade
        raise
    de.unlink()
    avisar(1.0)


def _planejar_lixo(movimentos: list[Movimento], origem: Path, modo: str, limite_mb: float) -> None:
    """Para cada pasta de onde um vídeo vai sair, lista o lixo dela (no 1º movimento daquela pasta)."""
    ja_vistas: set[Path] = set()
    vao_junto = {antigo for m in movimentos for antigo, _ in (m.acompanhantes or [])}
    for mov in movimentos:
        pasta = mov.origem.parent
        if mov.status != "simulado" or pasta in ja_vistas:
            continue
        ja_vistas.add(pasta)
        mov.apagar = [a for a in lixo_da_pasta(pasta, origem, modo, limite_mb) if a not in vao_junto]


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


def _gravar_log(pasta_filmes: Path, feitos: list[tuple[Path, Path]], apagados: list[Path] = (),
                pastas_apagadas: list[Path] = ()) -> Path:
    pasta = pasta_filmes / PASTA_LOGS
    pasta.mkdir(parents=True, exist_ok=True)
    log = pasta / f"log-{datetime.now():%Y%m%d-%H%M%S-%f}.json"
    log.write_text(json.dumps({"raiz": str(pasta_filmes),
                               "itens": [{"de": str(a), "para": str(b)} for a, b in feitos],
                               "apagados": [str(a) for a in apagados],
                               "pastas_apagadas": [str(p) for p in pastas_apagadas]},
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
    if dados.get("pastas_apagadas"):
        mensagens.append(f"{len(dados['pastas_apagadas'])} pasta(s) de origem foram apagadas: o que sobrou "
                         "nelas (amostras, prints...) não volta; os filmes voltaram para pastas recriadas")
    if dados.get("apagados"):
        mensagens.append(f"{len(dados['apagados'])} arquivo(s) de lixo foram apagados e não voltam "
                         f"(ex.: {Path(dados['apagados'][0]).name})")
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
