"""Ouvir o ORIGINAL antes de dublar com o Gemini: para cada fala, COMO ela é dita (emoção, intensidade, ritmo) e se
quem fala é homem ou mulher; para cada pedaço, a CENA (quem são as pessoas, o clima). Isso vai junto no pedido da
voz, fala por fala, como as notas de um diretor de dublagem:

    áudio original  ->  Gemini ouve  ->  12: "com raiva, gritando, rápido" (mulher)  ->  voz feminina, com raiva

Sem isso, a voz lia tudo no mesmo tom, como um locutor lendo uma lista, e com a voz escolhida nas Configurações
mesmo quando quem fala é do outro gênero (a professora dublada com voz de homem).

Custa pouco: só OUVIR (áudio enviado em mp3 leve, ~US$ 0,12 por hora de filme na estimativa). Na amostra, só o
pedaço da amostra vai. O que já foi ouvido fica guardado (tons.json no progresso do filme): a amostra e depois o
filme inteiro não pagam duas vezes pelo mesmo trecho. Se a legenda mudar, a fala é ouvida de novo.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .dublagem import ErroDublagem, horarios
from .personagens import GENEROS, TRECHO, _carregar, _hms, audio_do_trecho, pedacos
from .voz_gemini import PRECO_OUVIR, TOKENS_POR_SEGUNDO, ler_json, perguntar_sobre_audio

TOM_MAXIMO = 80               # letras do tom de uma fala (uma indicação curta, não uma descrição)
CENA_MAXIMO = 240             # letras da descrição da cena

_PERGUNTA = """Você é um diretor de dublagem e ouve um trecho do áudio ORIGINAL de um filme ou vídeo ({inicio} a \
{fim}). Abaixo estão as falas da legenda deste trecho: o número (id), o horário em segundos CONTADOS DO INÍCIO DESTE \
TRECHO e o texto já traduzido para o português (o áudio pode estar em outro idioma).

1. cena: em 1 ou 2 frases, em português, o que está acontecendo e quem fala (ex.: "Uma senhora recebe uma jovem \
estrangeira em casa; a senhora é calorosa e teatral, a jovem é tímida e cansada da viagem").
2. Para cada fala:
   - tom: COMO ela é dita, para o dublador repetir a mesma interpretação: a emoção, a INTENSIDADE e o ritmo/volume, \
em 3 a 8 palavras, em português (ex.: "muito animada, quase cantando, rápido", "com raiva, gritando", "tímida, baixo \
e hesitante", "sussurrando, com medo", "irônica, devagar"). Não repita o texto: só o jeito de falar. Não suavize: \
se o original é exagerado ou teatral, diga.
   - genero: "m" se quem fala tem voz de homem, "f" se de mulher, "?" se não der para saber (criança, robô).

Responda SÓ com JSON, neste formato:
{{"cena": "...", "falas": [{{"id": 12, "tom": "animada, explicando", "genero": "f"}}]}}

Falas:
{falas}"""


@dataclass(frozen=True)
class Ouvida:
    """O que o Gemini ouviu de uma fala: o tom, o gênero de quem fala e a cena do pedaço."""
    tom: str = ""
    genero: str = "?"
    cena: str = ""

    def nota(self) -> str:
        """A nota de direção que vai no pedido da voz (vazia se não ouviu nada útil)."""
        partes = ([f"Cena: {self.cena.rstrip('.')}."] if self.cena else []) + \
            ([f"Nesta fala: {self.tom.rstrip('.')}."] if self.tom else [])
        return " ".join(partes)


def custo_estimado(segundos: float) -> float:
    """US$ para ouvir `segundos` de áudio (estimativa; confira o preço atual no AI Studio)."""
    return segundos * TOKENS_POR_SEGUNDO * PRECO_OUVIR / 1_000_000


def _limpar(texto, maximo: int) -> str:
    texto = " ".join(str(texto or "").replace('"', "").split()).strip(" .;")
    return texto[:maximo]


def _ler_guardado(arquivo: Path | None, falas: list) -> dict[int, Ouvida]:
    """{número: Ouvida} do que já foi ouvido com o MESMO texto ({número: [texto, tom, gênero, cena]})."""
    guardado = {}
    for k, valor in _carregar(arquivo).items():
        try:
            k = int(k)
            if (0 <= k < len(falas) and isinstance(valor, list) and len(valor) >= 4
                    and valor[0] == falas[k][1]):
                guardado[k] = Ouvida(str(valor[1]), str(valor[2]), str(valor[3]))
        except (ValueError, IndexError, TypeError):
            continue
    return guardado


def ouvir_falas(video: str | Path, falas: list, ids: list[int], cliente, ffmpeg: str,
                arquivo: str | Path | None = None, parar=None, ao_progresso=None, extrair=audio_do_trecho,
                tamanho: float = TRECHO, esperar=None, avisar=None) -> dict[int, Ouvida]:
    """{número da fala: Ouvida} das falas `ids`. falas: [(Fala, texto)] (dublagem.falas_da_legenda). arquivo: onde
    guardar o que já foi ouvido; a fala com outro texto é ouvida de novo.
    Um pedaço que falhar (limite do dia, sem internet) para a escuta: fica o que já foi ouvido, avisar(texto) diz o
    que houve, e a próxima vez continua de onde parou. Se nada foi ouvido, o erro sobe."""
    video = Path(video)
    arquivo = Path(arquivo) if arquivo else None
    ouvidas = _ler_guardado(arquivo, falas)
    faltam = [k for k in ids if k not in ouvidas]
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
            if (parar and parar()) or not any(ouvidas.get(k) for k in ids):
                raise
            if avisar:
                avisar(f"parte das falas não foi ouvida no original ({str(erro)[:150]}): elas seguem sem a emoção "
                       "da cena")
            break
        cena = _limpar(dados.get("cena"), CENA_MAXIMO)
        validos = set(grupo)
        for item in dados.get("falas", []):
            try:
                k = int(item["id"])
            except (KeyError, TypeError, ValueError):
                continue
            if k in validos:
                genero = str(item.get("genero", "?")).strip().lower()[:1]
                ouvidas[k] = Ouvida(_limpar(item.get("tom"), TOM_MAXIMO), genero if genero in GENEROS else "?", cena)
        for k in grupo:
            ouvidas.setdefault(k, Ouvida(cena=cena))     # sem resposta para ela: não pergunta (nem paga) de novo
        if arquivo:
            arquivo.parent.mkdir(parents=True, exist_ok=True)
            arquivo.write_text(json.dumps({str(k): [falas[k][1], o.tom, o.genero, o.cena]
                                           for k, o in sorted(ouvidas.items())}, ensure_ascii=False),
                               encoding="utf-8")
        if ao_progresso:
            ao_progresso((n + 1) / len(partes))
    pedidos = set(ids)
    return {k: o for k, o in ouvidas.items() if k in pedidos}
