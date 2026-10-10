"""Programação de verdade (iptv-org/epg): o mapa, o channels.xml e o container do Docker."""

import json
import os
import subprocess
import xml.etree.ElementTree as ET

import pytest

from jellyfin_tools import epg_iptv
from jellyfin_tools.epg_iptv import (ErroEPG, achar_guias, baixar_mapa, comando_docker, gerar_channels_xml,
                                     gravar_channels_xml, iniciar_container)
from jellyfin_tools.tv_ao_vivo import Canal

MAPA = [
    {"channel": "AgroMais.br", "feed": "SD", "site": "mi.tv", "site_id": "br#agromais", "site_name": "AgroMais",
     "lang": "pt"},
    {"channel": "AgroMais.br", "feed": "SD", "site": "outro.com", "site_id": "agro", "site_name": "AgroMais",
     "lang": "pt"},
    {"channel": "GloboNews.br", "feed": None, "site": "meuguia.tv", "site_id": "GNT", "site_name": "Globo News",
     "lang": "pt"},
    {"channel": "CNN.us", "feed": None, "site": "tvguide.com", "site_id": "cnn", "site_name": "CNN",
     "lang": "en"},
    {"channel": "CNNBrasil.br", "feed": None, "site": "mi.tv", "site_id": "br#cnn-brasil",
     "site_name": "CNN Brasil", "lang": "pt"},
]


def _por_nome(achados):
    return {c.nome: g for c, g in achados}


def test_acha_pelo_tvg_id_e_prefere_os_sites_que_funcionam_melhor():
    canais = [Canal("Agro Mais", "http://a", id_guia="AgroMais.br@SD")]
    (_, g), = achar_guias(canais, MAPA)
    assert g["site"] == "mi.tv" and g["site_id"] == "br#agromais"


def test_acha_pelo_nome_sem_enfeites_e_no_idioma_do_canal():
    canais = [Canal("Globo News (720p)", "http://b", grupo="Notícias", idioma="Português"),
              Canal("CNN Brasil HD", "http://c", idioma="Português"),
              Canal("Canal Que Não Existe", "http://d", idioma="Português")]
    achados = _por_nome(achar_guias(canais, MAPA))
    assert achados["Globo News (720p)"]["channel"] == "GloboNews.br"
    assert achados["CNN Brasil HD"]["channel"] == "CNNBrasil.br"
    assert achados["Canal Que Não Existe"] is None


def test_pelo_nome_nao_pega_o_canal_de_outro_idioma():
    canais = [Canal("CNN", "http://c", idioma="Português")]       # a CNN americana é em inglês
    (_, g), = achar_guias(canais, MAPA)
    assert g is None


def test_channels_xml_usa_o_mesmo_id_e_nome_do_canal_no_jellyfin():
    canais = [Canal("Agro Mais", "http://a", id_guia="AgroMais.br@SD"),
              Canal("Globo News", "http://b", idioma="Português"),
              Canal("Sem Guia", "http://x", idioma="Português")]
    raiz = ET.fromstring(gerar_channels_xml(achar_guias(canais, MAPA)))
    entradas = raiz.findall("channel")
    assert len(entradas) == 2                                     # o sem guia fica de fora
    agro, globo = entradas
    assert agro.attrib == {"site": "mi.tv", "lang": "pt", "xmltv_id": "AgroMais.br@SD", "site_id": "br#agromais"}
    assert agro.text == "Agro Mais"
    assert globo.attrib["xmltv_id"] == "GloboNews.br" and globo.text == "Globo News"


def test_channels_xml_escapa_caracteres_especiais():
    mapa = [{"channel": "AeB.br", "feed": None, "site": "mi.tv", "site_id": "a&b", "site_name": "A & B",
             "lang": "pt"}]
    texto = gerar_channels_xml(achar_guias([Canal("A & B", "http://a", id_guia="AeB.br")], mapa))
    entrada = ET.fromstring(texto).find("channel")                # XML válido
    assert entrada.text == "A & B" and entrada.attrib["site_id"] == "a&b"


def test_gravar_channels_xml_conta_os_com_e_sem_programacao(tmp_path):
    canais = [Canal("Agro Mais", "http://a", id_guia="AgroMais.br"), Canal("Nada", "http://n", idioma="Português")]
    arquivo, com, sem = gravar_channels_xml(canais, tmp_path / "TV", MAPA)
    assert arquivo == tmp_path / "TV" / "channels.xml" and arquivo.is_file()
    assert com == 1 and [c.nome for c in sem] == ["Nada"]


class _Resposta:
    def __init__(self, status, dados):
        self.status_code, self._dados = status, dados
        self.ok = status < 400

    def json(self):
        return self._dados


class _Sessao:
    def __init__(self, *respostas):
        self.respostas, self.urls = list(respostas), []

    def get(self, url, timeout=None):
        self.urls.append(url)
        return self.respostas.pop(0)


