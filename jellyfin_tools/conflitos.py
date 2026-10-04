"""Resolver conflitos com um clique: fica a melhor cópia, a outra sai (sem apagar de vez).

Dois tipos de conflito saem da pré-visualização:
    cópia repetida      -> duas cópias do mesmo filme/episódio nos downloads (720p e 1080p): a pior sai
    já está na biblioteca -> o filme já existe no destino: compara as duas e fica a melhor
                           (se a nova for melhor, a antiga sai e a nova entra no lugar)

"Melhor" = maior resolução REAL do vídeo (lida pelo ffmpeg, porque na biblioteca o nome já não diz
"1080p"), depois a origem pelo nome (BluRay > WEB > DVD) e, no empate, o arquivo maior.

O que sai vai para '<pasta>/.organizador/removidos/<data>/' (o Jellyfin ignora pastas com ponto) e
"Desfazer última" põe tudo de volta. Para liberar o espaço de vez, apague essa pasta depois.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from .nomes import qualidade
from .organizador import PASTA_LOGS, Movimento, _gravar_log, _mesmo_arquivo

_RE_RESOLUCAO = re.compile(r"Video:.*?(\d{3,5})x(\d{3,5})")


@lru_cache(maxsize=4096)
def _altura_pelo_ffmpeg(caminho: str, tamanho: int) -> int:
    """Altura do vídeo (1080, 720...) lida do próprio arquivo; 0 se não der. (tamanho entra no cache)"""
    try:
        import imageio_ffmpeg
        r = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-i", caminho],
                           capture_output=True, text=True, errors="replace", timeout=30,
                           **({"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}))
        if m := _RE_RESOLUCAO.search(r.stderr):
            largura, altura = int(m.group(1)), int(m.group(2))
            return max(altura, round(largura * 9 / 16)) if largura >= altura else altura   # 1920x800 ~ 1080p
    except Exception:
        pass
    return 0


def nota(arquivo: Path) -> tuple[int, int, int]:
    """(resolução, origem, tamanho): quanto maior, melhor."""
    try:
        tamanho = arquivo.stat().st_size
    except OSError:
        tamanho = 0
    resolucao_nome, fonte, _ = qualidade(arquivo.name)
    return _altura_pelo_ffmpeg(str(arquivo), tamanho) or resolucao_nome, fonte, tamanho


def descricao(arquivo: Path) -> str:
    resolucao, _, tamanho = nota(arquivo)
    partes = [f"{resolucao}p" if resolucao else "", qualidade(arquivo.name)[2].split(" ")[-1] if
              qualidade(arquivo.name)[2] else "", f"{tamanho / 1024 ** 3:.1f} GB" if tamanho >= 1024 ** 3
              else f"{tamanho / 1024 ** 2:.0f} MB"]
    return ", ".join(dict.fromkeys(p for p in partes if p))


@dataclass
class Decisao:
    movimento: Movimento
    fica: Path
    sai: Path
    substitui: bool          # True: a nova entra no lugar da que já estava na biblioteca

    def texto(self) -> str:
        acao = "troca a da biblioteca pela nova" if self.substitui else "fica a que está"
        return (f"{self.movimento.destino.name if self.movimento.destino else self.fica.name}: {acao}\n"
                f"   fica: {self.fica.name} ({descricao(self.fica)})\n"
                f"   sai:  {self.sai.name} ({descricao(self.sai)})")


def decidir(movimentos: list[Movimento], escolhidos: list[Movimento] | None = None) -> list[Decisao]:
    """O que fazer com cada conflito (dos escolhidos; sem escolha, de todos)."""
    alvos = [m for m in (escolhidos if escolhidos else movimentos) if m.status == "conflito" and m.destino]
    vai = {str(m.destino).lower(): m for m in movimentos if m.status == "simulado" and m.destino}
    decisoes = []
    for m in alvos:
        if m.destino.exists() and not _mesmo_arquivo(m.destino, m.origem):      # já está na biblioteca
            if nota(m.origem) > nota(m.destino):
                decisoes.append(Decisao(m, m.origem, m.destino, True))
            else:
                decisoes.append(Decisao(m, m.destino, m.origem, False))
        elif melhor := vai.get(str(m.destino).lower()):                          # cópia repetida
            decisoes.append(Decisao(m, melhor.origem, m.origem, False))
    return decisoes


def _raiz_de(arquivo: Path, raizes: list[Path]) -> Path:
    for raiz in raizes:
        try:
            arquivo.resolve().relative_to(raiz.resolve())
            return raiz
        except ValueError:
            continue
    return arquivo.parent


def aplicar(decisoes: list[Decisao], biblioteca: Path, origem: Path | None = None) -> tuple[int, list[str]]:
    """Tira o pior de cada conflito (para .organizador/removidos, na mesma pasta: não copia entre discos)
    e, quando a nova é melhor, põe a nova no lugar. Grava o log na biblioteca ("Desfazer última")."""
    agora = f"{datetime.now():%Y%m%d-%H%M%S-%f}"
    raizes = [r for r in (biblioteca, origem) if r]
    guardados, itens, lixeiras, mensagens = [], [], [], []
    for d in decisoes:
        raiz = _raiz_de(d.sai, raizes)
        lixeira = raiz / PASTA_LOGS / "removidos" / agora
        try:
            relativo = d.sai.resolve().relative_to(raiz.resolve())
        except ValueError:
            relativo = Path(d.sai.name)
        para = lixeira / relativo
        try:
            para.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(d.sai), str(para))
            guardados.append({"de": str(d.sai), "para": str(para)})
            if str(lixeira) not in lixeiras:
                lixeiras.append(str(lixeira))
            mensagens.append(f"saiu (pior cópia): {d.sai}")
            if d.substitui:
                m = d.movimento
                shutil.move(str(m.origem), str(m.destino))
                itens.append((m.origem, m.destino))
                for de, ate in m.acompanhantes or []:          # legenda da cópia nova vai junto
                    if de.exists() and not ate.exists():
                        shutil.move(str(de), str(ate))
                        itens.append((de, ate))
                mensagens.append(f"entrou no lugar: {m.destino}")
        except OSError as erro:
            mensagens.append(f"erro em {d.sai}: {erro}")
    if guardados:
        _gravar_log(biblioteca, itens, extra={"espelhos_guardados": guardados, "lixeiras": lixeiras})
    return len(guardados), mensagens
