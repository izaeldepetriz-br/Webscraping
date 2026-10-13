"""Aba "🎧 Áudio" na janela moderna: ler as faixas, conferir o encaixe, ouvir 30 s, inserir/extrair e o histórico.

Separado de app_moderna.py (como a TV ao vivo): a AppModerna herda esta parte. A tela fica em painel_audio.py e o
trabalho pesado (ffmpeg, encaixe, volume) em jellyfin_tools/troca_audio.py. Tudo no PC, sem custo.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from tkinter import filedialog

from jellyfin_tools import troca_audio as ta
from jellyfin_tools.dublagem import ErroDublagem, caminho_amostra, localizar_ffmpeg

from . import automacao, config
from .painel_audio import JanelaTrocas, PainelAudio

_VLC: dict = {}                         # a instância do VLC (criada uma vez; None = não tem no PC)


def vlc_do_pc(programa: str | None = None):
    """O VLC instalado no PC, para tocar o vídeo dentro da aba (python-vlc). None: sem o VLC (ou de 32 bits num
    Maestro de 64), e o trecho abre no player padrão. programa: o vlc.exe achado (Configurações > Dublagem)."""
    if "instancia" in _VLC:
        return _VLC["instancia"]
    if programa and Path(programa).name.lower() == "vlc.exe":       # um VLC fora da pasta de sempre
        pasta = Path(programa).parent
        os.environ.setdefault("PYTHON_VLC_LIB_PATH", str(pasta / "libvlc.dll"))
        os.environ.setdefault("PYTHON_VLC_MODULE_PATH", str(pasta / "plugins"))
    try:
        import vlc
        instancia = vlc.Instance("--quiet", "--no-video-title-show")
    except Exception:                    # sem a biblioteca, sem o VLC ou um VLC que não carrega
        instancia = None
    _VLC["instancia"] = instancia
    return instancia


TIPOS_DE_VIDEO = [("Vídeos", "*.mkv *.mp4 *.m4v *.avi *.mov *.ts *.m2ts *.mts *.wmv *.webm *.vob *.mpg *.mka"),
                  ("Todos os arquivos", "*.*")]


class TrocaDeAudio:
    """Parte "🎧 Áudio" da AppModerna (usa self.fila, self._rodar, self.mostrar_mensagem... da janela)."""

    def _iniciar_troca_audio(self) -> None:
        self.painel_audio = None                # o painel da aba (montado na 1ª vez que ela abre)
        self._seq_ondas = 0                     # só a última leitura das ondas vale (as antigas são descartadas)

    @property
    def arquivo_trocas(self) -> Path:
        return config.ARQUIVO.parent / "trocas_audio.json"

    def ao_abrir_aba_audio(self) -> None:
        if self.painel_audio is not None and self.painel_audio.winfo_exists():
            return
        self.painel_audio = PainelAudio(self.aba_audio, self, {
            "escolher": self.audio_escolher, "ler": self.audio_ler, "conferir": self.audio_conferir,
            "ondas": self.audio_ondas, "ouvir": self.audio_ouvir, "amostras": lambda: self.ao_testes_feitos("audio"),
            "trocas": self.audio_trocas_feitas, "inserir": self.audio_inserir, "parar": self.ao_parar,
            "abrir_fora": self._abrir_trecho_fora, "vlc": self._vlc})
        self.painel_audio.grid(row=0, column=0, sticky="nsew")

    def _vlc(self):
        try:
            programa = automacao.programa_do_player(self.obter_opcoes_jellyfin())
        except Exception:
            programa = None
        return vlc_do_pc(programa)

    def _abrir_trecho_fora(self, caminho) -> None:
        try:
            self.abrir_video(str(caminho))
        except OSError as erro:
            self.mostrar_mensagem("Ver 30 s", f"Não deu para abrir o player: {erro}\n\nO trecho está em: {caminho}",
                                  "erro")

    def _soltar_previa(self) -> None:
        """O VLC da aba solta o trecho (para apagar o arquivo no Windows, ele não pode estar aberto)."""
        if self.painel_audio is not None and self.painel_audio.winfo_exists():
            self.painel_audio.previa.parar()

    def _ffmpeg_audio(self) -> str | None:
        ffmpeg = localizar_ffmpeg()
        if not ffmpeg:
            self.mostrar_mensagem("Áudio", "Não achei o ffmpeg (ele vem junto com o Maestro). Reinstale o Maestro ou "
                                  "instale o ffmpeg e tente de novo.", "erro")
        return ffmpeg

    def _mensagem_audio(self, tipo: str, *dados) -> None:
        """As respostas das tarefas da aba (na thread da janela)."""
        painel = self.painel_audio
        if painel is None or not painel.winfo_exists():
            return
        if tipo == "lido":
            painel.mostrar_arquivo(*dados)
        elif tipo == "encaixe":
            painel.mostrar_encaixe(*dados)
        elif tipo == "ondas":
            seq, ondas = dados
            if seq == self._seq_ondas:
                painel.mostrar_ondas(ondas)
        elif tipo == "amostra":                        # toca aqui dentro (VLC); sem o VLC, no player padrão
            saida, = dados
            if painel.previa.carregar(saida):
                painel.mostrar_previa()
            else:
                self._abrir_trecho_fora(saida)
        elif tipo == "feito":
            resultado, pedido = dados
            self._mostrar_troca_feita(resultado, pedido)

    # ---- 1 e 2: os arquivos
    def audio_escolher(self, lado: str) -> None:
        painel = self.painel_audio
        atual = painel.caminho(lado) or painel.caminho("origem" if lado == "destino" else "destino")
        caminho = filedialog.askopenfilename(
            parent=self, title="O arquivo com o áudio que você quer (origem)" if lado == "origem" else
            "O arquivo que vai receber a faixa (destino)", filetypes=TIPOS_DE_VIDEO,
            initialdir=str(Path(atual).parent) if atual else None)
        if caminho:
            painel.definir_caminho(lado, caminho)
            self.audio_ler(lado)

    def audio_ler(self, lado: str) -> None:
        """Lê as faixas do arquivo. Na origem, as faixas sem idioma marcado são ouvidas pelo Whisper (30 s)."""
        caminho = Path(self.painel_audio.caminho(lado))
        if not caminho.is_file():
            self.mostrar_mensagem("Áudio", f"Arquivo não encontrado:\n{caminho}", "aviso")
            return
        ffmpeg = self._ffmpeg_audio()
        if not ffmpeg or self.trabalhando:
            return
        o = self.obter_opcoes_jellyfin()

        def tarefa():
            info = ta.ler_arquivo(ffmpeg, caminho)
            if not info.audios and not info.videos:
                self.fila.put(("msg", ("Áudio", f"Não achei faixas de áudio nem de vídeo em:\n{caminho}", "aviso")))
            sem_idioma = [f for f in info.audios if not f.idioma or f.idioma == "und"] if lado == "origem" else []
            if sem_idioma:
                self._detectar_idiomas(ffmpeg, info, sem_idioma, o)
            self.fila.put(("audio", ("lido", lado, info)))
            self.fila.put(("status_fim", f"{caminho.name}: {info.resumo()}"))

        self._rodar("Lendo as faixas da origem..." if lado == "origem" else "Lendo as faixas do destino...", tarefa)

    def _detectar_idiomas(self, ffmpeg: str, info: ta.InfoArquivo, faixas: list, o) -> None:
        """Faixas sem etiqueta de idioma: o Whisper (no PC) ouve 30 s do meio do filme e diz o idioma."""
        try:
            from jellyfin_tools.transcricao import Transcritor
            transcritor = Transcritor(modelo=o.modelo_whisper, usar_gpu=o.whisper_gpu,
                                      pasta_modelos=self.pasta_modelos_whisper)
        except Exception as erro:                        # sem o Whisper: a pessoa escolhe o idioma na tabela
            self._log.warning("Áudio: sem o Whisper para descobrir o idioma (%s)", erro)
            return
        inicio = max(0.0, (info.duracao or 60) / 2 - 15)
        for k, faixa in enumerate(faixas):
            if self.evento_parar.is_set():
                return
            self.fila.put(("jf_analise", (k / len(faixas), f"O Whisper está ouvindo a faixa {faixa.ordem + 1}")))
            try:
                codigo = ta.detectar_idioma(ffmpeg, info.caminho, faixa, transcritor, inicio)
            except Exception as erro:
                self._log.warning("Áudio: não deu para descobrir o idioma da faixa %d: %s", faixa.ordem + 1, erro)
                continue
            if codigo:
                faixa.idioma, faixa.detectado = codigo, True
                self._log.info("Áudio: a faixa %d (sem idioma marcado) é %s (o Whisper ouviu 30 s)", faixa.ordem + 1,
                               ta.nome_idioma(codigo))

    def _pedido_audio(self, onde: str | None = None) -> ta.Pedido | None:
        painel = self.painel_audio
        pedido = painel.pedido(onde)
        if pedido is None:
            self.mostrar_mensagem("Áudio", "Escolha primeiro a origem e o destino.", "aviso")
            return None
        if not pedido.audios:
            self.mostrar_mensagem("Áudio", "Marque (☐) pelo menos uma faixa de áudio da origem.", "aviso")
            return None
        if painel.atraso() is None:
            self.mostrar_mensagem("Áudio", f"O atraso \"{painel.var_atraso.get()}\" não é um número (ex.: −4,30).",
                                  "aviso")
            return None
        return pedido

    # ---- 3: o encaixe
    def audio_conferir(self, manual: bool = False) -> None:
        """"Conferir encaixe" (automático: acha a velocidade e o atraso) ou "Conferir este ajuste" (o da tela)."""
        painel = self.painel_audio
        pedido = self._pedido_audio()
        ffmpeg = self._ffmpeg_audio() if pedido else None
        if not ffmpeg or self.trabalhando:
            return
        info_o, info_d = painel.info["origem"], painel.info["destino"]
        velocidade = painel.var_velocidade.get() if manual else "Automática"
        atraso = painel.atraso() if manual else None
        faixa, faixa_destino = pedido.audios[0].ordem, painel.faixa_destino()
        medir_volume = not manual or painel.lufs is None

        def progresso(fracao: float) -> None:
            self.fila.put(("jf_analise", (fracao * (0.8 if medir_volume else 1.0), "Comparando o começo, o meio e o "
                                                                                   "fim do filme")))

        def tarefa():
            try:
                encaixe = ta.conferir_encaixe(ffmpeg, pedido.origem, faixa, pedido.destino, faixa_destino,
                                              info_o.duracao, info_d.duracao, velocidade, atraso,
                                              parar=self.evento_parar.is_set, ao_progresso=progresso)
            except ErroDublagem as erro:
                if not self.evento_parar.is_set():
                    self.fila.put(("msg", ("Conferir encaixe", f"Não deu para conferir: {erro}", "erro")))
                return
            lufs = None
            if medir_volume and not self.evento_parar.is_set():
                self.fila.put(("jf_analise", (0.85, "Medindo o volume das duas faixas")))
                tempos = [p.tempo for p in encaixe.pontos]
                janela = min(60.0, max(6.0, (info_d.duracao or 60) / 6))
                original = ta.loudness(ffmpeg, pedido.destino, faixa_destino, tempos, janela)
                nova = ta.loudness(ffmpeg, pedido.origem, faixa,
                                   [max(0.0, (t - encaixe.atraso) / encaixe.fator) for t in tempos],
                                   janela / encaixe.fator)
                lufs = (nova, original)
            self._log.info("Áudio: %s (atraso %.3f s, fator %.5f; pontos: %s)", encaixe.texto_situacao(),
                           encaixe.atraso, encaixe.fator,
                           ", ".join(f"{ta.hms(p.tempo)}={p.atraso}" for p in encaixe.pontos))
            self.fila.put(("audio", ("encaixe", encaixe, lufs)))
            self.fila.put(("status_fim", encaixe.texto_situacao().split(":")[0] + "."))

        self._rodar("Conferindo este ajuste..." if manual else "Conferindo o encaixe...", tarefa)

    def audio_ondas(self) -> None:
        """As ondas do trecho escolhido (leve: roda ao lado, sem travar os botões; só a última pedida aparece)."""
        dados = self.painel_audio.dados_das_ondas()
        ffmpeg = localizar_ffmpeg()
        self._seq_ondas += 1
        seq = self._seq_ondas
        if dados is None or not ffmpeg:
            self.painel_audio.mostrar_ondas(None)
            return
        pedido, faixa_destino, inicio, duracao, ajustada, pontos = dados

        def trabalho():
            try:
                destino, nova = ta.ondas(ffmpeg, pedido, faixa_destino, inicio, duracao, ajustada, pontos)
                resposta = (destino, nova, inicio, duracao, ajustada)
            except Exception as erro:
                self._log.warning("Áudio: não deu para ler as ondas: %s", erro)
                resposta = None
            self.fila.put(("audio", ("ondas", seq, resposta)))

        threading.Thread(target=trabalho, daemon=True).start()

    def audio_ouvir(self) -> None:
        """"🎬 Ver 30 s": o trecho do destino (imagem) com a faixa nova (ajustada) e o áudio original depois. Toca
        dentro da aba (para ver se a boca bate com a voz); sem o VLC, no player."""
        painel = self.painel_audio
        pedido = self._pedido_audio()
        ffmpeg = self._ffmpeg_audio() if pedido else None
        if not ffmpeg or self.trabalhando:
            return
        total = painel.info["destino"].duracao or 30.0
        inicio = max(0.0, min(painel.inicio_da_amostra(), total - 30.0))
        saida = caminho_amostra(automacao.pasta_dublagem(), pedido.destino)
        detalhe = f"{ta.nome_idioma(pedido.audios[0].idioma)} · {pedido.ajuste.texto()}"

        def tarefa():
            try:
                ta.amostra(ffmpeg, pedido, inicio, saida, 30.0, parar=self.evento_parar.is_set,
                           ao_progresso=lambda f: self.fila.put(("jf_analise", (f, "Montando os 30 s"))))
            except ErroDublagem as erro:
                if not self.evento_parar.is_set():
                    self.fila.put(("msg", ("Ver 30 s", f"Não deu para montar o trecho: {erro}", "erro")))
                return
            automacao.registrar_teste(pedido.destino, saida, (inicio, min(total, inicio + 30.0)), aba="audio",
                                      detalhe=detalhe)
            self._log.info("Áudio: amostra de 30 s a partir de %s (%s): %s", ta.hms(inicio), detalhe, saida)
            self.fila.put(("audio", ("amostra", saida)))
            self.fila.put(("status_fim", f"Trecho pronto (a partir de {ta.hms(inicio)}): veja se a boca bate com a "
                                         "voz; \"Ouvir: Original\" troca para o áudio do destino, no mesmo ponto."))

        self._rodar("Montando a amostra de 30 s...", tarefa)

    # ---- inserir / extrair
    def audio_inserir(self, onde: str | None = None) -> None:
        """"Inserir N faixas" (no próprio arquivo, conferido antes de trocar, ou numa cópia) ou "Só extrair (.mka)"."""
        painel = self.painel_audio
        pedido = self._pedido_audio(onde)
        ffmpeg = self._ffmpeg_audio() if pedido else None
        if not ffmpeg or self.trabalhando:
            return
        encaixe = painel.encaixe
        if encaixe is not None and encaixe.situacao == "cortes" and pedido.onde != "extrair":
            self.mostrar_mensagem("Inserir", "As versões são diferentes (o atraso muda ao longo do filme): a faixa "
                                  "ficaria fora de sincronia em parte dele. Confira outro ajuste antes.", "aviso")
            return
        n = len(pedido.audios)
        nomes = ", ".join(ta.nome_idioma(f.idioma) for f in pedido.audios)
        if pedido.onde == "extrair":
            saida = ta.saida_extraida(pedido.destino, pedido.audios[0].idioma)
            acao = f"Extrair {n} faixa(s) de áudio ({nomes}) já ajustada(s) para:\n{saida}"
        elif pedido.onde == "copia":
            saida = ta.saida_da_copia(pedido.destino, pedido.audios[0].idioma)
            acao = (f"Criar uma cópia do destino com {n} faixa(s) de áudio a mais ({nomes}):\n{saida}\n\nO destino "
                    "original não é mexido.")
        else:
            acao = (f"Inserir {n} faixa(s) de áudio ({nomes}) dentro de:\n{pedido.destino}\n\nA cópia nova é "
                    "conferida (duração e faixas) antes de tomar o lugar do original.")
        legendas = (f"\nLegendas que vão junto: {', '.join(ta.nome_idioma(s.idioma) for s in pedido.legendas)}"
                    if pedido.legendas and pedido.onde != "extrair" else "")
        refaz = ("o áudio é refeito (AC3, mesma qualidade) por causa da velocidade/volume" if pedido.ajuste.refaz_audio
                 else "a faixa é copiada como está (sem perder qualidade)")
        avisos = []
        if encaixe is None:
            avisos.append("⚠ O encaixe ainda não foi conferido: vai o ajuste da tela. O recomendado é \"Conferir "
                          "encaixe\" e ouvir os 30 s antes.")
        elif not painel.encaixe_valido:
            avisos.append("⚠ O ajuste mudou depois da última conferência.")
        elif encaixe.situacao == "sem_dados":
            avisos.append("⚠ A conferência não conseguiu medir (pouco som em comum): ouça os 30 s antes.")
        valido = painel.encaixe_valido
        texto = (f"{acao}{legendas}\n\nAjuste: {pedido.ajuste.texto()} ({refaz})."
                 + ("\n\n" + "\n".join(avisos) if avisos else ""))
        if not self.perguntar("Só extrair" if pedido.onde == "extrair" else "Inserir as faixas", texto):
            return

        def tarefa():
            try:
                resultado = ta.executar(ffmpeg, pedido, parar=self.evento_parar.is_set,
                                        ao_progresso=lambda f: self.fila.put(("jf_analise", (f, "Juntando a faixa"))))
            except ErroDublagem as erro:
                if not self.evento_parar.is_set():
                    self.fila.put(("msg", ("Inserir", f"Não deu certo: {erro}\n\nO arquivo de destino não foi "
                                                      "mexido.", "erro")))
                return
            ta.registrar_troca(self.arquivo_trocas, pedido, resultado, encaixe if valido else None)
            self._log.info("Áudio: %s -> %s (%s)", pedido.origem.name, resultado.saida, pedido.ajuste.texto())
            for aviso in resultado.avisos:
                self._log.warning("Áudio: %s", aviso)
            self.fila.put(("audio", ("feito", resultado, pedido)))
            self.fila.put(("status_fim", f"Pronto: {resultado.saida.name}"))

        self._rodar("Extraindo a faixa..." if pedido.onde == "extrair" else "Inserindo a faixa...", tarefa)

    def _mostrar_troca_feita(self, resultado: ta.Resultado, pedido: ta.Pedido) -> None:
        avisos = ("\n\nAvisos:\n• " + "\n• ".join(resultado.avisos)) if resultado.avisos else ""
        if pedido.onde == "extrair":
            texto = f"A faixa ajustada está em:\n{resultado.saida}"
        elif pedido.onde == "copia":
            texto = f"A cópia com a faixa nova está em:\n{resultado.saida}"
        else:
            texto = (f"A faixa nova está dentro de:\n{resultado.saida}\n\nNo Jellyfin, escolha o áudio no player (ou "
                     "atualize a biblioteca para ver a faixa nova).")
        self.mostrar_mensagem("Pronto", texto + "\n\nFica registrado em 📜 Trocas feitas." + avisos, "info")
        if pedido.onde == "dentro" and Path(self.painel_audio.caminho("destino")) == pedido.destino:
            if resultado.saida != pedido.destino:          # o .avi virou .mkv, por exemplo
                self.painel_audio.definir_caminho("destino", str(resultado.saida))
            self._reler_destino_quando_livre()             # o "Já tem" mostra a faixa nova

    def _reler_destino_quando_livre(self, tentativas: int = 50) -> None:
        """Lê o destino de novo assim que a tarefa que inseriu terminar (o "fim" dela chega depois desta resposta)."""
        if self.trabalhando and tentativas > 0:
            self.after(200, lambda: self._reler_destino_quando_livre(tentativas - 1))
        elif not self.trabalhando:
            self.audio_ler("destino")

    # ---- 📜 Trocas feitas
    def audio_trocas_feitas(self) -> None:
        JanelaTrocas(self, lambda: ta.trocas_feitas(self.arquivo_trocas), self._abrir_troca, self._pasta_da_troca,
                     self._tirar_trocas)

    def _abrir_troca(self, troca: dict) -> None:
        saida = Path(str(troca.get("saida", "")))
        if not saida.is_file():
            self.mostrar_mensagem("Trocas feitas", f"O arquivo não está mais lá:\n{saida}", "aviso")
            return
        try:
            self.abrir_video(str(saida))
        except OSError as erro:
            self.mostrar_mensagem("Trocas feitas", f"Não deu para abrir: {erro}", "erro")

    def _pasta_da_troca(self, troca: dict) -> None:
        self._abrir_no_sistema(str(Path(str(troca.get("saida", ""))).parent))

    def _tirar_trocas(self, trocas: list) -> bool:
        if not self.perguntar("Tirar do histórico", f"Tirar {len(trocas)} troca(s) do histórico? Os arquivos não são "
                              "apagados."):
            return False
        ta.apagar_trocas(self.arquivo_trocas, trocas)
        return True
