"""O modo "Enquanto joga (tradutor de tela)" da aba 🎮 Jogos: ler o texto que aparece na janela do jogo (ou do
emulador) e mostrar a tradução numa janelinha por cima, SEM mexer em nenhum arquivo do jogo. Funciona com qualquer
jogo (PS2 no PCSX2, PS1, jogos de PC). Só jogos para um jogador: em jogo online, programa que lê a tela pode ser
confundido com trapaça pelo anticheat.

    janelas_abertas()        as janelas do Windows (para escolher a do jogo) e onde cada uma está na tela
    capturar(retangulo)      a foto de um pedaço da tela (a janela inteira ou a caixa de diálogo marcada)
    leitor_de_texto()        quem lê o texto da foto (OCR) no PC: o leitor que já vem no Windows 10/11 (de graça,
                             nada sai do PC) ou o Tesseract, se instalado
    TradutorDeTela           o laço: fotografa; quando o texto muda (e para de mudar: o jogo escreve letra por
                             letra), lê, traduz (a mesma frase sai da memória, sem pagar de novo) e mostra
    AtalhoGlobal             a tecla (F9) que traduz na hora, mesmo com o jogo na frente (Windows)
"""

from __future__ import annotations

import ctypes
import json
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

INTERVALO = 0.6               # segundos entre as fotos
MUDOU = 0.4                   # % dos pontos da foto que mudaram para dizer que o texto mudou (o texto é pequeno)
PAROU = 0.05                  # ...e abaixo disso entre duas fotos seguidas: o texto parou de ser escrito
LETRAS_MINIMAS = 3
TECLAS = {f"F{n}": 0x6F + n for n in range(1, 13)}


class ErroTela(Exception):
    pass


@dataclass
class Janela:
    titulo: str
    ident: int                      # o "hwnd" do Windows
    retangulo: tuple                # (esquerda, topo, direita, baixo) na tela
    processo: int = 0

    @property
    def largura(self) -> int:
        return self.retangulo[2] - self.retangulo[0]

    @property
    def altura(self) -> int:
        return self.retangulo[3] - self.retangulo[1]


# ----------------------------------------------------------------- as janelas (Windows)
def janelas_abertas(sistema: str = sys.platform) -> list[Janela]:
    """As janelas visíveis com título (a do PCSX2 primeiro, depois as maiores). Fora do Windows: nenhuma."""
    if sistema != "win32":
        return []
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    janelas: list[Janela] = []
    PROTOTIPO = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cada(hwnd, _):
        if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return True
        tamanho = user32.GetWindowTextLengthW(hwnd)
        if tamanho <= 0:
            return True
        texto = ctypes.create_unicode_buffer(tamanho + 1)
        user32.GetWindowTextW(hwnd, texto, tamanho + 1)
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if rect.right - rect.left > 160 and rect.bottom - rect.top > 120:
            janelas.append(Janela(texto.value, int(hwnd), (rect.left, rect.top, rect.right, rect.bottom),
                                  int(pid.value)))
        return True
    user32.EnumWindows(PROTOTIPO(cada), 0)
    return ordenar_janelas(janelas)


def ordenar_janelas(janelas: list[Janela]) -> list[Janela]:
    emulador = re.compile(r"pcsx2|duckstation|ppsspp|dolphin|retroarch|epsxe|rpcs3|pcsx", re.I)
    return sorted(janelas, key=lambda j: (not emulador.search(j.titulo), -(j.largura * j.altura)))


def retangulo_atual(janela: Janela, sistema: str = sys.platform) -> tuple:
    """Onde a janela está AGORA (ela pode ter sido movida)."""
    if sistema != "win32":
        return janela.retangulo
    from ctypes import wintypes
    rect = wintypes.RECT()
    if ctypes.windll.user32.GetWindowRect(janela.ident, ctypes.byref(rect)):
        return rect.left, rect.top, rect.right, rect.bottom
    return janela.retangulo


