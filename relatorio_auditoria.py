"""
relatorio_auditoria.py - resumo do uso do assistente, a partir da tabela de auditoria.

Uso:
  python relatorio_auditoria.py
"""

from sqlalchemy import text

from banco import criar_engine

CONSULTAS = {
    "Perguntas por status": """
        SELECT status, COUNT(*) AS total
        FROM auditoria
        GROUP BY status
        ORDER BY total DESC
    """,
    "Origem das respostas": """
        SELECT COALESCE(origem, '-') AS origem, COUNT(*) AS total
        FROM auditoria
        GROUP BY origem
        ORDER BY total DESC
    """,
    "Tempos médios (segundos)": """
        SELECT
            ROUND(AVG(tempo_busca), 2)                                   AS busca_media,
            ROUND(AVG(CASE WHEN origem = 'llm' THEN tempo_llm END), 2)   AS qwen_media,
            ROUND(MAX(tempo_llm), 2)                                     AS qwen_maximo
        FROM auditoria
        WHERE status = 'encontrado'
    """,
    "Perguntas por usuário": """
        SELECT a.login, COALESCE(u.nome, '(não cadastrado)') AS nome, COUNT(*) AS total
        FROM auditoria a
        LEFT JOIN usuario u ON u.login = a.login
        GROUP BY a.login, u.nome
        ORDER BY total DESC
    """,
    "Tentativas de login": """
        SELECT login,
               SUM(sucesso)      AS com_sucesso,
               SUM(NOT sucesso)  AS com_falha,
               DATE_FORMAT(MAX(criado_em), '%d/%m %H:%i') AS ultima
        FROM auditoria_login
        GROUP BY login
        ORDER BY com_falha DESC
    """,
    "Últimas 10 perguntas": """
        SELECT DATE_FORMAT(criado_em, '%d/%m %H:%i') AS quando, login, status,
               LEFT(pergunta, 50) AS pergunta
        FROM auditoria
        ORDER BY id DESC
        LIMIT 10
    """,
}


def main():
    with criar_engine().connect() as conn:
        total = conn.execute(text("SELECT COUNT(*) FROM auditoria")).scalar()
        print(f"Total de perguntas registradas: {total}")

        for titulo, sql in CONSULTAS.items():
            resultado = conn.execute(text(sql))
            colunas = list(resultado.keys())
            print(f"\n{titulo}")
            print("   " + " | ".join(colunas))
            for linha in resultado:
                print("   " + " | ".join("-" if v is None else str(v) for v in linha))


if __name__ == "__main__":
    main()