"""Structured, greppable logs: `ts LEVEL event key=value ...`."""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone

from ..config import settings

_CONFIGURED = False


class _StructuredFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        base = f"{ts} {record.levelname} {record.getMessage()}"
        extras = getattr(record, "kv", None)
        if extras:
            base += " " + " ".join(f"{k}={v}" for k, v in extras.items())
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


def configure_logging() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_StructuredFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.log_level.upper())
    logging.getLogger("uvicorn.access").setLevel("WARNING")
    _CONFIGURED = True


class StructuredLogger:
    def __init__(self, name: str):
        self._log = logging.getLogger(name)

    def _emit(self, level: int, event: str, **kv) -> None:
        self._log.log(level, event, extra={"kv": kv})

    def info(self, event: str, **kv) -> None:
        self._emit(logging.INFO, event, **kv)

    def warn(self, event: str, **kv) -> None:
        self._emit(logging.WARNING, event, **kv)

    def error(self, event: str, **kv) -> None:
        self._emit(logging.ERROR, event, **kv)

    def debug(self, event: str, **kv) -> None:
        self._emit(logging.DEBUG, event, **kv)

    def exception(self, event: str, **kv) -> None:
        self._log.exception(event, extra={"kv": kv})


def get_logger(name: str) -> StructuredLogger:
    configure_logging()
    return StructuredLogger(name)
