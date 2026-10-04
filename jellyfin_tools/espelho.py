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

Outros sites (não só o archive.org): o .strm só funciona bem se o link for DIRETO (o arquivo, não
a página), PERMANENTE (links "assinados" expiram em horas) e PÚBLICO (o Jellyfin não tem o seu
login). verificar_links() confere isso antes, em paralelo, e mede quanto o servidor demora a responder.
Ao tocar, o vídeo vem do servidor do site a cada vez: a fluidez depende dele e da sua internet.

Direitos autorais: espelhar só faz sentido com o que pode ser distribuído. Por isso a licença do
item (quando o site informa, como no archive.org) acompanha cada link, e há a opção de espelhar
só o que é domínio público ou licença aberta (Creative Commons).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests

from .nomes import eh_video_da_biblioteca, extrair_titulo_e_ano, marca_de_episodio
from .organizador import EXTRAS_DO_STRM, PASTA_LOGS, _consultas, _gravar_log, planejar

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
    status: str = ""                 # criar | ja_existe | tem_video | no_jellyfin | ignorado | sem_licenca | link_ruim |
    #                                  nao_identificado | criado | erro
    detalhe: str = ""
    fonte_nome: str = ""             # TMDB | catálogo | arquivo
    raiz: Path | None = None         # a biblioteca (Filmes ou Séries) onde o .strm vai
    filme: object = None             # Filme do catálogo (título original ajuda a achar legenda)
    episodio: tuple | None = None    # (temporada, episódio), em séries

    def como_item_da_biblioteca(self):
        """Para o pós-processamento (legendas, pôster, .nfo): o .strm faz o papel do vídeo."""
        from .pos_processamento import ItemBiblioteca
        return ItemBiblioteca(self.destino, self.filme, self.episodio), self.destino.stem


# ----------------------------------------------------------------- o link serve para .strm?
# Parâmetros de link "assinado": expira e o .strm pararia de funcionar
_RE_TEMPORARIO = re.compile(r"[?&](?:expires?|exp|token|signature|sig|x-amz-signature|x-amz-expires|"
                            r"policy|key-pair-id|hdnts|hdnea)=", re.IGNORECASE)
LENTO_SEGUNDOS = 3.0


@dataclass
class Verificacao:
    ok: bool
    problema: str = ""               # por que NÃO serve para .strm
    aviso: str = ""                  # serve, mas com ressalva (sem avanço, resposta lenta)
    tempo: float | None = None       # segundos até o servidor responder


def verificar_link(url: str, sessao: requests.Session | None = None, timeout: float = 10,
                   permitido=None) -> Verificacao:
    """Pede só o 1º byte do arquivo (Range: bytes=0-0) e confere: é vídeo? é público? deixa avançar?"""
    if _RE_TEMPORARIO.search(url):
        return Verificacao(False, "link temporário (expira; o .strm pararia de funcionar)")
    if permitido is not None and not permitido(url):
        return Verificacao(False, "o robots.txt do site não permite")
    sessao = sessao or requests.Session()
    inicio = time.monotonic()
    try:
        with sessao.get(url, headers={"Range": "bytes=0-0", "User-Agent": "videoscraper (espelho Jellyfin)"},
                        stream=True, timeout=timeout, allow_redirects=True) as r:
            tempo = time.monotonic() - inicio
            status, cabecalhos = r.status_code, r.headers
    except requests.RequestException as erro:
        motivo = "não respondeu a tempo" if isinstance(erro, requests.Timeout) else "fora do ar ou sem conexão"
        return Verificacao(False, f"servidor {motivo}")
    if status in (401, 403):
        return Verificacao(False, "exige login ou permissão (o Jellyfin não tem o seu acesso)", tempo=tempo)
    if status in (404, 410):
        return Verificacao(False, "arquivo não encontrado (removido?)", tempo=tempo)
    if status >= 400:
        return Verificacao(False, f"o site respondeu HTTP {status}", tempo=tempo)
    tipo = cabecalhos.get("Content-Type", "").lower()
    if tipo.startswith(("text/html", "application/xhtml")):
        return Verificacao(False, "é uma página, não o arquivo do vídeo", tempo=tempo)
    avisos = []
    if status != 206 and "bytes" not in cabecalhos.get("Accept-Ranges", "").lower():
        avisos.append("o servidor não deixa avançar o vídeo")
    if tempo > LENTO_SEGUNDOS:
        avisos.append(f"resposta lenta ({tempo:.1f} s)")
    return Verificacao(True, aviso="; ".join(avisos), tempo=tempo)


