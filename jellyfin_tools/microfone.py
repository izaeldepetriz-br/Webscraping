"""Gravar do microfone (para clonar a SUA voz): aperta Gravar, fala, aperta Parar. E tocar um .wav (ouvir a frase de
teste da voz).

Usa o sounddevice (PortAudio; no Windows a biblioteca vem junto). Sem ele, ou sem microfone, a janela oferece
"Escolher arquivo" (uma gravação feita no celular, por exemplo).
"""

from __future__ import annotations

import threading
import time

TAXA = 24000
MAXIMO_SEGUNDOS = 90         # para não encher a memória se esquecer gravando


def _biblioteca():
    try:
        import sounddevice
    except (ImportError, OSError):           # OSError: falta o PortAudio (Linux sem libportaudio2)
        return None
    return sounddevice


def disponivel() -> str:
    """"" se dá para gravar; senão, o motivo (para mostrar no lugar do botão)."""
    sd = _biblioteca()
    if sd is None:
        return "gravação pelo microfone indisponível neste PC (use \"Escolher arquivo\")"
    try:
        entrada = sd.query_devices(kind="input")
    except Exception:
        return "nenhum microfone encontrado (use \"Escolher arquivo\")"
    return "" if entrada else "nenhum microfone encontrado (use \"Escolher arquivo\")"


class Gravador:
    """gravador.iniciar() ... gravador.parar() -> bytes (16 bits, mono, 24 kHz). `nivel` (0 a 1) mostra se o
    microfone está ouvindo; `segundos` quanto já gravou."""

    def __init__(self, taxa: int = TAXA, biblioteca=None):
        self.taxa = taxa
        self._sd = biblioteca or _biblioteca()
        self._pedacos: list[bytes] = []
        self._trava = threading.Lock()
        self._fluxo = None
        self._inicio = 0.0
        self.nivel = 0.0

    @property
    def gravando(self) -> bool:
        return self._fluxo is not None

    @property
    def segundos(self) -> float:
        with self._trava:
            return sum(len(p) for p in self._pedacos) / 2 / self.taxa

    def _ao_ouvir(self, dados, quadros, tempo, situacao) -> None:
        bruto = bytes(dados)
        with self._trava:
            if sum(len(p) for p in self._pedacos) / 2 / self.taxa < MAXIMO_SEGUNDOS:
                self._pedacos.append(bruto)
        if bruto:
            from array import array
            amostras = array("h")
            amostras.frombytes(bruto[:len(bruto) // 2 * 2])
            self.nivel = min(1.0, max((abs(a) for a in amostras), default=0) / 32767 * 1.5)

    def iniciar(self) -> None:
        if self._sd is None:
            raise OSError(disponivel())
        self._pedacos = []
        self._fluxo = self._sd.RawInputStream(samplerate=self.taxa, channels=1, dtype="int16",
                                              callback=self._ao_ouvir)
        self._fluxo.start()
        self._inicio = time.monotonic()

    def parar(self) -> bytes:
        fluxo, self._fluxo = self._fluxo, None
        if fluxo is not None:
            try:
                fluxo.stop()
            finally:
                fluxo.close()
        self.nivel = 0.0
        with self._trava:
            return b"".join(self._pedacos)


def tocar(wav, biblioteca=None, plataforma: str | None = None) -> None:
    """Toca o .wav sem travar a janela. No Windows, pelo próprio Windows (winsound); nos outros, pelo sounddevice.
    Sem nenhum dos dois: OSError (a janela mostra onde está o arquivo, para abrir no player)."""
    import sys
    plataforma = plataforma or sys.platform
    if plataforma == "win32" and biblioteca is None:
        import winsound
        winsound.PlaySound(str(wav), winsound.SND_FILENAME | winsound.SND_ASYNC)
        return
    sd = biblioteca or _biblioteca()
    if sd is None:
        raise OSError("não há como tocar áudio neste PC")
    import wave
    from array import array
    with wave.open(str(wav), "rb") as w:
        amostras = array("h")
        amostras.frombytes(w.readframes(w.getnframes()))
        taxa = w.getframerate()
    sd.play(amostras, taxa)                          # volta logo; o som continua tocando
