"""
testar_intencoes.py - calibra o LIMIAR_INTENCAO.

Mostra o score de frases que DEVEM ser reconhecidas como ajuda/cumprimento
e de perguntas de catálogo que NÃO podem ser. O limiar bom fica entre os dois grupos.
"""

from intencoes import LIMIAR_INTENCAO, classificar

# Frases que NÃO estão na lista de exemplos, mas devem ser reconhecidas
DEVEM_RECONHECER = [
    ("ajuda", "pra que você serve?"),
    ("ajuda", "quais coisas você sabe responder?"),
    ("ajuda", "como funciona esse assistente?"),
    ("ajuda", "o que dá pra perguntar aqui?"),
    ("saudacao", "opa"),
    ("saudacao", "olá, bom dia"),
    ("saudacao", "oii"),
    ("agradecimento", "brigado"),
    ("agradecimento", "show, valeu"),
    # Frases NOVAS: não foram usadas para ajustar os exemplos.
    # Se só as antigas passarem, os exemplos "decoraram" o teste.
    ("ajuda", "você responde o quê?"),
    ("ajuda", "quais são suas capacidades?"),
    ("ajuda", "não entendi como usar isso"),
    ("saudacao", "Opa!!"),
    ("saudacao", "boa tarde, tudo certo?"),
    ("agradecimento", "vlw"),
    ("agradecimento", "obrigado pela ajuda, era isso"),
    # Listar (frases que não estão nos exemplos)
    ("listar", "que relatórios estão liberados pra mim?"),
    ("listar", "me mostra tudo que eu posso acessar"),
    ("listar", "quais são os meus BIs?"),
]

# Perguntas de catálogo: precisam seguir para a busca normal
NAO_PODEM_RECONHECER = [
    "Onde eu consigo a informação de vendas?",
    "Quais relatórios usam a VW_SALARIO?",
    "O que tem no Painel de Pessoas?",
    "Oi, onde vejo dados de salário?",
    "Quais dados de RH existem?",
    "Qual relatório mostra o que a empresa faz com o orçamento?",
    "Obrigado, e onde vejo o headcount?",
    "Opa, quais relatórios mostram vendas?",
    "Como funciona o cálculo da margem de contribuição?",
    "O que o relatório de chamados de TI mostra?",
    # Parecem "listar", mas pedem um ASSUNTO: precisam ir para a busca
    "Quais relatórios mostram vendas?",
    "Quais relatórios têm dados de salário?",
    "Que relatório eu uso para ver o headcount?",
    # Têm palavra de posse E de assunto: a regra 2 precisa mandar para a busca
    "Eu tenho acesso a dados de vendas?",
    "Posso ver informações sobre salário?",
]


def main():
    print(f"Limiar atual: {LIMIAR_INTENCAO}\n")

    print("DEVEM ser reconhecidas:")
    menor_positivo = 1.0
    erros = 0
    for esperada, frase in DEVEM_RECONHECER:
        r = classificar(frase)
        ok = r["intencao"] == esperada
        erros += not ok
        menor_positivo = min(menor_positivo, r["score"]) if r["candidata"] == esperada else menor_positivo
        print(f"  {'OK  ' if ok else 'ERRO'} [{r['score']}] {frase!r:<42} -> {r['candidata']}")

    print("\nNÃO podem ser reconhecidas (seguem para o catálogo):")
    maior_negativo = 0.0
    bloqueadas = 0
    for frase in NAO_PODEM_RECONHECER:
        r = classificar(frase)
        ok = r["intencao"] is None
        erros += not ok
        if r["bloqueada_pela_regra"]:
            bloqueadas += 1
            nota = "  <- bloqueada pela regra do 'listar'"
        else:
            maior_negativo = max(maior_negativo, r["score"])
            nota = ""
        print(f"  {'OK  ' if ok else 'ERRO'} [{r['score']}] {frase!r:<42} "
              f"(parecida com: {r['frase_mais_parecida']!r}){nota}")

    print("\n" + "-" * 70)
    print(f"Perguntas de catálogo barradas pela regra do 'listar': {bloqueadas}")
    print(f"Menor score entre as que devem ser reconhecidas:        {menor_positivo}")
    print(f"Maior score entre as de catálogo (fora as barradas):    {maior_negativo}")
    if menor_positivo > maior_negativo:
        print(f"Separadas. Folga entre os grupos: {round(menor_positivo - maior_negativo, 3)}")
    else:
        print("Os grupos se SOBREPÕEM mesmo com a regra. Revise os exemplos.")
    print(f"Erros com o limiar atual: {erros}")


if __name__ == "__main__":
    main()