def verificar_links(urls: list[str], trabalhadores: int = 8, ao_progresso=None,
                    respeitar_robots: bool = True) -> dict[str, Verificacao]:
    """Confere vários links AO MESMO TEMPO (a espera é quase toda da rede). ao_progresso(feitos, total)."""
    unicos = list(dict.fromkeys(urls))
    if not unicos:
        return {}
    local = threading.local()
    trava_robots = threading.Lock()
    robots = None
    if respeitar_robots:
        from videoscraper.rede import ClienteHTTP
        robots = ClienteHTTP(espera=0)

    def permitido(url: str) -> bool:
        with trava_robots:                                    # 1 robots.txt por site, guardado
            return robots.permitido(url)

    def um(url: str) -> Verificacao:
        if not hasattr(local, "sessao"):
            local.sessao = requests.Session()
        return verificar_link(url, local.sessao, permitido=permitido if robots else None)

    resultado = {}
    with ThreadPoolExecutor(max_workers=min(trabalhadores, len(unicos))) as executor:
        for feitos, (url, verificacao) in enumerate(zip(unicos, executor.map(um, unicos)), 1):
            resultado[url] = verificacao
            if ao_progresso:
                ao_progresso(feitos, len(unicos))
    return resultado


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
                     nomes_episodios: bool = False, verificacoes: dict | None = None,
                     indice_jellyfin=None) -> list[ItemEspelho]:
    """Decide o .strm de cada link (não cria nada). `verificacoes`: o resultado de verificar_links().
    `indice_jellyfin`: o que o servidor já tem (servidor_jellyfin.indice_da_biblioteca): não duplica."""
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
        verificacao = (verificacoes or {}).get(item.link.url)
        if verificacao is not None and not verificacao.ok:
            item.status, item.detalhe = "link_ruim", verificacao.problema
            continue
        pasta = pasta_filmes if item.tipo == "filme" else pasta_series
        if not pasta:
            item.status, item.detalhe = "erro", f"escolha a pasta da biblioteca de {'Filmes' if item.tipo == 'filme' else 'Séries'}"
            continue
        item.raiz = Path(pasta)
        mov = planejar(_video_virtual(item.link, item.tipo), Path(pasta), catalogo, incluir_tmdbid,
                       modo="filmes" if item.tipo == "filme" else "series", nomes_episodios=nomes_episodios)
        if not mov.destino:
            item.status, item.detalhe = "nao_identificado", mov.detalhe
            continue
        item.destino = mov.destino.with_suffix(EXTENSAO)
        item.fonte_nome, item.filme, item.episodio = mov.fonte_nome, mov.filme, mov.episodio
        item.detalhe = mov.detalhe
        if indice_jellyfin is not None and _ja_no_jellyfin(indice_jellyfin, item, mov):
            item.status, item.detalhe = "no_jellyfin", "já está no Jellyfin (mesmo filme/episódio)"
        elif str(item.destino).lower() in destinos_vistos:
            item.status, item.detalhe = "ja_existe", "outro link da lista já vai para esse nome"
        elif item.destino.exists():
            item.status = "ja_existe"
        elif any(p.stem.lower() == item.destino.stem.lower() and p.suffix.lower() != EXTENSAO
                 for p in _arquivos_da_pasta(item.destino.parent)):
            item.status, item.detalhe = "tem_video", "a biblioteca já tem esse vídeo (baixado)"
        else:
            item.status = "criar"
            if verificacao is not None and verificacao.aviso:
                item.detalhe = "; ".join(t for t in (item.detalhe, verificacao.aviso) if t)
        destinos_vistos.add(str(item.destino).lower())
    return itens


