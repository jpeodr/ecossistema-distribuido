# =============================================================================
# AgroData Distribuído — Consumer da Fila / Entrada do Worker (Etapa 4)
# =============================================================================
# Consome as tarefas da fila 'sidra_tasks' do RabbitMQ (uma por UF, publicadas
# pelo manager) e entrega cada uma ao processor (paralelismo interno + gravação
# no MySQL Master).
#
# Tratamento de erros:
#   - falha -> a tarefa é devolvida à fila (header x-retry-count incrementado);
#   - após MAX_TENTATIVAS processamentos -> basic_reject(requeue=False), e o
#     dead-letter exchange (dlx) encaminha a mensagem para a DLQ 'sidra_tasks_dlq';
#   - payload malformado (JSON inválido) -> vai direto para a DLQ, pois tentar
#     de novo nunca vai consertar a mensagem.
# =============================================================================

import json
import logging
import time

import pika

from app import config, processor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(threadName)-10s | %(message)s",
    datefmt="%H:%M:%S",
)
# o pika é muito verboso em INFO — reduz para WARNING (os logs mostram só o worker)
logging.getLogger("pika").setLevel(logging.WARNING)
log = logging.getLogger(__name__)


def _conectar_rabbitmq():
    """Abre a conexão com o RabbitMQ (com retentativas para aguentar o boot)."""
    credenciais = pika.PlainCredentials(config.RABBITMQ_USER, config.RABBITMQ_PASS)
    return pika.BlockingConnection(
        pika.ConnectionParameters(
            host=config.RABBITMQ_HOST,
            port=config.RABBITMQ_PORT,
            credentials=credenciais,
            connection_attempts=10,
            retry_delay=3,
            heartbeat=60,
        )
    )


def _declarar_filas(channel):
    """Declara o exchange de dead-letter, a DLQ e a fila principal.

    Idempotente: as mesmas declarações do manager — assim o worker também
    sobe sozinho, antes ou depois dele, sem quebrar nada.
    """
    channel.exchange_declare(exchange=config.RABBITMQ_DLX, exchange_type="direct", durable=True)
    channel.queue_declare(queue=config.RABBITMQ_DLQ, durable=True)
    channel.queue_bind(exchange=config.RABBITMQ_DLX, queue=config.RABBITMQ_DLQ, routing_key=config.RABBITMQ_QUEUE)

    channel.queue_declare(
        queue=config.RABBITMQ_QUEUE,
        durable=True,
        arguments={
            "x-dead-letter-exchange": config.RABBITMQ_DLX,
            "x-dead-letter-routing-key": config.RABBITMQ_QUEUE,
        },
    )


def _callback(channel, method, properties, body):
    """Recebe UMA tarefa da fila e decide: ack, devolver à fila ou DLQ."""
    # 1) decodifica o payload da tarefa
    try:
        tarefa = json.loads(body)
    except json.JSONDecodeError as e:
        log.error("Mensagem malformada (JSON inválido: %s) — encaminhando direto para a DLQ", e)
        channel.basic_reject(delivery_tag=method.delivery_tag, requeue=False)
        return

    uf = tarefa.get("uf", "?")
    tentativa = int((properties.headers or {}).get("x-retry-count", 0)) + 1

    # 2) processa: busca no SIDRA em paralelo + gravação em lote no Master
    try:
        resumo = processor.processar_tarefa(tarefa)
        log.info(
            "[%s] Tarefa concluída (tentativa %d/%d): %s",
            uf, tentativa, config.MAX_TENTATIVAS, resumo,
        )
        channel.basic_ack(delivery_tag=method.delivery_tag)

    # 3) falha: devolve à fila ou encaminha para a DLQ
    except Exception as e:
        log.error("[%s] Falha ao processar tarefa (tentativa %d/%d): %s", uf, tentativa, config.MAX_TENTATIVAS, e)

        if tentativa < config.MAX_TENTATIVAS:
            # devolve à fila para uma nova tentativa, marcando o contador no header
            time.sleep(config.RETRY_DELAY)
            channel.basic_publish(
                exchange="",
                routing_key=config.RABBITMQ_QUEUE,
                body=body,
                properties=pika.BasicProperties(
                    delivery_mode=2,  # persistente
                    content_type="application/json",
                    headers={**(properties.headers or {}), "x-retry-count": tentativa},
                ),
            )
            channel.basic_ack(delivery_tag=method.delivery_tag)
            log.warning(
                "[%s] Tarefa devolvida à fila '%s' para nova tentativa",
                uf, config.RABBITMQ_QUEUE,
            )
        else:
            # tentativas esgotadas: rejeita sem requeue -> dlx -> DLQ
            channel.basic_reject(delivery_tag=method.delivery_tag, requeue=False)
            log.error(
                "[%s] Tentativas esgotadas (%d/%d) — tarefa encaminhada para a DLQ '%s'",
                uf, tentativa, config.MAX_TENTATIVAS, config.RABBITMQ_DLQ,
            )


def main():
    log.info(
        "Worker '%s' iniciando | threads=%d | tentativas por tarefa=%d",
        config.WORKER_ID, config.WORKER_THREADS, config.MAX_TENTATIVAS,
    )

    while True:  # loop de resiliência: reconecta se o RabbitMQ cair
        connection = None
        try:
            connection = _conectar_rabbitmq()
            channel = connection.channel()
            _declarar_filas(channel)

            # 1 tarefa por vez por worker: o RabbitMQ distribui as 27 UFs
            # em round-robin entre os workers que estão livres
            channel.basic_qos(prefetch_count=1)

            channel.basic_consume(queue=config.RABBITMQ_QUEUE, on_message_callback=_callback)
            log.info("Aguardando tarefas na fila '%s'...", config.RABBITMQ_QUEUE)
            channel.start_consuming()

        except KeyboardInterrupt:
            log.info("Encerrando worker '%s'...", config.WORKER_ID)
            if connection and connection.is_open:
                connection.close()
            break
        except Exception as e:
            log.error("Conexão com o RabbitMQ perdida (%s). Reconectando em 5s...", e)
            time.sleep(5)


if __name__ == "__main__":
    main()
