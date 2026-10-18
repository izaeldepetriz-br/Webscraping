"""Teste de verdade do patch de jogos num Windows (o mesmo código do Maestro): baixa o xdelta3 oficial (conferindo
a impressão digital do download), cria o .xdelta de uma "tradução", aplica numa cópia da ISO, recusa a ISO de
outra versão e aplica um .ppf. As ISOs são de mentira (geradas pelo teste): nenhum jogo de verdade.

Uso: python testar_patch_jogo.py <pasta_de_trabalho>
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from jellyfin_tools import patch_jogo as pj                  # noqa: E402
from tests.test_patch_jogo import iso_de_teste, ppf          # noqa: E402

pasta = Path(sys.argv[1])
pasta.mkdir(parents=True, exist_ok=True)
ferramentas = pasta / "ferramentas"
original = iso_de_teste(pasta / "Meu Jogo.iso", setores_de_dados=20000)      # ~40 MB
conteudo = bytearray(original.read_bytes())
for onde in range(1_000_000, 40_000_000, 3_000_000):
    conteudo[onde:onde + 12] = b"TRADUZIDO PT"
modificada = pasta / "Meu Jogo PT-BR.iso"
modificada.write_bytes(bytes(conteudo))

t0 = time.time()
xdelta = pj.programa_xdelta(ferramentas)
print(f"::notice title=xdelta3::{xdelta} ({xdelta.stat().st_size} bytes) baixado e conferido em "
      f"{time.time() - t0:.1f} s", flush=True)
t0 = time.time()
patch = pj.criar_patch(original, modificada, pasta / "patch" / "Meu Jogo PT-BR.xdelta", ferramentas, "Meu Jogo PT-BR")
print(f"::notice title=Criar o patch::{patch.name}: {patch.stat().st_size} bytes em {time.time() - t0:.1f} s",
      flush=True)
esperado = pj.esperado_do_leia_me(patch)
digital = pj.impressao_digital(original)
assert esperado.confere(digital), (esperado.descrever(), digital)
t0 = time.time()
r = pj.aplicar(original, patch, pasta / "DVD" / pj.nome_para_o_opl(pj.ler_info(original), "Meu Jogo PT-BR"),
               ferramentas, digital, esperado)
assert r.destino.read_bytes() == bytes(conteudo) and r.conferido == "bateu com o leia-me"
print(f"::notice title=Aplicar o xdelta::{r.destino.name} igual à traduzida, em {time.time() - t0:.1f} s", flush=True)

outra = iso_de_teste(pasta / "Meu Jogo (Europa).iso", "SLES_512.34", semente=9, setores_de_dados=20000)
try:
    pj.aplicar(outra, patch, pasta / "DVD" / "europa.iso", ferramentas)
    raise SystemExit("o xdelta3 aplicou na ISO de outra versão")
except pj.ErroPatch as erro:
    assert "outra versão" in str(erro), erro
    print(f"::notice title=Outra versão recusada::{erro}", flush=True)

trad = pasta / "patch" / "Meu Jogo PT-BR.ppf"
trad.write_bytes(ppf(3, [(41000, b"OLA MUNDO")], original))
r = pj.aplicar(original, trad, pasta / "DVD" / "ppf.iso", ferramentas)
assert r.destino.read_bytes()[41000:41009] == b"OLA MUNDO"
print("::notice title=PPF::aplicado (com a conferência do pedaço da ISO)", flush=True)
