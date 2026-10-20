"""Aba "🎮 Jogos", modo "📦 Instalar a tradução" (Nintendo Switch e PC, no lugar do patch na ISO): a ligação da tela
(painel_instalar.py) com o trabalho (jellyfin_tools/instalar_traducao.py). A AppModerna herda esta parte, como a do
patch.

    Switch   o mod de tradução (pasta ou .zip, com o TitleID) vai para a pasta de mods do emulador ou para o cartão
             SD com Atmosphère; o jogo não muda
    PC       os arquivos da tradução vão por cima da pasta do jogo; os originais ficam guardados para Desfazer

"🗂 Traduções instaladas" lista o que o Maestro instalou (traducoes_instaladas.json, junto das configurações) para
desfazer. "Compartilhar a sua tradução" cria o mod (.zip) ou o pacote (.zip), só com os arquivos traduzidos.
"""

from __future__ import annotations

from pathlib import Path
from tkinter import filedialog

from jellyfin_tools import comunidade as cm
from jellyfin_tools import instalar_traducao as it
from jellyfin_tools import patch_jogo as pj

from . import config
from .painel_instalar import ONDES_SWITCH, PainelInstalar

TIPOS_ZIP = [("Tradução (.zip)", "*.zip"), ("Todos os arquivos", "*.*")]


