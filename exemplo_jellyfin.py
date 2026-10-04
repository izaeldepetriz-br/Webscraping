"""Exemplo de como chamar o jellyfin_tools a partir do SEU arquivo principal.

Ajuste as pastas abaixo e rode:  python exemplo_jellyfin.py
Primeiro roda em modo SIMULAÇÃO; troque APLICAR para True quando o resultado estiver certo.
"""

import os
from pathlib import Path

from jellyfin_tools import (CatalogoEmCadeia, CatalogoLocal, CatalogoTMDB, ConfigSite,
                            ProvedorOpenSubtitles, ProvedorSiteHTML, organizar_e_legendar)

PASTA_BAGUNCADA = Path("C:/Users/Voce/Downloads")    # onde estão os vídeos com nomes bagunçados
PASTA_FILMES = Path("D:/Jellyfin/Filmes")              # a pasta 'Filmes' da biblioteca do Jellyfin
APLICAR = False                                        # False = só mostra o que faria


def montar_catalogo():
    catalogo = CatalogoLocal.padrao()                  # jellyfin_tools/catalogo_filmes.json
    if os.environ.get("TMDB_API_KEY"):                 # com chave, consulta também o TMDB
        catalogo = CatalogoEmCadeia(catalogo, CatalogoTMDB(os.environ["TMDB_API_KEY"]))
    return catalogo


def montar_provedores_de_legenda():
    provedores = []
    if os.environ.get("OPENSUBTITLES_API_KEY"):
        provedores.append(ProvedorOpenSubtitles(os.environ["OPENSUBTITLES_API_KEY"]))
    # Um site de busca simples que PERMITE robôs (confira o robots.txt e os termos de uso):
    # provedores.append(ProvedorSiteHTML(ConfigSite("https://exemplo.com/busca?q={consulta}")))
    return provedores


def main():
    # As 4 etapas de uma vez: limpar o nome, criar "Nome (Ano)/", levar legendas/imagens,
    # apagar o lixo do torrent e baixar a legenda pt-BR que estiver faltando.
    movimentos, legendas = organizar_e_legendar(
        PASTA_BAGUNCADA, PASTA_FILMES, montar_catalogo(), montar_provedores_de_legenda(),
        aplicar=APLICAR, limpar_lixo=True, limite_trailer_mb=100)
    for m in movimentos:
        print(m)
        for lixo in m.apagar or []:
            print("    apagar:", lixo.name)
    for r in legendas:
        print(r)


if __name__ == "__main__":
    main()
