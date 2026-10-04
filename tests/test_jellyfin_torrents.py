"""Os casos de teste do pedido: torrents com propaganda, imagens, legenda FORCED e legenda faltando."""
import pytest

from jellyfin_tools import CatalogoLocal, ConfigSite, ProvedorSiteHTML, desfazer, organizar_e_legendar
from jellyfin_tools.extras import eh_lixo, nome_da_legenda, parece_propaganda, tipo_de_arte
from jellyfin_tools.organizador import ultimo_log
from videoscraper.rede import ClienteHTTP

MB = 1024 * 1024
LIMITE = 1          # nos testes, "trailer" = vídeo < 1 MB (no uso real o padrão é 100 MB)
CREED = "Creed.II.2018.1080p.BluRay.6CH.x264.DUAL-WWW.BLUDV.TV-TioKennedy.mkv"
EXTRAS_CREED = ["BLUDV.TV.url", "Leia.txt", "Creed.II-backdrop.jpg", "Creed.II-poster.jpg", "Creed.II.FORCED.srt"]


def _video(caminho, tamanho):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, "wb") as f:
        f.truncate(tamanho)            # arquivo "grande" sem ocupar disco de verdade


def _arquivo(caminho, conteudo=b"x"):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_bytes(conteudo)


def _provedor(site):
    return [ProvedorSiteHTML(ConfigSite(site.base + "/busca?q={consulta}", nome="demo"), ClienteHTTP(espera=0))]


def _conteudo(pasta):
    return sorted(p.name for p in pasta.iterdir())


@pytest.mark.parametrize("subpasta", ["Creed.II.2018.1080p.BluRay-BLUDV", ""],
                         ids=["pasta-do-torrent", "solto-na-raiz"])
def test_exemplo_1_creed(tmp_path, site_legendas, subpasta):
    downloads, filmes = tmp_path / "Downloads", tmp_path / "Filmes"
    pasta = downloads / subpasta if subpasta else downloads
    _video(pasta / CREED, 2 * MB)
    for nome in EXTRAS_CREED:
        _arquivo(pasta / nome)
    _video(pasta / "BLUDV.TV-Trailer.mp4", 10_000)                 # trailer de propaganda

    movimentos, legendas = organizar_e_legendar(downloads, filmes, CatalogoLocal.padrao(), _provedor(site_legendas),
                                                aplicar=True, limite_trailer_mb=LIMITE)
    [m] = movimentos                                                # o trailer NÃO é tratado como filme
    assert m.status == "movido"
    assert _conteudo(filmes / "Creed II (2018)") == sorted(
        ["Creed II (2018).mkv", "Creed II (2018).pt-BR.forced.srt", "poster.jpg", "backdrop.jpg"])
    assert legendas[0].status == "nao_encontrada"                   # forced não é legenda completa: buscou
    # .url, .txt e trailer apagados; na subpasta, ela some porque esvaziou
    if subpasta:
        assert not pasta.exists()
    else:
        assert _conteudo(downloads) == []


def test_exemplo_2_velhos_bandidos_busca_legenda(tmp_path, site_legendas):
    downloads, filmes = tmp_path / "Downloads", tmp_path / "Filmes"
    _video(downloads / "Velhos.Bandidos.2026.1080p.WEB-DL.NACIONAL.5.1.mkv", 2 * MB)
    movimentos, legendas = organizar_e_legendar(downloads, filmes, CatalogoLocal.padrao(), _provedor(site_legendas),
                                                aplicar=True, limite_trailer_mb=LIMITE)
    pasta = filmes / "Velhos Bandidos (2026)"
    assert _conteudo(pasta) == ["Velhos Bandidos (2026).mkv", "Velhos Bandidos (2026).pt-BR.srt"]
    assert legendas[0].status == "baixada"
    assert "Velhos Bandidos" in (pasta / "Velhos Bandidos (2026).pt-BR.srt").read_text(encoding="utf-8")


