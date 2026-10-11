"""Voz premium (Gemini): blocos de falas por pedido, corte nas pausas, progresso guardado e voz por personagem.
Tudo com um Gemini de mentira: nada vai para a internet."""
import base64
import io
import json
import math
import wave
from array import array
from pathlib import Path
from types import SimpleNamespace

import pytest

from jellyfin_tools import personagens, voz_gemini
from jellyfin_tools.dublagem import ErroDublagem, dublar_video, falas_da_legenda, localizar_ffmpeg
from jellyfin_tools.traducao import Fala

TAXA = 24000
FFMPEG = localizar_ffmpeg()


def fala_sintetica(segundos: float, freq: float = 220.0) -> array:
    return array("h", (int(8000 * math.sin(2 * math.pi * freq * i / TAXA)) for i in range(int(TAXA * segundos))))


def silencio(segundos: float) -> array:
    return array("h", bytes(2 * int(TAXA * segundos)))


def wav_de(amostras: array) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(TAXA)
        w.writeframes(amostras.tobytes())
    return buf.getvalue()


def duracao(wav: Path) -> float:
    with wave.open(str(wav), "rb") as w:
        return w.getnframes() / w.getframerate()


class GeminiFalso:
    """Lê as falas do pedido e "fala" cada uma: 0,06 s por letra, com uma pausa de 0,5 s entre elas (a <long pause>).
    juntar=True: ignora as pausas (o corte não bate e o bloco tem que ser refeito fala por fala)."""

    def __init__(self, juntar=False, falhar_depois=None):
        self.pedidos, self.juntar, self.falhar_depois = [], juntar, falhar_depois
        self.interactions = self
        self.models = SimpleNamespace(get=lambda model: SimpleNamespace(display_name="Gemini TTS"))

    def create(self, **k):
        if self.falhar_depois is not None and len(self.pedidos) >= self.falhar_depois:
            raise type("ClientError", (Exception,), {"code": 429})("RESOURCE_EXHAUSTED: limite do dia")
        self.pedidos.append(k)
        audio = array("h")
        for item in k["input"]:
            texto = item["text"].replace(voz_gemini.PAUSA, "")
            audio += silencio(0.05) + fala_sintetica(0.06 * len(texto))
            if voz_gemini.PAUSA in item["text"] and not self.juntar:
                audio += silencio(0.5)
        return SimpleNamespace(output_audio=SimpleNamespace(data=base64.b64encode(wav_de(audio)).decode()))


def test_blocos_juntam_falas_seguidas_com_no_maximo_duas_vozes():
    itens = [(f"fala {i}", Path(f"{i}.wav"), v) for i, v in enumerate("AABBCCA")]
    assert [[v for _, _, v in g] for g in voz_gemini.blocos(itens, bloco=10)] == [list("AABB"), list("CCA")]
    assert [len(g) for g in voz_gemini.blocos([(f"x{i}", None, "A") for i in range(70)])] == [30, 30, 10]
    longas = [("y" * 900, None, "A")] * 3                               # 2.000 letras por pedido, no máximo
    assert [len(g) for g in voz_gemini.blocos(longas)] == [2, 1]
    assert voz_gemini.pedidos_estimados(1200) == 40                     # um filme: 40 pedidos em vez de 1.200


def test_corte_nas_pausas_confere_o_tamanho_de_cada_fala():
    audio = fala_sintetica(0.6) + silencio(0.08) + fala_sintetica(0.3) + silencio(0.5) + fala_sintetica(1.2) \
        + silencio(0.5) + fala_sintetica(0.4)
    cortes = voz_gemini.separar_por_pausas(audio, TAXA, [10, 20, 7])   # a pausinha de 0,08 s não é um corte
    assert cortes is not None and len(cortes) == 3
    esperado = [0.6 + 0.08 + 0.3, 1.2, 0.4]                               # cada uma com ~40 ms de folga
    assert all(abs((b - a) / TAXA - e) < 0.1 for (a, b), e in zip(cortes, esperado))
    assert voz_gemini.separar_por_pausas(audio, TAXA, [10, 20, 7, 5]) is None      # pausas de menos
    assert voz_gemini.separar_por_pausas(audio, TAXA, [100, 2, 100]) is None       # tamanho incoerente com o texto
    assert voz_gemini.separar_por_pausas(silencio(1), TAXA, [3, 3]) is None


