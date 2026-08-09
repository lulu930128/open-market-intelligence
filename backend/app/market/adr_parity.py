from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
import math
from typing import Any

from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.models import (
    MarketDailyPrice,
    ResourceQuoteSnapshot,
    TaiwanStockQuoteSnapshot,
    USDailyPrice,
)
from app.market.trading_calendar import (
    next_taiwan_trading_day,
    previous_taiwan_trading_day,
)
from app.market.cross_market.relation_store import build_relation_registry_read


FX_STALE_AFTER_SECONDS = 72 * 60 * 60


@dataclass(frozen=True)
class AdrMapping:
    stock_id: str
    stock_name: str
    adr_symbol: str
    adr_name: str
    adr_exchange: str
    local_shares_per_adr: int
    source_label: str
    source_url: str
    verified_on: date


@dataclass(frozen=True)
class AdrMappingResolution:
    mapping: AdrMapping | None
    selected_source: str
    registry_status: str
    shadow_status: str
    shadow_differences: tuple[str, ...] = ()
    relation_id: int | None = None
    relation_version: int | None = None
    relation_valid_from: date | None = None
    relation_valid_to: date | None = None
    relation_verified_at: datetime | None = None
    evidence_ids: tuple[int, ...] = ()
    registry_schema_version: str | None = None
    warnings: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    def as_payload(self) -> dict[str, Any]:
        return {
            "selected_source": self.selected_source,
            "registry_status": self.registry_status,
            "shadow_status": self.shadow_status,
            "shadow_differences": list(self.shadow_differences),
            "relation_id": self.relation_id,
            "relation_version": self.relation_version,
            "relation_valid_from": _iso(self.relation_valid_from),
            "relation_valid_to": _iso(self.relation_valid_to),
            "relation_verified_at": _iso(self.relation_verified_at),
            "evidence_ids": list(self.evidence_ids),
            "registry_schema_version": self.registry_schema_version,
            "warnings": list(self.warnings),
            "limitations": list(self.limitations),
        }


ADR_MAPPINGS: dict[str, AdrMapping] = {
    "2330": AdrMapping(
        stock_id="2330",
        stock_name="台積電",
        adr_symbol="TSM",
        adr_name="TSMC ADR",
        adr_exchange="NYSE",
        local_shares_per_adr=5,
        source_label="TSMC 2025 Form 20-F",
        source_url="https://www.sec.gov/Archives/edgar/data/1046179/000162828026025362/tsm-20251231.htm",
        verified_on=date(2026, 7, 22),
    ),
    "2303": AdrMapping(
        stock_id="2303",
        stock_name="聯電",
        adr_symbol="UMC",
        adr_name="UMC ADR",
        adr_exchange="NYSE",
        local_shares_per_adr=5,
        source_label="UMC 2025 Form 20-F",
        source_url="https://www.sec.gov/Archives/edgar/data/1033767/000119312526193757/d91630d20f.htm",
        verified_on=date(2026, 7, 22),
    ),
    "3711": AdrMapping(
        stock_id="3711",
        stock_name="日月光投控",
        adr_symbol="ASX",
        adr_name="ASE Technology ADR",
        adr_exchange="NYSE",
        local_shares_per_adr=2,
        source_label="ASE Technology 2025 Form 20-F",
        source_url="https://www.sec.gov/Archives/edgar/data/1122411/000119312526135585/d50802d20f.htm",
        verified_on=date(2026, 7, 22),
    ),
    "8150": AdrMapping(
        stock_id="8150",
        stock_name="南茂",
        adr_symbol="IMOS",
        adr_name="ChipMOS ADR",
        adr_exchange="NASDAQ",
        local_shares_per_adr=20,
        source_label="ChipMOS 2025 Form 20-F",
        source_url="https://www.sec.gov/Archives/edgar/data/1123134/000119312526153743/imos-20251231.htm",
        verified_on=date(2026, 7, 22),
    ),
}


def get_adr_mapping(stock_id: str) -> AdrMapping | None:
    return ADR_MAPPINGS.get(stock_id.strip())


