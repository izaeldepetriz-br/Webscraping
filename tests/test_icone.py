"""O ícone do Maestro (o "M" com a batuta), desenhado por código: .ico com todos os tamanhos e a bandeja."""
from PIL import Image

from videoscraper import bandeja, icone


def test_desenho_em_varios_tamanhos():
    for tamanho in (16, 32, 256):
        imagem = icone.desenhar(tamanho)
        assert imagem.size == (tamanho, tamanho) and imagem.mode == "RGBA"
    grande = icone.desenhar(256)
    assert grande.getpixel((0, 0))[3] == 0                          # canto arredondado: transparente
    r, g, b, a = grande.getpixel((128, 200))                         # fundo roxo
    assert a == 255 and b > r > g
    r, g, b, _ = grande.getpixel((int(256 * .85), int(256 * .15)))   # a ponta verde da batuta
    assert g > 150 and r < 100 and b < 150
    assert bandeja.imagem_do_icone(64).size == (64, 64)


def test_ico_com_todos_os_tamanhos(tmp_path):
    caminho = icone.salvar_ico(tmp_path / "x" / "maestro.ico")
    assert set(Image.open(caminho).info["sizes"]) >= {(16, 16), (32, 32), (48, 48), (256, 256)}
    assert icone.NOME_APP == "Maestro"
