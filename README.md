<img src="docs/maestro.png" width="96" align="left" alt="ícone do Maestro">

# Maestro (antigo videoscraper)

**Biblioteca do Jellyfin, TV ao vivo e downloads, regidos num lugar só.** O nome técnico continua
`videoscraper` (o `.exe`, a pasta `.videoscraper` e o `videoscraper-windows.zip`), para as atualizações
automáticas seguirem funcionando nas instalações que já existem (desde a v2.1.0 o programa que você abre é o
`Maestro.exe`; o `videoscraper.exe` fica escondido, só para a compatibilidade).

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

### Novidades da v2.12.0

- **Criar legenda pelo áudio** (aba Jellyfin > Legendas): para os vídeos **sem nenhuma legenda**, o
  **Whisper** (código aberto, roda no seu PC, grátis) ouve o áudio e escreve as falas com os horários
  (`Nome.en.srt`, no idioma do áudio); se o áudio não é português, o **Claude** traduz para `Nome.pt-BR.srt`.
  Áudio já em português sai direto, sem gastar com a API. Escolha o modelo do Whisper (`tiny` ... `large-v3`,
  padrão `small`) e, se tiver, a placa de vídeo NVIDIA (bem mais rápido). Na 1ª vez ele baixa o modelo.
- **Dublar filmes (voz sintética)**: a legenda em português é lida por uma voz do **Piper** (roda no PC, grátis;
  vozes genéricas, nunca a voz de atores) e o ffmpeg grava **`Nome - Dublado IA.mkv`**: o vídeo copiado sem perder
  qualidade, a faixa dublada como a 1ª (padrão) e o áudio original preservado. Estilo narração de documentário:
  a voz original fica mais baixa enquanto a dublada fala, e a boca dos atores não acompanha. O arquivo original
  não é tocado; no Jellyfin aparecem as duas **versões** do filme. Só filmes, por enquanto.
- **Sincronizar legendas**: compara onde há voz no áudio com onde há fala na legenda e corrige as adiantadas ou
  atrasadas (a original fica como `Nome.srt.original`). Quando o encaixe não é claro, nada é mudado.
- **Tradução econômica (em lote)**: no "Traduzir legendas com IA", a opção **"Econômico"** custa **metade** do
  preço e fica pronta em até 24 h (quase sempre menos de 1 h). Pode fechar o Maestro: ele busca o resultado
  sozinho depois (o painel de saúde mostra "Tradução em lote: N aguardando").
- **Revisão da legenda traduzida**: no máximo 42 letras por linha (o padrão de legendagem), em 2 linhas
  equilibradas; diálogos ("- Oi." / "- Olá.") ficam como estão.
- **Agendar tarefas**: escolha na janela o que o Maestro faz sozinho (organizar, conferir canais, traduzir,
  legendar, dublar, sincronizar...) e quando; vai para o **Agendador de Tarefas do Windows** (pasta "Maestro").
- **Resumo do dia** no Discord/Telegram, às 21h: o que foi baixado, organizado, traduzido, dublado, e o que
  quebrou. Dia parado não gera mensagem.
- **Exportar/importar configurações** (.zip, com ou sem as chaves de API), para levar o Maestro para outro
  computador; antes de importar, as atuais ficam guardadas em `backups`.
- **Baixar todos com vídeos selecionados** agora pergunta: só os selecionados ou todos? A situação "baixado"
  marca só a linha do vídeo baixado, e o log mostra quais foram escolhidos.
- **Download por streaming**: em vez de "ffmpeg falhou: sem detalhes", explica o que houve e o que fazer.
- Comandos de robô novos: `--legendar-audio`, `--dublar`, `--sincronizar-legendas` (com `--limite-videos`,
  padrão 5 por execução) e `--traduzir-legendas --economico`.
- O `.exe` testa no GitHub, a cada versão, a ida e volta do áudio: o Piper **fala** uma frase em português e o
  Whisper **ouve** e confere.

### Novidades da v2.11.0

- **Traduzir legendas com IA** (aba Jellyfin, seção Legendas, botão **"Traduzir legendas com IA..."**): acha nas
  bibliotecas os vídeos que só têm legenda `.srt` em outro idioma (inglês tem preferência) e nenhuma em
  português, mostra quantos são e o **custo estimado**, e, se você confirmar, cria `Nome.pt-BR.srt` com os
  **mesmos horários**. Usa a API da Anthropic (Claude), com o modelo padrão **`claude-sonnet-4-6`** (dá para
  trocar no campo "Modelo"). Crie a chave em console.anthropic.com > API Keys; o uso é pago por quantidade de
  texto (um filme costuma custar centavos de dólar).
  - A IA recebe **só o texto das falas**, numeradas; os horários nunca saem do seu computador. Cada fala volta
    com o mesmo número, e o Maestro confere: fala esquecida é pedida de novo, resposta longa demais é dividida.
  - A legenda original continua lá e **nada é sobrescrito**. No fim, o Jellyfin é avisado para atualizar.
- **Coletor de programação no painel de saúde:** a linha "Programação" mostra se o coletor (iptv-org/epg no
  Docker) está rodando e quantos programas tem no guia. Se ele **parar**, o Maestro avisa no Discord/Telegram
  (uma vez, quando para; não fica repetindo).
- **Coluna "Agora passando"** na TV ao vivo: o programa de agora, até que horas vai e o próximo
  ("Jornal (até 20:30) → Novela"), lidos do guia do coletor. Atualiza sozinha a cada 10 minutos. A tabela
  ganhou barra de rolagem para os lados.
