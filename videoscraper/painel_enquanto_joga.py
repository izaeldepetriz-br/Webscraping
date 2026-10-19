"""Aba "🎮 Jogos", modo "Enquanto joga (tradutor de tela)" (como no protótipo aprovado): para qualquer jogo, por
cima da janela do emulador, sem mexer na ISO. Só a tela fica aqui; o trabalho fica em jellyfin_tools (tela_jogo,
legenda_ao_vivo) e a ligação com a janela em enquanto_joga_moderna.py.

    1. Janela do jogo    qual janela o Maestro olha (o PCSX2 aparece primeiro) e a prévia: a caixa roxa é a
                         janelinha do Maestro; o jogo continua igual por baixo
    2. Texto da tela     ligado/desligado, a área (a janela inteira ou a caixa de diálogo marcada), o atalho (F9),
                         quem traduz e "traduzir sozinho quando o texto mudar"
    3. Vozes ao vivo     a legenda das vozes (Whisper) e, experimental, a voz traduzida falando
"""

from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

from .gui_moderna import Tema

AREAS = ("Janela inteira", "Caixa de diálogo (marcada)")
TRADUTORES = ("Grátis no PC (Argos)", "Gemini Flash (chave grátis)", "Claude (pago)")
VOZES_AO_VIVO = ("XTTS-v2 (no PC)", "Gemini (pago)")
WHISPERS = ("turbo · placa de vídeo", "small · processador", "base · processador (mais rápido)")
TECLAS = tuple(f"F{n}" for n in range(1, 13))


