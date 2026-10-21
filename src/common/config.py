"""Configuração central via variáveis de ambiente (12-factor, enxuto)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(key: str, default: str) -> str:
    return os.getenv(key, default)


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, default))
    except (TypeError, ValueError):
        return default


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, default))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Settings:
    """Configuração compartilhada entre Manager e Workers."""

    redis_url: str = field(default_factory=lambda: _env("REDIS_URL", "redis://redis:6379/0"))
    manager_url: str = field(default_factory=lambda: _env("MANAGER_URL", "http://manager:8000"))
    task_queue: str = field(default_factory=lambda: _env("TASK_QUEUE", "sidra:tasks"))
    db_path: str = field(default_factory=lambda: _env("DB_PATH", "/data/manager.db"))

    worker_id: str = field(default_factory=lambda: _env("WORKER_ID", f"worker-{os.getpid()}"))
    worker_concurrency: int = field(default_factory=lambda: _env_int("WORKER_CONCURRENCY", 4))

    sidra_base_url: str = field(
        default_factory=lambda: _env("SIDRA_BASE_URL", "https://apisidra.ibge.gov.br/values/")
    )
    http_timeout: float = field(default_factory=lambda: _env_float("HTTP_TIMEOUT", 30.0))
    max_retries: int = field(default_factory=lambda: _env_int("MAX_RETRIES", 3))
    worker_stale_seconds: int = field(default_factory=lambda: _env_int("WORKER_STALE_SECONDS", 30))
    heartbeat_seconds: float = field(default_factory=lambda: _env_float("HEARTBEAT_SECONDS", 10.0))

    log_level: str = field(default_factory=lambda: _env("LOG_LEVEL", "INFO"))


settings = Settings()