def test_baixar_mapa_guarda_so_o_que_interessa_e_usa_o_cache(tmp_path):
    cache = tmp_path / "epg_mapa.json"
    bruto = MAPA[:1] + [{"channel": None, "site": "x", "site_id": "y"}, {"channel": "A.br", "site": "s",
                                                                         "site_id": "1", "extra": "fora"}]
    sessao = _Sessao(_Resposta(200, bruto))
    mapa = baixar_mapa(cache, sessao=sessao)
    assert len(mapa) == 2 and "extra" not in mapa[1]               # sem canal: fora; campos extras: fora
    assert json.loads(cache.read_text(encoding="utf-8")) == mapa
    assert baixar_mapa(cache, sessao=_Sessao()) == mapa             # dentro dos 7 dias: nem consulta


def test_baixar_mapa_tenta_o_segundo_endereco_e_sem_internet_usa_o_cache_velho(tmp_path):
    cache = tmp_path / "epg_mapa.json"
    sessao = _Sessao(_Resposta(404, None), _Resposta(200, MAPA))
    assert len(baixar_mapa(cache, sessao=sessao)) == len(MAPA)
    assert sessao.urls == list(epg_iptv.URLS_MAPA)
    velho = os.stat(cache).st_mtime - 30 * 86400
    os.utime(cache, (velho, velho))                                 # cache vencido...
    falhas = _Sessao(_Resposta(500, None), _Resposta(503, None))
    assert len(baixar_mapa(cache, sessao=falhas)) == len(MAPA)      # ...mas é melhor que nada
    with pytest.raises(ErroEPG, match="HTTP 500"):
        baixar_mapa(tmp_path / "outro.json", sessao=_Sessao(_Resposta(500, None), _Resposta(500, None)))


def test_comando_docker_monta_o_channels_xml_e_coleta_todo_dia():
    cmd = comando_docker("C:\\TV\\channels.xml", "docker", dias=2)
    assert cmd[:3] == ["docker", "run", "-d"]
    assert "C:\\TV\\channels.xml:/epg/public/channels.xml" in cmd
    assert "DAYS=2" in cmd and "CRON_SCHEDULE=0 6 * * *" in cmd and "RUN_AT_STARTUP=true" in cmd
    assert cmd[cmd.index("--restart") + 1] == "unless-stopped" and cmd[-1] == epg_iptv.IMAGEM


def test_iniciar_container_troca_o_antigo_e_avisa_se_falhar():
    chamados = []

    def rodar(cmd, **_):
        chamados.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="abc123\n", stderr="")
    assert iniciar_container("/tv/channels.xml", rodar=rodar, docker="docker") == "abc123"
    assert chamados[0] == ["docker", "rm", "-f", "maestro-guia"] and chamados[1][1] == "run"

    def recusa(cmd, **_):
        return subprocess.CompletedProcess(cmd, 0 if "rm" in cmd else 125, stdout="",
                                           stderr="port is already allocated")
    with pytest.raises(ErroEPG, match="port is already allocated"):
        iniciar_container("/tv/channels.xml", rodar=recusa, docker="docker")


def test_iniciar_container_sem_docker(monkeypatch):
    monkeypatch.setattr(epg_iptv, "achar_docker", lambda: None)
    with pytest.raises(ErroEPG, match="Docker não foi encontrado"):
        iniciar_container("/tv/channels.xml", rodar=lambda *a, **k: None)


def test_estado_do_coletor_no_docker():
    def resposta(codigo, saida="", erro=""):
        return lambda cmd, **_: subprocess.CompletedProcess(cmd, codigo, stdout=saida, stderr=erro)
    assert epg_iptv.estado_do_coletor(resposta(0, "running\n"), docker="docker") == "rodando"
    assert epg_iptv.estado_do_coletor(resposta(0, "exited\n"), docker="docker") == "parado (exited)"
    assert epg_iptv.estado_do_coletor(resposta(1, erro="Error: No such object: maestro-guia"),
                                      docker="docker") == "não criado"
    assert epg_iptv.estado_do_coletor(resposta(1, erro="error during connect: is the docker daemon running?"),
                                      docker="docker") == "Docker fechado"