def test_motor_pede_em_blocos_e_corta_cada_fala(tmp_path):
    gemini = GeminiFalso()
    motor = voz_gemini.MotorGemini("chave", voz="Kore", cliente=gemini, simultaneos=1)
    textos = ["Oi, tudo bem?", "Tudo ótimo, e você?", "Também.", "Vamos embora daqui agora."]
    motor.sintetizar([(t, tmp_path / f"{i}.wav") for i, t in enumerate(textos)])
    assert motor.pedidos == 1 and motor.falas_geradas == 4 and motor.blocos_refeitos == 0
    pedido = gemini.pedidos[0]
    assert pedido["generation_config"] == {"speech_config": [{"voice": "Kore"}]}
    assert [i["text"] for i in pedido["input"]][-2:] == ["Também." + voz_gemini.PAUSA, "Vamos embora daqui agora."]
    for i, t in enumerate(textos):                                       # cada pedaço ~0,06 s por letra
        assert abs(duracao(tmp_path / f"{i}.wav") - 0.06 * len(t)) < 0.2


def test_bloco_que_nao_corta_direito_e_refeito_fala_por_fala(tmp_path):
    gemini = GeminiFalso(juntar=True)
    motor = voz_gemini.MotorGemini("chave", cliente=gemini, simultaneos=1)
    motor.sintetizar([("Primeira fala.", tmp_path / "1.wav"), ("Segunda fala aqui.", tmp_path / "2.wav")])
    assert motor.blocos_refeitos == 1 and motor.pedidos == 3 and motor.falas_geradas == 2
    assert all((tmp_path / n).is_file() for n in ("1.wav", "2.wav"))


def test_duas_vozes_vao_como_dialogo(tmp_path):
    gemini = GeminiFalso()
    motor = voz_gemini.MotorGemini("chave", cliente=gemini, simultaneos=1)
    motor.sintetizar([("Quem é você?", tmp_path / "1.wav", "Charon"), ("Sou a Ana.", tmp_path / "2.wav", "Kore"),
                      ("Prazer.", tmp_path / "3.wav", "Charon")])
    pedido = gemini.pedidos[0]
    assert pedido["generation_config"]["speech_config"] == [{"speaker": "Pessoa 1", "voice": "Charon"},
                                                            {"speaker": "Pessoa 2", "voice": "Kore"}]
    assert [i["annotations"][0]["speaker"] for i in pedido["input"]] == ["Pessoa 1", "Pessoa 2", "Pessoa 1"]
    with pytest.raises(ErroDublagem, match="desconhecida"):
        motor.sintetizar([("x", tmp_path / "4.wav", "Fulano")])        # só vozes prontas


SRT = "".join(f"{i + 1}\n00:00:{2 * i + 1:02d},000 --> 00:00:{2 * i + 2:02d},500\nFala número {i + 1}.\n\n"
              for i in range(8))


@pytest.mark.skipif(not FFMPEG, reason="sem ffmpeg")
def test_limite_do_dia_guarda_o_que_fez_e_continua_depois(tmp_path):
    from tests.test_dublagem import video_de_teste
    pasta = tmp_path / "Filme (2003)"
    pasta.mkdir()
    video = video_de_teste(pasta / "Filme (2003).mkv", segundos=18)
    legenda = pasta / "Filme (2003).pt-BR.srt"
    legenda.write_text(SRT, encoding="utf-8")
    cache = tmp_path / "progresso"
    gemini = GeminiFalso(falhar_depois=1)                                # 1 pedido e acabou o limite do dia
    motor = voz_gemini.MotorGemini("chave", cliente=gemini, simultaneos=1, bloco=4, esperar=lambda s: None)
    r = dublar_video(video, legenda, motor, FFMPEG, sondar=lambda v: (18.0, ["eng"]), pasta_cache=cache)
    assert r.status == "erro" and "limite de uso do Gemini" in r.detalhe
    assert "4 de 8 falas já prontas e guardadas" in r.detalhe
    gemini.falhar_depois = None                                          # no dia seguinte
    r = dublar_video(video, legenda, motor, FFMPEG, sondar=lambda v: (18.0, ["eng"]), pasta_cache=cache)
    assert r.status == "dublado" and r.retomadas == 4, r.detalhe
    assert len(gemini.pedidos) == 2                                      # só o bloco que faltava
    assert not list(cache.iterdir())                                     # terminou: o progresso foi apagado


