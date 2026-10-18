"""A fala dublada no FORMATO do jogo e com a DURAÇÃO exata da original: o que o jogo (PS2) precisa para tocar a
fala nova no lugar da antiga sem travar nem cortar.

    gravar_como(original, dublada, destino)   lê o formato da fala original do jogo e grava a dublada igual:
                                              mesma taxa (Hz), mesmos canais, mesmo número de amostras e, nos
                                              formatos do PS2, o mesmo tamanho em bytes (a ferramenta de
                                              reinserção põe no mesmo lugar do disco)

Formatos: WAV (PCM 16 bits), VAG ("VAGp", mono) e ADS ("SShd"/"SSbd", mono ou estéreo intercalado), os dois
com o PS-ADPCM (a compressão do som do PS2: 28 amostras em 16 bytes). Os outros (ADX, AT3...) ainda não.

A duração: a fala dublada mais comprida é acelerada SEM mudar o tom (até 35%, como na dublagem dos filmes; mais
que isso fica difícil de entender: encurte a frase antes, o Maestro faz isso com o Claude); o que ainda sobrar é
cortado com um fim suave, e a mais curta é completada com silêncio. O jogo recebe exatamente o tamanho que espera.
"""

from __future__ import annotations

import struct
import subprocess
import wave
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .dublagem import ACELERAR_MAX, SEM_JANELA, ErroDublagem

AMOSTRAS_POR_BLOCO, BYTES_POR_BLOCO = 28, 16
# os 5 filtros do PS-ADPCM (o "palpite" de cada amostra pelas 2 anteriores, em 64 avos)
FILTROS = np.array([[0, 0], [60, 0], [115, -52], [98, -55], [122, -60]], dtype=np.int64)
FIM_SUAVE = 0.02                  # segundos de "fade" quando a fala precisa ser cortada no limite
CABECALHO_VAG = 48
FORMATOS = ("wav", "vag", "ads")


class ErroAudioJogo(ErroDublagem):
    pass


