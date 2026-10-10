"""Liga o motor de scraping à interface moderna.

    JanelaModerna (gui_moderna.py)  -> só aparência; cliques são placeholders
    AppModerna    (este arquivo)    -> herda a janela e preenche os placeholders com o motor

O padrão é o mesmo da interface clássica (gui.py): o trabalho pesado roda numa thread e
conversa com a janela por uma fila, para a tela nunca travar.
"""

from __future__ import annotations

import re
import contextlib
import json
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

from jellyfin_tools import (CatalogoLocal, CatalogoTMDB, ErroCatalogo, ProvedorOpenSubtitles, ProvedorSubDL,
                            desfazer, organizar_pasta)
from jellyfin_tools.legendas import normalizar_idiomas
from jellyfin_tools.nomes import extrair_episodio, extrair_titulo_e_ano, normalizar, serie_da_pasta
from jellyfin_tools.metadados import ClienteTMDB
from jellyfin_tools.notificacoes import Notificador
from .memoria_downloads import MemoriaDownloads, texto_quando
from jellyfin_tools.espelho import (aplicar_espelho, classificar, conferir_e_avisar, conferir_espelhos,
                                    desfazer_ultima_remocao, eh_link_temporario, intervalo_em_segundos,
                                    licenca_aberta, lotes_de_espelhos, nome_do_link, planejar_espelho,
                                    remover_espelhos, remover_espelhos_escolhidos, verificar_links)
from jellyfin_tools.conflitos import aplicar as aplicar_conflitos, decidir as decidir_conflitos
from jellyfin_tools.traducao import Tradutor, estimar_custo, legendas_para_traduzir, traduzir_arquivo
from jellyfin_tools.transcricao import Transcritor, estimar as estimar_audio, legendar_pelo_audio, videos_sem_legenda
from jellyfin_tools.dublagem import (ErroDublagem, MotorPiper, dublar_video, preparar_piper, preparar_voz,
                                     videos_para_dublar)
from jellyfin_tools.paralelo import prioridade_baixa
from jellyfin_tools.lixeira import apagar_lotes, lotes_antigos, tamanho_legivel
from jellyfin_tools.tv_ao_vivo import carregar_canais, conferir_canais, mensagem_fora_do_ar
from jellyfin_tools.regras import RegraNome, adicionar_regra, carregar_regras, regra_para, salvar_regras
from jellyfin_tools.organizador import (DETALHE_EPISODIO, agrupar_nao_identificados, episodio_do_video, protegido, organizar_misto, problema_no_caminho, sugestao_de_caminho,
                                       ultimo_log)
from jellyfin_tools.pos_processamento import ConfigPos, itens_da_biblioteca, itens_de_series, pos_processar
from jellyfin_tools.registro import configurar_log, encerrar_log_da_acao, iniciar_log_da_acao
from jellyfin_tools.relatorio import gerar_relatorio, resumo, salvar_csv
from jellyfin_tools.servidor_jellyfin import ErroJellyfin, atualizar_biblioteca, indice_da_biblioteca, testar_conexao
from jellyfin_tools.vigia import filtro_prontos

from . import config
from .cli import salvar
from .extracao import LinkVideo
from .gui import ORIGENS, _SaidaParaFila, _so_caracteres_basicos
from . import atualizacao, automacao, instalacao, bandeja, inicializacao
from .gui_moderna import (DialogoCompletar, JanelaEspelhos, JanelaModerna, JanelaNaoIdentificados,
                          OpcoesInterface, Tema)
from .tv_moderna import TVAoVivo
from .navegador import PERFIL_PADRAO, PlaywrightAusente
from .rede import pode_ignorar_robots, site_de
from .servico import MENSAGEM_ROBOTS, Trabalho, fazer_login

def pasta_padrao_videos() -> str:
    """Onde os vídeos baixados ficam por padrão. ANTES era "videos_baixados" dentro da pasta ATUAL do processo;
    aberto pelo "Iniciar com o Windows", a pasta atual é C:\\Windows\\System32 (proibida) e o download dava
    "Acesso negado". Agora é um lugar FIXO: a pasta antiga ao lado do programa (se já existe, para não espalhar
    os vídeos) ou Vídeos\\Maestro do seu usuário."""
    if getattr(sys, "frozen", False):
        antiga = atualizacao.pasta_do_programa() / "videos_baixados"
        if antiga.is_dir():
            return str(antiga)
    return str(Path.home() / "Videos" / "Maestro")


def pasta_segura(pasta: str, padrao: str) -> str:
    """Caminho completo e fora da pasta do Windows. Relativo ("videos") vira Vídeos\\videos; dentro de
    C:\\Windows (onde o programa não pode gravar) vira o padrão."""
    texto = os.path.expandvars(os.path.expanduser((pasta or "").strip()))
    if not texto:
        return padrao
    caminho = Path(texto)
    if not caminho.is_absolute():
        caminho = Path.home() / "Videos" / caminho
    windows = os.path.normcase(os.path.abspath(os.environ.get("SystemRoot", r"C:\Windows")))
    completo = os.path.normcase(os.path.abspath(str(caminho)))
    if completo == windows or completo.startswith(windows.rstrip("\\/") + os.sep):
        return padrao
    return str(caminho)


PASTA_PADRAO = pasta_padrao_videos()
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
            "telegram_token", "chave_claude")


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


