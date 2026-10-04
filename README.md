# videoscraper: extrair e baixar vídeos públicos

Programa em Python que encontra links de vídeo em páginas web e, se você quiser, baixa os vídeos.
Funciona em sites simples (só HTML) e também em sites que **montam a página com JavaScript**,
que **exigem login** ou que mostram **verificações** que você resolve na janela do navegador.

## Programa pronto para Windows (.exe, sem instalar o Python)

- **Baixar pronto:** página **Releases** do repositório → a versão mais nova → **Assets** →
  `videoscraper-windows.zip`. Descompacte e abra `videoscraper\videoscraper.exe`. (Também em **Actions** →
  "Gerar o .exe (Windows)" → a execução mais recente → **Artifacts**, que expiram depois de um tempo.)
- **Publicar uma versão nova:** Actions → "Gerar o .exe (Windows)" → **Run workflow** → `versao` = `v1.1`.
- **Gerar no seu PC:** dê duplo clique em `gerar_exe.bat` (precisa do Python só para gerar).
  O programa fica em `dist\videoscraper\` — para levar para outro computador, copie a pasta inteira.
- O modo navegador baixa o Chromium sozinho na primeira vez (~150 MB), também no `.exe`. Ele fica em
  `C:\Users\<você>\AppData\Local\ms-playwright` (fora da pasta do programa: trocar de versão não baixa de novo).
- Autoteste do pacote: `videoscraper.exe --verificar` e `--verificar-navegador` (baixa o Chromium e abre uma
  página); o robô do GitHub roda os dois a cada versão.

## Rodar no seu computador

1. Instale o **Python 3.9+** em <https://www.python.org/downloads/>.
   No Windows, marque **"Add python.exe to PATH"** na instalação.
2. Baixe este repositório: **Code → Download ZIP** e extraia (ou `git clone`).
3. Na pasta do projeto:
   - **Windows:** duplo clique em **`iniciar.bat`** (não no `iniciar.py`).
   - **Linux/Mac:** `./iniciar.sh`

Na primeira vez ele cria o ambiente `.venv`, instala as bibliotecas e baixa o navegador
Chromium (~150 MB). Isso só acontece uma vez. Depois abre **a janela do programa**, em
Dark Mode (CustomTkinter):

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

Outras interfaces: `python iniciar.py --classica` (janela cinza antiga) ou
`python iniciar.py --texto` (menu no terminal).

### Aba Jellyfin (organizar filmes e séries)

No topo da janela, troque de **Vídeos** para **Jellyfin**:

1. Escolha **Filmes** ou **Séries**, a pasta com os arquivos bagunçados e a pasta da biblioteca
   (a mesma cadastrada no painel do Jellyfin: Painel → Bibliotecas → Pastas).
   Se os arquivos bagunçados **já estão dentro da biblioteca**, use a mesma pasta nos dois campos:
   o que já está no padrão aparece como "já organizado" e não é mexido, e as pastas que
   ficarem vazias depois de mover são apagadas.
2. **Pré-visualizar** mostra "arquivo atual → novo nome" e não move nada.
3. **Organizar** só fica disponível depois da pré-visualização. Se você mudar pastas ou opções,
   precisa pré-visualizar de novo. Move, renomeia e, se marcado, baixa as legendas.
4. **Desfazer última** devolve os arquivos. **Baixar legendas que faltam** percorre a biblioteca.

As pastas e opções ficam salvas em `~/.videoscraper/config.json` (fora do projeto). As chaves de
API só são salvas se você marcar "Lembrar as chaves neste computador".

### Melhorias na aba Jellyfin (as mesmas do script)

O painel lateral tem as seções **Nomes e metadados (TMDB)**, **Servidor Jellyfin** (com "Testar
conexão") e **Avisos** (com "Enviar aviso de teste"). Ao **Organizar**, depois de mover, o programa
baixa legenda, pôster/backdrop e `.nfo`, avisa no Discord/Telegram e pede **um** scan ao Jellyfin.
**Completar biblioteca** faz o mesmo (sem avisos) nos filmes que já estão organizados. **Abrir log**
mostra o `jellyfin_organizer.log` (fica em `~/.videoscraper/`).

Velocidade: os filmes são processados **4 ao mesmo tempo** (a internet é o gargalo); as legendas
continuam uma por vez, para não ser bloqueado pelos sites de legenda.

Outras opções da aba Jellyfin:

- **Mostrar:** (acima da tabela) escolha quais situações aparecem, ex.: desmarque "Já organizado"
  para ver só o que vai mudar. É só visual: o contador mostra "X de Y" e o **Organizar** avisa se
  algum "vai mover" está escondido.
- **Legendas em vários idiomas:** marque Português, Inglês, Espanhol e/ou escreva outros em
  "Outros idiomas" (ex.: `fr, it`). Um arquivo por idioma: `Nome (Ano).pt-BR.srt`, `Nome (Ano).en.srt`.
- **Apagar a pasta do torrent depois de transferir:** apaga a pasta inteira (amostras, prints,
  `.nfo` de release...) depois que o filme saiu dela. Por segurança, só se não sobrar nenhum outro
  vídeo nela e nunca a própria pasta de origem. A pré-visualização mostra quais pastas serão apagadas.
- **Testar conexão com o TMDB:** confere a chave (v3 ou token v4) e a internet. Abaixo do botão
  aparece "✓ TMDB conectado" ou o motivo do erro.
- **Coluna "Nome via":** de onde veio o nome novo de cada arquivo. Com o TMDB marcado: `TMDB ✓`
  (o TMDB identificou) ou `TMDB ✕ (catálogo)` / `TMDB ✕ (arquivo)` (não identificou; o nome veio do
  catálogo local ou do próprio arquivo, confira). Sem o TMDB: `catálogo` ou `arquivo`. O rodapé
  resume: "TMDB identificou 150 de 166". Se o TMDB não responder, um aviso explica o motivo.
- **Séries: nome do episódio depois do número:** com o TMDB, `Dark S01E01.mkv` vira
  `Dark S01E01 - Segredos.mkv` (o número continua; as legendas acompanham o novo nome). Episódios já
  organizados só com o número também são renomeados. Se o TMDB ainda não tem o nome traduzido
  ("Episódio 3"), fica só o número; um nome que o arquivo já tinha nunca é apagado.
- **Séries de torrent** (ex.: uma pasta por temporada com `BLUDV.TV.mp4`): o vídeo pequeno com
  cara de propaganda que NÃO é episódio vira lixo (episódios curtos continuam a salvo), e a imagem de
  cada episódio (`The.Office.S01E01...-poster.jpg`) vira a miniatura dele no padrão do Jellyfin:
  `The Office S01E01 - Piloto-thumb.jpg`. Sem a propaganda, a pasta da temporada pode ser apagada.
- **Sobras de uma organização anterior:** com "Apagar a pasta do torrent" marcado, a prévia lê os
  logs em `.organizador` e mostra as pastas que o próprio organizador já esvaziou antes e onde só
  sobrou propaganda/imagens ("vai apagar a pasta"). Ao organizar, as imagens dos episódios vão para
  junto deles e a pasta é apagada. Pastas que não estão no log, ou que ainda têm vídeo de verdade,
  nunca são mexidas.
- **Completar biblioteca** pergunta antes de começar: **Só o que falta** ou **Substituir o que já
  existe** (baixa de novo e troca legenda, pôster, backdrop e `.nfo`; os vídeos não são mexidos).
  A caixa "Substituir o que já existe" vale também para o Organizar.
- **Ampliar lista:** esconde o painel "Antes → Depois" e o console; a tabela ocupa a altura toda
  (o andamento continua no rodapé). Clique de novo em "Reduzir lista" para voltar.
- **Nome do episódio sem tradução:** se o TMDB não tem o nome em português ("Episódio 25"), usa o
  nome original em inglês; sem nenhum dos dois, fica só o número.
- **Caminho conferido antes de tudo:** um endereço colado dentro de outro
  (`E:\Series_OE:\Series_Organizadas\...`) ou caracteres que o Windows não aceita (`< > " | ? *`)
  são avisados antes da prévia, com a correção sugerida (a partir do último `E:\`). O motor também
  recusa o caminho antes de mexer em qualquer arquivo (antes, cada arquivo dava "WinError 123").
- **Organizar × Completar biblioteca:** os dois usam o MESMO pós-processamento (legenda em cada
  idioma, pôster/backdrop/`.nfo` nos filmes e um scan do Jellyfin no fim). A diferença:
  **Organizar** move/renomeia o que está na pasta de origem e processa só o que acabou de mover
  (e avisa no Discord/Telegram); **Completar biblioteca** não move nada e passa por TUDO que já está
  na biblioteca, baixando só o que falta (ou trocando, se escolher "Substituir"). Agora vale também
  para séries (antes, nas séries, o Completar só baixava legendas e não pedia o scan).
- **Registro por ação:** o console "O que está acontecendo" guarda um registro para cada ação
  (Pré-visualizar, Organizar, Completar, testes). O seletor no topo do console mostra a atual ou
  uma anterior (até 30). Cada ação também grava um arquivo só dela em `~/.videoscraper/logs/`
  (ex.: `2026-10-04_13-24-05_Organizando.log`); **Abrir log** abre o arquivo da ação escolhida no
  seletor (antes abria o log geral, com tudo do dia). O `jellyfin_organizer.log` continua com tudo,
  cada ação começando com `===== Organizando =====`. O script faz o mesmo em `logs/`, ao lado do
  `ARQUIVO_LOG`. Ficam os 200 arquivos mais recentes.
- **Legendas de séries:** a busca não usa mais o ano da série (o OpenSubtitles guarda o ano do
  EPISÓDIO: a 2ª temporada de The Last of Us é de 2025, a série é de 2023), que descartava todas as
  legendas das temporadas mais novas.
- **Propaganda repetida:** vídeo pequeno, que não é episódio, com o MESMO nome em 3 ou mais pastas
  (ex.: `BAIXAR PROXIMO EPISÓDIO.mp4` em cada pasta de episódio) é tratado como propaganda.
- **Formatos de episódio aceitos:** `S01E02`, `1x02`, `1x (11)` (número entre parênteses, como em
  "Um maluco no pedaço 1x (11).avi"), "Temporada 2 Episódio 4", "Episódio 3" (temporada 1) e o de
  **anime**, só com o número (temporada 1): `HunterXHunter 01`, `Dragon Ball 001 - 1280x960`,
  `[Grupo] Hunter x Hunter - 01 (1080p)`, `One.Piece.1071`. Palavras grudadas (`HunterXHunter`)
  são separadas para a busca.
- **Ano da pasta como dica:** sem ano no nome do arquivo, o ano da pasta escolhe entre séries de
  mesmo nome (`hunter-x-hunter-1999/` → Hunter x Hunter de 1999, e não o de 2011).
- **Testar chaves das legendas:** botão abaixo das chaves (OpenSubtitles e/ou SubDL); faz uma busca de
  teste (que não gasta a cota de downloads) e mostra ✓/✕ para cada fonte.
- **SubDL** (<https://subdl.com>, chave gratuita em Painel → API): fonte de legendas própria
  ("SubDL (API)") ou **reserva do OpenSubtitles**: com a fonte "OpenSubtitles (API)", preencha
  também "Reserva: chave do SubDL". Quando o OpenSubtitles não acha a legenda ou atinge o limite
  diário, o SubDL é consultado; depois do limite, o OpenSubtitles não é mais chamado naquela
  execução. No script: `SUBDL_API_KEY`; na linha de comando: `--subdl`.
- **Episódio no modo Filmes:** arquivo com `S05E19`, `5x19` ou "Temporada 5 Episódio 19" aparece
  como "é episódio de série (S05E19): use o modo Séries" (e não é consultado no TMDB como filme).
  Anime com numeração contínua também ("Samurai X - 01", "- 02"... na mesma pasta, sem ano). Se a
  biblioteca escolhida for a pasta da própria série (ex.: `Animes\Samurai X`), a sugestão usa a de
  cima (`Animes`), para não criar `Samurai X\Samurai X`.
  Se a maioria da prévia for episódio, a janela pergunta se deve trocar para **Séries** e
  pré-visualizar de novo. ("Star.Wars.Episode.4.1977" continua sendo filme.)
- **Cópias de qualidade diferente:** duas cópias do mesmo filme/episódio (ex.: 720p e 1080p) → vai a
  **melhor**: resolução (2160p > 1080p > 720p), depois a origem (Remux > BluRay > WEB-DL > WEBRip >
  HDTV > DVD; CAM/TS por último) e, no empate, o arquivo maior. As outras ficam como "conflito"
  dizendo qual foi no lugar. Se o filme já está na biblioteca, nada é sobrescrito: a linha mostra o
  tamanho das duas para você decidir.
- **Anime com numeração contínua** (`Dragon Ball 153`): com o TMDB, o número vira a temporada e o
  episódio certos (ex.: S04E70), pela quantidade de episódios de cada temporada no TMDB (um pedido
  por série). Sem o TMDB, ou se o número passa do que ele conhece, fica na temporada 1.
- **Várias pastas vigiadas (ex.: as do uTorrent), filmes e séries separados sozinhos:** na seção
  "Automático", liste as pastas de download (uma por linha, ou "Adicionar pasta..."). Em cada uma,
  episódios (S01E02, 1x02, ou só o número sem ano de filme, como em anime) vão para a biblioteca de
  **Séries** e o resto para a de **Filmes** (as duas escolhidas na aba, trocando Filmes/Séries no
  topo). Serve para pastas separadas e também para uma pasta misturada. Lista vazia = a pasta de
  origem. No script: `VIGIAR_PASTAS = [r"D:\Torrent\Filmes", r"D:\Torrent\Series"]` e `PASTA_SERIES`.
- **Pasta vigiada** (seção "Automático"): a cada N minutos confere a pasta de origem e organiza
  **sozinho, sem perguntar,** o que terminou de baixar (arquivo parado há 2 min e sem `.part`,
  `.!qB`, `.crdownload` na pasta), com as mesmas opções da aba (legendas, lixo, scan, avisos no
  Discord/Telegram). Fica ligada entre uma vez e outra que abrir o programa. No qBittorrent, marque
  "Acrescentar a extensão .!qB a arquivos incompletos". No script: `--vigiar`
  (`VIGIAR_A_CADA_MIN`, `PRONTO_APOS_MIN`).
- **Conferir espelhos:** confere o link de cada `.strm` das bibliotecas (o site ainda tem o vídeo?),
  mostra "funcionando"/"quebrado" na tabela e oferece remover os quebrados.
- **Conferir espelhos automaticamente** (seção "Automático"): marque "Conferir os espelhos (.strm)
  sozinho" e escolha em "A cada:" **N minutos, horas ou dias** (ex.: 30 minutos, 12 horas, 7 dias; mínimo de 5 minutos, para não sobrecarregar os sites). O programa confere os
  `.strm` das duas bibliotecas nesse intervalo (mesmo que fique fechado: ao abrir, se já passou do
  prazo, confere em 1 minuto) e **avisa no Discord/Telegram** só quando algum link quebrar
  ("🔗 2 espelho(s) quebrado(s) no Jellyfin" + nome e motivo). Com "Remover os quebrados (dá para desfazer)" marcado,
  ele também apaga esses `.strm` (o "Desfazer última" os recoloca). A data da última conferência
  aparece embaixo. No script: `CONFERIR_ESPELHOS_A_CADA = "7d"` (ou `"12h"`, `"30min"`), que roda junto com o
  `--vigiar`, `REMOVER_ESPELHOS_QUEBRADOS` e `--conferir-espelhos` para conferir uma vez agora.
- **Relatório da biblioteca** (botão "Relatório"; **"Abrir relatório"**, em cima da lista, abre a planilha mais
  recente, e oferece gerar uma se ainda não houver): lista o que falta, sem mexer em nada:
  filmes **sem legenda** (em cada idioma escolhido; legenda "forced" não conta), filmes **sem
  pôster** e **episódios faltando** numa temporada ("Dark — S02: falta E05, E07–E09"; com o TMDB
  também o fim da temporada e temporadas inteiras) e episódios sem legenda. Aparece na tabela e é
  salvo em `.csv` (abre no Excel) em `C:\Users\<você>\.videoscraper\relatorios`. No script:
  `--relatorio`. Complementa o Sonarr: ele busca os episódios que faltam; o relatório também cobre
  filmes, legendas e pôsteres.
- **Remover qualquer espelhamento (não só o último):** o botão **"Espelhos..."** lista os `.strm` das
  duas bibliotecas agrupados por espelhamento ("Espelhamento 1 — 04/10/2026 18:10 · 12 item(ns)",
  "Espelhamento 2"...; os feitos à mão ficam em "Sem registro"). Selecione um espelhamento inteiro
  (ex.: o 1º de 3) ou só um filme/episódio (campo "Procurar", Ctrl+clique para vários) e clique em
  **Remover selecionados**. Saem junto a legenda, a miniatura e o `.nfo` de mesmo nome, e a pasta do
  filme/temporada/série se ficar sem nenhum vídeo (vídeos baixados nunca são tocados). Nada é
  apagado de vez: vai para `.organizador/removidos` dentro da biblioteca (o Jellyfin ignora essa
  pasta) e **"Desfazer última remoção"** põe de volta, nas duas bibliotecas de uma vez. Os números
  dos espelhamentos não mudam depois de uma remoção. No script: `--espelhos` (lista),
  `--remover-espelhos 1` ou `--remover-espelhos "Nosferatu"` (só simula; com `--aplicar` remove) e
  `--desfazer-remocao-espelhos`.
- **Desfazer o espelho:** "Desfazer última" também vale para o espelho: apaga os `.strm` criados (com a
  legenda/miniatura de mesmo nome e as pastas que o espelho criou, se não tiverem vídeo) e recoloca
  os `.strm` que o "Conferir espelhos" removeu.
- **Mais padrões de nome de episódio:** número entre parênteses (`Pica-Pau.WEB.DUB-WWW.BLUDV.COM (75).mkv` →
  `Pica Pau S01E75`), temporada.episódio com pontos (`Regular.Show.03.15-by-fulano.avi` → S03E15),
  `S012E20` (→ S12E20) e arquivo sem o nome da série (`Temp 01 - Epi 04 - Socos Mortais.mkv`,
  `04-01 Saída 9B.mkv`): a série vem da pasta (`Apenas um Show - 1a Temporada` → "Apenas um Show"; pastas
  como "Desenhos", "Animes" e "Season 01" não contam). Também: `O Mentalista HDTV 01-21.mkv` (→ S01E21),
  só o número no começo (`13 - To'hajiilee.mp4` em `Breaking Bad 5 Temporada Parte 2` → Breaking Bad S05E13;
  `61 Ninguém Pega Esse Coelho!.avi` em `As Aventuras De Jackie Chan` → episódio 61, que o TMDB põe na
  temporada certa) e nome + número + saga (`HunterXHunter 66_York Shin.mp4`, aceito quando há outros
  números da mesma série na pasta; o ano 1999 vem da pasta `1999 - Hunter x Hunter`).
  **Nome do episódio depois do número:** o que vier no arquivo fica (`13 - To'hajiilee` → `Breaking Bad S05E13 -
  To'hajiilee`, `61 Ninguém Pega Esse Coelho!` → `... S01E61 - Ninguém Pega Esse Coelho!`); com o TMDB e
  "Séries: nome do episódio depois do número" marcados, o nome do TMDB vem primeiro (é assim que
  `O Mentalista HDTV 01-21`, que não traz o nome, ganha o dele). No formato de saga do Hunter x Hunter, fica o
  nome da saga (`Hunter X Hunter S01E66 - York Shin`). Um `BLUDV.mp4` pequeno ao lado de arquivos
  `...WWW.BLUDV.COM...` fica como "ignorado: propaganda do site".
