"""Lê nomes de arquivo bagunçados e monta nomes no padrão do Jellyfin. Não acessa a internet."""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
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
    "imax", "remastered", "yts", "yify", "rarbg", "2ch", "6ch", "8ch",
}
# Palavras comuns em nomes "caseiros" que não fazem parte do título.
PALAVRAS_RUIDO = {
    "filme", "completo", "dublado", "dub", "legendado", "leg", "dual", "audio", "nacional",
    "portugues", "pt", "br", "ptbr", "torrent", "download", "baixar", "full", "movie",
    "forced", "forcada", "forcadas", "legenda", "legendas", "www",
}
PALAVRAS_PEQUENAS = {"de", "da", "do", "das", "dos", "e", "o", "a", "os", "as", "em", "no", "na",
                     "nos", "nas", "um", "uma", "of", "the", "and", "an", "in", "on", "at", "to"}

# Propaganda de site no nome: "[WWW.SITE.TV]", "WWW.SITE.COM", "SITE.TV" (removida antes de ler o título).
_TLDS = r"(?:com|net|org|tv|to|io|me|cc|info|biz|site|xyz|vip|club|top|ws)(?:\.br)?"
_RE_SITE = re.compile(
    rf"\[[^\]]*(?:www\.|\.{_TLDS}\b)[^\]]*\]"          # [WWW.SITE.TV] ou [Acesse SITE.COM]
    rf"|\bwww\.[a-z0-9-]+(?:\.[a-z0-9-]+)*"             # www.site.qualquer
    rf"|\b[a-z0-9-]{{3,}}\.{_TLDS}\b",                   # SITE.TV, SITE.COM
    re.IGNORECASE)
# Canais de áudio ("5.1", "DDP5.1", "7.1") que, sem ano no nome, poluiriam o título.
_RE_AUDIO = re.compile(r"(?<![\d.])(?:ddp?|e?ac3|aac|dts)?[ ._-]?[257][ .][01](?![\d])", re.IGNORECASE)


def sites_no_texto(texto: str) -> list[str]:
    """'Pica-Pau.WEB.DUB-WWW.BLUDV.COM (75)' -> ['WWW.BLUDV.COM']."""
    return [m.group() for m in _RE_SITE.finditer(texto)]


def tem_site(texto: str) -> bool:
    """True se o texto tem cara de propaganda de site (www., .com, .tv...)."""
    return bool(_RE_SITE.search(texto))


# Etiqueta de grupo no começo do nome: "[Gekiga Fansub] - Filme..." (comum em animes).
_RE_GRUPO_INICIAL = re.compile(r"^\s*\[[^\]]*\][\s._-]*")


def _sem_propaganda(texto: str) -> str:
    return _RE_AUDIO.sub(" ", _RE_SITE.sub(" ", _RE_GRUPO_INICIAL.sub("", texto)))


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


# @lru_cache: o mesmo nome é lido muitas vezes (um por vídeo da pasta); a resposta fica guardada.
@lru_cache(maxsize=65536)
def normalizar(texto: str) -> str:
    """'O Poderoso Chefão!' -> 'o poderoso chefao' (para comparar textos)."""
    texto = sem_acentos(texto).lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", texto).split())


@lru_cache(maxsize=65536)
def similaridade(a: str, b: str) -> float:
    """0.0 (nada a ver) a 1.0 (iguais), ignorando acentos, pontuação e maiúsculas."""
    return SequenceMatcher(None, normalizar(a), normalizar(b)).ratio()


def eh_video(caminho: Path) -> bool:
    return caminho.suffix.lower() in EXTENSOES_VIDEO


def eh_video_da_biblioteca(caminho: Path) -> bool:
    """Vídeo OU .strm (link espelhado: o Jellyfin toca do link). Usado ao completar a biblioteca;
    o organizador não move .strm (são minúsculos e seriam confundidos com propaganda)."""
    return eh_video(caminho) or caminho.suffix.lower() == ".strm"


@lru_cache(maxsize=65536)
def extrair_titulo_e_ano(nome_arquivo: str) -> NomeExtraido:
    """'Matrix.1999.1080p.BluRay.x264-VERSAO.mp4' -> NomeExtraido('Matrix', 1999)
       'interestellar_filme_completo_dublado_2014.mkv' -> NomeExtraido('interestellar', 2014)
    """
    caminho = Path(nome_arquivo)
    base = caminho.stem if caminho.suffix.lower() in EXTENSOES_VIDEO | EXTENSOES_ACOMPANHANTES \
        else caminho.name
    texto = _RE_SEPARADORES.sub(" ", _sem_propaganda(base)).strip()

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

    return NomeExtraido(_limpar_palavras(antes, cortar_na_etiqueta=ano is None), ano)


