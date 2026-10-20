"""Instalar a tradução dos jogos que não usam patch na imagem do disco (aba 🎮 Jogos, Nintendo Switch e PC), com
Desfazer; e criar a sua (o mod do Switch e o pacote do PC), para compartilhar.

    Switch   o mod de tradução (uma pasta ou um .zip com romfs/exefs e o TitleID do jogo) vai para a pasta de mods do
             emulador (<pasta>/<TitleID>/<nome do mod>/romfs) ou para o cartão SD do Switch com Atmosphère
             (<SD>/atmosphere/contents/<TitleID>/romfs). O jogo não muda.
    PC       os arquivos da tradução (uma pasta ou um .zip) vão por cima da pasta do jogo; os que já existiam são
             guardados antes numa cópia de segurança (<jogo>/.maestro_original/...).

Desfazer apaga o que o Maestro copiou e devolve os arquivos originais. O registro fica em traducoes_instaladas.json
(junto das configurações). O Maestro não baixa jogos nem mods: sempre os arquivos que você escolhe.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from .patch_jogo import ErroPatch

TITLE_ID = re.compile(r"(?<![0-9A-Fa-f])(01[0-9A-Fa-f]{14})(?![0-9A-Fa-f])")
PARTES_MOD = ("romfs", "exefs")
EMULADOR, SD = "emulador", "sd"
COPIA_SEGURANCA = ".maestro_original"
LEIA_ME = re.compile(r"(leia|readme|leeme|instru|info)[^/]*\.(txt|md|nfo)$", re.I)
LIXO = re.compile(r"(^|/)(__MACOSX/|\._|\.DS_Store$|Thumbs\.db$|desktop\.ini$)", re.I)   # o que o Mac e o Windows põem


@dataclass
class Pacote:
    """O que veio na tradução: os arquivos (caminho dentro do pacote -> tamanho), sem a pasta de cima que só embrulha."""
    origem: Path
    arquivos: dict = field(default_factory=dict)       # "romfs/Message/Main.msbt" -> bytes
    raiz: str = ""                                     # o que é tirado da frente de cada caminho
    title_id: str = ""                                 # Switch: o código do jogo (0100...)
    partes: list = field(default_factory=list)         # Switch: ["romfs", "exefs"]
    leia_me: str = ""                                  # o texto do leia-me que veio junto

    @property
    def nome(self) -> str:
        return self.origem.stem if self.origem.suffix.lower() == ".zip" else self.origem.name

    @property
    def tamanho(self) -> int:
        return sum(self.arquivos.values())

    def destino_de(self, caminho: str) -> str:
        return caminho[len(self.raiz):] if self.raiz and caminho.startswith(self.raiz) else caminho


def _listar(origem: Path) -> dict[str, int]:
    """{caminho com "/": tamanho}. Os .zip feitos por programas antigos do Windows trazem "\\" no lugar da "/"; o
    lixo do Mac (__MACOSX, ._*) e do Windows (Thumbs.db, desktop.ini) não entra."""
    if origem.is_dir():
        arquivos = {p.relative_to(origem).as_posix(): p.stat().st_size for p in sorted(origem.rglob("*"))
                    if p.is_file()}
    elif origem.suffix.lower() == ".zip" and origem.is_file():
        try:
            with zipfile.ZipFile(origem) as z:
                arquivos = {i.filename.replace("\\", "/"): i.file_size for i in z.infolist()
                            if not i.is_dir() and not i.filename.endswith("\\")}
        except zipfile.BadZipFile as erro:
            raise ErroPatch(f"{origem.name} não é um .zip válido ({erro})") from erro
    else:
        raise ErroPatch(f"escolha a pasta ou o .zip da tradução (não achei {origem})")
    return {c: t for c, t in arquivos.items() if not LIXO.search(c)}


def _ler(origem: Path, caminho: str) -> bytes:
    if origem.is_dir():
        return (origem / caminho).read_bytes()
    with zipfile.ZipFile(origem) as z:
        try:
            return z.read(caminho)
        except KeyError:                                 # (o nome dentro do .zip está com "\\")
            return z.read(caminho.replace("/", "\\"))


def _liberar(arquivo: Path) -> None:
    """Tira o "somente leitura" (no Windows, os arquivos do jogo às vezes vêm assim e não deixam trocar)."""
    if arquivo.exists() and not os.access(arquivo, os.W_OK):
        os.chmod(arquivo, arquivo.stat().st_mode | stat.S_IWRITE)


def _apagar_pasta(pasta: Path) -> None:
    for arquivo in pasta.rglob("*"):
        if arquivo.is_file():
            _liberar(arquivo)
    shutil.rmtree(pasta, ignore_errors=True)


def _leia_me(origem: Path, arquivos: dict) -> str:
    for caminho in sorted(arquivos, key=lambda c: c.count("/")):
        if LEIA_ME.search(caminho) and arquivos[caminho] < 200_000:
            return _ler(origem, caminho).decode("utf-8", "replace").strip()
    return ""


def ler_mod(origem: str | Path) -> Pacote:
    """O mod de tradução do Switch: onde estão romfs/exefs e o TitleID (do caminho dentro do mod ou do nome)."""
    origem = Path(origem)
    arquivos = _listar(origem)
    pacote = Pacote(origem, arquivos, leia_me=_leia_me(origem, arquivos))
    bases = []
    for caminho in arquivos:
        partes = caminho.split("/")
        for i, parte in enumerate(partes[:-1]):
            if parte.lower() in PARTES_MOD:
                bases.append(("/".join(partes[:i]) + "/") if i else "")
                break
    if not bases:
        raise ErroPatch(f"{origem.name} não parece um mod do Switch: falta a pasta romfs (ou exefs)")
    pacote.raiz = min(bases, key=len)
    pacote.arquivos = {c: t for c, t in arquivos.items() if c.startswith(pacote.raiz)}
    pacote.partes = sorted({c[len(pacote.raiz):].split("/")[0].lower() for c in pacote.arquivos} & set(PARTES_MOD))
    achado = TITLE_ID.search(pacote.raiz) or TITLE_ID.search(origem.name) or next(
        (m for m in (TITLE_ID.search(c) for c in arquivos) if m), None)
    pacote.title_id = achado.group(1).upper() if achado else ""
    return pacote


def ler_pacote_pc(origem: str | Path, pasta_jogo: str | Path | None = None) -> Pacote:
    """Os arquivos da tradução do PC. A pasta de cima que só embrulha tudo ("Tradução PT-BR/...") sai, a não ser
    que o jogo tenha uma pasta com esse nome. Os leia-me não vão para a pasta do jogo."""
    origem = Path(origem)
    arquivos = _listar(origem)
    pacote = Pacote(origem, {c: t for c, t in arquivos.items() if not LEIA_ME.search(c)},
                    leia_me=_leia_me(origem, arquivos))
    if not pacote.arquivos:
        raise ErroPatch(f"{origem.name} não tem arquivos de tradução")
    primeiras = {c.split("/")[0] for c in pacote.arquivos}
    if len(primeiras) == 1 and all("/" in c for c in pacote.arquivos):
        unica = primeiras.pop()
        if pasta_jogo is None or not (Path(pasta_jogo) / unica).is_dir():
            pacote.raiz = unica + "/"
    return pacote


def destino_do_mod(pacote: Pacote, onde: str, pasta: str | Path, title_id: str = "") -> Path:
    """A pasta onde o mod fica: no emulador <pasta>/<TitleID>/<nome do mod>; no SD <SD>/atmosphere/contents/
    <TitleID> (se a pasta escolhida já é uma delas, não repete)."""
    title_id = (title_id or pacote.title_id).upper()
    if not TITLE_ID.fullmatch(title_id):
        raise ErroPatch("falta o TitleID do jogo (16 letras e números começando com 01: aparece no emulador, em "
                        "Propriedades do jogo, e costuma vir no nome do mod)")
    pasta = Path(pasta)
    if onde == SD:
        if pasta.name.lower() == title_id.lower():
            return pasta
        if pasta.name.lower() == "contents":
            return pasta / title_id
        return pasta / "atmosphere" / "contents" / title_id
    base = pasta if pasta.name.lower() == title_id.lower() else pasta / title_id
    return base / re.sub(r'[<>:"/\\|?*]+', " ", pacote.nome).strip()


@dataclass
class Instalacao:
    console: str
    nome: str
    destino: str                                        # a pasta (do mod ou do jogo)
    criados: list = field(default_factory=list)         # caminhos relativos ao destino, que não existiam
    trocados: list = field(default_factory=list)        # que existiam (o original está na cópia de segurança)
    copia: str = ""                                     # a pasta da cópia de segurança
    quando: str = ""
    criou_pasta: str = ""                               # a pasta mais de cima que não existia (Desfazer apaga)


def instalar(pacote: Pacote, destino: str | Path, console: str, ao_progresso=None, parar=None,
             separar_mod: bool = False) -> Instalacao:
    """Copia os arquivos do pacote para o destino. Os que já existiam vão antes para a cópia de segurança."""
    destino = Path(destino)
    agora = time.strftime("%Y-%m-%d %H:%M")
    copia = destino / COPIA_SEGURANCA / time.strftime("%Y%m%d-%H%M%S")
    feito = Instalacao(console, pacote.nome, str(destino), copia=str(copia), quando=agora)
    pasta = destino
    while not pasta.exists() and pasta.parent != pasta:  # (no Switch, a pasta do TitleID pode ser nova)
        feito.criou_pasta, pasta = str(pasta), pasta.parent
    progresso = ao_progresso or (lambda f: None)
    total = max(1, len(pacote.arquivos))
    try:
        for k, caminho in enumerate(pacote.arquivos):
            if parar and parar():
                raise ErroPatch("interrompido (botão Parar)")
            relativo = pacote.destino_de(caminho)
            alvo = destino / PurePosixPath(relativo)
            if destino.resolve() not in alvo.resolve().parents:
                raise ErroPatch(f"o pacote tem um caminho que sai da pasta: {caminho}")
            if alvo.exists():
                guardado = copia / PurePosixPath(relativo)
                guardado.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(alvo, guardado)
                feito.trocados.append(relativo)
            else:
                feito.criados.append(relativo)
            alvo.parent.mkdir(parents=True, exist_ok=True)
            _liberar(alvo)
            alvo.write_bytes(_ler(pacote.origem, caminho))
            progresso((k + 1) / total)
    except BaseException:
        desfazer(feito)                                  # pela metade não fica
        raise
    if not feito.trocados:
        feito.copia = ""
    return feito


def desfazer(feito: Instalacao) -> None:
    """Apaga o que foi copiado e devolve os originais (da cópia de segurança). As pastas que ficaram vazias saem."""
    destino = Path(feito.destino)
    for relativo in feito.criados:
        _liberar(destino / PurePosixPath(relativo))
        (destino / PurePosixPath(relativo)).unlink(missing_ok=True)
    if feito.copia:
        copia = Path(feito.copia)
        for relativo in feito.trocados:
            guardado = copia / PurePosixPath(relativo)
            if guardado.is_file():
                _liberar(destino / PurePosixPath(relativo))
                shutil.copy2(guardado, destino / PurePosixPath(relativo))     # (volta com o "somente leitura")
        _apagar_pasta(copia)
    pastas = {(destino / PurePosixPath(r)).parent for r in feito.criados + feito.trocados}
    pastas.add(destino / COPIA_SEGURANCA)
    limite = Path(feito.criou_pasta).parent if feito.criou_pasta else destino.parent
    for pasta in sorted(pastas, key=lambda p: len(p.parts), reverse=True):
        atual = pasta
        while atual != limite and atual.is_dir() and not any(atual.iterdir()):
            atual.rmdir()
            atual = atual.parent


# ----------------------------------------------------------------- o registro (Traduções instaladas)
def carregar(arquivo: str | Path) -> list[Instalacao]:
    try:
        dados = json.loads(Path(arquivo).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [Instalacao(**d) for d in dados if isinstance(d, dict) and d.get("destino")]


def registrar(arquivo: str | Path, feito: Instalacao) -> list[Instalacao]:
    lista = carregar(arquivo) + [feito]
    _gravar(arquivo, lista)
    return lista


def esquecer(arquivo: str | Path, feito: Instalacao) -> list[Instalacao]:
    lista = [i for i in carregar(arquivo) if (i.destino, i.quando, i.nome) != (feito.destino, feito.quando, feito.nome)]
    _gravar(arquivo, lista)
    return lista


def _gravar(arquivo: str | Path, lista: list[Instalacao]) -> None:
    arquivo = Path(arquivo)
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    arquivo.write_text(json.dumps([i.__dict__ for i in lista], ensure_ascii=False, indent=1), encoding="utf-8")


# ----------------------------------------------------------------- criar a sua (para compartilhar)
def criar_mod(pasta_traduzida: str | Path, title_id: str, saida: str | Path, descricao: str = "") -> Path:
    """O mod da SUA tradução: um .zip com atmosphere/contents/<TitleID>/romfs/... (o que o Switch e os emuladores
    entendem). pasta_traduzida: a romfs (ou a pasta que tem romfs/exefs) com só os arquivos que você traduziu."""
    pasta, saida, title_id = Path(pasta_traduzida), Path(saida), title_id.upper()
    if not TITLE_ID.fullmatch(title_id):
        raise ErroPatch("falta o TitleID do jogo (16 letras e números começando com 01)")
    arquivos = _listar(pasta)
    if not arquivos:
        raise ErroPatch(f"{pasta.name} está vazia")
    tem_partes = any(c.split("/")[0].lower() in PARTES_MOD for c in arquivos)
    saida.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED) as z:
        for caminho in arquivos:
            dentro = caminho if tem_partes else f"romfs/{caminho}"
            z.write(pasta / caminho, f"atmosphere/contents/{title_id}/{dentro}")
        z.writestr("LEIA-ME.txt", f"{descricao or saida.stem}\n\nMod de tradução para o jogo {title_id}.\n"
                                  "Emulador: copie a pasta romfs para a pasta de mods do jogo (ou use o Maestro > "
                                  "🎮 Jogos > Nintendo Switch > Instalar). Switch com Atmosphère: copie a pasta "
                                  "atmosphere para a raiz do cartão SD.\nNão contém o jogo.\n")
    return saida


def criar_pacote(pasta_traduzida: str | Path, saida: str | Path, pasta_original: str | Path | None = None,
                 descricao: str = "") -> Path:
    """O pacote da SUA tradução de um jogo de PC: um .zip com os arquivos traduzidos no mesmo lugar da pasta do
    jogo. Com a pasta original, só os arquivos novos ou diferentes entram (nada do jogo vai junto)."""
    pasta, saida = Path(pasta_traduzida), Path(saida)
    arquivos = _listar(pasta)
    if pasta_original is not None:
        original = Path(pasta_original)
        arquivos = {c: t for c, t in arquivos.items()
                    if not (original / c).is_file() or (original / c).read_bytes() != (pasta / c).read_bytes()}
    arquivos = {c: t for c, t in arquivos.items() if not c.startswith(COPIA_SEGURANCA + "/")}
    if not arquivos:
        raise ErroPatch("nenhum arquivo traduzido (todos iguais aos do jogo)")
    saida.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED) as z:
        for caminho in arquivos:
            z.write(pasta / caminho, caminho)
        z.writestr("LEIA-ME.txt", f"{descricao or saida.stem}\n\nTradução: copie os arquivos por cima da pasta do "
                                  "jogo (ou use o Maestro > 🎮 Jogos > PC > Instalar, que guarda os originais para "
                                  "desfazer).\nNão contém o jogo: só os arquivos traduzidos.\n")
    return saida
