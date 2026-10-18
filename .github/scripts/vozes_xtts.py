"""XTTS-v2 (licença CPML: só uso NÃO comercial): as vozes prontas falando português.

Uso: python vozes_xtts.py <pasta_saida> referencia|tudo
  referencia  só a voz-alvo lendo o texto de referência (ref_alvo.wav), para os outros motores imitarem
  tudo        a cena do guarda (inglês e português) com 4 vozes prontas + o catálogo de todas as vozes
"""

import json
import os
import sys
import time
from pathlib import Path

os.environ["COQUI_TOS_AGREED"] = "1"      # aceita a licença CPML (uso não comercial: teste pessoal)
sys.path.insert(0, str(Path(__file__).parent))

from TTS.api import TTS                    # noqa: E402

from vozes_comum import CENA_EN, CENA_PT, FRASE_CATALOGO, GUARDAS, TEXTO_REFERENCIA, VOZ_ALVO   # noqa: E402

SAIDA, MODO = Path(sys.argv[1]), sys.argv[2]
SAIDA.mkdir(parents=True, exist_ok=True)
inicio = time.time()
tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to("cpu")
vozes = list(tts.speakers or [])
print(f"modelo carregado em {time.time() - inicio:.0f} s; {len(vozes)} vozes prontas: {vozes}", flush=True)
alvo = VOZ_ALVO if VOZ_ALVO in vozes else ([v for v in GUARDAS if v in vozes] or vozes)[0]
tempos = []


def falar(texto, voz, idioma, nome):
    t0 = time.time()
    tts.tts_to_file(texto, speaker=voz, language=idioma, file_path=str(SAIDA / f"{nome}.wav"))
    tempos.append({"arquivo": f"{nome}.wav", "voz": voz, "texto": texto, "idioma": idioma,
                   "segundos_para_gerar": round(time.time() - t0, 2)})
    print(json.dumps(tempos[-1], ensure_ascii=False), flush=True)


if MODO == "referencia":
    falar(TEXTO_REFERENCIA, alvo, "pt", "ref_alvo")
else:
    for voz in [v for v in GUARDAS if v in vozes] or vozes[-4:]:
        rotulo = voz.split()[0].lower()
        for i, (en, pt) in enumerate(zip(CENA_EN, CENA_PT)):
            falar(en, voz, "en", f"cena_{rotulo}_en_{i}")
            falar(pt, voz, "pt", f"cena_{rotulo}_pt_{i}")
    for i, voz in enumerate(vozes):
        falar(FRASE_CATALOGO, voz, "pt", f"catalogo_{i:02d}")
(SAIDA / f"tempos_xtts_{MODO}.json").write_text(json.dumps({"alvo": alvo, "vozes": vozes, "falas": tempos},
                                                           ensure_ascii=False, indent=1), encoding="utf-8")
print(f"pronto em {time.time() - inicio:.0f} s")
