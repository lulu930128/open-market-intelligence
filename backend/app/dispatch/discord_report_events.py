"""Dedicated stderr events; the launcher alone owns runtime log files."""
from contextlib import contextmanager
from contextvars import ContextVar
import logging
import re
from threading import RLock
from uuid import uuid4


_lock = RLock()
_context = ContextVar("discord_report_event_context", default={})
_LOGGER_NAME = "app.discord_market_report.events"
_HANDLER_NAME = "discord_market_report_stderr"


def event_logger() -> logging.Logger:
    logger = logging.getLogger(_LOGGER_NAME)
    with _lock:
        if not any(handler.name == _HANDLER_NAME for handler in logger.handlers):
            handler = logging.StreamHandler()
            handler.name = _HANDLER_NAME
            handler.setFormatter(logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s pid=%(process)d %(message)s"))
            logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


@contextmanager
def report_event_context(phase: str):
    token = _context.set({"run_id": uuid4().hex, "phase": phase})
    try:
        yield
    finally:
        _context.reset(token)


def safe_exception_fields(error: Exception) -> dict:
    """Never stringify, retain, or traverse an exception or its chain."""
    def number(name):
        value = getattr(error, name, None)
        return value if type(value) is int else None

    return {"exception_type": type(error).__name__,
            "errno": number("errno"), "winerror": number("winerror")}


def report_event(stage: str, **fields) -> None:
    # Closed field inventory excludes caller text, URLs, payloads and bodies.
    allowed = {"run_id", "phase", "job_id", "scheduled_time", "timezone",
               "status", "sent_chunks", "selected", "attempted", "repaired", "unresolved",
               "exception_type", "errno", "winerror", "status_code", "outcome"}
    values = {**_context.get(), **fields}
    parts = [f"stage={stage}"]
    for key, value in values.items():
        if key not in allowed:
            continue
        if value is None or type(value) is int:
            parts.append(f"{key}={value}")
        elif isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_:/-]{1,80}", value):
            parts.append(f"{key}={value}")
    event_logger().info(" ".join(parts))
