"""Dublagem por IA: uma voz FALSA (tom de áudio) faz o papel do Piper; o ffmpeg é o de verdade."""
import io
import json
import math
import struct
import subprocess
import sys
import tarfile
import wave
from pathlib import Path

import pytest

from jellyfin_tools import dublagem
from jellyfin_tools.dublagem import (ACELERAR_MAX, ErroDublagem, MotorPiper, ParaDublar, caminho_dublado,
                                     comando_mixar, dublar_video, executavel_piper, horarios, localizar_ffmpeg,
                                     montar_trilha, preparar_piper, preparar_voz, texto_para_falar,
                                     falas_da_legenda, videos_para_dublar)

TAXA = 16000
FFMPEG = localizar_ffmpeg()
SRT = """1
00:00:01,000 --> 00:00:02,000
<i>Olá!</i>

2
00:00:02,500 --> 00:00:03,000
- Uma fala comprida demais para caber nesse pedacinho de tempo.

3
00:00:04,000 --> 00:00:05,000
♪ [música] ♪
"""


def gravar_tom(caminho: Path, segundos: float, taxa: int = TAXA) -> None:
    amostras = int(segundos * taxa)
    with wave.open(str(caminho), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(taxa)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(n / 8))) for n in range(amostras)))


class VozFalsa:
    """Faz o papel do Piper: um tom de 0,05 s por letra (fala longa = áudio longo)."""

    def __init__(self):
        self.textos = []

    def sintetizar(self, pedidos, parar=None, ao_progresso=None):
        for texto, wav in pedidos:
            self.textos.append(texto)
            gravar_tom(Path(wav), 0.05 * len(texto))
        if ao_progresso:
            ao_progresso(1.0)


def video_de_teste(caminho: Path, segundos: int = 6) -> Path:
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    f"testsrc=duration={segundos}:size=160x120:rate=10", "-f", "lavfi", "-i",
                    f"sine=duration={segundos}", "-c:v", "libx264", "-c:a", "aac", "-metadata:s:a:0", "language=eng",
                    str(caminho)], check=True, capture_output=True)
    return caminho


def faixas(arquivo: Path) -> list[str]:
    """As linhas 'Stream #0:N(lang): Audio...' que o ffmpeg mostra (sem precisar do ffprobe)."""
    r = subprocess.run([FFMPEG, "-hide_banner", "-i", str(arquivo)], capture_output=True, text=True)
    return [l.strip() for l in r.stderr.splitlines() if "Stream #" in l]


def test_texto_e_horarios():
    assert texto_para_falar("<i>Olá!</i>\n- Tudo bem?") == "Olá! Tudo bem?"
    assert texto_para_falar("♪ [música] ♪") == "" and texto_para_falar("{\\an8}(risos) Oi") == "Oi"
    assert horarios("00:01:02,500 --> 01:00:00.250") == (62.5, 3600.25)


def test_trilha_poe_cada_fala_no_horario_acelera_e_corta(tmp_path):
    curta, longa, ultima = tmp_path / "1.wav", tmp_path / "2.wav", tmp_path / "3.wav"
    gravar_tom(curta, 0.5)
    gravar_tom(longa, 3.0)                      # vaga até a próxima: 1,5 s -> acelera 1,35x e ainda corta
    gravar_tom(ultima, 0.5)
    acelerados = []

    def acelerar(wav, fator):
        acelerados.append(round(fator, 2))
        saida = wav.with_name("rapido.wav")
        gravar_tom(saida, 3.0 / fator)
        return saida
    contas = montar_trilha([(1.0, 2.0, curta), (2.5, 3.0, longa), (4.0, 5.0, ultima)], 6.0, tmp_path / "t.wav",
                           acelerar)
    assert acelerados == [ACELERAR_MAX] and contas == {"aceleradas": 1, "cortadas": 1}
    with wave.open(str(tmp_path / "t.wav"), "rb") as w:
        assert w.getframerate() == TAXA and w.getnframes() == 6 * TAXA          # do tamanho do vídeo
        amostras = struct.unpack(f"<{w.getnframes()}h", w.readframes(w.getnframes()))

    def tem_som(ini, fim):
        return any(abs(a) > 100 for a in amostras[int(ini * TAXA):int(fim * TAXA)])
    assert not tem_som(0, 0.99) and tem_som(1.0, 1.49) and not tem_som(1.51, 2.49)    # 1ª fala: 1 s a 1,5 s
    assert tem_som(2.5, 4.29)                  # a longa, acelerada, vai até 4,3 s (a próxima + 0,3 s) e é cortada
    assert tem_som(4.31, 4.79) and not tem_som(4.81, 6.0)       # a 3ª começa logo depois (4,3 s) e dura 0,5 s


