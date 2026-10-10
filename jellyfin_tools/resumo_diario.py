"""Resumo diário no Discord/Telegram: "Hoje: 3 filmes organizados, 2 legendas traduzidas, 1 canal fora do ar".

Cada ação (da janela ou dos comandos de robô) soma no arquivo resumo_do_dia.json; uma vez por dia, na hora escolhida,
o programa manda o resumo (só se aconteceu alguma coisa: dia parado não gera mensagem).
"""

from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path

# o que pode aparecer no resumo, na ordem da mensagem
ITENS = {"baixados": "vídeo(s) baixado(s)",
         "organizados": "filme(s)/episódio(s) organizado(s)",
         "traduzidas": "legenda(s) traduzida(s) pelo Claude",
         "pelo_audio": "legenda(s) criada(s) pelo áudio",
         "dublados": "filme(s) dublado(s)",
         "espelhos_quebrados": "espelho(s) .strm quebrado(s)",
         "canais_fora": "canal(is) ao vivo fora do ar",
         "erros": "erro(s) — veja o log"}


class ResumoDiario:
    def __init__(self, arquivo: str | Path):
        self.arquivo = Path(arquivo)

    def _ler(self) -> dict:
        try:
            dados = json.loads(self.arquivo.read_text(encoding="utf-8"))
            return dados if isinstance(dados, dict) else {}
        except (OSError, ValueError):
            return {}

    def _gravar(self, dados: dict) -> None:
        try:
            self.arquivo.parent.mkdir(parents=True, exist_ok=True)
            self.arquivo.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass                                       # o resumo nunca pode atrapalhar a ação de verdade

    def registrar(self, item: str, quantidade: int = 1, agora: datetime | None = None) -> None:
        """Soma `quantidade` ao item de HOJE (um dia novo começa do zero)."""
        if quantidade <= 0 or item not in ITENS:
            return
        hoje = (agora or datetime.now()).date().isoformat()
        dados = self._ler()
        if dados.get("dia") != hoje:
            dados = {"dia": hoje, "contagens": {}, "enviado": dados.get("enviado", "")}
        dados["contagens"][item] = dados["contagens"].get(item, 0) + quantidade
        self._gravar(dados)

    def para_enviar(self, hora: int, agora: datetime | None = None) -> dict | None:
        """As contagens de hoje, se já passou da `hora`, ainda não foi enviado e aconteceu algo. Marca como enviado."""
        agora = agora or datetime.now()
        hoje = agora.date().isoformat()
        dados = self._ler()
        if agora.hour < hora or dados.get("enviado") == hoje:
            return None
        contagens = dados.get("contagens", {}) if dados.get("dia") == hoje else {}
        dados.update({"enviado": hoje, "dia": hoje, "contagens": contagens})
        self._gravar(dados)
        return contagens or None


def mensagem(contagens: dict, quando: datetime | None = None) -> tuple[str, str]:
    """(texto do Discord, texto do Telegram)."""
    data = f"{(quando or datetime.now()):%d/%m}"
    linhas = [f"{contagens[k]} {texto}" for k, texto in ITENS.items() if contagens.get(k)]
    discord = f"\U0001F4CB **Resumo do dia {data} no Maestro**\n" + "\n".join(f"• {l}" for l in linhas)
    telegram = (f"\U0001F4CB <b>Resumo do dia {data} no Maestro</b>\n"
                + "\n".join(f"• {html.escape(l)}" for l in linhas))
    return discord, telegram
