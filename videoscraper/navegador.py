"""Navegador de verdade (Chromium via Playwright) para sites que:
  - montam a lista de vídeos com JavaScript (o HTML 'cru' vem vazio);
  - exigem login (você entra com a SUA conta, na janela, e a sessão fica salva);
  - mostram verificações ('não sou um robô', aviso de cookies) que VOCÊ resolve na janela.

Este módulo NÃO tenta enganar sistemas anti-robô nem resolver CAPTCHA sozinho:
se o site bloquear automação, a decisão de continuar é sua, na janela, como pessoa.
"""

from __future__ import annotations

import html
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from .extracao import eh_resposta_de_midia
from .rede import eh_plataforma_protegida

# Pasta onde o navegador guarda cookies/sessões entre execuções (login fica salvo aqui).
# Cookies da sessão (inclusive os que o Chrome apagaria ao fechar). Contém seu LOGIN: não compartilhe.
ARQUIVO_SESSAO = "sessao_cookies.json"

PERFIL_PADRAO = str(Path(__file__).resolve().parent.parent / ".perfil_navegador")

# Textos típicos de páginas de verificação/bloqueio (só para AVISAR o usuário).
SINAIS_DE_BLOQUEIO = ("captcha", "just a moment", "verify you are human", "não sou um robô",
                      "are you a robot", "access denied", "acesso negado", "attention required")

# Players que só carregam o vídeo depois de um clique (o "play" grande em cima do poster). Além dos <video> que
# ainda não têm dados, o programa clica nestes botões. Só no DOM da própria página: os players de outros sites
# (iframes do YouTube, Vimeo...) não são tocados.
SELETORES_PLAY = (".vjs-big-play-button", ".plyr__control--overlaid", ".jw-display-icon-display", ".fp-play",
                  ".mejs__overlay-button", ".mejs-overlay-button", "[aria-label='play' i]", "[aria-label^='play ' i]",
                  "[aria-label*='reproduzir' i]", "[title='play' i]", "[title^='play ' i]",
                  "[class*='play-button' i]", "[class*='playbutton' i]", "[class*='play-btn' i]", "[data-play]")


class PlaywrightAusente(RuntimeError):
    pass


def aguardar_no_terminal(mensagem: str) -> None:
    """Jeito padrão de esperar o usuário: mostra a mensagem e espera Enter no terminal.
    A interface gráfica troca isso por uma caixa de diálogo com botão OK."""
    print(f"\n{mensagem}\n   (pressione Enter aqui quando terminar)")
    input()


