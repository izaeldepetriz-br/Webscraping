"""Melhoria 4b: avisos no Discord (Webhook) e/ou Telegram (Bot) quando um filme é processado.

Discord:  Configurações do canal -> Integrações -> Webhooks -> Copiar URL do webhook.
Telegram: fale com @BotFather -> /newbot -> copie o TOKEN; o CHAT_ID é o da conversa
          (mande uma mensagem ao bot e veja em https://api.telegram.org/bot<TOKEN>/getUpdates).

Falhar ao notificar NUNCA interrompe a organização: o erro só vai para o log.
"""

from __future__ import annotations

import html
import time

import requests

from .registro import obter_logger

log = obter_logger()


class Notificador:
    def __init__(self, discord_webhook: str = "", telegram_token: str = "", telegram_chat_id: str = "",
                 telegram_base: str = "https://api.telegram.org", timeout: float = 15,
                 sessao: requests.Session | None = None):
        self.discord_webhook = discord_webhook.strip()
        self.telegram_token = telegram_token.strip()
        self.telegram_chat_id = str(telegram_chat_id).strip()
        self.telegram_base = telegram_base.rstrip("/")
        self.timeout = timeout
        self.sessao = sessao or requests.Session()

    @property
    def ativo(self) -> bool:
        return bool(self.discord_webhook or (self.telegram_token and self.telegram_chat_id))

    def novo_filme(self, nome: str) -> None:
        """'🍿 Novo filme adicionado ao Jellyfin: Creed II (2018)' (negrito em cada plataforma)."""
        self.enviar(discord=f"\U0001F37F **Novo filme adicionado ao Jellyfin:** {nome}",
                    telegram=f"\U0001F37F <b>Novo filme adicionado ao Jellyfin:</b> {html.escape(nome)}")

    def resumo(self, nomes: list[str], ja_avisados: int) -> None:
        """Um aviso só para muitos filmes (evita spam e o limite de mensagens das plataformas)."""
        restantes = nomes[ja_avisados:]
        if not restantes:
            return
        lista = "\n".join(f"• {n}" for n in restantes[:30]) + ("\n…" if len(restantes) > 30 else "")
        self.enviar(discord=f"\U0001F37F **{len(restantes)} filmes adicionados ao Jellyfin:**\n{lista}",
                    telegram=f"\U0001F37F <b>{len(restantes)} filmes adicionados ao Jellyfin:</b>\n"
                             f"{html.escape(lista)}")

    def enviar(self, discord: str, telegram: str) -> bool:
        ok = True
        if self.discord_webhook:
            ok &= self._postar(self.discord_webhook, {"content": discord[:2000]}, "Discord")
        if self.telegram_token and self.telegram_chat_id:
            url = f"{self.telegram_base}/bot{self.telegram_token}/sendMessage"
            ok &= self._postar(url, {"chat_id": self.telegram_chat_id, "text": telegram[:4096],
                                     "parse_mode": "HTML", "disable_web_page_preview": True}, "Telegram")
        return ok

    def _postar(self, url: str, dados: dict, plataforma: str) -> bool:
        for tentativa in (1, 2):
            try:
                r = self.sessao.post(url, json=dados, timeout=self.timeout)
            except requests.RequestException as erro:
                log.warning("Notificação %s falhou (rede): %s", plataforma, erro)
                return False
            if r.status_code == 429 and tentativa == 1:            # muitas mensagens: espera e tenta 1x
                espera = _segundos_de_espera(r)
                log.info("Notificação %s: limite de mensagens, esperando %.0f s", plataforma, espera)
                time.sleep(espera)
                continue
            if r.ok:
                log.debug("Notificação %s enviada", plataforma)
                return True
            log.warning("Notificação %s recusada: HTTP %s %s", plataforma, r.status_code, r.text[:200])
            return False
        return False


def _segundos_de_espera(resposta: requests.Response) -> float:
    try:
        dados = resposta.json()
        valor = dados.get("retry_after") or (dados.get("parameters") or {}).get("retry_after") or 2
    except ValueError:
        valor = resposta.headers.get("Retry-After", 2)
    return min(float(valor), 30.0)
