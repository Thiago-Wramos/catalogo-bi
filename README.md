# Catálogo de Dados com IA

Assistente de chat que responde, em português, **em qual relatório de BI e em qual view** está a informação procurada, mostrando apenas o que o perfil (role) do usuário pode ver.

- **LLM local:** Qwen 3.5 9B via Ollama (nenhum dado vai para APIs externas)
- **Busca por significado:** embeddings bge-m3 no Qdrant, com filtro de permissão aplicado *antes* da IA
- **Catálogo, usuários, roles e auditoria:** MySQL
- **Interface:** Streamlit, com login (senhas em bcrypt)

```
Usuário ──► Streamlit (app) ──► MySQL   (catálogo, usuários, roles, auditoria)
                │          └──► Qdrant  (vetores, filtrados por role)
                └─────────────► Ollama  (bge-m3 + Qwen, na GPU)
```

---

## Pré-requisitos

| Item | Observação |
|---|---|
| Docker | Docker Desktop (Windows/Mac, uso pessoal) ou Docker Engine (Linux/servidor) |
| Ollama | Com GPU NVIDIA de pelo menos 12 GB de VRAM para o Qwen 3.5 9B |
| Python 3.12 | Só para os scripts de carga, indexação e testes (a aplicação roda no Docker) |
| Git | Para baixar o projeto |

---

## Instalação do zero

> Comandos de `docker` e `git` no **PowerShell**; comandos de `python` no ambiente Python do projeto (ex.: Anaconda Prompt com `conda activate catalogo-bi`).

**1. Baixe o projeto e crie o `.env`**
```powershell
git clone <endereço-do-repositório>
cd catalogo-bi
Copy-Item .env.example .env      # depois edite o .env e troque senhas e chaves
```
O MySQL lê usuário e senha **só na primeira subida**. Defina-os antes do passo 3.

**2. Baixe os modelos**
```powershell
ollama pull qwen3.5:9b
ollama pull bge-m3
```

**3. Suba MySQL, Qdrant e a aplicação**
```powershell
docker compose up -d --build
docker compose ps                # espere o mysql ficar "healthy"
```

**4. Crie as tabelas** (rode cada script **uma vez**, na ordem)
```powershell
Get-Content -Raw sql\01_schema.sql   | docker exec -i catalogo-mysql sh -c 'mysql -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE"'
Get-Content -Raw sql\02_auditoria.sql | docker exec -i catalogo-mysql sh -c 'mysql -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE"'
Get-Content -Raw sql\03_login.sql    | docker exec -i catalogo-mysql sh -c 'mysql -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE"'
```
No Linux, troque `Get-Content -Raw arquivo |` por `cat arquivo |`.

**5. Prepare o ambiente Python dos scripts**
```
conda create -n catalogo-bi python=3.12 -c conda-forge --override-channels
conda activate catalogo-bi
pip install -r requirements.txt
```

**6. Carregue o catálogo e gere os vetores**

Coloque a planilha em `dados/Catalogo_Relatorios_Mascarado.xlsx` (abas `Catalogo` e `Dicionario_Views`) e rode:
```
python carga_catalogo.py         # planilha -> MySQL (valida antes de gravar)
python indexar_qdrant.py         # MySQL -> embeddings -> Qdrant
```

**7. Crie o primeiro administrador**
```
python criar_admin.py
```

**8. Acesse** `http://127.0.0.1:8501`, entre com o administrador e crie os demais usuários em **Administração**.

---

## Operação do dia a dia

| Situação | O que fazer |
|---|---|
| Ligar tudo | Abrir o Docker e o Ollama → `docker compose up -d` |
| Desligar | `docker compose stop` (os dados ficam nos volumes) |
| Mudou código da aplicação ou `requirements.txt` | `docker compose up -d --build` |
| Mudou `.env` ou `docker-compose.yml` | `docker compose up -d` |
| Mudou a planilha do catálogo | `python carga_catalogo.py` e depois `python indexar_qdrant.py` |
| Ver erros da aplicação | `docker compose logs app` |
| Resumo de uso e de logins | `python relatorio_auditoria.py` |
| Rodar a bateria de testes | `python rodar_bateria.py` (resultado em `testes/resultados/`) |

> ⚠️ `docker compose down -v` **apaga os volumes** (banco e vetores). Para desligar, use `stop` ou `down` **sem** `-v`.

**Desenvolvendo a interface:** para não reconstruir a imagem a cada ajuste, pare só o container da aplicação (`docker compose stop app`) e rode `streamlit run app.py` localmente; ele recarrega ao salvar. No fim, `docker compose up -d --build`.

---

## Estrutura

| Arquivo | Papel |
|---|---|
| `app.py` | Interface: login, chat e administração de usuários |
| `assistente.py` | Fluxo da resposta: intenções → busca → Qwen → conferência → auditoria |
| `busca.py` | Busca com filtro de permissão; decide *encontrado / sem acesso / não encontrado*; busca por nome exato |
| `intencoes.py` | Reconhece ajuda, cumprimentos, agradecimentos e "listar" |
| `usuarios.py` | Login (bcrypt) e administração de usuários e roles |
| `auditoria.py` | Grava cada pergunta e resposta na tabela `auditoria` |
| `banco.py` | Conexões com MySQL e Qdrant e configurações gerais |
| `carga_catalogo.py` | Planilha → MySQL |
| `indexar_qdrant.py` | MySQL → embeddings → Qdrant |
| `criar_admin.py` | Cria ou promove um administrador pelo terminal |
| `rodar_bateria.py` + `testes/bateria.csv` | Bateria de testes com métricas de decisão, fonte, vazamento e tempo |
| `relatorio_auditoria.py` | Resumo de uso a partir da auditoria |
| `sql/` | Criação das tabelas (rodar em ordem, uma vez) |
| `testar_*.py`, `teste_conexoes.py` | Testes rápidos de cada parte |

---

## Segurança, em resumo

- O filtro de permissão é aplicado **na busca**: o modelo nunca recebe relatórios fora do perfil do usuário.
- Toda resposta do Qwen é conferida: se citar relatório ou view fora do contexto, é descartada.
- Senhas guardadas apenas como hash bcrypt; mensagem de erro de login genérica.
- Todas as portas publicadas só em `127.0.0.1`; o `.env` não entra no Git nem na imagem.
- A autenticação está na interface: qualquer nova porta de entrada (ex.: uma API) precisa autenticar também.
