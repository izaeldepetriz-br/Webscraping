"""Melhoria 1: avisa o servidor Jellyfin para escanear a biblioteca (POST /Library/Refresh).

A chave de API se cria em: Painel do Jellyfin -> Avançado -> Chaves de API -> "+".
JELLYFIN_URL é o endereço que você abre no navegador, ex.: http://localhost:8096
"""

from __future__ import annotations

import requests

from .registro import obter_logger

log = obter_logger()


class ErroJellyfin(Exception):
    pass


def _cabecalhos(api_key: str) -> dict:
    # Formato atual do Jellyfin ("MediaBrowser Token=") + o antigo (X-Emby-Token), para versões mais velhas.
    return {"Authorization": f'MediaBrowser Token="{api_key}", Client="jellyfin-tools", Version="1.0"',
            "X-Emby-Token": api_key}


def atualizar_biblioteca(jellyfin_url: str, api_key: str, timeout: float = 20,
                         sessao: requests.Session | None = None) -> None:
    """Dispara o scan das bibliotecas. Lança ErroJellyfin com uma explicação se não der."""
    if not jellyfin_url or not api_key:
        raise ErroJellyfin("JELLYFIN_URL e JELLYFIN_API_KEY precisam estar preenchidos")
    url = jellyfin_url.rstrip("/") + "/Library/Refresh"
    try:
        r = (sessao or requests).post(url, headers=_cabecalhos(api_key), timeout=timeout)
    except requests.RequestException as erro:
        raise ErroJellyfin(f"não consegui falar com o Jellyfin em {jellyfin_url}: {erro}") from erro
    if r.status_code in (401, 403):
        raise ErroJellyfin("o Jellyfin recusou a chave de API (confira JELLYFIN_API_KEY)")
    if r.status_code == 404:
        raise ErroJellyfin(f"endereço errado? {url} não existe (confira JELLYFIN_URL)")
    if not r.ok:
        raise ErroJellyfin(f"o Jellyfin respondeu HTTP {r.status_code}")
    log.info("Jellyfin: escaneamento da biblioteca iniciado (%s)", jellyfin_url)


def _pedir_json(sessao, metodo: str, url: str, api_key: str, timeout: float, **extra):
    try:
        r = (sessao or requests).request(metodo, url, headers=_cabecalhos(api_key), timeout=timeout, **extra)
    except requests.RequestException as erro:
        raise ErroJellyfin(f"não consegui falar com o Jellyfin: {erro}") from erro
    if r.status_code in (401, 403):
        raise ErroJellyfin("o Jellyfin recusou a chave de API")
    if not r.ok:
        raise ErroJellyfin(f"o Jellyfin respondeu HTTP {r.status_code} em {url}")
    try:
        return r.json() if r.content else {}
    except ValueError:
        return {}


def contagem_da_biblioteca(jellyfin_url: str, api_key: str, timeout: float = 20, sessao=None) -> dict:
    """Quantos filmes, séries e episódios o Jellyfin tem agora (GET /Items/Counts)."""
    dados = _pedir_json(sessao, "GET", jellyfin_url.rstrip("/") + "/Items/Counts", api_key, timeout) or {}
    return {"filmes": int(dados.get("MovieCount") or 0), "series": int(dados.get("SeriesCount") or 0),
            "episodios": int(dados.get("EpisodeCount") or 0)}


INTERVALO_SCAN = 3.0                  # segundos entre uma olhada e outra na tarefa de scan


