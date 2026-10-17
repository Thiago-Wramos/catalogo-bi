"""
app.py - interface do catálogo de dados (Streamlit), com login.

Rodar (Anaconda Prompt, com o ambiente catalogo-bi ativado):
    streamlit run app.py

Páginas:
  - Login        -> todo mundo começa aqui
  - Chat         -> qualquer usuário logado
  - Administração -> só quem tem a role Admin
"""

import streamlit as st

from assistente import aquecer, responder
from banco import MODELO_CHAT, criar_engine, criar_qdrant
from usuarios import (
    ErroUsuario, atualizar_usuario, autenticar, criar_usuario, eh_admin,
    listar_roles, listar_usuarios, redefinir_senha,
)

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


AJUDA_ROLES = "Um usuário pode ter várias roles. A role Admin já dá acesso a tudo e não pode ser combinada com outras."


def avisar(texto):
    """Guarda um aviso para mostrar depois do st.rerun() (que apaga a tela)."""
    st.session_state.aviso = texto


def mostrar_aviso():
    if st.session_state.get("aviso"):
        st.success(st.session_state.pop("aviso"))


engine, cliente = conexoes()


# =====================================================================
# LOGIN
# =====================================================================
def pagina_login():
    st.title("📚 Catálogo de Dados")
    st.caption("Entre com o seu usuário para consultar o catálogo.")

    with st.form("login"):
        login = st.text_input("Login")
        senha = st.text_input("Senha", type="password")
        entrar = st.form_submit_button("Entrar", use_container_width=True)

    if entrar:
        usuario = autenticar(engine, login, senha)
        if usuario:
            st.session_state.usuario = usuario
            st.session_state.historico = []
            st.session_state.pagina = "Chat"  # todo login começa no chat
            st.rerun()
        else:
            # Mesma mensagem para login inexistente e senha errada (não revela qual foi)
            st.error("Login ou senha incorretos.")


# =====================================================================
# CHAT
# =====================================================================
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


def pagina_chat(usuario, mostrar_detalhes):
    st.title("📚 Catálogo de Dados")
    st.caption("Pergunte em qual relatório e em qual view está a informação que você procura.")

    for msg in st.session_state.historico:
        with st.chat_message(msg["papel"]):
            st.markdown(msg["texto"])
            if mostrar_detalhes and msg.get("detalhes"):
                mostrar_detalhes_tecnicos(msg["detalhes"])

    pergunta = st.chat_input("Ex.: em qual relatório encontro dados de salário?")
    if not pergunta:
        return

    st.session_state.historico.append({"papel": "user", "texto": pergunta})
    with st.chat_message("user"):
        st.markdown(pergunta)

    with st.chat_message("assistant"):
        with st.spinner("Consultando o catálogo..."):
            try:
                saida = responder(pergunta, usuario["login"], engine=engine, cliente=cliente)
                texto = saida["resposta"]
            except Exception:
                saida = None
                texto = ("Não consegui responder agora. Confira se o Docker e o Ollama "
                         "estão ligados e tente de novo. Se persistir, fale com a equipe de BI.")
        st.markdown(texto)
        if mostrar_detalhes and saida:
            mostrar_detalhes_tecnicos(saida)

    st.session_state.historico.append({"papel": "assistant", "texto": texto, "detalhes": saida})


