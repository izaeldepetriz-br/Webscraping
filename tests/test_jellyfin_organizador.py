"""Parte 1: leitura de nomes, catálogo e organização no padrão do Jellyfin."""

import pytest

from jellyfin_tools import (CatalogoEmCadeia, CatalogoLocal, CatalogoTMDB, ErroCatalogo, Filme,
                            desfazer, extrair_titulo_e_ano, nome_jellyfin, organizar_pasta)
from jellyfin_tools.nomes import formatar_titulo, ler_nome_jellyfin
from jellyfin_tools.organizador import ultimo_log

# Os 3 casos do enunciado: arquivo -> pasta/arquivo esperados
CASOS = {
    "Matrix.1999.1080p.BluRay.x264-VERSAO.mp4": "Matrix (1999)/Matrix (1999).mp4",
    "interestellar_filme_completo_dublado_2014.mkv": "Interestelar (2014)/Interestelar (2014).mkv",
    "O.Poderoso.Chefao.1972.Bluray.mkv": "O Poderoso Chefão (1972)/O Poderoso Chefão (1972).mkv",
}


@pytest.mark.parametrize("nome, titulo, ano", [
    ("Matrix.1999.1080p.BluRay.x264-VERSAO.mp4", "Matrix", 1999),
    ("interestellar_filme_completo_dublado_2014.mkv", "interestellar", 2014),
    ("O.Poderoso.Chefao.1972.Bluray.mkv", "O Poderoso Chefao", 1972),
    ("Blade.Runner.2049.2017.2160p.mkv", "Blade Runner 2049", 2017),     # 2049 é título, não ano
    ("1917.2019.mkv", "1917", 2019),
    ("1917.mkv", "1917", None),
    ("Duna.Parte.Dois.1080p.WEB-DL.mkv", "Duna Parte Dois", None),       # corta no 1080p
    ("Star Wars - Episode IV [1977] (Dublado).avi", "Star Wars Episode IV", 1977),
    ("Filme.de.Terror.2010.Dublado.mkv", "Filme de Terror", 2010),        # 'Filme' é o título aqui
])
def test_extrair_titulo_e_ano(nome, titulo, ano):
    assert extrair_titulo_e_ano(nome) == (titulo, ano)


def test_nomes_no_padrao_jellyfin():
    assert nome_jellyfin("Missão: Impossível", 1996) == "Missão - Impossível (1996)"
    assert nome_jellyfin("Matrix", 1999, 603, incluir_tmdbid=True) == "Matrix (1999) [tmdbid-603]"
    assert nome_jellyfin('Que?/Filme*"', 2000) == "QueFilme (2000)"
    assert ler_nome_jellyfin("Matrix (1999) [tmdbid-603]") == ("Matrix", 1999)
    assert formatar_titulo("o senhor dos aneis") == "O Senhor dos Aneis"


def test_catalogo_corrige_digitacao_acentos_e_respeita_o_ano():
    c = CatalogoLocal.padrao()
    assert c.buscar("interestellar", 2014).titulo == "Interestelar"      # título brasileiro
    assert c.buscar("Interstellar", 2014).titulo == "Interestelar"       # achado pelo original
    assert c.buscar("O Poderoso Chefao", 1972).titulo == "O Poderoso Chefão"
    assert c.buscar("The Godfather", 1972).titulo == "O Poderoso Chefão"    # pelo título original
    assert c.buscar("Matrix", 2021) is None                                 # outro filme
    assert c.buscar("Filme Que Nao Existe", 2001) is None


def _criar(pasta, nomes):
    pasta.mkdir(parents=True, exist_ok=True)
    for n in nomes:
        (pasta / n).write_bytes(b"video")


def test_simulacao_nao_mexe_em_nada(tmp_path):
    _criar(tmp_path / "bagunca", CASOS)
    movs = organizar_pasta(tmp_path / "bagunca", tmp_path / "Filmes", CatalogoLocal.padrao())
    assert {m.status for m in movs} == {"simulado"}
    assert not (tmp_path / "Filmes").exists()
    assert sorted(p.name for p in (tmp_path / "bagunca").iterdir()) == sorted(CASOS)


