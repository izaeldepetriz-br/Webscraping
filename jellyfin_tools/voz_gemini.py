"""Voz PREMIUM da dublagem: o Gemini (Google AI Studio) lê as falas, no lugar do Piper.

    Piper  -> grátis, roda no PC, voz mais "robótica"
    Gemini -> pago por uso (chave do Google AI Studio), voz bem mais natural e com entonação

Só VOZES PRONTAS (genéricas) do Gemini: o Maestro nunca usa a "réplica de voz" (clonar a voz de alguém).
O motor tem a mesma cara do MotorPiper (sintetizar(pedidos)): cada fala vira um .wav (24 kHz, mono, 16 bits).

BLOCOS (economiza pedidos): em vez de 1 pedido por fala (um filme tem ~1.200), o motor manda até BLOCO falas
seguidas num pedido só, com uma pausa longa entre elas, e depois corta o áudio nas pausas:

    "Oi. <long pause> Tudo bem? <long pause> Vamos."  ->  ▁▁███▁▁▁▁▁▁█████▁▁▁▁▁▁███▁▁  ->  3 arquivos .wav

O corte confere se cada pedaço tem um tamanho coerente com o texto; se não bater (o modelo juntou duas falas, por
exemplo), só aquele bloco é refeito fala por fala. Com vozes diferentes (uma por personagem), cada bloco tem no
máximo 2 vozes e vai como um DIÁLOGO (o Gemini aceita 2 falantes por pedido).

A chave: aistudio.google.com > "Get API key". O Gemini cobra por token de áudio gerado; a camada grátis tem limites
baixos por minuto e por dia (o motor espera e tenta de novo; o limite do dia faz parar e guardar o que já fez).
"""

from __future__ import annotations

import base64
import io
import json
import re
import time
import wave
from array import array
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

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
SIMULTANEOS = 4               # blocos pedidos ao mesmo tempo
TENTATIVAS = 6
BLOCO = 30                    # falas por pedido
LETRAS_POR_BLOCO = 2000
PAUSA = " <long pause>"       # marca de pausa do Gemini TTS entre uma fala e a próxima do bloco


def texto_da_voz(voz: str) -> str:
    """'Kore (feminina, firme)' para os menus."""
    return f"{voz} ({VOZES.get(voz, '')})" if voz in VOZES else voz


def estimar_custo(segundos_de_fala: float) -> tuple[float, float]:
    """(mínimo, máximo) em US$ para gerar essa quantidade de fala. Estimativa: o preço muda; confira no AI Studio."""
    tokens = segundos_de_fala * TOKENS_POR_SEGUNDO
    return tokens * PRECO_SAIDA[0] / 1_000_000, tokens * PRECO_SAIDA[1] / 1_000_000


