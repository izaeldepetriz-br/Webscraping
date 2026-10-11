"""Tradução local (Argos): baixar o modelo na 1ª vez, a ponte pelo inglês, itálico e diálogo na legenda. O modelo de
verdade (CTranslate2) é testado no autoteste do .exe; aqui, um tradutor de mentira."""
import io
import json
import zipfile
from types import SimpleNamespace

import pytest

from jellyfin_tools import traducao_local as tl
from jellyfin_tools.traducao import ErroTraducao, ler_srt, traduzir_arquivo

INDICE = [{"from_code": "en", "to_code": "pt", "links": ["https://argos-net.com/v1/translate-en_pt-1_9.argosmodel"]},
          {"from_code": "fr", "to_code": "en", "links": ["https://argos-net.com/v1/translate-fr_en-1_9.argosmodel"]},
          {"from_code": "es", "to_code": "pt", "links": ["https://argos-net.com/v1/translate-es_pt-1_0.argosmodel"]}]


def pacote(nome: str) -> bytes:
    """Um .argosmodel de mentira: a mesma estrutura do de verdade."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(f"{nome}/metadata.json", json.dumps({"from_code": nome[10:12], "to_code": nome[13:15]}))
        z.writestr(f"{nome}/model/model.bin", b"x")
        z.writestr(f"{nome}/sentencepiece.model", b"x")
    return buf.getvalue()


class Internet:
    def __init__(self):
        self.baixados = []

    def __call__(self, url, timeout=30, stream=False):
        if url == tl.INDICE:
            return SimpleNamespace(json=lambda: INDICE)
        self.baixados.append(url)
        dados = pacote(url.rsplit("/", 1)[1].rsplit("-", 1)[0])
        return SimpleNamespace(headers={"content-length": str(len(dados))},
                               iter_content=lambda n: [dados[:10], dados[10:]])


class ModeloFalso:
    """'en->pt' põe [pt] na frente; 'fr->en' põe [en]: dá para ver a ponte pelo inglês."""

    def __init__(self, pasta):
        self.para = json.loads((pasta / "metadata.json").read_text())["to_code"]
        self.vezes = 0

    def traduzir(self, textos):
        self.vezes += 1
        return [f"[{self.para}] {t}" for t in textos]


def test_codigos_e_idioma_pelo_nome_do_arquivo():
    assert tl.codigo("pt-BR") == "pt" and tl.codigo("eng") == "en" and tl.codigo("EN") == "en"
    assert tl.idioma_do_arquivo("Filme (2003).en.srt") == "en"
    assert tl.idioma_do_arquivo("Filme.eng.forced.srt") == "en"
    assert tl.idioma_do_arquivo("Filme.srt") == ""


def test_rota_direta_ou_pelo_ingles():
    pares = {("en", "pt"), ("fr", "en"), ("es", "pt")}
    assert tl.rota(pares, "en", "pt-BR") == [("en", "pt")]
    assert tl.rota(pares, "es", "pt") == [("es", "pt")]
    assert tl.rota(pares, "fr", "pt") == [("fr", "en"), ("en", "pt")]          # sem fr->pt: passa pelo inglês
    assert tl.rota(pares, "pt", "pt-BR") == []
    with pytest.raises(tl.ErroTraducaoLocal, match="ja para pt"):
        tl.rota(pares, "ja", "pt")


def test_baixa_o_modelo_so_na_primeira_vez(tmp_path):
    internet = Internet()
    pasta = tl.preparar_par("en", "pt", tmp_path, internet)
    assert (pasta / "metadata.json").is_file() and (pasta / "model").is_dir()
    assert tl.preparar_par("en", "pt", tmp_path, internet) == pasta and len(internet.baixados) == 1
    with pytest.raises(tl.ErroTraducaoLocal, match="não há modelo"):
        tl.preparar_par("ja", "pt", tmp_path, internet)


def test_pacote_adulterado_nao_escreve_fora_da_pasta(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("../fora.txt", b"x")
    def obter(url, timeout=30, stream=False):
        if url == tl.INDICE:
            return SimpleNamespace(json=lambda: INDICE)
        dados = buf.getvalue()
        return SimpleNamespace(headers={}, iter_content=lambda n: [dados])
    with pytest.raises(tl.ErroTraducaoLocal, match="estranho"):
        tl.preparar_par("en", "pt", tmp_path / "modelos", obter)
    assert not (tmp_path / "fora.txt").exists()


def test_traduz_a_legenda_mantendo_italico_e_dialogo(tmp_path):
    origem = tmp_path / "Filme.fr.srt"
    origem.write_text("1\n00:00:01,000 --> 00:00:02,000\n<i>Bonjour</i>\n\n"
                      "2\n00:00:03,000 --> 00:00:04,000\n- Oui ?\n- Non.\n\n"
                      "3\n00:00:05,000 --> 00:00:06,000\nUne phrase\ncoupée en deux\n\n", encoding="utf-8")
    tradutor = tl.TradutorLocal(tmp_path / "modelos", "pt-BR", obter=Internet(), carregar=ModeloFalso)
    r = traduzir_arquivo(origem, tmp_path / "Filme.pt-BR.srt", tradutor)
    assert r.status == "traduzida" and tradutor.idioma_origem == "fr" and tradutor.custo == 0
    textos = [f.texto for f in ler_srt(r.destino.read_text(encoding="utf-8"))]
    assert textos[0] == "<i>[pt] [en] Bonjour</i>"                              # fr -> en -> pt
    assert textos[1] == "- [pt] [en] Oui ?\n- [pt] [en] Non."                    # cada fala do diálogo
    assert textos[2] == "[pt] [en] Une phrase coupée en deux"                    # as linhas viram uma frase


def test_sem_modelo_para_o_idioma_e_erro_de_traducao(tmp_path):
    tradutor = tl.TradutorLocal(tmp_path, "pt-BR", idioma_origem="ja", obter=Internet(), carregar=ModeloFalso)
    with pytest.raises(ErroTraducao, match="ja para pt"):
        tradutor.traduzir_falas(["こんにちは"])
