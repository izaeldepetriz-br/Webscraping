"""Sincronizar legenda adiantada ou atrasada (a fala aparece antes ou depois da voz).

Como funciona (a mesma ideia do ffsubsync): duas "réguas" de 10 em 10 milissegundos,
    áudio:    ____████____██████______███____     (onde há VOZ, pelo detector de voz do Whisper, o Silero)
    legenda:  ______████____██████______███__     (onde há FALA na legenda)
e o programa desliza uma sobre a outra até encaixar melhor (correlação). O deslocamento que mais encaixa é o atraso.
Só corrige quando o encaixe é claramente melhor que o de agora; a legenda original fica guardada como
'Nome.pt-BR.srt.original' (é só apagar a nova e tirar o '.original' para voltar).

Não corrige legenda feita para OUTRA versão do vídeo (com cenas a mais ou velocidade diferente, 23,976 x 25
quadros): aí o atraso muda ao longo do filme. Nesse caso o resultado é "incerta" e nada é mudado.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .legendas import ErroLegenda, extrair_srt
from .traducao import Fala, gerar_srt, ler_srt
from .dublagem import horarios
from .transcricao import tempo_srt

PASSO = 0.01                  # 10 ms por posição da régua
ATRASO_MAXIMO = 60.0          # procura entre -60 s e +60 s
MINIMO = 0.25                 # menos que isso não vale corrigir (ninguém percebe)
GANHO_MINIMO = 1.15           # o encaixe novo precisa ser 15% melhor que o atual
TRECHO = 10 * 60              # o áudio é ouvido em pedaços de 10 min (pouca memória num filme de 2 h)


@dataclass
class ResultadoSincronia:
    legenda: Path
    status: str                # "ajustada", "ja_certa", "incerta", "erro"
    atraso: float = 0.0        # segundos que a legenda foi MOVIDA (+ = mais tarde)
    ganho: float = 1.0         # quanto o encaixe melhorou (1,0 = igual)
    detalhe: str = ""


def regua_da_legenda(falas: list[Fala], tamanho: int):
    import numpy as np
    regua = np.zeros(tamanho, dtype=np.float32)
    for f in falas:
        try:
            ini, fim = horarios(f.tempo)
        except ValueError:
            continue
        regua[max(0, int(ini / PASSO)):max(0, min(tamanho, int(fim / PASSO)))] = 1
    return regua


def regua_do_audio(video: str | Path):
    """Onde há voz no áudio do vídeo (1) ou não (0), de 10 em 10 ms. Lê o áudio em pedaços de 10 minutos."""
    import av
    import numpy as np
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    taxa, partes, pedaco, lidos = 16000, [], [], 0

    def ouvir(amostras):
        regua = np.zeros(int(len(amostras) / taxa / PASSO) + 1, dtype=np.float32)
        for trecho in get_speech_timestamps(amostras, VadOptions(min_silence_duration_ms=200, speech_pad_ms=0)):
            regua[int(trecho["start"] / taxa / PASSO):int(trecho["end"] / taxa / PASSO)] = 1
        return regua[:int(len(amostras) / taxa / PASSO)]
    with av.open(str(video)) as arquivo:
        if not arquivo.streams.audio:
            raise ErroLegenda("o vídeo não tem áudio")
        conversor = av.AudioResampler(format="flt", layout="mono", rate=taxa)
        for quadro in arquivo.decode(audio=0):
            for convertido in conversor.resample(quadro):
                dados = convertido.to_ndarray().reshape(-1)
                pedaco.append(dados)
                lidos += len(dados)
                if lidos >= TRECHO * taxa:
                    partes.append(ouvir(np.concatenate(pedaco)))
                    pedaco, lidos = [], 0
        if pedaco:
            partes.append(ouvir(np.concatenate(pedaco)))
    return np.concatenate(partes) if partes else np.zeros(0, dtype=np.float32)


def melhor_atraso(audio, legenda, maximo: float = ATRASO_MAXIMO) -> tuple[float, float]:
    """(atraso em segundos, ganho): quanto MOVER a legenda para encaixar no áudio, e quanto o encaixe melhora."""
    import numpy as np
    n = max(len(audio), len(legenda))
    a = np.zeros(n, dtype=np.float32)
    b = np.zeros(n, dtype=np.float32)
    a[:len(audio)], b[:len(legenda)] = audio, legenda
    a, b = a * 2 - 1, b * 2 - 1                         # +1 fala, -1 silêncio: encaixa fala E silêncio
    tamanho = 1 << (2 * n - 1).bit_length()
    correlacao = np.fft.irfft(np.fft.rfft(a, tamanho) * np.conj(np.fft.rfft(b, tamanho)), tamanho)
    passos = int(maximo / PASSO)
    candidatos = np.concatenate([correlacao[:passos + 1], correlacao[-passos:]])   # 0..+max e -max..-1
    deslocamentos = np.concatenate([np.arange(passos + 1), np.arange(-passos, 0)])
    melhor = int(np.argmax(candidatos))
    atual = float(correlacao[0])
    escala = float(n)                                   # correlação vai de -n a +n: põe tudo positivo
    ganho = (float(candidatos[melhor]) + escala) / (atual + escala) if atual + escala > 0 else 1.0
    return float(deslocamentos[melhor]) * PASSO, ganho


def deslocar(falas: list[Fala], segundos: float) -> list[Fala]:
    """As mesmas falas, todas `segundos` mais tarde (negativo = mais cedo; nada fica antes do 0)."""
    novas = []
    for f in falas:
        ini, fim = horarios(f.tempo)
        novas.append(Fala(f"{tempo_srt(max(0.0, ini + segundos))} --> {tempo_srt(max(0.0, fim + segundos))}",
                          f.texto))
    return novas


def sincronizar(legenda: str | Path, video: str | Path, ouvir=regua_do_audio) -> ResultadoSincronia:
    """Confere a legenda contra o áudio e, se estiver adiantada/atrasada, corrige (guardando a original)."""
    legenda = Path(legenda)
    try:
        falas = ler_srt(extrair_srt(legenda.read_bytes()))
    except (OSError, ErroLegenda) as erro:
        return ResultadoSincronia(legenda, "erro", detalhe=f"não deu para ler a legenda: {erro}")
    if len(falas) < 10:
        return ResultadoSincronia(legenda, "incerta", detalhe="poucas falas para comparar")
    try:
        audio = ouvir(video)
    except Exception as erro:                           # sem PyAV/Whisper, arquivo ruim...
        return ResultadoSincronia(legenda, "erro", detalhe=f"não deu para ouvir o áudio: {str(erro)[:150]}")
    if len(audio) == 0 or audio.sum() == 0:
        return ResultadoSincronia(legenda, "incerta", detalhe="nenhuma voz encontrada no áudio")
    atraso, ganho = melhor_atraso(audio, regua_da_legenda(falas, len(audio)))
    if abs(atraso) < MINIMO:
        return ResultadoSincronia(legenda, "ja_certa", atraso, ganho)
    if ganho < GANHO_MINIMO:
        return ResultadoSincronia(legenda, "incerta", 0.0, ganho, f"o encaixe em {atraso:+.2f} s não é claramente "
                                  "melhor (legenda de outra versão do vídeo?)")
    original = legenda.with_name(legenda.name + ".original")
    try:
        if not original.exists():
            original.write_bytes(legenda.read_bytes())
        parcial = legenda.with_name(legenda.name + ".part")
        parcial.write_text(gerar_srt(deslocar(falas, atraso)), encoding="utf-8")
        parcial.replace(legenda)
    except OSError as erro:
        return ResultadoSincronia(legenda, "erro", detalhe=f"não deu para gravar: {erro}")
    return ResultadoSincronia(legenda, "ajustada", atraso, ganho)


def legendas_para_sincronizar(*pastas, conferidas: dict | None = None) -> list[tuple[Path, Path]]:
    """[(legenda .srt, vídeo)] das bibliotecas, menos as já conferidas sem mudança desde então
    (conferidas: {caminho da legenda: data de modificação quando foi conferida})."""
    from .nomes import eh_video_da_biblioteca
    conferidas = conferidas or {}
    pares = []
    for pasta in pastas:
        if not pasta or not Path(pasta).is_dir():
            continue
        for video in sorted(Path(pasta).rglob("*")):
            if ".organizador" in video.parts or not video.is_file() or not eh_video_da_biblioteca(video):
                continue
            irmas = [a for a in video.parent.iterdir() if a.name.startswith(video.stem + ".")]   # sem glob: "[" no nome
            for legenda in sorted(a for a in irmas if a.suffix.lower() == ".srt"):
                if not legenda.is_file() or ".forced" in legenda.name.lower():
                    continue
                if conferidas.get(str(legenda)) == legenda.stat().st_mtime:
                    continue
                pares.append((legenda, video))
    return pares


class Conferidas:
    """{legenda: data de modificação} das já conferidas: da próxima vez só as novas ou mudadas são ouvidas."""

    def __init__(self, arquivo: str | Path):
        self.arquivo = Path(arquivo)
        try:
            self.dados = json.loads(self.arquivo.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.dados = {}

    def marcar(self, legenda: Path) -> None:
        try:
            self.dados[str(legenda)] = legenda.stat().st_mtime
            self.arquivo.parent.mkdir(parents=True, exist_ok=True)
            self.arquivo.write_text(json.dumps(self.dados, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
