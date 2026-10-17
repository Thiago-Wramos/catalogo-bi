"""
busca.py - a busca por significado, com filtro de permissão e decisão de relevância.

A função principal é consultar(pergunta, login), que devolve uma de três situações:

  "encontrado"      -> há relatórios/views relevantes que o usuário PODE ver
  "sem_acesso"      -> o assunto existe no catálogo, mas fora do perfil do usuário
  "nao_encontrado"  -> o catálogo não tem nada sobre o assunto

No caso "sem_acesso", NENHUM nome de relatório ou view é devolvido:
a busca sem filtro serve só para saber SE o assunto existe.
"""

import os

import ollama
from qdrant_client import models
from sqlalchemy import text

from banco import COLECAO_QDRANT, MODELO_EMBEDDING, criar_engine, criar_qdrant

# Parâmetros de relevância (calibrados com testar_busca.py; ajustáveis no .env)
SCORE_MINIMO = float(os.getenv("SCORE_MINIMO", "0.45"))     # abaixo disso, o catálogo não tem o assunto
MARGEM = float(os.getenv("MARGEM_RELEVANCIA", "0.05"))     # distância tolerada em relação ao melhor resultado

# "indicar": avisa que o assunto existe mas não está liberado (sem dizer onde)
# "neutra":  responde apenas que não encontrou
POLITICA_SEM_ACESSO = os.getenv("POLITICA_SEM_ACESSO", "indicar")


class UsuarioSemAcesso(Exception):
    """Login inexistente, desativado ou sem nenhuma role."""


# =====================================================================
# 1. QUEM É O USUÁRIO E O QUE ELE PODE VER (consulta no MySQL)
# =====================================================================
def obter_acesso(conn, login):
    roles = conn.execute(text("""
        SELECT ro.nome, ro.acesso_total
        FROM usuario u
        JOIN usuario_role ur ON ur.usuario_id = u.id
        JOIN role ro         ON ro.id = ur.role_id
        WHERE u.login = :login AND u.ativo = TRUE
    """), {"login": login}).all()

    if not roles:
        raise UsuarioSemAcesso(f"Usuário '{login}' não existe, está inativo ou não tem role.")

    nomes_roles = [nome for nome, _ in roles]
    acesso_total = any(total for _, total in roles)

    if acesso_total:
        codigos = conn.execute(text("SELECT codigo FROM relatorio")).scalars().all()
    else:
        codigos = conn.execute(text("""
            SELECT DISTINCT r.codigo
            FROM relatorio r
            JOIN relatorio_role rr ON rr.relatorio_id = r.id
            JOIN usuario_role ur   ON ur.role_id = rr.role_id
            JOIN usuario u         ON u.id = ur.usuario_id
            WHERE u.login = :login AND u.ativo = TRUE
        """), {"login": login}).scalars().all()

    return {
        "login": login,
        "roles": nomes_roles,
        "acesso_total": acesso_total,
        "relatorios_visiveis": set(codigos),
    }


# =====================================================================
# 2. PEÇAS DA BUSCA
# =====================================================================
def montar_filtro(acesso):
    """Filtro do Qdrant: só pontos de alguma role do usuário. Admin não tem filtro."""
    if acesso["acesso_total"]:
        return None
    return models.Filter(must=[
        models.FieldCondition(key="roles", match=models.MatchAny(any=acesso["roles"]))
    ])


def limpar_resultado(payload, acesso):
    """
    Segunda barreira: tira da view a lista de relatórios que o usuário
    não pode ver (uma view pode ser usada por várias áreas).
    """
    resultado = dict(payload)
    if resultado["tipo"] == "view":
        resultado["relatorios"] = [
            c for c in resultado["relatorios"] if c in acesso["relatorios_visiveis"]
        ]
    return resultado


def pesquisar(cliente, vetor, filtro, limite):
    return cliente.query_points(
        collection_name=COLECAO_QDRANT,
        query=vetor,
        query_filter=filtro,
        limit=limite,
        with_payload=True,
    ).points


# =====================================================================
# 3. A CONSULTA COMPLETA
# =====================================================================
def consultar(pergunta, login, limite=5, engine=None, cliente=None):
    engine = engine or criar_engine()
    cliente = cliente or criar_qdrant()

    with engine.connect() as conn:
        acesso = obter_acesso(conn, login)

    vetor = ollama.embed(model=MODELO_EMBEDDING, input=pergunta).embeddings[0]

    # Busca 1: no catálogo inteiro, só para saber o melhor score que existe.
    # O resultado dela NUNCA é devolvido nem mostrado; só o número é usado.
    melhor_global = pesquisar(cliente, vetor, filtro=None, limite=1)
    score_global = melhor_global[0].score if melhor_global else 0.0

    # Busca 2: só no que o usuário pode ver.
    visiveis = pesquisar(cliente, vetor, montar_filtro(acesso), limite)
    score_visivel = visiveis[0].score if visiveis else 0.0

    diagnostico = {"score_global": round(score_global, 3), "score_visivel": round(score_visivel, 3)}

    # Regra 1: nada no catálogo inteiro chega perto da pergunta.
    if score_global < SCORE_MINIMO:
        return {"status": "nao_encontrado", "resultados": [], "acesso": acesso, **diagnostico}

    # Regra 2: o melhor resultado do catálogo está fora do alcance do usuário,
    # e o melhor que ele pode ver fica bem atrás.
    if score_visivel < score_global - MARGEM:
        status = "sem_acesso" if POLITICA_SEM_ACESSO == "indicar" else "nao_encontrado"
        return {"status": status, "resultados": [], "acesso": acesso, **diagnostico}

    # Regra 3: encontrado. Mantém só o que está perto do melhor resultado visível.
    resultados = []
    for p in visiveis:
        if p.score >= score_visivel - MARGEM:
            item = limpar_resultado(p.payload, acesso)
            item["score"] = round(p.score, 3)
            resultados.append(item)

    return {"status": "encontrado", "resultados": resultados, "acesso": acesso, **diagnostico}