def test_programas_do_guia_conta_por_canal_e_aceita_gz(api_falsa):
    import gzip
    guia = ('<?xml version="1.0"?><tv><channel id="AgroMais.br"/><channel id="Vazio.br"/>'
            '<programme channel="AgroMais.br" start="20261006000000 +0000"><title>A</title></programme>'
            '<programme channel="AgroMais.br" start="20261006010000 +0000"><title>B</title></programme></tv>').encode()
    api_falsa.rotas["/guide.xml"] = lambda q: (200, guia)
    api_falsa.rotas["/guide.xml.gz"] = lambda q: (200, gzip.compress(guia))
    esperado = {"AgroMais.br": 2, "Vazio.br": 0}
    assert epg_iptv.programas_do_guia(api_falsa.base + "/guide.xml") == esperado
    assert epg_iptv.programas_do_guia(api_falsa.base + "/guide.xml.gz") == esperado
    api_falsa.rotas["/vazio.xml"] = lambda q: (200, b"<tv></tv>")
    assert epg_iptv.programas_do_guia(api_falsa.base + "/vazio.xml") is None           # ainda não coletou
    assert epg_iptv.programas_do_guia(api_falsa.base + "/nao-existe.xml") is None      # 404
    assert epg_iptv.programas_do_guia("http://127.0.0.1:9/guide.xml", timeout=1) is None   # desligado


def test_programacao_por_canal_e_resumo(tmp_path):
    canais = [Canal("Agro Mais", "http://a", id_guia="AgroMais.br"), Canal("Globo News", "http://b", idioma="Português"),
              Canal("Sem Guia", "http://x", idioma="Português")]
    arquivo, _, _ = gravar_channels_xml(canais, tmp_path, MAPA)
    entradas = epg_iptv.ler_channels_xml(arquivo)
    assert entradas == [("Agro Mais", "AgroMais.br", "mi.tv"), ("Globo News", "GloboNews.br", "meuguia.tv")]
    antes = epg_iptv.programacao_por_canal(canais, entradas, None)
    assert antes == {"http://a": "aguardando coleta · mi.tv", "http://b": "aguardando coleta · meuguia.tv",
                     "http://x": "só categoria"}
    depois = epg_iptv.programacao_por_canal(canais, entradas, {"AgroMais.br": 40, "GloboNews.br": 0})
    assert depois == {"http://a": "✓ 40 programas · mi.tv", "http://b": "sem programas · meuguia.tv",
                      "http://x": "só categoria"}
    texto = epg_iptv.resumo_do_coletor("rodando", {"AgroMais.br": 40, "GloboNews.br": 0}, depois, True, False)
    assert "rodando ✓" in texto and "2 canal(is), 40 programa(s)" in texto
    assert "1 com programação, 0 aguardando a coleta, 1 sem programas no site, 1 só com o guia" in texto
    assert "Salvar e enviar ao Jellyfin" in texto
    texto = epg_iptv.resumo_do_coletor("Docker fechado", None, antes, False, None)
    assert "abra-o" in texto and "ainda não respondeu" in texto and "NÃO está no campo" in texto


def test_horarios_do_guia_e_agora_passando(api_falsa):
    from datetime import datetime, timezone
    guia = ('<tv><channel id="A.br"/>'
            '<programme channel="A.br" start="20261010120000 -0300" stop="20261010130000 -0300"><title>Jornal</title>'
            '</programme><programme channel="A.br" start="20261010130000 -0300" stop="20261010150000 -0300">'
            '<title>Filme da Tarde</title></programme>'
            '<programme channel="B.br" start="20261010180000 +0000"><title>Esporte</title></programme></tv>').encode()
    api_falsa.rotas["/guide.xml"] = lambda q: (200, guia)
    grade = epg_iptv.ler_guia(api_falsa.base + "/guide.xml")
    assert [p.titulo for p in grade["A.br"]] == ["Jornal", "Filme da Tarde"]
    assert grade["A.br"][0].inicio == datetime(2026, 10, 10, 15, 0, tzinfo=timezone.utc)   # -0300 -> UTC
    assert grade["B.br"][0].fim is None
    assert epg_iptv.programas_do_guia(api_falsa.base + "/guide.xml") == {"A.br": 2, "B.br": 1}
    canais = [Canal("Canal A", "http://a"), Canal("Canal B", "http://b"), Canal("Sem Guia", "http://x")]
    entradas = [("Canal A", "A.br", "mi.tv"), ("Canal B", "B.br", "mi.tv")]
    meio_dia_e_meia = datetime(2026, 10, 10, 15, 30, tzinfo=timezone.utc)                # 12:30 em Brasília
    agora = epg_iptv.agora_por_canal(canais, entradas, grade, meio_dia_e_meia)
    ate = datetime(2026, 10, 10, 16, 0, tzinfo=timezone.utc).astimezone().strftime("%H:%M")
    proximo = datetime(2026, 10, 10, 18, 0, tzinfo=timezone.utc).astimezone().strftime("%H:%M")
    assert agora == {"http://a": f"Jornal (até {ate}) → Filme da Tarde", "http://b": f"às {proximo}: Esporte"}
    assert epg_iptv.agora_por_canal(canais, entradas, None) == {}
    assert epg_iptv._quando("lixo") is None and epg_iptv._quando("20261010120000").tzinfo == timezone.utc
