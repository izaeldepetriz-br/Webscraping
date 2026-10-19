"""Procurar na comunidade: os PATCHES de tradução (e dublagem) feitos por fãs para o jogo da sua ISO, numa lista
dentro do Maestro (a janela "🔎 Procurar na comunidade" da aba 🎮 Jogos).

    PO.B.R.E (romhackers.org)   o banco de dados público do portal (github.com/romhackersbr/romhackersbr-db): cada
                                tradução com o grupo, a versão, o formato, o que traz e para qual versão do jogo
                                (o código SLUS/SLES, a região, às vezes a impressão CRC32). Baixado uma vez por
                                semana (~2 MB) e procurado aqui no PC
    Fórum romhacking.net.br     a busca do fórum (os tópicos de lançamento: "[PS2] Jogo - PT-BR")
    Romhacking.net e itch.io    não deixam programas procurar (o Romhacking.net bloqueia; o robots.txt do itch.io
                                proíbe a busca): o Maestro abre a busca no navegador, para você

Regras: só aparecem PATCHES. A tradução distribuída como "ISO traduzida" (o jogo inteiro) fica escondida, e o
Maestro diz quantas escondeu. O download é feito por você, na página do grupo (os créditos e as regras do site são
respeitados); depois, "Já baixei: usar o arquivo" confere a impressão digital e aplica.
"""

from __future__ import annotations

import html
import io
import json
import re
import time
import unicodedata
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote_plus

from .dublagem import _baixar
from .patch_jogo import ErroPatch, InfoISO, normalizar_id

URL_BANCO_POBRE = "https://codeload.github.com/romhackersbr/romhackersbr-db/zip/refs/heads/main"
PAGINA_POBRE = "https://romhackers.org/traducoes/{plataforma}/{sistema}/{slug}/"
URL_FORUM = ("https://www.romhacking.net.br/index.php?action=search2;search={termos};searchtype=1;subject_only=1;"
             "sort=relevance|desc")
URL_RHN = "https://www.romhacking.net/?page=translations&title={termos}&perpage=50&searchtype=1"
URL_ITCH = "https://itch.io/search?q={termos}"
VALIDADE_DIAS = 7
SISTEMAS_POBRE = {"PS2": "playstation-2", "PS1": "playstation"}
ONDES = ("PO.B.R.E (romhackers.org)", "Fórum romhacking.net.br", "Romhacking.net (no navegador)",
         "itch.io (no navegador)")
QUER = ("Textos e/ou dublagem", "Só dublagem", "Só textos")
SO_O_JOGO = ("iso traduzida", "jogo completo", "iso completa")
_REGIOES = (("EUA", r"americana|\(usa|ntsc[- ]?u|\bslus\b|\bscus\b|\bus\b"),
            ("Europa", r"europ[eé]ia|\(europe|\bpal\b|\bsles\b|\bsces\b"),
            ("Japão", r"japonesa|\(japan|ntsc[- ]?j|\bslpm\b|\bslps\b|\bscps\b"))
_ID = re.compile(r"\b(S[CL][A-Z]{2}[-_ ]?\d{3}\.?\d{2})\b", re.I)
_CRC = re.compile(r"CRC[-\s]?(?:32)?\s*[:=]?\s*(?:0x)?([0-9a-f]{8})\b", re.I)
_TAMANHO = re.compile(r"(\d{1,3}(?:[.,]\d{3}){2,})\s*bytes", re.I)


class ErroBusca(ErroPatch):
    pass


@dataclass
class Achado:
    onde: str                         # "PO.B.R.E", "romhacking.net.br"
    titulo: str                       # "God of War II (Traduzido e Dublado)"
    grupo: str = ""
    versao: str = ""
    traz: list = field(default_factory=list)     # ["textos", "vozes dubladas"]
    feito_para: str = ""              # "SLUS-21374 (EUA)" / "EUA" / ""
    ids: set = field(default_factory=set)
    regiao: str = ""
    crc32: str = ""
    tamanho: int = 0
    formato: str = ""                 # "xdelta3", "PPF 3.0"...
    pagina: str = ""                  # onde baixar (a página do grupo ou do portal)
    site_do_grupo: str = ""
    descricao: str = ""
    encaixa: str = ""                 # "✓ encaixa", "⚠ outra região: não encaixa", "? confira o leia-me"
    nota: int = 0                     # o quanto o nome bate com o jogo (para ordenar)

    @property
    def patch(self) -> str:
        return " · ".join(p for p in (self.titulo, self.grupo, f"v{self.versao}" if self.versao else "") if p)

    def ok(self) -> bool:
        return self.encaixa.startswith("✓")