def _ja_no_jellyfin(indice, item: ItemEspelho, mov) -> bool:
    filme = mov.filme
    nomes = [n for n in ((filme.titulo, filme.titulo_original) if filme else ()) if n]
    if item.tipo == "serie" and mov.episodio:
        pasta_serie = mov.destino.parent.parent.name                     # "Dark (2017)"
        nomes.append(re.sub(r"\s*\(\d{4}\).*$", "", pasta_serie))
        return indice.tem_episodio(nomes, *mov.episodio, tmdb_id=filme.tmdb_id if filme else None)
    lido = re.match(r"(.+?) \((\d{4})\)", mov.destino.parent.name)       # "Nosferatu (1922)"
    if lido:
        nomes.append(lido.group(1))
    ano = filme.ano if filme else (int(lido.group(2)) if lido else None)
    return indice.tem_filme(nomes, ano, tmdb_id=filme.tmdb_id if filme else None)


def _arquivos_da_pasta(pasta: Path) -> list[Path]:
    try:
        return [p for p in pasta.iterdir() if p.is_file()]
    except OSError:
        return []


def _primeira_pasta_nova(destino: Path, raiz: Path | None) -> Path | None:
    """A pasta mais alta que AINDA não existe (ex.: 'Filmes/Nosferatu (1922)'): o desfazer a remove."""
    nova, pasta = None, destino.parent
    while not pasta.exists() and pasta != raiz and pasta != pasta.parent:
        nova, pasta = pasta, pasta.parent
    return nova


def aplicar_espelho(itens: list[ItemEspelho], gravar_log: bool = True) -> list[ItemEspelho]:
    """Cria os .strm planejados (status 'criar'). Nunca sobrescreve nada. Grava um log em cada
    biblioteca (.organizador): 'Desfazer última' apaga o que o espelho criou."""
    registro: dict[Path, dict] = {}
    espelhamento = f"{datetime.now():%Y%m%d-%H%M%S-%f}"     # o mesmo nos logs de Filmes e de Séries
    for item in itens:
        if item.status != "criar":
            continue
        try:
            nova = _primeira_pasta_nova(item.destino, item.raiz)
            item.destino.parent.mkdir(parents=True, exist_ok=True)
            with open(item.destino, "x", encoding="utf-8") as f:     # "x": falha se já existir
                f.write(item.link.url + "\n")
            item.status = "criado"
            reg = registro.setdefault(item.raiz or item.destino.parent,
                                      {"espelhamento": espelhamento, "strm_criados": [], "pastas_criadas": []})
            reg["strm_criados"].append(str(item.destino))
            if nova is not None:
                reg["pastas_criadas"].append(str(nova))
        except FileExistsError:
            item.status = "ja_existe"
        except OSError as erro:
            item.status, item.detalhe = "erro", str(erro)
    if gravar_log:
        for raiz, reg in registro.items():
            _gravar_log(raiz, [], extra=reg)
    return itens


# ----------------------------------------------------------------- conferir os espelhos
def ler_strm(arquivo: Path) -> str:
    """O link guardado no .strm (a 1ª linha preenchida)."""
    try:
        for linha in arquivo.read_text(encoding="utf-8", errors="replace").splitlines():
            if linha.strip():
                return linha.strip()
    except OSError:
        pass
    return ""


def espelhos_da_biblioteca(*pastas) -> list[tuple[Path, Path]]:
    """[(raiz da biblioteca, .strm)] de todas as bibliotecas (sem entrar em .organizador). Se uma
    biblioteca está dentro da outra (ex.: Séries = 'E:\\Series' e Filmes = 'E:\\Series\\Animes'), cada
    .strm aparece uma vez só, com a biblioteca mais de dentro."""
    raizes = [r for r in dict.fromkeys(Path(p) for p in pastas if p) if r.is_dir()]
    vistos, achados = set(), []
    for raiz in sorted(raizes, key=lambda r: len(r.resolve().parts), reverse=True):
        for a in sorted(raiz.rglob("*.strm")):
            if PASTA_LOGS not in a.parts and (chave := os.path.normcase(str(a.resolve()))) not in vistos:
                vistos.add(chave)
                achados.append((raiz, a))
    ordem = {r: n for n, r in enumerate(raizes)}
    return sorted(achados, key=lambda ra: (ordem[ra[0]], str(ra[1]).lower()))


