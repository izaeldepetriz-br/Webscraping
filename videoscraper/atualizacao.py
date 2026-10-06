"""Aviso de versão nova: ao abrir, consulta a página Releases do GitHub (uma chamada, ~1 KB).

    versão deste programa: o .exe gerado pelo GitHub traz 'versao_build.txt' (ex.: v1.5); rodando pelo
    Python, vale o __version__ do pacote.
    versão mais nova: GET https://api.github.com/repos/<dono>/<repo>/releases/latest -> tag_name

Nada é instalado sozinho. Dá para BAIXAR o .zip da versão nova sem fechar o programa (vai para a
pasta Downloads); trocar a pasta do programa pela nova é com você, com o programa fechado (o Windows
não deixa substituir um programa que está aberto).
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

import requests

from . import __version__

REPOSITORIO = "izaeldepetriz-br/Webscraping"
API = "https://api.github.com"


def versao_atual() -> str:
    """A versão deste programa (a do .exe, gravada pelo GitHub ao gerar; senão a do código).

    O número gravado fica na pasta _internal, mas o código das telas fica DENTRO do Maestro.exe. Se uma
    atualização trocou a _internal e não conseguiu trocar o .exe (outra janela do Maestro aberta o segurava), os
    dois discordam: vale o MENOR, para o programa não se dizer atualizado e oferecer a versão nova de novo."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    for arquivo in (base / "videoscraper" / "versao_build.txt", Path(__file__).with_name("versao_build.txt")):
        try:
            texto = arquivo.read_text(encoding="utf-8").strip()
            if texto:
                return texto if numeros(texto) <= numeros(__version__) else "v" + __version__
        except OSError:
            continue
    return __version__


def numeros(versao: str) -> tuple[int, ...]:
    """'v1.10.2' -> (1, 10, 2): compara número por número (1.10 é mais nova que 1.9)."""
    return tuple(int(n) for n in re.findall(r"\d+", versao)[:4]) or (0,)


@dataclass
class VersaoNova:
    versao: str
    url: str                      # a página da versão (Releases)
    notas: str = ""
    arquivo_url: str = ""         # o .zip do programa para Windows (Assets)
    arquivo_nome: str = ""


class ErroAtualizacao(Exception):
    pass


def ultima_versao(api: str = API, repositorio: str = REPOSITORIO, timeout: float = 6) -> VersaoNova:
    """A versão mais nova publicada (seja qual for). Lança ErroAtualizacao dizendo o motivo."""
    try:
        r = requests.get(f"{api.rstrip('/')}/repos/{repositorio}/releases/latest", timeout=timeout,
                         headers={"Accept": "application/vnd.github+json"})
    except requests.RequestException as erro:
        raise ErroAtualizacao(f"sem conexão com o GitHub ({type(erro).__name__})") from erro
    if r.status_code == 404:
        raise ErroAtualizacao("nenhuma versão publicada ainda")
    if not r.ok:
        raise ErroAtualizacao(f"o GitHub respondeu HTTP {r.status_code}")
    try:
        dados = r.json()
    except ValueError as erro:
        raise ErroAtualizacao("resposta inesperada do GitHub") from erro
    tag = str(dados.get("tag_name") or "")
    if not tag:
        raise ErroAtualizacao("a versão publicada não tem número")
    zip_ = next((a for a in dados.get("assets") or [] if str(a.get("name", "")).lower().endswith(".zip")), {})
    return VersaoNova(tag, str(dados.get("html_url") or f"https://github.com/{repositorio}/releases/latest"),
                      str(dados.get("body") or "").strip()[:600], str(zip_.get("browser_download_url") or ""),
                      str(zip_.get("name") or ""))


def verificar(atual: str | None = None, api: str = API, repositorio: str = REPOSITORIO,
              timeout: float = 6) -> VersaoNova | None:
    """A versão mais nova publicada, se for mais nova que esta; None se não houver (ou sem internet)."""
    try:
        nova = ultima_versao(api, repositorio, timeout)
    except ErroAtualizacao:
        return None
    return nova if numeros(nova.versao) > numeros(atual or versao_atual()) else None


