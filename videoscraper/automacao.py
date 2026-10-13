"""Comandos de linha para robôs (RPA: UiPath, BotCity, Agendador de Tarefas do Windows).

    Maestro.exe --organizar            organiza o que terminou de baixar (filmes e séries)
    Maestro.exe --conferir-espelhos    confere os links dos .strm (e avisa no Discord/Telegram se quebrou)
    Maestro.exe --conferir-canais      confere os canais da TV ao vivo (e avisa se algum saiu do ar)
    Maestro.exe --enviar-tv            envia a lista de canais ao Jellyfin (o mesmo "Salvar e enviar")
    Maestro.exe --traduzir-legendas    traduz com a IA (Claude) as legendas que faltam
    Maestro.exe --legendar-audio       cria a legenda ouvindo o áudio (Whisper no PC + Claude) dos vídeos sem nenhuma
    Maestro.exe --dublar               dubla com voz sintética (Piper) os filmes com legenda em português
    Maestro.exe --sincronizar-legendas corrige legendas adiantadas/atrasadas (compara com a voz do áudio)

Dá para juntar vários (rodam nessa ordem): Maestro.exe --organizar --traduzir-legendas
Opções:  --simular (organizar: só mostra o que faria)   --limite-dolares 1.00 (traduzir: 0 = sem limite)
         --economico (traduzir: em lote, metade do preço; fica pronto em até 24 h e a próxima execução grava)
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
import hashlib
import json
import logging
import os
import shutil
import subprocess
import re
import sys
import time
import traceback
from collections import Counter
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
from jellyfin_tools.registro import configurar_log, encerrar_log_da_acao, iniciar_log_da_acao, obter_logger
from jellyfin_tools.regras import carregar_regras
from jellyfin_tools.resumo_diario import ResumoDiario
from jellyfin_tools.servidor_jellyfin import ErroJellyfin, atualizar_biblioteca
from jellyfin_tools.site_demo import iniciar_site_demo
from jellyfin_tools.traducao import (_PORTUGUES, ErroTraducao, Tradutor, estimar_custo, legendas_para_traduzir,
                                     traduzir_arquivo)
from jellyfin_tools import traducao_lote
from jellyfin_tools.sincronia import Conferidas, legendas_para_sincronizar, sincronizar
from jellyfin_tools.transcricao import Transcritor, legendar_pelo_audio, videos_sem_legenda
from jellyfin_tools.dublagem import (PREFIXO_CLOUD, PREFIXO_PIPER, ErroDublagem, MotorMisto, MotorPiper, dublar_video,
                                     chave_da_fala, episodios_para_dublar, esquecer_fala, falas_da_legenda, horarios,
                                     ler_pronuncias, localizar_ffmpeg, motor_expressivo, pasta_do_filme, salvar_ajuste,
                                     preparar_piper, preparar_voz, videos_para_dublar)
from jellyfin_tools.legendas import ErroLegenda
from jellyfin_tools.tv_ao_vivo import (VELOCIDADES, ClienteTV, carregar_canais, carregar_historico,
                                       conferir_canais, mensagem_fora_do_ar, publicar, registrar_no_historico,
                                       salvar_historico)
from jellyfin_tools import cotacao, gastos, personagens, tom, vigia, voz_clonada, voz_cloud, voz_gemini
from jellyfin_tools.adaptacao import Adaptador
from jellyfin_tools.vigia import filtro_prontos

from . import agendador, config
from .gui_moderna import JanelaModerna, OpcoesJellyfin

# Ordem em que rodam quando vêm juntos (organizar primeiro: as legendas novas já entram na tradução)
COMANDOS = ("--organizar", "--conferir-espelhos", "--conferir-canais", "--enviar-tv", "--traduzir-legendas",
            "--legendar-audio", "--sincronizar-legendas", "--dublar", "--avulsos", "--continuar-dublagem")
OK, PROBLEMA, FALTA_CONFIGURACAO, ERRO_INESPERADO = 0, 1, 2, 3

# Chave não lembrada no config.json? Vem destas variáveis de ambiente (as mesmas que a janela usa).
VARIAVEIS = {"chave_tmdb": "TMDB_API_KEY", "chave_opensubtitles": "OPENSUBTITLES_API_KEY",
             "chave_subdl": "SUBDL_API_KEY", "jellyfin_url": "JELLYFIN_URL", "jellyfin_api_key": "JELLYFIN_API_KEY",
             "discord_webhook": "DISCORD_WEBHOOK_URL", "telegram_token": "TELEGRAM_BOT_TOKEN",
             "telegram_chat_id": "TELEGRAM_CHAT_ID", "chave_claude": "ANTHROPIC_API_KEY",
             "chave_gemini": "GEMINI_API_KEY", "chave_cloud_tts": "GOOGLE_TTS_API_KEY"}
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
    contagens: dict = field(default_factory=dict)      # para o resumo do dia (Discord/Telegram)


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
    configurar_gastos(o)                                  # os robôs também anotam os gastos e respeitam o teto
    return o, pastas


def arquivo_cotacao() -> Path:
    return config.ARQUIVO.parent / "cotacao_dolar.json"


def conversao_reais(o: OpcoesJellyfin, consultar: bool = True) -> tuple[float | None, str]:
    """(reais por dólar já com o IOF, de onde veio) para mostrar os gastos em reais; (None, motivo) se for em dólar
    ou se ainda não há cotação (sem internet na 1ª vez e sem cotação manual). consultar=False: só a guardada."""
    if o.moeda_gastos != "R$":
        return None, ""
    iof = max(0.0, float(o.iof_cartao or 0))
    if o.cotacao_dolar and o.cotacao_dolar > 0:
        valor, origem = float(o.cotacao_dolar), "cotação fixa"
    else:
        dados = (cotacao.atual(arquivo_cotacao()) if consultar else cotacao.carregar(arquivo_cotacao()))
        if not dados:
            return None, "sem cotação ainda (sem internet?): mostrando em dólar"
        valor, origem = float(dados["valor"]), f"PTAX de {cotacao.data_br(dados.get('data', ''))}, Banco Central"
    iof_texto = f"{iof:g}".replace(".", ",")
    texto = f"US$ 1 = {cotacao.em_reais(valor)} ({origem}) + IOF {iof_texto}%"
    return valor * (1 + iof / 100), texto


def configurar_gastos(o: OpcoesJellyfin, consultar: bool = True):
    """Liga o registro dos gastos com o teto e a moeda da tela. Sem cotação (em reais), o teto não é aplicado em
    dólares por engano: fica sem teto até a cotação chegar."""
    fator, texto = conversao_reais(o, consultar)
    teto = o.teto_gastos if (fator or o.moeda_gastos != "R$") else 0.0
    voz_gemini.usar_flex(getattr(o, "gemini_flex", False))      # modo econômico do Gemini (metade do preço)
    return gastos.configurar(arquivo_gastos(), teto, fator=fator, conversao=texto,
                             plano_gemini=getattr(o, "plano_gemini", "?"))


def arquivo_gastos() -> Path:
    """Os gastos estimados por mês nas APIs pagas (Claude e Gemini), junto das configurações."""
    return config.ARQUIVO.parent / "gastos.json"


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


def usa_gemini(o: OpcoesJellyfin) -> bool:
    return o.motor_voz.startswith("Gemini")


def usa_cloud(o: OpcoesJellyfin) -> bool:
    return o.motor_voz.startswith("Google Cloud")


def chave_cloud(o: OpcoesJellyfin) -> str:
    """A chave do Google Cloud (Text-to-Speech): a do campo ou, vazio, a variável GOOGLE_TTS_API_KEY."""
    return o.chave_cloud_tts or os.environ.get("GOOGLE_TTS_API_KEY", "")


def motor_cloud(o: OpcoesJellyfin):
    if not chave_cloud(o):
        raise FaltaConfiguracao("Para a voz do Google Cloud TTS, crie a chave em console.cloud.google.com (ative a "
                                "\"Cloud Text-to-Speech API\" > Credenciais > Criar chave de API) e cole em "
                                "Configurações > Chaves de API (ou use o Piper, grátis).")
    return voz_cloud.MotorCloudTTS(chave_cloud(o), o.voz_cloud)


def chave_gemini(o: OpcoesJellyfin) -> str:
    """A chave do Google AI Studio: a do campo ou, vazio, a variável GEMINI_API_KEY."""
    return o.chave_gemini or os.environ.get("GEMINI_API_KEY", "")


def arquivo_vozes_clonadas() -> Path:
    """As chaves das vozes clonadas (réplica do Gemini): só neste PC, junto das configurações."""
    return config.ARQUIVO.parent / "vozes_clonadas.json"


def vozes_clonadas() -> list:
    return voz_clonada.carregar(arquivo_vozes_clonadas())


def conferir_voz_clonada(voz: str, vozes: list) -> None:
    """A voz principal é uma clonada? Ela precisa existir neste PC e não ter vencido."""
    if not voz_clonada.e_clonada(voz):
        return
    achada = next((v for v in vozes if v.valor == voz), None)
    if achada is None:
        raise FaltaConfiguracao(f"A voz clonada \"{voz_clonada.nome_da_voz(voz)}\" não está neste PC. Clone de novo "
                                "em Configurações > Dublagem (ou escolha uma voz pronta).")
    if achada.vencida():
        raise FaltaConfiguracao(f"A chave da voz clonada \"{achada.nome}\" venceu. Clone de novo em Configurações > "
                                "Dublagem (grave a referência e o consentimento outra vez).")


def motor_piper(o: OpcoesJellyfin, voz: str = "", progresso_piper=None, progresso_voz=None) -> MotorPiper:
    """O Piper (grátis, no PC) com a voz dada (ou a da tela). Baixa o programa e a voz só na 1ª vez."""
    pasta = config.ARQUIVO.parent
    return MotorPiper(preparar_piper(pasta / "piper", ao_progresso=progresso_piper),
                      preparar_voz(voz or o.voz_dublagem, pasta / "vozes", ao_progresso=progresso_voz))


def figurantes_no_cloud(o: OpcoesJellyfin) -> bool:
    """Mista com a opção "Figurantes com o Google Cloud enquanto a cota grátis do mês der" (e a chave)."""
    return bool(usa_gemini(o) and o.figurantes_piper and getattr(o, "figurantes_cloud", False) and chave_cloud(o))


def figurante(o: OpcoesJellyfin) -> str | None:
    """Dublagem mista: a voz dos figurantes ("piper:faber" ou "cloud:Neural2", o tipo do Google Cloud: cada
    figurante ganha uma voz do gênero dele), ou None (todos com o Gemini)."""
    if not (usa_gemini(o) and o.figurantes_piper):
        return None
    if figurantes_no_cloud(o):
        return f"{PREFIXO_CLOUD}{o.tipo_cloud if o.tipo_cloud in voz_cloud.TIPOS else voz_cloud.TIPO_PADRAO}"
    return f"{PREFIXO_PIPER}{o.voz_dublagem}"


def jeito_do_gemini(o: OpcoesJellyfin) -> tuple[int, int, int]:
    """(pedidos ao mesmo tempo, falas por pedido, letras por pedido) da voz do Gemini. Na chave GRÁTIS o limite conta
    pedidos: 1 por vez (o limite por minuto é baixo) e, com a opção ligada, blocos de 20 falas (menos pedidos)."""
    if getattr(o, "plano_gemini", "?") != "gratis":
        return voz_gemini.SIMULTANEOS, voz_gemini.BLOCO, voz_gemini.LETRAS_POR_BLOCO
    if getattr(o, "gemini_blocos_maiores", True):
        return voz_gemini.SIMULTANEOS_GRATIS, voz_gemini.BLOCO_GRATIS, voz_gemini.LETRAS_GRATIS
    return voz_gemini.SIMULTANEOS_GRATIS, voz_gemini.BLOCO, voz_gemini.LETRAS_POR_BLOCO


FALAS_POR_MINUTO = 15         # para estimar o teste antes do Whisper (um diálogo comum tem de 10 a 20 por minuto)


def pedidos_de_voz_estimados(o: OpcoesJellyfin, falas: int) -> int:
    """Quantos pedidos de voz ao Gemini para `falas` falas (com o tamanho de bloco da chave)."""
    _, bloco, _ = jeito_do_gemini(o)
    return max(1, -(-int(falas) // bloco))


def aviso_do_saldo_gemini(o: OpcoesJellyfin, falas: int | None = None) -> str:
    """Chave grátis, ANTES de começar: o limite do dia já acabou, ou os pedidos de voz deste trabalho não cabem no
    que resta hoje? ('' quando cabe, quando o limite ainda é desconhecido ou fora da chave grátis.) falas=None:
    avisa só se já acabou."""
    atual = gastos.atual()
    if not usa_gemini(o) or atual is None or getattr(o, "plano_gemini", "?") == "pago":
        return ""
    restam = atual.restam_hoje("voz")
    if restam is None:
        return ""
    volta = atual.virada_do_dia()
    if restam <= 0:
        return (f"O limite do dia da chave grátis do Gemini (voz) já acabou hoje: volta às {volta}. Se começar agora, "
                "para no 1º pedido de voz (o que ficar pronto é guardado e continua depois).")
    precisa = pedidos_de_voz_estimados(o, falas) if falas else 0
    if precisa > restam:
        return (f"Este trabalho deve usar ~{precisa} pedido(s) de voz do Gemini e restam ~{restam} hoje na chave "
                f"grátis: pode parar no meio (o que ficar pronto é guardado e continua depois das {volta}).")
    return ""


def preparar_motor(o: OpcoesJellyfin, progresso_piper=None, progresso_voz=None):
    """A voz da dublagem: Gemini (premium, com a chave do AI Studio) ou Piper (grátis; baixa na 1ª vez). Com os
    figurantes no Piper (mista), um MotorMisto: cada fala vai para o motor da voz dela."""
    if usa_cloud(o):
        return motor_cloud(o)
    if usa_gemini(o):
        if not chave_gemini(o):
            raise FaltaConfiguracao("Para a voz premium do Gemini, crie a chave em aistudio.google.com (Get API key) "
                                    "e cole no campo \"Chave do Google AI Studio\" (ou use o Piper, grátis).")
        clonadas = vozes_clonadas()
        conferir_voz_clonada(o.voz_gemini, clonadas)
        simultaneos, bloco, letras = jeito_do_gemini(o)
        if simultaneos == voz_gemini.SIMULTANEOS_GRATIS:
            obter_logger().info("Dublagem: chave grátis do Gemini: 1 pedido de voz por vez%s (para não esbarrar no "
                                "limite por minuto)", f", até {bloco} falas por pedido" if bloco > voz_gemini.BLOCO
                                else "")
        gemini = voz_gemini.MotorGemini(chave_gemini(o), o.voz_gemini,
                                        vozes_clonadas=voz_clonada.chaves([v for v in clonadas if not v.vencida()]),
                                        avisar=lambda texto: obter_logger().info("Dublagem: %s", texto),
                                        simultaneos=simultaneos, bloco=bloco, letras=letras)
        if not o.figurantes_piper:
            return gemini
        return MotorMisto(gemini, lambda voz: motor_piper(o, voz),
                          cloud=(lambda: motor_cloud(o)) if figurantes_no_cloud(o) else None,
                          reserva=o.voz_dublagem, avisar=lambda texto: obter_logger().warning("Dublagem: %s", texto))
    return motor_piper(o, progresso_piper=progresso_piper, progresso_voz=progresso_voz)


def ouvinte_de_tons(o: OpcoesJellyfin, video: str | Path, motor, log: logging.Logger | None = None):
    """Quem ouve o original (tom.py) e diz, de cada fala, se quem fala é homem ou mulher (SEMPRE, nas abas Jellyfin e
    Avulsos, no teste e no vídeo inteiro: a voz segue o gênero) e, com a "Emoção da cena" ligada, o tom e a cena,
    para a voz repetir a interpretação. Com o Piper ou o Google Cloud (não interpretam): só os sons sem fala, se
    eles forem voltar (separação das vozes e "Manter os sons" ligados). None: sem a chave do Gemini, ou nos robôs
    "só com o Piper (sem custo)"."""
    if not chave_gemini(o) or getattr(o, "sem_gemini", False):
        return None
    video = Path(video)
    if not motor_expressivo(motor):                   # Piper / Google Cloud: só os sons sem fala (se forem voltar)
        if not (getattr(o, "manter_sons", True) and getattr(o, "separar_vozes", False)):
            return None

        def so_os_sons(falas, ids, pasta, parar):
            ffmpeg = localizar_ffmpeg()
            if not ffmpeg:
                raise ErroDublagem("falta o ffmpeg (pip install imageio-ffmpeg)")
            aviso = (lambda texto: log.warning("Dublagem: %s", texto)) if log else None
            if log:
                log.info("Dublagem: o Gemini está ouvindo só os sons sem fala do original (bocejo, risada, gemido): "
                         "a voz não interpreta, mas os sons voltam")
            tom.ouvir_sons(video, falas, ids, voz_gemini._cliente(chave_gemini(o), aviso), ffmpeg,
                           Path(pasta) / "tons.json", parar=parar, avisar=aviso)
            return {}                                 # sem tom: a voz do Piper/Google Cloud não usa
        return so_os_sons
    emocao = getattr(o, "emocao_da_cena", True)

    def ouvir(falas, ids, pasta, parar):
        ffmpeg = localizar_ffmpeg()
        if not ffmpeg:
            raise ErroDublagem("falta o ffmpeg (pip install imageio-ffmpeg)")
        if log:
            log.info("Dublagem: o Gemini está ouvindo %d falas no original (quem fala: homem ou mulher%s)",
                     len(ids), "; e a emoção da cena" if emocao else "")
        aviso = (lambda texto: log.warning("Dublagem: %s", texto)) if log else None
        ouvidas = tom.ouvir_falas(video, falas, ids, voz_gemini._cliente(chave_gemini(o), aviso), ffmpeg,
                                  Path(pasta) / "tons.json", parar=parar, avisar=aviso)
        if not emocao:                                # emoção desligada: só o gênero (a voz certa)
            ouvidas = {k: tom.Ouvida(genero=x.genero) for k, x in ouvidas.items()}
        if log:
            generos = Counter(x.genero for x in ouvidas.values())
            log.info("Dublagem: ouvidas %d falas (%d de mulher, %d de homem, %d sem saber)", len(ouvidas),
                     generos["f"], generos["m"], generos["?"])
        return ouvidas
    return ouvir


def vozes_por_genero(o: OpcoesJellyfin, motor) -> dict | None:
    """{"m": voz, "f": voz}: a voz escolhida fica com o gênero dela, e o outro gênero ganha uma voz pronta do Gemini
    (a fala de mulher não sai com voz de homem). None: sem a escuta do original ou com uma voz clonada (é a SUA voz,
    escolhida para tudo)."""
    if not chave_gemini(o) or not motor_expressivo(motor):
        return None
    voz = o.voz_gemini if o.voz_gemini in voz_gemini.VOZES else ("" if o.voz_gemini.startswith("clone:")
                                                                  else voz_gemini.VOZ_PADRAO)
    if not voz:
        return None
    if voz_gemini.VOZES[voz].startswith("masculina"):
        base = {"m": voz, "f": voz_gemini.VOZES_FEMININAS[0]}
    else:
        base = {"f": voz, "m": voz_gemini.VOZES_MASCULINAS[0]}
    for (genero, idade), opcoes in personagens.VOZES_POR_IDADE.items():    # criança, jovem e idoso: a voz da idade
        base[f"{genero}:{idade}"] = opcoes[0]
    return base


def pronuncias_de(o: OpcoesJellyfin) -> dict:
    """Configurações > Dublagem > Pronúncia: {"Johnson": "Djônson"} (a voz lê assim; a legenda não muda)."""
    return ler_pronuncias(getattr(o, "pronuncias", ""))


def registrar_qualidade(log: logging.Logger, r, onde: str = "Dublagem") -> None:
    """O relatório de qualidade no log: as falas para conferir (aceleradas demais, cortadas, sem som)."""
    problemas = getattr(r, "problemas", None) or []
    if not problemas:
        return
    log.warning("%s: %d fala(s) para conferir em %s:", onde, len(problemas), Path(r.video).name)
    for linha in problemas[:40]:
        log.warning("  %s", linha)
    if len(problemas) > 40:
        log.warning("  ... e mais %d", len(problemas) - 40)


NOMES_DAS_APIS = {"Claude": "Claude (tradução e falas encurtadas)", "Gemini (voz)": "Gemini (voz)",
                  "Gemini (escuta)": "Gemini (ouvir o original: quem fala e emoção)", "Gemini": "Gemini",
                  "Google TTS": "Google Cloud TTS"}
DICAS_DE_ECONOMIA = {
    "Gemini (voz)": "ligue o \"Modo econômico do Gemini (Flex)\" em Configurações > Gastos (metade do preço, mais "
                    "lento) ou use o Piper/Google Cloud nos figurantes",
    "Gemini (escuta)": "desligar a \"Emoção da cena\" deixa a escuta mais curta (o gênero de quem fala continua)",
    "Claude": "a \"Tradução econômica\" (em lote, metade do preço, pronta em até 24 h) ou a tradução local, grátis",
    "Google TTS": "a cota grátis do mês acabou: o resto do mês fica mais barato no Piper",
}


def foto_dos_gastos() -> dict | None:
    """Uso e gasto de cada API agora (para medir quanto um teste custou em cada uma)."""
    atual = gastos.atual()
    return atual.foto() if atual is not None else None


def custos_por_api(antes: dict | None) -> dict[str, tuple[float, bool]]:
    """{API: (US$, foi grátis?)} desde a foto `antes` (foto_dos_gastos)."""
    return gastos.custos_entre(antes, foto_dos_gastos())


def texto_dos_custos(custos: dict, valor=None) -> str:
    """"Claude (tradução) R$ 0,05 · Gemini (voz) R$ 0,40 · Gemini (ouvir) grátis" + a dica da mais cara."""
    if not custos:
        return ""
    atual = gastos.atual()
    valor = valor or (atual.valor if atual is not None else (lambda d: f"US$ {d:.2f}"))
    partes = [f"{NOMES_DAS_APIS.get(api, api)}: " + ("grátis" if gratis else valor(usd))
              for api, (usd, gratis) in sorted(custos.items(), key=lambda x: -x[1][0])]
    pagos = {api: usd for api, (usd, gratis) in custos.items() if not gratis and usd > 0}
    dica = ""
    if pagos and (mais := max(pagos, key=pagos.get)) in DICAS_DE_ECONOMIA:
        dica = f"\nPara economizar em {NOMES_DAS_APIS.get(mais, mais)}, que foi a mais cara: {DICAS_DE_ECONOMIA[mais]}."
    return "Custos por API:\n" + "\n".join(f"• {p}" for p in partes) + dica


NOMES_DAS_COTAS = {"Claude": "os créditos da Anthropic (Claude) acabaram: recarregue em console.anthropic.com",
                   "Gemini": "o limite do dia do Gemini acabou (chave grátis: volta amanhã; com faturamento, é pago)"}


def cotas_que_acabaram(antes: dict | None) -> list[str]:
    """As cotas grátis (ou créditos) que acabaram desde a foto `antes`: o aviso "agora é pago"."""
    depois = foto_dos_gastos()
    if not antes or not depois:
        return []
    novas = [api for api, c in depois.get("cotas", {}).items() if antes.get("cotas", {}).get(api) != c]
    return [NOMES_DAS_COTAS.get(api, f"a cota grátis do mês do {api.replace('Google TTS', 'Google Cloud TTS (')}"
                                     f"{')' if api.startswith('Google TTS') else ''} acabou: daqui para frente é pago")
            for api in novas]


def gasto_ate_agora() -> float:
    """US$ gastos no mês (Claude + Gemini), para medir quanto custou um teste."""
    atual = gastos.atual()
    return atual.total() if atual is not None else 0.0


def previsao_pelo_teste(video: str | Path, duracao: float | None) -> str:
    """"Pelo teste deste vídeo (US$ 0.03 em 2 min), o vídeo inteiro (98 min) deve custar ~US$ 1.47." — a conta com o
    custo REAL do teste (escuta, voz, blocos refeitos, tradução); vazio se não houver teste com custo."""
    teste = next((t for t in _ler_testes() if _chave(t.get("video", "")) == _chave(video)), None)
    if not teste or not duracao or not teste.get("custo") or not teste.get("minutos"):
        return ""
    minutos, custo = float(teste["minutos"]), float(teste["custo"])
    total = custo / minutos * duracao / 60
    atual = gastos.atual()
    valor = atual.valor if atual is not None else (lambda d: f"US$ {d:.2f}")
    return (f"Pelo teste deste vídeo ({valor(custo)} em {_duracao(minutos * 60)}), o vídeo inteiro "
            f"({_duracao(duracao)}) deve custar ~{valor(total)}.")


def pasta_dublagem() -> Path:
    """O progresso guardado das dublagens (as falas já geradas de cada filme), para continuar de onde parou."""
    return config.ARQUIVO.parent / "dublagem"


def ouvir_personagens(o: OpcoesJellyfin, video: Path, falas: list, cliente=None, ao_progresso=None, parar=None,
                      serie: str = "", arquivo: Path | None = None, ids: list[int] | None = None):
    """O Gemini ouve o filme e diz quem fala cada fala (ver personagens.py). O que já ouviu fica guardado.
    serie: episódio; o elenco dos outros episódios vai junto, para os mesmos personagens terem os mesmos rótulos."""
    ffmpeg = localizar_ffmpeg()
    if not ffmpeg:
        raise ErroDublagem("falta o ffmpeg (pip install imageio-ffmpeg)")
    cliente = cliente or voz_gemini._cliente(chave_gemini(o))
    arquivo = arquivo or pasta_do_filme(pasta_dublagem(), video) / "personagens.json"
    elenco = personagens.carregar_elenco(arquivo_elenco(serie))["pessoas"] if serie else []
    if ids is None and not serie:                 # o vídeo inteiro depois do teste: as mesmas pessoas do teste
        elenco = personagens.carregar_elenco(arquivo_elenco_do_teste(video))["pessoas"]
    achado = pelo_roteiro(o, video, falas)
    sabidas = achado.falas if achado else None
    if achado:                                    # o elenco do roteiro primeiro: o que a série já sabe vale mais
        elenco = [{"rotulo": n, "genero": g, "descricao": "do roteiro"} for n, g in achado.generos.items()] + elenco
    return personagens.identificar(video, falas, cliente, ffmpeg, arquivo, ao_progresso=ao_progresso, parar=parar,
                                   elenco=elenco or None, sabidas=sabidas, ids=ids)


def pelo_roteiro(o: OpcoesJellyfin, video: Path, falas: list):
    """Quem fala cada fala pelo roteiro ao lado do vídeo ('Nome.roteiro.txt'), se houver e a opção estiver ligada.
    Avisa no log quanto o roteiro cobriu e quantos trechos o Gemini não vai precisar ouvir."""
    if not getattr(o, "usar_roteiro", True):
        return None
    from jellyfin_tools import roteiro
    log = obter_logger()
    try:
        achado = roteiro.quem_fala(video, falas)
    except (roteiro.ErroRoteiro, OSError) as erro:
        log.warning("Roteiro de %s: %s (segue sem o roteiro)", Path(video).name, erro)
        return None
    if achado:
        partes = personagens.trechos(falas)
        pulados = sum(personagens.trecho_coberto(ids, achado.falas) for _, _, ids in partes)
        log.info("Roteiro de %s: %d de %d falas com o nome de quem fala (%.0f%%), %d personagem(ns); o Gemini não "
                 "precisa ouvir %d de %d trecho(s)", Path(video).name, len(achado.falas), achado.total,
                 achado.cobertura * 100, len(achado.generos), pulados, len(partes))
    return achado


def arquivo_elenco(serie: str) -> Path:
    """O elenco de uma série (quem fala e a voz de cada um), para os próximos episódios."""
    nome = re.sub(r"[^\w() -]", "_", serie).strip()[:80] or "serie"
    return pasta_dublagem() / "series" / f"{nome}.json"


def arquivo_elenco_do_teste(video: Path) -> Path:
    """Quem falou no TESTE e a voz de cada um: o vídeo inteiro, depois, usa as mesmas (as que você ouviu)."""
    return pasta_do_filme(pasta_dublagem(), video) / "elenco-do-teste.json"


def vozes_fixas(video: Path, serie: str = "") -> dict:
    """{rótulo: voz} que já valem: as dos episódios anteriores (série) ou as do teste deste vídeo (filme)."""
    return vozes_da_serie(serie) if serie else personagens.carregar_elenco(arquivo_elenco_do_teste(video))["vozes"]


def vozes_da_serie(serie: str) -> dict:
    """{rótulo: voz} já escolhidas nos episódios anteriores (vazio: filme, ou 1º episódio)."""
    return personagens.carregar_elenco(arquivo_elenco(serie))["vozes"] if serie else {}


def itens_para_dublar(pastas: dict, idioma: str = "pt-BR", sondar=None, no_original: bool = False) -> list:
    """Os filmes e os episódios das séries para dublar. no_original: a dublagem vira faixa do próprio arquivo;
    senão, versão ao lado (filmes) ou na pasta irmã 'Séries (Dublado IA)' (episódios)."""
    extra = {"sondar": sondar} if sondar else {}
    extra["no_original"] = no_original
    filmes = pastas.get("Filmes") or ""
    itens = videos_para_dublar(filmes, idioma=idioma, **extra) if filmes and Path(filmes).is_dir() else []
    itens += episodios_para_dublar(pastas.get("Séries") or "", idioma=idioma, **extra)
    esperando = com_previa()                          # prévia pronta, esperando você ouvir: não dubla de novo
    return [i for i in itens if _chave(i.video) not in esperando]


def videos_da_biblioteca(pastas: dict) -> list[tuple[Path, str, bool]]:
    """Os filmes e os episódios das bibliotecas (sem as versões dubladas), para escolher o vídeo do "📜 Roteiro" na
    aba Jellyfin: [(vídeo, onde: 'Filmes' ou 'Séries · Nome da série', já tem roteiro?)], na ordem das pastas."""
    from jellyfin_tools.dublagem import MARCA_DUBLADO
    from jellyfin_tools.nomes import eh_video
    from jellyfin_tools.roteiro import caminho_roteiro
    saida, vistos = [], set()
    for tipo in ("Filmes", "Séries"):
        raiz = Path(pastas.get(tipo) or "")
        if not pastas.get(tipo) or not raiz.is_dir():
            continue
        for video in sorted(raiz.rglob("*"), key=lambda v: str(v).lower()):
            if ".organizador" in video.parts or not video.is_file() or not eh_video(video) \
                    or video.stem.endswith(MARCA_DUBLADO) or (k := _chave(video)) in vistos:
                continue
            vistos.add(k)
            partes = video.relative_to(raiz).parts
            onde = f"Séries · {partes[0]}" if tipo == "Séries" and len(partes) > 1 else tipo
            saida.append((video, onde, caminho_roteiro(video) is not None))
    return saida


def usa_traducao_local(o: OpcoesJellyfin) -> bool:
    return (o.motor_traducao or "Claude").startswith("Local")


def pasta_traducao_local() -> Path:
    """Os modelos da tradução local (Argos), baixados na 1ª vez."""
    return config.ARQUIVO.parent / "traducao_local"


def pode_traduzir(o: OpcoesJellyfin) -> bool:
    """Local: sempre (grátis). Claude: só com a chave."""
    return usa_traducao_local(o) or bool(o.chave_claude or os.environ.get("ANTHROPIC_API_KEY"))


def tradutor_para(o: OpcoesJellyfin, idioma: str, ao_baixar=None):
    """Quem traduz as legendas, conforme Configurações > Tradução: o Claude (com a chave) ou o local (grátis, no PC).
    None: Claude escolhido, mas sem chave."""
    if usa_traducao_local(o):
        from jellyfin_tools.traducao_local import TradutorLocal
        return TradutorLocal(pasta_traducao_local(), idioma, ao_baixar=ao_baixar)
    if not (o.chave_claude or os.environ.get("ANTHROPIC_API_KEY")):
        return None
    return Tradutor(chave=o.chave_claude, modelo=o.modelo_traducao, idioma=idioma)


def adaptador(o: OpcoesJellyfin, titulo: str = ""):
    """Quem reescreve as falas longas (o Claude), ou None: opção desligada ou sem a chave da Anthropic."""
    if not o.encurtar_falas or not (o.chave_claude or os.environ.get("ANTHROPIC_API_KEY")):
        return None
    return Adaptador(Tradutor(chave=o.chave_claude, modelo=o.modelo_traducao, idioma="pt-BR"), titulo)


# ============================================================================ os comandos
def organizar(log: logging.Logger, simular: bool = False) -> Resultado:
    """Como a pasta vigiada: só o que TERMINOU de baixar; cada pasta vigiada dentro dela mesma (opção marcada)
    ou filmes para Filmes e episódios para Séries."""
    o, pastas = opcoes_salvas()
    alvos = vigia.alvos(o.pastas_vigiadas, o.origem, pastas["Filmes"], pastas["Séries"], o.vigia_no_lugar,
                        valida=lambda p: not problema_no_caminho(p))
    if not alvos:
        raise FaltaConfiguracao("Escolha a pasta de origem (ou as pastas vigiadas) na aba Jellyfin.")
    alvos = [a for a in alvos if a[1] or a[2]]
    if not alvos:
        raise FaltaConfiguracao("Escolha a biblioteca de Filmes e/ou de Séries na aba Jellyfin.")
    legendas = o.legendas
    if legendas and problema_legendas(o):
        legendas = False
        log.warning("Legendas desligadas nesta rodada: %s", problema_legendas(o))
    for pasta, filmes, series in alvos:
        log.info("Organizar%s: %s -> filmes: %s | séries: %s", " (SIMULAÇÃO)" if simular else "", pasta,
                 filmes or "—", series or "—")
    regras = carregar_regras(config.ARQUIVO.parent / "regras_nomes.json")
    todos = []
    for pasta, filmes, series in alvos:
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
                     [str(m) for m in todos if m.status == "erro"],
                     {"organizados": len(movidos), "erros": contagem["erro"]})


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
    return Resultado("--conferir-espelhos", PROBLEMA if quebrados else OK, resumo, detalhes,
                     {"espelhos_quebrados": len(quebrados)})


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
                     f"{len(fora)} fora do ar.", [f"{c.nome}: {s.detalhe}" for c, s in fora], {"canais_fora": len(fora)})


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


def pasta_lotes() -> Path:
    """As traduções em lote (modo econômico) esperando a resposta da Anthropic."""
    return config.ARQUIVO.parent / "lotes"


def usa_lote(o: OpcoesJellyfin) -> bool:
    """Modo econômico ligado em Configurações > Tradução (só com o Claude: a tradução local já é grátis)."""
    return bool(getattr(o, "traducao_economica", False)) and not usa_traducao_local(o)


def destinos_em_lote() -> set[str]:
    """As legendas (destino) que já estão num lote esperando: não são enviadas de novo."""
    destinos = set()
    for arquivo in traducao_lote.pendentes_no_disco(pasta_lotes()):
        try:
            dados = json.loads(arquivo.read_text(encoding="utf-8"))
            destinos |= {_chave(a["destino"]) for a in dados.get("arquivos", [])}
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return destinos


def coletar_lotes(log: logging.Logger, o) -> int:
    """Grava as traduções em lote (modo econômico) que já ficaram prontas. Devolve quantas legendas."""
    feitas = 0
    for arquivo in traducao_lote.pendentes_no_disco(pasta_lotes()):
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
        tradutor = Tradutor(chave=o.chave_claude, modelo=dados.get("modelo") or o.modelo_traducao,
                            idioma=dados.get("idioma") or "pt-BR")
        resultados = traducao_lote.coletar(arquivo, tradutor)
        if resultados is None:
            log.info("Tradução em lote %s: ainda processando", arquivo.stem)
            continue
        for r in resultados:
            (log.error if r.status == "erro" else log.info)("[lote %s] %s", r.status, r.destino.name)
        feitas += sum(r.status == "traduzida" for r in resultados)
    return feitas


def traduzir_legendas(log: logging.Logger, limite: float = 1.0, economico: bool = False) -> Resultado:
    o, pastas = opcoes_salvas()
    economico = economico or usa_lote(o)              # --economico ou a opção de Configurações > Tradução
    onde = bibliotecas(pastas)
    if not onde:
        raise FaltaConfiguracao("Escolha a biblioteca de Filmes e/ou de Séries na aba Jellyfin.")
    if not pode_traduzir(o):
        raise FaltaConfiguracao("Falta a chave da API da Anthropic (Configurações > Chaves de API, com \"Lembrar as "
                                "chaves\" marcado, ou a variável de ambiente ANTHROPIC_API_KEY), ou escolha a "
                                "tradução Local (grátis) em Configurações > Tradução.")
    idioma = o.idioma.split(",")[0].strip() or "pt-BR"
    if usa_traducao_local(o):                        # grátis, no PC: sem limite de dólares e sem lote
        return _traduzir_local(log, o, onde, idioma)
    do_lote = coletar_lotes(log, o)
    aguardando = len(traducao_lote.pendentes_no_disco(config.ARQUIVO.parent / "lotes"))
    pendentes = legendas_para_traduzir(*onde, idioma=idioma)
    if economico and aguardando:
        return Resultado("--traduzir-legendas", OK, f"{do_lote} legenda(s) do lote gravada(s); {aguardando} lote(s) "
                         "ainda processando (um de cada vez).", contagens={"traduzidas": do_lote})
    if not pendentes:
        return Resultado("--traduzir-legendas", OK, f"Nada a traduzir: os vídeos já têm legenda em {idioma}."
                         + (f" {do_lote} legenda(s) do lote gravada(s)." if do_lote else ""),
                         contagens={"traduzidas": do_lote})
    escolhidos, estimado = escolher_dentro_do_limite(pendentes, o.modelo_traducao, limite * (2 if economico else 1))
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
    if economico:
        codigo, pedidos = traducao_lote.enviar(escolhidos, tradutor, config.ARQUIVO.parent / "lotes")
        return Resultado("--traduzir-legendas", OK, f"Lote {codigo} enviado: {len(escolhidos)} legenda(s), "
                         f"{pedidos} pedido(s), metade do preço. A próxima execução grava o que ficar pronto."
                         + (f" {do_lote} legenda(s) de um lote anterior gravada(s)." if do_lote else ""),
                         contagens={"traduzidas": do_lote})
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
                     [f"{r.origem.name}: {r.detalhe}" for r in erros], {"traduzidas": len(traduzidas) + do_lote})


def _traduzir_local(log: logging.Logger, o: OpcoesJellyfin, onde: list, idioma: str) -> Resultado:
    pendentes = legendas_para_traduzir(*onde, idioma=idioma)
    if not pendentes:
        return Resultado("--traduzir-legendas", OK, f"Nada a traduzir: os vídeos já têm legenda em {idioma}.")
    tradutor = tradutor_para(o, idioma)
    log.info("Traduzir legendas (local, grátis): %d pendente(s)", len(pendentes))
    resultados = []
    for p in pendentes:
        r = traduzir_arquivo(p.origem, p.destino, tradutor, titulo=p.video.stem)
        resultados.append(r)
        (log.error if r.status == "erro" else log.info)("[%s] %s -> %s%s", r.status, r.origem.name, r.destino.name,
                                                         f" ({r.detalhe})" if r.detalhe else "")
        if r.status == "erro" and "modelo" in r.detalhe:
            break                                       # sem o modelo, nenhuma vai dar certo
    traduzidas = [r for r in resultados if r.status == "traduzida"]
    erros = [r for r in resultados if r.status == "erro"]
    return Resultado("--traduzir-legendas", PROBLEMA if erros else OK,
                     f"{len(traduzidas)} de {len(pendentes)} legenda(s) traduzida(s) no PC (grátis), "
                     f"{len(erros)} erro(s).", [f"{r.origem.name}: {r.detalhe}" for r in erros],
                     {"traduzidas": len(traduzidas)})


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
    tradutor = tradutor_para(o, idioma)
    log.info("Legendar pelo áudio: %d sem legenda, %d nesta execução (Whisper %s, %s)", len(itens), len(escolhidos),
             o.modelo_whisper, f"com tradução ({tradutor.modelo})" if tradutor else
             "sem tradução: falta a chave da Anthropic")
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
                     [f"{r.video.name}: {r.detalhe}" for r in erros], {"pelo_audio": len(feitas)})


def sincronizar_legendas(log: logging.Logger, limite_videos: int = 5) -> Resultado:
    _, pastas = opcoes_salvas()
    onde = bibliotecas(pastas)
    if not onde:
        raise FaltaConfiguracao("Escolha a biblioteca de Filmes e/ou de Séries na aba Jellyfin.")
    registro = Conferidas(config.ARQUIVO.parent / "sincronia.json")
    pares = legendas_para_sincronizar(*onde, conferidas=registro.dados)
    escolhidos = pares[:limite_videos] if limite_videos > 0 else pares
    resultados = []
    for legenda, video in escolhidos:
        r = sincronizar(legenda, video)
        resultados.append(r)
        if r.status != "erro":
            registro.marcar(legenda)
        (log.error if r.status == "erro" else log.info)("[%s] %s %s", r.status, legenda.name,
                                                         f"{r.atraso:+.2f} s" if r.status == "ajustada" else r.detalhe)
    ajustadas = [r for r in resultados if r.status == "ajustada"]
    erros = [r for r in resultados if r.status == "erro"]
    resumo = (f"{len(resultados)} legenda(s) conferida(s): {len(ajustadas)} corrigida(s), {len(erros)} erro(s)"
              + (f", {len(pares) - len(resultados)} para a próxima vez." if len(resultados) < len(pares) else "."))
    return Resultado("--sincronizar-legendas", PROBLEMA if erros else OK, resumo,
                     [f"{r.legenda.name}: {r.detalhe}" for r in erros])


def dublar(log: logging.Logger, limite_videos: int = 5) -> Resultado:
    """Os filmes e episódios com legenda em português e sem áudio em português ganham a dublagem: uma faixa nova no
    próprio arquivo (padrão) ou a versão à parte (filmes: 'Nome - Dublado IA.mkv' ao lado; episódios: na pasta irmã
    'Séries (Dublado IA)')."""
    o, pastas = opcoes_salvas()
    if o.robo_so_piper:                               # opção "Nos robôs agendados, usar só o Piper (sem custo)"
        o.motor_voz, o.voz_por_personagem, o.figurantes_piper = "Piper (grátis, no PC)", False, False
        o.sem_gemini = True                           # nem a escuta dos sons sem fala (sem custo nenhum)
    if not any(pastas.get(t) and Path(pastas[t]).is_dir() for t in ("Filmes", "Séries")):
        raise FaltaConfiguracao("Escolha a biblioteca de Filmes e/ou de Séries na aba Jellyfin.")
    itens = itens_para_dublar(pastas, o.idioma.split(",")[0].strip() or "pt-BR",
                              no_original=o.dublagem_no_original)
    if not itens:
        return Resultado("--dublar", OK, "Nenhum filme ou episódio para dublar.")
    escolhidos = itens[:limite_videos] if limite_videos > 0 else itens
    try:
        motor = preparar_motor(o)
    except ErroDublagem as erro:
        return Resultado("--dublar", PROBLEMA, f"Não deu para preparar a voz: {erro}")
    voz = (f"Gemini {o.voz_gemini}" if usa_gemini(o) else f"Google Cloud {o.voz_cloud}" if usa_cloud(o)
           else f"Piper {o.voz_dublagem}")
    log.info("Dublar: %d filme(s), %d nesta execução (voz %s)", len(itens), len(escolhidos), voz)
    resultados = []
    separar = separador_de_vozes(o, log)
    for item in escolhidos:
        r = dublar_item(o, item, motor, log, separar=separar)
        resultados.append(r)
        (log.error if r.status == "erro" else log.info)("[%s] %s%s (%d falas, %d adaptadas, %d aceleradas, "
                                                         "%d repetidas reaproveitadas)", r.status, r.video.name,
                                                         f" ({r.detalhe})" if r.detalhe else "", r.falas,
                                                         r.adaptadas, r.aceleradas, r.reaproveitadas)
    feitos = [r for r in resultados if r.status == "dublado"]
    erros = [r for r in resultados if r.status == "erro"]
    if feitos and o.atualizar_jellyfin and o.jellyfin_url and o.jellyfin_api_key:
        try:
            atualizar_biblioteca(o.jellyfin_url, o.jellyfin_api_key)
        except ErroJellyfin as erro:
            log.warning("Jellyfin: scan não pedido (%s)", erro)
    previas = [r for r in resultados if r.status == "previa"]
    resumo = (f"{len(feitos)} de {len(resultados)} vídeo(s) dublado(s), {len(erros)} erro(s)"
              + (f", {len(previas)} prévia(s) para ouvir e aprovar (aba Avulsos > Prévias)" if previas else "")
              + (f", {len(itens) - len(resultados)} para a próxima vez." if len(resultados) < len(itens) else "."))
    return Resultado("--dublar", PROBLEMA if erros else OK, resumo, [f"{r.video.name}: {r.detalhe}" for r in erros],
                     {"dublados": len(feitos)})


def vozes_automaticas(o: OpcoesJellyfin, item, log: logging.Logger) -> dict | None:
    """Robôs e vídeos avulsos (sem ninguém para conferir a tabela): uma voz por personagem escolhida sozinha."""
    if not (usa_gemini(o) and o.voz_por_personagem):
        return None
    try:
        lista = ouvir_personagens(o, item.video, falas_da_legenda(item.legenda), serie=item.serie)
        mapa = personagens.distribuir_vozes(lista, o.voz_gemini, figurante(o), o.limite_figurante,
                                            fixas=vozes_fixas(item.video, item.serie))
        if item.serie:                                # os próximos episódios usam as mesmas vozes
            personagens.salvar_elenco(arquivo_elenco(item.serie), lista, mapa)
        return personagens.vozes_por_fala(lista, mapa)
    except (ErroDublagem, OSError, ErroLegenda) as erro:
        log.warning("Voz por personagem em %s: %s (segue com uma voz só)", item.video.name, erro)
        return None


def vozes_do_teste(o: OpcoesJellyfin, video: Path, legenda: Path, trecho: tuple[float, float],
                   log: logging.Logger) -> dict | None:
    """O TESTE com a voz por personagem ligada: o Gemini ouve só o trecho do teste e cada pessoa ganha uma voz do
    gênero dela, como na dublagem do vídeo inteiro (antes o teste saía sempre com uma voz só). Sem figurantes no Piper:
    em poucos minutos todo mundo fala pouco."""
    if not (usa_gemini(o) and o.voz_por_personagem and chave_gemini(o)):
        return None
    try:
        falas = falas_da_legenda(legenda)
        ids = [k for k, (f, _) in enumerate(falas) if trecho[0] <= horarios(f.tempo)[0] < trecho[1]]
        if not ids:
            return None
        arquivo = pasta_do_filme(pasta_dublagem(), video) / "teste-personagens.json"
        arquivo.unlink(missing_ok=True)                  # o trecho (ou a legenda) do teste pode ter mudado
        log.info("Teste: o Gemini está ouvindo quem fala as %d falas do trecho (voz por personagem)", len(ids))
        lista = ouvir_personagens(o, video, falas, arquivo=arquivo, ids=ids)
        mapa = personagens.distribuir_vozes(lista, o.voz_gemini)
        for p in lista:
            log.info("Teste: %s (%s%s, %d falas) -> %s", p.rotulo, personagens.GENEROS.get(p.genero, "?"),
                     f", {personagens.IDADES[p.idade]}" if p.idade in personagens.IDADES else "", len(p.falas),
                     voz_gemini.texto_da_voz(mapa.get(p.rotulo, o.voz_gemini)))
        elenco = arquivo_elenco_do_teste(video)          # o vídeo inteiro usa as mesmas pessoas e vozes
        elenco.unlink(missing_ok=True)
        personagens.salvar_elenco(elenco, lista, mapa)
        return personagens.vozes_por_fala(lista, mapa)
    except (ErroDublagem, OSError, ErroLegenda) as erro:
        log.warning("Teste: voz por personagem: %s (segue com a voz pelo gênero)", erro)
        return None


def pasta_separar_vozes() -> Path:
    """O modelo que separa as vozes do fundo (baixado na 1ª vez, ~67 MB)."""
    return config.ARQUIVO.parent / "separar_vozes"


def separador_de_vozes(o: OpcoesJellyfin, log: logging.Logger | None = None, ao_baixar=None):
    """O 'separar' do dublar_video, se ligado em Configurações > Dublagem ("Tirar as vozes originais").
    None: fica o voice-over (falta o onnxruntime ou o modelo não baixou: avisa no log e segue)."""
    if not getattr(o, "separar_vozes", False):
        return None
    from jellyfin_tools import separar_vozes
    ffmpeg = localizar_ffmpeg()
    if not separar_vozes.disponivel() or not ffmpeg:
        if log:
            log.warning("Tirar as vozes originais: falta o onnxruntime ou o ffmpeg; a dublagem fica por cima do áudio")
        return None
    try:
        modelo = separar_vozes.preparar_modelo(pasta_separar_vozes(), ao_progresso=ao_baixar)
    except Exception as erro:                       # sem internet na 1ª vez, download corrompido...
        if log:
            log.warning("Tirar as vozes originais: não deu para baixar o modelo (%s); a dublagem fica por cima do "
                        "áudio desta vez", erro)
        return None
    carregado = {}

    def separar(video, destino, trecho, duracao, parar, ao_progresso):
        if "modelo" not in carregado:               # carrega uma vez só, para todos os vídeos da vez
            carregado["modelo"] = separar_vozes.Separador(modelo, usar_gpu=getattr(o, "separar_gpu", True))
            if log:                                  # uma linha só (o motivo, se a placa de vídeo não entrou)
                log.info("Tirar as vozes originais: usando o(a) %s", carregado["modelo"].dispositivo)
        return separar_vozes.separar_fundo(ffmpeg, video, destino, modelo, trecho, duracao, parar, ao_progresso,
                                           carregado["modelo"])
    return separar


# ---------------------------------------------------------------------------- fase de teste (prévia antes do original)
def pasta_previas() -> Path:
    """As prévias da dublagem (fora das bibliotecas: o Jellyfin não as vê) e a lista das que esperam aprovação."""
    return config.ARQUIVO.parent / "previas_dublagem"


def usa_previa(o: OpcoesJellyfin) -> bool:
    """Fase de teste: com a dublagem no original, primeiro uma prévia para ouvir (Configurações > Dublagem)."""
    return bool(o.dublagem_no_original and getattr(o, "dublagem_previa", True))


def caminho_previa(video: Path) -> Path:
    marca = hashlib.sha1(str(Path(video).resolve()).lower().encode("utf-8")).hexdigest()[:10]
    return pasta_previas() / marca / f"{Path(video).stem} - prévia da dublagem.mkv"


def _arquivo_previas() -> Path:
    return pasta_previas() / "previas.json"


def previas_pendentes() -> list[dict]:
    """[{video, previa, legenda, criada}] das prévias que ainda existem (e cujo vídeo ainda existe)."""
    try:
        dados = json.loads(_arquivo_previas().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [d for d in dados if Path(d.get("video", "")).is_file() and Path(d.get("previa", "")).is_file()]


def _salvar_previas(lista: list[dict]) -> None:
    _arquivo_previas().parent.mkdir(parents=True, exist_ok=True)
    _arquivo_previas().write_text(json.dumps(lista, ensure_ascii=False, indent=1), encoding="utf-8")


def registrar_previa(video: Path, previa: Path, legenda: Path | None) -> None:
    """legenda: a que vai para dentro do vídeo ao aprovar. Uma CÓPIA fica junto da prévia (se o .srt ao lado do
    vídeo sumir até você aprovar, a legenda ainda entra); o original é apagado depois de aprovar."""
    copia = ""
    if legenda and Path(legenda).is_file():
        copia = str(Path(previa).with_suffix(".srt"))
        shutil.copyfile(legenda, copia)
    lista = [d for d in previas_pendentes() if _chave(d["video"]) != _chave(video)]
    lista.append({"video": str(video), "previa": str(previa), "legenda": copia,
                  "legenda_original": str(legenda) if legenda else "",
                  "criada": datetime.now().isoformat(timespec="minutes")})
    _salvar_previas(lista)


def com_previa() -> set[str]:
    """Os vídeos (chave) com prévia esperando aprovação: não entram de novo na fila de dublar."""
    return {_chave(d["video"]) for d in previas_pendentes()}


def aprovar_previa_de(video: str | Path, log: logging.Logger | None = None, parar=None) -> Path:
    """Grava a dublagem da prévia no original (e a legenda, se a prévia foi feita com ela)."""
    from jellyfin_tools.dublagem import aprovar_previa
    item = next((d for d in previas_pendentes() if _chave(d["video"]) == _chave(video)), None)
    if item is None:
        raise ErroDublagem("não há prévia deste vídeo (dublar de novo)")
    ffmpeg = localizar_ffmpeg()
    if not ffmpeg:
        raise ErroDublagem("falta o ffmpeg")
    final = aprovar_previa(ffmpeg, item["video"], item["previa"], item.get("legenda") or None, parar)
    if item.get("legenda") and item.get("legenda_original"):
        Path(item["legenda_original"]).unlink(missing_ok=True)   # está dentro do vídeo (senão apareceria 2 vezes)
    _salvar_previas([d for d in previas_pendentes() if _chave(d["video"]) != _chave(video)])
    if log:
        log.info("[aprovada] dublagem gravada no original: %s", final)
    return final


def descartar_previa_de(video: str | Path, log: logging.Logger | None = None) -> None:
    for d in previas_pendentes():
        if _chave(d["video"]) == _chave(video):
            Path(d["previa"]).unlink(missing_ok=True)
            if d.get("legenda"):
                Path(d["legenda"]).unlink(missing_ok=True)       # a cópia da legenda (o original fica)
            with contextlib.suppress(OSError):
                Path(d["previa"]).parent.rmdir()
            if log:
                log.info("[descartada] prévia da dublagem de %s", Path(d["video"]).name)
    _salvar_previas([d for d in previas_pendentes() if _chave(d["video"]) != _chave(video)])


def dublar_item(o: OpcoesJellyfin, item, motor, log: logging.Logger, parar=None, ao_progresso=None, separar=None,
                legenda_no_video: bool = False, vozes: dict | None = None, tipo: str = "jellyfin"):
    """Dubla um vídeo. Com a fase de teste, o resultado é uma PRÉVIA (status "previa"), registrada para aprovar.
    vozes: as da 1ª parte (continuação depois do limite do dia), para a voz não mudar no meio do filme. Se o limite
    do dia da chave grátis parar a dublagem, ela fica guardada para continuar sozinha (anotar_continuacao)."""
    previa = caminho_previa(item.video) if usa_previa(o) else None
    vozes = vozes if vozes is not None else vozes_automaticas(o, item, log)
    r = dublar_video(item.video, item.legenda, motor, adaptar=adaptador(o, item.video.stem),
                     avisar=lambda texto: log.warning("Dublagem: %s", texto), vozes=vozes,
                     pasta_cache=pasta_dublagem(), destino=item.destino, parar=parar, ao_progresso=ao_progresso,
                     separar=separar, no_original=o.dublagem_no_original, legenda_no_video=legenda_no_video,
                     previa=previa, ambientar=getattr(o, "ambientar_voz", True),
                     tons=ouvinte_de_tons(o, item.video, motor, log), por_genero=vozes_por_genero(o, motor),
                     pronuncias=pronuncias_de(o), manter_sons=getattr(o, "manter_sons", True),
                     camada_emocao=getattr(o, "camada_de_emocao", True))
    registrar_qualidade(log, r)
    if r.status == "previa":
        registrar_previa(item.video, r.destino, item.legenda if legenda_no_video else None)
    anotar_continuacao(o, item.video, tipo, r, vozes, log)
    return r


# ============================================================================ continuar depois do limite do dia
def arquivo_continuar() -> Path:
    """As dublagens que pararam no limite do dia da chave grátis do Gemini, para o robô --continuar-dublagem."""
    return config.ARQUIVO.parent / "continuar_dublagem.json"


def ler_continuacoes() -> dict:
    """{chave do vídeo: {"video", "tipo" ("jellyfin" ou "avulso"), "vozes" ({fala: voz} ou None), "desde"}}"""
    try:
        dados = json.loads(arquivo_continuar().read_text(encoding="utf-8"))
        return dados if isinstance(dados, dict) else {}
    except (OSError, ValueError):
        return {}


def _gravar_continuacoes(dados: dict) -> None:
    arquivo = arquivo_continuar()
    if not dados:
        arquivo.unlink(missing_ok=True)
        return
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    arquivo.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")


def parou_no_limite_do_dia(detalhe: str) -> bool:
    return "limite do dia" in detalhe or "limite de uso do Gemini" in detalhe


def hora_de_continuar() -> str:
    """10 min depois da virada do dia do Google (meia-noite na Califórnia), na hora daqui: 'HH:MM'."""
    atual = gastos.atual()
    h, m = (int(x) for x in (atual.virada_do_dia() if atual is not None else "04:00").split(":"))
    total = (h * 60 + m + 10) % (24 * 60)
    return f"{total // 60:02d}:{total % 60:02d}"


def anotar_continuacao(o: OpcoesJellyfin, video: Path, tipo: str, r, vozes: dict | None,
                       log: logging.Logger | None = None, agendar=None) -> None:
    """Depois de cada dublagem: parou no limite do dia da chave GRÁTIS -> guarda (com as vozes usadas, para não
    mudarem) e agenda o robô --continuar-dublagem para depois da virada do dia; ficou pronta -> sai da lista."""
    dados = ler_continuacoes()
    chave = _chave(video)
    if (r.status == "erro" and parou_no_limite_do_dia(r.detalhe or "")
            and getattr(o, "plano_gemini", "?") == "gratis"):
        dados[chave] = {"video": str(video), "tipo": tipo, "desde": datetime.now().isoformat(timespec="minutes"),
                        "vozes": {str(k): v for k, v in vozes.items()} if vozes else None}
        _gravar_continuacoes(dados)
        hora = hora_de_continuar()
        try:
            (agendar or agendador.agendar)("--continuar-dublagem", agendador.FREQUENCIAS[0], hora)
            if log:
                log.warning("Dublagem: o limite do dia da chave grátis do Gemini acabou; %s continua sozinho às %s "
                            "(tarefa \"Maestro\\continuar-dublagem\" no Agendador do Windows; o computador precisa "
                            "estar ligado e com você conectado). O que já ficou pronto está guardado", video.name, hora)
        except agendador.ErroAgenda as erro:
            if log:
                log.warning("Dublagem: o limite do dia acabou; não deu para agendar a continuação (%s). Dublar de "
                            "novo depois das %s continua de onde parou", erro, hora)
    elif r.status in ("dublado", "previa") and chave in dados:
        dados.pop(chave)
        _gravar_continuacoes(dados)


def continuar_dublagem(log: logging.Logger, remover=None) -> Resultado:
    """Robô --continuar-dublagem (agendado sozinho quando o limite do dia acaba): retoma SÓ as dublagens que pararam
    (não pega outros filmes), com as mesmas vozes. Sem nada para continuar, tira a própria tarefa do Agendador."""
    pendentes = ler_continuacoes()

    def tirar_tarefa():
        try:
            (remover or agendador.remover)("--continuar-dublagem")
        except agendador.ErroAgenda:
            pass
    if not pendentes:
        tirar_tarefa()
        return Resultado("--continuar-dublagem", OK, "Nada para continuar (a tarefa agendada foi removida).")
    o, pastas = opcoes_salvas()
    atual = gastos.atual()
    if atual is not None and atual.restam_hoje("voz") == 0:
        return Resultado("--continuar-dublagem", OK, f"O limite do dia do Gemini ainda não voltou: {len(pendentes)} "
                                                     "dublagem(ns) esperando a próxima execução.")
    try:
        motor = preparar_motor(o)
    except ErroDublagem as erro:
        return Resultado("--continuar-dublagem", PROBLEMA, f"Não deu para preparar a voz: {erro}")
    idioma = o.idioma.split(",")[0].strip() or "pt-BR"
    jellyfin = {_chave(i.video): i for i in itens_para_dublar(pastas, idioma, no_original=o.dublagem_no_original)} \
        if any(p.get("tipo") == "jellyfin" for p in pendentes.values()) else {}
    separar = separador_de_vozes(o, log)
    feitos, erros = 0, []
    for chave, pendente in list(pendentes.items()):
        video = Path(pendente.get("video", ""))
        vozes = {int(k): v for k, v in pendente["vozes"].items()} if pendente.get("vozes") else None
        if pendente.get("tipo") == "avulso":
            item = next((i for i in planejar_avulsos(o, o.pasta_avulsos, [video]).dublar), None)
            tipo = "avulso"
        else:
            item, tipo = jellyfin.get(chave), "jellyfin"
        if item is None:                              # já dublado (ou o vídeo saiu do lugar): sai da lista
            dados = ler_continuacoes()
            dados.pop(chave, None)
            _gravar_continuacoes(dados)
            continue
        log.info("Continuar: %s (parou no limite do dia em %s)", video.name, pendente.get("desde", "?"))
        r = dublar_item(o, item, motor, log, separar=separar, vozes=vozes, tipo=tipo)
        if r.status in ("dublado", "previa"):
            feitos += 1
        elif r.status == "erro":
            erros.append(f"{video.name}: {r.detalhe}")
            if parou_no_limite_do_dia(r.detalhe or ""):
                break                                 # acabou de novo: os outros esperam a próxima execução
    if not ler_continuacoes():
        tirar_tarefa()
    faltam = len(ler_continuacoes())
    return Resultado("--continuar-dublagem", PROBLEMA if erros and not faltam else OK,
                     f"{feitos} dublagem(ns) continuada(s) até o fim" + (f"; {faltam} ainda esperando" if faltam
                                                                          else "") + ".", erros, {"dublados": feitos})


# ============================================================================ vídeos avulsos
@dataclasses.dataclass
class PlanoAvulsos:
    """O que a caixa de entrada (e/ou os arquivos escolhidos) tem para fazer."""
    traduzir: list                 # legendas em outro idioma -> português (Claude ou local)
    pelo_audio: list               # vídeos sem nenhuma legenda -> Whisper (+ tradução)
    dublar: list                   # já com legenda em português, sem áudio em português
    videos: int = 0                # quantos vídeos olhados
    lista: list = field(default_factory=list)      # todos os vídeos olhados (Path), para a aba Avulsos
    embutir: list = field(default_factory=list)    # (vídeo, .srt): a legenda em português vira faixa do vídeo
    legenda_dentro: set = field(default_factory=set)   # vídeos (chave) que já têm legenda em português dentro
    previas: set = field(default_factory=set)      # vídeos (chave) com a prévia da dublagem esperando aprovação

    @property
    def vazio(self) -> bool:
        return not (self.traduzir or self.pelo_audio or self.dublar or self.embutir)


def _chave(caminho) -> str:
    return str(Path(caminho).resolve()).lower()


def _dentro(caminho, pasta: str) -> bool:
    try:
        Path(caminho).resolve().relative_to(Path(pasta).resolve())
        return True
    except (ValueError, OSError):
        return False


def _so_estes(itens: list, pasta: str, arquivos) -> list:
    """Os itens da pasta inteira MAIS os arquivos escolhidos (cada vídeo uma vez só)."""
    escolhidos = {_chave(a) for a in arquivos}
    vistos, saida = set(), []
    for i in itens:
        k = _chave(i.video)
        if k not in vistos and ((pasta and _dentro(i.video, pasta)) or k in escolhidos):
            vistos.add(k)
            saida.append(i)
    return saida


def srt_portugues(video: Path, idioma: str = "pt-BR") -> Path | None:
    """A legenda em português AO LADO do vídeo ('Nome.pt-BR.srt'...), se houver."""
    return next((video.with_name(f"{video.stem}.{c}.srt") for c in dict.fromkeys((idioma, "pt-BR", "pt", "por"))
                 if video.with_name(f"{video.stem}.{c}.srt").is_file()), None)


def planejar_avulsos(o: OpcoesJellyfin, pasta: str = "", arquivos=(), sondar=None) -> PlanoAvulsos:
    """A pasta de vídeos avulsos inteira e/ou os arquivos escolhidos (em qualquer pasta).
    O que olha DENTRO de cada vídeo (idiomas do áudio e das legendas) vem do próprio ffmpeg; sondar(vídeo) ->
    (duração, idiomas do áudio) troca só a parte do áudio (testes)."""
    from jellyfin_tools.dublagem import MARCA_DUBLADO, Faixas, inspecionar
    from jellyfin_tools.nomes import eh_video
    legendar = getattr(o, "avulsos_legendar", True)
    no_original = getattr(o, "dublagem_no_original", False)
    pasta = pasta if pasta and Path(pasta).is_dir() else ""
    onde = sorted({str(Path(a).parent) for a in arquivos} | ({pasta} if pasta else set()))
    onde = [p for p in onde if p and Path(p).is_dir()]
    idioma = o.idioma.split(",")[0].strip() or "pt-BR"
    lista, vistos = [], set()
    candidatos = [v for v in Path(pasta).rglob("*") if v.is_file()] if pasta else []
    for v in candidatos + [Path(a) for a in arquivos if Path(a).is_file()]:
        if eh_video(v) and not v.stem.endswith(MARCA_DUBLADO) and _chave(v) not in vistos:
            vistos.add(_chave(v))
            lista.append(v)
    lista.sort(key=lambda v: (str(v.parent).lower(), v.name.lower()))
    if not onde or not (legendar or o.avulsos_dublar):
        return PlanoAvulsos([], [], [], len(lista), lista)
    ffmpeg, olhados = localizar_ffmpeg(), {}

    def faixas(video) -> Faixas:
        k = _chave(video)
        if k not in olhados:
            olhados[k] = inspecionar(ffmpeg, Path(video)) if ffmpeg else Faixas(None)
        return olhados[k]

    def sondar_legendas(video):
        return faixas(video).duracao, set(faixas(video).idiomas_legenda)
    sondar_audio = sondar or (lambda v: (faixas(v).duracao, faixas(v).idiomas_audio))
    dublar = (_so_estes(videos_para_dublar(*onde, idioma=idioma, sondar=sondar_audio, no_original=no_original),
                        pasta, arquivos) if o.avulsos_dublar else [])
    dentro = {_chave(v) for v in lista if faixas(v).tem_legenda_portugues()}
    esperando = com_previa() & {_chave(v) for v in lista}
    dublar = [i for i in dublar if _chave(i.video) not in esperando]
    embutir = []
    if legendar:
        vai_dublar = {_chave(i.video) for i in dublar} | esperando if no_original else set()  # vai junto da dublagem
        embutir = [(v, srt) for v in lista if _chave(v) not in dentro and _chave(v) not in vai_dublar
                   and (srt := srt_portugues(v, idioma))]
    return PlanoAvulsos(_so_estes(legendas_para_traduzir(*onde, idioma=idioma, sondar_embutidas=sondar_legendas),
                                  pasta, arquivos),
                        _so_estes(videos_sem_legenda(*onde, idioma=idioma, sondar_arquivo=sondar_legendas),
                                  pasta, arquivos),
                        dublar, len(lista), lista, embutir, dentro, esperando)


def situacao_avulsos(plano: PlanoAvulsos, dublar: bool = True, legendar: bool = False
                     ) -> list[tuple[Path, str, str, bool]]:
    """Uma linha por vídeo para a aba Avulsos: (vídeo, legenda em português, o que falta, pronto?)."""
    traduzir = {_chave(i.video) for i in plano.traduzir}
    pelo_audio = {_chave(i.video) for i in plano.pelo_audio}
    para_dublar = {_chave(i.video) for i in plano.dublar}
    embutir = {_chave(v) for v, _ in plano.embutir}
    linhas = []
    for v in plano.lista:
        k = _chave(v)
        partes = []
        if k in traduzir:
            partes.append("traduzir a legenda")
        elif k in pelo_audio:
            partes.append("criar a legenda pelo áudio")
        if dublar and (k in para_dublar or k in traduzir or k in pelo_audio):
            partes.append("dublar")
        if legendar and (k in embutir or k in traduzir or k in pelo_audio or k in para_dublar):
            partes.append("pôr a legenda no vídeo")
        if k in plano.legenda_dentro:
            legenda = "✓ dentro do vídeo"
        elif k in traduzir:
            legenda = "em outro idioma"
        elif k in pelo_audio:
            legenda = "nenhuma"
        else:
            legenda = "✓ ao lado (.srt)"
        if k in plano.previas:
            linhas.append((v, legenda, "Ouvir a prévia e aprovar", False))
            continue
        if partes:
            acao = " → ".join(partes)
            linhas.append((v, legenda, acao[0].upper() + acao[1:], False))
        else:
            linhas.append((v, legenda, "Nada: já está pronto", True))
    return linhas


def processar_avulsos(o: OpcoesJellyfin, log: logging.Logger, pasta: str = "", arquivos=(), parar=None,
                      avisar=None, sondar=None, motor=None, separar=None, andamento=None) -> Resultado:
    """Caixa de entrada: (1) traduz a legenda que já existe; (2) cria pelo áudio a dos que não têm nenhuma; (3) se
    marcado, dubla os que ficaram com legenda em português; (4) se marcado "Legendar", a legenda em português entra
    como faixa do vídeo. A dublagem e a legenda ficam no próprio arquivo (ou, se escolhido em Configurações >
    Dublagem, a dublagem fica à parte: 'Nome - Dublado IA.mkv')."""
    from jellyfin_tools.dublagem import RelogioDaDublagem, embutir_legenda
    avisar = avisar or (lambda texto: None)
    # andamento(fração 0..1, texto): a barra e a porcentagem na tela (antes só aparecia no fim)
    andamento = andamento or (lambda fracao, texto: avisar(texto))
    parado = parar or (lambda: False)
    legendar = getattr(o, "avulsos_legendar", True)
    idioma = o.idioma.split(",")[0].strip() or "pt-BR"
    contas, erros = {"traduzidas": 0, "pelo_audio": 0, "dublados": 0, "legendas_no_video": 0, "previas": 0,
                     "no_lote": 0}, []
    economico = usa_lote(o)
    if economico:                                     # o que voltou do lote (metade do preço) entra na dublagem já
        try:
            contas["traduzidas"] += coletar_lotes(log, o)
        except (ErroTraducao, ImportError, OSError, ValueError) as erro:
            log.warning("Tradução em lote: %s", erro)
    plano = planejar_avulsos(o, pasta, arquivos, sondar)
    tradutor = tradutor_para(o, idioma)
    if plano.traduzir and tradutor is None:
        erros.append(f"{len(plano.traduzir)} legenda(s) em outro idioma: falta a chave da Anthropic para traduzir")
    tradutor_das_legendas = tradutor
    if economico and tradutor is not None and plano.traduzir:
        tradutor_das_legendas = None                 # vão pelo lote: nenhuma é traduzida agora, a preço cheio
        novos = [p for p in plano.traduzir if _chave(p.destino) not in destinos_em_lote()]
        if novos:                                     # as que já estão num lote esperando não vão de novo
            andamento(0.0, f"Enviando {len(novos)} legenda(s) no modo econômico (lote, metade do preço)...")
            try:
                codigo, _ = traducao_lote.enviar(novos, tradutor, pasta_lotes())
                log.info("Tradução em lote %s: %d legenda(s) de vídeos avulsos", codigo, len(novos))
            except ErroTraducao as erro:
                erros.append(f"modo econômico: {erro}")
        contas["no_lote"] = len({_chave(p.destino) for p in plano.traduzir} & destinos_em_lote())
    for k, p in enumerate(plano.traduzir if tradutor_das_legendas else []):
        if parado():
            break
        andamento(k / len(plano.traduzir), f"Traduzindo a legenda {k + 1} de {len(plano.traduzir)}: {p.video.stem}")
        r = traduzir_arquivo(p.origem, p.destino, tradutor, titulo=p.video.stem)
        log.info("[%s] avulso %s -> %s%s", r.status, r.origem.name, r.destino.name,
                 f" ({r.detalhe})" if r.detalhe else "")
        if r.status == "erro":
            erros.append(f"{p.origem.name}: {r.detalhe}")
        else:
            contas["traduzidas"] += 1
    if plano.pelo_audio and not parado():
        transcritor = Transcritor(modelo=o.modelo_whisper, usar_gpu=o.whisper_gpu,
                                  pasta_modelos=str(config.ARQUIVO.parent / "modelos_whisper"))
        for k, item in enumerate(plano.pelo_audio):
            if parado():
                break
            andamento(k / len(plano.pelo_audio),
                      f"Criando a legenda pelo áudio {k + 1} de {len(plano.pelo_audio)}: {item.video.stem} (o "
                      "Whisper ouve o vídeo inteiro: pode demorar)")
            r = legendar_pelo_audio(item.video, transcritor, tradutor, idioma)
            log.info("[%s] avulso %s%s", r.status, r.video.name, f" ({r.detalhe})" if r.detalhe else "")
            if r.status == "erro":
                erros.append(f"{item.video.name}: {r.detalhe}")
            else:
                contas["pelo_audio"] += 1
    dublar_agora = []
    if o.avulsos_dublar and not parado():            # de novo: as legendas novas entram na dublagem
        dublar_agora = planejar_avulsos(o, pasta, arquivos, sondar).dublar
    if dublar_agora:
        try:
            motor = motor or preparar_motor(o)
        except (ErroDublagem, FaltaConfiguracao) as erro:
            erros.append(f"dublagem: não deu para preparar a voz: {erro}")
            dublar_agora = []
        if dublar_agora and separar is None:
            avisar("Preparando a separação das vozes (na 1ª vez baixa o modelo, ~67 MB)...")
            separar = separador_de_vozes(o, log)
        for k, item in enumerate(dublar_agora):
            if parado():
                break
            total, relogio = len(dublar_agora), RelogioDaDublagem(bool(separar))

            def progresso(fracao, k=k, item=item, total=total, relogio=relogio):
                andamento((k + fracao) / total,
                          f"Dublando {k + 1} de {total}: {item.video.stem} – {relogio.texto(fracao)}")
            progresso(0.0)
            r = dublar_item(o, item, motor, log, parar, separar=separar or None, legenda_no_video=legendar,
                            ao_progresso=progresso, tipo="avulso")
            log.info("[%s] avulso %s%s", r.status, r.video.name, f" ({r.detalhe})" if r.detalhe else "")
            if r.status == "erro":
                erros.append(f"{item.video.name}: {r.detalhe}")
            elif r.status == "previa":
                contas["previas"] += 1
            elif r.status == "dublado":
                contas["dublados"] += 1
                if legendar and o.dublagem_no_original:
                    contas["legendas_no_video"] += 1
    embutir_agora = planejar_avulsos(o, pasta, arquivos, sondar).embutir if legendar and not parado() else []
    ffmpeg = localizar_ffmpeg() if embutir_agora else None
    for k, (video, srt) in enumerate(embutir_agora):
        if parado() or not ffmpeg:
            break
        andamento(k / len(embutir_agora), f"Pondo a legenda no vídeo {k + 1} de {len(embutir_agora)}: {video.stem}")
        try:
            final = embutir_legenda(ffmpeg, video, srt, parar=parar)
            log.info("[legenda no vídeo] avulso %s", final.name)
            contas["legendas_no_video"] += 1
        except (ErroDublagem, OSError) as erro:
            log.error("[erro] legenda no vídeo %s (%s)", video.name, erro)
            erros.append(f"{video.name}: {erro}")
    resumo = (f"Vídeos avulsos: {contas['traduzidas']} legenda(s) traduzida(s), {contas['pelo_audio']} criada(s) pelo "
              f"áudio, {contas['dublados']} dublado(s), {contas['legendas_no_video']} com a legenda dentro do vídeo"
              + (f", {contas['previas']} prévia(s) para ouvir e aprovar" if contas["previas"] else "")
              + (f", {contas['no_lote']} legenda(s) no modo econômico (metade do preço; prontas em até 24 h, a "
                 "dublagem delas fica para a próxima vez)" if contas["no_lote"] else "")
              + (f", {len(erros)} problema(s)." if erros else "."))
    if plano.vazio and not dublar_agora and not embutir_agora and not contas["traduzidas"]:
        resumo = "Vídeos avulsos: nada a fazer (já têm legenda em português e dublagem, ou não há vídeos)."
    return Resultado("--avulsos", PROBLEMA if erros else OK, resumo, erros, contas)


# ---------------------------------------------------------------------------- teste (só alguns minutos)
@dataclasses.dataclass
class ResultadoTeste:
    amostra: Path | None
    trecho: tuple[float, float] = (0.0, 0.0)
    falas: int = 0
    passos: list = field(default_factory=list)    # o que foi feito (para a mensagem)
    erro: str = ""
    problemas: list = field(default_factory=list)  # relatório de qualidade (falas para conferir)
    custo: float = 0.0                             # US$ gastos no teste (para prever o vídeo inteiro)
    custos: dict = field(default_factory=dict)     # {API: (US$, grátis?)}: o custo do teste em cada API


def _duracao(segundos: float) -> str:
    """"45 s", "2 min", "1,5 min", "29 min", "1 h 40 min" (antes: "28,9932 min")."""
    if segundos < 60:
        return f"{int(segundos)} s"
    minutos = segundos / 60
    if minutos >= 60:
        horas, resto = divmod(round(minutos), 60)
        return f"{horas} h {resto} min" if resto else f"{horas} h"
    return (f"{minutos:.1f}".rstrip("0").rstrip(".") if minutos < 10 else f"{round(minutos)}").replace(".", ",") \
        + " min"


# ---------------------------------------------------------------------------- testes feitos (para abrir de novo)
def arquivo_testes() -> Path:
    return pasta_dublagem() / "testes.json"


def _ler_testes() -> list:
    try:
        dados = json.loads(arquivo_testes().read_text(encoding="utf-8"))
        return [t for t in dados if isinstance(t, dict) and t.get("amostra")] if isinstance(dados, list) else []
    except (OSError, ValueError):
        return []


ABAS_DOS_TESTES = {"jellyfin": "Jellyfin", "avulsos": "Avulsos", "audio": "Áudio"}


def aba_do_teste(teste: dict) -> str:
    """Onde o teste foi feito: 'jellyfin', 'avulsos' ou 'audio' (a aba Áudio). Os de antes da v2.18.12 não
    guardavam: o dos Avulsos tem a legenda no progresso do Maestro (ou nenhuma: só legendar); o do Jellyfin usa a
    legenda que fica ao lado do vídeo."""
    if teste.get("aba") in ABAS_DOS_TESTES:
        return teste["aba"]
    if not teste.get("legenda"):
        return "avulsos"
    try:
        Path(teste["legenda"]).resolve().relative_to(pasta_dublagem().resolve())
        return "avulsos"
    except (ValueError, OSError):
        return "jellyfin"


def _legenda_do_teste(legenda: Path, amostra: Path) -> Path:
    """A legenda de um teste dos Avulsos ('teste.pt-BR.srt', no progresso do vídeo) é refeita a cada teste: uma
    cópia fica junto do teste, para "Ajustar falas" de um teste antigo usar as falas DELE. Fica em 'legendas' (ao
    lado do vídeo, o player a abriria por cima da legenda do próprio teste)."""
    try:
        legenda.resolve().relative_to(pasta_dublagem().resolve())
    except (ValueError, OSError):
        return legenda                                   # a do Jellyfin (ao lado do filme) não muda a cada teste
    copia = amostra.parent / "legendas" / f"{amostra.stem}{''.join(legenda.suffixes[-2:])}"
    try:
        copia.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(legenda, copia)
        return copia
    except OSError:
        return legenda


def registrar_teste(video: str | Path, amostra: str | Path, trecho: tuple[float, float], legenda=None,
                    vozes: dict | None = None, custo: float | None = None, legendar: bool = False,
                    custos: dict | None = None, aba: str = "jellyfin") -> None:
    """Guarda o teste na lista "Testes feitos" (o vídeo de teste fica em 'testes'). Cada teste fica guardado, até
    vários do mesmo vídeo (antes, o novo apagava o anterior), até você apagar. aba: 'jellyfin', 'avulsos' ou
    'audio' (de onde veio; a janela abre mostrando os da aba). legenda e vozes: para "Ajustar falas" refazer só uma
    fala do teste; custo (US$): para prever o vídeo inteiro."""
    lista = [t for t in _ler_testes() if t.get("amostra") != str(amostra)]
    registro = {"video": str(video), "amostra": str(amostra), "trecho": [round(trecho[0], 1), round(trecho[1], 1)],
                "feito": datetime.now().isoformat(timespec="seconds"), "minutos": round((trecho[1] - trecho[0]) / 60, 2),
                "legendar": bool(legendar), "aba": aba if aba in ABAS_DOS_TESTES else "jellyfin"}
    if legenda:
        registro["legenda"] = str(_legenda_do_teste(Path(legenda), Path(amostra)))
    if vozes:
        registro["vozes"] = {str(k): v for k, v in vozes.items()}
    if custo is not None:
        registro["custo"] = round(max(0.0, custo), 4)
    if custos:
        registro["custos"] = {api: [round(usd, 5), bool(gratis)] for api, (usd, gratis) in custos.items()}
    lista.insert(0, registro)
    _gravar_testes(lista)


def _gravar_testes(lista: list) -> None:
    try:
        arquivo_testes().parent.mkdir(parents=True, exist_ok=True)
        arquivo_testes().write_text(json.dumps(lista, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def testes_feitos() -> list:
    """Os testes cujo vídeo de teste ainda existe, do mais novo para o mais velho (com a 'aba' de onde vieram,
    também nos antigos)."""
    return [{**t, "aba": aba_do_teste(t)} for t in _ler_testes() if Path(t["amostra"]).is_file()]


def tamanho_dos_testes(testes: list) -> int:
    """Bytes ocupados pelos vídeos de teste (para a janela mostrar quanto apagar libera)."""
    total = 0
    for t in testes:
        try:
            total += Path(t["amostra"]).stat().st_size
        except OSError:
            pass
    return total


def apagar_testes(testes: list) -> int:
    """Apaga os vídeos de teste (e a cópia da legenda de cada um) e tira da lista. O vídeo original e as falas já
    geradas continuam. Devolve quantos foram apagados."""
    amostras = {str(t.get("amostra")) for t in testes if t.get("amostra")}
    pasta_testes = pasta_dublagem() / "testes"
    for t in testes:
        Path(t["amostra"]).unlink(missing_ok=True)
        legenda = Path(t.get("legenda") or "")
        if t.get("legenda") and legenda.parent == pasta_testes / "legendas":
            legenda.unlink(missing_ok=True)
    _gravar_testes([t for t in _ler_testes() if t.get("amostra") not in amostras])
    return len(amostras)


def apagar_teste(teste: dict) -> None:
    apagar_testes([teste])


def refazer_fala(o: OpcoesJellyfin, teste: dict, k: int, log: logging.Logger, texto: str = "", voz: str = "",
                 tom: str = "", separar=None, parar=None, ao_progresso=None):
    """"Ajustar falas" > "Refazer esta fala": guarda o ajuste (texto que a voz lê, voz ou tom; vazio = automático),
    apaga só o áudio dessa fala e monta o vídeo de teste de novo. As outras falas, a escuta e o fundo já estão
    guardados: paga só essa fala. O ajuste vale também quando o vídeo inteiro for dublado."""
    video, legenda = Path(teste["video"]), Path(teste.get("legenda", ""))
    if not teste.get("legenda") or not legenda.is_file():
        raise FaltaConfiguracao("este teste é de uma versão anterior (ou a legenda dele sumiu): faça o teste de novo "
                                "para poder ajustar as falas")
    falas = falas_da_legenda(legenda)
    if not 0 <= k < len(falas):
        raise ErroDublagem("essa fala não está mais na legenda do teste")
    pasta = pasta_do_filme(pasta_dublagem(), video)
    salvar_ajuste(pasta, chave_da_fala(falas[k][0]), texto, voz, tom)
    esquecer_fala(pasta, k)
    motor = preparar_motor(o)
    vozes = {int(n): v for n, v in dict(teste.get("vozes") or {}).items()}
    log.info("Ajustar falas: refazendo a fala %s de %s%s%s%s", chave_da_fala(falas[k][0]), video.name,
             f" (texto: \"{texto}\")" if texto else "", f" (voz: {voz})" if voz else "", f" (tom: {tom})" if tom else "")
    antes = gasto_ate_agora()
    r = dublar_video(video, legenda, motor, trecho=tuple(teste["trecho"]), destino=Path(teste["amostra"]),
                     pasta_cache=pasta_dublagem(), separar=separar, ambientar=getattr(o, "ambientar_voz", True),
                     legenda_no_video=bool(teste.get("legendar")), adaptar=adaptador(o, video.stem), vozes=vozes,
                     tons=ouvinte_de_tons(o, video, motor, log), por_genero=vozes_por_genero(o, motor),
                     pronuncias=pronuncias_de(o), manter_sons=getattr(o, "manter_sons", True),
                     camada_emocao=getattr(o, "camada_de_emocao", True), parar=parar, ao_progresso=ao_progresso,
                     avisar=lambda aviso: log.warning("Ajustar falas: %s", aviso))
    if r.status != "dublado":
        raise ErroDublagem(r.detalhe)
    log.info("Ajustar falas: pronto (custou ~US$ %.4f)", max(0.0, gasto_ate_agora() - antes))
    registrar_qualidade(log, r, "Teste")
    return r


def falas_do_teste(teste: dict) -> list[tuple[int, str, str, str, str]]:
    """[(número, horário, texto que a voz lê, voz, tom)] das falas do teste, para a janela "Ajustar falas"."""
    legenda = Path(teste.get("legenda", ""))
    if not teste.get("legenda") or not legenda.is_file():
        return []
    from jellyfin_tools.dublagem import ler_ajustes
    falas = falas_da_legenda(legenda)
    ajustes = ler_ajustes(pasta_do_filme(pasta_dublagem(), Path(teste["video"])))
    vozes = dict(teste.get("vozes") or {})
    inicio, fim = teste["trecho"][:2]
    saida = []
    for k, (f, texto) in enumerate(falas):
        if inicio <= horarios(f.tempo)[0] < fim:
            ajuste = ajustes.get(chave_da_fala(f), {})
            saida.append((k, chave_da_fala(f)[:8], ajuste.get("texto") or texto, ajuste.get("voz") or vozes.get(str(k), ""),
                          ajuste.get("tom", "")))
    return saida


def localizar_vlc() -> str | None:
    """O vlc.exe instalado (pasta padrão do Windows, 64 ou 32 bits) ou no PATH; None se não houver."""
    candidatos = [os.path.join(os.environ.get(v, ""), "VideoLAN", "VLC", "vlc.exe")
                  for v in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "LOCALAPPDATA") if os.environ.get(v)]
    achado = next((c for c in candidatos if os.path.isfile(c)), None)
    return achado or shutil.which("vlc")


def programa_do_player(o) -> str | None:
    """O programa que abre as prévias e os testes (None: o programa padrão do Windows)."""
    escolha = (getattr(o, "player_video", "vlc") or "vlc").strip()
    if escolha == "padrao":
        return None
    if escolha == "vlc":
        return localizar_vlc()
    return escolha if os.path.isfile(escolha) else localizar_vlc()


class _Relogio:
    """", faltam ~2 min" pela velocidade até agora (só depois de 15 s e 3% feitos, para não chutar)."""

    def __init__(self, agora=time.monotonic):
        self.agora, self.inicio = agora, agora()

    def falta(self, fracao: float) -> str:
        passou = self.agora() - self.inicio
        if fracao < 0.03 or passou < 15 or fracao >= 1:
            return ""
        segundos = passou * (1 - fracao) / fracao
        if segundos < 5:
            return ""
        return f", faltam ~{max(1, round(segundos / 60))} min" if segundos >= 60 else f", faltam ~{int(segundos)} s"


def minutos_de_teste(o: OpcoesJellyfin) -> float:
    return max(0.5, min(float(getattr(o, "minutos_teste", 2) or 2), 60.0))


def ler_inicio(texto) -> float | None:
    """O início do teste digitado: "12:30" (minutos:segundos), "1:02:30" (horas), "12" (minutos) ou vazio/"auto"
    (None: o Maestro escolhe o trecho com mais falas). Texto que não dá para entender: ValueError."""
    texto = str(texto or "").strip().lower()
    if texto in ("", "auto", "automático", "automatico"):
        return None
    partes = texto.replace(",", ".").split(":")
    try:
        numeros = [float(x) for x in partes]
    except ValueError:
        raise ValueError(texto) from None
    if len(numeros) > 3 or any(n < 0 for n in numeros) or any(n >= 60 for n in numeros[1:]):
        raise ValueError(texto)
    if len(numeros) == 1:
        return numeros[0] * 60                       # um número só: minutos
    segundos = 0.0
    for n in numeros:
        segundos = segundos * 60 + n
    return segundos


def texto_do_inicio(segundos: float) -> str:
    s = int(segundos)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def trecho_do_teste(o: OpcoesJellyfin, falas: list | None, segundos: float,
                    duracao: float | None = None) -> tuple[float, float]:
    """(início, fim) do teste: a partir do minuto escolhido ("a partir de", para testar uma cena com várias pessoas
    falando) ou, vazio, o trecho com mais falas (sem legenda: um pedaço depois da abertura)."""
    from jellyfin_tools.dublagem import trecho_de_amostra
    try:
        inicio = ler_inicio(getattr(o, "inicio_teste", ""))
    except ValueError:
        raise ErroDublagem(f"não entendi o início do teste \"{o.inicio_teste}\": use minutos:segundos, como 12:30 "
                           "(ou deixe vazio para o Maestro escolher)") from None
    if inicio is None:
        return trecho_de_amostra(falas, segundos) if falas else _trecho_sem_legenda(duracao, segundos)
    if duracao and inicio >= duracao:
        raise ErroDublagem(f"o teste começa em {texto_do_inicio(inicio)}, mas o vídeo tem só "
                           f"{texto_do_inicio(duracao)}")
    return inicio, inicio + segundos


def _trecho_sem_legenda(duracao: float | None, segundos: float) -> tuple[float, float]:
    """Sem legenda nenhuma ainda (não dá para achar o trecho com mais falas): um pedaço depois da abertura."""
    if not duracao or duracao <= segundos * 1.5:
        return 0.0, segundos
    inicio = min(duracao * 0.2, duracao - segundos)
    return inicio, inicio + segundos


def testar_avulso(o: OpcoesJellyfin, video: str | Path, log: logging.Logger, motor=None, separar=None,
                  transcritor=None, parar=None, andamento=None) -> ResultadoTeste:
    """Teste de alguns minutos (Configurações > Dublagem > "Teste"): legenda e/ou dubla SÓ esse trecho, num vídeo
    curto fora da biblioteca, para conferir antes de gastar com o vídeo inteiro. Não mexe no original nem cria o
    .srt ao lado dele: tudo fica na pasta de trabalho do Maestro.
    - já tem legenda em português: o trecho com mais falas;
    - legenda em outro idioma: só as falas do trecho são traduzidas;
    - sem legenda: o Whisper ouve só o trecho (e traduz, se não for português)."""
    from jellyfin_tools.dublagem import amostra_so_legenda, caminho_amostra, inspecionar, srt_do_trecho
    from jellyfin_tools.traducao import Fala, gerar_srt, ler_srt
    from jellyfin_tools.transcricao import tempo_srt
    from jellyfin_tools.legendas import extrair_srt
    andamento = andamento or (lambda fracao, texto: None)
    video = Path(video)
    gasto_antes, foto_antes = gasto_ate_agora(), foto_dos_gastos()
    vozes_teste = None
    idioma = o.idioma.split(",")[0].strip() or "pt-BR"
    segundos = minutos_de_teste(o) * 60
    ffmpeg = localizar_ffmpeg()
    if not ffmpeg:
        return ResultadoTeste(None, erro="falta o ffmpeg")
    pasta = pasta_do_filme(pasta_dublagem(), video)
    pasta.mkdir(parents=True, exist_ok=True)
    legenda_teste = pasta / f"teste.{idioma}.srt"
    r = ResultadoTeste(None)
    try:
        pt = srt_portugues(video, idioma)
        if pt:                                            # 1) já tem em português
            falas = ler_srt(extrair_srt(pt.read_bytes()))
            r.trecho = trecho_do_teste(o, [(f, f.texto) for f in falas], segundos)
            legenda_teste.write_text(gerar_srt(falas), encoding="utf-8")
            r.passos.append(f"legenda em português: {pt.name}")
        else:
            estrangeiras = [i for i in legendas_para_traduzir(video.parent, idioma=idioma) if i.video == video]
            tradutor = tradutor_para(o, idioma)
            if estrangeiras:                              # 2) traduz só as falas do trecho
                falas = ler_srt(extrair_srt(estrangeiras[0].origem.read_bytes()))
                r.trecho = trecho_do_teste(o, [(f, f.texto) for f in falas], segundos)
                dentro = [f for f in falas if r.trecho[0] <= horarios(f.tempo)[0] < r.trecho[1]]
                if tradutor is None:
                    raise ErroDublagem("a legenda está em outro idioma e falta a chave da Anthropic para traduzir")
                andamento(0.1, f"Teste: traduzindo {len(dentro)} falas do trecho")
                textos = tradutor.traduzir_falas([f.texto for f in dentro], titulo=video.stem, parar=parar)
                legenda_teste.write_text(gerar_srt([Fala(f.tempo, t) for f, t in zip(dentro, textos)]),
                                         encoding="utf-8")
                r.passos.append(f"traduziu só as {len(dentro)} falas do trecho")
            else:                                         # 3) o Whisper ouve só o trecho
                r.trecho = trecho_do_teste(o, None, segundos, inspecionar(ffmpeg, video).duracao)
                audio = pasta / "teste-audio.wav"
                subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{r.trecho[0]:.3f}",
                                "-t", f"{segundos:.3f}", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000",
                                str(audio)], check=True, capture_output=True)
                transcritor = transcritor or Transcritor(modelo=o.modelo_whisper, usar_gpu=o.whisper_gpu,
                                                         pasta_modelos=str(config.ARQUIVO.parent / "modelos_whisper"))
                modelo = getattr(transcritor, "modelo", "")
                andamento(0.05, f"Teste: carregando o Whisper ({modelo})" if modelo else "Teste: carregando o Whisper")
                log.info("Teste: o Whisper (modelo %s) vai ouvir %s de %s", modelo or "?", _duracao(segundos),
                         video.name)
                relogio = _Relogio()

                def ouvindo(fracao):                     # a barra anda enquanto o Whisper ouve (antes parava em 10%)
                    de_novo = (" (2ª vez, sem o filtro de voz: parece música)"
                               if getattr(transcritor, "aviso", "").startswith("o filtro de voz") else "")
                    andamento(0.05 + 0.35 * fracao, f"Teste: o Whisper está ouvindo o trecho {fracao * 100:.0f}%"
                              + de_novo + relogio.falta(fracao))
                lingua, _, ouvidas = transcritor.transcrever(audio, parar=parar, ao_progresso=ouvindo)
                if getattr(transcritor, "aviso", ""):
                    log.info("Whisper: %s", transcritor.aviso)
                audio.unlink(missing_ok=True)
                falas = [Fala(f"{tempo_srt(horarios(f.tempo)[0] + r.trecho[0])} --> "
                              f"{tempo_srt(horarios(f.tempo)[1] + r.trecho[0])}", f.texto) for f in ouvidas]
                if not falas:
                    raise ErroDublagem("o Whisper não reconheceu nenhuma fala nesse trecho")
                portugues = lingua in _PORTUGUES or lingua == idioma.lower().split("-")[0]
                log.info("Teste: o Whisper terminou (%d falas, áudio em %s)", len(falas), lingua or "?")
                if not portugues:
                    if tradutor is None:
                        raise ErroDublagem(f"o áudio está em {lingua} e falta a chave da Anthropic para traduzir")
                    quem = "tradução local" if usa_traducao_local(o) else "Claude"
                    andamento(0.42, f"Teste: traduzindo {len(falas)} falas ({quem})")
                    log.info("Teste: traduzindo %d falas (%s)", len(falas), quem)
                    textos = tradutor.traduzir_falas([f.texto for f in falas], titulo=video.stem, parar=parar)
                    falas = [Fala(f.tempo, t) for f, t in zip(falas, textos)]
                legenda_teste.write_text(gerar_srt(falas), encoding="utf-8")
                r.passos.append(f"o Whisper ouviu só o trecho ({len(falas)} falas"
                                + (", traduzidas)" if not portugues else ")"))
        destino = caminho_amostra(pasta_dublagem(), video)
        if o.avulsos_dublar:
            from jellyfin_tools.dublagem import RelogioDaDublagem
            voz = ("Gemini" if usa_gemini(o) else "Google Cloud" if usa_cloud(o) else "Piper")
            andamento(0.45, f"Teste: preparando a voz ({voz})")
            log.info("Teste: dublando com a voz do %s%s", voz, ", tirando as vozes originais" if separar else "")
            motor = motor or preparar_motor(o)
            relogio_dub = RelogioDaDublagem(bool(separar))
            # a barra só anda para a frente: o Whisper e a tradução ficaram com até 45%
            vozes_teste = vozes_do_teste(o, video, legenda_teste, r.trecho, log)
            r_dub = dublar_video(video, legenda_teste, motor, parar=parar, trecho=r.trecho, destino=destino,
                                 adaptar=adaptador(o, video.stem), pasta_cache=pasta_dublagem(), separar=separar,
                                 tons=ouvinte_de_tons(o, video, motor, log), por_genero=vozes_por_genero(o, motor),
                                 vozes=vozes_teste, pronuncias=pronuncias_de(o), manter_sons=getattr(o, "manter_sons", True),
                                 camada_emocao=getattr(o, "camada_de_emocao", True),
                                 ambientar=getattr(o, "ambientar_voz", True), legenda_no_video=o.avulsos_legendar,
                                 avisar=lambda texto: log.warning("Teste: %s", texto),
                                 ao_progresso=lambda f: andamento(0.45 + 0.55 * f,
                                                                  f"Teste: {relogio_dub.texto(f)} ({voz})"))
            if r_dub.status != "dublado":
                raise ErroDublagem(r_dub.detalhe)
            r.falas, r.problemas = r_dub.falas, list(r_dub.problemas)
            registrar_qualidade(log, r_dub, "Teste")
            r.passos.append(f"dublou só as {r_dub.falas} falas do trecho")
        else:
            texto = srt_do_trecho(ler_srt(legenda_teste.read_text(encoding="utf-8")), r.trecho)
            janela = pasta / "teste-trecho.srt"
            janela.write_text(texto, encoding="utf-8")
            amostra_so_legenda(ffmpeg, video, janela, r.trecho, destino, parar,
                               lambda f: andamento(0.2 + 0.8 * f, f"Teste: montando a amostra ({int(f * 100)}%)"))
            r.falas = texto.count(" --> ")
            r.passos.append("só a legenda (sem dublar)")
        r.amostra = destino
        r.custo = max(0.0, gasto_ate_agora() - gasto_antes)
        r.custos = custos_por_api(foto_antes)
        registrar_teste(video, destino, r.trecho, legenda_teste if o.avulsos_dublar else None, vozes_teste, r.custo,
                        o.avulsos_legendar, r.custos, aba="avulsos")
        log.info("Teste de %s (%s a %s): %s", video.name, tempo_srt(r.trecho[0])[:8], tempo_srt(r.trecho[1])[:8],
                 "; ".join(r.passos))
    except (ErroDublagem, OSError, ErroLegenda, subprocess.CalledProcessError, FaltaConfiguracao) as erro:
        r.erro = str(erro)
        log.error("Teste de %s: %s", video.name, erro)
    except Exception as erro:                        # ErroTraducao, ErroTranscricao...
        r.erro = str(erro)
        log.error("Teste de %s: %s", video.name, erro)
    return r


def avulsos(log: logging.Logger) -> Resultado:
    """Robô --avulsos: a caixa de entrada inteira (Configurações > Vídeos avulsos)."""
    o, _ = opcoes_salvas()
    if not o.pasta_avulsos or not Path(o.pasta_avulsos).is_dir():
        raise FaltaConfiguracao("Escolha a pasta de vídeos avulsos (Configurações > Vídeos avulsos).")
    if o.robo_so_piper:                               # opção "Nos robôs agendados, usar só o Piper (sem custo)"
        o.motor_voz, o.voz_por_personagem, o.figurantes_piper = "Piper (grátis, no PC)", False, False
        o.sem_gemini = True                           # nem a escuta dos sons sem fala (sem custo nenhum)
    return processar_avulsos(o, log, o.pasta_avulsos, avisar=lambda texto: log.info("%s", texto))


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
    p.add_argument("--economico", action="store_true",
                   help="traduzir: em lote, metade do preço (pronto em até 24 h; a próxima execução grava)")
    p.add_argument("--limite-videos", type=int, default=5,
                   help="legendar-audio: quantos vídeos por execução (0 = todos)")
    p.add_argument("--resultado", help="onde gravar o resumo em JSON (padrão ~/.videoscraper/rpa/ultimo.json)")
    return p


def _rodar(comando: str, args, log: logging.Logger) -> Resultado:
    acoes = {"--organizar": lambda: organizar(log, args.simular),
             "--conferir-espelhos": lambda: conferir_os_espelhos(log),
             "--conferir-canais": lambda: conferir_os_canais(log),
             "--enviar-tv": lambda: enviar_tv(log),
             "--traduzir-legendas": lambda: traduzir_legendas(log, args.limite_dolares, args.economico),
             "--legendar-audio": lambda: legendar_audio(log, args.limite_videos, args.limite_dolares),
             "--sincronizar-legendas": lambda: sincronizar_legendas(log, args.limite_videos),
             "--dublar": lambda: dublar(log, args.limite_videos),
             "--avulsos": lambda: avulsos(log),
             "--continuar-dublagem": lambda: continuar_dublagem(log)}
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
            for item, quantidade in r.contagens.items():
                ResumoDiario(pasta / "resumo_do_dia.json").registrar(item, quantidade)
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
