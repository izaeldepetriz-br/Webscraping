# videoscraper: extrair e baixar vídeos públicos

Programa em Python que encontra links de vídeo em páginas web e, se você quiser, baixa os vídeos.
Funciona em sites simples (só HTML) e também em sites que **montam a página com JavaScript**,
que **exigem login** ou que mostram **verificações** que você resolve na janela do navegador.

## Rodar no seu computador

1. Instale o **Python 3.9+** em <https://www.python.org/downloads/>.
   No Windows, marque **"Add python.exe to PATH"** na instalação.
2. Baixe este repositório: **Code → Download ZIP** e extraia (ou `git clone`).
3. Na pasta do projeto:
   - **Windows:** duplo clique em **`iniciar.bat`** (não no `iniciar.py`).
   - **Linux/Mac:** `./iniciar.sh`

Na primeira vez ele cria o ambiente `.venv`, instala as bibliotecas e baixa o navegador
Chromium (~150 MB). Isso só acontece uma vez. Depois abre **a janela do programa**:

1. Cole o endereço da página e clique em **Buscar vídeos**.
2. Os vídeos aparecem na tabela. Duplo clique abre o link; **Copiar link** e
   **Salvar lista** (CSV/JSON/TXT) também estão lá.
3. Selecione (Ctrl+clique para vários) e clique em **Baixar selecionados**, ou **Baixar todos**.

Opções da janela:

- **Usar navegador**: para sites que montam a lista com JavaScript ou exigem login.
- **Mostrar a janela do navegador** / **Pausar para eu resolver verificações**: abre o Chrome
  para você ver/resolver (aviso de cookies, "não sou um robô"). O programa espera seu OK.
- **Fazer login no site**: abre o site para você entrar com a sua conta; a sessão fica salva.
- **Parar**: interrompe depois do item atual.

Prefere o menu de texto antigo? `python iniciar.py --texto`.

### Por que o YouTube (e similares) não funciona?

O arquivo `robots.txt` do YouTube **proíbe robôs** nas páginas de busca, e os termos de uso
proíbem baixar vídeos sem o botão oficial de download. O programa respeita isso e mostra o aviso
"Acesso não permitido". Para **pesquisar** vídeos do YouTube por programa, o caminho permitido é a
**API oficial (YouTube Data API)**, que precisa de uma chave gratuita do Google.

## Dois modos de acesso

| | Modo simples (padrão) | Modo navegador (`--navegador`) |
|---|---|---|
| Como funciona | `requests` baixa só o HTML | Chrome de verdade (Playwright) abre a página |
| Velocidade | Rápido, leve | Mais lento |
| JavaScript | Não executa | Executa (vê listas montadas por JS) |
| Login | Não | Sim, com a sua conta (comando `login`) |
| Vídeos pedidos pelo player | Não vê | Vê (captura `.mp4`/`.m3u8` na rede) |
| iframes | Só o endereço | Lê o conteúdo também |

Comece pelo simples. Se aparecer "0 links", tente com `--navegador`.

## Comandos (terminal)

Com o ambiente ativado (`.venv\Scripts\activate` no Windows, `. .venv/bin/activate` no Linux/Mac):

```bash
# Listar links (salva em .csv, .json ou .txt; o .csv abre no Excel com acentos)
python -m videoscraper links https://site.com/videos -s links.csv

# Página que carrega os vídeos com JavaScript
python -m videoscraper links https://site.com/videos --navegador

# Baixar por seletor CSS, seguindo 1 nível de links, no máximo 5 vídeos
python -m videoscraper baixar https://site.com/videos --seletor "a.video-link" -p 1 -l 5 -d meus_videos

# Site com login: 1) entre na sua conta uma vez  2) use --navegador normalmente
python -m videoscraper login https://site.com/entrar
python -m videoscraper baixar https://site.com/minha-area --navegador

# Site com verificação ("não sou um robô", aviso de cookies): resolva você mesmo na janela
python -m videoscraper links https://site.com/videos --pausar
```

Opções úteis: `-e` espera entre pedidos (padrão 1.5 s), `--visivel` mostra a janela,
`--so-listar` não baixa nada, `--qualquer-dominio` segue links para outros sites,
`--chrome CAMINHO` usa um Chrome já instalado.

## O que ele detecta e baixa

- **Detecta:** `<video>`, `<source>`, `<iframe>` (YouTube, Vimeo...), `<a href>` para
  `.mp4/.webm/.mkv/.mov/.m3u8/.mpd`, meta `og:video`, JSON-LD `VideoObject`, URLs em scripts
  e (modo navegador) vídeos que o player pede pela rede.
- **Baixa:** arquivos diretos (em blocos, com progresso, sem sobrescrever) e **streaming HLS/DASH**
  (`.m3u8`/`.mpd`), que o ffmpeg junta num `.mp4`. O ffmpeg já vem no pacote `imageio-ffmpeg`.
- **Não baixa:** players de outros sites (YouTube, Vimeo). Esses aparecem na lista mas são pulados.

## Limites e uso responsável

- Respeita o `robots.txt` e espera entre pedidos. `--ignorar-robots` só em sites seus.
- **Não contorna** CAPTCHA, sistemas anti-robô, paywall nem **DRM** (Netflix, Globoplay, Prime...).
  Quando aparece uma verificação, quem resolve é você, na janela (`--pausar`).
  Se o site proíbe automação nos termos de uso, não use nele.
