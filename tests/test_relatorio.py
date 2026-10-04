"""Relatório da biblioteca: legendas, pôsteres e episódios faltando."""
from jellyfin_tools.relatorio import faixas, gerar_relatorio, resumo, salvar_csv


def _arquivo(caminho, conteudo=b"x"):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_bytes(conteudo)


def test_faixas():
    assert faixas([5, 7, 8, 9, 12]) == "E05, E07–E09, E12"
    assert faixas([3]) == "E03" and faixas([]) == ""


def test_filmes_sem_legenda_e_sem_poster(tmp_path):
    filmes = tmp_path / "Filmes"
    _arquivo(filmes / "Matrix (1999)" / "Matrix (1999).mkv")
    _arquivo(filmes / "Matrix (1999)" / "Matrix (1999).pt-BR.srt")
    _arquivo(filmes / "Matrix (1999)" / "poster.jpg")
    _arquivo(filmes / "Creed II (2018)" / "Creed II (2018).mkv")
    _arquivo(filmes / "Creed II (2018)" / "Creed II (2018).pt-BR.forced.srt")     # forçada não conta
    _arquivo(filmes / "Nosferatu (1922)" / "Nosferatu (1922).strm", b"https://x/n.mp4\n")   # espelho também
    _arquivo(filmes / "Nosferatu (1922)" / "folder.jpg")
    _arquivo(filmes / "Pasta vazia" / "leia.txt")                                  # sem vídeo: ignorada
    pend = gerar_relatorio(filmes, None, ["pt-BR", "en"])
    assert sorted((p.item, p.falta) for p in pend) == [
        ("Creed II (2018)", "legenda en"), ("Creed II (2018)", "legenda pt-BR"), ("Creed II (2018)", "pôster"),
        ("Matrix (1999)", "legenda en"), ("Nosferatu (1922)", "legenda en"), ("Nosferatu (1922)", "legenda pt-BR")]


def test_series_episodios_faltando_e_sem_legenda(tmp_path):
    series = tmp_path / "Series"
    temporada = series / "Dark (2017)" / "Season 02"
    for n in (1, 2, 3, 4, 6, 8):
        _arquivo(temporada / f"Dark S02E{n:02d}.mkv")
    for n in (1, 2, 3, 4, 6):
        _arquivo(temporada / f"Dark S02E{n:02d}.pt-BR.srt")
    pend = gerar_relatorio(None, series, ["pt-BR"])
    assert [(p.item, p.falta, p.detalhe) for p in pend] == [
        ("Dark (2017) S02", "episódios", "E05, E07"),
        ("Dark (2017) S02", "legenda pt-BR", "1 episódio(s): E08")]
    assert resumo(pend) == "1 temporada(s) – falta episódios; 1 temporada(s) – falta legenda pt-BR"


def test_series_com_tmdb_fim_da_temporada_e_temporada_inteira(tmp_path):
    from jellyfin_tools.catalogo import Catalogo, Filme

    class TMDBFalso(Catalogo):
        def buscar(self, titulo, ano, tipo="filme"):
            return Filme("Dark", 2017, tmdb_id=70523, tipo="serie")

        def temporadas(self, serie):
            return [(1, 10), (2, 8), (3, 8)]
    temporada = tmp_path / "Series" / "Dark (2017)" / "Season 01"
    for n in range(1, 9):                                                  # tem 1..8 de 10
        _arquivo(temporada / f"Dark S01E{n:02d}.mkv")
        _arquivo(temporada / f"Dark S01E{n:02d}.pt-BR.srt")
    pend = gerar_relatorio(None, tmp_path / "Series", ["pt-BR"], TMDBFalso())
    assert [(p.item, p.falta, p.detalhe) for p in pend] == [
        ("Dark (2017) S01", "episódios", "E09–E10"),
        ("Dark (2017) S02", "temporada inteira", "8 episódio(s) no TMDB"),
        ("Dark (2017) S03", "temporada inteira", "8 episódio(s) no TMDB")]


def test_salvar_csv(tmp_path):
    import csv
    _arquivo(tmp_path / "F" / "Matrix (1999)" / "Matrix (1999).mkv")
    arquivo = salvar_csv(gerar_relatorio(tmp_path / "F", None, ["pt-BR"]), tmp_path / "relatorios")
    with open(arquivo, encoding="utf-8-sig", newline="") as f:
        linhas = list(csv.reader(f, delimiter=";"))
    assert linhas[0] == ["tipo", "item", "falta", "detalhe", "pasta"]
    assert [l[2] for l in linhas[1:]] == ["legenda pt-BR", "pôster"]


def test_script_relatorio(tmp_path, monkeypatch):
    import organizar_jellyfin as script
    _arquivo(tmp_path / "Filmes" / "Matrix (1999)" / "Matrix (1999).mkv")
    for nome, valor in {"PASTA_FILMES": tmp_path / "Filmes", "PASTA_SERIES": "", "TMDB_API_KEY": "",
                        "ARQUIVO_LOG": tmp_path / "log" / "j.log"}.items():
        monkeypatch.setenv(nome, str(valor))
    assert script.main(["--relatorio"]) == 0
    [planilha] = (tmp_path / "log" / "relatorios").glob("relatorio-*.csv")
    assert "legenda pt-BR" in planilha.read_text(encoding="utf-8-sig")
    assert "[falta pôster] Matrix (1999)" in (tmp_path / "log" / "j.log").read_text(encoding="utf-8")
