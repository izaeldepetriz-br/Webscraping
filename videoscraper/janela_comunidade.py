"""A janela "🔎 Procurar na comunidade" da aba 🎮 Jogos (como no protótipo): a lista dos patches do jogo da sua ISO
(o banco do PO.B.R.E e o fórum romhacking.net.br), com o que cada um traz, para qual versão foi feito e se encaixa
na sua ISO. Só patches: a tradução distribuída como a ISO inteira fica escondida. O download é feito por você, na
página do grupo; depois, "Já baixei: usar o arquivo..." volta para a aba com o patch escolhido.
"""

from __future__ import annotations

import threading
import tkinter as tk
import webbrowser
from tkinter import ttk

import customtkinter as ctk

from jellyfin_tools import comunidade as cm

from .gui_moderna import Tema


class JanelaComunidade(ctk.CTkToplevel):
    """procurar(termos, onde, quer) -> comunidade.Resultado (roda numa tarefa). usar_arquivo(): o "Já baixei"."""

    def __init__(self, pai, titulo_jogo: str, termos: str, procurar, usar_arquivo, abrir=None):
        super().__init__(pai)
        self.app, self._procurar, self._usar_arquivo = pai, procurar, usar_arquivo
        self._abrir = abrir or (lambda endereco: webbrowser.open(endereco))
        self.resultado: cm.Resultado | None = None
        self._linhas: dict[str, object] = {}         # iid -> Achado ou (site, endereço) do navegador
        self.title(f"Procurar na comunidade · {titulo_jogo}")
        self.configure(fg_color=Tema.CARTAO)
        self.geometry("1180x700")
        self.minsize(900, 560)
        self.transient(pai)
        m = pai
        pequeno = ctk.CTkFont(Tema.FAMILIA, 11)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)
        topo = ctk.CTkFrame(self, fg_color="transparent")
        topo.grid(row=0, column=0, sticky="ew", padx=18, pady=(14, 6))
        topo.grid_columnconfigure(1, weight=1)
        m._rotulo(topo, "Procurar:", suave=False).grid(row=0, column=0, padx=(0, 8))
        self.var_termos = tk.StringVar(self, value=termos)
        campo = m._entrada(topo, self.var_termos, "o nome do jogo (e o código do disco)")
        campo.grid(row=0, column=1, sticky="ew")
        campo.bind("<Return>", lambda e: self.procurar())
        m._rotulo(topo, "Idioma:", suave=False).grid(row=0, column=2, padx=(14, 8))
        self.var_idioma = tk.StringVar(self, value="Português (Brasil)")
        m._menu_opcoes(topo, self.var_idioma, ["Português (Brasil)"]).grid(row=0, column=3)
        m._rotulo(topo, "Quer:", suave=False).grid(row=0, column=4, padx=(14, 8))
        self.var_quer = tk.StringVar(self, value=cm.QUER[0])
        m._menu_opcoes(topo, self.var_quer, cm.QUER).grid(row=0, column=5)
        self.bt_procurar = m._botao(topo, "Procurar", self.procurar, "primario", largura=120)
        self.bt_procurar.grid(row=0, column=6, padx=(14, 0))
        onde = ctk.CTkFrame(self, fg_color="transparent")
        onde.grid(row=1, column=0, sticky="ew", padx=18, pady=(2, 6))
        m._rotulo(onde, "Onde:", suave=False).pack(side="left", padx=(0, 8))
        self.vars_onde = {}
        for nome in cm.ONDES:
            var = tk.BooleanVar(self, value=True)
            self.vars_onde[nome] = var
            ctk.CTkCheckBox(onde, text=nome, variable=var, font=m.f_normal, text_color=Tema.TEXTO,
                            fg_color=Tema.PRIMARIA, hover_color=Tema.PRIMARIA_HOVER, border_color=Tema.CAMPO_BORDA,
                            checkbox_width=18, checkbox_height=18, corner_radius=5,
                            border_width=2).pack(side="left", padx=(0, 14))
        self.lb_situacao = m._rotulo(self, "", fonte=pequeno)
        self.lb_situacao.grid(row=2, column=0, sticky="w", padx=20)
        quadro = ctk.CTkFrame(self, fg_color=Tema.CARTAO, corner_radius=0)
        quadro.grid(row=3, column=0, sticky="nsew", padx=18, pady=(4, 6))
        quadro.grid_columnconfigure(0, weight=1)
        quadro.grid_rowconfigure(0, weight=1)
        colunas = [("onde", "Onde", 150, False), ("patch", "Patch (grupo · versão)", 420, True),
                   ("traz", "O que traz", 200, False), ("para", "Feito para", 170, False),
                   ("encaixa", "Na sua ISO", 300, True)]
        self.tabela = ttk.Treeview(quadro, columns=[c[0] for c in colunas], show="headings", selectmode="browse",
                                   style="Moderno.Treeview")
        for chave, texto, largura, estica in colunas:
            self.tabela.heading(chave, text=texto, anchor="w")
            self.tabela.column(chave, width=largura, minwidth=60, stretch=estica, anchor="w")
        self.tabela.grid(row=0, column=0, sticky="nsew")
        self.tabela.tag_configure("encaixa", background="#14301f")
        self.tabela.tag_configure("nao", background="#3a2a12")
        self.tabela.tag_configure("talvez", background=Tema.LINHA_PAR)
        self.tabela.tag_configure("navegador", background=Tema.LINHA_IMPAR, foreground=Tema.TEXTO_SUAVE)
        self.tabela.bind("<<TreeviewSelect>>", lambda e: self.mostrar_selecionado())
        self.tabela.bind("<Double-1>", lambda e: self.abrir_pagina())
        rolagem = ctk.CTkScrollbar(quadro, command=self.tabela.yview)
        rolagem.grid(row=0, column=1, sticky="ns")
        self.tabela.configure(yscrollcommand=rolagem.set)
        detalhes = ctk.CTkFrame(self, fg_color=Tema.CAMPO, corner_radius=Tema.RAIO_CONTROLE)
        detalhes.grid(row=4, column=0, sticky="ew", padx=18, pady=(4, 6))
        detalhes.grid_columnconfigure(1, weight=1)
        self.detalhe = {}
        for i, (chave, rotulo) in enumerate((("selecionado", "Selecionado"), ("encaixa", "Encaixa?"),
                                             ("custo", "Custo"), ("seguranca", "Segurança"))):
            ctk.CTkLabel(detalhes, text=rotulo, font=pequeno, text_color=Tema.TEXTO_SUAVE, width=110,
                         anchor="w").grid(row=i, column=0, sticky="w", padx=(14, 6), pady=3)
            self.detalhe[chave] = ctk.CTkLabel(detalhes, text="—", font=m.f_rotulo, text_color=Tema.TEXTO,
                                               anchor="w", justify="left", wraplength=980)
            self.detalhe[chave].grid(row=i, column=1, sticky="w", padx=(0, 14), pady=3)
        botoes = ctk.CTkFrame(self, fg_color="transparent")
        botoes.grid(row=5, column=0, sticky="ew", padx=18, pady=(2, 4))
        self.bt_abrir = m._botao(botoes, "🌐  Abrir a página do patch", self.abrir_pagina, "primario")
        self.bt_abrir.pack(side="left")
        self.bt_usar = m._botao(botoes, "📥  Já baixei: usar o arquivo...", self.usar_arquivo)
        self.bt_usar.pack(side="left", padx=(8, 0))
        m._botao(botoes, "Fechar", self.destroy, "fantasma").pack(side="right")
        m._rotulo(self, "O download é feito por você, na página do grupo (assim o crédito e as regras do site são "
                        "respeitados). Depois o Maestro confere e aplica.", fonte=pequeno).grid(
            row=6, column=0, sticky="w", padx=20, pady=(0, 12))
        self.bt_abrir.configure(state="disabled")
        self.after(100, self.procurar)

    # ------------------------------------------------------------------ procurar
    def procurar(self) -> None:
        onde = tuple(nome for nome, var in self.vars_onde.items() if var.get())
        self.bt_procurar.configure(state="disabled")
        self.lb_situacao.configure(text="Procurando...", text_color=Tema.TEXTO_SUAVE)
        termos, quer = self.var_termos.get(), self.var_quer.get()
        resposta: dict = {}

        def tarefa():
            try:
                resposta["r"] = self._procurar(termos, onde, quer)
            except Exception as erro:                    # sem internet etc.: diz na janela
                resposta["erro"] = str(erro)

        fio = threading.Thread(target=tarefa, daemon=True)
        fio.start()

        def esperar():
            if fio.is_alive():
                self.after(150, esperar)
                return
            if self.winfo_exists():
                self.mostrar(resposta.get("r"), resposta.get("erro", ""))
        self.after(150, esperar)

    def mostrar(self, r: cm.Resultado | None, erro: str = "") -> None:
        self.bt_procurar.configure(state="normal")
        self.resultado = r
        self.tabela.delete(*self.tabela.get_children())
        self._linhas.clear()
        if r is None:
            self.lb_situacao.configure(text=f"✗ Não deu para procurar: {erro}", text_color=Tema.PERIGO)
            return
        for i, a in enumerate(r.achados):
            tag = "encaixa" if a.ok() else "nao" if a.encaixa.startswith("⚠") else "talvez"
            iid = f"a{i}"
            self.tabela.insert("", "end", iid=iid, values=(a.onde, a.patch, " + ".join(a.traz), a.feito_para,
                                                           a.encaixa), tags=(tag,))
            self._linhas[iid] = a
        for site, endereco in r.no_navegador.items():
            iid = f"n{site}"
            self.tabela.insert("", "end", iid=iid, values=(site, "(o site não deixa programas procurar)", "—", "—",
                                                           "abrir a busca no navegador"), tags=("navegador",))
            self._linhas[iid] = (site, endereco)
        if r.achados:
            texto = f"{len(r.achados)} patch(es) achado(s)" + (f" · {sum(a.ok() for a in r.achados)} encaixa(m) na "
                                                              "sua ISO" if any(a.ok() for a in r.achados) else "")
            cor = Tema.SUCESSO if any(a.ok() for a in r.achados) else Tema.TEXTO
        else:
            texto, cor = ("Nenhum patch achado para este jogo nos sites que o Maestro lê. Veja os que abrem no "
                          "navegador, ou faça a sua tradução no modo \"Traduzir e dublar (no PC)\"."), Tema.AVISO
        if r.avisos:
            texto += "  ·  " + "; ".join(r.avisos)
        self.lb_situacao.configure(text=texto, text_color=cor)
        self.detalhe["seguranca"].configure(
            text=f"🛡 Só aparecem PATCHES. Links de jogo completo (ISO) são escondidos: {r.escondidos} escondido(s) "
                 "nesta busca.", text_color=Tema.AVISO)
        primeiro = next(iter(self.tabela.get_children()), "")
        if primeiro:
            self.tabela.selection_set(primeiro)
            self.tabela.focus(primeiro)
        self.mostrar_selecionado()

    def selecionado(self):
        item = self.tabela.focus() or next(iter(self.tabela.selection()), "")
        return self._linhas.get(item)

    def mostrar_selecionado(self) -> None:
        a = self.selecionado()
        if a is None:
            for chave in ("selecionado", "encaixa", "custo"):
                self.detalhe[chave].configure(text="—")
            self.bt_abrir.configure(state="disabled")
            return
        self.bt_abrir.configure(state="normal")
        if isinstance(a, tuple):
            self.detalhe["selecionado"].configure(text=f"{a[0]}: a busca abre no seu navegador")
            self.detalhe["encaixa"].configure(text="confira a versão e a impressão digital na página do patch",
                                              text_color=Tema.TEXTO_SUAVE)
        else:
            extra = " · ".join(p for p in (a.formato, f"{a.descricao[:160]}…" if len(a.descricao) > 160 else
                                           a.descricao) if p)
            self.detalhe["selecionado"].configure(text=f"{a.patch} · {extra}" if extra else a.patch)
            self.detalhe["encaixa"].configure(text=a.encaixa + ("  (o Maestro confere de novo quando você usar o "
                                                                "arquivo)" if a.ok() else ""),
                                              text_color=Tema.SUCESSO if a.ok() else Tema.AVISO
                                              if a.encaixa.startswith("⚠") else Tema.TEXTO)
        self.detalhe["custo"].configure(text="Grátis · trabalho voluntário do grupo: dê os créditos e, se quiser, "
                                             "apoie quem fez")

    def abrir_pagina(self) -> None:
        a = self.selecionado()
        if a is None:
            return
        self._abrir(a[1] if isinstance(a, tuple) else (a.pagina or a.site_do_grupo))

    def usar_arquivo(self) -> None:
        if self._usar_arquivo():
            self.destroy()
