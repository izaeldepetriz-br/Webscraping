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
