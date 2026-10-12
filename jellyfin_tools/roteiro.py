"""Quem fala cada fala pelo ROTEIRO do filme (nome em MAIÚSCULAS e a fala embaixo), sem gastar nada com IA.

    Roteiro:                          Legenda original (Filme.en.srt):     Legenda em português (a dublada):
          TINA                        12  00:03:10 --> 00:03:12            12  00:03:10 --> 00:03:12
      Just a dream, Ma...                 Just a dream, Ma...                  Só um sonho, mãe...

    1. Ler: o roteiro vira uma lista [(personagem, fala)]. Aceita .txt, .html (a página do site, salva ou pelo link)
       e .pdf COM texto (o PDF "foto das páginas", impresso como imagem, não tem texto para ler).
    2. Casar: cada fala da legenda no idioma do roteiro (a original, ao lado do vídeo: mesmos horários da
       portuguesa) é comparada, NO SEU PC, com as falas do roteiro perto de onde a anterior foi achada. Parecida o
       bastante: o nome de quem fala vai para a fala em português do mesmo horário.
    3. O Gemini só ouve os trechos que o roteiro não cobriu (roteiro de filmagem não é o filme final: cenas mudam e
       falas são cortadas ou improvisadas). As vozes de quem o roteiro achou ficam com o nome do personagem.

O roteiro fica ao lado do vídeo: 'Nome do vídeo.roteiro.txt' (o botão "📜 Roteiro" grava assim).
"""

from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

EXTENSOES = (".txt", ".html", ".htm", ".pdf")
MINIMO_TEXTO = 2000            # letras: menos que isso num PDF = PDF de imagens (sem texto)
JANELA = 80                    # falas do roteiro olhadas adiante da última achada
PARECIDA = 0.6                 # parte das palavras da legenda que precisa estar na fala do roteiro
PARECIDA_LONGE = 0.8           # achada longe (cena trocada de lugar): mais exigente
COBERTO = 0.85                 # trecho com 85% das falas achadas no roteiro: o Gemini não precisa ouvir


class ErroRoteiro(Exception):
    pass


@dataclass
class Dialogo:
    personagem: str            # como no roteiro, arrumado: "Tina", "Tina's Mother"
    texto: str
    palavras: tuple = ()


# ----------------------------------------------------------------- 1. ler
def caminho_roteiro(video: str | Path) -> Path | None:
    """O roteiro ao lado do vídeo ('Nome.roteiro.txt', .html, .htm ou .pdf), se houver."""
    video = Path(video)
    return next((video.with_name(f"{video.stem}.roteiro{e}") for e in EXTENSOES
                 if video.with_name(f"{video.stem}.roteiro{e}").is_file()), None)


def _do_html(texto: str) -> str:
    texto = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", texto)
    texto = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</h\d>", "\n", texto)
    return html.unescape(re.sub(r"<[^>]+>", "", texto))


