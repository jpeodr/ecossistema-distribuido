"""Producer RabbitMQ do Manager.

Publica as fatias de trabalho (uma tarefa por UF) na fila `sidra_tasks`.
A fila e duravel e possui Dead Letter Queue para tarefas que falharem
repetidamente nos workers (padrao visto em aula).
"""
import json
import time
import uuid

import pika

from . import config


def _conectar() -> pika.BlockingConnection:
    credenciais = pika.PlainCredentials(config.RABBITMQ_USER, config.RABBITMQ_PASS)
    parametros = pika.ConnectionParameters(
        host=config.RABBITMQ_HOST, credentials=credenciais, heartbeat=60
    )
    return pika.BlockingConnection(parametros)


def declarar_topologia(channel: pika.adapters.blocking_connection.BlockingChannel) -> None:
    """Declara a fila de tarefas (duravel) e sua DLQ."""
    channel.queue_declare(queue=config.FILA_DLQ, durable=True)
    channel.queue_declare(
        queue=config.FILA_TAREFAS,
        durable=True,
        arguments={
            "x-dead-letter-exchange": "",
            "x-dead-letter-routing-key": config.FILA_DLQ,
            "x-message-ttl": 600000,  # 10 min na fila
        },
    )


def publicar_coleta(tarefa_id: str | None = None) -> dict:
    """Fatia a coleta da LSPA em 1 tarefa por UF e publica na fila.

    Estrategia de participonamento: PARALELISMO DE DADOS — cada worker
    recebe um recorte territorial (UF) e processa todos os produtos e
    variaveis daquele recorte em threads internas.
    """
    tarefa_id = tarefa_id or str(uuid.uuid4())
    conexao = _conectar()
    canal = conexao.channel()
    declarar_topologia(canal)

    total = 0
    for uf_cod, uf_nome in config.UFS.items():
        mensagem = {
            "id": str(uuid.uuid4()),
            "tarefa_id": tarefa_id,
            "tipo": "COLETA_UF",
            "uf_cod": uf_cod,
            "uf_nome": uf_nome,
            "tabela": config.SIDRA_TABELA,
            "periodos": config.SIDRA_PERIODOS,
            "variaveis": config.SIDRA_VARIAVEIS,
            "produtos": config.SIDRA_PRODUTOS,
            "timestamp": time.time(),
        }
        canal.basic_publish(
            exchange="",
            routing_key=config.FILA_TAREFAS,
            body=json.dumps(mensagem, ensure_ascii=False),
            properties=pika.BasicProperties(
                delivery_mode=2,  # mensagem persistente
                content_type="application/json",
            ),
        )
        total += 1

    conexao.close()
    return {"tarefa_id": tarefa_id, "tarefas_publicadas": total}


def profundidade_filas() -> dict:
    """Retorna quantas mensagens estao pendentes em cada fila."""
    conexao = _conectar()
    canal = conexao.channel()
    declarar_topologia(canal)
    filas = {}
    for nome in (config.FILA_TAREFAS, config.FILA_DLQ):
        declarada = canal.queue_declare(queue=nome, durable=True, passive=True)
        filas[nome] = declarada.method.message_count
    conexao.close()
    return filas
