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
Chromium (~150 MB). Isso só acontece uma vez. Depois abre o menu:

```
1) Listar links de vídeo de uma página
2) Baixar vídeos de uma página
3) Ver o que seria baixado (sem baixar)
4) Fazer login num site (abre o navegador; a sessão fica salva)
```

O menu mostra o **comando equivalente** antes de rodar, para você aprender a usar direto no terminal.

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
  cli.py        comandos links / baixar / login
  menu.py       menu interativo
tests/          testes com servidor local (sem internet)
```

## Testes

```bash
pip install pytest && python -m pytest -q tests
```

Os testes do modo navegador são pulados automaticamente se o Chromium não estiver instalado.
