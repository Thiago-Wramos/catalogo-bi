"""
busca.py - a busca por significado, com filtro de permissão e decisão de relevância.

A função principal é consultar(pergunta, login), que devolve uma de três situações:

  "encontrado"      -> há relatórios/views relevantes que o usuário PODE ver
  "sem_acesso"      -> o assunto existe no catálogo, mas fora do perfil do usuário
  "nao_encontrado"  -> o catálogo não tem nada sobre o assunto

No caso "sem_acesso", NENHUM nome de relatório ou view é devolvido:
a busca sem filtro serve só para saber SE o assunto existe.
"""

import difflib
import os
import re

import ollama
from qdrant_client import models
from sqlalchemy import bindparam, text

from banco import COLECAO_QDRANT, MODELO_EMBEDDING, criar_engine, criar_qdrant
from indexar_qdrant import id_estavel

# Nomes exatos citados na pergunta: "VW_SALARIO", "BI 201"
RE_VIEW = re.compile(r"\bVW_[A-Z0-9_]+\b")
RE_BI = re.compile(r"\bBI\s*(\d{3})\b", re.IGNORECASE)

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


def views_visiveis(engine, acesso):
    """Nomes das views usadas pelos relatórios que o usuário pode ver."""
    if not acesso["relatorios_visiveis"]:
        return []
    sql = text("""
        SELECT DISTINCT v.nome
        FROM view_dados v
        JOIN relatorio_view rv ON rv.view_id = v.id
        JOIN relatorio r       ON r.id = rv.relatorio_id
        WHERE r.codigo IN :codigos
    """).bindparams(bindparam("codigos", expanding=True))
    with engine.connect() as conn:
        return conn.execute(sql, {"codigos": sorted(acesso["relatorios_visiveis"])}).scalars().all()


def busca_exata(engine, cliente, pergunta, acesso):
    """
    Se a pergunta cita um nome exato (VW_... ou BI 123), resolve pelo nome,
    sem embedding. Devolve None só quando a pergunta não cita nenhum nome.
    """
    views = set(RE_VIEW.findall(pergunta.upper()))
    codigos = set(RE_BI.findall(pergunta))
    if not views and not codigos:
        return None

    ids = [id_estavel(f"view:{v}") for v in views] + [id_estavel(f"relatorio:{c}") for c in codigos]
    pontos = cliente.retrieve(collection_name=COLECAO_QDRANT, ids=ids, with_payload=True)

    if not pontos:
        # Nenhum nome citado existe. Sugere nomes parecidos, mas SÓ entre as views
        # que o usuário enxerga: sugerir uma view de outra área seria um vazamento.
        candidatas = views_visiveis(engine, acesso)
        sugestoes = sorted({
            s for v in views for s in difflib.get_close_matches(v, candidatas, n=2, cutoff=0.8)
        })
        citados = sorted(views) + [f"BI {c}" for c in sorted(codigos)]
        return {"status": "nao_encontrado", "resultados": [], "score_global": 0.0, "score_visivel": 0.0,
                "nomes_inexistentes": citados, "sugestoes": sugestoes}

    # Mesma regra do filtro do Qdrant: alguma role em comum, ou acesso total
    visiveis = [
        p for p in pontos
        if acesso["acesso_total"] or set(p.payload["roles"]) & set(acesso["roles"])
    ]
    if visiveis:
        resultados = [{**limpar_resultado(p.payload, acesso), "score": 1.0} for p in visiveis]
        return {"status": "encontrado", "resultados": resultados,
                "score_global": 1.0, "score_visivel": 1.0}

    status = "sem_acesso" if POLITICA_SEM_ACESSO == "indicar" else "nao_encontrado"
    return {"status": status, "resultados": [], "score_global": 1.0, "score_visivel": 0.0}


# =====================================================================
# 3. A CONSULTA COMPLETA
# =====================================================================
def consultar(pergunta, login, limite=5, engine=None, cliente=None):
    engine = engine or criar_engine()
    cliente = cliente or criar_qdrant()

    with engine.connect() as conn:
        acesso = obter_acesso(conn, login)

    # Nome exato citado na pergunta? Resolve pelo nome, sem embedding.
    exata = busca_exata(engine, cliente, pergunta, acesso)
    if exata:
        return {**exata, "acesso": acesso}

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