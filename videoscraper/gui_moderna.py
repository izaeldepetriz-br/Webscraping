"""Interface moderna (Dark Mode) do videoscraper, feita com CustomTkinter.

Este arquivo é SÓ a camada visual (a "View"):
  - monta a janela, os cartões, os botões e a tabela;
  - oferece métodos para o motor atualizar a tela (adicionar_video, escrever_log, definir_status...);
  - os cliques dos botões chamam métodos "placeholder" (ao_buscar, ao_baixar_todos...) que
    aqui só têm `pass`. Quem dá vida a eles é uma subclasse (ver app_moderna.py), que herda
    esta janela e sobrescreve esses métodos com o motor de scraping.

Rodar só a interface (sem motor, com dados de exemplo):
    python -m videoscraper.gui_moderna
"""

from __future__ import annotations

import sys
import tkinter as tk
from dataclasses import dataclass
from tkinter import filedialog, ttk

import customtkinter as ctk


# =============================================================================== tema
class Tema:
    """Paleta e tipografia num só lugar: mudar a cara do app = mudar só aqui."""

    FUNDO = "#0d0f14"           # fundo da janela
    CARTAO = "#151821"          # cartões (painéis)
    CARTAO_BORDA = "#232836"
    CAMPO = "#1b1f2a"           # campos de texto
    CAMPO_BORDA = "#2b3142"
    CAMPO_FOCO = "#7c5cff"
    TEXTO = "#e7e9f0"
    TEXTO_SUAVE = "#8e96ab"
    TEXTO_FRACO = "#5d6578"
    PRIMARIA = "#7c5cff"        # ação principal (CTA)
    PRIMARIA_HOVER = "#6a48f5"
    SECUNDARIA = "#232836"
    SECUNDARIA_HOVER = "#2d3344"
    SUCESSO = "#22c55e"
    AVISO = "#f5a524"
    PERIGO = "#f05252"
    PERIGO_HOVER = "#2a1618"
    CONSOLE = "#0a0c10"
    LINHA_PAR = "#151821"
    LINHA_IMPAR = "#181c26"
    SELECAO = "#2e2754"

    RAIO = 14                   # cantos arredondados dos cartões
    RAIO_CONTROLE = 10          # cantos de botões e campos
    ESPACO = 16                 # espaçamento padrão

    if sys.platform.startswith("win"):
        FAMILIA, MONO = "Segoe UI", "Cascadia Mono"
    elif sys.platform == "darwin":
        FAMILIA, MONO = "Helvetica Neue", "Menlo"
    else:
        FAMILIA, MONO = "Roboto", "DejaVu Sans Mono"


@dataclass
class OpcoesInterface:
    """Tudo o que o usuário escolheu no painel de opções."""
    navegador: bool
    visivel: bool
    pausar: bool
    seletor: str
    profundidade: int
    max_paginas: int
    limite: int
    espera: float
    pasta: str


# =============================================================================== componentes
class CampoNumerico(ctk.CTkFrame):
    """Seletor numérico moderno ( -  [ valor ]  + ). O CustomTkinter não tem Spinbox."""

    def __init__(self, master, valor: float, minimo: float, maximo: float, passo: float = 1,
                 decimal: bool = False, largura: int = 120):
        super().__init__(master, fg_color=Tema.CAMPO, corner_radius=Tema.RAIO_CONTROLE,
                         border_width=1, border_color=Tema.CAMPO_BORDA, width=largura, height=38)
        self.minimo, self.maximo, self.passo, self.decimal = minimo, maximo, passo, decimal
        self.var = tk.StringVar(value=self._formatar(valor))
        fonte = ctk.CTkFont(Tema.FAMILIA, 13)
        estilo_botao = dict(width=30, height=30, corner_radius=8, fg_color="transparent",
                            hover_color=Tema.SECUNDARIA_HOVER, text_color=Tema.TEXTO_SUAVE,
                            font=ctk.CTkFont(Tema.FAMILIA, 16, "bold"))
        ctk.CTkButton(self, text="-", command=lambda: self._somar(-1), **estilo_botao).pack(side="left", padx=(4, 0))
        self.entrada = ctk.CTkEntry(self, textvariable=self.var, width=largura - 72, height=30, border_width=0,
                                    fg_color=Tema.CAMPO, text_color=Tema.TEXTO, font=fonte, justify="center")
        self.entrada.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(self, text="+", command=lambda: self._somar(1), **estilo_botao).pack(side="left", padx=(0, 4))
        self.entrada.bind("<FocusOut>", lambda e: self.set(self.get()))
        self.entrada.bind("<Up>", lambda e: self._somar(1))
        self.entrada.bind("<Down>", lambda e: self._somar(-1))

    def _formatar(self, valor: float) -> str:
        return f"{valor:.1f}" if self.decimal else str(int(valor))

    def _somar(self, sinal: int) -> None:
        self.set(self.get() + sinal * self.passo)

    def get(self) -> float:
        try:
            valor = float(self.var.get().replace(",", "."))
        except ValueError:
            valor = self.minimo
        valor = min(max(valor, self.minimo), self.maximo)
        return valor if self.decimal else int(valor)

    def set(self, valor: float) -> None:
        self.var.set(self._formatar(min(max(valor, self.minimo), self.maximo)))


