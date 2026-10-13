"""Quanto o Maestro gastou nas APIs pagas, por mês: Claude (Anthropic) e Gemini (Google AI Studio).

Cada pedido pago registra o seu custo ESTIMADO aqui (pelos tokens que a API devolveu, ou pelo tamanho do áudio),
no ponto mais baixo do código (Tradutor, motor do Gemini): assim vale para a janela, para os robôs agendados e para
a tradução em lote, sem ninguém precisar lembrar de somar.

Teto do mês (opcional): passou do teto, o próximo pedido pago é recusado com TetoAtingido. Quem chama transforma
em ErroTraducao/ErroDublagem, e o que já ficou pronto continua guardado (a dublagem retoma de onde parou).

É uma estimativa: o valor oficial é o da página de cobrança de cada empresa (console.anthropic.com e
aistudio.google.com). Sem configurar() (ex.: nos testes), nada é gravado e não há teto.

Em reais: o arquivo guarda sempre em DÓLAR (é como as APIs cobram); `fator` (cotação × (1 + IOF)) só converte
para mostrar e para comparar com o teto, que fica na moeda escolhida na tela (ver cotacao.py).
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

SERVICOS = ("Claude", "Gemini (voz)", "Gemini (escuta)", "Gemini", "Google TTS")   # "Gemini": meses antigos
PLANOS_GEMINI = {"?": "não sei", "gratis": "grátis (sem cartão)", "pago": "pago (com faturamento)"}


def servico_gemini(servico: str) -> bool:
    return servico.startswith("Gemini")


NOMES_PEDIDOS_GEMINI = {"voz": "voz", "escuta": "escuta do original"}


def hora_do_pacifico(utc: datetime) -> datetime:
    """O horário da Califórnia: o "dia" das cotas do Google vira à meia-noite de lá (no Brasil, entre 4h e 5h).
    Sem o tzdata (o Windows não tem): PDT (UTC-7) do 2º domingo de março ao 1º domingo de novembro, às 2h; senão
    PST (UTC-8)."""
    utc = utc.astimezone(timezone.utc).replace(tzinfo=None) if utc.tzinfo else utc

    def domingo(mes: int, n: int) -> datetime:
        dia = datetime(utc.year, mes, 1)
        return dia + timedelta(days=(6 - dia.weekday()) % 7 + 7 * (n - 1))
    verao = domingo(3, 2) + timedelta(hours=10) <= utc < domingo(11, 1) + timedelta(hours=9)
    return utc - timedelta(hours=7 if verao else 8)


class TetoAtingido(Exception):
    pass


class Gastos:
    def __init__(self, arquivo: Path, teto: float = 0.0, agora=datetime.now, fator: float | None = None,
                 conversao: str = "", plano_gemini: str = "?"):
        """teto: na moeda mostrada (reais, com `fator`; senão dólares). fator: reais por dólar já com o IOF.
        conversao: o texto de onde veio o fator ('PTAX de 09/10 + IOF 3,5%'). plano_gemini: "gratis" (a chave não
        tem faturamento: o Gemini não cobra, só para quando o limite do dia acaba), "pago" ou "?" (conta como pago)."""
        self.plano_gemini = plano_gemini if plano_gemini in PLANOS_GEMINI else "?"
        self.arquivo, self.teto, self._agora = Path(arquivo), float(teto or 0), agora
        self.fator, self.conversao = (float(fator) if fator else None), conversao
        self._trava = threading.Lock()

    def valor(self, dolares: float) -> str:
        """US$ -> texto na moeda mostrada: 'R$ 12,45' (com a cotação) ou 'US$ 2.29'."""
        if self.fator:
            from .cotacao import em_reais
            return em_reais(dolares * self.fator)
        return f"US$ {dolares:.2f}"

    def _teto_texto(self) -> str:
        if self.fator:
            from .cotacao import em_reais
            return em_reais(self.teto)
        return f"US$ {self.teto:.2f}"

    def na_moeda(self, dolares: float) -> float:
        return dolares * self.fator if self.fator else dolares

    def _ler(self) -> dict:
        try:
            dados = json.loads(self.arquivo.read_text(encoding="utf-8"))
            return dados if isinstance(dados, dict) else {}
        except (OSError, ValueError):
            return {}

    def mes(self) -> str:
        return f"{self._agora():%Y-%m}"

    def do_mes(self, mes: str | None = None) -> dict[str, float]:
        """{"Claude": US$, "Gemini": US$} do mês (o atual, se não disser)."""
        meses = self._ler().get("meses", {})
        do_mes = meses.get(mes or self.mes(), {}) if isinstance(meses, dict) else {}
        return {s: float(do_mes.get(s, 0) or 0) for s in SERVICOS}

    def total(self, mes: str | None = None) -> float:
        return sum(self.do_mes(mes).values())

    def gratis(self, servico: str) -> bool:
        """O serviço não cobra (Gemini com a chave sem faturamento): o uso é anotado, o gasto não."""
        return servico_gemini(servico) and self.plano_gemini == "gratis"

    def registrar(self, servico: str, valor: float) -> None:
        """O USO estimado (sempre, para mostrar quanto cada API usou) e o GASTO (só o que é cobrado)."""
        if not valor or valor <= 0:
            return
        with self._trava:
            dados = self._ler()
            uso = dados.setdefault("uso", {}).setdefault(self.mes(), {})
            uso[servico] = round(float(uso.get(servico, 0) or 0) + valor, 6)
            if not self.gratis(servico):
                do_mes = dados.setdefault("meses", {}).setdefault(self.mes(), {})
                do_mes[servico] = round(float(do_mes.get(servico, 0) or 0) + valor, 6)
            self._gravar(dados)

    def _gravar(self, dados: dict) -> None:
        self.arquivo.parent.mkdir(parents=True, exist_ok=True)
        temporario = self.arquivo.with_suffix(".tmp")
        temporario.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
        temporario.replace(self.arquivo)

    def uso_do_mes(self, mes: str | None = None) -> dict[str, float]:
        """{serviço: US$ estimados} de TUDO o que foi usado no mês, pago ou grátis."""
        uso = self._ler().get("uso", {}).get(mes or self.mes(), {})
        return {str(k): float(v or 0) for k, v in uso.items()} if isinstance(uso, dict) else {}

    def foto(self) -> dict:
        """O uso e o gasto de cada serviço AGORA (para comparar antes/depois de um teste: custos_entre)."""
        return {"uso": self.uso_do_mes(), "pago": self.do_mes(), "google_tts": sum(self.caracteres().values()),
                "cotas": self.cotas()}

    # ---------------------------------------------------------------- cotas grátis
    def marcar_cota(self, api: str, situacao: str) -> bool:
        """Anota (uma vez por mês) que a cota grátis / o crédito de uma API acabou: {"situacao", "quando"}.
        Devolve True se foi agora (para avisar no log só na 1ª vez)."""
        with self._trava:
            dados = self._ler()
            cotas = dados.setdefault("cotas", {}).setdefault(self.mes(), {})
            anterior = cotas.get(api, {})
            if anterior.get("situacao") == situacao and (
                    anterior.get("dia") == self.dia_do_google() if situacao == "limite do dia"
                    else str(anterior.get("quando", "")).startswith(self.mes())):
                return False
            cotas[api] = {"situacao": situacao, "quando": self._agora().isoformat(timespec="minutes"),
                          "dia": self.dia_do_google()}
            self._gravar(dados)
            return True

    def anotar_gemini_gratis(self) -> bool:
        """O Google respondeu, num erro de limite, que a chave está na camada GRÁTIS: anota o dia e a hora (uma vez
        por dia). Com "Paga" escolhido, isso quer dizer que o faturamento ainda não vale para essa chave."""
        with self._trava:
            dados = self._ler()
            if str(dados.get("gemini_gratis_em", "")).startswith(f"{self._agora():%Y-%m-%d}"):
                return False
            dados["gemini_gratis_em"] = self._agora().isoformat(timespec="minutes")
            self._gravar(dados)
            return True

    def esquecer_gemini_gratis(self) -> None:
        """Escolheu "Paga" agora (acabou de cadastrar o cartão): o que o Google respondeu antes não vale mais."""
        with self._trava:
            dados = self._ler()
            if dados.pop("gemini_gratis_em", None) is not None:
                self._gravar(dados)

    def aviso_do_plano(self) -> str:
        """O plano do Gemini escolhido não bate com o que o Google respondeu HOJE ('' quando bate)."""
        if not str(self._ler().get("gemini_gratis_em", "")).startswith(f"{self._agora():%Y-%m-%d}"):
            return ""
        if self.plano_gemini == "pago":
            return ("Gemini: a chave está marcada como PAGA, mas hoje o Google respondeu como chave GRÁTIS (limite da "
                    "camada grátis): o faturamento ainda não está ativo no projeto dessa chave (confira em "
                    "aistudio.google.com/apikey; pode levar alguns minutos depois de cadastrar o cartão)")
        if self.plano_gemini == "?":
            return "Gemini: hoje o Google respondeu como chave GRÁTIS: escolha \"Grátis\" abaixo"
        return ""

    # ---------------------------------------------------------------- pedidos do dia (chave grátis do Gemini)
    def _utc(self) -> datetime:
        return self._agora().astimezone(timezone.utc)              # o relógio do PC (naive = hora local)

    def dia_do_google(self) -> str:
        """O dia das cotas do Google (vira à meia-noite da Califórnia)."""
        return f"{hora_do_pacifico(self._utc()):%Y-%m-%d}"

    def virada_do_dia(self) -> str:
        """A hora LOCAL em que o dia do Google vira (o limite do dia volta): 'HH:MM'."""
        agora = hora_do_pacifico(self._utc())
        meia_noite = datetime(agora.year, agora.month, agora.day) + timedelta(days=1)
        return f"{self._agora() + (meia_noite - agora):%H:%M}"

    def _pedidos_de_hoje(self, dados: dict) -> dict:
        hoje = self.dia_do_google()
        pedidos = dados.get("pedidos_gemini", {})
        if not isinstance(pedidos, dict) or hoje not in pedidos:
            dados["pedidos_gemini"] = pedidos = {hoje: {}}            # só o dia de hoje fica guardado
        return pedidos[hoje]

    def contar_pedido_gemini(self, tipo: str) -> None:
        """Um pedido ao Gemini que deu certo ("voz" ou "escuta"): conta para o limite do dia da chave grátis."""
        with self._trava:
            dados = self._ler()
            hoje = self._pedidos_de_hoje(dados)
            hoje[tipo] = int(hoje.get(tipo, 0) or 0) + 1
            self._gravar(dados)

    def anotar_limite_gemini(self, tipo: str, por_dia: int | None = None, por_minuto: int | None = None,
                             esgotou: bool = False) -> None:
        """O que o Google disse no erro de limite: o tamanho do limite por dia/minuto ("limit: 15") e se o do dia
        acabou HOJE (aí restam 0, mesmo que a conta do Maestro diga outra coisa)."""
        with self._trava:
            dados = self._ler()
            limites = dados.setdefault("limites_gemini", {}).setdefault(tipo, {})
            if por_dia:
                limites["dia"] = int(por_dia)
            if por_minuto:
                limites["minuto"] = int(por_minuto)
            if esgotou:
                self._pedidos_de_hoje(dados)[f"{tipo}_esgotou"] = self._agora().isoformat(timespec="minutes")
            self._gravar(dados)

    def restam_hoje(self, tipo: str) -> int | None:
        """Pedidos grátis que restam hoje ("voz" ou "escuta"): 0 se o do dia acabou; None se o Google ainda não
        disse o tamanho do limite (ou na chave paga)."""
        if self.plano_gemini == "pago":
            return None
        dados = self._ler()
        hoje = dados.get("pedidos_gemini", {}).get(self.dia_do_google(), {})
        if hoje.get(f"{tipo}_esgotou"):
            return 0
        limite = (dados.get("limites_gemini", {}).get(tipo) or {}).get("dia")
        return max(0, int(limite) - int(hoje.get(tipo, 0) or 0)) if limite else None

    def uso_do_dia_gemini(self) -> list[str]:
        """Chave grátis do Gemini: quantos pedidos foram feitos HOJE e quantos restam (o Google não diz quanto
        resta: o Maestro conta os pedidos dele e o limite vem da 1ª mensagem de limite do Google). Vazio na chave
        paga."""
        if self.plano_gemini == "pago":
            return []
        dados = self._ler()
        hoje = dados.get("pedidos_gemini", {}).get(self.dia_do_google(), {})
        limites = dados.get("limites_gemini", {})
        linhas = []
        for tipo, nome in NOMES_PEDIDOS_GEMINI.items():
            feitos, limite = int(hoje.get(tipo, 0) or 0), (limites.get(tipo) or {}).get("dia")
            if hoje.get(f"{tipo}_esgotou"):
                linhas.append(f"Gemini ({nome}): o limite do dia ACABOU às {str(hoje[f'{tipo}_esgotou'])[11:16]}"
                              + (f" ({limite} pedidos)" if limite else "") + "; restam 0")
            elif limite:
                linhas.append(f"Gemini ({nome}): {feitos} de {limite} pedidos grátis hoje; "
                              f"restam ~{max(0, limite - feitos)}")
            elif feitos:
                linhas.append(f"Gemini ({nome}): {feitos} pedido(s) hoje (o limite do dia aparece aqui quando o "
                              "Google avisar pela 1ª vez)")
        if linhas:
            linhas.append(f"O dia do Google vira às {self.virada_do_dia()} (meia-noite na Califórnia): aí o limite "
                          "do dia volta inteiro")
        return linhas

    def resumo_do_dia_gemini(self) -> tuple[str, bool | None] | None:
        """Para o painel do topo: "Gemini grátis hoje: voz 3/15 (restam ~12) · escuta 1/20 (restam ~19)". Vermelho
        quando o limite do dia de algum acabou. None na chave paga ou sem nada a mostrar."""
        if self.plano_gemini == "pago":
            return None
        dados = self._ler()
        hoje = dados.get("pedidos_gemini", {}).get(self.dia_do_google(), {})
        limites, partes, acabou = dados.get("limites_gemini", {}), [], False
        for tipo in NOMES_PEDIDOS_GEMINI:
            feitos, limite = int(hoje.get(tipo, 0) or 0), (limites.get(tipo) or {}).get("dia")
            if hoje.get(f"{tipo}_esgotou"):
                partes.append(f"{tipo} ACABOU (volta às {self.virada_do_dia()})")
                acabou = True
            elif limite:
                partes.append(f"{tipo} {feitos}/{limite} (restam ~{max(0, limite - feitos)})")
            elif feitos:
                partes.append(f"{tipo} {feitos} pedido(s)")
        if not partes:
            return None
        return "Gemini grátis hoje: " + " · ".join(partes), (False if acabou else None)

    def cotas(self, mes: str | None = None) -> dict:
        cotas = self._ler().get("cotas", {}).get(mes or self.mes(), {})
        return dict(cotas) if isinstance(cotas, dict) else {}

    def situacao_das_cotas(self, tipos_cloud: dict | None = None) -> list[str]:
        """Uma linha por API: grátis, dentro da cota, cota acabou (desde quando) ou pago. tipos_cloud: voz_cloud.TIPOS."""
        cotas, linhas = self.cotas(), []

        def quando(api):
            texto = str(cotas.get(api, {}).get("quando", ""))
            return f"{texto[8:10]}/{texto[5:7]} às {texto[11:16]}" if len(texto) >= 16 else ""
        for tipo, usados in sorted(self.caracteres().items()):
            preco, cota = ((tipos_cloud or {}).get(tipo) or (None, None, 0.0, 0))[2:4]
            if cota and usados >= cota:
                linhas.append(f"Google Cloud TTS ({tipo}): a cota grátis do mês ACABOU"
                              + (f" em {quando('Google TTS ' + tipo)}" if quando("Google TTS " + tipo) else "")
                              + f"; agora é pago (~US$ {preco:g} por milhão de caracteres)")
            elif cota:
                linhas.append(f"Google Cloud TTS ({tipo}): {usados // 1000} mil de {cota // 1000} mil caracteres "
                              f"grátis do mês ({usados * 100 // cota}%)")
        if aviso := self.aviso_do_plano():
            linhas.append(aviso)
        if self.plano_gemini == "gratis":
            linhas.append("Gemini: chave GRÁTIS (sem faturamento): não cobra; quando o limite do dia acaba, para até o "
                          "dia seguinte" + (f" (o de hoje acabou às {quando('Gemini')[-5:]})"
                                            if self._limite_do_dia_hoje(cotas.get("Gemini", {})) else ""))
        elif self.plano_gemini == "pago":
            linhas.append("Gemini: chave com faturamento: pago desde o 1º pedido (não há cota grátis)")
        else:
            linhas.append("Gemini: escolha abaixo se a sua chave é grátis ou paga (por enquanto conta como paga)")
        linhas.append("Claude: pago por uso, com créditos pré-pagos (não há cota grátis)"
                      + (f"; os créditos ACABARAM em {quando('Claude')}: recarregue em console.anthropic.com"
                         if cotas.get("Claude") else ""))
        linhas.append("Whisper, Piper e tradução local: grátis (rodam no seu PC)")
        return linhas

    def _limite_do_dia_hoje(self, cota: dict) -> bool:
        """O limite do dia acabou no dia do Google de HOJE? (registros antigos, sem "dia": pelo dia local)"""
        if "dia" in cota:
            return cota["dia"] == self.dia_do_google()
        return str(cota.get("quando", "")).startswith(f"{self._agora():%Y-%m-%d}")

    def cotas_acabadas(self) -> list[str]:
        """As que acabaram neste mês (para o aviso no painel de saúde)."""
        return [api for api, c in self.cotas().items()
                if c.get("situacao") != "limite do dia" or self._limite_do_dia_hoje(c)]

    def caracteres(self, mes: str | None = None) -> dict[str, int]:
        """Google Cloud TTS: {tipo: caracteres lidos no mês} (para a cota grátis de cada tipo)."""
        do_mes = self._ler().get("caracteres", {}).get(mes or self.mes(), {})
        return {str(k): int(v or 0) for k, v in do_mes.items()} if isinstance(do_mes, dict) else {}

    def registrar_caracteres(self, tipo: str, quantos: int, tipos: dict) -> None:
        """Soma os caracteres do tipo no mês; só a parte que passar da cota grátis vira gasto (Google TTS).
        tipos: {tipo: (_, _, US$ por milhão, cota grátis)} (voz_cloud.TIPOS)."""
        if quantos <= 0:
            return
        preco, cota = (tipos.get(tipo) or (None, None, 0.0, 0))[2:4]
        with self._trava:
            dados = self._ler()
            do_mes = dados.setdefault("caracteres", {}).setdefault(self.mes(), {})
            antes = int(do_mes.get(tipo, 0) or 0)
            do_mes[tipo] = antes + quantos
            pago = max(0, antes + quantos - cota) - max(0, antes - cota)
            if pago:
                gasto = dados.setdefault("meses", {}).setdefault(self.mes(), {})
                gasto["Google TTS"] = round(float(gasto.get("Google TTS", 0) or 0) + pago * preco / 1_000_000, 6)
            if cota and antes < cota <= antes + quantos:          # a cota grátis do mês acabou AGORA
                dados.setdefault("cotas", {}).setdefault(self.mes(), {})[f"Google TTS {tipo}"] = {
                    "situacao": "acabou", "quando": self._agora().isoformat(timespec="minutes")}
            self._gravar(dados)

    def conferir(self) -> None:
        """Antes de um pedido pago: passou do teto do mês? TetoAtingido com o motivo."""
        if self.teto > 0 and self.na_moeda(gasto := self.total()) >= self.teto:
            raise TetoAtingido(f"o teto de gastos do mês ({self._teto_texto()}) foi atingido: já são "
                               f"{self.valor(gasto)} estimados. Aumente o teto em Configurações > Gastos (ou espere "
                               "o mês virar); o que já ficou pronto está guardado")

    def resumo(self) -> str:
        """'US$ 1.23 (Claude 0.40 · Gemini 0.83) de US$ 5.00', ou em reais: 'R$ 12,45 (Claude R$ 2,28 · Gemini
        R$ 10,17) de R$ 30,00', para o painel e as Configurações."""
        valores = self.do_mes()
        if self.fator:
            partes = " · ".join(f"{s} {self.valor(v)}" for s, v in valores.items() if v) or "nada ainda"
        else:
            partes = " · ".join(f"{s} {v:.2f}" for s, v in valores.items() if v) or "nada ainda"
        texto = f"{self.valor(sum(valores.values()))} ({partes})"
        return texto + (f" de {self._teto_texto()}" if self.teto > 0 else "")

    def perto_do_teto(self, parte: float = 0.8) -> bool:
        return self.teto > 0 and self.na_moeda(self.total()) >= parte * self.teto


