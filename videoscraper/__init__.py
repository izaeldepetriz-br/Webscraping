"""videoscraper: encontra e baixa vídeos PÚBLICOS de páginas web.

Módulos (cada um com UMA responsabilidade):
  extracao   -> lê HTML e acha links de vídeo (não acessa a internet)
  rede       -> conversa com servidores via requests (robots.txt, pausas, tentativas)
  navegador  -> abre um Chrome de verdade (Playwright) para sites com JavaScript/login
  coleta     -> junta tudo: obtém páginas, navega entre elas, devolve os links
  download   -> salva os vídeos no disco (arquivo direto ou streaming HLS via ffmpeg)
  cli        -> comandos de terminal (links / baixar / login)
  menu       -> menu interativo para quem não quer decorar comandos
"""

__version__ = "1.5.0"   # o .exe do GitHub usa versao_build.txt (a versão publicada em Releases)
