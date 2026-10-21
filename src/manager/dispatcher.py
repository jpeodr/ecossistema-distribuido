"""Dispatcher: transforma um job em tarefas distribuídas (fatiamento).

Estratégia de fatiamento: **uma tarefa por Unidade da Federação**.
O volume de trabalho é、天然mente paralelo (27 UFs para LSPA) e cada tarefa
resulta em uma chamada independente à API do SIDRA.
"""

from __future__ import annotations

import uuid

from ..common.datasets import Dataset, UFS
from ..common.models import Task


def build_tasks(
    job_id: str,
    dataset: Dataset,
    period: str,
    variables: list[int],
    categories: list[int],
) -> list[Task]:
    tasks: list[Task] = []
    for code, name in UFS:
        tasks.append(
            Task(
                task_id=uuid.uuid4().hex[:12],
                job_id=job_id,
                dataset=dataset.key,
                table=dataset.table,
                level=dataset.level,
                territory_code=code,
                territory_name=name,
                classification_id=dataset.classification_id,
                variables=variables,
                categories=categories,
                period=period,
            )
        )
    return tasks