def test_organiza_os_3_arquivos_do_enunciado_e_desfaz(tmp_path):
    origem, filmes = tmp_path / "bagunca", tmp_path / "Filmes"
    _criar(origem, CASOS)
    (origem / "Matrix.1999.1080p.BluRay.x264-VERSAO.pt-BR.srt").write_text("1\n00:00 --> 00:01\noi\n")
    movs = organizar_pasta(origem, filmes, CatalogoLocal.padrao(), aplicar=True)
    assert {m.status for m in movs} == {"movido"}
    for esperado in CASOS.values():
        assert (filmes / esperado).is_file()
    assert (filmes / "Matrix (1999)" / "Matrix (1999).pt-BR.srt").is_file()   # legenda foi junto

    mensagens = desfazer(ultimo_log(filmes))
    assert sorted(p.name for p in origem.iterdir()) == sorted(
        list(CASOS) + ["Matrix.1999.1080p.BluRay.x264-VERSAO.pt-BR.srt"])
    assert not any(p.is_dir() for p in filmes.iterdir() if not p.name.startswith("."))
    assert all(m.startswith("voltou") for m in mensagens)


def test_conflitos_amostras_e_nao_identificados(tmp_path):
    origem, filmes = tmp_path / "bagunca", tmp_path / "Filmes"
    _criar(origem, ["Matrix.1999.mkv", "Matrix.1999.sample.mkv", "video_sem_ano.mp4", "Filme.Caseiro.2010.mp4"])
    _criar(origem / "sub", ["The.Matrix.1999.720p.mkv"])
    _criar(filmes / "Cidade de Deus (2002)", ["Cidade de Deus (2002).mkv"])
    _criar(origem, ["Cidade.de.Deus.2002.mkv"])
    status = {m.origem.name: (m.status, m.destino) for m in
              organizar_pasta(origem, filmes, CatalogoLocal.padrao(), aplicar=True)}
    assert status["The.Matrix.1999.720p.mkv"][0] == "movido"         # mesmo filme: vai a de qualidade conhecida
    assert status["Matrix.1999.mkv"][0] == "conflito"
    assert status["Matrix.1999.sample.mkv"][0] == "ignorado"
    assert status["video_sem_ano.mp4"][0] == "nao_identificado"
    assert status["Cidade.de.Deus.2002.mkv"][0] == "conflito"        # já existia na biblioteca
    assert status["Filme.Caseiro.2010.mp4"] == ("movido", filmes / "Filme Caseiro (2010)" / "Filme Caseiro (2010).mp4")
    assert (origem / "Cidade.de.Deus.2002.mkv").exists()             # nada foi sobrescrito


def test_exigir_catalogo_e_pasta_inexistente(tmp_path):
    _criar(tmp_path / "o", ["Filme.Caseiro.2010.mp4"])
    [m] = organizar_pasta(tmp_path / "o", tmp_path / "F", CatalogoLocal.padrao(), exigir_catalogo=True)
    assert m.status == "nao_identificado"
    with pytest.raises(NotADirectoryError):
        organizar_pasta(tmp_path / "nao-existe", tmp_path / "F")


def test_catalogo_json_invalido(tmp_path):
    (tmp_path / "c.json").write_text("[{\"titulo\": \"X\"}]")
    with pytest.raises(ErroCatalogo):
        CatalogoLocal.de_json(tmp_path / "c.json")


# ----------------------------------------------------------------- TMDB (servidor falso, sem internet)
def test_tmdb_com_servidor_falso(api_falsa):
    api_falsa.rotas["/3/search/movie"] = lambda q: (200, {"results": [
        {"id": 238, "title": "O Poderoso Chefão", "original_title": "The Godfather", "release_date": "1972-03-14"},
        {"id": 240, "title": "O Poderoso Chefão: Parte II", "original_title": "The Godfather Part II",
         "release_date": "1974-12-20"}]})
    tmdb = CatalogoTMDB("chave123", base_url=api_falsa.base + "/3")
    filme = tmdb.buscar("O Poderoso Chefao", 1972)
    assert filme == Filme("O Poderoso Chefão", 1972, "The Godfather", 238)
    pedido = api_falsa.pedidos[-1]
    assert pedido["query"]["api_key"] == ["chave123"] and pedido["query"]["language"] == ["pt-BR"]

    CatalogoTMDB("eyJtoken", base_url=api_falsa.base + "/3").buscar("O Poderoso Chefao", 1972)
    assert api_falsa.pedidos[-1]["headers"]["Authorization"] == "Bearer eyJtoken"


