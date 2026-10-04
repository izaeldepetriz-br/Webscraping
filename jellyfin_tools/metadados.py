"""Melhorias 2 e 3: pôster/backdrop em pt-BR e arquivo .nfo, a partir da API OFICIAL do TMDB.

Por que API e não raspagem do site: os termos do TMDB proíbem raspar o site; a API é gratuita
(https://www.themoviedb.org/settings/api), estável, e é a mesma fonte que o Jellyfin usa.

Um único pedido traz tudo (detalhes em pt-BR + lista de imagens + IDs externos):
    GET /movie/{id}?language=pt-BR&append_to_response=images,external_ids&include_image_language=pt,null

  - poster.jpg   -> pôster em português (pt) mais votado; se não houver, o pôster padrão
  - backdrop.jpg -> plano de fundo SEM texto (idioma "null"), o de maior resolução/voto
  - Nome (Ano).nfo -> <movie> com título, ano, sinopse em português, duração, gêneros e IDs

Imagens que já vieram no torrent têm prioridade: nada é sobrescrito (a não ser que peça).
"""

from __future__ import annotations

import threading
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

import requests

from .registro import obter_logger

log = obter_logger()

URL_IMAGENS = "https://image.tmdb.org/t/p/original"


class ErroMetadados(Exception):
    pass


@dataclass
class ResultadoMetadados:
    pasta: Path
    criados: list[Path] = field(default_factory=list)      # poster.jpg, backdrop.jpg, .nfo
    pulados: list[str] = field(default_factory=list)       # "poster.jpg (já existia)"...
    detalhe: str = ""


class ClienteTMDB:
    def __init__(self, chave: str, idioma: str = "pt-BR", base_url: str = "https://api.themoviedb.org/3",
                 base_imagens: str = URL_IMAGENS, timeout: float = 20, sessao: requests.Session | None = None):
        if not chave:
            raise ErroMetadados("informe a chave da API do TMDB (TMDB_API_KEY)")
        self.idioma = idioma
        self.base_url = base_url.rstrip("/")
        self.base_imagens = base_imagens.rstrip("/")
        self.timeout = timeout
        self._sessao_fixa = sessao
        self._local = threading.local()                    # uma sessão por thread (vários filmes juntos)
        self._cabecalhos: dict = {}
        self.params_auth: dict = {}
        if chave.startswith("eyJ"):                        # "Token de leitura" (v4)
            self._cabecalhos["Authorization"] = f"Bearer {chave}"
        else:                                              # "Chave da API" (v3)
            self.params_auth = {"api_key": chave}

    @property
    def sessao(self) -> requests.Session:
        if self._sessao_fixa is not None:
            return self._sessao_fixa
        if not hasattr(self._local, "sessao"):
            self._local.sessao = requests.Session()
            self._local.sessao.headers.update(self._cabecalhos)
        return self._local.sessao

    def _get(self, caminho: str, **params) -> dict:
        try:
            r = self.sessao.get(f"{self.base_url}{caminho}", params={**params, **self.params_auth},
                                timeout=self.timeout)
        except requests.RequestException as erro:
            raise ErroMetadados(f"TMDB fora do ar ou sem internet: {erro}") from erro
        if r.status_code == 401:
            raise ErroMetadados("TMDB recusou a chave (confira TMDB_API_KEY)")
        if r.status_code == 404:
            raise ErroMetadados("filme não encontrado no TMDB")
        if not r.ok:
            raise ErroMetadados(f"TMDB respondeu HTTP {r.status_code}")
        return r.json()

    def buscar_id(self, titulo: str, ano: int | None) -> int | None:
        """Título + ano -> id do TMDB (o resultado mais relevante do mesmo ano)."""
        params = {"query": titulo, "language": self.idioma}
        if ano:
            params["year"] = ano
        resultados = self._get("/search/movie", **params).get("results") or []
        return resultados[0]["id"] if resultados else None

    def detalhes(self, tmdb_id: int) -> dict:
        return self._get(f"/movie/{tmdb_id}", language=self.idioma, append_to_response="images,external_ids",
                         include_image_language="pt,null")

    def baixar_imagem(self, caminho_tmdb: str, destino: Path) -> None:
        """Baixa para um .part e só renomeia no fim (nada de imagem pela metade)."""
        parcial = destino.with_name(destino.name + ".part")
        try:
            with self.sessao.get(f"{self.base_imagens}{caminho_tmdb}", stream=True, timeout=self.timeout) as r:
                r.raise_for_status()
                with open(parcial, "wb") as f:
                    for bloco in r.iter_content(256 * 1024):
                        f.write(bloco)
            parcial.replace(destino)
        except requests.RequestException as erro:
            raise ErroMetadados(f"falha ao baixar {destino.name}: {erro}") from erro
        finally:
            parcial.unlink(missing_ok=True)


