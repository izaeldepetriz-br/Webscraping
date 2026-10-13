"""Comandos para robôs (Maestro.exe --organizar, --conferir-espelhos...): sem janela, com código de saída e log."""
import json
import logging
import os
import subprocess
import sys
import time
from types import SimpleNamespace
from pathlib import Path

import pytest

from jellyfin_tools.traducao import Tradutor
from jellyfin_tools.tv_ao_vivo import Canal, carregar_historico, salvar_canais
from videoscraper import automacao, config

from test_traducao import SRT, ClienteFalso

RAIZ = Path(__file__).resolve().parent.parent


@pytest.fixture
def casa(tmp_path, monkeypatch):
    """Uma pasta de configurações só do teste (o config.json de verdade não é tocado) e sem chaves no ambiente."""
    monkeypatch.setattr(config, "ARQUIVO", tmp_path / "config" / "config.json")
    for variavel in automacao.VARIAVEIS.values():
        monkeypatch.delenv(variavel, raising=False)

    def configurar(**jellyfin):
        tudo = {"jellyfin": jellyfin}
        tudo.update(jellyfin.pop("_resto", {}))
        config.salvar(tudo)
    configurar.pasta = tmp_path
    return configurar


def resultado(tmp_path) -> dict:
    return json.loads((tmp_path / "config" / "rpa" / "ultimo.json").read_text(encoding="utf-8"))


