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