def blocos(itens: list, bloco: int = BLOCO, letras: int = LETRAS_POR_BLOCO) -> list[list]:
    """Agrupa [(texto, wav, voz)] em blocos de falas SEGUIDAS: até `bloco` falas, `letras` letras e 2 vozes."""
    grupos, atual, vozes = [], [], set()
    for item in itens:
        texto, _, voz = item
        cabe = (len(atual) < bloco and sum(len(t) for t, _, _ in atual) + len(texto) <= letras
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


def separar_por_pausas(amostras: array, taxa: int, pesos: list[int]) -> list[tuple[int, int]] | None:
    """Corta o áudio de um bloco em len(pesos) pedaços nas PAUSAS mais longas. pesos: letras de cada fala (o
    pedaço de uma fala longa tem que ser mais longo). Devolve [(início, fim)] em amostras, ou None se não der para
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
    escolhidas = sorted(sorted(pausas, reverse=True)[:n - 1], key=lambda p: p[1])
    folga = int(FOLGA_CORTE / JANELA)
    limites = [primeiro] + [x for _, a, b in escolhidas for x in (a, b)] + [ultimo + 1]
    pedacos = [(max(0, limites[2 * i] - folga) * passo, min(len(nivel), limites[2 * i + 1] + folga) * passo)
               for i in range(n)]
    taxas = sorted((fim - ini) / max(1, p) for (ini, fim), p in zip(pedacos, pesos))
    mediana = taxas[len(taxas) // 2]
    if mediana <= 0 or taxas[0] < mediana / 3 or taxas[-1] > mediana * 3:
        return None                                    # um pedaço curto/longo demais para o texto: não confia
    return [(ini, min(fim, len(amostras))) for ini, fim in pedacos]


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
    if codigo == 429 or "RESOURCE_EXHAUSTED" in texto:
        return ("limite de uso do Gemini atingido (a camada grátis tem limites baixos por dia); o que já ficou pronto "
                "está guardado e a próxima dublagem continua de onde parou")
    if type(erro).__name__ in ("ConnectError", "ConnectTimeout", "ReadTimeout"):
        return "sem conexão com o Gemini"
    return f"{type(erro).__name__}: {texto}"[:300]


def _limite(erro: Exception) -> bool:
    return _codigo(erro) in (429, 500, 503) or "RESOURCE_EXHAUSTED" in str(erro)


def _cliente(chave: str):
    try:
        from google import genai
    except ImportError as erro:
        raise ErroDublagem("falta a biblioteca do Gemini (pip install google-genai)") from erro
    return genai.Client(api_key=chave)


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


def _com_tentativas(chamar, esperar=time.sleep):
    """Chama a API; no limite por minuto (429) ou instabilidade (5xx) espera 2, 4, 8, 16, 32 s e tenta de novo."""
    for tentativa in range(TENTATIVAS):
        try:
            return chamar()
        except ErroDublagem:
            raise
        except Exception as erro:
            if _limite(erro) and tentativa < TENTATIVAS - 1:
                esperar(min(60, 2 ** (tentativa + 1)))
                continue
            raise ErroDublagem(_explicar(erro)) from erro


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
        raise ErroDublagem("o Gemini não respondeu no formato esperado")
    try:
        return json.loads(achado.group(0))
    except ValueError as erro:
        raise ErroDublagem("o Gemini não respondeu no formato esperado") from erro


def perguntar_sobre_audio(cliente, pergunta: str, mp3: bytes, modelo: str = MODELO_OUVIR, esperar=time.sleep) -> str:
    """Manda um trecho de áudio (mp3) e uma pergunta ao Gemini; devolve o texto da resposta."""
    entrada = [{"type": "text", "text": pergunta},
               {"type": "audio", "data": base64.b64encode(mp3).decode(), "mime_type": "audio/mp3"}]
    return texto_da_resposta(_com_tentativas(lambda: cliente.interactions.create(model=modelo, input=entrada),
                                             esperar))


# ----------------------------------------------------------------- o motor
class MotorGemini:
    """Gera as falas com vozes prontas do Gemini, em blocos. Mesma interface do MotorPiper; cada pedido pode
    trazer a voz da fala: (texto, wav) usa a voz do motor, (texto, wav, voz) usa a voz dada."""

    def __init__(self, chave: str, voz: str = VOZ_PADRAO, modelo: str = MODELO_PADRAO, estilo: str = ESTILO,
                 cliente=None, simultaneos: int = SIMULTANEOS, esperar=time.sleep, bloco: int = BLOCO):
        if voz not in VOZES:
            raise ErroDublagem(f"voz do Gemini desconhecida: {voz}")
        self.voz, self.modelo, self.estilo = voz, modelo or MODELO_PADRAO, estilo
        self.cliente = cliente or _cliente(chave)
        self.simultaneos, self._esperar, self.bloco = max(1, simultaneos), esperar, max(1, bloco)
        self.falas_geradas = self.pedidos = self.blocos_refeitos = 0

    def _pedir(self, itens: list) -> tuple[array, int]:
        """Um pedido com as falas do bloco (diálogo, se houver 2 vozes). Devolve o áudio inteiro."""
        vozes = list(dict.fromkeys(v for _, _, v in itens))
        if any(v not in VOZES for v in vozes):
            raise ErroDublagem(f"voz do Gemini desconhecida: {', '.join(v for v in vozes if v not in VOZES)}")
        dialogo = len(vozes) > 1
        falantes = {v: f"Pessoa {i + 1}" for i, v in enumerate(vozes)}
        entrada = []
        for k, (texto, _, voz) in enumerate(itens):
            anotacao = {"type": "speech_metadata", "style": self.estilo}
            if dialogo:
                anotacao["speaker"] = falantes[voz]
            entrada.append({"type": "text", "text": texto + (PAUSA if k < len(itens) - 1 else ""),
                            "annotations": [anotacao]})
        config = ([{"speaker": falantes[v], "voice": v} for v in vozes] if dialogo else [{"voice": vozes[0]}])

        def chamar():
            return self.cliente.interactions.create(model=self.modelo, input=entrada, response_format={"type": "audio"},
                                                    generation_config={"speech_config": config})
        resposta = _com_tentativas(chamar, self._esperar)
        self.pedidos += 1
        audio = getattr(resposta, "output_audio", None)
        if audio is None or not getattr(audio, "data", None):
            raise ErroDublagem("o Gemini não devolveu áudio")
        return _ler_audio(audio.data)

    def _falar_bloco(self, itens: list, parar=None) -> None:
        if parar and parar():
            raise ErroDublagem("interrompido (botão Parar)")
        amostras, taxa = self._pedir(itens)
        cortes = separar_por_pausas(amostras, taxa, [max(1, len(t)) for t, _, _ in itens])
        if cortes is None and len(itens) > 1:          # o corte não bateu: refaz este bloco fala por fala
            self.blocos_refeitos += 1
            for item in itens:
                self._falar_bloco([item], parar)
            return
        for (ini, fim), (_, wav, _) in zip(cortes or [(0, len(amostras))], itens):
            _gravar_wav(amostras[ini:fim], taxa, Path(wav))
            self.falas_geradas += 1

    def sintetizar(self, pedidos: list, parar=None, ao_progresso=None) -> None:
        """pedidos: [(texto, .wav)] ou [(texto, .wav, voz)]. Em blocos, alguns ao mesmo tempo; para no Parar. Se um
        bloco falhar (limite do dia, sem internet), os que já terminaram ficam gravados."""
        itens = [(p[0], Path(p[1]), p[2] if len(p) > 2 and p[2] else self.voz) for p in pedidos]
        grupos = blocos(itens, self.bloco)
        feitos = 0
        with ThreadPoolExecutor(max_workers=self.simultaneos) as grupo:
            futuros = {grupo.submit(self._falar_bloco, g, parar): len(g) for g in grupos}
            try:
                for futuro in as_completed(futuros):
                    futuro.result()
                    feitos += futuros[futuro]
                    if ao_progresso:
                        ao_progresso(feitos / len(itens))
            except BaseException:
                for f in futuros:
                    f.cancel()
                raise
        if parar and parar():
            raise ErroDublagem("interrompido (botão Parar)")