def pasta_dos_navegadores() -> str:
    """Onde o Playwright guarda o Chromium: o mesmo lugar do "playwright install" de sempre."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return str(Path(base) / "ms-playwright")
    if sys.platform == "darwin":
        return str(Path.home() / "Library" / "Caches" / "ms-playwright")
    return str(Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "ms-playwright")


def fixar_pasta_dos_navegadores() -> None:
    """No .exe, o Playwright procura o Chromium DENTRO da pasta do programa (PLAYWRIGHT_BROWSERS_PATH=0),
    mas o instalador baixa na pasta do usuário: um não achava o outro ("Executable doesn't exist").
    Aqui os dois passam a usar a pasta do usuário, que ainda sobrevive à troca de versão do programa
    (não precisa baixar os ~150 MB de novo a cada versão nova)."""
    if getattr(sys, "frozen", False) and not os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = pasta_dos_navegadores()


def comando_instalar_chromium() -> tuple[list[str], dict | None]:
    """O comando que baixa o Chromium do Playwright. No programa empacotado (.exe), sys.executable é
    o PRÓPRIO programa ('python -m playwright' abriria outra janela): usa o instalador do Playwright
    (node + cli.js, que vêm dentro do .exe)."""
    if getattr(sys, "frozen", False):
        fixar_pasta_dos_navegadores()
        from playwright._impl._driver import compute_driver_executable, get_driver_env
        driver = compute_driver_executable()
        partes = list(driver) if isinstance(driver, (tuple, list)) else [driver]
        return [*map(str, partes), "install", "chromium"], get_driver_env()
    return [sys.executable, "-m", "playwright", "install", "chromium"], None


def instalar_chromium() -> None:
    comando, ambiente = comando_instalar_chromium()
    subprocess.run(comando, check=True, env=ambiente,
                   **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}))


class Navegador:
    """Uso:
        with Navegador(visivel=True) as nav:
            html, url_final, frames, midias = nav.renderizar("https://site.com")
    """

    def __init__(self, perfil: str = PERFIL_PADRAO, visivel: bool = False,
                 pausar: bool = False, espera_extra: float = 2.0, rolagens: int = 8,
                 timeout: float = 45, executavel: str | None = None,
                 aguardar_usuario=aguardar_no_terminal, ativar_midias: bool = True, max_cliques: int = 8,
                 espera_midia: float = 5.0):
        self.perfil = perfil
        # clicar no poster/play dos vídeos que só carregam com um clique, e esperar (até espera_midia s) a
        # mídia começar a carregar antes de ler a página
        self.ativar_midias = ativar_midias
        self.max_cliques = max_cliques
        self.espera_midia = espera_midia
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
        fixar_pasta_dos_navegadores()
        self._pw = sync_playwright().start()
        try:
            self.contexto = self._lancar()
        except Exception as erro:
            if "Executable doesn't exist" not in str(erro) or self.executavel:
                self.fechar()
                raise
            # Primeira vez: o Chromium do Playwright ainda não foi baixado. Baixa e tenta de novo.
            print("⏬ Baixando o navegador Chromium (só na primeira vez, ~150 MB, pode levar alguns "
                  "minutos)...", file=sys.stderr)
            try:
                instalar_chromium()
                self.contexto = self._lancar()
            except Exception as erro2:
                self.fechar()
                raise PlaywrightAusente(
                    "Não consegui baixar/abrir o navegador Chromium (usado no modo navegador).\n"
                    f"Pasta esperada: {os.environ.get('PLAYWRIGHT_BROWSERS_PATH') or pasta_dos_navegadores()}\n"
                    "Confira a internet e o espaço em disco e tente de novo. Enquanto isso, desmarque "
                    "\"Usar navegador\": o archive.org funciona sem ele.\n\n"
                    f"Detalhe: {str(erro2).splitlines()[0][:300]}") from erro2

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
            if eh_plataforma_protegida(resposta.url):
                return                             # YouTube, Instagram...: nunca (termos de uso)
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
            if self.ativar_midias:
                self._ativar_midias(pagina, midias)   # clica no poster/play e espera a mídia carregar
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
            return pagina.content() + self._conteudo_das_shadow_doms(pagina), pagina.url, frames, midias
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
    # Sites feitos com Web Components (ex.: a busca do archive.org) guardam o conteúdo em
    # "shadow DOMs", partes isoladas da página que o pagina.content() NÃO inclui.
    # Este JavaScript entra em cada shadow DOM (inclusive umas dentro das outras) e coleta
    # links e vídeos. Os endereços já vêm completos (a.href resolve links relativos).
    _JS_SHADOW = """() => {
        const links = [], midias = [];
        const visitar = (raiz, dentroDeShadow) => {
            for (const el of raiz.querySelectorAll('*')) {
                if (el.shadowRoot) visitar(el.shadowRoot, true);
            }
            if (!dentroDeShadow) return;      // o DOM normal já vem no pagina.content()
            for (const a of raiz.querySelectorAll('a[href]'))
                links.push([a.href, (a.textContent || '').trim().slice(0, 200)]);
            for (const v of raiz.querySelectorAll('video[src], source[src], iframe[src]'))
                midias.push([v.tagName.toLowerCase(), v.src]);
        };
        visitar(document, false);
        return {links, midias};
    }"""

    def _conteudo_das_shadow_doms(self, pagina) -> str:
        """Devolve o que estava nas shadow DOMs como HTML simples, para o extrator ler normalmente."""
        try:
            achado = pagina.evaluate(self._JS_SHADOW)
        except Exception:
            return ""
        if not achado["links"] and not achado["midias"]:
            return ""
        partes = ['\n<div data-videoscraper="shadow-dom">']
        for href, texto in achado["links"]:
            partes.append(f'<a href="{html.escape(href, quote=True)}">{html.escape(texto)}</a>')
        for tag, src in achado["midias"]:
            fechamento = "</iframe>" if tag == "iframe" else ""
            partes.append(f'<{tag} src="{html.escape(src, quote=True)}">{fechamento}')
        partes.append("</div>")
        return "".join(partes)

    # --- vídeos que só carregam com um clique -------------------------------------------
    # Marca os alvos: <video> visíveis ainda sem dados (só o poster) e botões de play conhecidos.
    _JS_ALVOS = """(seletores) => {
        const visivel = el => {
            const r = el.getBoundingClientRect(), s = getComputedStyle(el);
            return r.width >= 24 && r.height >= 24 && s.visibility !== 'hidden' && s.display !== 'none'
                && s.opacity !== '0';
        };
        const alvos = [];
        for (const v of document.querySelectorAll('video'))
            if (v.readyState < 2 && visivel(v)) alvos.push(v);
        for (const sel of seletores) {
            let lista;
            try { lista = document.querySelectorAll(sel); } catch (e) { continue; }
            for (const el of lista)
                if (visivel(el) && !alvos.some(a => a.contains(el) || el.contains(a))) alvos.push(el);
        }
        alvos.forEach((el, i) => el.setAttribute('data-maestro-alvo', String(i)));
        return alvos.length;
    }"""
    # O que está de fato no ponto do clique (o que fica POR CIMA: a sobreposição do poster, o botão...)
    _JS_NO_PONTO = """([x, y]) => {
        const el = document.elementFromPoint(x, y);
        if (!el) return 'nada';
        const a = el.closest('a[href]');
        if (a) {
            const h = (a.getAttribute('href') || '').trim().toLowerCase();
            if (h && !h.startsWith('#') && !h.startsWith('javascript:')) return 'link';
        }
        if (el.closest('iframe')) return 'iframe';
        return 'ok';
    }"""
    _JS_ESTADO = """() => Array.from(document.querySelectorAll('video')).map(
        v => [v.readyState, v.networkState, v.currentSrc || v.src || '', v.buffered.length])"""
    _JS_PAUSAR = """() => {
        let drm = 0;
        for (const v of document.querySelectorAll('video')) {
            try { v.pause(); } catch (e) {}
            if (v.mediaKeys) drm++;
        }
        return drm;
    }"""

    @staticmethod
    def _carregando(antes: list, agora: list) -> bool:
        """A mídia mudou de estado? Um <video> novo, mais dados (readyState), começou a baixar (networkState 2 =
        LOADING), trocou de endereço ou já tem pedaços no buffer."""
        if len(agora) != len(antes):
            return True
        for (rs0, ns0, src0, buf0), (rs1, ns1, src1, buf1) in zip(antes, agora):
            if rs1 > rs0 or (ns1 == 2 and ns0 != 2) or src1 != src0 or buf1 > buf0:
                return True
        return False

    def _esperar_midia(self, pagina, antes: list, midias: list, ja_vistas: int, passo: float = 0.25) -> bool:
        """Depois do clique: checa a cada `passo` s, por até `espera_midia` s, se a mídia começou a carregar
        (estado do <video> mudou ou chegaram pacotes de vídeo na rede). True = começou."""
        fim = time.monotonic() + self.espera_midia
        while True:
            if len(midias) > ja_vistas:
                return True
            try:
                if self._carregando(antes, pagina.evaluate(self._JS_ESTADO)):
                    return True
            except Exception:
                pass                               # a página está trocando: tenta de novo no próximo passo
            if time.monotonic() >= fim:
                return False
            pagina.wait_for_timeout(passo * 1000)

    def _ativar_midias(self, pagina, midias: list) -> int:
        """Clica (um clique de mouse de verdade) no CENTRO de cada poster/botão de play e espera a mídia
        carregar. Não clica em links (sairia da página: o rastreador segue os links sozinho) nem em players de
        outros sites (iframes). Vídeo com DRM (EME) não é baixado. Devolve quantos cliques carregaram mídia."""
        try:
            total = min(pagina.evaluate(self._JS_ALVOS, list(SELETORES_PLAY)), self.max_cliques)
        except Exception:
            return 0
        inicio, carregaram = len(midias), 0
        url_da_pagina = pagina.url
        for i in range(total):
            alvo = pagina.locator(f'[data-maestro-alvo="{i}"]').first
            try:
                alvo.scroll_into_view_if_needed(timeout=2000)
                caixa = alvo.bounding_box()
                if not caixa:
                    continue
                x, y = caixa["x"] + caixa["width"] / 2, caixa["y"] + caixa["height"] / 2
                if pagina.evaluate(self._JS_NO_PONTO, [x, y]) != "ok":
                    continue
                antes, ja_vistas = pagina.evaluate(self._JS_ESTADO), len(midias)
                abertas = list(pagina.context.pages)
                pagina.mouse.click(x, y)
                comecou = self._esperar_midia(pagina, antes, midias, ja_vistas)
            except Exception as erro:
                print(f"  ▶ não deu para clicar no player {i + 1}: {str(erro).splitlines()[0][:120]}",
                      file=sys.stderr)
                continue
            for extra in pagina.context.pages:          # janelas de anúncio abertas pelo clique: fecha
                if extra not in abertas and extra is not pagina:
                    try:
                        extra.close()
                    except Exception:
                        pass
            carregaram += comecou
            print(f"  ▶ player {i + 1}: " + ("a mídia começou a carregar" if comecou else
                                             f"nada mudou em {self.espera_midia:g} s"))
            if pagina.url != url_da_pagina:           # o clique mudou de página: volta e para de clicar
                try:
                    pagina.go_back(wait_until="domcontentloaded", timeout=self.timeout_ms)
                except Exception:
                    pass
                break
        try:
            drm = pagina.evaluate(self._JS_PAUSAR)      # para de tocar (o que interessa é o endereço)
        except Exception:
            drm = 0
        if drm and len(midias) > inicio:
            del midias[inicio:]
            print("  🔒 vídeo protegido contra cópia (DRM): os endereços dele não entram na lista.", file=sys.stderr)
        return carregaram

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