def escanear_e_conferir(jellyfin_url: str, api_key: str, limite: float = 1800, parar=None,
                        intervalo: float | None = None, ao_andamento=None, sessao=None) -> dict:
    """Pede o scan E ACOMPANHA a tarefa "Escanear biblioteca" (RefreshLibrary) até ela terminar; conta filmes,
    séries e episódios antes e depois. Devolve {terminou, status, erro, antes, depois, segundos}.
    (Antes, o botão só sabia que o Jellyfin ACEITOU o pedido, não se o scan rodou de fato.)"""
    import time
    intervalo = INTERVALO_SCAN if intervalo is None else intervalo
    base = jellyfin_url.rstrip("/")
    antes = contagem_da_biblioteca(jellyfin_url, api_key, sessao=sessao)
    tarefas = _pedir_json(sessao, "GET", base + "/ScheduledTasks", api_key, 20) or []
    tarefa = next((t for t in tarefas if t.get("Key") == "RefreshLibrary"), None) if isinstance(tarefas, list) else None
    fim_antes = ((tarefa or {}).get("LastExecutionResult") or {}).get("EndTimeUtc")
    inicio = time.monotonic()
    atualizar_biblioteca(jellyfin_url, api_key, sessao=sessao)
    resultado = {"terminou": False, "status": "", "erro": "", "antes": antes, "depois": antes, "segundos": 0.0}
    if tarefa and tarefa.get("Id"):
        viu_rodando = False
        while time.monotonic() - inicio < limite and not (parar and parar()):
            time.sleep(intervalo)
            info = _pedir_json(sessao, "GET", f"{base}/ScheduledTasks/{tarefa['Id']}", api_key, 20) or {}
            estado, ultimo = info.get("State", "Idle"), info.get("LastExecutionResult") or {}
            if estado != "Idle":
                viu_rodando = True
                if ao_andamento and info.get("CurrentProgressPercentage") is not None:
                    ao_andamento(float(info["CurrentProgressPercentage"]))
            elif viu_rodando or (ultimo.get("EndTimeUtc") and ultimo.get("EndTimeUtc") != fim_antes):
                resultado.update(terminou=True, status=ultimo.get("Status", ""),
                                 erro=ultimo.get("ErrorMessage") or "")
                break
    resultado["segundos"] = time.monotonic() - inicio
    resultado["depois"] = contagem_da_biblioteca(jellyfin_url, api_key, sessao=sessao)
    return resultado


def texto_do_scan_conferido(r: dict) -> str:
    """'Terminou em 2 min: +3 filme(s), +12 episódio(s).' / 'nada novo' / erro / ainda rodando."""
    dif = {k: r["depois"][k] - r["antes"][k] for k in ("filmes", "series", "episodios")}
    nomes = {"filmes": "filme(s)", "series": "série(s)", "episodios": "episódio(s)"}
    mudou = ", ".join(f"{'+' if v > 0 else ''}{v} {nomes[k]}" for k, v in dif.items() if v)
    tempo = f"{r['segundos'] / 60:.0f} min" if r["segundos"] >= 90 else f"{r['segundos']:.0f} s"
    agora = (f"Agora: {r['depois']['filmes']} filme(s), {r['depois']['series']} série(s), "
             f"{r['depois']['episodios']} episódio(s).")
    if not r["terminou"]:
        return (f"O Jellyfin aceitou o pedido e ainda está escaneando ({tempo} até agora). "
                + (f"Até aqui: {mudou}. " if mudou else "") + "Acompanhe em Painel > Tarefas agendadas.")
    if r["status"] in ("Failed", "Aborted"):
        return f"O escaneamento terminou com ERRO ({r['status']}): {r['erro'] or 'veja Painel > Logs'}."
    return f"Escaneamento concluído em {tempo}: " + (mudou + "." if mudou else "nada novo (já estava em dia).") + f"\n{agora}"


def testar_conexao(jellyfin_url: str, api_key: str, timeout: float = 10,
                   sessao: requests.Session | None = None) -> str:
    """Confere endereço e chave (GET /System/Info). Devolve 'Nome do servidor (versão)'."""
    if not jellyfin_url or not api_key:
        raise ErroJellyfin("preencha o endereço e a chave de API do Jellyfin")
    url = jellyfin_url.rstrip("/") + "/System/Info"
    try:
        r = (sessao or requests).get(url, headers=_cabecalhos(api_key), timeout=timeout)
    except requests.RequestException as erro:
        raise ErroJellyfin(f"não consegui falar com o Jellyfin em {jellyfin_url}: {erro}") from erro
    if r.status_code in (401, 403):
        raise ErroJellyfin("o Jellyfin recusou a chave de API")
    if not r.ok:
        raise ErroJellyfin(f"o Jellyfin respondeu HTTP {r.status_code} (o endereço está certo?)")
    try:
        info = r.json()
    except ValueError as erro:
        raise ErroJellyfin("esse endereço respondeu, mas não parece um servidor Jellyfin") from erro
    return f"{info.get('ServerName', 'Jellyfin')} (versão {info.get('Version', '?')})"


