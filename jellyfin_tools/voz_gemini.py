"""Voz PREMIUM da dublagem: o Gemini (Google AI Studio) lê as falas, no lugar do Piper.

    Piper  -> grátis, roda no PC, voz mais "robótica"
    Gemini -> pago por uso (chave do Google AI Studio), voz bem mais natural e com entonação

Só VOZES PRONTAS (genéricas) do Gemini: o Maestro nunca usa a "réplica de voz" (clonar a voz de alguém).
O motor tem a mesma cara do MotorPiper (sintetizar(pedidos)), então o resto da dublagem não muda: cada fala vira
um .wav (24 kHz, mono, 16 bits) e a trilha é montada igual.

A chave: aistudio.google.com > "Get API key". O Gemini cobra por token de áudio gerado; a camada grátis do AI Studio
tem limites baixos por minuto (o motor espera e tenta de novo quando o limite é atingido).
"""

from __future__ import annotations

import base64
import time
import wave
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .dublagem import ErroDublagem

MODELO_PADRAO = "gemini-3.8-flash-tts"
# vozes prontas do Gemini (há 30; estas combinam bem com dublagem). Ouça todas em aistudio.google.com/generate-speech
VOZES = {"Charon": "masculina, informativa", "Orus": "masculina, firme", "Puck": "masculina, animada",
         "Kore": "feminina, firme", "Aoede": "feminina, leve", "Leda": "feminina, jovem"}
VOZ_PADRAO = "Charon"
ESTILO = ("Dublagem brasileira de filme: fale em português do Brasil, natural e com a emoção da cena, no ritmo de "
          "uma conversa, sem soar como locutor lendo.")
TAXA = 24000                  # o Gemini devolve 24 kHz, mono, 16 bits
TOKENS_POR_SEGUNDO = 32       # áudio gerado vira ~32 tokens por segundo (para a ESTIMATIVA de custo)
PRECO_SAIDA = (6.0, 20.0)     # US$ por milhão de tokens de áudio: faixa dos modelos TTS do Gemini (confira o atual)
SIMULTANEOS = 4               # falas pedidas ao mesmo tempo
TENTATIVAS = 6


def estimar_custo(segundos_de_fala: float) -> tuple[float, float]:
    """(mínimo, máximo) em US$ para gerar essa quantidade de fala. Estimativa: o preço muda; confira no AI Studio."""
    tokens = segundos_de_fala * TOKENS_POR_SEGUNDO
    return tokens * PRECO_SAIDA[0] / 1_000_000, tokens * PRECO_SAIDA[1] / 1_000_000


def _explicar(erro: Exception) -> str:
    """O erro do SDK do Google em português (pelo código HTTP, quando houver)."""
    codigo = getattr(erro, "code", None) or getattr(erro, "status_code", None)
    texto = str(erro)
    if codigo in (400, 401, 403) and ("key" in texto.lower() or "API_KEY" in texto or codigo != 400):
        return "a chave do Google AI Studio foi recusada (confira em aistudio.google.com > Get API key)"
    if codigo == 404:
        return f"modelo de voz não encontrado ({MODELO_PADRAO}?)"
    if codigo == 429:
        return "limite de uso do Gemini atingido (a camada grátis tem limites baixos); tente mais tarde"
    if type(erro).__name__ in ("ConnectError", "ConnectTimeout", "ReadTimeout"):
        return "sem conexão com o Gemini"
    return f"{type(erro).__name__}: {texto}"[:300]


def _limite(erro: Exception) -> bool:
    codigo = getattr(erro, "code", None) or getattr(erro, "status_code", None)
    return codigo in (429, 500, 503) or "RESOURCE_EXHAUSTED" in str(erro)


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


def _para_wav(dados, destino: Path) -> None:
    """O áudio vem como WAV completo (começa com RIFF) ou PCM puro; às vezes em base64."""
    if isinstance(dados, str):
        dados = base64.b64decode(dados)
    elif not dados.startswith(b"RIFF"):
        try:
            decodificado = base64.b64decode(dados, validate=True)
            dados = decodificado if decodificado.startswith(b"RIFF") else dados
        except ValueError:
            pass
    if dados.startswith(b"RIFF"):
        destino.write_bytes(dados)
        return
    with wave.open(str(destino), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(TAXA)
        w.writeframes(dados)


class MotorGemini:
    """Gera cada fala com uma voz pronta do Gemini. Mesma interface do MotorPiper."""

    def __init__(self, chave: str, voz: str = VOZ_PADRAO, modelo: str = MODELO_PADRAO, estilo: str = ESTILO,
                 cliente=None, simultaneos: int = SIMULTANEOS, esperar=time.sleep):
        if voz not in VOZES:
            raise ErroDublagem(f"voz do Gemini desconhecida: {voz}")
        self.voz, self.modelo, self.estilo = voz, modelo or MODELO_PADRAO, estilo
        self.cliente = cliente or _cliente(chave)
        self.simultaneos, self._esperar = max(1, simultaneos), esperar
        self.falas_geradas = 0

    def _falar(self, texto: str, destino: Path) -> None:
        for tentativa in range(TENTATIVAS):
            try:
                resposta = self.cliente.interactions.create(
                    model=self.modelo,
                    input=[{"type": "text", "text": texto,
                            "annotations": [{"type": "speech_metadata", "style": self.estilo}]}],
                    response_format={"type": "audio"},
                    generation_config={"speech_config": [{"voice": self.voz}]})
                audio = getattr(resposta, "output_audio", None)
                if audio is None or not getattr(audio, "data", None):
                    raise ErroDublagem("o Gemini não devolveu áudio para uma fala")
                _para_wav(audio.data, destino)
                self.falas_geradas += 1
                return
            except ErroDublagem:
                raise
            except Exception as erro:
                if _limite(erro) and tentativa < TENTATIVAS - 1:
                    self._esperar(min(60, 2 ** (tentativa + 1)))       # 2, 4, 8, 16, 32 s
                    continue
                raise ErroDublagem(_explicar(erro)) from erro

    def sintetizar(self, pedidos: list[tuple[str, Path]], parar=None, ao_progresso=None) -> None:
        """pedidos: [(texto, .wav de destino)]. Algumas falas ao mesmo tempo; para no botão Parar."""
        feitos = 0
        with ThreadPoolExecutor(max_workers=self.simultaneos) as grupo:
            futuros = []
            for texto, wav in pedidos:
                futuros.append(grupo.submit(self._falar_se_continua, texto, Path(wav), parar))
            try:
                for futuro in as_completed(futuros):
                    futuro.result()
                    feitos += 1
                    if ao_progresso:
                        ao_progresso(feitos / len(pedidos))
            except BaseException:
                for f in futuros:
                    f.cancel()
                raise
        if parar and parar():
            raise ErroDublagem("interrompido (botão Parar)")

    def _falar_se_continua(self, texto: str, wav: Path, parar) -> None:
        if parar and parar():
            raise ErroDublagem("interrompido (botão Parar)")
        self._falar(texto, wav)