def baixado(caminho: Path) -> Path:
    """Um vídeo que terminou de baixar (parado há 10 minutos)."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_bytes(b"\0" * 2_000_000)
    antigo = time.time() - 600
    os.utime(caminho, (antigo, antigo))
    return caminho


def test_organizar_simula_e_depois_move_filmes_e_series(casa, tmp_path):
    origem = tmp_path / "Downloads"
    baixado(origem / "Matrix.1999.1080p.mkv")
    baixado(origem / "Dark.S01E01.mkv")
    casa(origem=str(origem), destino_filmes=str(tmp_path / "Filmes"), destino_series=str(tmp_path / "Series"),
         legendas=False, imagens_tmdb=False, gerar_nfo=False)

    assert automacao.main(["--organizar", "--simular"]) == automacao.OK
    assert "2 arquivo(s) seriam movidos" in resultado(tmp_path)["comandos"][0]["resumo"]
    assert (origem / "Matrix.1999.1080p.mkv").exists()                     # simular não mexe em nada

    assert automacao.main(["--organizar"]) == automacao.OK
    assert (tmp_path / "Filmes" / "Matrix (1999)" / "Matrix (1999).mkv").exists()
    assert list((tmp_path / "Series").rglob("Dark S01E01*.mkv"))
    r = resultado(tmp_path)
    assert r["codigo"] == 0 and r["comandos"][0]["resumo"].startswith("2 movido(s)")
    log = Path(r["log"])                                                    # o log desta execução, para o robô ler
    assert log.parent == tmp_path / "config" / "logs" and "RPA-organizar" in log.name
    assert "Matrix (1999)" in log.read_text(encoding="utf-8")


def test_falta_configuracao_ou_comando_errado_da_codigo_2(casa, tmp_path):
    casa()
    assert automacao.main(["--organizar"]) == automacao.FALTA_CONFIGURACAO
    assert "pasta de origem" in resultado(tmp_path)["comandos"][0]["resumo"]
    assert automacao.main(["--conferir-canais"]) == automacao.FALTA_CONFIGURACAO
    assert automacao.main(["--organizar", "--opcao-que-nao-existe"]) == automacao.FALTA_CONFIGURACAO
    assert "não entendido" in resultado(tmp_path)["resumo"]
    destino = tmp_path / "meu-robo" / "saida.json"                          # o robô escolhe onde ler o resumo
    assert automacao.main(["--enviar-tv", "--resultado", str(destino)]) == automacao.FALTA_CONFIGURACAO
    assert "VAZIA" in json.loads(destino.read_text(encoding="utf-8"))["comandos"][0]["resumo"].upper()
    assert not automacao.foi_pedido(["--classica"]) and automacao.foi_pedido(["--conferir-espelhos"])


def test_conferir_espelhos_quebrado_da_codigo_1_e_avisa(casa, tmp_path, api_falsa):
    api_falsa.rotas["/ok.mp4"] = lambda q: (206, b"x", {"Content-Type": "video/mp4", "Accept-Ranges": "bytes"})
    api_falsa.rotas["/sumiu.mp4"] = lambda q: (404, b"", {})
    api_falsa.rotas["/discord"] = lambda q: (204, b"")
    filmes = tmp_path / "Filmes"
    for nome, url in (("Bom (2000)", "/ok.mp4"), ("Quebrado (2001)", "/sumiu.mp4")):
        (filmes / nome).mkdir(parents=True)
        (filmes / nome / f"{nome}.strm").write_text(api_falsa.base + url + "\n", encoding="utf-8")
    casa(destino_filmes=str(filmes), discord_webhook=api_falsa.base + "/discord")
    assert automacao.main(["--conferir-espelhos"]) == automacao.PROBLEMA
    comando = resultado(tmp_path)["comandos"][0]
    assert comando["resumo"] == "2 espelho(s) conferido(s): 1 funcionando, 1 quebrado(s)."
    assert comando["detalhes"][0].startswith("Quebrado (2001)/Quebrado (2001).strm")
    assert [p for p in api_falsa.pedidos if p["caminho"] == "/discord"]        # avisou no Discord
    assert (filmes / "Quebrado (2001)" / "Quebrado (2001).strm").exists()     # remover_quebrados desligado


def test_conferir_canais_grava_o_historico(casa, tmp_path, api_falsa):
    api_falsa.rotas["/ok.m3u8"] = lambda q: (200, b"#EXTM3U\n", {"Content-Type": "application/x-mpegURL"})
    casa()
    canais = [Canal("No ar", api_falsa.base + "/ok.m3u8"), Canal("Sumiu", api_falsa.base + "/sumiu.m3u8")]
    salvar_canais(tmp_path / "config" / "canais.json", canais)
    assert automacao.main(["--conferir-canais"]) == automacao.PROBLEMA
    comando = resultado(tmp_path)["comandos"][0]
    assert comando["resumo"] == "2 canal(is) conferido(s): 1 no ar, 1 fora do ar."
    assert comando["detalhes"][0].startswith("Sumiu: ")
    historico = carregar_historico(tmp_path / "config" / "canais_historico.json")
    assert historico == {canais[0].url: [True], canais[1].url: [False]}     # a coluna "Últimas" da janela


def test_enviar_tv_sem_jellyfin_so_salva_a_lista(casa, tmp_path):
    pasta_tv = tmp_path / "TV"
    casa(_resto={"tv": {"pasta": str(pasta_tv)}})
    salvar_canais(tmp_path / "config" / "canais.json", [Canal("Rádio", "http://exemplo.org/radio.mp3")])
    assert automacao.main(["--enviar-tv"]) == automacao.PROBLEMA
    assert "http://exemplo.org/radio.mp3" in (pasta_tv / "canais.m3u").read_text(encoding="utf-8")
    assert "não foi avisado" in resultado(tmp_path)["comandos"][0]["resumo"]


def test_traduzir_legendas_respeita_o_limite_de_custo(casa, tmp_path, monkeypatch):
    filmes = tmp_path / "Filmes"
    for nome in ("A (2001)", "B (2002)"):
        baixado(filmes / nome / f"{nome}.mkv")
        (filmes / nome / f"{nome}.en.srt").write_text(SRT, encoding="utf-8")
    cliente = ClienteFalso()
    monkeypatch.setattr(automacao, "Tradutor", lambda **k: Tradutor(cliente=cliente, **k))
    casa(destino_filmes=str(filmes))
    assert automacao.main(["--traduzir-legendas"]) == automacao.FALTA_CONFIGURACAO     # sem chave: nem tenta
    assert "ANTHROPIC_API_KEY" in resultado(tmp_path)["comandos"][0]["resumo"]
    assert not cliente.pedidos

    casa(destino_filmes=str(filmes), chave_claude="chave-do-teste")
    assert automacao.main(["--traduzir-legendas", "--limite-dolares", "0.0000001"]) == automacao.FALTA_CONFIGURACAO
    assert "passa do limite" in resultado(tmp_path)["comandos"][0]["resumo"] and not cliente.pedidos

    assert automacao.main(["--traduzir-legendas"]) == automacao.OK
    assert (filmes / "A (2001)" / "A (2001).pt-BR.srt").read_text(encoding="utf-8").count("PT: ") == 3
    assert (filmes / "B (2002)" / "B (2002).pt-BR.srt").exists()
    assert {p["model"] for p in cliente.pedidos} == {"claude-sonnet-4-6"}     # o modelo padrão
    assert resultado(tmp_path)["comandos"][0]["resumo"].startswith("2 de 2 legenda(s) traduzida(s), 0 erro(s)")


def test_juntos_rodam_na_ordem_e_o_codigo_e_o_pior(casa, tmp_path, api_falsa):
    api_falsa.rotas["/ok.m3u8"] = lambda q: (200, b"#EXTM3U\n", {"Content-Type": "application/x-mpegURL"})
    casa()
    salvar_canais(tmp_path / "config" / "canais.json", [Canal("No ar", api_falsa.base + "/ok.m3u8")])
    assert automacao.main(["--conferir-canais", "--organizar"]) == automacao.FALTA_CONFIGURACAO
    assert [(c["comando"], c["codigo"]) for c in resultado(tmp_path)["comandos"]] == [
        ("--organizar", 2), ("--conferir-canais", 0)]


def test_pelo_iniciar_py_sem_abrir_a_janela(tmp_path):
    """O mesmo caminho do Maestro.exe: iniciar.py com um comando de robô devolve o código e não abre janela."""
    ambiente = {**os.environ, "HOME": str(tmp_path), "USERPROFILE": str(tmp_path), "DISPLAY": ""}
    for variavel in automacao.VARIAVEIS.values():
        ambiente.pop(variavel, None)
    feito = subprocess.run([sys.executable, str(RAIZ / "iniciar.py"), "--conferir-canais"], env=ambiente,
                           capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
    assert feito.returncode == automacao.FALTA_CONFIGURACAO, feito.stderr
    assert "--conferir-canais: código 2" in feito.stdout
    assert json.loads((tmp_path / ".videoscraper" / "rpa" / "ultimo.json").read_text(encoding="utf-8"))["codigo"] == 2


def test_legendar_audio_no_maximo_n_videos_por_vez(casa, tmp_path, monkeypatch):
    from jellyfin_tools import transcricao
    from test_transcricao import WhisperFalso
    filmes = tmp_path / "Filmes"
    for nome in ("A (2001)", "B (2002)", "C (2003)"):
        baixado(filmes / nome / f"{nome}.mkv")
    monkeypatch.setattr(automacao, "videos_sem_legenda",
                        lambda *p, **k: transcricao.videos_sem_legenda(*p, sondar_arquivo=lambda v: (600.0, set()), **k))
    monkeypatch.setattr(automacao, "Transcritor", lambda **k: transcricao.Transcritor(motor=WhisperFalso(), **k))
    monkeypatch.setattr(automacao, "Tradutor", lambda **k: Tradutor(cliente=ClienteFalso(), **k))
    casa(destino_filmes=str(filmes), chave_claude="chave-do-teste")
    assert automacao.main(["--legendar-audio", "--limite-videos", "2"]) == automacao.OK
    resumo = resultado(tmp_path)["comandos"][0]["resumo"]
    assert resumo.startswith("2 de 2 legenda(s) em pt-BR criada(s), 0 erro(s), 1 vídeo(s) para a próxima vez")
    assert (filmes / "A (2001)" / "A (2001).pt-BR.srt").exists() and (filmes / "B (2002)" / "B (2002).en.srt").exists()
    assert not (filmes / "C (2003)" / "C (2003).pt-BR.srt").exists()
    assert automacao.main(["--legendar-audio"]) == automacao.OK                  # a próxima execução pega o C
    assert (filmes / "C (2003)" / "C (2003).pt-BR.srt").exists()
    assert automacao.main(["--legendar-audio"]) == automacao.OK
    assert resultado(tmp_path)["comandos"][0]["resumo"] == "Nenhum vídeo sem legenda."


def test_dublar_pelo_robo(casa, tmp_path, monkeypatch):
    from jellyfin_tools import dublagem
    from test_dublagem import FFMPEG, SRT, VozFalsa, faixas, video_de_teste
    if not FFMPEG:
        pytest.skip("sem ffmpeg")
    filmes = tmp_path / "Filmes"
    (filmes / "A (2001)").mkdir(parents=True)
    video_de_teste(filmes / "A (2001)" / "A (2001).mkv")
    (filmes / "A (2001)" / "A (2001).pt-BR.srt").write_text(SRT, encoding="utf-8")
    monkeypatch.setattr(automacao, "preparar_piper", lambda pasta, **k: Path("piper"))
    monkeypatch.setattr(automacao, "preparar_voz", lambda voz, pasta, **k: Path("v.onnx"))
    monkeypatch.setattr(automacao, "MotorPiper", lambda exe, modelo: VozFalsa())
    monkeypatch.setattr(automacao, "videos_para_dublar",
                        lambda *p, **k: dublagem.videos_para_dublar(*p, **{**k, "sondar": lambda v: (6.0, ["eng"])}))
    casa()
    assert automacao.main(["--dublar"]) == automacao.FALTA_CONFIGURACAO
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    casa(destino_filmes=str(filmes), motor_voz="Gemini (premium, Google AI Studio)")    # voz premium sem chave
    assert automacao.main(["--dublar"]) == automacao.FALTA_CONFIGURACAO
    assert "aistudio.google.com" in resultado(tmp_path)["comandos"][0]["resumo"]
    # fase de teste (padrão): uma prévia fora da biblioteca; o original fica igual até aprovar
    casa(destino_filmes=str(filmes))
    video = filmes / "A (2001)" / "A (2001).mkv"
    antes = video.read_bytes()
    assert automacao.main(["--dublar"]) == automacao.OK
    assert "1 prévia(s) para ouvir e aprovar" in resultado(tmp_path)["comandos"][0]["resumo"]
    assert video.read_bytes() == antes and len(automacao.previas_pendentes()) == 1
    previa = Path(automacao.previas_pendentes()[0]["previa"])
    assert previa.is_file() and str(previa).startswith(str(automacao.pasta_previas()))
    assert automacao.main(["--dublar"]) == automacao.OK                   # esperando aprovação: não dubla de novo
    assert resultado(tmp_path)["comandos"][0]["resumo"] == "Nenhum filme ou episódio para dublar."
    automacao.aprovar_previa_de(video)                                    # aprovada: entra no original
    assert not previa.exists() and automacao.previas_pendentes() == []
    assert len([l for l in faixas(video) if "Audio" in l]) == 2
    # sem a fase de teste: direto no original
    video_de_teste(video)
    casa(destino_filmes=str(filmes), dublagem_previa=False)
    assert automacao.main(["--dublar"]) == automacao.OK
    assert resultado(tmp_path)["comandos"][0]["resumo"] == "1 de 1 vídeo(s) dublado(s), 0 erro(s)."
    # padrão: a dublagem é uma faixa do próprio arquivo (sem 'Nome - Dublado IA.mkv' ao lado)
    assert not (filmes / "A (2001)" / "A (2001) - Dublado IA.mkv").exists()
    audios = [l for l in faixas(filmes / "A (2001)" / "A (2001).mkv") if "Audio" in l]
    assert len(audios) == 2 and "(por)" in audios[0]


def test_robo_soma_no_resumo_do_dia(casa, tmp_path, api_falsa):
    from jellyfin_tools.resumo_diario import ResumoDiario
    api_falsa.rotas["/ok.m3u8"] = lambda q: (200, b"#EXTM3U\n", {"Content-Type": "application/x-mpegURL"})
    casa()
    salvar_canais(tmp_path / "config" / "canais.json", [Canal("Sumiu", api_falsa.base + "/sumiu.m3u8")])
    automacao.main(["--conferir-canais"])
    assert ResumoDiario(tmp_path / "config" / "resumo_do_dia.json").para_enviar(0) == {"canais_fora": 1}


def test_traducao_economica_pelo_robo(casa, tmp_path, monkeypatch):
    from test_traducao_lote import LoteFalso
    filmes = tmp_path / "Filmes"
    baixado(filmes / "A (2001)" / "A (2001).mkv")
    (filmes / "A (2001)" / "A (2001).en.srt").write_text(SRT, encoding="utf-8")
    cliente = ClienteFalso()
    cliente.batches = LoteFalso(cliente)
    monkeypatch.setattr(automacao, "Tradutor", lambda **k: Tradutor(cliente=cliente, **k))
    casa(destino_filmes=str(filmes), chave_claude="chave")
    assert automacao.main(["--traduzir-legendas", "--economico"]) == automacao.OK
    assert resultado(tmp_path)["comandos"][0]["resumo"].startswith("Lote msgbatch_1 enviado: 1 legenda(s)")
    assert automacao.main(["--traduzir-legendas", "--economico"]) == automacao.OK      # ainda processando
    assert "ainda processando" in resultado(tmp_path)["comandos"][0]["resumo"]
    cliente.batches.terminado = True
    assert automacao.main(["--traduzir-legendas", "--economico"]) == automacao.OK
    assert (filmes / "A (2001)" / "A (2001).pt-BR.srt").exists()
    assert "1 legenda(s) do lote gravada(s)" in resultado(tmp_path)["comandos"][0]["resumo"]


def test_dublar_pelo_robo_com_voz_por_personagem(casa, tmp_path, monkeypatch):
    """Sem janela: o robô ouve, distribui as vozes sozinho (sem a tabela) e guarda o progresso."""
    from jellyfin_tools import dublagem, personagens, voz_gemini
    from test_dublagem import FFMPEG, SRT_APERTADA, faixas, gravar_tom, video_de_teste
    if not FFMPEG:
        pytest.skip("sem ffmpeg")
    filmes = tmp_path / "Filmes"
    (filmes / "A (2001)").mkdir(parents=True)
    video_de_teste(filmes / "A (2001)" / "A (2001).mkv")
    (filmes / "A (2001)" / "A (2001).pt-BR.srt").write_text(SRT_APERTADA, encoding="utf-8")
    monkeypatch.setattr(automacao, "videos_para_dublar",
                        lambda *p, **k: dublagem.videos_para_dublar(*p, **{**k, "sondar": lambda v: (6.0, ["eng"])}))
    monkeypatch.setattr(automacao, "ouvir_personagens", lambda o, video, falas, **k: [
        personagens.Personagem("Pessoa 1", "m", falas=[0, 2]), personagens.Personagem("Ana", "f", falas=[1])])
    vozes = {}

    class Voz:
        def sintetizar(self, pedidos, parar=None, ao_progresso=None):
            for texto, wav, *voz in pedidos:
                vozes[texto] = voz[0] if voz else None
                gravar_tom(Path(wav), 0.05 * len(texto))
    monkeypatch.setattr(voz_gemini, "MotorGemini", lambda chave, voz, **k: Voz())
    casa(destino_filmes=str(filmes), motor_voz="Gemini (premium, Google AI Studio)", chave_gemini="AIza",
         voz_gemini="Kore", voz_por_personagem=True, encurtar_falas=False, dublagem_previa=False)
    assert automacao.main(["--dublar"]) == automacao.OK
    # quem fala menos de 3 falas fica com a voz principal (Kore) se for do mesmo gênero; o homem, com uma masculina
    assert sorted(vozes.values()) == ["Charon", "Charon", "Kore"] and len(vozes) == 3
    assert len([l for l in faixas(filmes / "A (2001)" / "A (2001).mkv") if "Audio" in l]) == 2
    assert [a.name for a in (tmp_path / "config" / "dublagem").iterdir()] == ["frases"]   # terminou: o progresso
    # foi apagado; fica só o banco das frases curtas (para os próximos filmes)


def test_robo_dublagem_mista_figurantes_no_piper(casa, tmp_path, monkeypatch):
    from jellyfin_tools import dublagem, personagens, voz_gemini
    from test_dublagem import FFMPEG, SRT_APERTADA, gravar_tom, video_de_teste
    if not FFMPEG:
        pytest.skip("sem ffmpeg")
    filmes = tmp_path / "Filmes"
    (filmes / "A (2001)").mkdir(parents=True)
    video_de_teste(filmes / "A (2001)" / "A (2001).mkv")
    (filmes / "A (2001)" / "A (2001).pt-BR.srt").write_text(SRT_APERTADA, encoding="utf-8")
    monkeypatch.setattr(automacao, "videos_para_dublar",
                        lambda *p, **k: dublagem.videos_para_dublar(*p, **{**k, "sondar": lambda v: (6.0, ["eng"])}))
    monkeypatch.setattr(personagens, "FIGURANTE", 2)                     # a fala do "Guarda" (1 fala) é figurante
    monkeypatch.setattr(automacao, "ouvir_personagens", lambda o, video, falas, **k: [
        personagens.Personagem("Conde", "m", falas=[0, 2]), personagens.Personagem("Guarda", "m", falas=[1])])
    quem = {}

    class Voz:
        def __init__(self, nome):
            self.nome = nome

        def sintetizar(self, pedidos, parar=None, ao_progresso=None):
            for texto, wav, *_ in pedidos:
                quem[texto] = self.nome
                gravar_tom(Path(wav), 0.05 * len(texto))
    monkeypatch.setattr(voz_gemini, "MotorGemini", lambda chave, voz, **k: Voz("gemini"))
    monkeypatch.setattr(automacao, "motor_piper", lambda o, voz="", **k: Voz(f"piper {voz}"))
    monkeypatch.setattr(personagens, "distribuir_vozes",
                        lambda lista, principal, figurante=None, limite=2, **k: {"Conde": "Charon", "Guarda": figurante})
    casa(destino_filmes=str(filmes), motor_voz="Gemini (premium, Google AI Studio)", chave_gemini="AIza",
         voz_por_personagem=True, figurantes_piper=True, voz_dublagem="edresson", encurtar_falas=False)
    assert automacao.main(["--dublar"]) == automacao.OK
    assert quem == {"Olá!": "gemini", "Tchau.": "gemini",
                    "Uma fala comprida demais para caber nesse pedacinho de tempo.": "piper edresson"}


def test_robo_so_com_o_piper(casa, tmp_path, monkeypatch):
    """Opção "Nos robôs agendados, usar só o Piper": mesmo com o Gemini na tela, o --dublar não gasta nada."""
    from jellyfin_tools import dublagem, voz_gemini
    from test_dublagem import FFMPEG, SRT, VozFalsa, faixas, video_de_teste
    if not FFMPEG:
        pytest.skip("sem ffmpeg")
    filmes = tmp_path / "Filmes"
    (filmes / "A (2001)").mkdir(parents=True)
    video_de_teste(filmes / "A (2001)" / "A (2001).mkv")
    (filmes / "A (2001)" / "A (2001).pt-BR.srt").write_text(SRT, encoding="utf-8")
    monkeypatch.setattr(automacao, "videos_para_dublar",
                        lambda *p, **k: dublagem.videos_para_dublar(*p, **{**k, "sondar": lambda v: (6.0, ["eng"])}))
    monkeypatch.setattr(voz_gemini, "MotorGemini", lambda *a, **k: pytest.fail("o robô não deveria usar o Gemini"))
    piper = VozFalsa()
    monkeypatch.setattr(automacao, "motor_piper", lambda o, voz="", **k: piper)
    casa(destino_filmes=str(filmes), motor_voz="Gemini (premium, Google AI Studio)", chave_gemini="AIza",
         voz_por_personagem=True, robo_so_piper=True, encurtar_falas=False)
    assert automacao.main(["--dublar"]) == automacao.OK and piper.textos


def test_robo_avulsos_precisa_da_pasta_e_dubla_a_caixa_de_entrada(casa, tmp_path, monkeypatch):
    from jellyfin_tools import dublagem
    from tests.test_dublagem import FFMPEG, SRT, VozFalsa, faixas, video_de_teste
    casa()
    assert automacao.main(["--avulsos"]) == automacao.FALTA_CONFIGURACAO
    if not FFMPEG:
        pytest.skip("sem ffmpeg")
    caixa = tmp_path / "Para Dublar"
    caixa.mkdir()
    video = video_de_teste(caixa / "Aula.mkv")
    (caixa / "Aula.pt-BR.srt").write_text(SRT, encoding="utf-8")
    (caixa / "Sem legenda.mkv").write_bytes(b"")                    # sem legenda e sem chave: só o Whisper faria
    voz = VozFalsa()
    monkeypatch.setattr(automacao, "preparar_motor", lambda o, **k: voz)
    monkeypatch.setattr(automacao, "videos_para_dublar",
                        lambda *p, **k: dublagem.videos_para_dublar(*p, **{**k, "sondar": lambda v: (6.0, ["eng"])}))
    monkeypatch.setattr(automacao, "videos_sem_legenda", lambda *p, **k: [])
    casa(pasta_avulsos=str(caixa), encurtar_falas=False, dublagem_previa=False)
    assert automacao.main(["--avulsos"]) == automacao.OK
    linhas = faixas(video)                          # dublagem E legenda dentro do próprio vídeo; o .srt saiu
    assert len([l for l in linhas if "Audio" in l]) == 2 and [l for l in linhas if "Subtitle" in l] and voz.textos
    assert not (caixa / "Aula.pt-BR.srt").exists() and not dublagem.caminho_dublado(video).exists()
    resumo = json.loads((tmp_path / "config" / "rpa" / "ultimo.json").read_text(encoding="utf-8"))
    assert "1 dublado" in resumo["comandos"][0]["resumo"]
    o, _ = automacao.opcoes_salvas()
    o.avulsos_dublar = False                                        # só legenda: não dubla
    plano = automacao.planejar_avulsos(o, str(caixa))
    assert plano.dublar == [] and plano.videos == 2              # a versão dublada não conta como vídeo novo


def test_avulsos_caixa_de_entrada_mais_videos_de_outras_pastas(tmp_path):
    """A aba Avulsos junta a caixa de entrada com vídeos de outras pastas (sem repetir) e diz o que falta em cada um."""
    caixa, outra = tmp_path / "Caixa", tmp_path / "Outra"
    for pasta in (caixa, outra):
        pasta.mkdir()
    for nome in ("A.mkv", "B.mkv", "C.mkv", "Z - Dublado IA.mkv"):     # a versão dublada não é um vídeo novo
        (caixa / nome).write_bytes(b"")
    (caixa / "A.en.srt").write_text("1\n00:00:01,000 --> 00:00:02,000\nHi.\n", encoding="utf-8")
    (caixa / "C.pt-BR.srt").write_text("1\n00:00:01,000 --> 00:00:02,000\nOi.\n", encoding="utf-8")
    for nome in ("D.mkv", "E.mkv"):
        (outra / nome).write_bytes(b"")
    o = SimpleNamespace(idioma="pt-BR", avulsos_dublar=True, avulsos_legendar=False,
                        dublagem_no_original=True)                        # só o que o plano usa
    plano = automacao.planejar_avulsos(o, str(caixa), (str(outra / "D.mkv"), str(caixa / "A.mkv")),
                                       sondar=lambda v: (60.0, ["eng"]))
    assert [v.name for v in plano.lista] == ["A.mkv", "B.mkv", "C.mkv", "D.mkv"]     # E não foi escolhido
    assert plano.videos == 4
    linhas = {v.name: (legenda, acao, pronto) for v, legenda, acao, pronto in automacao.situacao_avulsos(plano)}
    assert linhas == {"A.mkv": ("em outro idioma", "Traduzir a legenda → dublar", False),
                      "B.mkv": ("nenhuma", "Criar a legenda pelo áudio → dublar", False),
                      "C.mkv": ("✓ ao lado (.srt)", "Dublar", False),
                      "D.mkv": ("nenhuma", "Criar a legenda pelo áudio → dublar", False)}
    # "Legendar" marcado: a legenda também vai para dentro do vídeo
    o.avulsos_legendar = True
    plano = automacao.planejar_avulsos(o, str(caixa), (str(outra / "D.mkv"),), sondar=lambda v: (60.0, ["eng"]))
    linhas = {v.name: acao for v, _, acao, _ in automacao.situacao_avulsos(plano, legendar=True)}
    assert linhas["A.mkv"] == "Traduzir a legenda → dublar → pôr a legenda no vídeo"
    assert linhas["C.mkv"] == "Dublar → pôr a legenda no vídeo" and plano.embutir == []   # vai junto com a dublagem
    o.avulsos_dublar = False
    plano = automacao.planejar_avulsos(o, str(caixa), sondar=lambda v: (60.0, ["eng"]))
    assert [(v.name, s.name) for v, s in plano.embutir] == [("C.mkv", "C.pt-BR.srt")]       # só a legenda
    assert {v.name: acao for v, _, acao, _ in automacao.situacao_avulsos(plano, dublar=False, legendar=True)
            }["C.mkv"] == "Pôr a legenda no vídeo"
    o.avulsos_dublar, o.avulsos_legendar = True, False
    # já dublado: pronto; sem dublar: só a legenda
    (caixa / "C - Dublado IA.mkv").write_bytes(b"x")
    o.avulsos_dublar = False
    plano = automacao.planejar_avulsos(o, "", (str(caixa / "C.mkv"),))
    assert [(v.name, acao, pronto) for v, _, acao, pronto in automacao.situacao_avulsos(plano, dublar=False)] == [
        ("C.mkv", "Nada: já está pronto", True)]
    assert automacao.planejar_avulsos(o, str(tmp_path / "não existe")).lista == []


def test_arquivo_do_elenco_da_serie(tmp_path, monkeypatch):
    """Antes faltava 'import re': dublar episódio de série com voz por personagem dava NameError aqui."""
    monkeypatch.setattr(automacao, "pasta_dublagem", lambda: tmp_path)
    assert automacao.arquivo_elenco("Sweet Home (2020)") == tmp_path / "series" / "Sweet Home (2020).json"
    assert automacao.arquivo_elenco("A/B: C?") == tmp_path / "series" / "A_B_ C_.json"
    assert automacao.arquivo_elenco("") == tmp_path / "series" / "serie.json"


def test_avulsos_mostra_o_andamento_da_dublagem(casa, tmp_path, monkeypatch):
    """Antes a aba Avulsos só dizia "Dublando 1 de 1" e a porcentagem aparecia no fim."""
    from jellyfin_tools import dublagem
    from test_dublagem import FFMPEG, SRT, VozFalsa, video_de_teste
    if not FFMPEG:
        pytest.skip("sem ffmpeg")
    caixa = tmp_path / "Avulsos"
    caixa.mkdir()
    video_de_teste(caixa / "Aula.mkv")
    (caixa / "Aula.pt-BR.srt").write_text(SRT, encoding="utf-8")
    monkeypatch.setattr(automacao, "videos_para_dublar",
                        lambda *p, **k: dublagem.videos_para_dublar(*p, **{**k, "sondar": lambda v: (6.0, ["eng"])}))
    monkeypatch.setattr(automacao, "videos_sem_legenda", lambda *p, **k: [])
    casa(pasta_avulsos=str(caixa), encurtar_falas=False, dublagem_previa=False)
    o, _ = automacao.opcoes_salvas()
    passos = []
    r = automacao.processar_avulsos(o, logging.getLogger("t"), str(caixa), motor=VozFalsa(),
                                    andamento=lambda fracao, texto: passos.append((fracao, texto)))
    assert r.contagens["dublados"] == 1
    fracoes = [f for f, t in passos if t.startswith("Dublando 1 de 1: Aula –")]
    assert len(fracoes) >= 3 and fracoes == sorted(fracoes) and fracoes[-1] == 1.0
    assert any("%" in t for _, t in passos)



def test_teste_de_alguns_minutos_traduz_e_ouve_so_o_trecho(casa, tmp_path, monkeypatch):
    """Teste dos avulsos: com legenda em outro idioma, só as falas do trecho vão para o tradutor; sem legenda, o
    Whisper ouve só o trecho. Nada é gravado ao lado do vídeo."""
    from types import SimpleNamespace as NS
    from jellyfin_tools import dublagem
    from jellyfin_tools.traducao import Fala
    from test_dublagem import FFMPEG, video_de_teste
    if not FFMPEG:
        pytest.skip("sem ffmpeg")
    casa(minutos_teste=1, avulsos_dublar=False, avulsos_legendar=True)
    o, _ = automacao.opcoes_salvas()
    caixa = tmp_path / "Avulsos"
    caixa.mkdir()
    video = video_de_teste(caixa / "Talk.mkv", segundos=200)
    linhas = []
    for k in range(40):                                        # 40 falas, uma a cada 5 s
        ini = 5 * k
        linhas.append(f"{k + 1}\n00:{ini // 60:02d}:{ini % 60:02d},000 --> 00:{ini // 60:02d}:{ini % 60:02d},900\n"
                      f"Line {k}\n")
    (caixa / "Talk.en.srt").write_text("\n".join(linhas), encoding="utf-8")
    pedidas = []

    class Tradutor:
        def traduzir_falas(self, textos, titulo="", parar=None, ao_progresso=None):
            pedidas.extend(textos)
            return [f"Fala {t.split()[1]}" for t in textos]
    monkeypatch.setattr(automacao, "tradutor_para", lambda o, idioma, ao_baixar=None: Tradutor())
    r = automacao.testar_avulso(o, video, logging.getLogger("t"))
    assert not r.erro, r.erro
    assert len(pedidas) == 12 and r.trecho[1] - r.trecho[0] == 60      # 1 min = 12 falas, não as 40
    assert r.amostra.is_file() and "Subtitle" in " ".join(dublagem_faixas(r.amostra))
    assert sorted(p.name for p in caixa.iterdir()) == ["Talk.en.srt", "Talk.mkv"]      # nada novo ao lado
    # sem legenda nenhuma: o Whisper ouve só o trecho
    (caixa / "Talk.en.srt").unlink()
    ouvidos = []

    class Whisper:
        def transcrever(self, audio, parar=None, ao_progresso=None):
            ouvidos.append(audio)
            ao_progresso(0.5)                                           # o Whisper avisa quanto já ouviu
            return "pt", 60.0, [Fala("00:00:01,000 --> 00:00:02,000", "Olá.")]
    passos = []
    r = automacao.testar_avulso(o, video, logging.getLogger("t"), transcritor=Whisper(),
                                andamento=lambda fracao, texto: passos.append((fracao, texto)))
    assert not r.erro, r.erro
    assert len(ouvidos) == 1 and r.falas == 1 and r.trecho[0] > 0          # um pedaço depois da abertura
    assert (0.225, "Teste: o Whisper está ouvindo o trecho 50%") in [(round(f, 3), t) for f, t in passos]


def test_relogio_do_whisper_e_nucleos():
    from jellyfin_tools.transcricao import nucleos_para_o_whisper
    agora = [0.0]
    relogio = automacao._Relogio(lambda: agora[0])
    agora[0] = 10
    assert relogio.falta(0.5) == ""                                       # cedo demais para estimar
    agora[0] = 30
    assert relogio.falta(0.25) == ", faltam ~2 min" and relogio.falta(0.75) == ", faltam ~10 s"
    assert (nucleos_para_o_whisper(4), nucleos_para_o_whisper(16), nucleos_para_o_whisper(2)) == (3, 8, 2)


def test_teste_a_partir_do_minuto_escolhido():
    """"a partir de 12:30": testar uma cena com várias pessoas falando, em vez do trecho com mais falas."""
    from types import SimpleNamespace as NS
    from jellyfin_tools.traducao import Fala
    assert [automacao.ler_inicio(t) for t in ("", "auto", "12", "12:30", "1:02:30", "0:05,5")] == \
        [None, None, 720, 750, 3750, 5.5]
    for errado in ("12h", "1:75", "-3", "1:2:3:4"):
        with pytest.raises(ValueError):
            automacao.ler_inicio(errado)
    falas = [(Fala(f"00:00:{s:02d},000 --> 00:00:{s:02d},900", "x"), "x") for s in range(0, 60, 2)]
    assert automacao.trecho_do_teste(NS(inicio_teste="0:10"), falas, 60) == (10, 70)
    assert automacao.trecho_do_teste(NS(inicio_teste=""), falas, 30) == (0, 30)       # automático
    assert automacao.trecho_do_teste(NS(inicio_teste="2:00"), None, 60, duracao=600) == (120, 180)
    with pytest.raises(automacao.ErroDublagem, match="vídeo tem só 1:40"):
        automacao.trecho_do_teste(NS(inicio_teste="5:00"), None, 60, duracao=100)
    with pytest.raises(automacao.ErroDublagem, match="não entendi"):
        automacao.trecho_do_teste(NS(inicio_teste="meio"), falas, 60)


def test_emocao_da_cena_so_com_a_voz_do_gemini(casa, tmp_path, monkeypatch):
    from test_dublagem import GeminiFalso, VozComVoz
    casa(chave_gemini="chave", emocao_da_cena=True)
    o, _ = automacao.opcoes_salvas()
    assert automacao.ouvinte_de_tons(o, "f.mkv", GeminiFalso()) is not None
    assert automacao.ouvinte_de_tons(o, "f.mkv", VozComVoz()) is None          # o Piper não interpreta
    o.emocao_da_cena = False                                                    # sem a emoção: ainda ouve o gênero
    from jellyfin_tools import tom
    monkeypatch.setattr(automacao, "localizar_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(automacao.voz_gemini, "_cliente", lambda chave: None)
    monkeypatch.setattr(tom, "ouvir_falas", lambda *a, **k: {0: tom.Ouvida("animada", "f", "Uma aula.")})
    ouvidas = automacao.ouvinte_de_tons(o, "f.mkv", GeminiFalso())([], [0], tmp_path, None)
    assert ouvidas == {0: tom.Ouvida(genero="f")} and ouvidas[0].nota() == ""
    assert automacao.vozes_por_genero(o, GeminiFalso()) is not None


def test_voz_pelo_genero_e_voz_por_personagem_no_teste(casa, tmp_path, monkeypatch):
    from jellyfin_tools import personagens
    from test_dublagem import GeminiFalso, VozComVoz
    casa(chave_gemini="chave", voz_gemini="Charon", motor_voz="Gemini (premium, Google AI Studio)")
    o, _ = automacao.opcoes_salvas()
    por_genero = automacao.vozes_por_genero(o, GeminiFalso())
    assert {k: por_genero[k] for k in ("m", "f")} == {"m": "Charon", "f": "Kore"}
    assert por_genero["f:crianca"] == "Leda" and por_genero["m:idoso"] == "Algieba"   # e a voz de cada idade
    assert automacao.vozes_por_genero(o, VozComVoz()) is None                # Piper: não ouve o original
    o.voz_gemini = "Aoede"
    assert {k: automacao.vozes_por_genero(o, GeminiFalso())[k] for k in ("m", "f")} == {"f": "Aoede", "m": "Charon"}
    o.voz_gemini = "clone:Izael"
    assert automacao.vozes_por_genero(o, GeminiFalso()) is None              # a SUA voz: vale para tudo
    # o teste com a voz por personagem: só as falas do trecho, cada pessoa com uma voz do gênero dela
    legenda = tmp_path / "A.pt-BR.srt"
    legenda.write_text("".join(f"{k + 1}\n00:00:{2 * k:02d},000 --> 00:00:{2 * k + 1:02d},000\nFala {k}.\n\n"
                               for k in range(8)), encoding="utf-8")
    pedidos = []
    ouvir_de_verdade = automacao.ouvir_personagens
    monkeypatch.setattr(automacao, "ouvir_personagens", lambda o, video, falas, **k: pedidos.append(k["ids"]) or [
        personagens.Personagem("Agatha", "f", falas=[2, 4, 5]), personagens.Personagem("Elena", "f", falas=[3, 6, 7])])
    o.voz_gemini, o.voz_por_personagem = "Charon", True
    vozes = automacao.vozes_do_teste(o, tmp_path / "A.mkv", legenda, (4.0, 16.0), logging.getLogger("t"))
    assert pedidos == [[2, 3, 4, 5, 6, 7]]
    assert {vozes[2], vozes[3]} <= set(automacao.voz_gemini.VOZES_FEMININAS) and vozes[2] != vozes[3]
    # o vídeo inteiro, depois, usa as mesmas pessoas (o elenco vai para o Gemini) e as mesmas vozes do teste
    assert automacao.vozes_fixas(tmp_path / "A.mkv") == {"Agatha": vozes[2], "Elena": vozes[3]}
    assert automacao.vozes_fixas(tmp_path / "A.mkv", serie="Outra") == {}       # série: o elenco da série
    capturado = {}
    monkeypatch.setattr(automacao, "localizar_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(personagens, "identificar", lambda *a, **k: capturado.update(k) or [])
    ouvir_de_verdade(o, tmp_path / "A.mkv", [], cliente=object())
    assert [p["rotulo"] for p in capturado["elenco"]] == ["Agatha", "Elena"]   # o Gemini reusa os rótulos
    o.voz_por_personagem = False
    assert automacao.vozes_do_teste(o, tmp_path / "A.mkv", legenda, (4.0, 16.0), logging.getLogger("t")) is None


def test_custo_do_teste_preve_o_video_inteiro_e_ajustar_uma_fala(casa, tmp_path, monkeypatch):
    """O teste guarda quanto custou: a confirmação do vídeo inteiro mostra a previsão com esse custo REAL. "Ajustar
    falas" refaz só a fala escolhida (com o texto, a voz e o tom trocados) e monta o vídeo de teste de novo."""
    from jellyfin_tools import dublagem
    from test_dublagem import FFMPEG, SRT, GeminiFalso, video_de_teste
    if not FFMPEG:
        pytest.skip("sem ffmpeg")
    casa(pronuncias="Johnson = Djônson")
    o, _ = automacao.opcoes_salvas()
    assert automacao.pronuncias_de(o) == {"Johnson": "Djônson"}
    pasta = tmp_path / "Filme"
    pasta.mkdir()
    video = video_de_teste(pasta / "Filme.mkv", segundos=8)
    legenda = pasta / "Filme.pt-BR.srt"
    legenda.write_text(SRT, encoding="utf-8")
    amostra = tmp_path / "teste.mkv"
    gemini = GeminiFalso()
    r = automacao.dublar_video(video, legenda, gemini, pasta_cache=automacao.pasta_dublagem(), trecho=(0, 8),
                               destino=amostra)
    assert r.status == "dublado"
    automacao.registrar_teste(video, amostra, (0, 120), legenda, {1: "Kore"}, 0.06)
    teste = automacao.testes_feitos()[0]
    assert teste["custo"] == 0.06 and teste["minutos"] == 2.0 and teste["vozes"] == {"1": "Kore"}
    assert automacao.previsao_pelo_teste(video, 100 * 60) == \
        "Pelo teste deste vídeo (US$ 0.06 em 2 min), o vídeo inteiro (1 h 40 min) deve custar ~US$ 3.00."
    assert automacao.previsao_pelo_teste(tmp_path / "outro.mkv", 600) == ""
    teste["trecho"] = [0, 8]
    linhas = automacao.falas_do_teste(teste)
    assert [(k, voz) for k, _, _, voz, _ in linhas] == [(0, ""), (1, "Kore")]
    monkeypatch.setattr(automacao, "preparar_motor", lambda o: gemini)
    antes = len(gemini.textos)
    r = automacao.refazer_fala(o, teste, 1, logging.getLogger("t"), texto="Agora mais curta.", tom="com raiva")
    assert r.status == "dublado" and gemini.textos[antes:] == ["Agora mais curta."]   # só essa fala
    assert gemini.vozes[-1] == "Kore" and gemini.tons[-1].startswith("Nesta fala: com raiva.")
    assert automacao.falas_do_teste(teste)[1][2:] == ("Agora mais curta.", "Kore", "com raiva")
    with pytest.raises(automacao.FaltaConfiguracao, match="versão anterior"):
        automacao.refazer_fala(o, {"video": str(video), "trecho": [0, 8], "amostra": str(amostra)}, 0,
                               logging.getLogger("t"))


