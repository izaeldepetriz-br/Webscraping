"""Compara os motores de voz com a mesma régua, em todas as falas em português:

  entendido   o Whisper ouve a fala e compara com o texto (1,0 = entendeu tudo; baixo = palavra errada/"alucinada")
  naturalidade  nota do UTMOS (1 a 5): um modelo treinado para prever a nota que PESSOAS dariam à voz
  parecida    semelhança com a voz-alvo (0 a 1), só nos testes de imitar a mesma voz

Uso: python comparar_vozes.py <pasta_com_os_wav>   (lê tudo o que os outros passos gravaram, recursivamente)
Escreve comparativo.json e comparativo.md na mesma pasta e um resumo nas anotações da execução.
"""

import difflib
import json
import re
import sys
import unicodedata
from pathlib import Path

import librosa
import numpy as np
import torch
from faster_whisper import WhisperModel

PASTA = Path(sys.argv[1])
sys.path.insert(0, str(Path(__file__).parent))
from vozes_comum import CENA_PT, FRASE_CATALOGO   # noqa: E402

try:
    from resemblyzer import VoiceEncoder, preprocess_wav
    codificador = VoiceEncoder("cpu")
except Exception as erro:                          # sem a semelhança de voz, o resto continua
    print(f"::warning::sem a medida de semelhança de voz: {erro}")
    codificador = None
mos = torch.hub.load("tarepan/SpeechMOS:v1.2.0", "utmos22_strong", trust_repo=True)
ouvido = WhisperModel("small", device="cpu", compute_type="int8")


def simples(texto):
    texto = unicodedata.normalize("NFD", texto.lower())
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", texto).split())


def voz(caminho):
    return codificador.embed_utterance(preprocess_wav(caminho)) if codificador else None


alvo = next(PASTA.rglob("ref_alvo.wav"), None)
voz_alvo = voz(alvo) if alvo else None
CONJUNTOS = [  # (nome, padrão do arquivo, compara com a voz-alvo?)
    ("Piper edresson (o mais simples)", "edresson_pt_*.wav", False),
    ("Piper faber (o padrão do Maestro)", "faber_pt_*.wav", False),
    ("OpenVoice V2 (Piper faber + timbre do alvo)", "openvoice_pt_*.wav", True),
    ("Chatterbox (voz padrão)", "chatterbox_padrao_pt_*.wav", False),
    ("Chatterbox (imitando o alvo)", "chatterbox_clone_pt_*.wav", True),
    ("XTTS-v2 (a própria voz-alvo, pronta)", "cena_damien_pt_*.wav", True),
    ("XTTS-v2 (outras vozes prontas)", "cena_[!d]*_pt_*.wav", False),
]
resultado = {"conjuntos": [], "catalogo": []}


def medir(arquivo, texto):
    onda, taxa = librosa.load(str(arquivo), sr=16000, mono=True)
    nota = float(mos(torch.from_numpy(onda).unsqueeze(0), taxa).item())
    segmentos, _ = ouvido.transcribe(str(arquivo), language="pt", beam_size=5)
    entendido_txt = " ".join(s.text.strip() for s in segmentos)
    entendido = difflib.SequenceMatcher(None, simples(texto), simples(entendido_txt)).ratio()
    return {"arquivo": arquivo.name, "texto": texto, "whisper": entendido_txt, "entendido": round(entendido, 3),
            "naturalidade": round(nota, 2), "segundos": round(len(onda) / taxa, 2)}


for nome, padrao, com_alvo in CONJUNTOS:
    arquivos = sorted(PASTA.rglob(padrao))
    if not arquivos:
        print(f"::warning::{nome}: nenhum áudio (o passo desse motor falhou?)")
        continue
    falas = []
    for arq in arquivos:
        i = int(arq.stem.rsplit("_", 1)[1])
        item = medir(arq, CENA_PT[i])
        if com_alvo and voz_alvo is not None:
            item["parecida"] = round(float(np.dot(voz(arq), voz_alvo)), 3)
        falas.append(item)
    media = {k: round(float(np.mean([f[k] for f in falas])), 3) for k in ("entendido", "naturalidade", "parecida")
             if k in falas[0]}
    resultado["conjuntos"].append({"nome": nome, "media": media, "falas": falas})
    print(f"::notice title={nome}::" + "  ·  ".join(f"{k} {v}" for k, v in media.items()), flush=True)

for arq in sorted(PASTA.rglob("catalogo_*.wav")):
    resultado["catalogo"].append(medir(arq, FRASE_CATALOGO))
tempos = PASTA.rglob("tempos_xtts_tudo.json")
nomes = next((json.loads(t.read_text(encoding="utf-8"))["vozes"] for t in tempos), [])
for item in resultado["catalogo"]:
    n = int(item["arquivo"].split("_")[1].split(".")[0])
    item["voz"] = nomes[n] if n < len(nomes) else f"voz {n}"
if resultado["catalogo"]:
    boas = sorted((c for c in resultado["catalogo"] if c["entendido"] >= 0.85), key=lambda c: -c["naturalidade"])
    print("::notice title=Catálogo XTTS (as 10 mais naturais)::" +
          "%0A".join(f"{c['voz']}: {c['naturalidade']}" for c in boas[:10]))

(PASTA / "comparativo.json").write_text(json.dumps(resultado, ensure_ascii=False, indent=1), encoding="utf-8")
linhas = ["| Motor | Entendido (Whisper) | Naturalidade (UTMOS 1-5) | Parecida com o alvo |", "|---|---|---|---|"]
for c in resultado["conjuntos"]:
    m = c["media"]
    linhas.append(f"| {c['nome']} | {m['entendido']} | {m['naturalidade']} | {m.get('parecida', '—')} |")
(PASTA / "comparativo.md").write_text("\n".join(linhas) + "\n", encoding="utf-8")
print("\n".join(linhas))
