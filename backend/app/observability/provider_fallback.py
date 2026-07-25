from __future__ import annotations

import logging
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.observability.provider_health import record_provider_event
from app.observability.provider_http import provider_http_failure


logger = logging.getLogger(__name__)
SessionFactory = Callable[[], Session]


def observe_provider_fallback(
    exc: BaseException,
    *,
    operation: str,
    fallback_provider: str | None = None,
    session_factory: SessionFactory | None = None,
) -> bool:
    """Persist canonical provider failures without touching the caller transaction."""

    failure = provider_http_failure(exc)
    if failure is None:
        logger.warning(
            "Provider fallback used after an unclassified failure operation=%s error_type=%s",
            operation,
            type(exc).__name__,
        )
        return False

    db: Session | None = None
    try:
        db = (session_factory or SessionLocal)()
        record_provider_event(
            db,
            event_type="fallback",
            message=f"Provider fallback activated during {operation}.",
            detail={
                "operation": operation,
                "primary_provider": failure.context.provider,
                "fallback_provider": fallback_provider,
                "switch_reason": (
                    failure.error_message
                    or f"primary_status={failure.status}"
                ),
            },
            **failure.provider_event_fields(),
        )
        logger.warning(
            "Provider fallback recorded operation=%s market=%s provider=%s resource=%s target=%s status=%s",
            operation,
            failure.context.market,
            failure.context.provider,
            failure.context.resource,
            failure.context.target,
            failure.status,
        )
        return True
    except Exception:
        if db is not None:
            try:
                db.rollback()
            except Exception:
                logger.exception(
                    "Provider fallback telemetry rollback failed operation=%s",
                    operation,
                )
        logger.exception(
            "Provider fallback telemetry persistence failed operation=%s market=%s provider=%s resource=%s target=%s",
            operation,
            failure.context.market,
            failure.context.provider,
            failure.context.resource,
            failure.context.target,
        )
        return False
    finally:
        if db is not None:
            try:
                db.close()
            except Exception:
                logger.exception(
                    "Provider fallback telemetry session close failed operation=%s",
                    operation,
                )


__all__ = ["observe_provider_fallback"]
