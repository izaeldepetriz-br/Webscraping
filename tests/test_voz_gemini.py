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
    assert [len(g) for g in voz_gemini.blocos([(f"x{i}", None, "A") for i in range(25)])] == [10, 10, 5]
    longas = [("y" * 300, None, "A")] * 3                               # 700 letras por pedido, no máximo
    assert [len(g) for g in voz_gemini.blocos(longas)] == [2, 1]
    assert voz_gemini.pedidos_estimados(1200) == 120                    # um filme: 120 pedidos em vez de 1.200


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
    # "Sou Agatha, ... Agatha Johnson": a pausa no meio da 1ª frase não pode virar o corte (a 2ª ficaria com 0,3 s
    # para 30 letras, 100 letras por segundo: impossível)
    meio = fala_sintetica(0.9) + silencio(0.6) + fala_sintetica(1.6) + silencio(0.3) + fala_sintetica(0.3)
    assert voz_gemini.separar_por_pausas(meio, TAXA, [40, 30]) is None
    # pausa dramática DENTRO da 1ª fala (0,9 s) mais longa que a pausa ENTRE as falas (0,5 s): o corte fica na que
    # está perto de onde a 1ª fala termina pelas letras, não na mais comprida
    drama = (fala_sintetica(0.5) + silencio(0.9) + fala_sintetica(1.0) + silencio(0.5) + fala_sintetica(1.5)
             + silencio(0.5) + fala_sintetica(0.6))
    cortes = voz_gemini.separar_por_pausas(drama, TAXA, [25, 24, 10])   # "Espelho... espelho meu." etc.
    assert cortes is not None
    esperado = [0.5 + 0.9 + 1.0, 1.5, 0.6]                              # a 1ª inteira, com a pausa dramática
    assert all(abs((b - a) / TAXA - e) < 0.15 for (a, b), e in zip(cortes, esperado))


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
    assert [a.name for a in cache.iterdir()] == ["frases"]           # terminou: o progresso foi apagado (fica o banco de frases curtas)


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
    # menos de 3 falas: a voz principal, se for do mesmo gênero (antes a Ana e a idosa saíam com voz de homem)
    assert mapa == {"Pessoa 1": "Charon", "Ana": "Kore", "Pessoa 3": "Kore"}
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


def test_gemini_que_nao_responde_nao_prende_o_parar(tmp_path):
    """Um pedido que o Google não devolve: o Parar responde em menos de 1 s (antes esperava para sempre)."""
    import threading
    import time
    liberar = threading.Event()

    class Mudo(GeminiFalso):
        def create(self, **k):
            liberar.wait(10)                                                # o Google não responde
            return super().create(**k)
    motor = voz_gemini.MotorGemini("chave", cliente=Mudo(), simultaneos=1)
    pedido = time.monotonic()
    with pytest.raises(ErroDublagem, match="Parar"):
        motor.sintetizar([("Olá.", tmp_path / "1.wav")], parar=lambda: time.monotonic() - pedido > 0.3)
    assert time.monotonic() - pedido < 2
    liberar.set()


def test_cliente_do_gemini_tem_tempo_limite(monkeypatch):
    import sys
    from types import ModuleType
    criados = []
    genai = ModuleType("google.genai")
    genai.Client = lambda **k: criados.append(k) or object()
    google = ModuleType("google")
    google.genai = genai
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.genai", genai)
    voz_gemini._cliente("chave")
    assert criados[0]["http_options"] == {"timeout": voz_gemini.TEMPO_LIMITE * 1000}


def test_tom_de_cada_fala_vai_no_pedido_da_voz(tmp_path):
    gemini = GeminiFalso()
    motor = voz_gemini.MotorGemini("chave", cliente=gemini, simultaneos=1)
    motor.sintetizar([("Saia daqui!", tmp_path / "1.wav", "", "com raiva, gritando"),
                      ("Tá bom.", tmp_path / "2.wav")])
    estilos = [i["annotations"][0]["style"] for i in gemini.pedidos[0]["input"]]
    assert estilos[0].startswith(voz_gemini.ESTILO) and "Nesta fala: com raiva, gritando." in estilos[0]
    assert voz_gemini.DIRECAO in estilos[0]
    assert estilos[1] == voz_gemini.ESTILO                                # sem tom: só o estilo geral
    assert duracao(tmp_path / "1.wav") > 0 and duracao(tmp_path / "2.wav") > 0


