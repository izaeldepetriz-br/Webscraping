"""As vozes do jogo dubladas no PC (modo "Traduzir e dublar" da aba 🎮 Jogos): o texto de cada fala pelo roteiro
(ou pelo Whisper, quando o jogo não tem as falas escritas), o gênero e o grito pelo som da original, uma voz por
personagem, a fala gerada no formato e na duração da original (os mesmos nomes de arquivo), o retomar de onde
parou e a entrega. O motor de vozes, o Whisper e o Claude são falsos."""
import csv
import wave
from types import SimpleNamespace

import numpy as np
import pytest

from jellyfin_tools import audio_jogo as aj
from jellyfin_tools import dublar_jogo as dj
from jellyfin_tools import genero_local
from jellyfin_tools import roteiro_jogo as rj
from tests.test_audio_jogo import vag, wav
from tests.test_roteiro_jogo import ClienteJogo
from tests.test_voz_clonada import FFMPEG

pytestmark = pytest.mark.skipif(not FFMPEG, reason="sem ffmpeg")


def voz(segundos: float, f0: float, taxa: int = 22050, volume: float = 6000) -> np.ndarray:
    """Uma "voz" de mentira: o tom (f0) com harmônicos, em sílabas."""
    t = np.arange(int(taxa * segundos)) / taxa
    som = sum(np.sin(2 * np.pi * f0 * h * t) / h for h in range(1, 8))
    silabas = 0.55 + 0.45 * np.sign(np.sin(2 * np.pi * 3 * t))
    return (volume / 2 * som * silabas).astype(np.int16)


def jogo(tmp_path):
    pasta = tmp_path / "Meu Jogo - extraído"
    (pasta / "SOUND").mkdir(parents=True)
    (pasta / "DJ").mkdir()
    vag(pasta / "SOUND/KAEL_001.vag", voz(1.0, 120), nome=b"KAEL_001")
    vag(pasta / "SOUND/KAEL_002.vag", voz(1.4, 115), nome=b"KAEL_002")
    vag(pasta / "SOUND/GUARD_01.vag", voz(0.9, 110), nome=b"GUARD_01")
    vag(pasta / "SOUND/MAYA_01.vag", voz(1.0, 230), nome=b"MAYA_01")
    for i in range(6):                                                    # o locutor: sem texto no roteiro
        wav(pasta / f"DJ/STRYKER_{i:02d}.wav", voz(0.8, 125 + i), taxa=22050)
    wav(pasta / "DJ/STRYKER_GRITO.wav", voz(0.8, 210, volume=30000), taxa=22050)   # bem mais alto: gritando
    (pasta / "SOUND/QUEBRADO.vag").write_bytes(b"nada")
    roteiro = pasta / "roteiro.csv"
    roteiro.write_text("id;texto;audio;personagem\n1;Open the gate!;KAEL_001.vag;Kael\n"
                       "2;Thanks, {NAME}. The forest is safe now.;SOUND/KAEL_002.vag;Kael\n"
                       "3;Open the gate!;GUARD_01.vag;Guarda\nMAYA_01;Save your game?;;Maya\n4;New game;;\n",
                       encoding="utf-8")
    return pasta, rj.ler_roteiro(roteiro)


