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
from .personagens import GENEROS, TRECHO, _carregar, _hms, audio_do_trecho, idade_de, pedacos
from .voz_gemini import PRECO_OUVIR, TOKENS_POR_SEGUNDO, ErroPassageiro, ler_json, perguntar_sobre_audio

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
   - quem: QUEM fala, como um perfil para o dublador, em 3 a 8 palavras (idade aproximada, jeito, personalidade; ex.: "senhora idosa, calorosa e teatral", "jovem estrangeira, tímida", "menino de 8 anos, travesso"). Use o mesmo perfil para a mesma pessoa.
   - idade: "crianca", "jovem", "adulto" ou "idoso", pela voz.

3. sons: os sons de voz SEM palavras que alguém faz neste trecho (bocejo, risada, suspiro, choro, grito sem palavras, \
tosse, espirro, gemido, respiração ofegante), com o início e o fim em segundos CONTADOS DO INÍCIO DESTE TRECHO. Não \
inclua falas com palavras, música nem efeitos sonoros. Se não houver, uma lista vazia.

Responda SÓ com JSON, neste formato:
{{"sons": [{{"inicio": 61.2, "fim": 63.0, "tipo": "bocejo"}}], "cena": "...", "falas": [{{"id": 12, "tom": "animada, explicando", "genero": "f", "idade": "adulto", "quem": "professora, paciente"}}]}}

Falas:
{falas}"""


_PERGUNTA_SONS = """Você ouve um trecho do áudio ORIGINAL de um filme ou vídeo ({inicio} a {fim}). Liste os sons de voz \
SEM palavras que alguém faz (bocejo, risada, suspiro, choro, grito sem palavras, tosse, espirro, gemido, respiração \
ofegante), com o início e o fim em segundos CONTADOS DO INÍCIO DESTE TRECHO. Não inclua falas com palavras, música \
nem efeitos sonoros.

