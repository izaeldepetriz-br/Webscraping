"""O que os testes de voz têm em comum: as falas do guarda (a mesma cena para todos os motores) e a voz-alvo.

A voz-alvo dos testes de clonagem é uma voz PRONTA (genérica) do XTTS-v2 falando o texto de referência: nenhum
ator e nenhuma pessoa real sem autorização. Assim os três motores tentam imitar a mesma voz e dá para comparar.
"""

CENA_EN = ["Hey! You there! The gate is closed after sunset.",
           "If you want to cross the forest, talk to the elder first.",
           "And be careful. Something has been moving between the trees."]
CENA_PT = ["Ei, você! O portão fecha ao anoitecer.",
           "Quer cruzar a floresta? Fale antes com o ancião.",
           "E cuidado. Tem algo se mexendo nas árvores."]
FRASE_CATALOGO = "Olá! Esta é uma das vozes prontas, falando em português do Brasil."
TEXTO_REFERENCIA = ("Olá! Hoje o dia está bonito. Vou fazer um café e ver um filme. Você quer vir junto? "
                    "Vai ser ótimo!")
VOZ_ALVO = "Damien Black"           # voz pronta do XTTS-v2 usada como alvo (se não existir, a 1ª dos guardas)
GUARDAS = ["Damien Black", "Craig Gordon", "Gilberto Mathias", "Luis Moray"]
