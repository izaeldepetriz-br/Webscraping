"""OpenVoice V2 (licença MIT): não fala português sozinho; troca o TIMBRE de uma fala já pronta.

Aqui a fala em português vem do Piper (a voz "faber", a padrão do Maestro) e o OpenVoice troca o timbre dela pelo
da voz-alvo. O ritmo e a entonação continuam os do Piper: só a "cor" da voz muda.

Uso: python vozes_openvoice.py <pasta_saida> <ref_alvo.wav> <pasta_piper_pt>
  <pasta_piper_pt>: faber_pt_N.wav (as falas) e faber_ref.wav (o Piper lendo o texto de referência)
"""

import json
import sys
import time
from pathlib import Path

from huggingface_hub import hf_hub_download
from openvoice import api

# defeito do OpenVoice: o ToneColorConverter repassa "enable_watermark" para a classe de base, que não aceita
_base = api.OpenVoiceBaseClass.__init__
api.OpenVoiceBaseClass.__init__ = lambda self, config_path, device="cuda:0", **_: _base(self, config_path, device)

SAIDA, REF, PIPER = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
SAIDA.mkdir(parents=True, exist_ok=True)
inicio = time.time()
config = hf_hub_download("myshell-ai/OpenVoiceV2", "converter/config.json")
pesos = hf_hub_download("myshell-ai/OpenVoiceV2", "converter/checkpoint.pth")
conversor = api.ToneColorConverter(config, device="cpu", enable_watermark=False)
conversor.load_ckpt(pesos)
origem = conversor.extract_se([str(PIPER / "faber_ref.wav")])     # o timbre do Piper
alvo = conversor.extract_se([REF])                                 # o timbre que queremos
print(f"modelo carregado em {time.time() - inicio:.0f} s", flush=True)
tempos = []
for fala in sorted(PIPER.glob("faber_pt_*.wav")):
    t0 = time.time()
    nome = fala.name.replace("faber_", "openvoice_")
    conversor.convert(str(fala), origem, alvo, output_path=str(SAIDA / nome), tau=0.3)
    tempos.append({"arquivo": nome, "segundos_para_gerar": round(time.time() - t0, 2)})
    print(json.dumps(tempos[-1]), flush=True)
(SAIDA / "tempos_openvoice.json").write_text(json.dumps(tempos, indent=1), encoding="utf-8")
print(f"pronto em {time.time() - inicio:.0f} s")
