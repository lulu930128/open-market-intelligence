from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Protocol

from sqlalchemy.orm import Session

from app.ai.market_context.common import append_source_ref_once as _append_source_ref_once
from app.ai.market_context.taiwan_projection import (
    _build_tw_market_slots,
    _compact_index_quote,
    _compact_single_intraday_series,
    _with_evidence_passport,
)
from app.ai.market_payload_contract import (
    intraday_point_limit as _intraday_point_limit,
    market_data_params as _market_data_params,
    payload_level as _payload_level,
)
from app.db.models import StockMaster
from app.market.taiwan_industries import normalize_tw_industry_label


class MarketService(Protocol):
    def get_latest_trade_date(self, db: Session) -> Any: ...

    def list_market_daily_prices(
        self,
        *,
        db: Session,
        trade_date: Any,
        limit: int,
    ) -> list[Any]: ...


@dataclass(frozen=True)
class TaiwanMarketDependencies:
    market_service: MarketService
    get_market_index_intraday: Callable[[str], dict[str, Any]]
    get_market_index_summary: Callable[..., dict[str, Any]]
    read_cross_market_context: Callable[..., dict[str, Any]]
    read_market_chips_context: Callable[..., dict[str, Any]]
    read_market_volume_state: Callable[..., dict[str, Any]]
    build_taiwan_source_health: Callable[..., dict[str, Any]]
    now: Callable[[], datetime]
    get_market_index_contributions: Callable[..., dict[str, Any]] | None = None
    list_taiwan_corporate_events: Callable[..., dict[str, Any]] | None = None


def _compact_auxiliary_context(value: dict[str, Any]) -> dict[str, Any]:
    compact = ((value.get("data") or {}).get("compact")) if isinstance(value.get("data"), dict) else None
    if isinstance(compact, dict):
        return compact
    return {
        key: value.get(key)
        for key in ("kind", "status", "as_of", "scope", "summary", "missing", "warnings", "slots")
        if key in value
    }


def _compact_source_health(value: dict[str, Any]) -> dict[str, Any]:
    summary = value.get("summary") if isinstance(value.get("summary"), dict) else {}
    error_count = int(summary.get("error_count") or 0)
    stale_count = int(summary.get("stale_count") or 0)
    empty_count = int(summary.get("empty_count") or 0)
    entry_count = int(summary.get("entry_count") or 0)
    ok_count = int(summary.get("ok_count") or 0)
    explicit_status = str(value.get("status") or "").strip().lower()
    if explicit_status:
        status = explicit_status
    elif error_count:
        status = "degraded"
    elif stale_count or empty_count:
        status = "partial"
    elif entry_count and ok_count:
        status = "ready"
    else:
        status = "unavailable"
    return {
        "status": status,
        "as_of": value.get("generated_at") or value.get("as_of"),
        "summary": summary,
        "warnings": list(value.get("warnings") or []),
    }


def _build_tw_market_compact(
    *,
    as_of: str | None,
    latest_trade_date: str | None,
    payload_level: str,
    breadth: dict[str, Any],
    breadth_by_market: dict[str, Any],
    sample_breadth: dict[str, Any],
    sample_coverage: dict[str, Any],
    distribution: dict[str, Any],
    top_gainers: list[dict[str, Any]],
    top_losers: list[dict[str, Any]],
    value_leaders: list[dict[str, Any]],
    top_industries: list[dict[str, Any]],
    weak_industries: list[dict[str, Any]],
    industry_strength_label: str,
    index_intraday: dict[str, Any],
    cross_market: dict[str, Any],
    market_chips: dict[str, Any],
    volume_state: dict[str, Any],
    source_health: dict[str, Any],
    market_aggregates: dict[str, Any],
    slots: dict[str, Any],
) -> dict[str, Any]:
    return {
        "kind": "tw_market_compact_evidence",
        "version": "market_compact_evidence.v1",
        "payload_level": payload_level,
        "target": {"type": "market", "id": "TW", "label": "台股市場", "market": "TW"},
        "as_of": as_of,
        "latest_trade_date": latest_trade_date,
        "breadth": breadth,
        "breadth_by_market": breadth_by_market,
        "sample_breadth": sample_breadth,
        "sample_coverage": sample_coverage,
        "distribution": distribution,
        "top_gainers": top_gainers,
        "top_losers": top_losers,
        "value_leaders": value_leaders,
        "top_industries": top_industries,
        "weak_industries": weak_industries,
        "sample_top_gainers": top_gainers,
        "sample_top_losers": top_losers,
        "sample_value_leaders": value_leaders,
        "sample_top_industries": top_industries,
        "sample_weak_industries": weak_industries,
        "industry_strength_label": industry_strength_label,
        "index_intraday": index_intraday,
        "cross_market": _compact_auxiliary_context(cross_market),
        "market_chips": _compact_auxiliary_context(market_chips),
        "volume_state": volume_state,
        "source_health": _compact_source_health(source_health) if source_health else {},
        "market": market_aggregates,
        "events": {
            "calendar": market_aggregates.get("events_calendar")
        }
        if isinstance(market_aggregates.get("events_calendar"), dict)
        else {},
        "freshness_by_domain": {
            "breadth": (slots.get("market_breadth") or {}).get("status"),
            "sample_ranking": (slots.get("sample_distribution") or {}).get("status"),
            "index_intraday": (slots.get("index_intraday") or {}).get("status"),
            "cross_market": (slots.get("cross_market") or {}).get("status"),
            "market_chips": (slots.get("market_chips") or {}).get("status"),
            "volume": (slots.get("market_volume") or {}).get("status"),
            "indices": (slots.get("market_indices") or {}).get("status"),
            "sectors": (slots.get("market_sectors") or {}).get("status"),
            "index_contributions": (
                slots.get("market_index_contributions") or {}
            ).get("status"),
            "institutional_flow": (
                slots.get("market_institutional_flow") or {}
            ).get("status"),
            "margin_short": (
                slots.get("market_margin_short") or {}
            ).get("status"),
        },
        "freshness_by_capability": market_aggregates.get(
            "freshness_by_capability",
            {},
        ),
        "slots": slots,
    }


def _market_index_ids_from_params(params: dict[str, Any] | None) -> list[str]:
    data_params = _market_data_params(params)
    raw_value = data_params.get("index_ids") or data_params.get("indices") or ("TAIEX", "TPEX")
    if isinstance(raw_value, str):
        values = [item.strip().upper() for item in raw_value.split(",")]
    elif isinstance(raw_value, list):
        values = [str(item).strip().upper() for item in raw_value]
    else:
        values = ["TAIEX", "TPEX"]
    supported = {"TAIEX", "TPEX"}
    selected = [value for value in values if value in supported]
    return list(dict.fromkeys(selected or ["TAIEX", "TPEX"]))[:2]


