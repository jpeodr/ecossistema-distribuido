import os

# =============================================================================
# AgroData Distribuído — Configuração do Worker (Etapa 4)
# =============================================================================
# Lê as variáveis de ambiente (docker-compose / .env) e centraliza o domínio
# da coleta: códigos IBGE das UFs e categorias SIDRA dos produtos monitorados.
# =============================================================================

# -----------------------------------------------------------------------------
# Identidade e paralelismo interno deste nó
# -----------------------------------------------------------------------------
WORKER_ID = os.getenv("WORKER_ID", "worker-local")
WORKER_THREADS = int(os.getenv("WORKER_THREADS", "4"))  # threads do ThreadPoolExecutor

# -----------------------------------------------------------------------------
# RabbitMQ — fila de tarefas, exchange de dead-letter e fila de erros (DLQ)
# -----------------------------------------------------------------------------
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_PORT = int(os.getenv("RABBITMQ_PORT", "5672"))
RABBITMQ_USER = os.getenv("RABBITMQ_DEFAULT_USER", "guest")
RABBITMQ_PASS = os.getenv("RABBITMQ_DEFAULT_PASS", "guest")
RABBITMQ_QUEUE = "sidra_tasks"    # fila principal (1 tarefa por UF)
RABBITMQ_DLQ = "sidra_tasks_dlq"  # fila de erros (dead-letter queue)
RABBITMQ_DLX = "dlx"              # exchange que roteia mensagens rejeitadas para a DLQ

# -----------------------------------------------------------------------------
# MySQL Master — única porta de escrita do ecossistema (replicado para os slaves)
# -----------------------------------------------------------------------------
MYSQL_MASTER_HOST = os.getenv("MYSQL_MASTER_HOST", "mysql_master")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "agro")
MYSQL_PASS = os.getenv("MYSQL_PASSWORD", "agropass")
MYSQL_DB = os.getenv("MYSQL_DATABASE", "agrodata")

# -----------------------------------------------------------------------------
# Política de retentativas da tarefa (falha -> devolve à fila -> DLQ)
# -----------------------------------------------------------------------------
MAX_TENTATIVAS = int(os.getenv("WORKER_MAX_TENTATIVAS", "2"))  # após N tentativas -> DLQ
RETRY_DELAY = int(os.getenv("WORKER_RETRY_DELAY", "2"))        # segundos antes de devolver à fila

# -----------------------------------------------------------------------------
# API SIDRA/IBGE — tabela 6588 (LSPA)
# -----------------------------------------------------------------------------
SIDRA_URL = os.getenv("SIDRA_URL", "https://apisidra.ibge.gov.br/values")
SIDRA_TABELA = os.getenv("SIDRA_TABELA", "6588")
SIDRA_TIMEOUT = int(os.getenv("SIDRA_TIMEOUT", "20"))       # timeout HTTP (segundos)
SIDRA_TENTATIVAS = int(os.getenv("SIDRA_TENTATIVAS", "4"))  # tentativas por requisição
SIDRA_BACKOFF = float(os.getenv("SIDRA_BACKOFF", "3.0"))   # base do backoff exponencial

# Variáveis da tabela 6588 (LSPA) — códigos oficiais do SIDRA
SIDRA_VAR_AREA_PLANTADA = "109"  # Área plantada (hectares)
SIDRA_VAR_AREA_COLHIDA = "216"   # Área colhida (hectares)
SIDRA_VAR_PRODUCAO = "35"        # Produção (toneladas)
SIDRA_VAR_RENDIMENTO = "36"      # Rendimento médio (kg/ha)
SIDRA_VARIAVEIS = "109,216,35,36"

# Classificação 48 = "Produto das lavouras" na tabela 6588
SIDRA_CLASSIFICACAO = "48"

# Sigla da UF -> código IBGE (nível territorial n3 = Unidade da Federação)
UF_COD_IBGE = {
    "AC": "12", "AL": "27", "AP": "16", "AM": "13", "BA": "29",
    "CE": "23", "DF": "53", "ES": "32", "GO": "52", "MA": "21",
    "MT": "51", "MS": "50", "MG": "31", "PA": "15", "PB": "25",
    "PR": "41", "PE": "26", "PI": "22", "RJ": "33", "RN": "24",
    "RS": "43", "RO": "11", "RR": "14", "SC": "42", "SP": "35",
    "SE": "28", "TO": "17",
}

# Produto (nome amigável) -> categorias da classificação 48 na tabela 6588.
# Produtos com mais de uma safra no LSPA têm várias categorias e são agregados
# pelo worker (produção/áreas somadas; rendimento recalculado pela média ponderada).
# Também é possível usar o código SIDRA diretamente (ex.: "39454" = Café arábica).
PRODUTO_CATEGORIAS = {
    "soja": ["39443"],                      # 1.17 Soja
    "milho": ["39441", "39442"],            # 1.15 Milho (1ª safra) + 1.16 Milho (2ª safra)
    "arroz": ["39432"],                     # 1.4 Arroz
    "feijao": ["39436", "39437", "39438"],  # Feijão (1ª, 2ª e 3ª safra)
    "feijão": ["39436", "39437", "39438"],
    "trigo": ["39445"],                     # 1.19 Trigo
    "cafe": ["40527"],                      # 9/10 Café total
    "café": ["40527"],
    "algodao": ["39429"],                   # 1.1 Algodão herbáceo
    "algodão": ["39429"],
    "sorgo": ["39444"],                     # 1.18 Sorgo
    "aveia": ["39433"],                     # 1.5 Aveia
    "cana": ["39456"],                      # 11 Cana-de-açúcar
    "mandioca": ["39467"],                  # 21 Mandioca
    "cacau": ["39453"],                     # 8 Cacau
    "laranja": ["39463"],                   # 18 Laranja
    "uva": ["39471"],                       # 25 Uva
}
