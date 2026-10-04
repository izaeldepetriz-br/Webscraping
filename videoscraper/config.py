"""Lembra as escolhas do usuário entre uma execução e outra.

Fica na pasta do USUÁRIO (ex.: C:/Users/Voce/.videoscraper/config.json), fora do projeto:
assim nunca vai parar no GitHub por engano. Chaves de API só são gravadas se o usuário pedir.
"""

from __future__ import annotations

import json
from pathlib import Path

ARQUIVO = Path.home() / ".videoscraper" / "config.json"


def carregar() -> dict:
    try:
        return json.loads(ARQUIVO.read_text(encoding="utf-8"))
    except (OSError, ValueError):          # ainda não existe ou foi corrompido: começa do zero
        return {}


def salvar(dados: dict) -> None:
    try:
        ARQUIVO.parent.mkdir(parents=True, exist_ok=True)
        ARQUIVO.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass                               # não conseguir salvar preferências não pode travar o app
