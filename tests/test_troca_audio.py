"""Aba "🎧 Áudio": ler as faixas, conferir o encaixe (atraso, velocidade, cortes), volume, inserir/extrair e a
amostra de 30 s. Os arquivos de teste são sintéticos: a "música e os efeitos" (batidas) são iguais nos dois e as
"falas" (ruído com começo suave) são diferentes, como num filme em dois idiomas."""
import json
import random
import subprocess
import wave
from pathlib import Path

import pytest

from jellyfin_tools import troca_audio as ta
from jellyfin_tools.dublagem import localizar_ffmpeg

FFMPEG = localizar_ffmpeg()
pytestmark = pytest.mark.skipif(not FFMPEG, reason="sem ffmpeg")
TAXA = 48000


def _som(duracao: float, batidas, falas, volume: float = 1.0):
    import numpy as np
    n = int(duracao * TAXA)
    rng = np.random.default_rng(1)
    sinal = rng.normal(0, 0.003, n).astype(np.float32)                # o "ar" da sala
    for t in batidas:                                                   # música e efeitos: ataque seco
        i = int(t * TAXA)
        tamanho = int(0.08 * TAXA)
        if 0 <= i < n - tamanho:
            ruido = np.random.default_rng(int(t * 1000)).normal(0, 0.5, tamanho).astype(np.float32)
            sinal[i:i + tamanho] += ruido * np.exp(-np.linspace(0, 6, tamanho)).astype(np.float32)
    for t, comprimento, semente in falas:                               # falas: começo suave (não "bate")
        i, tamanho = int(t * TAXA), int(comprimento * TAXA)
        if 0 <= i < n - tamanho:
            envelope = np.sin(np.linspace(0, np.pi, tamanho)).astype(np.float32) ** 2
            sinal[i:i + tamanho] += np.random.default_rng(semente).normal(0, 0.12, tamanho).astype(np.float32) * envelope
    return np.clip(sinal * volume, -1, 1)


def _wav(caminho: Path, sinal) -> Path:
    import numpy as np
    with wave.open(str(caminho), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(TAXA)
        w.writeframes((sinal * 32767).astype(np.int16).tobytes())
    return caminho


def _video(caminho: Path, duracao: float, audios: list, legendas: list = (), formato_audio: str = "ac3") -> Path:
    """audios: [(wav, idioma, título)]; legendas: [(srt, idioma, forçada?)]."""
    comando = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
               f"color=c=black:s=64x36:r=24:d={duracao:.2f}"]
    for wav, _, _ in audios:
        comando += ["-i", str(wav)]
    for srt, _, _ in legendas:
        comando += ["-i", str(srt)]
    comando += ["-map", "0:v"]
    for i in range(len(audios)):
        comando += ["-map", f"{i + 1}:a"]
    for k in range(len(legendas)):
        comando += ["-map", f"{len(audios) + 1 + k}:0"]
    comando += ["-c:v", "libx264", "-preset", "ultrafast", "-c:a", formato_audio, "-c:s", "srt"]
    for i, (_, idioma, titulo) in enumerate(audios):
        if idioma:
            comando += [f"-metadata:s:a:{i}", f"language={idioma}"]
        if titulo:
            comando += [f"-metadata:s:a:{i}", f"title={titulo}"]
    for k, (_, idioma, forcada) in enumerate(legendas):
        comando += [f"-metadata:s:s:{k}", f"language={idioma}", f"-disposition:s:{k}", "forced" if forcada else "0"]
    subprocess.run(comando + ["-t", f"{duracao:.3f}", str(caminho)], check=True, capture_output=True)  # a legenda
    # pode acabar antes (com -shortest, o arquivo era cortado no fim dela)
    return caminho


def _cena(duracao: float = 90.0, semente: int = 7):
    rng = random.Random(semente)
    batidas = sorted(rng.uniform(1, duracao - 1) for _ in range(int(duracao * 0.8)))
    def falas(s):
        r = random.Random(s)
        return [(r.uniform(1, duracao - 2), r.uniform(0.4, 1.2), r.randint(1, 10_000)) for _ in range(int(duracao / 2))]
    return batidas, falas(11), falas(23)


