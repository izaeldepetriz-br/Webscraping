"""Aba "🎮 Jogos", modo "🗣 Traduzir e dublar (no PC)": a ligação da tela (painel_dublar_jogo.py) com o trabalho
(jellyfin_tools: iso_jogo, roteiro_jogo, dublar_jogo). A AppModerna herda esta parte, como a do patch.

O que fica guardado na pasta da entrega (".maestro"): as traduções (traducao.json: a mesma frase não é traduzida de
novo, e o que você corrigiu vale para sempre), as vozes escolhidas na tabela e as falas já dubladas (retomar).

Cada jogo tem as suas marcações 📝 Legendar e 🗣 Dublar (em jogos.json > "marcacoes", pelo caminho da ISO, da ROM ou
da pasta): só legendar traduz os textos e entrega o roteiro em português (as vozes ficam as originais); só dublar
traduz só as falas que têm voz, dubla e monta (os textos do jogo ficam como estão).

Cada console do submenu "Jogos →" tem o seu painel (o que você abriu no PS2 continua lá quando volta), e o fim muda:
o .xdelta nos discos, o .bps nas ROMs, o mod .zip no Switch e o pacote .zip no PC.
"""

from __future__ import annotations

import dataclasses
import json
import time
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from jellyfin_tools import consoles as cs
from jellyfin_tools import dublar_jogo as dj
from jellyfin_tools import iso_jogo as ij
from jellyfin_tools import patch_jogo as pj
from jellyfin_tools import personagens, voz_gemini, voz_local
from jellyfin_tools import roteiro_jogo as rj
from jellyfin_tools import tempo_jogo as tj
from jellyfin_tools.dublagem import localizar_ffmpeg

from . import automacao, config
from .painel_dublar_jogo import EMOCOES, MOTORES, QUEM_TRADUZ, PainelDublarJogo

TIPOS_ROTEIRO = [("Roteiro do jogo", "*.csv *.tsv *.txt *.json"), ("Todos os arquivos", "*.*")]
NOMES_DE_ROTEIRO = ("roteiro", "script", "texto", "textos", "strings", "dialog", "dialogo", "falas", "msg", "text")
ARQUIVO_MEMORIA = "traducao.json"
ARQUIVO_ELENCO = "elenco.json"
CRIAR_NOME = {"xdelta": "Criar o patch", "bps": "Criar o patch", "mod": "Criar o mod", "pacote": "Criar o pacote"}
MARCACOES = "marcacoes"                 # jogos.json > "marcacoes": {caminho do jogo: [legendar, dublar]}
MARQUE = "Marque 📝 Legendar e/ou 🗣 Dublar (em cima, no ⏱ Tempo deste jogo): o Maestro faz só o que está marcado."


