"""Comandos para robôs (Maestro.exe --organizar, --conferir-espelhos...): sem janela, com código de saída e log."""
import json
import os
import subprocess
import sys
import time
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
    from test_dublagem import FFMPEG, SRT, VozFalsa, video_de_teste
    if not FFMPEG:
        pytest.skip("sem ffmpeg")
    filmes = tmp_path / "Filmes"
    (filmes / "A (2001)").mkdir(parents=True)
    video_de_teste(filmes / "A (2001)" / "A (2001).mkv")
    (filmes / "A (2001)" / "A (2001).pt-BR.srt").write_text(SRT, encoding="utf-8")
    monkeypatch.setattr(automacao, "preparar_piper", lambda pasta: Path("piper"))
    monkeypatch.setattr(automacao, "preparar_voz", lambda voz, pasta: Path("v.onnx"))
    monkeypatch.setattr(automacao, "MotorPiper", lambda exe, modelo: VozFalsa())
    monkeypatch.setattr(automacao, "videos_para_dublar",
                        lambda *p, **k: dublagem.videos_para_dublar(*p, sondar=lambda v: (6.0, ["eng"]), **k))
    casa()
    assert automacao.main(["--dublar"]) == automacao.FALTA_CONFIGURACAO
    casa(destino_filmes=str(filmes))
    assert automacao.main(["--dublar"]) == automacao.OK
    assert resultado(tmp_path)["comandos"][0]["resumo"] == "1 de 1 filme(s) dublado(s), 0 erro(s)."
    assert (filmes / "A (2001)" / "A (2001) - Dublado IA.mkv").is_file()


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
