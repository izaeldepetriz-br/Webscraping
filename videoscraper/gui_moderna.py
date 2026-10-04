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
from datetime import datetime
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
    apagar_pasta_origem: bool    # apagar a pasta do torrent inteira depois de transferir
    legendas: bool               # baixar legendas ao organizar
    fonte_legenda: str           # um de JanelaModerna.FONTES_LEGENDA
    chave_opensubtitles: str
    url_site: str
    idioma: str
    sobrescrever: bool
    lembrar_chaves: bool
    imagens_tmdb: bool = True        # baixar poster.jpg/backdrop.jpg do TMDB se faltarem
    gerar_nfo: bool = True           # criar Nome (Ano).nfo
    jellyfin_url: str = ""
    jellyfin_api_key: str = ""
    atualizar_jellyfin: bool = True  # pedir o scan da biblioteca no fim
    discord_webhook: str = ""
    telegram_token: str = ""
    telegram_chat_id: str = ""
    filtros_ocultos: tuple = ()      # situações escondidas na tabela (só visual)
    nomes_episodios: bool = True     # séries: 'Dark S01E01 - Segredos.mkv' (nome do episódio pelo TMDB)
    chave_subdl: str = ""            # SubDL: fonte própria ou reserva do OpenSubtitles
    vigiar: bool = False             # pasta vigiada ligada
    vigiar_min: float = 5            # de quanto em quanto tempo conferir
    pastas_vigiadas: tuple = ()      # pastas de download (ex.: as do uTorrent); vazio = a pasta de origem
    conferir_auto: bool = False      # conferir os .strm sozinho
    conferir_a_cada: float = 7
    conferir_unidade: str = "dias"   # "minutos", "horas" ou "dias"
    remover_quebrados: bool = False
    ultima_conferencia: str = ""     # data/hora (ISO) da última conferência automática


# Máximo dos campos "Máx. de páginas" e "Máx. de vídeos" (antes 2000 e 1000).
MAXIMO_ITENS = 100_000


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

    def __init__(self, master, titulo: str, mensagem: str, tipo: str = "info", pergunta: bool = False,
                 opcoes: tuple[str, ...] = ()):
        """opcoes: botões de escolha (o 1º é o principal); `resposta` vira o texto do botão clicado
        (None = Cancelar)."""
        super().__init__(master, fg_color=Tema.CARTAO)
        self.resposta = None if opcoes else False
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
        if opcoes:
            ctk.CTkButton(botoes, text="Cancelar", width=100, height=38, corner_radius=Tema.RAIO_CONTROLE,
                          fg_color=Tema.SECUNDARIA, hover_color=Tema.SECUNDARIA_HOVER,
                          font=ctk.CTkFont(Tema.FAMILIA, 13), command=self.destroy).pack(side="left")
            for n, texto in reversed(list(enumerate(opcoes))):
                ctk.CTkButton(botoes, text=texto, height=38, corner_radius=Tema.RAIO_CONTROLE,
                              fg_color=Tema.PRIMARIA if n == 0 else Tema.SECUNDARIA,
                              hover_color=Tema.PRIMARIA_HOVER if n == 0 else Tema.SECUNDARIA_HOVER,
                              font=ctk.CTkFont(Tema.FAMILIA, 13, "bold" if n == 0 else "normal"),
                              command=lambda t=texto: self._escolher(t)).pack(side="right", padx=(10, 0))
            self.bind("<Return>", lambda e: self._escolher(opcoes[0]))
        else:
            ctk.CTkButton(botoes, text="OK" if not pergunta else "Continuar", width=110, height=38,
                          corner_radius=Tema.RAIO_CONTROLE, fg_color=Tema.PRIMARIA, hover_color=Tema.PRIMARIA_HOVER,
                          font=ctk.CTkFont(Tema.FAMILIA, 13, "bold"), command=self._sim).pack(side="right")
            self.bind("<Return>", lambda e: self._sim())
        if pergunta and not opcoes:
            ctk.CTkButton(botoes, text="Cancelar", width=110, height=38, corner_radius=Tema.RAIO_CONTROLE,
                          fg_color=Tema.SECUNDARIA, hover_color=Tema.SECUNDARIA_HOVER,
                          font=ctk.CTkFont(Tema.FAMILIA, 13), command=self.destroy).pack(side="right", padx=(0, 10))
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

    def _escolher(self, texto: str) -> None:
        self.resposta = texto
        self.destroy()


class JanelaEspelhos(ctk.CTkToplevel):
    """Os espelhos (.strm) das bibliotecas agrupados por espelhamento (1, 2, 3...), para tirar
    qualquer um, não só o último: um espelhamento inteiro, um filme ou alguns episódios."""

    COLUNAS = (("biblioteca", "Biblioteca", 110), ("link", "Link", 360))

    def __init__(self, master, ao_remover, ao_desfazer):
        """ao_remover(iids dos .strm escolhidos); ao_desfazer(): volta a última remoção."""
        super().__init__(master, fg_color=Tema.CARTAO)
        self.title("Espelhos no Jellyfin")
        self.geometry("1040x620")
        self.minsize(760, 420)
        self.transient(master)
        self._grupos: list[tuple[str, list[tuple[str, str, str, str]]]] = []

        topo = ctk.CTkFrame(self, fg_color="transparent")
        topo.pack(fill="x", padx=24, pady=(18, 6))
        ctk.CTkLabel(topo, text="Espelhos (.strm) nas bibliotecas", font=ctk.CTkFont(Tema.FAMILIA, 17, "bold"),
                     text_color=Tema.TEXTO, anchor="w").pack(fill="x")
        ctk.CTkLabel(topo, text="Escolha um espelhamento inteiro (ex.: o 1º) ou só um filme/episódio "
                     "(Ctrl+clique para vários) e clique em Remover. Nada é apagado de vez: "
                     "\"Desfazer última remoção\" põe de volta.", font=master.f_rotulo,
                     text_color=Tema.TEXTO_SUAVE, anchor="w", justify="left", wraplength=980).pack(fill="x", pady=(4, 8))
        busca = ctk.CTkFrame(topo, fg_color="transparent")
        busca.pack(fill="x")
        ctk.CTkLabel(busca, text="Procurar:", font=master.f_rotulo, text_color=Tema.TEXTO_SUAVE).pack(side="left")
        self.var_busca = tk.StringVar()
        self.campo_busca = master._entrada(busca, self.var_busca, "nome do filme ou da série", altura=34)
        self.campo_busca.pack(side="left", fill="x", expand=True, padx=(8, 0))
        self.var_busca.trace_add("write", lambda *_: self._mostrar())

        quadro = ctk.CTkFrame(self, fg_color=Tema.CARTAO)
        quadro.pack(fill="both", expand=True, padx=24, pady=6)
        quadro.grid_columnconfigure(0, weight=1)
        quadro.grid_rowconfigure(0, weight=1)
        self.arvore = ttk.Treeview(quadro, columns=[c[0] for c in self.COLUNAS], show="tree headings",
                                   selectmode="extended", style="Moderno.Treeview")
        self.arvore.heading("#0", text="Espelhamento / item", anchor="w")
        self.arvore.column("#0", width=430, minwidth=200, stretch=True, anchor="w")
        for chave, texto, largura in self.COLUNAS:
            self.arvore.heading(chave, text=texto, anchor="w")
            self.arvore.column(chave, width=largura, minwidth=60, stretch=chave == "link", anchor="w")
        self.arvore.tag_configure("grupo", background=Tema.SECUNDARIA, font=(Tema.FAMILIA, 11, "bold"))
        self.arvore.grid(row=0, column=0, sticky="nsew")
        rolagem = ctk.CTkScrollbar(quadro, command=self.arvore.yview, button_color=Tema.CARTAO_BORDA,
                                   button_hover_color=Tema.CAMPO_BORDA)
        rolagem.grid(row=0, column=1, sticky="ns", padx=(4, 0))
        self.arvore.configure(yscrollcommand=rolagem.set)
        self.arvore.bind("<<TreeviewSelect>>", lambda e: self._contar())

        rodape = ctk.CTkFrame(self, fg_color="transparent")
        rodape.pack(fill="x", padx=24, pady=(6, 18))
        self.lb_resumo = ctk.CTkLabel(rodape, text="", font=master.f_rotulo, text_color=Tema.TEXTO_SUAVE)
        self.lb_resumo.pack(side="left")
        master._botao(rodape, "Fechar", self.destroy, "fantasma", largura=90).pack(side="right")
        self.bt_remover = master._botao(rodape, "Remover selecionados", lambda: ao_remover(self.selecionados()),
                                        "perigo", largura=190)
        self.bt_remover.pack(side="right", padx=(0, 8))
        self.bt_desfazer = master._botao(rodape, "Desfazer última remoção", ao_desfazer, largura=200)
        self.bt_desfazer.pack(side="right", padx=(0, 8))
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Delete>", lambda e: ao_remover(self.selecionados()))

    def preencher(self, grupos: list[tuple[str, list[tuple[str, str, str, str]]]]) -> None:
        """grupos: [(título do espelhamento, [(iid, nome, biblioteca, link)])]."""
        self._grupos = grupos
        self._mostrar()

    def _mostrar(self) -> None:
        procura = _sem_acentos(self.var_busca.get().strip())
        self.arvore.delete(*self.arvore.get_children())
        for n, (titulo, itens) in enumerate(self._grupos):
            visiveis = [i for i in itens if procura in _sem_acentos(i[1])]
            if not visiveis:
                continue
            grupo = self.arvore.insert("", "end", iid=f"grupo-{n}", text=titulo, open=True, tags=("grupo",))
            for k, (iid, nome, biblioteca, link) in enumerate(visiveis):
                self.arvore.insert(grupo, "end", iid=iid, text="   " + nome, values=(biblioteca, link),
                                   tags=("par" if k % 2 == 0 else "impar",))
        self._contar()

    def selecionados(self) -> list[str]:
        """Os .strm escolhidos; um espelhamento selecionado vale por todos os itens dele (os visíveis)."""
        escolhidos = []
        for iid in self.arvore.selection():
            filhos = self.arvore.get_children(iid) if iid.startswith("grupo-") else (iid,)
            escolhidos += [f for f in filhos if f not in escolhidos]
        return escolhidos

    def _contar(self) -> None:
        total = sum(len(self.arvore.get_children(g)) for g in self.arvore.get_children())
        escolhidos = len(self.selecionados())
        self.lb_resumo.configure(text=f"{total} espelho(s)" + (f" · {escolhidos} selecionado(s)" if escolhidos else ""))