def _do_pdf(caminho: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as erro:
        raise ErroRoteiro("para ler roteiro em PDF falta a biblioteca pypdf (pip install pypdf); salve a página "
                          "do roteiro como .txt ou use o link") from erro
    try:
        return "\n".join((p.extract_text() or "") for p in PdfReader(str(caminho)).pages)
    except Exception as erro:                       # PDF quebrado, protegido...
        raise ErroRoteiro(f"não deu para ler o PDF ({type(erro).__name__})") from erro


def texto_do_roteiro(origem: str | Path) -> str:
    """O texto do roteiro de um arquivo (.txt, .html, .pdf com texto)."""
    caminho = Path(origem)
    if caminho.suffix.lower() == ".pdf":
        texto = _do_pdf(caminho)
        if len(texto.strip()) < MINIMO_TEXTO:
            raise ErroRoteiro("este PDF é só imagem (fotos das páginas, sem texto para ler). Use o link da página do "
                              "roteiro ou salve a página como .txt")
        return texto
    bruto = caminho.read_bytes()
    try:
        texto = bruto.decode("utf-8")
    except UnicodeDecodeError:
        texto = bruto.decode("latin-1")
    return _do_html(texto) if caminho.suffix.lower() in (".html", ".htm") or "<html" in texto[:2000].lower() \
        else texto


def baixar_roteiro(url: str, obter=None) -> str:
    """O texto de uma página de roteiro (o link que você colou)."""
    if not re.match(r"https?://", url.strip()):
        raise ErroRoteiro("o link precisa começar com http:// ou https://")
    if obter is None:
        import requests
        obter = requests.get
    try:
        resposta = obter(url.strip(), timeout=30, headers={"User-Agent": "Mozilla/5.0 (Maestro)"})
    except Exception as erro:
        raise ErroRoteiro(f"não deu para abrir o link ({type(erro).__name__})") from erro
    if resposta.status_code != 200:
        raise ErroRoteiro(f"o site respondeu {resposta.status_code}")
    tipo = resposta.headers.get("content-type", "")
    if "pdf" in tipo:
        raise ErroRoteiro("o link é um PDF: baixe o arquivo e escolha-o (precisa ter texto, não fotos das páginas)")
    return _do_html(resposta.text)


def guardar_roteiro(video: str | Path, texto: str) -> Path:
    """Grava 'Nome.roteiro.txt' ao lado do vídeo (troca o que houver). Confere antes se tem falas."""
    if len(ler_roteiro(texto)) < 20:
        raise ErroRoteiro("não achei falas com o nome de quem fala (nome em MAIÚSCULAS e a fala embaixo): este "
                          "texto não parece um roteiro")
    video = Path(video)
    for antigo in EXTENSOES:
        video.with_name(f"{video.stem}.roteiro{antigo}").unlink(missing_ok=True)
    destino = video.with_name(f"{video.stem}.roteiro.txt")
    destino.write_text(texto, encoding="utf-8")
    return destino


# ----------------------------------------------------------------- o formato do roteiro
_NAO_E_NOME = re.compile(r"^(INT|EXT|INT/EXT|I/E|CUT|FADE|SMASH|DISSOLVE|MATCH|BURN|THE END|CONTINUED|MORE|"
                         r"CLOSE|ANGLE|BACK TO|INTERCUT|SUPER|TITLE|INSERT|MONTAGE|SERIES OF|FLASHBACK|END|"
                         r"OMITTED|CONT|POV|LATER|NIGHT|DAY|MOMENTS LATER|CORTA|FUSÃO|INT\.|EXT\.)\b")
_MARCA = re.compile(r"\s*\((?:[^)]*)\)\s*$")       # (O.S.), (V.O.), (CONT'D), (OFF)...


def _nome(linha: str) -> str | None:
    """'TINA'S MOTHER (O.S.)' -> "Tina's Mother"; None se a linha não é o nome de quem fala."""
    s = linha.strip()
    if not s or len(s) > 40 or s.endswith((":", "!", "?", ",", ";")):
        return None
    sem_marca = _MARCA.sub("", s).strip()
    sem_marca = re.sub(r"\s*\((?:[^)]*)\)\s*", " ", sem_marca).strip()
    letras = [c for c in sem_marca if c.isalpha()]
    if len(letras) < 2 or any(c.islower() for c in letras) or _NAO_E_NOME.match(sem_marca):
        return None
    if re.search(r"\d", sem_marca) or len(sem_marca.split()) > 4 or sem_marca.endswith("."):
        return None
    return " ".join(p[:1] + p[1:].lower() for p in sem_marca.split())


def _palavras(texto: str) -> tuple:
    """Minúsculas, sem acento e sem pontuação: 'Don't you DARE!' -> ('dont', 'you', 'dare')."""
    texto = unicodedata.normalize("NFKD", texto.lower())
    texto = "".join(c for c in texto if not unicodedata.combining(c)).replace("'", "").replace("’", "")
    return tuple(re.findall(r"[a-z0-9]+", texto))


def ler_roteiro(texto: str) -> list[Dialogo]:
    """[(personagem, fala)] na ordem do roteiro. O nome é uma linha só em MAIÚSCULAS; a fala são as linhas logo
    abaixo, até a linha em branco. As indicações entre parênteses ('(low)', '(to Tina)') saem da fala."""
    linhas = texto.replace("\r", "").split("\n")
    dialogos: list[Dialogo] = []
    i = 0
    while i < len(linhas):
        nome = _nome(linhas[i])
        if nome is None:
            i += 1
            continue
        fala, j = [], i + 1
        while j < len(linhas) and linhas[j].strip():
            if _nome(linhas[j]) is not None and fala:          # outro nome logo embaixo: começa outra fala
                break
            fala.append(linhas[j].strip())
            j += 1
        texto_fala = re.sub(r"\([^)]*\)", " ", " ".join(fala))
        texto_fala = " ".join(texto_fala.split())
        palavras = _palavras(texto_fala)
        if palavras and not (texto_fala.isupper() and len(palavras) > 3):   # bloco em maiúsculas = ação, não fala
            dialogos.append(Dialogo(nome, texto_fala, palavras))
        i = max(j, i + 1)
    return dialogos


# ----------------------------------------------------------------- gênero (pelo texto das cenas)
_FEMININOS = {"mother", "mom", "ma", "woman", "girl", "mrs", "miss", "ms", "lady", "aunt", "sister", "wife",
              "daughter", "grandma", "grandmother", "queen", "nun", "mae", "mulher", "menina", "senhora", "tia",
              "irma", "esposa", "filha", "avo", "garota", "moca"}
_MASCULINOS = {"father", "dad", "pa", "man", "boy", "mr", "sir", "uncle", "brother", "husband", "son", "grandpa",
               "grandfather", "king", "priest", "guy", "pai", "homem", "menino", "senhor", "tio", "irmao", "marido",
               "filho", "garoto", "rapaz", "padre"}


def generos(texto: str, nomes: set[str]) -> dict[str, str]:
    """{personagem: "m" | "f" | "?"}: pelas palavras do próprio nome ("Tina's Mother" -> f) e pelos pronomes
    ("she/her" x "he/his/him") nas frases das cenas em que o nome aparece."""
    contas = {n: [0, 0] for n in nomes}
    frases = re.split(r"(?<=[.!?])\s+|\n\s*\n", texto)
    maiusculos = {n: n.upper() for n in nomes}
    for frase in frases:
        presentes = [n for n, m in maiusculos.items() if re.search(rf"\b{re.escape(m)}\b", frase)]
        if len(presentes) != 1:                        # duas pessoas na frase: o pronome pode ser de qualquer uma
            continue
        palavras = re.findall(r"[a-z']+", frase.lower())
        contas[presentes[0]][0] += sum(p in ("she", "her", "hers", "herself") for p in palavras)
        contas[presentes[0]][1] += sum(p in ("he", "him", "his", "himself") for p in palavras)
        # a apresentação do personagem: "MARA, a tired woman of forty" (vale 2)
        contas[presentes[0]][0] += 2 * sum(p in ("woman", "girl", "lady", "mother", "wife") for p in palavras)
        contas[presentes[0]][1] += 2 * sum(p in ("man", "boy", "guy", "father", "husband", "son") for p in palavras)
    resultado = {}
    for n in nomes:
        do_nome = set(_palavras(n.replace("'s", "")))
        if do_nome & _FEMININOS:
            resultado[n] = "f"
        elif do_nome & _MASCULINOS:
            resultado[n] = "m"
        else:
            f, m = contas[n]
            resultado[n] = "f" if f >= 2 and f > 1.5 * m else "m" if m >= 2 and m > 1.5 * f else "?"
    return resultado


# ----------------------------------------------------------------- 2. casar com a legenda
def _semelhanca(linha: tuple, fala: tuple) -> float:
    """Que parte das palavras da linha da legenda aparece, na ordem, na fala do roteiro (0 a 1)."""
    if not linha or not fala:
        return 0.0
    blocos = SequenceMatcher(None, linha, fala, autojunk=False).get_matching_blocks()
    return sum(b.size for b in blocos) / len(linha)


def casar(dialogos: list[Dialogo], linhas: list[str]) -> dict[int, str]:
    """{número da linha: personagem} para as linhas da legenda (no idioma do roteiro) achadas no roteiro.
    Segue o roteiro em ordem: procura perto de onde a anterior foi achada; longe, só se for bem parecida."""
    achadas: dict[int, str] = {}
    posicao = 0
    for k, linha in enumerate(linhas):
        if re.search(r"(^|\n)\s*-.+\n\s*-", linha):      # "- Oi. / - Tchau.": duas pessoas na mesma legenda
            continue
        palavras = _palavras(linha)
        if not palavras:
            continue
        curta = len(palavras) <= 2
        fim = min(len(dialogos), posicao + (4 if curta else JANELA))
        melhor, nota = None, 0.0
        for d in range(max(0, posicao - 1), fim):
            n = _semelhanca(palavras, dialogos[d].palavras)
            if n > nota + 1e-9:
                melhor, nota = d, n
        if melhor is not None and nota >= (1.0 if curta else PARECIDA):
            achadas[k], posicao = dialogos[melhor].personagem, melhor
            continue
        if len(palavras) >= 4:                            # cena trocada de lugar: procura no roteiro todo
            longe = max(range(len(dialogos)), key=lambda d: _semelhanca(palavras, dialogos[d].palavras),
                        default=None)
            if longe is not None and _semelhanca(palavras, dialogos[longe].palavras) >= PARECIDA_LONGE:
                achadas[k], posicao = dialogos[longe].personagem, longe
    return achadas


def mesmo_horario(portuguesas: list[tuple[float, float]], originais: list[tuple[float, float]]) -> list[int | None]:
    """Para cada fala em português, a fala da legenda original no mesmo horário (a que mais se sobrepõe)."""
    resultado = []
    j = 0
    for a, b in portuguesas:
        while j < len(originais) and originais[j][1] < a - 1.0:
            j += 1
        melhor, sobra = None, 0.0
        for i in range(j, len(originais)):
            c, d = originais[i]
            if c > b + 1.0:
                break
            comum = min(b, d) - max(a, c)
            if comum > sobra or (melhor is None and abs(c - a) <= 0.5):
                melhor, sobra = i, max(comum, 0.0)
        resultado.append(melhor)
    return resultado


# ----------------------------------------------------------------- 3. o vídeo inteiro
def legenda_original(video: str | Path) -> Path | None:
    """A legenda em outro idioma ao lado do vídeo ('Nome.en.srt'...), na ordem de preferência da tradução."""
    from .traducao import _PORTUGUES, ORIGENS_PREFERIDAS
    video = Path(video)
    achadas = {}
    for srt in video.parent.glob(f"{glob_escape(video.stem)}.*.srt"):
        codigo = srt.name[len(video.stem) + 1:-4].lower()
        if codigo and codigo not in _PORTUGUES and "roteiro" not in codigo:
            achadas[codigo] = srt
    for codigo in ORIGENS_PREFERIDAS:
        if codigo in achadas:
            return achadas[codigo]
    return next(iter(sorted(achadas.items())), (None, None))[1]


def glob_escape(texto: str) -> str:
    return re.sub(r"([\[\]*?])", r"[\1]", texto)


@dataclass
class QuemFala:
    falas: dict                # {número da fala em português: personagem}
    generos: dict              # {personagem: "m" | "f" | "?"}
    total: int                 # falas em português
    roteiro: Path | None = None

    @property
    def cobertura(self) -> float:
        return len(self.falas) / self.total if self.total else 0.0


def quem_fala(video: str | Path, falas: list) -> QuemFala | None:
    """Pelo roteiro ao lado do vídeo: quem fala cada fala da legenda em português (falas: a lista de
    dublagem.falas_da_legenda). None: o vídeo não tem roteiro. Compara com a legenda original (mesmos horários) e
    também direto com a portuguesa (roteiro em português); fica a que achar mais falas."""
    from .dublagem import horarios
    from .legendas import extrair_srt
    from .traducao import ler_srt
    caminho = caminho_roteiro(video)
    if caminho is None:
        return None
    texto = texto_do_roteiro(caminho)
    dialogos = ler_roteiro(texto)
    if not dialogos:
        raise ErroRoteiro(f"não achei falas no roteiro {caminho.name} (nome em MAIÚSCULAS e a fala embaixo)")
    melhor = casar(dialogos, [f.texto for f, _ in falas])
    original = legenda_original(video)
    if original is not None:
        try:
            outras = ler_srt(extrair_srt(original.read_bytes()))
        except Exception:                               # legenda original quebrada: fica só a comparação direta
            outras = []
        if outras:
            achadas = casar(dialogos, [f.texto for f in outras])
            par = mesmo_horario([horarios(f.tempo) for f, _ in falas], [horarios(f.tempo) for f in outras])
            pela_original = {k: achadas[i] for k, i in enumerate(par) if i is not None and i in achadas}
            if len(pela_original) > len(melhor):
                melhor = pela_original
    return QuemFala(melhor, generos(texto, set(melhor.values())), len(falas), caminho)