_atual: Gastos | None = None


def configurar(arquivo: Path | None, teto: float = 0.0, fator: float | None = None,
               conversao: str = "", plano_gemini: str = "?") -> Gastos | None:
    """Liga o registro (o app e os robôs chamam ao começar); None desliga. fator: reais por dólar (com IOF)."""
    global _atual
    _atual = Gastos(arquivo, teto, fator=fator, conversao=conversao, plano_gemini=plano_gemini) if arquivo else None
    return _atual


def marcar_cota(api: str, situacao: str) -> bool:
    """A cota grátis (ou o crédito) de uma API acabou: anota com a data. True se foi agora (avisar no log)."""
    if _atual is not None:
        try:
            return _atual.marcar_cota(api, situacao)
        except OSError:
            pass
    return False


def anotar_gemini_gratis() -> bool:
    """O erro de limite do Google falou da camada grátis: anota (para conferir com o plano escolhido)."""
    if _atual is not None:
        try:
            return _atual.anotar_gemini_gratis()
        except OSError:
            pass
    return False


def contar_pedido_gemini(tipo: str) -> None:
    if _atual is not None:
        try:
            _atual.contar_pedido_gemini(tipo)
        except OSError:
            pass


def anotar_limite_gemini(tipo: str, por_dia: int | None = None, por_minuto: int | None = None,
                         esgotou: bool = False) -> None:
    if _atual is not None:
        try:
            _atual.anotar_limite_gemini(tipo, por_dia, por_minuto, esgotou)
        except OSError:
            pass


