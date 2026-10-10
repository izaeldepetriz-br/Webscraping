"""Tradução de legendas com o Claude: um cliente FALSO faz o papel da API (nenhum teste gasta crédito)."""
import json
import re
from types import SimpleNamespace

import pytest

from jellyfin_tools.traducao import (ErroTraducao, Fala, MODELO_PADRAO, Tradutor, estimar_custo, gerar_srt,
                                     legendas_para_traduzir, ler_srt, parece_portugues, traduzir_arquivo)

SRT = """1
00:00:01,000 --> 00:00:03,000
Hello, how are you?

2
00:00:04,000 --> 00:00:06,500
<i>I'm fine.</i>
Thanks!

3
00:00:07,000 --> 00:00:08,000


4
00:00:09,000 --> 00:00:10,000
See you tomorrow.
"""


class ClienteFalso:
    """Faz o papel de anthropic.Anthropic: lê as falas do pedido e devolve 'PT: <texto>' com o mesmo id."""

    def __init__(self, respostas=None, esquecer=(), parar_em_tokens=False):
        self.pedidos = []
        self.esquecer = set(esquecer)           # ids que a "IA" não devolve na 1ª vez
        self.parar_em_tokens = parar_em_tokens
        self.messages = self

    def create(self, **k):
        self.pedidos.append(k)
        falas = json.loads(k["messages"][0]["content"].split("Falas:\n", 1)[1])
        if self.parar_em_tokens and len(falas) > 1:
            return SimpleNamespace(stop_reason="max_tokens", content=[], usage=SimpleNamespace(
                input_tokens=10, output_tokens=10))
        volta = [{"id": f["id"], "texto": "PT: " + f["texto"]} for f in falas if f["id"] not in self.esquecer]
        self.esquecer.clear()
        return SimpleNamespace(stop_reason="end_turn", usage=SimpleNamespace(input_tokens=100, output_tokens=120),
                               content=[SimpleNamespace(type="text", text=json.dumps({"falas": volta}))])


def test_ler_e_gerar_srt_mantem_os_horarios_e_as_quebras():
    falas = ler_srt("﻿" + SRT.replace("\n", "\r\n"))
    assert [f.tempo for f in falas] == ["00:00:01,000 --> 00:00:03,000", "00:00:04,000 --> 00:00:06,500",
                                        "00:00:07,000 --> 00:00:08,000", "00:00:09,000 --> 00:00:10,000"]
    assert falas[1].texto == "<i>I'm fine.</i>\nThanks!" and falas[2].texto == ""
    assert ler_srt(gerar_srt(falas)) == falas                                   # ida e volta sem perder nada


def test_traduz_so_o_texto_com_o_mesmo_id_e_os_mesmos_horarios(tmp_path):
    origem = tmp_path / "Filme (2003).en.srt"
    origem.write_text(SRT, encoding="utf-8")
    cliente = ClienteFalso()
    tradutor = Tradutor(cliente=cliente)
    assert tradutor.modelo == MODELO_PADRAO == "claude-sonnet-4-6"
    r = traduzir_arquivo(origem, tmp_path / "Filme (2003).pt-BR.srt", tradutor, titulo="Filme (2003)")
    assert r.status == "traduzida" and r.falas == 4
    falas = ler_srt(r.destino.read_text(encoding="utf-8"))
    assert [f.texto for f in falas] == ["PT: Hello, how are you?", "PT: <i>I'm fine.</i>\nThanks!", "",
                                        "PT: See you tomorrow."]                # a fala vazia não vai para a API
    assert [f.tempo for f in falas] == [f.tempo for f in ler_srt(SRT)]
    pedido = cliente.pedidos[0]
    assert pedido["model"] == "claude-sonnet-4-6" and pedido["output_config"]["format"]["type"] == "json_schema"
    assert "Português" in pedido["system"] and "Filme (2003)" in pedido["messages"][0]["content"]
    assert "-->" not in pedido["messages"][0]["content"]                       # os horários nunca saem do PC
    assert (tradutor.tokens_entrada, tradutor.tokens_saida) == (100, 120)
    assert tradutor.custo == pytest.approx((100 * 3 + 120 * 15) / 1_000_000)
    assert traduzir_arquivo(origem, r.destino, tradutor).status == "ja_existe"  # nunca sobrescreve


