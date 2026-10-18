"""Demonstração da emoção no XTTS-v2 com o código do Maestro: uma cena de exemplo (vozes geradas, nenhum filme),
dublada ANTES (só o XTTS-v2, neutro) e DEPOIS (a emoção medida pelo volume do original e as falas com emoção pelo
Chatterbox, imitando a mesma voz).

Uso: python demo_emocao.py <pasta_do_motor> <saida>
"""
import json
import sys
import time
import wave
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from scipy.signal import resample_poly

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).parent))

from efeitos import no_volume, sussurrar                        # noqa: E402
from jellyfin_tools import genero_local as gl                   # noqa: E402
from jellyfin_tools import voz_emocao as ve                     # noqa: E402
from jellyfin_tools import voz_local as vl                      # noqa: E402
from jellyfin_tools.emocoes import NORMAL, emocao_da_nota       # noqa: E402
from jellyfin_tools.transcricao import Transcritor              # noqa: E402

# quem fala (m/f), o original em inglês, a dublagem e como a fala é dita no original
CENA = [
    ("m", "Did you hear that? Something is moving outside.", "Você ouviu isso? Tem alguma coisa se mexendo lá fora.",
     "normal"),
    ("f", "It's just the wind. Go back to sleep.", "É só o vento. Volta a dormir.", "normal"),
    ("m", "No, listen. Someone is at the door.", "Não, escuta. Tem alguém na porta.", "normal"),
    ("m", "Stay quiet. They can hear us.", "Fica quieta. Eles podem ouvir a gente.", "sussurro"),
    ("f", "Okay. What do we do now?", "Tá bom. E agora, o que a gente faz?", "normal"),
    ("m", "I'm going to check the window.", "Vou olhar pela janela.", "normal"),
    ("f", "Be careful, please.", "Toma cuidado, por favor.", "normal"),
    ("m", "Run! Get out of the house, now!", "Corre! Sai da casa, agora!", "grito"),
    ("f", "Where are you going? Wait for me!", "Pra onde você vai? Me espera!", "normal"),
    ("f", "Please, don't leave me alone. I can't do this.", "Por favor, não me deixa sozinha. Eu não aguento.",
     "choro"),
    ("m", "Get down! Now!", "Abaixa! Agora!", "grito"),
    ("m", "It's over. We're safe now.", "Acabou. Agora a gente está seguro.", "normal"),
]
# o "original" em inglês: a voz dela bem aguda (uma de 160 a 185 Hz fica "sem saber" e vai com a voz principal)
VOZ_ORIGINAL = {"m": "Viktor Eka", "f": "Narelle Moon"}
VOZ_DUBLAGEM = {"m": "Gilberto Mathias", "f": "Ana Florence"}     # a dublagem (a principal é a masculina)
NORMAL_RMS, GRITO_RMS, SUSSURRO_RMS = 0.03, 0.12, 0.006     # sem estourar (a distorção engana o tom)

pasta, saida = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
saida.mkdir(parents=True, exist_ok=True)
inicio = time.time()


def ler(wav: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(wav)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float64) / 32768, w.getframerate()


def salvar(wav: Path, som: np.ndarray, taxa: int) -> None:
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(taxa)
        w.writeframes((np.clip(som, -0.99, 0.99) * 32767).astype(np.int16).tobytes())


def hms(x: float) -> str:
    h, m = divmod(x, 3600)
    m, s = divmod(m, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:06.3f}".replace(".", ",")


progresso = lambda f, texto: print(f"{f:4.0%} {texto}", flush=True)    # noqa: E731
vl.instalar(pasta, gpu=False, ao_progresso=progresso)
ve.instalar(pasta, gpu=False, ao_progresso=progresso)
print(f"::notice title=Instalados::XTTS-v2 e Chatterbox em {time.time() - inicio:.0f} s", flush=True)

# 1) o "original" em inglês: o grito bem mais alto e o sussurro sem a vibração da voz
motor = vl.MotorLocal(pasta, VOZ_ORIGINAL["m"], idioma="en")
motor.sintetizar([(ingles, saida / f"original_{i:02d}.wav", VOZ_ORIGINAL[quem])
                  for i, (quem, ingles, _, _) in enumerate(CENA)])
