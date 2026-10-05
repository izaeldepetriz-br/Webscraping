"""TV ao vivo na janela moderna: a lista de canais, conferir, editar, remover/desfazer e enviar ao Jellyfin.

Separado de app_moderna.py (que passou de 2.000 linhas): a AppModerna herda esta parte.
O trabalho pesado (consultar os canais, falar com o Jellyfin) fica em jellyfin_tools/tv_ao_vivo.py.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path
from tkinter import filedialog

from jellyfin_tools.paralelo import prioridade_baixa
from jellyfin_tools.servidor_jellyfin import ErroJellyfin
from jellyfin_tools.tv_ao_vivo import (VELOCIDADES, Canal, ClienteTV, NaoEhLista, carregar_canais, carregar_historico,
                                       conferir_canais, descrever_sintonizador, importar as importar_canais,
                                       publicar as publicar_canais, registrar_no_historico, resumo_historico,
                                       salvar_canais, salvar_historico, sempre_falha)

from . import config
from .gui_moderna import DialogoCanal, JanelaCanais, LinhaCanal


class TVAoVivo:
    """Parte "TV ao vivo" da AppModerna (usa self.fila, self._rodar, self.mostrar_mensagem... da janela)."""

    def _iniciar_tv_ao_vivo(self) -> None:
        self.janela_canais = None               # "TV ao vivo..."
        self._canais, self._situacao_canais = [], {}
        self._historico_canais = None           # {link: [no ar nas últimas conferências]} (lido na 1ª vez)

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
            for linha in feito:
                self._log.info("TV ao vivo: %s", linha)
            dica = "" if cliente else ("\n\nSem o endereço e a chave do Jellyfin (aba Jellyfin), a lista só foi salva: "
                                       "cadastre-a em Painel > TV ao vivo > Sintonizadores > M3U.")
            self.fila.put(("msg", ("TV ao vivo", "\n".join(feito) + dica, "sucesso")))

        self._rodar("Enviando os canais ao Jellyfin (e esperando ele atualizar o guia)...", tarefa)

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
