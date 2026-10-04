"""Espelhar links no Jellyfin com arquivos .strm (sem baixar os vídeos).

Um .strm é um arquivo de texto com UM link dentro. O Jellyfin trata o .strm como se fosse o
vídeo: aparece na biblioteca com pôster e sinopse, e ao dar play ele toca direto do link.

    Filmes/Anjos da Noite (2003)/Anjos da Noite (2003).strm       <- https://archive.org/download/...
    Séries/Dark (2017)/Season 01/Dark S01E02.strm

Os nomes saem da MESMA lógica do organizador (planejar): catálogo local/TMDB, ano, S01E02...
Cada link é classificado em:
    "serie"  -> tem marca forte de episódio no título ou no arquivo (S01E02, 1x02, Temporada 1 Episódio 2)
    "filme"  -> tem ano (no título, no nome do arquivo ou nos metadados do item)
    "outro"  -> nem um nem outro: fica de fora (não dá para nomear com segurança)

Direitos autorais: espelhar só faz sentido com o que pode ser distribuído. Por isso a licença do
item (quando o site informa, como no archive.org) acompanha cada link, e há a opção de espelhar
só o que é domínio público ou licença aberta (Creative Commons).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

from .nomes import extrair_titulo_e_ano, marca_de_episodio
from .organizador import _consultas, planejar

# etiquetas de lançamento que não fazem parte do nome ("Anjos da Noite 2003 (Dual Audio) PT-BR")
_RE_ETIQUETAS = re.compile(r"[\[(]?\b(?:dvd(?:rip|iso)?|r\dbr|vhs|dual[ ._-]*audio|pt[ ._-]?br|dublado|dublagem"
                           r"(?: original)?(?: em portugu[eê]s)?|legendado|nacional|completo|hd)\b[\])]?", re.IGNORECASE)

# pasta que não existe: o planejar() só precisa do NOME do "vídeo", não de um arquivo de verdade
_VIRTUAL = Path("/__espelho_jellyfin__")
EXTENSAO = ".strm"


@dataclass
class ItemEspelho:
    link: object                     # LinkVideo (url, titulo, licenca, ano)
    tipo: str                        # filme | serie | outro
    destino: Path | None = None      # o .strm que será criado
    status: str = ""                 # criar | ja_existe | tem_video | ignorado | sem_licenca | nao_identificado | criado | erro
    detalhe: str = ""
    fonte_nome: str = ""             # TMDB | catálogo | arquivo
    filme: object = None             # Filme do catálogo (título original ajuda a achar legenda)
    episodio: tuple | None = None    # (temporada, episódio), em séries

    def como_item_da_biblioteca(self):
        """Para o pós-processamento (legendas, pôster, .nfo): o .strm faz o papel do vídeo."""
        from .pos_processamento import ItemBiblioteca
        return ItemBiblioteca(self.destino, self.filme, self.episodio), self.destino.stem


def licenca_aberta(licenca: str) -> bool:
    """Domínio público ou Creative Commons: pode espelhar sem dúvida."""
    return licenca == "Domínio público" or licenca.startswith("CC ")


def nome_do_link(link) -> str:
    """Título do item; sem título, o nome do arquivo do link (sem a extensão)."""
    titulo = str(getattr(link, "titulo", "") or "").strip()
    if titulo:
        return titulo
    return Path(unquote(urlparse(link.url).path)).stem


def classificar(link) -> str:
    titulo = nome_do_link(link)
    arquivo = Path(unquote(urlparse(link.url).path)).name
    if marca_de_episodio(titulo + ".mkv") or marca_de_episodio(arquivo):
        return "serie"
    if extrair_titulo_e_ano(titulo + ".mkv").ano or getattr(link, "ano", None) or extrair_titulo_e_ano(arquivo).ano:
        return "filme"
    return "outro"


def _video_virtual(link, tipo: str) -> Path:
    """Um 'arquivo' com o nome certo para o planejar() ler: 'Dark S01E02.mkv', 'Matrix 1999.mkv'."""
    titulo = _RE_ETIQUETAS.sub(" ", nome_do_link(link).replace("/", " ").replace("\\", " "))
    titulo = re.sub(r"\(\s*\)|\[\s*\]|\s*-\s*$|\s+", " ", titulo).strip(" -")
    if tipo == "serie" and not marca_de_episodio(titulo + ".mkv"):
        titulo = Path(unquote(urlparse(link.url).path)).stem          # a marca está no nome do arquivo
    if tipo == "filme" and not extrair_titulo_e_ano(titulo + ".mkv").ano:
        ano = getattr(link, "ano", None) or extrair_titulo_e_ano(Path(urlparse(link.url).path).name).ano
        titulo = f"{titulo} {ano}"
    return _VIRTUAL / f"{titulo}.mkv"


def planejar_espelho(links: list, pasta_filmes: str | Path | None, pasta_series: str | Path | None,
                     catalogo=None, so_licenca_aberta: bool = False, incluir_tmdbid: bool = False,
                     nomes_episodios: bool = False) -> list[ItemEspelho]:
    """Decide o .strm de cada link (não cria nada)."""
    itens = [ItemEspelho(link, classificar(link)) for link in links]
    if catalogo is not None:                                  # TMDB: todas as buscas de uma vez
        for tipo, modo in (("filme", "filmes"), ("serie", "series")):
            videos = [_video_virtual(i.link, tipo) for i in itens if i.tipo == tipo]
            if videos and hasattr(catalogo, "pre_buscar"):
                catalogo.pre_buscar(_consultas(videos, modo))
    destinos_vistos: set[str] = set()
    for item in itens:
        if item.tipo == "outro":
            item.status, item.detalhe = "ignorado", "sem ano nem episódio no título: não dá para nomear"
            continue
        if so_licenca_aberta and not licenca_aberta(getattr(item.link, "licenca", "")):
            item.status = "sem_licenca"
            item.detalhe = f"licença: {getattr(item.link, 'licenca', '') or 'não informada'}"
            continue
        pasta = pasta_filmes if item.tipo == "filme" else pasta_series
        if not pasta:
            item.status, item.detalhe = "erro", f"escolha a pasta da biblioteca de {'Filmes' if item.tipo == 'filme' else 'Séries'}"
            continue
        mov = planejar(_video_virtual(item.link, item.tipo), Path(pasta), catalogo, incluir_tmdbid,
                       modo="filmes" if item.tipo == "filme" else "series", nomes_episodios=nomes_episodios)
        if not mov.destino:
            item.status, item.detalhe = "nao_identificado", mov.detalhe
            continue
        item.destino = mov.destino.with_suffix(EXTENSAO)
        item.fonte_nome, item.filme, item.episodio = mov.fonte_nome, mov.filme, mov.episodio
        item.detalhe = mov.detalhe
        if str(item.destino).lower() in destinos_vistos:
            item.status, item.detalhe = "ja_existe", "outro link da lista já vai para esse nome"
        elif item.destino.exists():
            item.status = "ja_existe"
        elif any(p.stem.lower() == item.destino.stem.lower() and p.suffix.lower() != EXTENSAO
                 for p in _arquivos_da_pasta(item.destino.parent)):
            item.status, item.detalhe = "tem_video", "a biblioteca já tem esse vídeo (baixado)"
        else:
            item.status = "criar"
        destinos_vistos.add(str(item.destino).lower())
    return itens


def _arquivos_da_pasta(pasta: Path) -> list[Path]:
    try:
        return [p for p in pasta.iterdir() if p.is_file()]
    except OSError:
        return []


def aplicar_espelho(itens: list[ItemEspelho]) -> list[ItemEspelho]:
    """Cria os .strm planejados (status 'criar'). Nunca sobrescreve nada."""
    for item in itens:
        if item.status != "criar":
            continue
        try:
            item.destino.parent.mkdir(parents=True, exist_ok=True)
            with open(item.destino, "x", encoding="utf-8") as f:     # "x": falha se já existir
                f.write(item.link.url + "\n")
            item.status = "criado"
        except FileExistsError:
            item.status = "ja_existe"
        except OSError as erro:
            item.status, item.detalhe = "erro", str(erro)
    return itens