def _market_index_intraday_pack(
    *,
    dependencies: TaiwanMarketDependencies,
    include_intraday: bool,
    market_data_params: dict[str, Any] | None,
    missing: list[str],
    warnings: list[str],
    source_refs: list[dict[str, Any]],
) -> dict[str, Any]:
    payload_level = _payload_level(market_data_params)
    point_limit = _intraday_point_limit(market_data_params)
    index_ids = _market_index_ids_from_params(market_data_params)
    if not include_intraday:
        return {
            "kind": "market_index_intraday_pack",
            "enabled": False,
            "payload_level": payload_level,
            "bar_limit": point_limit,
            "index_ids": index_ids,
            "indices": [],
            "warnings": [],
        }

    rows: list[dict[str, Any]] = []
    local_warnings: list[str] = []
    _append_source_ref_once(source_refs, {"type": "external_or_cache", "name": "market_index_intraday"})
    for index_id in index_ids:
        try:
            intraday = dependencies.get_market_index_intraday(index_id)
        except Exception as exc:
            message = f"{index_id} index intraday unavailable: {exc}"
            warnings.append(message)
            local_warnings.append(message)
            missing.append(f"market_index_intraday.{index_id}")
            continue

        intraday_bars = _compact_single_intraday_series(
            raw_payload=intraday,
            interval="1m",
            include_intraday=True,
            market_data_params=market_data_params,
        )
        quote = _compact_index_quote(
            index_id=index_id,
            index_snapshot=None,
            intraday=intraday,
        )
        rows.append(
            {
                "index_id": index_id,
                "quote": quote,
                "intraday_bars": intraday_bars,
            }
        )
        series = intraday_bars.get("series") if isinstance(intraday_bars.get("series"), dict) else {}
        if not any(isinstance(item, dict) and item.get("returned_point_count") for item in series.values()):
            missing.append(f"market_index_intraday.{index_id}")

    return {
        "kind": "market_index_intraday_pack",
        "enabled": True,
        "payload_level": payload_level,
        "bar_limit": point_limit,
        "index_ids": index_ids,
        "indices": rows,
        "warnings": local_warnings,
    }


def _json_scalar(value: Any) -> Any:
    isoformat = getattr(value, "isoformat", None)
    return isoformat() if callable(isoformat) else value


def _json_event_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {
            str(key): _json_event_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_json_event_value(item) for item in value]
    return value


def _market_breadth_label(market: str | None, scope: str) -> str:
    normalized_market = str(market or "TWSE").upper()
    market_label = "上市" if normalized_market == "TWSE" else "上櫃" if normalized_market == "TPEX" else normalized_market
    if scope == "full_market":
        return f"{market_label}全市場廣度"
    if scope == "registered_universe":
        return f"{market_label}即時廣度（註冊範圍）"
    if scope == "omi_sample":
        return "OMI 樣本股廣度"
    return f"{market_label}本機資料集廣度"


def _coverage_ratio(
    coverage_count: int,
    universe_count: int,
) -> tuple[float | None, float | None, bool]:
    if universe_count <= 0:
        return None, None, False
    raw_ratio = coverage_count / universe_count
    return min(max(raw_ratio, 0.0), 1.0), raw_ratio, raw_ratio > 1.0


def _industry_strength_label(rows: list[dict[str, Any]]) -> str:
    leading_change = rows[0].get("average_change_pct") if rows else None
    if not isinstance(leading_change, (int, float)):
        return "產業相對表現"
    if leading_change > 0:
        return "強勢產業"
    if leading_change < 0:
        return "相對抗跌產業"
    return "產業相對表現"


def _volume_state_with_breadth_current_value(
    volume_state: dict[str, Any],
    *,
    breadth: dict[str, Any] | None,
) -> dict[str, Any]:
    output = dict(volume_state)
    if output.get("current_cumulative_trade_value") is not None:
        native_markets = [
            str(item.get("market"))
            for item in output.get("markets") or []
            if isinstance(item, dict)
            and item.get("market")
            and item.get("cumulative_trade_value") is not None
        ]
        output.setdefault(
            "available_cumulative_trade_value",
            output.get("current_cumulative_trade_value"),
        )
        output.setdefault("trade_value_available", True)
        output.setdefault("trade_value_complete", True)
        output.setdefault("trade_value_status", "complete")
        output.setdefault("included_markets", native_markets or ["TWSE", "TPEX"])
        output.setdefault("missing_markets", [])
        output.setdefault("trade_value_estimate", None)
        output.setdefault("trade_value_estimate_method", "not_estimated")
        return output
    markets = (
        breadth.get("markets")
        if isinstance(breadth, dict) and isinstance(breadth.get("markets"), dict)
        else {}
    )
    selected = [
        markets.get(market)
        for market in ("TWSE", "TPEX")
        if isinstance(markets.get(market), dict)
    ]
    trade_dates = {
        str(item.get("trade_date"))
        for item in selected
        if item.get("trade_date")
    }
    values = [
        item.get("trade_value")
        for item in selected
        if isinstance(item.get("trade_value"), (int, float))
    ]
    available_markets = [
        str(item.get("market") or item.get("index_id"))
        for item in selected
        if isinstance(item.get("trade_value"), (int, float))
    ]
    missing_markets = [
        market for market in ("TWSE", "TPEX") if market not in available_markets
    ]
    available_value = int(sum(values)) if values else None
    output["available_cumulative_trade_value"] = available_value
    output["trade_value_available"] = available_value is not None
    output["trade_value_complete"] = (
        len(selected) == 2 and len(values) == 2 and len(trade_dates) == 1
    )
    output["trade_value_status"] = (
        "complete"
        if output["trade_value_complete"]
        else "partial"
        if available_value is not None
        else "missing"
    )
    output["included_markets"] = available_markets
    output["missing_markets"] = missing_markets
    output["trade_value_estimate"] = None
    output["trade_value_estimate_method"] = "not_estimated"
    field_status = (
        dict(output.get("field_status"))
        if isinstance(output.get("field_status"), dict)
        else {}
    )
    if len(selected) == 2 and len(values) == 2 and len(trade_dates) == 1:
        output["current_cumulative_trade_value"] = int(sum(values))
        output["current_value_source"] = "official_market_breadth_summary"
        output["trade_date"] = next(iter(trade_dates))
        output["as_of"] = (
            breadth.get("as_of")
            or output.get("as_of")
            or output["trade_date"]
        )
        output["markets"] = [
            {
                "market": item.get("market"),
                "index_id": item.get("index_id"),
                "currency": "TWD",
                "trade_value_unit": "TWD",
                "cumulative_trade_value": item.get("trade_value"),
                "quality_status": item.get("status"),
                "source": item.get("source"),
                "official_flag": item.get("scope") == "full_market",
            }
            for item in selected
        ]
        field_status["current_cumulative_trade_value"] = {
            "status": "available",
            "source": "official_market_breadth_summary",
            "trade_date": output["trade_date"],
        }
    else:
        field_status["current_cumulative_trade_value"] = {
            "status": "missing",
            "reason": (
                "TWSE and TPEX same-date official trade values are not both "
                "available."
            ),
        }
    output["field_status"] = field_status
    return output


def _market_evidence_as_of(
    *,
    fallback_trade_date: Any,
    breadth: dict[str, Any] | None,
    index_intraday: dict[str, Any],
    volume_state: dict[str, Any],
) -> str | None:
    candidates: list[str] = []
    for item in index_intraday.get("indices") or []:
        if not isinstance(item, dict):
            continue
        quote = item.get("quote") if isinstance(item.get("quote"), dict) else {}
        value = quote.get("quote_time") or quote.get("trade_date")
        if value:
            candidates.append(str(value))
    if volume_state.get("as_of"):
        candidates.append(str(volume_state["as_of"]))
    if isinstance(breadth, dict):
        value = breadth.get("trade_date")
        if value:
            candidates.append(str(value))
    if fallback_trade_date:
        candidates.append(str(_json_scalar(fallback_trade_date)))
    parsed: list[tuple[datetime, str]] = []
    for value in candidates:
        try:
            normalized = value.replace("Z", "+00:00")
            timestamp = datetime.fromisoformat(normalized)
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            else:
                timestamp = timestamp.astimezone(timezone.utc)
        except (TypeError, ValueError):
            continue
        parsed.append((timestamp, value))
    return max(parsed, default=(None, None), key=lambda item: item[0])[1]


