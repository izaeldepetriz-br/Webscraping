"""Vozes IMPORTADAS (Configurações > Dublagem > "Importar voz"): de dois tipos.

1. Modelo do Piper (.onnx + o .onnx.json ao lado): uma voz pronta a mais para o Piper (grátis, no PC). Há muitas em
   huggingface.co/rhasspy/piper-voices (em português: cadu, jeff, faber, edresson...). Vai para a pasta das vozes
   do Piper com o nome escolhido e aparece no menu "Voz do Piper" e na tabela "Vozes dos personagens".

2. Gravação de uma voz para CLONAR: a referência (a pessoa lendo com calma, de 6 a 60 s) + o consentimento (a MESMA
   pessoa dizendo a frase de consentimento, a mesma do Google). Só a SUA voz ou a de quem autorizou: nunca de
   atores, de famosos ou de quem não sabe. Por isso não aceita áudio de dentro de vídeos (filme, série, jogo) e
   pede quem é o dono da voz. Fica guardada neste PC, pronta para o motor de clonagem no PC (quando instalado) e
   para "Clonar no Gemini" (o Google confere a frase e se as duas gravações são da mesma pessoa).

    vozes_importadas.json   a lista (nome, tipo, arquivos, dono, idioma...)
    vozes/<id>.onnx(.json)  os modelos do Piper importados (a mesma pasta das vozes baixadas)
    vozes_importadas/<id>/  referencia.wav e consentimento.wav das gravações
"""

from __future__ import annotations

import json
import re
import shutil
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from .dublagem import VOZES, ErroDublagem
from . import voz_clonada

PIPER, GRAVACAO = "piper", "gravacao"
EXTENSOES_GRAVACAO = (".wav", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".flac", ".wma", ".webm")
# áudio tirado de vídeo (filme, série, jogo) não serve: a voz seria de atores, que não autorizaram
EXTENSOES_VIDEO = (".mkv", ".mp4", ".avi", ".mov", ".m4v", ".ts", ".m2ts", ".mts", ".wmv", ".flv", ".mpg",
                   ".mpeg", ".vob", ".iso", ".3gp", ".ogv", ".rmvb")


@dataclass
class VozImportada:
    nome: str                 # como aparece na tela ("Cadu")
    id: str                   # sem espaços nem acentos ("cadu"): nome dos arquivos e valor nos menus
    tipo: str                 # PIPER ou GRAVACAO
    origem: str = ""          # o arquivo escolhido (só para lembrar de onde veio)
    idioma: str = ""          # do .onnx.json do Piper ("pt_BR"); vazio nas gravações
    dono: str = ""            # gravação: quem é o dono da voz e gravou o consentimento
    importada_em: str = ""

    def descrever(self) -> str:
        if self.tipo == PIPER:
            return f"{self.nome}: voz do Piper ({self.idioma or 'idioma não informado'}), importada em " \
                   f"{self.importada_em}"
        return f"{self.nome}: gravação para clonar, autorizada por {self.dono}, importada em {self.importada_em}"


def criar_id(nome: str) -> str:
    """'Cadu Jr.' -> 'cadu-jr' (sem acentos, só letras, números e hífen)."""
    texto = unicodedata.normalize("NFD", nome.lower())
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "-", texto).strip("-")[:40]


def validar_nome(nome: str, existentes: list[VozImportada] = ()) -> tuple[str, str]:
    """(nome limpo, id), ou ErroDublagem com o motivo."""
    nome = " ".join(nome.split())
    if not nome:
        raise ErroDublagem("dê um nome para a voz")
    if len(nome) > 40:
        raise ErroDublagem("o nome da voz pode ter até 40 letras")
    if any(c in nome for c in voz_clonada.PROIBIDOS):
        raise ErroDublagem(f"o nome da voz não pode ter estes sinais: {' '.join(voz_clonada.PROIBIDOS)}")
    ident = criar_id(nome)
    if not ident:
        raise ErroDublagem("use pelo menos uma letra ou número no nome da voz")
    if ident in VOZES:
        raise ErroDublagem(f"\"{nome}\" já é uma voz do Piper que vem com o Maestro: use outro nome")
    if any(v.id == ident or v.nome.lower() == nome.lower() for v in existentes):
        raise ErroDublagem(f"já existe uma voz importada chamada \"{nome}\" (remova a antiga ou use outro nome)")
    return nome, ident


def tipo_do_arquivo(caminho: str | Path) -> str:
    """PIPER (.onnx), GRAVACAO (áudio) ou ErroDublagem dizendo o que o Maestro aceita."""
    extensao = Path(caminho).suffix.lower()
    if extensao == ".onnx":
        return PIPER
    if extensao in EXTENSOES_GRAVACAO:
        return GRAVACAO
    if extensao in EXTENSOES_VIDEO:
        raise ErroDublagem("áudio de dentro de vídeos (filme, série, jogo) não é aceito: a voz seria de atores, que "
                           "não autorizaram. Use uma gravação da SUA voz, ou de quem autorizou")
    raise ErroDublagem("escolha um modelo do Piper (.onnx, com o .onnx.json ao lado) ou uma gravação de voz "
                       f"({', '.join(EXTENSOES_GRAVACAO)})")


def _agora() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


