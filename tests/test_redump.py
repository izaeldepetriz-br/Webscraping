"""O banco Redump: baixa a lista uma vez (guardada como índice), acha a ISO perfeita pela impressão digital (MD5,
ou CRC32 + tamanho) e fica com a lista anterior se a nova vier estragada."""
import io
import zipfile

import pytest

from jellyfin_tools import redump
from jellyfin_tools.patch_jogo import ErroPatch

DAT = b"""<?xml version="1.0"?>
<datafile><header><name>Sony - PlayStation 2</name><version>2026-06-15</version></header>
<game name="Burnout 3 - Takedown (USA)"><category>Games</category>
<rom name="Burnout 3 - Takedown (USA).iso" size="2867855360" crc="70f0e224" md5="53d793704ac0a263546d05893804d0cc"/>
</game>
<game name="Jogo de CD (Europe)"><rom name="Jogo de CD (Europe).cue" size="99" crc="11111111" md5="aa"/>
<rom name="Jogo de CD (Europe).bin" size="1000" crc="deadbeef" md5="0123456789abcdef0123456789abcdef"/></game>
</datafile>"""


def pacote(dados: bytes) -> bytes:
    saida = io.BytesIO()
    with zipfile.ZipFile(saida, "w") as z:
        z.writestr("Sony - PlayStation 2 - Datfile (2).dat", dados)
    return saida.getvalue()


def test_baixa_uma_vez_e_acha_a_iso_perfeita(tmp_path):
    baixados = []

    def baixar(url, destino, progresso):
        baixados.append(url)
        destino.write_bytes(pacote(DAT))
    indice = redump.indice("PS2", tmp_path, baixar)
    assert baixados == ["http://redump.org/datfile/ps2/"] and indice["versao"] == "2026-06-15"
    assert redump.procurar(indice, "53D793704AC0A263546D05893804D0CC", "", 0) == "Burnout 3 - Takedown (USA)"
    assert redump.procurar(indice, "", "DEADBEEF", 1000) == "Jogo de CD (Europe)"      # pelo CRC32 + tamanho
    assert redump.procurar(indice, "00" * 16, "12345678", 5) is None
    redump.indice("PS2", tmp_path, baixar)
    assert len(baixados) == 1                                                  # guardado: não baixa de novo
    velho = redump.indice("PS2", tmp_path, lambda u, d, p: d.write_bytes(b"lixo"), agora=lambda: 9e12)
    assert velho["versao"] == "2026-06-15"                                     # veio estragada: fica a anterior
    with pytest.raises(ErroPatch, match="só os discos de PS2"):
        redump.indice("GameCube", tmp_path, baixar)
