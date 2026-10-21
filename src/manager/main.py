"""Manager (coordenador) do Ecossistema Distribuído.

Responsabilidades:
  1. Receber a solicitação de job e fatiá-la em tarefas (dispatcher).
  2. Publicar as tarefas na fila do Redis (broker).
  3. Receber o retorno dos Workers (callback HTTP) e persistir em SQLite.
  4. Executar a etapa REDUCE e publicar o relatório final.
"""

from __future__ import annotations

import json
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from redis.asyncio import Redis
from redis.exceptions import RedisError

from ..common.config import settings
from ..common.datasets import DATASETS, get_dataset
from ..common.logging import setup_logging
from ..common.models import JobRequest, JobStatus, Task, TaskResult, WorkerHeartbeat
from ..common.sidra import SidraClient
from .analysis import reduce_results
from .dispatcher import build_tasks
from .store import Store

log = setup_logging("manager", settings.log_level)

redis: Redis
store: Store
sidra: SidraClient


@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis, store, sidra
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    store = Store(settings.db_path)
    sidra = SidraClient(settings, log)
    try:
        await redis.ping()
        log.info("manager pronto", extra={"extra_fields": {"redis": settings.redis_url}})
    except RedisError as exc:
        log.error("redis indisponivel", extra={"extra_fields": {"erro": str(exc)}})
    yield
    await redis.aclose()
    await sidra.aclose()


app = FastAPI(
    title="Ecossistema Distribuído - Manager",
    description="Coordenador de jobs distribuídos sobre a API do SIDRA/IBGE.",
    version="1.0.0",
    lifespan=lifespan,
)

PAINEL_DIR = Path(__file__).parent / "static"


@app.get("/", include_in_schema=False)
async def raiz() -> RedirectResponse:
    """Redireciona a raiz para o painel web do ecossistema."""
    return RedirectResponse("/painel/")


@app.get("/painel", include_in_schema=False)
async def painel() -> RedirectResponse:
    return RedirectResponse("/painel/")


app.mount("/painel", StaticFiles(directory=PAINEL_DIR, html=True), name="painel")


# ----------------------------------------------------------------- saúde
@app.get("/api/v1/health")
async def health() -> dict:
    redis_ok = False
    try:
        redis_ok = bool(await redis.ping())
    except RedisError:
        redis_ok = False
    workers = store.workers(settings.worker_stale_seconds) if store else []
    return {
        "status": "ok" if redis_ok else "degraded",
        "redis": redis_ok,
        "workers_ativos": len(workers),
        "fila": await _queue_depth(),
    }


async def _queue_depth() -> int:
    try:
        return int(await redis.llen(settings.task_queue))
    except RedisError:
        return -1


# --------------------------------------------------------------- datasets
@app.get("/api/v1/datasets")
async def list_datasets() -> dict:
    """Pesquisas do SIDRA suportadas (usado pelo painel web)."""
    return {
        d.key: {
            "key": d.key,
            "label": d.label,
            "theme": d.theme,
            "table": d.table,
            "classification_id": d.classification_id,
            "narrative": d.narrative,
            "variables": [{"code": v.code, "name": v.name, "unit": v.unit, "agg": v.agg}
                          for v in d.variables],
            "categories": [{"code": c.code, "name": c.name} for c in d.categories],
        }
        for d in DATASETS.values()
    }


# ------------------------------------------------------------------ jobs
@app.post("/api/v1/jobs", status_code=202)
async def create_job(request: JobRequest) -> dict:
    """Cria o job, fatia em tarefas e publica na fila do Redis."""
    try:
        dataset = get_dataset(request.dataset)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    variables = request.variables or [v.code for v in dataset.variables]
    categories = request.categories or [c.code for c in dataset.categories]

    period = request.period
    if not period:
        try:
            period = await sidra.last_period(dataset.table, dataset.primary_variable, dataset.level)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"Falha ao consultar período no SIDRA: {exc}") from exc

    job_id = uuid.uuid4().hex[:12]
    tasks = build_tasks(job_id, dataset, period, variables, categories)

    store.create_job(job_id, dataset.key, period, len(tasks))
    store.register_tasks(job_id, tasks)

    pipeline = redis.pipeline()
    for task in tasks:
        pipeline.rpush(settings.task_queue, task.model_dump_json())
    await pipeline.execute()
    store.mark_job_running(job_id)

    log.info(
        "job despachado",
        extra={"extra_fields": {
            "job_id": job_id, "dataset": dataset.key, "period": period,
            "tarefas": len(tasks), "categorias": categories,
        }},
    )
    return {
        "job_id": job_id,
        "dataset": dataset.key,
        "label": dataset.label,
        "period": period,
        "total_tasks": len(tasks),
        "status": "running",
        "fila": settings.task_queue,
    }


