"""Os consoles da aba 🎮 Jogos (o submenu "Jogos → PlayStation 2", "→ PlayStation 1", "→ PSP"...): o que cada um usa
para o Maestro não misturar um com o outro (as configurações do PS2 continuam as mesmas).

    PlayStation 2      ISO/BIN · o código do SYSTEM.CNF · PCSX2 · nome do OPL · patch, dublar, enquanto joga
    PlayStation 1      BIN/ISO · o código do SYSTEM.CNF · DuckStation · patch, dublar (as falas VAG), enquanto joga
    PSP                ISO do UMD · o código do PARAM.SFO · PPSSPP · patch, enquanto joga
    Nintendo clássicos ROM do SNES, NES, GBA, GB/GBC, N64 ou DS · o título e o código do cabeçalho · o seu emulador
    GameCube / Wii     ISO/GCM (e WBFS/RVZ: só o código) · o cabeçalho do disco · Dolphin · patch, enquanto joga
    Nintendo Switch    o mod de tradução (pasta ou .zip, com o TitleID) · instalar no emulador ou no SD · enquanto joga
    PC                 a pasta do jogo · instalar os arquivos da tradução (com cópia de segurança) · enquanto joga

O Maestro não baixa jogos: sempre o arquivo tirado do SEU disco ou cartucho (ou o jogo que você comprou, no PC).
"""

from __future__ import annotations

import os
import re
import shutil
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

from . import patch_jogo as pj
from .patch_jogo import ErroPatch, InfoISO

PATCH, DUBLAR, ENQUANTO, INSTALAR = "patch", "dublar", "enquanto", "instalar"


@dataclass(frozen=True)
class Console:
    chave: str                   # "PS2" (a chave das configurações)
    nome: str                    # "PlayStation 2" (o submenu)
    modos: tuple                 # os modos da aba neste console (PATCH, DUBLAR, ENQUANTO, INSTALAR)
    jogo: str                    # "a ISO do seu disco" (o que você escolhe)
    rotulo: str                  # "ISO:" (o campo)
    tipos: tuple                 # os tipos de arquivo da janela de abrir
    emulador: str = ""           # "PCSX2"
    programas: tuple = ()        # os programas do emulador (Windows)
    pastas: tuple = ()           # onde ele costuma ficar (em Arquivos de Programas ou na pasta do usuário)
    opl: bool = False            # o nome no padrão do OPL (só o PS2)
    midia: str = "ISO"           # "ISO" / "ROM" (nos textos: "a ISO nova", "a ROM nova")
    redump: bool = False         # o disco tem lista no Redump

    @property
    def padrao(self) -> bool:
        return self.chave == "PS2"


TIPOS_ROM = "*.sfc *.smc *.nes *.gba *.gb *.gbc *.n64 *.z64 *.v64 *.nds"
_TODOS = ("Todos os arquivos", "*.*")
CONSOLES: dict[str, Console] = {c.chave: c for c in (
    Console("PS2", "PlayStation 2", (PATCH, DUBLAR, ENQUANTO), "a ISO do seu disco", "ISO:",
            (("Imagem do disco", "*.iso *.bin *.img"), _TODOS), "PCSX2", ("pcsx2-qt.exe", "pcsx2.exe", "pcsx2x64.exe"),
            ("PCSX2", "PCSX2 Nightly", "Programs/PCSX2", "Programs/pcsx2"), opl=True, redump=True),
    Console("PS1", "PlayStation 1", (PATCH, DUBLAR, ENQUANTO), "a imagem do seu disco (.bin ou .iso)", "Imagem:",
            (("Imagem do disco", "*.bin *.iso *.img"), _TODOS), "DuckStation",
            ("duckstation-qt-x64-ReleaseLTCG.exe", "duckstation-qt.exe", "duckstation.exe"),
            ("DuckStation", "Programs/DuckStation"), redump=True),
    Console("PSP", "PSP", (PATCH, ENQUANTO), "a ISO do seu UMD", "ISO:", (("ISO do UMD", "*.iso"), _TODOS), "PPSSPP",
            ("PPSSPPWindows64.exe", "PPSSPPWindows.exe", "PPSSPPQt.exe"), ("PPSSPP", "Programs/PPSSPP"), redump=True),
    Console("NINTENDO", "Nintendo clássicos", (PATCH, ENQUANTO), "a ROM do seu cartucho", "ROM:",
            (("ROM (SNES, NES, GBA, GB, N64, DS)", TIPOS_ROM), _TODOS), "o seu emulador",
            ("retroarch.exe", "mGBA.exe", "snes9x-x64.exe", "snes9x.exe", "Project64.exe", "melonDS.exe", "Mesen.exe"),
            ("RetroArch", "RetroArch-Win64", "mGBA", "Snes9x", "Project64 3.0", "melonDS", "Mesen"), midia="ROM"),
    Console("GCWII", "GameCube / Wii", (PATCH, ENQUANTO), "a ISO do seu disco", "ISO:",
            (("Imagem do disco", "*.iso *.gcm *.wbfs *.rvz"), _TODOS), "Dolphin", ("Dolphin.exe",),
            ("Dolphin", "Dolphin-x64", "Programs/Dolphin"), redump=True),
    Console("SWITCH", "Nintendo Switch", (INSTALAR, ENQUANTO), "o mod de tradução (pasta ou .zip)", "Mod:",
            (("Mod de tradução (.zip)", "*.zip"), _TODOS), "o seu emulador",
            ("Ryujinx.exe", "eden.exe", "citron.exe", "suyu.exe"), ("Ryujinx", "Eden", "Citron", "suyu")),
    Console("PC", "PC", (INSTALAR, ENQUANTO), "a pasta do jogo", "Pasta do jogo:", (_TODOS,)),
)}
ORDEM = tuple(CONSOLES)
NOMES = {"PS2": "PlayStation 2", "PS1": "PlayStation", "PSP": "PSP", "GC": "GameCube", "Wii": "Wii", "SNES": "Super NES",
         "NES": "NES", "GBA": "Game Boy Advance", "GB": "Game Boy", "GBC": "Game Boy Color", "N64": "Nintendo 64",
         "DS": "Nintendo DS", "Switch": "Nintendo Switch", "PC": "PC"}
