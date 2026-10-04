"""Arquivos que vêm junto com o filme (torrents): legendas, imagens de arte e lixo.

  Creed.II.FORCED.srt      -> Creed II (2018).pt-BR.forced.srt
  Creed.II.ENG.srt         -> Creed II (2018).en.srt
  Creed.II-poster.jpg      -> poster.jpg        (padrão de imagens locais do Jellyfin)
  BLUDV.TV.url, Leia.txt   -> apagados
  Trailer pequeno (<100MB) -> apagado

Regras de segurança para APAGAR (é irreversível):
  - Pasta só do filme (ex.: Downloads/Creed.II.2018.1080p/): .url/.txt e vídeos pequenos de propaganda.
  - Pasta raiz (ex.: Downloads/ com vários filmes soltos): só o que TEM CARA de propaganda
    (nome com site, "Leia", "Visite", "trailer"...). Um "minhas_notas.txt" nunca é apagado.
  - Vídeo pequeno só é "trailer" se houver um vídeo MAIOR (o filme) na mesma pasta.
  - Modo séries: vídeos nunca são apagados (episódios curtos são normais).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from .nomes import eh_video, extrair_titulo_e_ano, normalizar, similaridade, tem_site

EXTENSOES_LEGENDA = {".srt", ".ass", ".ssa", ".sub", ".idx", ".vtt"}
EXTENSOES_IMAGEM = {".jpg", ".jpeg", ".png", ".webp"}
EXTENSOES_LIXO = {".url", ".txt", ".lnk", ".website", ".webloc"}
LIMITE_TRAILER_MB = 100

# sufixo no nome da imagem -> nome que o Jellyfin entende
ARTES = {"poster": "poster", "folder": "poster", "cover": "poster", "backdrop": "backdrop",
         "fanart": "backdrop", "landscape": "landscape", "logo": "logo", "clearlogo": "logo", "banner": "banner"}

# palavras no nome da legenda -> código de idioma (sem nenhuma: pt-BR)
IDIOMAS = (("en", {"en", "eng", "english", "ingles"}),
           ("es", {"es", "spa", "spanish", "espanol", "esp"}),
           ("fr", {"fr", "fre", "fra", "french", "frances"}),
           ("it", {"ita", "italian", "italiano"}),
           ("de", {"ger", "deu", "german", "alemao"}),
           ("pt-BR", {"pt", "br", "ptbr", "por", "pob", "portugues", "portuguese", "brazilian"}))
PALAVRAS_FORCADA = {"forced", "forcada", "forcadas", "forcado", "forcados"}
PALAVRAS_PROPAGANDA = {"leia", "leiame", "readme", "visite", "acesse", "www", "trailer", "teaser", "promo",
                       "propaganda", "sample", "torrent", "torrents", "download", "baixe", "site"}
SIMILARIDADE_EXTRA = 0.8


@dataclass
class PlanoExtras:
    mover: list[tuple[Path, Path]] = field(default_factory=list)   # (de, para): legendas, imagens, .nfo


def _palavras(arquivo: Path) -> set[str]:
    return set(normalizar(arquivo.stem).split())


def parece_propaganda(arquivo: Path) -> bool:
    """Nome com site (www., .tv, .com) ou palavras típicas ("Leia", "Visite", "trailer"...)."""
    return tem_site(arquivo.stem) or bool(_palavras(arquivo) & PALAVRAS_PROPAGANDA)


# ----------------------------------------------------------------- cache de pastas
# Com 166 filmes na mesma pasta, cada vídeo listava a pasta inteira de novo (e o tamanho de cada
# arquivo): milhares de consultas ao disco. Agora cada pasta é lida UMA vez por execução.
# organizar_pasta() chama limpar_cache() no começo, porque os arquivos mudam entre execuções.
_arquivos_da_pasta: dict[Path, dict[Path, int]] = {}


def limpar_cache() -> None:
    _arquivos_da_pasta.clear()
    _resolver.cache_clear()


@lru_cache(maxsize=4096)
def _resolver(pasta: Path) -> Path:
    return pasta.resolve()


def _arquivos(pasta: Path) -> dict[Path, int]:
    """{arquivo: tamanho} da pasta, lido uma vez. os.scandir já traz o tamanho junto
    (no Windows sem consultar arquivo por arquivo), muito mais rápido que iterdir() + stat()."""
    if pasta not in _arquivos_da_pasta:
        arquivos = {}
        try:
            with os.scandir(pasta) as itens:
                for item in itens:
                    try:
                        if item.is_file():
                            arquivos[Path(item.path)] = item.stat().st_size
                    except OSError:
                        continue
        except OSError:
            pass
        _arquivos_da_pasta[pasta] = dict(sorted(arquivos.items()))
    return _arquivos_da_pasta[pasta]


def _tamanho(arquivo: Path) -> int:
    tamanho = _arquivos(arquivo.parent).get(arquivo)
    if tamanho is None:
        try:
            return arquivo.stat().st_size
        except OSError:
            return 0
    return tamanho


def eh_trailer(video: Path, raiz: Path, limite_mb: float = LIMITE_TRAILER_MB) -> bool:
    """Vídeo pequeno de propaganda/trailer que acompanha um filme maior na mesma pasta."""
    limite = limite_mb * 1024 * 1024
    if _tamanho(video) >= limite:
        return False
    tem_filme_maior = any(eh_video(v) and v != video and tamanho >= limite
                          for v, tamanho in _arquivos(video.parent).items())
    if not tem_filme_maior:
        return False
    if _resolver(video.parent) == _resolver(raiz):         # pasta raiz: só com cara de propaganda
        return parece_propaganda(video)
    return parece_propaganda(video) or extrair_titulo_e_ano(video.name).ano is None


def eh_lixo(arquivo: Path, raiz: Path) -> bool:
    """.url/.txt/atalhos. Na pasta raiz, só se tiver cara de propaganda."""
    if arquivo.suffix.lower() not in EXTENSOES_LIXO:
        return False
    if _resolver(arquivo.parent) == _resolver(raiz):
        return parece_propaganda(arquivo)
    return True


def nome_da_legenda(legenda: Path, nome_base: str) -> str:
    """'Creed.II.FORCED.srt' -> 'Creed II (2018).pt-BR.forced.srt'."""
    palavras = _palavras(legenda)
    idioma = next((codigo for codigo, chaves in IDIOMAS if palavras & chaves), "pt-BR")
    forcada = ".forced" if palavras & PALAVRAS_FORCADA else ""
    return f"{nome_base}.{idioma}{forcada}{legenda.suffix.lower()}"


def tipo_de_arte(imagem: Path) -> str | None:
    """'Creed.II-poster.jpg' -> 'poster';  'poster.jpg' -> 'poster';  'cena01.jpg' -> None."""
    if imagem.suffix.lower() not in EXTENSOES_IMAGEM:
        return None
    nome = imagem.stem.lower()
    for chave in ARTES:
        if nome == chave or any(nome.endswith(sep + chave) for sep in ("-", ".", "_", " ")):
            return chave
    return None


def _mesmo_filme(extra: Path, titulo_video: str, prefixo: str | None = None) -> bool:
    """O extra (legenda/imagem solta numa pasta com vários filmes) é deste filme? Compara pelo título."""
    texto = prefixo if prefixo is not None else extra.name
    titulo_extra = extrair_titulo_e_ano(texto + ".mkv" if prefixo is not None else texto).titulo
    if not titulo_extra:
        return False
    # Filtro barato antes da comparação cara: títulos do mesmo filme começam igual
    # ("Matrix..." nunca é "Cidade de Deus..."). Corta milhares de comparações numa pasta cheia.
    if normalizar(titulo_extra)[:3] != normalizar(titulo_video)[:3]:
        return False
    return similaridade(titulo_extra, titulo_video) >= SIMILARIDADE_EXTRA


def planejar_extras(video: Path, nome_base: str, pasta_destino: Path, raiz: Path | None,
                    modo: str = "filmes", limite_mb: float = LIMITE_TRAILER_MB) -> PlanoExtras:
    """Decide quais legendas/imagens/.nfo da pasta do vídeo vão junto e com que nome."""
    plano = PlanoExtras()
    pasta = video.parent
    titulo_video = extrair_titulo_e_ano(video.name).titulo
    arquivos = _arquivos(pasta)
    # "Pasta exclusiva": subpasta (não a raiz) com um único filme -> tudo nela é deste filme.
    exclusiva = False
    if raiz is not None and _resolver(pasta) != _resolver(raiz):
        videos_da_pasta = [v for v in arquivos if eh_video(v)
                           and not (modo == "filmes" and eh_trailer(v, raiz, limite_mb))]
        exclusiva = len(videos_da_pasta) == 1
    usados: set[str] = set()

    def adicionar(origem: Path, nome_novo: str) -> None:
        if nome_novo.lower() not in usados:                 # duas legendas com o mesmo destino: fica a 1ª
            usados.add(nome_novo.lower())
            plano.mover.append((origem, pasta_destino / nome_novo))

    for extra in arquivos:
        if extra == video:
            continue
        mesmo_prefixo = extra.name.startswith(video.stem + ".")
        ext = extra.suffix.lower()
        if ext in EXTENSOES_LEGENDA:
            if mesmo_prefixo or exclusiva or (modo == "filmes" and _mesmo_filme(extra, titulo_video)):
                adicionar(extra, nome_da_legenda(extra, nome_base))
        elif ext == ".nfo" and mesmo_prefixo:
            adicionar(extra, f"{nome_base}{extra.name[len(video.stem):]}")
        elif modo == "filmes" and (arte := tipo_de_arte(extra)):
            prefixo = extra.stem[: len(extra.stem) - len(arte)].rstrip("-._ ")
            if exclusiva or (prefixo and _mesmo_filme(extra, titulo_video, prefixo)):
                extensao = ".jpg" if ext == ".jpeg" else ext
                adicionar(extra, f"{ARTES[arte]}{extensao}")
    return plano


def lixo_da_pasta(pasta: Path, raiz: Path, modo: str = "filmes",
                  limite_mb: float = LIMITE_TRAILER_MB) -> list[Path]:
    """Arquivos a apagar numa pasta de onde um filme está saindo."""
    lixo = []
    for arquivo in _arquivos(pasta):
        if eh_lixo(arquivo, raiz) or (modo == "filmes" and eh_video(arquivo) and eh_trailer(arquivo, raiz, limite_mb)):
            lixo.append(arquivo)
    return lixo
