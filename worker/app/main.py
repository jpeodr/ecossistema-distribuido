"""Consumer RabbitMQ do worker (loop principal).

- Conecta com retry (o RabbitMQ pode ainda estar subindo).
- prefetch_count=1: cada worker pega UMA tarefa por vez -> as 3 replicas
  dividem as 27 UFs naturalmente (distribuicao Round-Robin do RabbitMQ).
- Sucesso -> ACK. Falha na 1a vez -> requeue. Falha repetida -> DLQ.
"""
import json
import time

import pika

from . import config
from .processor import WORKER_ID, processar_tarefa, registrar_falha


def _conectar() -> pika.BlockingConnection:
    credenciais = pika.PlainCredentials(config.RABBITMQ_USER, config.RABBITMQ_PASS)
    parametros = pika.ConnectionParameters(
        host=config.RABBITMQ_HOST, credentials=credenciais, heartbeat=60
    )
    while True:
        try:
            return pika.BlockingConnection(parametros)
        except pika.exceptions.AMQPConnectionError:
            print(f"⏳ [{WORKER_ID}] RabbitMQ indisponível, tentando em 5s...")
            time.sleep(5)


def _ao_receber(ch, method, properties, body):
    tarefa: dict = {}
    try:
        tarefa = json.loads(body.decode("utf-8"))
        print(f"📥 [{WORKER_ID}] Tarefa recebida: UF {tarefa['uf_cod']} "
              f"({tarefa.get('uf_nome', '')})")
        processar_tarefa(tarefa)
        ch.basic_ack(delivery_tag=method.delivery_tag)
    except Exception as exc:  # noqa: BLE001 - fronteira do consumer
        print(f"❌ [{WORKER_ID}] Erro ao processar: {exc}")
        registrar_falha(tarefa, exc)
        if method.redelivered:
            # Segunda falha: desiste e manda para a Dead Letter Queue
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
            print(f"☠️  [{WORKER_ID}] Tarefa enviada para a DLQ")
        else:
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)


def main():
    print(f"🚀 Worker {WORKER_ID} iniciando | threads={config.WORKER_THREADS}")
    conexao = _conectar()
    canal = conexao.channel()
    canal.queue_declare(queue=config.FILA_DLQ, durable=True)
    canal.queue_declare(
        queue=config.FILA_TAREFAS,
        durable=True,
        arguments={
            "x-dead-letter-exchange": "",
            "x-dead-letter-routing-key": config.FILA_DLQ,
            "x-message-ttl": 600000,
        },
    )
    canal.basic_qos(prefetch_count=1)
    canal.basic_consume(queue=config.FILA_TAREFAS, on_message_callback=_ao_receber)
    print(f"🎯 [{WORKER_ID}] Aguardando tarefas na fila '{config.FILA_TAREFAS}'...")
    canal.start_consuming()


if __name__ == "__main__":
    main()
