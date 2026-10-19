"""Abrir a ISO do SEU disco de PS2 para o modo "Traduzir e dublar (no PC)" da aba 🎮 Jogos: ver o que tem dentro,
tirar as falas que o Maestro sabe trocar e, no fim, montar a ISO em português (numa CÓPIA) com as falas dubladas
no MESMO lugar.

    analisar(iso)       a lista de todos os arquivos do disco (ISO 9660), quanto ocupa cada tipo, e o que tem som:
                        falas .VAG/.ADS/.WAV soltas e falas VAG guardadas dentro dos "pacotões" (.BIN, .PAK...),
                        achadas pela marca "VAGp" do começo de cada uma. Os formatos que o Maestro ainda não abre
                        (RenderWare .RWS, .AWD, .BNK, .XA, .ADX...) aparecem no relatório: é o que mostra o próximo
                        passo para aquele jogo. O relatório vira um .txt para mandar a quem for ajudar.
    extrair(...)        as falas em audio\\ (o nome diz de onde veio) + mapa_iso.json (onde cada uma fica no disco)
    montar(...)         copia a ISO e grava cada fala dublada por cima da original, no mesmo byte: como a fala nova
                        tem o MESMO tamanho (audio_jogo.gravar_como), nada no disco sai do lugar e o jogo acha tudo

Por que no mesmo lugar: muitos jogos de PS2 acham os arquivos pela posição exata no disco (o setor), não pelo nome.
Um programa genérico de ISO reorganiza o disco ao salvar, e o jogo trava. Aqui nenhum byte fora das falas muda.
Só ISO de DVD (setor de 2048 bytes); a de CD em .bin (2352 bytes) tem códigos de correção em cada setor.
"""

from __future__ import annotations

import json
import os
import struct
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from . import audio_jogo
from .patch_jogo import BLOCO, ErroPatch, _formato_iso, _ler, conferir_espaco, ler_info, tamanho_legivel

ARQUIVO_MAPA = "mapa_iso.json"
PASTA_AUDIO = "audio"
MARCA_VAG = b"VAGp"
TAXAS_VAG = range(4000, 48001)
MAIOR_VAG = 16 * 1024 * 1024             # uma fala de VAG maior que isso é engano (é música, ou não é VAG)
# os sons que o Maestro ainda não troca: o nome do formato (para o relatório)
OUTROS_SONS = {
    ".RWS": "RenderWare Audio (RWS)", ".AWD": "RenderWare Wave Dictionary (AWD)", ".BNK": "banco de sons (BNK)",
    ".XA": "CD-XA", ".ADX": "CRI ADX", ".AHX": "CRI AHX", ".AFS": "pacote CRI AFS (costuma ter ADX)",
    ".AT3": "ATRAC3", ".VPK": "VPK", ".VB": "banco de sons VB", ".VH": "cabeçalho de banco VH", ".BD": "banco BD",
    ".HD": "cabeçalho de banco HD", ".SS2": "SS2", ".MIB": "MIB", ".STR": "stream (vídeo ou som)", ".MIC": "MIC",
    ".SPU": "SPU", ".SND": "som (SND)", ".SFX": "efeitos (SFX)", ".MUS": "música (MUS)", ".WP2": "WP2",
}
VIDEOS = {".PSS": "vídeo PSS (as cenas: o som está dentro do vídeo)", ".IPU": "vídeo IPU", ".PSM": "vídeo PSM",
          ".M2V": "vídeo MPEG-2", ".BIK": "vídeo Bink"}
RWS_ID = 0x0000080D                      # o primeiro pedaço de um arquivo RenderWare Audio


@dataclass
class ArquivoISO:
    caminho: str                         # "SOUND/VOZES.BIN"
    setor: int
    tamanho: int

    @property
    def inicio(self) -> int:
        return self.setor * 2048

    @property
    def extensao(self) -> str:
        return Path(self.caminho).suffix.upper()