def conferir_espelhos(*pastas, ao_progresso=None, respeitar_robots: bool = True) -> list[tuple]:
    """Confere o link de cada .strm: [(raiz, arquivo, url, Verificacao)]."""
    espelhos = espelhos_da_biblioteca(*pastas)
    links = {a: ler_strm(a) for _, a in espelhos}
    verificacoes = verificar_links([u for u in links.values() if u], ao_progresso=ao_progresso,
                                   respeitar_robots=respeitar_robots)
    sem_link = Verificacao(False, "o .strm está vazio")
    return [(raiz, a, links[a], verificacoes.get(links[a], sem_link)) for raiz, a in espelhos]


def remover_espelhos(quebrados: list[tuple]) -> int:
    """Apaga os .strm quebrados [(raiz, arquivo, url, ...)] e grava o log (o Desfazer os recria)."""
    por_raiz: dict[Path, list] = {}
    for raiz, arquivo, url, *_ in quebrados:
        try:
            arquivo.unlink()
            por_raiz.setdefault(raiz, []).append({"arquivo": str(arquivo), "url": url})
        except OSError:
            continue
    for raiz, removidos in por_raiz.items():
        _gravar_log(raiz, [], extra={"strm_removidos": removidos})
    return sum(len(r) for r in por_raiz.values())


# ----------------------------------------------------------------- conferência automática (com aviso)
UNIDADES = {"minutos": 60, "horas": 3600, "dias": 86400}
INTERVALO_MINIMO = 5 * 60   # conferir os links mais vezes que isso só sobrecarrega os sites


def intervalo_em_segundos(valor, unidade: str = "dias") -> float:
    """(12, 'horas') -> 43200; também aceita texto: '30min', '12h', '7d', '7' (dias), '1.5 dias'.
    Nunca menos que INTERVALO_MINIMO (5 minutos)."""
    if isinstance(valor, str):
        texto = valor.strip().lower().replace(",", ".")
        m = re.fullmatch(r"([\d.]+)\s*(m|min|mins|minuto|minutos|h|hora|horas|d|dia|dias)?", texto)
        if not m:
            raise ValueError(f"intervalo inválido: {valor!r} (use, por exemplo, 30min, 12h ou 7d)")
        letra = (m.group(2) or "d")[0]
        valor, unidade = float(m.group(1)), {"m": "minutos", "h": "horas", "d": "dias"}[letra]
    return max(float(valor) * UNIDADES[unidade], INTERVALO_MINIMO)


def mensagem_quebrados(quebrados: list, removidos: int = 0, limite: int = 15) -> tuple[str, str]:
    """Texto do aviso (Discord, Telegram) com os espelhos quebrados e o motivo de cada um."""
    import html
    linhas = [(arquivo.stem, v.problema) for _, arquivo, _, v in quebrados[:limite]]
    resto = f"\n… e mais {len(quebrados) - limite}" if len(quebrados) > limite else ""
    rodape = "\nRemovidos da biblioteca (dá para voltar com 'Desfazer última')." if removidos else ""
    titulo = f"{len(quebrados)} espelho(s) quebrado(s) no Jellyfin"
    discord = f"\U0001F517 **{titulo}**\n" + "\n".join(f"• {n} — {p}" for n, p in linhas) + resto + rodape
    telegram = (f"\U0001F517 <b>{html.escape(titulo)}</b>\n"
                + "\n".join(f"• {html.escape(n)} — {html.escape(p)}" for n, p in linhas) + resto + rodape)
    return discord, telegram


def conferir_e_avisar(*pastas, notificador=None, remover: bool = False, ao_progresso=None,
                      respeitar_robots: bool = True) -> tuple[list, list, int]:
    """Confere os .strm, (opcional) remove os quebrados e avisa no Discord/Telegram se algum quebrou.
    Devolve (todos, quebrados, quantos removidos)."""
    resultado = conferir_espelhos(*pastas, ao_progresso=ao_progresso, respeitar_robots=respeitar_robots)
    quebrados = [r for r in resultado if not r[3].ok]
    removidos = remover_espelhos(quebrados) if quebrados and remover else 0
    if quebrados and notificador is not None and getattr(notificador, "ativo", False):
        notificador.enviar(*mensagem_quebrados(quebrados, removidos))
    return resultado, quebrados, removidos


