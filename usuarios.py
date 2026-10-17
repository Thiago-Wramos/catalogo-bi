"""
usuarios.py - login e administração de usuários.

Regras de segurança:
  - A senha nunca é guardada: só o hash bcrypt dela.
  - A mensagem de erro do login é sempre a mesma ("login ou senha incorretos"),
    para não revelar se um login existe.
  - Toda tentativa de login vai para a tabela auditoria_login.
  - Ninguém pode tirar o próprio acesso de administrador, e sempre precisa
    sobrar pelo menos um administrador ativo (evita ficar trancado para fora).
"""

import re

import bcrypt
from sqlalchemy import bindparam, text

ROLE_ADMIN = "Admin"
PADRAO_LOGIN = re.compile(r"^[a-z0-9._-]{3,50}$")
TAMANHO_MINIMO_SENHA = 8

# Hash de uma senha qualquer, usado quando o login não existe (ver autenticar)
_HASH_FALSO = bcrypt.hashpw(b"senha-que-nao-existe", bcrypt.gensalt()).decode()


class ErroUsuario(Exception):
    """Erro de validação, com mensagem pronta para mostrar na tela."""


# =====================================================================
# VALIDAÇÃO E HASH
# =====================================================================
def validar_login(login):
    if not PADRAO_LOGIN.match(login or ""):
        raise ErroUsuario(
            "Login inválido: use de 3 a 50 caracteres entre letras minúsculas, "
            "números, ponto, hífen ou sublinhado."
        )


def validar_senha(senha):
    if len(senha or "") < TAMANHO_MINIMO_SENHA:
        raise ErroUsuario(f"A senha precisa ter pelo menos {TAMANHO_MINIMO_SENHA} caracteres.")
    if len(senha.encode("utf-8")) > 72:  # limite do bcrypt
        raise ErroUsuario("A senha é longa demais.")


def gerar_hash(senha):
    validar_senha(senha)
    return bcrypt.hashpw(senha.encode("utf-8"), bcrypt.gensalt()).decode()


def _confere(senha, hash_salvo):
    try:
        return bcrypt.checkpw((senha or "").encode("utf-8"), hash_salvo.encode())
    except ValueError:  # senha acima do limite do bcrypt
        return False


# =====================================================================
# LOGIN
# =====================================================================
def _roles_do_usuario(conn, usuario_id):
    return conn.execute(text("""
        SELECT ro.nome FROM usuario_role ur
        JOIN role ro ON ro.id = ur.role_id
        WHERE ur.usuario_id = :id
        ORDER BY ro.nome
    """), {"id": usuario_id}).scalars().all()


def autenticar(engine, login, senha):
    """Devolve os dados do usuário se login e senha conferirem; senão, None."""
    login = (login or "").strip().lower()

    with engine.begin() as conn:
        u = conn.execute(
            text("SELECT id, login, nome, senha_hash, ativo FROM usuario WHERE login = :login"),
            {"login": login},
        ).mappings().first()

        if u and u["senha_hash"] and u["ativo"]:
            ok = _confere(senha, u["senha_hash"])
        else:
            # Confere contra um hash falso para gastar o mesmo tempo:
            # assim, o tempo de resposta não revela se o login existe.
            _confere(senha, _HASH_FALSO)
            ok = False

        conn.execute(
            text("INSERT INTO auditoria_login (login, sucesso) VALUES (:login, :ok)"),
            {"login": login[:50], "ok": ok},
        )
        if not ok:
            return None

        conn.execute(text("UPDATE usuario SET ultimo_login = NOW() WHERE id = :id"), {"id": u["id"]})
        roles = _roles_do_usuario(conn, u["id"])

    return {"login": u["login"], "nome": u["nome"], "roles": roles, "admin": ROLE_ADMIN in roles}


def eh_admin(engine, login):
    """Consulta o banco na hora: não confia só no que ficou guardado na sessão."""
    with engine.connect() as conn:
        return bool(conn.execute(text("""
            SELECT COUNT(*) FROM usuario u
            JOIN usuario_role ur ON ur.usuario_id = u.id
            JOIN role ro         ON ro.id = ur.role_id
            WHERE u.login = :login AND u.ativo = TRUE AND ro.nome = :admin
        """), {"login": login, "admin": ROLE_ADMIN}).scalar())