# ----------------------------------------------------------------- escolha das imagens
def escolher_poster(detalhes: dict) -> str | None:
    """Pôster em português (mais votado); se não houver, o pôster padrão do filme."""
    posters = (detalhes.get("images") or {}).get("posters") or []
    em_pt = [p for p in posters if p.get("iso_639_1") == "pt" and p.get("file_path")]
    if em_pt:
        return max(em_pt, key=lambda p: (p.get("vote_average") or 0, p.get("width") or 0))["file_path"]
    return detalhes.get("poster_path")


def escolher_backdrop(detalhes: dict) -> str | None:
    """Plano de fundo sem texto (idioma nulo), o de maior resolução e voto."""
    fundos = (detalhes.get("images") or {}).get("backdrops") or []
    sem_texto = [b for b in fundos if not b.get("iso_639_1") and b.get("file_path")]
    if sem_texto:
        return max(sem_texto, key=lambda b: (b.get("width") or 0, b.get("vote_average") or 0))["file_path"]
    return detalhes.get("backdrop_path")


# ----------------------------------------------------------------- .nfo
def gerar_nfo(detalhes: dict, titulo: str | None = None, ano: int | None = None) -> str:
    """XML no formato <movie> que o Jellyfin (e o Kodi) leem."""
    raiz = ET.Element("movie")

    def tag(nome: str, valor, **atributos) -> None:
        if valor not in (None, "", 0):
            ET.SubElement(raiz, nome, {k: str(v) for k, v in atributos.items()}).text = str(valor)

    data = detalhes.get("release_date") or ""
    tag("title", titulo or detalhes.get("title"))
    tag("originaltitle", detalhes.get("original_title"))
    tag("year", ano or (data[:4] if data[:4].isdigit() else None))
    tag("plot", detalhes.get("overview"))
    tag("outline", detalhes.get("overview"))
    tag("tagline", detalhes.get("tagline"))
    tag("runtime", detalhes.get("runtime"))                          # em minutos
    tag("premiered", data)
    for genero in detalhes.get("genres") or []:
        tag("genre", genero.get("name"))
    for estudio in (detalhes.get("production_companies") or [])[:3]:
        tag("studio", estudio.get("name"))
    tag("uniqueid", detalhes.get("id"), type="tmdb", default="true")
    imdb = detalhes.get("imdb_id") or (detalhes.get("external_ids") or {}).get("imdb_id")
    tag("uniqueid", imdb, type="imdb")
    tag("tmdbid", detalhes.get("id"))
    tag("imdbid", imdb)
    ET.indent(raiz, space="  ")
    return '<?xml version="1.0" encoding="utf-8" standalone="yes"?>\n' + ET.tostring(raiz, encoding="unicode") + "\n"


def nfo_valido(arquivo: Path) -> bool:
    """True se for um .nfo de metadados (<movie>). O .nfo de "informações do release" que vem
    em torrents é texto solto: esse pode ser substituído."""
    try:
        return ET.parse(arquivo).getroot().tag == "movie"
    except (ET.ParseError, OSError):
        return False


# ----------------------------------------------------------------- tudo junto
def enriquecer_filme(pasta: Path, nome_base: str, cliente: ClienteTMDB, titulo: str, ano: int | None,
                     tmdb_id: int | None = None, imagens: bool = True, nfo: bool = True,
                     sobrescrever: bool = False) -> ResultadoMetadados:
    """Baixa poster.jpg/backdrop.jpg (se faltarem) e escreve 'Nome (Ano).nfo' na pasta do filme."""
    resultado = ResultadoMetadados(pasta)
    tmdb_id = tmdb_id or cliente.buscar_id(titulo, ano)
    if not tmdb_id:
        resultado.detalhe = "filme não encontrado no TMDB"
        log.warning("Metadados: '%s (%s)' não encontrado no TMDB", titulo, ano)
        return resultado
    detalhes = cliente.detalhes(tmdb_id)

    if imagens:
        for nome, escolher in (("poster", escolher_poster), ("backdrop", escolher_backdrop)):
            existente = next((p for p in pasta.glob(f"{nome}.*") if p.suffix.lower() in (".jpg", ".png", ".webp")),
                             None)
            if existente and not sobrescrever:
                resultado.pulados.append(f"{existente.name} (já existia)")   # a do torrent tem prioridade
                continue
            caminho_tmdb = escolher(detalhes)
            if not caminho_tmdb:
                resultado.pulados.append(f"{nome}.jpg (o TMDB não tem)")
                continue
            destino = pasta / f"{nome}.jpg"
            cliente.baixar_imagem(caminho_tmdb, destino)
            resultado.criados.append(destino)

    if nfo:
        destino = pasta / f"{nome_base}.nfo"
        if destino.exists() and not sobrescrever and nfo_valido(destino):
            resultado.pulados.append(f"{destino.name} (já existia)")
        else:
            destino.write_text(gerar_nfo(detalhes, titulo, ano), encoding="utf-8")
            resultado.criados.append(destino)

    log.info("Metadados de %s: criados %s%s", nome_base, [p.name for p in resultado.criados] or "nada",
             f"; pulados {resultado.pulados}" if resultado.pulados else "")
    return resultado
