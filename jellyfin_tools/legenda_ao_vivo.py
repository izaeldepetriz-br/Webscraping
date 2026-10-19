"""A legenda AO VIVO das vozes do jogo (modo "Enquanto joga" da aba 🎮 Jogos): o Maestro ouve o som que sai do PC
(o do emulador ou do jogo), separa cada fala pelas pausas, o Whisper escreve o que foi dito (na placa de vídeo, o
modelo "turbo" leva menos de 1 s) e a tradução aparece na janelinha por cima do jogo.

Ler em voz alta (experimental): a fala traduzida também é FALADA (XTTS-v2 no PC, ou o Gemini). Chega uns segundos
depois da original, por isso é experimental; enquanto ela fala, o som do jogo abaixa (sem sumir) e o Maestro não
ouve a própria voz (senão traduziria a si mesmo).

    CapturaDoSom      o som que sai do PC ("loopback" do Windows), em pedaços de 0,1 s, a 16 kHz
    Cortador          junta os pedaços em falas: começa quando o volume sobe, termina numa pausa (ou em 12 s)
    LegendaAoVivo     o laço: captura -> fala -> Whisper -> tradução -> mostrar (e falar, se ligado)
"""

from __future__ import annotations

import queue
import threading
import time

import numpy as np

TAXA = 16000                  # o Whisper ouve em 16 kHz
PEDACO = 0.1                  # segundos por pedaço capturado
LIMIAR_DB = -42.0             # mais alto que isso é som (fala); abaixo, silêncio
PAUSA = 0.6                   # segundos de silêncio que terminam uma fala
FALA_MINIMA = 0.4
FALA_MAXIMA = 12.0
ANTES = 0.3                   # um pouco do som de antes do começo (o começo da palavra)
VOLUME_ABAIXADO = 0.3         # o som do jogo enquanto a voz traduzida fala (30%)


class ErroLegenda(Exception):
    pass


def db(pedaco: np.ndarray) -> float:
    return float(20 * np.log10(np.sqrt(np.mean(np.square(pedaco))) + 1e-9)) if len(pedaco) else -120.0


class Cortador:
    """Recebe os pedaços do som; devolve cada fala inteira (np.float32, 16 kHz) quando ela termina."""

    def __init__(self, limiar_db: float = LIMIAR_DB, pausa: float = PAUSA):
        self.limiar, self.pausa = limiar_db, pausa
        self._antes: list[np.ndarray] = []
        self._fala: list[np.ndarray] = []
        self._silencio = self._som_antes = 0.0

    def receber(self, pedaco: np.ndarray) -> np.ndarray | None:
        duracao = len(pedaco) / TAXA
        alto = db(pedaco) > self.limiar
        if not self._fala:
            if alto:
                self._fala = self._antes + [pedaco]
                self._som_antes = sum(len(p) for p in self._antes) / TAXA
                self._silencio = 0.0
            else:
                self._antes = (self._antes + [pedaco])[-max(1, int(ANTES / PEDACO)):]
            return None
        self._fala.append(pedaco)
        self._silencio = 0.0 if alto else self._silencio + duracao
        total = sum(len(p) for p in self._fala) / TAXA
        if self._silencio >= self.pausa or total >= FALA_MAXIMA:
            fala, silencio = np.concatenate(self._fala), self._silencio
            self._fala, self._antes, self._silencio = [], [], 0.0
            if total - silencio - self._som_antes >= FALA_MINIMA:       # só a parte com voz conta
                return fala
        return None


class CapturaDoSom:
    """O som que sai do PC, pelo "loopback" do alto-falante padrão (biblioteca soundcard). ler() -> pedaço."""

    def __init__(self, taxa: int = TAXA):
        try:
            import soundcard
        except Exception as erro:                     # (sem a biblioteca, ou sem placa de som)
            raise ErroLegenda(f"não deu para ouvir o som do PC ({erro})") from erro
        alto_falante = soundcard.default_speaker()
        if alto_falante is None:
            raise ErroLegenda("não achei o alto-falante do PC")
        self.nome = alto_falante.name
        self._microfone = soundcard.get_microphone(id=str(alto_falante.name), include_loopback=True)
        self._gravador = self._microfone.recorder(samplerate=taxa, channels=1, blocksize=int(taxa * PEDACO))
        self._gravador.__enter__()

    def ler(self) -> np.ndarray:
        dados = self._gravador.record(numframes=int(TAXA * PEDACO))
        return np.asarray(dados, dtype=np.float32).reshape(-1)

    def fechar(self) -> None:
        try:
            self._gravador.__exit__(None, None, None)
        except Exception:
            pass