def test_tmdb_erros_e_cadeia(api_falsa):
    api_falsa.rotas["/3/search/movie"] = lambda q: (401, {"status_message": "Invalid API key"})
    tmdb = CatalogoTMDB("errada", base_url=api_falsa.base + "/3")
    with pytest.raises(ErroCatalogo, match="401"):
        tmdb.buscar("Matrix", 1999)
    # Em cadeia: o local responde antes; se só o TMDB falhar, não derruba o programa.
    cadeia = CatalogoEmCadeia(CatalogoLocal.padrao(), tmdb)
    assert cadeia.buscar("Matrix", 1999).titulo == "Matrix"
    assert cadeia.buscar("Desconhecido", 2001) is None
    with pytest.raises(ErroCatalogo):
        CatalogoTMDB("")


# ----------------------------------------------------------------- origem = a própria biblioteca
def test_organiza_dentro_da_propria_biblioteca(tmp_path):
    """Caso comum: os filmes bagunçados JÁ estão na pasta do Jellyfin (mesma pasta nos 2 campos)."""
    biblioteca = tmp_path / "Filmes_Organizados"
    _criar(biblioteca / "Matrix.1999.1080p.BluRay", ["Matrix.1999.1080p.BluRay.x264-VERSAO.mp4"])
    (biblioteca / "Matrix.1999.1080p.BluRay" / "Matrix.1999.1080p.BluRay.x264-VERSAO.pt-BR.srt").write_text("x")
    _criar(biblioteca, ["O.Poderoso.Chefao.1972.Bluray.mkv"])                       # solto na raiz
    _criar(biblioteca / "Interestelar (2014)", ["Interestelar (2014).mkv"])          # já no padrão
    _criar(biblioteca / "Pasta com capa", ["interestellar_filme_completo_dublado_2014.mkv", ])
    (biblioteca / "Pasta com capa" / "capa.jpg").write_bytes(b"jpg")                 # sobra: pasta fica

    previa = {m.origem.name: m for m in organizar_pasta(biblioteca, biblioteca, CatalogoLocal.padrao())}
    assert previa["Interestelar (2014).mkv"].status == "organizado"                  # não mexe
    assert previa["Matrix.1999.1080p.BluRay.x264-VERSAO.mp4"].status == "simulado"
    assert previa["interestellar_filme_completo_dublado_2014.mkv"].status == "conflito"  # já existe

    movs = organizar_pasta(biblioteca, biblioteca, CatalogoLocal.padrao(), aplicar=True)
    assert sum(m.status == "movido" for m in movs) == 2
    assert (biblioteca / "Matrix (1999)" / "Matrix (1999).mp4").is_file()
    assert (biblioteca / "Matrix (1999)" / "Matrix (1999).pt-BR.srt").is_file()
    assert (biblioteca / "O Poderoso Chefão (1972)" / "O Poderoso Chefão (1972).mkv").is_file()
    assert not (biblioteca / "Matrix.1999.1080p.BluRay").exists()                   # esvaziou: apagada
    assert (biblioteca / "Pasta com capa" / "capa.jpg").exists()                     # não estava vazia
    assert (biblioteca / "Interestelar (2014)" / "Interestelar (2014).mkv").is_file()

    # Rodar de novo não muda nada: tudo que dava para arrumar já está no padrão.
    de_novo = organizar_pasta(biblioteca, biblioteca, CatalogoLocal.padrao())
    assert not [m for m in de_novo if m.status == "simulado"]

    desfazer(ultimo_log(biblioteca))                                                  # e volta tudo
    assert (biblioteca / "Matrix.1999.1080p.BluRay" / "Matrix.1999.1080p.BluRay.x264-VERSAO.mp4").is_file()
    assert (biblioteca / "O.Poderoso.Chefao.1972.Bluray.mkv").is_file()
    assert not (biblioteca / "Matrix (1999)").exists()


