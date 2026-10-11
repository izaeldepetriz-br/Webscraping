"""Tradução LOCAL e grátis das legendas: roda no seu PC, sem chave e sem internet (só baixa o modelo na 1ª vez).

Usa os modelos abertos do Argos Translate (OpenNMT), no mesmo motor do Whisper (CTranslate2) e o SentencePiece para
cortar o texto em pedaços. Não usa a biblioteca argostranslate (ela puxa o PyTorch, enorme): só os modelos.

    pacote .argosmodel = um .zip com  <pasta>/metadata.json, <pasta>/model/ (CTranslate2), <pasta>/sentencepiece.model

Idiomas: há modelo direto para o português a partir do inglês e do espanhol; os outros (francês, alemão, italiano,
japonês, coreano...) vão em duas etapas, passando pelo inglês (ex.: fr -> en -> pt).

A qualidade é boa para entender o filme, mas abaixo do Claude: frases idiomáticas e gírias saem mais literais, e o
tradutor não sabe o contexto das falas anteriores. Em compensação: custo zero e nada sai do seu PC.
"""

from __future__ import annotations

import json
import re
import shutil
import zipfile
from pathlib import Path

INDICE = "https://raw.githubusercontent.com/argosopentech/argospm-index/main/index.json"
LOTE = 32                         # falas por vez no tradutor
TRES_LETRAS = {"eng": "en", "spa": "es", "fre": "fr", "fra": "fr", "ger": "de", "deu": "de", "ita": "it",
               "jpn": "ja", "kor": "ko", "por": "pt", "rus": "ru", "chi": "zh", "zho": "zh", "dut": "nl",
               "nld": "nl", "pol": "pl", "tur": "tr", "ara": "ar", "hin": "hi"}
_ITALICO = re.compile(r"^\s*<i>(.*)</i>\s*$", re.S)


class ErroTraducaoLocal(Exception):
    pass


def codigo(idioma: str) -> str:
    """'pt-BR' -> 'pt', 'eng' -> 'en', 'en' -> 'en'."""
    idioma = (idioma or "").strip().lower()
    base = idioma.split("-")[0].split("_")[0]
    return TRES_LETRAS.get(base, base)


def idioma_do_arquivo(legenda: str | Path) -> str:
    """'Filme.en.srt' -> 'en'; 'Filme.eng.forced.srt' -> 'en'; sem marca -> ''."""
    partes = Path(legenda).name.lower().split(".")[1:-1]
    for parte in reversed(partes):
        c = codigo(parte)
        if 2 <= len(c) <= 3 and c.isalpha() and parte not in ("forced", "sdh", "cc", "hi"):
            return c
    return ""


def rota(pares: set[tuple[str, str]], de: str, para: str) -> list[tuple[str, str]]:
    """Os modelos a usar: direto, ou passando pelo inglês. Sem caminho: ErroTraducaoLocal."""
    de, para = codigo(de), codigo(para)
    if de == para:
        return []
    if (de, para) in pares:
        return [(de, para)]
    if (de, "en") in pares and ("en", para) in pares:
        return [(de, "en"), ("en", para)]
    raise ErroTraducaoLocal(f"não há modelo de tradução local de {de} para {para}")


# ----------------------------------------------------------------- baixar os modelos (só na 1ª vez)
def _obter(url: str, timeout: float = 30, stream: bool = False):
    import requests
    resposta = requests.get(url, timeout=timeout, stream=stream)
    resposta.raise_for_status()
    return resposta