- **Totais nos filtros:** cada caixa de "Mostrar" diz quantos arquivos tem ("Não identificado (540)"), e
  "Mostrar todos" marca todas de novo. Os resultados de "Conferir espelhos", "Relatório" e "Completar
  biblioteca" sempre aparecem inteiros (a lista não fica vazia por causa de um filtro da prévia).
- **Porcentagem na pré-visualização:** o rodapé mostra "Pré-visualizando... 45% · Consultando o
  TMDB: 75 de 166" e a barra acompanha.

Velocidade do TMDB: as consultas são feitas **6 ao mesmo tempo** antes de planejar, e as respostas
ficam guardadas enquanto o programa estiver aberto. Medido com 166 filmes e 0,2 s por consulta:
34 s uma de cada vez → **6 s** em paralelo; pré-visualizar de novo ou Organizar logo depois:
**0,3 s** (nenhuma consulta repetida). Nomes de episódios: **um pedido por temporada**, não um por
episódio. Se a chave for recusada ou não houver internet, o programa para de insistir após a
primeira falha (antes esperava o tempo limite em cada filme).

### Como a janela moderna é organizada (para quem quer mexer)

- `videoscraper/gui_moderna.py`: **só a aparência** (`JanelaModerna`). Cores e fontes ficam na
  classe `Tema`. Os cliques chamam métodos *placeholder* (`ao_buscar`, `ao_baixar_todos`...) que
  ali só têm `pass`. Para ver só o visual: `python -m videoscraper.gui_moderna`.
