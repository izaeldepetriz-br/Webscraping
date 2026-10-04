"""Lê nomes de arquivo bagunçados e monta nomes no padrão do Jellyfin. Não acessa a internet."""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path
from typing import NamedTuple, Optional

EXTENSOES_VIDEO = {".mp4", ".mkv", ".avi", ".mov", ".m4v", ".wmv", ".m2ts", ".webm", ".mpg", ".mpeg"}
# Arquivos que "acompanham" o vídeo e devem ir junto (legendas, metadados).
EXTENSOES_ACOMPANHANTES = {".srt", ".ass", ".ssa", ".sub", ".idx", ".vtt", ".nfo"}

# Depois destas etiquetas técnicas só vem informação de release (qualidade, codec, grupo).
ETIQUETAS_TECNICAS = {
    "480p", "576p", "720p", "1080p", "1080i", "2160p", "4k", "uhd", "hd", "fullhd", "fhd",
    "bluray", "blu", "ray", "brrip", "bdrip", "bdremux", "remux", "webrip", "webdl", "web", "dl",
    "hdrip", "dvdrip", "dvdscr", "hdtv", "hdcam", "cam", "ts", "x264", "x265", "h264", "h265",
    "hevc", "avc", "xvid", "divx", "aac", "ac3", "eac3", "dts", "ddp", "dd5", "atmos", "truehd",
    "10bit", "8bit", "hdr", "hdr10", "dv", "sdr", "proper", "repack", "extended", "unrated",
    "imax", "remastered", "yts", "yify", "rarbg",
}
# Palavras comuns em nomes "caseiros" que não fazem parte do título.
PALAVRAS_RUIDO = {
    "filme", "completo", "dublado", "dub", "legendado", "leg", "dual", "audio", "nacional",
    "portugues", "pt", "br", "ptbr", "torrent", "download", "baixar", "full", "movie",
}
PALAVRAS_PEQUENAS = {"de", "da", "do", "das", "dos", "e", "o", "a", "os", "as", "em", "no", "na",
                     "nos", "nas", "um", "uma", "of", "the", "and", "an", "in", "on", "at", "to"}

_RE_ANO = re.compile(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)")
_RE_SEPARADORES = re.compile(r"[._\-\s\[\]\(\)\{\}+]+")
# Caracteres proibidos em nomes de arquivo no Windows (e problemáticos no Jellyfin).
_RE_PROIBIDOS = re.compile(r'[<>"/\\|?*\x00-\x1f]')


class NomeExtraido(NamedTuple):
    """Tupla com nome: dá para usar r.titulo ou desempacotar  titulo, ano = r"""
    titulo: str          # já "limpo", mas ainda pode ter erros de digitação/acentos
    ano: Optional[int]


def sem_acentos(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


def normalizar(texto: str) -> str:
    """'O Poderoso Chefão!' -> 'o poderoso chefao' (para comparar textos)."""
    texto = sem_acentos(texto).lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", texto).split())


def similaridade(a: str, b: str) -> float:
    """0.0 (nada a ver) a 1.0 (iguais), ignorando acentos, pontuação e maiúsculas."""
    return SequenceMatcher(None, normalizar(a), normalizar(b)).ratio()


def eh_video(caminho: Path) -> bool:
    return caminho.suffix.lower() in EXTENSOES_VIDEO


def extrair_titulo_e_ano(nome_arquivo: str) -> NomeExtraido:
    """'Matrix.1999.1080p.BluRay.x264-VERSAO.mp4' -> NomeExtraido('Matrix', 1999)
       'interestellar_filme_completo_dublado_2014.mkv' -> NomeExtraido('interestellar', 2014)
    """
    caminho = Path(nome_arquivo)
    base = caminho.stem if caminho.suffix.lower() in EXTENSOES_VIDEO | EXTENSOES_ACOMPANHANTES \
        else caminho.name
    texto = _RE_SEPARADORES.sub(" ", base).strip()

    # O ano é o ÚLTIMO ano plausível que não está no começo (ex.: "1917 2019" -> 2019;
    # "Blade Runner 2049 2017" -> 2017, porque 2049 está no futuro).
    limite = date.today().year + 1
    anos = [(m.start(), int(m.group())) for m in _RE_ANO.finditer(texto)
            if 1900 <= int(m.group()) <= limite]
    ano = None
    antes = texto
    for posicao, valor in reversed(anos):
        if posicao > 0:
            ano, antes = valor, texto[:posicao]
            break

    palavras = []
    for palavra in antes.split():
        chave = normalizar(palavra).replace(" ", "")
        if chave in ETIQUETAS_TECNICAS:
            if ano is None:
                break          # sem ano: o que vem depois da 1ª etiqueta técnica é lixo de release
            continue
        if chave in PALAVRAS_RUIDO and palavras:    # a 1ª palavra fica ("Filme de Terror")
            continue
        palavras.append(palavra)
    return NomeExtraido(" ".join(palavras), ano)


def formatar_titulo(titulo: str) -> str:
    """'o poderoso chefao' -> 'O Poderoso Chefao' (usado quando o catálogo não conhece o filme)."""
    saida = []
    for i, palavra in enumerate(titulo.split()):
        if palavra.islower():
            palavra = palavra if (i > 0 and palavra in PALAVRAS_PEQUENAS) else palavra[:1].upper() + palavra[1:]
        saida.append(palavra)
    return " ".join(saida)


def limpar_para_arquivo(texto: str) -> str:
    """Deixa o texto válido como nome de pasta/arquivo (regra do Jellyfin: ':' vira ' -')."""
    texto = texto.replace(":", " -")
    texto = _RE_PROIBIDOS.sub("", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto.rstrip(". ")          # Windows não aceita nome terminando em ponto/espaço


def nome_jellyfin(titulo: str, ano: int | None, tmdb_id: int | None = None,
                  incluir_tmdbid: bool = False) -> str:
    """'Matrix', 1999 -> 'Matrix (1999)'. Com incluir_tmdbid: 'Matrix (1999) [tmdbid-603]'
    (o Jellyfin usa esse id para identificar o filme sem margem de erro)."""
    nome = limpar_para_arquivo(titulo)
    if not nome:
        raise ValueError("título vazio")
    if ano:
        nome += f" ({ano})"
    if incluir_tmdbid and tmdb_id:
        nome += f" [tmdbid-{tmdb_id}]"
    return nome


_RE_PASTA_JELLYFIN = re.compile(r"^(?P<titulo>.+?) \((?P<ano>\d{4})\)(?: \[[^\]]+\])*$")


def ler_nome_jellyfin(nome: str) -> NomeExtraido | None:
    """'Matrix (1999)' ou 'Matrix (1999) [tmdbid-603]' -> NomeExtraido('Matrix', 1999)."""
    m = _RE_PASTA_JELLYFIN.match(nome.strip())
    return NomeExtraido(m["titulo"], int(m["ano"])) if m else None
