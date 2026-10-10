"""Tradução em lote (modo econômico): uma API de lotes FALSA guarda os pedidos e responde quando 'termina'."""
from types import SimpleNamespace as NS

from jellyfin_tools.traducao import Tradutor, ler_srt
from jellyfin_tools.traducao import Pendente
from jellyfin_tools.traducao_lote import coletar, enviar, pendentes_no_disco

from test_traducao import SRT, ClienteFalso


class LoteFalso:
    def __init__(self, cliente, falhar=()):
        self.cliente, self.falhar, self.criados, self.terminado = cliente, set(falhar), [], False

    def create(self, requests):
        self.criados.append(requests)
        return NS(id=f"msgbatch_{len(self.criados)}", processing_status="in_progress")

    def retrieve(self, codigo):
        return NS(id=codigo, processing_status="ended" if self.terminado else "in_progress")

    def results(self, codigo):
        for pedido in self.criados[-1]:
            if pedido["custom_id"] in self.falhar:
                yield NS(custom_id=pedido["custom_id"], result=NS(type="errored"))
                continue
            mensagem = ClienteFalso.create(self.cliente, **pedido["params"])
            yield NS(custom_id=pedido["custom_id"], result=NS(type="succeeded", message=mensagem))


def test_envia_espera_e_coleta(tmp_path):
    filmes = tmp_path / "Filmes"
    pendentes = []
    for nome in ("A (2001)", "B (2002)"):
        (filmes / nome).mkdir(parents=True)
        (filmes / nome / f"{nome}.en.srt").write_text(SRT, encoding="utf-8")
        pendentes.append(Pendente(filmes / nome / f"{nome}.mkv", filmes / nome / f"{nome}.en.srt",
                                  filmes / nome / f"{nome}.pt-BR.srt"))
    cliente = ClienteFalso()
    cliente.batches = LoteFalso(cliente, falhar={"a1-p0"})          # o pedido do B falha no lote
    tradutor = Tradutor(cliente=cliente)
    codigo, pedidos = enviar(pendentes, tradutor, tmp_path / "lotes")
    assert (codigo, pedidos) == ("msgbatch_1", 2) and len(pendentes_no_disco(tmp_path / "lotes")) == 1
    params = cliente.batches.criados[0][0]["params"]
    assert params["model"] == "claude-sonnet-4-6" and params["output_config"]["format"]["type"] == "json_schema"
    assert "-->" not in params["messages"][0]["content"]                       # horários nunca saem do PC
    assert not cliente.pedidos                                                 # nada no modo normal ainda

    assert coletar(pendentes_no_disco(tmp_path / "lotes")[0], tradutor) is None   # ainda processando
    cliente.batches.terminado = True
    resultados = coletar(pendentes_no_disco(tmp_path / "lotes")[0], tradutor)
    assert [r.status for r in resultados] == ["traduzida", "traduzida"]
    for p in pendentes:
        traduzida = ler_srt(p.destino.read_text(encoding="utf-8"))
        assert [f.texto for f in traduzida][0] == "PT: Hello, how are you?"
        assert [f.tempo for f in traduzida] == [f.tempo for f in ler_srt(SRT)]
    assert len(cliente.pedidos) == 2              # o A respondido no lote + o B refeito no modo normal
    assert not pendentes_no_disco(tmp_path / "lotes")                          # o lote terminou: sai do disco
    assert tradutor.tokens_entrada == 100 // 2 + 100                           # lote = metade; refeito = cheio
