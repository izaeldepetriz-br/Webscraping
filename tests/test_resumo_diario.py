"""Resumo do dia no Discord/Telegram."""
from datetime import datetime

from jellyfin_tools.resumo_diario import ResumoDiario, mensagem


def test_soma_no_dia_e_manda_uma_vez_depois_da_hora(tmp_path):
    r = ResumoDiario(tmp_path / "resumo.json")
    manha, noite = datetime(2026, 10, 10, 9), datetime(2026, 10, 10, 21, 5)
    r.registrar("organizados", 3, manha)
    r.registrar("traduzidas", 2, manha)
    r.registrar("organizados", 1, manha)
    r.registrar("item-que-nao-existe", 5, manha)                 # ignorado
    r.registrar("dublados", 0, manha)                            # zero não aparece
    assert r.para_enviar(21, manha) is None                       # ainda não deu a hora
    assert r.para_enviar(21, noite) == {"organizados": 4, "traduzidas": 2}
    assert r.para_enviar(21, datetime(2026, 10, 10, 23)) is None  # uma vez por dia
    r.registrar("baixados", 1, datetime(2026, 10, 11, 8))         # dia novo começa do zero
    assert r.para_enviar(21, datetime(2026, 10, 11, 21)) == {"baixados": 1}
    assert r.para_enviar(21, datetime(2026, 10, 12, 22)) is None  # dia parado: nada a mandar


def test_mensagem():
    discord, telegram = mensagem({"canais_fora": 1, "organizados": 4}, datetime(2026, 10, 10, 21))
    assert discord.splitlines() == ["\U0001F4CB **Resumo do dia 10/10 no Maestro**",
                                    "• 4 filme(s)/episódio(s) organizado(s)", "• 1 canal(is) ao vivo fora do ar"]
    assert "<b>Resumo do dia 10/10 no Maestro</b>" in telegram