def _registry_tables_available(db: Session) -> bool:
    try:
        inspector = inspect(db.connection())
        return inspector.has_table("cross_market_relation") and inspector.has_table(
            "cross_market_relation_evidence"
        )
    except SQLAlchemyError:
        return False


def _mapping_differences(
    legacy: AdrMapping,
    registry: AdrMapping,
) -> tuple[str, ...]:
    fields = (
        "stock_id",
        "adr_symbol",
        "adr_exchange",
        "local_shares_per_adr",
        "source_label",
        "source_url",
        "verified_on",
    )
    return tuple(
        field
        for field in fields
        if getattr(legacy, field) != getattr(registry, field)
    )


def _mapping_from_registry_relation(
    relation: Any,
    *,
    legacy: AdrMapping | None,
) -> AdrMapping:
    numerator = relation.ratio_numerator
    denominator = relation.ratio_denominator
    if numerator is None or denominator is None:
        raise ValueError("registry direct relation ratio is missing")
    local_shares_per_adr = float(denominator) / float(numerator)
    rounded_ratio = round(local_shares_per_adr)
    if not math.isclose(local_shares_per_adr, rounded_ratio, abs_tol=1e-9):
        raise ValueError(
            "legacy ADR parity contract requires an integer local-shares-per-ADR ratio"
        )
    evidence = next((item for item in relation.evidence if item.is_primary), None)
    if evidence is None:
        raise ValueError("registry direct relation requires primary evidence")
    adr_symbol = (
        relation.source.provider_symbol
        or relation.source.canonical_symbol.partition(":")[2]
    )
    stock_id = (
        relation.target.provider_symbol
        or relation.target.canonical_symbol.partition(":")[2]
    )
    use_legacy_names = legacy is not None and legacy.adr_symbol == adr_symbol
    return AdrMapping(
        stock_id=stock_id,
        stock_name=legacy.stock_name if use_legacy_names else stock_id,
        adr_symbol=adr_symbol,
        adr_name=legacy.adr_name if use_legacy_names else f"{adr_symbol} ADR",
        adr_exchange=relation.source.exchange or "UNKNOWN",
        local_shares_per_adr=int(rounded_ratio),
        source_label=evidence.source_label,
        source_url=evidence.source_url,
        verified_on=relation.verified_at.date(),
    )


