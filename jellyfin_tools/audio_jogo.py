"""A fala dublada no FORMATO do jogo e com a DURAÇÃO exata da original: o que o jogo (PS2) precisa para tocar a
fala nova no lugar da antiga sem travar nem cortar.

    gravar_como(original, dublada, destino)   lê o formato da fala original do jogo e grava a dublada igual:
                                              mesma taxa (Hz), mesmos canais, mesmo número de amostras e, nos
                                              formatos do PS2, o mesmo tamanho em bytes (a ferramenta de
                                              reinserção põe no mesmo lugar do disco)

Formatos: WAV (PCM 16 bits), VAG ("VAGp", mono) e ADS ("SShd"/"SSbd", mono ou estéreo intercalado), os dois
com o PS-ADPCM (a compressão do som do PS2: 28 amostras em 16 bytes). Pelo ffmpeg (jogos de PC e de outros
consoles): OGG, MP3, FLAC e Opus, lidos e gravados no mesmo formato; AT3/AT9 (PSP/PS Vita), WMA e M4A, lidos e
devolvidos em WAV (não há programa livre que grave ATRAC: a ferramenta do jogo converte). ADX, Wwise (.wem) e
os outros ainda não.

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
# pelo ffmpeg: a extensão -> (o tipo, o codificador e as opções; None = só lê: a dublada sai em WAV)
COMPRIMIDOS = {".ogg": ("ogg", ["-c:a", "libvorbis", "-q:a", "5"]), ".mp3": ("mp3", ["-c:a", "libmp3lame"]),
               ".flac": ("flac", ["-c:a", "flac"]), ".opus": ("opus", ["-c:a", "libopus"]),
               ".at3": ("at3", None), ".at9": ("at9", None), ".wma": ("wma", None), ".m4a": ("m4a", None)}
RESERVA = {"libvorbis": ["-c:a", "vorbis", "-strict", "-2"], "libopus": ["-c:a", "opus", "-strict", "-2"]}


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


def _sondar(arquivo: Path, tipo: str, ffmpeg: str | None = None, executar=subprocess.run) -> Formato:
    """A taxa, os canais e as amostras de um áudio comprimido (pelo ffmpeg: a duração exata, decodificando)."""
    import re
    if ffmpeg is None:
        from .dublagem import localizar_ffmpeg
        ffmpeg = localizar_ffmpeg()
    if not ffmpeg:
        raise ErroAudioJogo(f"{arquivo.name}: falta o ffmpeg para ler {tipo.upper()} (pip install imageio-ffmpeg)")
    r = executar([ffmpeg, "-hide_banner", "-i", str(arquivo)], capture_output=True, timeout=60, **SEM_JANELA)
    texto = (r.stderr or b"").decode("utf-8", "replace")
    audio = re.search(r"Audio: ([^,\n]+), (\d+) Hz, ([^,\n]+)", texto)
    if not audio:
        raise ErroAudioJogo(f"{arquivo.name}: o ffmpeg não reconheceu o áudio ({tipo.upper()})")
    taxa, como = int(audio.group(2)), audio.group(3).strip()
    canais = 1 if como == "mono" else 2 if como == "stereo" else int((re.match(r"(\d+)", como) or [0, 2])[1])
    taxa_bits = re.search(r"Audio: .*?(\d+) kb/s", texto)
    amostras = len(_ler(arquivo, taxa, ffmpeg, executar))
    return Formato(tipo, taxa, canais, amostras, arquivo.stat().st_size,
                   {"so_ler": COMPRIMIDOS.get(arquivo.suffix.lower(), (tipo, None))[1] is None,
                    "codec": audio.group(1).split()[0], "kbps": int(taxa_bits.group(1)) if taxa_bits else 0})


def ler_formato(arquivo: str | Path, ffmpeg: str | None = None) -> Formato:
    arquivo = Path(arquivo)
    dados = arquivo.read_bytes()
    extensao = arquivo.suffix.lower()
    pcm = dados[:4] == b"RIFF" and dados[8:12] == b"WAVE" and dados[20:22] == b"\x01\x00"
    if extensao in COMPRIMIDOS and not pcm:             # (um .at3 com som sem compressão é um WAV comum)
        return _sondar(arquivo, COMPRIMIDOS[extensao][0], ffmpeg)
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
    raise ErroAudioJogo(f"{arquivo.name}: formato que o Maestro ainda não grava (WAV, VAG, ADS, OGG, MP3, FLAC e "
                        "Opus; AT3/AT9 volta em WAV). Converta a original para WAV com a ferramenta do jogo")


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
                executar=subprocess.run, exata: bool = True) -> dict:
    """Grava a fala dublada no formato da original do jogo (taxa, canais, duração e, no VAG/ADS, o tamanho em
    bytes iguais). Devolve o que foi feito (formato, aceleração, corte, silêncio completado). exata=False: no
    formato da original, mas com a duração natural da fala dublada (para a ferramenta do jogo que aceita outro
    tamanho; o Maestro só monta a ISO com a duração exata)."""
    formato = ler_formato(original)
    if exata:
        som, info = encaixar_na_duracao(dublada, formato.amostras, formato.taxa, ffmpeg, executar)
    else:
        som = np.clip(np.rint(_ler(dublada, formato.taxa, ffmpeg, executar)), -32768, 32767).astype(np.int16)
        info = {"acelerada": 1.0, "cortada": 0.0, "completada": 0.0}
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    if formato.extra.get("so_ler"):                 # AT3/AT9...: em WAV, para a ferramenta do jogo converter
        destino = destino.with_suffix(".wav")
    if formato.tipo == "wav" or formato.extra.get("so_ler"):
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
    elif formato.tipo in {tipo for tipo, opcoes in COMPRIMIDOS.values() if opcoes}:
        _gravar_comprimido(som, formato, destino, ffmpeg, executar)
    else:
        e = formato.extra
        passo = e["intercalado"]
        cabecalho, rabo = e["cabecalho"], e["rabo"]
        if exata:
            por_canal = e["tamanho_dados"] // formato.canais
        else:                                           # do tamanho da fala, em pedaços inteiros do intercalado
            bruto = len(som) * 2 if e["codec"] != 0x10 else -(-len(som) // AMOSTRAS_POR_BLOCO) * BYTES_POR_BLOCO
            por_canal = -(-bruto // passo) * passo
            cabecalho = bytearray(cabecalho)
            struct.pack_into("<I", cabecalho, 36, por_canal * formato.canais)
            cabecalho, rabo = bytes(cabecalho), b""
        if e["codec"] == 0x10:
            canal = codificar_adpcm(som)[:por_canal].ljust(por_canal, b"\x00")
        else:
            canal = som.astype("<i2").tobytes()[:por_canal].ljust(por_canal, b"\x00")
        dados = bytearray()
        for pos in range(0, por_canal, passo):         # L, R, L, R... em pedaços do tamanho do original
            for _ in range(formato.canais):
                dados += canal[pos:pos + passo]
        destino.write_bytes(cabecalho + bytes(dados) + rabo)      # (o enchimento do fim, igual)
    novo = destino.stat().st_size
    if formato.extra.get("so_ler"):
        info["em_wav"] = True                           # (o caminho mudou: .wav no lugar do .at3)
    if exata and formato.tipo in ("vag", "ads") and novo != formato.tamanho:
        raise ErroAudioJogo(f"{destino.name} ficou com {novo} bytes e a original tem {formato.tamanho}")
    return {"formato": formato.descrever(), **info, "bytes": novo}


def _gravar_comprimido(som: np.ndarray, formato: Formato, destino: Path, ffmpeg: str, executar) -> None:
    """A fala no mesmo formato comprimido da original (OGG, MP3, FLAC, Opus), com a taxa e os canais dela."""
    temporario = destino.with_name(destino.name + ".maestro.wav")
    with wave.open(str(temporario), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(formato.taxa)
        w.writeframes(som.tobytes())
    opcoes = list(COMPRIMIDOS[destino.suffix.lower()][1] if destino.suffix.lower() in COMPRIMIDOS else
                  next(o for t, o in COMPRIMIDOS.values() if t == formato.tipo))
    if formato.extra.get("kbps") and formato.tipo in ("mp3", "opus"):
        opcoes += ["-b:a", f"{formato.extra['kbps']}k"]
    try:
        for tentativa in (opcoes, RESERVA.get(opcoes[1])):
            if tentativa is None:
                break
            r = executar([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(temporario), "-ac",
                          str(formato.canais), "-ar", str(formato.taxa), *tentativa, str(destino)],
                         capture_output=True, timeout=300, **SEM_JANELA)
            if r.returncode == 0:
                return
        detalhe = (r.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        raise ErroAudioJogo(f"o ffmpeg não gravou {destino.name} em {formato.tipo.upper()}"
                            f"{': ' + detalhe[-1] if detalhe else ''}")
    finally:
        temporario.unlink(missing_ok=True)


# ----------------------------------------------------------------- ouvir a original (sem o ffmpeg)
def ler_som(arquivo: str | Path) -> tuple[np.ndarray, int]:
    """(amostras em mono, de -1 a 1; taxa em Hz) de uma fala do jogo: WAV, VAG ou ADS (decodificados aqui mesmo,
    como o PS2 toca). Para medir o tom e o volume e para o Whisper ouvir a original."""
    formato = ler_formato(arquivo)
    if formato.tipo not in FORMATOS:                     # comprimido: pelo ffmpeg
        from .dublagem import localizar_ffmpeg
        return _ler(arquivo, formato.taxa, localizar_ffmpeg(), subprocess.run) / 32768.0, formato.taxa
    dados = Path(arquivo).read_bytes()
    if formato.tipo == "wav":
        with wave.open(str(arquivo)) as w:
            som = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32)
        som = som.reshape(-1, formato.canais).mean(axis=1) if formato.canais > 1 else som
    elif formato.tipo == "vag":
        corpo = dados[CABECALHO_VAG:]
        if formato.extra["vazio"]:
            corpo = corpo[BYTES_POR_BLOCO:]
        som = decodificar_adpcm(corpo[:formato.amostras // AMOSTRAS_POR_BLOCO * BYTES_POR_BLOCO]).astype(np.float32)
    else:
        e = formato.extra
        corpo = dados[40:40 + e["tamanho_dados"]]
        passo, canais = e["intercalado"], formato.canais
        partes = [bytearray() for _ in range(canais)]
        for pos in range(0, len(corpo), passo * canais):          # L, R, L, R... em pedaços do intercalado
            for c in range(canais):
                partes[c] += corpo[pos + c * passo:pos + (c + 1) * passo]
        if e["codec"] == 0x10:
            canais_som = [decodificar_adpcm(bytes(p)).astype(np.float32) for p in partes]
        else:
            canais_som = [np.frombuffer(bytes(p)[:len(p) // 2 * 2], dtype="<i2").astype(np.float32) for p in partes]
        menor = min(len(c) for c in canais_som)
        som = np.mean([c[:menor] for c in canais_som], axis=0)
    return som / 32768.0, formato.taxa


def para_wav(arquivo: str | Path, destino: str | Path) -> Path:
    """A fala original do jogo num WAV comum (16 bits, mono), para ouvir e para o Whisper."""
    som, taxa = ler_som(arquivo)
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(destino), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(taxa)
        w.writeframes(np.clip(np.rint(som * 32767), -32768, 32767).astype("<i2").tobytes())
    return destino
