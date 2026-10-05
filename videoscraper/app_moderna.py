"""Liga o motor de scraping à interface moderna.

    JanelaModerna (gui_moderna.py)  -> só aparência; cliques são placeholders
    AppModerna    (este arquivo)    -> herda a janela e preenche os placeholders com o motor

O padrão é o mesmo da interface clássica (gui.py): o trabalho pesado roda numa thread e
conversa com a janela por uma fila, para a tela nunca travar.
"""

from __future__ import annotations

import contextlib
import logging
import os
import queue
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import unquote, urlparse

import tkinter as tk
from tkinter import filedialog

from jellyfin_tools import (CatalogoEmCadeia, CatalogoLocal, CatalogoTMDB, ConfigSite, ErroCatalogo,
                            ProvedorOpenSubtitles, ProvedorSiteHTML, ProvedorSubDL, desfazer, organizar_pasta)
from jellyfin_tools.legendas import normalizar_idiomas
from jellyfin_tools.nomes import extrair_episodio, extrair_titulo_e_ano, normalizar, serie_da_pasta
from jellyfin_tools.metadados import ClienteTMDB
from jellyfin_tools.notificacoes import Notificador
from jellyfin_tools.espelho import (aplicar_espelho, classificar, conferir_e_avisar, conferir_espelhos,
                                    desfazer_ultima_remocao, intervalo_em_segundos, licenca_aberta,
                                    lotes_de_espelhos, nome_do_link, planejar_espelho, remover_espelhos,
                                    remover_espelhos_escolhidos, verificar_links)
from jellyfin_tools.conflitos import aplicar as aplicar_conflitos, decidir as decidir_conflitos
from jellyfin_tools.tv_ao_vivo import (Canal, ClienteTV, NaoEhLista, carregar_canais, conferir_canais, importar as importar_canais,
                                       mensagem_fora_do_ar, publicar as publicar_canais, salvar_canais)
from jellyfin_tools.regras import RegraNome, adicionar_regra, carregar_regras, regra_para, salvar_regras
from jellyfin_tools.organizador import (DETALHE_EPISODIO, episodio_do_video, protegido, organizar_misto, problema_no_caminho, sugestao_de_caminho,
                                       ultimo_log)
from jellyfin_tools.pos_processamento import ConfigPos, itens_da_biblioteca, itens_de_series, pos_processar
from jellyfin_tools.registro import configurar_log, encerrar_log_da_acao, iniciar_log_da_acao
from jellyfin_tools.relatorio import gerar_relatorio, resumo, salvar_csv
from jellyfin_tools.servidor_jellyfin import ErroJellyfin, atualizar_biblioteca, indice_da_biblioteca, testar_conexao
from jellyfin_tools.site_demo import iniciar_site_demo
from jellyfin_tools.vigia import filtro_prontos

from . import config
from .cli import salvar
from .extracao import LinkVideo
from .gui import ORIGENS, _SaidaParaFila, _so_caracteres_basicos
from . import atualizacao, bandeja, inicializacao
from .gui_moderna import JanelaCanais, JanelaEspelhos, JanelaModerna, OpcoesInterface
from .navegador import PERFIL_PADRAO, PlaywrightAusente
from .servico import MENSAGEM_ROBOTS, Trabalho, fazer_login

PASTA_PADRAO = os.path.abspath("videos_baixados")
TEXTOS_SITUACAO = {"ok": "baixado", "pulado": "pulado", "erro": "erro"}
# Status do organizador -> categoria do filtro "Mostrar" da tabela
CATEGORIA = {"simulado": "mover", "movido": "movido", "organizado": "organizado", "conflito": "conflito",
             "nao_identificado": "nao_identificado", "ignorado": "ignorado", "erro": "erro",
             "limpeza": "mover", "pasta_apagada": "movido"}
OK_LEGENDA = ("baixada", "ja_existe")
TIPOS_CONTEUDO = {"filme": "Filme", "serie": "Série", "outro": "—"}
# Espelho no Jellyfin: status do item -> (texto na coluna Situação, cor)
SITUACAO_ESPELHO = {"criado": ("espelhado", "ok"), "ja_existe": ("já espelhado", "ok"),
                    "tem_video": ("já na biblioteca", "ok"), "no_jellyfin": ("já no Jellyfin", "ok"), "ignorado": ("sem ano/episódio", "pulado"),
                    "sem_licenca": ("sem licença aberta", "pulado"), "nao_identificado": ("não identificado", "pulado"),
                    "link_ruim": ("link não serve", "erro"),
                    "erro": ("erro", "erro")}

# Chaves e tokens: só vão para o config.json se o usuário marcar "Lembrar as chaves".
SEGREDOS = ("chave_tmdb", "chave_opensubtitles", "chave_subdl", "jellyfin_api_key", "discord_webhook",
            "telegram_token")


