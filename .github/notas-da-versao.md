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
- **Mais:** sincronizar legendas, tradução econômica em lote (metade do preço), agendar tarefas no Windows, resumo do dia no Discord/Telegram, exportar/importar configurações.
