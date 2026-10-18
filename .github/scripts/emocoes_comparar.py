"""O Whisper ouve cada fala (entendeu? leu a pontuação?). Uso: python emocoes_comparar.py <pasta>"""
import json
import sys
from pathlib import Path

from faster_whisper import WhisperModel

sys.path.insert(0, str(Path(__file__).parent))
from emocoes_comum import EMOCOES      # noqa: E402

PASTA = Path(sys.argv[1])
ouvido = WhisperModel("small", device="cpu", compute_type="int8")
resultado = []
for chave, emocao, texto, genero, _, _ in EMOCOES:
    for motor in ("xtts", "chatterbox"):
        arquivo = next(PASTA.rglob(f"{motor}_{chave}.wav"), None)
        if arquivo is None:
            continue
        segmentos, info = ouvido.transcribe(str(arquivo), language="pt", beam_size=5)
        texto_ouvido = " ".join(s.text.strip() for s in segmentos)
        resultado.append({"motor": motor, "emocao": emocao, "texto": texto, "ouvido": texto_ouvido,
                          "segundos": round(info.duration, 1), "leu_ponto": "ponto" in texto_ouvido.lower()})
        print(f"::notice title={motor} · {emocao}::{texto_ouvido}", flush=True)
(PASTA / "emocoes.json").write_text(json.dumps(resultado, ensure_ascii=False, indent=1), encoding="utf-8")
