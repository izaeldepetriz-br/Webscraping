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
from pathlib import Path

from .dublagem import SEM_JANELA, ErroDublagem, _baixar

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
FRASE_DE_TESTE = "Olá! Esta é a voz que vai dublar os seus vídeos, aqui no seu computador, sem custo."

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


try:
    import torch
    from TTS.api import TTS
    dispositivo = "cuda" if torch.cuda.is_available() else "cpu"
    tts = TTS(os.environ.get("MAESTRO_MODELO", "tts_models/multilingual/multi-dataset/xtts_v2")).to(dispositivo)
    placa = torch.cuda.get_device_name(0) if dispositivo == "cuda" else ""
    responder({"pronto": True, "dispositivo": dispositivo, "placa": placa, "vozes": list(tts.speakers or [])})
except Exception as erro:
    responder({"erro": f"{type(erro).__name__}: {erro}"})
    sys.exit(1)

for linha in sys.stdin:
    try:
        pedido = json.loads(linha)
        if pedido.get("cmd") == "sair":
            break
        voz = {"speaker_wav": pedido["referencia"]} if pedido.get("referencia") else {"speaker": pedido["voz"]}
        tts.tts_to_file(pedido["texto"], language=pedido.get("idioma", "pt"), file_path=pedido["saida"],
                        split_sentences=True, **voz)
        responder({"ok": True})
    except Exception as erro:
        responder({"erro": f"{type(erro).__name__}: {erro}"})
