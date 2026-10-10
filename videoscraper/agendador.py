"""Agendar os comandos de robô no Agendador de Tarefas do Windows, sem precisar digitar nada.

    "Conferir os canais todo dia às 06:00"  ->  schtasks /Create /TN "Maestro\\conferir-canais"
                                               /TR "\"...\\Maestro.exe\" --conferir-canais" /SC DAILY /ST 06:00 /F

As tarefas ficam numa pasta "Maestro" do Agendador (dá para ver e mudar por lá também: Iniciar > Agendador de
Tarefas). Rodam com o seu usuário, só com o computador ligado e você conectado (não pede senha nem administrador).
O resultado de cada execução fica no log e em ~/.videoscraper/rpa/ultimo.json, como em qualquer comando de robô.
"""

from __future__ import annotations

import csv
import io
import subprocess
import sys
from pathlib import Path

PASTA = "Maestro"
COMANDOS = {"--organizar": "Organizar o que terminou de baixar",
            "--conferir-espelhos": "Conferir os espelhos (.strm)",
            "--conferir-canais": "Conferir os canais da TV ao vivo",
            "--enviar-tv": "Enviar a lista de canais ao Jellyfin",
            "--traduzir-legendas": "Traduzir as legendas que faltam (Claude)",
            "--legendar-audio": "Criar legenda pelo áudio (Whisper)",
            "--dublar": "Dublar filmes (voz sintética)"}
FREQUENCIAS = ("Todo dia", "Toda semana (segunda)", "A cada 6 horas", "A cada hora")
SEM_JANELA = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}


class ErroAgenda(Exception):
    """Mensagem já em português."""


def nome_da_tarefa(comando: str) -> str:
    return f"{PASTA}\\{comando.lstrip('-')}"


def programa() -> str:
    """O que a tarefa roda: o Maestro.exe do lugar fixo (continua valendo depois das atualizações)."""
    if getattr(sys, "frozen", False):
        try:
            from .instalacao import executavel_fixo
            fixo = executavel_fixo()
            if fixo.is_file():
                return f'"{fixo}"'
        except Exception:
            pass
        return f'"{sys.executable}"'
    executavel = Path(sys.executable)
    sem_janela = executavel.with_name("pythonw.exe")
    iniciar = Path(__file__).resolve().parent.parent / "iniciar.py"
    return f'"{sem_janela if sem_janela.exists() else executavel}" "{iniciar}"'


def comando_criar(comando: str, frequencia: str, hora: str = "06:00", exe: str | None = None) -> list[str]:
    if comando not in COMANDOS:
        raise ErroAgenda(f"comando desconhecido: {comando}")
    partes = hora.strip().split(":")
    if len(partes) != 2 or not all(p.isdigit() for p in partes) or not (0 <= int(partes[0]) < 24 and 0 <= int(partes[1]) < 60):
        raise ErroAgenda(f"horário inválido: {hora!r} (use HH:MM, ex.: 06:00)")
    hora = f"{int(partes[0]):02d}:{int(partes[1]):02d}"
    quando = {FREQUENCIAS[0]: ["/SC", "DAILY", "/ST", hora],
              FREQUENCIAS[1]: ["/SC", "WEEKLY", "/D", "MON", "/ST", hora],
              FREQUENCIAS[2]: ["/SC", "HOURLY", "/MO", "6", "/ST", hora],
              FREQUENCIAS[3]: ["/SC", "HOURLY", "/MO", "1", "/ST", hora]}.get(frequencia)
    if quando is None:
        raise ErroAgenda(f"frequência desconhecida: {frequencia}")
    return ["schtasks", "/Create", "/TN", nome_da_tarefa(comando), "/TR", f"{exe or programa()} {comando}",
            *quando, "/F"]


def _rodar(comando: list[str], rodar=None) -> subprocess.CompletedProcess:
    if rodar is None:
        if sys.platform != "win32":
            raise ErroAgenda("o Agendador de Tarefas só existe no Windows (no Linux/Mac, use o cron)")
        rodar = subprocess.run
    r = rodar(comando, capture_output=True, text=True, **SEM_JANELA)
    if r.returncode != 0:
        raise ErroAgenda((r.stderr or r.stdout or "").strip() or f"o Agendador recusou (código {r.returncode})")
    return r


def agendar(comando: str, frequencia: str, hora: str = "06:00", rodar=None) -> str:
    _rodar(comando_criar(comando, frequencia, hora), rodar)
    return nome_da_tarefa(comando)


def remover(comando: str, rodar=None) -> None:
    _rodar(["schtasks", "/Delete", "/TN", nome_da_tarefa(comando), "/F"], rodar)


def listar(rodar=None) -> list[tuple[str, str, str]]:
    """[(comando, próxima execução, situação)] das tarefas do Maestro."""
    r = _rodar(["schtasks", "/Query", "/FO", "CSV", "/NH"], rodar)
    tarefas = []
    for linha in csv.reader(io.StringIO(r.stdout)):
        if len(linha) >= 3 and linha[0].lstrip("\\").startswith(PASTA + "\\"):
            comando = "--" + linha[0].lstrip("\\")[len(PASTA) + 1:]
            if comando in COMANDOS:
                tarefas.append((comando, linha[1], linha[2]))
    return tarefas
