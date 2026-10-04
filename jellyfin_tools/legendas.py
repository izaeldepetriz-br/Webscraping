"""Busca e baixa legendas no padrão do Jellyfin (mesmo nome do vídeo + .pt-BR.srt):

    Filmes/Matrix (1999)/Matrix (1999).pt-BR.srt
    Séries/Dark (2017)/Season 01/Dark S01E02.pt-BR.srt

Provedores (qualquer objeto com .nome, .buscar() e .baixar() serve):
  - ProvedorSiteHTML: raspagem com BeautifulSoup de um site de busca simples (seletores configuráveis).
    Respeita robots.txt. Use só em sites que permitem; o site_demo.py é um exemplo local.
  - ProvedorOpenSubtitles: API oficial (https://opensubtitles.stoplight.io). Chave gratuita
    e limite de downloads por dia. Raspar o site do OpenSubtitles viola os termos; a API não.
"""

from __future__ import annotations

import io
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from videoscraper.rede import ClienteHTTP

from .nomes import eh_video, extrair_episodio, extrair_titulo_e_ano, ler_nome_jellyfin, similaridade

IDIOMA_PADRAO = "pt-BR"

# Apelidos aceitos ao digitar os idiomas -> código que o Jellyfin entende no nome do arquivo.
APELIDOS_IDIOMA = {
    "pt-br": "pt-BR", "ptbr": "pt-BR", "pt_br": "pt-BR", "br": "pt-BR", "pt": "pt-BR", "por": "pt-BR",
    "portugues": "pt-BR", "português": "pt-BR", "pt-pt": "pt-PT", "ptpt": "pt-PT",
    "en": "en", "eng": "en", "english": "en", "ingles": "en", "inglês": "en",
    "es": "es", "spa": "es", "esp": "es", "espanol": "es", "español": "es", "espanhol": "es",
    "fr": "fr", "fre": "fr", "fra": "fr", "frances": "fr", "francês": "fr",
    "it": "it", "ita": "it", "italiano": "it", "de": "de", "ger": "de", "deu": "de", "alemao": "de",
    "alemão": "de", "ja": "ja", "jpn": "ja", "japones": "ja", "japonês": "ja",
}


def normalizar_idiomas(texto) -> list[str]:
    """'pt-BR, inglês; es' -> ['pt-BR', 'en', 'es'] (sem repetir, na ordem digitada).
    Aceita também uma lista. Códigos desconhecidos no formato 'xx' ou 'xx-YY' passam como estão."""
    import re
    partes = texto if isinstance(texto, (list, tuple)) else re.split(r"[,;\s]+", str(texto or ""))
    idiomas = []
    for parte in partes:
        chave = str(parte).strip().lower()
        if not chave:
            continue
        codigo = APELIDOS_IDIOMA.get(chave)
        if codigo is None and re.fullmatch(r"[a-z]{2,3}(-[a-z]{2})?", chave):
            base, _, regiao = chave.partition("-")
            codigo = f"{base}-{regiao.upper()}" if regiao else base
        if codigo and codigo not in idiomas:
            idiomas.append(codigo)
    return idiomas
TAMANHO_MAXIMO = 5 * 1024 * 1024        # legenda é texto: 5 MB já é muito
SIMILARIDADE_MINIMA = 0.6


class ErroLegenda(Exception):
    pass


@dataclass
class CandidatoLegenda:
    titulo: str
    ano: int | None
    idioma: str
    url: str
    downloads: int = 0
    provedor: str = ""
    extra: dict = field(default_factory=dict)
    temporada: int | None = None      # só para episódios de série
    episodio: int | None = None


@dataclass
class ResultadoLegenda:
    pasta: Path
    status: str               # baixada | ja_existe | nao_encontrada | erro | sem_video
    caminho: Path | None = None
    detalhe: str = ""

    def __str__(self) -> str:
        return f"[{self.status}] {self.pasta.name}" + (f" ({self.detalhe})" if self.detalhe else "")


