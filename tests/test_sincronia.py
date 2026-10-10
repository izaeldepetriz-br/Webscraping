"""Sincronizar legenda: a 'régua' do áudio é falsa (nenhum áudio é ouvido); a conta (correlação) é a de verdade."""
import random
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

from jellyfin_tools.sincronia import (deslocar, legendas_para_sincronizar, melhor_atraso, regua_da_legenda,  # noqa: E402
                                      sincronizar)
from jellyfin_tools.traducao import Fala, gerar_srt, ler_srt  # noqa: E402
from jellyfin_tools.transcricao import tempo_srt  # noqa: E402


def falas_aleatorias(n=60, semente=1):
    sorteio, t, falas = random.Random(semente), 2.0, []
    for k in range(n):
        dur = sorteio.uniform(0.8, 4.0)
        falas.append(Fala(f"{tempo_srt(t)} --> {tempo_srt(t + dur)}", f"fala {k}"))
        t += dur + sorteio.uniform(0.3, 5.0)
    return falas, t + 5


def test_acha_o_atraso_e_corrige(tmp_path):
    falas, total = falas_aleatorias()
    audio = regua_da_legenda(falas, int(total / 0.01))                # a voz está onde as falas "certas" estão
    atrasada = deslocar(falas, 2.5)                                    # a legenda veio 2,5 s atrasada
    legenda = tmp_path / "Filme.pt-BR.srt"
    legenda.write_text(gerar_srt(atrasada), encoding="utf-8")
    r = sincronizar(legenda, tmp_path / "Filme.mkv", ouvir=lambda v: audio)
    assert r.status == "ajustada" and r.atraso == pytest.approx(-2.5, abs=0.02) and r.ganho > 1.15
    assert [f.tempo for f in ler_srt(legenda.read_text(encoding="utf-8"))] == [f.tempo for f in falas]
    assert ler_srt((tmp_path / "Filme.pt-BR.srt.original").read_text(encoding="utf-8")) == atrasada
    assert sincronizar(legenda, tmp_path / "Filme.mkv", ouvir=lambda v: audio).status == "ja_certa"


def test_adiantada_e_casos_incertos(tmp_path):
    falas, total = falas_aleatorias(semente=7)
    audio = regua_da_legenda(falas, int(total / 0.01))
    assert melhor_atraso(audio, regua_da_legenda(deslocar(falas, -1.2), len(audio)))[0] == pytest.approx(1.2, abs=0.02)
    legenda = tmp_path / "X.srt"
    legenda.write_text(gerar_srt(deslocar(falas, 3)), encoding="utf-8")
    ruido = np.array([random.Random(3).random() > 0.5 for _ in range(len(audio))], dtype=np.float32)
    r = sincronizar(legenda, tmp_path / "X.mkv", ouvir=lambda v: ruido)  # áudio que não tem nada a ver
    assert r.status == "incerta" and not (tmp_path / "X.srt.original").exists()
    assert sincronizar(legenda, tmp_path / "X.mkv", ouvir=lambda v: np.zeros(10)).status == "incerta"
    erro = sincronizar(legenda, tmp_path / "X.mkv", ouvir=lambda v: (_ for _ in ()).throw(RuntimeError("sem av")))
    assert erro.status == "erro" and "sem av" in erro.detalhe


def test_quais_legendas_conferir(tmp_path):
    pasta = tmp_path / "Filmes" / "A [2001]"
    pasta.mkdir(parents=True)
    video = pasta / "A [2001].mkv"
    video.write_bytes(b"\0" * 2_000_000)
    for nome in ("A [2001].pt-BR.srt", "A [2001].en.srt", "A [2001].pt-BR.forced.srt"):
        (pasta / nome).write_text("1\n00:00:01,000 --> 00:00:02,000\nx\n", encoding="utf-8")
    pares = legendas_para_sincronizar(tmp_path / "Filmes")
    assert [p[0].name for p in pares] == ["A [2001].en.srt", "A [2001].pt-BR.srt"] and pares[0][1] == video
    ja = {str(pasta / "A [2001].en.srt"): (pasta / "A [2001].en.srt").stat().st_mtime}
    assert [p[0].name for p in legendas_para_sincronizar(tmp_path / "Filmes", conferidas=ja)] == ["A [2001].pt-BR.srt"]


def test_ouve_o_audio_de_verdade_em_pedacos(tmp_path, monkeypatch):
    """O caminho real (PyAV + detector de voz do Whisper), com pedaços de 2 s para passar pela emenda."""
    pytest.importorskip("av")
    pytest.importorskip("faster_whisper")
    from jellyfin_tools import sincronia
    from test_dublagem import FFMPEG, video_de_teste
    if not FFMPEG:
        pytest.skip("sem ffmpeg")
    monkeypatch.setattr(sincronia, "TRECHO", 2)
    regua = sincronia.regua_do_audio(video_de_teste(tmp_path / "v.mkv", segundos=5))
    assert abs(len(regua) - 500) <= 5 and regua.sum() == 0         # um apito não é voz