def indice(pasta: Path, obter=_obter, validade_dias: float = 7) -> list[dict]:
    """A lista de modelos do Argos, guardada por uma semana (sem internet, vale a última)."""
    import time
    arquivo = Path(pasta) / "indice.json"
    try:
        if time.time() - arquivo.stat().st_mtime < validade_dias * 86400:
            return json.loads(arquivo.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    try:
        dados = obter(INDICE).json()
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        arquivo.write_text(json.dumps(dados), encoding="utf-8")
        return dados
    except Exception as erro:
        try:
            return json.loads(arquivo.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise ErroTraducaoLocal(f"não deu para baixar a lista de modelos de tradução ({type(erro).__name__})")


def _link(pacote: dict) -> str:
    return next((l for l in pacote.get("links", []) if l.startswith("http")), "")


def preparar_par(de: str, para: str, pasta: Path, obter=_obter, ao_progresso=None) -> Path:
    """A pasta do modelo de..para (baixa e descompacta na 1ª vez). Devolve a pasta que tem o metadata.json."""
    pasta = Path(pasta)
    destino = pasta / f"{de}_{para}"
    if (pronto := _pasta_do_modelo(destino)) is not None:
        return pronto
    pacote = next((p for p in indice(pasta, obter) if p.get("from_code") == de and p.get("to_code") == para), None)
    if pacote is None or not _link(pacote):
        raise ErroTraducaoLocal(f"não há modelo de tradução local de {de} para {para}")
    parcial = pasta / f"{de}_{para}.argosmodel.part"
    parcial.parent.mkdir(parents=True, exist_ok=True)
    try:
        resposta = obter(_link(pacote), timeout=60, stream=True)
        total = int(resposta.headers.get("content-length") or 0)
        feito = 0
        with open(parcial, "wb") as saida:
            for pedaco in resposta.iter_content(1 << 16):
                saida.write(pedaco)
                feito += len(pedaco)
                if ao_progresso and total:
                    ao_progresso(min(feito / total, 1.0))
        temporaria = pasta / f"{de}_{para}.tmp"
        shutil.rmtree(temporaria, ignore_errors=True)
        with zipfile.ZipFile(parcial) as z:
            raiz = temporaria.resolve()
            for nome in z.namelist():                     # nada pode sair da pasta (zip adulterado)
                if not (temporaria / nome).resolve().is_relative_to(raiz):
                    raise ErroTraducaoLocal("o pacote do modelo de tradução está estranho")
            z.extractall(temporaria)
        shutil.rmtree(destino, ignore_errors=True)
        temporaria.replace(destino)
    except ErroTraducaoLocal:
        raise
    except Exception as erro:
        raise ErroTraducaoLocal(f"não deu para baixar o modelo de tradução {de}->{para} ({type(erro).__name__}: "
                                f"{str(erro)[:120]})") from erro
    finally:
        parcial.unlink(missing_ok=True)
    pronto = _pasta_do_modelo(destino)
    if pronto is None:
        raise ErroTraducaoLocal(f"o modelo de tradução {de}->{para} veio incompleto")
    return pronto


def _pasta_do_modelo(destino: Path) -> Path | None:
    if not destino.is_dir():
        return None
    for meta in [destino / "metadata.json", *destino.glob("*/metadata.json")]:
        base = meta.parent
        if meta.is_file() and (base / "model").is_dir() and (base / "sentencepiece.model").is_file():
            return base
    return None


# ----------------------------------------------------------------- traduzir
class ModeloArgos:
    """Um par de idiomas carregado (CTranslate2 + SentencePiece)."""

    def __init__(self, pasta: Path, threads: int = 0):
        try:
            import ctranslate2
            import sentencepiece
        except ImportError as erro:
            raise ErroTraducaoLocal("falta a biblioteca da tradução local (pip install ctranslate2 sentencepiece)") \
                from erro
        pasta = Path(pasta)
        try:
            meta = json.loads((pasta / "metadata.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            meta = {}
        self.prefixo = str(meta.get("target_prefix") or "")
        self.tradutor = ctranslate2.Translator(str(pasta / "model"), device="cpu", compute_type="int8",
                                               inter_threads=1, intra_threads=threads)
        self.pecas = sentencepiece.SentencePieceProcessor(model_file=str(pasta / "sentencepiece.model"))

    def traduzir(self, textos: list[str]) -> list[str]:
        if not textos:
            return []
        tokens = [self.pecas.encode(t, out_type=str) for t in textos]
        prefixos = [[self.prefixo]] * len(tokens) if self.prefixo else None
        resultados = self.tradutor.translate_batch(tokens, target_prefix=prefixos, beam_size=4, max_batch_size=LOTE,
                                                   replace_unknowns=True, length_penalty=0.2)
        saida = []
        for r in resultados:
            pedacos = r.hypotheses[0][1:] if self.prefixo else r.hypotheses[0]
            saida.append(self.pecas.decode(pedacos).strip())
        return saida


def _quebrar(texto: str) -> tuple[list[str], bool, bool]:
    """A fala da legenda em pedaços para traduzir: (frases, era itálico, era diálogo '- Oi.\\n- Olá.')."""
    italico = _ITALICO.match(texto)
    corpo = italico.group(1) if italico else texto
    corpo = re.sub(r"</?[^>]+>", "", corpo)               # outras marcas (<b>, <font>) saem
    linhas = [l.strip() for l in corpo.splitlines() if l.strip()]
    if len(linhas) > 1 and all(l.startswith("-") for l in linhas):
        return [l.lstrip("- ").strip() for l in linhas], bool(italico), True
    return [" ".join(linhas)], bool(italico), False


def _juntar(partes: list[str], italico: bool, dialogo: bool) -> str:
    texto = "\n".join(f"- {p}" for p in partes) if dialogo else (partes[0] if partes else "")
    return f"<i>{texto}</i>" if italico and texto else texto


class TradutorLocal:
    """O mesmo jeito de usar do Tradutor (Claude): traduzir_falas(textos, titulo, parar, ao_progresso). Custo zero.
    idioma_origem: de onde traduzir (traduzir_arquivo põe o do nome do arquivo: 'Filme.en.srt' -> 'en')."""

    modelo = "local (Argos Translate, no PC)"
    custo = 0.0
    tokens_entrada = tokens_saida = 0
    fator_preco = 1.0

    def __init__(self, pasta: Path, idioma: str = "pt-BR", idioma_origem: str = "en", obter=_obter,
                 carregar=ModeloArgos, ao_baixar=None):
        self.pasta, self.idioma, self.idioma_origem = Path(pasta), idioma, idioma_origem
        self._obter, self._carregar, self._ao_baixar = obter, carregar, ao_baixar
        self._modelos: dict[tuple[str, str], object] = {}
        self.pedidos = 0

    def conferir_teto(self) -> None:                       # local: não gasta
        pass

    def contar(self, resposta) -> None:
        pass

    def _modelo(self, par: tuple[str, str]):
        if par not in self._modelos:
            pasta = preparar_par(*par, self.pasta, self._obter, self._ao_baixar)
            self._modelos[par] = self._carregar(pasta)
        return self._modelos[par]

    def _rota(self) -> list[tuple[str, str]]:
        pares = {(p.get("from_code"), p.get("to_code")) for p in indice(self.pasta, self._obter)}
        return rota(pares, self.idioma_origem or "en", self.idioma)

    def traduzir_falas(self, textos: list[str], titulo: str = "", parar=None, ao_progresso=None) -> list[str]:
        from .traducao import ErroTraducao
        try:
            etapas = self._rota()
            resultado = list(textos)
            quebradas = [(_quebrar(t) if t.strip() else ([], False, False)) for t in textos]
            frases = [(i, f) for i, (partes, _, _) in enumerate(quebradas) for f in partes]
            traduzidas = [f for _, f in frases]
            feitos = 0
            for inicio in range(0, len(traduzidas), LOTE):
                if parar and parar():
                    raise ErroTraducao("interrompido")
                lote = traduzidas[inicio:inicio + LOTE]
                for par in etapas:
                    lote = self._modelo(par).traduzir(lote)
                traduzidas[inicio:inicio + LOTE] = lote
                self.pedidos += 1
                feitos = min(len(traduzidas), inicio + LOTE)
                if ao_progresso:
                    ao_progresso(feitos, len(traduzidas))
        except ErroTraducaoLocal as erro:
            raise ErroTraducao(str(erro)) from erro
        por_fala: dict[int, list[str]] = {}
        for (i, _), traduzida in zip(frases, traduzidas):
            por_fala.setdefault(i, []).append(traduzida)
        for i, (partes, italico, dialogo) in enumerate(quebradas):
            if partes:
                resultado[i] = _juntar(por_fala.get(i, []), italico, dialogo)
        return resultado
