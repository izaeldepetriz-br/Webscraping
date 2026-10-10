"""Legenda a partir do áudio: um Whisper FALSO faz o papel do modelo (nada é baixado e nenhum áudio é ouvido)."""
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from jellyfin_tools.traducao import Tradutor, ler_srt
from jellyfin_tools.transcricao import (MODELO_PADRAO, ErroTranscricao, SemLegenda, Transcritor, estimar,
                                        falas_dos_segmentos, legendar_pelo_audio, quebrar_linhas, tempo_srt,
                                        videos_sem_legenda)

from test_traducao import ClienteFalso


def palavras(inicio: float, texto: str, passo: float = 0.4):
    """' Hello there.' -> palavras com 0,4 s cada, começando em `inicio`."""
    lista = []
    for n, w in enumerate(texto.split()):
        lista.append(NS(start=inicio + n * passo, end=inicio + n * passo + passo - 0.05, word=" " + w))
    return lista


class WhisperFalso:
    """Faz o papel do WhisperModel: devolve trechos prontos e conta quantas vezes foi chamado."""

    def __init__(self, idioma="en", trechos=None, erro=None):
        self.idioma, self.erro, self.chamadas = idioma, erro, []
        self.trechos = trechos if trechos is not None else [
            NS(start=1.0, end=3.0, text=" Hello, how are you?", words=palavras(1.0, "Hello, how are you?")),
            NS(start=5.0, end=6.0, text=" Fine.", words=palavras(5.0, "Fine.")),
        ]

    def transcribe(self, caminho, **opcoes):
        self.chamadas.append((caminho, opcoes))
        if self.erro:
            raise self.erro
        return iter(self.trechos), NS(language=self.idioma, duration=10.0)


def test_tempo_e_quebra_de_linha():
    assert tempo_srt(3723.4567) == "01:02:03,457" and tempo_srt(-1) == "00:00:00,000"
    assert quebrar_linhas("curta") == "curta"
    texto = quebrar_linhas("Esta é uma frase bem comprida que precisa virar duas linhas na tela")
    assert texto.count("\n") == 1 and all(len(l) <= 42 for l in texto.split("\n"))


def test_trechos_viram_falas_do_tamanho_de_uma_legenda():
    longo = "Uma frase. " + "palavra " * 30                       # passa de 84 letras e de 6 s
    falas = falas_dos_segmentos([NS(start=0, end=20, text=longo, words=palavras(0.0, longo)),
                                 NS(start=30, end=31, text=" Depois da pausa.", words=palavras(30.0, "Depois da pausa."))])
    assert len(falas) == 5 and falas[0].texto.startswith("Uma frase. palavra")      # 4 + a de depois
    for f in falas:
        assert len(f.texto.replace("\n", " ")) <= 84 and all(len(l) <= 42 for l in f.texto.split("\n"))
        ini, fim = f.tempo.split(" --> ")
        assert ini < fim
    assert falas[-1].texto == "Depois da pausa." and falas[-1].tempo.startswith("00:00:30,000")
    sem_palavras = falas_dos_segmentos([NS(start=0, end=4, text=" Primeira. Segunda!", words=None)])
    assert [f.texto for f in sem_palavras] == ["Primeira.", "Segunda!"]
    assert sem_palavras[1].tempo.startswith("00:00:02")                     # tempo dividido pelo tamanho


def test_ouve_em_ingles_grava_a_original_e_traduz(tmp_path):
    video = tmp_path / "Filme (2003).mkv"
    video.write_bytes(b"\0" * 100)
    whisper, cliente, andamento = WhisperFalso(), ClienteFalso(), []
    transcritor = Transcritor(motor=whisper)
    assert transcritor.modelo == MODELO_PADRAO == "small"
    r = legendar_pelo_audio(video, transcritor, Tradutor(cliente=cliente), ao_progresso=andamento.append)
    assert r.status == "traduzida" and r.idioma_audio == "en" and r.falas == 2
    original = ler_srt((tmp_path / "Filme (2003).en.srt").read_text(encoding="utf-8"))
    traduzida = ler_srt((tmp_path / "Filme (2003).pt-BR.srt").read_text(encoding="utf-8"))
    assert [f.texto for f in original] == ["Hello, how are you?", "Fine."]
    assert [f.texto for f in traduzida] == ["PT: Hello, how are you?", "PT: Fine."]
    assert [f.tempo for f in traduzida] == [f.tempo for f in original]
    assert whisper.chamadas[0][1]["word_timestamps"] and whisper.chamadas[0][1]["vad_filter"]
    assert andamento[-1] == 1.0 and max(andamento[:-1]) <= 1.0
    assert legendar_pelo_audio(video, transcritor).status == "ja_existe"      # nunca refaz nem sobrescreve


