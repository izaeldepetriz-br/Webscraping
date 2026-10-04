"""Parte 2: busca e download de legendas para a pasta do filme."""
import io
import json
import zipfile

import pytest

from jellyfin_tools import (CatalogoLocal, ConfigSite, ErroLegenda, ProvedorOpenSubtitles,
                            ProvedorSiteHTML, baixar_legenda, baixar_legendas_biblioteca,
                            organizar_pasta)
from jellyfin_tools.legendas import CandidatoLegenda, escolher_melhor, extrair_srt
from videoscraper.rede import ClienteHTTP

SRT = "1\n00:00:01,000 --> 00:00:02,000\nAção!\n"


def _provedor(site):
    return ProvedorSiteHTML(ConfigSite(site.base + "/busca?q={consulta}", nome="demo"), ClienteHTTP(espera=0))


def _pasta_filme(raiz, nome, ext=".mkv"):
    pasta = raiz / nome
    pasta.mkdir(parents=True)
    (pasta / f"{nome}{ext}").write_bytes(b"video")
    return pasta


def test_extrair_srt_utf8_cp1252_zip_e_invalido():
    assert extrair_srt(SRT.encode("utf-8")) == SRT
    assert extrair_srt(SRT.encode("cp1252")) == SRT                      # legenda 'antiga'
    assert extrair_srt(("﻿" + SRT).replace("\n", "\r\n").encode()) == SRT   # BOM + CRLF
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("leia.txt", "x")
        z.writestr("../../perigo/legenda.srt", SRT.encode())              # caminho malicioso: só lemos
    assert extrair_srt(buf.getvalue()) == SRT
    with pytest.raises(ErroLegenda):
        extrair_srt(b"<html>nao e legenda</html>")
    with pytest.raises(ErroLegenda):
        extrair_srt(b"PK\x03\x04quebrado")


def test_escolhe_idioma_ano_e_mais_baixado():
    c = [CandidatoLegenda("Matrix", 1999, "en", "u1", 9000),
         CandidatoLegenda("Matrix", 1999, "pt-BR", "u2", 300),
         CandidatoLegenda("Matrix", 1999, "pt-BR", "u3", 1500),
         CandidatoLegenda("Matrix Resurrections", 2021, "pt-BR", "u4", 99999),
         CandidatoLegenda("Outro Filme", 1999, "pt-BR", "u5", 99999)]
    assert escolher_melhor(c, "Matrix", 1999, "pt-BR").url == "u3"


@pytest.mark.parametrize("nome, trecho", [
    ("Matrix (1999)", "Matrix (1999) BluRay 1080p"),                  # o mais baixado em pt-BR
    ("O Poderoso Chefão (1972)", "O Poderoso Chefão (1972) Remastered"),  # veio em Windows-1252
])
def test_baixa_legenda_com_o_nome_do_video(tmp_path, site_legendas, nome, trecho):
    pasta = _pasta_filme(tmp_path, nome)
    r = baixar_legenda(pasta, [_provedor(site_legendas)])
    assert r.status == "baixada"
    assert r.caminho == pasta / f"{nome}.pt-BR.srt"
    texto = r.caminho.read_text(encoding="utf-8")
    assert trecho in texto and "Ação" in texto


def test_titulo_brasileiro_usa_o_original_como_reserva(tmp_path, site_legendas):
    # O site simulado só tem "Interstellar"; a pasta está com o título brasileiro.
    pasta = _pasta_filme(tmp_path, "Interestelar (2014)")
    assert baixar_legenda(pasta, [_provedor(site_legendas)]).status == "nao_encontrada"
    r = baixar_legenda(pasta, [_provedor(site_legendas)], titulos_alternativos=["Interstellar"])
    assert r.status == "baixada" and r.caminho.name == "Interestelar (2014).pt-BR.srt"
    assert "Interstellar" in r.caminho.read_text(encoding="utf-8")   # veio de dentro do .zip


