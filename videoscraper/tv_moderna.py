"""TV ao vivo na janela moderna: a lista de canais, conferir, editar, remover/desfazer e enviar ao Jellyfin.

Separado de app_moderna.py (que passou de 2.000 linhas): a AppModerna herda esta parte.
O trabalho pesado (consultar os canais, falar com o Jellyfin) fica em jellyfin_tools/tv_ao_vivo.py.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import filedialog

from jellyfin_tools.notificacoes import Notificador
from jellyfin_tools.paralelo import prioridade_baixa
from jellyfin_tools.servidor_jellyfin import ErroJellyfin
from jellyfin_tools.tv_ao_vivo import (VELOCIDADES, Canal, ClienteTV, NaoEhLista, carregar_canais, carregar_historico,
                                       canais_a_mais, conferir_canais, desativar_plugins_e_limpar,
                                       descrever_sintonizador, plugins_de_tv,
                                       importar as importar_canais, limpar_e_reenviar,
                                       publicar as publicar_canais, registrar_no_historico, resumo_historico,
                                       resumo_tv, salvar_canais, salvar_historico, sempre_falha, texto_diagnostico)

from . import config
from .gui_moderna import DialogoCanal, JanelaCanais, LinhaCanal


class TVAoVivo:
    """Parte "TV ao vivo" da AppModerna (usa self.fila, self._rodar, self.mostrar_mensagem... da janela)."""

    def _iniciar_tv_ao_vivo(self) -> None:
        self.janela_canais = None               # "TV ao vivo..."
        self._canais, self._situacao_canais = [], {}
        self._historico_canais = None           # {link: [no ar nas últimas conferências]} (lido na 1ª vez)
        self._saude_tv = None                   # (tudo certo?, texto) da última consulta ao Jellyfin
        self._saude_tv_quando = 0.0             # time.monotonic() da última consulta (0 = consultar logo)
        self._saude_tv_rodando = False
        self._semanal_rodando = False           # conferência semanal dos canais em andamento
        self._semanal_visto = 0.0               # time.monotonic() da última vez que olhou se estava na hora
        self._semanal_resultado = None          # (conferidos, fora do ar, sempre falham) da última semanal

    def _receber_conferencia_canais(self, situacoes) -> None:
        """Chegou o resultado de uma conferência (na thread da janela): situação, histórico e a tabela."""
        self._situacao_canais.update({c.url: sit for c, sit in situacoes})
        registrar_no_historico(self.historico_canais, situacoes)       # "✓✓✕..." das últimas conferências
        try:
            salvar_historico(self.arquivo_historico_canais, self.historico_canais,
                             self._canais or carregar_canais(self.arquivo_canais))
        except OSError as erro:
            self._log.warning("Não deu para gravar o histórico dos canais: %s", erro)
        self._mostrar_canais(manter_selecao=True)

    @property
    def arquivo_canais(self) -> Path:
        return config.ARQUIVO.parent / "canais.json"

    @property
    def arquivo_historico_canais(self) -> Path:
        return config.ARQUIVO.parent / "canais_historico.json"

    @property
    def arquivo_lixeira_canais(self) -> Path:
        return config.ARQUIVO.parent / "canais_removidos.json"

    @property
    def historico_canais(self) -> dict:
        if self._historico_canais is None:
            self._historico_canais = carregar_historico(self.arquivo_historico_canais)
        return self._historico_canais

    def ao_tv_ao_vivo(self) -> None:
        if self.janela_canais is None or not self.janela_canais.winfo_exists():
            self.janela_canais = JanelaCanais(self, {
                "adicionar": self._adicionar_canal, "importar_arquivo": self._importar_canais_arquivo,
                "importar_endereco": self._importar_canais_endereco, "remover": self._remover_canais,
                "remover_todos": self._remover_todos_canais, "conferir": self._conferir_canais,
                "publicar": self._publicar_canais, "editar": self._editar_canal, "numerar": self._numerar_canais,
                "diagnostico": self.ao_diagnostico_tv, "semanal": self._guardar_opcoes_tv,
                "desfazer": self._desfazer_remocao_canais})
            dados = config.carregar().get("tv", {})
            dados.setdefault("pasta", str(config.ARQUIVO.parent / "tv"))
            self.janela_canais.definir_valores(dados)
            self.janela_canais.menu_velocidade.configure(command=lambda _: self._guardar_opcoes_tv())
        self._canais = carregar_canais(self.arquivo_canais)
        self._mostrar_canais()
        self.janela_canais.lift()

    def _mostrar_canais(self, manter_selecao: bool = False) -> None:
        if self.janela_canais is None or not self.janela_canais.winfo_exists():
            return
        linhas = []
        historico = self.historico_canais
        for i, c in enumerate(self._canais):
            situacao = self._situacao_canais.get(c.url)            # None = ainda não conferido
            ultimas = historico.get(c.url, [])
            linhas.append(LinhaCanal(str(i), c.nome, c.grupo, situacao.detalhe if situacao else "—", c.url,
                                     situacao.ok if situacao else None, c.numero, resumo_historico(ultimas),
                                     sempre_falha(ultimas)))
        self.janela_canais.preencher(linhas, manter_selecao)
        self.janela_canais.bt_desfazer.configure(state="normal" if self._lixeira_canais() else "disabled")

    def _guardar_opcoes_tv(self) -> None:
        if self.janela_canais is not None and self.janela_canais.winfo_exists():
            tudo = config.carregar()
            tudo["tv"] = self.janela_canais.valores()
            config.salvar(tudo)

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

    def _consultas_ao_mesmo_tempo(self) -> int:
        """Leve 8 / Normal 16 / Rápida 32 (escolhido na janela de TV ao vivo e guardado na configuração)."""
        janela = self.janela_canais
        if janela is not None and janela.winfo_exists():
            nome = janela.var_velocidade.get()
        else:
            nome = config.carregar().get("tv", {}).get("velocidade", "Normal")
        return VELOCIDADES.get(nome, VELOCIDADES["Normal"])

    LIXEIRA_GUARDA = 10                           # quantas remoções dá para desfazer

    def _lixeira_canais(self) -> list:
        try:
            dados = json.loads(self.arquivo_lixeira_canais.read_text(encoding="utf-8"))
            return dados if isinstance(dados, list) else []
        except (OSError, ValueError):
            return []

    def _guardar_na_lixeira(self, indices) -> None:
        """Guarda os canais que vão sair (com a posição de cada um) para o "Desfazer remoção"."""
        lote = [[i, asdict(self._canais[i])] for i in sorted(indices) if 0 <= i < len(self._canais)]
        if not lote:
            return
        pilha = (self._lixeira_canais() + [lote])[-self.LIXEIRA_GUARDA:]
        try:
            self.arquivo_lixeira_canais.parent.mkdir(parents=True, exist_ok=True)
            self.arquivo_lixeira_canais.write_text(json.dumps(pilha, ensure_ascii=False), encoding="utf-8")
        except OSError as erro:
            self._log.warning("Não deu para guardar os canais removidos (Desfazer): %s", erro)

    def _desfazer_remocao_canais(self) -> None:
        """Põe de volta os canais da ÚLTIMA remoção, cada um na posição em que estava."""
        pilha = self._lixeira_canais()
        if not pilha:
            self.mostrar_mensagem("TV ao vivo", "Não há remoção para desfazer.", "info")
            return
        lote = pilha.pop()
        conhecidos = {c.url for c in self._canais}
        campos = set(Canal.__dataclass_fields__)
        voltaram = 0
        for posicao, dados in lote:                        # em ordem crescente: as posições continuam certas
            canal = Canal(**{k: v for k, v in dados.items() if k in campos})
            if canal.url not in conhecidos:
                self._canais.insert(min(int(posicao), len(self._canais)), canal)
                conhecidos.add(canal.url)
                voltaram += 1
        self.arquivo_lixeira_canais.write_text(json.dumps(pilha, ensure_ascii=False), encoding="utf-8")
        self._guardar_canais()
        self.mostrar_mensagem("TV ao vivo", f"{voltaram} canal(is) voltaram para a lista."
                              + ("\n\nPara o Jellyfin receber, clique em \"Salvar e enviar\"." if voltaram else ""),
                              "sucesso")

    def _remover_todos_canais(self) -> None:
        if self._canais and self.perguntar("TV ao vivo", f"Tirar TODOS os {len(self._canais)} canal(is) da lista?\n\n"
                                           "(Dá para voltar atrás com \"Desfazer remoção\". O Jellyfin muda só no "
                                           "próximo \"Salvar e enviar\".)"):
            self._guardar_na_lixeira(range(len(self._canais)))
            self._canais, self._situacao_canais = [], {}
            self._guardar_canais()

    def _editar_canal(self, iid: str) -> None:
        """Duplo clique numa linha: muda nome, número, grupo, link, logo ou o ID do guia."""
        indice = int(iid)
        if not 0 <= indice < len(self._canais):
            return
        atual = self._canais[indice]
        novo = self._pedir_dados_canal(asdict(atual))
        if not novo:
            return
        url = novo.get("url", "").strip()
        if not url.lower().startswith(("http://", "https://", "rtsp://", "rtmp://", "udp://")):
            self.mostrar_mensagem("TV ao vivo", "O link do sinal precisa começar com http://, https://, rtsp://...",
                                  "aviso")
            return
        if url != atual.url and any(c.url == url for c in self._canais):
            self.mostrar_mensagem("TV ao vivo", "Esse link já está em outro canal da lista.", "aviso")
            return
        if novo.get("numero") and not novo["numero"].replace(".", "", 1).isdigit():
            self.mostrar_mensagem("TV ao vivo", "O número do canal precisa ser um número (ex.: 2 ou 2.1).", "aviso")
            return
        campos = set(Canal.__dataclass_fields__)
        self._canais[indice] = Canal(**{**asdict(atual), **{k: v for k, v in novo.items() if k in campos}})
        if url != atual.url:                               # outro link: a situação antiga não vale mais
            self._situacao_canais.pop(atual.url, None)
            self.historico_canais.pop(atual.url, None)
        self._guardar_canais()

    def _pedir_dados_canal(self, dados: dict) -> dict | None:
        dialogo = DialogoCanal(self.janela_canais or self, dados)
        self.wait_window(dialogo)
        return dialogo.resultado

    def _numerar_canais(self) -> None:
        """Número de cada canal no Jellyfin (tvg-chno): 1, 2, 3... na ordem da lista. Com canais selecionados,
        só eles, continuando depois do maior número que já existe."""
        janela = self.janela_canais
        escolhidos = janela.a_conferir() if janela is not None and janela.winfo_exists() else None
        indices = list(range(len(self._canais))) if escolhidos is None else sorted(int(i) for i in escolhidos)
        if not indices:
            return
        if escolhidos is None:
            inicio, alvo = 1, f"os {len(indices)} canal(is), de 1 a {len(indices)}"
        else:
            outros = [float(c.numero) for i, c in enumerate(self._canais)
                      if i not in set(indices) and c.numero.replace(".", "", 1).isdigit()]
            inicio = int(max(outros, default=0)) + 1
            alvo = f"os {len(indices)} selecionado(s), de {inicio} a {inicio + len(indices) - 1}"
        if not self.perguntar("TV ao vivo", f"Numerar {alvo}, na ordem da lista?\n\nO número aparece no Jellyfin "
                              "(TV ao vivo e guia). Dá para mudar um por um com duplo clique no canal."):
            return
        for n, i in enumerate(indices, inicio):
            self._canais[i].numero = str(n)
        self._guardar_canais()

    def _remover_canais(self) -> None:
        tirar = {int(i) for i in self.janela_canais.selecionados()}
        if not tirar:
            self.mostrar_mensagem("TV ao vivo", "Selecione os canais (clique; Ctrl+clique para vários), ou use "
                                  "\"Selecionar os fora do ar\" / \"Remover todos\".", "aviso")
            return
        if self.perguntar("TV ao vivo", f"Tirar {len(tirar)} canal(is) da lista?\n\n(Dá para voltar atrás com "
                          "\"Desfazer remoção\".)"):
            self._guardar_na_lixeira(tirar)
            self._canais = [c for i, c in enumerate(self._canais) if i not in tirar]
            self._guardar_canais()

    CANAIS_NO_CONSOLE = 300

    def _registrar_canais(self, situacoes) -> None:
        """Uma linha por canal no arquivo de log. No console da janela, só em listas pequenas: 11 mil linhas
        de uma vez travavam a tela por alguns segundos (a situação de cada um já aparece na tabela)."""
        grande = len(situacoes) > self.CANAIS_NO_CONSOLE
        for c, s in situacoes:
            nivel = logging.DEBUG if grande else (logging.INFO if s.ok else logging.WARNING)
            self._log.log(nivel, "[canal] %s: %s", c.nome, s.detalhe)
        if grande:
            self._log.info("[canal] %d canais conferidos: a situação de cada um está na tabela de canais e no "
                           "arquivo de log (botão Abrir log).", len(situacoes))

    def _conferir_canais(self) -> None:
        """Confere os canais SELECIONADOS na tabela (sem seleção, todos). Os outros mantêm a situação de antes."""
        janela = self.janela_canais
        escolhidos = janela.a_conferir() if janela is not None and janela.winfo_exists() else None
        canais = list(self._canais) if escolhidos is None else \
            [self._canais[int(i)] for i in escolhidos if 0 <= int(i) < len(self._canais)]
        if not canais:
            return
        rotulo = "Conferindo canais" if len(canais) == len(self._canais) else f"Conferindo {len(canais)} selecionado(s)"

        trabalhadores = self._consultas_ao_mesmo_tempo()

        def tarefa():
            with prioridade_baixa():
                situacoes = conferir_canais(canais, trabalhadores, parar=self.evento_parar.is_set,
                                            ao_progresso=self._progresso_com_velocidade(rotulo))
            self._registrar_canais(situacoes)
            fora = sum(1 for _, sit in situacoes if not sit.ok)
            self.fila.put(("canais_conferidos", situacoes))
            parado = f" Parado: {len(situacoes)} de {len(canais)} conferidos." if len(situacoes) < len(canais) else ""
            self.fila.put(("status_fim", f"Canais: {len(situacoes) - fora} no ar, {fora} fora do ar.{parado}"))

        self._rodar("Conferindo os canais ao vivo...", tarefa)

    def _publicar_canais(self) -> None:
        valores = self.janela_canais.valores()
        if not valores["pasta"]:
            self.mostrar_mensagem("TV ao vivo", "Escolha a pasta onde salvar a lista (canais.m3u).", "aviso")
            return
        janela = self.janela_canais
        visiveis = set(janela.tabela.get_children()) if janela._filtros else None
        if visiveis is not None and len(visiveis) < len(self._canais):
            # O filtro só ESCONDE: a lista enviada é a inteira. Pergunta o que a pessoa quer.
            fora = len(self._canais) - len(visiveis)
            escolha = self.escolher(
                "TV ao vivo", f"O filtro está ligado: a tabela mostra {len(visiveis)} de {len(self._canais)} canais.\n\n"
                f"O envio manda a LISTA inteira (o filtro só esconde). Enviar só os {len(visiveis)} que aparecem? "
                f"Os outros {fora} saem da lista (dá para voltar com \"Desfazer remoção\").",
                (f"Enviar só os {len(visiveis)} filtrados", f"Enviar todos os {len(self._canais)}"), cancelar="Cancelar")
            if escolha is None:
                return
            if escolha.startswith("Enviar só"):
                tirar = [i for i in range(len(self._canais)) if str(i) not in visiveis]
                self._guardar_na_lixeira(tirar)
                self._canais = [c for i, c in enumerate(self._canais) if str(i) in visiveis]
                janela.limpar_filtros()
                self._guardar_canais()
        if not self._canais and not valores["antena"] and not self.perguntar(
                "TV ao vivo", "A lista está VAZIA.\n\nEnviar assim TIRA do Jellyfin os canais enviados antes "
                "(a lista canais.m3u fica sem canais). Continuar?"):
            return
        self._guardar_canais()
        o = self.obter_opcoes_jellyfin()
        canais = list(self._canais)

        def tarefa():
            cliente = ClienteTV(o.jellyfin_url, o.jellyfin_api_key) if o.jellyfin_url and o.jellyfin_api_key else None
            feito = publicar_canais(canais, valores["pasta"], valores["no_servidor"], valores["guia"], cliente,
                                    valores["antena"], parar=self.evento_parar.is_set)
            if cliente is not None:                       # outros sintonizadores somam canais ao total do Jellyfin
                endereco = valores["no_servidor"].strip() or str(Path(valores["pasta"]) / "canais.m3u")
                try:
                    outros = cliente.outros_sintonizadores(endereco)
                except ErroJellyfin as erro:
                    outros = []
                    self._log.warning("TV ao vivo: não deu para ver os outros sintonizadores: %s", erro)
                if outros:
                    feito.append(f"Atenção: o Jellyfin tem mais {len(outros)} sintonizador(es) que não são desta lista "
                                 "(os canais deles entram no total).")
                    self.fila.put(("tv_outros_sintonizadores", (outros, o.jellyfin_url, o.jellyfin_api_key)))
                else:
                    # nenhum de fora, mas o Jellyfin ficou com bem mais canais que a lista: guarda canais velhos
                    try:
                        total = cliente.quantos_canais()
                        todos = cliente.configuracao().get("TunerHosts") or []
                    except ErroJellyfin:
                        total, todos = None, []
                    if canais_a_mais(total, canais, valores["antena"]):
                        feito.append(f"Atenção: o Jellyfin tem {total} canais, mas a lista enviada tem {len(canais)}.")
                        self.fila.put(("tv_canais_a_mais", (total, len(canais), todos, endereco, o.jellyfin_url,
                                                            o.jellyfin_api_key)))
            for linha in feito:
                self._log.info("TV ao vivo: %s", linha)
            self._saude_tv_quando = 0.0                   # o painel de saúde confere de novo
            dica = "" if cliente else ("\n\nSem o endereço e a chave do Jellyfin (aba Jellyfin), a lista só foi salva: "
                                       "cadastre-a em Painel > TV ao vivo > Sintonizadores > M3U.")
            self.fila.put(("msg", ("TV ao vivo", "\n".join(feito) + dica, "sucesso")))

        self._rodar("Enviando os canais ao Jellyfin (e esperando ele atualizar o guia)...", tarefa)

    INTERVALO_SAUDE_TV = 30 * 60               # segundos entre uma consulta e outra (são 3 pedidos pequenos)

    def item_saude_tv(self):
        """("TV: 144 canais", True) para o painel de saúde; None se não há lista ou ainda não consultou.
        Com canais que sempre falham (conferência semanal), fica laranja até você tirá-los."""
        if not self._saude_tv and not self._semanal_resultado:
            return None
        ok, texto = self._saude_tv or (True, "")
        if self._semanal_resultado and self._semanal_resultado[2]:
            texto = (texto + " · " if texto else "") + f"{self._semanal_resultado[2]} sempre falham"
            ok = False if ok is not None else ok
        return f"TV: {texto}", ok

    # ---- conferência semanal (opção na janela TV ao vivo)
    DIAS_ENTRE_CONFERENCIAS = 7
    OLHAR_A_CADA = 10 * 60                     # segundos: de quanto em quanto tempo vê se já está na hora

    def conferencia_semanal_tv(self, agora: datetime | None = None, relogio: float | None = None) -> bool:
        """Se a opção está ligada e a última foi há 7 dias ou mais: confere TODOS os canais em segundo plano,
        devagar ("Leve" e prioridade baixa), sem travar a janela nem as outras tarefas. True = começou."""
        relogio = time.monotonic() if relogio is None else relogio
        if self._semanal_rodando or (self._semanal_visto and relogio - self._semanal_visto < self.OLHAR_A_CADA):
            return False
        self._semanal_visto = relogio
        tudo = config.carregar()
        if not tudo.get("tv", {}).get("semanal"):
            return False
        agora = agora or datetime.now()
        quando = tudo.get("tv_semanal", {}).get("quando")
        try:
            if quando and agora - datetime.fromisoformat(quando) < timedelta(days=self.DIAS_ENTRE_CONFERENCIAS):
                return False
        except ValueError:
            pass
        try:
            canais = list(self._canais) or carregar_canais(self.arquivo_canais)
        except (OSError, ValueError):
            canais = []
        if not canais:
            return False
        self._semanal_rodando = True
        tudo.setdefault("tv_semanal", {})["quando"] = agora.isoformat(timespec="seconds")
        config.salvar(tudo)
        self._log.info("TV ao vivo: conferência semanal de %d canais (em segundo plano)", len(canais))

        def conferir():
            try:
                with prioridade_baixa():
                    situacoes = conferir_canais(canais, VELOCIDADES["Leve"])
                self._registrar_canais(situacoes)
                self.fila.put(("tv_semanal", situacoes))
            finally:
                self._semanal_rodando = False
        threading.Thread(target=conferir, daemon=True, name="tv-semanal").start()
        return True

    def _fim_conferencia_semanal(self, situacoes) -> None:
        """Chegou a semanal: guarda no histórico, mostra no painel de saúde e avisa (Discord/Telegram e, com
        a janela aberta, uma pergunta) os que falharam em TODAS as últimas conferências."""
        self._receber_conferencia_canais(situacoes)
        historico = self.historico_canais
        canais = self._canais or carregar_canais(self.arquivo_canais)
        ruins = [c for c in canais if sempre_falha(historico.get(c.url, []))]
        fora = sum(1 for _, sit in situacoes if not sit.ok)
        self._semanal_resultado = (len(situacoes), fora, len(ruins))
        resumo = (f"TV ao vivo, conferência semanal: {len(situacoes) - fora} no ar, {fora} fora do ar"
                  + (f", {len(ruins)} sempre falham" if ruins else "") + ".")
        self._log.info("%s", resumo)
        if ruins:
            o = self.obter_opcoes_jellyfin()
            notificador = Notificador(o.discord_webhook, o.telegram_token, o.telegram_chat_id)
            if notificador.ativo:
                nomes = ", ".join(c.nome for c in ruins[:10]) + (f" e mais {len(ruins) - 10}" if len(ruins) > 10 else "")
                threading.Thread(target=notificador.enviar, daemon=True, kwargs={
                    "discord": f"📺 **{resumo}** Sempre falham: {nomes}",
                    "telegram": f"📺 <b>{resumo}</b> Sempre falham: {nomes}"}).start()
            self._oferecer_canais_ruins(len(ruins), resumo)

    def _oferecer_canais_ruins(self, quantos: int, resumo: str) -> None:
        if self.trabalhando:                          # não interrompe uma tarefa: pergunta depois
            self.after(60_000, lambda: self._oferecer_canais_ruins(quantos, resumo))
            return
        if self.state() in ("withdrawn", "iconic"):   # minimizado na bandeja: fica no painel de saúde e no log
            return
        escolha = self.escolher(
            "TV ao vivo: conferência semanal",
            f"{resumo}\n\n{quantos} canal(is) falharam em TODAS as últimas conferências: provavelmente saíram do "
            "ar de vez. Quer ver e decidir se remove? (Um canal que funciona só em alguns horários não entra "
            "nessa conta.)", ("Abrir e selecionar os que sempre falham",), cancelar="Depois")
        if escolha:
            self.ao_tv_ao_vivo()
            self.janela_canais.selecionar_mortos()

    def conferir_saude_tv(self, agora: float | None = None) -> bool:
        """Consulta o Jellyfin em segundo plano (sem travar nada) a cada INTERVALO_SAUDE_TV. True = disparou."""
        import threading
        import time
        agora = time.monotonic() if agora is None else agora
        if self._saude_tv_rodando or (self._saude_tv_quando and agora - self._saude_tv_quando < self.INTERVALO_SAUDE_TV):
            return False
        url, chave = self.var_jf_url.get().strip(), self.var_jf_chave_jellyfin.get().strip()
        try:
            na_lista = len(self._canais) or len(carregar_canais(self.arquivo_canais))
        except (OSError, ValueError):
            na_lista = 0
        if not (url and chave and na_lista):
            return False                              # sem Jellyfin ou sem lista: nada a mostrar
        self._saude_tv_rodando, self._saude_tv_quando = True, agora

        def consultar():
            try:
                self._saude_tv = resumo_tv(ClienteTV(url, chave, timeout=15).estado(), na_lista)
            except ErroJellyfin as erro:
                self._saude_tv = (None, f"sem resposta ({str(erro)[:40]})")
            finally:
                self._saude_tv_rodando = False
            if self._saude_tv[0] is False:
                self._log.warning("TV ao vivo (painel de saúde): %s", self._saude_tv[1])
        threading.Thread(target=consultar, daemon=True, name="saude-tv").start()
        return True

    def _oferecer_tirar_sintonizadores(self, outros: list[dict], url: str, chave: str) -> None:
        """Depois do envio: o Jellyfin tem sintonizadores que não são desta lista (ex.: uma lista grande cadastrada
        à mão no Painel). Mostra quais são e, se a pessoa quiser, tira do Jellyfin."""
        lista = "\n".join(f"• {descrever_sintonizador(h)}" for h in outros[:10])
        resto = f"\n… e mais {len(outros) - 10}" if len(outros) > 10 else ""
        escolha = self.escolher(
            "TV ao vivo: outros sintonizadores",
            f"Além da sua lista, o Jellyfin tem {len(outros)} sintonizador(es) cadastrados fora do programa:\n\n"
            f"{lista}{resto}\n\nOs canais deles aparecem junto em TV ao vivo (por isso o total é maior que a sua lista). "
            "Tirar estes sintonizadores do Jellyfin? (Só eles; a sua lista continua.)",
            ("Tirar do Jellyfin",), cancelar="Deixar como está")
        if escolha != "Tirar do Jellyfin":
            return

        def tarefa():
            cliente = ClienteTV(url, chave)
            for host in outros:
                cliente.remover_sintonizador(host.get("Id", ""))
                self._log.info("TV ao vivo: sintonizador retirado do Jellyfin: %s", descrever_sintonizador(host))
            texto = f"{len(outros)} sintonizador(es) retirado(s) do Jellyfin."
            if (tarefa_guia := cliente.atualizar_guia()) and cliente.esperar_tarefa(tarefa_guia, 180,
                                                                                  self.evento_parar.is_set):
                total = cliente.quantos_canais()
                texto += f"\nGuia atualizado: agora TV ao vivo tem {total} canal(is)." if total is not None else ""
            else:
                texto += "\nO Jellyfin está atualizando o guia: os canais somem em alguns minutos."
            self.fila.put(("msg", ("TV ao vivo", texto, "sucesso")))

        self._rodar("Tirando os outros sintonizadores do Jellyfin...", tarefa)

    def _oferecer_limpar_tv(self, total: int, enviados: int, todos: list[dict], endereco: str, url: str,
                            chave: str) -> None:
        """Depois do envio: o Jellyfin ficou com MUITO mais canais que a lista (ex.: 11.129 com 144 enviados) e
        não há sintonizador de fora. Mostra os sintonizadores e oferece a faxina (tira, atualiza, põe de volta)."""
        lista = "\n".join(f"• {descrever_sintonizador(h)}" for h in todos[:10]) or "• (nenhum)"
        escolha = self.escolher(
            "TV ao vivo: canais a mais no Jellyfin",
            f"O Jellyfin está com {total} canais, mas a lista enviada tem {enviados}.\n\nSintonizadores no Jellyfin:\n"
            f"{lista}\n\nO Jellyfin ainda guarda canais de listas antigas. \"Limpar e reenviar\": tira a lista do "
            "Jellyfin, espera ele apagar os canais velhos, põe a lista atual de volta e atualiza de novo (leva alguns "
            "minutos; os favoritos da TV ao vivo precisam ser marcados de novo).",
            ("Limpar e reenviar",), cancelar="Deixar como está")
        if escolha != "Limpar e reenviar":
            return

        enviados_nomes = {c.nome for c in self._canais}

        def tarefa():
            cliente = ClienteTV(url, chave)
            feito = limpar_e_reenviar(cliente, endereco, self.evento_parar.is_set)
            for linha in feito:
                self._log.info("TV ao vivo (limpeza): %s", linha)
            total = cliente.quantos_canais()
            if total is not None and total > enviados + max(10, enviados // 10):
                # nem sem a lista os canais saíram: vêm de outra fonte, ou o Jellyfin não está limpando
                d = cliente.diagnostico()
                self._saude_tv = resumo_tv(d, enviados)
                self.fila.put(("tv_diagnostico", ("\n".join(feito), texto_diagnostico(d, enviados_nomes, enviados),
                                                  plugins_de_tv(d)[0], url, chave, self._saude_tv[0])))
            else:
                self.fila.put(("msg", ("TV ao vivo", "\n".join(feito) or "Pronto.", "sucesso")))

        self._rodar("Limpando a TV ao vivo do Jellyfin e reenviando (alguns minutos)...", tarefa)

    def ao_diagnostico_tv(self) -> None:
        """Botão "Diagnóstico do Jellyfin": de onde vêm os canais que estão na TV ao vivo."""
        o = self.obter_opcoes_jellyfin()
        if not (o.jellyfin_url and o.jellyfin_api_key):
            self.mostrar_mensagem("TV ao vivo", "Preencha o endereço e a chave de API do Jellyfin (aba Jellyfin).", "aviso")
            return
        nomes, na_lista = {c.nome for c in self._canais}, len(self._canais)

        def tarefa():
            d = ClienteTV(o.jellyfin_url, o.jellyfin_api_key).diagnostico()
            texto = texto_diagnostico(d, nomes, na_lista)
            self._saude_tv = resumo_tv(d, na_lista)
            self._log.info("TV ao vivo, diagnóstico:\n%s", texto)
            self.fila.put(("tv_diagnostico", ("", texto, plugins_de_tv(d)[0], o.jellyfin_url, o.jellyfin_api_key,
                                              self._saude_tv[0])))

        self._rodar("Consultando o Jellyfin (diagnóstico da TV ao vivo)...", tarefa)

    def _mostrar_diagnostico_tv(self, antes: str, texto: str, plugins: list[dict] = (), url: str = "",
                                chave: str = "", ok: bool | None = None) -> None:
        if ok:                                      # tudo certo: sem o texto de "se os canais não são da lista..."
            explicacao = ""
            opcoes = ("Copiar o diagnóstico",)
        elif plugins:
            nomes = " e ".join(str(p.get("Name")) for p in plugins)
            explicacao = (
                f"\n\nPROVÁVEL CAUSA: os plugins {nomes} estão instalados. Se um deles não está configurado (ou o "
                "servidor dele está desligado), a atualização do guia dá erro nele e, com erro, o Jellyfin PULA a "
                "limpeza: os canais velhos nunca saem.\n\n\"Desativar os plugins e limpar\": desativa esses "
                "plugins (não apaga), reinicia o Jellyfin e atualiza o guia. Use se você não usa NextPVR/TVHeadend.")
            opcoes = ("Desativar os plugins e limpar", "Copiar o diagnóstico")
        else:
            explicacao = (
                "\n\nSe os canais não são da sua lista e não há outro sintonizador, eles vêm de outro serviço (plugin "
                "de TV ao vivo) ou ficaram guardados porque a atualização do guia teve um erro: com erro, o Jellyfin "
                "pula a limpeza dos canais velhos. Veja em Painel > Logs (procure \"Error refreshing\").")
            opcoes = ("Copiar o diagnóstico",)
        escolha = self.escolher("TV ao vivo: diagnóstico", (antes + "\n\n" if antes else "") + texto + explicacao,
                                opcoes, cancelar="Fechar")
        if escolha == "Copiar o diagnóstico":
            self.clipboard_clear()
            self.clipboard_append(texto)
            self.definir_status("Diagnóstico copiado: cole numa mensagem (Ctrl+V).")
        elif escolha == "Desativar os plugins e limpar":
            self._desativar_plugins_tv(list(plugins), url, chave)

    def _desativar_plugins_tv(self, plugins: list[dict], url: str, chave: str) -> None:
        nomes = "\n".join(f"• {p.get('Name')} {p.get('Version')}" for p in plugins)
        if not self.perguntar(
                "Desativar plugins de TV ao vivo",
                f"Vou desativar no Jellyfin:\n{nomes}\n\ne REINICIAR o Jellyfin (quem estiver assistindo algo cai "
                "por um ou dois minutos). Depois o guia é atualizado e os canais velhos saem.\n\nNada é apagado: "
                "para usar de novo, Painel > Plugins > (o plugin) > Ativar, e reinicie.\n\nVocê tem certeza?"):
            return
        enviados = len(self._canais)

        def tarefa():
            feito, total = desativar_plugins_e_limpar(ClienteTV(url, chave), plugins, self.evento_parar.is_set)
            for linha in feito:
                self._log.info("TV ao vivo (plugins): %s", linha)
            sobrou = total is not None and total > enviados + max(10, enviados // 10)
            self.fila.put(("msg", ("TV ao vivo", "\n".join(feito) + (
                "\n\nAinda há canais a mais: clique em \"Diagnóstico do Jellyfin\" de novo e me mande o resultado."
                if sobrou else ""), "aviso" if sobrou or total is None else "sucesso")))

        self._rodar("Desativando plugins de TV e reiniciando o Jellyfin (alguns minutos)...", tarefa)
