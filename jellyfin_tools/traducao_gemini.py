"""Traduzir com o Gemini Flash (o mesmo modelo que ouve os filmes), pela chave do Google AI Studio: com a chave
GRÁTIS não custa nada (tem um limite de pedidos por dia: um jogo grande pode levar mais de um dia). O mesmo jeito de
usar do Tradutor do Claude e do grátis no PC: traduzir_falas(textos, titulo, parar, ao_progresso).

Para os jogos, as mesmas regras do Claude (roteiro_jogo): as marcas ⟦1⟧ dos códigos voltam iguais e o "max" de
cada texto é respeitado (o que passar, ele encurta numa 2ª volta).
"""

from __future__ import annotations

import json
import re
import time

from . import gastos
from .traducao import LINHAS_POR_PEDIDO, ErroTraducao, nome_do_idioma
from .voz_gemini import MODELO_OUVIR, _cliente, _com_tentativas, texto_da_resposta

PRECO_TEXTO = (0.30, 2.50)      # US$ por milhão de tokens (entrada, saída) do Flash pago: estimativa, confira
_JSON = re.compile(r"\{.*\}", re.S)


class TradutorGemini:
    """O tradutor do Gemini Flash. sistema: as regras (as de jogo, de roteiro_jogo, ou as de legenda)."""

    def __init__(self, chave: str, idioma: str = "pt-BR", sistema: str = "", cliente=None, modelo: str = MODELO_OUVIR,
                 esperar=time.sleep, avisar=None):
        from .roteiro_jogo import _SISTEMA_JOGO
        self.idioma, self.modelo = idioma, modelo
        self.sistema = sistema or _SISTEMA_JOGO.format(idioma=nome_do_idioma(idioma))
        self.cliente = cliente or _cliente(chave, avisar)
        self.esperar, self.avisar = esperar, avisar
        self.limites: dict = {}
        self.pedidos = self.tokens_entrada = self.tokens_saida = 0

    @property
    def custo(self) -> float:
        """O que custaria no Flash pago (com a chave grátis é zero)."""
        return (self.tokens_entrada * PRECO_TEXTO[0] + self.tokens_saida * PRECO_TEXTO[1]) / 1_000_000

    def conferir_teto(self) -> None:
        try:
            gastos.conferir()
        except gastos.TetoAtingido as erro:
            raise ErroTraducao(str(erro)) from erro

    def _pedir(self, pedido: str) -> dict[int, str]:
        self.conferir_teto()
        texto = self.sistema + "\n\n" + pedido + '\n\nResponda SÓ com JSON: {"falas": [{"id": 0, "texto": "..."}]}'
        try:
            resposta = _com_tentativas(lambda: self.cliente.interactions.create(model=self.modelo, input=texto),
                                       self.esperar, self.avisar, "tradução")
        except Exception as erro:
            raise ErroTraducao(f"o Gemini não traduziu: {erro}") from erro
        self.pedidos += 1
        gastos.contar_pedido_gemini("texto")
        uso = getattr(resposta, "usage", None)
        self.tokens_entrada += int(getattr(uso, "total_input_tokens", 0) or len(texto) // 4)
        saida = texto_da_resposta(resposta)
        self.tokens_saida += int(getattr(uso, "total_output_tokens", 0) or len(saida) // 4)
        achado = _JSON.search(saida or "")
        try:
            return {int(f["id"]): str(f["texto"]) for f in json.loads(achado.group(0))["falas"]}
        except (AttributeError, ValueError, KeyError, TypeError) as erro:
            raise ErroTraducao("a resposta do Gemini veio num formato inesperado") from erro

    def traduzir_falas(self, textos: list[str], titulo: str = "", parar=None, ao_progresso=None) -> list[str]:
        resultado = list(textos)
        fazer = [i for i, t in enumerate(textos) if t.strip()]
        for inicio in range(0, len(fazer), LINHAS_POR_PEDIDO):
            if parar and parar():
                raise ErroTraducao("interrompido")
            lote = fazer[inicio:inicio + LINHAS_POR_PEDIDO]
            itens = [{"id": i, "texto": textos[i], **({"max": self.limites[i]} if self.limites.get(i) else {})}
                     for i in lote]
            pedido = (f"Título: {titulo or '(desconhecido)'}\nTraduza para {nome_do_idioma(self.idioma)} e devolva "
                      f"cada texto com o mesmo id.\nTextos do jogo:\n{json.dumps(itens, ensure_ascii=False)}")
            voltou = self._pedir(pedido)
            faltando = [i for i in lote if i not in voltou]
            if faltando:                                     # o que não voltou: pede de novo só esses
                itens = [x for x in itens if x["id"] in faltando]
                voltou.update(self._pedir(pedido.rsplit("\n", 1)[0] + "\n" + json.dumps(itens, ensure_ascii=False)))
            for i in lote:
                if i not in voltou:
                    raise ErroTraducao(f"{len([j for j in lote if j not in voltou])} texto(s) não voltaram do Gemini")
                resultado[i] = voltou[i]
            if ao_progresso:
                ao_progresso(min(len(fazer), inicio + len(lote)), len(fazer))
        return resultado

    def encurtar(self, textos: dict[int, str], limites: dict[int, int]) -> dict[int, str]:
        from .roteiro_jogo import _ENCURTAR
        saida: dict[int, str] = {}
        itens = list(textos.items())
        for inicio in range(0, len(itens), LINHAS_POR_PEDIDO):
            lote = itens[inicio:inicio + LINHAS_POR_PEDIDO]
            saida.update(self._pedir(_ENCURTAR + "\n" + json.dumps(
                [{"id": i, "texto": t, "max": limites[i]} for i, t in lote], ensure_ascii=False)))
        return saida
