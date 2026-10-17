"""
criar_admin.py - cria (ou promove) um administrador pelo terminal.

Uso, uma vez só (Anaconda Prompt):
    python criar_admin.py

Se o login já existir, o usuário recebe a nova senha, passa a ter SÓ a
role Admin (que não pode ser combinada com outras) e é reativado.
"""

import sys
from getpass import getpass

from banco import criar_engine
from usuarios import (
    ROLE_ADMIN, ErroUsuario, atualizar_usuario, criar_usuario,
    listar_usuarios, redefinir_senha, validar_login, validar_senha,
)


def main():
    engine = criar_engine()

    login = input("Login do administrador: ").strip().lower()
    try:
        validar_login(login)
    except ErroUsuario as erro:
        sys.exit(str(erro))

    existentes = {u["login"]: u for u in listar_usuarios(engine)}
    atual = existentes.get(login)
    nome = input(f"Nome completo [{atual['nome'] if atual else ''}]: ").strip()
    if atual and not nome:
        nome = atual["nome"]

    # getpass esconde a senha enquanto você digita
    senha = getpass("Senha (não aparece enquanto você digita): ")
    if senha != getpass("Repita a senha: "):
        sys.exit("As senhas não conferem. Nada foi alterado.")

    try:
        validar_senha(senha)
        if atual:
            redefinir_senha(engine, login, senha)
            outras = sorted(set(atual["lista_roles"]) - {ROLE_ADMIN})
            if outras:
                print(f"Atenção: as roles {', '.join(outras)} serão substituídas por {ROLE_ADMIN}.")
            atualizar_usuario(engine, login, nome, [ROLE_ADMIN], True, quem_edita=None)
            print(f"Usuário '{login}' atualizado: nova senha e role {ROLE_ADMIN}.")
        else:
            criar_usuario(engine, login, nome, senha, [ROLE_ADMIN])
            print(f"Administrador '{login}' criado.")
    except ErroUsuario as erro:
        sys.exit(str(erro))


if __name__ == "__main__":
    main()