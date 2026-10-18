"""Motor de vozes no PC (XTTS-v2): o instalador (com um uv de mentira) e o motor conversando com um servidor de
mentira (um Python que "fala" um tom puro), sem baixar nada e sem o PyTorch."""
import io
import json
import os
import sys
import tarfile
import wave
from types import SimpleNamespace

import pytest

from jellyfin_tools import voz_local as vl
from jellyfin_tools import vozes_importadas as vi
from jellyfin_tools.dublagem import ErroDublagem

SERVIDOR_FALSO = r'''
import json, math, struct, sys, wave
sys.stdin.reconfigure(encoding="utf-8")
print("carregando...", file=sys.stderr)
print("> uma linha que a biblioteca escreve na tela")           # não é JSON: o motor ignora
print(json.dumps({"pronto": True, "dispositivo": "cuda", "placa": "RTX 4060", "vozes": ["Ana Florence"]}), flush=True)
pedidos = []
for linha in sys.stdin:
    p = json.loads(linha)
    if p.get("cmd") == "sair":
        break
    if p["texto"] == "erro":
        print(json.dumps({"erro": "falhou de propósito"}), flush=True)
        continue
    with wave.open(p["saida"], "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(i / 8))) for i in range(12000)))
    with open(p["saida"] + ".json", "w", encoding="utf-8") as f:
        json.dump(p, f, ensure_ascii=False)
    print(json.dumps({"ok": True}), flush=True)
'''


def pacote_falso(pasta):
    """Um motor "instalado": o python do ambiente é o deste teste e o servidor é o de mentira."""
    python = vl.python_do_motor(pasta)
    python.parent.mkdir(parents=True)
    os.symlink(sys.executable, python) if os.name != "nt" else python.write_bytes(open(sys.executable, "rb").read())
    (pasta / "instalado.json").write_text(json.dumps({"gpu": True}), encoding="utf-8")
    vl.arquivo_servidor(pasta).write_text(SERVIDOR_FALSO, encoding="utf-8")


@pytest.mark.skipif(os.name == "nt", reason="o python falso usa um atalho (symlink)")
def test_motor_fala_com_o_servidor_e_escolhe_as_vozes(tmp_path):
    pasta = tmp_path / "motor_vozes"
    pacote_falso(pasta)
    gravacao = vi.VozImportada("Izael", "izael", vi.GRAVACAO, genero="masculina")
    (tmp_path / "vozes_importadas" / "izael").mkdir(parents=True)
    (tmp_path / "vozes_importadas" / "izael" / "referencia.wav").write_bytes(b"RIFF")
    avisos, progresso = [], []
    motor = vl.MotorLocal(pasta, "Ana Florence", [gravacao], tmp_path, avisar=avisos.append)
    pedidos = [("Olá, tudo bem?", tmp_path / "a.wav"), ("Com a minha voz.", tmp_path / "b.wav", "imp:izael"),
               ("Voz do Gemini.", tmp_path / "c.wav", "Kore"), ("Clonada.", tmp_path / "d.wav", "clone:Izael")]
    motor.sintetizar(pedidos, ao_progresso=progresso.append)
    enviados = [json.loads((tmp_path / f"{n}.wav.json").read_text(encoding="utf-8")) for n in "abcd"]
    assert enviados[0]["voz"] == "Ana Florence" and enviados[0]["idioma"] == "pt"
    assert enviados[1]["referencia"].endswith("referencia.wav") and enviados[3]["referencia"] == enviados[1]["referencia"]
    assert enviados[2]["voz"] in vl.vozes_por_genero("feminina")        # "Kore" é feminina no Gemini
    assert all((tmp_path / f"{n}.wav").is_file() for n in "abcd") and progresso[-1] == 1.0
    assert motor.dispositivo == "cuda" and motor.placa == "RTX 4060" and motor.pedidos == 4
    assert any("RTX 4060" in a for a in avisos)
    with pytest.raises(ErroDublagem, match="falhou de propósito"):
        motor.sintetizar([("erro", tmp_path / "e.wav")])
    motor.fechar()
    assert "carregando" in (pasta / "registro.txt").read_text(encoding="utf-8")   # o que a biblioteca escreve


def test_motor_sem_o_pacote_explica_onde_instalar(tmp_path):
    with pytest.raises(ErroDublagem, match="Instalar o motor de vozes"):
        vl.MotorLocal(tmp_path / "nada").sintetizar([("Oi.", tmp_path / "a.wav")])


def test_vozes_menu_e_equivalentes():
    assert vl.texto_do_menu("Ana Florence") == "Ana Florence (feminina, adulta)"
    assert vl.valor_do_menu("Ana Florence (feminina, adulta)") == "Ana Florence"
    assert vl.valor_do_menu("Importada: Izael Jr (masculina, adulta)") == "imp:izael-jr"
    v = vi.VozImportada("Izael", "izael", vi.GRAVACAO, genero="masculina", idade="jovem")
    assert vl.menu_da_importada(v) == "Importada: Izael (masculina, jovem)"
    assert vl.perfil_da_voz("imp:izael", [v]) == "masculina, jovem" and vl.perfil_da_voz("Damien Black") != ""
    assert vl.equivalente("Charon") in vl.vozes_por_genero("masculina")
    assert vl.equivalente("Charon") == vl.equivalente("Charon")                 # sempre a mesma
    assert vl.VOZ_PADRAO in vl.VOZES_PRONTAS


