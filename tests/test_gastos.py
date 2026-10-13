"""Gastos do mês nas APIs pagas: cada pedido anota o custo estimado e o teto para as tarefas pagas."""
from datetime import datetime
from types import SimpleNamespace

import pytest

from jellyfin_tools import gastos, voz_gemini
from jellyfin_tools.dublagem import ErroDublagem
from jellyfin_tools.traducao import ErroTraducao, Tradutor
from tests.test_traducao import ClienteFalso
from tests.test_voz_gemini import GeminiFalso


def test_soma_por_mes_e_servico(tmp_path):
    agora = [datetime(2026, 10, 11)]
    g = gastos.Gastos(tmp_path / "gastos.json", teto=5, agora=lambda: agora[0])
    g.registrar("Claude", 0.40)
    g.registrar("Gemini", 0.83)
    g.registrar("Gemini", 0)                                       # nada a anotar
    assert g.do_mes() == {"Claude": 0.40, "Gemini (voz)": 0.0, "Gemini (escuta)": 0.0, "Gemini": 0.83,
                          "Google TTS": 0.0} and g.total() == pytest.approx(1.23)     # "Gemini": meses antigos
    assert g.resumo() == "US$ 1.23 (Claude 0.40 · Gemini 0.83) de US$ 5.00"
    agora[0] = datetime(2026, 11, 1)                               # o mês virou: começa do zero
    assert g.total() == 0 and g.resumo() == "US$ 0.00 (nada ainda) de US$ 5.00"
    assert g.total("2026-10") == pytest.approx(1.23)                # o mês passado fica guardado
    g.conferir()
    g.registrar("Claude", 5)
    with pytest.raises(gastos.TetoAtingido, match="teto de gastos do mês"):
        g.conferir()
    (tmp_path / "gastos.json").write_text("{quebrado", encoding="utf-8")
    assert g.total() == 0                                           # arquivo estragado não trava nada


def test_sem_configurar_nao_anota_nem_bloqueia(tmp_path):
    gastos.registrar("Claude", 1.0)
    gastos.conferir()
    assert gastos.atual() is None and not list(tmp_path.iterdir())


def test_cada_pedido_ao_claude_anota_e_o_teto_para(tmp_path):
    g = gastos.configurar(tmp_path / "gastos.json")
    tradutor = Tradutor(cliente=ClienteFalso())
    tradutor.traduzir_falas(["Hello.", "Bye."])
    assert g.do_mes()["Claude"] == pytest.approx(tradutor.custo) and tradutor.custo > 0
    g.teto = tradutor.custo / 2                                     # já passou do teto: o próximo pedido não vai
    antes = tradutor.pedidos
    with pytest.raises(ErroTraducao, match="teto de gastos"):
        tradutor.traduzir_falas(["Again."])
    assert tradutor.pedidos == antes


def test_cada_pedido_de_voz_ao_gemini_anota_e_o_teto_para(tmp_path):
    g = gastos.configurar(tmp_path / "gastos.json")
    motor = voz_gemini.MotorGemini("x", "Kore", cliente=GeminiFalso(), esperar=lambda s: None)
    motor.sintetizar([("Olá, tudo bem?", tmp_path / "1.wav")])
    gasto = g.do_mes()["Gemini (voz)"]
    assert gasto > 0 and gasto == pytest.approx(voz_gemini.custo_da_fala(0.06 * len("Olá, tudo bem?")), rel=0.2)
    g.teto = gasto
    with pytest.raises(ErroDublagem, match="teto de gastos"):
        motor.sintetizar([("De novo.", tmp_path / "2.wav")])
    assert not (tmp_path / "2.wav").exists()


def test_ouvir_quem_fala_tambem_anota(tmp_path):
    g = gastos.configurar(tmp_path / "gastos.json")
    cliente = SimpleNamespace(interactions=SimpleNamespace(create=lambda **k: SimpleNamespace(output_text="{}")))
    voz_gemini.perguntar_sobre_audio(cliente, "quem fala?", b"x" * 4000 * 60, esperar=lambda s: None)   # 1 min
    assert g.do_mes()["Gemini (escuta)"] == pytest.approx(60 * voz_gemini.TOKENS_POR_SEGUNDO * voz_gemini.PRECO_OUVIR
                                                           / 1e6)