REGIAO_PELA_LETRA = {"E": "EUA", "P": "Europa", "D": "Europa", "F": "Europa", "S": "Europa", "I": "Europa", "X": "Europa",
                     "J": "Japão", "K": "Coreia", "U": "Europa"}
REGIOES_PSP = {"ULUS": "EUA", "UCUS": "EUA", "NPUH": "EUA", "ULES": "Europa", "UCES": "Europa", "NPEH": "Europa",
               "ULJM": "Japão", "ULJS": "Japão", "UCJS": "Japão", "NPJH": "Japão", "ULKS": "Coreia", "ULAS": "Ásia"}


def console(chave: str) -> Console:
    return CONSOLES.get(chave, CONSOLES["PS2"])


def _texto(dados: bytes) -> str:
    """O texto de um cabeçalho (só as letras que dá para ler)."""
    texto = dados.split(b"\0")[0].decode("latin-1", "replace")
    return re.sub(r"[^\x20-\x7e\xc0-\xff]", "", texto).strip()


# ----------------------------------------------------------------- ler o código do jogo, por console
def identificar(caminho: str | Path, chave: str = "PS2") -> InfoISO:
    """O código, o título, a região e o sistema do jogo, lidos de dentro do arquivo. ErroPatch se não é do console."""
    caminho = Path(caminho)
    if not caminho.is_file():
        raise ErroPatch(f"não achei o arquivo: {caminho}")
    if chave in ("PS2", "PS1"):
        return pj.ler_info(caminho)
    if chave == "PSP":
        return _psp(caminho)
    if chave == "GCWII":
        return _gamecube_wii(caminho)
    if chave == "NINTENDO":
        return _rom_nintendo(caminho)
    return InfoISO(caminho, caminho.stat().st_size)


