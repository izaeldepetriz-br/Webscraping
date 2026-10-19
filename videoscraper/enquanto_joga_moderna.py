"""Aba "🎮 Jogos", modo "🖥 Enquanto joga (tradutor de tela)": a ligação da tela (painel_enquanto_joga.py) com o
trabalho (jellyfin_tools.tela_jogo e legenda_ao_vivo) e com a janelinha por cima do jogo (sobreposicao.py).

O tradutor de tela e a legenda ao vivo rodam em segundo plano (não usam o "trabalhando" da janela: dá para continuar
usando o Maestro). As frases já traduzidas ficam guardadas (frases_jogo.json): a mesma frase não paga de novo.
"""

from __future__ import annotations

import tempfile
import time
import wave
from pathlib import Path

from jellyfin_tools import legenda_ao_vivo as lv
from jellyfin_tools import tela_jogo as tj
from jellyfin_tools import voz_local

from . import automacao, config
from .painel_enquanto_joga import AREAS, TRADUTORES, VOZES_AO_VIVO, WHISPERS, PainelEnquantoJoga
from .sobreposicao import ROXO, MarcarArea, Sobreposicao


class EnquantoJoga:
    """Parte "Enquanto joga" da aba 🎮 Jogos."""

    def _iniciar_enquanto_joga(self) -> None:
        self.painel_enquanto_joga = None
        self.sobreposicao = None
        self._tradutor_de_tela = None
        self._legenda_ao_vivo = None
        self._atalho = None
        self._area_marcada: tuple | None = None          # relativa à janela do jogo
        self._alvo_tela: tuple = (None, False)           # (janela, usar a área marcada): o que as tarefas leem
        self._memoria_tela = None

    def painel_do_modo_enquanto(self) -> PainelEnquantoJoga:
        if self.painel_enquanto_joga is None or not self.painel_enquanto_joga.winfo_exists():
            self.painel_enquanto_joga = PainelEnquantoJoga(self.aba_jogos, self, {
                "atualizar_janelas": self.enquanto_atualizar_janelas, "janela": self.enquanto_previa,
                "previa": self.enquanto_previa, "tela": lambda: self.enquanto_ligar(
                    "tela", self.painel_enquanto_joga.var_tela.get()),
                "marcar": self.enquanto_marcar_area, "legenda": lambda: self.enquanto_ligar(
                    "legenda", self.painel_enquanto_joga.var_legenda.get()),
                "voz": self.enquanto_mudou_voz, "traduzir_agora": self.enquanto_traduzir_agora})
            for var in (self.painel_enquanto_joga.var_janela, self.painel_enquanto_joga.var_area):
                var.trace_add("write", lambda *a: self._guardar_alvo())
            self.enquanto_atualizar_janelas()
        return self.painel_enquanto_joga

    # ------------------------------------------------------------------ a janela do jogo
    def enquanto_atualizar_janelas(self) -> None:
        p = self.painel_enquanto_joga
        p.mostrar_janelas([j for j in tj.janelas_abertas() if "Maestro" not in j.titulo])
        self.enquanto_previa()

    def _janela_do_jogo(self):
        p = self.painel_do_modo_enquanto()
        return p.janela_escolhida()

    def _guardar_alvo(self) -> None:
        """A janela e a área escolhidas, copiadas para o tradutor de tela (as tarefas não podem ler os campos)."""
        p = self.painel_enquanto_joga
        self._alvo_tela = (p.janela_escolhida(), p.var_area.get() == AREAS[1])

    def _area_na_tela(self) -> tuple:
        """O retângulo que o tradutor de tela fotografa (roda na tarefa: usa só o que _guardar_alvo copiou)."""
        janela, so_a_marcada = self._alvo_tela
        if janela is None:
            raise tj.ErroTela("escolha a janela do jogo")
        esquerda, topo, direita, baixo = tj.retangulo_atual(janela)
        if so_a_marcada and self._area_marcada:
            x0, y0, x1, y1 = self._area_marcada
            return esquerda + x0, topo + y0, esquerda + x1, topo + y1
        return esquerda, topo, direita, baixo

    def enquanto_previa(self) -> None:
        """A foto da janela com a caixa roxa (a janelinha do Maestro) desenhada por cima."""
        janela = self._janela_do_jogo()
        if janela is None:
            return
        try:
            foto = tj.capturar(tj.retangulo_atual(janela))
        except Exception as erro:
            self._log.info("Prévia da janela do jogo: %s", erro)
            self.painel_enquanto_joga.mostrar_previa(None)
            return
        from PIL import ImageDraw
        foto = foto.convert("RGB")
        d = ImageDraw.Draw(foto, "RGBA")
        largura, altura = foto.size
        if self._area_marcada and self.painel_enquanto_joga.var_area.get() == AREAS[1]:
            d.rectangle(self._area_marcada, outline=(250, 204, 21, 255), width=max(2, largura // 300))
        caixa = (largura * 0.08, altura * 0.62, largura * 0.92, altura * 0.80)
        d.rounded_rectangle(caixa, radius=max(6, largura // 90), fill=(20, 15, 36, 225), outline=ROXO,
                            width=max(2, largura // 320))
        d.text((caixa[0] + 12, caixa[1] + 8), "Maestro · tradução da tela", fill=(196, 181, 253, 255))
        d.text((caixa[0] + 12, caixa[1] + 30), self._ultima_traducao_tela() or "A tradução aparece aqui.",
               fill=(255, 255, 255, 255))
        self.painel_enquanto_joga.mostrar_previa(foto)

    def _ultima_traducao_tela(self) -> str:
        s = self.sobreposicao
        return s.lb_tela.cget("text") if s is not None and s.winfo_exists() else ""

    def enquanto_marcar_area(self) -> None:
        janela = self._janela_do_jogo()
        if janela is None:
            self.mostrar_mensagem("Marcar a área", "Escolha a janela do jogo primeiro (1. Janela do jogo).", "aviso")
            return
        marcar = MarcarArea(self, tj.retangulo_atual(janela))
        self.wait_window(marcar)
        if marcar.resultado:
            self._area_marcada = marcar.resultado
            self.painel_enquanto_joga.var_area.set(AREAS[1])
            self.guardar_preferencia_jogos("area_marcada", list(marcar.resultado))
            self.enquanto_previa()

    # ------------------------------------------------------------------ ligar e desligar
    def _sobreposicao(self) -> Sobreposicao:
        if self.sobreposicao is None or not self.sobreposicao.winfo_exists():
            self.sobreposicao = Sobreposicao(self)
        return self.sobreposicao

    def _traduzir_ao_vivo(self, qual: str):
        """traduzir(texto) -> tradução, pelo tradutor escolhido (o grátis no PC, o Gemini Flash ou o Claude)."""
        o = self.obter_opcoes_jellyfin()
        escolha = self.painel_do_modo_enquanto().var_tradutor.get()
        if escolha == TRADUTORES[1]:
            if not automacao.chave_gemini(o):
                raise automacao.FaltaConfiguracao("Para o Gemini Flash, cole a chave do Google AI Studio (a grátis "
                                                  "serve) em Configurações > Chaves de API.")
            from jellyfin_tools.traducao_gemini import TradutorGemini
            tradutor = TradutorGemini(automacao.chave_gemini(o))
        elif escolha == TRADUTORES[2]:
            import os

            from jellyfin_tools.traducao import Tradutor
            if not (o.chave_claude or os.environ.get("ANTHROPIC_API_KEY")):
                raise automacao.FaltaConfiguracao("Para o Claude, cole a chave da Anthropic em Configurações > Chaves "
                                                  "de API (ou escolha \"Grátis no PC\").")
            tradutor = Tradutor(chave=o.chave_claude, modelo="claude-haiku-5-5")
        else:
            from jellyfin_tools.traducao_local import TradutorLocal
            tradutor = TradutorLocal(automacao.pasta_traducao_local(), "pt-BR")
        return lambda texto: tradutor.traduzir_falas([texto], "jogo")[0]

    def _memoria(self) -> tj.MemoriaDeFrases:
        if self._memoria_tela is None:
            self._memoria_tela = tj.MemoriaDeFrases(config.ARQUIVO.parent / "frases_jogo.json")
        return self._memoria_tela

    def enquanto_ligar(self, qual: str, ligado: bool) -> bool:
        """Liga/desliga o tradutor de tela ("tela") ou a legenda ao vivo ("legenda"). False se não deu para ligar."""
        p = self.painel_do_modo_enquanto()
        var = p.var_tela if qual == "tela" else p.var_legenda
        var.set(ligado)
        atalho_painel = getattr(self.painel_jogos, "var_atalho_tela" if qual == "tela" else "var_atalho_legenda",
                                None) if self.painel_jogos is not None else None
        if not ligado:
            self._desligar(qual)
            if atalho_painel is not None:
                atalho_painel.set(False)
            return True
        try:
            if qual == "tela":
                self._ligar_tela()
            else:
                self._ligar_legenda()
        except (tj.ErroTela, lv.ErroLegenda, automacao.FaltaConfiguracao) as erro:
            var.set(False)
            if atalho_painel is not None:
                atalho_painel.set(False)
            self.mostrar_mensagem("Enquanto joga", str(erro), "aviso")
            return False
        if atalho_painel is not None:
            atalho_painel.set(True)
        janela = self._janela_do_jogo()
        if janela is not None and self.painel_jogos is not None:
            self.painel_jogos.lb_janela_atalho.configure(text=f"Janela: {janela.titulo[:50]}")
        return True

    def _ligar_tela(self) -> None:
        p = self.painel_enquanto_joga
        if self._janela_do_jogo() is None:
            raise tj.ErroTela("abra o jogo no emulador e escolha a janela dele (1. Janela do jogo)")
        leitor = tj.leitor_de_texto("en")
        traduzir = self._traduzir_ao_vivo("tela")
        if self._area_marcada is None:
            marcada = self.preferencia_jogos("area_marcada")
            self._area_marcada = tuple(marcada) if marcada else None
        self._desligar("tela")
        self._guardar_alvo()
        self._tradutor_de_tela = tj.TradutorDeTela(
            self._area_na_tela, leitor, traduzir,
            lambda original, traducao: self.fila.put(("jogos", ("e_tela", original, traducao))),
            self._memoria(), sozinho=p.var_sozinho.get(),
            avisar=lambda texto: self.fila.put(("jogos", ("e_aviso_tela", texto))))
        self._tradutor_de_tela.comecar()
        self._atalho = tj.AtalhoGlobal(p.var_atalho.get(), self.enquanto_traduzir_agora)
        com_atalho = self._atalho.comecar()
        p.mostrar_estado_tela(f"✓ Lendo a janela com o leitor {leitor.nome}" +
                              (f" · atalho {p.var_atalho.get()} traduz na hora" if com_atalho else ""))
        self._log.info("Enquanto joga: tradutor de tela ligado (%s, %s)", leitor.nome, p.var_tradutor.get())
        self._sobreposicao().posicionar(tj.retangulo_atual(self._janela_do_jogo()))

    def _ligar_legenda(self) -> None:
        p = self.painel_enquanto_joga
        o = self.obter_opcoes_jellyfin()
        traduzir = self._traduzir_ao_vivo("legenda")
        from jellyfin_tools.transcricao import Transcritor
        modelo = p.var_whisper.get().split(" · ")[0]
        transcritor = Transcritor(modelo=modelo, usar_gpu=p.var_whisper.get() == WHISPERS[0],
                                  pasta_modelos=str(config.ARQUIVO.parent / "modelos_whisper"))
        captura = lv.CapturaDoSom()
        self._desligar("legenda")
        janela = self._janela_do_jogo()
        falar, volume = (self._falar_ao_vivo(o), lv.VolumeDoJogo(janela.processo) if janela else None) \
            if p.var_falar.get() else (None, None)
        self._legenda_ao_vivo = lv.LegendaAoVivo(
            captura, lv.ouvinte_whisper(transcritor), traduzir,
            lambda original, traducao: self.fila.put(("jogos", ("e_legenda", original, traducao))),
            falar=falar, volume=volume, memoria=self._memoria(),
            avisar=lambda texto: self.fila.put(("jogos", ("e_aviso_vozes", texto))))
        self._legenda_ao_vivo.comecar()
        p.mostrar_estado_vozes(f"✓ Ouvindo o som do PC ({captura.nome}) · Whisper {modelo}")
        self._log.info("Enquanto joga: legenda ao vivo ligada (Whisper %s)", modelo)
        if janela is not None:
            self._sobreposicao().posicionar(tj.retangulo_atual(janela))

    def _falar_ao_vivo(self, o):
        """falar(texto): a voz traduzida (XTTS-v2 no PC ou Gemini), tocada até o fim (o som do jogo abaixado)."""
        import dataclasses
        p = self.painel_enquanto_joga
        motor_voz = voz_local.NOME if p.var_voz.get() == VOZES_AO_VIVO[0] else self.MOTORES_VOZ[1]
        motor = automacao.preparar_motor(dataclasses.replace(o, motor_voz=motor_voz, conferir_falas=False,
                                                             figurantes_piper=False))
        pasta = Path(tempfile.mkdtemp(prefix="maestro-voz-"))

        def falar(texto: str) -> None:
            wav = pasta / "fala.wav"
            wav.unlink(missing_ok=True)
            motor.sintetizar([(texto, wav)])
            from jellyfin_tools import microfone
            microfone.tocar(wav)
            with wave.open(str(wav)) as w:
                time.sleep(w.getnframes() / max(1, w.getframerate()))
        self._motor_ao_vivo = motor
        return falar

    def enquanto_mudou_voz(self) -> None:
        """Ligou/desligou "Ler em voz alta": com a legenda ligada, reinicia ela com (ou sem) a voz."""
        p = self.painel_enquanto_joga
        if self._legenda_ao_vivo is not None and p.var_legenda.get():
            self.enquanto_ligar("legenda", True)

    def enquanto_traduzir_agora(self) -> None:
        if self._tradutor_de_tela is not None:
            self._tradutor_de_tela.agora()

    def _desligar(self, qual: str) -> None:
        if qual == "tela":
            if self._tradutor_de_tela is not None:
                self._tradutor_de_tela.parar()
                fechar = getattr(self._tradutor_de_tela.leitor, "fechar", None)   # a tarefa do leitor do Windows
                if fechar is not None:
                    fechar()
                self._tradutor_de_tela = None
            if self._atalho is not None:
                self._atalho.parar()
                self._atalho = None
            if self.painel_enquanto_joga is not None:
                self.painel_enquanto_joga.mostrar_estado_tela("")
        else:
            if self._legenda_ao_vivo is not None:
                self._legenda_ao_vivo.parar()
                try:
                    self._legenda_ao_vivo.captura.fechar()
                except Exception:
                    pass
                self._legenda_ao_vivo = None
            motor = getattr(self, "_motor_ao_vivo", None)
            if motor is not None and hasattr(motor, "fechar"):
                motor.fechar()
                self._motor_ao_vivo = None
            if self.painel_enquanto_joga is not None:
                self.painel_enquanto_joga.mostrar_estado_vozes("")
        if self._tradutor_de_tela is None and self._legenda_ao_vivo is None and self.sobreposicao is not None \
                and self.sobreposicao.winfo_exists():
            self.sobreposicao.esconder()

    def desligar_enquanto_joga(self) -> None:
        """Ao fechar o Maestro: para tudo (as tarefas em segundo plano e o atalho)."""
        for qual in ("tela", "legenda"):
            try:
                self._desligar(qual)
            except Exception:
                pass

    def _mensagem_enquanto(self, tipo: str, *dados) -> None:
        if tipo == "e_tela":
            original, traducao = dados
            self._sobreposicao().mostrar_tela(traducao)
            self._log.info("Tela: %s -> %s", original[:80], traducao[:80])
        elif tipo == "e_legenda":
            original, traducao = dados
            self._sobreposicao().mostrar_legenda(traducao)
        elif tipo == "e_aviso_tela" and self.painel_enquanto_joga is not None:
            self.painel_enquanto_joga.mostrar_estado_tela(f"⚠ {dados[0]}", False)
        elif tipo == "e_aviso_vozes" and self.painel_enquanto_joga is not None:
            self.painel_enquanto_joga.mostrar_estado_vozes(f"⚠ {dados[0]}", False)

