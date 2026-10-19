"""O ROTEIRO de um jogo (os textos tirados de dentro dele: menus, itens, legendas e falas), traduzido sem quebrar o
jogo. É o passo 2 do modo "Traduzir e dublar (no PC)" da aba 🎮 Jogos.

Entra o arquivo que a ferramenta do jogo (ou da comunidade) exporta:
    .csv / .tsv / .txt com colunas   com cabeçalho (id, texto, audio, personagem, limite...) ou sem (id;texto)
    .txt                             uma fala por linha
    .json                            {"id": "texto"} ou [{"id": ..., "text": ...}]
e sai o roteiro_ptbr com AS MESMAS colunas, a mesma ordem, o mesmo separador e a mesma codificação, só com o texto
traduzido: a ferramenta do jogo põe de volta sem estranhar.

Três cuidados que o jogo exige (e o Maestro confere fala por fala):
    códigos especiais   {NAME}, <br>, [cor]...[/cor], %s, \\n: o jogo usa na hora de mostrar. Viram marcas ⟦1⟧, ⟦2⟧
                        antes da tradução e voltam no mesmo lugar; a fala em que um código não voltou fica marcada
                        para revisão (com o código no fim, para o jogo não quebrar)
    espaço máximo       a coluna "limite" (ou "max"): a tradução não pode passar (o português costuma ser ~25% maior
                        que o inglês). O Claude encurta; o que ainda passar fica marcado
    letras da fonte     muitos jogos de PS2 não têm ç, ã, é na fonte: "sem acentos" troca por c, a, e

A mesma frase tem sempre a mesma tradução (traduz uma vez só: mais barato e o jogo fica coerente), e o glossário
guarda os nomes que não se traduzem (personagens, lugares, golpes).
"""

from __future__ import annotations

import csv
import io
import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from .traducao import (_ESQUEMA, LINHAS_POR_PEDIDO, MAX_TOKENS, ErroTraducao, Tradutor, _explicar, ler_resposta,
                       nome_do_idioma)

EXTENSOES_ROTEIRO = (".csv", ".tsv", ".txt", ".json")
# os códigos do jogo: {NAME} {0}, <br> <color=...> </i>, [cor] [/cor] (sem espaço dentro: "[Press X]" é texto),
# %s %d %1$s %.2f, \n \r \t escritos com a barra, ~r~ (cores de alguns jogos)
CODIGOS = re.compile(r"\{[^{}\s]{1,32}\}|</?[A-Za-z][^<>\n]{0,38}>|<br\s*/?>|\[/?[^\[\]\s]{1,24}\]"
                     r"|%(?:\d+\$)?[-+ #0]*\d*(?:\.\d+)?[sdifuxXcp%]|\\[nrt]|~[A-Za-z0-9]{1,3}~")
MARCA = "⟦{}⟧"
_MARCAS = re.compile(r"⟦\s*(\d+)\s*⟧")
SEPARADORES = ",;\t|"
COLUNAS = {          # os nomes de coluna que cada ferramenta usa (sem acento, sem espaço, minúsculos)
    "id": ("id", "chave", "key", "label", "stringid", "index", "indice", "codigo", "hash", "entry", "linha", "line",
           "nomeid", "textid", "msgid"),
    "texto": ("texto", "text", "original", "english", "ingles", "en", "source", "string", "fonte", "origem",
              "textooriginal", "sourcetext", "msgstr", "dialogo", "dialogue", "fala"),
    "traducao": ("traducao", "translation", "portugues", "pt", "ptbr", "target", "traduzido", "destino",
                 "translated"),
    "audio": ("audio", "arquivo", "file", "wav", "som", "voice", "sound", "audiofile", "arquivodeaudio", "vag",
              "filename", "voicefile"),
    "personagem": ("personagem", "speaker", "character", "ator", "quem", "falante", "char", "actor", "name",
                   "nome"),
    "limite": ("limite", "max", "maxlen", "maxlength", "maximo", "tamanho", "size", "bytes", "maxchars", "limit",
               "espaco"),
}