- `videoscraper/app_moderna.py`: `AppModerna` **herda** a janela e preenche os placeholders com o
  motor (busca e download em thread, comunicação pela fila).

### Espelhar no Jellyfin (.strm), sem baixar

Na aba **Vídeos**, a tabela mostra o **Tipo** de cada link (Filme, Série ou "—") e a **Licença**
informada pelo site (no archive.org: "Domínio público", "CC BY 4.0"...; "—" = não informada).
O botão **Espelhar no Jellyfin (.strm)...** (nos selecionados; sem seleção, em todos). Para escolher, use
**Selecionar todos**, **Só filmes e séries** (o que dá para espelhar) ou **Limpar seleção**, no topo da lista,
ou Ctrl+clique / Shift+clique / Ctrl+A; o topo mostra "3 de 273 selecionado(s)":

1. separa filmes (título com ano) de episódios (S01E02, 1x02...); o que não tem nenhum dos dois fica de fora;
2. cria um arquivo `.strm` com o link, com o mesmo nome que o organizador daria (catálogo/TMDB):
   `Filmes/Nome (Ano)/Nome (Ano).strm` e `Séries/Nome (Ano)/Season 01/Nome S01E02.strm`, nas
   bibliotecas escolhidas na aba Jellyfin. O Jellyfin trata o `.strm` como o vídeo e **toca direto
   do link**, sem ocupar espaço;
