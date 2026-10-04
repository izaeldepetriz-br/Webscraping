"""Confirma o título e o ano corretos de um filme.

- CatalogoLocal: lista em JSON (busca "estruturada" simulada, funciona offline).
Serve para filmes e séries (tipo="serie").

- CatalogoTMDB: API oficial do The Movie Database, a mesma fonte que o Jellyfin usa.
  Precisa de uma chave gratuita: https://www.themoviedb.org/settings/api
  (Usar a API oficial é o jeito permitido; raspar o site do TMDB/IMDb viola os termos de uso.)
"""

from __future__ import annotations

import json
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

    def nomes(self) -> list[str]:
        return [n for n in (self.titulo, self.titulo_original, *self.alternativos) if n]


class Catalogo:
    """Interface: todo catálogo tem buscar(titulo, ano, tipo) -> Filme ou None."""

    def buscar(self, titulo: str, ano: int | None, tipo: str = "filme") -> Filme | None:
        raise NotImplementedError


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


class CatalogoTMDB(Catalogo):
    def __init__(self, chave: str, idioma: str = "pt-BR",
                 base_url: str = "https://api.themoviedb.org/3",
                 sessao: requests.Session | None = None, timeout: float = 15,
                 minimo: float = SIMILARIDADE_MINIMA):
        if not chave:
            raise ErroCatalogo("informe a chave da API do TMDB (variável TMDB_API_KEY)")
        self.idioma = idioma
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.minimo = minimo
        self.sessao = sessao or requests.Session()
        self.params_auth: dict = {}
        if chave.startswith("eyJ"):        # "Token de leitura" (v4) vai no cabeçalho
            self.sessao.headers["Authorization"] = f"Bearer {chave}"
        else:                              # "Chave da API" (v3) vai na URL
            self.params_auth = {"api_key": chave}

    def _pesquisar(self, titulo: str, ano: int | None, tipo: str = "filme") -> list[dict]:
        params = {"query": titulo, "language": self.idioma, "include_adult": "false", **self.params_auth}
        if ano:
            params["year" if tipo == "filme" else "first_air_date_year"] = ano
        caminho = "/search/movie" if tipo == "filme" else "/search/tv"
        try:
            r = self.sessao.get(f"{self.base_url}{caminho}", params=params, timeout=self.timeout)
        except requests.RequestException as erro:
            raise ErroCatalogo(f"TMDB fora do ar ou sem internet: {erro}") from erro
        if r.status_code == 401:
            raise ErroCatalogo("TMDB recusou a chave (401). Confira TMDB_API_KEY.")
        if r.status_code == 429:
            raise ErroCatalogo("TMDB: muitas consultas seguidas (429). Espere um pouco.")
        if not r.ok:
            raise ErroCatalogo(f"TMDB respondeu HTTP {r.status_code}")
        try:
            return r.json().get("results", [])
        except ValueError as erro:
            raise ErroCatalogo("TMDB devolveu uma resposta inválida") from erro

    def buscar(self, titulo: str, ano: int | None, tipo: str = "filme") -> Filme | None:
        if not titulo:
            return None
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
                          titulo_original=r.get(k_original, ""), tmdb_id=r.get("id"), tipo=tipo)
            if not filme.titulo:
                continue
            nota = _pontuar(filme, titulo, ano)
            if nota > nota_melhor:
                melhor, nota_melhor = filme, nota
        return melhor if nota_melhor >= self.minimo else None


class CatalogoEmCadeia(Catalogo):
    """Tenta vários catálogos em ordem (ex.: primeiro o local, depois o TMDB)."""

    def __init__(self, *catalogos: Catalogo):
        self.catalogos = catalogos

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
