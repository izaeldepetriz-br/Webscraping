"""O tempo de traduzir e dublar um jogo: a estimativa por etapa (com a velocidade deste PC), o horário de término e
a previsão corrigida durante o trabalho."""
import time

from jellyfin_tools import tempo_jogo as tj


def test_estima_cada_etapa_e_aprende_a_velocidade_do_pc(tmp_path):
    arquivo = tmp_path / "velocidades_jogos.json"
    v = tj.Velocidades(arquivo)
    etapas = tj.estimar(v, segundos_sem_texto=600, textos=1000, falas=2000, iso_mb=4000, quem_traduz="Claude",
                        motor="XTTS-v2", placa=True, whisper_placa=True, custos={"traduzir": "≈ US$ 0,40"})
    assert [e.chave for e in etapas] == ["ouvir", "traduzir", "dublar", "entregar", "montar"]
    dublar = etapas[2]
    assert dublar.quem == "XTTS-v2 (placa de vídeo)" and dublar.segundos == 60 + 2000 * 3.0 and not dublar.medida_no_pc
    assert etapas[1].custo == "≈ US$ 0,40" and etapas[0].tamanho() == "10 min de áudio"
    assert tj.legivel(dublar.segundos) == "1 h 41 min"
    # no processador, 9 vezes mais devagar; sem ISO, não monta
    lento = tj.estimar(v, falas=2000, placa=False)
    assert [e.chave for e in lento] == ["dublar", "entregar"] and tj.legivel(lento[0].segundos) == "15 h 02 min"
    # só legendar: traduz e entrega o roteiro (sem dublar nem montar)
    assert [e.chave for e in tj.estimar(v, textos=500)] == ["traduzir", "entregar"]
    # o PC mediu 2 s por fala (300 falas em 660 s, tirando 1 min de abrir): a próxima estimativa usa a medida
    v.medir("dublar:XTTS-v2:placa", 300, 660)
    assert v.de("dublar:XTTS-v2:placa") == 2.0
    de_novo = tj.Velocidades(arquivo)                                   # ficou guardada
    assert de_novo.medida("dublar:XTTS-v2:placa") and de_novo.de("dublar:XTTS-v2:placa") == 2.0
    de_novo.medir("dublar:XTTS-v2:placa", 300, 60 + 300 * 4.0)          # metade de cada: (2 + 4) / 2
    assert de_novo.de("dublar:XTTS-v2:placa") == 3.0
    de_novo.medir("dublar:XTTS-v2:placa", 2, 500)                       # 2 falas não ensinam nada
    assert de_novo.de("dublar:XTTS-v2:placa") == 3.0
    assert tj.estimar(de_novo, falas=10, placa=True)[0].medida_no_pc


def test_resumo_horario_de_termino_e_cronometro():
    agora = time.mktime((2026, 10, 19, 21, 0, 0, 0, 0, -1))
    assert tj.termina_as(40 * 60, agora) == "por volta das 21h40"
    assert tj.termina_as(5 * 3600, agora) == "amanhã por volta das 02h00"
    assert tj.termina_as(3 * 86400, agora) == "em 3 dias, por volta das 21h00"
    etapas = tj.estimar(tj.Velocidades(), textos=400, falas=100, quem_traduz="Argos", motor="Piper")
    texto = tj.resumo(etapas, agora)
    assert texto.startswith("≈ 3 min (traduzir 2 min · dublar menos de 1 min)") and "por volta das 21h02" in texto
    assert tj.resumo([], agora).startswith("nada para fazer")
    # durante: no começo vale a previsão; depois, a velocidade real (10 % em 60 s: faltam 9 min) + as próximas
    relogio = [0.0]
    c = tj.Cronometro(1200, depois=600, relogio=lambda: relogio[0], agora=lambda: agora)
    assert c.falta(0.0) == 1800
    relogio[0] = 60.0
    assert c.falta(0.1) == 540 + 600 and c.texto(0.1) == "faltam ≈ 19 min · termina por volta das 21h19"