def test_custos_por_api_cota_gratis_e_chave_gratis_do_gemini(tmp_path):
    """Cada API separada (para saber onde economizar); a chave grátis do Gemini não vira gasto (só uso); a cota
    grátis do mês do Google Cloud TTS e os créditos do Claude que acabam ficam anotados com a data."""
    from jellyfin_tools import voz_cloud
    agora = [datetime(2026, 10, 13, 14, 32)]
    g = gastos.Gastos(tmp_path / "gastos.json", agora=lambda: agora[0], plano_gemini="gratis")
    antes = g.foto()
    g.registrar("Claude", 0.05)
    g.registrar("Gemini (voz)", 0.40)
    g.registrar("Gemini (escuta)", 0.16)
    custos = gastos.custos_entre(antes, g.foto())
    assert custos == {"Claude": (0.05, False), "Gemini (voz)": (0.40, True), "Gemini (escuta)": (0.16, True)}
    assert g.total() == pytest.approx(0.05)                       # o Gemini grátis não conta como gasto
    tipo = "Neural2"
    cota = voz_cloud.TIPOS[tipo][3]
    g.registrar_caracteres(tipo, cota - 10, voz_cloud.TIPOS)
    assert not g.cotas()
    antes = g.foto()
    g.registrar_caracteres(tipo, 1000, voz_cloud.TIPOS)           # passou da cota grátis AGORA
    assert g.cotas()[f"Google TTS {tipo}"] == {"situacao": "acabou", "quando": "2026-10-13T14:32"}
    assert gastos.custos_entre(antes, g.foto())["Google TTS"][1] is False      # agora é pago
    linhas = g.situacao_das_cotas(voz_cloud.TIPOS)
    assert any("cota grátis do mês ACABOU em 13/10 às 14:32" in l for l in linhas)
    assert any(l.startswith("Gemini: chave GRÁTIS") for l in linhas) and any("Whisper" in l for l in linhas)
    assert g.marcar_cota("Claude", "créditos acabaram") and not g.marcar_cota("Claude", "créditos acabaram")
    assert set(g.cotas_acabadas()) == {f"Google TTS {tipo}", "Claude"}
    assert any("os créditos ACABARAM em 13/10 às 14:32" in l for l in g.situacao_das_cotas(voz_cloud.TIPOS))
    g.marcar_cota("Gemini", "limite do dia")
    assert "Gemini" in g.cotas_acabadas()
    agora[0] = datetime(2026, 10, 14, 9, 0)                        # no dia seguinte o limite do dia voltou
    assert "Gemini" not in g.cotas_acabadas()
    g.plano_gemini = "pago"
    assert any("pago desde o 1º pedido" in l for l in g.situacao_das_cotas())


def test_modo_flex_do_gemini_custa_metade_e_volta_ao_normal_se_recusado(tmp_path):
    from types import SimpleNamespace as NS
    g = gastos.configurar(tmp_path / "gastos.json")
    pedidos = []

    class Base:
        def create(self, **k):
            pedidos.append(k.get("service_tier"))
            return NS(output_text="{}")
    cliente = voz_gemini.ClienteFlex(NS(interactions=Base(), models=None))
    voz_gemini.perguntar_sobre_audio(cliente, "quem fala?", b"x" * 4000 * 60, esperar=lambda s: None)
    assert pedidos == ["flex"]
    assert g.do_mes()["Gemini (escuta)"] == pytest.approx(
        60 * voz_gemini.TOKENS_POR_SEGUNDO * voz_gemini.PRECO_OUVIR / 1e6 * voz_gemini.DESCONTO_FLEX)
    avisos = []

    class Recusa:
        def create(self, **k):
            if "service_tier" in k:
                raise type("ClientError", (Exception,), {"code": 400})("service_tier flex is not supported")
            pedidos.append("normal")
            return NS(output_text="{}")
    cliente = voz_gemini.ClienteFlex(NS(interactions=Recusa(), models=None), avisos.append)
    voz_gemini.perguntar_sobre_audio(cliente, "quem fala?", b"x", esperar=lambda s: None)
    assert pedidos[-1] == "normal" and cliente.flex is False and "preço normal" in avisos[0]


