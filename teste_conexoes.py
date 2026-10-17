"""
Etapa 2.6 - Teste de fumaça
Confere se o Python consegue falar com as 3 peças do projeto:
  1. MySQL   (no Docker, porta 3306)
  2. Qdrant  (no Docker, porta 6333)
  3. Ollama  (no Windows, porta 11434) - chat com o Qwen e embedding com o bge-m3

Não grava nada em lugar nenhum: só "pergunta" e mostra o resultado.
"""

import os
import time

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from qdrant_client import QdrantClient
import ollama

# Lê o arquivo .env e coloca as variáveis disponíveis para o os.getenv()
load_dotenv()


# ---------------------------------------------------------------- MySQL
def testar_mysql():
    # URL.create monta o endereço de conexão com segurança,
    # mesmo que a senha tenha caracteres especiais (!, @, #...)
    url = URL.create(
        "mysql+pymysql",
        username=os.getenv("MYSQL_USER"),
        password=os.getenv("MYSQL_PASSWORD"),
        host="127.0.0.1",
        port=3306,
        database=os.getenv("MYSQL_DATABASE"),
    )
    engine = create_engine(url)
    with engine.connect() as conn:
        versao = conn.execute(text("SELECT VERSION()")).scalar()
    print(f"   Conectado! Versão do MySQL: {versao}")


# ---------------------------------------------------------------- Qdrant
def testar_qdrant():
    cliente = QdrantClient(
        url="http://localhost:6333",
        api_key=os.getenv("QDRANT_API_KEY"),
    )
    colecoes = cliente.get_collections().collections
    print(f"   Conectado! Collections existentes: {len(colecoes)}")


# ---------------------------------------------------------------- Ollama (chat)
def testar_ollama_chat():
    inicio = time.time()
    resposta = ollama.chat(
        model="qwen3.5:9b",
        messages=[{"role": "user", "content": "Responda só com a palavra: funcionando"}],
        think=False,  # desliga o "raciocínio interno" para responder rápido
    )
    segundos = time.time() - inicio
    print(f"   Resposta do Qwen: {resposta.message.content.strip()}")
    print(f"   Tempo: {segundos:.1f} s")


# ---------------------------------------------------------------- Ollama (embedding)
def testar_ollama_embedding():
    resultado = ollama.embed(model="bge-m3", input="Onde encontro dados de vendas?")
    vetor = resultado.embeddings[0]
    print(f"   Vetor gerado com {len(vetor)} números")
    print(f"   Primeiros 5: {[round(x, 4) for x in vetor[:5]]}")


# ---------------------------------------------------------------- Execução
testes = [
    ("MySQL", testar_mysql),
    ("Qdrant", testar_qdrant),
    ("Ollama - chat (Qwen)", testar_ollama_chat),
    ("Ollama - embedding (bge-m3)", testar_ollama_embedding),
]

for nome, funcao in testes:
    print(f"\n[{nome}]")
    try:
        funcao()
        print("   OK")
    except Exception as erro:
        # Se um teste falhar, mostra o erro e continua para o próximo
        print(f"   FALHOU: {type(erro).__name__}: {erro}")

print("\nFim dos testes.")