def _par(tmp_path, atraso: float = 0.0, fator: float = 1.0, corte: tuple | None = None, volume_origem: float = 1.0,
         duracao: float = 90.0, legenda: bool = False):
    """(origem, destino): o destino em inglês; a origem em português, com o atraso/velocidade/corte pedidos.
    nova = origem × fator + atraso (o mesmo jeito do ajuste)."""
    batidas, falas_en, falas_pt = _cena(duracao)
    destino = _video(tmp_path / "Filme 1080p.mkv", duracao,
                     [(_wav(tmp_path / "en.wav", _som(duracao, batidas, falas_en)), "eng", "Original")])

    def na_origem(t):
        if corte and t >= corte[0]:
            if t < corte[0] + corte[1]:
                return None                                              # a cena que a origem não tem
            t -= corte[1]
        return (t - atraso) / fator
    duracao_origem = (duracao - atraso) / fator - (corte[1] if corte else 0)
    batidas_o = [x for x in (na_origem(t) for t in batidas) if x is not None and 0 < x < duracao_origem]
    falas_o = [(na_origem(t), c / fator, s) for t, c, s in falas_pt if na_origem(t) is not None]
    falas_o = [(t, c, s) for t, c, s in falas_o if 0 < t < duracao_origem]
    legendas = []
    if legenda:
        srt = tmp_path / "forcada.srt"
        srt.write_text("1\n00:00:10,000 --> 00:00:12,000\n[placa] Saída\n\n2\n00:00:40,000 --> 00:00:41,500\n"
                       "Olá, alienígena\n", encoding="utf-8")
        legendas = [(srt, "por", True)]
    origem = _video(tmp_path / "Filme DVD dublado.mkv", duracao_origem,
                    [(_wav(tmp_path / "pt.wav", _som(duracao_origem, batidas_o, falas_o, volume_origem)), "por",
                      "Dublado"),
                     (_wav(tmp_path / "es.wav", _som(duracao_origem, batidas_o, falas_o)), "", "")], legendas)
    return origem, destino


def test_le_as_faixas_de_audio_e_de_legenda(tmp_path):
    origem, destino = _par(tmp_path, legenda=True, duracao=20)
    info = ta.ler_arquivo(FFMPEG, origem)
    assert [(a.idioma, a.formato, a.titulo) for a in info.audios] == [("por", "ac3", "Dublado"), ("", "ac3", "")]
    assert info.audios[0].canais == "1.0" and info.audios[0].num_canais == 1
    assert [(s.idioma, s.forcada, s.de_texto, s.nome_formato) for s in info.legendas] == [
        ("por", True, True, "texto (SRT)")]
    assert info.videos == 1 and abs(info.duracao - 20) < 0.5
    assert ta.nome_idioma("") == "sem idioma marcado" and ta.nome_idioma("por") == "Português"
    assert ta.codigo_de("Espanhol (spa)") == "spa" and ta.codigo_de("pt") == "por"
    assert "áudio Inglês (AC3 1.0)" in ta.ler_arquivo(FFMPEG, destino).resumo()


def test_detecta_o_idioma_da_faixa_sem_etiqueta(tmp_path):
    origem, _ = _par(tmp_path, duracao=12)
    info = ta.ler_arquivo(FFMPEG, origem)
    ouvidos = []

    class Whisper:
        def transcrever(self, arquivo, **k):
            ouvidos.append(Path(arquivo).suffix)
            return "es", 30.0, []
    assert ta.detectar_idioma(FFMPEG, origem, info.audios[1], Whisper(), inicio=2) == "spa"
    assert ouvidos == [".wav"]


def test_mesma_versao_encaixa_sem_ajuste(tmp_path):
    origem, destino = _par(tmp_path)
    e = ta.conferir_encaixe(FFMPEG, origem, 0, destino)
    assert e.situacao == "mesma", (e.fator, e.atraso, e.pontos)
    assert len(e.pontos) == 3 and all(p.ok for p in e.pontos)


