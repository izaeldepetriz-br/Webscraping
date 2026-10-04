"""Busca e baixa legendas para a pasta do filme, no padrão do Jellyfin:

    Filmes/Matrix (1999)/Matrix (1999).mkv
    Filmes/Matrix (1999)/Matrix (1999).pt-BR.srt   <- mesmo nome do vídeo + .pt-BR.srt

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

from .nomes import eh_video, extrair_titulo_e_ano, ler_nome_jellyfin, similaridade

IDIOMA_PADRAO = "pt-BR"
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
                    idioma: str) -> CandidatoLegenda | None:
    """Mesmo idioma, mesmo ano, título parecido; entre os bons, o mais baixado."""
    bons = []
    for c in candidatos:
        if c.idioma.lower() != idioma.lower():
            continue
        if ano and c.ano and c.ano != ano:
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

    def buscar(self, titulo: str, ano: int | None, idioma: str = IDIOMA_PADRAO) -> list[CandidatoLegenda]:
        consulta = quote_plus(f"{titulo} {ano}" if ano else titulo)
        html, url_final = self._html(self.config.url_busca.format(consulta=consulta))
        sopa = BeautifulSoup(html, "lxml")
        candidatos = []
        for item in sopa.select(self.config.item):
            link = item.select_one(self.config.link)
            if not link or not link.get("href"):
                continue
            extraido = extrair_titulo_e_ano(link.get_text(" ", strip=True))
            contador = item.select_one(self.config.downloads) if self.config.downloads else None
            numeros = "".join(ch for ch in (contador.get_text() if contador else "") if ch.isdigit())
            candidatos.append(CandidatoLegenda(
                titulo=extraido.titulo, ano=extraido.ano,
                idioma=item.get(self.config.atributo_idioma, idioma),
                url=urljoin(url_final, link["href"]), downloads=int(numeros or 0), provedor=self.nome))
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

    def _json(self, metodo: str, caminho: str, **kwargs) -> dict:
        try:
            r = self.sessao.request(metodo, f"{self.base_url}{caminho}", timeout=self.timeout, **kwargs)
        except requests.RequestException as erro:
            raise ErroLegenda(f"OpenSubtitles fora do ar ou sem internet: {erro}") from erro
        if r.status_code in (401, 403):
            raise ErroLegenda("OpenSubtitles recusou a chave da API")
        if r.status_code == 406:
            raise ErroLegenda("limite diário de downloads do OpenSubtitles atingido")
        if r.status_code == 429:
            raise ErroLegenda("OpenSubtitles: muitas consultas seguidas, espere um pouco")
        if not r.ok:
            raise ErroLegenda(f"OpenSubtitles respondeu HTTP {r.status_code}")
        try:
            return r.json()
        except ValueError as erro:
            raise ErroLegenda("OpenSubtitles devolveu uma resposta inválida") from erro

    def buscar(self, titulo: str, ano: int | None, idioma: str = IDIOMA_PADRAO) -> list[CandidatoLegenda]:
        params = {"query": titulo, "languages": idioma.lower(), "type": "movie"}
        if ano:
            params["year"] = ano
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
                titulo=detalhes.get("title") or detalhes.get("movie_name") or titulo,
                ano=detalhes.get("year"),
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


# --------------------------------------------------------------------------- orquestração
def baixar_legenda(pasta_filme: str | Path, provedores: list, titulo: str | None = None,
                   ano: int | None = None, idioma: str = IDIOMA_PADRAO,
                   sobrescrever: bool = False) -> ResultadoLegenda:
    """Baixa a legenda para UMA pasta de filme. Título/ano saem do nome da pasta se não informados."""
    pasta = Path(pasta_filme)
    if not pasta.is_dir():
        return ResultadoLegenda(pasta, "erro", detalhe="pasta não existe")
    if titulo is None:
        lido = ler_nome_jellyfin(pasta.name)
        if not lido:
            return ResultadoLegenda(pasta, "erro", detalhe="nome da pasta fora do padrão 'Nome (Ano)'")
        titulo, ano = lido.titulo, lido.ano

    destino = caminho_da_legenda(pasta, idioma)
    if destino.exists() and not sobrescrever:
        return ResultadoLegenda(pasta, "ja_existe", destino)

    problemas = []
    for provedor in provedores:
        try:
            escolhido = escolher_melhor(provedor.buscar(titulo, ano, idioma), titulo, ano, idioma)
            if not escolhido:
                problemas.append(f"{provedor.nome}: nada compatível")
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


def baixar_legendas_biblioteca(pasta_filmes: str | Path, provedores: list, idioma: str = IDIOMA_PADRAO,
                               sobrescrever: bool = False) -> list[ResultadoLegenda]:
    """Passa por todas as pastas 'Nome (Ano)' da biblioteca e baixa o que estiver faltando."""
    resultados = []
    for pasta in sorted(p for p in Path(pasta_filmes).iterdir() if p.is_dir() and not p.name.startswith(".")):
        if not any(eh_video(p) for p in pasta.iterdir() if p.is_file()):
            resultados.append(ResultadoLegenda(pasta, "sem_video"))
            continue
        resultado = baixar_legenda(pasta, provedores, idioma=idioma, sobrescrever=sobrescrever)
        print(resultado, file=sys.stderr)
        resultados.append(resultado)
    return resultados
