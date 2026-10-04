#!/usr/bin/env python3
"""Ponto de entrada com menu. Duplo clique no iniciar.bat (Windows) ou ./iniciar.sh."""

import sys

# Se faltar alguma biblioteca, avisa em português e segura a janela aberta
# (sem isso, no Windows, a janela fecha antes de dar tempo de ler o erro).
try:
    import bs4  # noqa: F401
    import lxml  # noqa: F401
    import requests  # noqa: F401
    from videoscraper import menu
except ModuleNotFoundError as erro:
    print(f"❌ Falta instalar a biblioteca: {erro.name}")
    print("   Feche esta janela e dê duplo clique em 'iniciar.bat' (ele instala tudo sozinho),")
    print(f"   ou rode no terminal:  {sys.executable} -m pip install -r requirements.txt")
    input("\nPressione Enter para fechar...")
    raise SystemExit(1)

if __name__ == "__main__":
    try:
        codigo = menu.main()
    except KeyboardInterrupt:
        print("\nInterrompido.")
        codigo = 130
    input("\nPressione Enter para fechar...")
    raise SystemExit(codigo)
