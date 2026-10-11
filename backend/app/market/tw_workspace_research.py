"""Bounded transport projection of the existing Taiwan report; no IO or policy."""

from collections import Counter
from datetime import date, datetime
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.market.schemas import TechnicalReportRead


WORKSPACE_RESEARCH_MAX_BYTES = 128 * 1024


class TaiwanResearchProjectionTooLarge(ValueError):
    """Semantic fields cannot be silently discarded to satisfy transport limits."""


class WorkspaceRsiRead(BaseModel):
    model_config = ConfigDict(extra="allow")
    rsi14: float | None = None


class WorkspaceMacdRead(BaseModel):
    model_config = ConfigDict(extra="allow")
    macd: float | None = None
    signal: float | None = None
    histogram: float | None = None


class WorkspaceKdRead(BaseModel):
    model_config = ConfigDict(extra="allow")
    k9: float | None = None
    d9: float | None = None


class WorkspaceIndicatorSummary(BaseModel):
    basis: Literal["daily_indicator", "indicator", "daily_background"] | None = None
    time: date | datetime | str | None = None
    close: float | None = None
    rsi: WorkspaceRsiRead | None = None
    macd: WorkspaceMacdRead | None = None
    kd: WorkspaceKdRead | None = None
    change_pct: float | None = None


class WorkspaceTechnicalReportRead(TechnicalReportRead):
    model_config = ConfigDict(extra="allow")
    algorithm_version: str | None = None
    indicator_engine: dict[str, Any] | None = None
    evidence_passport: dict[str, Any] | None = None
    limitations: list[str] = Field(default_factory=list)


class TaiwanWorkspaceResearchRead(BaseModel):
    kind: Literal["omi.tw_stock_research"] = "omi.tw_stock_research"
    version: Literal["omi.tw_stock_research.workspace.v1"] = "omi.tw_stock_research.workspace.v1"
    projection: Literal["workspace"] = "workspace"
    stock_id: str
    timeframe: Literal["today", "daily", "weekly", "monthly"]
    cache_only: Literal[True] = True
    max_bytes: Literal[131072] = WORKSPACE_RESEARCH_MAX_BYTES
    technical: WorkspaceTechnicalReportRead
    technical_summary: WorkspaceIndicatorSummary
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


def _json_default(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"Unsupported research value: {type(value).__name__}")


def _compact_canonical_limitations(quality: dict[str, Any]) -> dict[str, Any]:
    """Summarize the Bar owner's dated blocker tokens, never arbitrary prose.

    Unknown/malformed tokens remain verbatim. Group counts are occurrences,
    not continuous coverage, and retain the exact state/reason pair.
    """
    limitations = quality.get("canonical_limitations")
    if not isinstance(limitations, list):
        return quality
    retained: list[Any] = []
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in limitations:
        parts = entry.split(":", 3) if isinstance(entry, str) else []
        if len(parts) != 4 or parts[0] != "TW_DAILY_DAY_STATE" or not parts[2] or not parts[3]:
            retained.append(entry)
            continue
        _, day, state, reason = parts
        try:
            valid_day = date.fromisoformat(day).isoformat() == day
        except ValueError:
            valid_day = False
        if not valid_day:
            retained.append(entry)
            continue
        group = groups.setdefault((state, reason), {
            "state": state, "reason": reason, "count": 0,
            "first_trade_date": day, "last_trade_date": day,
        })
        group["count"] += 1
        group["first_trade_date"] = min(group["first_trade_date"], day)
        group["last_trade_date"] = max(group["last_trade_date"], day)
    if not groups:
        return quality
    return {
        **quality,
        "canonical_limitations": retained,
        "canonical_limitations_summary": {
            "scope": "TW_DAILY_DAY_STATE occurrences grouped by exact state/reason; other limitations retained verbatim",
            "total_count": len(limitations), "grouped_count": len(limitations) - len(retained),
            "retained_count": len(retained), "groups": list(groups.values()),
            "date_bounds_are_continuous": False,
            "details_projection": "full", "details_field": "canonical_limitations",
        },
    }