class DialogoModerno(ctk.CTkToplevel):
    """Caixa de mensagem escura (substitui o messagebox cinza do Windows)."""

    CORES = {"info": Tema.PRIMARIA, "aviso": Tema.AVISO, "erro": Tema.PERIGO, "sucesso": Tema.SUCESSO}

    def __init__(self, master, titulo: str, mensagem: str, tipo: str = "info", pergunta: bool = False):
        super().__init__(master, fg_color=Tema.CARTAO)
        self.resposta = False
        self.title(titulo)
        self.resizable(False, False)
        self.transient(master)

        faixa = ctk.CTkFrame(self, fg_color=self.CORES.get(tipo, Tema.PRIMARIA), height=4, corner_radius=0)
        faixa.pack(fill="x")
        corpo = ctk.CTkFrame(self, fg_color="transparent")
        corpo.pack(fill="both", expand=True, padx=28, pady=(22, 10))
        ctk.CTkLabel(corpo, text=titulo, font=ctk.CTkFont(Tema.FAMILIA, 17, "bold"),
                     text_color=Tema.TEXTO, anchor="w").pack(fill="x")
        ctk.CTkLabel(corpo, text=mensagem, font=ctk.CTkFont(Tema.FAMILIA, 13), text_color=Tema.TEXTO_SUAVE,
                     justify="left", anchor="w", wraplength=460).pack(fill="x", pady=(10, 0))

        botoes = ctk.CTkFrame(self, fg_color="transparent")
        botoes.pack(fill="x", padx=28, pady=(8, 22))
        ctk.CTkButton(botoes, text="OK" if not pergunta else "Continuar", width=110, height=38,
                      corner_radius=Tema.RAIO_CONTROLE, fg_color=Tema.PRIMARIA, hover_color=Tema.PRIMARIA_HOVER,
                      font=ctk.CTkFont(Tema.FAMILIA, 13, "bold"), command=self._sim).pack(side="right")
        if pergunta:
            ctk.CTkButton(botoes, text="Cancelar", width=110, height=38, corner_radius=Tema.RAIO_CONTROLE,
                          fg_color=Tema.SECUNDARIA, hover_color=Tema.SECUNDARIA_HOVER,
                          font=ctk.CTkFont(Tema.FAMILIA, 13), command=self.destroy).pack(side="right", padx=(0, 10))
        self.bind("<Return>", lambda e: self._sim())
        self.bind("<Escape>", lambda e: self.destroy())

        self.update_idletasks()     # centraliza sobre a janela principal
        x = master.winfo_rootx() + (master.winfo_width() - self.winfo_reqwidth()) // 2
        y = master.winfo_rooty() + (master.winfo_height() - self.winfo_reqheight()) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        try:
            self.grab_set()         # modal: bloqueia a janela de trás até responder
        except tk.TclError:
            pass

    def _sim(self) -> None:
        self.resposta = True
        self.destroy()


