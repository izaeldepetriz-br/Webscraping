"""Adaptar a fala da DUBLAGEM ao tempo da cena, do jeito que um tradutor de dublagem faz.

    Legenda (2 s na tela): "Eu não acredito que você fez isso comigo depois de tudo."
    A voz leva 3,1 s para ler isso: não cabe.
    Adaptada (até 33 letras):  "Não acredito que fez isso comigo."   -> cabe, sem acelerar

Só as falas que NÃO cabem vão para o Claude (as outras ficam como na legenda). Ele reescreve cada uma mais curta,
fiel ao sentido e ao tom e no português falado do Brasil. A legenda e o vídeo não mudam: a frase adaptada é só o
que a voz lê. Se a API falhar, a dublagem segue do jeito antigo (acelera um pouco e, se precisar, corta).
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from .traducao import _ESQUEMA, ErroTraducao, Tradutor, _explicar, ler_resposta

NATURAL = 1.12              # até 12% mais rápida ninguém percebe: não precisa reescrever
POR_PEDIDO = 60             # falas por pedido à API
MINIMO_LETRAS = 4

_SISTEMA = """Você é um adaptador de texto para DUBLAGEM em português do Brasil, como os de estúdio.
Cada fala vai ser lida em voz alta e precisa caber no tempo da cena. Reescreva cada fala recebida:
- Com no máximo o número de letras do campo "max" (contando espaços).
- Fiel ao sentido e ao tom da fala: não invente, não acrescente informação, não mude quem fala com quem.
- Do jeito que um brasileiro diria naturalmente em voz alta, como numa boa dublagem de filme. Pode usar formas
  faladas como "pra" e "tá" quando combinarem com o tom; não use gírias que a fala não tem.
- Corte primeiro o que é dispensável para entender (repetições, "você" óbvio, "então", "bem").
- Mantenha nomes de pessoas, lugares e marcas.
- Se não der para chegar ao limite sem perder o sentido, devolva a versão mais curta que mantenha o sentido.
- Use a fala anterior (campo "antes") só como contexto.
Devolva TODAS as falas recebidas, cada uma com o MESMO id, sem comentários."""


def limite_de_letras(texto: str, duracao: float, vaga: float) -> int:
    """Quantas letras cabem: o texto encolhe na mesma proporção que o áudio precisa encolher (com 5% de folga)."""
    return max(MINIMO_LETRAS, int(len(texto) * vaga / duracao * 0.95)) if duracao > 0 else len(texto)


@dataclass
class Adaptador:
    """Usa o mesmo cliente, modelo e contagem de custo do Tradutor (a mesma chave da Anthropic)."""
    tradutor: Tradutor
    titulo: str = ""

    def __call__(self, itens: list[tuple[int, str, int, str]]) -> dict[int, str]:
        """itens: [(id, texto, máximo de letras, fala anterior)]. Devolve {id: texto adaptado} (só as que voltaram
        MAIS CURTAS que a original: o resto continua como estava)."""
        resultado = {}
        for inicio in range(0, len(itens), POR_PEDIDO):
            lote = itens[inicio:inicio + POR_PEDIDO]
            for i, novo in self._pedir(lote).items():
                original = next(t for k, t, _, _ in lote if k == i)
                novo = " ".join(novo.split())
                if novo and len(novo) < len(original):
                    resultado[i] = novo
        return resultado

    def _pedir(self, lote: list[tuple[int, str, int, str]]) -> dict[int, str]:
        falas = [{"id": i, "texto": t, "max": m, **({"antes": a} if a else {})} for i, t, m, a in lote]
        pedido = (f"Filme: {self.titulo or '(desconhecido)'}\n\nAdapte cada fala para caber no limite de letras.\n"
                  f"Falas:\n{json.dumps(falas, ensure_ascii=False)}")
        self.tradutor.conferir_teto()
        try:
            resposta = self.tradutor.cliente.messages.create(
                model=self.tradutor.modelo, max_tokens=8000, system=self.tradutor.sistema(_SISTEMA),
                messages=[{"role": "user", "content": pedido}],
                output_config={"format": {"type": "json_schema", "schema": _ESQUEMA}})
        except Exception as erro:
            raise ErroTraducao(_explicar(erro)) from erro
        self.tradutor.contar(resposta)
        if resposta.stop_reason == "refusal":
            raise ErroTraducao("o modelo recusou adaptar um trecho")
        return ler_resposta(resposta)
