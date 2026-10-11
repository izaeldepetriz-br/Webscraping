"""Gastos do mês nas APIs pagas: cada pedido anota o custo estimado e o teto para as tarefas pagas."""
from datetime import datetime
from types import SimpleNamespace

import pytest

from jellyfin_tools import gastos, voz_gemini
from jellyfin_tools.dublagem import ErroDublagem
from jellyfin_tools.traducao import ErroTraducao, Tradutor
from tests.test_traducao import ClienteFalso
from tests.test_voz_gemini import GeminiFalso


def test_soma_por_mes_e_servico(tmp_path):
    agora = [datetime(2026, 10, 11)]
    g = gastos.Gastos(tmp_path / "gastos.json", teto=5, agora=lambda: agora[0])
    g.registrar("Claude", 0.40)
    g.registrar("Gemini", 0.83)
    g.registrar("Gemini", 0)                                       # nada a anotar
    assert g.do_mes() == {"Claude": 0.40, "Gemini": 0.83} and g.total() == pytest.approx(1.23)
    assert g.resumo() == "US$ 1.23 (Claude 0.40 · Gemini 0.83) de US$ 5.00"
    agora[0] = datetime(2026, 11, 1)                               # o mês virou: começa do zero
    assert g.total() == 0 and g.resumo() == "US$ 0.00 (nada ainda) de US$ 5.00"
    assert g.total("2026-10") == pytest.approx(1.23)                # o mês passado fica guardado
    g.conferir()
    g.registrar("Claude", 5)
    with pytest.raises(gastos.TetoAtingido, match="teto de gastos do mês"):
        g.conferir()
    (tmp_path / "gastos.json").write_text("{quebrado", encoding="utf-8")
    assert g.total() == 0                                           # arquivo estragado não trava nada


def test_sem_configurar_nao_anota_nem_bloqueia(tmp_path):
    gastos.registrar("Claude", 1.0)
    gastos.conferir()
    assert gastos.atual() is None and not list(tmp_path.iterdir())


def test_cada_pedido_ao_claude_anota_e_o_teto_para(tmp_path):
    g = gastos.configurar(tmp_path / "gastos.json")
    tradutor = Tradutor(cliente=ClienteFalso())
    tradutor.traduzir_falas(["Hello.", "Bye."])
    assert g.do_mes()["Claude"] == pytest.approx(tradutor.custo) and tradutor.custo > 0
    g.teto = tradutor.custo / 2                                     # já passou do teto: o próximo pedido não vai
    antes = tradutor.pedidos
    with pytest.raises(ErroTraducao, match="teto de gastos"):
        tradutor.traduzir_falas(["Again."])
    assert tradutor.pedidos == antes


def test_cada_pedido_de_voz_ao_gemini_anota_e_o_teto_para(tmp_path):
    g = gastos.configurar(tmp_path / "gastos.json")
    motor = voz_gemini.MotorGemini("x", "Kore", cliente=GeminiFalso(), esperar=lambda s: None)
    motor.sintetizar([("Olá, tudo bem?", tmp_path / "1.wav")])
    gasto = g.do_mes()["Gemini"]
    assert gasto > 0 and gasto == pytest.approx(voz_gemini.custo_da_fala(0.06 * len("Olá, tudo bem?")), rel=0.2)
    g.teto = gasto
    with pytest.raises(ErroDublagem, match="teto de gastos"):
        motor.sintetizar([("De novo.", tmp_path / "2.wav")])
    assert not (tmp_path / "2.wav").exists()


def test_ouvir_quem_fala_tambem_anota(tmp_path):
    g = gastos.configurar(tmp_path / "gastos.json")
    cliente = SimpleNamespace(interactions=SimpleNamespace(create=lambda **k: SimpleNamespace(output_text="{}")))
    voz_gemini.perguntar_sobre_audio(cliente, "quem fala?", b"x" * 4000 * 60, esperar=lambda s: None)   # 1 min
    assert g.do_mes()["Gemini"] == pytest.approx(60 * voz_gemini.TOKENS_POR_SEGUNDO * voz_gemini.PRECO_OUVIR / 1e6)