class PainelEnquantoJoga(ctk.CTkScrollableFrame):
    """acoes: {'atualizar_janelas', 'janela', 'previa', 'tela', 'marcar', 'legenda', 'voz', 'traduzir_agora'}."""

    def __init__(self, pai, app, acoes: dict):
        super().__init__(pai, fg_color="transparent")
        self.app, self.acoes = app, acoes
        self.janelas: list = []
        self._imagem = None
        self._pequeno = ctk.CTkFont(Tema.FAMILIA, 11)
        self.grid_columnconfigure(0, weight=1)
        aviso = app._rotulo(self, "Só jogos para um jogador: em jogo online, um programa que lê a tela pode ser "
                                  "confundido com trapaça pelo anticheat.", fonte=self._pequeno)
        aviso.grid(row=0, column=0, sticky="w", padx=(28, 16), pady=(12, 0))
        self._montar_janela()
        self._montar_tela()
        self._montar_vozes()

    def _cartao(self, linha: int, titulo: str, dica: str) -> ctk.CTkFrame:
        m = self.app
        cartao = m._cartao(self)
        cartao.grid(row=linha, column=0, sticky="ew", padx=(28, 16), pady=(12, 0))
        cartao.grid_columnconfigure(0, weight=1)
        topo = ctk.CTkFrame(cartao, fg_color="transparent")
        topo.grid(row=0, column=0, sticky="ew", padx=20, pady=(12, 6))
        m._rotulo(topo, titulo, suave=False, fonte=m.f_secao).pack(side="left")
        m._rotulo(topo, "   " + dica, fonte=self._pequeno).pack(side="left", pady=(3, 0))
        return cartao

    def _faixa(self, cartao, linha: int, pady=(4, 4)) -> ctk.CTkFrame:
        faixa = ctk.CTkFrame(cartao, fg_color="transparent")
        faixa.grid(row=linha, column=0, sticky="ew", padx=20, pady=pady)
        return faixa

    def _interruptor(self, pai, texto: str, var: tk.BooleanVar, comando) -> ctk.CTkSwitch:
        return ctk.CTkSwitch(pai, text=texto, variable=var, command=comando, font=self.app.f_normal,
                             text_color=Tema.TEXTO, progress_color=Tema.PRIMARIA)

    def _montar_janela(self) -> None:
        m = self.app
        cartao = self._cartao(1, "1. Janela do jogo", "o Maestro olha só esta janela e põe a tradução por cima dela")
        faixa = self._faixa(cartao, 1)
        m._rotulo(faixa, "Janela:", suave=False).pack(side="left", padx=(0, 10))
        self.var_janela = tk.StringVar(self, value="")
        self.menu_janela = ctk.CTkOptionMenu(faixa, variable=self.var_janela, values=["(nenhuma janela)"], width=420,
                                             height=36, corner_radius=Tema.RAIO_CONTROLE, font=m.f_normal,
                                             fg_color=Tema.CAMPO, button_color=Tema.SECUNDARIA,
                                             button_hover_color=Tema.SECUNDARIA_HOVER, dropdown_fg_color=Tema.CARTAO,
                                             text_color=Tema.TEXTO, dynamic_resizing=False,
                                             command=lambda _: self.acoes["janela"]())
        self.menu_janela.pack(side="left")
        m._botao(faixa, "⟳", self.acoes["atualizar_janelas"], "fantasma", largura=44).pack(side="left", padx=(8, 0))
        m._botao(faixa, "Prévia", self.acoes["previa"], "fantasma", largura=90).pack(side="left", padx=(4, 0))
        self.lb_previa = ctk.CTkLabel(cartao, text="(abra o jogo no emulador e escolha a janela)", font=m.f_rotulo,
                                      text_color=Tema.TEXTO_FRACO, fg_color=Tema.CAMPO, corner_radius=8, height=240)
        self.lb_previa.grid(row=2, column=0, sticky="ew", padx=20, pady=(6, 2))
        m._rotulo(cartao, "Prévia: a caixa roxa é a janelinha do Maestro; o jogo continua igual por baixo.",
                  fonte=self._pequeno).grid(row=3, column=0, pady=(0, 14))

    def _montar_tela(self) -> None:
        m = self.app
        cartao = self._cartao(2, "2. Texto da tela", "lê o texto da imagem no seu PC (OCR) e manda ao tradutor só o "
                                                     "texto")
        faixa = self._faixa(cartao, 1)
        self.var_tela = tk.BooleanVar(self, value=False)
        self.sw_tela = self._interruptor(faixa, "Ligado", self.var_tela, self.acoes["tela"])
        self.sw_tela.pack(side="left")
        m._rotulo(faixa, "Área:", suave=False).pack(side="left", padx=(24, 8))
        self.var_area = tk.StringVar(self, value=AREAS[0])
        m._menu_opcoes(faixa, self.var_area, AREAS).pack(side="left")
        self.bt_marcar = m._botao(faixa, "✂  Marcar a área", self.acoes["marcar"], "fantasma")
        self.bt_marcar.pack(side="left", padx=(8, 0))
        m._rotulo(faixa, "Atalho:", suave=False).pack(side="left", padx=(16, 8))
        self.var_atalho = tk.StringVar(self, value="F9")
        m._menu_opcoes(faixa, self.var_atalho, TECLAS).pack(side="left")
        faixa2 = self._faixa(cartao, 2)
        m._rotulo(faixa2, "Quem traduz:", suave=False).pack(side="left", padx=(0, 8))
        self.var_tradutor = tk.StringVar(self, value=TRADUTORES[0])
        m._menu_opcoes(faixa2, self.var_tradutor, TRADUTORES).pack(side="left")
        self.var_sozinho = tk.BooleanVar(self, value=True)
        ctk.CTkCheckBox(faixa2, text="Traduzir sozinho quando o texto mudar", variable=self.var_sozinho,
                        font=m.f_normal, text_color=Tema.TEXTO, fg_color=Tema.PRIMARIA,
                        hover_color=Tema.PRIMARIA_HOVER, border_color=Tema.CAMPO_BORDA, checkbox_width=20,
                        checkbox_height=20, corner_radius=6, border_width=2).pack(side="left", padx=(18, 0))
        self.bt_agora = m._botao(faixa2, "Traduzir agora", self.acoes["traduzir_agora"], "fantasma")
        self.bt_agora.pack(side="left", padx=(12, 0))
        self.lb_custo_tela = m._rotulo(faixa2, "Frases repetidas saem da memória (sem pagar de novo)",
                                       fonte=self._pequeno)
        self.lb_custo_tela.pack(side="right")
        self.lb_tela = m._rotulo(cartao, "", fonte=self._pequeno)
        self.lb_tela.grid(row=3, column=0, sticky="w", padx=20, pady=(2, 14))
        self.var_tradutor.trace_add("write", lambda *_: self.mostrar_custo())
        self.mostrar_custo()

    def _montar_vozes(self) -> None:
        m = self.app
        cartao = self._cartao(3, "3. Vozes ao vivo (Whisper + tradução)", "o Whisper ouve o som do jogo na sua placa "
                                                                           "de vídeo; a tradução aparece embaixo")
        faixa = self._faixa(cartao, 1)
        self.var_legenda = tk.BooleanVar(self, value=False)
        self.sw_legenda = self._interruptor(faixa, "Legenda das vozes", self.var_legenda, self.acoes["legenda"])
        self.sw_legenda.pack(side="left")
        self.var_falar = tk.BooleanVar(self, value=False)
        self.sw_falar = self._interruptor(faixa, "Ler em voz alta (experimental)", self.var_falar, self.acoes["voz"])
        self.sw_falar.pack(side="left", padx=(24, 0))
        self.var_voz = tk.StringVar(self, value=VOZES_AO_VIVO[0])
        m._menu_opcoes(faixa, self.var_voz, VOZES_AO_VIVO).pack(side="left", padx=(8, 0))
        m._rotulo(faixa, "Whisper:", suave=False).pack(side="left", padx=(24, 8))
        self.var_whisper = tk.StringVar(self, value=WHISPERS[0])
        m._menu_opcoes(faixa, self.var_whisper, WHISPERS).pack(side="left")
        quadro = ctk.CTkFrame(cartao, fg_color=Tema.CAMPO, corner_radius=Tema.RAIO_CONTROLE)
        quadro.grid(row=2, column=0, sticky="ew", padx=20, pady=(6, 4))
        for i, (rotulo, texto, cor) in enumerate((
                ("Atraso", "legenda ≈ 1 s depois da fala · voz traduzida ≈ 2 a 3 s depois (por isso é experimental)",
                 Tema.TEXTO),
                ("Volume", "com a voz ligada, o som do jogo fica baixinho por baixo (não some: está misturado na "
                           "trilha); o Maestro não ouve a própria voz", Tema.AVISO))):
            ctk.CTkLabel(quadro, text=rotulo, font=self._pequeno, text_color=Tema.TEXTO_SUAVE, width=80,
                         anchor="w").grid(row=i, column=0, sticky="w", padx=(14, 6), pady=4)
            ctk.CTkLabel(quadro, text=texto, font=m.f_rotulo, text_color=cor, anchor="w", justify="left",
                         wraplength=900).grid(row=i, column=1, sticky="w", padx=(0, 14), pady=4)
        self.lb_vozes = m._rotulo(cartao, "", fonte=self._pequeno)
        self.lb_vozes.grid(row=3, column=0, sticky="w", padx=20, pady=(2, 14))

    # ------------------------------------------------------------------ o que a tela mostra
    def mostrar_janelas(self, janelas: list) -> None:
        self.janelas = janelas
        titulos = [j.titulo[:70] for j in janelas] or ["(nenhuma janela)"]
        self.menu_janela.configure(values=titulos)
        if self.var_janela.get() not in titulos:
            self.var_janela.set(titulos[0])

    def janela_escolhida(self):
        titulo = self.var_janela.get()
        return next((j for j in self.janelas if j.titulo[:70] == titulo), None)

    def mostrar_previa(self, imagem) -> None:
        """imagem: PIL.Image já com a caixa roxa desenhada (ou None)."""
        if imagem is None:
            self.lb_previa.configure(image=None, text="(não deu para fotografar a janela)")
            return
        largura = 760
        altura = int(imagem.height * largura / max(1, imagem.width))
        self._imagem = ctk.CTkImage(light_image=imagem, dark_image=imagem, size=(largura, min(altura, 430)))
        self.lb_previa.configure(image=self._imagem, text="", height=min(altura, 430))

    def mostrar_custo(self) -> None:
        tradutor = self.var_tradutor.get()
        extra = {"Claude (pago)": "≈ US$ 0,01 a 0,15 por hora de jogo", "Gemini Flash (chave grátis)":
                 "grátis com a chave grátis", "Grátis no PC (Argos)": "grátis, no PC"}[tradutor]
        self.lb_custo_tela.configure(text=f"Frases repetidas saem da memória (sem pagar de novo) · {extra}")

    def mostrar_estado_tela(self, texto: str, ok: bool = True) -> None:
        self.lb_tela.configure(text=texto, text_color=Tema.SUCESSO if ok else Tema.AVISO)

    def mostrar_estado_vozes(self, texto: str, ok: bool = True) -> None:
        self.lb_vozes.configure(text=texto, text_color=Tema.SUCESSO if ok else Tema.AVISO)
