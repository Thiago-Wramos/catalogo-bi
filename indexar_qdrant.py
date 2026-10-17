"""
indexar_qdrant.py - lê o catálogo do MySQL, gera os embeddings e grava no Qdrant.

Etapas:
  1. Buscar no MySQL relatórios, views e suas roles
  2. Montar um "documento" de texto para cada relatório e cada view
  3. Transformar cada texto em vetor (embedding) com o bge-m3
  4. Recriar a collection no Qdrant e gravar os vetores com as roles

O MySQL é a fonte da verdade. O Qdrant é só um "índice" derivado dele:
pode ser apagado e recriado a qualquer momento rodando este script de novo.
"""

import uuid
from collections import defaultdict

import ollama
from qdrant_client import models
from sqlalchemy import text

from banco import COLECAO_QDRANT, MODELO_EMBEDDING, criar_engine, criar_qdrant


# =====================================================================
# 1. BUSCAR O CATÁLOGO NO MYSQL
# =====================================================================
def buscar_catalogo(conn):
    relatorios = conn.execute(text("""
        SELECT id, codigo, nome, descricao, area, empresa, responsavel
        FROM relatorio
        ORDER BY codigo
    """)).mappings().all()

    views = conn.execute(text("""
        SELECT id, nome, schema_nome, descricao, sensivel
        FROM view_dados
        ORDER BY nome
    """)).mappings().all()

    # Quais roles enxergam cada relatório
    roles_do_rel = defaultdict(list)
    for rel_id, role in conn.execute(text("""
        SELECT rr.relatorio_id, ro.nome
        FROM relatorio_role rr
        JOIN role ro ON ro.id = rr.role_id
    """)):
        roles_do_rel[rel_id].append(role)

    # Quais views cada relatório usa, e quais relatórios usam cada view
    views_do_rel = defaultdict(list)
    rels_da_view = defaultdict(list)
    for rel_id, view_id, view_nome in conn.execute(text("""
        SELECT rv.relatorio_id, rv.view_id, v.nome
        FROM relatorio_view rv
        JOIN view_dados v ON v.id = rv.view_id
    """)):
        views_do_rel[rel_id].append(view_nome)
        rels_da_view[view_id].append(rel_id)

    return relatorios, views, roles_do_rel, views_do_rel, rels_da_view


# =====================================================================
# 2. MONTAR OS DOCUMENTOS
# =====================================================================
def id_estavel(chave):
    """Gera sempre o mesmo id para a mesma chave (ex.: 'relatorio:101')."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"catalogo-bi/{chave}"))


def montar_documentos(relatorios, views, roles_do_rel, views_do_rel, rels_da_view):
    docs = []
    codigo_por_id = {r["id"]: r["codigo"] for r in relatorios}

    for r in relatorios:
        lista_views = sorted(views_do_rel[r["id"]])
        texto = (
            f"Relatório {r['codigo']} - {r['nome']}. "
            f"Área: {r['area']}. Empresa: {r['empresa']}. "
            f"Descrição: {r['descricao']} "
            f"Views utilizadas: {', '.join(lista_views)}."
        )
        docs.append({
            "id": id_estavel(f"relatorio:{r['codigo']}"),
            "texto": texto,
            "payload": {
                "tipo": "relatorio",
                "codigo": r["codigo"],
                "nome": r["nome"],
                "area": r["area"],
                "empresa": r["empresa"],
                "responsavel": r["responsavel"],
                "descricao": r["descricao"],
                "views": lista_views,
                "roles": sorted(roles_do_rel[r["id"]]),
                "texto": texto,
            },
        })

    for v in views:
        # A view é visível para todas as roles dos relatórios que a usam.
        ids_rel = rels_da_view[v["id"]]
        roles = sorted({role for rid in ids_rel for role in roles_do_rel[rid]})

        # De propósito, o texto da view NÃO cita relatórios: uma view pode
        # aparecer em relatórios de outras áreas, e o nome deles não pode
        # chegar até quem não tem acesso. Os relatórios ficam só no payload,
        # e a busca filtra quais o usuário pode ver.
        texto = (
            f"View {v['nome']} (schema {v['schema_nome']}). "
            f"Descrição: {v['descricao']}"
        )
        docs.append({
            "id": id_estavel(f"view:{v['nome']}"),
            "texto": texto,
            "payload": {
                "tipo": "view",
                "nome": v["nome"],
                "schema": v["schema_nome"],
                "descricao": v["descricao"],
                "sensivel": bool(v["sensivel"]),
                "relatorios": sorted(codigo_por_id[rid] for rid in ids_rel),
                "roles": roles,
                "texto": texto,
            },
        })

    return docs


# =====================================================================
# 3. GERAR OS EMBEDDINGS
# =====================================================================
def gerar_embeddings(textos, tamanho_lote=16):
    vetores = []
    for i in range(0, len(textos), tamanho_lote):
        lote = textos[i:i + tamanho_lote]
        resposta = ollama.embed(model=MODELO_EMBEDDING, input=lote)
        vetores.extend(resposta.embeddings)
        print(f"   {len(vetores)}/{len(textos)} textos transformados em vetor")
    return vetores


# =====================================================================
# 4. GRAVAR NO QDRANT
# =====================================================================
def recriar_colecao(cliente, dimensao):
    if cliente.collection_exists(COLECAO_QDRANT):
        cliente.delete_collection(COLECAO_QDRANT)

    cliente.create_collection(
        collection_name=COLECAO_QDRANT,
        vectors_config=models.VectorParams(size=dimensao, distance=models.Distance.COSINE),
    )

    # Índices nos campos usados nos filtros: deixam o filtro por role rápido
    for campo in ("roles", "tipo"):
        cliente.create_payload_index(
            collection_name=COLECAO_QDRANT,
            field_name=campo,
            field_schema=models.PayloadSchemaType.KEYWORD,
        )


def gravar_pontos(cliente, docs, vetores):
    pontos = [
        models.PointStruct(id=d["id"], vector=vetor, payload=d["payload"])
        for d, vetor in zip(docs, vetores)
    ]
    cliente.upsert(collection_name=COLECAO_QDRANT, points=pontos, wait=True)


def contar(cliente, tipo):
    filtro = models.Filter(must=[
        models.FieldCondition(key="tipo", match=models.MatchValue(value=tipo))
    ])
    return cliente.count(COLECAO_QDRANT, count_filter=filtro, exact=True).count


# =====================================================================
# EXECUÇÃO
# =====================================================================
def main():
    print("1/4 Lendo o catálogo do MySQL...")
    with criar_engine().connect() as conn:
        dados = buscar_catalogo(conn)
    relatorios, views = dados[0], dados[1]
    print(f"   {len(relatorios)} relatórios e {len(views)} views")

    print("2/4 Montando os documentos...")
    docs = montar_documentos(*dados)

    print(f"3/4 Gerando embeddings com {MODELO_EMBEDDING}...")
    vetores = gerar_embeddings([d["texto"] for d in docs])

    print(f"4/4 Gravando na collection '{COLECAO_QDRANT}' do Qdrant...")
    cliente = criar_qdrant()
    recriar_colecao(cliente, dimensao=len(vetores[0]))
    gravar_pontos(cliente, docs, vetores)

    print("\nResumo do Qdrant:")
    print(f"   relatórios indexados: {contar(cliente, 'relatorio')}")
    print(f"   views indexadas:      {contar(cliente, 'view')}")
    print(f"   dimensão dos vetores: {len(vetores[0])}")
    print("\nIndexação concluída.")


if __name__ == "__main__":
    main()