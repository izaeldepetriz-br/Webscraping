"""O ícone do Maestro: o "M" cuja perna direita vira a batuta do maestro, com a ponta acesa em verde
(o mesmo verde do "no ar" da TV ao vivo), em fundo roxo vivo (a cor dos botões principais).

Desenhado por código (Pillow): o mesmo desenho vira o .ico do .exe (na hora de gerar o programa), o ícone da
janela e o da bandeja perto do relógio, em qualquer tamanho, sem arquivo de imagem para carregar.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

NOME_APP = "Maestro"
TAMANHOS_ICO = (16, 20, 24, 32, 40, 48, 64, 128, 256)
_ROXO, _ROXO2, _VERDE, _ESCURO = (124, 92, 255), (168, 85, 247), (34, 197, 94), (13, 15, 20)
_REVISAO = 1                                   # mude se o desenho mudar (o .ico em cache é refeito)


def desenhar(tamanho: int = 256):
    """O ícone em RGBA, do tamanho pedido (desenha 4x maior e reduz: bordas lisas mesmo a 16 px)."""
    from PIL import Image, ImageDraw
    t = max(16, int(tamanho)) * 4
    claro = Image.new("RGB", (t, t), _ROXO)
    escuro = Image.new("RGB", (t, t), _ROXO2)
    mistura = Image.linear_gradient("L").rotate(-35, expand=False).resize((t, t))
    fundo = Image.composite(escuro, claro, mistura).convert("RGBA")
    mascara = Image.new("L", (t, t), 0)
    ImageDraw.Draw(mascara).rounded_rectangle([0, 0, t - 1, t - 1], radius=int(t * 0.23), fill=255)
    fundo.putalpha(mascara)
    d = ImageDraw.Draw(fundo)
    branco = (255, 255, 255, 255)

    def linha(pontos, largura):
        d.line(pontos, fill=branco, width=int(largura), joint="curve")
        for x, y in pontos:                                       # pontas arredondadas
            d.ellipse([x - largura / 2, y - largura / 2, x + largura / 2, y + largura / 2], fill=branco)

    w = t * 0.08
    linha([(t * .20, t * .76), (t * .20, t * .34), (t * .45, t * .60), (t * .70, t * .34)], w)
    linha([(t * .70, t * .34), (t * .84, t * .16)], w * 0.55)    # a batuta
    linha([(t * .70, t * .34), (t * .70, t * .76)], w)
    d.ellipse([t * .79, t * .09, t * .91, t * .21], fill=_ESCURO + (255,))
    d.ellipse([t * .81, t * .11, t * .89, t * .19], fill=_VERDE + (255,))   # a ponta acesa: "ao vivo"
    return fundo.resize((int(tamanho), int(tamanho)), Image.LANCZOS)


def salvar_ico(caminho: str | Path) -> Path:
    """Grava o .ico com todos os tamanhos que o Windows usa (16 px na bandeja ... 256 px na Área de Trabalho)."""
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    desenhar(256).save(caminho, format="ICO", sizes=[(n, n) for n in TAMANHOS_ICO])
    return caminho


def arquivo_ico() -> Path | None:
    """O .ico pronto para as janelas (gerado uma vez e guardado na pasta temporária). None se não deu."""
    caminho = Path(tempfile.gettempdir()) / f"maestro-icone-{_REVISAO}.ico"
    try:
        if not caminho.is_file() or caminho.stat().st_size == 0:
            salvar_ico(caminho)
        return caminho
    except Exception:                                # sem Pillow, disco cheio...: fica o ícone padrão
        return None


def aplicar(janela) -> None:
    """Põe o ícone na janela (barra de título e de tarefas). No Windows usa o .ico; nos outros, a imagem."""
    try:
        if sys.platform == "win32":
            if ico := arquivo_ico():
                janela.iconbitmap(str(ico))
            return
        from PIL import ImageTk
        foto = ImageTk.PhotoImage(desenhar(64), master=janela)
        janela.iconphoto(True, foto)
        janela._foto_icone = foto                    # sem guardar a referência, o Tk perde a imagem
    except Exception:
        pass
