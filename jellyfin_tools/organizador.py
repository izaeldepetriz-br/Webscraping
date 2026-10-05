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
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .catalogo import Catalogo, ErroCatalogo, Filme
from .extras import (ARTES, LIMITE_TRAILER_MB, _arquivos, eh_propaganda_pequena, eh_trailer, imagem_do_video, limpar_cache,
                     lixo_da_pasta, marcar_repetidos, planejar_extras, tipo_de_arte)
from .regras import aplicar_regra, regra_para
from .nomes import (EpisodioExtraido, NomeExtraido, eh_video, eh_video_da_biblioteca, extrair_episodio, qualidade, extrair_titulo_e_ano,
                    episodio_no_meio, formatar_titulo, marca_de_episodio, nome_episodio_jellyfin, nome_jellyfin,
                    normalizar, numeros_sem_serie, pasta_temporada, serie_da_pasta, temporada_da_pasta)

PASTA_LOGS = ".organizador"
MODOS = ("filmes", "series")
DETALHE_EPISODIO = "é episódio de série"     # modo Filmes: a janela oferece trocar para Séries
WINDOWS = os.name == "nt"                  # as regras de nome de pasta abaixo são as do Windows
_RE_UNIDADE = re.compile(r"[A-Za-z]:[\\/]")
_PROIBIDOS_WINDOWS = set('<>"|?*')


def problema_no_caminho(texto: str, windows: bool | None = None) -> str | None:
    """Confere se o caminho é válido no Windows ANTES de mexer em qualquer arquivo.
    Ex.: 'E:\\Series_OE:\\Series_Organizadas' (um endereço colado dentro de outro) -> explica o erro.
    Devolve None se estiver tudo certo."""
    if not (WINDOWS if windows is None else windows):
        return None
    texto = str(texto).strip()
    if texto[:4] in ("\\\\?\\", "//?/"):          # prefixo de caminho longo do Windows: é válido
        texto = texto[4:]
    resto = texto[2:] if re.match(r"[A-Za-z]:", texto) else texto      # tira o 'E:' do começo
    if ":" in resto:
        return (f"o caminho tem \"{resto[max(resto.index(':') - 1, 0):][:2]}\" no meio, o que o Windows não aceita:\n"
                f"{texto}\nParece que um endereço foi colado dentro de outro.")
    proibidos = sorted(_PROIBIDOS_WINDOWS & set(resto))
    if proibidos:
        return f"o caminho tem caracteres que o Windows não aceita ({' '.join(proibidos)}):\n{texto}"
    return None


def sugestao_de_caminho(texto: str) -> str | None:
    """'E:\\Series_OE:\\Series_Organizadas\\Series' -> 'E:\\Series_Organizadas\\Series' (a partir do último 'E:\\')."""
    inicios = [m.start() for m in _RE_UNIDADE.finditer(str(texto))]
    return str(texto)[inicios[-1]:] if len(inicios) > 1 else None


@dataclass
class Movimento:
    origem: Path
    destino: Path | None
    status: str          # simulado | movido | organizado | conflito | nao_identificado | ignorado | erro
    #                      limpeza | pasta_apagada  (sobra de uma organização anterior; ver _planejar_sobras)
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
        mov.status, mov.detalhe = "conflito", (f"já existe na biblioteca ({_tamanho_legivel(destino)}); "
                                               f"este tem {_tamanho_legivel(video)}"
                                               + (f", {qualidade(video.name)[2]}" if qualidade(video.name)[2] else "")
                                               + ". Nada é sobrescrito: compare e apague o pior")
    return mov


def episodio_do_video(video: Path, raiz: Path | None = None) -> EpisodioExtraido | None:
    """Episódio pelo nome do arquivo; se o arquivo não traz o nome da série ('Temp 01 - Epi 04 -
    Socos Mortais.mkv', '04-01 Saída 9B.mkv'), a série vem da pasta ('Apenas um Show - 1a Temporada'
    -> 'Apenas um Show') ou da de cima, sem passar da pasta de origem."""
    if ep := extrair_episodio(video.name):
        return ep
    if (ep := episodio_no_meio(video.name)) and _tem_irmao(video, ep, episodio_no_meio):
        return ep                                          # 'HunterXHunter 66_York Shin' (com 67, 68... ao lado)
    if not (numeros := numeros_sem_serie(video.name)):
        return None
    temporada, episodio, absoluto, titulo = numeros
    if absoluto and (da_pasta := temporada_da_pasta(video.parent.name)):
        temporada, absoluto = da_pasta, False              # 'Breaking Bad 5 Temporada/13 - To'hajiilee'
    for pasta in (video.parent, video.parent.parent):
        if achado := serie_da_pasta(pasta.name):
            return EpisodioExtraido(achado[0], temporada, episodio, achado[1], absoluto, titulo)
        if raiz is not None and pasta.resolve() == Path(raiz).resolve():
            break
    return None


