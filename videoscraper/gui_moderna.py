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

import re
import sys
import tkinter as tk
from dataclasses import dataclass
from typing import NamedTuple
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, ttk

import customtkinter as ctk

from jellyfin_tools import voz_clonada, voz_cloud

from . import icone


def _icone_do_maestro(self) -> None:
    """O CustomTkinter põe o ícone DELE em cada janela/diálogo 200 ms depois de abrir (no Windows), a menos
    que o programa já tenha posto um: aqui, o do Maestro."""
    try:
        if not getattr(self, "_iconbitmap_method_called", False):
            icone.aplicar(self)
    except Exception:
        pass


for _classe in (ctk.CTk, ctk.CTkToplevel):
    if hasattr(_classe, "_windows_set_titlebar_icon"):
        _classe._windows_set_titlebar_icon = _icone_do_maestro


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
    ignorar_robots: bool = False      # só sites seus/autorizados; o programa confirma a cada busca
    clicar_play: bool = True          # com o navegador: clica no poster/play e espera o vídeo carregar
    espelhar: bool = False            # modo híbrido: os botões "Baixar" criam .strm no Jellyfin em vez de baixar


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
    vigia_no_lugar: bool = True      # cada pasta vigiada se organiza dentro dela mesma (não usa as bibliotecas)
    pastas_protegidas: tuple = ()    # pastas que o organizador nunca mexe (ex.: as do Sonarr/Radarr)
    conferir_auto: bool = False      # conferir os .strm sozinho
    conferir_a_cada: float = 7
    conferir_unidade: str = "dias"   # "minutos", "horas" ou "dias"
    remover_quebrados: bool = False
    ultima_conferencia: str = ""     # data/hora (ISO) da última conferência automática
    avisar_versao: bool = True       # ao abrir, avisar se saiu versão nova (página Releases do GitHub)
    atualizar_sozinho: bool = False  # versão nova: baixa, instala e reinicia o programa sozinho (quando livre)
    versao_avisada: str = ""         # a última versão já avisada (não repete o aviso a cada abertura)
    fechar_na_bandeja: bool = False  # o X esconde a janela perto do relógio (a vigia continua)
    chave_claude: str = ""           # API da Anthropic: traduzir legendas (vazio = variável ANTHROPIC_API_KEY)
    modelo_traducao: str = "claude-sonnet-4-6"
    motor_traducao: str = "Claude"   # "Claude" (pago, melhor) ou "Local" (grátis, no PC: modelos Argos)
    modelo_whisper: str = "small"    # legenda pelo áudio: tamanho do modelo do Whisper (maior = acerta mais, demora mais)
    whisper_gpu: bool = False        # usar a placa de vídeo NVIDIA na transcrição
    voz_dublagem: str = "faber"      # dublagem por IA: a voz sintética do Piper
    motor_voz: str = "Piper (grátis, no PC)"   # ou "Gemini (premium, Google AI Studio)"
    voz_gemini: str = "Charon"       # voz do Gemini: pronta ("Kore") ou clonada com consentimento ("clone:Izael")
    chave_gemini: str = ""           # Google AI Studio > Get API key (vazio = variável GEMINI_API_KEY)
    encurtar_falas: bool = True      # dublagem: o Claude reescreve mais curtas as falas que não cabem no tempo
    voz_por_personagem: bool = False  # Gemini: ouve o filme, separa quem fala e dá uma voz para cada personagem
    figurantes_piper: bool = False   # dublagem mista: quem fala pouco (figurante) fica com o Piper, grátis
    limite_figurante: int = 20       # dublagem mista: figurante = quem tem menos falas que isso
    traducao_economica: bool = False  # Claude: tradução em LOTE (metade do preço, pronta em até 24 h)
    usar_roteiro: bool = True        # voz por personagem: o roteiro ao lado do vídeo diz quem fala (Gemini ouve menos)
    vozes_sem_tabela: bool = False   # voz por personagem: escolhe as vozes sozinho (sem abrir a tabela de conferir)
    figurantes_cloud: bool = False   # mista: figurantes no Google Cloud enquanto a cota grátis do mês der (depois Piper)
    perguntar_filmes: bool = True    # Gemini com vários filmes: perguntar quais vão com o Gemini (o resto, Piper)
    robo_so_piper: bool = False      # robôs agendados (--dublar): só o Piper, sem custo
    guardar_gravacoes: bool = False  # voz clonada: guardar as gravações no PC (para clonar de novo com um clique)
    tipo_cloud: str = "Neural2"      # Google Cloud TTS: Standard, WaveNet, Neural2 ou Studio
    voz_cloud: str = "pt-BR-Neural2-B"
    chave_cloud_tts: str = ""        # console.cloud.google.com > Credenciais (vazio = variável GOOGLE_TTS_API_KEY)
    teto_gastos: float = 0.0         # por mês nas APIs pagas (Claude + Gemini), na moeda abaixo; 0 = sem teto
    moeda_gastos: str = "R$"         # "R$" (com a cotação do dólar + IOF) ou "US$" (como as APIs cobram)
    cotacao_dolar: float = 0.0       # reais por dólar fixos; 0 = automática (PTAX do Banco Central)
    iof_cartao: float = 3.5          # % de IOF na compra internacional no cartão (confira na fatura)
    pasta_avulsos: str = ""          # "Vídeos avulsos": a caixa de entrada para legendar, traduzir e dublar
    avulsos_dublar: bool = True      # vídeos avulsos: dublar também (desmarcado = só a legenda em português)
    avulsos_legendar: bool = True    # vídeos avulsos: a legenda em português entra como faixa DENTRO do vídeo
    dublagem_no_original: bool = True   # a dublagem vira uma faixa do próprio arquivo (False: 'Nome - Dublado IA.mkv')
    separar_vozes: bool = True       # tira as vozes originais (IA no PC) e a dublagem entra sobre a música e os efeitos
    dublagem_previa: bool = True     # fase de teste: uma prévia para ouvir e aprovar antes de gravar no original
    ambientar_voz: bool = True       # a voz dublada ganha o tom, o volume e o eco das vozes originais (com a separação)
    separar_gpu: bool = True         # dublagem natural na placa de vídeo (DirectML); se não der, no processador
    minutos_teste: float = 2.0       # "Testar": legenda e dubla só esses minutos (gasta pouco) num vídeo curto
    resumo_diario: bool = False      # mandar no Discord/Telegram, uma vez por dia, o que o Maestro fez
    hora_resumo: int = 21


# Máximo dos campos "Máx. de páginas" e "Máx. de vídeos" (antes 2000 e 1000).
MAXIMO_ITENS = 100_000


# =============================================================================== componentes
class CampoNumerico(ctk.CTkFrame):
    """Seletor numérico moderno ( -  [ valor ]  + ). O CustomTkinter não tem Spinbox."""

    def __init__(self, master, valor: float, minimo: float, maximo: float, passo: float = 1,
                 decimal: bool = False, largura: int = 120, casas: int = 1, virgula: bool = False,
                 var: tk.StringVar | None = None):
        """casas: casas decimais mostradas; virgula: mostra '5,44' (dinheiro, jeito brasileiro). Digitar com ponto
        ou vírgula funciona nos dois casos. var: o mesmo valor em vários campos (mudar um muda todos)."""
        super().__init__(master, fg_color=Tema.CAMPO, corner_radius=Tema.RAIO_CONTROLE,
                         border_width=1, border_color=Tema.CAMPO_BORDA, width=largura, height=38)
        self.minimo, self.maximo, self.passo, self.decimal = minimo, maximo, passo, decimal
        self.casas, self.virgula = casas, virgula
        self.var = var if var is not None else tk.StringVar(value=self._formatar(valor))
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
        if not self.decimal:
            return str(int(valor))
        texto = f"{valor:.{getattr(self, 'casas', 1)}f}"
        return texto.replace(".", ",") if getattr(self, "virgula", False) else texto

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
                 opcoes: tuple[str, ...] = (), cancelar: str = "Cancelar"):
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
            ctk.CTkButton(botoes, text=cancelar, width=100, height=38, corner_radius=Tema.RAIO_CONTROLE,
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


class DialogoLista(ctk.CTkToplevel):
    """Escolher UM item de uma lista (ex.: qual das séries 'Tom and Jerry' do TMDB). `resposta` = o índice
    escolhido (None = Cancelar). Duplo clique ou Enter também escolhem."""

    def __init__(self, master, titulo: str, mensagem: str, itens: list[str], botao: str = "Usar esta",
                 marcado: int | None = None, procurar=None, termo: str = ""):
        """procurar(texto) -> novos itens (roda numa thread): mostra um campo para procurar outro nome."""
        super().__init__(master, fg_color=Tema.CARTAO)
        self.resposta = None
        self._procurar = procurar
        self._rodape_mensagem = "\n".join(mensagem.splitlines()[1:])   # ex.: "a escolha vale para N arquivos"
        self.title(titulo)
        self.transient(master)
        self.geometry("720x460")
        self.minsize(520, 340)
        ctk.CTkFrame(self, fg_color=Tema.PRIMARIA, height=4, corner_radius=0).pack(fill="x")
        ctk.CTkLabel(self, text=titulo, font=ctk.CTkFont(Tema.FAMILIA, 17, "bold"), text_color=Tema.TEXTO,
                     anchor="w").pack(fill="x", padx=24, pady=(16, 4))
        self.lb_mensagem = ctk.CTkLabel(self, text=mensagem, font=ctk.CTkFont(Tema.FAMILIA, 12),
                                        text_color=Tema.TEXTO_SUAVE, justify="left", anchor="w", wraplength=660)
        self.lb_mensagem.pack(fill="x", padx=24)
        if procurar is not None:                         # procurar outro nome sem fechar a lista
            busca = ctk.CTkFrame(self, fg_color="transparent")
            busca.pack(fill="x", padx=24, pady=(10, 0))
            self.var_termo = tk.StringVar(value=termo)
            self.campo_termo = ctk.CTkEntry(busca, textvariable=self.var_termo, height=34, fg_color=Tema.CAMPO,
                                            border_color=Tema.CAMPO_BORDA, text_color=Tema.TEXTO)
            self.campo_termo.pack(side="left", fill="x", expand=True)
            self.bt_procurar = ctk.CTkButton(busca, text="Procurar", width=100, height=34,
                                             corner_radius=Tema.RAIO_CONTROLE, fg_color=Tema.SECUNDARIA,
                                             hover_color=Tema.SECUNDARIA_HOVER, command=self.procurar)
            self.bt_procurar.pack(side="left", padx=(8, 0))
            self.campo_termo.bind("<Return>", lambda e: (self.procurar(), "break")[1])
        botoes = ctk.CTkFrame(self, fg_color="transparent")
        botoes.pack(side="bottom", fill="x", padx=24, pady=(8, 18))      # antes da lista: nunca some
        quadro = ctk.CTkFrame(self, fg_color=Tema.CAMPO, corner_radius=8)
        quadro.pack(fill="both", expand=True, padx=24, pady=(10, 0))
        self.lista = tk.Listbox(quadro, activestyle="none", selectmode="browse", exportselection=False, borderwidth=0,
                                highlightthickness=0, bg=Tema.CAMPO, fg=Tema.TEXTO, selectbackground=Tema.PRIMARIA,
                                selectforeground="white", font=(Tema.FAMILIA, 12))
        rolagem = ctk.CTkScrollbar(quadro, command=self.lista.yview, button_color=Tema.CARTAO_BORDA)
        self.lista.configure(yscrollcommand=rolagem.set)
        rolagem.pack(side="right", fill="y", pady=4)
        self.lista.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=6)
        if itens:
            self.lista.insert("end", *itens)
        escolhido = marcado if marcado is not None and 0 <= marcado < len(itens) else 0
        if itens:
            self.lista.selection_set(escolhido)
            self.lista.see(escolhido)
        ctk.CTkButton(botoes, text="Cancelar", width=100, height=36, corner_radius=Tema.RAIO_CONTROLE,
                      fg_color=Tema.SECUNDARIA, hover_color=Tema.SECUNDARIA_HOVER,
                      font=ctk.CTkFont(Tema.FAMILIA, 13), command=self.destroy).pack(side="left")
        ctk.CTkButton(botoes, text=botao, height=36, corner_radius=Tema.RAIO_CONTROLE, fg_color=Tema.PRIMARIA,
                      hover_color=Tema.PRIMARIA_HOVER, font=ctk.CTkFont(Tema.FAMILIA, 13, "bold"),
                      command=self._ok).pack(side="right")
        self.lista.bind("<Double-1>", lambda e: self._ok())
        self.lista.bind("<Return>", lambda e: self._ok())
        if procurar is None:
            self.bind("<Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self.destroy())
        self.update_idletasks()
        x = master.winfo_rootx() + (master.winfo_width() - 720) // 2
        y = master.winfo_rooty() + (master.winfo_height() - 460) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        try:
            self.grab_set()
        except tk.TclError:
            pass

    def _ok(self) -> None:
        selecao = self.lista.curselection()
        if selecao:
            self.resposta = int(selecao[0])
            self.destroy()

    def procurar(self) -> None:
        """Procura o nome digitado (numa thread: a janela não trava) e troca a lista pelo resultado."""
        import threading
        texto = self.var_termo.get().strip()
        if not texto or self._procurar is None:
            return
        self.bt_procurar.configure(state="disabled", text="Procurando...")
        resultado = {}

        def buscar():
            try:
                resultado["itens"] = self._procurar(texto)
            except Exception as erro:                 # sem internet, chave recusada...
                resultado["erro"] = str(erro)

        def esperar():
            if not self.winfo_exists():
                return
            if not resultado:
                self.after(100, esperar)
                return
            self.bt_procurar.configure(state="normal", text="Procurar")
            if "erro" in resultado:
                self.lb_mensagem.configure(text=f"Não deu para procurar \"{texto}\": {resultado['erro'][:120]}")
                return
            self.mostrar_itens(resultado["itens"], f"\"{texto}\": {len(resultado['itens'])} opção(ões).")
        threading.Thread(target=buscar, daemon=True).start()
        self.after(100, esperar)

    def mostrar_itens(self, itens: list[str], mensagem: str = "") -> None:
        self.lista.delete(0, "end")
        if itens:
            self.lista.insert("end", *itens)
            self.lista.selection_set(0)
            self.lista.see(0)
        if mensagem:
            self.lb_mensagem.configure(text=mensagem + ("" if itens else " Tente outro nome.")
                                       + (f"\n{self._rodape_mensagem}" if self._rodape_mensagem else ""))


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


# Uma pasta por linha; também aceita ";" e "," quando a vírgula separa dois caminhos ("E:\\A, E:\\B"). Uma
# vírgula no meio do nome de uma pasta ("Filmes, Séries") continua fazendo parte do nome.
_RE_SEPARA_PASTAS = re.compile(r"[\n;]|,\s*(?=[A-Za-z]:[\\/]|\\\\|/)")


def janela_de_filtro(dono, app, titulo: str, valores: list[tuple[str, int]], ativos, ao_aplicar,
                     botao: str = "Mostrar e selecionar"):
    """Janelinha do filtro de uma coluna (como no Excel): um campo para DIGITAR (a lista encolhe enquanto você
    escreve) e a lista para MARCAR um ou vários valores (☑). Leve mesmo com milhares de valores: é uma lista
    simples do Tk, não uma caixinha (widget) por valor, que travava a tela com 11 mil canais.
    valores: [(valor, quantos)]; ativos: os marcados agora (None = todos); ao_aplicar(escolhidos).
    Devolve (janela, (var_texto, marcados, aplicar)) - o segundo é para os testes digitarem/marcarem."""
    sem_acentos = {v: _sem_acentos(v) for v, _ in valores}       # calculado uma vez (a busca roda a cada letra)
    marcados = {v for v, _ in valores} if ativos is None else set(ativos)
    janela = ctk.CTkToplevel(dono, fg_color=Tema.CARTAO)
    janela.title(f"Filtrar: {titulo}")
    janela.transient(dono)
    janela.geometry("460x480")
    janela.minsize(360, 320)
    ctk.CTkLabel(janela, text=f"{titulo}: digite e/ou marque um ou vários", font=app.f_secao,
                 text_color=Tema.TEXTO, anchor="w").pack(fill="x", padx=16, pady=(14, 6))
    var_texto = tk.StringVar()
    campo = app._entrada(janela, var_texto, "Digite parte do valor (ex.: globo, 404, .org)", altura=32)
    campo.pack(fill="x", padx=16)
    quadro = ctk.CTkFrame(janela, fg_color=Tema.CAMPO, corner_radius=8)
    quadro.pack(fill="both", expand=True, padx=16, pady=(8, 0))
    lista = tk.Listbox(quadro, activestyle="none", selectmode="browse", exportselection=False, borderwidth=0,
                       highlightthickness=0, bg=Tema.CAMPO, fg=Tema.TEXTO, selectbackground=Tema.CAMPO,
                       selectforeground=Tema.TEXTO, font=(Tema.FAMILIA, 11))
    rolagem = ctk.CTkScrollbar(quadro, command=lista.yview, button_color=Tema.CARTAO_BORDA)
    lista.configure(yscrollcommand=rolagem.set)
    rolagem.pack(side="right", fill="y", pady=4)
    lista.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=6)
    lb_conta = ctk.CTkLabel(janela, text="", font=ctk.CTkFont(Tema.FAMILIA, 11), text_color=Tema.TEXTO_FRACO,
                            anchor="w")
    lb_conta.pack(fill="x", padx=16, pady=(4, 0))
    visiveis: list[tuple[str, int]] = []

    def linha(valor, quantos) -> str:
        return f"{'☑' if valor in marcados else '☐'}  {valor}  ({quantos})"

    def contar() -> None:
        lb_conta.configure(text=f"{len(visiveis)} de {len(valores)} valor(es) na lista · {len(marcados)} marcado(s)")

    def mostrar(*_):
        procura = _sem_acentos(var_texto.get().strip())
        visiveis[:] = [vq for vq in valores if procura in sem_acentos[vq[0]]]
        lista.delete(0, "end")
        if visiveis:
            lista.insert("end", *[linha(v, q) for v, q in visiveis])
        for i, (v, _) in enumerate(visiveis):
            if v not in marcados:
                lista.itemconfigure(i, fg=Tema.TEXTO_FRACO)
        contar()

    def trocar(indice: int) -> None:
        if not 0 <= indice < len(visiveis):
            return
        valor, quantos = visiveis[indice]
        marcados.symmetric_difference_update({valor})
        lista.delete(indice)
        lista.insert(indice, linha(valor, quantos))
        lista.itemconfigure(indice, fg=Tema.TEXTO if valor in marcados else Tema.TEXTO_FRACO)
        contar()

    def marcar_visiveis(marcar: bool) -> None:
        for v, _ in visiveis:
            (marcados.add if marcar else marcados.discard)(v)
        mostrar()

    espera = [None]

    def ao_digitar(*_):                         # espera a pessoa parar de digitar (não refaz a cada letra)
        if espera[0]:
            janela.after_cancel(espera[0])
        espera[0] = janela.after(150, mostrar)
    var_texto.trace_add("write", ao_digitar)
    lista.bind("<ButtonRelease-1>", lambda e: trocar(lista.nearest(e.y)))
    lista.bind("<space>", lambda e: trocar(lista.index("active")))

    botoes = ctk.CTkFrame(janela, fg_color="transparent")
    botoes.pack(fill="x", padx=16, pady=12)
    estilo = dict(height=30, corner_radius=6, fg_color="transparent", hover_color=Tema.SECUNDARIA_HOVER,
                  text_color=Tema.PRIMARIA, font=ctk.CTkFont(Tema.FAMILIA, 12), width=60)
    ctk.CTkButton(botoes, text="Todos", command=lambda: marcar_visiveis(True), **estilo).pack(side="left")
    ctk.CTkButton(botoes, text="Nenhum", command=lambda: marcar_visiveis(False), **estilo).pack(side="left",
                                                                                             padx=(4, 0))

    def aplicar():
        if espera[0]:
            janela.after_cancel(espera[0])
        # Como no Excel: com algo digitado, valem os MARCADOS que aparecem na lista (os que contêm o texto)
        procura = _sem_acentos(var_texto.get().strip())
        escolhidos = set(marcados)
        if procura:
            escolhidos = {v for v, _ in valores if v in marcados and procura in sem_acentos[v]} or {"\0nada"}
        ao_aplicar(escolhidos)
        janela.destroy()
    app._botao(botoes, botao, aplicar, "primario").pack(side="right")
    janela.bind("<Return>", lambda e: aplicar())
    janela.bind("<Escape>", lambda e: janela.destroy())
    mostrar()
    janela.update_idletasks()
    x = max(0, min(dono.winfo_pointerx() - 40, janela.winfo_screenwidth() - 480))
    y = max(0, min(dono.winfo_pointery() + 10, janela.winfo_screenheight() - 520))
    janela.geometry(f"+{x}+{y}")
    campo.focus_set()
    return janela, (var_texto, marcados, aplicar)


def numeros_do_texto(texto: str) -> set[int] | None:
    """"1-5, 8; 10 a 12" -> {1, 2, 3, 4, 5, 8, 10, 11, 12}. Texto que não é só números/intervalos -> None
    (aí a busca é pelo nome)."""
    juntos = re.sub(r"(\d)\s*(?:-|até|a)\s*(?=\d)", r"\1-", texto.strip().lower())
    partes = [p for p in re.split(r"[,;\s]+", juntos) if p]
    numeros: set[int] = set()
    for parte in partes:
        intervalo = re.fullmatch(r"(\d+)-(\d+)", parte)
        if intervalo:
            inicio, fim = sorted((int(intervalo[1]), int(intervalo[2])))
            if fim - inicio > 100_000:
                return None
            numeros.update(range(inicio, fim + 1))
        elif parte.isdigit():
            numeros.add(int(parte))
        else:
            return None
    return numeros or None


def dividir_pastas(texto: str) -> list[str]:
    return [p.strip().strip('"') for p in _RE_SEPARA_PASTAS.split(texto or "") if p.strip().strip('"')]


