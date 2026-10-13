"""Voz clonada (réplica do Gemini): preparar as gravações, criar a voz, guardar a chave só no PC e usar na dublagem.
Tudo com um Google de mentira: nada vai para a internet."""
import base64
import io
import json
import math
import wave
from array import array
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from jellyfin_tools import microfone, personagens, voz_clonada, voz_gemini
from jellyfin_tools.dublagem import ErroDublagem, localizar_ffmpeg
from tests.test_voz_gemini import GeminiFalso

TAXA = 24000
FFMPEG = localizar_ffmpeg()


def wav(segundos: float, taxa: int = TAXA, silencio_nas_pontas: float = 0.0) -> bytes:
    sil = [0] * int(taxa * silencio_nas_pontas)
    som = [int(9000 * math.sin(2 * math.pi * 220 * i / taxa)) for i in range(int(taxa * segundos))]
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(taxa)
        w.writeframes(array("h", sil + som + sil).tobytes())
    return buf.getvalue()


class VozesFalsas:
    """O client.voices de mentira: guarda o pedido e devolve uma chave (ou recusa, como o Google faz)."""

    def __init__(self, recusar=False):
        self.pedidos, self.recusar = [], recusar

    def create(self, **k):
        if self.recusar:
            raise type("ClientError", (Exception,), {"code": 400})("FAILED_PRECONDITION: consent verification failed")
        self.pedidos.append(k)
        return SimpleNamespace(key="voicekey_abc123", id=None,
                               expire_time=datetime(2027, 10, 11, tzinfo=timezone.utc))


def test_criar_manda_as_duas_gravacoes_sem_guardar_no_google():
    vozes = VozesFalsas()
    nova = voz_clonada.criar(SimpleNamespace(voices=vozes), "Izael", "Izael Depetriz", wav(12), wav(6))
    pedido = vozes.pedidos[0]
    assert pedido["store"] is False                                 # a chave fica só neste PC
    voz = pedido["voice"]
    assert voz["type"] == "replicated" and voz["model"] == voz_gemini.MODELO_PADRAO
    assert voz["replicated"]["source_audio"]["mime_type"] == "audio/wav"
    assert base64.b64decode(voz["replicated"]["consent_audio"]["data"]).startswith(b"RIFF")
    assert nova.chave == "voicekey_abc123" and nova.valor == "clone:Izael" and nova.autorizada_por == "Izael Depetriz"
    assert nova.expira_em.startswith("2027-10-11") and not nova.vencida()


def test_criar_confere_duracoes_e_explica_a_recusa():
    cliente = SimpleNamespace(voices=VozesFalsas())
    with pytest.raises(ErroDublagem, match="pelo menos"):
        voz_clonada.criar(cliente, "A", "A", wav(3), wav(6))          # referência curta demais
    with pytest.raises(ErroDublagem, match="frase inteira"):
        voz_clonada.criar(cliente, "A", "A", wav(12), wav(1))         # consentimento cortado
    with pytest.raises(ErroDublagem, match="dono da voz"):
        voz_clonada.criar(cliente, "A", " ", wav(12), wav(6))
    assert not cliente.voices.pedidos                                # nada foi mandado
    with pytest.raises(ErroDublagem, match="mesma pessoa"):
        voz_clonada.criar(SimpleNamespace(voices=VozesFalsas(recusar=True)), "A", "A", wav(12), wav(6))


def test_nome_da_voz_e_o_caminho_do_menu():
    existentes = [voz_clonada.VozClonada("Izael", "Izael", "voicekey_1")]
    assert voz_clonada.validar_nome("  Maria   Clara ") == "Maria Clara"
    for ruim, motivo in (("", "dê um nome"), ("Voz (minha)", "sinais"), ("izael", "já existe")):
        with pytest.raises(ErroDublagem, match=motivo):
            voz_clonada.validar_nome(ruim, existentes)
    texto = voz_clonada.texto_do_menu(voz_clonada.VozClonada("Maria Clara", "Maria", "k"))
    assert texto == "Clonada: Maria Clara (autorizada por Maria)"
    assert voz_clonada.valor_do_menu(texto) == "clone:Maria Clara"
    assert voz_clonada.valor_do_menu("Kore (feminina, firme)") is None
    assert voz_gemini.texto_da_voz("clone:Maria Clara") == "Maria Clara (voz clonada)"


