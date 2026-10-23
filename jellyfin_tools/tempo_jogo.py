"""Quanto tempo leva traduzir e dublar um jogo (aba 🎮 Jogos, modo "Traduzir e dublar (no PC)") e a que horas termina.

Antes de começar, cada etapa é estimada pelo tamanho do trabalho (segundos de áudio sem texto, textos, falas,
tamanho da ISO) vezes a velocidade DESTE PC: a medida nos jogos anteriores (velocidades_jogos.json) ou, na 1ª vez, uma
média. Durante, o Cronometro corrige a previsão pela velocidade real ("faltam ≈ 38 min · termina por volta das
22h41") e, no fim, guarda a velocidade medida para o próximo jogo.

    ouvir      o Whisper ouve as falas sem texto            por segundo de áudio (placa de vídeo ou processador)
    traduzir   Claude, Gemini Flash ou Argos (no PC)       por texto
    dublar     XTTS-v2 (placa ou processador), Gemini,     por fala
               Google Cloud ou Piper
    entregar   o roteiro em português e o relatório        quase nada
    montar     a cópia da ISO com as falas no lugar        por MB da ISO
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

ETAPAS = ("ouvir", "traduzir", "dublar", "entregar", "montar")
NOMES = {"ouvir": "Ouvir as falas sem texto", "traduzir": "Traduzir os textos e as falas", "dublar": "Dublar as falas",
         "entregar": "Entregar (roteiro em português e relatório)", "montar": "Montar a ISO em português"}
MEDIDAS = {"ouvir": "s de áudio", "traduzir": "textos", "dublar": "falas", "entregar": "falas", "montar": "MB"}
# segundos por unidade antes de medir neste PC (médias de PCs comuns; a 1ª fala do XTTS-v2 já com o modelo baixado)
PADRAO = {"ouvir:placa": 0.1, "ouvir:processador": 0.6,
          "traduzir:Claude": 0.15, "traduzir:Gemini": 0.2, "traduzir:Argos": 0.3,
          "dublar:XTTS-v2:placa": 3.0, "dublar:XTTS-v2:processador": 27.0, "dublar:Gemini": 4.0,
          "dublar:Google Cloud": 0.6, "dublar:Piper": 0.3,
          "entregar": 0.002, "montar": 0.008}
FIXO = {"dublar:XTTS-v2:placa": 60.0, "dublar:XTTS-v2:processador": 90.0, "montar": 5.0, "entregar": 1.0}  # abrir
MINIMO_PARA_MEDIR = 5         # menos unidades que isso não ensinam a velocidade (o tempo fixo pesaria demais)
ARQUIVO = "velocidades_jogos.json"


def legivel(segundos: float) -> str:
    """'menos de 1 min', '12 min', '1 h 40 min', '2 dias e 3 h'."""
    segundos = max(0.0, segundos)
    if segundos < 60:
        return "menos de 1 min"
    minutos = round(segundos / 60)
    if minutos < 60:
        return f"{minutos} min"
    horas, minutos = divmod(minutos, 60)
    if horas < 24:
        return f"{horas} h" + (f" {minutos:02d} min" if minutos else "")
    dias, horas = divmod(horas, 24)
    return f"{dias} dia{'s' if dias > 1 else ''}" + (f" e {horas} h" if horas else "")


def termina_as(segundos: float, agora: float | None = None) -> str:
    """'por volta das 23h15' (hoje), 'amanhã por volta das 01h30' ou 'em 3 dias, por volta das 09h00'."""
    agora = time.time() if agora is None else agora
    fim, hoje = time.localtime(agora + max(0.0, segundos)), time.localtime(agora)
    dias = (time.mktime((fim.tm_year, fim.tm_mon, fim.tm_mday, 12, 0, 0, 0, 0, -1)) -
            time.mktime((hoje.tm_year, hoje.tm_mon, hoje.tm_mday, 12, 0, 0, 0, 0, -1))) // 86400
    hora = f"por volta das {fim.tm_hour:02d}h{fim.tm_min:02d}"
    return hora if dias <= 0 else f"amanhã {hora}" if dias == 1 else f"em {int(dias)} dias, {hora}"


class Velocidades:
    """A velocidade DESTE PC em cada etapa (segundos por unidade), aprendida nos jogos anteriores."""

    def __init__(self, arquivo: str | Path | None = None):
        self.arquivo = Path(arquivo) if arquivo else None
        self.medidas: dict[str, float] = {}
        if self.arquivo is not None:
            try:
                self.medidas = {k: float(v) for k, v in json.loads(self.arquivo.read_text(encoding="utf-8")).items()}
            except (OSError, ValueError, TypeError, AttributeError):
                self.medidas = {}

    def de(self, chave: str) -> float:
        return self.medidas.get(chave, PADRAO.get(chave, 1.0))

    def medida(self, chave: str) -> bool:
        """True se a velocidade já foi medida neste PC (senão é a média)."""
        return chave in self.medidas

    def medir(self, chave: str, unidades: float, segundos: float) -> None:
        """Junta a velocidade de agora (sem o tempo de abrir) com a guardada (metade de cada) e grava."""
        if unidades < MINIMO_PARA_MEDIR or segundos <= 0:
            return
        agora = max(0.0, segundos - FIXO.get(chave, 0.0)) / unidades
        antes = self.medidas.get(chave)
        self.medidas[chave] = agora if antes is None else (antes + agora) / 2
        if self.arquivo is not None:
            try:
                self.arquivo.parent.mkdir(parents=True, exist_ok=True)
                self.arquivo.write_text(json.dumps(self.medidas, indent=1), encoding="utf-8")
            except OSError:
                pass


@dataclass
class Etapa:
    chave: str                   # "dublar"
    velocidade: str              # "dublar:XTTS-v2:placa" (a chave da velocidade)
    quem: str                    # "XTTS-v2 (placa de vídeo)"
    unidades: float              # 1200 (falas), 3600 (s de áudio), 4300 (MB)
    segundos: float              # a estimativa
    custo: str = "grátis"
    medida_no_pc: bool = False   # a velocidade veio deste PC (e não da média)

    @property
    def nome(self) -> str:
        return NOMES[self.chave]

    def tamanho(self) -> str:
        n = round(self.unidades)
        return f"{n} {MEDIDAS[self.chave]}" if self.chave != "ouvir" else f"{legivel(self.unidades)} de áudio"


def estimar(velocidades: Velocidades, *, segundos_sem_texto: float = 0.0, textos: int = 0, falas: int = 0,
            iso_mb: float = 0.0, quem_traduz: str = "Claude", motor: str = "XTTS-v2", placa: bool = False,
            whisper_placa: bool = False, custos: dict | None = None) -> list[Etapa]:
    """As etapas que têm trabalho, cada uma com o tempo estimado. quem_traduz: Claude/Gemini/Argos; motor: XTTS-v2,
    Gemini, Google Cloud ou Piper; placa: o XTTS-v2 roda na placa de vídeo; custos: {etapa: "US$ 0,40"}."""
    custos = custos or {}
    pedidos = []
    if segundos_sem_texto > 0:
        pedidos.append(("ouvir", "ouvir:" + ("placa" if whisper_placa else "processador"),
                        "Whisper (" + ("placa de vídeo" if whisper_placa else "processador") + ")", segundos_sem_texto))
    if textos > 0:
        pedidos.append(("traduzir", f"traduzir:{quem_traduz}",
                        {"Argos": "Argos (no PC)", "Gemini": "Gemini Flash"}.get(quem_traduz, quem_traduz), textos))
    if falas > 0:
        if motor == "XTTS-v2":
            chave, quem = f"dublar:XTTS-v2:{'placa' if placa else 'processador'}", \
                f"XTTS-v2 ({'placa de vídeo' if placa else 'processador'})"
        else:
            chave, quem = f"dublar:{motor}", motor
        pedidos.append(("dublar", chave, quem, falas))
    if falas > 0 or textos > 0:         # (só legendar: entrega o roteiro em português, sem vozes)
        pedidos.append(("entregar", "entregar", "no seu PC", falas or textos))
    if iso_mb > 0:                     # (iso_mb = 0 quando não há ISO para montar ou ela já está montada)
        pedidos.append(("montar", "montar", "no seu PC", iso_mb))
    etapas = []
    for etapa, chave, quem, unidades in pedidos:
        segundos = FIXO.get(chave, 0.0) + unidades * velocidades.de(chave)
        etapas.append(Etapa(etapa, chave, quem, unidades, segundos, custos.get(etapa, "grátis"),
                            velocidades.medida(chave)))
    return etapas


def total(etapas: list[Etapa], so: tuple | list | None = None) -> float:
    return sum(e.segundos for e in etapas if so is None or e.chave in so)


def resumo(etapas: list[Etapa], agora: float | None = None) -> str:
    """'≈ 1 h 40 min (ouvir 6 min · traduzir 2 min · dublar 1 h 30 min · montar 1 min) · termina por volta das
    23h15 se começar agora'."""
    if not etapas:
        return "nada para fazer ainda: abra o roteiro ou tire as falas da ISO"
    partes = " · ".join(f"{e.chave} {legivel(e.segundos)}" for e in etapas if e.chave != "entregar")
    segundos = total(etapas)
    return f"≈ {legivel(segundos)} ({partes}) · termina {termina_as(segundos, agora)} se começar agora"


class Cronometro:
    """Durante uma etapa: quanto falta (pela velocidade real, depois dos primeiros %) e a que horas termina. depois:
    os segundos estimados das etapas que vêm depois desta (no 🤖 Automático)."""

    def __init__(self, estimado: float, depois: float = 0.0, relogio=time.monotonic, agora=time.time):
        self.estimado, self.depois = max(0.0, estimado), max(0.0, depois)
        self.relogio, self.agora = relogio, agora
        self.inicio = relogio()

    @property
    def passou(self) -> float:
        return self.relogio() - self.inicio

    def falta(self, fracao: float) -> float:
        fracao = min(1.0, max(0.0, fracao))
        if fracao < 0.03 or self.passou < 5:            # no começo, a previsão (o motor ainda abrindo)
            desta = max(self.estimado - self.passou, self.estimado * (1 - fracao))
        else:
            desta = self.passou * (1 - fracao) / fracao
        return desta + self.depois

    def texto(self, fracao: float) -> str:
        falta = self.falta(fracao)
        return f"faltam ≈ {legivel(falta)} · termina {termina_as(falta, self.agora())}"
