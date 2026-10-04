"""Interface gráfica: janela com campos e botões (Tkinter, que já vem com o Python).

Ideia central: a janela NUNCA pode travar. Por isso todo trabalho demorado (acessar sites,
baixar vídeos) roda numa *thread* separada, e a thread conversa com a janela por uma *fila*
(queue). A cada 100 ms a janela olha a fila e atualiza o que precisa.
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import traceback
import webbrowser
from dataclasses import dataclass
from urllib.parse import unquote, urlparse

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from .cli import salvar
from .extracao import LinkVideo
from .navegador import PERFIL_PADRAO, PlaywrightAusente
from .servico import MENSAGEM_ROBOTS, Trabalho, fazer_login

PASTA_PADRAO = os.path.abspath("videos_baixados")

# Nomes amigáveis para a coluna "Origem" (de onde o link saiu).
ORIGENS = {"video_tag": "vídeo da página", "source_tag": "vídeo da página", "iframe": "player embutido",
           "link": "link", "meta": "metadados", "json_ld": "dados da página", "script": "código da página",
           "rede": "pedido do player", "seletor": "seletor CSS"}


@dataclass
class Opcoes:
    navegador: bool
    visivel: bool
    pausar: bool
    seletor: str
    profundidade: int
    max_paginas: int
    limite: int
    espera: float
    pasta: str


class _SaidaParaFila:
    """Substitui o 'print' da tela preta: tudo que o programa imprimir vai para o log da janela."""

    def __init__(self, fila: queue.Queue):
        self.fila = fila

    def write(self, texto: str) -> None:
        if texto:
            self.fila.put(("log", texto))

    def flush(self) -> None:
        pass


def _so_caracteres_basicos(texto: str) -> str:
    # O Tk 8.6 (usado pelo Python no Windows) pode falhar com emojis fora do "plano básico".
    return "".join(c for c in texto if ord(c) <= 0xFFFF)


class App:
    def __init__(self, raiz: tk.Tk):
        self.raiz = raiz
        self.fila: queue.Queue = queue.Queue()
        self.evento_parar = threading.Event()
        self.links: list[LinkVideo] = []
        self.trabalhando = False
        self._stdout, self._stderr = sys.stdout, sys.stderr

        raiz.title("videoscraper - vídeos públicos")
        raiz.minsize(940, 660)
        raiz.geometry("1040x800")
        raiz.protocol("WM_DELETE_WINDOW", self.fechar)
        self._estilos()
        self._montar()

        self.redirecionar_saida()
        raiz.after(100, self._processar_fila)

    def redirecionar_saida(self) -> None:
        sys.stdout = sys.stderr = _SaidaParaFila(self.fila)

    # ------------------------------------------------------------------ layout
    def _estilos(self) -> None:
        estilo = ttk.Style(self.raiz)
        if "vista" not in estilo.theme_names():
            estilo.theme_use("clam")
        estilo.configure("Titulo.TLabel", font=("Segoe UI", 15, "bold"))
        estilo.configure("Sub.TLabel", foreground="#555")
        estilo.configure("Destaque.TButton", font=("Segoe UI", 10, "bold"), padding=(14, 6))
        estilo.configure("TButton", padding=(10, 5))

    def _montar(self) -> None:
        r = self.raiz
        principal = ttk.Frame(r, padding=14)
        principal.pack(fill="both", expand=True)

        ttk.Label(principal, text="Extrair e baixar vídeos públicos", style="Titulo.TLabel").pack(anchor="w")
        ttk.Label(principal, style="Sub.TLabel",
                  text="1) Cole o endereço da página   2) Clique em Buscar vídeos   "
                       "3) Selecione e clique em Baixar").pack(anchor="w", pady=(0, 10))

        # --- endereço
        linha_url = ttk.Frame(principal)
        linha_url.pack(fill="x")
        ttk.Label(linha_url, text="Endereço da página:").pack(side="left")
        self.var_url = tk.StringVar()
        self.campo_url = ttk.Entry(linha_url, textvariable=self.var_url, font=("Segoe UI", 10))
        self.campo_url.pack(side="left", fill="x", expand=True, padx=8)
        self.campo_url.bind("<Return>", lambda e: self.buscar())
        ttk.Button(linha_url, text="Colar", command=self._colar).pack(side="left")
        self.campo_url.focus_set()

        # --- opções
        caixa = ttk.LabelFrame(principal, text=" Opções ", padding=10)
        caixa.pack(fill="x", pady=10)

        self.var_nav = tk.BooleanVar(value=False)
        self.var_visivel = tk.BooleanVar(value=False)
        self.var_pausar = tk.BooleanVar(value=False)
        ttk.Checkbutton(caixa, text="Usar navegador (sites com JavaScript ou login)",
                        variable=self.var_nav, command=self._ajustar_checks).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(caixa, text="Mostrar a janela do navegador",
                        variable=self.var_visivel, command=self._ajustar_checks).grid(row=0, column=2, columnspan=2, sticky="w")
        ttk.Checkbutton(caixa, text="Pausar para eu resolver verificações",
                        variable=self.var_pausar, command=self._ajustar_checks).grid(row=0, column=4, columnspan=2, sticky="w")

        ttk.Label(caixa, text="Seletor CSS (opcional):").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.var_seletor = tk.StringVar()
        ttk.Entry(caixa, textvariable=self.var_seletor, width=22).grid(row=1, column=1, sticky="w", pady=(8, 0))

        self.var_prof = tk.IntVar(value=0)
        self.var_maxp = tk.IntVar(value=30)
        self.var_limite = tk.IntVar(value=0)
        self.var_espera = tk.DoubleVar(value=1.5)
        self._spin(caixa, 1, 2, "Seguir links (níveis):", self.var_prof, 0, 5, 1)
        self._spin(caixa, 1, 4, "Máx. de páginas:", self.var_maxp, 1, 300, 1)
        self._spin(caixa, 2, 0, "Máx. de vídeos (0 = todos):", self.var_limite, 0, 1000, 1)
        self._spin(caixa, 2, 2, "Espera entre pedidos (s):", self.var_espera, 0.5, 10, 0.5)

        ttk.Label(caixa, text="Salvar vídeos em:").grid(row=3, column=0, sticky="w", pady=(8, 0))
        self.var_pasta = tk.StringVar(value=PASTA_PADRAO)
        ttk.Entry(caixa, textvariable=self.var_pasta).grid(row=3, column=1, columnspan=4, sticky="we", pady=(8, 0))
        ttk.Button(caixa, text="Escolher...", command=self._escolher_pasta).grid(row=3, column=5, sticky="w", padx=6, pady=(8, 0))
        caixa.columnconfigure(3, weight=1)

        # --- botões principais
        botoes = ttk.Frame(principal)
        botoes.pack(fill="x")
        self.bt_buscar = ttk.Button(botoes, text="Buscar vídeos", style="Destaque.TButton", command=self.buscar)
        self.bt_baixar_sel = ttk.Button(botoes, text="Baixar selecionados", command=lambda: self.baixar(True))
        self.bt_baixar_todos = ttk.Button(botoes, text="Baixar todos", command=lambda: self.baixar(False))
        self.bt_login = ttk.Button(botoes, text="Fazer login no site", command=self.login)
        self.bt_parar = ttk.Button(botoes, text="Parar", command=self.parar, state="disabled")
        for b in (self.bt_buscar, self.bt_baixar_sel, self.bt_baixar_todos, self.bt_login, self.bt_parar):
            b.pack(side="left", padx=(0, 8))

        # Os blocos de baixo são montados ANTES da tabela (side='bottom'): assim, se a janela
        # ficar pequena, quem encolhe é a tabela, e o log e o rodapé continuam visíveis.
        rodape = ttk.Frame(principal)
        rodape.pack(side="bottom", fill="x", pady=(8, 0))
        self.var_status = tk.StringVar(value="Pronto.")
        ttk.Label(rodape, textvariable=self.var_status).pack(side="left")
        self.barra = ttk.Progressbar(rodape, mode="indeterminate", length=200)
        self.barra.pack(side="right")

        # --- log + barra de status
        quadro_log = ttk.LabelFrame(principal, text=" O que está acontecendo ", padding=6)
        quadro_log.pack(side="bottom", fill="x", pady=(10, 0))
        self.log = ScrolledText(quadro_log, height=7, font=("Consolas", 9), state="disabled", wrap="word")
        self.log.pack(fill="both", expand=True)

        acoes = ttk.Frame(principal)
        acoes.pack(side="bottom", fill="x")
        ttk.Button(acoes, text="Abrir link", command=self._abrir_link).pack(side="left", padx=(0, 8))
        ttk.Button(acoes, text="Copiar link", command=self._copiar_link).pack(side="left", padx=(0, 8))
        ttk.Button(acoes, text="Salvar lista (CSV/JSON/TXT)...", command=self._salvar_lista).pack(side="left", padx=(0, 8))
        ttk.Button(acoes, text="Abrir pasta dos vídeos", command=self._abrir_pasta).pack(side="left")

        # --- tabela de resultados
        quadro = ttk.LabelFrame(principal, text=" Vídeos encontrados ", padding=6)
        quadro.pack(fill="both", expand=True, pady=10)
        colunas = ("n", "status", "titulo", "tipo", "url")
        self.tabela = ttk.Treeview(quadro, columns=colunas, show="headings", selectmode="extended", height=9)
        for col, texto, larg, estica in (("n", "#", 40, False), ("status", "Situação", 90, False),
                                         ("titulo", "Título", 220, True), ("tipo", "Origem", 135, False),
                                         ("url", "Link", 420, True)):
            self.tabela.heading(col, text=texto)
            self.tabela.column(col, width=larg, stretch=estica, anchor="w")
        rolagem = ttk.Scrollbar(quadro, orient="vertical", command=self.tabela.yview)
        self.tabela.configure(yscrollcommand=rolagem.set)
        self.tabela.pack(side="left", fill="both", expand=True)
        rolagem.pack(side="left", fill="y")
        self.tabela.bind("<Double-1>", lambda e: self._abrir_link())
        self.tabela.tag_configure("ok", foreground="#1a7f37")
        self.tabela.tag_configure("erro", foreground="#cf222e")
        self.tabela.tag_configure("pulado", foreground="#8a6d00")

    def _spin(self, pai, linha, coluna, texto, var, de, ate, passo):
        ttk.Label(pai, text=texto).grid(row=linha, column=coluna, sticky="w", padx=(12 if coluna else 0, 4), pady=(8, 0))
        ttk.Spinbox(pai, textvariable=var, from_=de, to=ate, increment=passo, width=7).grid(
            row=linha, column=coluna + 1, sticky="w", pady=(8, 0))

    # ------------------------------------------------------------------ ações dos botões
    def buscar(self) -> None:
        url, opcoes = self._validar()
        if not url:
            return
        self._limpar_tabela()

        def tarefa():
            with self._novo_trabalho(opcoes) as t:
                print(f"Acessando{' com navegador' if t.usa_navegador else ''}: {url}")
                links = t.buscar(url, opcoes.profundidade, opcoes.max_paginas, True, opcoes.seletor)
                print(f"{len(links)} vídeo(s) encontrado(s).")
                self.fila.put(("links", links))
                self._explicar_resultado(t, links)

        self._rodar("Buscando vídeos...", tarefa)

    def baixar(self, so_selecionados: bool) -> None:
        url, opcoes = self._validar(exigir_url=not self.links)
        if not opcoes:
            return
        if so_selecionados:
            ids = self.tabela.selection()
            if not ids:
                messagebox.showinfo("Nada selecionado",
                                    "Clique nos vídeos da lista (Ctrl+clique para vários) e tente de novo,\n"
                                    "ou use 'Baixar todos'.")
                return
            escolhidos = [self.links[int(i)] for i in ids]
        else:
            escolhidos = list(self.links)
        if opcoes.limite:
            escolhidos = escolhidos[:opcoes.limite]

        def tarefa():
            with self._novo_trabalho(opcoes) as t:
                lista = escolhidos
                if not lista:                       # ainda não buscou: busca primeiro
                    print(f"Acessando: {url}")
                    lista = t.buscar(url, opcoes.profundidade, opcoes.max_paginas, True, opcoes.seletor)
                    self.fila.put(("links", lista))
                    if not lista:
                        self._explicar_resultado(t, lista)
                        return
                    if opcoes.limite:
                        lista = lista[:opcoes.limite]
                resumo = t.baixar(lista, opcoes.pasta,
                                  ao_terminar_item=lambda l, st, det: self.fila.put(("item", (l.url, st))))
                self.fila.put(("info", ("Downloads concluídos",
                                        f"Baixados: {resumo.ok}\nPulados: {resumo.pulados}\n"
                                        f"Com erro: {resumo.falhas}\n\nPasta: {opcoes.pasta}")))

        self._rodar("Baixando vídeos...", tarefa)

    def login(self) -> None:
        url, _ = self._validar()
        if not url:
            return
        if not messagebox.askokcancel(
                "Fazer login",
                "Vai abrir uma janela do navegador neste site.\n"
                "Entre com a SUA conta e depois clique em OK na mensagem que vai aparecer.\n\n"
                "A sessão fica salva no seu computador (pasta .perfil_navegador).\n"
                "Não compartilhe essa pasta: ela dá acesso à sua conta."):
            return

        def tarefa():
            fazer_login(url, perfil=PERFIL_PADRAO, aguardar_usuario=self._aguardar_usuario)
            self.fila.put(("info", ("Login salvo",
                                    "Pronto! Agora marque 'Usar navegador' para aproveitar o login.")))
            self.fila.put(("marcar_navegador", None))

        self._rodar("Esperando você fazer login...", tarefa)

    def parar(self) -> None:
        self.evento_parar.set()
        self.var_status.set("Parando... (termina o item atual)")

    # ------------------------------------------------------------------ execução em segundo plano
    def _rodar(self, status: str, tarefa) -> None:
        if self.trabalhando:
            return
        self.trabalhando = True
        self.evento_parar.clear()
        self._botoes_ocupados(True)
        self.var_status.set(status)
        self.barra.start(12)

        def alvo():
            try:
                tarefa()
            except PlaywrightAusente as erro:
                self.fila.put(("erro", str(erro)))
            except Exception as erro:
                traceback.print_exc()
                self.fila.put(("erro", f"{type(erro).__name__}: {erro}"))
            finally:
                self.fila.put(("fim", None))

        threading.Thread(target=alvo, daemon=True).start()

    def _novo_trabalho(self, o: Opcoes) -> Trabalho:
        return Trabalho(espera=o.espera, navegador=o.navegador, visivel=o.visivel, pausar=o.pausar,
                        perfil=PERFIL_PADRAO, aguardar_usuario=self._aguardar_usuario,
                        parar=self.evento_parar.is_set)

    def _aguardar_usuario(self, mensagem: str) -> None:
        """Chamado pela thread de trabalho: pede para a janela mostrar um aviso e espera o OK."""
        ok = threading.Event()
        self.fila.put(("aguardar", (mensagem, ok)))
        ok.wait()

    def _explicar_resultado(self, t: Trabalho, links: list[LinkVideo]) -> None:
        if links:
            return
        if t.bloqueadas:
            self.fila.put(("aviso", ("Acesso não permitido", MENSAGEM_ROBOTS)))
        elif not t.usa_navegador:
            self.fila.put(("info", ("Nenhum vídeo encontrado",
                                    "Nenhum vídeo no HTML da página.\n\nSe a página monta a lista com "
                                    "JavaScript ou exige login, marque 'Usar navegador' e busque de novo.")))
        else:
            self.fila.put(("info", ("Nenhum vídeo encontrado",
                                    "Nem com o navegador apareceu vídeo.\nTente 'Pausar para eu resolver "
                                    "verificações', 'Fazer login no site' ou um seletor CSS.")))

    def _processar_fila(self) -> None:
        try:
            while True:
                tipo, dado = self.fila.get_nowait()
                if tipo == "log":
                    self._escrever_log(dado)
                elif tipo == "links":
                    self._preencher_tabela(dado)
                elif tipo == "item":
                    self._marcar_item(*dado)
                elif tipo == "aguardar":
                    mensagem, ok = dado
                    messagebox.showinfo("Sua vez", mensagem + "\n\nClique em OK quando terminar.")
                    ok.set()
                elif tipo == "info":
                    messagebox.showinfo(*dado)
                elif tipo == "aviso":
                    messagebox.showwarning(*dado)
                elif tipo == "erro":
                    messagebox.showerror("Erro", dado)
                elif tipo == "marcar_navegador":
                    self.var_nav.set(True)
                elif tipo == "fim":
                    self.trabalhando = False
                    self.barra.stop()
                    self._botoes_ocupados(False)
                    self.var_status.set(f"Pronto. {len(self.links)} vídeo(s) na lista.")
        except queue.Empty:
            pass
        self.raiz.after(100, self._processar_fila)

    # ------------------------------------------------------------------ auxiliares
    def _validar(self, exigir_url: bool = True):
        url = self.var_url.get().strip()
        if url and not url.startswith(("http://", "https://")):
            url = "https://" + url
            self.var_url.set(url)
        if exigir_url and not url:
            messagebox.showwarning("Falta o endereço", "Cole o endereço da página (ex.: https://site.com/videos).")
            return None, None
        try:
            opcoes = Opcoes(
                navegador=self.var_nav.get(), visivel=self.var_visivel.get(), pausar=self.var_pausar.get(),
                seletor=self.var_seletor.get().strip(), profundidade=int(self.var_prof.get()),
                max_paginas=int(self.var_maxp.get()), limite=int(self.var_limite.get()),
                espera=float(self.var_espera.get()), pasta=self.var_pasta.get().strip() or PASTA_PADRAO)
        except (tk.TclError, ValueError):
            messagebox.showwarning("Valor inválido", "Confira os números nas Opções.")
            return None, None
        return url, opcoes

    def _ajustar_checks(self) -> None:
        if self.var_pausar.get() or self.var_visivel.get():
            self.var_nav.set(True)            # pausar/mostrar janela só existem no modo navegador
        if self.var_pausar.get():
            self.var_visivel.set(True)

    def _botoes_ocupados(self, ocupado: bool) -> None:
        estado = "disabled" if ocupado else "normal"
        for b in (self.bt_buscar, self.bt_baixar_sel, self.bt_baixar_todos, self.bt_login):
            b.configure(state=estado)
        self.bt_parar.configure(state="normal" if ocupado else "disabled")

    def _limpar_tabela(self) -> None:
        self.links = []
        self.tabela.delete(*self.tabela.get_children())

    def _preencher_tabela(self, links: list[LinkVideo]) -> None:
        self._limpar_tabela()
        self.links = list(links)
        for i, l in enumerate(self.links):
            titulo = l.titulo or unquote(os.path.basename(urlparse(l.url).path)) or l.url
            self.tabela.insert("", "end", iid=str(i),
                               values=(i + 1, "", titulo, ORIGENS.get(l.tipo, l.tipo), l.url))

    def _marcar_item(self, url: str, status: str) -> None:
        textos = {"ok": "baixado", "pulado": "pulado", "erro": "erro"}
        for i, l in enumerate(self.links):
            if l.url == url:
                valores = list(self.tabela.item(str(i), "values"))
                valores[1] = textos.get(status, status)
                self.tabela.item(str(i), values=valores, tags=(status,))
                self.tabela.see(str(i))

    def _escrever_log(self, texto: str) -> None:
        texto = _so_caracteres_basicos(texto)
        self.log.configure(state="normal")
        partes = texto.split("\r")
        for n, parte in enumerate(partes):
            if n > 0:   # '\r' = voltar ao início da linha (barra de progresso do download)
                self.log.delete("end-1c linestart", "end-1c")
            self.log.insert("end", parte)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _link_selecionado(self) -> LinkVideo | None:
        ids = self.tabela.selection() or self.tabela.focus()
        if isinstance(ids, str):
            ids = (ids,) if ids else ()
        if not ids:
            messagebox.showinfo("Nenhum link", "Selecione um vídeo da lista primeiro.")
            return None
        return self.links[int(ids[0])]

    def _abrir_link(self) -> None:
        link = self._link_selecionado()
        if link:
            webbrowser.open(link.url)

    def _copiar_link(self) -> None:
        link = self._link_selecionado()
        if link:
            self.raiz.clipboard_clear()
            self.raiz.clipboard_append(link.url)
            self.var_status.set("Link copiado.")

    def _colar(self) -> None:
        try:
            self.var_url.set(self.raiz.clipboard_get().strip())
        except tk.TclError:
            pass

    def _escolher_pasta(self) -> None:
        pasta = filedialog.askdirectory(initialdir=self.var_pasta.get() or ".")
        if pasta:
            self.var_pasta.set(pasta)

    def _salvar_lista(self) -> None:
        if not self.links:
            messagebox.showinfo("Lista vazia", "Busque vídeos primeiro.")
            return
        caminho = filedialog.asksaveasfilename(
            defaultextension=".csv", initialfile="links.csv",
            filetypes=[("Planilha CSV", "*.csv"), ("JSON", "*.json"), ("Texto", "*.txt")])
        if caminho:
            salvar(self.links, caminho)
            self.var_status.set(f"Lista salva em {caminho}")

    def _abrir_pasta(self) -> None:
        pasta = self.var_pasta.get() or PASTA_PADRAO
        os.makedirs(pasta, exist_ok=True)
        if sys.platform.startswith("win"):
            os.startfile(pasta)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", pasta])

    def fechar(self) -> None:
        if self.trabalhando and not messagebox.askyesno("Sair", "Ainda está trabalhando. Sair mesmo assim?"):
            return
        self.evento_parar.set()
        sys.stdout, sys.stderr = self._stdout, self._stderr
        self.raiz.destroy()


def main() -> int:
    if sys.platform.startswith("win"):
        try:                                   # texto nítido em telas com zoom (Windows)
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    raiz = tk.Tk()
    App(raiz)
    raiz.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