def test_audio_em_portugues_nao_gasta_com_a_api(tmp_path):
    video = tmp_path / "Nacional (2010).mp4"
    video.write_bytes(b"\0" * 100)
    cliente = ClienteFalso()
    r = legendar_pelo_audio(video, Transcritor(motor=WhisperFalso(idioma="pt")), Tradutor(cliente=cliente))
    assert r.status == "criada" and (tmp_path / "Nacional (2010).pt-BR.srt").exists() and not cliente.pedidos
    sem_tradutor = tmp_path / "Outro (2011).mp4"
    sem_tradutor.write_bytes(b"\0")
    r = legendar_pelo_audio(sem_tradutor, Transcritor(motor=WhisperFalso(idioma="es")))
    assert r.status == "so_original" and (tmp_path / "Outro (2011).es.srt").exists()
    assert "Espanhol" in r.detalhe or "es" in r.detalhe


def test_erros_e_silencio(tmp_path):
    video = tmp_path / "Mudo (1920).mkv"
    video.write_bytes(b"\0")
    assert legendar_pelo_audio(video, Transcritor(motor=WhisperFalso(trechos=[]))).status == "sem_fala"
    r = legendar_pelo_audio(video, Transcritor(motor=WhisperFalso(erro=RuntimeError("arquivo corrompido"))))
    assert r.status == "erro" and "não deu para ouvir o áudio" in r.detalhe
    with pytest.raises(ErroTranscricao, match="interrompido"):
        Transcritor(motor=WhisperFalso()).transcrever(video, parar=lambda: True)


def test_placa_de_video_que_falha_volta_para_o_processador(tmp_path, monkeypatch):
    abertos = []

    def abrir(self, gpu):
        abertos.append(gpu)
        return WhisperFalso(erro=RuntimeError("cudnn64_9.dll não encontrada")) if gpu else WhisperFalso()
    monkeypatch.setattr(Transcritor, "_abrir", abrir)
    t = Transcritor(usar_gpu=True)
    lingua, _, falas = t.transcrever(tmp_path / "x.mkv")
    assert abertos == [True, False] and lingua == "en" and len(falas) == 2
    assert "usando o processador" in t.aviso


def test_acha_os_videos_sem_nenhuma_legenda(tmp_path):
    def video(caminho: Path, *legendas):
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_bytes(b"\0" * 2_000_000)
        for nome in legendas:
            (caminho.parent / nome).write_text("1\n00:00:01,000 --> 00:00:02,000\nx\n", encoding="utf-8")
        return caminho
    a = video(tmp_path / "Filmes" / "A (2001)" / "A (2001).mkv")
    video(tmp_path / "Filmes" / "B (2002)" / "B (2002).mkv", "B (2002).en.srt")       # o Traduzir resolve
    video(tmp_path / "Filmes" / "C (2003)" / "C (2003).mkv")                           # legenda embutida pt
    video(tmp_path / "Filmes" / "A (2001)" / "A (2001) - Dublado IA.mkv")              # versão dublada
    embutidas = {"C (2003).mkv": {"por"}}
    achados = videos_sem_legenda(tmp_path / "Filmes", sondar_arquivo=lambda v: (5400.0, embutidas.get(v.name, set())))
    assert achados == [SemLegenda(a, 5400.0)]
    horas, letras, falas = estimar(achados + [SemLegenda(a, None)])
    assert horas == 1.5 and letras == 5400 * 6 and falas > 1000
