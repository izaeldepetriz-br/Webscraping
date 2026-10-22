"""Testes de verdade da aba 🎮 Jogos num Windows, com a internet (o mesmo código do Maestro):

  sites   — o banco do Redump (a impressão digital do disco) e a busca de patches na comunidade (o banco público do
            PO.B.R.E e o fórum romhacking.net.br). Roda toda semana: se um site mudar o jeito da página, o teste
            avisa antes de quem usa o Maestro perceber.
  dublar  — o modo "Traduzir e dublar (no PC)" do começo ao fim: analisa uma ISO de mentira, tira as falas, o Piper
            de verdade fala as traduções, grava no formato do PS2 (VAG) e no tamanho da original e monta a ISO em
            português. Nenhum jogo de verdade.
  instalar — o modo "📦 Instalar a tradução" com os caminhos do Windows: no PC, por cima da pasta do jogo (com espaço
            e acento no nome, arquivo "somente leitura" e o .zip de programa antigo com "\\"), Desfazer e o pacote;
            no Switch, o mod na pasta de mods do emulador (em AppData) e no cartão SD; e o emulador achado em
            Arquivos de Programas. Nenhum jogo de verdade.
  meus     — "🔎 Meus jogos" com os caminhos do Windows: a pasta de jogos (com espaço e acento), o padrão do OPL e a
            biblioteca da Steam (appmanifest); da 2ª vez, só os arquivos novos. Nenhum jogo de verdade.

Uso: python testar_jogos_ao_vivo.py sites|dublar|instalar|meus <pasta_de_trabalho>
"""
import os
import stat
import sys
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from jellyfin_tools import patch_jogo as pj                  # noqa: E402

# o disco do teste do Burnout 3 (EUA): a impressão digital de uma cópia do disco original
BURNOUT3 = {"md5": "53D793704AC0A263546D05893804D0CC", "crc32": "70F0E224"}


ESPERA_SITE = 60                         # antes da 2ª tentativa num site que não respondeu


def avisar(titulo: str, texto: str) -> None:
    print(f"::notice title={titulo}::{texto}", flush=True)


def sites(pasta: Path) -> None:
    from jellyfin_tools import comunidade as cm
    from jellyfin_tools import redump
    t0 = time.time()
    indice = redump.indice("PS2", pasta / "redump")
    nomes = set(indice["md5"].values())
    assert len(indice["md5"]) > 5000, f"o Redump veio com só {len(indice['md5'])} discos de PS2"
    assert any(n.startswith("Burnout 3 - Takedown (USA)") for n in nomes), "o Burnout 3 (EUA) sumiu do Redump"
    nome = redump.procurar(indice, BURNOUT3["md5"], BURNOUT3["crc32"], 0)
    avisar("Redump", f"{len(indice['md5'])} discos de PS2 em {time.time() - t0:.1f} s; a cópia do Burnout 3 do teste: "
                     f"{nome or 'não é igual à do banco (outra versão ou cópia com erro)'}")

    gow2 = pj.InfoISO(Path("God of War II.iso"), 8533671936, "SLUS-21374", "SLUS_213.74", "GOW2", "PS2")
    t0 = time.time()
    r = cm.procurar("God of War II", gow2, pasta / "comunidade", onde=cm.ONDES)
    if r.avisos:                        # um site fora do ar por um instante não é a página que mudou: mais uma vez
        avisar("Nova tentativa", f"{'; '.join(r.avisos)} · tentando de novo em {ESPERA_SITE} s")
        time.sleep(ESPERA_SITE)
        r = cm.procurar("God of War II", gow2, pasta / "comunidade", onde=cm.ONDES)
    assert not r.avisos, r.avisos
    pobre = [a for a in r.achados if a.onde == "PO.B.R.E"]
    forum = [a for a in r.achados if a.onde == "romhacking.net.br"]
    assert pobre and all("God of War" in a.titulo for a in pobre), [a.titulo for a in pobre]
    assert any(a.formato and a.traz and a.pagina.startswith("https://romhackers.org/") for a in pobre), pobre[:2]
    assert forum and all(a.pagina.startswith("https://") and "PHPSESSID" not in a.pagina for a in forum), forum[:2]
    assert set(r.no_navegador) == {"Romhacking.net", "itch.io"}
    avisar("Procurar na comunidade", f"God of War II: {len(pobre)} no PO.B.R.E, {len(forum)} no fórum, "
                                     f"{r.escondidos} ISO(s) inteira(s) escondida(s), em {time.time() - t0:.1f} s; "
                                     f"o 1º: {r.achados[0].titulo} · {r.achados[0].formato} · "
                                     f"{', '.join(r.achados[0].traz)}")
    burnout = pj.InfoISO(Path("Burnout 3.iso"), 0, "SLUS-21050", "SLUS_210.50", "BURNOUT3", "PS2")
    r = cm.procurar("Burnout 3 Takedown", burnout, pasta / "comunidade", onde=cm.ONDES[:2])
    avisar("Burnout 3 na comunidade", f"{len(r.achados)} patch(es): " +
           ("; ".join(f"{a.onde}: {a.titulo}" for a in r.achados[:5]) or "nenhum (dá para traduzir e dublar no PC)"))


