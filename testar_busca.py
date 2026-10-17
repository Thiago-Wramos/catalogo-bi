"""
testar_busca.py - testa a busca SEM o LLM: mostra a decisão para cada usuário.

Uso:
  python testar_busca.py                         -> roda a bateria de testes
  python testar_busca.py usr_rh "sua pergunta"   -> testa uma pergunta só
"""

import sys

from banco import criar_engine, criar_qdrant
from busca import MARGEM, SCORE_MINIMO, UsuarioSemAcesso, consultar

USUARIOS = ["usr_rh", "usr_comercial", "usr_corporativo", "usr_admin"]

# (pergunta, {login: status esperado})
CASOS = [
    ("Onde eu consigo a informação de vendas?",
     {"usr_rh": "sem_acesso", "usr_comercial": "encontrado",
      "usr_corporativo": "sem_acesso", "usr_admin": "encontrado"}),
    ("Preciso de uma base com dados de salário",
     {"usr_rh": "encontrado", "usr_comercial": "sem_acesso",
      "usr_corporativo": "sem_acesso", "usr_admin": "encontrado"}),
    ("Onde vejo o headcount da empresa?",
     {"usr_rh": "encontrado", "usr_comercial": "sem_acesso",
      "usr_corporativo": "encontrado", "usr_admin": "encontrado"}),
    ("Quanto devemos em empréstimos e financiamentos?",
     {"usr_rh": "sem_acesso", "usr_comercial": "sem_acesso",
      "usr_corporativo": "encontrado", "usr_admin": "encontrado"}),
    ("Quero acompanhar os chamados de TI",
     {"usr_rh": "sem_acesso", "usr_comercial": "sem_acesso",
      "usr_corporativo": "sem_acesso", "usr_admin": "encontrado"}),
    # Fora do catálogo: ninguém deve encontrar nada
    ("Qual a previsão do tempo para amanhã?",
     {u: "nao_encontrado" for u in USUARIOS}),
    ("Qual é o cardápio do refeitório hoje?",
     {u: "nao_encontrado" for u in USUARIOS}),
]

ROTULO = {
    "encontrado": "ENCONTRADO",
    "sem_acesso": "SEM ACESSO (existe, mas fora do perfil)",
    "nao_encontrado": "NÃO ENCONTRADO no catálogo",
}


def mostrar(r):
    print(f"     {ROTULO[r['status']]}   "
          f"(melhor global: {r['score_global']} | melhor visível: {r['score_visivel']})")
    for item in r["resultados"]:
        if item["tipo"] == "relatorio":
            print(f"       [{item['score']}] Relatório {item['codigo']} - {item['nome']}")
        else:
            rels = ", ".join(item["relatorios"]) or "nenhum visível"
            aviso = "  ⚠ sensível" if item["sensivel"] else ""
            print(f"       [{item['score']}] View {item['nome']}  (nos relatórios: {rels}){aviso}")


def verificar_vazamento(r):
    """Conta resultados que o usuário NÃO deveria ver. O esperado é sempre zero."""
    acesso = r["acesso"]
    if acesso["acesso_total"]:
        return 0
    problemas = 0
    for item in r["resultados"]:
        if not set(item["roles"]) & set(acesso["roles"]):
            problemas += 1
        if item["tipo"] == "view" and not set(item["relatorios"]) <= acesso["relatorios_visiveis"]:
            problemas += 1
    return problemas


def bateria():
    engine, cliente = criar_engine(), criar_qdrant()
    acertos = total = vazamentos = 0

    print(f"Parâmetros: SCORE_MINIMO={SCORE_MINIMO}  MARGEM={MARGEM}")
    for pergunta, esperado in CASOS:
        print("\n" + "=" * 78)
        print(f"PERGUNTA: {pergunta}")
        for login in USUARIOS:
            r = consultar(pergunta, login, engine=engine, cliente=cliente)
            ok = r["status"] == esperado[login]
            acertos += ok
            total += 1
            vazamentos += verificar_vazamento(r)
            marca = "OK " if ok else "ERRO (esperado: " + esperado[login] + ")"
            print(f"\n  {login:<16} {marca}")
            mostrar(r)

    print("\n" + "=" * 78)
    print(f"Decisões corretas: {acertos}/{total}")
    print(f"Vazamentos de permissão: {vazamentos}")


def pergunta_unica(login, pergunta):
    try:
        r = consultar(pergunta, login)
    except UsuarioSemAcesso as erro:
        sys.exit(str(erro))
    print(f"{login}  (roles: {', '.join(r['acesso']['roles'])})")
    mostrar(r)
    print(f"\nVazamentos: {verificar_vazamento(r)}")


if __name__ == "__main__":
    if len(sys.argv) == 3:
        pergunta_unica(sys.argv[1], sys.argv[2])
    else:
        bateria()