@pytest.mark.skipif(not FFMPEG, reason="sem ffmpeg")
def test_dubla_o_filme_numa_versao_nova_sem_mexer_no_original(tmp_path):
    pasta = tmp_path / "Filme (2003)"
    pasta.mkdir()
    video = video_de_teste(pasta / "Filme (2003).mkv")
    (pasta / "Filme (2003).pt-BR.srt").write_text(SRT, encoding="utf-8")
    antes = video.read_bytes()
    voz, andamento = VozFalsa(), []
    r = dublar_video(video, pasta / "Filme (2003).pt-BR.srt", voz, FFMPEG, ao_progresso=andamento.append,
                     sondar=lambda v: (6.0, ["eng"]))
    assert r.status == "dublado", r.detalhe
    assert voz.textos == ["Olá!", "Uma fala comprida demais para caber nesse pedacinho de tempo."]   # ♪ fica de fora
    assert r.destino == pasta / "Filme (2003) - Dublado IA.mkv" and r.aceleradas == 0     # usou o silêncio até o fim
    assert video.read_bytes() == antes                                          # o original não é tocado
    linhas = faixas(r.destino)
    audios = [l for l in linhas if "Audio" in l]
    assert len(audios) == 2 and "(por)" in audios[0] and "(default)" in audios[0]
    assert "(eng)" in audios[1] and "(default)" not in audios[1]
    assert any("Video" in l for l in linhas) and andamento[-1] == 1.0
    assert dublar_video(video, pasta / "Filme (2003).pt-BR.srt", voz, FFMPEG).status == "ja_existe"
    assert not list(pasta.glob("*.part"))


def test_erro_do_ffmpeg_e_video_sem_audio(tmp_path):
    video = tmp_path / "X (2000).mkv"
    video.write_bytes(b"isto nao e um video")
    (tmp_path / "X (2000).pt-BR.srt").write_text(SRT, encoding="utf-8")
    sem_audio = dublar_video(video, tmp_path / "X (2000).pt-BR.srt", VozFalsa(), FFMPEG or "ffmpeg",
                             sondar=lambda v: (6.0, []))
    assert sem_audio.status == "erro" and "não tem áudio" in sem_audio.detalhe
    if FFMPEG:
        r = dublar_video(video, tmp_path / "X (2000).pt-BR.srt", VozFalsa(), FFMPEG, sondar=lambda v: (6.0, [""]))
        assert r.status == "erro" and "ffmpeg não conseguiu juntar" in r.detalhe
        assert not caminho_dublado(video).exists()


def test_comando_do_ffmpeg():
    c = comando_mixar("ffmpeg", Path("F.mp4"), Path("t.wav"), Path("s.part"), 2, legendas=False)
    assert c[c.index("-map") + 1] == "0:v?" and "[dub]" in c and "0:s?" not in c
    assert "-disposition:a:1" in c and "-disposition:a:2" in c and c[-3:] == ["-f", "matroska", "s.part"]
    assert "0:s?" in comando_mixar("ffmpeg", Path("F.mkv"), Path("t.wav"), Path("s.part"), 1, legendas=True)


def test_acha_os_filmes_para_dublar(tmp_path):
    filmes = tmp_path / "Filmes"

    def filme(nome, legenda=True, dublado=False):
        (filmes / nome).mkdir(parents=True)
        v = filmes / nome / f"{nome}.mkv"
        v.write_bytes(b"\0" * 2_000_000)
        if legenda:
            (filmes / nome / f"{nome}.pt-BR.srt").write_text(SRT, encoding="utf-8")
        if dublado:
            caminho_dublado(v).write_bytes(b"\0" * 2_000_000)
        return v
    a = filme("A (2001)")
    filme("B (2002)", legenda=False)
    filme("C (2003)", dublado=True)
    filme("Nacional (2004)")
    audio = {"Nacional (2004).mkv": ["por"]}
    achados = videos_para_dublar(filmes, sondar=lambda v: (5400.0, audio.get(v.name, ["eng"])))
    assert achados == [ParaDublar(a, filmes / "A (2001)" / "A (2001).pt-BR.srt", 2, 5400.0, 2_000_000,
                                  caminho_dublado(a))]


def test_motor_piper_conversa_com_o_programa(tmp_path):
    """Um 'piper' de mentira (script Python) confere o que o Maestro manda: --model, --json-input e uma linha
    JSON por fala com o texto e o .wav de saída."""
    if sys.platform == "win32":
        pytest.skip("o programa de mentira é um script do Linux/Mac")
    falso = tmp_path / "piper"
    falso.write_text(f"""#!{sys.executable}
import json, sys, wave
assert sys.argv[1] == "--model" and sys.argv[3] == "--json-input"
for linha in sys.stdin:
    pedido = json.loads(linha)
    with wave.open(pedido["output_file"], "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(b"\\0\\0" * len(pedido["text"]))
""", encoding="utf-8")
    falso.chmod(0o755)
    pedidos = [(f"Fala número {n}, com acentuação", tmp_path / f"{n}.wav") for n in range(120)]
    andamento = []
    MotorPiper(falso, tmp_path / "voz.onnx").sintetizar(pedidos, ao_progresso=andamento.append)
    assert all(w.is_file() for _, w in pedidos) and andamento == [50 / 120, 100 / 120, 1.0]
    with pytest.raises(ErroDublagem, match="interrompido"):
        MotorPiper(falso, tmp_path / "voz.onnx").sintetizar(pedidos, parar=lambda: True)


