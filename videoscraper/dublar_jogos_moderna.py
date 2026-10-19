"""Aba "🎮 Jogos", modo "🗣 Traduzir e dublar (no PC)": a ligação da tela (painel_dublar_jogo.py) com o trabalho
(jellyfin_tools: iso_jogo, roteiro_jogo, dublar_jogo). A AppModerna herda esta parte, como a do patch.

O que fica guardado na pasta da entrega (".maestro"): as traduções (traducao.json: a mesma frase não é traduzida de
novo, e o que você corrigiu vale para sempre), as vozes escolhidas na tabela e as falas já dubladas (retomar).
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from jellyfin_tools import dublar_jogo as dj
from jellyfin_tools import iso_jogo as ij
from jellyfin_tools import patch_jogo as pj
from jellyfin_tools import personagens, voz_gemini, voz_local
from jellyfin_tools import roteiro_jogo as rj
from jellyfin_tools.dublagem import localizar_ffmpeg

from . import automacao, config
from .painel_dublar_jogo import EMOCOES, MOTORES, QUEM_TRADUZ, PainelDublarJogo

TIPOS_ROTEIRO = [("Roteiro do jogo", "*.csv *.tsv *.txt *.json"), ("Todos os arquivos", "*.*")]
NOMES_DE_ROTEIRO = ("roteiro", "script", "texto", "textos", "strings", "dialog", "dialogo", "falas", "msg", "text")
ARQUIVO_MEMORIA = "traducao.json"
ARQUIVO_ELENCO = "elenco.json"


class DublagemDeJogos:
    """Parte "Traduzir e dublar (no PC)" da aba 🎮 Jogos (usa self.fila, self._rodar... da janela)."""

    def _iniciar_dublar_jogo(self) -> None:
        self.painel_dublar_jogo = None
        self._memoria_jogo: dict = {}
        self._fixas_jogo: dict = {}

    def painel_do_modo_dublar(self) -> PainelDublarJogo:
        if self.painel_dublar_jogo is None or not self.painel_dublar_jogo.winfo_exists():
            self.painel_dublar_jogo = PainelDublarJogo(self.aba_jogos, self, {
                "escolher_pasta": self.d_escolher_pasta, "ler": self.d_ler, "escolher_roteiro": self.d_escolher_roteiro,
                "escolher_iso": self.d_escolher_iso, "analisar": self.d_analisar, "relatorio": self.d_relatorio,
                "extrair": self.d_extrair, "traduzir": self.d_traduzir, "traduzir_teste": lambda: self.d_traduzir(20),
                "editar": self.d_editar, "custos": self.d_custos, "motor": self.d_motor,
                "trocar_voz": self.d_trocar_voz, "dublar": self.d_dublar, "dublar_teste": lambda: self.d_dublar(5),
                "ouvir": self.d_ouvir, "editar_fala": self.d_editar_fala, "escolher_saida": self.d_escolher_saida,
                "entregar": self.d_entregar, "abrir_saida": self.d_abrir_saida, "montar": self.d_montar,
                "criar_patch": self.d_criar_patch})
            self.painel_dublar_jogo.var_iso.trace_add("write", lambda *_: self.painel_dublar_jogo.atualizar())
            self.painel_dublar_jogo.mostrar_estimativas(motor=self._estado_do_motor())
        return self.painel_dublar_jogo

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
            return "⚠ XTTS-v2 ainda não instalado (Configurações > Dublagem)"
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
        elif tipo == "d_traduzido":
            p.mostrar_traducao(dados[0])
            self._refazer_elenco()
            p.atualizar()
        elif tipo == "d_andamento":
            p.mostrar_andamento(*dados)
        elif tipo == "d_dublado":
            r, = dados
            texto = f"{r.dubladas} falas dubladas" + (f" · {r.puladas} já estavam prontas" if r.puladas else "") + \
                (f" · {len(r.erros)} com erro (veja o log)" if r.erros else "")
            p.mostrar_andamento(1.0, "")
            p.mostrar_dublagem(texto, not r.erros)
            self._refazer_elenco()
        elif tipo == "d_entregue":
            arquivos, saida = dados
            p.mostrar_entrega("✓ Pronto em " + str(saida) + ": " + ", ".join(a.name for a in arquivos) +
                              f" e {dj.PASTA_SAIDA_AUDIO}\\")
        elif tipo == "d_montado":
            m, = dados
            p.iso_montada = m.destino
            p.mostrar_entrega(f"✓ ISO em português: {m.destino.name} ({m.trocadas} falas trocadas no mesmo lugar" +
                              (f"; {len(m.puladas)} puladas, veja o log" if m.puladas else "") + "). A original não "
                              "mudou.", not m.puladas)

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
        arquivo = filedialog.askopenfilename(parent=self, title="A ISO tirada do SEU disco", filetypes=TIPOS_ISO)
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
            iso = Path(iso_tela) if iso_tela else next(iter(sorted(pasta.parent.glob("*.iso"))), None)
            jogo = ""
            if iso is not None and iso.is_file():
                try:
                    jogo = pj.ler_info(iso).descrever() + ("  (lido da ISO ao lado)" if not iso_tela else "")
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
        roteiro, falas = p.roteiro, p.falas
        glossario, sem_acentos, ouvir = self._glossario(), p.var_sem_acentos.get(), p.var_ouvir.get()
        saida = self._saida_jogo()

        def tarefa():
            andamento = lambda f, texto: self.fila.put(("jf_analise", (f, texto)))   # noqa: E731
            try:
                sem_texto = [f for f in falas if f.formato is not None and not f.texto.strip()]
                if ouvir and sem_texto and saida is not None:
                    from jellyfin_tools.transcricao import Transcritor
                    transcritor = Transcritor(modelo=o.modelo_whisper, usar_gpu=o.whisper_gpu,
                                              pasta_modelos=str(config.ARQUIVO.parent / "modelos_whisper"))
                    alvo = sem_texto[:so] if so else sem_texto
                    dj.ouvir(alvo, transcritor, saida / dj.PASTA_TRABALHO, None, self.evento_parar.is_set,
                             lambda f: andamento(0.3 * f, f"O Whisper ouvindo as falas sem texto: {f:.0%}"))
                resumo = rj.ResumoTraducao()
                if roteiro is not None:
                    resumo = rj.traduzir_roteiro(roteiro, tradutor, glossario, sem_acentos, self._memoria_jogo, so,
                                                 self.evento_parar.is_set,
                                                 lambda f: andamento(0.3 + 0.6 * f, f"Traduzindo: {f:.0%}"))
                dj.ligar_traducoes(falas)
                ouvidas = [f for f in falas if f.ouvida]
                if ouvidas:
                    r2 = dj.traduzir_ouvidas(ouvidas[:so] if so else ouvidas, tradutor, glossario, sem_acentos,
                                             self._memoria_jogo, self.evento_parar.is_set,
                                             lambda f: andamento(0.9 + 0.1 * f, f"Traduzindo as falas ouvidas: {f:.0%}"))
                    resumo.traduzidas += r2.traduzidas
                    resumo.encurtadas += r2.encurtadas
                resumo.custo = getattr(tradutor, "custo", None)
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

        self._rodar("Traduzindo o jogo" + (f" (as {so} primeiras)" if so else "") + "...", tarefa)

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
        o = self._opcoes_do_jogo()
        falas = p.falas
        alvo = falas_so if falas_so is not None else ([f for f in falas if f.formato is not None and f.traducao][:so]
                                                      if so else None)
        if not any(f.traducao for f in (alvo if alvo is not None else falas)):
            self.mostrar_mensagem("Dublar no PC", "Traduza antes (2. Tradução): a voz fala a tradução.", "aviso")
            return
        formato, duracao = p.var_formato.get(), p.var_duracao.get()
        com_emocao = p.var_emocao.get() == EMOCOES[0]

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
                              self.evento_parar.is_set,
                              lambda f: (self.fila.put(("jf_analise", (f, f"Dublando: {f:.0%}"))),
                                         self.fila.put(("jogos", ("d_andamento", f, f"{round(f * total)} de {total} "
                                                                  f"falas · {f:.0%}")))))
            finally:
                if hasattr(motor, "fechar"):
                    motor.fechar()
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
        roteiro, falas = p.roteiro, p.falas

        def tarefa():
            arquivos = dj.entregar(roteiro, falas, saida)
            self._guardar_memoria_jogo(saida)
            self._log.info("Tradução do jogo entregue em %s: %s", saida, ", ".join(a.name for a in arquivos))
            self.fila.put(("jogos", ("d_entregue", arquivos, saida)))

        self._rodar("Gerando o roteiro e as vozes em português...", tarefa)

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
        try:
            info = pj.ler_info(iso)
        except pj.ErroPatch as erro:
            self.mostrar_mensagem("Montar a ISO", str(erro), "aviso")
            return
        destino = saida / pj.nome_para_o_opl(info, f"{iso.stem} PT-BR")

        def tarefa():
            try:
                m = ij.montar(iso, pasta, saida / dj.PASTA_SAIDA_AUDIO, destino, self.evento_parar.is_set,
                              lambda f: self.fila.put(("jf_analise", (f, f"Montando a ISO em português: {f:.0%}"))))
            except (pj.ErroPatch, OSError) as erro:
                self.fila.put(("msg", ("Montar a ISO", f"Não montei: {erro}", "aviso")))
                return
            for relativo, motivo in m.puladas:
                self._log.warning("Montar a ISO: %s pulada (%s)", relativo, motivo)
            self._log.info("ISO em português: %s (%d falas trocadas)", m.destino, m.trocadas)
            pj.registrar_aplicado(self.arquivo_aplicados, iso, saida, m.destino, "montada pelo Maestro")
            self.fila.put(("jogos", ("d_montado", m)))

        self._rodar(f"Montando {destino.name}...", tarefa)

    def d_criar_patch(self) -> None:
        """O .xdelta da tradução: a ISO original + a montada (pelo Maestro ou pela ferramenta do jogo)."""
        from .jogos_moderna import TIPOS_ISO
        p = self.painel_dublar_jogo
        original = Path(p.var_iso.get().strip())
        modificada = p.iso_montada
        if modificada is None or not Path(modificada).is_file():
            escolhida = filedialog.askopenfilename(parent=self, title="A ISO com a tradução (montada pela ferramenta "
                                                   "do jogo)", filetypes=TIPOS_ISO)
            if not escolhida:
                return
            modificada = Path(escolhida)
        self.jogo_criar(original, Path(modificada), f"{original.stem} PT-BR (Maestro)")