@app.get("/api/v1/jobs")
async def list_jobs(limit: int = 20) -> dict:
    return {"jobs": store.jobs(limit)}


@app.get("/api/v1/jobs/{job_id}")
async def get_job(job_id: str) -> JobStatus:
    job = store.job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job não encontrado")
    tasks = store.tasks_of_job(job_id)
    return JobStatus(
        job_id=job["job_id"],
        dataset=job["dataset"],
        period=job["period"],
        status=job["status"],
        total_tasks=job["total_tasks"],
        done_tasks=job["done_tasks"],
        failed_tasks=job["failed_tasks"],
        created_at=job["created_at"],
        started_at=job["started_at"],
        finished_at=job["finished_at"],
        workers_involved=sorted({t["worker_id"] for t in tasks if t["worker_id"]}),
    )


@app.get("/api/v1/jobs/{job_id}/tasks")
async def get_job_tasks(job_id: str) -> dict:
    tasks = store.tasks_of_job(job_id)
    distribuicao: dict[str, int] = {}
    for task in tasks:
        if task["worker_id"]:
            distribuicao[task["worker_id"]] = distribuicao.get(task["worker_id"], 0) + 1
    return {"tasks": tasks, "distribuicao_por_worker": distribuicao}


@app.get("/api/v1/jobs/{job_id}/results")
async def get_job_results(job_id: str) -> dict:
    job = store.job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job não encontrado")

    summary = json.loads(job["summary"]) if job["summary"] else None
    return {
        "job_id": job_id,
        "status": job["status"],
        "dataset": job["dataset"],
        "period": job["period"],
        "summary": summary,
    }


# ------------------------------------------------------- callback do worker
@app.post("/api/v1/internal/results")
async def receive_result(result: TaskResult) -> dict:
    """Recebe o resultado de uma tarefa executada por um Worker."""
    task = store.task(result.task_id)
    if not task:
        raise HTTPException(status_code=404, detail="tarefa desconhecida")

    if result.error:
        # Política de retry: devolve a tarefa para a fila enquanto houver tentativas.
        if result.attempt < settings.max_retries:
            await _requeue(result.task_id, result.attempt + 1)
            log.warning(
                "tarefa falhou, re-enfileirada",
                extra={"extra_fields": {
                    "task_id": result.task_id, "tentativa": result.attempt, "erro": result.error,
                }},
            )
            return {"status": "requeued", "task_id": result.task_id}
        store.fail_task(result.task_id, result.job_id, result.worker_id, result.duration_ms, result.error)
        log.warning(
            "tarefa falhou definitivamente",
            extra={"extra_fields": {"task_id": result.task_id, "erro": result.error}},
        )
    else:
        store.complete_task(
            result.task_id, result.job_id, result.worker_id, result.duration_ms,
            [r.model_dump() for r in result.records],
        )

    await _maybe_finalize(result.job_id)
    return {"status": "accepted", "task_id": result.task_id}


async def _requeue(task_id: str, attempt: int) -> None:
    """Reenfileira a tarefa original, incrementando o número da tentativa."""
    row = store.task(task_id)
    if not row or not row.get("payload"):
        return
    task = Task.model_validate_json(row["payload"])
    task.attempt = attempt
    await redis.rpush(settings.task_queue, task.model_dump_json())


async def _maybe_finalize(job_id: str) -> None:
    """Dispara o REDUCE quando todas as tarefas do job concluírem."""
    job = store.job(job_id)
    if not job or job["status"] in {"completed", "failed"}:
        return
    if job["done_tasks"] + job["failed_tasks"] < job["total_tasks"]:
        return

    if job["failed_tasks"] > 0 and job["done_tasks"] == 0:
        store.finish_job(job_id, "failed", {"erro": "todas as tarefas falharam"})
        return

    records = store.records_of_job(job_id)
    dataset = get_dataset(job["dataset"])
    summary = reduce_results(records, dataset)
    summary["tarefas"] = {
        "total": job["total_tasks"],
        "concluidas": job["done_tasks"],
        "falhas": job["failed_tasks"],
    }
    summary["tempo_total_s"] = round((time.time() - (job["started_at"] or job["created_at"])), 2)
    store.finish_job(job_id, "completed", summary)
    log.info(
        "job finalizado",
        extra={"extra_fields": {"job_id": job_id, "registros": len(records)}},
    )


# --------------------------------------------------------------- workers
@app.post("/api/v1/workers/heartbeat")
async def heartbeat(beat: WorkerHeartbeat) -> dict:
    store.upsert_worker(
        beat.worker_id, beat.capacity, beat.tasks_done, beat.tasks_failed, beat.started_at
    )
    return {"status": "ok", "server_time": time.time()}


@app.get("/api/v1/workers")
async def list_workers() -> dict:
    workers = store.workers(settings.worker_stale_seconds)
    return {"workers": workers, "fila": await _queue_depth()}