def _listar(f, formato, lba: int, tamanho: int) -> dict[str, tuple[int, int]]:
    """{nome: (setor, tamanho)} de uma pasta do disco (ISO 9660)."""
    dados = pj._ler(f, formato, lba, min(tamanho, 64 * 2048))
    arquivos, pos = {}, 0
    while pos < len(dados):
        n = dados[pos]
        if n == 0:
            pos = (pos // 2048 + 1) * 2048
            continue
        registro = dados[pos:pos + n]
        if len(registro) >= 33:
            nome = registro[33:33 + registro[32]].decode("ascii", "replace").split(";")[0].upper()
            arquivos[nome] = (struct.unpack_from("<I", registro, 2)[0], struct.unpack_from("<I", registro, 10)[0])
        pos += n
    return arquivos


def ler_sfo(dados: bytes) -> dict[str, str | int]:
    """As informações do PARAM.SFO do PSP (TITLE, DISC_ID, DISC_VERSION...)."""
    if dados[:4] != b"\0PSF":
        return {}
    chaves, valores, quantos = struct.unpack_from("<III", dados, 8)
    campos: dict[str, str | int] = {}
    for i in range(quantos):
        onde_chave, formato, tamanho, _, onde_valor = struct.unpack_from("<HHIII", dados, 20 + 16 * i)
        nome = dados[chaves + onde_chave:].split(b"\0")[0].decode("ascii", "replace")
        bruto = dados[valores + onde_valor:valores + onde_valor + tamanho]
        campos[nome] = struct.unpack_from("<I", bruto)[0] if formato == 0x0404 and len(bruto) >= 4 else \
            bruto.split(b"\0")[0].decode("utf-8", "replace")
    return campos


def _psp(caminho: Path) -> InfoISO:
    info = InfoISO(caminho, caminho.stat().st_size, sistema="PSP")
    with open(caminho, "rb") as f:
        formato = pj._formato_iso(f)
        if formato is None:
            raise ErroPatch(f"{caminho.name} não parece a ISO de um UMD (ISO 9660). CSO comprimido: descomprima "
                            "antes (o PPSSPP abre, mas o patch é feito na ISO)")
        info.volume = pj._ler(f, formato, 16, 2048)[40:72].decode("ascii", "replace").strip()
        raiz = pj._arquivos_da_raiz(f, formato)
        sfo: dict = {}
        if "PSP_GAME" in raiz:
            pasta = _listar(f, formato, *raiz["PSP_GAME"])
            if "PARAM.SFO" in pasta:
                lba, tamanho = pasta["PARAM.SFO"]
                sfo = ler_sfo(pj._ler(f, formato, lba, min(tamanho, 64 * 1024)))
        codigo = str(sfo.get("DISC_ID", ""))
        if not codigo and "UMD_DATA.BIN" in raiz:
            lba, tamanho = raiz["UMD_DATA.BIN"]
            codigo = pj._ler(f, formato, lba, min(tamanho, 256)).split(b"|")[0].decode("ascii", "replace")
    codigo = re.sub(r"[^A-Z0-9]", "", codigo.upper())
    if re.fullmatch(r"[A-Z]{4}\d{5}", codigo):
        info.id_jogo = f"{codigo[:4]}-{codigo[4:]}"
        info.regiao_lida = REGIOES_PSP.get(codigo[:4], "")
    info.volume = str(sfo.get("TITLE", "")) or info.volume
    info.versao = str(sfo.get("DISC_VERSION", ""))
    return info


def _gamecube_wii(caminho: Path) -> InfoISO:
    info = InfoISO(caminho, caminho.stat().st_size)
    with open(caminho, "rb") as f:
        inicio = f.read(0x400)
        if inicio[:4] == b"WBFS":                      # o disco começa no setor do WBFS
            f.seek(0x200)
            disco = f.read(0x80)
        elif inicio[:4] in (b"RVZ\x01", b"WIA\x01"):   # comprimido: o cabeçalho do disco vem copiado no começo
            disco = inicio[0x58:0x58 + 0x80]
        else:
            disco = inicio[:0x80]
    wii = struct.unpack_from(">I", disco, 0x18)[0] == 0x5D1C9EA3
    gc = struct.unpack_from(">I", disco, 0x1C)[0] == 0xC2339F3D
    if not (wii or gc):
        raise ErroPatch(f"{caminho.name} não parece um disco de GameCube ou Wii (ISO, GCM, WBFS ou RVZ)")
    info.sistema = "Wii" if wii else "GC"
    info.id_jogo = _texto(disco[:6])
    info.volume = _texto(disco[0x20:0x80])
    info.versao = str(disco[7])
    info.regiao_lida = REGIAO_PELA_LETRA.get(info.id_jogo[3:4], "")
    return info


def _rom_nintendo(caminho: Path) -> InfoISO:
    tamanho = caminho.stat().st_size
    with open(caminho, "rb") as f:
        dados = f.read(0x10200)
    info = InfoISO(caminho, tamanho)
    ext = caminho.suffix.lower()
    if dados[:4] == b"NES\x1a" or ext == ".nes":
        info.sistema, info.volume = "NES", caminho.stem
    elif ext == ".gba":
        codigo = _texto(dados[0xAC:0xB0])
        info.sistema, info.volume = "GBA", _texto(dados[0xA0:0xAC])
        info.id_jogo = f"AGB-{codigo}" if codigo else ""
        info.regiao_lida = REGIAO_PELA_LETRA.get(codigo[3:4], "")
    elif ext in (".gb", ".gbc"):
        info.sistema = "GBC" if len(dados) > 0x143 and dados[0x143] & 0x80 else "GB"
        info.volume = _texto(dados[0x134:0x144])
    elif ext in (".n64", ".z64", ".v64"):
        cab = bytearray(dados[:0x40])
        if cab[:4] == b"\x37\x80\x40\x12":            # .v64: os bytes trocados de 2 em 2
            cab[0::2], cab[1::2] = cab[1::2], cab[0::2]
        elif cab[:4] == b"\x40\x12\x37\x80":          # .n64: de 4 em 4, ao contrário
            cab = bytearray(b"".join(bytes(reversed(cab[i:i + 4])) for i in range(0, len(cab), 4)))
        codigo = _texto(bytes(cab[0x3B:0x3F]))
        info.sistema, info.volume = "N64", _texto(bytes(cab[0x20:0x34]))
        info.id_jogo = f"NUS-{codigo}" if len(codigo) == 4 else ""
        info.regiao_lida = REGIAO_PELA_LETRA.get(codigo[3:4], "")
    elif ext == ".nds":
        codigo = _texto(dados[0x0C:0x10])
        info.sistema, info.volume = "DS", _texto(dados[0:0x0C])
        info.id_jogo = f"NTR-{codigo}" if codigo else ""
        info.regiao_lida = REGIAO_PELA_LETRA.get(codigo[3:4], "")
    elif ext in (".sfc", ".smc"):
        copiador = 512 if tamanho % 1024 == 512 else 0           # (o cabeçalho de 512 bytes dos copiadores antigos)
        melhor = None
        for onde in (0x7FC0, 0xFFC0):                             # LoROM / HiROM
            base = copiador + onde
            if len(dados) >= base + 0x20:
                complemento, soma = struct.unpack_from("<HH", dados, base + 0x1C)
                if complemento + soma == 0xFFFF:
                    melhor = base
                    break
                if melhor is None and _texto(dados[base:base + 21]):
                    melhor = base
        info.sistema = "SNES"
        if melhor is not None:
            info.volume = _texto(dados[melhor:melhor + 21])
            info.regiao_lida = {0: "Japão", 1: "EUA"}.get(dados[melhor + 0x19], "Europa")
    else:
        raise ErroPatch(f"{caminho.name}: não conheço essa ROM (.sfc, .smc, .nes, .gba, .gb, .gbc, .n64, .z64, .v64 "
                        "ou .nds)")
    return info


def descrever(info: InfoISO) -> str:
    """'GALE01 · Super Smash Bros. Melee · GameCube · EUA · versão 2 · 1,36 GB'."""
    partes = [p for p in (info.id_jogo, info.volume if info.sistema not in ("PS2", "PS1") else "",
                          NOMES.get(info.sistema, info.sistema), info.regiao,
                          f"versão {info.versao}" if info.versao and info.versao != "0" else "",
                          pj.tamanho_legivel(info.tamanho)) if p]
    return " · ".join(partes)


# ----------------------------------------------------------------- o arquivo novo e o emulador
def nome_final(chave: str, info: InfoISO | None, nome: str, opl: bool = False) -> str:
    """O nome da cópia traduzida: no PS2, o padrão do OPL (se marcado); nos outros, com a extensão do original."""
    if not nome:
        return ""
    if chave == "PS2" and opl and info is not None:
        return pj.nome_para_o_opl(info, nome)
    extensao = info.caminho.suffix.lower() if info is not None and info.caminho.suffix else ".iso"
    return nome if nome.lower().endswith(extensao) else f"{nome}{extensao}"


def achar_emulador(chave: str, escolhido: str = "", sistema: str = sys.platform) -> Path | None:
    """O emulador do console neste PC: o escolhido antes ou os lugares de sempre (o PATH, Arquivos de Programas)."""
    if escolhido and Path(escolhido).is_file():
        return Path(escolhido)
    c = console(chave)
    nomes = c.programas if sistema == "win32" else tuple(dict.fromkeys(n[:-4].lower() if n.endswith(".exe") else n
                                                                       for n in c.programas))
    for nome in nomes:
        if achado := shutil.which(nome):
            return Path(achado)
    if sistema == "win32":
        for base in filter(None, (os.environ.get(v, "") for v in ("ProgramFiles", "ProgramFiles(x86)",
                                                                  "LOCALAPPDATA"))):
            for pasta in c.pastas:
                for nome in nomes:
                    if (Path(base) / pasta / nome).is_file():
                        return Path(base) / pasta / nome
    return None