def dublar(pasta: Path) -> None:
    from jellyfin_tools import audio_jogo as aj
    from jellyfin_tools import dublar_jogo as dj
    from jellyfin_tools import iso_jogo as ij
    from jellyfin_tools.dublagem import MotorPiper, localizar_ffmpeg, preparar_piper, preparar_voz
    from tests.test_iso_jogo import disco
    iso, _ = disco(pasta)
    original = iso.read_bytes()
    t0 = time.time()
    analise = ij.analisar(iso)
    extraida = pasta / "Burnout 3 - Takedown - extraído"
    assert ij.extrair(analise, extraida) == 4
    falas = sorted(dj.achar_falas(extraida), key=lambda f: f.relativo)
    assert len(falas) == 4 and all(f.formato is not None for f in falas), [(f.relativo, f.erro) for f in falas]
    for fala, texto in zip(falas, ("Abra o portão!", "Obrigado, a floresta está segura agora.", "Cuidado!",
                                   "Novo jogo")):
        fala.traducao = texto
    motor = MotorPiper(preparar_piper(pasta / "piper"), preparar_voz("faber", pasta / "vozes"))
    saida = pasta / "Burnout 3 - Takedown - PT-BR"
    r = dj.dublar(falas, motor, saida, localizar_ffmpeg())
    assert r.dubladas == 4 and not r.erros, (r.dubladas, r.erros)
    for fala in falas:
        dublada = saida / "audio_ptbr" / fala.relativo
        assert dublada.stat().st_size == fala.arquivo.stat().st_size, fala.relativo
        som, _ = aj.ler_som(dublada)
        assert len(som) and float(abs(som).max()) > 0.05, f"{fala.relativo} ficou mudo"
    nova = saida / "SLUS_210.50.Burnout 3 - Takedown PT-BR.iso"
    m = ij.montar(iso, extraida, saida / "audio_ptbr", nova)
    assert m.trocadas == 4 and not m.puladas, (m.trocadas, m.puladas)
    assert iso.read_bytes() == original and nova.stat().st_size == len(original) and nova.read_bytes() != original
    assert pj.ler_info(nova).id_jogo == "SLUS-21050"
    arquivos = dj.entregar(None, falas, saida)
    avisar("Dublar um jogo no PC", f"4 falas dubladas pelo Piper no formato VAG e no tamanho da original, ISO em "
                                   f"português montada ({nova.stat().st_size} bytes, igual à original) em "
                                   f"{time.time() - t0:.1f} s; entregues: {', '.join(a.name for a in arquivos)}")


