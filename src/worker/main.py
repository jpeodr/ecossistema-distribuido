"""Worker (processamento) do Ecossistema Distribuído.

Ciclo de vida:
    BLPOP na fila do Redis -> executa a tarefa -> devolve o resultado ao Manager.

Paralelismo interno do nó:
  * assíncrono (I/O): até WORKER_CONCURRENCY tarefas em voo ao mesmo tempo;
  * multithreading (CPU): normalização pandas executada em thread dedicada.
"""

from __future__ import annotations

import asyncio
import os
import socket
import time
from dataclasses import replace

import httpx
from redis.asyncio import Redis
from redis.exceptions import RedisError

from ..common.config import Settings, settings
from ..common.logging import setup_logging
from ..common.models import Task, TaskResult
from ..common.sidra import SidraClient, SidraError
from .processor import parse_rows, summarize

log = setup_logging(settings.worker_id, settings.log_level)


class Worker:
    def __init__(self, cfg: Settings) -> None:
        self.cfg = cfg
        self.worker_id = cfg.worker_id or f"worker-{socket.gethostname()}"
        self.redis = Redis.from_url(cfg.redis_url, decode_responses=True)
        self.sidra = SidraClient(cfg, log)
        self.http = httpx.AsyncClient(timeout=httpx.Timeout(cfg.http_timeout, connect=10.0))
        self.tasks_done = 0
        self.tasks_failed = 0
        self.started_at = time.time()
        self._running = True

    # ------------------------------------------------------------- helpers
    async def _post_result(self, result: TaskResult) -> bool:
        """Envia o resultado ao Manager com retry e backoff."""
        for attempt in range(1, self.cfg.max_retries + 1):
            try:
                response = await self.http.post(
                    f"{self.cfg.manager_url}/api/v1/internal/results", json=result.model_dump()
                )
                if response.status_code < 400:
                    return True
                log.warning(
                    "manager recusou resultado",
                    extra={"extra_fields": {"status": response.status_code, "body": response.text[:200]}},
                )
            except httpx.HTTPError as exc:
                log.warning(
                    "falha ao enviar resultado",
                    extra={"extra_fields": {"tentativa": attempt, "erro": str(exc)}},
                )
            if attempt < self.cfg.max_retries:
                await asyncio.sleep(2 ** (attempt - 1))
        return False

    async def _heartbeat(self) -> None:
        while self._running:
            try:
                await self.http.post(
                    f"{self.cfg.manager_url}/api/v1/workers/heartbeat",
                    json={
                        "worker_id": self.worker_id,
                        "capacity": self.cfg.worker_concurrency,
                        "tasks_done": self.tasks_done,
                        "tasks_failed": self.tasks_failed,
                        "started_at": self.started_at,
                    },
                )
            except httpx.HTTPError:
                pass
            await asyncio.sleep(self.cfg.heartbeat_seconds)

    # --------------------------------------------------------- execução
    async def handle(self, task: Task) -> None:
        """Executa uma tarefa: busca no SIDRA, normaliza e devolve ao Manager."""
        started = time.perf_counter()
        error: str | None = None
        records = []
        aggregates: dict[str, float] = {}

        try:
            rows = await self.sidra.fetch(
                table=task.table,
                level=task.level,
                territories=task.territory_code,
                variables=task.variables,
                period=task.period,
                classification_id=task.classification_id,
                categories=task.categories,
            )
            records = parse_rows(rows, task.dataset)
            # Etapa CPU-bound em thread: não bloqueia o event loop.
            aggregates = await asyncio.to_thread(summarize, records)
        except (SidraError, httpx.HTTPError, asyncio.TimeoutError) as exc:
            error = str(exc)
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"

        duration_ms = int((time.perf_counter() - started) * 1000)
        result = TaskResult(
            task_id=task.task_id,
            job_id=task.job_id,
            worker_id=self.worker_id,
            duration_ms=duration_ms,
            attempt=task.attempt,
            records=records,
            aggregates=aggregates,
            error=error,
        )
        delivered = await self._post_result(result)
        if error or not delivered:
            self.tasks_failed += 1
            log.warning(
                "tarefa concluida com falha",
                extra={"extra_fields": {
                    "task_id": task.task_id, "uf": task.territory_name,
                    "erro": error, "entregue": delivered, "duracao_ms": duration_ms,
                }},
            )
        else:
            self.tasks_done += 1
            log.info(
                "tarefa concluida",
                extra={"extra_fields": {
                    "task_id": task.task_id, "uf": task.territory_name,
                    "registros": len(records), "duracao_ms": duration_ms,
                }},
            )

    async def run(self) -> None:
        log.info(
            "worker iniciado",
            extra={"extra_fields": {
                "worker_id": self.worker_id,
                "concorrencia": self.cfg.worker_concurrency,
                "fila": self.cfg.task_queue,
                "host": socket.gethostname(),
            }},
        )
        heartbeat = asyncio.create_task(self._heartbeat())
        inflight: set[asyncio.Task] = set()

        try:
            while self._running:
                if len(inflight) >= self.cfg.worker_concurrency:
                    done, inflight = await asyncio.wait(
                        inflight, return_when=asyncio.FIRST_COMPLETED
                    )
                    for item in done:
                        item.exception()

                try:
                    item = await self.redis.blpop(self.cfg.task_queue, timeout=5)
                except RedisError as exc:
                    log.error("redis indisponivel", extra={"extra_fields": {"erro": str(exc)}})
                    await asyncio.sleep(2)
                    continue

                if item is None:
                    continue

                _, payload = item
                try:
                    task = Task.model_validate_json(payload)
                except Exception as exc:  # noqa: BLE001
                    log.error("tarefa invalida descartada", extra={"extra_fields": {"erro": str(exc)}})
                    continue

                job = asyncio.create_task(self.handle(task))
                inflight.add(job)
                job.add_done_callback(inflight.discard)
        except asyncio.CancelledError:
            raise
        finally:
            self._running = False
            heartbeat.cancel()
            for job in list(inflight):
                job.cancel()
            await self.http.aclose()
            await self.sidra.aclose()
            await self.redis.aclose()


async def main() -> None:
    cfg = settings
    if not os.getenv("WORKER_ID"):
        # No Docker o HOSTNAME é o id do container: mantém o nó rastreável
        # (docker ps mostra o mesmo id).
        cfg = replace(cfg, worker_id=f"worker-{socket.gethostname()[:8]}")
    worker = Worker(cfg)
    await worker.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
