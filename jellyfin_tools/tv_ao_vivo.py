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
from dataclasses import asdict, dataclass
from pathlib import Path

import requests

from .espelho import _RE_TEMPORARIO
from .paralelo import em_paralelo
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
# Só isto vira canal: um link de verdade (o resto de uma página HTML, por exemplo, é ignorado)
_RE_LINK = re.compile(r"^(?:https?|rtsps?|rtmps?|rtp|udp|mms)://\S+$", re.IGNORECASE)


class NaoEhLista(ValueError):
    """O endereço/arquivo não é uma lista de canais (.m3u): é uma página, por exemplo."""


def parece_lista(texto: str) -> bool:
    inicio = texto.lstrip("\ufeff \r\n\t")[:4096].lower()
    if inicio.startswith(("<!doctype", "<html")) or "<head" in inicio[:600]:
        return False
    return "#extinf" in texto.lower() or inicio.startswith("#extm3u")


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
            if not _RE_LINK.match(linha):            # HTML, texto solto...: não é canal
                info = None
                continue
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
    """Lista .m3u de um arquivo do PC ou de um endereço (http...). Lança NaoEhLista se o conteúdo
    não for uma lista de canais (ex.: o endereço é uma página de site)."""
    if origem.lower().startswith(("http://", "https://")):
        r = requests.get(origem, timeout=timeout)
        r.raise_for_status()
        texto = r.text
    else:
        texto = Path(origem).read_text(encoding="utf-8", errors="replace")
    if not parece_lista(texto):
        raise NaoEhLista("isso não é uma lista de canais (.m3u): parece uma página de site. Use o link "
                         "que termina em .m3u (a lista) ou o link do sinal de um canal (.m3u8).")
    canais = ler_m3u(texto)
    if not canais:
        raise NaoEhLista("a lista .m3u não tem nenhum canal com link")
    return canais


# ----------------------------------------------------------------- conferir (o canal está no ar?)
@dataclass
class Situacao:
    ok: bool
    detalhe: str = ""
    servidor_caiu: bool = False     # nem conectou (o servidor inteiro, não só este canal)


TEMPO_CONECTAR, TEMPO_RESPOSTA = 3, 6     # segundos: conectar / esperar cada pedaço da resposta
PRAZO_POR_CANAL = 12                      # nenhum canal segura a fila mais que isso (somando tudo)


def _primeiros_bytes(resposta, quantos: int, prazo: float = TEMPO_RESPOSTA) -> bytes:
    """O começo da resposta, sem ficar preso: lê o que já chegou (read1) até ter `quantos` bytes, o fim
    ou o prazo. (Ler "2048 bytes" de uma vez esperava os 2048; um servidor que manda 1 byte por vez
    prendia a consulta por minutos.)"""
    import time
    ler = getattr(resposta.raw, "read1", None)
    if ler is None:                                       # urllib3 antigo
        return next(resposta.iter_content(2048), b"")
    inicio, limite = b"", time.monotonic() + prazo
    while len(inicio) < quantos and time.monotonic() < limite:
        parte = ler(2048, decode_content=True)
        if not parte:
            break
        inicio += parte
    return inicio


def conferir_canal(url: str, timeout=(TEMPO_CONECTAR, TEMPO_RESPOSTA),
                   sessao: requests.Session | None = None) -> Situacao:
    """timeout: (conectar, esperar a resposta). Um canal que nem conecta em 3 s está fora do ar."""
    sessao = sessao or requests
    aviso = "; link temporário (token/expires): deve parar de funcionar" if _RE_TEMPORARIO.search(url) else ""
    try:
        with sessao.get(url, timeout=timeout, stream=True, headers={"User-Agent": "Mozilla/5.0"}) as r:
            if r.status_code in (401, 403):
                return Situacao(False, f"o canal pede login (HTTP {r.status_code})")
            if not r.ok:
                return Situacao(False, f"fora do ar (HTTP {r.status_code})")
            tipo = r.headers.get("Content-Type", "").lower()
            inicio = _primeiros_bytes(r, 7 if ".m3u8" in url.lower() or "mpegurl" in tipo else 1)
    except (requests.ConnectionError, requests.Timeout) as erro:
        # não conectou, ou conectou e ficou mudo: conta como falha do SERVIDOR (os outros canais dele
        # provavelmente estão iguais)
        nome = "demorou demais para responder" if isinstance(erro, requests.ReadTimeout) else "sem resposta"
        return Situacao(False, f"{nome} ({type(erro).__name__})", servidor_caiu=True)
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


FALHAS_PARA_DESISTIR = 2      # 2 canais do mesmo servidor sem resposta (e nenhum que respondeu): desiste dele
POR_SERVIDOR = 6              # no máximo 6 consultas ao MESMO servidor ao mesmo tempo (não sobrecarrega nem é bloqueado)


def _servidores_que_existem(urls: list[str], parar=None) -> set[str]:
    """Os nomes de servidor que o DNS encontra. Feito UMA vez por servidor, todos ao mesmo tempo:
    servidor que não existe mais (comum em listas velhas) sai na hora, sem esperar canal por canal."""
    import socket
    from urllib.parse import urlparse
    nomes = sorted({h for h in (urlparse(u).hostname for u in urls) if h})

    def existe(nome: str) -> bool:
        try:
            socket.getaddrinfo(nome, None)
            return True
        except (OSError, UnicodeError):
            return False
    achados = em_paralelo(nomes, existe, 64, parar=parar, prazo=5, ao_estourar=lambda _: False)
    return {n for i, n in enumerate(nomes) if achados.get(i, True)}