def test_guardar_carregar_e_vencer(tmp_path):
    arquivo = tmp_path / "vozes_clonadas.json"
    antiga = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    vozes = [voz_clonada.VozClonada("Izael", "Izael", "voicekey_1", "2026-10-11 10:00"),
             voz_clonada.VozClonada("Vó", "Dona Ana", "voicekey_2", expira_em=antiga)]
    voz_clonada.salvar(vozes, arquivo)
    lidas = voz_clonada.carregar(arquivo)
    assert [v.nome for v in lidas] == ["Izael", "Vó"]
    assert voz_clonada.chaves(lidas) == {"clone:Izael": "voicekey_1", "clone:Vó": "voicekey_2"}
    assert not lidas[0].vencida() and lidas[1].vencida()
    assert "VENCIDA" in voz_clonada.descrever(lidas[1]) and "autorizada por Dona Ana" in voz_clonada.descrever(lidas[1])
    assert voz_clonada.carregar(tmp_path / "nao_existe.json") == []
    arquivo.write_text("{quebrado", encoding="utf-8")
    assert voz_clonada.carregar(arquivo) == []


def test_motor_troca_o_nome_da_voz_clonada_pela_chave(tmp_path):
    gemini = GeminiFalso()
    motor = voz_gemini.MotorGemini("x", "clone:Izael", cliente=gemini, esperar=lambda s: None,
                                   vozes_clonadas={"clone:Izael": "voicekey_1"})
    motor.sintetizar([("Oi.", tmp_path / "1.wav"), ("Tudo bem?", tmp_path / "2.wav", "Kore")])
    configs = [p["generation_config"]["speech_config"] for p in gemini.pedidos]
    vozes_usadas = {c["voice"] for config in configs for c in config}
    assert vozes_usadas == {"voicekey_1", "Kore"}                    # o nome nunca vai para o Google: só a chave
    assert (tmp_path / "1.wav").exists() and (tmp_path / "2.wav").exists()
    with pytest.raises(ErroDublagem, match="não está neste PC"):
        voz_gemini.MotorGemini("x", "clone:Outro", cliente=gemini)


def test_voz_clonada_principal_vai_para_quem_mais_fala():
    lista = [personagens.Personagem("Pessoa 1", "f", "", list(range(30))),
             personagens.Personagem("Pessoa 2", "m", "", list(range(30, 50)))]
    mapa = personagens.distribuir_vozes(lista, "clone:Izael")
    assert mapa["Pessoa 1"] == "clone:Izael"                          # mesmo com outro gênero (dá para trocar)
    assert mapa["Pessoa 2"] in voz_gemini.VOZES_MASCULINAS


@pytest.mark.skipif(not FFMPEG, reason="sem ffmpeg")
def test_preparar_audio_converte_e_tira_o_silencio(tmp_path):
    origem = tmp_path / "celular.wav"
    origem.write_bytes(wav(4, taxa=44100, silencio_nas_pontas=1.5))
    pronto = voz_clonada.preparar_audio(origem, FFMPEG)
    with wave.open(io.BytesIO(pronto)) as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (24000, 1, 2)
    assert 3.6 < voz_clonada.duracao(pronto) < 4.4                   # os 3 s de silêncio saíram
    with pytest.raises(ErroDublagem, match="não achei"):
        voz_clonada.preparar_audio(tmp_path / "sumiu.mp3", FFMPEG)


def test_gravador_junta_o_que_o_microfone_ouviu():
    class Fluxo:
        def __init__(self, **k):
            self.callback, self.parado = k["callback"], False

        def start(self):
            self.callback(array("h", [1000] * 24000).tobytes(), 24000, None, None)    # 1 s
            self.callback(array("h", [-30000] * 12000).tobytes(), 12000, None, None)  # 0,5 s, alto

        def stop(self):
            self.parado = True

        def close(self):
            pass
    sd = SimpleNamespace(RawInputStream=lambda **k: Fluxo(**k))
    gravador = microfone.Gravador(biblioteca=sd)
    gravador.iniciar()
    assert gravador.gravando and abs(gravador.segundos - 1.5) < 0.01 and gravador.nivel == 1.0
    dados = gravador.parar()
    assert len(dados) == 36000 * 2 and not gravador.gravando


def test_exportar_so_leva_as_vozes_clonadas_com_as_chaves(tmp_path, monkeypatch):
    import zipfile

    from videoscraper import config
    monkeypatch.setattr(config, "ARQUIVO", tmp_path / "config.json")
    config.salvar({"jellyfin": {}})
    (tmp_path / "vozes_clonadas.json").write_text(json.dumps({"vozes": []}), encoding="utf-8")
    assert "vozes_clonadas.json" not in config.exportar(tmp_path / "sem.zip")
    assert "vozes_clonadas.json" in config.exportar(tmp_path / "com.zip", incluir_chaves=True)
    assert "vozes_clonadas.json" in zipfile.ZipFile(tmp_path / "com.zip").namelist()


