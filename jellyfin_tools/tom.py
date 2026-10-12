"""A EMOÇÃO de cada fala na dublagem com o Gemini: ele ouve o áudio ORIGINAL e diz, em poucas palavras, COMO cada
fala é dita ("animada, explicando", "com raiva, gritando", "sussurrando, com medo"). Esse tom vai junto no pedido
da voz, fala por fala: sem ele, a voz lê tudo no mesmo tom, como um locutor lendo uma lista.

    áudio original  ->  Gemini ouve  ->  {12: "com raiva, gritando", 13: "calmo"}  ->  a voz repete a emoção

Custa pouco: só OUVIR (áudio enviado em mp3 leve, ~US$ 0,12 por hora de filme na estimativa). Na amostra, só o
pedaço da amostra vai. O que já foi ouvido fica guardado (tons.json no progresso do filme): a amostra e depois o
filme inteiro não pagam duas vezes pelo mesmo trecho. Se a legenda mudar, a fala é ouvida de novo.
"""

from __future__ import annotations

import json
from pathlib import Path

from .dublagem import ErroDublagem, horarios
from .personagens import _carregar, _hms, audio_do_trecho
from .voz_gemini import PRECO_OUVIR, TOKENS_POR_SEGUNDO, ler_json, perguntar_sobre_audio

TRECHO = 15 * 60              # segundos de áudio por pedido, no máximo
FOLGA = 1.0                   # segundos a mais antes da 1ª e depois da última fala do pedaço
TOM_MAXIMO = 60               # letras do tom (é uma indicação curta, não uma descrição)

_PERGUNTA = """Você ouve um trecho do áudio ORIGINAL de um filme ou vídeo ({inicio} a {fim}). Abaixo estão as falas \
da legenda deste trecho: o número (id), o horário em segundos CONTADOS DO INÍCIO DESTE TRECHO e o texto já traduzido \
para o português (o áudio pode estar em outro idioma).

Para cada fala, diga COMO ela é dita no áudio, para um dublador repetir a mesma interpretação: a emoção e a \
intensidade em 2 a 6 palavras, em português (ex.: "animada, explicando com calma", "com raiva, gritando", "triste, \
quase chorando", "sussurrando, com medo", "irônico", "neutro"). Não repita o texto da fala: só o jeito de falar.

Responda SÓ com JSON, neste formato:
{{"falas": [{{"id": 12, "tom": "animada, explicando"}}]}}

Falas:
{falas}"""


def custo_estimado(segundos: float) -> float:
    """US$ para ouvir `segundos` de áudio (estimativa; confira o preço atual no AI Studio)."""
    return segundos * TOKENS_POR_SEGUNDO * PRECO_OUVIR / 1_000_000


def _limpar(tom) -> str:
    tom = " ".join(str(tom or "").replace('"', "").split()).strip(" .;")
    return tom[:TOM_MAXIMO]


def pedacos(falas: list, ids: list[int], tamanho: float = TRECHO) -> list[tuple[float, float, list[int]]]:
    """[(início, fim, números)] só em volta das falas pedidas (a amostra de 1 minuto manda ~1 minuto de áudio)."""
    grupos: dict[int, list[int]] = {}
    for k in ids:
        grupos.setdefault(int(horarios(falas[k][0].tempo)[0] // tamanho), []).append(k)
    saida = []
    for _, grupo in sorted(grupos.items()):
        inicio = max(0.0, min(horarios(falas[k][0].tempo)[0] for k in grupo) - FOLGA)
        fim = max(horarios(falas[k][0].tempo)[1] for k in grupo) + FOLGA
        saida.append((inicio, fim, grupo))
    return saida


def ouvir_tons(video: str | Path, falas: list, ids: list[int], cliente, ffmpeg: str,
               arquivo: str | Path | None = None, parar=None, ao_progresso=None, extrair=audio_do_trecho,
               tamanho: float = TRECHO, esperar=None, avisar=None) -> dict[int, str]:
    """{número da fala: tom} das falas `ids`. falas: [(Fala, texto)] (dublagem.falas_da_legenda). arquivo: onde
    guardar o que já foi ouvido ({número: [texto, tom]}); a fala com outro texto é ouvida de novo.
    Um pedaço que falhar (limite do dia, sem internet) para a escuta: fica o que já foi ouvido, avisar(texto) diz o
    que houve, e a próxima vez continua de onde parou. Se nada foi ouvido, o erro sobe."""
    video = Path(video)
    arquivo = Path(arquivo) if arquivo else None
    tons: dict[int, str] = {}
    for k, valor in _carregar(arquivo).items():
        try:
            k = int(k)
            if 0 <= k < len(falas) and isinstance(valor, list) and valor[0] == falas[k][1]:
                tons[k] = str(valor[1])
        except (ValueError, IndexError, TypeError):
            continue
    faltam = [k for k in ids if k not in tons]
    partes = pedacos(falas, faltam, tamanho)
    for n, (inicio, fim, grupo) in enumerate(partes):
        if parar and parar():
            raise ErroDublagem("interrompido (botão Parar)")
        linhas = "\n".join(f"{k} [{max(0.0, horarios(falas[k][0].tempo)[0] - inicio):.1f}s] {falas[k][1]}"
                           for k in grupo)
        pergunta = _PERGUNTA.format(inicio=_hms(inicio), fim=_hms(fim), falas=linhas)
        try:
            mp3 = extrair(ffmpeg, video, inicio, fim - inicio)
            kwargs = {"esperar": esperar} if esperar else {}
            dados = ler_json(perguntar_sobre_audio(cliente, pergunta, mp3, **kwargs))
        except Exception as erro:
            if (parar and parar()) or not any(tons.get(k) for k in ids):
                raise
            if avisar:
                avisar(f"o tom de parte das falas não foi ouvido ({str(erro)[:150]}): elas seguem sem a emoção da "
                       "cena")
            break
        validos = set(grupo)
        for item in dados.get("falas", []):
            try:
                k = int(item["id"])
            except (KeyError, TypeError, ValueError):
                continue
            if k in validos:
                tons[k] = _limpar(item.get("tom"))
        for k in grupo:
            tons.setdefault(k, "")                     # sem resposta para ela: não pergunta (nem paga) de novo
        if arquivo:
            arquivo.parent.mkdir(parents=True, exist_ok=True)
            arquivo.write_text(json.dumps({str(k): [falas[k][1], t] for k, t in sorted(tons.items())},
                                          ensure_ascii=False), encoding="utf-8")
        if ao_progresso:
            ao_progresso((n + 1) / len(partes))
    pedidos = set(ids)
    return {k: t for k, t in tons.items() if t and k in pedidos}