# --------------------------------------------------------------------------- arquivo .srt
def extrair_srt(conteudo: bytes) -> str:
    """Aceita .srt puro ou .zip com .srt dentro. Devolve o texto (corrige a codificação)."""
    if conteudo[:2] == b"PK":                                   # assinatura de arquivo zip
        try:
            with zipfile.ZipFile(io.BytesIO(conteudo)) as z:
                nomes = [n for n in z.namelist() if n.lower().endswith(".srt")]
                if not nomes:
                    raise ErroLegenda("o .zip não tem nenhum .srt")
                # lê direto da memória: nada é extraído para o disco (evita 'zip slip')
                conteudo = z.read(max(nomes, key=lambda n: z.getinfo(n).file_size))
        except zipfile.BadZipFile as erro:
            raise ErroLegenda("arquivo .zip corrompido") from erro
    for codificacao in ("utf-8-sig", "cp1252", "latin-1"):     # legendas antigas vêm em Windows-1252
        try:
            texto = conteudo.decode(codificacao)
            break
        except UnicodeDecodeError:
            continue
    if "-->" not in texto:
        raise ErroLegenda("o arquivo baixado não parece uma legenda .srt")
    return texto.replace("\r\n", "\n")


def caminho_da_legenda(pasta_filme: Path, idioma: str = IDIOMA_PADRAO) -> Path:
    """Mesmo nome do vídeo da pasta + '.pt-BR.srt' (se não houver vídeo, usa o nome da pasta)."""
    videos = sorted(p for p in pasta_filme.iterdir() if p.is_file() and eh_video(p))
    base = videos[0].stem if videos else pasta_filme.name
    return pasta_filme / f"{base}.{idioma}.srt"


# --------------------------------------------------------------------------- escolha
def escolher_melhor(candidatos: list[CandidatoLegenda], titulo: str, ano: int | None,
                    idioma: str, temporada: int | None = None,
                    episodio: int | None = None) -> CandidatoLegenda | None:
    """Mesmo idioma, mesmo ano, título parecido (e, em séries, o MESMO episódio);
    entre os bons, o mais baixado.
    Séries: o ano NÃO é comparado. O ano da série é o da estreia (The Last of Us: 2023), mas a
    legenda traz o ano do EPISÓDIO (2ª temporada: 2025); temporada + episódio + título bastam."""
    bons = []
    for c in candidatos:
        if c.idioma.lower() != idioma.lower():
            continue
        if episodio is not None and (c.temporada, c.episodio) != (temporada, episodio):
            continue                     # legenda de outro episódio fica fora do tempo do vídeo
        if episodio is None and ano and c.ano and c.ano != ano:
            continue
        if similaridade(titulo, c.titulo) < SIMILARIDADE_MINIMA:
            continue
        bons.append(c)
    return max(bons, key=lambda c: c.downloads, default=None)


# --------------------------------------------------------------------------- provedor: site HTML
@dataclass
class ConfigSite:
    """Como 'ler' o site. Os padrões batem com o site_demo; para outro site, troque os seletores."""
    url_busca: str                         # ex.: "http://127.0.0.1:8765/busca?q={consulta}"
    item: str = "li.resultado"             # cada resultado da busca
    link: str = "a.titulo"                 # dentro do item: link para a página da legenda
    atributo_idioma: str = "data-idioma"   # no item: idioma da legenda
    downloads: str = ".downloads"          # dentro do item: contador de downloads (opcional)
    botao_download: str = "a.download"     # na página da legenda: link do arquivo
    nome: str = "site"


class ProvedorSiteHTML:
    def __init__(self, config: ConfigSite, cliente: ClienteHTTP | None = None):
        self.config = config
        self.cliente = cliente or ClienteHTTP(espera=1.0)
        self.nome = config.nome

    def _html(self, url: str) -> tuple[bytes, str]:
        if not self.cliente.permitido(url):
            raise ErroLegenda(f"robots.txt do site não permite: {url}")
        resultado = self.cliente.obter_html(url)
        if resultado is None:
            raise ErroLegenda(f"não consegui abrir {url}")
        return resultado

    def buscar(self, titulo: str, ano: int | None, idioma: str = IDIOMA_PADRAO,
               temporada: int | None = None, episodio: int | None = None) -> list[CandidatoLegenda]:
        if episodio is not None:
            termo = f"{titulo} S{temporada:02d}E{episodio:02d}"
        else:
            termo = f"{titulo} {ano}" if ano else titulo
        html, url_final = self._html(self.config.url_busca.format(consulta=quote_plus(termo)))
        sopa = BeautifulSoup(html, "lxml")
        candidatos = []
        for item in sopa.select(self.config.item):
            link = item.select_one(self.config.link)
            if not link or not link.get("href"):
                continue
            texto = link.get_text(" ", strip=True)
            ep = extrair_episodio(texto)
            if ep:
                nome, ano_item, temp_item, ep_item = ep.serie, ep.ano, ep.temporada, ep.episodio
            else:
                nome, ano_item = extrair_titulo_e_ano(texto)
                temp_item = ep_item = None
            contador = item.select_one(self.config.downloads) if self.config.downloads else None
            numeros = "".join(ch for ch in (contador.get_text() if contador else "") if ch.isdigit())
            candidatos.append(CandidatoLegenda(
                titulo=nome, ano=ano_item, idioma=item.get(self.config.atributo_idioma, idioma),
                url=urljoin(url_final, link["href"]), downloads=int(numeros or 0), provedor=self.nome,
                temporada=temp_item, episodio=ep_item))
        return candidatos

    def baixar(self, candidato: CandidatoLegenda) -> bytes:
        url = candidato.url
        if not urlparse(url).path.lower().endswith((".srt", ".zip")):   # é a página, não o arquivo
            html, url_final = self._html(url)
            botao = BeautifulSoup(html, "lxml").select_one(self.config.botao_download)
            if not botao or not botao.get("href"):
                raise ErroLegenda("não achei o botão de download na página da legenda")
            url = urljoin(url_final, botao["href"])
        if not self.cliente.permitido(url):
            raise ErroLegenda(f"robots.txt do site não permite: {url}")
        self.cliente.pausar()
        return _baixar_bytes(self.cliente.sessao, url, self.cliente.timeout, referer=candidato.url)


