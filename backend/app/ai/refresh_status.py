from __future__ import annotations

from datetime import datetime, timezone

from numbers import Real
from typing import Any

from sqlalchemy.orm import Session

from app.ai import agentic_policy, capability_contract
from app.jobs import service as job_service
from app.jobs.taiwan_intraday_demand import consumer_request


AI_REFRESH_JOB_TYPE = "ai.tool_refresh"
PUBLIC_STATUS_VERSION = "omi.ai.refresh.status.v1"
PUBLIC_DEMAND_REASONS = frozenset({
    "CANONICAL_CURRENT_SESSION_READY", "CURRENT_SESSION_BASELINE_NOT_READY",
    "CANONICAL_PERSISTENCE_REJECTED", "TW_INTRADAY_DEMAND_EXPIRED",
    "TW_INTRADAY_DEMAND_SUBMIT_FAILED", "TW_INTRADAY_DEMAND_TIMEOUT",
    "TW_INTRADAY_DEMAND_ACQUISITION_FAILED", "TW_INTRADAY_DEMAND_PROVIDER_BACKOFF",
    "TW_INTRADAY_DEMAND_INSTRUMENT_UNAVAILABLE", "TW_INTRADAY_DEMAND_FAILED",
})


class AiRefreshJobNotFoundError(Exception):
    """Raised when an id is unknown or is not a public AI refresh job."""


def _operation(
    *,
    request: dict[str, Any],
    result: dict[str, Any],
) -> str | None:
    result_tool = str(result.get("tool") or "").strip()
    if result_tool in agentic_policy.ALLOWED_TOOLS:
        return result_tool
    for value in request.get("requested_capabilities") or []:
        candidate = str(value or "").strip()
        if candidate in agentic_policy.ALLOWED_TOOLS:
            return candidate
    return None


def _target_type(operation: str | None) -> str | None:
    if operation == "tw.refresh_watchlist_evidence":
        return "watchlist"
    if operation == "cross_market.refresh_context" or str(operation).startswith(
        "tw."
    ):
        return "tw_stock"
    if str(operation).startswith("us."):
        return "us_stock"
    if str(operation).startswith("jp."):
        return "jp_index" if "index" in str(operation) else "jp_stock"
    if str(operation).startswith("kr."):
        return "kr_index" if "index" in str(operation) else "kr_stock"
    if str(operation).startswith("crypto."):
        return "crypto_asset"
    return None


def _requested_capabilities(request: dict[str, Any]) -> list[str]:
    return list(
        dict.fromkeys(
            str(value).strip()
            for value in request.get("requested_capabilities") or []
            if str(value).strip() in capability_contract.CAPABILITIES
        )
    )


def _numeric_summary(value: Any) -> dict[str, Real]:
    if not isinstance(value, dict):
        return {}
    summary: dict[str, Real] = {}
    for key, item in value.items():
        if (
            isinstance(item, Real)
            and not isinstance(item, bool)
            and (
                str(key).endswith("_count")
                or str(key)
                in {
                    "rows",
                    "points",
                    "requested",
                    "returned",
                }
            )
        ):
            summary[str(key)] = item
    nested = value.get("result")
    if isinstance(nested, dict):
        for key, item in _numeric_summary(nested).items():
            summary.setdefault(key, item)
    return summary


def _operation_status(public_status: str) -> str:
    return {
        "queued": "queued",
        "running": "running",
        "completed": "succeeded",
        "partial": "partial",
        "failed": "failed",
        "cancelled": "cancelled",
        "expired": "expired",
    }.get(public_status, "unknown")


def _evidence_status(public_status: str) -> str:
    return {
        "completed": "rebuild_required",
        "partial": "partial_rebuild_required",
    }.get(public_status, "unobserved")