def _episodio_em_sequencia(video: Path):
    """Só o número, sem ano ('Samurai X - 01 Dual Audio.avi') E outros arquivos da mesma pasta com o
    mesmo nome e outro número: é episódio de anime, não filme. Um 'Rocky 2.avi' sozinho não conta."""
    ep = extrair_episodio(video.name)
    if ep is None or not ep.absoluto or ep.ano is not None:
        return None
    return ep if _tem_irmao(video, ep, extrair_episodio) else None


def _tem_irmao(video: Path, ep, extrator) -> bool:
    """Outro vídeo da mesma pasta com o mesmo nome de série e OUTRO número (uma sequência)."""
    try:
        vizinhos = [a for a in video.parent.iterdir() if a != video and a.is_file() and eh_video(a)]
    except OSError:
        return False
    serie = normalizar(ep.serie)
    for vizinho in vizinhos:
        outro = extrator(vizinho.name)
        if outro and outro.absoluto and outro.episodio != ep.episodio and normalizar(outro.serie) == serie:
            return True
    return False


def planejar(video: Path, pasta_filmes: Path, catalogo: Catalogo | None = None,
             incluir_tmdbid: bool = False, exigir_catalogo: bool = False, modo: str = "filmes",
             raiz: Path | None = None, limite_mb: float = LIMITE_TRAILER_MB,
             nomes_episodios: bool = False, regras=()) -> Movimento:
    """Decide PARA ONDE o vídeo vai (e o que vai junto), sem mover nada.
    `raiz` é a pasta de origem da varredura (para saber se o vídeo está numa pasta só dele).
    nomes_episodios: séries ganham o nome do episódio, se o catálogo souber (TMDB):
    'Dark S01E01 - Segredos.mkv'. Sem o nome, fica só o número ('Dark S01E01.mkv').
    regras: o que você ensinou no "Corrigir nome" (jellyfin_tools.regras)."""
    if "sample" in normalizar(video.stem).split():
        return Movimento(video, None, "ignorado", "arquivo de amostra (sample)")
    if eh_propaganda_pequena(video, limite_mb):          # 'BLUDV.mp4' junto dos episódios do site BLUDV
        return Movimento(video, None, "ignorado", "propaganda do site (não é filme nem episódio)")
    if modo == "series":
        return _planejar_episodio(video, pasta_filmes, catalogo, incluir_tmdbid, exigir_catalogo, raiz, limite_mb,
                                  nomes_episodios, regras)

    if regra := regra_para(video, regras, "filme"):     # você disse qual filme é ("Corrigir nome")
        extraido = NomeExtraido(regra.titulo, regra.ano)
    elif marca := marca_de_episodio(video.name):        # modo Filmes com episódio: avisa, não chuta
        return Movimento(video, None, "nao_identificado", f"{DETALHE_EPISODIO} ({marca}): use o modo Séries")
    else:
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
    elif ep := _episodio_em_sequencia(video):         # "Samurai X - 01", "- 02"...: anime no modo Filmes
        return Movimento(video, None, "nao_identificado",
                         f"{DETALHE_EPISODIO} (episódio {ep.episodio:02d}, numeração contínua): use o modo Séries")
    else:
        return Movimento(video, None, "nao_identificado",
                         detalhe or "não achei o ano no nome; renomeie à mão ou use o TMDB")

    nome = nome_jellyfin(titulo, ano, filme.tmdb_id if filme else None, incluir_tmdbid)
    return _finalizar(video, pasta_filmes / nome, nome, detalhe, filme, None, raiz, limite_mb)