def test_creditos_do_claude_acabaram(tmp_path):
    from jellyfin_tools import traducao
    g = gastos.configurar(tmp_path / "gastos.json")
    erro = type("BadRequestError", (Exception,), {})("Your credit balance is too low to access the Anthropic API.")
    assert "créditos da API da Anthropic acabaram" in traducao._explicar(erro)
    assert g.cotas()["Claude"]["situacao"] == "créditos acabaram"


def test_google_diz_que_a_chave_e_gratis_e_o_plano_marcado_e_pago(tmp_path):
    """O erro de limite do Google fala da camada grátis: com "Paga" marcado, o faturamento ainda não vale (aviso);
    com "Não sei", sugere "Grátis". Só vale no mesmo dia; escolher "Paga" de novo esquece."""
    agora = [datetime(2026, 10, 13, 15, 0)]
    g = gastos.configurar(tmp_path / "gastos.json", plano_gemini="pago")
    g._agora = lambda: agora[0]
    erro = type("ClientError", (Exception,), {"code": 429})(
        "429 RESOURCE_EXHAUSTED. Quota exceeded for metric: generativelanguage.googleapis.com/"
        "generate_content_free_tier_requests, limit: 15 (quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier)")
    pago = type("ClientError", (Exception,), {"code": 429})("429 RESOURCE_EXHAUSTED. Quota exceeded (Tier 1)")

    def falha(e):
        def chamar():
            raise e
        return chamar
    with pytest.raises(ErroDublagem, match="chave GRÁTIS do Gemini"):
        voz_gemini._com_tentativas(falha(erro), esperar=lambda s: None)
    assert "faturamento ainda não está ativo" in g.aviso_do_plano()
    assert any("faturamento ainda não está ativo" in l for l in g.situacao_das_cotas())
    g.plano_gemini = "?"
    assert "escolha \"Grátis\"" in g.aviso_do_plano()
    g.plano_gemini = "gratis"
    assert g.aviso_do_plano() == ""
    g.plano_gemini = "pago"
    g.esquecer_gemini_gratis()                                       # escolheu "Paga" agora: começa do zero
    assert g.aviso_do_plano() == ""
    with pytest.raises(ErroDublagem, match="limite de uso do Gemini"):
        voz_gemini._com_tentativas(falha(pago), esperar=lambda s: None)     # chave paga: o texto não fala em grátis
    assert g.aviso_do_plano() == ""
    g.anotar_gemini_gratis()
    agora[0] = datetime(2026, 10, 14, 9, 0)                           # no dia seguinte, a resposta de ontem não vale
    assert g.aviso_do_plano() == ""


def test_dia_do_google_vira_a_meia_noite_da_california():
    """O limite do dia da chave grátis volta à meia-noite da Califórnia (no Brasil, 4h ou 5h), com o horário de
    verão de lá (sem depender do tzdata, que o Windows não tem)."""
    from datetime import timezone
    utc = lambda *a: datetime(*a, tzinfo=timezone.utc)
    assert gastos.hora_do_pacifico(utc(2026, 10, 13, 14, 36)) == datetime(2026, 10, 13, 7, 36)     # PDT (UTC-7)
    assert gastos.hora_do_pacifico(utc(2026, 12, 1, 7, 59)) == datetime(2026, 11, 30, 23, 59)     # PST (UTC-8)
    assert gastos.hora_do_pacifico(utc(2026, 3, 8, 9, 59)).hour == 1                               # muda às 2h
    assert gastos.hora_do_pacifico(utc(2026, 3, 8, 10, 0)).hour == 3
    assert gastos.hora_do_pacifico(utc(2026, 11, 1, 8, 59)).hour == 1
    assert gastos.hora_do_pacifico(utc(2026, 11, 1, 9, 0)).hour == 1                               # 1h de novo
    agora = [utc(2026, 10, 13, 14, 36)]
    g = gastos.Gastos("/nao/existe.json", agora=lambda: agora[0])
    assert g.dia_do_google() == "2026-10-13" and g.virada_do_dia() == "07:00"     # 7h UTC = 4h em Brasília
    agora[0] = utc(2026, 10, 14, 6, 59)                                            # 3h59 em Brasília: ainda é dia 13
    assert g.dia_do_google() == "2026-10-13"
    agora[0] = utc(2026, 10, 14, 7, 0)
    assert g.dia_do_google() == "2026-10-14"


