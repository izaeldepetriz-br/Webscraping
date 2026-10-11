"""Cotação do dólar (PTAX do Banco Central) para mostrar os gastos em reais. Sem internet: respostas de mentira."""
from datetime import date
from types import SimpleNamespace

import pytest

from jellyfin_tools import cotacao, gastos

BUSCAR_PTAX = cotacao.buscar_ptax            # a de verdade (nos testes, a "da internet" é trocada por uma offline)


class Resposta:
    def __init__(self, dados, codigo=200):
        self.dados, self.codigo = dados, codigo

    def raise_for_status(self):
        if self.codigo >= 400:
            raise RuntimeError(f"HTTP {self.codigo}")

    def json(self):
        return self.dados


def test_ptax_pede_os_ultimos_dias_e_fica_com_a_mais_recente():
    pedidos = []

    def obter(url, params, timeout):
        pedidos.append((url, params))
        return Resposta({"value": [{"cotacaoVenda": 5.41, "dataHoraCotacao": "2026-10-08 13:03:10.1"},
                                   {"cotacaoVenda": 5.44, "dataHoraCotacao": "2026-10-09 13:04:29.5"}]})
    valor, quando = BUSCAR_PTAX(date(2026, 10, 11), obter=obter)     # domingo: vale a de sexta
    assert (valor, quando) == (5.44, "2026-10-09")
    url, params = pedidos[0]
    assert "CotacaoDolarPeriodo" in url and params["@dataInicial"] == "'10-01-2026'"
    assert params["@dataFinalCotacao"] == "'10-11-2026'" and params["$format"] == "json"


@pytest.mark.parametrize("resposta", [Resposta({"value": []}), Resposta({}, 500), Resposta({"value": [{"x": 1}]})])
def test_ptax_sem_resposta_boa_e_erro_explicado(resposta):
    with pytest.raises(cotacao.ErroCotacao):
        BUSCAR_PTAX(date(2026, 10, 11), obter=lambda *a, **k: resposta)


def test_cotacao_guardada_por_um_dia_e_a_ultima_vale_sem_internet(tmp_path):
    arquivo, consultas = tmp_path / "cotacao_dolar.json", []

    def buscar(hoje):
        consultas.append(hoje)
        return 5.44, "2026-10-09"
    dados = cotacao.atual(arquivo, date(2026, 10, 11), buscar)
    assert dados["valor"] == 5.44 and dados["fonte"].startswith("Banco Central")
    cotacao.atual(arquivo, date(2026, 10, 11), buscar)              # mesmo dia: não consulta de novo
    assert len(consultas) == 1

    def sem_internet(hoje):
        raise cotacao.ErroCotacao("offline")
    assert cotacao.atual(arquivo, date(2026, 10, 12), sem_internet)["valor"] == 5.44    # a última guardada
    assert cotacao.atual(tmp_path / "nunca.json", date(2026, 10, 12), sem_internet) == {}


def test_formato_brasileiro():
    assert cotacao.em_reais(1234.5) == "R$ 1.234,50" and cotacao.em_reais(0.456) == "R$ 0,46"
    assert cotacao.data_br("2026-10-09") == "09/10"


def test_gastos_em_reais_com_teto_em_reais(tmp_path):
    g = gastos.Gastos(tmp_path / "g.json", teto=20, fator=5.44 * 1.035, conversao="PTAX")
    g.registrar("Gemini", 3.0)                                      # US$ 3 = R$ 16,89
    assert g.resumo() == "R$ 16,89 (Gemini R$ 16,89) de R$ 20,00" and g.perto_do_teto()
    g.conferir()
    g.registrar("Claude", 1.0)                                      # mais R$ 5,63: passou de R$ 20
    with pytest.raises(gastos.TetoAtingido, match=r"R\$ 20,00.*R\$ 22,52"):
        g.conferir()


def test_conversao_da_tela(tmp_path, monkeypatch):
    from videoscraper import automacao, config
    monkeypatch.setattr(config, "ARQUIVO", tmp_path / "config.json")
    o = SimpleNamespace(moeda_gastos="R$", cotacao_dolar=0.0, iof_cartao=3.5, teto_gastos=30.0)
    fator, texto = automacao.conversao_reais(o)                     # sem internet e sem nada guardado
    assert fator is None and "dólar" in texto
    assert automacao.configurar_gastos(o).teto == 0                 # sem cotação, o teto em reais não vale em dólar
    monkeypatch.setattr(cotacao, "buscar_ptax", lambda hoje: (5.44, "2026-10-09"))
    fator, texto = automacao.conversao_reais(o)
    assert fator == pytest.approx(5.44 * 1.035) and texto == "US$ 1 = R$ 5,44 (PTAX de 09/10, Banco Central) + IOF 3,5%"
    o.cotacao_dolar = 5.0
    assert automacao.conversao_reais(o)[1] == "US$ 1 = R$ 5,00 (cotação fixa) + IOF 3,5%"
    o.moeda_gastos = "US$"
    assert automacao.conversao_reais(o) == (None, "") and automacao.configurar_gastos(o).teto == 30
