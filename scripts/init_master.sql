-- ============================================================
-- Init do MySQL MASTER
-- 1) Cria o usuario de replicacao usado pelos slaves
-- 2) Cria o schema do dominio (LSPA - IBGE/SIDRA)
-- ============================================================

CREATE USER IF NOT EXISTS 'repl'@'%' IDENTIFIED WITH mysql_native_password BY 'replpassword';
ALTER USER 'repl'@'%' IDENTIFIED WITH mysql_native_password BY 'replpassword';
GRANT REPLICATION SLAVE ON *.* TO 'repl'@'%';
FLUSH PRIVILEGES;

CREATE TABLE IF NOT EXISTS agrodb.lspa_registros (
    id            BIGINT AUTO_INCREMENT PRIMARY KEY,
    uf_cod        VARCHAR(2)   NOT NULL,
    uf_nome       VARCHAR(100) NOT NULL,
    variavel_cod  VARCHAR(10)  NOT NULL,
    variavel      VARCHAR(60)  NOT NULL,
    periodo       VARCHAR(6)   NOT NULL COMMENT 'AAAAMM',
    periodo_nome  VARCHAR(30)  NOT NULL,
    produto_cod   VARCHAR(10)  NOT NULL,
    produto       VARCHAR(80)  NOT NULL,
    unidade       VARCHAR(60)  NOT NULL,
    valor         DOUBLE       NULL COMMENT 'NULL quando SIDRA retorna .. / ... / -',
    worker_id     VARCHAR(80)  NOT NULL COMMENT 'Container do worker que processou',
    coletado_em   TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_registro (uf_cod, variavel_cod, periodo, produto_cod)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS agrodb.coletas (
    id            BIGINT AUTO_INCREMENT PRIMARY KEY,
    tarefa_id     VARCHAR(64)  NOT NULL,
    uf_cod        VARCHAR(2)   NOT NULL,
    status        VARCHAR(20)  NOT NULL COMMENT 'SUCESSO | ERRO',
    registros     INT          DEFAULT 0,
    duracao_ms    INT          DEFAULT 0,
    worker_id     VARCHAR(80)  NOT NULL,
    mensagem      TEXT         NULL,
    executado_em  TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    KEY ix_coletas_tarefa (tarefa_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
