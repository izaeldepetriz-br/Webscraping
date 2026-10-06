"""Memória dos vídeos já baixados (aba Vídeos).

Cada download que deu certo fica guardado em C:\\Users\\<você>\\.videoscraper\\baixados.json: o link, quando foi
baixado, o arquivo e o título. Numa busca nova (hoje ou daqui a um mês), os que já foram baixados aparecem como
"já baixado" e o "Baixar" pergunta se pula esses, para não baixar duas vezes.

Um link de archive.org é sempre o mesmo. Alguns sites mudam o endereço a cada visita (?token=...): para esses,
vale também a combinação página de origem + título.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urldefrag


def _chave_link(url: str) -> str:
    return urldefrag(url.strip())[0]


def _chave_pagina(origem: str, titulo: str) -> str:
    return f"{_chave_link(origem)}|{titulo.strip().casefold()}" if origem and titulo and titulo.strip() else ""


class MemoriaDownloads:
    """Lê uma vez, grava a cada download (de várias threads ao mesmo tempo, com trava)."""

    def __init__(self, arquivo: str | Path):
        self.arquivo = Path(arquivo)
        self._trava = threading.Lock()
        self._itens: dict[str, dict] | None = None
        self._por_pagina: dict[str, str] = {}

    def _carregar(self) -> dict[str, dict]:
        if self._itens is None:
            try:
                dados = json.loads(self.arquivo.read_text(encoding="utf-8"))
                self._itens = {k: v for k, v in dados.items() if isinstance(v, dict)} if isinstance(dados, dict) else {}
            except (OSError, ValueError):
                self._itens = {}
            self._por_pagina = {v["pagina"]: k for k, v in self._itens.items() if v.get("pagina")}
        return self._itens

    def _gravar(self) -> None:
        self.arquivo.parent.mkdir(parents=True, exist_ok=True)
        temporario = self.arquivo.with_suffix(".tmp")
        temporario.write_text(json.dumps(self._itens, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(temporario, self.arquivo)              # nunca fica meio gravado

    def registrar(self, link, arquivo: str = "", quando: datetime | None = None) -> None:
        with self._trava:
            itens = self._carregar()
            chave = _chave_link(link.url)
            pagina = _chave_pagina(getattr(link, "origem", ""), getattr(link, "titulo", ""))
            itens[chave] = {"quando": (quando or datetime.now()).isoformat(timespec="seconds"),
                            "arquivo": str(arquivo or ""), "titulo": getattr(link, "titulo", "") or "",
                            "pagina": pagina}
            if pagina:
                self._por_pagina[pagina] = chave
            self._gravar()

    def baixado(self, link) -> dict | None:
        """O registro do download (quando, arquivo, título) ou None se nunca foi baixado."""
        with self._trava:
            itens = self._carregar()
            if registro := itens.get(_chave_link(link.url)):
                return registro
            pagina = _chave_pagina(getattr(link, "origem", ""), getattr(link, "titulo", ""))
            return itens.get(self._por_pagina.get(pagina, "")) if pagina else None

    def esquecer(self, links) -> int:
        """Tira da memória (para baixar de novo sem perguntar). Devolve quantos saíram."""
        with self._trava:
            itens = self._carregar()
            saiu = 0
            for link in links:
                chave = _chave_link(link.url)
                pagina = _chave_pagina(getattr(link, "origem", ""), getattr(link, "titulo", ""))
                chave = chave if chave in itens else self._por_pagina.get(pagina, "")
                if registro := itens.pop(chave, None):
                    self._por_pagina.pop(registro.get("pagina", ""), None)
                    saiu += 1
            if saiu:
                self._gravar()
            return saiu

    def _antigas(self, dias: int, agora: datetime) -> list[str]:
        """Chaves baixadas há MAIS de `dias` dias (dias=0: todas)."""
        limite = agora - timedelta(days=dias)
        antigas = []
        for chave, registro in self._carregar().items():
            try:
                quando = datetime.fromisoformat(registro.get("quando", ""))
            except ValueError:
                quando = datetime.min                       # sem data: conta como antiga
            if not dias or quando < limite:
                antigas.append(chave)
        return antigas

    def quantos_antigos(self, dias: int, agora: datetime | None = None) -> int:
        with self._trava:
            return len(self._antigas(dias, agora or datetime.now()))

    def esquecer_antigos(self, dias: int, agora: datetime | None = None) -> int:
        """Limpa a memória por período: os baixados há mais de `dias` dias (0 = tudo). Devolve quantos saíram."""
        with self._trava:
            antigas = self._antigas(dias, agora or datetime.now())
            for chave in antigas:
                registro = self._itens.pop(chave)
                self._por_pagina.pop(registro.get("pagina", ""), None)
            if antigas:
                self._gravar()
            return len(antigas)

    def tamanho(self) -> int:
        """Tamanho do arquivo da memória em bytes (0 se ainda não existe)."""
        try:
            return self.arquivo.stat().st_size
        except OSError:
            return 0

    def __len__(self) -> int:
        with self._trava:
            return len(self._carregar())


def texto_quando(registro: dict) -> str:
    """'05/10/2026' (o dia em que foi baixado)."""
    try:
        return datetime.fromisoformat(registro.get("quando", "")).strftime("%d/%m/%Y")
    except ValueError:
        return ""
