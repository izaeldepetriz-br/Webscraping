"""jellyfin_tools: organiza filmes no padrão do Jellyfin e baixa legendas pt-BR.

Uso no seu arquivo principal:

    from pathlib import Path
    from jellyfin_tools import (CatalogoLocal, ProvedorSiteHTML, ConfigSite,
                                organizar_pasta, baixar_legendas_biblioteca)

    movimentos = organizar_pasta(Path("C:/Downloads"), Path("D:/Filmes"),
                                 CatalogoLocal.padrao(), aplicar=True)
    resultados = baixar_legendas_biblioteca(Path("D:/Filmes"), [meu_provedor])

Módulos:
  nomes       -> lê nomes bagunçados ("Matrix.1999.1080p...") e monta "Matrix (1999)"
  catalogo    -> confirma título/ano: catálogo local (JSON) ou API oficial do TMDB
  organizador -> move/renomeia para Filmes/Nome (Ano)/Nome (Ano).ext (com simulação e desfazer)
  legendas    -> busca e baixa legendas (site HTML via BeautifulSoup ou API OpenSubtitles)
  site_demo   -> site de legendas SIMULADO, local, para testes e demonstração
"""

from .catalogo import Catalogo, CatalogoEmCadeia, CatalogoLocal, CatalogoTMDB, ErroCatalogo, Filme
from .legendas import (CandidatoLegenda, ConfigSite, ErroLegenda, ProvedorOpenSubtitles,
                       ProvedorSiteHTML, ResultadoLegenda, baixar_legenda,
                       baixar_legendas_biblioteca)
from .nomes import NomeExtraido, extrair_titulo_e_ano, nome_jellyfin
from .organizador import Movimento, desfazer, organizar_pasta

__all__ = [
    "Catalogo", "CatalogoEmCadeia", "CatalogoLocal", "CatalogoTMDB", "ErroCatalogo", "Filme",
    "CandidatoLegenda", "ConfigSite", "ErroLegenda", "ProvedorOpenSubtitles", "ProvedorSiteHTML",
    "ResultadoLegenda", "baixar_legenda", "baixar_legendas_biblioteca",
    "NomeExtraido", "extrair_titulo_e_ano", "nome_jellyfin",
    "Movimento", "desfazer", "organizar_pasta",
]
