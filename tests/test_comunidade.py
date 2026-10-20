"""Procurar na comunidade: a lista dos patches do jogo (o banco público do PO.B.R.E e a busca do fórum), com o que
cada um traz, para qual versão foi feito e se encaixa na SUA ISO; a ISO inteira nunca aparece; o Romhacking.net e o
itch.io (que não deixam programas procurar) abrem no navegador."""
from pathlib import Path

from jellyfin_tools import comunidade as c
from jellyfin_tools.patch_jogo import InfoISO

ITENS = [
    {"arquivo": "playstation-2/god-of-war-ii-traduzido-e-dublado-bw.md",
     "title": " God of War II (Traduzido e Dublado) (Brazillian Warriors e Silent Fandub)", "system": "Playstation 2",
     "game_title": "God of War II", "patch_group": "undefined", "patch_version": "???", "patch_type": "xdelta3",
     "patch_progress": "Textos", "patch_site": "undefined",
     "texto": "Todos os textos do jogo estão traduzidos e os vídeos e diálogos falados durante o jogo foram "
              "dublados.ATENÇÃO:Esta tradução deve ser aplicada na versão americana do jogo God of War II, com "
              "CRC32 E271930D. O tamanho da imagem ISO compatível com a tradução é de 8.533.671.936 bytes."},
    {"arquivo": "playstation-2/devil-may-cry-3-bw.md", "title": " Devil May Cry 3 (Special Edition) (Brazilian Warriors)",
     "game_title": "Devil May Cry 3 - Dante's Awakening", "patch_group": "Brazilian Warriors", "patch_version": "2.0",
     "patch_type": "xdelta3", "patch_progress": "Textos",
     "texto": "ATENÇÃO:Esta tradução deve ser usada na versão europeia (SLES-54186) do jogo."},
    {"arquivo": "playstation-2/god-of-war-iso.md", "title": " God of War II (Grupo X)", "game_title": "God of War II",
     "patch_type": "ISO traduzida", "texto": "A ISO já traduzida."},
    {"arquivo": "playstation-2/god-of-war-1.md", "title": " God of War (Grupo Y)", "game_title": "God of War",
     "patch_type": "PPF 3.0", "texto": "versão americana"},
    {"arquivo": "playstation/final-fantasy-vii.md", "title": " Final Fantasy VII (Tradu-Kings)",
     "game_title": "Final Fantasy VII", "patch_type": "PPF 3.0", "texto": "SCUS-94163"},
]
FORUM = """<div class="windowbg"><div class="topic_details"><h5><a href="https://www.romhacking.net.br/index.php?PHPSESSID=abc&amp;board=3.0">Lançamentos</a> / <a href="https://www.romhacking.net.br/index.php?PHPSESSID=abc&amp;topic=99.msg1#msg1">[PS2] <mark class="highlight">God</mark> of War 2 - Dublado e Legendado [V1.1]</a></h5>
<span class="smalltext">Maio 21, 2021 por <strong><a href="x" title="Ver o perfil de Sonderhen">Sonderhen</a></strong></span></div></div>
<div class="windowbg"><h5><a href="b">Lixeira</a> / <a href="https://x/index.php?topic=5.0">FLOOD - [PS2] God of War 2</a></h5><strong><a href="y" title="perfil">Fulano</a></strong></div>
<div class="windowbg"><h5><a href="b">Lançamentos</a> / <a href="https://x/index.php?topic=7.0">[PS3] God of War HD Collection</a></h5><strong><a href="y" title="perfil">Beltrano</a></strong></div>"""


def baixar_banco(url, destino, progresso):
    destino.write_bytes(c.pagina_do_pobre_offline(ITENS))


def test_acha_os_patches_e_diz_se_encaixam(tmp_path):
    gow2 = InfoISO(Path("God of War II.iso"), 8533671936, "SLUS-21374", "SLUS_213.74", "GOW2", "PS2")
    pedidos = []
    r = c.procurar("God of War II", gow2, tmp_path, onde=c.ONDES, crc32="E271930D", baixar=baixar_banco,
                   obter=lambda url: pedidos.append(url) or FORUM)
    assert r.escondidos == 1                                                   # a "ISO traduzida" não aparece
    primeiro = r.achados[0]
    assert primeiro.onde == "PO.B.R.E" and primeiro.encaixa == "✓ encaixa: a impressão CRC32 é a da sua ISO"
    assert primeiro.traz == ["textos", "dublagem"] and primeiro.formato == "xdelta3" and primeiro.regiao == "EUA"
    assert primeiro.pagina == "https://romhackers.org/traducoes/console/playstation-2/god-of-war-ii-traduzido-e-" \
                              "dublado-bw/"
    forum = [a for a in r.achados if a.onde == "romhacking.net.br"]
    assert [a.titulo for a in forum] == ["[PS2] God of War 2 - Dublado e Legendado [V1.1]"]   # sem lixeira/PS3
    assert forum[0].versao == "1.1" and forum[0].grupo == "Sonderhen" and "PHPSESSID" not in forum[0].pagina
    assert "God of War" not in [a.titulo for a in r.achados]                   # God of War (1) é outro jogo
    assert set(r.no_navegador) == {"Romhacking.net", "itch.io"} and "God+of+War+II" in pedidos[0]
    # outra impressão (outra versão): não encaixa; e o filtro "Só dublagem"
    r = c.procurar("God of War II", gow2, tmp_path, crc32="00000000", quer=c.QUER[1], baixar=baixar_banco,
                   obter=lambda url: FORUM)
    pobre = next(a for a in r.achados if a.onde == "PO.B.R.E")
    assert pobre.encaixa.startswith("⚠ impressão diferente") and r.achados[-1] is pobre   # o que não encaixa no fim
    assert all("dublagem" in a.traz for a in r.achados)