def _planejar_episodio(video: Path, pasta_series: Path, catalogo: Catalogo | None,
                       incluir_tmdbid: bool, exigir_catalogo: bool, raiz: Path | None = None,
                       limite_mb: float = LIMITE_TRAILER_MB, nomes_episodios: bool = False,
                       regras=()) -> Movimento:
    ep = episodio_do_video(video, raiz)
    if regra := regra_para(video, regras, "serie"):     # você disse qual série é ("Corrigir nome")
        ep = aplicar_regra(ep, video, regra)
    if not ep:
        return Movimento(video, None, "nao_identificado",
                         "não achei temporada/episódio no nome (ex.: S01E02, 1x02, Episodio 3)")
    serie, detalhe = _achar_serie(catalogo, ep, video, raiz)
    if serie:
        nome, ano = serie.titulo, serie.ano
    elif exigir_catalogo:
        return Movimento(video, None, "nao_identificado", detalhe or f"série '{ep.serie}' não está no catálogo")
    else:
        nome, ano = formatar_titulo(ep.serie), ep.ano
        detalhe = detalhe or "série não confirmada no catálogo: confira o nome"
    temporada, episodio = _temporada_e_episodio(catalogo, ep, serie)
    if (temporada, episodio) != (ep.temporada, ep.episodio):
        detalhe = "; ".join(t for t in (detalhe, f"numeração contínua {ep.episodio} = "
                                                f"temporada {temporada}, episódio {episodio} (TMDB)") if t)
    pasta_serie = pasta_series / nome_jellyfin(nome, ano, serie.tmdb_id if serie else None, incluir_tmdbid)
    pasta = pasta_serie / pasta_temporada(temporada)
    titulo_ep = ep.titulo if ep.saga else ""          # 'HunterXHunter 66_York Shin': fica o nome da saga
    if not titulo_ep and nomes_episodios and serie is not None and catalogo is not None:
        titulo_ep = getattr(catalogo, "nome_episodio", lambda *a: None)(serie, temporada, episodio) or ""
    titulo_ep = titulo_ep or ep.titulo                 # o nome que veio no arquivo ('13 - To'hajiilee')
    if not titulo_ep:                    # já tem nome ('Dark S01E01 - Segredos'): não tira, mesmo sem TMDB
        so_numero = nome_episodio_jellyfin(nome, temporada, episodio)
        if video.stem.lower().startswith(so_numero.lower() + " - "):
            titulo_ep = video.stem[len(so_numero) + 3:]
    return _finalizar(video, pasta, nome_episodio_jellyfin(nome, temporada, episodio, titulo_ep), detalhe, serie,
                      (temporada, episodio), raiz, limite_mb)


def _temporada_e_episodio(catalogo, ep, serie) -> tuple[int, int]:
    """Anime com numeração contínua ('Dragon Ball 153'): se o TMDB divide a série em temporadas,
    153 vira (temporada, episódio) pela quantidade de episódios de cada uma. Sem o TMDB, ou se o
    número passa do que ele conhece, fica como veio (temporada 1)."""
    if not ep.absoluto or serie is None or catalogo is None:
        return ep.temporada, ep.episodio
    lista = getattr(catalogo, "temporadas", lambda s: None)(serie)
    restante = ep.episodio
    for numero, quantidade in lista or []:
        if quantidade <= 0:
            continue
        if restante <= quantidade:
            return numero, restante
        restante -= quantidade
    return ep.temporada, ep.episodio


def _consultas(videos: list[Path], modo: str) -> list[tuple[str, int | None, str]]:
    """As mesmas buscas que o planejar() vai fazer, para o catálogo adiantar de uma vez."""
    consultas = []
    for v in videos:
        if "sample" in normalizar(v.stem).split():
            continue
        if modo == "series":
            ep = episodio_do_video(v)
            if ep:
                if not ep.ano and (dica := _ano_da_pasta(v)):
                    consultas.append((ep.serie, dica, "serie"))           # a busca com a dica de ano
                consultas.append((ep.serie, ep.ano, "serie"))
        elif not marca_de_episodio(v.name):               # episódio no modo Filmes: nem consulta
            extraido = extrair_titulo_e_ano(v.name)
            consultas.append((extraido.titulo, extraido.ano, "filme"))
    return consultas


def _temporadas(videos: list[Path], catalogo: Catalogo) -> list[tuple[Filme, int]]:
    """(série, temporada) de cada episódio, para buscar os nomes de uma temporada inteira de uma vez."""
    pedidos = []
    for v in videos:
        ep = episodio_do_video(v)
        if ep:
            serie, _ = _achar_serie(catalogo, ep, v)                          # já está no cache
            if serie:
                pedidos.append((serie, _temporada_e_episodio(catalogo, ep, serie)[0]))
    return list(dict.fromkeys(pedidos))