# ----------------------------------------------------------------- o PS-ADPCM
def codificar_adpcm(amostras, inicio_vazio: bool = False, fim: bool = True) -> bytes:
    """int16 mono -> PS-ADPCM (16 bytes a cada 28 amostras). Para cada bloco, testa os 5 filtros x 13 escalas de
    uma vez (numpy) e fica com o de menor erro, decodificando como o PS2 decodifica (o erro não se acumula)."""
    x = np.asarray(amostras, dtype=np.int64)
    blocos = max(1, -(-len(x) // AMOSTRAS_POR_BLOCO))
    x = np.concatenate([x, np.zeros(blocos * AMOSTRAS_POR_BLOCO - len(x), dtype=np.int64)])
    c0, c1 = np.repeat(FILTROS[:, 0], 13), np.repeat(FILTROS[:, 1], 13)
    escala = np.tile(np.arange(13, dtype=np.int64), 5)
    passo = (2.0 ** (12 - escala))
    s1 = np.zeros(65, dtype=np.int64)
    s2 = np.zeros(65, dtype=np.int64)
    saida = bytearray(bytes(BYTES_POR_BLOCO) if inicio_vazio else b"")
    for b in range(blocos):
        bloco = x[b * AMOSTRAS_POR_BLOCO:(b + 1) * AMOSTRAS_POR_BLOCO]
        a1, a2 = s1.copy(), s2.copy()
        erro = np.zeros(65)
        nibbles = np.zeros((65, AMOSTRAS_POR_BLOCO), dtype=np.int64)
        for i in range(AMOSTRAS_POR_BLOCO):
            palpite = (a1 * c0 + a2 * c1 + 32) >> 6
            t = np.clip(np.rint((bloco[i] - palpite) / passo), -8, 7).astype(np.int64)
            dec = np.clip(((t << 12) >> escala) + palpite, -32768, 32767)
            erro += (bloco[i] - dec) ** 2
            nibbles[:, i] = t
            a2, a1 = a1, dec
        k = int(np.argmin(erro))
        s1[:], s2[:] = a1[k], a2[k]                      # todos seguem do decodificado da escolhida
        cab = (int(k // 13) << 4) | int(escala[k])
        flag = 1 if fim and b == blocos - 1 else 0
        n = nibbles[k] & 0xF
        saida += bytes([cab, flag]) + bytes((n[0::2] | (n[1::2] << 4)).astype(np.uint8))
    return bytes(saida)


def decodificar_adpcm(dados: bytes) -> np.ndarray:
    """PS-ADPCM -> int16 mono (como o PS2 toca)."""
    saida = []
    s1 = s2 = 0
    for pos in range(0, len(dados) - BYTES_POR_BLOCO + 1, BYTES_POR_BLOCO):
        cab = dados[pos]
        escala, filtro = cab & 0x0F, min(4, cab >> 4)
        if escala > 12:
            escala = 9
        f0, f1 = FILTROS[filtro]
        for byte in dados[pos + 2:pos + BYTES_POR_BLOCO]:
            for t in (byte & 0x0F, byte >> 4):
                t = t - 16 if t >= 8 else t
                s = ((t << 12) >> escala) + ((s1 * int(f0) + s2 * int(f1) + 32) >> 6)
                s = max(-32768, min(32767, s))
                saida.append(s)
                s2, s1 = s1, s
    return np.array(saida, dtype=np.int16)


# ----------------------------------------------------------------- os formatos
@dataclass
class Formato:
    tipo: str                    # "wav", "vag" ou "ads"
    taxa: int                    # amostras por segundo (Hz)
    canais: int
    amostras: int                # por canal: a duração exata (o que o jogo espera)
    tamanho: int = 0             # bytes do arquivo
    extra: dict = field(default_factory=dict)

    @property
    def segundos(self) -> float:
        return self.amostras / self.taxa if self.taxa else 0.0

    def descrever(self) -> str:
        return (f"{self.tipo.upper()} · {self.taxa} Hz · {'mono' if self.canais == 1 else f'{self.canais} canais'} · "
                f"{self.segundos:.3f} s".replace(".", ","))


def _vag_extras(dados: bytes) -> tuple[bool, bool]:
    """(começa com o bloco vazio, termina com o bloco de fim "07") no VAG original: o novo segue igual."""
    corpo = dados[CABECALHO_VAG:]
    if len(corpo) < 2 * BYTES_POR_BLOCO:
        return False, False
    return corpo[:BYTES_POR_BLOCO] == bytes(BYTES_POR_BLOCO), corpo[-BYTES_POR_BLOCO + 1] == 0x07


def ler_formato(arquivo: str | Path) -> Formato:
    arquivo = Path(arquivo)
    dados = arquivo.read_bytes()
    if dados[:4] == b"RIFF" and dados[8:12] == b"WAVE":
        try:
            with wave.open(str(arquivo)) as w:
                if w.getsampwidth() != 2:
                    raise ErroAudioJogo(f"{arquivo.name}: WAV de {8 * w.getsampwidth()} bits (o Maestro grava 16)")
                return Formato("wav", w.getframerate(), w.getnchannels(), w.getnframes(), len(dados))
        except wave.Error as erro:
            raise ErroAudioJogo(f"{arquivo.name}: WAV que o Maestro não lê ({erro})") from erro
    if dados[:4] == b"VAGp":
        tamanho_dados = struct.unpack_from(">I", dados, 12)[0]
        taxa = struct.unpack_from(">I", dados, 16)[0]
        corpo = len(dados) - CABECALHO_VAG
        vazio, fim07 = _vag_extras(dados)
        blocos = corpo // BYTES_POR_BLOCO - int(vazio) - int(fim07)
        return Formato("vag", taxa, 1, blocos * AMOSTRAS_POR_BLOCO, len(dados),
                       {"nome": dados[32:48], "versao": dados[4:8], "vazio": vazio, "fim07": fim07,
                        "tamanho_dados": tamanho_dados})
    if dados[:4] == b"SShd" and dados[32:36] == b"SSbd":
        codec, taxa, canais, intercalado = struct.unpack_from("<IIII", dados, 8)
        tamanho_dados = struct.unpack_from("<I", dados, 36)[0]
        if codec == 0x10:
            amostras = tamanho_dados // canais // BYTES_POR_BLOCO * AMOSTRAS_POR_BLOCO
        elif codec == 0x01:
            amostras = tamanho_dados // canais // 2
        else:
            raise ErroAudioJogo(f"{arquivo.name}: ADS com uma compressão que o Maestro ainda não grava ({codec:#x})")
        return Formato("ads", taxa, canais, amostras, len(dados),
                       {"codec": codec, "intercalado": intercalado or BYTES_POR_BLOCO, "cabecalho": dados[:40],
                        "tamanho_dados": tamanho_dados, "rabo": dados[40 + tamanho_dados:]})
    raise ErroAudioJogo(f"{arquivo.name}: formato que o Maestro ainda não grava (ele grava WAV, VAG e ADS). "
                        "Converta a original para WAV com a ferramenta do jogo")


# ----------------------------------------------------------------- a duração exata
def encaixar_na_duracao(dublada: str | Path, amostras: int, taxa: int, ffmpeg: str, executar=subprocess.run,
                        acelerar_max: float = ACELERAR_MAX) -> tuple[np.ndarray, dict]:
    """A fala dublada em int16 mono, na taxa do jogo, com EXATAMENTE `amostras` amostras."""
    som = _ler(dublada, taxa, ffmpeg, executar)
    fator = min(acelerar_max, len(som) / amostras) if amostras and len(som) > amostras * 1.005 else 1.0
    if fator > 1.0:                                      # comprida: acelera sem mudar o tom (atempo)
        som = _ler(dublada, taxa, ffmpeg, executar, f"atempo={fator:.4f}")
    info = {"acelerada": round(fator, 3), "cortada": 0.0, "completada": 0.0}
    if len(som) > amostras:
        info["cortada"] = round((len(som) - amostras) / taxa, 3)
        som = som[:amostras]
        suave = min(len(som), int(FIM_SUAVE * taxa))
        if suave:
            som[-suave:] *= np.linspace(1.0, 0.0, suave)
    elif len(som) < amostras:
        info["completada"] = round((amostras - len(som)) / taxa, 3)
        som = np.concatenate([som, np.zeros(amostras - len(som))])
    return np.clip(np.rint(som), -32768, 32767).astype(np.int16), info


def _ler(arquivo: str | Path, taxa: int, ffmpeg: str, executar, filtro: str = "") -> np.ndarray:
    """O áudio em mono, na taxa do jogo (com o filtro do ffmpeg, se houver), como números."""
    r = executar([ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(arquivo),
                  *(["-af", filtro] if filtro else []), "-ac", "1", "-ar", str(taxa), "-f", "s16le", "pipe:1"],
                 capture_output=True, timeout=300, **SEM_JANELA)
    if r.returncode != 0:
        detalhe = (r.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        raise ErroAudioJogo(f"o ffmpeg não leu {Path(arquivo).name}{': ' + detalhe[-1] if detalhe else ''}")
    return np.frombuffer(r.stdout[:len(r.stdout) // 2 * 2], dtype=np.int16).astype(np.float64)


# ----------------------------------------------------------------- gravar igual à original
def gravar_como(original: str | Path, dublada: str | Path, destino: str | Path, ffmpeg: str,
                executar=subprocess.run) -> dict:
    """Grava a fala dublada no formato da original do jogo (taxa, canais, duração e, no VAG/ADS, o tamanho em
    bytes iguais). Devolve o que foi feito (formato, aceleração, corte, silêncio completado)."""
    formato = ler_formato(original)
    som, info = encaixar_na_duracao(dublada, formato.amostras, formato.taxa, ffmpeg, executar)
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    if formato.tipo == "wav":
        with wave.open(str(destino), "wb") as w:
            w.setnchannels(formato.canais)
            w.setsampwidth(2)
            w.setframerate(formato.taxa)
            w.writeframes(np.repeat(som, formato.canais).tobytes())
    elif formato.tipo == "vag":
        e = formato.extra
        corpo = codificar_adpcm(som, inicio_vazio=e["vazio"])
        if e["fim07"]:
            corpo += bytes([0x00, 0x07]) + bytes([0x77]) * 14
        cab = bytearray(CABECALHO_VAG)
        cab[0:4], cab[4:8] = b"VAGp", e["versao"]
        struct.pack_into(">I", cab, 12, len(corpo))
        struct.pack_into(">I", cab, 16, formato.taxa)
        cab[32:48] = e["nome"]
        destino.write_bytes(bytes(cab) + corpo)
    else:
        e = formato.extra
        por_canal = e["tamanho_dados"] // formato.canais
        if e["codec"] == 0x10:
            canal = codificar_adpcm(som)[:por_canal].ljust(por_canal, b"\x00")
        else:
            canal = som.astype("<i2").tobytes()[:por_canal].ljust(por_canal, b"\x00")
        passo = e["intercalado"]
        dados = bytearray()
        for pos in range(0, por_canal, passo):         # L, R, L, R... em pedaços do tamanho do original
            for _ in range(formato.canais):
                dados += canal[pos:pos + passo]
        destino.write_bytes(e["cabecalho"] + bytes(dados) + e["rabo"])      # (o enchimento do fim, igual)
    novo = destino.stat().st_size
    if formato.tipo in ("vag", "ads") and novo != formato.tamanho:
        raise ErroAudioJogo(f"{destino.name} ficou com {novo} bytes e a original tem {formato.tamanho}")
    return {"formato": formato.descrever(), **info, "bytes": novo}