# ----------------------------------------------------------------- gerenciar: remover o espelhamento escolhido
_RE_DATA_LOG = re.compile(r"log-(\d{8}-\d{6})")


@dataclass
class EspelhoSalvo:
    """Um .strm que está na biblioteca."""
    raiz: Path
    arquivo: Path
    url: str = ""

    @property
    def nome(self) -> str:
        return self.arquivo.stem

    @property
    def caminho(self) -> str:
        return "/".join(self.arquivo.relative_to(self.raiz).parts)


@dataclass
class LoteEspelho:
    """Um espelhamento (um clique em "Espelhar no Jellyfin"), com os .strm dele que ainda existem.
    numero 1 = o mais antigo; 0 = .strm sem registro (feitos à mão ou antes do histórico)."""
    numero: int
    data: datetime | None
    itens: list[EspelhoSalvo] = field(default_factory=list)

    @property
    def titulo(self) -> str:
        if not self.numero:
            return f"Sem registro (feitos à mão ou antes do histórico) · {len(self.itens)} item(ns)"
        quando = f" — {self.data:%d/%m/%Y %H:%M}" if self.data else ""
        return f"Espelhamento {self.numero}{quando} · {len(self.itens)} item(ns)"


def _chave(caminho: Path) -> str:
    """Compara caminhos do log com os do disco (no Windows, sem diferenciar maiúsculas)."""
    return os.path.normcase(os.path.abspath(caminho))


def _data_do_log(log: Path) -> datetime | None:
    m = _RE_DATA_LOG.match(log.name)
    return datetime.strptime(m.group(1), "%Y%m%d-%H%M%S") if m else None


