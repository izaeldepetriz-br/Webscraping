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


def comando(executavel: str | Path | None = None) -> str:
    """O que o Windows roda ao entrar. executavel: outro .exe (ex.: o do lugar fixo, logo depois de instalar)."""
    if executavel:
        return f'"{executavel}" --minimizado'
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


def ativar(ligar: bool, registro=None, executavel: str | Path | None = None) -> None:
    """Liga/desliga. Lança OSError fora do Windows (ou se o registro recusar)."""
    reg = registro or _registro()
    with reg.CreateKey(reg.HKEY_CURRENT_USER, CHAVE) as chave:
        if ligar:
            reg.SetValueEx(chave, NOME, 0, reg.REG_SZ, comando(executavel))
        else:
            try:
                reg.DeleteValue(chave, NOME)
            except FileNotFoundError:
                pass


def comando_registrado(registro=None) -> str:
    """O comando que está hoje no registro ('' se não está ligado)."""
    try:
        reg = registro or _registro()
        with reg.OpenKey(reg.HKEY_CURRENT_USER, CHAVE) as chave:
            valor, _ = reg.QueryValueEx(chave, NOME)
            return str(valor or "")
    except OSError:
        return ""


def corrigir_se_preciso(preferido: str | Path | None = None, registro=None) -> bool:
    """Ligado, mas apontando para OUTRO .exe (ex.: uma pasta antiga dos Downloads que já foi apagada)? O Windows
    tenta abrir um arquivo que não existe e não avisa nada. Regrava com o certo: o `preferido` (o do lugar fixo,
    se existir) ou este programa. Devolve True se corrigiu."""
    atual = comando_registrado(registro)
    if not atual:
        return False
    certo = comando(preferido if preferido and Path(preferido).is_file() else None)
    if atual.strip().lower() == certo.strip().lower():
        return False
    ativar(True, registro, preferido if preferido and Path(preferido).is_file() else None)
    return True