def test_baixa_o_piper_e_a_voz_so_na_primeira_vez(tmp_path):
    baixados = []

    def baixar(url, destino, ao_progresso=None):
        baixados.append(url)
        if url.endswith(".tar.gz"):
            conteudo = b"#!/bin/sh\n"
            with tarfile.open(destino, "w:gz") as t:
                info = tarfile.TarInfo("piper/piper")
                info.size = len(conteudo)
                t.addfile(info, io.BytesIO(conteudo))
        else:
            destino.write_text(json.dumps({"url": url}), encoding="utf-8")
    exe = preparar_piper(tmp_path / "piper", "linux", baixar)
    assert exe == executavel_piper(tmp_path / "piper", "linux") and exe.is_file()
    assert baixados == ["https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_x86_64.tar.gz"]
    modelo = preparar_voz("faber", tmp_path / "vozes", baixar)
    assert modelo.name == "pt_BR-faber-medium.onnx" and modelo.with_name(modelo.name + ".json").is_file()
    assert baixados[-1].endswith("/v1.0.0/pt/pt_BR/faber/medium/pt_BR-faber-medium.onnx")
    preparar_piper(tmp_path / "piper", "linux", baixar)
    preparar_voz("faber", tmp_path / "vozes", baixar)
    assert len(baixados) == 3                                                    # da 2ª vez, nada baixa
    with pytest.raises(ErroDublagem, match="voz desconhecida"):
        preparar_voz("ator-famoso", tmp_path / "vozes", baixar)


SRT_APERTADA = SRT.replace("♪ [música] ♪", "Tchau.")       # a fala 2 só tem 1,5 s até a 3 começar


@pytest.mark.skipif(not FFMPEG, reason="sem ffmpeg")
def test_fala_longa_e_reescrita_mais_curta_em_vez_de_acelerar(tmp_path):
    """A fala 2 (61 letras, ~3 s) tem 1,5 s: a IA reescreve até 28 letras e a voz lê a versão curta."""
    pasta = tmp_path / "Filme (2003)"
    pasta.mkdir()
    video = video_de_teste(pasta / "Filme (2003).mkv")
    (pasta / "Filme (2003).pt-BR.srt").write_text(SRT_APERTADA, encoding="utf-8")
    pedidos = []

    def adaptar(itens):
        pedidos.extend(itens)
        return {k: "Fala longa demais pro tempo." for k, *_ in itens}
    voz = VozFalsa()
    r = dublar_video(video, pasta / "Filme (2003).pt-BR.srt", voz, FFMPEG, sondar=lambda v: (6.0, ["eng"]),
                     adaptar=adaptar)
    assert r.status == "dublado" and r.adaptadas == 1, r.detalhe
    assert pedidos == [(1, "Uma fala comprida demais para caber nesse pedacinho de tempo.", 28, "Olá!")]
    assert voz.textos[-1] == "Fala longa demais pro tempo."                   # a voz leu a versão curta
    legenda = (pasta / "Filme (2003).pt-BR.srt").read_text(encoding="utf-8")
    assert "Uma fala comprida demais" in legenda                              # a legenda não muda


@pytest.mark.skipif(not FFMPEG, reason="sem ffmpeg")
def test_sem_a_ia_a_dublagem_segue_como_antes(tmp_path):
    pasta = tmp_path / "Filme (2003)"
    pasta.mkdir()
    video = video_de_teste(pasta / "Filme (2003).mkv")
    (pasta / "Filme (2003).pt-BR.srt").write_text(SRT_APERTADA, encoding="utf-8")
    avisos = []

    def adaptar(itens):
        raise RuntimeError("sem crédito")
    r = dublar_video(video, pasta / "Filme (2003).pt-BR.srt", VozFalsa(), FFMPEG, sondar=lambda v: (6.0, ["eng"]),
                     adaptar=adaptar, avisar=avisos.append)
    assert r.status == "dublado" and r.adaptadas == 0
    assert "não adaptadas (sem crédito)" in avisos[0]


def test_adaptador_pede_ao_claude_e_so_aceita_o_que_encurtou():
    import json
    from types import SimpleNamespace
    from jellyfin_tools.adaptacao import Adaptador, limite_de_letras
    from jellyfin_tools.traducao import Tradutor

    class Claude:
        def __init__(self):
            self.pedidos = []
            self.messages = self

        def create(self, **k):
            self.pedidos.append(k)
            falas = json.loads(k["messages"][0]["content"].split("Falas:\n", 1)[1])
            volta = [{"id": f["id"], "texto": f["texto"][:f["max"]] if f["id"] != 7 else f["texto"] + " mais"}
                     for f in falas]
            return SimpleNamespace(stop_reason="end_turn", usage=SimpleNamespace(input_tokens=50, output_tokens=20),
                                   content=[SimpleNamespace(type="text", text=json.dumps({"falas": volta}))])
    claude = Claude()
    tradutor = Tradutor(cliente=claude)
    adaptar = Adaptador(tradutor, "Matrix")
    assert adaptar([(3, "Eu não acredito que você fez isso", 20, "Oi"), (7, "Curta", 3, "")]) == \
        {3: "Eu não acredito que"[:20].strip()}                                # a 7 voltou MAIOR: fica a original
    pedido = claude.pedidos[0]
    assert "dublagem" in pedido["system"].lower() and "Filme: Matrix" in pedido["messages"][0]["content"]
    assert '"antes": "Oi"' in pedido["messages"][0]["content"] and tradutor.tokens_entrada == 50
    assert limite_de_letras("x" * 60, duracao=3.0, vaga=1.5) == 28 and limite_de_letras("abc", 3.0, 0.1) == 4


