"""Voz PREMIUM da dublagem: o Gemini (Google AI Studio) lê as falas, no lugar do Piper.

    Piper  -> grátis, roda no PC, voz mais "robótica"
    Gemini -> pago por uso (chave do Google AI Studio), voz bem mais natural e com entonação

Vozes PRONTAS (genéricas) do Gemini e, se você criar, vozes CLONADAS ("clone:Nome", ver voz_clonada.py): só a voz
de quem autorizou e gravou a frase de consentimento, nunca a de atores.
O motor tem a mesma cara do MotorPiper (sintetizar(pedidos)): cada fala vira um .wav (24 kHz, mono, 16 bits).

BLOCOS (economiza pedidos e mantém a voz igual): em vez de 1 pedido por fala (um filme tem ~1.200), o motor manda até
BLOCO falas seguidas (uma conversa curta) num pedido só, com uma pausa longa entre elas, e depois corta o áudio nas pausas:

    "Oi. <long pause> Tudo bem? <long pause> Vamos."  ->  ▁▁███▁▁▁▁▁▁█████▁▁▁▁▁▁███▁▁  ->  3 arquivos .wav

O corte confere se cada pedaço tem um tamanho coerente com o texto; se não bater (o modelo juntou duas falas, ou parou
no meio de uma frase), só aquele bloco é refeito em duas metades (e assim por diante), em vez de soltar uma palavra
no lugar da outra. Com vozes diferentes (uma por personagem), cada bloco tem no
máximo 2 vozes e vai como um DIÁLOGO (o Gemini aceita 2 falantes por pedido).

A chave: aistudio.google.com > "Get API key". O Gemini cobra por token de áudio gerado; a camada grátis tem limites
baixos por minuto e por dia (o motor espera e tenta de novo; o limite do dia faz parar e guardar o que já fez).
"""

from __future__ import annotations

import base64
import io
import json
import re
import threading
import time
import wave
from array import array
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

from . import gastos
from .dublagem import ErroDublagem

MODELO_PADRAO = "gemini-3.8-flash-tts"
MODELO_OUVIR = "gemini-3.8-flash"     # o que OUVE o filme para separar quem fala (voz por personagem)
# vozes prontas do Gemini (há 30; estas combinam com dublagem). Ouça todas em aistudio.google.com/generate-speech
VOZES = {"Charon": "masculina, informativa", "Orus": "masculina, firme", "Puck": "masculina, animada",
         "Fenrir": "masculina, empolgada", "Iapetus": "masculina, clara", "Algieba": "masculina, suave",
         "Enceladus": "masculina, sussurrada",
         "Kore": "feminina, firme", "Aoede": "feminina, leve", "Leda": "feminina, jovem",
         "Zephyr": "feminina, brilhante", "Despina": "feminina, suave", "Callirrhoe": "feminina, tranquila",
         "Autonoe": "feminina, clara"}
VOZES_MASCULINAS = tuple(v for v, d in VOZES.items() if d.startswith("masculina"))
VOZES_FEMININAS = tuple(v for v, d in VOZES.items() if d.startswith("feminina"))
VOZ_PADRAO = "Charon"
ESTILO = ("Dublagem brasileira de filme: fale em português do Brasil, natural e com a emoção da cena, no ritmo de "
          "uma conversa, sem soar como locutor lendo.")
TAXA = 24000                  # o Gemini devolve 24 kHz, mono, 16 bits
TOKENS_POR_SEGUNDO = 32       # áudio vira ~32 tokens por segundo (para a ESTIMATIVA de custo)
PRECO_SAIDA = (6.0, 20.0)     # US$ por milhão de tokens de áudio: faixa dos modelos TTS do Gemini (confira o atual)
PRECO_OUVIR = 1.0             # US$ por milhão de tokens de áudio ENVIADO (ouvir quem fala; estimativa, confira)
KBPS_OUVIR = 32               # o áudio enviado para ouvir vai em mp3 de 32 kbps (personagens.audio_do_trecho)
SIMULTANEOS = 4               # blocos pedidos ao mesmo tempo
TEMPO_LIMITE = 300            # segundos que um pedido pode levar (um bloco de 30 falas leva bem menos)
TEMPO_LIMITE_FLEX = 1200      # no modo Flex, o Google pode demorar de 1 a 15 minutos por pedido
DESCONTO_FLEX = 0.5           # o Flex custa metade do preço normal
_flex = {"ligado": False}     # Configurações > Gastos > "Modo econômico do Gemini (Flex)" (usar_flex)
TENTATIVAS = 6
ESPERA_MAXIMA = 90            # no limite por minuto, espera o que o Google pedir ("retry in 39s"), até 90 s
AVISO_ESPERA = 60             # sem resposta do Google há tanto tempo: avisa no log (para não parecer travado)
BLOCO = 10                    # falas por pedido (com 30, uma pausa no lugar errado jogava palavras na fala seguinte)
LETRAS_POR_BLOCO = 700
PAUSA = " <long pause>"       # marca de pausa do Gemini TTS entre uma fala e a próxima do bloco