def test_origem_dentro_da_biblioteca_e_biblioteca_dentro_da_origem(tmp_path):
    biblioteca = tmp_path / "Filmes"
    _criar(biblioteca / "Baixados", ["Matrix.1999.mkv"])
    [m] = organizar_pasta(biblioteca / "Baixados", biblioteca, CatalogoLocal.padrao(), aplicar=True)
    assert m.status == "movido" and (biblioteca / "Matrix (1999)" / "Matrix (1999).mkv").is_file()
    assert (biblioteca / "Baixados").exists()               # a própria origem nunca é apagada

    # Origem "maior" que a biblioteca (ex.: E:/ e E:/Filmes): o que está na biblioteca fica de fora.
    _criar(tmp_path, ["Cidade.de.Deus.2002.mkv"])
    movs = organizar_pasta(tmp_path, biblioteca, CatalogoLocal.padrao())
    assert [m.origem.name for m in movs] == ["Cidade.de.Deus.2002.mkv"]


def test_series_dentro_da_propria_biblioteca(tmp_path):
    series = tmp_path / "Series"
    _criar(series / "Dark (2017)" / "Season 01", ["Dark S01E01.mkv"])                # já no padrão
    _criar(series / "baixados dark", ["Dark.S01E02.WEBRip.mkv"])
    movs = {m.origem.name: m for m in organizar_pasta(series, series, CatalogoLocal.padrao(),
                                                       aplicar=True, modo="series")}
    assert movs["Dark S01E01.mkv"].status == "organizado"
    assert movs["Dark.S01E02.WEBRip.mkv"].status == "movido"
    assert (series / "Dark (2017)" / "Season 01" / "Dark S01E02.mkv").is_file()
    assert not (series / "baixados dark").exists()


# ----------------------------------------------------------------- progresso
def test_mover_entre_discos_copia_em_blocos_com_progresso(tmp_path, monkeypatch):
    import jellyfin_tools.organizador as org
    monkeypatch.setattr(org, "_mesmo_disco", lambda a, b: False)       # finge C: -> E:
    monkeypatch.setattr(org, "BLOCO_COPIA", 1000)
    origem = tmp_path / "filme.mkv"
    dados = bytes(range(256)) * 40                                      # 10.240 bytes = 11 blocos
    origem.write_bytes(dados)
    destino = tmp_path / "Filme (2000)" / "Filme (2000).mkv"
    destino.parent.mkdir()
    fracoes = []
    org.mover_com_progresso(origem, destino, fracoes.append)
    assert destino.read_bytes() == dados and not origem.exists()
    assert fracoes == sorted(fracoes) and fracoes[-1] == 1.0 and len(fracoes) >= 10
    assert not list(destino.parent.glob("*.part"))                      # sem sobra de cópia parcial
    origem.write_bytes(b"x")
    with pytest.raises(FileExistsError):                                 # nunca sobrescreve
        org.mover_com_progresso(origem, destino)


def test_organizar_avisa_plano_e_andamento(tmp_path):
    _criar(tmp_path / "o", ["Matrix.1999.mkv", "Cidade.de.Deus.2002.mkv", "sem_ano.mp4"])
    planos, avisos = [], []
    movs = organizar_pasta(tmp_path / "o", tmp_path / "F", CatalogoLocal.padrao(), aplicar=True,
                           ao_planejar=planos.append, ao_progresso=lambda i, m, f: avisos.append((i, f)))
    assert len(planos) == 1 and len(planos[0]) == 3
    movidos = [i for i, m in enumerate(movs) if m.status == "movido"]
    assert sorted({i for i, _ in avisos}) == movidos                   # só quem se move dá aviso
    for i in movidos:
        fr = [f for j, f in avisos if j == i]
        assert fr[0] == 0.0 and fr[-1] == 1.0


# ------------------------------------------------------------------ caminho inválido (caso real)
CAMINHO_COLADO = r"E:\Series_OE:\Series_Organizadas\Series\Uma Família Perfeita S01 2025"


