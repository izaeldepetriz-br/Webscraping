#!/usr/bin/env python3
"""Ponto de entrada. Abre a JANELA com botões.
   Menu de texto antigo:  python iniciar.py --texto
"""

import sys


def _avisar(mensagem: str) -> None:
    """Mostra o erro numa caixa de diálogo (sem tela preta) ou no terminal."""
    if sys.stdout is None:                    # aberto com pythonw (sem console)
        try:
            import tkinter as tk
            from tkinter import messagebox
            raiz = tk.Tk()
            raiz.withdraw()
            messagebox.showerror("videoscraper", mensagem)
            raiz.destroy()
        except Exception:
            pass
        return
    print(mensagem)
    try:
        input("\nPressione Enter para fechar...")
    except (EOFError, RuntimeError):
        pass


# Se faltar alguma biblioteca, avisa em português (sem a janela sumir sem explicação).
try:
    import bs4  # noqa: F401
    import lxml  # noqa: F401
    import requests  # noqa: F401
    from videoscraper import menu
except ModuleNotFoundError as erro:
    _avisar(f"Falta instalar a biblioteca: {erro.name}\n\n"
            "Feche e dê duplo clique em 'iniciar.bat' (ele instala tudo sozinho),\n"
            f"ou rode no terminal:  {sys.executable} -m pip install -r requirements.txt")
    raise SystemExit(1)


def _menu_texto() -> int:
    try:
        codigo = menu.main()
    except KeyboardInterrupt:
        print("\nInterrompido.")
        codigo = 130
    input("\nPressione Enter para fechar...")
    return codigo


if __name__ == "__main__":
    if "--texto" in sys.argv:
        raise SystemExit(_menu_texto())
    try:
        from videoscraper import gui
    except ImportError:                       # Python sem Tkinter (raro no Windows)
        _avisar("Este Python não tem a biblioteca de janelas (Tkinter).\n"
                "Reinstale o Python marcando 'tcl/tk and IDLE'. Abrindo o menu de texto...")
        raise SystemExit(_menu_texto() if sys.stdout else 1)
    raise SystemExit(gui.main())
