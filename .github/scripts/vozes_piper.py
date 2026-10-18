"""Piper (o motor grátis de hoje no Maestro): as falas do guarda com as vozes faber e edresson.

Uso: python vozes_piper.py <pasta_saida> <programa_piper> <pasta_das_vozes>
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from vozes_comum import CENA_PT, TEXTO_REFERENCIA   # noqa: E402

SAIDA, PIPER, VOZES = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
SAIDA.mkdir(parents=True, exist_ok=True)


def falar(texto, voz, nome):
    subprocess.run([PIPER, "-m", str(VOZES / f"pt_BR-{voz}.onnx"), "-f", str(SAIDA / f"{nome}.wav"), "-q"],
                   input=texto.encode(), check=True)


for voz in ("faber-medium", "edresson-low"):
    rotulo = voz.split("-")[0]
    for i, texto in enumerate(CENA_PT):
        falar(texto, voz, f"{rotulo}_pt_{i}")
falar(TEXTO_REFERENCIA, "faber-medium", "faber_ref")
print(sorted(p.name for p in SAIDA.glob("*.wav")))
