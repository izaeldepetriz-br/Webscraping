#!/usr/bin/env python3
"""Ponto de entrada. Abre a JANELA moderna (Dark Mode).
   Janela clássica (cinza):  python iniciar.py --classica
   Menu de texto antigo:     python iniciar.py --texto
   Autoteste do pacote:      python iniciar.py --verificar
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
            messagebox.showerror("Maestro", mensagem)
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


def _verificar() -> int:
    """Autoteste do pacote (usado ao gerar o .exe): tudo que o programa precisa veio junto?"""
    import os
    from jellyfin_tools import CatalogoLocal, organizar_pasta  # noqa: F401
    from jellyfin_tools.espelho import verificar_links  # noqa: F401
    from videoscraper import app_moderna  # noqa: F401
    from videoscraper.navegador import comando_instalar_chromium
    import customtkinter  # noqa: F401
    import imageio_ffmpeg
    catalogo = CatalogoLocal.padrao()
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    comando, _ = comando_instalar_chromium()
    faltando = [c for c in comando[:2] if getattr(sys, "frozen", False) and not os.path.exists(c)]
    from videoscraper.atualizacao import versao_atual
    from videoscraper import bandeja
    from jellyfin_tools.conflitos import nota  # noqa: F401
    from jellyfin_tools.tv_ao_vivo import ler_m3u  # noqa: F401
    if sys.platform == "win32" and not bandeja.disponivel():
        faltando.append("pystray (ícone perto do relógio)")
    print(f"ok: versão {versao_atual()}, {len(catalogo.filmes)} títulos no catálogo, ffmpeg em {ffmpeg}, "
          f"instalador do navegador {'OK' if not faltando else 'FALTANDO: ' + str(faltando)}")
    return 1 if faltando else 0


def _verificar_navegador() -> int:
    """Autoteste do modo navegador (usado ao gerar o .exe): baixa o Chromium, se faltar, e abre uma página."""
    import tempfile
    from videoscraper.navegador import Navegador
    with tempfile.TemporaryDirectory() as perfil, Navegador(perfil=perfil, timeout=120) as nav:
        pagina = nav.contexto.new_page()
        pagina.set_content("<title>navegador ok</title>")
        titulo = pagina.title()
    print(f"ok: {titulo}")
    return 0 if titulo == "navegador ok" else 1


if __name__ == "__main__":
    if "--verificar" in sys.argv:
        raise SystemExit(_verificar())
    if "--verificar-navegador" in sys.argv:
        raise SystemExit(_verificar_navegador())
    if "--testar-atualizacao" in sys.argv:          # GitHub: a troca dos arquivos funciona no Windows de verdade?
        from pathlib import Path
        from videoscraper import atualizacao
        import tempfile
        import traceback
        zip_ = Path(sys.argv[sys.argv.index("--testar-atualizacao") + 1])
        relatorio = Path(tempfile.gettempdir()) / "videoscraper-teste-atualizacao.txt"
        try:
            script = atualizacao.instalar_ao_fechar(zip_, reabrir=False)
            import time
            time.sleep(3)                           # o PowerShell continua vivo (esperando este fechar)?
            codigo = atualizacao.ultimo_processo.poll() if atualizacao.ultimo_processo else "?"
            relatorio.write_text(f"script iniciado: {script}\n"
                                 f"PowerShell depois de 3 s: {'rodando' if codigo is None else f'saiu com {codigo}'}\n",
                                 encoding="utf-8")
        except Exception:                           # sem console: o motivo vai para um arquivo
            relatorio.write_text(traceback.format_exc(), encoding="utf-8")
            raise SystemExit(1)
        raise SystemExit(0)                         # fecha: o script espera isto para trocar os arquivos
    if "--testar-instalacao" in sys.argv:           # GitHub: o lugar fixo e os atalhos funcionam no Windows?
        from pathlib import Path
        from videoscraper import atualizacao, instalacao
        import tempfile
        import traceback
        relatorio = Path(tempfile.gettempdir()) / "videoscraper-teste-instalacao.txt"
        try:
            exe = instalacao.copiar_para_pasta_fixa(atualizacao.pasta_do_programa())
            instalacao.criar_atalhos(exe)
            relatorio.write_text(f"instalado: {exe}\n", encoding="utf-8")
        except Exception:
            relatorio.write_text(traceback.format_exc(), encoding="utf-8")
            raise SystemExit(1)
        raise SystemExit(0)
    if "--texto" in sys.argv:
        raise SystemExit(_menu_texto())
    try:
        from videoscraper import gui
    except ImportError:                       # Python sem Tkinter (raro no Windows)
        _avisar("Este Python não tem a biblioteca de janelas (Tkinter).\n"
                "Reinstale o Python marcando 'tcl/tk and IDLE'. Abrindo o menu de texto...")
        raise SystemExit(_menu_texto() if sys.stdout else 1)
    if "--classica" not in sys.argv:
        try:                                  # interface moderna (Dark Mode, CustomTkinter)
            from videoscraper import app_moderna
        except ImportError:                   # customtkinter não instalado: usa a clássica
            pass
        else:
            raise SystemExit(app_moderna.main())
    raise SystemExit(gui.main())
