"""
app.py - interface de chat do catálogo de dados (Streamlit).

Rodar (Anaconda Prompt, com o ambiente catalogo-bi ativado):
    streamlit run app.py

Protótipo: a escolha do usuário na barra lateral SIMULA o login.
Na empresa, ela é substituída pelo login real (AD/SSO), sem mudar o resto.
"""

import streamlit as st
from sqlalchemy import text

from assistente import aquecer, responder
from banco import MODELO_CHAT, criar_engine, criar_qdrant

st.set_page_config(page_title="Catálogo de Dados", page_icon="📚", layout="centered")


# =====================================================================
# RECURSOS COMPARTILHADOS (criados uma vez por processo)
# =====================================================================
@st.cache_resource
def conexoes():
    return criar_engine(), criar_qdrant()


@st.cache_resource(show_spinner="Carregando os modelos na GPU (só na primeira vez)...")
def aquecer_modelos():
    aquecer()
    return True


@st.cache_data(ttl=60)
def listar_usuarios():
    engine, _ = conexoes()
    with engine.connect() as conn:
        return conn.execute(text("""
            SELECT u.login, u.nome, GROUP_CONCAT(ro.nome ORDER BY ro.nome SEPARATOR ', ') AS roles
            FROM usuario u
            JOIN usuario_role ur ON ur.usuario_id = u.id
            JOIN role ro         ON ro.id = ur.role_id
            WHERE u.ativo = TRUE
            GROUP BY u.login, u.nome
            ORDER BY u.login
        """)).mappings().all()


# =====================================================================
# INICIALIZAÇÃO
# =====================================================================
engine, cliente = conexoes()

try:
    aquecer_modelos()
except Exception as erro:
    st.error(
        "Não consegui carregar os modelos. Confira se o Ollama está aberto "
        f"e se os modelos foram baixados.\n\nDetalhe: {erro}"
    )
    st.stop()

if "historico" not in st.session_state:
    st.session_state.historico = []
    st.session_state.usuario_atual = None


# =====================================================================
# BARRA LATERAL
# =====================================================================
with st.sidebar:
    st.header("Usuário")
    usuarios = listar_usuarios()
    opcoes = {u["login"]: f"{u['nome']} ({u['roles']})" for u in usuarios}
    login = st.selectbox("Entrar como", options=list(opcoes), format_func=opcoes.get)
    st.caption("Protótipo: esta escolha simula o login da empresa.")

    # Trocar de usuário apaga a conversa: as respostas do perfil anterior
    # não podem continuar visíveis para o próximo.
    if login != st.session_state.usuario_atual:
        st.session_state.historico = []
        st.session_state.usuario_atual = login

    if st.button("Nova conversa", use_container_width=True):
        st.session_state.historico = []
        st.rerun()

    st.divider()
    mostrar_detalhes = st.toggle("Mostrar detalhes técnicos", value=False)
    st.caption(f"Modelo: {MODELO_CHAT}")


# =====================================================================
# CHAT
# =====================================================================
st.title("📚 Catálogo de Dados")
st.caption("Pergunte em qual relatório e em qual view está a informação que você procura.")


def mostrar_detalhes_tecnicos(d):
    with st.expander("Detalhes técnicos"):
        st.write(f"**Status:** {d['status']}  |  **Origem:** {d['origem']}")
        st.write(f"**Busca:** {d['tempo_busca']} s  |  **Qwen:** {d['tempo_llm']} s")
        if d.get("score_global") is not None:
            st.write(f"**Score global:** {d['score_global']}  |  **Score visível:** {d['score_visivel']}")
        if d.get("fontes"):
            st.write("**Contexto enviado ao modelo:**")
            for linha in d["fontes"]:
                st.text(linha)


for msg in st.session_state.historico:
    with st.chat_message(msg["papel"]):
        st.markdown(msg["texto"])
        if mostrar_detalhes and msg.get("detalhes"):
            mostrar_detalhes_tecnicos(msg["detalhes"])

pergunta = st.chat_input("Ex.: em qual relatório encontro dados de salário?")

if pergunta:
    st.session_state.historico.append({"papel": "user", "texto": pergunta})
    with st.chat_message("user"):
        st.markdown(pergunta)

    with st.chat_message("assistant"):
        with st.spinner("Consultando o catálogo..."):
            try:
                saida = responder(pergunta, login, engine=engine, cliente=cliente)
                texto = saida["resposta"]
            except Exception:
                saida = None
                texto = ("Não consegui responder agora. Confira se o Docker e o Ollama "
                         "estão ligados e tente de novo. Se persistir, fale com a equipe de BI.")
        st.markdown(texto)
        if mostrar_detalhes and saida:
            mostrar_detalhes_tecnicos(saida)

    st.session_state.historico.append({"papel": "assistant", "texto": texto, "detalhes": saida})