def capturar(retangulo: tuple):
    """A foto (PIL.Image) de um pedaço da tela."""
    from PIL import ImageGrab
    esquerda, topo, direita, baixo = (int(v) for v in retangulo)
    if direita - esquerda < 4 or baixo - topo < 4:
        raise ErroTela("a área marcada é pequena demais")
    return ImageGrab.grab(bbox=(esquerda, topo, direita, baixo), all_screens=True)


def diferenca(a, b) -> float:
    """Quantos % dos pontos mudaram de verdade entre duas fotos (0 = iguais, 100 = tudo diferente), numa versão
    menor e em cinza. Conta os pontos (e não a média): uma letra nova numa tela grande muda pouco a média."""
    import numpy as np
    if a is None or b is None:
        return 100.0
    pa = np.asarray(a.convert("L").resize((320, 180)), dtype=np.int16)
    pb = np.asarray(b.convert("L").resize((320, 180)), dtype=np.int16)
    return float((np.abs(pa - pb) > 40).mean() * 100)


# ----------------------------------------------------------------- ler o texto (OCR)
class LeitorWindows:
    """O leitor de texto que vem no Windows 10/11 (Windows.Media.Ocr): rápido, de graça e nada sai do PC. Lê no
    idioma do jogo, se o pacote de idioma estiver instalado (o inglês costuma estar); senão, no do Windows."""
    nome = "Windows (OCR do próprio Windows)"

    def __init__(self, idioma: str = "en-US"):
        from winrt.windows.globalization import Language
        from winrt.windows.media.ocr import OcrEngine
        self._motor = None
        try:
            if OcrEngine.is_language_supported(Language(idioma)):
                self._motor = OcrEngine.try_create_from_language(Language(idioma))
        except Exception:
            self._motor = None
        if self._motor is None:
            self._motor = OcrEngine.try_create_from_user_profile_languages()
        if self._motor is None:
            raise ErroTela("o Windows não tem nenhum idioma para ler texto (Configurações > Hora e idioma > Idioma: "
                           "adicione o Inglês)")
        self.idioma = self._motor.recognizer_language.language_tag

    def ler(self, imagem) -> str:
        import asyncio

        from winrt.windows.graphics.imaging import BitmapAlphaMode, BitmapPixelFormat, SoftwareBitmap
        from winrt.windows.storage.streams import DataWriter
        imagem = preparar_para_ler(imagem, maior=4000)
        escritor = DataWriter()
        pixels = imagem.convert("RGBA").tobytes("raw", "BGRA")
        try:
            escritor.write_bytes(pixels)                 # (as versões novas do winrt aceitam os bytes direto)
        except TypeError:
            escritor.write_bytes(list(pixels))
        foto = SoftwareBitmap.create_copy_from_buffer(escritor.detach_buffer(), BitmapPixelFormat.BGRA8,
                                                      imagem.width, imagem.height, BitmapAlphaMode.PREMULTIPLIED)

        async def ler():
            return await self._motor.recognize_async(foto)
        resultado = asyncio.run(ler())
        return "\n".join(linha.text for linha in resultado.lines)


