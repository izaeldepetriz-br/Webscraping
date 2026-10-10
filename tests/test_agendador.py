"""Agendar tarefas no Agendador do Windows: o 'schtasks' é falso (os testes rodam em qualquer sistema)."""
from types import SimpleNamespace as NS

import pytest

from videoscraper import agendador


class SchtasksFalso:
    def __init__(self, saida="", codigo=0):
        self.chamadas, self.saida, self.codigo = [], saida, codigo

    def __call__(self, comando, **k):
        self.chamadas.append(comando)
        return NS(returncode=self.codigo, stdout=self.saida, stderr="ERRO: acesso negado." if self.codigo else "")


def test_monta_o_comando_do_agendador():
    c = agendador.comando_criar("--conferir-canais", "Todo dia", "6:5", exe='"C:\\Maestro\\Maestro.exe"')
    assert c == ["schtasks", "/Create", "/TN", "Maestro\\conferir-canais", "/TR",
                 '"C:\\Maestro\\Maestro.exe" --conferir-canais', "/SC", "DAILY", "/ST", "06:05", "/F"]
    semana = agendador.comando_criar("--organizar", "Toda semana (segunda)", "22:00", exe="x")
    assert semana[-7:] == ["/SC", "WEEKLY", "/D", "MON", "/ST", "22:00", "/F"]
    assert agendador.comando_criar("--dublar", "A cada 6 horas", exe="x")[-7:-1] == ["/SC", "HOURLY", "/MO", "6", "/ST", "06:00"]
    with pytest.raises(agendador.ErroAgenda, match="horário inválido"):
        agendador.comando_criar("--organizar", "Todo dia", "25:00", exe="x")
    with pytest.raises(agendador.ErroAgenda, match="comando desconhecido"):
        agendador.comando_criar("--apagar-tudo", "Todo dia", exe="x")


def test_agendar_listar_e_remover():
    saida = ('"\\Maestro\\conferir-canais","11/10/2026 06:00:00","Pronto"\n'
             '"\\Microsoft\\Windows\\Outra","N/A","Pronto"\n"\\Maestro\\organizar","10/10/2026 22:00:00","Em execução"\n')
    falso = SchtasksFalso(saida)
    assert agendador.listar(falso) == [("--conferir-canais", "11/10/2026 06:00:00", "Pronto"),
                                       ("--organizar", "10/10/2026 22:00:00", "Em execução")]
    assert agendador.agendar("--organizar", "Todo dia", "22:00", falso) == "Maestro\\organizar"
    agendador.remover("--organizar", falso)
    assert falso.chamadas[-1] == ["schtasks", "/Delete", "/TN", "Maestro\\organizar", "/F"]
    with pytest.raises(agendador.ErroAgenda, match="acesso negado"):
        agendador.agendar("--organizar", "Todo dia", "22:00", SchtasksFalso(codigo=1))