def test_motor_gemini_gera_cada_fala_com_voz_pronta_e_espera_o_limite(tmp_path):
    import base64
    import io
    from types import SimpleNamespace
    from jellyfin_tools import voz_gemini
    from jellyfin_tools.dublagem import ErroDublagem

    def wav_bytes(segundos):
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(24000)
            w.writeframes(b"\0\0" * int(24000 * segundos))
        return buf.getvalue()

    class Limite(Exception):
        code = 429

    class Gemini:
        def __init__(self):
            self.pedidos, self.falhar = [], 1
            self.interactions = self
            self.models = SimpleNamespace(get=lambda model: SimpleNamespace(display_name="Gemini 3.8 Flash TTS"))

        def create(self, **k):
            if self.falhar:
                self.falhar -= 1
                raise Limite("RESOURCE_EXHAUSTED")
            self.pedidos.append(k)
            texto = k["input"][0]["text"]
            dados = wav_bytes(0.1) if texto != "pcm" else b"\0\0" * 2400
            return SimpleNamespace(output_audio=SimpleNamespace(data=base64.b64encode(dados).decode(),
                                                                mime_type="audio/wav"))
    gemini, esperas = Gemini(), []
    motor = voz_gemini.MotorGemini("chave", voz="Kore", cliente=gemini, simultaneos=1, esperar=esperas.append)
    motor.sintetizar([("Olá!", tmp_path / "1.wav"), ("pcm", tmp_path / "2.wav")])
    assert esperas == [2] and motor.falas_geradas == 2                      # esperou o limite e tentou de novo
    for nome in ("1.wav", "2.wav"):
        with wave.open(str(tmp_path / nome), "rb") as w:
            assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (24000, 1, 2)
    pedido = gemini.pedidos[0]
    assert pedido["generation_config"] == {"speech_config": [{"voice": "Kore"}]}
    assert pedido["model"] == "gemini-3.8-flash-tts" and "português do Brasil" in \
        pedido["input"][0]["annotations"][0]["style"]
    assert voz_gemini.testar_chave("chave", cliente=gemini) == "Gemini 3.8 Flash TTS"
    with pytest.raises(ErroDublagem, match="desconhecida"):
        voz_gemini.MotorGemini("chave", voz="Fulano", cliente=gemini)    # só as vozes prontas da lista
    with pytest.raises(ErroDublagem, match="preencha"):
        voz_gemini.testar_chave("  ")
    recusada = SimpleNamespace(models=SimpleNamespace(get=lambda model: (_ for _ in ()).throw(
        type("ClientError", (Exception,), {"code": 400})("API key not valid"))))
    with pytest.raises(ErroDublagem, match="chave do Google AI Studio foi recusada"):
        voz_gemini.testar_chave("errada", cliente=recusada)
    minimo, maximo = voz_gemini.estimar_custo(3600)                       # 1 h de fala
    assert 0.5 < minimo < maximo < 5


SRT_LONGA = "".join(f"{k + 1}\n00:{(k * 20) // 60:02d}:{(k * 20) % 60:02d},000 --> 00:{(k * 20) // 60:02d}:"
                    f"{(k * 20) % 60:02d},800\nFala {k + 1}.\n\n" for k in range(3)) + \
    "".join(f"{k + 4}\n00:01:{10 + k * 3:02d},000 --> 00:01:{10 + k * 3:02d},800\nConversa {k + 1}.\n\n"
            for k in range(6))


def test_trecho_de_amostra_e_o_minuto_com_mais_falas(tmp_path):
    legenda = tmp_path / "f.pt-BR.srt"
    legenda.write_text(SRT_LONGA, encoding="utf-8")
    inicio, fim = dublagem.trecho_de_amostra(falas_da_legenda(legenda))
    assert (inicio, fim) == (40 - 0.5, 100 - 0.5)                   # das 0:40 (fala 3) até a última conversa


@pytest.mark.skipif(not FFMPEG, reason="sem ffmpeg")
def test_amostra_dubla_so_o_trecho_e_o_filme_aproveita_as_falas(tmp_path):
    """A amostra (fora da biblioteca) só pede as falas do trecho; o filme inteiro, depois, não pede de novo."""
    pasta = tmp_path / "Filme (2003)"
    pasta.mkdir()
    video = video_de_teste(pasta / "Filme (2003).mkv", segundos=8)
    legenda = pasta / "Filme (2003).pt-BR.srt"
    legenda.write_text(SRT, encoding="utf-8")
    cache, voz = tmp_path / "cache", VozFalsa()
    amostra = dublagem.caminho_amostra(cache, video)
    r = dublar_video(video, legenda, voz, pasta_cache=cache, trecho=(1.5, 4.5), destino=amostra)
    assert r.status == "dublado", r.detalhe
    assert voz.textos == ["Uma fala comprida demais para caber nesse pedacinho de tempo."]   # só a do trecho
    assert amostra.is_file() and not dublagem.caminho_dublado(video).exists()             # a biblioteca não muda
    assert any("Video" in l for l in faixas(amostra)) and any("por" in l for l in faixas(amostra))
    r = dublar_video(video, legenda, voz, pasta_cache=cache)                                # agora o filme inteiro
    assert r.status == "dublado" and r.retomadas == 1
    assert voz.textos[1:] == ["Olá!"]                              # a fala da amostra não foi pedida de novo