@dataclass
class Resultado:
    achados: list = field(default_factory=list)
    escondidos: int = 0               # traduções que distribuem a ISO inteira (não aparecem)
    avisos: list = field(default_factory=list)   # "o fórum não respondeu"...
    no_navegador: dict = field(default_factory=dict)   # {onde: endereço da busca}


# ----------------------------------------------------------------- comparar nomes
def _normal(texto: str) -> str:
    sem = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    sem = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", sem)            # (USA), [T-BR], (Traduzido e Dublado)
    sem = re.sub(r"\b(the|of|a|o|de|do|da)\b", " ", sem)
    sem = sem.replace("ii", " 2 ").replace(" iii ", " 3 ")
    return " ".join(re.findall(r"[a-z0-9]+", sem))


def parecido(a: str, b: str) -> int:
    """De 0 a 100: o quanto o nome do jogo `a` bate com `b` (as palavras de `a` que aparecem em `b`)."""
    pa, pb = set(_normal(a).split()), set(_normal(b).split())
    if not pa or not pb:
        return 0
    comuns = pa & pb
    numeros_a, numeros_b = {p for p in pa if p.isdigit()}, {p for p in pb if p.isdigit()}
    if numeros_a != numeros_b and (numeros_a or numeros_b):    # "God of War" não é "God of War 2"
        return min(40, round(100 * len(comuns) / len(pa)))
    return round(100 * len(comuns) / max(len(pa), len(pb) * 0.6))


def nome_do_jogo(info: InfoISO | None, nome_arquivo: str = "", redump: str = "") -> str:
    """O nome para procurar: o do Redump (o mais certo), o do arquivo da ISO sem o código, ou o volume."""
    if redump:
        return re.sub(r"\s*\([^)]*\)", "", redump).strip()
    nome = re.sub(r"^S[CL][A-Z]{2}[_-]?\d{3}\.?\d{2}\.?", "", nome_arquivo or "", flags=re.I)
    nome = re.sub(r"\b(PT-?BR|USA|NTSC|PAL|EUROPE|\[.*?\]|\(.*?\))", " ", nome, flags=re.I)
    nome = re.sub(r"[_.]+", " ", nome).strip(" -")
    return nome or (info.volume.replace("_", " ").title() if info else "")


def _o_que_traz(texto: str) -> list[str]:
    t = texto.lower()
    traz = []
    if re.search(r"texto|di[áa]logo|legenda|menu|tradu", t):
        traz.append("textos" + (" + menus" if "menu" in t else ""))
    if re.search(r"dublad|dublag|falados.{0,40}dublad|vozes", t):
        traz.append("dublagem")
    if re.search(r"v[íi]deos? (?:foram )?legendad|v[íi]deos - 100", t):
        traz.append("vídeos legendados")
    if re.search(r"gr[áa]fico.{0,30}(?:editad|traduzid)|gr[áa]ficos - 100", t):
        traz.append("gráficos")
    return traz or ["textos"]


def _regiao(texto: str) -> str:
    return next((nome for nome, padrao in _REGIOES if re.search(padrao, texto, re.I)), "")


def _encaixa(a: Achado, info: InfoISO | None, crc32: str = "") -> str:
    if info is None:
        return "? escolha a ISO para conferir"
    if a.crc32 and crc32:
        return "✓ encaixa: a impressão CRC32 é a da sua ISO" if a.crc32 == crc32.upper() else \
            "⚠ impressão diferente: é outra versão (não encaixa)"
    if a.tamanho and info.tamanho and a.tamanho != info.tamanho:
        return "⚠ tamanho diferente: é outra versão (não encaixa)"
    if a.ids and info.id_jogo:
        return "✓ encaixa: o mesmo código do disco" if info.id_jogo in a.ids else \
            f"⚠ é para {', '.join(sorted(a.ids))}: outra versão (não encaixa)"
    if a.regiao and info.regiao:
        return "✓ mesma região (confira a impressão no leia-me)" if a.regiao == info.regiao else \
            f"⚠ outra região ({a.regiao}): não encaixa"
    return "? confira o leia-me (a página não diz a versão)"


# ----------------------------------------------------------------- PO.B.R.E (o banco de dados público)
def _frente(texto: str) -> tuple[dict, str]:
    """(campos do cabeçalho "---", texto) de uma tradução do banco do PO.B.R.E."""
    partes = texto.split("---", 2)
    if len(partes) < 3:
        return {}, texto
    campos = {}
    for linha in partes[1].splitlines():
        if ":" in linha:
            chave, valor = linha.split(":", 1)
            valor = valor.strip()
            if valor.startswith('"') and valor.endswith('"'):
                valor = valor[1:-1]
            campos[chave.strip()] = "" if valor in ("undefined", "???") else valor.strip()
    return campos, partes[2].strip()


