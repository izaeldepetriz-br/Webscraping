"""Camada usada pelo terminal (cli) E pela janela (gui): buscar e baixar, sem saber quem chamou.

Uso:
    with Trabalho(navegador=True) as t:
        links = t.buscar("https://site.com/videos")
        t.baixar(links, "videos_baixados")
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from . import archive_org
from .coleta import FonteNavegador, FonteRequests, rastrear
from .download import NaoBaixavel, baixar_video
from .extracao import LinkVideo
from .navegador import PERFIL_PADRAO, Navegador, aguardar_no_terminal
from .rede import ClienteHTTP


@dataclass
class Resumo:
    ok: int = 0
    pulados: int = 0
    falhas: int = 0


class Trabalho:
    def __init__(self, espera: float = 1.5, ignorar_robots: bool = False,
                 navegador: bool = False, visivel: bool = False, pausar: bool = False,
                 perfil: str = PERFIL_PADRAO, chrome: str | None = None,
                 aguardar_usuario=aguardar_no_terminal, parar=None):
        self.cliente = ClienteHTTP(espera=espera, respeitar_robots=not ignorar_robots)
        self.parar = parar or (lambda: False)
        self.cliente.parar = self.parar              # as pausas entre pedidos também param na hora
        if navegador or visivel or pausar:
            nav = Navegador(perfil=perfil, visivel=visivel, pausar=pausar, executavel=chrome,
                            aguardar_usuario=aguardar_usuario)
            self.fonte = FonteNavegador(self.cliente, nav)
        else:
            self.fonte = FonteRequests(self.cliente)

    @property
    def usa_navegador(self) -> bool:
        return isinstance(self.fonte, FonteNavegador)

    @property
    def bloqueadas(self) -> list[str]:
        """Páginas que o robots.txt do site não permite acessar."""
        return self.fonte.bloqueadas

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.fechar()

    def fechar(self) -> None:
        self.fonte.fechar()

    def buscar(self, url: str, profundidade: int = 0, max_paginas: int = 30,
               mesmo_dominio: bool = True, seletor: str | None = None,
               filtro_links: str = "") -> list[LinkVideo]:
        if archive_org.reconhece(url) and not seletor:
            print("archive.org detectado: usando a API oficial (lista todos os itens, sem rolar a página).\n"
                  f"Máx. de páginas = máx. de itens consultados ({max_paginas}).")
            return archive_org.buscar(self.cliente, url, limite=max_paginas, parar=self.parar,
                                      bloqueadas=self.fonte.bloqueadas)
        return rastrear(self.fonte, url, profundidade, max_paginas, mesmo_dominio,
                        seletor or None, parar=self.parar, filtro_links=filtro_links)

    def baixar(self, links: list[LinkVideo], pasta: str, ao_terminar_item=None) -> Resumo:
        """Baixa os links. `ao_terminar_item(link, status, detalhe)` é chamado a cada vídeo
        (status: 'ok', 'pulado' ou 'erro') para quem quiser mostrar o andamento."""
        self.fonte.sincronizar_cookies()      # downloads usam a mesma sessão (login) do navegador
        os.makedirs(pasta, exist_ok=True)
        resumo = Resumo()
        avisar = ao_terminar_item or (lambda *a: None)
        for i, link in enumerate(links, 1):
            if self.parar():
                print("⏹  Downloads interrompidos.")
                break
            print(f"\n[{i}/{len(links)}] {link.titulo or link.url}\n   {link.url}  [{link.tipo}]")
            try:
                destino = baixar_video(self.cliente, link, pasta, i)
                print(f"✅ Salvo em {destino}")
                resumo.ok += 1
                avisar(link, "ok", destino)
            except NaoBaixavel as motivo:
                print(f"⏭  Pulado: {motivo}")
                resumo.pulados += 1
                avisar(link, "pulado", str(motivo))
            except Exception as erro:          # um vídeo com erro não derruba os outros
                print(f"❌ Erro: {erro}")
                resumo.falhas += 1
                avisar(link, "erro", str(erro))
        print(f"\n🎉 Pronto! {resumo.ok} baixado(s), {resumo.pulados} pulado(s), {resumo.falhas} falha(s).")
        return resumo


def fazer_login(url: str, perfil: str = PERFIL_PADRAO, chrome: str | None = None,
                aguardar_usuario=aguardar_no_terminal) -> None:
    with Navegador(perfil=perfil, visivel=True, executavel=chrome,
                   aguardar_usuario=aguardar_usuario) as nav:
        nav.login_manual(url)


MENSAGEM_ROBOTS = (
    "O próprio site proíbe robôs nesta página (regras do arquivo robots.txt).\n"
    "Por isso o programa não acessa, nem com o navegador.\n\n"
    "Grandes plataformas (YouTube, Instagram, TikTok...) bloqueiam desse jeito e, nos termos\n"
    "de uso, proíbem baixar vídeos sem o botão oficial de download. Para pesquisar no YouTube\n"
    "por programa, o caminho permitido é a API oficial (YouTube Data API)."
)
