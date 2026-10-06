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
    numero: str = ""       # tvg-chno: o número do canal no Jellyfin (vazio = o Jellyfin numera sozinho)
    idioma: str = ""       # tvg-language ("Português"); vazio = o programa deduz (idioma_do_canal)


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
                         atributos.get("tvg-logo", ""), atributos.get("tvg-id", ""),
                         atributos.get("tvg-chno", "") or atributos.get("channel-number", ""),
                         nome_do_idioma(re.split(r"[;,]", atributos.get("tvg-language", ""))[0]))
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


def _ids_e_numeros(canais: list[Canal]) -> list[tuple[str, str]]:
    """(tvg-id, número) de cada canal como vão no .m3u: o repetido fica vazio (o 1º continua ligado ao guia)."""
    ids_usados, numeros_usados, saida = set(), set(), []
    for c in canais:
        id_guia = c.id_guia if c.id_guia and c.id_guia.lower() not in ids_usados else ""
        numero = c.numero if c.numero and c.numero not in numeros_usados else ""
        ids_usados.add(id_guia.lower())
        numeros_usados.add(numero)
        saida.append((id_guia, numero))
    return saida


def gerar_m3u(canais: list[Canal], guia: str = "") -> str:
    """A lista .m3u para o Jellyfin. tvg-id e número NÃO se repetem: o mesmo tvg-id em dois canais (comum em
    listas da internet: a versão HD e a SD do mesmo canal) pode dar erro na atualização do guia, e com erro
    o Jellyfin não apaga os canais velhos. O repetido fica sem tvg-id (o 1º continua ligado ao guia)."""
    cabecalho = f'#EXTM3U url-tvg="{guia}"' if guia else "#EXTM3U"
    linhas = [cabecalho]
    for c, (id_guia, numero) in zip(canais, _ids_e_numeros(canais)):
        atributos = " ".join(f'{chave}="{valor}"' for chave, valor in
                             (("tvg-id", id_guia), ("tvg-chno", numero), ("tvg-name", c.nome),
                              ("tvg-logo", c.logo), ("tvg-language", c.idioma), ("group-title", c.grupo)) if valor)
        linhas += [f"#EXTINF:-1 {atributos},{c.nome}".replace("-1 ,", "-1,"), c.url]
    return "\n".join(linhas) + "\n"


# ----------------------------------------------------------------- idioma do canal
# O Jellyfin não separa canais por idioma (não existe essa categoria). O programa descobre o idioma de cada
# canal, mostra numa coluna (com filtro), põe no guia como gênero e numera em faixas por idioma (Português
# 1-99, English 101-199...): assim os canais aparecem separados em qualquer aplicativo.
IDIOMAS_TV = {"pt": "Português", "en": "English", "es": "Español", "fr": "Français", "it": "Italiano",
              "de": "Deutsch", "ja": "日本語", "ar": "العربية", "ru": "Русский", "zh": "中文", "hi": "हिन्दी",
              "ko": "한국어", "nl": "Nederlands", "tr": "Türkçe", "pl": "Polski"}
_APELIDOS_IDIOMA = {"por": "pt", "portuguese": "pt", "portugues": "pt", "eng": "en", "english": "en", "ingles": "en",
                    "spa": "es", "spanish": "es", "espanol": "es", "fra": "fr", "fre": "fr", "french": "fr",
                    "frances": "fr", "ita": "it", "italian": "it", "deu": "de", "ger": "de", "german": "de",
                    "alemao": "de", "jpn": "ja", "japanese": "ja", "ara": "ar", "arabic": "ar", "rus": "ru",
                    "russian": "ru", "zho": "zh", "chi": "zh", "chinese": "zh", "hin": "hi", "hindi": "hi",
                    "kor": "ko", "korean": "ko", "nld": "nl", "dut": "nl", "dutch": "nl", "tur": "tr", "turkish": "tr",
                    "pol": "pl", "polish": "pl"}
_PAIS_IDIOMA = {"br": "pt", "pt": "pt", "ao": "pt", "mz": "pt", "us": "en", "uk": "en", "gb": "en", "ca": "en",
                "au": "en", "ie": "en", "nz": "en", "es": "es", "mx": "es", "ar": "es", "co": "es", "cl": "es",
                "pe": "es", "ve": "es", "uy": "es", "py": "es", "bo": "es", "ec": "es", "cr": "es", "do": "es",
                "gt": "es", "hn": "es", "sv": "es", "ni": "es", "pa": "es", "cu": "es", "pr": "es", "fr": "fr",
                "it": "it", "de": "de", "at": "de", "jp": "ja", "ru": "ru", "cn": "zh", "tw": "zh", "in": "hi",
                "kr": "ko", "nl": "nl", "tr": "tr", "pl": "pl", "sa": "ar", "ae": "ar", "eg": "ar", "qa": "ar"}
_NOME_IDIOMA = ((re.compile(r"\b(brazil|brasil|portugal|portugues[ae]?)\b", re.I), "pt"),
                (re.compile(r"\b(latin america|latam|latino|mexico|méxico|argentina|españa|espana|colombia|"
                            r"chile|peru|perú|venezuela)\b", re.I), "es"),
                (re.compile(r"\b(usa|us|uk|english)\b", re.I), "en"))


def nome_do_idioma(texto: str) -> str:
    """'por', 'pt', 'Portuguese', 'Português' -> 'Português'; desconhecido -> o texto como veio."""
    import unicodedata
    simples = "".join(c for c in unicodedata.normalize("NFD", (texto or "").strip().lower())
                      if unicodedata.category(c) != "Mn")
    if not simples:
        return ""
    codigo = simples if simples in IDIOMAS_TV else _APELIDOS_IDIOMA.get(simples, "")
    return IDIOMAS_TV.get(codigo, texto.strip())


