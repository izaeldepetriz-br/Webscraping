"""Configurações > Dublagem na janela moderna: "Importar voz" (importar, juntar gravações de emoção e remover), o
motor de vozes XTTS-v2 no PC (instalar, remover e ouvir uma frase de teste) e o Chatterbox (as falas com emoção).

Separado de app_moderna.py (como a aba Áudio): a AppModerna herda esta parte. Os campos ficam em gui_moderna.py e o
trabalho com os arquivos em jellyfin_tools/vozes_importadas.py.
"""

from __future__ import annotations

from jellyfin_tools import emocoes, voz_emocao, voz_local
from jellyfin_tools import vozes_importadas as vi
from jellyfin_tools.dublagem import ErroDublagem, localizar_ffmpeg

from . import automacao, config


class ImportarVozes:
    def _iniciar_vozes_importadas(self) -> None:
        self.atualizar_vozes_importadas(automacao.vozes_importadas())
        self._chatterbox = voz_emocao.instalado(automacao.pasta_motor_local())
        self.atualizar_motor_local(voz_local.instalado(automacao.pasta_motor_local()))

    def _guardar_vozes_importadas(self, vozes: list) -> None:
        vi.salvar(vozes, automacao.arquivo_vozes_importadas())
        self.atualizar_vozes_importadas(vozes)

    def _limpar_campos_importar(self) -> None:
        for var in (self.var_imp_arquivo, self.var_imp_nome):
            var.set("")
        self.var_imp_autorizo.set(False)
        self.var_imp_emocao.set(self.EMOCAO_NORMAL)

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
        emocao = emocoes.emocao_do_menu(self.var_imp_emocao.get())
        if emocao != emocoes.NORMAL:
            self._importar_emocao(arquivo, emocao, tipo, existentes, pasta)
            return
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

    def _importar_emocao(self, arquivo: str, emocao: str, tipo: str, existentes: list, pasta) -> None:
        """Uma gravação de EMOÇÃO para uma voz já importada (o nome diz qual)."""
        try:
            if tipo != vi.GRAVACAO:
                raise ErroDublagem("a gravação de emoção é um áudio (.wav, .mp3, .m4a...), não um modelo do Piper")
            voz = vi.achar_gravacao(self.var_imp_nome.get(), existentes)
        except ErroDublagem as erro:
            self.mostrar_mensagem("Importar voz", f"Não deu para importar: {erro}.", "aviso")
            return
        ffmpeg = localizar_ffmpeg()
        if not ffmpeg:
            self.mostrar_mensagem("Importar voz", "Falta o ffmpeg para ler a gravação (pip install imageio-ffmpeg).",
                                  "erro")
            return
        declaro = self.var_imp_autorizo.get()

        def tarefa():
            try:
                vi.importar_emocao(arquivo, voz, emocao, declaro, pasta, ffmpeg)
            except (ErroDublagem, OSError) as erro:
                self._log.warning("Importar gravação de emoção: %s", erro)
                self.fila.put(("msg", ("Importar voz", f"Não deu para importar: {erro}.", "aviso")))
                return
            vi.salvar(existentes, automacao.arquivo_vozes_importadas())
            self._log.info("Gravação de emoção importada: %s (%s)", voz.nome, emocao)
            self.fila.put(("vozes_importadas", existentes))
            self.fila.put(("msg", ("Importar voz", f"Pronto: a voz \"{voz.nome}\" agora tem a gravação "
                                   f"\"{emocoes.nome_da_emocao(emocao)}\". As falas com essa emoção vão com ela no "
                                   "XTTS-v2.", "sucesso")))

        self._rodar(f"Importando a gravação de emoção de {voz.nome}...", tarefa)

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

    # ---- o motor de vozes XTTS-v2 (grátis, no PC)
    def ao_instalar_motor_local(self) -> None:
        pasta = automacao.pasta_motor_local()
        gpu = voz_local.tem_placa_nvidia()
        tamanho = "~3 GB (com a placa de vídeo NVIDIA)" if gpu else "~1 GB (sem placa NVIDIA: vai pelo processador)"
        if not self.perguntar("Instalar o motor de vozes", f"Instalar o XTTS-v2 neste PC? Baixa {tamanho} uma vez, "
                              "e o modelo (~1,8 GB) na 1ª fala. Tudo fica na pasta das configurações (\"Remover do "
                              "PC\" apaga).\n\nLicença do modelo (CPML da Coqui): só uso pessoal, NÃO comercial. "
                              "Instalando, você aceita essa licença."):
            return

        def tarefa():
            try:
                info = voz_local.instalar(pasta, gpu=gpu, parar=self.evento_parar.is_set,
                                          ao_progresso=lambda f, texto: self.fila.put(("jf_analise", (f, texto))))
            except (ErroDublagem, OSError) as erro:
                self._log.warning("Instalar o motor de vozes: %s", erro)
                self.fila.put(("msg", ("Instalar o motor de vozes", f"Não deu para instalar: {erro}.", "erro")))
                return
            self._log.info("Motor de vozes XTTS-v2 instalado (%s)", "placa de vídeo" if info["gpu"] else "processador")
            self.fila.put(("motor_local", info))

        self._rodar("Instalando o motor de vozes XTTS-v2...", tarefa)

    def _motor_local_instalado(self, info: dict) -> None:
        """Depois de instalar: mostra e oferece trocar a voz da dublagem pelo XTTS-v2."""
        self.atualizar_motor_local(info)
        if self.var_jf_motor_voz.get().startswith("XTTS"):
            self.mostrar_mensagem("Motor de vozes", "Pronto: o XTTS-v2 está instalado. Use \"▶ Ouvir uma frase de "
                                  "teste\" (na 1ª vez baixa o modelo, ~1,8 GB).", "sucesso")
            return
        if self.perguntar("Motor de vozes", "Pronto: o XTTS-v2 está instalado. Usar ele na dublagem agora, no lugar "
                          "do motor atual? (dá para voltar no cartão \"Quem lê as falas\")"):
            self.var_jf_modo_voz.set("local")
            self._ao_escolher_modo_voz()
            self._sincronizar_modo_voz()
            self._salvar_config()

    def ao_remover_motor_local(self) -> None:
        pasta = automacao.pasta_motor_local()
        if not self.perguntar("Remover o motor de vozes", "Apagar o XTTS-v2 deste PC (o Python, o PyTorch e o modelo, "
                              "alguns GB; e o Chatterbox, se instalado)? As vozes importadas continuam. Para usar de "
                              "novo, é preciso instalar."):
            return
        voz_local.desinstalar(pasta)
        self._chatterbox = None
        self.atualizar_motor_local(None)
        if self.var_jf_motor_voz.get().startswith("XTTS"):       # sem o motor: volta para o Piper
            self.var_jf_modo_voz.set("piper")
            self._ao_escolher_modo_voz()
            self._sincronizar_modo_voz()
        self._salvar_config()
        self._log.info("Motor de vozes XTTS-v2 removido")

    # ---- o Chatterbox: o 2º motor, só para as falas com emoção
    def ao_instalar_chatterbox(self) -> None:
        pasta = automacao.pasta_motor_local()
        if not voz_local.instalado(pasta):
            self.mostrar_mensagem("Instalar o Chatterbox", "Instale primeiro o motor de vozes XTTS-v2 (o Chatterbox "
                                  "imita as vozes dele).", "aviso")
            return
        gpu = voz_local.tem_placa_nvidia()
        tamanho = "~5 GB (com a placa de vídeo NVIDIA)" if gpu else "~1 GB (sem placa NVIDIA: vai pelo processador)"
        if not self.perguntar("Instalar o Chatterbox", f"Instalar o Chatterbox neste PC, para as falas com emoção? "
                              f"Baixa {tamanho} uma vez, e o modelo (~3,2 GB) na 1ª fala com emoção. Fica dentro do "
                              "motor de vozes (\"Remover o Chatterbox\" apaga).\n\nLicença: MIT (uso livre). O "
                              "áudio gerado leva uma marca d'água inaudível que diz \"voz feita por IA\"."):
            return

        def tarefa():
            try:
                info = voz_emocao.instalar(pasta, gpu=gpu, parar=self.evento_parar.is_set,
                                           ao_progresso=lambda f, texto: self.fila.put(("jf_analise", (f, texto))))
            except (ErroDublagem, OSError) as erro:
                self._log.warning("Instalar o Chatterbox: %s", erro)
                self.fila.put(("msg", ("Instalar o Chatterbox", f"Não deu para instalar: {erro}.", "erro")))
                return
            self._log.info("Chatterbox instalado (%s)", "placa de vídeo" if info["gpu"] else "processador")
            self.fila.put(("chatterbox", info))

        self._rodar("Instalando o Chatterbox (emoção)...", tarefa)

    def _chatterbox_instalado(self, info: dict) -> None:
        self.atualizar_chatterbox(info)
        self.var_jf_emocao_chatterbox.set(True)
        self._salvar_config()
        self.mostrar_mensagem("Chatterbox", "Pronto: as falas com emoção (gritadas, choradas, sussurradas...) que não "
                              "têm a gravação da emoção vão pelo Chatterbox, com a mesma voz. Confira num teste de 1 "
                              "minuto antes de dublar o filme inteiro.", "sucesso")

    def ao_remover_chatterbox(self) -> None:
        if not self.perguntar("Remover o Chatterbox", "Apagar o Chatterbox deste PC (o PyTorch e o modelo, alguns "
                              "GB)? O XTTS-v2 continua; as falas com emoção sem a gravação da emoção saem neutras."):
            return
        voz_emocao.desinstalar(automacao.pasta_motor_local())
        self.atualizar_chatterbox(None)
        self._log.info("Chatterbox removido")

    def ao_ouvir_voz_local(self) -> None:
        o = self.obter_opcoes_jellyfin()
        destino = config.ARQUIVO.parent / "frase_de_teste_xtts.wav"

        def tarefa():
            motor = None
            try:
                motor = automacao.motor_local(o, avisar=lambda texto: self.fila.put(("jf_analise", (0.5, texto))))
                destino.unlink(missing_ok=True)
                motor.sintetizar([(voz_local.FRASE_DE_TESTE, destino, o.voz_local)], parar=self.evento_parar.is_set)
            except (ErroDublagem, automacao.FaltaConfiguracao, OSError) as erro:
                self._log.warning("Frase de teste do XTTS-v2: %s", erro)
                self.fila.put(("msg", ("Ouvir a voz", f"Não deu para gerar a frase: {erro}.", "erro")))
                return
            finally:
                if motor is not None:
                    motor.fechar()
            self._log.info("Frase de teste do XTTS-v2 com a voz %s (%s)", o.voz_local,
                           motor.placa or motor.dispositivo or "?")
            self.fila.put(("tocar", destino))

        self._rodar(f"Gerando a frase de teste com o XTTS-v2 ({o.voz_local})...", tarefa)
