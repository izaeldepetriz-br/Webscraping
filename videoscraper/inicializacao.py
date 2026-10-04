"""Iniciar junto com o Windows, já minimizado perto do relógio.

Usa a chave do registro do PRÓPRIO usuário que o Windows lê ao entrar (não precisa de administrador):
    HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Run   videoscraper = "...videoscraper.exe" --minimizado
É a mesma lista que aparece no Gerenciador de Tarefas > Inicializar (dá para desligar por lá também).
Rodando pelo Python, usa o pythonw.exe (sem a janela preta) + iniciar.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

CHAVE = r"Software\Microsoft\Windows\CurrentVersion\Run"
NOME = "videoscraper"


def comando() -> str:
    """O que o Windows roda ao entrar."""
    if getattr(sys, "frozen", False):                       # o .exe
        return f'"{sys.executable}" --minimizado'
    executavel = Path(sys.executable)
    sem_janela = executavel.with_name("pythonw.exe")
    iniciar = Path(__file__).resolve().parent.parent / "iniciar.py"
    return f'"{sem_janela if sem_janela.exists() else executavel}" "{iniciar}" --minimizado'


def _registro():
    if sys.platform != "win32":
        raise OSError("iniciar junto com o sistema só existe no Windows")
    import winreg
    return winreg


def ativo(registro=None) -> bool:
    try:
        reg = registro or _registro()
        with reg.OpenKey(reg.HKEY_CURRENT_USER, CHAVE) as chave:
            valor, _ = reg.QueryValueEx(chave, NOME)
            return bool(valor)
    except OSError:
        return False


def ativar(ligar: bool, registro=None) -> None:
    """Liga/desliga. Lança OSError fora do Windows (ou se o registro recusar)."""
    reg = registro or _registro()
    with reg.CreateKey(reg.HKEY_CURRENT_USER, CHAVE) as chave:
        if ligar:
            reg.SetValueEx(chave, NOME, 0, reg.REG_SZ, comando())
        else:
            try:
                reg.DeleteValue(chave, NOME)
            except FileNotFoundError:
                pass