def _achar_serie(catalogo, ep, video: Path, raiz: Path | None = None):
    """Série no catálogo. Sem ano no nome do arquivo, o ano da pasta é uma DICA:
    'hunter-x-hunter-1999/HunterXHunter 01.mp4' -> prefere a de 1999 (e não a de 2011)."""
    dica = None if ep.ano else _ano_da_pasta(video, raiz)
    if dica:
        serie, detalhe = _consultar(catalogo, ep.serie, dica, "serie")
        if serie and serie.ano == dica:
            return serie, detalhe
    return _consultar(catalogo, ep.serie, ep.ano, "serie")   # ano da pasta era outro (ex.: da temporada)


_RE_ANO_PASTA = re.compile(r"(?<!\d)(19[3-9]\d|20[0-4]\d)(?!\d)")


def _ano_da_pasta(video: Path, raiz: Path | None = None, niveis: int = 3) -> int | None:
    """Ano no nome da pasta do episódio (ou de uma acima, sem sair da origem):
    'hunter-x-hunter-1999 Ranking/HunterXHunter 01.mp4' -> 1999. Serve só de DICA para a busca."""
    for pasta in [video.parent, *video.parent.parents][:niveis]:
        if m := _RE_ANO_PASTA.search(pasta.name):
            return int(m.group(1))
        if raiz is not None and pasta == raiz:
            break
    return None


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


def protegido(caminho: str | Path, protegidas=()) -> bool:
    """True se o caminho está numa pasta protegida (ex.: as do Sonarr/Radarr): o organizador não mexe."""
    if not protegidas:
        return False
    alvo = os.path.normcase(os.path.abspath(caminho))
    for pasta in protegidas:
        if str(pasta).strip():
            base = os.path.normcase(os.path.abspath(str(pasta).strip()))
            if alvo == base or alvo.startswith(base.rstrip("\\/") + os.sep):
                return True
    return False


