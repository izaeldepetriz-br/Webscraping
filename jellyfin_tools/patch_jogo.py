"""Patch de fãs (tradução, dublagem) na ISO do SEU disco de PS2 (ou PS1), para rodar em qualquer lugar: no PS2 pelo
OPL, no PCSX2, no NetherSX2/AetherSX2 do celular ou num DVD gravado. Tudo fica DENTRO da ISO nova.

Os grupos de fãs distribuem só o PATCH (a lista das diferenças), nunca o jogo: quem tem o disco aplica na própria
ISO. O Maestro não baixa jogos; a busca na comunidade procura só patches.

    1. Jogo   a ISO: o código do jogo (SLUS-20946...) lido do SYSTEM.CNF e a "impressão digital" (CRC32/MD5/SHA-1)
    2. Patch  .xdelta/.vcdiff (o xdelta3 oficial, baixado uma vez, ~0,2 MB) ou .ppf (aplicado aqui mesmo); o leia-me
              do patch costuma dizer a impressão digital da ISO certa: o Maestro confere ANTES de aplicar (o patch
              da versão americana estraga a europeia)
    3. Aplicar numa CÓPIA (a ISO original não muda), com o nome no padrão do OPL se quiser

E o caminho de volta: criar o .xdelta da SUA tradução (a ISO original + a modificada), para compartilhar sem
compartilhar o jogo.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import threading
import time
import zipfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path

from .dublagem import SEM_JANELA, ErroDublagem, _baixar

VERSAO_XDELTA = "3.1.0"
URL_XDELTA = (f"https://github.com/jmacd/xdelta-gpl/releases/download/v{VERSAO_XDELTA}/"
              f"xdelta3-{VERSAO_XDELTA}-x86_64.exe.zip")
SHA256_XDELTA = "b10e0d1df3e212e5a2d37d5c088d2f72ecec760bc3c26caeca51499c3118b93a"   # o .zip oficial (conferido)
XDELTA, PPF, IPS, BPS = "xdelta", "ppf", "ips", "bps"
EXTENSOES_PATCH = (".xdelta", ".vcdiff", ".xd3", ".delta", ".ppf", ".ips", ".bps")
EXTENSOES_ISO = (".iso", ".bin", ".img")
MAGICA_VCDIFF = b"\xd6\xc3\xc4"
BLOCO = 8 * 1024 * 1024                  # leitura de 8 MB por vez (a ISO de DVD tem 4 GB)
FOLGA_DISCO = 200 * 1024 * 1024          # além do tamanho da ISO nova
JANELA_XDELTA = 256 * 1024 * 1024        # criar o patch: quanto da ISO original o xdelta3 olha de uma vez
REGIOES = {"SLUS": "EUA", "SCUS": "EUA", "SLES": "Europa", "SCES": "Europa", "SCED": "Europa", "SLPS": "Japão",
           "SLPM": "Japão", "SCPS": "Japão", "SLKA": "Coreia", "SCKA": "Coreia", "SLAJ": "Ásia", "SCAJ": "Ásia"}


class ErroPatch(ErroDublagem):
    pass


# ----------------------------------------------------------------- 1. o jogo (a ISO)
@dataclass
class InfoISO:
    caminho: Path
    tamanho: int
    id_jogo: str = ""          # "SLUS-20946" ("" se não achou o SYSTEM.CNF)
    arquivo_boot: str = ""     # "SLUS_209.46" (como no disco: o nome que o OPL usa)
    volume: str = ""           # o nome do volume ("MEU_JOGO")
    sistema: str = ""          # "PS2" (BOOT2) ou "PS1" (BOOT); nos outros consoles, "PSP", "GC", "SNES"...
    versao: str = ""           # "1.00" (VER no SYSTEM.CNF)
    regiao_lida: str = ""      # a região lida do próprio jogo (nos consoles sem o código SLUS/SCES...)

    @property
    def regiao(self) -> str:
        return self.regiao_lida or REGIOES.get(self.id_jogo[:4], "")

    def descrever(self) -> str:
        partes = [p for p in (self.id_jogo, self.regiao, self.sistema, f"versão {self.versao}" if self.versao else "",
                              self.volume, tamanho_legivel(self.tamanho)) if p]
        return " · ".join(partes) if self.id_jogo else "não achei o código do jogo (é do console escolhido?) · " + \
            tamanho_legivel(self.tamanho)


def tamanho_legivel(n: int) -> str:
    return f"{n / 1024 ** 3:.2f} GB".replace(".", ",") if n >= 1024 ** 3 else \
        f"{n / 1024 ** 2:.0f} MB" if n >= 1024 ** 2 else f"{n / 1024:.0f} KB"


def _formato_iso(f) -> tuple[int, int] | None:
    """(tamanho do setor, onde começam os dados no setor): 2048 (ISO) ou 2352 (BIN: modo 2 ou modo 1)."""
    for setor, inicio in ((2048, 0), (2352, 24), (2352, 16)):
        f.seek(16 * setor + inicio)
        pvd = f.read(7)
        if len(pvd) == 7 and pvd[1:6] == b"CD001":
            return setor, inicio
    return None


def _ler(f, formato, lba: int, tamanho: int) -> bytes:
    setor, inicio = formato
    partes = []
    while tamanho > 0:
        f.seek(lba * setor + inicio)
        partes.append(f.read(min(2048, tamanho)))
        tamanho -= 2048
        lba += 1
    return b"".join(partes)


def _arquivos_da_raiz(f, formato) -> dict[str, tuple[int, int]]:
    """{nome: (setor, tamanho)} dos arquivos na raiz do disco (ISO 9660)."""
    pvd = _ler(f, formato, 16, 2048)
    raiz = pvd[156:190]
    lba, tamanho = struct.unpack_from("<I", raiz, 2)[0], struct.unpack_from("<I", raiz, 10)[0]
    dados = _ler(f, formato, lba, min(tamanho, 64 * 2048))
    arquivos, pos = {}, 0
    while pos < len(dados):
        n = dados[pos]
        if n == 0:                                   # o resto do setor está vazio: pula para o próximo
            pos = (pos // 2048 + 1) * 2048
            continue
        registro = dados[pos:pos + n]
        if len(registro) >= 33:
            nome = registro[33:33 + registro[32]].decode("ascii", "replace").split(";")[0].upper()
            arquivos[nome] = (struct.unpack_from("<I", registro, 2)[0], struct.unpack_from("<I", registro, 10)[0])
        pos += n
    return arquivos


def ler_info(iso: str | Path) -> InfoISO:
    """O código do jogo (do SYSTEM.CNF), o volume e o tamanho. ErroPatch se não é uma imagem de disco."""
    iso = Path(iso)
    if not iso.is_file():
        raise ErroPatch(f"não achei a ISO: {iso}")
    info = InfoISO(iso, iso.stat().st_size)
    with open(iso, "rb") as f:
        formato = _formato_iso(f)
        if formato is None:
            raise ErroPatch(f"{iso.name} não parece uma imagem de disco (ISO 9660). Use a ISO tirada do seu disco")
        info.volume = _ler(f, formato, 16, 2048)[40:72].decode("ascii", "replace").strip()
        arquivos = _arquivos_da_raiz(f, formato)
        if "SYSTEM.CNF" in arquivos:
            lba, tamanho = arquivos["SYSTEM.CNF"]
            texto = _ler(f, formato, lba, min(tamanho, 4096)).decode("ascii", "replace")
            achado = re.search(r"^\s*(BOOT2?)\s*=\s*cdrom0?:\\?([A-Z]{4}[_-]\d{3}\.\d{2})", texto, re.M | re.I)
            if achado:
                info.sistema = "PS2" if achado.group(1).upper() == "BOOT2" else "PS1"
                info.arquivo_boot = achado.group(2).upper()
                info.id_jogo = normalizar_id(info.arquivo_boot)
            versao = re.search(r"^\s*VER\s*=\s*([\d.]+)", texto, re.M | re.I)
            info.versao = versao.group(1) if versao else ""
    return info


def normalizar_id(texto: str) -> str:
    """'SLUS_209.46' / 'slus-20946' / 'SLUS20946' -> 'SLUS-20946'."""
    limpo = re.sub(r"[^A-Z0-9]", "", texto.upper())
    return f"{limpo[:4]}-{limpo[4:]}" if len(limpo) == 9 else texto.upper()


@dataclass
class Digital:
    """A "impressão digital" da ISO: muda se um único byte mudar."""
    crc32: str
    md5: str
    sha1: str

    def __str__(self) -> str:
        return f"CRC32 {self.crc32} · MD5 {self.md5}"


def impressao_digital(arquivo: str | Path, ao_progresso=None, parar=None) -> Digital:
    arquivo = Path(arquivo)
    total, lido, crc = max(1, arquivo.stat().st_size), 0, 0
    md5, sha1 = hashlib.md5(), hashlib.sha1()
    with open(arquivo, "rb") as f:
        while bloco := f.read(BLOCO):
            if parar and parar():
                raise ErroPatch("interrompido (botão Parar)")
            crc = zlib.crc32(bloco, crc)
            md5.update(bloco)
            sha1.update(bloco)
            lido += len(bloco)
            if ao_progresso:
                ao_progresso(lido / total)
    return Digital(f"{crc & 0xFFFFFFFF:08X}", md5.hexdigest().upper(), sha1.hexdigest().upper())


# ----------------------------------------------------------------- 2. o patch
@dataclass
class Esperado:
    """O que o leia-me do patch diz da ISO certa (e de que jogo é)."""
    crc32: set = field(default_factory=set)
    md5: set = field(default_factory=set)
    sha1: set = field(default_factory=set)
    ids: set = field(default_factory=set)
    arquivos: list = field(default_factory=list)

    def tem_digital(self) -> bool:
        return bool(self.crc32 or self.md5 or self.sha1)

    def confere(self, d: Digital) -> bool:
        """Alguma das impressões do leia-me bate (o leia-me às vezes traz a da original E a da traduzida)."""
        return d.crc32 in self.crc32 or d.md5 in self.md5 or d.sha1 in self.sha1

    def descrever(self) -> str:
        partes = [f"{nome} {', '.join(sorted(v))}" for nome, v in (("CRC32", self.crc32), ("MD5", self.md5),
                                                                   ("SHA-1", self.sha1)) if v]
        return " · ".join(partes)


_CRC = re.compile(r"CRC[-\s]?(?:32)?\s*(?:\(.{0,12}\))?\s*[:=]?\s*(?:0x)?([0-9a-f]{8})\b", re.I)
_MD5 = re.compile(r"(?<![0-9a-f])([0-9a-f]{32})(?![0-9a-f])", re.I)
_SHA1 = re.compile(r"(?<![0-9a-f])([0-9a-f]{40})(?![0-9a-f])", re.I)
_ID = re.compile(r"\b(S[CL][A-Z]{2}[-_ ]?\d{3}\.?\d{2}|U[LC][A-Z]{2}[-_ ]?\d{5}|NP[A-Z]{2}[-_ ]?\d{5})\b", re.I)


def esperado_no_texto(texto: str, esperado: Esperado | None = None) -> Esperado:
    esperado = esperado or Esperado()
    esperado.crc32 |= {c.upper() for c in _CRC.findall(texto)}
    esperado.md5 |= {m.upper() for m in _MD5.findall(texto)}
    esperado.sha1 |= {s.upper() for s in _SHA1.findall(texto)}
    esperado.ids |= {normalizar_id(i) for i in _ID.findall(texto)}
    return esperado


def esperado_do_leia_me(patch: str | Path) -> Esperado:
    """Lê os textos ao lado do patch (leia-me, .txt, .nfo, .diz) e o FILE_ID.DIZ de dentro do .ppf."""
    patch = Path(patch)
    esperado = Esperado()
    for arquivo in sorted(patch.parent.iterdir()) if patch.parent.is_dir() else []:
        if arquivo.suffix.lower() in (".txt", ".nfo", ".diz", ".md") and arquivo.stat().st_size <= 512 * 1024:
            try:
                texto = arquivo.read_bytes().decode("utf-8", "replace")
            except OSError:
                continue
            antes = (len(esperado.crc32), len(esperado.md5), len(esperado.sha1), len(esperado.ids))
            esperado_no_texto(texto, esperado)
            if (len(esperado.crc32), len(esperado.md5), len(esperado.sha1), len(esperado.ids)) != antes:
                esperado.arquivos.append(arquivo.name)
    if tipo_do_patch(patch) == PPF:
        diz = ler_ppf(patch).diz
        if diz:
            esperado_no_texto(diz, esperado)
            esperado.arquivos.append("FILE_ID.DIZ (dentro do .ppf)")
    return esperado


def tipo_do_patch(patch: str | Path) -> str:
    """XDELTA ou PPF, pelo começo do arquivo (não pela extensão). ErroPatch explicando, se não for patch."""
    patch = Path(patch)
    if not patch.is_file():
        raise ErroPatch(f"não achei o patch: {patch}")
    with open(patch, "rb") as f:
        inicio = f.read(5)
    if inicio[:3] == MAGICA_VCDIFF:
        return XDELTA
    if inicio in (b"PPF10", b"PPF20", b"PPF30"):
        return PPF
    if inicio == b"PATCH":
        return IPS
    if inicio[:4] == b"BPS1":
        return BPS
    if patch.suffix.lower() in EXTENSOES_ISO or patch.stat().st_size > 1024 ** 3:
        raise ErroPatch("isso parece um jogo inteiro, não um patch. O patch é um arquivo pequeno (.xdelta, .ppf, "
                        ".ips ou .bps) que o grupo de tradução distribui")
    raise ErroPatch(f"{patch.name} não é um patch .xdelta, .ppf, .ips nem .bps (se veio num .zip/.rar/.7z, extraia "
                    "antes)")


# ---- IPS (o formato mais antigo: trocas de até 16 MB do começo do arquivo) e BPS (com a impressão da original)
def aplicar_ips(patch: str | Path, destino: str | Path, ao_progresso=None, parar=None) -> None:
    """Aplica o .ips no destino (já uma CÓPIA da ISO): cada troca diz onde (3 bytes) e quanto (2 bytes); tamanho 0
    é uma sequência do mesmo byte (RLE). No fim, "EOF" e, às vezes, o tamanho final (corta o arquivo)."""
    dados = Path(patch).read_bytes()
    if dados[:5] != b"PATCH":
        raise ErroPatch(f"{Path(patch).name}: não é um .ips")
    pos, trocas = 5, 0
    with open(destino, "r+b") as d:
        while pos + 3 <= len(dados):
            if dados[pos:pos + 3] == b"EOF" and pos + 3 in (len(dados), len(dados) - 3):
                if pos + 6 == len(dados):
                    d.truncate(int.from_bytes(dados[pos + 3:pos + 6], "big"))
                break
            if pos + 5 > len(dados):
                raise ErroPatch("o .ips está cortado (baixe de novo)")
            onde, n = int.from_bytes(dados[pos:pos + 3], "big"), int.from_bytes(dados[pos + 3:pos + 5], "big")
            pos += 5
            if n:
                trecho = dados[pos:pos + n]
                pos += n
            else:
                repete, valor = int.from_bytes(dados[pos:pos + 2], "big"), dados[pos + 2:pos + 3]
                trecho = valor * repete
                pos += 3
            d.seek(onde)
            d.write(trecho)
            trocas += 1
            if trocas % 4096 == 0:
                if parar and parar():
                    raise ErroPatch("interrompido (botão Parar)")
                if ao_progresso:
                    ao_progresso(pos / len(dados))
        else:
            raise ErroPatch("o .ips está cortado (falta o fim \"EOF\"; baixe de novo)")


def _numero_bps(dados: bytes, pos: int) -> tuple[int, int]:
    """O número de tamanho variável do BPS (7 bits por byte; o bit alto marca o último)."""
    valor, deslocamento = 0, 1
    while True:
        if pos >= len(dados):
            raise ErroPatch("o .bps está cortado (baixe de novo)")
        x = dados[pos]
        pos += 1
        valor += (x & 0x7F) * deslocamento
        if x & 0x80:
            return valor, pos
        deslocamento <<= 7
        valor += deslocamento


def info_bps(patch: str | Path) -> dict:
    """{"origem": tamanho, "destino": tamanho, "crc_origem": "8 hex", "crc_destino": ..., "texto": metadados}."""
    dados = Path(patch).read_bytes()
    if dados[:4] != b"BPS1" or len(dados) < 16:
        raise ErroPatch(f"{Path(patch).name}: não é um .bps")
    origem, pos = _numero_bps(dados, 4)
    destino, pos = _numero_bps(dados, pos)
    n_meta, pos = _numero_bps(dados, pos)
    crc_o, crc_d, crc_p = struct.unpack_from("<III", dados, len(dados) - 12)
    if zlib.crc32(dados[:-4]) & 0xFFFFFFFF != crc_p:
        raise ErroPatch("o .bps está estragado (a conferência dele mesmo não bateu; baixe de novo)")
    return {"origem": origem, "destino": destino, "crc_origem": f"{crc_o:08X}", "crc_destino": f"{crc_d:08X}",
            "texto": dados[pos:pos + n_meta].decode("utf-8", "replace"), "inicio": pos + n_meta}


def aplicar_bps(patch: str | Path, origem: str | Path, destino: str | Path, ao_progresso=None, parar=None) -> None:
    """Monta o destino a partir da ISO original + o .bps. O BPS traz a impressão (CRC32) da original E da nova: o
    Maestro confere as duas (a de outra versão do jogo não passa)."""
    info = info_bps(patch)
    origem, destino = Path(origem), Path(destino)
    if origem.stat().st_size != info["origem"]:
        raise ErroPatch(f"o patch é para uma ISO de {info['origem']} bytes e a sua tem {origem.stat().st_size}: é "
                        "outra versão do jogo")
    crc = 0
    with open(origem, "rb") as o:
        while bloco := o.read(BLOCO):
            crc = zlib.crc32(bloco, crc)
    if f"{crc & 0xFFFFFFFF:08X}" != info["crc_origem"]:
        raise ErroPatch("a sua ISO não é a versão do patch (a impressão CRC32 que o .bps pede não bateu). Procure "
                        "o patch feito para a sua")
    dados = Path(patch).read_bytes()
    pos, fim = info["inicio"], len(dados) - 12
    saida_pos = rel_origem = rel_destino = 0
    with open(origem, "rb") as o, open(destino, "w+b") as d:
        while pos < fim:
            comando, pos = _numero_bps(dados, pos)
            acao, n = comando & 3, (comando >> 2) + 1
            if acao == 0:                                  # o mesmo pedaço da original, no mesmo lugar
                o.seek(saida_pos)
                d.write(o.read(n))
            elif acao == 1:                                # bytes novos, do próprio patch
                d.write(dados[pos:pos + n])
                pos += n
            else:
                desloc, pos = _numero_bps(dados, pos)
                desloc = -(desloc >> 1) if desloc & 1 else desloc >> 1
                if acao == 2:                              # um pedaço de outro lugar da original
                    rel_origem += desloc
                    o.seek(rel_origem)
                    d.write(o.read(n))
                    rel_origem += n
                else:                                      # um pedaço do que já foi escrito (pode se repetir)
                    rel_destino += desloc
                    falta = n
                    while falta:
                        d.seek(rel_destino)
                        pedaco = d.read(min(falta, saida_pos + (n - falta) - rel_destino, BLOCO))
                        d.seek(0, os.SEEK_END)
                        d.write(pedaco)
                        rel_destino += len(pedaco)
                        falta -= len(pedaco)
            saida_pos += n
            d.seek(saida_pos)
            if parar and parar():
                raise ErroPatch("interrompido (botão Parar)")
            if ao_progresso and saida_pos % (64 * 1024 * 1024) < n:
                ao_progresso(saida_pos / max(1, info["destino"]))
        d.flush()
        d.seek(0)
        crc = 0
        while bloco := d.read(BLOCO):
            crc = zlib.crc32(bloco, crc)
    if f"{crc & 0xFFFFFFFF:08X}" != info["crc_destino"]:
        raise ErroPatch("a ISO nova não saiu como o grupo publicou (a impressão não bateu): o patch está estragado")


# ---- PPF (Playstation Patch File 1.0, 2.0 e 3.0): aplicado aqui mesmo
@dataclass
class InfoPpf:
    versao: int
    descricao: str
    inicio: int                 # onde começam as trocas
    fim: int                    # onde acabam (antes do FILE_ID.DIZ)
    bloco: bytes | None = None  # 1024 bytes que a ISO certa tem (para conferir a versão)
    onde_bloco: int = 0x9320
    tamanho_original: int = 0   # (PPF 2.0) o tamanho da ISO certa
    desfazer: bool = False      # (PPF 3.0) cada troca traz também o original (pula)
    diz: str = ""


def ler_ppf(patch: str | Path) -> InfoPpf:
    patch = Path(patch)
    total = patch.stat().st_size
    with open(patch, "rb") as f:
        cab = f.read(60)
        if len(cab) < 56 or cab[:3] != b"PPF":
            raise ErroPatch(f"{patch.name}: não é um .ppf")
        versao = int(cab[3:4])
        info = InfoPpf(versao, cab[6:56].decode("latin-1").strip(" \x00"), 56, total)
        if versao == 2:
            info.tamanho_original = struct.unpack_from("<I", cab, 56)[0]
            f.seek(60)
            info.bloco, info.inicio = f.read(1024), 1084
        elif versao == 3:
            tipo_imagem, com_bloco, info.desfazer = cab[56], cab[57], bool(cab[58])
            info.onde_bloco = 0x80A0 if tipo_imagem == 1 else 0x9320
            info.inicio = 60
            if com_bloco:
                f.seek(60)
                info.bloco, info.inicio = f.read(1024), 1084
        # FILE_ID.DIZ no fim: "@BEGIN_FILE_ID.DIZ" texto "@END_FILE_ID.DIZ" + o tamanho do texto (2 ou 4 bytes)
        f.seek(max(0, total - 24))
        rabo = f.read()
        for largura in (2, 4):
            fim_marca = len(rabo) - largura
            if fim_marca >= 16 and rabo[fim_marca - 16:fim_marca] == b"@END_FILE_ID.DIZ":
                tamanho = int.from_bytes(rabo[fim_marca:], "little")
                comeco = total - largura - 16 - tamanho - 18
                if comeco >= info.inicio:
                    f.seek(comeco)
                    if f.read(18) == b"@BEGIN_FILE_ID.DIZ":
                        info.diz = f.read(tamanho).decode("latin-1", "replace")
                        info.fim = comeco
                        break
    return info


def _trocas_ppf(info: InfoPpf, f):
    """(onde, bytes) de cada troca do .ppf."""
    largura = 8 if info.versao == 3 else 4
    f.seek(info.inicio)
    pos = info.inicio
    while pos < info.fim:
        cab = f.read(largura + 1)
        if len(cab) < largura + 1:
            raise ErroPatch("o .ppf está cortado (baixe de novo)")
        onde, n = int.from_bytes(cab[:largura], "little"), cab[largura]
        dados = f.read(n)
        if info.desfazer:
            f.seek(n, os.SEEK_CUR)
        pos += largura + 1 + n * (2 if info.desfazer else 1)
        yield onde, dados


def aplicar_ppf(patch: str | Path, destino: str | Path, ao_progresso=None, parar=None) -> None:
    """Aplica o .ppf no arquivo destino (já uma CÓPIA da ISO). Confere a versão antes, se o .ppf traz o bloco."""
    info = ler_ppf(patch)
    destino = Path(destino)
    tamanho = destino.stat().st_size
    with open(patch, "rb") as p, open(destino, "r+b") as d:
        if info.tamanho_original and info.tamanho_original != tamanho:
            raise ErroPatch(f"a ISO tem {tamanho} bytes e o patch é para uma de {info.tamanho_original}: é outra "
                            "versão do jogo (outra região ou outra edição)")
        if info.bloco:
            d.seek(info.onde_bloco)
            if d.read(1024) != info.bloco:
                raise ErroPatch("o .ppf conferiu um pedaço da ISO e não bateu: é outra versão do jogo (outra região "
                                "ou outra edição). Procure o patch feito para a sua")
        vistos = 0
        for onde, dados in _trocas_ppf(info, p):
            if onde + len(dados) > tamanho:
                raise ErroPatch("o patch mexe depois do fim da sua ISO: é para outra versão do jogo")
            d.seek(onde)
            d.write(dados)
            vistos += 1
            if vistos % 4096 == 0:
                if parar and parar():
                    raise ErroPatch("interrompido (botão Parar)")
                if ao_progresso:
                    ao_progresso(min(1.0, p.tell() / max(1, info.fim)))


# ---- xdelta3 (o programa oficial)
def programa_xdelta(pasta: str | Path, sistema: str = sys.platform, baixar=_baixar) -> Path:
    """O xdelta3: o do sistema (Linux: apt install xdelta3) ou, no Windows, o oficial baixado uma vez (~0,2 MB,
    conferido pela impressão digital) para a pasta das ferramentas."""
    if sistema != "win32" and (achado := shutil.which("xdelta3")):
        return Path(achado)
    exe = Path(pasta) / "xdelta3" / ("xdelta3.exe" if sistema == "win32" else "xdelta3")
    if exe.is_file():
        return exe
    if sistema != "win32":
        raise ErroPatch("falta o xdelta3 neste sistema (no Linux: sudo apt install xdelta3)")
    exe.parent.mkdir(parents=True, exist_ok=True)
    pacote = exe.parent / "xdelta3.zip"
    baixar(URL_XDELTA, pacote, None)
    try:
        if hashlib.sha256(pacote.read_bytes()).hexdigest() != SHA256_XDELTA:
            raise ErroPatch("o xdelta3 baixado não é o oficial (a impressão digital não bateu); tente de novo")
        with zipfile.ZipFile(pacote) as z:
            nome = next((n for n in z.namelist() if n.lower().endswith(".exe")), None)
            if nome is None:
                raise ErroPatch("o pacote do xdelta3 não tinha o programa")
            exe.write_bytes(z.read(nome))
    except zipfile.BadZipFile as erro:
        raise ErroPatch(f"o pacote do xdelta3 veio estragado ({erro}); tente de novo") from erro
    finally:
        pacote.unlink(missing_ok=True)
    return exe


ERROS_XDELTA = (("checksum mismatch", "o patch não bate com a sua ISO: é outra versão do jogo (outra região ou "
                 "outra edição). Procure o patch feito para a sua"),
                ("source file too short", "o patch é para uma ISO maior: é outra versão do jogo"),
                ("not a vcdiff", "o arquivo não é um patch xdelta válido (baixe de novo)"),
                ("unexpected end", "o patch está cortado (baixe de novo)"),
                ("no space", "faltou espaço no disco"))


def _rodar_xdelta(argumentos: list, crescendo: Path, esperado: int, ao_progresso, parar, abrir) -> None:
    """Roda o xdelta3 mostrando o andamento (o tamanho do arquivo que ele está escrevendo) e com o Parar."""
    processo = abrir([str(a) for a in argumentos], stdout=subprocess.PIPE, stderr=subprocess.PIPE, **SEM_JANELA)
    saida: dict = {}
    leitor = threading.Thread(target=lambda: saida.update(err=processo.stderr.read()), daemon=True)
    leitor.start()
    while processo.poll() is None:
        if parar and parar():
            processo.kill()
            raise ErroPatch("interrompido (botão Parar)")
        if ao_progresso and crescendo.exists():
            ao_progresso(min(0.99, crescendo.stat().st_size / max(1, esperado)))
        time.sleep(0.3)
    leitor.join(timeout=5)
    if processo.returncode != 0:
        detalhe = (saida.get("err") or b"").decode("utf-8", "replace").strip()
        motivo = next((texto for chave, texto in ERROS_XDELTA if chave in detalhe.lower()), None)
        ultima = detalhe.splitlines()[-1] if detalhe else f"código {processo.returncode}"
        raise ErroPatch(motivo or f"o xdelta3 não conseguiu: {ultima}")


# ----------------------------------------------------------------- 3. aplicar (numa cópia) e criar
def nome_para_o_opl(info: InfoISO, titulo: str) -> str:
    """'SLUS_209.46.Meu Jogo PT-BR.iso' (o padrão do OPL; o nome tem até 32 letras)."""
    titulo = re.sub(r'[<>:"/\\|?*.]+', " ", titulo).strip()[:32].strip() or "Jogo"
    return f"{info.arquivo_boot}.{titulo}.iso" if info.arquivo_boot else f"{titulo}.iso"


def conferir_espaco(pasta: str | Path, precisa: int) -> None:
    alvo = Path(pasta).absolute()
    while not alvo.exists() and alvo.parent != alvo:
        alvo = alvo.parent
    try:
        livre = shutil.disk_usage(alvo).free
    except OSError:
        return
    if livre < precisa:
        raise ErroPatch(f"falta espaço no disco {alvo.anchor or alvo}: a ISO nova precisa de "
                        f"{tamanho_legivel(precisa)} e há {tamanho_legivel(livre)} livres")


@dataclass
class Resultado:
    destino: Path
    info: InfoISO
    tipo: str
    conferido: str            # "bateu com o leia-me", "o próprio patch conferiu" ou "sem como conferir"


def aplicar(iso: str | Path, patch: str | Path, destino: str | Path, pasta_ferramentas: str | Path,
            digital: Digital | None = None, esperado: Esperado | None = None, ao_progresso=None, parar=None,
            abrir=subprocess.Popen, baixar=_baixar, sistema: str = sys.platform, identificar=None) -> Resultado:
    """Aplica o patch numa CÓPIA da ISO (destino). Com o leia-me trazendo a impressão digital (esperado) e a da
    ISO já medida (digital), confere ANTES: não bate, não aplica. O destino só ganha o nome final no fim (sem ISO
    pela metade com o nome certo). identificar: como ler o jogo (o PS1/PS2 por padrão; os outros consoles têm o
    deles em consoles.py: a ROM do SNES, a ISO do PSP...)."""
    identificar = identificar or ler_info
    iso, patch, destino = Path(iso), Path(patch), Path(destino)
    info = identificar(iso)
    tipo = tipo_do_patch(patch)
    if destino.resolve() == iso.resolve():
        raise ErroPatch("escolha outro nome para a ISO nova: a original fica como está")
    if esperado is not None and esperado.tem_digital() and digital is not None and not esperado.confere(digital):
        raise ErroPatch(f"a sua ISO não é a versão do patch: o leia-me pede {esperado.descrever()} e a sua é "
                        f"{digital}. Procure o patch feito para a sua versão")
    conferir_espaco(destino.parent, info.tamanho + FOLGA_DISCO)
    destino.parent.mkdir(parents=True, exist_ok=True)
    parcial = destino.with_name(destino.name + ".parcial")
    parcial.unlink(missing_ok=True)
    progresso = ao_progresso or (lambda f: None)
    try:
        if tipo in (PPF, IPS):
            _copiar(iso, parcial, lambda f: progresso(0.6 * f), parar)
            (aplicar_ppf if tipo == PPF else aplicar_ips)(patch, parcial, lambda f: progresso(0.6 + 0.4 * f), parar)
        elif tipo == BPS:
            aplicar_bps(patch, iso, parcial, progresso, parar)
        else:
            xdelta = programa_xdelta(pasta_ferramentas, sistema, baixar)
            _rodar_xdelta([xdelta, "-d", "-f", "-s", iso, patch, parcial], parcial, info.tamanho, progresso, parar,
                          abrir)
        nova = identificar(parcial)                      # a ISO nova ainda é um disco (que o OPL lê)
    except BaseException:
        parcial.unlink(missing_ok=True)
        raise
    os.replace(parcial, destino)
    nova.caminho = destino
    progresso(1.0)
    conferido = ("bateu com o leia-me" if esperado is not None and esperado.tem_digital() and digital is not None
                 else "o próprio patch conferiu" if tipo in (XDELTA, BPS) or (tipo == PPF and ler_ppf(patch).bloco)
                 else "sem como conferir")
    return Resultado(destino, nova, tipo, conferido)


def _copiar(origem: Path, destino: Path, ao_progresso, parar) -> None:
    total, copiado = max(1, origem.stat().st_size), 0
    with open(origem, "rb") as o, open(destino, "wb") as d:
        while bloco := o.read(BLOCO):
            if parar and parar():
                raise ErroPatch("interrompido (botão Parar)")
            d.write(bloco)
            copiado += len(bloco)
            ao_progresso(copiado / total)


def _numero_para_bps(n: int) -> bytes:
    """O contrário de _numero_bps: 7 bits por byte, o bit alto no último."""
    saida = bytearray()
    while True:
        x = n & 0x7F
        n >>= 7
        if n == 0:
            saida.append(0x80 | x)
            return bytes(saida)
        saida.append(x)
        n -= 1


def criar_bps(original: str | Path, modificada: str | Path, saida: str | Path, descricao: str = "",
              ao_progresso=None) -> Path:
    """O .bps da SUA tradução de uma ROM (o patch que os grupos usam no SNES, GBA, NES...): os trechos iguais viram
    "copie da original" e os diferentes vão no patch. Leva o CRC32 da original e da traduzida (quem aplica confere
    sozinho) e um leia-me ao lado. Não contém a ROM."""
    import numpy as np
    original, modificada, saida = Path(original), Path(modificada), Path(saida)
    if original.resolve() == modificada.resolve():
        raise ErroPatch("escolha a ROM modificada (a com a sua tradução), não a mesma original")
    fonte, alvo = original.read_bytes(), modificada.read_bytes()
    progresso = ao_progresso or (lambda f: None)
    acoes = bytearray()
    comum = min(len(fonte), len(alvo))
    iguais = np.frombuffer(fonte, np.uint8)[:comum] == np.frombuffer(alvo, np.uint8)[:comum]
    # os trechos: onde muda de igual para diferente (os iguais curtos, de menos de 4 bytes, vão junto com os diferentes)
    bordas = np.flatnonzero(np.diff(iguais.astype(np.int8))) + 1 if comum else np.array([], dtype=np.int64)
    inicios = np.concatenate([[0], bordas]).astype(np.int64) if comum else np.array([], dtype=np.int64)
    fins = np.concatenate([bordas, [comum]]).astype(np.int64) if comum else np.array([], dtype=np.int64)
    pos, diferente_desde = 0, None
    for k, (ini, fim) in enumerate(zip(inicios.tolist(), fins.tolist())):
        if iguais[ini] and fim - ini >= 4:
            if diferente_desde is not None:
                acoes += _numero_para_bps(((ini - diferente_desde - 1) << 2) | 1) + alvo[diferente_desde:ini]
                diferente_desde = None
            acoes += _numero_para_bps((fim - ini - 1) << 2)          # SourceRead: igual à original
        elif diferente_desde is None:
            diferente_desde = ini
        pos = fim
        if k % 4096 == 0:
            progresso(0.9 * pos / max(1, len(alvo)))
    if diferente_desde is not None or len(alvo) > comum:              # o que sobrou e o que a ROM ganhou no fim
        inicio = comum if diferente_desde is None else diferente_desde
        acoes += _numero_para_bps(((len(alvo) - inicio - 1) << 2) | 1) + alvo[inicio:]
    corpo = b"BPS1" + _numero_para_bps(len(fonte)) + _numero_para_bps(len(alvo)) + _numero_para_bps(0) + bytes(acoes)
    corpo += struct.pack("<II", zlib.crc32(fonte), zlib.crc32(alvo))
    saida.parent.mkdir(parents=True, exist_ok=True)
    saida.write_bytes(corpo + struct.pack("<I", zlib.crc32(corpo)))
    saida.with_name(saida.stem + " - leia-me.txt").write_text(
        f"{descricao or saida.stem}\n\nAplique na ROM do SEU cartucho, que deve ter esta impressão digital:\n"
        f"  CRC32: {zlib.crc32(fonte):08X}\n  Tamanho: {len(fonte)} bytes\n\n"
        "Como aplicar: Maestro > 🎮 Jogos > Nintendo clássicos > Aplicar patch (ou Floating IPS / beat).\n"
        "O .bps confere sozinho a ROM original e a traduzida. Este arquivo traz só as diferenças: não contém o "
        "jogo.\n", encoding="utf-8")
    progresso(1.0)
    return saida


def criar_patch(original: str | Path, modificada: str | Path, saida: str | Path, pasta_ferramentas: str | Path,
                descricao: str = "", ao_progresso=None, parar=None, abrir=subprocess.Popen, baixar=_baixar,
                sistema: str = sys.platform) -> Path:
    """O .xdelta da SUA tradução (as diferenças entre a ISO original e a modificada) + um leia-me com a impressão
    digital da original, para quem for aplicar conferir. Compartilhe só o patch, nunca a ISO."""
    original, modificada, saida = Path(original), Path(modificada), Path(saida)
    info, nova = ler_info(original), ler_info(modificada)
    if original.resolve() == modificada.resolve():
        raise ErroPatch("escolha a ISO modificada (a com a sua tradução), não a mesma original")
    progresso = ao_progresso or (lambda f: None)
    digital = impressao_digital(original, lambda f: progresso(0.3 * f), parar)
    saida.parent.mkdir(parents=True, exist_ok=True)
    parcial = saida.with_name(saida.name + ".parcial")
    xdelta = programa_xdelta(pasta_ferramentas, sistema, baixar)
    try:
        # -B: a "janela" de 256 MB da original (a mudança longe no disco ainda vira cópia, e o patch fica pequeno)
        _rodar_xdelta([xdelta, "-e", "-9", "-S", "djw", "-B", str(JANELA_XDELTA), "-f", "-s", original, modificada,
                       parcial], parcial,
                      max(1, nova.tamanho // 20), lambda f: progresso(0.3 + 0.7 * f), parar, abrir)
    except BaseException:
        parcial.unlink(missing_ok=True)
        raise
    os.replace(parcial, saida)
    leia_me = saida.with_name(saida.stem + " - leia-me.txt")
    leia_me.write_text(
        f"{descricao or saida.stem}\n\n"
        f"Patch para: {info.id_jogo or '(código não encontrado)'} {info.regiao} {info.volume}\n"
        f"Aplique na ISO do SEU disco, que deve ter esta impressão digital:\n"
        f"  CRC32: {digital.crc32}\n  MD5:   {digital.md5}\n  SHA-1: {digital.sha1}\n"
        f"  Tamanho: {info.tamanho} bytes\n\n"
        "Como aplicar: Maestro > 🎮 Jogos > Aplicar patch (ou xdelta UI / Delta Patcher).\n"
        "Este arquivo traz só as diferenças: não contém o jogo.\n", encoding="utf-8")
    progresso(1.0)
    return saida


def busca_na_comunidade(info: InfoISO, nome: str = "") -> str:
    """O endereço da busca de PATCHES de tradução do jogo (PO.B.R.E e Romhacking.net), no navegador."""
    from urllib.parse import quote_plus
    termos = " ".join(t for t in (nome.strip(), f'"{info.id_jogo}"' if info.id_jogo else "") if t) or info.volume
    pergunta = f"{termos} tradução PT-BR patch (site:romhackers.org OR site:romhacking.net)"
    return "https://www.google.com/search?q=" + quote_plus(pergunta)


# ----------------------------------------------------------------- o que o leia-me conta
@dataclass
class LeiaMe:
    arquivo: Path | None = None
    o_que_traz: list = field(default_factory=list)   # ["textos e menus em português", "vozes dubladas", ...]
    creditos: str = ""                                # "Grupo Exemplo · versão 1.2"


_TRAZ = (("textos", r"\btexto|\btradu[çc][ãa]o (?:completa|dos textos|do jogo)|\bdi[áa]logo|\blegenda"),
         ("menus", r"\bmenu"),
         ("vozes dubladas", r"\bdublag|\bdublad|\bvozes\b|\b[áa]udio em portugu"),
         ("letras com ç e acentos", r"\bacentua|\bacentos?\b|\bç\b|cedilha|\bfonte"),
         ("gráficos traduzidos", r"\bgr[áa]fico|\btextura|\bimage(?:m|ns)\b|\blogo"))
_VERSAO = re.compile(r"\b(?:v(?:ers[ãa]o)?\.?\s?)(\d+(?:\.\d+){0,3}[a-z]?)\b", re.I)
_GRUPO = re.compile(r"(?:grupo|equipe|team|tradu[çz]ido por|tradu[çc][ãa]o(?: feita)? por|translated by|"
                    r"hack(?:ing)? por|criado por|by)\s*[:\-]?\s*([^\n\r|·]{2,60})", re.I)


def leia_me(patch: str | Path) -> LeiaMe:
    """O leia-me ao lado do patch: o que ele traz (textos, menus, vozes, acentos) e os créditos (grupo e versão)."""
    patch = Path(patch)
    textos = []
    for arquivo in sorted(patch.parent.iterdir()) if patch.parent.is_dir() else []:
        if arquivo.suffix.lower() in (".txt", ".nfo", ".diz", ".md") and arquivo.stat().st_size <= 512 * 1024:
            try:
                textos.append((arquivo, arquivo.read_bytes().decode("utf-8", "replace")))
            except OSError:
                continue
    if tipo_do_patch(patch) == PPF and ler_ppf(patch).diz:
        textos.append((None, ler_ppf(patch).diz))
    principal = next((a for a, _ in textos if a is not None and re.search(r"leia|readme|ler|info", a.stem, re.I)),
                     next((a for a, _ in textos if a is not None), None))
    tudo = "\n".join(t for _, t in textos)
    info = LeiaMe(principal, [nome for nome, padrao in _TRAZ if re.search(padrao, tudo, re.I)])
    grupo = _GRUPO.search(tudo)
    versao = _VERSAO.search(tudo) or _VERSAO.search(patch.stem)
    partes = [grupo.group(1).strip(" .:-") if grupo else "", f"versão {versao.group(1)}" if versao else ""]
    info.creditos = " · ".join(p for p in partes if p)
    return info


# ----------------------------------------------------------------- abrir no PCSX2
def achar_pcsx2(escolhido: str = "", sistema: str = sys.platform) -> Path | None:
    """O PCSX2 deste PC: o escolhido nas configurações ou os lugares de sempre (Arquivos de Programas, a pasta do
    usuário, o PATH)."""
    if escolhido and Path(escolhido).is_file():
        return Path(escolhido)
    nomes = ("pcsx2-qt.exe", "pcsx2.exe", "pcsx2x64.exe") if sistema == "win32" else ("pcsx2-qt", "pcsx2",
                                                                                     "PCSX2.AppImage")
    for nome in nomes:
        if achado := shutil.which(nome):
            return Path(achado)
    if sistema == "win32":
        bases = [os.environ.get(v, "") for v in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA")]
        for base in filter(None, bases):
            for pasta in ("PCSX2", "PCSX2 Nightly", "Programs/PCSX2", "Programs/pcsx2"):
                for nome in nomes:
                    if (Path(base) / pasta / nome).is_file():
                        return Path(base) / pasta / nome
    return None


def abrir_no_pcsx2(iso: str | Path, pcsx2: str | Path, abrir=subprocess.Popen):
    """Liga o jogo no PCSX2 (o emulador abre a ISO direto)."""
    return abrir([str(pcsx2), str(iso)])


# ----------------------------------------------------------------- os patches aplicados (para refazer ou apagar)
def carregar_aplicados(arquivo: str | Path) -> list[dict]:
    try:
        dados = json.loads(Path(arquivo).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [d for d in dados if isinstance(d, dict) and d.get("destino")]


def registrar_aplicado(arquivo: str | Path, iso: Path, patch: Path, destino: Path, conferido: str) -> list[dict]:
    """Guarda o patch aplicado (o mais novo primeiro; a mesma ISO nova aparece uma vez só)."""
    from datetime import datetime
    lista = [d for d in carregar_aplicados(arquivo) if d["destino"] != str(destino)]
    lista.insert(0, {"quando": datetime.now().strftime("%d/%m/%Y %H:%M"), "iso": str(iso), "patch": str(patch),
                     "destino": str(destino), "conferido": conferido})
    Path(arquivo).parent.mkdir(parents=True, exist_ok=True)
    Path(arquivo).write_text(json.dumps(lista[:200], ensure_ascii=False, indent=1), encoding="utf-8")
    return lista
