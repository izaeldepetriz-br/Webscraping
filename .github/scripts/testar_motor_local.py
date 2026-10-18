"""Teste de verdade do motor de vozes XTTS-v2 (o mesmo código do Maestro), num Windows sem placa de vídeo:
instala (uv -> Python 3.12 -> PyTorch -> coqui-tts), fala com uma voz pronta e com uma "importada" (uma gravação
gerada pela própria voz pronta: nenhuma pessoa real) e confere cada fala com o Whisper. Depois, as falas com
EMOÇÃO: pela gravação de emoção da voz importada e pelo Chatterbox (instalado no ambiente dele).

Uso: python testar_motor_local.py <pasta_do_motor> <pasta_de_saida>
"""
import shutil
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from jellyfin_tools import voz_emocao as ve                    # noqa: E402
from jellyfin_tools import voz_local as vl                     # noqa: E402
from jellyfin_tools import vozes_importadas as vi              # noqa: E402
from jellyfin_tools.transcricao import Transcritor             # noqa: E402

pasta, saida = Path(sys.argv[1]), Path(sys.argv[2])
saida.mkdir(parents=True, exist_ok=True)


def duracao(wav: Path) -> float:
    with wave.open(str(wav)) as w:
        return w.getnframes() / w.getframerate()


print(f"::notice title=Espaço no disco::{vl.espaco_livre(pasta):.0f} GB livres", flush=True)
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
ouvidos = []
for f in falas:
    segundos = duracao(f[1])
    assert segundos > 1.0, f"{f[1].name}: só {segundos:.2f} s"
    segmentos, _ = conferir.transcritor.motor.transcribe(str(f[1]), language="pt", beam_size=5)
    ouvido = " ".join(s.text.strip() for s in segmentos)
    ouvidos.append(f"{f[1].stem}: {ouvido}")
    print(f"{f[1].name}: {segundos:.1f} s -> {ouvido}", flush=True)
print("::notice title=O Whisper ouviu::" + "%0A".join(ouvidos), flush=True)
lidos = [o for o in ouvidos if "ponto" in o.lower()]
assert not lidos, f"o XTTS-v2 leu a pontuação: {lidos}"
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


def ouvir(wav: Path) -> str:
    segmentos, _ = conferir.transcritor.motor.transcribe(str(wav), language="pt", beam_size=5)
    return " ".join(s.text.strip() for s in segmentos)


# EMOÇÃO 1: a gravação "brava" da voz importada (aqui, a mesma gravação: o teste é do caminho, não da atuação)
shutil.copyfile(destino / "referencia.wav", destino / "brava.wav")
importada.emocoes = ["brava"]
avisos = []
motor = vl.MotorLocal(pasta, "imp:teste", [importada], saida, conferir=conferir, avisar=avisos.append)
motor.sintetizar([("Eu já disse para você sair daqui!", saida / "emocao_gravacao.wav", "",
                   "Nesta fala: gritando, com força.")])         # grito -> a gravação "brava" (a parecida)
motor.fechar()
assert any("1 fala(s) com a gravação de emoção" in a for a in avisos), avisos
print(f"::notice title=Emoção pela gravação::{ouvir(saida / 'emocao_gravacao.wav')}", flush=True)

# EMOÇÃO 2: o Chatterbox, instalado no ambiente dele, imitando uma voz pronta e a importada
t0 = time.time()
info = ve.instalar(pasta, gpu=False, ao_progresso=lambda f, texto: print(f"{f:4.0%} {texto}", flush=True))
print(f"::notice title=Chatterbox instalado::{info} em {time.time() - t0:.0f} s", flush=True)
avisos = []
motor = vl.MotorLocal(pasta, "Damien Black", [importada], saida, conferir=conferir,
                      emocao=ve.MotorEmocao(pasta, avisar=avisos.append), avisar=avisos.append)
falas = [("Corre! Ele está vindo! Sai da frente!", saida / "chatterbox_grito.wav", "", "Nesta fala: gritando."),
         ("Por favor, não me deixa sozinha.", saida / "chatterbox_choro.wav", "imp:teste", "Nesta fala: chorando."),
         ("Fala baixo. Eles podem ouvir a gente.", saida / "chatterbox_sussurro.wav", "imp:teste",
          "Nesta fala: sussurrando, em voz baixa.")]
t0 = time.time()
motor.sintetizar(falas)
gasto = time.time() - t0
motor.fechar()
print("\n".join(avisos), flush=True)
assert not any("o Chatterbox falhou" in a for a in avisos), avisos
assert any("3 pelo Chatterbox" in a for a in avisos), avisos
ouvidos = [f"{f[1].stem} ({duracao(f[1]):.1f} s): {ouvir(f[1])}" for f in falas]
print("::notice title=Chatterbox · o Whisper ouviu::" + "%0A".join(ouvidos), flush=True)
assert all(duracao(f[1]) > 1.0 for f in falas) and not [o for o in ouvidos if "ponto" in o.lower()], ouvidos
print(f"::notice title=Chatterbox::3 falas com emoção em {gasto:.0f} s (com o 1º carregamento do modelo); "
      f"total {time.time() - inicio:.0f} s", flush=True)
