"""
Configuracao compartilhada do ecossistema AgroData Distribuido.

Centraliza: UFs do IBGE, variaveis e produtos da tabela LSPA (SIDRA 6588)
e leitura das variaveis de ambiente injetadas pelo docker-compose.
"""
import os

# ---------------------------------------------------------------
# Dominio SIDRA / LSPA (tabela 6588 - Levantamento Sistematico
# da Producao Agricola)
# ---------------------------------------------------------------

# Codigos das Unidades da Federacao segundo o IBGE (nivel n3)
UFS = {
    "11": "Rondônia", "12": "Acre", "13": "Amazonas", "14": "Roraima",
    "15": "Pará", "16": "Amapá", "17": "Tocantins",
    "21": "Maranhão", "22": "Piauí", "23": "Ceará", "24": "Rio Grande do Norte",
    "25": "Paraíba", "26": "Pernambuco", "27": "Alagoas", "28": "Sergipe",
    "29": "Bahia",
    "31": "Minas Gerais", "32": "Espírito Santo", "33": "Rio de Janeiro",
    "35": "São Paulo",
    "41": "Paraná", "42": "Santa Catarina", "43": "Rio Grande do Sul",
    "50": "Mato Grosso do Sul", "51": "Mato Grosso", "52": "Goiás",
    "53": "Distrito Federal",
}

# Variaveis da LSPA 6588 (descricao amigavel para logs/docs)
VARIAVEIS_LSPA = {
    "35": "Produção",
    "36": "Rendimento médio",
    "109": "Área plantada",
    "216": "Área colhida",
}

# Produtos monitorados por padrao (codigo c48 -> nome)
PRODUTOS_LSPA = {
    "39443": "Soja",
    "39441": "Milho (1ª Safra)",
    "39442": "Milho (2ª Safra)",
    "39456": "Cana-de-açúcar",
    "39432": "Arroz",
    "39454": "Café arábica",
    "39436": "Feijão (1ª Safra)",
    "39445": "Trigo",
    "39467": "Mandioca",
    "39429": "Algodão herbáceo",
}

# ---------------------------------------------------------------
# Variaveis de ambiente (injetadas pelo docker-compose)
# ---------------------------------------------------------------
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "guest")
RABBITMQ_PASS = os.getenv("RABBITMQ_PASS", "guest")

MYSQL_MASTER_HOST = os.getenv("MYSQL_MASTER_HOST", "localhost")
MYSQL_MASTER_PORT = int(os.getenv("MYSQL_MASTER_PORT", "3306"))
MYSQL_SLAVE_HOSTS = os.getenv(
    "MYSQL_SLAVE_HOSTS", "mysql_slave1,mysql_slave2,mysql_slave3"
).split(",")
MYSQL_USER = os.getenv("MYSQL_USER", "appuser")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "apppassword")
MYSQL_ROOT_PASSWORD = os.getenv("MYSQL_ROOT_PASSWORD", "rootpassword")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "agrodb")

SIDRA_TABELA = os.getenv("SIDRA_TABELA", "6588")
SIDRA_PERIODOS = os.getenv("SIDRA_PERIODOS", "last 12")
SIDRA_VARIAVEIS = os.getenv("SIDRA_VARIAVEIS", "35,36,109,216").split(",")
SIDRA_PRODUTOS = os.getenv(
    "SIDRA_PRODUTOS",
    "39443,39441,39442,39456,39432,39454,39436,39445,39467,39429",
).split(",")

FILA_TAREFAS = "sidra_tasks"
FILA_DLQ = "sidra_dead_letter"
