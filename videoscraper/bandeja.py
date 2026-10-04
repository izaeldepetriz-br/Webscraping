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
    """Um círculo roxo com um 'play' branco (as cores do programa)."""
    from PIL import Image, ImageDraw
    imagem = Image.new("RGBA", (tamanho, tamanho), (0, 0, 0, 0))
    desenho = ImageDraw.Draw(imagem)
    desenho.ellipse((2, 2, tamanho - 2, tamanho - 2), fill=(124, 92, 255, 255))
    t = tamanho
    desenho.polygon([(t * 0.40, t * 0.28), (t * 0.40, t * 0.72), (t * 0.74, t * 0.50)], fill=(255, 255, 255, 255))
    return imagem


class Bandeja:
    """pedir(acao): põe "abrir" ou "sair" na fila do programa (a janela atende)."""

    def __init__(self, pedir, titulo: str = "videoscraper", fabrica=None):
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
