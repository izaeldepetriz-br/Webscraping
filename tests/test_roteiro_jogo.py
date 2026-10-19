"""O roteiro do jogo (modo "Traduzir e dublar" da aba 🎮 Jogos): ler o que a ferramenta exporta (.csv com ou sem
cabeçalho, .tsv, .txt, .json), traduzir sem perder os códigos ({NAME}, <br>, [cor]), respeitar o espaço de cada
texto (o Claude encurta), tirar os acentos para a fonte do jogo e gravar com as mesmas colunas. O Claude é falso:
nenhum teste gasta crédito."""
import json
from types import SimpleNamespace

from jellyfin_tools import roteiro_jogo as rj

TRADUCOES = {
    "Open the gate!": "Abra o portão!",
    "Thanks, ⟦1⟧.⟦2⟧The forest is safe now.": "Obrigado, ⟦1⟧.⟦2⟧A floresta está segura agora.",
    "Save your game?": "Você deseja salvar o seu jogo agora?",
    "⟦1⟧Ancient Key⟦2⟧ obtained.": "Você pegou a ⟦1⟧Chave Antiga⟦2⟧.",
    "Welcome to ⟦2⟧, ⟦1⟧!": "Bem-vindo a ⟦2⟧!",          # a "IA" esqueceu o ⟦1⟧ ({NAME})
}
CURTAS = {"Você deseja salvar o seu jogo agora?": "Salvar o jogo?"}


class ClienteJogo:
    """O papel do anthropic.Anthropic: traduz pelo dicionário (ou 'PT: ...') e encurta quando pedem."""

    def __init__(self):
        self.pedidos = []
        self.messages = self

    def create(self, **k):
        self.pedidos.append(k)
        conteudo = k["messages"][0]["content"]
        if conteudo.startswith(rj._ENCURTAR):
            itens = json.loads(conteudo[len(rj._ENCURTAR):])
            volta = [{"id": x["id"], "texto": CURTAS.get(x["texto"], x["texto"])} for x in itens]
        else:
            itens = json.loads(conteudo.split("Textos do jogo:\n", 1)[1])
            volta = [{"id": x["id"], "texto": TRADUCOES.get(x["texto"], "PT: " + x["texto"])} for x in itens]
        return SimpleNamespace(stop_reason="end_turn", usage=SimpleNamespace(input_tokens=100, output_tokens=50),
                               content=[SimpleNamespace(type="text", text=json.dumps({"falas": volta}))])


CSV = ("id;texto;audio;personagem;limite\r\n"
       "1;Open the gate!;KAEL_001.vag;Kael;\r\n"
       "2;\"Thanks, {NAME}.<br>The forest is safe now.\";KAEL_002.vag;Kael;60\r\n"
       "3;Save your game?;;;16\r\n"
       "4;[cor]Ancient Key[/cor] obtained.;;;\r\n"
       "5;Open the gate!;GUARD_01.vag;Guarda;\r\n"
       "6;Welcome to Kael, {NAME}!;;;\r\n")


def test_le_a_planilha_e_acha_as_colunas(tmp_path):
    arquivo = tmp_path / "roteiro.csv"
    arquivo.write_bytes(CSV.encode("utf-8"))
    r = rj.ler_roteiro(arquivo)
    assert r.tipo == "csv" and r.separador == ";" and r.fim_de_linha == "\r\n" and r.cabecalho[0] == "id"
    assert [e.chave for e in r.entradas] == ["1", "2", "3", "4", "5", "6"]
    assert r.entradas[1].texto == "Thanks, {NAME}.<br>The forest is safe now." and r.entradas[1].limite == 60
    assert (r.entradas[0].audio, r.entradas[0].personagem) == ("KAEL_001.vag", "Kael")
    assert r.codigos_achados()[:3] == ["{NAME}", "[cor]", "<br>"] and r.com_limite() == 2
    assert "6 textos" in r.descrever() and "{NAME}" in r.descrever()


