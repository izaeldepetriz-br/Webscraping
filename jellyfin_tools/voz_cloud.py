"""Voz da dublagem pelo Google Cloud Text-to-Speech: os TIPOS de voz Standard, WaveNet, Neural2 e Studio.

Não é o Gemini: é outro produto do Google (Cloud Console, não AI Studio). Cobra por CARACTERE de texto lido e tem uma
COTA GRÁTIS por mês para cada tipo. Para um filme (~50 mil caracteres de fala), a cota grátis do Neural2 dá para
cerca de 20 filmes por mês sem pagar nada. A voz é bem melhor que a do Piper, mas menos expressiva que a do Gemini
(não entende a emoção da cena).

A chave: console.cloud.google.com > ative a "Cloud Text-to-Speech API" > Credenciais > Criar chave de API (de
preferência restrita a essa API). O Google exige uma conta de faturamento ativa, mesmo para usar só a cota grátis.

    POST https://texttospeech.googleapis.com/v1/text:synthesize?key=CHAVE
        {"input": {"text": ...}, "voice": {"languageCode": "pt-BR", "name": "pt-BR-Neural2-B"},
         "audioConfig": {"audioEncoding": "LINEAR16", "sampleRateHertz": 24000}}
    -> {"audioContent": "<WAV em base64>"}

Preços e cotas abaixo são ESTIMATIVAS para o painel de gastos (o Google muda; confira em
cloud.google.com/text-to-speech/pricing). O que vale é a sua fatura.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from . import gastos
from .dublagem import ErroDublagem

URL = "https://texttospeech.googleapis.com/v1"
TAXA = 24000
SIMULTANEOS = 4
TENTATIVAS = 5
CARACTERES_POR_FALA = 40           # para estimar antes de dublar (uma fala de legenda tem ~30 a 50 letras)

# tipo: (no nome da voz, descrição, US$ por milhão de caracteres, cota grátis por mês em caracteres)
TIPOS = {
    "Neural2": ("Neural2", "natural, boa entonação (recomendada)", 16.0, 1_000_000),
    "WaveNet": ("Wavenet", "boa, um pouco menos natural que a Neural2", 16.0, 1_000_000),
    "Standard": ("Standard", "a mais barata; soa mais robótica", 4.0, 4_000_000),
    "Studio": ("Studio", "qualidade de estúdio, para narração; cota pequena e cara", 160.0, 100_000),
}
TIPO_PADRAO = "Neural2"
# vozes em português do Brasil que existem nos quatro tipos (a lista completa vem do "Validar")
LETRAS = {"Neural2": "ABC", "WaveNet": "ABC", "Standard": "ABC", "Studio": "BC"}
GENERO = {"A": "feminina", "B": "masculina", "C": "feminina", "D": "feminina", "E": "masculina"}


def nome_da_voz(tipo: str, letra: str) -> str:
    """('Neural2', 'B') -> 'pt-BR-Neural2-B' (o WaveNet se escreve 'Wavenet' no nome)."""
    return f"pt-BR-{TIPOS[tipo][0]}-{letra}"


def vozes_do_tipo(tipo: str) -> list[str]:
    return [nome_da_voz(tipo, l) for l in LETRAS.get(tipo, "ABC")]


def tipo_da_voz(voz: str) -> str:
    """'pt-BR-Neural2-B' -> 'Neural2'; 'pt-BR-Wavenet-A' -> 'WaveNet'."""
    for tipo, (no_nome, *_resto) in TIPOS.items():
        if f"-{no_nome}-" in voz:
            return tipo
    return TIPO_PADRAO


def texto_da_voz(voz: str) -> str:
    """'pt-BR-Neural2-B' -> 'pt-BR-Neural2-B (masculina)'."""
    letra = voz.rsplit("-", 1)[-1]
    return f"{voz} ({GENERO[letra]})" if letra in GENERO else voz


def custo_estimado(caracteres: int, tipo: str, ja_usados: int = 0) -> float:
    """Quanto custaria ler `caracteres` a mais neste mês (a parte dentro da cota grátis não custa)."""
    preco, cota = TIPOS[tipo][2], TIPOS[tipo][3]
    pago = max(0, ja_usados + caracteres - cota) - max(0, ja_usados - cota)
    return pago * preco / 1_000_000


def _explicar(codigo: int, texto: str) -> str:
    if codigo in (400, 401, 403) and ("API key" in texto or "API_KEY" in texto or codigo in (401, 403)):
        if "billing" in texto.lower():
            return ("o Google Cloud pede uma conta de faturamento ativa no projeto (mesmo para usar só a cota "
                    "grátis): console.cloud.google.com > Faturamento")
        if "has not been used" in texto or "disabled" in texto.lower():
            return ("a \"Cloud Text-to-Speech API\" não está ativada no projeto da chave (console.cloud.google.com "
                    "> APIs e serviços > Ativar)")
        return "a chave do Google Cloud foi recusada (confira em console.cloud.google.com > Credenciais)"
    if codigo == 429:
        return "limite de pedidos por minuto do Google Cloud atingido; tente de novo em instantes"
    return f"o Google Cloud TTS respondeu {codigo}: {texto[:200]}"


def _post(url, **k):
    import requests
    return requests.post(url, **k)


def _get(url, **k):
    import requests
    return requests.get(url, **k)


def listar_vozes(chave: str, obter=_get) -> list[str]:
    """As vozes pt-BR da conta (também serve para VALIDAR a chave: não gera áudio, não gasta)."""
    if not chave.strip():
        raise ErroDublagem("preencha a chave do Google Cloud (Text-to-Speech)")
    try:
        resposta = obter(f"{URL}/voices", params={"languageCode": "pt-BR", "key": chave.strip()}, timeout=20)
    except Exception as erro:
        raise ErroDublagem(f"sem conexão com o Google Cloud ({type(erro).__name__})") from erro
    if resposta.status_code != 200:
        raise ErroDublagem(_explicar(resposta.status_code, resposta.text))
    nomes = [v.get("name", "") for v in resposta.json().get("voices", [])]
    return sorted(n for n in nomes if n.startswith("pt-BR-") and any(f"-{t[0]}-" in n for t in TIPOS.values()))


class MotorCloudTTS:
    """Lê cada fala com a voz do Google Cloud. Mesma interface do MotorPiper/MotorGemini: sintetizar(pedidos), com
    pedidos [(texto, .wav)] ou [(texto, .wav, voz)]. Anota os caracteres do mês (cota grátis) no painel de gastos."""

    def __init__(self, chave: str, voz: str = "", postar=None, esperar=time.sleep, simultaneos: int = SIMULTANEOS):
        if not chave.strip():
            raise ErroDublagem("preencha a chave do Google Cloud (Text-to-Speech) em Configurações > Chaves de API")
        self.chave, self.voz = chave.strip(), voz or nome_da_voz(TIPO_PADRAO, "B")
        self._postar = postar or (lambda *a, **k: _post(*a, **k))    # buscado na hora (os testes trocam o _post)
        self._esperar, self.simultaneos = esperar, max(1, simultaneos)
        self.pedidos = self.caracteres = 0

    def _falar(self, texto: str, wav: Path, voz: str) -> None:
        from .voz_gemini import _gravar_wav, _ler_audio
        try:
            gastos.conferir()
        except gastos.TetoAtingido as erro:
            raise ErroDublagem(str(erro)) from erro
        corpo = {"input": {"text": texto}, "voice": {"languageCode": "pt-BR", "name": voz},
                 "audioConfig": {"audioEncoding": "LINEAR16", "sampleRateHertz": TAXA}}
        for tentativa in range(TENTATIVAS):
            try:
                resposta = self._postar(f"{URL}/text:synthesize", params={"key": self.chave}, json=corpo, timeout=60)
            except Exception as erro:
                if tentativa < TENTATIVAS - 1:
                    self._esperar(2 ** (tentativa + 1))
                    continue
                raise ErroDublagem(f"sem conexão com o Google Cloud ({type(erro).__name__})") from erro
            if resposta.status_code in (429, 500, 503) and tentativa < TENTATIVAS - 1:
                self._esperar(min(30, 2 ** (tentativa + 1)))
                continue
            if resposta.status_code != 200:
                raise ErroDublagem(_explicar(resposta.status_code, resposta.text))
            break
        dados = resposta.json().get("audioContent")
        if not dados:
            raise ErroDublagem("o Google Cloud não devolveu áudio")
        amostras, taxa = _ler_audio(dados)
        _gravar_wav(amostras, taxa, Path(wav))
        self.pedidos += 1
        self.caracteres += len(texto)
        gastos.registrar_caracteres(tipo_da_voz(voz), len(texto), TIPOS)

    def sintetizar(self, pedidos: list, parar=None, ao_progresso=None) -> None:
        itens = [(p[0], Path(p[1]), p[2] if len(p) > 2 and p[2] else self.voz) for p in pedidos]
        feitos = 0
        with ThreadPoolExecutor(max_workers=self.simultaneos) as grupo:
            futuros = []
            for texto, wav, voz in itens:
                if parar and parar():
                    break
                futuros.append(grupo.submit(self._falar, texto, wav, voz))
            try:
                for futuro in as_completed(futuros):
                    futuro.result()
                    feitos += 1
                    if ao_progresso and itens:
                        ao_progresso(feitos / len(itens))
            except BaseException:
                for f in futuros:
                    f.cancel()
                raise
        if parar and parar():
            raise ErroDublagem("interrompido (botão Parar)")
