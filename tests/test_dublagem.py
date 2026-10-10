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

from jellyfin_tools.dublagem import (ACELERAR_MAX, ErroDublagem, MotorPiper, ParaDublar, caminho_dublado,
                                     comando_mixar, dublar_video, executavel_piper, horarios, localizar_ffmpeg,
                                     montar_trilha, preparar_piper, preparar_voz, texto_para_falar,
                                     videos_para_dublar)

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
    assert achados == [ParaDublar(a, filmes / "A (2001)" / "A (2001).pt-BR.srt", 2, 5400.0, 2_000_000)]


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
