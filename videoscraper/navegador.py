"""Navegador de verdade (Chromium via Playwright) para sites que:
  - montam a lista de vídeos com JavaScript (o HTML 'cru' vem vazio);
  - exigem login (você entra com a SUA conta, na janela, e a sessão fica salva);
  - mostram verificações ('não sou um robô', aviso de cookies) que VOCÊ resolve na janela.

Este módulo NÃO tenta enganar sistemas anti-robô nem resolver CAPTCHA sozinho:
se o site bloquear automação, a decisão de continuar é sua, na janela, como pessoa.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from .extracao import eh_resposta_de_midia

# Pasta onde o navegador guarda cookies/sessões entre execuções (login fica salvo aqui).
# Cookies da sessão (inclusive os que o Chrome apagaria ao fechar). Contém seu LOGIN: não compartilhe.
ARQUIVO_SESSAO = "sessao_cookies.json"

PERFIL_PADRAO = str(Path(__file__).resolve().parent.parent / ".perfil_navegador")

# Textos típicos de páginas de verificação/bloqueio (só para AVISAR o usuário).
SINAIS_DE_BLOQUEIO = ("captcha", "just a moment", "verify you are human", "não sou um robô",
                      "are you a robot", "access denied", "acesso negado", "attention required")


class PlaywrightAusente(RuntimeError):
    pass


def aguardar_no_terminal(mensagem: str) -> None:
    """Jeito padrão de esperar o usuário: mostra a mensagem e espera Enter no terminal.
    A interface gráfica troca isso por uma caixa de diálogo com botão OK."""
    print(f"\n{mensagem}\n   (pressione Enter aqui quando terminar)")
    input()


class Navegador:
    """Uso:
        with Navegador(visivel=True) as nav:
            html, url_final, frames, midias = nav.renderizar("https://site.com")
    """

    def __init__(self, perfil: str = PERFIL_PADRAO, visivel: bool = False,
                 pausar: bool = False, espera_extra: float = 2.0, rolagens: int = 8,
                 timeout: float = 45, executavel: str | None = None,
                 aguardar_usuario=aguardar_no_terminal):
        self.perfil = perfil
        self.visivel = visivel or pausar          # pausar só faz sentido com a janela aberta
        self.pausar = pausar
        self.espera_extra = espera_extra
        self.rolagens = rolagens
        self.timeout_ms = int(timeout * 1000)
        # Caminho do Chrome/Chromium (opcional). Sem isso, usa o que o Playwright instalou.
        self.executavel = executavel or os.environ.get("VIDEOSCRAPER_CHROME") or None
        self.aguardar_usuario = aguardar_usuario
        self._pw = None
        self.contexto = None

    # --- abrir / fechar ---------------------------------------------------------
    def __enter__(self):
        self.abrir()
        return self

    def __exit__(self, *exc):
        self.fechar()

    def abrir(self) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ModuleNotFoundError:
            raise PlaywrightAusente(
                "O modo navegador precisa do Playwright. Instale com:\n"
                f"   {sys.executable} -m pip install playwright\n"
                f"   {sys.executable} -m playwright install chromium") from None
        self._pw = sync_playwright().start()
        try:
            self.contexto = self._lancar()
        except Exception as erro:
            if "Executable doesn't exist" not in str(erro) or self.executavel:
                self.fechar()
                raise
            # Primeira vez: o Chromium do Playwright ainda não foi baixado. Baixa e tenta de novo.
            print("⏬ Baixando o navegador Chromium (só na primeira vez, ~150 MB)...", file=sys.stderr)
            subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True,
                           **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}))
            self.contexto = self._lancar()

    def _lancar(self):
        Path(self.perfil).mkdir(parents=True, exist_ok=True)
        # Contexto PERSISTENTE = funciona como um perfil do Chrome: cookies e login ficam salvos.
        contexto = self._pw.chromium.launch_persistent_context(
            self.perfil,
            headless=not self.visivel,
            executable_path=self.executavel,
            locale="pt-BR",
            viewport={"width": 1366, "height": 900},
        )
        # O Chrome apaga cookies "de sessão" (sem validade) ao fechar, e muitos sites guardam o
        # login justamente neles. Por isso salvamos/restauramos os cookies num arquivo à parte.
        arquivo = Path(self.perfil) / ARQUIVO_SESSAO
        if arquivo.exists():
            try:
                contexto.add_cookies(json.loads(arquivo.read_text(encoding="utf-8")))
            except Exception as erro:
                print(f"⚠️  Não consegui restaurar a sessão salva: {erro}", file=sys.stderr)
        return contexto

    def fechar(self) -> None:
        if self.contexto is not None:
            try:
                arquivo = Path(self.perfil) / ARQUIVO_SESSAO
                arquivo.write_text(json.dumps(self.contexto.cookies()), encoding="utf-8")
            except Exception:
                pass
            try:
                self.contexto.close()
            except Exception:
                pass
            self.contexto = None
        if self._pw is not None:
            self._pw.stop()
            self._pw = None

    # --- usar -------------------------------------------------------------------
    def renderizar(self, url: str):
        """Abre a página, deixa o JavaScript trabalhar e devolve:
           (html_final, url_final, [(url_do_iframe, html_do_iframe)], [urls_de_midia_vistas_na_rede])
        """
        pagina = self.contexto.new_page()
        midias: list[str] = []

        # Escuta TODAS as respostas de rede: é assim que achamos vídeos carregados por JavaScript
        # (por exemplo, a lista .m3u8 que o player pede depois que a página abre).
        def ao_responder(resposta):
            if eh_resposta_de_midia(resposta.url, resposta.headers.get("content-type")):
                if resposta.url not in midias and resposta.url.startswith("http"):
                    midias.append(resposta.url)

        pagina.on("response", ao_responder)
        try:
            resposta = pagina.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            self._esperar_rede(pagina)

            if self.pausar:
                self.aguardar_usuario(
                    "Janela do navegador aberta. Resolva o que aparecer (login, aviso de cookies,\n"
                    "'não sou um robô', clicar em play...) e depois continue.")
                self._esperar_rede(pagina)

            self._rolar(pagina)                    # carrega itens 'lazy' (que aparecem ao rolar)
            pagina.wait_for_timeout(self.espera_extra * 1000)
            self._avisar_se_bloqueado(pagina, resposta)

            frames = []
            for frame in pagina.frames:
                if frame is pagina.main_frame or not frame.url.startswith("http"):
                    continue
                try:
                    frames.append((frame.url, frame.content()))
                except Exception:
                    pass                           # iframe que fechou ou recusou leitura
            return pagina.content(), pagina.url, frames, midias
        finally:
            pagina.close()

    def cookies(self) -> list[dict]:
        """Cookies atuais do navegador (para o download via requests usar a mesma sessão)."""
        return self.contexto.cookies()

    def login_manual(self, url: str) -> None:
        """Abre o site para VOCÊ entrar com sua conta. A sessão fica salva no perfil."""
        pagina = self.contexto.new_page()
        pagina.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
        self.aguardar_usuario("Faça login na janela do navegador que abriu.\n"
                              "Quando terminar (já logado), continue.")
        pagina.close()
        print(f"✅ Sessão salva em: {self.perfil}")

    # --- detalhes ---------------------------------------------------------------
    def _esperar_rede(self, pagina) -> None:
        try:
            pagina.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass   # sites com conexões eternas (chat, anúncios) nunca ficam 'idle'; seguimos

    def _rolar(self, pagina) -> None:
        altura_anterior = 0
        for _ in range(self.rolagens):
            altura = pagina.evaluate("document.body ? document.body.scrollHeight : 0")
            if altura == altura_anterior:
                break
            altura_anterior = altura
            pagina.mouse.wheel(0, altura)
            pagina.wait_for_timeout(700)

    def _avisar_se_bloqueado(self, pagina, resposta) -> None:
        status = resposta.status if resposta else 0
        try:
            texto = (pagina.title() + " " + pagina.inner_text("body")[:3000]).lower()
        except Exception:
            texto = ""
        if status in (401, 403, 429, 503) or any(s in texto for s in SINAIS_DE_BLOQUEIO):
            print(f"⚠️  A página parece pedir verificação/login ou bloqueou o acesso (HTTP {status}).\n"
                  "   Tente: 'login' para entrar com sua conta, ou --pausar para resolver na janela.\n"
                  "   Se o site proíbe automação nos termos de uso, não insista.", file=sys.stderr)