def custos_entre(antes: dict | None, depois: dict | None) -> dict[str, tuple[float, bool]]:
    """{serviço: (US$ usados, foi grátis?)} entre duas fotos (Gastos.foto): o custo de um teste por API."""
    if not antes or not depois:
        return {}
    saida = {}
    for servico, usado in depois["uso"].items():
        diferenca = usado - antes["uso"].get(servico, 0.0)
        if diferenca > 1e-7:
            pago = depois["pago"].get(servico, 0.0) - antes["pago"].get(servico, 0.0)
            saida[servico] = (diferenca, pago <= 1e-7)
    caracteres = depois.get("google_tts", 0) - antes.get("google_tts", 0)
    if caracteres > 0:
        pago = depois["pago"].get("Google TTS", 0.0) - antes["pago"].get("Google TTS", 0.0)
        saida["Google TTS"] = (pago, pago <= 1e-7)
    return saida


def atual() -> Gastos | None:
    return _atual


def registrar(servico: str, valor: float) -> None:
    if _atual is not None:
        try:
            _atual.registrar(servico, valor)
        except OSError:
            pass                                  # não conseguir anotar o gasto não pode parar a tarefa


def conferir() -> None:
    if _atual is not None:
        _atual.conferir()


def registrar_caracteres(tipo: str, quantos: int, tipos: dict) -> None:
    if _atual is not None:
        try:
            _atual.registrar_caracteres(tipo, quantos, tipos)
        except OSError:
            pass