class AppModerna(TVAoVivo, JanelaModerna):
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
        self._tv_outros_pendente = None         # TV ao vivo: outros sintonizadores no Jellyfin (pergunta no fim)
        self._baixar_pendente = None            # vídeos achados pelo "Baixar" sem buscar antes (licença no fim)
        # robots.txt: os sites que a pessoa disse serem dela (ignorados só enquanto o programa está aberto) e os
        # que ela disse "não" (não pergunta de novo nesta sessão)
        self.sites_sem_robots: set[str] = set()
        self._robots_recusados: set[str] = set()
        self._robots_pendente = None
        self._tmdb_opcoes_pendente = None       # "Escolher no TMDB": a lista abre depois do "fim"
        self._instalar_ao_sair = None           # (zip, reabrir): troca os arquivos quando o programa fechar
        self._versao_agendada = None
        self._bandeja = None                    # ícone perto do relógio (quando escondida)
        self._iniciar_tv_ao_vivo()
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
        ignorar = self._confirmar_ignorar_robots(opcoes, [url])
        if ignorar is None:
            return
        self._mostrar_links([])

        def tarefa():
            with self._novo_trabalho(opcoes, ignorar) as t:
                print(f"Acessando{' com navegador' if t.usa_navegador else ''}: {url}")
                links = t.buscar(url, opcoes.profundidade, opcoes.max_paginas, True, opcoes.seletor,
                                 opcoes.filtro_links)
                print(f"{len(links)} vídeo(s) encontrado(s).")
                self.fila.put(("links", links))
                self._explicar_resultado(t, links, "buscar", perguntar=not opcoes.ignorar_robots)

        self._rodar("Buscando vídeos...", tarefa)

    def ao_baixar_selecionados(self) -> None:
        ids = self.selecionados()
        if ids and self.var_espelhar.get():           # modo híbrido: .strm no Jellyfin em vez de baixar
            self.ao_espelhar_jellyfin([int(i) for i in ids])
            return
        if not ids:
            self.mostrar_mensagem("Nada selecionado", "Clique nos vídeos da lista (Ctrl+clique para vários) "
                                  "e tente de novo, ou use 'Baixar todos'.", "aviso")
            return
        ids = [i for i in ids if i.isdigit() and int(i) < len(self.links)]
        self._log.info("Baixar selecionados: %d de %d (#%s)", len(ids), len(self.links),
                       ", #".join(str(int(i) + 1) for i in ids[:20]) + (" ..." if len(ids) > 20 else ""))
        self._baixar([self.links[int(i)] for i in ids])

    def ao_baixar_todos(self) -> None:
        """Com filtro nas colunas, "todos" = os que estão À VISTA (o escondido pelo filtro não é baixado).
        Com alguns selecionados (☑), pergunta antes: só eles ou todos? (antes baixava todos sem avisar)"""
        selecionados = [i for i in self.tabela.selection() if i.isdigit() and int(i) < len(self.links)]
        visiveis = self.visiveis_videos() if self._filtros_videos else [str(i) for i in range(len(self.links))]
        if selecionados and len(selecionados) < len(visiveis):
            acao = "Espelhar" if self.var_espelhar.get() else "Baixar"
            escolha = self.escolher(
                f"{acao} todos?", f"Há {len(selecionados)} vídeo(s) selecionado(s) (☑) na lista, mas o botão é "
                f"\"{acao} todos\": {len(visiveis)} vídeo(s).", (f"Só os {len(selecionados)} selecionados",
                                                                  f"Todos os {len(visiveis)}"))
            if escolha is None:
                return
            if escolha.startswith("Só"):
                self.ao_baixar_selecionados()
                return
        if self.var_espelhar.get():                   # modo híbrido: .strm no Jellyfin em vez de baixar
            visiveis = self.visiveis_videos() if self._filtros_videos else range(len(self.links))
            self.ao_espelhar_jellyfin([int(i) for i in visiveis if int(i) < len(self.links)])
            return
        if self._filtros_videos:
            self._baixar([self.links[int(i)] for i in self.visiveis_videos() if int(i) < len(self.links)])
            return
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
    def _baixar(self, escolhidos: list[LinkVideo], ignorar: bool | None = None) -> None:
        """ignorar: a resposta sobre o robots.txt já dada nesta mesma ação (None = perguntar, se marcado)."""
        url, opcoes = self._validar(exigir_url=not self.links)
        if not opcoes:
            return
        # archive.org: qualquer pessoa pode enviar arquivos; sem licença aberta, pergunta (como no Espelhar)
        escolhidos = self._filtrar_por_licenca(escolhidos)
        if escolhidos is None:
            return
        escolhidos = self._filtrar_ja_baixados(escolhidos)
        if escolhidos is None:
            return
        if opcoes.limite:
            escolhidos = escolhidos[:opcoes.limite]
        if ignorar is None:
            ignorar = self._confirmar_ignorar_robots(opcoes, [lk.url for lk in escolhidos] or [url])
            if ignorar is None:
                return

        def tarefa():
            with self._novo_trabalho(opcoes, ignorar) as t:
                lista = escolhidos
                if not lista:                         # ainda não buscou: busca primeiro
                    print(f"Acessando: {url}")
                    lista = t.buscar(url, opcoes.profundidade, opcoes.max_paginas, True, opcoes.seletor,
                                     opcoes.filtro_links)
                    self.fila.put(("links", lista))
                    if not lista:
                        self._explicar_resultado(t, lista, "baixar", perguntar=not opcoes.ignorar_robots)
                        return
                    if self._sem_licenca_aberta(lista) or any(map(self.memoria_downloads.baixado, lista)):
                        # pergunta no fim (licença, já baixados) e baixa o que for escolhido
                        self._ignorar_baixar_depois = ignorar        # não pergunta o robots.txt 2 vezes
                        self.fila.put(("baixar_depois", lista))
                        self.fila.put(("status_fim", f"{len(lista)} vídeo(s) encontrados: escolha a licença."))
                        return
                    if opcoes.limite:
                        lista = lista[:opcoes.limite]
                def terminou(link, status, detalhe):
                    if status == "ok":                    # memória: numa busca futura aparece "já baixado"
                        self.memoria_downloads.registrar(link, detalhe)
                    self.fila.put(("item", (link, status)))
                resumo = t.baixar(lista, opcoes.pasta, ao_terminar_item=terminou)
                self.fila.put(("msg", ("Downloads concluídos",
                                       f"Baixados: {resumo.ok}\nPulados: {resumo.pulados}\n"
                                       f"Com erro: {resumo.falhas}\n\nPasta: {opcoes.pasta}",
                                       "erro" if resumo.falhas else "sucesso")))

        self._rodar("Baixando vídeos...", tarefa)

    OPCOES_LICENCA = ("Só domínio público / CC", "Todos (tenho certeza)")

    @property
    def memoria_downloads(self) -> MemoriaDownloads:
        if getattr(self, "_memoria_downloads", None) is None:
            self._memoria_downloads = MemoriaDownloads(config.ARQUIVO.parent / "baixados.json")
        return self._memoria_downloads

    def _filtrar_ja_baixados(self, links: list[LinkVideo]) -> list[LinkVideo] | None:
        """Os que já foram baixados antes (mesmo em outra busca, outro dia): pergunta se pula ou baixa de novo.
        Devolve a lista a baixar, ou None se cancelou (ou se não sobrou nada)."""
        ja = [lk for lk in links if self.memoria_downloads.baixado(lk)]
        if not ja:
            return links
        exemplos = "\n".join(f"• {lk.titulo or lk.url} ({texto_quando(self.memoria_downloads.baixado(lk))})"
                              for lk in ja[:5]) + (f"\n… e mais {len(ja) - 5}" if len(ja) > 5 else "")
        pular = f"Pular os {len(ja)} já baixados"
        escolha = self.escolher(
            "Já baixados", f"{len(ja)} de {len(links)} vídeo(s) já foram baixados antes:\n\n{exemplos}\n\n"
            "Pular evita baixar duas vezes. (Para o programa esquecer downloads: botão \"Memória de "
            "downloads...\", embaixo da lista.)", (pular, "Baixar de novo"))
        if escolha is None:
            return None
        if escolha == pular:
            restantes = [lk for lk in links if lk not in ja]
            if not restantes:
                self.mostrar_mensagem("Já baixados", "Todos os escolhidos já foram baixados: nada novo para baixar.",
                                      "info")
                return None
            return restantes
        return links

    PERIODOS_MEMORIA = ((30, "baixados há mais de 30 dias"), (90, "baixados há mais de 90 dias"),
                        (365, "baixados há mais de 1 ano"), (0, "todos (a memória inteira)"))

    @staticmethod
    def _tamanho_curto(tamanho: int) -> str:
        return tamanho_legivel(tamanho) if tamanho >= 1024 ** 2 else f"{max(1, round(tamanho / 1024))} KB" if tamanho else "0 KB"

    def ao_memoria_downloads(self) -> None:
        """Memória de downloads: esquecer os selecionados ou limpar por período (o arquivo cresce com o tempo).
        O que sai da memória volta a ser baixado sem a pergunta "já baixado"; os vídeos no disco não mudam."""
        memoria = self.memoria_downloads
        ids = [i for i in self.tabela.selection() if i.isdigit() and int(i) < len(self.links)]
        selecionados = [self.links[int(i)] for i in ids]
        ja = [lk for lk in selecionados if memoria.baixado(lk)]
        opcoes, itens = [], []
        if ja:
            opcoes.append(("selecionados", 0))
            itens.append(f"Esquecer os {len(ja)} selecionado(s) que já foram baixados")
        for dias, texto in self.PERIODOS_MEMORIA:
            quantos = memoria.quantos_antigos(dias)
            opcoes.append(("periodo", dias))
            itens.append(f"Apagar os {texto}: {quantos} registro(s)")
        n = self.escolher_da_lista(
            "Memória de downloads", f"A memória guarda {len(memoria)} download(s) ({self._tamanho_curto(memoria.tamanho())}) "
            "para avisar \"já baixado\" nas próximas buscas. Apagar só esquece: os vídeos baixados continuam no "
            "disco.", itens, "Apagar")
        if n is None:
            return
        tipo, dias = opcoes[n]
        if tipo == "selecionados":
            saiu = memoria.esquecer(ja)
        else:
            quantos = memoria.quantos_antigos(dias)
            if not quantos:
                self.mostrar_mensagem("Memória de downloads", "Nada nesse período.", "info")
                return
            if not self.perguntar("Memória de downloads", f"Apagar {quantos} registro(s) da memória ("
                                  f"{dict(self.PERIODOS_MEMORIA)[dias]})? Esses vídeos voltam a ser baixados sem a "
                                  "pergunta \"já baixado\". Os arquivos no disco não mudam."):
                return
            saiu = memoria.esquecer_antigos(dias)
        for i, lk in enumerate(self.links):           # a lista na tela acompanha
            if "já baixado" in self.tabela.set(str(i), "status") and not memoria.baixado(lk):
                self.atualizar_situacao(str(i), "", "", rolar=False)
        self._log.info("Memória de downloads: %d registro(s) apagado(s)", saiu)
        self.definir_status(f"Memória de downloads: {saiu} registro(s) apagado(s); ficaram {len(memoria)}.")

    @staticmethod
    def _sem_licenca_aberta(links: list[LinkVideo]) -> list[LinkVideo]:
        return [lk for lk in links if lk.tipo == "archive.org" and not licenca_aberta(lk.licenca)]

    def _filtrar_por_licenca(self, links: list[LinkVideo]) -> list[LinkVideo] | None:
        """Vídeos do archive.org sem domínio público/Creative Commons: pergunta se baixa só os livres ou todos.
        Devolve a lista a baixar, ou None se cancelou (ou se não sobrou nada)."""
        sem_licenca = self._sem_licenca_aberta(links)
        if not sem_licenca:
            return links
        livres = len(links) - len(sem_licenca)
        escolha = self.escolher(
            "Licença dos vídeos",
            f"{len(links)} vídeo(s): {livres} com domínio público ou Creative Commons e {len(sem_licenca)} do "
            "archive.org sem licença aberta (coluna Licença vazia ou outra).\n\n"
            "No archive.org qualquer pessoa pode enviar arquivos: baixe só o que é de domínio público, tem licença "
            "livre (Creative Commons) ou que você tem direito de baixar. Cópias de filmes e séries comerciais "
            "(ex.: \"WEB-DL\" de um streaming) não são.\n\n"
            f"\"{self.OPCOES_LICENCA[0]}\": baixa {livres} e pula os outros.\n"
            f"\"{self.OPCOES_LICENCA[1]}\": você tem certeza de que pode baixar todos os {len(links)}?",
            self.OPCOES_LICENCA)
        if escolha is None:
            return None
        if escolha == self.OPCOES_LICENCA[1]:
            self._log.info("Baixar: %d vídeo(s) sem licença aberta confirmados pela pessoa", len(sem_licenca))
            return links
        fora = {id(lk) for lk in sem_licenca}
        restantes = [lk for lk in links if id(lk) not in fora]
        if not restantes:
            self.mostrar_mensagem("Licença dos vídeos", "Nenhum dos vídeos escolhidos é de domínio público ou "
                                  "Creative Commons: nada foi baixado.", "aviso")
            return None
        return restantes

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

    OPCOES_ROBOTS = ("Ignorar nesta vez", "Ignorar sempre (até fechar o Maestro)", "Respeitar o robots.txt")

    def _confirmar_ignorar_robots(self, opcoes: OpcoesInterface, urls: list[str]) -> bool | None:
        """Com "Ignorar o robots.txt" marcado, confirma a CADA busca/download (como a escolha da licença), a não
        ser que a pessoa tenha dado a confirmação geral ("Ignorar sempre"), que vale até fechar o programa ou
        desmarcar a opção. True = ignorar; False = respeitar; None = Cancelar (não faz nada)."""
        if not opcoes.ignorar_robots:
            self._robots_sempre = False              # desmarcou: a confirmação geral acaba
            return False
        sites = sorted({site_de(u) for u in urls if site_de(u)})
        nomes = ", ".join(sites[:5]) + (f" e mais {len(sites) - 5}" if len(sites) > 5 else "")
        if getattr(self, "_robots_sempre", False):
            self._log.warning("robots.txt IGNORADO (confirmação geral até fechar o Maestro): %s", nomes)
            return True
        protegidos = [s for s in sites if not pode_ignorar_robots(s)]
        escolha = self.escolher(
            "Ignorar o robots.txt?",
            f"A opção \"Ignorar o robots.txt\" está marcada.\n\nSite: {nomes or '(nenhum)'}\n\n"
            "O robots.txt é o aviso do DONO do site dizendo onde programas automáticos podem entrar. Ignore só "
            "em sites seus ou com autorização do dono (testes pessoais).\n\n"
            f"\"{self.OPCOES_ROBOTS[0]}\": só esta busca/download (pergunta de novo na próxima).\n"
            f"\"{self.OPCOES_ROBOTS[1]}\": confirmação geral, em qualquer site, sem perguntar de novo até fechar "
            "o Maestro ou desmarcar a opção.\n"
            f"\"{self.OPCOES_ROBOTS[2]}\": segue as regras do site, como sempre.\n\n"
            "Nos dois \"Ignorar\" as pausas entre os pedidos continuam."
            + (f"\n\n{', '.join(protegidos)}: plataforma protegida, o robots.txt dela é respeitado de qualquer "
               "jeito." if protegidos else ""),
            self.OPCOES_ROBOTS)
        if escolha is None:
            return None
        if escolha == self.OPCOES_ROBOTS[2]:
            return False
        self._robots_sempre = escolha == self.OPCOES_ROBOTS[1]
        self._log.warning("robots.txt IGNORADO %s (confirmado pela pessoa): %s",
                          "até fechar o Maestro" if self._robots_sempre else "nesta vez", nomes)
        return True

    def _novo_trabalho(self, o: OpcoesInterface, ignorar_robots: bool = False) -> Trabalho:
        return Trabalho(espera=o.espera, navegador=o.navegador, visivel=o.visivel, pausar=o.pausar,
                        ignorar_robots=ignorar_robots,
                        perfil=PERFIL_PADRAO, aguardar_usuario=self._aguardar_usuario,
                        parar=self.evento_parar.is_set, sites_sem_robots=set(self.sites_sem_robots),
                        clicar_play=getattr(o, "clicar_play", True))

    def _aguardar_usuario(self, mensagem: str) -> None:
        """Chamado pela thread: pede à janela um aviso e espera o OK do usuário."""
        ok = threading.Event()
        self.fila.put(("aguardar", (mensagem, ok)))
        ok.wait()

    def _explicar_resultado(self, t: Trabalho, links: list[LinkVideo], acao: str = "buscar",
                            perguntar: bool = True) -> None:
        # robots.txt bloqueou páginas de um site comum: pergunta (no fim) se o site é da pessoa. Com a opção
        # "Ignorar o robots.txt" marcada a pergunta já foi feita antes de começar.
        sites = sorted({site_de(u) for u in t.bloqueadas if pode_ignorar_robots(site_de(u))}
                       - self.sites_sem_robots - self._robots_recusados) if perguntar else []
        if sites:
            self.fila.put(("robots_perguntar", (sites, len(t.bloqueadas), bool(links), acao)))
            return
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

    OPCAO_IGNORAR_ROBOTS = "Sim, o site é meu: ignorar o robots.txt"

    def _perguntar_robots(self, sites: list[str], quantas: int, achou: bool, acao: str) -> bool:
        """O robots.txt de um site proibiu páginas: se o site é da pessoa (ou ela tem autorização do dono),
        ignora o robots.txt SÓ desse site, enquanto o programa estiver aberto, e busca de novo. True = ignorou."""
        nomes = ", ".join(sites)
        texto = (f"O robots.txt de {nomes} não deixa robôs entrarem em {quantas} página(s)"
                 + (" (os vídeos achados nas outras já estão na lista)" if achou else "") + ".\n\n"
                 "O robots.txt é um aviso do DONO do site dizendo onde programas automáticos podem entrar. Ignore "
                 "só se o site é SEU ou se o dono autorizou (ex.: testar o seu próprio site).\n\n"
                 f"Ignorar vale só para {nomes} e só enquanto o Maestro estiver aberto. As pausas entre os pedidos "
                 "continuam. Plataformas como YouTube, Instagram e TikTok nunca entram nesta opção.")
        escolha = self.escolher("robots.txt do site", texto, (self.OPCAO_IGNORAR_ROBOTS,),
                                cancelar="Não, respeitar")
        if escolha != self.OPCAO_IGNORAR_ROBOTS:
            self._robots_recusados.update(sites)
            if not achou:
                self.mostrar_mensagem("Acesso não permitido", MENSAGEM_ROBOTS, "aviso")
            return False
        self.sites_sem_robots.update(sites)
        self._log.warning("robots.txt IGNORADO (a pessoa confirmou que o site é dela ou autorizado): %s", nomes)
        if acao == "baixar":
            self._baixar([])
        else:
            self.ao_buscar()
        return True

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
            self._receber_conferencia_canais(dado)
        elif tipo == "tv_programacao":
            self._tv_programacao_pendente = dado            # pergunta depois do "fim"
        elif tipo == "tv_epg_estado":
            self._mostrar_estado_programacao(*dado)
        elif tipo == "tv_coletor_iniciado":
            self._tv_coletor_pendente = dado
        elif tipo == "tv_semanal":                     # conferência semanal dos canais (segundo plano)
            self._fim_conferencia_semanal(dado)
        elif tipo == "bandeja":                        # clique no ícone perto do relógio
            if dado == "abrir":
                self.mostrar_janela()
            elif dado == "sair":
                self.sair_de_vez()
        elif tipo == "versao_consultada":
            self._mostrar_versao_consultada(*dado)
        elif tipo == "lixeira_antiga":
            self._oferecer_limpar_lixeira(dado)
        elif tipo == "atalhos_feitos":                 # atalhos refeitos para esta versão (não refaz de novo)
            tudo = config.carregar()
            tudo.setdefault("instalacao", {})["atalhos_versao"] = dado
            config.salvar(tudo)
        elif tipo == "instalado_fixo":
            self._instalado_fixo_pendente = dado           # depois do "fim"
        elif tipo == "tv_diagnostico":
            self._tv_diagnostico_pendente = dado           # depois do "fim"
        elif tipo == "tv_canais_a_mais":
            self._tv_canais_a_mais_pendente = dado         # pergunta depois do "fim"
        elif tipo == "tv_outros_sintonizadores":
            self._tv_outros_pendente = dado                # pergunta depois do "fim"
        elif tipo == "atualizacao_baixada":
            self._atualizacao_pendente = dado              # pergunta depois do "fim"
        elif tipo == "tmdb_opcoes":
            self._tmdb_opcoes_pendente = dado              # a lista abre depois do "fim"
        elif tipo == "baixar_depois":
            self._baixar_pendente = dado                   # pergunta a licença depois do "fim"
        elif tipo == "traduzir_pendente":
            self._traduzir_pendente = dado                 # pergunta (com o custo) depois do "fim"
        elif tipo == "dublar_pendente":
            self._dublar_pendente = dado                   # pergunta (espaço em disco) depois do "fim"
        elif tipo == "legendar_audio_pendente":
            self._legendar_audio_pendente = dado           # pergunta (tempo e custo) depois do "fim"
        elif tipo == "robots_perguntar":
            self._robots_pendente = dado                   # pergunta depois do "fim" (a janela já está livre)
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
            if getattr(self, "_instalado_fixo_pendente", None):
                instalado, self._instalado_fixo_pendente = self._instalado_fixo_pendente, None
                self.after(50, lambda: self._instalado_fixo(*instalado))
            if getattr(self, "_tv_diagnostico_pendente", None):
                diagnostico, self._tv_diagnostico_pendente = self._tv_diagnostico_pendente, None
                self.after(50, lambda: self._mostrar_diagnostico_tv(*diagnostico))
            if getattr(self, "_tv_canais_a_mais_pendente", None):
                a_mais, self._tv_canais_a_mais_pendente = self._tv_canais_a_mais_pendente, None
                self.after(50, lambda: self._oferecer_limpar_tv(*a_mais))
            if getattr(self, "_tv_programacao_pendente", None):
                prog, self._tv_programacao_pendente = self._tv_programacao_pendente, None
                self.after(50, lambda: self._oferecer_programacao(*prog))
            if getattr(self, "_tv_coletor_pendente", None):
                arq, self._tv_coletor_pendente = self._tv_coletor_pendente, None
                self.after(50, lambda: self._coletor_iniciado(arq))
            if self._tv_outros_pendente:
                outros, self._tv_outros_pendente = self._tv_outros_pendente, None
                self.after(50, lambda: self._oferecer_tirar_sintonizadores(*outros))
            if getattr(self, "_tmdb_opcoes_pendente", None):
                opcoes, self._tmdb_opcoes_pendente = self._tmdb_opcoes_pendente, None
                self.after(50, lambda: self._escolher_opcao_tmdb(*opcoes))
            if self._baixar_pendente:
                lista, self._baixar_pendente = self._baixar_pendente, None
                ignorar, self._ignorar_baixar_depois = getattr(self, "_ignorar_baixar_depois", None), None
                self.after(50, lambda: self._baixar(lista) if ignorar is None else self._baixar(lista, ignorar))
            if getattr(self, "_traduzir_pendente", None):
                traduzir, self._traduzir_pendente = self._traduzir_pendente, None
                self.after(50, lambda: self._confirmar_traducao(*traduzir))
            if getattr(self, "_dublar_pendente", None):
                dublar, self._dublar_pendente = self._dublar_pendente, None
                self.after(50, lambda: self._confirmar_dublagem(*dublar))
            if getattr(self, "_legendar_audio_pendente", None):
                audio, self._legendar_audio_pendente = self._legendar_audio_pendente, None
                self.after(50, lambda: self._confirmar_legendar_audio(*audio))
            if self._robots_pendente:
                robots, self._robots_pendente = self._robots_pendente, None
                self.after(50, lambda: self._perguntar_robots(*robots))
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
    def obter_opcoes(self):
        """As opções da aba Vídeos, com a pasta dos vídeos SEMPRE completa e gravável (e lembrada)."""
        o = super().obter_opcoes()
        segura = pasta_segura(o.pasta, PASTA_PADRAO)
        if segura != o.pasta:
            self._log.warning("Pasta dos vídeos \"%s\" trocada por %s (não dá para gravar lá)", o.pasta, segura)
            self.var_pasta.set(segura)
            o.pasta = segura
        tudo = config.carregar()
        if tudo.get("videos", {}).get("pasta") != segura:          # da próxima vez abre com a mesma pasta
            tudo.setdefault("videos", {})["pasta"] = segura
            config.salvar(tudo)
        return o

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
            if registro := self.memoria_downloads.baixado(l):        # baixado numa busca anterior
                self.atualizar_situacao(str(i), f"já baixado ({texto_quando(registro)})", "ok", rolar=False)

    def _marcar_item(self, link, status: str) -> None:
        """Marca a situação SÓ da linha desse vídeo (antes marcava todas as linhas com o mesmo endereço)."""
        indices = [i for i, l in enumerate(self.links) if l is link] or \
                  [i for i, l in enumerate(self.links) if l.url == getattr(link, "url", link)][:1]
        for i in indices:
            self.atualizar_situacao(str(i), TEXTOS_SITUACAO.get(status, status), status)

    def _link_selecionado(self) -> LinkVideo | None:
        ids = self.selecionados()
        if not ids:
            self.mostrar_mensagem("Nenhum link", "Selecione um vídeo da lista primeiro.", "aviso")
            return None
        foco = self.tabela.focus()                   # a linha clicada por último (com vários marcados)
        return self.links[int(foco if foco in ids else ids[0])]

    # ================================================================== aba Jellyfin
    def ao_previsualizar(self, so=None) -> None:
        """so: só esses arquivos (depois de "Corrigir nome"/"Escolher no TMDB"): analisa de novo apenas eles e
        encaixa na lista que já está na tela, em vez de refazer os 700 (com o TMDB, minutos). Sem prévia
        válida na tela, faz a completa. O Organizar sempre confere tudo de novo na hora de mover."""
        o = self._validar_jellyfin()
        if not o:
            return
        self._salvar_config()
        assinatura = self._assinatura(o)
        if so and self._movimentos_previa and self._previa == assinatura:
            self._previsualizar_alguns(o, assinatura, set(so))
            return

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

    def _previsualizar_alguns(self, o, assinatura, so: set) -> None:
        anteriores = list(self._movimentos_previa)

        def tarefa():
            self._log.info("Pré-visualizando de novo só %d arquivo(s) (o resto da lista fica como está)", len(so))
            parcial = organizar_pasta(o.origem, o.destino, self._catalogo(o), aplicar=False,
                                      incluir_tmdbid=o.incluir_tmdbid, exigir_catalogo=o.exigir_catalogo,
                                      modo=o.modo, limpar_lixo=o.limpar_lixo, apagar_pasta_origem=False,
                                      nomes_episodios=o.nomes_episodios, protegidas=o.pastas_protegidas,
                                      regras=self.regras_de_nome(), ao_analisar=self._avisar_analise,
                                      filtro=lambda v: v in so, parar=self.evento_parar.is_set)
            novos = {m.origem: m for m in parcial if m.status not in ("limpeza", "pasta_apagada")}
            for m in novos.values():
                self._log.info("%s", m)
            movimentos = [novos.get(m.origem, m) for m in anteriores]
            quantos = sum(m.status == "simulado" for m in movimentos)
            sobras = sum(m.status == "limpeza" for m in movimentos)
            self.fila.put(("jf_movimentos", movimentos))
            self.fila.put(("jf_previa", (assinatura, quantos + sobras)))
            self.fila.put(("status_fim", f"Pré-visualização atualizada: {len(novos)} arquivo(s) analisados de novo "
                                         f"(os outros {len(movimentos) - len(novos)} ficaram como estavam). "
                                         f"{quantos} para mover. Nada foi movido."))

        self._rodar(f"Analisando de novo {len(so)} arquivo(s)...", tarefa)

    def _afetados_por(self, alvos) -> set:
        """Os arquivos da prévia que uma regra nova afeta: o próprio arquivo ou tudo dentro da pasta."""
        chaves = [os.path.normcase(os.path.abspath(str(a))) for a in alvos]
        afetados = set()
        for m in self._movimentos_previa:
            if m.status in ("limpeza", "pasta_apagada"):
                continue
            caminho = os.path.normcase(os.path.abspath(str(m.origem)))
            if any(caminho == c or caminho.startswith(c.rstrip("\\/") + os.sep) for c in chaves):
                afetados.add(m.origem)
        return afetados

    # ================================================================== espelhar no Jellyfin (.strm)
    def ao_espelhar_jellyfin(self, indices: list[int] | None = None) -> None:
        """Links da aba Vídeos -> .strm nas bibliotecas de Filmes e Séries da aba Jellyfin
        (+ legendas, pôster, .nfo e scan, como no Organizar). Selecionados; sem seleção, todos.
        `indices`: os links escolhidos pelos botões "Espelhar selecionados/todos" (modo híbrido)."""
        if indices is None:
            indices = [int(i) for i in self.tabela.selection()] or list(range(len(self.links)))
        if not indices:
            self.mostrar_mensagem("Espelhar no Jellyfin", "Busque os vídeos primeiro.", "aviso")
            return
        links = [self.links[i] for i in indices]
        o = self.obter_opcoes_jellyfin()
        self._destinos[self._modo_atual] = self.var_jf_destino.get()
        pasta_filmes, pasta_series = self._destinos.get("Filmes", ""), self._destinos.get("Séries", "")
        tipos = [classificar(l) for l in links]
        filmes, series, comuns = tipos.count("filme"), tipos.count("serie"), tipos.count("outro")
        faltam = [n for n, (qtd, pasta) in (("Filmes", (filmes, pasta_filmes)), ("Séries", (series, pasta_series)))
                  if qtd and not pasta]
        if faltam:
            self.mostrar_mensagem("Espelhar no Jellyfin", f"Escolha a biblioteca de {' e de '.join(faltam)} na aba "
                                  "Jellyfin (troque Filmes/Séries no topo dela) e tente de novo.", "aviso")
            return
        pasta_comuns = ""
        if comuns:                                   # vídeos sem ano nem episódio: pasta própria ou de fora
            pasta_comuns = self._escolher_pasta_videos_comuns(comuns)
            if pasta_comuns is None:
                return
        if not filmes + series and not pasta_comuns:
            self.mostrar_mensagem("Espelhar no Jellyfin", "Nenhum link tem ano (filme) ou temporada/episódio "
                                  "(série) no título, e os vídeos comuns ficaram de fora: nada a espelhar.", "aviso")
            return
        abertos = sum(licenca_aberta(getattr(l, "licenca", "")) for l, t in zip(links, tipos)
                      if t != "outro" or pasta_comuns)
        legendas = f"legendas ({o.idioma}) pela fonte \"{o.fonte_legenda}\"" if o.legendas else "sem legendas"
        escolha = self.escolher(
            "Espelhar no Jellyfin",
            f"{len(links)} link(s){' selecionado(s)' if self.tabela.selection() else ''}: {filmes} filme(s), "
            f"{series} episódio(s), {comuns} vídeo(s) comum(ns) (sem ano/episódio"
            f"{'' if pasta_comuns else ': ficam de fora'}).\n\n"
            f"Filmes: {pasta_filmes or '—'}\nSéries: {pasta_series or '—'}\n"
            f"Vídeos comuns: {pasta_comuns or '— (de fora)'}\n\n"
            "Cada um vira um arquivo .strm com o link: o Jellyfin toca direto do site, sem baixar. Depois: "
            f"{legendas}, pôster/.nfo e scan do Jellyfin.\n\n"
            f"Licença: {abertos} com domínio público ou Creative Commons. Os demais podem ser cópias sem "
            "autorização do dono dos direitos; espelhe só o que você pode assistir legalmente.",
            self.OPCOES_ESPELHO)
        if escolha is None:
            return
        so_abertos = escolha == self.OPCOES_ESPELHO[0]
        # links temporários (assinatura que expira): a pessoa decide se entram
        temporarios = [l.url for l, t in zip(links, tipos) if (t != "outro" or pasta_comuns)
                       and (not so_abertos or licenca_aberta(getattr(l, "licenca", ""))) and eh_link_temporario(l.url)]
        aceitar_temporarios = self._confirmar_temporarios(temporarios) if temporarios else False
        if aceitar_temporarios is None:
            return
        self._salvar_config()

        def tarefa():
            # 1) cada link serve para .strm? (direto, permanente, público) - vários ao mesmo tempo
            candidatos = [l.url for l, t in zip(links, tipos) if (t != "outro" or pasta_comuns)
                          and (not so_abertos or licenca_aberta(getattr(l, "licenca", "")))]
            self._log.info("Conferindo %d link(s) (direto, permanente, público?)", len(candidatos))
            verificacoes = verificar_links(candidatos, parar=self.evento_parar.is_set,
                                           aceitar_temporarios=aceitar_temporarios,
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
                                     o.incluir_tmdbid, o.nomes_episodios, verificacoes, indice,
                                     pasta_outros=pasta_comuns or None)
            aplicar_espelho(itens)
            for item in itens:
                destino = f" -> {item.destino}" if item.destino else ""
                nivel = self._log.error if item.status == "erro" else self._log.info
                nivel("[%s] %s%s%s", item.status, nome_do_link(item.link), destino,
                      f" ({item.detalhe})" if item.detalhe else "")
            self.fila.put(("espelho", [(i, SITUACAO_ESPELHO.get(item.status, (item.status, None)))
                                       for i, item in zip(indices, itens)]))
            criados = [item for item in itens if item.status == "criado"]
            # legendas, pôster e .nfo só para filmes e episódios (o TMDB não conhece um vídeo comum)
            com_metadados = [item for item in criados if item.tipo != "outro"]
            resultados = []
            if com_metadados:
                self._log.info("Legendas, pôster/.nfo e scan para %d item(ns) espelhado(s)", len(com_metadados))
                resultados = self._pos_processar(o, [item.como_item_da_biblioteca() for item in com_metadados],
                                                 [f"espelho-{k}" for k in range(len(com_metadados))], "Espelho",
                                                 legendas=o.legendas, notificar=True)
            elif criados and o.atualizar_jellyfin and o.jellyfin_url and o.jellyfin_api_key:
                try:                                   # só vídeos comuns: basta avisar o Jellyfin
                    atualizar_biblioteca(o.jellyfin_url, o.jellyfin_api_key)
                    self._ultimo_scan = "pedido"
                except ErroJellyfin as erro:
                    self._log.warning("Jellyfin: scan não pedido (%s)", erro)
            baixadas = sum(1 for r in resultados for le in (r.legendas or {"": r.legenda}).values()
                           if le and le.status == "baixada")
            contagem = {s: sum(item.status == s for item in itens) for s in SITUACAO_ESPELHO}
            self.fila.put(("status_fim", f"Espelho: {len(criados)} .strm criado(s), {baixadas} legenda(s)."))
            self.fila.put(("msg", ("Espelho no Jellyfin",
                                   f"Criados: {len(criados)} ({sum(i.tipo == 'filme' for i in criados)} filme(s), "
                                   f"{sum(i.tipo == 'serie' for i in criados)} episódio(s), "
                                   f"{sum(i.tipo == 'outro' for i in criados)} vídeo(s) comum(ns))\n"
                                   f"Já existiam: {contagem['ja_existe'] + contagem['tem_video']}\n"
                                   f"Já estavam no Jellyfin (pulados): {contagem['no_jellyfin']}\n"
                                   f"Sem ano/episódio (de fora): {contagem['ignorado']}\n"
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
    OPCOES_TEMPORARIOS = ("Criar nesta vez", "Sempre criar (até fechar o Maestro)", "Deixar de fora")

    def _confirmar_temporarios(self, urls: list[str]) -> bool | None:
        """Links com assinatura que expira (?expires=, ?token=...): o .strm toca só até expirar. A pessoa decide,
        como na licença: nesta vez, sempre (até fechar o programa) ou de fora. True = criar; False = de fora;
        None = Cancelar (não espelha nada)."""
        if getattr(self, "_temporarios_sempre", False):
            self._log.info("Espelho: %d link(s) temporário(s) aceitos (confirmação geral)", len(urls))
            return True
        exemplo = urls[0] if len(urls[0]) <= 90 else urls[0][:87] + "..."
        escolha = self.escolher(
            "Links temporários",
            f"{len(urls)} link(s) são temporários: têm uma assinatura que expira (ex.: {exemplo}).\n\n"
            "O .strm com um link desses toca só até a assinatura expirar (em horas ou dias, depende do site). "
            "Depois ele para de tocar, e o \"Conferir espelhos\" passa a marcá-lo como quebrado.\n\n"
            f"\"{self.OPCOES_TEMPORARIOS[0]}\": cria os .strm só neste espelhamento (pergunta de novo na próxima).\n"
            f"\"{self.OPCOES_TEMPORARIOS[1]}\": confirmação geral, sem perguntar de novo até fechar o Maestro.\n"
            f"\"{self.OPCOES_TEMPORARIOS[2]}\": como antes, eles não entram.",
            self.OPCOES_TEMPORARIOS)
        if escolha is None:
            return None
        if escolha == self.OPCOES_TEMPORARIOS[2]:
            return False
        self._temporarios_sempre = escolha == self.OPCOES_TEMPORARIOS[1]
        self._log.info("Espelho: %d link(s) temporário(s) aceitos (%s)", len(urls),
                       "até fechar o Maestro" if self._temporarios_sempre else "nesta vez")
        return True

    # ---- vídeos comuns (sem ano nem episódio): uma pasta própria, lembrada entre as vezes
    @property
    def pasta_videos_comuns(self) -> str:
        return str(config.carregar().get("espelho", {}).get("pasta_videos_comuns", "") or "")

    def _guardar_pasta_videos_comuns(self, pasta: str) -> None:
        tudo = config.carregar()
        tudo.setdefault("espelho", {})["pasta_videos_comuns"] = pasta
        config.salvar(tudo)

    def _pedir_pasta(self, titulo: str, inicial: str = "") -> str:
        return filedialog.askdirectory(title=titulo, initialdir=inicial or None, mustexist=False) or ""

    def _escolher_pasta_videos_comuns(self, quantos: int) -> str | None:
        """Onde criar os .strm dos vídeos comuns: a pasta de sempre, outra (escolhida agora e lembrada) ou de
        fora. Devolve a pasta, "" (ficam de fora) ou None (Cancelar)."""
        atual = self.pasta_videos_comuns
        usar, outra, nova, fora = "Usar esta pasta", "Escolher outra pasta...", "Escolher a pasta...", "Deixar de fora"
        texto = (f"{quantos} link(s) sem ano nem temporada/episódio no título: vídeos comuns (aulas, clipes, "
                 "vídeos pessoais...). Eles não vão para Filmes nem Séries: ficam numa pasta própria, com o nome "
                 "do próprio link.\n\n"
                 + (f"Pasta dos vídeos comuns: {atual}\n\n" if atual else "Ainda não há uma pasta para eles.\n\n")
                 + "No Jellyfin, essa pasta precisa ser uma biblioteca do tipo \"Vídeos caseiros e fotos\" (ou "
                 "\"Conteúdo misto\"): Painel > Bibliotecas > Adicionar biblioteca.")
        escolha = self.escolher("Vídeos comuns", texto, (usar, outra, fora) if atual else (nova, fora))
        if escolha is None:
            return None
        if escolha == fora:
            return ""
        if escolha == usar:
            return atual
        pasta = self._pedir_pasta("Pasta dos vídeos comuns (biblioteca do Jellyfin)", atual)
        if not pasta:
            return None                              # fechou a janela de pastas: não faz nada
        self._guardar_pasta_videos_comuns(pasta)
        self._log.info("Pasta dos vídeos comuns: %s", pasta)
        return pasta

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
        self.atualizar_aviso_vigiadas(arrumar=True)
        if problemas := self.problemas_nas_vigiadas(self.pastas_vigiadas()):
            self.mostrar_mensagem("Pastas vigiadas", "Confira as pastas vigiadas:\n\n" + "\n".join(
                f"• {p}" for p in problemas) + "\n\nAs que não existem são ignoradas.", "aviso")
        for aviso in self._bibliotecas_faltando():         # no log; na tela, o estado da vigia já diz
            self._log.warning("Vigia: %s", aviso)
        self._log.info("Vigia ligada: conferindo %s a cada %s min", self.var_jf_origem.get(),
                       int(self.campo_vigia_min.get()))
        self._ciclo_vigia()

    def _agendar_vigia(self) -> None:
        minutos = self.campo_vigia_min.get()
        self._vigia_agendada = self.after(int(minutos * 60_000), self._ciclo_vigia)
        proxima = datetime.now() + timedelta(minutes=minutos)
        faltando = [tipo for tipo in ("Filmes", "Séries") if not ({**self._destinos, self._modo_atual:
                                                                    self.var_jf_destino.get()}).get(tipo)]
        sem_scan = self.var_jf_atualizar.get() and not (self.var_jf_url.get().strip()
                                                        and self.var_jf_chave_jellyfin.get().strip())
        self.definir_estado_vigia(f"Ligada: próxima conferência às {proxima:%H:%M}."
                                  + (f" Sem biblioteca de {' e '.join(faltando)}: esses ficam parados." if faltando
                                     else "")
                                  + (" Sem a chave do Jellyfin: o Jellyfin NÃO é avisado para atualizar a biblioteca."
                                     if sem_scan else ""), True)
        if faltando or sem_scan:                      # aviso em laranja, não no verde de "tudo certo"
            self.lb_estado_vigia.configure(text_color=Tema.AVISO)

    def _bibliotecas_faltando(self) -> list[str]:
        """A vigia separa filmes e séries; sem uma das bibliotecas, aquele tipo fica parado (antes, sem aviso)."""
        destinos = dict(self._destinos)
        destinos[self._modo_atual] = self.var_jf_destino.get()
        artigo = {"Filmes": "os filmes", "Séries": "as séries"}
        return [f"A biblioteca de {tipo} não está escolhida: {artigo[tipo]} ficam onde estão. Escolha-a no modo "
                f"{tipo} (campo \"Biblioteca de {tipo} do Jellyfin\")." for tipo in ("Filmes", "Séries")
                if not destinos.get(tipo)]

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
        fora = frozenset(self._lembrar_desmarcados())   # o que você desmarcou (☐) na prévia: a vigia não mexe

        def conferir():                              # na thread: a janela não trava
            novos = 0
            for pasta in pastas:
                try:
                    previa = organizar_misto(pasta, filmes, series, CatalogoLocal.padrao(), filtro=filtro_prontos(),
                                             protegidas=o.pastas_protegidas, regras=self.regras_de_nome(), fora=fora)
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
        fora = frozenset(self._lembrar_desmarcados())

        def tarefa():
            todos = []
            for pasta in pastas:
                todos += organizar_misto(pasta, filmes, series, self._catalogo(o), filtro=filtro_prontos(),
                                         aplicar=True, incluir_tmdbid=o.incluir_tmdbid,
                                         exigir_catalogo=o.exigir_catalogo, limpar_lixo=o.limpar_lixo,
                                         apagar_pasta_origem=o.apagar_pasta_origem, nomes_episodios=o.nomes_episodios,
                                         protegidas=o.pastas_protegidas, regras=self.regras_de_nome(), fora=fora)
            for m in todos:
                nivel = {"erro": self._log.error, "movido": self._log.info}.get(m.status, self._log.warning)
                nivel("%s", m)
            self.fila.put(("jf_movimentos", todos))
            movidos = [(i, m) for i, m in enumerate(todos) if m.status == "movido"]
            if movidos:                              # legendas, pôster, .nfo, avisos e scan (como no Organizar)
                self._pos_processar(o, [(m, m.destino.stem) for _, m in movidos], [i for i, _ in movidos],
                                    "Vigia", legendas=o.legendas, notificar=True)
            filmes_movidos = sum(1 for _, m in movidos if not m.episodio)
            parados = "".join(f" {tipo}: biblioteca não escolhida, ficaram onde estão." for tipo, pasta in
                              (("Filmes", filmes), ("Séries", series)) if not pasta)
            scan = self._texto_do_scan(getattr(self, "_ultimo_scan", "")) if movidos else ""
            self.fila.put(("status_fim", f"Vigia: {filmes_movidos} filme(s) e {len(movidos) - filmes_movidos} "
                                         f"episódio(s) organizados.{parados}{scan}"))

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
        pastas = [p for p in dict.fromkeys((self._destinos.get("Filmes"), self._destinos.get("Séries"),
                                            self.pasta_videos_comuns)) if p and Path(p).is_dir()]
        canais = carregar_canais(self.arquivo_canais)
        if not pastas and not canais:
            self._log.warning("Conferência automática: escolha as bibliotecas de Filmes/Séries")
            return
        notificador = Notificador(o.discord_webhook, o.telegram_token, o.telegram_chat_id)
        trabalhadores = self._consultas_ao_mesmo_tempo()

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
                with prioridade_baixa():
                    situacoes = conferir_canais(canais, trabalhadores, parar=self.evento_parar.is_set,
                                                ao_progresso=self._progresso_com_velocidade("Conferindo canais ao vivo"))
                fora = [(c, s) for c, s in situacoes if not s.ok]
                self._registrar_canais(situacoes)
                self.fila.put(("canais_conferidos", situacoes))
                linhas += [(f"TV ao vivo/{c.nome}", s.ok, s.detalhe) for c, s in situacoes]
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
        pastas = [p for p in dict.fromkeys((self._destinos.get("Filmes"), self._destinos.get("Séries"),
                                            self.pasta_videos_comuns)) if p and Path(p).is_dir()]
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
        """{pasta: "Filmes"/"Séries"/"Vídeos comuns"} das bibliotecas escolhidas que existem."""
        self._destinos[self._modo_atual] = self.var_jf_destino.get()
        pastas = {}
        for tipo, pasta in (("Filmes", self._destinos.get("Filmes")), ("Séries", self._destinos.get("Séries")),
                            ("Vídeos comuns", self.pasta_videos_comuns)):
            if pasta and Path(pasta).is_dir():
                pastas.setdefault(pasta, tipo)
        return pastas

    def ao_gerenciar_espelhos(self) -> None:
        if not self._bibliotecas():
            self.mostrar_mensagem("Espelhos", "Escolha a biblioteca de Filmes e/ou de Séries (ou espelhe vídeos "
                                  "comuns numa pasta).", "aviso")
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
        # Só o que está MARCADO (☑) e À VISTA: desmarcado ou escondido por um filtro fica onde está
        escondidos = {i for i in self._ordem_jf if not self._visivel_jf(i) and self._categoria_jf.get(i) == "mover"}
        fora = {self._movimentos_previa[int(i)].origem for i in set(self.nao_mover_jf()) | escondidos
                if int(i) < len(self._movimentos_previa)}
        quantos = sum(m.status == "simulado" and m.origem not in fora for m in self._movimentos_previa)
        limpezas = sum(m.status == "limpeza" and m.origem not in fora for m in self._movimentos_previa)
        if not quantos and not limpezas:
            self.mostrar_mensagem("Organizar", "Nenhum arquivo marcado (☑) e à vista para mover. Marque na coluna "
                                  "# (ou \"☑ Mover selecionados\") e confira os filtros (\"Mostrar todos\").", "aviso")
            return
        lixo = sum(len(m.apagar or []) for m in self._movimentos_previa
                   if m.origem not in fora) if o.limpar_lixo else 0
        aviso_lixo = (f"\n\n{lixo} arquivo(s) de lixo (.url, .txt, trailers) serão APAGADOS. "
                      "Isso não tem como desfazer." if lixo else "")
        pastas = [m.pasta_apagar for m in self._movimentos_previa if m.pasta_apagar and m.origem not in fora]
        if pastas:
            aviso_lixo += (f"\n\n{len(pastas)} pasta(s) de torrent serão APAGADAS inteiras, com o que sobrar "
                           "nelas (amostras, prints, .nfo de release...). Isso não tem como desfazer.")
        substituir = ("\n\n\"Substituir o que já existe\" está marcado: legendas, pôster, backdrop e .nfo "
                      "dos itens movidos serão baixados de novo e trocados." if o.sobrescrever else "")
        desmarcados = ""
        if fora:
            partes = [f"{n} {texto}" for n, texto in ((len(self.nao_mover_jf()), "desmarcado(s) (☐)"),
                                                      (len(escondidos - set(self.nao_mover_jf())),
                                                       "escondido(s) pelo filtro")) if n]
            desmarcados = f"\n\n{' e '.join(partes)} ficam onde estão, sem nenhuma alteração."
        if not self.perguntar("Organizar", f"Mover {quantos} arquivo(s) para:\n{o.destino}\n\n"
                              "Nenhum vídeo é sobrescrito, e você pode voltar atrás com 'Desfazer última'."
                              + desmarcados + substituir + aviso_lixo):
            return
        self._salvar_config()
        self._previa = None
        self.liberar_organizar(False)
        self._tmdb_ativo = o.tmdb
        if fora:
            self._log.info("Organizar: %d arquivo(s) desmarcado(s) ficam onde estão", len(fora))

        self._rodar("Organizando...", self._tarefa_organizar(o, fora=frozenset(fora)))

    def _tarefa_organizar(self, o, filtro=None, automatico: bool = False, fora=frozenset()):
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
                                         nomes_episodios=o.nomes_episodios, filtro=filtro, fora=fora,
                                         parar=self.evento_parar.is_set,
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
            scan = self._texto_do_scan(getattr(self, "_ultimo_scan", "")) if movidos else ""
            self.fila.put(("status_fim", f"Organizado: {len(movidos)} movido(s), {legendas} legenda(s).{scan}"))
            if automatico:                       # pasta vigiada: ninguém para clicar em OK
                return
            self.fila.put(("msg", ("Organização concluída",
                                   f"Movidos: {len(movidos)}\nLegendas baixadas: {legendas}\n"
                                   f"Pôster/backdrop/.nfo: {metadados}\nCom erro: {erros}\n"
                                   + (f"Pastas de torrent apagadas: {pastas_apagadas}\n" if pastas_apagadas else "")
                                   + (f"\n{scan.strip()}\n" if scan else "")
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
        padrao = {"legendas": True, "imagens": True, "nfo": True, **config.carregar().get("completar", {}),
                  "substituir": o.sobrescrever}
        escolha = self._pedir_o_que_completar(o.destino, padrao, o.modo == "series")
        if not escolha:
            return
        if escolha["legendas"] and (problema := self._problema_legendas(o)):
            self.mostrar_mensagem("Legendas", problema + "\n\n(Ou desmarque \"Legendas\" e complete só o resto.)", "aviso")
            return
        if (escolha["imagens"] or escolha["nfo"]) and not o.chave_tmdb and not escolha["legendas"]:
            self.mostrar_mensagem("Completar biblioteca", "Imagens e .nfo vêm do TMDB: preencha a chave da API do TMDB "
                                  "(aba Jellyfin, \"Nomes e metadados\").", "aviso")
            return                                     # (com legendas junto: faz as legendas e avisa no log)
        tudo = config.carregar()
        tudo["completar"] = {k: escolha[k] for k in ("legendas", "imagens", "nfo")}   # lembra para a próxima
        config.salvar(tudo)
        o.sobrescrever = escolha["substituir"]
        o.imagens_tmdb, o.gerar_nfo = escolha["imagens"], escolha["nfo"]
        self.var_jf_sobrescrever.set(o.sobrescrever)          # a caixa acompanha a escolha
        self._salvar_config()
        self._previa = None
        self.liberar_organizar(False)
        self._completar(o, Path(o.destino), legendas=escolha["legendas"])

    def _pedir_o_que_completar(self, pasta: str, padrao: dict, series: bool) -> dict | None:
        dialogo = DialogoCompletar(self, pasta, padrao, series)
        self.wait_window(dialogo)
        return dialogo.resultado

    def _completar(self, o, destino: Path, legendas: bool = True) -> None:
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
            sufixo = (f".{idiomas[0]}.srt" + (f"  (+{', '.join(idiomas[1:])})" if len(idiomas) > 1 else "")
                      if legendas else "  (só imagens/.nfo)")
            self.fila.put(("jf_alvos", [(atual, f"{nome}{sufixo}") for atual, (_, nome) in zip(linhas, itens)]))
            tipo = "filme(s)" if o.modo == "filmes" else "episódio(s)"
            self._log.info("Completar biblioteca: %d %s em %s", len(itens), tipo, destino)
            resultados = self._pos_processar(o, itens, list(range(len(itens))), "Completando",
                                             legendas=legendas, notificar=False)
            baixadas = sum(1 for r in resultados for le in (r.legendas or {"": r.legenda}).values()
                           if le and le.status == "baixada")
            metadados = sum(1 for r in resultados if r.metadados and r.metadados.criados)
            series = getattr(self, "_series_feitas", [])
            partes = ([f"{baixadas} legenda(s) baixada(s)"] if legendas else []) + (
                [f"{metadados} filme(s) com pôster/.nfo"] if o.modo == "filmes" and (o.imagens_tmdb or o.gerar_nfo)
                else [f"{sum(len(s.criados) for s in series)} imagem(ns) em {len(series)} série(s)"]
                if o.modo != "filmes" and o.imagens_tmdb else [])
            resumo = ", ".join(partes) or "nada a fazer"
            self.fila.put(("jf_total", (1.0, f"Concluído: {resumo}")))
            self.fila.put(("status_fim", f"Biblioteca completada: {len(itens)} {tipo}; {resumo}."))

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
            resultados = pos_processar(itens, cfg, self._log, ao_item=ao_item, parar=self.evento_parar.is_set)
            self._ultimo_scan = cfg.scan if o.atualizar_jellyfin else "desligado"
            self._series_feitas = cfg.series_feitas
            if cfg.scan == "pedido":
                self._saude_jellyfin = "ok"
            elif cfg.scan.startswith("erro"):
                self._saude_jellyfin = cfg.scan
            return resultados

    @staticmethod
    def _texto_do_scan(scan: str) -> str:
        """Para o resultado da vigia/organizar: o Jellyfin foi avisado para atualizar a biblioteca?"""
        if scan == "pedido":
            return " Jellyfin: biblioteca atualizando (scan pedido)."
        if scan == "sem chave":
            return (" ⚠ Jellyfin: scan NÃO pedido (falta a chave de API; marque \"Lembrar as chaves\" para ela não "
                    "sumir ao reiniciar).")
        if scan.startswith("erro"):
            return f" ⚠ Jellyfin: scan NÃO pedido ({scan[6:]})."
        return ""

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

    # ================================================================== traduzir legendas com IA (Claude)
    def ao_traduzir_legendas(self) -> None:
        """Botão "Traduzir legendas com IA...": acha nas bibliotecas os vídeos que só têm legenda em outro idioma,
        mostra quantos e o custo estimado, e (se a pessoa confirmar) cria 'Nome.pt-BR.srt' com os mesmos horários."""
        o = self.obter_opcoes_jellyfin()
        pastas = list(self._bibliotecas())
        if not pastas:
            self.mostrar_mensagem("Traduzir legendas", "Escolha a biblioteca de Filmes e/ou de Séries.", "aviso")
            return
        if not (o.chave_claude or os.environ.get("ANTHROPIC_API_KEY")):
            self.mostrar_mensagem("Traduzir legendas", "Preencha a chave da API da Anthropic (crie uma em "
                                  "console.anthropic.com > API Keys; o uso é pago por quantidade de texto).", "aviso")
            return
        idioma = o.idioma.split(",")[0].strip() or "pt-BR"
        self._salvar_config()

        def tarefa():
            pendentes = legendas_para_traduzir(*pastas, idioma=idioma)
            self._log.info("Traduzir legendas: %d vídeo(s) com legenda só em outro idioma", len(pendentes))
            self.fila.put(("traduzir_pendente", (pendentes, idioma, o)))

        self._rodar("Procurando legendas para traduzir...", tarefa)

    def _confirmar_traducao(self, pendentes: list, idioma: str, o) -> None:
        if not pendentes:
            self.mostrar_mensagem("Traduzir legendas", f"Nada a traduzir: os vídeos já têm legenda em {idioma} "
                                  "(ou não têm legenda .srt em outro idioma).", "info")
            return
        entrada, saida, custo = estimar_custo(sum(p.caracteres for p in pendentes), sum(p.falas for p in pendentes),
                                              o.modelo_traducao)
        exemplos = "\n".join(f"• {p.origem.name}" for p in pendentes[:5]) + (
            f"\n... e mais {len(pendentes) - 5}" if len(pendentes) > 5 else "")
        valor = f"cerca de US$ {custo:.2f}" if custo is not None else "preço deste modelo desconhecido"
        escolha = self.escolher(
            "Traduzir legendas com IA",
            f"{len(pendentes)} vídeo(s) têm legenda só em outro idioma e nenhuma em {idioma}:\n{exemplos}\n\n"
            f"Modelo: {o.modelo_traducao}\nCusto estimado: {valor} (~{(entrada + saida) // 1000} mil tokens)\n\n"
            f"Cada um vira 'Nome.{idioma}.srt' com os MESMOS horários (a IA recebe só o texto das falas). A legenda "
            "original continua lá e nada é sobrescrito.",
            (f"Traduzir os {len(pendentes)}",))
        if escolha is None:
            return
        self._traduzir(pendentes, idioma, o)

    def _traduzir(self, pendentes: list, idioma: str, o) -> None:
        def tarefa():
            try:
                tradutor = Tradutor(chave=o.chave_claude, modelo=o.modelo_traducao, idioma=idioma)
            except ImportError:
                self.fila.put(("msg", ("Traduzir legendas", "Falta a biblioteca 'anthropic' (pip install anthropic).",
                                       "erro")))
                return
            resultados, total = [], len(pendentes)
            for k, p in enumerate(pendentes):
                if self.evento_parar.is_set():
                    break

                def andamento(feitas, todas, k=k, p=p):
                    fracao = (k + feitas / max(todas, 1)) / total
                    self.fila.put(("jf_analise", (fracao, f"Traduzindo {k + 1} de {total}: {p.video.stem} "
                                                          f"({feitas * 100 // max(todas, 1)}%)")))
                andamento(0, 1)
                r = traduzir_arquivo(p.origem, p.destino, tradutor, titulo=p.video.stem,
                                     parar=self.evento_parar.is_set, ao_progresso=andamento)
                resultados.append(r)
                nivel = self._log.error if r.status == "erro" else self._log.info
                nivel("[%s] %s -> %s%s", r.status, r.origem.name, r.destino.name, f" ({r.detalhe})" if r.detalhe else "")
                if r.status == "erro" and r.detalhe.startswith(("a chave", "sem conexão", "limite", "modelo não")):
                    break                                       # vale para todos: não insiste nos outros
            traduzidas = [r for r in resultados if r.status == "traduzida"]
            erros = [r for r in resultados if r.status == "erro"]
            if traduzidas and o.atualizar_jellyfin and o.jellyfin_url and o.jellyfin_api_key:
                try:
                    atualizar_biblioteca(o.jellyfin_url, o.jellyfin_api_key)
                except ErroJellyfin as erro:
                    self._log.warning("Jellyfin: scan não pedido (%s)", erro)
            custo = tradutor.custo
            texto = (f"Traduzidas: {len(traduzidas)} de {total}\n"
                     f"Já existiam: {sum(r.status == 'ja_existe' for r in resultados)}\n"
                     f"Com erro: {len(erros)}" + (f" (ex.: {erros[0].origem.name}: {erros[0].detalhe})" if erros else "")
                     + (f"\nNão feitas (parou antes): {total - len(resultados)}" if len(resultados) < total else "")
                     + f"\n\nModelo: {tradutor.modelo} · {tradutor.pedidos} pedido(s) · "
                     f"{tradutor.tokens_entrada + tradutor.tokens_saida} tokens"
                     + (f" · custo real ~US$ {custo:.2f}" if custo is not None else ""))
            self.fila.put(("status_fim", f"Legendas traduzidas: {len(traduzidas)} de {total}."))
            self.fila.put(("msg", ("Traduzir legendas", texto, "erro" if erros and not traduzidas else "sucesso")))

        self._rodar(f"Traduzindo {len(pendentes)} legenda(s) com IA...", tarefa)

    # ================================================================== legenda a partir do áudio (Whisper)
    @property
    def pasta_modelos_whisper(self) -> str:
        return str(config.ARQUIVO.parent / "modelos_whisper")

    def ao_legendar_audio(self) -> None:
        """Botão "Criar legenda pelo áudio...": acha os vídeos sem NENHUMA legenda, mostra o tempo de áudio e o custo
        da tradução e, confirmado, o Whisper ouve cada um no PC e o Claude traduz o que não for português."""
        o = self.obter_opcoes_jellyfin()
        pastas = list(self._bibliotecas())
        if not pastas:
            self.mostrar_mensagem("Criar legenda pelo áudio", "Escolha a biblioteca de Filmes e/ou de Séries.", "aviso")
            return
        idioma = o.idioma.split(",")[0].strip() or "pt-BR"
        self._salvar_config()

        def tarefa():
            itens = videos_sem_legenda(*pastas, idioma=idioma)
            self._log.info("Criar legenda pelo áudio: %d vídeo(s) sem nenhuma legenda", len(itens))
            self.fila.put(("legendar_audio_pendente", (itens, idioma, o)))

        self._rodar("Procurando vídeos sem legenda...", tarefa)

    def _confirmar_legendar_audio(self, itens: list, idioma: str, o) -> None:
        if not itens:
            self.mostrar_mensagem("Criar legenda pelo áudio", "Nenhum vídeo sem legenda: todos têm alguma legenda ao "
                                  "lado (as de outro idioma: use \"Traduzir legendas com IA\").", "info")
            return
        horas, letras, falas = estimar_audio(itens)
        traduzir = bool(o.chave_claude or os.environ.get("ANTHROPIC_API_KEY"))
        custo = estimar_custo(letras, falas, o.modelo_traducao)[2] if traduzir else None
        exemplos = "\n".join(f"• {i.video.name}" for i in itens[:5]) + (
            f"\n... e mais {len(itens) - 5}" if len(itens) > 5 else "")
        traducao = (f"Tradução com o Claude ({o.modelo_traducao}), só do que não for {idioma}: no máximo cerca de "
                    f"US$ {custo:.2f}." if custo is not None else
                    f"Tradução com o Claude ({o.modelo_traducao}): preço deste modelo desconhecido." if traduzir else
                    "Sem a chave da Anthropic: fica só a legenda no idioma do áudio (sem tradução).")
        escolha = self.escolher(
            "Criar legenda pelo áudio",
            f"{len(itens)} vídeo(s) sem nenhuma legenda (cerca de {horas:.1f} h de áudio):\n{exemplos}\n\n"
            f"O Whisper (modelo \"{o.modelo_whisper}\") ouve o áudio NO SEU PC: é grátis, mas demora (no processador, "
            "pode levar mais que a duração do vídeo; com a placa de vídeo, bem menos). Na 1ª vez ele baixa o modelo "
            f"(de dezenas de MB a mais de 1 GB).\n\n{traducao}\n\nCada vídeo ganha 'Nome.{idioma}.srt' (e a legenda no "
            "idioma do áudio, ex.: 'Nome.en.srt'). Nada é sobrescrito. O \"Parar\" interrompe entre um trecho e outro.",
            (f"Criar para os {len(itens)}",))
        if escolha is None:
            return
        self._legendar_audio(itens, idioma, o, traduzir)

    @staticmethod
    def _texto_duracao(segundos: float) -> str:
        minutos = max(1, int(round(segundos / 60)))
        return f"{minutos} min" if minutos < 60 else f"{minutos // 60} h {minutos % 60:02d} min"

    def _legendar_audio(self, itens: list, idioma: str, o, traduzir: bool) -> None:
        def tarefa():
            transcritor = Transcritor(modelo=o.modelo_whisper, usar_gpu=o.whisper_gpu,
                                      pasta_modelos=self.pasta_modelos_whisper)
            tradutor = None
            if traduzir:
                try:
                    tradutor = Tradutor(chave=o.chave_claude, modelo=o.modelo_traducao, idioma=idioma)
                except ImportError:
                    self._log.warning("Falta a biblioteca 'anthropic': as legendas ficam sem tradução")
            resultados, total, inicio, avisados = [], len(itens), time.monotonic(), set()
            for k, item in enumerate(itens):
                if self.evento_parar.is_set():
                    break

                def andamento(fracao, k=k, item=item):
                    geral, gasto = (k + fracao) / total, time.monotonic() - inicio
                    resta = f" · faltam ~{self._texto_duracao(gasto / geral - gasto)}" if geral > 0.02 else ""
                    self.fila.put(("jf_analise", (geral, f"Ouvindo {k + 1} de {total}: {item.video.stem} "
                                                         f"({int(fracao * 100)}%){resta}")))
                andamento(0.0)
                r = legendar_pelo_audio(item.video, transcritor, tradutor, idioma, parar=self.evento_parar.is_set,
                                        ao_progresso=andamento)
                resultados.append(r)
                for aviso in set(r.avisos) - avisados:
                    self._log.warning("Whisper: %s", aviso)
                    avisados.add(aviso)
                nivel = self._log.error if r.status == "erro" else self._log.info
                nivel("[%s] %s%s (áudio: %s, %s)", r.status, r.video.name, f" ({r.detalhe})" if r.detalhe else "",
                      r.idioma_audio or "?", self._texto_duracao(r.segundos))
                if r.status == "erro" and r.detalhe.startswith(("não deu para carregar o modelo", "falta a biblioteca",
                                                                "a chave", "sem conexão", "limite", "modelo não")):
                    break                                       # vale para todos: não insiste nos outros
            feitas = [r for r in resultados if r.status in ("criada", "traduzida")]
            if feitas and o.atualizar_jellyfin and o.jellyfin_url and o.jellyfin_api_key:
                try:
                    atualizar_biblioteca(o.jellyfin_url, o.jellyfin_api_key)
                except ErroJellyfin as erro:
                    self._log.warning("Jellyfin: scan não pedido (%s)", erro)
            conta = {s: sum(r.status == s for r in resultados) for s in
                     ("criada", "traduzida", "so_original", "sem_fala", "erro", "ja_existe")}
            erros = [r for r in resultados if r.status == "erro"]
            texto = (f"Legendas em {idioma}: {len(feitas)} de {total}\n"
                     f"   • do áudio já em {idioma}: {conta['criada']}\n   • traduzidas pelo Claude: {conta['traduzida']}\n"
                     + (f"Só no idioma do áudio (sem tradução): {conta['so_original']}\n" if conta["so_original"] else "")
                     + (f"Sem fala reconhecida: {conta['sem_fala']}\n" if conta["sem_fala"] else "")
                     + f"Com erro: {len(erros)}" + (f" (ex.: {erros[0].video.name}: {erros[0].detalhe})" if erros else "")
                     + (f"\nNão feitos (parou antes): {total - len(resultados)}" if len(resultados) < total else "")
                     + f"\n\nTempo: {self._texto_duracao(time.monotonic() - inicio)}"
                     + (f" · Claude: {tradutor.pedidos} pedido(s), custo ~US$ {tradutor.custo:.2f}"
                        if tradutor is not None and tradutor.pedidos and tradutor.custo is not None else "")
                     + "".join(f"\n⚠ {a}" for a in avisados))
            self.fila.put(("status_fim", f"Legendas pelo áudio: {len(feitas)} de {total}."))
            self.fila.put(("msg", ("Criar legenda pelo áudio", texto, "erro" if erros and not feitas else "sucesso")))

        self._rodar(f"Ouvindo {len(itens)} vídeo(s) com o Whisper...", tarefa)

    # ================================================================== dublagem por IA (Piper)
    def ao_dublar(self) -> None:
        """Botão "Dublar filmes...": os filmes com legenda em português e sem áudio em português ganham uma versão
        'Nome - Dublado IA.mkv' com a legenda lida por uma voz sintética (o original não é tocado)."""
        o = self.obter_opcoes_jellyfin()
        filmes = self.destinos_jellyfin()["Filmes"]
        if not filmes or not Path(filmes).is_dir():
            self.mostrar_mensagem("Dublar filmes", "Escolha a biblioteca de Filmes (a dublagem é só para filmes, por "
                                  "enquanto: em séries a versão dublada apareceria como episódio repetido).", "aviso")
            return
        idioma = o.idioma.split(",")[0].strip() or "pt-BR"
        self._salvar_config()

        def tarefa():
            itens = videos_para_dublar(filmes, idioma=idioma)
            self._log.info("Dublar: %d filme(s) com legenda em %s e sem áudio em português", len(itens), idioma)
            self.fila.put(("dublar_pendente", (itens, o)))

        self._rodar("Procurando filmes para dublar...", tarefa)

    def _confirmar_dublagem(self, itens: list, o) -> None:
        if not itens:
            self.mostrar_mensagem("Dublar filmes", "Nenhum filme para dublar: é preciso ter a legenda em português "
                                  "(\"Criar legenda pelo áudio\" ou \"Traduzir legendas\" fazem uma) e não ter "
                                  "áudio em português nem versão dublada.", "info")
            return
        espaco = sum(i.tamanho for i in itens)
        exemplos = "\n".join(f"• {i.video.name} ({i.falas} falas)" for i in itens[:5]) + (
            f"\n... e mais {len(itens) - 5}" if len(itens) > 5 else "")
        escolha = self.escolher(
            "Dublar filmes (voz sintética)",
            f"{len(itens)} filme(s) com legenda em português e sem áudio em português:\n{exemplos}\n\n"
            f"Cada um ganha 'Nome - Dublado IA.mkv': a legenda é lida pela voz \"{o.voz_dublagem}\" (Piper, no seu PC, "
            "grátis) e a voz original fica mais baixa por baixo, no estilo narração de documentário. A boca dos atores "
            "não acompanha. O Jellyfin mostra as duas versões do filme.\n\n"
            f"Espaço em disco: cerca de {tamanho_legivel(espaco)} (o vídeo é copiado, sem perder qualidade). "
            "Na 1ª vez baixa o Piper (~25 MB) e a voz (~60 MB). O arquivo original não é tocado.",
            (f"Dublar os {len(itens)}",))
        if escolha is None:
            return
        self._dublar(itens, o)

    def _dublar(self, itens: list, o) -> None:
        def tarefa():
            pasta = config.ARQUIVO.parent
            try:
                self.fila.put(("jf_analise", (0.0, "Preparando o Piper (só na 1ª vez baixa)...")))
                exe = preparar_piper(pasta / "piper", ao_progresso=lambda f: self.fila.put(
                    ("jf_analise", (f * 0.5, f"Baixando o Piper: {int(f * 100)}%"))))
                modelo = preparar_voz(o.voz_dublagem, pasta / "vozes", ao_progresso=lambda f: self.fila.put(
                    ("jf_analise", (0.5 + f * 0.5, f"Baixando a voz \"{o.voz_dublagem}\": {int(f * 100)}%"))))
            except ErroDublagem as erro:
                self.fila.put(("msg", ("Dublar filmes", f"Não deu para preparar a voz: {erro}", "erro")))
                return
            motor, resultados, total, inicio = MotorPiper(exe, modelo), [], len(itens), time.monotonic()
            for k, item in enumerate(itens):
                if self.evento_parar.is_set():
                    break

                def andamento(fracao, k=k, item=item):
                    geral = (k + fracao) / total
                    etapa = "lendo as falas" if fracao < 0.6 else "juntando ao vídeo"
                    self.fila.put(("jf_analise", (geral, f"Dublando {k + 1} de {total}: {item.video.stem} – {etapa} "
                                                         f"({int(fracao * 100)}%)")))
                r = dublar_video(item.video, item.legenda, motor, parar=self.evento_parar.is_set,
                                 ao_progresso=andamento)
                resultados.append(r)
                (self._log.error if r.status == "erro" else self._log.info)(
                    "[%s] %s%s (%d falas, %d aceleradas, %d cortadas)", r.status, r.video.name,
                    f" ({r.detalhe})" if r.detalhe else "", r.falas, r.aceleradas, r.cortadas)
            feitos = [r for r in resultados if r.status == "dublado"]
            erros = [r for r in resultados if r.status == "erro"]
            if feitos and o.atualizar_jellyfin and o.jellyfin_url and o.jellyfin_api_key:
                try:
                    atualizar_biblioteca(o.jellyfin_url, o.jellyfin_api_key)
                except ErroJellyfin as erro:
                    self._log.warning("Jellyfin: scan não pedido (%s)", erro)
            texto = (f"Dublados: {len(feitos)} de {total}\nCom erro: {len(erros)}"
                     + (f" (ex.: {erros[0].video.name}: {erros[0].detalhe})" if erros else "")
                     + (f"\nNão feitos (parou antes): {total - len(resultados)}" if len(resultados) < total else "")
                     + f"\n\nTempo: {self._texto_duracao(time.monotonic() - inicio)}"
                     + ("\n\nNo Jellyfin, abra o filme e escolha a versão \"Dublado IA\"." if feitos else ""))
            self.fila.put(("status_fim", f"Dublagem: {len(feitos)} de {total} filme(s)."))
            self.fila.put(("msg", ("Dublar filmes", texto, "erro" if erros and not feitos else "sucesso")))

        self._rodar(f"Dublando {len(itens)} filme(s) com voz sintética...", tarefa)

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
                self._saude_jellyfin = "ok"
                self._log.info("Jellyfin: conectado a %s", servidor)
                self.fila.put(("msg", ("Jellyfin conectado", f"Tudo certo: {servidor}.", "sucesso")))
            except ErroJellyfin as erro:
                self._saude_jellyfin = f"erro: {erro}"
                self._log.warning("Jellyfin: %s", erro)
                self.fila.put(("msg", ("Jellyfin", str(erro).capitalize() + ".", "erro")))

        self._rodar("Testando o Jellyfin...", tarefa)

    def ao_atualizar_jellyfin_agora(self) -> None:
        """Pede ao Jellyfin para escanear as bibliotecas AGORA (o mesmo pedido do fim do Organizar e da vigia)."""
        o = self.obter_opcoes_jellyfin()
        if not (o.jellyfin_url and o.jellyfin_api_key):
            self.mostrar_mensagem("Jellyfin", "Preencha o endereço e a chave de API do Jellyfin (Painel > Avançado > "
                                  "Chaves de API).", "aviso")
            return

        def tarefa():
            from jellyfin_tools.servidor_jellyfin import escanear_e_conferir, texto_do_scan_conferido
            try:
                r = escanear_e_conferir(o.jellyfin_url, o.jellyfin_api_key, parar=self.evento_parar.is_set,
                                        ao_andamento=lambda pct: self._avisar_analise(
                                            pct / 100, f"Jellyfin escaneando a biblioteca: {pct:.0f}%"))
            except ErroJellyfin as erro:
                self.fila.put(("msg", ("Jellyfin", str(erro).capitalize() + ".", "erro")))
                return
            texto = texto_do_scan_conferido(r)
            self._log.info("Atualizar a biblioteca: %s", texto.replace("\n", " "))
            self.fila.put(("status_fim", texto.split("\n")[0]))
            self.fila.put(("msg", ("Jellyfin", texto, "erro" if r["status"] in ("Failed", "Aborted") else
                                   "sucesso" if r["terminou"] else "info")))

        self._rodar("Jellyfin: escaneando a biblioteca e conferindo (pode levar alguns minutos)...", tarefa)

    def ao_testar_avisos(self) -> None:
        o = self.obter_opcoes_jellyfin()
        notificador = Notificador(o.discord_webhook, o.telegram_token, o.telegram_chat_id)
        if not notificador.ativo:
            self.mostrar_mensagem("Avisos", "Preencha o webhook do Discord e/ou o token e o Chat ID do Telegram.",
                                  "aviso")
            return

        def tarefa():
            ok = notificador.enviar(discord="✅ **Teste do Maestro:** os avisos estão funcionando.",
                                    telegram="✅ <b>Teste do Maestro:</b> os avisos estão funcionando.")
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
        self.ao_previsualizar(so=self._afetados_por(alvos))           # só os afetados (não os 700)

    def _nome_do_arquivo(self, video, tipo: str) -> str:
        """O nome que veio no arquivo (sem regra): 'Juni Lee S01E04.mkv' -> 'Juni Lee'."""
        if tipo == "serie":
            ep = episodio_do_video(video)
            return ep.serie if ep else (serie_da_pasta(video.parent.name) or ("",))[0]
        return extrair_titulo_e_ano(video.name).titulo

    def ao_escolher_no_tmdb(self) -> None:
        """Nome repetido no TMDB ('Tom and Jerry' de 1940, 2014 e 2023) ou nome curto/errado no arquivo ('Juni
        Lee' = 'A Vida e Aventuras de Juniper Lee'): lista as opções, dá para PROCURAR outro nome ali mesmo, e
        a escolha vale para TODOS os arquivos da prévia com o mesmo nome (não só o selecionado). Fica guardada
        como regra e só esses arquivos são analisados de novo."""
        if self.trabalhando:
            return
        o = self.obter_opcoes_jellyfin()
        ids = [int(i) for i in self.tabela_jf.selection() if i.isdigit()]
        movimentos = [self._movimentos_previa[i] for i in ids if 0 <= i < len(self._movimentos_previa)]
        movimentos = [m for m in movimentos if m.status not in ("limpeza", "pasta_apagada")]
        if not movimentos:
            self.mostrar_mensagem("Escolher no TMDB", "Pré-visualize e clique no arquivo (ou episódio) cuja série/filme "
                                  "veio errada. Os outros com o mesmo nome entram juntos.", "aviso")
            return
        if not o.chave_tmdb:
            self.mostrar_mensagem("Escolher no TMDB", "Preencha a chave da API do TMDB (aba Jellyfin, \"Nomes e "
                                  "metadados\") para ver as opções.", "aviso")
            return
        tipo = "serie" if o.modo == "series" else "filme"
        nomes = {normalizar(self._nome_do_arquivo(m.origem, tipo)) for m in movimentos} - {""}
        primeiro = movimentos[0].origem
        regra = regra_para(primeiro, self.regras_de_nome(), tipo)
        termo = (regra.titulo if regra else "") or self._nome_do_arquivo(primeiro, tipo)
        if not termo:
            self.mostrar_mensagem("Escolher no TMDB", "Não achei um nome para procurar: use \"Corrigir nome...\".",
                                  "aviso")
            return
        # os outros arquivos da prévia com o MESMO nome (ex.: todos os "Juni Lee", em qualquer pasta)
        validos = [m for m in self._movimentos_previa if m.status not in ("limpeza", "pasta_apagada")]
        nome_de = {m.origem: normalizar(self._nome_do_arquivo(m.origem, tipo)) for m in validos}
        escolhidos = {m.origem for m in movimentos} | {v for v, n in nome_de.items() if n and n in nomes}
        raizes = {Path(r) for r in [o.origem, o.destino, *self.pastas_vigiadas()] if r}
        alvos = self._alvos_da_escolha(escolhidos, nome_de, tipo, raizes)
        atual = getattr(movimentos[0].filme, "tmdb_id", None)
        chave = o.chave_tmdb

        def tarefa():
            try:
                opcoes = CatalogoTMDB(chave).opcoes(termo, tipo)
            except ErroCatalogo as erro:
                self.fila.put(("msg", ("Escolher no TMDB", f"Não deu para consultar o TMDB: {erro}", "erro")))
                return
            self.fila.put(("tmdb_opcoes", (opcoes, alvos, tipo, termo, atual, regra.temporada if regra else None,
                                           chave, len(escolhidos))))
            self.fila.put(("status_fim", f"TMDB: {len(opcoes)} opção(ões) para \"{termo}\"."))

        self._rodar(f"Procurando \"{termo}\" no TMDB...", tarefa)

    @staticmethod
    def _alvos_da_escolha(arquivos: set, nome_de: dict, tipo: str, raizes=frozenset()) -> list:
        """Onde guardar a escolha: a PASTA, se todos os vídeos dela na prévia têm o mesmo nome (vale também para
        episódios que chegarem depois); senão cada ARQUIVO (pasta "DESENHOS" com séries misturadas: a escolha
        não pode valer para as outras séries). A pasta de origem (ou uma vigiada/biblioteca) nunca: ali entram
        séries novas o tempo todo."""
        if tipo != "serie":
            return sorted(arquivos)
        raizes = {os.path.normcase(os.path.abspath(str(r))) for r in raizes}
        alvos = []
        for pasta in sorted({v.parent for v in arquivos}):
            da_pasta = [v for v in nome_de if v.parent == pasta]
            if os.path.normcase(os.path.abspath(str(pasta))) not in raizes and all(v in arquivos for v in da_pasta):
                alvos.append(pasta)
            else:
                alvos += sorted(v for v in da_pasta if v in arquivos)
        return alvos

    @staticmethod
    def _itens_tmdb(opcoes, atual) -> list[str]:
        itens = []
        for op in opcoes:
            original = f"  ·  original: {op['original']}" if op["original"] and op["original"] != op["titulo"] else ""
            itens.append(f"{op['titulo']} ({op['ano']}){original}" + ("   ← a de agora" if op["tmdb_id"] == atual
                                                                       else "")
                         + (f"   —   {op['resumo'][:70]}…" if op["resumo"] else ""))
        return itens

    def _escolher_opcao_tmdb(self, opcoes, alvos, tipo, termo, atual, temporada, chave="", arquivos=0) -> None:
        estado = {"opcoes": list(opcoes)}

        def procurar(texto: str) -> list[str]:          # roda numa thread (o campo "Procurar" da lista)
            estado["opcoes"] = CatalogoTMDB(chave).opcoes(texto.strip(), tipo) if texto.strip() else []
            return self._itens_tmdb(estado["opcoes"], atual)

        pastas = sum(1 for a in alvos if Path(a).suffix == "")
        onde = (f"{arquivos} arquivo(s) com \"{termo}\" no nome" + (f" ({pastas} pasta(s))" if pastas else ""))
        marcado = next((n for n, op in enumerate(opcoes) if op["tmdb_id"] == atual), None)
        texto = (f"\"{termo}\": {len(opcoes)} opção(ões) no TMDB." if opcoes else
                 f"O TMDB não achou nada com \"{termo}\". Digite outro nome (ex.: o nome completo) e clique em "
                 "Procurar.") + f"\nA escolha vale para {onde}; só eles são analisados de novo."
        n = self.escolher_da_lista("Escolher no TMDB", texto, self._itens_tmdb(opcoes, atual), "Usar esta", marcado,
                                   procurar=procurar if chave else None, termo=termo)
        if n is None or n >= len(estado["opcoes"]):
            return
        escolhida = estado["opcoes"][n]
        for alvo in alvos:
            nova = RegraNome(str(alvo), tipo, escolhida["titulo"], escolhida["ano"], temporada if tipo == "serie" else None)
            adicionar_regra(self.arquivo_regras, nova)
            self._log.info("Escolhido no TMDB: %s -> %s (id %s)", alvo, nova.descricao(), escolhida["tmdb_id"])
        self.ao_previsualizar(so=self._afetados_por(alvos))

    def ao_nao_identificados(self) -> None:
        """Os não identificados da prévia juntos por pasta; um "Corrigir nome" por pasta resolve o grupo todo."""
        grupos = agrupar_nao_identificados(self._movimentos_previa)
        if not grupos:
            self.mostrar_mensagem("Não identificados", "Nenhum não identificado na pré-visualização (pré-visualize "
                                  "primeiro).", "info")
            return
        linhas = []
        for pasta, indices in grupos:
            primeiro = self._movimentos_previa[indices[0]]
            motivo = (primeiro.detalhe or "").split(":")[0][:60]
            linhas.append((str(pasta), len(indices), motivo, primeiro.origem.name))

        def selecionar(posicoes) -> list[str]:
            iids = [str(i) for n in posicoes for i in grupos[n][1]]
            existentes = [i for i in iids if self.tabela_jf.exists(i)]
            self.tabela_jf.selection_set(existentes)
            if existentes:
                self.tabela_jf.see(existentes[0])
            return existentes

        def corrigir(posicoes) -> None:
            if selecionar(posicoes):
                self.janela_nao_identificados.destroy()
                self.ao_corrigir_nome()

        self.janela_nao_identificados = JanelaNaoIdentificados(self, linhas, {"corrigir": corrigir,
                                                                             "mostrar": selecionar})

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
        # o mais recente entre a biblioteca da aba e a pasta dos vídeos comuns (espelho só de vídeos comuns)
        logs = [lg for pasta in (o.destino, self.pasta_videos_comuns)
                if pasta and Path(pasta).is_dir() and (lg := ultimo_log(pasta))]
        log = max(logs, key=lambda lg: lg.name) if logs else None
        if not log:
            self.mostrar_mensagem("Nada para desfazer", f"Não há organização registrada em:\n{o.destino}", "info")
            return
        todos = self._logs_do_mesmo_espelhamento(log)          # um espelho grava 1 log por pasta: desfaz todos
        if not self.perguntar("Desfazer", "Devolver os arquivos da última organização para onde estavam?\n\n"
                              "Legendas baixadas depois continuam na biblioteca."):
            return
        self._previa = None
        self.liberar_organizar(False)

        def tarefa():
            mensagens = []
            for um in todos:
                self._log.info("Desfazendo: %s", um)
                mensagens += desfazer(um)
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

    def _logs_do_mesmo_espelhamento(self, log: Path) -> list[Path]:
        """O log escolhido e, se ele é de um espelho, os logs do MESMO espelhamento nas outras bibliotecas
        (Filmes, Séries, vídeos comuns): o espelho de uma lista mista cria um log em cada uma."""
        try:
            marca = json.loads(log.read_text(encoding="utf-8")).get("espelhamento")
        except (OSError, ValueError, AttributeError):
            marca = None
        if not marca:
            return [log]
        todos = [log]
        for pasta in self._bibliotecas():
            outro = ultimo_log(pasta)
            if outro is None or outro.resolve() in {t.resolve() for t in todos}:
                continue
            try:
                if json.loads(outro.read_text(encoding="utf-8")).get("espelhamento") == marca:
                    todos.append(outro)
            except (OSError, ValueError, AttributeError):
                pass
        return todos

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
        return automacao.problema_legendas(o)

    def _catalogo(self, o):
        return automacao.catalogo(o)

    def _provedores(self, o):
        return automacao.provedores(o)

    RE_PASTA_TEMPORADA = re.compile(r"^(season|temporada|s)\s*\d+$", re.IGNORECASE)

    def _pasta_para_proteger(self, origem: Path) -> Path:
        """A pasta do vídeo; se for de temporada ("Season 1", "Temporada 2", "S01"), a da série."""
        pasta = origem.parent
        return pasta.parent if self.RE_PASTA_TEMPORADA.match(pasta.name.strip()) else pasta

    def ao_proteger_pasta_jf(self) -> None:
        """Põe a pasta das linhas selecionadas em "Pastas protegidas": o organizador nunca mais mexe nela
        (nem a pasta vigiada). Na prévia atual, os arquivos dela ficam desmarcados (☐)."""
        ids = [i for i in self.tabela_jf.selection() if int(i) < len(self._movimentos_previa)]
        if not ids:
            self.mostrar_mensagem("Proteger a pasta", "Selecione na lista um arquivo da pasta que não deve ser "
                                  "alterada (Ctrl+clique para várias) e clique de novo.", "aviso")
            return
        pastas = list(dict.fromkeys(self._pasta_para_proteger(self._movimentos_previa[int(i)].origem) for i in ids))
        if not self.perguntar("Proteger a pasta", "O organizador (e a pasta vigiada) nunca vai mexer em:\n\n"
                              + "\n".join(f"• {p}" for p in pastas[:15])
                              + (f"\n... e mais {len(pastas) - 15}" if len(pastas) > 15 else "")
                              + "\n\nPara voltar a organizar, apague a linha em \"Pastas protegidas\" (aba Jellyfin, "
                              "lado esquerdo).\n\nProteger?"):
            return
        self.definir_pastas_protegidas(self.pastas_protegidas() + [str(p) for p in pastas
                                                                     if str(p) not in self.pastas_protegidas()])
        self._salvar_config()
        dentro = [str(i) for i, m in enumerate(self._movimentos_previa)
                  if any(p == m.origem.parent or p in m.origem.parents for p in pastas)]
        self.marcar_mover_jf(dentro, False)
        self._log.info("Pastas protegidas: %s", ", ".join(map(str, pastas)))
        self.definir_status(f"{len(pastas)} pasta(s) protegida(s): {len(dentro)} arquivo(s) ficam onde estão.")

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

    def _lembrar_desmarcados(self) -> set:
        """Os ☐ de agora (pelo caminho do arquivo) + os lembrados de antes que nem apareceram nesta lista.
        Um que você marcou de novo (☑) é esquecido."""
        anteriores = getattr(self, "_desmarcados_lembrados", set())
        previa = getattr(self, "_movimentos_previa", [])
        # só as linhas "vai mover" que estão na tabela (com o Relatório na tela, por exemplo, não há nenhuma)
        na_tela = {previa[int(i)].origem for i in self._ordem_jf
                   if self._categoria_jf.get(i) == "mover" and int(i) < len(previa)}
        agora = {previa[int(i)].origem for i in self.nao_mover_jf() if int(i) < len(previa)}
        self._desmarcados_lembrados = (anteriores - na_tela) | agora
        return self._desmarcados_lembrados

    def limpar_tabela_jf(self) -> None:
        if getattr(self, "_movimentos_previa", None) is not None and hasattr(self, "_ordem_jf"):
            self._lembrar_desmarcados()               # trocar de modo, Relatório...: os ☐ não se perdem
        super().limpar_tabela_jf()

    def _mostrar_movimentos(self, movimentos) -> None:
        lembrados = self._lembrar_desmarcados()       # Pré-visualizar de novo não volta tudo para ☑
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
        if lembrados:
            self.marcar_mover_jf([str(i) for i, m in enumerate(movimentos) if m.origem in lembrados], False)

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
        pasta_videos = config.carregar().get("videos", {}).get("pasta")
        if pasta_videos:                              # a pasta dos vídeos que você usou da última vez
            self.var_pasta.set(pasta_segura(pasta_videos, PASTA_PADRAO))
        dados = config.carregar().get("jellyfin", {})
        dados.setdefault("chave_tmdb", os.environ.get("TMDB_API_KEY", ""))
        dados.setdefault("chave_opensubtitles", os.environ.get("OPENSUBTITLES_API_KEY", ""))
        dados.setdefault("chave_subdl", os.environ.get("SUBDL_API_KEY", ""))
        for chave, variavel in (("jellyfin_url", "JELLYFIN_URL"), ("jellyfin_api_key", "JELLYFIN_API_KEY"),
                                ("discord_webhook", "DISCORD_WEBHOOK_URL"), ("telegram_token", "TELEGRAM_BOT_TOKEN"),
                                ("telegram_chat_id", "TELEGRAM_CHAT_ID")):
            dados.setdefault(chave, os.environ.get(variavel, ""))
        dados.setdefault("origem", PASTA_PADRAO)
        if dados.get("origem"):                       # salva quando o programa abria pelo Windows (System32)
            dados["origem"] = pasta_segura(dados["origem"], PASTA_PADRAO)
        self.definir_opcoes_jellyfin(dados)
        try:                                  # "Iniciar com o Windows" apontando para um .exe antigo/apagado? conserta
            if atualizacao.pode_instalar_sozinho() and inicializacao.corrigir_se_preciso(instalacao.executavel_fixo()):
                self._log.info("Iniciar com o Windows: caminho corrigido para %s", inicializacao.comando_registrado())
        except OSError as erro:
            self._log.warning("Iniciar com o Windows: não deu para conferir (%s)", erro)
        self.var_jf_iniciar_windows.set(inicializacao.ativo())    # o que vale é o registro do Windows
        if self.var_jf_vigiar.get():                 # ficou ligada da última vez: volta a vigiar
            self.after(3000, self.ao_alternar_vigia)
        self.definir_estado_conferencia(self._texto_ultima_conferencia())
        self._conferencia_agendada = self.after(60_000, self._ciclo_conferencia)
        self._mostrar_pasta_programa()
        self._ciclo_saude()
        if not os.environ.get("VIDEOSCRAPER_SEM_ATUALIZACAO"):
            self.after(8000, self._conferir_lixeira)      # .organizador\removidos com mais de 30 dias?
            self.after(4000, self._ciclo_versao)          # ao abrir e depois a cada 6 horas (programa aberto)
            self.after(2500, self._conferir_instalacao)   # .exe fora do lugar fixo? oferece instalar

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

    # ================================================================== Windows: iniciar junto e ícone no relógio
    def ao_alternar_inicializacao(self) -> None:
        ligar = self.var_jf_iniciar_windows.get()
        no_lugar_fixo = atualizacao.pode_instalar_sozinho() and instalacao.esta_na_pasta_fixa(atualizacao.pasta_do_programa())
        try:
            inicializacao.ativar(ligar, executavel=instalacao.executavel_fixo() if no_lugar_fixo else None)
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
                                            f"Maestro {atualizacao.versao_atual()}")
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

    # ================================================================== painel de saúde (uma linha no topo)
    def itens_saude(self) -> list[tuple[str, bool | None]]:
        """O que está certo (True), o que falta (False) e o que é só informação (None)."""
        destinos = dict(self._destinos)
        destinos[self._modo_atual] = self.var_jf_destino.get()
        itens: list[tuple[str, bool | None]] = []
        for tipo in ("Filmes", "Séries"):
            pasta = destinos.get(tipo)
            if not pasta:
                itens.append((f"{tipo}: biblioteca não escolhida", False))
            elif not Path(pasta).is_dir():
                itens.append((f"{tipo}: pasta não encontrada", False))
            else:
                itens.append((tipo, True))
        jellyfin = getattr(self, "_saude_jellyfin", "")
        if not (self.var_jf_url.get().strip() and self.var_jf_chave_jellyfin.get().strip()):
            itens.append(("Jellyfin: sem a chave de API", False))
        elif jellyfin.startswith("erro"):
            itens.append((f"Jellyfin: {jellyfin[6:][:60]}", False))
        else:
            itens.append(("Jellyfin" + (" (conectado)" if jellyfin == "ok" else ""), True))
        if item_tv := self.item_saude_tv():
            itens.append(item_tv)
        if item_coletor := self.item_saude_coletor():
            itens.append(item_coletor)
        itens.append(("● Vigia ligada" if self.var_jf_vigiar.get() else "○ Vigia desligada", None))
        if atualizacao.pode_instalar_sozinho():
            fixo = instalacao.esta_na_pasta_fixa(atualizacao.pasta_do_programa())
            itens.append(("Lugar fixo" if fixo else "Fora do lugar fixo", fixo))
        atual, publicada = atualizacao.versao_atual(), getattr(self, "_versao_publicada", "")
        if publicada and atualizacao.numeros(publicada) > atualizacao.numeros(atual):
            itens.append((f"Versão {atual}: a {publicada} já saiu", False))
        else:
            itens.append((f"Versão {atual}" + (" (a mais nova)" if publicada else ""), True))
        return itens

    def _ciclo_saude(self) -> None:
        try:
            self.definir_saude(self.itens_saude())
        except tk.TclError:
            return
        self.conferir_saude_tv()                      # a cada 30 min, em segundo plano
        self.conferir_saude_coletor()                 # o coletor de programação (Docker), também a cada 30 min
        if not os.environ.get("VIDEOSCRAPER_SEM_ATUALIZACAO"):
            self.conferencia_semanal_tv()             # opção "Conferir sozinho toda semana" (TV ao vivo)
            if not getattr(self, "_guia_renovado", False):  # uma vez por abertura (e o arquivo vale 30 dias)
                self._guia_renovado = True
                self.renovar_guia_categorias()
        self.after(15_000, self._ciclo_saude)

    # ================================================================== lixeira (.organizador\removidos)
    def _raizes_da_lixeira(self) -> list[str]:
        destinos = dict(self._destinos)
        destinos[self._modo_atual] = self.var_jf_destino.get()
        raizes = [destinos.get("Filmes"), destinos.get("Séries"), self.var_jf_origem.get(), *self.pastas_vigiadas()]
        return [r for r in dict.fromkeys(r for r in raizes if r) if Path(r).is_dir()]

    def _conferir_lixeira(self, sempre: bool = False) -> None:
        """No máximo uma vez por semana: lotes em .organizador\removidos com mais de 30 dias -> pergunta se apaga."""
        dados = config.carregar().get("lixeira", {})
        if not sempre and (dados.get("nao_perguntar") or
                           (dados.get("perguntado") and
                            datetime.now() - datetime.fromisoformat(dados["perguntado"]) < timedelta(days=7))):
            return
        raizes = self._raizes_da_lixeira()

        def procurar():
            lotes = lotes_antigos(raizes)
            if lotes:
                self.fila.put(("lixeira_antiga", lotes))
            elif sempre:
                self.fila.put(("msg", ("Lixeira", "Nada com mais de 30 dias em .organizador\\removidos.", "info")))
        threading.Thread(target=procurar, daemon=True).start()

    def _oferecer_limpar_lixeira(self, lotes) -> None:
        if self.trabalhando:
            self.after(60_000, lambda: self._oferecer_limpar_lixeira(lotes))
            return
        tudo = config.carregar()
        tudo.setdefault("lixeira", {})["perguntado"] = datetime.now().isoformat(timespec="seconds")
        config.salvar(tudo)
        total = sum(lote.tamanho for lote in lotes)
        lista = "\n".join(f"• {lote.pasta}  ({lote.data:%d/%m/%Y}, {tamanho_legivel(lote.tamanho)})" for lote in lotes[:6])
        resto = f"\n… e mais {len(lotes) - 6}" if len(lotes) > 6 else ""
        escolha = self.escolher(
            "Lixeira do organizador",
            f"{len(lotes)} lote(s) em .organizador\\removidos têm mais de 30 dias ({tamanho_legivel(total)}). São as "
            "cópias piores dos conflitos e os espelhos que você removeu.\n\n" + lista + resto +
            "\n\nApagar de vez libera o espaço; depois disso o \"Desfazer\" desses lotes não funciona mais.",
            ("Apagar de vez", "Não perguntar de novo"), cancelar="Agora não")
        if escolha == "Não perguntar de novo":
            tudo = config.carregar()
            tudo.setdefault("lixeira", {})["nao_perguntar"] = True
            config.salvar(tudo)
        elif escolha == "Apagar de vez":
            def tarefa():
                apagados, erros = apagar_lotes(lotes)
                for erro in erros:
                    self._log.warning("Lixeira: %s", erro)
                self._log.info("Lixeira: %d lote(s) apagado(s) (%s)", apagados, tamanho_legivel(total))
                self.fila.put(("status_fim", f"Lixeira: {apagados} lote(s) apagado(s), {tamanho_legivel(total)} "
                                             "liberados." + (f" {len(erros)} com erro (veja o log)." if erros else "")))
            self._rodar("Apagando a lixeira antiga...", tarefa)

    # ================================================================== lugar fixo do programa e atalhos
    def _mostrar_pasta_programa(self) -> None:
        """Na aba Jellyfin: onde o programa está. O botão "Instalar no lugar fixo" só aparece no .exe do Windows
        rodando de fora do lugar fixo (ex.: da pasta Downloads)."""
        pasta = atualizacao.pasta_do_programa()
        fixo = instalacao.esta_na_pasta_fixa(pasta)
        self.lb_pasta_programa.configure(text=f"Programa em: {pasta}" + ("  (lugar fixo ✓)" if fixo else ""))
        if atualizacao.pode_instalar_sozinho() and not fixo:
            self.bt_instalar_fixo.pack(anchor="w", padx=18, pady=(2, 6), after=self.bt_abrir_pasta_programa)
        else:
            self.bt_instalar_fixo.pack_forget()

    def ao_abrir_pasta_programa(self) -> None:
        self._abrir_no_sistema(str(atualizacao.pasta_do_programa()))

    def _conferir_instalacao(self) -> None:
        """Ao abrir o .exe (Windows): no lugar fixo, confere os atalhos e o "Iniciar com o Windows"; fora dele,
        oferece instalar lá (uma vez; dá para pedir "Não perguntar de novo")."""
        if not atualizacao.pode_instalar_sozinho():
            return
        if self.trabalhando:
            self.after(30_000, self._conferir_instalacao)
            return
        pasta = atualizacao.pasta_do_programa()
        dados = config.carregar().get("instalacao", {})
        if instalacao.esta_na_pasta_fixa(pasta):
            versao = atualizacao.versao_atual()
            instalacao.esconder_exe_antigo(pasta)       # na pasta você vê só o Maestro.exe
            if dados.get("atalhos_versao") != versao:      # instalou ou atualizou: refaz os atalhos (uma vez)
                exe = str(instalacao.executavel_fixo())    # o Maestro.exe (mesmo se abriu pelo nome antigo)

                def refazer():
                    try:
                        instalacao.criar_atalhos(exe)
                        self.fila.put(("atalhos_feitos", versao))
                    except (OSError, subprocess.SubprocessError) as erro:
                        self._log.warning("Atalhos: %s", erro)
                threading.Thread(target=refazer, daemon=True).start()
            if inicializacao.ativo():                     # "Iniciar com o Windows" aponta para o lugar fixo
                try:
                    inicializacao.ativar(True, executavel=instalacao.executavel_fixo())   # o Maestro.exe
                except OSError:
                    pass
            return
        if dados.get("nao_perguntar"):
            return
        escolha = self.escolher(
            "Instalar no lugar fixo",
            f"O programa está rodando de:\n{pasta}\n\nInstalar num lugar FIXO?\n{instalacao.pasta_fixa()}\n\n"
            "• cria o atalho \"Maestro\" na Área de Trabalho e no Menu Iniciar;\n"
            "• as atualizações vão sempre para lá (sem cópias espalhadas pelos Downloads);\n"
            "• configurações, regras e canais continuam os mesmos.\n\nDepois, a cópia antiga pode ser apagada.",
            ("Instalar no lugar fixo", "Não perguntar de novo"), cancelar="Agora não")
        if escolha == "Instalar no lugar fixo":
            self.ao_instalar_fixo()
        elif escolha == "Não perguntar de novo":
            tudo = config.carregar()
            tudo.setdefault("instalacao", {})["nao_perguntar"] = True
            config.salvar(tudo)

    def ao_instalar_fixo(self) -> None:
        """Copia o programa para o lugar fixo, cria os atalhos e reabre de lá."""
        if self.trabalhando:
            self.mostrar_mensagem("Instalar", "Espere a tarefa atual terminar.", "aviso")
            return
        origem = atualizacao.pasta_do_programa()

        def tarefa():
            try:
                exe = instalacao.copiar_para_pasta_fixa(origem)
            except OSError as erro:
                self.fila.put(("msg", ("Instalar", f"Não deu para copiar para {instalacao.pasta_fixa()}:\n{erro}\n\n"
                                       "Se o programa já está aberto de lá, feche-o e tente de novo.", "erro")))
                return
            self._log.info("Programa instalado no lugar fixo: %s", exe)
            avisos = []
            try:
                instalacao.criar_atalhos(exe)
            except (OSError, subprocess.SubprocessError) as erro:
                avisos.append(f"Os atalhos não foram criados ({erro}).")
            if inicializacao.ativo():
                try:
                    inicializacao.ativar(True, executavel=exe)
                except OSError as erro:
                    avisos.append(f"\"Iniciar com o Windows\" não foi trocado ({erro}).")
            self.fila.put(("instalado_fixo", (str(exe), avisos)))

        self._rodar("Instalando no lugar fixo...", tarefa)

    def _instalado_fixo(self, exe: str, avisos: list[str]) -> None:
        """Instalou: avisa, abre o programa do lugar fixo e fecha esta cópia."""
        self.mostrar_mensagem("Instalado", f"Pronto: o programa agora fica em\n{Path(exe).parent}\n\nUse o atalho "
                              "\"Maestro\" da Área de Trabalho ou do Menu Iniciar. Ele vai abrir de lá agora; a "
                              "cópia antiga (esta) pode ser apagada." + ("\n\n" + "\n".join(avisos) if avisos else ""),
                              "sucesso")
        try:
            instalacao.abrir(exe)
        except OSError as erro:
            self._log.error("Não consegui abrir %s: %s", exe, erro)
            return
        self.sair_de_vez()

    # ================================================================== aviso de versão nova
    INTERVALO_VERSAO_MS = 6 * 60 * 60 * 1000

    def _ciclo_versao(self) -> None:
        """Consulta sozinha enquanto o programa está aberto (quem deixa rodando perto do relógio também é avisado)."""
        self._versao_agendada = self.after(self.INTERVALO_VERSAO_MS, self._ciclo_versao)
        if self.var_jf_avisar_versao.get() or self.var_jf_atualizar_sozinho.get():
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
        if nova:
            self._versao_publicada = nova.versao
        atual = atualizacao.versao_atual()
        if erro:
            self.mostrar_mensagem("Verificar atualizações", f"Não consegui consultar agora: {erro}.\n"
                                  f"Esta é a versão {atual}.", "aviso")
        elif atualizacao.numeros(nova.versao) > atualizacao.numeros(atual):
            self._avisar_versao_nova(nova)
        else:
            self._log.info("Atualizações: esta é a mais nova (%s; publicada: %s)", atual, nova.versao)
            self.mostrar_mensagem("Verificar atualizações", f"Você já está na versão mais nova ({atual}).", "sucesso")

    def _baixar_atualizacao(self, nova, sozinho: bool = False) -> None:
        """Baixa o .zip em segundo plano (pode continuar usando o programa). sozinho=True ("Atualizar sozinho"):
        no fim, instala e reinicia sem perguntar."""
        if self.trabalhando and sozinho:                 # automático: tenta de novo quando a tarefa acabar
            self.after(60_000, lambda: self._baixar_atualizacao(nova, sozinho))
            return
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
            self.fila.put(("atualizacao_baixada", (nova, arquivo, sozinho)))
            self.fila.put(("status_fim", f"Versão {nova.versao} baixada em {arquivo.parent}."))

        self._rodar(f"Baixando a versão {nova.versao}...", tarefa)

    SEGUNDOS_PARA_REINICIAR = 20

    def _reiniciar_para_atualizar(self, versao: str, faltam: int | None = None) -> None:
        """"Atualizar sozinho": espera o programa ficar livre, avisa no rodapé com contagem regressiva e reinicia
        (fecha, troca os arquivos e abre de novo). Desmarcar a opção cancela: instala quando você fechar."""
        if not self.var_jf_atualizar_sozinho.get():
            self.definir_status(f"Reinício cancelado: a versão {versao} será instalada quando você fechar o programa.")
            if self._instalar_ao_sair:
                self._instalar_ao_sair = (self._instalar_ao_sair[0], False)      # instala ao fechar, sem reabrir
            return
        if self.trabalhando:                              # nunca interrompe uma tarefa: tenta de novo daqui a pouco
            self.after(30_000, lambda: self._reiniciar_para_atualizar(versao))
            return
        faltam = self.SEGUNDOS_PARA_REINICIAR if faltam is None else faltam
        if faltam <= 0:
            self._log.info("Atualizar sozinho: reiniciando para instalar a versão %s", versao)
            self.sair_de_vez()
            return
        self.definir_status(f"Versão {versao} pronta: o programa reinicia sozinho em {faltam} s para atualizar "
                            "(desmarque \"Atualizar sozinho\" na aba Jellyfin para cancelar).")
        self.after(1000, lambda: self._reiniciar_para_atualizar(versao, faltam - 1))

    def _atualizacao_baixada(self, nova, arquivo, sozinho: bool = False) -> None:
        """Baixou: avisa que, para concluir, o programa PRECISA FECHAR (o Windows não troca um programa aberto).
        Com "Atualizar sozinho": não pergunta; reinicia quando estiver livre."""
        if sozinho and atualizacao.pode_instalar_sozinho():
            self._instalar_ao_sair = (arquivo, True)
            self._reiniciar_para_atualizar(nova.versao)
            return
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
            "segundos) e abre de novo já na versão nova.\n\nConfigurações, regras e canais continuam valendo.\n\n"
            "Dica: marque \"Atualizar sozinho\" na aba Jellyfin e as próximas versões se instalam e reiniciam sem "
            "perguntar.",
            ("Atualizar e reiniciar agora", "Atualizar quando eu fechar"), cancelar="Depois")
        if escolha == "Atualizar e reiniciar agora":
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
        self._versao_publicada = nova.versao
        self.var_jf_versao_avisada.set(nova.versao)
        self._salvar_config()
        self._log.info("Versão nova disponível: %s (esta é %s) %s", nova.versao, atualizacao.versao_atual(), nova.url)
        if self.var_jf_atualizar_sozinho.get() and nova.arquivo_url and atualizacao.pode_instalar_sozinho():
            self._log.info("Atualizar sozinho: baixando %s", nova.versao)
            self._baixar_atualizacao(nova, sozinho=True)
            return
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
