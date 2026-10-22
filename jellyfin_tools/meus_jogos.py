"""🔎 Meus jogos (aba 🎮 Jogos): acha os jogos que você JÁ TEM no PC, separa por console e procura a tradução de cada
um. O Maestro só lê os seus arquivos: não baixa jogos, não move nem apaga nada.

    achar        as pastas escolhidas (com as subpastas): ISO/BIN/IMG (PS2, PS1, PSP, GameCube/Wii), GCM/WBFS/RVZ,
                 as ROMs (SNES, NES, GBA, GB/GBC, N64, DS), NSP/XCI (Switch, as cópias do SEU cartucho) e a
                 biblioteca da Steam (os jogos de PC instalados, pelos appmanifest)
    identificar  o console, o código, o título e a região, lidos de dentro de cada arquivo (consoles.py)
    guardar      meus_jogos.json: o que já foi lido, pelo tamanho e pela data do arquivo; da 2ª vez em diante, só os
                 arquivos novos ou mudados são abertos de novo
    Redump       (opcional) a impressão digital do disco comparada com a lista das cópias perfeitas
    tradução     a busca na comunidade (comunidade.py: só patches; as ISOs inteiras ficam de fora), guardada por 7 dias
    traduzidos   os que você já traduziu pelo Maestro (patches_aplicados.json e traducoes_instaladas.json)
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import consoles as cs
from . import patch_jogo as pj
from .patch_jogo import ErroPatch

DISCOS = {".iso", ".bin", ".img"}                         # PS2, PS1, PSP (ISO 9660) ou GameCube/Wii (.iso)
GCWII = {".gcm", ".wbfs", ".rvz"}
ROMS = {".sfc", ".smc", ".nes", ".gba", ".gb", ".gbc", ".n64", ".z64", ".v64", ".nds"}
SWITCH = {".nsp", ".xci"}
EXTENSOES = DISCOS | GCWII | ROMS | SWITCH
PULAR = re.compile(r"^(\.|__MACOSX$|\$RECYCLE\.BIN$|System Volume Information$|\.maestro)", re.I)
MINIMO_DISCO = 64 * 1024                                  # (um .bin/.img menor não é a imagem de um disco)
VALIDADE_TRADUCAO = 7 * 24 * 3600                         # a busca na comunidade vale 7 dias
TITLE_ID = re.compile(r"\[?(01[0-9A-Fa-f]{14})\]?")
ROTULOS = {"PS2": "PlayStation 2", "PS1": "PlayStation 1", "PSP": "PSP", "GC": "GameCube", "Wii": "Wii",
           "SNES": "Super NES", "NES": "NES", "GBA": "GBA", "GB": "Game Boy", "GBC": "Game Boy Color",
           "N64": "Nintendo 64", "DS": "Nintendo DS", "Switch": "Switch", "Steam": "PC"}
FILTROS = (("PS2", "PS2"), ("PS1", "PS1"), ("PSP", "PSP"), ("NINTENDO", "Nintendo"), ("GCWII", "GC / Wii"),
           ("SWITCH", "Switch"), ("PC", "PC"))
ORDEM = tuple(chave for chave, _ in FILTROS)


@dataclass
class Jogo:
    caminho: str                  # o arquivo (no PC: a pasta do jogo)
    console: str                  # a chave do submenu: PS2, PS1, PSP, NINTENDO, GCWII, SWITCH, PC
    sistema: str                  # "PS2", "SNES", "GC", "Switch", "Steam"...
    titulo: str = ""
    codigo: str = ""              # "SLUS-21050", "AGB-BMJE", "0100ABCD12340000", "Steam 123450"
    regiao: str = ""
    tamanho: int = 0
    data: int = 0                 # a data do arquivo (ns): junto com o tamanho, diz se mudou
    versao: str = ""
    crc32: str = ""
    md5: str = ""
    redump: str | None = None     # o nome no banco Redump; "" = não está; None = não conferido
    traducao: dict = field(default_factory=dict)   # {"quando", "achados": [...], "aviso"}
    traduzido: str = ""           # "aplicado" (a cópia traduzida), "original" (tem cópia traduzida), "instalado"
    procurando: bool = False      # a busca na comunidade deste jogo está na fila

    @property
    def rotulo(self) -> str:
        return ROTULOS.get(self.sistema, self.sistema)

    @property
    def disco(self) -> bool:
        """Tem lista no Redump (os discos, não os cartuchos nem o PC)."""
        return self.sistema in ("PS2", "PS1", "PSP", "GC", "Wii")

    def info(self) -> pj.InfoISO:
        return pj.InfoISO(Path(self.caminho), self.tamanho, self.codigo if self.console in ("PS2", "PS1", "PSP")
                          else "", volume=self.titulo, sistema=self.sistema, versao=self.versao,
                          regiao_lida=self.regiao)

    # ---- o que a tabela mostra
    def texto_copia(self) -> str:
        if self.traduzido == "aplicado":
            return "· modificada (já traduzida)"
        if self.console == "PC":
            return "— (jogo de PC)"
        if not self.disco:
            return "— cartucho (sem Redump)"
        if self.redump:
            return "✓ perfeita (Redump)"
        if self.redump == "":
            return "⚠ não está no Redump"
        return "não conferida"

    def achados(self) -> list[dict]:
        return list(self.traducao.get("achados", []))

    def texto_traducao(self) -> str:
        if self.traduzido == "aplicado":
            return "✓ já traduzida por você (🗂 aplicados)"
        if self.traduzido == "instalado":
            return "✓ instalada por você (Desfazer em 🗂)"
        if self.traduzido == "original":
            return "✓ você já tem a cópia traduzida"
        if not self.traducao:
            return "… procurando" if self.procurando else "— não procurada"
        bons = [a for a in self.achados() if not a.get("encaixa", "").startswith("⚠")]
        if bons:
            traz = bons[0].get("traz") or []
            return f"✓ {len(bons)} patch{'es' if len(bons) > 1 else ''}" + (f" · {' e '.join(traz[:2])}" if traz
                                                                                   else "")
        if self.achados():
            return "⚠ só de outra versão do jogo"
        if self.traducao.get("aviso") and not self.traducao.get("achados"):
            return "? a comunidade não respondeu"
        return "✗ não tem → 🗣 traduzir e dublar"

    def tem_traducao(self) -> bool:
        return self.texto_traducao().startswith("✓")


# ----------------------------------------------------------------- achar e identificar
def listar(pastas, parar=None) -> list[Path]:
    """Os arquivos de jogo e as bibliotecas da Steam das pastas (com as subpastas)."""
    achados: list[Path] = []
    vistos: set = set()
    for pasta in pastas:
        pasta = Path(pasta)
        if not pasta.is_dir():
            continue
        steam = biblioteca_steam(pasta)
        if steam is not None:                            # (a Steam: a lista dos jogos, sem abrir os arquivos deles)
            if steam not in vistos:
                vistos.add(steam)
                achados.append(steam)
            continue
        for raiz, dirs, arquivos in os.walk(pasta):
            if parar and parar():
                raise ErroPatch("interrompido (botão Parar)")
            for d in dirs:                               # uma biblioteca da Steam lá dentro (D:\SteamLibrary)
                steam = biblioteca_steam(Path(raiz) / d) if (Path(raiz) / d / "steamapps").is_dir() else None
                if steam is not None and steam not in vistos:
                    vistos.add(steam)
                    achados.append(steam)
            dirs[:] = sorted(d for d in dirs if not PULAR.match(d) and not (Path(raiz) / d / "steamapps").is_dir()
                             and d.lower() != "steamapps")
            for nome in sorted(arquivos):
                caminho = Path(raiz) / nome
                if caminho.suffix.lower() in EXTENSOES and caminho not in vistos:
                    vistos.add(caminho)
                    achados.append(caminho)
    return achados


def biblioteca_steam(pasta: Path) -> Path | None:
    """A pasta steamapps (com os appmanifest) se a escolhida é a da Steam, a steamapps ou a common."""
    pasta = Path(pasta)
    for candidata in (pasta, pasta / "steamapps", pasta.parent):
        if candidata.name.lower() == "steamapps" and any(candidata.glob("appmanifest_*.acf")):
            if candidata == pasta.parent and pasta.name.lower() != "common":
                continue
            return candidata
    return None


def _acf(texto: str) -> dict:
    return {chave.lower(): valor for chave, valor in re.findall(r'"(\w+)"\s+"([^"]*)"', texto)}


def jogos_da_steam(steamapps: Path) -> list[Jogo]:
    jogos = []
    for manifesto in sorted(steamapps.glob("appmanifest_*.acf")):
        try:
            dados = _acf(manifesto.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        pasta = steamapps / "common" / dados.get("installdir", "")
        if not dados.get("installdir") or not pasta.is_dir() or "redistributable" in dados.get("name", "").lower():
            continue
        jogos.append(Jogo(str(pasta), "PC", "Steam", dados.get("name", pasta.name), f"Steam {dados.get('appid', '')}",
                          tamanho=int(dados.get("sizeondisk", "0") or 0), data=manifesto.stat().st_mtime_ns))
    return jogos


def identificar(caminho: Path) -> Jogo | None:
    """O jogo de dentro do arquivo (None se não é um jogo que o Maestro conhece)."""
    caminho = Path(caminho)
    estado = caminho.stat()
    ext = caminho.suffix.lower()
    jogo = Jogo(str(caminho), "", "", tamanho=estado.st_size, data=estado.st_mtime_ns)
    if ext in SWITCH:
        achado = TITLE_ID.search(caminho.name)
        jogo.console, jogo.sistema = "SWITCH", "Switch"
        jogo.codigo = achado.group(1).upper() if achado else ""
        jogo.titulo = re.sub(r"\s*[\[(][^\])]*[\])]", "", caminho.stem).strip() or caminho.stem
        return jogo
    try:
        if ext in ROMS:
            info, jogo.console = cs.identificar(caminho, "NINTENDO"), "NINTENDO"
        elif ext in GCWII:
            info, jogo.console = cs.identificar(caminho, "GCWII"), "GCWII"
        else:
            if estado.st_size < MINIMO_DISCO:
                return None
            info = _disco(caminho)
            if info is None:
                return None
            jogo.console = {"PS2": "PS2", "PS1": "PS1", "PSP": "PSP"}.get(info.sistema, "GCWII")
    except (ErroPatch, OSError, ValueError, IndexError):
        return None
    jogo.sistema, jogo.codigo, jogo.versao = info.sistema, info.id_jogo, info.versao
    jogo.regiao = info.regiao
    jogo.titulo = _titulo(caminho, info)
    return jogo


def _disco(caminho: Path) -> pj.InfoISO | None:
    """PS2/PS1 (SYSTEM.CNF), PSP (PARAM.SFO) ou GameCube/Wii (o cabeçalho): o que for."""
    try:
        info = pj.ler_info(caminho)
    except ErroPatch:
        try:
            return cs.identificar(caminho, "GCWII")         # (não é ISO 9660: pode ser o disco do GameCube/Wii)
        except ErroPatch:
            return None
    if info.sistema in ("PS2", "PS1"):
        return info
    try:
        psp = cs.identificar(caminho, "PSP")
    except ErroPatch:
        return None
    return psp if psp.id_jogo else None


def _titulo(caminho: Path, info: pj.InfoISO) -> str:
    """O nome do arquivo sem o código do OPL e sem os parênteses; se não sobrar nada, o título de dentro."""
    nome = re.sub(r"^[A-Z]{4}[_-]\d{3}\.\d{2}\.", "", caminho.stem)
    nome = re.sub(r"\s*[\[(][^\])]*[\])]", "", nome).replace("_", " ").strip()
    return nome or info.volume or caminho.stem


# ----------------------------------------------------------------- guardar (só reabre o que mudou)
def carregar(arquivo: str | Path) -> dict[str, Jogo]:
    try:
        dados = json.loads(Path(arquivo).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    jogos = {}
    for d in dados.get("jogos", []) if isinstance(dados, dict) else []:
        try:
            jogos[d["caminho"]] = Jogo(**d)
        except (TypeError, KeyError):
            continue
        jogos[d["caminho"]].procurando = False
    return jogos


def salvar(arquivo: str | Path, jogos: list[Jogo]) -> None:
    arquivo = Path(arquivo)
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    temporario = arquivo.with_suffix(".tmp")
    temporario.write_text(json.dumps({"jogos": [asdict(j) for j in jogos]}, ensure_ascii=False, indent=1),
                          encoding="utf-8")
    os.replace(temporario, arquivo)


def varrer(pastas, guardados: dict[str, Jogo] | None = None, ao_progresso=None, parar=None,
           identificar_=identificar) -> tuple[list[Jogo], int, list[Jogo]]:
    """Os jogos das pastas: os que não mudaram (mesmo tamanho e data) vêm do que foi guardado. (jogos, quantos
    arquivos foram examinados agora, os arquivos que não são jogo: guardados também, para não abrir de novo)."""
    guardados = guardados or {}
    progresso = ao_progresso or (lambda f, texto="": None)
    arquivos = listar(pastas, parar)
    jogos: list[Jogo] = []
    ignorados: list[Jogo] = []
    lidos = 0
    for k, caminho in enumerate(arquivos):
        if parar and parar():
            raise ErroPatch("interrompido (botão Parar)")
        progresso(k / max(1, len(arquivos)), f"Lendo {k + 1} de {len(arquivos)}: {caminho.name}")
        if caminho.name.lower() == "steamapps":
            for jogo in jogos_da_steam(caminho):
                antigo = guardados.get(jogo.caminho)
                if antigo is not None:
                    jogo.traducao = antigo.traducao
                jogos.append(jogo)
            continue
        try:
            estado = caminho.stat()
        except OSError:
            continue
        antigo = guardados.get(str(caminho))
        if antigo is not None and (antigo.tamanho, antigo.data) == (estado.st_size, estado.st_mtime_ns):
            antigo.traduzido = ""
            (jogos if antigo.console else ignorados).append(antigo)
            continue
        lidos += 1
        jogo = identificar_(caminho)
        if jogo is not None:
            jogos.append(jogo)
        else:                                            # (não é jogo: guardado sem console)
            ignorados.append(Jogo(str(caminho), "", "", tamanho=estado.st_size, data=estado.st_mtime_ns))
    progresso(1.0, f"{len(arquivos)} arquivos lidos")
    return jogos, lidos, ignorados


# ----------------------------------------------------------------- o que você já traduziu pelo Maestro
def marcar_traduzidos(jogos: list[Jogo], aplicados: list[dict], instaladas: list) -> None:
    """A cópia traduzida (dos patches aplicados), o original que já tem cópia traduzida e as traduções instaladas."""
    def chave(caminho) -> str:
        return os.path.normcase(os.path.abspath(str(caminho)))
    destinos = {chave(d.get("destino", "")) for d in aplicados}
    originais = {chave(d.get("iso", "")) for d in aplicados if Path(d.get("destino", "")).exists()}
    pastas_pc = {chave(i.destino) for i in instaladas if i.console == "PC"}
    switch = " ".join(i.destino.upper() for i in instaladas if i.console == "SWITCH")
    for jogo in jogos:
        c = chave(jogo.caminho)
        if c in destinos:
            jogo.traduzido = "aplicado"
        elif c in originais:
            jogo.traduzido = "original"
        elif jogo.console == "PC" and c in pastas_pc:
            jogo.traduzido = "instalado"
        elif jogo.console == "SWITCH" and jogo.codigo and jogo.codigo in switch:
            jogo.traduzido = "instalado"


# ----------------------------------------------------------------- Redump e a tradução na comunidade
def conferir_redump(jogo: Jogo, indices: dict, pasta_redump: str | Path, ao_progresso=None, parar=None,
                    indice_=None, procurar_=None) -> None:
    """A impressão digital (uma vez só: fica guardada com o tamanho e a data) e o nome no banco Redump."""
    from . import redump
    indice_ = indice_ or redump.indice
    procurar_ = procurar_ or redump.procurar
    if not jogo.disco or jogo.traduzido == "aplicado" or jogo.redump is not None or \
            Path(jogo.caminho).suffix.lower() in (".wbfs", ".rvz"):     # (comprimido: a impressão nunca bate)
        return
    if not jogo.md5:
        digital = pj.impressao_digital(jogo.caminho, ao_progresso, parar)
        jogo.crc32, jogo.md5 = digital.crc32, digital.md5
    if jogo.sistema not in indices:
        indices[jogo.sistema] = indice_(jogo.sistema, pasta_redump)
    jogo.redump = procurar_(indices[jogo.sistema], jogo.md5, jogo.crc32, jogo.tamanho) or ""


def precisa_procurar(jogo: Jogo, agora: float | None = None) -> bool:
    if jogo.traduzido:
        return False
    quando = jogo.traducao.get("quando", 0) if jogo.traducao else 0
    return (agora or time.time()) - quando > VALIDADE_TRADUCAO or bool(jogo.traducao.get("aviso"))


def termos(jogo: Jogo) -> str:
    from . import comunidade as cm
    nome = re.sub(r"\s*\([^)]*\)", "", jogo.redump).strip() if jogo.redump else ""
    return nome or cm.nome_do_jogo(jogo.info(), jogo.titulo) or jogo.titulo


def procurar_traducao(jogo: Jogo, pasta_comunidade: str | Path, procurar_=None, agora=time.time) -> None:
    """A busca na comunidade (só patches): o PO.B.R.E e o fórum romhacking.net.br."""
    from . import comunidade as cm
    procurar_ = procurar_ or cm.procurar
    sistema = {"Steam": "PC"}.get(jogo.sistema, jogo.sistema)
    info = jogo.info() if jogo.console not in ("PC", "SWITCH") else None
    r = procurar_(termos(jogo), info, pasta_comunidade, cm.ONDES[:2], cm.QUER[0], crc32=jogo.crc32, sistema=sistema)
    jogo.traducao = {"quando": agora(), "aviso": "; ".join(r.avisos),
                     "achados": [{"titulo": a.titulo, "onde": a.onde, "grupo": a.grupo, "versao": a.versao,
                                  "traz": list(a.traz), "encaixa": a.encaixa, "pagina": a.pagina, "formato": a.formato}
                                 for a in r.achados[:20]]}


# ----------------------------------------------------------------- o resumo
def contar(jogos: list[Jogo]) -> dict[str, int]:
    contagem = {chave: 0 for chave, _ in FILTROS}
    for jogo in jogos:
        contagem[jogo.console] = contagem.get(jogo.console, 0) + 1
    return contagem


def resumo(jogos: list[Jogo]) -> str:
    com = sum(1 for j in jogos if j.tem_traducao())
    seus = sum(1 for j in jogos if j.traduzido)
    sem = sum(1 for j in jogos if j.texto_traducao().startswith("✗"))
    procurando = sum(1 for j in jogos if j.texto_traducao().startswith("…"))
    partes = [f"{com} com tradução" + (f" ({seus} já traduzido{'s' if seus != 1 else ''} por você)" if seus else ""),
              f"{sem} sem tradução (dá para traduzir e dublar)"]
    if procurando:
        partes.append(f"{procurando} procurando…")
    return " · ".join(partes)


def por_pasta(jogos: list[Jogo], pastas) -> dict[str, tuple[int, str]]:
    """{pasta: (quantos jogos, "PS2 (12), PS1 (3)")}: os nomes curtos, para caber na tabela."""
    resultado = {}
    for pasta in pastas:
        base = os.path.normcase(os.path.abspath(str(pasta)))
        dentro = [j for j in jogos if os.path.normcase(os.path.abspath(j.caminho)).startswith(base.rstrip("\\/") +
                                                                                            os.sep)]
        quantos: dict[str, int] = {}
        for j in dentro:
            curto = {"Steam": "PC"}.get(j.sistema, j.sistema)
            quantos[curto] = quantos.get(curto, 0) + 1
        resultado[str(pasta)] = (len(dentro), ", ".join(f"{n} ({q})" for n, q in sorted(quantos.items(),
                                                                                         key=lambda x: -x[1])))
    return resultado
