"""O elenco por obra: as vozes do XTTS-v2 com as variantes (grave, aguda, jovem), a regra de ninguém repetir a voz
de outro na mesma cena, o elenco guardado por motor (Gemini e XTTS-v2) e a voz por personagem no XTTS-v2 pelo
roteiro (sem o Gemini)."""
import logging
from pathlib import Path
from types import SimpleNamespace

from jellyfin_tools import personagens as ps
from jellyfin_tools import voz_local as vl

P = ps.Personagem


def test_catalogo_do_xtts_com_as_variantes():
    c = ps.catalogo_xtts()
    homens, mulheres = vl.vozes_por_genero("masculina"), vl.vozes_por_genero("feminina")
    assert (len(homens), len(mulheres)) == (26, 31)
    assert len(c.masculinas) == 3 * 26 and len(c.femininas) == 3 * 31          # prontas + agudas + graves
    assert c.masculinas[:26] == tuple(homens) and c.chave == "vozes_xtts" and c.padrao == vl.VOZ_PADRAO
    assert c.por_idade[("f", "jovem")][0] == f"{mulheres[0]} · jovem" and c.por_idade[("m", "idoso")][0].endswith(
        " · grave")
    assert c.valida("Ana Florence · jovem") and c.valida("Damien Black") and not c.valida("Charon")
    assert len(vl.vozes_por_genero("masculina", True) + vl.vozes_por_genero("feminina", True)) == 57 * 4   # 228


def test_na_mesma_cena():
    lista = [P("A", "m", falas=[0, 1]), P("B", "m", falas=[2]), P("C", "f", falas=[3])]
    tempos = {0: 0.0, 1: 10.0, 2: 50.0, 3: 400.0}
    juntos = ps.na_mesma_cena(lista, tempos)
    assert juntos == {"A": {"B"}, "B": {"A"}, "C": set()}                  # B a 40 s de A; C bem depois


def cena(n_principais, n_figurantes, inicio=0.0, genero="m", prefixo=""):
    """Personagens que falam todos perto uns dos outros (a mesma cena), e os números das falas."""
    lista, tempos, k = [], {}, int(inicio)
    for i in range(n_principais + n_figurantes):
        quantas = 10 if i < n_principais else 1
        falas = list(range(k, k + quantas))
        for j, numero in enumerate(falas):
            tempos[numero] = inicio + i * 2 + j
        lista.append(P(f"{prefixo}{'Principal' if i < n_principais else 'Figurante'} {i}", genero, falas=falas))
        k += quantas
    return lista, tempos


def test_ninguem_repete_a_voz_na_mesma_cena():
    lista, tempos = cena(3, 6)
    mapa = ps.distribuir_vozes(lista, "Damien Black", catalogo=ps.catalogo_xtts(), tempos=tempos)
    assert mapa["Principal 0"] == "Damien Black"                           # quem mais fala: a voz principal
    assert len(set(mapa.values())) == 9 and ps.repetidas_na_cena(mapa, lista, tempos) == []
    principais = {mapa[f"Principal {i}"] for i in range(3)}
    assert not principais & {mapa[f"Figurante {i}"] for i in range(3, 9)}   # figurante não usa voz de principal
    antes = ps.distribuir_vozes(lista, "Damien Black", catalogo=ps.catalogo_xtts())   # sem os tempos: como antes
    assert {antes[f"Figurante {i}"] for i in range(3, 9)} == {"Damien Black"}


def test_quando_as_vozes_acabam_repete_com_quem_nao_esta_na_cena():
    tres = ps.Catalogo(("H1", "H2", "H3"), ("M1",), {}, "H1")
    cena1, t1 = cena(3, 0, inicio=0.0, prefixo="a")
    cena2, t2 = cena(2, 1, inicio=1000.0, prefixo="b")
    lista = sorted(cena1 + cena2, key=lambda p: -len(p.falas))
    tempos = {**t1, **t2}
    mapa = ps.distribuir_vozes(lista, "H1", catalogo=tres, tempos=tempos)
    assert set(mapa.values()) == {"H1", "H2", "H3"} and ps.repetidas_na_cena(mapa, lista, tempos) == []


def test_idade_e_voz_pessoal_no_xtts():
    lista = [P("Menina", "f", falas=list(range(10)), idade="crianca"), P("Avô", "m", falas=list(range(10, 18)),
                                                                      idade="idoso"),
             P("Pai", "m", falas=list(range(18, 24)))]
    tempos = {k: float(k) for k in range(24)}
    mapa = ps.distribuir_vozes(lista, "Damien Black", catalogo=ps.catalogo_xtts(), tempos=tempos)
    assert mapa["Menina"].endswith(" · jovem") and mapa["Avô"].endswith(" · grave")
    assert mapa["Pai"] == "Damien Black"                                   # a principal não vai para criança/idoso
    pessoal = ps.distribuir_vozes(lista, "imp:izael", catalogo=ps.catalogo_xtts(), tempos=tempos)
    assert pessoal["Menina"] == "imp:izael"                                # a SUA voz: para quem mais fala


