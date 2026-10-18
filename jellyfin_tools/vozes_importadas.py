"""Vozes IMPORTADAS (Configurações > Dublagem > "Importar voz"): de dois tipos.

1. Modelo do Piper (.onnx + o .onnx.json ao lado): uma voz pronta a mais para o Piper (grátis, no PC). Há muitas em
   huggingface.co/rhasspy/piper-voices (em português: cadu, jeff, faber, edresson...). Vai para a pasta das vozes
   do Piper com o nome escolhido e aparece no menu "Voz do Piper" e na tabela "Vozes dos personagens".

2. Gravação de uma voz para CLONAR (a pessoa lendo com calma, de 6 a 60 s): o motor de vozes no PC (XTTS-v2) fala
   com esse timbre. Sem conferir consentimento: só uma declaração de que a voz é sua ou de quem autorizou. Áudio
   de dentro de vídeos (filme, série, jogo) continua recusado: a voz seria de atores.
   Gravações de EMOÇÃO (a mesma pessoa lendo brava, chorando, sussurrando..., de 3 a 60 s) entram na mesma voz:
   o XTTS-v2 copia o jeito da gravação, e a fala com raiva vai com a gravação brava (emocoes.py).

Em todas: o nome, o gênero e a idade (a "Automática" escolhe a voz pelo gênero e pela idade de quem fala).

    vozes_importadas.json   a lista (nome, tipo, gênero, idade, idioma...)
    vozes/<id>.onnx(.json)  os modelos do Piper importados (a mesma pasta das vozes baixadas)
    vozes_importadas/<id>/  referencia.wav das gravações (e brava.wav, choro.wav... as de emoção)
"""

from __future__ import annotations

import json
import re
import shutil
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from .dublagem import VOZES, ErroDublagem
from . import voz_clonada
from .emocoes import EMOCOES, NORMAL, PARECIDAS

PIPER, GRAVACAO = "piper", "gravacao"
EXTENSOES_GRAVACAO = (".wav", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".flac", ".wma", ".webm")
# áudio tirado de vídeo (filme, série, jogo) não serve: a voz seria de atores, que não autorizaram
GENEROS = ("masculina", "feminina")
IDADES = ("criança", "jovem", "adulta", "idosa")
EXTENSOES_VIDEO = (".mkv", ".mp4", ".avi", ".mov", ".m4v", ".ts", ".m2ts", ".mts", ".wmv", ".flv", ".mpg",
                   ".mpeg", ".vob", ".iso", ".3gp", ".ogv", ".rmvb")


@dataclass
class VozImportada:
    nome: str                 # como aparece na tela ("Cadu")
    id: str                   # sem espaços nem acentos ("cadu"): nome dos arquivos e valor nos menus
    tipo: str                 # PIPER ou GRAVACAO
    origem: str = ""          # o arquivo escolhido (só para lembrar de onde veio)
    idioma: str = ""          # do .onnx.json do Piper ("pt_BR"); vazio nas gravações
    dono: str = ""            # (versões antigas: quem autorizou; não é mais pedido)
    importada_em: str = ""
    genero: str = "masculina"     # GENEROS
    idade: str = "adulta"         # IDADES
    emocoes: list = field(default_factory=list)    # gravações de emoção desta voz ("brava", "choro"...: emocoes.py)

    @property
    def perfil(self) -> str:
        return f"{self.genero}, {self.idade}"

    def descrever(self) -> str:
        if self.tipo == PIPER:
            return f"{self.nome}: voz do Piper ({self.idioma or 'idioma não informado'}) · {self.perfil} · importada " \
                   f"em {self.importada_em}"
        emocoes = f" · emoções: {', '.join(EMOCOES[e].lower() for e in self.emocoes if e in EMOCOES)}" \
            if self.emocoes else ""
        return f"{self.nome}: gravação para clonar · {self.perfil}{emocoes} · importada em {self.importada_em}"


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


def conferir_perfil(genero: str, idade: str) -> tuple[str, str]:
    genero, idade = genero.strip().lower(), idade.strip().lower()
    if genero not in GENEROS:
        raise ErroDublagem(f"escolha o gênero da voz ({' ou '.join(GENEROS)})")
    if idade not in IDADES:
        raise ErroDublagem(f"escolha a idade da voz ({', '.join(IDADES)})")
    return genero, idade


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
def importar_piper(onnx: str | Path, nome: str, pasta_vozes: str | Path, existentes: list[VozImportada] = (),
                   genero: str = "masculina", idade: str = "adulta") -> VozImportada:
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
    genero, idade = conferir_perfil(genero, idade)
    idioma = (dados.get("language") or {}).get("code") or (dados.get("espeak") or {}).get("voice") or ""
    pasta = Path(pasta_vozes)
    pasta.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(onnx, pasta / f"{ident}.onnx")
    shutil.copyfile(config, pasta / f"{ident}.onnx.json")
    return VozImportada(nome, ident, PIPER, str(onnx), idioma=str(idioma), importada_em=_agora(), genero=genero,
                        idade=idade)


def e_portugues(v: VozImportada) -> bool:
    return v.tipo != PIPER or not v.idioma or v.idioma.lower().replace("-", "_").startswith("pt")


def modelo_piper(ident: str, pasta_vozes: str | Path) -> Path | None:
    """O .onnx de uma voz do Piper importada (com o .json ao lado), ou None."""
    modelo = Path(pasta_vozes) / f"{ident}.onnx"
    return modelo if modelo.is_file() and modelo.with_name(modelo.name + ".json").is_file() else None


