"""
carga_catalogo.py - lê a planilha do catálogo e grava no MySQL.

Etapas:
  1. Ler as duas abas da planilha (Catalogo e Dicionario_Views)
  2. Validar os dados ANTES de tocar no banco
  3. Gravar tudo numa única transação (ou grava tudo, ou nada)
  4. Criar usuários de teste, um por role
  5. Mostrar um resumo do que ficou no banco

Pode rodar quantas vezes quiser: ele atualiza o que já existe em vez de duplicar.
"""

import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from banco import criar_engine

PLANILHA = Path(__file__).parent / "dados" / "Catalogo_Relatorios_Mascarado.xlsx"

# Usuários fictícios para testar o controle de acesso: (login, nome, role)
USUARIOS_TESTE = [
    ("usr_rh", "Usuário Teste RH", "RH"),
    ("usr_comercial", "Usuário Teste Comercial", "Comercial"),
    ("usr_corporativo", "Usuário Teste Corporativo", "Corporativo"),
    ("usr_admin", "Usuário Teste Admin", "Admin"),
]


# =====================================================================
# 1. LEITURA
# =====================================================================
def sem_vazios(df):
    """Troca os vazios do pandas (NaN/NaT) por None, que o MySQL entende como NULL."""
    return df.astype(object).where(pd.notna(df), None)


def ler_planilha(caminho):
    rel = pd.read_excel(caminho, sheet_name="Catalogo")
    vws = pd.read_excel(caminho, sheet_name="Dicionario_Views")

    # "101 - Painel de Pessoas"  ->  codigo "101", nome "Painel de Pessoas"
    partes = rel["Nome do Relatório"].str.split(" - ", n=1, expand=True)
    rel["codigo"] = partes[0].str.strip()
    rel["nome"] = partes[1].str.strip()

    # "VW_A, VW_B"  ->  ["VW_A", "VW_B"]
    rel["lista_views"] = rel["Views Utilizadas"].fillna("").apply(
        lambda s: [v.strip() for v in s.split(",") if v.strip()]
    )

    vws["sensivel"] = vws["Dado Sensível"].str.strip().str.lower().eq("sim")
    return rel, vws


# =====================================================================
# 2. VALIDAÇÃO (antes de gravar qualquer coisa)
# =====================================================================
def validar(rel, vws, roles_validas):
    erros = []

    duplicados = rel.loc[rel["codigo"].duplicated(), "codigo"].tolist()
    if duplicados:
        erros.append(f"Códigos de relatório repetidos: {duplicados}")

    sem_nome = rel.loc[rel["nome"].isna(), "Nome do Relatório"].tolist()
    if sem_nome:
        erros.append(f"Nomes fora do padrão 'código - nome': {sem_nome}")

    roles_planilha = set(rel["Role"].dropna().str.strip())
    desconhecidas = roles_planilha - roles_validas
    if desconhecidas:
        erros.append(f"Roles que não existem no banco: {sorted(desconhecidas)}")

    sem_role = rel.loc[rel["Role"].isna(), "codigo"].tolist()
    if sem_role:
        erros.append(f"Relatórios sem role: {sem_role}")

    usadas = {v for lista in rel["lista_views"] for v in lista}
    nao_documentadas = usadas - set(vws["View"].str.strip())
    if nao_documentadas:
        erros.append(f"Views usadas mas ausentes no dicionário: {sorted(nao_documentadas)}")

    return erros


# =====================================================================
# 3. GRAVAÇÃO
# =====================================================================
SQL_UPSERT_RELATORIO = text("""
    INSERT INTO relatorio
        (codigo, nome, descricao, area, empresa, responsavel, desenvolvedor,
         qtd_acessos, dt_solicitacao, dt_publicacao)
    VALUES
        (:codigo, :nome, :descricao, :area, :empresa, :responsavel, :desenvolvedor,
         :qtd_acessos, :dt_solicitacao, :dt_publicacao)
    ON DUPLICATE KEY UPDATE
        nome = VALUES(nome), descricao = VALUES(descricao), area = VALUES(area),
        empresa = VALUES(empresa), responsavel = VALUES(responsavel),
        desenvolvedor = VALUES(desenvolvedor), qtd_acessos = VALUES(qtd_acessos),
        dt_solicitacao = VALUES(dt_solicitacao), dt_publicacao = VALUES(dt_publicacao)
""")

SQL_UPSERT_VIEW = text("""
    INSERT INTO view_dados (nome, schema_nome, descricao, sensivel)
    VALUES (:nome, :schema_nome, :descricao, :sensivel)
    ON DUPLICATE KEY UPDATE
        schema_nome = VALUES(schema_nome), descricao = VALUES(descricao),
        sensivel = VALUES(sensivel)
""")


def para_inteiro(valor):
    return None if valor is None else int(valor)