def read_refresh_status(
    *,
    db: Session,
    job_id: int,
) -> dict[str, Any]:
    try:
        job = job_service.get_job(db, job_id)
    except job_service.JobRunNotFoundError as exc:
        raise AiRefreshJobNotFoundError(
            f"AI refresh job id={job_id} not found."
        ) from exc
    demand = consumer_request(job)
    if str(job.job_type) != AI_REFRESH_JOB_TYPE and demand is None:
        # Deliberately hide whether a non-AI job id exists.
        raise AiRefreshJobNotFoundError(
            f"AI refresh job id={job_id} not found."
        )

    serialized = job_service.serialize_job(job, include_payload=True)
    request = (
        serialized.get("request")
        if isinstance(serialized.get("request"), dict)
        else {}
    )
    result = (
        serialized.get("result")
        if isinstance(serialized.get("result"), dict)
        else {}
    )
    public_status = str(serialized.get("public_status") or "unknown")
    if demand is not None and public_status == "queued" and datetime.now(timezone.utc) >= datetime.fromisoformat(demand["expires_at"]):
        # Expiration is a read projection; only a command may terminalize a row.
        public_status = "expired"
    operation = _operation(request=request, result=result)
    capabilities = _requested_capabilities(request)
    target_id = str(serialized.get("target") or "").strip() or None
    target_type = _target_type(operation)
    if demand is not None:
        operation = "tw.refresh_intraday_bars"
        capabilities = ["intraday.bars"]
        target_id = demand["stock_id"]
        target_type = "tw_stock"
    target = {
        **({"type": target_type} if target_type else {}),
        **({"id": target_id} if target_id else {}),
    }
    evidence_rebuild_required = public_status in {"completed", "partial"}
    resume = None
    if evidence_rebuild_required and target_type and target_id and capabilities:
        resume = {
            "tool": "omi.ask",
            "arguments": {
                "contract_version": "omi.decision.v4",
                "question": "Rebuild evidence after the selected background refresh.",
                "target": target,
                "selection": {"include": capabilities},
                "output": "evidence_only",
                "realtime_policy": "cache_only",
                "allow_llm": False,
                "allow_write": False,
                "allow_external_fetch": False,
            },
        }
        if demand is not None:
            resume["arguments"]["market_data_params"] = {
                "trade_date": demand["trade_date"], "include_intraday": True,
                "intraday_interval": "1m",
            }

    error = None
    if public_status in {"failed", "cancelled", "expired"}:
        error = {
            "code": f"AI_REFRESH_{public_status.upper()}",
            "message": (
                "Background refresh did not complete. Inspect OMI provider events "
                "or source health for redacted diagnostics."
            ),
            "retryable": public_status == "failed",
        }

    return {
        "kind": "ai_refresh_status",
        "version": PUBLIC_STATUS_VERSION,
        "job_id": int(job.id),
        "job_type": str(job.job_type),
        "status": public_status,
        "operation_status": _operation_status(public_status),
        "evidence_status": _evidence_status(public_status),
        "operation": operation,
        "target": target,
        "requested_capabilities": capabilities,
        "produced_capabilities": list(
            capability_contract.canonical_fill_operation_produced_capabilities().get(
                operation or "",
                (),
            )
        ),
        "provider_set": [] if demand is not None else [
            str(value)
            for value in request.get("provider_set") or []
            if str(value).strip()
        ],
        "date_range": ({"from": demand["trade_date"], "to": demand["trade_date"]} if demand is not None else (
            request.get("date_range")
            if isinstance(request.get("date_range"), dict)
            else {}
        )),
        "include_today": request.get("include_today"),
        "progress": {
            "current": int(serialized.get("progress_current") or 0),
            "total": int(serialized.get("progress_total") or 0),
        },
        "result_summary": (
            {key: result[key] for key in ("attempt_count", "external_call_count", "external_call_budget_used", "bars_written_count", "reread_count", "current_session_bar_count")
             if isinstance(result.get(key), int) and not isinstance(result[key], bool)}
            if demand is not None else _numeric_summary(result)
        ),
        "requested_trade_date": demand["trade_date"] if demand else None,
        "reason_code": (
            result.get("reason_code")
            if demand and result.get("reason_code") in PUBLIC_DEMAND_REASONS else None
        ),
        "next_retry_at": result.get("next_retry_at") if demand and public_status == "queued" else None,
        "expires_at": demand["expires_at"] if demand else None,
        "retry_not_before_at": result.get("retry_not_before_at") if demand else None,
        "materialization": ({
            key: result.get(key) for key in (
                "reread_ready", "reread_trade_date", "snapshot_phase", "snapshot_revision",
                "external_call_count", "bars_written_count",
            )
        } if demand else None),
        "evidence_rebuild_required": evidence_rebuild_required,
        "retryable": bool(error and error.get("retryable")),
        "error": error,
        "created_at": serialized.get("created_at"),
        "started_at": serialized.get("started_at"),
        "finished_at": serialized.get("ended_at"),
        "updated_at": serialized.get("updated_at"),
        "poll_url": f"/api/ai/refresh-status/{job.id}",
        "resume": resume,
    }