Responda SÓ com JSON: {{"sons": [{{"inicio": 61.2, "fim": 63.0, "tipo": "bocejo"}}]}} (lista vazia se não houver)."""
SONS_MAXIMO = 8.0             # segundos: um "som sem fala" mais longo que isso é engano (ou é música)


def arquivo_sons(arquivo_tons: Path) -> Path:
    """Os sons sem fala ouvidos no original, ao lado do tons.json (dublagem.sons_guardados lê daqui)."""
    return Path(arquivo_tons).with_name("sons.json")


def _ler_sons(arquivo: Path | None) -> dict:
    dados = _carregar(arquivo)
    return {"ouvidos": [list(x) for x in dados.get("ouvidos", []) if isinstance(x, list) and len(x) == 2],
            "sons": [list(x) for x in dados.get("sons", []) if isinstance(x, list) and len(x) == 3]}


def _anotar_sons(arquivo: Path | None, inicio: float, fim: float, dados: dict) -> None:
    """Guarda os sons sem fala de um pedaço (em segundos do VÍDEO) e que o pedaço já foi ouvido para isso."""
    if not arquivo:
        return
    guardados = _ler_sons(arquivo)
    guardados["sons"] = [x for x in guardados["sons"] if not inicio <= x[0] < fim]   # ouvido de novo: troca
    for item in dados.get("sons", []) or []:
        try:
            a, b = float(item["inicio"]), float(item["fim"])
        except (KeyError, TypeError, ValueError):
            continue
        if 0 <= a < b and b - a <= SONS_MAXIMO:
            guardados["sons"].append([round(inicio + a, 2), round(inicio + b, 2), _limpar(item.get("tipo"), 30)])
    guardados["ouvidos"].append([round(inicio, 2), round(fim, 2)])
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    arquivo.write_text(json.dumps(guardados, ensure_ascii=False), encoding="utf-8")


def _coberta(falas: list, k: int, ouvidos: list) -> bool:
    """A fala k está dentro de um pedaço já ouvido para os sons sem fala."""
    inicio, fim = horarios(falas[k][0].tempo)
    return any(a <= inicio and fim <= b for a, b in ouvidos)


@dataclass(frozen=True)
class Ouvida:
    """O que o Gemini ouviu de uma fala: o tom, o gênero de quem fala e a cena do pedaço."""
    tom: str = ""
    genero: str = "?"
    cena: str = ""
    quem: str = ""
    idade: str = ""          # "crianca", "jovem", "adulto", "idoso" ou "" (escolhe a voz da idade)

    def nota(self) -> str:
        """A nota de direção que vai no pedido da voz (vazia se não ouviu nada útil): a cena, o perfil de quem fala
        (a voz "atua" o personagem) e como esta fala é dita."""
        partes = ([f"Cena: {self.cena.rstrip('.')}."] if self.cena else []) + \
            ([f"Quem fala: {self.quem.rstrip('.')}."] if self.quem else []) + \
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
                guardado[k] = Ouvida(str(valor[1]), str(valor[2]), str(valor[3]),
                                     str(valor[4]) if len(valor) > 4 else "", str(valor[5]) if len(valor) > 5 else "")
        except (ValueError, IndexError, TypeError):
            continue
    return guardado


def ouvir_falas(video: str | Path, falas: list, ids: list[int], cliente, ffmpeg: str,
                arquivo: str | Path | None = None, parar=None, ao_progresso=None, extrair=audio_do_trecho,
                tamanho: float = TRECHO, esperar=None, avisar=None) -> dict[int, Ouvida]:
    """{número da fala: Ouvida} das falas `ids`. falas: [(Fala, texto)] (dublagem.falas_da_legenda). arquivo: onde
    guardar o que já foi ouvido; a fala com outro texto é ouvida de novo.
    Um pedaço que falhar por um problema da hora (o Google lento ou no limite por minuto: ErroPassageiro) fica sem a
    emoção e os outros seguem; o limite do dia, o teto ou 2 pedaços seguidos falhando param a escuta. Fica o que já
    foi ouvido, avisar(texto) diz o que houve, e a próxima vez ouve só o que faltou. Se nada foi ouvido, o erro
    sobe."""
    video = Path(video)
    arquivo = Path(arquivo) if arquivo else None
    ouvidas = _ler_guardado(arquivo, falas)
    faltam = [k for k in ids if k not in ouvidas]
    partes = pedacos(falas, faltam, tamanho)
    erro_final, seguidos = None, 0
    for n, (inicio, fim, grupo) in enumerate(partes):
        if parar and parar():
            raise ErroDublagem("interrompido (botão Parar)")
        linhas = "\n".join(f"{k} [{max(0.0, horarios(falas[k][0].tempo)[0] - inicio):.1f}s] {falas[k][1]}"
                           for k in grupo)
        pergunta = _PERGUNTA.format(inicio=_hms(inicio), fim=_hms(fim), falas=linhas)
        try:
            mp3 = extrair(ffmpeg, video, inicio, fim - inicio)
            kwargs = ({"esperar": esperar} if esperar else {}) | {"avisar": avisar}
            dados = ler_json(perguntar_sobre_audio(cliente, pergunta, mp3, **kwargs))
        except Exception as erro:
            if parar and parar():
                raise
            erro_final, seguidos = erro, seguidos + 1
            if avisar:
                avisar(f"um pedaço do original não foi ouvido ({str(erro)[:150]}): {len(grupo)} fala(s) seguem sem a "
                       "emoção da cena")
            # passageiro (Google lento, limite por minuto): os outros pedaços seguem; 2 seguidos ou o limite do
            # dia / o teto: para (os outros também falhariam). A próxima vez ouve só o que faltou.
            if not isinstance(erro, ErroPassageiro) or seguidos >= 2:
                break
            continue
        seguidos = 0
        _anotar_sons(arquivo_sons(arquivo) if arquivo else None, inicio, fim, dados)
        cena = _limpar(dados.get("cena"), CENA_MAXIMO)
        validos = set(grupo)
        for item in dados.get("falas", []):
            try:
                k = int(item["id"])
            except (KeyError, TypeError, ValueError):
                continue
            if k in validos:
                genero = str(item.get("genero", "?")).strip().lower()[:1]
                ouvidas[k] = Ouvida(_limpar(item.get("tom"), TOM_MAXIMO), genero if genero in GENEROS else "?", cena,
                                    _limpar(item.get("quem"), TOM_MAXIMO), idade_de(item.get("idade")))
        for k in grupo:
            ouvidas.setdefault(k, Ouvida(cena=cena))     # sem resposta para ela: não pergunta (nem paga) de novo
        if arquivo:
            arquivo.parent.mkdir(parents=True, exist_ok=True)
            arquivo.write_text(json.dumps({str(k): [falas[k][1], o.tom, o.genero, o.cena, o.quem, o.idade]
                                           for k, o in sorted(ouvidas.items())}, ensure_ascii=False),
                               encoding="utf-8")
        if ao_progresso:
            ao_progresso((n + 1) / len(partes))
    if erro_final is not None and not any(ouvidas.get(k) for k in ids):
        raise erro_final                                # nada foi ouvido: o erro sobe (como antes)
    if arquivo:                                         # falas ouvidas antes (sem os sons): só os sons, pedido curto
        ouvidos = _ler_sons(arquivo_sons(arquivo))["ouvidos"]
        _ouvir_so_os_sons(video, falas, [k for k in ids if not _coberta(falas, k, ouvidos)],
                          cliente, ffmpeg, arquivo_sons(arquivo), parar, extrair, tamanho, esperar, avisar)
    pedidos = set(ids)
    return {k: o for k, o in ouvidas.items() if k in pedidos}


def _ouvir_so_os_sons(video, falas, ids, cliente, ffmpeg, arquivo, parar, extrair, tamanho, esperar, avisar) -> None:
    """Os sons sem fala (bocejo, risada...) dos pedaços cujas falas já tinham sido ouvidas antes desta versão: não
    ouve o tom de novo (o que já foi gerado continua valendo), só pergunta pelos sons."""
    for inicio, fim, _ in pedacos(falas, ids, tamanho):
        if parar and parar():
            raise ErroDublagem("interrompido (botão Parar)")
        try:
            mp3 = extrair(ffmpeg, video, inicio, fim - inicio)
            kwargs = ({"esperar": esperar} if esperar else {}) | {"avisar": avisar}
            dados = ler_json(perguntar_sobre_audio(cliente, _PERGUNTA_SONS.format(inicio=_hms(inicio), fim=_hms(fim)),
                                                   mp3, **kwargs))
        except Exception as erro:
            if parar and parar():
                raise
            if avisar:
                avisar(f"os sons sem fala (risos, bocejos) não foram ouvidos ({str(erro)[:150]})")
            return
        _anotar_sons(arquivo, inicio, fim, dados)
