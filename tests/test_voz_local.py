"""Motor de vozes no PC (XTTS-v2): o instalador (com um uv de mentira) e o motor conversando com um servidor de
mentira (um Python que "fala" um tom puro), sem baixar nada e sem o PyTorch."""
import io
import json
import os
import sys
import tarfile
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from jellyfin_tools import voz_local as vl
from jellyfin_tools import vozes_importadas as vi
from jellyfin_tools.dublagem import ErroDublagem

SERVIDOR_FALSO = r'''
import json, math, os, struct, sys, wave
sys.stdin.reconfigure(encoding="utf-8")
print("carregando...", file=sys.stderr)
print("> uma linha que a biblioteca escreve na tela")           # não é JSON: o motor ignora
memoria = float(os.environ["MEMORIA_FALSA"]) if os.environ.get("MEMORIA_FALSA") else None
print(json.dumps({"pronto": True, "dispositivo": "cuda", "placa": "RTX 4060", "memoria": memoria,
                  "vozes": ["Ana Florence"]}), flush=True)
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


def pacote_falso(pasta, monkeypatch):
    """Um motor "instalado": o python do ambiente é o deste teste e o servidor é o de mentira."""
    monkeypatch.setattr(vl, "SERVIDOR", SERVIDOR_FALSO)
    python = vl.python_do_motor(pasta)
    python.parent.mkdir(parents=True)
    os.symlink(sys.executable, python) if os.name != "nt" else python.write_bytes(open(sys.executable, "rb").read())
    (pasta / "instalado.json").write_text(json.dumps({"gpu": True}), encoding="utf-8")
    vl.arquivo_servidor(pasta).write_text(SERVIDOR_FALSO, encoding="utf-8")


@pytest.mark.skipif(os.name == "nt", reason="o python falso usa um atalho (symlink)")
def test_motor_fala_com_o_servidor_e_escolhe_as_vozes(tmp_path, monkeypatch):
    pasta = tmp_path / "motor_vozes"
    pacote_falso(pasta, monkeypatch)
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
    assert enviados[0]["frases"] == [["Olá, tudo bem?", 0.0]] and enviados[1]["frases"] == [["Com a minha voz", 0.0]]
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
                       ao_progresso=lambda f, t: etapas.append(f), medir_espaco=lambda p: 100.0)
    assert baixados == [vl.URL_UV + "uv-x86_64-unknown-linux-gnu.tar.gz"]
    assert [c[1:3] for c in comandos] == [["venv", str(tmp_path / "ambiente")], ["pip", "install"],
                                          ["pip", "install"]]
    assert (vl.INDICE_GPU if gpu else vl.INDICE_CPU) in comandos[1] and "torch==2.8.0" in comandos[1]
    assert "coqui-tts==0.27.5" in comandos[2] and "transformers>=4.57,<5" in comandos[2]
    assert info["gpu"] is gpu and vl.instalado(tmp_path)["gpu"] is gpu and etapas[-1] == 1.0
    assert "frases" in vl.arquivo_servidor(tmp_path).read_text(encoding="utf-8")
    comandos.clear()                                     # de novo: o Python já está lá, só confere os pacotes
    vl.instalar(tmp_path, gpu=gpu, sistema="linux", baixar=baixar, executar=executar, medir_espaco=lambda p: 100.0)
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
                    executar=executar, medir_espaco=lambda p: 100.0)
    assert vl.instalado(tmp_path) is None


def test_instalar_confere_o_espaco_no_disco(tmp_path):
    """Sem espaço, avisa ANTES de baixar (antes, parava no meio com "No space left on device")."""
    comandos = []

    def executar(argumentos, **k):
        comandos.append(argumentos)
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    pasta = tmp_path / "motor_vozes"
    with pytest.raises(ErroDublagem, match=r"falta espaço no disco .*uns 9 GB livres e há 3\.2 GB"):
        vl.instalar(pasta, gpu=True, sistema="linux", baixar=None, executar=executar, medir_espaco=lambda p: 3.2)
    with pytest.raises(ErroDublagem, match="uns 4 GB"):                     # sem placa: o PyTorch é menor
        vl.instalar(pasta, gpu=False, sistema="linux", baixar=None, executar=executar, medir_espaco=lambda p: 3.2)
    assert comandos == [] and not pasta.exists()
    assert vl.espaco_livre(tmp_path / "ainda" / "nao" / "existe") > 0         # mede o disco da pasta de cima
    vl.conferir_espaco(pasta, 2.0, medir=lambda p: None)                     # não deu para medir: segue


# ----------------------------------------------------------------- o servidor de verdade, com bibliotecas de mentira
TORCH_FALSO = """
import os
class _Cuda:
    class OutOfMemoryError(RuntimeError):
        pass
    def is_available(self):
        return bool(os.environ.get("PLACA"))
    def get_device_name(self, i):
        return os.environ["PLACA"]
    def get_device_properties(self, i):
        class _Propriedades:
            total_memory = int(float(os.environ.get("MEMORIA_FALSA", "8")) * 1024 ** 3)
        return _Propriedades()
    def empty_cache(self):
        pass
cuda = _Cuda()
"""
TTS_FALSO = """
import math, os, struct, wave
class _Sintetizador:
    output_sample_rate = 24000
    def save_wav(self, wav, path):
        with wave.open(path, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000)
            w.writeframes(b"".join(struct.pack("<h", int(8000 * x)) for x in wav))
class TTS:
    def __init__(self, nome):
        self.speakers, self.synthesizer, self.lugar = ["Ana Florence"], _Sintetizador(), "cpu"
    def to(self, lugar):
        if lugar == "cuda" and os.environ.get("FALHA") == "carregar":
            raise RuntimeError("CUDA out of memory. Tried to allocate 2.00 GiB")
        self.lugar = lugar
        return self
    def tts(self, text, language, split_sentences, **voz):
        if self.lugar == "cuda" and os.environ.get("FALHA") == "falar":
            raise RuntimeError("CUDA error: no kernel image is available for execution on the device")
        return [math.sin(i / 8) * 0.5 for i in range(2400)]
"""


def bibliotecas_falsas(pasta, monkeypatch, placa="GT 1030", falha=""):
    """torch e TTS de mentira (a placa "falha" ao carregar ou ao falar), na frente das bibliotecas deste Python."""
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "torch.py").write_text(TORCH_FALSO, encoding="utf-8")
    (pasta / "TTS").mkdir(exist_ok=True)
    (pasta / "TTS" / "__init__.py").write_text("", encoding="utf-8")
    (pasta / "TTS" / "api.py").write_text(TTS_FALSO, encoding="utf-8")
    pacotes = [p for p in sys.path if p.endswith("site-packages")]           # o numpy deste Python
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join([str(pasta)] + pacotes))
    monkeypatch.setenv("PLACA", placa)
    monkeypatch.setenv("FALHA", falha)


def pacote_de_verdade(pasta):
    """Um motor "instalado" com o servidor DE VERDADE (o MotorLocal escreve o SERVIDOR do Maestro)."""
    python = vl.python_do_motor(pasta)
    python.parent.mkdir(parents=True)
    os.symlink(sys.executable, python)
    (pasta / "instalado.json").write_text(json.dumps({"gpu": True}), encoding="utf-8")


@pytest.mark.skipif(os.name == "nt", reason="o python falso usa um atalho (symlink)")
@pytest.mark.parametrize("falha", ["carregar", "falar"])
def test_plano_b_vai_pelo_processador_quando_a_placa_nao_aguenta(tmp_path, monkeypatch, falha):
    bibliotecas_falsas(tmp_path / "libs", monkeypatch, falha=falha)
    pasta = tmp_path / "motor_vozes"
    pacote_de_verdade(pasta)
    avisos = []
    motor = vl.MotorLocal(pasta, "Ana Florence", avisar=avisos.append)
    motor.sintetizar([("Oi. Tudo bem?", tmp_path / "a.wav"), ("De novo.", tmp_path / "b.wav")])
    with wave.open(str(tmp_path / "a.wav")) as w:                        # as duas frases + a pausa
        assert w.getnframes() == 2 * 2400 + int(24000 * vl.PAUSA_PONTO)
    assert (tmp_path / "b.wav").is_file() and motor.dispositivo == "cpu" and motor.placa == ""
    if falha == "carregar":
        assert any("não aguentou o modelo" in a and "mais devagar" in a for a in avisos)
    else:
        assert any("GT 1030" in a for a in avisos)                         # abriu na placa...
        assert sum("segue pelo processador" in a for a in avisos) == 1      # ...e passou para o processador uma vez
    motor.fechar()
    assert "processador" in (pasta / "registro.txt").read_text(encoding="utf-8")


@pytest.mark.skipif(os.name == "nt", reason="o python falso usa um atalho (symlink)")
def test_servidor_de_verdade_na_placa_que_aguenta(tmp_path, monkeypatch):
    bibliotecas_falsas(tmp_path / "libs", monkeypatch)
    pasta = tmp_path / "motor_vozes"
    pacote_de_verdade(pasta)
    motor = vl.MotorLocal(pasta, "Ana Florence")
    motor.sintetizar([("Oi.", tmp_path / "a.wav")])
    assert (motor.dispositivo, motor.placa) == ("cuda", "GT 1030")
    motor.fechar()


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
def test_motor_corta_a_sobra_e_gera_de_novo_a_embolada(tmp_path, monkeypatch):
    pasta = tmp_path / "motor_vozes"
    pacote_falso(pasta, monkeypatch)
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


def test_frases_sem_o_ponto_final():
    """O XTTS-v2 lia o ponto final ("...nas árvores, ponto"): cada frase vai sem ele, com uma pausa no lugar."""
    assert vl.frases_para_falar("E cuidado. Tem algo se mexendo nas árvores.") == [
        ["E cuidado", vl.PAUSA_PONTO], ["Tem algo se mexendo nas árvores", 0.0]]
    assert vl.frases_para_falar("Ei, você! Quer cruzar a floresta? Fale antes.") == [
        ["Ei, você!", vl.PAUSA_PERGUNTA], ["Quer cruzar a floresta?", vl.PAUSA_PERGUNTA], ["Fale antes", 0.0]]
    assert vl.frases_para_falar("Bem... não sei; talvez: amanhã...") == [["Bem, não sei, talvez, amanhã", 0.0]]
    assert vl.frases_para_falar("Sim.") == [["Sim", 0.0]]
    for frase, _ in vl.frases_para_falar("Um. Dois... Três; quatro: cinco."):
        assert not frase.endswith((".", "…", ";", ":"))


class ChatterboxFalso:
    """O 2º motor de mentira: anota cada fala (e falha quando mandado)."""

    def __init__(self, falhar_em=None):
        self.falas, self.falhar_em, self.fechado = [], falhar_em, False

    def falar(self, texto, saida, referencia, emocao, parar=None, idioma="pt"):
        if texto == self.falhar_em:
            raise ErroDublagem("o Chatterbox não abriu: sem memória")
        self.falas.append((texto, str(referencia), emocao))
        Path(saida).write_bytes(b"RIFF")

    def fechar(self):
        self.fechado = True

    def aberto(self):
        return False


@pytest.mark.skipif(os.name == "nt", reason="o python falso usa um atalho (symlink)")
def test_emocao_vai_pela_gravacao_da_emocao_ou_pelo_chatterbox(tmp_path, monkeypatch):
    pasta = tmp_path / "motor_vozes"
    pacote_falso(pasta, monkeypatch)
    izael = vi.VozImportada("Izael", "izael", vi.GRAVACAO, genero="masculina", emocoes=["brava", "sussurro"])
    gravacoes = tmp_path / "vozes_importadas" / "izael"
    gravacoes.mkdir(parents=True)
    for nome in ("referencia", "brava", "sussurro"):
        (gravacoes / f"{nome}.wav").write_bytes(b"RIFF")
    chatterbox, avisos = ChatterboxFalso(), []
    motor = vl.MotorLocal(pasta, "Ana Florence", [izael], tmp_path, emocao=chatterbox, avisar=avisos.append)
    motor.sintetizar([
        ("Sai daqui!", tmp_path / "a.wav", "imp:izael", "Nesta fala: gritando, com força."),   # grito -> a brava
        ("Fala baixo.", tmp_path / "b.wav", "imp:izael", "Cena: um esconderijo. Nesta fala: sussurrando."),
        ("Por favor.", tmp_path / "c.wav", "imp:izael", "Nesta fala: chorando."),     # sem a de choro: Chatterbox
        ("Socorro!", tmp_path / "d.wav", "", "Nesta fala: com medo, apavorada."),     # voz pronta: Chatterbox
        ("Tudo bem.", tmp_path / "e.wav", "imp:izael", "Ritmo: cerca de 1,0 s no original."),        # neutra
    ])
    enviados = {n: json.loads((tmp_path / f"{n}.wav.json").read_text(encoding="utf-8")) for n in "abe"}
    assert enviados["a"]["referencia"].endswith("brava.wav")
    assert json.loads((tmp_path / "b.wav.json").read_text(encoding="utf-8"))["referencia"].endswith("sussurro.wav")
    assert enviados["e"]["referencia"].endswith("referencia.wav")
    pronta = pasta / "referencias" / "ana-florence.wav"                  # a fala que o Chatterbox imita
    pedido = json.loads((pasta / "referencias" / "ana-florence.tmp.wav.json").read_text(encoding="utf-8"))
    assert pronta.is_file() and pedido["texto"] == vl.FRASE_DE_REFERENCIA and pedido["voz"] == "Ana Florence"
    assert chatterbox.falas == [("Por favor.", str(gravacoes / "referencia.wav"), "choro"),
                                ("Socorro!", str(pronta), "medo")]
    assert any("2 fala(s) com a gravação de emoção da voz, 2 pelo Chatterbox" in a for a in avisos)
    motor.fechar()
    assert chatterbox.fechado


@pytest.mark.skipif(os.name == "nt", reason="o python falso usa um atalho (symlink)")
def test_chatterbox_que_falha_deixa_o_resto_neutro(tmp_path, monkeypatch):
    pasta = tmp_path / "motor_vozes"
    pacote_falso(pasta, monkeypatch)
    chatterbox, avisos = ChatterboxFalso(falhar_em="Socorro!"), []
    motor = vl.MotorLocal(pasta, "Ana Florence", emocao=chatterbox, avisar=avisos.append)
    motor.sintetizar([("Socorro!", tmp_path / "a.wav", "", "Nesta fala: gritando."),
                      ("Corre!", tmp_path / "b.wav", "", "Nesta fala: gritando.")])
    for n in "ab":                                                      # as duas pelo XTTS-v2, neutras
        assert json.loads((tmp_path / f"{n}.wav.json").read_text(encoding="utf-8"))["voz"] == "Ana Florence"
    assert motor.emocao is None and chatterbox.fechado and chatterbox.falas == []
    assert sum("o Chatterbox falhou" in a for a in avisos) == 1
    motor.fechar()


@pytest.mark.skipif(os.name == "nt", reason="o python falso usa um atalho (symlink)")
@pytest.mark.parametrize("memoria", ["8", "24"])
def test_um_de_cada_vez_na_placa_pequena(tmp_path, monkeypatch, memoria):
    """RTX 4060 (8 GB): primeiro as falas do XTTS-v2, ele fecha, e só então o Chatterbox. Com 24 GB, juntos."""
    monkeypatch.setenv("MEMORIA_FALSA", memoria)
    pasta = tmp_path / "motor_vozes"
    pacote_falso(pasta, monkeypatch)
    ordem = []

    class Espiao(ChatterboxFalso):
        def falar(self, texto, saida, referencia, emocao, parar=None, idioma="pt"):
            ordem.append((texto, "XTTS aberto" if motor.aberto() else "XTTS fechado"))
            super().falar(texto, saida, referencia, emocao, parar, idioma)

    avisos = []
    motor = vl.MotorLocal(pasta, "Ana Florence", emocao=Espiao(), avisar=avisos.append)
    motor.sintetizar([("Corre!", tmp_path / "a.wav", "", "Nesta fala: gritando."),
                      ("Tudo bem.", tmp_path / "b.wav"),
                      ("Socorro!", tmp_path / "c.wav", "", "Nesta fala: chorando."),
                      ("Até logo.", tmp_path / "d.wav")])
    assert all((tmp_path / f"{n}.wav").is_file() for n in "abcd") and motor.memoria == float(memoria)
    if memoria == "8":
        assert ordem == [("Corre!", "XTTS fechado"), ("Socorro!", "XTTS fechado")]   # as com emoção no fim
        assert any("um de cada vez na placa (8 GB)" in a and "2 fala(s)" in a for a in avisos)
        motor.sintetizar([("De novo.", tmp_path / "e.wav")])            # o XTTS-v2 abre de novo sozinho
        assert (tmp_path / "e.wav").is_file()
    else:
        assert ordem == [("Corre!", "XTTS aberto"), ("Socorro!", "XTTS aberto")] and not any(
            "um de cada vez" in a for a in avisos)
    motor.fechar()