class ErroRoteiro(ErroTraducao):
    pass


@dataclass
class Entrada:
    """Uma fala, item ou texto de menu do roteiro."""
    numero: int                      # a posição no roteiro (0, 1, 2...)
    chave: str                       # o id (ou o número da linha, sem coluna de id)
    texto: str                       # o original
    traducao: str = ""
    audio: str = ""                  # o arquivo de som da fala (se o roteiro diz)
    personagem: str = ""
    limite: int | None = None        # o espaço máximo (letras), se o roteiro diz
    avisos: list = field(default_factory=list)   # o que conferir ("passou do limite", "faltou {NAME}")
    longa: str = ""                  # a 1ª tradução, que não cabia (a usada é a sugestão do Claude, mais curta)

    def espaco(self) -> str:
        """'✓ 14 de 16', '⚠ 21 de 16' ou '14 letras' (sem limite no roteiro), da tradução usada."""
        n = len(self.traducao)
        if not self.traducao:
            return ""
        if not self.limite:
            return f"{n} letras"
        return f"{'✓' if n <= self.limite else '⚠'} {n} de {self.limite}"


@dataclass
class Roteiro:
    arquivo: Path
    tipo: str                        # "csv", "txt" ou "json"
    entradas: list = field(default_factory=list)
    codificacao: str = "utf-8"
    bom: bool = False
    fim_de_linha: str = "\n"
    separador: str = ","
    cabecalho: list | None = None    # as colunas (None: sem cabeçalho)
    linhas: list = field(default_factory=list)   # as linhas da planilha, como vieram (para gravar igual)
    colunas: dict = field(default_factory=dict)  # {"texto": 1, "id": 0, ...}: onde está cada coisa
    json_original: object = None

    @property
    def com_texto(self) -> list:
        return [e for e in self.entradas if e.texto.strip()]

    def letras(self) -> int:
        return sum(len(e.texto) for e in self.entradas)

    def codigos_achados(self, maximo: int = 6) -> list[str]:
        """Os códigos especiais mais comuns ("{NAME}", "<br>", "[cor]"), para mostrar na tela."""
        contagem: dict[str, int] = {}
        for e in self.entradas:
            for codigo in CODIGOS.findall(e.texto):
                forma = re.sub(r"^\[/", "[", re.sub(r"^</", "<", codigo))     # [cor] e [/cor] contam juntos
                contagem[forma] = contagem.get(forma, 0) + 1
        return [c for c, _ in sorted(contagem.items(), key=lambda x: -x[1])[:maximo]]

    def com_limite(self) -> int:
        return sum(1 for e in self.entradas if e.limite)

    def traduzidas(self) -> int:
        return sum(1 for e in self.com_texto if e.traducao.strip())

    def ajustes(self) -> int:
        return sum(1 for e in self.entradas if e.avisos)

    def descrever(self) -> str:
        partes = [f"{self.arquivo.name}", f"{len(self.com_texto)} textos", f"{self.letras() / 1000:.0f} mil letras"
                  if self.letras() >= 1000 else f"{self.letras()} letras"]
        codigos = self.codigos_achados()
        if codigos:
            partes.append("códigos especiais: " + " ".join(codigos))
        return " · ".join(partes)