# ----------------------------------------------------------------- 2. gravação para clonar
def importar_gravacao(referencia: str | Path, nome: str, genero: str, idade: str, declaro: bool, pasta: str | Path,
                      ffmpeg: str, existentes: list[VozImportada] = (), executar=None) -> VozImportada:
    """Guarda a gravação (WAV 24 kHz, mono, sem os silêncios das pontas) para o motor de vozes no PC."""
    _conferir_gravacao(referencia, declaro)
    nome, ident = validar_nome(nome, existentes)
    genero, idade = conferir_perfil(genero, idade)
    ref = _preparar_gravacao(referencia, ffmpeg, executar, voz_clonada.MINIMO_REFERENCIA)
    destino = pasta_da_gravacao(pasta, ident)
    destino.mkdir(parents=True, exist_ok=True)
    (destino / "referencia.wav").write_bytes(ref)
    return VozImportada(nome, ident, GRAVACAO, str(referencia), importada_em=_agora(), genero=genero, idade=idade)


MINIMO_EMOCAO = 3.0           # segundos: um grito ou um choro curto já mostram o jeito (a normal pede 6)


def importar_emocao(referencia: str | Path, voz: VozImportada, emocao: str, declaro: bool, pasta: str | Path,
                    ffmpeg: str, executar=None) -> VozImportada:
    """Junta à gravação importada `voz` a gravação de uma EMOÇÃO (a mesma pessoa lendo brava, chorando...).
    Devolve a voz com a emoção na lista (a gravação de antes da mesma emoção é trocada)."""
    if emocao not in EMOCOES:
        raise ErroDublagem(f"escolha a emoção da gravação ({', '.join(EMOCOES.values())})")
    if voz.tipo != GRAVACAO:
        raise ErroDublagem(f"\"{voz.nome}\" é uma voz do Piper: as gravações de emoção são das gravações para clonar")
    _conferir_gravacao(referencia, declaro)
    ref = _preparar_gravacao(referencia, ffmpeg, executar, MINIMO_EMOCAO)
    destino = pasta_da_gravacao(pasta, voz.id)
    destino.mkdir(parents=True, exist_ok=True)
    (destino / f"{emocao}.wav").write_bytes(ref)
    voz.emocoes = [e for e in EMOCOES if e in set(voz.emocoes) | {emocao}]       # na ordem do menu
    return voz


def achar_gravacao(nome: str, existentes: list[VozImportada]) -> VozImportada:
    """A gravação importada com este nome (para juntar a ela uma gravação de emoção)."""
    alvo = " ".join(nome.split()).lower()
    achada = next((v for v in existentes if v.tipo == GRAVACAO and (v.nome.lower() == alvo or v.id == criar_id(alvo))),
                  None)
    if achada is None:
        nomes = ", ".join(v.nome for v in existentes if v.tipo == GRAVACAO)
        raise ErroDublagem(f"para uma gravação de emoção, o nome tem de ser o de uma voz já importada (a gravação "
                           f"normal vem antes){': ' + nomes if nomes else ''}")
    return achada


def _conferir_gravacao(referencia: str | Path, declaro: bool) -> None:
    if not declaro:
        raise ErroDublagem("marque a declaração de que a voz é sua ou de quem autorizou (não de atores ou famosos)")
    if tipo_do_arquivo(referencia) != GRAVACAO:
        raise ErroDublagem(f"{Path(referencia).name}: escolha um arquivo de áudio ({', '.join(EXTENSOES_GRAVACAO)})")


def _preparar_gravacao(referencia: str | Path, ffmpeg: str, executar, minimo: float) -> bytes:
    extra = {"executar": executar} if executar else {}
    ref = voz_clonada.preparar_audio(Path(referencia), ffmpeg, **extra)
    segundos = voz_clonada.duracao(ref)
    if segundos < minimo:
        raise ErroDublagem(f"a gravação tem {segundos:.0f} s (sem os silêncios); use pelo menos {minimo:.0f} s de "
                           "fala (o ideal é de 10 a 30 s)")
    if segundos > voz_clonada.MAXIMO_REFERENCIA:
        raise ErroDublagem(f"a gravação tem {segundos:.0f} s; use no máximo {voz_clonada.MAXIMO_REFERENCIA:.0f} s")
    return ref


def pasta_da_gravacao(pasta: str | Path, ident: str) -> Path:
    return Path(pasta) / "vozes_importadas" / ident


def arquivo_da_gravacao(v: VozImportada, pasta: str | Path) -> Path:
    """O .wav de referência de uma gravação importada (o motor de vozes no PC fala com esse timbre)."""
    arquivo = pasta_da_gravacao(pasta, v.id) / "referencia.wav"
    if not arquivo.is_file():
        raise ErroDublagem(f"a gravação da voz \"{v.nome}\" sumiu deste PC; importe de novo")
    return arquivo


def arquivo_da_emocao(v: VozImportada, pasta: str | Path, emocao: str) -> Path | None:
    """A gravação de EMOÇÃO da voz (ou a da emoção parecida: sem a de grito, a brava), ou None se não tem."""
    if emocao == NORMAL:
        return None
    for qual in (emocao, PARECIDAS.get(emocao)):
        if qual and qual in v.emocoes:
            arquivo = pasta_da_gravacao(pasta, v.id) / f"{qual}.wav"
            if arquivo.is_file():
                return arquivo
    return None


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
