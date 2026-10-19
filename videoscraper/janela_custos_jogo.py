"""A janela "💰 Opções e custos" do modo "Traduzir e dublar (no PC)" (como no protótipo): grátis ou pago em cada
etapa, com os valores estimados PARA ESTE JOGO (pelas letras do roteiro e pelos segundos das falas), e os perfis que
escolhem tudo com um clique (Tudo grátis, Equilibrado, Melhor qualidade). Embaixo, o "Enquanto joga" por hora de jogo.
"""

from __future__ import annotations

from tkinter import ttk

import customtkinter as ctk

from jellyfin_tools import gastos
from jellyfin_tools.traducao import estimar_custo
from jellyfin_tools.voz_gemini import DESCONTO_FLEX
from jellyfin_tools.voz_gemini import estimar_custo as custo_voz

from .gui_moderna import Tema

MODELOS = (("Claude Haiku 5.5", "claude-haiku-5-5", "boa · rápida"),
           ("Claude Sonnet 5.5", "claude-sonnet-5-5", "muito boa · respeita o espaço de cada fala"),
           ("Claude Opus 5.5", "claude-opus-5-5", "a melhor"))
LETRAS_CLOUD_GRATIS = 1_000_000


def _us(valor: float) -> str:
    return f"US$ {valor:.2f}".replace(".", ",")


def linhas_de_custo(letras: int, textos: int, segundos: float) -> list[tuple[str, str, str, str, float, float]]:
    """[(etapa, opção, como fica, custo em texto, mínimo, máximo)] para este jogo."""
    linhas = [("Tradução", "Grátis no PC (Argos)", "mais literal · nada sai do seu PC", _us(0), 0.0, 0.0),
              ("Tradução", "Gemini Flash · chave grátis", "boa · limite de pedidos por dia", _us(0), 0.0, 0.0)]
    for nome, modelo, como in MODELOS:
        custo = estimar_custo(max(1, letras), max(1, textos), modelo)[2] or 0.0
        linhas.append(("Tradução", nome, como, f"≈ {_us(custo)}", custo, custo))
    minimo, maximo = custo_voz(segundos) if segundos else (0.0, 0.0)
    linhas += [("Dublagem", "XTTS-v2 (no PC)", "natural · emoção pela gravação ou Chatterbox · nada sai do PC",
                _us(0), 0.0, 0.0),
               ("Dublagem", "Piper (no PC)", "robótica · nada sai do seu PC", _us(0), 0.0, 0.0),
               ("Dublagem", "Google Cloud Neural2 · cota grátis", f"natural, pouca emoção · usa {round(letras / 1000)} "
                f"mil de 1 milhão de letras do mês", _us(0) if letras <= LETRAS_CLOUD_GRATIS else "passa da cota",
                0.0, 0.0),
               ("Dublagem", "Gemini · chave grátis", "expressiva · leva alguns dias (limite diário)", _us(0), 0.0, 0.0),
               ("Dublagem", "Gemini pago · modo Flex", "expressiva · termina no mesmo dia",
                f"≈ {_us(minimo * DESCONTO_FLEX)} a {_us(maximo * DESCONTO_FLEX).replace('US$ ', '')}",
                minimo * DESCONTO_FLEX, maximo * DESCONTO_FLEX),
               ("Dublagem", "Gemini pago · normal", "expressiva · mais rápida",
                f"≈ {_us(minimo)} a {_us(maximo).replace('US$ ', '')}", minimo, maximo)]
    return linhas


PERFIS = {"Tudo grátis": ("Grátis no PC (Argos)", "XTTS-v2 (no PC)"),
          "Equilibrado": ("Claude Haiku 5.5", "XTTS-v2 (no PC)"),
          "Melhor qualidade": ("Claude Sonnet 5.5", "Gemini pago · normal")}


def custo_do_perfil(linhas: list, perfil: str) -> tuple[float, float]:
    traducao, dublagem = PERFIS[perfil]
    escolhidas = [linha for linha in linhas if linha[1] in (traducao, dublagem)]
    return sum(linha[4] for linha in escolhidas), sum(linha[5] for linha in escolhidas)


