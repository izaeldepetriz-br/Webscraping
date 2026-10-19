"""Motor de vozes GRÁTIS no PC: o XTTS-v2 (Coqui), no lugar do Gemini. Natural, fala português e imita o timbre de
uma gravação curta (as vozes importadas). Usa a placa de vídeo NVIDIA quando há (a RTX faz 1 min de fala em
segundos); sem ela, o processador (bem mais devagar).

Licença do modelo: CPML da Coqui, só uso NÃO comercial (o Maestro pede para aceitar antes de instalar).

O XTTS precisa do PyTorch (~3 GB com a placa de vídeo), que não cabe no Maestro.exe e não convive com as bibliotecas
dele. Por isso fica num "pacote" à parte, na pasta das configurações (motor_vozes/), instalado uma vez pelo botão
"Instalar o motor de vozes":

    uv/            o uv (astral.sh): baixa o Python 3.12 e instala os pacotes, rápido e sem mexer no PC
    python/        o Python 3.12 do pacote          ambiente/   PyTorch + coqui-tts
    modelos/       o modelo XTTS-v2 (~1,8 GB, baixado na 1ª fala)
    servidor.py    o "estúdio": carrega o modelo uma vez e fala cada pedido que chega (JSON, uma linha por pedido)

O Maestro conversa com o servidor.py pela entrada e saída dele (como um interfone): manda {"texto", "saida", "voz"
ou "referencia"} e recebe {"ok": true} ou {"erro": "..."}.

As vozes: as PRONTAS do XTTS-v2 (genéricas, de estúdio; o gênero de cada uma foi medido pelo tom) e as gravações
importadas (Configurações > Dublagem > Importar voz), como "imp:<id>". Uma voz do Gemini ("Charon", "Kore"...) que
chegue da voz por personagem vira uma voz pronta do mesmo gênero (sempre a mesma para o mesmo nome).

A EMOÇÃO (emocoes.py): a fala com nota de direção ("Nesta fala: gritando") vai com a gravação daquela emoção da voz
importada, se houver; senão, com o Chatterbox (voz_emocao.py, opcional), imitando a mesma voz; sem os dois, neutra.

Placa de vídeo que não aguenta (pouca memória, ou nova demais para este PyTorch): o servidor passa para o
processador sozinho (mais devagar, mas termina) e avisa. E na placa de até 12 GB (a RTX 4060 tem 8), o XTTS-v2 e o
Chatterbox não ficam abertos juntos (os dois somam ~7-8 GB): primeiro as falas normais, depois as com emoção.
"""

from __future__ import annotations

import hashlib
import json
import os
import queue
import shutil
import subprocess
import sys
import tarfile
import threading
import zipfile
from collections import Counter
from pathlib import Path

from .dublagem import SEM_JANELA, ErroDublagem, _baixar
from .emocoes import NORMAL, emocao_da_nota, nome_da_emocao

NOME = "XTTS-v2 (grátis, no PC)"
VERSAO_UV = "0.13.1"
URL_UV = f"https://github.com/astral-sh/uv/releases/download/{VERSAO_UV}/"
ARQUIVOS_UV = {"win32": "uv-x86_64-pc-windows-msvc.zip", "linux": "uv-x86_64-unknown-linux-gnu.tar.gz",
               "darwin": "uv-aarch64-apple-darwin.tar.gz"}
VERSAO_PYTHON = "3.12"
TORCH = ["torch==2.8.0", "torchaudio==2.8.0"]
INDICE_GPU = "https://download.pytorch.org/whl/cu128"     # placas NVIDIA (RTX 20 a 50)
INDICE_CPU = "https://download.pytorch.org/whl/cpu"
PACOTES = ["coqui-tts==0.27.5", "transformers>=4.57,<5"]   # o transformers 5 quebra o XTTS
MODELO = "tts_models/multilingual/multi-dataset/xtts_v2"
PREFIXO_IMPORTADA = "imp:"
TEMPO_PARA_CARREGAR = 3600      # segundos: na 1ª vez o servidor baixa o modelo (~1,8 GB) antes de ficar pronto
JUNTOS_NA_PLACA_GB = 12.0       # com menos memória que isso, XTTS-v2 e Chatterbox usam a placa um de cada vez
FRASE_DE_TESTE = "Olá! Esta é a voz que vai dublar os seus vídeos, aqui no seu computador, sem custo."
# a fala que o Chatterbox imita para fazer uma voz PRONTA com emoção (gerada uma vez pelo XTTS-v2, em referencias/)
FRASE_DE_REFERENCIA = ("Olá! Hoje o dia está bonito. Vou fazer um café e ver um filme. Você quer vir junto? Vai ser "
                       "ótimo!")
# espaço livre no disco para instalar (GB): PyTorch + coqui-tts + o modelo (~1,8 GB); para atualizar, bem menos
ESPACO_GPU, ESPACO_CPU, ESPACO_ATUALIZAR = 9.0, 4.0, 1.5

