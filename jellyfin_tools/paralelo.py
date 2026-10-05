"""Fazer muitas consultas de rede ao mesmo tempo, com um "Parar" que vale NA HORA.

O jeito simples (executor.map) só devolve quando TODOS terminam: com 11 mil canais e o botão Parar
apertado, ele seguia consultando até o fim. Aqui cada resultado é recolhido assim que chega e, se
parar() ficar verdadeiro, o que ainda está na fila é cancelado e a função volta na mesma hora (as poucas
consultas que já estavam em andamento terminam sozinhas em segundo plano, sem segurar ninguém).
"""

from __future__ import annotations

import queue
import threading
from time import monotonic


def em_paralelo(itens: list, funcao, trabalhadores: int = 16, ao_progresso=None, parar=None,
                intervalo: float = 0.2, prazo: float | None = None, ao_estourar=None) -> dict:
    """{índice: funcao(item)} dos que terminaram (todos, ou até o parar()). ao_progresso(feitos, total).

    Leve com listas enormes: os itens ficam numa fila simples e cada trabalhador pega o próximo
    (antes, 11 mil "tarefas" eram entregues de uma vez e cada espera passava por todas elas: só isso
    ocupava um núcleo do processador e deixava a janela lenta). O progresso sai no máximo a cada
    `intervalo` segundos.

    prazo (segundos): um item que passa disso deixa de ser esperado; o resultado dele é ao_estourar(item)
    (ou None) e outro trabalhador entra no lugar. A consulta presa termina sozinha em segundo plano
    (os trabalhadores são "daemon": nem o fechamento do programa espera por eles)."""
    resultado: dict = {}
    if not itens:
        return resultado
    trabalhadores = max(1, min(trabalhadores, len(itens)))
    fila: queue.Queue = queue.Queue()
    for par in enumerate(itens):
        fila.put(par)
    prontos: queue.Queue = queue.Queue()
    cancelado = threading.Event()
    trava = threading.Lock()
    rodando: dict = {}                       # índice -> quando começou
    abandonados: set = set()

    def trabalhar() -> None:
        while not cancelado.is_set():
            try:
                n, item = fila.get_nowait()
            except queue.Empty:
                return
            with trava:
                rodando[n] = monotonic()
            try:
                prontos.put((n, funcao(item), None))
            except BaseException as erro:                  # devolve o erro para quem chamou
                prontos.put((n, None, erro))
            with trava:
                rodando.pop(n, None)
                if n in abandonados:                       # passou do prazo: alguém já entrou no lugar
                    return

    def contratar() -> None:
        threading.Thread(target=trabalhar, daemon=True, name="em_paralelo").start()

    for _ in range(trabalhadores):
        contratar()
    ultimo_aviso = 0.0
    try:
        while len(resultado) < len(itens):
            novos = 0
            try:
                pacote = prontos.get(timeout=intervalo)
                while True:
                    n, valor, erro = pacote
                    if erro is not None:
                        raise erro
                    if n not in resultado:                 # o de um item abandonado não conta mais
                        resultado[n] = valor
                        novos += 1
                    pacote = prontos.get_nowait()
            except queue.Empty:
                pass
            if prazo:
                agora = monotonic()
                with trava:
                    estourados = [n for n, comeco in rodando.items()
                                  if agora - comeco > prazo and n not in abandonados and n not in resultado]
                    abandonados.update(estourados)
                for n in estourados:
                    resultado[n] = ao_estourar(itens[n]) if ao_estourar else None
                    novos += 1
                    contratar()                            # o preso fica para trás; outro segue a fila
            if parar and parar():
                break
            agora = monotonic()
            if ao_progresso and novos and (agora - ultimo_aviso >= intervalo or len(resultado) == len(itens)):
                ultimo_aviso = agora
                ao_progresso(len(resultado), len(itens))
    finally:
        cancelado.set()                                    # o Parar é imediato: ninguém pega mais nada
    return resultado


class prioridade_baixa:
    """Enquanto ativo, o programa roda com prioridade "abaixo do normal" no Windows: numa conferência longa,
    o resto do computador (navegador, vídeo...) continua fluindo. Em outros sistemas não faz nada.

        with prioridade_baixa():
            conferir_canais(...)
    """
    _ativos = 0
    _trava = threading.Lock()

    def __enter__(self):
        with self._trava:
            type(self)._ativos += 1
            if self._ativos == 1:
                self._mudar(0x00004000)          # BELOW_NORMAL_PRIORITY_CLASS
        return self

    def __exit__(self, *erro):
        with self._trava:
            type(self)._ativos -= 1
            if self._ativos == 0:
                self._mudar(0x00000020)          # NORMAL_PRIORITY_CLASS
        return False

    @staticmethod
    def _mudar(classe: int) -> None:
        import sys
        if sys.platform != "win32":
            return
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.SetPriorityClass(kernel32.GetCurrentProcess(), classe)
        except Exception:                        # sem permissão etc.: segue na prioridade normal
            pass
