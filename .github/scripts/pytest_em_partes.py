"""Roda os testes de um arquivo em partes, cada parte num processo NOVO do Python.

Por quê: cada teste da janela moderna abre e fecha uma janela inteira, e o Tk acumula recursos no processo. Com
~180 janelas no mesmo processo, fechar a janela passou a derrubar o Python ("Segmentation fault", código 139), no
GitHub e no PC. Em partes de ~60, cada processo começa limpo.

Uso (com a tela virtual): xvfb-run -a python pytest_em_partes.py tests/test_gui_moderna.py 3 -q -rfE
"""
import math
import subprocess
import sys


def main() -> int:
    arquivo, partes, extra = sys.argv[1], int(sys.argv[2]), sys.argv[3:]
    coleta = subprocess.run([sys.executable, "-m", "pytest", arquivo, "--collect-only", "-q", "-p",
                             "no:cacheprovider"], capture_output=True, text=True)
    testes = [linha.strip() for linha in coleta.stdout.splitlines() if "::" in linha]
    if not testes:
        print(coleta.stdout[-3000:], coleta.stderr[-3000:], sep="\n")
        print("Nenhum teste coletado.")
        return 1
    tamanho = math.ceil(len(testes) / partes)
    codigos = []
    for n in range(0, len(testes), tamanho):
        parte = testes[n:n + tamanho]
        print(f"===== Parte {n // tamanho + 1}: {len(parte)} de {len(testes)} testes =====", flush=True)
        codigos.append(subprocess.run([sys.executable, "-m", "pytest", *parte, *extra]).returncode)
    print(f"===== Partes: {codigos} =====", flush=True)
    return next((c for c in codigos if c != 0), 0)


if __name__ == "__main__":
    sys.exit(main())
