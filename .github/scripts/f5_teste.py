"""F5-TTS em português (o ajuste firstpixel/F5-TTS-pt-br, licença CC-BY-NC: só uso não comercial): UMA das 8 falas
de emoção imitando a mesma voz do teste (as referências geradas pelo XTTS-v2) e o que o Whisper ouve dela.
O workflow roda as 8 emoções em paralelo (uma por máquina) e junta os resultados. Uso:
python f5_teste.py <saida> <pasta com ref_f.wav e ref_m.wav> <emoção (raiva, odio...)>

O modelo pt-br foi treinado na arquitetura F5TTS_Base (a 1ª versão). A F5TTS_v1_Base tem as mesmas peças (os pesos
"encaixam" sem erro), mas outro jeito de juntar texto e posição: com ela a fala sai sem sentido."""
import json
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf
from huggingface_hub import hf_hub_download

sys.path.insert(0, str(Path(__file__).parent))
from emocoes_comum import EMOCOES, REFERENCIA, frases_para_falar   # noqa: E402

SAIDA, REFS, CHAVE = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
SAIDA.mkdir(parents=True, exist_ok=True)
REPO, PESO, ARQUITETURA = "firstpixel/F5-TTS-pt-br", "pt-br/model_last.safetensors", "F5TTS_Base"

from f5_tts.api import F5TTS  # noqa: E402

t0 = time.time()
modelo = F5TTS(model=ARQUITETURA, ckpt_file=hf_hub_download(REPO, PESO), device="cpu")
print(f"::notice title=F5 carregado::{PESO} com {ARQUITETURA} em {time.time() - t0:.0f} s", flush=True)

from faster_whisper import WhisperModel  # noqa: E402
ouvido = WhisperModel("small", device="cpu", compute_type="int8")
chave, emocao, texto, genero, _, _ = next(e for e in EMOCOES if e[0] == CHAVE)
t0, partes, tempos = time.time(), [], []
for frase, pausa in frases_para_falar(texto):
    t1 = time.time()
    # o leia-me do modelo pede texto em minúsculas (e números por extenso)
    wav, taxa, _ = modelo.infer(ref_file=str(REFS / f"ref_{genero}.wav"), ref_text=REFERENCIA.lower(),
                                gen_text=frase.lower(), show_info=lambda *a, **k: None, progress=None, seed=7)
    tempos.append(round(time.time() - t1, 1))
    partes.append(np.asarray(wav, dtype=np.float32))
    if pausa:
        partes.append(np.zeros(int(taxa * pausa), np.float32))
destino = SAIDA / f"f5_{chave}.wav"
sf.write(destino, np.concatenate(partes), taxa)
segmentos, _ = ouvido.transcribe(str(destino), language="pt", beam_size=5)
texto_ouvido = " ".join(s.text.strip() for s in segmentos)
resultado = [{"motor": "f5", "emocao": emocao, "texto": texto, "ouvido": texto_ouvido,
              "segundos_para_gerar": round(time.time() - t0, 1), "segundos_por_frase": tempos,
              "duracao_do_audio": round(sum(len(p) for p in partes) / taxa, 1),
              "leu_ponto": "ponto" in texto_ouvido.lower()}]
print(f"::notice title=f5 · {emocao}::{texto_ouvido} | frases em {tempos} s", flush=True)
(SAIDA / f"f5_{chave}.json").write_text(json.dumps(resultado, ensure_ascii=False, indent=1), encoding="utf-8")
