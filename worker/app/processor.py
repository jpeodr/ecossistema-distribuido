"""Processador de tarefas do worker.

Para cada tarefa (uma UF), busca todos os produtos configurados em
PARALELO usando ThreadPoolExecutor — paralelismo interno dentro de cada
no worker, exatamente o padrao `concurrent.futures` visto em aula.

Depois grava o lote no MySQL MASTER (unica porta de escrita do sistema);
a replicacao leva os dados aos 3 slaves.
"""
import socket
import time
from concurrent.futures import ThreadPoolExecutor

import mysql.connector

from . import config, sidra_fetch

WORKER_ID = socket.gethostname()  # nome do container (ex.: projeto-worker-2)

_INSERT = """
INSERT INTO lspa_registros
    (uf_cod, uf_nome, variavel_cod, variavel, periodo, periodo_nome,
     produto_cod, produto, unidade, valor, worker_id)
VALUES (%(uf_cod)s, %(uf_nome)s, %(variavel_cod)s, %(variavel)s,
        %(periodo)s, %(periodo_nome)s, %(produto_cod)s, %(produto)s,
        %(unidade)s, %(valor)s, %(worker_id)s)
ON DUPLICATE KEY UPDATE
    valor = VALUES(valor), worker_id = VALUES(worker_id),
    coletado_em = CURRENT_TIMESTAMP
"""

_INSERT_COLETA = """
INSERT INTO coletas
    (tarefa_id, uf_cod, status, registros, duracao_ms, worker_id, mensagem)
VALUES (%(tarefa_id)s, %(uf_cod)s, %(status)s, %(registros)s,
        %(duracao_ms)s, %(worker_id)s, %(mensagem)s)
"""


def _conexao_master():
    return mysql.connector.connect(
        host=config.MYSQL_MASTER_HOST,
        port=config.MYSQL_MASTER_PORT,
        user=config.MYSQL_USER,
        password=config.MYSQL_PASSWORD,
        database=config.MYSQL_DATABASE,
        connection_timeout=10,
    )


def processar_tarefa(tarefa: dict) -> int:
    """Processa uma tarefa (UF). Retorna o numero de registros gravados.

    Lanca excecao em caso de falha — o consumer faz nack/requeue ou DLQ.
    """
    inicio = time.time()
    uf_cod = tarefa["uf_cod"]
    produtos = tarefa.get("produtos", [])
    variaveis = tarefa.get("variaveis")
    periodos = tarefa.get("periodos")

    # --- Paralelismo interno: uma thread por produto ----------------
    with ThreadPoolExecutor(max_workers=config.WORKER_THREADS) as pool:
        futuros = {
            pool.submit(
                sidra_fetch.buscar_dados_uf_produto,
                uf_cod, produto, variaveis, periodos,
            ): produto
            for produto in produtos
        }
        registros: list[dict] = []
        for futuro, produto in futuros.items():
            registros.extend(futuro.result())

    # --- Gravacao em lote no MASTER ---------------------------------
    for registro in registros:
        registro["worker_id"] = WORKER_ID

    conexao = _conexao_master()
    try:
        cursor = conexao.cursor()
        cursor.executemany(_INSERT, registros)
        duracao_ms = int((time.time() - inicio) * 1000)
        cursor.execute(_INSERT_COLETA, {
            "tarefa_id": tarefa["tarefa_id"],
            "uf_cod": uf_cod,
            "status": "SUCESSO",
            "registros": len(registros),
            "duracao_ms": duracao_ms,
            "worker_id": WORKER_ID,
            "mensagem": None,
        })
        conexao.commit()
    finally:
        conexao.close()

    print(f"✅ [{WORKER_ID}] UF {uf_cod} ({tarefa.get('uf_nome', '')}): "
          f"{len(registros)} registros em {duracao_ms}ms")
    return len(registros)


def registrar_falha(tarefa: dict, erro: Exception) -> None:
    """Registra a falha no log de coletas (best-effort, nao propaga)."""
    try:
        conexao = _conexao_master()
        cursor = conexao.cursor()
        cursor.execute(_INSERT_COLETA, {
            "tarefa_id": tarefa.get("tarefa_id", "?"),
            "uf_cod": tarefa.get("uf_cod", "?"),
            "status": "ERRO",
            "registros": 0,
            "duracao_ms": 0,
            "worker_id": WORKER_ID,
            "mensagem": str(erro)[:500],
        })
        conexao.commit()
        conexao.close()
    except mysql.connector.Error:
        pass