def test_relatorio_de_qualidade_no_log(caplog):
    from types import SimpleNamespace as NS
    with caplog.at_level(logging.WARNING):
        automacao.registrar_qualidade(logging.getLogger("t"), NS(video="A.mkv", problemas=['0:05 "Oi.": cortada']))
        automacao.registrar_qualidade(logging.getLogger("t"), NS(video="B.mkv", problemas=[]))
    assert "1 fala(s) para conferir em A.mkv" in caplog.text and '0:05 "Oi.": cortada' in caplog.text
    assert "B.mkv" not in caplog.text


def test_duracao_arredondada_e_custos_por_api_com_dica():
    assert [automacao._duracao(x) for x in (45, 120, 90, 1739.6, 6000, 7200)] == \
        ["45 s", "2 min", "1,5 min", "29 min", "1 h 40 min", "2 h"]           # antes: "28,9932 min"
    texto = automacao.texto_dos_custos({"Claude": (0.05, False), "Gemini (voz)": (0.40, False),
                                        "Gemini (escuta)": (0.16, True)}, valor=lambda d: f"US$ {d:.2f}")
    assert texto.splitlines()[:4] == ["Custos por API:", "• Gemini (voz): US$ 0.40",
                                      "• Gemini (ouvir o original: quem fala e emoção): grátis",
                                      "• Claude (tradução e falas encurtadas): US$ 0.05"]
    assert "Para economizar em Gemini (voz)" in texto and "Flex" in texto
    assert automacao.texto_dos_custos({}) == ""


