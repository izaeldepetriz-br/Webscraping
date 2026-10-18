"""As EMOÇÕES que o motor de vozes no PC sabe fazer, e como achar a de cada fala pela nota de direção.

O XTTS-v2 não tem "botão de emoção": ele copia o JEITO da gravação que recebe. Por isso a emoção vem de dois lugares:

1. Gravações de emoção de uma voz importada (Importar voz > Emoção da gravação): a mesma pessoa lendo brava,
   chorando, sussurrando... A fala com raiva vai com a gravação brava, e o timbre continua o da pessoa.
2. O Chatterbox (o 2º motor, opcional): tem a intensidade de emoção (exaggeration) e imita a voz do XTTS-v2. Faz as
   falas com emoção quando a voz não tem a gravação daquela emoção.

A emoção de cada fala vem da nota de direção ("Nesta fala: gritando..."): medida no PC pelo volume do original
(genero_local: grito e sussurro), dita pelo Gemini, ou escrita à mão em "Refazer esta fala".
"""

from __future__ import annotations

import re

NORMAL = "normal"
# chave: o nome no menu "Emoção da gravação" (e na lista das vozes importadas)
EMOCOES: dict[str, str] = {
    "brava": "Brava / com raiva",
    "grito": "Gritando",
    "triste": "Triste",
    "choro": "Chorando",
    "alegre": "Alegre / rindo",
    "medo": "Com medo",
    "sussurro": "Sussurrando",
}
# sem a gravação desta emoção, serve a da parecida
PARECIDAS = {"grito": "brava", "brava": "grito", "choro": "triste", "triste": "choro"}
# Chatterbox: (exaggeration, cfg_weight) de cada emoção, os do teste de emoções (8 falas, ouvidas pelo Whisper):
# mais exaggeration = mais intensidade; cfg menor = mais devagar e mais "atuado"
CHATTERBOX: dict[str, tuple[float, float]] = {
    "brava": (1.1, 0.4), "grito": (1.4, 0.3), "triste": (0.4, 0.3), "choro": (0.9, 0.3),
    "alegre": (1.0, 0.5), "medo": (0.8, 0.4), "sussurro": (0.25, 0.3),
}
# a força da interpretação (Configurações > Dublagem > "Força da emoção"): o Chatterbox mais intenso, as pausas do
# choro e o que atuacao.py faz com a voz (choro trêmulo, raiva rasgada...). "Desligada" = como na v2.20
FORCAS: dict[str, float] = {"Desligada": 0.0, "Leve": 0.45, "Média": 0.75, "Forte": 1.0}
FORCA_PADRAO = "Forte"
EXAGERO_MAX = 1.8               # acima disso o Chatterbox embola as palavras
# as palavras da nota de direção (em ordem: a 1ª que bater vale; "gritando de medo" é grito)
_PALAVRAS = [
    ("sussurro", r"sussurr\w*|cochich\w*|baixinho|murmur\w*|em voz baixa"),
    ("choro", r"chor\w*|solu[çc]\w*|prantos?|lacrimos\w*"),
    ("grito", r"grit\w*|berr\w*|urr\w*|aos berros|esbravej\w*"),
    ("brava", r"raiva|irritad\w*|brav[oa]s?|furios\w*|[óo]dio|indignad\w*|r[íi]spid\w*|agressiv\w*|amea[çc]\w*"),
    ("medo", r"medo|assustad\w*|apavor\w*|aterroriz\w*|nervos\w*|amedront\w*|p[âa]nico|desesper\w*"),
    ("alegre", r"alegr\w*|feliz\w*|rindo|risad\w*|gargalh\w*|animad\w*|empolgad\w*|euf[óo]ric\w*|entusiasm\w*"),
    ("triste", r"trist\w*|melanc[óo]lic\w*|abatid\w*|desanimad\w*|lament\w*|desolad\w*|magoad\w*"),
]
_PADROES = [(emocao, re.compile(rf"\b({padrao})\b")) for emocao, padrao in _PALAVRAS]


def emocao_da_nota(nota: str) -> str:
    """'Cena: briga. Nesta fala: gritando, com força.' -> 'grito'; sem emoção conhecida -> NORMAL. Olha só o "Nesta
    fala:" (a cena pode falar em grito sem que ESTA fala seja gritada) e não o ritmo."""
    nota = str(nota or "")
    if "Nesta fala:" in nota:
        nota = nota.split("Nesta fala:", 1)[1]
    elif nota.startswith(("Cena:", "Quem fala:")):
        return NORMAL
    nota = nota.split("Ritmo:", 1)[0].lower()
    return next((emocao for emocao, padrao in _PADROES if padrao.search(nota)), NORMAL)


def forca_do_menu(texto: str) -> float:
    """'Forte' -> 1.0; desconhecido -> a padrão."""
    return FORCAS.get(texto, FORCAS[FORCA_PADRAO])


def intensidade_chatterbox(emocao: str, forca: float = 0.0) -> tuple[float, float]:
    """(exaggeration, cfg) do Chatterbox: o da tabela na força 0 e até 35% mais intenso na "Forte" (no máximo
    EXAGERO_MAX)."""
    exaggeration, cfg = CHATTERBOX[emocao]
    return round(min(EXAGERO_MAX, exaggeration * (1 + 0.35 * max(0.0, forca))), 2), cfg


def nome_da_emocao(emocao: str) -> str:
    return EMOCOES.get(emocao, "Normal")


def emocao_do_menu(texto: str) -> str:
    """'Gritando' -> 'grito'; 'Normal (voz nova)' ou desconhecido -> NORMAL."""
    return next((chave for chave, nome in EMOCOES.items() if nome == texto), NORMAL)