3. depois, o mesmo pós-processamento do Organizar: **legendas** (com o mesmo nome do `.strm`, nos
   idiomas e fontes escolhidos, inclusive OpenSubtitles + SubDL), pôster/backdrop/`.nfo` e o scan.

**Consulta ao Jellyfin:** com o endereço e a chave do servidor preenchidos, o espelho pergunta ao
Jellyfin o que ele já tem (filmes, séries e episódios) e pula o que já está lá — pelo id do TMDB ou
pelo nome + ano / série + temporada + episódio, mesmo que a pasta tenha outro nome.

**Outros sites** (não só o archive.org): o espelho aceita qualquer link da aba Vídeos, mas antes
**confere cada um** (8 ao mesmo tempo, pedindo só o 1º byte do arquivo). Um `.strm` só serve se o link for:
- **direto**: o arquivo do vídeo, não a página (página → pulado);
- **permanente**: links "assinados" (`?Expires=`, `token=`, `Signature=`...) expiram em horas (→ pulado);
- **público**: se o site pede login (HTTP 401/403), o Jellyfin não tem o seu acesso (→ pulado);
- e o `robots.txt` do site precisa permitir.
Também avisa (mas cria) quando o servidor não deixa avançar o vídeo ou demora mais de 3 s, e
mostra o tempo médio de resposta. **Estabilidade:** com `.strm`, o vídeo vem do servidor do site a
cada play: a fluidez depende dele e da sua internet, e se o site tirar o arquivo do ar, o item para
de tocar. Para o que você quer guardar de vez, baixar continua sendo o mais estável.

