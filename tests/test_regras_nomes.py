"""'Corrigir nome': regras que você ensina e o organizador lembra."""
from jellyfin_tools import CatalogoLocal, organizar_pasta
from jellyfin_tools.organizador import organizar_misto
from jellyfin_tools.regras import RegraNome, adicionar_regra, carregar_regras, numero_do_episodio, regra_para


def test_numero_do_episodio_sem_ano_resolucao_ou_codec():
    assert numero_do_episodio("Ep 14 [720p].mp4") == 14
    assert numero_do_episodio("Final 2019 1080p x264 - 07.mkv") == 7
    assert numero_do_episodio("sem numero.mkv") is None


def test_regras_salvas_e_a_mais_de_dentro_vale(tmp_path):
    arquivo = tmp_path / "regras.json"
    adicionar_regra(arquivo, RegraNome(str(tmp_path / "A"), "serie", "Nome Errado"))
    adicionar_regra(arquivo, RegraNome(str(tmp_path / "A"), "serie", "Breaking Bad", 2008, 5))   # troca
    adicionar_regra(arquivo, RegraNome(str(tmp_path / "A" / "B"), "serie", "Outra"))
    regras = carregar_regras(arquivo)
    assert len(regras) == 2
    assert regra_para(tmp_path / "A" / "x.mkv", regras, "serie").titulo == "Breaking Bad"
    assert regra_para(tmp_path / "A" / "B" / "x.mkv", regras, "serie").titulo == "Outra"
    assert regra_para(tmp_path / "C" / "x.mkv", regras, "serie") is None
    assert carregar_regras(tmp_path / "nao_existe.json") == []


def test_regra_de_serie_e_de_filme_no_organizador(tmp_path):
    pasta = tmp_path / "Downloads" / "Pasta Estranha"
    pasta.mkdir(parents=True)
    for nome in ("13 - To'hajiilee.mp4", "Ep 14.mp4", "Breaking.Bad.S03E02.mkv", "sem numero.mp4"):
        (pasta / nome).write_bytes(b"v")
    filme = tmp_path / "Downloads" / "filme_final_v2.mkv"
    filme.write_bytes(b"v")
    regras = [RegraNome(str(pasta), "serie", "Breaking Bad", 2008, 5),
              RegraNome(str(filme), "filme", "O Auto da Compadecida", 2000)]
    series = {m.origem.name: m for m in organizar_pasta(pasta, tmp_path / "Series", None, modo="series",
                                                       regras=regras)}
    destino = lambda nome: series[nome].destino.relative_to(tmp_path / "Series").as_posix()   # noqa: E731
    assert destino("13 - To'hajiilee.mp4") == "Breaking Bad (2008)/Season 05/Breaking Bad S05E13 - To'hajiilee.mp4"
    assert destino("Ep 14.mp4") == "Breaking Bad (2008)/Season 05/Breaking Bad S05E14.mp4"
    assert destino("Breaking.Bad.S03E02.mkv") == "Breaking Bad (2008)/Season 03/Breaking Bad S03E02.mkv"  # o S03 vale
    assert series["sem numero.mp4"].status == "nao_identificado"
    misto = {m.origem.name: m.destino for m in organizar_misto(tmp_path / "Downloads", tmp_path / "Filmes",
                                                               tmp_path / "Series", CatalogoLocal.padrao(),
                                                               regras=regras)}
    assert misto["filme_final_v2.mkv"].relative_to(tmp_path / "Filmes").as_posix() == \
        "O Auto da Compadecida (2000)/O Auto da Compadecida (2000).mkv"
    assert misto["Ep 14.mp4"].is_relative_to(tmp_path / "Series")
