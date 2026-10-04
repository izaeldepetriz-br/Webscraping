"""Regras de nome que VOCÊ ensina ("Corrigir nome" nos não identificados).

Quando o nome do arquivo não diz qual é a série ou o filme, você diz uma vez e o organizador lembra:

    regra de SÉRIE (vale para a pasta inteira, e as subpastas):
        D:/Torrent/Pasta Estranha  ->  série "Breaking Bad" (2008), temporada 5
        "13 - To'hajiilee.mp4" e "Ep 14.mp4" dessa pasta viram Breaking Bad S05E13 e S05E14
    regra de FILME (vale para aquele arquivo):
        D:/Torrent/filme_final_v2.mkv  ->  "O Auto da Compadecida" (2000)

As regras ficam num .json (ao lado das configurações) e valem nas próximas organizações e na vigia.
O número do episódio continua vindo do nome do arquivo; o nome da série e (se você disser) a temporada
vêm da regra. Um 'S03E15' escrito no arquivo vale mais que a temporada da regra.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from .nomes import EXTENSOES_VIDEO, EpisodioExtraido, _RE_SITE


@dataclass
class RegraNome:
    caminho: str                  # série: a pasta; filme: o arquivo
    tipo: str                     # "serie" ou "filme"
    titulo: str
    ano: int | None = None
    temporada: int | None = None  # só série: a temporada dos arquivos que não dizem qual é

    def descricao(self) -> str:
        ano = f" ({self.ano})" if self.ano else ""
        temporada = f", temporada {self.temporada}" if self.temporada else ""
        return f"{self.titulo}{ano}{temporada}"


def _chave(caminho) -> str:
    return os.path.normcase(os.path.abspath(str(caminho)))


def carregar_regras(arquivo: str | Path) -> list[RegraNome]:
    try:
        dados = json.loads(Path(arquivo).read_text(encoding="utf-8"))
        return [RegraNome(**r) for r in dados if r.get("titulo") and r.get("caminho")]
    except (OSError, ValueError, TypeError):
        return []


def salvar_regras(arquivo: str | Path, regras: list[RegraNome]) -> None:
    Path(arquivo).parent.mkdir(parents=True, exist_ok=True)
    Path(arquivo).write_text(json.dumps([asdict(r) for r in regras], ensure_ascii=False, indent=2),
                             encoding="utf-8")


def adicionar_regra(arquivo: str | Path, nova: RegraNome) -> list[RegraNome]:
    """Guarda a regra (a de mesmo caminho e tipo é trocada pela nova)."""
    regras = [r for r in carregar_regras(arquivo)
              if not (r.tipo == nova.tipo and _chave(r.caminho) == _chave(nova.caminho))]
    regras.append(nova)
    salvar_regras(arquivo, regras)
    return regras


def regra_para(video: Path, regras, tipo: str) -> RegraNome | None:
    """A regra que vale para o vídeo: filme = o próprio arquivo; série = a pasta mais de dentro que tem regra."""
    if not regras:
        return None
    alvo = _chave(video)
    melhor = None
    for regra in regras:
        if regra.tipo != tipo:
            continue
        base = _chave(regra.caminho)
        if tipo == "filme":
            if alvo == base:
                return regra
        elif alvo.startswith(base.rstrip("\\/") + os.sep) and (melhor is None or len(base) > len(_chave(melhor.caminho))):
            melhor = regra
    return melhor


_RE_NAO_EPISODIO = re.compile(r"\[[^\]]*\]|\([^)]*\)|\b\d{3,4}p\b|\b\d{3,4}x\d{3,4}\b|\b[xh]\.?26[45]\b|"
                              r"\b(?:19|20)\d{2}\b|\b[257]\.[01]\b", re.IGNORECASE)


def numero_do_episodio(nome_arquivo: str) -> int | None:
    """O primeiro número que não é ano, resolução ou codec: 'Ep 14 [720p].mp4' -> 14."""
    caminho = Path(nome_arquivo)
    base = caminho.stem if caminho.suffix.lower() in EXTENSOES_VIDEO | {".strm"} else caminho.name
    base = _RE_NAO_EPISODIO.sub(" ", _RE_SITE.sub(" ", base))
    if m := re.search(r"(?<![a-z\d])(\d{1,4})(?!\d)", base, re.IGNORECASE):
        return int(m.group(1)) or None
    return None


def aplicar_regra(ep: EpisodioExtraido | None, video: Path, regra: RegraNome) -> EpisodioExtraido | None:
    """Episódio com o nome (e a temporada) da regra. Sem número no arquivo, não dá para saber qual é."""
    if ep is None:
        numero = numero_do_episodio(video.name)
        if numero is None:
            return None
        return EpisodioExtraido(regra.titulo, regra.temporada or 1, numero, regra.ano,
                                absoluto=regra.temporada is None)
    if regra.temporada and ep.absoluto:            # 'Breaking Bad 5ª/13 - X': a temporada vem da regra
        ep = ep._replace(temporada=regra.temporada, absoluto=False)
    return ep._replace(serie=regra.titulo, ano=regra.ano or ep.ano)
