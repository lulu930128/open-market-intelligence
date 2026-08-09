from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import utc_now
from app.dispatch.schedule_time import ensure_utc
from app.market.calendar_status import build_taiwan_calendar_status
from app.market.source_health import build_taiwan_source_health


READINESS_CONTRACT_VERSION = "omi.dispatch.readiness.v1"
UNHEALTHY_SOURCE_STATUSES = {"empty", "error", "missing", "stale"}


def _source_health_projection(payload: dict[str, Any]) -> dict[str, Any]:
    entries = payload.get("entries")
    normalized_entries = entries if isinstance(entries, list) else []
    limitations: list[dict[str, Any]] = []
    for entry in normalized_entries:
        if not isinstance(entry, dict):
            continue
        status = str(entry.get("status") or "unknown").lower()
        if status in UNHEALTHY_SOURCE_STATUSES:
            limitations.append(
                {
                    "resource": entry.get("resource"),
                    "status": status,
                    "reason": entry.get("reason"),
                    "latest_data_date": entry.get("latest_data_date"),
                    "expected_data_date": entry.get("expected_data_date"),
                }
            )
    return {
        "summary": payload.get("summary") if isinstance(payload.get("summary"), dict) else {},
        "limitations": limitations[:12],
    }


def evaluate_dispatch_readiness(
    db: Session,
    *,
    profile: str,
    policy: str,
    scheduled_for: datetime,
    deadline_minutes: int,
    retry_interval_seconds: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    checked_at = ensure_utc(now or utc_now())
    scheduled_at = ensure_utc(scheduled_for)
    deadline = scheduled_at + timedelta(minutes=max(int(deadline_minutes), 0))
    normalized_profile = str(profile or "generic").strip().lower()
    normalized_policy = str(policy or "immediate").strip().lower()
    base = {
        "contract_version": READINESS_CONTRACT_VERSION,
        "profile": normalized_profile,
        "policy": normalized_policy,
        "checked_at": checked_at,
        "scheduled_for": scheduled_at,
        "deadline_at": deadline,
        "retry_at": checked_at + timedelta(seconds=max(int(retry_interval_seconds), 10)),
        "required_capabilities": [],
        "optional_capabilities": [],
        "warnings": [],
        "missing": [],
        "provider_failures": [],
        "source_refs": [],
        "metadata": {},
    }

    if normalized_profile == "generic":
        return {
            **base,
            "ready": True,
            "status": "ready",
            "retryable": False,
            "reason_code": "READY_GENERIC",
            "reason_message": "No market-specific readiness gate is required.",
        }

    if normalized_profile not in {"tw_preopen", "tw_post_close", "watchlist_radar"}:
        return {
            **base,
            "ready": False,
            "status": "error",
            "retryable": False,
            "reason_code": "READINESS_PROFILE_UNSUPPORTED",
            "reason_message": f"Unsupported readiness profile: {normalized_profile}",
        }

    calendar = build_taiwan_calendar_status(now=checked_at)
    base["source_refs"] = ["tw.market.calendar"]
    base["metadata"] = {
        "market": "tw",
        "calendar": {
            "date": calendar.get("date"),
            "phase": calendar.get("phase"),
            "is_trading_day": calendar.get("is_trading_day"),
            "reason": calendar.get("reason"),
        },
    }
    if calendar.get("is_trading_day") is not True:
        return {
            **base,
            "ready": False,
            "status": "not_applicable",
            "retryable": False,
            "reason_code": "TW_NON_TRADING_DAY",
            "reason_message": "The scheduled date is not a Taiwan trading day.",
        }

    phase = str(calendar.get("phase") or "unknown")
    if normalized_profile == "tw_preopen":
        ready = phase in {"preopen", "regular", "closing_auction", "post_close"}
        return {
            **base,
            "ready": ready,
            "status": "ready" if ready else "pending",
            "retryable": not ready and checked_at < deadline,
            "reason_code": "TW_PREOPEN_READY" if ready else "TW_PREOPEN_NOT_STARTED",
            "reason_message": (
                "Taiwan pre-open session context is available."
                if ready
                else "Taiwan pre-open session has not started."
            ),
        }

    if normalized_profile == "tw_post_close" and phase != "post_close":
        return {
            **base,
            "ready": False,
            "status": "pending",
            "retryable": checked_at < deadline,
            "reason_code": "TW_SESSION_NOT_CLOSED",
            "reason_message": "Taiwan regular trading has not reached post-close.",
        }

    dataset = "market_breadth" if normalized_profile == "tw_post_close" else "taiwan_market_minute_state"
    health = build_taiwan_source_health(
        db,
        dataset=dataset,
        now=checked_at,
        sync_snapshots=False,
    )
    health_projection = _source_health_projection(health)
    limitations = health_projection["limitations"]
    ready = not limitations
    base["required_capabilities"] = [f"tw.{dataset}"]
    base["source_refs"] = [*base["source_refs"], f"tw.source_health.{dataset}"]
    base["metadata"] = {
        **base["metadata"],
        "source_health": health_projection,
    }
    base["missing"] = [
        str(item.get("resource") or dataset)
        for item in limitations
        if item.get("status") in {"empty", "missing"}
    ]
    base["warnings"] = [
        f"{item.get('resource') or dataset}: {item.get('status')}"
        for item in limitations
    ]
    return {
        **base,
        "ready": ready,
        "status": "ready" if ready else "incomplete",
        "retryable": not ready and checked_at < deadline,
        "reason_code": "TW_DATA_READY" if ready else "TW_REQUIRED_DATA_INCOMPLETE",
        "reason_message": (
            "Required Taiwan market data is ready."
            if ready
            else "Required Taiwan market data is missing, stale, or unavailable."
        ),
    }


__all__ = ["READINESS_CONTRACT_VERSION", "evaluate_dispatch_readiness"]
