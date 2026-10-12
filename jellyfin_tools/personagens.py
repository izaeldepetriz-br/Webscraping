"""Uma voz para cada PERSONAGEM na dublagem: o Gemini ouve o áudio original e diz quem fala cada fala da legenda.

    1. Ouvir: o áudio do filme vai em trechos de TRECHO segundos (mp3 leve, só a voz importa), cada um com as falas
       da legenda daquele pedaço (número e horário). O Gemini devolve, para cada fala, um RÓTULO de quem fala
       ("Pessoa 1", ou o nome do personagem, se ele aparece no filme) e se a voz é masculina ou feminina.
       De um trecho para o outro, vai junto a lista de quem já foi identificado, para manter os mesmos rótulos.
    2. Distribuir: cada pessoa ganha uma voz pronta do Gemini do mesmo gênero (a que mais fala fica com a voz
       principal escolhida na tela); vozes repetem só quando acabam.
    3. Conferir: a janela mostra "Pessoa -> Voz" com exemplos de fala, para trocar o que quiser.

Pode errar: falas sobrepostas, música alta, muitas pessoas. Fala sem dono (ou de alguém que fala pouco) fica com a
voz principal. O que já foi ouvido fica guardado (personagens.json): parar no meio não perde o que foi pago.
"""

from __future__ import annotations

import json
import subprocess
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .dublagem import PREFIXO_CLOUD, SEM_JANELA, ErroDublagem, horarios
from .voz_gemini import (VOZ_PADRAO, VOZES, VOZES_FEMININAS, VOZES_MASCULINAS, ler_json, perguntar_sobre_audio)

TRECHO = 15 * 60              # segundos de áudio por pedido (o Gemini separa bem quem fala em até ~30 min)
MINIMO_FALAS = 3              # quem fala menos que isso fica com a voz principal
FIGURANTE = 20                # dublagem mista: quem tem menos falas que isso é figurante (vai para o Piper)
GENEROS = {"m": "homem", "f": "mulher", "?": "indefinido"}

_PERGUNTA = """Você ouve um trecho do áudio de um filme ({inicio} a {fim} do filme). Abaixo estão as falas da \
legenda deste trecho: o número (id), o horário em segundos CONTADOS DO INÍCIO DESTE TRECHO e o texto (em português; \
o áudio pode estar em outro idioma).

Diga QUEM fala cada fala, pela VOZ:
- Use o mesmo rótulo para a mesma pessoa. Pessoas já identificadas antes (reuse o rótulo se for a mesma voz):
{conhecidas}
- Pessoa nova: "Pessoa N" (o próximo número livre) ou o NOME do personagem, se ele for dito no filme.
- genero: "m" (voz masculina), "f" (voz feminina) ou "?" (criança, robô, não dá para saber).
- descricao: poucas palavras sobre a voz (ex.: "homem idoso, voz grave").
- Falas marcadas com [roteiro: Nome] já têm dono certo (do roteiro do filme): use esse Nome como o rótulo da voz \
dessa pessoa também nas outras falas dela.
- Se não der para saber quem fala uma fala, use o rótulo "?".

Responda SÓ com JSON, neste formato:
{{"pessoas": [{{"rotulo": "Pessoa 1", "genero": "m", "descricao": "..."}}], "falas": [{{"id": 12, "rotulo": "Pessoa 1"}}]}}

Falas:
{falas}"""


@dataclass
class Personagem:
    rotulo: str
    genero: str = "?"
    descricao: str = ""
    falas: list = field(default_factory=list)      # números das falas (a mesma numeração da dublagem)


