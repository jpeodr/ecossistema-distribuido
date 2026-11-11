# =============================================================================
# AgroData Distribuído — Processamento da Tarefa (Etapa 4)
# =============================================================================
# Recebe a tarefa de uma UF (publicada pelo manager na fila), busca os dados
# de cada produto × período em paralelo com ThreadPoolExecutor e grava o
# resultado em lote (INSERT ... ON DUPLICATE KEY UPDATE) no MySQL Master —
# a única porta de escrita do ecossistema, replicada para os slaves.
#
# Toda execução (e falha) é auditada na tabela `coletas_log`.
# =============================================================================

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

import mysql.connector

from app import config, sidra_fetch

log = logging.getLogger(__name__)

SQL_INSERT_LOTE = """
    INSERT INTO producao_agricola
        (uf, produto, periodo, producao, rendimento, area_plantada, area_colhida, worker_id)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
        producao     = VALUES(producao),
        rendimento   = VALUES(rendimento),
        area_plantada = VALUES(area_plantada),
        area_colhida  = VALUES(area_colhida),
        worker_id     = VALUES(worker_id)
"""


def _conectar_master():
    """Abre uma conexão com o MySQL Master (escrita)."""
    return mysql.connector.connect(
        host=config.MYSQL_MASTER_HOST,
        port=config.MYSQL_PORT,
        user=config.MYSQL_USER,
        password=config.MYSQL_PASS,
        database=config.MYSQL_DB,
        connect_timeout=5,
        autocommit=False,
    )


def _categorias_do_produto(produto: str) -> list:
    """Resolve o nome amigável do produto para as categorias SIDRA (classificação 48).
    Aceita também o código da categoria diretamente (ex.: '39454' = Café arábica)."""
    chave = str(produto).strip().lower()
    if chave in config.PRODUTO_CATEGORIAS:
        return config.PRODUTO_CATEGORIAS[chave]
    if chave.isdigit():
        return [chave]
    raise ValueError(
        f"Produto desconhecido: '{produto}' "
        f"(use um nome mapeado no worker ou o código SIDRA da categoria)"
    )


def _job_buscar(uf_codigo: str, tabela: str, produto: str, periodo: str):
    """Job executado em uma thread do pool: busca um produto em um período."""
    categorias = _categorias_do_produto(produto)
    dados = sidra_fetch.buscar_produto(tabela, uf_codigo, categorias, periodo)
    return produto, periodo, dados


def _buscar_produtos_em_paralelo(uf: str, uf_codigo: str, tabela: str, produtos: list, periodos: list):
    """Distribui as consultas (produto × período) entre as threads do worker.

    Retorna (registros, sem_dados): as linhas prontas para o INSERT em lote e
    a lista de combinações sem divulgação no SIDRA.
    """
    registros = []
    sem_dados = []
    combinacoes = [(p, per) for p in produtos for per in periodos]

    with ThreadPoolExecutor(max_workers=config.WORKER_THREADS, thread_name_prefix="sidra") as pool:
        futuros = {
            pool.submit(_job_buscar, uf_codigo, tabela, produto, periodo): (produto, periodo)
            for produto, periodo in combinacoes
        }
        for futuro in as_completed(futuros):
            produto, periodo, dados = futuro.result()  # exceção -> tarefa falha (retry/DLQ)
            if dados is None:
                sem_dados.append(f"{produto}/{periodo}")
                log.info("[%s] %-8s %s: sem dados divulgados no SIDRA", uf, produto, periodo)
                continue
            registros.append((
                uf, produto, str(periodo),
                dados["producao"], dados["rendimento"],
                dados["area_plantada"], dados["area_colhida"],
                config.WORKER_ID,
            ))
            log.info(
                "[%s] %-8s %s: produção=%s t | área colhida=%s ha | rendimento=%s kg/ha",
                uf, produto, periodo,
                f"{dados['producao']:,.0f}".replace(",", "."),
                f"{dados['area_colhida']:,.0f}".replace(",", "."),
                f"{dados['rendimento']:,.0f}".replace(",", ".") if dados["rendimento"] else "-",
            )

    return registros, sem_dados


def _registrar_log(cur, uf: str, status: str, mensagem: str):
    """Insere uma linha de auditoria em coletas_log e devolve o id gerado."""
    cur.execute(
        "INSERT INTO coletas_log (worker_id, uf, status, mensagem) VALUES (%s, %s, %s, %s)",
        (config.WORKER_ID, uf, status, mensagem),
    )
    return cur.lastrowid


def _atualizar_log(conn, cur, log_id: int, status: str, mensagem: str):
    """Atualiza a linha de auditoria (best-effort: não derruba a tarefa por causa do log)."""
    try:
        cur.execute(
            "UPDATE coletas_log SET status = %s, mensagem = %s WHERE id = %s",
            (status, mensagem[:500], log_id),
        )
        conn.commit()
    except mysql.connector.Error:
        conn.rollback()
        log.exception("Falha ao atualizar o log de coleta (id=%s)", log_id)


def processar_tarefa(tarefa: dict) -> dict:
    """Processa a tarefa de uma UF: busca paralela no SIDRA + gravação em lote
    no Master. Levanta exceção em qualquer falha (o consumer decide retry/DLQ)."""
    uf = str(tarefa.get("uf", "")).strip().upper()
    if uf not in config.UF_COD_IBGE:
        raise ValueError(f"UF inválida na tarefa: '{uf}'")
    uf_codigo = config.UF_COD_IBGE[uf]

    tabela = str(tarefa.get("tabela") or config.SIDRA_TABELA)
    produtos = tarefa.get("produtos") or []
    periodos = tarefa.get("periodos") or []
    if not produtos or not periodos:
        raise ValueError("Tarefa sem 'produtos' ou 'periodos' — payload inválido")

    log.info(
        "[%s] Tarefa recebida: %d produto(s) × %d período(s) na tabela %s",
        uf, len(produtos), len(periodos), tabela,
    )

    conn = _conectar_master()
    try:
        cur = conn.cursor()
        log_id = _registrar_log(
            cur, uf, "EM_ANDAMENTO",
            f"Coletando {len(produtos)} produto(s) × {len(periodos)} período(s) no SIDRA",
        )
        conn.commit()

        try:
            registros, sem_dados = _buscar_produtos_em_paralelo(uf, uf_codigo, tabela, produtos, periodos)

            # Gravação em lote no Master — idempotente: reprocessar uma tarefa
            # atualiza os mesmos registros (ON DUPLICATE KEY UPDATE) em vez de duplicar.
            if registros:
                cur.executemany(SQL_INSERT_LOTE, registros)
                conn.commit()
                log.info("[%s] Lote de %d registro(s) gravado no Master (%s)", uf, len(registros), config.MYSQL_MASTER_HOST)

            mensagem = f"Concluída: {len(registros)} registro(s) gravado(s) no Master"
            if sem_dados:
                mensagem += f"; {len(sem_dados)} combinação(ões) sem dados no SIDRA ({', '.join(sem_dados)})"
            _atualizar_log(conn, cur, log_id, "SUCESSO", mensagem)
        except Exception as e:
            _atualizar_log(conn, cur, log_id, "ERRO", f"Falha no processamento: {e}")
            raise
    finally:
        if conn.is_connected():
            conn.close()

    return {
        "uf": uf,
        "worker": config.WORKER_ID,
        "registros_gravados": len(registros),
        "sem_dados": len(sem_dados),
    }