def dublagem_faixas(arquivo):
    from test_dublagem import faixas
    return faixas(arquivo)


def test_avulsos_no_modo_economico_vao_no_lote_e_dublam_depois(casa, tmp_path, monkeypatch):
    """Modo econômico ligado: a legenda em outro idioma vai num lote (metade do preço), não é enviada duas vezes,
    e quando o lote fica pronto a legenda em português aparece e o vídeo entra na dublagem."""
    from jellyfin_tools.traducao import Tradutor
    from test_traducao import SRT, ClienteFalso
    from test_traducao_lote import LoteFalso
    caixa = tmp_path / "Avulsos"
    caixa.mkdir()
    (caixa / "Aula.mkv").write_bytes(b"")
    (caixa / "Aula.en.srt").write_text(SRT, encoding="utf-8")
    cliente = ClienteFalso()
    cliente.batches = LoteFalso(cliente)
    monkeypatch.setattr(automacao, "Tradutor", lambda **k: Tradutor(cliente=cliente, **{
        c: v for c, v in k.items() if c != "chave"}))
    monkeypatch.setattr(automacao, "videos_sem_legenda", lambda *p, **k: [])
    from jellyfin_tools import dublagem
    monkeypatch.setattr(dublagem, "embutir_legenda", lambda ffmpeg, video, srt, **k: Path(video))
    casa(pasta_avulsos=str(caixa), avulsos_dublar=False, avulsos_legendar=True, traducao_economica=True,
         chave_claude="sk-ant")
    o, _ = automacao.opcoes_salvas()
    assert automacao.usa_lote(o)
    r = automacao.processar_avulsos(o, logging.getLogger("t"), str(caixa), sondar=lambda v: (60.0, ["eng"]))
    assert r.contagens["no_lote"] == 1 and r.contagens["traduzidas"] == 0 and "modo econômico" in r.resumo
    assert len(cliente.batches.criados) == 1 and not cliente.pedidos            # nada a preço cheio
    r = automacao.processar_avulsos(o, logging.getLogger("t"), str(caixa), sondar=lambda v: (60.0, ["eng"]))
    assert len(cliente.batches.criados) == 1 and r.contagens["no_lote"] == 1    # esperando: não manda de novo
    cliente.batches.terminado = True
    r = automacao.processar_avulsos(o, logging.getLogger("t"), str(caixa), sondar=lambda v: (60.0, ["eng"]))
    assert r.contagens["traduzidas"] == 1 and (caixa / "Aula.pt-BR.srt").is_file()
    assert not automacao.destinos_em_lote() and r.contagens["no_lote"] == 0