# ----------------------------------------------------------------- 1. modelo do Piper
def importar_piper(onnx: str | Path, nome: str, pasta_vozes: str | Path,
                   existentes: list[VozImportada] = ()) -> VozImportada:
    """Copia o modelo (.onnx) e a configuração (.onnx.json, ao lado) para a pasta das vozes do Piper."""
    onnx = Path(onnx)
    if not onnx.is_file():
        raise ErroDublagem(f"não achei o arquivo: {onnx}")
    config = onnx.with_name(onnx.name + ".json")
    if not config.is_file():
        config = onnx.with_suffix(".json")
    if not config.is_file():
        raise ErroDublagem(f"falta o arquivo de configuração da voz ao lado do modelo: {onnx.name}.json (ele vem "
                           "junto, no mesmo lugar de onde você baixou o .onnx)")
    try:
        dados = json.loads(config.read_text(encoding="utf-8"))
    except (OSError, ValueError) as erro:
        raise ErroDublagem(f"o {config.name} não é uma configuração de voz do Piper válida ({erro})") from erro
    if not isinstance(dados, dict) or "audio" not in dados or "phoneme_id_map" not in dados:
        raise ErroDublagem(f"o {config.name} não parece ser de uma voz do Piper (faltam \"audio\" e "
                           "\"phoneme_id_map\")")
    nome, ident = validar_nome(nome, existentes)
    idioma = (dados.get("language") or {}).get("code") or (dados.get("espeak") or {}).get("voice") or ""
    pasta = Path(pasta_vozes)
    pasta.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(onnx, pasta / f"{ident}.onnx")
    shutil.copyfile(config, pasta / f"{ident}.onnx.json")
    return VozImportada(nome, ident, PIPER, str(onnx), idioma=str(idioma), importada_em=_agora())


def e_portugues(v: VozImportada) -> bool:
    return v.tipo != PIPER or not v.idioma or v.idioma.lower().replace("-", "_").startswith("pt")


def modelo_piper(ident: str, pasta_vozes: str | Path) -> Path | None:
    """O .onnx de uma voz do Piper importada (com o .json ao lado), ou None."""
    modelo = Path(pasta_vozes) / f"{ident}.onnx"
    return modelo if modelo.is_file() and modelo.with_name(modelo.name + ".json").is_file() else None


# ----------------------------------------------------------------- 2. gravação para clonar
def importar_gravacao(referencia: str | Path, consentimento: str | Path, nome: str, dono: str, autorizo: bool,
                      pasta: str | Path, ffmpeg: str, existentes: list[VozImportada] = (),
                      executar=None) -> VozImportada:
    """Confere e guarda a referência + o consentimento (WAV 24 kHz, mono, sem os silêncios das pontas)."""
    if not autorizo:
        raise ErroDublagem("marque a confirmação de que a voz é sua ou de quem autorizou (e gravou o consentimento)")
    dono = " ".join(dono.split())
    if not dono:
        raise ErroDublagem("diga quem é o dono da voz (quem autorizou e gravou o consentimento)")
    if not str(consentimento).strip():
        raise ErroDublagem("escolha também a gravação do consentimento (a mesma pessoa dizendo a frase)")
    for arquivo in (referencia, consentimento):
        if tipo_do_arquivo(arquivo) != GRAVACAO:
            raise ErroDublagem(f"{Path(arquivo).name}: escolha um arquivo de áudio ({', '.join(EXTENSOES_GRAVACAO)})")
    nome, ident = validar_nome(nome, existentes)
    extra = {"executar": executar} if executar else {}
    ref = voz_clonada.preparar_audio(Path(referencia), ffmpeg, **extra)
    con = voz_clonada.preparar_audio(Path(consentimento), ffmpeg, **extra)
    voz_clonada.conferir_duracoes(ref, con)
    destino = pasta_da_gravacao(pasta, ident)
    destino.mkdir(parents=True, exist_ok=True)
    (destino / "referencia.wav").write_bytes(ref)
    (destino / "consentimento.wav").write_bytes(con)
    return VozImportada(nome, ident, GRAVACAO, str(referencia), dono=dono, importada_em=_agora())


def pasta_da_gravacao(pasta: str | Path, ident: str) -> Path:
    return Path(pasta) / "vozes_importadas" / ident


def ler_gravacao(v: VozImportada, pasta: str | Path) -> tuple[bytes, bytes]:
    """(referência, consentimento) de uma gravação importada."""
    destino = pasta_da_gravacao(pasta, v.id)
    try:
        return (destino / "referencia.wav").read_bytes(), (destino / "consentimento.wav").read_bytes()
    except OSError as erro:
        raise ErroDublagem(f"as gravações da voz \"{v.nome}\" sumiram deste PC; importe de novo") from erro


# ----------------------------------------------------------------- guardar neste PC
def carregar(arquivo: Path) -> list[VozImportada]:
    try:
        dados = json.loads(Path(arquivo).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    campos = set(VozImportada.__dataclass_fields__)
    return [VozImportada(**{k: v for k, v in d.items() if k in campos}) for d in dados
            if isinstance(d, dict) and d.get("id") and d.get("tipo") in (PIPER, GRAVACAO)]


def salvar(vozes: list[VozImportada], arquivo: Path) -> None:
    arquivo = Path(arquivo)
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    temporario = arquivo.with_suffix(".tmp")
    temporario.write_text(json.dumps([asdict(v) for v in vozes], ensure_ascii=False, indent=1), encoding="utf-8")
    temporario.replace(arquivo)


def remover(v: VozImportada, pasta: str | Path, pasta_vozes: str | Path) -> None:
    """Apaga os arquivos da voz deste PC (o modelo do Piper ou as gravações)."""
    if v.tipo == PIPER:
        for nome in (f"{v.id}.onnx", f"{v.id}.onnx.json"):
            (Path(pasta_vozes) / nome).unlink(missing_ok=True)
    else:
        shutil.rmtree(pasta_da_gravacao(pasta, v.id), ignore_errors=True)