def resolve_adr_mapping(
    db: Session,
    stock_id: str,
    *,
    as_of: date,
    data_available_at: datetime | None = None,
) -> AdrMappingResolution:
    normalized_stock_id = stock_id.strip()
    legacy = get_adr_mapping(normalized_stock_id)
    if not _registry_tables_available(db):
        return AdrMappingResolution(
            mapping=legacy,
            selected_source="legacy" if legacy is not None else "none",
            registry_status="unavailable",
            shadow_status=("registry_unavailable" if legacy is not None else "not_applicable"),
            warnings=("cross_market_relation_registry_unavailable",),
            limitations=("legacy_mapping_fallback",) if legacy is not None else (),
        )

    try:
        registry = build_relation_registry_read(
            db,
            normalized_stock_id,
            as_of=as_of,
            generated_at=data_available_at,
            data_available_at=data_available_at,
        )
    except SQLAlchemyError:
        return AdrMappingResolution(
            mapping=legacy,
            selected_source="legacy" if legacy is not None else "none",
            registry_status="failed",
            shadow_status=("registry_failed" if legacy is not None else "not_applicable"),
            warnings=("cross_market_relation_registry_read_failed",),
            limitations=("legacy_mapping_fallback",) if legacy is not None else (),
        )

    direct_relations = [
        relation
        for relation in registry.relations
        if relation.relation_type in {"same_equity_dr", "secondary_listing"}
        and relation.decision_usable
    ]
    if len(direct_relations) > 1:
        return AdrMappingResolution(
            mapping=legacy,
            selected_source="legacy" if legacy is not None else "none",
            registry_status="blocked",
            shadow_status="multiple_registry_direct_relations",
            registry_schema_version=registry.schema_version,
            warnings=("multiple_effective_direct_relations",),
            limitations=("legacy_mapping_fallback",) if legacy is not None else (),
        )
    if not direct_relations:
        return AdrMappingResolution(
            mapping=legacy,
            selected_source="legacy" if legacy is not None else "none",
            registry_status=registry.status,
            shadow_status=("legacy_only" if legacy is not None else "not_applicable"),
            registry_schema_version=registry.schema_version,
            warnings=("cross_market_relation_registry_missing",) if legacy is not None else (),
            limitations=("legacy_mapping_fallback",) if legacy is not None else (),
        )

    relation = direct_relations[0]
    common = {
        "relation_id": relation.relation_id,
        "relation_version": relation.relation_version,
        "relation_valid_from": relation.valid_from,
        "relation_valid_to": relation.valid_to,
        "relation_verified_at": relation.verified_at,
        "evidence_ids": tuple(item.evidence_id for item in relation.evidence),
        "registry_schema_version": registry.schema_version,
    }
    try:
        registry_mapping = _mapping_from_registry_relation(
            relation,
            legacy=legacy,
        )
    except ValueError as exc:
        return AdrMappingResolution(
            mapping=legacy,
            selected_source="legacy" if legacy is not None else "none",
            registry_status="blocked",
            shadow_status="registry_contract_incompatible",
            warnings=(str(exc),),
            limitations=("legacy_mapping_fallback",) if legacy is not None else (),
            **common,
        )

    if legacy is None:
        return AdrMappingResolution(
            mapping=registry_mapping,
            selected_source="registry",
            registry_status=registry.status,
            shadow_status="registry_only",
            **common,
        )
    differences = _mapping_differences(legacy, registry_mapping)
    if differences:
        return AdrMappingResolution(
            mapping=legacy,
            selected_source="legacy",
            registry_status="limited",
            shadow_status="mismatch",
            shadow_differences=differences,
            warnings=("adr_mapping_registry_shadow_mismatch",),
            limitations=("legacy_mapping_fallback",),
            **common,
        )
    return AdrMappingResolution(
        mapping=registry_mapping,
        selected_source="registry",
        registry_status=registry.status,
        shadow_status="match",
        **common,
    )


def calculate_implied_tw_price(
    *,
    adr_close_usd: float,
    usd_twd: float,
    local_shares_per_adr: int,
) -> float:
    if not _positive(adr_close_usd):
        raise ValueError("adr_close_usd must be a finite positive number")
    if not _positive(usd_twd):
        raise ValueError("usd_twd must be a finite positive number")
    if local_shares_per_adr <= 0:
        raise ValueError("local_shares_per_adr must be positive")
    return adr_close_usd * usd_twd / local_shares_per_adr