def test_ouvir_o_tom_so_do_trecho_e_guardar(tmp_path):
    """O Gemini ouve só em volta das falas pedidas (a amostra de 1 min manda ~1 min) e o que ouviu fica guardado:
    o filme inteiro, depois, não paga de novo; a fala com outro texto é ouvida de novo."""
    from jellyfin_tools import tom
    falas = [(Fala(f"00:{m:02d}:{s:02d},000 --> 00:{m:02d}:{s + 2:02d},000", t), t) for m, s, t in
             [(0, 5, "Saia daqui!"), (0, 9, "Tá bom."), (20, 1, "Bom dia.")]]
    perguntas, trechos = [], []

    class Ouvinte:
        def __init__(self):
            self.interactions = self

        def create(self, model, input):
            perguntas.append(input[0]["text"])
            return SimpleNamespace(output_text=json.dumps({"falas": [
                {"id": 0, "tom": '"com raiva, gritando".', "genero": "F", "quem": "mãe brava",
                 "idade": "adulta"}, {"id": 1, "tom": "cansado"}, {"id": 7, "tom": "x"}],
                "cena": "Uma mãe briga com o filho."}))
    guardado = tmp_path / "tons.json"
    extrair = lambda f, v, ini, dur: trechos.append((ini, dur)) or b"mp3"     # noqa: E731
    achados = tom.ouvir_falas("f.mkv", falas, [0, 1], Ouvinte(), "ffmpeg", guardado, extrair=extrair)
    assert {k: (o.tom, o.genero) for k, o in achados.items()} == {0: ("com raiva, gritando", "f"), 1: ("cansado", "?")}
    assert achados[0].idade == "adulto"
    assert achados[0].nota() == ("Cena: Uma mãe briga com o filho. Quem fala: mãe brava. Nesta fala: com raiva, "
                                 "gritando.")
    assert trechos == [(4.0, 8.0)] and "1 [5.0s] Tá bom." in perguntas[0]      # 0:04 a 0:12, não 15 minutos
    assert tom.ouvir_falas("f.mkv", falas, [0, 1], None, "ffmpeg", guardado) == achados  # guardado: não pede
    falas[1] = (falas[1][0], "Está bem.")                                       # a legenda mudou
    tom.ouvir_falas("f.mkv", falas, [0, 1], Ouvinte(), "ffmpeg", guardado, extrair=extrair)
    assert len(perguntas) == 2 and "Saia daqui" not in perguntas[1]             # só a fala que mudou
    assert 0.1 < tom.custo_estimado(3600) < 0.2                                 # ~US$ 0,12 por hora


def test_escuta_que_falha_no_meio_fica_com_o_que_ouviu(tmp_path):
    from jellyfin_tools import tom
    falas = [(Fala(f"00:{m:02d}:00,000 --> 00:{m:02d}:02,000", f"Fala {m}."), f"Fala {m}.") for m in (0, 20)]

    class Ouvinte:
        def __init__(self):
            self.interactions, self.vezes = self, 0

        def create(self, model, input):
            self.vezes += 1
            if self.vezes > 1:
                raise type("ClientError", (Exception,), {"code": 403})("sem crédito")
            return SimpleNamespace(output_text='{"falas": [{"id": 0, "tom": "animado"}]}')
    avisos = []
    achados = tom.ouvir_falas("f.mkv", falas, [0, 1], Ouvinte(), "ffmpeg", tmp_path / "t.json",
                              extrair=lambda *a: b"mp3", avisar=avisos.append)
    assert {k: o.tom for k, o in achados.items()} == {0: "animado"} and "parte das falas" in avisos[0]
    sem_credito = Ouvinte()
    sem_credito.vezes = 1                                                    # já no 1º pedido: sem crédito
    with pytest.raises(ErroDublagem):                                       # nada ouvido: o erro sobe
        tom.ouvir_falas("f.mkv", falas, [1], sem_credito, "ffmpeg", tmp_path / "t.json", extrair=lambda *a: b"mp3")


