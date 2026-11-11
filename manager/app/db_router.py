"""Router de conexoes MySQL do Manager.

- Escritas sempre no MASTER (via workers, na pratica).
- Leituras distribuidas entre os 3 SLAVES em Round-Robin,
  com fallback para o master caso um slave esteja fora.
- Inclui monitoramento do lag de replicacao (SHOW REPLICA STATUS).
"""
import mysql.connector

from . import config


class DatabaseRouter:
    def __init__(self):
        self._indice_slave = 0

    # -----------------------------------------------------------
    # Conexoes
    # -----------------------------------------------------------
    def _cfg(self, host: str, port: int = 3306) -> dict:
        return {
            "host": host,
            "port": port,
            "user": config.MYSQL_USER,
            "password": config.MYSQL_PASSWORD,
            "database": config.MYSQL_DATABASE,
            "connection_timeout": 5,
        }

    def conexao_master(self):
        return mysql.connector.connect(**self._cfg(config.MYSQL_MASTER_HOST,
                                                   config.MYSQL_MASTER_PORT))

    def conexao_slave(self):
        """Round-Robin entre slaves; se um falhar, tenta o proximo."""
        erros = []
        for _ in range(len(config.MYSQL_SLAVE_HOSTS)):
            host = config.MYSQL_SLAVE_HOSTS[self._indice_slave]
            self._indice_slave = (self._indice_slave + 1) % len(config.MYSQL_SLAVE_HOSTS)
            try:
                return mysql.connector.connect(**self._cfg(host)), host
            except mysql.connector.Error as exc:
                erros.append(f"{host}: {exc}")
        # Fallback: leitura direta no master
        return self.conexao_master(), f"{config.MYSQL_MASTER_HOST} (fallback: {erros})"

    # -----------------------------------------------------------
    # Leituras (sempre via slave, quando possivel)
    # -----------------------------------------------------------
    def ler(self, query: str, params: tuple = ()) -> dict:
        conexao, origem = self.conexao_slave()
        try:
            cursor = conexao.cursor(dictionary=True)
            cursor.execute(query, params)
            linhas = cursor.fetchall()
            return {"origem_leitura": origem, "linhas": linhas}
        finally:
            conexao.close()

    # -----------------------------------------------------------
    # Monitoramento da replicacao
    # -----------------------------------------------------------
    def lag_replicacao(self) -> dict:
        """Consulta SHOW REPLICA STATUS em cada slave."""
        status = {}
        for host in config.MYSQL_SLAVE_HOSTS:
            try:
                conexao = mysql.connector.connect(
                    host=host, port=3306, user="root",
                    password=config.MYSQL_ROOT_PASSWORD,
                    connection_timeout=5,
                )
                cursor = conexao.cursor(dictionary=True)
                cursor.execute("SHOW REPLICA STATUS")
                replica = cursor.fetchone() or {}
                status[host] = {
                    "io_running": replica.get("Replica_IO_Running"),
                    "sql_running": replica.get("Replica_SQL_Running"),
                    "lag_segundos": replica.get("Seconds_Behind_Source"),
                }
                conexao.close()
            except mysql.connector.Error as exc:
                status[host] = {"erro": str(exc)}
        return status