def test_elenco_guarda_as_vozes_de_cada_motor(tmp_path):
    arquivo = tmp_path / "Série.json"
    lista = [P("Ana", "f", falas=[1])]
    ps.salvar_elenco(arquivo, lista, {"Ana": "Kore"})                      # Gemini
    ps.salvar_elenco(arquivo, lista, {"Ana": "Ana Florence · jovem"}, "vozes_xtts")
    elenco = ps.carregar_elenco(arquivo)
    assert elenco["vozes"] == {"Ana": "Kore"} and elenco["vozes_xtts"] == {"Ana": "Ana Florence · jovem"}
    assert [p["rotulo"] for p in elenco["pessoas"]] == ["Ana"]


def test_personagens_do_roteiro():
    achado = SimpleNamespace(falas={3: "Tina", 1: "Tina", 2: "Bob"}, generos={"Tina": "f", "Bob": "m"})
    lista = ps.do_roteiro(achado)
    assert [(p.rotulo, p.genero, p.falas) for p in lista] == [("Tina", "f", [1, 3]), ("Bob", "m", [2])]


def test_xtts_com_voz_por_personagem_pelo_roteiro(tmp_path, monkeypatch):
    """XTTS-v2 sem a chave do Gemini: quem fala vem do roteiro, as vozes são as do XTTS-v2 e a série guarda o
    elenco em "vozes_xtts" (o próximo episódio repete as mesmas)."""
    from jellyfin_tools.traducao import Fala
    from videoscraper import automacao

    def OpcoesJellyfin(**campos):                      # as opções que a voz por personagem lê
        return SimpleNamespace(**{"voz_local": "", "voz_gemini": "Charon", "usar_roteiro": True,
                                  "limite_figurante": 20, "figurantes_piper": False, **campos})
    monkeypatch.setattr(automacao, "pasta_dublagem", lambda: tmp_path)
    falas = [(Fala(f"00:00:{s:02d},000 --> 00:00:{s + 1:02d},000", f"fala {s}"), f"fala {s}") for s in range(0, 40, 2)]
    monkeypatch.setattr(automacao, "falas_da_legenda", lambda legenda: falas)
    quem = {k: ("Tina" if k % 2 else "Bob") for k in range(18)} | {18: "Guarda", 19: "Garçom"}
    achado = SimpleNamespace(falas=quem, generos={"Tina": "f", "Bob": "m", "Guarda": "m", "Garçom": "m"}, total=20,
                             cobertura=1.0)
    monkeypatch.setattr(automacao, "pelo_roteiro", lambda o, video, falas: achado)
    o = OpcoesJellyfin(motor_voz="XTTS-v2 (grátis, no PC)", voz_por_personagem=True, chave_gemini="")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert automacao.personagem_por_voz(o) and automacao.voz_principal(o) == "Damien Black"
    item = SimpleNamespace(video=tmp_path / "S01E01.mkv", legenda=tmp_path / "S01E01.srt", serie="Minha Série")
    vozes = automacao.vozes_automaticas(o, item, logging.getLogger("teste"))
    por_quem = {quem[k]: v for k, v in vozes.items()}
    assert por_quem["Bob"] == "Damien Black" and vl.perfil_da_voz(por_quem["Tina"]).startswith("feminina")
    assert len({por_quem["Bob"], por_quem["Guarda"], por_quem["Garçom"]}) == 3       # mesma cena: vozes diferentes
    elenco = ps.carregar_elenco(automacao.arquivo_elenco("Minha Série"))
    assert elenco["vozes_xtts"]["Tina"] == por_quem["Tina"] and elenco["vozes"] == {}
    por_quem["Tina"] = "Ana Florence · jovem"                              # trocada na tabela: vale para a série
    ps.salvar_elenco(automacao.arquivo_elenco("Minha Série"), ps.do_roteiro(achado), por_quem, "vozes_xtts")
    item.video = tmp_path / "S01E02.mkv"
    de_novo = automacao.vozes_automaticas(o, item, logging.getLogger("teste"))
    assert {quem[k]: v for k, v in de_novo.items()}["Tina"] == "Ana Florence · jovem"
    sem_roteiro = OpcoesJellyfin(motor_voz="XTTS-v2 (grátis, no PC)", voz_por_personagem=True, chave_gemini="")
    monkeypatch.setattr(automacao, "pelo_roteiro", lambda o, video, falas: None)
    assert automacao.vozes_automaticas(sem_roteiro, item, logging.getLogger("teste")) is None   # uma voz por gênero
    assert not automacao.personagem_por_voz(OpcoesJellyfin(motor_voz="Piper (grátis, no PC)", voz_por_personagem=True))
    assert Path(automacao.arquivo_elenco("Minha Série")).is_file()