- **Comandos para robôs (RPA)**: UiPath, BotCity ou o Agendador de Tarefas do Windows podem rodar as tarefas do
  Maestro **sem abrir a janela**:

  | Comando | O que faz |
  |---|---|
  | `Maestro.exe --organizar` | organiza o que **terminou de baixar** (filmes → Filmes, episódios → Séries), com legendas, pôster, `.nfo` e scan do Jellyfin. `--simular` só mostra o que faria |
  | `Maestro.exe --conferir-espelhos` | confere os links dos `.strm` e avisa no Discord/Telegram se algum quebrou |
  | `Maestro.exe --conferir-canais` | confere os canais da TV ao vivo e avisa se algum saiu do ar |
  | `Maestro.exe --enviar-tv` | envia a lista de canais ao Jellyfin (o mesmo "Salvar e enviar") |
  | `Maestro.exe --traduzir-legendas` | traduz as legendas que faltam, até `--limite-dolares` (padrão 1.00; 0 = sem limite) |

  Usam as **mesmas configurações da janela** e só as leem. Dá para juntar vários
  (`Maestro.exe --organizar --traduzir-legendas`). O robô sabe o que aconteceu pelo **código de saída**:
  **0** tudo certo · **1** terminou, mas achou problema (link quebrado, canal fora do ar, erro ao mover) ·
  **2** falta configuração (pasta, chave, lista vazia): nada foi feito · **3** erro inesperado. O resumo fica em
  `C:\Users\<você>\.videoscraper\rpa\ultimo.json` (ou onde você pedir com `--resultado arquivo.json`), e o
  log completo em `.videoscraper\logs\` (o mesmo do botão "Abrir log"). Chaves não lembradas ("Lembrar as
  chaves" desmarcado) vêm das variáveis de ambiente (`TMDB_API_KEY`, `ANTHROPIC_API_KEY`, `JELLYFIN_API_KEY`...).

  No Prompt de Comando, use `start /wait Maestro.exe --conferir-canais` e depois `echo %ERRORLEVEL%`; no
  PowerShell, `(Start-Process Maestro.exe --conferir-canais -Wait -PassThru).ExitCode`.
- **Testes no GitHub:** a cada envio, os mais de 400 testes automáticos rodam sozinhos no GitHub (Actions >
  "Testes"); um ✕ vermelho ao lado do commit mostra qual quebrou antes de virar versão. O `.exe` também
  ganhou um autoteste dos comandos de robô.

### Novidades da v2.10.0

- **Espelhar: links temporários com confirmação.** Links com assinatura que expira (`?expires=`, `?token=`,
  `?signature=`...) antes ficavam sempre de fora ("Link que não serve para .strm"). Agora o Maestro mostra
  quantos são, explica que o `.strm` toca só até a assinatura expirar, e pergunta, como na escolha da licença:
  - **"Criar nesta vez"**: só neste espelhamento; pergunta de novo na próxima;
  - **"Sempre criar (até fechar o Maestro)"**: confirmação geral;
  - **"Deixar de fora"**: como antes.

  Os aceitos ainda passam pela conferência normal (é vídeo? é público?) e saem com o aviso "link temporário".
  No **Conferir espelhos**, um temporário só aparece como quebrado quando de fato parar de tocar.

### Novidades da v2.9.0

- **Separação por tipo (Filmes, Séries, Esportes, Notícias, Infantil) mais certeira:**
  - O Jellyfin decide o tipo de cada programa comparando as categorias do guia com listas de palavras que,
    de fábrica, só têm inglês ("movie", "sports"...). Os guias brasileiros (mi.tv, meuguia.tv) mandam
    "Filme", "Esporte", "Infantil"..., e nada caía em tipo nenhum. Agora cada guia é cadastrado com as
    palavras em **português** (e espanhol) também, somadas às de fábrica.
  - **"Tipos..."** (botão novo na TV ao vivo): o Jellyfin e os aplicativos (Moonfin...) só têm esses **5
    tipos**, e não dá para criar outros, como "Entertainment". Nessa janela você escolhe em qual dos 5 cada
    Grupo entra (por exemplo **Entertainment → Séries**), ou nenhum. Vale no próximo "Salvar e enviar".
- **Envio com andamento em %:** o rodapé mostra o passo e a porcentagem: "1/5 Salvando a lista...", "2/5
  Cadastrando a lista...", "3/5 Cadastrando os guias...", "4/5 Jellyfin atualizando o guia: 37%", "5/5
  Conferindo...". A espera pela atualização do guia vai até 10 minutos (o "Parar" interrompe).
- **Relatório do envio mais preciso:** quantos canais ficaram em cada tipo pelo Grupo, quais grupos ficaram sem
  tipo, e quantos **programas de cada tipo** o Jellyfin tem de fato no guia depois do envio. Esses números são
  o que os aplicativos usam para separar.
- "Numerar em ordem..." agora se chama **"Numerar..."** (mesma função; abre espaço para "Tipos...").

### Novidades da v2.8.0

- **TV ao vivo: coluna "Programação"** (com filtro e na exportação). Mostra, canal por canal:
  - **"✓ 48 programas · mi.tv"**: o guia do coletor já tem a grade desse canal;
  - **"aguardando coleta · mi.tv"**: o canal está na lista do coletor, mas a grade ainda não chegou;
  - **"sem programas · meuguia.tv"**: o guia chegou, mas o site não trouxe nada para esse canal;
  - **"só categoria"**: nenhum site de guia tem esse canal, então ele fica com o guia de categorias.

  A coluna se atualiza sozinha ao abrir a janela e depois de ligar o coletor.
- **"Conferir programação"** (ao lado de "Programação dos canais..."): confere, em ordem, o que funciona e o que
  falta. (1) O container `maestro-guia` está rodando no Docker? (2) O guia em `http://localhost:3000/guide.xml`
  já responde, com quantos canais e programas? (3) Quantos dos seus canais têm grade? (4) O guia está no campo
  e cadastrado no Jellyfin? Cada item que falta vem com o que fazer.