def test_legenda_local_completa_evita_o_scraper(tmp_path, site_legendas):
    downloads, filmes = tmp_path / "Downloads", tmp_path / "Filmes"
    _video(downloads / "Matrix.1999" / "Matrix.1999.1080p.mkv", 2 * MB)
    _arquivo(downloads / "Matrix.1999" / "legenda.srt", b"1\n00:00 --> 00:01\nminha\n")
    _, legendas = organizar_e_legendar(downloads, filmes, CatalogoLocal.padrao(), _provedor(site_legendas),
                                       aplicar=True, limite_trailer_mb=LIMITE)
    assert legendas[0].status == "ja_existe"
    assert (filmes / "Matrix (1999)" / "Matrix (1999).pt-BR.srt").read_bytes().endswith(b"minha\n")


def test_previa_nao_apaga_nada_e_mostra_resumo(tmp_path):
    downloads = tmp_path / "Downloads" / "Creed"
    _video(downloads / CREED, 2 * MB)
    for nome in EXTRAS_CREED:
        _arquivo(downloads / nome)
    [m], _ = organizar_e_legendar(tmp_path / "Downloads", tmp_path / "Filmes", CatalogoLocal.padrao(),
                                  limite_trailer_mb=LIMITE)
    assert m.status == "simulado" and len(m.apagar) == 2
    assert m.resumo_extras == "+1 legenda(s), 2 imagem(ns); apagar 2"
    assert _conteudo(downloads) == sorted([CREED] + EXTRAS_CREED)      # nada mexido


def test_travas_de_seguranca(tmp_path):
    downloads, filmes = tmp_path / "Downloads", tmp_path / "Filmes"
    _video(downloads / "Matrix.1999.mkv", 2 * MB)
    _arquivo(downloads / "minhas_notas.txt")                        # da pessoa, na raiz: fica
    _arquivo(downloads / "atalho banco.url")                        # sem cara de propaganda: fica
    _video(downloads / "Curta.Metragem.1965.mp4", 10_000)           # vídeo pequeno legítimo na raiz: fica
    _video(downloads / "pasta-do-curta" / "Curta.Antigo.1930.mp4", 10_000)   # único vídeo da pasta: fica
    _arquivo(downloads / "pasta-do-curta" / "Leia.txt")
    _video(tmp_path / "Series" / "Dark.S01" / "Dark.S01E01.mkv", 2 * MB)
    _video(tmp_path / "Series" / "Dark.S01" / "Dark.S01E02.mkv", 10_000)     # episódio curto: nunca é lixo

    movimentos, _ = organizar_e_legendar(downloads, filmes, CatalogoLocal.padrao(), aplicar=True,
                                         limite_trailer_mb=LIMITE)
    assert {"minhas_notas.txt", "atalho banco.url"} <= set(_conteudo(downloads))
    assert (filmes / "Curta Metragem (1965)" / "Curta Metragem (1965).mp4").exists()   # virou filme
    assert (filmes / "Curta Antigo (1930)" / "Curta Antigo (1930).mp4").exists()
    assert not (downloads / "pasta-do-curta").exists()               # Leia.txt da pasta do filme: apagado

    series_mov, _ = organizar_e_legendar(tmp_path / "Series", tmp_path / "Bib", CatalogoLocal.padrao(),
                                         aplicar=True, modo="series", limite_trailer_mb=LIMITE)
    assert sorted(m.status for m in series_mov) == ["movido", "movido"]


def test_sem_limpeza_e_desfazer_avisa_o_que_foi_apagado(tmp_path):
    downloads, filmes = tmp_path / "Downloads", tmp_path / "Filmes"
    _video(downloads / "Creed" / CREED, 2 * MB)
    _arquivo(downloads / "Creed" / "Leia.txt")
    organizar_e_legendar(downloads, filmes, aplicar=True, limpar_lixo=False, limite_trailer_mb=LIMITE)
    assert (downloads / "Creed" / "Leia.txt").exists()               # limpar_lixo=False: nada apagado
    desfazer(ultimo_log(filmes))

    organizar_e_legendar(downloads, filmes, aplicar=True, limite_trailer_mb=LIMITE)
    mensagens = desfazer(ultimo_log(filmes))
    assert (downloads / "Creed" / CREED).exists()
    assert any("apagados e não voltam" in m for m in mensagens)


