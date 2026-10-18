"""Vozes importadas (Configurações > Dublagem > "Importar voz"): modelos do Piper e gravações para clonar."""
import json

import pytest

from jellyfin_tools import vozes_importadas as vi
from jellyfin_tools.dublagem import ErroDublagem, executavel_piper, preparar_voz, voz_pronta
from tests.test_voz_clonada import FFMPEG, wav

CONFIG_PIPER = {"audio": {"sample_rate": 22050}, "language": {"code": "pt_BR"}, "phoneme_id_map": {"a": [1]}}


def modelo_piper(pasta, nome="pt_BR-cadu-medium", config=CONFIG_PIPER):
    onnx = pasta / f"{nome}.onnx"
    onnx.write_bytes(b"modelo")
    if config is not None:
        onnx.with_name(onnx.name + ".json").write_text(json.dumps(config), encoding="utf-8")
    return onnx


def test_tipo_do_arquivo_e_recusa_de_video():
    assert vi.tipo_do_arquivo("voz.onnx") == vi.PIPER
    assert vi.tipo_do_arquivo("C:/gravacoes/minha voz.M4A") == vi.GRAVACAO
    with pytest.raises(ErroDublagem, match="atores"):
        vi.tipo_do_arquivo("Filme (2020).mkv")
    with pytest.raises(ErroDublagem, match="modelo do Piper"):
        vi.tipo_do_arquivo("notas.txt")


def test_nome_e_id():
    assert vi.criar_id("Cadu Júnior!") == "cadu-junior"
    assert vi.validar_nome("  Cadu   Jr ") == ("Cadu Jr", "cadu-jr")
    existente = vi.VozImportada("Cadu", "cadu", vi.PIPER)
    for nome, motivo in (("", "dê um nome"), ("faber", "já é uma voz"), ("cadu", "já existe"), ("!!!", "letra"),
                         ("Voz (nova)", "sinais")):
        with pytest.raises(ErroDublagem, match=motivo):
            vi.validar_nome(nome, [existente])


def test_importar_piper_copia_e_o_piper_usa(tmp_path):
    origem = tmp_path / "baixados"
    origem.mkdir()
    vozes = tmp_path / "vozes"
    nova = vi.importar_piper(modelo_piper(origem), "Cadu", vozes, genero="masculina", idade="jovem")
    assert (nova.nome, nova.id, nova.tipo, nova.idioma, nova.perfil) == ("Cadu", "cadu", vi.PIPER, "pt_BR",
                                                                         "masculina, jovem")
    assert (vozes / "cadu.onnx").read_bytes() == b"modelo" and (vozes / "cadu.onnx.json").is_file()
    assert vi.e_portugues(nova) and vi.modelo_piper("cadu", vozes) == vozes / "cadu.onnx"
    # a dublagem acha a voz importada sem baixar nada
    nada = []
    assert preparar_voz("cadu", vozes, baixar=lambda *a: nada.append(a)) == vozes / "cadu.onnx" and not nada
    piper = executavel_piper(tmp_path / "piper")
    piper.parent.mkdir(parents=True)
    piper.write_bytes(b"")
    assert voz_pronta("cadu", tmp_path / "piper", vozes)
    assert not voz_pronta("../cadu", tmp_path / "piper", vozes)                # nome esquisito: não
    with pytest.raises(ErroDublagem, match="Importar voz"):
        preparar_voz("outra", vozes)
    # a lista guarda e volta igual; remover apaga os arquivos
    arquivo = tmp_path / "vozes_importadas.json"
    vi.salvar([nova], arquivo)
    assert vi.carregar(arquivo) == [nova]
    vi.remover(nova, tmp_path, vozes)
    assert not (vozes / "cadu.onnx").exists() and not (vozes / "cadu.onnx.json").exists()


def test_importar_piper_confere_a_configuracao(tmp_path):
    with pytest.raises(ErroDublagem, match="configuração da voz"):
        vi.importar_piper(modelo_piper(tmp_path, "sem-json", None), "X", tmp_path / "vozes")
    with pytest.raises(ErroDublagem, match="não parece"):
        vi.importar_piper(modelo_piper(tmp_path, "outra", {"ola": 1}), "Y", tmp_path / "vozes")
    ingles = vi.importar_piper(modelo_piper(tmp_path, "en_US-amy-medium", {**CONFIG_PIPER, "language":
                                                                            {"code": "en_US"}}),
                               "Amy", tmp_path / "vozes")
    assert not vi.e_portugues(ingles)


@pytest.mark.skipif(not FFMPEG, reason="sem ffmpeg")
def test_importar_gravacao_com_genero_e_idade_sem_consentimento(tmp_path):
    referencia = tmp_path / "minha voz.wav"
    referencia.write_bytes(wav(12))
    with pytest.raises(ErroDublagem, match="declaração"):
        vi.importar_gravacao(referencia, "Izael", "masculina", "adulta", False, tmp_path, FFMPEG)
    with pytest.raises(ErroDublagem, match="gênero"):
        vi.importar_gravacao(referencia, "Izael", "robô", "adulta", True, tmp_path, FFMPEG)
    with pytest.raises(ErroDublagem, match="idade"):
        vi.importar_gravacao(referencia, "Izael", "masculina", "antiga", True, tmp_path, FFMPEG)
    video = tmp_path / "trecho.mp4"
    video.write_bytes(b"")
    with pytest.raises(ErroDublagem, match="atores"):
        vi.importar_gravacao(video, "Izael", "masculina", "adulta", True, tmp_path, FFMPEG)
    curta = tmp_path / "curta.wav"
    curta.write_bytes(wav(2))
    with pytest.raises(ErroDublagem, match="pelo menos"):
        vi.importar_gravacao(curta, "Izael", "masculina", "adulta", True, tmp_path, FFMPEG)
    nova = vi.importar_gravacao(referencia, "Izael", "Masculina", "Adulta", True, tmp_path, FFMPEG)
    assert (nova.tipo, nova.id, nova.perfil) == (vi.GRAVACAO, "izael", "masculina, adulta")
    assert vi.arquivo_da_gravacao(nova, tmp_path).read_bytes().startswith(b"RIFF")
    assert "masculina, adulta" in nova.descrever() and "consent" not in nova.descrever()
    vi.remover(nova, tmp_path, tmp_path / "vozes")
    with pytest.raises(ErroDublagem, match="sumiu"):
        vi.arquivo_da_gravacao(nova, tmp_path)