motor.fechar()
partes, falas, t = [], [], 1.0
taxa = 24000
partes.append(np.zeros(taxa))
for i, (quem, ingles, portugues, jeito) in enumerate(CENA):
    som, taxa = ler(saida / f"original_{i:02d}.wav")
    if jeito == "sussurro":
        som = no_volume(sussurrar(som, taxa), SUSSURRO_RMS)
    else:
        som = no_volume(som, GRITO_RMS if jeito == "grito" else NORMAL_RMS)
    salvar(saida / f"original_{i:02d}.wav", som, taxa)
    falas.append((SimpleNamespace(tempo=f"{hms(t)} --> {hms(t + len(som) / taxa)}"), portugues))
    partes += [som, np.zeros(int(0.8 * taxa))]
    t += len(som) / taxa + 0.8
cena = np.concatenate(partes)
salvar(saida / "cena_original.wav", cena, taxa)

# 2) o Maestro mede cada fala do original (o tom diz o gênero; o volume, grito e sussurro)
cena8 = resample_poly(cena, 8000, taxa).astype(np.float32)
ouvidas = gl.ouvir_generos("cena", falas, list(range(len(CENA))), "ffmpeg", saida / "generos.json",
                           ler=lambda ff, v, a, d: cena8[int(a * 8000):int((a + d) * 8000)], emocao=True)
notas, vozes = {}, {}
for k, (quem, _, _, jeito) in enumerate(CENA):
    notas[k] = ouvidas[k].nota()
    if jeito == "choro":                     # o choro o volume não mostra: a nota escrita em "Refazer esta fala"
        notas[k] = "Nesta fala: chorando."
    genero = ouvidas[k].genero
    vozes[k] = VOZ_DUBLAGEM.get(genero, VOZ_DUBLAGEM["m"])
medidas = json.loads((saida / "generos.json").read_text(encoding="utf-8"))

# 3) a dublagem ANTES (só o XTTS-v2) e DEPOIS (com o Chatterbox nas falas com emoção)
conferir = vl.ConferidorWhisper(Transcritor(modelo="base", usar_gpu=False, pasta_modelos=str(saida / "whisper")))
resultado = {}
for versao, emocao in (("antes", None), ("depois", ve.MotorEmocao(pasta, avisar=print))):
    t0 = time.time()
    motor = vl.MotorLocal(pasta, VOZ_DUBLAGEM["m"], conferir=conferir, emocao=emocao, avisar=print)
    motor.sintetizar([(CENA[k][2], saida / f"{versao}_{k:02d}.wav", vozes[k], notas[k]) for k in range(len(CENA))])
    motor.fechar()
    resultado[versao] = round(time.time() - t0, 1)

linhas = []
for k, (quem, ingles, portugues, jeito) in enumerate(CENA):
    ouvidos = {}
    for versao in ("antes", "depois"):
        segmentos, _ = conferir.transcritor.motor.transcribe(str(saida / f"{versao}_{k:02d}.wav"), language="pt",
                                                             beam_size=5)
        ouvidos[versao] = " ".join(s.text.strip() for s in segmentos)
    emocao = emocao_da_nota(notas[k])
    linhas.append({"quem": quem, "ingles": ingles, "portugues": portugues, "jeito": jeito,
                   "medido": medidas.get(str(k), {}), "genero": ouvidas[k].genero, "nota": notas[k],
                   "emocao": emocao, "voz": vozes[k], "motor_depois": "Chatterbox" if emocao != NORMAL else "XTTS-v2",
                   "ouvido_antes": ouvidos["antes"], "ouvido_depois": ouvidos["depois"]})
    print(f"::notice title={k:02d} {jeito} -> {emocao}::{linhas[-1]['medido']} | antes: {ouvidos['antes']} | "
          f"depois: {ouvidos['depois']}", flush=True)
(saida / "demo.json").write_text(json.dumps({"linhas": linhas, "segundos": resultado}, ensure_ascii=False, indent=1),
                                 encoding="utf-8")
print(f"::notice title=Pronto::antes {resultado['antes']} s, depois {resultado['depois']} s; total "
      f"{time.time() - inicio:.0f} s", flush=True)