def _compact_quality(quality: dict[str, Any]) -> dict[str, Any]:
    """Group daily semantics without carrying repeated raw receipt lineage.

    All non-provenance fields participate in the group key, including blockers,
    limitations and price-basis axes. Detailed dated states remain in full mode.
    """
    quality = _compact_canonical_limitations(quality)
    if "day_states" not in quality:
        return quality
    states = quality["day_states"]
    groups: dict[str, dict[str, Any]] = {}
    counts: Counter[str] = Counter()
    for state in states:
        semantic = {key: value for key, value in state.items()
                    if key not in {"trade_date", "lineage", "instrument"}}
        if isinstance(semantic.get("price_basis"), dict):
            semantic["price_basis"] = {key: value for key, value in semantic["price_basis"].items()
                                       if key != "lineage"}
        key = json.dumps(semantic, sort_keys=True, ensure_ascii=False, default=_json_default)
        day = str(state["trade_date"])
        if key not in groups:
            groups[key] = {"semantics": semantic, "count": 0, "first_trade_date": day, "last_trade_date": day}
        group = groups[key]
        group["count"] += 1
        group["first_trade_date"] = min(group["first_trade_date"], day)
        group["last_trade_date"] = max(group["last_trade_date"], day)
        counts[str(state.get("state"))] += 1
    blockers: dict[str, dict[str, Any]] = {}
    for entry in quality.get("day_state_blockers", []):
        semantic = {key: value for key, value in entry.items() if key != "trade_date"}
        key = json.dumps(semantic, sort_keys=True, ensure_ascii=False, default=_json_default)
        day = str(entry["trade_date"])
        if key not in blockers:
            blockers[key] = {"semantics": semantic, "count": 0, "first_trade_date": day, "last_trade_date": day}
        group = blockers[key]
        group["count"] += 1
        group["first_trade_date"] = min(group["first_trade_date"], day)
        group["last_trade_date"] = max(group["last_trade_date"], day)
    return {
        **{key: value for key, value in quality.items() if key not in {"day_states", "day_state_blockers"}},
        "day_state_summary": {"count": len(states), "state_counts": dict(counts), "groups": list(groups.values())},
        "day_state_blocker_summary": {"count": len(quality.get("day_state_blockers", [])), "groups": list(blockers.values())},
    }


def project_tw_workspace_research(full: dict[str, Any]) -> dict[str, Any]:
    report = full["technical"]
    data = dict(report.get("data") or {})
    # The producer intentionally shares quality objects across report views.
    # Memoize only within this projection; no persistent cache or new owner.
    qualities: dict[int, dict[str, Any]] = {}
    def compact(quality: dict[str, Any]) -> dict[str, Any]:
        identity = id(quality)
        if identity not in qualities:
            qualities[identity] = _compact_quality(quality)
        return qualities[identity]

    if isinstance(data.get("input_quality"), dict):
        data["input_quality"] = compact(data["input_quality"])
    for key in ("daily_indicator", "indicator", "daily_background", "current_partial_indicator"):
        indicator = data.get(key)
        if isinstance(indicator, dict) and isinstance(indicator.get("input_quality"), dict):
            data[key] = {**indicator, "input_quality": compact(indicator["input_quality"])}
    basis = next((key for key in ("daily_indicator", "indicator", "daily_background")
                  if isinstance(data.get(key), dict)), None)
    indicator = data[basis] if basis else {}
    result = TaiwanWorkspaceResearchRead.model_validate({
        **full, "version": "omi.tw_stock_research.workspace.v1", "projection": "workspace",
        "technical": {**report, "data": data},
        "technical_summary": {
            "basis": basis, **{key: indicator.get(key) for key in ("time", "close", "rsi", "macd", "kd")},
            "change_pct": indicator.get("change_pct"),
        },
        "limitations": [
            *(full.get("limitations") or []),
            "Daily state semantics are grouped; per-date state and raw receipt lineage remain available with projection=full.",
            "Dated canonical day-state limitations are grouped by exact state/reason with occurrence counts and date bounds; other limitations remain verbatim. Full details are in the same input_quality.canonical_limitations field with projection=full.",
            "Group first/last dates are bounds, not a claim of continuous daily membership.",
            "The indicator summary retains its own time and close; it is not the current intraday price.",
            "Indicator change_pct shares that indicator's basis; contextual change_pct remains in technical.data.",
            "Projection reduces transport size, not report computation or provider latency.",
        ],
    })
    # Match FastAPI's compact, UTF-8 JSON response encoding, including nulls.
    payload = result.model_dump(mode="json")
    size = len(json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8"))
    if size > WORKSPACE_RESEARCH_MAX_BYTES:
        raise TaiwanResearchProjectionTooLarge(
            f"Workspace research exceeds {WORKSPACE_RESEARCH_MAX_BYTES} UTF-8 JSON bytes; use projection=full."
        )
    return payload