def test_formatos_sem_cabecalho_txt_e_json(tmp_path):
    (tmp_path / "a.csv").write_text("MSG_01,Hello there\nMSG_02,\"Good, very good\"\n", encoding="utf-8")
    r = rj.ler_roteiro(tmp_path / "a.csv")
    assert [(e.chave, e.texto) for e in r.entradas] == [("MSG_01", "Hello there"), ("MSG_02", "Good, very good")]
    (tmp_path / "b.txt").write_text("Press Start, please.\nNew game\n\nLoad, or quit?\n", encoding="cp1252")
    r = rj.ler_roteiro(tmp_path / "b.txt")
    assert r.tipo == "txt" and [e.texto for e in r.entradas] == ["Press Start, please.", "New game", "",
                                                                 "Load, or quit?"]
    (tmp_path / "c.json").write_text(json.dumps({"menu_ok": "OK", "menu_back": "Back"}), encoding="utf-8")
    r = rj.ler_roteiro(tmp_path / "c.json")
    assert [(e.chave, e.texto) for e in r.entradas] == [("menu_ok", "OK"), ("menu_back", "Back")]
    (tmp_path / "d.json").write_text(json.dumps([{"key": "a", "text": "Hi", "voice": "a.wav"}]), encoding="utf-8")
    assert rj.ler_roteiro(tmp_path / "d.json").entradas[0].audio == "a.wav"


def test_proteger_e_restaurar_os_codigos():
    marcado, pecas = rj.proteger("[cor]Ancient Key[/cor] by Kael. Press X %s\\n ~r~ [Press Start]", ("Kael",))
    assert pecas == ["[cor]", "[/cor]", "%s", "\\n", "~r~", "Kael"] and "[Press Start]" in marcado   # é texto
    assert rj.restaurar("Obrigado, ⟦1⟧.⟦ 2 ⟧Fim", ["{NAME}", "<br>"]) == ("Obrigado, {NAME}.<br>Fim", [])
    texto, faltaram = rj.restaurar("Obrigado.", ["{NAME}", "<br>"])
    assert texto == "Obrigado.{NAME}<br>" and faltaram == ["{NAME}", "<br>"]     # no fim: o jogo não quebra
    assert rj.sem_acentos("Ação é útil — “sim”") == 'Acao e util - "sim"'
    assert rj.para_falar("Obrigado, {NAME}.<br>A floresta [cor]segura[/cor].") == "Obrigado. A floresta segura."


def test_traduz_com_os_codigos_o_espaco_e_a_memoria(tmp_path):
    arquivo = tmp_path / "roteiro.csv"
    arquivo.write_bytes(CSV.encode("utf-8"))
    r = rj.ler_roteiro(arquivo)
    cliente = ClienteJogo()
    tradutor = rj.TradutorJogo(cliente=cliente)
    memoria = {}
    resumo = rj.traduzir_roteiro(r, tradutor, glossario=("Kael",), memoria=memoria)
    t = {e.chave: e.traducao for e in r.entradas}
    assert t["1"] == t["5"] == "Abra o portão!"                                 # a mesma frase, uma vez só
    assert t["2"] == "Obrigado, {NAME}.<br>A floresta está segura agora."
    assert t["3"] == "Salvar o jogo?" and resumo.encurtadas == 1               # passava de 16: o Claude encurtou
    assert r.entradas[2].longa == "Você deseja salvar o seu jogo agora?" and r.entradas[2].espaco() == "✓ 14 de 16"
    assert r.entradas[0].longa == "" and r.entradas[0].espaco() == "14 letras"
    assert t["4"] == "Você pegou a [cor]Chave Antiga[/cor]."
    assert t["6"] == "Bem-vindo a Kael!{NAME}" and r.entradas[5].avisos == ["faltou {NAME} (posto no fim)"]
    assert resumo.unicas == 5 and resumo.traduzidas == 6 and resumo.sem_codigo == 1 and resumo.passaram == 0
    pedido = cliente.pedidos[0]
    textos = json.loads(pedido["messages"][0]["content"].split("Textos do jogo:\n", 1)[1])
    assert {"id": 2, "texto": "Save your game?", "max": 16} in textos             # o espaço vai junto
    assert "{NAME}" not in pedido["messages"][0]["content"] and "Kael" not in pedido["messages"][0]["content"]
    assert "jogos" in pedido["system"][0]["text"] and r.traduzidas() == 6 and r.ajustes() == 1
    # de novo: tudo da memória (nenhum pedido novo); a correção à mão vale para todas as vezes
    rj.corrigir(memoria, "Open the gate!", "Abram o portão!")
    rj.salvar_memoria(tmp_path / "memoria.json", memoria)
    memoria = rj.carregar_memoria(tmp_path / "memoria.json")
    antes = len(cliente.pedidos)
    resumo = rj.traduzir_roteiro(r, tradutor, glossario=("Kael",), memoria=memoria, tirar_acentos=True)
    assert len(cliente.pedidos) == antes and resumo.reaproveitadas == 6
    t = {e.chave: e.traducao for e in r.entradas}
    assert t["1"] == t["5"] == "Abram o portao!" and t["2"] == "Obrigado, {NAME}.<br>A floresta esta segura agora."
    assert r.entradas[2].longa == "Voce deseja salvar o seu jogo agora?"            # a memória guarda a 1ª também


