"""F5-TTS em português (o ajuste firstpixel/F5-TTS-pt-br, licença CC-BY-NC: só uso não comercial): as 8 falas de
emoção imitando as mesmas 2 vozes do teste (as referências geradas pelo XTTS-v2) e o que o Whisper ouve de cada uma.
Também ouve as falas do XTTS-v2 e do Chatterbox daquele teste (para comparar). Uso:
python f5_teste.py <saida> <pasta com ref_f.wav, ref_m.wav e xtts_*.wav> <pasta com chatterbox_*.wav>"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf
from huggingface_hub import hf_hub_download, list_repo_files

sys.path.insert(0, str(Path(__file__).parent))
from emocoes_comum import EMOCOES, REFERENCIA, frases_para_falar   # noqa: E402

SAIDA, REFS, OUTROS = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
SAIDA.mkdir(parents=True, exist_ok=True)
REPO = "firstpixel/F5-TTS-pt-br"
arquivos = list_repo_files(REPO)
print("arquivos do modelo:", arquivos, flush=True)
pesos = sorted([a for a in arquivos if a.endswith((".safetensors", ".pt"))], key=lambda a: (a.endswith(".pt"), a))
vocab = next((a for a in arquivos if a.endswith("vocab.txt")), "")
print(f"::notice title=F5 pesos::{pesos} vocab={vocab}", flush=True)
try:
    leia = Path(hf_hub_download(REPO, "README.md")).read_text(encoding="utf-8")[:1500]
    print("::notice title=F5 leia-me::" + leia.replace("%", "%25").replace("\n", "%0A"), flush=True)
except Exception as erro:
    print("sem leia-me:", erro)

from f5_tts.api import F5TTS  # noqa: E402

vocab_local = hf_hub_download(REPO, vocab) if vocab else ""
modelo = None
for peso in pesos:
    for arquitetura in ("F5TTS_v1_Base", "F5TTS_Base"):
        try:
            modelo = F5TTS(model=arquitetura, ckpt_file=hf_hub_download(REPO, peso), vocab_file=vocab_local, device="cpu")
            print(f"::notice title=F5 carregado::{peso} com {arquitetura}", flush=True)
            break
        except Exception as erro:
            print(f"não carregou {peso} com {arquitetura}: {type(erro).__name__}: {str(erro)[:200]}", flush=True)
    if modelo:
        break
if modelo is None:
    raise SystemExit("nenhum peso do F5-TTS pt-br carregou")

from faster_whisper import WhisperModel  # noqa: E402
ouvido = WhisperModel("small", device="cpu", compute_type="int8")
resultado = []
for motor, pasta in (("xtts", REFS), ("chatterbox", OUTROS)):          # os outros dois motores, para comparar
    for chave, emocao, texto, _, _, _ in EMOCOES:
        arquivo = pasta / f"{motor}_{chave}.wav"
        if arquivo.is_file():
            segmentos, _ = ouvido.transcribe(str(arquivo), language="pt", beam_size=5)
            texto_ouvido = " ".join(s.text.strip() for s in segmentos)
            resultado.append({"motor": motor, "emocao": emocao, "texto": texto, "ouvido": texto_ouvido,
                              "leu_ponto": "ponto" in texto_ouvido.lower()})
            print(f"{motor} · {emocao}: {texto_ouvido}", flush=True)
for chave, emocao, texto, genero, _, _ in EMOCOES:
    t0, partes = time.time(), []
    for frase, pausa in frases_para_falar(texto):
        wav, taxa, _ = modelo.infer(ref_file=str(REFS / f"ref_{genero}.wav"), ref_text=REFERENCIA, gen_text=frase,
                                    show_info=lambda *a, **k: None, progress=None, seed=7)
        partes.append(np.asarray(wav, dtype=np.float32))
        if pausa:
            partes.append(np.zeros(int(taxa * pausa), np.float32))
    destino = SAIDA / f"f5_{chave}.wav"
    sf.write(destino, np.concatenate(partes), taxa)
    segmentos, _ = ouvido.transcribe(str(destino), language="pt", beam_size=5)
    texto_ouvido = " ".join(s.text.strip() for s in segmentos)
    resultado.append({"motor": "f5", "emocao": emocao, "texto": texto, "ouvido": texto_ouvido,
                      "segundos_para_gerar": round(time.time() - t0, 1), "leu_ponto": "ponto" in texto_ouvido.lower()})
    print(f"::notice title=f5 · {emocao}::{texto_ouvido}", flush=True)
(SAIDA / "f5.json").write_text(json.dumps(resultado, ensure_ascii=False, indent=1), encoding="utf-8")