# As vozes prontas do XTTS-v2 (os nomes são inventados pela Coqui: não dizem o gênero). O gênero foi MEDIDO pelo tom
# de cada uma falando português (genero_local.tom_medio); nas poucas do meio do caminho, o grupo em que vêm no modelo.
# Fora da lista: "Marcos Rudaski" (em português, o Whisper não entendeu a fala dele).
VOZES_PRONTAS: dict[str, str] = {
    "Claribel Dervla": "masculina, adulta",
    "Daisy Studious": "feminina, adulta",
    "Gracie Wise": "feminina, adulta",
    "Tammie Ema": "feminina, adulta",
    "Alison Dietlinde": "feminina, adulta",
    "Ana Florence": "feminina, adulta",
    "Annmarie Nele": "feminina, adulta",
    "Asya Anara": "feminina, adulta",
    "Brenda Stern": "feminina, adulta",
    "Gitta Nikolina": "feminina, adulta",
    "Henriette Usha": "feminina, adulta",
    "Sofia Hellen": "feminina, adulta",
    "Tammy Grit": "feminina, adulta",
    "Tanja Adelina": "feminina, adulta",
    "Vjollca Johnnie": "feminina, adulta",
    "Andrew Chipper": "feminina, adulta",
    "Badr Odhiambo": "feminina, adulta",
    "Dionisio Schuyler": "masculina, adulta",
    "Royston Min": "masculina, adulta",
    "Viktor Eka": "masculina, adulta",
    "Abrahan Mack": "masculina, adulta",
    "Adde Michal": "masculina, adulta",
    "Baldur Sanjin": "masculina, adulta",
    "Craig Gutsy": "masculina, adulta",
    "Damien Black": "masculina, adulta",
    "Gilberto Mathias": "masculina, adulta",
    "Ilkin Urbano": "masculina, adulta",
    "Kazuhiko Atallah": "masculina, adulta",
    "Ludvig Milivoj": "masculina, adulta",
    "Suad Qasim": "feminina, adulta",
    "Torcull Diarmuid": "masculina, adulta",
    "Viktor Menelaos": "masculina, adulta",
    "Zacharie Aimilios": "masculina, adulta",
    "Nova Hogarth": "feminina, adulta",
    "Maja Ruoho": "feminina, adulta",
    "Uta Obando": "feminina, adulta",
    "Lidiya Szekeres": "feminina, adulta",
    "Chandra MacFarland": "feminina, adulta",
    "Szofi Granger": "feminina, adulta",
    "Camilla Holmström": "feminina, adulta",
    "Lilya Stainthorpe": "feminina, adulta",
    "Zofija Kendrick": "feminina, adulta",
    "Narelle Moon": "feminina, adulta",
    "Barbora MacLean": "feminina, adulta",
    "Alexandra Hisakawa": "feminina, adulta",
    "Alma María": "feminina, adulta",
    "Rosemary Okafor": "feminina, adulta",
    "Ige Behringer": "masculina, adulta",
    "Filip Traverse": "masculina, adulta",
    "Damjan Chapman": "masculina, adulta",
    "Wulf Carlevaro": "masculina, adulta",
    "Aaron Dreschner": "masculina, adulta",
    "Kumar Dahl": "masculina, adulta",
    "Eugenio Mataracı": "masculina, adulta",
    "Ferran Simen": "masculina, adulta",
    "Xavier Hayasaka": "masculina, adulta",
    "Luis Moray": "masculina, adulta",
}
VOZ_PADRAO = "Damien Black"
# As VARIANTES de cada voz pronta (mais vozes sem clonar ninguém): outro tom (semitons) e outra "garganta" (os
# formantes: 1,10 = 10% menor, voz mais jovem). A mesma voz genérica com outro tom e outra garganta soa como outra
# pessoa: as 57 viram 228, e a "jovem" faz os adolescentes (as prontas são todas de adultos). "Ana Florence · jovem".
SEPARADOR_VARIANTE = " · "
VARIANTES: dict[str, dict[str, tuple[float, float]]] = {      # variante: {gênero: (semitons, formantes)}
    "grave": {"masculina": (-2.5, 0.93), "feminina": (-2.0, 0.94)},
    "aguda": {"masculina": (2.0, 1.04), "feminina": (2.0, 1.04)},
    "jovem": {"masculina": (3.0, 1.10), "feminina": (2.0, 1.10)},
}
PERFIL_DA_VARIANTE = {"grave": "adulta, mais grave", "aguda": "adulta, mais aguda", "jovem": "jovem"}

# O "estúdio" que roda no Python do pacote (fica em motor_vozes/servidor.py). O que a biblioteca escreve na tela vai
# para o registro (stderr): a saída fica só para as respostas, uma linha JSON por pedido.
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
    """Falta de memória na placa de vídeo, ou placa nova demais para este PyTorch ("no kernel image")."""
    texto = f"{type(erro).__name__} {erro}".lower()
    return "cuda" in texto or "out of memory" in texto or "cublas" in texto or "cudnn" in texto


try:
    import numpy as np
    import torch
    from TTS.api import TTS
    tts = TTS(os.environ.get("MAESTRO_MODELO", "tts_models/multilingual/multi-dataset/xtts_v2"))
    dispositivo, placa, aviso, memoria = "cpu", "", "", None
    if torch.cuda.is_available():
        try:
            tts = tts.to("cuda")
            dispositivo, placa = "cuda", torch.cuda.get_device_name(0)
            memoria = memoria_da_placa()
        except Exception as erro:            # plano B: a placa não aguentou, vai pelo processador
            print(f"a placa de vídeo não aguentou ({type(erro).__name__}: {erro}); vai pelo processador",
                  file=sys.stderr)
            tts = tts.to("cpu")
            torch.cuda.empty_cache()
            aviso = f"a placa de vídeo não aguentou o modelo ({type(erro).__name__}); vai pelo processador"
    responder({"pronto": True, "dispositivo": dispositivo, "placa": placa, "aviso": aviso, "memoria": memoria,
               "vozes": list(tts.speakers or [])})
except Exception as erro:
    responder({"erro": f"{type(erro).__name__}: {erro}"})
    sys.exit(1)


def gerar(pedido):
    voz = {"speaker_wav": pedido["referencia"]} if pedido.get("referencia") else {"speaker": pedido["voz"]}
    frases = pedido.get("frases") or [[pedido["texto"], 0.0]]
    taxa = getattr(tts.synthesizer, "output_sample_rate", 24000) or 24000
    partes = []
    for frase, pausa in frases:          # uma por vez, sem o ponto final (o XTTS lia "ponto" em voz alta)
        partes.append(np.asarray(tts.tts(text=frase, language=pedido.get("idioma", "pt"), split_sentences=False,
                                         **voz), dtype=np.float32))
        if pausa:
            partes.append(np.zeros(int(taxa * pausa), dtype=np.float32))
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
            tts = tts.to("cpu")
            torch.cuda.empty_cache()
            dispositivo, placa = "cpu", ""
            audio = gerar(pedido)
        tts.synthesizer.save_wav(wav=audio, path=pedido["saida"])
        responder({"ok": True, "dispositivo": dispositivo})
    except Exception as erro:
        responder({"erro": f"{type(erro).__name__}: {erro}"})
