"""Confirma o título e o ano corretos de um filme.

- CatalogoLocal: lista em JSON (busca "estruturada" simulada, funciona offline).
Serve para filmes e séries (tipo="serie").

- CatalogoTMDB: API oficial do The Movie Database, a mesma fonte que o Jellyfin usa.
  Precisa de uma chave gratuita: https://www.themoviedb.org/settings/api
  (Usar a API oficial é o jeito permitido; raspar o site do TMDB/IMDb viola os termos de uso.)

Velocidade com o TMDB: cada consulta espera a internet (~0,2 s). Com 166 filmes, uma de cada vez
levava ~30 s. pre_buscar() faz as consultas em paralelo (6 ao mesmo tempo) ANTES de planejar, e
as respostas ficam guardadas: o "Organizar" logo depois da prévia não consulta de novo.
"""

from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import requests

from .nomes import similaridade

ARQUIVO_PADRAO = Path(__file__).with_name("catalogo_filmes.json")
SIMILARIDADE_MINIMA = 0.75


class ErroCatalogo(Exception):
    """Falha ao consultar um catálogo (rede, chave inválida...)."""


@dataclass(frozen=True)
class Filme:
    titulo: str                       # nome que vai para a pasta (ex.: "O Poderoso Chefão")
    ano: int
    titulo_original: str = ""
    tmdb_id: int | None = None
    alternativos: tuple[str, ...] = field(default=())
    tipo: str = "filme"               # "filme" ou "serie" (para séries, ano = ano de estreia)
    fonte: str = field(default="catálogo", compare=False)   # de onde veio o nome: "catálogo" ou "TMDB"

    def nomes(self) -> list[str]:
        return [n for n in (self.titulo, self.titulo_original, *self.alternativos) if n]


class Catalogo:
    """Interface: todo catálogo tem buscar(titulo, ano, tipo) -> Filme ou None."""

    def buscar(self, titulo: str, ano: int | None, tipo: str = "filme") -> Filme | None:
        raise NotImplementedError

    def pre_buscar(self, consultas, ao_progresso=None) -> None:
        """Adianta as buscas [(titulo, ano, tipo)] de uma vez (só faz algo em catálogos online)."""

    @property
    def usa_tmdb(self) -> bool:
        return False

    def nome_episodio(self, serie: Filme, temporada: int, episodio: int) -> str | None:
        """Título do episódio (ex.: 'Segredos'), ou None se o catálogo não souber."""
        return None

    def pre_buscar_episodios(self, pedidos, ao_progresso=None) -> None:
        """Adianta nome_episodio() de várias temporadas: pedidos [(serie, temporada)]."""


def _pontuar(filme: Filme, titulo: str, ano: int | None) -> float:
    nota = max(similaridade(titulo, n) for n in filme.nomes())
    if ano is not None:
        diferenca = abs(filme.ano - ano)
        if diferenca > 1:
            return 0.0               # ano muito diferente: é outro filme (refilmagem, sequência...)
        nota -= 0.05 * diferenca     # lançamentos às vezes têm o ano de estreia em outro país
    return nota


class CatalogoLocal(Catalogo):
    def __init__(self, filmes: list[Filme], minimo: float = SIMILARIDADE_MINIMA):
        self.filmes = list(filmes)
        self.minimo = minimo

    @classmethod
    def de_json(cls, caminho: str | Path) -> "CatalogoLocal":
        try:
            dados = json.loads(Path(caminho).read_text(encoding="utf-8"))
            filmes = [Filme(titulo=d["titulo"], ano=int(d["ano"]),
                            titulo_original=d.get("titulo_original", ""),
                            tmdb_id=d.get("tmdb_id"),
                            alternativos=tuple(d.get("alternativos", ())),
                            tipo=d.get("tipo", "filme")) for d in dados]
        except (OSError, ValueError, KeyError, TypeError) as erro:
            raise ErroCatalogo(f"catálogo inválido em {caminho}: {erro}") from erro
        return cls(filmes)

    @classmethod
    def padrao(cls) -> "CatalogoLocal":
        """Catálogo de exemplo que vem com o projeto (edite catalogo_filmes.json para crescer)."""
        return cls.de_json(ARQUIVO_PADRAO)

    def buscar(self, titulo: str, ano: int | None, tipo: str = "filme") -> Filme | None:
        if not titulo:
            return None
        melhor, nota_melhor = None, 0.0
        for filme in self.filmes:
            if filme.tipo != tipo:
                continue
            nota = _pontuar(filme, titulo, ano)
            if nota > nota_melhor:
                melhor, nota_melhor = filme, nota
        return melhor if nota_melhor >= self.minimo else None