class InstalarTraducao:
    """Parte "📦 Instalar a tradução" da aba 🎮 Jogos (usa self.fila, self._rodar, self.console_jogos... da janela)."""

    def _iniciar_instalar(self) -> None:
        self.painel_instalar = None
        self._paineis_instalar: dict[str, PainelInstalar] = {}      # Switch e PC

    @property
    def arquivo_instaladas(self) -> Path:
        return config.ARQUIVO.parent / "traducoes_instaladas.json"

    def painel_do_modo_instalar(self) -> PainelInstalar:
        console = self.console_jogos
        self.painel_instalar = self._paineis_instalar.get(console.chave)
        if self.painel_instalar is None or not self.painel_instalar.winfo_exists():
            self.painel_instalar = PainelInstalar(self.aba_jogos, self, {
                "escolher_zip": self.i_escolher_zip, "escolher_pasta": self.i_escolher_pasta,
                "procurar": self.i_procurar, "escolher_destino": self.i_escolher_destino,
                "instalar": self.i_instalar, "instaladas": self.i_instaladas, "abrir_destino": self.i_abrir_destino,
                "abrir_emulador": self.i_abrir_emulador, "criar_escolher": lambda: self._i_criar_escolher("pasta"),
                "criar_escolher_original": lambda: self._i_criar_escolher("original"), "criar": self.i_criar,
                "trocou_onde": self.i_trocou_onde},
                console)
            self._paineis_instalar[console.chave] = self.painel_instalar
            p = self.painel_instalar
            if p.switch:                                # onde ficou da última vez (a pasta de mods ou o SD)
                onde = self.preferencia_console("onde", it.EMULADOR, console)
                if onde in (it.EMULADOR, it.SD) and onde != p.onde():
                    p.seletor_onde.set(ONDES_SWITCH[onde])
                    p.var_onde.set(onde)
                p.var_destino.set(self.preferencia_console(f"destino_{p.onde()}", "", console))
        return self.painel_instalar

    # ------------------------------------------------------------------ 1. a tradução
    def i_escolher_zip(self) -> bool:
        p = self.painel_instalar
        atual = p.var_origem.get().strip()
        caminho = filedialog.askopenfilename(parent=self, title="O mod de tradução (.zip)" if p.switch else
                                             "A tradução do jogo (.zip)", filetypes=TIPOS_ZIP,
                                             initialdir=str(Path(atual).parent) if atual else None)
        if not caminho:
            return False
        p.var_origem.set(caminho)
        self.i_ler()
        return True

    def i_escolher_pasta(self) -> None:
        p = self.painel_instalar
        pasta = filedialog.askdirectory(parent=self, title="A pasta do mod de tradução" if p.switch else
                                        "A pasta com os arquivos da tradução")
        if pasta:
            p.var_origem.set(pasta)
            self.i_ler()

    def i_ler(self) -> None:
        p = self.painel_instalar
        texto = p.var_origem.get().strip()
        if not texto:
            return
        try:
            if p.switch:
                pacote = it.ler_mod(texto)
            else:
                pasta_jogo = p.var_destino.get().strip()
                pacote = it.ler_pacote_pc(texto, pasta_jogo if pasta_jogo and Path(pasta_jogo).is_dir() else None)
        except (pj.ErroPatch, OSError) as erro:
            p.mostrar_pacote(None, f"✗ {erro}")
            return
        p.mostrar_pacote(pacote)

    def i_procurar(self) -> None:
        """A janela "Procurar na comunidade" com o sistema do console (o resultado escolhido vem para o campo 1)."""
        from .janela_comunidade import JanelaComunidade
        p = self.painel_instalar
        sistema = "Switch" if p.switch else "PC"
        if p.pacote is not None:
            termos = p.pacote.nome
        elif not p.switch and p.var_destino.get().strip():
            termos = Path(p.var_destino.get().strip()).name               # o nome da pasta do jogo
        else:
            termos = ""
        termos = cm.nome_do_jogo(None, termos) if termos else ""
        pasta = config.ARQUIVO.parent / "comunidade"
        if self.janela_comunidade is not None and self.janela_comunidade.winfo_exists():
            self.janela_comunidade.destroy()
        self.janela_comunidade = JanelaComunidade(
            self, f"{termos or 'o jogo'} ({p.console.nome})", termos,
            lambda termos, onde, quer: cm.procurar(termos, None, pasta, onde, quer, sistema=sistema),
            self.i_escolher_zip)

    # ------------------------------------------------------------------ 2. onde instalar
    def i_escolher_destino(self) -> None:
        p = self.painel_instalar
        titulo = ("A pasta de mods do emulador (ex.: ...\\mods\\contents)" if p.onde() == it.EMULADOR else
                  "A raiz do cartão SD do Switch") if p.switch else "A pasta onde o jogo está instalado"
        pasta = filedialog.askdirectory(parent=self, title=titulo)
        if not pasta:
            return
        p.var_destino.set(pasta)
        if p.switch:
            self.guardar_preferencia_console(f"destino_{p.onde()}", pasta)
        elif p.var_origem.get().strip():                # no PC, a pasta do jogo decide se a pasta de cima sai
            self.i_ler()

    def i_trocou_onde(self, onde: str) -> None:
        """Emulador <-> cartão SD: cada um lembra a sua pasta."""
        p = self.painel_instalar
        self.guardar_preferencia_console("onde", onde)
        p.var_destino.set(self.preferencia_console(f"destino_{onde}", ""))

    # ------------------------------------------------------------------ 3. instalar e desfazer
    def i_instalar(self) -> None:
        p = self.painel_instalar
        pacote, destino, console = p.pacote, p.destino(), p.console
        if pacote is None or destino is None:
            self.mostrar_mensagem("Instalar a tradução", "Escolha a tradução (1) e onde instalar (2)" +
                                  (" (e o TitleID do jogo)." if p.switch else "."), "aviso")
            return
        if not p.switch and not destino.is_dir():
            self.mostrar_mensagem("Instalar a tradução", f"Não achei a pasta do jogo: {destino}", "aviso")
            return

        def andamento(f):
            self.fila.put(("jf_analise", (f, f"Instalando a tradução: {f:.0%}")))
            self.fila.put(("jogos", ("i_andamento", f)))

        def tarefa():
            try:
                feito = it.instalar(pacote, destino, console.chave, andamento, self.evento_parar.is_set)
                it.registrar(self.arquivo_instaladas, feito)
            except (pj.ErroPatch, OSError) as erro:
                self._log.warning("Instalar a tradução: %s", erro)
                self.fila.put(("msg", ("Instalar a tradução", f"Não instalei: {erro}.", "aviso")))
                return
            self._log.info("Tradução instalada (%s): %s em %s · %d novos, %d trocados", console.chave, feito.nome,
                           feito.destino, len(feito.criados), len(feito.trocados))
            self.fila.put(("jogos", ("i_instalado", feito)))
            self.fila.put(("msg", ("Instalar a tradução", f"Pronto: {feito.nome} instalada em {feito.destino}.\n\n" +
                                   ("Abra o jogo no emulador (ou no Switch): o mod entra sozinho. O jogo não mudou."
                                    if p.switch else "Os arquivos que já existiam ficaram guardados: \"Traduções "
                                    "instaladas\" desfaz e devolve tudo."), "sucesso")))

        self._rodar(f"Instalando {pacote.nome}...", tarefa)

    def i_instaladas(self) -> None:
        """As traduções instaladas neste console: Desfazer (apaga o que o Maestro copiou e devolve os originais)."""
        console = self.console_jogos
        lista = [i for i in it.carregar(self.arquivo_instaladas) if i.console == console.chave]
        if not lista:
            self.mostrar_mensagem("Traduções instaladas", "Nenhuma tradução instalada pelo Maestro neste console.",
                                  "info")
            return
        itens = [f"{i.quando} · {i.nome} · {i.destino} · {len(i.criados) + len(i.trocados)} arquivos" +
                 ("" if Path(i.destino).exists() else " (a pasta não existe mais)") for i in lista]
        k = self.escolher_da_lista("Traduções instaladas", "O que o Maestro instalou (Desfazer apaga só o que ele "
                                   "copiou e devolve os originais):", itens, botao="Escolher")
        if k is None:
            return
        feito = lista[k]
        acao = self.escolher("Traduções instaladas", f"{feito.nome}\n{feito.destino}",
                             ["Desfazer (tirar a tradução)", "Abrir a pasta", "Fechar"])
        if acao == "Abrir a pasta":
            self._abrir_pasta_do_sistema(feito.destino)
        elif acao == "Desfazer (tirar a tradução)" and self.perguntar(
                "Desfazer", f"Tirar {feito.nome} de {feito.destino}?" + (" Os arquivos originais voltam." if
                                                                         feito.trocados else "")):
            try:
                it.desfazer(feito)
                it.esquecer(self.arquivo_instaladas, feito)
            except OSError as erro:
                self.mostrar_mensagem("Desfazer", f"Não deu para desfazer tudo: {erro}", "aviso")
                return
            self._log.info("Tradução desfeita (%s): %s em %s", console.chave, feito.nome, feito.destino)
            if self.painel_instalar is not None and self.painel_instalar.winfo_exists():
                self.painel_instalar.mostrar_resultado(f"↩ Desfeita: {feito.nome} saiu de {feito.destino}" + (
                    " e os originais voltaram." if feito.trocados else "."))
            self.mostrar_mensagem("Desfazer", f"Pronto: {feito.nome} saiu.", "sucesso")

    def i_abrir_destino(self) -> None:
        p = self.painel_instalar
        pasta = p.ultimo or (Path(p.var_destino.get().strip()) if p.var_destino.get().strip() else None)
        if pasta is not None and pasta.exists():
            self._abrir_pasta_do_sistema(str(pasta))

    def i_abrir_emulador(self) -> None:
        self.abrir_no_emulador(self.console_jogos)

    # ------------------------------------------------------------------ compartilhar: o mod e o pacote
    def _i_criar_escolher(self, qual: str) -> None:
        p = self.painel_instalar
        pasta = filedialog.askdirectory(parent=self, title=(
            "A pasta com os arquivos traduzidos (romfs)" if p.switch else "A pasta do jogo com a sua tradução")
            if qual == "pasta" else "Uma cópia do jogo sem a tradução")
        if pasta:
            (p.var_criar_pasta if qual == "pasta" else p.var_criar_original).set(pasta)

    def _pedir_title_id(self, atual: str = "") -> str | None:
        pedir = getattr(self, "pedir_texto_do_jogo", None)
        if pedir is None:
            return None
        return pedir("Criar o mod", "O TitleID do jogo (16 letras e números começando com 01: aparece no emulador, "
                     "em Propriedades do jogo)", atual or "—")

    def i_criar(self, pasta: Path | None = None, descricao: str = "") -> None:
        """O mod (.zip com atmosphere/contents/<TitleID>/romfs) ou o pacote (.zip só com o que mudou). Do modo
        Traduzir e dublar, vem a pasta das vozes em português."""
        console = self.console_jogos
        switch = console.chave == "SWITCH"
        p = self._paineis_instalar.get(console.chave)
        p = p if p is not None and p.winfo_exists() else None
        nome = "Criar o mod" if switch else "Criar o pacote"
        pasta = pasta or (Path(p.var_criar_pasta.get().strip()) if p and p.var_criar_pasta.get().strip() else None)
        if pasta is None or not pasta.is_dir():
            self.mostrar_mensagem(nome, "Escolha a pasta com os arquivos traduzidos.", "aviso")
            return
        descricao = descricao or (p.var_criar_descricao.get().strip() if p else "")
        original = None
        if not switch and p is not None and p.var_criar_original.get().strip():
            original = Path(p.var_criar_original.get().strip())
        title_id = ""
        if switch:
            achado = it.TITLE_ID.search(str(pasta)) or it.TITLE_ID.search(p.var_title_id.get() if p else "")
            title_id = achado.group(1) if achado else (self._pedir_title_id() or "").strip()
            if not it.TITLE_ID.fullmatch(title_id.upper()):
                self.mostrar_mensagem(nome, "Falta o TitleID do jogo (16 letras e números começando com 01: aparece "
                                      "no emulador, em Propriedades do jogo).", "aviso")
                return
        saida = filedialog.asksaveasfilename(parent=self, title="Salvar o mod" if switch else "Salvar o pacote",
                                             defaultextension=".zip", initialdir=str(pasta.parent),
                                             initialfile=f"{descricao or pasta.name}.zip",
                                             filetypes=[("Arquivo .zip", "*.zip")])
        if not saida:
            return

        def tarefa():
            try:
                criado = it.criar_mod(pasta, title_id, saida, descricao) if switch else \
                    it.criar_pacote(pasta, saida, original, descricao)
            except (pj.ErroPatch, OSError) as erro:
                self._log.warning("%s: %s", nome, erro)
                self.fila.put(("msg", (nome, f"Não deu para criar: {erro}.", "aviso")))
                return
            self._log.info("%s: %s", nome, criado)
            self.fila.put(("jogos", ("i_criado", criado)))
            self.fila.put(("msg", (nome, f"Pronto: {criado.name} ({pj.tamanho_legivel(criado.stat().st_size)}), com "
                                   "um leia-me de como instalar.\n\nCompartilhe só a tradução, nunca o jogo.",
                                   "sucesso")))

        self._rodar(f"{nome}...", tarefa)

    # ------------------------------------------------------------------ as respostas das tarefas
    def _mensagem_instalar(self, tipo: str, *dados) -> None:
        p = self.painel_instalar
        if p is None or not p.winfo_exists():
            return
        if tipo == "i_andamento":
            p.mostrar_andamento(dados[0])
        elif tipo == "i_instalado":
            feito, = dados
            p.ultimo = Path(feito.destino)
            p.mostrar_andamento(1.0)
            p.mostrar_resultado(f"✓ Instalada: {feito.nome} em {feito.destino} · {len(feito.criados)} arquivo(s) "
                                "novo(s)" + (f", {len(feito.trocados)} trocado(s) (os originais ficaram guardados)"
                                             if feito.trocados else "") + ". Fica em 🗂 Traduções instaladas para "
                                "desfazer.")
        elif tipo == "i_criado":
            p.mostrar_criado(dados[0])

