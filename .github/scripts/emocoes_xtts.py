"""XTTS-v2: as falas de emoção com as 2 vozes prontas (frase a frase, sem o ponto final) e as referências das vozes
para o Chatterbox imitar. Uso: python emocoes_xtts.py <saida>"""
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

os.environ["COQUI_TOS_AGREED"] = "1"
sys.path.insert(0, str(Path(__file__).parent))
from TTS.api import TTS                      # noqa: E402

from emocoes_comum import EMOCOES, REFERENCIA, VOZES, frases_para_falar   # noqa: E402

SAIDA = Path(sys.argv[1])
SAIDA.mkdir(parents=True, exist_ok=True)
tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to("cpu")
taxa = getattr(tts.synthesizer, "output_sample_rate", 24000) or 24000


def falar(texto, voz, nome):
    partes = []
    for frase, pausa in frases_para_falar(texto):
        partes.append(np.asarray(tts.tts(text=frase, language="pt", speaker=voz, split_sentences=False), np.float32))
        if pausa:
            partes.append(np.zeros(int(taxa * pausa), np.float32))
    tts.synthesizer.save_wav(wav=np.concatenate(partes), path=str(SAIDA / f"{nome}.wav"))


tempos = {}
for genero, voz in VOZES.items():
    falar(REFERENCIA, voz, f"ref_{genero}")
for chave, _, texto, genero, _, _ in EMOCOES:
    t0 = time.time()
    falar(texto, VOZES[genero], f"xtts_{chave}")
    tempos[chave] = round(time.time() - t0, 1)
    print(chave, tempos[chave], "s", flush=True)
(SAIDA / "tempos_xtts.json").write_text(json.dumps(tempos), encoding="utf-8")
