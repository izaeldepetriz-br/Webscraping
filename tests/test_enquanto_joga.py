"""O modo "Enquanto joga" da aba 🎮 Jogos: o tradutor de tela (fotografa, espera o texto parar de ser escrito, lê,
traduz uma vez só cada frase e mostra) e a legenda ao vivo (corta o som do PC em falas pelas pausas, o Whisper
escreve, traduz, mostra e, ligado, fala com o som do jogo abaixado e sem ouvir a si mesmo). Leitor, Whisper e
tradutor são falsos."""
import numpy as np
from PIL import Image, ImageDraw

from jellyfin_tools import legenda_ao_vivo as lv
from jellyfin_tools import tela_jogo as tj


def foto(texto: str) -> Image.Image:
    imagem = Image.new("RGB", (320, 90), "black")
    ImageDraw.Draw(imagem).text((10, 30), texto, fill="white")
    imagem.info["texto"] = texto
    return imagem


class LeitorFalso:
    def ler(self, imagem):
        return imagem.info.get("texto", "") + "\n|"


def test_tradutor_de_tela_espera_o_texto_parar_e_traduz_uma_vez(tmp_path):
    # o jogo escreve letra por letra ("Hey" -> "Hey! You") e depois para; depois a mesma frase volta
    quadros = [foto("")] * 2 + [foto("Hey")] + [foto("Hey! You there!")] * 4 + [foto("")] * 3 + \
        [foto("Hey! You there!")] * 4 + [foto("The gate is closed.")] * 4
    mostrados, pedidos = [], []
    memoria = tj.MemoriaDeFrases(tmp_path / "frases.json")
    t = tj.TradutorDeTela(lambda: (0, 0, 320, 90), LeitorFalso(), lambda texto: pedidos.append(texto) or f"PT {texto}",
                          lambda o, tr: mostrados.append(tr), memoria, esperar=lambda s: None)
    fila = iter(quadros)

    def fotografar(area):
        try:
            return next(fila)
        except StopIteration:
            t._parar.set()
            return quadros[-1]
    t.fotografar = fotografar
    t._laco()
    assert mostrados == ["PT Hey! You there!", "PT Hey! You there!", "PT The gate is closed."]
    assert pedidos == ["Hey! You there!", "The gate is closed."]               # a repetida veio da memória
    assert memoria.reaproveitadas == 1
    assert tj.MemoriaDeFrases(tmp_path / "frases.json").get("hey you there") == "PT Hey! You there!"
    # o atalho (F9): traduz na hora, mesmo a mesma frase
    assert t.passo(foto("The gate is closed."), forcar=True) == "PT The gate is closed."


def test_partes_do_tradutor_de_tela():
    assert tj.limpar("  Guarda |\nHey!   You   there!\n_ \n") == "Guarda Hey! You there!"
    assert tj.diferenca(foto("A"), foto("A")) == 0 and tj.diferenca(foto("A"), foto("Outra frase")) > 0
    assert tj.diferenca(None, foto("A")) == 100.0
    janelas = [tj.Janela("Bloco de notas", 1, (0, 0, 800, 600)), tj.Janela("PCSX2 · Burnout 3", 2, (0, 0, 640, 480)),
               tj.Janela("Navegador", 3, (0, 0, 1920, 1080))]
    assert [j.ident for j in tj.ordenar_janelas(janelas)] == [2, 3, 1]       # o emulador primeiro
    assert tj.janelas_abertas("linux") == [] and not tj.AtalhoGlobal("F9", print, "linux").comecar()
    leitor = tj.preparar_para_ler(foto("x"))
    assert leitor.size == (640, 180)                                         # texto pequeno: o dobro


def fala(segundos: float, volume: float = 0.3) -> np.ndarray:
    t = np.arange(int(lv.TAXA * segundos)) / lv.TAXA
    return (volume * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def em_pedacos(som: np.ndarray):
    n = int(lv.TAXA * lv.PEDACO)
    return [som[i:i + n] for i in range(0, len(som), n)]


def test_cortador_separa_as_falas_pelas_pausas():
    som = np.concatenate([np.zeros(lv.TAXA), fala(1.0), np.zeros(lv.TAXA), fala(0.2), np.zeros(lv.TAXA),
                          fala(14.0)])
    cortador, falas = lv.Cortador(), []
    for pedaco in em_pedacos(som):
        r = cortador.receber(pedaco)
        if r is not None:
            falas.append(len(r) / lv.TAXA)
    assert len(falas) == 2                                                   # a de 0,2 s é curta demais
    assert 1.5 <= falas[0] <= 2.0 and abs(falas[1] - lv.FALA_MAXIMA) < 0.6     # a longa é cortada em 12 s


def test_legenda_ao_vivo_mostra_fala_e_nao_ouve_a_si_mesma():
    mostrados, falados, eventos = [], [], []

    class Volume:
        def abaixar(self):
            eventos.append("abaixou")

        def voltar(self):
            eventos.append("voltou")
    legenda = lv.LegendaAoVivo(None, lambda f: " Hey, you! ", lambda t: "Ei, você!", lambda o, t: mostrados.append(t),
                               falar=lambda t: (falados.append(t), eventos.append(legenda._falando.is_set())),
                               volume=Volume())
    assert legenda.processar(fala(1.0)) == "Ei, você!"
    assert mostrados == ["Ei, você!"] and falados == ["Ei, você!"]
    assert eventos == ["abaixou", True, "voltou"] and not legenda._falando.is_set()
    assert lv.LegendaAoVivo(None, lambda f: "", str, print).processar(fala(1.0)) is None   # o Whisper não ouviu nada


def test_leitor_do_windows_numa_tarefa_so_dele_e_volume_na_tarefa_que_fala():
    """O winrt muda o modo do COM da tarefa: o leitor do Windows prepara e lê numa tarefa só dele (a da tela e a do
    volume ficam livres). O volume do jogo procura as sessões de som na 1ª vez, na tarefa que fala."""
    import threading

    import pytest
    quem = []
    leitor = tj.LeitorWindows("en-US", preparar=lambda idioma: quem.append(("preparar", threading.current_thread())),
                              ler_aqui=lambda imagem: quem.append(("ler", threading.current_thread())) or "PRESS START")
    assert leitor.ler(foto("PRESS START")) == "PRESS START"
    assert quem[0][1] is quem[1][1] and quem[0][1] is not threading.current_thread()
    leitor.fechar()

    def sem_winrt(idioma):
        raise ImportError("No module named 'winrt'")
    with pytest.raises(ImportError):                       # o mesmo erro: leitor_de_texto cai no Tesseract
        tj.LeitorWindows("en-US", preparar=sem_winrt)
    falha = tj.LeitorWindows("en-US", preparar=lambda idioma: None, ler_aqui=lambda imagem: 1 / 0)
    with pytest.raises(ZeroDivisionError):
        falha.ler(foto("x"))
    falha.fechar()

    class Volume:
        def __init__(self):
            self.valor = 0.8

        def GetMasterVolume(self):
            return self.valor

        def SetMasterVolume(self, valor, contexto):
            self.valor = valor

    class Sessao:
        SimpleAudioVolume = Volume()
    procuradas = []
    volume = lv.VolumeDoJogo(4321)
    volume._achar = lambda: procuradas.append(threading.current_thread()) or [Sessao()]
    assert not procuradas                                  # nada do COM ao criar (na tarefa da tela)
    fio = threading.Thread(target=lambda: (volume.abaixar(), volume.voltar()))
    fio.start()
    fio.join()
    assert procuradas == [fio] and Sessao.SimpleAudioVolume.valor == 0.8 and volume.funciona
