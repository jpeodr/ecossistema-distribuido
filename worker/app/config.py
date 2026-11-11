"""Configuracao do worker (espelho da config do manager).

Os servicos sao independentes: cada um carrega seu proprio modulo de
configuracao a partir das variaveis de ambiente do docker-compose.
"""
import os

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "guest")
RABBITMQ_PASS = os.getenv("RABBITMQ_PASS", "guest")

MYSQL_MASTER_HOST = os.getenv("MYSQL_MASTER_HOST", "localhost")
MYSQL_MASTER_PORT = int(os.getenv("MYSQL_MASTER_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "appuser")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "apppassword")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "agrodb")

SIDRA_TABELA = os.getenv("SIDRA_TABELA", "6588")
SIDRA_PERIODOS = os.getenv("SIDRA_PERIODOS", "last 12")
SIDRA_VARIAVEIS = os.getenv("SIDRA_VARIAVEIS", "35,36,109,216").split(",")

# Threads por worker (paralelismo interno, visto em aula)
WORKER_THREADS = int(os.getenv("WORKER_THREADS", "4"))

FILA_TAREFAS = "sidra_tasks"
FILA_DLQ = "sidra_dead_letter"
