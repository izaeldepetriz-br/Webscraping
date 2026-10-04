"""As 4 etapas de uma vez (é esta a função para chamar do seu arquivo principal):

  1. Limpeza e extração do título/ano     (nomes.py)
  2. Pasta "Nome (Ano)" + vídeo e legendas locais renomeados (organizador.py + extras.py)
  3. Imagens renomeadas (poster.jpg...) e lixo apagado        (extras.py)
  4. Legenda pt-BR baixada se o filme ainda não tiver         (legendas.py)

Exemplo:
    from pathlib import Path
    from jellyfin_tools import CatalogoLocal, organizar_e_legendar
    movimentos, legendas = organizar_e_legendar(Path("C:/Downloads"), Path("E:/Filmes"),
                                                CatalogoLocal.padrao(), provedores=[...], aplicar=True)
"""

from __future__ import annotations

from pathlib import Path

from .catalogo import Catalogo
from .extras import LIMITE_TRAILER_MB
from .legendas import IDIOMA_PADRAO, ResultadoLegenda, baixar_legenda, baixar_legenda_episodio, normalizar_idiomas
from .organizador import Movimento, organizar_pasta


def organizar_e_legendar(origem: str | Path, biblioteca: str | Path, catalogo: Catalogo | None = None,
                         provedores: list | None = None, aplicar: bool = False, modo: str = "filmes",
                         limpar_lixo: bool = True, limite_trailer_mb: float = LIMITE_TRAILER_MB,
                         idioma: str = IDIOMA_PADRAO, incluir_tmdbid: bool = False,
                         exigir_catalogo: bool = False, apagar_pasta_origem: bool = False,
                         ao_legendar=None, nomes_episodios: bool = False) -> tuple[list[Movimento], list[ResultadoLegenda]]:
    """Organiza `origem` dentro de `biblioteca` e, para cada vídeo movido SEM legenda local no
    idioma, procura uma nos `provedores`. Com aplicar=False só simula (nada é movido/baixado).
    `idioma` aceita vários: "pt-BR, en, es" (um arquivo de legenda por idioma).
    `ao_legendar(movimento, resultado)` é chamado a cada legenda (para mostrar o andamento)."""
    movimentos = organizar_pasta(origem, biblioteca, catalogo, aplicar=aplicar, modo=modo,
                                 limpar_lixo=limpar_lixo, limite_trailer_mb=limite_trailer_mb,
                                 incluir_tmdbid=incluir_tmdbid, exigir_catalogo=exigir_catalogo,
                                 apagar_pasta_origem=apagar_pasta_origem, nomes_episodios=nomes_episodios)
    resultados: list[ResultadoLegenda] = []
    if not aplicar or not provedores:
        return movimentos, resultados
    idiomas = normalizar_idiomas(idioma) or [IDIOMA_PADRAO]      # "pt-BR, en" -> um arquivo por idioma
    for m in movimentos:
        if m.status != "movido":
            continue
        # Etapa 4: baixar_legenda* já devolve 'ja_existe' se a legenda local (do torrent) veio junto.
        originais = [m.filme.titulo_original] if m.filme and m.filme.titulo_original else []
        for codigo in idiomas:
            if m.episodio:
                resultado = baixar_legenda_episodio(m.destino, provedores, idioma=codigo,
                                                    titulos_alternativos=originais)
            else:
                resultado = baixar_legenda(m.destino.parent, provedores, idioma=codigo,
                                           titulos_alternativos=originais)
            resultados.append(resultado)
            if ao_legendar:
                ao_legendar(m, resultado)
    return movimentos, resultados
    idiomas = normalizar_idiomas(idioma) or [IDIOMA_PADRAO]      # "pt-BR, en" -> um arquivo por idioma
    for m in (m for m in movimentos if m.status == "movido") if False else []:
        pass
    for m in movimentos:
        if m.status != "movido":
            continue
        # Etapa 4: baixar_legenda* já devolve 'ja_existe' se a legenda local (do torrent) veio junto.
        originais = [m.filme.titulo_original] if m.filme and m.filme.titulo_original else []
        if m.episodio:
            resultado = baixar_legenda_episodio(m.destino, provedores, idioma=idioma, titulos_alternativos=originais)
        else:
            resultado = baixar_legenda(m.destino.parent, provedores, idioma=idioma, titulos_alternativos=originais)
        resultados.append(resultado)
        if ao_legendar:
            ao_legendar(m, resultado)
    return movimentos, resultados
