"""O 2º motor de vozes no PC, para as falas com emoção (o Chatterbox): o instalador (com um uv de mentira) e o
servidor de verdade conversando com bibliotecas de mentira (sem baixar nada e sem o PyTorch)."""
import json
import os
import sys
import wave
from types import SimpleNamespace

import pytest

from jellyfin_tools import voz_emocao as ve
from jellyfin_tools import voz_local as vl
from jellyfin_tools.dublagem import ErroDublagem
from jellyfin_tools.emocoes import CHATTERBOX
from tests.test_voz_local import TORCH_FALSO, uv_falso

CHATTERBOX_FALSO = """
import json, os
class _Som:
    def __init__(self, n):
        self.n = n
    def squeeze(self, eixo):
        return self
    def detach(self):
        return self
    def cpu(self):
        return self
    def numpy(self):
        import numpy as np
        return np.full((self.n,), 0.25, dtype=np.float32)
class ChatterboxMultilingualTTS:
    sr = 24000
    @classmethod
    def from_pretrained(cls, device):
        if device == "cuda" and os.environ.get("FALHA") == "carregar":
            raise RuntimeError("CUDA out of memory")
        modelo = cls()
        modelo.device = device
        return modelo
    def generate(self, texto, language_id, audio_prompt_path, exaggeration, cfg_weight):
        if self.device == "cuda" and os.environ.get("FALHA") == "falar":
            raise RuntimeError("CUDA error: out of memory")
        with open(os.environ["ANOTAR"], "a", encoding="utf-8") as f:
            f.write(json.dumps([texto, language_id, audio_prompt_path, exaggeration, cfg_weight, self.device]) + "\\n")
        return _Som(2400)
"""
SOUNDFILE_FALSO = """
import struct, wave
def write(caminho, dados, taxa):
    with wave.open(caminho, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(taxa)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * x)) for x in dados))
"""


def xtts_instalado(pasta):
    python = vl.python_do_motor(pasta, "linux")
    python.parent.mkdir(parents=True)
    python.write_text("")
    (pasta / "instalado.json").write_text(json.dumps({"gpu": False}), encoding="utf-8")


def test_instalar_o_chatterbox_no_ambiente_dele(tmp_path):
    pasta = tmp_path / "motor_vozes"
    comandos, etapas = [], []

    def executar(argumentos, **k):
        comandos.append(argumentos)
        assert k["env"]["UV_CACHE_DIR"] == str(pasta / "cache")              # o mesmo uv e o mesmo cache do XTTS
        if argumentos[1] == "venv":
            python = vl.python_do_motor(pasta / "chatterbox", "linux")
            python.parent.mkdir(parents=True)
            python.write_text("")
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    with pytest.raises(ErroDublagem, match="instale primeiro o motor de vozes XTTS-v2"):
        ve.instalar(pasta, gpu=False, sistema="linux", executar=executar, medir_espaco=lambda p: 100.0)
    xtts_instalado(pasta)
    with pytest.raises(ErroDublagem, match="o Chatterbox precisa de uns 10 GB"):
        ve.instalar(pasta, gpu=True, sistema="linux", executar=executar, medir_espaco=lambda p: 7.0)
    baixados = []
    info = ve.instalar(pasta, gpu=True, sistema="linux", executar=executar, medir_espaco=lambda p: 100.0,
                       baixar=lambda url, destino, p: (baixados.append(url), destino.write_bytes(uv_falso())),
                       ao_progresso=lambda f, t: etapas.append(f))
    assert [c[1:3] for c in comandos] == [["venv", str(pasta / "chatterbox" / "ambiente")], ["pip", "install"],
                                          ["pip", "install"]]
    assert comandos[0][-1] == "3.11" and "torch==2.6.0" in comandos[1] and ve.INDICE_GPU in comandos[1]
    assert "chatterbox-tts==0.1.7" in comandos[2] and "setuptools<81" in comandos[2]    # o Perth usa o pkg_resources
    assert len(baixados) == 1 and etapas[-1] == 1.0
    assert info["gpu"] and ve.instalado(pasta)["gpu"] and "exaggeration" in ve.arquivo_servidor(pasta).read_text(
        encoding="utf-8")
    ve.desinstalar(pasta)
    assert ve.instalado(pasta) is None and vl.instalado(pasta)                # o XTTS-v2 continua


