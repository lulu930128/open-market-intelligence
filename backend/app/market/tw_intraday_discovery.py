"""Cache-only full-universe discovery over the existing lightweight state owner.

No provider selection, bar materialization, lease admission or alternate
freshness/session policy lives here. Coverage describes usable observations,
not the number of rows returned by a provider.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from hashlib import sha256
import json

from sqlalchemy.orm import Session

from app.db.models import TaiwanIntradayStockState
from app.market.trading_calendar import TAIWAN_TZ, taiwan_market_session_phase
from app.market.tw_intraday_radar_contracts import (
    DiscoveryCoverage, DiscoveryObservation, IntradayDiscovery, IntradayFeature,
    IntradayFeatures, IntradayLineage, IntradayCandidateConfig, IntradayRadarResult,
)
from app.market.tw_intraday_radar import evaluate_intraday_candidates
from app.market.tw_intraday_state import (
    _aware_taipei, _distance_below_high_pct, _load_samples, _number,
    _percent_change, _ranking_eligibility, _rolling_reference,
    read_taiwan_intraday_stock_states,
)
from app.market.tw_universe import list_taiwan_stock_universe


def _feature(value: float | None, reason: str) -> IntradayFeature:
    return IntradayFeature(value=value, reason=reason if value is None else None)


def _features(state: TaiwanIntradayStockState, *, generated: datetime, usable: bool) -> IntradayFeatures:
    price, previous = _number(state.current_price), _number(state.previous_close)
    high, low = _number(state.high_price), _number(state.low_price)
    price = price if state.has_actual_trade and price is not None and price > 0 else None
    previous = previous if previous is not None and previous > 0 else None
    balanced = bool(price is not None and high is not None and low is not None and 0 < low <= price <= high)
    values = {
        "change_pct": _feature(_percent_change(price, previous), "PRICE_OR_REFERENCE_UNAVAILABLE"),
        "distance_from_high_pct": _feature(_distance_below_high_pct(price, high) if balanced else None, "PRICE_RANGE_UNAVAILABLE_OR_INVALID"),
        "rebound_from_low_pct": _feature(_percent_change(price, low) if balanced else None, "PRICE_RANGE_UNAVAILABLE_OR_INVALID"),
        "intraday_range_pct": _feature((high - low) / previous * 100 if balanced and previous else None, "PRICE_RANGE_OR_REFERENCE_UNAVAILABLE"),
    }
    # Historical returns require trustworthy event AND availability clocks.
    # Legacy samples do not have that evidence and cannot become PIT features.
    samples = [sample for sample in _load_samples(state.samples_json, trade_date=state.trade_date)
               if sample.get("sample_contract_version") == "tw.trade_sample.v2"
               and sample.get("lineage_complete") is True
               and isinstance(sample.get("raw_result_ids"), list) and sample["raw_result_ids"]
               and all(isinstance(raw_id, str) and raw_id.strip() for raw_id in sample["raw_result_ids"])
               and (event := _aware_taipei(sample.get("price_as_of"))) is not None
               and (received := _aware_taipei(sample.get("received_at"))) is not None
               and event <= received <= generated]
    at = _aware_taipei(state.price_as_of)
    for minutes in (1, 3, 5, 15):
        reference = _rolling_reference(samples, current_time=at, minutes=minutes) if at and usable else None
        values[f"return_{minutes}m"] = IntradayFeature(
            value=_percent_change(price, reference[1]) if reference else None,
            reason=None if reference and price else "REFERENCE_SAMPLE_UNAVAILABLE" if usable else "CURRENT_RESEARCH_EVIDENCE_REQUIRED",
            reference_time=reference[0] if reference else None,
            reference_raw_result_ids=tuple(sorted({str(raw_id)
                for sample in samples
                if reference and _aware_taipei(sample.get("price_as_of")) == reference[0]
                and _number(sample.get("price")) == reference[1]
                for raw_id in sample["raw_result_ids"]})),
        )
    return IntradayFeatures(**values)


def _raw_ids(value: str | None) -> tuple[str, ...]:
    try:
        rows = json.loads(value or "[]")
    except (TypeError, ValueError):
        return ()
    return tuple(item for item in rows if isinstance(item, str) and item.strip()) if isinstance(rows, list) else ()


def read_tw_intraday_discovery(db: Session, *, evaluated_at: datetime | None = None) -> IntradayDiscovery:
    if evaluated_at is not None and evaluated_at.tzinfo is None:
        raise ValueError("evaluated_at must be timezone aware")
    generated = (evaluated_at or datetime.now(TAIWAN_TZ)).astimezone(TAIWAN_TZ)
    phase = taiwan_market_session_phase(generated)
    # no_autoflush prevents an incidental read from persisting caller-owned WIP.
    with db.no_autoflush:
        stocks = list_taiwan_stock_universe(db)
        pairs = read_taiwan_intraday_stock_states(db, stocks=stocks, trade_date=generated.date())
    revision = sha256(json.dumps([(stock.market.upper(), stock.stock_id) for stock in stocks],
                                separators=(",", ":")).encode()).hexdigest()
    missing = {stock.stock_id: "CURRENT_SESSION_OBSERVATION_MISSING" for stock in stocks}
    observations = []
    exclusions = {}
    freshness = Counter()
    coverage_count = 0
    actual_price_count = no_trade_count = 0
    for state, stock in pairs:
        eligibility = _ranking_eligibility(db, state, generated=generated)
        at = _aware_taipei(state.price_as_of)
        event = _aware_taipei(state.event_time)
        received = eligibility["observation_received_at"]
        # Do not reinterpret latest-state storage as an historical replay store.
        if event is None or received is None or event > generated or received > generated or (at and at > generated):
            missing[stock.stock_id] = "OBSERVATION_NOT_AVAILABLE_AT_EVALUATION"
            continue
        del missing[stock.stock_id]
        ids = _raw_ids(state.component_raw_result_ids_json)
        lineage_ok = bool(state.lineage_complete and ids)
        actual_price_count += bool(state.has_actual_trade and (_number(state.current_price) or 0) > 0)
        no_trade_count += eligibility["coverage_reason"] == "valid_no_trade"
        ranking = bool(eligibility["facts_usable_for_ranking"] and lineage_ok)
        research = bool(eligibility["intraday_research_usable"] and lineage_ok)
        reasons = []
        if not lineage_ok:
            reasons.append("LINEAGE_INCOMPLETE")
        if not ranking:
            reasons.append(str(eligibility["coverage_reason"]).upper())
        if not research:
            reasons.append("CURRENT_RESEARCH_EVIDENCE_REQUIRED")
        features = _features(state, generated=generated, usable=research)
        if features.distance_from_high_pct.value is None:
            research = False
            reasons.append("PRICE_RANGE_UNAVAILABLE_OR_INVALID")
        freshness[eligibility["observation_received_freshness"]] += 1
        # A received but price-less traded symbol does not count as usable coverage.
        # Verified no-trade can count toward coverage without becoming rankable.
        coverage_count += bool(eligibility["breadth_usable"] and lineage_ok)
        if reasons:
            exclusions[stock.stock_id] = tuple(dict.fromkeys(reasons))
        observations.append(DiscoveryObservation(
            stock_id=stock.stock_id, stock_name=stock.stock_name, market=state.market,
            trade_date=state.trade_date, as_of=at, received_at=received,
            freshness=eligibility["last_trade_recency"],
            receipt_freshness=eligibility["observation_received_freshness"],
            ranking_eligible=ranking, research_eligible=research,
            cumulative_volume_lots=_number(state.cumulative_volume_lots), features=features,
            lineage=IntradayLineage(provider=state.provider, source=state.source,
                                   raw_result_ids=ids, state_version=state.state_contract_version,
                                   calculation_version=state.calculation_version, complete=lineage_ok),
            exclusion_reasons=exclusions.get(stock.stock_id, ()),
        ))
    count = len(stocks)
    ratio = coverage_count / count if count else 0.0
    ranking_count = sum(row.ranking_eligible for row in observations)
    research_count = sum(row.research_eligible for row in observations)
    status = "blocked" if not count or not coverage_count else "ready" if ratio >= 0.95 else "partial"
    times = [row.as_of for row in observations if row.as_of is not None]
    limitations = ["LATEST_STATE_ONLY_REPLAY_REQUIRES_SEQUENTIAL_INPUT", "LIGHTWEIGHT_SAMPLES_NOT_COMPLETE_1M_BARS",
                   "RVOL_TIME_BASELINE_UNAVAILABLE", "VOLUME_VELOCITY_UNAVAILABLE"]
    if status != "ready":
        limitations.append("DISCOVERY_COVERAGE_BELOW_95_PERCENT")
    if coverage_count < count:
        limitations.append("INCOMPLETE_UNIVERSE_OBSERVATIONS")
    if research_count < ranking_count:
        limitations.append("FACTUAL_RANKABILITY_DOES_NOT_IMPLY_CURRENT_MOMENTUM")
    if phase not in {"regular", "closing_auction", "close_resolution"}:
        status = "blocked"
        limitations.append("CURRENT_INTRADAY_SESSION_REQUIRED")
    return IntradayDiscovery(
        evaluated_at=generated, session_phase=phase,
        coverage=DiscoveryCoverage(
            universe_revision=revision, universe_count=count, observed_count=len(observations),
            coverage_count=coverage_count, ranking_eligible_count=ranking_count,
            research_eligible_count=research_count, coverage_ratio=ratio, status=status,
            actual_trade_price_count=actual_price_count,
            actual_price_unavailable_count=len(observations) - actual_price_count - no_trade_count,
            verified_no_trade_count=no_trade_count,
            count_ratios={key: value / count if count else 0.0 for key, value in {
                "observed": len(observations), "actual_price": actual_price_count,
                "actual_price_unavailable": len(observations) - actual_price_count - no_trade_count,
                "verified_no_trade": no_trade_count, "usable": coverage_count,
                "ranking_eligible": ranking_count, "research_eligible": research_count,
            }.items()},
            is_full_market=bool(count and coverage_count == count and status == "ready"),
            as_of=max(times, default=None), oldest_as_of=min(times, default=None),
            freshness_counts=dict(freshness), missing_reasons=missing, exclusion_reasons=exclusions,
        ),
        observations=tuple(observations), limitations=tuple(limitations),
    )


def build_tw_intraday_radar_snapshot(
    db: Session, *, evaluated_at: datetime | None = None, config: IntradayCandidateConfig | None = None,
) -> IntradayRadarResult:
    return evaluate_intraday_candidates(read_tw_intraday_discovery(db, evaluated_at=evaluated_at), config=config)
