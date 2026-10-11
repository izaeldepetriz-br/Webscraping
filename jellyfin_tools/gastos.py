"""Quanto o Maestro gastou nas APIs pagas, por mês: Claude (Anthropic) e Gemini (Google AI Studio).

Cada pedido pago registra o seu custo ESTIMADO aqui (pelos tokens que a API devolveu, ou pelo tamanho do áudio),
no ponto mais baixo do código (Tradutor, motor do Gemini): assim vale para a janela, para os robôs agendados e para
a tradução em lote, sem ninguém precisar lembrar de somar.

Teto do mês (opcional): passou do teto, o próximo pedido pago é recusado com TetoAtingido. Quem chama transforma
em ErroTraducao/ErroDublagem, e o que já ficou pronto continua guardado (a dublagem retoma de onde parou).

É uma estimativa: o valor oficial é o da página de cobrança de cada empresa (console.anthropic.com e
aistudio.google.com). Sem configurar() (ex.: nos testes), nada é gravado e não há teto.
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
    def __init__(self, arquivo: Path, teto: float = 0.0, agora=datetime.now):
        self.arquivo, self.teto, self._agora = Path(arquivo), float(teto or 0), agora
        self._trava = threading.Lock()

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
        if self.teto > 0 and (gasto := self.total()) >= self.teto:
            raise TetoAtingido(f"o teto de gastos do mês (US$ {self.teto:.2f}) foi atingido: já são US$ {gasto:.2f} "
                               "estimados. Aumente o teto em Configurações > Gastos (ou espere o mês virar); o que "
                               "já ficou pronto está guardado")

    def resumo(self) -> str:
        """'US$ 1.23 (Claude 0.40 · Gemini 0.83) de US$ 5.00' para o painel e as Configurações."""
        valores = self.do_mes()
        partes = " · ".join(f"{s} {v:.2f}" for s, v in valores.items() if v) or "nada ainda"
        texto = f"US$ {sum(valores.values()):.2f} ({partes})"
        return texto + (f" de US$ {self.teto:.2f}" if self.teto > 0 else "")


_atual: Gastos | None = None


def configurar(arquivo: Path | None, teto: float = 0.0) -> Gastos | None:
    """Liga o registro (o app e os robôs chamam ao começar); None desliga."""
    global _atual
    _atual = Gastos(arquivo, teto) if arquivo else None
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
