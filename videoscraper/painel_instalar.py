"""Aba "🎮 Jogos", modo "📦 Instalar a tradução" (Nintendo Switch e PC), como no protótipo: 1. a tradução (o mod
do Switch, com o TitleID, ou os arquivos da tradução do PC; e "Procurar na comunidade"), 2. onde instalar (a pasta de
mods do emulador ou o cartão SD com Atmosphère; no PC, a pasta do jogo), 3. instalar (e "Traduções instaladas" para
desfazer) e "Compartilhar a sua tradução" (o mod .zip ou o pacote .zip). Só a tela fica aqui; o trabalho fica em
jellyfin_tools/instalar_traducao.py e a ligação com a janela em instalar_moderna.py.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path

import customtkinter as ctk

from jellyfin_tools import consoles as cs
from jellyfin_tools import instalar_traducao as it
from jellyfin_tools import patch_jogo as pj

from .gui_moderna import Tema

ONDES_SWITCH = {it.EMULADOR: "Emulador (pasta de mods)", it.SD: "Cartão SD do Switch (Atmosphère)"}


class PainelInstalar(ctk.CTkScrollableFrame):
    """acoes: {'escolher_zip', 'escolher_pasta', 'procurar', 'escolher_destino', 'instalar', 'instaladas',
    'abrir_destino', 'abrir_emulador', 'criar_escolher', 'criar_escolher_original', 'criar'} (sem argumentos) e
    'trocou_onde' (opcional: recebe it.EMULADOR ou it.SD)."""

    def __init__(self, pai, app, acoes: dict, console: cs.Console):
        super().__init__(pai, fg_color="transparent")
        self.app, self.acoes, self.console = app, acoes, console
        self.switch = console.chave == "SWITCH"
        self.pacote: it.Pacote | None = None
        self.ultimo: Path | None = None                  # a pasta da última instalação (para "Abrir a pasta")
        self._pequeno = ctk.CTkFont(Tema.FAMILIA, 11)
        self.grid_columnconfigure(0, weight=1)
        m = app
        m._rotulo(self, (f"{console.nome}: instalar o mod de tradução no emulador ou no cartão SD. O jogo não muda e "
                         "\"Desfazer\" tira o mod.") if self.switch else
                  f"{console.nome}: instalar os arquivos da tradução na pasta do jogo. Os originais ficam guardados "
                  "e \"Desfazer\" devolve tudo. O Maestro não baixa jogos nem traduções: só os arquivos que você "
                  "escolhe.", fonte=self._pequeno).grid(row=0, column=0, sticky="w", padx=(28, 16), pady=(12, 0))
        self._montar_traducao()
        self._montar_destino()
        self._montar_instalar()
        self._montar_criar()
        self._atualizar()

    # ------------------------------------------------------------------ montagem
    def _cartao(self, linha: int, titulo: str, dica: str) -> ctk.CTkFrame:
        m = self.app
        cartao = m._cartao(self)
        cartao.grid(row=linha, column=0, sticky="ew", padx=(28, 16), pady=(12, 0))
        cartao.grid_columnconfigure(1, weight=1)
        topo = ctk.CTkFrame(cartao, fg_color="transparent")
        topo.grid(row=0, column=0, columnspan=3, sticky="ew", padx=20, pady=(12, 6))
        m._rotulo(topo, titulo, suave=False, fonte=m.f_secao).pack(side="left")
        m._rotulo(topo, "   " + dica, fonte=self._pequeno).pack(side="left", pady=(3, 0))
        return cartao

    def _campo(self, cartao, linha: int, rotulo: str, dica: str, botoes: list[tuple[str, str]]) -> tk.StringVar:
        m = self.app
        m._rotulo(cartao, rotulo, suave=False).grid(row=linha, column=0, padx=(20, 10), pady=4, sticky="w")
        var = tk.StringVar(self)
        m._entrada(cartao, var, dica).grid(row=linha, column=1, sticky="ew", pady=4)
        caixa = ctk.CTkFrame(cartao, fg_color="transparent")
        caixa.grid(row=linha, column=2, padx=(10, 20), pady=4)
        for texto, acao in botoes:
            m._botao(caixa, texto, self.acoes[acao], largura=130).pack(side="left", padx=(0, 6))
        return var

    def _montar_traducao(self) -> None:
        m = self.app
        cartao = self._cartao(1, "1. O mod de tradução" if self.switch else "1. A tradução",
                              "a pasta ou o .zip do grupo de tradução (com romfs e o TitleID do jogo)" if self.switch
                              else "a pasta ou o .zip com os arquivos traduzidos do jogo")
        self.var_origem = self._campo(cartao, 1, "Mod:" if self.switch else "Tradução:", "a pasta ou o .zip",
                                      [("Escolher .zip", "escolher_zip"), ("Escolher pasta", "escolher_pasta")])
        quadro = ctk.CTkFrame(cartao, fg_color=Tema.CAMPO, corner_radius=Tema.RAIO_CONTROLE)
        quadro.grid(row=2, column=0, columnspan=3, sticky="ew", padx=20, pady=(6, 4))
        quadro.grid_columnconfigure(1, weight=1)
        self.info: dict[str, ctk.CTkLabel] = {}
        campos = [("traducao", "Tradução"), ("traz", "Traz"), ("leia", "Leia-me")]
        for i, (chave, rotulo) in enumerate(campos):
            ctk.CTkLabel(quadro, text=rotulo, font=self._pequeno, text_color=Tema.TEXTO_SUAVE, anchor="w",
                         width=120).grid(row=i, column=0, sticky="w", padx=(14, 6), pady=3)
            self.info[chave] = ctk.CTkLabel(quadro, text="—", font=m.f_rotulo, text_color=Tema.TEXTO, anchor="w",
                                            justify="left", wraplength=900)
            self.info[chave].grid(row=i, column=1, sticky="w", padx=(0, 14), pady=3)
        self.var_title_id = tk.StringVar(self)
        linha = 3
        if self.switch:
            m._rotulo(cartao, "TitleID:", suave=False).grid(row=linha, column=0, padx=(20, 10), pady=4, sticky="w")
            m._entrada(cartao, self.var_title_id, "0100... (16 letras e números; lido do mod, ou veja nas "
                                                  "propriedades do jogo no emulador)").grid(row=linha, column=1,
                                                                                            sticky="ew", pady=4)
            self.var_title_id.trace_add("write", lambda *_: self.mostrar_destino())
            linha += 1
        faixa = ctk.CTkFrame(cartao, fg_color="transparent")
        faixa.grid(row=linha, column=0, columnspan=3, sticky="ew", padx=20, pady=(4, 14))
        self.bt_procurar = m._botao(faixa, "🔎  Procurar na comunidade", self.acoes["procurar"], "primario")
        self.bt_procurar.pack(side="left")
        m._rotulo(faixa, "   a lista das traduções do jogo (PO.B.R.E, fórum romhacking.net.br; Romhacking.net e "
                         "itch.io no navegador). Dê os créditos ao grupo.", fonte=self._pequeno).pack(side="left")

    def _montar_destino(self) -> None:
        m = self.app
        cartao = self._cartao(2, "2. Onde instalar", "no emulador (a pasta de mods) ou no cartão SD do Switch "
                                                     "(Atmosphère)" if self.switch else "a pasta onde o jogo está "
                                                     "instalado")
        self.var_onde = tk.StringVar(self, value=it.EMULADOR)
        linha = 1
        if self.switch:
            self.seletor_onde = ctk.CTkSegmentedButton(
                cartao, values=list(ONDES_SWITCH.values()), command=lambda v: self._escolheu_onde(v), height=30,
                font=m.f_normal, fg_color=Tema.CARTAO, selected_color=Tema.PRIMARIA,
                selected_hover_color=Tema.PRIMARIA_HOVER, unselected_color=Tema.CAMPO,
                unselected_hover_color=Tema.SECUNDARIA_HOVER, text_color=Tema.TEXTO)
            self.seletor_onde.set(ONDES_SWITCH[it.EMULADOR])
            self.seletor_onde.grid(row=1, column=0, columnspan=3, sticky="w", padx=20, pady=(0, 6))
            linha = 2
        self.var_destino = self._campo(cartao, linha, "Pasta:" if self.switch else "Pasta do jogo:",
                                       "a pasta de mods do emulador (ex.: ...\\mods\\contents) ou a raiz do cartão SD"
                                       if self.switch else "ex.: C:\\Jogos\\Meu Jogo", [("Escolher", "escolher_destino")])
        self.var_destino.trace_add("write", lambda *_: self.mostrar_destino())
        self.lb_vai_para = m._rotulo(cartao, "", fonte=self._pequeno)
        self.lb_vai_para.grid(row=linha + 1, column=0, columnspan=3, sticky="w", padx=20, pady=(2, 14))

    def _montar_instalar(self) -> None:
        m = self.app
        cartao = self._cartao(3, "3. Instalar", "copia a tradução para o lugar certo; Desfazer apaga só o que o "
                                                "Maestro copiou e devolve os originais")
        linha = ctk.CTkFrame(cartao, fg_color="transparent")
        linha.grid(row=1, column=0, columnspan=3, sticky="ew", padx=20, pady=(0, 6))
        self.bt_instalar = m._botao(linha, "📦  Instalar a tradução", self.acoes["instalar"], "primario")
        self.bt_instalar.pack(side="left")
        self.bt_instaladas = m._botao(linha, "🗂  Traduções instaladas (Desfazer)", self.acoes["instaladas"],
                                      "fantasma")
        self.bt_instaladas.pack(side="left", padx=(8, 0))
        self.bt_abrir_destino = m._botao(linha, "Abrir a pasta", self.acoes["abrir_destino"], "fantasma")
        self.bt_abrir_destino.pack(side="left", padx=(8, 0))
        if self.switch:
            self.bt_abrir_emulador = m._botao(linha, "▶  Abrir o emulador", self.acoes["abrir_emulador"], "fantasma")
            self.bt_abrir_emulador.pack(side="left", padx=(8, 0))
        self.barra = ctk.CTkProgressBar(linha, width=200, height=8, corner_radius=4, mode="determinate",
                                        fg_color=Tema.SECUNDARIA, progress_color=Tema.SUCESSO)
        self.barra.set(0)
        self.barra.pack(side="right")
        self.lb_resultado = ctk.CTkLabel(cartao, text="", font=m.f_rotulo, text_color=Tema.TEXTO_SUAVE, anchor="w",
                                         justify="left", wraplength=1000)
        self.lb_resultado.grid(row=2, column=0, columnspan=3, sticky="w", padx=20, pady=(2, 14))

    def _montar_criar(self) -> None:
        m = self.app
        cartao = self._cartao(4, "Compartilhar a sua tradução", "o mod (.zip) com o TitleID: só os arquivos "
                                                               "traduzidos, sem o jogo" if self.switch else
                              "o pacote (.zip) só com os arquivos novos ou diferentes: nada do jogo vai junto")
        self.var_criar_pasta = self._campo(cartao, 1, "Arquivos traduzidos:" if self.switch else "Jogo traduzido:",
                                           "a pasta romfs (ou a que tem romfs/exefs) com só o que você traduziu"
                                           if self.switch else "a pasta do jogo (ou uma cópia) com a sua tradução",
                                           [("Escolher", "criar_escolher")])
        self.var_criar_original = tk.StringVar(self)
        linha = 2
        if not self.switch:
            self.var_criar_original = self._campo(cartao, 2, "Jogo original:", "(opcional) uma cópia sem tradução: "
                                                  "só o que mudou entra no pacote",
                                                  [("Escolher", "criar_escolher_original")])
            linha = 3
        m._rotulo(cartao, "Descrição:", suave=False).grid(row=linha, column=0, padx=(20, 10), pady=4, sticky="w")
        self.var_criar_descricao = tk.StringVar(self)
        m._entrada(cartao, self.var_criar_descricao, "ex.: Meu Jogo PT-BR v1.0 · Grupo Exemplo").grid(
            row=linha, column=1, sticky="ew", pady=4)
        faixa = ctk.CTkFrame(cartao, fg_color="transparent")
        faixa.grid(row=linha + 1, column=0, columnspan=3, sticky="ew", padx=20, pady=(8, 6))
        self.bt_criar = m._botao(faixa, "📦  Criar o mod (.zip)" if self.switch else "📦  Criar o pacote (.zip)",
                                 self.acoes["criar"])
        self.bt_criar.pack(side="left")
        m._rotulo(faixa, "   vai junto um leia-me de como instalar. Compartilhe só a tradução, nunca o jogo.",
                  fonte=self._pequeno).pack(side="left")
        self.lb_criado = ctk.CTkLabel(cartao, text="", font=m.f_rotulo, text_color=Tema.TEXTO_SUAVE, anchor="w",
                                      justify="left", wraplength=1000)
        self.lb_criado.grid(row=linha + 2, column=0, columnspan=3, sticky="w", padx=20, pady=(2, 14))

    # ------------------------------------------------------------------ o que a tela mostra
    def _escolheu_onde(self, texto: str) -> None:
        self.var_onde.set(next(k for k, v in ONDES_SWITCH.items() if v == texto))
        if "trocou_onde" in self.acoes:                 # (cada lugar lembra a sua pasta)
            self.acoes["trocou_onde"](self.var_onde.get())
        self.mostrar_destino()

    def onde(self) -> str:
        return self.var_onde.get()

    def mostrar_pacote(self, pacote: it.Pacote | None, erro: str = "") -> None:
        self.pacote = pacote
        if pacote is None:
            self.info["traducao"].configure(text=erro or "—", text_color=Tema.AVISO if erro else Tema.TEXTO)
            self.info["traz"].configure(text="—")
            self.info["leia"].configure(text="—")
        else:
            n = len(pacote.arquivos)
            self.info["traducao"].configure(text=f"{pacote.nome}  ·  {n} arquivo{'s' if n != 1 else ''} · "
                                                 f"{pj.tamanho_legivel(pacote.tamanho)}", text_color=Tema.TEXTO)
            if self.switch:
                traz = " · ".join({"romfs": "romfs (textos e imagens)", "exefs": "exefs (código)"}[p]
                                  for p in pacote.partes)
                if pacote.title_id:
                    self.var_title_id.set(pacote.title_id)
                    traz += f"  ·  TitleID {pacote.title_id} (lido do mod)"
                else:
                    traz += "  ·  sem o TitleID no mod: escreva o do jogo no campo abaixo"
            else:
                pastas = sorted({pacote.destino_de(c).split("/")[0] for c in pacote.arquivos if "/" in
                                 pacote.destino_de(c)})
                traz = f"{n} arquivo{'s' if n != 1 else ''} para a pasta do jogo" + (
                    f" (em {', '.join(pastas[:4])}{'...' if len(pastas) > 4 else ''})" if pastas else "")
            self.info["traz"].configure(text=traz, text_color=Tema.TEXTO)
            primeira = next((linha.strip() for linha in pacote.leia_me.splitlines() if linha.strip()), "")
            self.info["leia"].configure(text=f"\"{primeira[:140]}\"" if primeira else "não veio leia-me",
                                        text_color=Tema.TEXTO if primeira else Tema.TEXTO_SUAVE)
        self.mostrar_destino()

    def destino(self) -> Path | None:
        """A pasta final (no Switch, já com o TitleID e o nome do mod); None se falta algo."""
        pasta = self.var_destino.get().strip()
        if not pasta or self.pacote is None:
            return None
        if not self.switch:
            return Path(pasta)
        try:
            return it.destino_do_mod(self.pacote, self.onde(), pasta, self.var_title_id.get().strip())
        except pj.ErroPatch:
            return None

    def mostrar_destino(self) -> None:
        destino = self.destino()
        if destino is not None:
            texto = f"Vai para: {destino}" + ("  (o jogo não muda)" if self.switch else
                                             "  (os arquivos que já existem ficam guardados para Desfazer)")
        elif self.switch and self.pacote is not None and self.var_destino.get().strip():
            texto = "Falta o TitleID do jogo (16 letras e números começando com 01)"
        else:
            texto = ""
        self.lb_vai_para.configure(text=texto)
        self._atualizar()

    def mostrar_andamento(self, fracao: float) -> None:
        self.barra.set(max(0.0, min(1.0, fracao)))

    def mostrar_resultado(self, texto: str, ok: bool = True) -> None:
        self.lb_resultado.configure(text=texto, text_color=Tema.SUCESSO if ok else Tema.AVISO)
        self._atualizar()

    def mostrar_criado(self, caminho: Path) -> None:
        self.lb_criado.configure(text=f"✓ Criado: {caminho.name} ({pj.tamanho_legivel(caminho.stat().st_size)}), em "
                                      f"{caminho.parent}", text_color=Tema.SUCESSO)

    def _atualizar(self) -> None:
        self.bt_instalar.configure(state="normal" if self.destino() is not None else "disabled")
        self.bt_abrir_destino.configure(state="normal" if self.ultimo or self.var_destino.get().strip() else
                                        "disabled")
