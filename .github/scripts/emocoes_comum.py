"""Teste de emoções: as mesmas falas (raiva, ódio, choro...) no XTTS-v2 e no Chatterbox, com as mesmas 2 vozes.

O texto vai frase a frase e SEM o ponto final (como no Maestro: o XTTS-v2 lia "ponto" em voz alta).
O XTTS-v2 não tem controle de emoção: a interpretação vem só do texto (e do "!" e do "?"). O Chatterbox tem a
"exaggeration" (0 = contida, 0,5 = normal, 1+ = exagerada) e o "cfg" (mais baixo = mais pausado).
"""
import re

VOZES = {"f": "Narelle Moon", "m": "Gilberto Mathias"}     # vozes prontas do XTTS-v2 (gênero medido pelo tom)
REFERENCIA = "Olá! Hoje o dia está bonito. Vou fazer um café e ver um filme. Você quer vir junto? Vai ser ótimo!"
# (chave, emoção, texto, voz, exaggeration do Chatterbox, cfg do Chatterbox)
EMOCOES = [
    ("raiva", "Raiva", "Eu já disse para você sair daqui! Agora! Não quero te ver nunca mais!", "m", 1.1, 0.4),
    ("odio", "Ódio", "Eu nunca vou te perdoar pelo que você fez. Nunca. Você destruiu a minha família.", "m", 0.9, 0.35),
    ("choro", "Choro", "Por favor, não me deixa sozinha. Eu não aguento mais. Eu não aguento.", "f", 0.9, 0.3),
    ("medo", "Medo", "Tem alguém aí? Quem está aí? Por favor, responde.", "f", 0.8, 0.4),
    ("alegria", "Alegria", "A gente conseguiu! Eu não acredito, a gente conseguiu!", "f", 1.0, 0.5),
    ("tristeza", "Tristeza", "Ele foi embora e não volta mais. Eu nem consegui me despedir.", "m", 0.4, 0.3),
    ("sussurro", "Sussurro", "Fala baixo. Eles podem ouvir a gente. Fica quieto.", "f", 0.25, 0.3),
    ("grito", "Grito", "Corre! Corre! Ele está vindo! Sai da frente!", "m", 1.4, 0.3),
]


def frases_para_falar(texto: str) -> list[list]:
    """A mesma regra do Maestro (jellyfin_tools/voz_local.py): frase a frase, sem o ponto final, pausa no lugar."""
    texto = " ".join(texto.replace("...", "…").split())
    texto = re.sub(r"\s*[;:]\s*", ", ", texto)
    texto = re.sub(r"…(?=\s*\w)", ",", texto)
    frases = []
    for parte in re.split(r"(?<=[.!?…])\s+", texto):
        parte = parte.strip()
        frase = parte.rstrip(".…").rstrip(" ,")
        if re.search(r"\w", frase):
            frases.append([frase, 0.35 if parte.endswith(("?", "!")) else 0.30])
    if frases:
        frases[-1][1] = 0.0
    return frases or [[texto, 0.0]]