def banco_pobre(pasta: str | Path, baixar=_baixar, agora=time.time) -> dict:
    """{"PS2": [campos + "texto" + "slug" + "plataforma"], "PS1": [...]}: baixado uma vez por semana."""
    pasta = Path(pasta)
    arquivo = pasta / "pobre_traducoes.json"
    if arquivo.is_file() and agora() - arquivo.stat().st_mtime < VALIDADE_DIAS * 86400:
        try:
            return json.loads(arquivo.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    pasta.mkdir(parents=True, exist_ok=True)
    pacote = pasta / "pobre_traducoes.zip"
    try:
        baixar(URL_BANCO_POBRE, pacote, None)
        banco: dict = {s: [] for s in SISTEMAS_POBRE}
        pastas = {v: k for k, v in SISTEMAS_POBRE.items()}
        with zipfile.ZipFile(pacote) as z:
            for nome in z.namelist():
                partes = nome.split("/")
                if len(partes) == 5 and partes[1] == "_traducoes" and partes[3] in pastas and nome.endswith(".md"):
                    campos, texto = _frente(z.read(nome).decode("utf-8", "replace"))
                    banco[pastas[partes[3]]].append({**campos, "texto": texto, "slug": partes[4][:-3].rstrip("."),
                                                     "plataforma": partes[2], "sistema_pasta": partes[3]})
    except (zipfile.BadZipFile, OSError, ErroPatch) as erro:
        if arquivo.is_file():                                  # sem internet: fica a lista da semana passada
            return json.loads(arquivo.read_text(encoding="utf-8"))
        raise ErroBusca(f"não deu para baixar a lista do PO.B.R.E ({erro})") from erro
    finally:
        pacote.unlink(missing_ok=True)
    arquivo.write_text(json.dumps(banco, ensure_ascii=False), encoding="utf-8")
    return banco


def _achado_pobre(item: dict) -> Achado:
    texto = item.get("texto", "")
    tudo = " ".join([item.get("title", ""), item.get("patch_progress", ""), texto])
    a = Achado("PO.B.R.E", item.get("title", "").strip() or item.get("game_title", ""),
               grupo=item.get("patch_group", "") or item.get("patch_author", ""), versao=item.get("patch_version", ""),
               traz=_o_que_traz(tudo), formato=item.get("patch_type", ""),
               pagina=PAGINA_POBRE.format(plataforma=item.get("plataforma", "console"),
                                          sistema=item.get("sistema_pasta", ""), slug=item.get("slug", "")),
               site_do_grupo=("https:" + item["patch_site"]) if item.get("patch_site", "").startswith("//")
               else item.get("patch_site", ""), descricao=texto)
    a.ids = {normalizar_id(i) for i in _ID.findall(tudo + " " + item.get("patch_file", ""))}
    a.regiao = _regiao(tudo + " " + item.get("patch_file", ""))
    crc = _CRC.search(texto)
    a.crc32 = crc.group(1).upper() if crc else ""
    tamanho = _TAMANHO.search(texto)
    a.tamanho = int(re.sub(r"\D", "", tamanho.group(1))) if tamanho else 0
    a.feito_para = " ".join(p for p in (", ".join(sorted(a.ids)), f"({a.regiao})" if a.regiao else "") if p) or "—"
    return a


# ----------------------------------------------------------------- o fórum (busca do SMF)
_TOPICO = re.compile(r'<h5><a href="[^"]*board=[^"]*">([^<]*)</a>\s*/\s*<a href="([^"]*topic=[^"]*)">(.*?)</a></h5>'
                     r'.*?<strong><a [^>]*title="[^"]*">([^<]*)</a></strong>', re.S)


def ler_busca_do_forum(pagina: str) -> list[Achado]:
    achados = []
    for secao, link, titulo, autor in _TOPICO.findall(pagina):
        titulo = html.unescape(re.sub(r"<[^>]+>", "", titulo)).strip()
        if re.search(r"lixeira|arquivo morto", secao, re.I) or titulo.upper().startswith("FLOOD"):
            continue                                       # os tópicos apagados e as brincadeiras
        link = re.sub(r"PHPSESSID=[^&;]*&(amp;)?", "", html.unescape(link))
        a = Achado("romhacking.net.br", titulo, grupo=html.unescape(autor), traz=_o_que_traz(titulo), pagina=link,
                   formato=f"tópico em {html.unescape(secao)}")
        a.ids = {normalizar_id(i) for i in _ID.findall(titulo)}
        a.regiao = _regiao(titulo)
        versao = re.search(r"\[v\s?([\d.]+)\]|\bv(\d+(?:\.\d+)+)", titulo, re.I)
        a.versao = (versao.group(1) or versao.group(2)) if versao else ""
        a.feito_para = " ".join(p for p in (", ".join(sorted(a.ids)), f"({a.regiao})" if a.regiao else "") if p) or "—"
        achados.append(a)
    return achados


def _obter_texto(url: str, timeout: float = 30) -> str:
    import requests
    r = requests.get(url, timeout=timeout, headers={"User-Agent": "Maestro (organizador de jogos do PC)"})
    r.raise_for_status()
    r.encoding = r.encoding or "utf-8"
    return r.text


# ----------------------------------------------------------------- procurar
PREFIXOS = {"PS2": ("[PS2]", "PlayStation 2", "Playstation 2"), "PS1": ("[PSX]", "[PS1]", "PlayStation", "PSX")}


def procurar(termos: str, info: InfoISO | None, pasta: str | Path, onde: tuple = ONDES[:2], quer: str = QUER[0],
             crc32: str = "", sistema: str = "", baixar=_baixar, obter=_obter_texto) -> Resultado:
    """Os patches do jogo nos sites escolhidos, do que mais bate com a sua ISO para o que menos."""
    sistema = sistema or (info.sistema if info and info.sistema else "PS2")
    r = Resultado()
    termos = termos.strip()
    termos_web = quote_plus(re.sub(r"\bS[CL][A-Z]{2}[-_ ]?\d{3}\.?\d{2}\b", "", termos, flags=re.I).strip() or termos)
    if ONDES[0] in onde:
        try:
            banco = banco_pobre(pasta, baixar)
            for item in banco.get(sistema, []):
                nota = max(parecido(termos, item.get("game_title", "")), parecido(termos, item.get("title", "")))
                ids = {normalizar_id(i) for i in _ID.findall(item.get("texto", "") + item.get("patch_file", ""))}
                if info and info.id_jogo and info.id_jogo in ids:
                    nota = max(nota, 100)
                if nota < 60:
                    continue
                if any(s in (item.get("patch_type", "") + " " + item.get("title", "")).lower() for s in SO_O_JOGO):
                    r.escondidos += 1                      # o jogo inteiro (ISO): não aparece
                    continue
                a = _achado_pobre(item)
                a.nota = nota
                r.achados.append(a)
        except ErroBusca as erro:
            r.avisos.append(str(erro))
    if ONDES[1] in onde:
        try:
            pagina = obter(URL_FORUM.format(termos=termos_web))
            for a in ler_busca_do_forum(pagina):
                a.nota = parecido(termos, a.titulo)
                if a.nota >= 50 and any(a.titulo.startswith(p) or p in a.titulo for p in PREFIXOS.get(sistema, ())):
                    if any(s in a.titulo.lower() for s in SO_O_JOGO):
                        r.escondidos += 1
                        continue
                    r.achados.append(a)
        except Exception as erro:                          # o fórum fora do ar não impede o resto
            r.avisos.append(f"o fórum romhacking.net.br não respondeu ({str(erro)[:80]})")
    if ONDES[2] in onde:
        r.no_navegador["Romhacking.net"] = URL_RHN.format(termos=termos_web)
    if ONDES[3] in onde:
        r.no_navegador["itch.io"] = URL_ITCH.format(termos=termos_web + "+tradu%C3%A7%C3%A3o")
    for a in r.achados:
        a.encaixa = _encaixa(a, info, crc32)
    if quer == QUER[1]:
        r.achados = [a for a in r.achados if "dublagem" in a.traz]
    elif quer == QUER[2]:
        r.achados = [a for a in r.achados if "dublagem" not in a.traz]
    r.achados.sort(key=lambda a: (not a.ok(), a.encaixa.startswith("⚠"), -a.nota, a.onde != "PO.B.R.E"))
    return r


def pagina_do_pobre_offline(itens: list[dict]) -> bytes:
    """(Para os testes) um zip do banco do PO.B.R.E com estas traduções."""
    saida = io.BytesIO()
    with zipfile.ZipFile(saida, "w") as z:
        for item in itens:
            campos = "\n".join(f'{k}: "{v}"' for k, v in item.items() if k not in ("texto", "arquivo"))
            z.writestr(f"romhackersbr-db-main/_traducoes/console/{item['arquivo']}", f"---\n{campos}\n---\n"
                       f"{item.get('texto', '')}")
    return saida.getvalue()
