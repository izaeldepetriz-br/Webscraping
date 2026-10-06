# -*- mode: python ; coding: utf-8 -*-
# Receita do PyInstaller: gera a pasta dist/videoscraper com o programa pronto (sem precisar do Python).
#   Windows: gerar_exe.bat     Outros: python -m PyInstaller videoscraper.spec --noconfirm
from PyInstaller.utils.hooks import collect_all, collect_data_files

datas = collect_data_files("customtkinter")                                   # temas e fontes da janela
datas += [("jellyfin_tools/catalogo_filmes.json", "jellyfin_tools")]          # catálogo local
import os  # noqa: E402
if os.path.exists("videoscraper/versao_build.txt"):                          # a versão (gravada pelo GitHub)
    datas += [("videoscraper/versao_build.txt", "videoscraper")]
binaries, hiddenimports = [], ["videoscraper.app_moderna", "videoscraper.gui", "videoscraper.menu"]
hiddenimports += ["pystray._win32", "PIL.Image", "PIL.ImageDraw"]               # ícone perto do relógio
for pacote in ("imageio_ffmpeg", "playwright", "pystray"):                    # ffmpeg, instalador do navegador, ícone
    d, b, h = collect_all(pacote)
    datas, binaries, hiddenimports = datas + d, binaries + b, hiddenimports + h

import sys  # noqa: E402
sys.path.insert(0, os.path.abspath("."))
from videoscraper.icone import salvar_ico  # noqa: E402
icone_exe = str(salvar_ico(os.path.join("build", "maestro.ico")))           # o "M" com a batuta, no .exe

a = Analysis(["iniciar.py"], pathex=[], binaries=binaries, datas=datas, hiddenimports=hiddenimports,
             excludes=["pytest", "PyInstaller"], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="videoscraper",   # nome técnico (atualização)
          console=False,                       # abre só a janela, sem a tela preta
          icon=icone_exe,                      # ícone do Maestro no Explorer, nos atalhos e na barra
          upx=False)
# Maestro.exe: o que você usa (atalhos, Iniciar com o Windows). O videoscraper.exe continua junto porque as
# versões antigas, ao se atualizar, procuram esse nome e reabrem por ele (o programa o deixa escondido).
exe_maestro = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Maestro", console=False, icon=icone_exe,
                  upx=False)
coll = COLLECT(exe, exe_maestro, a.binaries, a.datas, name="videoscraper", upx=False)