def build_adr_parity_report(
    db: Session,
    stock_id: str,
    *,
    stock_name: str | None = None,
    expected_adr_trade_date: date | None = None,
    generated_at: datetime | None = None,
    mapping_as_of: date | None = None,
    data_available_at: datetime | None = None,
) -> dict[str, Any] | None:
    now = generated_at or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    mapping_resolution = resolve_adr_mapping(
        db,
        stock_id,
        as_of=mapping_as_of or now.date(),
        data_available_at=data_available_at or now,
    )
    mapping = mapping_resolution.mapping
    if mapping is None:
        return None

    missing: list[str] = []
    warnings: list[str] = list(mapping_resolution.warnings)
    stale_reasons: list[str] = []

    adr_row = _latest_adr_row(
        db,
        mapping.adr_symbol,
        available_at=data_available_at,
    )
    if adr_row is None:
        missing.append(f"us_daily_price.{mapping.adr_symbol}")

    fx = _latest_usd_twd(db, available_at=data_available_at)
    if fx is None:
        missing.append("resource_quote_snapshot.USD-TWD")

    adr_trade_date = adr_row.trade_date if adr_row is not None else None
    tw_reference = (
        _latest_tw_daily_at_or_before(
            db,
            mapping.stock_id,
            adr_trade_date,
            available_at=data_available_at,
        )
        if adr_trade_date is not None
        else None
    )
    if adr_trade_date is not None and tw_reference is None:
        missing.append(f"market_daily_price.{mapping.stock_id}.reference")

    target_tw_trade_date = (
        next_taiwan_trading_day(adr_trade_date, include_value=False)
        if adr_trade_date is not None
        else None
    )
    comparison = _latest_tw_comparison(
        db,
        mapping.stock_id,
        available_at=data_available_at,
    )

    adr_close_usd = _number(adr_row.close_price) if adr_row is not None else None
    usd_twd = fx["usd_twd"] if fx is not None else None
    tw_reference_price_twd = (
        _number(tw_reference.close_price) if tw_reference is not None else None
    )

    implied_tw_price_twd: float | None = None
    implied_gap_pct: float | None = None
    parity_adr_price_usd: float | None = None
    remaining_gap_pct: float | None = None
    if (
        adr_close_usd is not None
        and usd_twd is not None
        and tw_reference_price_twd is not None
    ):
        implied_tw_price_twd = calculate_implied_tw_price(
            adr_close_usd=adr_close_usd,
            usd_twd=usd_twd,
            local_shares_per_adr=mapping.local_shares_per_adr,
        )
        implied_gap_pct = _pct_gap(implied_tw_price_twd, tw_reference_price_twd)
        parity_adr_price_usd = (
            tw_reference_price_twd * mapping.local_shares_per_adr / usd_twd
        )

    comparison_price = comparison["price"] if comparison is not None else None
    if implied_tw_price_twd is not None and comparison_price is not None:
        remaining_gap_pct = _pct_gap(implied_tw_price_twd, comparison_price)

    if (
        adr_trade_date is not None
        and expected_adr_trade_date is not None
        and adr_trade_date < expected_adr_trade_date
    ):
        stale_reasons.append("adr_close")
        warnings.append(
            f"ADR 收盤日 {adr_trade_date.isoformat()} 落後預期 {expected_adr_trade_date.isoformat()}。"
        )

    if fx is not None:
        fx_age_seconds = _age_seconds(now, fx["as_of"])
        fx["age_seconds"] = fx_age_seconds
        if fx["source_symbol"] == "TWD-USD":
            warnings.append("USD/TWD 由 TWD-USD 反向換算。")
        if fx_age_seconds is not None and fx_age_seconds > FX_STALE_AFTER_SECONDS:
            stale_reasons.append("fx")
            warnings.append("USD/TWD 匯率快取已超過 72 小時。")

    if adr_trade_date is not None and tw_reference is not None:
        expected_tw_reference_date = previous_taiwan_trading_day(
            adr_trade_date,
            include_value=True,
        )
        if tw_reference.trade_date < expected_tw_reference_date:
            stale_reasons.append("tw_reference")
            warnings.append(
                "台股參考收盤日 "
                f"{tw_reference.trade_date.isoformat()} 落後預期 {expected_tw_reference_date.isoformat()}。"
            )

    status = "partial" if missing else "stale" if stale_reasons else "ready"
    comparison_mode = _comparison_mode(
        comparison_trade_date=(comparison or {}).get("trade_date"),
        comparison_source=(comparison or {}).get("source"),
        target_tw_trade_date=target_tw_trade_date,
    )

    mapping_payload = asdict(mapping)
    mapping_payload["verified_on"] = mapping.verified_on.isoformat()
    source_refs = [
        {
            "type": "filing",
            "name": mapping.source_label,
            "url": mapping.source_url,
        },
        {"type": "table", "name": "us_daily_price"},
        {"type": "table", "name": "market_daily_price"},
        {"type": "table", "name": "resource_quote_snapshot"},
        {"type": "derived", "name": "app.market.adr_parity"},
    ]
    if mapping_resolution.relation_id is not None:
        source_refs.extend(
            [
                {
                    "type": "table",
                    "name": "cross_market_relation",
                    "id": str(mapping_resolution.relation_id),
                },
                *(
                    {
                        "type": "table",
                        "name": "cross_market_relation_evidence",
                        "id": str(evidence_id),
                    }
                    for evidence_id in mapping_resolution.evidence_ids
                ),
            ]
        )

    return {
        "kind": "tw_adr_parity",
        "status": status,
        "is_current": status == "ready",
        "stock_id": mapping.stock_id,
        "stock_name": stock_name or mapping.stock_name,
        "mapping": mapping_payload,
        "mapping_resolution": mapping_resolution.as_payload(),
        "formula": "adr_close_usd * usd_twd / local_shares_per_adr",
        "adr_close_usd": _round(adr_close_usd),
        "adr_trade_date": _iso(adr_trade_date),
        "adr_provider": adr_row.provider if adr_row is not None else None,
        "expected_adr_trade_date": _iso(expected_adr_trade_date),
        "usd_twd": _round(usd_twd, 6),
        "fx_source_symbol": fx["source_symbol"] if fx is not None else None,
        "fx_provider": fx["provider"] if fx is not None else None,
        "fx_as_of": _iso(fx["as_of"] if fx is not None else None),
        "fx_age_seconds": fx.get("age_seconds") if fx is not None else None,
        "tw_reference_price_twd": _round(tw_reference_price_twd),
        "tw_reference_trade_date": _iso(
            tw_reference.trade_date if tw_reference is not None else None
        ),
        "tw_reference_semantics": (
            "taiwan_close_at_or_before_adr_trade_date_used_as_the_aligned_gap_baseline"
        ),
        "target_tw_trade_date": _iso(target_tw_trade_date),
        "implied_tw_price_twd": _round(implied_tw_price_twd),
        "implied_gap_pct": _round(implied_gap_pct),
        "parity_adr_price_usd": _round(parity_adr_price_usd),
        "tw_comparison_price_twd": _round(comparison_price),
        "tw_comparison_trade_date": _iso(
            comparison["trade_date"] if comparison is not None else None
        ),
        "tw_comparison_as_of": _iso(
            comparison["as_of"] if comparison is not None else None
        ),
        "tw_comparison_source": comparison["source"] if comparison is not None else None,
        "tw_comparison_semantics": (
            "latest_available_taiwan_price_used_only_for_remaining_gap"
        ),
        "tw_session_phase": comparison.get("session_phase") if comparison is not None else None,
        "comparison_mode": comparison_mode,
        "remaining_gap_pct": _round(remaining_gap_pct),
        "missing": list(dict.fromkeys(missing)),
        "warnings": list(dict.fromkeys(warnings)),
        "source_refs": source_refs,
        "freshness": {
            "adr_is_current": bool(
                adr_trade_date is not None
                and (
                    expected_adr_trade_date is None
                    or adr_trade_date >= expected_adr_trade_date
                )
            ),
            "fx_is_current": bool(fx is not None and "fx" not in stale_reasons),
            "tw_reference_is_current": bool(
                tw_reference is not None and "tw_reference" not in stale_reasons
            ),
            "stale_reasons": list(dict.fromkeys(stale_reasons)),
            "data_available_at": _iso(data_available_at),
        },
    }