# =====================================================================
# ADMINISTRAÇÃO
# =====================================================================
def listar_usuarios(engine):
    with engine.connect() as conn:
        linhas = conn.execute(text("""
            SELECT u.login, u.nome, u.ativo,
                   (u.senha_hash IS NOT NULL) AS tem_senha,
                   u.ultimo_login,
                   GROUP_CONCAT(ro.nome ORDER BY ro.nome SEPARATOR ', ') AS roles
            FROM usuario u
            LEFT JOIN usuario_role ur ON ur.usuario_id = u.id
            LEFT JOIN role ro         ON ro.id = ur.role_id
            GROUP BY u.id, u.login, u.nome, u.ativo, u.senha_hash, u.ultimo_login
            ORDER BY u.login
        """)).mappings().all()
    return [
        {**dict(l), "lista_roles": l["roles"].split(", ") if l["roles"] else []}
        for l in linhas
    ]


def listar_roles(engine):
    with engine.connect() as conn:
        return conn.execute(text("SELECT nome FROM role ORDER BY nome")).scalars().all()


def _id_do_usuario(conn, login):
    id_ = conn.execute(text("SELECT id FROM usuario WHERE login = :l"), {"l": login}).scalar()
    if id_ is None:
        raise ErroUsuario(f"Usuário '{login}' não encontrado.")
    return id_


def _definir_roles(conn, usuario_id, roles):
    roles = sorted(set(roles or []))
    if not roles:
        raise ErroUsuario("Escolha pelo menos uma role.")
    if ROLE_ADMIN in roles and len(roles) > 1:
        raise ErroUsuario(
            f"A role {ROLE_ADMIN} já dá acesso a todos os relatórios e não pode ser combinada com outras."
        )
    sql = text("SELECT id FROM role WHERE nome IN :roles").bindparams(
        bindparam("roles", expanding=True)
    )
    ids = conn.execute(sql, {"roles": roles}).scalars().all()
    if len(ids) != len(roles):
        raise ErroUsuario("Uma das roles escolhidas não existe.")

    conn.execute(text("DELETE FROM usuario_role WHERE usuario_id = :u"), {"u": usuario_id})
    conn.execute(
        text("INSERT INTO usuario_role (usuario_id, role_id) VALUES (:u, :r)"),
        [{"u": usuario_id, "r": r} for r in ids],
    )


def _conferir_que_sobra_admin(conn):
    total = conn.execute(text("""
        SELECT COUNT(DISTINCT u.id) FROM usuario u
        JOIN usuario_role ur ON ur.usuario_id = u.id
        JOIN role ro         ON ro.id = ur.role_id
        WHERE ro.nome = :admin AND u.ativo = TRUE AND u.senha_hash IS NOT NULL
    """), {"admin": ROLE_ADMIN}).scalar()
    if total == 0:
        raise ErroUsuario("Precisa sobrar pelo menos um administrador ativo com senha.")


def criar_usuario(engine, login, nome, senha, roles):
    login = (login or "").strip().lower()
    nome = (nome or "").strip()
    validar_login(login)
    if not nome:
        raise ErroUsuario("Informe o nome.")
    hash_ = gerar_hash(senha)

    with engine.begin() as conn:
        if conn.execute(text("SELECT 1 FROM usuario WHERE login = :l"), {"l": login}).first():
            raise ErroUsuario(f"Já existe um usuário com o login '{login}'.")
        conn.execute(
            text("INSERT INTO usuario (login, nome, senha_hash) VALUES (:l, :n, :h)"),
            {"l": login, "n": nome, "h": hash_},
        )
        _definir_roles(conn, _id_do_usuario(conn, login), roles)


def atualizar_usuario(engine, login, nome, roles, ativo, quem_edita):
    nome = (nome or "").strip()
    if not nome:
        raise ErroUsuario("Informe o nome.")
    if login == quem_edita and (not ativo or ROLE_ADMIN not in roles):
        raise ErroUsuario("Você não pode tirar o seu próprio acesso de administrador nem se desativar.")

    # Tudo numa transação: se a última checagem falhar, nada é gravado (rollback)
    with engine.begin() as conn:
        usuario_id = _id_do_usuario(conn, login)
        conn.execute(
            text("UPDATE usuario SET nome = :n, ativo = :a WHERE id = :id"),
            {"n": nome, "a": bool(ativo), "id": usuario_id},
        )
        _definir_roles(conn, usuario_id, roles)
        _conferir_que_sobra_admin(conn)


def redefinir_senha(engine, login, senha):
    hash_ = gerar_hash(senha)
    with engine.begin() as conn:
        usuario_id = _id_do_usuario(conn, login)
        conn.execute(
            text("UPDATE usuario SET senha_hash = :h WHERE id = :id"),
            {"h": hash_, "id": usuario_id},
        )