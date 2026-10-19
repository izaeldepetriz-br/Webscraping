"""Aba "🎮 Jogos" na janela moderna, com os 3 modos do protótipo:

    📀 Aplicar patch de fãs              escolher a ISO e o patch (ou procurar na comunidade), conferir a impressão
                                         digital (e o banco Redump), aplicar numa cópia, abrir no PCSX2, criar o
                                         patch da sua tradução
    🗣 Traduzir e dublar (no PC)         dublar_jogos_moderna.py (o roteiro, a tradução, as vozes e a entrega)
    🖥 Enquanto joga (tradutor de tela)  enquanto_joga_moderna.py (o texto da tela e a legenda ao vivo)

Separado de app_moderna.py (como a aba Áudio): a AppModerna herda esta parte. As telas ficam em painel_jogos.py,
painel_dublar_jogo.py e painel_enquanto_joga.py; o trabalho em jellyfin_tools (patch_jogo, redump, comunidade...).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from jellyfin_tools import comunidade as cm
from jellyfin_tools import patch_jogo as pj
from jellyfin_tools import redump

from . import config
from .gui_moderna import Tema
from .painel_jogos import PainelJogos

TIPOS_ISO = [("Imagem do disco", "*.iso *.bin *.img"), ("Todos os arquivos", "*.*")]
TIPOS_PATCH = [("Patch de fãs", "*.xdelta *.vcdiff *.xd3 *.delta *.ppf *.ips *.bps"), ("Todos os arquivos", "*.*")]
TIPOS_PROGRAMA = [("Programa", "*.exe"), ("Todos os arquivos", "*.*")]
MODO_PATCH, MODO_DUBLAR, MODO_ENQUANTO = ("📀 Aplicar patch de fãs", "🗣 Traduzir e dublar (no PC)",
                                          "🖥 Enquanto joga (tradutor de tela)")
MODOS = (MODO_PATCH, MODO_DUBLAR, MODO_ENQUANTO)
SUBTITULOS_MODO = {
    MODO_PATCH: "1) Escolha a ISO do seu disco    2) Procure ou escolha o patch    3) Aplique",
    MODO_DUBLAR: "1) Abra o roteiro    2) Traduza    3) Duble no PC (XTTS-v2)    4) Entregue",
    MODO_ENQUANTO: "Para qualquer jogo, por cima da janela do emulador · sem mexer na ISO",
}


class PatchDeJogos:
    """Parte "🎮 Jogos" da AppModerna (usa self.fila, self._rodar, self.mostrar_mensagem... da janela)."""

    def _iniciar_jogos(self) -> None:
        self.painel_jogos = None                # montado na 1ª vez que a aba abre
        self.painel_dublar_jogo = None
        self.painel_enquanto_joga = None
        self.janela_comunidade = None
        self._modo_jogos = MODO_PATCH
        self._digitais: dict[tuple, pj.Digital] = {}   # (caminho, tamanho, data) -> impressão digital já medida
        for iniciar in ("_iniciar_dublar_jogo", "_iniciar_enquanto_joga"):
            if hasattr(self, iniciar):
                getattr(self, iniciar)()

    @property
    def pasta_ferramentas(self) -> Path:
        return config.ARQUIVO.parent / "ferramentas"

    @property
    def arquivo_aplicados(self) -> Path:
        return config.ARQUIVO.parent / "patches_aplicados.json"

    # ---- as preferências da aba (o modo, o PCSX2...): ficam num arquivo pequeno junto das configurações
    def preferencia_jogos(self, chave: str, padrao=None):
        try:
            return json.loads((config.ARQUIVO.parent / "jogos.json").read_text(encoding="utf-8")).get(chave, padrao)
        except (OSError, ValueError):
            return padrao

    def guardar_preferencia_jogos(self, chave: str, valor) -> None:
        arquivo = config.ARQUIVO.parent / "jogos.json"
        try:
            dados = json.loads(arquivo.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            dados = {}
        dados[chave] = valor
        try:
            arquivo.parent.mkdir(parents=True, exist_ok=True)
            arquivo.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            pass

    # ---- os 3 modos
    def ao_abrir_aba_jogos(self) -> None:
        if self.painel_jogos is None or not self.painel_jogos.winfo_exists():
            self.aba_jogos.grid_rowconfigure(0, weight=0)
            self.aba_jogos.grid_rowconfigure(1, weight=1)
            barra = ctk.CTkFrame(self.aba_jogos, fg_color="transparent")
            barra.grid(row=0, column=0, sticky="ew", padx=(28, 16), pady=(8, 0))
            self._rotulo(barra, "Modo:", suave=False).pack(side="left", padx=(0, 10))
            self.seletor_modo_jogos = ctk.CTkSegmentedButton(
                barra, values=list(MODOS), command=self.mostrar_modo_jogos, height=32,
                corner_radius=Tema.RAIO_CONTROLE, font=self.f_normal, fg_color=Tema.CARTAO,
                selected_color=Tema.PRIMARIA, selected_hover_color=Tema.PRIMARIA_HOVER, unselected_color=Tema.CARTAO,
                unselected_hover_color=Tema.SECUNDARIA_HOVER, text_color=Tema.TEXTO)
            self.seletor_modo_jogos.pack(side="left")
            self.painel_jogos = PainelJogos(self.aba_jogos, self, {
                "escolher_iso": self.jogo_escolher_iso, "ler_iso": self.jogo_ler_iso, "conferir": self.jogo_conferir,
                "escolher_patch": self.jogo_escolher_patch, "ler_patch": self.jogo_ler_patch,
                "procurar": self.jogo_procurar, "abrir_leia_me": self.jogo_abrir_leia_me,
                "escolher_pasta": self.jogo_escolher_pasta, "aplicar": self.jogo_aplicar,
                "abrir_pasta": self.jogo_abrir_pasta, "abrir_pcsx2": self.jogo_abrir_pcsx2,
                "aplicados": self.jogo_aplicados,
                "escolher_original": lambda: self._jogo_escolher_criar("original"),
                "escolher_modificada": lambda: self._jogo_escolher_criar("modificada"), "criar": self.jogo_criar,
                "tela": lambda: self._jogo_atalho_enquanto("tela"),
                "legenda": lambda: self._jogo_atalho_enquanto("legenda")})
            modo = self.preferencia_jogos("modo", MODO_PATCH)
            self._modo_jogos = modo if modo in MODOS else MODO_PATCH
        self.mostrar_modo_jogos(self._modo_jogos)

    def mostrar_modo_jogos(self, modo: str) -> None:
        """Troca o modo da aba (e o subtítulo do topo, como no protótipo)."""
        self._modo_jogos = modo if modo in MODOS else MODO_PATCH
        self.seletor_modo_jogos.set(self._modo_jogos)
        paineis = {MODO_PATCH: self.painel_jogos}
        if self._modo_jogos == MODO_DUBLAR and hasattr(self, "painel_do_modo_dublar"):
            paineis[MODO_DUBLAR] = self.painel_do_modo_dublar()
        if self._modo_jogos == MODO_ENQUANTO and hasattr(self, "painel_do_modo_enquanto"):
            paineis[MODO_ENQUANTO] = self.painel_do_modo_enquanto()
        for painel in (self.painel_jogos, self.painel_dublar_jogo, self.painel_enquanto_joga):
            if painel is not None and painel.winfo_exists():
                painel.grid_remove()
        paineis.get(self._modo_jogos, self.painel_jogos).grid(row=1, column=0, sticky="nsew")
        if self.seletor_aba.get() == "🎮 Jogos":
            self.lb_titulo.configure(text=self.TITULOS["🎮 Jogos"])
            self.lb_subtitulo.configure(text=SUBTITULOS_MODO[self._modo_jogos])
            self.after_idle(self._caber_titulo)
        self.guardar_preferencia_jogos("modo", self._modo_jogos)

    def _mensagem_jogos(self, tipo: str, *dados) -> None:
        """As respostas das tarefas da aba (na thread da janela)."""
        if tipo.startswith("d_") and hasattr(self, "_mensagem_dublar_jogo"):
            self._mensagem_dublar_jogo(tipo, *dados)
            return
        if tipo.startswith("e_") and hasattr(self, "_mensagem_enquanto"):
            self._mensagem_enquanto(tipo, *dados)
            return
        painel = self.painel_jogos
        if painel is None or not painel.winfo_exists():
            return
        if tipo == "digital":
            caminho, digital, *resto = dados
            if painel.info is not None and painel.info.caminho == caminho:
                painel.mostrar_digital(digital, resto[0] if resto else None)
        elif tipo == "andamento":
            painel.mostrar_andamento(*dados)
        elif tipo == "aplicado":
            resultado, *resto = dados
            painel.mostrar_resultado(resultado, resto[0] if resto else "")
        elif tipo == "criado":
            patch, = dados
            painel.mostrar_criado(patch)
        elif tipo == "abrir_pcsx2":
            self.jogo_abrir_pcsx2(dados[0])

    @staticmethod
    def _chave(caminho: Path) -> tuple:
        estado = caminho.stat()
        return str(caminho.resolve()), estado.st_size, estado.st_mtime_ns

    # ---- 1. o jogo
    def jogo_escolher_iso(self) -> None:
        atual = self.painel_jogos.var_iso.get().strip()
        caminho = filedialog.askopenfilename(parent=self, title="A ISO tirada do SEU disco", filetypes=TIPOS_ISO,
                                             initialdir=str(Path(atual).parent) if atual else None)
        if caminho:
            self.painel_jogos.var_iso.set(caminho)
            self.jogo_ler_iso()

    def jogo_ler_iso(self) -> None:
        painel = self.painel_jogos
        caminho = Path(painel.var_iso.get().strip())
        try:
            info = pj.ler_info(caminho)
        except pj.ErroPatch as erro:
            painel.mostrar_jogo(None, f"✗ {erro}")
            return
        painel.mostrar_jogo(info)
        guardada = self._digitais.get(self._chave(caminho))
        if guardada:
            painel.mostrar_digital(*guardada) if isinstance(guardada, tuple) else painel.mostrar_digital(guardada)

    def _consultar_redump(self, info: pj.InfoISO, digital: pj.Digital) -> str | None:
        """O nome do disco no banco Redump ("" = não está; None = não deu para consultar agora)."""
        try:
            indice = redump.indice(info.sistema or "PS2", config.ARQUIVO.parent / "redump")
        except Exception as erro:                       # sem internet: a impressão vale do mesmo jeito
            self._log.info("Banco Redump indisponível: %s", erro)
            return None
        return redump.procurar(indice, digital.md5, digital.crc32, info.tamanho) or ""

    def jogo_conferir(self, depois=None) -> None:
        """Mede a impressão digital (CRC32/MD5/SHA-1) numa tarefa (a ISO de DVD leva ~1 minuto) e procura no
        banco Redump (a lista dos discos originais)."""
        info = self.painel_jogos.info
        if info is None:
            return
        caminho = info.caminho

        def tarefa():
            try:
                digital = pj.impressao_digital(caminho, lambda f: self.fila.put(
                    ("jf_analise", (f, f"Conferindo a impressão digital: {f:.0%}"))), self.evento_parar.is_set)
            except (pj.ErroPatch, OSError) as erro:
                self.fila.put(("msg", ("Conferir a ISO", f"Não deu para conferir: {erro}.", "aviso")))
                return
            nome = self._consultar_redump(info, digital)
            self._digitais[self._chave(caminho)] = (digital, nome)
            self._log.info("Impressão digital de %s: CRC32 %s MD5 %s · Redump: %s", caminho.name, digital.crc32,
                           digital.md5, nome if nome else "não está" if nome == "" else "sem consulta")
            self.fila.put(("jogos", ("digital", caminho, digital, nome)))
            if depois:
                depois(digital)

        self._rodar(f"Conferindo a impressão digital de {caminho.name}...", tarefa)

    # ---- 2. o patch
    def jogo_escolher_patch(self) -> bool:
        atual = self.painel_jogos.var_patch.get().strip()
        caminho = filedialog.askopenfilename(parent=self, title="O patch do grupo de tradução (.xdelta, .ppf, .ips, "
                                             ".bps)", filetypes=TIPOS_PATCH,
                                             initialdir=str(Path(atual).parent) if atual else None)
        if caminho:
            self.painel_jogos.var_patch.set(caminho)
            self.jogo_ler_patch()
            return True
        return False

    def jogo_ler_patch(self) -> None:
        painel = self.painel_jogos
        caminho = Path(painel.var_patch.get().strip())
        try:
            tipo = pj.tipo_do_patch(caminho)
            if tipo == pj.PPF:
                ppf = pj.ler_ppf(caminho)
                descricao = f"PPF {ppf.versao}.0 · {ppf.descricao or caminho.stem}" + (
                    " · confere um pedaço da ISO antes" if ppf.bloco else "")
            elif tipo == pj.BPS:
                b = pj.info_bps(caminho)
                descricao = f"bps · {caminho.name} · confere a impressão da original (CRC32 {b['crc_origem']}) e da " \
                            f"nova"
            elif tipo == pj.IPS:
                descricao = f"ips · {caminho.name} ({pj.tamanho_legivel(caminho.stat().st_size)}) · sem conferência"
            else:
                descricao = f"xdelta · {caminho.name} ({pj.tamanho_legivel(caminho.stat().st_size)}) · o xdelta3 " \
                            "confere a ISO ao aplicar"
            esperado = pj.esperado_do_leia_me(caminho)
            if tipo == pj.BPS:
                esperado.crc32.add(pj.info_bps(caminho)["crc_origem"])
            leia = pj.leia_me(caminho)
        except (pj.ErroPatch, OSError) as erro:
            painel.mostrar_patch("", "", None, f"✗ {erro}")
            return
        painel.mostrar_patch(tipo, descricao, esperado, leia_me=leia)

    def jogo_abrir_leia_me(self) -> None:
        leia = self.painel_jogos.leia_me
        if leia and leia.arquivo:
            self._abrir_arquivo_do_sistema(leia.arquivo)

    def _abrir_arquivo_do_sistema(self, arquivo: Path) -> None:
        try:
            if sys.platform == "win32":
                os.startfile(str(arquivo))  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open" if sys.platform != "darwin" else "open", str(arquivo)])
        except OSError as erro:
            self.mostrar_mensagem("Abrir", f"Não consegui abrir {arquivo.name}: {erro}", "aviso")

    def jogo_procurar(self) -> None:
        """A janela "Procurar na comunidade": a lista dos patches do jogo, com o que traz e se encaixa."""
        from .janela_comunidade import JanelaComunidade
        painel = self.painel_jogos
        if painel.info is None:
            self.mostrar_mensagem("Procurar na comunidade", "Escolha primeiro a ISO do seu disco: a busca usa o "
                                  "nome e o código do jogo (SLUS-...) para achar o patch da sua versão.", "aviso")
            return
        info = painel.info
        nome = cm.nome_do_jogo(info, info.caminho.stem, painel.redump)
        digital = painel.digital
        pasta = config.ARQUIVO.parent / "comunidade"
        if self.janela_comunidade is not None and self.janela_comunidade.winfo_exists():
            self.janela_comunidade.destroy()
        self.janela_comunidade = JanelaComunidade(
            self, f"{nome} ({info.id_jogo})" if info.id_jogo else nome, nome,
            lambda termos, onde, quer: cm.procurar(termos, info, pasta, onde, quer,
                                                   crc32=digital.crc32 if digital else ""),
            self.jogo_escolher_patch)

    # ---- 3. aplicar
    def jogo_escolher_pasta(self) -> None:
        pasta = filedialog.askdirectory(parent=self, title="Onde salvar a ISO nova")
        if pasta:
            self.painel_jogos.var_pasta_saida.set(pasta)

    def jogo_aplicar(self) -> None:
        painel = self.painel_jogos
        info, patch = painel.info, Path(painel.var_patch.get().strip())
        if info is None or not painel.tipo_patch:
            self.mostrar_mensagem("Aplicar o patch", "Escolha a ISO do seu disco (1) e o patch (2).", "aviso")
            return
        destino = painel.pasta_saida() / painel.nome_final()
        if destino.exists() and not self.perguntar("Aplicar o patch", f"Já existe {destino.name}. Trocar por "
                                                   "uma nova?"):
            return
        esperado, digital = painel.esperado, painel.digital
        conferir_copia, abrir_depois = painel.var_conferir_copia.get(), painel.var_abrir_pcsx2.get()

        def tarefa():
            nonlocal digital

            def andamento(f, texto):
                self.fila.put(("jf_analise", (f, texto)))
                self.fila.put(("jogos", ("andamento", f, f"{f:.0%}")))
            try:
                if esperado is not None and esperado.tem_digital() and digital is None:   # confere ANTES
                    digital = pj.impressao_digital(info.caminho, lambda f: andamento(
                        0.2 * f, f"Conferindo a versão da ISO: {f:.0%}"), self.evento_parar.is_set)
                    self._digitais[self._chave(info.caminho)] = (digital, None)
                    self.fila.put(("jogos", ("digital", info.caminho, digital)))
                fim = 0.8 if conferir_copia else 1.0
                resultado = pj.aplicar(info.caminho, patch, destino, self.pasta_ferramentas, digital, esperado,
                                       lambda f: andamento(0.2 + (fim - 0.2) * f, f"Aplicando o patch: {f:.0%}"),
                                       self.evento_parar.is_set)
                copia = ""
                if conferir_copia:
                    nova = pj.impressao_digital(destino, lambda f: andamento(0.8 + 0.2 * f,
                                                                             f"Conferindo a cópia: {f:.0%}"),
                                                self.evento_parar.is_set)
                    if esperado is not None and esperado.tem_digital() and esperado.confere(nova):
                        copia = "a impressão digital da cópia confere com a publicada pelo grupo"
                    else:
                        copia = f"cópia conferida (CRC32 {nova.crc32}); {resultado.conferido}"
            except (pj.ErroPatch, OSError) as erro:
                self._log.warning("Aplicar patch: %s", erro)
                self.fila.put(("msg", ("Aplicar o patch", f"Não apliquei: {erro}.", "aviso")))
                return
            self._log.info("Patch aplicado: %s + %s -> %s (%s)", info.caminho.name, patch.name, destino,
                           copia or resultado.conferido)
            pj.registrar_aplicado(self.arquivo_aplicados, info.caminho, patch, destino, copia or resultado.conferido)
            self.fila.put(("jogos", ("aplicado", resultado, copia)))
            self.fila.put(("msg", ("Aplicar o patch", f"Pronto: {destino.name}.\n\nA ISO original não mudou. Copie "
                                   "a nova para a pasta DVD (ou CD) do pendrive/HD do OPL, ou abra no PCSX2 ou no "
                                   "celular.", "sucesso")))
            if abrir_depois:
                self.fila.put(("jogos", ("abrir_pcsx2", destino)))

        self._rodar(f"Aplicando o patch em {info.caminho.name}...", tarefa)

    def jogo_abrir_pasta(self) -> None:
        ultimo = self.painel_jogos.ultimo
        if ultimo is not None:
            self._abrir_pasta_do_sistema(str(ultimo.parent))

    def jogo_abrir_pcsx2(self, iso: Path | None = None) -> None:
        """Abre a ISO no PCSX2 (o do PC; na 1ª vez, se não achar, pergunta onde ele está)."""
        painel = self.painel_jogos
        iso = iso or painel.ultimo or (painel.info.caminho if painel.info else None)
        if iso is None:
            return
        exe = pj.achar_pcsx2(self.preferencia_jogos("pcsx2", ""))
        if exe is None:
            escolhido = filedialog.askopenfilename(parent=self, title="Onde está o PCSX2 (pcsx2-qt.exe)?",
                                                   filetypes=TIPOS_PROGRAMA)
            if not escolhido:
                return
            exe = Path(escolhido)
            self.guardar_preferencia_jogos("pcsx2", str(exe))
        try:
            pj.abrir_no_pcsx2(iso, exe)
            self._log.info("Aberto no PCSX2: %s", iso)
        except OSError as erro:
            self.mostrar_mensagem("Abrir no PCSX2", f"O PCSX2 não abriu: {erro}", "aviso")

    def jogo_aplicados(self) -> None:
        """Os patches aplicados: para abrir no PCSX2, abrir a pasta ou apagar a cópia (a original nunca)."""
        lista = pj.carregar_aplicados(self.arquivo_aplicados)
        if not lista:
            self.mostrar_mensagem("Patches aplicados", "Nenhum patch aplicado ainda.", "info")
            return
        itens = [f"{d['quando']} · {Path(d['destino']).name} · {d['conferido']}" +
                 ("" if Path(d["destino"]).exists() else " (a cópia não existe mais)") for d in lista]
        k = self.escolher_da_lista("Patches aplicados", "As cópias traduzidas que o Maestro criou (a ISO original "
                                   "nunca é alterada):", itens, botao="Escolher")
        if k is None:
            return
        destino = Path(lista[k]["destino"])
        acao = self.escolher("Patches aplicados", f"{destino.name}\nPatch: {Path(lista[k]['patch']).name}",
                             ["Abrir no PCSX2", "Abrir a pasta", "Apagar a cópia", "Fechar"])
        if acao == "Abrir no PCSX2" and destino.exists():
            self.jogo_abrir_pcsx2(destino)
        elif acao == "Abrir a pasta":
            self._abrir_pasta_do_sistema(str(destino.parent))
        elif acao == "Apagar a cópia" and destino.exists() and self.perguntar(
                "Apagar a cópia", f"Apagar {destino.name}? (é a cópia traduzida; a ISO original continua)"):
            destino.unlink()
            self._log.info("Cópia apagada: %s", destino)

    # ---- compartilhar: criar o patch
    def _jogo_escolher_criar(self, qual: str) -> None:
        caminho = filedialog.askopenfilename(
            parent=self, filetypes=TIPOS_ISO, title="A ISO original do seu disco" if qual == "original" else
            "A ISO com a sua tradução")
        if caminho:
            (self.painel_jogos.var_criar_original if qual == "original" else
             self.painel_jogos.var_criar_modificada).set(caminho)

    def jogo_criar(self, original: Path | None = None, modificada: Path | None = None, descricao: str = "") -> None:
        painel = self.painel_jogos
        original = original or Path(painel.var_criar_original.get().strip())
        modificada = modificada or Path(painel.var_criar_modificada.get().strip())
        if not (original.is_file() and modificada.is_file()):
            self.mostrar_mensagem("Criar o patch", "Escolha a ISO original do seu disco e a modificada (com a sua "
                                  "tradução).", "aviso")
            return
        descricao = descricao or painel.var_criar_descricao.get().strip()
        saida = filedialog.asksaveasfilename(parent=self, title="Salvar o patch", defaultextension=".xdelta",
                                             initialdir=str(modificada.parent),
                                             initialfile=f"{descricao or modificada.stem}.xdelta",
                                             filetypes=[("Patch xdelta", "*.xdelta")])
        if not saida:
            return

        def tarefa():
            try:
                patch = pj.criar_patch(original, modificada, Path(saida), self.pasta_ferramentas, descricao,
                                       lambda f: self.fila.put(("jf_analise", (f, f"Criando o patch: {f:.0%}"))),
                                       self.evento_parar.is_set)
            except (pj.ErroPatch, OSError) as erro:
                self._log.warning("Criar patch: %s", erro)
                self.fila.put(("msg", ("Criar o patch", f"Não deu para criar: {erro}.", "aviso")))
                return
            self._log.info("Patch criado: %s", patch)
            self.fila.put(("jogos", ("criado", patch)))
            tamanho = pj.tamanho_legivel(patch.stat().st_size)
            self.fila.put(("msg", ("Criar o patch", f"Pronto: {patch.name} ({tamanho}) e o leia-me ao lado.\n\n"
                                   "Compartilhe só esses dois arquivos: quem tem o disco aplica na própria ISO.",
                                   "sucesso")))

        self._rodar("Criando o patch da sua tradução...", tarefa)

    # ---- "Enquanto joga" (os atalhos do cartão do fim): ligam o mesmo do modo completo
    def _jogo_atalho_enquanto(self, qual: str) -> None:
        painel = self.painel_jogos
        var = painel.var_atalho_tela if qual == "tela" else painel.var_atalho_legenda
        if not hasattr(self, "enquanto_ligar"):
            var.set(False)
            return
        if not self.enquanto_ligar(qual, var.get()):
            var.set(False)