def _hms(segundos: float) -> str:
    s = int(segundos)
    return f"{s // 3600:d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def audio_do_trecho(ffmpeg: str, video: Path, inicio: float, duracao: float) -> bytes:
    """O áudio de um pedaço do filme em mp3 leve (mono, 16 kHz, 32 kbps): ~4 MB por 15 minutos."""
    r = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-ss", f"{inicio:.2f}", "-t", f"{duracao:.2f}",
                        "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", "-b:a", "32k", "-f", "mp3", "pipe:1"],
                       capture_output=True, **SEM_JANELA)
    if r.returncode != 0 or not r.stdout:
        detalhe = (r.stderr or b"").decode("utf-8", "replace").strip()[-200:]
        raise ErroDublagem(f"não deu para tirar o áudio do trecho ({detalhe or r.returncode})")
    return r.stdout


def trechos(falas: list, tamanho: float = TRECHO) -> list[tuple[float, float, list[int]]]:
    """[(início, fim, números das falas)] cobrindo o filme em pedaços de `tamanho` segundos."""
    grupos: dict[int, list[int]] = {}
    for k, (f, _) in enumerate(falas):
        grupos.setdefault(int(horarios(f.tempo)[0] // tamanho), []).append(k)
    return [(n * tamanho, (n + 1) * tamanho, ids) for n, ids in sorted(grupos.items())]


def _carregar(arquivo: Path | None) -> dict:
    try:
        return json.loads(arquivo.read_text(encoding="utf-8")) if arquivo else {}
    except (OSError, ValueError):
        return {}


def identificar(video: str | Path, falas: list, cliente, ffmpeg: str, arquivo: str | Path | None = None,
                ao_progresso=None, parar=None, extrair=audio_do_trecho, tamanho: float = TRECHO,
                esperar=None, elenco: list[dict] | None = None,
                sabidas: dict[int, str] | None = None) -> list[Personagem]:
    """Quem fala cada fala. falas: [(Fala, texto)] (dublagem.falas_da_legenda). arquivo: onde guardar o progresso
    (um trecho já ouvido não é pedido de novo). elenco: quem já foi identificado nos OUTROS episódios da série
    ([{rotulo, genero, descricao}]): o Gemini reusa os mesmos rótulos, e cada um continua com a mesma voz.
    sabidas: {número da fala: personagem} já sabidas pelo ROTEIRO (roteiro.py): valem mais que o que o Gemini
    disser, e o trecho com quase todas sabidas (trecho_coberto) nem é mandado para ouvir (não gasta)."""
    video = Path(video)
    arquivo = Path(arquivo) if arquivo else None
    progresso = _carregar(arquivo)
    feitos = set(progresso.get("trechos", []))
    pessoas: dict[str, dict] = {p["rotulo"]: dict(p) for p in (elenco or []) if p.get("rotulo")}
    pessoas.update({p["rotulo"]: p for p in progresso.get("pessoas", [])})
    de_quem: dict[int, str] = {int(k): v for k, v in progresso.get("falas", {}).items()}
    sabidas = sabidas or {}
    de_quem.update(sabidas)
    for rotulo in set(sabidas.values()):
        pessoas.setdefault(rotulo, {"rotulo": rotulo, "genero": "?", "descricao": "do roteiro"})
    partes = trechos(falas, tamanho)
    for n, (inicio, fim, ids) in enumerate(partes):
        if parar and parar():
            raise ErroDublagem("interrompido (botão Parar)")
        if inicio in feitos or trecho_coberto(ids, sabidas):
            if ao_progresso:
                ao_progresso((n + 1) / len(partes))
            continue
        conhecidas = "\n".join(f'  - "{p["rotulo"]}" ({p.get("genero", "?")}): {p.get("descricao", "")}'
                               for p in pessoas.values()) or "  (ninguém ainda)"
        linhas = "\n".join(f"{k} [{max(0.0, horarios(falas[k][0].tempo)[0] - inicio):.1f}s] {falas[k][1]}"
                           + (f" [roteiro: {sabidas[k]}]" if k in sabidas else "") for k in ids)
        pergunta = _PERGUNTA.format(inicio=_hms(inicio), fim=_hms(fim), conhecidas=conhecidas, falas=linhas)
        mp3 = extrair(ffmpeg, video, inicio, fim - inicio)
        kwargs = {"esperar": esperar} if esperar else {}
        dados = ler_json(perguntar_sobre_audio(cliente, pergunta, mp3, **kwargs))
        for p in dados.get("pessoas", []):
            rotulo = str(p.get("rotulo", "")).strip()
            if rotulo and rotulo != "?":
                antes = pessoas.get(rotulo, {})
                genero = str(p.get("genero", "?")).strip().lower()[:1]
                pessoas[rotulo] = {"rotulo": rotulo, "genero": genero if genero in GENEROS else antes.get("genero", "?"),
                                   "descricao": str(p.get("descricao", "") or antes.get("descricao", ""))[:80]}
        validos = set(ids)
        for item in dados.get("falas", []):
            try:
                k, rotulo = int(item["id"]), str(item.get("rotulo", "")).strip()
            except (KeyError, TypeError, ValueError):
                continue
            if k in validos and rotulo and rotulo != "?" and k not in sabidas:     # o roteiro vale mais
                de_quem[k] = rotulo
                pessoas.setdefault(rotulo, {"rotulo": rotulo, "genero": "?", "descricao": ""})
        feitos.add(inicio)
        if arquivo:
            arquivo.parent.mkdir(parents=True, exist_ok=True)
            arquivo.write_text(json.dumps({"trechos": sorted(feitos), "pessoas": list(pessoas.values()),
                                           "falas": {str(k): v for k, v in de_quem.items()}}, ensure_ascii=False),
                               encoding="utf-8")
        if ao_progresso:
            ao_progresso((n + 1) / len(partes))
    lista = []
    for rotulo, p in pessoas.items():
        suas = sorted(k for k, r in de_quem.items() if r == rotulo)
        if suas:
            lista.append(Personagem(rotulo, p.get("genero", "?"), p.get("descricao", ""), suas))
    return sorted(lista, key=lambda p: -len(p.falas))


def trecho_coberto(ids: list[int], sabidas: dict | None, parte: float = 0.85) -> bool:
    """O roteiro já diz quem fala quase todas as falas do trecho: não precisa mandar o áudio para o Gemini ouvir."""
    return bool(sabidas) and bool(ids) and sum(k in sabidas for k in ids) >= parte * len(ids)


def distribuir_vozes(personagens: list[Personagem], voz_principal: str = VOZ_PADRAO,
                     figurante: str | None = None, limite: int = FIGURANTE,
                     fixas: dict[str, str] | None = None) -> dict[str, str]:
    """{rótulo: voz}. Quem mais fala fica com a voz principal (se o gênero combinar); os outros, vozes do mesmo
    gênero ainda não usadas (repetem só quando acabam). Quem fala pouco fica com a voz principal. Uma voz clonada
    ("clone:Nome") como principal vai para quem mais fala, qualquer que seja o gênero (dá para trocar na tabela).
    figurante ("piper:faber"): dublagem MISTA, quem tem menos de `limite` falas vai para essa voz (Piper, grátis).
    figurante "cloud:Neural2": vai para o Google Cloud (cota grátis), com uma voz do tipo e do gênero de cada um."""
    clonada = voz_principal.startswith("clone:")       # a SUA voz clonada como principal: vai para quem mais fala
    principal = voz_principal if voz_principal in VOZES or clonada else VOZ_PADRAO
    fixas = fixas or {}
    usadas: Counter = Counter(fixas.values())
    mapa, figurantes = {}, Counter()
    for p in personagens:                              # já vêm de quem fala mais para quem fala menos
        if p.rotulo in fixas:                          # série: a voz que esse personagem já tinha
            mapa[p.rotulo] = fixas[p.rotulo]
            continue
        if figurante and len(p.falas) < limite:
            mapa[p.rotulo] = voz_de_figurante(figurante, p.genero, figurantes[p.genero])
            figurantes[p.genero] += 1
            continue
        if len(p.falas) < MINIMO_FALAS:
            mapa[p.rotulo] = principal
            continue
        grupo = {"m": VOZES_MASCULINAS, "f": VOZES_FEMININAS}.get(p.genero, VOZES_MASCULINAS + VOZES_FEMININAS)
        if not usadas and (principal in grupo or clonada):
            voz = principal
        else:
            voz = min(grupo, key=lambda v: (usadas[v], grupo.index(v)))
        mapa[p.rotulo] = voz
        usadas[voz] += 1
    return mapa


def voz_de_figurante(figurante: str, genero: str, n: int = 0) -> str:
    """"cloud:Neural2" + gênero -> "cloud:pt-BR-Neural2-B" (homem) ou "-A"/"-C" (mulher, alternando: duas
    figurantes seguidas não ficam com a mesma voz). "piper:faber" (ou uma voz do Cloud já completa) fica igual."""
    from .voz_cloud import LETRAS, TIPOS, nome_da_voz
    tipo = figurante[len(PREFIXO_CLOUD):] if figurante.startswith(PREFIXO_CLOUD) else ""
    if tipo not in TIPOS:
        return figurante
    letras = LETRAS.get(tipo, "ABC")
    femininas = [l for l in letras if l in "ACD"] or list(letras)
    masculinas = [l for l in letras if l in "BE"] or list(letras)
    grupo = femininas if genero == "f" else masculinas if genero == "m" else list(letras)
    return f"{PREFIXO_CLOUD}{nome_da_voz(tipo, grupo[n % len(grupo)])}"


def carregar_elenco(arquivo: str | Path) -> dict:
    """{"pessoas": [{rotulo, genero, descricao}], "vozes": {rotulo: voz}} de uma série (vazio se ainda não tem)."""
    try:
        dados = json.loads(Path(arquivo).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"pessoas": [], "vozes": {}}
    return {"pessoas": [p for p in dados.get("pessoas", []) if isinstance(p, dict) and p.get("rotulo")],
            "vozes": {str(k): str(v) for k, v in dict(dados.get("vozes", {})).items()}}


def salvar_elenco(arquivo: str | Path, personagens: list[Personagem], mapa: dict[str, str]) -> None:
    """Junta ao elenco da série quem apareceu neste episódio e a voz de cada um (a escolhida vale para os próximos)."""
    elenco = carregar_elenco(arquivo)
    pessoas = {p["rotulo"]: p for p in elenco["pessoas"]}
    for p in personagens:
        pessoas[p.rotulo] = {"rotulo": p.rotulo, "genero": p.genero, "descricao": p.descricao}
    vozes = {**elenco["vozes"], **{r: v for r, v in mapa.items() if v}}
    arquivo = Path(arquivo)
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    arquivo.write_text(json.dumps({"pessoas": list(pessoas.values()), "vozes": vozes}, ensure_ascii=False, indent=2),
                       encoding="utf-8")


def vozes_por_fala(personagens: list[Personagem], mapa: dict[str, str]) -> dict[int, str]:
    """{número da fala: voz} para dublagem.dublar_video(vozes=...). Fala sem dono não entra (usa a voz principal)."""
    return {k: mapa[p.rotulo] for p in personagens if mapa.get(p.rotulo) for k in p.falas}


def resumo(personagens: list[Personagem], falas: list, limite: int = 6) -> list[str]:
    """Para a janela: 'Pessoa 1 (homem, voz grave) · 312 falas · ex.: "Onde você estava?"'."""
    linhas = []
    for p in personagens[:limite]:
        suas = [falas[k][1] for k in p.falas if 0 <= k < len(falas)]          # número fora da legenda: ignora
        exemplo = next((t for t in suas if 8 <= len(t) <= 60), suas[0] if suas else "")
        extra = f", {p.descricao}" if p.descricao else ""
        linhas.append(f'{p.rotulo} ({GENEROS.get(p.genero, "indefinido")}{extra}) · {len(p.falas)} falas · '
                      f'ex.: "{exemplo[:60]}"')
    return linhas


def para_json(personagens: list[Personagem]) -> list[dict]:
    return [asdict(p) for p in personagens]
