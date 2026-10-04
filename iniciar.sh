#!/usr/bin/env bash
# Linux/Mac: ./iniciar.sh  (cria o ambiente na 1a vez e abre o menu)
set -e
cd "$(dirname "$0")"
command -v python3 >/dev/null || { echo "Instale o Python 3: https://www.python.org/downloads/"; exit 1; }
if [ ! -d .venv ]; then
  echo "Criando ambiente virtual..."
  python3 -m venv .venv
  . .venv/bin/activate
  pip install --upgrade pip
  pip install -r requirements.txt
else
  . .venv/bin/activate
fi
python iniciar.py
