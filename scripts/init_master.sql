-- =============================================================================
-- AgroData Distribuído — Inicialização do MySQL Master (Etapa 2)
-- =============================================================================
-- Este script cria:
--   1. O banco de dados `agrodata`
--   2. A tabela principal de dados coletados (`producao_agricola`)
--   3. A tabela de log das coletas (`coletas_log`)
--   4. O usuário de aplicação (`agro`) e o usuário de replicação (`repl`)
-- =============================================================================

CREATE DATABASE IF NOT EXISTS agrodata
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE agrodata;

-- -----------------------------------------------------------------------------
-- 1. Tabela principal de dados coletados do IBGE/SIDRA (Tabela 6588 - LSPA)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS producao_agricola (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    uf VARCHAR(10) NOT NULL COMMENT 'Sigla ou código da UF (ex: SP, MT, PR)',
    produto VARCHAR(100) NOT NULL COMMENT 'Nome ou código do produto agrícola (ex: soja, milho)',
    periodo VARCHAR(20) NOT NULL COMMENT 'Período/ano ou mês da safra (ex: 2024, 202401)',
    producao DECIMAL(18, 2) NULL DEFAULT NULL COMMENT 'Produção (toneladas)',
    rendimento DECIMAL(18, 2) NULL DEFAULT NULL COMMENT 'Rendimento médio da produção (kg/ha)',
    area_plantada DECIMAL(18, 2) NULL DEFAULT NULL COMMENT 'Área plantada (hectares)',
    area_colhida DECIMAL(18, 2) NULL DEFAULT NULL COMMENT 'Área colhida (hectares)',
    worker_id VARCHAR(50) NULL DEFAULT 'unknown' COMMENT 'Identificador do worker que realizou a gravação',
    coletado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Data/hora da última atualização',
    UNIQUE KEY uk_uf_produto_periodo (uf, produto, periodo),
    INDEX idx_uf (uf),
    INDEX idx_produto (produto),
    INDEX idx_periodo (periodo),
    INDEX idx_worker_id (worker_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- 2. Tabela de log das coletas (auditoria de execução por worker)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS coletas_log (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    worker_id VARCHAR(50) NOT NULL COMMENT 'Identificador do worker (ex: worker1, worker2, worker3)',
    uf VARCHAR(10) NULL DEFAULT NULL COMMENT 'UF processada na tarefa (opcional)',
    status VARCHAR(30) NOT NULL COMMENT 'Status da coleta (ex: SUCESSO, ERRO, EM_ANDAMENTO)',
    mensagem TEXT NULL COMMENT 'Detalhes ou mensagem de erro da coleta',
    data_coleta TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'Data/hora do registro do log',
    INDEX idx_log_worker (worker_id),
    INDEX idx_log_status (status),
    INDEX idx_log_data (data_coleta)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- 3. Usuário da aplicação (leitura e escrita) e Usuário de Replicação
--    Usa mysql_native_password para máxima compatibilidade com clientes Python
--    e com os containers MySQL Slaves sem necessidade de SSL/RSA handshake.
-- -----------------------------------------------------------------------------
CREATE USER IF NOT EXISTS 'agro'@'%' IDENTIFIED WITH mysql_native_password BY 'agropass';
ALTER USER 'agro'@'%' IDENTIFIED WITH mysql_native_password BY 'agropass';
GRANT ALL PRIVILEGES ON agrodata.* TO 'agro'@'%';
GRANT REPLICATION CLIENT ON *.* TO 'agro'@'%';

CREATE USER IF NOT EXISTS 'repl'@'%' IDENTIFIED WITH mysql_native_password BY 'replpass';
ALTER USER 'repl'@'%' IDENTIFIED WITH mysql_native_password BY 'replpass';
GRANT REPLICATION SLAVE, REPLICATION CLIENT ON *.* TO 'repl'@'%';

FLUSH PRIVILEGES;