def _market_breadth_from_index_summary(
    *,
    db: Session,
    dependencies: TaiwanMarketDependencies,
    warnings: list[str],
    source_refs: list[dict[str, Any]],
) -> dict[str, Any] | None:
    try:
        summary = dependencies.get_market_index_summary(db, force_refresh=False)
    except Exception as exc:
        warnings.append(f"Taiwan market index breadth unavailable: {exc}")
        return None

    indices = summary.get("indices") if isinstance(summary, dict) else None
    breadth_by_market: dict[str, dict[str, Any]] = {}
    for index_id, market in (("TAIEX", "TWSE"), ("TPEX", "TPEX")):
        index_item = next(
            (
                item
                for item in indices or []
                if isinstance(item, dict) and item.get("index_id") == index_id
            ),
            None,
        )
        raw_breadth = index_item.get("breadth") if isinstance(index_item, dict) else None
        if not isinstance(raw_breadth, dict) or not raw_breadth.get("total_count"):
            continue

        scope = str(raw_breadth.get("scope") or "local_dataset")
        breadth = {key: _json_scalar(value) for key, value in raw_breadth.items()}
        breadth["market"] = str(raw_breadth.get("market") or market).upper()
        breadth["index_id"] = index_id
        breadth["scope"] = scope
        breadth["label"] = str(
            raw_breadth.get("label")
            or _market_breadth_label(breadth["market"], scope)
        )
        breadth_status = (
            index_item.get("breadth_status")
            if isinstance(index_item.get("breadth_status"), dict)
            else {}
        )
        breadth["status"] = str(breadth_status.get("status") or "ready")
        breadth["currency"] = "TWD"
        breadth["trade_value_unit"] = "TWD"
        advance_count = int(breadth.get("advance_count") or 0)
        decline_count = int(breadth.get("decline_count") or 0)
        comparison_count = advance_count + decline_count
        breadth["positive_ratio"] = (
            advance_count / comparison_count if comparison_count else None
        )
        breadth["advance_decline_ratio"] = (
            advance_count / decline_count if decline_count else None
        )
        total_count = int(breadth.get("total_count") or 0)
        unchanged_count = int(breadth.get("unchanged_count") or 0)
        classified_count = advance_count + decline_count + unchanged_count
        unknown_count = max(total_count - classified_count, 0)
        universe_count = int(
            breadth.get("universe_count")
            or breadth.get("coverage_count")
            or total_count
        )
        breadth["universe_count"] = universe_count
        breadth["coverage_count"] = total_count
        (
            breadth["coverage_ratio"],
            breadth["coverage_ratio_raw"],
            coverage_overflow,
        ) = _coverage_ratio(
            total_count,
            universe_count,
        )
        breadth["coverage_overflow"] = coverage_overflow
        if coverage_overflow:
            breadth["status"] = "partial"
            breadth["coverage_issue"] = "coverage_count_exceeds_universe"
            warnings.append(
                f"{market} breadth coverage count {total_count} exceeds "
                f"universe count {universe_count}; ratio was bounded to 1.0."
            )
        breadth["classified_count"] = classified_count
        breadth["unknown_count"] = unknown_count
        breadth["reconciliation_status"] = (
            "balanced"
            if (
                total_count > 0
                and classified_count == total_count
                and not coverage_overflow
            )
            else "partial"
            if (
                total_count > 0
                and classified_count < total_count
                and not coverage_overflow
            )
            else "inconsistent"
        )
        breadth["reconciliation_formula"] = (
            "advance_count+decline_count+unchanged_count=total_count"
        )
        breadth_by_market[market] = breadth

    if not breadth_by_market:
        return None

    missing_markets = [
        market for market in ("TWSE", "TPEX") if market not in breadth_by_market
    ]
    component_statuses = {
        str(item.get("status") or "ready") for item in breadth_by_market.values()
    }
    component_scopes = {
        str(item.get("scope") or "local_dataset") for item in breadth_by_market.values()
    }

    def _sum_count(key: str) -> int:
        return sum(int(item.get(key) or 0) for item in breadth_by_market.values())

    def _sum_optional(key: str) -> int | None:
        values = [item.get(key) for item in breadth_by_market.values()]
        return sum(int(value) for value in values if value is not None) if any(
            value is not None for value in values
        ) else None

    advance_count = _sum_count("advance_count")
    decline_count = _sum_count("decline_count")
    unchanged_count = _sum_count("unchanged_count")
    total_count = _sum_count("total_count")
    classified_count = advance_count + decline_count + unchanged_count
    unknown_count = max(total_count - classified_count, 0)
    comparison_count = advance_count + decline_count
    trade_dates = {
        str(item.get("trade_date"))
        for item in breadth_by_market.values()
        if item.get("trade_date")
    }
    status = (
        "ready"
        if not missing_markets
        and component_statuses == {"ready"}
        and len(trade_dates) <= 1
        else "partial"
    )
    trade_value_included_markets = [
        market
        for market, item in breadth_by_market.items()
        if item.get("trade_value") is not None
    ]
    trade_value_missing_markets = [
        market
        for market in ("TWSE", "TPEX")
        if market not in trade_value_included_markets
    ]
    cumulative_trade_value = _sum_optional("trade_value")
    market_completion_ratio = len(breadth_by_market) / 2
    combined_universe_count = _sum_count("universe_count")
    (
        combined_coverage_ratio,
        combined_coverage_ratio_raw,
        combined_coverage_overflow,
    ) = _coverage_ratio(total_count, combined_universe_count)
    breadth = {
        "market": "TW",
        "scope": "full_market" if component_scopes == {"full_market"} else "mixed",
        "label": "台股上市櫃市場廣度" if not missing_markets else "台股市場廣度（部分市場）",
        "trade_date": next(iter(trade_dates)) if len(trade_dates) == 1 else None,
        "as_of": _json_scalar(summary.get("as_of")) if isinstance(summary, dict) else None,
        "source": "app.market.indices.summary",
        "status": status,
        "advance_count": advance_count,
        "decline_count": decline_count,
        "unchanged_count": unchanged_count,
        "total_count": total_count,
        "universe_count": combined_universe_count,
        "coverage_count": total_count,
        "coverage_ratio": combined_coverage_ratio,
        "coverage_ratio_raw": combined_coverage_ratio_raw,
        "coverage_overflow": combined_coverage_overflow,
        "coverage_issue": (
            "coverage_count_exceeds_universe"
            if combined_coverage_overflow
            else None
        ),
        "classified_count": classified_count,
        "unknown_count": unknown_count,
        "reconciliation_status": (
            "balanced"
            if total_count > 0
            and classified_count == total_count
            and all(
                item.get("reconciliation_status") == "balanced"
                for item in breadth_by_market.values()
            )
            else "partial"
        ),
        "reconciliation_formula": (
            "advance_count+decline_count+unchanged_count=total_count"
        ),
        "limit_up_count": _sum_optional("limit_up_count"),
        "limit_down_count": _sum_optional("limit_down_count"),
        "trade_value": cumulative_trade_value,
        "trade_value_available": cumulative_trade_value is not None,
        "trade_value_complete": not trade_value_missing_markets,
        "trade_value_status": (
            "complete"
            if not trade_value_missing_markets
            else "partial"
            if cumulative_trade_value is not None
            else "missing"
        ),
        "trade_value_included_markets": trade_value_included_markets,
        "trade_value_missing_markets": trade_value_missing_markets,
        "trade_value_estimate": None,
        "trade_value_estimate_method": "not_estimated",
        "currency": "TWD",
        "trade_value_unit": "TWD",
        "positive_ratio": advance_count / comparison_count if comparison_count else None,
        "advance_decline_ratio": advance_count / decline_count if decline_count else None,
        "included_markets": list(breadth_by_market),
        "missing_markets": missing_markets,
        "markets": breadth_by_market,
        "market_completion_ratio": market_completion_ratio,
        "close_reconciliation": {
            "status": (
                "confirmed"
                if status == "ready" and market_completion_ratio == 1
                else "partial"
            ),
            "expected_markets": ["TWSE", "TPEX"],
            "confirmed_markets": list(breadth_by_market),
            "missing_markets": missing_markets,
            "completion_ratio": market_completion_ratio,
            "trade_date_aligned": len(trade_dates) <= 1,
            "official_sources": [
                item.get("source")
                for item in breadth_by_market.values()
                if item.get("source")
            ],
        },
    }
    _append_source_ref_once(
        source_refs,
        {"type": "derived", "name": "app.market.indices.summary"},
    )
    return breadth


