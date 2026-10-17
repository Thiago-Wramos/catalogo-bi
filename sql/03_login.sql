-- =====================================================================
-- Catálogo de Dados com IA - Login
-- Arquivo: sql/03_login.sql
--
-- ATENÇÃO: rode UMA vez só. O MySQL não tem "ADD COLUMN IF NOT EXISTS";
-- rodando de novo, o ALTER TABLE dá erro "Duplicate column name"
-- (não estraga nada, só não faz nada).
-- =====================================================================

-- Senha (só o hash bcrypt, nunca a senha em si) e data do último acesso
ALTER TABLE usuario
    ADD COLUMN senha_hash   VARCHAR(100) NULL AFTER nome,
    ADD COLUMN ultimo_login DATETIME     NULL;

-- Toda tentativa de login, com sucesso ou não.
-- Serve para perceber, por exemplo, alguém testando senhas.
CREATE TABLE IF NOT EXISTS auditoria_login (
    id         BIGINT       NOT NULL AUTO_INCREMENT,
    criado_em  DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    login      VARCHAR(50)  NOT NULL,   -- texto: registra também logins que não existem
    sucesso    BOOLEAN      NOT NULL,
    PRIMARY KEY (id),
    KEY idx_login_data  (criado_em),
    KEY idx_login_login (login)
) ENGINE = InnoDB;
