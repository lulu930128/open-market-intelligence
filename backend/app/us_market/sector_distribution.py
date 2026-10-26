"""Completed-session US universe projection; GET reads only the owned EOD checkpoint."""

from __future__ import annotations

from collections import defaultdict
import json
from datetime import datetime, timezone
from decimal import Decimal
from statistics import median
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.market_data.contracts import BarFinalization
from app.market_data.candidate_repository import CandidateReadLimitExceeded
from app.us_market.classification import read_us_classification
from app.us_market.daily_ohlcv_platform import USDailyOhlcvPlatform
from app.us_market.daily_market_state import USInstrumentIdentityUnavailableError
from app.us_market.full_market_eod import US_FULL_MARKET_EOD_LIFECYCLE
from app.us_market.trading_calendar import US_MARKET_TIMEZONE, previous_us_trading_day, is_us_daily_price_finalized


US_DISTRIBUTION_MEMBER_LIMIT = 5


class USDistributionCounts(BaseModel):
    universe: int = 0
    evaluated: int = 0
    observed_price: int = 0
    comparable: int = 0
    up: int = 0
    down: int = 0
    flat: int = 0
    unknown: int = 0
    no_trade: int = 0
    fresh: int = 0
    stale: int = 0
    missing: int = 0
    partial: int = 0
    not_covered: int = 0


class USDistributionGroup(BaseModel):
    group_id: str
    dimension: Literal["sector", "industry"]
    provider: str | None
    taxonomy: Literal["SIC", "provider_reported"] | None = None
    sector: str | None
    industry: str | None
    classification_status: Literal["known", "unknown"]
    counts: USDistributionCounts
    avg_return_pct: float | None
    median_return_pct: float | None
    price_coverage_ratio: float | None
    comparable_coverage_ratio: float | None
    relative_strength_pct: float | None = None
    turnover_value: float | None = None
    turnover_status: str = "unavailable"
    members: list[dict]
    members_truncated: bool


