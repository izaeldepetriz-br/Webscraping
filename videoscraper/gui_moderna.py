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
    filtro_links: str
    profundidade: int
    max_paginas: int
    limite: int
    espera: float
    pasta: str


@dataclass
class OpcoesJellyfin:
    """Tudo o que o usuário escolheu na aba Jellyfin."""
    modo: str                    # "filmes" ou "series"
    origem: str                  # pasta com os arquivos bagunçados
    destino: str                 # biblioteca do Jellyfin (Filmes ou Séries, conforme o modo)
    tmdb: bool
    chave_tmdb: str
    incluir_tmdbid: bool
    exigir_catalogo: bool
    limpar_lixo: bool            # apagar .url/.txt de propaganda e trailers pequenos
    legendas: bool               # baixar legendas ao organizar
    fonte_legenda: str           # um de JanelaModerna.FONTES_LEGENDA
    chave_opensubtitles: str
    url_site: str
    idioma: str
    sobrescrever: bool
    lembrar_chaves: bool


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

        self._estilizar_tabela()
        self._extras_tabela: dict = {}       # tabela -> (contador, texto de "vazio")
        self.logs: list[ctk.CTkTextbox] = []  # um console por aba, com o mesmo conteúdo

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._montar_cabecalho()
        # Cada aba é um quadro na MESMA célula da grade; trocar de aba = mostrar um e esconder o outro.
        self.aba_videos = ctk.CTkFrame(self, fg_color="transparent")
        self.aba_jellyfin = ctk.CTkFrame(self, fg_color="transparent")
        for aba in (self.aba_videos, self.aba_jellyfin):
            aba.grid(row=1, column=0, sticky="nsew")
            aba.grid_columnconfigure(0, weight=1)
        self.aba_videos.grid_rowconfigure(2, weight=1)
        self.aba_jellyfin.grid_rowconfigure(1, weight=1)
        self._montar_endereco(self.aba_videos)
        self._montar_acoes(self.aba_videos)
        self._montar_corpo(self.aba_videos)
        self._montar_aba_jellyfin(self.aba_jellyfin)
        self._montar_rodape()
        self._organizar_liberado = False
        self.definir_ocupado(False)
        self.mostrar_aba("Vídeos")
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

    def _entrada(self, master, var, dica="", altura=38, **extra) -> ctk.CTkEntry:
        e = ctk.CTkEntry(master, textvariable=var, placeholder_text=dica, height=altura,
                         corner_radius=Tema.RAIO_CONTROLE, border_width=1, fg_color=Tema.CAMPO,
                         border_color=Tema.CAMPO_BORDA, text_color=Tema.TEXTO,
                         placeholder_text_color=Tema.TEXTO_FRACO, font=self.f_normal, **extra)
        e.bind("<FocusIn>", lambda ev: e.configure(border_color=Tema.CAMPO_FOCO))
        e.bind("<FocusOut>", lambda ev: e.configure(border_color=Tema.CAMPO_BORDA))
        return e

    def _rotulo(self, master, texto, suave=True, fonte=None) -> ctk.CTkLabel:
        return ctk.CTkLabel(master, text=texto, anchor="w", font=fonte or self.f_rotulo,
                            text_color=Tema.TEXTO_SUAVE if suave else Tema.TEXTO)

    # ------------------------------------------------------------------ 1. cabeçalho e endereço
    SUBTITULOS = {
        "Vídeos": "1) Cole o endereço da página    2) Clique em Buscar vídeos    3) Selecione e clique em Baixar",
        "Jellyfin": "1) Escolha as pastas    2) Clique em Pré-visualizar    3) Confira e clique em Organizar",
    }
    TITULOS = {"Vídeos": "Extrair e baixar vídeos públicos",
               "Jellyfin": "Organizar a biblioteca do Jellyfin"}

    def _montar_cabecalho(self) -> None:
        topo = ctk.CTkFrame(self, fg_color="transparent")
        topo.grid(row=0, column=0, sticky="ew", padx=28, pady=(18, 0))
        textos = ctk.CTkFrame(topo, fg_color="transparent")
        textos.pack(side="left")
        self.lb_titulo = ctk.CTkLabel(textos, text=self.TITULOS["Vídeos"], font=self.f_titulo,
                                      text_color=Tema.TEXTO, anchor="w")
        self.lb_titulo.pack(anchor="w")
        self.lb_subtitulo = ctk.CTkLabel(textos, font=self.f_sub, text_color=Tema.TEXTO_SUAVE, anchor="w",
                                         text=self.SUBTITULOS["Vídeos"])
        self.lb_subtitulo.pack(anchor="w", pady=(2, 0))
        self.seletor_aba = ctk.CTkSegmentedButton(
            topo, values=["Vídeos", "Jellyfin"], command=self.mostrar_aba, height=38,
            corner_radius=Tema.RAIO_CONTROLE, font=self.f_botao, fg_color=Tema.CARTAO,
            selected_color=Tema.PRIMARIA, selected_hover_color=Tema.PRIMARIA_HOVER,
            unselected_color=Tema.CARTAO, unselected_hover_color=Tema.SECUNDARIA_HOVER, text_color=Tema.TEXTO)
        self.seletor_aba.pack(side="right", pady=(4, 0))

    def mostrar_aba(self, nome: str) -> None:
        """'Vídeos' ou 'Jellyfin'."""
        mostrar, esconder = ((self.aba_videos, self.aba_jellyfin) if nome == "Vídeos"
                             else (self.aba_jellyfin, self.aba_videos))
        esconder.grid_remove()
        mostrar.grid()
        self.seletor_aba.set(nome)
        self.lb_titulo.configure(text=self.TITULOS[nome])
        self.lb_subtitulo.configure(text=self.SUBTITULOS[nome])

    def aba_atual(self) -> str:
        return self.seletor_aba.get()

    def _montar_endereco(self, aba) -> None:
        cartao = self._cartao(aba)
        cartao.grid(row=0, column=0, sticky="ew", padx=28, pady=(14, 0))
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
    def _montar_acoes(self, aba) -> None:
        barra = ctk.CTkFrame(aba, fg_color="transparent")
        barra.grid(row=1, column=0, sticky="ew", padx=28, pady=12)
        self.bt_buscar = self._botao(barra, "Buscar vídeos", self.ao_buscar, "primario", largura=170)
        self.bt_baixar_sel = self._botao(barra, "Baixar selecionados", self.ao_baixar_selecionados, largura=170)
        self.bt_baixar_todos = self._botao(barra, "Baixar todos", self.ao_baixar_todos, largura=130)
        self.bt_login = self._botao(barra, "Fazer login no site", self.ao_fazer_login, largura=160)
        self.bt_parar = self._botao(barra, "Parar", self.ao_parar, "perigo", largura=100)
        for b in (self.bt_buscar, self.bt_baixar_sel, self.bt_baixar_todos, self.bt_login):
            b.pack(side="left", padx=(0, 10))
        self.bt_parar.pack(side="right")

    # ------------------------------------------------------------------ corpo: opções + vídeos + log
    def _montar_corpo(self, aba) -> None:
        corpo = self._corpo(aba, linha=2)
        self._montar_opcoes(corpo)
        self._montar_tabela(corpo)
        self._criar_console(corpo)

    def _corpo(self, aba, linha: int) -> ctk.CTkFrame:
        """Área de baixo de uma aba: painel lateral (coluna 0) + tabela e console (coluna 1)."""
        corpo = ctk.CTkFrame(aba, fg_color="transparent")
        corpo.grid(row=linha, column=0, sticky="nsew", padx=28)
        corpo.grid_columnconfigure(1, weight=1)
        corpo.grid_rowconfigure(0, weight=3)
        corpo.grid_rowconfigure(1, weight=2)
        return corpo

    def _lateral(self, corpo) -> ctk.CTkScrollableFrame:
        lateral = ctk.CTkScrollableFrame(corpo, width=320, fg_color=Tema.CARTAO, corner_radius=Tema.RAIO,
                                         border_width=1, border_color=Tema.CARTAO_BORDA,
                                         scrollbar_button_color=Tema.CARTAO_BORDA,
                                         scrollbar_button_hover_color=Tema.CAMPO_BORDA)
        lateral.grid(row=0, column=0, rowspan=2, sticky="nsw", padx=(0, 14))
        return lateral

    def _checkbox(self, master, texto, var, comando=None) -> ctk.CTkCheckBox:
        caixa = ctk.CTkCheckBox(master, text=texto, variable=var, command=comando,
                                font=self.f_normal, text_color=Tema.TEXTO, fg_color=Tema.PRIMARIA,
                                hover_color=Tema.PRIMARIA_HOVER, border_color=Tema.CAMPO_BORDA,
                                checkbox_width=20, checkbox_height=20, corner_radius=6, border_width=2)
        caixa.pack(anchor="w", pady=4, padx=18)
        return caixa

    # 2. painel de opções (cartão lateral; rola se a tela for baixa)
    def _montar_opcoes(self, corpo) -> None:
        lateral = self._lateral(corpo)
        p = dict(padx=18)

        self._rotulo(lateral, "Opções", suave=False, fonte=self.f_secao).pack(anchor="w", pady=(12, 4), **p)
        self.var_nav = tk.BooleanVar(value=False)
        self.var_visivel = tk.BooleanVar(value=False)
        self.var_pausar = tk.BooleanVar(value=False)
        for texto, var in (("Usar navegador (sites com\nJavaScript ou login)", self.var_nav),
                           ("Mostrar a janela do navegador", self.var_visivel),
                           ("Pausar para eu resolver verificações", self.var_pausar)):
            self._checkbox(lateral, texto, var, self._ajustar_checks)

        self._separador(lateral)
        self._rotulo(lateral, "Parâmetros", suave=False, fonte=self.f_secao).pack(anchor="w", pady=(0, 6), **p)
        self._rotulo(lateral, "Seletor CSS (opcional):").pack(anchor="w", **p)
        self.var_seletor = tk.StringVar()
        self._entrada(lateral, self.var_seletor, "ex.: a.video-link").pack(fill="x", pady=(4, 10), **p)
        self._rotulo(lateral, "Seguir só links que contêm (opcional):").pack(anchor="w", **p)
        self.var_filtro = tk.StringVar()
        self._entrada(lateral, self.var_filtro, "ex.: /details/").pack(fill="x", pady=(4, 10), **p)

        self.campo_prof = self._numero(lateral, "Seguir links (níveis):", 0, 0, 5, 1)
        self.campo_maxp = self._numero(lateral, "Máx. de páginas:", 30, 1, 2000, 10)
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

    def _criar_tabela(self, corpo, titulo: str, colunas, texto_vazio: str):
        """Cartão com título + contador, tabela escura com rolagem e uma faixa para botões.
        Devolve (tabela, faixa_de_botoes)."""
        cartao = self._cartao(corpo)
        cartao.grid(row=0, column=1, sticky="nsew", pady=(0, 14))
        cartao.grid_columnconfigure(0, weight=1)
        cartao.grid_rowconfigure(1, weight=1)

        topo = ctk.CTkFrame(cartao, fg_color="transparent")
        topo.grid(row=0, column=0, columnspan=2, sticky="ew", padx=18, pady=(14, 8))
        self._rotulo(topo, titulo, suave=False, fonte=self.f_secao).pack(side="left")
        contador = ctk.CTkLabel(topo, text="0", font=ctk.CTkFont(Tema.FAMILIA, 11, "bold"),
                                fg_color=Tema.SECUNDARIA, text_color=Tema.TEXTO_SUAVE,
                                corner_radius=10, width=34, height=22)
        contador.pack(side="left", padx=10)

        quadro = ctk.CTkFrame(cartao, fg_color=Tema.CARTAO, corner_radius=0)
        quadro.grid(row=1, column=0, sticky="nsew", padx=(18, 0))
        quadro.grid_columnconfigure(0, weight=1)
        quadro.grid_rowconfigure(0, weight=1)
        tabela = ttk.Treeview(quadro, columns=[c[0] for c in colunas], show="headings",
                              selectmode="extended", style="Moderno.Treeview")
        for chave, texto, largura, estica in colunas:
            tabela.heading(chave, text=texto, anchor="w")
            tabela.column(chave, width=largura, minwidth=40, stretch=estica, anchor="w")
        tabela.grid(row=0, column=0, sticky="nsew")
        tabela.tag_configure("par", background=Tema.LINHA_PAR)
        tabela.tag_configure("impar", background=Tema.LINHA_IMPAR)
        for situacao, cor in self.FUNDO_SITUACAO.items():
            tabela.tag_configure(situacao, background=cor)
        rolagem = ctk.CTkScrollbar(cartao, command=tabela.yview, button_color=Tema.CARTAO_BORDA,
                                   button_hover_color=Tema.CAMPO_BORDA)
        rolagem.grid(row=1, column=1, sticky="ns", padx=(4, 10))
        tabela.configure(yscrollcommand=rolagem.set)

        vazio = ctk.CTkLabel(quadro, text=texto_vazio, font=self.f_normal, text_color=Tema.TEXTO_FRACO,
                             fg_color=Tema.CARTAO)
        vazio.place(relx=0.5, rely=0.55, anchor="center")
        self._extras_tabela[str(tabela)] = (contador, vazio)

        faixa = ctk.CTkFrame(cartao, fg_color="transparent")
        faixa.grid(row=2, column=0, columnspan=2, sticky="ew", padx=18, pady=14)
        return tabela, faixa

    # 4. vídeos encontrados
    def _montar_tabela(self, corpo) -> None:
        self.tabela, acoes = self._criar_tabela(
            corpo, "Vídeos encontrados", self.COLUNAS,
            "Nenhum vídeo ainda. Cole um endereço e clique em Buscar vídeos.")
        self.lb_contador, self.lb_vazio = self._extras_tabela[str(self.tabela)]
        self.tabela.bind("<Double-1>", lambda e: self.ao_abrir_link())
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

    # 5. console de logs (um por aba; escrever_log escreve em todos)
    def _criar_console(self, corpo) -> ctk.CTkTextbox:
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

        console = ctk.CTkTextbox(cartao, fg_color=Tema.CONSOLE, text_color="#c9d1e3", font=self.f_mono,
                                 corner_radius=Tema.RAIO_CONTROLE, border_width=1, border_color=Tema.CARTAO_BORDA,
                                 scrollbar_button_color=Tema.CARTAO_BORDA, wrap="word")
        console.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 16))
        console.tag_config("erro", foreground=Tema.PERIGO)
        console.tag_config("ok", foreground=Tema.SUCESSO)
        console.tag_config("aviso", foreground=Tema.AVISO)
        console.configure(state="disabled")
        self.logs.append(console)
        if len(self.logs) == 1:
            self.log = console           # o da aba Vídeos (nome mantido por compatibilidade)
        return console

    # ------------------------------------------------------------------ aba Jellyfin
    COLUNAS_JF = (("n", "#", 44, False), ("status", "Situação", 150, False),
                  ("atual", "Arquivo atual", 210, True), ("novo", "Novo nome (a pasta leva o mesmo nome)", 300, True),
                  ("legenda", "Legenda", 140, False))
    FONTES_LEGENDA = ("Site de demonstração", "OpenSubtitles (API)", "Site de busca (URL)")
    ROTULOS_DESTINO = {"Filmes": "Biblioteca de Filmes do Jellyfin:", "Séries": "Biblioteca de Séries do Jellyfin:"}

    def _montar_aba_jellyfin(self, aba) -> None:
        barra = ctk.CTkFrame(aba, fg_color="transparent")
        barra.grid(row=0, column=0, sticky="ew", padx=28, pady=(14, 12))
        self.bt_previa = self._botao(barra, "Pré-visualizar", self.ao_previsualizar, "primario", largura=170)
        self.bt_organizar = self._botao(barra, "Organizar", self.ao_organizar, largura=130)
        self.bt_legendas = self._botao(barra, "Baixar legendas que faltam", self.ao_baixar_legendas, largura=210)
        self.bt_desfazer = self._botao(barra, "Desfazer última", self.ao_desfazer, largura=140)
        self.bt_parar_jf = self._botao(barra, "Parar", self.ao_parar, "perigo", largura=100)
        for b in (self.bt_previa, self.bt_organizar, self.bt_legendas, self.bt_desfazer):
            b.pack(side="left", padx=(0, 10))
        self.bt_parar_jf.pack(side="right")

        corpo = self._corpo(aba, linha=1)
        lateral = self._lateral(corpo)
        p = dict(padx=18)

        self._rotulo(lateral, "Tipo de conteúdo", suave=False, fonte=self.f_secao).pack(anchor="w", pady=(12, 6), **p)
        self._destinos = {"Filmes": "", "Séries": ""}
        self._modo_atual = "Filmes"
        self.seletor_modo = ctk.CTkSegmentedButton(
            lateral, values=["Filmes", "Séries"], command=self._ao_trocar_modo, height=34,
            corner_radius=Tema.RAIO_CONTROLE, font=self.f_normal, fg_color=Tema.CAMPO,
            selected_color=Tema.PRIMARIA, selected_hover_color=Tema.PRIMARIA_HOVER,
            unselected_color=Tema.CAMPO, unselected_hover_color=Tema.SECUNDARIA_HOVER, text_color=Tema.TEXTO)
        self.seletor_modo.pack(fill="x", **p)
        self.seletor_modo.set("Filmes")

        self._separador(lateral)
        self._rotulo(lateral, "Pastas", suave=False, fonte=self.f_secao).pack(anchor="w", pady=(0, 6), **p)
        self.var_jf_origem = tk.StringVar()
        self.var_jf_destino = tk.StringVar()
        self._campo_pasta(lateral, "Arquivos para organizar:", self.var_jf_origem, "ex.: C:/Users/Voce/Downloads")
        self.lb_destino = self._campo_pasta(lateral, self.ROTULOS_DESTINO["Filmes"], self.var_jf_destino,
                                            "ex.: D:/Jellyfin/Filmes")

        self._separador(lateral)
        self._rotulo(lateral, "Nomes", suave=False, fonte=self.f_secao).pack(anchor="w", pady=(0, 6), **p)
        self.var_jf_tmdb = tk.BooleanVar(value=False)
        self.var_jf_chave_tmdb = tk.StringVar()
        self.cb_tmdb = self._checkbox(lateral, "Consultar também o TMDB", self.var_jf_tmdb, self._mostrar_campos_jf)
        self.campo_chave_tmdb = self._entrada(lateral, self.var_jf_chave_tmdb, "Chave da API do TMDB", show="•")
        self.var_jf_tmdbid = tk.BooleanVar(value=False)
        self.var_jf_exigir = tk.BooleanVar(value=False)
        self.cb_tmdbid = self._checkbox(lateral, "Incluir [tmdbid] no nome da pasta", self.var_jf_tmdbid)
        self._checkbox(lateral, "Só mover o que estiver no catálogo", self.var_jf_exigir)

        self._separador(lateral)
        self._rotulo(lateral, "Limpeza", suave=False, fonte=self.f_secao).pack(anchor="w", pady=(0, 6), **p)
        self.var_jf_lixo = tk.BooleanVar(value=True)
        self._checkbox(lateral, "Apagar lixo do torrent (.url, .txt\nde propaganda, trailers < 100 MB)",
                       self.var_jf_lixo)
        self._rotulo(lateral, "Imagens (poster, backdrop...) e legendas\nlocais vão junto com o filme.",
                     fonte=ctk.CTkFont(Tema.FAMILIA, 11)).pack(anchor="w", pady=(2, 0), **p)

        self._separador(lateral)
        self._rotulo(lateral, "Legendas", suave=False, fonte=self.f_secao).pack(anchor="w", pady=(0, 6), **p)
        self.var_jf_legendas = tk.BooleanVar(value=True)
        self._checkbox(lateral, "Baixar legendas ao organizar", self.var_jf_legendas)
        self._rotulo(lateral, "Fonte das legendas:").pack(anchor="w", pady=(6, 4), **p)
        self.var_jf_fonte = tk.StringVar(value=self.FONTES_LEGENDA[0])
        ctk.CTkOptionMenu(lateral, variable=self.var_jf_fonte, values=list(self.FONTES_LEGENDA),
                          command=lambda v: self._mostrar_campos_jf(), height=36,
                          corner_radius=Tema.RAIO_CONTROLE, font=self.f_normal, fg_color=Tema.CAMPO,
                          button_color=Tema.SECUNDARIA, button_hover_color=Tema.SECUNDARIA_HOVER,
                          dropdown_fg_color=Tema.CARTAO, dropdown_hover_color=Tema.SECUNDARIA_HOVER,
                          dropdown_font=self.f_normal, text_color=Tema.TEXTO).pack(fill="x", **p)
        self.quadro_fonte = ctk.CTkFrame(lateral, fg_color="transparent")
        self.quadro_fonte.pack(fill="x")
        self.var_jf_chave_os = tk.StringVar()
        self.var_jf_url_site = tk.StringVar()
        self.campo_chave_os = self._entrada(self.quadro_fonte, self.var_jf_chave_os,
                                            "Chave da API do OpenSubtitles", show="•")
        self.campo_url_site = self._entrada(self.quadro_fonte, self.var_jf_url_site,
                                            "https://site/busca?q={consulta}")
        linha = ctk.CTkFrame(lateral, fg_color="transparent")
        linha.pack(fill="x", pady=(8, 2), **p)
        self.var_jf_idioma = tk.StringVar(value="pt-BR")
        self._entrada(linha, self.var_jf_idioma, width=90).pack(side="right")
        self._rotulo(linha, "Idioma da legenda:").pack(side="left")
        self.var_jf_sobrescrever = tk.BooleanVar(value=False)
        self.var_jf_lembrar = tk.BooleanVar(value=False)
        self._checkbox(lateral, "Trocar legendas que já existem", self.var_jf_sobrescrever)
        self._checkbox(lateral, "Lembrar as chaves neste computador", self.var_jf_lembrar)
        ctk.CTkFrame(lateral, height=12, fg_color="transparent").pack()
        self._mostrar_campos_jf()

        self.tabela_jf, faixa = self._criar_tabela(
            corpo, "Arquivos", self.COLUNAS_JF,
            "Escolha as pastas e clique em Pré-visualizar. Nada é movido sem você confirmar.")
        self.bt_abrir_biblioteca = self._botao(faixa, "Abrir pasta da biblioteca", self.ao_abrir_biblioteca,
                                               "fantasma")
        self.bt_abrir_biblioteca.pack(side="left")
        self._criar_console(corpo)

    def _campo_pasta(self, master, rotulo: str, var: tk.StringVar, dica: str) -> ctk.CTkLabel:
        lb = self._rotulo(master, rotulo)
        lb.pack(anchor="w", padx=18, pady=(4, 4))
        linha = ctk.CTkFrame(master, fg_color="transparent")
        linha.pack(fill="x", padx=18, pady=(0, 6))
        self._botao(linha, "Escolher...", lambda: self._escolher_pasta_em(var), largura=96).pack(side="right")
        self._entrada(linha, var, dica).pack(side="left", fill="x", expand=True, padx=(0, 8))
        return lb

    def _escolher_pasta_em(self, var: tk.StringVar) -> None:
        pasta = filedialog.askdirectory(initialdir=var.get() or ".")
        if pasta:
            var.set(pasta)

    def _mostrar_campos_jf(self) -> None:
        """Mostra só os campos que fazem sentido para as escolhas atuais."""
        if self.var_jf_tmdb.get():
            self.campo_chave_tmdb.pack(fill="x", padx=18, pady=(0, 6), after=self.cb_tmdb)
        else:
            self.campo_chave_tmdb.pack_forget()
        fonte = self.var_jf_fonte.get()
        self.campo_chave_os.pack_forget()
        self.campo_url_site.pack_forget()
        if fonte == self.FONTES_LEGENDA[1]:
            self.campo_chave_os.pack(fill="x", padx=18, pady=(8, 0))
        elif fonte == self.FONTES_LEGENDA[2]:
            self.campo_url_site.pack(fill="x", padx=18, pady=(8, 0))

    def _ao_trocar_modo(self, modo: str) -> None:
        """Filmes e Séries têm bibliotecas diferentes: cada modo lembra a sua pasta."""
        self._destinos[self._modo_atual] = self.var_jf_destino.get()
        self._modo_atual = modo
        self.var_jf_destino.set(self._destinos.get(modo, ""))
        self.lb_destino.configure(text=self.ROTULOS_DESTINO[modo])
        self.limpar_tabela_jf()
        self.liberar_organizar(False)              # a pré-visualização era do outro modo

    # ------------------------------------------------------------------ 5. rodapé
    def _montar_rodape(self) -> None:
        rodape = ctk.CTkFrame(self, fg_color=Tema.CARTAO, corner_radius=0, height=40, border_width=0)
        rodape.grid(row=2, column=0, sticky="ew", pady=(14, 0))
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
            seletor=self.var_seletor.get().strip(), filtro_links=self.var_filtro.get().strip(),
            profundidade=int(self.campo_prof.get()),
            max_paginas=int(self.campo_maxp.get()), limite=int(self.campo_limite.get()),
            espera=float(self.campo_espera.get()), pasta=self.var_pasta.get().strip() or self._pasta_padrao)

    def obter_opcoes_jellyfin(self) -> OpcoesJellyfin:
        self._destinos[self._modo_atual] = self.var_jf_destino.get()
        return OpcoesJellyfin(
            modo="series" if self._modo_atual == "Séries" else "filmes",
            origem=self.var_jf_origem.get().strip(), destino=self.var_jf_destino.get().strip(),
            tmdb=self.var_jf_tmdb.get(), chave_tmdb=self.var_jf_chave_tmdb.get().strip(),
            incluir_tmdbid=self.var_jf_tmdbid.get(), exigir_catalogo=self.var_jf_exigir.get(),
            limpar_lixo=self.var_jf_lixo.get(), legendas=self.var_jf_legendas.get(), fonte_legenda=self.var_jf_fonte.get(),
            chave_opensubtitles=self.var_jf_chave_os.get().strip(), url_site=self.var_jf_url_site.get().strip(),
            idioma=self.var_jf_idioma.get().strip() or "pt-BR", sobrescrever=self.var_jf_sobrescrever.get(),
            lembrar_chaves=self.var_jf_lembrar.get())

    def destinos_jellyfin(self) -> dict:
        """Pasta de Filmes e de Séries (cada modo tem a sua)."""
        self._destinos[self._modo_atual] = self.var_jf_destino.get()
        return {"Filmes": self._destinos["Filmes"].strip(), "Séries": self._destinos["Séries"].strip()}

    def definir_opcoes_jellyfin(self, dados: dict) -> None:
        """Preenche a aba com valores salvos (chaves que não existirem ficam como estão)."""
        textos = {"origem": self.var_jf_origem, "chave_tmdb": self.var_jf_chave_tmdb,
                  "chave_opensubtitles": self.var_jf_chave_os, "url_site": self.var_jf_url_site,
                  "idioma": self.var_jf_idioma}
        marcas = {"tmdb": self.var_jf_tmdb, "incluir_tmdbid": self.var_jf_tmdbid,
                  "exigir_catalogo": self.var_jf_exigir, "legendas": self.var_jf_legendas,
                  "limpar_lixo": self.var_jf_lixo,
                  "sobrescrever": self.var_jf_sobrescrever, "lembrar_chaves": self.var_jf_lembrar}
        for chave, var in textos.items():
            if dados.get(chave):
                var.set(dados[chave])
        for chave, var in marcas.items():
            if chave in dados:
                var.set(bool(dados[chave]))
        if dados.get("fonte_legenda") in self.FONTES_LEGENDA:
            self.var_jf_fonte.set(dados["fonte_legenda"])
        self._destinos["Filmes"] = dados.get("destino_filmes", self._destinos["Filmes"])
        self._destinos["Séries"] = dados.get("destino_series", self._destinos["Séries"])
        self.var_jf_destino.set(self._destinos[self._modo_atual])
        self._mostrar_campos_jf()

    def limpar_tabela_jf(self) -> None:
        self.tabela_jf.delete(*self.tabela_jf.get_children())
        self._atualizar_contador(self.tabela_jf)

    def adicionar_linha_jf(self, iid: str, numero: int, situacao: str, tipo: str | None,
                           atual: str, novo: str, legenda: str = "") -> None:
        """tipo: 'ok', 'erro', 'pulado' ou None (linha neutra)."""
        if tipo:
            situacao = f"{self.SIMBOLO_SITUACAO[tipo]}  {situacao}"
            tags = (tipo,)
        else:
            tags = ("par" if len(self.tabela_jf.get_children()) % 2 == 0 else "impar",)
        self.tabela_jf.insert("", "end", iid=iid, values=(numero, situacao, atual, novo, legenda), tags=tags)
        self._atualizar_contador(self.tabela_jf)

    def atualizar_linha_jf(self, iid: str, legenda: str | None = None, legenda_tipo: str | None = None) -> None:
        if not self.tabela_jf.exists(iid):
            return
        valores = list(self.tabela_jf.item(iid, "values"))
        if legenda is not None:
            simbolo = self.SIMBOLO_SITUACAO.get(legenda_tipo or "", "")
            valores[4] = f"{simbolo}  {legenda}" if simbolo else legenda
        self.tabela_jf.item(iid, values=valores)
        self.tabela_jf.see(iid)

    def liberar_organizar(self, sim: bool) -> None:
        """O botão Organizar só funciona depois de uma pré-visualização."""
        self._organizar_liberado = sim
        self.bt_organizar.configure(state="normal" if sim and not self._ocupado else "disabled")

    def marcar_navegador(self) -> None:
        self.var_nav.set(True)

    def limpar_tabela(self) -> None:
        self.tabela.delete(*self.tabela.get_children())
        self._atualizar_contador(self.tabela)

    def adicionar_video(self, iid: str, numero: int, situacao: str, titulo: str, origem: str, link: str) -> None:
        listra = "par" if len(self.tabela.get_children()) % 2 == 0 else "impar"
        self.tabela.insert("", "end", iid=iid, values=(numero, situacao, titulo, origem, link), tags=(listra,))
        self._atualizar_contador(self.tabela)

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
        """Acrescenta texto aos consoles. '\\r' volta ao início da linha (barra de progresso)."""
        for console in self.logs:
            console.configure(state="normal")
            for n, parte in enumerate(texto.split("\r")):
                if n > 0:
                    console.delete("end-1c linestart", "end-1c")
                for pedaco in parte.splitlines(keepends=True):      # cor decidida linha a linha
                    inicio = console.index("end-1c")
                    console.insert("end", pedaco)
                    tag = self._cor_da_linha(console.get(f"{inicio} linestart", "end-1c"))
                    if tag:
                        console.tag_add(tag, f"{inicio} linestart", "end-1c")
            console.see("end")
            console.configure(state="disabled")

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
        for console in self.logs:
            console.configure(state="normal")
            console.delete("1.0", "end")
            console.configure(state="disabled")

    def definir_status(self, texto: str, ocupado: bool | None = None) -> None:
        self.var_status.set(texto)
        if ocupado is not None:
            self.definir_ocupado(ocupado)

    def definir_ocupado(self, ocupado: bool) -> None:
        """Liga/desliga botões, a barra animada e a cor do indicador."""
        self._ocupado = ocupado
        estado = "disabled" if ocupado else "normal"
        for b in (self.bt_buscar, self.bt_baixar_sel, self.bt_baixar_todos, self.bt_login,
                  self.bt_previa, self.bt_legendas, self.bt_desfazer):
            b.configure(state=estado)
        self.bt_organizar.configure(state="normal" if self._organizar_liberado and not ocupado else "disabled")
        for parar in (self.bt_parar, self.bt_parar_jf):
            parar.configure(state="normal" if ocupado else "disabled",
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

    def _atualizar_contador(self, tabela) -> None:
        contador, vazio = self._extras_tabela[str(tabela)]
        total = len(tabela.get_children())
        contador.configure(text=str(total))
        if total:
            vazio.place_forget()
        else:
            vazio.place(relx=0.5, rely=0.55, anchor="center")

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

    # --- aba Jellyfin
    def ao_previsualizar(self) -> None:
        pass

    def ao_organizar(self) -> None:
        pass

    def ao_baixar_legendas(self) -> None:
        pass

    def ao_desfazer(self) -> None:
        pass

    def ao_abrir_biblioteca(self) -> None:
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