def _daily_sample_coverage(
    db: Session,
    *,
    sample_stock_ids: set[str],
) -> dict[str, Any]:
    universe_rows = (
        db.query(StockMaster.stock_id, StockMaster.market)
        .filter(StockMaster.is_active.is_(True))
        .filter(StockMaster.instrument_type == "stock")
        .all()
    )
    universe_by_market: dict[str, int] = {"TWSE": 0, "TPEX": 0, "OTHER": 0}
    sample_by_market: dict[str, int] = {"TWSE": 0, "TPEX": 0, "OTHER": 0}

    def _market_key(value: Any) -> str:
        normalized = str(value or "").strip().upper()
        if normalized in {"TWSE", "上市"}:
            return "TWSE"
        if normalized in {"TPEX", "上櫃"}:
            return "TPEX"
        return "OTHER"

    universe_stock_ids: set[str] = set()
    known_sample_ids: set[str] = set()
    for stock_id, market in universe_rows:
        universe_stock_ids.add(stock_id)
        key = _market_key(market)
        universe_by_market[key] += 1
        if stock_id in sample_stock_ids:
            sample_by_market[key] += 1
            known_sample_ids.add(stock_id)
    sample_by_market["OTHER"] += len(sample_stock_ids - known_sample_ids)

    universe_count = len(universe_rows)
    sample_count = len(sample_stock_ids)
    covered_universe_count = len(sample_stock_ids & universe_stock_ids)
    coverage_ratio = (
        covered_universe_count / universe_count if universe_count else None
    )
    return {
        "scope": "active_stock_master",
        "status": (
            "complete"
            if universe_count and covered_universe_count >= universe_count
            else "partial"
            if universe_count and sample_count
            else "empty"
            if universe_count
            else "unknown"
        ),
        "sample_count": sample_count,
        "covered_universe_count": covered_universe_count,
        "universe_count": universe_count,
        "coverage_ratio": coverage_ratio,
        "sample_count_by_market": sample_by_market,
        "universe_count_by_market": universe_by_market,
    }


def _capability_parameters(
    data_params: dict[str, Any],
    capability_id: str,
) -> dict[str, Any]:
    values = data_params.get("capability_parameters")
    if not isinstance(values, dict):
        return {}
    selected = values.get(capability_id)
    return dict(selected) if isinstance(selected, dict) else {}


def _market_indices_capability(
    *,
    db: Session,
    dependencies: TaiwanMarketDependencies,
) -> dict[str, Any]:
    try:
        summary = dependencies.get_market_index_summary(
            db,
            force_refresh=False,
        )
    except Exception as exc:
        return {
            "kind": "tw_market_indices",
            "status": "unavailable",
            "as_of": None,
            "items": [],
            "source": "market_index_summary",
            "missing": ["market_index_summary"],
            "warnings": [f"Taiwan market indices unavailable: {exc}"],
        }
    raw_items = (
        summary.get("indices")
        if isinstance(summary, dict)
        and isinstance(summary.get("indices"), list)
        else []
    )
    items: list[dict[str, Any]] = []
    for index_id, market, label in (
        ("TAIEX", "TWSE", "臺灣加權股價指數"),
        ("TPEX", "TPEX", "櫃買指數"),
    ):
        item = next(
            (
                row
                for row in raw_items
                if isinstance(row, dict)
                and str(row.get("index_id") or "").upper() == index_id
            ),
            None,
        )
        if item is None:
            continue
        close = (
            item.get("close")
            if item.get("close") is not None
            else item.get("value")
        )
        change = item.get("change")
        change_pct = item.get("change_pct")
        if (
            change_pct is None
            and isinstance(close, (int, float))
            and isinstance(change, (int, float))
            and close != change
        ):
            change_pct = change / (close - change) * 100
        items.append(
            {
                "index_id": index_id,
                "name": item.get("name") or item.get("label") or label,
                "market": str(item.get("market") or market).upper(),
                "close": close,
                "change": change,
                "change_pct": change_pct,
                "trade_date": _json_scalar(
                    item.get("trade_date")
                    or item.get("date")
                    or item.get("as_of")
                ),
                "source": item.get("source")
                or summary.get("source")
                or "market_index_summary",
                "freshness": item.get("freshness")
                or item.get("quote_status")
                or {},
            }
        )
    as_of = _latest_timestamp(
        [
            str(item.get("trade_date"))
            for item in items
            if item.get("trade_date")
        ]
    )
    status = "ready" if len(items) == 2 else "partial" if items else "missing"
    return {
        "kind": "tw_market_indices",
        "status": status,
        "as_of": as_of,
        "count": len(items),
        "items": items,
        "source": "market_index_summary",
        "missing": (
            []
            if len(items) == 2
            else [
                f"market_index_summary.{index_id}"
                for index_id in ("TAIEX", "TPEX")
                if not any(
                    row.get("index_id") == index_id for row in items
                )
            ]
        ),
        "warnings": [],
    }


def _market_index_contributions_capability(
    *,
    db: Session,
    dependencies: TaiwanMarketDependencies,
    data_params: dict[str, Any],
) -> dict[str, Any]:
    parameters = _capability_parameters(
        data_params,
        "market.index_contributions",
    )
    index_ids = [
        str(value).strip().upper()
        for value in parameters.get("index_ids") or ["TAIEX", "TPEX"]
        if str(value).strip()
    ]
    limit = int(parameters.get("limit") or 10)
    if dependencies.get_market_index_contributions is None:
        return {
            "kind": "tw_market_index_contributions",
            "status": "unavailable",
            "as_of": None,
            "indices": {},
            "missing": ["market_index_contributions"],
            "warnings": ["Market index contribution reader is not configured."],
        }
    if data_params.get("external_fetch_allowed") is not True:
        return {
            "kind": "tw_market_index_contributions",
            "status": "not_requested",
            "as_of": None,
            "indices": {},
            "cache_policy": "external_fetch_required_bounded",
            "missing": [],
            "warnings": [
                "Index contributions were not read because bounded external "
                "fetch is disabled for this request."
            ],
        }

    rows: dict[str, Any] = {}
    warnings: list[str] = []
    for index_id in index_ids:
        try:
            rows[index_id] = dependencies.get_market_index_contributions(
                index_id=index_id,
                limit=limit,
                db=db,
            )
        except Exception as exc:
            warnings.append(f"{index_id} contributions unavailable: {exc}")
    trade_dates = [
        str(item.get("trade_date"))
        for item in rows.values()
        if isinstance(item, dict) and item.get("trade_date")
    ]
    return {
        "kind": "tw_market_index_contributions",
        "status": (
            "ready"
            if len(rows) == len(index_ids)
            else "partial"
            if rows
            else "unavailable"
        ),
        "as_of": max(trade_dates) if trade_dates else None,
        "index_ids": index_ids,
        "indices": rows,
        "method": "estimated_market_cap_weight",
        "cache_policy": "bounded_external_fetch",
        "missing": [
            f"market_index_contributions.{index_id}"
            for index_id in index_ids
            if index_id not in rows
        ],
        "warnings": warnings,
    }


