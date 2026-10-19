"""A janela "🤖 Automático" do modo "Traduzir e dublar (no PC)" da aba 🎮 Jogos: as etapas que ainda faltam neste jogo
(ouvir as falas sem texto, traduzir, dublar, entregar, montar a ISO), quem faz cada uma, o custo e o tempo estimado
pela velocidade deste PC; o total marcado e a que horas termina. "▶ Fazer tudo" faz as marcadas uma depois da outra
(o "Parar" da janela principal interrompe; o que ficou pronto é guardado e não é feito de novo).
"""

from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

from jellyfin_tools import tempo_jogo as tj

from .gui_moderna import Tema


class JanelaAutomaticoJogo(ctk.CTkToplevel):
    """fazer(marcadas): começa as etapas marcadas (["traduzir", "dublar", ...])."""

    def __init__(self, pai, jogo: str, etapas: list, fazer):
        super().__init__(pai)
        self.title(f"Automático · {jogo}")
        self.configure(fg_color=Tema.CARTAO)
        self.geometry("1060x480")
        self.transient(pai)
        self.etapas, self._fazer = etapas, fazer
        m = pai
        pequeno = ctk.CTkFont(Tema.FAMILIA, 11)
        m._rotulo(self, f"🤖 Automático · {jogo}", suave=False, fonte=m.f_secao).pack(anchor="w", padx=20,
                                                                                       pady=(16, 0))
        m._rotulo(self, "O Maestro faz as etapas marcadas uma depois da outra: pode deixar o PC trabalhando. O tempo "
                        "é o deste PC (medido nos jogos anteriores) ou, na 1ª vez, uma média.",
                  fonte=pequeno).pack(anchor="w", padx=20, pady=(0, 10))
        grade = ctk.CTkFrame(self, fg_color=Tema.CAMPO, corner_radius=Tema.RAIO_CONTROLE)
        grade.pack(fill="both", expand=True, padx=20)
        grade.grid_columnconfigure(1, weight=1)
        for coluna, titulo in enumerate(("", "Etapa", "Quem faz", "Custo", "Tempo")):
            m._rotulo(grade, titulo, suave=False).grid(row=0, column=coluna, sticky="w", padx=12, pady=(10, 4))
        self.marcar: dict[str, tk.BooleanVar] = {}
        self.caixas: dict[str, ctk.CTkCheckBox] = {}
        for i, e in enumerate(etapas, start=1):
            var = tk.BooleanVar(self, value=True)
            caixa = ctk.CTkCheckBox(grade, text="", variable=var, width=24, command=lambda c=e.chave: self._mudou(c),
                                    fg_color=Tema.PRIMARIA, hover_color=Tema.PRIMARIA_HOVER)
            caixa.grid(row=i, column=0, padx=(12, 0), pady=6)
            self.marcar[e.chave], self.caixas[e.chave] = var, caixa
            m._rotulo(grade, f"{e.nome}  ({e.tamanho()})", suave=False).grid(row=i, column=1, sticky="w", padx=12)
            m._rotulo(grade, e.quem).grid(row=i, column=2, sticky="w", padx=12)
            m._rotulo(grade, e.custo).grid(row=i, column=3, sticky="w", padx=12)
            m._rotulo(grade, "≈ " + tj.legivel(e.segundos) + ("" if e.medida_no_pc else " (média)")).grid(
                row=i, column=4, sticky="w", padx=12)
        self.lb_total = m._rotulo(self, "", suave=False)
        self.lb_total.pack(anchor="w", padx=20, pady=(10, 2))
        m._rotulo(self, "\"Parar\" (embaixo, na janela principal) interrompe; o que já ficou pronto é guardado e não é "
                        "feito de novo.", fonte=pequeno).pack(anchor="w", padx=20)
        botoes = ctk.CTkFrame(self, fg_color="transparent")
        botoes.pack(fill="x", padx=20, pady=12)
        m._botao(botoes, "Fechar", self.destroy, "fantasma").pack(side="right")
        self.bt_fazer = m._botao(botoes, "▶  Fazer tudo", self.fazer_tudo, "primario")
        self.bt_fazer.pack(side="right", padx=(0, 8))
        self._mostrar_total()

    def marcadas(self) -> list[str]:
        return [e.chave for e in self.etapas if self.marcar[e.chave].get()]

    def _mudou(self, chave: str) -> None:
        """Ouvir as falas sem texto é para traduzir: marcar ouvir marca traduzir; desmarcar traduzir desmarca ouvir."""
        if chave == "ouvir" and self.marcar["ouvir"].get() and "traduzir" in self.marcar:
            self.marcar["traduzir"].set(True)
        if chave == "traduzir" and not self.marcar["traduzir"].get() and "ouvir" in self.marcar:
            self.marcar["ouvir"].set(False)
        self._mostrar_total()

    def _mostrar_total(self) -> None:
        marcadas = self.marcadas()
        if not marcadas:
            self.lb_total.configure(text="Nada marcado.")
            self.bt_fazer.configure(state="disabled")
            return
        segundos = tj.total(self.etapas, marcadas)
        self.lb_total.configure(text=f"Total marcado: ≈ {tj.legivel(segundos)} · termina {tj.termina_as(segundos)} "
                                     "se começar agora")
        self.bt_fazer.configure(state="normal")

    def fazer_tudo(self) -> None:
        marcadas = self.marcadas()
        self.destroy()
        self._fazer(marcadas)
