"""Attach Atlas Documents to the existing selected-evidence pipeline."""
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.stocks.atlas_news import CAPABILITY_ID, read_stock_news


def selection_for_question(selection: dict[str, Any], *, question: str, scope_type: str) -> dict[str, Any]:
    if scope_type != "stock" or not settings.omi_atlas_news_enabled:
        return selection
    if not any(term in question.lower() for term in ("新聞", "新闻", "news")):
        return selection
    if CAPABILITY_ID in (selection.get("exclude") or []):
        return selection
    if any(key in selection for key in ("required", "include", "optional")):
        return selection
    return {**selection, "optional": [CAPABILITY_ID], "auto_planning": True}


def selected(selection: dict[str, Any]) -> bool:
    return CAPABILITY_ID in [*(selection.get("required") or selection.get("include") or []),
                             *(selection.get("optional") or [])]


def attach_to_result(result: dict[str, Any], *, db: Session, stock_id: str,
                     selection: dict[str, Any]) -> None:
    limit = (selection.get("limits") or {}).get(CAPABILITY_ID, 20)
    parameters = (selection.get("parameters") or {}).get(CAPABILITY_ID, {})
    context = read_stock_news(db, stock_id, limit=limit, cursor=parameters.get("cursor"))
    data = result.setdefault("data", {})
    compact = data.setdefault("compact", {})
    data["company_news"] = context
    compact["company_news"] = context
    # Evidence retrieval and dataset completeness are independent. A readable stale
    # document must not make the capability's manifest appear current.
    status = context["status"]
    if status in {"available", "ready_empty"}:
        status = context["freshness"].get("status", "unknown")
        if context["coverage"].get("guarantee") == "best_effort" and status == "current":
            status = "partial"
    compact.setdefault("slots", {})["company_news"] = {
        "capability": CAPABILITY_ID, "status": status,
        "payload_ref": "data.company_news", "payload_level": "compact",
        "as_of": context["freshness"].get("as_of"),
        "missing": context["missing"], "warnings": context["warnings"],
    }
