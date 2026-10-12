"""Roteiro: quem fala cada fala sai do roteiro (nome em MAIÚSCULAS e a fala embaixo), comparado no PC, sem IA.
O roteiro de exemplo foi escrito para o teste (não é de nenhum filme)."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from jellyfin_tools import personagens, roteiro
from jellyfin_tools.dublagem import falas_da_legenda
from jellyfin_tools.traducao import Fala

ROTEIRO = """
                         THE LIGHTHOUSE

1.   INT. KITCHEN. NIGHT.                                         1.

     MARA, a tired woman of forty, stirs a pot. Her son
     LEO bursts in, dripping wet.

                         LEO
               Mom, the bus left without me again.

                         MARA
                    (not looking up)
               Then you walk tomorrow. Set the table.

                         LEO (O.S.)
               Fine. But I am not eating the green stuff.

                                              CUT TO:

2.   EXT. PIER. LATER.                                            2.

     An OLD SAILOR mends a net. He squints at the sea.

                         OLD SAILOR
               The fog always comes back for what it lost.

                         LEO
               What did it lose?

                         OLD SAILOR
               A keeper. Forty years ago tonight.

                         MARA (V.O.)
               Leo! Dinner is getting cold!
"""

EN = """1
00:00:01,000 --> 00:00:03,000
Mom, the bus left without me.

2
00:00:03,500 --> 00:00:05,000
Then you walk tomorrow.

3
00:00:05,200 --> 00:00:06,500
Set the table.

4
00:00:07,000 --> 00:00:09,000
I am not eating the green stuff.

5
00:00:12,000 --> 00:00:14,000
The fog always comes back.

6
00:00:14,500 --> 00:00:15,500
What did it lose?

7
00:00:16,000 --> 00:00:18,000
- A keeper.
- What?

8
00:00:19,000 --> 00:00:20,000
Something nobody wrote.
"""

PT = """1
00:00:01,000 --> 00:00:03,000
Mãe, o ônibus foi embora sem mim.

2
00:00:03,500 --> 00:00:05,000
Então amanhã você vai a pé.

3
00:00:05,200 --> 00:00:06,500
Põe a mesa.

4
00:00:07,000 --> 00:00:09,000
Não vou comer a coisa verde.

5
00:00:12,000 --> 00:00:14,000
A neblina sempre volta.

6
00:00:14,500 --> 00:00:15,500
O que ela perdeu?

7
00:00:16,000 --> 00:00:18,000
- Um faroleiro.
- O quê?

