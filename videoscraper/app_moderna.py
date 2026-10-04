"""Liga o motor de scraping à interface moderna.

    JanelaModerna (gui_moderna.py)  -> só aparência; cliques são placeholders
    AppModerna    (este arquivo)    -> herda a janela e preenche os placeholders com o motor

O padrão é o mesmo da interface clássica (gui.py): o trabalho pesado roda numa thread e
conversa com a janela por uma fila, para a tela nunca travar.
"""

from __future__ import annotations

import contextlib
import os
import queue
import subprocess
import sys
import threading
import traceback
import webbrowser
from dataclasses import asdict
from pathlib import Path
from urllib.parse import unquote, urlparse

import tkinter as tk
from tkinter import filedialog

from jellyfin_tools import (CatalogoEmCadeia, CatalogoLocal, CatalogoTMDB, ConfigSite, ErroCatalogo, ErroLegenda,
                            ProvedorOpenSubtitles, ProvedorSiteHTML, ResultadoLegenda, baixar_legenda,
                            baixar_legenda_episodio,
                            baixar_legendas_biblioteca, baixar_legendas_series, desfazer, organizar_pasta)
from jellyfin_tools.legendas import episodios_da_biblioteca, pastas_de_filmes
from jellyfin_tools.organizador import ultimo_log
from jellyfin_tools.site_demo import iniciar_site_demo

from . import config
from .cli import salvar
from .extracao import LinkVideo
from .gui import ORIGENS, _SaidaParaFila, _so_caracteres_basicos
from .gui_moderna import JanelaModerna, OpcoesInterface
from .navegador import PERFIL_PADRAO, PlaywrightAusente
from .servico import MENSAGEM_ROBOTS, Trabalho, fazer_login

PASTA_PADRAO = os.path.abspath("videos_baixados")
TEXTOS_SITUACAO = {"ok": "baixado", "pulado": "pulado", "erro": "erro"}

# Aba Jellyfin: status do organizador / da legenda -> (texto, cor da linha)
STATUS_MOVIMENTO = {"simulado": ("vai mover", None), "movido": ("movido", "ok"),
                    "organizado": ("já organizado", "ok"), "conflito": ("conflito", "pulado"),
                    "nao_identificado": ("não identificado", "pulado"), "ignorado": ("ignorado", None),
                    "erro": ("erro", "erro")}
STATUS_LEGENDA = {"baixada": ("baixada", "ok"), "ja_existe": ("já existia", None),
                  "nao_encontrada": ("não encontrada", "pulado"), "erro": ("erro", "erro"),
                  "sem_video": ("sem vídeo", None)}