def test_identificar_so_as_falas_do_teste(tmp_path):
    """O teste de 1 minuto manda só o áudio em volta das falas dele, e o pedaço não conta como trecho já ouvido."""
    falas = [(Fala(f"00:{m:02d}:{s:02d},000 --> 00:{m:02d}:{s + 2:02d},000", t), t) for m, s, t in
             [(0, 5, "Oi."), (12, 1, "Espelho, espelho meu."), (12, 6, "Olá, eu sou Elena."), (12, 9, "Entre.")]]
    trechos = []

    class Ouvinte:
        def __init__(self):
            self.interactions = self

        def create(self, model, input):
            return SimpleNamespace(output_text=json.dumps({
                "pessoas": [{"rotulo": "Pessoa 1", "genero": "f"}, {"rotulo": "Elena", "genero": "f"}],
                "falas": [{"id": 1, "rotulo": "Pessoa 1"}, {"id": 2, "rotulo": "Elena"}, {"id": 3, "rotulo": "Pessoa 1"},
                          {"id": 0, "rotulo": "Pessoa 1"}]}))
    arquivo = tmp_path / "teste-personagens.json"
    lista = personagens.identificar("f.mkv", falas, Ouvinte(), "ffmpeg", arquivo, ids=[1, 2, 3],
                                    extrair=lambda f, v, ini, dur: trechos.append((ini, dur)) or b"mp3")
    assert trechos == [(720.0, 12.0)]                                       # 12:00 a 12:12, não 15 minutos
    assert {p.rotulo: p.falas for p in lista} == {"Pessoa 1": [1, 3], "Elena": [2]}   # a fala 0 não era do teste
    assert json.loads(arquivo.read_text(encoding="utf-8"))["trechos"] == []
    mapa = personagens.distribuir_vozes(lista, "Charon")                    # duas mulheres, voz principal de homem
    assert set(mapa.values()) <= set(voz_gemini.VOZES_FEMININAS) and mapa["Pessoa 1"] != mapa["Elena"] or \
        len(lista[1].falas) < personagens.MINIMO_FALAS


def test_metades_vao_em_paralelo_e_a_barra_anda_por_fala(tmp_path):
    """O corte que não bate não prende o bloco numa fila: as metades voltam para a fila e são pedidas junto com os
    outros pedidos; a barra anda a cada fala pronta (antes ficava em 0% até o bloco inteiro terminar)."""
    import threading
    import time as relogio
    ao_mesmo_tempo, agora = [], [0]
    trava = threading.Lock()

    class Lento(GeminiFalso):
        def create(self, **k):
            with trava:
                agora[0] += 1
                ao_mesmo_tempo.append(agora[0])
            relogio.sleep(0.05)
            try:
                return super().create(**k)
            finally:
                with trava:
                    agora[0] -= 1
    gemini, avisos, barra = Lento(juntar=True), [], []
    motor = voz_gemini.MotorGemini("chave", cliente=gemini, simultaneos=4, avisar=avisos.append)
    motor.sintetizar([(f"Fala número {i} aqui.", tmp_path / f"{i}.wav") for i in range(4)], ao_progresso=barra.append)
    assert motor.falas_geradas == 4 and len(gemini.pedidos) == 7         # 1 de 4, 2 de 2, 4 de 1
    assert max(ao_mesmo_tempo) >= 2                                       # as metades foram juntas
    assert len(avisos) == 4 and "duas metades" in avisos[0]
    assert avisos[-1].startswith("Gemini: 3 bloco(s) pedido(s) de novo") and "custo a mais estimado: US$" in avisos[-1]
    assert motor.gasto_refeito > 0                                        # o áudio jogado fora também foi pago
    assert barra[-1] == 1.0 and len(set(barra)) >= 3                      # 0,25... 0,5... 1,0


def test_corte_de_um_dialogo_longo_com_pausas_dramaticas():
    """10 falas (como um bloco de diálogo): pausas de 0,45 s entre as falas e, em 3 delas, uma pausa dramática de
    0,8 s no meio. O corte acha as 9 pausas certas (antes pegava as dramáticas e o bloco era pedido de novo)."""
    letras = [18, 30, 12, 25, 40, 15, 22, 35, 10, 28]
    dramaticas = {1, 4, 7}
    audio, esperado = array("h"), []
    for i, n in enumerate(letras):
        dur = 0.065 * n
        if i in dramaticas:
            audio += fala_sintetica(dur / 2) + silencio(0.8) + fala_sintetica(dur / 2)
            esperado.append(dur + 0.8)
        else:
            audio += fala_sintetica(dur)
            esperado.append(dur)
        if i < len(letras) - 1:
            audio += silencio(0.45)
    cortes = voz_gemini.separar_por_pausas(audio, TAXA, letras)
    assert cortes is not None
    assert all(abs((b - a) / TAXA - e) < 0.15 for (a, b), e in zip(cortes, esperado))