def gravar(conn, rel, vws, ids_role):
    # --- relatórios
    linhas = sem_vazios(rel)
    conn.execute(SQL_UPSERT_RELATORIO, [
        {
            "codigo": r["codigo"],
            "nome": r["nome"],
            "descricao": r["Descrição"],
            "area": r["Área"],
            "empresa": r["Empresa"],
            "responsavel": r["Responsável"],
            "desenvolvedor": r["Desenvolvedor"],
            "qtd_acessos": para_inteiro(r["Quantidade de Acessos"]),
            "dt_solicitacao": r["Data de Solicitação"],
            "dt_publicacao": r["Data de Publicação"],
        }
        for _, r in linhas.iterrows()
    ])

    # --- views
    linhas = sem_vazios(vws)
    conn.execute(SQL_UPSERT_VIEW, [
        {
            "nome": v["View"].strip(),
            "schema_nome": v["Schema"],
            "descricao": v["Descrição"],
            "sensivel": bool(v["sensivel"]),
        }
        for _, v in linhas.iterrows()
    ])

    # --- descobrir os ids que o banco gerou
    ids_rel = dict(conn.execute(text("SELECT codigo, id FROM relatorio")).all())
    ids_view = dict(conn.execute(text("SELECT nome, id FROM view_dados")).all())

    # --- ligações: apaga e recria, para refletir exatamente a planilha
    conn.execute(text("DELETE FROM relatorio_view"))
    conn.execute(text("DELETE FROM relatorio_role"))

    pares_view = [
        {"r": ids_rel[r["codigo"]], "v": ids_view[nome_view]}
        for _, r in rel.iterrows()
        for nome_view in r["lista_views"]
    ]
    conn.execute(
        text("INSERT INTO relatorio_view (relatorio_id, view_id) VALUES (:r, :v)"),
        pares_view,
    )

    pares_role = [
        {"r": ids_rel[r["codigo"]], "ro": ids_role[r["Role"].strip()]}
        for _, r in rel.iterrows()
    ]
    conn.execute(
        text("INSERT INTO relatorio_role (relatorio_id, role_id) VALUES (:r, :ro)"),
        pares_role,
    )


# =====================================================================
# 4. USUÁRIOS DE TESTE
# =====================================================================
def criar_usuarios_teste(conn, ids_role):
    for login, nome, role in USUARIOS_TESTE:
        conn.execute(
            text("INSERT IGNORE INTO usuario (login, nome) VALUES (:login, :nome)"),
            {"login": login, "nome": nome},
        )
        id_usuario = conn.execute(
            text("SELECT id FROM usuario WHERE login = :login"), {"login": login}
        ).scalar_one()
        conn.execute(
            text("INSERT IGNORE INTO usuario_role (usuario_id, role_id) VALUES (:u, :r)"),
            {"u": id_usuario, "r": ids_role[role]},
        )


# =====================================================================
# 5. RESUMO
# =====================================================================
def mostrar_resumo(conn):
    print("\nResumo do banco:")
    for tabela in ["relatorio", "view_dados", "relatorio_view", "relatorio_role",
                   "usuario", "usuario_role"]:
        total = conn.execute(text(f"SELECT COUNT(*) FROM {tabela}")).scalar()
        print(f"   {tabela:<16} {total:>4} linhas")

    print("\nRelatórios por role:")
    sql = text("""
        SELECT ro.nome, COUNT(*)
        FROM relatorio_role rr
        JOIN role ro ON ro.id = rr.role_id
        GROUP BY ro.nome
        ORDER BY ro.nome
    """)
    for nome, total in conn.execute(sql):
        print(f"   {nome:<12} {total:>3}")


# =====================================================================
# EXECUÇÃO
# =====================================================================
def main():
    if not PLANILHA.exists():
        sys.exit(f"Planilha não encontrada em: {PLANILHA}")

    print(f"Lendo {PLANILHA.name}...")
    rel, vws = ler_planilha(PLANILHA)
    print(f"   {len(rel)} relatórios e {len(vws)} views lidos")

    engine = criar_engine()

    with engine.connect() as conn:
        ids_role = dict(conn.execute(text("SELECT nome, id FROM role")).all())

    erros = validar(rel, vws, set(ids_role))
    if erros:
        print("\nA planilha tem problemas. NADA foi gravado no banco:")
        for e in erros:
            print(f"   - {e}")
        sys.exit(1)
    print("   Validação OK")

    # engine.begin() abre uma transação: se qualquer passo falhar,
    # o MySQL desfaz tudo (rollback) e o banco fica como estava antes.
    with engine.begin() as conn:
        gravar(conn, rel, vws, ids_role)
        criar_usuarios_teste(conn, ids_role)

    with engine.connect() as conn:
        mostrar_resumo(conn)

    print("\nCarga concluída.")


if __name__ == "__main__":
    main()