def test_versao_e_regiao_e_o_que_nao_tem(tmp_path):
    dmc = InfoISO(Path("DMC3.iso"), 1, "SLUS-20964", "", "", "PS2")
    r = c.procurar("Devil May Cry 3", dmc, tmp_path, onde=c.ONDES[:1], baixar=baixar_banco)
    assert r.achados[0].encaixa == "⚠ é para SLES-54186: outra versão (não encaixa)"
    burnout = InfoISO(Path("Burnout 3.iso"), 1, "SLUS-21050", "", "", "PS2")
    r = c.procurar("Burnout 3 Takedown", burnout, tmp_path, onde=c.ONDES[:1], baixar=baixar_banco)
    assert r.achados == [] and r.escondidos == 0
    ff7 = InfoISO(Path("FF7.bin"), 1, "SCUS-94163", "", "", "PS1")
    r = c.procurar("Final Fantasy VII", ff7, tmp_path, onde=c.ONDES[:1], baixar=baixar_banco)
    assert r.achados[0].encaixa == "✓ encaixa: o mesmo código do disco"       # PS1 vem da outra pasta


def test_nome_do_jogo_e_parecido():
    info = InfoISO(Path("x.iso"), 1, "SLUS-21050", "", "BURNOUT_3", "PS2")
    assert c.nome_do_jogo(info, "SLUS_210.50.Burnout 3 - Takedown PT-BR") == "Burnout 3 - Takedown"
    assert c.nome_do_jogo(info, "", "Burnout 3 - Takedown (USA)") == "Burnout 3 - Takedown"
    assert c.nome_do_jogo(info) == "Burnout 3"
    assert c.parecido("God of War II", "God of War 2 - Dublado") >= 80
    assert c.parecido("God of War II", "God of War") <= 40                   # o número muda o jogo


def test_todos_os_consoles(tmp_path):
    """A busca vale para todos os consoles do submenu: o banco do PO.B.R.E tem PSP, GameCube, Wii, NES, SNES, N64,
    GBA, GB/GBC, DS e PC; o fórum filtra pelo prefixo do console ([PSP], [SNES], [Switch]...); o código do PSP
    (ULUS-10041) encaixa como o do PS2; a lista antiga (só PS1/PS2) é baixada de novo."""
    import json
    itens = [{"arquivo": "playstation-portable/meu-jogo-psp.md", "plataforma": "portatil", "title": " Meu Jogo Portatil",
              "game_title": "Meu Jogo Portatil", "patch_type": "xdelta3", "patch_progress": "Textos",
              "texto": "Deve ser aplicado na ISO americana (ULUS-10041)."},
             {"arquivo": "super-nes/meu-jogo-snes.md", "title": " Meu Jogo de Aventura", "game_title":
              "Meu Jogo de Aventura", "patch_type": "IPS", "patch_progress": "Textos", "texto": "ROM americana"}]
    (tmp_path / "pobre_traducoes.json").write_text(json.dumps({"PS2": [], "PS1": []}), encoding="utf-8")
    baixou = []

    def baixar(url, destino, progresso):
        baixou.append(url)
        destino.write_bytes(c.pagina_do_pobre_offline(itens))
    psp = InfoISO(Path("Meu Jogo.iso"), 1, "ULUS-10041", "", "Meu Jogo Portatil", "PSP")
    r = c.procurar("Meu Jogo Portatil", psp, tmp_path, onde=c.ONDES[:1], baixar=baixar)
    assert baixou and r.achados[0].encaixa == "✓ encaixa: o mesmo código do disco"
    assert r.achados[0].pagina.endswith("/portatil/playstation-portable/meu-jogo-psp/")
    snes = InfoISO(Path("Meu Jogo (USA).sfc"), 1, "", "", "MEU JOGO DE AVENTURA", "SNES")
    r = c.procurar("Meu Jogo de Aventura", snes, tmp_path, onde=c.ONDES[:1], baixar=baixar)
    assert [a.formato for a in r.achados] == ["IPS"] and len(baixou) == 1          # a lista nova ficou guardada
    forum = ('<div class="windowbg"><h5><a href="https://x/index.php?board=3.0">Lançamentos</a> / <a href="https://x/'
             'index.php?topic=9.0">[Switch] Meu Jogo do Switch - Tradução PT-BR</a></h5><strong><a href="y" title="p">'
             'Grupo</a></strong></div><div class="windowbg"><h5><a href="https://x/index.php?board=3.0">Lançamentos'
             '</a> / <a href="https://x/index.php?topic=8.0">[PS2] Meu Jogo do Switch</a></h5><strong><a href="y" '
             'title="p">Outro</a></strong></div>')
    r = c.procurar("Meu Jogo do Switch", None, tmp_path, onde=c.ONDES[1:2], sistema="Switch", obter=lambda url: forum)
    assert [a.titulo for a in r.achados] == ["[Switch] Meu Jogo do Switch - Tradução PT-BR"]