'''


# ----------------------------------------------------------------- o texto: frase a frase, sem o ponto final
# O XTTS-v2 LÊ o ponto final em português ("...nas árvores, ponto"): no teste, 1 em cada 3 falas. Por isso cada frase
# vai sozinha e sem o ponto, e no lugar dele entra uma pausa de silêncio. "?" e "!" ficam (dão a entonação de
# pergunta e de exclamação); ";" e ":" viram vírgula; reticências no meio viram vírgula e, no fim, saem.
PAUSA_PONTO, PAUSA_PERGUNTA = 0.30, 0.35


# o jeito de falar de cada emoção: o choro, o medo e a tristeza falam aos pedaços (cada vírgula vira uma pausa; o choro
# puxa o ar nelas) (pausa da frase, pausa da vírgula); a raiva e o grito terminam as frases com "!"
PAUSAS_DA_EMOCAO = {"choro": (0.55, 0.4), "medo": (0.4, 0.3), "triste": (0.5, 0.3)}
EXCLAMAR = ("brava", "grito")


def frases_para_falar(texto: str, emocao: str = NORMAL) -> list[list]:
    """'E cuidado. Tem algo ali?' -> [['E cuidado', 0.3], ['Tem algo ali?', 0.0]] (a última sem pausa). Com a
    emoção: chorando, 'Por favor, não vai.' -> [['Por favor', 0.4], ['não vai', 0.0]]; com raiva, 'Sai.' -> 'Sai!'."""
    import re
    texto = " ".join(texto.replace("...", "…").split())
    texto = re.sub(r"\s*[;:]\s*", ", ", texto)
    texto = re.sub(r"…(?=\s*\w)", ",", texto)
    frases = []
    for parte in re.split(r"(?<=[.!?…])\s+", texto):
        parte = parte.strip()
        frase = parte.rstrip(".…").rstrip(" ,")
        if not re.search(r"\w", frase):
            continue
        if emocao in EXCLAMAR and not frase.endswith(("?", "!")):
            frase += "!"
        pausa = PAUSA_PERGUNTA if frase.endswith(("?", "!")) else PAUSA_PONTO
        if emocao in PAUSAS_DA_EMOCAO:
            na_frase, na_virgula = PAUSAS_DA_EMOCAO[emocao]
            pedacos = []
            for pedaco in (p.strip() for p in frase.split(",")):
                if pedacos and len(pedacos[-1].split()) < 2:          # pedaço de 1 palavra vai junto do próximo
                    pedacos[-1] = f"{pedacos[-1]}, {pedaco}"
                elif re.search(r"\w", pedaco):
                    pedacos.append(pedaco)
            if len(pedacos) > 1 and len(pedacos[-1].split()) < 2:     # e a última palavra sozinha, do anterior
                pedacos[-2:] = [f"{pedacos[-2]}, {pedacos[-1]}"]
            frases += [[pedaco, na_virgula] for pedaco in pedacos[:-1]] + [[pedacos[-1], na_frase]]
            continue
        frases.append([frase, pausa])
    if frases:
        frases[-1][1] = 0.0
    return frases or [[texto, 0.0]]


# ----------------------------------------------------------------- as vozes
def separar_variante(voz: str) -> tuple[str, str]:
    """'Ana Florence · jovem' -> ('Ana Florence', 'jovem'); sem variante -> (voz, '')."""
    base, separador, variante = str(voz or "").rpartition(SEPARADOR_VARIANTE)
    return (base, variante) if separador and base and variante in VARIANTES else (voz, "")


def com_variante(voz: str, variante: str) -> str:
    """('Ana Florence', 'jovem') -> 'Ana Florence · jovem' (variante vazia ou desconhecida: a voz como está)."""
    base = separar_variante(voz)[0]
    return f"{base}{SEPARADOR_VARIANTE}{variante}" if variante in VARIANTES else base


def vozes_por_genero(genero: str, variantes: bool = False) -> list[str]:
    """As vozes prontas do gênero; com variantes, depois delas as variantes de cada uma (grave, aguda, jovem)."""
    base = [v for v, perfil in VOZES_PRONTAS.items() if perfil.startswith(genero)]
    return base + ([com_variante(v, n) for n in VARIANTES for v in base] if variantes else [])


def texto_do_menu(voz: str) -> str:
    """'Ana Florence' -> 'Ana Florence (feminina, adulta)'; 'Ana Florence · jovem' -> '... (feminina, jovem)'."""
    perfil = perfil_da_voz(voz)
    return f"{voz} ({perfil})" if perfil and separar_variante(voz)[0] in VOZES_PRONTAS else voz


def valor_do_menu(texto: str) -> str:
    """'Ana Florence (feminina, adulta)' -> 'Ana Florence'; 'Importada: Izael (masculina, adulta)' -> 'imp:izael'."""
    from .vozes_importadas import criar_id
    if texto.startswith("Importada: "):
        return PREFIXO_IMPORTADA + criar_id(texto[len("Importada: "):].split(" (")[0])
    return texto.split(" (")[0].strip()


def menu_da_importada(v) -> str:
    return f"Importada: {v.nome} ({v.perfil})"


def perfil_da_voz(voz: str, importadas: list = ()) -> str:
    """'feminina, adulta' (ou '' se não sabe) de uma voz pronta ou importada; da variante, 'feminina, jovem'."""
    voz, variante = separar_variante(voz)
    if voz.startswith(PREFIXO_IMPORTADA):
        achada = next((v for v in importadas if v.id == voz[len(PREFIXO_IMPORTADA):]), None)
        perfil = achada.perfil if achada else ""
    else:
        perfil = VOZES_PRONTAS.get(voz, "")
    if perfil and variante:
        return f"{perfil.split(',')[0]}, {PERFIL_DA_VARIANTE[variante]}"
    return perfil


def equivalente(voz: str) -> str:
    """Uma voz do Gemini ("Kore", feminina) vira uma voz pronta do mesmo gênero, sempre a mesma para o mesmo nome."""
    from .voz_gemini import VOZES as GEMINI
    genero = "feminina" if GEMINI.get(voz, "").startswith("feminina") else "masculina"
    opcoes = vozes_por_genero(genero)
    return opcoes[int(hashlib.md5(voz.encode()).hexdigest(), 16) % len(opcoes)]


# ----------------------------------------------------------------- conferir cada fala com o Whisper
# O XTTS-v2 às vezes "inventa" um pedacinho no fim da frase ("nas árvores.u.") ou embola uma palavra no meio (no
# teste de comparação: 3 de 9 falas). O Whisper (no PC) ouve a fala gerada: sobra no fim -> corta logo depois da
# última palavra certa; embolada no meio (ou quase nada certo) -> gera de novo (até 2 vezes) e fica a melhor.
TENTATIVAS = 3
FOLGA_DO_CORTE = 0.08          # segundos depois do fim da última palavra certa


def _palavras(texto: str) -> list[str]:
    import re
    import unicodedata
    texto = unicodedata.normalize("NFD", texto.lower())
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9 ]+", " ", texto).split()


def avaliar(esperado: str, ouvidas: list[tuple[str, float, float]]) -> tuple[str, float | None, float]:
    """("ok" | "cortar" | "refazer", onde cortar em segundos, nota de 0 a 1). ouvidas: [(palavra, início, fim)]."""
    from difflib import SequenceMatcher
    alvo = _palavras(esperado)
    ditas = [(p, ini, fim) for palavra, ini, fim in ouvidas for p in _palavras(palavra)[:1]]
    if not alvo:
        return "ok", None, 1.0
    casamento = SequenceMatcher(None, alvo, [d[0] for d in ditas], autojunk=False)
    nota = casamento.ratio()
    blocos = [b for b in casamento.get_matching_blocks() if b.size]
    if not blocos or sum(b.size for b in blocos) / len(alvo) < 0.7:
        return "refazer", None, nota
    no_meio = sum(max(0, b2.b - (b1.b + b1.size)) for b1, b2 in zip(blocos, blocos[1:])
                  if b2.a == b1.a + b1.size)               # palavra a mais entre duas certas seguidas
    if no_meio:
        return "refazer", None, nota
    ultimo = blocos[-1]
    sobra = len(ditas) - (ultimo.b + ultimo.size)
    if sobra and ultimo.a + ultimo.size == len(alvo):      # o texto acabou e veio mais coisa: corta
        return "cortar", ditas[ultimo.b + ultimo.size - 1][2] + FOLGA_DO_CORTE, nota
    return "ok", None, nota


def cortar_wav(wav: Path, segundos: float) -> None:
    import wave
    with wave.open(str(wav), "rb") as w:
        params, taxa = w.getparams(), w.getframerate()
        quadros = w.readframes(min(w.getnframes(), max(int(segundos * taxa), int(0.3 * taxa))))
    with wave.open(str(wav), "wb") as w:
        w.setparams(params)
        w.writeframes(quadros)


class ConferidorWhisper:
    """conferir(texto, wav) -> (ação, corte, nota): o Whisper do Maestro ouve a fala gerada (modelo "base": rápido)."""

    def __init__(self, transcritor):
        self.transcritor = transcritor

    def __call__(self, texto: str, wav: Path) -> tuple[str, float | None, float]:
        self.transcritor._carregar()
        segmentos, _ = self.transcritor.motor.transcribe(str(wav), language="pt", word_timestamps=True,
                                                         beam_size=1, vad_filter=False)
        palavras = [(p.word, p.start, p.end) for s in segmentos for p in (s.words or [])]
        return avaliar(texto, palavras)


# ----------------------------------------------------------------- instalar o pacote
def python_do_motor(pasta: str | Path, sistema: str = sys.platform) -> Path:
    ambiente = Path(pasta) / "ambiente"
    return ambiente / ("Scripts/python.exe" if sistema == "win32" else "bin/python")


def arquivo_servidor(pasta: str | Path) -> Path:
    return Path(pasta) / "servidor.py"


def instalado(pasta: str | Path) -> dict | None:
    """O que foi instalado ({"gpu": True, "versao": ...}) ou None se o pacote não está pronto."""
    marca = Path(pasta) / "instalado.json"
    if not (marca.is_file() and python_do_motor(pasta).is_file()):
        return None
    try:
        return json.loads(marca.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def tem_placa_nvidia(executar=subprocess.run) -> bool:
    programa = shutil.which("nvidia-smi")
    if not programa:
        return False
    try:
        r = executar([programa, "-L"], capture_output=True, text=True, timeout=20, **SEM_JANELA)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0 and "GPU" in (r.stdout or "")


def espaco_livre(pasta: str | Path) -> float | None:
    """GB livres no disco da pasta (a pasta ainda não existe: o disco da 1ª que existe acima), ou None."""
    alvo = Path(pasta).absolute()
    while not alvo.exists() and alvo.parent != alvo:
        alvo = alvo.parent
    try:
        return shutil.disk_usage(alvo).free / 1e9
    except OSError:
        return None


def conferir_espaco(pasta: str | Path, precisa: float, medir=espaco_livre, o_que: str = "o motor de vozes") -> None:
    """ErroDublagem em português se o disco não tem `precisa` GB livres (em vez de falhar no meio da instalação)."""
    livre = medir(pasta)
    if livre is not None and livre < precisa:
        disco = Path(pasta).absolute().anchor or str(pasta)
        raise ErroDublagem(f"falta espaço no disco {disco}: {o_que} precisa de uns {precisa:.0f} GB livres e há "
                           f"{livre:.1f} GB. Libere espaço (apague arquivos grandes ou esvazie a Lixeira) e tente de "
                           "novo")


def _ambiente_do_uv(pasta: Path) -> dict:
    """Tudo do uv dentro da pasta do pacote (apagar a pasta desinstala tudo)."""
    return {**os.environ, "UV_PYTHON_INSTALL_DIR": str(pasta / "python"), "UV_CACHE_DIR": str(pasta / "cache"),
            "UV_NO_PROGRESS": "1"}


def _executavel_uv(pasta: Path, sistema: str) -> Path:
    return pasta / "uv" / ("uv.exe" if sistema == "win32" else "uv")


def _preparar_uv(pasta: Path, sistema: str, baixar) -> Path:
    exe = _executavel_uv(pasta, sistema)
    if exe.is_file():
        return exe
    if sistema not in ARQUIVOS_UV:
        raise ErroDublagem(f"o motor de vozes não tem instalador para este sistema ({sistema})")
    destino = pasta / "uv"
    destino.mkdir(parents=True, exist_ok=True)
    pacote = destino / ARQUIVOS_UV[sistema]
    baixar(URL_UV + ARQUIVOS_UV[sistema], pacote, None)
    try:
        if pacote.suffix == ".zip":
            with zipfile.ZipFile(pacote) as z:
                z.extractall(destino)
        else:
            with tarfile.open(pacote) as t:
                t.extractall(destino, filter="data")
    except (zipfile.BadZipFile, tarfile.TarError, OSError) as erro:
        raise ErroDublagem(f"o pacote do uv veio estragado ({erro}); tente de novo") from erro
    finally:
        pacote.unlink(missing_ok=True)
    achado = next((p for p in destino.rglob(exe.name) if p.is_file()), None)
    if achado is None:
        raise ErroDublagem("o pacote do uv não tinha o programa esperado")
    if achado != exe:
        shutil.move(str(achado), exe)
    if sistema != "win32":
        exe.chmod(0o755)
    return exe


def instalar(pasta: str | Path, gpu: bool | None = None, sistema: str = sys.platform, baixar=_baixar,
             executar=subprocess.run, ao_progresso=None, parar=None, medir_espaco=espaco_livre) -> dict:
    """Instala (ou completa) o pacote: uv -> Python 3.12 -> PyTorch (placa de vídeo ou processador) -> coqui-tts.
    Devolve o que ficou instalado. Pode demorar (o PyTorch para a placa de vídeo tem ~3 GB). Antes, confere se o
    disco tem espaço (sem ele, a instalação parava no meio com um erro em inglês)."""
    pasta = Path(pasta)
    if gpu is None:
        gpu = tem_placa_nvidia(executar)
    conferir_espaco(pasta, ESPACO_ATUALIZAR if instalado(pasta) else ESPACO_GPU if gpu else ESPACO_CPU,
                    medir_espaco)
    pasta.mkdir(parents=True, exist_ok=True)
    etapa = _etapas(ao_progresso, parar)
    instalar_pacote(pasta, pasta, VERSAO_PYTHON, TORCH, INDICE_GPU if gpu else INDICE_CPU, PACOTES,
                    "o XTTS-v2 (coqui-tts)", gpu, sistema, baixar, executar, etapa)
    arquivo_servidor(pasta).write_text(SERVIDOR, encoding="utf-8")
    info = {"gpu": gpu, "torch": TORCH[0], "pacotes": PACOTES, "uv": VERSAO_UV}
    (pasta / "instalado.json").write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
    etapa(1.0, "Motor de vozes instalado.")
    return info


def _etapas(ao_progresso, parar):
    def etapa(fracao: float, texto: str) -> None:
        if parar and parar():
            raise ErroDublagem("interrompido (botão Parar)")
        if ao_progresso:
            ao_progresso(fracao, texto)
    return etapa


def instalar_pacote(pasta_uv: Path, destino: Path, versao_python: str, torch: list, indice: str, pacotes: list,
                    nome: str, gpu: bool, sistema: str, baixar, executar, etapa) -> None:
    """uv -> Python -> PyTorch -> os pacotes, no ambiente destino/ambiente. O uv, os Pythons baixados e o cache ficam
    em pasta_uv (o 2º motor, o Chatterbox, usa os mesmos: não baixa o uv de novo)."""
    ambiente = _ambiente_do_uv(Path(pasta_uv))

    def rodar(argumentos: list[str], quanto: str) -> None:
        r = executar(argumentos, capture_output=True, text=True, env=ambiente, timeout=3 * 3600, **SEM_JANELA)
        if r.returncode != 0:
            detalhe = ((r.stderr or "") + (r.stdout or "")).strip().splitlines()
            raise ErroDublagem(f"não deu para instalar {quanto}: {detalhe[-1] if detalhe else r.returncode}")

    etapa(0.02, "Baixando o instalador (uv)...")
    uv = str(_preparar_uv(Path(pasta_uv), sistema, baixar))
    python = python_do_motor(destino, sistema)
    if not python.is_file():
        etapa(0.08, f"Baixando o Python {versao_python} do motor de vozes...")
        rodar([uv, "venv", str(Path(destino) / "ambiente"), "--python", versao_python], f"o Python {versao_python}")
    etapa(0.15, "Baixando o PyTorch " + ("para a placa de vídeo (~3 GB, a parte mais demorada)..." if gpu
                                         else "para o processador..."))
    rodar([uv, "pip", "install", "--python", str(python), *torch, "--index-url", indice], "o PyTorch")
    etapa(0.80, f"Instalando {nome}...")
    rodar([uv, "pip", "install", "--python", str(python), *pacotes], nome)


def desinstalar(pasta: str | Path) -> None:
    shutil.rmtree(pasta, ignore_errors=True)


# ----------------------------------------------------------------- o "interfone" com o servidor
class ServidorDeVoz:
    """Um "estúdio" (servidor.py no Python de um pacote) que fica aberto e fala cada pedido que chega: o Maestro
    manda uma linha JSON pela entrada dele e lê a resposta na saída (o que a biblioteca escreve vai para o
    registro.txt). Base do XTTS-v2 (MotorLocal) e do Chatterbox (voz_emocao.MotorEmocao)."""

    nome = "o motor de vozes"
    registro = "motor_vozes/registro.txt"     # onde ver o que deu errado (na pasta das configurações)

    def __init__(self, abrir=subprocess.Popen, avisar=None):
        self._abrir, self.avisar = abrir, avisar
        self._processo = None
        self._respostas: queue.Queue = queue.Queue()
        self.dispositivo = self.placa = ""
        self.memoria: float | None = None          # GB da placa de vídeo (None: processador ou não informou)

    def _ler_saida(self, saida, respostas: queue.Queue) -> None:
        """Lê as respostas de UM processo para a fila DELE (o recado "fechou" de um processo já fechado não pode
        cair na fila do novo, quando o servidor é aberto de novo)."""
        for linha in saida:
            linha = linha.strip()
            if linha.startswith("{"):
                try:
                    respostas.put(json.loads(linha))
                except ValueError:
                    pass
        respostas.put({"erro": f"{self.nome} fechou sozinho (veja o {self.registro})"})

    def _resposta(self, limite: float, parar=None) -> dict:
        fim = limite
        while fim > 0:
            try:
                return self._respostas.get(timeout=1.0)
            except queue.Empty:
                fim -= 1.0
                if parar and parar():
                    self.fechar()
                    raise ErroDublagem("interrompido (botão Parar)")
        self.fechar()
        raise ErroDublagem(f"{self.nome} não respondeu a tempo")

    def aberto(self) -> bool:
        return self._processo is not None and self._processo.poll() is None

    def _abrir_servidor(self, python: Path, servidor: Path, codigo: str, ambiente: dict, pasta: Path,
                        carregando: str, parar=None) -> dict:
        """Abre o servidor e espera ele dizer que está pronto (na 1ª vez, baixando o modelo)."""
        if not servidor.is_file() or servidor.read_text(encoding="utf-8") != codigo:   # versão nova do Maestro
            servidor.write_text(codigo, encoding="utf-8")
        registro = open(pasta / "registro.txt", "a", encoding="utf-8", errors="replace")
        self._processo = self._abrir([str(python), "-u", str(servidor)], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=registro, text=True, encoding="utf-8",
                                     env=ambiente, cwd=str(pasta), **SEM_JANELA)
        registro.close()
        self._respostas = queue.Queue()
        threading.Thread(target=self._ler_saida, args=(self._processo.stdout, self._respostas), daemon=True).start()
        if self.avisar:
            self.avisar(carregando)
        pronto = self._resposta(TEMPO_PARA_CARREGAR, parar)
        if not pronto.get("pronto"):
            self.fechar()
            raise ErroDublagem(f"{self.nome} não abriu: {pronto.get('erro', 'sem resposta')}")
        self.dispositivo, self.placa = pronto.get("dispositivo", ""), pronto.get("placa", "")
        self.memoria = pronto.get("memoria")
        if self.avisar:
            if pronto.get("aviso"):
                self.avisar(f"{self.nome}: {pronto['aviso']} (mais devagar, mas termina)")
            memoria = f", {self.memoria:g} GB" if self.placa and self.memoria else ""
            self.avisar(f"{self.nome} pronto ({'placa de vídeo ' + self.placa + memoria if self.placa else 'processador'})")
        return pronto

    def _pedir(self, pedido: dict, parar=None, limite: float = 600) -> dict:
        self._processo.stdin.write(json.dumps(pedido, ensure_ascii=False) + "\n")
        self._processo.stdin.flush()
        resposta = self._resposta(limite, parar)
        if resposta.get("dispositivo") == "cpu" and self.dispositivo == "cuda":     # plano B no meio do trabalho
            self.dispositivo, self.placa = "cpu", ""
            if self.avisar:
                self.avisar(f"{self.nome}: a placa de vídeo não aguentou (pouca memória, ou placa não suportada); "
                            "segue pelo processador, mais devagar")
        return resposta

    def fechar(self) -> None:
        processo, self._processo = self._processo, None
        if processo is None:
            return
        try:
            if processo.poll() is None:
                processo.stdin.write(json.dumps({"cmd": "sair"}) + "\n")
                processo.stdin.flush()
                processo.wait(timeout=10)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            processo.kill()

    def __del__(self):
        try:
            self.fechar()
        except Exception:
            pass


# ----------------------------------------------------------------- o motor
class MotorLocal(ServidorDeVoz):
    """A voz da dublagem pelo XTTS-v2 no PC. sintetizar(pedidos): [(texto, wav[, voz[, tom]])]; a voz de cada fala:
    vazia (a principal), uma pronta ("Ana Florence"), uma importada ("imp:izael"), uma do Gemini (vira a
    equivalente) ou uma clonada do Gemini ("clone:Izael": a importada de mesmo nome, se houver). O tom (a nota de
    direção) diz a EMOÇÃO: a fala vai com a gravação daquela emoção da voz, ou com o Chatterbox (emocao), ou neutra."""

    expressiva = False                  # não interpreta o tom da cena como o Gemini: a emoção vai pela gravação
    modelo = "xtts_v2"

    def __init__(self, pasta: str | Path, voz: str = VOZ_PADRAO, importadas: list = (), pasta_importadas=None,
                 abrir=subprocess.Popen, avisar=None, idioma: str = "pt", conferir=None, emocao=None,
                 forca_emocao: float = 0.0, ffmpeg: str | None = None):
        super().__init__(abrir, avisar)
        self.pasta, self.voz, self.idioma = Path(pasta), voz or VOZ_PADRAO, idioma
        self.conferir = conferir                 # ConferidorWhisper (ou None: sem conferir)
        self.emocao = emocao                     # voz_emocao.MotorEmocao (o Chatterbox) ou None
        self.forca = forca_emocao                # a interpretação (atuacao.py): 0 = desligada (padrão), 1 = "Forte"
        self.ffmpeg = ffmpeg                     # (só para subir ou descer o tom; None = o do sistema)
        self.cortadas = self.refeitas = 0
        self.com_emocao: Counter = Counter()     # "gravação" / "chatterbox": quantas falas foram com emoção
        self.interpretadas: Counter = Counter()  # emoção -> quantas falas a interpretação mudou
        self.variadas: Counter = Counter()       # variante -> quantas falas ("grave", "aguda", "jovem")
        self.como_ficou: dict[str, str] = {}     # emoção -> o que a interpretação fez (para o registro)
        self.importadas, self.pasta_importadas = list(importadas), pasta_importadas
        self.pedidos = 0

    @property
    def estilo(self) -> str:
        """Entra no nome das falas guardadas (dublagem._assinatura): trocar a força da emoção gera as falas de novo
        (na "Desligada", os mesmos nomes da v2.20)."""
        return f"interpretação {self.forca:g}" if self.forca > 0 else ""

    # --- o servidor
    def iniciar(self, parar=None) -> None:
        if self.aberto():
            return
        python = python_do_motor(self.pasta)
        if not instalado(self.pasta) or not python.is_file():
            raise ErroDublagem("o motor de vozes XTTS-v2 não está instalado: Configurações > Dublagem > \"Instalar "
                               "o motor de vozes\"")
        ambiente = {**os.environ, "COQUI_TOS_AGREED": "1", "TTS_HOME": str(self.pasta / "modelos"),
                    "HF_HOME": str(self.pasta / "modelos" / "hf"), "PYTHONIOENCODING": "utf-8",
                    "PYTHONUNBUFFERED": "1", "MAESTRO_MODELO": MODELO}
        self._abrir_servidor(python, arquivo_servidor(self.pasta), SERVIDOR, ambiente, self.pasta,  # (nos testes,
                             "carregando o motor de vozes XTTS-v2 (na 1ª vez baixa o modelo, ~1,8 GB)", parar)  # outro)

    def fechar(self) -> None:
        super().fechar()
        if getattr(self, "emocao", None) is not None:
            self.emocao.fechar()

    # --- as falas
    def _resolver(self, voz: str) -> tuple[dict, object]:
        """({"voz": nome pronto} ou {"referencia": wav importado}, a VozImportada ou None)."""
        from .vozes_importadas import GRAVACAO, PIPER, arquivo_da_gravacao
        voz = separar_variante(voz or self.voz)[0]          # a variante entra depois (_variar), na fala pronta
        if voz.startswith("clone:"):                    # clonada do Gemini: a importada de mesmo nome, se houver
            nome = voz[len("clone:"):].lower()
            achada = next((v for v in self.importadas if v.nome.lower() == nome and v.tipo == GRAVACAO), None)
            voz = PREFIXO_IMPORTADA + achada.id if achada else self.voz
        if voz.startswith(PREFIXO_IMPORTADA):
            ident = voz[len(PREFIXO_IMPORTADA):]
            achada = next((v for v in self.importadas if v.id == ident and v.tipo != PIPER), None)
            if achada is not None and self.pasta_importadas is not None:
                return {"referencia": str(arquivo_da_gravacao(achada, self.pasta_importadas))}, achada
            voz = VOZ_PADRAO
        if voz not in VOZES_PRONTAS:
            voz = equivalente(voz)
        return {"voz": voz}, None

    def _voz_do_pedido(self, voz: str) -> dict:
        return self._resolver(voz)[0]

    def _jeito(self, emocao: str) -> str:
        """A emoção que muda o jeito de falar (as pausas, o "!"): nenhuma com a interpretação desligada."""
        return emocao if self.forca > 0 else NORMAL

    def _falar(self, texto: str, saida: Path, voz: dict, parar, emocao: str = NORMAL) -> None:
        self.iniciar(parar)                    # (fechado para o Chatterbox usar a placa: abre de novo)
        pedido = {"texto": texto, "frases": frases_para_falar(texto, self._jeito(emocao)),
                  "saida": str(Path(saida).absolute()),
                  "idioma": self.idioma, **voz}          # caminho completo: o servidor trabalha em outra pasta
        resposta = self._pedir(pedido, parar)
        if not resposta.get("ok"):
            raise ErroDublagem(f"o motor de vozes não gerou a fala: {resposta.get('erro', 'sem resposta')}")
        self.pedidos += 1

    def referencia_da_pronta(self, voz: str, parar=None) -> Path:
        """A fala de referência de uma voz PRONTA (para o Chatterbox imitar): gerada uma vez pelo XTTS-v2."""
        from .vozes_importadas import criar_id
        destino = self.pasta / "referencias" / f"{criar_id(voz)}.wav"
        if not destino.is_file():
            destino.parent.mkdir(parents=True, exist_ok=True)
            temporario = destino.with_suffix(".tmp.wav")
            self._falar(FRASE_DE_REFERENCIA, temporario, {"voz": voz}, parar)
            temporario.replace(destino)
        return destino

    def _como_falar(self, voz: str, emocao: str, parar) -> tuple[str, object]:
        """(modo, falar(texto, saida)) da fala: "gravação" (a gravação da emoção, pelo XTTS-v2), "chatterbox" ou
        "xtts" (neutra). A fala de referência que o Chatterbox imita já sai aqui (com o XTTS-v2 aberto)."""
        from .vozes_importadas import arquivo_da_emocao
        xtts, importada = self._resolver(voz)
        if emocao != NORMAL:
            gravacao = (arquivo_da_emocao(importada, self.pasta_importadas, emocao)
                        if importada is not None and self.pasta_importadas is not None else None)
            if gravacao is not None:
                self.com_emocao["gravação"] += 1
                return "gravação", lambda texto, saida: self._falar(texto, saida, {"referencia": str(gravacao)},
                                                                     parar, emocao)
            if self.emocao is not None:
                referencia = xtts.get("referencia") or str(self.referencia_da_pronta(xtts["voz"], parar))
                self.com_emocao["chatterbox"] += 1
                return "chatterbox", lambda texto, saida: self._falar_com_emocao(texto, saida, referencia, emocao,
                                                                                xtts, parar)
        return "xtts", lambda texto, saida: self._falar(texto, saida, xtts, parar, emocao)

    def _falar_com_emocao(self, texto: str, saida: Path, referencia: str, emocao: str, xtts: dict, parar) -> None:
        """Pelo Chatterbox; se ele falhar (não abriu, sem memória...), o resto segue neutro pelo XTTS-v2."""
        if self.emocao is not None:
            try:
                self.emocao.falar(texto, saida, referencia, emocao, parar, idioma=self.idioma, forca=self.forca)
                self.pedidos += 1
                return
            except ErroDublagem as erro:
                if parar and parar():
                    raise
                if self.avisar:
                    self.avisar(f"o Chatterbox falhou ({str(erro)[:150]}): as falas com emoção seguem neutras pelo "
                                "XTTS-v2")
                self.emocao.fechar()
                self.emocao = None
        self._falar(texto, saida, xtts, parar, emocao)

    def _falar_conferindo(self, texto: str, wav: Path, falar) -> None:
        """Gera; com o conferidor, corta a sobra do fim ou gera de novo a embolada (fica a de melhor nota)."""
        falar(texto, wav)
        if self.conferir is None:
            return
        melhor = None
        for tentativa in range(TENTATIVAS):
            atual = wav if tentativa == 0 else wav.with_name(f"{wav.stem}-tentativa{tentativa}.wav")
            if tentativa:
                falar(texto, atual)
            try:
                acao, corte, nota = self.conferir(texto, atual)
            except Exception as erro:                      # sem o Whisper: fica como saiu
                if self.avisar:
                    self.avisar(f"não deu para conferir as falas com o Whisper ({str(erro)[:120]}): seguem sem")
                self.conferir = None
                return
            if acao == "cortar":
                cortar_wav(atual, corte)
                self.cortadas += 1
                acao = "ok"
            if melhor is None or nota > melhor[1]:
                melhor = (atual, nota)
            if acao == "ok":
                melhor = (atual, nota)
                break
        if melhor[0] != wav:
            shutil.move(str(melhor[0]), wav)
            self.refeitas += 1
        for sobra in wav.parent.glob(f"{wav.stem}-tentativa*.wav"):
            sobra.unlink(missing_ok=True)

    def _ffmpeg(self) -> str | None:
        if self.ffmpeg is None:
            from .dublagem import localizar_ffmpeg
            self.ffmpeg = localizar_ffmpeg() or ""
        return self.ffmpeg or None

    def _variar(self, wav: Path, voz: str) -> None:
        """A variante da voz ("Ana Florence · jovem"): outro tom e outra garganta na fala já conferida (e antes da
        interpretação). Também na fala do Chatterbox, que imitou a voz de base."""
        base, variante = separar_variante(voz or self.voz)
        if not variante:
            return
        from . import atuacao
        genero = "feminina" if perfil_da_voz(base, self.importadas).startswith("feminina") else "masculina"
        semitons, formantes = VARIANTES[variante][genero]
        if atuacao.variar(wav, semitons, formantes, self._ffmpeg()):
            self.variadas[variante] += 1

    def _interpretar(self, wav: Path, emocao: str) -> None:
        """A interpretação da emoção (atuacao.py) na fala já conferida: o choro treme, a raiva rasga..."""
        if emocao == NORMAL or self.forca <= 0:
            return
        from . import atuacao
        feito = atuacao.interpretar(wav, emocao, self.forca, self._ffmpeg())
        if feito:
            self.interpretadas[emocao] += 1
            self.como_ficou[emocao] = atuacao.resumo(feito)

    def um_de_cada_vez(self) -> bool:
        """Na placa de vídeo com pouca memória (até 12 GB; a RTX 4060 tem 8), o XTTS-v2 e o Chatterbox não ficam
        abertos juntos (somam ~7-8 GB e estourariam: o plano B mandaria o Chatterbox para o processador, lento)."""
        return self.dispositivo == "cuda" and (self.memoria is None or self.memoria < JUNTOS_NA_PLACA_GB)

    def sintetizar(self, pedidos: list, parar=None, ao_progresso=None) -> None:
        """As falas. Na placa pequena, em duas passadas: todas as do XTTS-v2 (e as falas de referência que o
        Chatterbox imita); fecha o XTTS-v2; depois as com emoção pelo Chatterbox."""
        if self.emocao is not None and self.emocao.aberto() and self.um_de_cada_vez():
            self.emocao.fechar()                 # a vez é do XTTS-v2 (o Chatterbox ficou aberto da vez anterior)
        self.iniciar(parar)
        total, feitas, depois = max(1, len(pedidos)), 0, []
        for p in pedidos:
            if parar and parar():
                raise ErroDublagem("interrompido (botão Parar)")
            voz, nota = (p[2] if len(p) > 2 and p[2] else ""), (p[3] if len(p) > 3 else "")
            emocao = emocao_da_nota(nota)
            modo, falar = self._como_falar(voz, emocao, parar)
            if modo == "chatterbox" and self.um_de_cada_vez():
                depois.append((p[0], Path(p[1]), falar, emocao, voz))
                continue
            self._falar_conferindo(p[0], Path(p[1]), falar)
            self._variar(Path(p[1]), voz)
            self._interpretar(Path(p[1]), emocao)
            feitas += 1
            if ao_progresso:
                ao_progresso(feitas / total)
        if depois:
            if self.avisar:
                memoria = f" ({self.memoria:g} GB)" if self.memoria else ""
                self.avisar(f"um de cada vez na placa{memoria}: fechando o XTTS-v2 para o Chatterbox fazer as "
                            f"{len(depois)} fala(s) com emoção")
            ServidorDeVoz.fechar(self)           # só o XTTS-v2 (o Chatterbox abre agora)
            for texto, wav, falar, emocao, voz in depois:
                if parar and parar():
                    raise ErroDublagem("interrompido (botão Parar)")
                self._falar_conferindo(texto, wav, falar)
                self._variar(wav, voz)
                self._interpretar(wav, emocao)
                feitas += 1
                if ao_progresso:
                    ao_progresso(feitas / total)
        if (self.cortadas or self.refeitas) and self.avisar:
            self.avisar(f"conferência pelo Whisper: {self.cortadas} fala(s) com sobra no fim cortada(s), "
                        f"{self.refeitas} gerada(s) de novo")
        if self.com_emocao and self.avisar:
            self.avisar(f"emoção: {self.com_emocao['gravação']} fala(s) com a gravação de emoção da voz, "
                        f"{self.com_emocao['chatterbox']} pelo Chatterbox")
            self.com_emocao.clear()
        if self.variadas and self.avisar:
            self.avisar("variantes das vozes: " + ", ".join(f"{n} fala(s) {v}" for v, n in self.variadas.items()))
            self.variadas.clear()
        if self.interpretadas and self.avisar:
            self.avisar("interpretação da emoção: " + "; ".join(
                f"{n} fala(s) {nome_da_emocao(e).lower()} ({self.como_ficou[e]})" for e, n in self.interpretadas.items()))
            self.interpretadas.clear()
