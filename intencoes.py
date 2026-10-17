"""
intencoes.py - reconhece perguntas que NÃO são sobre o catálogo:
pedidos de ajuda ("o que você pode fazer?"), cumprimentos e agradecimentos.

Como funciona: cada intenção tem frases de exemplo. A pergunta do usuário
vira vetor (bge-m3) e é comparada com os vetores dessas frases. Se ficar
parecida o bastante com alguma, a intenção é reconhecida.

Vantagem sobre procurar palavras exatas: "pra que você serve?" é reconhecida
mesmo sem estar na lista, porque o SIGNIFICADO é parecido com "o que você faz?".
"""

import math
import os
import re

import ollama

from banco import MODELO_EMBEDDING

# Abaixo deste valor, a pergunta segue para a busca normal no catálogo.
# Calibrado com testar_intencoes.py; ajustável no .env.
LIMIAR_INTENCAO = float(os.getenv("LIMIAR_INTENCAO", "0.70"))

# Mensagens curtas e informais: o embedding se confunde com elas,
# então são reconhecidas por comparação EXATA (a mensagem inteira, não um pedaço).
# "opa, onde vejo vendas?" NÃO casa aqui, porque não é só "opa".
EXATAS = {
    "saudacao": {"oi", "oii", "oiii", "ola", "olá", "opa", "eae", "eai", "e ai", "e aí",
                 "salve", "fala", "bom dia", "boa tarde", "boa noite"},
    "agradecimento": {"obrigado", "obrigada", "brigado", "brigada", "obg", "vlw", "valeu",
                      "brigadão", "obrigadão", "show", "top", "beleza", "blz", "massa"},
    "ajuda": {"ajuda", "help", "socorro", "menu"},
}

EXEMPLOS = {
    "ajuda": [
        "o que você pode fazer?",
        "o que você faz?",
        "como você funciona?",
        "como funciona isso aqui?",
        "como eu uso você?",
        "quais são as suas funções?",
        "o que você sabe?",
        "quais perguntas você responde?",
        "me explica como te usar",
        "me ajuda",
        "para que você serve?",
        "que tipo de pergunta eu posso fazer?",
    ],
    "saudacao": [
        "oi",
        "olá",
        "bom dia",
        "boa tarde",
        "boa noite",
        "e aí, tudo bem?",
    ],
    "agradecimento": [
        "obrigado",
        "obrigada",
        "valeu",
        "muito obrigado pela ajuda",
        "perfeito, obrigado",
    ],
}

_vetores_exemplos = None  # calculados uma vez só, na primeira pergunta


def _normalizar(vetor):
    tamanho = math.sqrt(sum(x * x for x in vetor))
    return [x / tamanho for x in vetor]


def _similaridade(a, b):
    """Similaridade de cosseno entre dois vetores já normalizados."""
    return sum(x * y for x, y in zip(a, b))


def _carregar_exemplos():
    global _vetores_exemplos
    if _vetores_exemplos is None:
        frases = [(intencao, f) for intencao, lista in EXEMPLOS.items() for f in lista]
        vetores = ollama.embed(model=MODELO_EMBEDDING, input=[f for _, f in frases]).embeddings
        _vetores_exemplos = [
            (intencao, frase, _normalizar(v)) for (intencao, frase), v in zip(frases, vetores)
        ]
    return _vetores_exemplos


def _limpar(texto):
    """'Opa!!' -> 'opa' ; 'E aí,  tudo?' -> 'e aí tudo'"""
    texto = re.sub(r"[^\w\s]", " ", texto.lower())
    return " ".join(texto.split())


def classificar(pergunta):
    # 1) Comparação exata: rápida e 100% previsível para mensagens curtas
    limpa = _limpar(pergunta)
    for intencao, palavras in EXATAS.items():
        if limpa in palavras:
            return {"intencao": intencao, "score": 1.0, "candidata": intencao,
                    "frase_mais_parecida": limpa}

    # 2) Comparação por significado, para o resto
    vetor = _normalizar(ollama.embed(model=MODELO_EMBEDDING, input=pergunta).embeddings[0])

    score, intencao, frase = max(
        (_similaridade(vetor, v), intencao, frase) for intencao, frase, v in _carregar_exemplos()
    )

    return {
        "intencao": intencao if score >= LIMIAR_INTENCAO else None,
        "score": round(score, 3),
        "candidata": intencao,
        "frase_mais_parecida": frase,
    }