def _listar_videos(origem: Path, pasta_filmes: Path, recursivo: bool, protegidas=()) -> list[Path]:
    """Vídeos da origem. Se a origem fica FORA da biblioteca, o que estiver dentro da biblioteca
    é ignorado (ex.: origem E:/ e biblioteca E:/Filmes). Se a origem É a biblioteca (ou uma pasta
    dela), olha tudo: o que já estiver no padrão vira 'organizado' no planejar()."""
    no_lugar = _dentro(origem, pasta_filmes)
    # Só precisa conferir arquivo por arquivo se a biblioteca for uma subpasta da origem.
    biblioteca_dentro = not no_lugar and _dentro(pasta_filmes, origem)
    biblioteca = pasta_filmes.resolve()
    videos = []
    if protegido(origem, protegidas):
        return []
    for pasta, subpastas, arquivos in os.walk(origem):
        subpastas[:] = sorted(d for d in subpastas if d != PASTA_LOGS   # não entra no log
                              and not protegido(Path(pasta) / d, protegidas))
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
                    nomes_episodios: bool = False, filtro=None, protegidas=(), regras=(),
                    parar=None) -> list[Movimento]:
    """Organiza todos os vídeos de `origem` na biblioteca `pasta_filmes` (no modo "series",
    a pasta de séries do Jellyfin). Devolve o que fez (ou faria).
    limpar_lixo: ao aplicar, apaga .url/.txt de propaganda e trailers pequenos (< limite_trailer_mb).
    ao_planejar(movimentos): chamado com o plano, antes de mover (para mostrar a lista).
    ao_progresso(indice, movimento, fracao): andamento de cada item (0.0 a 1.0) enquanto move.
    apagar_pasta_origem: no fim, apaga a pasta do torrent INTEIRA (com o que sobrou nela), se for
    seguro (ver _planejar_pastas_a_apagar). Irreversível: a pré-visualização mostra quais.
    ao_analisar(fracao, texto): andamento da ANÁLISE (consultas ao TMDB + planejamento), 0.0 a 1.0.
    nomes_episodios: no modo séries, acrescenta o nome do episódio (TMDB) depois do número;
    episódios já organizados só com o número também são renomeados.
    filtro(video) -> bool: só os vídeos aprovados entram (ex.: vigia.filtro_prontos(), só o que
    terminou de baixar); os outros ficam onde estão, sem aparecer no resultado.
    protegidas: pastas que o organizador NUNCA mexe (ex.: as do Sonarr/Radarr), nem entra nelas.
    parar() verdadeiro: para NA HORA. Na análise, devolve só o que já analisou; ao mover, termina o arquivo
    atual (uma cópia entre discos é interrompida e o original fica onde estava) e grava o log do que moveu."""
    if modo not in MODOS:
        raise ValueError(f"modo deve ser um de {MODOS}")
    limpar_cache()                       # os arquivos podem ter mudado desde a última execução
    for nome, caminho in (("origem", origem), ("biblioteca", pasta_filmes)):
        if problema := problema_no_caminho(str(caminho)):
            raise ValueError(f"pasta da {nome} inválida: {problema}")   # antes de mexer em qualquer arquivo
    origem, pasta_filmes = Path(origem).expanduser(), Path(pasta_filmes).expanduser()
    if not origem.is_dir():
        raise NotADirectoryError(f"pasta de origem não existe: {origem}")

    videos = _listar_videos(origem, pasta_filmes, recursivo, protegidas)
    marcar_repetidos(videos, limite_trailer_mb)          # propaganda repetida em cada pasta de episódio
    # Trailers/propagandas pequenos não são filmes: ficam fora do planejamento (e viram lixo).
    trailers = {v for v in videos if eh_trailer(v, origem, limite_trailer_mb, modo)}
    # Pastas de torrent que uma organização ANTERIOR já esvaziou (só sobrou propaganda/imagens):
    sobras = _planejar_sobras(origem, pasta_filmes, videos, limite_trailer_mb) if apagar_pasta_origem else []
    trailers |= {v for s in sobras for v in s.apagar or []}
    analisar = [v for v in videos if v not in trailers and (filtro is None or filtro(v))]
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
                                                                 f"Consultando o TMDB: {feitas} de {total}"),
                            parar=parar)
        if com_episodios:
            catalogo.pre_buscar_episodios(
                _temporadas(analisar, catalogo),
                lambda feitas, total: avisar_analise(peso_nomes + (peso_tmdb - peso_nomes) * feitas / total,
                                                     f"Nomes dos episódios: temporada {feitas} de {total}"),
                parar=parar)
    movimentos = []
    passo = max(1, len(analisar) // 100)                 # no máximo ~100 avisos (não trava a janela)
    for n, v in enumerate(analisar, 1):
        if parar and parar():                              # "Parar": devolve o que já analisou
            break
        movimentos.append(planejar(v, pasta_filmes, catalogo, incluir_tmdbid, exigir_catalogo, modo,
                                   origem, limite_trailer_mb, nomes_episodios, regras))
        if n % passo == 0 or n == len(analisar):
            avisar_analise(peso_tmdb + (1 - peso_tmdb) * n / len(analisar),
                           f"Analisando: {n} de {len(analisar)} – {v.name}")
    _marcar_destinos_repetidos(movimentos)
    if limpar_lixo:
        _planejar_lixo(movimentos, origem, modo, limite_trailer_mb)
    if apagar_pasta_origem:
        _planejar_pastas_a_apagar(movimentos, origem, pasta_filmes, trailers)
        destinos = [m.destino.resolve() for m in movimentos if m.destino]
        movimentos += [s for s in sobras                  # nenhum destino novo dentro dela
                       if not any(s.origem.resolve() in d.parents for d in destinos)]
    if protegidas:                                        # pasta com uma protegida dentro: não se apaga
        for m in movimentos:
            if m.pasta_apagar and any(protegido(p, [m.pasta_apagar]) for p in protegidas if str(p).strip()):
                m.pasta_apagar = None
        movimentos = [m for m in movimentos if not (m.status == "limpeza" and any(
            protegido(p, [m.origem]) for p in protegidas if str(p).strip()))]
    if not aplicar:
        return movimentos
    if ao_planejar:
        ao_planejar(movimentos)
    avisar = ao_progresso or (lambda *a: None)

    feitos = []
    apagados: list[Path] = []
    pastas_de_onde_sairam: set[Path] = set()
    parado = False
    for indice, mov in enumerate(movimentos):
        if parar and parar():                                # "Parar": não começa o próximo
            parado = True
            break
        if mov.status == "limpeza":                          # artes de episódios/filmes já movidos
            for antigo, novo in mov.acompanhantes or []:
                if antigo.exists() and novo.parent.is_dir() and not novo.exists():
                    try:
                        shutil.move(str(antigo), str(novo))
                        feitos.append((antigo, novo))
                    except OSError as erro:
                        mov.detalhe = f"não consegui mover {antigo.name}: {erro}"
            continue
        if mov.status != "simulado":
            continue
        pastas_de_onde_sairam.add(mov.origem.parent)
        avisar(indice, mov, 0.0)
        try:
            mov.destino.parent.mkdir(parents=True, exist_ok=True)
            # o vídeo é 95% do trabalho; legendas, imagens e lixo são o resto
            mover_com_progresso(mov.origem, mov.destino, lambda f, i=indice, m=mov: avisar(i, m, f * 0.95), parar)
            feitos.append((mov.origem, mov.destino))
            mov.status = "movido"
            for antigo, novo in mov.acompanhantes or []:
                if novo.exists() or not antigo.exists():
                    continue
                shutil.move(str(antigo), str(novo))
                feitos.append((antigo, novo))
        except InterruptedError:                              # "Parar" no meio de uma cópia grande
            mov.detalhe = "parado no meio da cópia: o original continua onde estava"
            parado = True
            break
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
    pastas_apagadas = (_apagar_pastas_de_origem(movimentos, trailers, origem)
                       if apagar_pasta_origem and not parado else [])   # parado: não apaga pasta nenhuma
    if feitos or apagados or pastas_apagadas:
        _gravar_log(pasta_filmes, feitos, apagados, pastas_apagadas)
        _apagar_pastas_que_esvaziaram(pastas_de_onde_sairam, origem)
    return movimentos


# ----------------------------------------------------------------- pasta com filmes E séries
def eh_episodio_de_serie(video: Path) -> bool:
    """Para separar sozinho: 'S01E02'/'1x02' é série; só o número ('HunterXHunter 01') também,
    desde que não tenha ano de filme ('Rocky.II.1979' continua filme)."""
    if marca_de_episodio(video.name):
        return True
    return episodio_do_video(video) is not None and extrair_titulo_e_ano(video.name).ano is None


def organizar_misto(origem: str | Path, pasta_filmes: str | Path | None, pasta_series: str | Path | None,
                    catalogo: Catalogo | None = None, filtro=None, **opcoes) -> list[Movimento]:
    """Uma pasta de downloads com filmes E séries (ou cada pasta do uTorrent): os episódios vão para
    a biblioteca de Séries (modo séries) e o resto para a de Filmes. Sem uma das bibliotecas, aquele
    tipo fica onde está. `opcoes`: as mesmas de organizar_pasta (aplicar, limpar_lixo...)."""
    regras = opcoes.get("regras", ())

    def eh_serie(v: Path) -> bool:                    # o "Corrigir nome" decide antes do nome do arquivo
        if regra_para(v, regras, "filme"):
            return False
        return regra_para(v, regras, "serie") is not None or eh_episodio_de_serie(v)

    def so(series: bool):
        return lambda v: (filtro is None or filtro(v)) and eh_serie(v) == series
    movimentos = []
    if pasta_series:                                  # séries primeiro: a pasta do torrent esvazia antes
        movimentos += organizar_pasta(origem, pasta_series, catalogo, modo="series", filtro=so(True), **opcoes)
    if pasta_filmes:
        movimentos += organizar_pasta(origem, pasta_filmes, catalogo, modo="filmes", filtro=so(False), **opcoes)
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
        limpeza = mov.status == "limpeza"
        if limpeza:
            mov.status = "erro"                              # vira "pasta_apagada" se der certo
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
            if limpeza:
                mov.status = "pasta_apagada"
        except OSError as erro:
            mov.detalhe = f"não consegui apagar a pasta {pasta.name}: {erro}"
    return apagadas


# ----------------------------------------------------------------- sobras de organizações anteriores
def _historico(pasta_filmes: Path) -> list[tuple[Path, Path]]:
    """(de, para) de todas as organizações registradas em <biblioteca>/.organizador (menos as desfeitas)."""
    itens = []
    for log in sorted((pasta_filmes / PASTA_LOGS).glob("log-*.json")):
        if log.name.endswith(".desfeito.json"):
            continue
        try:
            dados = json.loads(log.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for item in dados if isinstance(dados, list) else dados.get("itens", []):
            try:
                itens.append((Path(item["de"]), Path(item["para"])))
            except (KeyError, TypeError):
                continue
    return itens


def _planejar_sobras(origem: Path, pasta_filmes: Path, videos: list[Path],
                     limite_mb: float = LIMITE_TRAILER_MB) -> list[Movimento]:
    """Pastas de torrent de onde uma organização ANTERIOR (registrada no log) já tirou os vídeos e
    onde só sobrou propaganda ('BLUDV.TV.mp4'), imagens e afins. Cada uma vira um Movimento
    'limpeza' que apaga a pasta; as imagens dos episódios/filmes que saíram dela ('...-poster.jpg')
    vão antes para junto deles. Seguro: só pastas que o próprio organizador esvaziou (log), dentro
    da origem, sem a biblioteca dentro e sem nenhum vídeo de verdade."""
    historico = [(de, para) for de, para in _historico(pasta_filmes) if para.exists() and not de.exists()]
    if not historico:
        return []
    bib = pasta_filmes.resolve()
    destinos = [para.resolve() for _, para in historico]
    por_pasta: dict[Path, list[tuple[Path, Path]]] = {}
    for de, para in historico:
        pasta = _pasta_do_torrent(de, origem)
        if pasta is not None and pasta.is_dir():
            por_pasta.setdefault(pasta, []).append((de, para))
    resolvidos = [(v, v.resolve()) for v in videos]          # uma vez só (pasta de rede é lenta)
    sobras = []
    for pasta, itens in sorted(por_pasta.items()):
        p = pasta.resolve()
        if p == bib or p in bib.parents or any(d == p or p in d.parents for d in destinos):
            continue                                         # a biblioteca (ou um filme) está aqui dentro
        restantes = [v for v, r in resolvidos if p in r.parents]
        propaganda = [v for v in restantes if eh_propaganda_pequena(v, limite_mb)]
        if len(propaganda) != len(restantes):
            continue                                         # ainda tem vídeo de verdade: não mexe
        sobras.append(Movimento(pasta, None, "limpeza", "sobra de uma organização anterior",
                                acompanhantes=_artes_dos_que_sairam(itens), apagar=propaganda,
                                pasta_apagar=pasta))
    return sobras


def _artes_dos_que_sairam(itens: list[tuple[Path, Path]]) -> list[tuple[Path, Path]]:
    """Imagens que ficaram para trás: 'X.S01E01.720p-poster.jpg' -> 'Série S01E01 - Nome-thumb.jpg'
    (miniatura do episódio); 'Filme.2019-poster.jpg' -> 'poster.jpg' na pasta do filme."""
    junto = []
    for de, para in itens:
        if not eh_video(de):
            continue
        for imagem in _arquivos(de.parent):                  # pasta lida uma vez (cache)
            if not imagem_do_video(imagem, de.stem):
                continue
            ext = ".jpg" if imagem.suffix.lower() == ".jpeg" else imagem.suffix.lower()
            if extrair_episodio(para.name):
                novo = para.with_name(f"{para.stem}-thumb{ext}")
            elif arte := tipo_de_arte(imagem):
                novo = para.parent / f"{ARTES[arte]}{ext}"
            else:
                continue
            if not novo.exists() and all(n != novo for _, n in junto):
                junto.append((imagem, novo))
    return junto


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


def mover_com_progresso(de: Path, para: Path, ao_progresso=None, parar=None) -> None:
    """Move um arquivo avisando o andamento (0.0 a 1.0).
    Mesmo disco: só troca o nome (instantâneo). Discos diferentes: copia em blocos de 8 MB
    (para a porcentagem andar de verdade), confere o tamanho e só então apaga o original.
    parar() verdadeiro no meio da cópia: apaga a cópia pela metade e lança InterruptedError."""
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
                if parar and parar():
                    raise InterruptedError("cópia interrompida")
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


def _nota_de_qualidade(mov: Movimento) -> tuple:
    """Para escolher entre cópias: resolução, depois origem (BluRay > WEB > DVD > CAM), depois tamanho."""
    resolucao, fonte, _ = qualidade(mov.origem.name)
    try:
        tamanho = mov.origem.stat().st_size
    except OSError:
        tamanho = 0
    return resolucao, fonte, tamanho


def _rotulo(mov: Movimento) -> str:
    return qualidade(mov.origem.name)[2] or _tamanho_legivel(mov.origem)


def _tamanho_legivel(arquivo: Path) -> str:
    try:
        tamanho = arquivo.stat().st_size
    except OSError:
        return "tamanho desconhecido"
    return f"{tamanho / 1024 ** 3:.1f} GB" if tamanho >= 1024 ** 3 else f"{tamanho / 1024 ** 2:.0f} MB"


def _marcar_destinos_repetidos(movimentos: list[Movimento]) -> None:
    """Duas cópias que virariam o mesmo nome (ex.: Matrix 720p e Matrix 1080p): vai a de MELHOR
    qualidade; as outras ficam como 'conflito', dizendo qual foi no lugar delas."""
    grupos: dict[str, list[Movimento]] = {}
    for mov in movimentos:
        if mov.status == "simulado":
            grupos.setdefault(str(mov.destino).lower(), []).append(mov)
    for copias in grupos.values():
        if len(copias) < 2:
            continue
        melhor = max(copias, key=_nota_de_qualidade)                 # empate: a primeira da lista
        for mov in copias:
            if mov is not melhor:
                mov.status = "conflito"
                mov.detalhe = (f"cópia repetida ({_rotulo(mov)}); vai a melhor ({_rotulo(melhor)}): "
                               f"{melhor.origem.name}")


def _gravar_log(pasta_filmes: Path, feitos: list[tuple[Path, Path]], apagados: list[Path] = (),
                pastas_apagadas: list[Path] = (), extra: dict | None = None) -> Path:
    """extra: chaves do espelho (.strm): strm_criados, pastas_criadas, strm_removidos."""
    pasta = pasta_filmes / PASTA_LOGS
    pasta.mkdir(parents=True, exist_ok=True)
    log = pasta / f"log-{datetime.now():%Y%m%d-%H%M%S-%f}.json"
    log.write_text(json.dumps({"raiz": str(pasta_filmes),
                               "itens": [{"de": str(a), "para": str(b)} for a, b in feitos],
                               "apagados": [str(a) for a in apagados],
                               "pastas_apagadas": [str(p) for p in pastas_apagadas], **(extra or {})},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    return log


EXTRAS_DO_STRM = {".srt", ".ass", ".ssa", ".vtt", ".sub", ".nfo", ".jpg", ".jpeg", ".png", ".webp"}


def _desfazer_espelho(dados: dict, mensagens: list[str]) -> None:
    """Espelho (.strm): apaga os criados (e a legenda/miniatura/.nfo de mesmo nome), as pastas que o
    espelho criou (se não tiverem vídeo dentro) e recria os .strm que o "Conferir espelhos" removeu."""
    for arquivo in map(Path, reversed(dados.get("strm_criados", []))):
        if arquivo.exists():
            arquivo.unlink()
            mensagens.append(f"espelho removido: {arquivo.name}")
        if arquivo.parent.is_dir():
            for extra in arquivo.parent.iterdir():
                if (extra.is_file() and extra.suffix.lower() in EXTRAS_DO_STRM
                        and extra.name.startswith((arquivo.stem + ".", arquivo.stem + "-"))):
                    extra.unlink()
    for pasta in map(Path, dados.get("pastas_criadas", [])):
        if pasta.is_dir() and not any(eh_video_da_biblioteca(a) for a in pasta.rglob("*") if a.is_file()):
            shutil.rmtree(pasta, ignore_errors=True)
            mensagens.append(f"pasta do espelho removida: {pasta.name}")
    for item in dados.get("strm_removidos", []):
        arquivo = Path(item["arquivo"])
        if arquivo.exists():
            continue
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        arquivo.write_text(item["url"] + "\n", encoding="utf-8")
        mensagens.append(f"voltou: {arquivo}")
    for item in reversed(dados.get("espelhos_guardados", [])):     # "Gerenciar espelhos" -> remover
        de, para = Path(item["de"]), Path(item["para"])
        if de.exists() or not para.exists():
            mensagens.append(f"não desfeito ({'já existe' if de.exists() else 'sumiu da lixeira'}): {de}")
            continue
        de.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(para), str(de))
        mensagens.append(f"voltou: {de}")
    for lixeira in [dados.get("lixeira"), *dados.get("lixeiras", [])]:     # removidos/<data> que esvaziou
        if lixeira and Path(lixeira).is_dir() and not any(a.is_file() for a in Path(lixeira).rglob("*")):
            shutil.rmtree(lixeira, ignore_errors=True)


def ultimo_log(pasta_filmes: str | Path) -> Path | None:
    logs = sorted(p for p in (Path(pasta_filmes) / PASTA_LOGS).glob("log-*.json")
                  if not p.name.endswith(".desfeito.json"))           # o desfeito não se desfaz de novo
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
    _desfazer_espelho(dados, mensagens)
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


def agrupar_nao_identificados(movimentos: list[Movimento]) -> list[tuple[Path, list[int]]]:
    """Os não identificados juntos por pasta (os de uma série costumam estar na mesma pasta): [(pasta,
    [índices na lista])], a pasta com mais arquivos primeiro. Assim um "Corrigir nome" resolve o grupo todo."""
    grupos: dict[Path, list[int]] = {}
    for i, m in enumerate(movimentos):
        if m.status == "nao_identificado":
            grupos.setdefault(m.origem.parent, []).append(i)
    return sorted(grupos.items(), key=lambda pi: (-len(pi[1]), str(pi[0]).lower()))