Nada é sobrescrito: um link que já tem `.strm`, ou um filme que já está baixado na biblioteca, é
pulado.

**Onde os arquivos ficam (não precisa anexar nada no Jellyfin):** o programa grava os `.strm` (e as
legendas, `poster.jpg`, `backdrop.jpg`, `.nfo`) direto nas pastas das bibliotecas escolhidas na aba
Jellyfin, que devem ser as MESMAS cadastradas no Jellyfin (Painel → Bibliotecas → Pastas). Se a série
ou o filme já existe, o item novo entra na mesma pasta e aparece junto. Com o endereço e a chave do
servidor preenchidos e "Atualizar a biblioteca no fim (scan)" marcado, o Jellyfin é avisado na hora;
sem isso, ele acha os arquivos no próximo scan automático (ou clique em "Escanear biblioteca").
O Jellyfin completa as capas de séries/episódios e, com "Coleções automáticas" ligado na biblioteca,
junta os filmes nas coleções do TMDB (ex.: "Matrix: Coleção"). O servidor do Jellyfin precisa de
internet para tocar os `.strm`. **Completar biblioteca** também enxerga os `.strm` (para baixar legendas que faltaram).
Muitos itens enviados por usuários (ex.: "DVDISO", "Dual Audio") não têm autorização do dono dos
direitos: a primeira opção do botão espelha **só domínio público / Creative Commons**.

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

