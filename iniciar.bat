@echo off
REM Windows: duplo clique. Na 1a vez cria o ambiente, instala as bibliotecas e o navegador.
REM Depois abre a janela do programa.
chcp 65001 >nul
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python nao encontrado. Instale em https://www.python.org/downloads/
  echo e marque a opcao "Add python.exe to PATH" na instalacao.
  pause
  exit /b 1
)
if not exist .venv (
  echo Criando ambiente virtual...
  python -m venv .venv || (pause & exit /b 1)
)
call .venv\Scripts\activate.bat
REM O marcador muda quando as dependencias mudam; assim quem ja tinha .venv atualiza sozinho.
if not exist .venv\instalado-v3 (
  echo Instalando bibliotecas - so na primeira vez...
  python -m pip install --upgrade pip
  pip install -r requirements.txt || (pause & exit /b 1)
  echo Baixando o navegador Chromium para o modo navegador, cerca de 150 MB...
  python -m playwright install chromium || (pause & exit /b 1)
  echo ok> .venv\instalado-v3
)
REM pythonw = abre so a janela, sem a tela preta. Menu de texto: python iniciar.py --texto
start "" pythonw iniciar.py
