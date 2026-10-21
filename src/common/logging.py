"""Logging estruturado e enxuto (JSON por linha, ideal para conteineres)."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "node": record.name,
            "msg": record.getMessage(),
        }
        for key, value in getattr(record, "extra_fields", {}).items():
            payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def force_utf8() -> None:
    """Garante saída UTF-8 (importante no Windows, cujo console não é UTF-8)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def setup_logging(node: str, level: str = "INFO") -> logging.Logger:
    force_utf8()
    logger = logging.getLogger(node)
    logger.setLevel(level.upper())
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    logger.propagate = False
    return logger


def log_extra(logger: logging.Logger, level: int, msg: str, **fields) -> None:
    """Log com campos extras serializados em JSON."""
    logger.log(level, msg, extra={"extra_fields": fields})