class AppModerna(JanelaModerna):
    def __init__(self):
        super().__init__(pasta_padrao=PASTA_PADRAO)
        self.fila: queue.Queue = queue.Queue()
        self.evento_parar = threading.Event()
        self.links: list[LinkVideo] = []
        self.trabalhando = False
        self._texto_fim: str | None = None      # texto do rodapé quando a tarefa acabar
        self._previa = None                     # "assinatura" das opções da última pré-visualização
        self._movimentos_previa: list = []      # o que a última pré-visualização mostrou
        self._carregar_config()
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
                links = t.buscar(url, opcoes.profundidade, opcoes.max_paginas, True, opcoes.seletor,
                                 opcoes.filtro_links)
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
        self._abrir_no_sistema(pasta)

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
                    lista = t.buscar(url, opcoes.profundidade, opcoes.max_paginas, True, opcoes.seletor,
                                     opcoes.filtro_links)
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
                elif tipo == "jf_movimentos":
                    self._mostrar_movimentos(dado)
                elif tipo == "jf_previa":
                    self._previa, quantos = dado
                    self.liberar_organizar(quantos > 0)
                elif tipo == "jf_alvos":
                    self.limpar_tabela_jf()
                    for i, (atual, novo) in enumerate(dado):
                        self.adicionar_linha_jf(str(i), i + 1, "na biblioteca", None, atual, novo)
                elif tipo == "jf_legenda":
                    iid, resultado = dado
                    self.atualizar_linha_jf(iid, *STATUS_LEGENDA.get(resultado.status, (resultado.status, None)))
                elif tipo == "jf_limpar":
                    self.limpar_tabela_jf()
                elif tipo == "status_fim":
                    self._texto_fim = dado
                elif tipo == "fim":
                    self.trabalhando = False
                    self.definir_status(self._texto_fim or f"Pronto. {len(self.links)} vídeo(s) na lista.",
                                        ocupado=False)
                    self._texto_fim = None
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

    # ================================================================== aba Jellyfin
    def ao_previsualizar(self) -> None:
        o = self._validar_jellyfin()
        if not o:
            return
        self._salvar_config()
        assinatura = self._assinatura(o)

        def tarefa():
            print(f"\nPré-visualizando ({'séries' if o.modo == 'series' else 'filmes'}): {o.origem} -> {o.destino}")
            movimentos = organizar_pasta(o.origem, o.destino, self._catalogo(o), aplicar=False,
                                         incluir_tmdbid=o.incluir_tmdbid, exigir_catalogo=o.exigir_catalogo,
                                         modo=o.modo, limpar_lixo=o.limpar_lixo)
            for m in movimentos:
                print(m)
            quantos = sum(m.status == "simulado" for m in movimentos)
            prontos = sum(m.status == "organizado" for m in movimentos)
            self.fila.put(("jf_movimentos", movimentos))
            self.fila.put(("jf_previa", (assinatura, quantos)))
            self.fila.put(("status_fim", f"Pré-visualização: {quantos} para mover, {prontos} já organizado(s), "
                                         f"{len(movimentos) - quantos - prontos} com pendência. Nada foi movido."))
            if not movimentos:
                self.fila.put(("msg", ("Nenhum vídeo", f"Não achei vídeos em:\n{o.origem}", "aviso")))

        self._rodar("Pré-visualizando...", tarefa)

    def ao_organizar(self) -> None:
        o = self._validar_jellyfin()
        if not o:
            return
        if self._previa != self._assinatura(o):
            self.liberar_organizar(False)
            self.mostrar_mensagem("Pré-visualize de novo", "As pastas ou opções mudaram desde a pré-visualização. "
                                  "Clique em Pré-visualizar para conferir antes de mover.", "aviso")
            return
        problema = self._problema_legendas(o) if o.legendas else None
        if problema:
            self.mostrar_mensagem("Legendas", problema, "aviso")
            return
        quantos = sum(m.status == "simulado" for m in self._movimentos_previa)
        lixo = sum(len(m.apagar or []) for m in self._movimentos_previa) if o.limpar_lixo else 0
        aviso_lixo = (f"\n\n{lixo} arquivo(s) de lixo (.url, .txt, trailers) serão APAGADOS. "
                      "Isso não tem como desfazer." if lixo else "")
        if not self.perguntar("Organizar", f"Mover {quantos} arquivo(s) para:\n{o.destino}\n\n"
                              "Nada é sobrescrito, e você pode voltar atrás com 'Desfazer última'."
                              + aviso_lixo):
            return
        self._salvar_config()
        self._previa = None
        self.liberar_organizar(False)

        def tarefa():
            print(f"\nOrganizando: {o.origem} -> {o.destino}")
            movimentos = organizar_pasta(o.origem, o.destino, self._catalogo(o), aplicar=True,
                                         incluir_tmdbid=o.incluir_tmdbid, exigir_catalogo=o.exigir_catalogo,
                                         modo=o.modo, limpar_lixo=o.limpar_lixo)
            for m in movimentos:
                print(m)
            self.fila.put(("jf_movimentos", movimentos))
            movidos = [(i, m) for i, m in enumerate(movimentos) if m.status == "movido"]
            legendas = 0
            if o.legendas and movidos:
                print("\nBaixando legendas...")
                with self._provedores(o) as provedores:
                    for i, m in movidos:
                        if self.evento_parar.is_set():
                            print("Legendas interrompidas.")
                            break
                        resultado = self._legenda_do_movimento(m, provedores, o)
                        print(resultado)
                        legendas += resultado.status == "baixada"
                        self.fila.put(("jf_legenda", (str(i), resultado)))
            erros = sum(m.status == "erro" for m in movimentos)
            self.fila.put(("status_fim", f"Organizado: {len(movidos)} movido(s), {legendas} legenda(s)."))
            self.fila.put(("msg", ("Organização concluída",
                                   f"Movidos: {len(movidos)}\nLegendas baixadas: {legendas}\nCom erro: {erros}\n\n"
                                   "Para voltar atrás, use 'Desfazer última'.", "erro" if erros else "sucesso")))

        self._rodar("Organizando...", tarefa)

    def ao_baixar_legendas(self) -> None:
        o = self._validar_jellyfin(precisa_origem=False)
        if not o:
            return
        if not Path(o.destino).is_dir():
            self.mostrar_mensagem("Biblioteca não encontrada", f"A pasta não existe:\n{o.destino}", "aviso")
            return
        problema = self._problema_legendas(o)
        if problema:
            self.mostrar_mensagem("Legendas", problema, "aviso")
            return
        self._salvar_config()
        self._previa = None
        self.liberar_organizar(False)
        destino = Path(o.destino)

        def tarefa():
            if o.modo == "series":
                alvos = episodios_da_biblioteca(destino)
                linhas = [("/".join(v.relative_to(destino).parts), f"{v.stem}.{o.idioma}.srt") for v in alvos]
                funcao = baixar_legendas_series
            else:
                alvos = pastas_de_filmes(destino)
                linhas = [(p.name, f"{p.name}.{o.idioma}.srt") for p in alvos]
                funcao = baixar_legendas_biblioteca
            self.fila.put(("jf_alvos", linhas))
            print(f"\nProcurando legendas para {len(alvos)} item(ns) em {destino}")
            with self._provedores(o) as provedores:
                resultados = funcao(destino, provedores, o.idioma, o.sobrescrever, catalogo=self._catalogo(o),
                                    ao_terminar=lambda i, r: self.fila.put(("jf_legenda", (str(i), r))),
                                    parar=self.evento_parar.is_set)
            baixadas = sum(r.status == "baixada" for r in resultados)
            self.fila.put(("status_fim", f"Legendas: {baixadas} baixada(s) de {len(alvos)} item(ns)."))

        self._rodar("Baixando legendas...", tarefa)

    def ao_desfazer(self) -> None:
        o = self._validar_jellyfin(precisa_origem=False)
        if not o:
            return
        log = ultimo_log(o.destino) if Path(o.destino).is_dir() else None
        if not log:
            self.mostrar_mensagem("Nada para desfazer", f"Não há organização registrada em:\n{o.destino}", "info")
            return
        if not self.perguntar("Desfazer", "Devolver os arquivos da última organização para onde estavam?\n\n"
                              "Legendas baixadas depois continuam na biblioteca."):
            return
        self._previa = None
        self.liberar_organizar(False)

        def tarefa():
            print(f"\nDesfazendo: {log.name}")
            mensagens = desfazer(log)
            for m in mensagens:
                print(m)
            voltaram = sum(m.startswith("voltou") for m in mensagens)
            self.fila.put(("jf_limpar", None))
            self.fila.put(("status_fim", f"Desfeito: {voltaram} arquivo(s) voltaram."))
            self.fila.put(("msg", ("Desfeito", f"{voltaram} arquivo(s) voltaram para a pasta de origem.", "sucesso")))

        self._rodar("Desfazendo...", tarefa)

    def ao_abrir_biblioteca(self) -> None:
        destino = self.obter_opcoes_jellyfin().destino
        if not destino or not Path(destino).is_dir():
            self.mostrar_mensagem("Biblioteca", "Escolha uma pasta de biblioteca que exista.", "aviso")
            return
        self._abrir_no_sistema(destino)

    # --- auxiliares da aba Jellyfin
    def _validar_jellyfin(self, precisa_origem: bool = True):
        o = self.obter_opcoes_jellyfin()
        tipo = "Séries" if o.modo == "series" else "Filmes"
        if precisa_origem and (not o.origem or not Path(o.origem).expanduser().is_dir()):
            self.mostrar_mensagem("Pasta de origem", "Escolha a pasta com os arquivos para organizar "
                                  "(ela precisa existir).", "aviso")
            return None
        if not o.destino:
            self.mostrar_mensagem("Biblioteca", f"Escolha a pasta da biblioteca de {tipo} do Jellyfin.", "aviso")
            return None
        if o.tmdb and not o.chave_tmdb:
            self.mostrar_mensagem("Chave do TMDB", "Preencha a chave da API do TMDB ou desmarque "
                                  "'Consultar também o TMDB'.", "aviso")
            return None
        return o

    @staticmethod
    def _assinatura(o) -> tuple:
        """O que, se mudar, invalida a pré-visualização."""
        return (o.modo, o.origem, o.destino, o.tmdb, o.chave_tmdb, o.incluir_tmdbid, o.exigir_catalogo,
                o.limpar_lixo)

    def _problema_legendas(self, o) -> str | None:
        fontes = self.FONTES_LEGENDA
        if o.fonte_legenda == fontes[1] and not o.chave_opensubtitles:
            return "Preencha a chave da API do OpenSubtitles (é gratuita em opensubtitles.com)."
        if o.fonte_legenda == fontes[2] and "{consulta}" not in o.url_site:
            return "A URL de busca precisa ter {consulta} no lugar do termo pesquisado.\n" \
                   "Ex.: https://site.com/busca?q={consulta}"
        return None

    def _catalogo(self, o):
        local = CatalogoLocal.padrao()
        return CatalogoEmCadeia(local, CatalogoTMDB(o.chave_tmdb)) if o.tmdb else local

    @contextlib.contextmanager
    def _provedores(self, o):
        """Cria o provedor de legendas escolhido (e desliga o site de demonstração no fim)."""
        fontes = self.FONTES_LEGENDA
        servidor = None
        try:
            if o.fonte_legenda == fontes[0]:
                servidor, base = iniciar_site_demo()
                yield [ProvedorSiteHTML(ConfigSite(f"{base}/busca?q={{consulta}}", nome="site demo"))]
            elif o.fonte_legenda == fontes[1]:
                yield [ProvedorOpenSubtitles(o.chave_opensubtitles)]
            else:
                yield [ProvedorSiteHTML(ConfigSite(o.url_site))]
        finally:
            if servidor:
                servidor.shutdown()

    @staticmethod
    def _legenda_do_movimento(m, provedores, o):
        originais = [m.filme.titulo_original] if m.filme and m.filme.titulo_original else []
        try:
            if m.episodio:
                return baixar_legenda_episodio(m.destino, provedores, idioma=o.idioma, sobrescrever=o.sobrescrever,
                                               titulos_alternativos=originais)
            return baixar_legenda(m.destino.parent, provedores, idioma=o.idioma, sobrescrever=o.sobrescrever,
                                  titulos_alternativos=originais)
        except (ErroLegenda, ErroCatalogo) as erro:
            return ResultadoLegenda(m.destino.parent, "erro", detalhe=str(erro))

    def _mostrar_movimentos(self, movimentos) -> None:
        self._movimentos_previa = list(movimentos)
        self.limpar_tabela_jf()
        for i, m in enumerate(movimentos):
            texto, cor = STATUS_MOVIMENTO.get(m.status, (m.status, None))
            if m.status == "simulado" and m.detalhe:
                texto = "vai mover (confira)"       # nome não confirmado no catálogo
            # Só o nome do arquivo: a pasta tem o mesmo nome (Filmes/Nome (Ano)/Nome (Ano).mkv)
            novo = m.destino.name if m.destino else f"({m.detalhe})"
            if m.destino and m.resumo_extras and m.status in ("simulado", "movido"):
                novo += f"   ({m.resumo_extras})"
            self.adicionar_linha_jf(str(i), i + 1, texto, cor, m.origem.name, novo)

    # --- configurações (pastas e opções lembradas entre execuções)
    def _carregar_config(self) -> None:
        dados = config.carregar().get("jellyfin", {})
        dados.setdefault("chave_tmdb", os.environ.get("TMDB_API_KEY", ""))
        dados.setdefault("chave_opensubtitles", os.environ.get("OPENSUBTITLES_API_KEY", ""))
        dados.setdefault("origem", PASTA_PADRAO)
        self.definir_opcoes_jellyfin(dados)

    def _salvar_config(self) -> None:
        o = self.obter_opcoes_jellyfin()
        dados = asdict(o)
        for chave in ("destino", "modo"):
            dados.pop(chave)
        destinos = self.destinos_jellyfin()
        dados["destino_filmes"], dados["destino_series"] = destinos["Filmes"], destinos["Séries"]
        if not o.lembrar_chaves:                     # chaves de API só se o usuário pedir
            dados.pop("chave_tmdb")
            dados.pop("chave_opensubtitles")
        tudo = config.carregar()
        tudo["jellyfin"] = dados
        config.salvar(tudo)

    @staticmethod
    def _abrir_no_sistema(pasta: str) -> None:
        if sys.platform.startswith("win"):
            os.startfile(pasta)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", pasta])

    def fechar(self) -> None:
        if self.trabalhando and not self.perguntar("Sair", "Ainda está trabalhando. Sair mesmo assim?"):
            return
        self._salvar_config()
        self.evento_parar.set()
        sys.stdout, sys.stderr = self._stdout, self._stderr
        self.destroy()


def main() -> int:
    AppModerna().mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
