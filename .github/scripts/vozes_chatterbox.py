"""Chatterbox Multilingual (licença MIT): a voz padrão e a imitação da voz-alvo, falando português.

Uso: python vozes_chatterbox.py <pasta_saida> <ref_alvo.wav>
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import torchaudio                                         # noqa: E402
from chatterbox.mtl_tts import ChatterboxMultilingualTTS  # noqa: E402

from vozes_comum import CENA_PT                           # noqa: E402

SAIDA, REF = Path(sys.argv[1]), sys.argv[2]
SAIDA.mkdir(parents=True, exist_ok=True)
inicio = time.time()
modelo = ChatterboxMultilingualTTS.from_pretrained(device="cpu")
print(f"modelo carregado em {time.time() - inicio:.0f} s", flush=True)
tempos = []
for rotulo, referencia in (("padrao", None), ("clone", REF)):
    for i, texto in enumerate(CENA_PT):
        t0 = time.time()
        wav = modelo.generate(texto, language_id="pt", audio_prompt_path=referencia)
        torchaudio.save(str(SAIDA / f"chatterbox_{rotulo}_pt_{i}.wav"), wav, modelo.sr)
        tempos.append({"arquivo": f"chatterbox_{rotulo}_pt_{i}.wav", "texto": texto,
                       "segundos_para_gerar": round(time.time() - t0, 2)})
        print(json.dumps(tempos[-1], ensure_ascii=False), flush=True)
(SAIDA / "tempos_chatterbox.json").write_text(json.dumps(tempos, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"pronto em {time.time() - inicio:.0f} s")