def _latest_adr_row(
    db: Session,
    symbol: str,
    *,
    available_at: datetime | None = None,
) -> USDailyPrice | None:
    query = db.query(USDailyPrice).filter(USDailyPrice.symbol == symbol)
    if available_at is not None:
        query = query.filter(USDailyPrice.fetched_at <= available_at)
    rows = (
        query
        .order_by(
            USDailyPrice.trade_date.desc(),
            USDailyPrice.updated_at.desc(),
            USDailyPrice.id.desc(),
        )
        .limit(8)
        .all()
    )
    return next((row for row in rows if _positive(row.close_price)), None)


def _latest_tw_daily_at_or_before(
    db: Session,
    stock_id: str,
    reference_date: date,
    *,
    available_at: datetime | None = None,
) -> MarketDailyPrice | None:
    query = (
        db.query(MarketDailyPrice)
        .filter(
            MarketDailyPrice.stock_id == stock_id,
            MarketDailyPrice.trade_date <= reference_date,
        )
    )
    if available_at is not None:
        query = query.filter(MarketDailyPrice.created_at <= available_at)
    rows = (
        query
        .order_by(
            MarketDailyPrice.trade_date.desc(),
            MarketDailyPrice.updated_at.desc(),
            MarketDailyPrice.id.desc(),
        )
        .limit(12)
        .all()
    )
    return next((row for row in rows if _positive(row.close_price)), None)


