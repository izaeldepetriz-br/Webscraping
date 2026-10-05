"""Fazer muitas consultas de rede ao mesmo tempo, com um "Parar" que vale NA HORA.

O jeito simples (executor.map) só devolve quando TODOS terminam: com 11 mil canais e o botão Parar
apertado, ele seguia consultando até o fim. Aqui cada resultado é recolhido assim que chega e, se
parar() ficar verdadeiro, o que ainda está na fila é cancelado e a função volta na mesma hora (as poucas
consultas que já estavam em andamento terminam sozinhas em segundo plano, sem segurar ninguém).
"""

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait


def em_paralelo(itens: list, funcao, trabalhadores: int = 16, ao_progresso=None, parar=None,
                intervalo: float = 0.2) -> dict:
    """{índice: funcao(item)} dos que terminaram (todos, ou até o parar()). ao_progresso(feitos, total)."""
    resultado: dict = {}
    if not itens:
        return resultado
    executor = ThreadPoolExecutor(max_workers=max(1, min(trabalhadores, len(itens))))
    pendentes = {executor.submit(funcao, item): n for n, item in enumerate(itens)}
    try:
        while pendentes:
            prontos, _ = wait(pendentes, timeout=intervalo, return_when=FIRST_COMPLETED)
            for futuro in prontos:
                resultado[pendentes.pop(futuro)] = futuro.result()
                if ao_progresso:
                    ao_progresso(len(resultado), len(itens))
            if parar and parar():
                break
    finally:
        executor.shutdown(wait=False, cancel_futures=True)        # não espera: o Parar é imediato
    return resultado