def _segundos(texto: str | None, maximo: float = 3) -> float:
    try:
        return min(max(float(texto or 1), 0), maximo)
    except ValueError:
        return 1


# "Episódio 7" / "Episode 7": o TMDB ainda não tem o nome traduzido -> melhor só o número
_RE_EPISODIO_GENERICO = re.compile(r"^\s*(epis[oó]dio|episode|ep\.?|cap[ií]tulo)\s*\d+\s*$", re.IGNORECASE)


class CatalogoTMDB(Catalogo):
    # Respostas guardadas para a sessão inteira do programa (todas as instâncias):
    # (endereço, chave, idioma, título, ano, tipo) -> Filme ou None
    _cache: dict = {}
    _trava_cache = threading.Lock()
    TRABALHADORES = 6                    # consultas ao mesmo tempo (o TMDB aceita ~40 por segundo)

    def __init__(self, chave: str, idioma: str = "pt-BR",
                 base_url: str = "https://api.themoviedb.org/3",
                 sessao: requests.Session | None = None, timeout: float = 15,
                 minimo: float = SIMILARIDADE_MINIMA):
        if not chave:
            raise ErroCatalogo("informe a chave da API do TMDB (variável TMDB_API_KEY)")
        self.chave = chave
        self.idioma = idioma
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.minimo = minimo
        self._sessao_fixa = sessao
        self._local = threading.local()            # uma sessão por thread (consultas em paralelo)
        self._cabecalhos: dict = {}
        self.params_auth: dict = {}
        self._erro_grave: str = ""                 # chave recusada/sem internet: não insiste 166 vezes
        if chave.startswith("eyJ"):        # "Token de leitura" (v4) vai no cabeçalho
            self._cabecalhos["Authorization"] = f"Bearer {chave}"
        else:                              # "Chave da API" (v3) vai na URL
            self.params_auth = {"api_key": chave}
        if sessao is not None:
            sessao.headers.update(self._cabecalhos)

    @property
    def usa_tmdb(self) -> bool:
        return True

    @property
    def erro(self) -> str:
        """Chave recusada ou sem internet (vazio se está tudo bem)."""
        return self._erro_grave

    @property
    def sessao(self) -> requests.Session:
        if self._sessao_fixa is not None:
            return self._sessao_fixa
        if not hasattr(self._local, "sessao"):
            self._local.sessao = requests.Session()
            self._local.sessao.headers.update(self._cabecalhos)
        return self._local.sessao

    @classmethod
    def limpar_cache(cls) -> None:
        with cls._trava_cache:
            cls._cache.clear()

    def _get(self, caminho: str, params: dict) -> requests.Response:
        try:
            return self.sessao.get(f"{self.base_url}{caminho}", params={**params, **self.params_auth},
                                   timeout=self.timeout)
        except requests.RequestException as erro:
            raise ErroCatalogo(f"TMDB fora do ar ou sem internet: {erro}") from erro

    def testar(self) -> str:
        """Confere a chave e a conexão (GET /configuration). Devolve um texto curto ou levanta ErroCatalogo."""
        r = self._get("/configuration", {})
        if r.status_code == 401:
            raise ErroCatalogo("o TMDB recusou a chave (401). Confira se copiou a chave inteira")
        if not r.ok:
            raise ErroCatalogo(f"o TMDB respondeu HTTP {r.status_code}")
        tipo = "token de leitura (v4)" if self._cabecalhos else "chave da API (v3)"
        return f"conectado ao TMDB com a {tipo}"

    def _pesquisar(self, titulo: str, ano: int | None, tipo: str = "filme") -> list[dict]:
        params = {"query": titulo, "language": self.idioma, "include_adult": "false"}
        if ano:
            params["year" if tipo == "filme" else "first_air_date_year"] = ano
        caminho = "/search/movie" if tipo == "filme" else "/search/tv"
        try:
            r = self._get(caminho, params)
            if r.status_code == 429:                       # pediu calma: espera um pouco e tenta 1 vez
                time.sleep(_segundos(r.headers.get("Retry-After")))
                r = self._get(caminho, params)
        except ErroCatalogo as erro:
            self._erro_grave = str(erro)
            raise
        if r.status_code == 401:
            self._erro_grave = "TMDB recusou a chave (401). Confira TMDB_API_KEY."
            raise ErroCatalogo(self._erro_grave)
        if r.status_code == 429:
            raise ErroCatalogo("TMDB: muitas consultas seguidas (429). Espere um pouco.")
        if not r.ok:
            raise ErroCatalogo(f"TMDB respondeu HTTP {r.status_code}")
        try:
            return r.json().get("results", [])
        except ValueError as erro:
            raise ErroCatalogo("TMDB devolveu uma resposta inválida") from erro

    def _chave_cache(self, titulo: str, ano: int | None, tipo: str) -> tuple:
        return (self.base_url, self.chave, self.idioma, titulo, ano, tipo)

    def buscar(self, titulo: str, ano: int | None, tipo: str = "filme") -> Filme | None:
        if not titulo:
            return None
        chave = self._chave_cache(titulo, ano, tipo)
        with self._trava_cache:
            if chave in self._cache:
                return self._cache[chave]
        if self._erro_grave:                       # já falhou feio: não espera a internet de novo
            raise ErroCatalogo(self._erro_grave)
        filme = self._buscar_sem_cache(titulo, ano, tipo)
        with self._trava_cache:
            self._cache[chave] = filme
        return filme

    def pre_buscar(self, consultas, ao_progresso=None) -> None:
        """Faz as buscas em paralelo e guarda as respostas. ao_progresso(feitas, total).
        Erros não interrompem: o planejar() mostra o motivo no item."""
        unicas = list(dict.fromkeys((t, a, tp) for t, a, tp in consultas if t))
        with self._trava_cache:
            faltam = [c for c in unicas if self._chave_cache(*c) not in self._cache]
        if not faltam:
            return

        def uma(consulta):
            if self._erro_grave:
                return
            try:
                self.buscar(*consulta)
            except ErroCatalogo:
                pass

        with ThreadPoolExecutor(max_workers=min(self.TRABALHADORES, len(faltam))) as executor:
            for feitas, _ in enumerate(executor.map(uma, faltam), 1):
                if ao_progresso:
                    ao_progresso(feitas, len(faltam))

    # ------------------------------------------------------------- nomes dos episódios
    def _chave_temporada(self, tmdb_id: int, temporada: int) -> tuple:
        return (self.base_url, self.chave, self.idioma, "temporada", tmdb_id, temporada)

    def _episodios_da_temporada(self, tmdb_id: int, temporada: int) -> dict[int, str]:
        """{número: nome} de uma temporada inteira (UM pedido por temporada, guardado no cache)."""
        chave = self._chave_temporada(tmdb_id, temporada)
        with self._trava_cache:
            if chave in self._cache:
                return self._cache[chave]
        if self._erro_grave:
            return {}
        try:
            r = self._get(f"/tv/{tmdb_id}/season/{temporada}", {"language": self.idioma})
        except ErroCatalogo:
            return {}                                      # sem nome: o arquivo fica só com o número
        nomes = {}
        if r.ok:
            try:
                for ep in r.json().get("episodes") or []:
                    nome = (ep.get("name") or "").strip()
                    if ep.get("episode_number") is not None and nome and not _RE_EPISODIO_GENERICO.match(nome):
                        nomes[int(ep["episode_number"])] = nome
            except (ValueError, TypeError, AttributeError):
                nomes = {}
        if r.ok or r.status_code == 404:                   # 404 = temporada que o TMDB não tem
            with self._trava_cache:
                self._cache[chave] = nomes
        return nomes

    def nome_episodio(self, serie: Filme, temporada: int, episodio: int) -> str | None:
        if not serie or not serie.tmdb_id:
            return None
        return self._episodios_da_temporada(serie.tmdb_id, temporada).get(episodio)

    def pre_buscar_episodios(self, pedidos, ao_progresso=None) -> None:
        temporadas = list(dict.fromkeys((serie.tmdb_id, temporada) for serie, temporada in pedidos
                                        if serie and serie.tmdb_id))
        with self._trava_cache:
            faltam = [t for t in temporadas if self._chave_temporada(*t) not in self._cache]
        if not faltam:
            return
        with ThreadPoolExecutor(max_workers=min(self.TRABALHADORES, len(faltam))) as executor:
            for feitas, _ in enumerate(executor.map(lambda t: self._episodios_da_temporada(*t), faltam), 1):
                if ao_progresso:
                    ao_progresso(feitas, len(faltam))

    def _buscar_sem_cache(self, titulo: str, ano: int | None, tipo: str) -> Filme | None:
        resultados = self._pesquisar(titulo, ano, tipo)
        if not resultados and ano:
            resultados = self._pesquisar(titulo, None, tipo)     # tenta sem o ano
        # Filmes usam title/release_date; séries usam name/first_air_date.
        k_titulo, k_original, k_data = (("title", "original_title", "release_date") if tipo == "filme"
                                        else ("name", "original_name", "first_air_date"))
        melhor, nota_melhor = None, 0.0
        for r in resultados:
            data = r.get(k_data) or ""
            if len(data) < 4 or not data[:4].isdigit():
                continue
            filme = Filme(titulo=r.get(k_titulo) or r.get(k_original, ""), ano=int(data[:4]),
                          titulo_original=r.get(k_original, ""), tmdb_id=r.get("id"), tipo=tipo,
                          fonte="TMDB")
            if not filme.titulo:
                continue
            nota = _pontuar(filme, titulo, ano)
            if nota > nota_melhor:
                melhor, nota_melhor = filme, nota
        return melhor if nota_melhor >= self.minimo else None