class JanelaCustos(ctk.CTkToplevel):
    """aplicar(perfil): o que o perfil escolhido muda no modo (quem traduz e o motor)."""

    def __init__(self, pai, jogo: str, letras: int, textos: int, falas: int, segundos: float, aplicar):
        super().__init__(pai)
        self.title(f"Opções e custos · {jogo}")
        self.configure(fg_color=Tema.CARTAO)
        self.geometry("1100x720")
        self.transient(pai)
        self.aplicar = aplicar
        m = pai
        pequeno = ctk.CTkFont(Tema.FAMILIA, 11)
        self.linhas = linhas_de_custo(letras, textos, segundos)
        topo = ctk.CTkFrame(self, fg_color="transparent")
        topo.pack(fill="x", padx=18, pady=(14, 4))
        m._rotulo(topo, f"💰 Opções e custos · {jogo}", suave=False, fonte=m.f_secao).pack(side="left")
        m._rotulo(topo, f"   {textos} textos · {letras / 1000:.0f} mil letras de texto · {falas} falas com voz (≈ "
                        f"{max(1, round(segundos / 60))} min de fala)".replace(".", ","),
                  fonte=pequeno).pack(side="left")
        perfis = ctk.CTkFrame(self, fg_color="transparent")
        perfis.pack(fill="x", padx=18, pady=(4, 6))
        m._rotulo(perfis, "Perfil:", suave=False).pack(side="left", padx=(0, 8))
        self.botoes_perfil = {}
        for perfil in PERFIS:
            minimo, maximo = custo_do_perfil(self.linhas, perfil)
            valor = _us(minimo) if abs(maximo - minimo) < 0.005 else f"≈ {_us(minimo)} a {maximo:.2f}".replace(".", ",")
            botao = m._botao(perfis, f"{perfil}   {valor}", lambda p=perfil: self.escolher(p),
                             "primario" if perfil == "Tudo grátis" else "secundario")
            botao.pack(side="left", padx=(0, 8))
            self.botoes_perfil[perfil] = botao
        quadro = ctk.CTkFrame(self, fg_color=Tema.CARTAO, corner_radius=0)
        quadro.pack(fill="both", expand=True, padx=18, pady=(4, 4))
        self.tabela = ttk.Treeview(quadro, columns=("etapa", "opcao", "como", "custo"), show="headings", height=11,
                                   style="Moderno.Treeview")
        for chave, texto, largura in (("etapa", "Etapa", 110), ("opcao", "Opção", 290), ("como", "Como fica", 470),
                                      ("custo", "Custo estimado", 180)):
            self.tabela.heading(chave, text=texto, anchor="w")
            self.tabela.column(chave, width=largura, anchor="w", stretch=chave == "como")
        self.tabela.tag_configure("gratis", background="#14301f")
        self.tabela.tag_configure("pago", background=Tema.LINHA_PAR)
        for i, (etapa, opcao, como, custo, minimo, maximo) in enumerate(self.linhas):
            self.tabela.insert("", "end", iid=str(i), values=(etapa, opcao, como, custo),
                               tags=("gratis" if maximo == 0 and custo != "passa da cota" else "pago",))
        self.tabela.pack(fill="both", expand=True)
        atual = gastos.atual()
        rodape = ctk.CTkFrame(self, fg_color="transparent")
        rodape.pack(fill="x", padx=18, pady=(2, 8))
        m._rotulo(rodape, "verde = grátis · o perfil marca a tradução e a dublagem · patch pronto da comunidade: "
                          "sempre grátis", fonte=pequeno).pack(side="left")
        if atual is not None:
            usado = atual.total()
            m._rotulo(rodape, f"Teto do mês: {atual._teto_texto() if atual.teto else 'sem teto'} · usado: "
                              f"{_us(usado)}", fonte=pequeno).pack(side="right")
        m._rotulo(self, "Enquanto joga · por hora de jogo  (≈ 400 caixas de texto e ≈ 12 minutos de fala por hora)",
                  suave=False).pack(anchor="w", padx=18, pady=(6, 2))
        hora = ttk.Treeview(self, columns=("etapa", "gratis", "pago"), show="headings", height=4,
                            style="Moderno.Treeview")
        for chave, texto, largura in (("etapa", "Etapa", 200), ("gratis", "Grátis", 420), ("pago", "Pago", 420)):
            hora.heading(chave, text=texto, anchor="w")
            hora.column(chave, width=largura, anchor="w")
        for linha in (("Ler a tela (OCR)", "no seu PC (o leitor do Windows)", "—"),
                      ("Traduzir o texto", "Argos no PC · Gemini Flash (chave grátis)",
                       "Claude Haiku ≈ US$ 0,01/h · Sonnet ≈ US$ 0,15/h"),
                      ("Legenda das vozes", "Whisper turbo na placa de vídeo", "—"),
                      ("Ler em voz alta", "XTTS-v2 no PC · Piper", "Gemini ≈ US$ 0,14 a 0,46/h")):
            hora.insert("", "end", values=linha)
        hora.pack(fill="x", padx=18, pady=(0, 4))
        m._rotulo(self, "Frases repetidas saem da memória e não são pagas de novo.", fonte=pequeno).pack(
            anchor="w", padx=18, pady=(0, 6))
        m._botao(self, "Fechar", self.destroy, "fantasma").pack(anchor="e", padx=18, pady=(0, 12))
        self.escolhido = ""
        self._marcar("Tudo grátis")

    def _marcar(self, perfil: str) -> None:
        escolhidas = set(PERFIS[perfil])
        for i, linha in enumerate(self.linhas):
            valores = list(self.tabela.item(str(i), "values"))
            valores[1] = ("✓ " if linha[1] in escolhidas else "") + linha[1]
            self.tabela.item(str(i), values=valores)
        for nome, botao in self.botoes_perfil.items():
            botao.configure(fg_color=Tema.PRIMARIA if nome == perfil else Tema.SECUNDARIA)

    def escolher(self, perfil: str) -> None:
        self.escolhido = perfil
        self._marcar(perfil)
        self.aplicar(perfil)

