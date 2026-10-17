"""
auditoria.py - grava cada pergunta e resposta na tabela "auditoria" do MySQL.

Regra de ouro: uma falha ao gravar o log NUNCA pode derrubar a resposta
ao usuário. Se o log falhar, o erro é mostrado no terminal e o chat segue.
"""

import sys

from sqlalchemy import text

SQL_INSERIR = text("""
    INSERT INTO auditoria
        (login, roles, pergunta, status, origem, resposta, citados,
         score_global, score_visivel, tempo_busca, tempo_llm, modelo)
    VALUES
        (:login, :roles, :pergunta, :status, :origem, :resposta, :citados,
         :score_global, :score_visivel, :tempo_busca, :tempo_llm, :modelo)
""")


def registrar(engine, login, pergunta, saida, modelo, citados):
    try:
        with engine.begin() as conn:
            conn.execute(SQL_INSERIR, {
                "login": (login or "")[:50],
                "roles": saida.get("roles"),
                "pergunta": (pergunta or "")[:500],   # corta perguntas longas demais
                "status": saida.get("status") or "desconhecido",
                "origem": saida.get("origem"),
                "resposta": saida.get("resposta"),
                "citados": citados[:500] if citados else None,
                "score_global": saida.get("score_global"),
                "score_visivel": saida.get("score_visivel"),
                "tempo_busca": saida.get("tempo_busca"),
                "tempo_llm": saida.get("tempo_llm"),
                "modelo": modelo,
            })
    except Exception as erro:
        print(f"[auditoria] Falha ao gravar o log: {type(erro).__name__}: {erro}", file=sys.stderr)
