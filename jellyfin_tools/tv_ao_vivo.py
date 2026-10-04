"""Canais ao vivo no Jellyfin (TV ao vivo): a lista de canais (.m3u), o guia (XMLTV) e a antena.

O Jellyfin já sabe passar TV ao vivo; ele só precisa de duas peças, cadastradas em
Painel -> TV ao vivo. Este módulo monta e cadastra as duas pela API:

    sintonizador = de onde vêm os canais
        "m3u"       -> uma lista .m3u: nome + link de cada canal (gerada aqui)
        "hdhomerun" -> um sintonizador de ANTENA na rede (TV aberta digital, de graça e legal)
    guia (XMLTV)  -> a programação ("o que está passando"), um arquivo/endereço .xml; sem ele os
                     canais aparecem, mas sem a grade de horários

Use só fontes que você tem direito de assistir: o sinal aberto oficial (antena ou a transmissão que o
próprio canal publica), a lista da sua operadora de TV/IPTV. Listas "piratas" de canais pagos não.

Conferir um canal: o link está no ar? (.m3u8 -> a playlist responde e começa com #EXTM3U; outro
fluxo -> responde com vídeo/áudio). Links "assinados" (token=, expires=) param de funcionar.
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path

import requests

from .espelho import _RE_TEMPORARIO
from .registro import obter_logger
from .servidor_jellyfin import ErroJellyfin, _cabecalhos

log = obter_logger()
NOME_SINTONIZADOR = "videoscraper"
_TIPOS_FLUXO = ("video/", "audio/", "application/vnd.apple.mpegurl", "application/x-mpegurl",
                "application/octet-stream", "application/mp2t")


@dataclass
class Canal:
    nome: str
    url: str
    grupo: str = ""        # "Notícias", "Abertos"... (group-title)
    logo: str = ""         # tvg-logo
    id_guia: str = ""      # tvg-id: liga o canal à programação do guia (XMLTV)


# ----------------------------------------------------------------- a lista (.m3u)
_RE_ATRIBUTO = re.compile(r'([\w-]+)="([^"]*)"')


def ler_m3u(texto: str) -> list[Canal]:
    """'#EXTINF:-1 tvg-id="tvcultura.br" tvg-logo="..." group-title="Abertos",TV Cultura' + o link na linha de baixo."""
    canais, info = [], None
    for linha in texto.splitlines():
        linha = linha.strip()
        if linha.upper().startswith("#EXTINF"):
            atributos = dict(_RE_ATRIBUTO.findall(linha))
            nome = linha.rsplit(",", 1)[-1].strip() if "," in linha else ""
            info = Canal(nome or atributos.get("tvg-name", ""), "", atributos.get("group-title", ""),
                         atributos.get("tvg-logo", ""), atributos.get("tvg-id", ""))
        elif linha and not linha.startswith("#"):
            canal = info or Canal("", "")
            canal.url = linha
            canal.nome = canal.nome or linha.rsplit("/", 1)[-1]
            canais.append(canal)
            info = None
    return canais


def gerar_m3u(canais: list[Canal], guia: str = "") -> str:
    cabecalho = f'#EXTM3U url-tvg="{guia}"' if guia else "#EXTM3U"
    linhas = [cabecalho]
    for c in canais:
        atributos = " ".join(f'{chave}="{valor}"' for chave, valor in
                             (("tvg-id", c.id_guia), ("tvg-name", c.nome), ("tvg-logo", c.logo),
                              ("group-title", c.grupo)) if valor)
        linhas += [f"#EXTINF:-1 {atributos},{c.nome}".replace("-1 ,", "-1,"), c.url]
    return "\n".join(linhas) + "\n"


def carregar_canais(arquivo: str | Path) -> list[Canal]:
    try:
        return [Canal(**c) for c in json.loads(Path(arquivo).read_text(encoding="utf-8"))]
    except (OSError, ValueError, TypeError):
        return []


def salvar_canais(arquivo: str | Path, canais: list[Canal]) -> None:
    Path(arquivo).parent.mkdir(parents=True, exist_ok=True)
    Path(arquivo).write_text(json.dumps([asdict(c) for c in canais], ensure_ascii=False, indent=2), encoding="utf-8")


def importar(origem: str, timeout: float = 20) -> list[Canal]:
    """Lista .m3u de um arquivo do PC ou de um endereço (http...)."""
    if origem.lower().startswith(("http://", "https://")):
        r = requests.get(origem, timeout=timeout)
        r.raise_for_status()
        return ler_m3u(r.text)
    return ler_m3u(Path(origem).read_text(encoding="utf-8", errors="replace"))


# ----------------------------------------------------------------- conferir (o canal está no ar?)
@dataclass
class Situacao:
    ok: bool
    detalhe: str = ""


def conferir_canal(url: str, timeout: float = 10, sessao: requests.Session | None = None) -> Situacao:
    sessao = sessao or requests
    aviso = "; link temporário (token/expires): deve parar de funcionar" if _RE_TEMPORARIO.search(url) else ""
    try:
        with sessao.get(url, timeout=timeout, stream=True, headers={"User-Agent": "Mozilla/5.0"}) as r:
            if r.status_code in (401, 403):
                return Situacao(False, f"o canal pede login (HTTP {r.status_code})")
            if not r.ok:
                return Situacao(False, f"fora do ar (HTTP {r.status_code})")
            tipo = r.headers.get("Content-Type", "").lower()
            inicio = next(r.iter_content(2048), b"")
    except requests.RequestException as erro:
        return Situacao(False, f"sem resposta ({type(erro).__name__})")
    if ".m3u8" in url.lower() or "mpegurl" in tipo:
        if not inicio.lstrip().startswith(b"#EXTM3U"):
            return Situacao(False, "o endereço respondeu, mas não é uma transmissão (.m3u8 sem #EXTM3U)")
        return Situacao(True, "no ar" + aviso)
    if tipo.startswith("text/html"):
        return Situacao(False, "é uma página, não o sinal do canal")
    if tipo and not tipo.startswith(_TIPOS_FLUXO):
        return Situacao(False, f"não parece vídeo/áudio ({tipo})")
    return Situacao(True, "no ar" + aviso)


def conferir_canais(canais: list[Canal], trabalhadores: int = 8, ao_progresso=None) -> list[tuple[Canal, Situacao]]:
    feitos = 0
    resultado: dict[int, Situacao] = {}

    def um(indice: int) -> None:
        nonlocal feitos
        resultado[indice] = conferir_canal(canais[indice].url)
        feitos += 1
        if ao_progresso:
            ao_progresso(feitos, len(canais))

    with ThreadPoolExecutor(max_workers=max(1, trabalhadores)) as grupo:
        list(grupo.map(um, range(len(canais))))
    return [(c, resultado[i]) for i, c in enumerate(canais)]


def mensagem_fora_do_ar(fora: list[tuple[Canal, Situacao]], limite: int = 15) -> tuple[str, str]:
    import html
    titulo = f"{len(fora)} canal(is) ao vivo fora do ar"
    linhas = [(c.nome, s.detalhe) for c, s in fora[:limite]]
    resto = f"\n… e mais {len(fora) - limite}" if len(fora) > limite else ""
    discord = f"\U0001F4FA **{titulo}**\n" + "\n".join(f"• {n} — {d}" for n, d in linhas) + resto
    telegram = (f"\U0001F4FA <b>{html.escape(titulo)}</b>\n"
                + "\n".join(f"• {html.escape(n)} — {html.escape(d)}" for n, d in linhas) + resto)
    return discord, telegram


# ----------------------------------------------------------------- cadastrar no Jellyfin
class ClienteTV:
    """Painel -> TV ao vivo, pela API (a chave de API do Painel é de administrador)."""

    def __init__(self, url: str, chave: str, timeout: float = 20, sessao: requests.Session | None = None):
        if not url or not chave:
            raise ErroJellyfin("preencha o endereço e a chave de API do Jellyfin")
        self.base, self.cabecalhos = url.rstrip("/"), _cabecalhos(chave)
        self.timeout, self.sessao = timeout, sessao or requests.Session()

    def _pedir(self, metodo: str, caminho: str, **extra):
        try:
            r = self.sessao.request(metodo, self.base + caminho, headers=self.cabecalhos, timeout=self.timeout, **extra)
        except requests.RequestException as erro:
            raise ErroJellyfin(f"não consegui falar com o Jellyfin em {self.base}: {erro}") from erro
        if r.status_code in (401, 403):
            raise ErroJellyfin("o Jellyfin recusou a chave (use uma chave do Painel > Chaves de API)")
        if not r.ok:
            raise ErroJellyfin(f"o Jellyfin respondeu HTTP {r.status_code} em {caminho}: {r.text[:200]}")
        return r.json() if r.content and "json" in r.headers.get("Content-Type", "") else None

    def configuracao(self) -> dict:
        return self._pedir("GET", "/System/Configuration/livetv") or {}

    def cadastrar_sintonizador(self, tipo: str, endereco: str, nome: str = NOME_SINTONIZADOR) -> dict:
        """tipo 'm3u' (endereco = o .m3u, como o SERVIDOR enxerga) ou 'hdhomerun' (endereco = IP da antena).
        Se já existe um com o mesmo endereço, ou o nosso do mesmo tipo, ele é atualizado (não duplica)."""
        existente = next((t for t in self.configuracao().get("TunerHosts") or []
                          if t.get("Url") == endereco or (t.get("FriendlyName") == nome and t.get("Type") == tipo)),
                         None)
        corpo = {**(existente or {}), "Type": tipo, "Url": endereco, "FriendlyName": nome,
                 "ImportFavoritesOnly": False, "AllowHWTranscoding": False, "EnableStreamLooping": False,
                 "TunerCount": (existente or {}).get("TunerCount", 0), "Source": ""}
        return self._pedir("POST", "/LiveTv/TunerHosts", json=corpo) or corpo

    def cadastrar_guia(self, endereco: str) -> dict:
        """Guia XMLTV (arquivo ou endereço .xml/.xml.gz), para todos os sintonizadores."""
        existente = next((p for p in self.configuracao().get("ListingProviders") or []
                          if p.get("Type") == "xmltv" and p.get("Path") == endereco), None)
        corpo = {**(existente or {}), "Type": "xmltv", "Path": endereco, "EnableAllTuners": True}
        return self._pedir("POST", "/LiveTv/ListingProviders", json=corpo,
                           params={"validateListings": "false", "validateLogin": "false"}) or corpo

    def atualizar_guia(self) -> bool:
        """Roda a tarefa 'Atualizar o guia' agora (senão o Jellyfin espera o horário dela)."""
        tarefas = self._pedir("GET", "/ScheduledTasks") or []
        tarefa = next((t for t in tarefas if t.get("Key") == "RefreshGuide"), None)
        if not tarefa:
            return False
        self._pedir("POST", f"/ScheduledTasks/Running/{tarefa['Id']}")
        return True


def publicar(canais: list[Canal], pasta: str | Path, caminho_no_servidor: str = "", guia: str = "",
             cliente: ClienteTV | None = None, antena: str = "") -> list[str]:
    """Grava '<pasta>/canais.m3u' e (com o cliente) cadastra no Jellyfin: a lista, o guia e a antena.
    caminho_no_servidor: como o SERVIDOR do Jellyfin enxerga o arquivo, se for outro computador
    (ex.: 'E:\\TV\\canais.m3u' lá, '\\\\Servidor\\e\\TV\\canais.m3u' aqui). Vazio = o mesmo caminho."""
    feito = []
    if canais:
        arquivo = Path(pasta) / "canais.m3u"
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        arquivo.write_text(gerar_m3u(canais, guia), encoding="utf-8")
        feito.append(f"lista salva: {arquivo} ({len(canais)} canal(is))")
    if cliente is None:
        return feito
    if canais:
        endereco = caminho_no_servidor.strip() or str(Path(pasta) / "canais.m3u")
        cliente.cadastrar_sintonizador("m3u", endereco)
        feito.append(f"Jellyfin: sintonizador M3U -> {endereco}")
    if antena.strip():
        cliente.cadastrar_sintonizador("hdhomerun", antena.strip(), f"{NOME_SINTONIZADOR} antena")
        feito.append(f"Jellyfin: sintonizador de antena HDHomeRun -> {antena.strip()}")
    if guia.strip():
        cliente.cadastrar_guia(guia.strip())
        feito.append(f"Jellyfin: guia de programação (XMLTV) -> {guia.strip()}")
    if cliente.atualizar_guia():
        feito.append("Jellyfin: atualizando o guia agora (os canais aparecem em TV ao vivo em alguns minutos)")
    return feito
