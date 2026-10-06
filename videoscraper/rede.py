"""Acesso HTTP 'educado' com requests: robots.txt, pausa entre pedidos e novas tentativas."""

from __future__ import annotations

import random
import sys
import time
from urllib import robotparser
from urllib.parse import urlparse

import requests

USER_AGENT = "videoscraper/2.0 (projeto educacional)"
TIMEOUT = 20

# Plataformas grandes: os termos de uso proíbem baixar sem o botão oficial. O robots.txt delas NUNCA é ignorado,
# nem com a pessoa dizendo que pode (para pesquisar no YouTube, o caminho é a API oficial).
PLATAFORMAS_PROTEGIDAS = ("youtube.com", "youtu.be", "googlevideo.com", "instagram.com", "facebook.com", "fb.watch",
                          "tiktok.com", "twitter.com", "x.com", "twitch.tv", "netflix.com", "primevideo.com",
                          "disneyplus.com", "max.com", "globoplay.globo.com", "vimeo.com", "dailymotion.com",
                          "kwai.com", "spotify.com")


def site_de(url: str) -> str:
    """'https://WWW.Meusite.com:8080/a' -> 'www.meusite.com:8080' (o site, como o robots.txt vale)."""
    return urlparse(url).netloc.lower()


def pode_ignorar_robots(site: str) -> bool:
    """False para as plataformas grandes (e os subdomínios delas)."""
    host = site.split(":")[0].lower().strip(".")
    return bool(host) and not any(host == p or host.endswith("." + p) for p in PLATAFORMAS_PROTEGIDAS)


class ClienteHTTP:
    def __init__(self, espera: float = 1.0, tentativas: int = 3, respeitar_robots: bool = True,
                 timeout: float = TIMEOUT, sites_sem_robots=(), variacao: float = 0.0,
                 pausa_longa_a_cada: int = 0):
        """variacao: a espera entre pedidos vira um sorteio em [espera·(1-v), espera·(1+v)] (média = espera;
        ex.: espera 5 e variacao 0.4 = de 3 a 7 s). pausa_longa_a_cada: depois de N pedidos, uma pausa
        preventiva maior, sorteada entre 6 e 12 vezes a espera (espera 5 = de 30 a 60 s). 0 = sem pausa longa."""
        self.espera = espera
        self.variacao = max(0.0, min(variacao, 1.0))
        self.pausa_longa_a_cada = pausa_longa_a_cada
        self.pedidos = 0                 # pedidos já feitos (conta para a pausa longa)
        self.tentativas = tentativas
        self.respeitar_robots = respeitar_robots
        # sites que a pessoa disse serem dela (ou ter autorização): o robots.txt só deles é ignorado
        self.sites_sem_robots = {s.lower() for s in sites_sem_robots if pode_ignorar_robots(s)}
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
        p = urlparse(url)
        if p.netloc.lower() in self.sites_sem_robots or (not self.respeitar_robots
                                                           and pode_ignorar_robots(p.netloc)):
            return True
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

    def intervalo(self) -> float:
        """A espera antes do próximo pedido: fixa, ou sorteada (random.uniform) em volta da média."""
        if not self.variacao:
            return self.espera
        return random.uniform(self.espera * (1 - self.variacao), self.espera * (1 + self.variacao))

    def pausar(self) -> None:
        """Espera o intervalo entre um pedido e outro; a cada `pausa_longa_a_cada` pedidos, uma pausa maior."""
        if self.pausa_longa_a_cada and self.pedidos and self.pedidos % self.pausa_longa_a_cada == 0:
            longa = random.uniform(self.espera * 6, self.espera * 12)
            print(f"  ⏸ pausa preventiva de {longa:.0f} s ({self.pedidos} pedidos feitos)", file=sys.stderr)
            if self._dormir(longa):
                return                                 # "Parar" no meio da pausa
        sobra = self.intervalo() - (time.monotonic() - self._ultimo)
        if sobra > 0:
            self._dormir(sobra)
        self._ultimo = time.monotonic()
        self.pedidos += 1

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