### Novidades da v2.7.0

- **Modo híbrido: "Espelhar em vez de baixar"** (aba Vídeos, em Opções). Marcada, os botões viram **"Espelhar
  selecionados"** e **"Espelhar todos"** e criam os `.strm` no Jellyfin, com o mesmo fluxo do "Espelhar no Jellyfin
  (.strm)...": Filmes, Séries, vídeos comuns, licença, conferência dos links e Desfazer. Desmarcada, os botões
  voltam a **baixar** os arquivos como sempre. Com filtro nas colunas, "todos" são só os que estão à vista. Os
  links de plataformas como o YouTube continuam fora, porque são páginas e não arquivos.
- **"Clicar no play sozinho"** (Opções, marcada por padrão): liga ou desliga o clique automático no poster/play
  da v2.5.0 quando "Usar navegador" está marcado.

### Novidades da v2.6.0

- **Espelhar no Jellyfin: vídeos comuns, além de Filmes e Séries.** Links sem ano nem temporada/episódio (aulas,
  clipes, vídeos pessoais...) não ficam mais só "de fora". O Maestro pergunta onde guardá-los:
  - **"Usar esta pasta"** (a de sempre), **"Escolher outra pasta..."** ou, na primeira vez, **"Escolher a
    pasta..."**: a pasta escolhida fica lembrada;
  - **"Deixar de fora"**: como antes.

  Cada um vira `<pasta>/<Título do link>.strm`. Se dois vídeos têm o mesmo título, o segundo vira
  `Título (2).strm`. No Jellyfin, a pasta deve ser uma biblioteca do tipo **"Vídeos caseiros e fotos"** (ou
  "Conteúdo misto"). Os vídeos comuns entram no **Conferir espelhos**, na janela **Espelhos...** e no
  **Desfazer última**, que agora desfaz o espelhamento inteiro, em todas as pastas onde ele criou arquivos.
  Legendas, pôster e .nfo continuam só para filmes e episódios (o TMDB não conhece um vídeo comum).

### Novidades da v2.5.0

- **Modo navegador: vídeos que só carregam com um clique.** Muitos players mostram só o poster e criam ou
  carregam o vídeo quando alguém clica no "play". Agora, depois de abrir a página, o Maestro dá um **clique
  de mouse de verdade no centro** de cada `<video>` que ainda só tem o poster e dos botões de play conhecidos
  (Video.js, Plyr, JW Player, MediaElement, Flowplayer, `aria-label="Play"`...). Depois de cada clique ele
  **espera até 5 s**, checando a cada 0,25 s, a mídia mudar de estado (metadados, começou a baixar, buffer) ou
  chegar pela rede, e só então lê a página.
  - **Travas:** não clica em links (sairia da página; os links o rastreador já segue), nem em players de
    outros sites (iframes); fecha janelas de anúncio abertas pelo clique; para o vídeo depois; no máximo 8
    cliques por página; vídeo com proteção contra cópia (DRM) não entra na lista; e endereços de YouTube,
    Instagram, TikTok e outras plataformas protegidas nunca são capturados.

### Novidades da v2.4.0

- **Busca de vídeos: opção "Ignorar o robots.txt"** (aba Vídeos, em Opções), para testar sites seus ou com
  autorização do dono. Com ela marcada, cada busca ou download **pergunta antes de começar**, como na escolha
  "domínio público ou todos":
  - **"Ignorar nesta vez"**: só aquela busca/download; a próxima pergunta de novo;
  - **"Ignorar sempre (até fechar o Maestro)"**: confirmação geral, em qualquer site, sem perguntar de novo até
    fechar o programa ou desmarcar a opção;
  - **"Respeitar o robots.txt"**: segue as regras do site; **Cancelar**: não faz nada.
- **Sem a opção marcada**, se o robots.txt bloquear a página o Maestro pergunta no fim se o site é seu: com
  **"Sim, o site é meu"**, busca de novo ignorando o robots.txt só daquele site (até fechar o programa).
- Em todos os casos as pausas entre os pedidos continuam, e plataformas como YouTube, Instagram, TikTok,
  Facebook, Netflix e Vimeo **nunca** têm o robots.txt ignorado (nem com `--ignorar-robots` na linha de comando).
- **Pedidos mais espaçados e com pausas (mais estável e mais gentil com o site):** o campo vira **"Espera
  média (s)"** entre pedidos (padrão **5 s**) e cada espera é sorteada entre 60% e 140% dela (`random.uniform`:
  com 5 s, de **3 a 7 s**). A cada **20 pedidos**, uma **pausa preventiva** maior, sorteada entre 6 e 12 vezes
  a espera (com 5 s, de **30 a 60 s**). O "Parar" interrompe as pausas na hora. As novas tentativas continuam
  como antes: em erro de rede, timeout ou HTTP 429/5xx, espera 2 s, depois 4 s... (dobrando) antes de desistir.

### Novidades da v2.3.2

- **Corrigido: atualização pela metade.** Com outra janela do Maestro aberta (por exemplo, a da bandeja, do
  "Iniciar com o Windows"), o Windows não deixava trocar o `Maestro.exe`: só a pasta `_internal` mudava. O
  programa dizia "versão nova", mas as telas continuavam as antigas. Agora a atualização espera essas janelas
  fecharem (até 30 s) e fecha as que sobrarem antes de trocar os arquivos. E se o `.exe` e a `_internal`
  discordarem, o Maestro mostra a versão mais antiga das duas e oferece a atualização de novo.

### Novidades da v2.3.1

