"""Aba "🎮 Jogos" → "🔎 Meus jogos": a ligação da tela (painel_meus_jogos.py) com o trabalho
(jellyfin_tools/meus_jogos.py). A AppModerna herda esta parte, como as outras da aba.

A busca roda numa tarefa: acha e identifica os jogos (só os arquivos novos ou mudados são abertos), confere no Redump
(se marcado) e procura a tradução de cada um na comunidade (uma pausa entre um jogo e outro, para não sobrecarregar o
fórum). O que foi lido fica em meus_jogos.json; as pastas e as opções, em jogos.json > "meus_jogos".
"""

from __future__ import annotations

import copy
import time
import webbrowser
from pathlib import Path
from tkinter import filedialog
from urllib.parse import quote_plus

from jellyfin_tools import comunidade as cm
from jellyfin_tools import consoles as cs
from jellyfin_tools import instalar_traducao as it
from jellyfin_tools import meus_jogos as mj
from jellyfin_tools import patch_jogo as pj

from . import config
from .painel_meus_jogos import PainelMeusJogos

MEUS_JOGOS = "🔎 Meus jogos"
SUBTITULO = "Os jogos que você já tem no PC, com a tradução de cada um"
PAUSA_ENTRE_BUSCAS = 1.5                 # segundos entre um jogo e outro na comunidade (o fórum é de voluntários)
ESPERA_AO_ABRIR = 15_000                 # ms depois de abrir o Maestro, para a busca sozinha


