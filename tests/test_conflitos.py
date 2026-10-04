"""Resolver conflitos com um clique: fica a melhor cópia; a outra vai para .organizador/removidos."""
import imageio_ffmpeg
import pytest
import subprocess

from jellyfin_tools import CatalogoLocal, desfazer, organizar_pasta
from jellyfin_tools.conflitos import aplicar, decidir, nota
from jellyfin_tools.organizador import ultimo_log


def _video(caminho, altura, segundos=1):
    """Vídeo de verdade (pequeno) com a resolução pedida, para o ffmpeg ler."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    largura = altura * 16 // 9 // 2 * 2
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-f", "lavfi", "-i",
                    f"color=c=black:size={largura}x{altura}:rate=1", "-t", str(segundos), "-y", str(caminho)],
                   check=True)
    return caminho


def test_nota_le_a_resolucao_do_proprio_video(tmp_path):
    sem_nome = _video(tmp_path / "Matrix (1999).mp4", 1080)          # na biblioteca o nome não diz "1080p"
    pior = _video(tmp_path / "Matrix.1999.720p.mp4", 720)
    assert nota(sem_nome)[0] == 1080 and nota(pior)[0] == 720


def test_copia_repetida_sai_a_pior_e_desfazer_volta(tmp_path):
    origem, filmes = tmp_path / "Downloads", tmp_path / "Filmes"
    _video(origem / "Matrix.1999.1080p.BluRay.mp4", 1080)
    _video(origem / "Matrix.1999.720p.WEB-DL.mp4", 720)
    movs = organizar_pasta(origem, filmes, CatalogoLocal.padrao())
    decisoes = decidir(movs)
    assert [(d.fica.name, d.sai.name, d.substitui) for d in decisoes] == [
        ("Matrix.1999.1080p.BluRay.mp4", "Matrix.1999.720p.WEB-DL.mp4", False)]
    assert "fica: Matrix.1999.1080p.BluRay.mp4 (1080p" in decisoes[0].texto()
    saiu, _ = aplicar(decisoes, filmes, origem)
    assert saiu == 1 and not (origem / "Matrix.1999.720p.WEB-DL.mp4").exists()
    assert list((origem / ".organizador" / "removidos").rglob("Matrix.1999.720p.WEB-DL.mp4"))
    assert [m.status for m in organizar_pasta(origem, filmes, CatalogoLocal.padrao())] == ["simulado"]   # sem conflito
    desfazer(ultimo_log(filmes))
    assert (origem / "Matrix.1999.720p.WEB-DL.mp4").exists()


@pytest.mark.parametrize("nova, antiga, troca", [(1080, 720, True), (720, 1080, False)])
def test_ja_na_biblioteca_fica_a_melhor(tmp_path, nova, antiga, troca):
    origem, filmes = tmp_path / "Downloads", tmp_path / "Filmes"
    na_biblioteca = _video(filmes / "Matrix (1999)" / "Matrix (1999).mp4", antiga)
    _video(origem / "Matrix.1999.mp4", nova)
    (origem / "Matrix.1999.pt-BR.srt").write_text("legenda", encoding="utf-8")
    movs = organizar_pasta(origem, filmes, CatalogoLocal.padrao())
    assert [m.status for m in movs] == ["conflito"]
    decisao, = decidir(movs)
    assert decisao.substitui is troca
    aplicar([decisao], filmes, origem)
    assert nota(na_biblioteca)[0] == max(nova, antiga)                 # a melhor ficou no lugar
    assert (origem / "Matrix.1999.mp4").exists() is False
    desfazer(ultimo_log(filmes))                                       # e tudo volta como estava
    assert nota(na_biblioteca)[0] == antiga and (origem / "Matrix.1999.mp4").exists()
