"""Abrir a ISO do jogo (modo "Traduzir e dublar" da aba 🎮 Jogos): a lista de todos os arquivos (com pastas), o que
tem som (VAG solto, VAG dentro de pacote, RenderWare que ainda não abre, vídeo), tirar as falas e montar a ISO em
português numa cópia, com cada fala no MESMO byte (o resto do disco não muda)."""
import struct

import numpy as np
import pytest

from jellyfin_tools import audio_jogo as aj
from jellyfin_tools import iso_jogo as ij
from jellyfin_tools import patch_jogo as pj
from tests.test_audio_jogo import tom, vag
from tests.test_patch_jogo import _registro
from tests.test_voz_clonada import FFMPEG


def iso_de_jogo(caminho, arquivos: dict, boot: str = "SLUS_210.50", volume: str = "BURNOUT3"):
    """Uma ISO 9660 de "PS2" com pastas: {"SOUND/VOZES.BIN": bytes, ...} + o SYSTEM.CNF."""
    arquivos = {"SYSTEM.CNF": f"BOOT2 = cdrom0:\\{boot};1\r\nVER = 1.00\r\n".encode(), **arquivos}
    pastas = {""}
    for nome in arquivos:
        partes = nome.split("/")
        for i in range(1, len(partes)):
            pastas.add("/".join(partes[:i]))
    pastas = sorted(pastas, key=lambda p: (p.count("/"), p))
    setor_da_pasta = {p: 18 + i for i, p in enumerate(pastas)}
    proximo = 18 + len(pastas)
    setor_do_arquivo = {}
    for nome, dados in arquivos.items():
        setor_do_arquivo[nome] = proximo
        proximo += max(1, -(-len(dados) // 2048))
    total = proximo
    setores = {}
    for p in pastas:
        pai = "/".join(p.split("/")[:-1]) if p else ""
        registros = _registro(b"\x00", setor_da_pasta[p], 2048, True) + \
            _registro(b"\x01", setor_da_pasta[pai], 2048, True)
        filhos = sorted({n.split("/")[p.count("/") + 1 if p else 0] for n in list(arquivos) + pastas
                         if (n.startswith(p + "/") if p else n) and n != p})
        for nome in filhos:
            completo = f"{p}/{nome}" if p else nome
            if completo in setor_da_pasta:
                registros += _registro(nome.encode(), setor_da_pasta[completo], 2048, True)
            else:
                registros += _registro(f"{nome};1".encode(), setor_do_arquivo[completo], len(arquivos[completo]))
        assert len(registros) <= 2048
        setores[setor_da_pasta[p]] = registros.ljust(2048, b"\x00")
    pvd = bytearray(2048)
    pvd[0:7] = b"\x01CD001\x01"
    pvd[40:72] = volume.encode().ljust(32)
    pvd[80:88] = struct.pack("<I", total) + struct.pack(">I", total)
    pvd[156:156 + 34] = _registro(b"\x00", 18, 2048, True)
    fim = bytearray(2048)
    fim[0:7] = b"\xffCD001\x01"
    setores[16], setores[17] = bytes(pvd), bytes(fim)
    with open(caminho, "wb") as f:
        f.truncate(total * 2048)
        for s, dados in setores.items():
            f.seek(s * 2048)
            f.write(dados)
        for nome, dados in arquivos.items():
            f.seek(setor_do_arquivo[nome] * 2048)
            f.write(dados.ljust(max(1, -(-len(dados) // 2048)) * 2048, b"\x00"))
    return caminho


def vag_bytes(tmp_path, segundos: float, nome: bytes, freq: float = 220.0) -> bytes:
    return vag(tmp_path / f"{nome.decode()}.vag", tom(segundos, 22050, freq), nome=nome).read_bytes()


def disco(tmp_path):
    """Um jogo de mentira: 3 falas VAG dentro de um pacote (com lixo entre elas), 1 VAG solto, a música em RWS
    (RenderWare, que o Maestro ainda não abre), um vídeo e os dados."""
    falas = [vag_bytes(tmp_path, s, n, f) for s, n, f in ((0.8, b"DJ_001", 140.0), (1.2, b"DJ_002", 150.0),
                                                           (0.6, b"DJ_003", 130.0))]
    pacote = b"PACK" + bytes(300) + falas[0] + b"LIXO" * 50 + falas[1] + bytes(77) + falas[2] + b"VAGp quebrado" + \
        bytes(500)
    rws = struct.pack("<III", ij.RWS_ID, 5000, 0x1C020037) + bytes(5000)
    arquivos = {"SOUND/VOZES.BIN": pacote, "SOUND/MENU.VAG": vag_bytes(tmp_path, 0.5, b"MENU", 300.0),
                "TRACKS/EATRAX0.RWS": rws, "MOVIES/INTRO.PSS": bytes(4096), "DATA/GLOBAL.BIN": bytes(range(256)) * 40}
    return iso_de_jogo(tmp_path / "Burnout 3 - Takedown.iso", arquivos), falas


def test_lista_todos_os_arquivos_com_as_pastas(tmp_path):
    iso, _ = disco(tmp_path)
    arquivos, setor = ij.listar(iso)
    assert setor == 2048
    assert {a.caminho for a in arquivos} == {"SYSTEM.CNF", "SOUND/VOZES.BIN", "SOUND/MENU.VAG",
                                             "TRACKS/EATRAX0.RWS", "MOVIES/INTRO.PSS", "DATA/GLOBAL.BIN"}
    assert pj.ler_info(iso).id_jogo == "SLUS-21050"


def test_analisa_o_que_tem_som(tmp_path):
    iso, falas = disco(tmp_path)
    andamento = []
    a = ij.analisar(iso, ao_progresso=andamento.append)
    assert andamento[-1] == 1.0 and a.id_jogo == "SLUS-21050" and a.pode_trocar
    soltas = [f for f in a.falas if f.solta]
    dentro = [f for f in a.falas if not f.solta]
    assert [f.origem for f in soltas] == ["SOUND/MENU.VAG"]
    assert [f.tamanho for f in dentro] == [len(x) for x in falas]            # o "VAGp quebrado" não conta
    assert a.pacotes_com_vag == {"SOUND/VOZES.BIN": 3}
    assert dentro[0].relativo.startswith("audio/SOUND/VOZES.BIN/") and dentro[0].relativo.endswith("_DJ_001.vag")
    assert a.outros_sons == {"RenderWare Audio (RWS)": 1} and sum(a.videos.values()) == 1
    assert a.resumo() == "4 falas que o Maestro troca (1 soltas, 3 dentro de 1 pacote(s))"
    texto = ij.relatorio(a)
    for trecho in ("SLUS-21050", "3 falas VAG dentro de SOUND/VOZES.BIN", "RenderWare Audio (RWS)",
                   "TRACKS/EATRAX0.RWS", "vídeo PSS"):
        assert trecho in texto, trecho


def test_sem_nada_que_o_maestro_troque(tmp_path):
    iso = iso_de_jogo(tmp_path / "Corrida.iso", {"TRACKS/EATRAX0.RWS": struct.pack("<I", ij.RWS_ID) + bytes(3000)})
    a = ij.analisar(iso)
    assert not a.falas and not a.pode_trocar
    assert a.resumo() == "nenhuma fala que o Maestro já saiba trocar (achei 1 RenderWare Audio (RWS): veja o relatório)"


@pytest.mark.skipif(not FFMPEG, reason="sem ffmpeg")
def test_tirar_dublar_e_montar_a_iso_no_mesmo_lugar(tmp_path):
    iso, falas = disco(tmp_path)
    original = iso.read_bytes()
    a = ij.analisar(iso)
    pasta = tmp_path / "extraido"
    assert ij.extrair(a, pasta) == 4
    mapa = ij.ler_mapa(pasta)
    assert mapa["iso"]["id"] == "SLUS-21050" and len(mapa["falas"]) == 4
    dentro = sorted((f for f in a.falas if not f.solta), key=lambda f: f.inicio)
    assert (pasta / dentro[1].relativo).read_bytes() == falas[1]               # a fala saiu inteira e igual
    # a "dublagem": outra voz, gravada no formato e no tamanho da original
    saida = tmp_path / "entrega"
    trocadas = []
    for i, fala in enumerate(dentro[:2]):
        dublada = tmp_path / f"dublada{i}.wav"
        import wave
        with wave.open(str(dublada), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(24000)
            w.writeframes(tom(0.9, 24000, 400.0).tobytes())
        aj.gravar_como(pasta / fala.relativo, dublada, saida / "audio_ptbr" / fala.relativo, FFMPEG)
        trocadas.append(fala)
    (saida / "audio_ptbr" / "audio/SOUND/MENU.VAG").parent.mkdir(parents=True, exist_ok=True)
    (saida / "audio_ptbr" / "audio/SOUND/MENU.VAG").write_bytes(b"VAGp" + bytes(10))     # tamanho errado: pula
    nova = tmp_path / "PT" / "SLUS_210.50.Burnout 3 PT-BR.iso"
    m = ij.montar(iso, pasta, saida / "audio_ptbr", nova)
    assert m.trocadas == 2 and [p[0] for p in m.puladas] == ["audio/SOUND/MENU.VAG"]
    assert iso.read_bytes() == original                                        # a original não mudou
    novo = nova.read_bytes()
    assert len(novo) == len(original)
    diferentes = np.flatnonzero(np.frombuffer(novo, np.uint8) != np.frombuffer(original, np.uint8))
    for b in (diferentes.min(), diferentes.max()):                              # só mudou dentro das 2 falas
        assert any(f.inicio <= b < f.inicio + f.tamanho for f in trocadas)
    som, _ = aj.ler_som(saida / "audio_ptbr" / trocadas[0].relativo)
    novo_vag = novo[trocadas[0].inicio:trocadas[0].inicio + trocadas[0].tamanho]
    assert novo_vag == (saida / "audio_ptbr" / trocadas[0].relativo).read_bytes() and len(som)
    assert pj.ler_info(nova).id_jogo == "SLUS-21050"
    with pytest.raises(pj.ErroPatch, match="outro nome"):
        ij.montar(iso, pasta, saida / "audio_ptbr", iso)
    with pytest.raises(pj.ErroPatch, match="mapa_iso"):
        ij.montar(iso, tmp_path, saida / "audio_ptbr", tmp_path / "x.iso")
