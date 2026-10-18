"""Aba "🎮 Jogos" da janela moderna: aplicar o patch de fãs (tradução, dublagem) na ISO do SEU disco, numa cópia que
roda em qualquer lugar (PS2 pelo OPL, PCSX2, celular), e criar o patch da sua própria tradução. Só a tela fica
aqui; o trabalho fica em jellyfin_tools/patch_jogo.py e a ligação com a janela em jogos_moderna.py.

Quatro cartões, de cima para baixo: 1. Jogo (a ISO e a impressão digital), 2. Patch (o .xdelta/.ppf, o que o
leia-me pede e se bate com a sua ISO), 3. Aplicar (onde salvar e o nome, no padrão do OPL se quiser) e "Compartilhar
a sua tradução" (criar o .xdelta: só as diferenças, sem o jogo).
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path

import customtkinter as ctk

from jellyfin_tools import patch_jogo as pj

from .gui_moderna import Tema


class PainelJogos(ctk.CTkScrollableFrame):
    """A aba inteira (rola quando a tela é baixa). acoes: {'escolher_iso', 'ler_iso', 'conferir', 'escolher_patch',
    'ler_patch', 'procurar', 'escolher_pasta', 'aplicar', 'abrir_pasta', 'escolher_original',
    'escolher_modificada', 'criar'} (sem argumentos)."""

    def __init__(self, pai, app, acoes: dict):
        super().__init__(pai, fg_color="transparent")
        self.app = app
        self.acoes = acoes
        self.info: pj.InfoISO | None = None
        self.digital: pj.Digital | None = None           # a impressão digital da ISO escolhida (se conferida)
        self.esperado: pj.Esperado | None = None         # o que o leia-me do patch pede
        self.tipo_patch = ""
        self.ultimo: Path | None = None                  # a última ISO nova (para "Abrir a pasta")
        self._pequeno = ctk.CTkFont(Tema.FAMILIA, 11)
        self.grid_columnconfigure(0, weight=1)
        m = app
        aviso = m._rotulo(self, "Aplicar o patch de fãs (tradução, dublagem) na ISO do SEU disco: a ISO nova roda "
                                "em qualquer lugar (no PS2 pelo OPL, no PCSX2, no celular). O Maestro não baixa "
                                "jogos; a busca na comunidade procura só patches.", fonte=self._pequeno)
        aviso.grid(row=0, column=0, sticky="w", padx=(28, 16), pady=(12, 0))
        self._montar_jogo()
        self._montar_patch()
        self._montar_aplicar()
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

    def _linha_campo(self, cartao, linha: int, rotulo: str, dica: str, acao: str | None,
                     texto_botao: str = "Escolher...") -> tuple[tk.StringVar, ctk.CTkButton | None]:
        m = self.app
        m._rotulo(cartao, rotulo, suave=False).grid(row=linha, column=0, padx=(20, 10), pady=4, sticky="w")
        var = tk.StringVar(self)
        m._entrada(cartao, var, dica).grid(row=linha, column=1, sticky="ew", pady=4)
        botao = None
        if acao:
            botao = m._botao(cartao, texto_botao, self.acoes[acao], largura=130)
            botao.grid(row=linha, column=2, padx=(10, 20), pady=4)
        return var, botao

    def _quadro_info(self, cartao, linha: int, campos: list[tuple[str, str]]) -> dict[str, ctk.CTkLabel]:
        """O quadro de informações (rótulo à esquerda, valor à direita), como no protótipo."""
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

    def _montar_jogo(self) -> None:
        m = self.app
        cartao = self._cartao(1, "1. Jogo", "a ISO tirada do SEU disco (.iso; .bin de CD)")
        self.var_iso, self.bt_escolher_iso = self._linha_campo(cartao, 1, "ISO:", "o caminho da ISO do seu disco",
                                                               "escolher_iso")
        self.info_jogo = self._quadro_info(cartao, 2, [("jogo", "Jogo"), ("digital", "Impressão digital")])
        linha = ctk.CTkFrame(cartao, fg_color="transparent")
        linha.grid(row=3, column=0, columnspan=3, sticky="ew", padx=20, pady=(4, 14))
        self.bt_conferir_iso = m._botao(linha, "🔍  Conferir a impressão digital", self.acoes["conferir"])
        self.bt_conferir_iso.pack(side="left")
        m._rotulo(linha, "   CRC32/MD5/SHA-1: muda se um único byte mudar (o leia-me do patch diz qual é a certa). "
                         "Na ISO de DVD leva ~1 minuto.", fonte=self._pequeno).pack(side="left")

    def _montar_patch(self) -> None:
        m = self.app
        cartao = self._cartao(2, "2. Patch", "o .xdelta ou .ppf do grupo de tradução (com o leia-me ao lado)")
        self.var_patch, self.bt_escolher_patch = self._linha_campo(cartao, 1, "Patch:", ".xdelta, .vcdiff ou .ppf",
                                                                   "escolher_patch")
        self.info_patch = self._quadro_info(cartao, 2, [("patch", "Patch"), ("pede", "O leia-me pede"),
                                                        ("bate", "Na sua ISO")])
        linha = ctk.CTkFrame(cartao, fg_color="transparent")
        linha.grid(row=3, column=0, columnspan=3, sticky="ew", padx=20, pady=(4, 14))
        self.bt_procurar_patch = m._botao(linha, "🔎  Procurar na comunidade", self.acoes["procurar"])
        self.bt_procurar_patch.pack(side="left")
        m._rotulo(linha, "   abre no navegador a busca de patches do jogo (PO.B.R.E e Romhacking.net). O download é "
                         "na página do grupo: dê os créditos.", fonte=self._pequeno).pack(side="left")

    def _montar_aplicar(self) -> None:
        m = self.app
        cartao = self._cartao(3, "3. Aplicar", "numa CÓPIA: a ISO original fica como está")
        self.var_pasta_saida, _ = self._linha_campo(cartao, 1, "Salvar em:", "a pasta da ISO nova (vazio: a mesma "
                                                    "da original)", "escolher_pasta")
        self.var_nome_saida, _ = self._linha_campo(cartao, 2, "Nome:", "o nome da ISO nova (ex.: Meu Jogo PT-BR)",
                                                   None)
        self.var_nome_saida.trace_add("write", lambda *_: self._mostrar_nome())
        self.var_nome_opl = tk.BooleanVar(self, value=True)
        self.cx_nome_opl = ctk.CTkCheckBox(
            cartao, text="No padrão do OPL (SLUS_209.46.Nome.iso): o OPL antigo só lista assim",
            variable=self.var_nome_opl, font=m.f_normal, text_color=Tema.TEXTO, fg_color=Tema.PRIMARIA,
            hover_color=Tema.PRIMARIA_HOVER, border_color=Tema.CAMPO_BORDA, checkbox_width=20, checkbox_height=20,
            corner_radius=6, border_width=2)
        self.cx_nome_opl.grid(row=3, column=0, columnspan=3, sticky="w", padx=20, pady=(4, 0))
        self.var_nome_opl.trace_add("write", lambda *_: self._mostrar_nome())
        self.lb_nome_final = m._rotulo(cartao, "", fonte=self._pequeno)
        self.lb_nome_final.grid(row=4, column=0, columnspan=3, sticky="w", padx=20, pady=(2, 0))
        linha = ctk.CTkFrame(cartao, fg_color="transparent")
        linha.grid(row=5, column=0, columnspan=3, sticky="ew", padx=20, pady=(8, 6))
        self.bt_aplicar_patch = m._botao(linha, "🧩  Aplicar o patch", self.acoes["aplicar"], "primario")
        self.bt_aplicar_patch.pack(side="left")
        self.bt_abrir_pasta_jogo = m._botao(linha, "Abrir a pasta", self.acoes["abrir_pasta"], "fantasma")
        self.bt_abrir_pasta_jogo.pack(side="left", padx=(8, 0))
        self.lb_resultado_patch = ctk.CTkLabel(cartao, text="", font=m.f_rotulo, text_color=Tema.TEXTO_SUAVE,
                                               anchor="w", justify="left", wraplength=1000)
        self.lb_resultado_patch.grid(row=6, column=0, columnspan=3, sticky="w", padx=20, pady=(2, 14))

    def _montar_criar(self) -> None:
        m = self.app
        cartao = self._cartao(4, "Compartilhar a sua tradução", "crie o patch: só as diferenças, sem o jogo")
        self.var_criar_original, _ = self._linha_campo(cartao, 1, "ISO original:", "a do seu disco, sem mudar nada",
                                                       "escolher_original")
        self.var_criar_modificada, _ = self._linha_campo(cartao, 2, "ISO modificada:", "a com a sua tradução ou "
                                                         "dublagem já dentro", "escolher_modificada")
        self.var_criar_descricao, _ = self._linha_campo(cartao, 3, "Descrição:", "ex.: Meu Jogo PT-BR v1.0 · Grupo "
                                                        "Exemplo", None)
        linha = ctk.CTkFrame(cartao, fg_color="transparent")
        linha.grid(row=4, column=0, columnspan=3, sticky="ew", padx=20, pady=(8, 6))
        self.bt_criar_patch = m._botao(linha, "📦  Criar o patch (.xdelta)", self.acoes["criar"])
        self.bt_criar_patch.pack(side="left")
        m._rotulo(linha, "   vai junto um leia-me com a impressão digital da original. Compartilhe só o patch, "
                         "nunca a ISO.", fonte=self._pequeno).pack(side="left")
        self.lb_criado = ctk.CTkLabel(cartao, text="", font=m.f_rotulo, text_color=Tema.TEXTO_SUAVE, anchor="w",
                                      justify="left", wraplength=1000)
        self.lb_criado.grid(row=5, column=0, columnspan=3, sticky="w", padx=20, pady=(2, 14))

    # ------------------------------------------------------------------ o que a tela mostra
    def mostrar_jogo(self, info: pj.InfoISO | None, erro: str = "") -> None:
        self.info, self.digital = info, None
        self.info_jogo["jogo"].configure(text=info.descrever() if info else (erro or "—"),
                                         text_color=Tema.TEXTO if info and info.id_jogo else Tema.AVISO
                                         if info or erro else Tema.TEXTO)
        self.info_jogo["digital"].configure(text="ainda não conferida", text_color=Tema.TEXTO_SUAVE)
        if info and not self.var_nome_saida.get().strip():
            self.var_nome_saida.set(f"{info.caminho.stem} PT-BR")
        self._mostrar_bate()
        self._mostrar_nome()
        self._atualizar()

    def mostrar_digital(self, digital: pj.Digital) -> None:
        self.digital = digital
        self.info_jogo["digital"].configure(text=f"CRC32 {digital.crc32} · MD5 {digital.md5}",
                                            text_color=Tema.TEXTO)
        self._mostrar_bate()

    def mostrar_patch(self, tipo: str, descricao: str, esperado: pj.Esperado | None, erro: str = "") -> None:
        self.tipo_patch, self.esperado = tipo, esperado
        if erro:
            self.info_patch["patch"].configure(text=erro, text_color=Tema.AVISO)
        else:
            self.info_patch["patch"].configure(text=descricao, text_color=Tema.TEXTO)
        pede = []
        if esperado and esperado.ids:
            pede.append("jogo " + ", ".join(sorted(esperado.ids)))
        if esperado and esperado.tem_digital():
            pede.append(esperado.descrever())
        self.info_patch["pede"].configure(
            text=(" · ".join(pede) + f"  ({', '.join(esperado.arquivos)})") if pede else
            "o leia-me não diz a impressão digital da ISO certa" if tipo else "—",
            text_color=Tema.TEXTO if pede else Tema.TEXTO_SUAVE)
        self._mostrar_bate()
        self._atualizar()

    def _mostrar_bate(self) -> None:
        """✓ / ✗ / ? : a ISO escolhida é a versão que o patch pede?"""
        rotulo = self.info_patch["bate"]
        e, info = self.esperado, self.info
        if not self.tipo_patch or info is None:
            rotulo.configure(text="—", text_color=Tema.TEXTO_SUAVE)
            return
        if e and e.ids and info.id_jogo and info.id_jogo not in e.ids:
            rotulo.configure(text=f"✗ o patch é de {', '.join(sorted(e.ids))} e a sua ISO é {info.id_jogo} (outra "
                                  "versão ou outro jogo)", text_color=Tema.PERIGO)
        elif e and e.tem_digital() and self.digital is not None:
            if e.confere(self.digital):
                rotulo.configure(text="✓ encaixa: a impressão digital bate com o leia-me", text_color=Tema.SUCESSO)
            else:
                rotulo.configure(text="✗ não encaixa: a impressão digital é de outra versão (o Maestro não aplica)",
                                 text_color=Tema.PERIGO)
        elif e and e.tem_digital():
            rotulo.configure(text="? confira a impressão digital da ISO (o \"Aplicar\" confere antes de mexer)",
                             text_color=Tema.AVISO)
        else:
            confere = "o xdelta3 confere sozinho ao aplicar" if self.tipo_patch == pj.XDELTA else \
                "o .ppf confere um pedaço da ISO ao aplicar (se trouxer)"
            rotulo.configure(text=f"sem a impressão digital no leia-me: {confere}", text_color=Tema.TEXTO_SUAVE)

    def nome_final(self) -> str:
        nome = self.var_nome_saida.get().strip() or (f"{self.info.caminho.stem} PT-BR" if self.info else "")
        if not nome:
            return ""
        if self.var_nome_opl.get() and self.info is not None:
            return pj.nome_para_o_opl(self.info, nome)
        return nome if nome.lower().endswith(".iso") else f"{nome}.iso"

    def pasta_saida(self) -> Path | None:
        pasta = self.var_pasta_saida.get().strip()
        if pasta:
            return Path(pasta)
        return self.info.caminho.parent if self.info else None

    def _mostrar_nome(self) -> None:
        nome, pasta = self.nome_final(), self.pasta_saida()
        self.lb_nome_final.configure(text=f"A ISO nova: {pasta / nome}" if nome and pasta else "")

    def mostrar_resultado(self, r: pj.Resultado) -> None:
        self.ultimo = r.destino
        dica = "  Em pendrive FAT32 (4 GB por arquivo), divida com o USBUtil ou use exFAT (OPL novo)." \
            if r.info.tamanho > 4 * 1024 ** 3 - 1 else ""
        self.lb_resultado_patch.configure(
            text=f"✓ Pronta: {r.destino.name} ({r.info.id_jogo or '?'} · {pj.tamanho_legivel(r.info.tamanho)} · "
                 f"{r.conferido}). Copie para a pasta DVD (ou CD) do OPL, ou abra no PCSX2.{dica}",
            text_color=Tema.SUCESSO)
        self._atualizar()

    def mostrar_criado(self, patch: Path) -> None:
        self.lb_criado.configure(text=f"✓ Patch criado: {patch.name} ({pj.tamanho_legivel(patch.stat().st_size)}) "
                                      f"+ o leia-me, em {patch.parent}", text_color=Tema.SUCESSO)

    def _atualizar(self) -> None:
        pronto = self.info is not None and bool(self.tipo_patch)
        self.bt_aplicar_patch.configure(state="normal" if pronto else "disabled")
        self.bt_conferir_iso.configure(state="normal" if self.info is not None else "disabled")
        self.bt_abrir_pasta_jogo.configure(state="normal" if self.ultimo else "disabled")