8
00:00:19,000 --> 00:00:20,000
Algo que ninguém escreveu.
"""


def test_le_o_roteiro_e_o_genero_de_cada_um():
    falas = roteiro.ler_roteiro(ROTEIRO)
    assert [(d.personagem, d.texto) for d in falas[:3]] == [
        ("Leo", "Mom, the bus left without me again."), ("Mara", "Then you walk tomorrow. Set the table."),
        ("Leo", "Fine. But I am not eating the green stuff.")]                    # "(not looking up)" saiu
    assert {d.personagem for d in falas} == {"Leo", "Mara", "Old Sailor"}     # CUT TO, INT., EXT. não são nomes
    generos = roteiro.generos(ROTEIRO, {"Leo", "Mara", "Old Sailor"})
    assert generos == {"Mara": "f", "Leo": "m", "Old Sailor": "?"}     # o "He" do marinheiro está noutra frase
    assert roteiro.generos("", {"Tina's Mother", "Old Man"}) == {"Tina's Mother": "f", "Old Man": "m"}


def test_casa_as_falas_em_ordem_e_pula_o_que_nao_e_do_roteiro():
    falas = roteiro.ler_roteiro(ROTEIRO)
    linhas = [b.split("\n", 2)[2] for b in EN.strip().split("\n\n")]
    achadas = roteiro.casar(falas, linhas)
    assert achadas == {0: "Leo", 1: "Mara", 2: "Mara", 3: "Leo", 4: "Old Sailor", 5: "Leo"}
    # 6: duas pessoas na mesma legenda; 7: não está no roteiro (improviso)


def test_quem_fala_pela_legenda_original_do_mesmo_horario(tmp_path):
    video = tmp_path / "Farol (2020).mkv"
    video.write_bytes(b"")
    (tmp_path / "Farol (2020).en.srt").write_text(EN, encoding="utf-8")
    legenda = tmp_path / "Farol (2020).pt-BR.srt"
    legenda.write_text(PT, encoding="utf-8")
    falas = falas_da_legenda(legenda)
    assert roteiro.quem_fala(video, falas) is None                          # ainda sem roteiro
    (tmp_path / "Farol (2020).roteiro.html").write_text(
        "<html><body><pre>" + ROTEIRO.replace("&", "&amp;") + "</pre></body></html>", encoding="utf-8")
    achado = roteiro.quem_fala(video, falas)
    assert achado.falas == {0: "Leo", 1: "Mara", 2: "Mara", 3: "Leo", 4: "Old Sailor", 5: "Leo"}
    assert achado.cobertura == pytest.approx(6 / 8) and achado.generos["Mara"] == "f"
    assert roteiro.legenda_original(video).name == "Farol (2020).en.srt"


def test_guardar_o_roteiro_ao_lado_do_video(tmp_path):
    video = tmp_path / "Farol.mkv"
    (tmp_path / "Farol.roteiro.pdf").write_bytes(b"%PDF antigo")
    with pytest.raises(roteiro.ErroRoteiro, match="não parece um roteiro"):
        roteiro.guardar_roteiro(video, "Uma receita de bolo.\nFarinha e ovos.")
    texto = ROTEIRO * 4                                                      # 20+ falas
    destino = roteiro.guardar_roteiro(video, texto)
    assert destino.name == "Farol.roteiro.txt" and not (tmp_path / "Farol.roteiro.pdf").exists()
    assert roteiro.caminho_roteiro(video) == destino and roteiro.texto_do_roteiro(destino) == texto


def test_pdf_so_de_imagens_e_link(tmp_path, monkeypatch):
    pdf = tmp_path / "r.pdf"
    pdf.write_bytes(b"%PDF")
    monkeypatch.setattr(roteiro, "_do_pdf", lambda caminho: "  12/10/2026  ")
    with pytest.raises(roteiro.ErroRoteiro, match="só imagem"):
        roteiro.texto_do_roteiro(pdf)
    with pytest.raises(roteiro.ErroRoteiro, match="http"):
        roteiro.baixar_roteiro("www.exemplo.com/roteiro")
    pagina = SimpleNamespace(status_code=200, headers={"content-type": "text/html"},
                             text="<html><pre>  LEO\n  Oi &amp; tchau.\n</pre></html>")
    assert "Oi & tchau." in roteiro.baixar_roteiro("https://exemplo.com/r.html", obter=lambda *a, **k: pagina)
    with pytest.raises(roteiro.ErroRoteiro, match="404"):
        roteiro.baixar_roteiro("https://exemplo.com/x", obter=lambda *a, **k: SimpleNamespace(status_code=404,
                                                                                             headers={}))


def test_gemini_so_ouve_o_trecho_que_o_roteiro_nao_cobriu(tmp_path):
    """Trecho 1 (0-15 min): o roteiro achou todas as falas -> não vai para o Gemini. Trecho 2: vai, com as falas
    sabidas marcadas, e o roteiro vale mais que o Gemini."""
    falas = [(Fala(f"00:{m:02d}:{s:02d},000 --> 00:{m:02d}:{s + 1:02d},000", t), t) for m, s, t in
             [(0, 5, "Mãe, o ônibus foi embora."), (0, 9, "Põe a mesa."), (16, 1, "A neblina volta."),
              (16, 4, "O que ela perdeu?"), (16, 8, "Algo que ninguém escreveu.")]]
    sabidas = {0: "Leo", 1: "Mara", 2: "Old Sailor", 3: "Leo"}
    perguntas = []

    class Ouvinte:
        def __init__(self):
            self.interactions = self

        def create(self, model, input):
            perguntas.append(input[0]["text"])
            return SimpleNamespace(output_text=json.dumps({
                "pessoas": [{"rotulo": "Leo", "genero": "m"}, {"rotulo": "Pessoa 1", "genero": "f"}],
                "falas": [{"id": 2, "rotulo": "Pessoa 1"}, {"id": 3, "rotulo": "Leo"}, {"id": 4, "rotulo": "Leo"}]}))
    trechos = []
    lista = personagens.identificar("farol.mkv", falas, Ouvinte(), "ffmpeg", tmp_path / "p.json",
                                    extrair=lambda f, v, ini, dur: trechos.append(ini) or b"mp3",
                                    elenco=[{"rotulo": "Mara", "genero": "f", "descricao": "do roteiro"}],
                                    sabidas=sabidas)
    assert trechos == [900]                                                  # só o 2º trecho foi ouvido
    assert "2 [61.0s] A neblina volta. [roteiro: Old Sailor]" in perguntas[0] and "[roteiro:" in perguntas[0]
    quem = {k: p.rotulo for p in lista for k in p.falas}
    assert quem == {0: "Leo", 1: "Mara", 2: "Old Sailor", 3: "Leo", 4: "Leo"}   # a 2 ficou com o roteiro
    assert {p.rotulo: p.genero for p in lista}["Mara"] == "f"
    assert personagens.trecho_coberto([0, 1], sabidas) and not personagens.trecho_coberto([2, 4], sabidas)