def test_identifica_quem_fala_e_distribui_as_vozes(tmp_path):
    falas = [(Fala(f"00:{m:02d}:{s:02d},000 --> 00:{m:02d}:{s + 1:02d},000", t), t) for m, s, t in
             [(0, 5, "Onde você estava?"), (0, 9, "No mercado, ué."), (0, 20, "Mentira."), (16, 1, "Bom dia."),
              (16, 4, "Bom dia, Ana."), (16, 8, "Quem é esse?"), (16, 9, "Ninguém sabe.")]]
    respostas = [
        {"pessoas": [{"rotulo": "Pessoa 1", "genero": "m", "descricao": "homem, voz grave"},
                     {"rotulo": "Ana", "genero": "f", "descricao": "mulher jovem"}],
         "falas": [{"id": 0, "rotulo": "Pessoa 1"}, {"id": 1, "rotulo": "Ana"}, {"id": 2, "rotulo": "Pessoa 1"},
                   {"id": 99, "rotulo": "Pessoa 1"}]},
        {"pessoas": [{"rotulo": "Ana", "genero": "f"}, {"rotulo": "Pessoa 3", "genero": "f", "descricao": "idosa"}],
         "falas": [{"id": 3, "rotulo": "Ana"}, {"id": 4, "rotulo": "Pessoa 1"}, {"id": 5, "rotulo": "?"},
                   {"id": 6, "rotulo": "Pessoa 3"}]}]
    perguntas, trechos = [], []

    class Ouvinte:
        def __init__(self):
            self.interactions = self

        def create(self, model, input):
            perguntas.append(input[0]["text"])
            assert input[1]["type"] == "audio" and input[1]["mime_type"] == "audio/mp3" and model == "gemini-3.8-flash"
            return SimpleNamespace(output_text="```json\n" + json.dumps(respostas[len(perguntas) - 1]) + "\n```")
    progresso = tmp_path / "personagens.json"
    lista = personagens.identificar("filme.mkv", falas, Ouvinte(), "ffmpeg", progresso,
                                    extrair=lambda f, v, ini, dur: trechos.append((ini, dur)) or b"mp3")
    assert trechos == [(0, 900), (900, 900)]                              # 2 trechos de 15 min
    assert '"Ana" (f): mulher jovem' in perguntas[1]                      # o 2º trecho sabe quem já apareceu
    assert "4 [64.0s] Bom dia, Ana." in perguntas[1]                      # 16:04 = 64 s depois de 15:00
    assert [(p.rotulo, p.genero, p.falas) for p in lista] == [("Pessoa 1", "m", [0, 2, 4]), ("Ana", "f", [1, 3]),
                                                              ("Pessoa 3", "f", [6])]
    # guardado: chamar de novo não pede nada
    assert personagens.identificar("filme.mkv", falas, None, "ffmpeg", progresso,
                                   extrair=lambda *a: pytest.fail("não deveria ouvir de novo"))[0].falas == [0, 2, 4]
    mapa = personagens.distribuir_vozes(lista, "Charon")
    assert mapa == {"Pessoa 1": "Charon", "Ana": "Charon", "Pessoa 3": "Charon"}   # menos de 3 falas: voz principal
    personagens_grandes = [personagens.Personagem("Pessoa 1", "m", falas=list(range(10))),
                           personagens.Personagem("Ana", "f", falas=list(range(10, 18))),
                           personagens.Personagem("Pessoa 3", "m", falas=list(range(18, 22))),
                           personagens.Personagem("Robô", "?", falas=list(range(22, 26)))]
    mapa = personagens.distribuir_vozes(personagens_grandes, "Charon")
    assert mapa["Pessoa 1"] == "Charon" and mapa["Ana"] in voz_gemini.VOZES_FEMININAS
    assert mapa["Pessoa 3"] in voz_gemini.VOZES_MASCULINAS and mapa["Pessoa 3"] != "Charon"
    assert len(set(mapa.values())) == 4                                   # ninguém repete enquanto houver voz
    vozes = personagens.vozes_por_fala(personagens_grandes, mapa)
    assert vozes[0] == "Charon" and vozes[10] == mapa["Ana"]
    linhas = personagens.resumo(lista, falas)
    assert linhas[0].startswith('Pessoa 1 (homem, homem, voz grave) · 3 falas · ex.: "Onde você estava?"')


def test_falas_da_legenda_e_a_mesma_lista_da_dublagem(tmp_path):
    legenda = tmp_path / "a.srt"
    legenda.write_text("1\n00:00:01,000 --> 00:00:02,000\n♪ ♪\n\n2\n00:00:03,000 --> 00:00:04,000\n- Oi!\n",
                       encoding="utf-8")
    assert [t for _, t in falas_da_legenda(legenda)] == ["Oi!"]