def test_o_que_ainda_passa_do_espaco_fica_marcado():
    tradutor = rj.TradutorJogo(cliente=ClienteJogo())
    textos, avisos, resumo = rj.traduzir_textos(["Open the gate!"], tradutor, [8])
    assert textos == ["Abra o portão!"] and avisos == [["passou do espaço: 14 de 8 letras"]] and resumo.passaram == 1


def test_grava_com_as_mesmas_colunas(tmp_path):
    arquivo = tmp_path / "roteiro.csv"
    arquivo.write_bytes(b"\xef\xbb\xbf" + CSV.encode("utf-8"))
    r = rj.ler_roteiro(arquivo)
    rj.traduzir_roteiro(r, rj.TradutorJogo(cliente=ClienteJogo()), so=2)       # o teste: só os 2 primeiros
    assert [bool(e.traducao) for e in r.entradas] == [True, True, False, False, False, False]
    saida = rj.gravar_roteiro(r, tmp_path / "roteiro_ptbr.csv")
    dados = saida.read_bytes()
    assert dados.startswith(b"\xef\xbb\xbf") and b"\r\n" in dados
    linhas = dados[3:].decode("utf-8").split("\r\n")
    assert linhas[0] == "id;texto;audio;personagem;limite"
    assert linhas[1] == "1;Abra o portão!;KAEL_001.vag;Kael;"
    assert linhas[2] == "2;Obrigado, {NAME}.<br>A floresta está segura agora.;KAEL_002.vag;Kael;60"
    assert linhas[3] == "3;Save your game?;;;16"                               # sem tradução: como estava
    # com uma coluna de tradução no original: vai nela, e o texto original fica
    (tmp_path / "po.tsv").write_text("key\tsource\ttarget\nA\tYes\t\n", encoding="utf-8")
    r = rj.ler_roteiro(tmp_path / "po.tsv")
    r.entradas[0].traducao = "Sim"
    assert rj.gravar_roteiro(r, tmp_path / "po_ptbr.tsv").read_text(encoding="utf-8") == "key\tsource\ttarget\n" \
        "A\tYes\tSim\n"
    txt = tmp_path / "menu.txt"
    txt.write_text("New game\nQuit\n", encoding="utf-8")
    r = rj.ler_roteiro(txt)
    r.entradas[1].traducao = "Sair"
    assert rj.gravar_roteiro(r, tmp_path / "menu_ptbr.txt").read_text(encoding="utf-8") == "New game\nSair\n"


def test_gemini_flash_traduz_com_as_mesmas_regras():
    """O Gemini (chave grátis do AI Studio): as marcas e o "max" vão no pedido, o JSON volta (mesmo dentro de
    ```json), o que não voltou é pedido de novo e o que passou do espaço ele encurta."""
    from jellyfin_tools import traducao_gemini as tg

    class Interacoes:
        def __init__(self):
            self.pedidos = []

        def create(self, model, input):
            self.pedidos.append(input)
            if rj._ENCURTAR in input:
                itens = json.loads(input.split(rj._ENCURTAR + "\n", 1)[1].split("\n\nResponda")[0])
                volta = [{"id": x["id"], "texto": CURTAS.get(x["texto"], x["texto"])} for x in itens]
            else:
                itens = json.loads(input.split("Textos do jogo:\n", 1)[1].split("\n\nResponda")[0])
                volta = [{"id": x["id"], "texto": TRADUCOES.get(x["texto"], "PT: " + x["texto"])} for x in itens
                         if len(self.pedidos) > 1 or x["id"] != 1]                 # o id 1 some na 1ª vez
            return SimpleNamespace(output_text="```json\n" + json.dumps({"falas": volta}) + "\n```", usage=None)

    interacoes = Interacoes()
    tradutor = tg.TradutorGemini("", cliente=SimpleNamespace(interactions=interacoes))
    textos, avisos, resumo = rj.traduzir_textos(["Open the gate!", "Save your game?", "Thanks, {NAME}."], tradutor,
                                                [None, 16, None])
    assert textos == ["Abra o portão!", "Salvar o jogo?", "PT: Thanks, {NAME}."] and resumo.encurtadas == 1
    assert '"max": 16' in interacoes.pedidos[0] and "{NAME}" not in interacoes.pedidos[0]
    assert len(interacoes.pedidos) == 3 and tradutor.custo > 0                # 1ª, o que faltou e o encurtar
