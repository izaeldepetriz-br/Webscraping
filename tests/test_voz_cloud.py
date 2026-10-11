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
