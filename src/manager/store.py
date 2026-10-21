"""Persistência do Manager (SQLite).

O SQLite é a fonte da verdade do coordenador: jobs, tarefas, registros
coletados e o registro de workers. O Redis fica só com o papel de broker.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterable


class Store:
    def __init__(self, path: str) -> None:
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._create_schema()

    # -------------------------------------------------------------- schema
    def _create_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id       TEXT PRIMARY KEY,
                    dataset      TEXT NOT NULL,
                    period       TEXT NOT NULL,
                    status       TEXT NOT NULL,
                    total_tasks  INTEGER NOT NULL,
                    done_tasks   INTEGER NOT NULL DEFAULT 0,
                    failed_tasks INTEGER NOT NULL DEFAULT 0,
                    created_at   REAL NOT NULL,
                    started_at   REAL,
                    finished_at  REAL,
                    summary      TEXT
                );

                CREATE TABLE IF NOT EXISTS tasks (
                    task_id         TEXT PRIMARY KEY,
                    job_id          TEXT NOT NULL,
                    territory_code  TEXT NOT NULL,
                    territory_name  TEXT NOT NULL,
                    status          TEXT NOT NULL,
                    worker_id       TEXT,
                    duration_ms     INTEGER,
                    error           TEXT,
                    payload         TEXT,
                    created_at      REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS records (
                    id               INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id           TEXT NOT NULL,
                    task_id          TEXT NOT NULL,
                    territory_code   TEXT NOT NULL,
                    territory_name   TEXT NOT NULL,
                    variable_code    INTEGER NOT NULL,
                    variable_name    TEXT NOT NULL,
                    unit             TEXT,
                    category_code    INTEGER NOT NULL,
                    category_name    TEXT NOT NULL,
                    period           TEXT NOT NULL,
                    value            REAL,
                    raw_value        TEXT
                );

                CREATE TABLE IF NOT EXISTS workers (
                    worker_id   TEXT PRIMARY KEY,
                    capacity    INTEGER NOT NULL,
                    tasks_done  INTEGER NOT NULL DEFAULT 0,
                    tasks_failed INTEGER NOT NULL DEFAULT 0,
                    started_at  REAL NOT NULL,
                    last_seen   REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_records_job ON records(job_id);
                CREATE INDEX IF NOT EXISTS idx_tasks_job  ON tasks(job_id);
                """
            )

    # ---------------------------------------------------------------- jobs
    def create_job(self, job_id: str, dataset: str, period: str, total_tasks: int) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO jobs (job_id, dataset, period, status, total_tasks, created_at)"
                " VALUES (?, ?, ?, 'queued', ?, ?)",
                (job_id, dataset, period, total_tasks, time.time()),
            )

    def mark_job_running(self, job_id: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE jobs SET status = 'running', started_at = COALESCE(started_at, ?)"
                " WHERE job_id = ?",
                (time.time(), job_id),
            )

    def finish_job(self, job_id: str, status: str, summary: dict[str, Any]) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE jobs SET status = ?, finished_at = ?, summary = ? WHERE job_id = ?",
                (status, time.time(), json.dumps(summary, ensure_ascii=False), job_id),
            )

    def job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        return dict(row) if row else None

    def jobs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def completed_jobs(self, limit: int = 20) -> list[dict[str, Any]]:
        """Jobs concluídos, do mais recente para o mais antigo (usado pela interface)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM jobs WHERE status = 'completed'"
                " ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    # --------------------------------------------------------------- tasks
    def register_tasks(self, job_id: str, tasks: Iterable[Any]) -> None:
        """Registra as tarefas do job. `tasks` são objetos Task (payload fica guardado)."""
        now = time.time()
        rows = [
            (
                t.task_id, job_id, t.territory_code, t.territory_name, "pending",
                t.model_dump_json(), now,
            )
            for t in tasks
        ]
        with self._lock, self._conn:
            self._conn.executemany(
                "INSERT OR REPLACE INTO tasks"
                " (task_id, job_id, territory_code, territory_name, status, payload, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                rows,
            )

    def complete_task(
        self,
        task_id: str,
        job_id: str,
        worker_id: str,
        duration_ms: int,
        records: list[dict[str, Any]],
    ) -> None:
        now = time.time()
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE tasks SET status = 'done', worker_id = ?, duration_ms = ?"
                " WHERE task_id = ?",
                (worker_id, duration_ms, task_id),
            )
            self._conn.executemany(
                "INSERT INTO records (job_id, task_id, territory_code, territory_name,"
                " variable_code, variable_name, unit, category_code, category_name,"
                " period, value, raw_value) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        job_id, task_id, r["territory_code"], r["territory_name"],
                        r["variable_code"], r["variable_name"], r["unit"], r["category_code"],
                        r["category_name"], r["period"], r["value"], r["raw_value"],
                    )
                    for r in records
                ],
            )
            self._conn.execute(
                "UPDATE jobs SET done_tasks = done_tasks + 1,"
                " status = CASE WHEN status = 'queued' THEN 'running' ELSE status END"
                " WHERE job_id = ?",
                (job_id,),
            )

    def fail_task(self, task_id: str, job_id: str, worker_id: str, duration_ms: int, error: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE tasks SET status = 'failed', worker_id = ?, duration_ms = ?, error = ?"
                " WHERE task_id = ?",
                (worker_id, duration_ms, error[:500], task_id),
            )
            self._conn.execute(
                "UPDATE jobs SET failed_tasks = failed_tasks + 1,"
                " status = CASE WHEN status = 'queued' THEN 'running' ELSE status END"
                " WHERE job_id = ?",
                (job_id,),
            )

    def task(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        return dict(row) if row else None

    def tasks_of_job(self, job_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM tasks WHERE job_id = ? ORDER BY territory_code", (job_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    def records_of_job(self, job_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM records WHERE job_id = ?", (job_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------- workers
    def upsert_worker(self, worker_id: str, capacity: int, tasks_done: int, tasks_failed: int,
                      started_at: float) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO workers (worker_id, capacity, tasks_done, tasks_failed, started_at, last_seen)"
                " VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(worker_id) DO UPDATE SET"
                "   capacity = excluded.capacity, tasks_done = excluded.tasks_done,"
                "   tasks_failed = excluded.tasks_failed, last_seen = excluded.last_seen",
                (worker_id, capacity, tasks_done, tasks_failed, started_at, time.time()),
            )

    def workers(self, stale_seconds: int = 30) -> list[dict[str, Any]]:
        limit = time.time() - stale_seconds
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM workers WHERE last_seen >= ? ORDER BY worker_id", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]
