"""Aviso de versão nova (página Releases do GitHub), com um servidor falso no lugar do GitHub."""
from videoscraper import atualizacao


def test_compara_numero_por_numero():
    assert atualizacao.numeros("v1.10") > atualizacao.numeros("v1.9")
    assert atualizacao.numeros("1.5.0") == (1, 5, 0) and atualizacao.numeros("sem número") == (0,)


def test_avisa_so_quando_ha_versao_mais_nova(api_falsa):
    rota = "/repos/izaeldepetriz-br/Webscraping/releases/latest"
    api_falsa.rotas[rota] = lambda q: (200, {"tag_name": "v1.6", "html_url": "https://github.com/x/releases/tag/v1.6",
                                             "body": "Canais ao vivo"})
    nova = atualizacao.verificar("v1.5", api=api_falsa.base)
    assert (nova.versao, nova.url, nova.notas) == ("v1.6", "https://github.com/x/releases/tag/v1.6", "Canais ao vivo")
    assert atualizacao.verificar("v1.6", api=api_falsa.base) is None              # já é a mais nova
    assert atualizacao.verificar("v2.0", api=api_falsa.base) is None
    api_falsa.rotas[rota] = lambda q: (404, {})
    assert atualizacao.verificar("v1.5", api=api_falsa.base) is None              # sem versão publicada
    assert atualizacao.verificar("v1.5", api="http://127.0.0.1:9", timeout=1) is None   # sem internet: quieto


def test_versao_do_exe_vem_do_arquivo_gravado_pelo_github(tmp_path, monkeypatch):
    monkeypatch.setattr(atualizacao.sys, "_MEIPASS", str(tmp_path), raising=False)
    (tmp_path / "videoscraper").mkdir()
    (tmp_path / "videoscraper" / "versao_build.txt").write_text("v1.7", encoding="utf-8")
    assert atualizacao.versao_atual() == "v1.7"


def test_ultima_versao_e_baixar_o_zip(api_falsa, tmp_path):
    import pytest
    rota = "/repos/izaeldepetriz-br/Webscraping/releases/latest"
    api_falsa.rotas[rota] = lambda q: (200, {"tag_name": "v1.6", "html_url": "https://github.com/x/v1.6", "assets": [
        {"name": "videoscraper-windows.zip", "browser_download_url": api_falsa.base + "/zip"}]})
    api_falsa.rotas["/zip"] = lambda q: (200, b"PK" + b"x" * 300_000, {"Content-Type": "application/zip"})
    nova = atualizacao.ultima_versao(api=api_falsa.base)
    assert (nova.versao, nova.arquivo_nome) == ("v1.6", "videoscraper-windows.zip")
    passos = []
    arquivo = atualizacao.baixar(nova, tmp_path, ao_progresso=lambda f, t: passos.append((f, t)))
    assert arquivo.name == "videoscraper-windows-v1.6.zip" and arquivo.stat().st_size == 300_002
    assert passos[-1] == (300_002, 300_002) and not list(tmp_path.glob("*.part"))
    with pytest.raises(atualizacao.ErroAtualizacao, match="interrompido"):
        atualizacao.baixar(nova, tmp_path / "b", parar=lambda: True)
    assert not list((tmp_path / "b").glob("*"))                       # nada pela metade
    api_falsa.rotas[rota] = lambda q: (500, {})
    with pytest.raises(atualizacao.ErroAtualizacao, match="HTTP 500"):
        atualizacao.ultima_versao(api=api_falsa.base)


def test_script_de_instalacao_espera_fechar_e_troca_os_arquivos():
    from pathlib import Path
    texto = atualizacao.script_de_instalacao(Path(r"C:\Users\Ana\Downloads\v.zip"), Path(r"C:\Prog's\videoscraper"),
                                             4321, r"C:\Prog's\videoscraper\videoscraper.exe")
    assert "Wait-Process -Id 4321" in texto                            # espera o programa fechar
    assert "Expand-Archive" in texto and "robocopy" in texto
    assert "'C:\\Prog''s\\videoscraper'" in texto                     # aspas do PowerShell escapadas
    assert "Start-Process -FilePath 'C:\\Prog''s\\videoscraper\\videoscraper.exe'" in texto
    assert "(não reabre)" in atualizacao.script_de_instalacao(Path("a.zip"), Path("p"), 1, "")


def test_script_dos_atalhos_aponta_para_o_lugar_fixo(monkeypatch, tmp_path):
    from videoscraper import instalacao
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\Ana\AppData\Local")
    assert str(instalacao.executavel_fixo()).replace("/", "\\").endswith(r"Programs\videoscraper\videoscraper.exe")
    script = instalacao.script_atalhos(r"C:\Users\Ana's\AppData\Local\Programs\videoscraper\videoscraper.exe")
    assert "GetFolderPath('Desktop')" in script and "GetFolderPath('Programs')" in script
    assert "'C:\\Users\\Ana''s\\AppData" in script                      # aspas simples escapadas
    assert "'Maestro.lnk'" in script and "'videoscraper.lnk'" in script and "Remove-Item" in script   # o antigo sai
    origem = tmp_path / "Downloads"
    with __import__("pytest").raises(OSError):
        instalacao.copiar_para_pasta_fixa(origem, tmp_path / "fixo")      # sem o .exe: recusa
    (origem / "_internal").mkdir(parents=True)
    (origem / "videoscraper.exe").write_bytes(b"novo")
    (tmp_path / "fixo").mkdir()
    (tmp_path / "fixo" / "videoscraper.exe").write_bytes(b"velho")
    exe = instalacao.copiar_para_pasta_fixa(origem, tmp_path / "fixo")      # por cima do que havia
    assert exe.read_bytes() == b"novo"


