# -*- mode: python ; coding: utf-8 -*-
# Receita do PyInstaller: gera a pasta dist/videoscraper com o programa pronto (sem precisar do Python).
#   Windows: gerar_exe.bat     Outros: python -m PyInstaller videoscraper.spec --noconfirm
from PyInstaller.utils.hooks import collect_all, collect_data_files

datas = collect_data_files("customtkinter")                                   # temas e fontes da janela
datas += [("jellyfin_tools/catalogo_filmes.json", "jellyfin_tools")]          # catálogo local
binaries, hiddenimports = [], ["videoscraper.app_moderna", "videoscraper.gui", "videoscraper.menu"]
for pacote in ("imageio_ffmpeg", "playwright"):                               # ffmpeg e o instalador do navegador
    d, b, h = collect_all(pacote)
    datas, binaries, hiddenimports = datas + d, binaries + b, hiddenimports + h

a = Analysis(["iniciar.py"], pathex=[], binaries=binaries, datas=datas, hiddenimports=hiddenimports,
             excludes=["pytest", "PyInstaller"], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="videoscraper",
          console=False,                       # abre só a janela, sem a tela preta
          upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name="videoscraper", upx=False)
