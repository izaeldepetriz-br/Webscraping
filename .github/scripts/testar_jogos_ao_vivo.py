"""Testes de verdade da aba 🎮 Jogos num Windows, com a internet (o mesmo código do Maestro):

  sites   — o banco do Redump (a impressão digital do disco) e a busca de patches na comunidade (o banco público do
            PO.B.R.E e o fórum romhacking.net.br). Roda toda semana: se um site mudar o jeito da página, o teste
            avisa antes de quem usa o Maestro perceber.
  dublar  — o modo "Traduzir e dublar (no PC)" do começo ao fim: analisa uma ISO de mentira, tira as falas, o Piper
            de verdade fala as traduções, grava no formato do PS2 (VAG) e no tamanho da original e monta a ISO em
            português. Nenhum jogo de verdade.

Uso: python testar_jogos_ao_vivo.py sites|dublar <pasta_de_trabalho>
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from jellyfin_tools import patch_jogo as pj                  # noqa: E402

# o disco do teste do Burnout 3 (EUA): a impressão digital de uma cópia do disco original
BURNOUT3 = {"md5": "53D793704AC0A263546D05893804D0CC", "crc32": "70F0E224"}


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


if __name__ == "__main__":
    qual, pasta = sys.argv[1], Path(sys.argv[2])
    pasta.mkdir(parents=True, exist_ok=True)
    {"sites": sites, "dublar": dublar}[qual](pasta)
