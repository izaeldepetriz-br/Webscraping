"""Cotação do dólar para mostrar os gastos das APIs em reais: a PTAX de venda do Banco Central (oficial, grátis, sem
chave), guardada por um dia num arquivo. Sem internet, vale a última guardada; o usuário também pode fixar uma.

    API (OData do BCB): CotacaoDolarPeriodo com as datas no formato MM-DD-AAAA; a resposta traz
    {"value": [{"cotacaoCompra": 5.43, "cotacaoVenda": 5.44, "dataHoraCotacao": "2026-10-09 13:04:29.513"}, ...]}
    Fim de semana e feriado não têm cotação: pede os últimos 10 dias e fica com a mais recente.

As APIs cobram em dólar no cartão: no Brasil, a compra internacional no cartão tem IOF (em 2026, 3,5%; confira na
fatura). O valor em reais aqui é uma ESTIMATIVA: dólar estimado × cotação × (1 + IOF).
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

URL = ("https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/CotacaoDolarPeriodo("
       "dataInicial=@dataInicial,dataFinalCotacao=@dataFinalCotacao)")
IOF_PADRAO = 3.5          # % sobre compras internacionais no cartão (confira na sua fatura)


class ErroCotacao(Exception):
    pass


def buscar_ptax(hoje: date | None = None, obter=None, timeout: float = 8) -> tuple[float, str]:
    """(cotação de venda, 'AAAA-MM-DD') da PTAX mais recente dos últimos 10 dias."""
    hoje = hoje or date.today()
    if obter is None:
        import requests
        obter = requests.get
    parametros = {"@dataInicial": f"'{hoje - timedelta(days=10):%m-%d-%Y}'",
                  "@dataFinalCotacao": f"'{hoje:%m-%d-%Y}'", "$format": "json",
                  "$select": "cotacaoVenda,dataHoraCotacao"}
    try:
        resposta = obter(URL, params=parametros, timeout=timeout)
        resposta.raise_for_status()
        valores = resposta.json().get("value", [])
    except Exception as erro:                                    # sem internet, site fora, resposta estranha
        raise ErroCotacao(f"não deu para consultar a cotação no Banco Central ({type(erro).__name__})") from erro
    validos = [v for v in valores if isinstance(v, dict) and v.get("cotacaoVenda") and v.get("dataHoraCotacao")]
    if not validos:
        raise ErroCotacao("o Banco Central não devolveu cotação para os últimos dias")
    ultimo = max(validos, key=lambda v: v["dataHoraCotacao"])
    return float(ultimo["cotacaoVenda"]), str(ultimo["dataHoraCotacao"])[:10]


def carregar(arquivo: Path) -> dict:
    try:
        dados = json.loads(Path(arquivo).read_text(encoding="utf-8"))
        return dados if isinstance(dados, dict) and float(dados.get("valor", 0)) > 0 else {}
    except (OSError, ValueError, TypeError):
        return {}


def atual(arquivo: Path, hoje: date | None = None, buscar=None) -> dict:
    """{"valor": 5.44, "data": "2026-10-09", "fonte": "Banco Central (PTAX)"}: a guardada, se for de hoje; senão
    consulta (e guarda). Falhou a consulta: a última guardada (ou {} se nunca deu certo)."""
    hoje = hoje or date.today()
    guardada = carregar(arquivo)
    if guardada.get("consultada_em") == hoje.isoformat():
        return guardada
    try:
        valor, quando = (buscar or buscar_ptax)(hoje)
    except ErroCotacao:
        return guardada
    nova = {"valor": valor, "data": quando, "fonte": "Banco Central (PTAX)", "consultada_em": hoje.isoformat()}
    try:
        Path(arquivo).parent.mkdir(parents=True, exist_ok=True)
        Path(arquivo).write_text(json.dumps(nova, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return nova


def em_reais(valor: float) -> str:
    """1234.5 -> 'R$ 1.234,50' (o jeito brasileiro: ponto nos milhares, vírgula nos centavos)."""
    texto = f"{valor:,.2f}".replace(",", "§").replace(".", ",").replace("§", ".")
    return f"R$ {texto}"


def data_br(iso: str) -> str:
    try:
        return datetime.strptime(iso[:10], "%Y-%m-%d").strftime("%d/%m")
    except ValueError:
        return iso