def test_lotes_com_contexto_fala_esquecida_e_resposta_longa_demais():
    textos = [f"Line {n}" for n in range(250)]
    cliente = ClienteFalso(esquecer={7})
    progresso = []
    tradutor = Tradutor(cliente=cliente)
    saida = tradutor.traduzir_falas(textos, "Série S01E01", ao_progresso=lambda f, t: progresso.append((f, t)))
    assert saida == [f"PT: Line {n}" for n in range(250)]
    assert len(cliente.pedidos) == 4                                            # 3 lotes + 1 para a esquecida
    assert "Falas anteriores" in cliente.pedidos[2]["messages"][0]["content"]  # 2º lote leva contexto
    assert progresso == [(100, 250), (200, 250), (250, 250)]
    dividido = Tradutor(cliente=ClienteFalso(parar_em_tokens=True))
    assert dividido.traduzir_falas(["a", "b", "c"]) == ["PT: a", "PT: b", "PT: c"]   # dividiu até caber


def test_erros_viram_mensagens_em_portugues():
    class Recusa(ClienteFalso):
        def create(self, **k):
            return SimpleNamespace(stop_reason="refusal", content=[], usage=None)

    class AuthenticationError(Exception):
        pass

    class SemChave(ClienteFalso):
        def create(self, **k):
            raise AuthenticationError("401")
    with pytest.raises(ErroTraducao, match="recusou"):
        Tradutor(cliente=Recusa()).traduzir_falas(["oi"])
    with pytest.raises(ErroTraducao, match="chave de API foi recusada"):
        Tradutor(cliente=SemChave()).traduzir_falas(["oi"])
    with pytest.raises(ErroTraducao, match="interrompido"):
        Tradutor(cliente=ClienteFalso()).traduzir_falas(["oi"], parar=lambda: True)


def test_acha_na_biblioteca_o_que_falta_traduzir(tmp_path):
    def video(caminho, *legendas):
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_bytes(b"\0" * 2_000_000)
        for nome, texto in legendas:
            (caminho.parent / nome).write_text(texto, encoding="utf-8")
        return caminho
    a = video(tmp_path / "Filmes" / "A (2001)" / "A (2001).mkv", ("A (2001).en.srt", SRT), ("A (2001).es.srt", SRT))
    video(tmp_path / "Filmes" / "B (2002)" / "B (2002).mkv", ("B (2002).en.srt", SRT), ("B (2002).pt-BR.srt", SRT))
    video(tmp_path / "Filmes" / "C (2003)" / "C (2003).mkv", ("C (2003).en.forced.srt", SRT))
    portugues = "1\n00:00:01,000 --> 00:00:02,000\nVocê não está aqui agora, então vamos já.\n"
    video(tmp_path / "Series" / "D" / "Season 01" / "D S01E01.mkv", ("D S01E01.srt", portugues))
    e = video(tmp_path / "Series" / "D" / "Season 01" / "D S01E02.mkv", ("D S01E02.srt", SRT))
    pendentes = legendas_para_traduzir(tmp_path / "Filmes", tmp_path / "Series")
    assert [(p.video, p.origem.name, p.destino.name) for p in pendentes] == [
        (a, "A (2001).en.srt", "A (2001).pt-BR.srt"),                           # o inglês tem preferência
        (e, "D S01E02.srt", "D S01E02.pt-BR.srt")]                              # sem idioma, mas não é português
    assert pendentes[0].caracteres == sum(len(f.texto) for f in ler_srt(SRT))
    assert parece_portugues(portugues) and not parece_portugues(SRT)


def test_estimativa_de_custo():
    entrada, saida, custo = estimar_custo(30_000, 700, "claude-sonnet-4-6")
    assert 8_000 < entrada < 20_000 and 8_000 < saida < 20_000
    assert custo == pytest.approx((entrada * 3 + saida * 15) / 1_000_000)
    assert estimar_custo(1000, 10, "modelo-que-nao-existe")[2] is None
    assert re.fullmatch(r"claude-[a-z0-9-]+", MODELO_PADRAO)
    assert Fala("t", "x") == Fala("t", "x")