def texto_da_voz(voz: str) -> str:
    """'Kore (feminina, firme)' para os menus; 'clone:Izael' -> 'Izael (voz clonada)'."""
    if voz.startswith("clone:"):
        return f"{voz[len('clone:'):]} (voz clonada)"
    return f"{voz} ({VOZES.get(voz, '')})" if voz in VOZES else voz


def estimar_custo(segundos_de_fala: float) -> tuple[float, float]:
    """(mínimo, máximo) em US$ para gerar essa quantidade de fala. Estimativa: o preço muda; confira no AI Studio."""
    tokens = segundos_de_fala * TOKENS_POR_SEGUNDO
    return tokens * PRECO_SAIDA[0] / 1_000_000, tokens * PRECO_SAIDA[1] / 1_000_000


def blocos(itens: list, bloco: int = BLOCO, letras: int = LETRAS_POR_BLOCO) -> list[list]:
    """Agrupa [(texto, wav, voz[, tom])] em blocos de falas SEGUIDAS: até `bloco` falas, `letras` letras e 2 vozes."""
    grupos, atual, vozes = [], [], set()
    for item in itens:
        texto, _, voz = item[:3]
        cabe = (len(atual) < bloco and sum(len(i[0]) for i in atual) + len(texto) <= letras
                and len(vozes | {voz}) <= 2)
        if atual and not cabe:
            grupos.append(atual)
            atual, vozes = [], set()
        atual.append(item)
        vozes.add(voz)
    if atual:
        grupos.append(atual)
    return grupos


def pedidos_estimados(falas: int, vozes: list[str] | None = None) -> int:
    """Quantos pedidos ao Gemini para `falas` falas (com a lista de vozes por fala, se houver). Aproximado."""
    itens = [("x" * 40, None, (vozes[i] if vozes else VOZ_PADRAO)) for i in range(falas)]
    return len(blocos(itens))


# ----------------------------------------------------------------- cortar o áudio do bloco nas pausas
JANELA = 0.01                 # 10 ms
PAUSA_MINIMA = 0.12           # silêncio mais curto que isso não conta como pausa
FOLGA_CORTE = 0.04            # silêncio que fica antes e depois de cada fala cortada
FOLGA_TAXA = 2.2              # um pedaço pode ser até 2,2x mais lento/rápido que a mediana do bloco (era 3x)
LETRAS_POR_SEGUNDO = (2.5, 28)  # fala de verdade: entre 2,5 (dramática, lenta) e 28 letras por segundo


