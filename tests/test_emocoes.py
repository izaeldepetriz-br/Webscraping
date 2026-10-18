"""A emoção de cada fala pela nota de direção (medida no PC, dita pelo Gemini ou escrita em "Refazer esta fala")."""
from jellyfin_tools import emocoes as em
from jellyfin_tools.genero_local import TOM_GRITO, TOM_SUSSURRO


def test_emocao_da_nota():
    casos = {
        f"Nesta fala: {TOM_GRITO}.": "grito",
        f"Nesta fala: {TOM_SUSSURRO}.": "sussurro",
        "Cena: uma briga. Quem fala: o pai. Nesta fala: furioso, ríspido.": "brava",
        "Nesta fala: chorando, com a voz embargada. Ritmo: fale sem pressa.": "choro",
        "Nesta fala: gritando de medo.": "grito",                       # a 1ª da lista vale
        "Nesta fala: apavorada, em pânico.": "medo",
        "Nesta fala: rindo, feliz.": "alegre",
        "Nesta fala: triste, abatido.": "triste",
        "chorando": "choro",                                            # escrita à mão (Refazer esta fala)
        "Cena: todos gritando no estádio. Nesta fala: calmo.": em.NORMAL,   # a cena não é a fala
        "Cena: todos gritando no estádio.": em.NORMAL,
        "Nesta fala: adorando, dormindo.": em.NORMAL,                    # "dor" e "dormindo" não são emoção
        "Ritmo: cerca de 1,0 s no original.": em.NORMAL,
        "": em.NORMAL,
    }
    for nota, esperada in casos.items():
        assert em.emocao_da_nota(nota) == esperada, nota


def test_menu_das_emocoes():
    assert em.emocao_do_menu("Gritando") == "grito" and em.emocao_do_menu("Normal (voz nova)") == em.NORMAL
    assert em.nome_da_emocao("choro") == "Chorando" and em.nome_da_emocao(em.NORMAL) == "Normal"
    assert set(em.CHATTERBOX) == set(em.EMOCOES)                      # toda emoção tem a intensidade do Chatterbox
    assert all(em.PARECIDAS[p] in em.EMOCOES for p in em.PARECIDAS)
