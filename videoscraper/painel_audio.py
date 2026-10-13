"""Aba "🎧 Áudio" da janela moderna: trocar o áudio entre duas versões de um filme que são suas (ex.: o seu DVD
dublado e o seu Blu-ray). Só a tela fica aqui; o trabalho (ler as faixas, conferir o encaixe, inserir) fica em
jellyfin_tools/troca_audio.py e a ligação com a janela em audio_moderna.py.

Três cartões, de cima para baixo: 1. Origem (o arquivo que tem o áudio que você quer, com as faixas de áudio e de
legenda para marcar), 2. Destino (o arquivo que vai receber a faixa) e 3. Encaixe (conferir, ajustar atraso,
velocidade e volume, comparar as ondas, ouvir 30 s e inserir).
"""

from __future__ import annotations

import re
import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk

import customtkinter as ctk

from jellyfin_tools import troca_audio as ta

from .gui_moderna import SeletorDeTabela, Tema


def numero_do_texto(texto: str) -> float | None:
    """'−4,30' / '-4.3 s' / '+5,8 dB' -> número (None se não for um número)."""
    limpo = (texto or "").strip().replace("−", "-").replace(",", ".").replace(" ", "")
    limpo = re.sub(r"(s|db)$", "", limpo, flags=re.IGNORECASE)
    try:
        return float(limpo)
    except ValueError:
        return None


def segundos_do_texto(texto: str) -> float | None:
    """'58:10' / '0:58:10' / '3490' -> segundos; 'auto' ou vazio -> None (o Maestro escolhe)."""
    texto = (texto or "").strip().lower()
    if not texto or texto == "auto":
        return None
    partes = texto.replace(",", ".").split(":")
    try:
        valores = [float(p) for p in partes]
    except ValueError:
        return None
    if len(valores) > 3:
        return None
    total = 0.0
    for valor in valores:
        total = total * 60 + valor
    return max(0.0, total)


def texto_segundos(valor: float) -> str:
    """-4.3 -> '−4,30'; 0 -> '0,00'; 1.5 -> '+1,50'."""
    if abs(valor) < 0.005:
        return "0,00"
    return f"{valor:+.2f}".replace(".", ",").replace("-", "−")


def texto_lufs(valor: float) -> str:
    return f"{valor:.1f} LUFS".replace(".", ",").replace("-", "−")


def _juntar(nomes: list[str]) -> str:
    """['a', 'b', 'c'] -> 'a, b e c'."""
    if len(nomes) <= 1:
        return "".join(nomes)
    return ", ".join(nomes[:-1]) + " e " + nomes[-1]


def nome_da_faixa(faixa: ta.Faixa) -> str:
    """'Português (por)', 'Espanhol (detectado)' ou 'sem idioma marcado'."""
    if not faixa.idioma or faixa.idioma == "und":
        return "sem idioma marcado"
    return f"{ta.nome_idioma(faixa.idioma)} ({'detectado' if faixa.detectado else faixa.idioma})"