@pytest.mark.parametrize("nome, esperado", [
    ("Creed.II.FORCED.srt", "Filme (2018).pt-BR.forced.srt"),
    ("Creed.II.srt", "Filme (2018).pt-BR.srt"),
    ("Creed.II.ENG.srt", "Filme (2018).en.srt"),
    ("Creed.II.English.Forced.srt", "Filme (2018).en.forced.srt"),
    ("Creed.II.pt-BR.srt", "Filme (2018).pt-BR.srt"),
    ("Creed.II.Espanol.ass", "Filme (2018).es.ass"),
])
def test_nome_da_legenda(nome, esperado, tmp_path):
    assert nome_da_legenda(tmp_path / nome, "Filme (2018)") == esperado


def test_artes_e_propaganda(tmp_path):
    assert [tipo_de_arte(tmp_path / n) for n in ("Creed.II-poster.jpg", "poster.jpg", "x-backdrop.jpeg",
            "Creed-landscape.jpg", "Creed-logo.png", "cena01.jpg", "poster.txt")] == \
        ["poster", "poster", "backdrop", "landscape", "logo", None, None]
    assert parece_propaganda(tmp_path / "BLUDV.TV.url") and parece_propaganda(tmp_path / "Leia.txt")
    assert not parece_propaganda(tmp_path / "minhas_notas.txt")
    (tmp_path / "sub").mkdir()
    assert eh_lixo(tmp_path / "sub" / "qualquer.txt", tmp_path)        # dentro da pasta do torrent
    assert not eh_lixo(tmp_path / "qualquer.txt", tmp_path)            # na raiz, sem cara de propaganda


# ----------------------------------------------------------------- apagar a pasta do torrent
def test_apagar_pasta_de_origem_com_sobras(tmp_path):
    downloads, filmes = tmp_path / "Downloads", tmp_path / "Filmes"
    torrent = downloads / "Creed.II.2018.1080p-BLUDV"
    _video(torrent / CREED, 2 * MB)
    _video(torrent / "Sample" / "creed-sample.mkv", 10_000)                 # amostra: pode sumir junto
    _arquivo(torrent / "Screens" / "cena01.png")                            # sobra qualquer
    _arquivo(torrent / "release.nfo", b"RELEASE INFO")
    previa, _ = organizar_e_legendar(downloads, filmes, CatalogoLocal.padrao(), limite_trailer_mb=LIMITE,
                                     apagar_pasta_origem=True)
    [m] = [x for x in previa if x.status == "simulado"]
    assert m.pasta_apagar == torrent and "apagar a pasta" in m.resumo_extras
    assert torrent.exists()                                                 # prévia não apaga

    organizar_e_legendar(downloads, filmes, CatalogoLocal.padrao(), aplicar=True, limite_trailer_mb=LIMITE,
                         apagar_pasta_origem=True)
    assert not torrent.exists()
    assert (filmes / "Creed II (2018)" / "Creed II (2018).mkv").exists()
    mensagens = desfazer(ultimo_log(filmes))                               # o filme volta; as sobras não
    assert (torrent / CREED).exists() and not (torrent / "Screens").exists()
    assert any("pasta(s) de origem foram apagadas" in t for t in mensagens)


def test_pasta_nao_e_apagada_se_sobrar_video_ou_for_a_raiz(tmp_path):
    downloads, filmes = tmp_path / "Downloads", tmp_path / "Filmes"
    pack = downloads / "Pack.de.Filmes"
    _video(pack / "Matrix.1999.mkv", 2 * MB)
    _video(pack / "video_sem_ano.mp4", 2 * MB)                              # não identificado: fica
    _video(downloads / "Cidade.de.Deus.2002.mkv", 2 * MB)                    # solto na raiz
    _arquivo(downloads / "minhas_notas.txt")
    movs, _ = organizar_e_legendar(downloads, filmes, CatalogoLocal.padrao(), aplicar=True,
                                   limite_trailer_mb=LIMITE, apagar_pasta_origem=True)
    assert all(m.pasta_apagar is None for m in movs)
    assert (pack / "video_sem_ano.mp4").exists()                             # nada que não foi movido some
    assert (downloads / "minhas_notas.txt").exists()                         # a raiz nunca é apagada