def lotes_de_espelhos(*pastas) -> list[LoteEspelho]:
    """Os espelhamentos feitos nas bibliotecas, do mais antigo ao mais novo, cada um com os .strm
    que ainda existem. A numeração (Espelhamento 1, 2, 3...) não muda quando um deles é removido."""
    existentes = {_chave(a): (raiz, a) for raiz, a in espelhos_da_biblioteca(*pastas)}
    criacoes: dict[str, list] = {}               # id do espelhamento -> [data, [.strm criados]]
    for raiz in dict.fromkeys(Path(p) for p in pastas if p):
        for log in sorted((raiz / PASTA_LOGS).glob("log-*.json")):
            if log.name.endswith(".desfeito.json"):
                continue
            try:
                dados = json.loads(log.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(dados, dict) or not dados.get("strm_criados"):
                continue
            data = _data_do_log(log)
            ident = dados.get("espelhamento") or (f"{data:%Y%m%d-%H%M%S}" if data else log.name)
            entrada = criacoes.setdefault(ident, [data, []])
            entrada[1] += dados["strm_criados"]
    lotes, dono = [], {}
    for numero, (_, (data, criados)) in enumerate(sorted(criacoes.items(), key=lambda kv: kv[0]), start=1):
        lotes.append(LoteEspelho(numero, data))
        for caminho in criados:
            dono[_chave(Path(caminho))] = numero - 1          # recriado depois: fica no mais novo
    sem_registro = LoteEspelho(0, None)
    for chave, (raiz, arquivo) in existentes.items():
        lote = lotes[dono[chave]] if chave in dono else sem_registro
        lote.itens.append(EspelhoSalvo(raiz, arquivo, ler_strm(arquivo)))
    for lote in lotes + [sem_registro]:
        lote.itens.sort(key=lambda e: e.caminho.lower())
    return [lote for lote in lotes + [sem_registro] if lote.itens]


def _extras_do_strm(arquivo: Path) -> list[Path]:
    """Legenda, miniatura e .nfo com o mesmo nome do .strm."""
    if not arquivo.parent.is_dir():
        return []
    return [a for a in sorted(arquivo.parent.iterdir())
            if a.is_file() and a.suffix.lower() in EXTRAS_DO_STRM
            and a.name.startswith((arquivo.stem + ".", arquivo.stem + "-"))]


def _pasta_que_sai_junto(arquivo: Path, raiz: Path, escolhidos: set[str], memoria: dict) -> Path | None:
    """A pasta mais de fora (abaixo da biblioteca) cujos vídeos são TODOS .strm escolhidos: o filme,
    a temporada ou a série inteira. Pasta com algum vídeo baixado ou .strm não escolhido fica."""
    candidata, pasta = None, arquivo.parent
    while pasta != raiz and raiz in pasta.parents:
        if pasta not in memoria:
            videos = [a for a in pasta.rglob("*") if a.is_file() and eh_video_da_biblioteca(a)]
            memoria[pasta] = all(_chave(v) in escolhidos for v in videos)
        if not memoria[pasta]:
            break
        candidata, pasta = pasta, pasta.parent
    return candidata


def remover_espelhos_escolhidos(itens: list[EspelhoSalvo]) -> tuple[int, list[str]]:
    """Tira da biblioteca os .strm escolhidos (qualquer espelhamento, não só o último), com a legenda,
    a miniatura e o .nfo de mesmo nome. Se a pasta do filme/temporada/série fica sem nenhum vídeo,
    sai a pasta inteira (pôster, backdrop...). Nada é apagado: vai para
    <biblioteca>/.organizador/removidos/<data>/ e "Desfazer última" devolve.
    Devolve (quantos .strm saíram, mensagens)."""
    agora = f"{datetime.now():%Y%m%d-%H%M%S-%f}"
    total, mensagens = 0, []
    por_raiz: dict[Path, list[EspelhoSalvo]] = {}
    for item in itens:
        if item.arquivo.exists():
            por_raiz.setdefault(item.raiz, []).append(item)
    for raiz, lista in por_raiz.items():
        lixeira = raiz / PASTA_LOGS / "removidos" / agora
        escolhidos = {_chave(i.arquivo) for i in lista}
        memoria: dict = {}
        pastas = {p for i in lista if (p := _pasta_que_sai_junto(i.arquivo, raiz, escolhidos, memoria))}
        pastas = {p for p in pastas if not any(o in p.parents for o in pastas)}       # só a mais de fora
        movimentos = [(p, lixeira / p.relative_to(raiz)) for p in sorted(pastas)]
        for i in lista:
            if not any(p in i.arquivo.parents for p in pastas):
                movimentos += [(a, lixeira / a.relative_to(raiz)) for a in [i.arquivo] + _extras_do_strm(i.arquivo)]
        guardados = []
        for de, para in movimentos:
            try:
                strm = [de] if de.is_file() else [a for a in de.rglob("*.strm") if _chave(a) in escolhidos]
                para.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(de), str(para))
                guardados.append({"de": str(de), "para": str(para)})
                total += sum(1 for a in strm if a.suffix.lower() == EXTENSAO)
                mensagens.append(f"espelho tirado da biblioteca: {de.relative_to(raiz)}")
            except OSError as erro:
                mensagens.append(f"erro em {de}: {erro}")
        if guardados:
            _gravar_log(raiz, [], extra={"espelhos_guardados": guardados, "lixeira": str(lixeira)})
    return total, mensagens


def desfazer_ultima_remocao(*pastas) -> list[str]:
    """Desfaz a última remoção feita em "Gerenciar espelhos", nas duas bibliotecas de uma vez
    (uma remoção que pegou filmes e episódios grava um log em cada uma)."""
    from .organizador import desfazer, ultimo_log
    candidatos = []
    for raiz in dict.fromkeys(Path(p) for p in pastas if p):
        log = ultimo_log(raiz) if raiz.is_dir() else None
        try:
            dados = json.loads(log.read_text(encoding="utf-8")) if log else {}
        except (OSError, ValueError):
            continue
        if isinstance(dados, dict) and dados.get("espelhos_guardados") and dados.get("lixeira"):
            candidatos.append((Path(dados["lixeira"]).name, log))
    if not candidatos:
        return []
    mais_nova = max(c[0] for c in candidatos)
    mensagens = []
    for marca, log in candidatos:
        if marca == mais_nova:
            mensagens += desfazer(log)
    return mensagens
