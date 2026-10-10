"""Tradução em LOTE (modo econômico): metade do preço, mas o resultado leva até 24 horas (quase sempre menos de 1 h).

Como o envio de uma carta registrada em vez de um telefonema: o Maestro manda TODOS os pedidos de uma vez para a API
de lotes da Anthropic (Message Batches), guarda o número do lote num arquivo e volta depois para buscar as respostas.
Dá para fechar o programa: ao abrir de novo (ou na próxima execução do robô), ele confere os lotes pendentes.

    enviar()   -> cria o lote e grava ~/.videoscraper/lotes/<id>.json (o que é de quem)
    coletar()  -> se o lote terminou, monta cada 'Nome.pt-BR.srt' com os MESMOS horários e apaga o arquivo do lote

Cada pedido do lote é igual ao do modo normal (as mesmas regras e a mesma saída estruturada em JSON). Como os pedidos
vão todos juntos, o "contexto" de cada trecho são as falas anteriores no idioma ORIGINAL (no modo normal, as já
traduzidas). Trecho que falhar ou voltar incompleto é traduzido de novo no modo normal (preço cheio só nele).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .legendas import ErroLegenda, extrair_srt
from .traducao import (CONTEXTO_ANTERIOR, LINHAS_POR_PEDIDO, ErroTraducao, Fala, ResultadoTraducao, Tradutor,
                       _explicar, ajustar_linhas, gerar_srt, ler_resposta, ler_srt)

ROTULO_CONTEXTO = "Falas anteriores, no idioma original (só contexto, não devolva):"


def _falas(origem: Path) -> list[Fala]:
    return ler_srt(extrair_srt(Path(origem).read_bytes()))


def enviar(pendentes: list, tradutor: Tradutor, pasta_lotes: str | Path) -> tuple[str, int]:
    """Cria o lote com as legendas pendentes (cada uma: .origem, .destino, .video). Devolve (id do lote, pedidos)."""
    arquivos, pedidos, requisicoes = [], {}, []
    for k, p in enumerate(pendentes):
        try:
            falas = _falas(p.origem)
        except (OSError, ErroLegenda):
            continue
        indices = [i for i, f in enumerate(falas) if f.texto.strip()]
        if not indices:
            continue
        arquivos.append({"origem": str(p.origem), "destino": str(p.destino), "titulo": Path(p.video).stem})
        n = len(arquivos) - 1
        for parte, inicio in enumerate(range(0, len(indices), LINHAS_POR_PEDIDO)):
            lote = {i: falas[i].texto for i in indices[inicio:inicio + LINHAS_POR_PEDIDO]}
            anteriores = [falas[i].texto for i in indices[max(0, inicio - CONTEXTO_ANTERIOR):inicio]]
            codigo = f"a{n}-p{parte}"                                    # ^[a-zA-Z0-9_-]{1,64}$
            pedidos[codigo] = [n, list(lote)]
            requisicoes.append({"custom_id": codigo, "params": tradutor.parametros(
                lote, Path(p.video).stem, anteriores, ROTULO_CONTEXTO)})
    if not requisicoes:
        raise ErroTraducao("nenhuma legenda com falas para enviar")
    try:
        envio = tradutor.cliente.messages.batches.create(requests=requisicoes)
    except Exception as erro:
        raise ErroTraducao(_explicar(erro)) from erro
    pasta = Path(pasta_lotes)
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / f"{envio.id}.json").write_text(json.dumps(
        {"id": envio.id, "modelo": tradutor.modelo, "idioma": tradutor.idioma,
         "enviado": datetime.now().isoformat(timespec="seconds"), "arquivos": arquivos, "pedidos": pedidos},
        ensure_ascii=False, indent=2), encoding="utf-8")
    return envio.id, len(requisicoes)


def pendentes_no_disco(pasta_lotes: str | Path) -> list[Path]:
    pasta = Path(pasta_lotes)
    return sorted(pasta.glob("*.json")) if pasta.is_dir() else []


def coletar(arquivo_lote: str | Path, tradutor: Tradutor) -> list[ResultadoTraducao] | None:
    """Se o lote terminou, grava as legendas e apaga o arquivo do lote; senão devolve None (ainda processando).
    `tradutor` traduz no modo normal os trechos que falharem (e soma os tokens: os do lote valem metade)."""
    arquivo_lote = Path(arquivo_lote)
    dados = json.loads(arquivo_lote.read_text(encoding="utf-8"))
    try:
        situacao = tradutor.cliente.messages.batches.retrieve(dados["id"])
        if situacao.processing_status != "ended":
            return None
        respostas = {r.custom_id: r.result for r in tradutor.cliente.messages.batches.results(dados["id"])}
    except Exception as erro:
        raise ErroTraducao(_explicar(erro)) from erro
    traduzidas: dict[int, dict[int, str]] = {}
    refazer: dict[int, list[int]] = {}
    tokens = [0, 0]
    for codigo, (n, ids) in dados["pedidos"].items():
        resultado = respostas.get(codigo)
        textos = {}
        if resultado is not None and getattr(resultado, "type", "") == "succeeded":
            mensagem = resultado.message
            uso = getattr(mensagem, "usage", None)
            tokens[0] += getattr(uso, "input_tokens", 0) or 0
            tokens[1] += getattr(uso, "output_tokens", 0) or 0
            if mensagem.stop_reason == "end_turn":
                try:
                    textos = ler_resposta(mensagem)
                except ErroTraducao:
                    textos = {}
        traduzidas.setdefault(n, {}).update({i: textos[i] for i in ids if i in textos})
        refazer.setdefault(n, []).extend(i for i in ids if i not in textos)
    # os tokens do lote custam metade: soma no tradutor como meio token (o custo final fica certo)
    tradutor.tokens_entrada += tokens[0] // 2
    tradutor.tokens_saida += tokens[1] // 2
    resultados = []
    for n, info in enumerate(dados["arquivos"]):
        origem, destino = Path(info["origem"]), Path(info["destino"])
        if destino.exists():
            resultados.append(ResultadoTraducao(origem, destino, "ja_existe", "a legenda traduzida já existe"))
            continue
        try:
            falas = _falas(origem)
            textos = [f.texto for f in falas]
            for i, t in traduzidas.get(n, {}).items():
                textos[i] = t
            faltam = refazer.get(n, [])
            if faltam:                                          # o que o lote não trouxe: modo normal, só esses
                novos = tradutor.traduzir_falas([falas[i].texto for i in faltam], info["titulo"])
                for i, t in zip(faltam, novos):
                    textos[i] = t
            parcial = destino.with_name(destino.name + ".part")
            parcial.write_text(gerar_srt([Fala(f.tempo, ajustar_linhas(t)) for f, t in zip(falas, textos)]),
                               encoding="utf-8")
            parcial.replace(destino)
            resultados.append(ResultadoTraducao(origem, destino, "traduzida", "", len(falas)))
        except (OSError, ErroLegenda, ErroTraducao) as erro:
            resultados.append(ResultadoTraducao(origem, destino, "erro", str(erro)))
    arquivo_lote.unlink(missing_ok=True)
    return resultados