### Páginas com centenas de resultados

- **archive.org:** links de coleção (`https://archive.org/details/Comedy_Films`), de busca
  (`https://archive.org/search?query=...`) ou de um item são lidos pela **API oficial** do
  archive.org: o programa lista todos os itens (não só os que aparecem na tela) e escolhe o melhor
  arquivo de vídeo de cada um. "Máx. de páginas" vira "máximo de itens" (até 100.000). Confira a
  licença de cada item.
- **Outros sites:** com "Seguir links" ≥ 1, o programa visita primeiro os links que se repetem no
  mesmo formato (os resultados, como `/filme/123`, `/filme/456`) e deixa por último os links únicos
  do menu (`/sobre`, `/contato`). Para mandar explicitamente, use **"Seguir só links que contêm"**
  (ex.: `/details/`) ou `--filtro-links` no terminal.

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
  gui_moderna.py janela moderna, só a aparência (CustomTkinter, Dark Mode)
  app_moderna.py liga o motor à janela moderna (preenche os placeholders)
  gui.py        janela clássica (Tkinter cinza)
  cli.py        comandos links / baixar / login
  menu.py       menu de texto (python iniciar.py --texto)
jellyfin_tools/
  nomes.py       lê nomes bagunçados e monta "Nome (Ano)"
  catalogo.py    confirma título/ano (JSON local ou API do TMDB)
  organizador.py move/renomeia no padrão do Jellyfin, com simulação e desfazer
  legendas.py    busca/baixa legendas (site HTML ou API do OpenSubtitles)
  site_demo.py   site de legendas simulado, para demonstração e testes
  metadados.py   pôster/backdrop pt-BR e .nfo pela API do TMDB
  servidor_jellyfin.py  scan da biblioteca (POST /Library/Refresh)
  notificacoes.py       avisos no Discord/Telegram
  registro.py           log em arquivo (logging)