def _achou(catalogo: Catalogo, consulta) -> bool:
    try:
        return catalogo.buscar(*consulta) is not None
    except ErroCatalogo:
        return False


class CatalogoEmCadeia(Catalogo):
    """Tenta vários catálogos em ordem (ex.: primeiro o local, depois o TMDB)."""

    def __init__(self, *catalogos: Catalogo):
        self.catalogos = catalogos

    @property
    def usa_tmdb(self) -> bool:
        return any(c.usa_tmdb for c in self.catalogos)

    def nome_episodio(self, serie: Filme, temporada: int, episodio: int) -> str | None:
        for catalogo in self.catalogos:
            nome = catalogo.nome_episodio(serie, temporada, episodio)
            if nome:
                return nome
        return None

    def pre_buscar_episodios(self, pedidos, ao_progresso=None) -> None:
        for catalogo in self.catalogos:
            catalogo.pre_buscar_episodios(pedidos, ao_progresso)

    def pre_buscar(self, consultas, ao_progresso=None) -> None:
        """Cada catálogo só adianta o que os anteriores não acharam (o local é instantâneo)."""
        restantes = list(consultas)
        for n, catalogo in enumerate(self.catalogos):
            catalogo.pre_buscar(restantes, ao_progresso)
            if n < len(self.catalogos) - 1:
                restantes = [c for c in restantes if not _achou(catalogo, c)]

    def buscar(self, titulo: str, ano: int | None, tipo: str = "filme") -> Filme | None:
        erros = []
        for catalogo in self.catalogos:
            try:
                filme = catalogo.buscar(titulo, ano, tipo)
            except ErroCatalogo as erro:
                erros.append(str(erro))
                continue
            if filme:
                return filme
        if erros and len(erros) == len(self.catalogos):
            raise ErroCatalogo("; ".join(erros))
        return None