def test_comando_da_amostra_corta_e_recodifica_o_video():
    comando = dublagem.comando_mixar("ffmpeg", Path("f.mkv"), Path("t.wav"), Path("s.mkv"), 1, True, (10.0, 70.0))
    assert comando[comando.index("-ss") + 1] == "10.000" and comando[comando.index("-t") + 1] == "60.000"
    assert comando.index("-ss") < comando.index("-i") and "libx264" in comando and "0:s?" not in comando
    normal = dublagem.comando_mixar("ffmpeg", Path("f.mkv"), Path("t.wav"), Path("s.mkv"), 1, True)
    assert "-ss" not in normal and "libx264" not in normal and "0:s?" in normal


def _separar_falso(chamadas):
    """Faz o papel do separador de vozes: grava um 'fundo' (um tom) do tamanho pedido."""
    def separar(video, destino, trecho, duracao, parar, ao_progresso):
        segundos = (trecho[1] - trecho[0]) if trecho else duracao
        chamadas.append((Path(video).name, Path(destino).name, trecho))
        subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                        f"sine=f=440:duration={segundos}", "-ac", "2", "-ar", "44100", str(destino)], check=True)
        ao_progresso(1.0)
        return Path(destino)
    return separar


@pytest.mark.skipif(not FFMPEG, reason="sem ffmpeg")
@pytest.mark.parametrize("nome", ["Filme (2003).mkv", "Filme (2003).mp4"])
def test_dublagem_como_faixa_do_proprio_arquivo_com_a_legenda(tmp_path, nome):
    """no_original: a faixa 'Português (dublagem IA)' e a legenda entram no PRÓPRIO arquivo (o .mkv continua .mkv e o
    .mp4 continua .mp4); a cópia é conferida antes de trocar; o .srt sai (está dentro do vídeo); com o separador, a
    dublagem usa o fundo sem as vozes."""
    video = video_de_teste(tmp_path / nome)
    legenda = tmp_path / "Filme (2003).pt-BR.srt"
    legenda.write_text(SRT, encoding="utf-8")
    chamadas, andamento = [], []
    r = dublar_video(video, legenda, VozFalsa(), FFMPEG, sondar=lambda v: (6.0, ["eng"]), no_original=True,
                     legenda_no_video=True, separar=_separar_falso(chamadas), ao_progresso=andamento.append)
    assert r.status == "dublado", r.detalhe
    assert r.destino == video and video.is_file() and not legenda.exists()
    assert not caminho_dublado(video).exists() and not dublagem.temporario_no_original(video).exists()
    assert chamadas == [(nome, "fundo.flac", None)]
    linhas = faixas(video)
    audios = [l for l in linhas if "Audio" in l]
    legendas = [l for l in linhas if "Subtitle" in l]
    assert len(audios) == 2 and "(por)" in audios[0] and "(default)" in audios[0] and "(eng)" in audios[1]
    assert len(legendas) == 1 and "(por)" in legendas[0]
    assert andamento[-1] == 1.0 and sorted(andamento) == andamento                # a barra só anda para frente
    # de novo: já tem áudio em português
    legenda.write_text(SRT, encoding="utf-8")
    assert dublar_video(video, legenda, VozFalsa(), FFMPEG, sondar=lambda v: (6.0, ["por", "eng"]),
                        no_original=True).status == "ja_existe"


@pytest.mark.skipif(not FFMPEG, reason="sem ffmpeg")
def test_avi_vira_mkv_e_copia_ruim_nao_troca_o_original(tmp_path):
    video = tmp_path / "Velho (1999).avi"
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc=duration=6:size=160x120:rate=10", "-f", "lavfi", "-i", "sine=duration=6",
                    "-c:v", "mpeg4", "-c:a", "mp3", str(video)], check=True)
    legenda = tmp_path / "Velho (1999).pt-BR.srt"
    legenda.write_text(SRT, encoding="utf-8")
    antes = video.read_bytes()
    # a conferência acha um problema (a cópia "perdeu" o vídeo): nada é trocado
    original = dublagem.inspecionar

    def inspecionar_ruim(ffmpeg, arquivo):
        f = original(ffmpeg, arquivo)
        return f if Path(arquivo) == video else dublagem.Faixas(f.duracao, 0, f.audio, f.legenda)
    dublagem.inspecionar = inspecionar_ruim
    try:
        r = dublar_video(video, legenda, VozFalsa(), FFMPEG, sondar=lambda v: (6.0, [""]), no_original=True)
    finally:
        dublagem.inspecionar = original
    assert r.status == "erro" and "o original não foi alterado" in r.detalhe and "vídeo: 1 -> 0" in r.detalhe
    assert video.read_bytes() == antes and not dublagem.temporario_no_original(video).exists()
    assert not video.with_suffix(".mkv").exists() and legenda.exists()
    # agora sim: vira .mkv com as duas faixas e o .avi sai
    r = dublar_video(video, legenda, VozFalsa(), FFMPEG, sondar=lambda v: (6.0, [""]), no_original=True)
    assert r.status == "dublado", r.detalhe
    assert r.destino == video.with_suffix(".mkv") and not video.exists() and legenda.exists()
    assert len([l for l in faixas(r.destino) if "Audio" in l]) == 2