# =============================================================================== janela
class JanelaModerna(ctk.CTk):
    COLUNAS = (("n", "#", 48, False), ("status", "Situação", 110, False), ("titulo", "Título", 240, True),
               ("tipo", "Origem", 140, False), ("url", "Link", 420, True))
    # Linha tingida de leve + símbolo na coluna Situação (o Treeview não colore uma célula só).
    FUNDO_SITUACAO = {"ok": "#132519", "erro": "#2a1519", "pulado": "#2a2212"}
    SIMBOLO_SITUACAO = {"ok": "\u2713", "erro": "\u2715", "pulado": "\u21b7"}    # ✓ ✕ ↷

    def __init__(self, pasta_padrao: str = "videos_baixados"):
        ctk.set_appearance_mode("dark")
        super().__init__(fg_color=Tema.FUNDO)
        self.title("videoscraper - vídeos públicos")
        altura = min(900, max(700, self.winfo_screenheight() - 90))
        self.geometry(f"1320x{altura}")
        self.minsize(1100, 680)
        self._pasta_padrao = pasta_padrao
        self._ocupado = False

        self.f_titulo = ctk.CTkFont(Tema.FAMILIA, 26, "bold")
        self.f_sub = ctk.CTkFont(Tema.FAMILIA, 13)
        self.f_secao = ctk.CTkFont(Tema.FAMILIA, 14, "bold")
        self.f_rotulo = ctk.CTkFont(Tema.FAMILIA, 12)
        self.f_normal = ctk.CTkFont(Tema.FAMILIA, 13)
        self.f_botao = ctk.CTkFont(Tema.FAMILIA, 13, "bold")
        self.f_mono = ctk.CTkFont(Tema.MONO, 12)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)
        self._montar_cabecalho()
        self._montar_endereco()
        self._montar_acoes()
        self._montar_corpo()
        self._montar_rodape()
        self.definir_ocupado(False)
        self.campo_url.focus_set()

    # ------------------------------------------------------------------ fábrica de widgets
    def _cartao(self, master, **kw) -> ctk.CTkFrame:
        return ctk.CTkFrame(master, fg_color=Tema.CARTAO, corner_radius=Tema.RAIO, border_width=1,
                            border_color=Tema.CARTAO_BORDA, **kw)

    def _botao(self, master, texto, comando, tipo="secundario", largura=0) -> ctk.CTkButton:
        estilos = {
            "primario": dict(fg_color=Tema.PRIMARIA, hover_color=Tema.PRIMARIA_HOVER, text_color="#ffffff",
                             border_width=0),
            "secundario": dict(fg_color=Tema.SECUNDARIA, hover_color=Tema.SECUNDARIA_HOVER,
                               text_color=Tema.TEXTO, border_width=1, border_color=Tema.CAMPO_BORDA),
            "perigo": dict(fg_color="transparent", hover_color=Tema.PERIGO_HOVER, text_color=Tema.PERIGO,
                           border_width=1, border_color=Tema.PERIGO),
            "fantasma": dict(fg_color="transparent", hover_color=Tema.SECUNDARIA_HOVER,
                             text_color=Tema.TEXTO_SUAVE, border_width=0),
        }[tipo]
        return ctk.CTkButton(master, text=texto, command=comando, height=40, corner_radius=Tema.RAIO_CONTROLE,
                             font=self.f_botao if tipo == "primario" else self.f_normal,
                             text_color_disabled=Tema.TEXTO_FRACO, width=largura or 0, **estilos)

    def _entrada(self, master, var, dica="", altura=38) -> ctk.CTkEntry:
        e = ctk.CTkEntry(master, textvariable=var, placeholder_text=dica, height=altura,
                         corner_radius=Tema.RAIO_CONTROLE, border_width=1, fg_color=Tema.CAMPO,
                         border_color=Tema.CAMPO_BORDA, text_color=Tema.TEXTO,
                         placeholder_text_color=Tema.TEXTO_FRACO, font=self.f_normal)
        e.bind("<FocusIn>", lambda ev: e.configure(border_color=Tema.CAMPO_FOCO))
        e.bind("<FocusOut>", lambda ev: e.configure(border_color=Tema.CAMPO_BORDA))
        return e

    def _rotulo(self, master, texto, suave=True, fonte=None) -> ctk.CTkLabel:
        return ctk.CTkLabel(master, text=texto, anchor="w", font=fonte or self.f_rotulo,
                            text_color=Tema.TEXTO_SUAVE if suave else Tema.TEXTO)

    # ------------------------------------------------------------------ 1. cabeçalho e endereço
    def _montar_cabecalho(self) -> None:
        topo = ctk.CTkFrame(self, fg_color="transparent")
        topo.grid(row=0, column=0, sticky="ew", padx=28, pady=(18, 0))
        ctk.CTkLabel(topo, text="Extrair e baixar vídeos públicos", font=self.f_titulo,
                     text_color=Tema.TEXTO, anchor="w").pack(anchor="w")
        ctk.CTkLabel(topo, font=self.f_sub, text_color=Tema.TEXTO_SUAVE, anchor="w",
                     text="1) Cole o endereço da página    2) Clique em Buscar vídeos    "
                          "3) Selecione e clique em Baixar").pack(anchor="w", pady=(2, 0))

    def _montar_endereco(self) -> None:
        cartao = self._cartao(self)
        cartao.grid(row=1, column=0, sticky="ew", padx=28, pady=(14, 0))
        cartao.grid_columnconfigure(1, weight=1)
        self._rotulo(cartao, "Endereço da página:", suave=False, fonte=self.f_secao).grid(
            row=0, column=0, padx=(20, 12), pady=18)
        self.var_url = tk.StringVar()
        self.campo_url = self._entrada(cartao, self.var_url, "https://site.com/videos", altura=44)
        self.campo_url.grid(row=0, column=1, sticky="ew", pady=18)
        self.campo_url.bind("<Return>", lambda e: self.ao_buscar())
        self.bt_colar = self._botao(cartao, "Colar", self.ao_colar, largura=96)
        self.bt_colar.grid(row=0, column=2, padx=(10, 20), pady=18)

    # ------------------------------------------------------------------ 3. barra de comandos
    def _montar_acoes(self) -> None:
        barra = ctk.CTkFrame(self, fg_color="transparent")
        barra.grid(row=2, column=0, sticky="ew", padx=28, pady=12)
        self.bt_buscar = self._botao(barra, "Buscar vídeos", self.ao_buscar, "primario", largura=170)
        self.bt_baixar_sel = self._botao(barra, "Baixar selecionados", self.ao_baixar_selecionados, largura=170)
        self.bt_baixar_todos = self._botao(barra, "Baixar todos", self.ao_baixar_todos, largura=130)
        self.bt_login = self._botao(barra, "Fazer login no site", self.ao_fazer_login, largura=160)
        self.bt_parar = self._botao(barra, "Parar", self.ao_parar, "perigo", largura=100)
        for b in (self.bt_buscar, self.bt_baixar_sel, self.bt_baixar_todos, self.bt_login):
            b.pack(side="left", padx=(0, 10))
        self.bt_parar.pack(side="right")

    # ------------------------------------------------------------------ corpo: opções + vídeos + log
    def _montar_corpo(self) -> None:
        corpo = ctk.CTkFrame(self, fg_color="transparent")
        corpo.grid(row=3, column=0, sticky="nsew", padx=28)
        corpo.grid_columnconfigure(1, weight=1)
        corpo.grid_rowconfigure(0, weight=3)
        corpo.grid_rowconfigure(1, weight=2)
        self._montar_opcoes(corpo)
        self._montar_tabela(corpo)
        self._montar_log(corpo)

    # 2. painel de opções (cartão lateral; rola se a tela for baixa)
    def _montar_opcoes(self, corpo) -> None:
        lateral = ctk.CTkScrollableFrame(corpo, width=320, fg_color=Tema.CARTAO, corner_radius=Tema.RAIO,
                                         border_width=1, border_color=Tema.CARTAO_BORDA,
                                         scrollbar_button_color=Tema.CARTAO_BORDA,
                                         scrollbar_button_hover_color=Tema.CAMPO_BORDA)
        lateral.grid(row=0, column=0, rowspan=2, sticky="nsw", padx=(0, 14))
        p = dict(padx=18)

        self._rotulo(lateral, "Opções", suave=False, fonte=self.f_secao).pack(anchor="w", pady=(12, 4), **p)
        self.var_nav = tk.BooleanVar(value=False)
        self.var_visivel = tk.BooleanVar(value=False)
        self.var_pausar = tk.BooleanVar(value=False)
        for texto, var in (("Usar navegador (sites com\nJavaScript ou login)", self.var_nav),
                           ("Mostrar a janela do navegador", self.var_visivel),
                           ("Pausar para eu resolver verificações", self.var_pausar)):
            ctk.CTkCheckBox(lateral, text=texto, variable=var, command=self._ajustar_checks,
                            font=self.f_normal, text_color=Tema.TEXTO, fg_color=Tema.PRIMARIA,
                            hover_color=Tema.PRIMARIA_HOVER, border_color=Tema.CAMPO_BORDA,
                            checkbox_width=20, checkbox_height=20, corner_radius=6, border_width=2
                            ).pack(anchor="w", pady=4, **p)

        self._separador(lateral)
        self._rotulo(lateral, "Parâmetros", suave=False, fonte=self.f_secao).pack(anchor="w", pady=(0, 6), **p)
        self._rotulo(lateral, "Seletor CSS (opcional):").pack(anchor="w", **p)
        self.var_seletor = tk.StringVar()
        self._entrada(lateral, self.var_seletor, "ex.: a.video-link").pack(fill="x", pady=(4, 10), **p)

        self.campo_prof = self._numero(lateral, "Seguir links (níveis):", 0, 0, 5, 1)
        self.campo_maxp = self._numero(lateral, "Máx. de páginas:", 30, 1, 300, 1)
        self.campo_limite = self._numero(lateral, "Máx. de vídeos (0 = todos):", 0, 0, 1000, 1)
        self.campo_espera = self._numero(lateral, "Espera entre pedidos (s):", 1.5, 0.5, 10, 0.5, True)

        self._separador(lateral)
        self._rotulo(lateral, "Salvar vídeos em:", suave=False, fonte=self.f_secao).pack(anchor="w", pady=(0, 6), **p)
        self.var_pasta = tk.StringVar(value=self._pasta_padrao)
        self._entrada(lateral, self.var_pasta).pack(fill="x", **p)
        self.bt_escolher = self._botao(lateral, "Escolher...", self.ao_escolher_pasta)
        self.bt_escolher.pack(fill="x", pady=(8, 14), **p)

    def _numero(self, master, texto, valor, minimo, maximo, passo, decimal=False):
        linha = ctk.CTkFrame(master, fg_color="transparent")
        linha.pack(fill="x", padx=18, pady=(0, 6))
        campo = CampoNumerico(linha, valor, minimo, maximo, passo, decimal, largura=112)
        campo.pack(side="right")
        self._rotulo(linha, texto).pack(side="left", fill="x", expand=True)
        return campo

    def _separador(self, master) -> None:
        ctk.CTkFrame(master, height=1, fg_color=Tema.CARTAO_BORDA).pack(fill="x", padx=18, pady=10)

    # 4. vídeos encontrados
    def _montar_tabela(self, corpo) -> None:
        cartao = self._cartao(corpo)
        cartao.grid(row=0, column=1, sticky="nsew", pady=(0, 14))
        cartao.grid_columnconfigure(0, weight=1)
        cartao.grid_rowconfigure(1, weight=1)

        topo = ctk.CTkFrame(cartao, fg_color="transparent")
        topo.grid(row=0, column=0, columnspan=2, sticky="ew", padx=18, pady=(14, 8))
        self._rotulo(topo, "Vídeos encontrados", suave=False, fonte=self.f_secao).pack(side="left")
        self.lb_contador = ctk.CTkLabel(topo, text="0", font=ctk.CTkFont(Tema.FAMILIA, 11, "bold"),
                                        fg_color=Tema.SECUNDARIA, text_color=Tema.TEXTO_SUAVE,
                                        corner_radius=10, width=34, height=22)
        self.lb_contador.pack(side="left", padx=10)

        self._estilizar_tabela()
        quadro = ctk.CTkFrame(cartao, fg_color=Tema.CARTAO, corner_radius=0)
        quadro.grid(row=1, column=0, sticky="nsew", padx=(18, 0))
        quadro.grid_columnconfigure(0, weight=1)
        quadro.grid_rowconfigure(0, weight=1)
        self.tabela = ttk.Treeview(quadro, columns=[c[0] for c in self.COLUNAS], show="headings",
                                   selectmode="extended", style="Moderno.Treeview")
        for chave, titulo, largura, estica in self.COLUNAS:
            self.tabela.heading(chave, text=titulo, anchor="w")
            self.tabela.column(chave, width=largura, minwidth=40, stretch=estica, anchor="w")
        self.tabela.grid(row=0, column=0, sticky="nsew")
        self.tabela.tag_configure("par", background=Tema.LINHA_PAR)
        self.tabela.tag_configure("impar", background=Tema.LINHA_IMPAR)
        for situacao, cor in self.FUNDO_SITUACAO.items():
            self.tabela.tag_configure(situacao, background=cor)
        self.tabela.bind("<Double-1>", lambda e: self.ao_abrir_link())
        rolagem = ctk.CTkScrollbar(cartao, command=self.tabela.yview, button_color=Tema.CARTAO_BORDA,
                                   button_hover_color=Tema.CAMPO_BORDA)
        rolagem.grid(row=1, column=1, sticky="ns", padx=(4, 10))
        self.tabela.configure(yscrollcommand=rolagem.set)

        self.lb_vazio = ctk.CTkLabel(quadro, text="Nenhum vídeo ainda. Cole um endereço e clique em Buscar vídeos.",
                                     font=self.f_normal, text_color=Tema.TEXTO_FRACO, fg_color=Tema.CARTAO)
        self.lb_vazio.place(relx=0.5, rely=0.55, anchor="center")

        acoes = ctk.CTkFrame(cartao, fg_color="transparent")
        acoes.grid(row=2, column=0, columnspan=2, sticky="ew", padx=18, pady=14)
        self.bt_abrir_link = self._botao(acoes, "Abrir link", self.ao_abrir_link, "fantasma")
        self.bt_copiar_link = self._botao(acoes, "Copiar link", self.ao_copiar_link, "fantasma")
        self.bt_salvar_lista = self._botao(acoes, "Salvar lista (CSV/JSON/TXT)...", self.ao_salvar_lista, "fantasma")
        self.bt_abrir_pasta = self._botao(acoes, "Abrir pasta dos vídeos", self.ao_abrir_pasta, "fantasma")
        for b in (self.bt_abrir_link, self.bt_copiar_link, self.bt_salvar_lista, self.bt_abrir_pasta):
            b.pack(side="left", padx=(0, 6))

    def _estilizar_tabela(self) -> None:
        """A tabela é um ttk.Treeview (o CustomTkinter não tem tabela) pintado no tema escuro."""
        estilo = ttk.Style(self)
        estilo.theme_use("clam")       # o único tema do ttk que aceita todas as cores
        estilo.configure("Moderno.Treeview", background=Tema.LINHA_PAR, fieldbackground=Tema.CARTAO,
                         foreground=Tema.TEXTO, rowheight=34, borderwidth=0, relief="flat",
                         font=(Tema.FAMILIA, 11))
        estilo.configure("Moderno.Treeview.Heading", background=Tema.CARTAO, foreground=Tema.TEXTO_FRACO,
                         relief="flat", borderwidth=0, padding=(6, 8), font=(Tema.FAMILIA, 10, "bold"))
        estilo.map("Moderno.Treeview.Heading", background=[("active", Tema.CARTAO)])
        estilo.map("Moderno.Treeview", background=[("selected", Tema.SELECAO)],
                   foreground=[("selected", "#ffffff")])
        estilo.layout("Moderno.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])   # sem borda

    # 5. console de logs
    def _montar_log(self, corpo) -> None:
        cartao = self._cartao(corpo)
        cartao.grid(row=1, column=1, sticky="nsew")
        cartao.grid_columnconfigure(0, weight=1)
        cartao.grid_rowconfigure(1, weight=1)
        topo = ctk.CTkFrame(cartao, fg_color="transparent")
        topo.grid(row=0, column=0, sticky="ew", padx=18, pady=(12, 6))
        for cor in ("#f05252", "#f5a524", "#22c55e"):        # "bolinhas" de janela de terminal
            ctk.CTkFrame(topo, width=10, height=10, corner_radius=5, fg_color=cor).pack(side="left", padx=(0, 6))
        self._rotulo(topo, "O que está acontecendo", suave=False, fonte=self.f_secao).pack(side="left", padx=(8, 0))
        self._botao(topo, "Limpar", self.limpar_log, "fantasma", largura=70).pack(side="right")

        self.log = ctk.CTkTextbox(cartao, fg_color=Tema.CONSOLE, text_color="#c9d1e3", font=self.f_mono,
                                  corner_radius=Tema.RAIO_CONTROLE, border_width=1, border_color=Tema.CARTAO_BORDA,
                                  scrollbar_button_color=Tema.CARTAO_BORDA, wrap="word")
        self.log.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 16))
        self.log.tag_config("erro", foreground=Tema.PERIGO)
        self.log.tag_config("ok", foreground=Tema.SUCESSO)
        self.log.tag_config("aviso", foreground=Tema.AVISO)
        self.log.configure(state="disabled")

    # ------------------------------------------------------------------ 5. rodapé
    def _montar_rodape(self) -> None:
        rodape = ctk.CTkFrame(self, fg_color=Tema.CARTAO, corner_radius=0, height=40, border_width=0)
        rodape.grid(row=4, column=0, sticky="ew", pady=(14, 0))
        self.indicador = ctk.CTkFrame(rodape, width=10, height=10, corner_radius=5, fg_color=Tema.SUCESSO)
        self.indicador.pack(side="left", padx=(28, 8), pady=14)
        self.var_status = tk.StringVar(value="Pronto.")
        ctk.CTkLabel(rodape, textvariable=self.var_status, font=self.f_rotulo,
                     text_color=Tema.TEXTO_SUAVE).pack(side="left")
        self.barra = ctk.CTkProgressBar(rodape, width=220, height=6, corner_radius=3, mode="determinate",
                                        fg_color=Tema.SECUNDARIA, progress_color=Tema.PRIMARIA)
        self.barra.pack(side="right", padx=28)
        self.barra.set(0)

    # ================================================================== API para o motor
    def obter_url(self) -> str:
        return self.var_url.get().strip()

    def definir_url(self, url: str) -> None:
        self.var_url.set(url)

    def obter_opcoes(self) -> OpcoesInterface:
        return OpcoesInterface(
            navegador=self.var_nav.get(), visivel=self.var_visivel.get(), pausar=self.var_pausar.get(),
            seletor=self.var_seletor.get().strip(), profundidade=int(self.campo_prof.get()),
            max_paginas=int(self.campo_maxp.get()), limite=int(self.campo_limite.get()),
            espera=float(self.campo_espera.get()), pasta=self.var_pasta.get().strip() or self._pasta_padrao)

    def marcar_navegador(self) -> None:
        self.var_nav.set(True)

    def limpar_tabela(self) -> None:
        self.tabela.delete(*self.tabela.get_children())
        self._atualizar_contador()

    def adicionar_video(self, iid: str, numero: int, situacao: str, titulo: str, origem: str, link: str) -> None:
        listra = "par" if len(self.tabela.get_children()) % 2 == 0 else "impar"
        self.tabela.insert("", "end", iid=iid, values=(numero, situacao, titulo, origem, link), tags=(listra,))
        self._atualizar_contador()

    def atualizar_situacao(self, iid: str, texto: str, tipo: str) -> None:
        """tipo: 'ok' (verde), 'erro' (vermelho) ou 'pulado' (amarelo)."""
        if not self.tabela.exists(iid):
            return
        valores = list(self.tabela.item(iid, "values"))
        simbolo = self.SIMBOLO_SITUACAO.get(tipo, "")
        valores[1] = f"{simbolo}  {texto}" if simbolo else texto
        self.tabela.item(iid, values=valores, tags=(tipo,))
        self.tabela.see(iid)

    def selecionados(self) -> list[str]:
        """iids das linhas selecionadas (ou a linha em foco)."""
        ids = list(self.tabela.selection())
        if not ids and self.tabela.focus():
            ids = [self.tabela.focus()]
        return ids

    def escrever_log(self, texto: str) -> None:
        """Acrescenta texto ao console. '\\r' volta ao início da linha (barra de progresso)."""
        self.log.configure(state="normal")
        for n, parte in enumerate(texto.split("\r")):
            if n > 0:
                self.log.delete("end-1c linestart", "end-1c")
            for pedaco in parte.splitlines(keepends=True):      # cor decidida linha a linha
                inicio = self.log.index("end-1c")
                self.log.insert("end", pedaco)
                tag = self._cor_da_linha(self.log.get(f"{inicio} linestart", "end-1c"))
                if tag:
                    self.log.tag_add(tag, f"{inicio} linestart", "end-1c")
        self.log.see("end")
        self.log.configure(state="disabled")

    @staticmethod
    def _cor_da_linha(linha: str) -> str | None:
        baixo = linha.lower()
        if "erro" in baixo or "falhou" in baixo:
            return "erro"
        if "salvo em" in baixo or baixo.lstrip().startswith("pronto"):
            return "ok"
        if "pulado" in baixo or "robots" in baixo or "aviso" in baixo:
            return "aviso"
        return None

    def limpar_log(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def definir_status(self, texto: str, ocupado: bool | None = None) -> None:
        self.var_status.set(texto)
        if ocupado is not None:
            self.definir_ocupado(ocupado)

    def definir_ocupado(self, ocupado: bool) -> None:
        """Liga/desliga botões, a barra animada e a cor do indicador."""
        self._ocupado = ocupado
        estado = "disabled" if ocupado else "normal"
        for b in (self.bt_buscar, self.bt_baixar_sel, self.bt_baixar_todos, self.bt_login):
            b.configure(state=estado)
        self.bt_parar.configure(state="normal" if ocupado else "disabled",
                                border_color=Tema.PERIGO if ocupado else Tema.CAMPO_BORDA)
        self.indicador.configure(fg_color=Tema.AVISO if ocupado else Tema.SUCESSO)
        if ocupado:
            self.barra.configure(mode="indeterminate", progress_color=Tema.PRIMARIA)
            self.barra.start()
        else:
            self.barra.stop()
            # o modo animado não volta sozinho ao zero; e no zero o CTk ainda desenha um "pontinho"
            self.barra.configure(mode="determinate", progress_color=Tema.SECUNDARIA)
            self.barra.set(0)

    def mostrar_mensagem(self, titulo: str, mensagem: str, tipo: str = "info") -> None:
        dialogo = DialogoModerno(self, titulo, mensagem, tipo)
        self.wait_window(dialogo)

    def perguntar(self, titulo: str, mensagem: str) -> bool:
        dialogo = DialogoModerno(self, titulo, mensagem, "info", pergunta=True)
        self.wait_window(dialogo)
        return dialogo.resposta

    def _atualizar_contador(self) -> None:
        total = len(self.tabela.get_children())
        self.lb_contador.configure(text=str(total))
        if total:
            self.lb_vazio.place_forget()
        else:
            self.lb_vazio.place(relx=0.5, rely=0.55, anchor="center")

    def _ajustar_checks(self) -> None:
        if self.var_pausar.get() or self.var_visivel.get():
            self.var_nav.set(True)          # pausar/mostrar janela só existem com o navegador
        if self.var_pausar.get():
            self.var_visivel.set(True)

    # ================================================================== ações só de interface
    def ao_colar(self) -> None:
        try:
            self.var_url.set(self.clipboard_get().strip())
        except tk.TclError:
            pass

    def ao_escolher_pasta(self) -> None:
        pasta = filedialog.askdirectory(initialdir=self.var_pasta.get() or ".")
        if pasta:
            self.var_pasta.set(pasta)

    # ================================================================== PLACEHOLDERS (motor)
    # Sobrescreva estes métodos numa subclasse para ligar o motor de scraping (ver app_moderna.py).
    def ao_buscar(self) -> None:
        pass

    def ao_baixar_selecionados(self) -> None:
        pass

    def ao_baixar_todos(self) -> None:
        pass

    def ao_fazer_login(self) -> None:
        pass

    def ao_parar(self) -> None:
        pass

    def ao_abrir_link(self) -> None:
        pass

    def ao_copiar_link(self) -> None:
        pass

    def ao_salvar_lista(self) -> None:
        pass

    def ao_abrir_pasta(self) -> None:
        pass


if __name__ == "__main__":
    # Só a interface, com dados de exemplo (os botões de ação não fazem nada aqui).
    janela = JanelaModerna()
    exemplos = [("Aula 01 - Introdução", "vídeo da página", "https://exemplo.com/videos/aula01.mp4"),
                ("Trailer oficial", "player embutido", "https://www.youtube.com/embed/abc123"),
                ("Palestra completa", "pedido do player", "https://cdn.exemplo.com/hls/master.m3u8")]
    for i, (titulo, origem, link) in enumerate(exemplos):
        janela.adicionar_video(str(i), i + 1, "", titulo, origem, link)
    janela.atualizar_situacao("0", "baixado", "ok")
    janela.atualizar_situacao("1", "pulado", "pulado")
    janela.escrever_log("Acessando: https://exemplo.com/videos\n3 vídeo(s) encontrado(s).\n"
                        "Salvo em videos_baixados/Aula 01 - Introdução.mp4\nPulado: é um player de outro site\n")
    janela.mainloop()