# ----------------------------------------------------------------- ler e gravar
def _normal(nome: str) -> str:
    sem = unicodedata.normalize("NFKD", str(nome)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", sem.lower())


def _decodificar(dados: bytes) -> tuple[str, str, bool]:
    """(texto, codificação, tinha BOM): UTF-8 (com ou sem BOM), UTF-16 (com BOM) ou Windows-1252."""
    if dados[:3] == b"\xef\xbb\xbf":
        return dados[3:].decode("utf-8"), "utf-8", True
    if dados[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return dados.decode("utf-16"), "utf-16", True
    try:
        return dados.decode("utf-8"), "utf-8", False
    except UnicodeDecodeError:
        return dados.decode("cp1252", errors="replace"), "cp1252", False


def _achar_colunas(cabecalho: list[str]) -> dict[str, int]:
    nomes = [_normal(c) for c in cabecalho]
    achadas: dict[str, int] = {}
    for papel, opcoes in COLUNAS.items():
        for opcao in opcoes:                          # na ordem de preferência ("texto" antes de "string")
            if opcao in nomes and nomes.index(opcao) not in achadas.values():
                achadas[papel] = nomes.index(opcao)
                break
    return achadas


def _limite(valor: str) -> int | None:
    try:
        n = int(float(str(valor).strip()))
    except ValueError:
        return None
    return n if n > 0 else None


def ler_roteiro(arquivo: str | Path) -> Roteiro:
    """O roteiro exportado do jogo. ErroRoteiro se não dá para ler (ou não tem texto)."""
    arquivo = Path(arquivo)
    if not arquivo.is_file():
        raise ErroRoteiro(f"não achei o roteiro: {arquivo}")
    texto, codificacao, bom = _decodificar(arquivo.read_bytes())
    fim = "\r\n" if "\r\n" in texto[:20000] else "\n"
    extensao = arquivo.suffix.lower()
    if extensao == ".json":
        roteiro = _ler_json(arquivo, texto)
    else:
        roteiro = _ler_planilha(arquivo, texto, extensao)
    roteiro.codificacao, roteiro.bom, roteiro.fim_de_linha = codificacao, bom, fim
    if not roteiro.com_texto:
        raise ErroRoteiro(f"{arquivo.name}: não achei nenhum texto para traduzir")
    return roteiro


def _separador(linhas: list[str], padrao: str = "") -> str:
    """O separador das colunas: o que aparece O MESMO número de vezes em quase todas as linhas (num .txt de frases,
    as vírgulas variam de linha para linha: não é planilha)."""
    amostra = [linha for linha in linhas[:300] if linha.strip()]
    melhor, nota = padrao, 0.0
    for s in SEPARADORES:
        contagens = [linha.count(s) for linha in amostra]
        if not contagens or max(contagens) == 0:
            continue
        moda = max(set(contagens), key=contagens.count)
        constancia = sum(1 for c in contagens if c == moda) / len(contagens)
        if moda > 0 and constancia >= 0.8 and constancia > nota:
            melhor, nota = s, constancia
    return melhor


def _ler_planilha(arquivo: Path, texto: str, extensao: str) -> Roteiro:
    linhas_brutas = texto.splitlines()
    separador = "\t" if extensao == ".tsv" else _separador(linhas_brutas, padrao="," if extensao == ".csv" else "")
    if not separador:                                   # .txt: uma fala por linha
        roteiro = Roteiro(arquivo, "txt", linhas=linhas_brutas)
        roteiro.entradas = [Entrada(i, str(i + 1), linha) for i, linha in enumerate(linhas_brutas)]
        return roteiro
    try:
        linhas = list(csv.reader(io.StringIO(texto), delimiter=separador))
    except csv.Error as erro:
        raise ErroRoteiro(f"{arquivo.name}: planilha que o Maestro não lê ({erro})") from erro
    linhas = [linha for linha in linhas if linha]
    if not linhas:
        raise ErroRoteiro(f"{arquivo.name}: vazio")
    colunas = _achar_colunas(linhas[0])
    cabecalho = None
    if "texto" in colunas:
        cabecalho, corpo = linhas[0], linhas[1:]
    else:                                               # sem cabeçalho: id;texto, ou o texto é a coluna mais longa
        corpo = linhas
        largura = max(len(linha) for linha in corpo)
        if largura == 1:
            colunas = {"texto": 0}
        else:
            media = [sum(len(linha[c]) for linha in corpo if c < len(linha)) for c in range(largura)]
            colunas = {"texto": max(range(largura), key=lambda c: media[c])}
            if colunas["texto"] != 0:
                colunas["id"] = 0
    roteiro = Roteiro(arquivo, "csv", separador=separador, cabecalho=cabecalho, linhas=corpo, colunas=colunas)

    def valor(linha, papel):
        c = colunas.get(papel)
        return linha[c] if c is not None and c < len(linha) else ""
    for i, linha in enumerate(corpo):
        roteiro.entradas.append(Entrada(i, valor(linha, "id") or str(i + 1), valor(linha, "texto"),
                                        traducao=valor(linha, "traducao"), audio=valor(linha, "audio").strip(),
                                        personagem=valor(linha, "personagem").strip(),
                                        limite=_limite(valor(linha, "limite"))))
    return roteiro


def _ler_json(arquivo: Path, texto: str) -> Roteiro:
    try:
        dados = json.loads(texto)
    except ValueError as erro:
        raise ErroRoteiro(f"{arquivo.name}: JSON que o Maestro não lê ({erro})") from erro
    roteiro = Roteiro(arquivo, "json", json_original=dados)
    if isinstance(dados, dict):
        for i, (chave, valor) in enumerate(dados.items()):
            if isinstance(valor, str):
                roteiro.entradas.append(Entrada(i, str(chave), valor))
    elif isinstance(dados, list) and all(isinstance(x, dict) for x in dados):
        nomes = list(dict.fromkeys(k for x in dados for k in x))
        papel = {p: nomes[c] for p, c in _achar_colunas(nomes).items()}
        if "texto" not in papel:
            raise ErroRoteiro(f"{arquivo.name}: não achei o campo do texto (text, texto, original...)")
        roteiro.colunas = papel
        for i, x in enumerate(dados):
            roteiro.entradas.append(Entrada(i, str(x.get(papel.get("id", ""), i + 1)), str(x.get(papel["texto"], "")),
                                            audio=str(x.get(papel.get("audio", ""), "") or ""),
                                            personagem=str(x.get(papel.get("personagem", ""), "") or ""),
                                            limite=_limite(x.get(papel.get("limite", ""), ""))))
    else:
        raise ErroRoteiro(f"{arquivo.name}: o JSON precisa ser {{\"id\": \"texto\"}} ou uma lista de objetos")
    return roteiro


def gravar_roteiro(roteiro: Roteiro, destino: str | Path) -> Path:
    """O roteiro traduzido com as MESMAS colunas, separador, codificação e fim de linha (o que não tem tradução fica
    como estava). Com uma coluna de tradução no original, a tradução vai nela e o texto original fica."""
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    traducao = {e.numero: e.traducao for e in roteiro.entradas if e.traducao.strip()}
    if roteiro.tipo == "txt":
        texto = roteiro.fim_de_linha.join(traducao.get(i, linha) for i, linha in enumerate(roteiro.linhas))
        texto += roteiro.fim_de_linha
    elif roteiro.tipo == "json":
        dados = roteiro.json_original
        if isinstance(dados, dict):
            novo = {e.chave: traducao.get(e.numero, e.texto) for e in roteiro.entradas}
            dados = {k: novo.get(str(k), v) for k, v in dados.items()}
        else:
            campo = roteiro.colunas.get("traducao") or roteiro.colunas["texto"]
            dados = [dict(x, **({campo: traducao[i]} if i in traducao else {})) for i, x in enumerate(dados)]
        texto = json.dumps(dados, ensure_ascii=False, indent=2) + roteiro.fim_de_linha
    else:
        coluna = roteiro.colunas.get("traducao", roteiro.colunas["texto"])
        saida = io.StringIO()
        escritor = csv.writer(saida, delimiter=roteiro.separador, lineterminator=roteiro.fim_de_linha)
        if roteiro.cabecalho is not None:
            escritor.writerow(roteiro.cabecalho)
        for i, linha in enumerate(roteiro.linhas):
            linha = list(linha)
            if i in traducao:
                linha += [""] * (coluna + 1 - len(linha))
                linha[coluna] = traducao[i]
            escritor.writerow(linha)
        texto = saida.getvalue()
    dados = texto.encode(roteiro.codificacao, errors="replace")
    if roteiro.bom and roteiro.codificacao == "utf-8":
        dados = b"\xef\xbb\xbf" + dados
    destino.write_bytes(dados)
    return destino


# ----------------------------------------------------------------- os códigos, o espaço e as letras
def proteger(texto: str, glossario: tuple = ()) -> tuple[str, list[str]]:
    """'Thanks, {NAME}.<br>The forest...' -> ('Thanks, ⟦1⟧.⟦2⟧The forest...', ['{NAME}', '<br>']). Os nomes do
    glossário viram marca também (voltam iguais)."""
    pecas: list[str] = []

    def marcar(achado):
        pecas.append(achado.group(0))
        return MARCA.format(len(pecas))
    texto = CODIGOS.sub(marcar, texto)
    for nome in sorted((n for n in glossario if n.strip()), key=len, reverse=True):
        texto = re.sub(rf"(?<![\w⟦]){re.escape(nome)}(?![\w⟧])", marcar, texto)
    return texto, pecas


def restaurar(texto: str, pecas: list[str]) -> tuple[str, list[str]]:
    """As marcas de volta aos códigos. (texto, códigos que não voltaram): os que faltaram vão para o fim (o jogo não
    quebra sem o código de fechar uma cor) e a fala fica marcada para revisão."""
    usadas: set[int] = set()

    def trocar(achado):
        n = int(achado.group(1))
        if 1 <= n <= len(pecas) and n not in usadas:
            usadas.add(n)
            return pecas[n - 1]
        return ""
    texto = _MARCAS.sub(trocar, texto)
    faltaram = [p for n, p in enumerate(pecas, 1) if n not in usadas and not _eh_nome(p)]
    nomes_faltando = [p for n, p in enumerate(pecas, 1) if n not in usadas and _eh_nome(p)]
    if faltaram:
        texto = texto.rstrip() + "".join(faltaram)
    return re.sub(r"[ \t]{2,}", " ", texto).strip(), faltaram + nomes_faltando


def _eh_nome(peca: str) -> bool:
    return not CODIGOS.fullmatch(peca)


def sem_acentos(texto: str) -> str:
    """'Ação é útil' -> 'Acao e util' (para a fonte do jogo que não tem as letras com acento)."""
    trocas = {"º": "o", "ª": "a", "«": '"', "»": '"', "–": "-", "—": "-", "…": "...", "“": '"', "”": '"', "‘": "'",
              "’": "'"}
    texto = "".join(trocas.get(c, c) for c in texto)
    return "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))


def para_falar(texto: str) -> str:
    """O texto sem os códigos do jogo, para a voz ler ('Obrigado, {NAME}.<br>A floresta' -> 'Obrigado. A floresta')."""
    texto = re.sub(r"\\[nrt]|<br\s*/?>", " ", texto)
    texto = CODIGOS.sub("", texto)
    texto = re.sub(r"\s+([,.!?;:])", r"\1", re.sub(r",\s*([.!?])", r"\1", texto))
    return re.sub(r"\s{2,}", " ", texto).strip()


# ----------------------------------------------------------------- traduzir
_SISTEMA_JOGO = """Você é um tradutor profissional de jogos (localização) para {idioma}.
Regras:
- Traduza cada texto (menu, botão, item, legenda ou fala) com a linguagem natural de jogo em {idioma}.
- As marcas ⟦1⟧, ⟦2⟧... são códigos do jogo (nomes, cores, quebras de linha) ou nomes que não se traduzem: \
mantenha TODAS, exatamente iguais, no lugar certo da frase traduzida. Não traduza, não junte e não apague as marcas.
- Quando o texto vier com "max", a tradução deve ter no máximo esse número de letras (cada marca conta como as \
letras dela): enxugue sem perder o sentido; em menus e itens, use a forma curta dos jogos.
- Devolva TODOS os textos recebidos, cada um com o MESMO id. Não junte, não divida e não pule.
- Nomes próprios (personagens, lugares, golpes, marcas) não se traduzem, a não ser que tenham nome oficial em \
{idioma}.
- Menus e botões no jeito usual dos jogos ("Continuar", "Salvar o jogo?", "Pressione Start").
- Não acrescente comentários, notas nem explicações."""

_ENCURTAR = ("Estas traduções passaram do espaço máximo do jogo. Reescreva cada uma com no máximo \"max\" letras, "
             "mantendo TODAS as marcas ⟦n⟧ e o sentido (abrevie como os jogos fazem). Devolva cada uma com o mesmo "
             "id.")


@dataclass
class TradutorJogo(Tradutor):
    """O tradutor do Claude com as regras de jogo: as marcas dos códigos e o espaço máximo de cada texto."""
    limites: dict = field(default_factory=dict)        # {posição: letras no máximo} (do lote em curso)

    def __post_init__(self):
        super().__post_init__()
        self._sistema = _SISTEMA_JOGO.format(idioma=nome_do_idioma(self.idioma))

    def parametros(self, lote: dict[int, str], titulo: str, anteriores: list[str], rotulo_contexto: str = "") -> dict:
        p = super().parametros(lote, titulo, anteriores, rotulo_contexto)
        falas = [{"id": i, "texto": t, **({"max": self.limites[i]} if self.limites.get(i) else {})}
                 for i, t in lote.items()]
        conteudo = p["messages"][0]["content"]
        p["messages"][0]["content"] = conteudo[:conteudo.rindex("Falas:\n")] + \
            f"Textos do jogo:\n{json.dumps(falas, ensure_ascii=False)}"
        return p

    def encurtar(self, textos: dict[int, str], limites: dict[int, int]) -> dict[int, str]:
        """Pede de novo, mais curtas, as traduções que passaram do espaço (as que não voltarem ficam como estavam)."""
        saida: dict[int, str] = {}
        itens = list(textos.items())
        for inicio in range(0, len(itens), LINHAS_POR_PEDIDO):
            lote = itens[inicio:inicio + LINHAS_POR_PEDIDO]
            self.conferir_teto()
            pedido = _ENCURTAR + "\n" + json.dumps([{"id": i, "texto": t, "max": limites[i]} for i, t in lote],
                                                   ensure_ascii=False)
            try:
                resposta = self.cliente.messages.create(
                    model=self.modelo, max_tokens=MAX_TOKENS, system=self.sistema(self._sistema),
                    messages=[{"role": "user", "content": pedido}],
                    output_config={"format": {"type": "json_schema", "schema": _ESQUEMA}})
            except Exception as erro:
                raise ErroTraducao(_explicar(erro)) from erro
            self.contar(resposta)
            if resposta.stop_reason in ("refusal", "max_tokens"):
                continue
            saida.update(ler_resposta(resposta))
        return saida


@dataclass
class ResumoTraducao:
    traduzidas: int = 0
    unicas: int = 0                  # textos diferentes que foram ao tradutor (as repetições não vão)
    reaproveitadas: int = 0          # já estavam traduzidas antes (a memória)
    encurtadas: int = 0
    passaram: int = 0                # ainda passam do espaço máximo
    sem_codigo: int = 0              # algum código não voltou
    custo: float | None = None


def traduzir_textos(textos: list[str], tradutor, limites: list | None = None, glossario: tuple = (),
                    tirar_acentos: bool = False, memoria: dict | None = None, titulo: str = "", parar=None,
                    ao_progresso=None, longas: list | None = None) -> tuple[list[str], list[list[str]],
                                                                             ResumoTraducao]:
    """(traduções, avisos de cada uma, resumo). O tradutor é o do Claude (TradutorJogo) ou o grátis no PC
    (TradutorLocal): os dois têm traduzir_falas. A memória ({original: tradução}) evita traduzir de novo. longas
    (uma lista vazia): recebe, de cada texto, a 1ª tradução que não cabia no espaço ("" se coube de primeira)."""
    limites = list(limites or [None] * len(textos))
    memoria = memoria if memoria is not None else {}
    resumo = ResumoTraducao()
    finais = memoria.get("\0finais", {})
    unicos: dict[str, int] = {}
    for texto in textos:
        if texto.strip() and texto not in memoria and texto not in finais and texto not in unicos:
            unicos[texto] = len(unicos)
    resumo.unicas = len(unicos)
    resumo.reaproveitadas = sum(1 for t in textos if t.strip() and (t in memoria or t in finais))
    lista = list(unicos)
    protegidos = [proteger(t, glossario) for t in lista]
    limite_de = {}
    for t, lim in zip(textos, limites):
        if lim and t in unicos:
            limite_de[t] = min(lim, limite_de.get(t, lim))
    if hasattr(tradutor, "limites"):                  # o "max" de cada texto, já descontado o tamanho dos códigos
        tradutor.limites = {i: max(1, limite_de[t] - sum(len(p) - len(MARCA.format(n)) for n, p in
                                                         enumerate(protegidos[i][1], 1)))
                            for i, t in enumerate(lista) if t in limite_de}
    if lista:
        traduzidos = tradutor.traduzir_falas([m for m, _ in protegidos], titulo, parar,
                                             (lambda feitos, total: ao_progresso(feitos / max(1, total)))
                                             if ao_progresso else None)
        # o que passou do espaço: o Claude encurta (uma vez)
        longos = {i: traduzidos[i] for i, t in enumerate(lista)
                  if t in limite_de and len(restaurar(traduzidos[i], protegidos[i][1])[0]) > limite_de[t]}
        if longos and hasattr(tradutor, "encurtar"):
            novos = tradutor.encurtar(longos, {i: tradutor.limites[i] for i in longos})
            for i, texto in novos.items():
                if i in longos and len(restaurar(texto, protegidos[i][1])[0]) < \
                        len(restaurar(traduzidos[i], protegidos[i][1])[0]):
                    memoria.setdefault("\0longas", {})[lista[i]] = traduzidos[i]
                    traduzidos[i] = texto
                    resumo.encurtadas += 1
        for i, original in enumerate(lista):
            memoria[original] = traduzidos[i]
            memoria.setdefault("\0pecas", {})[original] = protegidos[i][1]
    saida, avisos = [], []
    pecas_de, longas_de = memoria.get("\0pecas", {}), memoria.get("\0longas", {})
    for texto, limite in zip(textos, limites):
        if longas is not None:
            longa = ""
            if texto in longas_de and texto not in finais:
                longa = restaurar(longas_de[texto], pecas_de.get(texto) or proteger(texto, glossario)[1])[0]
                longa = sem_acentos(longa) if tirar_acentos else longa
            longas.append(longa)
        if not texto.strip():
            saida.append(texto)
            avisos.append([])
            continue
        if texto in finais:                            # corrigida à mão ("Editar"): vale como está
            final, faltaram = finais[texto], [c for c in CODIGOS.findall(texto) if c not in finais[texto]]
        else:
            pecas = pecas_de.get(texto) or proteger(texto, glossario)[1]
            final, faltaram = restaurar(memoria[texto], pecas)
        if tirar_acentos:
            final = sem_acentos(final)
        aviso = []
        if faltaram:
            aviso.append("faltou " + " ".join(faltaram) + (" (posto no fim)" if any(not _eh_nome(p) for p in faltaram)
                                                           else ""))
            resumo.sem_codigo += 1
        if limite and len(final) > limite:
            aviso.append(f"passou do espaço: {len(final)} de {limite} letras")
            resumo.passaram += 1
        saida.append(final)
        avisos.append(aviso)
        resumo.traduzidas += 1
    resumo.custo = getattr(tradutor, "custo", None)
    return saida, avisos, resumo


def traduzir_roteiro(roteiro: Roteiro, tradutor, glossario: tuple = (), tirar_acentos: bool = False,
                     memoria: dict | None = None, so: int | None = None, parar=None,
                     ao_progresso=None) -> ResumoTraducao:
    """Traduz o roteiro (ou só os `so` primeiros textos: o teste) e guarda em cada Entrada a tradução e os avisos."""
    alvo = roteiro.com_texto[:so] if so else roteiro.com_texto
    longas: list[str] = []
    traduzidas, avisos, resumo = traduzir_textos(
        [e.texto for e in alvo], tradutor, [e.limite for e in alvo], glossario, tirar_acentos, memoria,
        roteiro.arquivo.stem, parar, ao_progresso, longas)
    for entrada, texto, aviso, longa in zip(alvo, traduzidas, avisos, longas):
        entrada.traducao, entrada.avisos, entrada.longa = texto, aviso, longa
    return resumo


# ----------------------------------------------------------------- a memória das traduções (retomar e revisar)
def carregar_memoria(arquivo: str | Path) -> dict:
    try:
        dados = json.loads(Path(arquivo).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    memoria = dict(dados.get("traducoes", {}))
    for chave, nome in (("\0pecas", "pecas"), ("\0finais", "corrigidas"), ("\0longas", "longas")):
        if dados.get(nome):
            memoria[chave] = dados[nome]
    return memoria


def corrigir(memoria: dict, original: str, traducao: str) -> None:
    """A tradução corrigida à mão ("Editar"): vale para todas as vezes que o texto aparece, e não volta ao tradutor."""
    memoria.setdefault("\0finais", {})[original] = traducao


def salvar_memoria(arquivo: str | Path, memoria: dict) -> None:
    arquivo = Path(arquivo)
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    dados = {"traducoes": {k: v for k, v in memoria.items() if not k.startswith("\0")},
             "pecas": memoria.get("\0pecas", {}), "corrigidas": memoria.get("\0finais", {}),
             "longas": memoria.get("\0longas", {})}
    temporario = arquivo.with_suffix(".tmp")
    temporario.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
    temporario.replace(arquivo)


class _SoMemoria:
    """O "tradutor" que nunca é chamado: da_memoria só passa os textos que já estão na memória."""

    def traduzir_falas(self, textos, titulo="", parar=None, ao_progresso=None):
        raise ErroTraducao("sem tradução guardada")


def da_memoria(textos: list[str], memoria: dict, limites: list | None = None, glossario: tuple = (),
               tirar_acentos: bool = False) -> list[tuple[str, list, str]]:
    """[(tradução, avisos, 1ª tradução longa)] dos textos JÁ traduzidos antes (ao abrir o jogo de novo: sem chamar o
    tradutor nem gastar); os que não estão na memória voltam com a tradução vazia."""
    limites = list(limites or [None] * len(textos))
    finais = memoria.get("\0finais", {})
    conhecidos = [i for i, t in enumerate(textos) if t.strip() and (t in finais or t in memoria)]
    saida = [("", [], "")] * len(textos)
    if conhecidos:
        longas: list[str] = []
        traducoes, avisos, _ = traduzir_textos([textos[i] for i in conhecidos], _SoMemoria(),
                                               [limites[i] for i in conhecidos], glossario, tirar_acentos, memoria,
                                               longas=longas)
        for k, i in enumerate(conhecidos):
            saida[i] = (traducoes[k], avisos[k], longas[k])
    return saida
