"""Menu interativo: monta os comandos para você, pergunta por pergunta."""

from __future__ import annotations

from . import cli


def perguntar(texto: str, padrao: str = "") -> str:
    sufixo = f" [{padrao}]" if padrao else ""
    return input(f"{texto}{sufixo}: ").strip() or padrao


def sim(texto: str) -> bool:
    return perguntar(texto + " (s/N)", "n").lower().startswith("s")


def main() -> int:
    print("=== Maestro: vídeos públicos ===")
    print("1) Listar links de vídeo de uma página")
    print("2) Baixar vídeos de uma página")
    print("3) Ver o que seria baixado (sem baixar)")
    print("4) Fazer login num site (abre o navegador; a sessão fica salva)")
    print("0) Sair")
    opcao = perguntar("Escolha", "1")
    if opcao == "0":
        return 0
    if opcao not in {"1", "2", "3", "4"}:
        print("❌ Opção inválida.")
        return 1

    url = perguntar("URL da página (começa com https://)")
    if opcao == "4":
        return cli.main(["login", url])

    comando = "links" if opcao == "1" else "baixar"
    args = [comando, url]

    print("\nO navegador é necessário quando a página monta os vídeos com JavaScript,")
    print("exige login, ou quando o modo simples não encontrou nada.")
    if sim("Usar navegador?"):
        args.append("--navegador")
        if sim("Parar para você resolver login/verificação na janela?"):
            args.append("--pausar")
        elif sim("Mostrar a janela do navegador?"):
            args.append("--visivel")

    seletor = perguntar("Seletor CSS dos links (Enter = detectar sozinho)")
    if seletor:
        args += ["--seletor", seletor]
    args += ["-p", perguntar("Seguir links até quantos níveis? (0 = só esta página)", "0")]

    if opcao == "1":
        saida = perguntar("Salvar em arquivo (links.csv / .json / .txt) ou Enter para mostrar na tela")
        if saida:
            args += ["-s", saida]
    elif opcao == "2":
        args += ["-d", perguntar("Pasta de destino", "videos_baixados"),
                 "-l", perguntar("Máximo de vídeos (0 = todos)", "0")]
    else:
        args.append("--so-listar")

    print("\n▶ Comando equivalente: python -m videoscraper " + " ".join(
        f'"{a}"' if " " in a else a for a in args) + "\n")
    return cli.main(args)