def test_mesma_pasta_nos_dois_campos_nao_apaga_a_pasta_do_filme(tmp_path):
    biblioteca = tmp_path / "Filmes"
    _video(biblioteca / "Matrix (1999)" / "Matrix.1999.1080p.mkv", 2 * MB)   # só renomeia lá dentro
    _arquivo(biblioteca / "Matrix (1999)" / "poster.jpg")
    _video(biblioteca / "Creed.II.2018-BLUDV" / CREED, 2 * MB)
    _arquivo(biblioteca / "Creed.II.2018-BLUDV" / "release.nfo")
    organizar_e_legendar(biblioteca, biblioteca, CatalogoLocal.padrao(), aplicar=True, limite_trailer_mb=LIMITE,
                         apagar_pasta_origem=True)
    assert (biblioteca / "Matrix (1999)" / "Matrix (1999).mkv").exists()
    assert (biblioteca / "Matrix (1999)" / "poster.jpg").exists()            # a pasta do filme ficou
    assert not (biblioteca / "Creed.II.2018-BLUDV").exists()                 # a do torrent saiu


def test_midia_solta_ganha_pasta_propria(tmp_path):
    """Só o arquivo de vídeo, sem pasta: ganha a pasta 'Nome (Ano)' (inclusive já com nome certo)."""
    biblioteca = tmp_path / "Filmes"
    _video(biblioteca / "Matrix (1999).mkv", 2 * MB)                         # nome certo, mas solto
    _video(biblioteca / "Cidade.de.Deus.2002.1080p.mkv", 2 * MB)             # nome bagunçado e solto
    movs, _ = organizar_e_legendar(biblioteca, biblioteca, CatalogoLocal.padrao(), aplicar=True,
                                   limite_trailer_mb=LIMITE)
    assert sorted(m.status for m in movs) == ["movido", "movido"]
    assert (biblioteca / "Matrix (1999)" / "Matrix (1999).mkv").exists()
    assert (biblioteca / "Cidade de Deus (2002)" / "Cidade de Deus (2002).mkv").exists()


# ------------------------------------------------------------------ séries de torrent (caso "The Office")
TEMPORADA = "Vida de Escritório (The Office) {ano} - {t}ª Temporada Completa Acesse o ORIGINAL WWW.BLUDV.TV"


