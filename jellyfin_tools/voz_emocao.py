"""O 2º motor de vozes no PC, só para as falas com EMOÇÃO: o Chatterbox (Resemble AI, licença MIT), opcional.

Por quê: o XTTS-v2 não tem controle de emoção (no teste de 8 emoções, a raiva e a tristeza saíram no mesmo tom). O
Chatterbox tem a "intensidade" (exaggeration) e imita a voz de uma gravação curta: a fala com raiva sai com raiva
e com a MESMA voz do personagem (ele imita a voz do XTTS-v2: a fala de referência de cada voz pronta é gerada uma
vez pelo XTTS-v2; a voz importada usa a própria gravação). No teste: 96% das palavras entendidas pelo Whisper e 91%
de semelhança com a voz imitada.

O Chatterbox pede outras versões das bibliotecas (PyTorch 2.6, transformers 5) que brigam com as do XTTS-v2: por
isso fica num ambiente À PARTE, dentro do pacote do XTTS-v2 (motor_vozes/chatterbox/), usando o mesmo uv:

    ambiente/      Python 3.11 + PyTorch 2.6 + chatterbox-tts
    modelos/       o modelo multilíngue (~3,2 GB, baixado na 1ª fala com emoção)
    servidor.py    o "estúdio", igual ao do XTTS-v2: um pedido por linha

A marca d'água: o Chatterbox põe no áudio uma marca inaudível (Perth) que diz "voz gerada por IA". Não muda o som.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .dublagem import ErroDublagem, _baixar
from .emocoes import EMOCOES, NORMAL, intensidade_chatterbox
from .voz_local import (INDICE_CPU, ServidorDeVoz, _etapas, conferir_espaco, espaco_livre, frases_para_falar,
                        instalar_pacote, python_do_motor, tem_placa_nvidia)

NOME = "Chatterbox (emoção, grátis, no PC)"
VERSAO_PYTHON = "3.11"
TORCH = ["torch==2.6.0", "torchaudio==2.6.0"]
INDICE_GPU = "https://download.pytorch.org/whl/cu126"     # o PyTorch 2.6 (placas sem suporte: vai pelo processador)
# o setuptools: a marca d'água (Perth) usa o pkg_resources, que o ambiente do uv não traz (sem ele, o Chatterbox
# não abria: "'NoneType' object is not callable"; visto no teste de verdade no Windows)
PACOTES = ["chatterbox-tts==0.1.7", "setuptools<81"]
ESPACO_GPU, ESPACO_CPU, ESPACO_ATUALIZAR = 10.0, 6.0, 1.5  # GB: PyTorch + pacotes + o modelo (~3,2 GB)

SERVIDOR = r'''
import json, os, sys
canal = sys.stdout
sys.stdout = sys.stderr
sys.stdin.reconfigure(encoding="utf-8")
canal.reconfigure(encoding="utf-8")


def responder(dados):
    canal.write(json.dumps(dados, ensure_ascii=False) + "\n")
    canal.flush()


def memoria_da_placa():
    """GB da placa de vídeo (None se não deu para saber: só informa, não decide o plano B)."""
    try:
        return round(torch.cuda.get_device_properties(0).total_memory / 1024 ** 3, 1)
    except Exception:
        return None


def erro_da_placa(erro):
    texto = f"{type(erro).__name__} {erro}".lower()
    return "cuda" in texto or "out of memory" in texto or "cublas" in texto or "cudnn" in texto


try:
    import numpy as np
    import soundfile as sf
    import torch
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS
    dispositivo, placa, aviso, memoria = "cpu", "", "", None
    if torch.cuda.is_available():
        try:
            modelo = ChatterboxMultilingualTTS.from_pretrained(device="cuda")
            dispositivo, placa = "cuda", torch.cuda.get_device_name(0)
            memoria = memoria_da_placa()
        except Exception as erro:            # plano B: a placa não aguentou, vai pelo processador
            print(f"a placa de vídeo não aguentou ({type(erro).__name__}: {erro}); vai pelo processador",
                  file=sys.stderr)
            torch.cuda.empty_cache()
            aviso = f"a placa de vídeo não aguentou o modelo ({type(erro).__name__}); vai pelo processador"
    if dispositivo == "cpu":
        modelo = ChatterboxMultilingualTTS.from_pretrained(device="cpu")
    responder({"pronto": True, "dispositivo": dispositivo, "placa": placa, "aviso": aviso, "memoria": memoria})
except Exception as erro:
    responder({"erro": f"{type(erro).__name__}: {erro}"})
    sys.exit(1)


def gerar(pedido):
    partes = []
    for frase, pausa in pedido["frases"]:
        som = modelo.generate(frase, language_id=pedido.get("idioma", "pt"), audio_prompt_path=pedido["referencia"],
                              exaggeration=pedido["exaggeration"], cfg_weight=pedido["cfg"])
        partes.append(np.asarray(som.squeeze(0).detach().cpu().numpy(), dtype=np.float32).reshape(-1))
        if pausa:
            partes.append(np.zeros(int(modelo.sr * pausa), dtype=np.float32))
    return np.concatenate(partes)


for linha in sys.stdin:
    try:
        pedido = json.loads(linha)
        if pedido.get("cmd") == "sair":
            break
        try:
            audio = gerar(pedido)
        except Exception as erro:
            if dispositivo != "cuda" or not erro_da_placa(erro):
                raise
            print(f"a placa de vídeo falhou no meio ({type(erro).__name__}: {erro}); segue pelo processador",
                  file=sys.stderr)
            del modelo
            torch.cuda.empty_cache()
            modelo = ChatterboxMultilingualTTS.from_pretrained(device="cpu")
            dispositivo, placa = "cpu", ""
            audio = gerar(pedido)
        sf.write(pedido["saida"], audio, modelo.sr)
        responder({"ok": True, "dispositivo": dispositivo})
    except Exception as erro:
        responder({"erro": f"{type(erro).__name__}: {erro}"})
'''


def pasta_do_chatterbox(pasta_xtts: str | Path) -> Path:
    return Path(pasta_xtts) / "chatterbox"


def arquivo_servidor(pasta_xtts: str | Path) -> Path:
    return pasta_do_chatterbox(pasta_xtts) / "servidor.py"


def instalado(pasta_xtts: str | Path) -> dict | None:
    """O que foi instalado ({"gpu": True, ...}) ou None se o Chatterbox não está pronto."""
    pasta = pasta_do_chatterbox(pasta_xtts)
    marca = pasta / "instalado.json"
    if not (marca.is_file() and python_do_motor(pasta).is_file()):
        return None
    try:
        return json.loads(marca.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def instalar(pasta_xtts: str | Path, gpu: bool | None = None, sistema: str = sys.platform, baixar=_baixar,
             executar=subprocess.run, ao_progresso=None, parar=None, medir_espaco=espaco_livre) -> dict:
    """Instala o Chatterbox no ambiente dele (precisa do XTTS-v2 instalado: usa o mesmo uv e imita as vozes dele)."""
    from .voz_local import instalado as xtts_instalado
    pasta_xtts = Path(pasta_xtts)
    if not xtts_instalado(pasta_xtts):
        raise ErroDublagem("instale primeiro o motor de vozes XTTS-v2 (o Chatterbox imita as vozes dele)")
    pasta = pasta_do_chatterbox(pasta_xtts)
    if gpu is None:
        gpu = tem_placa_nvidia(executar)
    conferir_espaco(pasta, ESPACO_ATUALIZAR if instalado(pasta_xtts) else ESPACO_GPU if gpu else ESPACO_CPU,
                    medir_espaco, "o Chatterbox")
    pasta.mkdir(parents=True, exist_ok=True)
    etapa = _etapas(ao_progresso, parar)
    instalar_pacote(pasta_xtts, pasta, VERSAO_PYTHON, TORCH, INDICE_GPU if gpu else INDICE_CPU, PACOTES,
                    "o Chatterbox", gpu, sistema, baixar, executar, etapa)
    arquivo_servidor(pasta_xtts).write_text(SERVIDOR, encoding="utf-8")
    info = {"gpu": gpu, "torch": TORCH[0], "pacotes": PACOTES}
    (pasta / "instalado.json").write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
    etapa(1.0, "Chatterbox instalado.")
    return info


def desinstalar(pasta_xtts: str | Path) -> None:
    shutil.rmtree(pasta_do_chatterbox(pasta_xtts), ignore_errors=True)


class MotorEmocao(ServidorDeVoz):
    """falar(texto, wav, referência, emoção): a fala com a emoção, imitando a voz da referência."""

    nome = "o Chatterbox"
    registro = "motor_vozes/chatterbox/registro.txt"

    def __init__(self, pasta_xtts: str | Path, abrir=subprocess.Popen, avisar=None):
        super().__init__(abrir, avisar)
        self.pasta_xtts = Path(pasta_xtts)
        self.pasta = pasta_do_chatterbox(pasta_xtts)
        self.pedidos = 0

    def iniciar(self, parar=None) -> None:
        if self.aberto():
            return
        python = python_do_motor(self.pasta)
        if not instalado(self.pasta_xtts) or not python.is_file():
            raise ErroDublagem("o Chatterbox não está instalado: Configurações > Dublagem > \"Instalar o Chatterbox\"")
        modelos = self.pasta / "modelos"
        ambiente = {**os.environ, "HF_HOME": str(modelos / "hf"), "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
        self._abrir_servidor(python, arquivo_servidor(self.pasta_xtts), SERVIDOR, ambiente, self.pasta,
                             "carregando o Chatterbox para as falas com emoção (na 1ª vez baixa o modelo, ~3,2 GB)",
                             parar)

    def falar(self, texto: str, saida: str | Path, referencia: str | Path, emocao: str, parar=None,
              idioma: str = "pt", forca: float = 0.0) -> None:
        """A fala com a emoção. Com a força da interpretação (> 0), mais intensa e no jeito da emoção (as pausas do
        choro, o "!" da raiva)."""
        if emocao not in EMOCOES:
            raise ErroDublagem(f"emoção desconhecida: {emocao}")
        self.iniciar(parar)
        exaggeration, cfg = intensidade_chatterbox(emocao, forca)
        frases = frases_para_falar(texto, emocao if forca > 0 else NORMAL)
        resposta = self._pedir({"texto": texto, "frases": frases, "idioma": idioma,
                                "saida": str(Path(saida).absolute()),           # caminhos completos: o servidor
                                "referencia": str(Path(referencia).absolute()),  # trabalha em outra pasta
                                "exaggeration": exaggeration, "cfg": cfg}, parar)
        if not resposta.get("ok"):
            raise ErroDublagem(f"o Chatterbox não gerou a fala: {resposta.get('erro', 'sem resposta')}")
        self.pedidos += 1