def _limpar_palavras(texto: str, cortar_na_etiqueta: bool) -> str:
    """Tira etiquetas técnicas (1080p, x264...) e palavras-ruído (dublado, completo...).
    cortar_na_etiqueta=True: tudo depois da 1ª etiqueta técnica é lixo de release."""
    palavras = []
    for palavra in _RE_SEPARADORES.sub(" ", texto).split():
        chave = normalizar(palavra).replace(" ", "")
        if chave in ETIQUETAS_TECNICAS:
            if cortar_na_etiqueta:
                break
            continue
        if chave in PALAVRAS_RUIDO and palavras:    # a 1ª palavra fica ("Filme de Terror")
            continue
        palavras.append(palavra)
    return " ".join(palavras)


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


# ============================================================================ séries
class EpisodioExtraido(NamedTuple):
    serie: str               # nome "limpo" (ainda sem correção do catálogo)
    temporada: int
    episodio: int
    ano: Optional[int]
    absoluto: bool = False   # só o número do episódio ("Dragon Ball 153"): numeração contínua


# Do mais confiável para o menos confiável. Cada um devolve (temporada, episódio).
_PADROES_EPISODIO = [
    re.compile(r"(?<![a-z0-9])s0?(\d{1,2})[ ._-]*e(\d{1,3})(?!\d)", re.I),                 # S01E02, s1.e2, S012E20
    re.compile(r"(?<![a-z0-9])(\d{1,2})x(\d{1,3})(?!\d)", re.I),                          # 1x02
    re.compile(r"(?<![a-z0-9])(\d{1,2})x[ ._-]*\([ ._-]*(\d{1,3})[ ._-]*\)", re.I),          # 1x (11)
    re.compile(r"(?:temporada|season|temp)[ ._-]*(\d{1,2})[ ._-]*(?:-[ ._-]*)?"
               r"(?:epis[oó]dio|episode|epi|ep|e)[ ._-]*(\d{1,3})(?!\d)", re.I),           # Temporada 2 Episodio 4, Temp 01 - Epi 04
]
# Só o número do episódio (temporada 1): "episodio 03", "Ep 3", "E03"
_PADRAO_SO_EPISODIO = re.compile(r"(?<![a-z0-9])(?:epis[oó]dio|episode|epi|ep|e)[ ._-]*(\d{1,3})(?!\d)", re.I)
# Fracos (só depois dos outros): "Regular.Show.03.15-by-fulano" (temporada.episódio com 2 dígitos, depois
# do nome) e, sem o nome da série, "04-01 Saída 9B" (no começo do arquivo; a série vem da pasta).
_PADRAO_PONTO = re.compile(r"(?<=[a-z][ ._])(\d{2})\.(\d{2})(?![\d.])", re.I)
_PADRAO_INICIO = re.compile(r"^\s*(\d{1,2})[-x](\d{2})(?!\d)(?=[ ._-]+[^\d\s])", re.I)
# Número entre parênteses no fim: "Pica-Pau.WEB.DUB-WWW.BLUDV.COM (75)"
_PADRAO_PARENTESES = re.compile(r"\((\d{1,4})\)\s*$")


@lru_cache(maxsize=65536)
def marca_de_episodio(nome_arquivo: str) -> str | None:
    """'The.Big.Bang.Theory.S05E19.720p.mkv' -> 'S05E19'. Só marcas FORTES (S05E19, 5x19,
    'Temporada 5 Episódio 19'): 'Star.Wars.Episode.4.1977' é filme e não conta."""
    base = _RE_SITE.sub(" ", Path(nome_arquivo).stem)
    for padrao in _PADROES_EPISODIO:
        if m := padrao.search(base):
            return f"S{int(m.group(1)):02d}E{int(m.group(2)):02d}"
    return None