@pytest.mark.skipif(not FFMPEG, reason="sem ffmpeg")
def test_so_a_legenda_dentro_do_video(tmp_path):
    video = video_de_teste(tmp_path / "Aula.mp4")
    legenda = tmp_path / "Aula.pt-BR.srt"
    legenda.write_text(SRT, encoding="utf-8")
    final = dublagem.embutir_legenda(FFMPEG, video, legenda)
    assert final == video and not legenda.exists()
    linhas = faixas(video)
    assert [l for l in linhas if "Subtitle" in l] and "(por)" in [l for l in linhas if "Subtitle" in l][0]
    assert len([l for l in linhas if "Audio" in l]) == 1                           # o áudio continua o mesmo
    f = dublagem.inspecionar(FFMPEG, video)
    assert f.video == 1 and f.audio == 1 and f.legenda == 1 and abs(f.duracao - 6) < 0.5


def test_amostra_separa_so_o_trecho_e_comando_com_fundo(tmp_path):
    c = comando_mixar("ffmpeg", Path("F.mkv"), Path("t.wav"), Path("s.part"), 1, True, fundo=Path("fundo.flac"),
                      legenda_nova=Path("F.pt-BR.srt"))
    assert c[c.index("-filter_complex") + 1] == dublagem.FILTRO_SEM_VOZES and "fundo.flac" in c
    assert c[c.index("F.pt-BR.srt") - 1] == "-i" and "3:0" in c and "language=por" in c
    mp4 = comando_mixar("ffmpeg", Path("F.mp4"), Path("t.wav"), Path("s.part"), 1, True, legenda_nova=Path("l.srt"),
                        formato="mp4")
    assert mp4[-3:] == ["-f", "mp4", "s.part"] and "mov_text" in mp4 and "0:t?" not in mp4 and "2:0" in mp4
    amostra = comando_mixar("ffmpeg", Path("F.mkv"), Path("t.wav"), Path("s.part"), 1, True, (10.0, 70.0),
                            Path("fundo-10-70.flac"), Path("l.srt"))
    assert "fundo-10-70.flac" in amostra and amostra[amostra.index("l.srt") - 1] == "-i"   # a amostra leva a legenda
    assert amostra[amostra.index("-disposition:s:0") + 1] == "default" and "0:s?" not in amostra
    assert dublagem.destino_no_original(Path("a.MKV"))[1] == "matroska"
    assert dublagem.destino_no_original(Path("a.m4v")) == (Path("a.m4v"), "mp4")
    assert dublagem.destino_no_original(Path("a.ts")) == (Path("a.mkv"), "matroska")


def test_no_original_ja_dublado_e_o_audio_em_portugues(tmp_path):
    filmes = tmp_path / "Filmes"
    (filmes / "A (2000)").mkdir(parents=True)
    for nome in ("A (2000).mkv", "A (2000).pt-BR.srt"):
        (filmes / "A (2000)" / nome).write_text("1\n00:00:01,000 --> 00:00:02,000\nOi.\n" if "srt" in nome else "x")
    (filmes / "A (2000)" / "A (2000) - Dublado IA.mkv").write_text("x")       # de uma versão antiga
    assert videos_para_dublar(filmes, sondar=lambda v: (60.0, ["eng"])) == []   # arquivo separado: já existe
    itens = videos_para_dublar(filmes, sondar=lambda v: (60.0, ["eng"]), no_original=True)
    assert [i.video.name for i in itens] == ["A (2000).mkv"] and itens[0].destino is None
    assert videos_para_dublar(filmes, sondar=lambda v: (60.0, ["por", "eng"]), no_original=True) == []
    series = tmp_path / "Séries"
    (series / "Show" / "Season 01").mkdir(parents=True)
    (series / "Show" / "Season 01" / "Show S01E01.mkv").write_text("x")
    (series / "Show" / "Season 01" / "Show S01E01.pt-BR.srt").write_text("1\n00:00:01,000 --> 00:00:02,000\nOi.\n")
    ep = dublagem.episodios_para_dublar(series, sondar=lambda v: (60.0, ["eng"]), no_original=True)
    assert ep[0].destino is None and ep[0].serie == "Show"                       # sem a pasta irmã