@dataclass
class Fala:
    """Uma fala que o Maestro sabe trocar: onde está no disco e onde ficou na pasta."""
    relativo: str                        # "audio/SOUND/VOZES.BIN/00012800_JIM_01.vag"
    inicio: int                          # o byte na ISO
    tamanho: int
    origem: str                          # o arquivo do disco onde ela está
    formato: str                         # "vag", "ads" ou "wav"
    solta: bool                          # o próprio arquivo do disco (True) ou dentro de um pacote (False)


@dataclass
class Analise:
    iso: Path
    id_jogo: str
    descricao: str
    tamanho: int
    setor: int                           # 2048 (ISO de DVD) ou 2352 (BIN de CD)
    arquivos: list = field(default_factory=list)
    falas: list = field(default_factory=list)
    outros_sons: Counter = field(default_factory=Counter)      # {formato: quantos arquivos}
    videos: Counter = field(default_factory=Counter)
    pacotes_com_vag: Counter = field(default_factory=Counter)  # {arquivo do disco: quantas falas VAG dentro}

    @property
    def por_extensao(self) -> list[tuple[str, int, int]]:
        """[(extensão, quantos, bytes)], dos que mais ocupam para os que menos."""
        conta: dict[str, list[int]] = {}
        for a in self.arquivos:
            item = conta.setdefault(a.extensao or "(sem)", [0, 0])
            item[0] += 1
            item[1] += a.tamanho
        return sorted(((e, n, b) for e, (n, b) in conta.items()), key=lambda x: -x[2])

    @property
    def pode_trocar(self) -> bool:
        return bool(self.falas) and self.setor == 2048

    def resumo(self) -> str:
        """Uma linha para a tela."""
        if not self.falas:
            outros = ", ".join(f"{n} {f}" for f, n in self.outros_sons.most_common(3))
            return "nenhuma fala que o Maestro já saiba trocar" + (f" (achei {outros}: veja o relatório)"
                                                                   if outros else "")
        soltas = sum(1 for f in self.falas if f.solta)
        dentro = len(self.falas) - soltas
        partes = [f"{soltas} soltas" if soltas else "", f"{dentro} dentro de {len(self.pacotes_com_vag)} pacote(s)"
                  if dentro else ""]
        return f"{len(self.falas)} falas que o Maestro troca (" + ", ".join(p for p in partes if p) + ")"