def test_motor_misto_manda_os_figurantes_para_o_piper(tmp_path):
    from jellyfin_tools.dublagem import MotorMisto
    feitos = {"gemini": [], "faber": []}

    class Falso:
        def __init__(self, nome):
            self.nome, self.pedidos = nome, 0

        def sintetizar(self, pedidos, parar=None, ao_progresso=None):
            self.pedidos += 1
            feitos[self.nome] += [p[0] for p in pedidos]
            assert self.nome == "gemini" or all(len(p) == 2 for p in pedidos)   # o Piper recebe (texto, wav)
    criados = []
    motor = MotorMisto(Falso("gemini"), lambda voz: criados.append(voz) or Falso(voz))
    motor.sintetizar([("A", tmp_path / "1.wav", "Charon"), ("B", tmp_path / "2.wav", "piper:faber"),
                      ("C", tmp_path / "3.wav", ""), ("D", tmp_path / "4.wav", "piper:faber")])
    assert feitos == {"gemini": ["A", "C"], "faber": ["B", "D"]} and criados == ["faber"]
    motor.sintetizar([("E", tmp_path / "5.wav", "piper:faber")])        # o Piper da voz é preparado uma vez só
    assert criados == ["faber"] and motor.pedidos == 1


def test_figurantes_ficam_com_o_piper():
    lista = [personagens.Personagem("Conde", "m", falas=list(range(50))),
             personagens.Personagem("Ellen", "f", falas=list(range(50, 80))),
             personagens.Personagem("Guarda", "m", falas=list(range(80, 85)))]
    mapa = personagens.distribuir_vozes(lista, "Charon", figurante="piper:faber")
    assert mapa["Conde"] == "Charon" and mapa["Ellen"] in voz_gemini.VOZES_FEMININAS
    assert mapa["Guarda"] == "piper:faber"                               # 5 falas (< 20): figurante, grátis


@pytest.mark.skipif(not FFMPEG, reason="sem ffmpeg")
def test_trilha_junta_falas_de_taxas_diferentes(tmp_path):
    from jellyfin_tools.dublagem import montar_trilha, reamostrar_com_ffmpeg
    piper, gemini = tmp_path / "piper.wav", tmp_path / "gemini.wav"
    for wav, taxa in ((piper, 22050), (gemini, 24000)):
        with wave.open(str(wav), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(taxa)
            w.writeframes(b"\x10\x00" * taxa)                            # 1 s
    destino = tmp_path / "trilha.wav"
    montar_trilha([(0.0, 1.0, piper), (2.0, 3.0, gemini)], 4.0, destino, reamostrar=reamostrar_com_ffmpeg(FFMPEG))
    with wave.open(str(destino), "rb") as w:
        assert w.getframerate() == 24000 and abs(w.getnframes() / 24000 - 4.0) < 0.05   # a melhor das taxas
    with pytest.raises(ErroDublagem, match="formatos diferentes"):        # sem reamostrar: erro, como antes
        montar_trilha([(0.0, 1.0, piper), (2.0, 3.0, gemini)], 4.0, destino)


def test_elenco_da_serie_mantem_rotulos_e_vozes_entre_episodios(tmp_path):
    """Episódio 2: o Gemini recebe quem já apareceu na série (mesmos rótulos) e cada um fica com a mesma voz."""
    elenco = tmp_path / "Show.json"
    ep1 = [personagens.Personagem("Ana", "f", "mulher jovem", list(range(30))),
           personagens.Personagem("Pessoa 1", "m", "voz grave", list(range(30, 50)))]
    personagens.salvar_elenco(elenco, ep1, {"Ana": "Aoede", "Pessoa 1": "Orus"})
    guardado = personagens.carregar_elenco(elenco)
    assert guardado["vozes"] == {"Ana": "Aoede", "Pessoa 1": "Orus"}
    perguntas = []

    class Ouvinte:
        interactions = None

        def create(self, model, input):
            perguntas.append(input[0]["text"])
            return SimpleNamespace(output_text=json.dumps({"pessoas": [], "falas": [{"id": 0, "rotulo": "Ana"},
                                                                                     {"id": 1, "rotulo": "Pessoa 1"}]}))
    ouvinte = Ouvinte()
    ouvinte.interactions = ouvinte
    falas = [(Fala("00:00:01,000 --> 00:00:02,000", "Oi."), "Oi."),
             (Fala("00:00:03,000 --> 00:00:04,000", "Olá."), "Olá.")]
    lista = personagens.identificar("ep2.mkv", falas, ouvinte, "ffmpeg", extrair=lambda *a: b"mp3",
                                    elenco=guardado["pessoas"])
    assert '"Ana" (f): mulher jovem' in perguntas[0] and '"Pessoa 1" (m): voz grave' in perguntas[0]
    assert {p.rotulo: p.genero for p in lista} == {"Ana": "f", "Pessoa 1": "m"}       # o gênero vem do elenco
    mapa = personagens.distribuir_vozes(lista, "Charon", fixas=guardado["vozes"])
    assert mapa == {"Ana": "Aoede", "Pessoa 1": "Orus"}                                # as mesmas do episódio 1
    assert personagens.carregar_elenco(tmp_path / "nao_existe.json") == {"pessoas": [], "vozes": {}}