def chatterbox_de_verdade(tmp_path, monkeypatch, placa="", falha=""):
    """O Chatterbox "instalado" (o python é o deste teste) e as bibliotecas de mentira na frente."""
    pasta = tmp_path / "motor_vozes"
    libs = tmp_path / "libs"
    (libs / "chatterbox").mkdir(parents=True)
    (libs / "chatterbox" / "__init__.py").write_text("", encoding="utf-8")
    (libs / "chatterbox" / "mtl_tts.py").write_text(CHATTERBOX_FALSO, encoding="utf-8")
    (libs / "torch.py").write_text(TORCH_FALSO, encoding="utf-8")
    (libs / "soundfile.py").write_text(SOUNDFILE_FALSO, encoding="utf-8")
    pacotes = [p for p in sys.path if p.endswith("site-packages")]
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join([str(libs)] + pacotes))
    monkeypatch.setenv("PLACA", placa)
    monkeypatch.setenv("FALHA", falha)
    monkeypatch.setenv("ANOTAR", str(tmp_path / "anotado.jsonl"))
    xtts_instalado(pasta)
    python = vl.python_do_motor(pasta / "chatterbox")
    python.parent.mkdir(parents=True)
    os.symlink(sys.executable, python)
    (pasta / "chatterbox" / "instalado.json").write_text(json.dumps({"gpu": bool(placa)}), encoding="utf-8")
    return pasta


@pytest.mark.skipif(os.name == "nt", reason="o python falso usa um atalho (symlink)")
def test_chatterbox_fala_com_a_intensidade_da_emocao(tmp_path, monkeypatch):
    pasta = chatterbox_de_verdade(tmp_path, monkeypatch)
    avisos = []
    motor = ve.MotorEmocao(pasta, avisar=avisos.append)
    motor.falar("Sai daqui! Agora.", tmp_path / "a.wav", tmp_path / "ref.wav", "grito")
    motor.falar("Fala baixo.", tmp_path / "b.wav", tmp_path / "ref.wav", "sussurro")
    anotado = [json.loads(x) for x in (tmp_path / "anotado.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [a[0] for a in anotado] == ["Sai daqui!", "Agora", "Fala baixo"]          # frase a frase, sem o ponto
    assert anotado[0][1:5] == ["pt", str(tmp_path / "ref.wav"), *CHATTERBOX["grito"]]
    assert anotado[2][3:5] == list(CHATTERBOX["sussurro"])
    with wave.open(str(tmp_path / "a.wav")) as w:                               # 2 frases + a pausa do "!"
        assert w.getnframes() == 2 * 2400 + int(24000 * vl.PAUSA_PERGUNTA)
    assert motor.dispositivo == "cpu" and any("processador" in a for a in avisos) and motor.pedidos == 2
    with pytest.raises(ErroDublagem, match="emoção desconhecida"):
        motor.falar("Oi.", tmp_path / "c.wav", tmp_path / "ref.wav", "normal")
    motor.fechar()


@pytest.mark.skipif(os.name == "nt", reason="o python falso usa um atalho (symlink)")
@pytest.mark.parametrize("falha", ["carregar", "falar"])
def test_chatterbox_tambem_tem_o_plano_b_da_placa(tmp_path, monkeypatch, falha):
    pasta = chatterbox_de_verdade(tmp_path, monkeypatch, placa="GTX 1050", falha=falha)
    avisos = []
    motor = ve.MotorEmocao(pasta, avisar=avisos.append)
    motor.falar("Corre!", tmp_path / "a.wav", tmp_path / "ref.wav", "grito")
    assert (tmp_path / "a.wav").is_file() and motor.dispositivo == "cpu"
    assert json.loads((tmp_path / "anotado.jsonl").read_text(encoding="utf-8").splitlines()[-1])[-1] == "cpu"
    assert any(("não aguentou o modelo" if falha == "carregar" else "segue pelo processador") in a for a in avisos)
    motor.fechar()


def test_chatterbox_sem_instalar_explica(tmp_path):
    with pytest.raises(ErroDublagem, match="Instalar o Chatterbox"):
        ve.MotorEmocao(tmp_path / "nada").falar("Oi!", tmp_path / "a.wav", tmp_path / "r.wav", "grito")