'''


# ----------------------------------------------------------------- as vozes
def vozes_por_genero(genero: str) -> list[str]:
    return [v for v, perfil in VOZES_PRONTAS.items() if perfil.startswith(genero)]


def texto_do_menu(voz: str) -> str:
    """'Ana Florence' -> 'Ana Florence (feminina, adulta)'."""
    return f"{voz} ({VOZES_PRONTAS[voz]})" if voz in VOZES_PRONTAS else voz


def valor_do_menu(texto: str) -> str:
    """'Ana Florence (feminina, adulta)' -> 'Ana Florence'; 'Importada: Izael (masculina, adulta)' -> 'imp:izael'."""
    from .vozes_importadas import criar_id
    if texto.startswith("Importada: "):
        return PREFIXO_IMPORTADA + criar_id(texto[len("Importada: "):].split(" (")[0])
    return texto.split(" (")[0].strip()


def menu_da_importada(v) -> str:
    return f"Importada: {v.nome} ({v.perfil})"


def perfil_da_voz(voz: str, importadas: list = ()) -> str:
    """'feminina, adulta' (ou '' se não sabe) de uma voz pronta ou importada."""
    if voz.startswith(PREFIXO_IMPORTADA):
        achada = next((v for v in importadas if v.id == voz[len(PREFIXO_IMPORTADA):]), None)
        return achada.perfil if achada else ""
    return VOZES_PRONTAS.get(voz, "")


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
             executar=subprocess.run, ao_progresso=None, parar=None) -> dict:
    """Instala (ou completa) o pacote: uv -> Python 3.12 -> PyTorch (placa de vídeo ou processador) -> coqui-tts.
    Devolve o que ficou instalado. Pode demorar (o PyTorch para a placa de vídeo tem ~3 GB)."""
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    if gpu is None:
        gpu = tem_placa_nvidia(executar)
    ambiente = _ambiente_do_uv(pasta)

    def etapa(fracao: float, texto: str) -> None:
        if parar and parar():
            raise ErroDublagem("interrompido (botão Parar)")
        if ao_progresso:
            ao_progresso(fracao, texto)

    def rodar(argumentos: list[str], quanto: str) -> None:
        r = executar(argumentos, capture_output=True, text=True, env=ambiente, timeout=3 * 3600, **SEM_JANELA)
        if r.returncode != 0:
            detalhe = ((r.stderr or "") + (r.stdout or "")).strip().splitlines()
            raise ErroDublagem(f"não deu para instalar {quanto}: {detalhe[-1] if detalhe else r.returncode}")

    etapa(0.02, "Baixando o instalador (uv)...")
    uv = str(_preparar_uv(pasta, sistema, baixar))
    python = python_do_motor(pasta, sistema)
    if not python.is_file():
        etapa(0.08, f"Baixando o Python {VERSAO_PYTHON} do motor de vozes...")
        rodar([uv, "venv", str(pasta / "ambiente"), "--python", VERSAO_PYTHON], f"o Python {VERSAO_PYTHON}")
    etapa(0.15, "Baixando o PyTorch " + ("para a placa de vídeo (~3 GB, a parte mais demorada)..." if gpu
                                         else "para o processador..."))
    rodar([uv, "pip", "install", "--python", str(python), *TORCH, "--index-url", INDICE_GPU if gpu else INDICE_CPU],
          "o PyTorch")
    etapa(0.80, "Instalando o XTTS-v2 (coqui-tts)...")
    rodar([uv, "pip", "install", "--python", str(python), *PACOTES], "o XTTS-v2 (coqui-tts)")
    arquivo_servidor(pasta).write_text(SERVIDOR, encoding="utf-8")
    info = {"gpu": gpu, "torch": TORCH[0], "pacotes": PACOTES, "uv": VERSAO_UV}
    (pasta / "instalado.json").write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
    etapa(1.0, "Motor de vozes instalado.")
    return info


def desinstalar(pasta: str | Path) -> None:
    shutil.rmtree(pasta, ignore_errors=True)


# ----------------------------------------------------------------- o motor
class MotorLocal:
    """A voz da dublagem pelo XTTS-v2 no PC. sintetizar(pedidos): [(texto, wav[, voz[, tom]])]; a voz de cada fala:
    vazia (a principal), uma pronta ("Ana Florence"), uma importada ("imp:izael"), uma do Gemini (vira a
    equivalente) ou uma clonada do Gemini ("clone:Izael": a importada de mesmo nome, se houver)."""

    expressiva = False                  # não interpreta o tom da cena (só o timbre): sem a nota de direção
    modelo = "xtts_v2"
    estilo = ""

    def __init__(self, pasta: str | Path, voz: str = VOZ_PADRAO, importadas: list = (), pasta_importadas=None,
                 abrir=subprocess.Popen, avisar=None, idioma: str = "pt", conferir=None):
        self.pasta, self.voz, self.idioma = Path(pasta), voz or VOZ_PADRAO, idioma
        self.conferir = conferir                 # ConferidorWhisper (ou None: sem conferir)
        self.cortadas = self.refeitas = 0
        self.importadas, self.pasta_importadas = list(importadas), pasta_importadas
        self._abrir, self.avisar = abrir, avisar
        self._processo = None
        self._respostas: queue.Queue = queue.Queue()
        self.dispositivo = self.placa = ""
        self.pedidos = 0

    # --- o servidor
    def _ler_saida(self, saida) -> None:
        for linha in saida:
            linha = linha.strip()
            if linha.startswith("{"):
                try:
                    self._respostas.put(json.loads(linha))
                except ValueError:
                    pass
        self._respostas.put({"erro": "o motor de vozes fechou sozinho (veja o motor_vozes/registro.txt)"})

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
        raise ErroDublagem("o motor de vozes não respondeu a tempo")

    def iniciar(self, parar=None) -> None:
        if self._processo is not None and self._processo.poll() is None:
            return
        python = python_do_motor(self.pasta)
        if not instalado(self.pasta) or not python.is_file():
            raise ErroDublagem("o motor de vozes XTTS-v2 não está instalado: Configurações > Dublagem > \"Instalar "
                               "o motor de vozes\"")
        if not arquivo_servidor(self.pasta).is_file():
            arquivo_servidor(self.pasta).write_text(SERVIDOR, encoding="utf-8")
        ambiente = {**os.environ, "COQUI_TOS_AGREED": "1", "TTS_HOME": str(self.pasta / "modelos"),
                    "HF_HOME": str(self.pasta / "modelos" / "hf"), "PYTHONIOENCODING": "utf-8",
                    "PYTHONUNBUFFERED": "1", "MAESTRO_MODELO": MODELO}
        registro = open(self.pasta / "registro.txt", "a", encoding="utf-8", errors="replace")
        self._processo = self._abrir([str(python), "-u", str(arquivo_servidor(self.pasta))], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=registro, text=True, encoding="utf-8",
                                     env=ambiente, cwd=str(self.pasta), **SEM_JANELA)
        registro.close()
        threading.Thread(target=self._ler_saida, args=(self._processo.stdout,), daemon=True).start()
        if self.avisar:
            self.avisar("carregando o motor de vozes XTTS-v2 (na 1ª vez baixa o modelo, ~1,8 GB)")
        pronto = self._resposta(TEMPO_PARA_CARREGAR, parar)
        if not pronto.get("pronto"):
            self.fechar()
            raise ErroDublagem(f"o motor de vozes não abriu: {pronto.get('erro', 'sem resposta')}")
        self.dispositivo, self.placa = pronto.get("dispositivo", ""), pronto.get("placa", "")
        if self.avisar:
            self.avisar(f"motor de vozes pronto ({'placa de vídeo ' + self.placa if self.placa else 'processador'})")

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

    # --- as falas
    def _voz_do_pedido(self, voz: str) -> dict:
        """{"voz": nome pronto} ou {"referencia": wav importado}."""
        from .vozes_importadas import GRAVACAO, PIPER, arquivo_da_gravacao
        voz = voz or self.voz
        if voz.startswith("clone:"):                    # clonada do Gemini: a importada de mesmo nome, se houver
            nome = voz[len("clone:"):].lower()
            achada = next((v for v in self.importadas if v.nome.lower() == nome and v.tipo == GRAVACAO), None)
            voz = PREFIXO_IMPORTADA + achada.id if achada else self.voz
        if voz.startswith(PREFIXO_IMPORTADA):
            ident = voz[len(PREFIXO_IMPORTADA):]
            achada = next((v for v in self.importadas if v.id == ident and v.tipo != PIPER), None)
            if achada is not None and self.pasta_importadas is not None:
                return {"referencia": str(arquivo_da_gravacao(achada, self.pasta_importadas))}
            voz = VOZ_PADRAO
        if voz not in VOZES_PRONTAS:
            voz = equivalente(voz)
        return {"voz": voz}

    def _falar(self, texto: str, saida: Path, voz: dict, parar) -> None:
        pedido = {"texto": texto, "saida": str(saida), "idioma": self.idioma, **voz}
        self._processo.stdin.write(json.dumps(pedido, ensure_ascii=False) + "\n")
        self._processo.stdin.flush()
        resposta = self._resposta(600, parar)
        if not resposta.get("ok"):
            raise ErroDublagem(f"o motor de vozes não gerou a fala: {resposta.get('erro', 'sem resposta')}")
        self.pedidos += 1

    def _falar_conferindo(self, texto: str, wav: Path, voz: dict, parar) -> None:
        """Gera; com o conferidor, corta a sobra do fim ou gera de novo a embolada (fica a de melhor nota)."""
        self._falar(texto, wav, voz, parar)
        if self.conferir is None:
            return
        melhor = None
        for tentativa in range(TENTATIVAS):
            atual = wav if tentativa == 0 else wav.with_name(f"{wav.stem}-tentativa{tentativa}.wav")
            if tentativa:
                self._falar(texto, atual, voz, parar)
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

    def sintetizar(self, pedidos: list, parar=None, ao_progresso=None) -> None:
        self.iniciar(parar)
        for n, p in enumerate(pedidos, 1):
            if parar and parar():
                raise ErroDublagem("interrompido (botão Parar)")
            self._falar_conferindo(p[0], Path(p[1]), self._voz_do_pedido(p[2] if len(p) > 2 and p[2] else ""),
                                   parar)
            if ao_progresso:
                ao_progresso(n / len(pedidos))
        if (self.cortadas or self.refeitas) and self.avisar:
            self.avisar(f"conferência pelo Whisper: {self.cortadas} fala(s) com sobra no fim cortada(s), "
                        f"{self.refeitas} gerada(s) de novo")
