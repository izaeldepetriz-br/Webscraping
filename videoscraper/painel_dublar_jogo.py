"""Aba "🎮 Jogos", modo "Traduzir e dublar (no PC)" (como no protótipo aprovado): traduzir os textos e dublar as
vozes de um jogo do SEU disco e entregar para pôr de volta numa cópia da ISO. Só a tela fica aqui; o trabalho fica em
jellyfin_tools (iso_jogo, roteiro_jogo, dublar_jogo) e a ligação com a janela em dublar_jogos_moderna.py.

    1. Roteiro do jogo   a pasta com os textos e as vozes já tirados do jogo (pela ferramenta da comunidade, ou pelo
                         próprio Maestro: "Analisar a ISO" e "Tirar as falas da ISO"); o jogo, os textos, o limite de
                         tamanho, as vozes e o volume medido
    2. Tradução          original x português com a coluna Espaço (a sugestão mais curta do Claude embaixo), o
                         glossário, quem traduz e o custo estimado
    3. Dublagem no PC    o motor, a emoção, uma voz por personagem (com a emoção e a duração de cada um), as opções
                         de formato e duração e o tempo estimado
    4. Entregar          roteiro_ptbr + audio_ptbr (+ montar a ISO, quando as falas saíram dela pelo Maestro) e o
                         patch .xdelta para compartilhar

Em cada console do submenu "Jogos →" o modo é o mesmo, com o guia de como tirar os textos e as vozes dele, o
campo da ISO só onde o Maestro abre o disco sozinho (PS2, PS1, PSP) e o que a tradução vira no fim: o patch .xdelta
(discos), o .bps (ROMs), o mod .zip (Switch) ou o pacote .zip (PC).

Em cima, o "⏱ Tempo deste jogo" (cada etapa, o total e a que horas termina, pela velocidade deste PC) e o botão
"🤖 Automático", que faz as etapas marcadas uma depois da outra.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import customtkinter as ctk

from jellyfin_tools import consoles as cs
from jellyfin_tools import dublar_jogo as dj

from .gui_moderna import Tema

QUEM_TRADUZ = ("Claude (pago, melhor)", "Gemini Flash (chave grátis)", "Grátis no PC (Argos)")
MOTORES = ("XTTS-v2 (grátis, no PC)", "Gemini (pago, expressivo)", "Google Cloud (cota grátis)",
           "Piper (grátis, robótico)")
EMOCOES = ("Gravação da emoção ou Chatterbox", "Sem emoção")
LINHAS_NA_TABELA = 600                    # a tabela mostra as primeiras (o resto vai igual para a entrega)
CRIAR = {"xdelta": "📦  Criar o patch (.xdelta)", "bps": "📦  Criar o patch (.bps)", "mod": "📦  Criar o mod (.zip)",
         "pacote": "📦  Criar o pacote (.zip)"}


class PainelDublarJogo(ctk.CTkScrollableFrame):
    """A tela do modo. acoes: {'escolher_pasta', 'ler', 'escolher_roteiro', 'escolher_iso', 'analisar',
    'relatorio', 'extrair', 'traduzir', 'traduzir_teste', 'editar', 'custos', 'trocar_voz', 'dublar',
    'dublar_teste', 'ouvir', 'editar_fala', 'escolher_saida', 'entregar', 'abrir_saida', 'montar',
    'criar_patch', 'automatico'}."""

    def __init__(self, pai, app, acoes: dict, console: cs.Console | None = None):
        super().__init__(pai, fg_color="transparent")
        self.app = app
        self.acoes = acoes
        self.console = console or cs.console("PS2")     # o submenu "Jogos → ..." (o PS2 fica como sempre foi)
        self.ps2 = self.console.chave == "PS2"
        self.com_original = self.console.criar in ("xdelta", "bps")    # o patch precisa da ISO/ROM original
        self.analise = None                  # iso_jogo.Analise
        self.roteiro = None                  # roteiro_jogo.Roteiro
        self.falas: list = []                # dublar_jogo.FalaJogo
        self.tem_mapa = False                # as falas saíram da ISO pelo Maestro (dá para montar a ISO de volta)
        self.iso_montada = None
        self._pequeno = ctk.CTkFont(Tema.FAMILIA, 11)
        self.grid_columnconfigure(0, weight=1)
        self._montar_tempo()
        self._montar_roteiro()
        self._montar_traducao()
        self._montar_dublagem()
        self._montar_entrega()
        self.atualizar()

    # ------------------------------------------------------------------ montagem
    def _cartao(self, linha: int, titulo: str, dica: str) -> ctk.CTkFrame:
        m = self.app
        cartao = m._cartao(self)
        cartao.grid(row=linha + 1, column=0, sticky="ew", padx=(28, 16), pady=(12, 0))   # (a linha 0: o tempo)
        cartao.grid_columnconfigure(1, weight=1)
        topo = ctk.CTkFrame(cartao, fg_color="transparent")
        topo.grid(row=0, column=0, columnspan=3, sticky="ew", padx=20, pady=(12, 6))
        m._rotulo(topo, titulo, suave=False, fonte=m.f_secao).pack(side="left")
        m._rotulo(topo, "   " + dica, fonte=self._pequeno).pack(side="left", pady=(3, 0))
        return cartao

    def _linha_campo(self, cartao, linha: int, rotulo: str, dica: str, acao: str | None):
        m = self.app
        m._rotulo(cartao, rotulo, suave=False).grid(row=linha, column=0, padx=(20, 10), pady=4, sticky="w")
        var = tk.StringVar(self)
        m._entrada(cartao, var, dica).grid(row=linha, column=1, sticky="ew", pady=4)
        botao = None
        if acao:
            botao = m._botao(cartao, "Escolher...", self.acoes[acao], largura=130)
            botao.grid(row=linha, column=2, padx=(10, 20), pady=4)
        return var, botao

    def _quadro_info(self, cartao, linha: int, campos: list[tuple[str, str]]) -> dict[str, ctk.CTkLabel]:
        quadro = ctk.CTkFrame(cartao, fg_color=Tema.CAMPO, corner_radius=Tema.RAIO_CONTROLE)
        quadro.grid(row=linha, column=0, columnspan=3, sticky="ew", padx=20, pady=(6, 4))
        quadro.grid_columnconfigure(1, weight=1)
        valores = {}
        for i, (chave, rotulo) in enumerate(campos):
            ctk.CTkLabel(quadro, text=rotulo, font=self._pequeno, text_color=Tema.TEXTO_SUAVE, anchor="w",
                         width=150).grid(row=i, column=0, sticky="w", padx=(14, 6), pady=3)
            valores[chave] = ctk.CTkLabel(quadro, text="—", font=self.app.f_rotulo, text_color=Tema.TEXTO,
                                          anchor="w", justify="left", wraplength=900)
            valores[chave].grid(row=i, column=1, sticky="w", padx=(0, 14), pady=3)
        return valores

    def _faixa(self, cartao, linha: int, pady=(6, 4)) -> ctk.CTkFrame:
        faixa = ctk.CTkFrame(cartao, fg_color="transparent")
        faixa.grid(row=linha, column=0, columnspan=3, sticky="ew", padx=20, pady=pady)
        return faixa

    def _caixa(self, pai, texto: str, var: tk.BooleanVar) -> ctk.CTkCheckBox:
        m = self.app
        return ctk.CTkCheckBox(pai, text=texto, variable=var, font=m.f_normal, text_color=Tema.TEXTO,
                               fg_color=Tema.PRIMARIA, hover_color=Tema.PRIMARIA_HOVER, border_color=Tema.CAMPO_BORDA,
                               checkbox_width=20, checkbox_height=20, corner_radius=6, border_width=2)

    def _tabela(self, cartao, linha: int, colunas: list[tuple[str, str, int, bool]], altura: int) -> ttk.Treeview:
        quadro = ctk.CTkFrame(cartao, fg_color=Tema.CARTAO, corner_radius=0)
        quadro.grid(row=linha, column=0, columnspan=3, sticky="ew", padx=20, pady=(6, 4))
        quadro.grid_columnconfigure(0, weight=1)
        tabela = ttk.Treeview(quadro, columns=[c[0] for c in colunas], show="headings", height=altura,
                              selectmode="browse", style="Moderno.Treeview")
        for chave, texto, largura, estica in colunas:
            tabela.heading(chave, text=texto, anchor="w")
            tabela.column(chave, width=largura, minwidth=40, stretch=estica, anchor="w")
        tabela.grid(row=0, column=0, sticky="ew")
        tabela.tag_configure("cabe", background="#14301f")
        tabela.tag_configure("conferir", background="#3a2a12")
        tabela.tag_configure("par", background=Tema.LINHA_PAR)
        tabela.tag_configure("impar", background=Tema.LINHA_IMPAR)
        rolagem = ctk.CTkScrollbar(quadro, command=tabela.yview, button_color=Tema.CARTAO_BORDA,
                                   button_hover_color=Tema.CAMPO_BORDA)
        rolagem.grid(row=0, column=1, sticky="ns", padx=(4, 0))
        tabela.configure(yscrollcommand=rolagem.set)
        return tabela

    def _montar_tempo(self) -> None:
        m = self.app
        faixa = m._cartao(self)
        faixa.grid(row=0, column=0, sticky="ew", padx=(28, 16), pady=(12, 0))
        faixa.grid_columnconfigure(1, weight=1)
        m._rotulo(faixa, "⏱ Tempo deste jogo", suave=False, fonte=m.f_secao).grid(row=0, column=0, padx=(20, 12),
                                                                                  pady=12, sticky="w")
        self.lb_tempo_jogo = m._rotulo(faixa, self.sem_nada(), fonte=self._pequeno)
        self.lb_tempo_jogo.grid(row=0, column=1, sticky="w", pady=12)
        self.bt_automatico = m._botao(faixa, "🤖  Automático", self.acoes["automatico"], "primario")
        self.bt_automatico.grid(row=0, column=2, padx=(12, 20), pady=12)

    def sem_nada(self) -> str:
        """O "⏱ Tempo deste jogo" antes de abrir o jogo (só PS2, PS1 e PSP têm "tirar as falas da ISO")."""
        return "abra o roteiro ou tire as falas da ISO para ver quanto tempo leva" if self.console.iso9660 else \
            "abra a pasta com o roteiro e as vozes para ver quanto tempo leva"

    def mostrar_tempo_jogo(self, texto: str, ok: bool = True) -> None:
        self.lb_tempo_jogo.configure(text=texto, text_color=Tema.TEXTO_SUAVE if ok else Tema.AVISO)

    def _montar_roteiro(self) -> None:
        m = self.app
        c = self.console
        cartao = self._cartao(0, "1. Roteiro do jogo", "os textos e as vozes já tirados de dentro do jogo (pelo "
                              "Maestro, nos formatos que ele conhece, ou por uma ferramenta da comunidade)")
        self.var_pasta, self.bt_escolher_pasta = self._linha_campo(
            cartao, 1, "Pasta:", "a pasta com o roteiro e as falas (ex.: D:\\Jogos\\PS2\\Meu Jogo - extraído)"
            if self.ps2 else "a pasta do jogo (ou a que tem os textos e as vozes tirados dele)" if c.chave == "PC" else
            f"a pasta com o roteiro e as falas (ex.: D:\\Jogos\\{c.chave}\\Meu Jogo - extraído)", "escolher_pasta")
        self.info = self._quadro_info(cartao, 2, [("jogo", "Jogo"), ("textos", "Textos"),
                                                  ("limite", "Limite de tamanho"), ("vozes", "Vozes"),
                                                  ("volume", "Volume medido")])
        faixa = self._faixa(cartao, 3)
        self.bt_ler = m._botao(faixa, "📂  Ler a pasta", self.acoes["ler"], "primario")
        self.bt_ler.pack(side="left")
        self.bt_escolher_roteiro = m._botao(faixa, "Outro roteiro...", self.acoes["escolher_roteiro"], "fantasma")
        self.bt_escolher_roteiro.pack(side="left", padx=(8, 0))
        self.lb_roteiro = m._rotulo(faixa, "   o roteiro (.csv, .tsv, .txt, .json) é achado sozinho na pasta",
                                    fonte=self._pequeno)
        self.lb_roteiro.pack(side="left")
        self.var_roteiro = tk.StringVar(self)
        # sem a pasta? o Maestro tira as falas da ISO (nos formatos que ele conhece); nos outros, a ISO/ROM original
        # é só para criar o patch no fim
        rotulo = {"PS1": "Imagem do disco:", "PSP": "ISO do UMD:", "NINTENDO": "ROM original:"}.get(c.chave,
                                                                                                  "ISO do disco:")
        self.var_iso, self.bt_escolher_iso = self._linha_campo(
            cartao, 4, rotulo if c.iso9660 or c.chave == "NINTENDO" else "ISO original:",
            "achada ao lado da pasta; ou escolha para o Maestro tirar as falas" if c.iso9660 else
            f"a do seu {'cartucho' if c.midia == 'ROM' else 'disco'}, sem mudar nada (para criar o patch .{c.criar} "
            "no fim)", "escolher_iso")
        if not self.com_original:                       # Switch e PC: o mod/pacote sai da pasta da entrega
            for item in cartao.grid_slaves(row=4):
                item.grid_remove()
        faixa = self._faixa(cartao, 5, pady=(2, 14))
        self.bt_analisar = m._botao(faixa, "🔍  Analisar a ISO", self.acoes["analisar"])
        self.bt_analisar.pack(side="left")
        self.bt_extrair = m._botao(faixa, "📤  Tirar as falas da ISO", self.acoes["extrair"])
        self.bt_extrair.pack(side="left", padx=(8, 0))
        self.bt_relatorio = m._botao(faixa, "Salvar o relatório", self.acoes["relatorio"], "fantasma")
        self.bt_relatorio.pack(side="left", padx=(8, 0))
        self.lb_analise = m._rotulo(faixa, "   o que tem dentro do disco e o que o Maestro já troca sozinho",
                                    fonte=self._pequeno)
        self.lb_analise.pack(side="left")
        if not c.iso9660:                               # (só PS2, PS1 e PSP: o Maestro abre o disco sozinho)
            faixa.grid_remove()
        if not self.ps2:
            self.lb_guia = ctk.CTkLabel(cartao, text=f"Como tirar do {c.nome}: {c.guia}", font=self._pequeno,
                                        text_color=Tema.TEXTO_SUAVE, anchor="w", justify="left", wraplength=1000)
            self.lb_guia.grid(row=6, column=0, columnspan=3, sticky="w", padx=20, pady=(0, 14))

    def _montar_traducao(self) -> None:
        m = self.app
        cartao = self._cartao(1, "2. Tradução (menus, legendas e falas)", "mantém os códigos especiais no lugar e "
                              "respeita o espaço de cada fala")
        self.tabela_traducao = self._tabela(cartao, 1, [("n", "#", 70, False), ("original", "Original (inglês)",
                                                        440, True), ("pt", "Português", 440, True),
                                                        ("espaco", "Espaço", 170, False)], 8)
        self.tabela_traducao.bind("<Double-1>", lambda e: self.acoes["editar"]())
        linha = ctk.CTkFrame(cartao, fg_color="transparent")
        linha.grid(row=2, column=0, columnspan=3, sticky="ew", padx=20, pady=(6, 0))
        linha.grid_columnconfigure(1, weight=1)
        m._rotulo(linha, "Glossário:", suave=False).grid(row=0, column=0, padx=(0, 10), sticky="w")
        self.var_glossario = tk.StringVar(self)
        m._entrada(linha, self.var_glossario, "Nomes que não se traduzem: Meu Jogo, Aldeia Verde, Kael").grid(
            row=0, column=1, sticky="ew")
        m._rotulo(linha, "Quem traduz:", suave=False).grid(row=0, column=2, padx=(16, 10), sticky="w")
        self.var_quem_traduz = tk.StringVar(self, value=QUEM_TRADUZ[0])
        self.menu_quem_traduz = m._menu_opcoes(linha, self.var_quem_traduz, QUEM_TRADUZ)
        self.menu_quem_traduz.grid(row=0, column=3, sticky="e")
        self.var_quem_traduz.trace_add("write", lambda *_: self.mostrar_estimativas())
        self.lb_custo_traducao = m._rotulo(linha, "", fonte=self._pequeno)
        self.lb_custo_traducao.grid(row=0, column=4, padx=(12, 0), sticky="e")
        opcoes = self._faixa(cartao, 3, pady=(4, 0))
        self.var_sem_acentos = tk.BooleanVar(self, value=False)
        self.cx_sem_acentos = self._caixa(opcoes, "Sem acentos (a fonte do jogo não tem ç, ã, é)",
                                          self.var_sem_acentos)
        self.cx_sem_acentos.pack(side="left")
        self.var_ouvir = tk.BooleanVar(self, value=True)
        self.cx_ouvir = self._caixa(opcoes, "As falas sem texto no roteiro: o Whisper ouve a original",
                                    self.var_ouvir)
        self.cx_ouvir.pack(side="left", padx=(18, 0))
        faixa = self._faixa(cartao, 4, pady=(8, 14))
        self.bt_traduzir = m._botao(faixa, "Traduzir", self.acoes["traduzir"], "primario", largura=150)
        self.bt_traduzir.pack(side="left")
        self.bt_traduzir_teste = m._botao(faixa, "Só as 20 primeiras (teste)", self.acoes["traduzir_teste"])
        self.bt_traduzir_teste.pack(side="left", padx=(8, 0))
        self.bt_custos = m._botao(faixa, "💰  Opções e custos", self.acoes["custos"], "fantasma")
        self.bt_custos.pack(side="left", padx=(8, 0))
        m._rotulo(faixa, "   dois cliques numa linha: corrigir", fonte=self._pequeno).pack(side="left")
        self.lb_traducao = m._rotulo(faixa, "", fonte=self._pequeno)
        self.lb_traducao.pack(side="right")

    def _montar_dublagem(self) -> None:
        m = self.app
        cartao = self._cartao(2, "3. Dublagem no PC (grátis)", "vozes GENÉRICAS do XTTS-v2 ou as que você importou: "
                              "nunca a voz dos atores do jogo")
        linha = self._faixa(cartao, 1, pady=(2, 0))
        m._rotulo(linha, "Motor:", suave=False).pack(side="left", padx=(0, 10))
        self.var_motor = tk.StringVar(self, value=MOTORES[0])
        m._menu_opcoes(linha, self.var_motor, MOTORES).pack(side="left")
        self.var_motor.trace_add("write", lambda *_: self.acoes["motor"]())
        m._rotulo(linha, "Emoção:", suave=False).pack(side="left", padx=(24, 10))
        self.var_emocao = tk.StringVar(self, value=EMOCOES[0])
        m._menu_opcoes(linha, self.var_emocao, EMOCOES).pack(side="left")
        self.lb_motor = m._rotulo(linha, "", fonte=self._pequeno)
        self.lb_motor.pack(side="right")
        self.tabela_elenco = self._tabela(cartao, 2, [("personagem", "Personagem", 200, True), ("falas", "Falas", 70,
                                                      False), ("voz", "Voz", 300, True),
                                                      ("emocao", "Emoção", 300, True),
                                                      ("duracao", "Duração", 220, False)], 5)
        self.tabela_elenco.bind("<Double-1>", lambda e: self.acoes["trocar_voz"]())
        opcoes = self._faixa(cartao, 3, pady=(4, 0))
        self.var_duracao = tk.BooleanVar(self, value=True)
        self.cx_duracao = self._caixa(opcoes, "Ajustar à duração da original", self.var_duracao)
        self.cx_duracao.pack(side="left")
        self.var_formato = tk.BooleanVar(self, value=True)
        self.cx_formato = self._caixa(opcoes, "Mesmo formato da original", self.var_formato)
        self.cx_formato.pack(side="left", padx=(18, 0))
        self.var_conferir = tk.BooleanVar(self, value=True)
        self.cx_conferir = self._caixa(opcoes, "Conferir cada fala com o Whisper", self.var_conferir)
        self.cx_conferir.pack(side="left", padx=(18, 0))
        self.lb_tempo = m._rotulo(opcoes, "", fonte=self._pequeno)
        self.lb_tempo.pack(side="right")
        faixa = self._faixa(cartao, 4, pady=(8, 14))
        self.bt_dublar = m._botao(faixa, "Dublar no PC", self.acoes["dublar"], "primario", largura=150)
        self.bt_dublar.pack(side="left")
        self.bt_ouvir = m._botao(faixa, "▶  Ouvir 5 falas", self.acoes["ouvir"])
        self.bt_ouvir.pack(side="left", padx=(8, 0))
        self.bt_editar_fala = m._botao(faixa, "✏  Editar uma fala", self.acoes["editar_fala"], "fantasma")
        self.bt_editar_fala.pack(side="left", padx=(8, 0))
        self.bt_dublar_teste = m._botao(faixa, "Só 5 falas (teste)", self.acoes["dublar_teste"], "fantasma")
        self.bt_dublar_teste.pack(side="left", padx=(8, 0))
        self.barra_dublagem = ctk.CTkProgressBar(faixa, width=200, height=8, corner_radius=4, mode="determinate",
                                                 fg_color=Tema.SECUNDARIA, progress_color=Tema.SUCESSO)
        self.barra_dublagem.set(0)
        self.barra_dublagem.pack(side="right")
        self.lb_dublagem = m._rotulo(faixa, "", fonte=self._pequeno)
        self.lb_dublagem.pack(side="right", padx=(0, 10))

    def _montar_entrega(self) -> None:
        m = self.app
        c = self.console
        cartao = self._cartao(3, "4. Entregar", "o Maestro não mexe na ISO original: entrega os arquivos para a "
                              "ferramenta do jogo colocar de volta numa cópia" if c.criar == "xdelta" else
                              "o Maestro não mexe na ROM original: entrega os arquivos para a ferramenta do jogo "
                              "colocar de volta numa cópia" if c.criar == "bps" else
                              "o Maestro não mexe no jogo: entrega os arquivos traduzidos e cria o " +
                              ("mod" if c.criar == "mod" else "pacote") + " para instalar")
        self.var_saida, self.bt_escolher_saida = self._linha_campo(
            cartao, 1, "Salvar em:", "a pasta da tradução (vazio: ao lado da pasta do jogo, com \" - PT-BR\")",
            "escolher_saida")
        faixa = self._faixa(cartao, 2)
        self.bt_entregar = m._botao(faixa, "📝  Gerar roteiro e vozes em português", self.acoes["entregar"],
                                    "primario")
        self.bt_entregar.pack(side="left")
        self.bt_abrir_saida = m._botao(faixa, "Abrir a pasta", self.acoes["abrir_saida"])
        self.bt_abrir_saida.pack(side="left", padx=(8, 0))
        self.bt_criar_patch_jogo = m._botao(faixa, CRIAR[c.criar], self.acoes["criar_patch"], "fantasma")
        self.bt_criar_patch_jogo.pack(side="left", padx=(8, 0))
        self.bt_montar = m._botao(faixa, "💿  Montar a ISO em português", self.acoes["montar"], "fantasma")
        if c.iso9660:
            self.bt_montar.pack(side="left", padx=(8, 0))
        quadro = ctk.CTkFrame(cartao, fg_color=Tema.CAMPO, corner_radius=Tema.RAIO_CONTROLE)
        quadro.grid(row=3, column=0, columnspan=3, sticky="ew", padx=20, pady=(6, 4))
        self.lb_vai_gerar = ctk.CTkLabel(quadro, text="", font=m.f_rotulo, text_color=Tema.TEXTO, anchor="w",
                                         justify="left", wraplength=1000)
        self.lb_vai_gerar.pack(anchor="w", padx=14, pady=(8, 0))
        self.lb_depois = ctk.CTkLabel(quadro, text="", font=self._pequeno, text_color=Tema.TEXTO_SUAVE, anchor="w",
                                      justify="left", wraplength=1000)
        self.lb_depois.pack(anchor="w", padx=14, pady=(2, 8))
        self.lb_entrega = ctk.CTkLabel(cartao, text="", font=m.f_rotulo, text_color=Tema.TEXTO_SUAVE, anchor="w",
                                       justify="left", wraplength=1000)
        self.lb_entrega.grid(row=4, column=0, columnspan=3, sticky="w", padx=20, pady=(2, 14))
        self._mostrar_vai_gerar()

    # ------------------------------------------------------------------ o que a tela mostra
    def mostrar_analise(self, analise) -> None:
        self.analise = analise
        cor = Tema.SUCESSO if analise.pode_trocar else Tema.AVISO
        self.lb_analise.configure(text=f"   {analise.resumo()}", text_color=cor)
        self.info["jogo"].configure(text=f"{analise.descricao}  (lido da ISO)", text_color=Tema.TEXTO)
        self.atualizar()

    def mostrar_lido(self, roteiro, falas: list, contagem: dict, tem_mapa: bool, jogo: str = "") -> None:
        from jellyfin_tools import genero_local
        self.roteiro, self.falas, self.tem_mapa = roteiro, falas, tem_mapa
        if jogo:
            self.info["jogo"].configure(text=jogo, text_color=Tema.TEXTO)
        lidas = [f for f in falas if f.formato is not None]
        if roteiro is not None:
            so_texto = max(0, len(roteiro.com_texto) - sum(1 for f in lidas if f.entrada is not None))
            self.info["textos"].configure(text=roteiro.descrever(), text_color=Tema.TEXTO)
            n = roteiro.com_limite()
            self.info["limite"].configure(
                text="✓ cada fala tem o espaço máximo anotado (a tradução não pode passar dele)"
                if n and n >= len(roteiro.com_texto) else
                f"✓ {n} texto(s) com o espaço máximo anotado (a tradução não pode passar dele)" if n else
                "o roteiro não diz o espaço máximo (confira os textos longos jogando)",
                text_color=Tema.SUCESSO if n else Tema.TEXTO_SUAVE)
            self.lb_roteiro.configure(text=f"   roteiro: {roteiro.arquivo.name}")
        else:
            so_texto = 0
            self.info["textos"].configure(text="sem roteiro: o Whisper ouve as falas e o texto vem dele",
                                          text_color=Tema.TEXTO_SUAVE)
            self.info["limite"].configure(text="—", text_color=Tema.TEXTO_SUAVE)
        com_texto = sum(1 for f in lidas if f.texto.strip())
        taxas = sorted({f.formato.taxa for f in lidas})
        tipos = sorted({f.formato.tipo.upper() for f in lidas})
        nao_lidas = len(falas) - len(lidas)
        pastas = sorted({f.relativo.split("/")[0] + "\\" for f in lidas if "/" in f.relativo})[:2]
        taxa_txt = ", ".join(f"{t // 1000} kHz" if t % 1000 == 0 else f"{t / 1000:.2f} kHz".replace(".", ",")
                             for t in taxas[:3])
        self.info["vozes"].configure(
            text=(" · ".join(p for p in (
                ("pasta " + ", ".join(pastas)) if pastas else "",
                f"{len(lidas)} falas gravadas ({', '.join(tipos)}, {taxa_txt})",
                f"{com_texto} com texto no roteiro" if roteiro is not None else "",
                f"as outras {so_texto} são só texto (menus, legendas, itens)" if so_texto else "",
                f"{nao_lidas} em formato que o Maestro não lê" if nao_lidas else "") if p)) if lidas else
            "nenhuma fala gravada que o Maestro leia (WAV, VAG ou ADS)",
            text_color=Tema.TEXTO if lidas else Tema.AVISO)
        gritos, sussurros = contagem.get(genero_local.TOM_GRITO, 0), contagem.get(genero_local.TOM_SUSSURRO, 0)
        self.info["volume"].configure(
            text=f"{gritos} falas gritadas e {sussurros} sussurradas no original (vão com a emoção) · "
                 f"{contagem.get('m', 0)} de homem, {contagem.get('f', 0)} de mulher" if lidas else "—",
            text_color=Tema.SUCESSO if lidas and (gritos or sussurros) else Tema.TEXTO if lidas else Tema.TEXTO_SUAVE)
        self.mostrar_traducao()
        self.mostrar_elenco()
        self.mostrar_estimativas()
        self.atualizar()

    def linhas_da_traducao(self) -> list:
        """(chave, original, português, espaço/aviso, limite, longa) de cada texto: do roteiro e das falas ouvidas."""
        linhas = []
        if self.roteiro is not None:
            for e in self.roteiro.com_texto:
                aviso = next((a for a in e.avisos if a.startswith("faltou")), "")
                linhas.append((e.chave, e.texto, e.traducao, f"⚠ {aviso}" if aviso else e.espaco(), e.limite, e.longa))
        for f in self.falas:
            if f.ouvida and f.texto.strip():
                aviso = next((a for a in f.avisos if a.startswith("faltou")), "")
                linhas.append((f.relativo, f.texto, f.traducao, f"⚠ {aviso}" if aviso else
                               (f"{len(f.traducao)} letras" if f.traducao else ""), None, ""))
        return linhas

    def mostrar_traducao(self, resumo=None) -> None:
        t = self.tabela_traducao
        t.delete(*t.get_children())
        linhas = self.linhas_da_traducao()
        for i, (chave, original, pt, espaco, limite, longa) in enumerate(linhas[:LINHAS_NA_TABELA]):
            if longa and limite:                     # a 1ª tradução não cabia: ela e a sugestão do Claude embaixo
                t.insert("", "end", iid=str(i), values=(chave, original.replace("\n", " ⏎ "), longa.replace("\n", " ⏎ "),
                                                        f"⚠ {len(longa)} de {limite}"), tags=("conferir",))
                t.insert("", "end", iid=f"{i}s", values=("", "", f"↳ sugestão do Claude: \"{pt}\" (vai esta)", espaco),
                         tags=("cabe",))
                continue
            tag = "conferir" if espaco.startswith("⚠") else "cabe" if espaco.startswith("✓") else \
                ("par" if i % 2 == 0 else "impar")
            t.insert("", "end", iid=str(i), values=(chave, original.replace("\n", " ⏎ "), pt.replace("\n", " ⏎ "),
                                                    espaco), tags=(tag,))
        feitas = sum(1 for linha in linhas if linha[2].strip())
        ajustadas = sum(1 for linha in linhas if linha[5])
        perdidos = sum(1 for linha in linhas if linha[3].startswith("⚠ faltou"))
        passaram = sum(1 for linha in linhas if linha[3].startswith("⚠") and not linha[3].startswith("⚠ faltou"))
        texto = (f"{feitas} de {len(linhas)} traduzidas · {ajustadas} ajustadas para caber · {perdidos} códigos "
                 f"perdidos" + (f" · {passaram} ainda passam do espaço" if passaram else "")) if linhas else ""
        if resumo is not None and getattr(resumo, "custo", None):
            texto += f" · US$ {resumo.custo:.2f}".replace(".", ",")
        self.lb_traducao.configure(text=texto, text_color=Tema.AVISO if perdidos or passaram else Tema.TEXTO_SUAVE)
        self._mostrar_vai_gerar()

    def mostrar_elenco(self, importadas: list = (), pasta_importadas=None, chatterbox: bool = False) -> None:
        t = self.tabela_elenco
        t.delete(*t.get_children())
        for i, (nome, n, voz, emocao, duracao) in enumerate(dj.tabela_do_elenco(self.falas, importadas,
                                                                               pasta_importadas, chatterbox)):
            tag = "conferir" if duracao.startswith("⚠") else "cabe" if duracao.startswith("✓") else \
                ("par" if i % 2 == 0 else "impar")
            from jellyfin_tools import voz_local
            t.insert("", "end", iid=nome, values=(nome, n, voz_local.texto_do_menu(voz) if voz else "—", emocao,
                                                  duracao), tags=(tag,))

    def mostrar_estimativas(self, custo_traducao: str = "", motor: str = "") -> None:
        if custo_traducao:
            self.lb_custo_traducao.configure(text=custo_traducao)
        if motor:
            self.lb_motor.configure(text=motor)
        dublaveis = sum(1 for f in self.falas if f.formato is not None)
        if dublaveis:
            gratis = self.var_motor.get() == MOTORES[0] or self.var_motor.get() == MOTORES[3]
            self.lb_tempo.configure(text=("US$ 0 · " if gratis else "") + dj.estimar_tempo(dublaveis))

    def mostrar_andamento(self, fracao: float, texto: str) -> None:
        self.barra_dublagem.set(max(0.0, min(1.0, fracao)))
        self.lb_dublagem.configure(text=texto, text_color=Tema.TEXTO_SUAVE)

    def mostrar_dublagem(self, texto: str, ok: bool = True) -> None:
        self.lb_dublagem.configure(text=texto, text_color=Tema.SUCESSO if ok else Tema.AVISO)
        self.atualizar()

    def mostrar_entrega(self, texto: str, ok: bool = True) -> None:
        self.lb_entrega.configure(text=texto, text_color=Tema.SUCESSO if ok else Tema.AVISO)
        self.atualizar()

    def selecionado_da_traducao(self) -> int | None:
        item = self.tabela_traducao.focus() or next(iter(self.tabela_traducao.selection()), "")
        return int(item.rstrip("s")) if item else None

    def selecionado_do_elenco(self) -> str | None:
        item = self.tabela_elenco.focus() or next(iter(self.tabela_elenco.selection()), "")
        return item or None

    def _mostrar_vai_gerar(self) -> None:
        partes = []
        if self.roteiro is not None:
            partes.append(f"{self.roteiro.arquivo.stem}_ptbr{self.roteiro.arquivo.suffix} (mesmas colunas do "
                          "original)")
        if self.falas or self.roteiro is None:
            partes.append(f"{dj.PASTA_SAIDA_AUDIO}\\ (mesmos nomes de arquivo)")
        if any(f.ouvida for f in self.falas):
            partes.append("falas_ouvidas.csv (o que o Whisper ouviu)")
        self.lb_vai_gerar.configure(text="Vai gerar:  " + "  +  ".join(partes))
        c = self.console
        emulador = "o seu emulador" if c.emulador.startswith("o ") else f"o {c.emulador}"
        if c.chave == "SWITCH":
            depois = ("Depois, \"Criar o mod (.zip)\" junta as vozes em português com o TitleID do jogo (os textos "
                      ".msbt traduzidos entram na mesma pasta romfs); o mod se instala em \"📦 Instalar a tradução\", "
                      "no emulador ou no cartão SD.")
        elif c.chave == "PC":
            depois = ("Depois, \"Criar o pacote (.zip)\" junta os arquivos em português para instalar por cima da "
                      "pasta onde estavam as vozes, em \"📦 Instalar a tradução\" (os originais ficam guardados e "
                      "Desfazer devolve).")
        elif c.criar == "bps":
            depois = ("Depois, a ferramenta do jogo (ou de romhacking) põe o texto e as vozes em português numa cópia "
                      f"da ROM; aí o Maestro cria o patch (.bps) para guardar ou compartilhar, e a ROM vai para "
                      f"{emulador}.")
        elif not c.iso9660:
            depois = ("Depois, o Dolphin (ou a ferramenta do jogo) remonta a ISO com os arquivos em português; aí o "
                      "Maestro cria o patch (.xdelta) para guardar ou compartilhar.")
        elif not self.ps2:
            depois = ("As falas saíram da ISO pelo Maestro: \"Montar a ISO em português\" põe cada uma no mesmo "
                      "lugar, numa cópia; aí \"Criar o patch (.xdelta)\" guarda a tradução para compartilhar, e a ISO "
                      f"vai para {emulador}." if self.tem_mapa else
                      "Depois, a ferramenta de reinserção do jogo põe tudo numa cópia da ISO; aí o Maestro cria o "
                      f"patch (.xdelta) para guardar ou compartilhar, e a ISO vai para {emulador}.")
        elif self.tem_mapa:
            depois = ("As falas saíram da ISO pelo Maestro: \"Montar a ISO em português\" põe cada uma no mesmo "
                      "lugar, numa cópia; aí \"Criar o patch (.xdelta)\" guarda a tradução para compartilhar, e a ISO "
                      "vai para o OPL/PCSX2.")
        else:
            depois = ("Depois, a ferramenta de reinserção do jogo põe tudo numa cópia da ISO; aí o Maestro cria o "
                      "patch (.xdelta) para guardar ou compartilhar, e a ISO vai para o OPL/PCSX2.")
        self.lb_depois.configure(text=depois)

    def atualizar(self) -> None:
        iso = bool(self.var_iso.get().strip())
        self.bt_analisar.configure(state="normal" if iso else "disabled")
        self.bt_extrair.configure(state="normal" if self.analise is not None and self.analise.falas else "disabled")
        self.bt_relatorio.configure(state="normal" if self.analise is not None else "disabled")
        tem = bool(self.falas) or self.roteiro is not None
        for botao in (self.bt_traduzir, self.bt_traduzir_teste, self.bt_custos, self.bt_automatico):
            botao.configure(state="normal" if tem else "disabled")
        dublaveis = any(f.formato is not None for f in self.falas)
        for botao in (self.bt_dublar, self.bt_dublar_teste, self.bt_ouvir, self.bt_editar_fala):
            botao.configure(state="normal" if dublaveis else "disabled")
        self.bt_entregar.configure(state="normal" if tem else "disabled")
        self.bt_montar.configure(state="normal" if self.tem_mapa and iso else "disabled")
        self.bt_criar_patch_jogo.configure(state="normal" if (iso if self.com_original else tem) else "disabled")
