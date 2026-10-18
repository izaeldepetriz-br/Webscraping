"""Aba "🎮 Jogos" na janela moderna: escolher a ISO e o patch, conferir a impressão digital, aplicar numa cópia e
criar o patch da sua tradução.

Separado de app_moderna.py (como a aba Áudio): a AppModerna herda esta parte. A tela fica em painel_jogos.py e o
trabalho em jellyfin_tools/patch_jogo.py. Tudo no PC, sem custo.
"""

from __future__ import annotations

import webbrowser
from pathlib import Path
from tkinter import filedialog

from jellyfin_tools import patch_jogo as pj

from . import config
from .painel_jogos import PainelJogos

TIPOS_ISO = [("Imagem do disco", "*.iso *.bin *.img"), ("Todos os arquivos", "*.*")]
TIPOS_PATCH = [("Patch de fãs", "*.xdelta *.vcdiff *.xd3 *.delta *.ppf"), ("Todos os arquivos", "*.*")]


class PatchDeJogos:
    """Parte "🎮 Jogos" da AppModerna (usa self.fila, self._rodar, self.mostrar_mensagem... da janela)."""

    def _iniciar_jogos(self) -> None:
        self.painel_jogos = None                # montado na 1ª vez que a aba abre
        self._digitais: dict[tuple, pj.Digital] = {}   # (caminho, tamanho, data) -> impressão digital já medida

    @property
    def pasta_ferramentas(self) -> Path:
        return config.ARQUIVO.parent / "ferramentas"

    def ao_abrir_aba_jogos(self) -> None:
        if self.painel_jogos is not None and self.painel_jogos.winfo_exists():
            return
        self.painel_jogos = PainelJogos(self.aba_jogos, self, {
            "escolher_iso": self.jogo_escolher_iso, "ler_iso": self.jogo_ler_iso, "conferir": self.jogo_conferir,
            "escolher_patch": self.jogo_escolher_patch, "ler_patch": self.jogo_ler_patch,
            "procurar": self.jogo_procurar, "escolher_pasta": self.jogo_escolher_pasta, "aplicar": self.jogo_aplicar,
            "abrir_pasta": self.jogo_abrir_pasta, "escolher_original": lambda: self._jogo_escolher_criar("original"),
            "escolher_modificada": lambda: self._jogo_escolher_criar("modificada"), "criar": self.jogo_criar})
        self.painel_jogos.grid(row=0, column=0, sticky="nsew")

    def _mensagem_jogos(self, tipo: str, *dados) -> None:
        """As respostas das tarefas da aba (na thread da janela)."""
        painel = self.painel_jogos
        if painel is None or not painel.winfo_exists():
            return
        if tipo == "digital":
            caminho, digital = dados
            if painel.info is not None and painel.info.caminho == caminho:
                painel.mostrar_digital(digital)
        elif tipo == "aplicado":
            resultado, = dados
            painel.mostrar_resultado(resultado)
        elif tipo == "criado":
            patch, = dados
            painel.mostrar_criado(patch)

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
            painel.mostrar_digital(guardada)

    def jogo_conferir(self, depois=None) -> None:
        """Mede a impressão digital (CRC32/MD5/SHA-1) numa tarefa (a ISO de DVD leva ~1 minuto)."""
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
            self._digitais[self._chave(caminho)] = digital
            self._log.info("Impressão digital de %s: CRC32 %s MD5 %s", caminho.name, digital.crc32, digital.md5)
            self.fila.put(("jogos", ("digital", caminho, digital)))
            if depois:
                depois(digital)

        self._rodar(f"Conferindo a impressão digital de {caminho.name}...", tarefa)

    # ---- 2. o patch
    def jogo_escolher_patch(self) -> None:
        atual = self.painel_jogos.var_patch.get().strip()
        caminho = filedialog.askopenfilename(parent=self, title="O patch do grupo de tradução (.xdelta ou .ppf)",
                                             filetypes=TIPOS_PATCH,
                                             initialdir=str(Path(atual).parent) if atual else None)
        if caminho:
            self.painel_jogos.var_patch.set(caminho)
            self.jogo_ler_patch()

    def jogo_ler_patch(self) -> None:
        painel = self.painel_jogos
        caminho = Path(painel.var_patch.get().strip())
        try:
            tipo = pj.tipo_do_patch(caminho)
            if tipo == pj.PPF:
                ppf = pj.ler_ppf(caminho)
                descricao = f"PPF {ppf.versao}.0 · {ppf.descricao or caminho.stem}" + (
                    " · confere um pedaço da ISO antes" if ppf.bloco else "")
            else:
                descricao = f"xdelta · {caminho.name} ({pj.tamanho_legivel(caminho.stat().st_size)}) · o xdelta3 " \
                            "confere a ISO ao aplicar"
            esperado = pj.esperado_do_leia_me(caminho)
        except (pj.ErroPatch, OSError) as erro:
            painel.mostrar_patch("", "", None, f"✗ {erro}")
            return
        painel.mostrar_patch(tipo, descricao, esperado)

    def jogo_procurar(self) -> None:
        painel = self.painel_jogos
        if painel.info is None:
            self.mostrar_mensagem("Procurar na comunidade", "Escolha primeiro a ISO do seu disco: a busca usa o "
                                  "código do jogo (SLUS-...) para achar o patch da sua versão.", "aviso")
            return
        nome = painel.info.caminho.stem
        webbrowser.open(pj.busca_na_comunidade(painel.info, nome))

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

        def tarefa():
            nonlocal digital
            andamento = lambda f, texto: self.fila.put(("jf_analise", (f, texto)))   # noqa: E731
            try:
                if esperado is not None and esperado.tem_digital() and digital is None:   # confere ANTES
                    digital = pj.impressao_digital(info.caminho, lambda f: andamento(
                        0.3 * f, f"Conferindo a versão da ISO: {f:.0%}"), self.evento_parar.is_set)
                    self._digitais[self._chave(info.caminho)] = digital
                    self.fila.put(("jogos", ("digital", info.caminho, digital)))
                resultado = pj.aplicar(info.caminho, patch, destino, self.pasta_ferramentas, digital, esperado,
                                       lambda f: andamento(0.3 + 0.7 * f, f"Aplicando o patch: {f:.0%}"),
                                       self.evento_parar.is_set)
            except (pj.ErroPatch, OSError) as erro:
                self._log.warning("Aplicar patch: %s", erro)
                self.fila.put(("msg", ("Aplicar o patch", f"Não apliquei: {erro}.", "aviso")))
                return
            self._log.info("Patch aplicado: %s + %s -> %s (%s)", info.caminho.name, patch.name, destino,
                           resultado.conferido)
            self.fila.put(("jogos", ("aplicado", resultado)))
            self.fila.put(("msg", ("Aplicar o patch", f"Pronto: {destino.name}.\n\nA ISO original não mudou. Copie "
                                   "a nova para a pasta DVD (ou CD) do pendrive/HD do OPL, ou abra no PCSX2 ou no "
                                   "celular.", "sucesso")))

        self._rodar(f"Aplicando o patch em {info.caminho.name}...", tarefa)

    def jogo_abrir_pasta(self) -> None:
        ultimo = self.painel_jogos.ultimo
        if ultimo is not None:
            self._abrir_pasta_do_sistema(str(ultimo.parent))

    # ---- compartilhar: criar o patch
    def _jogo_escolher_criar(self, qual: str) -> None:
        caminho = filedialog.askopenfilename(
            parent=self, filetypes=TIPOS_ISO, title="A ISO original do seu disco" if qual == "original" else
            "A ISO com a sua tradução")
        if caminho:
            (self.painel_jogos.var_criar_original if qual == "original" else
             self.painel_jogos.var_criar_modificada).set(caminho)

    def jogo_criar(self) -> None:
        painel = self.painel_jogos
        original = Path(painel.var_criar_original.get().strip())
        modificada = Path(painel.var_criar_modificada.get().strip())
        if not (original.is_file() and modificada.is_file()):
            self.mostrar_mensagem("Criar o patch", "Escolha a ISO original do seu disco e a modificada (com a sua "
                                  "tradução).", "aviso")
            return
        descricao = painel.var_criar_descricao.get().strip()
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