def pasta_downloads() -> Path:
    pasta = Path.home() / "Downloads"
    return pasta if pasta.is_dir() else Path.home()


def baixar(nova: VersaoNova, pasta: Path | None = None, ao_progresso=None, parar=None, timeout: float = 30) -> Path:
    """Baixa o .zip da versão nova (sem fechar o programa). ao_progresso(baixados, total); parar() -> True
    interrompe. Devolve o arquivo salvo (ex.: Downloads/videoscraper-windows-v1.6.zip)."""
    if not nova.arquivo_url:
        raise ErroAtualizacao("a versão nova não tem o .zip para Windows; use a página de download")
    pasta = Path(pasta or pasta_downloads())
    pasta.mkdir(parents=True, exist_ok=True)
    nome = Path(nova.arquivo_nome or "videoscraper-windows.zip")
    destino = pasta / f"{nome.stem}-{nova.versao}{nome.suffix or '.zip'}"
    parcial = destino.with_name(destino.name + ".part")
    try:
        with requests.get(nova.arquivo_url, stream=True, timeout=timeout) as r:
            r.raise_for_status()
            total, feitos = int(r.headers.get("Content-Length") or 0), 0
            with open(parcial, "wb") as f:
                for pedaco in r.iter_content(256 * 1024):
                    if parar and parar():
                        raise ErroAtualizacao("download interrompido")
                    f.write(pedaco)
                    feitos += len(pedaco)
                    if ao_progresso:
                        ao_progresso(feitos, total)
    except requests.RequestException as erro:
        parcial.unlink(missing_ok=True)
        raise ErroAtualizacao(f"o download falhou ({type(erro).__name__})") from erro
    except ErroAtualizacao:
        parcial.unlink(missing_ok=True)
        raise
    parcial.replace(destino)
    return destino


# ----------------------------------------------------------------- instalar (com o programa FECHADO)
# Um programa aberto não pode ser substituído no Windows. Por isso a troca é feita por um pequeno script
# do PowerShell que ESPERA o programa fechar, extrai o .zip por cima da pasta do programa e (se pedido)
# abre a versão nova. As configurações ficam em C:\Users\<você>\.videoscraper e não são tocadas.
def pode_instalar_sozinho() -> bool:
    """Só o .exe no Windows (rodando pelo Python, quem atualiza é o 'Download ZIP' do código)."""
    return sys.platform == "win32" and bool(getattr(sys, "frozen", False))


def pasta_do_programa() -> Path:
    return Path(sys.executable).resolve().parent