def _baixar_bytes(sessao: requests.Session, url: str, timeout: float, referer: str | None = None) -> bytes:
    try:
        with sessao.get(url, stream=True, timeout=timeout,
                        headers={"Referer": referer} if referer else {}) as r:
            r.raise_for_status()
            dados = bytearray()
            for bloco in r.iter_content(64 * 1024):
                dados += bloco
                if len(dados) > TAMANHO_MAXIMO:
                    raise ErroLegenda("arquivo grande demais para ser uma legenda")
            return bytes(dados)
    except requests.RequestException as erro:
        raise ErroLegenda(f"falha no download: {erro}") from erro


# --------------------------------------------------------------------------- provedor: OpenSubtitles
class ProvedorOpenSubtitles:
    nome = "OpenSubtitles"

    def __init__(self, chave: str, app: str = "jellyfin-tools v1.0",
                 base_url: str = "https://api.opensubtitles.com/api/v1",
                 sessao: requests.Session | None = None, timeout: float = 20):
        if not chave:
            raise ErroLegenda("informe a chave da API do OpenSubtitles (OPENSUBTITLES_API_KEY)")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.sessao = sessao or requests.Session()
        # A API exige um User-Agent com o nome do app e a chave no cabeçalho Api-Key.
        self.sessao.headers.update({"Api-Key": chave, "User-Agent": app, "Accept": "application/json"})
        self.esgotado = False           # limite diário atingido: as próximas legendas vão para a reserva

    def _json(self, metodo: str, caminho: str, **kwargs) -> dict:
        if self.esgotado:
            raise ErroLegenda("limite diário atingido (usando a próxima fonte)")
        try:
            r = self.sessao.request(metodo, f"{self.base_url}{caminho}", timeout=self.timeout, **kwargs)
        except requests.RequestException as erro:
            raise ErroLegenda(f"OpenSubtitles fora do ar ou sem internet: {erro}") from erro
        if r.status_code in (401, 403):
            raise ErroLegenda("OpenSubtitles recusou a chave da API")
        if r.status_code == 406:
            self.esgotado = True
            raise ErroLegenda("limite diário de downloads do OpenSubtitles atingido")
        if r.status_code == 429:
            raise ErroLegenda("OpenSubtitles: muitas consultas seguidas, espere um pouco")
        if not r.ok:
            raise ErroLegenda(f"OpenSubtitles respondeu HTTP {r.status_code}")
        try:
            return r.json()
        except ValueError as erro:
            raise ErroLegenda("OpenSubtitles devolveu uma resposta inválida") from erro

    def buscar(self, titulo: str, ano: int | None, idioma: str = IDIOMA_PADRAO,
               temporada: int | None = None, episodio: int | None = None) -> list[CandidatoLegenda]:
        params = {"query": titulo, "languages": idioma.lower(), "type": "movie"}
        if episodio is not None:
            params.update(type="episode", season_number=temporada, episode_number=episodio)
        elif ano:
            params["year"] = ano          # em séries, não: filtraria pelo ano do EPISÓDIO
        dados = self._json("GET", "/subtitles", params=params)
        candidatos = []
        for item in dados.get("data", []):
            attrs = item.get("attributes", {})
            arquivos = attrs.get("files") or []
            if not arquivos:
                continue
            detalhes = attrs.get("feature_details") or {}
            idioma_item = attrs.get("language", "")
            candidatos.append(CandidatoLegenda(
                titulo=(detalhes.get("parent_title") if episodio is not None else None)
                or detalhes.get("title") or detalhes.get("movie_name") or titulo,
                ano=detalhes.get("year"),
                temporada=detalhes.get("season_number"), episodio=detalhes.get("episode_number"),
                idioma=idioma if idioma_item.lower() == idioma.lower() else idioma_item,
                url=attrs.get("url", ""), downloads=int(attrs.get("download_count") or 0),
                provedor=self.nome, extra={"file_id": arquivos[0].get("file_id")}))
        return candidatos

    def baixar(self, candidato: CandidatoLegenda) -> bytes:
        file_id = candidato.extra.get("file_id")
        if not file_id:
            raise ErroLegenda("resultado sem file_id")
        link = self._json("POST", "/download", json={"file_id": file_id}).get("link")
        if not link:
            raise ErroLegenda("OpenSubtitles não devolveu o link de download")
        return _baixar_bytes(requests.Session(), link, self.timeout)


