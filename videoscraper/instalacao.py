"""Lugar FIXO do programa no Windows e os atalhos (Área de Trabalho e Menu Iniciar).

Antes, o programa ficava onde a pessoa extraía o .zip (ex.: Downloads\\videoscraper-windows\\...): cada download
virava mais uma cópia e a atualização trocava só a cópia que estava aberta. Agora ele mora sempre em

    C:\\Users\\<você>\\AppData\\Local\\Programs\\videoscraper\\videoscraper.exe

(o lugar padrão do Windows para programas de um usuário: não precisa de administrador). Os atalhos apontam para
lá, a atualização troca os arquivos de lá e o "Iniciar com o Windows" também. As configurações continuam em
C:\\Users\\<você>\\.videoscraper (não mudam de lugar).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

NOME = "videoscraper"


def pasta_fixa() -> Path:
    local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(local) / "Programs" / NOME


def executavel_fixo() -> Path:
    return pasta_fixa() / f"{NOME}.exe"


def esta_na_pasta_fixa(pasta_atual: str | Path) -> bool:
    try:
        return Path(pasta_atual).resolve() == pasta_fixa().resolve()
    except OSError:
        return False


def copiar_para_pasta_fixa(origem: str | Path, destino: str | Path | None = None) -> Path:
    """Copia a pasta do programa (o .exe e a pasta _internal) para o lugar fixo, por cima do que houver lá.
    Devolve o caminho do .exe novo. Lança OSError se não der (ex.: disco cheio)."""
    origem, destino = Path(origem), Path(destino or pasta_fixa())
    if not (origem / f"{NOME}.exe").is_file():
        raise OSError(f"não achei o {NOME}.exe em {origem}")
    destino.mkdir(parents=True, exist_ok=True)
    shutil.copytree(origem, destino, dirs_exist_ok=True)
    return destino / f"{NOME}.exe"


def script_atalhos(executavel: str | Path) -> str:
    """PowerShell que cria (ou refaz) o atalho na Área de Trabalho e no Menu Iniciar."""
    def aspas(texto) -> str:
        return "'" + str(texto).replace("'", "''") + "'"
    exe = Path(executavel)
    return f"""$ErrorActionPreference = 'Stop'
$ws = New-Object -ComObject WScript.Shell
foreach ($pasta in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {{
    $atalho = $ws.CreateShortcut((Join-Path $pasta {aspas(NOME + '.lnk')}))
    $atalho.TargetPath = {aspas(exe)}
    $atalho.WorkingDirectory = {aspas(exe.parent)}
    $atalho.IconLocation = {aspas(str(exe) + ',0')}
    $atalho.Description = 'videoscraper: organizar a biblioteca do Jellyfin'
    $atalho.Save()
}}
"""


def criar_atalhos(executavel: str | Path, rodar=subprocess.run) -> None:
    """Atalho "videoscraper" na Área de Trabalho e no Menu Iniciar apontando para o .exe. Lança OSError se falhar."""
    if sys.platform != "win32":
        raise OSError("atalhos só no Windows")
    powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / \
        "powershell.exe"
    resultado = rodar([str(powershell) if powershell.exists() else "powershell", "-NoProfile", "-NonInteractive",
                       "-ExecutionPolicy", "Bypass", "-Command", script_atalhos(executavel)],
                      capture_output=True, text=True, timeout=60, creationflags=0x08000000)   # CREATE_NO_WINDOW
    if resultado.returncode != 0:
        raise OSError((resultado.stderr or resultado.stdout or "o PowerShell recusou").strip()[:300])


def abrir(executavel: str | Path) -> None:
    """Abre o programa (o do lugar fixo) como um processo separado."""
    subprocess.Popen([str(executavel)], cwd=str(Path(executavel).parent), close_fds=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=0x00000008 | 0x00000200 if sys.platform == "win32" else 0)