- Corrigido: na TV ao vivo, o texto do botão "Remover selecionados" ficava cortado depois que o botão
  "Editar..." entrou na mesma linha.

### Novidades da v2.3.0

- **Programação de verdade dos canais (o que passa ao longo do dia).** Botão **"Programação dos canais..."** na
  TV ao vivo: o Maestro baixa o mapa da [iptv-org](https://github.com/iptv-org/epg) (que canal tem grade em qual
  site de guia de TV: mi.tv, meuguia.tv...), acha os canais da SUA lista e grava o `channels.xml` ao lado do
  `canais.m3u`. Depois liga o **coletor** (o programa da iptv-org que busca a grade) no Docker:
  `http://localhost:3000/guide.xml` entra sozinho no campo do guia, como o primeiro.
  - **Automático:** o coletor busca a grade ao ligar e todo dia às 06:00 (UTC), e volta sozinho sempre que o
    Docker Desktop abre. O Jellyfin relê o guia na atualização diária dele.
  - **Canais novos:** a cada "Salvar e enviar ao Jellyfin" o `channels.xml` é refeito com a lista atual; eles
    entram na próxima coleta. Os canais sem grade em nenhum site ficam com o guia de categorias.
  - Um guia que ainda não responde (ex.: o coletor na 1ª coleta) não é cadastrado naquele envio, para não
    atrapalhar a limpeza dos canais antigos no Jellyfin; entra no envio seguinte.
- **Editar canais pela tela da TV ao vivo:** botão **"Editar..."** (ou F2), com os canais selecionados. Um canal: corrige nome,
  número, grupo, link do sinal, logo, ID do guia e idioma. Vários canais: muda o **Grupo** e/ou o **Idioma** de
  todos de uma vez (campo vazio = fica como está em cada um). O duplo clique continua editando um canal.

### Novidades da v2.2.0

- **TV ao vivo: categorias no Jellyfin (Filmes, Esportes, Notícias, Infantil, Séries).** O Jellyfin lê o Grupo
  da lista mas não usa: as categorias que os aplicativos (Moonfin, TV, celular) mostram vêm só do guia de
  programação. Agora o Maestro gera um **guia de categorias** (`guia_categorias.xml`, junto da lista) com a
  categoria tirada do Grupo de cada canal ("Sports" -> Esportes, "Movies" -> Filmes, "News" -> Notícias,
  "Kids"/"Desenhos" -> Infantil, "Séries" -> Séries) e o cadastra sozinho no "Salvar e enviar". Grupos sem
  categoria no Jellyfin (ex.: "Religious") entram como gênero.
- **Vários guias de programação:** o campo aceita mais de um (separe com `;`). Para cada canal o Jellyfin usa o
  primeiro guia que tem a programação dele; o de categorias fica sempre por último, só para os que faltam.
- **Idioma dos canais:** nova coluna **Idioma** (com filtro), lida do `tvg-language` da lista ou deduzida pelo
  país do `tvg-id` (`.br` -> Português), pelo nome ("Brazil", "Latin America") ou pelo link (`.br`, `.pt`).
  Dá para corrigir no duplo clique. **"Numerar em ordem..." -> "Por idioma e grupo"**: cada idioma ganha uma
  faixa (Português 1-99, English 101-199...), e os canais aparecem separados por idioma em qualquer aplicativo
  (o Jellyfin não tem categoria de idioma). O idioma também vai no guia.
- **"Atualizar a biblioteca agora" confere de verdade:** acompanha a tarefa "Escanear biblioteca" do Jellyfin
  até o fim (com a porcentagem) e mostra o que mudou: "concluído em 2 min: +3 filme(s), +12 episódio(s)", ou o
  erro, se o scan falhar.

### Novidades da v2.1.1

- **Escolher no TMDB, mais esperto:**
  - **Procurar outro nome** na própria lista: "Juni Lee" não acha nada? Digite "Juniper Lee" e clique em
    Procurar, sem fechar.
  - **Vincula todos os arquivos com o mesmo nome** da prévia de uma vez (não só o selecionado), em
    qualquer pasta. A escolha vale para a pasta da série inteira; numa pasta com séries misturadas (ou na
    própria pasta de origem), vale só para aqueles arquivos.