def _the_office(raiz, temporadas=(1, 2), episodios=(1, 2, 3)):
    """Como o torrent chega: uma pasta por temporada com episódios, a imagem de cada episódio,
    a propaganda BLUDV.TV.mp4 (pequena) e o pôster da propaganda."""
    pastas = []
    for t in temporadas:
        pasta = raiz / TEMPORADA.format(ano=2004 + t, t=t)
        for e in episodios:
            base = f"The.Office.S{t:02d}E{e:02d}.720p.BluRay.x264.DUAL-WWW.BLUDV.TV"
            _video(pasta / f"{base}.mkv", 3 * MB)
            _arquivo(pasta / f"{base}-poster.jpg")
            _arquivo(pasta / f"{base}.srt")
        _video(pasta / "BLUDV.TV.mp4", MB // 2)
        _arquivo(pasta / "BLUDV.TV-poster.jpg")
        _arquivo(pasta / "Leia.txt")
        pastas.append(pasta)
    return pastas


def test_serie_de_torrent_apaga_propaganda_pastas_e_leva_as_imagens(tmp_path):
    from jellyfin_tools import organizar_pasta
    raiz = tmp_path / "Series" / "The Office"                    # origem e biblioteca: a mesma pasta
    pastas = _the_office(raiz)
    previa = organizar_pasta(raiz, raiz, CatalogoLocal.padrao(), modo="series", limite_trailer_mb=LIMITE,
                             apagar_pasta_origem=True)
    assert {m.status for m in previa} == {"simulado"}           # BLUDV.TV.mp4 não é mais "não identificado"
    assert sum(1 for m in previa if m.pasta_apagar) == 2
    assert all(p.exists() for p in pastas)                      # prévia não apaga nada

    organizar_pasta(raiz, raiz, CatalogoLocal.padrao(), modo="series", limite_trailer_mb=LIMITE,
                    apagar_pasta_origem=True, aplicar=True)
    assert not any(p.exists() for p in pastas)                  # pastas do torrent apagadas
    season = raiz / "The Office (2005)" / "Season 01"
    assert sorted(p.name for p in season.iterdir()) == [
        "The Office S01E01-thumb.jpg", "The Office S01E01.mkv", "The Office S01E01.pt-BR.srt",
        "The Office S01E02-thumb.jpg", "The Office S01E02.mkv", "The Office S01E02.pt-BR.srt",
        "The Office S01E03-thumb.jpg", "The Office S01E03.mkv", "The Office S01E03.pt-BR.srt"]
    assert sorted(p.name for p in raiz.iterdir()) == [".organizador", "The Office (2005)"]


def test_sobras_de_uma_organizacao_anterior_sao_limpas(tmp_path):
    """O que aconteceu de verdade: uma versão anterior moveu os episódios e deixou para trás
    BLUDV.TV.mp4, as imagens dos episódios e as pastas das temporadas."""
    import json
    from jellyfin_tools import organizar_pasta
    from jellyfin_tools.organizador import PASTA_LOGS
    raiz = tmp_path / "Series" / "The Office"
    pastas = _the_office(raiz, temporadas=(1, 2), episodios=(1, 2))
    itens = []
    for pasta in pastas:                                         # "move" como a versão antiga fazia
        for video in sorted(pasta.glob("*.mkv")):
            t, e = int(video.name[12:14]), int(video.name[15:17])
            novo = raiz / "The Office (2005)" / f"Season {t:02d}" / f"The Office S{t:02d}E{e:02d} - Ep {e}.mkv"
            novo.parent.mkdir(parents=True, exist_ok=True)
            video.rename(novo)
            itens.append({"de": str(video), "para": str(novo)})
        (pasta / "Leia.txt").unlink()
    (raiz / PASTA_LOGS).mkdir()
    (raiz / PASTA_LOGS / "log-20261004-121747-947836.json").write_text(json.dumps(
        {"raiz": str(raiz), "itens": itens, "apagados": [], "pastas_apagadas": []}), encoding="utf-8")

    previa = organizar_pasta(raiz, raiz, CatalogoLocal.padrao(), modo="series", limite_trailer_mb=LIMITE,
                             apagar_pasta_origem=True)
    limpezas = [m for m in previa if m.status == "limpeza"]
    assert sorted(m.origem for m in limpezas) == sorted(pastas)
    assert not any(m.status == "nao_identificado" for m in previa)      # BLUDV.TV.mp4 não aparece como pendência
    s01 = next(m for m in limpezas if "1ª" in m.origem.name)
    assert sorted(n.name for _, n in s01.acompanhantes) == ["The Office S01E01 - Ep 1-thumb.jpg",
                                                            "The Office S01E02 - Ep 2-thumb.jpg"]
    assert [a.name for a in s01.apagar] == ["BLUDV.TV.mp4"]

    feitos = organizar_pasta(raiz, raiz, CatalogoLocal.padrao(), modo="series", limite_trailer_mb=LIMITE,
                             apagar_pasta_origem=True, aplicar=True)
    assert {m.status for m in feitos if m.pasta_apagar} == {"pasta_apagada"}
    assert not any(p.exists() for p in pastas)
    s01_pasta = raiz / "The Office (2005)" / "Season 01"
    assert (s01_pasta / "The Office S01E01 - Ep 1-thumb.jpg").is_file()
    # sem o log anterior, nada mais a limpar; a nova organização tem o próprio log (desfaz as imagens)
    assert not [m for m in organizar_pasta(raiz, raiz, CatalogoLocal.padrao(), modo="series",
                                           limite_trailer_mb=LIMITE, apagar_pasta_origem=True)
                if m.status == "limpeza"]
    desfazer(ultimo_log(raiz))
    assert (pastas[0] / "The.Office.S01E01.720p.BluRay.x264.DUAL-WWW.BLUDV.TV-poster.jpg").is_file()


def test_sobras_travas_de_seguranca(tmp_path):
    import json
    from jellyfin_tools import organizar_pasta
    from jellyfin_tools.organizador import PASTA_LOGS
    raiz = tmp_path / "Series"
    biblioteca = raiz / "Dark (2017)" / "Season 01"
    # pasta A: o log diz que o episódio saiu, mas ainda tem um vídeo DE VERDADE -> fica
    _video(raiz / "Torrent A" / "Dark.S01E02.mkv", 3 * MB)
    _video(raiz / "Torrent A" / "BLUDV.TV.mp4", MB // 2)
    # pasta B: nunca passou pelo organizador (não está no log) -> fica, mesmo só com propaganda
    _video(raiz / "Fotos e propagandas" / "www.site.com.mp4", MB // 2)
    _video(biblioteca / "Dark S01E01.mkv", 3 * MB)
    (raiz / PASTA_LOGS).mkdir()
    (raiz / PASTA_LOGS / "log-1.json").write_text(json.dumps({"raiz": str(raiz), "itens": [
        {"de": str(raiz / "Torrent A" / "Dark.S01E01.mkv"), "para": str(biblioteca / "Dark S01E01.mkv")}]}),
        encoding="utf-8")
    (raiz / PASTA_LOGS / "log-0.desfeito.json").write_text(json.dumps({"raiz": str(raiz), "itens": [
        {"de": str(raiz / "Fotos e propagandas" / "x.mkv"), "para": str(biblioteca / "Dark S01E01.mkv")}]}),
        encoding="utf-8")                                          # desfeito: não conta
    for apagar in (True, False):
        movs = organizar_pasta(raiz, raiz, CatalogoLocal.padrao(), modo="series", limite_trailer_mb=LIMITE,
                               apagar_pasta_origem=apagar)
        assert not [m for m in movs if m.status == "limpeza"]
    movs = organizar_pasta(raiz, raiz, CatalogoLocal.padrao(), modo="series", limite_trailer_mb=LIMITE,
                           apagar_pasta_origem=True, aplicar=True)
    assert (raiz / "Fotos e propagandas" / "www.site.com.mp4").exists()
    assert ultimo_log(raiz).name != "log-0.desfeito.json"


def test_episodio_curto_continua_nao_sendo_apagado(tmp_path):
    """Modo séries: vídeo pequeno que É episódio (ou não tem cara de propaganda) nunca vira lixo."""
    from jellyfin_tools import organizar_pasta
    pasta = tmp_path / "o" / "Serie"
    _video(pasta / "Dark.S01E01.mkv", 3 * MB)
    _video(pasta / "Dark.S01E02.WWW.BLUDV.TV.mkv", MB // 2)        # curto, com site, mas é episódio
    _video(pasta / "Making of.mkv", MB // 2)                       # extra sem cara de propaganda
    movs = organizar_pasta(tmp_path / "o", tmp_path / "S", CatalogoLocal.padrao(), modo="series",
                           limite_trailer_mb=LIMITE)
    assert not any(m.apagar for m in movs)
    assert sorted(m.status for m in movs) == ["nao_identificado", "simulado", "simulado"]


def test_atalhos_de_grupos_e_redes_sociais_sao_lixo(tmp_path):
    """Caso real: 'GRUPO FACEBOOK.url', 'GRUPO TELEGRAM.url', 'STARCKFILMES.COM.url' junto dos episódios."""
    raiz = tmp_path / "Uma Família Perfeita S01 2025"
    for nome in ("GRUPO FACEBOOK.url", "GRUPO TELEGRAM.url", "STARCKFILMES.COM.url"):
        _arquivo(raiz / nome)
        assert eh_lixo(raiz / nome, raiz)                          # mesmo na pasta raiz da origem
    _arquivo(raiz / "minhas_notas.txt")
    assert not eh_lixo(raiz / "minhas_notas.txt", raiz)            # nota pessoal continua a salvo
