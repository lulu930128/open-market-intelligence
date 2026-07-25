from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
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
    now: Callable[[], datetime]


def _compact_auxiliary_context(value: dict[str, Any]) -> dict[str, Any]:
    compact = ((value.get("data") or {}).get("compact")) if isinstance(value.get("data"), dict) else None
    if isinstance(compact, dict):
        return compact
    return {
        key: value.get(key)
        for key in ("kind", "status", "as_of", "scope", "summary", "missing", "warnings", "slots")
        if key in value
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
        "freshness_by_domain": {
            "breadth": (slots.get("market_breadth") or {}).get("status"),
            "sample_ranking": (slots.get("sample_distribution") or {}).get("status"),
            "index_intraday": (slots.get("index_intraday") or {}).get("status"),
            "cross_market": (slots.get("cross_market") or {}).get("status"),
            "market_chips": (slots.get("market_chips") or {}).get("status"),
            "volume": (slots.get("market_volume") or {}).get("status"),
        },
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
        "unchanged_count": _sum_count("unchanged_count"),
        "total_count": _sum_count("total_count"),
        "limit_up_count": _sum_optional("limit_up_count"),
        "limit_down_count": _sum_optional("limit_down_count"),
        "trade_value": _sum_optional("trade_value"),
        "currency": "TWD",
        "trade_value_unit": "TWD",
        "positive_ratio": advance_count / comparison_count if comparison_count else None,
        "advance_decline_ratio": advance_count / decline_count if decline_count else None,
        "included_markets": list(breadth_by_market),
        "missing_markets": missing_markets,
        "markets": breadth_by_market,
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
