"""Contratos de dados compartilhados entre Manager e Workers (pydantic)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class JobRequest(BaseModel):
    """Pedido de execução de um job distribuído."""

    dataset: str = Field(default="lspa", description="lspa | pim_pf")
    period: str | None = Field(default=None, description="AAAAmm; None = último disponível")
    categories: list[int] | None = Field(default=None, description="Códigos das categorias")
    variables: list[int] | None = Field(default=None, description="Códigos das variáveis")


class Task(BaseModel):
    """Unidade de trabalho distribuída (uma por UF)."""

    task_id: str
    job_id: str
    dataset: str
    table: int
    level: str
    territory_code: str
    territory_name: str
    classification_id: int
    variables: list[int]
    categories: list[int]
    period: str
    attempt: int = 1


class Record(BaseModel):
    """Um dado bruto vindo do SIDRA, já normalizado."""

    territory_code: str
    territory_name: str
    variable_code: int
    variable_name: str
    unit: str
    category_code: int
    category_name: str
    period: str
    value: float | None = None
    raw_value: str = ""


class TaskResult(BaseModel):
    """Retorno do Worker ao Manager (callback HTTP)."""

    task_id: str
    job_id: str
    worker_id: str
    duration_ms: int
    attempt: int = 1
    records: list[Record] = []
    aggregates: dict[str, float] = {}
    error: str | None = None


class WorkerHeartbeat(BaseModel):
    worker_id: str
    capacity: int
    tasks_done: int
    tasks_failed: int
    started_at: float


class JobStatus(BaseModel):
    job_id: str
    dataset: str
    period: str
    status: str            # queued | running | completed | failed
    total_tasks: int
    done_tasks: int
    failed_tasks: int
    created_at: float
    started_at: float | None = None
    finished_at: float | None = None
    workers_involved: list[str] = []
