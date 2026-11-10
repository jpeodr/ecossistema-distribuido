import pika
import json
import datetime
from app.config import (
    RABBITMQ_HOST, RABBITMQ_PORT, RABBITMQ_USER, RABBITMQ_PASS,
    RABBITMQ_QUEUE, RABBITMQ_DLQ, UFS, SIDRA_TABELA, SIDRA_PRODUTOS, SIDRA_PERIODOS
)

def publicar_tarefas() -> dict:
    credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
    try:
        connection = pika.BlockingConnection(
            pika.ConnectionParameters(
                host=RABBITMQ_HOST,
                port=RABBITMQ_PORT,
                credentials=credentials,
                connection_attempts=5,
                retry_delay=2
            )
        )
    except Exception as e:
        return {"status": "erro", "mensagem": f"Falha ao conectar no RabbitMQ: {e}"}

    channel = connection.channel()

    channel.exchange_declare(exchange='dlx', exchange_type='direct', durable=True)
    channel.queue_declare(queue=RABBITMQ_DLQ, durable=True)
    channel.queue_bind(exchange='dlx', queue=RABBITMQ_DLQ, routing_key='sidra_tasks')

    channel.queue_declare(
        queue=RABBITMQ_QUEUE,
        durable=True,
        arguments={
            'x-dead-letter-exchange': 'dlx',
            'x-dead-letter-routing-key': 'sidra_tasks'
        }
    )

    publicadas = 0
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

    for uf in UFS:
        payload = {
            "uf": uf,
            "tabela": SIDRA_TABELA,
            "produtos": SIDRA_PRODUTOS,
            "periodos": SIDRA_PERIODOS,
            "timestamp": timestamp
        }

        channel.basic_publish(
            exchange='',
            routing_key=RABBITMQ_QUEUE,
            body=json.dumps(payload, ensure_ascii=False),
            properties=pika.BasicProperties(
                delivery_mode=2,  
                content_type='application/json'
            )
        )
        publicadas += 1

    connection.close()

    return {
        "status": "sucesso",
        "mensagem": f"{publicadas} tarefas enviadas para a fila '{RABBITMQ_QUEUE}'.",
        "total_tarefas": publicadas
    }