def _intercalar_por_servidor(canais: list[Canal]) -> list[int]:
    """Ordem de conferência: 1º canal de cada servidor, depois o 2º de cada um... Assim vários servidores
    trabalham ao mesmo tempo e um servidor morto é descoberto logo no começo (não no meio da lista)."""
    from urllib.parse import urlparse
    vez: dict[str, int] = {}
    chave = []
    for i, c in enumerate(canais):
        servidor = urlparse(c.url).netloc.lower()
        vez[servidor] = vez.get(servidor, 0) + 1
        chave.append((vez[servidor], i))
    return [i for _, i in sorted(chave)]


def conferir_canais(canais: list[Canal], trabalhadores: int = 32, ao_progresso=None,
                    parar=None) -> list[tuple[Canal, Situacao]]:
    """Confere vários canais ao mesmo tempo. Mais rápido em listas grandes:
      - servidores que não existem (DNS) são descobertos de uma vez, antes de tudo;
      - os canais são intercalados por servidor (vários servidores trabalhando juntos);
      - no máximo POR_SERVIDOR consultas ao mesmo servidor ao mesmo tempo;
      - servidor que nunca respondeu e já falhou em 2 canais (não conectou OU ficou mudo): os outros
        canais dele saem "fora do ar" sem esperar;
      - nenhum canal demora mais que PRAZO_POR_CANAL segundos.
    Com parar() verdadeiro, para NA HORA e devolve só os conferidos."""
    import threading
    from urllib.parse import urlparse
    local, trava = threading.local(), threading.Lock()
    falhas: dict[str, int] = {}
    responderam: set[str] = set()
    vagas: dict[str, threading.Semaphore] = {}
    # com proxy configurado quem procura o servidor é o proxy: aí não dá para julgar pelo DNS daqui
    existem = None if requests.utils.getproxies() else _servidores_que_existem([c.url for c in canais], parar)
    if parar and parar():
        return []

    def desistiu(servidor: str) -> Situacao | None:
        if servidor not in responderam and falhas.get(servidor, 0) >= FALHAS_PARA_DESISTIR:
            return Situacao(False, f"o servidor {servidor} não responde (outros canais dele já falharam)", True)
        return None

    def falhou(servidor: str) -> None:
        with trava:
            falhas[servidor] = falhas.get(servidor, 0) + 1

    def um(canal: Canal) -> Situacao:
        p = urlparse(canal.url)
        servidor = p.netloc.lower()
        if existem is not None and p.hostname and p.hostname not in existem:
            return Situacao(False, f"o servidor {p.hostname} não existe mais (endereço não encontrado)", True)
        with trava:
            if parou := desistiu(servidor):
                return parou
            vaga = vagas.setdefault(servidor, threading.Semaphore(POR_SERVIDOR))
        if not hasattr(local, "sessao"):
            local.sessao = requests.Session()
            local.sessao.max_redirects = 5
        with vaga:
            with trava:                                  # enquanto esperava a vez, o servidor pode ter caído
                if parou := desistiu(servidor):
                    return parou
            situacao = conferir_canal(canal.url, sessao=local.sessao)
        if situacao.servidor_caiu:
            falhou(servidor)
        else:
            with trava:
                responderam.add(servidor)
        return situacao

    def estourou(canal: Canal) -> Situacao:
        falhou(urlparse(canal.url).netloc.lower())
        return Situacao(False, f"sem resposta em {PRAZO_POR_CANAL} s", servidor_caiu=True)

    ordem = _intercalar_por_servidor(canais)
    resultado = em_paralelo([canais[i] for i in ordem], um, trabalhadores, ao_progresso, parar,
                            prazo=PRAZO_POR_CANAL, ao_estourar=estourou)
    por_posicao = {ordem[k]: s for k, s in resultado.items()}        # volta para a ordem da lista
    return [(canais[i], por_posicao[i]) for i in sorted(por_posicao)]


def exportar_tabela(linhas: list[dict], caminho) -> Path:
    """Salva as linhas da tabela de canais ({canal, grupo, situacao, no_ar, link}) conforme a extensão:
      .json -> lista de objetos;  .csv -> separado por ";" (abre direto no Excel em português);
      .txt  -> uma linha por canal, colunas separadas por TAB (cola certinho numa planilha)."""
    import csv
    caminho = Path(caminho)
    tipo = caminho.suffix.lower()
    titulos = {"canal": "Canal", "grupo": "Grupo", "situacao": "Situação", "no_ar": "No ar", "link": "Link"}

    def sim_nao(valor) -> str:
        return "" if valor is None else ("sim" if valor else "não")
    if tipo == ".json":
        caminho.write_text(json.dumps(linhas, ensure_ascii=False, indent=2), encoding="utf-8")
    elif tipo == ".csv":
        with caminho.open("w", newline="", encoding="utf-8-sig") as arquivo:   # -sig: o Excel lê os acentos
            escritor = csv.writer(arquivo, delimiter=";")
            escritor.writerow(titulos.values())
            for linha in linhas:
                escritor.writerow([sim_nao(linha[c]) if c == "no_ar" else linha[c] for c in titulos])
    elif tipo == ".txt":
        texto = ["\t".join(titulos.values())] + [
            "\t".join(sim_nao(linha[c]) if c == "no_ar" else str(linha[c]).replace("\t", " ") for c in titulos)
            for linha in linhas]
        caminho.write_text("\n".join(texto) + "\n", encoding="utf-8")
    else:
        raise ValueError(f"use .json, .csv ou .txt (não {tipo or 'sem extensão'})")
    return caminho


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
