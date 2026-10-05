"""Acesso HTTP 'educado' com requests: robots.txt, pausa entre pedidos e novas tentativas."""

from __future__ import annotations

import sys
import time
from urllib import robotparser
from urllib.parse import urlparse

import requests

USER_AGENT = "videoscraper/2.0 (projeto educacional)"
TIMEOUT = 20


class ClienteHTTP:
    def __init__(self, espera: float = 1.0, tentativas: int = 3, respeitar_robots: bool = True,
                 timeout: float = TIMEOUT):
        self.espera = espera
        self.tentativas = tentativas
        self.respeitar_robots = respeitar_robots
        self.timeout = timeout
        self.sessao = requests.Session()
        self.sessao.headers.update({"User-Agent": USER_AGENT,
                                    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"})
        self._robots: dict[str, robotparser.RobotFileParser | None] = {}
        self._ultimo = 0.0
        self.parar = None              # função: True quando o usuário apertou "Parar" (as pausas param na hora)

    def _dormir(self, segundos: float) -> bool:
        """Espera em pedacinhos de 0,1 s; devolve True se o "Parar" foi apertado no meio."""
        fim = time.monotonic() + segundos
        while (falta := fim - time.monotonic()) > 0:
            if self.parar and self.parar():
                return True
            time.sleep(min(0.1, falta))
        return bool(self.parar and self.parar())

    # --- regras do site -------------------------------------------------------
    def permitido(self, url: str) -> bool:
        """Consulta (e guarda em cache) o robots.txt do site. Sem robots.txt = liberado."""
        if not self.respeitar_robots:
            return True
        p = urlparse(url)
        raiz = f"{p.scheme}://{p.netloc}"
        if raiz not in self._robots:
            rp = robotparser.RobotFileParser()
            try:
                r = self.sessao.get(f"{raiz}/robots.txt", timeout=self.timeout)
                if r.status_code == 200:
                    rp.parse(r.text.splitlines())
                    self._robots[raiz] = rp
                else:
                    self._robots[raiz] = None
            except requests.RequestException:
                self._robots[raiz] = None
        rp = self._robots[raiz]
        return True if rp is None else rp.can_fetch(USER_AGENT, url)

    def pausar(self) -> None:
        """Garante pelo menos `espera` segundos entre um pedido e outro."""
        sobra = self.espera - (time.monotonic() - self._ultimo)
        if sobra > 0:
            self._dormir(sobra)
        self._ultimo = time.monotonic()

    # --- pedidos ----------------------------------------------------------------
    def obter_html(self, url: str) -> tuple[bytes, str] | None:
        """Devolve (bytes do HTML, url final após redirecionamentos) ou None."""
        for tentativa in range(1, self.tentativas + 1):
            self.pausar()
            if self.parar and self.parar():
                return None
            try:
                r = self.sessao.get(url, timeout=self.timeout)
                if r.status_code in (429, 500, 502, 503, 504):
                    raise requests.HTTPError(f"HTTP {r.status_code}")
                r.raise_for_status()
                if "html" not in r.headers.get("Content-Type", "").lower():
                    return None
                return r.content, r.url      # bytes: o BeautifulSoup detecta a codificação
            except requests.RequestException as erro:
                print(f"  [tentativa {tentativa}/{self.tentativas}] {url}: {erro}", file=sys.stderr)
                if tentativa < self.tentativas and self._dormir(2 ** tentativa):
                    return None                       # "Parar" durante a espera para tentar de novo
        return None

    def importar_cookies(self, cookies: list[dict]) -> None:
        """Copia cookies do navegador (ex.: sessão de login) para o requests."""
        for c in cookies:
            self.sessao.cookies.set(c["name"], c["value"], domain=c.get("domain", ""),
                                    path=c.get("path", "/"))
