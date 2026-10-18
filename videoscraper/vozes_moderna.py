"""Configurações > Dublagem > "Importar voz" na janela moderna: importar e remover.

Separado de app_moderna.py (como a aba Áudio): a AppModerna herda esta parte. Os campos ficam em gui_moderna.py e o
trabalho com os arquivos em jellyfin_tools/vozes_importadas.py.
"""

from __future__ import annotations

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
        for var in (self.var_imp_arquivo, self.var_imp_nome):
            var.set("")
        self.var_imp_autorizo.set(False)

    def _perfil_importar(self) -> tuple[str, str]:
        return self.var_imp_genero.get().lower(), self.var_imp_idade.get().lower()

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
                nova = vi.importar_piper(arquivo, self.var_imp_nome.get(), pasta / "vozes", existentes,
                                         *self._perfil_importar())
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
        genero, idade = self._perfil_importar()
        pedido = dict(referencia=arquivo, nome=self.var_imp_nome.get(), genero=genero, idade=idade,
                      declaro=self.var_imp_autorizo.get())

        def tarefa():
            try:
                nova = vi.importar_gravacao(pedido["referencia"], pedido["nome"], pedido["genero"], pedido["idade"],
                                            pedido["declaro"], pasta, ffmpeg, existentes)
            except (ErroDublagem, OSError) as erro:
                self._log.warning("Importar gravação de voz: %s", erro)
                self.fila.put(("msg", ("Importar voz", f"Não deu para importar: {erro}.", "aviso")))
                return
            vozes = existentes + [nova]
            vi.salvar(vozes, automacao.arquivo_vozes_importadas())
            self._log.info("Gravação de voz importada: %s (%s)", nova.nome, nova.perfil)
            self.fila.put(("vozes_importadas", vozes))
            self.fila.put(("msg", ("Importar voz", f"Pronto: a voz \"{nova.nome}\" ({nova.perfil}) ficou guardada "
                                   "neste PC e já aparece nas vozes do XTTS-v2 (o motor de vozes grátis no PC).",
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
