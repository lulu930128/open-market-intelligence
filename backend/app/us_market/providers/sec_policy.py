from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import threading
import time
from typing import TypeVar

from app.observability.provider_http import ProviderHttpError


R = TypeVar("R")


@dataclass
class SecRequestPolicy:
    min_interval_seconds: float = 0.25
    max_attempts: int = 2
    retry_backoff_seconds: float = 0.5
    max_retry_after_seconds: float = 5.0
    monotonic: Callable[[], float] = field(default=time.monotonic, repr=False)
    sleep: Callable[[float], None] = field(default=time.sleep, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _last_request_at: float | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.min_interval_seconds < 0:
            raise ValueError("SEC minimum request interval cannot be negative.")
        if self.max_attempts < 1 or self.max_attempts > 3:
            raise ValueError("SEC max_attempts must be between 1 and 3.")
        if self.retry_backoff_seconds < 0 or self.max_retry_after_seconds < 0:
            raise ValueError("SEC retry delays cannot be negative.")

    def _wait_for_request_slot(self) -> None:
        with self._lock:
            now = self.monotonic()
            if self._last_request_at is not None:
                remaining = self.min_interval_seconds - (now - self._last_request_at)
                if remaining > 0:
                    self.sleep(remaining)
                    now = self.monotonic()
            self._last_request_at = now

    def execute(self, request: Callable[[], R]) -> R:
        for attempt in range(1, self.max_attempts + 1):
            self._wait_for_request_slot()
            try:
                return request()
            except ProviderHttpError as exc:
                if attempt >= self.max_attempts or exc.status == "blocked":
                    raise

                if exc.status == "rate_limited":
                    retry_after = exc.retry_after_seconds
                    if retry_after is None:
                        delay = self.retry_backoff_seconds
                    elif retry_after > self.max_retry_after_seconds:
                        raise
                    else:
                        delay = float(retry_after)
                elif exc.status in {"timeout", "error"}:
                    delay = self.retry_backoff_seconds
                else:
                    raise

                if delay > 0:
                    self.sleep(delay)

        raise RuntimeError("SEC request policy exhausted without a result.")


DEFAULT_SEC_REQUEST_POLICY = SecRequestPolicy()


__all__ = ["DEFAULT_SEC_REQUEST_POLICY", "SecRequestPolicy"]
