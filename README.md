# Extrator de links de vídeos públicos

Programa em Python que visita páginas web e coleta os **endereços** de vídeos públicos
(não baixa os vídeos).

## Rodar no seu computador (passo a passo)

1. **Instale o Python 3.9+** em <https://www.python.org/downloads/>.
   No Windows, marque **"Add python.exe to PATH"** durante a instalação.
2. **Traga os arquivos** (escolha um):
   - Com Git: `git clone https://github.com/izaeldepetriz-br/Webscraping.git`
   - Sem Git: no GitHub, abra o repositório → **Code → Download ZIP** e extraia.
3. **Entre na pasta do projeto e inicie:**
   - **Windows:** duplo clique em `iniciar.bat`
   - **Linux/Mac:** `./iniciar.sh`

   Na primeira vez ele cria o ambiente virtual (`.venv`) e instala as dependências sozinho.
   Depois abre um menu: cole a URL e escolha listar ou baixar.

Os vídeos baixados ficam na pasta `videos_baixados/` (dentro da pasta do projeto).

## Instalação manual

```bash
cd webscraping
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Uso

```bash
# Uma página, resultado na tela
python extrair_links_videos.py https://exemplo.com/videos

# Seguindo links até 2 níveis, salvando em CSV (também aceita .json e .txt)
python extrair_links_videos.py https://exemplo.com -p 2 -s links.csv
```

Opções: `-p` profundidade, `-m` máx. de páginas, `-e` espera entre requisições (s),
`-s` arquivo de saída, `--qualquer-dominio`, `--ignorar-robots`.

## O que ele detecta

`<video>`, `<source>`, `<iframe>` (YouTube, Vimeo, Dailymotion...), `<a href>` para
`.mp4/.webm/.mkv/.m3u8...`, meta `og:video`, JSON-LD `VideoObject` e URLs de vídeo
dentro de scripts.

## Baixar os vídeos de uma listagem (`baixar_videos.py`)

Versão evoluída do script de 6 etapas (requisição → parse → extração → download):

```bash
python baixar_videos.py https://exemplo.com/videos/acao                 # baixa tudo
python baixar_videos.py URL --so-listar                                 # só mostra os links
python baixar_videos.py URL -s "a.video-link" -p meus_videos -e 3 -l 5  # seletor, pasta, espera, limite
```

Melhorias em relação ao script original: download em blocos com progresso (não enche a
memória), `raise_for_status` e `timeout`, links relativos resolvidos com `urljoin`,
título sanitizado como nome de arquivo (sem `/`, `:` etc.), sem sobrescrever arquivos,
arquivo `.part` apagado se o download falhar, e respeito ao `robots.txt`.

## Limites e uso responsável

- Respeita `robots.txt` e espera entre requisições por padrão.
- Só vê o que está no HTML. Páginas que montam o conteúdo com JavaScript podem exigir
  Selenium/Playwright (não incluído).
- Use apenas em conteúdo público e respeitando os termos de uso do site.

## Testes

```bash
pip install pytest && python -m pytest -q
```
