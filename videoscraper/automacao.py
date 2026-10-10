"""Comandos de linha para robôs (RPA: UiPath, BotCity, Agendador de Tarefas do Windows).

    Maestro.exe --organizar            organiza o que terminou de baixar (filmes e séries)
    Maestro.exe --conferir-espelhos    confere os links dos .strm (e avisa no Discord/Telegram se quebrou)
    Maestro.exe --conferir-canais      confere os canais da TV ao vivo (e avisa se algum saiu do ar)
    Maestro.exe --enviar-tv            envia a lista de canais ao Jellyfin (o mesmo "Salvar e enviar")
    Maestro.exe --traduzir-legendas    traduz com a IA (Claude) as legendas que faltam
    Maestro.exe --legendar-audio       cria a legenda ouvindo o áudio (Whisper no PC + Claude) dos vídeos sem nenhuma
    Maestro.exe --dublar               dubla com voz sintética (Piper) os filmes com legenda em português

Dá para juntar vários (rodam nessa ordem): Maestro.exe --organizar --traduzir-legendas
Opções:  --simular (organizar: só mostra o que faria)   --limite-dolares 1.00 (traduzir: 0 = sem limite)
         --limite-videos 5 (legendar-audio e dublar: quantos vídeos por execução; demora)
         --resultado C:\\pasta\\resultado.json (onde gravar o resumo; padrão: ~/.videoscraper/rpa/ultimo.json)

Usam as MESMAS configurações da janela (pastas, chaves, opções da aba Jellyfin e da TV ao vivo) e só as
LEEM: nada é mudado nelas. Nenhuma janela abre e nada é perguntado. Chave que não foi lembrada ("Lembrar as
chaves" desmarcado) vem da variável de ambiente (TMDB_API_KEY, ANTHROPIC_API_KEY, JELLYFIN_API_KEY...).

Código de saída (o robô decide o próximo passo por ele):
    0 = tudo certo
    1 = terminou, mas achou problema (erro ao mover, link quebrado, canal fora do ar...)
    2 = falta configuração (pasta, chave, lista de canais): nada foi feito
    3 = erro inesperado (o motivo está no log)
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import json
import logging
import os
import sys
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from jellyfin_tools import (CatalogoEmCadeia, CatalogoLocal, CatalogoTMDB, ConfigSite, ProvedorOpenSubtitles,
                            ProvedorSiteHTML, ProvedorSubDL)
from jellyfin_tools.espelho import conferir_e_avisar
from jellyfin_tools.metadados import ClienteTMDB
from jellyfin_tools.notificacoes import Notificador
from jellyfin_tools.organizador import organizar_misto, problema_no_caminho
from jellyfin_tools.paralelo import prioridade_baixa
from jellyfin_tools.pos_processamento import ConfigPos, pos_processar
from jellyfin_tools.registro import configurar_log, encerrar_log_da_acao, iniciar_log_da_acao
from jellyfin_tools.regras import carregar_regras
from jellyfin_tools.servidor_jellyfin import ErroJellyfin, atualizar_biblioteca
from jellyfin_tools.site_demo import iniciar_site_demo
from jellyfin_tools.traducao import Tradutor, estimar_custo, legendas_para_traduzir, traduzir_arquivo
from jellyfin_tools.transcricao import Transcritor, legendar_pelo_audio, videos_sem_legenda
from jellyfin_tools.dublagem import (ErroDublagem, MotorPiper, dublar_video, preparar_piper, preparar_voz,
                                     videos_para_dublar)
from jellyfin_tools.tv_ao_vivo import (VELOCIDADES, ClienteTV, carregar_canais, carregar_historico,
                                       conferir_canais, mensagem_fora_do_ar, publicar, registrar_no_historico,
                                       salvar_historico)
from jellyfin_tools.vigia import filtro_prontos

from . import config
from .gui_moderna import JanelaModerna, OpcoesJellyfin

# Ordem em que rodam quando vêm juntos (organizar primeiro: as legendas novas já entram na tradução)
COMANDOS = ("--organizar", "--conferir-espelhos", "--conferir-canais", "--enviar-tv", "--traduzir-legendas",
            "--legendar-audio", "--dublar")
OK, PROBLEMA, FALTA_CONFIGURACAO, ERRO_INESPERADO = 0, 1, 2, 3

# Chave não lembrada no config.json? Vem destas variáveis de ambiente (as mesmas que a janela usa).
VARIAVEIS = {"chave_tmdb": "TMDB_API_KEY", "chave_opensubtitles": "OPENSUBTITLES_API_KEY",
             "chave_subdl": "SUBDL_API_KEY", "jellyfin_url": "JELLYFIN_URL", "jellyfin_api_key": "JELLYFIN_API_KEY",
             "discord_webhook": "DISCORD_WEBHOOK_URL", "telegram_token": "TELEGRAM_BOT_TOKEN",
             "telegram_chat_id": "TELEGRAM_CHAT_ID", "chave_claude": "ANTHROPIC_API_KEY"}
# Os campos sem valor padrão na OpcoesJellyfin: os mesmos valores com que a janela abre da 1ª vez
PADROES = {"modo": "filmes", "origem": "", "destino": "", "tmdb": False, "chave_tmdb": "", "incluir_tmdbid": False,
           "exigir_catalogo": False, "limpar_lixo": True, "apagar_pasta_origem": False, "legendas": True,
           "fonte_legenda": JanelaModerna.FONTES_LEGENDA[0], "chave_opensubtitles": "", "url_site": "",
           "idioma": "pt-BR", "sobrescrever": False, "lembrar_chaves": False}


class FaltaConfiguracao(Exception):
    """Falta algo que só a pessoa pode escolher (pasta, chave): o comando termina com o código 2."""


@dataclass
class Resultado:
    comando: str
    codigo: int
    resumo: str
    detalhes: list[str] = field(default_factory=list)


# ============================================================================ as configurações da janela
def opcoes_salvas() -> tuple[OpcoesJellyfin, dict]:
    """(opções da aba Jellyfin, pastas {"Filmes":..., "Séries":..., "Vídeos comuns":...}) do config.json."""
    tudo = config.carregar()
    dados = dict(tudo.get("jellyfin", {}))
    for chave, variavel in VARIAVEIS.items():
        if not dados.get(chave):
            dados[chave] = os.environ.get(variavel, "")
    campos = {f.name for f in dataclasses.fields(OpcoesJellyfin)}
    o = OpcoesJellyfin(**{**PADROES, **{k: v for k, v in dados.items() if k in campos}})
    for nome in ("pastas_vigiadas", "pastas_protegidas", "filtros_ocultos"):      # no JSON viram listas
        setattr(o, nome, tuple(getattr(o, nome) or ()))
    pastas = {"Filmes": dados.get("destino_filmes") or "", "Séries": dados.get("destino_series") or "",
              "Vídeos comuns": tudo.get("espelho", {}).get("pasta_videos_comuns") or ""}
    return o, pastas


def bibliotecas(pastas: dict) -> list[str]:
    """As bibliotecas escolhidas que existem (sem repetir)."""
    return [p for p in dict.fromkeys(pastas.values()) if p and Path(p).is_dir()]


def notificador(o: OpcoesJellyfin) -> Notificador:
    return Notificador(o.discord_webhook, o.telegram_token, o.telegram_chat_id)


# ============================================================================ usados também pela janela
def catalogo(o: OpcoesJellyfin):
    """Com o TMDB marcado, ele vem PRIMEIRO (fonte oficial); o catálogo local fica de reserva."""
    local = CatalogoLocal.padrao()
    return CatalogoEmCadeia(CatalogoTMDB(o.chave_tmdb), local) if o.tmdb else local


def problema_legendas(o: OpcoesJellyfin) -> str | None:
    fontes = JanelaModerna.FONTES_LEGENDA
    if o.fonte_legenda == fontes[1] and not o.chave_opensubtitles:
        return "Preencha a chave da API do OpenSubtitles (é gratuita em opensubtitles.com)."
    if o.fonte_legenda == fontes[3] and not o.chave_subdl:
        return "Preencha a chave da API do SubDL (é gratuita em subdl.com, no Painel > API)."
    if o.fonte_legenda == fontes[2] and "{consulta}" not in o.url_site:
        return "A URL de busca precisa ter {consulta} no lugar do termo pesquisado.\n" \
               "Ex.: https://site.com/busca?q={consulta}"
    return None


@contextlib.contextmanager
def provedores(o: OpcoesJellyfin):
    """Cria o provedor de legendas escolhido (e desliga o site de demonstração no fim)."""
    fontes = JanelaModerna.FONTES_LEGENDA
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


def montar_config_pos(o: OpcoesJellyfin, provedores_legenda: list, notificar: bool) -> ConfigPos:
    """Legendas, pôster, .nfo, avisos e scan do Jellyfin com as opções da aba Jellyfin."""
    tmdb = ClienteTMDB(o.chave_tmdb) if o.chave_tmdb and (o.imagens_tmdb or o.gerar_nfo) else None
    return ConfigPos(provedores=provedores_legenda, idioma=o.idioma, tmdb=tmdb, imagens=o.imagens_tmdb,
                     nfo=o.gerar_nfo, notificar=notificar, sobrescrever=o.sobrescrever, notificador=notificador(o),
                     jellyfin_url=o.jellyfin_url, jellyfin_api_key=o.jellyfin_api_key if o.atualizar_jellyfin else "")


# ============================================================================ os comandos
def organizar(log: logging.Logger, simular: bool = False) -> Resultado:
    """Como a pasta vigiada: só o que TERMINOU de baixar; filmes para Filmes e episódios para Séries."""
    o, pastas = opcoes_salvas()
    vigiadas = [p for p in (o.pastas_vigiadas or (o.origem,)) if p and Path(p).is_dir() and not problema_no_caminho(p)]
    filmes, series = pastas["Filmes"] or None, pastas["Séries"] or None
    if not vigiadas:
        raise FaltaConfiguracao("Escolha a pasta de origem (ou as pastas vigiadas) na aba Jellyfin.")
    if not (filmes or series):
        raise FaltaConfiguracao("Escolha a biblioteca de Filmes e/ou de Séries na aba Jellyfin.")
    legendas = o.legendas
    if legendas and problema_legendas(o):
        legendas = False
        log.warning("Legendas desligadas nesta rodada: %s", problema_legendas(o))
    log.info("Organizar%s: %s -> filmes: %s | séries: %s", " (SIMULAÇÃO)" if simular else "", ", ".join(vigiadas),
             filmes or "—", series or "—")
    regras = carregar_regras(config.ARQUIVO.parent / "regras_nomes.json")
    todos = []
    for pasta in vigiadas:
        todos += organizar_misto(pasta, filmes, series, catalogo(o), filtro=filtro_prontos(), aplicar=not simular,
                                 incluir_tmdbid=o.incluir_tmdbid, exigir_catalogo=o.exigir_catalogo,
                                 limpar_lixo=o.limpar_lixo, apagar_pasta_origem=o.apagar_pasta_origem,
                                 nomes_episodios=o.nomes_episodios, protegidas=o.pastas_protegidas, regras=regras)
    for m in todos:
        {"erro": log.error, "movido": log.info, "simulado": log.info}.get(m.status, log.warning)("%s", m)
    contagem = {s: sum(m.status == s for m in todos) for s in ("simulado", "movido", "erro", "conflito",
                                                               "nao_identificado")}
    if simular:
        return Resultado("--organizar", OK, f"Simulação: {contagem['simulado']} arquivo(s) seriam movidos, "
                                            f"{contagem['nao_identificado']} não identificado(s). Nada foi mexido.")
    movidos = [m for m in todos if m.status == "movido"]
    legendas_baixadas, scan = 0, ""
    if movidos:
        log.info("Legendas, pôster, .nfo, avisos e scan do Jellyfin")
        with contextlib.ExitStack() as pilha:
            fontes = pilha.enter_context(provedores(o)) if legendas else []
            cfg = montar_config_pos(o, fontes, notificar=True)
            resultados = pos_processar([(m, m.destino.stem) for m in movidos], cfg, log)
        legendas_baixadas = sum(1 for r in resultados if r.legenda and r.legenda.status == "baixada")
        scan = {"pedido": " Jellyfin: biblioteca atualizando.", "sem chave": " Jellyfin: scan não pedido (sem chave)."
                }.get(cfg.scan, f" Jellyfin: {cfg.scan}." if cfg.scan.startswith("erro") else "")
    resumo = (f"{len(movidos)} movido(s), {legendas_baixadas} legenda(s), {contagem['erro']} erro(s), "
              f"{contagem['conflito']} conflito(s), {contagem['nao_identificado']} não identificado(s).{scan}")
    return Resultado("--organizar", PROBLEMA if contagem["erro"] else OK, resumo,
                     [str(m) for m in todos if m.status == "erro"])


def conferir_os_espelhos(log: logging.Logger) -> Resultado:
    o, pastas = opcoes_salvas()
    onde = bibliotecas(pastas)
    if not onde:
        raise FaltaConfiguracao("Escolha a biblioteca de Filmes e/ou de Séries na aba Jellyfin.")
    log.info("Conferindo os espelhos (.strm) em: %s", ", ".join(onde))
    todos, quebrados, removidos = conferir_e_avisar(*onde, notificador=notificador(o), remover=o.remover_quebrados)
    detalhes = []
    for raiz, arquivo, url, v in quebrados:
        texto = f"{'/'.join(arquivo.relative_to(raiz).parts)} -> {url} ({v.problema})"
        log.warning("[quebrado] %s", texto)
        detalhes.append(texto)
    resumo = (f"{len(todos)} espelho(s) conferido(s): {len(todos) - len(quebrados)} funcionando, "
              f"{len(quebrados)} quebrado(s)" + (f", {removidos} removido(s)" if removidos else "") + ".")
    return Resultado("--conferir-espelhos", PROBLEMA if quebrados else OK, resumo, detalhes)


def conferir_os_canais(log: logging.Logger) -> Resultado:
    o, _ = opcoes_salvas()
    canais = carregar_canais(config.ARQUIVO.parent / "canais.json")
    if not canais:
        raise FaltaConfiguracao("A lista de canais está vazia (Jellyfin > TV ao vivo...).")
    velocidade = config.carregar().get("tv", {}).get("velocidade", "Normal")
    log.info("Conferindo %d canal(is) ao vivo (velocidade %s)", len(canais), velocidade)
    with prioridade_baixa():
        situacoes = conferir_canais(canais, VELOCIDADES.get(velocidade, VELOCIDADES["Normal"]))
    for c, s in situacoes:
        log.log(logging.INFO if s.ok else logging.WARNING, "[canal] %s: %s", c.nome, s.detalhe)
    arquivo_historico = config.ARQUIVO.parent / "canais_historico.json"        # a coluna "Últimas" (✓✓✕)
    historico = carregar_historico(arquivo_historico)
    registrar_no_historico(historico, situacoes)
    try:
        salvar_historico(arquivo_historico, historico, canais)
    except OSError as erro:
        log.warning("Não deu para gravar o histórico dos canais: %s", erro)
    fora = [(c, s) for c, s in situacoes if not s.ok]
    avisos = notificador(o)
    if fora and avisos.ativo:
        avisos.enviar(*mensagem_fora_do_ar(fora))
    return Resultado("--conferir-canais", PROBLEMA if fora else OK,
                     f"{len(situacoes)} canal(is) conferido(s): {len(situacoes) - len(fora)} no ar, "
                     f"{len(fora)} fora do ar.", [f"{c.nome}: {s.detalhe}" for c, s in fora])


def enviar_tv(log: logging.Logger) -> Resultado:
    """O mesmo "Salvar e enviar ao Jellyfin" da janela de TV ao vivo, com a lista e as opções salvas."""
    o, _ = opcoes_salvas()
    tudo = config.carregar()
    tv = tudo.get("tv", {})
    pasta = tv.get("pasta") or str(config.ARQUIVO.parent / "tv")
    canais = carregar_canais(config.ARQUIVO.parent / "canais.json")
    if not canais and not tv.get("antena"):
        raise FaltaConfiguracao("A lista de canais está vazia: enviar assim TIRARIA os canais do Jellyfin. "
                                "Se é isso mesmo, envie pela janela (ela pergunta antes).")
    cliente = ClienteTV(o.jellyfin_url, o.jellyfin_api_key) if o.jellyfin_url and o.jellyfin_api_key else None
    log.info("Enviando %d canal(is) ao Jellyfin (lista em %s)", len(canais), pasta)
    feito = []
    if linha := _refazer_channels_xml(canais, pasta):                # canais novos -> coletor de programação
        feito.append(linha)
    feito += publicar(canais, pasta, tv.get("no_servidor", ""), tv.get("guia", ""), cliente, tv.get("antena", ""),
                      mapa_tipos=dict(tudo.get("tv_tipos", {}) or {}))
    if cliente is not None:
        endereco = (tv.get("no_servidor") or "").strip() or str(Path(pasta) / "canais.m3u")
        try:
            if outros := cliente.outros_sintonizadores(endereco):
                feito.append(f"Atenção: o Jellyfin tem mais {len(outros)} sintonizador(es) que não são desta lista "
                             "(os canais deles entram no total).")
        except ErroJellyfin as erro:
            log.warning("Não deu para ver os outros sintonizadores: %s", erro)
    for linha in feito:
        log.info("TV ao vivo: %s", linha)
    if cliente is None:
        return Resultado("--enviar-tv", PROBLEMA, "Lista salva, mas sem o endereço e a chave do Jellyfin (aba Jellyfin) "
                                                  "ele não foi avisado.", feito)
    return Resultado("--enviar-tv", OK, f"{len(canais)} canal(is) enviados ao Jellyfin.", feito)


def _refazer_channels_xml(canais, pasta) -> str:
    """Se o coletor de programação já está montado (channels.xml existe), refaz com a lista atual."""
    from jellyfin_tools.epg_iptv import ARQUIVO_CANAIS_EPG, ErroEPG, baixar_mapa, gravar_channels_xml
    if not (Path(pasta) / ARQUIVO_CANAIS_EPG).is_file():
        return ""
    try:
        _, com, _ = gravar_channels_xml(canais, pasta, baixar_mapa(config.ARQUIVO.parent / "epg_mapa.json"))
    except (ErroEPG, OSError) as erro:
        return f"programação: o channels.xml não foi refeito ({erro})"
    return f"programação: channels.xml refeito ({com} de {len(canais)} canal(is) com guia)"


def escolher_dentro_do_limite(pendentes: list, modelo: str, limite: float) -> tuple[list, float | None]:
    """Os primeiros pendentes cujo custo estimado, somado, cabe no limite (0 = sem limite). (escolhidos, custo)."""
    escolhidos, total = [], 0.0
    for p in pendentes:
        _, _, custo = estimar_custo(p.caracteres, p.falas, modelo)
        if custo is None:
            return (list(pendentes), None) if limite <= 0 else ([], None)
        if limite > 0 and total + custo > limite:
            break
        escolhidos.append(p)
        total += custo
    return escolhidos, total


def traduzir_legendas(log: logging.Logger, limite: float = 1.0) -> Resultado:
    o, pastas = opcoes_salvas()
    onde = bibliotecas(pastas)
    if not onde:
        raise FaltaConfiguracao("Escolha a biblioteca de Filmes e/ou de Séries na aba Jellyfin.")
    if not (o.chave_claude or os.environ.get("ANTHROPIC_API_KEY")):
        raise FaltaConfiguracao("Falta a chave da API da Anthropic (aba Jellyfin > Legendas, com \"Lembrar as "
                                "chaves\" marcado, ou a variável de ambiente ANTHROPIC_API_KEY).")
    idioma = o.idioma.split(",")[0].strip() or "pt-BR"
    pendentes = legendas_para_traduzir(*onde, idioma=idioma)
    if not pendentes:
        return Resultado("--traduzir-legendas", OK, f"Nada a traduzir: os vídeos já têm legenda em {idioma}.")
    escolhidos, estimado = escolher_dentro_do_limite(pendentes, o.modelo_traducao, limite)
    if estimado is None and not escolhidos:
        raise FaltaConfiguracao(f"O preço do modelo {o.modelo_traducao} é desconhecido: não dá para respeitar o "
                                "limite. Use --limite-dolares 0 (sem limite) ou o modelo padrão.")
    if not escolhidos:                              # senão o robô rodaria todo dia sem traduzir nada
        raise FaltaConfiguracao(f"A primeira legenda ({pendentes[0].origem.name}) sozinha já passa do limite de "
                                f"US$ {limite:.2f}: aumente o --limite-dolares.")
    log.info("Traduzir legendas: %d pendente(s); %d cabem no limite (%s), custo estimado %s", len(pendentes),
             len(escolhidos), f"US$ {limite:.2f}" if limite > 0 else "sem limite",
             f"US$ {estimado:.2f}" if estimado is not None else "desconhecido")
    tradutor = Tradutor(chave=o.chave_claude, modelo=o.modelo_traducao, idioma=idioma)
    resultados = []
    for p in escolhidos:
        r = traduzir_arquivo(p.origem, p.destino, tradutor, titulo=p.video.stem)
        resultados.append(r)
        (log.error if r.status == "erro" else log.info)("[%s] %s -> %s%s", r.status, r.origem.name, r.destino.name,
                                                         f" ({r.detalhe})" if r.detalhe else "")
        if r.status == "erro" and r.detalhe.startswith(("a chave", "sem conexão", "limite", "modelo não")):
            break                                       # vale para todos: não insiste nos outros
    traduzidas = [r for r in resultados if r.status == "traduzida"]
    erros = [r for r in resultados if r.status == "erro"]
    if traduzidas and o.atualizar_jellyfin and o.jellyfin_url and o.jellyfin_api_key:
        try:
            atualizar_biblioteca(o.jellyfin_url, o.jellyfin_api_key)
        except ErroJellyfin as erro:
            log.warning("Jellyfin: scan não pedido (%s)", erro)
    custo = tradutor.custo
    resumo = (f"{len(traduzidas)} de {len(pendentes)} legenda(s) traduzida(s), {len(erros)} erro(s)"
              + (f", {len(pendentes) - len(escolhidos)} para a próxima vez (limite de US$ {limite:.2f})"
                 if len(escolhidos) < len(pendentes) else "")
              + f". Modelo {tradutor.modelo}, {tradutor.tokens_entrada + tradutor.tokens_saida} tokens"
              + (f", custo ~US$ {custo:.2f}." if custo is not None else "."))
    return Resultado("--traduzir-legendas", PROBLEMA if erros else OK, resumo,
                     [f"{r.origem.name}: {r.detalhe}" for r in erros])


def legendar_audio(log: logging.Logger, limite_videos: int = 5, limite: float = 1.0) -> Resultado:
    """Os vídeos sem NENHUMA legenda: o Whisper ouve no PC e o Claude traduz (se houver chave e o áudio não for
    português). No máximo `limite_videos` por execução (0 = todos); o resto fica para a próxima."""
    o, pastas = opcoes_salvas()
    onde = bibliotecas(pastas)
    if not onde:
        raise FaltaConfiguracao("Escolha a biblioteca de Filmes e/ou de Séries na aba Jellyfin.")
    idioma = o.idioma.split(",")[0].strip() or "pt-BR"
    itens = videos_sem_legenda(*onde, idioma=idioma)
    if not itens:
        return Resultado("--legendar-audio", OK, "Nenhum vídeo sem legenda.")
    escolhidos = itens[:limite_videos] if limite_videos > 0 else itens
    tradutor = None
    if o.chave_claude or os.environ.get("ANTHROPIC_API_KEY"):
        tradutor = Tradutor(chave=o.chave_claude, modelo=o.modelo_traducao, idioma=idioma)
    log.info("Legendar pelo áudio: %d sem legenda, %d nesta execução (Whisper %s, %s)", len(itens), len(escolhidos),
             o.modelo_whisper, "com tradução" if tradutor else "sem tradução: falta a chave da Anthropic")
    transcritor = Transcritor(modelo=o.modelo_whisper, usar_gpu=o.whisper_gpu,
                              pasta_modelos=str(config.ARQUIVO.parent / "modelos_whisper"))
    resultados = []
    for item in escolhidos:
        if tradutor is not None and limite > 0 and tradutor.custo is not None and tradutor.custo >= limite:
            log.warning("Limite de US$ %.2f atingido: o resto fica para a próxima", limite)
            break
        r = legendar_pelo_audio(item.video, transcritor, tradutor, idioma)
        resultados.append(r)
        (log.error if r.status == "erro" else log.info)("[%s] %s%s (áudio: %s)", r.status, r.video.name,
                                                         f" ({r.detalhe})" if r.detalhe else "", r.idioma_audio or "?")
        if r.status == "erro" and r.detalhe.startswith(("não deu para carregar o modelo", "falta a biblioteca",
                                                        "a chave", "sem conexão", "limite", "modelo não")):
            break
    for aviso in dict.fromkeys(a for r in resultados for a in r.avisos):
        log.warning("Whisper: %s", aviso)
    feitas = [r for r in resultados if r.status in ("criada", "traduzida")]
    erros = [r for r in resultados if r.status == "erro"]
    if feitas and o.atualizar_jellyfin and o.jellyfin_url and o.jellyfin_api_key:
        try:
            atualizar_biblioteca(o.jellyfin_url, o.jellyfin_api_key)
        except ErroJellyfin as erro:
            log.warning("Jellyfin: scan não pedido (%s)", erro)
    resumo = (f"{len(feitas)} de {len(resultados)} legenda(s) em {idioma} criada(s), {len(erros)} erro(s)"
              + (f", {len(itens) - len(resultados)} vídeo(s) para a próxima vez" if len(resultados) < len(itens) else "")
              + (f". Claude ~US$ {tradutor.custo:.2f}." if tradutor is not None and tradutor.custo else "."))
    return Resultado("--legendar-audio", PROBLEMA if erros else OK, resumo,
                     [f"{r.video.name}: {r.detalhe}" for r in erros])


def dublar(log: logging.Logger, limite_videos: int = 5) -> Resultado:
    """Os filmes com legenda em português e sem áudio em português ganham 'Nome - Dublado IA.mkv'."""
    o, pastas = opcoes_salvas()
    filmes = pastas["Filmes"]
    if not filmes or not Path(filmes).is_dir():
        raise FaltaConfiguracao("Escolha a biblioteca de Filmes na aba Jellyfin (a dublagem é só para filmes).")
    itens = videos_para_dublar(filmes, idioma=o.idioma.split(",")[0].strip() or "pt-BR")
    if not itens:
        return Resultado("--dublar", OK, "Nenhum filme para dublar.")
    escolhidos = itens[:limite_videos] if limite_videos > 0 else itens
    pasta = config.ARQUIVO.parent
    try:
        motor = MotorPiper(preparar_piper(pasta / "piper"), preparar_voz(o.voz_dublagem, pasta / "vozes"))
    except ErroDublagem as erro:
        return Resultado("--dublar", PROBLEMA, f"Não deu para preparar a voz: {erro}")
    log.info("Dublar: %d filme(s), %d nesta execução (voz %s)", len(itens), len(escolhidos), o.voz_dublagem)
    resultados = []
    for item in escolhidos:
        r = dublar_video(item.video, item.legenda, motor)
        resultados.append(r)
        (log.error if r.status == "erro" else log.info)("[%s] %s%s", r.status, r.video.name,
                                                         f" ({r.detalhe})" if r.detalhe else "")
    feitos = [r for r in resultados if r.status == "dublado"]
    erros = [r for r in resultados if r.status == "erro"]
    if feitos and o.atualizar_jellyfin and o.jellyfin_url and o.jellyfin_api_key:
        try:
            atualizar_biblioteca(o.jellyfin_url, o.jellyfin_api_key)
        except ErroJellyfin as erro:
            log.warning("Jellyfin: scan não pedido (%s)", erro)
    resumo = (f"{len(feitos)} de {len(resultados)} filme(s) dublado(s), {len(erros)} erro(s)"
              + (f", {len(itens) - len(resultados)} para a próxima vez." if len(resultados) < len(itens) else "."))
    return Resultado("--dublar", PROBLEMA if erros else OK, resumo, [f"{r.video.name}: {r.detalhe}" for r in erros])


# ============================================================================ entrada
def foi_pedido(argv: list[str]) -> bool:
    """Algum comando de robô na linha? (senão, o programa abre a janela normalmente)"""
    return any(a in COMANDOS for a in argv)


def _argumentos() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="Maestro.exe", description="Comandos para robôs (RPA): nenhuma janela abre.",
                                epilog="Códigos de saída: 0 tudo certo, 1 achou problema, 2 falta configuração, "
                                       "3 erro inesperado.")
    for comando in COMANDOS:
        p.add_argument(comando, action="store_true")
    p.add_argument("--simular", action="store_true", help="organizar: só mostra o que faria")
    p.add_argument("--limite-dolares", type=float, default=1.0,
                   help="traduzir: no máximo este custo estimado por execução (0 = sem limite)")
    p.add_argument("--limite-videos", type=int, default=5,
                   help="legendar-audio: quantos vídeos por execução (0 = todos)")
    p.add_argument("--resultado", help="onde gravar o resumo em JSON (padrão ~/.videoscraper/rpa/ultimo.json)")
    return p


def _rodar(comando: str, args, log: logging.Logger) -> Resultado:
    acoes = {"--organizar": lambda: organizar(log, args.simular),
             "--conferir-espelhos": lambda: conferir_os_espelhos(log),
             "--conferir-canais": lambda: conferir_os_canais(log),
             "--enviar-tv": lambda: enviar_tv(log),
             "--traduzir-legendas": lambda: traduzir_legendas(log, args.limite_dolares),
             "--legendar-audio": lambda: legendar_audio(log, args.limite_videos, args.limite_dolares),
             "--dublar": lambda: dublar(log, args.limite_videos)}
    try:
        return acoes[comando]()
    except FaltaConfiguracao as falta:
        log.error("%s: %s", comando, falta)
        return Resultado(comando, FALTA_CONFIGURACAO, str(falta))
    except Exception as erro:                       # o robô recebe 3; o motivo completo fica no log
        log.critical("%s: erro inesperado: %s\n%s", comando, erro, traceback.format_exc())
        return Resultado(comando, ERRO_INESPERADO, f"Erro inesperado: {erro}")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    pasta = config.ARQUIVO.parent
    destino_json = pasta / "rpa" / "ultimo.json"
    try:                                            # o Maestro.exe não tem console: um erro aqui não pode sumir
        args = _argumentos().parse_args([a for a in argv if a not in ("--classica", "--texto")])
    except SystemExit:
        _gravar_json(destino_json, {"codigo": FALTA_CONFIGURACAO, "resumo": f"Comando não entendido: {argv}"})
        return FALTA_CONFIGURACAO
    if args.resultado:
        destino_json = Path(args.resultado)
    log = configurar_log(pasta / "jellyfin_organizer.log")
    pedidos = [c for c in COMANDOS if getattr(args, c[2:].replace("-", "_"))]
    handler, arquivo_log = iniciar_log_da_acao("RPA " + " ".join(c[2:] for c in pedidos), pasta / "logs")
    inicio = datetime.now()
    resultados = []
    try:
        for comando in pedidos:
            log.info("=== %s ===", comando)
            r = _rodar(comando, args, log)
            log.info("=== %s: código %d. %s ===", comando, r.codigo, r.resumo)
            resultados.append(r)
    finally:
        encerrar_log_da_acao(handler)
    codigo = max((r.codigo for r in resultados), default=OK)
    _gravar_json(destino_json, {"inicio": inicio.isoformat(timespec="seconds"),
                                "fim": datetime.now().isoformat(timespec="seconds"), "codigo": codigo,
                                "log": str(arquivo_log), "comandos": [dataclasses.asdict(r) for r in resultados]})
    if sys.stdout is not None:                     # rodando pelo Python num terminal: mostra o resumo
        for r in resultados:
            print(f"{r.comando}: código {r.codigo}. {r.resumo}")
    return codigo


def _gravar_json(destino: Path, dados: dict) -> None:
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass                                        # sem onde gravar: o código de saída e o log continuam valendo
