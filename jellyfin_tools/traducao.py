"""Traduzir legendas (.srt) com o Claude, pela API da Anthropic.

Para que serve: o filme ou episódio só tem legenda em outro idioma (ex.: 'Filme.en.srt') e nenhuma em português.
O programa manda à IA SÓ O TEXTO de cada fala, numerado, e remonta o .srt com os MESMOS horários da original:

    Filme (2003).en.srt  ->  Filme (2003).pt-BR.srt      (a original continua lá; nada é sobrescrito)

Por que só o texto: os horários nunca passam pela IA, então não tem como ela "desalinhar" a legenda. A resposta vem
num formato fixo (saída estruturada em JSON: [{id, texto}]) e o programa confere se TODA fala voltou com o mesmo id.

As falas vão em lotes (LINHAS_POR_PEDIDO), com as últimas falas do lote anterior como contexto (quem fala com quem,
"you" = você ou vocês). A chave de API vem da tela (ou da variável ANTHROPIC_API_KEY); o modelo padrão é
MODELO_PADRAO e pode ser trocado na tela.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .legendas import ErroLegenda, extrair_srt, nome_do_idioma
from .nomes import eh_video_da_biblioteca

MODELO_PADRAO = "claude-sonnet-4-6"
LINHAS_POR_PEDIDO = 100        # falas por pedido à API (a resposta cabe com folga no limite de saída)
CONTEXTO_ANTERIOR = 6          # falas já traduzidas que vão junto, só para dar contexto
MAX_TOKENS = 16000

# US$ por milhão de tokens (entrada, saída), para a ESTIMATIVA mostrada antes de traduzir
PRECOS = {
    "claude-sonnet-4-6": (3.0, 15.0), "claude-sonnet-5-5": (2.0, 10.0), "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50), "claude-haiku-4-5": (1.0, 5.0), "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0), "claude-opus-4-8": (5.0, 25.0), "claude-opus-4-7": (5.0, 25.0),
    "claude-opus-4-6": (5.0, 25.0),
}

# idiomas da legenda de ORIGEM, na ordem de preferência (o nome do arquivo diz: 'Filme.en.srt')
ORIGENS_PREFERIDAS = ("en", "eng", "en-us", "en-gb", "es", "spa", "es-419", "fr", "fre", "it", "ita", "de", "ger")
_PORTUGUES = {"pt", "pt-br", "pt-pt", "por", "pob", "pb", "ptbr"}

_SISTEMA = """Você é um tradutor profissional de legendas de filmes e séries.
Regras:
- Traduza cada fala para {idioma}, com a linguagem natural de legenda (frases curtas, fáceis de ler rápido).
- No máximo 42 letras por linha e 2 linhas por fala: se a tradução ficar longa, enxugue sem perder o sentido.
- Devolva TODAS as falas recebidas, cada uma com o MESMO id. Não junte, não divida e não pule falas.
- Mantenha as quebras de linha dentro de cada fala e as marcas de formatação como <i>, </i>, <b>, {{\\an8}}.
- Nomes de pessoas, lugares e marcas não se traduzem.
- Use o contexto (título e falas anteriores) para escolher "você" ou "vocês", gênero e tom.
- Não acrescente comentários, notas nem explicações."""

_ESQUEMA = {
    "type": "object",
    "properties": {
        "falas": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "integer"}, "texto": {"type": "string"}},
                "required": ["id", "texto"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["falas"],
    "additionalProperties": False,
}


class ErroTraducao(Exception):
    pass


# ----------------------------------------------------------------- o arquivo .srt
@dataclass
class Fala:
    tempo: str                 # "00:00:01,000 --> 00:00:03,500" (nunca passa pela IA)
    texto: str


_RE_TEMPO = re.compile(r"\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}\s*-->\s*\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}")


def ler_srt(texto: str) -> list[Fala]:
    """As falas de um .srt (o número de cada bloco é refeito na gravação)."""
    texto = texto.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n").strip()
    falas = []
    for bloco in re.split(r"\n[ \t]*\n", texto):
        linhas = bloco.split("\n")
        posicao = next((k for k, linha in enumerate(linhas) if _RE_TEMPO.search(linha)), None)
        if posicao is not None:
            falas.append(Fala(linhas[posicao].strip(), "\n".join(linhas[posicao + 1:]).strip()))
    return falas


def gerar_srt(falas: list[Fala]) -> str:
    return "\n\n".join(f"{n}\n{f.tempo}\n{f.texto}" for n, f in enumerate(falas, 1)) + "\n"


MAX_LINHA = 42                 # letras por linha de legenda (o padrão de legendagem)
_RE_MARCA = re.compile(r"<[^>]+>|\{[^}]*\}")


def quebrar_linhas(texto: str, max_linha: int = MAX_LINHA) -> str:
    """Texto longo vira 2 linhas equilibradas, cortando num espaço perto do meio."""
    texto = " ".join(texto.split())
    if len(_RE_MARCA.sub("", texto)) <= max_linha:
        return texto
    meio = len(texto) // 2
    espacos = [i for i, c in enumerate(texto) if c == " "]
    if not espacos:
        return texto
    corte = min(espacos, key=lambda i: abs(i - meio))
    return texto[:corte] + "\n" + texto[corte + 1:]


def ajustar_linhas(texto: str, max_linha: int = MAX_LINHA) -> str:
    """Revisão da legenda traduzida: linha com mais de 42 letras (sem contar <i> etc.) é redistribuída em 2 linhas
    equilibradas. Fala de diálogo ('- Oi.\n- Olá.') e falas que já cabem ficam como estão."""
    linhas = texto.split("\n")
    if all(len(_RE_MARCA.sub("", l)) <= max_linha for l in linhas):
        return texto
    if len(linhas) > 1 and all(l.lstrip(" <i>").startswith("-") for l in linhas):
        return texto                                   # diálogo: cada pessoa na sua linha
    return quebrar_linhas(" ".join(linhas), max_linha)


def parece_portugues(texto: str) -> bool:
    """Para a legenda sem idioma no nome ('Filme.srt'): já está em português? (palavras muito comuns)"""
    palavras = re.findall(r"[a-zà-ú]+", texto.lower())
    if not palavras:
        return False
    comuns = {"não", "você", "está", "então", "também", "isso", "aqui", "agora", "obrigado", "vamos", "já"}
    return sum(p in comuns for p in palavras) / len(palavras) > 0.02


# ----------------------------------------------------------------- o que traduzir na biblioteca
@dataclass
class Pendente:
    video: Path
    origem: Path               # a legenda em outro idioma
    destino: Path              # 'Nome.pt-BR.srt'
    caracteres: int = 0        # para a estimativa de custo
    falas: int = 0


def _idioma_no_nome(legenda: Path, video: Path) -> str:
    """'Filme.en.srt' -> 'en'; 'Filme.en.forced.srt' -> 'en.forced'; 'Filme.srt' -> ''."""
    resto = legenda.name[len(video.stem):]
    return resto[1:-len(legenda.suffix)].lower() if resto.startswith(".") and len(resto) > len(legenda.suffix) + 1 \
        else ""


def legendas_para_traduzir(*pastas, idioma: str = "pt-BR") -> list[Pendente]:
    """Os vídeos das bibliotecas que têm legenda .srt em OUTRO idioma e nenhuma no idioma pedido."""
    alvo = {idioma.lower()} | (_PORTUGUES if idioma.lower().startswith("pt") else set())
    pendentes, vistos = [], set()
    for pasta in pastas:
        if not pasta or not Path(pasta).is_dir():
            continue
        for video in sorted(Path(pasta).rglob("*")):
            if ".organizador" in video.parts or not video.is_file() or not eh_video_da_biblioteca(video):
                continue
            if (chave := str(video.resolve()).lower()) in vistos:
                continue
            vistos.add(chave)
            irmas = [a for a in video.parent.iterdir() if a.is_file() and a.name.startswith(video.stem + ".")
                     and a.suffix.lower() in (".srt", ".ass", ".ssa", ".vtt", ".sub")]
            idiomas = {a: _idioma_no_nome(a, video) for a in irmas}
            if any(cod.split(".")[0] in alvo for cod in idiomas.values()):
                continue                                           # já tem no idioma pedido
            candidatas = [a for a, cod in idiomas.items() if a.suffix.lower() == ".srt" and "forced" not in cod]
            if not candidatas:
                continue

            def ordem(legenda: Path) -> tuple:
                cod = idiomas[legenda].split(".")[0]
                return (ORIGENS_PREFERIDAS.index(cod) if cod in ORIGENS_PREFERIDAS else len(ORIGENS_PREFERIDAS)
                        + (1 if not cod else 0), legenda.name)
            for origem in sorted(candidatas, key=ordem):
                try:
                    texto = extrair_srt(origem.read_bytes())
                except (OSError, ErroLegenda):
                    continue
                if not idiomas[origem] and parece_portugues(texto):
                    break                                          # 'Filme.srt' já em português: nada a fazer
                falas = ler_srt(texto)
                if falas:
                    pendentes.append(Pendente(video, origem, video.with_name(f"{video.stem}.{idioma}.srt"),
                                              sum(len(f.texto) for f in falas), len(falas)))
                    break
    return pendentes


def estimar_custo(caracteres: int, falas: int, modelo: str) -> tuple[int, int, float | None]:
    """(tokens de entrada, tokens de saída, US$ ou None se o preço do modelo não é conhecido). Estimativa."""
    pedidos = max(1, -(-falas // LINHAS_POR_PEDIDO))
    entrada = int(caracteres / 3.5 + falas * 8 + pedidos * 450)
    saida = int(caracteres / 3.2 + falas * 10)
    preco = PRECOS.get(modelo)
    return entrada, saida, (entrada * preco[0] + saida * preco[1]) / 1_000_000 if preco else None


# ----------------------------------------------------------------- a tradução
def _explicar(erro: Exception) -> str:
    """O erro do SDK da Anthropic em português (pelo nome da classe: o SDK só é importado quando usado)."""
    nome = type(erro).__name__
    return {"AuthenticationError": "a chave de API foi recusada (confira em console.anthropic.com)",
            "PermissionDeniedError": "a chave de API não tem permissão para esse modelo",
            "NotFoundError": "modelo não encontrado: confira o nome do modelo",
            "RateLimitError": "limite de uso da API atingido; tente mais tarde",
            "APIConnectionError": "sem conexão com a API da Anthropic",
            "APITimeoutError": "a API demorou demais para responder",
            "OverloadedError": "a API está sobrecarregada; tente mais tarde"}.get(nome, f"{nome}: {erro}")[:300]


@dataclass
class Tradutor:
    chave: str = ""
    modelo: str = MODELO_PADRAO
    idioma: str = "pt-BR"
    cliente: object = None     # anthropic.Anthropic (ou um falso nos testes)
    tokens_entrada: int = 0
    tokens_saida: int = 0
    pedidos: int = 0
    _sistema: str = field(default="", repr=False)

    def __post_init__(self):
        self.modelo = (self.modelo or MODELO_PADRAO).strip()
        if self.cliente is None:
            import anthropic                                         # só quando for traduzir de verdade
            # sem chave na tela, o SDK usa a variável ANTHROPIC_API_KEY (ou o login do 'ant')
            self.cliente = anthropic.Anthropic(api_key=self.chave or None, max_retries=4)
        self._sistema = _SISTEMA.format(idioma=nome_do_idioma(self.idioma))

    @property
    def custo(self) -> float | None:
        preco = PRECOS.get(self.modelo)
        return (self.tokens_entrada * preco[0] + self.tokens_saida * preco[1]) / 1_000_000 if preco else None

    def traduzir_falas(self, textos: list[str], titulo: str = "", parar=None, ao_progresso=None) -> list[str]:
        """Os textos traduzidos, na mesma ordem. Falas vazias continuam vazias (não vão para a API)."""
        resultado = list(textos)
        a_traduzir = [i for i, t in enumerate(textos) if t.strip()]
        feitos = 0
        for inicio in range(0, len(a_traduzir), LINHAS_POR_PEDIDO):
            if parar and parar():
                raise ErroTraducao("interrompido")
            lote = a_traduzir[inicio:inicio + LINHAS_POR_PEDIDO]
            anteriores = [resultado[i] for i in a_traduzir[max(0, inicio - CONTEXTO_ANTERIOR):inicio]]
            for i, texto in self._traduzir_lote({i: textos[i] for i in lote}, titulo, anteriores).items():
                resultado[i] = texto
            feitos += len(lote)
            if ao_progresso:
                ao_progresso(feitos, len(a_traduzir))
        return resultado

    def _traduzir_lote(self, lote: dict[int, str], titulo: str, anteriores: list[str],
                       tentativa: int = 1) -> dict[int, str]:
        falas = [{"id": i, "texto": t} for i, t in lote.items()]
        contexto = ("Falas anteriores, já traduzidas (só contexto, não devolva):\n" + "\n".join(anteriores) + "\n\n"
                    if anteriores else "")
        pedido = (f"Título: {titulo or '(desconhecido)'}\n\n{contexto}"
                  f"Traduza para {nome_do_idioma(self.idioma)} e devolva cada fala com o mesmo id.\n"
                  f"Falas:\n{json.dumps(falas, ensure_ascii=False)}")
        try:
            resposta = self.cliente.messages.create(
                model=self.modelo, max_tokens=MAX_TOKENS, system=self._sistema,
                messages=[{"role": "user", "content": pedido}],
                output_config={"format": {"type": "json_schema", "schema": _ESQUEMA}})
        except Exception as erro:                    # erros do SDK (chave, conexão, limite...) em português
            raise ErroTraducao(_explicar(erro)) from erro
        self.pedidos += 1
        uso = getattr(resposta, "usage", None)
        self.tokens_entrada += getattr(uso, "input_tokens", 0) or 0
        self.tokens_saida += getattr(uso, "output_tokens", 0) or 0
        if resposta.stop_reason == "refusal":
            raise ErroTraducao("o modelo recusou traduzir um trecho desta legenda")
        if resposta.stop_reason == "max_tokens":                     # não coube: divide o lote ao meio
            if len(lote) == 1:
                raise ErroTraducao("uma fala é longa demais para traduzir")
            itens = list(lote.items())
            metade = len(itens) // 2
            return {**self._traduzir_lote(dict(itens[:metade]), titulo, anteriores),
                    **self._traduzir_lote(dict(itens[metade:]), titulo, anteriores)}
        try:
            texto = next(b.text for b in resposta.content if getattr(b, "type", "") == "text")
            traduzidas = {int(f["id"]): str(f["texto"]) for f in json.loads(texto)["falas"]}
        except (StopIteration, ValueError, KeyError, TypeError) as erro:
            raise ErroTraducao("a resposta da IA veio num formato inesperado") from erro
        faltando = {i: t for i, t in lote.items() if i not in traduzidas}
        if faltando:                                                 # alguma fala não voltou: pede de novo só ela
            if tentativa >= 2:
                raise ErroTraducao(f"{len(faltando)} fala(s) não voltaram traduzidas")
            traduzidas.update(self._traduzir_lote(faltando, titulo, anteriores, tentativa + 1))
        return {i: traduzidas[i] for i in lote}


@dataclass
class ResultadoTraducao:
    origem: Path
    destino: Path
    status: str                # traduzida | ja_existe | erro
    detalhe: str = ""
    falas: int = 0


def traduzir_arquivo(origem: str | Path, destino: str | Path, tradutor: Tradutor, titulo: str = "",
                     parar=None, ao_progresso=None) -> ResultadoTraducao:
    """Traduz 'origem' e grava 'destino' (com os mesmos horários). Nunca sobrescreve um arquivo que já existe."""
    origem, destino = Path(origem), Path(destino)
    if destino.exists():
        return ResultadoTraducao(origem, destino, "ja_existe", "a legenda traduzida já existe")
    try:
        falas = ler_srt(extrair_srt(origem.read_bytes()))
    except (OSError, ErroLegenda) as erro:
        return ResultadoTraducao(origem, destino, "erro", f"não deu para ler a legenda: {erro}")
    if not falas:
        return ResultadoTraducao(origem, destino, "erro", "a legenda não tem nenhuma fala")
    try:
        textos = tradutor.traduzir_falas([f.texto for f in falas], titulo or origem.stem, parar, ao_progresso)
        textos = [ajustar_linhas(t) for t in textos]                 # revisão: no máximo 42 letras por linha
    except ErroTraducao as erro:
        return ResultadoTraducao(origem, destino, "erro", str(erro), len(falas))
    parcial = destino.with_name(destino.name + ".part")
    try:
        parcial.write_text(gerar_srt([Fala(f.tempo, t) for f, t in zip(falas, textos)]), encoding="utf-8")
        parcial.replace(destino)
    except OSError as erro:
        parcial.unlink(missing_ok=True)
        return ResultadoTraducao(origem, destino, "erro", f"não deu para gravar: {erro}", len(falas))
    return ResultadoTraducao(origem, destino, "traduzida", "", len(falas))