class DublagemDeJogos:
    """Parte "Traduzir e dublar (no PC)" da aba 🎮 Jogos (usa self.fila, self._rodar... da janela)."""

    def _iniciar_dublar_jogo(self) -> None:
        self.painel_dublar_jogo = None
        self._paineis_dublar: dict[str, PainelDublarJogo] = {}      # um por console
        self._estado_dublar: dict[str, tuple] = {}                  # a memória e o elenco de cada console
        self._memoria_jogo: dict = {}
        self._fixas_jogo: dict = {}
        self._velocidades_jogo: tj.Velocidades | None = None
        self._placa_nvidia: bool | None = None
        self._auto_jogo: dict | None = None            # o 🤖 Automático em andamento (as etapas que faltam)

    def _console_do_jogo(self) -> cs.Console:
        return getattr(self, "console_jogos", None) or cs.console("PS2")

    def _trocar_console_dublar(self, antigo: cs.Console, novo: cs.Console) -> None:
        """A tradução guardada e o elenco ficam com o console de cada jogo (não passam para o outro)."""
        self._estado_dublar[antigo.chave] = (self._memoria_jogo, self._fixas_jogo)
        self._memoria_jogo, self._fixas_jogo = self._estado_dublar.get(novo.chave, ({}, {}))

    def painel_do_modo_dublar(self) -> PainelDublarJogo:
        console = self._console_do_jogo()
        self.painel_dublar_jogo = self._paineis_dublar.get(console.chave)
        if self.painel_dublar_jogo is None or not self.painel_dublar_jogo.winfo_exists():
            self.painel_dublar_jogo = PainelDublarJogo(self.aba_jogos, self, {
                "escolher_pasta": self.d_escolher_pasta, "ler": self.d_ler, "escolher_roteiro": self.d_escolher_roteiro,
                "escolher_iso": self.d_escolher_iso, "analisar": self.d_analisar, "relatorio": self.d_relatorio,
                "extrair": self.d_extrair, "traduzir": self.d_traduzir, "traduzir_teste": lambda: self.d_traduzir(20),
                "editar": self.d_editar, "custos": self.d_custos, "motor": self.d_motor,
                "trocar_voz": self.d_trocar_voz, "dublar": self.d_dublar, "dublar_teste": lambda: self.d_dublar(5),
                "ouvir": self.d_ouvir, "editar_fala": self.d_editar_fala, "escolher_saida": self.d_escolher_saida,
                "entregar": self.d_entregar, "abrir_saida": self.d_abrir_saida, "montar": self.d_montar,
                "criar_patch": self.d_criar_patch, "automatico": self.d_automatico,
                "marcacoes": self._ao_mudar_marcacoes}, console)
            self._paineis_dublar[console.chave] = self.painel_dublar_jogo
            p = self.painel_dublar_jogo
            p.var_iso.trace_add("write", lambda *_: p.atualizar())
            for var in (p.var_iso, p.var_pasta):        # outro jogo: as marcações dele
                var.trace_add("write", lambda *_, p=p: self._carregar_marcacoes(p))
            for var in (p.var_quem_traduz, p.var_motor, p.var_ouvir):
                var.trace_add("write", lambda *_: self._atualizar_tempo_jogo())
            p.mostrar_estimativas(motor=self._estado_do_motor())
        return self.painel_dublar_jogo

    # ------------------------------------------------------------------ 📝 Legendar / 🗣 Dublar: as de cada jogo
    def marcacoes_do_jogo(self, caminho: str | Path) -> tuple[bool, bool] | None:
        """(legendar, dublar) guardados para este jogo (a ISO, a ROM ou a pasta), ou None (nunca marcado)."""
        guardadas = self.preferencia_jogos(MARCACOES, {})
        if not str(caminho).strip() or not isinstance(guardadas, dict):
            return None
        valor = guardadas.get(str(Path(caminho)))
        return (bool(valor[0]), bool(valor[1])) if isinstance(valor, list) and len(valor) == 2 else None

    def guardar_marcacoes(self, caminhos, legendar: bool, dublar: bool) -> None:
        guardadas = self.preferencia_jogos(MARCACOES, {})
        guardadas = guardadas if isinstance(guardadas, dict) else {}
        for caminho in caminhos:
            if str(caminho).strip():
                guardadas[str(Path(caminho))] = [bool(legendar), bool(dublar)]
        self.guardar_preferencia_jogos(MARCACOES, guardadas)

    @staticmethod
    def _jogo_da_tela(p: PainelDublarJogo) -> str:
        """O jogo do painel nas marcações: a ISO (ou a ROM) e, sem ela (Switch, PC), a pasta."""
        return p.var_iso.get().strip() or p.var_pasta.get().strip()

    def _carregar_marcacoes(self, p: PainelDublarJogo) -> None:
        """Outro jogo no painel: as marcações guardadas dele (um jogo nunca marcado fica com as que estão na tela)."""
        guardadas = self.marcacoes_do_jogo(self._jogo_da_tela(p))
        if guardadas is not None:
            p.marcar(*guardadas)

    def _ao_mudar_marcacoes(self, guardar: bool = True) -> None:
        p = self.painel_dublar_jogo
        if p is None or not p.winfo_exists():
            return
        if guardar and self._jogo_da_tela(p):
            self.guardar_marcacoes([self._jogo_da_tela(p)], *p.marcacoes())
        self._atualizar_tempo_jogo()

    # ------------------------------------------------------------------ ajudantes
    def _pasta_jogo(self) -> Path | None:
        texto = self.painel_dublar_jogo.var_pasta.get().strip()
        return Path(texto) if texto else None

    def _saida_jogo(self) -> Path | None:
        p = self.painel_dublar_jogo
        if p.var_saida.get().strip():
            return Path(p.var_saida.get().strip())
        pasta = self._pasta_jogo()
        if pasta is None:
            return None
        nome = pasta.name
        for sufixo in (" - extraído", " - extraido", " extraído", "_extraido"):
            if nome.lower().endswith(sufixo):
                nome = nome[:-len(sufixo)]
        return pasta.parent / f"{nome} - PT-BR"

    def _glossario(self) -> tuple:
        texto = self.painel_dublar_jogo.var_glossario.get()
        texto = texto.split(":", 1)[1] if texto.lower().startswith("nomes que não se traduzem:") else texto
        return tuple(n.strip() for n in texto.replace(";", ",").split(",") if n.strip())

    def _guardar_memoria_jogo(self, saida: Path | None = None) -> None:
        """Nas tarefas (fora da tela), passe a saída: só a tela pode ler os campos."""
        saida = saida if saida is not None else self._saida_jogo()
        if saida is not None:
            rj.salvar_memoria(saida / dj.PASTA_TRABALHO / ARQUIVO_MEMORIA, self._memoria_jogo)
            (saida / dj.PASTA_TRABALHO).mkdir(parents=True, exist_ok=True)
            (saida / dj.PASTA_TRABALHO / ARQUIVO_ELENCO).write_text(
                json.dumps(self._fixas_jogo, ensure_ascii=False, indent=1), encoding="utf-8")

    def _motor_escolhido(self) -> str:
        return {MOTORES[0]: voz_local.NOME, MOTORES[1]: self.MOTORES_VOZ[1], MOTORES[2]: self.MOTORES_VOZ[2],
                MOTORES[3]: self.MOTORES_VOZ[0]}[self.painel_dublar_jogo.var_motor.get()]

    def _opcoes_do_jogo(self):
        o = self.obter_opcoes_jellyfin()
        return dataclasses.replace(o, motor_voz=self._motor_escolhido(), figurantes_piper=False,
                                   conferir_falas=self.painel_dublar_jogo.var_conferir.get())

    def _vozes_do_motor(self, o) -> tuple[str, dict, object]:
        """(voz principal, {"m": voz, "f": voz}, catálogo do elenco) do motor escolhido."""
        if automacao.usa_local(o):
            principal = o.voz_local or voz_local.VOZ_PADRAO
            if voz_local.perfil_da_voz(principal, automacao.vozes_importadas()).startswith("feminina"):
                return principal, {"f": principal, "m": voz_local.VOZ_PADRAO}, "xtts"
            return principal, {"m": principal, "f": voz_local.vozes_por_genero("feminina")[0]}, "xtts"
        if automacao.usa_gemini(o):
            voz = o.voz_gemini if o.voz_gemini in voz_gemini.VOZES else voz_gemini.VOZ_PADRAO
            masculina = voz_gemini.VOZES[voz].startswith("masculina")
            return voz, {"m": voz if masculina else voz_gemini.VOZES_MASCULINAS[0],
                         "f": voz_gemini.VOZES_FEMININAS[0] if masculina else voz}, personagens.CATALOGO_GEMINI
        principal = o.voz_cloud if automacao.usa_cloud(o) else o.voz_dublagem
        return principal, {"m": principal, "f": principal}, None

    def _estado_do_motor(self) -> str:
        if self.painel_dublar_jogo.var_motor.get() != MOTORES[0]:
            return ""
        pasta = automacao.pasta_motor_local()
        instalado = voz_local.instalado(pasta)
        if not instalado:
            return ("XTTS-v2 ainda não instalado: o Maestro instala sozinho ao dublar (~3 GB, uma vez)"
                    if automacao.licenca_xtts_aceita() else
                    "⚠ XTTS-v2 ainda não instalado: escolha o cartão XTTS-v2 em Configurações > Dublagem (instala "
                    "sozinho)")
        from jellyfin_tools import voz_emocao
        partes = ["✓ XTTS-v2" + (" e Chatterbox" if voz_emocao.instalado(pasta) else "") + " instalados"
                  if voz_emocao.instalado(pasta) else "✓ XTTS-v2 instalado",
                  "placa NVIDIA" if instalado.get("gpu") else "processador"]
        return " · ".join(partes)

    def _refazer_elenco(self) -> None:
        p = self.painel_dublar_jogo
        o = self._opcoes_do_jogo()
        principal, por_genero, catalogo = self._vozes_do_motor(o)
        dj.elenco(p.falas, principal, self._fixas_jogo, por_genero, catalogo)
        from jellyfin_tools import voz_emocao
        p.mostrar_elenco(automacao.vozes_importadas(), config.ARQUIVO.parent,
                         p.var_emocao.get() == EMOCOES[0] and voz_emocao.instalado(automacao.pasta_motor_local()))

    def _custo_da_traducao(self, letras: int, textos: int) -> str:
        from jellyfin_tools.traducao import estimar_custo
        escolha = self.painel_dublar_jogo.var_quem_traduz.get()
        if escolha == QUEM_TRADUZ[0]:
            o = self.obter_opcoes_jellyfin()
            custo = estimar_custo(max(1, letras), max(1, textos), o.modelo_traducao)[2]
            minutos = max(1, round(textos / 800 * 60 / 60))
            return (f"Claude ≈ US$ {custo:.2f}".replace(".", ",") if custo is not None else "Claude") + \
                f" · local: grátis (~{minutos} min no PC)"
        if escolha == QUEM_TRADUZ[1]:
            return f"Gemini Flash: grátis com a chave grátis (~{max(1, -(-textos // 100))} pedidos)"
        return "grátis, no PC (mais literal)"

    def _mensagem_dublar_jogo(self, tipo: str, *dados) -> None:
        p = self.painel_dublar_jogo
        if p is None or not p.winfo_exists():
            return
        if tipo == "d_analise":
            p.mostrar_analise(dados[0])
        elif tipo == "d_extraido":
            p.var_pasta.set(str(dados[0]))
            p.var_roteiro.set("")
            self._quando_livre(self.d_ler)
        elif tipo == "d_lido":
            roteiro, falas, contagem, tem_mapa, jogo, iso = dados
            if iso and not p.var_iso.get().strip():
                p.var_iso.set(str(iso))
            p.mostrar_lido(roteiro, falas, contagem, tem_mapa, jogo)
            self._refazer_elenco()
            letras = (roteiro.letras() if roteiro else 0) + sum(len(f.texto) for f in falas if f.ouvida)
            textos = (len(roteiro.com_texto) if roteiro else 0) + sum(1 for f in falas if f.ouvida)
            p.mostrar_estimativas(self._custo_da_traducao(letras, textos), self._estado_do_motor())
            self._atualizar_tempo_jogo()
        elif tipo == "d_traduzido":
            p.mostrar_traducao(dados[0])
            self._refazer_elenco()
            p.atualizar()
            self._atualizar_tempo_jogo()
        elif tipo == "d_andamento":
            p.mostrar_andamento(*dados)
        elif tipo == "d_eta":
            p.mostrar_tempo_jogo(dados[0])
        elif tipo == "d_dublado":
            r, = dados
            texto = f"{r.dubladas} falas dubladas" + (f" · {r.puladas} já estavam prontas" if r.puladas else "") + \
                (f" · {len(r.erros)} com erro (veja o log)" if r.erros else "")
            p.mostrar_andamento(1.0, "")
            p.mostrar_dublagem(texto, not r.erros)
            self._refazer_elenco()
            self._atualizar_tempo_jogo()
        elif tipo == "d_entregue":
            arquivos, saida, dublar = dados
            nomes = [a.name for a in arquivos] + ([f"{dj.PASTA_SAIDA_AUDIO}\\"] if dublar else [])
            p.mostrar_entrega("✓ Pronto em " + str(saida) + ": " + (", ".join(nomes[:-1]) + " e " + nomes[-1]
                                                                    if len(nomes) > 1 else nomes[0]))
        elif tipo == "d_montado":
            m, = dados
            p.iso_montada = m.destino
            p.mostrar_entrega(f"✓ ISO em português: {m.destino.name} ({m.trocadas} falas trocadas no mesmo lugar" +
                              (f"; {len(m.puladas)} puladas, veja o log" if m.puladas else "") + "). A original não "
                              "mudou.", not m.puladas)
            self._atualizar_tempo_jogo()

    # ------------------------------------------------------------------ ⏱ o tempo deste jogo
    def _velocidades(self) -> tj.Velocidades:
        if self._velocidades_jogo is None:
            self._velocidades_jogo = tj.Velocidades(config.ARQUIVO.parent / tj.ARQUIVO)
        return self._velocidades_jogo

    def _xtts_na_placa(self) -> bool:
        info = voz_local.instalado(automacao.pasta_motor_local())
        if info:
            return bool(info.get("gpu"))
        if self._placa_nvidia is None:                  # (ainda não instalado: o que vai ser instalado)
            self._placa_nvidia = voz_local.tem_placa_nvidia()
        return self._placa_nvidia

    def _ja_dubladas(self) -> set:
        saida = self._saida_jogo()
        if saida is None:
            return set()
        try:
            return set(json.loads((saida / dj.PASTA_TRABALHO / dj.ARQUIVO_FEITAS).read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            return set()

    def _entradas_a_traduzir(self) -> list:
        """Do roteiro, o que as marcações pedem: tudo (📝 Legendar) ou só as falas que têm voz (só 🗣 Dublar)."""
        p = self.painel_dublar_jogo
        legendar, dublar = p.marcacoes()
        if p.roteiro is None or not (legendar or dublar):
            return []
        return p.roteiro.com_texto if legendar else [e for e in dj.entradas_faladas(p.falas) if e.texto.strip()]

    def _etapas_do_jogo(self) -> list:
        """O que ainda falta neste jogo, com o tempo de cada etapa (lê a tela: só na tarefa principal)."""
        p = self.painel_dublar_jogo
        o = self.obter_opcoes_jellyfin()
        legendar, dublar = p.marcacoes()
        ouvir = p.var_ouvir.get() and dublar
        sem_texto = [f for f in p.falas if f.formato is not None and not f.texto.strip()] if ouvir else []
        pendentes = [e for e in self._entradas_a_traduzir() if not e.traducao]
        ouvidas = [f for f in p.falas if f.ouvida and not f.traducao] if dublar else []
        textos = len(pendentes) + len(ouvidas) + len(sem_texto)
        feitas = self._ja_dubladas()
        falas = sum(1 for f in p.falas if f.formato is not None and f.relativo not in feitas
                    and (f.traducao or f.texto.strip() or ouvir)) if dublar else 0
        iso = Path(p.var_iso.get().strip()) if p.var_iso.get().strip() else None
        montada = p.iso_montada is not None and Path(p.iso_montada).is_file() and not falas
        iso_mb = iso.stat().st_size / 1e6 if dublar and p.tem_mapa and iso is not None and iso.is_file() and \
            not montada else 0.0
        quem = ("Claude", "Gemini", "Argos")[QUEM_TRADUZ.index(p.var_quem_traduz.get())]
        motor = ("XTTS-v2", "Gemini", "Google Cloud", "Piper")[MOTORES.index(p.var_motor.get())]
        custos = {"traduzir": "grátis" if quem == "Argos" else "grátis (chave grátis)" if quem == "Gemini" else "pago",
                  "dublar": {"Gemini": "pago", "Google Cloud": "cota grátis"}.get(motor, "grátis")}
        if quem == "Claude" and textos:
            from jellyfin_tools.traducao import estimar_custo
            letras = sum(len(e.texto) for e in pendentes) + sum(len(f.texto) for f in ouvidas) + 60 * len(sem_texto)
            custo = estimar_custo(max(1, letras), textos, o.modelo_traducao)[2]
            if custo is not None:
                custos["traduzir"] = f"≈ US$ {custo:.2f}".replace(".", ",")
        return tj.estimar(self._velocidades(), segundos_sem_texto=sum(f.formato.segundos for f in sem_texto),
                          textos=textos, falas=falas, iso_mb=iso_mb, quem_traduz=quem, motor=motor,
                          placa=self._xtts_na_placa() if motor == "XTTS-v2" else False,
                          whisper_placa=bool(getattr(o, "whisper_gpu", False)), custos=custos)

    def _atualizar_tempo_jogo(self) -> None:
        p = self.painel_dublar_jogo
        if p is None or not p.winfo_exists() or self._auto_jogo is not None:
            return
        if p.roteiro is None and not p.falas:
            p.mostrar_tempo_jogo(p.sem_nada())
            return
        try:
            etapas = self._etapas_do_jogo()
        except (OSError, ValueError) as erro:
            self._log.info("Tempo do jogo: %s", erro)
            return
        legendar, dublar = p.marcacoes()
        p.mostrar_tempo_jogo(tj.resumo(etapas) if etapas else
                             "nada marcado: marque 📝 Legendar e/ou 🗣 Dublar" if not (legendar or dublar) else
                             "✓ nada falta: " + ("tudo traduzido e dublado" if legendar and dublar else
                                                 "tudo traduzido" if legendar else "tudo dublado"))

    def _cronometro_jogo(self, *chaves: str) -> tuple:
        """(Cronometro destas etapas, o começo do texto, {etapa: chave da velocidade}). No 🤖 Automático, o tempo
        das etapas que ainda vêm depois entra no "faltam". Só na tarefa principal (lê a tela)."""
        etapas = {e.chave: e for e in self._etapas_do_jogo()}
        estimado = sum(etapas[c].segundos for c in chaves if c in etapas)
        depois, prefixo = 0.0, ""
        auto = self._auto_jogo
        if auto is not None:
            restantes = [c for passo in auto["passos"] for c in (("ouvir", "traduzir") if passo == "traduzir"
                                                                    else (passo,))]
            depois = sum(auto["etapas"][c].segundos for c in restantes if c in auto["etapas"])
            prefixo = f"🤖 Automático {auto['feito']} de {auto['total']} · {tj.NOMES[auto['atual']]} · "
        return tj.Cronometro(estimado, depois), prefixo, {c: e.velocidade for c, e in etapas.items()}

    def _eta(self, crono, prefixo: str, fracao: float) -> None:
        """Na tarefa: o "faltam ≈ ... · termina por volta das ..." na faixa do tempo."""
        self.fila.put(("jogos", ("d_eta", prefixo + crono.texto(fracao))))

    # ------------------------------------------------------------------ 🤖 Automático: as etapas em sequência
    def d_automatico(self) -> None:
        from .janela_automatico_jogo import JanelaAutomaticoJogo
        p = self.painel_dublar_jogo
        if p.roteiro is None and not p.falas:
            self.mostrar_mensagem("🤖 Automático", "Abra primeiro o roteiro do jogo ou tire as falas da ISO (1. Roteiro "
                                  "do jogo): o Automático faz o resto.", "aviso")
            return
        if self.trabalhando or self._auto_jogo is not None:
            self.mostrar_mensagem("🤖 Automático", "Espere a tarefa de agora terminar.", "aviso")
            return
        if not any(p.marcacoes()):
            self.mostrar_mensagem("🤖 Automático", MARQUE, "aviso")
            return
        etapas = self._etapas_do_jogo()
        if not etapas:
            self.mostrar_mensagem("🤖 Automático", "Nada falta neste jogo: o que está marcado já foi feito.", "info")
            return
        jogo = p.info["jogo"].cget("text") if "jogo" in p.info else ""
        self.janela_automatico_jogo = JanelaAutomaticoJogo(
            self, jogo if jogo and jogo != "—" else (self._pasta_jogo().name if self._pasta_jogo() else "jogo"),
            etapas, lambda marcadas: self._comecar_automatico_jogo(marcadas, etapas))

    def _comecar_automatico_jogo(self, marcadas: list, etapas: list) -> None:
        p = self.painel_dublar_jogo
        if self.trabalhando:
            self.mostrar_mensagem("🤖 Automático", "Espere a tarefa de agora terminar.", "aviso")
            return
        p.var_ouvir.set("ouvir" in marcadas)
        dublar = p.marcacoes()[1]
        passos = [e for e in ("traduzir", "dublar", "entregar", "montar")
                  if (e in marcadas or (e == "traduzir" and "ouvir" in marcadas))
                  and (dublar or e not in ("dublar", "montar"))]
        if not passos:
            return
        self._auto_jogo = {"passos": passos, "total": len(passos), "feito": 0, "atual": passos[0],
                           "inicio": time.monotonic(), "estimado": tj.total(etapas, marcadas),
                           "etapas": {e.chave: e for e in etapas}, "parou": False}
        self._log.info("🤖 Automático do jogo: %s (≈ %s)", ", ".join(tj.NOMES[e] for e in passos),
                       tj.legivel(self._auto_jogo["estimado"]))
        self._proximo_passo_automatico()

    def _proximo_passo_automatico(self) -> None:
        auto = self._auto_jogo
        if auto is None:
            return
        if auto["feito"] and self.evento_parar.is_set():           # o "Parar" da janela
            self._fim_do_automatico(parou=True)
            return
        if not auto["passos"]:
            self._fim_do_automatico(parou=False)
            return
        passo = auto["passos"].pop(0)
        auto["atual"], auto["feito"] = passo, auto["feito"] + 1
        {"traduzir": self.d_traduzir, "dublar": self.d_dublar, "entregar": self.d_entregar,
         "montar": self.d_montar}[passo]()
        if not self.trabalhando:                    # não começou (faltava algo: a mensagem já apareceu)
            self._fim_do_automatico(parou=True)
            return
        self._quando_livre(self._proximo_passo_automatico)

    def _fim_do_automatico(self, parou: bool) -> None:
        auto, self._auto_jogo = self._auto_jogo, None
        if auto is None:
            return
        gasto = time.monotonic() - auto["inicio"]
        if parou:
            texto = (f"O Automático parou na etapa {auto['feito']} de {auto['total']} ({tj.NOMES[auto['atual']]}). O "
                     "que ficou pronto está guardado: o próximo Automático continua de onde parou.")
            self._log.warning("🤖 Automático do jogo: parou em %s", tj.NOMES[auto["atual"]])
        else:
            texto = (f"Pronto em {tj.legivel(gasto)} (o previsto era ≈ {tj.legivel(auto['estimado'])}): "
                     f"{auto['total']} etapa(s) feitas uma depois da outra.")
            self._log.info("🤖 Automático do jogo: pronto em %s", tj.legivel(gasto))
        self._atualizar_tempo_jogo()
        self.mostrar_mensagem("🤖 Automático", texto, "aviso" if parou else "sucesso")

    def _quando_livre(self, fazer) -> None:
        """Faz assim que a tarefa em andamento terminar (a mensagem chega antes do "fim" dela)."""
        if self.trabalhando:
            self.after(200, lambda: self._quando_livre(fazer))
        else:
            fazer()

    # ------------------------------------------------------------------ 1. o roteiro
    def d_escolher_pasta(self) -> None:
        pasta = filedialog.askdirectory(parent=self, title="A pasta com o roteiro e as falas do jogo (extraídos)")
        if pasta:
            self.painel_dublar_jogo.var_pasta.set(pasta)
            self.painel_dublar_jogo.var_roteiro.set("")
            self.d_ler()

    def d_escolher_roteiro(self) -> None:
        arquivo = filedialog.askopenfilename(parent=self, title="O roteiro do jogo (textos)", filetypes=TIPOS_ROTEIRO,
                                             initialdir=str(self._pasta_jogo() or ""))
        if arquivo:
            self.painel_dublar_jogo.var_roteiro.set(arquivo)
            if not self.painel_dublar_jogo.var_pasta.get().strip():
                self.painel_dublar_jogo.var_pasta.set(str(Path(arquivo).parent))
            self.d_ler()

    def d_escolher_iso(self) -> None:
        from .jogos_moderna import TIPOS_ISO
        c = self.painel_dublar_jogo.console
        arquivo = filedialog.askopenfilename(parent=self, title="A ISO tirada do SEU disco" if c.padrao else
                                             c.jogo[0].upper() + c.jogo[1:],
                                             filetypes=TIPOS_ISO if c.padrao else list(c.tipos))
        if arquivo:
            self.painel_dublar_jogo.var_iso.set(arquivo)

    @staticmethod
    def achar_roteiro(pasta: Path) -> Path | None:
        """O roteiro dentro da pasta (o nome diz: roteiro, script, strings...), fora os que o Maestro gera."""
        candidatos = [a for a in sorted(pasta.iterdir()) if a.is_file() and a.suffix.lower() in rj.EXTENSOES_ROTEIRO
                      and not a.stem.lower().endswith("_ptbr") and a.name not in (ij.ARQUIVO_MAPA,
                                                                                 "falas_ouvidas.csv",
                                                                                 "relatorio_traducao.txt")]
        return next((a for a in candidatos if any(n in a.stem.lower() for n in NOMES_DE_ROTEIRO)),
                    next((a for a in candidatos if a.suffix.lower() in (".csv", ".tsv")), None))

    def d_ler(self) -> None:
        p = self.painel_dublar_jogo
        pasta = self._pasta_jogo()
        if pasta is None or not pasta.is_dir():
            self.mostrar_mensagem("Ler a pasta", "Escolha a pasta com o roteiro e as falas do jogo (a que a ferramenta "
                                  "da comunidade extraiu), ou tire as falas da ISO pelo Maestro.", "aviso")
            return
        escolhido = p.var_roteiro.get().strip()
        iso_tela = p.var_iso.get().strip()
        saida = self._saida_jogo()
        console = p.console

        def tarefa():
            arquivo = Path(escolhido) if escolhido else self.achar_roteiro(pasta)
            roteiro = None
            if arquivo is not None:
                try:
                    roteiro = rj.ler_roteiro(arquivo)
                except rj.ErroRoteiro as erro:
                    self.fila.put(("msg", ("Roteiro do jogo", f"Não deu para ler o roteiro: {erro}", "aviso")))
            falas = dj.achar_falas(pasta, roteiro)
            contagem = dj.medir(falas, self.evento_parar.is_set,
                                lambda f: self.fila.put(("jf_analise", (f, f"Medindo as vozes: {f:.0%}"))))
            ao_lado = next(iter(sorted(pasta.parent.glob("*.iso"))), None) if console.iso9660 else None
            iso = Path(iso_tela) if iso_tela else ao_lado
            jogo = ""
            if iso is not None and iso.is_file():
                try:
                    jogo = (pj.ler_info(iso).descrever() if console.padrao else
                            cs.descrever(cs.identificar(iso, console.chave))) + \
                        ("  (lido da ISO ao lado)" if not iso_tela else "")
                except pj.ErroPatch:
                    jogo = ""
            # o que já foi traduzido antes (a memória da pasta da entrega) volta sem gastar
            self._memoria_jogo = rj.carregar_memoria(saida / dj.PASTA_TRABALHO / ARQUIVO_MEMORIA) if saida else {}
            try:
                self._fixas_jogo = json.loads((saida / dj.PASTA_TRABALHO / ARQUIVO_ELENCO).read_text(
                    encoding="utf-8")) if saida else {}
            except (OSError, ValueError):
                self._fixas_jogo = {}
            if saida is not None:
                dj.ouvidas_guardadas(falas, saida / dj.PASTA_TRABALHO)
            if roteiro is not None:
                for e, (traducao, avisos, longa) in zip(roteiro.com_texto, rj.da_memoria(
                        [e.texto for e in roteiro.com_texto], self._memoria_jogo,
                        [e.limite for e in roteiro.com_texto])):
                    e.traducao, e.avisos, e.longa = traducao, avisos, longa
            dj.ligar_traducoes(falas)
            ouvidas = [f for f in falas if f.ouvida and f.texto]
            for f, (traducao, avisos, _) in zip(ouvidas, rj.da_memoria([f.texto for f in ouvidas],
                                                                        self._memoria_jogo)):
                f.traducao, f.avisos = traducao, avisos
            self._log.info("Jogo: %s · roteiro %s · %d falas gravadas", pasta, arquivo.name if arquivo else "nenhum",
                           len(falas))
            self.fila.put(("jogos", ("d_lido", roteiro, falas, contagem, ij.ler_mapa(pasta) is not None, jogo, iso)))

        self._rodar(f"Lendo o jogo em {pasta.name}...", tarefa)

    def d_analisar(self) -> None:
        iso = Path(self.painel_dublar_jogo.var_iso.get().strip())

        def tarefa():
            try:
                analise = ij.analisar(iso, self.evento_parar.is_set, lambda f: self.fila.put(
                    ("jf_analise", (f, f"Analisando a ISO: {f:.0%}"))))
            except (pj.ErroPatch, OSError) as erro:
                self.fila.put(("msg", ("Analisar a ISO", f"Não deu para analisar: {erro}", "aviso")))
                return
            self._log.info("Análise de %s: %s", iso.name, analise.resumo())
            self.fila.put(("jogos", ("d_analise", analise)))

        self._rodar(f"Analisando {iso.name}...", tarefa)

    def d_relatorio(self) -> None:
        analise = self.painel_dublar_jogo.analise
        if analise is None:
            return
        destino = filedialog.asksaveasfilename(parent=self, title="Salvar o relatório da ISO", defaultextension=".txt",
                                               initialfile=f"análise - {analise.iso.stem}.txt",
                                               initialdir=str(analise.iso.parent), filetypes=[("Texto", "*.txt")])
        if destino:
            Path(destino).write_text(ij.relatorio(analise), encoding="utf-8")
            self.mostrar_mensagem("Relatório da ISO", f"Salvo em {destino}.\n\nMande para quem for ajudar com este "
                                  "jogo: ele diz o que tem dentro do disco e o que o Maestro já troca.", "sucesso")

    def d_extrair(self) -> None:
        p = self.painel_dublar_jogo
        analise = p.analise
        if analise is None or not analise.falas:
            return
        pasta = analise.iso.parent / f"{analise.iso.stem} - extraído"
        if pasta.exists() and any(pasta.iterdir()) and not self.perguntar(
                "Tirar as falas da ISO", f"A pasta {pasta.name} já existe. Tirar as falas de novo (por cima)?"):
            return

        def tarefa():
            try:
                n = ij.extrair(analise, pasta, self.evento_parar.is_set, lambda f: self.fila.put(
                    ("jf_analise", (f, f"Tirando as falas: {f:.0%}"))))
            except (pj.ErroPatch, OSError) as erro:
                self.fila.put(("msg", ("Tirar as falas", f"Não deu: {erro}", "aviso")))
                return
            self._log.info("%d falas tiradas de %s para %s", n, analise.iso.name, pasta)
            self.fila.put(("jogos", ("d_extraido", pasta)))

        self._rodar(f"Tirando as falas de {analise.iso.name}...", tarefa)

    # ------------------------------------------------------------------ 2. a tradução
    def _tradutor_do_jogo(self, o):
        escolha = self.painel_dublar_jogo.var_quem_traduz.get()
        if escolha == QUEM_TRADUZ[2]:
            from jellyfin_tools.traducao_local import TradutorLocal
            return TradutorLocal(automacao.pasta_traducao_local(), "pt-BR", ao_baixar=lambda f, texto="": self.fila.put(
                ("jf_analise", (f, f"Baixando o tradutor do PC: {f:.0%}"))))
        if escolha == QUEM_TRADUZ[1]:
            if not automacao.chave_gemini(o):
                raise automacao.FaltaConfiguracao("Para traduzir com o Gemini Flash, cole a chave do Google AI Studio "
                                                  "(a grátis serve) em Configurações > Chaves de API.")
            from jellyfin_tools.traducao_gemini import TradutorGemini
            return TradutorGemini(automacao.chave_gemini(o), avisar=lambda t: self._log.info("Gemini: %s", t))
        import os
        if not (o.chave_claude or os.environ.get("ANTHROPIC_API_KEY")):
            raise automacao.FaltaConfiguracao("Para traduzir com o Claude, cole a chave da Anthropic em Configurações > "
                                              "Chaves de API (ou escolha \"Grátis no PC\").")
        return rj.TradutorJogo(chave=o.chave_claude, modelo=o.modelo_traducao)

    def d_traduzir(self, so: int | None = None) -> None:
        p = self.painel_dublar_jogo
        o = self.obter_opcoes_jellyfin()
        try:
            tradutor = self._tradutor_do_jogo(o)
        except automacao.FaltaConfiguracao as erro:
            self.mostrar_mensagem("Traduzir", str(erro), "aviso")
            return
        legendar, dublar = p.marcacoes()
        if not (legendar or dublar):
            self.mostrar_mensagem("Traduzir", MARQUE, "aviso")
            return
        roteiro, falas = p.roteiro, p.falas
        glossario, sem_acentos, ouvir = self._glossario(), p.var_sem_acentos.get(), p.var_ouvir.get() and dublar
        entradas = None if legendar else self._entradas_a_traduzir()   # só dublar: só as falas que têm voz
        saida = self._saida_jogo()
        crono, prefixo, chaves = self._cronometro_jogo(*(("ouvir", "traduzir") if ouvir else ("traduzir",)))
        velocidades = self._velocidades()

        def andamento(f, texto):
            self.fila.put(("jf_analise", (f, texto)))
            if not so:                                  # (o teste das 20 primeiras não vale para o jogo todo)
                self._eta(crono, prefixo, f)

        def tarefa():
            try:
                sem_texto = [f for f in falas if f.formato is not None and not f.texto.strip()]
                if ouvir and sem_texto and saida is not None:
                    from jellyfin_tools.transcricao import Transcritor
                    inicio = time.monotonic()
                    transcritor = Transcritor(modelo=o.modelo_whisper, usar_gpu=o.whisper_gpu,
                                              pasta_modelos=str(config.ARQUIVO.parent / "modelos_whisper"))
                    alvo = sem_texto[:so] if so else sem_texto
                    dj.ouvir(alvo, transcritor, saida / dj.PASTA_TRABALHO, None, self.evento_parar.is_set,
                             lambda f: andamento(0.3 * f, f"O Whisper ouvindo as falas sem texto: {f:.0%}"))
                    if "ouvir" in chaves and not self.evento_parar.is_set():
                        velocidades.medir(chaves["ouvir"], sum(f.formato.segundos for f in alvo),
                                          time.monotonic() - inicio)
                inicio_traducao = time.monotonic()
                resumo = rj.ResumoTraducao()
                if roteiro is not None and (entradas is None or entradas):
                    resumo = rj.traduzir_roteiro(roteiro, tradutor, glossario, sem_acentos, self._memoria_jogo, so,
                                                 self.evento_parar.is_set,
                                                 lambda f: andamento(0.3 + 0.6 * f, f"Traduzindo: {f:.0%}"),
                                                 entradas=entradas)
                dj.ligar_traducoes(falas)
                ouvidas = [f for f in falas if f.ouvida] if dublar else []
                if ouvidas:
                    r2 = dj.traduzir_ouvidas(ouvidas[:so] if so else ouvidas, tradutor, glossario, sem_acentos,
                                             self._memoria_jogo, self.evento_parar.is_set,
                                             lambda f: andamento(0.9 + 0.1 * f, f"Traduzindo as falas ouvidas: {f:.0%}"))
                    resumo.traduzidas += r2.traduzidas
                    resumo.encurtadas += r2.encurtadas
                resumo.custo = getattr(tradutor, "custo", None)
                if "traduzir" in chaves and not self.evento_parar.is_set():
                    velocidades.medir(chaves["traduzir"], resumo.unicas, time.monotonic() - inicio_traducao)
            except Exception as erro:                    # (ErroTraducao, sem internet...): o que já foi fica guardado
                self._guardar_memoria_jogo(saida)
                self._log.warning("Traduzir o jogo: %s", erro)
                self.fila.put(("msg", ("Traduzir", f"A tradução parou: {erro}. O que já foi traduzido ficou guardado.",
                                       "aviso")))
                self.fila.put(("jogos", ("d_traduzido", None)))
                return
            self._guardar_memoria_jogo(saida)
            self._log.info("Jogo traduzido: %d textos (%d diferentes, %d da memória), %d encurtados pelo Claude, %d "
                           "ainda passam do espaço, %d com código perdido", resumo.traduzidas, resumo.unicas,
                           resumo.reaproveitadas, resumo.encurtadas, resumo.passaram, resumo.sem_codigo)
            self.fila.put(("jogos", ("d_traduzido", resumo)))

        self._rodar(("Traduzindo o jogo" if legendar else "Traduzindo as falas do jogo") +
                    (f" (as {so} primeiras)" if so else "") + "...", tarefa)

    def d_editar(self) -> None:
        """Dois cliques numa linha: corrigir a tradução (vale para todas as vezes que o texto aparece)."""
        p = self.painel_dublar_jogo
        k = p.selecionado_da_traducao()
        linhas = p.linhas_da_traducao()
        if k is None or k >= len(linhas):
            return
        chave, original, atual = linhas[k][:3]
        novo = self.pedir_texto_do_jogo("Corrigir a tradução", f"{chave}: {original}", atual)
        if novo is None or not novo.strip():
            return
        rj.corrigir(self._memoria_jogo, original, novo.strip())
        if p.roteiro is not None:
            for e in p.roteiro.com_texto:
                if e.texto == original:
                    e.traducao, e.longa = novo.strip(), ""
                    e.avisos = [f"passou do espaço: {len(e.traducao)} de {e.limite} letras"] \
                        if e.limite and len(e.traducao) > e.limite else []
        for f in p.falas:
            if f.texto == original:
                f.traducao, f.avisos = novo.strip(), []
        dj.ligar_traducoes(p.falas)
        self._guardar_memoria_jogo()
        p.mostrar_traducao()

    def pedir_texto_do_jogo(self, titulo: str, mensagem: str, atual: str) -> str | None:
        dialogo = ctk.CTkInputDialog(text=f"{mensagem}\n\nAgora: {atual}", title=titulo)
        return dialogo.get_input()

    def d_custos(self) -> None:
        from .janela_custos_jogo import JanelaCustos
        p = self.painel_dublar_jogo
        letras = (p.roteiro.letras() if p.roteiro else 0) + sum(len(f.texto) for f in p.falas if f.ouvida)
        textos = (len(p.roteiro.com_texto) if p.roteiro else 0) + sum(1 for f in p.falas if f.ouvida)
        lidas = [f for f in p.falas if f.formato is not None]
        segundos = sum(f.formato.segundos for f in lidas)
        jogo = (self._pasta_jogo().name if self._pasta_jogo() else "o jogo")

        def aplicar(perfil: str) -> None:
            traducao, dublagem = {"Tudo grátis": (QUEM_TRADUZ[2], MOTORES[0]),
                                  "Equilibrado": (QUEM_TRADUZ[0], MOTORES[0]),
                                  "Melhor qualidade": (QUEM_TRADUZ[0], MOTORES[1])}[perfil]
            p.var_quem_traduz.set(traducao)
            p.var_motor.set(dublagem)
        self.janela_custos_jogo = JanelaCustos(self, jogo, letras, textos, len(lidas), segundos, aplicar)

    # ------------------------------------------------------------------ 3. as vozes
    def d_motor(self) -> None:
        p = self.painel_dublar_jogo
        self._fixas_jogo = {}                        # outro motor: outras vozes
        self._refazer_elenco()
        p.mostrar_estimativas(motor=self._estado_do_motor())

    def _vozes_para_escolher(self, o) -> list[str]:
        if automacao.usa_local(o):
            importadas = [voz_local.PREFIXO_IMPORTADA + v.id for v in automacao.vozes_importadas()
                          if v.tipo == "gravacao"]
            return importadas + voz_local.vozes_por_genero("masculina", True) + \
                voz_local.vozes_por_genero("feminina", True)
        if automacao.usa_gemini(o):
            return list(voz_gemini.VOZES)
        return [self._vozes_do_motor(o)[0]]

    def d_trocar_voz(self) -> None:
        p = self.painel_dublar_jogo
        nome = p.selecionado_do_elenco()
        if not nome:
            return
        o = self._opcoes_do_jogo()
        vozes = self._vozes_para_escolher(o)
        textos = [voz_local.texto_do_menu(v) if automacao.usa_local(o) else
                  f"{v} ({voz_gemini.VOZES.get(v, '')})" if automacao.usa_gemini(o) else v for v in vozes]
        k = self.escolher_da_lista(f"A voz de {nome}", "Uma voz GENÉRICA (ou a sua, importada): nunca a do ator do "
                                   "jogo.", textos, botao="Usar esta")
        if k is None:
            return
        self._fixas_jogo[nome] = vozes[k]
        self._refazer_elenco()
        self._guardar_memoria_jogo()

    def _motor_do_jogo(self, o):
        motor = automacao.preparar_motor(o)
        return motor

    def d_dublar(self, so: int | None = None, falas_so: list | None = None, refazer: bool = False) -> None:
        p = self.painel_dublar_jogo
        saida = self._saida_jogo()
        if saida is None:
            return
        if not p.marcacoes()[1]:
            self.mostrar_mensagem("Dublar no PC", "Este jogo está só com 📝 Legendar: marque 🗣 Dublar (em cima, no "
                                  "⏱ Tempo deste jogo) para dublar as falas.", "aviso")
            return
        o = self._opcoes_do_jogo()
        falas = p.falas
        alvo = falas_so if falas_so is not None else ([f for f in falas if f.formato is not None and f.traducao][:so]
                                                      if so else None)
        if not any(f.traducao for f in (alvo if alvo is not None else falas)):
            self.mostrar_mensagem("Dublar no PC", "Traduza antes (2. Tradução): a voz fala a tradução.", "aviso")
            return
        formato, duracao = p.var_formato.get(), p.var_duracao.get()
        com_emocao = p.var_emocao.get() == EMOCOES[0]
        crono, prefixo, chaves = self._cronometro_jogo("dublar")
        velocidades, uma_parte = self._velocidades(), so is not None or falas_so is not None

        def andamento(f, total):
            self.fila.put(("jf_analise", (f, f"Dublando: {f:.0%}")))
            self.fila.put(("jogos", ("d_andamento", f, f"{round(f * total)} de {total} falas · {f:.0%}")))
            if not uma_parte:
                self._eta(crono, prefixo, f)

        def tarefa():
            ffmpeg = localizar_ffmpeg()
            if not ffmpeg:
                self.fila.put(("msg", ("Dublar no PC", "Falta o ffmpeg (pip install imageio-ffmpeg).", "aviso")))
                return
            try:
                motor = self._motor_do_jogo(o)
            except automacao.FaltaConfiguracao as erro:
                self.fila.put(("msg", ("Dublar no PC", str(erro), "aviso")))
                return
            total = len(alvo if alvo is not None else [f for f in falas if f.formato is not None and f.traducao])
            try:
                r = dj.dublar(falas, motor, saida, ffmpeg, formato, duracao, com_emocao, refazer, alvo,
                              self.evento_parar.is_set, lambda f: andamento(f, total))
            finally:
                if hasattr(motor, "fechar"):
                    motor.fechar()
            if "dublar" in chaves and not uma_parte and not self.evento_parar.is_set():
                velocidades.medir(chaves["dublar"], r.dubladas, crono.passou)   # a velocidade deste PC
            for relativo, erro in r.erros[:20]:
                self._log.warning("Dublar %s: %s", relativo, erro)
            self._log.info("Jogo dublado: %d falas (%d já prontas, %d aceleradas, %d cortadas no fim)", r.dubladas,
                           r.puladas, r.aceleradas, r.cortadas)
            self.fila.put(("jogos", ("d_dublado", r)))

        self._rodar("Dublando o jogo" + (f" (as {so} primeiras falas)" if so else "") + "...", tarefa)

    def d_ouvir(self) -> None:
        p = self.painel_dublar_jogo
        saida = self._saida_jogo()
        wav = dj.amostra(p.falas, saida, saida / dj.PASTA_TRABALHO / "ouvir 5 falas.wav", 5, p.var_formato.get()) \
            if saida else None
        if wav is None:
            self.mostrar_mensagem("Ouvir 5 falas", "Ainda não há falas dubladas: clique em \"Dublar no PC\" (ou "
                                  "\"Só 5 falas\").", "aviso")
            return
        self.fila.put(("tocar", wav))

    def d_editar_fala(self) -> None:
        """Escolher uma fala, mudar o texto (e a voz da tabela vale) e dublar SÓ ela de novo."""
        p = self.painel_dublar_jogo
        dublaveis = [f for f in p.falas if f.formato is not None and f.traducao]
        if not dublaveis:
            return
        k = self.escolher_da_lista("Editar uma fala", "Qual fala dublar de novo?",
                                   [f"{f.relativo} · {f.traducao}" for f in dublaveis], botao="Editar")
        if k is None:
            return
        fala = dublaveis[k]
        novo = self.pedir_texto_do_jogo("Editar uma fala", f"{fala.relativo}\nOriginal: {fala.texto}", fala.traducao)
        if novo is None:
            return
        if novo.strip() and novo.strip() != fala.traducao:
            fala.traducao = novo.strip()
            rj.corrigir(self._memoria_jogo, fala.texto, fala.traducao)
            self._guardar_memoria_jogo()
            p.mostrar_traducao()
        self.d_dublar(falas_so=[fala], refazer=True)

    # ------------------------------------------------------------------ 4. entregar
    def d_escolher_saida(self) -> None:
        pasta = filedialog.askdirectory(parent=self, title="Onde salvar a tradução do jogo")
        if pasta:
            self.painel_dublar_jogo.var_saida.set(pasta)

    def d_entregar(self) -> None:
        p = self.painel_dublar_jogo
        saida = self._saida_jogo()
        if saida is None:
            return
        legendar, dublar = p.marcacoes()
        if not (legendar or dublar):
            self.mostrar_mensagem("Entregar", MARQUE, "aviso")
            return
        roteiro, falas = p.roteiro, p.falas

        def tarefa():
            arquivos = dj.entregar(roteiro, falas, saida, legendar, dublar)
            self._guardar_memoria_jogo(saida)
            self._log.info("Tradução do jogo entregue em %s: %s", saida, ", ".join(a.name for a in arquivos))
            self.fila.put(("jogos", ("d_entregue", arquivos, saida, dublar)))

        self._rodar("Gerando " + ("o roteiro e as vozes" if legendar and dublar else "o roteiro" if legendar else
                                  "as vozes") + " em português...", tarefa)

    def d_abrir_saida(self) -> None:
        saida = self._saida_jogo()
        if saida is not None:
            saida.mkdir(parents=True, exist_ok=True)
            self._abrir_pasta_do_sistema(str(saida))

    def d_montar(self) -> None:
        p = self.painel_dublar_jogo
        iso, pasta, saida = Path(p.var_iso.get().strip()), self._pasta_jogo(), self._saida_jogo()
        if not (iso.is_file() and pasta and saida):
            return
        if not p.marcacoes()[1]:
            self.mostrar_mensagem("Montar a ISO", "Montar troca as vozes da ISO: marque 🗣 Dublar (em cima) para "
                                  "dublar este jogo. Só legendar: o roteiro em português volta ao jogo pela ferramenta "
                                  "da comunidade (a mesma que tirou os textos).", "aviso")
            return
        console = p.console
        try:
            info = pj.ler_info(iso) if console.padrao else cs.identificar(iso, console.chave)
        except pj.ErroPatch as erro:
            self.mostrar_mensagem("Montar a ISO", str(erro), "aviso")
            return
        destino = saida / (pj.nome_para_o_opl(info, f"{iso.stem} PT-BR") if console.padrao else
                           cs.nome_final(console.chave, info, f"{iso.stem} PT-BR"))
        crono, prefixo, chaves = self._cronometro_jogo("montar")
        velocidades = self._velocidades()

        def andamento(f):
            self.fila.put(("jf_analise", (f, f"Montando a ISO em português: {f:.0%}")))
            self._eta(crono, prefixo, f)

        def tarefa():
            try:
                m = ij.montar(iso, pasta, saida / dj.PASTA_SAIDA_AUDIO, destino, self.evento_parar.is_set, andamento)
            except (pj.ErroPatch, OSError) as erro:
                self.fila.put(("msg", ("Montar a ISO", f"Não montei: {erro}", "aviso")))
                return
            for relativo, motivo in m.puladas:
                self._log.warning("Montar a ISO: %s pulada (%s)", relativo, motivo)
            self._log.info("ISO em português: %s (%d falas trocadas)", m.destino, m.trocadas)
            if "montar" in chaves:
                velocidades.medir(chaves["montar"], iso.stat().st_size / 1e6, crono.passou)
            pj.registrar_aplicado(self.arquivo_aplicados, iso, saida, m.destino, "montada pelo Maestro",
                                  console=console.chave)
            self.fila.put(("jogos", ("d_montado", m)))

        self._rodar(f"Montando {destino.name}...", tarefa)

    def d_criar_patch(self) -> None:
        """O .xdelta da tradução: a ISO original + a montada (pelo Maestro ou pela ferramenta do jogo). Nas ROMs, o
        .bps; no Switch, o mod (.zip com o TitleID); no PC, o pacote (.zip), os dois com a pasta das vozes."""
        from .jogos_moderna import TIPOS_ISO
        p = self.painel_dublar_jogo
        c = p.console
        if not p.com_original:
            saida = self._saida_jogo()
            if not p.marcacoes()[1]:                    # só legendar: os arquivos do jogo com o texto devolvido
                pasta = filedialog.askdirectory(parent=self, title="A pasta com os arquivos do jogo já com o texto em "
                                                "português (da ferramenta da comunidade)")
                if pasta:
                    self.i_criar(Path(pasta), f"{Path(pasta).name} PT-BR (Maestro)")
                return
            audio = saida / dj.PASTA_SAIDA_AUDIO if saida is not None else None
            if audio is None or not audio.is_dir() or not any(audio.iterdir()):
                self.mostrar_mensagem(CRIAR_NOME[c.criar], "Gere primeiro o roteiro e as vozes em português (📝 no "
                                      "4. Entregar): o " + ("mod" if c.criar == "mod" else "pacote") + " junta o que "
                                      f"ficou em {dj.PASTA_SAIDA_AUDIO}.", "aviso")
                return
            nome = self._pasta_jogo().name if self._pasta_jogo() else saida.name
            self.i_criar(audio, f"{nome} PT-BR (Maestro)")
            return
        original = Path(p.var_iso.get().strip())
        modificada = p.iso_montada
        if modificada is None or not Path(modificada).is_file():
            midia = "ROM" if c.criar == "bps" else "ISO"
            escolhida = filedialog.askopenfilename(parent=self, title=f"A {midia} com a tradução (" + (
                "montada pela ferramenta do jogo)" if midia == "ISO" else "com o texto em português)"),
                filetypes=TIPOS_ISO if c.padrao else list(c.tipos))
            if not escolhida:
                return
            modificada = Path(escolhida)
        self.jogo_criar(original, Path(modificada), f"{original.stem} PT-BR (Maestro)")
