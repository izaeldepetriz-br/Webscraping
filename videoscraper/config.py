"""Lembra as escolhas do usuário entre uma execução e outra.

Fica na pasta do USUÁRIO (ex.: C:/Users/Voce/.videoscraper/config.json), fora do projeto:
assim nunca vai parar no GitHub por engano. Chaves de API só são gravadas se o usuário pedir.
"""

from __future__ import annotations

import json
import zipfile
from datetime import datetime
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


# ---------------------------------------------------------------- exportar / importar (levar para outro computador)
# O que vai junto: as opções, as regras do "Corrigir nome", a lista de canais (com histórico e lixeira) e a memória
# de downloads. Pastas grandes (modelos do Whisper, Piper, logs) não vão: o programa baixa/refaz sozinho.
ARQUIVOS_DA_CONFIGURACAO = ("config.json", "regras_nomes.json", "canais.json", "canais_historico.json",
                            "canais_removidos.json", "baixados.json", "epg_mapa.json")


def exportar(destino: str | Path, segredos=(), incluir_chaves: bool = False) -> list[str]:
    """Grava um .zip com as configurações. Sem incluir_chaves, as chaves de API (segredos) ficam de fora."""
    pasta, nomes = ARQUIVO.parent, []
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as z:
        for nome in ARQUIVOS_DA_CONFIGURACAO:
            arquivo = pasta / nome
            if not arquivo.is_file():
                continue
            if nome == "config.json" and not incluir_chaves:
                dados = carregar()
                for segredo in segredos:
                    dados.get("jellyfin", {}).pop(segredo, None)
                z.writestr(nome, json.dumps(dados, ensure_ascii=False, indent=2))
            else:
                z.write(arquivo, nome)
            nomes.append(nome)
    return nomes


def importar(origem: str | Path) -> tuple[list[str], Path]:
    """Troca as configurações pelas do .zip (só os arquivos conhecidos; o resto do .zip é ignorado). Antes, guarda
    as atuais em backups/antes-de-importar-<data>.zip. Devolve (arquivos importados, cópia de segurança)."""
    with zipfile.ZipFile(origem) as z:
        nomes = [n for n in z.namelist() if n in ARQUIVOS_DA_CONFIGURACAO]
        if "config.json" not in nomes:
            raise ValueError("este arquivo não é uma exportação do Maestro (falta o config.json)")
        conteudos = {n: z.read(n) for n in nomes}
    json.loads(conteudos["config.json"].decode("utf-8"))           # confere antes de trocar qualquer coisa
    pasta = ARQUIVO.parent
    copia = pasta / "backups" / f"antes-de-importar-{datetime.now():%Y-%m-%d_%H-%M-%S}.zip"
    copia.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(copia, "w", zipfile.ZIP_DEFLATED) as z:
        for nome in ARQUIVOS_DA_CONFIGURACAO:
            if (pasta / nome).is_file():
                z.write(pasta / nome, nome)
    for nome, dados in conteudos.items():
        (pasta / nome).write_bytes(dados)
    return nomes, copia