def _sem_acentos(texto: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn")


# =============================================================================== janela
class JanelaModerna(ctk.CTk):
    COLUNAS = (("n", "#", 48, False), ("status", "Situação", 110, False), ("titulo", "Título", 240, True),
               ("tipo", "Origem", 130, False), ("url", "Link", 300, True),
               ("conteudo", "Tipo", 70, False), ("licenca", "Licença", 120, False))
    # Ordem na TELA: Tipo e Licença ao lado do título (os valores continuam na ordem acima)
    ORDEM_TELA = ("n", "status", "titulo", "conteudo", "licenca", "tipo", "url")
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
        self._contadores: dict = {}                   # último texto de cada contador de tabela
        self._barra_animada = False
        self._status_base = "Pronto."

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
        # Registro POR AÇÃO: cada Pré-visualizar/Organizar/Completar/teste tem o seu; o seletor no topo
        # do console mostra a ação atual ou uma anterior (antes era tudo numa lista só).
        self._registros: list[dict] = [{"titulo": "1. Início", "partes": []}]
        self._registro_visivel = 0
        self._menus_registro: list[ctk.CTkOptionMenu] = []

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
        return ctk.CTkLabel(master, text=texto, anchor="w", justify="left", font=fonte or self.f_rotulo,
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

    def _lateral(self, corpo, linhas: int = 2) -> ctk.CTkScrollableFrame:
        lateral = ctk.CTkScrollableFrame(corpo, width=320, fg_color=Tema.CARTAO, corner_radius=Tema.RAIO,
                                         border_width=1, border_color=Tema.CARTAO_BORDA,
                                         scrollbar_button_color=Tema.CARTAO_BORDA,
                                         scrollbar_button_hover_color=Tema.CAMPO_BORDA)
        lateral.grid(row=0, column=0, rowspan=linhas, sticky="nsw", padx=(0, 14))
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
        self.campo_maxp = self._numero(lateral, "Máx. de páginas:", 30, 1, MAXIMO_ITENS, 10)
        self.campo_limite = self._numero(lateral, "Máx. de vídeos (0 = todos):", 0, 0, MAXIMO_ITENS, 1)
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
        campo = CampoNumerico(linha, valor, minimo, maximo, passo, decimal, largura=128)   # cabe "100000"
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
        self._topos_tabela = getattr(self, "_topos_tabela", {})
        self._topos_tabela[str(tabela)] = topo

        faixa = ctk.CTkFrame(cartao, fg_color="transparent")
        faixa.grid(row=2, column=0, columnspan=2, sticky="ew", padx=18, pady=14)
        return tabela, faixa

    # 4. vídeos encontrados
    def _montar_tabela(self, corpo) -> None:
        self.tabela, acoes = self._criar_tabela(
            corpo, "Vídeos encontrados", self.COLUNAS,
            "Nenhum vídeo ainda. Cole um endereço e clique em Buscar vídeos.")
        self.lb_contador, self.lb_vazio = self._extras_tabela[str(self.tabela)]
        self.tabela.configure(displaycolumns=self.ORDEM_TELA)
        self.tabela.bind("<Double-1>", lambda e: self.ao_abrir_link())
        # Seleção: um clique = um vídeo; Ctrl+clique = vários; Shift+clique = um intervalo; Ctrl+A = todos
        topo = self._topos_tabela[str(self.tabela)]
        estilo = dict(height=26, corner_radius=6, fg_color="transparent", hover_color=Tema.SECUNDARIA_HOVER,
                      text_color=Tema.PRIMARIA, font=ctk.CTkFont(Tema.FAMILIA, 12))
        self.bt_limpar_selecao = ctk.CTkButton(topo, text="Limpar seleção", command=self.limpar_selecao,
                                               width=110, **estilo)
        self.bt_selecionar_espelhaveis = ctk.CTkButton(topo, text="Só filmes e séries",
                                                       command=self.selecionar_filmes_e_series, width=130, **estilo)
        self.bt_selecionar_todos = ctk.CTkButton(topo, text="Selecionar todos", command=self.selecionar_todos,
                                                 width=120, **estilo)
        for b in (self.bt_limpar_selecao, self.bt_selecionar_espelhaveis, self.bt_selecionar_todos):
            b.pack(side="right", padx=(4, 0))
        self.lb_selecao = ctk.CTkLabel(topo, text="Ctrl+clique ou Shift+clique para escolher vários",
                                       font=self.f_rotulo, text_color=Tema.TEXTO_FRACO)
        self.lb_selecao.pack(side="right", padx=(0, 10))
        self.tabela.bind("<<TreeviewSelect>>", lambda e: self._atualizar_selecao())
        self.tabela.bind("<Control-a>", lambda e: (self.selecionar_todos(), "break")[1])
        self.tabela.bind("<Control-A>", lambda e: (self.selecionar_todos(), "break")[1])
        self.bt_abrir_link = self._botao(acoes, "Abrir link", self.ao_abrir_link, "fantasma")
        self.bt_copiar_link = self._botao(acoes, "Copiar link", self.ao_copiar_link, "fantasma")
        self.bt_salvar_lista = self._botao(acoes, "Salvar lista (CSV/JSON/TXT)...", self.ao_salvar_lista, "fantasma")
        self.bt_abrir_pasta = self._botao(acoes, "Abrir pasta dos vídeos", self.ao_abrir_pasta, "fantasma")
        for b in (self.bt_abrir_link, self.bt_copiar_link, self.bt_salvar_lista, self.bt_abrir_pasta):
            b.pack(side="left", padx=(0, 6))
        # .strm: o Jellyfin toca direto do link, sem baixar (filmes e séries separados, com legendas)
        self.bt_espelhar = self._botao(acoes, "Espelhar no Jellyfin (.strm)...", self.ao_espelhar_jellyfin)
        self.bt_espelhar.pack(side="right")

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
    def _criar_console(self, corpo, linha: int = 1, altura: int = 200) -> ctk.CTkTextbox:
        cartao = self._cartao(corpo)
        cartao.grid(row=linha, column=1, sticky="nsew")
        cartao.grid_columnconfigure(0, weight=1)
        cartao.grid_rowconfigure(1, weight=1)
        topo = ctk.CTkFrame(cartao, fg_color="transparent")
        topo.grid(row=0, column=0, sticky="ew", padx=18, pady=(12, 6))
        for cor in ("#f05252", "#f5a524", "#22c55e"):        # "bolinhas" de janela de terminal
            ctk.CTkFrame(topo, width=10, height=10, corner_radius=5, fg_color=cor).pack(side="left", padx=(0, 6))
        self._rotulo(topo, "O que está acontecendo", suave=False, fonte=self.f_secao).pack(side="left", padx=(8, 0))
        self._botao(topo, "Limpar", self.limpar_log, "fantasma", largura=70).pack(side="right")
        menu = ctk.CTkOptionMenu(topo, values=self._nomes_registros(), command=self._ao_escolher_registro,
                                 width=230, height=28, corner_radius=8, font=self.f_rotulo,
                                 fg_color=Tema.CAMPO, button_color=Tema.SECUNDARIA,
                                 button_hover_color=Tema.SECUNDARIA_HOVER, text_color=Tema.TEXTO,
                                 dropdown_fg_color=Tema.CARTAO, dropdown_text_color=Tema.TEXTO,
                                 dynamic_resizing=False)
        menu.set(self._registros[self._registro_visivel]["titulo"])
        menu.pack(side="right", padx=(0, 8))
        self._menus_registro.append(menu)
        # progresso total (aparece só durante tarefas longas)
        barra = ctk.CTkProgressBar(topo, width=180, height=8, corner_radius=4, mode="determinate",
                                   fg_color=Tema.SECUNDARIA, progress_color=Tema.SUCESSO)
        rotulo = ctk.CTkLabel(topo, text="", font=self.f_rotulo, text_color=Tema.TEXTO_SUAVE)
        rotulo.pack(side="right", padx=(0, 10))
        if not hasattr(self, "_progresso_total"):
            self._progresso_total = []
        self._progresso_total.append((rotulo, barra))

        console = ctk.CTkTextbox(cartao, fg_color=Tema.CONSOLE, text_color="#c9d1e3", font=self.f_mono, height=altura,
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
                  ("atual", "Arquivo atual", 175, True), ("novo", "Novo nome (a pasta leva o mesmo nome)", 235, True),
                  ("legenda", "Legenda", 115, False), ("progresso", "Progresso", 135, False),
                  ("fonte", "Nome via", 150, False))
    # Ordem na TELA: "Nome via" logo depois do novo nome (os valores continuam na ordem acima)
    ORDEM_TELA_JF = ("n", "status", "atual", "novo", "fonte", "legenda", "progresso")
    FONTES_LEGENDA = ("Site de demonstração", "OpenSubtitles (API)", "Site de busca (URL)", "SubDL (API)")
    IDIOMAS_JF = (("pt-BR", "Português"), ("en", "Inglês"), ("es", "Espanhol"))
    ROTULOS_DESTINO = {"Filmes": "Biblioteca de Filmes do Jellyfin:", "Séries": "Biblioteca de Séries do Jellyfin:"}

    def _montar_aba_jellyfin(self, aba) -> None:
        barra = ctk.CTkFrame(aba, fg_color="transparent")
        barra.grid(row=0, column=0, sticky="ew", padx=28, pady=(14, 12))
        self.bt_previa = self._botao(barra, "Pré-visualizar", self.ao_previsualizar, "primario", largura=170)
        self.bt_organizar = self._botao(barra, "Organizar", self.ao_organizar, largura=130)
        self.bt_legendas = self._botao(barra, "Completar biblioteca", self.ao_baixar_legendas, largura=190)
        self.bt_desfazer = self._botao(barra, "Desfazer última", self.ao_desfazer, largura=140)
        self.bt_conferir_espelhos = self._botao(barra, "Conferir espelhos", self.ao_conferir_espelhos, largura=150)
        self.bt_relatorio = self._botao(barra, "Relatório", self.ao_relatorio, largura=110)
        self.bt_gerenciar_espelhos = self._botao(barra, "Espelhos...", self.ao_gerenciar_espelhos, largura=120)
        self.bt_parar_jf = self._botao(barra, "Parar", self.ao_parar, "perigo", largura=100)
        for b in (self.bt_previa, self.bt_organizar, self.bt_legendas, self.bt_desfazer, self.bt_conferir_espelhos,
                  self.bt_relatorio, self.bt_gerenciar_espelhos):
            b.pack(side="left", padx=(0, 10))
        self.bt_parar_jf.pack(side="right")

        corpo = self._corpo(aba, linha=1)
        corpo.grid_rowconfigure(1, weight=0)          # painel Antes -> Depois: altura fixa
        lateral = self._lateral(corpo, linhas=3)
        self.lateral_jf = lateral
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
        self._rotulo(lateral, "Nomes e metadados (TMDB)", suave=False, fonte=self.f_secao).pack(
            anchor="w", pady=(0, 6), **p)
        self.var_jf_tmdb = tk.BooleanVar(value=False)
        self.var_jf_chave_tmdb = tk.StringVar()
        self.var_jf_imagens = tk.BooleanVar(value=True)
        self.var_jf_nfo = tk.BooleanVar(value=True)
        self._rotulo(lateral, "Chave da API do TMDB:").pack(anchor="w", **p)
        self.campo_chave_tmdb = self._entrada(lateral, self.var_jf_chave_tmdb, "themoviedb.org > Configurações > API",
                                              show="•")
        self.campo_chave_tmdb.pack(fill="x", pady=(2, 6), **p)
        self.bt_testar_tmdb = self._botao(lateral, "Testar conexão com o TMDB", self.ao_testar_tmdb)
        self.bt_testar_tmdb.pack(fill="x", pady=(0, 4), **p)
        self.lb_estado_tmdb = ctk.CTkLabel(lateral, text="", font=self.f_rotulo, text_color=Tema.TEXTO_FRACO,
                                           anchor="w", justify="left", wraplength=250)
        self.lb_estado_tmdb.pack(fill="x", pady=(0, 6), **p)
        self.cb_tmdb = self._checkbox(lateral, "Consultar o TMDB para confirmar nomes", self.var_jf_tmdb)
        self._checkbox(lateral, "Baixar pôster e backdrop (se faltarem)", self.var_jf_imagens)
        self._checkbox(lateral, "Criar arquivo .nfo (sinopse, duração...)", self.var_jf_nfo)
        self.var_jf_tmdbid = tk.BooleanVar(value=False)
        self.var_jf_exigir = tk.BooleanVar(value=False)
        self.cb_tmdbid = self._checkbox(lateral, "Incluir [tmdbid] no nome da pasta", self.var_jf_tmdbid)
        self.var_jf_nomes_ep = tk.BooleanVar(value=True)
        self._checkbox(lateral, "Séries: nome do episódio depois do\nnúmero (S01E07 - Nome)", self.var_jf_nomes_ep)
        self._checkbox(lateral, "Só mover o que estiver no catálogo", self.var_jf_exigir)

        self._separador(lateral)
        self._rotulo(lateral, "Limpeza", suave=False, fonte=self.f_secao).pack(anchor="w", pady=(0, 6), **p)
        self.var_jf_lixo = tk.BooleanVar(value=True)
        self._checkbox(lateral, "Apagar lixo do torrent (.url, .txt\nde propaganda, trailers < 100 MB)",
                       self.var_jf_lixo)
        self.var_jf_apagar_pasta = tk.BooleanVar(value=False)
        self._checkbox(lateral, "Apagar a pasta do torrent depois de\ntransferir (com o que sobrar nela)",
                       self.var_jf_apagar_pasta)
        self._rotulo(lateral, "Imagens (poster, backdrop...) e legendas\nlocais vão junto com o filme.",
                     fonte=ctk.CTkFont(Tema.FAMILIA, 11)).pack(anchor="w", pady=(2, 0), **p)

        self._separador(lateral)
        self._rotulo(lateral, "Automático", suave=False, fonte=self.f_secao).pack(anchor="w", pady=(0, 6), **p)
        self.var_jf_vigiar = tk.BooleanVar(value=False)
        self._checkbox(lateral, "Vigiar a pasta de origem e organizar\nsozinho o que terminar de baixar",
                       self.var_jf_vigiar, comando=self.ao_alternar_vigia)
        self.campo_vigia_min = self._numero(lateral, "Conferir a cada (min):", 5, 1, 240, 1)
        self._rotulo(lateral, "Pastas vigiadas, uma por linha (ex.: as do\nuTorrent). Filmes e séries são separados\n"
                              "sozinhos. Vazio = a pasta de origem acima.").pack(anchor="w", pady=(4, 2), **p)
        self.txt_pastas_vigiadas = ctk.CTkTextbox(lateral, height=64, font=self.f_rotulo, fg_color=Tema.CAMPO,
                                                  border_width=1, border_color=Tema.CAMPO_BORDA, text_color=Tema.TEXTO,
                                                  corner_radius=Tema.RAIO_CONTROLE, wrap="none")
        self.txt_pastas_vigiadas.pack(fill="x", **p)
        self._botao(lateral, "Adicionar pasta...", self._adicionar_pasta_vigiada, "fantasma").pack(
            anchor="w", pady=(2, 4), **p)
        # conferência automática dos espelhos (.strm), em horas ou dias
        self.var_jf_conferir_auto = tk.BooleanVar(value=False)
        self._checkbox(lateral, "Conferir os espelhos (.strm) sozinho e\navisar no Discord/Telegram se quebrar",
                       self.var_jf_conferir_auto, comando=self.ao_alternar_conferencia)
        linha = ctk.CTkFrame(lateral, fg_color="transparent")
        linha.pack(fill="x", padx=18, pady=(0, 6))
        self._rotulo(linha, "A cada:").pack(side="left")
        self.var_jf_conferir_unidade = tk.StringVar(value="dias")
        ctk.CTkOptionMenu(linha, variable=self.var_jf_conferir_unidade, values=["minutos", "horas", "dias"], width=96,
                          height=32, corner_radius=Tema.RAIO_CONTROLE, font=self.f_normal, fg_color=Tema.CAMPO,
                          button_color=Tema.SECUNDARIA, button_hover_color=Tema.SECUNDARIA_HOVER,
                          dropdown_fg_color=Tema.CARTAO, text_color=Tema.TEXTO).pack(side="right")
        self.campo_conferir_a_cada = CampoNumerico(linha, 7, 1, 999, 1, largura=102)
        self.campo_conferir_a_cada.pack(side="right", padx=(0, 6))
        self.var_jf_remover_quebrados = tk.BooleanVar(value=False)
        self._checkbox(lateral, "Remover os quebrados (dá para desfazer)", self.var_jf_remover_quebrados)
        self.var_jf_ultima_conferencia = tk.StringVar(value="")
        self.lb_estado_conferencia = ctk.CTkLabel(lateral, text="Última conferência: nunca.", font=self.f_rotulo,
                                                  text_color=Tema.TEXTO_FRACO, anchor="w", justify="left",
                                                  wraplength=250)
        self.lb_estado_conferencia.pack(fill="x", padx=18, pady=(0, 4))
        self.lb_estado_vigia = ctk.CTkLabel(lateral, text="Desligada. Usa as pastas e opções desta aba; o que ainda "
                                            "está baixando (.part, .!qB) fica para a próxima.",
                                            font=self.f_rotulo, text_color=Tema.TEXTO_FRACO, anchor="w",
                                            justify="left", wraplength=250)
        self.lb_estado_vigia.pack(fill="x", padx=18, pady=(0, 4))

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
        # height=1: vazio, um CTkFrame ocuparia 200 px (o padrão); assim só cresce com um campo dentro
        self.quadro_fonte = ctk.CTkFrame(lateral, fg_color="transparent", height=1)
        self.quadro_fonte.pack(fill="x")
        self.var_jf_chave_os = tk.StringVar()
        self.var_jf_url_site = tk.StringVar()
        self.var_jf_chave_subdl = tk.StringVar()
        self.rot_chave_os = self._rotulo(self.quadro_fonte, "Chave da API do OpenSubtitles:")
        self.campo_chave_os = self._entrada(self.quadro_fonte, self.var_jf_chave_os,
                                            "opensubtitles.com > API consumers", show="•")
        self.rot_chave_subdl = self._rotulo(self.quadro_fonte, "")
        self.campo_chave_subdl = self._entrada(self.quadro_fonte, self.var_jf_chave_subdl,
                                               "subdl.com > Painel > API", show="•")
        self.bt_testar_legendas = self._botao(self.quadro_fonte, "Testar chaves das legendas",
                                              self.ao_testar_legendas)
        self.lb_estado_legendas = ctk.CTkLabel(self.quadro_fonte, text="", font=self.f_rotulo,
                                               text_color=Tema.TEXTO_FRACO, anchor="w", justify="left",
                                               wraplength=250)
        self.campo_url_site = self._entrada(self.quadro_fonte, self.var_jf_url_site,
                                            "https://site/busca?q={consulta}")
        self._rotulo(lateral, "Idiomas das legendas (um arquivo cada):").pack(anchor="w", pady=(10, 2), **p)
        self.vars_idioma_jf = {codigo: tk.BooleanVar(value=(codigo == "pt-BR")) for codigo, _ in self.IDIOMAS_JF}
        for codigo, nome in self.IDIOMAS_JF:
            self._checkbox(lateral, f"{nome} ({codigo})", self.vars_idioma_jf[codigo])
        self._rotulo(lateral, "Outros idiomas:").pack(anchor="w", pady=(4, 0), **p)
        self.var_jf_outros_idiomas = tk.StringVar()
        self._entrada(lateral, self.var_jf_outros_idiomas, "ex.: fr, it, de").pack(fill="x", pady=(2, 4), **p)
        self.var_jf_sobrescrever = tk.BooleanVar(value=False)
        self._checkbox(lateral, "Substituir o que já existe (legendas,\npôster, backdrop e .nfo)",
                       self.var_jf_sobrescrever)

        self._separador(lateral)
        self._rotulo(lateral, "Servidor Jellyfin", suave=False, fonte=self.f_secao).pack(anchor="w", pady=(0, 6), **p)
        self.var_jf_url = tk.StringVar(value="http://localhost:8096")
        self.var_jf_chave_jellyfin = tk.StringVar()
        self.var_jf_atualizar = tk.BooleanVar(value=True)
        self._rotulo(lateral, "Endereço do servidor:").pack(anchor="w", **p)
        self._entrada(lateral, self.var_jf_url, "http://localhost:8096").pack(fill="x", pady=(2, 6), **p)
        self._rotulo(lateral, "Chave de API do Jellyfin:").pack(anchor="w", **p)
        self._entrada(lateral, self.var_jf_chave_jellyfin, "Painel > Avançado > Chaves de API",
                      show="•").pack(fill="x", pady=(2, 6), **p)
        self._checkbox(lateral, "Atualizar a biblioteca no fim (scan)", self.var_jf_atualizar)
        self.bt_testar_jellyfin = self._botao(lateral, "Testar conexão", self.ao_testar_jellyfin)
        self.bt_testar_jellyfin.pack(fill="x", pady=(6, 0), **p)

        self._separador(lateral)
        self._rotulo(lateral, "Avisos (opcional)", suave=False, fonte=self.f_secao).pack(anchor="w", pady=(0, 6), **p)
        self.var_jf_discord = tk.StringVar()
        self.var_jf_telegram_token = tk.StringVar()
        self.var_jf_telegram_chat = tk.StringVar()
        for rotulo, var, dica, secreto in (
                ("Webhook do Discord:", self.var_jf_discord, "Canal > Integrações > Webhooks", True),
                ("Token do bot do Telegram:", self.var_jf_telegram_token, "criado com o @BotFather", True),
                ("Chat ID do Telegram:", self.var_jf_telegram_chat, "ex.: 123456789", False)):
            self._rotulo(lateral, rotulo).pack(anchor="w", **p)
            self._entrada(lateral, var, dica, **({"show": "•"} if secreto else {})).pack(fill="x", pady=(2, 6), **p)
        self.bt_testar_avisos = self._botao(lateral, "Enviar aviso de teste", self.ao_testar_avisos)
        self.bt_testar_avisos.pack(fill="x", pady=(0, 0), **p)

        self._separador(lateral)
        self.var_jf_lembrar = tk.BooleanVar(value=False)
        self._checkbox(lateral, "Lembrar as chaves neste computador", self.var_jf_lembrar)
        self._rotulo(lateral, "Sem marcar, chaves e tokens valem só até\nfechar o programa.",
                     fonte=ctk.CTkFont(Tema.FAMILIA, 11)).pack(anchor="w", pady=(2, 0), **p)
        ctk.CTkFrame(lateral, height=12, fg_color="transparent").pack()
        self._mostrar_campos_jf()

        self.tabela_jf, faixa = self._criar_tabela(
            corpo, "Arquivos", self.COLUNAS_JF,
            "Escolha as pastas e clique em Pré-visualizar. Nada é movido sem você confirmar.")
        self.tabela_jf.configure(displaycolumns=self.ORDEM_TELA_JF)
        self.tabela_jf.bind("<<TreeviewSelect>>", lambda e: self.ao_selecionar_jf())
        topo = self._topos_tabela[str(self.tabela_jf)]
        self._montar_filtros_jf(topo)
        # Botões no topo (ao lado do título), e não numa faixa embaixo: sobra mais altura para a lista
        faixa.grid_remove()
        self.bt_ampliar_jf = self._botao(topo, "⤢  Ampliar lista", self.alternar_lista_jf, "fantasma", largura=130)
        self.bt_ampliar_jf.pack(side="right")
        self.bt_abrir_log = self._botao(topo, "Abrir log", self.ao_abrir_log, "fantasma", largura=90)
        self.bt_abrir_log.pack(side="right", padx=(0, 4))
        self.bt_abrir_relatorio = self._botao(topo, "Abrir relatório", self.ao_abrir_relatorio, "fantasma",
                                              largura=120)
        self.bt_abrir_relatorio.pack(side="right", padx=(0, 4))
        self.bt_abrir_biblioteca = self._botao(topo, "Abrir pasta da biblioteca", self.ao_abrir_biblioteca,
                                               "fantasma")
        self.bt_abrir_biblioteca.pack(side="right", padx=(0, 4))
        self._lista_ampliada = False
        self._cartao_detalhe_jf = self._montar_detalhe_jf(corpo)
        self._cartao_console_jf = self._criar_console(corpo, linha=2, altura=70).master
        # A lista fica com a maior parte da altura (antes dividia com o console e mostrava ~3 linhas)
        corpo.grid_rowconfigure(0, weight=5, minsize=300)
        corpo.grid_rowconfigure(2, weight=1, minsize=140)          # o registro da ação: ~4 linhas à vista

    # Situações que dá para esconder/mostrar na tabela (o filtro é só visual).
    FILTROS_JF = (("mover", "Vai mover"), ("movido", "Movido"), ("organizado", "Já organizado"),
                  ("conflito", "Conflito"), ("nao_identificado", "Não identificado"), ("ignorado", "Ignorado"),
                  ("erro", "Erro"))

    def _montar_filtros_jf(self, topo) -> None:
        self._ordem_jf: list[str] = []          # todas as linhas, na ordem (visíveis ou não)
        self._categoria_jf: dict[str, str | None] = {}
        self.vars_filtro_jf = {chave: tk.BooleanVar(value=True) for chave, _ in self.FILTROS_JF}
        linha = ctk.CTkFrame(topo, fg_color="transparent")
        # before=: empacotada ANTES do título, ganha a largura toda embaixo (senão iria para o lado)
        linha.pack(side="bottom", fill="x", pady=(8, 0), before=topo.winfo_children()[0])
        self._rotulo(linha, "Mostrar:", fonte=ctk.CTkFont(Tema.FAMILIA, 11, "bold")).pack(side="left", padx=(0, 8))
        self.checks_filtro_jf: dict[str, ctk.CTkCheckBox] = {}
        self._totais_jf: dict[str, int] = {}
        self._totais_agendados = None
        for chave, texto in self.FILTROS_JF:
            self.checks_filtro_jf[chave] = ctk.CTkCheckBox(
                linha, text=f"{texto} (0)", variable=self.vars_filtro_jf[chave], command=self.aplicar_filtro_jf,
                font=ctk.CTkFont(Tema.FAMILIA, 11), text_color=Tema.TEXTO_SUAVE, fg_color=Tema.PRIMARIA,
                hover_color=Tema.PRIMARIA_HOVER, border_color=Tema.CAMPO_BORDA, checkbox_width=16,
                checkbox_height=16, corner_radius=4, border_width=2)
            self.checks_filtro_jf[chave].pack(side="left", padx=(0, 10))
        self.bt_mostrar_todos_jf = ctk.CTkButton(
            linha, text="Mostrar todos", command=self.mostrar_todos_jf, width=96, height=22, corner_radius=6,
            fg_color="transparent", hover_color=Tema.SECUNDARIA_HOVER, text_color=Tema.PRIMARIA,
            font=ctk.CTkFont(Tema.FAMILIA, 11, underline=True))
        self.bt_mostrar_todos_jf.pack(side="left")

    def mostrar_todos_jf(self) -> None:
        """Marca todas as caixas do filtro (nada fica escondido)."""
        for var in self.vars_filtro_jf.values():
            var.set(True)
        self.aplicar_filtro_jf()

    def _agendar_totais_jf(self) -> None:
        """Os totais ao lado de cada filtro ("Não identificado (540)"): recontados uma vez a cada
        pouco, e não a cada linha (com milhares de linhas, seria lento)."""
        if self._totais_agendados is None:
            self._totais_agendados = self.after(120, self._atualizar_totais_jf)

    def _atualizar_totais_jf(self) -> None:
        self._totais_agendados = None
        totais = {chave: 0 for chave, _ in self.FILTROS_JF}
        for categoria in self._categoria_jf.values():
            if categoria in totais:
                totais[categoria] += 1
        for chave, texto in self.FILTROS_JF:
            if self._totais_jf.get(chave) != totais[chave]:
                self.checks_filtro_jf[chave].configure(text=f"{texto} ({totais[chave]})")
        self._totais_jf = totais

    def _visivel_jf(self, iid: str) -> bool:
        categoria = self._categoria_jf.get(iid)
        return categoria is None or categoria not in self.vars_filtro_jf or self.vars_filtro_jf[categoria].get()

    def aplicar_filtro_jf(self) -> None:
        """Esconde/mostra as linhas conforme as caixas marcadas, mantendo a ordem original."""
        tabela = self.tabela_jf
        tabela.detach(*self._ordem_jf)
        for iid in self._ordem_jf:
            if self._visivel_jf(iid):
                tabela.move(iid, "", "end")
        self._atualizar_contador(tabela)

    def linhas_ocultas_jf(self, categoria: str) -> int:
        return sum(1 for iid in self._ordem_jf if self._categoria_jf.get(iid) == categoria and not self._visivel_jf(iid))

    def _montar_detalhe_jf(self, corpo) -> None:
        """Cartão 'Antes -> Depois' com a pasta e o arquivo, como estão e como vão ficar."""
        cartao = self._cartao(corpo)
        cartao.grid(row=1, column=1, sticky="ew", pady=(0, 14))
        cartao.grid_columnconfigure((1, 2), weight=1, uniform="d")
        self.lb_detalhe_titulo = ctk.CTkLabel(cartao, text="Antes → Depois  (clique numa linha da tabela)",
                                              font=self.f_secao, text_color=Tema.TEXTO, anchor="w")
        self.lb_detalhe_titulo.grid(row=0, column=0, columnspan=3, sticky="w", padx=18, pady=(10, 4))
        for coluna, texto in ((1, "Pasta"), (2, "Arquivo")):
            self._rotulo(cartao, texto, fonte=ctk.CTkFont(Tema.FAMILIA, 11, "bold")).grid(
                row=1, column=coluna, sticky="w", padx=(0, 8))
        self.var_antes_pasta, self.var_antes_arquivo = tk.StringVar(), tk.StringVar()
        self.var_depois_pasta, self.var_depois_arquivo = tk.StringVar(), tk.StringVar()
        for linha, (rotulo, cor, var_p, var_a) in enumerate(
                (("Antes", Tema.TEXTO_SUAVE, self.var_antes_pasta, self.var_antes_arquivo),
                 ("Depois", Tema.SUCESSO, self.var_depois_pasta, self.var_depois_arquivo)), start=2):
            ctk.CTkLabel(cartao, text=rotulo, font=self.f_botao, text_color=cor, width=60, anchor="w").grid(
                row=linha, column=0, sticky="w", padx=(18, 8), pady=3)
            for coluna, var in ((1, var_p), (2, var_a)):
                self._campo_leitura(cartao, var).grid(row=linha, column=coluna, sticky="ew", padx=(0, 8), pady=3)
        self.lb_detalhe_extras = ctk.CTkLabel(cartao, text="", font=self.f_rotulo, text_color=Tema.TEXTO_SUAVE,
                                              anchor="w", justify="left", wraplength=900)
        self.lb_detalhe_extras.grid(row=4, column=0, columnspan=3, sticky="w", padx=18, pady=(2, 8))
        return cartao

    def alternar_lista_jf(self) -> None:
        """'Ampliar lista': esconde o painel Antes → Depois e o console; a tabela ocupa tudo.
        O andamento continua no rodapé (porcentagem e barra)."""
        self._lista_ampliada = not self._lista_ampliada
        for cartao in (self._cartao_detalhe_jf, self._cartao_console_jf):
            if self._lista_ampliada:
                cartao.grid_remove()
            else:
                cartao.grid()
        self.bt_ampliar_jf.configure(text="⤡  Reduzir lista" if self._lista_ampliada else "⤢  Ampliar lista")

    def _campo_leitura(self, master, var) -> ctk.CTkEntry:
        """Campo só para ler (dá para selecionar e copiar, mas não editar)."""
        campo = ctk.CTkEntry(master, textvariable=var, height=32, corner_radius=8, border_width=1,
                             fg_color=Tema.CAMPO, border_color=Tema.CAMPO_BORDA, text_color=Tema.TEXTO,
                             font=self.f_rotulo)
        navegacao = ("Left", "Right", "Home", "End")
        campo.bind("<Key>", lambda e: None if e.keysym in navegacao or (e.state & 0x4) else "break")  # 0x4 = Ctrl
        return campo

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
        fonte = self.var_jf_fonte.get()
        for campo in (self.rot_chave_os, self.campo_chave_os, self.rot_chave_subdl, self.campo_chave_subdl,
                      self.campo_url_site, self.bt_testar_legendas, self.lb_estado_legendas):
            campo.pack_forget()
        if fonte == self.FONTES_LEGENDA[1]:                 # OpenSubtitles, com o SubDL de reserva
            self.rot_chave_os.pack(anchor="w", padx=18, pady=(8, 0))
            self.campo_chave_os.pack(fill="x", padx=18, pady=(2, 0))
            self.rot_chave_subdl.configure(text="Reserva: chave do SubDL (usada quando o\n"
                                                "OpenSubtitles atingir o limite; opcional):")
            self.rot_chave_subdl.pack(anchor="w", padx=18, pady=(8, 0))
            self.campo_chave_subdl.pack(fill="x", padx=18, pady=(2, 0))
        elif fonte == self.FONTES_LEGENDA[3]:               # só o SubDL
            self.rot_chave_subdl.configure(text="Chave da API do SubDL:")
            self.rot_chave_subdl.pack(anchor="w", padx=18, pady=(8, 0))
            self.campo_chave_subdl.pack(fill="x", padx=18, pady=(2, 0))
        elif fonte == self.FONTES_LEGENDA[2]:
            self.campo_url_site.pack(fill="x", padx=18, pady=(8, 0))
        if fonte in (self.FONTES_LEGENDA[1], self.FONTES_LEGENDA[3]):   # fontes com chave: botão de teste
            self.bt_testar_legendas.pack(fill="x", padx=18, pady=(8, 2))
            self.lb_estado_legendas.pack(fill="x", padx=18)

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
            chave_opensubtitles=self.var_jf_chave_os.get().strip(), chave_subdl=self.var_jf_chave_subdl.get().strip(),
            url_site=self.var_jf_url_site.get().strip(),
            idioma=self.idiomas_jf(), sobrescrever=self.var_jf_sobrescrever.get(),
            lembrar_chaves=self.var_jf_lembrar.get(), imagens_tmdb=self.var_jf_imagens.get(),
            gerar_nfo=self.var_jf_nfo.get(), jellyfin_url=self.var_jf_url.get().strip(),
            jellyfin_api_key=self.var_jf_chave_jellyfin.get().strip(), atualizar_jellyfin=self.var_jf_atualizar.get(),
            discord_webhook=self.var_jf_discord.get().strip(), telegram_token=self.var_jf_telegram_token.get().strip(),
            telegram_chat_id=self.var_jf_telegram_chat.get().strip(),
            apagar_pasta_origem=self.var_jf_apagar_pasta.get(), nomes_episodios=self.var_jf_nomes_ep.get(),
            vigiar=self.var_jf_vigiar.get(), vigiar_min=self.campo_vigia_min.get(),
            pastas_vigiadas=tuple(self.pastas_vigiadas()),
            conferir_auto=self.var_jf_conferir_auto.get(), conferir_a_cada=self.campo_conferir_a_cada.get(),
            conferir_unidade=self.var_jf_conferir_unidade.get(), remover_quebrados=self.var_jf_remover_quebrados.get(),
            ultima_conferencia=self.var_jf_ultima_conferencia.get(),
            filtros_ocultos=tuple(c for c, v in self.vars_filtro_jf.items() if not v.get()))

    def idiomas_jf(self) -> str:
        """Idiomas marcados + 'Outros', ex.: 'pt-BR, en, fr' (sem nenhum: 'pt-BR')."""
        from jellyfin_tools.legendas import normalizar_idiomas
        marcados = [codigo for codigo, var in self.vars_idioma_jf.items() if var.get()]
        todos = normalizar_idiomas(marcados + normalizar_idiomas(self.var_jf_outros_idiomas.get()))
        return ", ".join(todos) or "pt-BR"

    def definir_idiomas_jf(self, texto: str) -> None:
        from jellyfin_tools.legendas import normalizar_idiomas
        idiomas = normalizar_idiomas(texto)
        for codigo, var in self.vars_idioma_jf.items():
            var.set(codigo in idiomas)
        self.var_jf_outros_idiomas.set(", ".join(i for i in idiomas if i not in self.vars_idioma_jf))

    def destinos_jellyfin(self) -> dict:
        """Pasta de Filmes e de Séries (cada modo tem a sua)."""
        self._destinos[self._modo_atual] = self.var_jf_destino.get()
        return {"Filmes": self._destinos["Filmes"].strip(), "Séries": self._destinos["Séries"].strip()}

    def definir_opcoes_jellyfin(self, dados: dict) -> None:
        """Preenche a aba com valores salvos (chaves que não existirem ficam como estão)."""
        textos = {"origem": self.var_jf_origem, "chave_tmdb": self.var_jf_chave_tmdb,
                  "chave_opensubtitles": self.var_jf_chave_os, "url_site": self.var_jf_url_site,
                  "chave_subdl": self.var_jf_chave_subdl,
                  "jellyfin_url": self.var_jf_url,
                  "jellyfin_api_key": self.var_jf_chave_jellyfin, "discord_webhook": self.var_jf_discord,
                  "telegram_token": self.var_jf_telegram_token, "telegram_chat_id": self.var_jf_telegram_chat}
        marcas = {"tmdb": self.var_jf_tmdb, "incluir_tmdbid": self.var_jf_tmdbid,
                  "exigir_catalogo": self.var_jf_exigir, "legendas": self.var_jf_legendas,
                  "limpar_lixo": self.var_jf_lixo, "imagens_tmdb": self.var_jf_imagens,
                  "apagar_pasta_origem": self.var_jf_apagar_pasta, "nomes_episodios": self.var_jf_nomes_ep,
                  "vigiar": self.var_jf_vigiar, "conferir_auto": self.var_jf_conferir_auto,
                  "remover_quebrados": self.var_jf_remover_quebrados,
                  "gerar_nfo": self.var_jf_nfo, "atualizar_jellyfin": self.var_jf_atualizar,
                  "sobrescrever": self.var_jf_sobrescrever, "lembrar_chaves": self.var_jf_lembrar}
        for chave, var in textos.items():
            if dados.get(chave):
                var.set(dados[chave])
        for chave, var in marcas.items():
            if chave in dados:
                var.set(bool(dados[chave]))
        if dados.get("idioma"):
            self.definir_idiomas_jf(dados["idioma"])
        if dados.get("vigiar_min"):
            self.campo_vigia_min.set(float(dados["vigiar_min"]))
        if dados.get("pastas_vigiadas"):
            self.definir_pastas_vigiadas(list(dados["pastas_vigiadas"]))
        if dados.get("conferir_a_cada"):
            self.campo_conferir_a_cada.set(float(dados["conferir_a_cada"]))
        if dados.get("conferir_unidade") in ("minutos", "horas", "dias"):
            self.var_jf_conferir_unidade.set(dados["conferir_unidade"])
        if dados.get("ultima_conferencia"):
            self.var_jf_ultima_conferencia.set(dados["ultima_conferencia"])
        if "filtros_ocultos" in dados:
            for chave, var in self.vars_filtro_jf.items():
                var.set(chave not in dados["filtros_ocultos"])
        if dados.get("fonte_legenda") in self.FONTES_LEGENDA:
            self.var_jf_fonte.set(dados["fonte_legenda"])
        self._destinos["Filmes"] = dados.get("destino_filmes", self._destinos["Filmes"])
        self._destinos["Séries"] = dados.get("destino_series", self._destinos["Séries"])
        self.var_jf_destino.set(self._destinos[self._modo_atual])
        self._mostrar_campos_jf()

    def limpar_tabela_jf(self) -> None:
        self.tabela_jf.delete(*self._ordem_jf)
        self._ordem_jf.clear()
        self._categoria_jf.clear()
        self._atualizar_contador(self.tabela_jf)
        self._agendar_totais_jf()

    def adicionar_linha_jf(self, iid: str, numero: int, situacao: str, tipo: str | None,
                           atual: str, novo: str, legenda: str = "", progresso: str = "",
                           categoria: str | None = None, fonte: str = "") -> None:
        """tipo: 'ok', 'erro', 'pulado' ou None (linha neutra).
        fonte: de onde veio o nome novo (coluna 'Nome via'), ex.: 'TMDB ✓'."""
        if tipo:
            situacao = f"{self.SIMBOLO_SITUACAO[tipo]}  {situacao}"
            tags = (tipo,)
        else:
            tags = ("par" if len(self.tabela_jf.get_children()) % 2 == 0 else "impar",)
        self.tabela_jf.insert("", "end", iid=iid, values=(numero, situacao, atual, novo, legenda, progresso, fonte),
                              tags=tags)
        self._ordem_jf.append(iid)
        self._categoria_jf[iid] = categoria
        if not self._visivel_jf(iid):
            self.tabela_jf.detach(iid)                 # escondida pelo filtro (continua existindo)
        self._atualizar_contador(self.tabela_jf)
        if categoria is not None:
            self._agendar_totais_jf()

    def atualizar_linha_jf(self, iid: str, legenda: str | None = None, legenda_tipo: str | None = None) -> None:
        if not self.tabela_jf.exists(iid):
            return
        valores = list(self.tabela_jf.item(iid, "values"))
        if legenda is not None:
            simbolo = self.SIMBOLO_SITUACAO.get(legenda_tipo or "", "")
            valores[4] = f"{simbolo}  {legenda}" if simbolo else legenda
        self.tabela_jf.item(iid, values=valores)
        if self._visivel_jf(iid):
            self.tabela_jf.see(iid)

    @staticmethod
    def barra_texto(fracao: float) -> str:
        """0.4 -> '████░░░░░░  40%' (barrinha de texto: a tabela não aceita widgets dentro)."""
        fracao = min(max(fracao, 0.0), 1.0)
        cheios = int(round(fracao * 10))
        return "█" * cheios + "░" * (10 - cheios) + f" {int(fracao * 100):3d}%"

    def definir_progresso_linha_jf(self, iid: str, fracao: float | None, texto: str | None = None) -> None:
        """Atualiza a coluna Progresso de uma linha (fracao None + texto = mostra só o texto)."""
        if not self.tabela_jf.exists(iid):
            return
        valores = list(self.tabela_jf.item(iid, "values"))
        valores[5] = texto if fracao is None else self.barra_texto(fracao)
        self.tabela_jf.item(iid, values=valores)

    def atualizar_situacao_jf(self, iid: str, texto: str, tipo: str | None, categoria: str | None = None) -> None:
        if not self.tabela_jf.exists(iid):
            return
        valores = list(self.tabela_jf.item(iid, "values"))
        valores[1] = f"{self.SIMBOLO_SITUACAO[tipo]}  {texto}" if tipo else texto
        tags = (tipo,) if tipo else self.tabela_jf.item(iid, "tags")
        self.tabela_jf.item(iid, values=valores, tags=tags)
        if categoria is not None and categoria != self._categoria_jf.get(iid):
            estava_visivel = self._visivel_jf(iid)
            self._categoria_jf[iid] = categoria        # ex.: "vai mover" virou "movido"
            self._agendar_totais_jf()
            if estava_visivel and not self._visivel_jf(iid):
                self.tabela_jf.detach(iid)             # só esta linha (rápido)
                self._atualizar_contador(self.tabela_jf)
            elif not estava_visivel and self._visivel_jf(iid):
                self.aplicar_filtro_jf()               # reaparece na posição certa (raro)
        if self._visivel_jf(iid):
            self.tabela_jf.see(iid)

    def pastas_vigiadas(self) -> list[str]:
        return [linha.strip() for linha in self.txt_pastas_vigiadas.get("1.0", "end").splitlines() if linha.strip()]

    def definir_pastas_vigiadas(self, pastas) -> None:
        if isinstance(pastas, str):
            pastas = pastas.splitlines()
        self.txt_pastas_vigiadas.delete("1.0", "end")
        self.txt_pastas_vigiadas.insert("1.0", "\n".join(p for p in pastas if p.strip()))

    def _adicionar_pasta_vigiada(self) -> None:
        pasta = filedialog.askdirectory()
        if pasta and pasta not in self.pastas_vigiadas():
            self.definir_pastas_vigiadas(self.pastas_vigiadas() + [pasta])

    def definir_estado_conferencia(self, texto: str, ok: bool | None = None) -> None:
        cor = {True: Tema.SUCESSO, False: Tema.PERIGO}.get(ok, Tema.TEXTO_FRACO)
        self.lb_estado_conferencia.configure(text=texto, text_color=cor)

    def definir_estado_vigia(self, texto: str, ligada: bool) -> None:
        self.lb_estado_vigia.configure(text=texto, text_color=Tema.SUCESSO if ligada else Tema.TEXTO_FRACO)

    def definir_estado_legendas(self, texto: str, ok: bool | None) -> None:
        """Linha abaixo de 'Testar chaves das legendas' (uma linha por fonte)."""
        cor = {True: Tema.SUCESSO, False: Tema.PERIGO}.get(ok, Tema.TEXTO_FRACO)
        self.lb_estado_legendas.configure(text=texto, text_color=cor)

    def definir_estado_tmdb(self, ok: bool | None, texto: str) -> None:
        """Linha abaixo do botão 'Testar conexão com o TMDB': verde (ok), vermelha (erro) ou neutra."""
        cor = {True: Tema.SUCESSO, False: Tema.PERIGO}.get(ok, Tema.TEXTO_FRACO)
        simbolo = {True: self.SIMBOLO_SITUACAO["ok"] + "  ", False: self.SIMBOLO_SITUACAO["erro"] + "  "}.get(ok, "")
        self.lb_estado_tmdb.configure(text=simbolo + texto if texto else "", text_color=cor)

    def definir_progresso_rodape(self, fracao: float, texto: str = "") -> None:
        """Rodapé com a PORCENTAGEM: a barra deixa de ser a animação 'vai e volta' e passa a
        mostrar quanto já foi feito; o texto vira ex.: 'Pré-visualizando... 45%  ·  Analisando: 75 de 166'."""
        if not self._ocupado:
            return
        if self._barra_animada:
            self.barra.stop()
            self.barra.configure(mode="determinate")
            self._barra_animada = False
        fracao = min(max(fracao, 0.0), 1.0)
        self.barra.set(fracao)
        self.var_status.set(f"{self._status_base} {int(fracao * 100)}%" + (f"  ·  {texto}" if texto else ""))

    def definir_progresso_total(self, fracao: float | None, texto: str = "") -> None:
        """Barra e texto de progresso TOTAL no topo dos consoles ('O que está acontecendo')
        e a porcentagem no rodapé."""
        if fracao is not None:
            self.definir_progresso_rodape(fracao)
        for rotulo, barra in self._progresso_total:
            if fracao is None:
                rotulo.configure(text="")
                barra.pack_forget()
            else:
                rotulo.configure(text=texto)
                if not barra.winfo_ismapped():
                    barra.pack(side="right", padx=(0, 12))
                barra.set(min(max(fracao, 0.0), 1.0))

    def mostrar_detalhe_jf(self, titulo: str, antes_pasta: str = "", antes_arquivo: str = "",
                           depois_pasta: str = "", depois_arquivo: str = "", extras: str = "") -> None:
        """Painel 'Antes → Depois': pasta e arquivo como estão e como vão ficar."""
        self.lb_detalhe_titulo.configure(text=titulo)
        for var, valor in ((self.var_antes_pasta, antes_pasta), (self.var_antes_arquivo, antes_arquivo),
                           (self.var_depois_pasta, depois_pasta), (self.var_depois_arquivo, depois_arquivo)):
            var.set(valor)
        self.lb_detalhe_extras.configure(text=extras)

    def liberar_organizar(self, sim: bool) -> None:
        """O botão Organizar só funciona depois de uma pré-visualização."""
        self._organizar_liberado = sim
        self.bt_organizar.configure(state="normal" if sim and not self._ocupado else "disabled")

    def marcar_navegador(self) -> None:
        self.var_nav.set(True)

    def limpar_tabela(self) -> None:
        self.tabela.delete(*self.tabela.get_children())
        self._atualizar_contador(self.tabela)
        self._atualizar_selecao()

    def adicionar_video(self, iid: str, numero: int, situacao: str, titulo: str, origem: str, link: str,
                        conteudo: str = "", licenca: str = "") -> None:
        """conteudo: 'Filme', 'Série' ou '—'; licenca: a informada pelo site (archive.org)."""
        listra = "par" if len(self.tabela.get_children()) % 2 == 0 else "impar"
        self.tabela.insert("", "end", iid=iid, values=(numero, situacao, titulo, origem, link, conteudo, licenca),
                           tags=(listra,))
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

    def selecionar_todos(self) -> None:
        self.tabela.selection_set(self.tabela.get_children())

    def selecionar_filmes_e_series(self) -> None:
        """Só o que dá para espelhar no Jellyfin (Tipo = Filme ou Série; o "—" fica de fora)."""
        self.tabela.selection_set([i for i in self.tabela.get_children()
                                   if self.tabela.set(i, "conteudo") in ("Filme", "Série")])

    def limpar_selecao(self) -> None:
        self.tabela.selection_remove(self.tabela.selection())

    def _atualizar_selecao(self) -> None:
        quantos = len(self.tabela.selection())
        self.lb_selecao.configure(
            text=f"{quantos} de {len(self.tabela.get_children())} selecionado(s)" if quantos
            else "Ctrl+clique ou Shift+clique para escolher vários",
            text_color=Tema.TEXTO if quantos else Tema.TEXTO_FRACO)

    def selecionados(self) -> list[str]:
        """iids das linhas selecionadas (ou a linha em foco)."""
        ids = list(self.tabela.selection())
        if not ids and self.tabela.focus():
            ids = [self.tabela.focus()]
        return ids

    MAX_REGISTROS = 30                    # ações guardadas no seletor (as mais antigas saem)

    def iniciar_registro(self, titulo: str) -> None:
        """Começa o registro de uma nova ação ('13:24:05 · Organizando') e passa a mostrá-lo."""
        numero = int(self._registros[-1]["titulo"].split(".", 1)[0]) + 1
        self._registros.append({"titulo": f"{numero}. {datetime.now():%H:%M:%S} · {titulo}", "partes": []})
        del self._registros[:-self.MAX_REGISTROS]
        self._mostrar_registro(len(self._registros) - 1)

    def _nomes_registros(self) -> list[str]:
        return [r["titulo"] for r in reversed(self._registros)]          # o mais novo primeiro

    def _ao_escolher_registro(self, titulo: str) -> None:
        indice = next((i for i, r in enumerate(self._registros) if r["titulo"] == titulo), None)
        if indice is not None:
            self._mostrar_registro(indice)

    def _mostrar_registro(self, indice: int) -> None:
        """Troca o que os consoles mostram pelo registro escolhido."""
        self._registro_visivel = indice
        registro = self._registros[indice]
        for menu in self._menus_registro:
            menu.configure(values=self._nomes_registros())
            menu.set(registro["titulo"])
        for console in self.logs:
            console.configure(state="normal")
            console.delete("1.0", "end")
            console.configure(state="disabled")
        for parte in registro["partes"]:
            self._inserir_nos_consoles(parte)

    def escrever_log(self, texto: str) -> None:
        """Acrescenta texto ao registro da ação ATUAL (e aos consoles, se ela estiver à mostra).
        '\\r' volta ao início da linha (barra de progresso)."""
        self._registros[-1]["partes"].append(texto)
        if self._registro_visivel == len(self._registros) - 1:
            self._inserir_nos_consoles(texto)

    def _inserir_nos_consoles(self, texto: str) -> None:
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
        """Limpa o registro que está à mostra."""
        self._registros[self._registro_visivel]["partes"].clear()
        for console in self.logs:
            console.configure(state="normal")
            console.delete("1.0", "end")
            console.configure(state="disabled")

    def definir_status(self, texto: str, ocupado: bool | None = None) -> None:
        self.var_status.set(texto)
        self._status_base = texto                     # a porcentagem é acrescentada depois dele
        if ocupado is not None:
            self.definir_ocupado(ocupado)

    def definir_ocupado(self, ocupado: bool) -> None:
        """Liga/desliga botões, a barra animada e a cor do indicador."""
        self._ocupado = ocupado
        estado = "disabled" if ocupado else "normal"
        for b in (self.bt_buscar, self.bt_baixar_sel, self.bt_baixar_todos, self.bt_login,
                  self.bt_previa, self.bt_legendas, self.bt_desfazer, self.bt_testar_jellyfin,
                  self.bt_testar_avisos, self.bt_testar_tmdb, self.bt_espelhar, self.bt_testar_legendas,
                  self.bt_conferir_espelhos, self.bt_relatorio, self.bt_gerenciar_espelhos):
            b.configure(state=estado)
        self.bt_organizar.configure(state="normal" if self._organizar_liberado and not ocupado else "disabled")
        for parar in (self.bt_parar, self.bt_parar_jf):
            parar.configure(state="normal" if ocupado else "disabled",
                            border_color=Tema.PERIGO if ocupado else Tema.CAMPO_BORDA)
        self.indicador.configure(fg_color=Tema.AVISO if ocupado else Tema.SUCESSO)
        if ocupado:
            self.barra.configure(mode="indeterminate", progress_color=Tema.PRIMARIA)
            self.barra.start()
            self._barra_animada = True
        else:
            self.barra.stop()
            self._barra_animada = False
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

    def escolher(self, titulo: str, mensagem: str, opcoes: tuple[str, ...]) -> str | None:
        """Pergunta com vários botões; devolve o texto do escolhido (None = Cancelar)."""
        dialogo = DialogoModerno(self, titulo, mensagem, "info", opcoes=opcoes)
        self.wait_window(dialogo)
        return dialogo.resposta

    def _atualizar_contador(self, tabela) -> None:
        contador, vazio = self._extras_tabela[str(tabela)]
        visiveis = len(tabela.get_children())
        total = len(self._ordem_jf) if str(tabela) == str(getattr(self, "tabela_jf", "")) else visiveis
        texto = str(total) if visiveis == total else f"{visiveis} de {total}"
        # Velocidade: com milhares de linhas isto roda a cada linha; redesenhar o rótulo do CTk
        # (e trocar a largura) só quando o texto muda de verdade.
        anterior = self._contadores.get(str(tabela))
        if anterior == (texto, bool(total)):
            return
        self._contadores[str(tabela)] = (texto, bool(total))
        if anterior is None or anterior[0] != texto:
            contador.configure(text=texto, width=34 if visiveis == total else 80)
        if anterior is None or anterior[1] != bool(total):
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

    def ao_selecionar_jf(self) -> None:
        pass

    def ao_testar_tmdb(self) -> None:
        pass

    def ao_espelhar_jellyfin(self) -> None:
        pass

    def ao_testar_legendas(self) -> None:
        pass

    def ao_conferir_espelhos(self) -> None:
        pass

    def ao_alternar_vigia(self) -> None:
        pass

    def ao_gerenciar_espelhos(self) -> None:
        pass

    def ao_abrir_relatorio(self) -> None:
        pass

    def ao_relatorio(self) -> None:
        pass

    def ao_alternar_conferencia(self) -> None:
        pass

    def ao_testar_jellyfin(self) -> None:
        pass

    def ao_testar_avisos(self) -> None:
        pass

    def ao_abrir_log(self) -> None:
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