organizar_jellyfin.py  script completo, com as configurações no topo
exemplo_jellyfin.py  como integrar no seu arquivo principal
tests/          testes com servidores locais (sem internet)
```

## Script completo: `organizar_jellyfin.py`

Um arquivo só, com **as configurações no topo**, que faz tudo em sequência:

| Etapa | O que faz |
|---|---|
| Organização | Limpa nomes de torrent e cria `Filmes/Nome (Ano)/Nome (Ano).ext` |
| Legendas e artes locais | `.pt-BR.srt`, `.pt-BR.forced.srt`, `poster.jpg`, `backdrop.jpg`, `landscape.jpg`, `logo.png` |
| Limpeza | Apaga `.url`, `.txt` de propaganda e trailers < 100 MB (com as travas de segurança) |
| Legenda faltante | OpenSubtitles (API) e/ou um site de busca (`SITE_LEGENDAS_URL`) |
| **Scan do Jellyfin** | `POST /Library/Refresh` uma vez no fim do lote (`JELLYFIN_URL`, `JELLYFIN_API_KEY`) |
| **Nomes pelo TMDB** | O TMDB vem primeiro (o catálogo local fica de reserva); séries ganham o nome do episódio (`NOMES_EPISODIOS`) |
| **Pôster e backdrop pt-BR** | Pela API do TMDB, só se o torrent não trouxe imagens |
| **Arquivo .nfo** | `Nome (Ano).nfo` com título, ano, sinopse em português, duração, gêneros e IDs |
| **Log e avisos** | `jellyfin_organizer.log` + Discord (webhook) e/ou Telegram (bot) |

```bash
python organizar_jellyfin.py                         # SIMULAÇÃO: só mostra e registra no log
python organizar_jellyfin.py --aplicar               # de verdade
python organizar_jellyfin.py --completar-biblioteca  # filmes JÁ organizados: baixa só o que falta
python organizar_jellyfin.py --relatorio             # o que falta: legendas, pôsteres, episódios
python organizar_jellyfin.py --conferir-espelhos     # confere os .strm agora (avisa se quebrou)
python organizar_jellyfin.py --espelhos              # lista os espelhamentos (1, 2, 3...)
python organizar_jellyfin.py --remover-espelhos 1 --aplicar   # tira o 1º espelhamento (ou um nome)
python organizar_jellyfin.py --vigiar                # vigia as pastas (+ espelhos em CONFERIR_ESPELHOS_A_CADA)
```

**Chaves e tokens:** em vez de escrevê-los no arquivo, crie variáveis de ambiente com o mesmo nome
(ex.: no Windows, `setx TMDB_API_KEY "sua-chave"`). A variável de ambiente vence o valor do topo,
e assim seus segredos não vão parar no GitHub.

- **TMDB:** chave gratuita em <https://www.themoviedb.org/settings/api>. Usamos a API oficial (não
  raspagem do site, que os termos proíbem). Imagens que vieram no torrent têm prioridade.
- **Jellyfin:** Painel → Avançado → Chaves de API. O scan roda **uma vez no fim do lote**:
  `/Library/Refresh` varre a biblioteca inteira, então um scan por filme seria desperdício.
- **Para o .nfo ser lido:** na biblioteca do Jellyfin, deixe "Nfo" marcado em "Leitores de metadados".
- **Discord:** canal → Editar → Integrações → Webhooks. **Telegram:** crie o bot com @BotFather.
  Com mais de `NOTIFICAR_CADA_FILME_ATE` filmes no lote, o resto vai num aviso de resumo.
- **Robustez:** cada filme é processado num `try/except` próprio; um erro (TMDB fora do ar, legenda
  não encontrada) vai para o log e o próximo filme segue.

## Jellyfin: organizar filmes e baixar legendas (`jellyfin_tools`)

Pacote separado para a biblioteca do Jellyfin.

**Parte 1, organizador:** lê nomes bagunçados, confirma título e ano num catálogo e move para o
padrão do Jellyfin.

| Arquivo bagunçado | Vira |
|---|---|
| `Matrix.1999.1080p.BluRay.x264-VERSAO.mp4` | `Filmes/Matrix (1999)/Matrix (1999).mp4` |
| `interestellar_filme_completo_dublado_2014.mkv` | `Filmes/Interestelar (2014)/Interestelar (2014).mkv` |
| `O.Poderoso.Chefao.1972.Bluray.mkv` | `Filmes/O Poderoso Chefão (1972)/O Poderoso Chefão (1972).mkv` |

Os nomes usam o **título brasileiro** (como o Jellyfin mostra com o idioma em português).

**Parte 2, legendas:** busca a legenda pt-BR e salva ao lado do vídeo com o mesmo nome:
`Matrix (1999).pt-BR.srt` (sempre em UTF-8; aceita `.srt`, `.zip` e codificação antiga do Windows).
Se o site de legendas não achar pelo título brasileiro, tenta o original (Interestelar → Interstellar).

### Torrents: legendas locais, imagens e lixo

Junto com o vídeo, o organizador cuida do que vem na pasta do torrent:

| Arquivo na origem | Vira |
|---|---|
| `Creed.II.FORCED.srt` | `Creed II (2018).pt-BR.forced.srt` |
| `Creed.II.ENG.srt` | `Creed II (2018).en.srt` |
| `Creed.II-poster.jpg`, `-backdrop.jpg`, `-landscape.jpg`, `-logo.png` | `poster.jpg`, `backdrop.jpg`, `landscape.jpg`, `logo.png` |
| `BLUDV.TV.url`, `Leia.txt`, trailer pequeno (< 100 MB) | **apagados** (só ao aplicar; dá para desligar) |

Prefixos de site no nome (`[WWW.SITE.TV] Creed II 2018`) e etiquetas como `6CH`, `DUAL`,
`NACIONAL` e `5.1` são ignorados. Se o filme ficar sem legenda completa (uma forced não conta),
o programa busca a pt-BR.

**Travas de segurança para apagar:** numa pasta só do torrent, apaga todo `.url`/`.txt` e os
trailers. Na pasta raiz (ex.: `Downloads` com vários filmes soltos), só apaga o que tem cara de
propaganda (nome com site, "Leia", "Visite", "trailer"...). Um vídeo pequeno só é trailer se
houver um vídeo maior na mesma pasta, e nunca no modo séries. A pré-visualização lista tudo o
que seria apagado, e apagar não tem desfazer.

```bash
python -m jellyfin_tools demo-torrent      # os dois exemplos: Creed II e Velhos Bandidos
```

No seu código, use `organizar_e_legendar(origem, biblioteca, catalogo, provedores, aplicar=True)`
(veja `exemplo_jellyfin.py`).

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
  Com o TMDB ligado, ele é consultado **primeiro** e o catálogo local fica de reserva (sem internet).
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
