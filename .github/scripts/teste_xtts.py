"""Teste de áudio do XTTS-v2 (roda no GitHub Actions, no processador): as vozes prontas falando português.

Gera, na pasta pedida:
  catalogo_NN.wav      uma frase curta com cada voz pronta do modelo (para escolher as vozes genéricas)
  cena_<voz>_en_N.wav  as falas do guarda em inglês (o "original" do jogo)
  cena_<voz>_pt_N.wav  as mesmas falas já adaptadas para o português
  relatorio.json       tempo de cada fala e o que o Whisper entendeu de volta (para achar fala "alucinada")

Licença do modelo: CPML da Coqui, só para uso NÃO comercial (este teste é pessoal).
Uso: python teste_xtts.py <pasta_saida>
"""

import difflib
import json
import os
import re
import sys
import time
import unicodedata
import wave
from pathlib import Path

os.environ["COQUI_TOS_AGREED"] = "1"      # aceita a licença CPML (uso não comercial)

from faster_whisper import WhisperModel   # noqa: E402
from TTS.api import TTS                    # noqa: E402

SAIDA = Path(sys.argv[1])
SAIDA.mkdir(parents=True, exist_ok=True)

FRASE_CATALOGO = "Olá! Esta é uma das vozes prontas, falando em português do Brasil."
CENA = [  # (original em inglês, adaptada para caber)
    ("Hey! You there! The gate is closed after sunset.", "Ei, você! O portão fecha ao anoitecer."),
    ("If you want to cross the forest, talk to the elder first.", "Quer cruzar a floresta? Fale antes com o ancião."),
    ("And be careful. Something has been moving between the trees.", "E cuidado. Tem algo se mexendo nas árvores."),
]
GUARDAS = ["Damien Black", "Craig Gordon", "Gilberto Mathias", "Luis Moray"]   # usadas se existirem no modelo


def duracao(caminho: Path) -> float:
    with wave.open(str(caminho)) as w:
        return w.getnframes() / w.getframerate()


def simples(texto: str) -> str:
    texto = unicodedata.normalize("NFD", texto.lower())
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", texto).split())


def parecido(a: str, b: str) -> float:
    return round(difflib.SequenceMatcher(None, simples(a), simples(b)).ratio(), 3)


inicio = time.time()
tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to("cpu")
print(f"modelo carregado em {time.time() - inicio:.0f} s", flush=True)
vozes = list(tts.speakers or [])
print(f"{len(vozes)} vozes prontas: {vozes}", flush=True)
ouvido = WhisperModel("small", device="cpu", compute_type="int8")


def falar(texto: str, voz: str, idioma: str, nome: str) -> dict:
    caminho = SAIDA / f"{nome}.wav"
    t0 = time.time()
    tts.tts_to_file(texto, speaker=voz, language=idioma, file_path=str(caminho))
    gasto = time.time() - t0
    segmentos, _ = ouvido.transcribe(str(caminho), language=idioma, beam_size=5)
    entendido = " ".join(s.text.strip() for s in segmentos)
    item = {"arquivo": caminho.name, "voz": voz, "idioma": idioma, "texto": texto, "entendido": entendido,
            "parecido": parecido(texto, entendido), "segundos_audio": round(duracao(caminho), 2),
            "segundos_para_gerar": round(gasto, 2)}
    print(json.dumps(item, ensure_ascii=False), flush=True)
    return item


relatorio = {"vozes": vozes, "falas": []}
guardas = [v for v in GUARDAS if v in vozes] or vozes[-4:]
for voz in guardas:
    rotulo = voz.split()[0].lower()
    for i, (en, pt) in enumerate(CENA):
        relatorio["falas"].append(falar(en, voz, "en", f"cena_{rotulo}_en_{i}"))
        relatorio["falas"].append(falar(pt, voz, "pt", f"cena_{rotulo}_pt_{i}"))
for i, voz in enumerate(vozes):
    item = falar(FRASE_CATALOGO, voz, "pt", f"catalogo_{i:02d}")
    relatorio["falas"].append(item)
relatorio["total_segundos"] = round(time.time() - inicio)
(SAIDA / "relatorio.json").write_text(json.dumps(relatorio, ensure_ascii=False, indent=1), encoding="utf-8")
ruins = [f for f in relatorio["falas"] if f["parecido"] < 0.8]
print(f"pronto em {relatorio['total_segundos']} s; {len(ruins)} fala(s) com o Whisper entendendo diferente:")
for f in ruins:
    print(f"  {f['arquivo']}: '{f['texto']}' -> '{f['entendido']}' ({f['parecido']})")