class USSectorDistributionRead(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["us.market.sector_distribution.v1"] = "us.market.sector_distribution.v1"
    market: Literal["US"] = "US"
    status: Literal["partial", "unavailable"]
    as_of: str | None
    expected_trade_date: str
    reference_trade_date: str
    evaluated_at: str
    data_mode: Literal["eod_market_snapshot"] = "eod_market_snapshot"
    is_intraday: Literal[False] = False
    is_full_market: bool = True
    decision_usable: Literal[False] = False
    execution_grade_usable: Literal[False] = False
    sample_only: bool = False
    freshness_status: Literal["current", "stale", "missing"]
    coverage: dict
    classification_coverage: dict
    counts: USDistributionCounts
    avg_return_pct: float | None = None
    median_return_pct: float | None = None
    sectors: list[USDistributionGroup]
    industries: list[USDistributionGroup]
    hot_groups: list[USDistributionGroup]
    provenance: dict
    limitations: list[str]
    intraday: dict = Field(default_factory=lambda: {
        "status": "pending", "sample_only": True,
        "reason": "US_INTRADAY_UNIVERSE_SNAPSHOT_COVERAGE_NOT_VERIFIED",
    })


def _summarize(rows: list[dict]) -> tuple[USDistributionCounts, list[Decimal]]:
    counts = USDistributionCounts(universe=len(rows))
    returns = []
    for row in rows:
        counts.evaluated += int(row["evaluated"])
        counts.observed_price += int(row["observed_price"])
        counts.fresh += int(row["price_status"] == "fresh")
        counts.stale += int(row["price_status"] == "stale")
        counts.missing += int(row["price_status"] == "missing")
        counts.partial += int(row["price_status"] == "partial")
        counts.not_covered += int(not row["evaluated"])
        direction = row["direction"]
        setattr(counts, direction, getattr(counts, direction) + 1)
        if row["return_pct"] is not None:
            counts.comparable += 1
            returns.append(row["return_pct"])
    assert counts.up + counts.down + counts.flat + counts.unknown + counts.no_trade == counts.universe
    assert counts.fresh + counts.stale + counts.missing + counts.partial == counts.universe
    return counts, returns


def _public_lineage(bar) -> dict:
    return {
        "provider": bar.lineage.provider, "source": bar.lineage.source,
        "event_at": bar.lineage.event_at.isoformat() if bar.lineage.event_at else None,
        "fetched_at": bar.lineage.fetched_at.isoformat() if bar.lineage.fetched_at else None,
        "finalization": bar.finalization.value, "price_basis": bar.price_basis,
    }


def _groups(rows: list[dict], dimension: Literal["sector", "industry"]) -> list[USDistributionGroup]:
    buckets = defaultdict(list)
    for row in rows:
        profile = row["classification"] or {}
        label = profile.get(dimension)
        # Never merge different providers' taxonomies by label alone.
        key = (profile.get("provider"), profile.get("sector"), profile.get("industry") if dimension == "industry" else None) if label else (None, None, None)
        buckets[key].append(row)
    groups = []
    for (provider, sector, industry), members in buckets.items():
        counts, returns = _summarize(members)
        samples = sorted((row for row in members if row["evaluated"]),
                         key=lambda row: (row["return_pct"] is None, -(row["return_pct"] or Decimal(0)), row["symbol"]))
        groups.append(USDistributionGroup(
            group_id=json.dumps([dimension, provider, sector, industry], ensure_ascii=False),
            dimension=dimension, provider=provider, sector=sector, industry=industry,
            taxonomy=("SIC" if provider == "sec_edgar_sic" else "provider_reported") if provider else None,
            classification_status="known" if provider else "unknown", counts=counts,
            avg_return_pct=float(sum(returns) / len(returns)) if returns else None,
            median_return_pct=float(median(returns)) if returns else None,
            price_coverage_ratio=counts.observed_price / counts.universe if counts.universe else None,
            comparable_coverage_ratio=counts.comparable / counts.universe if counts.universe else None,
            members=[{**row, "return_pct": float(row["return_pct"]) if row["return_pct"] is not None else None}
                     for row in samples[:US_DISTRIBUTION_MEMBER_LIMIT]],
            members_truncated=len(samples) > US_DISTRIBUTION_MEMBER_LIMIT,
        ))
    return sorted(groups, key=lambda group: (group.avg_return_pct is None, -(group.avg_return_pct or 0), group.group_id))


def build_us_sector_distribution(db: Session, *, now: datetime | None = None, coverage=None) -> USSectorDistributionRead:
    evaluated_at = now or datetime.now(timezone.utc)
    expected = US_FULL_MARKET_EOD_LIFECYCLE.expected_trade_date(now=evaluated_at)
    reference = previous_us_trading_day(expected, include_value=False)
    # No autoflush, including when called in an existing request transaction.
    with db.no_autoflush:
        classification = read_us_classification(db, now=evaluated_at)
        coverage = coverage or US_FULL_MARKET_EOD_LIFECYCLE.compute_coverage(db, expected_trade_date=expected)
        current = set(coverage.current_symbols)
        stale = set(coverage.stale_symbols)
        partial = set(coverage.partial_symbols)
        profiles = classification["profiles"]
        eligible = sorted(symbol for symbol in current if symbol in profiles
                          and (profiles[symbol]["sector"] or profiles[symbol]["industry"]))
        selected = set(classification["symbols"])
        resolved_pairs = USDailyOhlcvPlatform(db).read_market_pair(expected_date=expected, now=evaluated_at)
        rows = []
        for symbol in classification["symbols"]:
            profile = profiles.get(symbol)
            row = {
                "symbol": symbol, "classification": {key: value for key, value in profile.items()
                                                       if key != "raw_payload_hash"} if profile else None,
                "evaluated": symbol in selected, "observed_price": False,
                "price_status": "partial" if symbol in current or symbol in partial else "stale" if symbol in stale else "missing",
                "direction": "unknown", "return_pct": None,
                "reason": "CURRENT_OR_PREVIOUS_COMPLETED_BAR_MISSING",
                "price_lineage": [], "reference_trade_date": reference.isoformat(),
            }
            if symbol in selected:
                try:
                    result = resolved_pairs.get(symbol)
                    if result is None:
                        raise USInstrumentIdentityUnavailableError(symbol)
                except (USInstrumentIdentityUnavailableError, CandidateReadLimitExceeded) as exc:
                    row["reason"] = type(exc).__name__
                    rows.append(row)
                    continue
                resolved = result.result.resolved
                bars = {bar.end_at.astimezone(US_MARKET_TIMEZONE).date(): bar for bar in resolved.bars}
                latest, previous = bars.get(expected), bars.get(reference)
                row["reason"] = "CURRENT_OR_PREVIOUS_COMPLETED_BAR_MISSING"
                if latest is not None and result.temporal_postcondition_satisfied and is_us_daily_price_finalized(trade_date=expected, fetched_at=latest.lineage.fetched_at):
                    row["observed_price"] = True
                    row["price_status"] = "fresh"
                    row["price_lineage"] = [_public_lineage(latest)]
                    if latest.volume is not None and latest.volume.value == 0:
                        row["direction"] = "no_trade"
                        row["reason"] = "PROVIDER_REPORTED_ZERO_SHARES"
                    elif previous is not None and is_us_daily_price_finalized(trade_date=reference, fetched_at=previous.lineage.fetched_at) and all(
                        bar.finalization in {BarFinalization.FINAL, BarFinalization.CORRECTED}
                        for bar in (latest, previous)
                    ) and latest.price_basis == previous.price_basis and latest.lineage.provider == previous.lineage.provider and latest.lineage.source == previous.lineage.source and previous.close_price > 0:
                        value = (latest.close_price / previous.close_price - 1) * 100
                        row["return_pct"] = value
                        row["direction"] = "up" if value > 0 else "down" if value < 0 else "flat"
                        row["reason"] = "COMPLETED_SAME_SOURCE_PRICE_RETURN_CORPORATE_ACTION_UNVERIFIED"
                        row["price_lineage"].append(_public_lineage(previous))
            rows.append(row)
    counts, returns = _summarize(rows)
    market_mean = float(sum(returns) / len(returns)) if returns else None
    sectors, industries = _groups(rows, "sector"), _groups(rows, "industry")
    for group in [*sectors, *industries]:
        group.relative_strength_pct = group.avg_return_pct - market_mean if group.avg_return_pct is not None and market_mean is not None else None
    limits = ["EOD_NOT_INTRADAY", "RAW_PRICE_RETURN_NOT_TOTAL_RETURN",
              "TURNOVER_NOT_AVAILABLE_NOT_NET_FLOW", "CURRENT_CLASSIFICATION_EFFECTIVE_DATE_UNKNOWN",
              "PROVIDER_TAXONOMIES_NOT_EQUIVALENT_NO_GICS_MAPPING", "CORPORATE_ACTION_INTERVAL_PROOF_MISSING",
              "NO_TRADE_MEANS_PROVIDER_REPORTED_ZERO_SHARES_NOT_SUSPENSION"]
    if not counts.comparable:
        limits.append("NO_CLASSIFIED_COMPARABLE_PRICE_INTERSECTION")
    total = len(rows)
    return USSectorDistributionRead(
        status="partial" if counts.comparable else "unavailable",
        as_of=expected.isoformat() if counts.observed_price else None,
        expected_trade_date=expected.isoformat(), reference_trade_date=reference.isoformat(),
        evaluated_at=evaluated_at.isoformat(),
        freshness_status="current" if counts.fresh else "stale" if stale else "missing",
        coverage={
            "universe_count": total, "universe_source": coverage.universe_source,
            "universe_hash": coverage.universe_hash, "expected_trade_date": expected.isoformat(),
            "inventory_current_count": len(current), "inventory_stale_count": len(stale),
            "inventory_partial_count": len(partial), "inventory_missing_count": len(coverage.missing_symbols),
            "inventory_current_ratio": len(current) / total if total else None,
            "classified_price_eligible_count": len(eligible), "evaluated_count": len(selected),
            "comparable_count": counts.comparable, "observed_price_count": counts.observed_price,
            "price_coverage_ratio": counts.observed_price / total if total else None,
            "not_covered_count": total - counts.observed_price, "over_budget_count": 0,
            "query_symbol_limit": None,
            "selection_rule": "all_eligible_stockmaster_members_canonical_gateway",
            "truncated": False, "universe_complete": counts.observed_price == total and total > 0,
            "comparable_coverage_ratio": counts.comparable / total if total else None,
            "classified_comparable_count": sum(row["return_pct"] is not None and bool(row["classification"] and row["classification"]["sector"] and row["classification"]["industry"]) for row in rows),
            "coverage_basis": "materialized_eod_coverage_checkpoint",
            "snapshot_trade_date": expected.isoformat(),
        },
        classification_coverage=classification["coverage"], counts=counts,
        avg_return_pct=market_mean, median_return_pct=float(median(returns)) if returns else None,
        sectors=sectors, industries=industries,
        hot_groups=[group for group in industries if group.avg_return_pct is not None and group.classification_status == "known"],
        provenance={"price_owner": "USDailyOhlcvPlatform", "read_policy": "cache_only",
                    "comparison": "previous_trading_session_same_source_raw_price_return",
                    "taxonomy": "source_specific", "taxonomies": classification["coverage"]["taxonomies"], "effective_date": None,
                    "corporate_action_coverage": "unknown", "external_calls": 0,
                    "relative_strength_basis": "group_equal_weight_mean_minus_all_comparable_universe_equal_weight_mean",
                    "relative_strength_benchmark_count": counts.comparable, "turnover_status": "unavailable"},
        limitations=limits,
    )


def read_us_sector_distribution(db: Session, *, now: datetime | None = None) -> USSectorDistributionRead:
    """One checkpoint read, no universe scan, IO acquisition or implicit persistence."""
    from app.db.models import MarketDatasetCoverageCheckpoint
    from app.market_data.eod_coverage import US_DATASET_ID, US_SCOPE_KEY

    now = now or datetime.now(timezone.utc)
    expected = US_FULL_MARKET_EOD_LIFECYCLE.expected_trade_date(now=now)
    with db.no_autoflush:
        row = (db.query(MarketDatasetCoverageCheckpoint.detail_json)
               .filter(MarketDatasetCoverageCheckpoint.dataset_id == US_DATASET_ID,
                       MarketDatasetCoverageCheckpoint.scope_key == US_SCOPE_KEY,
                       MarketDatasetCoverageCheckpoint.expected_trade_date <= expected)
               .order_by(MarketDatasetCoverageCheckpoint.expected_trade_date.desc(),
                         MarketDatasetCoverageCheckpoint.checked_at.desc()).first())
    payload = json.loads(row.detail_json).get("us_sector_distribution") if row else None
    if payload is not None:
        snapshot = USSectorDistributionRead.model_validate(payload)
        if datetime.fromisoformat(snapshot.evaluated_at) <= now:
            if snapshot.expected_trade_date != expected.isoformat():
                return snapshot.model_copy(update={"freshness_status": "stale", "status": "partial",
                    "expected_trade_date": expected.isoformat(),
                    "limitations": [*snapshot.limitations, "SNAPSHOT_BEHIND_EXPECTED_SESSION"]})
            return snapshot
    return USSectorDistributionRead(status="unavailable", as_of=None, expected_trade_date=expected.isoformat(),
        reference_trade_date=previous_us_trading_day(expected, include_value=False).isoformat(),
        evaluated_at=now.isoformat(), is_full_market=False, freshness_status="missing",
        coverage={"universe_count": None, "evaluated_count": 0, "not_covered_count": None,
                  "over_budget_count": 0, "query_symbol_limit": None, "truncated": False,
                  "inventory_current_count": None, "inventory_stale_count": None,
                  "inventory_missing_count": None, "price_coverage_ratio": None,
                  "comparable_coverage_ratio": None, "universe_complete": False},
        classification_coverage={"mapped_count": None, "sector_count": None, "industry_count": None,
                  "unknown_count": None, "coverage_ratio": None, "as_of": None,
                  "effective_date_status": "unknown"},
        counts=USDistributionCounts(), sectors=[], industries=[], hot_groups=[],
        provenance={"read_policy": "cache_only", "external_calls": 0},
        limitations=["US_EOD_SNAPSHOT_NOT_MATERIALIZED", "UNIVERSE_COUNTS_UNKNOWN", "EOD_NOT_INTRADAY"])
