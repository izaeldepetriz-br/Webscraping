"""Ícone perto do relógio (bandeja do sistema): o programa some da barra de tarefas, mas continua
rodando a vigia e a conferência dos espelhos. Clique com o botão direito: Abrir / Sair.

O pystray chama os itens do menu na thread DELE; a janela (Tk) só pode ser mexida na thread dela.
Por isso o ícone só põe um pedido na fila do programa, e a janela atende no próximo ciclo.
"""

from __future__ import annotations


def disponivel() -> bool:
    """No Windows sempre (vem dentro do .exe). Em outros sistemas depende do ambiente gráfico."""
    import importlib
    try:
        importlib.import_module("pystray")
        importlib.import_module("PIL.Image")
        return True
    except Exception:                          # no Linux sem GTK o pystray falha ao importar
        return False


def imagem_do_icone(tamanho: int = 64):
    """O ícone do Maestro (o "M" com a batuta), o mesmo da janela e do .exe."""
    from .icone import desenhar
    return desenhar(tamanho)


class Bandeja:
    """pedir(acao): põe "abrir" ou "sair" na fila do programa (a janela atende)."""

    def __init__(self, pedir, titulo: str = "Maestro", fabrica=None):
        self.pedir = pedir
        self.titulo = titulo
        self._fabrica = fabrica                 # testes: um ícone de mentira no lugar do pystray
        self.icone = None

    def mostrar(self) -> None:
        if self.icone is not None:
            return
        if self._fabrica is not None:
            self.icone = self._fabrica(self)
        else:
            import pystray
            menu = pystray.Menu(pystray.MenuItem("Abrir", lambda *_: self.pedir("abrir"), default=True),
                                pystray.MenuItem("Sair", lambda *_: self.pedir("sair")))
            self.icone = pystray.Icon("videoscraper", imagem_do_icone(), self.titulo, menu)
        self.icone.run_detached()

    def esconder(self) -> None:
        if self.icone is not None:
            try:
                self.icone.stop()
            except Exception:
                pass
            self.icone = None