def test_iniciar_com_o_windows_apontando_para_exe_antigo_e_corrigido(tmp_path, monkeypatch):
    """Caso real: reiniciou o PC e o programa não abriu (o registro apontava para uma cópia antiga/apagada)."""
    import sys
    from videoscraper import inicializacao
    registro = {"videoscraper": r'"C:\Users\Ana\Downloads\velho\videoscraper.exe" --minimizado'}

    class Reg:
        HKEY_CURRENT_USER, REG_SZ = 1, 1

        class _C:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

        def CreateKey(self, *a):
            return self._C()
        OpenKey = CreateKey

        def SetValueEx(self, chave, nome, _, tipo, valor):
            registro[nome] = valor

        def QueryValueEx(self, chave, nome):
            if nome not in registro:
                raise FileNotFoundError(nome)
            return registro[nome], 1
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "Downloads" / "novo" / "videoscraper.exe"))
    fixo = tmp_path / "Programs" / "videoscraper" / "videoscraper.exe"
    fixo.parent.mkdir(parents=True)
    fixo.write_bytes(b"exe")
    assert inicializacao.corrigir_se_preciso(fixo, Reg()) is True
    assert registro["videoscraper"] == f'"{fixo}" --minimizado'            # o lugar fixo tem preferência
    assert inicializacao.corrigir_se_preciso(fixo, Reg()) is False          # já está certo: não mexe
    registro.clear()
    assert inicializacao.corrigir_se_preciso(fixo, Reg()) is False and registro == {}   # desligado: continua


def test_aviso_de_icones_ao_windows_sem_apagar_cache():
    from videoscraper import instalacao
    chamadas = []

    class Shell32:
        def SHChangeNotify(self, *args):
            chamadas.append(args)
    assert instalacao.avisar_windows_icones(Shell32())
    assert chamadas == [(0x08000000, 0, None, None)]                  # SHCNE_ASSOCCHANGED: "ícones mudaram"

    class Quebrado:
        def SHChangeNotify(self, *args):
            raise OSError("sem shell")
    assert not instalacao.avisar_windows_icones(Quebrado())          # falhar não derruba os atalhos
    assert "iconcache" not in open(instalacao.__file__, encoding="utf-8").read().lower().replace(
        "cache de ícones", "")                                       # nunca apaga o cache


def test_maestro_exe_e_o_principal_e_o_antigo_fica_escondido(tmp_path, monkeypatch):
    from videoscraper import instalacao
    pasta = tmp_path / "Programs" / "videoscraper"
    pasta.mkdir(parents=True)
    (pasta / "videoscraper.exe").write_bytes(b"x")
    assert instalacao.executavel_principal(pasta).name == "videoscraper.exe"   # instalação antiga: só ele
    chamadas = []

    class Kernel32:
        def SetFileAttributesW(self, caminho, atributos):
            chamadas.append((caminho, atributos))
            return 1
    assert not instalacao.esconder_exe_antigo(pasta, Kernel32())             # sem o Maestro.exe: não esconde
    (pasta / "Maestro.exe").write_bytes(b"x")
    assert instalacao.executavel_principal(pasta).name == "Maestro.exe"
    assert instalacao.esconder_exe_antigo(pasta, Kernel32())
    assert chamadas == [(str(pasta / "videoscraper.exe"), 0x2)]              # FILE_ATTRIBUTE_HIDDEN

    origem = tmp_path / "Downloads" / "videoscraper"
    (origem / "_internal").mkdir(parents=True)
    for nome in ("videoscraper.exe", "Maestro.exe"):
        (origem / nome).write_bytes(b"novo")
    assert instalacao.copiar_para_pasta_fixa(origem, tmp_path / "fixo").name == "Maestro.exe"


def test_atualizacao_reabre_o_mesmo_exe_que_estava_aberto(tmp_path, monkeypatch):
    import subprocess
    import sys
    from videoscraper import atualizacao
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "linux")                          # o caminho sem as opções do Windows
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: None)          # não roda o PowerShell
    for aberto in ("Maestro.exe", "videoscraper.exe"):
        monkeypatch.setattr(sys, "executable", str(tmp_path / aberto))
        texto = atualizacao.instalar_ao_fechar(tmp_path / "x.zip", pasta=tmp_path, pid=1).read_text(encoding="utf-8-sig")
        assert f"Start-Process -FilePath '{tmp_path / aberto}'" in texto        # reabre o MESMO que estava aberto
        assert "'videoscraper.exe'" in texto                                   # o .zip continua conferido por ele