# --------------------------------------------------------------------------- provedor: SubDL
# Códigos de idioma do SubDL (os mesmos que o Bazarr usa): pt-BR -> BR_PT, pt -> PT, en -> EN...
IDIOMAS_SUBDL = {"pt-br": "BR_PT", "pt": "PT", "en": "EN", "es": "ES", "fr": "FR", "it": "IT", "de": "DE",
                 "ja": "JA", "ko": "KO", "zh": "ZH", "ru": "RU", "ar": "AR", "nl": "NL", "pl": "PL", "tr": "TR"}


def _numero(valor) -> int | None:
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


class ProvedorSubDL:
    """API oficial do SubDL (https://subdl.com/panel/api): chave gratuita, boa RESERVA para quando o
    OpenSubtitles atinge o limite diário. GET api.subdl.com/api/v1/subtitles; o arquivo (.zip) vem
    de dl.subdl.com."""
    nome = "SubDL"

    def __init__(self, chave: str, base_url: str = "https://api.subdl.com/api/v1",
                 base_download: str = "https://dl.subdl.com", sessao: requests.Session | None = None,
                 timeout: float = 20):
        if not chave:
            raise ErroLegenda("informe a chave da API do SubDL (SUBDL_API_KEY)")
        self.chave = chave
        self.base_url = base_url.rstrip("/")
        self.base_download = base_download.rstrip("/")
        self.timeout = timeout
        self.sessao = sessao or requests.Session()
        self.sessao.headers.update({"User-Agent": "jellyfin-tools v1.0", "Accept": "application/json"})
        self.esgotado = False

    def buscar(self, titulo: str, ano: int | None, idioma: str = IDIOMA_PADRAO,
               temporada: int | None = None, episodio: int | None = None) -> list[CandidatoLegenda]:
        if self.esgotado:
            raise ErroLegenda("limite do SubDL atingido")
        codigo = IDIOMAS_SUBDL.get(idioma.lower(), idioma.split("-")[0].upper())
        params = {"api_key": self.chave, "film_name": titulo, "languages": codigo, "subs_per_page": 30,
                  "type": "movie" if episodio is None else "tv"}
        if episodio is not None:
            params.update(season_number=temporada, episode_number=episodio)
        elif ano:
            params["year"] = ano
        try:
            r = self.sessao.get(f"{self.base_url}/subtitles", params=params, timeout=self.timeout)
        except requests.RequestException as erro:
            raise ErroLegenda(f"SubDL fora do ar ou sem internet: {erro}") from erro
        if r.status_code in (401, 403):
            raise ErroLegenda("SubDL recusou a chave da API")
        if r.status_code in (402, 429):
            self.esgotado = True
            raise ErroLegenda("limite de consultas do SubDL atingido")
        if not r.ok:
            raise ErroLegenda(f"SubDL respondeu HTTP {r.status_code}")
        try:
            dados = r.json()
        except ValueError as erro:
            raise ErroLegenda("SubDL devolveu uma resposta inválida") from erro
        if dados.get("status") is False and "key" in str(dados.get("error", "")).lower():
            raise ErroLegenda(f"SubDL: {dados.get('error')}")
        obra = (dados.get("results") or [{}])[0]          # a obra encontrada (nome e ano oficiais)
        candidatos = []
        for item in dados.get("subtitles") or []:
            caminho = item.get("url") or ""
            outro_idioma = str(item.get("language") or "").upper()
            if not caminho or (outro_idioma in IDIOMAS_SUBDL.values() and outro_idioma != codigo):
                continue
            if episodio is not None:
                if item.get("full_season"):
                    continue                              # pacote da temporada inteira: não é ESTE episódio
                temp_item, ep_item = _numero(item.get("season")), _numero(item.get("episode"))
                if ep_item is not None and ((temp_item or temporada), ep_item) != (temporada, episodio):
                    continue
            candidatos.append(CandidatoLegenda(
                titulo=obra.get("name") or titulo, ano=obra.get("year") if episodio is None else None,
                idioma=idioma, url=self.base_download + "/" + caminho.lstrip("/"), provedor=self.nome,
                temporada=temporada, episodio=episodio, extra={"release": item.get("release_name", "")}))
        return candidatos

    def baixar(self, candidato: CandidatoLegenda) -> bytes:
        return _baixar_bytes(self.sessao, candidato.url, self.timeout)