class VolumeDoJogo:
    """Abaixa o som do processo do jogo enquanto a voz traduzida fala (Windows, pela biblioteca pycaw)."""

    def __init__(self, processo: int):
        self.processo, self._sessoes, self._antes = processo, [], {}
        try:
            from pycaw.pycaw import AudioUtilities
            self._sessoes = [s for s in AudioUtilities.GetAllSessions() if s.Process and s.Process.pid == processo]
        except Exception:
            self._sessoes = []

    @property
    def funciona(self) -> bool:
        return bool(self._sessoes)

    def abaixar(self) -> None:
        for s in self._sessoes:
            try:
                volume = s.SimpleAudioVolume
                self._antes[id(s)] = volume.GetMasterVolume()
                volume.SetMasterVolume(self._antes[id(s)] * VOLUME_ABAIXADO, None)
            except Exception:
                pass

    def voltar(self) -> None:
        for s in self._sessoes:
            try:
                s.SimpleAudioVolume.SetMasterVolume(self._antes.get(id(s), 1.0), None)
            except Exception:
                pass


class LegendaAoVivo:
    """captura.ler() -> pedaços; ouvir(fala) -> texto (Whisper); traduzir(texto) -> tradução; mostrar(original,
    tradução). falar(tradução) (opcional) toca a voz traduzida, com o som do jogo abaixado (volume)."""

    def __init__(self, captura, ouvir, traduzir, mostrar, falar=None, volume=None, avisar=None, memoria=None):
        self.captura, self.ouvir, self.traduzir, self.mostrar = captura, ouvir, traduzir, mostrar
        self.falar, self.volume, self.avisar = falar, volume, avisar
        self.memoria = memoria
        self.cortador = Cortador()
        self._falas: queue.Queue = queue.Queue(maxsize=8)
        self._parar = threading.Event()
        self._falando = threading.Event()
        self._fios: list[threading.Thread] = []
        self.ouvidas = 0

    def comecar(self) -> None:
        self._parar.clear()
        self._fios = [threading.Thread(target=self._capturar, daemon=True, name="legenda-captura"),
                      threading.Thread(target=self._trabalhar, daemon=True, name="legenda-whisper")]
        for fio in self._fios:
            fio.start()

    def parar(self) -> None:
        self._parar.set()
        try:
            self._falas.put_nowait(None)
        except queue.Full:
            pass

    def _capturar(self) -> None:
        while not self._parar.is_set():
            try:
                pedaco = self.captura.ler()
            except Exception as erro:
                if self.avisar:
                    self.avisar(f"parei de ouvir o som do PC ({erro})")
                return
            if self._falando.is_set():                       # a voz do Maestro: não ouve a si mesmo
                continue
            fala = self.cortador.receber(pedaco)
            if fala is not None:
                try:
                    self._falas.put_nowait(fala)
                except queue.Full:                           # o Whisper ficou para trás: pula a mais velha
                    try:
                        self._falas.get_nowait()
                        self._falas.put_nowait(fala)
                    except queue.Empty:
                        pass

    def _trabalhar(self) -> None:
        while not self._parar.is_set():
            fala = self._falas.get()
            if fala is None:
                return
            self.processar(fala)

    def processar(self, fala: np.ndarray) -> str | None:
        """Uma fala: escreve (Whisper), traduz, mostra e (ligado) fala. Devolve a tradução."""
        try:
            texto = (self.ouvir(fala) or "").strip()
        except Exception as erro:
            if self.avisar:
                self.avisar(f"o Whisper não ouviu ({erro})")
            return None
        if len(texto) < 2:
            return None
        self.ouvidas += 1
        traducao = self.memoria.get(texto) if self.memoria is not None else None
        if traducao is None:
            try:
                traducao = self.traduzir(texto)
            except Exception as erro:
                if self.avisar:
                    self.avisar(f"não deu para traduzir ({erro})")
                return None
            if self.memoria is not None:
                self.memoria.guardar(texto, traducao)
        self.mostrar(texto, traducao)
        if self.falar is not None:
            self._falando.set()
            try:
                if self.volume is not None:
                    self.volume.abaixar()
                self.falar(traducao)
            except Exception as erro:
                if self.avisar:
                    self.avisar(f"a voz traduzida falhou ({erro})")
            finally:
                if self.volume is not None:
                    self.volume.voltar()
                time.sleep(0.2)
                self._falando.clear()
        return traducao


def ouvinte_whisper(transcritor, idioma: str | None = "en"):
    """ouvir(fala) -> texto, pelo Whisper do Maestro (o modelo já carregado fica aberto entre as falas)."""
    def ouvir(fala: np.ndarray) -> str:
        transcritor._carregar()
        segmentos, _ = transcritor.motor.transcribe(fala.astype(np.float32), language=idioma, beam_size=1,
                                                    vad_filter=False, condition_on_previous_text=False)
        return " ".join(s.text.strip() for s in segmentos)
    return ouvir


def tem_captura() -> bool:
    """A biblioteca que ouve o som do PC (soundcard) veio junto?"""
    import importlib.util
    return importlib.util.find_spec("soundcard") is not None
