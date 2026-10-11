"""Quanto o Maestro gastou nas APIs pagas, por mês: Claude (Anthropic) e Gemini (Google AI Studio).

Cada pedido pago registra o seu custo ESTIMADO aqui (pelos tokens que a API devolveu, ou pelo tamanho do áudio),
no ponto mais baixo do código (Tradutor, motor do Gemini): assim vale para a janela, para os robôs agendados e para
a tradução em lote, sem ninguém precisar lembrar de somar.

Teto do mês (opcional): passou do teto, o próximo pedido pago é recusado com TetoAtingido. Quem chama transforma
em ErroTraducao/ErroDublagem, e o que já ficou pronto continua guardado (a dublagem retoma de onde parou).

É uma estimativa: o valor oficial é o da página de cobrança de cada empresa (console.anthropic.com e
aistudio.google.com). Sem configurar() (ex.: nos testes), nada é gravado e não há teto.

Em reais: o arquivo guarda sempre em DÓLAR (é como as APIs cobram); `fator` (cotação × (1 + IOF)) só converte
para mostrar e para comparar com o teto, que fica na moeda escolhida na tela (ver cotacao.py).
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path

SERVICOS = ("Claude", "Gemini")


class TetoAtingido(Exception):
    pass


class Gastos:
    def __init__(self, arquivo: Path, teto: float = 0.0, agora=datetime.now, fator: float | None = None,
                 conversao: str = ""):
        """teto: na moeda mostrada (reais, com `fator`; senão dólares). fator: reais por dólar já com o IOF.
        conversao: o texto de onde veio o fator ('PTAX de 09/10 + IOF 3,5%')."""
        self.arquivo, self.teto, self._agora = Path(arquivo), float(teto or 0), agora
        self.fator, self.conversao = (float(fator) if fator else None), conversao
        self._trava = threading.Lock()

    def valor(self, dolares: float) -> str:
        """US$ -> texto na moeda mostrada: 'R$ 12,45' (com a cotação) ou 'US$ 2.29'."""
        if self.fator:
            from .cotacao import em_reais
            return em_reais(dolares * self.fator)
        return f"US$ {dolares:.2f}"

    def _teto_texto(self) -> str:
        if self.fator:
            from .cotacao import em_reais
            return em_reais(self.teto)
        return f"US$ {self.teto:.2f}"

    def na_moeda(self, dolares: float) -> float:
        return dolares * self.fator if self.fator else dolares

    def _ler(self) -> dict:
        try:
            dados = json.loads(self.arquivo.read_text(encoding="utf-8"))
            return dados if isinstance(dados, dict) else {}
        except (OSError, ValueError):
            return {}

    def mes(self) -> str:
        return f"{self._agora():%Y-%m}"

    def do_mes(self, mes: str | None = None) -> dict[str, float]:
        """{"Claude": US$, "Gemini": US$} do mês (o atual, se não disser)."""
        meses = self._ler().get("meses", {})
        do_mes = meses.get(mes or self.mes(), {}) if isinstance(meses, dict) else {}
        return {s: float(do_mes.get(s, 0) or 0) for s in SERVICOS}

    def total(self, mes: str | None = None) -> float:
        return sum(self.do_mes(mes).values())

    def registrar(self, servico: str, valor: float) -> None:
        if not valor or valor <= 0:
            return
        with self._trava:
            dados = self._ler()
            meses = dados.setdefault("meses", {})
            do_mes = meses.setdefault(self.mes(), {})
            do_mes[servico] = round(float(do_mes.get(servico, 0) or 0) + valor, 6)
            self.arquivo.parent.mkdir(parents=True, exist_ok=True)
            temporario = self.arquivo.with_suffix(".tmp")
            temporario.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
            temporario.replace(self.arquivo)

    def conferir(self) -> None:
        """Antes de um pedido pago: passou do teto do mês? TetoAtingido com o motivo."""
        if self.teto > 0 and self.na_moeda(gasto := self.total()) >= self.teto:
            raise TetoAtingido(f"o teto de gastos do mês ({self._teto_texto()}) foi atingido: já são "
                               f"{self.valor(gasto)} estimados. Aumente o teto em Configurações > Gastos (ou espere "
                               "o mês virar); o que já ficou pronto está guardado")

    def resumo(self) -> str:
        """'US$ 1.23 (Claude 0.40 · Gemini 0.83) de US$ 5.00', ou em reais: 'R$ 12,45 (Claude R$ 2,28 · Gemini
        R$ 10,17) de R$ 30,00', para o painel e as Configurações."""
        valores = self.do_mes()
        if self.fator:
            partes = " · ".join(f"{s} {self.valor(v)}" for s, v in valores.items() if v) or "nada ainda"
        else:
            partes = " · ".join(f"{s} {v:.2f}" for s, v in valores.items() if v) or "nada ainda"
        texto = f"{self.valor(sum(valores.values()))} ({partes})"
        return texto + (f" de {self._teto_texto()}" if self.teto > 0 else "")

    def perto_do_teto(self, parte: float = 0.8) -> bool:
        return self.teto > 0 and self.na_moeda(self.total()) >= parte * self.teto


_atual: Gastos | None = None


def configurar(arquivo: Path | None, teto: float = 0.0, fator: float | None = None,
               conversao: str = "") -> Gastos | None:
    """Liga o registro (o app e os robôs chamam ao começar); None desliga. fator: reais por dólar (com IOF)."""
    global _atual
    _atual = Gastos(arquivo, teto, fator=fator, conversao=conversao) if arquivo else None
    return _atual


def atual() -> Gastos | None:
    return _atual


def registrar(servico: str, valor: float) -> None:
    if _atual is not None:
        try:
            _atual.registrar(servico, valor)
        except OSError:
            pass                                  # não conseguir anotar o gasto não pode parar a tarefa


def conferir() -> None:
    if _atual is not None:
        _atual.conferir()