# --------------------------------------------------------------------------- orquestração
def baixar_legenda(pasta_filme: str | Path, provedores: list, titulo: str | None = None,
                   ano: int | None = None, idioma: str = IDIOMA_PADRAO,
                   sobrescrever: bool = False,
                   titulos_alternativos: list[str] | None = None) -> ResultadoLegenda:
    """Baixa a legenda para UMA pasta de filme. Título/ano saem do nome da pasta se não informados.
    `titulos_alternativos`: outros nomes para tentar se o principal não achar nada (ex.: o título
    original "Interstellar" quando a pasta está com o brasileiro "Interestelar")."""
    pasta = Path(pasta_filme)
    if not pasta.is_dir():
        return ResultadoLegenda(pasta, "erro", detalhe="pasta não existe")
    if titulo is None:
        lido = ler_nome_jellyfin(pasta.name)
        if not lido:
            return ResultadoLegenda(pasta, "erro", detalhe="nome da pasta fora do padrão 'Nome (Ano)'")
        titulo, ano = lido.titulo, lido.ano

    return _baixar_para(caminho_da_legenda(pasta, idioma), pasta, provedores, titulo, ano, idioma,
                        sobrescrever, titulos_alternativos)


def baixar_legenda_episodio(video: str | Path, provedores: list, serie: str | None = None,
                            temporada: int | None = None, episodio: int | None = None,
                            ano: int | None = None, idioma: str = IDIOMA_PADRAO, sobrescrever: bool = False,
                            titulos_alternativos: list[str] | None = None) -> ResultadoLegenda:
    """Legenda de UM episódio: 'Season 01/Dark S01E02.mkv' -> 'Season 01/Dark S01E02.pt-BR.srt'.
    Série/temporada/episódio saem do nome do arquivo (e o ano, da pasta da série) se não informados."""
    video = Path(video)
    if not video.is_file():
        return ResultadoLegenda(video.parent, "erro", detalhe=f"vídeo não existe: {video.name}")
    if serie is None or episodio is None:
        ep = extrair_episodio(video.name)
        if not ep:
            return ResultadoLegenda(video.parent, "erro", detalhe=f"sem S01E02 no nome: {video.name}")
        serie, temporada, episodio = serie or ep.serie, ep.temporada, ep.episodio
        pasta_serie = ler_nome_jellyfin(video.parent.parent.name)       # "Dark (2017)"
        ano = ano or ep.ano or (pasta_serie.ano if pasta_serie else None)
    destino = video.with_name(f"{video.stem}.{idioma}.srt")
    return _baixar_para(destino, video.parent, provedores, serie, ano, idioma, sobrescrever,
                        titulos_alternativos, temporada, episodio)