class PainelAudio(ctk.CTkScrollableFrame):
    """A aba inteira (rola quando a tela é baixa). acoes: {'escolher' (lado), 'ler' (lado), 'conferir' (manual),
    'ondas' (), 'ouvir' (), 'amostras' (), 'trocas' (), 'inserir' (onde), 'parar' (), 'abrir_fora' (caminho),
    'vlc' () -> o VLC do PC ou None}. lado: 'origem' ou 'destino'."""

    COLUNAS_AUDIO = (("n", "#", 64, False), ("idioma", "Idioma", 190, False), ("formato", "Formato", 110, False),
                     ("canais", "Canais", 90, False), ("duracao", "Duração", 100, False),
                     ("titulo", "Título da faixa", 320, True))
    FILTROS_AUDIO = {"idioma": "Idioma", "formato": "Formato", "canais": "Canais", "duracao": "Duração",
                     "titulo": "Título da faixa"}
    COLUNAS_LEGENDA = (("n", "#", 64, False), ("idioma", "Idioma", 190, False), ("tipo", "Tipo", 160, False),
                       ("forcada", "Forçada", 100, False), ("obs", "Observação", 420, True))
    FILTROS_LEGENDA = {"idioma": "Idioma", "tipo": "Tipo", "forcada": "Forçada"}
    MODOS = ("Automático", "Manual")
    VISTAS = ("Antes do ajuste", "Depois do ajuste")
    FILME_INTEIRO = "Filme inteiro"
    ZOOMS = (1, 2, 4, 8)
    ALTO_ONDA = 74

    def __init__(self, pai, app, acoes: dict):
        super().__init__(pai, fg_color="transparent")
        self.app = app
        self.acoes = acoes
        self.info: dict[str, ta.InfoArquivo | None] = {"origem": None, "destino": None}
        self.encaixe: ta.Encaixe | None = None          # a última conferência (automática ou do ajuste manual)
        self.encaixe_auto: ta.Encaixe | None = None     # a última automática ("Voltar ao automático")
        self.encaixe_valido = False                     # False: o ajuste mudou depois da conferência
        self.lufs: tuple[float | None, float | None] | None = None   # (faixa nova, áudio do destino)
        self._volume_escolhido = False                  # a pessoa mexeu no volume: não muda mais sozinho
        self._mexendo = False                           # o programa mudando os campos (não conta como a pessoa)
        self._ondas = None                              # (destino, nova, início, duração, ajustada)
        self._texto_sem_ondas = "As ondas aparecem depois de \"Conferir encaixe\"."
        self._zoom = 0
        self._centro: float | None = None
        self._arrasto: dict | None = None
        self._visivel = None                            # (a, b, n, início, duração) do que está desenhado
        self._tempos_ver: dict[str, float] = {}
        self._pequeno = ctk.CTkFont(Tema.FAMILIA, 11)
        self.grid_columnconfigure(0, weight=1)
        self._montar_origem()
        self._montar_destino()
        self._montar_encaixe()
        self._mostrar_resultado()
        self._atualizar_botoes()

    # ------------------------------------------------------------------ montagem
    def _cartao(self, linha: int, titulo: str, dica: str) -> ctk.CTkFrame:
        m = self.app
        cartao = m._cartao(self)
        cartao.grid(row=linha, column=0, sticky="ew", padx=(28, 16), pady=(14 if linha == 0 else 12, 0))
        cartao.grid_columnconfigure(1, weight=1)
        topo = ctk.CTkFrame(cartao, fg_color="transparent")
        topo.grid(row=0, column=0, columnspan=3, sticky="ew", padx=20, pady=(12, 6))
        m._rotulo(topo, titulo, suave=False, fonte=m.f_secao).pack(side="left")
        m._rotulo(topo, "   " + dica, fonte=self._pequeno).pack(side="left", pady=(3, 0))
        return cartao

    def _linha_arquivo(self, cartao, lado: str) -> tk.StringVar:
        m = self.app
        m._rotulo(cartao, "Arquivo:", suave=False).grid(row=2, column=0, padx=(20, 10), sticky="w")
        var = tk.StringVar(self)
        campo = m._entrada(cartao, var, "o caminho do vídeo (.mkv, .mp4...)")
        campo.grid(row=2, column=1, sticky="ew")
        campo.bind("<Return>", lambda e: self.acoes["ler"](lado))
        botao = m._botao(cartao, "Escolher...", lambda: self.acoes["escolher"](lado), largura=110)
        botao.grid(row=2, column=2, padx=(10, 20))
        setattr(self, f"campo_{lado}", campo)
        setattr(self, f"bt_escolher_{lado}", botao)
        return var

    def _tabela(self, pai, colunas, filtros, linhas: int, ao_mudar):
        """(quadro, tabela, seletor): uma tabela com ☐/☑ na coluna # e filtro nos títulos com ▾."""
        quadro = ctk.CTkFrame(pai, fg_color=Tema.CARTAO, corner_radius=0)
        quadro.grid_columnconfigure(0, weight=1)
        tabela = ttk.Treeview(quadro, columns=[c[0] for c in colunas], show="headings", height=linhas,
                              style="Moderno.Treeview", selectmode="extended")
        for chave, texto, largura, estica in colunas:
            tabela.heading(chave, text=texto, anchor="w")
            tabela.column(chave, width=largura, stretch=estica, anchor="w")
        tabela.grid(row=0, column=0, sticky="ew")
        tabela.tag_configure("par", background=Tema.LINHA_PAR)
        tabela.tag_configure("impar", background=Tema.LINHA_IMPAR)
        seletor = SeletorDeTabela(tabela, self.app, filtros, ao_mudar=ao_mudar, coluna_nome="idioma")
        tabela.bind("<Double-1>", lambda e, t=tabela: self._corrigir_idioma(e, t), add="+")
        return quadro, tabela, seletor

    def _montar_origem(self) -> None:
        m = self.app
        c = self._cartao(0, "1. Origem", "O arquivo que tem o áudio que você quer (ex.: o seu DVD dublado). Use com "
                                         "arquivos seus.")
        self.var_origem = self._linha_arquivo(c, "origem")
        quadro, self.tabela_audios, self.sel_audios = self._tabela(c, self.COLUNAS_AUDIO, self.FILTROS_AUDIO, 3,
                                                                   self._ao_mudar_marcacao)
        quadro.grid(row=3, column=0, columnspan=3, sticky="ew", padx=20, pady=(10, 2))
        barra = ctk.CTkFrame(c, fg_color="transparent")
        barra.grid(row=4, column=0, columnspan=3, sticky="ew", padx=20, pady=(0, 6))
        self.sel_audios.montar_barra(barra, campo=False).pack(side="left")
        m._rotulo(barra, "Duplo clique no idioma para corrigir. Sem idioma marcado, o Whisper ouve 30 s.",
                  fonte=self._pequeno).pack(side="right")
        self.lb_origem = m._rotulo(c, "Escolha o arquivo da origem: as faixas de áudio aparecem aqui.",
                                   fonte=self._pequeno)
        self.lb_origem.grid(row=5, column=0, columnspan=3, sticky="w", padx=20)
        m._rotulo(c, "Legendas da origem (marque as que vêm junto, já corrigidas para o destino):",
                  suave=False).grid(row=6, column=0, columnspan=3, sticky="w", padx=20, pady=(8, 4))
        quadro, self.tabela_legendas, self.sel_legendas = self._tabela(c, self.COLUNAS_LEGENDA, self.FILTROS_LEGENDA,
                                                                       2, self._ao_mudar_marcacao)
        quadro.grid(row=7, column=0, columnspan=3, sticky="ew", padx=20)
        barra = ctk.CTkFrame(c, fg_color="transparent")
        barra.grid(row=8, column=0, columnspan=3, sticky="ew", padx=20, pady=(0, 14))
        self.sel_legendas.montar_barra(barra, campo=False).pack(side="left")

    def _montar_destino(self) -> None:
        m = self.app
        c = self._cartao(1, "2. Destino", "O arquivo que vai RECEBER a faixa (ex.: a versão com imagem melhor). Nada "
                                          "da imagem é refeito.")
        self.var_destino = self._linha_arquivo(c, "destino")
        self.lb_ja_tem = m._rotulo(c, "Já tem: (escolha o arquivo)", fonte=self._pequeno)
        self.lb_ja_tem.grid(row=3, column=0, columnspan=3, sticky="w", padx=20, pady=(6, 0))
        opcoes = ctk.CTkFrame(c, fg_color="transparent")
        opcoes.grid(row=4, column=0, columnspan=3, sticky="ew", padx=20, pady=(8, 4))
        m._rotulo(opcoes, "Comparar com:").pack(side="left")
        self.var_comparar = tk.StringVar(self, "o áudio principal")
        self.menu_comparar = m._menu_opcoes(opcoes, self.var_comparar, ["o áudio principal"])
        self.menu_comparar.configure(width=230, command=lambda _v: self._ajuste_mudou(fit=True))
        self.menu_comparar.pack(side="left", padx=(8, 20))
        m._rotulo(opcoes, "Onde:").pack(side="left")
        self.var_onde = tk.StringVar(self, ta.ONDES["dentro"])
        self.menu_onde = m._menu_opcoes(opcoes, self.var_onde, list(ta.ONDES.values()))
        self.menu_onde.configure(width=380)
        self.menu_onde.pack(side="left", padx=(8, 20))
        self.var_principal = tk.BooleanVar(self, True)
        ctk.CTkCheckBox(opcoes, text="A 1ª marcada como principal", variable=self.var_principal, font=m.f_normal,
                        text_color=Tema.TEXTO, fg_color=Tema.PRIMARIA, hover_color=Tema.PRIMARIA_HOVER,
                        border_color=Tema.CAMPO_BORDA, checkbox_width=20, checkbox_height=20, corner_radius=6,
                        border_width=2).pack(side="left")
        m._rotulo(c, "Idioma das novas faixas: o de cada uma (dá para trocar na tabela da origem, com duplo clique). "
                     "\"Dentro do próprio arquivo\": a cópia nova é conferida antes de tomar o lugar do original.",
                  fonte=self._pequeno).grid(row=5, column=0, columnspan=3, sticky="w", padx=20, pady=(0, 14))

    def _segmentado(self, pai, valores, comando) -> ctk.CTkSegmentedButton:
        return ctk.CTkSegmentedButton(pai, values=list(valores), command=comando, font=self.app.f_normal, height=32,
                                      fg_color=Tema.CARTAO, selected_color=Tema.PRIMARIA,
                                      selected_hover_color=Tema.PRIMARIA_HOVER, unselected_color=Tema.CARTAO,
                                      unselected_hover_color=Tema.SECUNDARIA_HOVER, text_color=Tema.TEXTO)

    def _montar_encaixe(self) -> None:
        m = self.app
        c = self._cartao(2, "3. Encaixe", "O Maestro compara a música e os efeitos (iguais nos dois idiomas) no "
                                          "começo, no meio e no fim do filme.")
        acoes = ctk.CTkFrame(c, fg_color="transparent")
        acoes.grid(row=2, column=0, columnspan=3, sticky="ew", padx=20, pady=(2, 8))
        self.bt_conferir = m._botao(acoes, "Conferir encaixe", lambda: self.acoes["conferir"](False), "primario",
                                    largura=160)
        self.bt_conferir.pack(side="left")
        self.bt_ouvir = m._botao(acoes, "🎬 Ver 30 s", self.acoes["ouvir"], largura=130)
        self.bt_ouvir.pack(side="left", padx=(10, 0))
        m._rotulo(acoes, "a partir de").pack(side="left", padx=(8, 4))
        self.var_inicio = tk.StringVar(self, "auto")
        m._entrada(acoes, self.var_inicio, width=70).pack(side="left")
        self.bt_amostras = m._botao(acoes, "📂 Amostras feitas", self.acoes["amostras"], "fantasma")
        self.bt_amostras.pack(side="left", padx=(6, 0))
        self.bt_trocas = m._botao(acoes, "📜 Trocas feitas", self.acoes["trocas"], "fantasma")
        self.bt_trocas.pack(side="left")
        self.bt_parar = m._botao(acoes, "Parar", self.acoes["parar"], "perigo", largura=80)
        self.bt_parar.pack(side="right")
        self.bt_inserir = m._botao(acoes, "Inserir 1 faixa", lambda: self.acoes["inserir"](None), "primario",
                                   largura=160)
        self.bt_inserir.pack(side="right", padx=(0, 10))
        self.bt_extrair = m._botao(acoes, "Só extrair (.mka)", lambda: self.acoes["inserir"]("extrair"), "fantasma")
        self.bt_extrair.pack(side="right", padx=(0, 6))

        # o ajuste: automático (o que a conferência achou) ou manual (atraso, velocidade e volume à mão)
        ajuste = ctk.CTkFrame(c, fg_color=Tema.CAMPO, corner_radius=Tema.RAIO_CONTROLE, border_width=1,
                              border_color=Tema.CAMPO_BORDA)
        ajuste.grid(row=3, column=0, columnspan=3, sticky="ew", padx=20, pady=(0, 10))
        l1 = ctk.CTkFrame(ajuste, fg_color="transparent")
        l1.pack(fill="x", padx=14, pady=(10, 4))
        m._rotulo(l1, "Ajuste:", suave=False).pack(side="left")
        self.var_modo = tk.StringVar(self, "Automático")
        self.seg_modo = self._segmentado(l1, self.MODOS, self._ao_escolher_modo)
        self.seg_modo.set("Automático")
        self.seg_modo.pack(side="left", padx=(8, 24))
        m._rotulo(l1, "Atraso (s):").pack(side="left")
        self.botoes_atraso = []
        for texto, passo in (("−1", -1.0), ("−0,1", -0.1)):
            b = m._botao(l1, texto, lambda p=passo: self.somar_atraso(p), largura=48)
            b.pack(side="left", padx=(6, 0))
            self.botoes_atraso.append(b)
        self.var_atraso = tk.StringVar(self, "0,00")
        self.campo_atraso = m._entrada(l1, self.var_atraso, width=80)
        self.campo_atraso.pack(side="left", padx=6)
        self.var_atraso.trace_add("write", lambda *_: self._ajuste_mudou(fit=True, manual=True))
        for texto, passo in (("+0,1", 0.1), ("+1", 1.0)):
            b = m._botao(l1, texto, lambda p=passo: self.somar_atraso(p), largura=48)
            b.pack(side="left", padx=(0, 6))
            self.botoes_atraso.append(b)
        self.lb_achou = m._rotulo(l1, "", fonte=self._pequeno)
        self.lb_achou.pack(side="left", padx=(4, 0))
        l2 = ctk.CTkFrame(ajuste, fg_color="transparent")
        l2.pack(fill="x", padx=14, pady=(4, 6))
        m._rotulo(l2, "Velocidade:").pack(side="left")
        self.var_velocidade = tk.StringVar(self, "Automática")
        self.menu_velocidade = m._menu_opcoes(l2, self.var_velocidade, list(ta.VELOCIDADES))
        self.menu_velocidade.configure(width=270, command=lambda _v: self._ajuste_mudou(fit=True, manual=True))
        self.menu_velocidade.pack(side="left", padx=(8, 16))
        self.bt_conferir_ajuste = m._botao(l2, "Conferir este ajuste", lambda: self.acoes["conferir"](True),
                                           largura=180)
        self.bt_conferir_ajuste.pack(side="left")
        self.bt_voltar_auto = m._botao(l2, "Voltar ao automático", self.voltar_ao_automatico, "fantasma")
        self.bt_voltar_auto.pack(side="left", padx=(6, 0))
        l3 = ctk.CTkFrame(ajuste, fg_color="transparent")
        l3.pack(fill="x", padx=14, pady=(0, 10))
        m._rotulo(l3, "Volume:").pack(side="left")
        self.var_volume = tk.StringVar(self, ta.VOLUMES[0])
        self.menu_volume = m._menu_opcoes(l3, self.var_volume, list(ta.VOLUMES))
        self.menu_volume.configure(width=300, command=self._ao_escolher_volume)
        self.menu_volume.pack(side="left", padx=(8, 10))
        self.bt_menos_db = m._botao(l3, "−1 dB", lambda: self.somar_db(-1.0), largura=60)
        self.bt_menos_db.pack(side="left")
        self.var_db = tk.StringVar(self, "0,0")
        self.campo_db = m._entrada(l3, self.var_db, width=70)
        self.campo_db.pack(side="left", padx=6)
        self.var_db.trace_add("write", lambda *_: self._ajuste_mudou())
        self.bt_mais_db = m._botao(l3, "+1 dB", lambda: self.somar_db(1.0), largura=60)
        self.bt_mais_db.pack(side="left")
        self.lb_medido = m._rotulo(l3, "   Medido: (depois de Conferir encaixe)", fonte=self._pequeno)
        self.lb_medido.configure(wraplength=560)
        self.lb_medido.pack(side="left", fill="x", expand=True)

        # as ondas: o áudio original do destino em cima, a faixa nova embaixo (arrastar = ajustar o atraso)
        ondas = ctk.CTkFrame(c, fg_color=Tema.CAMPO, corner_radius=Tema.RAIO_CONTROLE, border_width=1,
                             border_color=Tema.CAMPO_BORDA)
        ondas.grid(row=4, column=0, columnspan=3, sticky="ew", padx=20, pady=(0, 10))
        o1 = ctk.CTkFrame(ondas, fg_color="transparent")
        o1.pack(fill="x", padx=14, pady=(10, 4))
        m._rotulo(o1, "Comparar as ondas:", suave=False).pack(side="left")
        self.seg_vista = self._segmentado(o1, self.VISTAS, lambda _v: self._pedir_ondas())
        self.seg_vista.set("Depois do ajuste")
        self.seg_vista.pack(side="left", padx=(10, 16))
        m._rotulo(o1, "Ver:").pack(side="left")
        self.var_ver = tk.StringVar(self, self.FILME_INTEIRO)
        self.menu_ver = m._menu_opcoes(o1, self.var_ver, [self.FILME_INTEIRO])
        self.menu_ver.configure(width=170, command=lambda _v: self._pedir_ondas(novo_trecho=True))
        self.menu_ver.pack(side="left", padx=(6, 10))
        self.bt_zoom_menos = m._botao(o1, "− zoom", lambda: self.mudar_zoom(-1), "fantasma", largura=70)
        self.bt_zoom_menos.pack(side="left")
        self.bt_zoom_mais = m._botao(o1, "+ zoom", lambda: self.mudar_zoom(1), "fantasma", largura=70)
        self.bt_zoom_mais.pack(side="left")
        m._rotulo(o1, "Arraste a onda de baixo para ajustar o atraso à mão", fonte=self._pequeno).pack(side="right")
        self.tela = tk.Canvas(ondas, height=self.ALTO_ONDA * 2 + 44, bg=Tema.CAMPO, highlightthickness=0)
        self.tela.pack(fill="x", padx=14, pady=(2, 6))
        self.tela.bind("<Configure>", lambda e: self._desenhar(), add="+")
        self.tela.bind("<ButtonPress-1>", self._comecar_arrasto)
        self.tela.bind("<B1-Motion>", self._arrastar)
        self.tela.bind("<ButtonRelease-1>", self._soltar)
        self.tela.bind("<Motion>", self._cursor)
        ctk.CTkLabel(ondas, text="┆ verde: onde a música e os efeitos (iguais nos dois idiomas) batem nas duas ondas. "
                                 "Se as batidas ficarem desencontradas, o atraso está errado.",
                     font=self._pequeno, text_color=Tema.TEXTO_SUAVE, anchor="w").pack(anchor="w", padx=14,
                                                                                         pady=(0, 10))

        # o resultado da conferência: situação, detalhes e os 3 pontos do filme
        # embaixo: o resultado (à esquerda) e o vídeo de 30 s tocando aqui mesmo (à direita)
        baixo = ctk.CTkFrame(c, fg_color="transparent")
        baixo.grid(row=5, column=0, columnspan=3, sticky="ew", padx=20, pady=(0, 14))
        baixo.grid_columnconfigure(0, weight=1)
        self.previa = PreviaVideo(baixo, m, self.acoes.get("abrir_fora", lambda caminho: None),
                                  self.acoes.get("vlc", lambda: None))
        self.previa.grid(row=0, column=1, sticky="n", padx=(10, 0))
        self.quadro_resultado = ctk.CTkFrame(baixo, fg_color=Tema.SECUNDARIA, corner_radius=Tema.RAIO_CONTROLE)
        self.quadro_resultado.grid(row=0, column=0, sticky="nsew")
        self.lb_res_titulo = ctk.CTkLabel(self.quadro_resultado, text="", font=m.f_secao, anchor="w",
                                          justify="left")
        self.lb_res_titulo.pack(anchor="w", padx=16, pady=(8, 0))
        self.lb_res_detalhe = ctk.CTkLabel(self.quadro_resultado, text="", font=m.f_normal, text_color=Tema.TEXTO,
                                           anchor="w", justify="left", wraplength=640)
        self.lb_res_detalhe.pack(anchor="w", padx=16, pady=(2, 6))
        self.lb_res_aviso = ctk.CTkLabel(self.quadro_resultado, text="", font=m.f_rotulo, text_color=Tema.AVISO,
                                         anchor="w", justify="left", wraplength=640)
        self.quadro_pontos = ctk.CTkFrame(self.quadro_resultado, fg_color="transparent")
        self.quadro_pontos.pack(fill="x", padx=16, pady=(0, 6))
        self.lb_res_nota = ctk.CTkLabel(self.quadro_resultado, text="", font=self._pequeno,
                                        text_color=Tema.TEXTO_SUAVE, anchor="w", justify="left", wraplength=640)
        self.lb_res_nota.pack(anchor="w", padx=16, pady=(0, 10))

    # ------------------------------------------------------------------ os arquivos
    def caminho(self, lado: str) -> str:
        return (self.var_origem if lado == "origem" else self.var_destino).get().strip().strip('"')

    def definir_caminho(self, lado: str, caminho: str) -> None:
        (self.var_origem if lado == "origem" else self.var_destino).set(str(caminho))

    def mostrar_arquivo(self, lado: str, info: ta.InfoArquivo) -> None:
        """Chegou a leitura de um arquivo: as tabelas (origem) ou o "Já tem" (destino)."""
        self.info[lado] = info
        self.encaixe = self.encaixe_auto = None
        self.encaixe_valido = False
        self.lufs = None
        self._ondas = None
        self._texto_sem_ondas = "As ondas aparecem depois de \"Conferir encaixe\"."
        self.lb_achou.configure(text="")
        self.previa.parar()                               # o trecho anterior era de outro arquivo
        if lado == "origem":
            self._volume_escolhido = False
            self._preencher_audios()
        else:
            self.lb_ja_tem.configure(text="Já tem: " + info.resumo())
            opcoes = [f"{k + 1}. {ta.nome_idioma(a.idioma)} ({a.nome_formato} {a.canais})".replace(" )", ")")
                      for k, a in enumerate(info.audios)] or ["(sem áudio)"]
            self.menu_comparar.configure(values=opcoes)
            principal = next((k for k, a in enumerate(info.audios) if a.padrao), 0)
            self.var_comparar.set(opcoes[min(principal, len(opcoes) - 1)])
        self._preencher_legendas(manter=lado == "destino")   # a observação depende do destino
        self._preencher_ver()
        self._mostrar_resultado()
        self._mostrar_volume()
        self._desenhar()
        self._atualizar_botoes()

    def _preencher_audios(self) -> None:
        info = self.info["origem"]
        audios = info.audios if info else []
        linhas = []
        for k, faixa in enumerate(audios):
            titulo = faixa.titulo or ("sem idioma marcado: o Whisper ouviu 30 s" if faixa.detectado else "")
            linhas.append((f"a{k}", (nome_da_faixa(faixa), faixa.nome_formato, faixa.canais or "—",
                                     ta.hms(info.duracao or 0), titulo or "—"), ("par" if k % 2 == 0 else "impar",)))
        # já vem marcada: a 1ª em português (o caso mais comum); senão, a 1ª
        marcar = [f"a{k}" for k, f in enumerate(audios) if f.idioma == "por"][:1] or (["a0"] if audios else [])
        self.tabela_audios.configure(height=max(2, min(6, len(audios))))
        self.sel_audios.preencher(linhas, marcar=marcar)
        if info is None:
            texto = "Escolha o arquivo da origem: as faixas de áudio aparecem aqui."
        elif not audios:
            texto = "Esse arquivo não tem faixa de áudio."
        else:
            texto = (f"{len(audios)} faixa(s) de áudio · {len(info.legendas)} legenda(s) · duração "
                     f"{ta.hms(info.duracao or 0)}. Marque as que vão para o destino (☐/☑).")
        self.lb_origem.configure(text=texto)

    def _observacao(self, legenda: ta.Faixa) -> str:
        destino = self.info["destino"]
        if not legenda.de_texto:
            obs = "imagem: só entra com a mesma velocidade (copiada com o atraso)"
        elif legenda.forcada:
            obs = "só as partes em outro idioma"
        else:
            obs = "texto: os horários são corrigidos junto"
        if destino and any(s.idioma == legenda.idioma for s in destino.legendas):
            obs = f"o destino já tem legenda em {ta.nome_idioma(legenda.idioma)}" + (" · " + obs if legenda.forcada
                                                                                     else "")
        return obs

    def _preencher_legendas(self, manter: bool = False) -> None:
        """manter: o destino mudou (só a observação muda; as marcações continuam). Senão (origem nova), já vem
        marcada a legenda forçada de texto (as placas e as falas em outro idioma) que o destino não tem."""
        info = self.info["origem"]
        legendas = info.legendas if info else []
        antes = set(self.sel_legendas.marcados())
        destino = self.info["destino"]
        linhas = []
        for k, legenda in enumerate(legendas):
            linhas.append((f"s{k}", (nome_da_faixa(legenda), legenda.nome_formato, "sim" if legenda.forcada else "não",
                                     self._observacao(legenda)), ("par" if k % 2 == 0 else "impar",)))
        if manter:
            marcar = [i for i in antes if i in {iid for iid, _, _ in linhas}]
        else:
            ja_tem = {s.idioma for s in destino.legendas} if destino else set()
            marcar = [f"s{k}" for k, s in enumerate(legendas) if s.forcada and s.de_texto and s.idioma not in ja_tem]
        self.tabela_legendas.configure(height=max(2, min(5, len(legendas))))
        self.sel_legendas.preencher(linhas, marcar=marcar)

    def _faixa_audio(self, iid: str) -> ta.Faixa:
        return self.info["origem"].audios[int(iid[1:])]

    def _faixa_legenda(self, iid: str) -> ta.Faixa:
        return self.info["origem"].legendas[int(iid[1:])]

    def audios_marcados(self) -> list[ta.Faixa]:
        return [self._faixa_audio(i) for i in self.sel_audios.marcados()] if self.info["origem"] else []

    def legendas_marcadas(self) -> list[ta.Faixa]:
        return [self._faixa_legenda(i) for i in self.sel_legendas.marcados()] if self.info["origem"] else []

    def faixa_destino(self) -> int:
        """Com qual áudio do destino comparar (o principal, ou o escolhido em "Comparar com")."""
        achado = re.match(r"(\d+)\.", self.var_comparar.get())
        return int(achado[1]) - 1 if achado else 0

    def _corrigir_idioma(self, evento, tabela) -> str | None:
        """Duplo clique numa linha: um menu com os idiomas (para a faixa sem etiqueta ou com a etiqueta errada)."""
        iid = tabela.identify_row(evento.y)
        if not iid or self.info["origem"] is None:
            return None
        faixa = self._faixa_audio(iid) if tabela is self.tabela_audios else self._faixa_legenda(iid)
        menu = tk.Menu(self, tearoff=0, bg=Tema.CARTAO, fg=Tema.TEXTO, activebackground=Tema.PRIMARIA,
                       activeforeground="#ffffff")
        for opcao in ta.MENU_IDIOMAS:
            menu.add_command(label=opcao, command=lambda o=opcao: self.definir_idioma(faixa, ta.codigo_de(o)))
        menu.add_separator()
        menu.add_command(label="Outro (digitar o código de 3 letras)...", command=lambda: self._outro_idioma(faixa))
        try:
            menu.tk_popup(evento.x_root, evento.y_root)
        finally:
            menu.grab_release()
        return "break"

    def _outro_idioma(self, faixa: ta.Faixa) -> None:
        dialogo = ctk.CTkInputDialog(text="Código do idioma (3 letras, ex.: por, eng, spa):", title="Idioma da faixa")
        codigo = ta.codigo_de(dialogo.get_input() or "")
        if re.fullmatch(r"[a-z]{2,3}", codigo):
            self.definir_idioma(faixa, codigo)

    def definir_idioma(self, faixa: ta.Faixa, codigo: str) -> None:
        """Corrige o idioma de uma faixa (vale para o que for inserido: etiqueta e título)."""
        faixa.idioma, faixa.detectado = codigo, False
        tabela = self.tabela_audios if faixa.tipo == "audio" else self.tabela_legendas
        iid = ("a" if faixa.tipo == "audio" else "s") + str(
            (self.info["origem"].audios if faixa.tipo == "audio" else self.info["origem"].legendas).index(faixa))
        if tabela.exists(iid):
            tabela.set(iid, "idioma", nome_da_faixa(faixa))
        self._mostrar_resultado()
        self._mostrar_volume()

    def _ao_mudar_marcacao(self) -> None:
        if not hasattr(self, "bt_inserir"):
            return                                        # ainda montando
        self._mostrar_resultado()
        self._atualizar_botoes()

    # ------------------------------------------------------------------ o ajuste
    def atraso(self) -> float | None:
        return numero_do_texto(self.var_atraso.get())

    def fator(self) -> float:
        if self.var_modo.get() == "Automático" and self.encaixe_auto is not None:
            return self.encaixe_auto.fator
        escolha = ta.VELOCIDADES.get(self.var_velocidade.get())
        if escolha == "esticar":
            o, d = self.info["origem"], self.info["destino"]
            return d.duracao / o.duracao if o and d and o.duracao and d.duracao else 1.0
        if isinstance(escolha, float):
            return escolha
        return self.encaixe.fator if self.encaixe is not None else 1.0    # "Automática": a que a conferência achou

    def ganho_para_igualar(self) -> float | None:
        if not self.lufs or self.lufs[0] is None or self.lufs[1] is None:
            return None
        return round(self.lufs[1] - self.lufs[0], 1)

    def ganho(self) -> float:
        modo = self.var_volume.get()
        if modo == ta.VOLUMES[0]:
            return 0.0
        if modo == ta.VOLUMES[1]:
            return self.ganho_para_igualar() or 0.0
        return numero_do_texto(self.var_db.get()) or 0.0

    def ajuste(self) -> ta.Ajuste:
        return ta.Ajuste(self.fator(), self.atraso() or 0.0, self.ganho())

    def onde(self) -> str:
        return next((chave for chave, texto in ta.ONDES.items() if texto == self.var_onde.get()), "dentro")

    def pedido(self, onde: str | None = None) -> ta.Pedido | None:
        o, d = self.info["origem"], self.info["destino"]
        if o is None or d is None:
            return None
        return ta.Pedido(o.caminho, d.caminho, self.audios_marcados(), self.legendas_marcadas(), self.ajuste(),
                         bool(self.var_principal.get()), onde or self.onde())

    def inicio_da_amostra(self) -> float:
        """O começo dos 30 s: o campo "a partir de" (ex.: 58:10) ou, em "auto", o ponto do meio do filme."""
        escolhido = segundos_do_texto(self.var_inicio.get())
        if escolhido is not None:
            return escolhido
        if self.encaixe is not None and self.encaixe.pontos:
            return self.encaixe.pontos[len(self.encaixe.pontos) // 2].tempo
        duracao = (self.info["destino"].duracao if self.info["destino"] else None) or 60.0
        return max(0.0, duracao / 2 - 15)

    def somar_atraso(self, passo: float) -> None:
        self.var_atraso.set(texto_segundos(round((self.atraso() or 0.0) + passo, 3)))

    def somar_db(self, passo: float) -> None:
        base = self.ganho()
        self._volume_escolhido = True
        self.var_volume.set(ta.VOLUMES[2])
        self._ao_escolher_volume(ta.VOLUMES[2], marcar=False)
        self.var_db.set(f"{base + passo:+.1f}".replace(".", ","))

    def _ao_escolher_modo(self, modo: str) -> None:
        if modo == "Automático":
            self.voltar_ao_automatico()
        else:
            self.var_modo.set("Manual")
            self._mostrar_resultado()

    def voltar_ao_automatico(self) -> None:
        """O ajuste que a conferência automática achou (atraso e velocidade)."""
        self._mexendo = True
        try:
            self.var_modo.set("Automático")
            self.seg_modo.set("Automático")
            self.var_velocidade.set("Automática")
            if self.encaixe_auto is not None:
                self.var_atraso.set(texto_segundos(self.encaixe_auto.atraso))
                self.encaixe, self.encaixe_valido = self.encaixe_auto, True
        finally:
            self._mexendo = False
        self._mostrar_resultado()
        self._atualizar_botoes()
        self._pedir_ondas()

    def _ajuste_mudou(self, fit: bool = False, manual: bool = False) -> None:
        """A pessoa mexeu no atraso/velocidade (o resultado da conferência fica para trás) ou no volume."""
        if self._mexendo or not hasattr(self, "quadro_resultado"):
            return
        if manual and self.var_modo.get() != "Manual":
            self.var_modo.set("Manual")
            self.seg_modo.set("Manual")
        if fit and self.encaixe is not None:
            self.encaixe_valido = False
        self._mostrar_resultado()
        self._atualizar_botoes()

    def _ao_escolher_volume(self, valor: str, marcar: bool = True) -> None:
        if marcar:
            self._volume_escolhido = True
        manual = valor == ta.VOLUMES[2]
        for widget in (self.bt_menos_db, self.bt_mais_db, self.campo_db):
            widget.configure(state="normal")
        if valor == ta.VOLUMES[1]:
            ganho = self.ganho_para_igualar()
            self._mexendo = True
            self.var_db.set("?" if ganho is None else f"{ganho:+.1f}".replace(".", ","))
            self._mexendo = False
        elif valor == ta.VOLUMES[0]:
            self._mexendo = True
            self.var_db.set("0,0")
            self._mexendo = False
        if not manual:
            self.campo_db.configure(state="disabled")
        self._mostrar_resultado()

    # ------------------------------------------------------------------ o resultado da conferência
    def mostrar_encaixe(self, encaixe: ta.Encaixe, lufs=None) -> None:
        """Chegou uma conferência: o atraso achado no campo, o volume medido, o resultado e as ondas."""
        self.encaixe, self.encaixe_valido = encaixe, True
        if not encaixe.manual:
            self.encaixe_auto = encaixe
        if lufs is not None:
            self.lufs = lufs
        self._mexendo = True
        try:
            self.var_atraso.set(texto_segundos(encaixe.atraso))
            if not encaixe.manual:
                self.var_modo.set("Automático")
                self.seg_modo.set("Automático")
                self.var_velocidade.set("Automática")
        finally:
            self._mexendo = False
        self.lb_achou.configure(text=f"(o automático achou {texto_segundos(encaixe.atraso_achado)} s · "
                                     f"{ta.nome_da_velocidade(encaixe.fator_achado)})")
        self._mostrar_volume()
        self._preencher_ver(meio=True)
        self._mostrar_resultado()
        self._atualizar_botoes()
        self._pedir_ondas(novo_trecho=True)

    def _mostrar_volume(self) -> None:
        nova, original = self.lufs if self.lufs else (None, None)
        if not self.lufs:
            self.lb_medido.configure(text="   Medido: (depois de Conferir encaixe)")
            return
        if nova is None or original is None:
            self.lb_medido.configure(text="   Não deu para medir o volume (trecho sem som?): mantenha ou ajuste à mão.")
            return
        marcadas = self.audios_marcados()
        nome_nova = ta.nome_idioma(marcadas[0].idioma) if marcadas else "faixa nova"
        destino = self.info["destino"]
        k = self.faixa_destino()
        nome_destino = ta.nome_idioma(destino.audios[k].idioma) if destino and k < len(destino.audios) else "áudio"
        diferenca = original - nova
        texto = f"   Medido: {nome_nova} {texto_lufs(nova)} · {nome_destino} do destino {texto_lufs(original)}"
        if abs(diferenca) < ta.DIFERENCA_PARA_IGUALAR:
            texto += f" → diferença de {abs(diferenca):.1f} dB: pode manter (cópia direta)".replace(".", ",")
        else:
            texto += (f" → a faixa nova está {abs(diferenca):.1f} dB mais {'baixa' if diferenca > 0 else 'alta'} "
                      "(sugerido: igualar; os picos são protegidos)").replace(".", ",", 1)
            if not self._volume_escolhido:
                self.var_volume.set(ta.VOLUMES[1])
                self._ao_escolher_volume(ta.VOLUMES[1], marcar=False)
        self.lb_medido.configure(text=texto)
        if self.var_volume.get() == ta.VOLUMES[1]:
            ganho = self.ganho_para_igualar()
            self._mexendo = True
            self.var_db.set(f"{ganho:+.1f}".replace(".", ","))
            self._mexendo = False

    @staticmethod
    def situacao_do_ponto(ponto: ta.Ponto) -> str:
        if ponto.atraso is None:
            return "✕ não deu para medir (pouco som em comum)"
        if ponto.sobra is not None and ponto.sobra <= ta.TOLERANCIA:
            return "✓ boca e voz juntas"
        if ponto.sobra is not None and ponto.sobra <= ta.LIMITE_CORTES:
            return "⚠ quase: dá para notar"
        return "✕ não bate (cena a mais ou a menos?)"

    def texto_do_ajuste(self) -> str:
        """'Atraso −4,30 s · velocidade 25 → 23,976 · volume +5,8 dB · 2 faixas (...) · legenda forçada ...'."""
        aj = self.ajuste()
        partes = [f"Atraso {texto_segundos(aj.atraso)} s", f"velocidade {ta.nome_da_velocidade(aj.fator)}",
                  "volume mantido" if abs(aj.ganho_db) < 0.05 else
                  f"volume {aj.ganho_db:+.1f} dB".replace(".", ",")]
        audios = self.audios_marcados()
        if audios:
            nomes = [ta.nome_idioma(f.idioma) + (" detectado" if f.detectado else "") for f in audios]
            partes.append(f"{len(audios)} faixa{'s' if len(audios) > 1 else ''} ({_juntar(nomes)})")
        legendas = self.legendas_marcadas()
        if len(legendas) == 1:
            partes.append(("legenda forçada" if legendas[0].forcada else "1 legenda") + " corrigida junto")
        elif legendas:
            partes.append(f"{len(legendas)} legendas corrigidas junto")
        return " · ".join(partes)

    def _mostrar_resultado(self) -> None:
        if not hasattr(self, "quadro_resultado"):
            return
        for filho in self.quadro_pontos.winfo_children():
            filho.destroy()
        e = self.encaixe
        self.lb_res_aviso.pack_forget()
        if e is None:
            self.lb_res_titulo.configure(text="Ainda não conferido", text_color=Tema.TEXTO_SUAVE)
            self.lb_res_detalhe.configure(text="Escolha a origem e o destino e clique em \"Conferir encaixe\": o "
                                               "Maestro compara o começo, o meio e o fim do filme (leva de alguns "
                                               "segundos a 1 minuto).")
            self.lb_res_nota.configure(text="")
            return
        icone, cor = (("✓", Tema.SUCESSO) if e.ok else ("✕", Tema.PERIGO) if e.situacao == "cortes"
                      else ("⚠", Tema.AVISO))
        self.lb_res_titulo.configure(text=f"{icone}  {e.texto_situacao()}", text_color=cor)
        self.lb_res_detalhe.configure(text=self.texto_do_ajuste())
        avisos = []
        if not self.encaixe_valido:
            avisos.append("O ajuste mudou depois da conferência: clique em \"Conferir este ajuste\" para medir de novo "
                          "(ou ouça os 30 s).")
        if e.situacao == "cortes":
            avisos.append("\"Inserir\" fica desligado: com versões diferentes, a faixa ficaria fora de sincronia em "
                          "parte do filme. Tente outra velocidade no ajuste manual ou outra versão da origem.")
        if avisos:
            self.lb_res_aviso.configure(text="\n".join(avisos))
            self.lb_res_aviso.pack(anchor="w", padx=16, pady=(0, 6), before=self.quadro_pontos)
        fonte = ctk.CTkFont(Tema.FAMILIA, 11, "bold")
        colunas = (("Ponto do filme", [ta.hms(p.tempo) for p in e.pontos]),
                   ("Diferença que sobrou", ["—" if p.sobra is None else f"{p.sobra:.2f} s".replace(".", ",")
                                             for p in e.pontos]),
                   ("Situação", [self.situacao_do_ponto(p) for p in e.pontos]))
        for coluna, (titulo, valores) in enumerate(colunas):
            self.app._rotulo(self.quadro_pontos, titulo, suave=False, fonte=fonte).grid(row=0, column=coluna,
                                                                                         sticky="w", padx=(0, 40))
            for linha, valor in enumerate(valores, start=1):
                self.app._rotulo(self.quadro_pontos, valor).grid(row=linha, column=coluna, sticky="w", padx=(0, 40))
        audios = self.audios_marcados()
        if audios and self.info["origem"] is not None:
            titulo = ta.titulo_da_faixa(audios[0].idioma, self.info["origem"].caminho, self.ajuste())
            self.lb_res_nota.configure(text=f"O ajuste fica registrado: no título da faixa (\"{titulo}\"), em 📂 "
                                            "Amostras feitas e no histórico (📜 Trocas feitas).")
        else:
            self.lb_res_nota.configure(text="")

    def _atualizar_botoes(self) -> None:
        if not hasattr(self, "bt_inserir"):
            return
        ocupado = bool(getattr(self.app, "_ocupado", False))
        tem = self.info["origem"] is not None and self.info["destino"] is not None
        n = len(self.audios_marcados())
        self.bt_inserir.configure(text=f"Inserir {n} faixa{'s' if n != 1 else ''}" if n else "Inserir")
        pode = tem and n > 0 and not ocupado
        bloqueado = self.encaixe is not None and self.encaixe.situacao == "cortes"
        estado = "normal" if pode else "disabled"
        for botao in (self.bt_conferir, self.bt_ouvir, self.bt_conferir_ajuste):
            botao.configure(state=estado)
        self.bt_inserir.configure(state="normal" if pode and not bloqueado else "disabled")
        self.bt_extrair.configure(state=estado)
        livre = "disabled" if ocupado else "normal"
        for botao in (self.bt_escolher_origem, self.bt_escolher_destino):
            botao.configure(state=livre)
        self.bt_voltar_auto.configure(state="normal" if self.encaixe_auto is not None and not ocupado else "disabled")
        self.bt_parar.configure(state="normal" if ocupado else "disabled",
                                border_color=Tema.PERIGO if ocupado else Tema.CAMPO_BORDA)

    def definir_ocupado(self, ocupado: bool) -> None:
        self._atualizar_botoes()

    @property
    def botoes_de_trabalho(self) -> list:
        return [self.bt_conferir, self.bt_ouvir, self.bt_conferir_ajuste, self.bt_inserir, self.bt_extrair,
                self.bt_escolher_origem, self.bt_escolher_destino]

    # ------------------------------------------------------------------ as ondas
    def _preencher_ver(self, meio: bool = False) -> None:
        """Ver: o filme inteiro ou 30 s em cada um dos 3 pontos da conferência."""
        destino = self.info["destino"]
        if self.encaixe is not None and self.encaixe.pontos:
            tempos = [p.tempo for p in self.encaixe.pontos]
        elif destino is not None and destino.duracao:
            tempos = ta.pontos_do_filme(destino.duracao, ta._janela(destino.duracao))
        else:
            tempos = []
        self._tempos_ver = {f"30 s em {ta.hms(t)}": t for t in tempos}
        valores = [self.FILME_INTEIRO, *self._tempos_ver]
        self.menu_ver.configure(values=valores)
        if meio and self._tempos_ver:
            self.var_ver.set(list(self._tempos_ver)[len(self._tempos_ver) // 2])
        elif self.var_ver.get() not in valores:
            self.var_ver.set(self.FILME_INTEIRO)

    def trecho_das_ondas(self) -> tuple[float, float]:
        destino = self.info["destino"]
        total = (destino.duracao if destino else None) or 30.0
        if self.var_ver.get() in self._tempos_ver:
            inicio = self._tempos_ver[self.var_ver.get()]
            return inicio, min(30.0, max(1.0, total - inicio))
        return 0.0, total

    def dados_das_ondas(self):
        """(pedido, faixa do destino, início, duração, ajustada, pontos por segundo) ou None."""
        pedido = self.pedido()
        if pedido is None or not pedido.audios:
            return None
        inicio, duracao = self.trecho_das_ondas()
        pontos = 100 if duracao <= 60 else max(0.05, 4000 / duracao)
        return pedido, self.faixa_destino(), inicio, duracao, self.seg_vista.get() == "Depois do ajuste", pontos

    def mostrar_previa(self) -> None:
        """Rola a aba até o vídeo (ele fica no fim do cartão 3)."""
        try:
            self.update_idletasks()
            altura = max(1, self.winfo_height())
            y = self.previa.winfo_rooty() - self.winfo_rooty()
            self._parent_canvas.yview_moveto(max(0.0, (y - 120) / altura))
        except (tk.TclError, AttributeError):
            pass

    def _pedir_ondas(self, novo_trecho: bool = False) -> None:
        if novo_trecho:
            self._zoom, self._centro = 0, None
        if self.pedido() is None:
            return
        self._texto_sem_ondas = "Lendo as ondas..." + (" (o filme inteiro leva alguns segundos)"
                                                       if self.var_ver.get() == self.FILME_INTEIRO else "")
        self._ondas = None
        self._desenhar()
        self.acoes["ondas"]()

    def mostrar_ondas(self, dados) -> None:
        """dados: (onda do destino, onda da faixa nova, início, duração, ajustada) ou None (não deu)."""
        self._ondas = dados
        if dados is None:
            self._texto_sem_ondas = "Não deu para ler as ondas desse trecho."
        self._desenhar()

    def mudar_zoom(self, passo: int) -> None:
        self._zoom = max(0, min(len(self.ZOOMS) - 1, self._zoom + passo))
        self._desenhar()

    def _desenhar(self) -> None:
        import numpy as np
        c = self.tela
        c.delete("all")
        largura = max(200, c.winfo_width())
        alto = self.ALTO_ONDA
        if self._ondas is None or min(len(self._ondas[0]), len(self._ondas[1])) < 2:
            c.create_text(largura / 2, alto + 20, text=self._texto_sem_ondas, fill=Tema.TEXTO_SUAVE,
                          font=(Tema.FAMILIA, 11))
            self._visivel = None
            return
        destino, nova, inicio, duracao, ajustada = self._ondas
        n = min(len(destino), len(nova))
        visiveis = max(2, int(n / self.ZOOMS[self._zoom]))
        centro = 0.5 if self._centro is None else self._centro
        a = max(0, min(n - visiveis, int(round(centro * n - visiveis / 2))))
        b = a + visiveis
        self._visivel = (a, b, n, inicio, duracao)

        def colunas(valores):
            trecho = np.asarray(valores[a:b], dtype=np.float32)
            bordas = np.minimum(np.linspace(0, len(trecho), largura + 1).astype(int)[:-1], len(trecho) - 1)
            return np.maximum.reduceat(trecho, bordas)

        destino_c = self.info["destino"]
        k = self.faixa_destino()
        nome_destino = (ta.nome_idioma(destino_c.audios[k].idioma) if destino_c and k < len(destino_c.audios)
                        else "áudio")
        marcadas = self.audios_marcados()
        nome_nova = ta.nome_idioma(marcadas[0].idioma) if marcadas else "faixa nova"
        volume = " e o volume igualado" if self.var_volume.get() == ta.VOLUMES[1] else ""
        rotulos = (f"Destino: {nome_destino} (original)",
                   f"Nova faixa: {nome_nova} " + (f"(com o ajuste{volume})" if ajustada else "(sem o ajuste)"))
        for y0, valores, cor, rotulo, marca in ((4, destino, "#5b8def", rotulos[0], "destino"),
                                                (alto + 12, nova, Tema.PRIMARIA, rotulos[1], "nova")):
            meio = y0 + alto / 2
            c.create_line(0, meio, largura, meio, fill=Tema.CARTAO_BORDA, tags=(marca,))
            for x, v in enumerate(colunas(valores)):
                h = max(0.5, min(1.0, float(v)) * (alto / 2 - 4))
                c.create_line(x, meio - h, x, meio + h, fill=cor, tags=(marca,))
            c.create_text(8, y0 + 9, text=rotulo, anchor="w", fill=Tema.TEXTO, font=(Tema.FAMILIA, 10, "bold"),
                          tags=(marca,))
        for i in ta.batidas_comuns(destino[a:b], nova[a:b]):      # onde as batidas coincidem nas duas
            x = i * largura / visiveis
            c.create_line(x, 2, x, alto * 2 + 14, fill="#3ddc84", dash=(3, 3), tags=("verde",))
        regua = alto * 2 + 26
        for k in range(7):
            x = k * (largura - 1) / 6
            t = inicio + (a + k * visiveis / 6) / n * duracao
            c.create_line(x, regua - 6, x, regua - 2, fill=Tema.TEXTO_SUAVE)
            if duracao > 60 or self._zoom == 0:
                texto = ta.hms(t)
            else:                                         # com zoom num trecho de 30 s: os décimos de segundo
                texto = f"{int(t) // 60}:{t % 60:04.1f}".replace(".", ",")
            c.create_text(min(max(x, 26), largura - 26), regua + 8, text=texto, fill=Tema.TEXTO_SUAVE,
                          font=(Tema.FAMILIA, 9))

    def segundos_por_pixel(self) -> float | None:
        if self._visivel is None:
            return None
        a, b, n, _inicio, duracao = self._visivel
        return (b - a) / n * duracao / max(200, self.tela.winfo_width())

    def _na_onda_de_baixo(self, y: int) -> bool:
        return (self._ondas is not None and self._ondas[4] and self.ALTO_ONDA + 8 <= y <= self.ALTO_ONDA * 2 + 16
                and self.info["origem"] is not None)

    def _cursor(self, evento) -> None:
        self.tela.configure(cursor="sb_h_double_arrow" if self._na_onda_de_baixo(evento.y) else "")

    def _comecar_arrasto(self, evento) -> None:
        self._arrasto = {"x": evento.x, "total": 0} if self._na_onda_de_baixo(evento.y) else None

    def _arrastar(self, evento) -> None:
        if self._arrasto is None:
            return
        dx = evento.x - self._arrasto["x"]
        self._arrasto["x"] = evento.x
        self._arrasto["total"] += dx
        self.tela.move("nova", dx, 0)

    def _soltar(self, _evento=None) -> None:
        arrasto, self._arrasto = self._arrasto, None
        passo = self.segundos_por_pixel()
        if not arrasto or not arrasto["total"] or passo is None:
            return
        self.arrastar_atraso(arrasto["total"] * passo)

    def arrastar_atraso(self, segundos: float) -> None:
        """A onda de baixo foi arrastada: para a direita a faixa nova toca mais tarde (o atraso aumenta)."""
        self.var_atraso.set(texto_segundos(round((self.atraso() or 0.0) + segundos, 2)))
        self._pedir_ondas()


def ids_das_faixas(descricao) -> list[int]:
    """As faixas de áudio que o VLC achou no vídeo, na ordem (sem o "Desligado", que vem com id -1)."""
    ids = []
    for faixa in descricao or []:
        ident = faixa[0] if isinstance(faixa, (tuple, list)) else getattr(faixa, "id", None)
        if isinstance(ident, int) and ident >= 0:
            ids.append(ident)
    return ids


def minutos(segundos: float) -> str:
    s = max(0, int(segundos))
    return f"{s // 60}:{s % 60:02d}"


class PreviaVideo(ctk.CTkFrame):
    """O trecho de 30 s tocando DENTRO da aba (com o VLC instalado no PC), para ver se a boca bate com a voz.
    "Ouvir" troca, no mesmo ponto, entre a faixa nova e o áudio original do destino; "Abrir no player" abre em
    tela cheia. Sem o VLC, o trecho abre no player padrão (como os outros testes). criar_vlc() -> instância ou None."""
    LARGURA, ALTURA = 480, 270           # 16:9
    OUVIR = ("Faixa nova", "Original")

    def __init__(self, pai, app, abrir_fora, criar_vlc):
        super().__init__(pai, fg_color=Tema.CAMPO, corner_radius=Tema.RAIO_CONTROLE, border_width=1,
                         border_color=Tema.CAMPO_BORDA)
        self.app, self.abrir_fora, self.criar_vlc = app, abrir_fora, criar_vlc
        self.caminho: Path | None = None
        self.player = None
        self._vigiando = False
        pequeno = ctk.CTkFont(Tema.FAMILIA, 11)
        topo = ctk.CTkFrame(self, fg_color="transparent")
        topo.pack(fill="x", padx=12, pady=(8, 4))
        app._rotulo(topo, "Ver o encaixe", suave=False, fonte=app.f_secao).pack(side="left")
        app._rotulo(topo, "  a boca tem que bater com a voz", fonte=pequeno).pack(side="left", pady=(2, 0))
        escala = app._pontos() if hasattr(app, "_pontos") else 1.0
        self.tela = tk.Frame(self, bg="#000000", width=round(self.LARGURA * escala),
                             height=round(self.ALTURA * escala), highlightthickness=0)
        self.tela.pack(padx=12)
        self.tela.pack_propagate(False)
        self.lb_tela = tk.Label(self.tela, text="Clique em 🎬 Ver 30 s:\no trecho do filme toca aqui, com a faixa nova.",
                                fg=Tema.TEXTO_SUAVE, bg="#000000", font=(Tema.FAMILIA, 11), justify="center")
        self.lb_tela.place(relx=0.5, rely=0.5, anchor="center")
        controles = ctk.CTkFrame(self, fg_color="transparent")
        controles.pack(fill="x", padx=12, pady=(6, 10))
        estilo = dict(height=30, corner_radius=8, font=app.f_normal, fg_color=Tema.SECUNDARIA,
                      hover_color=Tema.SECUNDARIA_HOVER, text_color=Tema.TEXTO,
                      text_color_disabled=Tema.TEXTO_FRACO)
        self.bt_tocar = ctk.CTkButton(controles, text="▶", width=38, command=self.alternar, **estilo)
        self.bt_tocar.pack(side="left")
        self.bt_inicio = ctk.CTkButton(controles, text="⟲", width=34, command=self.do_comeco, **estilo)
        self.bt_inicio.pack(side="left", padx=(4, 8))
        app._rotulo(controles, "Ouvir:").pack(side="left")
        self.seg_ouvir = ctk.CTkSegmentedButton(controles, values=list(self.OUVIR), command=self.ouvir, height=30,
                                                font=app.f_normal, fg_color=Tema.CARTAO, selected_color=Tema.PRIMARIA,
                                                selected_hover_color=Tema.PRIMARIA_HOVER,
                                                unselected_color=Tema.CARTAO,
                                                unselected_hover_color=Tema.SECUNDARIA_HOVER, text_color=Tema.TEXTO)
        self.seg_ouvir.set(self.OUVIR[0])
        self.seg_ouvir.pack(side="left", padx=(6, 8))
        self.lb_tempo = app._rotulo(controles, "0:00 / 0:30", fonte=pequeno)
        self.lb_tempo.pack(side="left")
        self.bt_fora = ctk.CTkButton(controles, text="⛶ Abrir no player", width=20, command=self.abrir_no_player,
                                     **estilo)
        self.bt_fora.pack(side="right")
        self.bind("<Destroy>", lambda e: self.parar() if e.widget is self else None, add="+")
        self._atualizar()

    def carregar(self, caminho) -> bool:
        """Toca o trecho aqui dentro. False: sem o VLC (quem chamou abre no player padrão)."""
        self.parar()
        self.caminho = Path(caminho)
        instancia = self.criar_vlc()
        if instancia is None:
            self._mensagem("Para ver aqui dentro, instale o VLC (grátis, videolan.org).\n"
                           "Por enquanto, o trecho abre no player.")
            self._atualizar()
            return False
        try:
            self.player = instancia.media_player_new()
            self.player.set_media(instancia.media_new(str(self.caminho)))
            janela = self.tela.winfo_id()
            if sys.platform.startswith("win"):
                self.player.set_hwnd(janela)
            elif sys.platform == "darwin":
                self.player.set_nsobject(janela)
            else:
                self.player.set_xwindow(janela)
            self.lb_tela.place_forget()
            self.player.play()
        except Exception:                                 # o VLC do PC não quis tocar: fica o player de fora
            self.player = None
            self._mensagem("O VLC não conseguiu tocar aqui dentro: o trecho abre no player.")
            self._atualizar()
            return False
        self.seg_ouvir.set(self.OUVIR[0])
        self._atualizar()
        if not self._vigiando:
            self._vigiando = True
            self.after(250, self._vigiar)
        return True

    def _mensagem(self, texto: str) -> None:
        self.lb_tela.configure(text=texto)
        self.lb_tela.place(relx=0.5, rely=0.5, anchor="center")

    def _vigiar(self) -> None:
        """De 1/4 em 1/4 de segundo: o tempo, o botão ▶/⏸ e o fim do trecho."""
        if not self.winfo_exists() or self.player is None:
            self._vigiando = False
            return
        try:
            agora = max(0, self.player.get_time() or 0) / 1000
            total = max(0, self.player.get_length() or 0) / 1000 or 30.0
            self.lb_tempo.configure(text=f"{minutos(agora)} / {minutos(total)}")
            self.bt_tocar.configure(text="⏸" if self.player.is_playing() else "▶")
        except Exception:
            pass
        self.after(250, self._vigiar)

    def _terminou(self) -> bool:
        try:
            estado = str(self.player.get_state())
        except Exception:
            return False
        return estado.endswith(("Ended", "Stopped", "Error"))

    def alternar(self) -> None:
        """▶/⏸ (no fim do trecho, ▶ toca de novo do começo)."""
        if self.player is None:
            if self.caminho is not None and self.caminho.is_file():
                self.carregar(self.caminho)
            return
        if self._terminou():
            self.player.stop()
            self.player.play()
            self.after(300, lambda: self.ouvir(self.seg_ouvir.get()))
        elif self.player.is_playing():
            self.player.pause()
        else:
            self.player.play()
        self._atualizar()

    def do_comeco(self) -> None:
        if self.player is None:
            return
        if self._terminou():
            self.player.stop()
            self.player.play()
            self.after(300, lambda: self.ouvir(self.seg_ouvir.get()))
        else:
            self.player.set_time(0)

    def ouvir(self, qual: str) -> None:
        """Troca o áudio no mesmo ponto: a faixa nova (a 1ª do trecho) ou o original do destino (a 2ª)."""
        if self.player is None:
            return
        faixas = ids_das_faixas(self.player.audio_get_track_description())
        if len(faixas) >= 2:
            self.player.audio_set_track(faixas[0 if qual == self.OUVIR[0] else 1])

    def pausar(self) -> None:
        if self.player is not None and self.player.is_playing():
            self.player.pause()

    def parar(self) -> None:
        """Solta o vídeo (antes de apagar o trecho, de trocar de arquivo ou de fechar)."""
        player, self.player = self.player, None
        if player is not None:
            try:
                player.stop()
                player.release()
            except Exception:
                pass
            try:
                self._mensagem("Parado. Clique em ▶ para ver de novo.")
            except tk.TclError:
                pass
        try:
            self._atualizar()
        except tk.TclError:
            pass

    def abrir_no_player(self) -> None:
        if self.caminho is None:
            return
        self.pausar()
        self.abrir_fora(self.caminho)

    def _atualizar(self) -> None:
        tem = self.caminho is not None
        tocando = self.player is not None
        self.bt_tocar.configure(state="normal" if tem else "disabled")
        self.bt_inicio.configure(state="normal" if tocando else "disabled")
        self.bt_fora.configure(state="normal" if tem else "disabled")
        self.seg_ouvir.configure(state="normal" if tocando else "disabled")


class JanelaTrocas(ctk.CTkToplevel):
    """"📜 Trocas feitas": o histórico das faixas inseridas/extraídas (o ajuste usado, onde ficou). Abrir o arquivo
    feito, abrir a pasta ou tirar do histórico (os arquivos não são apagados). itens(): a lista de
    troca_audio.trocas_feitas; abrir/pasta(item); tirar(itens) -> True se tirou."""
    COLUNAS = (("n", "#", 64, False), ("feito", "Feito em", 130, False), ("destino", "Destino", 290, True),
               ("faixas", "Faixas", 150, False), ("ajuste", "Ajuste", 260, False), ("onde", "Onde", 130, False))
    FILTROS = {"feito": "Feito em", "destino": "Destino", "faixas": "Faixas", "onde": "Onde"}
    ONDES = {"dentro": "no próprio arquivo", "copia": "cópia à parte", "extrair": "só a faixa (.mka)"}

    def __init__(self, master, itens, abrir, pasta, tirar):
        super().__init__(master, fg_color=Tema.CARTAO)
        self.itens_de, self.abrir, self.pasta, self.tirar = itens, abrir, pasta, tirar
        self._itens: list[dict] = []
        self.title("Trocas feitas")
        self.geometry("1040x520")
        self.minsize(760, 380)
        self.transient(master.winfo_toplevel())
        ctk.CTkLabel(self, text="Trocas feitas", font=ctk.CTkFont(Tema.FAMILIA, 17, "bold"),
                     text_color=Tema.TEXTO, anchor="w").pack(fill="x", padx=24, pady=(18, 2))
        ctk.CTkLabel(self, text="As faixas que a aba 🎧 Áudio inseriu ou extraiu, com o ajuste usado (atraso, "
                     "velocidade, volume). \"Tirar do histórico\" não apaga nenhum arquivo.", font=master.f_rotulo,
                     text_color=Tema.TEXTO_SUAVE, anchor="w", justify="left", wraplength=980
                     ).pack(fill="x", padx=24, pady=(0, 6))
        quadro = ctk.CTkFrame(self, fg_color=Tema.CARTAO)
        self.tabela = ttk.Treeview(quadro, columns=[c[0] for c in self.COLUNAS], show="headings",
                                   selectmode="extended", style="Moderno.Treeview", height=8)
        for chave, texto, largura, estica in self.COLUNAS:
            self.tabela.heading(chave, text=texto, anchor="w")
            self.tabela.column(chave, width=largura, stretch=estica, anchor="w")
        self.tabela.pack(fill="both", expand=True)
        self.tabela.bind("<Double-1>", self._abrir_clicado)
        botoes = ctk.CTkFrame(self, fg_color="transparent")
        self.bt_abrir = master._botao(botoes, "▶  Abrir", self._abrir, "primario", largura=110)
        self.bt_pasta = master._botao(botoes, "📂  Abrir a pasta", self._pasta, largura=150)
        self.bt_tirar = master._botao(botoes, "✕  Tirar do histórico", self._tirar, "perigo", largura=200)
        for b in (self.bt_abrir, self.bt_pasta, self.bt_tirar):
            b.pack(side="left", padx=(0, 8))
        master._botao(botoes, "Fechar", self.destroy, "fantasma", largura=80).pack(side="right")
        self.seletor = SeletorDeTabela(self.tabela, master, self.FILTROS, valor=self._valor, ao_mudar=self._ao_mudar,
                                       coluna_nome="destino")
        self.seletor.montar_barra(self).pack(fill="x", padx=24, pady=(0, 4))
        self.lb_detalhe = ctk.CTkLabel(self, text="", font=master.f_rotulo, text_color=Tema.TEXTO_SUAVE, anchor="w",
                                       justify="left", wraplength=980)
        self.lb_detalhe.pack(fill="x", padx=24, pady=(0, 4))
        botoes.pack(side="bottom", fill="x", padx=24, pady=14)
        quadro.pack(fill="both", expand=True, padx=24)
        self.recarregar()

    @staticmethod
    def _quando(feito: str) -> str:
        data, _, hora = str(feito or "").partition("T")
        partes = data.split("-")
        return f"{partes[2]}/{partes[1]}/{partes[0]} {hora[:5]}".strip() if len(partes) == 3 else str(feito or "")

    def _valor(self, coluna: str, iid: str) -> str:
        valor = str(self.tabela.set(iid, coluna)).strip()
        if coluna == "feito":
            return valor.split(" ")[0] or "(vazio)"
        return valor or "(vazio)"

    def recarregar(self) -> None:
        from pathlib import Path
        self._itens = list(self.itens_de())
        linhas = []
        for i, item in enumerate(self._itens):
            linhas.append((str(i), (self._quando(item.get("feito", "")), Path(str(item.get("destino", ""))).name,
                                    _juntar(list(item.get("faixas") or [])) or "—", item.get("ajuste", "—"),
                                    self.ONDES.get(item.get("onde", ""), item.get("onde", "—"))),
                           ("par" if i % 2 == 0 else "impar",)))
        self.seletor.preencher(linhas, marcar=["0"] if linhas else [])

    def _ao_mudar(self) -> None:
        if not hasattr(self, "lb_detalhe"):
            return
        marcados = self.seletor.marcados()
        um = "normal" if marcados else "disabled"
        self.bt_abrir.configure(state=um)
        self.bt_pasta.configure(state=um)
        self.bt_tirar.configure(state=um, text=f"✕  Tirar do histórico ({len(marcados)})" if marcados
                                else "✕  Tirar do histórico")
        item = self.escolhido()
        if item is None:
            self.lb_detalhe.configure(text=f"{len(self._itens)} troca(s) no histórico." if self._itens
                                      else "Nenhuma troca feita ainda.")
            return
        legendas = ", ".join(item.get("legendas") or []) or "nenhuma"
        avisos = "; ".join(item.get("avisos") or [])
        self.lb_detalhe.configure(text=f"Origem: {item.get('origem', '')}\nFicou em: {item.get('saida', '')}\n"
                                       f"Legendas: {legendas}" + (f"\nAvisos: {avisos}" if avisos else ""))

    def escolhido(self) -> dict | None:
        iid = self.seletor.em_foco()
        return self._itens[int(iid)] if iid is not None else None

    def marcados(self) -> list[dict]:
        return [self._itens[int(i)] for i in self.seletor.marcados()]

    def _abrir_clicado(self, evento) -> None:
        iid = self.tabela.identify_row(evento.y)
        if iid and self.tabela.identify_region(evento.x, evento.y) in ("cell", "tree"):
            self.abrir(self._itens[int(iid)])

    def _abrir(self) -> None:
        if (item := self.escolhido()):
            self.abrir(item)

    def _pasta(self) -> None:
        if (item := self.escolhido()):
            self.pasta(item)

    def _tirar(self) -> None:
        if (itens := self.marcados()) and self.tirar(itens):
            self.recarregar()
