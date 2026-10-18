"""Demonstração da interpretação das emoções (v2.22.0) com o código do Maestro: as mesmas falas, com as vozes prontas
(genéricas) do XTTS-v2, nenhum filme, em 3 versões:

- antes: como na v2.20 (força "Desligada": o Chatterbox com a intensidade da tabela e nada depois da voz);
- agora: a v2.22 na força "Forte" (o Chatterbox mais intenso, o jeito de falar da emoção e a interpretação);
- xtts: sem o Chatterbox, só o XTTS-v2 e a interpretação (para quem não instalou o Chatterbox).

Cada fala sai também nivelada como na trilha do filme (antes: todas no mesmo volume; agora: pela emoção).

Uso: python demo_interpretacao.py <pasta_do_motor> <saida>
"""
import json
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from jellyfin_tools import dublagem                                  # noqa: E402
from jellyfin_tools import emocoes as em                             # noqa: E402
from jellyfin_tools import voz_emocao as ve                          # noqa: E402
from jellyfin_tools import voz_local as vl                           # noqa: E402
from jellyfin_tools.transcricao import Transcritor                   # noqa: E402

# (emoção, quem fala, o texto): a 1ª é a fala normal, a referência de volume
FALAS = [
    ("normal", "m", "Tá bom. Vamos conversar com calma, sentados."),
    ("choro", "f", "Por favor, não me deixa sozinha. Eu não aguento mais."),
    ("brava", "m", "Eu te falei cem vezes! Para de mentir pra mim!"),
    ("grito", "m", "Corre! Sai da casa, agora!"),
    ("medo", "f", "Tem alguém aqui dentro. Eu tô ouvindo os passos."),
    ("triste", "m", "Ela foi embora. E eu nem consegui dizer adeus."),
    ("sussurro", "m", "Fica quieta. Eles podem ouvir a gente."),
]
NOTAS = {"normal": "", "choro": "Nesta fala: chorando.", "brava": "Nesta fala: com raiva, furioso.",
         "grito": "Nesta fala: gritando, com força.", "medo": "Nesta fala: com medo, apavorada.",
         "triste": "Nesta fala: triste, abatido.", "sussurro": "Nesta fala: sussurrando."}
VOZ = {"m": "Damien Black", "f": "Ana Florence"}
VERSOES = {"antes": (0.0, True), "agora": (1.0, True), "xtts": (1.0, False)}    # (força, com o Chatterbox)

pasta, saida = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
saida.mkdir(parents=True, exist_ok=True)
inicio = time.time()
progresso = lambda f, texto: print(f"{f:4.0%} {texto}", flush=True)    # noqa: E731
vl.instalar(pasta, gpu=False, ao_progresso=progresso)
ve.instalar(pasta, gpu=False, ao_progresso=progresso)
print(f"::notice title=Instalados::XTTS-v2 e Chatterbox em {time.time() - inicio:.0f} s", flush=True)

conferir = vl.ConferidorWhisper(Transcritor(modelo="base", usar_gpu=False, pasta_modelos=str(saida / "whisper")))
registro, tempos, como_ficou = {}, {}, {}
for versao, (forca, com_chatterbox) in VERSOES.items():
    t0, avisos = time.time(), []
    emocao = ve.MotorEmocao(pasta, avisar=avisos.append) if com_chatterbox else None
    motor = vl.MotorLocal(pasta, VOZ["m"], conferir=conferir, emocao=emocao, avisar=avisos.append,
                          forca_emocao=forca)
    motor.sintetizar([(texto, saida / f"{versao}_{k}.wav", VOZ[quem], NOTAS[e]) for k, (e, quem, texto) in
                      enumerate(FALAS)])
    motor.fechar()
    tempos[versao], registro[versao], como_ficou[versao] = round(time.time() - t0, 1), avisos, dict(motor.como_ficou)
    for k, (e, _, _) in enumerate(FALAS):                # como na trilha do filme
        wav = saida / f"{versao}_{k}.wav"
        with wave.open(str(wav)) as w:
            parametros, amostras = w.getparams(), w.readframes(w.getnframes())
        db = dublagem.VOLUME_DA_EMOCAO.get(e, 0.0) if forca > 0 else 0.0
        nivelada, _ = dublagem.nivelar(amostras, 2, db)
        with wave.open(str(saida / f"{versao}_{k}_trilha.wav"), "wb") as w:
            w.setparams(parametros)
            w.writeframes(nivelada)
    print(f"::notice title={versao}::{tempos[versao]} s | " + " | ".join(a for a in avisos if "emoção" in a),
          flush=True)

linhas = []
for k, (e, quem, texto) in enumerate(FALAS):
    ouvido = {}
    for versao in VERSOES:
        segmentos, _ = conferir.transcritor.motor.transcribe(str(saida / f"{versao}_{k}.wav"), language="pt",
                                                             beam_size=5)
        ouvido[versao] = " ".join(s.text.strip() for s in segmentos)
    linhas.append({"emocao": e, "quem": quem, "texto": texto, "voz": VOZ[quem], "ouvido": ouvido,
                   "chatterbox": {"antes": em.intensidade_chatterbox(e, 0.0) if e in em.CHATTERBOX else None,
                                  "agora": em.intensidade_chatterbox(e, 1.0) if e in em.CHATTERBOX else None},
                   "interpretacao": {v: como_ficou[v].get(e, "") for v in VERSOES},
                   "volume_db": dublagem.VOLUME_DA_EMOCAO.get(e, 0.0)})
    print(f"::notice title={k} {e}::" + " | ".join(f"{v}: {ouvido[v]}" for v in VERSOES), flush=True)
(saida / "demo.json").write_text(json.dumps({"linhas": linhas, "segundos": tempos, "registro": registro},
                                            ensure_ascii=False, indent=1), encoding="utf-8")
print(f"::notice title=Pronto::{tempos}; total {time.time() - inicio:.0f} s", flush=True)
