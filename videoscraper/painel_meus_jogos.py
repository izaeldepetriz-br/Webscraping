"""Aba "🎮 Jogos" → "🔎 Meus jogos" (como no protótipo aprovado): os jogos que você já tem no PC, com a tradução de
cada um. Só a tela fica aqui; o trabalho fica em jellyfin_tools/meus_jogos.py e a ligação com a janela em
meus_jogos_moderna.py.

    1. Onde procurar   as pastas (o HD, o pendrive do OPL, a biblioteca da Steam), as opções e "🔎 Procurar agora"
    2. Os seus jogos   por console (os filtros com a quantidade), a busca pelo nome e a tabela: a cópia do disco
                       (Redump) e a tradução PT-BR de cada um; dois cliques abrem o jogo no submenu do console
    3. O jogo escolhido  o resumo, as traduções achadas e os atalhos (traduzir e dublar, aplicar o patch...)
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import ttk

import customtkinter as ctk

from jellyfin_tools import consoles as cs
from jellyfin_tools import meus_jogos as mj
from jellyfin_tools import patch_jogo as pj

from .gui_moderna import Tema

TODOS = "Todos"
TRADUCOES = ("Tradução: todas", "Só com tradução", "Só sem tradução", "Já traduzidos")


class PainelMeusJogos(ctk.CTkScrollableFrame):
    """acoes: {'adicionar_pasta', 'tirar_pasta', 'procurar'} (sem argumentos) e {'abrir' (jogo, modo ou None),
    'emulador', 'abrir_pasta', 'navegador'} (recebem o jogo)."""

    def __init__(self, pai, app, acoes: dict):
        super().__init__(pai, fg_color="transparent")
        self.app, self.acoes = app, acoes
        self.pastas: list[str] = []
        self.jogos: list[mj.Jogo] = []
        self.escolhido: mj.Jogo | None = None
        self._filtro = TODOS
        self._rotulos_filtro: dict[str, str] = {}
        self._pequeno = ctk.CTkFont(Tema.FAMILIA, 11)
        self.grid_columnconfigure(0, weight=1)
        app._rotulo(self, "O Maestro só lê os seus arquivos: não baixa jogos, não move nem apaga nada. A busca na "
                          "comunidade procura só patches (as ISOs inteiras ficam de fora).", fonte=self._pequeno).grid(
            row=0, column=0, sticky="w", padx=(28, 16), pady=(10, 0))
        self._montar_pastas()
        self._montar_jogos()
        self._montar_escolhido()
        self.mostrar_escolhido(None)

    # ------------------------------------------------------------------ montagem
    def _cartao(self, linha: int, titulo: str, dica: str) -> tuple[ctk.CTkFrame, ctk.CTkLabel, ctk.CTkLabel]:
        m = self.app
        cartao = m._cartao(self)
        cartao.grid(row=linha, column=0, sticky="ew", padx=(28, 16), pady=(12, 0))
        cartao.grid_columnconfigure(0, weight=1)
        topo = ctk.CTkFrame(cartao, fg_color="transparent")
        topo.grid(row=0, column=0, sticky="ew", padx=20, pady=(12, 6))
        lb_titulo = m._rotulo(topo, titulo, suave=False, fonte=m.f_secao)
        lb_titulo.pack(side="left")
        lb_dica = m._rotulo(topo, "   " + dica, fonte=self._pequeno)
        lb_dica.pack(side="left", pady=(3, 0))
        return cartao, lb_titulo, lb_dica

    def _caixa(self, pai, texto: str, valor: bool) -> tuple[ctk.CTkCheckBox, tk.BooleanVar]:
        var = tk.BooleanVar(self, value=valor)
        caixa = ctk.CTkCheckBox(pai, text=texto, variable=var, font=self.app.f_normal, text_color=Tema.TEXTO,
                                fg_color=Tema.PRIMARIA, hover_color=Tema.PRIMARIA_HOVER,
                                border_color=Tema.CAMPO_BORDA, checkbox_width=20, checkbox_height=20, corner_radius=6,
                                border_width=2)
        return caixa, var

    def _tabela(self, pai, linha: int, colunas: list, altura: int) -> ttk.Treeview:
        quadro = ctk.CTkFrame(pai, fg_color=Tema.CARTAO, corner_radius=0)
        quadro.grid(row=linha, column=0, sticky="ew", padx=20, pady=(6, 4))
        quadro.grid_columnconfigure(0, weight=1)
        tabela = ttk.Treeview(quadro, columns=[c[0] for c in colunas], show="headings", height=altura,
                              selectmode="browse", style="Moderno.Treeview")
        for chave, texto, largura, estica in colunas:
            tabela.heading(chave, text=texto, anchor="w")
            tabela.column(chave, width=largura, minwidth=40, stretch=estica, anchor="w")
        tabela.tag_configure("par", background=Tema.LINHA_PAR)
        tabela.tag_configure("impar", background=Tema.LINHA_IMPAR)
        tabela.grid(row=0, column=0, sticky="nsew")
        rolagem = ctk.CTkScrollbar(quadro, command=tabela.yview, height=40, button_color=Tema.CARTAO_BORDA,
                                   button_hover_color=Tema.CAMPO_BORDA)     # (a altura vem da tabela)
        rolagem.grid(row=0, column=1, sticky="ns", padx=(4, 0))
        tabela.configure(yscrollcommand=rolagem.set)
        return tabela

    def _montar_pastas(self) -> None:
        m = self.app
        cartao, _, _ = self._cartao(1, "1. Onde procurar", "as pastas do HD, o pendrive/HD do OPL e a biblioteca da "
                                                           "Steam (com as subpastas)")
        self.tabela_pastas = self._tabela(cartao, 1, [("pasta", "Pasta", 520, True), ("o_que", "O que tem", 360, True),
                                                      ("jogos", "Jogos", 90, False)], 3)
        faixa = ctk.CTkFrame(cartao, fg_color="transparent")
        faixa.grid(row=2, column=0, sticky="ew", padx=20, pady=(4, 2))
        self.bt_adicionar = m._botao(faixa, "＋ Adicionar pasta", self.acoes["adicionar_pasta"], largura=150)
        self.bt_adicionar.pack(side="left")
        self.bt_tirar = m._botao(faixa, "Tirar da lista", self.acoes["tirar_pasta"], "fantasma")
        self.bt_tirar.pack(side="left", padx=(8, 0))
        faixa = ctk.CTkFrame(cartao, fg_color="transparent")
        faixa.grid(row=3, column=0, sticky="w", padx=20, pady=(8, 0))
        self.cx_traducao, self.var_traducao = self._caixa(faixa, "Procurar a tradução de cada jogo (PO.B.R.E e "
                                                                 "fórum; só patches)", True)
        self.cx_traducao.pack(side="left")
        self.cx_redump, self.var_redump = self._caixa(faixa, "Conferir no Redump (lê o disco inteiro: ~1 min por "
                                                             "DVD)", True)
        self.cx_redump.pack(side="left", padx=(18, 0))
        faixa = ctk.CTkFrame(cartao, fg_color="transparent")
        faixa.grid(row=4, column=0, sticky="w", padx=20, pady=(6, 0))
        self.cx_sozinho, self.var_sozinho = self._caixa(faixa, "Procurar de novo sozinho ao abrir o Maestro (só os "
                                                               "arquivos novos)", False)
        self.cx_sozinho.pack(side="left")
        faixa = ctk.CTkFrame(cartao, fg_color="transparent")
        faixa.grid(row=5, column=0, sticky="ew", padx=20, pady=(10, 14))
        self.bt_procurar = m._botao(faixa, "🔎  Procurar agora", self.acoes["procurar"], "primario")
        self.bt_procurar.pack(side="left")
        self.barra = ctk.CTkProgressBar(faixa, width=240, height=8, corner_radius=4, fg_color=Tema.SECUNDARIA,
                                        progress_color=Tema.SUCESSO)
        self.barra.set(0)
        self.barra.pack(side="right")
        self.lb_andamento = m._rotulo(faixa, "", fonte=self._pequeno)
        self.lb_andamento.pack(side="right", padx=(0, 10))

    def _montar_jogos(self) -> None:
        m = self.app
        cartao, _, _ = self._cartao(2, "2. Os seus jogos", "separados por console; clique duas vezes para abrir no "
                                                           "submenu do console")
        faixa = ctk.CTkFrame(cartao, fg_color="transparent")
        faixa.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 4))
        self.seletor_filtro = ctk.CTkSegmentedButton(
            faixa, values=[f"{TODOS} (0)"], command=self._escolheu_filtro, height=30, font=m.f_normal,
            fg_color=Tema.CARTAO, selected_color=Tema.PRIMARIA, unselected_color=Tema.CAMPO,
            selected_hover_color=Tema.PRIMARIA_HOVER, unselected_hover_color=Tema.SECUNDARIA_HOVER,
            text_color=Tema.TEXTO)
        self.seletor_filtro.set(f"{TODOS} (0)")
        self.seletor_filtro.pack(side="left")
        m._rotulo(faixa, "🔍", suave=False).pack(side="left", padx=(14, 4))
        self.var_busca = tk.StringVar(self)
        m._entrada(faixa, self.var_busca, "o nome ou o código").pack(side="left", fill="x", expand=True)
        self.var_busca.trace_add("write", lambda *_: self._preencher())
        self.var_so = tk.StringVar(self, value=TRADUCOES[0])
        m._menu_opcoes(faixa, self.var_so, list(TRADUCOES)).pack(side="left", padx=(12, 0))
        self.var_so.trace_add("write", lambda *_: self._preencher())
        self.lb_resumo = m._rotulo(cartao, "Adicione as pastas dos seus jogos e clique em 🔎 Procurar agora.",
                                   fonte=self._pequeno)
        self.lb_resumo.grid(row=2, column=0, sticky="w", padx=20)
        self.tabela = self._tabela(cartao, 3, [("console", "Console", 120, False), ("jogo", "Jogo", 250, True),
                                               ("codigo", "Código", 130, False), ("regiao", "Região", 70, False),
                                               ("copia", "Cópia do disco", 200, False),
                                               ("traducao", "Tradução PT-BR", 300, True),
                                               ("onde", "Onde está", 190, False)], 10)
        self.tabela.bind("<<TreeviewSelect>>", lambda e: self.mostrar_escolhido(self.selecionado()))
        self.tabela.bind("<Double-1>", lambda e: self._abrir(None))
        ctk.CTkFrame(cartao, fg_color="transparent", height=10).grid(row=4, column=0)

    def _montar_escolhido(self) -> None:
        m = self.app
        cartao, self.lb_escolhido, self.lb_escolhido_dica = self._cartao(3, "O jogo escolhido", "")
        self.lb_traducoes = ctk.CTkLabel(cartao, text="", font=m.f_rotulo, text_color=Tema.TEXTO_SUAVE, anchor="w",
                                         justify="left", wraplength=1000)
        self.lb_traducoes.grid(row=1, column=0, sticky="w", padx=20)
        faixa = ctk.CTkFrame(cartao, fg_color="transparent")
        faixa.grid(row=2, column=0, sticky="ew", padx=20, pady=(10, 14))
        self.bt_dublar = m._botao(faixa, "🗣  Traduzir e dublar", lambda: self._abrir("dublar"), "primario")
        self.bt_dublar.pack(side="left")
        self.bt_patch = m._botao(faixa, "📀  Aplicar patch", lambda: self._abrir("patch"))
        self.bt_patch.pack(side="left", padx=(8, 0))
        self.bt_enquanto = m._botao(faixa, "🖥  Enquanto joga", lambda: self._abrir("enquanto"))
        self.bt_enquanto.pack(side="left", padx=(8, 0))
        self.bt_emulador = m._botao(faixa, "▶  Abrir no emulador", lambda: self._com_escolhido("emulador"), "fantasma")
        self.bt_emulador.pack(side="left", padx=(8, 0))
        self.bt_pasta = m._botao(faixa, "Abrir a pasta", lambda: self._com_escolhido("abrir_pasta"), "fantasma")
        self.bt_pasta.pack(side="left", padx=(8, 0))
        self.bt_navegador = m._botao(faixa, "🌐 Procurar no navegador", lambda: self._com_escolhido("navegador"),
                                     "fantasma")
        self.bt_navegador.pack(side="left", padx=(8, 0))

    # ------------------------------------------------------------------ o que a tela mostra
    def mostrar_pastas(self, pastas: list[str], por_pasta: dict | None = None) -> None:
        self.pastas = list(pastas)
        por_pasta = por_pasta or {}
        self.tabela_pastas.delete(*self.tabela_pastas.get_children())
        for i, pasta in enumerate(self.pastas):
            quantos, o_que = por_pasta.get(pasta, (None, ""))
            self.tabela_pastas.insert("", "end", iid=pasta, values=(
                pasta, o_que or ("ainda não procurada" if quantos is None else "nenhum jogo"),
                "" if quantos is None else quantos), tags=("par" if i % 2 else "impar",))
        self.bt_procurar.configure(state="normal" if self.pastas else "disabled")

    def pasta_escolhida(self) -> str | None:
        return self.tabela_pastas.focus() or next(iter(self.tabela_pastas.selection()), "") or None

    def mostrar_andamento(self, fracao: float, texto: str = "") -> None:
        self.barra.set(max(0.0, min(1.0, fracao)))
        self.lb_andamento.configure(text=texto, text_color=Tema.TEXTO_SUAVE)

    def mostrar_jogos(self, jogos: list[mj.Jogo]) -> None:
        self.jogos = list(jogos)
        contagem = mj.contar(self.jogos)
        self._rotulos_filtro = {f"{TODOS} ({len(self.jogos)})": TODOS}
        for chave, rotulo in mj.FILTROS:
            if contagem.get(chave):
                self._rotulos_filtro[f"{rotulo} ({contagem[chave]})"] = chave
        if self._filtro not in self._rotulos_filtro.values():
            self._filtro = TODOS
        self.seletor_filtro.configure(values=list(self._rotulos_filtro))
        self.seletor_filtro.set(next(r for r, c in self._rotulos_filtro.items() if c == self._filtro))
        self.lb_resumo.configure(text=mj.resumo(self.jogos) if self.jogos else
                                 "Nenhum jogo nessas pastas (ISO, BIN, ROM, WBFS, NSP ou a biblioteca da Steam).")
        self._preencher()

    def _escolheu_filtro(self, rotulo: str) -> None:
        self._filtro = self._rotulos_filtro.get(rotulo, TODOS)
        self._preencher()

    def visiveis(self) -> list[mj.Jogo]:
        busca = self.var_busca.get().strip().lower()
        so = self.var_so.get()
        lista = []
        for jogo in self.jogos:
            if self._filtro != TODOS and jogo.console != self._filtro:
                continue
            if busca and busca not in f"{jogo.titulo} {jogo.codigo}".lower():
                continue
            if so == TRADUCOES[1] and not jogo.tem_traducao() or so == TRADUCOES[2] and \
                    not jogo.texto_traducao().startswith("✗") or so == TRADUCOES[3] and not jogo.traduzido:
                continue
            lista.append(jogo)
        return sorted(lista, key=lambda j: (mj.ORDEM.index(j.console) if j.console in mj.ORDEM else 99,
                                            j.titulo.lower()))

    def _preencher(self) -> None:
        escolhido = self.escolhido.caminho if self.escolhido else ""
        self.tabela.delete(*self.tabela.get_children())
        for i, jogo in enumerate(self.visiveis()):
            pasta = jogo.caminho if jogo.console == "PC" else str(Path(jogo.caminho).parent)
            self.tabela.insert("", "end", iid=jogo.caminho, values=(
                jogo.rotulo, jogo.titulo, jogo.codigo or "—", jogo.regiao or "—", jogo.texto_copia(),
                jogo.texto_traducao(), pasta), tags=("par" if i % 2 else "impar",))
        if escolhido and self.tabela.exists(escolhido):
            self.tabela.selection_set(escolhido)
            self.tabela.focus(escolhido)
            self.mostrar_escolhido(self.selecionado())
        else:
            self.mostrar_escolhido(None)

    def selecionado(self) -> mj.Jogo | None:
        caminho = self.tabela.focus() or next(iter(self.tabela.selection()), "")
        return next((j for j in self.jogos if j.caminho == caminho), None)

    def mostrar_escolhido(self, jogo: mj.Jogo | None) -> None:
        self.escolhido = jogo
        botoes = (self.bt_dublar, self.bt_patch, self.bt_enquanto, self.bt_emulador, self.bt_pasta, self.bt_navegador)
        if jogo is None:
            self.lb_escolhido.configure(text="O jogo escolhido")
            self.lb_escolhido_dica.configure(text="   escolha um jogo na lista")
            self.lb_traducoes.configure(text="")
            for botao in botoes:
                botao.configure(state="disabled")
            return
        console = cs.console(jogo.console)
        partes = [console.nome if jogo.console not in ("NINTENDO", "GCWII") else jogo.rotulo, jogo.codigo, jogo.regiao,
                  pj.tamanho_legivel(jogo.tamanho) if jogo.tamanho else "",
                  f"cópia perfeita do disco (Redump: {jogo.redump})" if jogo.redump else jogo.texto_copia()
                  if jogo.disco else ""]
        self.lb_escolhido.configure(text=jogo.titulo)
        self.lb_escolhido_dica.configure(text="   " + " · ".join(p for p in partes if p))
        self.lb_traducoes.configure(text=self._texto_traducoes(jogo))
        for botao in botoes:
            botao.configure(state="normal")
        instalar = cs.INSTALAR in console.modos
        self.bt_patch.configure(text="📦  Instalar a tradução" if instalar else "📀  Aplicar patch")
        emulador = "o seu emulador" if console.emulador.startswith("o ") else console.emulador
        self.bt_emulador.configure(text="▶  Jogar (Steam)" if jogo.sistema == "Steam" else
                                   f"▶  Abrir no {emulador}".replace("no o seu", "no seu"))

    @staticmethod
    def _texto_traducoes(jogo: mj.Jogo) -> str:
        if jogo.traduzido:
            return f"Tradução: {jogo.texto_traducao()[2:]}."
        achados = jogo.achados()
        if not jogo.traducao:
            return "Tradução: " + ("procurando na comunidade…" if jogo.procurando else
                                   "ainda não procurada (marque \"Procurar a tradução de cada jogo\").")
        if not achados:
            aviso = f" ({jogo.traducao['aviso']})" if jogo.traducao.get("aviso") else ""
            return ("Tradução: nenhuma no PO.B.R.E nem no fórum" + aviso + ". Romhacking.net e itch.io: 🌐 Procurar "
                    "no navegador. Sem tradução, dá para traduzir e dublar no PC.")
        linhas = []
        for a in achados[:4]:
            detalhes = " · ".join(p for p in (a.get("grupo", ""), f"v{a['versao']}" if a.get("versao") else "",
                                              ", ".join(a.get("traz") or []), a.get("formato", "")) if p)
            linhas.append(f"• {a.get('onde', '')}: {a.get('titulo', '')}" + (f" · {detalhes}" if detalhes else "") +
                          (f"  {a['encaixa']}" if a.get("encaixa") else ""))
        mais = f"\n  … e mais {len(achados) - 4}" if len(achados) > 4 else ""
        return "Traduções na comunidade (baixe na página do grupo e use em 📀 Aplicar patch):\n" + "\n".join(linhas) + \
            mais

    # ------------------------------------------------------------------ os botões
    def _abrir(self, modo: str | None) -> None:
        jogo = self.selecionado() or self.escolhido
        if jogo is not None:
            self.acoes["abrir"](jogo, modo)

    def _com_escolhido(self, acao: str) -> None:
        jogo = self.selecionado() or self.escolhido
        if jogo is not None:
            self.acoes[acao](jogo)