def instalar(pasta: Path) -> None:
    from jellyfin_tools import consoles as cs
    from jellyfin_tools import instalar_traducao as it
    assert sys.platform == "win32", "este teste é para o Windows"
    t0 = time.time()
    registro = pasta / "AppData" / "Roaming" / "Maestro" / "traducoes_instaladas.json"
    # PC: a pasta do jogo com espaço e acento, e uma fala "somente leitura" (como alguns instaladores deixam)
    jogo = pasta / "Program Files (x86)" / "Jogos" / "Meu Jogo Ação"
    (jogo / "Data" / "Sound").mkdir(parents=True)
    (jogo / "Jogo.exe").write_bytes(b"MZ")
    fala = jogo / "Data" / "Sound" / "fala 01.ogg"
    fala.write_bytes(b"ORIGINAL")
    os.chmod(fala, stat.S_IREAD)
    assert not os.access(fala, os.W_OK)
    traducao = pasta / "Downloads" / "Meu Jogo Ação - Tradução PT-BR v1.0.zip"
    traducao.parent.mkdir(parents=True)
    with zipfile.ZipFile(traducao, "w") as z:
        for nome, dados in (("Tradução PT-BR\\Data\\Sound\\fala 01.ogg", b"DUBLADA"),
                            ("Tradução PT-BR\\Data\\textos_ptbr.json", '{"oi": "olá"}'.encode()),
                            ("__MACOSX/Tradução PT-BR/._fala 01.ogg", b"x"), ("Tradução PT-BR/LEIA-ME.txt",
                                                                           "Créditos: Grupo Exemplo".encode())):
            info = zipfile.ZipInfo("x")
            info.filename = nome                    # como os programas antigos do Windows gravam (com "\\")
            z.writestr(info, dados)
    pacote = it.ler_pacote_pc(traducao, jogo)
    assert pacote.raiz == "Tradução PT-BR/" and len(pacote.arquivos) == 2, (pacote.raiz, list(pacote.arquivos))
    feito = it.instalar(pacote, jogo, "PC")
    it.registrar(registro, feito)
    assert fala.read_bytes() == b"DUBLADA" and (jogo / "Data" / "textos_ptbr.json").is_file()
    assert (Path(feito.copia) / "Data" / "Sound" / "fala 01.ogg").read_bytes() == b"ORIGINAL"
    lista = it.carregar(registro)
    assert lista[0].destino == str(jogo) and "\\" in lista[0].destino, lista[0].destino
    it.desfazer(lista[0])
    it.esquecer(registro, lista[0])
    assert fala.read_bytes() == b"ORIGINAL" and not os.access(fala, os.W_OK), "o original não voltou como era"
    assert not (jogo / it.COPIA_SEGURANCA).exists() and not (jogo / "Data" / "textos_ptbr.json").exists()
    assert sorted(p.name for p in jogo.rglob("*")) == ["Data", "Jogo.exe", "Sound", "fala 01.ogg"]
    # o pacote da sua tradução: só o que mudou, com "/" dentro do .zip (abre em qualquer programa)
    copia = pasta / "Meu Jogo Ação (traduzido)"
    (copia / "Data" / "Sound").mkdir(parents=True)
    (copia / "Jogo.exe").write_bytes(b"MZ")
    (copia / "Data" / "Sound" / "fala 01.ogg").write_bytes(b"DUBLADA")
    os.chmod(fala, stat.S_IREAD | stat.S_IWRITE)
    with zipfile.ZipFile(it.criar_pacote(copia, pasta / "Meu Jogo PT-BR.zip", jogo, "Meu Jogo PT-BR v1.0")) as z:
        assert sorted(z.namelist()) == ["Data/Sound/fala 01.ogg", "LEIA-ME.txt"], z.namelist()
    # Switch: o mod na pasta de mods do Ryujinx (em AppData) e na raiz do cartão SD
    tid = "0100ABCD12340000"
    mod = pasta / "Downloads" / f"Meu Jogo PT-BR [{tid}].zip"
    with zipfile.ZipFile(mod, "w") as z:
        z.writestr("romfs/Message/Main.msbt", b"OLA")
        z.writestr("romfs/Font/fonte.bfttf", b"F" * 100)
    pacote = it.ler_mod(mod)
    assert pacote.title_id == tid and pacote.partes == ["romfs"], (pacote.title_id, pacote.partes)
    mods = pasta / "AppData" / "Roaming" / "Ryujinx" / "mods" / "contents"
    mods.mkdir(parents=True)
    destino = it.destino_do_mod(pacote, it.EMULADOR, mods)
    feito = it.instalar(pacote, destino, "SWITCH")
    assert (destino / "romfs" / "Message" / "Main.msbt").read_bytes() == b"OLA"
    it.desfazer(feito)
    assert not (mods / tid).exists() and mods.is_dir()
    sd = pasta / "SD"
    sd.mkdir()
    destino = it.destino_do_mod(pacote, it.SD, sd)
    assert destino == sd / "atmosphere" / "contents" / tid
    it.desfazer(it.instalar(pacote, destino, "SWITCH"))
    assert not (sd / "atmosphere").exists() and sd.is_dir()
    # o emulador em Arquivos de Programas (o PPSSPP do PSP)
    programas = pasta / "Program Files"
    (programas / "PPSSPP").mkdir(parents=True)
    (programas / "PPSSPP" / "PPSSPPWindows64.exe").write_bytes(b"MZ")
    os.environ["ProgramFiles"] = str(programas)
    achado = cs.achar_emulador("PSP")
    assert achado == programas / "PPSSPP" / "PPSSPPWindows64.exe", achado
    avisar("Instalar a tradução no Windows", f"PC: .zip com \\ e lixo do Mac, arquivo somente leitura trocado e "
                                             f"devolvido; Switch: mod no AppData e no SD; PPSSPP achado em "
                                             f"{achado.parent.parent.name}; em {time.time() - t0:.1f} s")


