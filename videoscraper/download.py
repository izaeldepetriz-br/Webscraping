"""Salva vídeos no disco: arquivo direto (em blocos) ou streaming HLS/DASH (via ffmpeg)."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from urllib.parse import unquote, urlparse

import requests

from .extracao import LinkVideo, eh_embed_de_video, eh_streaming, parece_video
from .rede import ClienteHTTP

# No Windows, evita abrir uma tela preta extra ao chamar o ffmpeg.
SEM_JANELA = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}

EXTENSOES_ARQUIVO = (".mp4", ".webm", ".mkv", ".mov", ".m4v", ".avi", ".ogv")


class NaoBaixavel(Exception):
    """O link existe, mas não é algo que este programa deva/consiga baixar."""


def nome_seguro(texto: str, padrao: str) -> str:
    """Título -> nome de arquivo válido no Windows/Linux (sem / \\ : * ? " < > |)."""
    limpo = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", texto or "")
    limpo = re.sub(r"\s+", " ", limpo).strip(" .")
    return limpo[:120] or padrao


def extensao_da_url(url: str) -> str:
    ext = os.path.splitext(urlparse(url).path)[1].lower()
    return ext if ext in EXTENSOES_ARQUIVO else ".mp4"   # streaming vira .mp4


def caminho_livre(pasta: str, base: str, ext: str) -> str:
    """Não sobrescreve: se 'aula.mp4' existe, devolve 'aula (2).mp4'."""
    caminho = os.path.join(pasta, base + ext)
    n = 2
    while os.path.exists(caminho):
        caminho = os.path.join(pasta, f"{base} ({n}){ext}")
        n += 1
    return caminho


def localizar_ffmpeg() -> str | None:
    """ffmpeg do sistema; se não houver, o que vem no pacote imageio-ffmpeg."""
    caminho = shutil.which("ffmpeg")
    if caminho:
        return caminho
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def baixar_arquivo(sessao: requests.Session, url: str, destino: str,
                   referer: str | None = None, timeout: float = 30) -> None:
    """Baixa em blocos de 1 MB para um '.part' e só renomeia se terminar bem."""
    parcial = destino + ".part"
    cabecalhos = {"Referer": referer} if referer else {}
    try:
        with sessao.get(url, stream=True, timeout=timeout, headers=cabecalhos) as r:
            r.raise_for_status()
            if "text/html" in r.headers.get("Content-Type", "").lower():
                raise NaoBaixavel("o endereço devolveu uma página HTML, não um vídeo "
                                  "(pode exigir login: use o comando 'login' e --navegador)")
            total = int(r.headers.get("Content-Length", 0))
            baixado = 0
            with open(parcial, "wb") as f:
                for bloco in r.iter_content(chunk_size=1024 * 1024):
                    f.write(bloco)
                    baixado += len(bloco)
                    if total:
                        print(f"\r   {baixado / total:5.1%} ({baixado / 1e6:.1f}/{total / 1e6:.1f} MB)",
                              end="", flush=True)
        if total:
            print()
        os.replace(parcial, destino)
    finally:
        if os.path.exists(parcial):
            os.remove(parcial)


def baixar_streaming(sessao: requests.Session, url: str, destino: str,
                     referer: str | None = None) -> None:
    """HLS (.m3u8) / DASH (.mpd): o vídeo vem em pedaços; o ffmpeg junta tudo num .mp4.
    Vídeos com DRM (Netflix, Globoplay etc.) NÃO funcionam, e não devem ser contornados."""
    ffmpeg = localizar_ffmpeg()
    if not ffmpeg:
        raise NaoBaixavel("é streaming (.m3u8/.mpd) e precisa do ffmpeg. Instale com: "
                          "pip install imageio-ffmpeg")
    # Repassa ao ffmpeg os mesmos cabeçalhos/cookies da sessão (importante em sites com login).
    preparado = sessao.prepare_request(requests.Request("GET", url))
    cabecalhos = {"User-Agent": preparado.headers.get("User-Agent", "")}
    if preparado.headers.get("Cookie"):
        cabecalhos["Cookie"] = preparado.headers["Cookie"]
    if referer:
        cabecalhos["Referer"] = referer
    texto_cabecalhos = "".join(f"{k}: {v}\r\n" for k, v in cabecalhos.items())

    parcial = destino + ".part"
    comando = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
               "-headers", texto_cabecalhos, "-i", url,
               "-c", "copy", "-bsf:a", "aac_adtstoasc", "-f", "mp4", parcial]
    print("   🎞  streaming: juntando os pedaços com ffmpeg (pode demorar)...")
    try:
        resultado = subprocess.run(comando, capture_output=True, text=True, **SEM_JANELA)
        if resultado.returncode != 0:
            raise RuntimeError("ffmpeg falhou: " + (resultado.stderr.strip()[-400:] or "sem detalhes"))
        os.replace(parcial, destino)
    finally:
        if os.path.exists(parcial):
            os.remove(parcial)


def baixar_video(cliente: ClienteHTTP, link: LinkVideo, pasta: str, indice: int) -> str:
    """Decide COMO baixar o link e devolve o caminho salvo. Lança exceção se não der."""
    if eh_embed_de_video(link.url) and not parece_video(link.url):
        raise NaoBaixavel("é um player de outro site (YouTube, Vimeo...), não um arquivo de vídeo")
    if not cliente.permitido(link.url):
        raise NaoBaixavel("robots.txt não permite este endereço")

    padrao = unquote(os.path.splitext(os.path.basename(urlparse(link.url).path))[0]) or f"video_{indice}"
    destino = caminho_livre(pasta, nome_seguro(link.titulo, padrao), extensao_da_url(link.url))
    cliente.pausar()
    if eh_streaming(link.url):
        baixar_streaming(cliente.sessao, link.url, destino, referer=link.origem)
    else:
        baixar_arquivo(cliente.sessao, link.url, destino, referer=link.origem, timeout=cliente.timeout)
    return destino