@pytest.mark.parametrize("caminho, ok", [
    (CAMINHO_COLADO, False),                                   # um endereço colado dentro de outro
    (r"E:\Filmes?", False), (r"E:\A|B", False),
    (r"E:\Series_Organizadas\Series", True), ("E:/Filmes", True), (r"\\DEPETRIZ\e\Series", True),
    (r"\\?\C:\Filmes\Matrix (1999)", True), (r"C:\x\Filme (2000) [tmdbid-603]", True)])
def test_problema_no_caminho_regras_do_windows(caminho, ok):
    from jellyfin_tools.organizador import problema_no_caminho
    assert (problema_no_caminho(caminho, windows=True) is None) == ok
    assert problema_no_caminho(caminho, windows=False) is None   # Linux/Mac: ':' e '?' são permitidos


def test_sugestao_e_trava_antes_de_mexer(tmp_path, monkeypatch):
    from jellyfin_tools import organizador
    assert organizador.sugestao_de_caminho(CAMINHO_COLADO) == r"E:\Series_Organizadas\Series\Uma Família Perfeita S01 2025"
    assert organizador.sugestao_de_caminho(r"E:\Filmes") is None
    origem = tmp_path / "o"
    origem.mkdir()
    (origem / "Matrix.1999.mkv").write_bytes(b"v")
    monkeypatch.setattr(organizador, "WINDOWS", True)
    with pytest.raises(ValueError, match="biblioteca inválida.*no meio"):
        organizar_pasta(origem, CAMINHO_COLADO, CatalogoLocal.padrao(), aplicar=True)
    assert (origem / "Matrix.1999.mkv").exists()                 # nada foi mexido


# ------------------------------------------------------------------ cópias de qualidade diferente
def test_qualidade_pelo_nome():
    from jellyfin_tools.nomes import qualidade
    assert qualidade("Matrix.1999.1080p.BluRay.x264.mkv") == (1080, 5, "1080p BluRay")
    assert qualidade("Matrix.1999.720p.WEB-DL.mkv") == (720, 4, "720p WEB-DL")
    assert qualidade("Matrix 1999 2160p UHD Remux.mkv")[:2] == (2160, 6)
    assert qualidade("Matrix.1999.HDCAM.mkv")[1] == -5                       # gravado no cinema: o pior
    assert qualidade("Matrix (1999).mkv") == (0, 0, "")


def test_entre_copias_vai_a_de_melhor_qualidade(tmp_path):
    origem = tmp_path / "Downloads"
    origem.mkdir()
    for nome, tamanho in (("Matrix.1999.720p.WEB-DL.mkv", 3), ("Matrix.1999.1080p.BluRay.x264.mkv", 2),
                          ("Matrix.1999.HDCAM.mkv", 5)):
        with open(origem / nome, "wb") as f:
            f.truncate(tamanho * 1024 * 1024)
    movs = {m.origem.name: m for m in organizar_pasta(origem, tmp_path / "F", CatalogoLocal.padrao())}
    assert movs["Matrix.1999.1080p.BluRay.x264.mkv"].status == "simulado"   # não a 1ª da lista nem a maior
    perdedora = movs["Matrix.1999.720p.WEB-DL.mkv"]
    assert perdedora.status == "conflito"
    assert perdedora.detalhe == ("cópia repetida (720p WEB-DL); vai a melhor (1080p BluRay): "
                                 "Matrix.1999.1080p.BluRay.x264.mkv")
    assert movs["Matrix.1999.HDCAM.mkv"].status == "conflito"


def test_copia_que_ja_esta_na_biblioteca_mostra_os_tamanhos(tmp_path):
    origem, filmes = tmp_path / "Downloads", tmp_path / "Filmes"
    origem.mkdir()
    (filmes / "Matrix (1999)").mkdir(parents=True)
    with open(filmes / "Matrix (1999)" / "Matrix (1999).mkv", "wb") as f:
        f.truncate(2 * 1024 ** 3)
    with open(origem / "Matrix.1999.2160p.UHD.Remux.mkv", "wb") as f:
        f.truncate(5 * 1024 ** 3)
    [m] = organizar_pasta(origem, filmes, CatalogoLocal.padrao())
    assert m.status == "conflito"
    assert m.detalhe == ("já existe na biblioteca (2.0 GB); este tem 5.0 GB, 2160p Remux. "
                         "Nada é sobrescrito: compare e apague o pior")
