import os

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_PORT = int(os.getenv("RABBITMQ_PORT", "5672"))
RABBITMQ_USER = os.getenv("RABBITMQ_DEFAULT_USER", "guest")
RABBITMQ_PASS = os.getenv("RABBITMQ_DEFAULT_PASS", "guest")
RABBITMQ_QUEUE = "sidra_tasks"
RABBITMQ_DLQ = "sidra_tasks_dlq"

MYSQL_USER = os.getenv("MYSQL_USER", "agro")
MYSQL_PASS = os.getenv("MYSQL_PASSWORD", "agropass")
MYSQL_DB = os.getenv("MYSQL_DATABASE", "agrodata")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))

MASTER = os.getenv("MYSQL_MASTER_HOST", "mysql_master")
SLAVES = [
    os.getenv("MYSQL_SLAVE1_HOST", "mysql_slave1"),
    os.getenv("MYSQL_SLAVE2_HOST", "mysql_slave2"),
    os.getenv("MYSQL_SLAVE3_HOST", "mysql_slave3"),
]

SIDRA_TABELA = os.getenv("SIDRA_TABELA", "6588")
SIDRA_PRODUTOS = os.getenv("SIDRA_PRODUTOS", "soja,milho,arroz,feijao,trigo,cafe").split(",")
SIDRA_PERIODOS = os.getenv("SIDRA_PERIODOS", "2023,2024,2025").split(",")

UFS = [
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA",
    "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN",
    "RS", "RO", "RR", "SC", "SP", "SE", "TO"
]