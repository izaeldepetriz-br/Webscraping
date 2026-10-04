#!/usr/bin/env python3
"""Menu interativo: para quem não quer decorar opções de linha de comando."""

import baixar_videos
import extrair_links_videos


def perguntar(texto, padrao=""):
    """Faz uma pergunta; Enter sem digitar usa o valor padrão entre colchetes."""
    sufixo = f" [{padrao}]" if padrao else ""
    resposta = input(f"{texto}{sufixo}: ").strip()
    return resposta or padrao


def main():
    print("=== Vídeos públicos: extrair e baixar ===")
    print("1) Listar links de vídeo de uma página (todos os tipos: <video>, iframe, .mp4...)")
    print("2) Baixar vídeos de uma página de listagem (por seletor CSS)")
    print("3) Só mostrar o que o seletor encontraria (sem baixar nada)")
    print("0) Sair")
    opcao = perguntar("Escolha", "1")
    if opcao == "0":
        return 0

    url = perguntar("URL da página (começa com https://)")
    if not url.startswith(("http://", "https://")):
        print("❌ A URL precisa começar com http:// ou https://")
        return 1

    if opcao == "1":
        prof = perguntar("Seguir links até quantos níveis? (0 = só esta página)", "0")
        saida = perguntar("Salvar em arquivo (links.csv / links.json / links.txt) ou Enter para mostrar na tela")
        args = [url, "-p", prof]
        if saida:
            args += ["-s", saida]
        return extrair_links_videos.main(args)

    seletor = perguntar("Seletor CSS dos links", baixar_videos.SELETOR)
    args = [url, "-s", seletor]
    if opcao == "3":
        args.append("--so-listar")
    elif opcao == "2":
        args += ["-p", perguntar("Pasta de destino", baixar_videos.PASTA),
                 "-l", perguntar("Máximo de vídeos (0 = todos)", "0")]
    else:
        print("❌ Opção inválida.")
        return 1
    return baixar_videos.main(args)


if __name__ == "__main__":
    try:
        codigo = main()
    except KeyboardInterrupt:
        print("\nInterrompido.")
        codigo = 130
    input("\nPressione Enter para fechar...")
    raise SystemExit(codigo)