class MeusJogos:
    """Parte "🔎 Meus jogos" da aba 🎮 Jogos (usa self.fila, self._rodar, self._trocar_console... da janela)."""

    def _iniciar_meus_jogos(self) -> None:
        self.painel_meus_jogos = None
        self.em_meus_jogos = False
        self._meus_jogos: list[mj.Jogo] = []
        self.after(ESPERA_AO_ABRIR, self._mj_ao_abrir_o_maestro)

    @property
    def arquivo_meus_jogos(self) -> Path:
        return config.ARQUIVO.parent / "meus_jogos.json"

    def _mj_preferencias(self) -> dict:
        dados = self.preferencia_jogos("meus_jogos", {})
        return dados if isinstance(dados, dict) else {}

    def _mj_guardar(self, **valores) -> None:
        dados = self._mj_preferencias()
        dados.update(valores)
        self.guardar_preferencia_jogos("meus_jogos", dados)

    def painel_do_meus_jogos(self) -> PainelMeusJogos:
        if self.painel_meus_jogos is None or not self.painel_meus_jogos.winfo_exists():
            p = self.painel_meus_jogos = PainelMeusJogos(self.aba_jogos, self, {
                "adicionar_pasta": self.mj_adicionar_pasta, "tirar_pasta": self.mj_tirar_pasta,
                "procurar": self.mj_procurar, "abrir": self.mj_abrir, "emulador": self.mj_emulador,
                "abrir_pasta": self.mj_abrir_pasta, "navegador": self.mj_navegador})
            prefs = self._mj_preferencias()
            p.var_traducao.set(bool(prefs.get("traducao", True)))
            p.var_redump.set(bool(prefs.get("redump", True)))
            p.var_sozinho.set(bool(prefs.get("sozinho", False)))
            for var, chave in ((p.var_traducao, "traducao"), (p.var_redump, "redump"), (p.var_sozinho, "sozinho")):
                var.trace_add("write", lambda *_, v=var, c=chave: self._mj_guardar(**{c: bool(v.get())}))
            guardados = [j for j in mj.carregar(self.arquivo_meus_jogos).values() if j.console]
            pastas = [str(x) for x in prefs.get("pastas", [])]
            dentro = [j for j in guardados if any(self._mj_dentro(j.caminho, pasta) for pasta in pastas)]
            self._mj_marcar(dentro)
            self._meus_jogos = dentro
            p.mostrar_pastas(pastas, mj.por_pasta(dentro, pastas) if dentro else None)
            p.mostrar_jogos(dentro)
            if dentro:
                p.mostrar_andamento(1.0, f"{len(dentro)} jogos da última busca · 🔎 Procurar agora lê só os arquivos "
                                         "novos")
        return self.painel_meus_jogos

    @staticmethod
    def _mj_dentro(caminho: str, pasta: str) -> bool:
        try:
            return Path(caminho).resolve().is_relative_to(Path(pasta).resolve())
        except (OSError, ValueError):
            return False

    def _mj_marcar(self, jogos: list) -> None:
        """O que você já traduziu pelo Maestro (os patches aplicados e as traduções instaladas)."""
        mj.marcar_traduzidos(jogos, pj.carregar_aplicados(self.arquivo_aplicados),
                             it.carregar(config.ARQUIVO.parent / "traducoes_instaladas.json"))

    # ------------------------------------------------------------------ mostrar e sair da tela
    def mostrar_meus_jogos(self) -> None:
        p = self.painel_do_meus_jogos()
        self.em_meus_jogos = True
        self.seletor_console_jogos.set(MEUS_JOGOS)
        self.seletor_modo_jogos.master.grid_remove()                # (a tela é de todos os consoles: sem "Modo:")
        for outro in self._todos_os_paineis_jogos():
            if outro is not None and outro is not p and outro.winfo_exists():
                outro.grid_remove()
        p.grid(row=2, column=0, sticky="nsew")
        self.guardar_preferencia_jogos("console", "MEUS")
        if self.seletor_aba.get() == "🎮 Jogos":
            self.lb_titulo.configure(text=self.TITULOS["🎮 Jogos"])
            self.lb_subtitulo.configure(text=SUBTITULO)
            self.after_idle(self._caber_titulo)

    def sair_de_meus_jogos(self) -> None:
        if self.em_meus_jogos:
            self.em_meus_jogos = False
            self.seletor_modo_jogos.master.grid()
            if self.painel_meus_jogos is not None and self.painel_meus_jogos.winfo_exists():
                self.painel_meus_jogos.grid_remove()

    # ------------------------------------------------------------------ 1. onde procurar
    def mj_adicionar_pasta(self) -> None:
        p = self.painel_do_meus_jogos()
        pasta = filedialog.askdirectory(parent=self, title="A pasta dos seus jogos (o HD, o pendrive do OPL ou a "
                                                           "biblioteca da Steam)")
        if not pasta:
            return
        pasta = str(Path(pasta))
        if pasta in p.pastas:
            return
        pastas = p.pastas + [pasta]
        self._mj_guardar(pastas=pastas)
        p.mostrar_pastas(pastas, mj.por_pasta(self._meus_jogos, pastas) if self._meus_jogos else None)

    def mj_tirar_pasta(self) -> None:
        p = self.painel_do_meus_jogos()
        pasta = p.pasta_escolhida()
        if not pasta:
            self.mostrar_mensagem("Meus jogos", "Escolha na lista a pasta que vai sair (os arquivos não são "
                                  "apagados: o Maestro só para de procurar nela).", "aviso")
            return
        pastas = [x for x in p.pastas if x != pasta]
        self._mj_guardar(pastas=pastas)
        self._meus_jogos = [j for j in self._meus_jogos if any(self._mj_dentro(j.caminho, x) for x in pastas)]
        p.mostrar_pastas(pastas, mj.por_pasta(self._meus_jogos, pastas))
        p.mostrar_jogos(self._meus_jogos)

    # ------------------------------------------------------------------ procurar (numa tarefa)
    def mj_procurar(self, automatico: bool = False) -> None:
        p = self.painel_do_meus_jogos()
        pastas = list(p.pastas)
        if not pastas:
            if not automatico:
                self.mostrar_mensagem("Meus jogos", "Adicione primeiro a pasta dos seus jogos (＋ Adicionar pasta).",
                                      "aviso")
            return
        if self.trabalhando:
            if not automatico:
                self.mostrar_mensagem("Meus jogos", "Espere a tarefa de agora terminar.", "aviso")
            return
        traducao, redump_ = p.var_traducao.get(), p.var_redump.get()
        aplicados = pj.carregar_aplicados(self.arquivo_aplicados)
        instaladas = it.carregar(config.ARQUIVO.parent / "traducoes_instaladas.json")
        arquivo = self.arquivo_meus_jogos
        pasta_comunidade, pasta_redump = config.ARQUIVO.parent / "comunidade", config.ARQUIVO.parent / "redump"
        inicio = time.monotonic()

        def andamento(f, texto):
            self.fila.put(("jf_analise", (f, texto)))
            self.fila.put(("jogos", ("mj_andamento", f, texto)))

        def mandar(jogos):
            self.fila.put(("jogos", ("mj_lista", copy.deepcopy(jogos))))

        def tarefa():
            parar = self.evento_parar.is_set
            guardados = mj.carregar(arquivo)
            try:
                jogos, lidos, ignorados = mj.varrer(pastas, guardados, lambda f, t: andamento(0.3 * f, t), parar)
            except pj.ErroPatch as erro:
                self.fila.put(("msg", ("Meus jogos", f"A busca parou: {erro}.", "aviso")))
                return
            mj.marcar_traduzidos(jogos, aplicados, instaladas)
            fora = [j for j in guardados.values() if not any(self._mj_dentro(j.caminho, x) for x in pastas)]
            fila = [j for j in jogos if traducao and mj.precisa_procurar(j)]
            for jogo in fila:
                jogo.procurando = True
            mj.salvar(arquivo, jogos + ignorados + fora)
            mandar(jogos)
            self._log.info("Meus jogos: %d jogos em %d pasta(s) (%d arquivo(s) lidos agora)", len(jogos), len(pastas),
                           lidos)
            try:
                if redump_:
                    self._mj_redump(jogos, pasta_redump, andamento, mandar, parar)
                for k, jogo in enumerate(fila):
                    if parar():
                        raise pj.ErroPatch("interrompido (botão Parar)")
                    andamento(0.7 + 0.3 * k / max(1, len(fila)), f"Procurando a tradução {k + 1} de {len(fila)}: "
                                                                  f"{jogo.titulo}")
                    try:
                        mj.procurar_traducao(jogo, pasta_comunidade)
                    except Exception as erro:           # sem internet: fica para a próxima busca
                        self._log.info("Meus jogos: a busca de %s não deu: %s", jogo.titulo, erro)
                        jogo.traducao = {"quando": time.time(), "achados": [], "aviso": str(erro)[:120]}
                    jogo.procurando = False
                    mandar(jogos)
                    if k + 1 < len(fila):
                        time.sleep(PAUSA_ENTRE_BUSCAS)
            except pj.ErroPatch as erro:
                self.fila.put(("msg", ("Meus jogos", f"A busca parou: {erro}. O que já foi lido ficou guardado.",
                                       "aviso")))
            finally:
                for jogo in jogos:
                    jogo.procurando = False
                mj.salvar(arquivo, jogos + ignorados + fora)
            gasto = time.monotonic() - inicio
            self.fila.put(("jogos", ("mj_pronto", copy.deepcopy(jogos), lidos, gasto)))

        self._rodar("Procurando os seus jogos...", tarefa)

    def _mj_redump(self, jogos, pasta_redump, andamento, mandar, parar) -> None:
        """A impressão digital dos discos ainda não conferidos (uma vez só) e o nome no banco Redump."""
        discos = [j for j in jogos if j.disco and j.redump is None and j.traduzido != "aplicado"]
        indices: dict = {}
        sem_banco: set = set()
        for k, jogo in enumerate(discos):
            if jogo.sistema in sem_banco:
                continue

            def progresso(f, k=k, jogo=jogo):
                andamento(0.3 + 0.4 * (k + f) / len(discos), f"Conferindo no Redump {k + 1} de {len(discos)}: "
                                                              f"{jogo.titulo} {f:.0%}")
            try:
                mj.conferir_redump(jogo, indices, pasta_redump, progresso, parar)
            except pj.ErroPatch as erro:
                if parar():
                    raise
                self._log.info("Meus jogos: Redump de %s: %s", jogo.titulo, erro)
            except Exception as erro:                   # o banco não baixou (sem internet): fica para a próxima
                self._log.info("Meus jogos: banco Redump (%s) indisponível: %s", jogo.sistema, erro)
                sem_banco.add(jogo.sistema)
            mandar(jogos)

    def _mensagem_meus_jogos(self, tipo: str, *dados) -> None:
        p = self.painel_meus_jogos
        if p is None or not p.winfo_exists():
            return
        if tipo == "mj_andamento":
            p.mostrar_andamento(*dados)
        elif tipo in ("mj_lista", "mj_pronto"):
            jogos = dados[0]
            self._meus_jogos = jogos
            p.mostrar_pastas(p.pastas, mj.por_pasta(jogos, p.pastas))
            p.mostrar_jogos(jogos)
            if tipo == "mj_pronto":
                lidos, gasto = dados[1], dados[2]
                minutos = f"{int(gasto // 60)} min {int(gasto % 60)} s" if gasto >= 60 else f"{gasto:.0f} s"
                p.mostrar_andamento(1.0, f"✓ {len(jogos)} jogos · {lidos} arquivo(s) lidos agora em {minutos} · da "
                                         "próxima vez, só os arquivos novos")

    def _mj_ao_abrir_o_maestro(self, tentativas: int = 20) -> None:
        """"Procurar de novo sozinho ao abrir o Maestro": quando a janela estiver livre (só os arquivos novos)."""
        prefs = self._mj_preferencias()
        if not prefs.get("sozinho") or not prefs.get("pastas"):
            return
        if self.trabalhando:
            if tentativas:
                self.after(30_000, lambda: self._mj_ao_abrir_o_maestro(tentativas - 1))
            return
        self._log.info("Meus jogos: procurando sozinho (ao abrir o Maestro)")
        self.mj_procurar(automatico=True)

    # ------------------------------------------------------------------ 3. o jogo escolhido
    def mj_abrir(self, jogo: mj.Jogo, modo: str | None = None) -> None:
        """Abre o jogo no submenu do console, no modo pedido, com o jogo já escolhido. Dois cliques: com tradução na
        comunidade, o patch (ou instalar); sem, o Traduzir e dublar."""
        from .jogos_moderna import MODO_DUBLAR, MODO_ENQUANTO, MODO_INSTALAR, MODO_PATCH
        console = cs.console(jogo.console)
        if console is not self.console_jogos and (self.trabalhando or getattr(self, "_auto_jogo", None) is not None):
            self.mostrar_mensagem("Meus jogos", "Espere a tarefa de agora terminar para abrir o jogo.", "aviso")
            return
        modo = modo or ("patch" if jogo.tem_traducao() else "dublar")
        caminho = Path(jogo.caminho)
        self._trocar_console(console)
        if modo == "patch" and cs.PATCH in console.modos:
            self.mostrar_modo_jogos(MODO_PATCH)
            if jogo.md5:                                # (a impressão digital já medida não é medida de novo)
                try:
                    self._digitais[self._chave(caminho)] = (pj.Digital(jogo.crc32, jogo.md5, ""), jogo.redump)
                except OSError:
                    pass
            self.painel_jogos.var_iso.set(str(caminho))
            self.jogo_ler_iso()
        elif modo == "patch":
            self.mostrar_modo_jogos(MODO_INSTALAR)
            p = self.painel_instalar
            if console.chave == "PC":
                p.var_destino.set(str(caminho))
            elif jogo.codigo:
                p.var_title_id.set(jogo.codigo)
        elif modo == "dublar":
            self.mostrar_modo_jogos(MODO_DUBLAR)
            d = self.painel_dublar_jogo
            if d.com_original:
                d.var_iso.set(str(caminho))
            elif console.chave == "PC" and not d.var_pasta.get().strip():
                d.var_pasta.set(str(caminho))
        else:
            self.mostrar_modo_jogos(MODO_ENQUANTO)
        self._log.info("Meus jogos: %s aberto em %s (%s)", jogo.titulo, console.nome, modo)

    def mj_emulador(self, jogo: mj.Jogo) -> None:
        if jogo.sistema == "Steam":
            appid = jogo.codigo.replace("Steam", "").strip()
            if appid:
                webbrowser.open(f"steam://rungameid/{appid}")
            return
        self.abrir_no_emulador(cs.console(jogo.console), Path(jogo.caminho))

    def mj_abrir_pasta(self, jogo: mj.Jogo) -> None:
        caminho = Path(jogo.caminho)
        self._abrir_pasta_do_sistema(str(caminho if caminho.is_dir() else caminho.parent))

    def mj_navegador(self, jogo: mj.Jogo) -> None:
        """A busca do jogo no Romhacking.net e no itch.io (eles não deixam programas procurarem: o navegador abre)."""
        termos = quote_plus(mj.termos(jogo))
        webbrowser.open(cm.URL_RHN.format(termos=termos))
        webbrowser.open(cm.URL_ITCH.format(termos=termos + "+tradu%C3%A7%C3%A3o"))
