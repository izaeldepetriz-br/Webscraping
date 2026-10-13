"""Trocar o áudio entre versões de um filme (aba "🎧 Áudio"): ler as faixas, conferir o encaixe, ajustar atraso,
velocidade e volume, e pôr a faixa no destino (ou só extrair para um .mka).

Como o encaixe é medido: das duas faixas, o ffmpeg tira um pedaço do som (mono, 8 mil amostras por segundo); daí sai a
"curva de ataques" (onde o som cresce de repente: uma batida, uma porta, uma explosão), de 10 em 10 ms. As falas são
diferentes nos dois idiomas, mas a música e os efeitos são os mesmos, então as duas curvas casam quando o atraso está
certo. A conta é feita em 3 pontos do filme (começo, meio e fim): se o atraso muda de um ponto para o outro, ou a
velocidade é outra (versão europeia, 25 quadros/s, ~4% mais rápida) ou as versões têm cortes diferentes.

A imagem nunca é refeita. A faixa entra copiada como está ("multiplexação direta") quando só o atraso muda; com
velocidade ou volume, só o áudio é refeito (AC3, na mesma qualidade). Tudo no PC, com o ffmpeg que vem no Maestro.
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from .dublagem import (MESMO_MP4, SEM_JANELA, ErroDublagem, _rodar_ffmpeg, destino_no_original, inspecionar,
                       temporario_no_original, trocar_original)


class ErroTrocaAudio(ErroDublagem):
    pass


# ----------------------------------------------------------------- idiomas (as faixas usam o código de 3 letras)
IDIOMAS = {"por": "Português", "eng": "Inglês", "spa": "Espanhol", "fre": "Francês", "fra": "Francês",
           "ger": "Alemão", "deu": "Alemão", "ita": "Italiano", "jpn": "Japonês", "kor": "Coreano", "chi": "Chinês",
           "zho": "Chinês", "rus": "Russo", "hin": "Hindi", "ara": "Árabe", "pol": "Polonês", "tur": "Turco",
           "dut": "Holandês", "nld": "Holandês", "swe": "Sueco", "dan": "Dinamarquês", "nor": "Norueguês",
           "fin": "Finlandês", "gre": "Grego", "ell": "Grego", "heb": "Hebraico", "hun": "Húngaro", "cze": "Tcheco",
           "ces": "Tcheco", "rum": "Romeno", "ron": "Romeno", "tha": "Tailandês", "ukr": "Ucraniano", "cat": "Catalão"}
DE_DUAS_LETRAS = {"pt": "por", "en": "eng", "es": "spa", "fr": "fre", "de": "ger", "it": "ita", "ja": "jpn",
                  "ko": "kor", "zh": "chi", "ru": "rus", "hi": "hin", "ar": "ara", "pl": "pol", "tr": "tur",
                  "nl": "dut", "sv": "swe", "da": "dan", "no": "nor", "fi": "fin", "el": "gre", "he": "heb",
                  "hu": "hun", "cs": "cze", "ro": "rum", "th": "tha", "uk": "ukr", "ca": "cat"}
MENU_IDIOMAS = ["Português (por)", "Inglês (eng)", "Espanhol (spa)", "Francês (fre)", "Italiano (ita)",
                "Alemão (ger)", "Japonês (jpn)", "Coreano (kor)", "Chinês (chi)", "Russo (rus)"]


def nome_idioma(codigo: str) -> str:
    """'por' -> 'Português'; vazio -> 'sem idioma marcado'; desconhecido volta como está."""
    codigo = (codigo or "").lower()
    if not codigo or codigo == "und":
        return "sem idioma marcado"
    return IDIOMAS.get(codigo, IDIOMAS.get(DE_DUAS_LETRAS.get(codigo, ""), codigo))


def codigo_de(texto: str) -> str:
    """'Português (por)' / 'pt' / 'por' -> 'por'."""
    achado = re.search(r"\((\w{2,3})\)\s*$", texto or "")
    codigo = (achado[1] if achado else (texto or "")).strip().lower()
    return DE_DUAS_LETRAS.get(codigo, codigo)


# ----------------------------------------------------------------- as faixas de um arquivo
LEGENDAS_DE_TEXTO = {"subrip", "srt", "ass", "ssa", "mov_text", "webvtt", "text"}
NAO_CABEM_NO_MP4 = {"dts", "truehd", "mlp", "flac", "opus", "vorbis"}


@dataclass
class Faixa:
    tipo: str                      # "audio" ou "legenda"
    ordem: int                     # a posição entre as do mesmo tipo (0:a:N, 0:s:N)
    idioma: str = ""               # "por", "eng"... ("" = sem idioma marcado)
    formato: str = ""              # "ac3", "dts", "subrip", "hdmv_pgs_subtitle"...
    canais: str = ""               # "5.1", "2.0"
    num_canais: int = 0
    titulo: str = ""
    padrao: bool = False
    forcada: bool = False
    detectado: bool = False        # o idioma foi descoberto pelo Whisper (a faixa não tinha)

    @property
    def de_texto(self) -> bool:
        return self.formato in LEGENDAS_DE_TEXTO

    @property
    def nome_formato(self) -> str:
        nomes = {"ac3": "AC3", "eac3": "E-AC3", "dts": "DTS", "truehd": "TrueHD", "aac": "AAC", "mp3": "MP3",
                 "flac": "FLAC", "opus": "Opus", "vorbis": "Vorbis", "subrip": "texto (SRT)", "ass": "texto (ASS)",
                 "ssa": "texto (SSA)", "mov_text": "texto (MP4)", "webvtt": "texto (VTT)",
                 "hdmv_pgs_subtitle": "imagem (PGS)", "dvd_subtitle": "imagem (VobSub)", "dvb_subtitle": "imagem (DVB)"}
        if self.formato.startswith("pcm"):
            return "PCM"
        return nomes.get(self.formato, self.formato.upper())


@dataclass
class InfoArquivo:
    caminho: Path
    duracao: float | None
    audios: list[Faixa] = field(default_factory=list)
    legendas: list[Faixa] = field(default_factory=list)
    videos: int = 0
    fps: float | None = None

    def resumo(self) -> str:
        """'áudio Inglês (DTS 5.1) · legendas Português, Inglês · duração 1:57:00'."""
        audios = ", ".join(f"{nome_idioma(a.idioma)} ({a.nome_formato} {a.canais})".replace(" )", ")")
                           for a in self.audios) or "nenhum"
        legendas = ", ".join(dict.fromkeys(nome_idioma(s.idioma) for s in self.legendas)) or "nenhuma"
        return f"áudio {audios} · legendas {legendas} · duração {hms(self.duracao or 0)}"


def hms(segundos: float) -> str:
    s = int(round(max(segundos, 0)))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


def _canais(layout: str) -> tuple[str, int]:
    layout = layout.strip().lower()
    conhecidos = {"mono": ("1.0", 1), "stereo": ("2.0", 2), "2.1": ("2.1", 3), "quad": ("4.0", 4), "4.0": ("4.0", 4),
                  "5.0": ("5.0", 5), "5.1": ("5.1", 6), "6.1": ("6.1", 7), "7.1": ("7.1", 8)}
    base = layout.split("(")[0]
    if base in conhecidos:
        return conhecidos[base]
    achado = re.match(r"(\d+) channels", layout)
    if achado:
        n = int(achado[1])
        return {1: "1.0", 2: "2.0", 6: "5.1", 8: "7.1"}.get(n, f"{n} canais"), n
    return layout, 0


def ler_arquivo(ffmpeg: str, caminho: str | Path) -> InfoArquivo:
    """As faixas de áudio e de legenda (idioma, formato, canais, título, padrão, forçada), pelo próprio ffmpeg."""
    caminho = Path(caminho)
    r = subprocess.run([ffmpeg, "-hide_banner", "-i", str(caminho)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", **SEM_JANELA)
    texto = r.stderr
    if "Invalid data found" in texto or "No such file" in texto or "Stream #" not in texto:
        raise ErroTrocaAudio(f"o ffmpeg não reconheceu {caminho.name} como vídeo ou áudio")
    achado = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", texto)
    duracao = (int(achado[1]) * 3600 + int(achado[2]) * 60 + float(achado[3])) if achado else None
    info = InfoArquivo(caminho, duracao)
    atual = None
    for linha in texto.splitlines():
        stream = re.match(r"\s*Stream #\d+:\d+(?:\[\w+\])?(?:\((\w+)\))?.*?: (Video|Audio|Subtitle): ([^,\s]+)(.*)",
                          linha)
        if stream:
            idioma, tipo, formato, resto = stream[1] or "", stream[2], stream[3], stream[4]
            idioma = "" if idioma.lower() == "und" else idioma.lower()
            atual = None
            if tipo == "Video":
                info.videos += 1
                fps = re.search(r"([\d.]+) fps", resto)
                if fps and info.fps is None:
                    info.fps = float(fps[1])
                continue
            disposicoes = re.findall(r"\((\w+)\)", resto)
            if tipo == "Audio":
                partes = [p.strip() for p in resto.split(",")]
                layout = partes[2] if len(partes) > 2 else ""
                canais, num = _canais(layout)
                atual = Faixa("audio", len(info.audios), idioma, formato.lower(), canais, num,
                              padrao="default" in disposicoes)
                info.audios.append(atual)
            else:
                atual = Faixa("legenda", len(info.legendas), idioma, formato.lower(), padrao="default" in disposicoes,
                              forcada="forced" in disposicoes)
                info.legendas.append(atual)
            continue
        titulo = re.match(r"\s+title\s*:\s*(.*)", linha)
        if titulo and atual is not None and not atual.titulo:
            atual.titulo = titulo[1].strip()
    return info


def detectar_idioma(ffmpeg: str, arquivo: Path, faixa: Faixa, transcritor, inicio: float = 0.0) -> str:
    """O idioma de uma faixa sem etiqueta: o Whisper ouve 30 s (no PC). Devolve o código de 3 letras ('' se não
    deu)."""
    with tempfile.TemporaryDirectory() as pasta:
        wav = Path(pasta) / "trecho.wav"
        subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{max(inicio, 0):.3f}", "-t", "30",
                        "-i", str(arquivo), "-map", f"0:a:{faixa.ordem}", "-ac", "1", "-ar", "16000", str(wav)],
                       capture_output=True, **SEM_JANELA)
        if not wav.is_file():
            return ""
        lingua = transcritor.transcrever(wav)[0] or ""
    return DE_DUAS_LETRAS.get(lingua.lower(), lingua.lower())


# ----------------------------------------------------------------- a curva de ataques e o encaixe
TAXA = 8000                        # amostras por segundo (só para comparar: não precisa de mais)
PASSO = 0.01                       # 10 ms por ponto da curva
TOLERANCIA = 0.10                  # s: diferença que sobra e ainda é "boca e voz juntas"
LIMITE_CORTES = 0.30               # s: mais que isso entre os pontos = versões com cortes diferentes
VELOCIDADES = {"Automática": None, "Igual (sem mudar)": 1.0, "25 → 23,976 (versão europeia)": 25 / 23.976,
               "23,976 → 25": 23.976 / 25, "24 → 23,976": 24 / 23.976, "Esticar até a duração do destino": "esticar"}
_CANDIDATOS = (1.0, 25 / 23.976, 23.976 / 25, 24 / 23.976, 23.976 / 24)


def nome_da_velocidade(fator: float) -> str:
    """1.0427 -> '25 → 23,976'; 1.0 -> 'igual'; outro -> 'x1,0012'."""
    if abs(fator - 1) < 1e-4:
        return "igual"
    for nome, valor in VELOCIDADES.items():
        if isinstance(valor, float) and abs(valor - fator) < 1e-4:
            return nome.split(" (")[0]
    return f"x{fator:.4f}".replace(".", ",")


def som(ffmpeg: str, arquivo: Path, ordem: int, inicio: float, duracao: float, taxa: int = TAXA):
    """O som de uma faixa (mono, float de -1 a 1) entre inicio e inicio+duracao. Antes do começo do arquivo: silêncio."""
    import numpy as np
    antes = max(0.0, -inicio)
    inicio = max(0.0, inicio)
    duracao = max(0.0, duracao - antes)
    # first_pts=0: se a faixa começa um pouco depois do zero (o AC3 começa ~32 ms depois), esse começo vira silêncio;
    # sem isso, o pedaço lido do início do arquivo ficava adiantado em relação a um lido do meio
    r = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-ss", f"{inicio:.3f}", "-t", f"{duracao:.3f}",
                        "-i", str(arquivo), "-map", f"0:a:{ordem}", "-ac", "1",
                        "-af", f"aresample={taxa}:async=1:first_pts=0", "-f", "s16le", "-"],
                       capture_output=True, **SEM_JANELA)
    amostras = np.frombuffer(r.stdout, dtype="<i2").astype(np.float32) / 32768.0
    if antes:
        amostras = np.concatenate([np.zeros(int(antes * taxa), dtype=np.float32), amostras])
    return amostras


def ataques(amostras, por_quadro: int = int(TAXA * PASSO)):
    """A curva de ataques: quanto o som cresce de um quadro (10 ms) para o seguinte, em escala log, normalizada."""
    import numpy as np
    quadros = len(amostras) // por_quadro
    if quadros < 2:
        return np.zeros(max(quadros, 0), dtype=np.float32)
    energia = (amostras[:quadros * por_quadro].reshape(quadros, por_quadro) ** 2).mean(axis=1)
    log = np.log10(energia + 1e-7)
    subida = np.diff(log, prepend=log[0])
    subida[subida < 0] = 0
    desvio = subida.std()
    return ((subida - subida.mean()) / desvio).astype(np.float32) if desvio > 0 else subida.astype(np.float32)


def nivel(amostras, por_quadro: int = int(TAXA * PASSO)):
    """O volume (RMS) de cada quadro de 10 ms, de 0 a 1: para desenhar a onda."""
    import numpy as np
    quadros = len(amostras) // por_quadro
    if quadros < 1:
        return np.zeros(0, dtype=np.float32)
    return np.sqrt((amostras[:quadros * por_quadro].reshape(quadros, por_quadro) ** 2).mean(axis=1)).astype(np.float32)


def _correlacao(curva_destino, curva_origem):
    """(posição do melhor encaixe da curva do destino dentro da da origem, em quadros com fração; força 0..1)."""
    import numpy as np
    n = len(curva_destino)
    if n < 10 or len(curva_origem) < n:
        return 0.0, 0.0
    valores = np.correlate(curva_origem, curva_destino, mode="valid") / n
    k = int(np.argmax(valores))
    melhor = float(valores[k])
    fracao = 0.0
    if 0 < k < len(valores) - 1:                       # o pico entre dois quadros (mais preciso que 10 ms)
        a, b, c = valores[k - 1], valores[k], valores[k + 1]
        divisor = a - 2 * b + c
        if divisor:
            fracao = float(0.5 * (a - c) / divisor)
    return k + max(-0.5, min(0.5, fracao)), max(0.0, min(1.0, melhor))


@dataclass
class Ponto:
    tempo: float                   # s no destino (o começo do trecho comparado)
    atraso: float | None           # o atraso medido ali (None = não deu para medir)
    forca: float = 0.0             # 0..1: quanto as curvas casaram
    sobra: float | None = None     # quanto sobra em relação ao ajuste escolhido

    @property
    def ok(self) -> bool:
        return self.sobra is not None and self.sobra <= TOLERANCIA


@dataclass
class Encaixe:
    fator: float = 1.0             # nova = origem × fator + atraso
    atraso: float = 0.0
    pontos: list[Ponto] = field(default_factory=list)
    situacao: str = ""             # "mesma", "ajuste", "cortes", "sem_dados"
    manual: bool = False
    fator_achado: float = 1.0      # o que o automático achou (fica mostrado ao lado do manual)
    atraso_achado: float = 0.0

    @property
    def ok(self) -> bool:
        return self.situacao in ("mesma", "ajuste")

    def texto_situacao(self) -> str:
        if self.situacao == "mesma":
            return "Encaixa sem ajuste: a faixa é copiada como está (rápido, sem perder qualidade)"
        if self.situacao == "ajuste":
            return "Encaixa com o ajuste " + ("MANUAL" if self.manual else "automático")
        if self.situacao == "cortes":
            return ("Versões diferentes: o atraso muda ao longo do filme (cena a mais ou a menos). Não dá para "
                    "encaixar com segurança")
        return "Não deu para comparar (pouco som em comum nos trechos: tente o ajuste manual e ouça os 30 s)"


def pontos_do_filme(duracao: float, janela: float) -> list[float]:
    """Os 3 trechos comparados: começo, meio e fim (sem pegar o finalzinho, que pode ser só créditos)."""
    if duracao <= janela * 3:
        return [0.0, max(0.0, (duracao - janela) / 2), max(0.0, duracao - janela)]
    return list(dict.fromkeys(min(round(duracao * fracao), round(duracao - janela - 1)) for fracao in (0.05, 0.5, 0.9)))


def _janela(duracao: float) -> float:
    return max(4.0, min(30.0, duracao / 5))


def medir_ponto(ffmpeg: str, origem: Path, faixa: int, destino: Path, faixa_destino: int, tempo: float, janela: float,
                fator: float, palpite: float, busca: float) -> Ponto:
    """O atraso no trecho [tempo, tempo+janela] do destino, procurando ±busca s em volta do palpite."""
    taxa_origem = max(1000, int(round(TAXA * fator)))       # na origem, cada quadro vale 10 ms do destino
    fator_real = taxa_origem / TAXA
    destino_curva = ataques(som(ffmpeg, destino, faixa_destino, tempo, janela))
    inicio_origem = (tempo - palpite - busca) / fator_real
    duracao_origem = (janela + 2 * busca) / fator_real
    origem_curva = ataques(som(ffmpeg, origem, faixa, inicio_origem, duracao_origem, taxa_origem),
                           int(TAXA * PASSO))
    k, forca = _correlacao(destino_curva, origem_curva)
    if forca < 0.08:
        return Ponto(tempo, None, forca)
    # o quadro k da origem cai no começo do trecho do destino: nova = origem × fator + atraso
    atraso = tempo - fator_real * inicio_origem - k * PASSO
    return Ponto(tempo, round(atraso, 3), round(forca, 3))


def conferir_encaixe(ffmpeg: str, origem: Path, faixa: int, destino: Path, faixa_destino: int = 0,
                     duracao_origem: float | None = None, duracao_destino: float | None = None,
                     velocidade: str = "Automática", atraso_manual: float | None = None, parar=None,
                     ao_progresso=None) -> Encaixe:
    """Compara a faixa da origem com o áudio do destino em 3 pontos. Automático: acha a velocidade (pela duração e
    pela deriva do atraso) e o atraso. Manual (atraso_manual e/ou uma velocidade escolhida): só mede quanto sobra."""
    origem, destino = Path(origem), Path(destino)
    if duracao_origem is None or duracao_destino is None:
        duracao_origem = duracao_origem or inspecionar(ffmpeg, origem).duracao
        duracao_destino = duracao_destino or inspecionar(ffmpeg, destino).duracao
    if not duracao_origem or not duracao_destino:
        raise ErroTrocaAudio("não deu para ler a duração dos arquivos")
    janela = _janela(duracao_destino)
    tempos = pontos_do_filme(duracao_destino, janela)
    escolha = VELOCIDADES.get(velocidade)
    if escolha == "esticar":
        candidatos = [duracao_destino / duracao_origem]
    elif isinstance(escolha, float):
        candidatos = [escolha]
    else:                                             # automática: todas, a mais provável pela duração primeiro
        razao = duracao_destino / duracao_origem
        candidatos = sorted(_CANDIDATOS, key=lambda c: abs(razao / c - 1))
    manual = atraso_manual is not None or velocidade != "Automática"
    busca = min(120.0, max(janela, duracao_destino / 3))
    passos = len(candidatos) * len(tempos) + (len(tempos) if atraso_manual is not None else 0)
    feitos = [0]

    def andou():
        feitos[0] += 1
        if ao_progresso:
            ao_progresso(min(feitos[0] / max(passos, 1), 1.0))
        if parar and parar():
            raise ErroTrocaAudio("interrompido (botão Parar)")

    melhor = None
    for posicao, fator in enumerate(candidatos):
        padrao = True                                 # uma das velocidades conhecidas (não corrigida pela deriva)
        pontos = []
        for t in tempos:
            pontos.append(medir_ponto(ffmpeg, origem, faixa, destino, faixa_destino, t, janela, fator, 0.0, busca))
            andou()
        medidos = [p for p in pontos if p.atraso is not None]
        if len(medidos) >= 2:                         # deriva = velocidade um pouco diferente: corrige o fator
            inclinacao = _inclinacao([(p.tempo, p.atraso) for p in medidos])
            espalhado = max(p.atraso for p in medidos) - min(p.atraso for p in medidos)
            if espalhado > TOLERANCIA and abs(inclinacao) < 0.01:
                fator_corrigido = fator / (1 - inclinacao)
                palpite = sorted(p.atraso for p in medidos)[len(medidos) // 2]
                refeitos = [medir_ponto(ffmpeg, origem, faixa, destino, faixa_destino, t, janela, fator_corrigido,
                                        palpite, min(busca, 10.0)) for t in tempos]
                if _espalhado(refeitos) < espalhado:
                    fator, pontos, padrao = fator_corrigido, refeitos, False
        # a melhor: mais pontos medidos; depois, menos espalhada (de 0,05 em 0,05 s: diferenças menores não
        # contam); depois, uma velocidade conhecida; depois, a mais provável pela duração
        nota = (len([p for p in pontos if p.atraso is not None]), -round(_espalhado(pontos) / 0.05), padrao,
                -posicao)
        if melhor is None or nota > melhor[0]:
            melhor = (nota, fator, pontos)
        medidos = [p for p in pontos if p.atraso is not None]
        if len(medidos) == len(tempos) and _espalhado(pontos) <= TOLERANCIA and padrao:
            break                                     # a mais provável já encaixa: não precisa testar as outras
    _, fator, pontos = melhor
    medidos = sorted(p.atraso for p in pontos if p.atraso is not None)
    atraso_achado = medidos[len(medidos) // 2] if medidos else 0.0
    encaixe = Encaixe(fator=fator, atraso=atraso_achado, pontos=pontos, manual=manual, fator_achado=fator,
                      atraso_achado=atraso_achado)
    if atraso_manual is not None:                     # manual: mede de novo em volta do atraso escolhido
        encaixe.atraso = atraso_manual
        encaixe.pontos = []
        for t in tempos:
            encaixe.pontos.append(medir_ponto(ffmpeg, origem, faixa, destino, faixa_destino, t, janela, fator,
                                              atraso_manual, min(busca, 10.0)))
            andou()
    for p in encaixe.pontos:
        p.sobra = None if p.atraso is None else round(abs(p.atraso - encaixe.atraso), 3)
    medidos = [p for p in encaixe.pontos if p.atraso is not None]
    if not medidos:
        encaixe.situacao = "sem_dados"
    elif _espalhado(encaixe.pontos) > LIMITE_CORTES or any(p.sobra > LIMITE_CORTES for p in medidos):
        encaixe.situacao = "cortes"
    elif abs(encaixe.fator - 1) < 1e-4 and abs(encaixe.atraso) < 0.04:
        encaixe.situacao = "mesma"
    else:
        encaixe.situacao = "ajuste"
    return encaixe


def _espalhado(pontos) -> float:
    medidos = [p.atraso for p in pontos if p.atraso is not None]
    return (max(medidos) - min(medidos)) if len(medidos) >= 2 else 0.0


def _inclinacao(pares) -> float:
    """A reta que passa pelos (tempo, atraso): quanto o atraso muda por segundo de filme."""
    n = len(pares)
    media_t = sum(t for t, _ in pares) / n
    media_a = sum(a for _, a in pares) / n
    cima = sum((t - media_t) * (a - media_a) for t, a in pares)
    baixo = sum((t - media_t) ** 2 for t, _ in pares)
    return cima / baixo if baixo else 0.0


# ----------------------------------------------------------------- volume (loudness, em LUFS)
VOLUMES = ("Manter como está (cópia direta)", "Igualar ao áudio original do destino", "Ajuste manual (dB)")
DIFERENCA_PARA_IGUALAR = 2.0       # dB: abaixo disso, a faixa é copiada sem mexer


def loudness(ffmpeg: str, arquivo: Path, ordem: int, tempos: list[float], janela: float = 60.0) -> float | None:
    """A altura percebida (LUFS, o padrão das TVs) da faixa, medida nos trechos (média da energia)."""
    import math
    valores = []
    for t in tempos:
        r = subprocess.run([ffmpeg, "-hide_banner", "-nostats", "-ss", f"{max(t, 0):.3f}", "-t", f"{janela:.3f}", "-i",
                            str(arquivo), "-map", f"0:a:{ordem}", "-af", "ebur128=framelog=quiet", "-f", "null", "-"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", **SEM_JANELA)
        achados = re.findall(r"I:\s+(-?\d+(?:\.\d+)?) LUFS", r.stderr)
        if achados and float(achados[-1]) > -70:
            valores.append(float(achados[-1]))
    if not valores:
        return None
    return round(10 * math.log10(sum(10 ** (v / 10) for v in valores) / len(valores)), 1)


# ----------------------------------------------------------------- o ajuste e a faixa nova
@dataclass
class Ajuste:
    fator: float = 1.0             # nova = origem × fator + atraso
    atraso: float = 0.0
    ganho_db: float = 0.0

    @property
    def refaz_audio(self) -> bool:
        return abs(self.fator - 1) > 1e-6 or abs(self.ganho_db) >= 0.05

    def texto(self) -> str:
        """'atraso −4,30 s · 25 → 23,976 · +5,8 dB' (o que vai no título da faixa e no histórico)."""
        partes = [f"atraso {self.atraso:+.2f} s".replace(".", ",").replace("-", "−")]
        if abs(self.fator - 1) > 1e-6:
            partes.append(nome_da_velocidade(self.fator))
        if abs(self.ganho_db) >= 0.05:
            partes.append(f"{self.ganho_db:+.1f} dB".replace(".", ","))
        return " · ".join(partes)


def titulo_da_faixa(idioma: str, origem: Path, ajuste: Ajuste) -> str:
    """'Português · de Meu Filme (2010) - DVD dublado · atraso −4,30 s · 25 → 23,976 · +5,8 dB'."""
    return f"{nome_idioma(idioma)} · de {Path(origem).stem} · {ajuste.texto()}"


def _filtro(ajuste: Ajuste) -> str:
    """atempo (velocidade, sem mudar o tom), volume com proteção de picos e o atraso (no tempo do destino)."""
    partes = []
    if abs(ajuste.fator - 1) > 1e-6:
        partes.append(f"atempo={1 / ajuste.fator:.6f}")
    if abs(ajuste.ganho_db) >= 0.05:
        partes.append(f"volume={ajuste.ganho_db:.2f}dB")
        if ajuste.ganho_db > 0:
            partes.append("alimiter=limit=0.97:level=disabled")
    if ajuste.atraso > 0.0005:
        partes.append(f"adelay=delays={int(round(ajuste.atraso * 1000))}:all=1")
    elif ajuste.atraso < -0.0005:
        partes.append(f"atrim=start={-ajuste.atraso:.3f},asetpts=PTS-STARTPTS")
    return ",".join(partes) or "anull"


def _codec_novo(faixa: Faixa, formato_saida: str) -> list[str]:
    """O áudio refeito: AC3 (até 5.1, 640 kb/s), ou FLAC no .mkv quando tem mais canais (o .mp4 desce para 5.1)."""
    if faixa.num_canais > 6:
        if formato_saida == "matroska":
            return ["flac"]
        return ["ac3", "640k", "6"]
    return ["ac3", "640k" if faixa.num_canais > 2 else "224k", ""]


def precisa_converter(faixa: Faixa, formato_saida: str) -> bool:
    return formato_saida == "mp4" and (faixa.formato in NAO_CABEM_NO_MP4 or faixa.formato.startswith("pcm"))


def ajustar_srt(texto: str, fator: float, atraso: float) -> str:
    """Os horários de uma legenda .srt com o mesmo ajuste do áudio (nova = origem × fator + atraso)."""
    def novo(achado) -> str:
        h, m, s, ms = (int(x) for x in achado.groups())
        t = max(0.0, (h * 3600 + m * 60 + s + ms / 1000) * fator + atraso)
        total = int(round(t * 1000))
        return f"{total // 3600000:02d}:{total % 3600000 // 60000:02d}:{total % 60000 // 1000:02d},{total % 1000:03d}"
    return re.sub(r"(\d{2}):(\d{2}):(\d{2}),(\d{3})", novo, texto)


def _legenda_srt(ffmpeg: str, origem: Path, legenda: Faixa, ajuste: Ajuste, pasta: Path) -> Path | None:
    """A legenda de texto da origem, em .srt, com os horários ajustados."""
    bruto = pasta / f"legenda-{legenda.ordem}.srt"
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(origem), "-map",
                    f"0:s:{legenda.ordem}", "-c:s", "srt", str(bruto)], capture_output=True, **SEM_JANELA)
    if not bruto.is_file():
        return None
    final = pasta / f"legenda-{legenda.ordem}-ajustada.srt"
    final.write_text(ajustar_srt(bruto.read_text(encoding="utf-8", errors="replace"), ajuste.fator, ajuste.atraso),
                     encoding="utf-8")
    return final


@dataclass
class Pedido:
    """O que inserir: as faixas de áudio (e de legenda) marcadas da origem, com o idioma de cada uma."""
    origem: Path
    destino: Path
    audios: list[Faixa]
    legendas: list[Faixa] = field(default_factory=list)
    ajuste: Ajuste = field(default_factory=Ajuste)
    principal: bool = True         # a 1ª marcada vira a faixa principal (padrão) do destino
    onde: str = "dentro"           # "dentro" (o próprio arquivo, conferido antes de trocar), "copia" ou "extrair"


@dataclass
class Resultado:
    saida: Path
    avisos: list[str] = field(default_factory=list)
    refez_audio: bool = False


ONDES = {"dentro": "Dentro do próprio arquivo (conferido antes de trocar)",
         "copia": "Numa cópia à parte (Nome - com áudio PT.mkv)"}


def saida_da_copia(destino: Path, idioma: str) -> Path:
    """'Meu Filme (2010) 1080p - com áudio Português.mkv' (o .mp4 continua .mp4; .avi e outros viram .mkv)."""
    final, formato = destino_no_original(destino)
    return destino.with_name(f"{destino.stem} - com áudio {nome_idioma(idioma)}{final.suffix}")


def saida_extraida(destino: Path, idioma: str) -> Path:
    return destino.with_name(f"{destino.stem} - {nome_idioma(idioma)}.mka")


def _comando(ffmpeg: str, pedido: Pedido, saida: Path, formato: str, info_destino: InfoArquivo, pasta: Path,
             avisos: list, so_audio: bool = False, trecho: tuple[float, float] | None = None) -> tuple[list, int, int]:
    """O comando do ffmpeg e quantas faixas de áudio e de legenda entram. trecho: (início, duração) no destino,
    para a amostra de 30 s (a imagem é refeita leve; o áudio original vem junto, para comparar)."""
    aj = pedido.ajuste
    comando = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
    if not so_audio:
        if trecho:
            comando += ["-ss", f"{trecho[0]:.3f}", "-t", f"{trecho[1]:.3f}"]
        comando += ["-i", str(pedido.destino)]
    refazer = aj.refaz_audio or trecho is not None or any(precisa_converter(f, formato) for f in pedido.audios)
    entrada_audio = 0 if so_audio else 1
    if refazer:                                       # o ajuste vai pelos filtros (no tempo do destino)
        if trecho:                                    # da origem, só o pedaço que cai no trecho (com folga)
            inicio_origem = (trecho[0] - aj.atraso) / aj.fator
            comando += ["-ss", f"{max(0.0, inicio_origem - 1):.3f}", "-t", f"{trecho[1] / aj.fator + 2:.3f}"]
        comando += ["-i", str(pedido.origem)]
    else:                                             # cópia direta: o atraso desloca a faixa inteira
        if aj.atraso > 0.0005:
            comando += ["-itsoffset", f"{aj.atraso:.3f}"]
        elif aj.atraso < -0.0005:
            comando += ["-ss", f"{-aj.atraso:.3f}"]
        comando += ["-i", str(pedido.origem)]
    proxima_entrada = entrada_audio + 1
    # legendas: as de texto vão ajustadas em .srt; as de imagem só com a mesma velocidade (copiadas com o atraso)
    entradas_legenda = []
    for legenda in ([] if so_audio or trecho else pedido.legendas):
        if legenda.de_texto:
            srt = _legenda_srt(ffmpeg, pedido.origem, legenda, aj, pasta)
            if srt:
                comando += ["-i", str(srt)]
                entradas_legenda.append((f"{proxima_entrada}:0", legenda, "texto"))
                proxima_entrada += 1
            else:
                avisos.append(f"a legenda {legenda.ordem + 1} ({nome_idioma(legenda.idioma)}) não pôde ser lida")
        elif formato == "mp4":
            avisos.append(f"a legenda {legenda.ordem + 1} é de imagem: o .mp4 não aceita (grave em .mkv para trazê-la)")
        elif abs(aj.fator - 1) > 1e-6:
            avisos.append(f"a legenda {legenda.ordem + 1} é de imagem ({legenda.nome_formato}): com a velocidade "
                          "mudada, ela não é corrigida nesta versão (ficou de fora)")
        else:
            if aj.atraso > 0.0005:
                comando += ["-itsoffset", f"{aj.atraso:.3f}"]
            elif aj.atraso < -0.0005:
                comando += ["-ss", f"{-aj.atraso:.3f}"]
            comando += ["-i", str(pedido.origem)]
            entradas_legenda.append((f"{proxima_entrada}:s:{legenda.ordem}", legenda, "imagem"))
            proxima_entrada += 1
    filtros, rotulos = [], []
    if refazer:
        filtro = _filtro(aj)
        for i, faixa in enumerate(pedido.audios):
            atraso_amostra = ""
            if trecho:                                # recorta exatamente o trecho do destino
                inicio_origem = max(0.0, (trecho[0] - aj.atraso) / aj.fator - 1)
                inicio_novo = inicio_origem * aj.fator + aj.atraso   # onde a faixa recortada cai no destino
                filtro_trecho = _filtro(Ajuste(aj.fator, 0.0, aj.ganho_db))
                desloc = inicio_novo - trecho[0]
                atraso_amostra = (f",adelay=delays={int(round(desloc * 1000))}:all=1" if desloc > 0.0005 else
                                  f",atrim=start={-desloc:.3f},asetpts=PTS-STARTPTS" if desloc < -0.0005 else "")
                filtros.append(f"[{entrada_audio}:a:{faixa.ordem}]{filtro_trecho}{atraso_amostra},"
                               f"atrim=duration={trecho[1]:.3f}[n{i}]")
            else:
                filtros.append(f"[{entrada_audio}:a:{faixa.ordem}]{filtro}[n{i}]")
            rotulos.append(f"[n{i}]")
        comando += ["-filter_complex", ";".join(filtros)]
    existentes = 0 if so_audio else len(info_destino.audios)
    legendas_antes = 0 if (so_audio or trecho) else len(info_destino.legendas)
    if not so_audio:
        comando += ["-map", "0:v:0?" if trecho else "0:v?"]
        if trecho:                                    # amostra: a faixa nova primeiro, o áudio original depois
            for rotulo in rotulos:
                comando += ["-map", rotulo]
            comando += ["-map", "0:a:0?"]
        else:
            comando += ["-map", "0:a?"]
            if formato == "matroska" or info_destino.caminho.suffix.lower() in MESMO_MP4:
                comando += ["-map", "0:s?"]
                if formato == "matroska":
                    comando += ["-map", "0:t?"]
            else:
                legendas_antes = 0
    if not trecho:
        if refazer:
            for rotulo in rotulos:
                comando += ["-map", rotulo]
        else:
            for faixa in pedido.audios:
                comando += ["-map", f"{entrada_audio}:a:{faixa.ordem}"]
    for mapa, _, _ in entradas_legenda:
        comando += ["-map", mapa]
    # codecs: a imagem é copiada (na amostra, refeita leve); o áudio novo copiado ou refeito
    if trecho:
        comando += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-c:a", "aac", "-b:a", "192k"]
        primeiro_novo = 0
    else:
        comando += ["-c", "copy"]
        primeiro_novo = existentes
    if refazer and not trecho:
        for i, faixa in enumerate(pedido.audios):
            codec = _codec_novo(faixa, formato)
            comando += [f"-c:a:{primeiro_novo + i}", codec[0]]
            if len(codec) > 1 and codec[1]:
                comando += [f"-b:a:{primeiro_novo + i}", codec[1]]
            if len(codec) > 2 and codec[2]:
                comando += [f"-ac:a:{primeiro_novo + i}", codec[2]]
    if formato == "mp4":
        comando += ["-c:s", "mov_text"]
    elif entradas_legenda and any(tipo == "texto" for _, _, tipo in entradas_legenda):
        for k, (_, _, tipo) in enumerate(entradas_legenda):
            if tipo == "texto":
                comando += [f"-c:s:{legendas_antes + k}", "srt"]
    # idioma, título (com o ajuste) e qual é a principal
    for i, faixa in enumerate(pedido.audios):
        k = primeiro_novo + i
        comando += [f"-metadata:s:a:{k}", f"language={faixa.idioma or 'und'}",
                    f"-metadata:s:a:{k}", f"title={titulo_da_faixa(faixa.idioma, pedido.origem, aj)}"]
    if not so_audio and not trecho:
        if pedido.principal:
            for i in range(existentes):
                comando += [f"-disposition:a:{i}", "0"]
            comando += [f"-disposition:a:{existentes}", "default"]
            for i in range(1, len(pedido.audios)):
                comando += [f"-disposition:a:{existentes + i}", "0"]
        else:
            for i in range(len(pedido.audios)):
                comando += [f"-disposition:a:{existentes + i}", "0"]
    elif trecho:
        comando += ["-disposition:a:0", "default", "-disposition:a:1", "0"]
    for k, (_, legenda, _) in enumerate(entradas_legenda):
        s = legendas_antes + k
        comando += [f"-metadata:s:s:{s}", f"language={legenda.idioma or 'und'}",
                    f"-metadata:s:s:{s}", f"title={nome_idioma(legenda.idioma)}"
                    + (" (forçada)" if legenda.forcada else "") + f" · de {pedido.origem.stem}",
                    f"-disposition:s:{s}", "forced" if legenda.forcada else "0"]
    if trecho:
        comando += ["-t", f"{trecho[1]:.3f}"]
    elif aj.atraso < -0.0005:
        # cópia direta (áudio ou legenda de imagem) com atraso negativo: sem isto o ffmpeg copia também o começo
        # da origem (antes do -ss) e empurra o vídeo e as legendas do destino para a frente, desfazendo o atraso
        comando += ["-copypriorss", "0"]
    comando += ["-progress", "pipe:1", "-nostats", "-f", formato, str(saida)]
    return comando, len(pedido.audios), len(entradas_legenda)


def executar(ffmpeg: str, pedido: Pedido, parar=None, ao_progresso=None) -> Resultado:
    """Insere (no próprio destino, conferido antes de trocar, ou numa cópia) ou só extrai (.mka) as faixas."""
    if not pedido.audios:
        raise ErroTrocaAudio("marque pelo menos uma faixa de áudio da origem")
    info_destino = ler_arquivo(ffmpeg, pedido.destino)
    avisos: list[str] = []
    idioma = pedido.audios[0].idioma
    with tempfile.TemporaryDirectory() as temporaria:
        pasta = Path(temporaria)
        if pedido.onde == "extrair":
            saida = saida_extraida(pedido.destino, idioma)
            parcial = saida.with_name(saida.name + ".part")
            comando, _, _ = _comando(ffmpeg, pedido, parcial, "matroska", info_destino, pasta, avisos, so_audio=True)
            _rodar_ffmpeg(comando, info_destino.duracao, parar, ao_progresso, "o ffmpeg não conseguiu extrair a faixa")
            parcial.replace(saida)
            return Resultado(saida, avisos, pedido.ajuste.refaz_audio)
        final, formato = destino_no_original(pedido.destino)
        if pedido.onde == "copia":
            saida = saida_da_copia(pedido.destino, idioma)
            parcial = saida.with_name(saida.name + ".part")
            comando, novos_audios, novas_legendas = _comando(ffmpeg, pedido, parcial, formato, info_destino, pasta,
                                                             avisos)
            try:
                _rodar_ffmpeg(comando, info_destino.duracao, parar, ao_progresso,
                              "o ffmpeg não conseguiu juntar a faixa")
                parcial.replace(saida)
            finally:
                parcial.unlink(missing_ok=True)
            return Resultado(saida, avisos, pedido.ajuste.refaz_audio)
        copia = temporario_no_original(pedido.destino)
        comando, novos_audios, novas_legendas = _comando(ffmpeg, pedido, copia, formato, info_destino, pasta, avisos)
        manter_legendas = formato == "matroska" or pedido.destino.suffix.lower() in MESMO_MP4
        try:
            _rodar_ffmpeg(comando, info_destino.duracao, parar, ao_progresso, "o ffmpeg não conseguiu juntar a faixa")
            saida = trocar_original(ffmpeg, pedido.destino, copia, final, novos_audios,
                                    (len(info_destino.legendas) if manter_legendas else 0) + novas_legendas)
        finally:
            copia.unlink(missing_ok=True)
    return Resultado(saida, avisos, pedido.ajuste.refaz_audio)


def amostra(ffmpeg: str, pedido: Pedido, inicio: float, saida: Path, duracao: float = 30.0, parar=None,
            ao_progresso=None) -> Path:
    """'🎧 Ouvir 30 s': o trecho do destino com a faixa nova (já ajustada, com o volume) e o áudio original depois,
    para comparar no player."""
    info_destino = ler_arquivo(ffmpeg, pedido.destino)
    total = info_destino.duracao or duracao
    inicio = max(0.0, min(inicio, max(0.0, total - duracao)))
    saida.parent.mkdir(parents=True, exist_ok=True)
    parcial = saida.with_name(saida.name + ".part")
    with tempfile.TemporaryDirectory() as temporaria:
        comando, _, _ = _comando(ffmpeg, Pedido(pedido.origem, pedido.destino, pedido.audios[:1], [], pedido.ajuste,
                                                True, "dentro"),
                                 parcial, "matroska", info_destino, Path(temporaria), [],
                                 trecho=(inicio, min(duracao, total)))
        try:
            _rodar_ffmpeg(comando, min(duracao, total), parar, ao_progresso, "o ffmpeg não conseguiu montar a amostra")
            parcial.replace(saida)
        finally:
            parcial.unlink(missing_ok=True)
    return saida


# ----------------------------------------------------------------- as ondas (para comparar na tela)
def ondas(ffmpeg: str, pedido: Pedido, faixa_destino: int, inicio: float, duracao: float, ajustada: bool = True,
          pontos_por_segundo: int = 100):
    """(onda do destino, onda da faixa nova) no trecho [inicio, inicio+duracao] do destino, de 0 a 1.
    ajustada=False: a faixa nova crua (sem o ajuste: as batidas ficam desencontradas)."""
    import numpy as np
    aj = pedido.ajuste if ajustada else Ajuste()
    por_quadro = max(1, int(TAXA / pontos_por_segundo))
    destino = nivel(som(ffmpeg, pedido.destino, faixa_destino, inicio, duracao), por_quadro)
    taxa_origem = max(1000, int(round(TAXA * aj.fator)))
    inicio_origem = (inicio - aj.atraso) / (taxa_origem / TAXA)
    nova = nivel(som(ffmpeg, pedido.origem, pedido.audios[0].ordem, inicio_origem, duracao * TAXA / taxa_origem,
                     taxa_origem), por_quadro)
    if aj.ganho_db:
        nova = nova * (10 ** (aj.ganho_db / 20))
    n = min(len(destino), len(nova))
    topo = max(float(destino[:n].max(initial=0)), float(nova[:n].max(initial=0)), 1e-6)
    return np.clip(destino[:n] / topo, 0, 1), np.clip(nova[:n] / topo, 0, 1)


def batidas_comuns(destino, nova, quantas: int = 12) -> list[int]:
    """Onde a música e os efeitos batem nas duas ondas (as linhas verdes): os maiores ataques que as duas têm juntas."""
    import numpy as np
    n = min(len(destino), len(nova))
    if n < 3:
        return []
    a = np.diff(np.asarray(destino[:n]), prepend=destino[0])
    b = np.diff(np.asarray(nova[:n]), prepend=nova[0])
    juntos = np.minimum(np.clip(a, 0, None), np.clip(b, 0, None))
    escolhidos: list[int] = []
    distancia = max(3, n // (quantas * 2))
    for i in np.argsort(juntos)[::-1]:
        if juntos[i] <= 0.02 or len(escolhidos) >= quantas:
            break
        if all(abs(int(i) - j) >= distancia for j in escolhidos):
            escolhidos.append(int(i))
    return sorted(escolhidos)


# ----------------------------------------------------------------- o histórico ("📜 Trocas feitas")
def registrar_troca(arquivo: Path, pedido: Pedido, resultado: Resultado, encaixe: Encaixe | None) -> None:
    try:
        lista = json.loads(Path(arquivo).read_text(encoding="utf-8"))
        lista = lista if isinstance(lista, list) else []
    except (OSError, ValueError):
        lista = []
    lista.insert(0, {
        "feito": datetime.now().isoformat(timespec="seconds"), "origem": str(pedido.origem),
        "destino": str(pedido.destino), "saida": str(resultado.saida), "onde": pedido.onde,
        "faixas": [nome_idioma(f.idioma) for f in pedido.audios],
        "legendas": [nome_idioma(s.idioma) + (" (forçada)" if s.forcada else "") for s in pedido.legendas],
        "ajuste": pedido.ajuste.texto(), "manual": bool(encaixe and encaixe.manual), **asdict(pedido.ajuste),
        "pontos": [[p.tempo, p.sobra] for p in (encaixe.pontos if encaixe else [])], "avisos": resultado.avisos})
    Path(arquivo).parent.mkdir(parents=True, exist_ok=True)
    Path(arquivo).write_text(json.dumps(lista, ensure_ascii=False, indent=2), encoding="utf-8")


def trocas_feitas(arquivo: Path) -> list[dict]:
    try:
        lista = json.loads(Path(arquivo).read_text(encoding="utf-8"))
        return [t for t in lista if isinstance(t, dict)] if isinstance(lista, list) else []
    except (OSError, ValueError):
        return []


def apagar_trocas(arquivo: Path, trocas: list[dict]) -> int:
    """Tira do histórico (os arquivos não são tocados)."""
    tirar = {(t.get("feito"), t.get("saida")) for t in trocas}
    lista = [t for t in trocas_feitas(arquivo) if (t.get("feito"), t.get("saida")) not in tirar]
    Path(arquivo).write_text(json.dumps(lista, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(tirar)