@pytest.mark.skipif(not FFMPEG, reason="sem ffmpeg")
def test_ambientacao_da_voz_com_o_perfil_das_vozes_originais(tmp_path):
    """Com a separação, a voz dublada recebe o volume, o tom e o eco medidos nas vozes originais (fundo.voz.json)."""
    pytest.importorskip("numpy")
    from jellyfin_tools import separar_vozes
    video = video_de_teste(tmp_path / "Filme (2003).mkv")
    legenda = tmp_path / "Filme (2003).pt-BR.srt"
    legenda.write_text(SRT, encoding="utf-8")
    chamadas, avisos = [], []
    separar = _separar_falso(chamadas)

    def separar_com_perfil(video, destino, trecho, duracao, parar, ao_progresso):
        fundo = separar(video, destino, trecho, duracao, parar, ao_progresso)
        separar_vozes.caminho_perfil(fundo).write_text(json.dumps(
            {"nivel": -14.0, "bandas": [0, 2, 3, 2, -4, -9, -14], "eco": 0.6, "quadros_com_fala": 100}))
        return fundo
    r = dublar_video(video, legenda, VozFalsa(), FFMPEG, sondar=lambda v: (6.0, ["eng"]), separar=separar_com_perfil,
                     ambientar=True, avisar=avisos.append, pasta_cache=tmp_path / "cache")
    assert r.status == "dublado", r.detalhe
    assert r.ambiente and r.ambiente["eco"] == 0.6 and -12 <= r.ambiente["ganho_db"] <= 12
    assert any("ambientação da voz" in a for a in avisos)
    assert len([l for l in faixas(r.destino) if "Audio" in l]) == 2
    # sem o perfil (ex.: separação antiga), segue sem ambientação
    r2 = dublar_video(video, legenda, VozFalsa(), FFMPEG, sondar=lambda v: (6.0, ["eng"]), separar=separar,
                      ambientar=True, destino=tmp_path / "outra.mkv")
    assert r2.status == "dublado" and r2.ambiente is None


def test_conta_da_ambientacao():
    pytest.importorskip("numpy")
    from jellyfin_tools import separar_vozes as sv
    voz = {"nivel": -20.0, "bandas": [10, 8, 6, 0, -6, -10, -12], "eco": 0.4}
    dublada = {"nivel": -10.0, "bandas": [10, 8, 6, 0, -6, -10, -12], "eco": 0.0}
    a = sv.ambiente(voz, dublada)
    assert a == {"ganho_db": -9.0, "eq": [], "eco": 0.4}                     # mesmo tom: só o volume (+1 dB de folga)
    aguda = dict(dublada, bandas=[0, 0, 0, 0, 0, 0, 0])
    a = sv.ambiente(voz, aguda)
    assert dict(a["eq"])[250] > 0 and dict(a["eq"])[8000] < 0               # puxa para o tom das vozes originais
    assert 125 not in dict(a["eq"])                                          # o grave depende da pessoa: fica
    assert all(abs(g) <= sv.EQ_MAXIMO for _, g in a["eq"])
    assert sv.ambiente(None, dublada) is None
    assert sv.filtro_da_voz(None) == "volume=1.5" and "equalizer=f=250" in sv.filtro_da_voz(a)
    assert sv.usa_sala(a) and not sv.usa_sala({"eco": 0.01})


def test_medidor_de_eco_e_perfil(tmp_path):
    """O eco: voz "seca" (cai rápido) x a mesma voz numa sala (cai devagar)."""
    np = pytest.importorskip("numpy")
    from jellyfin_tools import separar_vozes as sv
    taxa = 24000
    gerador = np.random.default_rng(1)
    seca = np.zeros(taxa * 8, dtype=np.float32)
    for k in range(10):                                             # 10 "falas" de 0,4 s com silêncio entre elas
        ini = int((0.3 + 0.75 * k) * taxa)
        seca[ini:ini + int(0.4 * taxa)] = gerador.standard_normal(int(0.4 * taxa)) * 0.3
    t = np.arange(int(taxa * 1.0)) / taxa
    sala = gerador.standard_normal(len(t)) * np.exp(-6.9 * t / 1.0)
    molhada = np.convolve(seca, sala)[:len(seca)].astype(np.float32)
    molhada *= np.abs(seca).max() / np.abs(molhada).max()
    p_seca, p_molhada = sv.perfil_de_sinal(seca, taxa), sv.perfil_de_sinal(molhada, taxa)
    assert p_seca["eco"] < 0.15 < p_molhada["eco"]
    assert -16 < p_seca["nivel"] < -9                           # 0,3 de ruído = -10,5 dB nas partes com fala
    assert len(p_seca["bandas"]) == len(sv.BANDAS)
    sv.gerar_sala(tmp_path / "sala.wav", 0.5)
    with wave.open(str(tmp_path / "sala.wav")) as w:
        assert w.getnchannels() == 2 and 0.5 < w.getnframes() / w.getframerate() <= 1.2


@pytest.mark.parametrize("custo_gpu, esperado", [(0.2, "placa de vídeo"), (3.0, "processador")])
def test_corrida_placa_de_video_x_processador(monkeypatch, custo_gpu, esperado):
    """Com o DirectML, um bloco de teste em cada um: fica o mais rápido (sem placa de vídeo de verdade, o DirectML
    usa um driver de software do Windows, mais lento que o processador)."""
    pytest.importorskip("numpy")
    import sys
    import types
    from jellyfin_tools import separar_vozes as sv
    relogio = [0.0]

    class Sessao:
        def __init__(self, modelo, opcoes=None, providers=()):
            self.provedores = [p[0] if isinstance(p, tuple) else p for p in providers]
            placa = next((p[1]["device_id"] for p in providers if isinstance(p, tuple)), None)
            if placa == 1:
                raise UnicodeDecodeError("utf-8", b"\xe2", 0, 1, "invalid continuation byte")   # 2ª placa: recusada
            self.custo = custo_gpu if "DmlExecutionProvider" in self.provedores else 1.0

        def get_providers(self):
            return self.provedores

        def get_inputs(self):
            return [types.SimpleNamespace(name="input")]

        def run(self, saidas, entradas):
            relogio[0] += self.custo
            return [entradas["input"]]
    falso = types.SimpleNamespace(
        InferenceSession=Sessao, SessionOptions=lambda: types.SimpleNamespace(),
        ExecutionMode=types.SimpleNamespace(ORT_SEQUENTIAL=1),
        get_available_providers=lambda: ["DmlExecutionProvider", "CPUExecutionProvider"])
    monkeypatch.setitem(sys.modules, "onnxruntime", falso)
    sessao, dispositivo = sv.criar_sessao("m.onnx", cronometro=lambda: relogio[0])
    assert dispositivo.startswith(esperado) and "por bloco" in dispositivo
    assert ("DmlExecutionProvider" in sessao.get_providers()) == (esperado == "placa de vídeo")
    sessao, dispositivo = sv.criar_sessao("m.onnx", usar_gpu=False)                 # desmarcado: processador
    assert dispositivo == "processador"
    assert "Windows recusou" in sv.motivo_da_falha(UnicodeDecodeError("utf-8", b"\xe2", 0, 1, "x"))