def _sem_acentos(texto: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn")


class JanelaCorrigirNome(ctk.CTkToplevel):
    """"Corrigir nome": você diz qual série (ou filme) é; o organizador guarda a regra e lembra."""

    def __init__(self, master, tipo: str, sugestao: str, onde: str, regra_atual: str = ""):
        super().__init__(master, fg_color=Tema.CARTAO)
        self.resposta = None
        serie = tipo == "serie"
        self.title("Corrigir nome")
        self.resizable(False, False)
        self.transient(master)
        corpo = ctk.CTkFrame(self, fg_color="transparent")
        corpo.pack(fill="both", expand=True, padx=26, pady=(20, 8))
        ctk.CTkLabel(corpo, text="Qual série é?" if serie else "Qual filme é?",
                     font=ctk.CTkFont(Tema.FAMILIA, 17, "bold"), text_color=Tema.TEXTO, anchor="w").pack(fill="x")
        explicacao = (f"Vale para TODOS os vídeos da pasta (e subpastas):\n{onde}\nO número do episódio continua "
                      "vindo do nome de cada arquivo." if serie else f"Vale para o arquivo:\n{onde}")
        if regra_atual:
            explicacao += f"\n\nRegra atual: {regra_atual}"
        ctk.CTkLabel(corpo, text=explicacao, font=master.f_rotulo, text_color=Tema.TEXTO_SUAVE, justify="left",
                     anchor="w", wraplength=440).pack(fill="x", pady=(6, 10))
        self.var_titulo, self.var_ano, self.var_temporada = tk.StringVar(value=sugestao), tk.StringVar(), tk.StringVar()
        campos = [("Nome" + (" da série" if serie else " do filme") + ":", self.var_titulo, "ex.: Breaking Bad"),
                  ("Ano (opcional, ajuda o TMDB):" if serie else "Ano:", self.var_ano, "ex.: 2008")]
        if serie:
            campos.append(("Temporada (opcional; vazio = numeração contínua):", self.var_temporada, "ex.: 5"))
        for rotulo, var, dica in campos:
            master._rotulo(corpo, rotulo).pack(anchor="w")
            master._entrada(corpo, var, dica, altura=34).pack(fill="x", pady=(2, 8))
        self.lb_erro = ctk.CTkLabel(corpo, text="", font=master.f_rotulo, text_color=Tema.PERIGO, anchor="w")
        self.lb_erro.pack(fill="x")
        botoes = ctk.CTkFrame(self, fg_color="transparent")
        botoes.pack(fill="x", padx=26, pady=(4, 20))
        master._botao(botoes, "Salvar e pré-visualizar", self._salvar, "primario").pack(side="right")
        master._botao(botoes, "Cancelar", self.destroy, "fantasma", largura=90).pack(side="right", padx=(0, 8))
        if regra_atual:
            master._botao(botoes, "Esquecer a regra", self._esquecer, "perigo").pack(side="left")
        self.bind("<Return>", lambda e: self._salvar())
        self.bind("<Escape>", lambda e: self.destroy())
        self.update_idletasks()
        x = master.winfo_rootx() + (master.winfo_width() - self.winfo_reqwidth()) // 2
        y = master.winfo_rooty() + (master.winfo_height() - self.winfo_reqheight()) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        try:
            self.grab_set()
        except tk.TclError:
            pass

    def _salvar(self) -> None:
        titulo = self.var_titulo.get().strip()
        ano, temporada = self.var_ano.get().strip(), self.var_temporada.get().strip()
        if not titulo:
            self.lb_erro.configure(text="Escreva o nome.")
            return
        if (ano and not (ano.isdigit() and 1880 <= int(ano) <= 2100)) or (temporada and not temporada.isdigit()):
            self.lb_erro.configure(text="Ano e temporada são números (ex.: 2008 e 5).")
            return
        self.resposta = {"titulo": titulo, "ano": int(ano) if ano else None,
                         "temporada": int(temporada) if temporada else None}
        self.destroy()

    def _esquecer(self) -> None:
        self.resposta = {"esquecer": True}
        self.destroy()


class JanelaNaoIdentificados(ctk.CTkToplevel):
    """Os não identificados da pré-visualização juntos por pasta (uma série costuma estar numa pasta só).
    grupos: [(pasta, quantos, motivo, exemplo)]. acoes: {'corrigir': f(posições), 'mostrar': f(posições)}."""

    def __init__(self, master, grupos: list[tuple[str, int, str, str]], acoes: dict):
        super().__init__(master, fg_color=Tema.CARTAO)
        self.title("Não identificados por pasta")
        self.geometry("1000x560")
        self.transient(master)
        total = sum(q for _, q, _, _ in grupos)
        ctk.CTkLabel(self, text=f"{total} não identificado(s) em {len(grupos)} pasta(s)", font=master.f_secao,
                     text_color=Tema.TEXTO, anchor="w").pack(fill="x", padx=20, pady=(16, 2))
        ctk.CTkLabel(self, text="Escolha uma ou mais pastas (Ctrl+clique) e clique em \"Corrigir nome\": você diz qual "
                     "série é e a regra vale para a pasta inteira (todos os arquivos dela de uma vez).",
                     font=master.f_rotulo, text_color=Tema.TEXTO_FRACO, anchor="w", justify="left",
                     wraplength=950).pack(fill="x", padx=20, pady=(0, 8))
        botoes = ctk.CTkFrame(self, fg_color="transparent")       # embaixo primeiro: a tabela é que encolhe
        botoes.pack(side="bottom", fill="x", padx=20, pady=14)
        quadro = ctk.CTkFrame(self, fg_color=Tema.CARTAO)
        quadro.pack(fill="both", expand=True, padx=20)
        self.tabela = ttk.Treeview(quadro, columns=("quantos", "motivo", "exemplo"), show="tree headings",
                                   selectmode="extended", style="Moderno.Treeview")
        for coluna, texto, largura in (("#0", "Pasta", 420), ("quantos", "Arquivos", 90), ("motivo", "Por quê", 220),
                                       ("exemplo", "Exemplo", 230)):
            self.tabela.heading(coluna, text=texto, anchor="w")
            self.tabela.column(coluna, width=largura, anchor="w", stretch=coluna in ("#0", "exemplo"))
        for n, (pasta, quantos, motivo, exemplo) in enumerate(grupos):
            self.tabela.insert("", "end", iid=str(n), text=pasta, values=(quantos, motivo, exemplo))
        self.tabela.pack(side="left", fill="both", expand=True)
        rolagem = ctk.CTkScrollbar(quadro, command=self.tabela.yview, button_color=Tema.CARTAO_BORDA)
        rolagem.pack(side="right", fill="y")
        self.tabela.configure(yscrollcommand=rolagem.set)
        master._botao(botoes, "Fechar", self.destroy, "fantasma", largura=90).pack(side="right")
        self.bt_corrigir = master._botao(botoes, "Corrigir nome da(s) pasta(s)...",
                                         lambda: self._com_selecao(acoes["corrigir"]), "primario")
        self.bt_corrigir.pack(side="right", padx=(0, 8))
        self.bt_mostrar = master._botao(botoes, "Mostrar na tabela", lambda: self._com_selecao(acoes["mostrar"]),
                                        "secundario")
        self.bt_mostrar.pack(side="right", padx=(0, 8))
        self.tabela.bind("<Double-1>", lambda e: self._com_selecao(acoes["corrigir"]))
        self.bind("<Escape>", lambda e: self.destroy())

    def _com_selecao(self, acao) -> None:
        escolhidos = [int(i) for i in self.tabela.selection()]
        if not escolhidos:
            self.master.mostrar_mensagem("Não identificados", "Escolha uma pasta da lista (Ctrl+clique para várias).",
                                         "aviso")
            return
        acao(escolhidos)


class DialogoCompletar(ctk.CTkToplevel):
    """"Completar biblioteca": o QUE completar (legendas, imagens, .nfo) e se troca o que já existe.
    `resultado`: {'legendas', 'imagens', 'nfo', 'substituir'} ou None (Cancelar)."""

    def __init__(self, master, pasta: str, padrao: dict, series: bool):
        super().__init__(master, fg_color=Tema.CARTAO)
        self.resultado = None
        self.title("Completar biblioteca")
        self.resizable(False, False)
        self.transient(master)
        corpo = ctk.CTkFrame(self, fg_color="transparent")
        corpo.pack(fill="both", expand=True, padx=26, pady=(20, 6))
        ctk.CTkLabel(corpo, text="Completar biblioteca", font=ctk.CTkFont(Tema.FAMILIA, 17, "bold"),
                     text_color=Tema.TEXTO, anchor="w").pack(fill="x")
        ctk.CTkLabel(corpo, text=pasta, font=master.f_rotulo, text_color=Tema.TEXTO_FRACO, anchor="w",
                     wraplength=440, justify="left").pack(fill="x", pady=(2, 10))
        ctk.CTkLabel(corpo, text="O que completar:", font=master.f_rotulo, text_color=Tema.TEXTO_SUAVE,
                     anchor="w").pack(fill="x")
        self.vars = {}
        imagens = ("Imagens: pôster e fundo da série e o pôster de cada temporada" if series
                   else "Imagens: pôster e fundo (backdrop) de cada filme")
        for chave, texto in (("legendas", "Legendas (nos idiomas escolhidos na aba)"), ("imagens", imagens),
                             ("nfo", "Arquivo .nfo (sinopse, elenco...; só filmes)")):
            self.vars[chave] = tk.BooleanVar(value=bool(padrao.get(chave, chave != "nfo" or not series)))
            caixa = master._checkbox(corpo, texto, self.vars[chave])
            caixa.pack_configure(padx=0)
            if chave == "nfo" and series:
                caixa.configure(state="disabled")
                self.vars[chave].set(False)
        ctk.CTkLabel(corpo, text="O que já existe:", font=master.f_rotulo, text_color=Tema.TEXTO_SUAVE,
                     anchor="w").pack(fill="x", pady=(10, 0))
        self.var_substituir = tk.StringVar(value="substituir" if padrao.get("substituir") else "falta")
        for valor, texto in (("falta", "Só o que falta (não mexe no que já está lá)"),
                             ("substituir", "Substituir o que já existe (ex.: pôster em inglês, legenda fora de sincronia)")):
            ctk.CTkRadioButton(corpo, text=texto, value=valor, variable=self.var_substituir, font=master.f_rotulo,
                               text_color=Tema.TEXTO, fg_color=Tema.PRIMARIA, hover_color=Tema.PRIMARIA_HOVER).pack(
                anchor="w", pady=3)
        ctk.CTkLabel(corpo, text="Os vídeos não são mexidos.", font=ctk.CTkFont(Tema.FAMILIA, 11),
                     text_color=Tema.TEXTO_FRACO, anchor="w").pack(fill="x", pady=(6, 0))
        botoes = ctk.CTkFrame(self, fg_color="transparent")
        botoes.pack(fill="x", padx=26, pady=(10, 20))
        master._botao(botoes, "Cancelar", self.destroy, "secundario").pack(side="left")
        master._botao(botoes, "Completar", self._ok, "primario").pack(side="right")
        self.bind("<Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self.destroy())
        self.update_idletasks()
        x = master.winfo_rootx() + (master.winfo_width() - self.winfo_reqwidth()) // 2
        y = master.winfo_rooty() + (master.winfo_height() - self.winfo_reqheight()) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        try:
            self.grab_set()
        except tk.TclError:
            pass

    def _ok(self) -> None:
        escolha = {chave: var.get() for chave, var in self.vars.items()}
        if not any(escolha.values()):
            self.master.mostrar_mensagem("Completar biblioteca", "Marque pelo menos uma coisa para completar.", "aviso")
            return
        self.resultado = {**escolha, "substituir": self.var_substituir.get() == "substituir"}
        self.destroy()


class DialogoAgendar(ctk.CTkToplevel):
    """"Agendar tarefas": uma caixa de marcar por comando de robô, botões para marcar todas/nenhuma, a frequência e
    o 1º horário na MESMA janela. `resultado`: {'acao': 'agendar'|'tirar', 'comandos': [...], 'frequencia', 'hora'}
    ou None (Cancelar). Várias marcadas: uma a cada 15 min a partir do horário (não rodam todas juntas)."""

    def __init__(self, master, comandos: dict, existentes: dict, frequencias: tuple, hora: str = "06:00"):
        super().__init__(master, fg_color=Tema.CARTAO)
        self.resultado = None
        self._existentes = existentes
        self.title("Agendar tarefas")
        self.resizable(False, False)
        self.transient(master)
        corpo = ctk.CTkFrame(self, fg_color="transparent")
        corpo.pack(fill="both", expand=True, padx=26, pady=(20, 6))
        ctk.CTkLabel(corpo, text="Agendar tarefas", font=ctk.CTkFont(Tema.FAMILIA, 17, "bold"),
                     text_color=Tema.TEXTO, anchor="w").pack(fill="x")
        ctk.CTkLabel(corpo, text="Marque o que o Maestro deve fazer sozinho, sem abrir a janela. As tarefas vão para o "
                     "Agendador de Tarefas do Windows (pasta \"Maestro\") e rodam com o computador ligado.",
                     font=master.f_rotulo, text_color=Tema.TEXTO_SUAVE, anchor="w", justify="left",
                     wraplength=520).pack(fill="x", pady=(2, 8))
        atalhos = ctk.CTkFrame(corpo, fg_color="transparent")
        atalhos.pack(fill="x", pady=(0, 4))
        self.bt_marcar_todas = master._botao(atalhos, "Marcar todas", lambda: self.marcar(True), "secundario")
        self.bt_marcar_todas.pack(side="left")
        self.bt_desmarcar = master._botao(atalhos, "Desmarcar todas", lambda: self.marcar(False), "secundario")
        self.bt_desmarcar.pack(side="left", padx=(8, 0))
        self.bt_marcar_agendadas = master._botao(atalhos, "Marcar as já agendadas", self.marcar_agendadas, "fantasma")
        self.bt_marcar_agendadas.pack(side="left", padx=(8, 0))
        if not existentes:
            self.bt_marcar_agendadas.configure(state="disabled")
        self.vars: dict[str, tk.BooleanVar] = {}
        for comando, texto in comandos.items():
            self.vars[comando] = tk.BooleanVar(value=False)
            extra = f"   ·   agendada (próxima: {existentes[comando]})" if comando in existentes else ""
            master._checkbox(corpo, texto + extra, self.vars[comando], comando=self._atualizar).pack_configure(padx=0)
        linha = ctk.CTkFrame(corpo, fg_color="transparent")
        linha.pack(fill="x", pady=(10, 0))
        ctk.CTkLabel(linha, text="Frequência:", font=master.f_rotulo, text_color=Tema.TEXTO_SUAVE).pack(side="left")
        self.var_frequencia = tk.StringVar(value=frequencias[0])
        self._frequencias = frequencias
        master._menu_opcoes(linha, self.var_frequencia, frequencias).pack(side="left", padx=(8, 16))
        ctk.CTkLabel(linha, text="1º horário:", font=master.f_rotulo, text_color=Tema.TEXTO_SUAVE).pack(side="left")
        self.var_hora = tk.StringVar(value=hora)
        self.menu_hora = master._menu_opcoes(linha, self.var_hora, [f"{h:02d}:{m:02d}" for h in range(24)
                                                                     for m in (0, 30)])
        self.menu_hora.pack(side="left", padx=(8, 0))
        self.var_frequencia.trace_add("write", lambda *a: self._atualizar())
        self.lb_resumo = ctk.CTkLabel(corpo, text="", font=ctk.CTkFont(Tema.FAMILIA, 11), text_color=Tema.TEXTO_FRACO,
                                      anchor="w", justify="left", wraplength=520)
        self.lb_resumo.pack(fill="x", pady=(8, 0))
        botoes = ctk.CTkFrame(self, fg_color="transparent")
        botoes.pack(fill="x", padx=26, pady=(10, 20))
        master._botao(botoes, "Cancelar", self.destroy, "secundario").pack(side="left")
        self.bt_tirar = master._botao(botoes, "Tirar do agendamento", lambda: self._ok("tirar"), "perigo")
        self.bt_tirar.pack(side="left", padx=(8, 0))
        self.bt_agendar = master._botao(botoes, "Agendar", lambda: self._ok("agendar"), "primario")
        self.bt_agendar.pack(side="right")
        self.bind("<Escape>", lambda e: self.destroy())
        self._atualizar()
        self.update_idletasks()
        x = master.winfo_rootx() + (master.winfo_width() - self.winfo_reqwidth()) // 2
        y = master.winfo_rooty() + (master.winfo_height() - self.winfo_reqheight()) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        try:
            self.grab_set()
        except tk.TclError:
            pass

    def marcados(self) -> list[str]:
        return [c for c, var in self.vars.items() if var.get()]

    def marcar(self, sim: bool) -> None:
        for var in self.vars.values():
            var.set(sim)
        self._atualizar()

    def marcar_agendadas(self) -> None:
        for comando, var in self.vars.items():
            var.set(comando in self._existentes)
        self._atualizar()

    def _atualizar(self) -> None:
        """Botões com a contagem ("Agendar 3 marcadas") e o resumo dos horários."""
        marcados = self.marcados()
        n = len(marcados)
        self.bt_agendar.configure(text=f"Agendar {n} marcada(s)" if n else "Agendar",
                                  state="normal" if n else "disabled")
        agendadas = [c for c in marcados if c in self._existentes]
        self.bt_tirar.configure(text=f"Tirar {len(agendadas)} do agendamento" if agendadas else "Tirar do agendamento",
                                state="normal" if agendadas else "disabled")
        cada_hora = self.var_frequencia.get() == self._frequencias[-1]
        self.menu_hora.configure(state="disabled" if cada_hora else "normal")
        if n > 1:
            self.lb_resumo.configure(text=f"{n} tarefas: uma a cada 15 minutos a partir do horário, para não "
                                          "rodarem todas juntas.")
        else:
            self.lb_resumo.configure(text="Marque uma ou várias (as caixas ou os botões acima)." if not n else "")

    def _ok(self, acao: str) -> None:
        marcados = self.marcados()
        if acao == "tirar":
            marcados = [c for c in marcados if c in self._existentes]
        if not marcados:
            return
        cada_hora = self.var_frequencia.get() == self._frequencias[-1]
        self.resultado = {"acao": acao, "comandos": marcados, "frequencia": self.var_frequencia.get(),
                          "hora": "00:00" if cada_hora else self.var_hora.get()}
        self.destroy()


def valor_da_voz(texto: str) -> str:
    """Do menu para o valor: "Kore (feminina, firme)" -> "Kore"; "Piper faber (grátis, no PC)" -> "piper:faber";
    "Clonada: Izael (autorizada por Izael)" -> "clone:Izael"; "Google Cloud pt-BR-Neural2-B (cota grátis)" ->
    "cloud:pt-BR-Neural2-B"."""
    clonada = voz_clonada.valor_do_menu(texto)
    if clonada:
        return clonada
    partes = texto.split()
    if not partes:
        return ""
    if partes[:2] == ["Google", "Cloud"] and len(partes) > 2:
        return f"cloud:{partes[2]}"
    return f"piper:{partes[1]}" if partes[0] == "Piper" and len(partes) > 1 else partes[0]


class DialogoMarcar(ctk.CTkToplevel):
    """Lista com caixas de marcar (ex.: quais filmes vão com a voz premium). `resultado`: índices marcados ou None."""

    def __init__(self, master, titulo: str, mensagem: str, itens: list[str], marcados: set[int], botao: str):
        super().__init__(master, fg_color=Tema.CARTAO)
        self.resultado = None
        self.title(titulo)
        self.resizable(False, False)
        self.transient(master)
        corpo = ctk.CTkFrame(self, fg_color="transparent")
        corpo.pack(fill="both", expand=True, padx=26, pady=(20, 6))
        ctk.CTkLabel(corpo, text=titulo, font=ctk.CTkFont(Tema.FAMILIA, 17, "bold"), text_color=Tema.TEXTO,
                     anchor="w").pack(fill="x")
        ctk.CTkLabel(corpo, text=mensagem, font=master.f_rotulo, text_color=Tema.TEXTO_SUAVE, anchor="w",
                     justify="left", wraplength=560).pack(fill="x", pady=(2, 8))
        atalhos = ctk.CTkFrame(corpo, fg_color="transparent")
        atalhos.pack(fill="x", pady=(0, 4))
        master._botao(atalhos, "Marcar todos", lambda: self._todos(True), "secundario").pack(side="left")
        master._botao(atalhos, "Desmarcar todos", lambda: self._todos(False), "secundario").pack(side="left",
                                                                                               padx=(8, 0))
        lista = ctk.CTkScrollableFrame(corpo, fg_color="transparent", height=min(320, 34 * len(itens) + 10))
        lista.pack(fill="x")
        self.vars = [tk.BooleanVar(value=i in marcados) for i in range(len(itens))]
        for texto, var in zip(itens, self.vars):
            master._checkbox(lista, texto, var).pack_configure(padx=0)
        botoes = ctk.CTkFrame(self, fg_color="transparent")
        botoes.pack(fill="x", padx=26, pady=(10, 20))
        master._botao(botoes, "Cancelar", self.destroy, "secundario").pack(side="left")
        self.bt_ok = master._botao(botoes, botao, self._ok, "primario")
        self.bt_ok.pack(side="right")
        self.bind("<Escape>", lambda e: self.destroy())
        self.update_idletasks()
        x = master.winfo_rootx() + (master.winfo_width() - self.winfo_reqwidth()) // 2
        y = master.winfo_rooty() + (master.winfo_height() - self.winfo_reqheight()) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        try:
            self.grab_set()
        except tk.TclError:
            pass

    def _todos(self, sim: bool) -> None:
        for var in self.vars:
            var.set(sim)

    def _ok(self) -> None:
        self.resultado = [i for i, var in enumerate(self.vars) if var.get()]
        self.destroy()


class DialogoVozes(ctk.CTkToplevel):
    """"Vozes dos personagens": quem o Gemini ouviu falar no filme e a voz sugerida para cada um, para trocar.
    `resultado`: {rótulo: voz} (dublar assim), {} (uma voz só para todos) ou None (pular este filme)."""

    def __init__(self, master, filme: str, linhas: list[str], rotulos: list[str], sugestao: dict, vozes: tuple):
        super().__init__(master, fg_color=Tema.CARTAO)
        self.resultado = None
        self.title("Vozes dos personagens")
        self.resizable(False, False)
        self.transient(master)
        corpo = ctk.CTkFrame(self, fg_color="transparent")
        corpo.pack(fill="both", expand=True, padx=26, pady=(20, 6))
        ctk.CTkLabel(corpo, text="Vozes dos personagens", font=ctk.CTkFont(Tema.FAMILIA, 17, "bold"),
                     text_color=Tema.TEXTO, anchor="w").pack(fill="x")
        ctk.CTkLabel(corpo, text=f"{filme}: quem o Gemini ouviu falar e a voz de cada um. Troque o que quiser (ouça as "
                     "vozes em aistudio.google.com/generate-speech). Quem fala pouco, ou fala sem dono, usa a voz "
                     "principal.", font=master.f_rotulo, text_color=Tema.TEXTO_SUAVE, anchor="w", justify="left",
                     wraplength=640).pack(fill="x", pady=(2, 10))
        self.vars: dict[str, tk.StringVar] = {}
        por_nome = {valor_da_voz(v): v for v in vozes}
        for rotulo, linha in zip(rotulos, linhas):
            fila = ctk.CTkFrame(corpo, fg_color="transparent")
            fila.pack(fill="x", pady=3)
            ctk.CTkLabel(fila, text=linha, font=master.f_rotulo, text_color=Tema.TEXTO, anchor="w", justify="left",
                         wraplength=400, width=400).pack(side="left")
            self.vars[rotulo] = tk.StringVar(value=por_nome.get(sugestao.get(rotulo, ""), vozes[0]))
            master._menu_opcoes(fila, self.vars[rotulo], vozes).pack(side="right")
        botoes = ctk.CTkFrame(self, fg_color="transparent")
        botoes.pack(fill="x", padx=26, pady=(10, 20))
        master._botao(botoes, "Pular este filme", self.destroy, "secundario").pack(side="left")
        self.bt_uma_voz = master._botao(botoes, "Uma voz só para todos", self._uma_voz, "fantasma")
        self.bt_uma_voz.pack(side="left", padx=(8, 0))
        self.bt_dublar = master._botao(botoes, "Dublar com estas vozes", self._ok, "primario")
        self.bt_dublar.pack(side="right")
        self.bind("<Escape>", lambda e: self.destroy())
        self.update_idletasks()
        x = master.winfo_rootx() + (master.winfo_width() - self.winfo_reqwidth()) // 2
        y = master.winfo_rooty() + (master.winfo_height() - self.winfo_reqheight()) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        try:
            self.grab_set()
        except tk.TclError:
            pass

    def _uma_voz(self) -> None:
        self.resultado = {}
        self.destroy()

    def _ok(self) -> None:
        self.resultado = {rotulo: valor_da_voz(var.get()) for rotulo, var in self.vars.items()}
        self.destroy()


class DialogoRoteiro(ctk.CTkToplevel):
    """"Roteiro do vídeo": cola o link da página do roteiro ou escolhe o arquivo (.txt, .html, .pdf com texto).
    `resultado`: o link, o caminho do arquivo ou None (Cancelar)."""

    def __init__(self, master, video: Path, ja_tem: Path | None = None):
        super().__init__(master, fg_color=Tema.CARTAO)
        self.resultado = None
        self.title("Roteiro do vídeo")
        self.resizable(False, False)
        self.transient(master)
        corpo = ctk.CTkFrame(self, fg_color="transparent")
        corpo.pack(fill="both", expand=True, padx=26, pady=(20, 6))
        ctk.CTkLabel(corpo, text="Roteiro do vídeo", font=ctk.CTkFont(Tema.FAMILIA, 17, "bold"),
                     text_color=Tema.TEXTO, anchor="w").pack(fill="x")
        texto = (f"{video.name}\n\nCole o link da página do roteiro (o nome de quem fala em MAIÚSCULAS e a fala "
                 "embaixo) ou escolha o arquivo. Ele fica ao lado do vídeo como 'roteiro.txt' e serve para a voz por "
                 "personagem: quem fala cada fala sai do roteiro, sem custo, e o Gemini só ouve o que faltar.")
        if ja_tem:
            texto += f"\n\nEste vídeo já tem roteiro ({ja_tem.name}): o novo fica no lugar dele."
        ctk.CTkLabel(corpo, text=texto, font=master.f_rotulo, text_color=Tema.TEXTO_SUAVE, anchor="w",
                     justify="left", wraplength=560).pack(fill="x", pady=(2, 10))
        self.var_link = tk.StringVar()
        self.campo_link = master._entrada(corpo, self.var_link, "https://...", width=560)
        self.campo_link.pack(fill="x")
        botoes = ctk.CTkFrame(self, fg_color="transparent")
        botoes.pack(fill="x", padx=26, pady=(12, 20))
        master._botao(botoes, "Cancelar", self.destroy, "secundario").pack(side="left")
        self.bt_arquivo = master._botao(botoes, "Escolher arquivo...", self._arquivo, "fantasma")
        self.bt_arquivo.pack(side="left", padx=(8, 0))
        self.bt_ok = master._botao(botoes, "Usar este link", self._ok, "primario")
        self.bt_ok.pack(side="right")
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Return>", lambda e: self._ok())
        self.update_idletasks()
        x = master.winfo_rootx() + (master.winfo_width() - self.winfo_reqwidth()) // 2
        y = master.winfo_rooty() + (master.winfo_height() - self.winfo_reqheight()) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        try:
            self.grab_set()
        except tk.TclError:
            pass

    def _arquivo(self) -> None:
        caminho = filedialog.askopenfilename(parent=self, title="Escolha o roteiro", filetypes=[
            ("Roteiro (*.txt *.html *.htm *.pdf)", "*.txt *.html *.htm *.pdf"), ("Todos", "*.*")])
        if caminho:
            self.resultado = caminho
            self.destroy()

    def _ok(self) -> None:
        if self.var_link.get().strip():
            self.resultado = self.var_link.get().strip()
            self.destroy()


class DialogoClonarVoz(ctk.CTkToplevel):
    """"Clonar uma voz" (réplica do Gemini): o nome, o dono da voz, a gravação de referência, a frase de
    consentimento (gravadas aqui pelo microfone ou escolhidas de um arquivo) e a confirmação de que há autorização.
    `resultado`: {"nome", "autorizada_por", "referencia": Path, "consentimento": Path} ou None (Cancelar)."""

    AUDIOS = "Áudio (*.wav *.mp3 *.m4a *.ogg *.opus *.aac *.flac *.webm)"

    def __init__(self, master, pasta: Path, gravador=None, motivo_sem_microfone: str = "", existentes=()):
        super().__init__(master, fg_color=Tema.CARTAO)
        self.resultado = None
        self.pasta, self.gravador, self.existentes = Path(pasta), gravador, [n.lower() for n in existentes]
        self.arquivos: dict[str, Path | None] = {"referencia": None, "consentimento": None}
        self._gravando: str | None = None
        self._relogio = None
        self.title("Clonar uma voz")
        self.resizable(False, False)
        self.transient(master)
        f_pequena = ctk.CTkFont(Tema.FAMILIA, 11)
        corpo = ctk.CTkFrame(self, fg_color="transparent")
        corpo.pack(fill="both", expand=True, padx=26, pady=(20, 6))
        ctk.CTkLabel(corpo, text="Clonar uma voz (réplica do Gemini)", font=ctk.CTkFont(Tema.FAMILIA, 17, "bold"),
                     text_color=Tema.TEXTO, anchor="w").pack(fill="x")
        ctk.CTkLabel(corpo, text="Só a SUA voz, ou a de alguém que autorizou e grava a frase de consentimento. O "
                     "Google confere se a frase foi dita e se as duas gravações são da mesma pessoa. Grave as duas no "
                     "mesmo lugar e microfone, sem música nem barulho.", font=master.f_rotulo,
                     text_color=Tema.TEXTO_SUAVE, anchor="w", justify="left", wraplength=640).pack(fill="x",
                                                                                                   pady=(2, 10))
        nomes = ctk.CTkFrame(corpo, fg_color="transparent")
        nomes.pack(fill="x")
        nomes.grid_columnconfigure((0, 1), weight=1)
        self.var_nome, self.var_dono = tk.StringVar(), tk.StringVar()
        for coluna, (rotulo, var, dica) in enumerate((("Nome da voz (aparece nos menus)", self.var_nome, "ex.: Izael"),
                                                      ("Dono da voz (quem autorizou)", self.var_dono,
                                                       "ex.: Izael Depetriz"))):
            ctk.CTkLabel(nomes, text=rotulo, font=master.f_rotulo, text_color=Tema.TEXTO_SUAVE, anchor="w").grid(
                row=0, column=coluna, sticky="w", padx=(0 if coluna == 0 else 8, 0))
            master._entrada(nomes, var, dica).grid(row=1, column=coluna, sticky="ew", padx=(0 if coluna == 0 else 8, 0))

        self.status: dict[str, ctk.CTkLabel] = {}
        self.bt_gravar: dict[str, ctk.CTkButton] = {}
        for chave, titulo, texto, extra in (
                ("referencia", "1. Gravação de referência (de 10 a 30 s)", "Leia em voz alta, com calma e do seu "
                 "jeito de falar:", voz_clonada.TEXTO_REFERENCIA),
                ("consentimento", "2. Frase de consentimento (em inglês, exatamente assim)",
                 f"Tradução: \"{voz_clonada.FRASE_TRADUCAO}\"", f"\"{voz_clonada.FRASE_CONSENTIMENTO}\"")):
            ctk.CTkLabel(corpo, text=titulo, font=master.f_secao, text_color=Tema.TEXTO, anchor="w").pack(
                fill="x", pady=(14, 2))
            caixa = ctk.CTkFrame(corpo, fg_color=Tema.CAMPO, corner_radius=10)
            caixa.pack(fill="x")
            if chave == "referencia":
                ctk.CTkLabel(caixa, text=texto, font=f_pequena, text_color=Tema.TEXTO_SUAVE, anchor="w").pack(
                    fill="x", padx=12, pady=(8, 0))
            ctk.CTkLabel(caixa, text=extra, font=ctk.CTkFont(Tema.FAMILIA, 13, "bold" if chave != "referencia"
                                                             else "normal"), text_color=Tema.TEXTO, anchor="w",
                         justify="left", wraplength=610).pack(fill="x", padx=12, pady=8)
            if chave == "consentimento":
                ctk.CTkLabel(caixa, text=texto, font=f_pequena, text_color=Tema.TEXTO_SUAVE, anchor="w",
                             justify="left", wraplength=610).pack(fill="x", padx=12, pady=(0, 8))
            linha = ctk.CTkFrame(corpo, fg_color="transparent")
            linha.pack(fill="x", pady=(6, 0))
            self.bt_gravar[chave] = master._botao(linha, "🎙  Gravar", lambda c=chave: self.alternar_gravacao(c),
                                                  "secundario")
            self.bt_gravar[chave].pack(side="left")
            if motivo_sem_microfone or gravador is None:
                self.bt_gravar[chave].configure(state="disabled")
            master._botao(linha, "📂  Escolher arquivo...", lambda c=chave: self.escolher_arquivo(c),
                          "fantasma").pack(side="left", padx=(8, 0))
            self.status[chave] = ctk.CTkLabel(linha, text=motivo_sem_microfone or "ainda não gravado",
                                              font=master.f_rotulo, text_color=Tema.TEXTO_FRACO, anchor="w")
            self.status[chave].pack(side="left", padx=(12, 0))

        self.var_autorizo = tk.BooleanVar(value=False)
        master._checkbox(corpo, "Confirmo que a voz é minha, ou que o dono dela autorizou e gravou o consentimento. "
                                "Uso pessoal; nunca a voz de atores ou de quem não sabe.",
                         self.var_autorizo).pack_configure(padx=0, pady=(14, 0))
        self.lb_aviso = ctk.CTkLabel(corpo, text="", font=master.f_rotulo, text_color=Tema.PERIGO, anchor="w",
                                     justify="left", wraplength=640)
        self.lb_aviso.pack(fill="x", pady=(6, 0))
        botoes = ctk.CTkFrame(self, fg_color="transparent")
        botoes.pack(fill="x", padx=26, pady=(10, 20))
        master._botao(botoes, "Cancelar", self.cancelar, "secundario").pack(side="left")
        self.bt_clonar = master._botao(botoes, "Clonar a voz", self.confirmar, "primario")
        self.bt_clonar.pack(side="right")
        self.bind("<Escape>", lambda e: self.cancelar())
        self.protocol("WM_DELETE_WINDOW", self.cancelar)
        self.update_idletasks()
        x = master.winfo_rootx() + (master.winfo_width() - self.winfo_reqwidth()) // 2
        y = master.winfo_rooty() + max(0, (master.winfo_height() - self.winfo_reqheight()) // 4)
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        try:
            self.grab_set()
        except tk.TclError:
            pass

    # ---- gravar (um de cada vez) ou escolher um arquivo
    def alternar_gravacao(self, chave: str) -> None:
        if self._gravando == chave:
            self._parar(chave)
            return
        if self._gravando:                              # estava gravando o outro: termina aquele primeiro
            self._parar(self._gravando)
        try:
            self.gravador.iniciar()
        except Exception as erro:
            self.status[chave].configure(text=f"não deu para gravar: {erro}", text_color=Tema.PERIGO)
            return
        self._gravando = chave
        self.bt_gravar[chave].configure(text="⏹  Parar")
        self._mostrar_tempo()

    def _mostrar_tempo(self) -> None:
        chave = self._gravando
        if not chave:
            return
        barras = int(getattr(self.gravador, "nivel", 0) * 5 + 0.5)
        self.status[chave].configure(text=f"gravando... {self.gravador.segundos:.0f} s  {'▮' * barras}{'▯' * (5 - barras)}",
                                     text_color=Tema.PERIGO)
        self._relogio = self.after(250, self._mostrar_tempo)

    def _parar(self, chave: str) -> None:
        if self._relogio:
            self.after_cancel(self._relogio)
            self._relogio = None
        self._gravando = None
        self.bt_gravar[chave].configure(text="🎙  Gravar de novo")
        amostras = self.gravador.parar()
        segundos = len(amostras) / 2 / voz_clonada.TAXA
        if segundos < 1:
            self.status[chave].configure(text="não ouvi nada (confira o microfone)", text_color=Tema.PERIGO)
            return
        destino = self.pasta / f"{chave}.wav"
        voz_clonada.gravar_wav(amostras, destino)
        self.arquivos[chave] = destino
        self.status[chave].configure(text=f"✓ gravado: {segundos:.0f} s", text_color=Tema.SUCESSO)

    def escolher_arquivo(self, chave: str) -> None:
        if self._gravando:
            self._parar(self._gravando)
        caminho = filedialog.askopenfilename(parent=self, title="Escolha a gravação",
                                             filetypes=[(self.AUDIOS.split(" (")[0],
                                                         self.AUDIOS.split("(")[1].rstrip(")")),
                                                        ("Todos os arquivos", "*.*")])
        if caminho:
            self.arquivos[chave] = Path(caminho)
            self.status[chave].configure(text=f"✓ arquivo: {Path(caminho).name}", text_color=Tema.SUCESSO)

    # ---- terminar
    def confirmar(self) -> None:
        if self._gravando:
            self._parar(self._gravando)
        try:
            nome = voz_clonada.validar_nome(self.var_nome.get())
        except Exception as erro:
            self.lb_aviso.configure(text=str(erro).capitalize())
            return
        problema = ("Já existe uma voz clonada com esse nome." if nome.lower() in self.existentes
                    else "Diga quem é o dono da voz." if not self.var_dono.get().strip()
                    else "Falta a gravação de referência (passo 1)." if not self.arquivos["referencia"]
                    else "Falta a frase de consentimento (passo 2)." if not self.arquivos["consentimento"]
                    else "Marque a confirmação de que a voz é sua ou de quem autorizou."
                    if not self.var_autorizo.get() else "")
        if problema:
            self.lb_aviso.configure(text=problema)
            return
        self.resultado = {"nome": nome, "autorizada_por": " ".join(self.var_dono.get().split()),
                          "referencia": self.arquivos["referencia"], "consentimento": self.arquivos["consentimento"]}
        self.destroy()

    def cancelar(self) -> None:
        if self._gravando:
            self._parar(self._gravando)
        self.destroy()


class LinhaCanal(NamedTuple):
    """Uma linha da tabela de canais."""
    iid: str
    nome: str
    grupo: str
    situacao: str
    link: str
    ok: bool | None            # None = não conferido
    numero: str = ""
    historico: str = ""        # "✓✓✕✓✕ (2 de 5 falharam)"
    morto: bool = False        # falhou em TODAS as últimas conferências (3 ou mais)
    idioma: str = ""           # "Português" (da lista ou deduzido pelo país/nome/link)
    programacao: str = ""      # "✓ 57 programas · mi.tv", "aguardando coleta · mi.tv", "só categoria" ("" = não conferido)
    agora: str = ""            # "Jornal Hoje (até 14:00) → Sessão da Tarde" (do guia do coletor)


class DialogoCanal(ctk.CTkToplevel):
    """Editar um canal (duplo clique na tabela ou o botão Editar): nome, número, grupo, link, logo e o ID do guia.
    `campos` limita o que aparece (vários canais de uma vez: só grupo e idioma); `aviso` é um texto acima dos
    campos. `resultado` vira um dict com os campos (None = Cancelar)."""

    CAMPOS = (("nome", "Nome do canal", "ex.: TV Cultura"),
              ("numero", "Número no Jellyfin (opcional)", "ex.: 2  (vazio = o Jellyfin numera sozinho)"),
              ("grupo", "Grupo (opcional)", "ex.: Abertos, Notícias, Rádios"),
              ("url", "Link do sinal", "https://.../index.m3u8"),
              ("logo", "Logo (opcional)", "link de uma imagem .png/.jpg"),
              ("id_guia", "ID no guia XMLTV (opcional)", "o tvg-id que liga o canal à programação"),
              ("idioma", "Idioma (opcional)", "ex.: Português, English, Español (vazio = o programa deduz)"))

    def __init__(self, master, dados: dict, titulo: str = "Editar canal", campos=None, aviso: str = ""):
        super().__init__(master, fg_color=Tema.CARTAO)
        self.resultado = None
        self.title(titulo)
        self.resizable(False, False)
        self.transient(master)
        app = master.master if not hasattr(master, "_entrada") else master
        corpo = ctk.CTkFrame(self, fg_color="transparent")
        corpo.pack(fill="both", expand=True, padx=24, pady=(18, 6))
        ctk.CTkLabel(corpo, text=titulo, font=ctk.CTkFont(Tema.FAMILIA, 17, "bold"), text_color=Tema.TEXTO,
                     anchor="w").pack(fill="x", pady=(0, 8))
        if aviso:
            ctk.CTkLabel(corpo, text=aviso, font=ctk.CTkFont(Tema.FAMILIA, 12), text_color=Tema.TEXTO_SUAVE,
                         anchor="w", justify="left", wraplength=460).pack(fill="x")
        self.vars = {}
        for chave, rotulo, dica in self.CAMPOS:
            if campos is not None and chave not in campos:
                continue
            app._rotulo(corpo, rotulo).pack(fill="x", pady=(6, 2))
            self.vars[chave] = tk.StringVar(value=str(dados.get(chave, "") or ""))
            app._entrada(corpo, self.vars[chave], dica, altura=32, width=460).pack(fill="x")
        botoes = ctk.CTkFrame(self, fg_color="transparent")
        botoes.pack(fill="x", padx=24, pady=(12, 18))
        app._botao(botoes, "Cancelar", self.destroy, "secundario").pack(side="left")
        app._botao(botoes, "Salvar", self._salvar, "primario").pack(side="right")
        self.bind("<Return>", lambda e: self._salvar())
        self.bind("<Escape>", lambda e: self.destroy())
        self.update_idletasks()
        x = master.winfo_rootx() + (master.winfo_width() - self.winfo_reqwidth()) // 2
        y = master.winfo_rooty() + (master.winfo_height() - self.winfo_reqheight()) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        try:
            self.grab_set()
        except tk.TclError:
            pass

    def _salvar(self) -> None:
        self.resultado = {chave: var.get().strip() for chave, var in self.vars.items()}
        self.destroy()


class DialogoTipos(ctk.CTkToplevel):
    """Grupo -> tipo do Jellyfin. grupos: [(grupo, quantos canais, tipo automático ou None)]; atual: a escolha
    salva ({grupo: "series" | "" (nenhum)}). `resultado`: o novo mapa (só o que saiu do automático); None = Cancelar."""

    NOMES = {"movie": "Filmes", "series": "Séries", "sports": "Esportes", "news": "Notícias", "kids": "Infantil"}

    def __init__(self, master, grupos: list[tuple[str, int, str | None]], atual: dict):
        super().__init__(master, fg_color=Tema.CARTAO)
        self.resultado = None
        self.title("Tipos no Jellyfin")
        self.geometry("620x600")
        self.transient(master)
        app = master.master if not hasattr(master, "_entrada") else master
        ctk.CTkLabel(self, text="Tipo de cada Grupo no Jellyfin", font=ctk.CTkFont(Tema.FAMILIA, 17, "bold"),
                     text_color=Tema.TEXTO, anchor="w").pack(fill="x", padx=24, pady=(18, 4))
        ctk.CTkLabel(self, text="O Jellyfin e os aplicativos (Moonfin, TV, celular) só conhecem 5 tipos: Filmes, Séries, "
                     "Esportes, Notícias e Infantil. Não dá para criar outros (\"Entertainment\", \"Religious\"...): "
                     "escolha em qual dos 5 cada grupo entra, ou nenhum. Vale no próximo \"Salvar e enviar\".",
                     font=ctk.CTkFont(Tema.FAMILIA, 12), text_color=Tema.TEXTO_SUAVE, anchor="w", justify="left",
                     wraplength=570).pack(fill="x", padx=24, pady=(0, 8))
        lista = ctk.CTkScrollableFrame(self, fg_color=Tema.CAMPO, height=380)
        lista.pack(fill="both", expand=True, padx=24, pady=4)
        lista.grid_columnconfigure(0, weight=1)
        self.vars: dict[str, tk.StringVar] = {}
        self._automatico: dict[str, str] = {}
        for n, (grupo, quantos, automatico) in enumerate(grupos):
            auto = f"Automático ({self.NOMES.get(automatico, 'sem tipo')})"
            self._automatico[grupo] = auto
            if grupo in atual:
                inicial = self.NOMES.get(atual[grupo], "Nenhum") if atual[grupo] else "Nenhum"
            else:
                inicial = auto
            ctk.CTkLabel(lista, text=f"{grupo}  ({quantos} canal(is))", font=app.f_rotulo, text_color=Tema.TEXTO,
                         anchor="w").grid(row=n, column=0, sticky="ew", padx=(8, 8), pady=3)
            self.vars[grupo] = tk.StringVar(value=inicial)
            ctk.CTkOptionMenu(lista, values=[auto, *self.NOMES.values(), "Nenhum"], variable=self.vars[grupo],
                              width=190, height=28, fg_color=Tema.CARTAO, button_color=Tema.CAMPO_BORDA,
                              button_hover_color=Tema.SECUNDARIA_HOVER, text_color=Tema.TEXTO, font=app.f_rotulo,
                              dropdown_font=app.f_rotulo).grid(row=n, column=1, padx=(0, 8), pady=3)
        botoes = ctk.CTkFrame(self, fg_color="transparent")
        botoes.pack(fill="x", padx=24, pady=(10, 18))
        app._botao(botoes, "Cancelar", self.destroy, "secundario").pack(side="left")
        app._botao(botoes, "Salvar", self._salvar, "primario").pack(side="right")
        self.bind("<Escape>", lambda e: self.destroy())
        self.update_idletasks()                          # no meio da janela da TV
        x = master.winfo_rootx() + (master.winfo_width() - self.winfo_width()) // 2
        y = master.winfo_rooty() + (master.winfo_height() - self.winfo_height()) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        try:
            self.grab_set()
        except tk.TclError:
            pass

    def _salvar(self) -> None:
        codigos = {nome: codigo for codigo, nome in self.NOMES.items()}
        self.resultado = {}
        for grupo, var in self.vars.items():
            escolha = var.get()
            if escolha == self._automatico[grupo]:
                continue
            self.resultado[grupo] = "" if escolha == "Nenhum" else codigos[escolha]
        self.destroy()


class JanelaCanais(ctk.CTkToplevel):
    """TV ao vivo no Jellyfin: a lista de canais (.m3u), o guia (XMLTV) e a antena (HDHomeRun).
    acoes: {'adicionar', 'importar_arquivo', 'importar_endereco', 'remover', 'remover_todos', 'conferir',
            'publicar', 'editar' (iid), 'editar_selecionados', 'numerar', 'desfazer'}."""

    COLUNAS = (("numero", "Nº", 44), ("grupo", "Grupo", 100), ("idioma", "Idioma", 90),
               ("programacao", "Programação", 175), ("agora", "Agora passando", 240), ("situacao", "Situação", 140),
               ("historico", "Últimas", 175), ("url", "Link", 220))

    def __init__(self, master, acoes: dict):
        super().__init__(master, fg_color=Tema.CARTAO)
        self.title("TV ao vivo no Jellyfin")
        self.geometry("1080x760")
        self.minsize(820, 560)
        self.transient(master)
        m = master
        topo = ctk.CTkFrame(self, fg_color="transparent")
        topo.pack(fill="x", padx=24, pady=(16, 4))
        ctk.CTkLabel(topo, text="Canais ao vivo (TV ao vivo do Jellyfin)", font=ctk.CTkFont(Tema.FAMILIA, 17, "bold"),
                     text_color=Tema.TEXTO, anchor="w").pack(fill="x")
        ctk.CTkLabel(topo, text="Use só fontes que você tem direito de assistir: o sinal aberto oficial (a transmissão "
                     "que o próprio canal publica), a lista da sua operadora ou uma antena com sintonizador de rede "
                     "(HDHomeRun). Listas \"piratas\" de canais pagos não.", font=m.f_rotulo,
                     text_color=Tema.AVISO, anchor="w", justify="left", wraplength=1020).pack(fill="x", pady=(2, 8))
        linha = ctk.CTkFrame(topo, fg_color="transparent")
        linha.pack(fill="x")
        self.var_nome, self.var_link = tk.StringVar(), tk.StringVar()
        m._rotulo(linha, "Canal:").pack(side="left", padx=(0, 4))
        m._entrada(linha, self.var_nome, "Nome do canal", altura=34, width=200).pack(side="left")
        m._rotulo(linha, "Link do sinal (.m3u8) ou de uma lista .m3u:").pack(side="left", padx=(10, 4))
        m._entrada(linha, self.var_link, "Link do sinal (.m3u8...) ou de uma lista .m3u", altura=34).pack(
            side="left", fill="x", expand=True, padx=(0, 8))
        for texto, chave, tipo in (("Adicionar", "adicionar", "primario"), ("Importar do link", "importar_endereco",
                                   "secundario"), ("Importar arquivo .m3u...", "importar_arquivo", "secundario")):
            b = m._botao(linha, texto, acoes[chave], tipo)
            b.configure(height=34)
            b.pack(side="left", padx=(0, 6))
        self._dica(topo, "Adicionar: um canal (nome + link do SINAL, ex.: https://.../index.m3u8).  Importar do link: o "
                   "link de uma LISTA de canais (.m3u), não de uma página de site.  Importar arquivo: uma lista .m3u "
                   "salva no PC.  Clique no TÍTULO de uma coluna para filtrar: digite e/ou marque um ou vários valores.  Conferir: só os "
                   "canais SELECIONADOS (sem seleção, todos).")

        quadro = ctk.CTkFrame(self, fg_color=Tema.CARTAO)
        quadro.pack(fill="both", expand=True, padx=24, pady=6)
        quadro.grid_columnconfigure(0, weight=1)
        quadro.grid_rowconfigure(0, weight=1)
        self.tabela = ttk.Treeview(quadro, columns=[c[0] for c in self.COLUNAS], show="tree headings",
                                   selectmode="extended", style="Moderno.Treeview")
        # Clique no título de uma coluna: escolher um ou vários valores dela (filtra e seleciona)
        self._linhas: list = []
        self._filtros: dict[str, set[str]] = {}
        self._janela_filtro = None
        self.tabela.column("#0", width=200, minwidth=120, anchor="w")
        for chave, texto, largura in self.COLUNAS:
            self.tabela.column(chave, width=largura, minwidth=60, stretch=chave == "url", anchor="w")
        self._titulos_colunas()
        self.tabela.tag_configure("ok", background="#13251b")
        self.tabela.tag_configure("erro", background="#2a1618")
        self.tabela.grid(row=0, column=0, sticky="nsew")
        rolagem = ctk.CTkScrollbar(quadro, command=self.tabela.yview, button_color=Tema.CARTAO_BORDA)
        rolagem.grid(row=0, column=1, sticky="ns", padx=(4, 0))
        # muitas colunas: rola para o lado em vez de espremer (o Link sumia numa janela pequena)
        rolagem_lado = ctk.CTkScrollbar(quadro, command=self.tabela.xview, orientation="horizontal",
                                        button_color=Tema.CARTAO_BORDA, height=14)
        rolagem_lado.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        self.tabela.configure(yscrollcommand=rolagem.set, xscrollcommand=rolagem_lado.set)
        self.tabela.bind("<Delete>", lambda e: acoes["remover"]())

        # Linha 1: o resumo e as formas de SELECIONAR. Linha 2: o que fazer com os selecionados.
        faixa = ctk.CTkFrame(self, fg_color="transparent")
        faixa.pack(fill="x", padx=24)
        selecao = ctk.CTkFrame(faixa, fg_color="transparent")
        selecao.pack(fill="x")
        self.lb_resumo = ctk.CTkLabel(selecao, text="", font=m.f_rotulo, text_color=Tema.TEXTO_SUAVE)
        self.lb_resumo.pack(side="left")
        estilo = dict(height=28, corner_radius=6, fg_color="transparent", hover_color=Tema.SECUNDARIA_HOVER,
                      text_color=Tema.PRIMARIA, font=ctk.CTkFont(Tema.FAMILIA, 12), width=20)
        ctk.CTkLabel(selecao, text="Selecionar:", font=m.f_rotulo, text_color=Tema.TEXTO_FRACO).pack(side="left",
                                                                                                   padx=(16, 0))
        self.bt_selecionar_todos = ctk.CTkButton(selecao, text="todos", command=self.selecionar_todos, **estilo)
        self.bt_selecionar_fora = ctk.CTkButton(selecao, text="os fora do ar", command=self.selecionar_fora_do_ar,
                                                **estilo)
        self.bt_selecionar_mortos = ctk.CTkButton(selecao, text="os que sempre falham",
                                                  command=self.selecionar_mortos, **estilo)
        self.bt_selecionar_duplicados = ctk.CTkButton(selecao, text="os repetidos",
                                                      command=self.selecionar_duplicados, **estilo)
        self.bt_tirar_filtros = ctk.CTkButton(selecao, text="Tirar os filtros", command=self.limpar_filtros, **estilo)
        self.bt_diagnostico = ctk.CTkButton(selecao, text="Diagnóstico do Jellyfin",
                                            command=acoes.get("diagnostico", lambda: None), **estilo)
        # a programação de verdade (o que passa ao longo do dia), pelo coletor iptv-org/epg no Docker
        self.bt_programacao = ctk.CTkButton(selecao, text="Programação dos canais...",
                                            command=acoes.get("programacao", lambda: None), **estilo)
        # o coletor está funcionando? quais canais já têm a grade? (preenche a coluna Programação)
        self.bt_conferir_programacao = ctk.CTkButton(selecao, text="Conferir programação",
                                                     command=acoes.get("conferir_programacao", lambda: None), **estilo)
        for botao in (self.bt_selecionar_todos, self.bt_selecionar_fora, self.bt_selecionar_mortos,
                      self.bt_selecionar_duplicados):
            botao.pack(side="left")
        self.bt_tirar_filtros.pack(side="right")
        self.bt_diagnostico.pack(side="right", padx=(0, 8))
        self.bt_programacao.pack(side="right", padx=(0, 8))
        self.bt_conferir_programacao.pack(side="right", padx=(0, 8))

        acoes_linha = ctk.CTkFrame(faixa, fg_color="transparent")
        acoes_linha.pack(fill="x", pady=(4, 0))
        self.bt_numerar = m._botao(acoes_linha, "Numerar...", acoes["numerar"], "secundario")
        self.bt_numerar.pack(side="left")
        # corrigir nome, grupo, link... de um canal; com vários selecionados, o grupo e o idioma de todos
        self.bt_editar = m._botao(acoes_linha, "Editar...",
                                  acoes.get("editar_selecionados", lambda: None), "secundario")
        self.bt_editar.pack(side="left", padx=(6, 0))
        # em qual dos 5 tipos do Jellyfin (Filmes, Séries, Esportes, Notícias, Infantil) cada Grupo entra
        self.bt_tipos = m._botao(acoes_linha, "Tipos...", acoes.get("tipos", lambda: None), "secundario")
        self.bt_tipos.pack(side="left", padx=(6, 0))
        self.bt_desfazer = m._botao(acoes_linha, "Desfazer remoção", acoes["desfazer"], "secundario")
        self.bt_desfazer.pack(side="left", padx=(6, 0))
        self.bt_conferir = m._botao(acoes_linha, "Conferir todos", acoes["conferir"], "secundario")
        self.bt_conferir.configure(width=170)
        self.bt_conferir.pack(side="right")
        # Leve = 8 consultas ao mesmo tempo, Normal = 16, Rápida = 32 (pode lotar o roteador/Wi-Fi de casa)
        self.var_velocidade = tk.StringVar(value="Normal")
        self.menu_velocidade = ctk.CTkOptionMenu(acoes_linha, values=["Leve", "Normal", "Rápida"], width=96,
                                                 height=32, variable=self.var_velocidade, fg_color=Tema.CAMPO,
                                                 button_color=Tema.CAMPO_BORDA, button_hover_color=Tema.SECUNDARIA_HOVER,
                                                 text_color=Tema.TEXTO, font=m.f_rotulo, dropdown_font=m.f_rotulo)
        self.menu_velocidade.pack(side="right", padx=(0, 6))
        ctk.CTkLabel(acoes_linha, text="Velocidade:", font=m.f_rotulo, text_color=Tema.TEXTO_FRACO).pack(
            side="right", padx=(12, 4))
        self.tabela.bind("<<TreeviewSelect>>", lambda e: self._texto_conferir())
        self.bt_remover_todos = m._botao(acoes_linha, "Remover todos", acoes["remover_todos"], "perigo")
        self.bt_remover_todos.pack(side="right", padx=(0, 6))
        self.bt_remover = m._botao(acoes_linha, "Remover selecionados", acoes["remover"], "perigo")
        self.bt_remover.pack(side="right", padx=(0, 6))
        self.tabela.bind("<Control-a>", lambda e: (self.selecionar_todos(), "break")[1])
        # duplo clique numa linha (não no título): editar o canal
        self.tabela.bind("<Double-1>", lambda e: self._ao_duplo_clique(e, acoes["editar"]))
        self.tabela.bind("<F2>", lambda e: acoes.get("editar_selecionados", lambda: None)())

        campos = ctk.CTkFrame(self, fg_color="transparent")
        campos.pack(fill="x", padx=24, pady=(10, 0))
        campos.grid_columnconfigure((1, 3), weight=1)
        self.var_guia, self.var_antena = tk.StringVar(), tk.StringVar()
        self.var_pasta, self.var_no_servidor = tk.StringVar(), tk.StringVar()
        for n, (rotulo, var, dica, explicacao) in enumerate((
                ("Guia de programação (XMLTV, opcional; vários: separe com ;):", self.var_guia,
                 "link ou arquivo .xml/.xml.gz",
                 "A grade de horários. Com ou sem ele, o Maestro também gera um guia de CATEGORIAS pelo Grupo (Filmes, "
                 "Esportes, Notícias, Infantil, Séries), usado nos canais que os guias de verdade não têm."),
                ("Antena HDHomeRun (IP, opcional):", self.var_antena, "ex.: 192.168.0.50",
                 "Só se você tem um sintonizador de antena na rede: a TV aberta digital entra no Jellyfin."),
                ("Salvar a lista (canais.m3u) em:", self.var_pasta, "uma pasta que o servidor do Jellyfin enxergue",
                 "Onde o programa grava o canais.m3u. O SERVIDOR do Jellyfin precisa conseguir abrir essa pasta."),
                ("Como o servidor enxerga o arquivo:", self.var_no_servidor, "só se for outro PC, ex.: E:\\TV\\canais.m3u",
                 "Vazio se o Jellyfin roda NESTE PC. Se roda em outro, o caminho como ELE vê: salvou em "
                 "\\\\Depetriz\\e\\TV aqui = E:\\TV\\canais.m3u lá."))):
            linha, coluna = divmod(n, 2)
            margem = (0 if coluna == 0 else 12, 0)
            m._rotulo(campos, rotulo).grid(row=linha * 3, column=coluna * 2, columnspan=2, sticky="w", padx=margem)
            m._entrada(campos, var, dica, altura=32).grid(row=linha * 3 + 1, column=coluna * 2, columnspan=2,
                                                         sticky="ew", padx=margem, pady=(2, 0))
            ctk.CTkLabel(campos, text=explicacao, font=ctk.CTkFont(Tema.FAMILIA, 11), text_color=Tema.TEXTO_FRACO,
                         anchor="w", justify="left", wraplength=500).grid(row=linha * 3 + 2, column=coluna * 2,
                                                                          columnspan=2, sticky="w", padx=margem,
                                                                          pady=(0, 6))
        rodape = ctk.CTkFrame(self, fg_color="transparent")
        rodape.pack(fill="x", padx=24, pady=(4, 16))
        # 1x por semana, em segundo plano e devagar ("Leve"): avisa os canais que falham em todas as conferências
        self.var_semanal = tk.BooleanVar(value=False)
        self.check_semanal = ctk.CTkCheckBox(
            rodape, text="Conferir sozinho toda semana\n(avisa os que sempre falham)", variable=self.var_semanal,
            command=acoes.get("semanal", lambda: None), font=m.f_rotulo, text_color=Tema.TEXTO_SUAVE,
            fg_color=Tema.PRIMARIA, hover_color=Tema.PRIMARIA_HOVER, border_color=Tema.CAMPO_BORDA, checkbox_width=18,
            checkbox_height=18, corner_radius=4, border_width=2)
        self.check_semanal.pack(side="left", padx=(0, 14))
        ctk.CTkLabel(rodape, text="O Jellyfin recebe a lista, o guia e a antena pela API (endereço e chave da aba "
                     "Jellyfin) e os canais aparecem em TV ao vivo.", font=m.f_rotulo, text_color=Tema.TEXTO_FRACO,
                     anchor="w", justify="left", wraplength=300).pack(side="left")
        m._botao(rodape, "Fechar", self.destroy, "fantasma", largura=90).pack(side="right")
        m._botao(rodape, "Salvar e enviar ao Jellyfin", acoes["publicar"], "primario").pack(side="right", padx=(0, 8))
        self.bt_exportar = m._botao(rodape, "Exportar (JSON, CSV ou TXT)...", self.ao_exportar, "secundario")
        self.bt_exportar.pack(side="right", padx=(0, 8))
        # Os botões e os campos ficam presos embaixo; a lista de canais é que encolhe numa tela pequena
        for parte in (rodape, campos, faixa):
            parte.pack_configure(side="bottom", before=quadro)
        self.bind("<Escape>", lambda e: self.destroy())

    TITULOS = {"#0": "Canal", "numero": "Nº", "grupo": "Grupo", "idioma": "Idioma", "programacao": "Programação",
               "agora": "Agora passando", "situacao": "Situação", "historico": "Últimas", "url": "Link"}

    def preencher(self, linhas: list[LinhaCanal], manter_selecao: bool = False) -> None:
        """linhas: [LinhaCanal] (ok None = não conferido).
        manter_selecao: depois de conferir, os mesmos canais continuam selecionados (a lista não mudou)."""
        antes = self.selecionados() if manter_selecao else []
        self._linhas = [LinhaCanal(*linha) for linha in linhas]
        self._mostrar()
        if antes:
            existem = set(self.tabela.get_children())
            self.tabela.selection_set([i for i in antes if i in existem])
            self._texto_conferir()

    @staticmethod
    def valor_na_coluna(coluna: str, linha) -> str:
        """O que conta para o filtro: o link conta pelo site (todos os canais de exemplo.org juntos)."""
        linha = LinhaCanal(*linha)
        if coluna == "url":
            from urllib.parse import urlparse
            return urlparse(linha.link).netloc or linha.link
        if coluna == "situacao":           # "o servidor a.org não responde" e "o servidor b.net..." = um valor só
            return re.sub(r"\bo servidor \S+ ", "o servidor ", linha.situacao) \
                if linha.situacao and linha.situacao != "—" else "(não conferido)"
        if coluna == "historico":          # sem as marcas ✓✕: "2 de 5 falharam", "sempre no ar"
            return linha.historico.split("  ", 1)[-1] if linha.historico else "(nunca conferido)"
        if coluna == "agora":              # o programa de agora (sem o horário e o próximo)
            return linha.agora.split(" (até")[0].split(" → ")[0] if linha.agora else "(sem grade agora)"
        if coluna == "programacao":        # sem a contagem: "com programação · mi.tv" junta os canais do mesmo site
            if not linha.programacao:
                return "(não conferido)"
            return re.sub(r"^✓ \d+ programas", "com programação", linha.programacao)
        return {"#0": linha.nome, "grupo": linha.grupo or "(sem grupo)", "idioma": linha.idioma or "(sem idioma)",
                "numero": linha.numero or "(sem número)"}[coluna]

    def _passa(self, linha) -> bool:
        return all(self.valor_na_coluna(c, linha) in valores for c, valores in self._filtros.items())

    def _mostrar(self) -> None:
        self.tabela.delete(*self.tabela.get_children())
        visiveis = [linha for linha in self._linhas if self._passa(linha)]
        for linha in visiveis:
            tags = () if linha.ok is None else ("ok" if linha.ok else "erro",)
            self.tabela.insert("", "end", iid=linha.iid, text=linha.nome, tags=tags,
                               values=(linha.numero, linha.grupo, linha.idioma or "—", linha.programacao or "—",
                                       linha.agora or "—", linha.situacao, linha.historico, linha.link))
        fora = sum(1 for linha in self._linhas if linha.ok is False)
        quantos = f"{len(visiveis)} de {len(self._linhas)}" if self._filtros else f"{len(self._linhas)}"
        self.lb_resumo.configure(text=f"{quantos} canal(is)" + (f" · {fora} fora do ar" if fora else "")
                                 + (" · filtro ligado" if self._filtros else ""))
        self._titulos_colunas()
        self._texto_conferir()

    def _titulos_colunas(self) -> None:
        for coluna, texto in self.TITULOS.items():
            marca = " ▼ (filtro)" if coluna in self._filtros else " ▾"
            self.tabela.heading(coluna, text=texto + marca, anchor="w", command=lambda c=coluna: self.abrir_filtro(c))

    def valores_da_coluna(self, coluna: str) -> list[tuple[str, int]]:
        """[(valor, quantos canais)] daquela coluna, em ordem."""
        contagem: dict[str, int] = {}
        for linha in self._linhas:
            valor = self.valor_na_coluna(coluna, linha)
            contagem[valor] = contagem.get(valor, 0) + 1
        return sorted(contagem.items(), key=lambda vq: _sem_acentos(vq[0]))       # "é" junto do "e"

    def aplicar_filtro(self, coluna: str, escolhidos) -> None:
        """Mostra só os canais com um dos valores escolhidos nessa coluna e já os SELECIONA (para remover,
        por exemplo). Todos marcados (ou nenhum) = sem filtro nessa coluna."""
        escolhidos = set(escolhidos)
        todos = {v for v, _ in self.valores_da_coluna(coluna)}
        if not escolhidos or escolhidos >= todos:
            self._filtros.pop(coluna, None)
        else:
            self._filtros[coluna] = escolhidos
        self._mostrar()
        if self._filtros:
            self.selecionar_todos()

    def limpar_filtros(self) -> None:
        self._filtros.clear()
        self._mostrar()

    def abrir_filtro(self, coluna: str) -> None:
        if self._janela_filtro is not None and self._janela_filtro.winfo_exists():
            self._janela_filtro.destroy()
        self._janela_filtro, self._filtro_aberto = janela_de_filtro(
            self, self.master, self.TITULOS[coluna], self.valores_da_coluna(coluna), self._filtros.get(coluna),
            lambda escolhidos: self.aplicar_filtro(coluna, escolhidos))

    def exportar(self, caminho) -> int:
        """Salva o que está NA TABELA (com o filtro, só os filtrados) em .json, .csv ou .txt. Devolve quantos."""
        from jellyfin_tools.tv_ao_vivo import exportar_tabela
        visiveis = set(self.tabela.get_children())
        linhas = [{"numero": linha.numero, "canal": linha.nome, "grupo": linha.grupo, "idioma": linha.idioma,
                   "programacao": linha.programacao,
                   "situacao": linha.situacao if linha.situacao != "—" else "", "no_ar": linha.ok,
                   "historico": linha.historico, "link": linha.link}
                  for linha in self._linhas if linha.iid in visiveis]
        exportar_tabela(linhas, caminho)
        return len(linhas)

    def ao_exportar(self) -> None:
        caminho = filedialog.asksaveasfilename(
            parent=self, title="Exportar os canais da tabela", initialfile="canais.csv", defaultextension=".csv",
            filetypes=[("CSV (abre no Excel)", "*.csv"), ("JSON", "*.json"), ("Texto", "*.txt")])
        if not caminho:
            return
        try:
            quantos = self.exportar(caminho)
        except (OSError, ValueError) as erro:
            self.master.mostrar_mensagem("Exportar", f"Não deu para salvar: {erro}", "erro")
            return
        extra = " (só os do filtro)" if self._filtros else ""
        self.master.mostrar_mensagem("Exportar", f"{quantos} canal(is){extra} salvos em:\n{caminho}", "info")

    def selecionados(self) -> list[str]:
        return list(self.tabela.selection())

    def a_conferir(self) -> list[str] | None:
        """Os canais que "Conferir" vai consultar: os selecionados; None = todos (sem seleção ou tudo selecionado)."""
        escolhidos = self.selecionados()
        return escolhidos if escolhidos and len(escolhidos) < len(self._linhas) else None

    def _texto_conferir(self) -> None:
        quantos = len(self.selecionados())
        parte = 0 < quantos < len(self._linhas)
        self.bt_conferir.configure(text=f"Conferir {quantos} selecionado(s)" if parte else "Conferir todos")

    def selecionar_todos(self) -> None:
        self.tabela.selection_set(self.tabela.get_children())
        self._texto_conferir()

    def _ao_duplo_clique(self, evento, editar) -> None:
        if self.tabela.identify_region(evento.x, evento.y) in ("cell", "tree"):
            if iid := self.tabela.identify_row(evento.y):
                editar(iid)

    def _selecionar(self, iids: list[str], vazio: str) -> int:
        self.tabela.selection_set(iids)
        if iids:
            self.tabela.see(iids[0])
        else:
            self.master.mostrar_mensagem("TV ao vivo", vazio, "info")
        self._texto_conferir()
        return len(iids)

    def selecionar_duplicados(self) -> int:
        """Os canais REPETIDOS (mesmo nome sem enfeites como "(720p)" ou "HD"), deixando um de cada: o primeiro
        que está no ar. É só conferir e clicar em Remover selecionados."""
        from jellyfin_tools.tv_ao_vivo import Canal, duplicados
        visiveis = set(self.tabela.get_children())
        linhas = [linha for linha in self._linhas if linha.iid in visiveis]
        canais = [Canal(linha.nome, linha.link) for linha in linhas]
        tirar = duplicados(canais, {linha.link: linha.ok for linha in linhas})
        return self._selecionar([linhas[i].iid for i in tirar], "Nenhum canal repetido na lista.")

    def selecionar_mortos(self) -> int:
        """Os que falharam em TODAS as últimas conferências (3 ou mais). Um canal "Not 24/7", que funciona
        só em alguns horários, não entra: uma falha só não prova que ele morreu."""
        visiveis = set(self.tabela.get_children())
        return self._selecionar([linha.iid for linha in self._linhas if linha.morto and linha.iid in visiveis],
                                "Nenhum canal falhou em todas as últimas conferências (são precisas pelo menos 3).")

    def selecionar_fora_do_ar(self) -> None:
        """Os que a conferência marcou em vermelho (fora do ar, página, pede login...)."""
        self.tabela.selection_set([i for i in self.tabela.get_children() if "erro" in self.tabela.item(i, "tags")])

    def _dica(self, master, texto: str) -> None:
        ctk.CTkLabel(master, text=texto, font=ctk.CTkFont(Tema.FAMILIA, 11), text_color=Tema.TEXTO_FRACO, anchor="w",
                     justify="left", wraplength=1020).pack(fill="x", pady=(4, 0))

    def valores(self) -> dict:
        return {"guia": self.var_guia.get().strip(), "antena": self.var_antena.get().strip(),
                "pasta": self.var_pasta.get().strip(), "no_servidor": self.var_no_servidor.get().strip(),
                "velocidade": self.var_velocidade.get(), "semanal": bool(self.var_semanal.get())}

    def definir_valores(self, dados: dict) -> None:
        for chave, var in (("guia", self.var_guia), ("antena", self.var_antena), ("pasta", self.var_pasta),
                           ("no_servidor", self.var_no_servidor)):
            var.set(dados.get(chave, "") or "")
        if dados.get("velocidade") in ("Leve", "Normal", "Rápida"):
            self.var_velocidade.set(dados["velocidade"])
        self.var_semanal.set(bool(dados.get("semanal")))


# =============================================================================== janela
class JanelaPrevias(ctk.CTkToplevel):
    """Fase de teste da dublagem: as prévias prontas, para ouvir e então aprovar (grava no original) ou descartar.
    itens(): [{video, previa, criada}]; ouvir/aprovar/descartar(item). Aprovar fecha a janela (o app grava numa
    tarefa); `escolha` fica com ("aprovar", item) para quem abriu a janela saber."""

    def __init__(self, master, itens, ouvir, descartar):
        super().__init__(master, fg_color=Tema.CARTAO)
        self.itens_de, self.ouvir, self.descartar = itens, ouvir, descartar
        self.escolha = None
        self.title("Prévias da dublagem")
        self.geometry("860x420")
        self.minsize(640, 320)
        self.transient(master)
        ctk.CTkLabel(self, text="Prévias da dublagem (fase de teste)", font=ctk.CTkFont(Tema.FAMILIA, 17, "bold"),
                     text_color=Tema.TEXTO, anchor="w").pack(fill="x", padx=24, pady=(18, 2))
        ctk.CTkLabel(self, text="O original ainda não foi alterado. Ouça a prévia (abre no seu player, com a dublagem e "
                     "a legenda) e, se gostar, aprove: a faixa dublada entra no vídeo original em poucos minutos, sem "
                     "dublar de novo. Não gostou? Descarte, ajuste as vozes em Configurações > Dublagem e duble de "
                     "novo.", font=master.f_rotulo, text_color=Tema.TEXTO_SUAVE,
                     anchor="w", justify="left", wraplength=800).pack(fill="x", padx=24, pady=(0, 10))
        quadro = ctk.CTkFrame(self, fg_color=Tema.CARTAO)
        quadro.pack(fill="both", expand=True, padx=24)
        self.tabela = ttk.Treeview(quadro, columns=("video", "criada", "pasta"), show="headings",
                                   selectmode="browse", style="Moderno.Treeview", height=6)
        for chave, texto, largura, estica in (("video", "Vídeo", 320, True), ("criada", "Prévia feita em", 140, False),
                                              ("pasta", "Pasta do vídeo", 320, True)):
            self.tabela.heading(chave, text=texto, anchor="w")
            self.tabela.column(chave, width=largura, stretch=estica, anchor="w")
        self.tabela.pack(fill="both", expand=True)
        self.tabela.bind("<Double-1>", lambda e: self._ouvir())
        botoes = ctk.CTkFrame(self, fg_color="transparent")
        botoes.pack(fill="x", padx=24, pady=14)
        self.bt_ouvir = master._botao(botoes, "▶  Ouvir a prévia", self._ouvir, largura=160)
        self.bt_aprovar = master._botao(botoes, "✓  Aprovar e gravar no original", self._aprovar, "primario")
        self.bt_descartar = master._botao(botoes, "✕  Descartar", self._descartar, "perigo", largura=130)
        for b in (self.bt_ouvir, self.bt_aprovar, self.bt_descartar):
            b.pack(side="left", padx=(0, 10))
        master._botao(botoes, "Fechar", self.destroy, "fantasma", largura=90).pack(side="right")
        self.recarregar()

    def recarregar(self) -> None:
        self._itens = list(self.itens_de())
        self.tabela.delete(*self.tabela.get_children())
        for i, item in enumerate(self._itens):
            video = Path(item["video"])
            self.tabela.insert("", "end", iid=str(i), values=(video.name, item.get("criada", "").replace("T", " "),
                                                              str(video.parent)))
        if self._itens:
            self.tabela.selection_set("0")
        estado = "normal" if self._itens else "disabled"
        for b in (self.bt_ouvir, self.bt_aprovar, self.bt_descartar):
            b.configure(state=estado)

    def escolhido(self) -> dict | None:
        selecao = self.tabela.selection()
        return self._itens[int(selecao[0])] if selecao else None

    def _ouvir(self) -> None:
        if (item := self.escolhido()):
            self.ouvir(item)

    def _aprovar(self) -> None:
        if (item := self.escolhido()):
            self.escolha = ("aprovar", item)
            self.destroy()

    def _descartar(self) -> None:
        if (item := self.escolhido()):
            self.descartar(item)
            self.recarregar()


def tamanho_inicial(largura_tela: int, altura_tela: int, escala: float = 1.0
                    ) -> tuple[int, int, int, int, tuple[int, int]]:
    """(largura, altura, x, y, (largura mínima, altura mínima)) da janela principal.

    A tela vem em pixels de verdade, mas o CTk multiplica a largura e a altura pela escala do Windows
    (125% = 1,25): por isso a conta é feita em "pontos" (pixels ÷ escala). Sem isso, numa tela de 1080 px
    com 125%, a janela pedia 900 pontos = 1125 px e a parte de baixo ficava fora da tela.
    A posição (x, y) não é multiplicada pelo CTk: fica em pixels, centralizada (40 px = barra de tarefas)."""
    escala = escala or 1.0
    pontos_l, pontos_a = largura_tela / escala, altura_tela / escala
    largura = int(min(1320, pontos_l - 40))
    altura = int(max(520, min(900, pontos_a - 110)))      # 110: barra de título + barra de tarefas, com folga
    x = max(0, int((largura_tela - largura * escala) / 2))
    y = max(0, int((altura_tela - 40 - altura * escala) / 2) - 15)
    return largura, altura, x, y, (min(1100, largura), min(680, altura))


class JanelaModerna(ctk.CTk):
    COLUNAS = (("n", "#", 48, False), ("status", "Situação", 110, False), ("titulo", "Título", 240, True),
               ("tipo", "Origem", 130, False), ("url", "Link", 300, True),
               ("conteudo", "Tipo", 70, False), ("licenca", "Licença", 120, False))
    # Ordem na TELA: Tipo e Licença ao lado do título (os valores continuam na ordem acima)
    ORDEM_TELA = ("n", "status", "titulo", "conteudo", "licenca", "tipo", "url")
    # Linha tingida de leve + símbolo na coluna Situação (o Treeview não colore uma célula só).
    FUNDO_SITUACAO = {"ok": "#132519", "erro": "#2a1519", "pulado": "#2a2212"}
    SIMBOLO_SITUACAO = {"ok": "\u2713", "erro": "\u2715", "pulado": "\u21b7"}    # ✓ ✕ ↷
    CAIXA = {False: "\u2610", True: "\u2611"}       # ☐ ☑ (seletor na coluna "#")

    def __init__(self, pasta_padrao: str = "videos_baixados"):
        ctk.set_appearance_mode("dark")
        super().__init__(fg_color=Tema.FUNDO)
        from .atualizacao import versao_atual
        self.title(f"{icone.NOME_APP} {versao_atual()}")
        icone.aplicar(self)                            # o "M" com a batuta (barra de título e de tarefas)
        largura, altura, x, y, minima = tamanho_inicial(self.winfo_screenwidth(), self.winfo_screenheight(),
                                                        self._get_window_scaling())
        self.geometry(f"{largura}x{altura}+{x}+{y}")
        self.minsize(*minima)
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
        self.aba_avulsos = ctk.CTkFrame(self, fg_color="transparent")
        self.aba_config = ctk.CTkFrame(self, fg_color="transparent")
        for aba in (self.aba_videos, self.aba_jellyfin, self.aba_avulsos, self.aba_config):
            aba.grid(row=1, column=0, sticky="nsew")
            aba.grid_columnconfigure(0, weight=1)
        self.aba_videos.grid_rowconfigure(2, weight=1)
        self.aba_jellyfin.grid_rowconfigure(3, weight=1)
        # ⚙ Configurações primeiro: as outras abas põem as opções delas nas categorias de lá
        self._montar_aba_config(self.aba_config)
        self._montar_endereco(self.aba_videos)
        self._montar_acoes(self.aba_videos)
        self._montar_corpo(self.aba_videos)
        self._montar_aba_jellyfin(self.aba_jellyfin)
        self._montar_aba_avulsos(self.aba_avulsos)      # depois da Jellyfin: usa a pasta e o "dublar" de lá
        self._montar_rodape()
        self._organizar_liberado = False
        self.definir_ocupado(False)
        self._quebrar_textos_config()
        self.mostrar_config("Nomes e TMDB")
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
        "Avulsos": "1) Escolha a caixa de entrada ou adicione vídeos    2) Clique em Olhar    3) Confira e clique em "
                   "Processar",
        "⚙ Configurações": "Tudo o que muda o jeito do programa trabalhar fica aqui. Vale na hora e fica salvo.",
    }
    TITULOS = {"Vídeos": "Extrair e baixar vídeos públicos",
               "Jellyfin": "Organizar a biblioteca do Jellyfin",
               "Avulsos": "Legendar e dublar vídeos avulsos",
               "⚙ Configurações": "Configurações"}

    def _montar_cabecalho(self) -> None:
        topo = ctk.CTkFrame(self, fg_color="transparent")
        topo.grid(row=0, column=0, sticky="ew", padx=28, pady=(18, 0))
        try:                                           # o ícone do Maestro ao lado do título
            self._imagem_icone = ctk.CTkImage(light_image=icone.desenhar(128), dark_image=icone.desenhar(128),
                                              size=(54, 54))
            ctk.CTkLabel(topo, text="", image=self._imagem_icone).pack(side="left", padx=(0, 14), anchor="n")
        except Exception:                              # sem Pillow: só o texto
            pass
        textos = ctk.CTkFrame(topo, fg_color="transparent")
        textos.pack(side="left")
        self.lb_titulo = ctk.CTkLabel(textos, text=self.TITULOS["Vídeos"], font=self.f_titulo,
                                      text_color=Tema.TEXTO, anchor="w")
        self.lb_titulo.pack(anchor="w")
        self.lb_subtitulo = ctk.CTkLabel(textos, font=self.f_sub, text_color=Tema.TEXTO_SUAVE, anchor="w",
                                         text=self.SUBTITULOS["Vídeos"])
        self.lb_subtitulo.pack(anchor="w", pady=(2, 0))
        # "painel de saúde" (aba Jellyfin): bibliotecas, Jellyfin, vigia, lugar fixo e versão numa linha só
        self.lb_saude = ctk.CTkLabel(textos, text="", font=ctk.CTkFont(Tema.FAMILIA, 12), text_color=Tema.TEXTO_SUAVE,
                                     anchor="w", justify="left", wraplength=760)    # muita coisa: quebra a linha
        self.seletor_aba = ctk.CTkSegmentedButton(
            topo, values=["Vídeos", "Jellyfin", "Avulsos", "⚙ Configurações"], command=self.mostrar_aba, height=38,
            corner_radius=Tema.RAIO_CONTROLE, font=self.f_botao, fg_color=Tema.CARTAO,
            selected_color=Tema.PRIMARIA, selected_hover_color=Tema.PRIMARIA_HOVER,
            unselected_color=Tema.CARTAO, unselected_hover_color=Tema.SECUNDARIA_HOVER, text_color=Tema.TEXTO)
        self.seletor_aba.pack(side="right", pady=(4, 0))
        # consulta a página Releases na hora (sem fechar o programa)
        self.bt_atualizacoes = ctk.CTkButton(
            topo, text="⟳  Verificar atualizações", command=self.ao_verificar_atualizacoes, height=38, width=190,
            corner_radius=Tema.RAIO_CONTROLE, font=self.f_normal, fg_color="transparent",
            hover_color=Tema.SECUNDARIA_HOVER, text_color=Tema.TEXTO_SUAVE, border_width=1,
            border_color=Tema.CAMPO_BORDA)
        self.bt_atualizacoes.pack(side="right", padx=(0, 12), pady=(4, 0))

    def mostrar_aba(self, nome: str) -> None:
        """'Vídeos', 'Jellyfin', 'Avulsos' ou '⚙ Configurações'."""
        abas = {"Vídeos": self.aba_videos, "Jellyfin": self.aba_jellyfin, "Avulsos": self.aba_avulsos,
                self.ABA_CONFIG: self.aba_config}
        saindo_da_config = self.seletor_aba.get() == self.ABA_CONFIG and nome != self.ABA_CONFIG
        for outro, aba in abas.items():
            if outro != nome:
                aba.grid_remove()
        abas[nome].grid()
        self.seletor_aba.set(nome)
        self.lb_titulo.configure(text=self.TITULOS[nome])
        self.lb_subtitulo.configure(text=self.SUBTITULOS[nome])
        if saindo_da_config and hasattr(self, "_salvar_config"):
            self._salvar_config()                       # o que mudou nas configurações já fica guardado
        if nome == "Jellyfin":
            self.atualizar_resumo_config()
        if nome == "Avulsos":
            self.atualizar_botao_testar()                # os minutos de teste podem ter mudado nas Configurações
        if nome in ("Jellyfin", self.ABA_CONFIG) and self.lb_saude.cget("text"):
            self.lb_saude.pack(anchor="w", pady=(2, 0))
        else:
            self.lb_saude.pack_forget()

    def definir_saude(self, itens: list[tuple[str, bool]]) -> None:
        """itens: [(texto, ok)]. Uma linha: '✓ Filmes · ⚠ Séries: não escolhida · ...' (laranja se algo falta)."""
        texto = "   ·   ".join(f"{'✓' if ok else '⚠'} {rotulo}" if ok is not None else rotulo
                               for rotulo, ok in itens)
        self.lb_saude.configure(text=texto, text_color=Tema.AVISO if any(ok is False for _, ok in itens)
                                else Tema.TEXTO_SUAVE)
        if self.aba_atual() in ("Jellyfin", self.ABA_CONFIG):
            self.lb_saude.pack(anchor="w", pady=(2, 0))

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
        # atalho para as opções da busca (navegador, qualidade, pasta...), que ficam em ⚙ Configurações
        self.bt_opcoes_videos = self._botao(barra, "⚙  Opções da busca", self.mostrar_opcoes_videos, "fantasma",
                                            largura=150)
        for b in (self.bt_buscar, self.bt_baixar_sel, self.bt_baixar_todos, self.bt_login):
            b.pack(side="left", padx=(0, 10))
        self.bt_parar.pack(side="right")
        self.bt_opcoes_videos.pack(side="right", padx=(0, 10))

    def mostrar_opcoes_videos(self) -> None:
        """⚙ Configurações > Opções de busca."""
        self.mostrar_aba(self.ABA_CONFIG)
        self.mostrar_config("Opções de busca")

    # ------------------------------------------------------------------ corpo: opções + vídeos + log
    def _montar_corpo(self, aba) -> None:
        corpo = self._corpo(aba, linha=2)
        self._montar_opcoes(corpo)
        self._montar_tabela(corpo)
        self._criar_console(corpo)

    def _corpo(self, aba, linha: int) -> ctk.CTkFrame:
        """Área de baixo de uma aba: a tabela e o console (as opções ficam em ⚙ Configurações)."""
        corpo = ctk.CTkFrame(aba, fg_color="transparent")
        corpo.grid(row=linha, column=0, sticky="nsew", padx=28)
        corpo.grid_columnconfigure(1, weight=1)
        corpo.grid_rowconfigure(0, weight=3)
        corpo.grid_rowconfigure(1, weight=2)
        return corpo

    def _menu_opcoes(self, master, var, valores) -> ctk.CTkOptionMenu:
        return ctk.CTkOptionMenu(master, variable=var, values=list(valores), height=36,
                                 corner_radius=Tema.RAIO_CONTROLE, font=self.f_normal, fg_color=Tema.CAMPO,
                                 button_color=Tema.SECUNDARIA, button_hover_color=Tema.SECUNDARIA_HOVER,
                                 dropdown_fg_color=Tema.CARTAO, dropdown_hover_color=Tema.SECUNDARIA_HOVER,
                                 dropdown_font=self.f_normal, text_color=Tema.TEXTO)

    def _checkbox(self, master, texto, var, comando=None) -> ctk.CTkCheckBox:
        caixa = ctk.CTkCheckBox(master, text=texto, variable=var, command=comando,
                                font=self.f_normal, text_color=Tema.TEXTO, fg_color=Tema.PRIMARIA,
                                hover_color=Tema.PRIMARIA_HOVER, border_color=Tema.CAMPO_BORDA,
                                checkbox_width=20, checkbox_height=20, corner_radius=6, border_width=2)
        caixa.pack(anchor="w", pady=4, padx=18)
        return caixa

    # 2. painel de opções (cartão lateral; rola se a tela for baixa)
    def _montar_opcoes(self, corpo) -> None:
        """As opções da busca de vídeos ficam em ⚙ Configurações > Opções de busca."""
        lateral = self._secao_config("Opções de busca")
        p = dict(padx=18)

        self._rotulo(lateral, "Opções", suave=False, fonte=self.f_secao).pack(anchor="w", pady=(12, 4), **p)
        self.var_nav = tk.BooleanVar(value=False)
        self.var_visivel = tk.BooleanVar(value=False)
        self.var_pausar = tk.BooleanVar(value=False)
        for texto, var in (("Usar navegador (sites com\nJavaScript ou login)", self.var_nav),
                           ("Mostrar a janela do navegador", self.var_visivel),
                           ("Pausar para eu resolver verificações", self.var_pausar)):
            self._checkbox(lateral, texto, var, self._ajustar_checks)
        # players que só carregam o vídeo com um clique no poster/play (só com o navegador)
        self.var_clicar_play = tk.BooleanVar(value=True)
        self.check_clicar_play = self._checkbox(lateral, "Clicar no play sozinho\n(com o navegador)",
                                                self.var_clicar_play)
        # modo híbrido: os botões "Baixar" viram "Espelhar" (.strm no Jellyfin); desmarcado, baixam como sempre
        self.var_espelhar = tk.BooleanVar(value=False)
        self.check_espelhar = self._checkbox(lateral, "Espelhar em vez de baixar\n(.strm no Jellyfin)",
                                             self.var_espelhar, self._ajustar_botoes_baixar)
        # para testar sites seus (ou com autorização do dono): pergunta antes de cada busca/download
        self.var_ignorar_robots = tk.BooleanVar(value=False)
        self.check_ignorar_robots = self._checkbox(lateral, "Ignorar o robots.txt\n(pergunta a cada busca)",
                                                   self.var_ignorar_robots)

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
        self.campo_espera = self._numero(lateral, "Espera média (s):", 5.0, 0.5, 10, 0.5, True)

        self._separador(lateral)
        self._rotulo(lateral, "Salvar vídeos em:", suave=False, fonte=self.f_secao).pack(anchor="w", pady=(0, 6), **p)
        self.var_pasta = tk.StringVar(value=self._pasta_padrao)
        self._entrada(lateral, self.var_pasta).pack(fill="x", **p)
        self.bt_escolher = self._botao(lateral, "Escolher...", self.ao_escolher_pasta)
        self.bt_escolher.pack(fill="x", pady=(8, 14), **p)

    def _numero(self, master, texto, valor, minimo, maximo, passo, decimal=False, casas=1, virgula=False, var=None):
        linha = ctk.CTkFrame(master, fg_color="transparent")
        linha.pack(fill="x", padx=18, pady=(0, 6))
        campo = CampoNumerico(linha, valor, minimo, maximo, passo, decimal, largura=128,   # cabe "100000"
                              casas=casas, virgula=virgula, var=var)
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
        self.bt_tirar_filtros_videos = ctk.CTkButton(topo, text="Tirar os filtros", command=self.tirar_filtros_videos,
                                                     width=100, **estilo)
        for b in (self.bt_tirar_filtros_videos, self.bt_limpar_selecao, self.bt_selecionar_espelhaveis,
                  self.bt_selecionar_todos):
            b.pack(side="right", padx=(4, 0))
        # Seletor: "1-5, 8" (números da coluna #) ou parte do nome ("1x0"); Enter marca (soma ao que já está)
        self.campo_selecionar = ctk.CTkEntry(topo, width=170, height=26,
                                             placeholder_text="Marcar: 1-5, 8 ou nome",
                                             fg_color=Tema.CAMPO, border_color=Tema.CAMPO_BORDA, text_color=Tema.TEXTO)
        self.campo_selecionar.bind("<Return>", lambda e: self.marcar_por_texto())
        self.bt_marcar = ctk.CTkButton(topo, text="Marcar", command=self.marcar_por_texto, width=64, **estilo)
        self.bt_marcar.pack(side="right", padx=(4, 0))
        self.campo_selecionar.pack(side="right", padx=(4, 0))
        self.lb_selecao = ctk.CTkLabel(topo, text=self.DICA_SELECAO, font=self.f_rotulo, text_color=Tema.TEXTO_FRACO)
        self.lb_selecao.pack(side="right", padx=(0, 10))
        self._marcados: set[str] = set()                  # linhas com ☑ (para trocar só as que mudaram)
        self.tabela.heading("n", text=f"{self.CAIXA[False]} #", command=self.alternar_todos)
        self.tabela.bind("<Button-1>", self._ao_clicar_tabela)
        self.tabela.bind("<<TreeviewSelect>>", lambda e: self._atualizar_selecao())
        self._ordem_videos: list[str] = []        # todas as linhas, na ordem (à vista ou escondidas pelo filtro)
        self._ocultos_videos: set[str] = set()
        self._filtros_videos: dict[str, set[str]] = {}
        self._janela_filtro_videos = None
        self._titulos_videos()
        self.tabela.bind("<Control-a>", lambda e: (self.selecionar_todos(), "break")[1])
        self.tabela.bind("<Control-A>", lambda e: (self.selecionar_todos(), "break")[1])
        self.bt_abrir_link = self._botao(acoes, "Abrir link", self.ao_abrir_link, "fantasma")
        self.bt_copiar_link = self._botao(acoes, "Copiar link", self.ao_copiar_link, "fantasma")
        self.bt_salvar_lista = self._botao(acoes, "Salvar lista (CSV/JSON/TXT)...", self.ao_salvar_lista, "fantasma")
        self.bt_abrir_pasta = self._botao(acoes, "Abrir pasta dos vídeos", self.ao_abrir_pasta, "fantasma")
        # memória de downloads: esquecer os selecionados ou limpar por período
        self.bt_esquecer = self._botao(acoes, "Memória de downloads...", self.ao_memoria_downloads, "fantasma")
        for b in (self.bt_abrir_link, self.bt_copiar_link, self.bt_salvar_lista, self.bt_abrir_pasta, self.bt_esquecer):
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
    MODELOS_WHISPER = ("tiny", "base", "small", "medium", "large-v3", "turbo")
    VOZES_DUBLAGEM = ("faber", "edresson")
    MOTORES_VOZ = ("Piper (grátis, no PC)", "Gemini (premium, Google AI Studio)", "Google Cloud TTS (cota grátis)")
    # as mesmas de jellyfin_tools.voz_gemini.VOZES (um teste confere), com a descrição para o menu
    VOZES_GEMINI = ("Charon (masculina, informativa)", "Orus (masculina, firme)", "Puck (masculina, animada)",
                    "Fenrir (masculina, empolgada)", "Iapetus (masculina, clara)", "Algieba (masculina, suave)",
                    "Enceladus (masculina, sussurrada)", "Kore (feminina, firme)", "Aoede (feminina, leve)",
                    "Leda (feminina, jovem)", "Zephyr (feminina, brilhante)", "Despina (feminina, suave)",
                    "Callirrhoe (feminina, tranquila)", "Autonoe (feminina, clara)")
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
        self.bt_tv_ao_vivo = self._botao(barra, "TV ao vivo...", self.ao_tv_ao_vivo, largura=120)
        self.bt_parar_jf = self._botao(barra, "Parar", self.ao_parar, "perigo", largura=100)
        for b in (self.bt_previa, self.bt_organizar, self.bt_legendas, self.bt_desfazer, self.bt_conferir_espelhos,
                  self.bt_relatorio, self.bt_gerenciar_espelhos, self.bt_tv_ao_vivo):
            b.pack(side="left", padx=(0, 10))
        self.bt_parar_jf.pack(side="right")

        # --- o contexto do trabalho: Filmes/Séries e as duas pastas (o resto fica em ⚙ Configurações)
        contexto = self._cartao(aba)
        contexto.grid(row=1, column=0, sticky="ew", padx=28, pady=(0, 10))
        self._destinos = {"Filmes": "", "Séries": ""}
        self._modo_atual = "Filmes"
        self.seletor_modo = ctk.CTkSegmentedButton(
            contexto, values=["Filmes", "Séries"], command=self._ao_trocar_modo, height=34, width=170,
            corner_radius=Tema.RAIO_CONTROLE, font=self.f_normal, fg_color=Tema.CAMPO,
            selected_color=Tema.PRIMARIA, selected_hover_color=Tema.PRIMARIA_HOVER,
            unselected_color=Tema.CAMPO, unselected_hover_color=Tema.SECUNDARIA_HOVER, text_color=Tema.TEXTO)
        self.seletor_modo.grid(row=0, column=0, padx=(16, 14), pady=12)
        self.seletor_modo.set("Filmes")
        self.var_jf_origem = tk.StringVar()
        self.var_jf_destino = tk.StringVar()
        contexto.grid_columnconfigure((2, 5), weight=1)
        self._rotulo(contexto, "Arquivos para organizar:").grid(row=0, column=1, padx=(0, 6))
        self._entrada(contexto, self.var_jf_origem, "ex.: C:/Users/Voce/Downloads").grid(row=0, column=2, sticky="ew")
        self._botao(contexto, "Escolher...", lambda: self._escolher_pasta_em(self.var_jf_origem), largura=90).grid(
            row=0, column=3, padx=(6, 14))
        self.lb_destino = self._rotulo(contexto, self.ROTULOS_DESTINO["Filmes"])
        self.lb_destino.grid(row=0, column=4, padx=(0, 6))
        self._entrada(contexto, self.var_jf_destino, "ex.: D:/Jellyfin/Filmes").grid(row=0, column=5, sticky="ew")
        self._botao(contexto, "Escolher...", lambda: self._escolher_pasta_em(self.var_jf_destino), largura=90).grid(
            row=0, column=6, padx=(6, 16))
        # o que está ligado (resumo) e o atalho para mudar
        self.lb_resumo_config = ctk.CTkLabel(contexto, text="", font=ctk.CTkFont(Tema.FAMILIA, 11),
                                             text_color=Tema.TEXTO_SUAVE, anchor="w", justify="left")
        self.lb_resumo_config.grid(row=1, column=0, columnspan=6, sticky="w", padx=16, pady=(0, 10))
        self._botao(contexto, "⚙ Configurações", lambda: self.mostrar_aba(self.ABA_CONFIG), "fantasma",
                    largura=130).grid(row=1, column=6, padx=(6, 16), pady=(0, 8))

        # --- ações de legendas e voz (o "como" de cada uma fica em ⚙ Configurações)
        voz = ctk.CTkFrame(aba, fg_color="transparent")
        voz.grid(row=2, column=0, sticky="ew", padx=28, pady=(0, 10))
        self._rotulo(voz, "Legendas e voz:").pack(side="left", padx=(2, 10))
        self.bt_traduzir_legendas = self._botao(voz, "Traduzir legendas com IA...", self.ao_traduzir_legendas)
        self.bt_legendar_audio = self._botao(voz, "Criar legenda pelo áudio...", self.ao_legendar_audio)
        self.bt_sincronizar = self._botao(voz, "Sincronizar legendas...", self.ao_sincronizar_legendas)
        self.bt_dublar = self._botao(voz, "Dublar...", self.ao_dublar)
        self.bt_testar_jf = self._botao(voz, "🧪 Testar", self.ao_testar_dublagem_jf)
        self.campo_jf_minutos = self.campo_minutos(voz)
        self.bt_roteiro_jf = self._botao(voz, "📜 Roteiro...", self.ao_roteiro_jellyfin)
        self.bt_previas_jf = self._botao(voz, "🎧 Prévias", self.ao_previas)
        for b in (self.bt_traduzir_legendas, self.bt_legendar_audio, self.bt_sincronizar, self.bt_dublar,
                  self.bt_testar_jf, self.bt_roteiro_jf, self.bt_previas_jf):
            b.configure(height=34)
        for b in (self.bt_traduzir_legendas, self.bt_legendar_audio, self.bt_sincronizar, self.bt_dublar,
                  self.bt_testar_jf, self.campo_jf_minutos, self.bt_roteiro_jf, self.bt_previas_jf):
            b.pack(side="left", padx=(0, 8))
        self.bt_testar_jf.pack_configure(padx=(0, 4))

        corpo = self._corpo(aba, linha=3)
        corpo.grid_rowconfigure(1, weight=0)          # painel Antes -> Depois: altura fixa
        p = dict(padx=18)

        # ===================================================== ⚙ Configurações > Nomes e TMDB
        lateral = self._secao_config("Nomes e TMDB")
        self.var_jf_tmdb = tk.BooleanVar(value=False)
        self.var_jf_chave_tmdb = tk.StringVar()
        self.var_jf_imagens = tk.BooleanVar(value=True)
        self.var_jf_nfo = tk.BooleanVar(value=True)
        self.cb_tmdb = self._checkbox(lateral, "Consultar o TMDB para confirmar nomes (a chave fica em Chaves de API)",
                                      self.var_jf_tmdb)
        self._checkbox(lateral, "Baixar pôster e backdrop (se faltarem)", self.var_jf_imagens)
        self._checkbox(lateral, "Criar arquivo .nfo (sinopse, duração...)", self.var_jf_nfo)
        self.var_jf_tmdbid = tk.BooleanVar(value=False)
        self.var_jf_exigir = tk.BooleanVar(value=False)
        self.cb_tmdbid = self._checkbox(lateral, "Incluir [tmdbid] no nome da pasta", self.var_jf_tmdbid)
        self.var_jf_nomes_ep = tk.BooleanVar(value=True)
        self._checkbox(lateral, "Séries: nome do episódio depois do número (S01E07 - Nome)", self.var_jf_nomes_ep)
        self._checkbox(lateral, "Só mover o que estiver no catálogo", self.var_jf_exigir)

        # ===================================================== Organização e limpeza
        lateral = self._secao_config("Organização e limpeza")
        self.var_jf_lixo = tk.BooleanVar(value=True)
        self._checkbox(lateral, "Apagar lixo do torrent (.url, .txt de propaganda, trailers < 100 MB)",
                       self.var_jf_lixo)
        self.var_jf_apagar_pasta = tk.BooleanVar(value=False)
        self._checkbox(lateral, "Apagar a pasta do torrent depois de transferir (com o que sobrar nela)",
                       self.var_jf_apagar_pasta)
        self._rotulo(lateral, "Vale também para a vigia. Desmarcado: o vídeo sai e a propaganda é apagada, mas a "
                              "pasta antiga do download continua (com a amostra e o que mais sobrou). A pasta só é "
                              "apagada se não sobrar nenhum outro vídeo de verdade nela.",
                     fonte=ctk.CTkFont(Tema.FAMILIA, 11)).pack(anchor="w", padx=(46, 18), pady=(0, 6))
        self._rotulo(lateral, "Imagens (poster, backdrop...) e legendas locais vão junto com o filme.",
                     fonte=ctk.CTkFont(Tema.FAMILIA, 11)).pack(anchor="w", pady=(2, 0), **p)
        self._separador(lateral)
        # pastas que o organizador nunca mexe (ex.: as que o Sonarr/Radarr cuidam)
        self._rotulo(lateral, "Pastas protegidas, uma por linha (ex.: as do Sonarr/Radarr). O organizador nunca "
                              "mexe nelas, nem entra nelas.").pack(anchor="w", pady=(4, 2), **p)
        self.txt_pastas_protegidas = ctk.CTkTextbox(lateral, height=70, font=self.f_rotulo, fg_color=Tema.CAMPO,
                                                    border_width=1, border_color=Tema.CAMPO_BORDA,
                                                    text_color=Tema.TEXTO, corner_radius=Tema.RAIO_CONTROLE,
                                                    wrap="none")
        self.txt_pastas_protegidas.pack(fill="x", **p)
        self._botao(lateral, "Proteger pasta...", self._adicionar_pasta_protegida, "fantasma").pack(
            anchor="w", pady=(2, 4), **p)

        # ===================================================== Vigia (automático)
        lateral = self._secao_config("Vigia (automático)")
        self.var_jf_vigiar = tk.BooleanVar(value=False)
        self._checkbox(lateral, "Vigiar as pastas e organizar sozinho o que terminar de baixar",
                       self.var_jf_vigiar, comando=self.ao_alternar_vigia)
        self.campo_vigia_min = self._numero(lateral, "Conferir a cada (min):", 5, 1, 240, 1)
        self._rotulo(lateral, "Pastas vigiadas, uma por linha (ex.: as do uTorrent, ou a própria biblioteca). Filmes "
                              "e séries são separados sozinhos. Vazio = a pasta de origem da aba Jellyfin.").pack(
            anchor="w", pady=(4, 2), **p)
        self.txt_pastas_vigiadas = ctk.CTkTextbox(lateral, height=80, font=self.f_rotulo, fg_color=Tema.CAMPO,
                                                  border_width=1, border_color=Tema.CAMPO_BORDA, text_color=Tema.TEXTO,
                                                  corner_radius=Tema.RAIO_CONTROLE, wrap="none")
        self.txt_pastas_vigiadas.pack(fill="x", **p)
        # aviso embaixo do campo: pasta que não existe, ou que é a própria biblioteca (some quando está tudo certo)
        self.lb_aviso_vigiadas = ctk.CTkLabel(lateral, text="", font=ctk.CTkFont(Tema.FAMILIA, 11),
                                              text_color=Tema.AVISO, anchor="w", justify="left", wraplength=600)
        self._espera_vigiadas = None

        def ao_digitar_vigiadas(_=None):
            if self._espera_vigiadas:
                self.after_cancel(self._espera_vigiadas)
            self._espera_vigiadas = self.after(600, self.atualizar_aviso_vigiadas)
        self.txt_pastas_vigiadas.bind("<KeyRelease>", ao_digitar_vigiadas)
        self.txt_pastas_vigiadas.bind("<FocusOut>", lambda e: self.atualizar_aviso_vigiadas(arrumar=True))
        self._botao(lateral, "Adicionar pasta...", self._adicionar_pasta_vigiada, "fantasma").pack(
            anchor="w", pady=(2, 4), **p)
        # ligado: E:/Series/NOVELAS se arruma em E:/Series/NOVELAS (a origem e as bibliotecas não contam)
        self.var_jf_vigia_no_lugar = tk.BooleanVar(value=True)
        self._checkbox(lateral, "Organizar cada pasta vigiada dentro dela mesma (não leva para as bibliotecas)",
                       self.var_jf_vigia_no_lugar)
        # simulação: mostra na lista o que a vigia moveria AGORA, sem mexer em nada
        self.bt_simular_vigia = self._botao(lateral, "O que a vigia faria agora? (simular)", self.ao_simular_vigia,
                                            "secundario")
        self.bt_simular_vigia.pack(anchor="w", pady=(2, 6), **p)
        self.lb_estado_vigia = ctk.CTkLabel(lateral, text="Desligada. Usa as pastas e opções desta aba; o que ainda "
                                            "está baixando (.part, .!qB) fica para a próxima.",
                                            font=self.f_rotulo, text_color=Tema.TEXTO_FRACO, anchor="w",
                                            justify="left", wraplength=600)
        self.lb_estado_vigia.pack(fill="x", padx=18, pady=(0, 4))

        # ===================================================== Espelhos (.strm)
        lateral = self._secao_config("Espelhos (.strm)")
        self.var_jf_conferir_auto = tk.BooleanVar(value=False)
        self._checkbox(lateral, "Conferir os espelhos (.strm) e os canais sozinho e avisar no Discord/Telegram se "
                                "quebrar", self.var_jf_conferir_auto, comando=self.ao_alternar_conferencia)
        linha = ctk.CTkFrame(lateral, fg_color="transparent")
        linha.pack(anchor="w", padx=18, pady=(0, 6))
        self._rotulo(linha, "A cada:").pack(side="left", padx=(0, 8))
        self.campo_conferir_a_cada = CampoNumerico(linha, 7, 1, 999, 1, largura=102)
        self.campo_conferir_a_cada.pack(side="left", padx=(0, 6))
        self.var_jf_conferir_unidade = tk.StringVar(value="dias")
        ctk.CTkOptionMenu(linha, variable=self.var_jf_conferir_unidade, values=["minutos", "horas", "dias"], width=96,
                          height=32, corner_radius=Tema.RAIO_CONTROLE, font=self.f_normal, fg_color=Tema.CAMPO,
                          button_color=Tema.SECUNDARIA, button_hover_color=Tema.SECUNDARIA_HOVER,
                          dropdown_fg_color=Tema.CARTAO, text_color=Tema.TEXTO).pack(side="left")
        self.var_jf_remover_quebrados = tk.BooleanVar(value=False)
        self._checkbox(lateral, "Remover os quebrados (dá para desfazer)", self.var_jf_remover_quebrados)
        self.var_jf_ultima_conferencia = tk.StringVar(value="")
        self.lb_estado_conferencia = ctk.CTkLabel(lateral, text="Última conferência: nunca.", font=self.f_rotulo,
                                                  text_color=Tema.TEXTO_FRACO, anchor="w", justify="left",
                                                  wraplength=600)
        self.lb_estado_conferencia.pack(fill="x", padx=18, pady=(0, 4))

        # ===================================================== Legendas
        lateral = self._secao_config("Legendas")
        self.var_jf_legendas = tk.BooleanVar(value=True)
        self._checkbox(lateral, "Baixar legendas ao organizar", self.var_jf_legendas)
        self._rotulo(lateral, "Fonte das legendas (as chaves ficam em Chaves de API):").pack(anchor="w",
                                                                                            pady=(6, 4), **p)
        self.var_jf_fonte = tk.StringVar(value=self.FONTES_LEGENDA[0])
        ctk.CTkOptionMenu(lateral, variable=self.var_jf_fonte, values=list(self.FONTES_LEGENDA),
                          command=lambda v: self._mostrar_campos_jf(), height=36, width=320,
                          corner_radius=Tema.RAIO_CONTROLE, font=self.f_normal, fg_color=Tema.CAMPO,
                          button_color=Tema.SECUNDARIA, button_hover_color=Tema.SECUNDARIA_HOVER,
                          dropdown_fg_color=Tema.CARTAO, dropdown_hover_color=Tema.SECUNDARIA_HOVER,
                          dropdown_font=self.f_normal, text_color=Tema.TEXTO).pack(anchor="w", **p)
        self.var_jf_chave_os = tk.StringVar()
        self.var_jf_url_site = tk.StringVar()
        self.var_jf_chave_subdl = tk.StringVar()
        # height=1: vazio, um CTkFrame ocuparia 200 px (o padrão); assim só cresce com um campo dentro
        self.quadro_fonte = ctk.CTkFrame(lateral, fg_color="transparent", height=1)
        self.quadro_fonte.pack(fill="x")
        self.campo_url_site = self._entrada(self.quadro_fonte, self.var_jf_url_site,
                                            "https://site/busca?q={consulta}")
        self._rotulo(lateral, "Idiomas das legendas (um arquivo cada):").pack(anchor="w", pady=(10, 2), **p)
        self.vars_idioma_jf = {codigo: tk.BooleanVar(value=(codigo == "pt-BR")) for codigo, _ in self.IDIOMAS_JF}
        for codigo, nome in self.IDIOMAS_JF:
            self._checkbox(lateral, f"{nome} ({codigo})", self.vars_idioma_jf[codigo])
        self._rotulo(lateral, "Outros idiomas (quantos quiser, separados por vírgula, ponto e vírgula ou espaço):").pack(
            anchor="w", pady=(4, 0), **p)
        self.var_jf_outros_idiomas = tk.StringVar()
        self._entrada(lateral, self.var_jf_outros_idiomas, "ex.: fr, italiano; coreano").pack(fill="x", pady=(2, 2), **p)
        # o que o programa entendeu do que foi digitado (e o que não entendeu)
        self.lb_idiomas_entendidos = ctk.CTkLabel(lateral, text="", font=ctk.CTkFont(Tema.FAMILIA, 11),
                                                  text_color=Tema.TEXTO_FRACO, anchor="w", justify="left",
                                                  wraplength=600)
        self.lb_idiomas_entendidos.pack(anchor="w", **p)
        self.var_jf_outros_idiomas.trace_add("write", lambda *_: self.atualizar_idiomas_entendidos())
        self.bt_mais_idiomas = self._botao(lateral, "Mais idiomas...", self.abrir_mais_idiomas, "fantasma")
        self.bt_mais_idiomas.pack(anchor="w", pady=(0, 4), **p)
        self.var_jf_sobrescrever = tk.BooleanVar(value=False)
        self._checkbox(lateral, "Substituir o que já existe (legendas, pôster, backdrop e .nfo)",
                       self.var_jf_sobrescrever)

        # ===================================================== Tradução (Claude)
        lateral = self._secao_config("Tradução")
        self._rotulo(lateral, "A legenda que só existe em outro idioma vira 'Nome.pt-BR.srt', com os mesmos horários. "
                              "Vale para \"Traduzir legendas\", \"Criar legenda pelo áudio\" e os vídeos avulsos.").pack(
            anchor="w", pady=(0, 6), **p)
        self._rotulo(lateral, "Quem traduz:").pack(anchor="w", pady=(2, 2), **p)
        self.var_jf_motor_traducao = tk.StringVar(value=self.MOTORES_TRADUCAO[0])
        menu = self._menu_opcoes(lateral, self.var_jf_motor_traducao, self.MOTORES_TRADUCAO)
        menu.configure(width=420)
        menu.pack(anchor="w", **p)
        self._rotulo(lateral, "Claude: tradução natural, entende o contexto das falas anteriores e as gírias; pago por "
                              "uso (a chave da Anthropic fica em Chaves de API; há o modo econômico, pela metade). "
                              "Local: roda no seu PC, sem chave e sem internet (baixa o modelo na 1ª vez, ~100 MB por "
                              "idioma); boa para entender o filme, mas mais literal. Do inglês e do espanhol vai direto; "
                              "dos outros idiomas, passa pelo inglês.", fonte=ctk.CTkFont(Tema.FAMILIA, 11)).pack(
            anchor="w", pady=(6, 4), **p)
        self._rotulo(lateral, "Modelo do Claude:").pack(anchor="w", pady=(6, 2), **p)
        self.var_jf_modelo_traducao = tk.StringVar(value="claude-sonnet-4-6")
        self._entrada(lateral, self.var_jf_modelo_traducao, "claude-sonnet-4-6", width=320).pack(anchor="w", **p)
        self.var_jf_traducao_economica = tk.BooleanVar(value=False)
        self.cb_traducao_economica = self._checkbox(lateral, "Modo econômico da Anthropic (metade do preço)",
                                                    self.var_jf_traducao_economica)
        self._rotulo(lateral, "As legendas vão num LOTE e ficam prontas em até 24 h (quase sempre menos de 1 h). Vale "
                              "para \"Traduzir legendas\" (aba Jellyfin), os vídeos avulsos e o robô "
                              "--traduzir-legendas. Nos avulsos, a dublagem desses vídeos fica para a próxima vez: ao "
                              "abrir o Maestro (ou no robô --avulsos) o lote pronto é gravado. O Claude também "
                              "reaproveita as regras fixas de cada pedido (cache de prompt: essa parte custa 10% nos "
                              "pedidos seguintes); essa economia é pequena, porque o que mais pesa é o texto traduzido "
                              "que volta.", fonte=ctk.CTkFont(Tema.FAMILIA, 11)).pack(anchor="w", pady=(0, 4), **p)

        # ===================================================== Legenda pelo áudio (Whisper)
        lateral = self._secao_config("Legenda pelo áudio")
        self._rotulo(lateral, "Para vídeos SEM nenhuma legenda: o Whisper ouve o áudio no seu PC (grátis) e, se o "
                              "áudio não for português, o Claude traduz.").pack(anchor="w", pady=(0, 4), **p)
        self._rotulo(lateral, "Modelo do Whisper (maior = acerta mais, mas demora mais):").pack(anchor="w",
                                                                                              pady=(2, 2), **p)
        self.var_jf_modelo_whisper = tk.StringVar(value="small")
        menu = self._menu_opcoes(lateral, self.var_jf_modelo_whisper, self.MODELOS_WHISPER)
        menu.configure(width=320)
        menu.pack(anchor="w", **p)
        self.var_jf_whisper_gpu = tk.BooleanVar(value=False)
        self._checkbox(lateral, "Usar a placa de vídeo NVIDIA", self.var_jf_whisper_gpu)

        # ===================================================== Dublagem
        self._montar_config_dublagem(self._secao_config("Dublagem"))

        # ===================================================== Vídeos avulsos (caixa de entrada)
        lateral = self._secao_config("Vídeos avulsos")
        self._rotulo(lateral, "Uma caixa de entrada para vídeos fora das bibliotecas: o que você colocar nesta pasta "
                              "ganha a legenda em português (pelo áudio ou traduzindo a que já tiver) e, se marcado, "
                              "a versão dublada. Os arquivos novos ficam ao lado do original, que nunca é alterado. "
                              "O trabalho em si fica na aba Avulsos (que também aceita vídeos de outras pastas); "
                              "o robô --avulsos faz tudo sozinho no horário agendado.").pack(
            anchor="w", pady=(0, 8), **p)
        self._rotulo(lateral, "Pasta de vídeos avulsos:").pack(anchor="w", **p)
        linha = ctk.CTkFrame(lateral, fg_color="transparent")
        linha.pack(fill="x", pady=(2, 6), **p)
        self.var_jf_pasta_avulsos = tk.StringVar()
        self._entrada(linha, self.var_jf_pasta_avulsos, r"ex.: D:\Para Dublar").pack(side="left", fill="x",
                                                                                       expand=True)
        self._botao(linha, "Escolher...", lambda: self._escolher_pasta_em(self.var_jf_pasta_avulsos),
                    "secundario").pack(side="left", padx=(8, 0))
        self.var_jf_avulsos_legendar = tk.BooleanVar(value=True)
        self._checkbox(lateral, "Legendar: a legenda em português entra como faixa DENTRO do vídeo (o .srt ao lado sai)",
                       self.var_jf_avulsos_legendar)
        self.var_jf_avulsos_dublar = tk.BooleanVar(value=True)
        self._checkbox(lateral, "Dublar (com o motor e as vozes de Configurações > Dublagem)",
                       self.var_jf_avulsos_dublar)

        # ===================================================== Jellyfin (servidor)
        lateral = self._secao_config("Jellyfin")
        self.var_jf_url = tk.StringVar(value="http://localhost:8096")
        self.var_jf_chave_jellyfin = tk.StringVar()
        self.var_jf_atualizar = tk.BooleanVar(value=True)
        self._rotulo(lateral, "Endereço do servidor (a chave fica em Chaves de API):").pack(anchor="w", **p)
        self._entrada(lateral, self.var_jf_url, "http://localhost:8096", width=320).pack(anchor="w", pady=(2, 6), **p)
        self._checkbox(lateral, "Atualizar a biblioteca no fim (scan)", self.var_jf_atualizar)
        # o mesmo scan do fim do Organizar/vigia, na hora (ex.: séries que não apareceram no Jellyfin)
        self.bt_scan_jellyfin = self._botao(lateral, "Atualizar a biblioteca agora", self.ao_atualizar_jellyfin_agora)
        self.bt_scan_jellyfin.pack(anchor="w", pady=(6, 0), **p)

        # ===================================================== Avisos e resumo do dia
        lateral = self._secao_config("Avisos e resumo do dia")
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
        self.bt_testar_avisos.pack(anchor="w", pady=(0, 0), **p)
        self.var_jf_resumo_diario = tk.BooleanVar(value=False)
        self._checkbox(lateral, "Resumo do dia às 21h (o que foi baixado, organizado, traduzido...)",
                       self.var_jf_resumo_diario)

        # ===================================================== Chaves de API (todas num lugar, cada uma com Validar)
        self._montar_config_chaves(self._secao_config("Chaves de API"))

        # ===================================================== Gastos (APIs pagas)
        lateral = self._secao_config("Gastos (APIs pagas)")
        self._rotulo(lateral, "Quanto o Maestro gastou neste mês nas APIs pagas (estimativa pelos pedidos feitos):",
                     suave=False).pack(anchor="w", pady=(0, 4), **p)
        self.lb_gastos_mes = ctk.CTkLabel(lateral, text="US$ 0.00 (nada ainda)", font=self.f_secao,
                                          text_color=Tema.TEXTO, anchor="w")
        self.lb_gastos_mes.pack(anchor="w", pady=(0, 2), **p)
        self.lb_cotacao = ctk.CTkLabel(lateral, text="", font=ctk.CTkFont(Tema.FAMILIA, 11),
                                       text_color=Tema.TEXTO_SUAVE, anchor="w")
        self.lb_cotacao.pack(anchor="w", pady=(0, 10), **p)
        self._rotulo(lateral, "Mostrar em:").pack(anchor="w", **p)
        self.var_jf_moeda_gastos = tk.StringVar(value=self.MOEDAS_GASTOS[0])
        menu = self._menu_opcoes(lateral, self.var_jf_moeda_gastos, self.MOEDAS_GASTOS)
        menu.configure(width=320)
        menu.pack(anchor="w", pady=(2, 8), **p)
        self.campo_teto_gastos = self._numero(lateral, "Teto do mês, na moeda escolhida (0 = sem teto): ao chegar nele, "
                                                       "as tarefas pagas param e o que ficou pronto é guardado",
                                              0, 0, 100000, 10)
        self.campo_cotacao_dolar = self._numero(lateral, "Cotação do dólar em R$ (0 = automática: PTAX do Banco "
                                                         "Central, consultada uma vez por dia)", 0, 0, 50, 0.05,
                                                decimal=True, casas=2, virgula=True)
        self.campo_iof = self._numero(lateral, "IOF da compra internacional no cartão, em % (confira na fatura)",
                                      3.5, 0, 20, 0.1, decimal=True, virgula=True)
        self._rotulo(lateral, "Atenção: a API é cobrada À PARTE da sua assinatura. A assinatura do Claude (Pro/Max) e "
                              "a do Google (Gemini/AI Pro) cobrem o uso no site e no app, não a chave de API que o "
                              "Maestro usa. O valor oficial está em console.anthropic.com (Claude) e em "
                              "aistudio.google.com (Gemini); aqui é uma estimativa (na voz, pelo preço mais alto).",
                     fonte=ctk.CTkFont(Tema.FAMILIA, 11)).pack(anchor="w", pady=(8, 0), **p)

        # ===================================================== Agendamentos
        lateral = self._secao_config("Agendamentos")
        self._rotulo(lateral, "As tarefas de robô (organizar, conferir canais, traduzir, dublar...) no Agendador de "
                              "Tarefas do Windows: rodam sozinhas, sem abrir a janela.").pack(anchor="w", pady=(0, 6), **p)
        # as tarefas de robô (organizar, conferir canais, traduzir...) no Agendador de Tarefas do Windows
        self.bt_agendar = self._botao(lateral, "Agendar tarefas...", self.ao_agendar)
        self.bt_agendar.pack(anchor="w", pady=(4, 0), **p)

        # ===================================================== Geral, backup e versão
        lateral = self._secao_config("Geral, backup e versão")
        self.var_jf_iniciar_windows = tk.BooleanVar(value=False)
        self._checkbox(lateral, "Iniciar junto com o Windows, minimizado perto do relógio", self.var_jf_iniciar_windows,
                       comando=self.ao_alternar_inicializacao)
        self.var_jf_fechar_bandeja = tk.BooleanVar(value=False)
        self._checkbox(lateral, "Ao fechar (X), continuar rodando perto do relógio (a vigia segue)",
                       self.var_jf_fechar_bandeja)
        self.var_jf_avisar_versao = tk.BooleanVar(value=True)
        self._checkbox(lateral, "Avisar quando sair versão nova do programa (ao abrir)", self.var_jf_avisar_versao)
        self.var_jf_atualizar_sozinho = tk.BooleanVar(value=False)
        self._checkbox(lateral, "Atualizar sozinho: baixar, instalar e reiniciar o programa (quando estiver livre)",
                       self.var_jf_atualizar_sozinho)
        self.var_jf_versao_avisada = tk.StringVar(value="")
        self._separador(lateral)
        # onde o programa está no computador (e, no Windows, o lugar fixo com atalhos)
        self.lb_pasta_programa = ctk.CTkLabel(lateral, text="", font=ctk.CTkFont(Tema.FAMILIA, 11),
                                              text_color=Tema.TEXTO_FRACO, anchor="w", justify="left", wraplength=600)
        self.lb_pasta_programa.pack(anchor="w", **p)
        self.bt_abrir_pasta_programa = self._botao(lateral, "Abrir a pasta do programa", self.ao_abrir_pasta_programa,
                                                   "fantasma")
        self.bt_abrir_pasta_programa.pack(anchor="w", **p)
        self.bt_instalar_fixo = self._botao(lateral, "Instalar no lugar fixo (com atalhos)...", self.ao_instalar_fixo,
                                            "secundario")
        self._separador(lateral)
        # levar tudo para outro computador (ou guardar uma cópia): opções, regras, canais e memória de downloads
        self.bt_exportar_config = self._botao(lateral, "Exportar configurações...", self.ao_exportar_config)
        self.bt_exportar_config.pack(anchor="w", pady=(4, 0), **p)
        self.bt_importar_config = self._botao(lateral, "Importar configurações...", self.ao_importar_config)
        self.bt_importar_config.pack(anchor="w", pady=(6, 0), **p)
        self._mostrar_campos_jf()

        self.tabela_jf, faixa = self._criar_tabela(
            corpo, "Arquivos", self.COLUNAS_JF,
            "Escolha as pastas e clique em Pré-visualizar. Nada é movido sem você confirmar.")
        # pede só 3 linhas: o resto da altura vem do "peso" da grade. Pedindo 10, a soma com o painel e o console
        # passava da janela (até em 1000 px) e o Tk espremia tudo: a lista nunca crescia e o console ficava cortado
        self.tabela_jf.configure(displaycolumns=self.ORDEM_TELA_JF, height=3)
        self.tabela_jf.bind("<<TreeviewSelect>>", lambda e: self.ao_selecionar_jf())
        self.tabela_jf.bind("<Button-1>", self._ao_clicar_tabela_jf)
        self._fora_jf: set[str] = set()       # "vai mover" desmarcados (☐): o Organizar deixa onde estão
        self._filtros_col_jf: dict[str, set[str]] = {}     # filtro por coluna (clique no título): coluna -> valores
        self._janela_filtro_jf = None
        topo = self._topos_tabela[str(self.tabela_jf)]
        self._montar_filtros_jf(topo)
        self._titulos_jf()
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
        self._corpo_jf = corpo
        corpo.grid_rowconfigure(0, weight=5, minsize=round(self.MINIMO_LISTA_JF * self._pontos()))
        corpo.grid_rowconfigure(2, weight=1, minsize=round(self.ALTURA_CONSOLE_JF * self._pontos()))  # ~4 linhas
        aba.bind("<Configure>", self._ajustar_altura_jf, add="+")

    # ------------------------------------------------------------------ aba Avulsos
    COLUNAS_AV = (("n", "#", 44, False), ("video", "Vídeo", 300, True), ("legenda", "Legenda em português", 200, False),
                  ("acao", "O que falta", 280, True), ("pasta", "Pasta", 300, True))

    def _montar_aba_avulsos(self, aba) -> None:
        """Vídeos fora das bibliotecas: a caixa de entrada (Configurações > Vídeos avulsos) e/ou arquivos de qualquer
        pasta. Olhar mostra o que falta em cada um; Processar legenda (traduz ou pelo áudio) e dubla."""
        aba.grid_rowconfigure(2, weight=1)
        cartao = self._cartao(aba)
        cartao.grid(row=0, column=0, sticky="ew", padx=28, pady=(14, 0))
        cartao.grid_columnconfigure(1, weight=1)
        self._rotulo(cartao, "Caixa de entrada:", suave=False, fonte=self.f_secao).grid(
            row=0, column=0, padx=(20, 12), pady=(16, 6))
        self.campo_pasta_av = self._entrada(cartao, self.var_jf_pasta_avulsos, r"ex.: D:\Para Dublar", altura=40)
        self.campo_pasta_av.grid(row=0, column=1, sticky="ew", pady=(16, 6))
        self._botao(cartao, "Escolher...", self._escolher_pasta_avulsos, largura=110).grid(
            row=0, column=2, padx=(10, 20), pady=(16, 6))
        baixo = ctk.CTkFrame(cartao, fg_color="transparent")
        baixo.grid(row=1, column=0, columnspan=3, sticky="ew", padx=(2, 20), pady=(0, 10))
        self.cb_av_legendar = self._checkbox(baixo, "Legendar (a legenda em português entra no vídeo)",
                                             self.var_jf_avulsos_legendar)
        self.cb_av_legendar.pack_configure(side="left")
        self.cb_av_dublar = self._checkbox(baixo, "Dublar (com o motor e as vozes de Configurações > Dublagem)",
                                           self.var_jf_avulsos_dublar)
        self.cb_av_dublar.pack_configure(side="left")
        self._botao(baixo, "⚙ Opções", self.mostrar_opcoes_avulsos, "fantasma", largura=100).pack(side="right")

        barra = ctk.CTkFrame(aba, fg_color="transparent")
        barra.grid(row=1, column=0, sticky="ew", padx=28, pady=12)
        self.bt_av_olhar = self._botao(barra, "Olhar", self.ao_olhar_avulsos, "primario", largura=150)
        self.bt_av_adicionar = self._botao(barra, "Adicionar vídeos...", self.ao_adicionar_avulsos, largura=170)
        self.bt_av_processar = self._botao(barra, "Processar", self.ao_processar_avulsos, largura=140)
        self.bt_av_limpar = self._botao(barra, "Tirar os adicionados", self.limpar_avulsos_adicionados, largura=170)
        self.bt_av_testar = self._botao(barra, "🧪 Testar", self.ao_testar_avulso, largura=110)
        self.campo_av_minutos = self.campo_minutos(barra)
        self.bt_av_roteiro = self._botao(barra, "📜 Roteiro", self.ao_roteiro_avulso, largura=120)
        self.bt_parar_av = self._botao(barra, "Parar", self.ao_parar, "perigo", largura=100)
        self.bt_previas_av = self._botao(barra, "🎧 Prévias", self.ao_previas, largura=130)
        for b in (self.bt_av_olhar, self.bt_av_adicionar, self.bt_av_testar, self.campo_av_minutos,
                  self.bt_av_roteiro, self.bt_av_processar, self.bt_av_limpar):
            b.pack(side="left", padx=(0, 10))
        self.bt_av_testar.pack_configure(padx=(0, 6))
        self.bt_parar_av.pack(side="right")
        self.bt_previas_av.pack(side="right", padx=(0, 10))

        corpo = self._corpo(aba, linha=2)
        self.tabela_av, faixa = self._criar_tabela(
            corpo, "Vídeos", self.COLUNAS_AV,
            "Nenhum vídeo ainda. Escolha a caixa de entrada e clique em Olhar, ou clique em Adicionar vídeos.")
        self.lb_contador_av, self.lb_vazio_av = self._extras_tabela[str(self.tabela_av)]
        self.tabela_av.bind("<Double-1>", lambda e: self.ao_abrir_pasta_avulso())
        self.lb_resumo_av = ctk.CTkLabel(faixa, text="", font=self.f_rotulo, text_color=Tema.TEXTO_SUAVE, anchor="w")
        self.lb_resumo_av.pack(side="left")
        self._botao(faixa, "Abrir a pasta do vídeo", self.ao_abrir_pasta_avulso, "fantasma").pack(side="right")
        self._criar_console(corpo, linha=1, altura=120)
        corpo.grid_rowconfigure(1, weight=2, minsize=round(150 * self._pontos()))    # o console: ~4 linhas
        self.avulsos_adicionados: list[str] = []      # vídeos de outras pastas (além da caixa de entrada)

    def _escolher_pasta_avulsos(self) -> None:
        self._escolher_pasta_em(self.var_jf_pasta_avulsos)
        if self.var_jf_pasta_avulsos.get().strip():
            self.ao_olhar_avulsos()

    def mostrar_opcoes_avulsos(self) -> None:
        self.mostrar_aba(self.ABA_CONFIG)
        self.mostrar_config("Vídeos avulsos")

    def limpar_avulsos_adicionados(self) -> None:
        """Tira da lista os vídeos de outras pastas (a caixa de entrada continua)."""
        self.avulsos_adicionados.clear()
        self.ao_olhar_avulsos()

    def mostrar_avulsos(self, linhas) -> None:
        """linhas: [(vídeo Path, legenda, o que falta, pronto?)] (automacao.situacao_avulsos)."""
        self.tabela_av.delete(*self.tabela_av.get_children())
        for i, (video, legenda, acao, pronto) in enumerate(linhas):
            tags = ("ok",) if pronto else ("par" if i % 2 == 0 else "impar",)
            self.tabela_av.insert("", "end", iid=str(i), tags=tags,
                                  values=(i + 1, video.name, legenda, ("✓ " if pronto else "") + acao, str(video.parent)))
        falta = sum(1 for *_, pronto in linhas if not pronto)
        self.lb_contador_av.configure(text=str(len(linhas)))
        self.lb_resumo_av.configure(text=(f"{falta} com algo a fazer · {len(linhas) - falta} pronto(s)" if linhas
                                          else ""))
        if linhas:
            self.lb_vazio_av.place_forget()
        else:
            self.lb_vazio_av.place(relx=0.5, rely=0.55, anchor="center")

    def linhas_avulsos(self) -> list[tuple]:
        """O que a tabela mostra: [(vídeo, legenda, o que falta, pasta)] (para os testes e o 'abrir pasta')."""
        return [tuple(self.tabela_av.item(i, "values"))[1:] for i in self.tabela_av.get_children()]

    def ao_abrir_pasta_avulso(self) -> None:
        escolhidos = self.tabela_av.selection() or self.tabela_av.get_children()[:1]
        if escolhidos:
            self._abrir_pasta_do_sistema(self.tabela_av.item(escolhidos[0], "values")[4])

    def _abrir_pasta_do_sistema(self, pasta: str) -> None:      # o app abre no Explorer
        pass

    # ------------------------------------------------------------------ ⚙ Configurações (4ª aba)
    ABA_CONFIG = "⚙ Configurações"
    GRUPOS_CONFIG = (("VÍDEOS", ("Opções de busca",)),      # a aba Vídeos: no topo, fácil de achar
                     ("BIBLIOTECA", ("Nomes e TMDB", "Organização e limpeza", "Vigia (automático)", "Espelhos (.strm)")),
                     ("LEGENDAS E VOZ", ("Legendas", "Tradução", "Legenda pelo áudio", "Dublagem",
                                         "Vídeos avulsos")),
                     ("SERVIDOR E AVISOS", ("Jellyfin", "Avisos e resumo do dia")),
                     ("SISTEMA", ("Chaves de API", "Gastos (APIs pagas)", "Agendamentos",
                                  "Geral, backup e versão")))
    ICONES_CONFIG = {"Nomes e TMDB": "🏷", "Organização e limpeza": "🧹", "Vigia (automático)": "👁",
                     "Espelhos (.strm)": "🔗", "Legendas": "💬", "Tradução": "🌐", "Legenda pelo áudio": "🎧",
                     "Dublagem": "🎙", "Jellyfin": "🖥", "Avisos e resumo do dia": "🔔", "Chaves de API": "🔑",
                     "Agendamentos": "⏰", "Opções de busca": "⬇", "Geral, backup e versão": "⚙",
                     "Vídeos avulsos": "📥", "Gastos (APIs pagas)": "💲"}

    def _montar_aba_config(self, aba) -> None:
        """Menu de categorias à esquerda e, à direita, as opções da categoria escolhida (rola se for comprida)."""
        aba.grid_columnconfigure(0, weight=0)          # o menu tem largura fixa; o resto é do painel
        aba.grid_columnconfigure(1, weight=1)
        aba.grid_rowconfigure(0, weight=1)
        # o menu também rola: em notebook (ou com o zoom do Windows em 125%) os últimos itens ficavam escondidos
        self.menu_config = menu = ctk.CTkScrollableFrame(aba, width=226, fg_color=Tema.CARTAO, corner_radius=Tema.RAIO,
                                                         border_width=1, border_color=Tema.CARTAO_BORDA,
                                                         scrollbar_button_color=Tema.CARTAO_BORDA,
                                                         scrollbar_button_hover_color=Tema.CAMPO_BORDA)
        menu.grid(row=0, column=0, sticky="ns", padx=(28, 14), pady=(14, 14))
        self._botoes_config: dict[str, ctk.CTkButton] = {}
        for grupo, nomes in self.GRUPOS_CONFIG:
            ctk.CTkLabel(menu, text=grupo, font=ctk.CTkFont(Tema.FAMILIA, 10, "bold"), text_color=Tema.TEXTO_FRACO,
                         anchor="w").pack(fill="x", padx=18, pady=(12, 2))
            for nome in nomes:
                botao = ctk.CTkButton(menu, text=f"{self.ICONES_CONFIG.get(nome, '')}  {nome}", anchor="w", height=32,
                                      corner_radius=9, font=self.f_normal, fg_color="transparent",
                                      hover_color=Tema.SECUNDARIA_HOVER, text_color=Tema.TEXTO_SUAVE,
                                      command=lambda n=nome: self.mostrar_config(n))
                botao.pack(fill="x", padx=10, pady=1)
                self._botoes_config[nome] = botao
        self.painel_config = ctk.CTkScrollableFrame(aba, fg_color=Tema.CARTAO, corner_radius=Tema.RAIO, border_width=1,
                                                    border_color=Tema.CARTAO_BORDA,
                                                    scrollbar_button_color=Tema.CARTAO_BORDA,
                                                    scrollbar_button_hover_color=Tema.CAMPO_BORDA)
        self.painel_config.grid(row=0, column=1, sticky="nsew", padx=(0, 28), pady=(14, 14))
        self._secoes_config: dict[str, ctk.CTkFrame] = {}
        self._config_atual = ""

    def _secao_config(self, nome: str) -> ctk.CTkFrame:
        """O quadro de uma categoria (criado na 1ª vez, com o título)."""
        if nome not in self._secoes_config:
            quadro = ctk.CTkFrame(self.painel_config, fg_color="transparent")
            ctk.CTkLabel(quadro, text=nome, font=ctk.CTkFont(Tema.FAMILIA, 20, "bold"), text_color=Tema.TEXTO,
                         anchor="w").pack(fill="x", padx=18, pady=(16, 8))
            self._secoes_config[nome] = quadro
        return self._secoes_config[nome]

    def mostrar_config(self, nome: str) -> None:
        """Mostra a categoria `nome` em ⚙ Configurações (e marca no menu)."""
        for outro, quadro in self._secoes_config.items():
            quadro.pack_forget()
            self._botoes_config[outro].configure(fg_color="transparent", text_color=Tema.TEXTO_SUAVE)
        self._secoes_config[nome].pack(fill="x", anchor="n", padx=(6, 140))
        self._botoes_config[nome].configure(fg_color=Tema.SELECAO, text_color=Tema.TEXTO)
        self._config_atual = nome
        try:
            self.painel_config._parent_canvas.yview_moveto(0)
        except (AttributeError, tk.TclError):
            pass
        self._rolar_menu_config(self._botoes_config[nome])

    def _rolar_menu_config(self, botao) -> None:
        """Se o item escolhido estiver fora da parte visível do menu, rola o menu até ele."""
        try:
            canvas = self.menu_config._parent_canvas
            self.update_idletasks()
            total = max(self.menu_config.winfo_height(), 1)
            visivel = canvas.winfo_height()
            topo = canvas.yview()[0] * total
            y, h = botao.winfo_y(), botao.winfo_height()
            if y < topo or y + h > topo + visivel:
                canvas.yview_moveto(max(0.0, (y - visivel / 2) / total))
        except (AttributeError, tk.TclError):
            pass

    def _quebrar_textos_config(self, largura: int = 780) -> None:
        """Textos compridos das Configurações quebram a linha em vez de sumir na borda do painel."""
        pendentes = list(self._secoes_config.values())
        while pendentes:
            widget = pendentes.pop()
            pendentes.extend(widget.winfo_children())
            if isinstance(widget, ctk.CTkLabel) and not widget.cget("wraplength"):
                widget.configure(wraplength=largura)

    def config_atual(self) -> str:
        return self._config_atual

    def atualizar_resumo_config(self) -> None:
        """A linha do contexto na aba Jellyfin: o que está ligado (o detalhe fica em ⚙ Configurações)."""
        idiomas = ", ".join(c for c, v in self.vars_idioma_jf.items() if v.get())
        outros = self.var_jf_outros_idiomas.get().strip()
        partes = [("TMDB ✓" if self.var_jf_tmdb.get() else "TMDB desligado"),
                  (f"Legendas: {idiomas}{', ' + outros if outros else ''}" if self.var_jf_legendas.get()
                   else "Legendas: não baixa"),
                  ("Propaganda do torrent: apaga" if self.var_jf_lixo.get() else "Propaganda do torrent: fica"),
                  # a pasta antiga do download é OUTRA opção (antes não aparecia aqui e parecia que era apagada)
                  ("Pasta do download: apaga" if self.var_jf_apagar_pasta.get() else "Pasta do download: fica"),
                  f"Dublagem: {self.NOMES_MODO_VOZ[self.var_jf_modo_voz.get()]}",
                  ("Vigia ligada" if self.var_jf_vigiar.get() else "Vigia desligada")]
        self.lb_resumo_config.configure(text="   ·   ".join(partes))

    # ---- Dublagem: o motor (Piper, Gemini ou Misto) e o que cada um usa
    NOMES_MODO_VOZ = {"piper": "Piper", "cloud": "Google Cloud TTS", "gemini": "Gemini",
                      "misto": "Misto (Gemini + Piper)"}

    def _montar_config_dublagem(self, lateral) -> None:
        p = dict(padx=18)
        self._rotulo(lateral, "Quem lê as falas (o motor da voz):").pack(anchor="w", pady=(0, 6), **p)
        self.var_jf_motor_voz = tk.StringVar(value=self.MOTORES_VOZ[0])
        self.var_jf_figurantes_piper = tk.BooleanVar(value=False)
        self.var_jf_modo_voz = tk.StringVar(value="piper")
        modos = ctk.CTkFrame(lateral, fg_color="transparent")
        modos.pack(fill="x", **p)
        self._cartoes_modo_voz: dict[str, ctk.CTkFrame] = {}
        for valor, titulo, texto in (
                ("piper", "Piper", "Grátis, no seu PC. Voz mais robótica; uma voz para o filme todo."),
                ("cloud", "Google Cloud TTS", "Neural2, WaveNet, Standard ou Studio. Cota grátis por mês; "
                                              "acima dela, por caractere."),
                ("gemini", "Gemini (premium)", "Voz natural, com emoção. Pago por uso (Google AI Studio)."),
                ("misto", "Misto: Gemini + Piper", "Principais com o Gemini, figurantes com o Piper. "
                                                   "Economiza pedidos.")):
            cartao = ctk.CTkFrame(modos, fg_color=Tema.CAMPO, corner_radius=12, border_width=1,
                                  border_color=Tema.CAMPO_BORDA)
            cartao.pack(side="left", fill="both", expand=True, padx=(0, 10))
            ctk.CTkRadioButton(cartao, text=titulo, value=valor, variable=self.var_jf_modo_voz,
                               command=self._ao_escolher_modo_voz, font=self.f_botao, text_color=Tema.TEXTO,
                               fg_color=Tema.PRIMARIA, hover_color=Tema.PRIMARIA_HOVER).pack(anchor="w", padx=14,
                                                                                              pady=(12, 4))
            ctk.CTkLabel(cartao, text=texto, font=ctk.CTkFont(Tema.FAMILIA, 11), text_color=Tema.TEXTO_SUAVE,
                         anchor="w", justify="left", wraplength=170).pack(anchor="w", padx=14, pady=(0, 12))
            self._cartoes_modo_voz[valor] = cartao
        self.var_jf_motor_voz.trace_add("write", lambda *_: self._sincronizar_modo_voz())
        self.var_jf_figurantes_piper.trace_add("write", lambda *_: self._sincronizar_modo_voz())

        self._rotulo(lateral, "Como fica a dublagem", suave=False, fonte=self.f_secao).pack(anchor="w", pady=(16, 4),
                                                                                           **p)
        self.var_jf_separar_vozes = tk.BooleanVar(value=True)
        self._checkbox(lateral, "Dublagem natural: tirar as vozes originais (fica a música e os efeitos)",
                       self.var_jf_separar_vozes, self._ao_trocar_separar_vozes)
        self._rotulo(lateral, "IA no seu PC, grátis, porém LENTA: um filme de 2 h leva de 1 a 3 horas a mais no processador "
                              "(com placa de vídeo, bem menos). Desmarcado: "
                              "\"voice-over\" (o áudio original só abaixa enquanto a voz fala).",
                     fonte=ctk.CTkFont(Tema.FAMILIA, 11)).pack(anchor="w", padx=(46, 18), pady=(0, 6))
        self.var_jf_ambientar_voz = tk.BooleanVar(value=True)
        self.cb_ambientar_voz = self._checkbox(
            lateral, "Ambientar a voz dublada: o mesmo tom, volume e eco das vozes originais (parece estar na cena)",
            self.var_jf_ambientar_voz)
        self.cb_ambientar_voz.pack_configure(padx=(42, 18))
        self.var_jf_separar_gpu = tk.BooleanVar(value=True)
        self.cb_separar_gpu = self._checkbox(
            lateral, "Usar a placa de vídeo (bem mais rápido; se não der, usa o processador)", self.var_jf_separar_gpu)
        self.cb_separar_gpu.pack_configure(padx=(42, 18), pady=(4, 8))
        self.var_jf_dublagem_no_original = tk.BooleanVar(value=True)
        self._checkbox(lateral, "Gravar a dublagem dentro do próprio vídeo (faixa \"Português (dublagem IA)\")",
                       self.var_jf_dublagem_no_original, self._ao_trocar_dublagem_no_original)
        self._rotulo(lateral, "O áudio original continua lá, como 2ª faixa; a cópia é conferida antes de trocar o "
                              "original. Desmarcado: um arquivo à parte, \"Nome - Dublado IA.mkv\".",
                     fonte=ctk.CTkFont(Tema.FAMILIA, 11)).pack(anchor="w", padx=(46, 18), pady=(0, 6))
        self.campo_minutos_teste = self._numero(
            lateral, "Teste (botões \"Testar\"): quantos minutos legendar e dublar, num vídeo curto à parte (gasta só "
                     "o desse trecho; dá para mudar também ao lado dos botões):", 2, *self.MINUTOS_TESTE,
            var=self.var_minutos_teste())
        self.var_jf_dublagem_previa = tk.BooleanVar(value=True)
        self.cb_dublagem_previa = self._checkbox(
            lateral, "Fase de teste: primeiro uma prévia para eu ouvir e aprovar (botão \"🎧 Prévias\")",
            self.var_jf_dublagem_previa)
        self.cb_dublagem_previa.pack_configure(padx=(42, 18))

        self._rotulo(lateral, "Vozes", suave=False, fonte=self.f_secao).pack(anchor="w", pady=(16, 4), **p)
        self._rotulo(lateral, "Voz principal do Gemini:").pack(anchor="w", pady=(2, 2), **p)
        self.var_jf_voz_gemini = tk.StringVar(value=self.VOZES_GEMINI[0])
        linha = ctk.CTkFrame(lateral, fg_color="transparent")
        linha.pack(fill="x", **p)
        self.menu_voz_gemini = self._menu_opcoes(linha, self.var_jf_voz_gemini, self.vozes_gemini_do_menu())
        self.menu_voz_gemini.configure(width=320)
        self.menu_voz_gemini.pack(side="left")
        self.bt_ouvir_voz = self._botao(linha, "▶  Ouvir uma frase de teste", self.ao_ouvir_voz, "fantasma")
        self.bt_ouvir_voz.pack(side="left", padx=(8, 0))
        self._rotulo(lateral, "Voz do Piper (no modo Piper, nos figurantes e nos filmes que vão com o Piper):").pack(
            anchor="w", pady=(8, 2), **p)
        self.var_jf_voz_dublagem = tk.StringVar(value="faber")
        menu = self._menu_opcoes(lateral, self.var_jf_voz_dublagem, self.VOZES_DUBLAGEM)
        menu.configure(width=320)
        menu.pack(anchor="w", **p)
        self.var_jf_voz_por_personagem = tk.BooleanVar(value=False)
        self._checkbox(lateral, "Uma voz para cada personagem (o Gemini ouve o filme e separa quem fala; antes de "
                                "dublar, a tabela \"Vozes dos personagens\" deixa trocar)",
                       self.var_jf_voz_por_personagem)
        self.var_jf_vozes_sem_tabela = tk.BooleanVar(value=False)
        self._checkbox(lateral, "Escolher as vozes dos personagens sozinho (sem abrir a tabela)",
                       self.var_jf_vozes_sem_tabela)
        self.var_jf_usar_roteiro = tk.BooleanVar(value=True)
        self._checkbox(lateral, "Usar o roteiro do vídeo, quando houver, para saber quem fala", self.var_jf_usar_roteiro)
        self._rotulo(lateral, "Os robôs e os vídeos avulsos já escolhem as vozes sozinhos; a opção acima faz o mesmo "
                              "no \"Dublar\" da aba Jellyfin (a escolha fica guardada para os próximos episódios da "
                              "série). Roteiro: 'Nome do vídeo.roteiro.txt' ao lado do vídeo (o botão abaixo grava "
                              "assim, a partir de um link ou de um arquivo .txt, .html ou .pdf com texto). O roteiro "
                              "é comparado com a legenda no SEU PC, sem custo; o Gemini só ouve os trechos que o "
                              "roteiro não cobriu, e os personagens ficam com o nome de verdade.",
                     fonte=ctk.CTkFont(Tema.FAMILIA, 11)).pack(anchor="w", pady=(0, 4), **p)
        self._botao(lateral, "📜 Roteiro de um vídeo...", self.ao_roteiro_de_um_video, "fantasma",
                    largura=210).pack(anchor="w", pady=(2, 4), **p)

        # --- Google Cloud TTS: o tipo de voz (preço e cota grátis de cada um) e a voz
        self._rotulo(lateral, "Google Cloud TTS", suave=False, fonte=self.f_secao).pack(anchor="w", pady=(16, 4), **p)
        self._rotulo(lateral, "Tipo de voz (preço por milhão de caracteres e cota grátis do mês; estimativas, confira "
                              "em cloud.google.com/text-to-speech/pricing):").pack(anchor="w", pady=(0, 2), **p)
        self.var_jf_tipo_cloud = tk.StringVar(value=self.texto_tipo_cloud(voz_cloud.TIPO_PADRAO))
        self.menu_tipo_cloud = self._menu_opcoes(lateral, self.var_jf_tipo_cloud,
                                                 [self.texto_tipo_cloud(t) for t in voz_cloud.TIPOS])
        self.menu_tipo_cloud.configure(width=560, command=lambda _v: self._ao_trocar_tipo_cloud())
        self.menu_tipo_cloud.pack(anchor="w", **p)
        self._rotulo(lateral, "Voz:").pack(anchor="w", pady=(8, 2), **p)
        linha = ctk.CTkFrame(lateral, fg_color="transparent")
        linha.pack(fill="x", **p)
        self._vozes_cloud_da_conta: list[str] = []
        self.var_jf_voz_cloud = tk.StringVar(value=voz_cloud.texto_da_voz(voz_cloud.nome_da_voz("Neural2", "B")))
        self.menu_voz_cloud = self._menu_opcoes(linha, self.var_jf_voz_cloud, self.vozes_cloud_do_menu())
        self.menu_voz_cloud.configure(width=320)
        self.menu_voz_cloud.pack(side="left")
        self.bt_ouvir_cloud = self._botao(linha, "▶  Ouvir uma frase de teste", self.ao_ouvir_cloud, "fantasma")
        self.bt_ouvir_cloud.pack(side="left", padx=(8, 0))
        self.lb_cota_cloud = ctk.CTkLabel(lateral, text="", font=ctk.CTkFont(Tema.FAMILIA, 11),
                                          text_color=Tema.TEXTO_SUAVE, anchor="w", justify="left")
        self.lb_cota_cloud.pack(anchor="w", pady=(6, 0), **p)
        self._rotulo(lateral, "A chave fica em Chaves de API (\"Validar\" também traz a lista de vozes da sua conta). O "
                              "Google pede uma conta de faturamento ativa, mesmo para usar só a cota grátis.",
                     fonte=ctk.CTkFont(Tema.FAMILIA, 11)).pack(anchor="w", pady=(4, 0), **p)

        self._rotulo(lateral, "Vozes clonadas (réplica do Gemini)", suave=False, fonte=self.f_secao).pack(
            anchor="w", pady=(16, 4), **p)
        self._rotulo(lateral, "Clone a SUA voz (ou a de quem autorizou e gravou a frase de consentimento) para usar "
                              "como voz principal ou de um personagem. Não precisa de placa de vídeo: o Google cria "
                              "a voz e a chave fica só neste PC. Nunca a voz de atores ou de quem não sabe.").pack(
            anchor="w", pady=(0, 6), **p)
        self.lb_vozes_clonadas = ctk.CTkLabel(lateral, text="", font=self.f_rotulo, text_color=Tema.TEXTO,
                                              anchor="w", justify="left")
        self.lb_vozes_clonadas.pack(anchor="w", pady=(0, 6), **p)
        linha = ctk.CTkFrame(lateral, fg_color="transparent")
        linha.pack(fill="x", **p)
        self.bt_clonar_voz = self._botao(linha, "🎙  Clonar uma voz...", self.ao_clonar_voz, "secundario")
        self.bt_clonar_voz.pack(side="left")
        self.bt_remover_voz_clonada = self._botao(linha, "Remover voz clonada...", self.ao_remover_voz_clonada,
                                                  "fantasma")
        self.bt_remover_voz_clonada.pack(side="left", padx=(8, 0))
        self.bt_reclonar_voz = self._botao(linha, "↻  Clonar de novo...", self.ao_reclonar_voz, "fantasma")
        self.bt_reclonar_voz.pack(side="left", padx=(8, 0))
        self.var_jf_guardar_gravacoes = tk.BooleanVar(value=False)
        self._checkbox(lateral, "Guardar as gravações neste PC (quando a chave vencer, \"Clonar de novo\" refaz a voz "
                                "sem gravar outra vez). Desmarcada, as gravações são apagadas depois de clonar.",
                       self.var_jf_guardar_gravacoes)
        self.atualizar_vozes_clonadas(self._vozes_clonadas)

        self._rotulo(lateral, "Modo misto", suave=False, fonte=self.f_secao).pack(anchor="w", pady=(16, 4), **p)
        self.campo_limite_figurante = self._numero(lateral, "É figurante quem tem menos de (falas no filme):", 20, 2,
                                                   500, 5)
        self.var_jf_figurantes_cloud = tk.BooleanVar(value=False)
        self._checkbox(lateral, "Figurantes com o Google Cloud TTS (cota grátis do mês)", self.var_jf_figurantes_cloud)
        self._rotulo(lateral, "Voz melhor que a do Piper, sem custo (precisa da chave do Google Cloud; usa o tipo de "
                              "voz escolhido acima, com uma voz do gênero de cada figurante). Passando de 95% da cota "
                              "grátis do mês, voltam para o Piper sozinhos.",
                     fonte=ctk.CTkFont(Tema.FAMILIA, 11)).pack(anchor="w", pady=(0, 4), **p)
        self.var_jf_perguntar_filmes = tk.BooleanVar(value=True)
        self._checkbox(lateral, "Perguntar, a cada dublagem com vários filmes, quais vão com o Gemini (os outros vão "
                                "inteiros com o Piper)", self.var_jf_perguntar_filmes)
        self.var_jf_robo_so_piper = tk.BooleanVar(value=False)
        self._checkbox(lateral, "Nos robôs agendados (--dublar), usar só o Piper (sem custo)",
                       self.var_jf_robo_so_piper)

        self._rotulo(lateral, "Texto da fala", suave=False, fonte=self.f_secao).pack(anchor="w", pady=(16, 4), **p)
        self.var_jf_encurtar_falas = tk.BooleanVar(value=True)
        self._checkbox(lateral, "Falas longas: o Claude reescreve mais curtas e naturais (em vez de acelerar). A "
                                "legenda não muda: só o que a voz lê.", self.var_jf_encurtar_falas)
        self._rotulo(lateral, "As chaves do Gemini e da Anthropic ficam em Chaves de API. O Gemini manda até 30 falas "
                              "por pedido e guarda o progresso de cada filme: se o limite do dia acabar, a próxima "
                              "dublagem continua de onde parou.", fonte=ctk.CTkFont(Tema.FAMILIA, 11)).pack(
            anchor="w", pady=(10, 4), **p)
        self._sincronizar_modo_voz()

    MOTORES_TRADUCAO = ("Claude (pago, tradução mais natural)", "Local (grátis, no seu PC, mais literal)")
    MOEDAS_GASTOS = ("R$ (real, com a cotação do dólar + IOF)", "US$ (dólar, como as APIs cobram)")

    # ---- Vozes clonadas: a lista vem do app (vozes_clonadas.json); aqui só o que aparece na tela
    _vozes_clonadas: tuple = ()

    def vozes_gemini_do_menu(self) -> tuple:
        """As vozes prontas do Gemini e, depois, as clonadas ("Clonada: Izael (autorizada por Izael)")."""
        return self.VOZES_GEMINI + tuple(voz_clonada.texto_do_menu(v) for v in self._vozes_clonadas
                                         if not v.vencida())

    def atualizar_vozes_clonadas(self, vozes) -> None:
        self._vozes_clonadas = tuple(vozes)
        if not hasattr(self, "lb_vozes_clonadas"):
            return
        self.lb_vozes_clonadas.configure(
            text="\n".join(voz_clonada.descrever(v) for v in self._vozes_clonadas) or "Nenhuma voz clonada ainda.",
            text_color=Tema.TEXTO if self._vozes_clonadas else Tema.TEXTO_FRACO)
        self.bt_remover_voz_clonada.configure(state="normal" if self._vozes_clonadas else "disabled")
        self.bt_reclonar_voz.configure(state="normal" if any(v.tem_gravacoes() for v in self._vozes_clonadas)
                                       else "disabled")
        opcoes = self.vozes_gemini_do_menu()
        self.menu_voz_gemini.configure(values=list(opcoes))
        atual = self.var_jf_voz_gemini.get()
        if atual not in opcoes:                          # a escolhida foi removida (ou o nome mudou): volta ao padrão
            valor = valor_da_voz(atual)
            self.var_jf_voz_gemini.set(next((v for v in opcoes if valor_da_voz(v) == valor), self.VOZES_GEMINI[0]))

    def ao_clonar_voz(self) -> None:                    # o app faz (precisa da chave e da internet)
        pass

    def _ao_trocar_separar_vozes(self) -> None:
        """Ambientar e a placa de vídeo dependem da dublagem natural (é dela que vêm as vozes medidas)."""
        estado = "normal" if self.var_jf_separar_vozes.get() else "disabled"
        for caixa in (self.cb_ambientar_voz, self.cb_separar_gpu):
            caixa.configure(state=estado)

    def _ao_trocar_dublagem_no_original(self) -> None:
        """A fase de teste só faz sentido com a dublagem dentro do vídeo (à parte, o arquivo já é a "prévia")."""
        self.cb_dublagem_previa.configure(state="normal" if self.var_jf_dublagem_no_original.get() else "disabled")

    def ao_previas(self) -> None:                       # o app abre a janela das prévias
        pass

    def ao_testar_avulso(self) -> None:                 # o app faz (numa tarefa)
        pass

    MINUTOS_TESTE = (1, 60, 1)                           # mínimo, máximo e passo dos minutos do teste

    def var_minutos_teste(self) -> tk.StringVar:
        """Os minutos do teste: UM valor para o campo das Configurações e os campos ao lado dos botões Testar."""
        if not hasattr(self, "_var_minutos_teste"):
            self._var_minutos_teste = tk.StringVar(value="2")
        return self._var_minutos_teste

    def campo_minutos(self, barra) -> ctk.CTkFrame:
        """"[ - 2 + ] min" ao lado de um botão Testar (o mesmo valor das Configurações)."""
        quadro = ctk.CTkFrame(barra, fg_color="transparent")
        CampoNumerico(quadro, 2, *self.MINUTOS_TESTE, largura=100, var=self.var_minutos_teste()).pack(side="left")
        self._rotulo(quadro, "min").pack(side="left", padx=(6, 0))
        return quadro

    def ao_testar_dublagem_jf(self) -> None:            # o app faz: o teste do filme com legenda, na aba Jellyfin
        pass

    def ao_roteiro_jellyfin(self) -> None:              # o app faz: escolhe o filme ou episódio e o roteiro
        pass

    def ao_roteiro_avulso(self) -> None:                # o app faz: o roteiro do vídeo escolhido na lista
        pass

    def ao_roteiro_de_um_video(self) -> None:           # o app faz: escolhe o vídeo e o roteiro
        pass

    def pedir_roteiro(self, video: Path, ja_tem: Path | None) -> str | None:
        """Janela "Roteiro" (ver DialogoRoteiro): o link ou o caminho do arquivo, ou None (Cancelar)."""
        dialogo = DialogoRoteiro(self, video, ja_tem)
        self.wait_window(dialogo)
        return dialogo.resultado

    def texto_minutos_teste(self) -> str:
        minutos = float(self.campo_minutos_teste.get())
        return f"{minutos:g}".replace(".", ",") + " min"

    def atualizar_botao_testar(self) -> None:
        """Os minutos ficam no campo ao lado do botão (o mesmo das Configurações): só confere o valor."""
        self.campo_minutos_teste.set(self.campo_minutos_teste.get())

    def video_avulso_escolhido(self) -> Path | None:
        """O vídeo selecionado na lista da aba Avulsos (ou o 1º com algo a fazer, ou o 1º)."""
        itens = self.tabela_av.get_children()
        if not itens:
            return None
        escolhido = (self.tabela_av.selection() or [next((i for i in itens if "✓" not in str(
            self.tabela_av.item(i, "values")[3])), itens[0])])[0]
        valores = self.tabela_av.item(escolhido, "values")
        return Path(valores[4]) / valores[1]

    def atualizar_botoes_previas(self, quantas: int) -> None:
        """'🎧 Prévias (2)': destacado quando há prévia esperando você ouvir."""
        texto = f"🎧 Prévias ({quantas})" if quantas else "🎧 Prévias"
        for botao in (self.bt_previas_jf, self.bt_previas_av):
            botao.configure(text=texto, text_color=Tema.AVISO if quantas else Tema.TEXTO)

    def ao_olhar_avulsos(self) -> None:                 # o app faz (lê as pastas numa tarefa)
        pass

    def ao_adicionar_avulsos(self) -> None:
        pass

    def ao_processar_avulsos(self) -> None:
        pass

    def _pedir_arquivos_video(self, pasta: str = "", titulo: str = "Escolha os vídeos") -> tuple:
        """Janela do sistema para escolher um ou mais vídeos (em qualquer pasta; começa em `pasta`, se houver)."""
        tipos = "*.mp4 *.mkv *.avi *.mov *.m4v *.wmv *.m2ts *.webm *.mpg *.mpeg"
        extra = {"initialdir": pasta} if pasta and Path(pasta).is_dir() else {}
        return tuple(filedialog.askopenfilenames(parent=self, title=titulo,
                                                 filetypes=[("Vídeos", tipos), ("Todos os arquivos", "*.*")], **extra))

    def ao_remover_voz_clonada(self) -> None:
        pass

    def ao_reclonar_voz(self) -> None:
        pass

    def ao_ouvir_voz(self) -> None:
        pass

    def pedir_clonagem(self, pasta: Path, gravador=None, motivo_sem_microfone: str = "") -> dict | None:
        """Janela "Clonar uma voz" (ver DialogoClonarVoz): {nome, autorizada_por, referencia, consentimento}."""
        dialogo = DialogoClonarVoz(self, pasta, gravador, motivo_sem_microfone, [v.nome for v in self._vozes_clonadas])
        self.wait_window(dialogo)
        return dialogo.resultado

    # ---- Google Cloud TTS: tipos e vozes nos menus
    @staticmethod
    def texto_tipo_cloud(tipo: str) -> str:
        _no_nome, descricao, preco, cota = voz_cloud.TIPOS[tipo]
        milhoes = cota // 1_000_000
        cota_texto = (f"{milhoes} {'milhão' if milhoes == 1 else 'milhões'}" if milhoes else f"{cota // 1000} mil")
        return f"{tipo}: {descricao} · US$ {preco:g}/milhão · grátis {cota_texto} de caracteres/mês"

    def tipo_cloud_escolhido(self) -> str:
        return self.var_jf_tipo_cloud.get().split(":")[0]

    def vozes_cloud_do_menu(self, tipo: str | None = None) -> list[str]:
        """As vozes do tipo: as da conta (depois do Validar) ou as que existem em pt-BR."""
        tipo = tipo or (self.tipo_cloud_escolhido() if hasattr(self, "var_jf_tipo_cloud") else voz_cloud.TIPO_PADRAO)
        da_conta = [v for v in self._vozes_cloud_da_conta if voz_cloud.tipo_da_voz(v) == tipo]
        return [voz_cloud.texto_da_voz(v) for v in (da_conta or voz_cloud.vozes_do_tipo(tipo))]

    def _ao_trocar_tipo_cloud(self) -> None:
        opcoes = self.vozes_cloud_do_menu()
        self.menu_voz_cloud.configure(values=opcoes)
        if self.var_jf_voz_cloud.get() not in opcoes:              # mantém a letra (B = masculina), se existir
            letra = self.var_jf_voz_cloud.get().split()[0].rsplit("-", 1)[-1]
            self.var_jf_voz_cloud.set(next((o for o in opcoes if o.split()[0].endswith(f"-{letra}")), opcoes[0]))

    def atualizar_vozes_cloud(self, vozes: list[str]) -> None:
        """Depois do "Validar": as vozes de verdade da conta (pode haver mais que A, B e C)."""
        self._vozes_cloud_da_conta = list(vozes)
        self._ao_trocar_tipo_cloud()

    def ao_ouvir_cloud(self) -> None:
        pass

    def ao_testar_cloud_tts(self) -> None:
        pass

    def definir_estado_cloud(self, ok: bool | None, texto: str) -> None:
        cor = {True: Tema.SUCESSO, False: Tema.PERIGO}.get(ok, Tema.TEXTO_FRACO)
        simbolo = {True: self.SIMBOLO_SITUACAO["ok"] + "  ", False: self.SIMBOLO_SITUACAO["erro"] + "  "}.get(ok, "")
        self.lb_estado_cloud.configure(text=simbolo + texto if texto else "", text_color=cor)

    def _ao_escolher_modo_voz(self) -> None:
        """O cartão escolhido (Piper / Cloud / Gemini / Misto) vira o motor e a opção dos figurantes."""
        modo = self.var_jf_modo_voz.get()
        self.var_jf_motor_voz.set({"piper": self.MOTORES_VOZ[0], "cloud": self.MOTORES_VOZ[2]}.get(
            modo, self.MOTORES_VOZ[1]))
        self.var_jf_figurantes_piper.set(modo == "misto")

    def _sincronizar_modo_voz(self) -> None:
        """O contrário: o motor e os figurantes (do config.json, ou mudados por código) marcam o cartão certo."""
        motor = self.var_jf_motor_voz.get()
        gemini = motor.startswith("Gemini")
        modo = (("misto" if self.var_jf_figurantes_piper.get() else "gemini") if gemini
                else "cloud" if motor.startswith("Google Cloud") else "piper")
        if self.var_jf_modo_voz.get() != modo:
            self.var_jf_modo_voz.set(modo)
        for valor, cartao in getattr(self, "_cartoes_modo_voz", {}).items():
            cartao.configure(border_color=Tema.PRIMARIA if valor == modo else Tema.CAMPO_BORDA,
                             border_width=2 if valor == modo else 1)

    # ---- Chaves de API: todas num lugar, cada uma com "Validar" e a situação ao lado
    def _montar_config_chaves(self, lateral) -> None:
        self._rotulo(lateral, "Validar não gasta crédito: só confere se a chave funciona.").pack(anchor="w", padx=18,
                                                                                               pady=(0, 8))
        grade = ctk.CTkFrame(lateral, fg_color="transparent")
        grade.pack(fill="x", padx=18)
        grade.grid_columnconfigure(1, weight=1)
        self.var_jf_chave_claude = tk.StringVar()
        self.var_jf_chave_gemini = tk.StringVar()
        self.var_jf_chave_cloud = tk.StringVar()

        def estado():
            return ctk.CTkLabel(grade, text="", font=self.f_rotulo, text_color=Tema.TEXTO_FRACO, anchor="w",
                                justify="left", wraplength=260, width=260)
        linhas = (("TMDB", "nomes, pôsteres, sinopse · grátis", self.var_jf_chave_tmdb,
                   "themoviedb.org > Configurações > API", self.ao_testar_tmdb, "tmdb"),
                  ("OpenSubtitles", "legendas · grátis", self.var_jf_chave_os, "opensubtitles.com > API consumers",
                   self.ao_testar_legendas, "os"),
                  ("SubDL", "legendas · grátis", self.var_jf_chave_subdl, "subdl.com > Painel > API",
                   self.ao_testar_legendas, "subdl"),
                  ("Anthropic (Claude)", "tradução e falas da dublagem · pago", self.var_jf_chave_claude,
                   "console.anthropic.com > API Keys", self.ao_testar_claude, "claude"),
                  ("Google AI Studio (Gemini)", "voz premium e por personagem · pago", self.var_jf_chave_gemini,
                   "aistudio.google.com > Get API key", self.ao_testar_gemini, "gemini"),
                  ("Google Cloud (Text-to-Speech)", "voz da dublagem · cota grátis por mês", self.var_jf_chave_cloud,
                   "console.cloud.google.com > Credenciais", self.ao_testar_cloud_tts, "cloud"),
                  ("Jellyfin", "scan da biblioteca, TV ao vivo", self.var_jf_chave_jellyfin,
                   "Painel > Avançado > Chaves de API", self.ao_testar_jellyfin, "jellyfin"))
        for n, (nome, descricao, var, dica, comando, chave) in enumerate(linhas):
            nomes = ctk.CTkFrame(grade, fg_color="transparent")
            nomes.grid(row=n, column=0, sticky="w", pady=6)
            rotulo = ctk.CTkLabel(nomes, text=nome, font=self.f_botao, text_color=Tema.TEXTO, anchor="w")
            rotulo.pack(anchor="w")
            ctk.CTkLabel(nomes, text=descricao, font=ctk.CTkFont(Tema.FAMILIA, 11), text_color=Tema.TEXTO_FRACO,
                         anchor="w").pack(anchor="w")
            campo = self._entrada(grade, var, dica, show="•")
            campo.grid(row=n, column=1, sticky="ew", padx=12)
            botao = self._botao(grade, "Validar", comando, largura=110)
            botao.grid(row=n, column=2)
            lb = estado()
            lb.grid(row=n, column=3, sticky="w", padx=(12, 0))
            setattr(self, f"_rotulo_chave_{chave}", rotulo)
            setattr(self, f"_campo_chave_{chave}", campo)
            setattr(self, f"_botao_chave_{chave}", botao)
            setattr(self, f"_estado_chave_{chave}", lb)
        # nomes de sempre (o resto do programa e os testes usam estes)
        self.campo_chave_tmdb, self.bt_testar_tmdb, self.lb_estado_tmdb = (
            self._campo_chave_tmdb, self._botao_chave_tmdb, self._estado_chave_tmdb)
        self.campo_chave_os, self.campo_chave_subdl = self._campo_chave_os, self._campo_chave_subdl
        self.rot_chave_os, self.rot_chave_subdl = self._rotulo_chave_os, self._rotulo_chave_subdl
        self.bt_testar_legendas, self.lb_estado_legendas = self._botao_chave_os, self._estado_chave_os
        self._estado_chave_subdl.configure(text="(validada junto com o OpenSubtitles)")
        self.bt_testar_claude, self.lb_estado_claude = self._botao_chave_claude, self._estado_chave_claude
        self.bt_testar_gemini, self.lb_estado_gemini = self._botao_chave_gemini, self._estado_chave_gemini
        self.bt_testar_cloud, self.lb_estado_cloud = self._botao_chave_cloud, self._estado_chave_cloud
        self.bt_testar_jellyfin = self._botao_chave_jellyfin
        self.bt_criar_chave_gemini = self._botao(lateral, "Criar a chave do Gemini no AI Studio (abre o site)",
                                                 self.ao_criar_chave_gemini, "fantasma")
        self.bt_criar_chave_gemini.pack(anchor="w", padx=18, pady=(6, 0))
        self._separador(lateral)
        self.var_jf_lembrar = tk.BooleanVar(value=False)
        self._checkbox(lateral, "Lembrar as chaves neste computador", self.var_jf_lembrar)
        self._rotulo(lateral, "Sem marcar, chaves e tokens valem só até fechar o programa.",
                     fonte=ctk.CTkFont(Tema.FAMILIA, 11)).pack(anchor="w", pady=(2, 8), padx=18)

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
        # Seletor: ☑ = o Organizar mexe; ☐ = fica onde está. Clique na caixa (coluna #) ou use os botões
        selecao = ctk.CTkFrame(topo, fg_color="transparent")
        selecao.pack(side="bottom", fill="x", pady=(4, 0), before=linha)       # embaixo da linha "Mostrar:"
        self._rotulo(selecao, "Seleção:", fonte=ctk.CTkFont(Tema.FAMILIA, 11, "bold")).pack(side="left", padx=(0, 8))
        # Corrigir nome / Resolver conflitos / Escolher no TMDB / Não identificados: aqui, sempre à vista (antes ficavam
        # no painel Antes -> Depois, que sai sozinho em tela baixa, e os botões sumiam junto)
        self.acoes_selecao_jf = ctk.CTkFrame(selecao, fg_color="transparent")
        self.acoes_selecao_jf.pack(side="right")
        estilo = dict(height=22, corner_radius=6, fg_color="transparent", hover_color=Tema.SECUNDARIA_HOVER,
                      text_color=Tema.PRIMARIA, font=ctk.CTkFont(Tema.FAMILIA, 11))
        self.bt_marcar_jf = ctk.CTkButton(selecao, text="☑ Mover selecionados", width=130,
                                          command=lambda: self.marcar_mover_jf(self.tabela_jf.selection(), True), **estilo)
        self.bt_desmarcar_jf = ctk.CTkButton(selecao, text="☐ Não mover selecionados", width=150,
                                             command=lambda: self.marcar_mover_jf(self.tabela_jf.selection(), False),
                                             **estilo)
        self.bt_proteger_pasta_jf = ctk.CTkButton(selecao, text="Proteger a pasta...", width=110,
                                                  command=self.ao_proteger_pasta_jf, **estilo)
        for b in (self.bt_marcar_jf, self.bt_desmarcar_jf, self.bt_proteger_pasta_jf):
            b.pack(side="left", padx=(0, 4))
        self._rotulo(selecao, "Só o ☑ à vista é organizado", fonte=ctk.CTkFont(Tema.FAMILIA, 11)).pack(
            side="left", padx=(10, 0))

    def marcar_mover_jf(self, iids, mover: bool | None = None) -> int:
        """☑/☐ nas linhas "vai mover" (mover=None: inverte cada uma). Devolve quantas mudaram."""
        mudou = 0
        for iid in iids:
            if self._categoria_jf.get(iid) != "mover" or not self.tabela_jf.exists(iid):
                continue
            fica = (iid not in self._fora_jf) if mover is None else not mover
            if fica == (iid in self._fora_jf):
                continue
            (self._fora_jf.add if fica else self._fora_jf.discard)(iid)
            numero = str(self.tabela_jf.set(iid, "n")).split()[-1]
            self.tabela_jf.set(iid, "n", f"{self.CAIXA[not fica]} {numero}")
            mudou += 1
        return mudou

    def nao_mover_jf(self) -> list[str]:
        """iids das linhas "vai mover" que estão desmarcadas (☐)."""
        return [i for i in self._ordem_jf if i in self._fora_jf]

    def _ao_clicar_tabela_jf(self, evento):
        """Clique na caixa ☑/☐ (coluna #) de uma linha "vai mover": marca/desmarca sem mudar a seleção."""
        if self.tabela_jf.identify_region(evento.x, evento.y) != "cell" or \
                self.tabela_jf.identify_column(evento.x) != "#1":
            return None
        iid = self.tabela_jf.identify_row(evento.y)
        if not iid or self._categoria_jf.get(iid) != "mover" or evento.state & 0x0005:
            return None
        self.marcar_mover_jf([iid])
        return "break"

    def ao_proteger_pasta_jf(self) -> None:
        pass

    def ao_escolher_no_tmdb(self) -> None:
        pass

    def ao_memoria_downloads(self) -> None:
        pass

    def mostrar_todos_jf(self) -> None:
        """Marca todas as caixas do filtro (nada fica escondido)."""
        for var in self.vars_filtro_jf.values():
            var.set(True)
        self._filtros_col_jf.clear()
        self._titulos_jf()
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
        if not (categoria is None or categoria not in self.vars_filtro_jf or self.vars_filtro_jf[categoria].get()):
            return False
        return all(self.valor_jf(coluna, iid) in valores for coluna, valores in self._filtros_col_jf.items())

    # ---- filtro por coluna (como na janela de canais): clique no título da coluna
    def _titulos_jf(self) -> None:
        for chave, texto, *_ in self.COLUNAS_JF:
            if chave == "n":                          # o # é o seletor: clique marca/desmarca todos os visíveis
                self.tabela_jf.heading("n", text=f"{self.CAIXA[True]} #", command=self.alternar_mover_visiveis_jf)
                continue
            marca = " ▼ (filtro)" if chave in self._filtros_col_jf else " ▾"
            self.tabela_jf.heading(chave, text=texto + marca, anchor="w",
                                   command=lambda c=chave: self.abrir_filtro_jf(c))

    def valor_jf(self, coluna: str, iid: str) -> str:
        """O valor da célula como aparece no filtro (sem o símbolo ✓/✕ da situação; vazio = "(vazio)")."""
        valor = str(self.tabela_jf.set(iid, coluna)).strip()
        if coluna == "status":
            valor = re.sub(r"^[\u2713\u2715\u21b7]\s+", "", valor)
        return valor or "(vazio)"

    def valores_jf(self, coluna: str) -> list[tuple[str, int]]:
        contagem: dict[str, int] = {}
        for iid in self._ordem_jf:
            valor = self.valor_jf(coluna, iid)
            contagem[valor] = contagem.get(valor, 0) + 1
        return sorted(contagem.items(), key=lambda vq: _sem_acentos(vq[0]))

    def aplicar_filtro_coluna_jf(self, coluna: str, escolhidos) -> None:
        """Mostra só as linhas com um dos valores nessa coluna. Todos marcados (ou nenhum) = sem filtro nela.
        O Organizar só mexe no que está À VISTA (o escondido pelo filtro fica onde está)."""
        escolhidos = set(escolhidos)
        if not escolhidos or escolhidos >= {v for v, _ in self.valores_jf(coluna)}:
            self._filtros_col_jf.pop(coluna, None)
        else:
            self._filtros_col_jf[coluna] = escolhidos
        self._titulos_jf()
        self.aplicar_filtro_jf()

    def abrir_filtro_jf(self, coluna: str) -> None:
        if self._janela_filtro_jf is not None and self._janela_filtro_jf.winfo_exists():
            self._janela_filtro_jf.destroy()
        titulo = next(t for c, t, *_ in self.COLUNAS_JF if c == coluna)
        self._janela_filtro_jf, self._filtro_aberto_jf = janela_de_filtro(
            self, self, titulo, self.valores_jf(coluna), self._filtros_col_jf.get(coluna),
            lambda escolhidos: self.aplicar_filtro_coluna_jf(coluna, escolhidos), botao="Mostrar")

    def tirar_filtros_coluna_jf(self) -> None:
        self._filtros_col_jf.clear()
        self._titulos_jf()
        self.aplicar_filtro_jf()

    def visiveis_jf(self) -> list[str]:
        return [i for i in self._ordem_jf if self._visivel_jf(i)]

    def alternar_mover_visiveis_jf(self) -> None:
        """Título "☑ #": desmarca todos os "vai mover" à vista; se já estão todos desmarcados, marca."""
        visiveis = [i for i in self.visiveis_jf() if self._categoria_jf.get(i) == "mover"]
        algum_marcado = any(i not in self._fora_jf for i in visiveis)
        self.marcar_mover_jf(visiveis, not algum_marcado)

    def aplicar_filtro_jf(self) -> None:
        """Esconde/mostra as linhas conforme as caixas marcadas, mantendo a ordem original."""
        tabela = self.tabela_jf
        tabela.detach(*self._ordem_jf)
        for iid in self._ordem_jf:
            if self._visivel_jf(iid):
                tabela.move(iid, "", "end")
        self._atualizar_contador(tabela)

    def _montar_detalhe_jf(self, corpo) -> None:
        """Cartão 'Antes -> Depois' com a pasta e o arquivo, como estão e como vão ficar."""
        cartao = self._cartao(corpo)
        cartao.grid(row=1, column=1, sticky="ew", pady=(0, 14))
        cartao.grid_columnconfigure((1, 2), weight=1, uniform="d")
        self.lb_detalhe_titulo = ctk.CTkLabel(cartao, text="Antes → Depois",
                                              font=self.f_secao, text_color=Tema.TEXTO, anchor="w")
        self.lb_detalhe_titulo.grid(row=0, column=0, columnspan=3, sticky="w", padx=18, pady=(10, 4))
        # não identificado? você diz qual é a série/filme e o programa lembra (regra salva)
        acoes = self.acoes_selecao_jf                     # na linha "Seleção:" da lista (sempre à vista)
        self.bt_corrigir_nome = self._botao(acoes, "Corrigir nome...", self.ao_corrigir_nome, "secundario",
                                            largura=130)
        # conflito (cópia repetida ou já na biblioteca): fica a melhor, a outra sai (dá para desfazer)
        self.bt_resolver_conflitos = self._botao(acoes, "Resolver conflitos...", self.ao_resolver_conflitos,
                                                 "secundario", largura=150)
        # nome repetido no TMDB (ex.: 'Tom and Jerry' de 1940, 2014, 2023): você escolhe qual é
        self.bt_escolher_tmdb = self._botao(acoes, "Escolher no TMDB...", self.ao_escolher_no_tmdb, "secundario",
                                            largura=150)
        # os não identificados juntos por pasta: corrige o grupo inteiro de uma vez
        self.bt_nao_identificados = self._botao(acoes, "Não identificados...", self.ao_nao_identificados,
                                                "secundario", largura=150)
        for b in (self.bt_resolver_conflitos, self.bt_corrigir_nome, self.bt_escolher_tmdb, self.bt_nao_identificados):
            b.configure(height=26, font=ctk.CTkFont(Tema.FAMILIA, 12))
            b.pack(side="right", padx=(6, 0))
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

    ALTURA_CONSOLE_JF = 140
    MINIMO_LISTA_JF = 160
    # Altura da aba a partir da qual cabe cada parte (medida: lista + painel + console pedem ~880 px; numa janela
    # de 900 px, a aba tem ~736). Abaixo disso, o que não cabe sai sozinho, em vez de ficar cortado.
    ABA_COM_CONSOLE = 880
    ABA_COM_DETALHE = 700

    def partes_visiveis_jf(self, altura: int | None = None) -> tuple[bool, bool]:
        """(painel Antes → Depois, console) que cabem nesta altura da aba (e com a lista não ampliada)."""
        if altura is None:                 # winfo_height é em pixels; os limites, em pontos (zoom do Windows: 125%...)
            altura = self.aba_jellyfin.winfo_height() / self._pontos()
        if self._lista_ampliada:
            return False, False
        return altura >= self.ABA_COM_DETALHE, altura >= self.ABA_COM_CONSOLE

    def _ajustar_altura_jf(self, _evento=None) -> None:
        """A janela mudou de tamanho: mostra só o que cabe (em notebook, a lista fica com a altura toda)."""
        detalhe, console = self.partes_visiveis_jf()
        for cartao, mostrar in ((self._cartao_detalhe_jf, detalhe), (self._cartao_console_jf, console)):
            if mostrar and not cartao.winfo_manager():
                cartao.grid()
            elif not mostrar and cartao.winfo_manager():
                cartao.grid_remove()
        # a altura mínima da linha do console vai junto: sem isso, o espaço continuava reservado e a lista não crescia
        self._corpo_jf.grid_rowconfigure(2, minsize=round(self.ALTURA_CONSOLE_JF * self._pontos()) if console else 0)

    def _pontos(self) -> float:
        """Pixels por ponto: 1,25 com o zoom do Windows em 125%. O CTk aumenta os botões e as letras, mas a grade
        do Tk (minsize) e o winfo_height continuam em pixels: as contas de altura precisam converter."""
        try:
            return ctk.ScalingTracker.get_widget_scaling(self) or 1.0
        except (AttributeError, tk.TclError):
            return 1.0

    def alternar_lista_jf(self) -> None:
        """'Ampliar lista': esconde o painel Antes → Depois e o console; a tabela ocupa tudo.
        O andamento continua no rodapé (porcentagem e barra). 'Reduzir' volta ao que cabe na tela."""
        self._lista_ampliada = not self._lista_ampliada
        self._ajustar_altura_jf()
        self.bt_ampliar_jf.configure(text="⤡  Reduzir lista" if self._lista_ampliada else "⤢  Ampliar lista")

    def _campo_leitura(self, master, var) -> ctk.CTkEntry:
        """Campo só para ler (dá para selecionar e copiar, mas não editar)."""
        campo = ctk.CTkEntry(master, textvariable=var, height=32, corner_radius=8, border_width=1,
                             fg_color=Tema.CAMPO, border_color=Tema.CAMPO_BORDA, text_color=Tema.TEXTO,
                             font=self.f_rotulo)
        navegacao = ("Left", "Right", "Home", "End")
        campo.bind("<Key>", lambda e: None if e.keysym in navegacao or (e.state & 0x4) else "break")  # 0x4 = Ctrl
        return campo

    def _escolher_pasta_em(self, var: tk.StringVar) -> None:
        pasta = filedialog.askdirectory(initialdir=var.get() or ".")
        if pasta:
            var.set(pasta)

    def _mostrar_campos_jf(self) -> None:
        """Mostra só os campos que fazem sentido para a fonte escolhida (as chaves ficam em Chaves de API)."""
        fonte = self.var_jf_fonte.get()
        self.campo_url_site.pack_forget()
        if fonte == self.FONTES_LEGENDA[2]:                 # site: o endereço da busca
            self.campo_url_site.pack(fill="x", padx=18, pady=(8, 0))
        # com o OpenSubtitles, o SubDL é a RESERVA (usada quando o OpenSubtitles atingir o limite; opcional)
        self.rot_chave_subdl.configure(text="SubDL (reserva)" if fonte == self.FONTES_LEGENDA[1] else "SubDL")

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
            espera=float(self.campo_espera.get()), pasta=self.var_pasta.get().strip() or self._pasta_padrao,
            ignorar_robots=self.var_ignorar_robots.get(), clicar_play=self.var_clicar_play.get(),
            espelhar=self.var_espelhar.get())

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
            pastas_vigiadas=tuple(self.pastas_vigiadas()), pastas_protegidas=tuple(self.pastas_protegidas()),
            vigia_no_lugar=self.var_jf_vigia_no_lugar.get(),
            conferir_auto=self.var_jf_conferir_auto.get(), conferir_a_cada=self.campo_conferir_a_cada.get(),
            conferir_unidade=self.var_jf_conferir_unidade.get(), remover_quebrados=self.var_jf_remover_quebrados.get(),
            ultima_conferencia=self.var_jf_ultima_conferencia.get(),
            avisar_versao=self.var_jf_avisar_versao.get(), versao_avisada=self.var_jf_versao_avisada.get(),
            atualizar_sozinho=self.var_jf_atualizar_sozinho.get(),
            fechar_na_bandeja=self.var_jf_fechar_bandeja.get(),
            chave_claude=self.var_jf_chave_claude.get().strip(),
            modelo_traducao=self.var_jf_modelo_traducao.get().strip() or "claude-sonnet-4-6",
            modelo_whisper=self.var_jf_modelo_whisper.get(), whisper_gpu=self.var_jf_whisper_gpu.get(),
            voz_dublagem=self.var_jf_voz_dublagem.get(), motor_voz=self.var_jf_motor_voz.get(),
            voz_gemini=valor_da_voz(self.var_jf_voz_gemini.get()), chave_gemini=self.var_jf_chave_gemini.get().strip(),
            encurtar_falas=self.var_jf_encurtar_falas.get(),
            voz_por_personagem=self.var_jf_voz_por_personagem.get(),
            figurantes_piper=self.var_jf_figurantes_piper.get(),
            figurantes_cloud=self.var_jf_figurantes_cloud.get(),
            traducao_economica=self.var_jf_traducao_economica.get(),
            usar_roteiro=self.var_jf_usar_roteiro.get(), vozes_sem_tabela=self.var_jf_vozes_sem_tabela.get(),
            limite_figurante=int(self.campo_limite_figurante.get()), perguntar_filmes=self.var_jf_perguntar_filmes.get(),
            robo_so_piper=self.var_jf_robo_so_piper.get(), guardar_gravacoes=self.var_jf_guardar_gravacoes.get(),
            teto_gastos=float(self.campo_teto_gastos.get()), pasta_avulsos=self.var_jf_pasta_avulsos.get().strip(),
            moeda_gastos=self.var_jf_moeda_gastos.get().split()[0],
            motor_traducao=self.var_jf_motor_traducao.get().split()[0],
            tipo_cloud=self.tipo_cloud_escolhido(), voz_cloud=self.var_jf_voz_cloud.get().split()[0],
            chave_cloud_tts=self.var_jf_chave_cloud.get().strip(), cotacao_dolar=float(self.campo_cotacao_dolar.get()),
            iof_cartao=float(self.campo_iof.get()),
            avulsos_dublar=self.var_jf_avulsos_dublar.get(), avulsos_legendar=self.var_jf_avulsos_legendar.get(),
            dublagem_no_original=self.var_jf_dublagem_no_original.get(),
            dublagem_previa=self.var_jf_dublagem_previa.get(), separar_vozes=self.var_jf_separar_vozes.get(),
            ambientar_voz=self.var_jf_ambientar_voz.get(), separar_gpu=self.var_jf_separar_gpu.get(),
            minutos_teste=float(self.campo_minutos_teste.get()),
            resumo_diario=self.var_jf_resumo_diario.get(),
            filtros_ocultos=tuple(c for c, v in self.vars_filtro_jf.items() if not v.get()))

    def idiomas_jf(self) -> str:
        """Idiomas marcados + 'Outros', ex.: 'pt-BR, en, fr' (sem nenhum: 'pt-BR')."""
        from jellyfin_tools.legendas import normalizar_idiomas
        marcados = [codigo for codigo, var in self.vars_idioma_jf.items() if var.get()]
        todos = normalizar_idiomas(marcados + normalizar_idiomas(self.var_jf_outros_idiomas.get()))
        return ", ".join(todos) or "pt-BR"

    def atualizar_idiomas_entendidos(self) -> None:
        """Embaixo do campo "Outros idiomas": 'Entendi: Francês (fr), Coreano (ko)' e o que não deu para entender."""
        from jellyfin_tools.legendas import analisar_idiomas, nome_do_idioma
        idiomas, desconhecidos = analisar_idiomas(self.var_jf_outros_idiomas.get())
        partes = []
        if idiomas:
            partes.append("Entendi: " + ", ".join(f"{nome_do_idioma(c)} ({c})" for c in idiomas))
        if desconhecidos:
            partes.append("⚠ Não reconheci: " + ", ".join(desconhecidos) + " (use o código, ex.: fr, ou \"Mais "
                          "idiomas...\")")
        self.lb_idiomas_entendidos.configure(text="\n".join(partes),
                                             text_color=Tema.AVISO if desconhecidos else Tema.TEXTO_FRACO)

    def abrir_mais_idiomas(self) -> None:
        """Lista dos idiomas conhecidos para MARCAR (com busca). Os marcados vão para "Outros idiomas"."""
        from jellyfin_tools.legendas import IDIOMAS_CONHECIDOS, normalizar_idiomas
        fixos = {codigo for codigo, _ in self.IDIOMAS_JF}
        opcoes = [(codigo, nome) for codigo, nome, _ in IDIOMAS_CONHECIDOS if codigo not in fixos]
        marcados = set(normalizar_idiomas(self.var_jf_outros_idiomas.get()))
        janela = ctk.CTkToplevel(self, fg_color=Tema.CARTAO)
        janela.title("Idiomas das legendas")
        janela.transient(self)
        janela.geometry("380x520")
        ctk.CTkLabel(janela, text="Marque os idiomas (um arquivo de legenda cada)", font=self.f_secao,
                     text_color=Tema.TEXTO, anchor="w").pack(fill="x", padx=16, pady=(14, 6))
        var_busca = tk.StringVar()
        self._entrada(janela, var_busca, "Procurar (ex.: core, russo, ja)", altura=32).pack(fill="x", padx=16)
        quadro = ctk.CTkFrame(janela, fg_color=Tema.CAMPO, corner_radius=8)
        quadro.pack(fill="both", expand=True, padx=16, pady=8)
        lista = tk.Listbox(quadro, activestyle="none", selectmode="browse", exportselection=False, borderwidth=0,
                           highlightthickness=0, bg=Tema.CAMPO, fg=Tema.TEXTO, selectbackground=Tema.CAMPO,
                           selectforeground=Tema.TEXTO, font=(Tema.FAMILIA, 12))
        lista.pack(fill="both", expand=True, padx=8, pady=6)
        visiveis: list[tuple[str, str]] = []

        def mostrar(*_):
            procura = _sem_acentos(var_busca.get().strip())
            visiveis[:] = [(c, n) for c, n in opcoes if procura in _sem_acentos(f"{n} {c}")]
            lista.delete(0, "end")
            for codigo, nome in visiveis:
                lista.insert("end", f"{'☑' if codigo in marcados else '☐'}  {nome} ({codigo})")

        def trocar(indice: int) -> None:
            if 0 <= indice < len(visiveis):
                marcados.symmetric_difference_update({visiveis[indice][0]})
                mostrar()
                lista.see(indice)

        def aplicar():
            # mantém o que foi digitado e não está na lista (ex.: um código raro) + os marcados, na ordem da lista
            digitados = [c for c in normalizar_idiomas(self.var_jf_outros_idiomas.get())
                         if c not in {o for o, _ in opcoes}]
            escolhidos = [c for c, _ in opcoes if c in marcados]
            self.var_jf_outros_idiomas.set(", ".join(digitados + escolhidos))
            janela.destroy()
        var_busca.trace_add("write", mostrar)
        lista.bind("<ButtonRelease-1>", lambda e: trocar(lista.nearest(e.y)))
        lista.bind("<space>", lambda e: trocar(lista.index("active")))
        botoes = ctk.CTkFrame(janela, fg_color="transparent")
        botoes.pack(fill="x", padx=16, pady=(0, 14))
        self._botao(botoes, "Cancelar", janela.destroy, "secundario").pack(side="left")
        self._botao(botoes, "Usar estes idiomas", aplicar, "primario").pack(side="right")
        janela.bind("<Escape>", lambda e: janela.destroy())
        mostrar()
        self._janela_idiomas = janela
        self._idiomas_abertos = (var_busca, marcados, aplicar)        # para os testes

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
                  "chave_subdl": self.var_jf_chave_subdl, "chave_claude": self.var_jf_chave_claude,
                  "modelo_traducao": self.var_jf_modelo_traducao, "modelo_whisper": self.var_jf_modelo_whisper,
                  "voz_dublagem": self.var_jf_voz_dublagem, "motor_voz": self.var_jf_motor_voz,
                  "chave_gemini": self.var_jf_chave_gemini,
                  "jellyfin_url": self.var_jf_url,
                  "jellyfin_api_key": self.var_jf_chave_jellyfin, "discord_webhook": self.var_jf_discord,
                  "telegram_token": self.var_jf_telegram_token, "telegram_chat_id": self.var_jf_telegram_chat,
                  "pasta_avulsos": self.var_jf_pasta_avulsos, "chave_cloud_tts": self.var_jf_chave_cloud}
        marcas = {"tmdb": self.var_jf_tmdb, "incluir_tmdbid": self.var_jf_tmdbid,
                  "exigir_catalogo": self.var_jf_exigir, "legendas": self.var_jf_legendas,
                  "limpar_lixo": self.var_jf_lixo, "imagens_tmdb": self.var_jf_imagens,
                  "apagar_pasta_origem": self.var_jf_apagar_pasta, "nomes_episodios": self.var_jf_nomes_ep,
                  "vigiar": self.var_jf_vigiar, "vigia_no_lugar": self.var_jf_vigia_no_lugar,
                  "conferir_auto": self.var_jf_conferir_auto,
                  "remover_quebrados": self.var_jf_remover_quebrados, "avisar_versao": self.var_jf_avisar_versao,
                  "atualizar_sozinho": self.var_jf_atualizar_sozinho,
                  "fechar_na_bandeja": self.var_jf_fechar_bandeja,
                  "gerar_nfo": self.var_jf_nfo, "atualizar_jellyfin": self.var_jf_atualizar,
                  "sobrescrever": self.var_jf_sobrescrever, "lembrar_chaves": self.var_jf_lembrar,
                  "whisper_gpu": self.var_jf_whisper_gpu, "resumo_diario": self.var_jf_resumo_diario,
                  "encurtar_falas": self.var_jf_encurtar_falas,
                  "voz_por_personagem": self.var_jf_voz_por_personagem,
                  "figurantes_piper": self.var_jf_figurantes_piper,
                  "figurantes_cloud": self.var_jf_figurantes_cloud,
                  "traducao_economica": self.var_jf_traducao_economica,
                  "usar_roteiro": self.var_jf_usar_roteiro, "vozes_sem_tabela": self.var_jf_vozes_sem_tabela,
                  "perguntar_filmes": self.var_jf_perguntar_filmes, "robo_so_piper": self.var_jf_robo_so_piper,
                  "guardar_gravacoes": self.var_jf_guardar_gravacoes,
                  "avulsos_dublar": self.var_jf_avulsos_dublar,
                  "avulsos_legendar": self.var_jf_avulsos_legendar,
                  "dublagem_no_original": self.var_jf_dublagem_no_original,
                  "dublagem_previa": self.var_jf_dublagem_previa, "separar_vozes": self.var_jf_separar_vozes,
                  "ambientar_voz": self.var_jf_ambientar_voz, "separar_gpu": self.var_jf_separar_gpu}
        for chave, var in textos.items():
            if dados.get(chave):
                var.set(dados[chave])
        for chave, var in marcas.items():
            if chave in dados:
                var.set(bool(dados[chave]))
        self._ao_trocar_dublagem_no_original()
        self._ao_trocar_separar_vozes()
        if dados.get("idioma"):
            self.definir_idiomas_jf(dados["idioma"])
        if dados.get("voz_gemini"):                      # salvo só o nome ("Kore", "clone:Izael"); o menu mostra
            self.var_jf_voz_gemini.set(next((v for v in self.vozes_gemini_do_menu()  # com a descrição
                                             if valor_da_voz(v) == dados["voz_gemini"]), self.VOZES_GEMINI[0]))
        if dados.get("minutos_teste"):
            self.campo_minutos_teste.set(float(dados["minutos_teste"]))
            self.atualizar_botao_testar()
        if dados.get("limite_figurante"):
            self.campo_limite_figurante.set(int(dados["limite_figurante"]))
        if dados.get("teto_gastos"):
            self.campo_teto_gastos.set(float(dados["teto_gastos"]))
        if dados.get("tipo_cloud") in voz_cloud.TIPOS:
            self.var_jf_tipo_cloud.set(self.texto_tipo_cloud(dados["tipo_cloud"]))
            self._ao_trocar_tipo_cloud()
        if dados.get("voz_cloud"):
            self.var_jf_voz_cloud.set(voz_cloud.texto_da_voz(dados["voz_cloud"]))
        if dados.get("motor_traducao"):
            self.var_jf_motor_traducao.set(next((m for m in self.MOTORES_TRADUCAO
                                                 if m.split()[0] == dados["motor_traducao"]), self.MOTORES_TRADUCAO[0]))
        if dados.get("moeda_gastos"):
            self.var_jf_moeda_gastos.set(next((m for m in self.MOEDAS_GASTOS if m.split()[0] == dados["moeda_gastos"]),
                                              self.MOEDAS_GASTOS[0]))
        if dados.get("cotacao_dolar") is not None:
            self.campo_cotacao_dolar.set(float(dados["cotacao_dolar"]))
        if dados.get("iof_cartao") is not None:
            self.campo_iof.set(float(dados["iof_cartao"]))
        if dados.get("vigiar_min"):
            self.campo_vigia_min.set(float(dados["vigiar_min"]))
        if dados.get("pastas_vigiadas"):
            self.definir_pastas_vigiadas(list(dados["pastas_vigiadas"]))
        if dados.get("pastas_protegidas"):
            self.definir_pastas_protegidas(list(dados["pastas_protegidas"]))
        if dados.get("conferir_a_cada"):
            self.campo_conferir_a_cada.set(float(dados["conferir_a_cada"]))
        if dados.get("conferir_unidade") in ("minutos", "horas", "dias"):
            self.var_jf_conferir_unidade.set(dados["conferir_unidade"])
        if dados.get("ultima_conferencia"):
            self.var_jf_ultima_conferencia.set(dados["ultima_conferencia"])
        if dados.get("versao_avisada"):
            self.var_jf_versao_avisada.set(dados["versao_avisada"])
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
        self._fora_jf.clear()
        if self._filtros_col_jf:                      # lista nova: os valores do filtro antigo não valem mais
            self._filtros_col_jf.clear()
            self._titulos_jf()
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
        if categoria == "mover":                       # seletor: ☑ vai mover / ☐ fica onde está
            numero = f"{self.CAIXA[iid not in self._fora_jf]} {numero}"
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
        return dividir_pastas(self.txt_pastas_vigiadas.get("1.0", "end"))

    def problemas_nas_vigiadas(self, pastas: list[str]) -> list[str]:
        """Avisos sobre as pastas vigiadas: as que não existem (são ignoradas pela vigia)."""
        from pathlib import Path
        return [f"Não existe: {pasta}" for pasta in pastas if not Path(pasta).is_dir()]

    def atualizar_aviso_vigiadas(self, arrumar: bool = False) -> None:
        """Mostra embaixo do campo o que está errado. arrumar=True (ao sair do campo): reescreve uma por linha."""
        pastas = self.pastas_vigiadas()
        if arrumar and "\n".join(pastas) != self.txt_pastas_vigiadas.get("1.0", "end").strip():
            self.definir_pastas_vigiadas(pastas)
        problemas = self.problemas_nas_vigiadas(pastas)
        self.lb_aviso_vigiadas.configure(text="\n".join(f"⚠ {p}" for p in problemas))
        if problemas:
            self.lb_aviso_vigiadas.pack(anchor="w", padx=18, pady=(2, 0), after=self.txt_pastas_vigiadas)
        else:
            self.lb_aviso_vigiadas.pack_forget()

    def definir_pastas_vigiadas(self, pastas) -> None:
        if isinstance(pastas, str):
            pastas = dividir_pastas(pastas)
        self.txt_pastas_vigiadas.delete("1.0", "end")
        self.txt_pastas_vigiadas.insert("1.0", "\n".join(p for p in pastas if p.strip()))
        self.atualizar_aviso_vigiadas()

    def pastas_protegidas(self) -> list[str]:
        return dividir_pastas(self.txt_pastas_protegidas.get("1.0", "end"))

    def definir_pastas_protegidas(self, pastas) -> None:
        if isinstance(pastas, str):
            pastas = dividir_pastas(pastas)
        self.txt_pastas_protegidas.delete("1.0", "end")
        self.txt_pastas_protegidas.insert("1.0", "\n".join(p for p in pastas if p.strip()))

    def _adicionar_pasta_protegida(self) -> None:
        pasta = filedialog.askdirectory()
        if pasta and pasta not in self.pastas_protegidas():
            self.definir_pastas_protegidas(self.pastas_protegidas() + [pasta])

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

    def definir_estado_claude(self, ok: bool | None, texto: str) -> None:
        """Linha abaixo de 'Testar chave da Anthropic': verde (ativa), vermelha (recusada) ou neutra."""
        cor = {True: Tema.SUCESSO, False: Tema.PERIGO}.get(ok, Tema.TEXTO_FRACO)
        simbolo = {True: self.SIMBOLO_SITUACAO["ok"] + "  ", False: self.SIMBOLO_SITUACAO["erro"] + "  "}.get(ok, "")
        self.lb_estado_claude.configure(text=simbolo + texto if texto else "", text_color=cor)

    def definir_estado_gemini(self, ok: bool | None, texto: str) -> None:
        """Linha abaixo de 'Validar chave do Gemini': verde (ativa), vermelha (recusada) ou neutra."""
        cor = {True: Tema.SUCESSO, False: Tema.PERIGO}.get(ok, Tema.TEXTO_FRACO)
        simbolo = {True: self.SIMBOLO_SITUACAO["ok"] + "  ", False: self.SIMBOLO_SITUACAO["erro"] + "  "}.get(ok, "")
        self.lb_estado_gemini.configure(text=simbolo + texto if texto else "", text_color=cor)

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
        # uma casa decimal: em tarefas longas (dublar um filme) o número mostra que está andando
        pct = fracao * 100
        numero = f"{pct:.0f}" if pct in (0, 100) else f"{pct:.1f}".replace(".", ",")
        self.var_status.set(f"{self._status_base} {numero}%" + (f"  ·  {texto}" if texto else ""))

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
        self.tabela.delete(*(self._ordem_videos or self.tabela.get_children()))   # as escondidas também
        self._ordem_videos.clear()
        self._ocultos_videos.clear()
        if self._filtros_videos:                       # lista nova: os valores do filtro antigo não valem mais
            self._filtros_videos.clear()
            self._titulos_videos()
        self._atualizar_contador(self.tabela)
        self._atualizar_selecao()

    def adicionar_video(self, iid: str, numero: int, situacao: str, titulo: str, origem: str, link: str,
                        conteudo: str = "", licenca: str = "") -> None:
        """conteudo: 'Filme', 'Série' ou '—'; licenca: a informada pelo site (archive.org)."""
        listra = "par" if len(self.tabela.get_children()) % 2 == 0 else "impar"
        self.tabela.insert("", "end", iid=iid, values=(f"{self.CAIXA[False]} {numero}", situacao, titulo, origem,
                                                       link, conteudo, licenca), tags=(listra,))
        self._ordem_videos.append(iid)
        if self._filtros_videos and not self._visivel_video(iid):
            self.tabela.detach(iid)
            self._ocultos_videos.add(iid)
        self._atualizar_contador(self.tabela)

    def atualizar_situacao(self, iid: str, texto: str, tipo: str, rolar: bool = True) -> None:
        """tipo: 'ok' (verde), 'erro' (vermelho), 'pulado' (amarelo) ou '' (volta ao normal)."""
        if not self.tabela.exists(iid):
            return
        valores = list(self.tabela.item(iid, "values"))
        simbolo = self.SIMBOLO_SITUACAO.get(tipo, "")
        valores[1] = f"{simbolo}  {texto}" if simbolo else texto
        listra = "par" if int(iid) % 2 == 0 else "impar" if iid.isdigit() else "par"
        self.tabela.item(iid, values=valores, tags=(tipo or listra,))
        if rolar and iid not in self._ocultos_videos:         # escondida pelo filtro: não dá para rolar até ela
            self.tabela.see(iid)

    DICA_SELECAO = ""                  # sem nada selecionado: a caixa ☐ da coluna # já explica (falta espaço)

    # ---- filtro por coluna na lista de vídeos (como na TV ao vivo): clique no título da coluna
    TITULOS_VIDEOS = {"status": "Situação", "titulo": "Título", "conteudo": "Tipo", "licenca": "Licença",
                      "tipo": "Origem", "url": "Link"}

    def _titulos_videos(self) -> None:
        for coluna, texto in self.TITULOS_VIDEOS.items():
            marca = " ▼" if coluna in self._filtros_videos else " ▾"     # colunas estreitas: só a seta cheia
            self.tabela.heading(coluna, text=texto + marca, anchor="w",
                                command=lambda c=coluna: self.abrir_filtro_videos(c))

    def valor_video(self, coluna: str, iid: str) -> str:
        valor = str(self.tabela.set(iid, coluna)).strip()
        if coluna == "status":                          # sem o símbolo; "já baixado (05/10/2026)" = "já baixado"
            valor = re.sub(r"^[\u2713\u2715\u21b7]\s+", "", valor)
            valor = re.sub(r"\s*\(\d{2}/\d{2}/\d{4}\)$", "", valor)
            return valor or "(não baixado)"
        return valor if valor and valor != "—" else "(vazio)"

    def valores_videos(self, coluna: str) -> list[tuple[str, int]]:
        contagem: dict[str, int] = {}
        for iid in self._ordem_videos:
            valor = self.valor_video(coluna, iid)
            contagem[valor] = contagem.get(valor, 0) + 1
        return sorted(contagem.items(), key=lambda vq: _sem_acentos(vq[0]))

    def _visivel_video(self, iid: str) -> bool:
        return all(self.valor_video(c, iid) in valores for c, valores in self._filtros_videos.items())

    def aplicar_filtro_videos(self, coluna: str | None = None, escolhidos=None) -> None:
        """Mostra só os vídeos com um dos valores escolhidos (todos ou nenhum = sem filtro nessa coluna).
        O escondido pelo filtro não é baixado nem pelo "Baixar todos"."""
        if coluna is not None:
            escolhidos = set(escolhidos or ())
            if not escolhidos or escolhidos >= {v for v, _ in self.valores_videos(coluna)}:
                self._filtros_videos.pop(coluna, None)
            else:
                self._filtros_videos[coluna] = escolhidos
        self.tabela.detach(*self._ordem_videos)
        self._ocultos_videos = set()
        for iid in self._ordem_videos:
            if self._visivel_video(iid):
                self.tabela.move(iid, "", "end")
            else:
                self._ocultos_videos.add(iid)
        if self._ocultos_videos:                        # escondido não fica selecionado (nem é baixado)
            self.tabela.selection_remove(*[i for i in self.tabela.selection() if i in self._ocultos_videos])
        self._titulos_videos()
        self._atualizar_contador(self.tabela)
        self._atualizar_selecao()

    def abrir_filtro_videos(self, coluna: str) -> None:
        if self._janela_filtro_videos is not None and self._janela_filtro_videos.winfo_exists():
            self._janela_filtro_videos.destroy()
        self._janela_filtro_videos, self._filtro_aberto_videos = janela_de_filtro(
            self, self, self.TITULOS_VIDEOS[coluna], self.valores_videos(coluna), self._filtros_videos.get(coluna),
            lambda escolhidos: self.aplicar_filtro_videos(coluna, escolhidos), botao="Mostrar")

    def tirar_filtros_videos(self) -> None:
        self._filtros_videos.clear()
        self.aplicar_filtro_videos()

    def visiveis_videos(self) -> list[str]:
        return [i for i in self._ordem_videos if i not in self._ocultos_videos]

    def selecionar_todos(self) -> None:
        self.tabela.selection_set(self.tabela.get_children())

    def alternar_todos(self) -> None:
        """Clique no título "☐ #": marca todos; se já estão todos marcados, desmarca."""
        linhas = self.tabela.get_children()
        if linhas and len(self.tabela.selection()) == len(linhas):
            self.limpar_selecao()
        else:
            self.selecionar_todos()

    def _ao_clicar_tabela(self, evento):
        """Um clique marca/desmarca a linha SEM perder as outras (como uma caixa de seleção). Ctrl e Shift
        continuam como antes (Shift+clique = intervalo)."""
        if evento.state & 0x0005:                         # Shift (0x1) ou Ctrl (0x4): comportamento normal
            return None
        if self.tabela.identify_region(evento.x, evento.y) not in ("cell", "tree"):
            return None                                   # título da coluna, borda: deixa o Treeview cuidar
        iid = self.tabela.identify_row(evento.y)
        if not iid:
            return None
        if iid in self.tabela.selection():
            self.tabela.selection_remove(iid)
        else:
            self.tabela.selection_add(iid)
        self.tabela.focus(iid)
        self.tabela.focus_set()
        return "break"

    def marcar_por_texto(self, texto: str | None = None) -> int:
        """Marca (somando ao que já está) pelos números da coluna # ("1-5, 8") ou por parte do título
        ("1x0", "episódio 2"). Devolve quantas linhas foram marcadas."""
        texto = (self.campo_selecionar.get() if texto is None else texto).strip()
        if not texto:
            return 0
        linhas = self.tabela.get_children()
        numeros = numeros_do_texto(texto)
        if numeros is not None:
            escolhidas = [i for i in linhas if self._numero_da_linha(i) in numeros]
        else:
            procura = texto.casefold()
            escolhidas = [i for i in linhas if procura in str(self.tabela.set(i, "titulo")).casefold()]
        if escolhidas:
            self.tabela.selection_add(escolhidas)
            self.tabela.see(escolhidas[0])
            if self.campo_selecionar.get():
                self.campo_selecionar.delete(0, "end")
                self.focus_set()                          # devolve o texto cinza de exemplo
        else:
            self.lb_selecao.configure(text=f"Nada com \"{texto}\"", text_color=Tema.AVISO)
        return len(escolhidas)

    def _numero_da_linha(self, iid: str) -> int:
        try:
            return int(str(self.tabela.set(iid, "n")).split()[-1])
        except (ValueError, IndexError):
            return -1

    def selecionar_filmes_e_series(self) -> None:
        """Só o que dá para espelhar no Jellyfin (Tipo = Filme ou Série; o "—" fica de fora)."""
        self.tabela.selection_set([i for i in self.tabela.get_children()
                                   if self.tabela.set(i, "conteudo") in ("Filme", "Série")])

    def limpar_selecao(self) -> None:
        self.tabela.selection_remove(self.tabela.selection())

    def _atualizar_selecao(self) -> None:
        selecao = set(self.tabela.selection())
        anteriores = getattr(self, "_marcados", set())
        for iid in selecao ^ anteriores:                  # troca ☐/☑ só nas linhas que mudaram (listas grandes)
            if self.tabela.exists(iid):
                self.tabela.set(iid, "n", f"{self.CAIXA[iid in selecao]} {self._numero_da_linha(iid)}")
        self._marcados = selecao
        quantos, total = len(selecao), len(self.tabela.get_children())
        self.tabela.heading("n", text=f"{self.CAIXA[bool(total) and quantos == total]} #")
        self.lb_selecao.configure(
            text=f"{quantos} de {total} selecionado(s)" if quantos else self.DICA_SELECAO,
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
                  self.bt_conferir_espelhos, self.bt_relatorio, self.bt_gerenciar_espelhos, self.bt_traduzir_legendas,
                  self.bt_legendar_audio, self.bt_dublar, self.bt_sincronizar, self.bt_testar_claude,
                  self.bt_av_olhar, self.bt_av_adicionar, self.bt_av_processar, self.bt_av_limpar, self.bt_av_testar,
                  self.bt_av_roteiro, self.bt_testar_jf, self.bt_roteiro_jf):
            b.configure(state=estado)
        self.bt_organizar.configure(state="normal" if self._organizar_liberado and not ocupado else "disabled")
        for parar in (self.bt_parar, self.bt_parar_jf, self.bt_parar_av):
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

    def pedir_nome(self, tipo: str, sugestao: str, onde: str, regra_atual: str = "") -> dict | None:
        """Janela do "Corrigir nome": {'titulo', 'ano', 'temporada'}, {'esquecer': True} ou None."""
        janela = JanelaCorrigirNome(self, tipo, sugestao, onde, regra_atual)
        self.wait_window(janela)
        return janela.resposta

    def escolher_da_lista(self, titulo: str, mensagem: str, itens: list[str], botao: str = "Usar esta",
                          marcado: int | None = None, procurar=None, termo: str = "") -> int | None:
        """Lista para escolher um item; devolve o índice (None = Cancelar). procurar: campo para buscar outro
        nome (a lista é trocada pelo resultado; o índice devolvido é na lista nova)."""
        dialogo = DialogoLista(self, titulo, mensagem, itens, botao, marcado, procurar, termo)
        self.wait_window(dialogo)
        return dialogo.resposta

    def pedir_marcados(self, titulo: str, mensagem: str, itens: list[str], marcados: set[int],
                       botao: str = "Continuar") -> list[int] | None:
        """Caixas de marcar (ver DialogoMarcar): os índices marcados, ou None (Cancelar)."""
        dialogo = DialogoMarcar(self, titulo, mensagem, itens, marcados, botao)
        self.wait_window(dialogo)
        return dialogo.resultado

    def pedir_vozes(self, filme: str, linhas: list[str], rotulos: list[str], sugestao: dict) -> dict | None:
        """Janela "Vozes dos personagens" (ver DialogoVozes)."""
        vozes = self.vozes_gemini_do_menu() + tuple(f"Piper {v} (grátis, no PC)" for v in self.VOZES_DUBLAGEM)
        if self.var_jf_figurantes_cloud.get():               # figurantes no Google Cloud (cota grátis)
            vozes += tuple(f"Google Cloud {v} (cota grátis)" for v in voz_cloud.vozes_do_tipo(self.tipo_cloud_escolhido()))
        dialogo = DialogoVozes(self, filme, linhas, rotulos, sugestao, vozes)
        self.wait_window(dialogo)
        return dialogo.resultado

    def pedir_agendamento(self, comandos: dict, existentes: dict, frequencias: tuple) -> dict | None:
        """Janela "Agendar tarefas" (caixas de marcar + botões); ver DialogoAgendar."""
        dialogo = DialogoAgendar(self, comandos, existentes, frequencias)
        self.wait_window(dialogo)
        return dialogo.resultado

    def escolher(self, titulo: str, mensagem: str, opcoes: tuple[str, ...], cancelar: str = "Cancelar") -> str | None:
        """Pergunta com vários botões; devolve o texto do escolhido (None = Cancelar)."""
        dialogo = DialogoModerno(self, titulo, mensagem, "info", opcoes=opcoes, cancelar=cancelar)
        self.wait_window(dialogo)
        return dialogo.resposta

    def _atualizar_contador(self, tabela) -> None:
        contador, vazio = self._extras_tabela[str(tabela)]
        visiveis = len(tabela.get_children())
        total = (len(self._ordem_jf) if str(tabela) == str(getattr(self, "tabela_jf", ""))
                 else len(getattr(self, "_ordem_videos", ())) or visiveis if str(tabela) == str(getattr(self, "tabela", ""))
                 else visiveis)
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

    def _ajustar_botoes_baixar(self) -> None:
        """Modo híbrido: com "Espelhar em vez de baixar", os botões dizem o que vão fazer."""
        verbo = "Espelhar" if self.var_espelhar.get() else "Baixar"
        self.bt_baixar_sel.configure(text=f"{verbo} selecionados")
        self.bt_baixar_todos.configure(text=f"{verbo} todos")

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

    def ao_traduzir_legendas(self) -> None:
        pass

    def ao_legendar_audio(self) -> None:
        pass

    def ao_testar_claude(self) -> None:
        pass

    def ao_testar_gemini(self) -> None:
        pass

    def ao_criar_chave_gemini(self) -> None:
        pass

    def ao_simular_vigia(self) -> None:
        pass

    def ao_exportar_config(self) -> None:
        pass

    def ao_agendar(self) -> None:
        pass

    def ao_importar_config(self) -> None:
        pass

    def ao_dublar(self) -> None:
        pass

    def ao_sincronizar_legendas(self) -> None:
        pass

    def ao_conferir_espelhos(self) -> None:
        pass

    def ao_alternar_vigia(self) -> None:
        pass

    def ao_atualizar_jellyfin_agora(self) -> None:
        pass

    def ao_nao_identificados(self) -> None:
        pass

    def ao_abrir_pasta_programa(self) -> None:
        pass

    def ao_instalar_fixo(self) -> None:
        pass

    def ao_gerenciar_espelhos(self) -> None:
        pass

    def ao_abrir_relatorio(self) -> None:
        pass

    def ao_corrigir_nome(self) -> None:
        pass

    def ao_resolver_conflitos(self) -> None:
        pass

    def ao_alternar_inicializacao(self) -> None:
        pass

    def ao_tv_ao_vivo(self) -> None:
        pass

    def ao_verificar_atualizacoes(self) -> None:
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
