"""Aba "🎮 Jogos", modo "Aplicar patch de fãs": aplicar o patch de fãs (tradução, dublagem) na ISO do SEU disco, numa
cópia que roda em qualquer lugar (PS2 pelo OPL, PCSX2, celular), e criar o patch da sua própria tradução. Só a tela
fica aqui; o trabalho fica em jellyfin_tools/patch_jogo.py e a ligação com a janela em jogos_moderna.py.

Como no protótipo: 1. Jogo (o console, o código do disco, a região e a impressão digital, conferida no banco
Redump), 2. Patch (.xdelta/.ppf/.ips/.bps: o formato, para qual versão foi feito, se encaixa, o que traz e os
créditos, pelo leia-me; "Procurar na comunidade" lista os patches do jogo), 3. Aplicar (numa cópia, com o nome do
OPL; conferir a cópia no fim, abrir no PCSX2, os patches aplicados), "Compartilhar a sua tradução" (o .xdelta) e
"Enquanto joga" (os atalhos do tradutor de tela e da legenda ao vivo).
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path

import customtkinter as ctk

from jellyfin_tools import patch_jogo as pj

from .gui_moderna import Tema

CONSOLES = {"PS2": "PlayStation 2", "PS1": "PlayStation"}
REGIOES_TV = {"EUA": "NTSC-U (EUA)", "Europa": "PAL (Europa)", "Japão": "NTSC-J (Japão)", "Coreia": "NTSC-K (Coreia)",
              "Ásia": "NTSC (Ásia)"}


class PainelJogos(ctk.CTkScrollableFrame):
    """O modo inteiro (rola quando a tela é baixa). acoes: {'escolher_iso', 'ler_iso', 'conferir', 'escolher_patch',
    'ler_patch', 'procurar', 'abrir_leia_me', 'escolher_pasta', 'aplicar', 'abrir_pasta', 'abrir_pcsx2',
    'aplicados', 'escolher_original', 'escolher_modificada', 'criar', 'tela', 'legenda'} (sem argumentos)."""

    def __init__(self, pai, app, acoes: dict):
        super().__init__(pai, fg_color="transparent")
        self.app = app
        self.acoes = acoes
        self.info: pj.InfoISO | None = None
        self.digital: pj.Digital | None = None           # a impressão digital da ISO escolhida (se conferida)
        self.redump = ""                                 # o nome do disco no banco Redump ("" = não achou / não viu)
        self.esperado: pj.Esperado | None = None         # o que o leia-me do patch pede
        self.leia_me: pj.LeiaMe | None = None
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
        self._montar_enquanto()
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
        self._quadro = quadro
        return valores

    def _caixa(self, pai, texto: str, var: tk.BooleanVar) -> ctk.CTkCheckBox:
        m = self.app
        return ctk.CTkCheckBox(pai, text=texto, variable=var, font=m.f_normal, text_color=Tema.TEXTO,
                               fg_color=Tema.PRIMARIA, hover_color=Tema.PRIMARIA_HOVER, border_color=Tema.CAMPO_BORDA,
                               checkbox_width=20, checkbox_height=20, corner_radius=6, border_width=2)

    def _montar_jogo(self) -> None:
        m = self.app
        cartao = self._cartao(1, "1. Jogo", "a ISO feita do SEU disco: o Maestro lê o código do disco e confere a "
                                            "impressão digital")
        self.var_iso, self.bt_escolher_iso = self._linha_campo(cartao, 1, "ISO:", "o caminho da ISO do seu disco",
                                                               "escolher_iso")
        self.info_jogo = self._quadro_info(cartao, 2, [("console", "Console"), ("jogo", "Jogo"),
                                                       ("regiao", "Região"), ("digital", "Impressão digital")])
        linha = ctk.CTkFrame(cartao, fg_color="transparent")
        linha.grid(row=3, column=0, columnspan=3, sticky="ew", padx=20, pady=(4, 14))
        self.bt_conferir_iso = m._botao(linha, "🔍  Conferir a impressão digital", self.acoes["conferir"])
        self.bt_conferir_iso.pack(side="left")
        m._rotulo(linha, "   CRC32/MD5/SHA-1 e o banco Redump (os discos originais): muda se um único byte mudar. "
                         "Na ISO de DVD leva ~1 minuto.", fonte=self._pequeno).pack(side="left")

    def _montar_patch(self) -> None:
        m = self.app
        cartao = self._cartao(2, "2. Patch de tradução / dublagem", "o arquivo do grupo de tradução (.xdelta, .ppf, "
                                                                     ".ips, .bps): só as diferenças, sem o jogo")
        self.var_patch, self.bt_escolher_patch = self._linha_campo(cartao, 1, "Patch:", ".xdelta, .vcdiff, .ppf, "
                                                                   ".ips ou .bps", "escolher_patch")
        self.info_patch = self._quadro_info(cartao, 2, [("patch", "Formato"), ("pede", "Feito para"),
                                                        ("bate", "Encaixa?"), ("traz", "O que traz"),
                                                        ("creditos", "Créditos")])
        self.bt_leia_me = ctk.CTkButton(self._quadro, text="📄 Abrir o leia-me", command=self.acoes["abrir_leia_me"],
                                        width=140, height=26, corner_radius=6, fg_color="transparent",
                                        hover_color=Tema.SECUNDARIA_HOVER, text_color=Tema.TEXTO_SUAVE,
                                        font=self._pequeno)
        self.bt_leia_me.grid(row=4, column=2, padx=(0, 10), pady=3, sticky="e")
        linha = ctk.CTkFrame(cartao, fg_color="transparent")
        linha.grid(row=3, column=0, columnspan=3, sticky="ew", padx=20, pady=(4, 14))
        self.bt_procurar_patch = m._botao(linha, "🔎  Procurar na comunidade", self.acoes["procurar"], "primario")
        self.bt_procurar_patch.pack(side="left")
        m._rotulo(linha, "   a lista dos patches do jogo (PO.B.R.E, fórum romhacking.net.br; Romhacking.net e "
                         "itch.io no navegador). Só patches; dê os créditos ao grupo.",
                  fonte=self._pequeno).pack(side="left")

    def _montar_aplicar(self) -> None:
        m = self.app
        cartao = self._cartao(3, "3. Aplicar", "a ISO original nunca é alterada: o Maestro cria uma cópia já "
                                               "traduzida")
        self.var_pasta_saida, _ = self._linha_campo(cartao, 1, "Salvar em:", "a pasta da ISO nova (vazio: a mesma "
                                                    "da original)", "escolher_pasta")
        self.var_nome_saida, _ = self._linha_campo(cartao, 2, "Nome:", "o nome da ISO nova (ex.: Meu Jogo PT-BR)",
                                                   None)
        self.var_nome_saida.trace_add("write", lambda *_: self._mostrar_nome())
        self.var_nome_opl = tk.BooleanVar(self, value=True)
        self.cx_nome_opl = self._caixa(cartao, "No padrão do OPL (CÓDIGO.Nome.iso): o OPL antigo só lista assim",
                                       self.var_nome_opl)
        self.cx_nome_opl.grid(row=3, column=0, columnspan=3, sticky="w", padx=20, pady=(4, 0))
        self.var_nome_opl.trace_add("write", lambda *_: self._mostrar_nome())
        self.lb_nome_final = m._rotulo(cartao, "", fonte=self._pequeno)
        self.lb_nome_final.grid(row=4, column=0, columnspan=3, sticky="w", padx=20, pady=(2, 0))
        opcoes = ctk.CTkFrame(cartao, fg_color="transparent")
        opcoes.grid(row=5, column=0, columnspan=3, sticky="w", padx=20, pady=(6, 0))
        self.var_conferir_copia = tk.BooleanVar(self, value=True)
        self.cx_conferir_copia = self._caixa(opcoes, "Conferir a cópia no fim (impressão digital esperada pelo grupo)",
                                             self.var_conferir_copia)
        self.cx_conferir_copia.pack(side="left")
        self.var_abrir_pcsx2 = tk.BooleanVar(self, value=False)
        self.cx_abrir_pcsx2 = self._caixa(opcoes, "Abrir no PCSX2 quando terminar", self.var_abrir_pcsx2)
        self.cx_abrir_pcsx2.pack(side="left", padx=(18, 0))
        linha = ctk.CTkFrame(cartao, fg_color="transparent")
        linha.grid(row=6, column=0, columnspan=3, sticky="ew", padx=20, pady=(8, 6))
        self.bt_aplicar_patch = m._botao(linha, "🧩  Aplicar o patch", self.acoes["aplicar"], "primario")
        self.bt_aplicar_patch.pack(side="left")
        self.bt_abrir_pcsx2 = m._botao(linha, "▶  Abrir no PCSX2", self.acoes["abrir_pcsx2"])
        self.bt_abrir_pcsx2.pack(side="left", padx=(8, 0))
        self.bt_aplicados = m._botao(linha, "🗂  Patches aplicados", self.acoes["aplicados"], "fantasma")
        self.bt_aplicados.pack(side="left", padx=(8, 0))
        self.bt_abrir_pasta_jogo = m._botao(linha, "Abrir a pasta", self.acoes["abrir_pasta"], "fantasma")
        self.bt_abrir_pasta_jogo.pack(side="left", padx=(8, 0))
        self.barra = ctk.CTkProgressBar(linha, width=220, height=8, corner_radius=4, mode="determinate",
                                        fg_color=Tema.SECUNDARIA, progress_color=Tema.SUCESSO)
        self.barra.set(0)
        self.barra.pack(side="right")
        self.lb_barra = m._rotulo(linha, "", fonte=self._pequeno)
        self.lb_barra.pack(side="right", padx=(0, 8))
        self.lb_resultado_patch = ctk.CTkLabel(cartao, text="", font=m.f_rotulo, text_color=Tema.TEXTO_SUAVE,
                                               anchor="w", justify="left", wraplength=1000)
        self.lb_resultado_patch.grid(row=7, column=0, columnspan=3, sticky="w", padx=20, pady=(2, 14))

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

    def _montar_enquanto(self) -> None:
        m = self.app
        cartao = self._cartao(5, "Enquanto joga", "para qualquer jogo, por cima da janela do emulador (sem mexer na "
                                                  "ISO): o modo completo fica em \"Enquanto joga\"")
        linha = ctk.CTkFrame(cartao, fg_color="transparent")
        linha.grid(row=1, column=0, columnspan=3, sticky="ew", padx=20, pady=(2, 14))
        self.var_atalho_tela = tk.BooleanVar(self, value=False)
        self.sw_atalho_tela = ctk.CTkSwitch(linha, text="Traduzir o texto da tela", variable=self.var_atalho_tela,
                                            command=self.acoes["tela"], font=m.f_normal, text_color=Tema.TEXTO,
                                            progress_color=Tema.PRIMARIA)
        self.sw_atalho_tela.pack(side="left")
        self.var_atalho_legenda = tk.BooleanVar(self, value=False)
        self.sw_atalho_legenda = ctk.CTkSwitch(linha, text="Legenda ao vivo das vozes (Whisper na placa de vídeo)",
                                               variable=self.var_atalho_legenda, command=self.acoes["legenda"],
                                               font=m.f_normal, text_color=Tema.TEXTO, progress_color=Tema.PRIMARIA)
        self.sw_atalho_legenda.pack(side="left", padx=(24, 0))
        self.lb_janela_atalho = m._rotulo(linha, "", fonte=self._pequeno)
        self.lb_janela_atalho.pack(side="left", padx=(24, 0))

    # ------------------------------------------------------------------ o que a tela mostra
    def mostrar_jogo(self, info: pj.InfoISO | None, erro: str = "") -> None:
        self.info, self.digital, self.redump = info, None, ""
        if info is None:
            for chave in self.info_jogo:
                self.info_jogo[chave].configure(text="—", text_color=Tema.TEXTO)
            self.info_jogo["jogo"].configure(text=erro or "—", text_color=Tema.AVISO if erro else Tema.TEXTO)
        else:
            midia = "DVD" if info.tamanho > 900 * 1024 ** 2 else "CD"
            self.info_jogo["console"].configure(
                text=f"{CONSOLES.get(info.sistema, info.sistema or '?')}  ({midia} · {pj.tamanho_legivel(info.tamanho)})",
                text_color=Tema.TEXTO)
            self.info_jogo["jogo"].configure(
                text=(f"{info.caminho.stem}  ·  código do disco {info.id_jogo} (lido de dentro da ISO)"
                      + (f" · versão {info.versao}" if info.versao else "")) if info.id_jogo else info.descrever(),
                text_color=Tema.TEXTO if info.id_jogo else Tema.AVISO)
            self.info_jogo["regiao"].configure(text=REGIOES_TV.get(info.regiao, info.regiao or "—"),
                                               text_color=Tema.TEXTO)
        self.info_jogo["digital"].configure(text="ainda não conferida" if info else "—", text_color=Tema.TEXTO_SUAVE)
        if info and not self.var_nome_saida.get().strip():
            self.var_nome_saida.set(f"{info.caminho.stem} PT-BR")
        self.cx_nome_opl.configure(text=f"No padrão do OPL ({info.arquivo_boot}.Nome.iso): o OPL antigo só lista assim"
                                   if info and info.arquivo_boot else
                                   "No padrão do OPL (CÓDIGO.Nome.iso): o OPL antigo só lista assim")
        self._mostrar_bate()
        self._mostrar_nome()
        self._atualizar()

    def mostrar_digital(self, digital: pj.Digital, redump: str | None = None) -> None:
        """redump: o nome do disco no banco ("" = não está; None = não deu para consultar)."""
        self.digital = digital
        if redump is not None:
            self.redump = redump
        if redump:
            extra, cor = f"  ✓ cópia perfeita do disco (igual à do banco Redump: {redump})", Tema.SUCESSO
        elif redump == "":
            extra, cor = "  · não está no banco Redump (ISO modificada, ou disco que o banco ainda não tem)", Tema.AVISO
        else:
            extra, cor = "", Tema.TEXTO
        self.info_jogo["digital"].configure(text=f"CRC32 {digital.crc32} · MD5 {digital.md5[:12]}…{extra}",
                                            text_color=cor)
        self._mostrar_bate()

    def mostrar_patch(self, tipo: str, descricao: str, esperado: pj.Esperado | None, erro: str = "",
                      leia_me: pj.LeiaMe | None = None) -> None:
        self.tipo_patch, self.esperado, self.leia_me = tipo, esperado, leia_me
        if erro:
            self.info_patch["patch"].configure(text=erro, text_color=Tema.AVISO)
        else:
            self.info_patch["patch"].configure(text=descricao, text_color=Tema.TEXTO)
        pede = []
        if esperado and esperado.ids:
            pede.append(" · ".join(f"{i} ({pj.REGIOES.get(i[:4], '?')})" for i in sorted(esperado.ids)))
        if esperado and esperado.tem_digital():
            pede.append(esperado.descrever())
        self.info_patch["pede"].configure(
            text=(" · ".join(pede) + f"  ({', '.join(esperado.arquivos)})") if pede else
            "o leia-me não diz a versão nem a impressão digital da ISO certa" if tipo else "—",
            text_color=Tema.TEXTO if pede else Tema.TEXTO_SUAVE)
        traz = " · ".join(leia_me.o_que_traz) if leia_me and leia_me.o_que_traz else ""
        self.info_patch["traz"].configure(text=(traz + "  (pelo leia-me)") if traz else "—" if not tipo else
                                          "o leia-me não diz", text_color=Tema.TEXTO if traz else Tema.TEXTO_SUAVE)
        creditos = leia_me.creditos if leia_me else ""
        self.info_patch["creditos"].configure(
            text=(creditos + (f"  ({leia_me.arquivo.name} ao lado do patch)" if leia_me and leia_me.arquivo else ""))
            if creditos else ("—" if not tipo else "dê os créditos ao grupo que fez (veja o leia-me)"),
            text_color=Tema.TEXTO if creditos else Tema.TEXTO_SUAVE)
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
                rotulo.configure(text="✓ Sim: mesmo código, mesma região e mesma impressão digital da sua ISO",
                                 text_color=Tema.SUCESSO)
            else:
                rotulo.configure(text="✗ não encaixa: a impressão digital é de outra versão (o Maestro não aplica)",
                                 text_color=Tema.PERIGO)
        elif e and e.tem_digital():
            rotulo.configure(text="? confira a impressão digital da ISO (o \"Aplicar\" confere antes de mexer)",
                             text_color=Tema.AVISO)
        else:
            confere = {pj.XDELTA: "o xdelta3 confere sozinho ao aplicar", pj.BPS: "o .bps confere sozinho ao aplicar",
                       pj.PPF: "o .ppf confere um pedaço da ISO ao aplicar (se trouxer)"}.get(
                self.tipo_patch, "o .ips não tem como conferir: confira a versão no leia-me")
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

    def mostrar_andamento(self, fracao: float, texto: str = "") -> None:
        self.barra.set(max(0.0, min(1.0, fracao)))
        self.lb_barra.configure(text=texto or f"{fracao:.0%}")

    def mostrar_resultado(self, r: pj.Resultado, copia: str = "") -> None:
        """copia: o que a conferência da cópia no fim disse ("" = não conferiu)."""
        self.ultimo = r.destino
        dica = "  Em pendrive FAT32 (4 GB por arquivo), divida com o USBUtil ou use exFAT (OPL novo)." \
            if r.info.tamanho > 4 * 1024 ** 3 - 1 else ""
        self.mostrar_andamento(1.0, "100%")
        self.lb_resultado_patch.configure(
            text=f"✓ Pronto: cópia traduzida criada\n\"{r.destino.name}\" ({pj.tamanho_legivel(r.info.tamanho)} · "
                 f"{r.info.id_jogo or '?'}) · {copia or r.conferido} · a ISO original continua igual.\nCopie para a "
                 f"pasta DVD (ou CD) do OPL, ou abra no PCSX2. Fica registrado em 🗂 Patches aplicados (para refazer "
                 f"ou apagar a cópia depois).{dica}", text_color=Tema.SUCESSO)
        self._atualizar()

    def mostrar_criado(self, patch: Path) -> None:
        self.lb_criado.configure(text=f"✓ Patch criado: {patch.name} ({pj.tamanho_legivel(patch.stat().st_size)}) "
                                      f"+ o leia-me, em {patch.parent}", text_color=Tema.SUCESSO)

    def _atualizar(self) -> None:
        pronto = self.info is not None and bool(self.tipo_patch)
        self.bt_aplicar_patch.configure(state="normal" if pronto else "disabled")
        self.bt_conferir_iso.configure(state="normal" if self.info is not None else "disabled")
        self.bt_abrir_pasta_jogo.configure(state="normal" if self.ultimo else "disabled")
        self.bt_abrir_pcsx2.configure(state="normal" if self.ultimo or self.info is not None else "disabled")
        self.bt_leia_me.configure(state="normal" if self.leia_me and self.leia_me.arquivo else "disabled")
