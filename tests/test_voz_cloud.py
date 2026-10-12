"""Google Cloud TTS (Standard, WaveNet, Neural2, Studio): vozes, ler as falas, cota grátis do mês e erros explicados.
Tudo com um Google de mentira: nada vai para a internet."""
import base64
import io
import math
import wave
from array import array
from types import SimpleNamespace

import pytest

from jellyfin_tools import gastos, voz_cloud
from jellyfin_tools.dublagem import ErroDublagem


def wav_de(segundos: float, taxa: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(taxa)
        w.writeframes(array("h", (int(8000 * math.sin(i / 8)) for i in range(int(taxa * segundos)))).tobytes())
    return buf.getvalue()


class GoogleFalso:
    def __init__(self, codigo=200, texto=""):
        self.pedidos, self.codigo, self.texto = [], codigo, texto

    def __call__(self, url, params=None, json=None, timeout=None):
        self.pedidos.append((url, params, json))
        if self.codigo != 200:
            return SimpleNamespace(status_code=self.codigo, text=self.texto, json=lambda: {})
        letras = len(json["input"]["text"])
        dados = base64.b64encode(wav_de(0.05 * letras)).decode()          # o Google devolve WAV em base64
        return SimpleNamespace(status_code=200, text="", json=lambda: {"audioContent": dados})


def test_nomes_tipos_e_menus():
    assert voz_cloud.nome_da_voz("WaveNet", "A") == "pt-BR-Wavenet-A"         # no nome é "Wavenet"
    assert voz_cloud.tipo_da_voz("pt-BR-Wavenet-A") == "WaveNet"
    assert voz_cloud.tipo_da_voz("pt-BR-Studio-C") == "Studio"
    assert voz_cloud.vozes_do_tipo("Studio") == ["pt-BR-Studio-B", "pt-BR-Studio-C"]
    assert voz_cloud.texto_da_voz("pt-BR-Neural2-B") == "pt-BR-Neural2-B (masculina)"


def test_custo_so_passa_a_contar_depois_da_cota_gratis():
    assert voz_cloud.custo_estimado(500_000, "Neural2") == 0                    # dentro do 1 milhão grátis
    assert voz_cloud.custo_estimado(500_000, "Neural2", ja_usados=800_000) == pytest.approx(300_000 * 16 / 1e6)
    assert voz_cloud.custo_estimado(100, "Neural2", ja_usados=2_000_000) == pytest.approx(100 * 16 / 1e6)


def test_le_as_falas_grava_wav_e_conta_a_cota(tmp_path):
    g = gastos.configurar(tmp_path / "gastos.json")
    google = GoogleFalso()
    motor = voz_cloud.MotorCloudTTS("AIza-x", "pt-BR-Neural2-B", postar=google, esperar=lambda s: None)
    motor.sintetizar([("Olá, tudo bem?", tmp_path / "1.wav"), ("Tchau.", tmp_path / "2.wav", "pt-BR-Standard-A")])
    assert (tmp_path / "1.wav").is_file() and (tmp_path / "2.wav").is_file()
    corpos = {j["input"]["text"]: j for _, _, j in google.pedidos}
    assert corpos["Olá, tudo bem?"]["voice"] == {"languageCode": "pt-BR", "name": "pt-BR-Neural2-B"}
    assert corpos["Tchau."]["voice"]["name"] == "pt-BR-Standard-A"                # voz por fala, se vier
    assert corpos["Tchau."]["audioConfig"] == {"audioEncoding": "LINEAR16", "sampleRateHertz": 24000}
    assert google.pedidos[0][1] == {"key": "AIza-x"}
    assert g.caracteres() == {"Neural2": 14, "Standard": 6} and g.total() == 0  # dentro da cota: não custa


def test_acima_da_cota_vira_gasto_e_o_teto_para(tmp_path):
    g = gastos.configurar(tmp_path / "gastos.json")
    g.registrar_caracteres("Studio", 99_990, voz_cloud.TIPOS)                  # quase no fim dos 100 mil grátis
    motor = voz_cloud.MotorCloudTTS("k", "pt-BR-Studio-B", postar=GoogleFalso(), esperar=lambda s: None)
    motor.sintetizar([("Uma frase com trinta letras!!", tmp_path / "1.wav")])
    assert g.do_mes()["Google TTS"] == pytest.approx(19 * 160 / 1e6)          # só as 19 letras além da cota
    g.teto = 0.000001
    with pytest.raises(ErroDublagem, match="teto de gastos"):
        motor.sintetizar([("De novo.", tmp_path / "2.wav")])


@pytest.mark.parametrize("codigo, texto, motivo", [
    (403, "Cloud Text-to-Speech API has not been used in project 123 before or it is disabled", "não está ativada"),
    (403, "This API method requires billing to be enabled", "faturamento"),
    (400, "API key not valid. Please pass a valid API key.", "recusada"),
])
def test_erros_do_google_explicados(tmp_path, codigo, texto, motivo):
    motor = voz_cloud.MotorCloudTTS("k", postar=GoogleFalso(codigo, texto), esperar=lambda s: None)
    with pytest.raises(ErroDublagem, match=motivo):
        motor.sintetizar([("Oi.", tmp_path / "1.wav")])


def test_validar_lista_as_vozes_pt_br():
    resposta = {"voices": [{"name": "pt-BR-Neural2-A"}, {"name": "pt-BR-Wavenet-E"}, {"name": "pt-PT-Wavenet-A"},
                           {"name": "pt-BR-Chirp3-HD-Aoede"}, {"name": "pt-BR-Studio-B"}]}
    pedidos = []

    def obter(url, params=None, timeout=None):
        pedidos.append((url, params))
        return SimpleNamespace(status_code=200, text="", json=lambda: resposta)
    assert voz_cloud.listar_vozes("k", obter) == ["pt-BR-Neural2-A", "pt-BR-Studio-B", "pt-BR-Wavenet-E"]
    assert pedidos[0][1] == {"languageCode": "pt-BR", "key": "k"}
    with pytest.raises(ErroDublagem, match="preencha"):
        voz_cloud.listar_vozes(" ")
    with pytest.raises(ErroDublagem, match="recusada"):
        voz_cloud.listar_vozes("k", lambda *a, **k: SimpleNamespace(status_code=403, text="denied", json=dict))


class _Gravador:
    """Faz o papel de um motor: anota os textos (e a voz) e grava um wav curto."""

    def __init__(self, nome, feitos, falhar=None):
        self.nome, self.feitos, self.falhar, self.pedidos = nome, feitos, falhar, 0

    def sintetizar(self, pedidos, parar=None, ao_progresso=None):
        if self.falhar:
            raise ErroDublagem(self.falhar)
        for p in pedidos:
            self.feitos.append((self.nome, p[0], p[2] if len(p) > 2 else ""))
            with wave.open(str(p[1]), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(24000)
                w.writeframes(b"\x01\x00" * 100)


def test_figurantes_no_google_cloud_ate_a_cota_e_depois_no_piper(tmp_path):
    from jellyfin_tools.dublagem import MotorMisto
    g = gastos.configurar(tmp_path / "gastos.json")
    feitos, avisos = [], []
    motor = MotorMisto(_Gravador("gemini", feitos), lambda voz: _Gravador(f"piper {voz}", feitos),
                       cloud=lambda: _Gravador("cloud", feitos), reserva="faber", avisar=avisos.append)
    motor.sintetizar([("Principal.", tmp_path / "1.wav", "Charon"),
                      ("Guarda.", tmp_path / "2.wav", "cloud:pt-BR-Neural2-B"),
                      ("Moça.", tmp_path / "3.wav", "cloud:pt-BR-Neural2-A")])
    assert sorted(feitos) == [("cloud", "Guarda.", "pt-BR-Neural2-B"), ("cloud", "Moça.", "pt-BR-Neural2-A"),
                              ("gemini", "Principal.", "Charon")]
    assert motor.no_cloud == 2 and not avisos
    g.registrar_caracteres("Neural2", 960_000, voz_cloud.TIPOS)               # passou de 95% da cota do mês
    feitos.clear()
    motor.sintetizar([("Outro guarda.", tmp_path / "4.wav", "cloud:pt-BR-Neural2-B")])
    assert feitos == [("piper faber", "Outro guarda.", "")] and "cota grátis" in avisos[0]
    gastos.configurar(None)


def test_figurantes_voltam_para_o_piper_se_o_google_cloud_falhar(tmp_path):
    from jellyfin_tools.dublagem import MotorMisto
    feitos, avisos, criados = [], [], []
    motor = MotorMisto(_Gravador("gemini", feitos), lambda voz: _Gravador(f"piper {voz}", feitos),
                       cloud=lambda: criados.append(1) or _Gravador("cloud", feitos, falhar="chave recusada"),
                       reserva="faber", avisar=avisos.append, cabe=lambda voz, n: True)
    motor.sintetizar([("Guarda.", tmp_path / "1.wav", "cloud:pt-BR-Neural2-B")])
    motor.sintetizar([("Guarda 2.", tmp_path / "2.wav", "cloud:pt-BR-Neural2-B")])
    assert feitos == [("piper faber", "Guarda.", ""), ("piper faber", "Guarda 2.", "")]
    assert criados == [1] and "chave recusada" in avisos[0]                   # não insiste na mesma dublagem


def test_sem_registro_de_gastos_nao_arrisca_a_cota():
    from jellyfin_tools.dublagem import cabe_na_cota
    gastos.configurar(None)
    assert not cabe_na_cota("pt-BR-Neural2-B", 10)


def test_voz_de_cada_figurante_pelo_genero():
    from jellyfin_tools import personagens
    lista = [personagens.Personagem("Conde", "m", falas=list(range(50))),
             personagens.Personagem("Guarda", "m", falas=[50, 51]),
             personagens.Personagem("Moça", "f", falas=[52]), personagens.Personagem("Velha", "f", falas=[53]),
             personagens.Personagem("Robô", "?", falas=[54])]
    mapa = personagens.distribuir_vozes(lista, "Charon", figurante="cloud:Neural2")
    assert mapa["Conde"] == "Charon" and mapa["Guarda"] == "cloud:pt-BR-Neural2-B"
    assert (mapa["Moça"], mapa["Velha"]) == ("cloud:pt-BR-Neural2-A", "cloud:pt-BR-Neural2-C")   # alterna
    assert mapa["Robô"].startswith("cloud:pt-BR-Neural2-")
    assert personagens.voz_de_figurante("piper:faber", "f") == "piper:faber"
    assert personagens.voz_de_figurante("cloud:Studio", "f") == "cloud:pt-BR-Studio-C"         # Studio: B e C