def meus(pasta: Path) -> None:
    from jellyfin_tools import meus_jogos as mj
    from tests.test_meus_jogos import biblioteca, steam
    assert sys.platform == "win32", "este teste é para o Windows"
    t0 = time.time()
    raiz = pasta / "Meus Jogos Ação"
    jogos = biblioteca(raiz)
    comum = steam(raiz)
    achados, lidos, ignorados = mj.varrer([jogos, comum])
    por_titulo = {j.titulo: j for j in achados}
    assert len(achados) == 8 and lidos == 8, (len(achados), lidos, sorted(por_titulo))
    assert por_titulo["Aventura no Castelo"].codigo == "SLUS-20946"            # (o nome do OPL: SLUS_209.46.Nome.iso)
    pc = por_titulo["Meu Jogo Indie"]
    assert pc.caminho == str(comum / "Meu Jogo Indie") and "\\" in pc.caminho, pc.caminho
    arquivo = pasta / "AppData" / "Roaming" / "Maestro" / "meus_jogos.json"
    mj.salvar(arquivo, achados + ignorados)
    _, lidos, _ = mj.varrer([jogos, comum], mj.carregar(arquivo))
    assert lidos == 0, lidos                                                   # da 2ª vez, nada é aberto
    contagem = mj.por_pasta(achados, [jogos, comum])
    avisar("Meus jogos no Windows", f"{len(achados)} jogos ({contagem[str(jogos)][1]}; Steam: "
                                    f"{contagem[str(comum)][1]}); da 2ª vez nada aberto; em {time.time() - t0:.1f} s")


if __name__ == "__main__":
    qual, pasta = sys.argv[1], Path(sys.argv[2])
    pasta.mkdir(parents=True, exist_ok=True)
    {"sites": sites, "dublar": dublar, "instalar": instalar, "meus": meus}[qual](pasta)
