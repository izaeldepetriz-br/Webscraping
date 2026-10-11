## Como usar (Windows, sem instalar o Python)

1. Baixe **videoscraper-windows.zip** logo abaixo, em **Assets**.
2. Clique com o botão direito no arquivo → **Extrair tudo...**
3. Abra a pasta e dê dois cliques em **videoscraper.exe**.
   Mantenha a pasta inteira junta: o `.exe` usa os outros arquivos dela.

Se o Windows mostrar "O Windows protegeu o seu computador", clique em **Mais informações → Executar assim mesmo**
(o programa não tem assinatura digital paga, por isso o aviso).

Suas configurações ficam em `C:\Users\<você>\.videoscraper\` e continuam valendo ao trocar de versão.

## O que tem nesta versão

- **Vídeos:** busca e baixa vídeos públicos de páginas (respeitando o robots.txt), com modo navegador para sites com JavaScript.
- **Jellyfin – organizar:** filmes e séries com os nomes do TMDB, legendas (OpenSubtitles + SubDL), pôster, `.nfo`, limpeza de lixo de torrent, Desfazer.
- **Pasta vigiada:** várias pastas do uTorrent/qBittorrent; filmes e séries separados sozinhos.
- **Espelhos (.strm):** espelhar links no Jellyfin sem baixar; conferir os links (também automático, a cada minutos/horas/dias, com aviso no Discord/Telegram); remover qualquer espelhamento, não só o último.
- **Relatório:** filmes sem legenda ou pôster e episódios faltando por temporada.
- **Traduzir legendas com IA:** cria `Nome.pt-BR.srt` a partir de uma legenda em outro idioma, com os mesmos horários (API da Anthropic, modelo padrão `claude-sonnet-4-6`; mostra o custo estimado antes).
- **TV ao vivo:** coluna "Agora passando" e o coletor de programação no painel de saúde (com aviso se ele parar).
- **Comandos para robôs (RPA):** `Maestro.exe --organizar`, `--conferir-espelhos`, `--conferir-canais`, `--enviar-tv` e `--traduzir-legendas`, sem abrir a janela, com código de saída (0 certo, 1 problema, 2 falta configuração, 3 erro) e resumo em `.videoscraper\rpa\ultimo.json`.
- **Legenda pelo áudio e dublagem por IA:** o Whisper (no PC) cria a legenda dos vídeos sem nenhuma; o Claude traduz; o Piper lê a legenda em português e gera "Nome - Dublado IA.mkv" (o original fica intacto).
- **Mais:** sincronizar legendas, tradução econômica em lote (metade do preço), agendar várias tarefas de uma vez no Windows (caixas de marcar), resumo do dia no Discord/Telegram, exportar/importar configurações.
- **Dublagem mais natural e voz premium:** falas longas reescritas mais curtas pelo Claude (fiéis ao sentido); voz premium do Gemini (Google AI Studio, vozes prontas, pago por uso) no lugar do Piper; botão "O que a vigia faria agora?" (simulação, sem mover nada).
- **Gemini econômico e voz por personagem:** blocos de até 30 falas por pedido, progresso guardado por filme (continua de onde parou se o limite do dia acabar) e uma voz para cada personagem (o Gemini ouve o filme; você confere na tabela "Vozes dos personagens").
- **Dublagem mista:** figurantes com o Piper (grátis) e os principais com o Gemini; ou escolha quais filmes vão com o Gemini e o resto com o Piper.
- **Nova tela ⚙ Configurações:** todas as opções num lugar, por categoria; Vídeos e Jellyfin sem painel lateral (a lista ocupa a tela); chaves de API centralizadas com Validar; dublagem com os modos Piper, Gemini e Misto.
- **Clonar a sua voz (réplica do Gemini, sem placa de vídeo):** em ⚙ Configurações > Dublagem, grave (microfone ou arquivo) um texto e a frase de consentimento; o Google confere que é a mesma pessoa. Só a sua voz ou de quem autorizou; a chave fica só no seu PC. A voz clonada aparece como voz principal e na tabela dos personagens; o painel de saúde avisa quando a chave vai vencer; opção de guardar as gravações para "Clonar de novo" com um clique.
- **Ouvir uma frase de teste** com a voz escolhida (pronta ou clonada) antes de dublar.
- **Atualização mais rápida**, com a janelinha "Atualizando o Maestro... (%)"; e "Ampliar lista" funcionando em telas baixas (notebooks).
- **v2.14 — amostra antes de dublar:** "Ouvir uma amostra (1 min)" dubla só o minuto com mais falas; as falas são reaproveitadas no filme inteiro.
- **v2.14 — gastos do mês, em reais:** Configurações > Gastos mostra o gasto estimado com Claude e Gemini em R$ (cotação PTAX do Banco Central + IOF do cartão) e aceita um teto em reais (as tarefas pagas param ao chegar nele).
- **v2.14 — vídeos avulsos:** uma caixa de entrada (ou arquivos de qualquer pasta) que ganha legenda em português e dublagem; robô `--avulsos`.
- **v2.14 — séries:** episódios dublados na pasta irmã "Séries (Dublado IA)", com as mesmas vozes para os mesmos personagens em todos os episódios.
- **v2.14 — notebooks:** a aba Jellyfin mostra só o que cabe e a lista cresce (antes ficava espremida e o console cortado).
- **Correções:** a pasta vigiada se organiza dentro dela mesma (opção marcada); "Conferir 1 selecionado" na TV não é mais seguido pela conferência automática de todos os canais.