def test_ouvir_personagens_usa_o_roteiro_ao_lado_do_video(casa, tmp_path, monkeypatch):
    """Com 'Nome.roteiro.txt' ao lado do vídeo, o Gemini só ouve o que o roteiro não cobriu; com a opção
    desligada, o roteiro é ignorado."""
    from jellyfin_tools import personagens
    from test_roteiro import EN, PT, ROTEIRO
    pasta = tmp_path / "Farol"
    pasta.mkdir()
    video = pasta / "Farol.mkv"
    video.write_bytes(b"")
    (pasta / "Farol.en.srt").write_text(EN, encoding="utf-8")
    (pasta / "Farol.pt-BR.srt").write_text(PT, encoding="utf-8")
    (pasta / "Farol.roteiro.txt").write_text(ROTEIRO, encoding="utf-8")
    monkeypatch.setattr(automacao, "localizar_ffmpeg", lambda: "ffmpeg")
    pedidos = {}
    monkeypatch.setattr(personagens, "identificar", lambda *a, **k: pedidos.update(k) or [])
    casa(chave_gemini="AIza")
    o, _ = automacao.opcoes_salvas()
    falas = automacao.falas_da_legenda(pasta / "Farol.pt-BR.srt")
    automacao.ouvir_personagens(o, video, falas, cliente=object())
    assert pedidos["sabidas"][0] == "Leo" and len(pedidos["sabidas"]) == 6
    assert {p["rotulo"] for p in pedidos["elenco"]} == {"Leo", "Mara", "Old Sailor"}
    o.usar_roteiro = False
    automacao.ouvir_personagens(o, video, falas, cliente=object())
    assert pedidos["sabidas"] is None and pedidos["elenco"] is None