def _latest_tw_comparison(
    db: Session,
    stock_id: str,
    *,
    available_at: datetime | None = None,
) -> dict[str, Any] | None:
    daily_query = db.query(MarketDailyPrice).filter(
        MarketDailyPrice.stock_id == stock_id
    )
    if available_at is not None:
        daily_query = daily_query.filter(MarketDailyPrice.created_at <= available_at)
    daily_rows = (
        daily_query
        .order_by(
            MarketDailyPrice.trade_date.desc(),
            MarketDailyPrice.updated_at.desc(),
            MarketDailyPrice.id.desc(),
        )
        .limit(12)
        .all()
    )
    daily = next((row for row in daily_rows if _positive(row.close_price)), None)

    quote_query = db.query(TaiwanStockQuoteSnapshot).filter(
        TaiwanStockQuoteSnapshot.stock_id == stock_id
    )
    if available_at is not None:
        quote_query = quote_query.filter(
            TaiwanStockQuoteSnapshot.fetched_at <= available_at,
            TaiwanStockQuoteSnapshot.quote_time <= available_at,
        )
    quote_rows = (
        quote_query
        .order_by(
            TaiwanStockQuoteSnapshot.quote_time.desc(),
            TaiwanStockQuoteSnapshot.id.desc(),
        )
        .limit(12)
        .all()
    )
    quote = next(
        (
            row
            for row in quote_rows
            if row.trade_date is not None and _positive(row.last_price)
        ),
        None,
    )

    if quote is not None and (daily is None or quote.trade_date >= daily.trade_date):
        return {
            "price": float(quote.last_price),
            "trade_date": quote.trade_date,
            "as_of": quote.quote_time,
            "source": "taiwan_stock_quote_snapshot",
            "session_phase": quote.session_phase,
        }
    if daily is None:
        return None
    return {
        "price": float(daily.close_price),
        "trade_date": daily.trade_date,
        "as_of": None,
        "source": "market_daily_price",
        "session_phase": "daily_close",
    }


def _latest_usd_twd(
    db: Session,
    *,
    available_at: datetime | None = None,
) -> dict[str, Any] | None:
    for symbol in ("USD-TWD", "TWD-USD"):
        query = db.query(ResourceQuoteSnapshot).filter(
            ResourceQuoteSnapshot.symbol == symbol
        )
        if available_at is not None:
            query = query.filter(ResourceQuoteSnapshot.fetched_at <= available_at)
        rows = (
            query
            .order_by(
                ResourceQuoteSnapshot.fetched_at.desc(),
                ResourceQuoteSnapshot.id.desc(),
            )
            .all()
        )
        for row in rows:
            if not _positive(row.last_price):
                continue
            usd_twd = (
                float(row.last_price)
                if symbol == "USD-TWD"
                else 1 / float(row.last_price)
            )
            return {
                "usd_twd": usd_twd,
                "source_symbol": row.symbol,
                "provider": row.provider,
                "as_of": row.event_time or row.fetched_at,
            }
    return None


def _comparison_mode(
    *,
    comparison_trade_date: date | None,
    comparison_source: str | None,
    target_tw_trade_date: date | None,
) -> str:
    if target_tw_trade_date is None or comparison_trade_date is None:
        return "reference_only"
    if comparison_trade_date < target_tw_trade_date:
        return "next_tw_session"
    if comparison_trade_date == target_tw_trade_date:
        return (
            "target_session_tracking"
            if comparison_source == "taiwan_stock_quote_snapshot"
            else "target_session_review"
        )
    return "historical_review"


def _age_seconds(now: datetime, value: datetime | None) -> int | None:
    if value is None:
        return None
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return max(0, int((now.astimezone(timezone.utc) - normalized.astimezone(timezone.utc)).total_seconds()))


def _pct_gap(value: float, reference: float) -> float | None:
    if not _positive(value) or not _positive(reference):
        return None
    return ((value / reference) - 1) * 100


def _number(value: Any) -> float | None:
    return float(value) if _positive(value) else None


def _positive(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    )


def _round(value: Any, digits: int = 4) -> float | None:
    return (
        round(float(value), digits)
        if isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        else None
    )


def _iso(value: date | datetime | None) -> str | None:
    return value.isoformat() if value is not None else None