def script_de_instalacao(zip_: Path, pasta: Path, pid: int, executavel: str = "") -> str:
    """O script do PowerShell (texto). executavel vazio = não reabre o programa no fim."""
    def aspas(texto) -> str:
        return "'" + str(texto).replace("'", "''") + "'"
    reabrir = f"Start-Process -FilePath {aspas(executavel)}" if executavel else "# (não reabre)"
    return f"""$ErrorActionPreference = 'Stop'
$zip = {aspas(zip_)}
$pasta = {aspas(pasta)}
$log = Join-Path $env:TEMP 'videoscraper-atualizacao.log'
"Atualizando $pasta com $zip" | Out-File $log
Wait-Process -Id {int(pid)} -ErrorAction SilentlyContinue      # espera o programa fechar
# Outra janela do programa aberta (ex.: a da bandeja, do "Iniciar com o Windows") segura o .exe: o Windows não
# deixa trocá-lo, e só a pasta _internal mudaria. Espera até 30 s e depois fecha as que sobraram.
$prefixo = $pasta.TrimEnd('\\') + '\\'
function Abertos {{ @(Get-Process -ErrorAction SilentlyContinue | Where-Object {{ $_.Path -and $_.Path.StartsWith($prefixo, [StringComparison]::OrdinalIgnoreCase) }}) }}
for ($i = 0; $i -lt 30 -and (Abertos).Count -gt 0; $i++) {{ Start-Sleep -Seconds 1 }}
foreach ($p in Abertos) {{
    "Fechando $($p.Path) (processo $($p.Id))" | Out-File $log -Append
    Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
}}
Start-Sleep -Seconds 1
$tmp = Join-Path $env:TEMP ('videoscraper-novo-' + [guid]::NewGuid())
try {{
    Expand-Archive -Path $zip -DestinationPath $tmp -Force
    $novo = $tmp
    if (-not (Test-Path (Join-Path $tmp 'videoscraper.exe'))) {{
        $novo = (Get-ChildItem $tmp -Directory | Where-Object {{ Test-Path (Join-Path $_.FullName 'videoscraper.exe') }} | Select-Object -First 1).FullName
    }}
    if (-not $novo) {{ throw 'o .zip não tem o videoscraper.exe' }}
    robocopy $novo $pasta /E /R:5 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) {{ throw "robocopy falhou ($LASTEXITCODE)" }}
    "OK" | Out-File $log -Append
}} catch {{
    "ERRO: $_" | Out-File $log -Append
}} finally {{
    Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
}}
{reabrir}
"""


ultimo_processo = None        # o PowerShell da última chamada (para o autoteste)


def instalar_ao_fechar(zip_: Path, reabrir: bool = True, pasta: Path | None = None, pid: int | None = None) -> Path:
    """Deixa o script rodando em segundo plano (escondido): ele espera ESTE programa fechar e troca os
    arquivos. Devolve o caminho do script. Chame logo antes de fechar o programa."""
    import os
    import subprocess
    import tempfile
    pasta = Path(pasta or pasta_do_programa())
    # reabre o MESMO .exe que está aberto (Maestro.exe; nas versões antigas, videoscraper.exe)
    nome = Path(sys.executable).name if getattr(sys, "frozen", False) else "videoscraper.exe"
    executavel = str(pasta / nome) if reabrir else ""
    script = Path(tempfile.gettempdir()) / "videoscraper-atualizar.ps1"
    script.write_text(script_de_instalacao(Path(zip_), pasta, pid or os.getpid(), executavel), encoding="utf-8-sig")
    # O .exe não tem console (nem stdin/stdout): o processo novo NÃO pode herdar essas saídas (o Windows
    # recusa com "identificador inválido"). A entrada vem de DEVNULL e as saídas vão para um arquivo de
    # texto (se o PowerShell reclamar de algo, o motivo fica registrado ali).
    global ultimo_processo
    saida = open(Path(tempfile.gettempdir()) / "videoscraper-atualizar-saida.txt", "w", encoding="utf-8")
    opcoes = dict(stdin=subprocess.DEVNULL, stdout=saida, stderr=subprocess.STDOUT, close_fds=True)
    powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    comando = [str(powershell) if powershell.exists() else "powershell", "-NoProfile", "-NonInteractive",
               "-ExecutionPolicy", "Bypass", "-File", str(script)]
    try:
        if sys.platform == "win32":
            # Sem janela (CREATE_NO_WINDOW: o PowerShell ganha um console invisível, coisa que ele precisa) e
            # fora do "grupo" deste programa, para continuar vivo depois que ele fechar. Se o Windows não
            # deixar sair do "job" (BREAKAWAY), tenta de novo sem isso.
            base = 0x08000000 | 0x00000200          # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
            try:
                ultimo_processo = subprocess.Popen(comando, creationflags=base | 0x01000000, **opcoes)
            except OSError:
                ultimo_processo = subprocess.Popen(comando, creationflags=base, **opcoes)
        else:
            ultimo_processo = subprocess.Popen(comando, start_new_session=True, **opcoes)
    finally:
        saida.close()                               # o processo novo já tem a cópia dele
    return script
