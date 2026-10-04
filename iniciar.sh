#!/usr/bin/env bash
# Linux/Mac: ./iniciar.sh  (na 1a vez cria o ambiente, instala as bibliotecas e o navegador)
set -e
cd "$(dirname "$0")"
command -v python3 >/dev/null || { echo "Instale o Python 3: https://www.python.org/downloads/"; exit 1; }
[ -d .venv ] || { echo "Criando ambiente virtual..."; python3 -m venv .venv; }
. .venv/bin/activate
if [ ! -f .venv/instalado-v3 ]; then
  pip install --upgrade pip
  pip install -r requirements.txt
  python -m playwright install chromium
  touch .venv/instalado-v3
fi
python iniciar.py