class MotorFalso:
    """O XTTS-v2 de mentira: um tom do tamanho do texto, mais grave ou agudo conforme a voz."""

    def __init__(self):
        self.pedidos = []

    def sintetizar(self, pedidos, parar=None, ao_progresso=None):
        for k, (texto, destino, voz_, nota) in enumerate(pedidos):
            self.pedidos.append((texto, voz_, nota))
            with wave.open(str(destino), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(24000)
                w.writeframes(voz(0.06 * len(texto), 100 + 7 * len(voz_), 24000).tobytes())
            if ao_progresso:
                ao_progresso((k + 1) / len(pedidos))


class WhisperFalso:
    def __init__(self):
        self.ouvidos = []
        self.motor = self

    def _carregar(self):
        pass

    def transcribe(self, arquivo, **k):
        self.ouvidos.append(arquivo)
        return [SimpleNamespace(text=" Crash FM, baby! ")], None


def test_acha_as_falas_e_o_texto_de_cada_uma(tmp_path):
    pasta, roteiro = jogo(tmp_path)
    falas = dj.achar_falas(pasta, roteiro)
    por_nome = {f.relativo: f for f in falas}
    assert len(falas) == 12 and por_nome["SOUND/QUEBRADO.vag"].erro               # o que não lê fica marcado
    assert (por_nome["SOUND/KAEL_001.vag"].texto, por_nome["SOUND/KAEL_001.vag"].personagem) == \
        ("Open the gate!", "Kael")
    assert por_nome["SOUND/KAEL_002.vag"].entrada.chave == "2"                    # pelo caminho do arquivo
    assert por_nome["SOUND/MAYA_01.vag"].personagem == "Maya"                    # pelo id igual ao nome
    assert not por_nome["DJ/STRYKER_00.wav"].texto
    conta = dj.medir(falas)
    assert por_nome["SOUND/MAYA_01.vag"].genero == "f" and por_nome["SOUND/KAEL_001.vag"].genero == "m"
    assert por_nome["DJ/STRYKER_GRITO.wav"].tom == genero_local.TOM_GRITO and conta[genero_local.TOM_GRITO] == 1
    whisper = WhisperFalso()
    assert dj.ouvir(falas, whisper, tmp_path / "trabalho") == 7
    assert por_nome["DJ/STRYKER_03.wav"].texto == "Crash FM, baby!" and por_nome["DJ/STRYKER_03.wav"].ouvida
    falas2 = dj.achar_falas(pasta, roteiro)
    assert dj.ouvir(falas2, whisper, tmp_path / "trabalho") == 0 and len(whisper.ouvidos) == 7   # guardado


def test_dubla_no_formato_retoma_e_entrega(tmp_path):
    pasta, roteiro = jogo(tmp_path)
    falas = dj.achar_falas(pasta, roteiro)
    dj.medir(falas)
    dj.ouvir(falas, WhisperFalso(), tmp_path / "saida" / dj.PASTA_TRABALHO)
    memoria = {}
    tradutor = rj.TradutorJogo(cliente=ClienteJogo())
    rj.traduzir_roteiro(roteiro, tradutor, memoria=memoria)
    dj.ligar_traducoes(falas)
    dj.traduzir_ouvidas(falas, tradutor, memoria=memoria)
    mapa = dj.elenco(falas, "Damien Black", vozes_genero={"m": "Damien Black", "f": "Ana Florence"})
    assert mapa["Kael"] == "Damien Black" and mapa["Maya"] != mapa["Guarda"] != "Damien Black"
    por_nome = {f.relativo: f for f in falas}
    assert por_nome["DJ/STRYKER_00.wav"].voz == "Damien Black"                    # "Outros": pelo tom (homem)
    tabela = dj.tabela_do_elenco(falas)
    assert tabela[0][:2] == ("Kael", 2) and tabela[-1][0] == dj.OUTROS and tabela[0][4] == "—"
    assert tabela[-1][3] == "1 gritando → XTTS-v2 (neutra)"
    assert dj.tabela_do_elenco(falas, chatterbox=True)[-1][3] == "1 gritando → Chatterbox"
    motor = MotorFalso()
    saida = tmp_path / "saida"
    andamento = []
    r = dj.dublar(falas, motor, saida, FFMPEG, ao_progresso=andamento.append)
    assert r.dubladas == 11 and not r.erros and andamento and andamento[-1] == pytest.approx(1.0)
    assert ("Abra o portão!", "Damien Black", "") in motor.pedidos
    assert any(nota.startswith("Nesta fala: gritando") for _, _, nota in motor.pedidos)
    for fala in falas:
        if fala.formato is None:
            continue
        nova = saida / "audio_ptbr" / fala.relativo                              # o mesmo nome e o mesmo caminho
        assert nova.is_file()
        formato = aj.ler_formato(nova)
        assert (formato.tipo, formato.taxa, formato.amostras) == (fala.formato.tipo, fala.formato.taxa,
                                                                  fala.formato.amostras)
        if formato.tipo == "vag":
            assert nova.stat().st_size == fala.arquivo.stat().st_size           # o mesmo tamanho em bytes
    # de novo: nada é gerado (retoma de onde parou); mudou a tradução de uma: só ela
    antes = len(motor.pedidos)
    assert dj.dublar(falas, motor, saida, FFMPEG).puladas == 11 and len(motor.pedidos) == antes
    por_nome["SOUND/KAEL_001.vag"].traducao = "Abram o portão!"
    r = dj.dublar(falas, motor, saida, FFMPEG)
    assert (r.dubladas, r.puladas) == (1, 10) and motor.pedidos[-1][0] == "Abram o portão!"
    # ouvir 5: a original e a dublada, uma depois da outra
    amostra = dj.amostra(falas, saida, tmp_path / "ouvir.wav")
    with wave.open(str(amostra)) as w:
        assert w.getnframes() > 24000 * 5
    # entregar: o roteiro com as mesmas colunas, as falas ouvidas pelo Whisper e o relatório
    feitos = dj.entregar(roteiro, falas, saida)
    nomes = [f.name for f in feitos]
    assert nomes == ["roteiro_ptbr.csv", "falas_ouvidas.csv", "relatorio_traducao.txt"]
    assert (saida / "roteiro_ptbr.csv").read_text(encoding="utf-8").splitlines()[1] == \
        "1;Abra o portão!;KAEL_001.vag;Kael"
    with open(saida / "falas_ouvidas.csv", encoding="utf-8-sig") as f:
        linhas = list(csv.reader(f, delimiter=";"))
    assert linhas[1][:3] == ["DJ/STRYKER_00.wav", "Crash FM, baby!", "PT: Crash FM, baby!"]
    relatorio = (saida / "relatorio_traducao.txt").read_text(encoding="utf-8")
    assert "11 dubladas" in relatorio and "audio_ptbr" in relatorio


def test_wav_natural_e_voz_fixa_para_os_outros(tmp_path):
    pasta, roteiro = jogo(tmp_path)
    falas = [f for f in dj.achar_falas(pasta, roteiro) if f.relativo.startswith("SOUND/KAEL")]
    for f in falas:
        f.traducao = "Uma fala bem comprida que não cabe no tempo da original de jeito nenhum mesmo"
    dj.elenco(falas, "Damien Black", fixas={"Kael": "Ana Florence · grave"})
    assert {f.voz for f in falas} == {"Ana Florence · grave"}
    r = dj.dublar(falas, MotorFalso(), tmp_path / "saida", FFMPEG, formato=False, duracao=False)
    assert r.dubladas == 2
    natural = tmp_path / "saida" / "audio_ptbr" / "SOUND" / "KAEL_001.wav"
    assert natural.is_file() and aj.ler_formato(natural).segundos > 3              # do tamanho natural
    r = dj.dublar(falas, MotorFalso(), tmp_path / "saida2", FFMPEG)
    assert r.cortadas == 2 and r.aceleradas == 2                                 # exato: acelera e corta
    assert dj.tabela_do_elenco(falas)[0][4] == "⚠ 2 cortada(s) no fim · 2 acelerada(s) 35%"
    r = dj.dublar(falas, MotorFalso(), tmp_path / "saida3", FFMPEG, duracao=False)   # o formato, sem cortar
    nova = tmp_path / "saida3" / "audio_ptbr" / "SOUND" / "KAEL_001.vag"
    assert r.cortadas == 0 and aj.ler_formato(nova).segundos > 3 and aj.ler_formato(nova).taxa == 22050
    r = dj.dublar(falas, MotorFalso(), tmp_path / "saida4", FFMPEG, formato=False)   # WAV com o tempo da original
    wav_ = tmp_path / "saida4" / "audio_ptbr" / "SOUND" / "KAEL_001.wav"
    assert abs(aj.ler_formato(wav_).segundos - falas[0].formato.segundos) < 0.01
    assert dj.estimar_tempo(1204) == "≈ 1 h com a placa NVIDIA (≈ 9 h no processador)"
    assert dj.estimar_tempo(10) == "≈ 1 min com a placa NVIDIA (≈ 4 min no processador)"


def test_vozes_comprimidas_de_pc_e_psp(tmp_path):
    """Jogos de PC e de outros consoles: a voz em OGG (ou MP3, FLAC, Opus) volta no mesmo formato, com a taxa, os
    canais e a duração da original; a que o Maestro só lê (AT3/AT9 do PSP, WMA) volta em WAV para a ferramenta do jogo
    converter; um .at3 que é um WAV comum continua WAV."""
    import subprocess
    ffmpeg = FFMPEG
    if not ffmpeg:
        pytest.skip("sem ffmpeg")

    def gerar(destino, segundos, canais=2, taxa=44100, extra=()):
        subprocess.run([ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=frequency=330:duration={segundos}",
                        "-ac", str(canais), "-ar", str(taxa), *extra, str(destino)], check=True)
        return destino
    original = gerar(tmp_path / "voz_001.ogg", 1.5, extra=("-c:a", "libvorbis"))
    formato = aj.ler_formato(original)
    assert (formato.tipo, formato.taxa, formato.canais, formato.extra["so_ler"]) == ("ogg", 44100, 2, False)
    assert abs(formato.segundos - 1.5) < 0.05
    dublada = gerar(tmp_path / "dublada.wav", 2.0, canais=1, taxa=24000)
    feito = aj.gravar_como(original, dublada, tmp_path / "saida" / "voz_001.ogg", ffmpeg)
    nova = aj.ler_formato(tmp_path / "saida" / "voz_001.ogg")
    assert (nova.tipo, nova.taxa, nova.canais) == ("ogg", 44100, 2) and abs(nova.amostras - formato.amostras) < 2048
    assert feito["acelerada"] > 1.0 and len(aj.ler_som(tmp_path / "saida" / "voz_001.ogg")[0]) > 0
    so_ler = gerar(tmp_path / "voz_002.wma", 1.0, extra=("-c:a", "wmav2"))
    formato = aj.ler_formato(so_ler)
    assert formato.tipo == "wma" and formato.extra["so_ler"]
    feito = aj.gravar_como(so_ler, dublada, tmp_path / "saida" / "voz_002.wma", ffmpeg)
    assert feito["em_wav"] and (tmp_path / "saida" / "voz_002.wav").is_file()
    assert dj.destino_da_fala(dj.FalaJogo(so_ler, "voz_002.wma", formato), tmp_path).suffix == ".wav"
    comum = gerar(tmp_path / "voz_003.at3", 0.5, canais=1, extra=("-f", "wav", "-c:a", "pcm_s16le"))
    assert aj.ler_formato(comum).tipo == "wav"
