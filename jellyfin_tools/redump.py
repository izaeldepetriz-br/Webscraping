"""O banco Redump (redump.org): a impressão digital de cada disco original de PS2 e PS1, conferida por quem
preserva jogos. Se a sua ISO tem a mesma impressão de um disco do banco, ela é uma cópia PERFEITA do disco (nenhum
byte diferente): o patch feito para aquele disco encaixa.

A lista (o "DAT" do Redump, ~1,3 MB) é baixada uma vez e guardada como um índice pequeno junto das configurações;
depois de VALIDADE_DIAS ela é atualizada (discos novos entram no banco).
"""

from __future__ import annotations

import json
import time
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from .dublagem import _baixar
from .patch_jogo import ErroPatch

URLS = {"PS2": "http://redump.org/datfile/ps2/", "PS1": "http://redump.org/datfile/psx/",
        "PSP": "http://redump.org/datfile/psp/", "GC": "http://redump.org/datfile/gc/",
        "Wii": "http://redump.org/datfile/wii/"}
VALIDADE_DIAS = 30


def _ler_dat(dados: bytes) -> dict:
    """{"md5": {md5: nome}, "crc": {"crc32:tamanho": nome}, "versao": ...} das faixas .iso/.bin do DAT."""
    indice = {"md5": {}, "crc": {}, "versao": ""}
    raiz = ET.fromstring(dados)
    versao = raiz.find("header/version")
    indice["versao"] = versao.text if versao is not None else ""
    for jogo in raiz.iter("game"):
        nome = jogo.get("name", "")
        for rom in jogo.iter("rom"):
            if not rom.get("name", "").lower().endswith((".iso", ".bin")):
                continue
            if rom.get("md5"):
                indice["md5"][rom.get("md5").upper()] = nome
            if rom.get("crc") and rom.get("size"):
                indice["crc"][f"{rom.get('crc').upper()}:{rom.get('size')}"] = nome
    return indice


def indice(sistema: str, pasta: str | Path, baixar=_baixar, agora=time.time) -> dict:
    """O índice do banco do sistema ("PS2" ou "PS1"), baixando a lista se ainda não tem (ou se está velha)."""
    if sistema not in URLS:
        raise ErroPatch(f"o banco Redump do Maestro tem só PS2 e PS1 (não {sistema or 'este disco'})")
    pasta = Path(pasta)
    arquivo = pasta / f"redump_{sistema.lower()}.json"
    if arquivo.is_file() and agora() - arquivo.stat().st_mtime < VALIDADE_DIAS * 86400:
        try:
            return json.loads(arquivo.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    pasta.mkdir(parents=True, exist_ok=True)
    pacote = pasta / f"redump_{sistema.lower()}.zip"
    try:
        baixar(URLS[sistema], pacote, None)
        with zipfile.ZipFile(pacote) as z:
            nome = next((n for n in z.namelist() if n.lower().endswith(".dat")), None)
            if nome is None:
                raise ErroPatch("a lista do Redump veio sem o arquivo .dat")
            dados = _ler_dat(z.read(nome))
    except (zipfile.BadZipFile, ET.ParseError) as erro:
        if arquivo.is_file():                       # sem internet ou o site fora do ar: fica com a anterior
            return json.loads(arquivo.read_text(encoding="utf-8"))
        raise ErroPatch(f"a lista do Redump veio estragada ({erro}); tente de novo mais tarde") from erro
    finally:
        pacote.unlink(missing_ok=True)
    arquivo.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    return dados


def procurar(indice_: dict, md5: str, crc32: str, tamanho: int) -> str | None:
    """O nome do disco no banco ("Burnout 3 - Takedown (USA)") se a ISO é uma cópia perfeita; None se não está."""
    return indice_["md5"].get(md5.upper()) or indice_["crc"].get(f"{crc32.upper()}:{tamanho}")