def test_acha_o_atraso_e_a_versao_europeia(tmp_path):
    origem, destino = _par(tmp_path, atraso=-4.3, fator=25 / 23.976)
    progresso = []
    e = ta.conferir_encaixe(FFMPEG, origem, 0, destino, ao_progresso=progresso.append)
    assert e.situacao == "ajuste" and not e.manual, (e.fator, e.atraso, e.pontos)
    assert abs(e.fator - 25 / 23.976) < 1e-3 and abs(e.atraso + 4.3) < 0.06
    assert all(p.sobra <= ta.TOLERANCIA for p in e.pontos) and progresso[-1] == 1.0
    assert ta.nome_da_velocidade(e.fator) == "25 → 23,976"
    # manual: o mesmo atraso digitado à mão confere; um atraso errado mostra quanto sobra
    certo = ta.conferir_encaixe(FFMPEG, origem, 0, destino, velocidade="25 → 23,976 (versão europeia)",
                                atraso_manual=-4.30)
    assert certo.manual and certo.ok and certo.atraso == -4.30 and abs(certo.atraso_achado + 4.3) < 0.06
    errado = ta.conferir_encaixe(FFMPEG, origem, 0, destino, velocidade="25 → 23,976 (versão europeia)",
                                 atraso_manual=-3.0)
    assert not errado.ok and all(p.sobra is None or p.sobra > 1 for p in errado.pontos)


def test_cortes_diferentes_nao_encaixam(tmp_path):
    origem, destino = _par(tmp_path, atraso=2.0, corte=(40.0, 6.0))
    e = ta.conferir_encaixe(FFMPEG, origem, 0, destino)
    assert e.situacao == "cortes" and not e.ok, (e.fator, e.atraso, e.pontos)
    assert "Versões diferentes" in e.texto_situacao()


def test_inserir_dentro_do_destino_com_a_legenda_forcada(tmp_path):
    origem, destino = _par(tmp_path, atraso=-1.5, legenda=True, duracao=30)
    info_o = ta.ler_arquivo(FFMPEG, origem)
    pedido = ta.Pedido(origem, destino, info_o.audios[:1], info_o.legendas, ta.Ajuste(1.0, -1.5, 0.0))
    r = ta.executar(FFMPEG, pedido)
    assert r.saida == destino and not r.refez_audio and r.avisos == []
    depois = ta.ler_arquivo(FFMPEG, destino)
    assert [(a.idioma, a.padrao) for a in depois.audios] == [("eng", False), ("por", True)]
    assert depois.audios[1].formato == "ac3"                              # copiada como estava
    assert depois.audios[1].titulo == "Português · de Filme DVD dublado · atraso −1,50 s"
    assert [(s.idioma, s.forcada) for s in depois.legendas] == [("por", True)]
    srt = tmp_path / "saiu.srt"
    subprocess.run([FFMPEG, "-loglevel", "error", "-y", "-i", str(destino), "-map", "0:s:0", str(srt)], check=True)
    inicio = srt.read_text(encoding="utf-8").split("\n")[1].split(" --> ")[0]
    h, m, resto = inicio.split(":")
    assert abs(int(h) * 3600 + int(m) * 60 + float(resto.replace(",", ".")) - 8.5) < 0.05, inicio   # 10 s - 1,5 s
    video = subprocess.run([FFMPEG, "-hide_banner", "-i", str(destino)], capture_output=True, text=True).stderr
    assert "start: 0.0" in video                                        # o vídeo do destino não andou
    assert not ta.temporario_no_original(destino).exists()