- O login fica salvo em `.perfil_navegador/` (inclusive o arquivo `sessao_cookies.json`).
  **Essa pasta dá acesso à sua conta: não compartilhe e não envie para o GitHub**
  (já está no `.gitignore`). Para "sair", apague a pasta.
- Baixe só conteúdo que você tem direito de baixar.

## Estrutura do código

```
videoscraper/
  extracao.py   lê HTML e acha links (não acessa a internet)
  rede.py       requests: robots.txt, pausas, novas tentativas, cookies
  navegador.py  Playwright: JavaScript, login, captura de rede, sessão salva
  coleta.py     junta tudo: obtém páginas (requests OU navegador) e navega entre elas
  download.py   salva arquivos (blocos/.part) e streaming (ffmpeg)
  servico.py    camada comum (buscar/baixar) usada pela janela e pelo terminal
  gui.py        janela com botões (Tkinter)
  cli.py        comandos links / baixar / login
  menu.py       menu de texto (python iniciar.py --texto)
jellyfin_tools/
  nomes.py       lê nomes bagunçados e monta "Nome (Ano)"
  catalogo.py    confirma título/ano (JSON local ou API do TMDB)
  organizador.py move/renomeia no padrão do Jellyfin, com simulação e desfazer
  legendas.py    busca/baixa legendas (site HTML ou API do OpenSubtitles)
  site_demo.py   site de legendas simulado, para demonstração e testes
exemplo_jellyfin.py  como integrar no seu arquivo principal
tests/          testes com servidores locais (sem internet)
```

## Jellyfin: organizar filmes e baixar legendas (`jellyfin_tools`)

Pacote separado para a biblioteca do Jellyfin.

**Parte 1, organizador:** lê nomes bagunçados, confirma título e ano num catálogo e move para o
padrão do Jellyfin.

| Arquivo bagunçado | Vira |
|---|---|
| `Matrix.1999.1080p.BluRay.x264-VERSAO.mp4` | `Filmes/Matrix (1999)/Matrix (1999).mp4` |
| `interestellar_filme_completo_dublado_2014.mkv` | `Filmes/Interstellar (2014)/Interstellar (2014).mkv` |
| `O.Poderoso.Chefao.1972.Bluray.mkv` | `Filmes/O Poderoso Chefão (1972)/O Poderoso Chefão (1972).mkv` |

**Parte 2, legendas:** busca a legenda pt-BR e salva ao lado do vídeo com o mesmo nome:
`Matrix (1999).pt-BR.srt` (sempre em UTF-8; aceita `.srt`, `.zip` e codificação antiga do Windows).

### Experimente (sem mexer nos seus arquivos)

```bash
python -m jellyfin_tools demo
```

Cria a pasta `demo_jellyfin/` com os 3 arquivos fictícios, organiza, baixa as legendas de um
**site de legendas simulado** (local) e mostra a árvore de pastas antes e depois.

### Usar nos seus arquivos

```bash
# 1) Simulação: mostra o que faria, não move nada
python -m jellyfin_tools organizar "C:/Users/Voce/Downloads" "D:/Jellyfin/Filmes"
# 2) De verdade
python -m jellyfin_tools organizar "C:/Users/Voce/Downloads" "D:/Jellyfin/Filmes" --aplicar
# 3) Arrependeu? Desfaz a última organização
python -m jellyfin_tools desfazer "D:/Jellyfin/Filmes"
# Legendas que faltam na biblioteca (API oficial do OpenSubtitles)
python -m jellyfin_tools legendas "D:/Jellyfin/Filmes" --opensubtitles
```

No seu próprio código, veja `exemplo_jellyfin.py`. As funções principais são `organizar_pasta`,
`desfazer`, `baixar_legenda` e `baixar_legendas_biblioteca`.

### De onde vêm os nomes e as legendas

- **Catálogo local** (`jellyfin_tools/catalogo_filmes.json`): funciona offline; acrescente seus filmes.
- **TMDB** (`--tmdb`, variável `TMDB_API_KEY`): API oficial e gratuita, a mesma base que o Jellyfin usa.
- **Legendas, API do OpenSubtitles** (`--opensubtitles`, variável `OPENSUBTITLES_API_KEY`):
  gratuita, com limite de downloads por dia.
- **Legendas, site HTML** (`--site-legendas "https://site/busca?q={consulta}"`): raspagem com
  BeautifulSoup e seletores configuráveis (`ConfigSite`). Respeita o `robots.txt`.

O programa usa as APIs oficiais em vez de raspar os sites do IMDb, TMDB e OpenSubtitles, porque
os termos de uso deles proíbem raspagem.

### Segurança dos seus arquivos

- Sem `--aplicar`, nada é movido.
- Nunca sobrescreve: se o destino já existe, o arquivo fica onde está (`conflito`).
- Legendas e `.nfo` com o mesmo nome do vídeo vão junto.
- Todo movimento fica num log em `Filmes/.organizador/`, que o `desfazer` usa.

## Testes

```bash
pip install pytest && python -m pytest -q tests
```

Os testes do modo navegador são pulados se o Chromium não estiver instalado, e os da janela
se não houver tela (no Linux sem monitor: `xvfb-run python -m pytest -q tests`).