def _official_market_flow_capabilities(
    market_chips: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    official = (
        market_chips.get("official_market_aggregate")
        if isinstance(market_chips.get("official_market_aggregate"), dict)
        else {}
    )
    rows = [
        row
        for row in official.get("rows") or []
        if isinstance(row, dict)
    ]
    same_trade_date = official.get("same_trade_date") is True
    trade_dates = [
        str(value)
        for value in official.get("trade_dates") or []
        if value
    ]
    status = (
        "ready"
        if rows and same_trade_date
        else "partial"
        if rows
        else "missing"
    )

    def sum_field(field: str) -> int | float | None:
        values = [
            row.get(field)
            for row in rows
            if row.get(field) is not None
        ]
        return sum(values) if values and same_trade_date else None

    common = {
        "status": status,
        "trade_date": trade_dates[0]
        if len(trade_dates) == 1
        else None,
        "trade_dates": trade_dates,
        "same_trade_date": same_trade_date,
        "markets": list(official.get("markets") or []),
        "rows": rows,
        "source_grade": (
            "official"
            if rows
            and all(str(row.get("source_grade") or "") == "official" for row in rows)
            else "mixed"
            if rows
            else "missing"
        ),
        "freshness": {
            "status": status,
            "as_of": trade_dates[0] if len(trade_dates) == 1 else None,
            "event_time_basis": "taiwan_completed_trade_date",
        },
        "missing": [] if rows else ["market_chip_daily"],
        "warnings": (
            []
            if same_trade_date or not rows
            else [
                "TWSE and TPEx official market-chip rows have different "
                "trade dates; combined totals are withheld."
            ]
        ),
    }
    institutional = {
        "kind": "tw_market_institutional_flow",
        **common,
        "unit": "TWD",
        "aggregate": {
            "total_institutional_net_value": sum_field(
                "total_institutional_net_value"
            ),
            "foreign_investor_net_value": sum_field(
                "foreign_investor_net_value"
            ),
            "investment_trust_net_value": sum_field(
                "investment_trust_net_value"
            ),
            "dealer_net_value": sum_field("dealer_net_value"),
        },
    }
    margin_short = {
        "kind": "tw_market_margin_short",
        **common,
        "unit_semantics": {
            "margin_balance_change_value": "TWD",
            "margin_balance_change_shares": "shares",
            "short_balance_change_shares": "shares",
        },
        "aggregate": {
            "margin_balance_change_value": sum_field(
                "margin_balance_change_value"
            ),
            "margin_balance_change_shares": sum_field(
                "margin_balance_change_shares"
            ),
            "short_balance_change_shares": sum_field(
                "short_balance_change_shares"
            ),
        },
        "margin_status": [
            {
                "index_id": row.get("index_id"),
                "market": row.get("market"),
                "status": (
                    "ready"
                    if row.get("margin_balance_change_value") is not None
                    or row.get("margin_balance_change_shares") is not None
                    else "missing"
                ),
            }
            for row in rows
        ],
    }
    return institutional, margin_short


def _events_calendar_capability(
    *,
    dependencies: TaiwanMarketDependencies,
    data_params: dict[str, Any],
    generated_at: datetime,
) -> dict[str, Any]:
    parameters = _capability_parameters(data_params, "events.calendar")
    if dependencies.list_taiwan_corporate_events is None:
        return {
            "kind": "tw_market_event_calendar",
            "status": "unavailable",
            "as_of": None,
            "events": [],
            "cache_policy": "cache_only",
            "missing": ["taiwan_corporate_events"],
            "warnings": [
                "Taiwan corporate-event calendar reader is not configured."
            ],
        }

    try:
        date_from = (
            date.fromisoformat(str(parameters["date_from"]))
            if parameters.get("date_from")
            else None
        )
        date_to = (
            date.fromisoformat(str(parameters["date_to"]))
            if parameters.get("date_to")
            else None
        )
    except ValueError:
        return {
            "kind": "tw_market_event_calendar",
            "status": "invalid",
            "as_of": generated_at.isoformat(),
            "events": [],
            "cache_policy": "cache_only",
            "missing": [],
            "warnings": [
                "events.calendar date_from and date_to must use YYYY-MM-DD."
            ],
        }
    if date_from and date_to and date_to < date_from:
        return {
            "kind": "tw_market_event_calendar",
            "status": "invalid",
            "as_of": generated_at.isoformat(),
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "events": [],
            "cache_policy": "cache_only",
            "missing": [],
            "warnings": ["events.calendar date_to must not precede date_from."],
        }
    if (
        date_from
        and date_to
        and date_to - date_from > timedelta(days=366)
    ):
        return {
            "kind": "tw_market_event_calendar",
            "status": "invalid",
            "as_of": generated_at.isoformat(),
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "events": [],
            "cache_policy": "cache_only",
            "missing": [],
            "warnings": [
                "events.calendar date range must not exceed 366 days."
            ],
        }

    event_types = {
        str(value).strip().lower()
        for value in parameters.get("event_types") or []
        if str(value).strip()
    }
    markets = {
        str(value).strip().upper()
        for value in parameters.get("markets") or ["TWSE", "TPEX"]
        if str(value).strip()
    }
    stock_ids = {
        str(value).strip()
        for value in parameters.get("stock_ids") or []
        if str(value).strip()
    }
    limit = max(1, min(int(parameters.get("limit") or 300), 500))
    offset = max(0, min(int(parameters.get("offset") or 0), 5000))
    listing = dependencies.list_taiwan_corporate_events(
        event_types=event_types or None,
        markets=markets or None,
        stock_ids=stock_ids or None,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
        now=generated_at,
    )
    rows = [
        _json_event_value(row)
        for row in listing.get("results") or []
        if isinstance(row, dict)
    ]
    total_count = int(listing.get("total_count") or len(rows))
    sources = (
        listing.get("sources")
        if isinstance(listing.get("sources"), dict)
        else {}
    )
    source_statuses = {
        str(item.get("status") or "missing").lower()
        for item in sources.values()
        if isinstance(item, dict)
    }
    if source_statuses and source_statuses <= {"current"}:
        status = "ready"
    elif not source_statuses or source_statuses <= {"missing"}:
        status = "missing"
    else:
        status = "partial"
    warning = str(listing.get("warning") or "").strip() or None
    return {
        "kind": "tw_market_event_calendar",
        "status": status,
        "as_of": _json_scalar(listing.get("as_of")),
        "date_from": _json_scalar(listing.get("date_from")),
        "date_to": _json_scalar(listing.get("date_to")),
        "event_types": sorted(event_types),
        "markets": sorted(markets),
        "stock_ids": sorted(stock_ids),
        "pagination": {
            "offset": offset,
            "limit": limit,
            "available_count": total_count,
            "returned_count": len(rows),
            "has_more": offset + len(rows) < total_count,
        },
        "result_count": len(rows),
        "events": rows,
        "source": "taiwan_corporate_event_cache",
        "sources": _json_event_value(sources),
        "cache_policy": "cache_only",
        "empty_result_is_valid": status == "ready" and not rows,
        "missing": (
            ["taiwan_corporate_events"] if status == "missing" else []
        ),
        "warnings": [warning] if warning else [],
    }


def _sample_sector_capability(
    *,
    industry_summary: list[dict[str, Any]],
    sample_coverage: dict[str, Any],
    as_of: str | None,
) -> dict[str, Any]:
    rows = [
        {
            "sector_id": str(item.get("industry") or ""),
            "name": item.get("industry"),
            "trade_date": as_of,
            "change_pct": item.get("average_change_pct"),
            "advance_count": item.get("advance_count"),
            "decline_count": item.get("decline_count"),
            "trade_value": item.get("trade_value"),
            "universe_count": item.get("count"),
            "coverage_count": item.get("count"),
            "coverage_ratio": 1.0 if item.get("count") else None,
            "ranking_basis": "omi_local_daily_sample_stock_aggregation",
        }
        for item in sorted(
            industry_summary,
            key=lambda item: (
                -(item.get("average_change_pct") or 0),
                str(item.get("industry") or ""),
            ),
        )
    ]
    return {
        "kind": "tw_market_sectors",
        "status": "partial" if rows else "missing",
        "as_of": as_of,
        "ranking_basis": "omi_local_daily_sample_stock_aggregation",
        "is_full_market": False,
        "coverage": sample_coverage,
        "count": len(rows),
        "items": rows,
        "missing": (
            ["market_daily_price.full_market_sector_index"]
            if rows
            else ["market_daily_price.sector_sample"]
        ),
        "warnings": [
            "Sector rows are derived from the latest OMI local stock sample and "
            "must not be treated as official full-market sector-index rankings."
        ],
    }


def _aggregate_freshness(
    capability_id: str,
    payload: dict[str, Any],
    *,
    dataset: str,
) -> dict[str, Any]:
    status = str(payload.get("status") or "missing")
    return {
        "capability": capability_id,
        "dataset": dataset,
        "status": status,
        "is_current": status == "ready",
        "latest": payload.get("as_of") or payload.get("trade_date"),
        "event_time_basis": "taiwan_completed_trade_date",
        "refresh_recommended": status
        in {"missing", "stale", "unavailable"},
        "missing": list(payload.get("missing") or []),
        "warnings": list(payload.get("warnings") or []),
    }


def _market_aggregate_slots(
    *,
    market_aggregates: dict[str, Any],
    payload_level: str,
) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for slot_name, capability_id, key in (
        ("market_indices", "market.indices", "indices"),
        ("market_sectors", "market.sectors", "sectors"),
        (
            "market_index_contributions",
            "market.index_contributions",
            "index_contributions",
        ),
        (
            "market_institutional_flow",
            "market.institutional_flow",
            "institutional_flow",
        ),
        (
            "market_margin_short",
            "market.margin_short",
            "margin_short",
        ),
        (
            "events_calendar",
            "events.calendar",
            "events_calendar",
        ),
    ):
        payload = market_aggregates.get(key)
        if not isinstance(payload, dict):
            continue
        output[slot_name] = {
            "status": str(payload.get("status") or "missing"),
            "capability": capability_id,
            "payload_ref": f"market.{key}",
            "payload_level": payload_level,
            "priority": "core",
            "as_of": payload.get("as_of") or payload.get("trade_date"),
            "freshness": (
                market_aggregates.get("freshness_by_capability", {}).get(
                    capability_id,
                    {},
                )
            ),
            "missing": list(payload.get("missing") or []),
            "warnings": list(payload.get("warnings") or []),
        }
    return output


def read_market_overview(
    db: Session,
    limit: int = 10,
    *,
    include_intraday: bool = False,
    market_data_params: dict[str, Any] | None = None,
    dependencies: TaiwanMarketDependencies,
) -> dict[str, Any]:
    generated_at = dependencies.now()
    latest_trade_date = dependencies.market_service.get_latest_trade_date(db)
    missing: list[str] = []
    warnings: list[str] = []
    source_refs: list[dict[str, Any]] = [{"type": "table", "name": "market_daily_price"}]
    payload_level = _payload_level(market_data_params)
    data_params = _market_data_params(market_data_params)
    requested_domains = {
        str(value).strip().lower()
        for value in data_params.get("requested_domains") or []
        if str(value).strip()
    }
    excluded_domains = {
        str(value).strip().lower()
        for value in data_params.get("excluded_domains") or []
        if str(value).strip()
    }
    requested_capabilities = {
        str(value).strip()
        for value in data_params.get("requested_capabilities") or []
        if str(value).strip()
    }
    source_health_requested = (
        "source.health" in requested_capabilities
        or "source_health" in requested_domains
    )
    selective_request = bool(requested_domains)
    explicit_domain_selection = data_params.get("explicit_domain_selection") is True

    def wants(domain: str) -> bool:
        return (
            domain not in excluded_domains
            and (not selective_request or domain in requested_domains)
        )

    omit_sample_rankings = (
        "sample_ranking" in excluded_domains
        or (
            explicit_domain_selection
            and
            selective_request
            and requested_domains <= {"breadth", "volume"}
        )
    )

    cross_market = (
        dependencies.read_cross_market_context(db=db, now=generated_at)
        if wants("cross_market")
        else {
            "kind": "cross_market_context",
            "status": "not_requested",
            "missing": [],
            "warnings": [],
            "source_refs": [],
        }
    )
    market_chips = (
        dependencies.read_market_chips_context(db=db, limit=limit)
        if wants("chips")
        else {
            "kind": "market_chips_context",
            "status": "not_requested",
            "missing": [],
            "warnings": [],
            "source_refs": [],
        }
    )
    market_aggregates: dict[str, Any] = {
        "freshness_by_capability": {}
    }
    if "events.calendar" in requested_capabilities:
        market_aggregates["events_calendar"] = (
            _events_calendar_capability(
                dependencies=dependencies,
                data_params=data_params,
                generated_at=generated_at,
            )
        )
        calendar_payload = market_aggregates["events_calendar"]
        market_aggregates["freshness_by_capability"][
            "events.calendar"
        ] = {
            "capability": "events.calendar",
            "dataset": "taiwan_corporate_events",
            "status": calendar_payload.get("status"),
            "is_current": calendar_payload.get("status") == "ready",
            "latest": calendar_payload.get("as_of"),
            "event_time_basis": "official_event_date",
            "refresh_recommended": calendar_payload.get("status")
            in {"missing", "stale", "unavailable"},
            "missing": list(calendar_payload.get("missing") or []),
            "warnings": list(calendar_payload.get("warnings") or []),
        }
    if "market.indices" in requested_capabilities:
        market_aggregates["indices"] = _market_indices_capability(
            db=db,
            dependencies=dependencies,
        )
        market_aggregates["freshness_by_capability"][
            "market.indices"
        ] = _aggregate_freshness(
            "market.indices",
            market_aggregates["indices"],
            dataset="market_index_summary",
        )
    if "market.index_contributions" in requested_capabilities:
        market_aggregates[
            "index_contributions"
        ] = _market_index_contributions_capability(
            db=db,
            dependencies=dependencies,
            data_params=data_params,
        )
        market_aggregates["freshness_by_capability"][
            "market.index_contributions"
        ] = _aggregate_freshness(
            "market.index_contributions",
            market_aggregates["index_contributions"],
            dataset="market_index_contributions",
        )
    institutional_flow, margin_short = (
        _official_market_flow_capabilities(market_chips)
    )
    if "market.institutional_flow" in requested_capabilities:
        market_aggregates["institutional_flow"] = institutional_flow
        market_aggregates["freshness_by_capability"][
            "market.institutional_flow"
        ] = _aggregate_freshness(
            "market.institutional_flow",
            institutional_flow,
            dataset="market_chip_daily",
        )
    if "market.margin_short" in requested_capabilities:
        market_aggregates["margin_short"] = margin_short
        market_aggregates["freshness_by_capability"][
            "market.margin_short"
        ] = _aggregate_freshness(
            "market.margin_short",
            margin_short,
            dataset="market_chip_daily",
        )
    volume_state = (
        dependencies.read_market_volume_state(db=db)
        if wants("volume")
        else {
            "kind": "taiwan_market_volume_state",
            "status": "not_requested",
            "warnings": [],
            "source_refs": [],
        }
    )
    source_health: dict[str, Any] = {}
    if source_health_requested:
        try:
            source_health = dependencies.build_taiwan_source_health(
                db,
                now=generated_at,
                sync_snapshots=False,
            )
        except Exception as exc:
            source_health = {
                "kind": "taiwan_source_health",
                "status": "error",
                "generated_at": generated_at.isoformat(),
                "summary": {},
                "entries": [],
                "warnings": ["Taiwan source health could not be read."],
                "provider_error": f"{type(exc).__name__}: {exc}",
            }
            warnings.extend(source_health["warnings"])
    for source_ref in cross_market.get("source_refs") or []:
        if isinstance(source_ref, dict):
            _append_source_ref_once(source_refs, source_ref)
    if wants("cross_market") and cross_market.get("status") != "ready":
        warnings.append(
            "Cross-market auxiliary context is partial; inspect data.cross_market.missing before using it."
        )
    for source_ref in market_chips.get("source_refs") or []:
        if isinstance(source_ref, dict):
            _append_source_ref_once(source_refs, source_ref)
    for source_ref in volume_state.get("source_refs") or []:
        if isinstance(source_ref, dict):
            _append_source_ref_once(source_refs, source_ref)
    if wants("volume") and volume_state.get("status") != "ready":
        missing.append("market_volume.same_time_baseline_20d")
        warnings.extend(str(item) for item in volume_state.get("warnings") or [] if item)
    index_intraday = _market_index_intraday_pack(
        dependencies=dependencies,
        include_intraday=include_intraday,
        market_data_params=market_data_params,
        missing=missing,
        warnings=warnings,
        source_refs=source_refs,
    )
    market_breadth = _market_breadth_from_index_summary(
        db=db,
        dependencies=dependencies,
        warnings=warnings,
        source_refs=source_refs,
    )
    breadth_by_market = (
        market_breadth.get("markets", {})
        if isinstance(market_breadth, dict)
        and isinstance(market_breadth.get("markets"), dict)
        else {}
    )
    volume_state = _volume_state_with_breadth_current_value(
        volume_state,
        breadth=market_breadth,
    )
    evidence_as_of = _market_evidence_as_of(
        fallback_trade_date=latest_trade_date,
        breadth=market_breadth,
        index_intraday=index_intraday,
        volume_state=volume_state,
    )
    if isinstance(market_breadth, dict) and market_breadth.get("status") != "ready":
        missing_markets = [
            str(market).strip().lower()
            for market in market_breadth.get("missing_markets") or []
            if str(market).strip()
        ]
        missing.extend(f"market_breadth.{market}" for market in missing_markets)
        if missing_markets:
            warnings.append(
                "Taiwan market breadth is partial; missing full-market coverage for "
                f"{', '.join(market.upper() for market in missing_markets)}."
            )

    if latest_trade_date is None:
        sample_coverage = _daily_sample_coverage(db, sample_stock_ids=set())
        if market_breadth is None:
            missing.append("market_breadth.full_market")
        no_daily_warnings = [
            "No market daily rows are available in the local database; movers and industry distribution are unavailable.",
            *warnings,
        ]
        slots = _build_tw_market_slots(
            as_of=evidence_as_of,
            payload_level=payload_level,
            breadth=market_breadth or {},
            sample_coverage=sample_coverage,
            distribution={},
            industry_rows=[],
            index_intraday=index_intraday,
            cross_market=cross_market,
            market_chips=market_chips,
            volume_state=volume_state,
            missing=list(dict.fromkeys(["market_daily_price", *missing])),
            warnings=no_daily_warnings,
        )
        if "market.sectors" in requested_capabilities:
            market_aggregates["sectors"] = _sample_sector_capability(
                industry_summary=[],
                sample_coverage=sample_coverage,
                as_of=evidence_as_of,
            )
            market_aggregates["freshness_by_capability"][
                "market.sectors"
            ] = _aggregate_freshness(
                "market.sectors",
                market_aggregates["sectors"],
                dataset="market_daily_price",
            )
        slots.update(
            _market_aggregate_slots(
                market_aggregates=market_aggregates,
                payload_level=payload_level,
            )
        )
        compact = _build_tw_market_compact(
            as_of=evidence_as_of,
            latest_trade_date=None,
            payload_level=payload_level,
            breadth=market_breadth or {},
            breadth_by_market=breadth_by_market,
            sample_breadth={},
            sample_coverage=sample_coverage,
            distribution={},
            top_gainers=[],
            top_losers=[],
            value_leaders=[],
            top_industries=[],
            weak_industries=[],
            industry_strength_label="產業相對表現",
            index_intraday=index_intraday,
            cross_market=cross_market,
            market_chips=market_chips,
            volume_state=volume_state,
            source_health=source_health,
            market_aggregates=market_aggregates,
            slots=slots,
        )
        envelope = {
            "kind": "market_overview",
            "generated_at": generated_at,
            "as_of": evidence_as_of,
            "scope": {},
            "data": {
                "latest_trade_date": None,
                "breadth": market_breadth or {},
                "breadth_by_market": breadth_by_market,
                "sample_breadth": {},
                "sample_coverage": sample_coverage,
                "top_gainers": [],
                "top_losers": [],
                "index_intraday": index_intraday,
                "cross_market": cross_market,
                "market_chips": market_chips,
                "volume_state": volume_state,
                "source_health": source_health,
                "market": market_aggregates,
                "freshness_by_capability": market_aggregates.get(
                    "freshness_by_capability",
                    {},
                ),
                "slots": slots,
                "compact": compact,
            },
            "missing": list(dict.fromkeys(["market_daily_price", *missing])),
            "warnings": no_daily_warnings,
            "source_refs": source_refs,
        }
        return _with_evidence_passport(
            envelope,
            freshness={
                "is_current": False,
                "missing": envelope["missing"],
                "warnings": envelope["warnings"],
            },
        )

    rows = dependencies.market_service.list_market_daily_prices(
        db=db,
        trade_date=latest_trade_date,
        limit=10000,
    )
    stock_ids = sorted({row.stock_id for row in rows if row.stock_id})
    sample_coverage = _daily_sample_coverage(db, sample_stock_ids=set(stock_ids))
    stock_industries: dict[str, str | None] = {}
    for index in range(0, len(stock_ids), 500):
        chunk = stock_ids[index : index + 500]
        for stock in db.query(StockMaster).filter(StockMaster.stock_id.in_(chunk)).all():
            stock_industries[stock.stock_id] = normalize_tw_industry_label(
                stock.industry or stock.category,
                fallback="未分類",
            )
    ranked = [
        {
            "stock_id": row.stock_id,
            "stock_name": row.stock_name,
            "close_price": row.close_price,
            "price_change": row.price_change,
            "change_pct": (
                (row.price_change / (row.close_price - row.price_change)) * 100
                if row.price_change is not None
                and row.close_price is not None
                and row.close_price != row.price_change
                else None
            ),
            "trade_volume": row.trade_volume,
            "trade_value": row.trade_value,
            "transaction_count": row.transaction_count,
            "industry": stock_industries.get(row.stock_id),
        }
        for row in rows
    ]
    ranked_with_change = [row for row in ranked if row["change_pct"] is not None]
    top_gainers = sorted(
        [row for row in ranked_with_change if row["change_pct"] > 0],
        key=lambda row: row["change_pct"],
        reverse=True,
    )[:limit]
    top_losers = sorted(
        [row for row in ranked_with_change if row["change_pct"] < 0],
        key=lambda row: row["change_pct"],
    )[:limit]
    value_leaders = sorted(
        [row for row in ranked if row["trade_value"] is not None],
        key=lambda row: row["trade_value"] or 0,
        reverse=True,
    )[:limit]

    advance_count = sum(1 for row in rows if (row.price_change or 0) > 0)
    decline_count = sum(1 for row in rows if (row.price_change or 0) < 0)
    unchanged_count = sum(1 for row in rows if (row.price_change or 0) == 0)
    total_trade_value = sum(row.trade_value or 0 for row in rows) or None
    total_count = len(rows)
    average_change_pct = (
        sum(row["change_pct"] for row in ranked_with_change) / len(ranked_with_change)
        if ranked_with_change
        else None
    )
    positive_ratio = advance_count / len(ranked_with_change) if ranked_with_change else None
    advance_decline_ratio = advance_count / decline_count if decline_count else None
    top_value_sum = sum(row["trade_value"] or 0 for row in value_leaders)
    top_value_share = (
        top_value_sum / total_trade_value
        if total_trade_value and value_leaders
        else None
    )
    sample_breadth = {
        "market": "TW",
        "scope": "omi_sample",
        "label": "OMI 樣本股廣度",
        "trade_date": latest_trade_date.isoformat(),
        "source": "market_daily_price",
        "advance_count": advance_count,
        "decline_count": decline_count,
        "unchanged_count": unchanged_count,
        "total_count": total_count,
        "trade_value": total_trade_value,
        "average_change_pct": average_change_pct,
        "positive_ratio": positive_ratio,
        "advance_decline_ratio": advance_decline_ratio,
        "top_value_share": top_value_share,
        "coverage": sample_coverage,
    }
    distribution = {
        "limit_up_count": sum(
            1 for row in ranked_with_change if (row["change_pct"] or 0) >= 9.5
        ),
        "strong_up_count": sum(
            1 for row in ranked_with_change if 5 <= (row["change_pct"] or 0) < 9.5
        ),
        "mild_up_count": sum(
            1 for row in ranked_with_change if 0 < (row["change_pct"] or 0) < 5
        ),
        "flat_count": unchanged_count,
        "mild_down_count": sum(
            1 for row in ranked_with_change if -5 < (row["change_pct"] or 0) < 0
        ),
        "strong_down_count": sum(
            1 for row in ranked_with_change if -9.5 < (row["change_pct"] or 0) <= -5
        ),
        "limit_down_count": sum(
            1 for row in ranked_with_change if (row["change_pct"] or 0) <= -9.5
        ),
    }
    industry_groups: dict[str, list[dict[str, Any]]] = {}
    for row in ranked_with_change:
        industry = normalize_tw_industry_label(row.get("industry"), fallback="未分類")
        industry_groups.setdefault(industry, []).append(row)

    industry_summary = []
    for industry, group_rows in industry_groups.items():
        changes = [
            row["change_pct"]
            for row in group_rows
            if isinstance(row.get("change_pct"), (int, float))
        ]
        if not changes:
            continue
        trade_value = sum(row.get("trade_value") or 0 for row in group_rows) or None
        top_row = max(
            group_rows,
            key=lambda row: (
                row.get("trade_value") or 0,
                row.get("change_pct") or 0,
            ),
        )
        industry_summary.append(
            {
                "industry": industry,
                "count": len(group_rows),
                "advance_count": sum(1 for value in changes if value > 0),
                "decline_count": sum(1 for value in changes if value < 0),
                "average_change_pct": sum(changes) / len(changes),
                "trade_value": trade_value,
                "top_stock_id": top_row.get("stock_id"),
                "top_stock_name": top_row.get("stock_name"),
            }
        )
    if "market.sectors" in requested_capabilities:
        market_aggregates["sectors"] = _sample_sector_capability(
            industry_summary=industry_summary,
            sample_coverage=sample_coverage,
            as_of=evidence_as_of,
        )
        market_aggregates["freshness_by_capability"][
            "market.sectors"
        ] = _aggregate_freshness(
            "market.sectors",
            market_aggregates["sectors"],
            dataset="market_daily_price",
        )
    top_industries = sorted(
        [row for row in industry_summary if row["industry"] != "未分類" and row["count"] >= 2],
        key=lambda row: (
            row["average_change_pct"],
            row.get("trade_value") or 0,
        ),
        reverse=True,
    )[:6]
    weak_industries = sorted(
        [row for row in industry_summary if row["industry"] != "未分類" and row["count"] >= 2],
        key=lambda row: (
            row["average_change_pct"],
            -(row.get("trade_value") or 0),
        ),
    )[:6]
    industry_strength_label = _industry_strength_label(top_industries)
    if omit_sample_rankings:
        top_gainers = []
        top_losers = []
        value_leaders = []
        top_industries = []
        weak_industries = []
        distribution = {}
        industry_strength_label = "樣本排行未請求"
        warnings.append(
            "Sample-derived movers and industry rankings were omitted by the "
            "bounded request selection."
        )

    if not ranked_with_change:
        missing.append("market_daily_price.change_pct")
    if not omit_sample_rankings and sample_coverage.get("status") != "complete":
        missing.append("market_daily_price.full_market_coverage")
        warnings.append(
            "Daily ranking and industry sample coverage is "
            f"{sample_coverage.get('sample_count')}/{sample_coverage.get('universe_count')} "
            "active stocks; sample-derived rankings must not be treated as full-market results."
        )

    if market_breadth is None:
        market_breadth = sample_breadth
        missing.append("market_breadth.full_market")
        warnings.append(
            "Full-market breadth is unavailable; breadth falls back to a clearly labeled OMI local sample."
        )
    else:
        warnings.append(
            "Market breadth comes from the market-index summary and is independent of the selected watchlist."
        )
    if not omit_sample_rankings:
        warnings.append(
            "Top movers, value leaders, distribution, and industry rankings still use the latest OMI local daily sample."
        )

    slots = _build_tw_market_slots(
        as_of=evidence_as_of,
        payload_level=payload_level,
        breadth=market_breadth,
        sample_coverage=sample_coverage,
        distribution=distribution,
        industry_rows=[*top_industries, *weak_industries],
        index_intraday=index_intraday,
        cross_market=cross_market,
        market_chips=market_chips,
        volume_state=volume_state,
        missing=missing,
        warnings=warnings,
    )
    slots.update(
        _market_aggregate_slots(
            market_aggregates=market_aggregates,
            payload_level=payload_level,
        )
    )
    compact = _build_tw_market_compact(
        as_of=evidence_as_of,
        latest_trade_date=latest_trade_date.isoformat(),
        payload_level=payload_level,
        breadth=market_breadth,
        breadth_by_market=breadth_by_market,
        sample_breadth=sample_breadth,
        sample_coverage=sample_coverage,
        distribution=distribution,
        top_gainers=top_gainers,
        top_losers=top_losers,
        value_leaders=value_leaders,
        top_industries=top_industries,
        weak_industries=weak_industries,
        industry_strength_label=industry_strength_label,
        index_intraday=index_intraday,
        cross_market=cross_market,
        market_chips=market_chips,
        volume_state=volume_state,
        source_health=source_health,
        market_aggregates=market_aggregates,
        slots=slots,
    )
    envelope = {
        "kind": "market_overview",
        "generated_at": generated_at,
        "as_of": evidence_as_of,
        "scope": {},
        "data": {
            "latest_trade_date": latest_trade_date.isoformat(),
            "breadth": market_breadth,
            "breadth_by_market": breadth_by_market,
            "sample_breadth": sample_breadth,
            "sample_coverage": sample_coverage,
            "distribution": distribution,
            "top_gainers": top_gainers,
            "top_losers": top_losers,
            "value_leaders": value_leaders,
            "top_industries": top_industries,
            "weak_industries": weak_industries,
            "sample_top_gainers": top_gainers,
            "sample_top_losers": top_losers,
            "sample_value_leaders": value_leaders,
            "sample_top_industries": top_industries,
            "sample_weak_industries": weak_industries,
            "industry_strength_label": industry_strength_label,
            "index_intraday": index_intraday,
            "cross_market": cross_market,
            "market_chips": market_chips,
            "volume_state": volume_state,
            "source_health": source_health,
            "market": market_aggregates,
            "freshness_by_capability": market_aggregates.get(
                "freshness_by_capability",
                {},
            ),
            "slots": slots,
            "compact": compact,
        },
        "missing": missing,
        "warnings": warnings,
        "source_refs": source_refs,
    }
    return _with_evidence_passport(
        envelope,
        freshness={
            "is_current": not missing,
            "missing": missing,
            "warnings": envelope["warnings"],
        },
    )