@lru_cache(maxsize=65536)
def extrair_episodio(nome_arquivo: str) -> EpisodioExtraido | None:
    """'Breaking.Bad.2008.S02E05.720p.mkv' -> EpisodioExtraido('Breaking Bad', 2, 5, 2008)
       'dark_episodio_03_dublado.mp4'     -> EpisodioExtraido('dark', 1, 3, None)
       'Matrix.1999.mkv'                  -> None (não é episódio)
    """
    caminho = Path(nome_arquivo)
    base = caminho.stem if caminho.suffix.lower() in EXTENSOES_VIDEO | EXTENSOES_ACOMPANHANTES \
        else caminho.name
    base = _RE_SITE.sub(" ", base)
    for padrao in _PADROES_EPISODIO:
        m = padrao.search(base)
        if m:
            temporada, episodio = int(m.group(1)), int(m.group(2))
            break
    else:
        m = _PADRAO_SO_EPISODIO.search(base)
        if m:
            return _montar_episodio(base[:m.start()], 1, int(m.group(1)), absoluto=True)
        if (m := _PADRAO_PONTO.search(base)) and 1 <= int(m.group(1)) <= 40 and int(m.group(2)) >= 1:
            return _montar_episodio(base[:m.start()], int(m.group(1)), int(m.group(2)))
        if (m := _PADRAO_PARENTESES.search(base)) and not 1900 <= int(m.group(1)) <= 2099 and int(m.group(1)):
            return _montar_episodio(_cortar_qualidade(base[:m.start()]), 1, int(m.group(1)), absoluto=True)
        return _episodio_absoluto(base)
    return _montar_episodio(base[:m.start()], temporada, episodio)


# Pastas que não são nome de série (para não chamar a série de "Desenhos" ou "Season 01").
PASTAS_GENERICAS = {"series", "serie", "series organizadas", "desenhos", "desenho", "animes", "anime", "downloads",
                    "download", "torrent", "torrents", "videos", "filmes", "tv", "shows", "novos", "organizadas",
                    "completo", "completa", "dublado", "legendado", "temporadas", "especiais", "extras"}
_RE_TEMPORADA_PASTA = re.compile(
    r"\b\d{1,2}\s*(?:a|ª|º|°)?\s*(?:temporada|temp)\b|\b(?:temporada|season|temp)\s*\d{1,2}\b"
    r"|\bs\d{1,2}(?:\s*e\d{1,3}(?:\s*-\s*\d{1,3})?)?\b|\bcompleta?\b", re.IGNORECASE)


def serie_da_pasta(nome_pasta: str) -> tuple[str, int | None] | None:
    """'Apenas um Show - 1a Temporada' -> ('Apenas um Show', None); 'Dark (2017)' -> ('Dark', 2017);
    'Apenas um show s03e1-19' -> ('Apenas um show', None); 'Season 01', 'Desenhos' -> None."""
    texto = _RE_TEMPORADA_PASTA.sub(" ", _sem_propaganda(nome_pasta))
    ano = None
    if m := _RE_ANO.search(texto):
        ano, texto = int(m.group(1)), texto[:m.start()]
    nome = _limpar_palavras(texto, True).strip(" -")
    if not nome or normalizar(nome) in PASTAS_GENERICAS or not re.search(r"[a-zA-Z]", nome):
        return None
    return nome, ano


def numeros_sem_serie(nome_arquivo: str) -> tuple[int, int, bool] | None:
    """Temporada e episódio de um arquivo SEM o nome da série: 'Temp 01 - Epi 04 - Socos Mortais.mkv'
    -> (1, 4, False); '04-01 Saída 9B - HD 720p.mkv' -> (4, 1, False); 'Episodio 05.mkv' -> (1, 5, True).
    O nome da série vem da pasta (organizador.episodio_do_video)."""
    base = _RE_SITE.sub(" ", Path(nome_arquivo).stem)
    for padrao in _PADROES_EPISODIO:
        if m := padrao.search(base):
            return int(m.group(1)), int(m.group(2)), False
    if m := _PADRAO_INICIO.match(base):
        return int(m.group(1)), int(m.group(2)), False
    if m := _PADRAO_SO_EPISODIO.match(base.strip(" ._-")):
        return 1, int(m.group(1)), True
    return None


# Anime: nome + só o número do episódio ("HunterXHunter 01", "Hunter x Hunter - 01 (1080p) [A1B2]",
# "One.Piece.1071.1080p"). A temporada fica 1 (numeração absoluta, como os animes costumam vir).
_RE_QUALIDADE = re.compile(r"(?i)[ ._-](?:\d{3,4}p|\d{3,4}x\d{3,4}|x26[45]|h\.?26[45]|hevc|web-?dl|webrip|web[ ._-]?(?:dub|leg)|blu-?ray|"
                           r"bdrip|dvdrip|hdtv|dual|dublado|dub|legendado|leg|multi)(?![a-z0-9])")
_RE_ABSOLUTO = re.compile(r"^(?P<antes>.*[a-zA-Z].*?)[ ._-]+(?:-[ ._-]*)?(?:ep[ ._-]*)?(?P<ep>\d{1,4})(?:v\d)?$",
                          re.IGNORECASE)


def _cortar_qualidade(texto: str) -> str:
    """'Pica-Pau.WEB.DUB-' -> 'Pica-Pau' (tudo depois da 1ª etiqueta de release sai)."""
    q = _RE_QUALIDADE.search(texto)
    return texto[:q.start()] if q else texto


