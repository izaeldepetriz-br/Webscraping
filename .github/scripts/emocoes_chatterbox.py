"""Chatterbox: as mesmas falas, imitando as mesmas 2 vozes do XTTS-v2, com a intensidade de emoção de cada uma.
Uso: python emocoes_chatterbox.py <saida> <pasta com ref_f.wav e ref_m.wav>"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import torch                                              # noqa: E402
import torchaudio                                         # noqa: E402
from chatterbox.mtl_tts import ChatterboxMultilingualTTS  # noqa: E402

from emocoes_comum import EMOCOES, frases_para_falar     # noqa: E402

SAIDA, REFS = Path(sys.argv[1]), Path(sys.argv[2])
SAIDA.mkdir(parents=True, exist_ok=True)
modelo = ChatterboxMultilingualTTS.from_pretrained(device="cpu")
for chave, _, texto, genero, exagero, cfg in EMOCOES:
    partes = []
    for frase, pausa in frases_para_falar(texto):
        partes.append(modelo.generate(frase, language_id="pt", audio_prompt_path=str(REFS / f"ref_{genero}.wav"),
                                      exaggeration=exagero, cfg_weight=cfg))
        if pausa:
            partes.append(torch.zeros(1, int(modelo.sr * pausa)))
    torchaudio.save(str(SAIDA / f"chatterbox_{chave}.wav"), torch.cat(partes, dim=1), modelo.sr)
    print(chave, "ok", flush=True)
