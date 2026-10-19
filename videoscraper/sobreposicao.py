"""A janelinha do Maestro POR CIMA do jogo (modo "Enquanto joga" da aba 🎮 Jogos), como no protótipo: a caixa roxa
com a tradução do texto da tela e, embaixo, a legenda das vozes. Fica sempre na frente, um pouco transparente, e dá
para arrastar. O jogo continua igual por baixo (ela não mexe em nada dele).

E a "tesoura" de "✂ Marcar a área": uma tela escura por cima da janela do jogo, onde você arrasta um retângulo em
volta da caixa de diálogo (o Maestro lê só ali: mais rápido e sem ler o placar ou o menu).
"""

from __future__ import annotations

import tkinter as tk

from .gui_moderna import Tema

ROXO = "#8b5cf6"
FUNDO = "#140f24"


class Sobreposicao(tk.Toplevel):
    """mostrar_tela(texto) e mostrar_legenda(texto): o que aparece por cima do jogo."""

    def __init__(self, pai, largura: int = 760):
        super().__init__(pai)
        self.withdraw()
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        try:
            self.attributes("-alpha", 0.93)
        except tk.TclError:
            pass
        self.configure(bg=ROXO)
        corpo = tk.Frame(self, bg=FUNDO)
        corpo.pack(fill="both", expand=True, padx=2, pady=2)
        topo = tk.Frame(corpo, bg=FUNDO)
        topo.pack(fill="x", padx=12, pady=(8, 0))
        self.lb_titulo = tk.Label(topo, text="Maestro · tradução da tela", bg=FUNDO, fg="#c4b5fd",
                                  font=(Tema.FAMILIA, 10, "bold"))
        self.lb_titulo.pack(side="left")
        fechar = tk.Label(topo, text="×", bg=FUNDO, fg="#a1a1aa", font=(Tema.FAMILIA, 12, "bold"), cursor="hand2")
        fechar.pack(side="right")
        fechar.bind("<Button-1>", lambda e: self.esconder())
        self.lb_tela = tk.Label(corpo, text="", bg=FUNDO, fg="#ffffff", font=(Tema.FAMILIA, 15), justify="left",
                                anchor="w", wraplength=largura)
        self.lb_tela.pack(fill="x", padx=12, pady=(2, 6))
        self.lb_legenda = tk.Label(corpo, text="", bg=FUNDO, fg="#fde68a", font=(Tema.FAMILIA, 14), justify="left",
                                   anchor="w", wraplength=largura)
        self._arrastando = (0, 0)
        for alvo in (self, corpo, topo, self.lb_titulo, self.lb_tela, self.lb_legenda):
            alvo.bind("<ButtonPress-1>", self._pegar, add="+")
            alvo.bind("<B1-Motion>", self._arrastar, add="+")
        self.movida = False

    def _pegar(self, evento) -> None:
        self._arrastando = (evento.x_root - self.winfo_x(), evento.y_root - self.winfo_y())

    def _arrastar(self, evento) -> None:
        dx, dy = self._arrastando
        self.geometry(f"+{evento.x_root - dx}+{evento.y_root - dy}")
        self.movida = True

    def posicionar(self, retangulo: tuple) -> None:
        """Embaixo, no meio da janela do jogo (até você arrastar para outro lugar)."""
        if self.movida:
            return
        esquerda, topo, direita, baixo = retangulo
        self.update_idletasks()
        largura, altura = max(self.winfo_reqwidth(), 300), max(self.winfo_reqheight(), 60)
        x = esquerda + max(0, (direita - esquerda - largura) // 2)
        y = max(topo, baixo - altura - max(40, (baixo - topo) // 5))
        self.geometry(f"+{x}+{y}")

    def mostrar_tela(self, texto: str) -> None:
        self.lb_titulo.configure(text="Maestro · tradução da tela")
        self.lb_tela.configure(text=texto)
        self._aparecer()

    def mostrar_legenda(self, texto: str) -> None:
        if not self.lb_legenda.winfo_ismapped():
            self.lb_legenda.pack(fill="x", padx=12, pady=(0, 10))
        self.lb_legenda.configure(text=texto)
        if not self.lb_tela.cget("text"):
            self.lb_titulo.configure(text="Maestro · legenda das vozes")
        self._aparecer()

    def _aparecer(self) -> None:
        self.deiconify()
        self.lift()
        self.attributes("-topmost", True)

    def esconder(self) -> None:
        self.withdraw()


class MarcarArea(tk.Toplevel):
    """Uma tela escura por cima da janela do jogo: arraste em volta da caixa de diálogo. resultado: (esquerda,
    topo, direita, baixo) relativo à janela, ou None (Esc)."""

    def __init__(self, pai, retangulo: tuple):
        super().__init__(pai)
        self.resultado: tuple | None = None
        esquerda, topo, direita, baixo = retangulo
        self.origem = (esquerda, topo)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        try:
            self.attributes("-alpha", 0.35)
        except tk.TclError:
            pass
        self.geometry(f"{direita - esquerda}x{baixo - topo}+{esquerda}+{topo}")
        self.tela = tk.Canvas(self, bg="#000000", highlightthickness=0, cursor="crosshair")
        self.tela.pack(fill="both", expand=True)
        self.tela.create_text((direita - esquerda) // 2, 30, text="Arraste em volta da caixa de diálogo do jogo  ·  "
                                                                 "Esc: cancelar", fill="#ffffff",
                              font=(Tema.FAMILIA, 14, "bold"))
        self._inicio = None
        self._retangulo = None
        self.tela.bind("<ButtonPress-1>", self._comecar)
        self.tela.bind("<B1-Motion>", self._mover)
        self.tela.bind("<ButtonRelease-1>", self._soltar)
        self.bind("<Escape>", lambda e: self.destroy())
        self.focus_force()

    def _comecar(self, evento) -> None:
        self._inicio = (evento.x, evento.y)
        self._retangulo = self.tela.create_rectangle(evento.x, evento.y, evento.x, evento.y, outline=ROXO, width=3)

    def _mover(self, evento) -> None:
        if self._inicio:
            self.tela.coords(self._retangulo, *self._inicio, evento.x, evento.y)

    def _soltar(self, evento) -> None:
        if self._inicio:
            x0, y0 = self._inicio
            area = (min(x0, evento.x), min(y0, evento.y), max(x0, evento.x), max(y0, evento.y))
            if area[2] - area[0] > 20 and area[3] - area[1] > 10:
                self.resultado = area
        self.destroy()