# ----------------------------------------------------------------- a lista dos arquivos (ISO 9660)
def _registros(dados: bytes):
    pos = 0
    while pos < len(dados):
        n = dados[pos]
        if n == 0:                                          # o resto do setor está vazio
            pos = (pos // 2048 + 1) * 2048
            continue
        registro = dados[pos:pos + n]
        pos += n
        if len(registro) < 34:
            continue
        nome = registro[33:33 + registro[32]]
        if nome in (b"\x00", b"\x01"):
            continue
        setor, tamanho = struct.unpack_from("<I", registro, 2)[0], struct.unpack_from("<I", registro, 10)[0]
        yield nome.decode("ascii", "replace").split(";")[0], setor, tamanho, bool(registro[25] & 2)


def listar(iso: str | Path) -> tuple[list[ArquivoISO], int]:
    """([todos os arquivos do disco], tamanho do setor)."""
    iso = Path(iso)
    with open(iso, "rb") as f:
        formato = _formato_iso(f)
        if formato is None:
            raise ErroPatch(f"{iso.name} não parece uma imagem de disco (ISO 9660)")
        pvd = _ler(f, formato, 16, 2048)
        raiz = pvd[156:190]
        pendentes = [("", struct.unpack_from("<I", raiz, 2)[0], struct.unpack_from("<I", raiz, 10)[0])]
        vistos, arquivos = set(), []
        while pendentes:
            pasta, setor, tamanho = pendentes.pop()
            if setor in vistos or len(vistos) > 20000:
                continue
            vistos.add(setor)
            for nome, s, t, eh_pasta in _registros(_ler(f, formato, setor, min(tamanho, 512 * 2048))):
                caminho = f"{pasta}/{nome}" if pasta else nome
                if eh_pasta:
                    pendentes.append((caminho, s, t))
                else:
                    arquivos.append(ArquivoISO(caminho, s, t))
    return sorted(arquivos, key=lambda a: a.setor), formato[0]


# ----------------------------------------------------------------- o que tem som
def _vag_valido(cabecalho: bytes, sobra: int) -> int | None:
    """O tamanho total (cabeçalho + som) do VAG que começa aqui, ou None se não é um VAG de verdade."""
    if len(cabecalho) < 48 or cabecalho[:4] != MARCA_VAG:
        return None
    dados, taxa = struct.unpack_from(">I", cabecalho, 12)[0], struct.unpack_from(">I", cabecalho, 16)[0]
    if taxa not in TAXAS_VAG or not 16 <= dados <= MAIOR_VAG or dados % 16 or 48 + dados > sobra:
        return None
    return 48 + dados


def _nome_seguro(texto: str) -> str:
    limpo = "".join(c if c.isalnum() or c in "-_." else "_" for c in texto).strip("._")
    return limpo[:40] or "fala"


def analisar(iso: str | Path, parar=None, ao_progresso=None) -> Analise:
    """O que tem dentro da ISO: os arquivos, os sons e as falas que o Maestro troca (VAG/ADS/WAV soltos e VAG dentro
    dos pacotes). Lê o disco inteiro uma vez (~1 a 2 minutos num DVD)."""
    iso = Path(iso)
    info = ler_info(iso)
    arquivos, setor = listar(iso)
    analise = Analise(iso, info.id_jogo, info.descrever(), info.tamanho, setor, arquivos)
    progresso = ao_progresso or (lambda f: None)
    total = max(1, sum(a.tamanho for a in arquivos))
    lido = 0
    with open(iso, "rb") as f:
        formato = _formato_iso(f)
        for a in arquivos:
            if parar and parar():
                raise ErroPatch("interrompido (botão Parar)")
            ext = a.extensao
            if ext in VIDEOS:
                analise.videos[VIDEOS[ext]] += 1
            inicio = _ler(f, formato, a.setor, min(a.tamanho, 64)) if a.tamanho else b""
            if inicio[:4] in (MARCA_VAG, b"SShd") or (inicio[:4] == b"RIFF" and inicio[8:12] == b"WAVE"):
                tipo = {MARCA_VAG: "vag", b"SShd": "ads"}.get(inicio[:4], "wav")
                if tipo != "vag" or _vag_valido(inicio, a.tamanho):
                    analise.falas.append(Fala(f"{PASTA_AUDIO}/{a.caminho}", a.inicio, a.tamanho, a.caminho, tipo,
                                              True))
                    lido += a.tamanho
                    progresso(lido / total)
                    continue
            if len(inicio) >= 4 and struct.unpack_from("<I", inicio, 0)[0] == RWS_ID or ext in OUTROS_SONS:
                analise.outros_sons[OUTROS_SONS.get(ext, "RenderWare Audio (RWS)")] += 1
            if setor == 2048 and a.tamanho > 64 and ext not in VIDEOS:
                _procurar_vag(f, a, analise, parar)
            lido += a.tamanho
            progresso(lido / total)
    progresso(1.0)
    return analise


def _procurar_vag(f, a: ArquivoISO, analise: Analise, parar) -> None:
    """As falas VAG guardadas dentro de um pacote: cada uma começa com "VAGp" e diz o próprio tamanho."""
    pos, fim, sobra = a.inicio, a.inicio + a.tamanho, b""
    proximo_livre = 0                                     # (um "VAGp" no meio do som de outra fala não conta)
    while pos < fim:
        if parar and parar():
            raise ErroPatch("interrompido (botão Parar)")
        f.seek(pos)
        bloco = f.read(min(BLOCO, fim - pos))
        if not bloco:
            break
        dados = sobra + bloco
        base = pos - len(sobra)
        achado = dados.find(MARCA_VAG)
        while achado != -1:
            if base + achado >= proximo_livre:
                f.seek(base + achado)
                cabecalho = f.read(48)
                tamanho = _vag_valido(cabecalho, fim - (base + achado))
                if tamanho:
                    nome = cabecalho[32:48].split(b"\x00")[0].decode("ascii", "replace")
                    deslocamento = base + achado - a.inicio
                    analise.falas.append(Fala(
                        f"{PASTA_AUDIO}/{a.caminho}/{deslocamento:08X}_{_nome_seguro(nome)}.vag", base + achado,
                        tamanho, a.caminho, "vag", False))
                    analise.pacotes_com_vag[a.caminho] += 1
                    proximo_livre = base + achado + tamanho
            achado = dados.find(MARCA_VAG, achado + 1)
        sobra = dados[-3:]
        pos += len(bloco)


def relatorio(analise: Analise) -> str:
    """O relatório da análise em texto (para guardar ou mandar a quem for ajudar com o jogo)."""
    linhas = [f"Análise da ISO: {analise.iso.name}", f"Jogo: {analise.descricao}",
              f"Setor: {analise.setor} bytes ({'ISO de DVD' if analise.setor == 2048 else 'BIN de CD'})",
              f"Arquivos no disco: {len(analise.arquivos)}", "",
              "O que o Maestro já troca:", f"  {analise.resumo()}"]
    for pacote, n in analise.pacotes_com_vag.most_common(15):
        linhas.append(f"    {n:5d} falas VAG dentro de {pacote}")
    if analise.falas and analise.setor != 2048:
        linhas.append("  (BIN de CD: o Maestro tira as falas para dublar, mas ainda não monta a ISO de volta)")
    linhas += ["", "Sons que o Maestro ainda NÃO abre (o próximo passo para este jogo):"]
    linhas += [f"  {n:5d} arquivo(s) {formato}" for formato, n in analise.outros_sons.most_common()] or ["  nenhum"]
    if analise.videos:
        linhas += ["", "Vídeos (o som das cenas fica dentro deles):"]
        linhas += [f"  {n:5d} {tipo}" for tipo, n in analise.videos.most_common()]
    linhas += ["", "Tipos de arquivo (dos que mais ocupam):"]
    for ext, n, tamanho in analise.por_extensao[:25]:
        linhas.append(f"  {ext:8s} {n:6d} arquivo(s)  {tamanho_legivel(tamanho):>9s}")
    linhas += ["", "Os 40 maiores arquivos:"]
    for a in sorted(analise.arquivos, key=lambda a: -a.tamanho)[:40]:
        linhas.append(f"  {tamanho_legivel(a.tamanho):>9s}  {a.caminho}")
    linhas += ["", "Todos os arquivos (setor, tamanho, caminho):"]
    linhas += [f"  {a.setor:8d} {a.tamanho:11d}  {a.caminho}" for a in analise.arquivos]
    return "\n".join(linhas) + "\n"


# ----------------------------------------------------------------- tirar e pôr de volta
def extrair(analise: Analise, pasta: str | Path, parar=None, ao_progresso=None) -> int:
    """As falas em <pasta>/audio/... e o mapa (onde cada uma fica no disco). Devolve quantas."""
    pasta = Path(pasta)
    progresso = ao_progresso or (lambda f: None)
    with open(analise.iso, "rb") as f:
        formato = _formato_iso(f)
        for i, fala in enumerate(analise.falas):
            if parar and parar():
                raise ErroPatch("interrompido (botão Parar)")
            destino = pasta / fala.relativo
            destino.parent.mkdir(parents=True, exist_ok=True)
            if analise.setor == 2048:
                f.seek(fala.inicio)
                destino.write_bytes(f.read(fala.tamanho))
            else:                                            # BIN de CD: setor por setor (só os 2048 de dados)
                setor = fala.inicio // 2048
                destino.write_bytes(_ler(f, formato, setor, fala.tamanho))
            progresso((i + 1) / max(1, len(analise.falas)))
    mapa = {"iso": {"nome": analise.iso.name, "tamanho": analise.tamanho, "id": analise.id_jogo,
                    "setor": analise.setor},
            "falas": {fala.relativo: {"inicio": fala.inicio, "tamanho": fala.tamanho, "origem": fala.origem,
                                      "formato": fala.formato} for fala in analise.falas}}
    (pasta / ARQUIVO_MAPA).write_text(json.dumps(mapa, ensure_ascii=False, indent=1), encoding="utf-8")
    return len(analise.falas)


def ler_mapa(pasta: str | Path) -> dict | None:
    try:
        return json.loads((Path(pasta) / ARQUIVO_MAPA).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


@dataclass
class Montagem:
    destino: Path
    trocadas: int
    puladas: list                        # [(fala, motivo)]


def montar(iso: str | Path, pasta_extraida: str | Path, pasta_dublada: str | Path, destino: str | Path,
           parar=None, ao_progresso=None) -> Montagem:
    """A ISO em português: uma CÓPIA da original com cada fala dublada (pasta_dublada/<mesmo caminho>) gravada por
    cima da original, no mesmo byte e com o mesmo tamanho. A original não muda."""
    iso, destino = Path(iso), Path(destino)
    mapa = ler_mapa(pasta_extraida)
    if not mapa:
        raise ErroPatch("esta pasta não foi tirada da ISO pelo Maestro (falta o mapa_iso.json): use a ferramenta do "
                        "jogo para pôr os arquivos de volta")
    if iso.stat().st_size != mapa["iso"]["tamanho"]:
        raise ErroPatch(f"esta não é a ISO de onde as falas saíram ({mapa['iso']['nome']})")
    if mapa["iso"].get("setor", 2048) != 2048:
        raise ErroPatch("ISO de CD em .bin (setor de 2352 bytes): o Maestro ainda não monta de volta")
    if destino.resolve() == iso.resolve():
        raise ErroPatch("escolha outro nome para a ISO nova: a original fica como está")
    conferir_espaco(destino.parent, iso.stat().st_size + 200 * 1024 * 1024)
    destino.parent.mkdir(parents=True, exist_ok=True)
    parcial = destino.with_name(destino.name + ".parcial")
    progresso = ao_progresso or (lambda f: None)
    trocadas, puladas = 0, []
    try:
        total, copiado = max(1, iso.stat().st_size), 0
        with open(iso, "rb") as o, open(parcial, "wb") as d:
            while bloco := o.read(BLOCO):
                if parar and parar():
                    raise ErroPatch("interrompido (botão Parar)")
                d.write(bloco)
                copiado += len(bloco)
                progresso(0.9 * copiado / total)
        with open(parcial, "r+b") as d:
            for relativo, onde in mapa["falas"].items():
                nova = Path(pasta_dublada) / relativo
                if not nova.is_file():
                    continue
                dados = nova.read_bytes()
                if len(dados) != onde["tamanho"]:
                    puladas.append((relativo, f"tamanho diferente ({len(dados)} de {onde['tamanho']} bytes)"))
                    continue
                if onde["formato"] in audio_jogo.FORMATOS and dados[:4] not in (MARCA_VAG, b"SShd", b"RIFF"):
                    puladas.append((relativo, "não é um som que o jogo lê"))
                    continue
                d.seek(onde["inicio"])
                d.write(dados)
                trocadas += 1
        ler_info(parcial)                                    # a ISO nova ainda é um disco que o PS2 lê
    except BaseException:
        parcial.unlink(missing_ok=True)
        raise
    os.replace(parcial, destino)
    progresso(1.0)
    return Montagem(destino, trocadas, puladas)