- **Corrigido: "Tom and Jerry EP37 Professor Tom (1948)" ia para "Tom e Jerry na Singapura (2023)".** Quando
  nenhuma série com esse nome existia no ano do episódio (no TMDB, os curtas clássicos não estão como série),
  o programa caía na mais popular de hoje. Agora fica o nome do arquivo ("Tom and Jerry S01E37 - Professor
  Tom"), marcado **"vai mover (confira)"**, e nunca uma série que estreou décadas depois.
- **Depois de "Escolher no TMDB" ou "Corrigir nome", só os arquivos afetados são analisados de novo** (antes,
  a prévia inteira era refeita: com 700 arquivos e o TMDB, minutos). O Organizar continua conferindo tudo na
  hora de mover.

### Novidades da v2.1.0

- **O programa agora é o `Maestro.exe`**, com o ícone. Os atalhos "Maestro" e o "Iniciar com o Windows"
  apontam para ele. O `videoscraper.exe` continua na pasta só para as versões antigas conseguirem se
  atualizar (elas procuram esse nome), e fica **escondido**: na pasta você vê o Maestro.
- A pasta do programa continua `AppData\Local\Programs\videoscraper` (mudar a pasta de lugar exigiria
  mover o programa enquanto ele roda; fica para uma próxima etapa, com cuidado).

### Novidades da v2.0.2

- **Corrigido: "Acesso negado" em `C:\Windows\system32\videos_baixados` ao baixar.** Aberto pelo "Iniciar
  com o Windows", a pasta atual do programa é a do sistema, e a pasta padrão dos vídeos era calculada a partir
  dela. Agora a pasta padrão é fixa: a `videos_baixados` ao lado do programa (se já existe) ou
  **Vídeos\Maestro**. Um caminho dentro da pasta do Windows é trocado sozinho pelo padrão.
- A pasta dos vídeos que você escolher fica **lembrada** entre uma abertura e outra.

### Novidades da v2.0.1

- Depois de refazer os atalhos, o programa **avisa o Windows que os ícones mudaram** (o mesmo aviso que os
  instaladores dão): a Área de Trabalho e o Menu Iniciar mostram o ícone do Maestro sem esperar reiniciar.
  Ele **não apaga** o cache de ícones (apagar com o Windows aberto deixa os ícones de todos os programas em
  branco até reiniciar).

### Novidades da v2.0.0: agora é **Maestro**

- **Nome e ícone novos:** o "M" cuja perna vira a batuta do maestro, com a ponta verde (o "no ar" da TV ao
  vivo), em roxo vivo. Aparece no topo do programa, na barra de título e de tarefas, em todas as janelas, no
  ícone perto do relógio e no próprio `.exe`.
- **Atalho "Maestro"** na Área de Trabalho e no Menu Iniciar; o atalho antigo "videoscraper" é tirado sozinho
  na primeira vez que a versão nova abre (para não ficarem dois).
- **Nada se perde:** configurações, chaves, canais, regras, histórico e a memória de downloads continuam na
  mesma pasta (`.videoscraper`), e o "Iniciar com o Windows" segue funcionando.

### Novidades da v1.9.4

- **Memória dos downloads (aba Vídeos):** cada vídeo baixado fica guardado em `.videoscraper\baixados.json`.
  Numa busca nova (hoje ou daqui a meses), ele aparece como **"já baixado (data)"** e o "Baixar" pergunta se
  pula os já baixados. Sites que mudam o link a cada visita são reconhecidos pela página + título.
- **"Memória de downloads..."** (embaixo da lista): esquecer os selecionados ou **limpar por período**
  (mais de 30 dias, 90 dias, 1 ano ou tudo), mostrando quantos registros e o tamanho do arquivo. Só esquece:
  os vídeos no disco não mudam.
- **Filtro em cada coluna da lista de vídeos** (Situação, Título, Tipo, Licença, Origem, Link), como na TV ao
  vivo: clique no título, digite ou marque. Com filtro, **"Baixar todos" baixa só o que está à vista**; botão
  "Tirar os filtros" no topo.
- **Pasta vigiada respeita os desmarcados (☐):** o que você desmarcou na prévia a vigia também não mexe.

### Novidades da v1.9.3

- **Diagnóstico da TV com resumo:** começa com **"✓ Tudo certo: 144 canais (os da sua lista)"** ou
  **"⚠ Atenção: ..."** (canais a mais ou plugin de TV ativo). A explicação longa só aparece quando há problema.
- **TV no painel de saúde** (topo da aba Jellyfin): "✓ TV: 144 canais", conferido em segundo plano a cada
  30 minutos. Fica laranja se o Jellyfin voltar a ter canais a mais, se aparecer um plugin de TV ativo ou se
  houver canais que sempre falham.
- **Escolher no TMDB...** (ao lado de "Corrigir nome..."): quando há vários com o mesmo nome (ex.: "Tom and
  Jerry" de 1940, 2014 e 2023), lista as opções com ano, nome original e resumo; a escolhida fica guardada como
  regra para aquela pasta e a prévia roda de novo.
- **Os desmarcados (☐) continuam desmarcados** ao pré-visualizar de novo (e ao trocar de modo ou abrir o
  Relatório no meio), enquanto o programa estiver aberto. Marcou de novo (☑): o programa esquece.
- **Conferir sozinho toda semana** (janela TV ao vivo, embaixo): confere todos os canais 1x por semana, em
  segundo plano e devagar ("Leve", prioridade baixa). Os que falharam em **todas** as últimas conferências
  aparecem no painel de saúde, no Discord/Telegram (se configurados) e numa pergunta que abre a lista já com
  eles selecionados, para você decidir se remove.

### Novidades da v1.9.2

- **TV ao vivo, os 11.129 canais que não saíam:** o diagnóstico agora lista os **plugins de TV ao vivo**
  (ex.: NextPVR, TVHeadend). Se um deles está instalado mas sem servidor, a atualização do guia dá erro nele e,
  com erro, o Jellyfin **pula a limpeza** dos canais velhos. O botão **"Desativar os plugins e limpar"**
  desativa esses plugins (sem apagar), reinicia o Jellyfin, atualiza o guia e mostra quantos canais ficaram.
  Para usar de novo: Painel > Plugins > Ativar.
- **Tela de Arquivos (Organizar), seletor e filtros:** caixa ☑/☐ na coluna **#** de cada "vai mover"
  (clique na caixa; o título **☑ #** marca/desmarca todos os que estão à vista; botões **☑ Mover selecionados**
  e **☐ Não mover selecionados**). Clique no título de **cada coluna** (Situação, Arquivo atual, Novo nome,
  Nome via, Legenda, Progresso) para filtrar digitando ou marcando valores. **O Organizar só mexe no que está
  marcado E à vista**: o que foi desmarcado ou escondido por um filtro fica onde está, sem nenhuma alteração.
- **Proteger a pasta...:** selecione um arquivo e a pasta dele (a da série, se o arquivo estiver em
  "Season 1") entra em "Pastas protegidas": nem o Organizar nem a pasta vigiada mexem mais nela.
- **Episódios com nome e ano no arquivo** ("Tom and Jerry EP37 Professor Tom (1948).mkv"): o nome do episódio
  é mantido ("Tom and Jerry S01E37 - Professor Tom") e o ano do episódio ajuda a achar a série certa no TMDB
  (a de 1940, e não a refilmagem de 2023 com o mesmo nome).

- **archive.org, item com vários vídeos:** o link de um item (`/details/<item>` ou a lista de arquivos
  `/download/<item>`) traz TODOS os vídeos dele (ex.: os episódios de uma série em domínio público), um por
  episódio (o original no lugar do .mp4 gerado), em ordem natural. Antes vinha só um.
- **Licença ao baixar (como no Espelhar):** se algum vídeo do archive.org não for de domínio público nem
  Creative Commons, o programa pergunta: **"Só domínio público / CC"** (baixa os livres e pula os outros) ou
  **"Todos (tenho certeza)"**. Lá qualquer pessoa pode enviar arquivos; baixe só o que você tem direito.
- **Seletor na lista de vídeos:** caixa ☐/☑ na coluna **#**. Um clique marca ou desmarca a linha sem perder as
  outras (não precisa de Ctrl); Shift+clique continua marcando um intervalo; clicar no título **☐ #** marca todos
  (de novo: nenhum). No campo **Marcar**, digite números (`1-5, 8` ou `10 a 12`) ou parte do nome (`1x0`) e
  aperte Enter. Depois, **Baixar selecionados**.

### Novidades da v1.9.1

- **TV ao vivo, canais que nem a limpeza tira:** a lista enviada não repete mais `tvg-id` nem número (o mesmo
  tvg-id em dois canais pode dar erro na atualização do guia, e com erro o Jellyfin não apaga os canais velhos).
- **Diagnóstico do Jellyfin** (janela TV ao vivo, e sozinho quando a limpeza não resolve): serviços de TV ao vivo
  (inclusive de plugins), sintonizadores, guias, uma amostra dos canais com o serviço de cada um e a última
  atualização do guia; botão para copiar e mandar.

### Novidades da v1.9

- **TV ao vivo, canais que não saíam do Jellyfin:** o programa contava os canais antes de o Jellyfin terminar de
  atualizar o guia (via a tarefa "parada" antes de começar); agora só vale um fim mais novo que o do pedido, e
  um erro da tarefa aparece na mensagem. Listas antigas do programa (outro "videoscraper" apontando para outro
  arquivo) saem no envio. Se o Jellyfin ainda ficar com bem mais canais que a lista, o programa mostra os
  sintonizadores e oferece **"Limpar e reenviar"** (tira, espera apagar, põe de volta).
- **Lixeira com limpeza:** os lotes de `.organizador\removidos` com mais de 30 dias: o programa pergunta (no
  máximo uma vez por semana) se pode apagar de vez, mostrando o espaço que libera.
- **Painel de saúde:** no topo da aba Jellyfin, uma linha com as bibliotecas, o Jellyfin (chave/conexão), a
  vigia, o lugar fixo e a versão; laranja quando falta algo.
- **Não identificados por pasta:** botão "Não identificados..." junta os arquivos por pasta (o maior grupo
  primeiro); escolha a pasta e "Corrigir nome" vale para todos os arquivos dela de uma vez.
- **Completar biblioteca, escolhendo o quê:** uma janela para marcar **Legendas**, **Imagens** e **.nfo**
  (e "Só o que falta" ou "Substituir o que já existe"); ex.: só atualizar as imagens, sem mexer nas legendas. A
  escolha fica lembrada.
- **Imagens de séries:** pôster e fundo na pasta da série e o pôster de cada temporada (`Season 01/poster.jpg`),
  uma consulta ao TMDB por série (antes, séries não recebiam imagem nenhuma).

### Novidades da v1.8.1

- **Scan do Jellyfin à vista:** o fim da vigia e do Organizar diz se o Jellyfin foi avisado para atualizar a
  biblioteca ("scan pedido") ou por que não (sem a chave de API, erro de conexão). Antes isso ia só para o log.
- O estado da vigia avisa (em laranja) quando falta a chave do Jellyfin: sem "Lembrar as chaves", ela some ao
  reiniciar o programa e o scan deixava de ser pedido.
- Botão **"Atualizar a biblioteca agora"** (aba Jellyfin, embaixo de "Testar conexão").
- **Lugar fixo do programa (Windows):** ao abrir o .exe de fora dele (ex.: Downloads), o programa oferece se
  instalar em `C:\Users\<você>\AppData\Local\Programs\videoscraper` (sem precisar de administrador), cria o
  atalho **videoscraper** na Área de Trabalho e no Menu Iniciar e reabre de lá. As atualizações vão sempre para
  esse lugar, e o "Iniciar com o Windows" também aponta para ele. Na aba Jellyfin aparece onde o programa está e o
  botão "Abrir a pasta do programa".
- **"Iniciar com o Windows" que parou de funcionar:** ele guardava o caminho do .exe daquele momento; se a pasta
  mudasse (outro download, cópia apagada), o Windows não abria nada. Agora, ao abrir, o programa confere e corrige
  o caminho sozinho (dando preferência ao lugar fixo).

### Novidades da v1.8

- **TV ao vivo, enviar com filtro ligado:** o filtro só esconde canais; agora o envio pergunta se é para mandar
  só os filtrados (os outros saem da lista, dá para desfazer) ou todos.
- **Outros sintonizadores no Jellyfin:** depois do envio, o programa mostra os sintonizadores cadastrados fora
  dele (ex.: uma lista grande da internet), que somam canais ao total, e oferece tirá-los do Jellyfin.
- **Pastas vigiadas:** aceitam vírgula ou ponto e vírgula além de uma por linha; aviso na hora para pasta que não
  existe. Vigiar a própria biblioteca continua valendo (o que já está organizado fica).
- **Vigia e filmes:** sem a biblioteca de Filmes escolhida, os filmes ficavam parados sem aviso; agora o estado
  da vigia e o resultado de cada rodada avisam.
- **Idiomas das legendas:** quantos quiser (vírgula, ponto e vírgula ou espaço), pelo código ou pelo nome
  (francês, coreano, russo...); 40 idiomas conhecidos; mostra o que entendeu; botão "Mais idiomas..." para marcar.
- **Atualizar sozinho:** com a opção marcada, a versão nova é baixada, o programa espera ficar livre, avisa no
  rodapé (20 s) e reinicia já atualizado. Desmarcar cancela.

### Novidades da v1.7 (TV ao vivo organizada)

- **Desfazer remoção:** os canais removidos (selecionados ou "Remover todos") podem voltar, cada um no lugar em
  que estava (guarda as últimas 10 remoções).
- **Favoritos mantidos:** ao enviar com canais removidos, o programa atualiza a lista, espera o Jellyfin
  atualizar o guia e confere se os removidos saíram; só recria o sintonizador se eles continuarem lá.
- **Selecionar os repetidos:** o mesmo canal em links diferentes ("TV Cultura (720p)" = "TV Cultura HD"); fica
  um de cada (o primeiro que está no ar).
- **Histórico (coluna Últimas):** as últimas 5 conferências de cada canal (✓ no ar, ✕ falhou) e o botão
  "os que sempre falham" (falhou em todas as últimas 3 ou mais; canais "Not 24/7" que às vezes funcionam não entram).
- **Editar com duplo clique:** nome, número, grupo, link, logo e o ID do guia.
- **Número do canal (Nº):** vai para o Jellyfin (tvg-chno); "Numerar em ordem..." numera 1, 2, 3... (ou só os
  selecionados, continuando do maior número).
- **Velocidade da conferência:** Leve (8 consultas ao mesmo tempo), Normal (16, o padrão) ou Rápida (32). Muitas
  conexões de uma vez podem lotar o roteador/Wi-Fi e parecer que o computador travou. No Windows a conferência
  roda com prioridade "abaixo do normal".
- Código: a parte de TV ao vivo da janela foi para `videoscraper/tv_moderna.py`.

### Novidades da v1.6.3

- **Canais removidos saem do Jellyfin de verdade:** ao "Salvar e enviar", a lista canais.m3u é sempre regravada
  (lista vazia = sem canais; antes ficava a antiga), o sintonizador M3U é recriado quando algum canal saiu e,
  com a lista vazia, é retirado do Jellyfin. Depois o programa roda "Atualizar o guia", espera terminar e mostra
  quantos canais o Jellyfin ficou tendo. Enviar a lista vazia pede confirmação.

### Novidades da v1.6.2

- **Conferir só os selecionados:** selecione uma faixa de canais e o botão vira "Conferir N selecionado(s)"
  (sem seleção: "Conferir todos"). Os outros canais mantêm a situação de antes.
- **Menos "fora do ar" falso:** vale o conteúdo da resposta (#EXTM3U), mesmo que o servidor diga que é
  "text/html"/"text/plain" ou mande a marca BOM; pedidos com cabeçalhos de navegador; espera de até 10 s pela
  resposta; desiste de um servidor só depois de 3 falhas e nunca ao conferir poucos canais (até 30).

### Novidades da v1.6.1 (TV ao vivo mais rápida)

- **Conferir canais sem travar:** servidor que conecta e fica mudo conta como "fora do ar" (depois de 2 canais
  assim, os outros dele saem na hora); nenhum canal segura a fila mais que 12 s; servidor que nem existe mais é
  descoberto uma vez só, no começo; os canais são intercalados por servidor. Num teste com servidores lentos e
  mudos, 467 canais passaram de **mais de 5 min para 18 s**, e o processador gasto em 11 mil canais caiu de 62 s
  para 2 s.
- **Filtro da coluna com campo de digitar:** escreva parte do valor (a lista encolhe enquanto você digita) e/ou
  marque um ou vários valores (☑). Abre na hora mesmo com 11 mil canais (antes travava a tela).
- **Exportar (JSON, CSV ou TXT)...:** salva as colunas da tabela (com filtro ligado, só os filtrados). O CSV abre
  direto no Excel.

### Novidades da v1.6

- **Verificar atualizações** (no topo): consulta na hora, sem fechar o programa; **Baixar agora** em segundo
  plano; para instalar, avisa que o programa **precisa fechar** e faz a troca sozinho (detalhes em "Aviso de
  versão nova", abaixo).
- **TV ao vivo**: filtro em cada coluna (clique no título: um ou vários valores), "Remover todos",
  "Selecionar os fora do ar" e conferência bem mais rápida em listas grandes.
- **Parar vale na hora** em tudo que demora: conferir canais/espelhos, buscar vídeos (inclusive ao listar as
  páginas e nas pausas entre pedidos), pré-visualizar (a prévia parada não libera o Organizar), organizar
  (termina o arquivo atual; uma cópia grande entre discos é interrompida e o original fica onde estava; o
  "Desfazer última" vale para o que já foi movido), relatório e espelhar (nada é criado pela metade).
  Velocidade e tempo restante no rodapé: "526 de 11393 · 40/s · faltam ~5 min".

### Novidades da v1.5

- **Corrigir nome** (painel "Antes → Depois"): clique num arquivo não identificado (ou com o nome errado),
  em **Corrigir nome...**, e diga qual é a série (nome, ano e, se quiser, a temporada) ou o filme. No modo
  Séries a regra vale para a **pasta inteira**: todos os episódios dela entram com esse nome, e o número de cada
  episódio continua vindo do arquivo (um `S03E15` escrito no arquivo vale mais que a temporada da regra). A
  regra fica guardada (`.videoscraper\regras_nomes.json`) e vale nas próximas organizações, na vigia e no
  script; "Esquecer a regra" apaga.
- **Resolver conflitos** (mesmo painel): fica a **melhor cópia**: a de maior resolução **lida do próprio vídeo**
  (pelo ffmpeg; na biblioteca o nome já não diz "1080p"), depois a origem (BluRay > WEB > DVD) e o tamanho. Se a
  cópia nova for melhor que a da biblioteca, ela entra no lugar. A que sai vai para
  `.organizador\removidos` (o Jellyfin ignora) e **Desfazer última** põe de volta; para liberar o espaço de
  vez, apague essa pasta. Com linhas selecionadas, resolve só elas; sem seleção, todos os conflitos.
- **Pastas protegidas** (seção "Automático"): as pastas do **Sonarr/Radarr** (ou outras): o organizador nunca
  entra nelas (nem organiza, nem apaga, nem põe legenda), nem pela vigia. No script: `PASTAS_PROTEGIDAS`.
- **Aviso de versão nova**: ao abrir (e a cada 6 horas, com o programa aberto) consulta a página Releases e
  avisa uma vez cada versão nova. A versão aparece no título da janela. Dá para desligar em "Automático".
  **Verificar atualizações** (no topo, ao lado de Vídeos/Jellyfin) consulta na hora, sem fechar nada.
  **Baixar agora** baixa o `.zip` em segundo plano (Downloads); dá para continuar usando. Para **instalar**, o
  programa precisa fechar (o Windows não deixa trocar um programa aberto) e ele avisa isso:
  **Fechar e atualizar agora** (fecha, troca os arquivos sozinho e abre de novo), **Atualizar quando eu fechar**
  ou **Depois**. As configurações (`C:\Users\<você>\.videoscraper`) não são tocadas. O GitHub testa essa troca
  no Windows a cada versão.
- **Iniciar com o Windows** (seção "Automático"): abre minimizado **perto do relógio**, com a vigia e a
  conferência funcionando sem a janela aberta. Clique no ícone para abrir; "Sair" no menu dele fecha de
  verdade. "Ao fechar (X), continuar rodando perto do relógio" faz o X só esconder a janela. Fica na lista do
  Gerenciador de Tarefas > Inicializar (dá para desligar por lá também). Opção de linha de comando: `--minimizado`.
- **TV ao vivo...** (barra de cima): canais ao vivo no Jellyfin (Painel > TV ao vivo), sem outro programa:
  1. adicione canais (nome + link do sinal `.m3u8`) ou importe uma lista `.m3u` (arquivo ou endereço);
  2. **Conferir**: só os canais **selecionados** (sem seleção, todos): no ar / fora do ar / pede login / link
     temporário (com token, que expira).
     **Selecionar os fora do ar** + **Remover selecionados** limpa a lista; **Remover todos** zera. Clique no
     **título de uma coluna** (Canal, Grupo, Situação, Link) para marcar um ou vários valores dela: a lista mostra
     e seleciona só esses (o Link conta pelo site); "Tirar os filtros" volta tudo. Listas grandes: 32 canais
     conferidos ao mesmo tempo (no máximo 6 do mesmo servidor), a conexão é reaproveitada e um servidor que não
     responde não é tentado de novo canal por canal; o rodapé mostra "526 de 11393 · 40/s · faltam ~5 min" e o
     **Parar** vale na hora (fica o que já foi conferido). Importar um
     link que é uma PÁGINA de site (não uma lista `.m3u`) é recusado com um aviso;
  3. **Salvar e enviar ao Jellyfin**: grava `canais.m3u` e cadastra pela API o sintonizador M3U, o **guia de
     programação** (XMLTV, opcional: sem ele os canais aparecem sem a grade de horários) e uma **antena
     HDHomeRun** (IP, opcional: TV aberta digital pela antena, de graça e legal).
  A pasta da lista precisa ser vista pelo **servidor** do Jellyfin; se ele roda em outro PC, preencha "Como o
  servidor enxerga o arquivo" (ex.: `E:\TV\canais.m3u` lá, `\\Servidor\e\TV` aqui). A conferência automática
  dos espelhos também confere os canais e avisa no Discord/Telegram quando um sai do ar (script:
  `--conferir-espelhos`, `ARQUIVO_CANAIS`). Use só fontes que você tem direito de assistir: o sinal aberto
  oficial, a lista da sua operadora ou a antena. Listas "piratas" de canais pagos não.

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
  automacao.py  comandos para robôs (Maestro.exe --organizar, --conferir-espelhos...), sem janela
  agendador.py  põe os comandos de robô no Agendador de Tarefas do Windows
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
  traducao.py           traduz legendas .srt com a IA (Claude), mantendo os horários
  traducao_lote.py      a mesma tradução em lote (metade do preço, pronta em até 24 h)
  transcricao.py        cria a legenda ouvindo o áudio (Whisper, no PC)
  dublagem.py           lê a legenda com voz sintética (Piper) e junta ao vídeo (ffmpeg)
  sincronia.py          acerta legenda adiantada/atrasada comparando com a voz do áudio
  resumo_diario.py      o resumo do dia no Discord/Telegram
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

No GitHub eles rodam sozinhos a cada envio (`.github/workflows/testes.yml`): as duas janelas em processos
separados, porque o Tk não aceita as duas no mesmo processo. Nenhum teste usa a internet nem gasta crédito
de API: servidores locais e um "cliente falso" fazem o papel do TMDB, do Jellyfin e do Claude.