def test_crianca_e_idoso_ganham_voz_da_idade():
    """As vozes prontas são de adultos: a criança fica com a que soa mais jovem do gênero dela, o idoso com uma mais
    calma, e a voz principal (adulta) não vai para eles. O tom também diz a idade de cada fala."""
    from jellyfin_tools import dublagem
    assert [personagens.idade_de(t) for t in ("criança", "Crianca", "idosa", "jovem", "adulto", "?")] == \
        ["crianca", "crianca", "idoso", "jovem", "adulto", ""]
    lista = [personagens.Personagem("Avó", "f", "senhora idosa", list(range(10)), "idoso"),
             personagens.Personagem("Pai", "m", "", list(range(10, 18)), "adulto"),
             personagens.Personagem("Menina", "f", "8 anos", list(range(18, 24)), "crianca"),
             personagens.Personagem("Menino", "m", "", [24], "crianca")]
    mapa = personagens.distribuir_vozes(lista, "Charon")
    assert mapa == {"Avó": "Callirrhoe", "Pai": "Charon", "Menina": "Leda", "Menino": "Puck"}
    por = {"m": "Charon", "f": "Kore", "f:crianca": "Leda"}
    assert dublagem.vozes_com_genero({}, {0: "f:crianca", 1: "f:idoso", 2: "m"}, por, [0, 1, 2]) == \
        {0: "Leda", 1: "Kore", 2: "Charon"}                                  # idade sem voz própria: a do gênero


def test_identificar_guarda_a_idade(tmp_path):
    falas = [(Fala("00:00:01,000 --> 00:00:02,000", "Vovó!"), "Vovó!")]

    class Ouvinte:
        def __init__(self):
            self.interactions = self

        def create(self, model, input):
            assert '"idade"' in input[0]["text"]
            return SimpleNamespace(output_text=json.dumps({
                "pessoas": [{"rotulo": "Lia", "genero": "f", "idade": "criança"}], "falas": [{"id": 0, "rotulo": "Lia"}]}))
    lista = personagens.identificar("f.mkv", falas, Ouvinte(), "ffmpeg", tmp_path / "p.json",
                                    extrair=lambda *a: b"mp3")
    assert [(p.rotulo, p.idade) for p in lista] == [("Lia", "crianca")]
    elenco = tmp_path / "elenco.json"
    personagens.salvar_elenco(elenco, lista, {"Lia": "Leda"})
    assert personagens.carregar_elenco(elenco)["pessoas"][0]["idade"] == "crianca"


def test_a_escuta_anota_os_sons_sem_fala(tmp_path):
    """Bocejo, risada...: a mesma escuta do tom anota os sons sem palavras (em segundos do vídeo). Falas já ouvidas
    numa versão anterior (sem os sons): só os sons são perguntados (o tom e as vozes já geradas não mudam)."""
    from jellyfin_tools import tom
    falas = [(Fala("00:00:58,000 --> 00:01:02,600", "Você deve estar cansada?"), "Você deve estar cansada?")]
    perguntas = []

    class Ouvinte:
        def __init__(self):
            self.interactions = self

        def create(self, model, input):
            perguntas.append(input[0]["text"])
            return SimpleNamespace(output_text=json.dumps({
                "sons": [{"inicio": 4.4, "fim": 6.9, "tipo": "bocejo"}, {"inicio": 1, "fim": 30, "tipo": "música"}],
                "cena": "x", "falas": [{"id": 0, "tom": "cansada", "genero": "f"}]}))
    guardado = tmp_path / "tons.json"
    tom.ouvir_falas("f.mkv", falas, [0], Ouvinte(), "ffmpeg", guardado, extrair=lambda *a: b"mp3")
    sons = json.loads((tmp_path / "sons.json").read_text(encoding="utf-8"))
    assert sons["sons"] == [[61.4, 63.9, "bocejo"]]                       # 57 s (o pedaço) + 4,4; os 29 s: engano
    assert '"sons"' in perguntas[0] and len(perguntas) == 1
    (tmp_path / "sons.json").unlink()                                     # como se fosse de uma versão anterior
    tom.ouvir_falas("f.mkv", falas, [0], Ouvinte(), "ffmpeg", guardado, extrair=lambda *a: b"mp3")
    assert len(perguntas) == 2 and "Liste os sons de voz SEM palavras" in perguntas[1]   # só os sons
    assert json.loads((tmp_path / "sons.json").read_text(encoding="utf-8"))["sons"] == [[61.4, 63.9, "bocejo"]]
    tom.ouvir_falas("f.mkv", falas, [0], Ouvinte(), "ffmpeg", guardado, extrair=lambda *a: b"mp3")
    assert len(perguntas) == 2                                            # tudo guardado: não pergunta de novo
