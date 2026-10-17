# Imagem da aplicação (interface Streamlit + lógica do assistente)

# Python "slim": a mesma versão usada no desenvolvimento, sem extras desnecessários
FROM python:3.12-slim

# Sem arquivos .pyc e com os logs saindo na hora (sem ficar presos em buffer)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 1) Primeiro só as dependências: se o código mudar e elas não,
#    o Docker reaproveita esta camada e o build fica muito mais rápido
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 2) Depois o código (o .dockerignore define o que fica de fora, como o .env)
COPY . .

# 3) Não rodar como root dentro do container
RUN useradd --create-home --uid 1000 appuser
USER appuser

EXPOSE 8501

# O Docker confere sozinho se a aplicação está respondendo
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health')"

# Dentro do container o Streamlit PRECISA escutar em 0.0.0.0 (todas as interfaces do container).
# Quem limita o acesso à sua máquina é o "127.0.0.1:8501:8501" do docker-compose.
CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]