def _episodio_absoluto(base: str) -> EpisodioExtraido | None:
    limpo = _RE_GRUPO_INICIAL.sub("", base)
    limpo = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", limpo)          # [grupo] (1080p) [CRC]
    limpo = _cortar_qualidade(limpo)
    m = _RE_ABSOLUTO.match(limpo.strip(" ._-"))
    if not m:
        return None
    episodio = int(m.group("ep"))
    if episodio == 0 or 1900 <= episodio <= 2099:     # "Filme 2019" é ano, não episódio
        return None
    return _montar_episodio(m.group("antes"), 1, episodio, absoluto=True)


def _separar_palavras_grudadas(texto: str) -> str:
    """'HunterXHunter' -> 'Hunter X Hunter' (só quando o nome não tem nenhum separador)."""
    if re.search(r"[ ._-]", texto.strip(" ._-")):
        return texto
    return re.sub(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", texto)


def _montar_episodio(antes: str, temporada: int, episodio: int, absoluto: bool = False) -> EpisodioExtraido | None:
    if not antes.strip(" ._-[]()"):
        return None                       # "S01E01.mkv": sem o nome da série não dá para organizar
    antes = _separar_palavras_grudadas(antes)
    extraido = extrair_titulo_e_ano(antes + ".mkv")          # "Breaking.Bad.2008." -> ano 2008
    nome, ano = (extraido.titulo, extraido.ano) if extraido.ano else (_limpar_palavras(antes, True), None)
    nome = re.sub(r"\s*\b(?:temporada|season|temp)\s*$", "", nome, flags=re.I).strip()
    if not nome:
        return None
    return EpisodioExtraido(nome, temporada, episodio, ano, absoluto)


def nome_episodio_jellyfin(serie: str, temporada: int, episodio: int, titulo_episodio: str = "") -> str:
    """'Breaking Bad', 2, 5 -> 'Breaking Bad S02E05' (padrão de episódios do Jellyfin).
    Com o nome do episódio (TMDB), o número continua e o nome vem depois:
    'Breaking Bad S02E05 - Quatro Dias Fora' (o Jellyfin entende os dois jeitos)."""
    nome = f"{limpar_para_arquivo(serie)} S{temporada:02d}E{episodio:02d}"
    titulo = limpar_para_arquivo(titulo_episodio or "")
    return f"{nome} - {titulo[:120].rstrip('. ')}" if titulo else nome


def pasta_temporada(temporada: int) -> str:
    """Jellyfin: 'Season 01' (temporada 0 = especiais = 'Season 00')."""
    return f"Season {temporada:02d}"


# ----------------------------------------------------------------- qualidade (para escolher entre cópias)
_RESOLUCOES = ((r"2160p|4k|uhd", 2160, "2160p"), (r"1080[pi]", 1080, "1080p"), (r"720p", 720, "720p"),
               (r"576p|480p|sd(?:tv)?", 480, "480p"))
# (o nome chega com - . _ trocados por espaço: "WEB-DL" vira "web dl")
_FONTES = ((r"remux", 6, "Remux"), (r"blu ?ray|bdrip|brrip|bdremux", 5, "BluRay"), (r"web ?dl", 4, "WEB-DL"),
           (r"webrip|web", 3, "WEBRip"), (r"hdtv|tvrip", 2, "HDTV"), (r"dvd(?:rip|scr|iso)?|r\dbr", 1, "DVD"),
           (r"hd ?cam|cam(?:rip)?|telesync|hd ?ts|ts", -5, "CAM"))


@lru_cache(maxsize=65536)
def qualidade(nome_arquivo: str) -> tuple[int, int, str]:
    """'Matrix.1999.1080p.BluRay.x264.mkv' -> (1080, 5, '1080p BluRay'). Quanto maior, melhor.
    Desconhecida -> (0, 0, '')."""
    texto = " " + re.sub(r"[._\[\]()-]+", " ", Path(nome_arquivo).stem.lower()) + " "
    resolucao, rotulos = 0, []
    for padrao, valor, rotulo in _RESOLUCOES:
        if re.search(rf"(?<![a-z0-9])(?:{padrao})(?![a-z0-9])", texto):
            resolucao = valor
            rotulos.append(rotulo)
            break
    fonte = 0
    for padrao, valor, rotulo in _FONTES:
        if re.search(rf"(?<![a-z0-9])(?:{padrao})(?![a-z0-9])", texto):
            fonte = valor
            rotulos.append(rotulo)
            break
    return resolucao, fonte, " ".join(rotulos)