def idioma_do_canal(c: Canal) -> str:
    """O idioma do canal: o da lista (tvg-language); senão o país do tvg-id ('AMCBrasil.br@SD' -> Português);
    senão o nome ('A&E Latin America Brazil' -> Português); senão o domínio do link (.br, .pt). Vazio = não sei."""
    if c.idioma:
        return nome_do_idioma(c.idioma)
    if m := re.search(r"\.([a-z]{2})(?:@|$)", (c.id_guia or "").lower()):
        if codigo := _PAIS_IDIOMA.get(m.group(1)):
            return IDIOMAS_TV[codigo]
    for padrao, codigo in _NOME_IDIOMA:
        if padrao.search(c.nome or ""):
            return IDIOMAS_TV[codigo]
    from urllib.parse import urlparse
    dominio = (urlparse(c.url).hostname or "").lower()
    if m := re.search(r"\.(br|pt)$", dominio):
        return IDIOMAS_TV[_PAIS_IDIOMA[m.group(1)]]
    return ""


def numerar_por_idioma(canais: list[Canal]) -> list[Canal]:
    """Reordena por idioma (o com mais canais primeiro; "sem idioma" por último), grupo e nome, e numera em
    FAIXAS: cada idioma começa na centena seguinte (Português 1-57, English 101-140...). Devolve a lista nova."""
    from collections import Counter
    idiomas = [idioma_do_canal(c) for c in canais]
    contagem = Counter(i for i in idiomas if i)
    ordem = {idioma: n for n, (idioma, _) in enumerate(sorted(contagem.items(),                      # empate: Português antes
                                                              key=lambda iq: (-iq[1], iq[0] != "Português", iq[0])))}
    pares = sorted(zip(canais, idiomas), key=lambda ci: (ordem.get(ci[1], len(ordem)), (ci[0].grupo or "~").lower(),
                                                          ci[0].nome.lower()))
    numero, anterior, saida = 0, object(), []
    for c, idioma in pares:
        if idioma != anterior:                       # idioma novo: próxima centena
            numero = (numero // 100 + 1) * 100 if numero else 0
            anterior = idioma
        numero += 1
        c.numero = str(numero)
        saida.append(c)
    return saida


# ----------------------------------------------------------------- guia de categorias
# O Jellyfin LÊ o group-title da lista, mas não usa para nada: as categorias que os aplicativos mostram (Filmes,
# Esportes, Notícias, Infantil, Séries) vêm SÓ do guia de programação (XMLTV), pela categoria dos programas.
# Sem guia, todo canal fica "sem categoria" (só a lista numerada). Sem um guia de verdade, o programa gera um
# simples: um "programa" por dia em cada canal, com a categoria tirada do Grupo do canal.
ARQUIVO_GUIA_CATEGORIAS = "guia_categorias.xml"
CATEGORIAS_DO_GRUPO = (    # (categoria que o Jellyfin entende, palavras do grupo que levam a ela)
    ("movie", ("filme", "filmes", "movie", "movies", "cinema")),
    ("sports", ("esporte", "esportes", "sport", "sports", "futebol", "football", "soccer")),
    ("news", ("noticia", "noticias", "news", "jornalismo", "journalism", "documentario", "documentary")),
    ("kids", ("infantil", "kids", "children", "crianca", "criancas", "desenho", "desenhos", "cartoon",
              "cartoons", "animation", "animacao", "family", "familia")),
    ("series", ("serie", "series", "seriado", "seriados")))


def categoria_do_grupo(grupo: str) -> str | None:
    """'Sports' -> 'sports'; 'Filmes;Ação' -> 'movie'; 'Religious' -> None (o Jellyfin não tem essa)."""
    import unicodedata
    texto = "".join(c for c in unicodedata.normalize("NFD", (grupo or "").lower()) if unicodedata.category(c) != "Mn")
    palavras = set(re.findall(r"[a-z]+", texto))
    return next((cat for cat, chaves in CATEGORIAS_DO_GRUPO if palavras & set(chaves)), None)


def gerar_guia_categorias(canais: list[Canal], agora=None, dias: int = 30) -> str:
    """XMLTV com um "programa" por dia em cada canal (título = o canal, gênero = o Grupo e a categoria que o
    Jellyfin entende). Os canais ligam pelo tvg-id ou, sem ele, pelo nome (como o Jellyfin faz)."""
    from datetime import datetime, timedelta, timezone
    from xml.sax.saxutils import escape, quoteattr
    agora = agora or datetime.now(timezone.utc)
    inicio = agora.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    linhas = ['<?xml version="1.0" encoding="UTF-8"?>', '<tv generator-info-name="Maestro (categorias pelo Grupo)">']
    ids = [id_guia or f"maestro.{n}" for n, (id_guia, _) in enumerate(_ids_e_numeros(canais), 1)]
    for c, cid in zip(canais, ids):
        linhas.append(f"  <channel id={quoteattr(cid)}><display-name>{escape(c.nome)}</display-name></channel>")
    for c, cid in zip(canais, ids):
        categoria = categoria_do_grupo(c.grupo)
        idioma = idioma_do_canal(c)
        generos = [g for g in (categoria, *(p.strip() for p in re.split(r"[;,/|]", c.grupo or "")), idioma) if g]
        for dia in range(dias + 1):
            de, ate = inicio + timedelta(days=dia), inicio + timedelta(days=dia + 1)
            linhas.append(f'  <programme start="{de:%Y%m%d%H%M%S} +0000" stop="{ate:%Y%m%d%H%M%S} +0000" '
                          f'channel={quoteattr(cid)}><title>{escape(c.nome)}</title>'
                          + (f"<desc>{escape(' · '.join(t for t in (c.grupo, idioma) if t))}</desc>"
                             if c.grupo or idioma else "")
                          + "".join(f"<category>{escape(g)}</category>" for g in dict.fromkeys(generos))
                          + (f'<episode-num system="xmltv_ns">0.{dia}.</episode-num>' if categoria == "series" else "")
                          + "</programme>")
    linhas.append("</tv>")
    return "\n".join(linhas) + "\n"


def separar_guias(texto: str) -> list[str]:
    """O campo "Guia de programação" aceita VÁRIOS guias, separados por ; ou espaço/linha
    ('https://a/epg.xml; E:\\TV\\guia.xml')."""
    partes = re.split(r"\s*[;\n]\s*|\s+(?=(?:https?://|[a-zA-Z]:\\\\|\\\\\\\|/))", texto or "")
    return list(dict.fromkeys(p.strip() for p in partes if p and p.strip()))


def caminho_irmao(caminho: str, nome: str) -> str:
    """Outro arquivo na MESMA pasta, no jeito de escrever do caminho (Windows ou não): 'E:\\TV\\canais.m3u' ->
    'E:\\TV\\guia_categorias.xml'."""
    return re.sub(r"[^\\/]*$", lambda m: nome, caminho.strip(), count=1)


def carregar_canais(arquivo: str | Path) -> list[Canal]:
    campos = set(Canal.__dataclass_fields__)
    try:
        return [Canal(**{k: v for k, v in c.items() if k in campos})
                for c in json.loads(Path(arquivo).read_text(encoding="utf-8"))]
    except (OSError, ValueError, TypeError, AttributeError):
        return []


# ----------------------------------------------------------------- duplicados e histórico
_RE_ENFEITES = re.compile(r"\([^)]*\)|\[[^\]]*\]|\b(?:fhd|uhd|hd|sd|4k|h265|hevc)\b")


def nome_base(nome: str) -> str:
    """O nome sem enfeites, para achar o mesmo canal em links diferentes:
    'TV Cultura (720p) [Not 24/7]' e 'tv cultura HD' -> 'tv cultura'."""
    import unicodedata
    texto = "".join(c for c in unicodedata.normalize("NFD", nome.lower()) if unicodedata.category(c) != "Mn")
    texto = _RE_ENFEITES.sub(" ", texto)
    return " ".join(re.sub(r"[^\w&+]+", " ", texto).split())


def duplicados(canais: list[Canal], ok: dict[str, bool | None] | None = None) -> list[int]:
    """Índices das CÓPIAS a tirar: canais com o mesmo nome base. Fica um de cada (o primeiro que está
    no ar; sem conferência, o primeiro da lista)."""
    ok = ok or {}
    grupos: dict[str, list[int]] = {}
    for i, c in enumerate(canais):
        if base := nome_base(c.nome):
            grupos.setdefault(base, []).append(i)
    tirar = []
    for indices in grupos.values():
        if len(indices) > 1:
            fica = next((i for i in indices if ok.get(canais[i].url)), indices[0])
            tirar += [i for i in indices if i != fica]
    return sorted(tirar)


GUARDAR_CONFERENCIAS = 5


def carregar_historico(arquivo: str | Path) -> dict[str, list[bool]]:
    """{link: [resultado das últimas conferências, a mais nova no fim]} (True = no ar)."""
    try:
        dados = json.loads(Path(arquivo).read_text(encoding="utf-8"))
        return {str(url): [bool(v) for v in lista][-GUARDAR_CONFERENCIAS:] for url, lista in dados.items()}
    except (OSError, ValueError, TypeError, AttributeError):
        return {}


def salvar_historico(arquivo: str | Path, historico: dict[str, list[bool]], canais: list[Canal] | None = None) -> None:
    """Grava (e esquece os links que não estão mais na lista, se ela for passada)."""
    if canais is not None:
        existentes = {c.url for c in canais}
        historico = {url: v for url, v in historico.items() if url in existentes}
    Path(arquivo).parent.mkdir(parents=True, exist_ok=True)
    Path(arquivo).write_text(json.dumps(historico, ensure_ascii=False), encoding="utf-8")


def registrar_no_historico(historico: dict[str, list[bool]], situacoes) -> None:
    for canal, situacao in situacoes:
        historico[canal.url] = (historico.get(canal.url, []) + [bool(situacao.ok)])[-GUARDAR_CONFERENCIAS:]


def resumo_historico(resultados: list[bool]) -> str:
    """'✓✓✕✓✕  2 de 5 falharam' (a mais nova à direita); vazio = nunca conferido."""
    if not resultados:
        return ""
    falhas = resultados.count(False)
    marcas = "".join("✓" if r else "✕" for r in resultados)
    return f"{marcas}  {falhas} de {len(resultados)} falharam" if falhas else f"{marcas}  sempre no ar"


def sempre_falha(resultados: list[bool], minimo: int = 3) -> bool:
    """Falhou em TODAS as últimas conferências (pelo menos `minimo`): é seguro dizer que está morto.
    Um canal "Not 24/7" que funciona em alguns horários não entra aqui."""
    return len(resultados) >= minimo and not any(resultados)


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


TEMPO_CONECTAR, TEMPO_RESPOSTA = 4, 10    # segundos: conectar / esperar cada pedaço da resposta
PRAZO_POR_CANAL = 15                      # nenhum canal segura a fila mais que isso (somando tudo)
# Cabeçalhos de um navegador comum: alguns servidores de transmissão recusam pedidos "de programa"
CABECALHOS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/124.0 Safari/537.36", "Accept": "*/*", "Accept-Language": "pt-BR,pt;q=0.9"}


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
    """timeout: (conectar, esperar a resposta). Um canal que nem conecta em 4 s está fora do ar."""
    sessao = sessao or requests
    aviso = "; link temporário (token/expires): deve parar de funcionar" if _RE_TEMPORARIO.search(url) else ""
    try:
        with sessao.get(url, timeout=timeout, stream=True, headers=CABECALHOS) as r:
            if r.status_code in (401, 403):
                return Situacao(False, f"o canal pede login (HTTP {r.status_code})")
            if not r.ok:
                return Situacao(False, f"fora do ar (HTTP {r.status_code})")
            tipo = r.headers.get("Content-Type", "").lower()
            texto = ".m3u8" in url.lower() or "mpegurl" in tipo or tipo.startswith("text/") or not tipo
            inicio = _primeiros_bytes(r, 16 if texto else 1)
    except (requests.ConnectionError, requests.Timeout) as erro:
        # não conectou, ou conectou e ficou mudo: conta como falha do SERVIDOR (os outros canais dele
        # provavelmente estão iguais)
        nome = "demorou demais para responder" if isinstance(erro, requests.ReadTimeout) else "sem resposta"
        return Situacao(False, f"{nome} ({type(erro).__name__})", servidor_caiu=True)
    except requests.RequestException as erro:
        return Situacao(False, f"sem resposta ({type(erro).__name__})")
    # O que vale é o CONTEÚDO: muitos servidores mandam a playlist como "text/html" ou "text/plain" (o
    # navegador toca assim mesmo). O começo pode ter a marca BOM e espaços.
    if inicio.lstrip(b"\xef\xbb\xbf \t\r\n").startswith(b"#EXTM3U"):
        return Situacao(True, "no ar" + aviso)
    if ".m3u8" in url.lower() or "mpegurl" in tipo:
        return Situacao(False, "o endereço respondeu, mas não é uma transmissão (.m3u8 sem #EXTM3U)")
    if tipo.startswith("text/html"):
        return Situacao(False, "é uma página, não o sinal do canal")
    if tipo and not tipo.startswith(_TIPOS_FLUXO):
        return Situacao(False, f"não parece vídeo/áudio ({tipo})")
    return Situacao(True, "no ar" + aviso)


FALHAS_PARA_DESISTIR = 3      # 3 canais do mesmo servidor sem resposta (e nenhum que respondeu): desiste dele
POUCOS_CANAIS = 30            # conferindo até 30 (ex.: os selecionados), cada canal é tentado de verdade
POR_SERVIDOR = 6              # no máximo 6 consultas ao MESMO servidor ao mesmo tempo (não sobrecarrega nem é bloqueado)


def _servidores_que_existem(urls: list[str], parar=None, trabalhadores: int = 16) -> set[str]:
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
    achados = em_paralelo(nomes, existe, trabalhadores, parar=parar, prazo=5, ao_estourar=lambda _: False)
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


VELOCIDADES = {"Leve": 8, "Normal": 16, "Rápida": 32}     # consultas ao mesmo tempo
# Por que não sempre "Rápida": muitas conexões de uma vez (mais as consultas de endereço) podem lotar o
# roteador/Wi-Fi de casa; a internet do computador inteiro fica lenta e parece que "travou".


def conferir_canais(canais: list[Canal], trabalhadores: int = VELOCIDADES["Normal"], ao_progresso=None,
                    parar=None) -> list[tuple[Canal, Situacao]]:
    """Confere vários canais ao mesmo tempo. Mais rápido em listas grandes:
      - servidores que não existem (DNS) são descobertos de uma vez, antes de tudo;
      - os canais são intercalados por servidor (vários servidores trabalhando juntos);
      - no máximo POR_SERVIDOR consultas ao mesmo servidor ao mesmo tempo;
      - servidor que nunca respondeu e já falhou em 3 canais (não conectou OU ficou mudo): os outros
        canais dele saem "fora do ar" sem esperar (só em listas com mais de POUCOS_CANAIS: conferindo
        poucos, por exemplo os selecionados, cada um é tentado de verdade);
      - nenhum canal demora mais que PRAZO_POR_CANAL segundos.
    Com parar() verdadeiro, para NA HORA e devolve só os conferidos."""
    import threading
    from urllib.parse import urlparse
    local, trava = threading.local(), threading.Lock()
    falhas: dict[str, int] = {}
    responderam: set[str] = set()
    vagas: dict[str, threading.Semaphore] = {}
    # com proxy configurado quem procura o servidor é o proxy: aí não dá para julgar pelo DNS daqui
    existem = None if requests.utils.getproxies() else _servidores_que_existem([c.url for c in canais], parar,
                                                                                     trabalhadores)
    if parar and parar():
        return []

    pode_desistir = len(canais) > POUCOS_CANAIS

    def desistiu(servidor: str) -> Situacao | None:
        if pode_desistir and servidor not in responderam and falhas.get(servidor, 0) >= FALHAS_PARA_DESISTIR:
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
            # anota ANTES de liberar a vaga: quem estava esperando já vê a falha (senão entra mais um em vão)
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
    titulos = {"numero": "Nº", "canal": "Canal", "grupo": "Grupo", "idioma": "Idioma", "situacao": "Situação",
               "no_ar": "No ar",
               "historico": "Últimas", "link": "Link"}
    linhas = [{**dict.fromkeys(titulos, ""), **linha} for linha in linhas]

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

    def sintonizadores(self, tipo: str, endereco: str = "", nome: str = NOME_SINTONIZADOR) -> list[dict]:
        """Os sintonizadores que são nossos: mesmo endereço, ou o nosso nome com o mesmo tipo."""
        return [h for h in self.configuracao().get("TunerHosts") or []
                if (endereco and h.get("Url") == endereco) or (h.get("FriendlyName") == nome and h.get("Type") == tipo)]

    def outros_sintonizadores(self, endereco: str, nome: str = NOME_SINTONIZADOR) -> list[dict]:
        """Os sintonizadores do Jellyfin que NÃO são os desta lista (cadastrados à mão no Painel, por exemplo
        uma lista grande da internet). Os canais deles aparecem junto em TV ao vivo e entram no total."""
        nossos = {h.get("Id") for h in self.sintonizadores("m3u", endereco, nome)}
        nossos |= {h.get("Id") for h in self.sintonizadores("hdhomerun", "", f"{nome} antena")}
        return [h for h in self.configuracao().get("TunerHosts") or [] if h.get("Id") not in nossos]

    def remover_sintonizador(self, id_: str) -> None:
        """Tira o sintonizador do Jellyfin. Na próxima atualização do guia, os canais dele somem de TV ao vivo."""
        self._pedir("DELETE", "/LiveTv/TunerHosts", params={"id": id_})

    def cadastrar_sintonizador(self, tipo: str, endereco: str, nome: str = NOME_SINTONIZADOR) -> dict:
        """tipo 'm3u' (endereco = o .m3u, como o SERVIDOR enxerga) ou 'hdhomerun' (endereco = IP da antena).
        Se já existe um com o mesmo endereço, ou o nosso do mesmo tipo, ele é atualizado (não duplica)."""
        existente = next(iter(self.sintonizadores(tipo, endereco, nome)), None)
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

    def remover_guias_de_categorias(self, exceto: str = "") -> int:
        """Tira do Jellyfin os guias de categorias gerados pelo programa (outro caminho antigo, ou porque agora há
        um guia de verdade). Devolve quantos tirou."""
        tirados = 0
        for p in self.configuracao().get("ListingProviders") or []:
            caminho = str(p.get("Path") or "")
            if caminho.replace("\\", "/").rsplit("/", 1)[-1] == ARQUIVO_GUIA_CATEGORIAS and caminho != exceto and p.get("Id"):
                self._pedir("DELETE", "/LiveTv/ListingProviders", params={"id": p["Id"]})
                tirados += 1
        return tirados

    def _tarefa(self, id_: str) -> dict:
        return self._pedir("GET", f"/ScheduledTasks/{id_}") or {}

    def atualizar_guia(self) -> str:
        """Roda a tarefa 'Atualizar o guia' agora (senão o Jellyfin espera o horário dela). Devolve o id da
        tarefa ('' se não achou). É ELA que lê a lista de novo e tira os canais que saíram."""
        tarefas = self._pedir("GET", "/ScheduledTasks") or []
        tarefa = next((t for t in tarefas if t.get("Key") == "RefreshGuide"), None)
        if not tarefa:
            return ""
        # quando ela terminou da ÚLTIMA vez: só vale como "terminou" um fim DEPOIS deste pedido
        try:
            antes = (self._tarefa(tarefa["Id"]).get("LastExecutionResult") or {}).get("EndTimeUtc")
        except ErroJellyfin:
            antes = None
        self._fim_anterior = getattr(self, "_fim_anterior", {})
        self._fim_anterior[str(tarefa["Id"])] = antes
        self._pedir("POST", f"/ScheduledTasks/Running/{tarefa['Id']}")
        return str(tarefa["Id"])

    def esperar_tarefa(self, id_: str, limite: float = 180, parar=None, intervalo: float = 2) -> bool:
        """Espera a tarefa pedida em atualizar_guia() TERMINAR (até `limite` segundos). True = terminou.
        Antes bastava ela aparecer "parada" (Idle), e logo depois do pedido ela ainda nem tinha começado: o
        programa contava os canais ANTIGOS. Agora só vale um fim mais novo que o de antes do pedido (ou tê-la
        visto rodando). Se ela terminou com erro, o motivo fica em self.erro_da_tarefa."""
        import time
        self.erro_da_tarefa = ""
        antes = getattr(self, "_fim_anterior", {}).get(str(id_))
        viu_rodando = False
        fim = time.monotonic() + limite
        time.sleep(min(intervalo, 1))
        while time.monotonic() < fim and not (parar and parar()):
            try:
                info = self._tarefa(id_)
            except ErroJellyfin:
                return False
            estado = info.get("State", "Idle")
            ultimo = info.get("LastExecutionResult") or {}
            viu_rodando = viu_rodando or estado != "Idle"
            if estado == "Idle" and ("LastExecutionResult" not in info          # Jellyfin antigo: sem o histórico
                                     or viu_rodando or (ultimo.get("EndTimeUtc") and ultimo.get("EndTimeUtc") != antes)):
                if ultimo.get("Status") in ("Failed", "Aborted"):
                    self.erro_da_tarefa = ultimo.get("ErrorMessage") or ultimo.get("Status")
                return True
            time.sleep(intervalo)
        return False

    def nomes_dos_canais(self) -> set[str] | None:
        """Os nomes dos canais que o Jellyfin tem em TV ao vivo (None se não deu para saber)."""
        try:
            itens = (self._pedir("GET", "/LiveTv/Channels", params={"EnableImages": "false"}) or {}).get("Items")
            return {str(i.get("Name", "")) for i in itens} if isinstance(itens, list) else None
        except ErroJellyfin:
            return None

    def diagnostico(self) -> dict:
        """Tudo o que ajuda a descobrir DE ONDE vêm canais que não saem: os serviços de TV ao vivo (o do próprio
        Jellyfin e os de plugins), os sintonizadores, os guias, uma amostra dos canais e a última atualização."""
        d: dict = {}
        for chave, consulta in (("info", lambda: self._pedir("GET", "/LiveTv/Info") or {}),
                                ("config", self.configuracao),
                                ("canais", lambda: self._pedir("GET", "/LiveTv/Channels",
                                                               params={"Limit": 15, "EnableImages": "false"}) or {}),
                                ("tarefas", lambda: self._pedir("GET", "/ScheduledTasks") or []),
                                ("plugins", self.plugins)):
            try:
                d[chave] = consulta()
            except ErroJellyfin as erro:
                d[chave] = {"erro": str(erro)}
        return d

    def plugins(self) -> list[dict]:
        return self._pedir("GET", "/Plugins") or []

    def estado(self) -> dict:
        """O mínimo para o painel de saúde (3 pedidos pequenos): serviços, plugins e o total de canais."""
        d: dict = {}
        for chave, consulta in (("info", lambda: self._pedir("GET", "/LiveTv/Info") or {}),
                                ("canais", lambda: self._pedir("GET", "/LiveTv/Channels", params={"Limit": 0}) or {}),
                                ("plugins", self.plugins)):
            try:
                d[chave] = consulta()
            except ErroJellyfin as erro:
                d[chave] = {"erro": str(erro)}
        return d

    def desativar_plugin(self, plugin: dict) -> None:
        """Desativa (não apaga) o plugin. Vale depois de reiniciar o Jellyfin; volta em Painel > Plugins > Ativar."""
        self._pedir("POST", f"/Plugins/{plugin.get('Id')}/{plugin.get('Version')}/Disable")

    def reiniciar(self) -> None:
        self._pedir("POST", "/System/Restart")

    def esperar_voltar(self, limite: float = 240, parar=None, dormir=None, agora=None) -> bool:
        """Depois de reiniciar: espera o Jellyfin cair (até 30 s) e voltar a responder (até `limite` s)."""
        import time
        dormir, agora = dormir or time.sleep, agora or time.monotonic
        inicio = agora()

        def responde() -> bool:
            try:
                r = self.sessao.get(self.base + "/System/Info/Public", timeout=5)
                return r.ok and bool(r.content)
            except requests.RequestException:
                return False
        while agora() - inicio < 30 and responde():          # ainda não caiu
            if parar and parar():
                return False
            dormir(2)
        while agora() - inicio < limite:
            if parar and parar():
                return False
            if responde():
                return True
            dormir(3)
        return False

    def quantos_canais(self) -> int | None:
        """Quantos canais o Jellyfin tem agora em TV ao vivo (None se não deu para saber)."""
        try:
            return int((self._pedir("GET", "/LiveTv/Channels", params={"Limit": 0}) or {}).get("TotalRecordCount"))
        except (ErroJellyfin, TypeError, ValueError):
            return None


def publicar(canais: list[Canal], pasta: str | Path, caminho_no_servidor: str = "", guia: str = "",
             cliente: ClienteTV | None = None, antena: str = "", parar=None, esperar_guia: float = 180) -> list[str]:
    """Grava '<pasta>/canais.m3u' e (com o cliente) cadastra no Jellyfin: a lista, o guia e a antena.
    caminho_no_servidor: como o SERVIDOR do Jellyfin enxerga o arquivo, se for outro computador
    (ex.: 'E:\\TV\\canais.m3u' lá, '\\\\Servidor\\e\\TV\\canais.m3u' aqui). Vazio = o mesmo caminho.

    Canais REMOVIDOS saem do Jellyfin de verdade, guardando os favoritos sempre que der:
      1. o arquivo é SEMPRE regravado (lista vazia = arquivo sem canais);
      2. o sintonizador M3U é atualizado no lugar e o guia é atualizado (o Jellyfin relê a lista);
      3. o programa confere se os removidos sumiram. Só se continuarem lá (ou se não der para conferir)
         o sintonizador é recriado, e aí os favoritos desses canais precisam ser marcados de novo;
      4. lista vazia: o nosso sintonizador M3U é retirado do Jellyfin."""
    feito = []
    arquivo = Path(pasta) / "canais.m3u"
    try:
        antigos = ler_m3u(arquivo.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        antigos = []
    urls_novas, urls_antigas = {c.url for c in canais}, {c.url for c in antigos}
    removidos = [c for c in antigos if c.url not in urls_novas]
    entraram = len(urls_novas - urls_antigas)
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    arquivo.write_text(gerar_m3u(canais, ",".join(separar_guias(guia))), encoding="utf-8")
    feito.append(f"lista salva: {arquivo} ({len(canais)} canal(is))"
                 + (f"; {len(removidos)} canal(is) saíram da lista" if removidos else ""))
    endereco = caminho_no_servidor.strip() or str(arquivo)
    guia_categorias = ""
    if canais:                                       # o de categorias (Filmes, Esportes...) pelo Grupo
        (Path(pasta) / ARQUIVO_GUIA_CATEGORIAS).write_text(gerar_guia_categorias(canais), encoding="utf-8")
        guia_categorias = caminho_irmao(endereco, ARQUIVO_GUIA_CATEGORIAS)
        com_categoria = sum(1 for c in canais if categoria_do_grupo(c.grupo))
        feito.append(f"guia de categorias salvo ({com_categoria} de {len(canais)} canal(is) com Filmes/Esportes/"
                     "Notícias/Infantil/Séries pelo Grupo)")
    if cliente is None:
        return feito
    nossos = cliente.sintonizadores("m3u", endereco)
    total_antes = cliente.quantos_canais() if removidos and nossos and canais else None
    if not canais:
        for host in nossos:
            cliente.remover_sintonizador(host.get("Id", ""))
        if nossos:
            feito.append("Jellyfin: lista vazia -> sintonizador M3U retirado (os canais saem de TV ao vivo)")
    else:
        cadastrado = cliente.cadastrar_sintonizador("m3u", endereco)
        feito.append(f"Jellyfin: sintonizador M3U -> {endereco}")
        # versões antigas/outra pasta: outro "videoscraper" apontando para OUTRO arquivo (com a lista velha)
        antigos = [h for h in cliente.sintonizadores("m3u", endereco)
                   if h.get("Url") != endereco and h.get("Id") != (cadastrado or {}).get("Id")]
        for host in antigos:
            cliente.remover_sintonizador(host.get("Id", ""))
        if antigos:
            feito.append(f"Jellyfin: {len(antigos)} lista(s) antiga(s) do programa retirada(s) (" +
                         "; ".join(str(h.get("Url", "")) for h in antigos[:3]) + ")")
    if antena.strip():
        cliente.cadastrar_sintonizador("hdhomerun", antena.strip(), f"{NOME_SINTONIZADOR} antena")
        feito.append(f"Jellyfin: sintonizador de antena HDHomeRun -> {antena.strip()}")
    for endereco_guia in separar_guias(guia):
        cliente.cadastrar_guia(endereco_guia)
        feito.append(f"Jellyfin: guia de programação (XMLTV) -> {endereco_guia}")
    try:                                             # o guia de categorias é um extra: falhar não derruba o envio
        # Para cada canal o Jellyfin usa o PRIMEIRO guia que tem programação dele: o de categorias vai sempre
        # por ÚLTIMO (sai e entra de novo), e só cobre os canais que os guias de verdade não têm.
        if cliente.remover_guias_de_categorias() and not guia_categorias:
            feito.append("Jellyfin: guia de categorias retirado")
        if guia_categorias:
            cliente.cadastrar_guia(guia_categorias)
            feito.append(f"Jellyfin: guia de categorias -> {guia_categorias}" + (
                " (por último: os guias de verdade valem primeiro)" if guia.strip() else ""))
    except ErroJellyfin as erro:
        feito.append(f"Jellyfin: o guia de categorias não foi cadastrado ({erro})")

    def atualizar() -> bool:
        tarefa = cliente.atualizar_guia()
        return bool(tarefa and esperar_guia and cliente.esperar_tarefa(tarefa, esperar_guia, parar))

    terminou = atualizar()
    if canais and removidos and nossos:
        if terminou and _removidos_sairam(cliente, removidos, canais, total_antes, entraram):
            feito.append(f"Jellyfin: os {len(removidos)} canal(is) removidos saíram (os favoritos foram mantidos)")
        elif not (parar and parar()):
            for host in cliente.sintonizadores("m3u", endereco):
                cliente.remover_sintonizador(host.get("Id", ""))
            cliente.cadastrar_sintonizador("m3u", endereco)
            feito.append(f"Jellyfin: os removidos continuavam lá -> sintonizador M3U recriado para tirar os "
                         f"{len(removidos)} canal(is) (os favoritos destes canais precisam ser marcados de novo)")
            terminou = atualizar()
    if terminou:
        total = cliente.quantos_canais()
        erro = getattr(cliente, "erro_da_tarefa", "")
        feito.append("Jellyfin: guia atualizado" + (f" -> agora TV ao vivo tem {total} canal(is)"
                                                    if total is not None else "")
                     + (f" (a tarefa terminou com erro: {erro})" if erro else ""))
    elif cliente is not None:
        feito.append("Jellyfin: atualizando o guia (os canais mudam em TV ao vivo em alguns minutos; "
                     "acompanhe em Painel > Tarefas agendadas > Atualizar o guia)")
    return feito


def descrever_sintonizador(host: dict) -> str:
    """'M3U "Minha lista": https://iptv-org.github.io/iptv/index.m3u'."""
    nome = f' "{host["FriendlyName"]}"' if host.get("FriendlyName") else ""
    return f'{str(host.get("Type", "?")).upper()}{nome}: {host.get("Url", "")}'


def _removidos_sairam(cliente: ClienteTV, removidos: list[Canal], canais: list[Canal], total_antes: int | None,
                      entraram: int) -> bool:
    """Os canais removidos sumiram do Jellyfin? Pelo nome, quando o nome saiu de vez da lista; senão (ex.: tirou
    uma cópia repetida, o nome continua) pela conta: o total tem que ter caído."""
    nomes_sairam = {c.nome for c in removidos} - {c.nome for c in canais}
    if nomes_sairam:
        nomes = cliente.nomes_dos_canais()
        return nomes is not None and not (nomes_sairam & nomes)
    total = cliente.quantos_canais()
    return total is not None and total_antes is not None and total <= total_antes - len(removidos) + entraram


def canais_a_mais(total: int | None, canais: list[Canal], antena: str = "") -> bool:
    """O Jellyfin ficou com bem mais canais do que a lista enviada? (Com antena não dá para saber quantos são.)"""
    return total is not None and not antena.strip() and total > len(canais) + max(10, len(canais) // 10)


def limpar_e_reenviar(cliente: ClienteTV, endereco: str, parar=None, esperar: float = 300) -> list[str]:
    """Faxina da TV ao vivo: tira TODOS os sintonizadores M3U do programa, atualiza o guia (o Jellyfin apaga os
    canais deles), cadastra de novo só a lista atual e atualiza o guia outra vez. Os favoritos se perdem."""
    feito = []
    for host in cliente.sintonizadores("m3u", endereco):
        cliente.remover_sintonizador(host.get("Id", ""))
    if (tarefa := cliente.atualizar_guia()) and cliente.esperar_tarefa(tarefa, esperar, parar):
        feito.append(f"Sem a lista: o Jellyfin ficou com {cliente.quantos_canais()} canal(is) (de outras fontes).")
    if parar and parar():
        return feito + ["Parado: cadastre de novo com \"Salvar e enviar\"."]
    cliente.cadastrar_sintonizador("m3u", endereco)
    if (tarefa := cliente.atualizar_guia()) and cliente.esperar_tarefa(tarefa, esperar, parar):
        feito.append(f"Com a lista de novo: agora TV ao vivo tem {cliente.quantos_canais()} canal(is).")
    else:
        feito.append("O Jellyfin ainda está atualizando o guia: confira em alguns minutos.")
    return feito


SERVICO_DO_JELLYFIN = "Emby"        # o serviço de TV do próprio Jellyfin (onde ficam os sintonizadores M3U)
APELIDOS_PLUGIN = {"tvhclient": ("tvheadend", "tvhclient"), "nextpvr": ("nextpvr",)}


def _simples(texto) -> str:
    return re.sub(r"[^a-z0-9]", "", str(texto or "").lower())


def plugins_de_tv(d: dict) -> tuple[list[dict], list[str]]:
    """Os serviços de TV ao vivo que vêm de PLUGINS (Next Pvr, TVHclient...) e o plugin de cada um.
    Se um deles der erro ao atualizar o guia (ex.: instalado mas sem servidor), o Jellyfin pula a limpeza e os
    canais velhos nunca saem. Devolve (plugins ativos a desativar, serviços cujo plugin não achei)."""
    servicos = [str(s.get("Name") or "") for s in (d.get("info") or {}).get("Services") or []
                if s.get("Name") and s.get("Name") != SERVICO_DO_JELLYFIN]
    plugins = d.get("plugins") if isinstance(d.get("plugins"), list) else []
    achados, sem_plugin = [], []
    for servico in servicos:
        nome = _simples(servico)
        chaves = next((apelidos for chave, apelidos in APELIDOS_PLUGIN.items() if chave in nome), (nome,))
        plugin = next((p for p in plugins if any(c and (c in _simples(p.get("Name")) or _simples(p.get("Name")) in c)
                                                 for c in chaves) and _simples(p.get("Name"))), None)
        if plugin is None:
            sem_plugin.append(servico)
        elif plugin.get("Status") not in ("Disabled", "NotSupported") and plugin not in achados:
            achados.append(plugin)
    return achados, sem_plugin


def desativar_plugins_e_limpar(cliente: ClienteTV, plugins: list[dict], parar=None, esperar: float = 300,
                               esperar_reinicio: float = 240) -> tuple[list[str], int | None]:
    """Desativa os plugins de TV, reinicia o Jellyfin, atualiza o guia e conta os canais. (o que foi feito, total)"""
    feito, antes = [], cliente.quantos_canais()
    for plugin in plugins:
        cliente.desativar_plugin(plugin)
        feito.append(f"Plugin desativado: {plugin.get('Name')} {plugin.get('Version')}")
    cliente.reiniciar()
    if not cliente.esperar_voltar(esperar_reinicio, parar):
        feito.append("O Jellyfin não voltou sozinho depois de reiniciar: abra-o de novo e, na janela TV ao vivo, "
                     "clique em \"Salvar e enviar ao Jellyfin\".")
        return feito, None
    feito.append("Jellyfin reiniciado.")
    if (tarefa := cliente.atualizar_guia()) and cliente.esperar_tarefa(tarefa, esperar, parar):
        total = cliente.quantos_canais()
        feito.append(f"Guia atualizado: TV ao vivo tinha {antes} canal(is), agora tem {total}."
                     + (f" Erro na atualização: {cliente.erro_da_tarefa}" if cliente.erro_da_tarefa else ""))
        return feito, total
    feito.append("O Jellyfin ainda está atualizando o guia: confira em alguns minutos.")
    return feito, None


def resumo_tv(d: dict, na_lista: int) -> tuple[bool | None, str]:
    """(tudo certo?, texto curto) a partir do diagnostico()/estado(). None = não deu para saber.
    Certo = sem plugin de TV ativo além do Jellyfin e o total de canais perto do da lista."""
    canais = d.get("canais") or {}
    if "erro" in canais or canais.get("TotalRecordCount") is None:
        return None, "não deu para ler os canais do Jellyfin"
    total = int(canais["TotalRecordCount"])
    plugins, sem_plugin = plugins_de_tv(d)
    if plugins or sem_plugin:
        nomes = [str(p.get("Name")) for p in plugins] + sem_plugin
        return False, f"plugin de TV ativo ({', '.join(nomes)}): pode impedir a limpeza"
    if na_lista and total > na_lista + max(10, na_lista // 10):
        return False, f"{total} canais no Jellyfin, a lista tem {na_lista}"
    return True, f"{total} canais" + (" (os da sua lista)" if na_lista else "")


def texto_diagnostico(d: dict, nomes_da_lista: set[str] = frozenset(), na_lista: int | None = None) -> str:
    """O diagnóstico em texto (para mostrar e para a pessoa copiar e mandar). Começa pelo resumo:
    "✓ Tudo certo" ou "⚠ ..." (na_lista: quantos canais a lista tem; padrão = quantos nomes)."""
    ok, resumo = resumo_tv(d, len(nomes_da_lista) if na_lista is None else na_lista)
    linhas = ["✓ Tudo certo: " + resumo if ok else f"⚠ Atenção: {resumo}" if ok is False else f"? {resumo}"]
    info, cfg, canais = d.get("info") or {}, d.get("config") or {}, d.get("canais") or {}
    servicos = info.get("Services") or []
    linhas.append(f"Serviços de TV ao vivo: {len(servicos)}")
    for s in servicos:
        linhas.append(f"  • {s.get('Name')}: {s.get('Status')}" + (f" ({s.get('StatusMessage')})" if s.get("StatusMessage")
                                                                   else ""))
    hosts = cfg.get("TunerHosts") or []
    linhas.append(f"Sintonizadores: {len(hosts)}")
    linhas += [f"  • {descrever_sintonizador(h)}" for h in hosts]
    guias = cfg.get("ListingProviders") or []
    linhas.append(f"Guias (XMLTV/Schedules Direct): {len(guias)}")
    linhas += [f"  • {g.get('Type')}: {g.get('Path') or g.get('ListingsId') or ''}" for g in guias]
    if "erro" in canais:
        linhas.append(f"Canais: não deu para ler ({canais['erro']})")
    else:
        itens = canais.get("Items") or []
        da_lista = sum(1 for c in itens if c.get("Name") in nomes_da_lista)
        linhas.append(f"Canais no Jellyfin: {canais.get('TotalRecordCount')} (amostra de {len(itens)}: {da_lista} são "
                      "da sua lista)")
        linhas += [f"  • {c.get('Name')}" + (f"  [serviço: {c['ServiceName']}]" if c.get("ServiceName") else "")
                   for c in itens[:10]]
    tarefa = next((t for t in (d.get("tarefas") if isinstance(d.get("tarefas"), list) else [])
                   if t.get("Key") == "RefreshGuide"), None)
    if tarefa:
        ultimo = tarefa.get("LastExecutionResult") or {}
        linhas.append(f"Última \"Atualizar o guia\": {ultimo.get('Status', '?')} em {ultimo.get('EndTimeUtc', '?')}"
                      + (f" — {ultimo.get('ErrorMessage')}" if ultimo.get("ErrorMessage") else ""))
    plugins, sem_plugin = plugins_de_tv(d)
    if plugins or sem_plugin:
        nomes = [f"{p.get('Name')} {p.get('Version')}" for p in plugins] + sem_plugin
        linhas.append(f"Plugins de TV ao vivo além do Jellyfin: {', '.join(nomes)}. Se um deles não estiver "
                      "configurado, a atualização do guia falha nele e o Jellyfin NÃO apaga os canais velhos.")
    return "\n".join(linhas)
