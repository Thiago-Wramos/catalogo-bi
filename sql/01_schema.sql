-- =====================================================================
-- Catálogo de Dados com IA - Estrutura do banco (MySQL 8.4)
-- Arquivo: sql/01_schema.sql
--
-- Pode rodar quantas vezes quiser: "IF NOT EXISTS" e "INSERT IGNORE"
-- fazem o script pular o que já existe, sem apagar nada.
-- =====================================================================


-- ---------------------------------------------------------------------
-- 1) ROLE: os perfis de acesso (RH, Comercial, Corporativo, Admin)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS role (
    id            INT          NOT NULL AUTO_INCREMENT,
    nome          VARCHAR(50)  NOT NULL,
    acesso_total  BOOLEAN      NOT NULL DEFAULT FALSE,  -- TRUE = enxerga todos os relatórios
    PRIMARY KEY (id),
    UNIQUE KEY uk_role_nome (nome)                      -- não deixa cadastrar a mesma role 2 vezes
) ENGINE = InnoDB;


-- ---------------------------------------------------------------------
-- 2) RELATORIO: um BI por linha
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS relatorio (
    id              INT           NOT NULL AUTO_INCREMENT,
    codigo          VARCHAR(10)   NOT NULL,   -- ex.: '101'
    nome            VARCHAR(150)  NOT NULL,   -- ex.: 'Painel de Pessoas'
    descricao       TEXT          NULL,
    area            VARCHAR(100)  NULL,
    empresa         VARCHAR(100)  NULL,
    responsavel     VARCHAR(150)  NULL,
    desenvolvedor   VARCHAR(150)  NULL,
    qtd_acessos     INT           NULL,
    dt_solicitacao  DATETIME      NULL,
    dt_publicacao   DATETIME      NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_relatorio_codigo (codigo)
) ENGINE = InnoDB;


-- ---------------------------------------------------------------------
-- 3) VIEW_DADOS: as views do data warehouse
--    (não se chama "view" porque VIEW é palavra reservada do SQL)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS view_dados (
    id           INT           NOT NULL AUTO_INCREMENT,
    nome         VARCHAR(100)  NOT NULL,   -- ex.: 'VW_SALARIO'
    schema_nome  VARCHAR(50)   NULL,       -- ex.: 'DW_RH'
    descricao    TEXT          NULL,
    sensivel     BOOLEAN       NOT NULL DEFAULT FALSE,
    PRIMARY KEY (id),
    UNIQUE KEY uk_view_nome (nome)
) ENGINE = InnoDB;


-- ---------------------------------------------------------------------
-- 4) USUARIO: quem usa o chat (no protótipo, usuários de teste)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS usuario (
    id         INT           NOT NULL AUTO_INCREMENT,
    login      VARCHAR(50)   NOT NULL,
    nome       VARCHAR(150)  NOT NULL,
    ativo      BOOLEAN       NOT NULL DEFAULT TRUE,    -- desativar em vez de apagar
    criado_em  TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_usuario_login (login)
) ENGINE = InnoDB;


-- ---------------------------------------------------------------------
-- 5) TABELAS DE LIGAÇÃO (relações "muitos para muitos")
-- ---------------------------------------------------------------------

-- Qual relatório usa qual view
CREATE TABLE IF NOT EXISTS relatorio_view (
    relatorio_id  INT NOT NULL,
    view_id       INT NOT NULL,
    PRIMARY KEY (relatorio_id, view_id),        -- impede a mesma ligação duplicada
    KEY idx_rv_view (view_id),                  -- acelera "quais relatórios usam a view X?"
    CONSTRAINT fk_rv_relatorio FOREIGN KEY (relatorio_id) REFERENCES relatorio (id) ON DELETE CASCADE,
    CONSTRAINT fk_rv_view      FOREIGN KEY (view_id)      REFERENCES view_dados (id) ON DELETE CASCADE
) ENGINE = InnoDB;

-- Qual relatório é liberado para qual role
CREATE TABLE IF NOT EXISTS relatorio_role (
    relatorio_id  INT NOT NULL,
    role_id       INT NOT NULL,
    PRIMARY KEY (relatorio_id, role_id),
    KEY idx_rr_role (role_id),
    CONSTRAINT fk_rr_relatorio FOREIGN KEY (relatorio_id) REFERENCES relatorio (id) ON DELETE CASCADE,
    CONSTRAINT fk_rr_role      FOREIGN KEY (role_id)      REFERENCES role (id)      ON DELETE CASCADE
) ENGINE = InnoDB;

-- Qual usuário tem qual role
CREATE TABLE IF NOT EXISTS usuario_role (
    usuario_id  INT NOT NULL,
    role_id     INT NOT NULL,
    PRIMARY KEY (usuario_id, role_id),
    KEY idx_ur_role (role_id),
    CONSTRAINT fk_ur_usuario FOREIGN KEY (usuario_id) REFERENCES usuario (id) ON DELETE CASCADE,
    CONSTRAINT fk_ur_role    FOREIGN KEY (role_id)    REFERENCES role (id)    ON DELETE CASCADE
) ENGINE = InnoDB;


-- ---------------------------------------------------------------------
-- 6) DADOS INICIAIS: as 4 roles
--    Admin vê tudo (acesso_total = TRUE); as demais só o que for ligado
--    a elas na tabela relatorio_role.
-- ---------------------------------------------------------------------
INSERT IGNORE INTO role (nome, acesso_total) VALUES
    ('RH',          FALSE),
    ('Comercial',   FALSE),
    ('Corporativo', FALSE),
    ('Admin',       TRUE);