def test_automacao_confere_a_voz_clonada(tmp_path, monkeypatch):
    from videoscraper import automacao, config
    monkeypatch.setattr(config, "ARQUIVO", tmp_path / "config.json")
    voz_clonada.salvar([voz_clonada.VozClonada("Izael", "Izael", "voicekey_1")], automacao.arquivo_vozes_clonadas())
    vozes = automacao.vozes_clonadas()
    automacao.conferir_voz_clonada("clone:Izael", vozes)               # existe: tudo certo
    automacao.conferir_voz_clonada("Kore", vozes)                      # voz pronta: nada a conferir
    with pytest.raises(automacao.FaltaConfiguracao, match="não está neste PC"):
        automacao.conferir_voz_clonada("clone:Maria", vozes)


def test_aviso_de_validade_para_o_painel_de_saude():
    agora = datetime(2026, 10, 11, 12, tzinfo=timezone.utc)
    def voz(dias):
        return voz_clonada.VozClonada("Izael", "Izael", "k", expira_em=(agora + timedelta(days=dias)).isoformat())
    assert voz_clonada.aviso_de_validade(voz(30), agora) == ""                       # longe: nada a dizer
    assert voz_clonada.aviso_de_validade(voz(5.5), agora) == "Voz clonada Izael: vence em 5 dia(s)"
    assert voz_clonada.aviso_de_validade(voz(0.3), agora) == "Voz clonada Izael: vence hoje"
    assert voz_clonada.aviso_de_validade(voz(-1), agora) == "Voz clonada Izael: venceu (clone de novo)"
    assert voz_clonada.aviso_de_validade(voz_clonada.VozClonada("A", "A", "k"), agora) == ""   # sem data


def test_gravacoes_guardadas_para_clonar_de_novo(tmp_path):
    pasta = voz_clonada.pasta_das_gravacoes(tmp_path, "Vó Ana?*")
    assert pasta.name == "Vó Ana__"                               # sinais que o Windows recusa viram _
    v = voz_clonada.VozClonada("Vó Ana", "Ana", "k")
    assert not v.tem_gravacoes()
    with pytest.raises(ErroDublagem, match="não estão guardadas"):
        voz_clonada.ler_gravacoes(v)
    v.gravacoes = str(voz_clonada.guardar_gravacoes(pasta, wav(12), wav(6)))
    assert v.tem_gravacoes() and "gravações guardadas" in voz_clonada.descrever(v)
    referencia, consentimento = voz_clonada.ler_gravacoes(v)
    assert voz_clonada.duracao(referencia) == pytest.approx(12) and voz_clonada.duracao(consentimento) == pytest.approx(6)
    voz_clonada.apagar_gravacoes(v)
    assert not pasta.exists() and not v.tem_gravacoes()


def test_frase_de_teste_com_a_voz_clonada(tmp_path):
    gemini = GeminiFalso()
    destino = voz_gemini.frase_de_teste("x", "clone:Izael", tmp_path / "teste.wav", {"clone:Izael": "voicekey_1"},
                                        cliente=gemini, esperar=lambda s: None)
    assert destino.is_file() and len(gemini.pedidos) == 1
    assert gemini.pedidos[0]["generation_config"]["speech_config"] == [{"voice": "voicekey_1"}]
    assert voz_gemini.FRASE_DE_TESTE in gemini.pedidos[0]["input"][0]["text"]


def test_tocar_o_wav(tmp_path, monkeypatch):
    arquivo = tmp_path / "frase.wav"
    arquivo.write_bytes(wav(1))
    tocados = []
    sd = SimpleNamespace(play=lambda dados, taxa: tocados.append((len(dados), taxa)))
    microfone.tocar(arquivo, biblioteca=sd, plataforma="linux")
    assert tocados == [(24000, 24000)]
    monkeypatch.setattr(microfone, "_biblioteca", lambda: None)       # sem sounddevice: a janela diz onde está
    with pytest.raises(OSError):
        microfone.tocar(arquivo, plataforma="linux")


def test_texto_de_referencia_curto_e_consentimento_igual_em_partes():
    """O texto de referência é curto e simples (~10 s); a frase de consentimento continua EXATAMENTE a do Google,
    só mostrada em 3 pedaços para ler."""
    assert len(voz_clonada.TEXTO_REFERENCIA.split()) <= 25
    assert " ".join(voz_clonada.CONSENTIMENTO_EM_PARTES) == voz_clonada.FRASE_CONSENTIMENTO