class _LogParaFila(logging.Handler):
    """Manda as mensagens do log (que também vão para o arquivo) para o console da janela."""

    def __init__(self, fila: queue.Queue):
        super().__init__(logging.INFO)
        self.fila = fila
        self.setFormatter(logging.Formatter("%(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        self.fila.put(("log", self.format(record) + "\n"))

# Aba Jellyfin: status do organizador / da legenda -> (texto, cor da linha)
STATUS_MOVIMENTO = {"simulado": ("vai mover", None), "movido": ("movido", "ok"),
                    "organizado": ("já organizado", "ok"), "conflito": ("conflito", "pulado"),
                    "nao_identificado": ("não identificado", "pulado"), "ignorado": ("ignorado", None),
                    "erro": ("erro", "erro"),
                    "limpeza": ("vai apagar a pasta", None), "pasta_apagada": ("pasta apagada", "ok")}
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
        # Melhoria 4: log em arquivo (na pasta do usuário, junto das configurações) + console da janela
        self.arquivo_log = config.ARQUIVO.parent / "jellyfin_organizer.log"       # log geral (tudo)
        self.pasta_logs = config.ARQUIVO.parent / "logs"                          # um arquivo por ação
        self._log_acao = None
        self._log = configurar_log(self.arquivo_log, no_terminal=False)
        self._log.addHandler(_LogParaFila(self.fila))
        self._previa = None                     # "assinatura" das opções da última pré-visualização
        self._tmdb_ativo = False                # o TMDB estava marcado na última análise?
        self._sugestao_series = None            # prévia em Filmes com episódios: (episódios, total)
        self._remocao_pendente = None           # "Conferir espelhos": .strm quebrados a oferecer remoção
        self._vigia_agendada = None             # pasta vigiada: id do próximo after()
        self._conferencia_agendada = None       # conferência automática dos espelhos
        self.janela_espelhos = None             # "Espelhos...": remover qualquer espelhamento
        self._conflitos_pendentes = None        # "Resolver conflitos": decisões esperando a confirmação
        self._previa_pendente = False
        self._versao_pendente = None            # aviso de versão nova que chegou durante uma tarefa
        self._atualizacao_pendente = None       # .zip da versão nova baixado (pergunta no fim)
        self._instalar_ao_sair = None           # (zip, reabrir): troca os arquivos quando o programa fechar
        self._versao_agendada = None
        self._bandeja = None                    # ícone perto do relógio (quando escondida)
        self.janela_canais = None               # "TV ao vivo..."
        self._canais, self._situacao_canais = [], {}
        self._saindo = False
        self._espelhos_salvos = {}
        self._vigia_conferindo = False
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
        acao = status.rstrip(". ")
        self.iniciar_registro(acao)                  # cada ação com o seu registro no console
        encerrar_log_da_acao(self._log_acao)         # (segurança: a anterior já foi fechada no "fim")
        try:                                         # ... e o seu próprio arquivo de log
            self._log_acao, self._registros[-1]["arquivo"] = iniciar_log_da_acao(acao, self.pasta_logs)
        except OSError as erro:
            self._log_acao = None
            self._log.warning("Não consegui criar o log desta ação: %s", erro)
        self._log.info("===== %s =====", acao)       # e um separador no log geral

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
        """Lê a fila e atualiza a tela. Um erro numa mensagem vai para o log e o ciclo CONTINUA
        (antes, uma exceção aqui parava a fila e a janela ficava "trabalhando" para sempre)."""
        mensagens = []
        while True:
            try:
                mensagens.append(self.fila.get_nowait())
            except queue.Empty:
                break
        # Velocidade: linhas de log seguidas viram UMA escrita no console (antes eram centenas,
        # cada uma rolando a tela até o fim).
        # Avisos de progresso: só o ÚLTIMO de cada tipo (e de cada linha) importa neste ciclo.
        ultimo: dict = {}
        for posicao, (tipo, dado) in enumerate(mensagens):
            if tipo in ("jf_total", "jf_atual", "jf_analise"):
                ultimo[tipo] = posicao
            elif tipo == "jf_prog":
                ultimo[("jf_prog", dado[0])] = posicao
        manter = set(ultimo.values())
        agrupadas: list = []
        for posicao, (tipo, dado) in enumerate(mensagens):
            chave = ("jf_prog", dado[0]) if tipo == "jf_prog" else tipo
            if chave in ultimo and posicao not in manter:
                continue                             # substituído por um aviso mais novo
            if tipo == "log" and agrupadas and agrupadas[-1][0] == "log":
                agrupadas[-1] = ("log", agrupadas[-1][1] + dado)
            else:
                agrupadas.append((tipo, dado))
        for tipo, dado in agrupadas:
            try:
                self._tratar_mensagem(tipo, dado)
            except tk.TclError:          # a janela foi fechada no meio do processamento
                return
            except Exception:
                self._log.error("Erro interno ao atualizar a tela (%s):\n%s", tipo, traceback.format_exc())
                if tipo == "fim":        # mesmo com erro, libera os botões
                    self.trabalhando = False
                    self.definir_ocupado(False)
        self.after(100, self._processar_fila)

    def report_callback_exception(self, tipo, valor, rastro) -> None:
        """Erros em cliques/temporizadores do Tk: registra no log em vez de sumir."""
        self._log.error("Erro interno na janela:\n%s", "".join(traceback.format_exception(tipo, valor, rastro)))

    def _tratar_mensagem(self, tipo: str, dado) -> None:
        """Atualiza a tela conforme a mensagem que a thread de trabalho mandou."""
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
            self.mostrar_todos_jf()                    # lista nova: nada escondido por um filtro antigo
            for i, (atual, novo) in enumerate(dado):
                self.adicionar_linha_jf(str(i), i + 1, "na biblioteca", None, atual, novo)
        elif tipo == "jf_legenda":
            iid, resultado = dado
            self.atualizar_linha_jf(iid, *STATUS_LEGENDA.get(resultado.status, (resultado.status, None)))
        elif tipo == "jf_legendas":                    # vários idiomas: "pt-BR ✓ · en ✓ · es ✕"
            iid, por_idioma = dado
            texto = " · ".join(f"{idioma} {'✓' if st in OK_LEGENDA else '✕'}"
                                    for idioma, st in por_idioma.items())
            self.atualizar_linha_jf(iid, texto, None)
        elif tipo == "jf_limpar":
            self.limpar_tabela_jf()
        elif tipo == "jf_prog":
            iid, fracao, status = dado
            self.definir_progresso_linha_jf(iid, fracao)
            if fracao >= 1.0 and not status.startswith("_"):     # "_legenda": só o progresso
                self.atualizar_situacao_jf(iid, *STATUS_MOVIMENTO.get(status, (status, None)),
                                           categoria=CATEGORIA.get(status))
                if status == "erro":
                    self.definir_progresso_linha_jf(iid, None, "erro")
        elif tipo == "jf_atual":
            self._mostrar_detalhe(int(dado), "Agora")
        elif tipo == "jf_total":
            self.definir_progresso_total(*dado)
        elif tipo == "jf_analise":                      # pré-visualização: "45% · Analisando: 75 de 166"
            fracao, texto = dado
            self.definir_progresso_total(fracao, texto)
            self.definir_progresso_rodape(fracao, texto)
        elif tipo == "jf_tmdb_estado":
            self.definir_estado_tmdb(*dado)
        elif tipo == "legendas_estado":
            self.definir_estado_legendas(*dado)
        elif tipo == "status_fim":
            self._texto_fim = dado
        elif tipo == "espelho":                        # aba Vídeos: situação de cada link espelhado
            for i, (texto, cor) in dado:
                self.atualizar_situacao(str(i), texto, cor)
        elif tipo == "sugerir_series":
            self._sugestao_series = dado
        elif tipo == "vigia_resultado":
            self._vigia_organizar(*dado)
        elif tipo == "sugerir_remocao":
            self._remocao_pendente = dado
        elif tipo == "conferencia_feita":              # conferência automática dos espelhos
            quando, total, quebrados, removidos = dado
            self.var_jf_ultima_conferencia.set(quando)
            self._salvar_config()
            self.definir_estado_conferencia(
                f"{self._texto_ultima_conferencia()} {total} espelho(s), {quebrados} quebrado(s)"
                + (f", {removidos} removido(s)." if removidos else "."), not quebrados)
        elif tipo == "canais_importados":
            self._juntar_canais(dado)
        elif tipo == "canais_conferidos":
            self._situacao_canais.update({c.url: sit for c, sit in dado})
            self._mostrar_canais()
        elif tipo == "bandeja":                        # clique no ícone perto do relógio
            if dado == "abrir":
                self.mostrar_janela()
            elif dado == "sair":
                self.sair_de_vez()
        elif tipo == "versao_consultada":
            self._mostrar_versao_consultada(*dado)
        elif tipo == "atualizacao_baixada":
            self._atualizacao_pendente = dado              # pergunta depois do "fim"
        elif tipo == "versao_nova":
            if self.trabalhando:                       # não interrompe uma tarefa: avisa no fim
                self._versao_pendente = dado
            else:
                self._avisar_versao_nova(dado)
        elif tipo == "conflitos_decididos":
            self._conflitos_pendentes = dado               # pergunta depois do "fim" (a janela já está livre)
        elif tipo == "previa_de_novo":
            self._previa_pendente = True
        elif tipo == "espelhos_atualizar":             # janela "Espelhos...": relê a lista
            if self.janela_espelhos is not None and self.janela_espelhos.winfo_exists():
                self._preencher_espelhos()
        elif tipo == "jf_relatorio":                   # o que falta na biblioteca
            self.limpar_tabela_jf()
            self.mostrar_todos_jf()
            for i, (item, falta, detalhe) in enumerate(dado):
                self.adicionar_linha_jf(str(i), i + 1, f"falta {falta}", "pulado", item, detalhe)
        elif tipo == "jf_espelhos":                    # resultado do "Conferir espelhos"
            self.limpar_tabela_jf()
            self.mostrar_todos_jf()                    # "funcionando" não pode sumir num filtro da prévia
            for i, (nome, ok, texto) in enumerate(dado):
                self.adicionar_linha_jf(str(i), i + 1, "funcionando" if ok else "quebrado", "ok" if ok else "erro",
                                        nome, texto, categoria="organizado" if ok else "erro")
        elif tipo == "fim":
            self.trabalhando = False
            encerrar_log_da_acao(self._log_acao)       # o arquivo desta ação está completo
            self._log_acao = None
            self.definir_status(self._texto_fim or f"Pronto. {len(self.links)} vídeo(s) na lista.",
                                ocupado=False)
            self._texto_fim = None
            if self._sugestao_series:                  # só agora: a janela já está livre para outra prévia
                sugestao, self._sugestao_series = self._sugestao_series, None
                self.after(50, lambda: self._oferecer_series(*sugestao))
            if self._remocao_pendente:
                quebrados, self._remocao_pendente = self._remocao_pendente, None
                self.after(50, lambda: self._oferecer_remocao(quebrados))
            if self._conflitos_pendentes:
                pendentes, self._conflitos_pendentes = self._conflitos_pendentes, None
                self.after(50, lambda: self._confirmar_conflitos(*pendentes))
            if self._atualizacao_pendente:
                baixada, self._atualizacao_pendente = self._atualizacao_pendente, None
                self.after(50, lambda: self._atualizacao_baixada(*baixada))
            if self._versao_pendente:
                nova, self._versao_pendente = self._versao_pendente, None
                self.after(50, lambda: self._avisar_versao_nova(nova))
            if self._previa_pendente:
                self._previa_pendente = False
                self.after(50, self.ao_previsualizar)


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
            self.adicionar_video(str(i), i + 1, "", titulo, ORIGENS.get(l.tipo, l.tipo), l.url,
                                 TIPOS_CONTEUDO[classificar(l)], getattr(l, "licenca", "") or "—")

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

        self.definir_progresso_total(None)
        self._tmdb_ativo = o.tmdb

        def tarefa():
            self._log.info("Pré-visualizando (%s): %s -> %s", "séries" if o.modo == "series" else "filmes",
                           o.origem, o.destino)
            catalogo = self._catalogo(o)
            movimentos = organizar_pasta(o.origem, o.destino, catalogo, aplicar=False,
                                         incluir_tmdbid=o.incluir_tmdbid, exigir_catalogo=o.exigir_catalogo,
                                         modo=o.modo, limpar_lixo=o.limpar_lixo,
                                         apagar_pasta_origem=o.apagar_pasta_origem,
                                         nomes_episodios=o.nomes_episodios, protegidas=o.pastas_protegidas,
                                         regras=self.regras_de_nome(), ao_analisar=self._avisar_analise,
                                         parar=self.evento_parar.is_set)
            for m in movimentos:
                self._log.info("%s", m)
            if self.evento_parar.is_set():               # "Parar": mostra o que analisou, mas não libera o Organizar
                self.fila.put(("jf_movimentos", movimentos))
                self.fila.put(("status_fim", f"Pré-visualização parada: {len(movimentos)} arquivo(s) analisados. "
                                             "Pré-visualize de novo para organizar."))
                return
            quantos = sum(m.status == "simulado" for m in movimentos)
            prontos = sum(m.status == "organizado" for m in movimentos)
            sobras = sum(m.status == "limpeza" for m in movimentos)
            self.fila.put(("jf_movimentos", movimentos))
            self.fila.put(("jf_previa", (assinatura, quantos + sobras)))      # só limpeza também libera
            resumo_tmdb = self._resumo_tmdb(catalogo, movimentos) if o.tmdb else ""
            resumo_sobras = f" {sobras} pasta(s) que sobraram de antes para apagar." if sobras else ""
            self.fila.put(("status_fim", f"Pré-visualização: {quantos} para mover, {prontos} já organizado(s), "
                                         f"{len(movimentos) - quantos - prontos - sobras} com pendência."
                                         f"{resumo_sobras}{resumo_tmdb} Nada foi movido."))
            if not movimentos:
                self.fila.put(("msg", ("Nenhum vídeo", f"Não achei vídeos em:\n{o.origem}", "aviso")))
            episodios = [m for m in movimentos if m.detalhe.startswith(DETALHE_EPISODIO)]
            if o.modo == "filmes" and episodios and len(episodios) * 2 >= len(movimentos):
                series = {normalizar(ep.serie) for m in episodios if (ep := extrair_episodio(m.origem.name))}
                self.fila.put(("sugerir_series", (len(episodios), len(movimentos), series)))  # depois do "fim"

        self._rodar("Pré-visualizando...", tarefa)

    # ================================================================== espelhar no Jellyfin (.strm)
    def ao_espelhar_jellyfin(self) -> None:
        """Links da aba Vídeos -> .strm nas bibliotecas de Filmes e Séries da aba Jellyfin
        (+ legendas, pôster, .nfo e scan, como no Organizar). Selecionados; sem seleção, todos."""
        indices = [int(i) for i in self.tabela.selection()] or list(range(len(self.links)))
        if not indices:
            self.mostrar_mensagem("Espelhar no Jellyfin", "Busque os vídeos primeiro.", "aviso")
            return
        links = [self.links[i] for i in indices]
        o = self.obter_opcoes_jellyfin()
        self._destinos[self._modo_atual] = self.var_jf_destino.get()
        pasta_filmes, pasta_series = self._destinos.get("Filmes", ""), self._destinos.get("Séries", "")
        tipos = [classificar(l) for l in links]
        filmes, series = tipos.count("filme"), tipos.count("serie")
        faltam = [n for n, (qtd, pasta) in (("Filmes", (filmes, pasta_filmes)), ("Séries", (series, pasta_series)))
                  if qtd and not pasta]
        if faltam:
            self.mostrar_mensagem("Espelhar no Jellyfin", f"Escolha a biblioteca de {' e de '.join(faltam)} na aba "
                                  "Jellyfin (troque Filmes/Séries no topo dela) e tente de novo.", "aviso")
            return
        if not filmes + series:
            self.mostrar_mensagem("Espelhar no Jellyfin", "Nenhum link tem ano (filme) ou temporada/episódio "
                                  "(série) no título: não dá para nomear com segurança.", "aviso")
            return
        abertos = sum(licenca_aberta(getattr(l, "licenca", "")) for l, t in zip(links, tipos) if t != "outro")
        legendas = f"legendas ({o.idioma}) pela fonte \"{o.fonte_legenda}\"" if o.legendas else "sem legendas"
        escolha = self.escolher(
            "Espelhar no Jellyfin",
            f"{len(links)} link(s){' selecionado(s)' if self.tabela.selection() else ''}: {filmes} filme(s), "
            f"{series} episódio(s), {len(links) - filmes - series} sem ano/episódio (ficam de fora).\n\n"
            f"Filmes: {pasta_filmes or '—'}\nSéries: {pasta_series or '—'}\n\n"
            "Cada um vira um arquivo .strm com o link: o Jellyfin toca direto do site, sem baixar. Depois: "
            f"{legendas}, pôster/.nfo e scan do Jellyfin.\n\n"
            f"Licença: {abertos} com domínio público ou Creative Commons. Os demais podem ser cópias sem "
            "autorização do dono dos direitos; espelhe só o que você pode assistir legalmente.",
            self.OPCOES_ESPELHO)
        if escolha is None:
            return
        so_abertos = escolha == self.OPCOES_ESPELHO[0]
        self._salvar_config()

        def tarefa():
            # 1) cada link serve para .strm? (direto, permanente, público) - vários ao mesmo tempo
            candidatos = [l.url for l, t in zip(links, tipos) if t != "outro"
                          and (not so_abertos or licenca_aberta(getattr(l, "licenca", "")))]
            self._log.info("Conferindo %d link(s) (direto, permanente, público?)", len(candidatos))
            verificacoes = verificar_links(candidatos, parar=self.evento_parar.is_set,
                                           ao_progresso=self._progresso_com_velocidade("Conferindo links"))
            if self.evento_parar.is_set():             # "Parar": não cria nenhum .strm pela metade
                self.fila.put(("status_fim", f"Espelhar parado: {len(verificacoes)} de {len(candidatos)} links "
                                             "conferidos, nada foi criado."))
                return
            tempos = [v.tempo for v in verificacoes.values() if v.ok and v.tempo is not None]
            if tempos:
                self._log.info("Tempo de resposta dos servidores: médio %.1f s, mais lento %.1f s",
                               sum(tempos) / len(tempos), max(tempos))
            # 2) o que o Jellyfin JÁ tem (se o endereço e a chave estiverem preenchidos): não duplica
            indice = None
            if o.jellyfin_url and o.jellyfin_api_key:
                try:
                    indice = indice_da_biblioteca(o.jellyfin_url, o.jellyfin_api_key)
                except ErroJellyfin as erro:
                    self._log.warning("Não consegui consultar o Jellyfin (%s); sigo sem essa conferência", erro)
            # 3) nomes e 4) .strm
            itens = planejar_espelho(links, pasta_filmes, pasta_series, self._catalogo(o), so_abertos,
                                     o.incluir_tmdbid, o.nomes_episodios, verificacoes, indice)
            aplicar_espelho(itens)
            for item in itens:
                destino = f" -> {item.destino}" if item.destino else ""
                nivel = self._log.error if item.status == "erro" else self._log.info
                nivel("[%s] %s%s%s", item.status, nome_do_link(item.link), destino,
                      f" ({item.detalhe})" if item.detalhe else "")
            self.fila.put(("espelho", [(i, SITUACAO_ESPELHO.get(item.status, (item.status, None)))
                                       for i, item in zip(indices, itens)]))
            criados = [item for item in itens if item.status == "criado"]
            resultados = []
            if criados:
                self._log.info("Legendas, pôster/.nfo e scan para %d item(ns) espelhado(s)", len(criados))
                resultados = self._pos_processar(o, [item.como_item_da_biblioteca() for item in criados],
                                                 [f"espelho-{k}" for k in range(len(criados))], "Espelho",
                                                 legendas=o.legendas, notificar=True)
            baixadas = sum(1 for r in resultados for le in (r.legendas or {"": r.legenda}).values()
                           if le and le.status == "baixada")
            contagem = {s: sum(item.status == s for item in itens) for s in SITUACAO_ESPELHO}
            self.fila.put(("status_fim", f"Espelho: {len(criados)} .strm criado(s), {baixadas} legenda(s)."))
            self.fila.put(("msg", ("Espelho no Jellyfin",
                                   f"Criados: {len(criados)} ({sum(i.tipo == 'filme' for i in criados)} filme(s), "
                                   f"{sum(i.tipo == 'serie' for i in criados)} episódio(s))\n"
                                   f"Já existiam: {contagem['ja_existe'] + contagem['tem_video']}\n"
                                   f"Já estavam no Jellyfin (pulados): {contagem['no_jellyfin']}\n"
                                   f"Sem ano/episódio: {contagem['ignorado']}\n"
                                   f"Sem licença aberta (pulados): {contagem['sem_licenca']}\n"
                                   f"Link que não serve para .strm (página, temporário, login, fora do ar): "
                                   f"{contagem['link_ruim']}\n"
                                   + (f"Resposta dos servidores: média {sum(tempos) / len(tempos):.1f} s\n"
                                      if tempos else "") +
                                   f"Não identificados: {contagem['nao_identificado']}\nCom erro: {contagem['erro']}\n"
                                   f"Legendas baixadas: {baixadas}\n\nDetalhes em 'Abrir log' (aba Jellyfin).",
                                   "erro" if contagem["erro"] else "sucesso")))

        self._rodar("Espelhando no Jellyfin...", tarefa)

    OPCOES_ESPELHO = ("Só domínio público / CC", "Todos os identificados")

    # ================================================================== pasta vigiada
    def ao_alternar_vigia(self) -> None:
        """Liga/desliga a vigia: a cada N minutos confere a pasta de origem e organiza (sem perguntar)
        só o que terminou de baixar. A janela fica livre entre uma conferência e outra."""
        if self._vigia_agendada:
            self.after_cancel(self._vigia_agendada)
            self._vigia_agendada = None
        if not self.var_jf_vigiar.get():
            self.definir_estado_vigia("Desligada.", False)
            self._log.info("Vigia desligada")
            return
        self._log.info("Vigia ligada: conferindo %s a cada %s min", self.var_jf_origem.get(),
                       int(self.campo_vigia_min.get()))
        self._ciclo_vigia()

    def _agendar_vigia(self) -> None:
        minutos = self.campo_vigia_min.get()
        self._vigia_agendada = self.after(int(minutos * 60_000), self._ciclo_vigia)
        proxima = datetime.now() + timedelta(minutes=minutos)
        self.definir_estado_vigia(f"Ligada: próxima conferência às {proxima:%H:%M}.", True)

    def _alvos_da_vigia(self, o):
        """(pastas vigiadas, biblioteca de Filmes, biblioteca de Séries). Sem lista, vigia a pasta de origem."""
        self._destinos[self._modo_atual] = self.var_jf_destino.get()
        pastas = [p for p in (o.pastas_vigiadas or (o.origem,))
                  if p and Path(p).is_dir() and not problema_no_caminho(p)]
        filmes, series = (self._destinos.get(t) or None for t in ("Filmes", "Séries"))
        return pastas, filmes, series

    def _ciclo_vigia(self) -> None:
        self._agendar_vigia()                        # a próxima já fica marcada, aconteça o que acontecer
        if self.trabalhando or self._vigia_conferindo:
            return                                   # outra tarefa rodando: confere na próxima
        o = self.obter_opcoes_jellyfin()
        pastas, filmes, series = self._alvos_da_vigia(o)
        if not pastas or not (filmes or series):
            self._log.warning("Vigia: escolha as pastas vigiadas (ou a de origem) e as bibliotecas de Filmes/Séries")
            return
        self._vigia_conferindo = True

        def conferir():                              # na thread: a janela não trava
            novos = 0
            for pasta in pastas:
                try:
                    previa = organizar_misto(pasta, filmes, series, CatalogoLocal.padrao(), filtro=filtro_prontos(),
                                             protegidas=o.pastas_protegidas, regras=self.regras_de_nome())
                    novos += sum(m.status == "simulado" for m in previa)
                except Exception as erro:
                    self._log.error("Vigia: não consegui olhar %s: %s", pasta, erro)
            self.fila.put(("vigia_resultado", (novos, o)))

        threading.Thread(target=conferir, daemon=True).start()

    def _vigia_organizar(self, novos: int, o) -> None:
        self._vigia_conferindo = False
        if not novos or self.trabalhando:
            return
        if o.legendas and self._problema_legendas(o):
            o.legendas = False                       # sem caixa de mensagem: segue sem legendas
            self._log.warning("Vigia: legendas desligadas nesta rodada (%s)", self._problema_legendas(o))
        pastas, filmes, series = self._alvos_da_vigia(o)
        self._log.info("Vigia: %d arquivo(s) terminaram de baixar; organizando (filmes -> %s, séries -> %s)",
                       novos, filmes or "—", series or "—")
        self._tmdb_ativo = o.tmdb
        self._previa = None
        self.liberar_organizar(False)

        def tarefa():
            todos = []
            for pasta in pastas:
                todos += organizar_misto(pasta, filmes, series, self._catalogo(o), filtro=filtro_prontos(),
                                         aplicar=True, incluir_tmdbid=o.incluir_tmdbid,
                                         exigir_catalogo=o.exigir_catalogo, limpar_lixo=o.limpar_lixo,
                                         apagar_pasta_origem=o.apagar_pasta_origem, nomes_episodios=o.nomes_episodios,
                                         protegidas=o.pastas_protegidas, regras=self.regras_de_nome())
            for m in todos:
                nivel = {"erro": self._log.error, "movido": self._log.info}.get(m.status, self._log.warning)
                nivel("%s", m)
            self.fila.put(("jf_movimentos", todos))
            movidos = [(i, m) for i, m in enumerate(todos) if m.status == "movido"]
            if movidos:                              # legendas, pôster, .nfo, avisos e scan (como no Organizar)
                self._pos_processar(o, [(m, m.destino.stem) for _, m in movidos], [i for i, _ in movidos],
                                    "Vigia", legendas=o.legendas, notificar=True)
            filmes_movidos = sum(1 for _, m in movidos if not m.episodio)
            self.fila.put(("status_fim", f"Vigia: {filmes_movidos} filme(s) e {len(movidos) - filmes_movidos} "
                                         "episódio(s) organizados."))

        self._rodar("Organizando (pasta vigiada)...", tarefa)

    # ================================================================== conferência automática dos espelhos
    def ao_alternar_conferencia(self) -> None:
        if self.var_jf_conferir_auto.get():
            self._log.info("Conferência automática dos espelhos ligada (a cada %s %s)",
                           int(self.campo_conferir_a_cada.get()), self.var_jf_conferir_unidade.get())
            self._verificar_conferencia()
        else:
            self.definir_estado_conferencia(self._texto_ultima_conferencia() + " Automático desligado.")

    def _ciclo_conferencia(self) -> None:
        """Roda a cada minuto; só confere quando já passou o período escolhido (minutos, horas ou dias)."""
        self._conferencia_agendada = self.after(60_000, self._ciclo_conferencia)
        self._verificar_conferencia()

    def _texto_ultima_conferencia(self) -> str:
        ultima = self.var_jf_ultima_conferencia.get()
        try:
            return f"Última conferência: {datetime.fromisoformat(ultima):%d/%m %H:%M}."
        except ValueError:
            return "Última conferência: nunca."

    def _verificar_conferencia(self) -> None:
        if not self.var_jf_conferir_auto.get() or self.trabalhando:
            return
        o = self.obter_opcoes_jellyfin()
        intervalo = intervalo_em_segundos(o.conferir_a_cada, o.conferir_unidade)
        try:
            ultima = datetime.fromisoformat(o.ultima_conferencia)
        except ValueError:
            ultima = None
        if ultima is not None and (datetime.now() - ultima).total_seconds() < intervalo:
            proxima = ultima + timedelta(seconds=intervalo)
            self.definir_estado_conferencia(f"{self._texto_ultima_conferencia()} Próxima: {proxima:%d/%m %H:%M}.")
            return
        self._destinos[self._modo_atual] = self.var_jf_destino.get()
        pastas = [p for p in dict.fromkeys((self._destinos.get("Filmes"), self._destinos.get("Séries")))
                  if p and Path(p).is_dir()]
        canais = carregar_canais(self.arquivo_canais)
        if not pastas and not canais:
            self._log.warning("Conferência automática: escolha as bibliotecas de Filmes/Séries")
            return
        notificador = Notificador(o.discord_webhook, o.telegram_token, o.telegram_chat_id)

        def tarefa():
            resultado, quebrados, removidos = [], [], 0
            if pastas:
                resultado, quebrados, removidos = conferir_e_avisar(
                    *pastas, notificador=notificador, remover=o.remover_quebrados, parar=self.evento_parar.is_set,
                    ao_progresso=self._progresso_com_velocidade("Conferindo espelhos"))
            linhas = []
            for raiz, arquivo, url, v in resultado:
                texto = v.problema or v.aviso or "funcionando"
                (self._log.info if v.ok else self._log.warning)("[%s] %s (%s)", "ok" if v.ok else "quebrado",
                                                                 arquivo, texto)
                linhas.append(("/".join(arquivo.relative_to(raiz).parts), v.ok, texto))
            fora = []
            if canais:                                 # canais ao vivo: avisa se algum saiu do ar
                situacoes = conferir_canais(canais, parar=self.evento_parar.is_set,
                                            ao_progresso=self._progresso_com_velocidade("Conferindo canais ao vivo"))
                fora = [(c, s) for c, s in situacoes if not s.ok]
                for c, s in situacoes:
                    (self._log.info if s.ok else self._log.warning)("[canal %s] %s (%s)", "ok" if s.ok else "fora do ar",
                                                                     c.nome, s.detalhe)
                    linhas.append((f"TV ao vivo/{c.nome}", s.ok, s.detalhe))
                if fora and notificador.ativo:
                    notificador.enviar(*mensagem_fora_do_ar(fora))
            if linhas:
                self.fila.put(("jf_espelhos", linhas))
            if (quebrados or fora) and not notificador.ativo:
                self._log.warning("Há espelhos/canais com problema, mas o Discord/Telegram não está configurado")
            self.fila.put(("conferencia_feita", (datetime.now().isoformat(timespec="seconds"), len(resultado) + len(canais),
                                                 len(quebrados) + len(fora), removidos)))
            self.fila.put(("status_fim", f"Espelhos: {len(resultado) - len(quebrados)} funcionando, "
                                         f"{len(quebrados)} quebrado(s)" + (f", {removidos} removido(s)" if removidos
                                                                           else "")
                                         + (f". Canais: {len(canais) - len(fora)} no ar, {len(fora)} fora." if canais
                                            else ".")))

        self._rodar("Conferindo espelhos (automático)...", tarefa)

    # ================================================================== relatório da biblioteca
    def ao_relatorio(self) -> None:
        """O que falta nas bibliotecas: legendas (cada idioma), pôsteres, episódios. Gera um .csv."""
        self._destinos[self._modo_atual] = self.var_jf_destino.get()
        filmes, series = (self._destinos.get(t) or None for t in ("Filmes", "Séries"))
        if not any(p and Path(p).is_dir() for p in (filmes, series)):
            self.mostrar_mensagem("Relatório", "Escolha a biblioteca de Filmes e/ou de Séries.", "aviso")
            return
        o = self.obter_opcoes_jellyfin()
        idiomas = normalizar_idiomas(o.idioma) or ["pt-BR"]
        self._previa = None
        self.liberar_organizar(False)

        def tarefa():
            catalogo = self._catalogo(o) if o.tmdb else None      # com o TMDB: confere o fim das temporadas
            pendencias = gerar_relatorio(filmes, series, idiomas, catalogo, parar=self.evento_parar.is_set)
            for p in pendencias:
                self._log.info("[falta %s] %s: %s", p.falta, p.item, p.detalhe)
            arquivo = salvar_csv(pendencias, config.ARQUIVO.parent / "relatorios")
            texto = resumo(pendencias)
            self._log.info("Relatório: %s. Planilha: %s", texto, arquivo)
            self.fila.put(("jf_relatorio", [(p.item, p.falta, p.detalhe) for p in pendencias]))
            self.fila.put(("status_fim", f"Relatório: {len(pendencias)} pendência(s)."))
            self.fila.put(("msg", ("Relatório da biblioteca",
                                   f"{texto.replace('; ', chr(10))}\n\nA lista completa está na tabela e na "
                                   f"planilha (botão \"Abrir relatório\", em cima da lista):\n{arquivo}"
                                   + ("" if o.tmdb else "\n\nCom o TMDB marcado, o "
                                   "relatório também confere o fim das temporadas e temporadas inteiras."),
                                   "info" if pendencias else "sucesso")))

        self._rodar("Gerando o relatório...", tarefa)

    def ao_conferir_espelhos(self) -> None:
        """Confere o link de cada .strm das bibliotecas de Filmes e Séries (o site ainda tem o vídeo?)."""
        self._destinos[self._modo_atual] = self.var_jf_destino.get()
        pastas = [p for p in dict.fromkeys((self._destinos.get("Filmes"), self._destinos.get("Séries")))
                  if p and Path(p).is_dir()]
        if not pastas:
            self.mostrar_mensagem("Conferir espelhos", "Escolha a biblioteca de Filmes e/ou de Séries.", "aviso")
            return
        self._previa = None
        self.liberar_organizar(False)

        def tarefa():
            resultado = conferir_espelhos(*pastas, parar=self.evento_parar.is_set,
                                          ao_progresso=self._progresso_com_velocidade("Conferindo espelhos"))
            if not resultado:
                self.fila.put(("msg", ("Conferir espelhos", "Nenhum .strm nas bibliotecas:\n" + "\n".join(pastas),
                                       "info")))
                return
            linhas = []
            for raiz, arquivo, url, v in resultado:
                texto = v.problema or v.aviso or (f"funcionando ({v.tempo:.1f} s)" if v.tempo is not None
                                                  else "funcionando")
                (self._log.info if v.ok else self._log.warning)("[%s] %s -> %s (%s)", "ok" if v.ok else "quebrado",
                                                                 arquivo, url, texto)
                linhas.append(("/".join(arquivo.relative_to(raiz).parts), v.ok, texto))
            self.fila.put(("jf_espelhos", linhas))
            quebrados = [r for r in resultado if not r[3].ok]
            self.fila.put(("status_fim", f"Espelhos: {len(resultado) - len(quebrados)} funcionando, "
                                         f"{len(quebrados)} quebrado(s)."))
            if quebrados:
                self.fila.put(("sugerir_remocao", quebrados))      # pergunta depois do "fim"

        self._rodar("Conferindo espelhos...", tarefa)

    # ================================================================== "Espelhos...": remover qualquer um
    def _bibliotecas(self) -> dict[str, str]:
        """{pasta: "Filmes"/"Séries"} das bibliotecas escolhidas que existem."""
        self._destinos[self._modo_atual] = self.var_jf_destino.get()
        pastas = {}
        for tipo in ("Filmes", "Séries"):
            pasta = self._destinos.get(tipo)
            if pasta and Path(pasta).is_dir():
                pastas.setdefault(pasta, tipo)
        return pastas

    def ao_gerenciar_espelhos(self) -> None:
        if not self._bibliotecas():
            self.mostrar_mensagem("Espelhos", "Escolha a biblioteca de Filmes e/ou de Séries.", "aviso")
            return
        if self.janela_espelhos is None or not self.janela_espelhos.winfo_exists():
            self.janela_espelhos = JanelaEspelhos(self, self._remover_espelhos_escolhidos,
                                                  self._desfazer_remocao_espelhos)
        self._preencher_espelhos()
        self.janela_espelhos.lift()
        self.janela_espelhos.focus_force()

    def _preencher_espelhos(self) -> None:
        bibliotecas = self._bibliotecas()
        tipos = {Path(p).resolve(): t for p, t in bibliotecas.items()}
        self._espelhos_salvos, grupos = {}, []
        for lote in lotes_de_espelhos(*bibliotecas):
            linhas = []
            for espelho in lote.itens:
                iid = f"e{len(self._espelhos_salvos)}"
                self._espelhos_salvos[iid] = espelho
                linhas.append((iid, espelho.nome, tipos.get(espelho.raiz.resolve(), espelho.raiz.name), espelho.url))
            grupos.append((lote.titulo, linhas))
        self.janela_espelhos.preencher(grupos)

    def _scan_se_ligado(self, o) -> None:
        if o.atualizar_jellyfin and o.jellyfin_url and o.jellyfin_api_key:
            try:
                atualizar_biblioteca(o.jellyfin_url, o.jellyfin_api_key)
            except ErroJellyfin as erro:
                self._log.warning("Scan do Jellyfin não disparado: %s", erro)

    def _remover_espelhos_escolhidos(self, iids: list[str]) -> None:
        if self.trabalhando:
            return
        escolhidos = [self._espelhos_salvos[i] for i in iids if i in self._espelhos_salvos]
        if not escolhidos:
            self.mostrar_mensagem("Nada selecionado", "Clique num espelhamento (todos os itens dele) ou nos "
                                  "filmes/episódios (Ctrl+clique para vários) e tente de novo.", "aviso")
            return
        nomes = "\n".join(f"• {e.nome}" for e in escolhidos[:8])
        if len(escolhidos) > 8:
            nomes += f"\n… e mais {len(escolhidos) - 8}"
        if not self.perguntar("Remover espelhos",
                              f"Tirar {len(escolhidos)} espelho(s) da biblioteca?\n\n{nomes}\n\n"
                              "Saem junto a legenda, a miniatura e o .nfo de mesmo nome (e a pasta do filme ou da "
                              "série, se ficar sem nenhum vídeo). Vídeos baixados não são tocados.\n"
                              "\"Desfazer última remoção\" põe tudo de volta."):
            return
        o = self.obter_opcoes_jellyfin()

        def tarefa():
            total, mensagens = remover_espelhos_escolhidos(escolhidos)
            for m in mensagens:
                (self._log.warning if m.startswith("erro") else self._log.info)("%s", m)
            self._log.info("%d espelho(s) tirado(s) da biblioteca (guardados em .organizador/removidos)", total)
            if total:
                self._scan_se_ligado(o)
            self.fila.put(("status_fim", f"{total} espelho(s) removido(s). \"Desfazer última remoção\" põe de volta."))
            self.fila.put(("espelhos_atualizar", None))

        self._rodar("Removendo espelhos escolhidos...", tarefa)

    def _desfazer_remocao_espelhos(self) -> None:
        if self.trabalhando:
            return
        pastas = list(self._bibliotecas())
        o = self.obter_opcoes_jellyfin()

        def tarefa():
            mensagens = desfazer_ultima_remocao(*pastas)
            if not mensagens:
                self.fila.put(("msg", ("Desfazer", "Não há remoção de espelhos para desfazer (ou depois dela "
                                       "veio outra ação na biblioteca: use \"Desfazer última\").", "info")))
                return
            for m in mensagens:
                self._log.info("%s", m)
            voltaram = sum(m.startswith("voltou") for m in mensagens)
            self._scan_se_ligado(o)
            self.fila.put(("status_fim", f"Remoção desfeita: {voltaram} item(ns) voltaram."))
            self.fila.put(("espelhos_atualizar", None))

        self._rodar("Desfazendo a remoção de espelhos...", tarefa)

    def _oferecer_remocao(self, quebrados: list) -> None:
        if not self.perguntar("Espelhos quebrados",
                              f"{len(quebrados)} .strm não funcionam mais (veja a tabela).\n\n"
                              "Remover da biblioteca? O Jellyfin deixa de mostrar esses itens no próximo scan.\n"
                              "Se mudar de ideia, 'Desfazer última' os coloca de volta."):
            return

        def tarefa():
            removidos = remover_espelhos(quebrados)
            self._log.info("%d espelho(s) quebrado(s) removido(s)", removidos)
            self.fila.put(("status_fim", f"{removidos} espelho(s) quebrado(s) removido(s)."))
            self.fila.put(("msg", ("Espelhos quebrados", f"{removidos} .strm removido(s).", "sucesso")))

        self._rodar("Removendo espelhos quebrados...", tarefa)

    def _oferecer_series(self, episodios: int, total: int, series: set[str] = frozenset()) -> None:
        """Prévia no modo Filmes com (quase) só episódios: oferece trocar para Séries e refazer."""
        destino_atual = self.var_jf_destino.get()
        destino_series = self._destinos.get("Séries") or destino_atual
        aviso_pasta = ""
        if destino_series and normalizar(Path(destino_series).name) in series:
            # "...\Animes\Samurai X" é a pasta DA série; a biblioteca é a de cima ("...\Animes"),
            # senão ficaria "Samurai X\Samurai X\Season 01".
            aviso_pasta = (f"\n(\"{Path(destino_series).name}\" é a pasta da própria série: a biblioteca "
                           "passa a ser a pasta de cima, e a série fica numa pasta dentro dela.)")
            destino_series = str(Path(destino_series).parent)
        if not self.perguntar("Parece série",
                              f"{episodios} de {total} arquivo(s) parecem episódios de série: temporada e episódio "
                              "no nome (ex.: S05E19) ou numeração contínua de anime (ex.: \"Samurai X - 01\").\n"
                              "O modo Filmes procura título + ano de filme, por isso ficaram como não "
                              "identificados.\n\n"
                              f"Trocar para o modo Séries e pré-visualizar de novo?\n"
                              f"Biblioteca de Séries: {destino_series}{aviso_pasta}"):
            return
        self.seletor_modo.set("Séries")
        self._ao_trocar_modo("Séries")
        if not self.var_jf_destino.get() or aviso_pasta:
            self.var_jf_destino.set(destino_series)
        self.ao_previsualizar()

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
        pastas = [m.pasta_apagar for m in self._movimentos_previa if m.pasta_apagar]
        if pastas:
            aviso_lixo += (f"\n\n{len(pastas)} pasta(s) de torrent serão APAGADAS inteiras, com o que sobrar "
                           "nelas (amostras, prints, .nfo de release...). Isso não tem como desfazer.")
        ocultos = self.linhas_ocultas_jf("mover")
        if ocultos:
            aviso_lixo += f"\n\nAtenção: {ocultos} deles estão escondidos pelo filtro \"Mostrar\" e também serão movidos."
        substituir = ("\n\n\"Substituir o que já existe\" está marcado: legendas, pôster, backdrop e .nfo "
                      "dos itens movidos serão baixados de novo e trocados." if o.sobrescrever else "")
        if not self.perguntar("Organizar", f"Mover {quantos} arquivo(s) para:\n{o.destino}\n\n"
                              "Nenhum vídeo é sobrescrito, e você pode voltar atrás com 'Desfazer última'."
                              + substituir + aviso_lixo):
            return
        self._salvar_config()
        self._previa = None
        self.liberar_organizar(False)
        self._tmdb_ativo = o.tmdb

        self._rodar("Organizando...", self._tarefa_organizar(o))

    def _tarefa_organizar(self, o, filtro=None, automatico: bool = False):
        """O trabalho do Organizar, sem perguntas (roda na thread). Usado pelo botão e pela pasta
        vigiada (filtro = só o que terminou de baixar; automatico = sem caixa de mensagem no fim)."""
        def tarefa():
            self._log.info("Organizando: %s -> %s", o.origem, o.destino)
            etapas = 2                       # 1: mover   2: legendas/metadados/avisos/scan
            andamento = {"total": 0, "feitos": 0, "ultimo": {}}

            def ao_planejar(movimentos):
                andamento["total"] = sum(m.status == "simulado" for m in movimentos) or 1
                self.fila.put(("jf_movimentos", movimentos))
                self.fila.put(("jf_total", (0.0, f"Etapa 1/{etapas} – movendo: 0 de {andamento['total']}")))

            def ao_progresso(i, m, fracao):
                # avisa a janela só quando a porcentagem muda (milhares de avisos travariam a tela)
                pct = int(fracao * 100)
                if andamento["ultimo"].get(i) == pct and fracao not in (0.0, 1.0):
                    return
                andamento["ultimo"][i] = pct
                if fracao == 0.0:
                    self.fila.put(("jf_atual", i))
                if fracao >= 1.0:
                    andamento["feitos"] += 1
                    nivel = {"erro": self._log.error, "movido": self._log.info}.get(m.status, self._log.warning)
                    nivel("%s", m)
                self.fila.put(("jf_prog", (str(i), fracao, m.status if fracao >= 1.0 else "simulado")))
                feitos, total = andamento["feitos"], andamento["total"]
                geral = (feitos + (0 if fracao >= 1.0 else fracao)) / total
                self.fila.put(("jf_total", (geral, f"Etapa 1/{etapas} – movendo: {feitos} de {total} "
                                                   f"({int(geral * 100)}%)")))

            movimentos = organizar_pasta(o.origem, o.destino, self._catalogo(o), aplicar=True,
                                         incluir_tmdbid=o.incluir_tmdbid, exigir_catalogo=o.exigir_catalogo,
                                         modo=o.modo, limpar_lixo=o.limpar_lixo,
                                         apagar_pasta_origem=o.apagar_pasta_origem,
                                         nomes_episodios=o.nomes_episodios, filtro=filtro, parar=self.evento_parar.is_set,
                                         protegidas=o.pastas_protegidas, regras=self.regras_de_nome(),
                                         ao_planejar=ao_planejar, ao_progresso=ao_progresso,
                                         ao_analisar=self._avisar_analise)
            movidos = [(i, m) for i, m in enumerate(movimentos) if m.status == "movido"]
            resultados = []
            if movidos:
                self._log.info("Etapa 2/%d: legendas, pôster, .nfo, avisos e scan do Jellyfin", etapas)
                resultados = self._pos_processar(o, [(m, m.destino.stem) for _, m in movidos],
                                                 [i for i, _ in movidos], f"Etapa 2/{etapas}",
                                                 legendas=o.legendas, notificar=True)
            legendas = sum(1 for r in resultados if r.legenda and r.legenda.status == "baixada")
            metadados = sum(1 for r in resultados if r.metadados and r.metadados.criados)
            for i, m in enumerate(movimentos):                 # sobras de antes: "pasta apagada" ou erro
                if m.pasta_apagar and m.status in ("pasta_apagada", "erro") and not m.destino:
                    self.fila.put(("jf_prog", (str(i), 1.0, m.status)))
            erros = sum(m.status == "erro" for m in movimentos)
            pastas_apagadas = sum(1 for m in movimentos if m.pasta_apagar and not m.pasta_apagar.exists())
            self.fila.put(("jf_total", (1.0, f"Concluído: {len(movidos)} movido(s), {legendas} legenda(s), "
                                             f"{metadados} com pôster/.nfo, {erros} erro(s)")))
            self.fila.put(("status_fim", f"Organizado: {len(movidos)} movido(s), {legendas} legenda(s)."))
            if automatico:                       # pasta vigiada: ninguém para clicar em OK
                return
            self.fila.put(("msg", ("Organização concluída",
                                   f"Movidos: {len(movidos)}\nLegendas baixadas: {legendas}\n"
                                   f"Pôster/backdrop/.nfo: {metadados}\nCom erro: {erros}\n"
                                   + (f"Pastas de torrent apagadas: {pastas_apagadas}\n" if pastas_apagadas else "")
                                   + "\n"
                                   "Para voltar atrás, use 'Desfazer última'.\nDetalhes em 'Abrir log'.",
                                   "erro" if erros else "sucesso")))

        return tarefa

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
        escolha = self.escolher(
            "Completar biblioteca",
            f"Procurar o que falta em:\n{o.destino}\n\n"
            "• Só o que falta: baixa legenda, pôster, backdrop e .nfo apenas onde ainda não existem.\n"
            "• Substituir o que já existe: baixa de novo e TROCA os que já estão lá "
            "(ex.: legenda fora de sincronia, pôster em inglês). Os vídeos não são mexidos.",
            self.OPCOES_COMPLETAR if not o.sobrescrever else self.OPCOES_COMPLETAR[::-1])
        if escolha is None:
            return
        o.sobrescrever = escolha == self.OPCOES_COMPLETAR[1]
        self.var_jf_sobrescrever.set(o.sobrescrever)          # a caixa acompanha a escolha
        self._salvar_config()
        self._previa = None
        self.liberar_organizar(False)
        self._completar(o, Path(o.destino))

    OPCOES_COMPLETAR = ("Só o que falta", "Substituir o que já existe")

    def _completar(self, o, destino: Path) -> None:
        """Itens JÁ organizados: o mesmo pós-processamento do Organizar (legendas em cada idioma,
        pôster/backdrop/.nfo nos filmes e um scan do Jellyfin no fim), só que sem mover e sem avisos."""
        def tarefa():
            if o.modo == "filmes":
                itens = itens_da_biblioteca(destino, self._log)
            else:
                itens = itens_de_series(destino, self._catalogo(o), self._log)
            if o.pastas_protegidas:                  # Sonarr/Radarr cuidam dessas: nem legenda o programa põe
                itens = [(m, nome) for m, nome in itens if not protegido(m.destino, o.pastas_protegidas)]
            if o.modo == "filmes":
                linhas = [nome for _, nome in itens]
            else:
                linhas = ["/".join(m.destino.relative_to(destino).parts) for m, _ in itens]
            idiomas = normalizar_idiomas(o.idioma) or ["pt-BR"]
            sufixo = f".{idiomas[0]}.srt" + (f"  (+{', '.join(idiomas[1:])})" if len(idiomas) > 1 else "")
            self.fila.put(("jf_alvos", [(atual, f"{nome}{sufixo}") for atual, (_, nome) in zip(linhas, itens)]))
            tipo = "filme(s)" if o.modo == "filmes" else "episódio(s)"
            self._log.info("Completar biblioteca: %d %s em %s", len(itens), tipo, destino)
            resultados = self._pos_processar(o, itens, list(range(len(itens))), "Completando",
                                             legendas=True, notificar=False)
            baixadas = sum(1 for r in resultados for le in (r.legendas or {"": r.legenda}).values()
                           if le and le.status == "baixada")
            metadados = sum(1 for r in resultados if r.metadados and r.metadados.criados)
            extra = f", {metadados} com pôster/.nfo" if o.modo == "filmes" else ""
            self.fila.put(("jf_total", (1.0, f"Concluído: {baixadas} legenda(s){extra}")))
            self.fila.put(("status_fim", f"Biblioteca completada: {len(itens)} {tipo}, {baixadas} legenda(s) "
                                         f"baixada(s){extra}."))

        self._rodar("Completando a biblioteca...", tarefa)

    def _pos_processar(self, o, itens: list, iids: list[int], etapa: str, legendas: bool, notificar: bool):
        """Monta o ConfigPos com as opções da tela e roda o pós-processamento (na thread de trabalho)."""
        tmdb = ClienteTMDB(o.chave_tmdb) if o.chave_tmdb and (o.imagens_tmdb or o.gerar_nfo) else None
        if tmdb is None and (o.imagens_tmdb or o.gerar_nfo):
            self._log.info("Sem chave do TMDB: pôster, backdrop e .nfo não serão baixados")
        total = len(itens) or 1
        self.fila.put(("jf_total", (0.0, f"{etapa} – legendas e metadados: 0 de {len(itens)}")))

        def ao_item(k, resultado):
            iid = str(iids[k])
            if len(resultado.legendas) > 1:
                self.fila.put(("jf_legendas", (iid, {k: r.status for k, r in resultado.legendas.items()})))
            elif resultado.legenda:
                self.fila.put(("jf_legenda", (iid, resultado.legenda)))
            self.fila.put(("jf_prog", (iid, 1.0, "_pos")))
            self.fila.put(("jf_total", ((k + 1) / total, f"{etapa} – legendas e metadados: {k + 1} de "
                                                         f"{len(itens)} ({(k + 1) * 100 // total}%)")))

        with contextlib.ExitStack() as pilha:
            provedores = pilha.enter_context(self._provedores(o)) if legendas else []
            cfg = ConfigPos(provedores=provedores, idioma=o.idioma, tmdb=tmdb, imagens=o.imagens_tmdb,
                            nfo=o.gerar_nfo, notificar=notificar, sobrescrever=o.sobrescrever,
                            notificador=Notificador(o.discord_webhook, o.telegram_token, o.telegram_chat_id),
                            jellyfin_url=o.jellyfin_url,
                            jellyfin_api_key=o.jellyfin_api_key if o.atualizar_jellyfin else "")
            return pos_processar(itens, cfg, self._log, ao_item=ao_item, parar=self.evento_parar.is_set)

    def _avisar_analise(self, fracao: float, texto: str) -> None:
        """Chamado pela thread enquanto analisa (consulta o TMDB e planeja cada arquivo)."""
        self.fila.put(("jf_analise", (fracao, texto)))

    def _resumo_tmdb(self, catalogo, movimentos) -> str:
        """' TMDB identificou 150 de 166.' (e avisa se o TMDB não respondeu)."""
        erro = next((c.erro for c in getattr(catalogo, "catalogos", (catalogo,)) if getattr(c, "erro", "")), "")
        analisados = [m for m in movimentos if m.fonte_nome]
        pelo_tmdb = sum(m.fonte_nome == "TMDB" for m in analisados)
        if erro:
            self._log.warning("TMDB: %s", erro)
            self.fila.put(("jf_tmdb_estado", (False, f"Sem resposta na prévia: {erro}")))
            self.fila.put(("msg", ("TMDB não respondeu",
                                   f"{erro}\n\nOs nomes vieram do catálogo local ou do próprio arquivo "
                                   "(coluna \"Nome via\"). Use \"Testar conexão com o TMDB\" para conferir.",
                                   "aviso")))
        self._log.info("TMDB identificou %d de %d", pelo_tmdb, len(analisados))
        return f" TMDB identificou {pelo_tmdb} de {len(analisados)}."

    def ao_testar_legendas(self) -> None:
        """Testa a chave de cada fonte de legendas preenchida (OpenSubtitles e/ou SubDL)."""
        o = self.obter_opcoes_jellyfin()
        fontes = self.FONTES_LEGENDA
        testes = []
        if o.fonte_legenda == fontes[1] or o.chave_opensubtitles and o.fonte_legenda != fontes[3]:
            testes.append(("OpenSubtitles", o.chave_opensubtitles, ProvedorOpenSubtitles))
        if o.chave_subdl or o.fonte_legenda == fontes[3]:
            testes.append(("SubDL", o.chave_subdl, ProvedorSubDL))
        if not testes or not any(chave for _, chave, _ in testes):
            self.mostrar_mensagem("Legendas", "Preencha a chave do OpenSubtitles e/ou do SubDL.", "aviso")
            return

        def tarefa():
            linhas, todos_ok = [], True
            for nome, chave, classe in testes:
                if not chave:
                    linhas.append(f"✕  {nome}: chave não preenchida")
                    todos_ok = False
                    continue
                try:
                    texto = classe(chave).testar()
                    linhas.append(f"✓  {nome}: {texto}")
                    self._log.info("Legendas - %s: %s", nome, texto)
                except Exception as erro:              # ErroLegenda, rede...
                    linhas.append(f"✕  {nome}: {erro}")
                    self._log.warning("Legendas - %s: %s", nome, erro)
                    todos_ok = False
            self.fila.put(("legendas_estado", ("\n".join(linhas), todos_ok)))
            self.fila.put(("msg", ("Fontes de legenda", "\n".join(linhas), "sucesso" if todos_ok else "erro")))

        self._rodar("Testando as chaves das legendas...", tarefa)

    def ao_testar_tmdb(self) -> None:
        o = self.obter_opcoes_jellyfin()
        if not o.chave_tmdb:
            self.mostrar_mensagem("TMDB", "Cole a chave da API do TMDB no campo acima.\n\n"
                                  "Ela é gratuita: themoviedb.org > Configurações > API.", "aviso")
            return

        def tarefa():
            try:
                texto = CatalogoTMDB(o.chave_tmdb).testar()
            except ErroCatalogo as erro:
                self._log.warning("TMDB: %s", erro)
                self.fila.put(("jf_tmdb_estado", (False, f"Sem conexão: {erro}")))
                self.fila.put(("msg", ("TMDB", f"Não consegui conectar: {erro}.", "erro")))
                return
            self._log.info("TMDB: %s", texto)
            dica = ("" if o.tmdb else "\n\nMarque \"Consultar o TMDB para confirmar nomes\" para usar o TMDB "
                    "na pré-visualização.")
            self.fila.put(("jf_tmdb_estado", (True, "TMDB conectado" + ("" if o.tmdb else " (desmarcado abaixo)"))))
            self.fila.put(("msg", ("TMDB conectado",
                                   f"Tudo certo: {texto}.\n\nNa tabela, a coluna \"Nome via\" mostra "
                                   f"\"TMDB ✓\" em cada arquivo cujo nome o TMDB identificou.{dica}", "sucesso")))

        self._rodar("Testando o TMDB...", tarefa)

    def ao_testar_jellyfin(self) -> None:
        o = self.obter_opcoes_jellyfin()

        def tarefa():
            try:
                servidor = testar_conexao(o.jellyfin_url, o.jellyfin_api_key)
                self._log.info("Jellyfin: conectado a %s", servidor)
                self.fila.put(("msg", ("Jellyfin conectado", f"Tudo certo: {servidor}.", "sucesso")))
            except ErroJellyfin as erro:
                self._log.warning("Jellyfin: %s", erro)
                self.fila.put(("msg", ("Jellyfin", str(erro).capitalize() + ".", "erro")))

        self._rodar("Testando o Jellyfin...", tarefa)

    def ao_testar_avisos(self) -> None:
        o = self.obter_opcoes_jellyfin()
        notificador = Notificador(o.discord_webhook, o.telegram_token, o.telegram_chat_id)
        if not notificador.ativo:
            self.mostrar_mensagem("Avisos", "Preencha o webhook do Discord e/ou o token e o Chat ID do Telegram.",
                                  "aviso")
            return

        def tarefa():
            ok = notificador.enviar(discord="✅ **Teste do videoscraper:** os avisos estão funcionando.",
                                    telegram="✅ <b>Teste do videoscraper:</b> os avisos estão funcionando.")
            if ok:
                self.fila.put(("msg", ("Avisos", "Aviso de teste enviado. Confira o Discord/Telegram.", "sucesso")))
            else:
                self.fila.put(("msg", ("Avisos", "Não consegui enviar. Veja o motivo em 'Abrir log'.", "erro")))

        self._rodar("Enviando aviso de teste...", tarefa)

    # ================================================================== "Corrigir nome" (regras que você ensina)
    @property
    def arquivo_regras(self) -> Path:
        return config.ARQUIVO.parent / "regras_nomes.json"

    def regras_de_nome(self) -> list:
        return carregar_regras(self.arquivo_regras)

    def ao_corrigir_nome(self) -> None:
        """Não identificado (ou nome errado): você diz qual série/filme é, a regra fica guardada e a
        pré-visualização roda de novo. Série: vale para a pasta inteira; filme: para o arquivo."""
        if self.trabalhando:
            return
        ids = [int(i) for i in self.tabela_jf.selection() if i.isdigit()]
        movimentos = [self._movimentos_previa[i] for i in ids if 0 <= i < len(self._movimentos_previa)]
        movimentos = [m for m in movimentos if m.status not in ("limpeza", "pasta_apagada")]
        if not movimentos:
            self.mostrar_mensagem("Corrigir nome", "Pré-visualize e clique no arquivo que ficou sem nome (ou com o "
                                  "nome errado). Ctrl+clique escolhe vários.", "aviso")
            return
        tipo = "serie" if self.obter_opcoes_jellyfin().modo == "series" else "filme"
        alvos = list(dict.fromkeys(m.origem.parent if tipo == "serie" else m.origem for m in movimentos))
        primeiro = movimentos[0].origem
        if tipo == "serie":
            ep = episodio_do_video(primeiro)
            sugestao = ep.serie if ep else (serie_da_pasta(primeiro.parent.name) or ("",))[0]
        else:
            sugestao = extrair_titulo_e_ano(primeiro.name).titulo
        atual = regra_para(primeiro, self.regras_de_nome(), tipo)
        onde = "\n".join(str(a) for a in alvos[:3]) + (f"\n… e mais {len(alvos) - 3}" if len(alvos) > 3 else "")
        resposta = self.pedir_nome(tipo, atual.titulo if atual else sugestao, onde,
                                   atual.descricao() if atual else "")
        if not resposta:
            return
        if resposta.get("esquecer"):
            esquecer = {os.path.normcase(os.path.abspath(str(a))) for a in alvos}
            salvar_regras(self.arquivo_regras, [r for r in self.regras_de_nome() if not (
                r.tipo == tipo and os.path.normcase(os.path.abspath(r.caminho)) in esquecer)])
            self._log.info("Regra de nome esquecida: %s", onde.replace("\n", "; "))
        else:
            for alvo in alvos:
                regra = RegraNome(str(alvo), tipo, resposta["titulo"], resposta.get("ano"),
                                  resposta.get("temporada") if tipo == "serie" else None)
                adicionar_regra(self.arquivo_regras, regra)
                self._log.info("Regra de nome: %s -> %s", alvo, regra.descricao())
        self.ao_previsualizar()

    # ================================================================== conflitos com um clique
    def ao_resolver_conflitos(self) -> None:
        """Conflitos da prévia (os selecionados; sem seleção, todos): fica a melhor cópia, a outra vai
        para .organizador/removidos. "Desfazer última" põe tudo de volta."""
        if self.trabalhando:
            return
        ids = [int(i) for i in self.tabela_jf.selection() if i.isdigit()]
        escolhidos = [self._movimentos_previa[i] for i in ids if 0 <= i < len(self._movimentos_previa)]
        escolhidos = [m for m in escolhidos if m.status == "conflito"]
        if not any(m.status == "conflito" for m in self._movimentos_previa):
            self.mostrar_mensagem("Resolver conflitos", "Nenhum conflito na pré-visualização. (Conflito = duas "
                                  "cópias do mesmo filme/episódio, ou um que já está na biblioteca.)", "info")
            return
        o = self.obter_opcoes_jellyfin()
        previa = list(self._movimentos_previa)

        def tarefa():
            self._log.info("Comparando as cópias (resolução lida de cada vídeo)...")
            decisoes = decidir_conflitos(previa, escolhidos or None)
            self.fila.put(("conflitos_decididos", (decisoes, o)))

        self._rodar("Comparando as cópias...", tarefa)

    def _confirmar_conflitos(self, decisoes, o) -> None:
        if not decisoes:
            self.mostrar_mensagem("Resolver conflitos", "Não consegui comparar esses conflitos (arquivos sumiram?). "
                                  "Pré-visualize de novo.", "aviso")
            return
        lista = "\n".join(d.texto() for d in decisoes[:6]) + (f"\n… e mais {len(decisoes) - 6}"
                                                              if len(decisoes) > 6 else "")
        if not self.perguntar("Resolver conflitos",
                              f"{len(decisoes)} conflito(s): fica a melhor cópia (maior resolução, depois a origem e "
                              f"o tamanho).\n\n{lista}\n\nA que sai vai para a pasta .organizador\\removidos (não é "
                              "apagada de vez; \"Desfazer última\" põe de volta). Para liberar o espaço, apague essa "
                              "pasta depois."):
            return

        def tarefa():
            saiu, mensagens = aplicar_conflitos(decisoes, Path(o.destino), Path(o.origem) if o.origem else None)
            for m in mensagens:
                (self._log.warning if m.startswith("erro") else self._log.info)("%s", m)
            self.fila.put(("status_fim", f"Conflitos: {saiu} cópia(s) pior(es) tiradas. Pré-visualizando de novo..."))
            self.fila.put(("previa_de_novo", None))

        self._rodar("Resolvendo conflitos...", tarefa)

    def ultimo_relatorio(self) -> Path | None:
        """A planilha do relatório mais recente (C:\\Users\\<você>\\.videoscraper\\relatorios)."""
        planilhas = list((config.ARQUIVO.parent / "relatorios").glob("relatorio-*.csv"))
        return max(planilhas, key=lambda p: p.stat().st_mtime) if planilhas else None

    def ao_abrir_relatorio(self) -> None:
        """Abre a planilha do último relatório (no Excel ou no programa de planilhas padrão)."""
        planilha = self.ultimo_relatorio()
        if planilha is None:
            if self.perguntar("Relatório", "Ainda não há relatório gerado.\n\nGerar agora? (lista o que falta: "
                              "legendas, pôsteres e episódios)"):
                self.ao_relatorio()
            return
        self._log.info("Abrindo o relatório: %s", planilha)
        self._abrir_no_sistema(str(planilha))

    def ao_abrir_log(self) -> None:
        """Abre o log SÓ da ação escolhida no seletor do console (antes abria o log geral, com tudo)."""
        registro = self._registros[self._registro_visivel]
        arquivo = registro.get("arquivo")
        if arquivo and Path(arquivo).exists():
            self._abrir_no_sistema(str(arquivo))
        elif self.arquivo_log.exists():
            self.mostrar_mensagem("Log", "Esta ação não tem log próprio; abrindo o log geral "
                                  f"(todas as ações):\n{self.arquivo_log}", "info")
            self._abrir_no_sistema(str(self.arquivo_log))
        else:
            self.mostrar_mensagem("Log", "O log ainda está vazio.", "info")

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
            self._log.info("Desfazendo: %s", log.name)
            mensagens = desfazer(log)
            for m in mensagens:
                self._log.info("%s", m)
            voltaram = sum(m.startswith("voltou") for m in mensagens)
            espelhos = sum(m.startswith("espelho removido") for m in mensagens)
            texto = f"{voltaram} arquivo(s) voltaram para onde estavam." + (
                f"\n{espelhos} espelho(s) .strm criados foram apagados." if espelhos else "")
            self.fila.put(("jf_limpar", None))
            self.fila.put(("status_fim", f"Desfeito: {voltaram} voltaram, {espelhos} espelho(s) apagado(s)."))
            self.fila.put(("msg", ("Desfeito", texto, "sucesso")))

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
        campos = (("Pasta de origem", o.origem, self.var_jf_origem),
                  ("Biblioteca", o.destino, self.var_jf_destino))
        for titulo, caminho, var in campos[0 if precisa_origem else 1:]:
            problema = caminho and problema_no_caminho(caminho)
            if not problema:
                continue
            sugestao = sugestao_de_caminho(caminho)
            if sugestao and self.perguntar(titulo, f"{problema[0].upper()}{problema[1:]}\n\n"
                                                   f"Usar este caminho?\n{sugestao}"):
                var.set(sugestao)
                return self._validar_jellyfin(precisa_origem)
            if not sugestao:
                self.mostrar_mensagem(titulo, f"{problema[0].upper()}{problema[1:]}\n\n"
                                      "Apague o campo e escolha a pasta pelo botão \"Escolher...\".", "aviso")
            return None
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
                o.limpar_lixo, o.apagar_pasta_origem, o.nomes_episodios)

    def _problema_legendas(self, o) -> str | None:
        fontes = self.FONTES_LEGENDA
        if o.fonte_legenda == fontes[1] and not o.chave_opensubtitles:
            return "Preencha a chave da API do OpenSubtitles (é gratuita em opensubtitles.com)."
        if o.fonte_legenda == fontes[3] and not o.chave_subdl:
            return "Preencha a chave da API do SubDL (é gratuita em subdl.com, no Painel > API)."
        if o.fonte_legenda == fontes[2] and "{consulta}" not in o.url_site:
            return "A URL de busca precisa ter {consulta} no lugar do termo pesquisado.\n" \
                   "Ex.: https://site.com/busca?q={consulta}"
        return None

    def _catalogo(self, o):
        """Com o TMDB marcado, ele vem PRIMEIRO (fonte oficial); o catálogo local fica de reserva."""
        local = CatalogoLocal.padrao()
        return CatalogoEmCadeia(CatalogoTMDB(o.chave_tmdb), local) if o.tmdb else local

    @contextlib.contextmanager
    def _provedores(self, o):
        """Cria o provedor de legendas escolhido (e desliga o site de demonstração no fim)."""
        fontes = self.FONTES_LEGENDA
        servidor = None
        try:
            if o.fonte_legenda == fontes[0]:
                servidor, base = iniciar_site_demo()
                yield [ProvedorSiteHTML(ConfigSite(f"{base}/busca?q={{consulta}}", nome="site demo"))]
            elif o.fonte_legenda == fontes[1]:             # OpenSubtitles; o SubDL é a reserva (se houver)
                yield [ProvedorOpenSubtitles(o.chave_opensubtitles)] + (
                    [ProvedorSubDL(o.chave_subdl)] if o.chave_subdl else [])
            elif o.fonte_legenda == fontes[3]:
                yield [ProvedorSubDL(o.chave_subdl)]
            else:
                yield [ProvedorSiteHTML(ConfigSite(o.url_site))]
        finally:
            if servidor:
                servidor.shutdown()

    def ao_selecionar_jf(self) -> None:
        ids = self.tabela_jf.selection()
        if ids and self._movimentos_previa:
            self._mostrar_detalhe(int(ids[0]), "Selecionado")

    def _mostrar_detalhe(self, indice: int, titulo: str) -> None:
        if not 0 <= indice < len(self._movimentos_previa):
            return
        m = self._movimentos_previa[indice]
        junto = ", ".join(f"{a.name} → {b.name}" for a, b in (m.acompanhantes or []))
        apagar = ", ".join(a.name for a in (m.apagar or []))
        extras = "   |   ".join(t for t in (f"Vai junto: {junto}" if junto else "",
                                            f"Apagar: {apagar}" if apagar else "",
                                            f"Apagar a pasta inteira: {m.pasta_apagar}" if m.pasta_apagar else "",
                                            m.detalhe if m.status != "simulado" else "") if t)
        self.mostrar_detalhe_jf(
            f"Antes → Depois  ({titulo}: #{indice + 1})", str(m.origem.parent), m.origem.name,
            str(m.destino.parent) if m.destino else "", m.destino.name if m.destino else "(fica onde está)",
            extras)

    def _mostrar_movimentos(self, movimentos) -> None:
        self._movimentos_previa = list(movimentos)
        self.limpar_tabela_jf()
        for i, m in enumerate(movimentos):
            texto, cor = STATUS_MOVIMENTO.get(m.status, (m.status, None))
            if m.status == "simulado" and m.detalhe:
                texto = "vai mover (confira)"       # nome não confirmado no catálogo
            # Só o nome do arquivo: a pasta tem o mesmo nome (Filmes/Nome (Ano)/Nome (Ano).mkv)
            novo = m.destino.name if m.destino else f"({m.detalhe})"
            if m.status in ("limpeza", "pasta_apagada"):          # sobra de uma organização anterior
                artes = len(m.acompanhantes or [])
                novo = ("(apagar a pasta inteira" + (f"; {artes} imagem(ns) vão para junto dos episódios/filmes"
                                                     if artes else "") + ")")
            if m.destino and m.resumo_extras and m.status in ("simulado", "movido"):
                novo += f"   ({m.resumo_extras})"
            progresso = "" if m.status in ("simulado", "limpeza") else "—"      # "—": não vai mexer
            self.adicionar_linha_jf(str(i), i + 1, texto, cor, m.origem.name, novo, "", progresso,
                                    categoria=CATEGORIA.get(m.status), fonte=self._texto_fonte(m))

    def _texto_fonte(self, m) -> str:
        """Coluna 'Nome via'. Com o TMDB ligado: 'TMDB ✓' (identificou) ou 'TMDB ✕ (catálogo/arquivo)'.
        Sem o TMDB: só de onde veio ('catálogo' ou 'arquivo')."""
        fonte = m.fonte_nome
        if not fonte:
            return "—"
        if fonte == "TMDB":
            return "TMDB ✓"
        return f"TMDB ✕ ({fonte})" if self._tmdb_ativo else fonte

    # --- configurações (pastas e opções lembradas entre execuções)
    def _carregar_config(self) -> None:
        dados = config.carregar().get("jellyfin", {})
        dados.setdefault("chave_tmdb", os.environ.get("TMDB_API_KEY", ""))
        dados.setdefault("chave_opensubtitles", os.environ.get("OPENSUBTITLES_API_KEY", ""))
        dados.setdefault("chave_subdl", os.environ.get("SUBDL_API_KEY", ""))
        for chave, variavel in (("jellyfin_url", "JELLYFIN_URL"), ("jellyfin_api_key", "JELLYFIN_API_KEY"),
                                ("discord_webhook", "DISCORD_WEBHOOK_URL"), ("telegram_token", "TELEGRAM_BOT_TOKEN"),
                                ("telegram_chat_id", "TELEGRAM_CHAT_ID")):
            dados.setdefault(chave, os.environ.get(variavel, ""))
        dados.setdefault("origem", PASTA_PADRAO)
        self.definir_opcoes_jellyfin(dados)
        self.var_jf_iniciar_windows.set(inicializacao.ativo())    # o que vale é o registro do Windows
        if self.var_jf_vigiar.get():                 # ficou ligada da última vez: volta a vigiar
            self.after(3000, self.ao_alternar_vigia)
        self.definir_estado_conferencia(self._texto_ultima_conferencia())
        self._conferencia_agendada = self.after(60_000, self._ciclo_conferencia)
        if not os.environ.get("VIDEOSCRAPER_SEM_ATUALIZACAO"):
            self.after(4000, self._ciclo_versao)          # ao abrir e depois a cada 6 horas (programa aberto)

    # ================================================================== TV ao vivo (canais no Jellyfin)
    @property
    def arquivo_canais(self) -> Path:
        return config.ARQUIVO.parent / "canais.json"

    def ao_tv_ao_vivo(self) -> None:
        if self.janela_canais is None or not self.janela_canais.winfo_exists():
            self.janela_canais = JanelaCanais(self, {
                "adicionar": self._adicionar_canal, "importar_arquivo": self._importar_canais_arquivo,
                "importar_endereco": self._importar_canais_endereco, "remover": self._remover_canais,
                "remover_todos": self._remover_todos_canais,
                "conferir": self._conferir_canais, "publicar": self._publicar_canais})
            dados = config.carregar().get("tv", {})
            dados.setdefault("pasta", str(config.ARQUIVO.parent / "tv"))
            self.janela_canais.definir_valores(dados)
        self._canais = carregar_canais(self.arquivo_canais)
        self._mostrar_canais()
        self.janela_canais.lift()

    def _mostrar_canais(self) -> None:
        if self.janela_canais is None or not self.janela_canais.winfo_exists():
            return
        linhas = []
        for i, c in enumerate(self._canais):
            situacao = self._situacao_canais.get(c.url)            # None = ainda não conferido
            linhas.append((str(i), c.nome, c.grupo, situacao.detalhe if situacao else "—", c.url,
                           situacao.ok if situacao else None))
        self.janela_canais.preencher(linhas)

    def _guardar_canais(self) -> None:
        salvar_canais(self.arquivo_canais, self._canais)
        if self.janela_canais is not None and self.janela_canais.winfo_exists():
            tudo = config.carregar()
            tudo["tv"] = self.janela_canais.valores()
            config.salvar(tudo)
        self._mostrar_canais()

    def _juntar_canais(self, novos) -> int:
        conhecidos = {c.url for c in self._canais}
        somados = [c for c in novos if c.url not in conhecidos]
        self._canais += somados
        self._guardar_canais()
        return len(somados)

    def _adicionar_canal(self) -> None:
        janela = self.janela_canais
        nome, link = janela.var_nome.get().strip(), janela.var_link.get().strip()
        if not link.lower().startswith(("http://", "https://", "rtsp://", "rtmp://", "udp://")):
            self.mostrar_mensagem("TV ao vivo", "Cole o link do sinal do canal (começa com http://, https://, rtsp://...).",
                                  "aviso")
            return
        if link.lower().split("?")[0].endswith(".m3u") and not nome:
            self._importar_canais_endereco()                   # é uma LISTA de canais: importa todos
            return
        self._juntar_canais([Canal(nome or link.rsplit("/", 1)[-1], link)])
        janela.var_nome.set("")
        janela.var_link.set("")

    def _importar_canais_arquivo(self) -> None:
        arquivo = filedialog.askopenfilename(title="Lista de canais (.m3u)",
                                             filetypes=[("Lista de canais", "*.m3u *.m3u8"), ("Todos", "*.*")])
        if arquivo:
            try:
                somados = self._juntar_canais(importar_canais(arquivo))
            except (NaoEhLista, OSError) as erro:
                self.mostrar_mensagem("TV ao vivo", f"Não importei: {erro}", "aviso")
                return
            self._log.info("TV ao vivo: %d canal(is) importado(s) de %s", somados, arquivo)

    def _importar_canais_endereco(self) -> None:
        link = self.janela_canais.var_link.get().strip()
        if not link.lower().startswith(("http://", "https://")):
            self.mostrar_mensagem("TV ao vivo", "Cole o endereço da lista .m3u (http...) no campo do link.", "aviso")
            return

        def tarefa():
            try:
                novos = importar_canais(link)
            except (NaoEhLista, OSError) as erro:          # página de site, endereço fora do ar...
                self._log.warning("TV ao vivo: %s: %s", link, erro)
                self.fila.put(("msg", ("TV ao vivo", f"Não importei: {erro}", "aviso")))
                return
            self._log.info("TV ao vivo: %d canal(is) na lista %s", len(novos), link)
            self.fila.put(("canais_importados", novos))

        self._rodar("Importando a lista de canais...", tarefa)

    def _remover_todos_canais(self) -> None:
        if self._canais and self.perguntar("TV ao vivo", f"Tirar TODOS os {len(self._canais)} canal(is) da lista?\n\n"
                                           "(O que já foi enviado ao Jellyfin muda só no próximo \"Salvar e enviar\".)"):
            self._canais, self._situacao_canais = [], {}
            self._guardar_canais()

    def _remover_canais(self) -> None:
        tirar = {int(i) for i in self.janela_canais.selecionados()}
        if not tirar:
            self.mostrar_mensagem("TV ao vivo", "Selecione os canais (clique; Ctrl+clique para vários), ou use "
                                  "\"Selecionar os fora do ar\" / \"Remover todos\".", "aviso")
            return
        if self.perguntar("TV ao vivo", f"Tirar {len(tirar)} canal(is) da lista?"):
            self._canais = [c for i, c in enumerate(self._canais) if i not in tirar]
            self._guardar_canais()

    def _progresso_com_velocidade(self, texto: str):
        """ao_progresso(feitos, total) que mostra a velocidade e quanto falta:
        'Conferindo canais: 526 de 11393 · 41/s · faltam ~4 min'."""
        inicio = time.monotonic()

        def avisar(feitos: int, total: int) -> None:
            passou = max(time.monotonic() - inicio, 0.001)
            por_segundo = feitos / passou
            falta = (total - feitos) / por_segundo if por_segundo > 0 else 0
            resto = (f"faltam ~{falta / 60:.0f} min" if falta >= 90 else f"faltam ~{falta:.0f} s") if feitos < total else ""
            self._avisar_analise(feitos / total, f"{texto}: {feitos} de {total} · {por_segundo:.0f}/s"
                                 + (f" · {resto}" if resto else ""))
        return avisar

    def _conferir_canais(self) -> None:
        canais = list(self._canais)
        if not canais:
            return

        def tarefa():
            situacoes = conferir_canais(canais, parar=self.evento_parar.is_set,
                                        ao_progresso=self._progresso_com_velocidade("Conferindo canais"))
            for c, sit in situacoes:
                (self._log.info if sit.ok else self._log.warning)("[canal] %s: %s", c.nome, sit.detalhe)
            fora = sum(1 for _, sit in situacoes if not sit.ok)
            self.fila.put(("canais_conferidos", situacoes))
            parado = f" Parado: {len(situacoes)} de {len(canais)} conferidos." if len(situacoes) < len(canais) else ""
            self.fila.put(("status_fim", f"Canais: {len(situacoes) - fora} no ar, {fora} fora do ar.{parado}"))

        self._rodar("Conferindo os canais ao vivo...", tarefa)

    def _publicar_canais(self) -> None:
        valores = self.janela_canais.valores()
        if not self._canais and not valores["antena"]:
            self.mostrar_mensagem("TV ao vivo", "Adicione canais (ou o IP da antena HDHomeRun) primeiro.", "aviso")
            return
        if not valores["pasta"]:
            self.mostrar_mensagem("TV ao vivo", "Escolha a pasta onde salvar a lista (canais.m3u).", "aviso")
            return
        self._guardar_canais()
        o = self.obter_opcoes_jellyfin()
        canais = list(self._canais)

        def tarefa():
            cliente = ClienteTV(o.jellyfin_url, o.jellyfin_api_key) if o.jellyfin_url and o.jellyfin_api_key else None
            feito = publicar_canais(canais, valores["pasta"], valores["no_servidor"], valores["guia"], cliente,
                                    valores["antena"])
            for linha in feito:
                self._log.info("TV ao vivo: %s", linha)
            dica = "" if cliente else ("\n\nSem o endereço e a chave do Jellyfin (aba Jellyfin), a lista só foi salva: "
                                       "cadastre-a em Painel > TV ao vivo > Sintonizadores > M3U.")
            self.fila.put(("msg", ("TV ao vivo", "\n".join(feito) + dica, "sucesso")))

        self._rodar("Enviando os canais ao Jellyfin...", tarefa)

    # ================================================================== Windows: iniciar junto e ícone no relógio
    def ao_alternar_inicializacao(self) -> None:
        ligar = self.var_jf_iniciar_windows.get()
        try:
            inicializacao.ativar(ligar)
        except OSError as erro:
            self.var_jf_iniciar_windows.set(inicializacao.ativo())
            self.mostrar_mensagem("Iniciar com o Windows", f"Não deu: {erro}", "aviso")
            return
        if ligar:
            self.var_jf_fechar_bandeja.set(True)         # quem inicia com o Windows quer ficar rodando
        self._salvar_config()
        self._log.info("Iniciar com o Windows: %s", "ligado (minimizado perto do relógio)" if ligar else "desligado")

    def esconder_na_bandeja(self) -> None:
        """Some da barra de tarefas e fica perto do relógio (sem a bandeja, só minimiza)."""
        if self._bandeja is None and bandeja.disponivel():
            self._bandeja = bandeja.Bandeja(lambda acao: self.fila.put(("bandeja", acao)),
                                            f"videoscraper {atualizacao.versao_atual()}")
        if self._bandeja is not None:
            try:
                self._bandeja.mostrar()
                self.withdraw()
                self._log.info("Rodando perto do relógio (clique no ícone para abrir). A vigia continua.")
                return
            except Exception as erro:                    # sem bandeja neste sistema: só minimiza
                self._log.warning("Ícone perto do relógio indisponível: %s", erro)
                self._bandeja = None
        self.iconify()

    def mostrar_janela(self) -> None:
        if self._bandeja is not None:
            self._bandeja.esconder()
            self._bandeja = None
        self.deiconify()
        self.lift()
        self.focus_force()

    def sair_de_vez(self) -> None:
        self._saindo = True
        self.mostrar_janela()
        self.fechar()

    # ================================================================== aviso de versão nova
    INTERVALO_VERSAO_MS = 6 * 60 * 60 * 1000

    def _ciclo_versao(self) -> None:
        """Consulta sozinha enquanto o programa está aberto (quem deixa rodando perto do relógio também é avisado)."""
        self._versao_agendada = self.after(self.INTERVALO_VERSAO_MS, self._ciclo_versao)
        if self.var_jf_avisar_versao.get():
            self.verificar_versao_nova()

    def ao_verificar_atualizacoes(self) -> None:
        """Botão "Verificar atualizações": consulta AGORA, sem fechar o programa, e sempre responde."""
        self.bt_atualizacoes.configure(state="disabled", text="⟳  Consultando...")

        def consultar():
            try:
                nova = atualizacao.ultima_versao()
                self.fila.put(("versao_consultada", (nova, None)))
            except atualizacao.ErroAtualizacao as erro:
                self.fila.put(("versao_consultada", (None, str(erro))))
        threading.Thread(target=consultar, daemon=True).start()

    def _mostrar_versao_consultada(self, nova, erro) -> None:
        self.bt_atualizacoes.configure(state="normal", text="⟳  Verificar atualizações")
        atual = atualizacao.versao_atual()
        if erro:
            self.mostrar_mensagem("Verificar atualizações", f"Não consegui consultar agora: {erro}.\n"
                                  f"Esta é a versão {atual}.", "aviso")
        elif atualizacao.numeros(nova.versao) > atualizacao.numeros(atual):
            self._avisar_versao_nova(nova)
        else:
            self._log.info("Atualizações: esta é a mais nova (%s; publicada: %s)", atual, nova.versao)
            self.mostrar_mensagem("Verificar atualizações", f"Você já está na versão mais nova ({atual}).", "sucesso")

    def _baixar_atualizacao(self, nova) -> None:
        """Baixa o .zip em segundo plano (pode continuar usando o programa) e abre a pasta no fim."""
        if self.trabalhando:
            self.mostrar_mensagem("Atualização", "Espere a tarefa atual terminar e clique de novo em "
                                  "\"Verificar atualizações\".", "aviso")
            return

        def tarefa():
            def progresso(feitos, total):
                if total:
                    self._avisar_analise(feitos / total, f"Baixando {nova.versao}: {feitos / 1024 ** 2:.0f} de "
                                                         f"{total / 1024 ** 2:.0f} MB")
            try:
                arquivo = atualizacao.baixar(nova, ao_progresso=progresso, parar=self.evento_parar.is_set)
            except atualizacao.ErroAtualizacao as erro:
                self.fila.put(("msg", ("Atualização", f"{erro}. Use a página de download:\n{nova.url}", "aviso")))
                return
            self._log.info("Atualização %s baixada: %s", nova.versao, arquivo)
            self.fila.put(("atualizacao_baixada", (nova, arquivo)))
            self.fila.put(("status_fim", f"Versão {nova.versao} baixada em {arquivo.parent}."))

        self._rodar(f"Baixando a versão {nova.versao}...", tarefa)

    def _atualizacao_baixada(self, nova, arquivo) -> None:
        """Baixou: avisa que, para concluir, o programa PRECISA FECHAR (o Windows não troca um programa aberto)."""
        if not atualizacao.pode_instalar_sozinho():           # rodando pelo Python: troca à mão
            if self.escolher("Atualização baixada",
                             f"A versão {nova.versao} está em:\n{arquivo}\n\nPara concluir, FECHE o programa, extraia o "
                             ".zip e troque a pasta do programa pela nova (um programa aberto não pode ser trocado). "
                             "Configurações, regras e canais continuam valendo.",
                             ("Abrir a pasta",), cancelar="Depois") == "Abrir a pasta":
                self._abrir_no_sistema(str(arquivo.parent))
            return
        escolha = self.escolher(
            "Atualização pronta para instalar",
            f"A versão {nova.versao} foi baixada.\n\nPara concluir a atualização, o programa PRECISA SER FECHADO: o "
            "Windows não deixa trocar um programa que está aberto. Ele fecha, troca os arquivos sozinho (uns "
            "segundos) e abre de novo já na versão nova.\n\nConfigurações, regras e canais continuam valendo.",
            ("Fechar e atualizar agora", "Atualizar quando eu fechar"), cancelar="Depois")
        if escolha == "Fechar e atualizar agora":
            self._instalar_ao_sair = (arquivo, True)
            self.sair_de_vez()
        elif escolha == "Atualizar quando eu fechar":
            self._instalar_ao_sair = (arquivo, False)
            self.definir_status(f"A versão {nova.versao} será instalada quando você fechar o programa.")
            self._log.info("Atualização %s: instala ao fechar o programa", nova.versao)

    def verificar_versao_nova(self, sempre: bool = False) -> None:
        """Consulta a página Releases (em segundo plano). Cada versão nova é avisada uma vez só."""
        ja_avisada = self.var_jf_versao_avisada.get()      # lido aqui: variável do Tk só na thread da janela

        def consultar():
            nova = atualizacao.verificar()
            if nova and (sempre or nova.versao != ja_avisada):
                self.fila.put(("versao_nova", nova))
        threading.Thread(target=consultar, daemon=True).start()

    def _avisar_versao_nova(self, nova) -> None:
        self.var_jf_versao_avisada.set(nova.versao)
        self._salvar_config()
        self._log.info("Versão nova disponível: %s (esta é %s) %s", nova.versao, atualizacao.versao_atual(), nova.url)
        notas = f"\n\nO que mudou:\n{nova.notas[:400]}" if nova.notas else ""
        opcoes = (("Baixar agora",) if nova.arquivo_url else ()) + ("Abrir a página de download",)
        escolha = self.escolher("Versão nova", f"Saiu a versão {nova.versao} do programa (esta é a "
                                f"{atualizacao.versao_atual()}).\n\n\"Baixar agora\" baixa em segundo plano: dá para "
                                f"continuar usando. Só para INSTALAR o programa precisa fechar (o Windows não troca um "
                                f"programa aberto); você escolhe a hora. Suas configurações continuam valendo.{notas}",
                                opcoes, cancelar="Agora não")
        if escolha == "Baixar agora":
            self._baixar_atualizacao(nova)
        elif escolha == "Abrir a página de download":
            webbrowser.open(nova.url)

    def _salvar_config(self) -> None:
        o = self.obter_opcoes_jellyfin()
        dados = asdict(o)
        for chave in ("destino", "modo"):
            dados.pop(chave)
        destinos = self.destinos_jellyfin()
        dados["destino_filmes"], dados["destino_series"] = destinos["Filmes"], destinos["Séries"]
        if not o.lembrar_chaves:                     # chaves de API só se o usuário pedir
            for segredo in SEGREDOS:
                dados.pop(segredo)
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
        if self.var_jf_fechar_bandeja.get() and not self._saindo:
            self._salvar_config()
            self.esconder_na_bandeja()               # o X só esconde; "Sair" no ícone fecha de verdade
            return
        if self.trabalhando and not self.perguntar("Sair", "Ainda está trabalhando. Sair mesmo assim?"):
            self._saindo = False
            return
        if self._bandeja is not None:
            self._bandeja.esconder()
        if self._instalar_ao_sair:                      # a troca dos arquivos começa assim que fechar
            arquivo, reabrir = self._instalar_ao_sair
            try:
                atualizacao.instalar_ao_fechar(arquivo, reabrir=reabrir)
                self._log.info("Atualizando com %s ao fechar (o programa %s)", arquivo,
                               "abre de novo sozinho" if reabrir else "abre na versão nova da próxima vez")
            except OSError as erro:
                self._log.error("Não consegui iniciar a atualização: %s", erro)
        self._salvar_config()
        self.evento_parar.set()
        for agendado in (self._vigia_agendada, self._conferencia_agendada, self._versao_agendada):
            if agendado:
                self.after_cancel(agendado)
        encerrar_log_da_acao(self._log_acao)
        self._log_acao = None
        sys.stdout, sys.stderr = self._stdout, self._stderr
        self.destroy()


def main(minimizado: bool | None = None) -> int:
    """minimizado (ou --minimizado): abre já perto do relógio (é assim que o Windows inicia)."""
    app = AppModerna()
    if minimizado if minimizado is not None else "--minimizado" in sys.argv:
        app.after(300, app.esconder_na_bandeja)
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