def test_copia_a_parte_extrair_e_volume_igualado(tmp_path):
    origem, destino = _par(tmp_path, volume_origem=0.3, duracao=30)
    info_o, info_d = ta.ler_arquivo(FFMPEG, origem), ta.ler_arquivo(FFMPEG, destino)
    tempos = ta.pontos_do_filme(30, 6)
    nova, original = (ta.loudness(FFMPEG, origem, 0, tempos, 6), ta.loudness(FFMPEG, destino, 0, tempos, 6))
    assert nova is not None and original - nova > ta.DIFERENCA_PARA_IGUALAR          # a dublagem está mais baixa
    ajuste = ta.Ajuste(1.0, 0.0, round(original - nova, 1))
    copia = ta.executar(FFMPEG, ta.Pedido(origem, destino, info_o.audios[:1], [], ajuste, onde="copia"))
    assert copia.saida.name == "Filme 1080p - com áudio Português.mkv" and copia.refez_audio
    feita = ta.ler_arquivo(FFMPEG, copia.saida)
    assert len(feita.audios) == 2 and "+" in feita.audios[1].titulo and " dB" in feita.audios[1].titulo
    igualada = ta.loudness(FFMPEG, copia.saida, 1, tempos, 6)
    assert abs(igualada - original) < 1.5
    assert ta.ler_arquivo(FFMPEG, destino).audios.__len__() == 1                        # o destino não mudou
    extraida = ta.executar(FFMPEG, ta.Pedido(origem, destino, info_o.audios, [], ta.Ajuste(), onde="extrair"))
    assert extraida.saida.name == "Filme 1080p - Português.mka"
    assert [a.idioma for a in ta.ler_arquivo(FFMPEG, extraida.saida).audios] == ["por", "und"[:0]]


def test_amostra_de_30_s_e_ondas(tmp_path):
    origem, destino = _par(tmp_path, atraso=-2.0, fator=25 / 23.976, duracao=40)
    info_o = ta.ler_arquivo(FFMPEG, origem)
    pedido = ta.Pedido(origem, destino, info_o.audios[:1], [], ta.Ajuste(25 / 23.976, -2.0, 3.0))
    saida = ta.amostra(FFMPEG, pedido, 5.0, tmp_path / "testes" / "amostra.mkv", duracao=10)
    feita = ta.ler_arquivo(FFMPEG, saida)
    assert len(feita.audios) == 2 and feita.audios[0].idioma == "por" and feita.audios[0].padrao
    assert abs(feita.duracao - 10) < 0.6
    destino_onda, nova = ta.ondas(FFMPEG, pedido, 0, 5.0, 10.0)
    assert len(destino_onda) == len(nova) > 900 and destino_onda.max() <= 1 and nova.max() <= 1
    batidas = ta.batidas_comuns(destino_onda, nova)
    assert batidas and all(0 <= b < len(nova) for b in batidas)
    crua_destino, crua = ta.ondas(FFMPEG, pedido, 0, 5.0, 10.0, ajustada=False)
    assert len(crua) == len(crua_destino)


def test_srt_titulo_e_historico(tmp_path):
    texto = "1\n00:00:25,000 --> 00:00:26,000\nOi\n"
    assert "00:00:24,068 --> 00:00:25,110" in ta.ajustar_srt(texto, 1.0427, -2.0)       # 25 × 1,0427 − 2
    ajuste = ta.Ajuste(25 / 23.976, -4.3, 5.8)
    assert ajuste.texto() == "atraso −4,30 s · 25 → 23,976 · +5,8 dB" and ajuste.refaz_audio
    assert not ta.Ajuste(1.0, 2.0, 0.0).refaz_audio
    assert ta.titulo_da_faixa("por", Path("Meu Filme - DVD.mkv"), ajuste).startswith("Português · de Meu Filme - DVD · ")
    arquivo = tmp_path / "trocas.json"
    pedido = ta.Pedido(Path("o.mkv"), Path("d.mkv"), [ta.Faixa("audio", 0, "por")], [], ajuste)
    encaixe = ta.Encaixe(ajuste.fator, ajuste.atraso, [ta.Ponto(5.0, -4.3, 0.5, 0.02)], "ajuste", manual=True)
    ta.registrar_troca(arquivo, pedido, ta.Resultado(Path("d.mkv")), encaixe)
    ta.registrar_troca(arquivo, pedido, ta.Resultado(Path("d2.mkv")), None)
    trocas = ta.trocas_feitas(arquivo)
    assert [t["saida"] for t in trocas] == ["d2.mkv", "d.mkv"] and trocas[1]["manual"]
    assert trocas[1]["ajuste"] == ajuste.texto() and trocas[1]["faixas"] == ["Português"]
    assert ta.apagar_trocas(arquivo, trocas[:1]) == 1
    assert [t["saida"] for t in json.loads(arquivo.read_text(encoding="utf-8"))] == ["d.mkv"]
