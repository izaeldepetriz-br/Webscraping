#!/usr/bin/env python3
"""Ponto de entrada. Abre a JANELA moderna (Dark Mode).
   Janela clássica (cinza):  python iniciar.py --classica
   Menu de texto antigo:     python iniciar.py --texto
   Autoteste do pacote:      python iniciar.py --verificar
   Comandos para robôs (RPA, sem janela): --organizar, --conferir-espelhos, --conferir-canais,
   --enviar-tv, --traduzir-legendas (veja videoscraper/automacao.py)
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
    from videoscraper import app_moderna, automacao  # noqa: F401
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
    import anthropic                                           # traduzir legendas: o SDK veio inteiro?
    anthropic.Anthropic(api_key="autoteste")                  # (só monta o cliente; não chama a API)
    import av  # noqa: F401                                   # legenda pelo áudio: Whisper, PyAV e o detector de voz
    import ctranslate2  # noqa: F401
    import faster_whisper
    vad = os.path.join(os.path.dirname(faster_whisper.__file__), "assets", "silero_vad_v6.onnx")
    if not os.path.exists(vad):
        faltando.append("detector de voz do Whisper (silero_vad_v6.onnx)")
    if sys.platform == "win32" and not bandeja.disponivel():
        faltando.append("pystray (ícone perto do relógio)")
    print(f"ok: versão {versao_atual()}, {len(catalogo.filmes)} títulos no catálogo, ffmpeg em {ffmpeg}, "
          f"instalador do navegador {'OK' if not faltando else 'FALTANDO: ' + str(faltando)}")
    return 1 if faltando else 0


def _verificar_audio() -> int:
    """Autoteste de ida e volta (usado ao gerar o .exe, com internet): o Piper FALA uma frase em português, o
    Whisper (modelo tiny) OUVE e o teste confere se entendeu. Prova a dublagem (fase 2) e a legenda (fase 1)."""
    import tempfile
    import traceback
    from pathlib import Path
    relatorio = Path(tempfile.gettempdir()) / "maestro-teste-audio.txt"
    try:
        from jellyfin_tools.dublagem import MotorPiper, preparar_piper, preparar_voz
        from jellyfin_tools.transcricao import Transcritor
        with tempfile.TemporaryDirectory() as pasta:
            pasta = Path(pasta)
            motor = MotorPiper(preparar_piper(pasta / "piper"), preparar_voz("faber", pasta / "vozes"))
            wav = pasta / "frase.wav"
            motor.sintetizar([("Olá! Este é um teste de legenda e dublagem do Maestro.", wav)])
            lingua, duracao, falas = Transcritor(modelo="tiny", pasta_modelos=str(pasta / "modelos")).transcrever(wav)
        texto = " ".join(f.texto.replace("\n", " ") for f in falas)
        ok = any(p in texto.lower() for p in ("teste", "legenda", "dublagem", "maestro"))
        relatorio.write_text(f"idioma: {lingua} | duração: {duracao:.1f} s | ouviu: {texto}", encoding="utf-8")
    except Exception:
        relatorio.write_text(traceback.format_exc()[-1500:], encoding="utf-8")
        return 1
    return 0 if ok else 1


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
    if "--verificar-audio" in sys.argv:
        raise SystemExit(_verificar_audio())
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
            escondido = instalacao.esconder_exe_antigo(exe.parent)
            relatorio.write_text(f"instalado: {exe}\nvideoscraper.exe escondido: {escondido}\n", encoding="utf-8")
        except Exception:
            relatorio.write_text(traceback.format_exc(), encoding="utf-8")
            raise SystemExit(1)
        raise SystemExit(0)
    try:
        from videoscraper import automacao
    except ImportError:                             # sem o customtkinter: só a janela clássica abre
        automacao = None
    if automacao and automacao.foi_pedido(sys.argv[1:]):   # robô (UiPath, BotCity, Agendador): sem janela
        raise SystemExit(automacao.main(sys.argv[1:]))
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
