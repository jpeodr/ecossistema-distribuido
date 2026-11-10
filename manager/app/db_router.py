import mysql.connector
import itertools
from app.config import SLAVES, MASTER, MYSQL_USER, MYSQL_PASS, MYSQL_DB, MYSQL_PORT

slave_cycle = itertools.cycle(SLAVES)

def get_db_connection():
    tentativas_slaves = len(SLAVES)

    for _ in range(tentativas_slaves):
        slave_host = next(slave_cycle)
        try:
            conn = mysql.connector.connect(
                host=slave_host,
                port=MYSQL_PORT,
                user=MYSQL_USER,
                password=MYSQL_PASS,
                database=MYSQL_DB,
                connect_timeout=2
            )
            if conn.is_connected():
                return conn, slave_host
        except mysql.connector.Error:
            continue  

    try:
        conn = mysql.connector.connect(
            host=MASTER,
            port=MYSQL_PORT,
            user=MYSQL_USER,
            password=MYSQL_PASS,
            database=MYSQL_DB,
            connect_timeout=3
        )
        if conn.is_connected():
            return conn, f"{MASTER} (Master-Fallback)"
    except mysql.connector.Error as e:
        raise Exception(f"Falha crítica de conexão em todos os nós do banco: {e}")

def execute_query(sql: str, params=None) -> tuple[list[dict], str]:
    """Executa consultas de leitura alternando entre os Slaves e retorna (dados, nó_origem)."""
    conn, origem = get_db_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql, params or ())
        resultados = cursor.fetchall()
        cursor.close()
        return resultados, origem
    finally:
        if conn and conn.is_connected():
            conn.close()