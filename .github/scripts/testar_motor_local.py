"""Teste de verdade do motor de vozes XTTS-v2 (o mesmo código do Maestro), num Windows sem placa de vídeo:
instala (uv -> Python 3.12 -> PyTorch -> coqui-tts), fala com uma voz pronta e com uma "importada" (uma gravação
gerada pela própria voz pronta: nenhuma pessoa real) e confere cada fala com o Whisper.

Uso: python testar_motor_local.py <pasta_do_motor> <pasta_de_saida>
"""
import shutil
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from jellyfin_tools import voz_local as vl                     # noqa: E402
from jellyfin_tools import vozes_importadas as vi              # noqa: E402
from jellyfin_tools.transcricao import Transcritor             # noqa: E402

pasta, saida = Path(sys.argv[1]), Path(sys.argv[2])
saida.mkdir(parents=True, exist_ok=True)


def duracao(wav: Path) -> float:
    with wave.open(str(wav)) as w:
        return w.getnframes() / w.getframerate()


inicio = time.time()
info = vl.instalar(pasta, gpu=False, ao_progresso=lambda f, texto: print(f"{f:4.0%} {texto}", flush=True))
print(f"::notice title=Instalado::{info} em {time.time() - inicio:.0f} s", flush=True)

conferir = vl.ConferidorWhisper(Transcritor(modelo="base", usar_gpu=False, pasta_modelos=str(saida / "whisper")))
motor = vl.MotorLocal(pasta, "Ana Florence", conferir=conferir, avisar=lambda t: print("motor:", t, flush=True))
falas = [("Olá! Este é o teste do motor de vozes, no Windows, sem placa de vídeo.", saida / "pronta_1.wav"),
         ("Ei, você! O portão fecha ao anoitecer.", saida / "pronta_2.wav"),
         ("E cuidado. Tem algo se mexendo nas árvores.", saida / "pronta_3.wav", "Damien Black"),
         (vl.FRASE_DE_TESTE + " Vou fazer um café e ver um filme. Você quer vir junto?", saida / "referencia.wav")]
t0 = time.time()
motor.sintetizar(falas)
gasto = time.time() - t0
for f in falas:
    segundos = duracao(f[1])
    assert segundos > 1.0, f"{f[1].name}: só {segundos:.2f} s"
    print(f"{f[1].name}: {segundos:.1f} s", flush=True)
print(f"::notice title=Vozes prontas::{len(falas)} falas em {gasto:.0f} s (processador; dispositivo={motor.dispositivo}); "
      f"cortadas={motor.cortadas} refeitas={motor.refeitas}", flush=True)
motor.fechar()

# uma voz "importada": a gravação de referência gerada acima (6 s ou mais), como se viesse do Importar voz
importada = vi.VozImportada("Teste", "teste", vi.GRAVACAO, genero="feminina")
destino = vi.pasta_da_gravacao(saida, "teste")
destino.mkdir(parents=True, exist_ok=True)
shutil.copyfile(saida / "referencia.wav", destino / "referencia.wav")
motor = vl.MotorLocal(pasta, "imp:teste", [importada], saida, conferir=conferir)
motor.sintetizar([("Esta fala usa o timbre da voz importada.", saida / "importada.wav")])
assert duracao(saida / "importada.wav") > 1.0
motor.fechar()
print(f"::notice title=Voz importada::ok ({duracao(saida / 'importada.wav'):.1f} s); total {time.time() - inicio:.0f} s")