def test_quanto_resta_hoje_na_chave_gratis_do_gemini(tmp_path):
    """O Google não diz quanto resta: o Maestro conta os pedidos do dia e guarda o limite que o Google informa na
    mensagem de limite ("quotaValue: 15"). Restam = limite - feitos; quando o do dia acaba, restam 0."""
    from datetime import timezone
    agora = [datetime(2026, 10, 13, 14, 36, tzinfo=timezone.utc)]
    g = gastos.configurar(tmp_path / "gastos.json", plano_gemini="gratis")
    g._agora = lambda: agora[0]
    assert g.uso_do_dia_gemini() == []
    erro_do_dia = type("ClientError", (Exception,), {"code": 429})(
        "429 RESOURCE_EXHAUSTED. {'details': [{'violations': [{'quotaId': 'GenerateRequestsPerMinutePerProject"
        "PerModel-FreeTier', 'quotaValue': '3'}, {'quotaId': 'GenerateRequestsPerDayPerProjectPerModel-FreeTier', "
        "'quotaDimensions': {'model': 'tts'}, 'quotaValue': '15'}]}]}")
    assert voz_gemini.limites_do_erro(erro_do_dia) == {"minuto": 3, "dia": 15}
    motor = voz_gemini.MotorGemini("x", "Kore", cliente=GeminiFalso(), esperar=lambda s: None, simultaneos=1)
    motor.sintetizar([("Olá, tudo bem?", tmp_path / "1.wav"), ("Tchau.", tmp_path / "2.wav")])
    linhas = g.uso_do_dia_gemini()
    assert linhas[0].startswith("Gemini (voz): 1 pedido(s) hoje") and "vira às" in linhas[-1]
    g.anotar_limite_gemini("voz", por_dia=15)                       # o Google disse o tamanho (num 429 por minuto)
    assert g.uso_do_dia_gemini()[0] == "Gemini (voz): 1 de 15 pedidos grátis hoje; restam ~14"
    assert g.resumo_do_dia_gemini() == ("Gemini grátis hoje: voz 1/15 (restam ~14)", None)    # painel do topo
    with pytest.raises(ErroDublagem, match="limite do dia"):
        voz_gemini._com_tentativas(lambda: (_ for _ in ()).throw(erro_do_dia), lambda s: None)
    assert g.uso_do_dia_gemini()[0] == "Gemini (voz): o limite do dia ACABOU às 14:36 (15 pedidos); restam 0"
    assert "Gemini" in g.cotas_acabadas()
    assert g.resumo_do_dia_gemini() == ("Gemini grátis hoje: voz ACABOU (volta às 07:00)", False)
    agora[0] = datetime(2026, 10, 14, 7, 0, tzinfo=timezone.utc)   # virou o dia do Google: tudo de novo
    assert g.uso_do_dia_gemini()[0] == "Gemini (voz): 0 de 15 pedidos grátis hoje; restam ~15"
    assert "Gemini" not in g.cotas_acabadas()
    voz_gemini.perguntar_sobre_audio(SimpleNamespace(interactions=SimpleNamespace(
        create=lambda **k: SimpleNamespace(output_text="{}"))), "quem fala?", b"x", esperar=lambda s: None)
    motor.sintetizar([("De novo.", tmp_path / "3.wav")])
    assert g.uso_do_dia_gemini()[:2] == ["Gemini (voz): 1 de 15 pedidos grátis hoje; restam ~14",
                                          "Gemini (escuta do original): 1 pedido(s) hoje (o limite do dia aparece "
                                          "aqui quando o Google avisar pela 1ª vez)"]
    g.plano_gemini = "pago"
    assert g.uso_do_dia_gemini() == [] and g.resumo_do_dia_gemini() is None     # chave paga: sem limite grátis
