"""
banco.py - conexões com os bancos do projeto, reaproveitadas por todos os scripts.

  - criar_engine(): MySQL (catálogo, usuários, roles)
  - criar_qdrant(): Qdrant (vetores para a busca por significado)

Por que um arquivo só para isso: as conexões vão ser usadas pela carga,
pela indexação, pela busca e pelo chat. Se um dia mudar o servidor ou a
senha, muda aqui (ou no .env) e vale para todo mundo.
"""

import os
import warnings

from dotenv import load_dotenv
from qdrant_client import QdrantClient
from sqlalchemy import create_engine
from sqlalchemy.engine import URL

load_dotenv()

# Configurações gerais (podem ser trocadas no .env sem mexer no código)
COLECAO_QDRANT = os.getenv("QDRANT_COLLECTION", "catalogo")
MODELO_EMBEDDING = os.getenv("EMBEDDING_MODEL", "bge-m3")
MODELO_CHAT = os.getenv("CHAT_MODEL", "qwen3.5:9b")


def criar_engine():
    url = URL.create(
        "mysql+pymysql",
        username=os.getenv("MYSQL_USER"),
        password=os.getenv("MYSQL_PASSWORD"),
        host=os.getenv("MYSQL_HOST", "127.0.0.1"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        database=os.getenv("MYSQL_DATABASE"),
        query={"charset": "utf8mb4"},  # garante acentos e cedilha corretos
    )
    # pool_pre_ping: testa a conexão antes de usar (evita erro se o MySQL reiniciou)
    return create_engine(url, pool_pre_ping=True)


def criar_qdrant():
    url = os.getenv("QDRANT_URL", "http://localhost:6333")

    # No protótipo a conexão é http (sem criptografia), então o Qdrant avisa
    # que a chave vai "aberta". Como tudo fica na própria máquina, escondemos
    # esse aviso SÓ para endereços locais. Num servidor, o aviso volta a aparecer.
    if url.startswith(("http://localhost", "http://127.0.0.1")):
        warnings.filterwarnings("ignore", message="Api key is used with an insecure connection")

    return QdrantClient(url=url, api_key=os.getenv("QDRANT_API_KEY"))