# ----------------------------------------------------------------- o que o Jellyfin já tem
class IndiceJellyfin:
    """Filmes, séries e episódios que JÁ estão no Jellyfin (para o espelho não duplicar).
    Compara pelo id do TMDB (o mais seguro) ou pelo nome + ano (filme) / nome da série + SxxEyy."""

    def __init__(self, filmes: list[dict], series: list[dict], episodios: list[dict]):
        from .nomes import normalizar
        self._normalizar = normalizar
        self.filmes_tmdb = {str(f.get("ProviderIds", {}).get("Tmdb")) for f in filmes
                            if (f.get("ProviderIds") or {}).get("Tmdb")}
        self.filmes_nome = {(normalizar(f.get("Name") or ""), f.get("ProductionYear")) for f in filmes}
        tmdb_da_serie = {s.get("Id"): str((s.get("ProviderIds") or {}).get("Tmdb") or "") for s in series}
        self.episodios_tmdb = set()
        self.episodios_nome = set()
        for e in episodios:
            temporada, numero = e.get("ParentIndexNumber"), e.get("IndexNumber")
            if temporada is None or numero is None:
                continue
            if tmdb := tmdb_da_serie.get(e.get("SeriesId")):
                self.episodios_tmdb.add((tmdb, temporada, numero))
            self.episodios_nome.add((normalizar(e.get("SeriesName") or ""), temporada, numero))
        self.total = len(filmes) + len(episodios)

    def tem_filme(self, titulos: list[str], ano: int | None, tmdb_id=None) -> bool:
        if tmdb_id and str(tmdb_id) in self.filmes_tmdb:
            return True
        return any((self._normalizar(t), ano) in self.filmes_nome for t in titulos if t)

    def tem_episodio(self, series: list[str], temporada: int, episodio: int, tmdb_id=None) -> bool:
        if tmdb_id and (str(tmdb_id), temporada, episodio) in self.episodios_tmdb:
            return True
        return any((self._normalizar(s), temporada, episodio) in self.episodios_nome for s in series if s)


def _itens(base: str, cabecalhos: dict, tipo: str, sessao, timeout: float, usuario: str | None) -> list[dict]:
    caminho = f"/Users/{usuario}/Items" if usuario else "/Items"
    r = sessao.get(base + caminho, headers=cabecalhos, timeout=timeout,
                   params={"Recursive": "true", "IncludeItemTypes": tipo, "EnableImages": "false",
                           "Fields": "ProviderIds,ProductionYear"})
    if r.status_code in (401, 403):
        raise ErroJellyfin("o Jellyfin recusou a chave de API")
    if not r.ok:
        raise ErroJellyfin(f"o Jellyfin respondeu HTTP {r.status_code} ao listar {tipo}")
    return r.json().get("Items") or []


def indice_da_biblioteca(jellyfin_url: str, api_key: str, timeout: float = 60,
                         sessao: requests.Session | None = None) -> IndiceJellyfin:
    """Lê do servidor os filmes, as séries e os episódios que ele já tem (3 pedidos)."""
    if not jellyfin_url or not api_key:
        raise ErroJellyfin("preencha o endereço e a chave de API do Jellyfin")
    base, cabecalhos, sessao = jellyfin_url.rstrip("/"), _cabecalhos(api_key), sessao or requests.Session()
    try:
        usuario = None
        try:
            filmes = _itens(base, cabecalhos, "Movie", sessao, timeout, None)
        except ErroJellyfin as erro:              # Jellyfin antigo: /Items só com um usuário
            if "recusou" in str(erro):
                raise
            usuarios = sessao.get(base + "/Users", headers=cabecalhos, timeout=timeout).json()
            usuario = usuarios[0]["Id"] if usuarios else None
            filmes = _itens(base, cabecalhos, "Movie", sessao, timeout, usuario)
        series = _itens(base, cabecalhos, "Series", sessao, timeout, usuario)
        episodios = _itens(base, cabecalhos, "Episode", sessao, timeout, usuario)
    except requests.RequestException as erro:
        raise ErroJellyfin(f"não consegui falar com o Jellyfin em {jellyfin_url}: {erro}") from erro
    except (ValueError, KeyError, IndexError, TypeError) as erro:
        raise ErroJellyfin(f"resposta inesperada do Jellyfin: {erro}") from erro
    indice = IndiceJellyfin(filmes, series, episodios)
    log.info("Jellyfin: %d filme(s) e %d episódio(s) na biblioteca", len(filmes), len(episodios))
    return indice
