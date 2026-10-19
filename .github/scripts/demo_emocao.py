"""Demonstração da DISCUSSÃO (v2.22.0) pelo caminho de verdade da dublagem do Maestro (dublar_video): uma cena de
briga entre três pessoas (vozes prontas, genéricas, do XTTS-v2; nenhum filme), com falas que se cruzam e um bloco
com travessões. Duas versões: AGORA (as falas juntas misturadas e o bloco em duas vozes) e ANTES (como na v2.21:
cada uma espera a vez, a anterior é cortada, e o bloco sai numa voz só). Sem a interpretação (desligada).

Uso: python demo_discussao.py <pasta_do_motor> <saida>
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from jellyfin_tools import dublagem                                  # noqa: E402
from jellyfin_tools import voz_local as vl                           # noqa: E402
from jellyfin_tools.transcricao import Transcritor                   # noqa: E402

# (início, fim, quem, texto): as falas 3 e 4 entram antes de a anterior acabar; a 5 é um bloco com travessões
CENA = [
    (0.5, 2.5, "Ana", "Você pegou o meu carro de novo?"),
    (2.8, 4.8, "Bruno", "Peguei, e daí? Eu precisava dele!"),
    (4.0, 6.0, "Ana", "Você nem pediu! Você nunca pede nada!"),
    (4.6, 6.6, "Carlos", "Ei, ei, calma, vocês dois!"),
    (7.2, 9.4, "Bruno", "- Fica fora disso, Carlos!\n- Não fico, não!"),
    (9.8, 11.8, "Ana", "Chega. Me dá a chave agora."),
    (10.9, 12.6, "Bruno", "Toma, toma a chave!"),
]
VOZ = {"Ana": "Ana Florence", "Bruno": "Damien Black", "Carlos": "Gilberto Mathias"}
DURACAO = 14.0


def hms(x: float) -> str:
    h, m = divmod(x, 3600)
    m, s = divmod(m, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:06.3f}".replace(".", ",")


class MotorFalso:
    """(DEMO_FALSO=1: para conferir o roteiro sem o XTTS-v2) um tom por voz, do tamanho do texto."""
    voz, modelo, estilo = "falsa", "falso", ""

    def sintetizar(self, pedidos, parar=None, ao_progresso=None):
        import math
        import wave
        for p in pedidos:
            freq = 200 + 40 * (hash(p[2] if len(p) > 2 else "") % 7)
            with wave.open(str(p[1]), "wb") as w:
                w.setnchannels(1), w.setsampwidth(2), w.setframerate(24000)
                w.writeframes(b"".join(int(6000 * math.sin(2 * math.pi * freq * n / 24000)).to_bytes(2, "little",
                                                                                                    signed=True)
                                       for n in range(int(0.06 * len(p[0]) * 24000))))

    def fechar(self):
        pass


FALSO = bool(os.environ.get("DEMO_FALSO"))
pasta, saida = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
saida.mkdir(parents=True, exist_ok=True)
inicio = time.time()
if not FALSO:
    vl.instalar(pasta, gpu=False, ao_progresso=lambda f, texto: print(f"{f:4.0%} {texto}", flush=True))
ffmpeg = dublagem.localizar_ffmpeg()
print(f"::notice title=Instalado::XTTS-v2 em {time.time() - inicio:.0f} s; ffmpeg {ffmpeg}", flush=True)
srt = "\n".join(f"{k + 1}\n{hms(a)} --> {hms(b)}\n{texto}\n" for k, (a, b, _, texto) in enumerate(CENA))
conferir = None if FALSO else vl.ConferidorWhisper(Transcritor(modelo="base", usar_gpu=False,
                                                                pasta_modelos=str(saida / "whisper")))
vozes = {k: VOZ[quem] for k, (_, _, quem, _) in enumerate(CENA)}
resultados = {}
for versao in ("agora", "antes"):
    pasta_video = saida / versao
    pasta_video.mkdir(exist_ok=True)
    video = pasta_video / "Cena.mkv"
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    f"color=c=0x10121a:s=320x180:d={DURACAO}:r=10", "-f", "lavfi", "-i",
                    f"anullsrc=r=48000:cl=stereo:d={DURACAO}", "-shortest", "-c:v", "libx264", "-c:a", "aac",
                    "-metadata:s:a:0", "language=eng", str(video)], check=True)
    (pasta_video / "Cena.pt-BR.srt").write_text(srt, encoding="utf-8")
    juntas, partes = dublagem.falas_juntas, dublagem.partes_do_dialogo
    if versao == "antes":                       # como na v2.21: cada uma espera a vez; o bloco numa voz só
        dublagem.falas_juntas = lambda *a, **k: set()
        dublagem.partes_do_dialogo = lambda texto: []
    avisos = []
    motor = MotorFalso() if FALSO else vl.MotorLocal(pasta, VOZ["Bruno"], conferir=conferir, avisar=avisos.append)
    t0 = time.time()
    r = dublagem.dublar_video(video, pasta_video / "Cena.pt-BR.srt", motor, ffmpeg, vozes=vozes,
                              sondar=lambda v: (DURACAO, ["eng"]), avisar=avisos.append,
                              destino=pasta_video / "Cena - Dublado.mkv")
    motor.fechar()
    dublagem.falas_juntas, dublagem.partes_do_dialogo = juntas, partes
    if r.status != "dublado":
        raise SystemExit(f"{versao}: {r.status} {r.detalhe}")
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(r.destino), "-map", "0:a:0",
                    "-ac", "1", "-ar", "24000", str(saida / f"{versao}.wav")], check=True)
    resultados[versao] = {"segundos": round(time.time() - t0, 1), "avisos": avisos, "cortadas": r.cortadas,
                          "aceleradas": r.aceleradas}
    print(f"::notice title={versao}::{resultados[versao]['segundos']} s | " + " | ".join(avisos[-6:]), flush=True)
(saida / "demo.json").write_text(json.dumps({"cena": CENA, "vozes": VOZ, "duracao": DURACAO,
                                             "resultados": resultados}, ensure_ascii=False, indent=1),
                                 encoding="utf-8")
print(f"::notice title=Pronto::total {time.time() - inicio:.0f} s", flush=True)