def separar_por_pausas(amostras: array, taxa: int, pesos: list[int]) -> list[tuple[int, int]] | None:
    """Corta o áudio de um bloco em len(pesos) pedaços nas PAUSAS entre as falas. pesos: letras de cada fala (o
    pedaço de uma fala longa tem que ser mais longo). Cada corte é a pausa mais longa PERTO de onde aquela fala
    deveria terminar pelas letras (_melhores_pausas): uma pausa dramática no meio de uma frase ("Espelho... espelho
    meu") não vira corte só por ser comprida. Devolve [(início, fim)] em amostras, ou None se não der para
    confiar no corte (menos pausas que o preciso, ou um pedaço com tamanho incoerente com o texto)."""
    n = len(pesos)
    passo = max(1, int(taxa * JANELA))
    nivel = [max((abs(x) for x in amostras[i:i + passo]), default=0) for i in range(0, len(amostras), passo)]
    if not nivel or max(nivel) == 0:
        return None
    limiar = max(nivel) * 0.06
    falando = [v > limiar for v in nivel]
    if True not in falando:
        return None
    primeiro, ultimo = falando.index(True), len(falando) - 1 - falando[::-1].index(True)
    if n == 1:
        return [(max(0, (primeiro - 4) * passo), min(len(amostras), (ultimo + 5) * passo))]
    pausas, inicio = [], None                          # (tamanho, começo, fim) dos silêncios ENTRE as falas
    for k in range(primeiro, ultimo + 1):
        if not falando[k] and inicio is None:
            inicio = k
        elif falando[k] and inicio is not None:
            if (k - inicio) * JANELA >= PAUSA_MINIMA:
                pausas.append((k - inicio, inicio, k))
            inicio = None
    if len(pausas) < n - 1:
        return None
    escolhidas = _melhores_pausas(pausas, pesos, primeiro, ultimo)
    folga = int(FOLGA_CORTE / JANELA)
    limites = [primeiro] + [x for _, a, b in escolhidas for x in (a, b)] + [ultimo + 1]
    pedacos = [(max(0, limites[2 * i] - folga) * passo, min(len(nivel), limites[2 * i + 1] + folga) * passo)
               for i in range(n)]
    taxas = sorted((fim - ini) / max(1, p) for (ini, fim), p in zip(pedacos, pesos))
    mediana = taxas[len(taxas) // 2]
    if mediana <= 0 or taxas[0] < mediana / FOLGA_TAXA or taxas[-1] > mediana * FOLGA_TAXA:
        return None                                    # um pedaço curto/longo demais para o texto: não confia
    for (ini, fim), p in zip(pedacos, pesos):          # e nenhuma fala impossível de dizer nesse tempo
        if p >= 8 and not LETRAS_POR_SEGUNDO[0] <= p / max(1e-3, (fim - ini) / taxa) <= LETRAS_POR_SEGUNDO[1]:
            return None
    return [(ini, min(fim, len(amostras))) for ini, fim in pedacos]


PESO_DISTANCIA = 0.8          # quanto custa, em janelas de pausa, cada janela de distância do ponto esperado


def _melhores_pausas(pausas: list[tuple[int, int, int]], pesos: list[int], primeiro: int,
                     ultimo: int) -> list[tuple[int, int, int]]:
    """As len(pesos)-1 pausas (em ordem) que melhor separam as falas: pausa longa E perto do ponto esperado (onde a
    fala terminaria se o tempo fosse proporcional às letras). Programação dinâmica: melhor[j][i] = a melhor soma
    usando a pausa i como o j-ésimo corte."""
    # o tempo do bloco = falas (proporcionais às letras) + as pausas entre elas (do tamanho das mais longas)
    cortes = len(pesos) - 1
    pausa = sorted((t for t, _, _ in pausas), reverse=True)[:cortes]
    pausa_media = sorted(pausa)[(len(pausa) - 1) // 2] if pausa else 0     # a do meio (com 2, a menor: a outra
    # pode ser uma pausa dramática)
    fala = max(1, (ultimo - primeiro) - cortes * pausa_media)
    total, acumulado, esperados = sum(pesos), 0, []
    for j, p in enumerate(pesos[:-1]):
        acumulado += p
        esperados.append(primeiro + fala * acumulado / total + (j + 0.5) * pausa_media)

    def nota(i: int, j: int) -> float:
        tamanho, a, b = pausas[i]
        return tamanho - PESO_DISTANCIA * abs((a + b) / 2 - esperados[j])
    k, m = len(esperados), len(pausas)
    melhor = [[float("-inf")] * m for _ in range(k)]
    veio = [[-1] * m for _ in range(k)]
    for i in range(m):
        melhor[0][i] = nota(i, 0)
    for j in range(1, k):
        topo, onde = float("-inf"), -1
        for i in range(j, m):                       # o j-ésimo corte vem depois do (j-1)-ésimo
            if melhor[j - 1][i - 1] > topo:
                topo, onde = melhor[j - 1][i - 1], i - 1
            melhor[j][i] = topo + nota(i, j)
            veio[j][i] = onde
    i = max(range(k - 1, m), key=lambda x: melhor[k - 1][x])
    escolhidas = []
    for j in range(k - 1, -1, -1):
        escolhidas.append(pausas[i])
        i = veio[j][i]
    return escolhidas[::-1]


def _ler_audio(dados) -> tuple[array, int]:
    """(amostras de 16 bits, taxa) do áudio devolvido: WAV completo (começa com RIFF) ou PCM puro; às vezes em
    base64."""
    if isinstance(dados, str):
        dados = base64.b64decode(dados)
    elif not dados.startswith(b"RIFF"):
        try:
            decodificado = base64.b64decode(dados, validate=True)
            dados = decodificado if decodificado.startswith(b"RIFF") else dados
        except ValueError:
            pass
    amostras = array("h")
    if dados.startswith(b"RIFF"):
        with wave.open(io.BytesIO(dados), "rb") as w:
            if w.getsampwidth() != 2 or w.getnchannels() != 1:
                raise ErroDublagem("o Gemini devolveu um áudio num formato inesperado")
            amostras.frombytes(w.readframes(w.getnframes()))
            return amostras, w.getframerate()
    amostras.frombytes(dados[:len(dados) // 2 * 2])
    return amostras, TAXA


def _gravar_wav(amostras: array, taxa: int, destino: Path) -> None:
    """Grava inteiro ou nada (arquivo .tmp e troca): um .wav pela metade não fica no meio do progresso guardado."""
    parcial = destino.with_name(destino.name + ".tmp")
    with wave.open(str(parcial), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(taxa)
        w.writeframes(amostras.tobytes())
    parcial.replace(destino)


# ----------------------------------------------------------------- erros e cliente
def _codigo(erro: Exception):
    return getattr(erro, "code", None) or getattr(erro, "status_code", None)


def _explicar(erro: Exception) -> str:
    """O erro do SDK do Google em português (pelo código HTTP, quando houver)."""
    codigo, texto = _codigo(erro), str(erro)
    if codigo in (400, 401, 403) and ("key" in texto.lower() or "API_KEY" in texto or codigo != 400):
        return "a chave do Google AI Studio foi recusada (confira em aistudio.google.com > Get API key)"
    if codigo == 404:
        return f"modelo do Gemini não encontrado ({texto[:80]})"
    if _limite_por_minuto(erro):
        return (f"o Gemini continuou no limite de pedidos por minuto depois de {TENTATIVAS} tentativas"
                + (" (chave grátis)" if _camada_gratis(erro) else "") + "; o que já ficou pronto está guardado: "
                "tente de novo em alguns minutos")
    if _camada_gratis(erro):
        return ("limite do dia da chave GRÁTIS do Gemini atingido (sem faturamento ativo no Google); o que já ficou "
                "pronto está guardado e a próxima dublagem continua de onde parou")
    if codigo == 429 or "RESOURCE_EXHAUSTED" in texto:
        return ("limite de uso do Gemini atingido (a camada grátis tem limites baixos por dia); o que já ficou pronto "
                "está guardado e a próxima dublagem continua de onde parou")
    if type(erro).__name__ in ("APITimeoutError", "ReadTimeout", "TimeoutException"):
        return (f"o Gemini não respondeu em {(TEMPO_LIMITE_FLEX if _flex['ligado'] else TEMPO_LIMITE) // 60} min, "
                "duas vezes (o Google está lento agora); o que já ficou pronto está guardado: tente de novo daqui a "
                "pouco")
    if type(erro).__name__ in ("ConnectError", "ConnectTimeout", "APIConnectionError"):
        return "sem conexão com o Gemini"
    return f"{type(erro).__name__}: {texto}"[:300]


def _camada_gratis(erro: Exception) -> bool:
    """O erro de limite (429) diz que a chave está na camada grátis ("generate_content_free_tier_requests",
    quotaId "...-FreeTier"); numa chave com faturamento ativo o limite é outro e o texto não fala nisso."""
    texto = str(erro).lower()
    return (_codigo(erro) == 429 or "resource_exhausted" in texto) and ("free_tier" in texto or "freetier" in texto)


def _limite(erro: Exception) -> bool:
    return _codigo(erro) in (429, 500, 503) or "RESOURCE_EXHAUSTED" in str(erro)


DIRECAO = ("Siga as notas de direção abaixo, que descrevem o áudio original: repita a mesma emoção, intensidade, "
           "ritmo e volume, sem suavizar (se o original é exagerado ou teatral, a dublagem também é).")


def estilo_da_fala(estilo: str, tom: str) -> str:
    """O estilo geral + as notas de direção desta fala (tom.py: a cena e COMO ela é dita no original)."""
    if not tom:
        return estilo
    nota = tom if tom.startswith(("Cena:", "Quem fala:", "Nesta fala:", "Ritmo:")) else f"Nesta fala: {tom}."
    return f"{estilo} {DIRECAO} {nota}"


def usar_flex(ligado: bool) -> None:
    """Modo econômico: os pedidos ao Gemini vão no nível "Flex" (metade do preço, mais lentos: o Google responde
    quando tem folga, em até ~15 min por pedido). Vale para a voz e para a escuta do original."""
    _flex["ligado"] = bool(ligado)


class _PedidosFlex:
    """interactions.create com service_tier="flex"; se o Google (ou a versão da biblioteca) não aceitar, volta ao
    normal sozinho e avisa uma vez (o pedido não se perde)."""

    def __init__(self, base, dono):
        self.base, self.dono = base, dono

    def create(self, **k):
        if self.dono.flex:
            try:
                return self.base.create(service_tier="flex", **k)
            except TypeError:
                pass                                       # a biblioteca instalada ainda não conhece o Flex
            except Exception as erro:
                texto = str(erro).lower()
                if _codigo(erro) != 400 or not ("service_tier" in texto or "flex" in texto or "tier" in texto):
                    raise
            self.dono.flex = False
            if self.dono.avisar:
                self.dono.avisar("o modo Flex do Gemini não foi aceito para este modelo: seguindo no preço normal")
        return self.base.create(**k)


class ClienteFlex:
    """O cliente do Gemini no modo Flex: mesmo uso do genai.Client (interactions.create, models.get)."""

    def __init__(self, base, avisar=None):
        self.base, self.flex, self.avisar = base, True, avisar
        self.interactions = _PedidosFlex(base.interactions, self)
        self.models = base.models


def _cliente(chave: str, avisar=None):
    try:
        from google import genai
    except ImportError as erro:
        raise ErroDublagem("falta a biblioteca do Gemini (pip install google-genai)") from erro
    # sem tempo-limite, um pedido que o Google não respondesse prendia a dublagem para sempre
    flex = _flex["ligado"]
    base = genai.Client(api_key=chave, http_options={"timeout": (TEMPO_LIMITE_FLEX if flex else TEMPO_LIMITE) * 1000})
    _sem_repeticoes_escondidas(base)
    return ClienteFlex(base, avisar) if flex else base


def _sem_repeticoes_escondidas(cliente) -> None:
    """A biblioteca do Google repete SOZINHA, e calada, o pedido que recebe limite (429) ou erro do servidor: até 4
    vezes, esperando o tempo pedido pelo Google. Somado às 6 tentativas do Maestro, um pedido virava até 24, sem
    nada no log (o teste parecia travado). Desliga: quem repete é _com_tentativas, que avisa cada espera."""
    try:
        cliente.interactions.sdk_configuration.retry_config = None
    except Exception:                                  # outra versão da biblioteca: segue como ela fizer
        pass


def fator_de_preco(cliente) -> float:
    """1,0 no preço normal; 0,5 no modo Flex (para o painel de gastos estimar certo)."""
    return DESCONTO_FLEX if getattr(cliente, "flex", False) is True else 1.0


def testar_chave(chave: str, modelo: str = MODELO_PADRAO, cliente=None) -> str:
    """Confere se a chave do AI Studio funciona e o modelo de voz existe, SEM gerar áudio (sem custo)."""
    if not chave.strip():
        raise ErroDublagem("preencha a chave do Google AI Studio")
    try:
        cliente = cliente or _cliente(chave.strip())
        info = cliente.models.get(model=modelo)
    except ErroDublagem:
        raise
    except Exception as erro:
        raise ErroDublagem(_explicar(erro)) from erro
    return getattr(info, "display_name", "") or modelo


def _conferir_teto() -> None:
    """Antes de cada pedido pago: passou do teto de gastos do mês? Para (o que já ficou pronto fica guardado)."""
    try:
        gastos.conferir()
    except gastos.TetoAtingido as erro:
        raise ErroDublagem(str(erro)) from erro


def custo_da_fala(segundos: float) -> float:
    """O custo estimado de `segundos` de áudio gerado, pelo preço MAIS ALTO da faixa (para o teto não ser
    ultrapassado por engano)."""
    return segundos * TOKENS_POR_SEGUNDO * PRECO_SAIDA[1] / 1_000_000


def _espera_pedida(erro: Exception) -> float:
    """Os segundos que o Google pediu para esperar no erro de limite ("Please retry in 39.9s", retryDelay '39s')."""
    achado = re.search(r"retry in ([\d.]+)\s*s|retryDelay['\"]?\s*:\s*['\"]([\d.]+)s", str(erro), re.IGNORECASE)
    return float(achado.group(1) or achado.group(2)) if achado else 0.0


def _limite_do_dia(erro: Exception) -> bool:
    """O limite que acabou é o do DIA (quotaId "...PerDay..."): esperar segundos não adianta, só amanhã."""
    return "perday" in str(erro).lower().replace("_", "")


class ErroPassageiro(ErroDublagem):
    """Um problema da hora (o Google lento, instável ou no limite por minuto; uma resposta fora do formato): o pedaço
    seguinte pode dar certo. O limite do dia, o teto e a chave recusada não são passageiros."""


def _tempo_esgotado(erro: Exception) -> bool:
    return type(erro).__name__ in ("APITimeoutError", "ReadTimeout", "WriteTimeout", "PoolTimeout", "TimeoutException")


def _limite_por_minuto(erro: Exception) -> bool:
    """O limite que acabou é o POR MINUTO (quotaId "...PerMinute..."): passa sozinho em instantes. Se o do DIA vier
    junto na mesma mensagem, vale o do dia (esperar segundos não adianta)."""
    return "perminute" in str(erro).lower().replace("_", "") and not _limite_do_dia(erro)


def limites_do_erro(erro: Exception) -> dict[str, int]:
    """O tamanho dos limites que o Google informou no erro 429: {"dia": 15, "minuto": 3} (cada violação traz o
    quotaId, "...PerDay..." ou "...PerMinute...", e o quotaValue)."""
    achados = {}
    for pedaco in str(erro).split("quotaId")[1:]:
        tipo = re.match(r"['\"]?\s*:\s*['\"]([^'\"]+)", pedaco)
        valor = re.search(r"quotaValue['\"]?\s*:\s*['\"]?(\d+)", pedaco)
        if tipo and valor:
            nome = tipo.group(1).lower()
            chave = "dia" if "perday" in nome else "minuto" if "perminute" in nome else None
            if chave and "request" in nome:                 # o limite de PEDIDOS (não o de tokens)
                achados[chave] = int(valor.group(1))
    return achados


def _com_tentativas(chamar, esperar=time.sleep, avisar=None, servico: str = "voz"):
    """Chama a API; no limite por minuto (429) ou instabilidade (5xx) espera e tenta de novo: 2, 4, 8, 16, 32 s ou
    o que o Google pedir (até 90 s), avisando no log. O limite do DIA não espera: avisa e para na hora. Sem resposta
    no tempo-limite, tenta de novo UMA vez (o Google às vezes perde um pedido; o 2º costuma vir na hora)."""
    esgotados = 0
    for tentativa in range(TENTATIVAS):
        try:
            return chamar()
        except ErroDublagem:
            raise
        except Exception as erro:
            if _camada_gratis(erro):                    # o Google disse qual é a camada da chave: confere o plano
                gastos.anotar_gemini_gratis()
            if limites := limites_do_erro(erro):         # o tamanho do limite: mostra quanto resta no dia
                gastos.anotar_limite_gemini(servico, limites.get("dia"), limites.get("minuto"),
                                            esgotou=_limite_do_dia(erro))
            if _tempo_esgotado(erro) and not esgotados:
                esgotados += 1
                if avisar:
                    avisar("Gemini: o Google não respondeu no tempo-limite; tentando de novo (uma vez)")
                continue
            if _limite(erro) and not _limite_do_dia(erro) and tentativa < TENTATIVAS - 1:
                espera = min(ESPERA_MAXIMA, max(2 ** (tentativa + 1), _espera_pedida(erro)))
                if avisar:
                    motivo = ("limite de pedidos por minuto" + (" da chave grátis" if _camada_gratis(erro) else "")
                              if _codigo(erro) == 429 or "RESOURCE_EXHAUSTED" in str(erro)
                              else "o Google está instável")
                    avisar(f"Gemini: {motivo}; tentando de novo em {espera:.0f} s ({tentativa + 2}ª de "
                           f"{TENTATIVAS} tentativas)")
                esperar(espera)
                continue
            if (_codigo(erro) == 429 or "RESOURCE_EXHAUSTED" in str(erro)) and not _limite_por_minuto(erro):
                gastos.marcar_cota("Gemini", "limite do dia")             # o limite do dia (na chave grátis)
            passageiro = (_tempo_esgotado(erro) or _limite_por_minuto(erro)
                          or (_limite(erro) and not (_codigo(erro) == 429 or "RESOURCE_EXHAUSTED" in str(erro))))
            raise (ErroPassageiro if passageiro else ErroDublagem)(_explicar(erro)) from erro


def texto_da_resposta(resposta) -> str:
    texto = getattr(resposta, "output_text", None)
    if texto:
        return texto
    try:
        return resposta.steps[-1].content[0].text
    except (AttributeError, IndexError, TypeError):
        return ""


def ler_json(texto: str) -> dict:
    """O JSON da resposta (tira ```json ... ``` e o que vier antes/depois)."""
    achado = re.search(r"\{.*\}", texto or "", re.S)
    if not achado:
        raise ErroPassageiro("o Gemini não respondeu no formato esperado")
    try:
        return json.loads(achado.group(0))
    except ValueError as erro:
        raise ErroPassageiro("o Gemini não respondeu no formato esperado") from erro


def _com_aviso_de_espera(chamar, avisar, o_que: str):
    """Chama e, enquanto o Google não responde, avisa no log a cada AVISO_ESPERA s (para não parecer travado)."""
    if not avisar:
        return chamar()
    resultado, feito = {}, threading.Event()

    def rodar():
        try:
            resultado["ok"] = chamar()
        except BaseException as erro:              # o erro volta para quem chamou (e para as tentativas)
            resultado["erro"] = erro
        finally:
            feito.set()
    threading.Thread(target=rodar, daemon=True).start()
    inicio = time.monotonic()
    while not feito.wait(AVISO_ESPERA):
        avisar(f"Gemini: esperando a resposta do Google há {max(1, round((time.monotonic() - inicio) / 60))} min "
               f"({o_que})")
    if "erro" in resultado:
        raise resultado["erro"]
    return resultado["ok"]


def perguntar_sobre_audio(cliente, pergunta: str, mp3: bytes, modelo: str = MODELO_OUVIR, esperar=time.sleep,
                          avisar=None) -> str:
    """Manda um trecho de áudio (mp3) e uma pergunta ao Gemini; devolve o texto da resposta."""
    entrada = [{"type": "text", "text": pergunta},
               {"type": "audio", "data": base64.b64encode(mp3).decode(), "mime_type": "audio/mp3"}]
    _conferir_teto()
    resposta = _com_tentativas(lambda: _com_aviso_de_espera(
        lambda: cliente.interactions.create(model=modelo, input=entrada), avisar, "ouvindo o original"), esperar, avisar,
        "escuta")
    gastos.contar_pedido_gemini("escuta")
    segundos = len(mp3) * 8 / (KBPS_OUVIR * 1000)
    gastos.registrar("Gemini (escuta)", segundos * TOKENS_POR_SEGUNDO * PRECO_OUVIR / 1_000_000 * fator_de_preco(cliente))
    return texto_da_resposta(resposta)


FRASE_DE_TESTE = ("Olá! Esta é a voz que vai dublar os seus filmes no Maestro. Que tal? Se não gostar, é só "
                  "escolher outra.")


def frase_de_teste(chave: str, voz: str, destino: Path, vozes_clonadas: dict | None = None, cliente=None,
                   esperar=time.sleep) -> Path:
    """Gera a FRASE_DE_TESTE com a voz escolhida (pronta ou clonada) num .wav: um pedido pequeno ao Gemini."""
    motor = MotorGemini(chave, voz, cliente=cliente, esperar=esperar, vozes_clonadas=vozes_clonadas)
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    motor.sintetizar([(FRASE_DE_TESTE, destino)])
    return destino


# ----------------------------------------------------------------- o motor
class MotorGemini:
    expressiva = True        # interpreta: o jeito de dizer muda com o contexto (dublagem.motor_expressivo)

    """Gera as falas com as vozes do Gemini, em blocos. Mesma interface do MotorPiper; cada pedido pode
    trazer a voz da fala: (texto, wav) usa a voz do motor, (texto, wav, voz) usa a voz dada, e
    (texto, wav, voz, tom) também diz COMO a fala é dita no original ("com raiva, gritando"; ver tom.py).
    vozes_clonadas: {"clone:Izael": "voicekey_..."} (ver voz_clonada.py); na hora do pedido, o nome vira a chave."""

    def __init__(self, chave: str, voz: str = VOZ_PADRAO, modelo: str = MODELO_PADRAO, estilo: str = ESTILO,
                 cliente=None, simultaneos: int = SIMULTANEOS, esperar=time.sleep, bloco: int = BLOCO,
                 vozes_clonadas: dict | None = None, avisar=None):
        self.clonadas = dict(vozes_clonadas or {})
        self.avisar, self._trava = avisar, threading.Lock()
        self.gasto_refeito = 0.0          # US$ (estimativa) do áudio dos blocos que tiveram de ser pedidos de novo
        if not self.conhece(voz):
            raise ErroDublagem(self._desconhecida([voz]))
        self.voz, self.modelo, self.estilo = voz, modelo or MODELO_PADRAO, estilo
        self.cliente = cliente or _cliente(chave, avisar)     # avisar: o Flex recusado aparece no log
        self.simultaneos, self._esperar, self.bloco = max(1, simultaneos), esperar, max(1, bloco)
        self.falas_geradas = self.pedidos = self.blocos_refeitos = 0
        self.AVISO_ESPERA = AVISO_ESPERA

    def _pedir(self, itens: list) -> tuple[array, int]:
        """Um pedido com as falas do bloco (diálogo, se houver 2 vozes). Devolve o áudio inteiro."""
        vozes = list(dict.fromkeys(v for _, _, v, _ in itens))
        if not all(self.conhece(v) for v in vozes):
            raise ErroDublagem(self._desconhecida([v for v in vozes if not self.conhece(v)]))
        dialogo = len(vozes) > 1
        falantes = {v: f"Pessoa {i + 1}" for i, v in enumerate(vozes)}
        entrada = []
        for k, (texto, _, voz, tom) in enumerate(itens):
            anotacao = {"type": "speech_metadata", "style": estilo_da_fala(self.estilo, tom)}
            if dialogo:
                anotacao["speaker"] = falantes[voz]
            entrada.append({"type": "text", "text": texto + (PAUSA if k < len(itens) - 1 else ""),
                            "annotations": [anotacao]})
        config = ([{"speaker": falantes[v], "voice": self.clonadas.get(v, v)} for v in vozes] if dialogo
                  else [{"voice": self.clonadas.get(vozes[0], vozes[0])}])

        def chamar():
            return self.cliente.interactions.create(model=self.modelo, input=entrada, response_format={"type": "audio"},
                                                    generation_config={"speech_config": config})
        _conferir_teto()
        resposta = _com_tentativas(chamar, self._esperar, self.avisar, "voz")
        self.pedidos += 1
        gastos.contar_pedido_gemini("voz")
        audio = getattr(resposta, "output_audio", None)
        if audio is None or not getattr(audio, "data", None):
            raise ErroDublagem("o Gemini não devolveu áudio")
        amostras, taxa = _ler_audio(audio.data)
        gastos.registrar("Gemini (voz)", custo_da_fala(len(amostras) / taxa) * fator_de_preco(self.cliente))
        return amostras, taxa

    def conhece(self, voz: str) -> bool:
        return voz in VOZES or voz in self.clonadas

    @staticmethod
    def _desconhecida(vozes: list[str]) -> str:
        clonadas = [v[len("clone:"):] for v in vozes if v.startswith("clone:")]
        if clonadas:
            return (f"a voz clonada \"{', '.join(clonadas)}\" não está neste PC (foi removida?); clone de novo em "
                    "Configurações > Dublagem ou escolha outra voz")
        return f"voz do Gemini desconhecida: {', '.join(vozes)}"

    def _falar_bloco(self, itens: list, parar=None) -> list[list]:
        """Pede o bloco e grava cada fala. Se o corte não bater, devolve as duas metades para pedir de novo (a voz e
        o ritmo continuam de conversa, não de falas soltas); quem chama as pede AO MESMO TEMPO que os outros blocos
        (antes eram pedidas uma depois da outra, e um bloco de 10 falas podia virar 19 pedidos em fila)."""
        if parar and parar():
            raise ErroDublagem("interrompido (botão Parar)")
        amostras, taxa = self._pedir(itens)
        cortes = separar_por_pausas(amostras, taxa, [max(1, len(t)) for t, _, _, _ in itens])
        if cortes is None and len(itens) > 1:
            with self._trava:
                self.blocos_refeitos += 1
                self.gasto_refeito += custo_da_fala(len(amostras) / taxa) * fator_de_preco(self.cliente)  # jogado fora
            meio = len(itens) // 2
            return [itens[:meio], itens[meio:]]
        for (ini, fim), (_, wav, _, _) in zip(cortes or [(0, len(amostras))], itens):
            _gravar_wav(amostras[ini:fim], taxa, Path(wav))
            with self._trava:
                self.falas_geradas += 1
        return []

    def sintetizar(self, pedidos: list, parar=None, ao_progresso=None) -> None:
        """pedidos: [(texto, .wav)], [(texto, .wav, voz)] ou [(texto, .wav, voz, tom)]. Em blocos, alguns ao mesmo tempo; para no Parar. Se um
        bloco falhar (limite do dia, sem internet), os que já terminaram ficam gravados."""
        itens = [(p[0], Path(p[1]), p[2] if len(p) > 2 and p[2] else self.voz, p[3] if len(p) > 3 else "")
                 for p in pedidos]
        grupos = blocos(itens, self.bloco)
        inicio, mostrado = self.falas_geradas, -1
        refeitos, gasto = self.blocos_refeitos, self.gasto_refeito
        # sem "with": no Parar (ou num erro), não espera os pedidos que ainda estão no Google
        flex = getattr(self.cliente, "flex", False) is True
        if flex and self.avisar and itens:              # antes dos pedidos: uma recusa do Flex vem depois deste aviso
            self.avisar("Gemini no modo Flex (metade do preço): cada pedido pode levar até ~15 min")
        grupo = ThreadPoolExecutor(max_workers=self.simultaneos)
        pendentes = {grupo.submit(self._falar_bloco, g, parar) for g in grupos}
        limite = "~15 min (modo Flex)" if flex else f"{TEMPO_LIMITE // 60} min"
        desde = time.monotonic()                    # a última resposta do Google
        proximo_aviso = desde + self.AVISO_ESPERA
        try:
            while pendentes:                        # confere o Parar enquanto espera o Google responder
                prontos, pendentes = wait(pendentes, timeout=0.5, return_when=FIRST_COMPLETED)
                agora = time.monotonic()
                if prontos:
                    desde, proximo_aviso = agora, agora + self.AVISO_ESPERA
                elif self.avisar and agora >= proximo_aviso:     # sem resposta há um tempo: diz que está esperando
                    self.avisar(f"Gemini: esperando a resposta do Google há {max(1, round((agora - desde) / 60))} "
                                f"min ({len(pendentes)} pedido(s) em andamento; cada um pode levar até {limite}; "
                                "o botão Parar interrompe e o que já ficou pronto é guardado)")
                    proximo_aviso += self.AVISO_ESPERA
                for futuro in prontos:
                    metades = futuro.result()       # o corte não bateu: as metades entram na fila
                    if metades and self.avisar:
                        self.avisar(f"Gemini: o corte de {sum(map(len, metades))} falas não bateu com as pausas; "
                                    "pedindo de novo em duas metades")
                    for metade in metades:
                        pendentes.add(grupo.submit(self._falar_bloco, metade, parar))
                feitas = self.falas_geradas - inicio      # a barra anda a cada fala pronta, não a cada bloco
                if ao_progresso and itens and feitas != mostrado:
                    mostrado = feitas
                    ao_progresso(min(1.0, feitas / len(itens)))
                if pendentes and parar and parar():
                    raise ErroDublagem("interrompido (botão Parar)")
        except BaseException:
            grupo.shutdown(wait=False, cancel_futures=True)
            raise
        grupo.shutdown(wait=False)
        if self.avisar and self.blocos_refeitos > refeitos:     # o que custou a mais (para ver se o corte melhorou)
            self.avisar(f"Gemini: {self.blocos_refeitos - refeitos} bloco(s) pedido(s) de novo em metades; custo a "
                        f"mais estimado: US$ {self.gasto_refeito - gasto:.3f}")
        if parar and parar():
            raise ErroDublagem("interrompido (botão Parar)")
