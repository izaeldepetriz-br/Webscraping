"""Liga o motor de scraping à interface moderna.

    JanelaModerna (gui_moderna.py)  -> só aparência; cliques são placeholders
    AppModerna    (este arquivo)    -> herda a janela e preenche os placeholders com o motor

O padrão é o mesmo da interface clássica (gui.py): o trabalho pesado roda numa thread e
conversa com a janela por uma fila, para a tela nunca travar.
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import traceback
import webbrowser
from urllib.parse import unquote, urlparse

import tkinter as tk
from tkinter import filedialog

from .cli import salvar
from .extracao import LinkVideo
from .gui import ORIGENS, _SaidaParaFila, _so_caracteres_basicos
from .gui_moderna import JanelaModerna, OpcoesInterface
from .navegador import PERFIL_PADRAO, PlaywrightAusente
from .servico import MENSAGEM_ROBOTS, Trabalho, fazer_login

PASTA_PADRAO = os.path.abspath("videos_baixados")
TEXTOS_SITUACAO = {"ok": "baixado", "pulado": "pulado", "erro": "erro"}


class AppModerna(JanelaModerna):
    def __init__(self):
        super().__init__(pasta_padrao=PASTA_PADRAO)
        self.fila: queue.Queue = queue.Queue()
        self.evento_parar = threading.Event()
        self.links: list[LinkVideo] = []
        self.trabalhando = False
        self._stdout, self._stderr = sys.stdout, sys.stderr
        self.protocol("WM_DELETE_WINDOW", self.fechar)
        self.redirecionar_saida()
        self.after(100, self._processar_fila)

    def redirecionar_saida(self) -> None:
        sys.stdout = sys.stderr = _SaidaParaFila(self.fila)

    # ================================================================== placeholders preenchidos
    def ao_buscar(self) -> None:
        url, opcoes = self._validar()
        if not url:
            return
        self._mostrar_links([])

        def tarefa():
            with self._novo_trabalho(opcoes) as t:
                print(f"Acessando{' com navegador' if t.usa_navegador else ''}: {url}")
                links = t.buscar(url, opcoes.profundidade, opcoes.max_paginas, True, opcoes.seletor)
                print(f"{len(links)} vídeo(s) encontrado(s).")
                self.fila.put(("links", links))
                self._explicar_resultado(t, links)

        self._rodar("Buscando vídeos...", tarefa)

    def ao_baixar_selecionados(self) -> None:
        ids = self.selecionados()
        if not ids:
            self.mostrar_mensagem("Nada selecionado", "Clique nos vídeos da lista (Ctrl+clique para vários) "
                                  "e tente de novo, ou use 'Baixar todos'.", "aviso")
            return
        self._baixar([self.links[int(i)] for i in ids])

    def ao_baixar_todos(self) -> None:
        self._baixar(list(self.links))

    def ao_fazer_login(self) -> None:
        url, _ = self._validar()
        if not url:
            return
        if not self.perguntar("Fazer login", "Vai abrir uma janela do navegador neste site. Entre com a SUA "
                              "conta e depois clique em OK na mensagem que vai aparecer.\n\nA sessão fica salva "
                              "no seu computador (pasta .perfil_navegador). Não compartilhe essa pasta: ela dá "
                              "acesso à sua conta."):
            return

        def tarefa():
            fazer_login(url, perfil=PERFIL_PADRAO, aguardar_usuario=self._aguardar_usuario)
            self.fila.put(("msg", ("Login salvo", "Pronto! Agora marque 'Usar navegador' para aproveitar o login.",
                                   "sucesso")))
            self.fila.put(("marcar_navegador", None))

        self._rodar("Esperando você fazer login...", tarefa)

    def ao_parar(self) -> None:
        self.evento_parar.set()
        self.definir_status("Parando... (termina o item atual)")

    def ao_abrir_link(self) -> None:
        link = self._link_selecionado()
        if link:
            webbrowser.open(link.url)

    def ao_copiar_link(self) -> None:
        link = self._link_selecionado()
        if link:
            self.clipboard_clear()
            self.clipboard_append(link.url)
            self.definir_status("Link copiado.")

    def ao_salvar_lista(self) -> None:
        if not self.links:
            self.mostrar_mensagem("Lista vazia", "Busque vídeos primeiro.", "aviso")
            return
        caminho = filedialog.asksaveasfilename(
            defaultextension=".csv", initialfile="links.csv",
            filetypes=[("Planilha CSV", "*.csv"), ("JSON", "*.json"), ("Texto", "*.txt")])
        if caminho:
            salvar(self.links, caminho)
            self.definir_status(f"Lista salva em {caminho}")

    def ao_abrir_pasta(self) -> None:
        pasta = self.obter_opcoes().pasta
        os.makedirs(pasta, exist_ok=True)
        if sys.platform.startswith("win"):
            os.startfile(pasta)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", pasta])

    # ================================================================== motor
    def _baixar(self, escolhidos: list[LinkVideo]) -> None:
        url, opcoes = self._validar(exigir_url=not self.links)
        if not opcoes:
            return
        if opcoes.limite:
            escolhidos = escolhidos[:opcoes.limite]

        def tarefa():
            with self._novo_trabalho(opcoes) as t:
                lista = escolhidos
                if not lista:                         # ainda não buscou: busca primeiro
                    print(f"Acessando: {url}")
                    lista = t.buscar(url, opcoes.profundidade, opcoes.max_paginas, True, opcoes.seletor)
                    self.fila.put(("links", lista))
                    if not lista:
                        self._explicar_resultado(t, lista)
                        return
                    if opcoes.limite:
                        lista = lista[:opcoes.limite]
                resumo = t.baixar(lista, opcoes.pasta,
                                  ao_terminar_item=lambda l, st, det: self.fila.put(("item", (l.url, st))))
                self.fila.put(("msg", ("Downloads concluídos",
                                       f"Baixados: {resumo.ok}\nPulados: {resumo.pulados}\n"
                                       f"Com erro: {resumo.falhas}\n\nPasta: {opcoes.pasta}",
                                       "erro" if resumo.falhas else "sucesso")))

        self._rodar("Baixando vídeos...", tarefa)

    def _rodar(self, status: str, tarefa) -> None:
        if self.trabalhando:
            return
        self.trabalhando = True
        self.evento_parar.clear()
        self.definir_status(status, ocupado=True)

        def alvo():
            try:
                tarefa()
            except PlaywrightAusente as erro:
                self.fila.put(("msg", ("Navegador indisponível", str(erro), "erro")))
            except Exception as erro:
                traceback.print_exc()
                self.fila.put(("msg", ("Erro", f"{type(erro).__name__}: {erro}", "erro")))
            finally:
                self.fila.put(("fim", None))

        threading.Thread(target=alvo, daemon=True).start()

    def _novo_trabalho(self, o: OpcoesInterface) -> Trabalho:
        return Trabalho(espera=o.espera, navegador=o.navegador, visivel=o.visivel, pausar=o.pausar,
                        perfil=PERFIL_PADRAO, aguardar_usuario=self._aguardar_usuario,
                        parar=self.evento_parar.is_set)

    def _aguardar_usuario(self, mensagem: str) -> None:
        """Chamado pela thread: pede à janela um aviso e espera o OK do usuário."""
        ok = threading.Event()
        self.fila.put(("aguardar", (mensagem, ok)))
        ok.wait()

    def _explicar_resultado(self, t: Trabalho, links: list[LinkVideo]) -> None:
        if links:
            return
        if t.bloqueadas:
            self.fila.put(("msg", ("Acesso não permitido", MENSAGEM_ROBOTS, "aviso")))
        elif not t.usa_navegador:
            self.fila.put(("msg", ("Nenhum vídeo encontrado", "Nenhum vídeo no HTML da página.\n\nSe a página "
                                   "monta a lista com JavaScript ou exige login, marque 'Usar navegador' e "
                                   "busque de novo.", "info")))
        else:
            self.fila.put(("msg", ("Nenhum vídeo encontrado", "Nem com o navegador apareceu vídeo. Tente "
                                   "'Pausar para eu resolver verificações', 'Fazer login no site' ou um "
                                   "seletor CSS.", "info")))

    def _processar_fila(self) -> None:
        try:
            while True:
                tipo, dado = self.fila.get_nowait()
                if tipo == "log":
                    self.escrever_log(_so_caracteres_basicos(dado))
                elif tipo == "links":
                    self._mostrar_links(dado)
                elif tipo == "item":
                    self._marcar_item(*dado)
                elif tipo == "aguardar":
                    mensagem, ok = dado
                    self.mostrar_mensagem("Sua vez", mensagem + "\n\nClique em OK quando terminar.")
                    ok.set()
                elif tipo == "msg":
                    self.mostrar_mensagem(*dado)
                elif tipo == "marcar_navegador":
                    self.marcar_navegador()
                elif tipo == "fim":
                    self.trabalhando = False
                    self.definir_status(f"Pronto. {len(self.links)} vídeo(s) na lista.", ocupado=False)
        except queue.Empty:
            pass
        except tk.TclError:          # a janela foi fechada no meio do processamento
            return
        self.after(100, self._processar_fila)

    # ================================================================== auxiliares
    def _validar(self, exigir_url: bool = True):
        url = self.obter_url()
        if url and not url.startswith(("http://", "https://")):
            url = "https://" + url
            self.definir_url(url)
        if exigir_url and not url:
            self.mostrar_mensagem("Falta o endereço", "Cole o endereço da página (ex.: https://site.com/videos).",
                                  "aviso")
            return None, None
        return url, self.obter_opcoes()

    def _mostrar_links(self, links: list[LinkVideo]) -> None:
        self.links = list(links)
        self.limpar_tabela()
        for i, l in enumerate(self.links):
            titulo = l.titulo or unquote(os.path.basename(urlparse(l.url).path)) or l.url
            self.adicionar_video(str(i), i + 1, "", titulo, ORIGENS.get(l.tipo, l.tipo), l.url)

    def _marcar_item(self, url: str, status: str) -> None:
        for i, l in enumerate(self.links):
            if l.url == url:
                self.atualizar_situacao(str(i), TEXTOS_SITUACAO.get(status, status), status)

    def _link_selecionado(self) -> LinkVideo | None:
        ids = self.selecionados()
        if not ids:
            self.mostrar_mensagem("Nenhum link", "Selecione um vídeo da lista primeiro.", "aviso")
            return None
        return self.links[int(ids[0])]

    def fechar(self) -> None:
        if self.trabalhando and not self.perguntar("Sair", "Ainda está trabalhando. Sair mesmo assim?"):
            return
        self.evento_parar.set()
        sys.stdout, sys.stderr = self._stdout, self._stderr
        self.destroy()


def main() -> int:
    AppModerna().mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
