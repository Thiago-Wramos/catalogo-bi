"""
rodar_bateria.py - bateria oficial de testes do assistente.

Lê as perguntas de testes/bateria.csv, roda cada uma pelo fluxo completo
(o mesmo da interface, sem a tela de login) e mede:

  - Decisão:   o status saiu como o esperado? (encontrado, sem_acesso, ajuda...)
  - Fonte:     quando a resposta devia apontar um relatório/view, apontou um certo?
  - Vazamento: a resposta citou algum relatório ou view fora do perfil?
  - Lista:     no "listar", vieram TODOS os relatórios do perfil?
  - Tempo:     quanto cada resposta levou

Salva tudo em testes/resultados/bateria_<data>.csv, com uma coluna vazia
"avaliacao_humana" para você ler as respostas e dar a sua nota.

Uso (Anaconda Prompt):
    python rodar_bateria.py
"""

import csv
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import bindparam, text

from assistente import aquecer, citacoes, responder
from banco import criar_engine, criar_qdrant
from busca import obter_acesso

PASTA = Path(__file__).parent / "testes"
ARQUIVO_BATERIA = PASTA / "bateria.csv"
PASTA_RESULTADOS = PASTA / "resultados"


# =====================================================================
# APOIO
# =====================================================================
def ler_casos():
    # utf-8-sig: aceita o arquivo mesmo se ele for salvo pelo Excel
    with open(ARQUIVO_BATERIA, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def views_visiveis(engine, codigos):
    """Views usadas pelos relatórios que o usuário pode ver."""
    sql = text("""
        SELECT DISTINCT v.nome
        FROM view_dados v
        JOIN relatorio_view rv ON rv.view_id = v.id
        JOIN relatorio r       ON r.id = rv.relatorio_id
        WHERE r.codigo IN :codigos
    """).bindparams(bindparam("codigos", expanding=True))
    with engine.connect() as conn:
        return set(conn.execute(sql, {"codigos": sorted(codigos)}).scalars())


def nomes_do_catalogo(engine):
    """Todos os códigos de BI e nomes de views que EXISTEM no catálogo."""
    with engine.connect() as conn:
        codigos = set(conn.execute(text("SELECT codigo FROM relatorio")).scalars())
        views = set(conn.execute(text("SELECT nome FROM view_dados")).scalars())
    return codigos, views


def perfil(engine, login, cache):
    """Acesso do usuário (relatórios e views visíveis), calculado uma vez por login."""
    if login not in cache:
        with engine.connect() as conn:
            acesso = obter_acesso(conn, login)
        acesso["views_visiveis"] = views_visiveis(engine, acesso["relatorios_visiveis"])
        cache[login] = acesso
    return cache[login]


# =====================================================================
# AVALIAÇÃO DE UM CASO
# =====================================================================
def avaliar(caso, r, acesso, catalogo):
    codigos, views = citacoes(r["resposta"] or "")
    citados = codigos | views
    esperado = caso["status_esperado"].strip()
    deve_citar = {x.strip() for x in (caso["deve_citar"] or "").split(",") if x.strip()}

    # Decisão: "*" quer dizer "qualquer status serve" (só a segurança é avaliada)
    decisao_ok = esperado == "*" or r["status"] == esperado

    # Fonte: só se aplica quando o caso diz o que deveria ser citado
    fonte_ok = bool(citados & deve_citar) if deve_citar else None

    # Vazamento: citou relatório ou view que EXISTE no catálogo e o perfil não enxerga?
    # (Um nome inexistente, repetido de volta ao usuário, não revela nada.)
    codigos_existentes, views_existentes = catalogo
    vazados = sorted(
        ((codigos & codigos_existentes) - acesso["relatorios_visiveis"])
        | ((views & views_existentes) - acesso["views_visiveis"])
    )

    # Lista: no "listar", vieram todos os relatórios do perfil?
    lista_ok = acesso["relatorios_visiveis"] <= codigos if r["status"] == "lista" else None

    return {
        "decisao_ok": decisao_ok,
        "fonte_ok": fonte_ok,
        "vazamentos": ", ".join(vazados),
        "lista_ok": lista_ok,
        "citados": ", ".join(sorted(citados)),
    }


# =====================================================================
# EXECUÇÃO
# =====================================================================
def main():
    engine, cliente = criar_engine(), criar_qdrant()
    casos = ler_casos()

    with engine.connect() as conn:
        ja_existentes = conn.execute(text("SELECT COUNT(*) FROM auditoria")).scalar()
    if ja_existentes:
        print(f"Aviso: a tabela auditoria já tem {ja_existentes} registros de antes desta bateria.")
        print("Para o relatório final, limpe com TRUNCATE TABLE auditoria; e rode de novo.\n")

    # Aquece os modelos antes: a partida a frio não pode contaminar o tempo da 1ª pergunta
    print("Aquecendo os modelos...")
    aquecer()

    cache_perfis = {}
    catalogo = nomes_do_catalogo(engine)
    linhas = []
    for caso in casos:
        acesso = perfil(engine, caso["login"], cache_perfis)

        inicio = time.perf_counter()
        r = responder(caso["pergunta"], caso["login"], engine=engine, cliente=cliente)
        tempo_total = round(time.perf_counter() - inicio, 2)

        av = avaliar(caso, r, acesso, catalogo)
        linhas.append({
            "id": int(caso["id"]),
            "categoria": caso["categoria"],
            "login": caso["login"],
            "pergunta": caso["pergunta"],
            "status_esperado": caso["status_esperado"],
            "status_obtido": r["status"],
            "origem": r["origem"],
            **av,
            "score_global": r["score_global"],
            "score_visivel": r["score_visivel"],
            "tempo_total": tempo_total,
            "tempo_busca": r["tempo_busca"],
            "tempo_llm": r["tempo_llm"],
            "resposta": r["resposta"],
            "avaliacao_humana": "",  # preencha: correta / parcial / incorreta
        })

        marca = "OK  " if av["decisao_ok"] and av["fonte_ok"] is not False and not av["vazamentos"] else "ERRO"
        print(f"{marca} #{caso['id']:>2} [{caso['categoria']:<18}] {r['status']:<15} "
              f"{tempo_total:>5}s  {caso['pergunta'][:55]}")

    df = pd.DataFrame(linhas)
    mostrar_resumo(df)

    PASTA_RESULTADOS.mkdir(parents=True, exist_ok=True)
    arquivo = PASTA_RESULTADOS / f"bateria_{datetime.now():%Y%m%d_%H%M}.csv"
    # ; e vírgula decimal: abre direto no Excel em português
    df.to_csv(arquivo, sep=";", decimal=",", index=False, encoding="utf-8-sig")
    print(f"\nResultados salvos em: {arquivo}")


def pct(serie):
    """Percentual de acertos, ignorando os casos em que a métrica não se aplica."""
    valores = serie.dropna()
    return f"{100 * valores.astype(bool).mean():.0f}% ({int(valores.astype(bool).sum())}/{len(valores)})" if len(valores) else "-"


def mostrar_resumo(df):
    print("\n" + "=" * 78)
    print("RESUMO GERAL")
    print(f"   Casos:                 {len(df)}")
    print(f"   Decisão correta:       {pct(df['decisao_ok'])}")
    print(f"   Fonte correta:         {pct(df['fonte_ok'])}")
    print(f"   Listas completas:      {pct(df['lista_ok'])}")
    print(f"   Casos com vazamento:   {(df['vazamentos'] != '').sum()}")
    origem = df["origem"].value_counts().to_dict()
    print(f"   Origem das respostas:  Qwen aprovado {origem.get('llm', 0)} | "
          f"reserva {origem.get('reserva', 0)} | fixa {origem.get('fixa', 0)}")

    print("\nPOR CATEGORIA")
    for categoria, grupo in df.groupby("categoria", sort=False):
        print(f"   {categoria:<20} decisão {pct(grupo['decisao_ok']):<14} fonte {pct(grupo['fonte_ok'])}")

    print("\nTEMPO DE RESPOSTA (segundos)")
    com_qwen = df[df["origem"].isin(["llm", "reserva"])]["tempo_total"]
    sem_qwen = df[df["origem"] == "fixa"]["tempo_total"]
    if len(com_qwen):
        print(f"   Com o Qwen:  média {com_qwen.mean():.2f} | máximo {com_qwen.max():.2f}")
    if len(sem_qwen):
        print(f"   Sem o Qwen:  média {sem_qwen.mean():.2f} | máximo {sem_qwen.max():.2f}")

    erros = df[~df["decisao_ok"] | (df["fonte_ok"] == False) | (df["vazamentos"] != "")]  # noqa: E712
    if len(erros):
        print("\nCASOS COM ERRO")
        for _, e in erros.iterrows():
            print(f"   #{e['id']} esperado={e['status_esperado']} obtido={e['status_obtido']} "
                  f"citou=[{e['citados']}] vazou=[{e['vazamentos']}]")
            print(f"       {e['pergunta']}")


if __name__ == "__main__":
    main()