def uv_falso():
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        dados = b"#!/bin/sh\n"
        info = tarfile.TarInfo("uv-x86_64-unknown-linux-gnu/uv")
        info.size = len(dados)
        t.addfile(info, io.BytesIO(dados))
    return buf.getvalue()


@pytest.mark.parametrize("gpu", [True, False])
def test_instalar_com_o_uv(tmp_path, gpu):
    baixados, comandos, etapas = [], [], []

    def baixar(url, destino, progresso):
        baixados.append(url)
        destino.write_bytes(uv_falso())

    def executar(argumentos, **k):
        comandos.append(argumentos)
        assert k["env"]["UV_PYTHON_INSTALL_DIR"].startswith(str(tmp_path))     # tudo dentro da pasta do pacote
        if argumentos[1] == "venv":
            python = vl.python_do_motor(tmp_path, "linux")
            python.parent.mkdir(parents=True)
            python.write_text("")
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    info = vl.instalar(tmp_path, gpu=gpu, sistema="linux", baixar=baixar, executar=executar,
                       ao_progresso=lambda f, t: etapas.append(f))
    assert baixados == [vl.URL_UV + "uv-x86_64-unknown-linux-gnu.tar.gz"]
    assert [c[1:3] for c in comandos] == [["venv", str(tmp_path / "ambiente")], ["pip", "install"],
                                          ["pip", "install"]]
    assert (vl.INDICE_GPU if gpu else vl.INDICE_CPU) in comandos[1] and "torch==2.8.0" in comandos[1]
    assert "coqui-tts==0.27.5" in comandos[2] and "transformers>=4.57,<5" in comandos[2]
    assert info["gpu"] is gpu and vl.instalado(tmp_path)["gpu"] is gpu and etapas[-1] == 1.0
    assert "tts_to_file" in vl.arquivo_servidor(tmp_path).read_text(encoding="utf-8")
    comandos.clear()                                     # de novo: o Python já está lá, só confere os pacotes
    vl.instalar(tmp_path, gpu=gpu, sistema="linux", baixar=baixar, executar=executar)
    assert [c[1] for c in comandos] == ["pip", "pip"] and len(baixados) == 1


def test_instalar_explica_a_falha(tmp_path):
    def executar(argumentos, **k):
        if argumentos[1] == "venv":
            vl.python_do_motor(tmp_path, "linux").parent.mkdir(parents=True)
            vl.python_do_motor(tmp_path, "linux").write_text("")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=1, stdout="", stderr="erro\nNo space left on device")
    with pytest.raises(ErroDublagem, match="PyTorch: No space left"):
        vl.instalar(tmp_path, gpu=True, sistema="linux", baixar=lambda u, d, p: d.write_bytes(uv_falso()),
                    executar=executar)
    assert vl.instalado(tmp_path) is None


def test_avaliar_a_fala_ouvida_pelo_whisper():
    def ditas(texto, fim=0.0):
        palavras = texto.split()
        return [(p, fim + i * 0.3, fim + i * 0.3 + 0.25) for i, p in enumerate(palavras)]
    assert vl.avaliar("E cuidado. Tem algo se mexendo nas árvores.",
                      ditas("E cuidado, tem algo se mexendo nas árvores."))[0] == "ok"
    acao, corte, _ = vl.avaliar("E cuidado. Tem algo se mexendo nas árvores.",
                                ditas("e cuidado tem algo se mexendo nas árvores u"))   # sobra no fim
    assert acao == "cortar" and abs(corte - (7 * 0.3 + 0.25 + vl.FOLGA_DO_CORTE)) < 1e-6
    assert vl.avaliar("E cuidado. Tem algo se mexendo.", ditas("e cuidado onto tem algo se mexendo"))[0] == "refazer"
    assert vl.avaliar("Quer cruzar a floresta?", ditas("que se com autosos esse"))[0] == "refazer"
    # o Whisper separou uma palavra ("a noitecer"): não é sobra, não corta a palavra de verdade
    assert vl.avaliar("Ei, você! O portão fecha ao anoitecer.", ditas("ei voce o portao fecha a noitecer"))[0] == "ok"


@pytest.mark.skipif(os.name == "nt", reason="o python falso usa um atalho (symlink)")
def test_motor_corta_a_sobra_e_gera_de_novo_a_embolada(tmp_path):
    pasta = tmp_path / "motor_vozes"
    pacote_falso(pasta)
    respostas = {"corta.wav": [("cortar", 0.2, 0.9)], "refaz.wav": [("refazer", None, 0.4), ("ok", None, 1.0)]}

    def conferir(texto, wav):
        nome = wav.name.split("-tentativa")[0] + ".wav" if "-tentativa" in wav.name else wav.name
        return respostas[nome].pop(0)
    avisos = []
    motor = vl.MotorLocal(pasta, conferir=conferir, avisar=avisos.append)
    motor.sintetizar([("Corta.", tmp_path / "corta.wav"), ("Refaz.", tmp_path / "refaz.wav")])
    with wave.open(str(tmp_path / "corta.wav")) as w:                  # 12000 quadros -> 0,3 s (o mínimo)
        assert w.getnframes() == int(0.3 * 24000)
    assert (motor.cortadas, motor.refeitas, motor.pedidos) == (1, 1, 3)
    assert not list(tmp_path.glob("*-tentativa*.wav")) and (tmp_path / "refaz.wav").is_file()
    assert any("1 fala(s) com sobra" in a for a in avisos)
    motor.fechar()
