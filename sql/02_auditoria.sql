-- =====================================================================
-- Catálogo de Dados com IA - Log de auditoria
-- Arquivo: sql/02_auditoria.sql
--
-- Uma linha por pergunta feita ao assistente.
-- Pode rodar mais de uma vez: "IF NOT EXISTS" pula se a tabela já existir.
-- =====================================================================

CREATE TABLE IF NOT EXISTS auditoria (
    id             BIGINT        NOT NULL AUTO_INCREMENT,
    criado_em      DATETIME(3)   NOT NULL DEFAULT CURRENT_TIMESTAMP(3),  -- com milissegundos

    -- Quem perguntou. Texto, e não chave estrangeira, de propósito:
    -- assim ficam registradas também tentativas com logins inexistentes.
    login          VARCHAR(50)   NOT NULL,
    roles          VARCHAR(200)  NULL,     -- "foto" das roles no momento da pergunta

    pergunta       VARCHAR(500)  NOT NULL,
    status         VARCHAR(20)   NOT NULL, -- encontrado, sem_acesso, nao_encontrado, ajuda, erro...
    origem         VARCHAR(10)   NULL,     -- llm, reserva, fixa
    resposta       TEXT          NULL,
    citados        VARCHAR(500)  NULL,     -- BIs e views citados na resposta

    score_global   DECIMAL(5,3)  NULL,
    score_visivel  DECIMAL(5,3)  NULL,
    tempo_busca    DECIMAL(7,2)  NULL,     -- segundos
    tempo_llm      DECIMAL(7,2)  NULL,     -- segundos
    modelo         VARCHAR(50)   NULL,

    PRIMARY KEY (id),
    KEY idx_auditoria_data   (criado_em),
    KEY idx_auditoria_login  (login),
    KEY idx_auditoria_status (status)
) ENGINE = InnoDB;