def _baixar_para(destino: Path, pasta: Path, provedores: list, titulo: str, ano: int | None, idioma: str,
                 sobrescrever: bool, titulos_alternativos: list[str] | None,
                 temporada: int | None = None, episodio: int | None = None) -> ResultadoLegenda:
    """Núcleo comum de filmes e episódios: procura nos provedores e grava `destino`."""
    if destino.exists() and not sobrescrever:
        return ResultadoLegenda(pasta, "ja_existe", destino)
    extras = {"temporada": temporada, "episodio": episodio} if episodio is not None else {}

    titulos = list(dict.fromkeys(t for t in [titulo, *(titulos_alternativos or [])] if t))  # sem repetir
    problemas = []
    for provedor in provedores:
        try:
            escolhido = None
            for tentativa in titulos:
                candidatos = provedor.buscar(tentativa, ano, idioma, **extras)
                escolhido = escolher_melhor(candidatos, tentativa, ano, idioma, temporada, episodio)
                if escolhido:
                    break
            if not escolhido:
                problemas.append(f"{provedor.nome}: nada compatível com {' / '.join(titulos)}")
                continue
            texto = extrair_srt(provedor.baixar(escolhido))
            temporario = destino.with_name(destino.name + ".part")
            temporario.write_text(texto, encoding="utf-8")     # UTF-8: o Jellyfin lê acentos certo
            temporario.replace(destino)
            return ResultadoLegenda(pasta, "baixada", destino, f"{provedor.nome}: {escolhido.titulo}")
        except ErroLegenda as erro:
            problemas.append(f"{provedor.nome}: {erro}")
        except OSError as erro:                                 # sem permissão para gravar etc.
            return ResultadoLegenda(pasta, "erro", detalhe=str(erro))
    return ResultadoLegenda(pasta, "nao_encontrada", detalhe="; ".join(problemas))


def _titulo_original(catalogo, pasta: Path, tipo: str = "filme") -> list[str]:
    """Consulta o catálogo para descobrir o título original (ex.: Interestelar -> Interstellar)."""
    lido = ler_nome_jellyfin(pasta.name)
    if not catalogo or not lido:
        return []
    try:
        filme = catalogo.buscar(lido.titulo, lido.ano, tipo)
    except Exception:                 # catálogo fora do ar não impede a legenda pelo título da pasta
        return []
    return [filme.titulo_original] if filme and filme.titulo_original else []


def pastas_de_filmes(pasta_filmes: str | Path) -> list[Path]:
    """Pastas de filme da biblioteca que têm vídeo dentro."""
    return [p for p in sorted(Path(pasta_filmes).iterdir())
            if p.is_dir() and not p.name.startswith(".") and any(eh_video(a) for a in p.iterdir() if a.is_file())]


def episodios_da_biblioteca(pasta_series: str | Path) -> list[Path]:
    """Todos os vídeos de episódio: Séries/<Série>/<Season NN>/<vídeo>."""
    return sorted(v for v in Path(pasta_series).glob("*/*/*")
                  if v.is_file() and eh_video(v) and not v.parts[-3].startswith("."))


def baixar_legendas_biblioteca(pasta_filmes: str | Path, provedores: list, idioma: str = IDIOMA_PADRAO,
                               sobrescrever: bool = False, catalogo=None,
                               ao_terminar=None, parar=None) -> list[ResultadoLegenda]:
    """Passa por todas as pastas 'Nome (Ano)' da biblioteca e baixa o que estiver faltando.
    Com `catalogo`, também tenta o título original de cada filme.
    `ao_terminar(indice, resultado)` é chamado a cada filme (para mostrar o andamento);
    `parar()` devolvendo True interrompe entre um filme e outro."""
    resultados = []
    for i, pasta in enumerate(pastas_de_filmes(pasta_filmes)):
        if parar and parar():
            break
        resultado = baixar_legenda(pasta, provedores, idioma=idioma, sobrescrever=sobrescrever,
                                   titulos_alternativos=_titulo_original(catalogo, pasta))
        print(resultado, file=sys.stderr)
        resultados.append(resultado)
        if ao_terminar:
            ao_terminar(i, resultado)
    return resultados


def baixar_legendas_series(pasta_series: str | Path, provedores: list, idioma: str = IDIOMA_PADRAO,
                           sobrescrever: bool = False, catalogo=None,
                           ao_terminar=None, parar=None) -> list[ResultadoLegenda]:
    """Igual a baixar_legendas_biblioteca, mas episódio por episódio de Séries/."""
    resultados = []
    for i, video in enumerate(episodios_da_biblioteca(pasta_series)):
        if parar and parar():
            break
        alternativos = _titulo_original(catalogo, video.parent.parent, "serie")
        resultado = baixar_legenda_episodio(video, provedores, idioma=idioma, sobrescrever=sobrescrever,
                                            titulos_alternativos=alternativos)
        print(f"{resultado} {video.name}", file=sys.stderr)
        resultados.append(resultado)
        if ao_terminar:
            ao_terminar(i, resultado)
    return resultados
