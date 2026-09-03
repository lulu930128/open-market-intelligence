from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from time import perf_counter
from typing import Any, Callable, Protocol

from sqlalchemy.orm import Session

from app.ai.market_context.common import append_source_ref_once as _append_source_ref_once
from app.ai.market_context.taiwan_bar_projection import project_taiwan_bar_series
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
from app.market.calendar_status import build_taiwan_calendar_status
from app.market.index_resolution import project_taiwan_index_headline
from app.market.taiwan_industries import normalize_tw_industry_label
from app.market.trading_calendar import (
    taiwan_market_session_phase,
)
from app.market.tw_market_breadth_contract import (
    TW_MARKET_BREADTH_STOCK_STATE_VERSION,
    TW_MARKET_BREADTH_VERSION,
)


class MarketService(Protocol):
    def get_latest_trade_date(self, db: Session) -> Any: ...

    def list_market_daily_prices(
        self,
        *,
        db: Session,
        trade_date: Any,
        limit: int,
    ) -> list[Any]: ...

    def read_market_daily_snapshot(
        self,
        db: Session,
        *,
        trade_date: Any,
        include_etf: bool,
    ) -> Any: ...


@dataclass(frozen=True)
class TaiwanMarketDependencies:
    market_service: MarketService
    read_taiwan_bars: Callable[..., Any]
    read_taiwan_index_intraday_bars: Callable[..., Any]
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
    sample_slot = (
        slots.get("sample_distribution")
        if isinstance(slots.get("sample_distribution"), dict)
        else {}
    )
    sample_status = str(
        sample_slot.get("status")
        or (
            "ready"
            if sample_coverage.get("status") == "complete"
            else "partial"
        )
    )
    sample_warnings = (
        []
        if sample_coverage.get("status") == "complete"
        else [
            "This ranking is derived from the bounded OMI local daily sample "
            "and must not be treated as a full-market screener."
        ]
    )
    sample_ranking = {
        "kind": "tw_market_sample_ranking",
        "status": sample_status,
        "scope": "omi_local_daily_sample",
        "scope_label": "OMI 台股本機日線樣本",
        "is_full_market": False,
        "coverage_status": "sample_only",
        "as_of": as_of,
        "latest_trade_date": latest_trade_date,
        "source": "tw.daily.ohlcv",
        "currency": "TWD",
        "price_unit": "TWD_per_share",
        "volume_unit": "shares",
        "trade_value_unit": "TWD",
        "unit_semantics": {
            "close_price": "TWD_per_share",
            "trade_volume": "shares",
            "trade_value": "TWD",
            "change_pct": "percent",
        },
        "sample_breadth": sample_breadth,
        "sample_coverage": sample_coverage,
        "distribution": distribution,
        "top_gainers": top_gainers,
        "top_losers": top_losers,
        "value_leaders": value_leaders,
        "top_industries": top_industries,
        "weak_industries": weak_industries,
        "industry_strength_label": industry_strength_label,
        "warnings": sample_warnings,
    }
    return {
        "kind": "tw_market_compact_evidence",
        "version": "market_compact_evidence.v1",
        "payload_level": payload_level,
        "target": {"type": "market", "id": "TW", "label": "台股市場", "market": "TW"},
        "as_of": as_of,
        "latest_trade_date": latest_trade_date,
        "breadth": breadth,
        "breadth_by_market": breadth_by_market,
        "sample_ranking": sample_ranking,
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
    db: Session,
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
    try:
        index_summary = dependencies.get_market_index_summary(
            db,
            force_refresh=False,
        )
    except Exception as exc:
        index_summary = {}
        message = f"Taiwan resolved index context unavailable: {exc}"
        warnings.append(message)
        local_warnings.append(message)
    index_snapshots = {
        str(item.get("index_id") or "").strip().upper(): item
        for item in index_summary.get("indices") or []
        if isinstance(item, dict)
    }
    _append_source_ref_once(source_refs, {"type": "external_or_cache", "name": "market_index_intraday"})
    for index_id in index_ids:
        try:
            bar_series = dependencies.read_taiwan_index_intraday_bars(
                db=db,
                index_id=index_id,
                requested_at=dependencies.now(),
            )
            intraday = project_taiwan_bar_series(
                bar_series,
                session_scope="current_session",
            )
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
            index_snapshot=index_snapshots.get(index_id),
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

    quotes = [
        item.get("quote")
        for item in rows
        if isinstance(item.get("quote"), dict)
    ]
    requested_count = len(index_ids)
    returned_count = len(quotes)

    def _quote_flag(quote: dict[str, Any], key: str) -> bool:
        freshness = quote.get("freshness")
        return bool(
            quote.get(key)
            or isinstance(freshness, dict) and freshness.get(key)
        )

    current_session_count = sum(
        1
        for quote in quotes
        if bool(
            quote.get("last_trade_is_current_session")
            or quote.get("is_latest_session_quote")
        )
    )
    live_index_count = sum(
        1
        for quote in quotes
        if _quote_flag(quote, "is_live")
        and bool(
            quote.get("last_trade_is_current_session")
            or quote.get("is_latest_session_quote")
        )
    )
    all_requested_returned = bool(
        requested_count and returned_count == requested_count
    )
    all_current_session = bool(
        all_requested_returned
        and current_session_count == requested_count
    )
    all_live = bool(
        all_requested_returned
        and live_index_count == requested_count
    )
    expected_trade_dates = {
        str(intraday_bars.get("expected_trade_date"))
        for row in rows
        if isinstance((intraday_bars := row.get("intraday_bars")), dict)
        and intraday_bars.get("expected_trade_date")
    }
    expected_trade_date = (
        next(iter(expected_trade_dates))
        if len(expected_trade_dates) == 1
        else None
    )

    def _consensus(key: str) -> str | None:
        values = {
            str(quote.get(key))
            for quote in quotes
            if quote.get(key) is not None
        }
        if not values:
            return None
        return next(iter(values)) if len(values) == 1 else "mixed"

    event_time = _latest_timestamp(
        [
            quote.get("quote_time")
            or quote.get("last_trade_time")
            or quote.get("trade_date")
            for quote in quotes
        ]
    )
    coverage_status = (
        "ready"
        if all_requested_returned
        else "partial"
        if returned_count
        else "unavailable"
    )
    freshness_status = (
        "live"
        if all_live
        else "partial"
        if returned_count
        else "unavailable"
    )

    return {
        "kind": "market_index_intraday_pack",
        "enabled": True,
        "session_scope": "current_session",
        "expected_trade_date": expected_trade_date,
        "payload_level": payload_level,
        "bar_limit": point_limit,
        "index_ids": index_ids,
        "indices": rows,
        "requested_index_count": requested_count,
        "returned_index_count": returned_count,
        "live_index_count": live_index_count,
        "current_session_index_count": current_session_count,
        "partial_index_count": max(requested_count - live_index_count, 0),
        "coverage_status": coverage_status,
        "is_live": all_live,
        "is_realtime": all_live,
        "is_current_session": all_current_session,
        "is_latest_session_quote": all_current_session,
        "market_status": _consensus("market_status"),
        "current_session_phase": _consensus("current_session_phase"),
        "session_phase": _consensus("current_session_phase"),
        "event_time": event_time,
        "freshness": {
            "status": freshness_status,
            "is_live": all_live,
            "is_realtime": all_live,
            "is_current_session": all_current_session,
            "coverage_status": coverage_status,
            "live_index_count": live_index_count,
            "requested_index_count": requested_count,
        },
        "warnings": local_warnings,
    }


def _json_scalar(value: Any) -> Any:
    isoformat = getattr(value, "isoformat", None)
    return isoformat() if callable(isoformat) else value


def _date_iso(value: Any) -> str | None:
    scalar = _json_scalar(value)
    if scalar is None:
        return None
    text = str(scalar).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        try:
            return date.fromisoformat(text).isoformat()
        except ValueError:
            return text


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
        output.setdefault("trade_value_coverage_status", "complete")
        output.setdefault("trade_value_authority_status", "unavailable")
        output.setdefault(
            "trade_value_status",
            f"{output['trade_value_authority_status']}_complete"
            if output["trade_value_authority_status"] != "unavailable"
            else "complete",
        )
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
    output["trade_value_coverage_status"] = (
        "complete"
        if output["trade_value_complete"]
        else "partial"
        if available_value is not None
        else "missing"
    )
    selected_authorities = [
        "estimated" if item.get("trade_value_is_estimate") else "official"
        for item in selected
        if isinstance(item.get("trade_value"), (int, float))
    ]
    output["trade_value_authority_status"] = (
        selected_authorities[0]
        if selected_authorities
        and all(value == selected_authorities[0] for value in selected_authorities)
        else "mixed"
        if selected_authorities
        else "unavailable"
    )
    output["trade_value_status"] = (
        f"{output['trade_value_authority_status']}_complete"
        if output["trade_value_coverage_status"] == "complete"
        else output["trade_value_coverage_status"]
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
                "trade_value_semantics": item.get("trade_value_semantics"),
                "trade_value_is_estimate": bool(item.get("trade_value_is_estimate")),
                "quality_status": item.get("status"),
                "source": item.get("source"),
                "official_flag": not bool(item.get("trade_value_is_estimate")),
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
    return _latest_timestamp(candidates)


def _latest_timestamp(values: list[Any]) -> str | None:
    parsed: list[tuple[datetime, str]] = []
    for raw_value in values:
        scalar = _json_scalar(raw_value)
        if scalar is None:
            continue
        value = str(scalar).strip()
        if not value:
            continue
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
        breadth = {
            key: _json_event_value(value) for key, value in raw_breadth.items()
        }
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
        universe_count = int(
            breadth.get("universe_count")
            or total_count
        )
        coverage_count = int(
            breadth.get("coverage_count")
            if breadth.get("coverage_count") is not None
            else classified_count
        )
        unknown_count = int(
            breadth.get("unknown_count")
            if breadth.get("unknown_count") is not None
            else max(universe_count - coverage_count, 0)
        )
        breadth["universe_count"] = universe_count
        breadth["coverage_count"] = coverage_count
        (
            breadth["coverage_ratio"],
            breadth["coverage_ratio_raw"],
            coverage_overflow,
        ) = _coverage_ratio(
            coverage_count,
            universe_count,
        )
        breadth["coverage_overflow"] = coverage_overflow
        if coverage_overflow:
            breadth["status"] = "partial"
            breadth["coverage_issue"] = "coverage_count_exceeds_universe"
            warnings.append(
                f"{market} breadth coverage count {coverage_count} exceeds "
                f"universe count {universe_count}; ratio was bounded to 1.0."
            )
        breadth["classified_count"] = classified_count
        breadth["unknown_count"] = unknown_count
        breadth["reconciliation_status"] = (
            "balanced"
            if (
                universe_count > 0
                and classified_count == coverage_count
                and coverage_count + unknown_count == universe_count
                and not coverage_overflow
            )
            else "partial"
            if (
                universe_count > 0
                and classified_count <= coverage_count
                and coverage_count + unknown_count <= universe_count
                and not coverage_overflow
            )
            else "inconsistent"
        )
        breadth["reconciliation_formula"] = (
            "advance_count+decline_count+unchanged_count=coverage_count; "
            "coverage_count+unknown_count=universe_count"
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
    component_versions = {
        str(item.get("version") or "legacy_unverified")
        for item in breadth_by_market.values()
    }
    component_state_versions = {
        str(item.get("state_contract_version") or "legacy_unverified")
        for item in breadth_by_market.values()
    }
    component_price_semantics = {
        str(item.get("price_semantics") or "legacy_unverified")
        for item in breadth_by_market.values()
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
    coverage_count = _sum_count("coverage_count")
    universe_count = _sum_count("universe_count")
    classified_count = advance_count + decline_count + unchanged_count
    unknown_count = _sum_count("unknown_count")
    comparison_count = advance_count + decline_count
    trade_dates = {
        str(item.get("trade_date"))
        for item in breadth_by_market.values()
        if item.get("trade_date")
    }
    status = (
        "pending"
        if not missing_markets and component_statuses == {"pending"}
        else (
            "ready"
            if not missing_markets
            and component_statuses == {"ready"}
            and len(trade_dates) <= 1
            else "partial"
        )
    )
    market_sessions = {
        str(item.get("market_session") or "unknown")
        for item in breadth_by_market.values()
    }
    market_session = (
        next(iter(market_sessions)) if len(market_sessions) == 1 else "mixed"
    )
    snapshot_as_of = _latest_timestamp(
        [
            item.get("snapshot_as_of") or item.get("as_of")
            for item in breadth_by_market.values()
        ]
    )
    auction_components = {
        market: dict(item["auction_breadth"])
        for market, item in breadth_by_market.items()
        if isinstance(item.get("auction_breadth"), dict)
    }
    auction_statuses = {
        str(item.get("status") or "unavailable")
        for item in auction_components.values()
    }
    auction_breadth = None
    if auction_components:
        auction_coverage_count = sum(
            int(item.get("coverage_count") or 0)
            for item in auction_components.values()
        )
        auction_universe_count = sum(
            int(item.get("universe_count") or 0)
            for item in auction_components.values()
        )
        auction_breadth = {
            "market": "TW",
            "status": (
                "provisional"
                if "provisional" in auction_statuses
                else "unavailable"
                if "unavailable" in auction_statuses
                else "not_applicable"
            ),
            "market_session": market_session,
            "scope": (
                next(iter(component_scopes))
                if len(component_scopes) == 1
                else "mixed"
            ),
            "as_of": _latest_timestamp(
                [item.get("as_of") for item in auction_components.values()]
            ),
            "advance_count": sum(
                int(item.get("advance_count") or 0)
                for item in auction_components.values()
            ),
            "decline_count": sum(
                int(item.get("decline_count") or 0)
                for item in auction_components.values()
            ),
            "unchanged_count": sum(
                int(item.get("unchanged_count") or 0)
                for item in auction_components.values()
            ),
            "coverage_count": auction_coverage_count,
            "universe_count": auction_universe_count,
            "unknown_count": max(
                auction_universe_count - auction_coverage_count,
                0,
            ),
            "price_semantics": "auction_indicative",
            "is_provisional": "provisional" in auction_statuses,
            "decision_usable": False,
            "source": "twse_mis_pz_ts",
            "markets": auction_components,
        }
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
    trade_value_authorities = [
        "estimated" if item.get("trade_value_is_estimate") else "official"
        for item in breadth_by_market.values()
        if item.get("trade_value") is not None
    ]
    trade_value_authority_status = (
        trade_value_authorities[0]
        if trade_value_authorities
        and all(value == trade_value_authorities[0] for value in trade_value_authorities)
        else "mixed"
        if trade_value_authorities
        else "unavailable"
    )
    trade_value_coverage_status = (
        "complete"
        if not trade_value_missing_markets
        else "partial"
        if cumulative_trade_value is not None
        else "missing"
    )
    market_completion_ratio = len(breadth_by_market) / 2
    (
        combined_coverage_ratio,
        combined_coverage_ratio_raw,
        combined_coverage_overflow,
    ) = _coverage_ratio(coverage_count, universe_count)
    breadth = {
        "market": "TW",
        "version": (
            next(iter(component_versions))
            if len(component_versions) == 1
            else "mixed"
        ),
        "state_contract_version": (
            next(iter(component_state_versions))
            if len(component_state_versions) == 1
            else "mixed"
        ),
        "scope": (
            next(iter(component_scopes)) if len(component_scopes) == 1 else "mixed"
        ),
        "label": "台股上市櫃市場廣度" if not missing_markets else "台股市場廣度（部分市場）",
        "trade_date": next(iter(trade_dates)) if len(trade_dates) == 1 else None,
        "as_of": snapshot_as_of,
        "snapshot_as_of": snapshot_as_of,
        "market_session": market_session,
        "price_semantics": (
            next(iter(component_price_semantics))
            if len(component_price_semantics) == 1
            else "mixed"
        ),
        "decision_usable": bool(
            status == "ready"
            and component_versions == {TW_MARKET_BREADTH_VERSION}
            and component_state_versions
            == {TW_MARKET_BREADTH_STOCK_STATE_VERSION}
            and all(
                item.get("decision_usable") is True
                for item in breadth_by_market.values()
            )
        ),
        "is_provisional": any(
            bool(item.get("is_provisional")) for item in breadth_by_market.values()
        ),
        "source": "app.market.indices.summary",
        "status": status,
        "advance_count": advance_count,
        "decline_count": decline_count,
        "unchanged_count": unchanged_count,
        "total_count": total_count,
        "universe_count": universe_count,
        "coverage_count": coverage_count,
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
            if universe_count > 0
            and classified_count == coverage_count
            and coverage_count + unknown_count == universe_count
            and all(
                item.get("reconciliation_status") == "balanced"
                for item in breadth_by_market.values()
            )
            else "partial"
        ),
        "reconciliation_formula": (
            "advance_count+decline_count+unchanged_count=coverage_count; "
            "coverage_count+unknown_count=universe_count"
        ),
        "limit_up_count": _sum_optional("limit_up_count"),
        "limit_down_count": _sum_optional("limit_down_count"),
        "trade_value": cumulative_trade_value,
        "trade_value_available": cumulative_trade_value is not None,
        "trade_value_complete": not trade_value_missing_markets,
        "trade_value_coverage_status": trade_value_coverage_status,
        "trade_value_authority_status": trade_value_authority_status,
        "trade_value_status": (
            f"{trade_value_authority_status}_complete"
            if trade_value_coverage_status == "complete"
            else trade_value_coverage_status
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
        "auction_breadth": auction_breadth,
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
    snapshot: Any,
) -> dict[str, Any]:
    universe_by_market = {
        **{"TWSE": 0, "TPEX": 0, "OTHER": 0},
        **dict(getattr(snapshot, "universe_count_by_market", ()) or ()),
    }
    sample_by_market = {
        **{"TWSE": 0, "TPEX": 0, "OTHER": 0},
        **dict(getattr(snapshot, "selected_count_by_market", ()) or ()),
    }
    universe_count = int(getattr(snapshot, "universe_count", 0) or 0)
    sample_count = len(getattr(snapshot, "rows", ()) or ())
    covered_universe_count = sum(sample_by_market.values())
    coverage_ratio = (
        covered_universe_count / universe_count if universe_count else None
    )
    return {
        "scope": "canonical_active_stock_universe",
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


def _daily_sample_coverage_warning(sample_coverage: dict[str, Any]) -> str:
    return (
        "Daily ranking and industry sample coverage is "
        f"{sample_coverage.get('sample_count')}/{sample_coverage.get('universe_count')} "
        "ordinary active stocks; sample-derived rankings must not be treated as "
        "full-market results."
    )


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
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    checked_at = generated_at or (
        dependencies.now()
        if callable(getattr(dependencies, "now", None))
        else datetime.now(timezone.utc)
    )
    session_phase = taiwan_market_session_phase(checked_at)
    active_index_session = session_phase in {"regular", "closing_auction"}
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
        headline = project_taiwan_index_headline(item)
        if headline is None:
            continue
        current_data_core = (
            item.get("current_data_core")
            if isinstance(item.get("current_data_core"), dict)
            else {}
        )
        current = (
            current_data_core.get("index")
            if isinstance(current_data_core.get("index"), dict)
            else item.get("current_observation")
            if isinstance(item.get("current_observation"), dict)
            else {}
        )
        completed_official = item.get("completed_official_index")
        if not isinstance(completed_official, dict):
            completed_official = None
        close = (
            completed_official.get("close")
            if completed_official is not None
            else item.get("close")
            if item.get("close") is not None
            else item.get("value")
        )
        change = (
            completed_official.get("change")
            if completed_official is not None
            else item.get("change")
        )
        change_pct = (
            completed_official.get("change_pct")
            if completed_official is not None
            else item.get("change_pct")
        )
        if (
            change_pct is None
            and isinstance(close, (int, float))
            and isinstance(change, (int, float))
            and close != change
        ):
            change_pct = change / (close - change) * 100
        official_as_of = _json_scalar(
            (completed_official or {}).get("lineage", {}).get("event_at")
            or item.get("as_of")
            or item.get("quote_time")
            or item.get("trade_date")
            or item.get("date")
        )
        trade_date = _date_iso(
            (completed_official or {}).get("trade_date")
            or item.get("trade_date")
            or item.get("date")
            or official_as_of
        )
        current_for_requested_session = headline["decision_usable"] is True
        selected_value = headline.get("value")
        selected_as_of = headline.get("event_time") or headline.get("trade_date")
        selected_trade_date = _date_iso(
            headline.get("trade_date") or selected_as_of
        )
        selected_change = headline.get("change")
        selected_previous_close = headline.get("previous_close")
        selected_change_pct = headline.get("change_pct")
        provisional_estimate = bool(headline.get("provisional_estimate"))
        finalization = str(headline.get("finalization") or "unknown")
        quote_semantics = str(
            headline.get("quote_semantics") or "unavailable"
        )
        items.append(
            {
                "index_id": index_id,
                "name": item.get("name") or item.get("label") or label,
                "market": str(item.get("market") or market).upper(),
                "close": selected_value,
                "official_close": {
                    "value": close,
                    "change": change,
                    "change_pct": change_pct,
                    "trade_date": trade_date,
                    "as_of": official_as_of,
                    "source": (completed_official or {}).get("lineage", {}).get("source")
                    or item.get("source")
                    or summary.get("source")
                    or "market_index_summary",
                },
                "live_snapshot": (
                    {
                        "value": current.get("close"),
                        "change": current.get("change"),
                        "change_pct": current.get("change_pct"),
                        "event_time": _json_scalar(current.get("as_of")),
                        "source": current.get("source"),
                        "is_partial": current.get("provisional") is True,
                    }
                    if current and active_index_session
                    else None
                ),
                "value": selected_value,
                "latest_value": selected_value,
                "previous_close": selected_previous_close,
                "change": selected_change,
                "change_pct": selected_change_pct,
                "trade_date": selected_trade_date,
                "event_time": _json_scalar(headline.get("event_time")),
                "as_of": _json_scalar(selected_as_of),
                "quote_semantics": quote_semantics,
                "resolution_quote_semantics": quote_semantics,
                "current_for_requested_session": current_for_requested_session,
                "decision_usable": bool(headline.get("decision_usable")),
                "coverage_status": headline.get("coverage_status"),
                "finalization": finalization,
                "provisional": provisional_estimate,
                "delivery_status": headline.get("delivery_status"),
                "source": headline.get("source"),
                "provider": headline.get("provider"),
                "resolution_version": headline.get("resolution_version"),
                "resolution_id": headline.get("resolution_id"),
                "acquisition_policy": headline.get("acquisition_policy"),
                "selected_candidate": headline.get("selected_candidate"),
                "selection_reason": headline.get("selection_reason"),
                "current_observation": current,
                "official_close_status": headline.get("official_close_status"),
                "official_source": bool(headline.get("official_source")),
                "official_close_confirmed": bool(
                    headline.get("official_close_confirmed")
                ),
                "authority": headline.get("authority"),
                "canonical_status_ref": "resolution",
                "resolution": item.get("resolution"),
                "compatibility_fallback": bool(
                    headline.get("compatibility_fallback")
                ),
                "limitations": list(headline.get("limitations") or []),
                "warnings": list(headline.get("warnings") or []),
                "freshness": {
                    "status": headline.get("freshness_status"),
                    "decision_usable": bool(headline.get("decision_usable")),
                    "event_time": _json_scalar(headline.get("event_time")),
                },
                "source_freshness": item.get("freshness")
                or item.get("quote_status")
                or {},
            }
        )
    selected_as_of_values = [
        str(item.get("as_of")) for item in items if item.get("as_of")
    ]
    official_dates = {
        str(_dict.get("trade_date"))
        for item in items
        if isinstance((_dict := item.get("official_close")), dict)
        and _dict.get("trade_date")
    }
    current_count = sum(
        item.get("current_for_requested_session") is True for item in items
    )
    is_complete = len(items) == 2
    if active_index_session:
        status = (
            "ready"
            if current_count == 2
            else "partial"
            if current_count or len(official_dates) > 1
            else "latest_completed_session"
            if is_complete
            else "missing"
        )
    elif session_phase in {"post_close", "market_closed"}:
        status = (
            "ready"
            if is_complete and current_count == 2
            else "partial"
            if items
            else "missing"
        )
    else:
        status = (
            "partial"
            if len(official_dates) > 1
            else "latest_completed_session"
            if is_complete
            else "partial"
            if items
            else "missing"
        )
    as_of = _latest_timestamp(selected_as_of_values)
    return {
        "kind": "tw_market_indices",
        "status": status,
        "as_of": as_of,
        "oldest_as_of": min(selected_as_of_values) if selected_as_of_values else None,
        "newest_as_of": max(selected_as_of_values) if selected_as_of_values else None,
        "mixed_as_of": len(set(selected_as_of_values)) > 1,
        "mixed_trade_dates": len(official_dates) > 1,
        "market_session": session_phase,
        "current_for_requested_session": current_count == 2,
        "is_current": current_count == 2,
        "decision_usable": is_complete and current_count == 2,
        "canonical_status_ref": "items[].resolution",
        "status_authority": "shared_market_data_core",
        "is_complete": is_complete,
        "coverage_status": "complete" if is_complete else "partial" if items else "missing",
        "observation_mix": sorted(
            {
                str(item.get("quote_semantics"))
                for item in items
                if item.get("quote_semantics")
            }
        ),
        "count": len(items),
        "items": items,
        "source": "shared_market_data_core",
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
        "warnings": (
            ["Taiwan market indices contain mixed official trade dates."]
            if len(official_dates) > 1
            else [
                "Current-session Taiwan index snapshots are unavailable; "
                "official completed-session closes are retained as reference."
            ]
            if active_index_session and current_count < 2
            else []
        ),
    }


def _market_index_contributions_capability(
    *,
    db: Session,
    dependencies: TaiwanMarketDependencies,
    data_params: dict[str, Any],
) -> dict[str, Any]:
    checked_at = (
        dependencies.now()
        if callable(getattr(dependencies, "now", None))
        else datetime.now(timezone.utc)
    )
    calendar_status = build_taiwan_calendar_status(now=checked_at)
    calendar_phase = str(calendar_status.get("phase") or "unknown")
    expected_trade_date = (
        calendar_status.get("date")
        if calendar_status.get("is_trading_day") is True
        and calendar_phase not in {"preopen_pending", "preopen", "market_closed"}
        else calendar_status.get("previous_trading_day")
    )
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
            "status": "not_fetched_due_to_policy",
            "as_of": None,
            "indices": {},
            "applicability_status": "applicable",
            "availability_status": "unknown",
            "policy_satisfied": False,
            "execution_status": "not_executed",
            "decision_usable": False,
            "reason_codes": ["EXTERNAL_FETCH_DISABLED_FOR_REQUEST"],
            "cache_policy": "external_fetch_required_bounded",
            "missing": [],
            "warnings": [
                "Index contributions were not read because bounded external "
                "fetch is disabled for this request."
            ],
        }

    rows: dict[str, Any] = {}
    warnings: list[str] = []
    tool_runs: list[dict[str, Any]] = []
    tool_budget = (
        data_params.get("tool_budget")
        if isinstance(data_params.get("tool_budget"), dict)
        else {}
    )
    max_external_fetches = tool_budget.get("max_external_fetches")
    if (
        isinstance(max_external_fetches, bool)
        or not isinstance(max_external_fetches, int)
    ):
        max_external_fetches = len(index_ids)
    max_external_fetches = max(0, max_external_fetches)
    for position, index_id in enumerate(index_ids):
        requested_capabilities = ["market.index_contributions"]
        if position >= max_external_fetches:
            warnings.append(
                f"{index_id} contributions skipped because the external "
                "fetch budget was exhausted."
            )
            tool_runs.append(
                {
                    "tool": "tw.read_market_index_contributions",
                    "provider": None,
                    "status": "skipped_budget",
                    "external_fetch": True,
                    "duration_ms": 0,
                    "writes_cache": False,
                    "requested_capabilities": requested_capabilities,
                    "arguments": {
                        "index_id": index_id,
                        "limit": limit,
                        "requested_capabilities": requested_capabilities,
                    },
                    "result_status": "skipped_budget",
                }
            )
            continue
        started_at = perf_counter()
        try:
            rows[index_id] = dependencies.get_market_index_contributions(
                index_id=index_id,
                limit=limit,
                db=db,
                expected_trade_date=expected_trade_date,
            )
            result = (
                rows[index_id]
                if isinstance(rows[index_id], dict)
                else {}
            )
            selected_provider = str(
                result.get("source") or ""
            ).strip() or None
            fallback_used = bool(
                result.get("fallback_used")
            )
            tool_runs.append(
                {
                    "tool": "tw.read_market_index_contributions",
                    "provider": selected_provider,
                    "status": (
                        "success_with_fallback"
                        if fallback_used
                        else "success"
                    ),
                    "external_fetch": True,
                    "duration_ms": max(
                        0,
                        int((perf_counter() - started_at) * 1000),
                    ),
                    "writes_cache": False,
                    "requested_capabilities": requested_capabilities,
                    "arguments": {
                        "index_id": index_id,
                        "limit": limit,
                        "requested_capabilities": requested_capabilities,
                    },
                    "result_status": result.get("status") or "completed",
                    "fallback_used": fallback_used,
                }
            )
        except Exception as exc:
            warnings.append(f"{index_id} contributions unavailable: {exc}")
            tool_runs.append(
                {
                    "tool": "tw.read_market_index_contributions",
                    "provider": None,
                    "status": "failed",
                    "external_fetch": True,
                    "duration_ms": max(
                        0,
                        int((perf_counter() - started_at) * 1000),
                    ),
                    "writes_cache": False,
                    "requested_capabilities": requested_capabilities,
                    "arguments": {
                        "index_id": index_id,
                        "limit": limit,
                        "requested_capabilities": requested_capabilities,
                    },
                    "result_status": "failed",
                    "error": str(exc),
                }
            )
    trade_dates = [
        str(item.get("trade_date"))
        for item in rows.values()
        if isinstance(item, dict) and item.get("trade_date")
    ]
    reconciliation_statuses = {
        str(item.get("reconciliation_status") or "unavailable")
        for item in rows.values()
        if isinstance(item, dict)
    }
    quality_ready = bool(
        len(rows) == len(index_ids)
        and all(
            isinstance(item, dict)
            and item.get("decision_usable") is True
            for item in rows.values()
        )
    )
    quality_reason_codes = list(
        dict.fromkeys(
            str(reason)
            for item in rows.values()
            if isinstance(item, dict)
            for reason in item.get("reason_codes") or []
            if reason
        )
    )
    if rows and not quality_ready:
        warnings.append(
            "Index contribution estimates are present but one or more "
            "market-owned quality gates are not satisfied."
        )
    return {
        "kind": "tw_market_index_contributions",
        "status": (
            "ready"
            if quality_ready
            else "partial"
            if rows
            else "unavailable"
        ),
        "applicability_status": "applicable",
        "availability_status": "available" if rows else "missing",
        "policy_satisfied": quality_ready,
        "execution_status": (
            "completed"
            if len(rows) == len(index_ids)
            else "partial"
            if rows
            else "failed"
        ),
        "decision_usable": quality_ready,
        "current_for_requested_session": quality_ready,
        "is_complete": quality_ready,
        "market_session": calendar_phase,
        "expected_trade_date": _date_iso(expected_trade_date),
        "reason_codes": quality_reason_codes,
        "as_of": max(trade_dates) if trade_dates else None,
        "index_ids": index_ids,
        "indices": rows,
        "method": "estimated_market_cap_weight",
        "method_version": "v1",
        "is_official": False,
        "currency": "TWD",
        "price_unit": "TWD",
        "market_value_unit": "TWD",
        "trade_value_unit": "TWD",
        "contribution_unit": "index_points",
        "reconciliation_status": (
            "within_tolerance"
            if reconciliation_statuses
            and reconciliation_statuses <= {"within_tolerance"}
            else "outside_tolerance"
            if "outside_tolerance" in reconciliation_statuses
            else "unavailable"
        ),
        "cache_policy": "bounded_external_fetch",
        "external_fetch": True,
        "writes_cache": False,
        "tool_runs": tool_runs,
        "provider_attempts": [
            {
                "index_id": (
                    run.get("arguments") or {}
                ).get("index_id"),
                "provider": run.get("provider"),
                "status": run.get("status"),
                "duration_ms": run.get("duration_ms"),
            }
            for run in tool_runs
        ],
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
    requested_markets = ["TWSE", "TPEX"]
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
    available_markets = list(
        dict.fromkeys(
            "TWSE"
            if str(row.get("market") or row.get("index_id") or "").upper()
            in {"TWSE", "TAIEX"}
            else "TPEX"
            if str(row.get("market") or row.get("index_id") or "").upper()
            == "TPEX"
            else str(row.get("market") or row.get("index_id") or "").upper()
            for row in rows
            if str(row.get("market") or row.get("index_id") or "").strip()
        )
    )
    missing_markets = [
        market
        for market in requested_markets
        if market not in available_markets
    ]
    coverage_status = (
        "complete"
        if not missing_markets and len(available_markets) == len(requested_markets)
        else "partial"
        if available_markets
        else "unknown"
    )
    status = (
        "ready"
        if rows and same_trade_date and coverage_status == "complete"
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
        "markets": available_markets,
        "coverage": {
            "requested_markets": requested_markets,
            "available_markets": available_markets,
            "missing_markets": missing_markets,
            "coverage_ratio": round(
                len(available_markets) / len(requested_markets),
                6,
            ),
            "coverage_status": coverage_status,
            "aggregate_scope": (
                "TWSE_TPEX"
                if coverage_status == "complete"
                else "_".join(available_markets) + "_only"
                if available_markets
                else "unavailable"
            ),
        },
        "coverage_status": coverage_status,
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
        "coverage_gaps": (
            [
                {
                    "dataset": "market_chip_daily",
                    "requested_markets": requested_markets,
                    "available_markets": available_markets,
                    "missing_markets": missing_markets,
                }
            ]
            if missing_markets
            else []
        ),
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
        "currency": "TWD",
        "value_unit": "TWD",
        "aggregate_scope": common["coverage"]["aggregate_scope"],
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
    margin_aggregate = {
        "margin_balance_change_value": sum_field(
            "margin_balance_change_value"
        ),
        "margin_balance_change_shares": sum_field(
            "margin_balance_change_shares"
        ),
        "short_balance_change_shares": sum_field(
            "short_balance_change_shares"
        ),
    }
    field_status = {
        field: "available" if value is not None else "missing"
        for field, value in margin_aggregate.items()
    }
    available_margin_fields = sum(
        value == "available" for value in field_status.values()
    )
    margin_status = (
        "missing"
        if available_margin_fields == 0
        else "partial"
        if available_margin_fields < len(field_status)
        or coverage_status != "complete"
        or not same_trade_date
        else "ready"
    )
    margin_short = {
        "kind": "tw_market_margin_short",
        **common,
        "status": margin_status,
        "availability_status": (
            "missing" if available_margin_fields == 0 else "available"
        ),
        "coverage_status": coverage_status,
        "aggregate_scope": common["coverage"]["aggregate_scope"],
        "freshness": {
            **common["freshness"],
            "status": margin_status,
            "is_current": margin_status in {"ready", "partial"},
        },
        "unit_semantics": {
            "margin_balance_change_value": "TWD",
            "margin_balance_change_shares": "shares",
            "short_balance_change_shares": "shares",
        },
        "aggregate": margin_aggregate,
        "field_status": field_status,
        "missing": list(
            dict.fromkeys(
                [
                    *common["missing"],
                    *(
                        [
                            f"market_chip_daily.{field}"
                            for field, field_state in field_status.items()
                            if field_state == "missing"
                        ]
                    ),
                ]
            )
        ),
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
    db: Session | None = None,
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
    instrument_types = {
        str(value).strip().lower()
        for value in parameters.get("instrument_types") or []
        if str(value).strip()
    }
    exclude_instrument_types = {
        str(value).strip().lower()
        for value in parameters.get("exclude_instrument_types") or []
        if str(value).strip()
    }
    industries = {
        normalize_tw_industry_label(str(value))
        for value in parameters.get("industries") or []
        if str(value).strip()
    }
    financial_report_related = parameters.get(
        "financial_report_related"
    )
    event_statuses = {
        str(value).strip().lower()
        for value in parameters.get("status") or []
        if str(value).strip()
    }
    timing_statuses = {
        str(value).strip().lower()
        for value in parameters.get("timing_status") or []
        if str(value).strip()
    }
    instrument_metadata: dict[str, dict[str, Any]] = {}
    if instrument_types or exclude_instrument_types or industries:
        if db is None:
            return {
                "kind": "tw_market_event_calendar",
                "status": "unavailable",
                "as_of": generated_at.isoformat(),
                "events": [],
                "cache_policy": "cache_only",
                "missing": ["stock_master"],
                "warnings": [
                    "Instrument filters require the local stock_master reader."
                ],
            }
        stock_rows = (
            db.query(StockMaster)
            .filter(StockMaster.is_active.is_(True))
            .all()
        )
        eligible_stock_ids: set[str] = set()
        for stock in stock_rows:
            instrument_type = str(
                getattr(stock, "instrument_type", "") or ""
            ).strip().lower()
            industry = normalize_tw_industry_label(
                str(getattr(stock, "industry", "") or "")
            )
            if instrument_types and instrument_type not in instrument_types:
                continue
            if (
                exclude_instrument_types
                and instrument_type in exclude_instrument_types
            ):
                continue
            if industries and industry not in industries:
                continue
            stock_id = str(getattr(stock, "stock_id", "") or "").strip()
            if not stock_id:
                continue
            eligible_stock_ids.add(stock_id)
            instrument_metadata[stock_id] = {
                "instrument_type": getattr(stock, "instrument_type", None),
                "industry": getattr(stock, "industry", None),
            }
        stock_ids = (
            stock_ids & eligible_stock_ids
            if stock_ids
            else eligible_stock_ids
        )
        if not stock_ids:
            stock_ids = {"__NO_MATCH__"}
    limit = max(1, min(int(parameters.get("limit") or 300), 500))
    offset = max(0, min(int(parameters.get("offset") or 0), 5000))
    listing_filters: dict[str, Any] = {}
    if isinstance(financial_report_related, bool):
        listing_filters[
            "financial_report_related"
        ] = financial_report_related
    if event_statuses:
        listing_filters["event_statuses"] = event_statuses
    if timing_statuses:
        listing_filters["timing_statuses"] = timing_statuses
    listing = dependencies.list_taiwan_corporate_events(
        event_types=event_types or None,
        markets=markets or None,
        stock_ids=stock_ids or None,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
        now=generated_at,
        **listing_filters,
    )
    rows = [
        _json_event_value(row)
        for row in listing.get("results") or []
        if isinstance(row, dict)
    ]
    for row in rows:
        stock_id = str(row.get("stock_id") or "")
        metadata = instrument_metadata.get(stock_id)
        if metadata:
            row.update(metadata)
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
    source_refs = [
        {
            "type": "provider_cache",
            "provider": str(provider),
            "dataset": "taiwan_corporate_events",
            "name": f"{provider}.taiwan_corporate_events",
            "source_grade": "official",
        }
        for provider in sorted(sources)
    ] or [
        {
            "type": "table",
            "provider": "taiwan_corporate_event_cache",
            "dataset": "taiwan_corporate_events",
            "name": "taiwan_corporate_events",
            "source_grade": "official_cache",
        }
    ]
    return {
        "kind": "tw_market_event_calendar",
        "status": status,
        "as_of": _json_scalar(listing.get("as_of")),
        "date_from": _json_scalar(listing.get("date_from")),
        "date_to": _json_scalar(listing.get("date_to")),
        "event_types": sorted(event_types),
        "markets": sorted(markets),
        "stock_ids": sorted(stock_ids),
        "instrument_types": sorted(instrument_types),
        "exclude_instrument_types": sorted(exclude_instrument_types),
        "industries": sorted(industries),
        "financial_report_related": (
            financial_report_related
            if isinstance(financial_report_related, bool)
            else None
        ),
        "event_statuses": sorted(event_statuses),
        "timing_statuses": sorted(timing_statuses),
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
        "source_refs": source_refs,
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
    computed_at: str | None = None,
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
            "currency": "TWD",
            "trade_value_unit": "TWD",
            "change_pct_method": "equal_weighted_mean_stock_return_pct",
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
        "observed_trade_date": as_of,
        "computed_at": computed_at,
        "data_mode": "previous_completed_session",
        "is_intraday": False,
        "ranking_basis": "omi_local_daily_sample_stock_aggregation",
        "aggregation_method": "equal_weighted_mean_stock_return_pct",
        "currency": "TWD",
        "trade_value_unit": "TWD",
        "is_full_market": False,
        "coverage": {
            **sample_coverage,
            "scope": sample_coverage.get("scope")
            or "canonical_active_stock_universe",
            "full_market_universe_count": sample_coverage.get(
                "universe_count"
            ),
            "covered_stock_count": sample_coverage.get(
                "covered_universe_count"
            ),
            "coverage_status": "sample_only",
            "is_full_market": False,
        },
        "count": len(rows),
        "items": rows,
        "missing": [] if rows else ["market_daily_price.sector_sample"],
        "coverage_gaps": (
            ["market_daily_price.full_market_sector_index"]
            if rows
            else []
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
    requires_explicit_session_currentness = capability_id in {
        "market.indices",
        "market.index_contributions",
    }
    current_for_requested_session = (
        bool(payload.get("current_for_requested_session"))
        if "current_for_requested_session" in payload
        else False
        if requires_explicit_session_currentness
        else status == "ready"
    )
    is_complete = (
        bool(payload.get("is_complete"))
        if "is_complete" in payload
        else status == "ready"
    )
    latest = (
        payload.get("newest_as_of")
        or payload.get("as_of")
        or payload.get("trade_date")
    )
    return {
        "capability": capability_id,
        "dataset": dataset,
        "status": status,
        "is_current": current_for_requested_session,
        "current_for_requested_session": current_for_requested_session,
        "is_complete": is_complete,
        "latest": latest,
        "oldest_as_of": payload.get("oldest_as_of"),
        "newest_as_of": payload.get("newest_as_of") or latest,
        "mixed_as_of": bool(payload.get("mixed_as_of")),
        "mixed_trade_dates": bool(payload.get("mixed_trade_dates")),
        "requested_session": payload.get("market_session"),
        "as_of_semantics": (
            "current_requested_session"
            if current_for_requested_session
            else "latest_completed_session_reference"
        ),
        "event_time_basis": (
            "index_quote_or_completed_trade_date"
            if capability_id == "market.indices"
            else "taiwan_completed_trade_date"
        ),
        "refresh_recommended": (
            status in {"missing", "stale", "unavailable"}
            or not current_for_requested_session
            and payload.get("market_session") in {"regular", "closing_auction"}
        ),
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
    source_refs: list[dict[str, Any]] = []
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
    if (
        not requested_capabilities
        or requested_capabilities
        & {
            "market.indices",
            "market.sectors",
            "market.breadth",
            "market.volume_state",
            "market.index_contributions",
        }
    ):
        _append_source_ref_once(
            source_refs,
            {"type": "resolved_market_data", "name": "tw.daily.ohlcv"},
        )
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
                db=db,
                dependencies=dependencies,
                data_params=data_params,
                generated_at=generated_at,
            )
        )
        calendar_payload = market_aggregates["events_calendar"]
        for source_ref in calendar_payload.get("source_refs") or []:
            if isinstance(source_ref, dict):
                _append_source_ref_once(source_refs, source_ref)
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
        _append_source_ref_once(
            source_refs,
            {"type": "resolved_market_data", "name": "tw.market_index.current"},
        )
        market_aggregates["indices"] = _market_indices_capability(
            db=db,
            dependencies=dependencies,
            generated_at=generated_at,
        )
        if any(
            isinstance(item, dict) and item.get("live_snapshot")
            for item in market_aggregates["indices"].get("items") or []
        ):
            _append_source_ref_once(
                source_refs,
                {"type": "table", "name": "taiwan_index_minute_snapshot"},
            )
        market_aggregates["freshness_by_capability"][
            "market.indices"
        ] = _aggregate_freshness(
            "market.indices",
            market_aggregates["indices"],
            dataset="market_index_summary",
        )
    if "market.index_contributions" in requested_capabilities:
        _append_source_ref_once(
            source_refs,
            {"type": "resolved_market_data", "name": "tw.daily.ohlcv"},
        )
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
        db=db,
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
        elif market_breadth.get("status") == "pending":
            warnings.append(
                "Regular-session Taiwan market breadth is pending; auction "
                "indicative prices are not actual trades."
            )
        else:
            warnings.append(
                "Taiwan market breadth is partial; conclusions must be limited "
                "to the reported scope and coverage."
            )

    if latest_trade_date is None:
        sample_coverage = _daily_sample_coverage(None)
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
                dataset="tw.daily.ohlcv",
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

    daily_snapshot = dependencies.market_service.read_market_daily_snapshot(
        db,
        trade_date=latest_trade_date,
        include_etf=False,
    )
    rows = list(daily_snapshot.rows)
    sample_coverage = _daily_sample_coverage(daily_snapshot)
    stock_ids = sorted({row.stock_id for row in rows if row.stock_id})
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
        "source": "tw.daily.ohlcv",
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
            as_of=latest_trade_date.isoformat(),
            computed_at=_json_scalar(generated_at),
        )
        market_aggregates["freshness_by_capability"][
            "market.sectors"
        ] = _aggregate_freshness(
            "market.sectors",
            market_aggregates["sectors"],
            dataset="tw.daily.ohlcv",
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
        warnings.append(_daily_sample_coverage_warning(sample_coverage))

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