def test_placa_de_video_recusada_explica_em_portugues(monkeypatch):
    """GeForce 920M: o Windows recusa e a mensagem (em português) chegava como "'utf-8' codec can't decode"."""
    pytest.importorskip("numpy")
    import sys
    import types
    from jellyfin_tools import separar_vozes as sv

    class Sessao:
        def __init__(self, modelo, opcoes=None, providers=()):
            if any(isinstance(p, tuple) for p in providers):
                raise UnicodeDecodeError("utf-8", b"\xe2", 0, 1, "invalid continuation byte")
            self.provedores = list(providers)

        def get_providers(self):
            return self.provedores

        def get_inputs(self):
            return [types.SimpleNamespace(name="input")]
    falso = types.SimpleNamespace(
        InferenceSession=Sessao, SessionOptions=lambda: types.SimpleNamespace(),
        ExecutionMode=types.SimpleNamespace(ORT_SEQUENTIAL=1),
        get_available_providers=lambda: ["DmlExecutionProvider", "CPUExecutionProvider"])
    monkeypatch.setitem(sys.modules, "onnxruntime", falso)
    avisos = []
    sessao, dispositivo = sv.criar_sessao("m.onnx", avisar=avisos.append)
    assert sessao.get_providers() == ["CPUExecutionProvider"]
    assert "Windows recusou" in dispositivo and "codec" not in dispositivo and len(avisos) == 1


@pytest.mark.skipif(not FFMPEG, reason="sem ffmpeg")
def test_legenda_que_some_no_meio_e_trava_entre_dois_maestros(tmp_path):
    """Visto na prática: outro processo apagou o .srt no meio da dublagem e o ffmpeg falhou ("Error opening input
    file ...pt-BR.srt"). Agora a legenda que entra no vídeo é uma CÓPIA de trabalho, e uma trava ao lado do vídeo
    impede dois Maestros (a janela e o robô) de dublarem o mesmo vídeo ao mesmo tempo."""
    import os
    import time
    video = video_de_teste(tmp_path / "Aquarela Do Brasil.mp4")
    legenda = tmp_path / "Aquarela Do Brasil.pt-BR.srt"
    legenda.write_text(SRT, encoding="utf-8")
    trava = dublagem.caminho_trava(video)
    trava.write_text("123")                                   # outro Maestro dublando agora
    r = dublar_video(video, legenda, VozFalsa(), FFMPEG, sondar=lambda v: (6.0, ["eng"]), no_original=True)
    assert r.status == "erro" and "outro Maestro" in r.detalhe and trava.exists()
    antigo = time.time() - dublagem.TRAVA_VALIDADE - 60       # trava velha (um Maestro que fechou no meio)
    os.utime(trava, (antigo, antigo))
    chamadas = []
    separar = _separar_falso(chamadas)

    def separar_e_apagar(*args):                              # "o outro processo" apaga o .srt no meio
        legenda.unlink()
        return separar(*args)
    r = dublar_video(video, legenda, VozFalsa(), FFMPEG, sondar=lambda v: (6.0, ["eng"]), no_original=True,
                     legenda_no_video=True, separar=separar_e_apagar, pasta_cache=tmp_path / "cache")
    assert r.status == "dublado", r.detalhe
    assert [l for l in faixas(video) if "Subtitle" in l]      # a legenda entrou mesmo assim (da cópia)
    assert not trava.exists()


def test_relogio_mostra_a_etapa_e_quanto_falta():
    agora = [0.0]
    relogio = dublagem.RelogioDaDublagem(separar=True, agora=lambda: agora[0])
    assert relogio.texto(0.2) == "lendo as falas 50%"
    agora[0] = 100
    assert relogio.texto(0.5) == "tirando as vozes originais 0%"          # começou a etapa longa
    agora[0] = 100 + 600                                                  # 10 min depois: 10% da etapa
    assert relogio.texto(0.53) == "tirando as vozes originais 10%, faltam ~1h30"
    assert dublagem.etapa_da_dublagem(0.9, True) == "juntando ao vídeo"
    assert dublagem.etapa_da_dublagem(0.6, False) == "montando a trilha"