class LeitorTesseract:
    """O Tesseract (se instalado: github.com/UB-Mannheim/tesseract), pela linha de comando."""
    nome = "Tesseract"

    def __init__(self, programa: str, idioma: str = "eng"):
        self.programa, self.idioma = programa, idioma

    def ler(self, imagem) -> str:
        import io
        dados = io.BytesIO()
        preparar_para_ler(imagem).save(dados, "PNG")
        r = subprocess.run([self.programa, "stdin", "stdout", "-l", self.idioma, "--psm", "6"], input=dados.getvalue(),
                           capture_output=True, timeout=30,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return r.stdout.decode("utf-8", "replace")


def preparar_para_ler(imagem, maior: int = 4000):
    """O texto de jogo é pequeno e colorido: aumenta (2x, até `maior`) e passa para cinza com contraste."""
    from PIL import ImageOps
    escala = min(2.0, maior / max(imagem.width, imagem.height))
    if escala > 1.05:
        imagem = imagem.resize((int(imagem.width * escala), int(imagem.height * escala)))
    return ImageOps.autocontrast(imagem.convert("L")).convert("RGB")


def achar_tesseract() -> str | None:
    if achado := shutil.which("tesseract"):
        return achado
    for base in (r"C:\Program Files\Tesseract-OCR", r"C:\Program Files (x86)\Tesseract-OCR"):
        if Path(base, "tesseract.exe").is_file():
            return str(Path(base, "tesseract.exe"))
    return None


def leitor_de_texto(idioma: str = "en", sistema: str = sys.platform):
    """O leitor de texto disponível neste PC (o do Windows primeiro). ErroTela explicando, se não há nenhum."""
    erros = []
    if sistema == "win32":
        try:
            return LeitorWindows({"en": "en-US", "ja": "ja-JP", "es": "es-ES", "fr": "fr-FR"}.get(idioma, idioma))
        except ImportError:
            erros.append("o leitor do Windows não veio junto do Maestro")
        except ErroTela as erro:
            erros.append(str(erro))
        except Exception as erro:
            erros.append(f"o leitor do Windows não abriu ({erro})")
    if programa := achar_tesseract():
        return LeitorTesseract(programa, {"en": "eng", "ja": "jpn", "es": "spa", "fr": "fra"}.get(idioma, "eng"))
    raise ErroTela("não há leitor de texto neste PC: " + ("; ".join(erros) or "fora do Windows, instale o Tesseract"))


def limpar(texto: str) -> str:
    """O texto lido, numa linha só e sem os riscos que o OCR inventa ('|', '_', espaços repetidos)."""
    texto = re.sub(r"[|_~`•]+", " ", texto or "")
    linhas = [re.sub(r"\s+", " ", linha).strip() for linha in texto.splitlines()]
    return " ".join(linha for linha in linhas if len(linha) >= 2).strip()


# ----------------------------------------------------------------- o laço do tradutor de tela
class MemoriaDeFrases:
    """As frases já traduzidas (guardadas no PC): a mesma frase do jogo não paga de novo."""

    def __init__(self, arquivo: str | Path | None = None):
        self.arquivo = Path(arquivo) if arquivo else None
        self.frases: dict[str, str] = {}
        if self.arquivo and self.arquivo.is_file():
            try:
                self.frases = json.loads(self.arquivo.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self.frases = {}
        self.reaproveitadas = 0

    @staticmethod
    def chave(texto: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", texto.lower()).strip()

    def get(self, texto: str) -> str | None:
        achada = self.frases.get(self.chave(texto))
        if achada is not None:
            self.reaproveitadas += 1
        return achada

    def guardar(self, texto: str, traducao: str) -> None:
        self.frases[self.chave(texto)] = traducao
        if self.arquivo:
            try:
                self.arquivo.parent.mkdir(parents=True, exist_ok=True)
                self.arquivo.write_text(json.dumps(self.frases, ensure_ascii=False), encoding="utf-8")
            except OSError:
                pass


class TradutorDeTela:
    """Fotografa a área a cada INTERVALO s; quando muda e para de mudar, lê, traduz e chama mostrar(original,
    tradução). traduzir(texto) -> tradução. agora(): traduz na hora (o atalho F9), mesmo sem mudança."""

    def __init__(self, area, leitor, traduzir, mostrar, memoria: MemoriaDeFrases | None = None, sozinho: bool = True,
                 avisar=None, fotografar=None, intervalo: float = INTERVALO, esperar=time.sleep):
        self.area = area                      # () -> retângulo (a janela pode mudar de lugar)
        self.leitor, self.traduzir, self.mostrar = leitor, traduzir, mostrar
        self.memoria = memoria or MemoriaDeFrases()
        self.sozinho, self.avisar = sozinho, avisar
        self.fotografar = fotografar or (lambda area: capturar(area))
        self.intervalo, self.esperar = intervalo, esperar
        self._parar, self._agora = threading.Event(), threading.Event()
        self._fio: threading.Thread | None = None
        self.ultimo_texto = ""
        self.lidas = self.traduzidas = 0

    def comecar(self) -> None:
        self._parar.clear()
        self._fio = threading.Thread(target=self._laco, daemon=True, name="tradutor-de-tela")
        self._fio.start()

    def parar(self) -> None:
        self._parar.set()
        self._agora.set()

    def agora(self) -> None:
        self._agora.set()

    @property
    def rodando(self) -> bool:
        return self._fio is not None and self._fio.is_alive() and not self._parar.is_set()

    def _laco(self) -> None:
        anterior, estavel, ja_lida = None, None, None
        while not self._parar.is_set():
            forcar = self._agora.is_set()
            self._agora.clear()
            try:
                foto = self.fotografar(self.area())
            except Exception as erro:
                if self.avisar:
                    self.avisar(f"não deu para fotografar a janela ({erro})")
                self.esperar(2.0)
                continue
            parado = diferenca(foto, anterior) < PAROU
            novo = diferenca(foto, ja_lida) >= MUDOU
            if forcar or (self.sozinho and parado and novo and estavel is not None):
                self.passo(foto, forcar)
                ja_lida = foto
            estavel = foto if parado else None
            anterior = foto
            if not forcar:
                self.esperar(self.intervalo)

    def passo(self, foto, forcar: bool = False) -> str | None:
        """Lê a foto e, se o texto é novo, traduz e mostra. Devolve a tradução (ou None)."""
        try:
            texto = limpar(self.leitor.ler(foto))
        except Exception as erro:
            if self.avisar:
                self.avisar(f"não deu para ler o texto da tela ({erro})")
            return None
        self.lidas += 1
        if len(re.sub(r"\W", "", texto)) < LETRAS_MINIMAS:
            self.ultimo_texto = ""                      # a caixa de texto sumiu: a mesma frase pode voltar
            return None
        if texto == self.ultimo_texto and not forcar:
            return None
        self.ultimo_texto = texto
        traducao = self.memoria.get(texto)
        if traducao is None:
            try:
                traducao = self.traduzir(texto)
            except Exception as erro:
                if self.avisar:
                    self.avisar(f"não deu para traduzir ({erro})")
                return None
            self.memoria.guardar(texto, traducao)
            self.traduzidas += 1
        self.mostrar(texto, traducao)
        return traducao


# ----------------------------------------------------------------- o atalho (F9) com o jogo na frente
class AtalhoGlobal:
    """Uma tecla que funciona mesmo com o jogo na frente (Windows: RegisterHotKey). Fora do Windows: nada."""

    def __init__(self, tecla: str, ao_apertar, sistema: str = sys.platform):
        self.tecla, self.ao_apertar, self.sistema = tecla.upper(), ao_apertar, sistema
        self._fio: threading.Thread | None = None
        self._id_fio = 0
        self.ativo = False

    def comecar(self) -> bool:
        if self.sistema != "win32" or self.tecla not in TECLAS:
            return False
        pronto = threading.Event()

        def ouvir():
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            self._id_fio = ctypes.windll.kernel32.GetCurrentThreadId()
            self.ativo = bool(user32.RegisterHotKey(None, 1, 0x4000, TECLAS[self.tecla]))   # MOD_NOREPEAT
            pronto.set()
            if not self.ativo:
                return
            mensagem = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(mensagem), None, 0, 0) > 0:
                if mensagem.message == 0x0312:                 # WM_HOTKEY
                    self.ao_apertar()
            user32.UnregisterHotKey(None, 1)
        self._fio = threading.Thread(target=ouvir, daemon=True, name="atalho-global")
        self._fio.start()
        pronto.wait(2)
        return self.ativo

    def parar(self) -> None:
        if self.sistema == "win32" and self._id_fio:
            ctypes.windll.user32.PostThreadMessageW(self._id_fio, 0x0012, 0, 0)       # WM_QUIT
        self.ativo = False
