"""Configurações > Dublagem > "Importar voz" na janela moderna: importar, remover e clonar no Gemini.

Separado de app_moderna.py (como a aba Áudio): a AppModerna herda esta parte. Os campos ficam em gui_moderna.py e o
trabalho com os arquivos em jellyfin_tools/vozes_importadas.py.
"""

from __future__ import annotations

from jellyfin_tools import voz_clonada, voz_gemini
from jellyfin_tools import vozes_importadas as vi
from jellyfin_tools.dublagem import ErroDublagem, localizar_ffmpeg

from . import automacao, config


class ImportarVozes:
    def _iniciar_vozes_importadas(self) -> None:
        self.atualizar_vozes_importadas(automacao.vozes_importadas())

    def _guardar_vozes_importadas(self, vozes: list) -> None:
        vi.salvar(vozes, automacao.arquivo_vozes_importadas())
        self.atualizar_vozes_importadas(vozes)

    def _limpar_campos_importar(self) -> None:
        for var in (self.var_imp_arquivo, self.var_imp_nome, self.var_imp_consentimento, self.var_imp_dono):
            var.set("")
        self.var_imp_autorizo.set(False)

    def ao_importar_voz(self) -> None:
        arquivo = self.var_imp_arquivo.get().strip()
        if not arquivo:
            self.mostrar_mensagem("Importar voz", "Escolha o arquivo da voz: um modelo do Piper (.onnx) ou uma "
                                  "gravação (.wav, .mp3, .m4a...).", "aviso")
            return
        try:
            tipo = vi.tipo_do_arquivo(arquivo)
        except ErroDublagem as erro:
            self.mostrar_mensagem("Importar voz", f"Não deu para importar: {erro}.", "aviso")
            return
        existentes = automacao.vozes_importadas()
        pasta = config.ARQUIVO.parent
        if tipo == vi.PIPER:
            try:
                nova = vi.importar_piper(arquivo, self.var_imp_nome.get(), pasta / "vozes", existentes)
            except (ErroDublagem, OSError) as erro:
                self._log.warning("Importar voz do Piper: %s", erro)
                self.mostrar_mensagem("Importar voz", f"Não deu para importar: {erro}.", "erro")
                return
            self._guardar_vozes_importadas(existentes + [nova])
            self._limpar_campos_importar()
            self._log.info("Voz do Piper importada: %s (%s)", nova.nome, nova.idioma)
            idioma = ("" if vi.e_portugues(nova) else f"\n\nAtenção: esta voz é de outro idioma ({nova.idioma}): ela "
                      "lê o português com sotaque. Para dublar, prefira uma voz pt_BR.")
            self.mostrar_mensagem("Importar voz", f"Pronto: a voz \"{nova.nome}\" já aparece em \"Voz do Piper\" e "
                                  f"na tabela \"Vozes dos personagens\".{idioma}", "sucesso")
            return
        ffmpeg = localizar_ffmpeg()
        if not ffmpeg:
            self.mostrar_mensagem("Importar voz", "Falta o ffmpeg para ler a gravação (pip install imageio-ffmpeg).",
                                  "erro")
            return
        pedido = dict(referencia=arquivo, consentimento=self.var_imp_consentimento.get().strip(),
                      nome=self.var_imp_nome.get(), dono=self.var_imp_dono.get(), autorizo=self.var_imp_autorizo.get())

        def tarefa():
            try:
                nova = vi.importar_gravacao(pedido["referencia"], pedido["consentimento"], pedido["nome"],
                                            pedido["dono"], pedido["autorizo"], pasta, ffmpeg, existentes)
            except (ErroDublagem, OSError) as erro:
                self._log.warning("Importar gravação de voz: %s", erro)
                self.fila.put(("msg", ("Importar voz", f"Não deu para importar: {erro}.", "aviso")))
                return
            vozes = existentes + [nova]
            vi.salvar(vozes, automacao.arquivo_vozes_importadas())
            self._log.info("Gravação de voz importada: %s (autorizada por %s)", nova.nome, nova.dono)
            self.fila.put(("vozes_importadas", vozes))
            self.fila.put(("msg", ("Importar voz", f"Pronto: a gravação da voz \"{nova.nome}\" (autorizada por "
                                   f"{nova.dono}) ficou guardada neste PC. Ela fica pronta para o motor de clonagem "
                                   "no PC e, se quiser, \"🎙 Clonar no Gemini...\" cria a voz no Gemini agora.",
                                   "sucesso")))

        self._rodar("Importando a gravação de voz...", tarefa)

    def ao_remover_voz_importada(self) -> None:
        vozes = automacao.vozes_importadas()
        if not vozes:
            self.atualizar_vozes_importadas([])
            return
        escolha = self.escolher_da_lista("Remover voz importada", "Qual voz importada apagar deste PC?",
                                         [v.descrever() for v in vozes], "Remover")
        if escolha is None:
            return
        removida = vozes.pop(escolha)
        if not self.perguntar("Remover voz importada", f"Apagar a voz \"{removida.nome}\" deste PC?"):
            return
        pasta = config.ARQUIVO.parent
        vi.remover(removida, pasta, pasta / "vozes")
        self._guardar_vozes_importadas(vozes)
        self._log.info("Voz importada removida: %s", removida.nome)
        self._salvar_config()

    def ao_clonar_importada_no_gemini(self) -> None:
        """Cria a voz no Gemini com as gravações importadas (o Google confere a frase e se é a mesma pessoa)."""
        o = self.obter_opcoes_jellyfin()
        if not automacao.chave_gemini(o):
            self.mostrar_mensagem("Clonar no Gemini", "Cole a chave do Google AI Studio em Configurações > Chaves de "
                                  "API.", "aviso")
            return
        gravacoes = [v for v in automacao.vozes_importadas() if v.tipo == vi.GRAVACAO]
        if not gravacoes:
            self.atualizar_vozes_importadas(automacao.vozes_importadas())
            return
        escolha = (0 if len(gravacoes) == 1 else
                   self.escolher_da_lista("Clonar no Gemini", "Qual gravação importada vira voz clonada no Gemini? "
                                          "(1 pedido ao Gemini)", [v.descrever() for v in gravacoes], "Clonar"))
        if escolha is None:
            return
        voz = gravacoes[escolha]
        try:
            nome = voz_clonada.validar_nome(voz.nome, automacao.vozes_clonadas())
        except ErroDublagem as erro:
            self.mostrar_mensagem("Clonar no Gemini", f"Não deu: {erro}.", "aviso")
            return

        def tarefa():
            try:
                referencia, consentimento = vi.ler_gravacao(voz, config.ARQUIVO.parent)
                nova = voz_clonada.criar(voz_gemini._cliente(automacao.chave_gemini(o)), nome, voz.dono,
                                         referencia, consentimento)
            except (ErroDublagem, OSError) as erro:
                self._log.warning("Clonar no Gemini (voz importada): %s", erro)
                self.fila.put(("msg", ("Clonar no Gemini", f"Não deu para clonar: {erro}.", "erro")))
                return
            vozes = automacao.vozes_clonadas() + [nova]
            voz_clonada.salvar(vozes, automacao.arquivo_vozes_clonadas())
            self._log.info("Voz importada clonada no Gemini: %s", nova.nome)
            self.fila.put(("vozes_clonadas", vozes))
            self.fila.put(("msg", ("Clonar no Gemini", f"Pronto: a voz \"{nova.nome}\" foi criada no Gemini e já "
                                   "aparece em \"Voz principal do Gemini\" e na tabela \"Vozes dos personagens\".",
                                   "sucesso")))

        self._rodar(f"Clonando a voz \"{voz.nome}\" no Gemini...", tarefa)