def test_nao_sobrescreve_e_nao_encontrada(tmp_path, site_legendas):
    pasta = _pasta_filme(tmp_path, "Matrix (1999)")
    (pasta / "Matrix (1999).pt-BR.srt").write_text("minha legenda")
    assert baixar_legenda(pasta, [_provedor(site_legendas)]).status == "ja_existe"
    assert (pasta / "Matrix (1999).pt-BR.srt").read_text() == "minha legenda"
    assert baixar_legenda(pasta, [_provedor(site_legendas)], sobrescrever=True).status == "baixada"

    sem = _pasta_filme(tmp_path, "Cidade de Deus (2002)")
    r = baixar_legenda(sem, [_provedor(site_legendas)])
    assert r.status == "nao_encontrada" and not list(sem.glob("*.srt"))
    assert baixar_legenda(_pasta_filme(tmp_path, "pasta fora do padrao"), []).status == "erro"


def test_robots_bloqueia_o_site(tmp_path, servidor):
    # O servidor de testes do videoscraper proíbe /proibido no robots.txt.
    prov = ProvedorSiteHTML(ConfigSite(servidor.base + "/proibido/busca?q={consulta}"), ClienteHTTP(espera=0))
    r = baixar_legenda(_pasta_filme(tmp_path, "Matrix (1999)"), [prov])
    assert r.status == "nao_encontrada" and "robots.txt" in r.detalhe


def test_parte1_mais_parte2_juntas(tmp_path, site_legendas):
    """Fluxo completo: arquivos bagunçados -> pastas do Jellyfin -> legendas pt-BR."""
    origem, filmes = tmp_path / "Downloads", tmp_path / "Filmes"
    origem.mkdir()
    for n in ("Matrix.1999.1080p.BluRay.x264-VERSAO.mp4", "interestellar_filme_completo_dublado_2014.mkv",
              "O.Poderoso.Chefao.1972.Bluray.mkv"):
        (origem / n).write_bytes(b"video")
    organizar_pasta(origem, filmes, CatalogoLocal.padrao(), aplicar=True)
    resultados = baixar_legendas_biblioteca(filmes, [_provedor(site_legendas)], catalogo=CatalogoLocal.padrao())
    assert [r.status for r in resultados] == ["baixada"] * 3
    for nome in ("Matrix (1999)", "Interestelar (2014)", "O Poderoso Chefão (1972)"):
        assert (filmes / nome / f"{nome}.pt-BR.srt").is_file()


# ------------------------------------------------------------ OpenSubtitles (API falsa, sem internet)
def test_opensubtitles_busca_e_download(tmp_path, api_falsa):
    api_falsa.rotas["/api/v1/subtitles"] = lambda q: (200, {"data": [
        {"attributes": {"language": "pt-br", "download_count": 50, "url": "x",
                        "feature_details": {"title": "Matrix", "year": 1999}, "files": [{"file_id": 11}]}},
        {"attributes": {"language": "pt-br", "download_count": 900, "url": "y",
                        "feature_details": {"title": "Matrix", "year": 1999}, "files": [{"file_id": 22}]}}]})
    api_falsa.rotas["/api/v1/download"] = lambda q: (200, {"link": api_falsa.base + "/arquivo.srt"})
    api_falsa.rotas["/arquivo.srt"] = lambda q: (200, SRT.encode("cp1252"))

    prov = ProvedorOpenSubtitles("minha-chave", base_url=api_falsa.base + "/api/v1")
    pasta = _pasta_filme(tmp_path, "Matrix (1999)")
    r = baixar_legenda(pasta, [prov])
    assert r.status == "baixada" and r.caminho.read_text(encoding="utf-8") == SRT

    busca = next(p for p in api_falsa.pedidos if p["caminho"] == "/api/v1/subtitles")
    assert busca["headers"]["Api-Key"] == "minha-chave"
    assert busca["query"]["languages"] == ["pt-br"] and busca["query"]["year"] == ["1999"]
    download = next(p for p in api_falsa.pedidos if p["caminho"] == "/api/v1/download")
    assert json.loads(download["corpo"]) == {"file_id": 22}               # escolheu o mais baixado


def test_opensubtitles_limite_e_queda_para_proximo_provedor(tmp_path, api_falsa, site_legendas):
    api_falsa.rotas["/api/v1/subtitles"] = lambda q: (406, {"message": "quota"})
    prov = ProvedorOpenSubtitles("k", base_url=api_falsa.base + "/api/v1")
    pasta = _pasta_filme(tmp_path, "Matrix (1999)")
    r = baixar_legenda(pasta, [prov, _provedor(site_legendas)])            # falha no 1º, usa o 2º
    assert r.status == "baixada" and r.detalhe.startswith("demo")
    with pytest.raises(ErroLegenda):
        ProvedorOpenSubtitles("")