# =====================================================================
# ADMINISTRAÇÃO
# =====================================================================
def pagina_admin(usuario):
    # Confere no banco a cada abertura: se o acesso foi retirado, a página fecha na hora
    if not eh_admin(engine, usuario["login"]):
        st.error("Acesso restrito a administradores.")
        return

    st.title("Administração de usuários")
    mostrar_aviso()

    usuarios = listar_usuarios(engine)
    roles = listar_roles(engine)

    st.dataframe(
        [{
            "Login": u["login"],
            "Nome": u["nome"],
            "Roles": u["roles"] or "-",
            "Ativo": "Sim" if u["ativo"] else "Não",
            "Senha definida": "Sim" if u["tem_senha"] else "Não",
            "Último acesso": u["ultimo_login"].strftime("%d/%m/%Y %H:%M") if u["ultimo_login"] else "-",
        } for u in usuarios],
        hide_index=True,
    )

    aba_novo, aba_editar, aba_senha = st.tabs(["Novo usuário", "Editar usuário", "Redefinir senha"])

    with aba_novo:
        with st.form("novo_usuario", clear_on_submit=True):
            login = st.text_input("Login", help="Letras minúsculas, números, ponto, hífen ou sublinhado.")
            nome = st.text_input("Nome completo")
            senha = st.text_input("Senha provisória", type="password", help="Mínimo de 8 caracteres.")
            escolhidas = st.multiselect("Roles", roles, help=AJUDA_ROLES)
            if st.form_submit_button("Criar usuário"):
                try:
                    criar_usuario(engine, login, nome, senha, escolhidas)
                    avisar(f"Usuário '{login.strip().lower()}' criado.")
                    st.rerun()
                except ErroUsuario as erro:
                    st.error(str(erro))

    with aba_editar:
        alvo = st.selectbox("Usuário", [u["login"] for u in usuarios], key="editar_alvo")
        dados = next(u for u in usuarios if u["login"] == alvo)
        # A chave do formulário inclui o login: ao trocar de usuário, os campos recarregam
        with st.form(f"editar_{alvo}"):
            nome = st.text_input("Nome completo", value=dados["nome"])
            escolhidas = st.multiselect("Roles", roles, default=dados["lista_roles"], help=AJUDA_ROLES)
            ativo = st.checkbox("Ativo", value=bool(dados["ativo"]))
            if st.form_submit_button("Salvar alterações"):
                try:
                    atualizar_usuario(engine, alvo, nome, escolhidas, ativo, quem_edita=usuario["login"])
                    avisar(f"Usuário '{alvo}' atualizado.")
                    st.rerun()
                except ErroUsuario as erro:
                    st.error(str(erro))

    with aba_senha:
        alvo_senha = st.selectbox("Usuário", [u["login"] for u in usuarios], key="senha_alvo")
        with st.form("redefinir_senha", clear_on_submit=True):
            nova = st.text_input("Nova senha", type="password")
            repetida = st.text_input("Repita a nova senha", type="password")
            if st.form_submit_button("Redefinir senha"):
                if nova != repetida:
                    st.error("As senhas não conferem.")
                else:
                    try:
                        redefinir_senha(engine, alvo_senha, nova)
                        avisar(f"Senha de '{alvo_senha}' redefinida.")
                        st.rerun()
                    except ErroUsuario as erro:
                        st.error(str(erro))


# =====================================================================
# FLUXO PRINCIPAL
# =====================================================================
try:
    aquecer_modelos()
except Exception as erro:
    st.error(
        "Não consegui carregar os modelos. Confira se o Ollama está aberto "
        f"e se os modelos foram baixados.\n\nDetalhe: {erro}"
    )
    st.stop()

usuario = st.session_state.get("usuario")

if not usuario:
    pagina_login()
    st.stop()

with st.sidebar:
    st.subheader(usuario["nome"])
    st.caption(f"{usuario['login']} · {', '.join(usuario['roles'])}")

    # A página atual fica guardada na sessão (definida como "Chat" a cada login).
    # Quem não é admin fica sempre no chat, mesmo que a sessão diga outra coisa.
    if not usuario["admin"]:
        st.session_state.pagina = "Chat"
    pagina = st.session_state.get("pagina", "Chat")

    if usuario["admin"]:
        for nome_pagina, icone in (("Chat", "💬"), ("Administração", "⚙️")):
            if st.button(
                f"{icone} {nome_pagina}",
                use_container_width=True,
                type="primary" if pagina == nome_pagina else "secondary",  # destaca a página atual
            ):
                st.session_state.pagina = nome_pagina
                st.rerun()
        st.divider()

    mostrar_detalhes = False
    if pagina == "Chat":
        if st.button("Nova conversa", use_container_width=True):
            st.session_state.historico = []
            st.rerun()
        mostrar_detalhes = st.toggle("Mostrar detalhes técnicos", value=False)

    st.divider()
    if st.button("Sair", use_container_width=True):
        st.session_state.clear()  # apaga login E histórico da conversa
        st.rerun()
    st.caption(f"Modelo: {MODELO_CHAT}")

if pagina == "Administração":
    pagina_admin(usuario)
else:
    pagina_chat(usuario, mostrar_detalhes)