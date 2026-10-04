@echo off
REM Gera o programa para Windows (pasta dist\videoscraper) - nao precisa de Python para usar depois.
chcp 65001 >nul
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python nao encontrado. Instale em https://www.python.org/downloads/
  pause
  exit /b 1
)
if not exist .venv python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt pyinstaller || (pause & exit /b 1)
python -m PyInstaller videoscraper.spec --noconfirm || (pause & exit /b 1)
REM Autoteste: confere se tudo veio junto no pacote
start "" /wait dist\videoscraper\videoscraper.exe --verificar
if errorlevel 1 (
  echo O autoteste do programa falhou.
  pause
  exit /b 1
)
echo.
echo Pronto: dist\videoscraper\videoscraper.exe
echo Para levar para outro computador, copie a pasta dist\videoscraper INTEIRA.
pause
