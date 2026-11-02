"""Bounded, cache-only completed-daily swing research (no trade triggers/orders).

Internal entry points: ``screen_tw_swing_candidates`` accepts pinned owner evidence;
``build_tw_swing_screening_snapshot`` reads an explicit stock subset from existing
owners. Holding horizons are trading sessions, not calendar days. This module
does not calculate indicators, build Price Maps, refresh data, or calculate R/R.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, time, timezone
from enum import Enum
from hashlib import sha256
import json
from math import isfinite
from typing import Any, Literal

from pydantic import AwareDatetime, Field, model_validator
from sqlalchemy.orm import Session

from app.market.trading_calendar import TAIWAN_TZ, latest_completed_taiwan_session_date
from app.market.tw_bar_contracts import TaiwanBarSeriesRead
from app.market.tw_technical_service import TaiwanTechnicalSeriesRead
from app.market_data.contracts import BarFinalization, CanonicalModel, SourceLineage


FEATURE_VERSION = "tw.swing.screen.v1"
RANKING_POLICY = "tw.swing.completed_daily.v2"


class SwingReason(str, Enum):
    UNIVERSE_MEMBER_UNAVAILABLE = "UNIVERSE_MEMBER_UNAVAILABLE"
    DAILY_NOT_COMPUTED = "DAILY_NOT_COMPUTED"
    DAILY_HISTORY_GAP = "DAILY_HISTORY_GAP"
    DAILY_NOT_COMPLETED = "DAILY_NOT_COMPLETED"
    CALENDAR_COVERAGE_UNKNOWN = "CALENDAR_COVERAGE_UNKNOWN"
    SOURCE_TIME_UNKNOWN = "SOURCE_TIME_UNKNOWN"
    SOURCE_AFTER_CUTOFF = "SOURCE_AFTER_CUTOFF"
    SOURCE_IDENTITY_MISMATCH = "SOURCE_IDENTITY_MISMATCH"
    TECHNICAL_NOT_USABLE = "TECHNICAL_NOT_USABLE"
    TECHNICAL_FEATURE_MISSING = "TECHNICAL_FEATURE_MISSING"
    SNAPSHOT_NOT_COMPUTED = "SNAPSHOT_NOT_COMPUTED"
    SNAPSHOT_NOT_USABLE = "SNAPSHOT_NOT_USABLE"
    SNAPSHOT_BASIS_MISMATCH = "SNAPSHOT_BASIS_MISMATCH"
    SNAPSHOT_REVISION_STALE = "SNAPSHOT_REVISION_STALE"
    CORPORATE_ACTION_UNKNOWN = "CORPORATE_ACTION_UNKNOWN"
    CORPORATE_ACTION_AFFECTED = "CORPORATE_ACTION_AFFECTED"
    LIQUIDITY_UNKNOWN = "LIQUIDITY_UNKNOWN"
    LIQUIDITY_BELOW_MINIMUM = "LIQUIDITY_BELOW_MINIMUM"
    SHORT_PRICE_CAP = "SHORT_PRICE_CAP"
    CURRENT_PRICE_UNKNOWN = "CURRENT_PRICE_UNKNOWN"
    INSTITUTIONAL_UNKNOWN = "INSTITUTIONAL_UNKNOWN"
    INSTITUTIONAL_COUNTER_EVIDENCE = "INSTITUTIONAL_COUNTER_EVIDENCE"
    NO_SETUP = "NO_SETUP"


class SwingScreenRequest(CanonicalModel):
    feature_version: Literal["tw.swing.screen.v1"] = FEATURE_VERSION
    # Deliberately explicit: the first internal service is a subset screen, never
    # an unbounded technical calculation over the entire market.
    stock_ids: tuple[str, ...] = Field(min_length=1, max_length=100)
    as_of_trade_date: date
    requested_at: AwareDatetime
    horizon_sessions: Literal[10, 15] = 10
    direction: Literal["long", "short", "both"] = "both"
    mode: Literal["aggressive", "confirmed", "both"] = "both"
    short_price_cap: float = Field(default=200, gt=0, le=200, allow_inf_nan=False)
    minimum_turnover_twd: float = Field(default=5_000_000, ge=0, allow_inf_nan=False)
    near_structure_pct: float = Field(default=2, gt=0, le=5, allow_inf_nan=False)
    top_n: int = Field(default=100, ge=1, le=100, strict=True)
    limit: int = Field(default=20, ge=1, le=200, strict=True)
    offset: int = Field(default=0, ge=0, le=5000, strict=True)

    @model_validator(mode="after")
    def _validate_scope(self) -> SwingScreenRequest:
        if len(set(self.stock_ids)) != len(self.stock_ids) or any(
            not item or item != item.strip() or len(item) > 20 for item in self.stock_ids
        ):
            raise ValueError("stock_ids must be distinct, nonempty bounded identifiers")
        if self.as_of_trade_date > latest_completed_taiwan_session_date(self.requested_at):
            raise ValueError("as_of_trade_date must be a completed Taiwan session")
        return self

    @property
    def ranking_config_hash(self) -> str:
        return _digest({"policy": RANKING_POLICY, **self.model_dump(mode="json", include={
            "minimum_turnover_twd", "near_structure_pct", "short_price_cap",
        })})


class SwingPriceMapEvidence(CanonicalModel):
    status: Literal["ready", "empty", "partial", "missing", "not_computed", "failed", "building"]
    published_at: AwareDatetime | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    reason_codes: tuple[SwingReason, ...] = ()


class SwingInstitutionalEvidence(CanonicalModel):
    """Optional corroboration; unknown flow is never neutral/zero flow."""
    status: Literal["qualified", "partial", "unknown"] = "unknown"
    trade_dates: tuple[date, ...] = ()
    available_at: AwareDatetime | None = None
    foreign_net_shares: float | None = Field(default=None, allow_inf_nan=False)
    trust_net_shares: float | None = Field(default=None, allow_inf_nan=False)
    source_refs: tuple[str, ...] = ()


class SwingStockEvidence(CanonicalModel):
    stock_id: str
    market: Literal["TWSE", "TPEX"]
    stock_name: str | None = None
    active_ordinary_stock: bool
    bars: TaiwanBarSeriesRead | None = None
    technical: TaiwanTechnicalSeriesRead | None = None
    price_map: SwingPriceMapEvidence | None = None
    institutional: SwingInstitutionalEvidence = Field(default_factory=SwingInstitutionalEvidence)


class SwingSnapshotBasis(CanonicalModel):
    trade_date: date
    requested_at: AwareDatetime
    bar_series_revision: str | None = None
    technical_revision: str | None = None
    parameter_revision: str | None = None
    price_map_basis_revision: str | None = None
    price_map_published_at: AwareDatetime | None = None
    source_event_at: AwareDatetime | None = None
    source_received_at: AwareDatetime | None = None
    source_fetched_at: AwareDatetime | None = None
    daily_receipt_basis: Literal["received_at", "raw_receipt_fetched_at", "mixed", "unknown"] = "unknown"
    daily_cutoff_verified: bool = False
    evidence_cutoff_limitations: tuple[str, ...] = ()
    institutional_available_at: AwareDatetime | None = None
    source_refs: tuple[str, ...] = ()


class SwingAssessment(CanonicalModel):
    stock_id: str
    status: Literal["qualified", "limited", "excluded", "not_computed"]
    observed: bool = False
    reason_codes: tuple[SwingReason, ...] = ()
    excluded_directions: dict[str, tuple[SwingReason, ...]] = Field(default_factory=dict)
    matched: bool = False
    basis: SwingSnapshotBasis


class SwingRetestEvidence(CanonicalModel):
    level: float
    level_source: str
    level_basis_trade_date: date
    break_trade_date: date
    retest_trade_date: date
    break_volume_ratio: float
    break_pvo: float
    technical_revision: str


class SwingCandidate(CanonicalModel):
    stock_id: str
    stock_name: str | None
    market: Literal["TWSE", "TPEX"]
    direction: Literal["long", "short"]
    mode: Literal["aggressive", "confirmed"]
    setup_type: Literal["support_reversal", "pullback_continuation", "resistance_rejection", "breakout_retest", "breakdown_retest", "trend_discovery"]
    horizon_sessions: Literal[10, 15]
    stage: Literal["discovered", "research_qualified"]
    evidence_quality: Literal["qualified", "limited"]
    reference_close: float
    historical_short_price_cap: Literal["satisfied", "not_applicable"]
    # G3 owns current price, regulation, borrow and funding eligibility.
    current_short_price_cap: Literal["unknown", "not_applicable"]
    trigger_ready: Literal[False] = False
    execution_eligibility: Literal["unknown"] = "unknown"
    execution_ready: Literal[False] = False
    direction_score: float
    opportunity_score: float | None = None  # structural space %, never R/R
    liquidity_turnover_twd: float | None = None
    institutional: SwingInstitutionalEvidence
    zone: dict[str, Any] | None = None
    retest: SwingRetestEvidence | None = None
    reason_codes: tuple[SwingReason, ...] = ()
    counter_evidence: tuple[str, ...] = ()
    basis: SwingSnapshotBasis
    rank: int = Field(default=0, ge=0)


class SwingCoverage(CanonicalModel):
    scope: Literal["selected_universe"] = "selected_universe"
    sample_only: Literal[True] = True
    universe_count: int
    observed: int
    qualified: int
    incomplete: int
    excluded: int
    not_computed: int
    matched_symbols: int
    no_match: int
    candidate_count: int
    returned_count: int
    research_qualified_candidate_count: int = 0
    limited_candidate_count: int = 0
    complete: bool
    excluded_reason_counts: dict[str, int]


class SwingScreenResult(CanonicalModel):
    version: Literal["tw.swing.screen.v1"] = FEATURE_VERSION
    status: Literal["ready", "limited", "not_computed"]
    request: SwingScreenRequest
    ranking_policy: str = RANKING_POLICY
    ranking_config_hash: str
    snapshot_id: str
    universe_stock_ids: tuple[str, ...]
    coverage: SwingCoverage
    assessments: tuple[SwingAssessment, ...]
    candidates: tuple[SwingCandidate, ...]
    empty_result_is_valid: bool
    response_truncated: bool
    cache_policy: Literal["cache_only_no_refresh_no_build"] = "cache_only_no_refresh_no_build"


def _digest(value: Any) -> str:
    return sha256(json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if isfinite(number) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _day(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _daily_receipt(lineage: SourceLineage) -> tuple[datetime | None, str]:
    if lineage.received_at is not None:
        return lineage.received_at, "received_at"
    # The completed-daily owner projects RawFetchResult.fetched_at, not
    # received_at. Require its receipt reference so an updated_at fallback on
    # an unreceipted storage row cannot masquerade as acquisition evidence.
    if lineage.fetched_at is not None and lineage.raw_receipt_id:
        return lineage.fetched_at, "raw_receipt_fetched_at"
    return None, "unknown"


def _basis(request: SwingScreenRequest, item: SwingStockEvidence | None) -> SwingSnapshotBasis:
    bars, tech, pm = (item.bars, item.technical, item.price_map) if item else (None, None, None)
    lineages = [bar.lineage for bar in bars.bars] if bars else []
    receipts = [_daily_receipt(lineage) for lineage in lineages]
    receipt_kinds = {kind for _, kind in receipts}
    time_unknown = not lineages or any(lineage.event_at is None for lineage in lineages) or "unknown" in receipt_kinds
    after_cutoff = any(stamp and stamp > request.requested_at for lineage in lineages
                       for stamp in (lineage.event_at, lineage.received_at, lineage.fetched_at))
    limitations = []
    if time_unknown:
        limitations.append("Historical completed-daily discovery only: source event or traceable receipt time is missing; requested_at visibility and point-in-time replay are unverified.")
    if after_cutoff:
        limitations.append("Daily source evidence is later than requested_at; it cannot enter this historical ranking.")
    return SwingSnapshotBasis(
        trade_date=request.as_of_trade_date, requested_at=request.requested_at,
        bar_series_revision=bars.identity.series_revision if bars else None,
        technical_revision=tech.technical_revision if tech else None,
        parameter_revision=tech.parameter_contract.get("parameter_revision") if tech else None,
        price_map_basis_revision=pm.payload.get("basis_revision") if pm else None,
        price_map_published_at=pm.published_at if pm else None,
        source_event_at=max((x.event_at for x in lineages if x.event_at), default=None),
        source_received_at=max((x.received_at for x in lineages if x.received_at), default=None),
        source_fetched_at=max((x.fetched_at for x in lineages if x.fetched_at), default=None),
        daily_receipt_basis="unknown" if not receipts or "unknown" in receipt_kinds else next(iter(receipt_kinds)) if len(receipt_kinds) == 1 else "mixed",
        daily_cutoff_verified=not time_unknown and not after_cutoff,
        evidence_cutoff_limitations=tuple(limitations),
        institutional_available_at=item.institutional.available_at if item else None,
        source_refs=tuple(sorted({f"{x.provider}:{x.source}:{x.observation_id or x.content_hash or ''}" for x in lineages}
                                 | {x.raw_receipt_id for x in lineages if x.raw_receipt_id})),
    )


def _daily_reasons(request: SwingScreenRequest, item: SwingStockEvidence) -> list[SwingReason]:
    bars = item.bars
    if bars is None or not bars.bars:
        return [SwingReason.DAILY_NOT_COMPUTED]
    reasons = []
    if (bars.requested_interval != "1d" or bars.instrument.symbol != item.stock_id
            or bars.instrument.venue != item.market or bars.instrument.instrument_type.value != "stock"):
        reasons.append(SwingReason.SOURCE_IDENTITY_MISMATCH)
    dates = [bar.start_at.astimezone(TAIWAN_TZ).date() for bar in bars.bars]
    expected = bars.expected_sessions
    if (not expected or len(expected) < request.horizon_sessions or dates != sorted(set(dates))
            or dates[-1] != request.as_of_trade_date or tuple(dates) != expected
            or not bars.history.requested_coverage_satisfied):
        reasons.append(SwingReason.DAILY_HISTORY_GAP)
    if any(day > request.as_of_trade_date for day in dates):
        reasons.append(SwingReason.SOURCE_AFTER_CUTOFF)
    if (len(bars.bar_states) != len(bars.bars)
            or any(bar.finalization not in {BarFinalization.FINAL, BarFinalization.CORRECTED} for bar in bars.bars)
            or any(not state.technical_eligible or state.start_at != bar.start_at
                   for state, bar in zip(bars.bar_states, bars.bars))):
        reasons.append(SwingReason.DAILY_NOT_COMPLETED)
    for bar in bars.bars:
        lineage = bar.lineage
        if lineage.event_at is None or _daily_receipt(lineage)[0] is None:
            reasons.append(SwingReason.SOURCE_TIME_UNKNOWN)
        if any(stamp and stamp > request.requested_at for stamp in (lineage.event_at, lineage.received_at, lineage.fetched_at)):
            reasons.append(SwingReason.SOURCE_AFTER_CUTOFF)
    return list(dict.fromkeys(reasons))


def _structure_reasons(request: SwingScreenRequest, item: SwingStockEvidence) -> list[SwingReason]:
    reasons: list[SwingReason] = []
    tech, bars, pm = item.technical, item.bars, item.price_map
    if tech is None or not tech.decision_usable:
        reasons.append(SwingReason.TECHNICAL_NOT_USABLE)
    if tech and bars and (tech.instrument != bars.instrument or tech.interval != "1d"
                         or tech.bar_series_revision != bars.identity.series_revision
                         or not tech.points or _day(tech.points[-1].get("time")) != request.as_of_trade_date):
        reasons.append(SwingReason.SOURCE_IDENTITY_MISMATCH)
    if pm is None or pm.status == "not_computed":
        reasons.append(SwingReason.SNAPSHOT_NOT_COMPUTED)
        return reasons
    reasons.extend(pm.reason_codes)
    payload = pm.payload
    if pm.published_at is None:
        reasons.append(SwingReason.SOURCE_TIME_UNKNOWN)
    elif pm.published_at > request.requested_at:
        reasons.append(SwingReason.SOURCE_AFTER_CUTOFF)
    if (pm.status not in {"ready", "empty"} or payload.get("structure_input_usable") is not True
            or payload.get("version") != "tw.stock.price_map.v4"):
        reasons.append(SwingReason.SNAPSHOT_NOT_USABLE)
    reference = _mapping(payload.get("reference"))
    if (payload.get("stock_id") != item.stock_id or payload.get("structure_timeframe") != "daily"
            or _day(reference.get("trade_date")) != request.as_of_trade_date
            or not bars or _number(reference.get("price")) != float(bars.bars[-1].close_price)
            or not payload.get("basis_revision")
            or (tech and _mapping(payload.get("parameter_contract")).get("parameter_revision") != tech.parameter_contract.get("parameter_revision"))):
        reasons.append(SwingReason.SNAPSHOT_BASIS_MISMATCH)
    corporate = _mapping(payload.get("corporate_action"))
    if corporate.get("coverage_status") != "complete":
        reasons.append(SwingReason.CORPORATE_ACTION_UNKNOWN)
    if corporate.get("affected_dates") and corporate.get("adjustment_applied") is not True:
        reasons.append(SwingReason.CORPORATE_ACTION_AFFECTED)
    return list(dict.fromkeys(reasons))


def _qualified_institutional(request: SwingScreenRequest, item: SwingStockEvidence) -> SwingInstitutionalEvidence:
    value = item.institutional
    expected = item.bars.expected_sessions[-5:] if item.bars else ()
    if (value.status != "qualified" or not expected or value.trade_dates != expected
            or value.available_at is None or value.available_at > request.requested_at
            or value.foreign_net_shares is None or value.trust_net_shares is None):
        # Preserve status, dates and lineage without using partial/late sums.
        return value.model_copy(update={"status": "unknown", "foreign_net_shares": None, "trust_net_shares": None})
    return value


def _zones(item: SwingStockEvidence, side: str) -> list[dict[str, Any]]:
    zones = item.price_map.payload.get("zones")
    return [zone for zone in (zones if isinstance(zones, list) else [])
            if isinstance(zone, dict) and zone.get("side") == side
            and zone.get("scanner_eligible") is True and zone.get("geometry_status") == "ready"
            and _number(zone.get("lower_bound")) is not None and _number(zone.get("upper_bound")) is not None
            and 0 < float(zone["lower_bound"]) < float(zone["upper_bound"])]


def _completed_retest(item: SwingStockEvidence, direction: str, horizon: int) -> SwingRetestEvidence | None:
    """Classify completed candles against preceding completed-point owner levels.

    No rolling extrema, MA, PVO or other indicator is calculated here. A level
    must already exist on the preceding technical point, followed by a volume-
    confirmed break, no intervening close invalidation, and a later held retest.
    Caller enforces the canonical/technical/corporate/receipt quality gates.
    """
    tech, bars = item.technical, item.bars.bars
    if tech is None or len(tech.points) != len(bars):
        return None
    if any(_day(point.get("time")) != bar.start_at.astimezone(TAIWAN_TZ).date()
           for point, bar in zip(tech.points, bars)):
        return None
    params = tech.parameter_contract
    period = params.get("support_resistance_period")
    volume_windows = params.get("volume_ma_windows") or ()
    threshold = _number(params.get("breakout_volume_ratio_threshold"))
    if type(period) is not int or len(volume_windows) < 2 or threshold is None or threshold <= 0:
        return None
    sign = 1 if direction == "long" else -1
    key = f"{'resistance' if direction == 'long' else 'support'}{period}"
    last = bars[-1]
    for index in range(len(bars) - 2, max(0, len(bars) - horizon - 1), -1):
        level = _number(_mapping(tech.points[index - 1].get("support_resistance")).get(key))
        point = tech.points[index]
        volume_ma = _number(_mapping(point.get("volume_ma")).get(f"volume_ma{volume_windows[1]}"))
        pvo = _number(_mapping(point.get("pvo")).get("pvo"))
        volume = _number(bars[index].volume.value) if bars[index].volume else None
        if level is None or level <= 0 or volume_ma is None or volume_ma <= 0 or volume is None or pvo is None:
            continue
        ratio = volume / volume_ma
        if ratio < threshold or pvo <= 0:
            continue
        if sign * (float(bars[index - 1].close_price) - level) > 0 or sign * (float(bars[index].close_price) - level) <= 0:
            continue
        if any(sign * (float(bar.close_price) - level) < 0 for bar in bars[index + 1:]):
            continue
        wick = float(last.low_price if direction == "long" else last.high_price)
        if sign * (wick - level) > 0 or sign * (float(last.close_price) - level) < 0:
            continue
        return SwingRetestEvidence(level=level, level_source=f"TaiwanTechnicalService.support_resistance.{key}",
            level_basis_trade_date=bars[index - 1].start_at.astimezone(TAIWAN_TZ).date(),
            break_trade_date=bars[index].start_at.astimezone(TAIWAN_TZ).date(),
            retest_trade_date=last.start_at.astimezone(TAIWAN_TZ).date(),
            break_volume_ratio=round(ratio, 6), break_pvo=pvo, technical_revision=tech.technical_revision)
    return None


def _stock_candidates(request: SwingScreenRequest, item: SwingStockEvidence,
                      reasons: list[SwingReason], basis: SwingSnapshotBasis,
                      excluded: dict[str, tuple[SwingReason, ...]]) -> list[SwingCandidate]:
    bars = item.bars.bars
    last, previous = bars[-1], bars[-2]
    close, prior = float(last.close_price), float(previous.close_price)
    window_return = (close / float(bars[-request.horizon_sessions].close_price) - 1) * 100
    point = item.technical.points[-1] if item.technical and item.technical.points else {}
    ma20 = _number((point.get("ma") or {}).get("ma20"))
    ma60 = _number((point.get("ma") or {}).get("ma60"))
    atr = _number((point.get("atr") or {}).get("atr14"))
    if ma20 is None or ma60 is None or atr is None or atr <= 0:
        reasons.append(SwingReason.TECHNICAL_FEATURE_MISSING)
    institutional = _qualified_institutional(request, item)
    rows = []
    for direction in ("long", "short"):
        if request.direction not in {direction, "both"} or direction in excluded:
            continue
        sign = 1 if direction == "long" else -1
        mode: Literal["aggressive", "confirmed"] = "aggressive"
        zone = None
        opportunity = None
        setup = "trend_discovery"
        retest = None
        if reasons:
            if sign * window_return <= 0:
                continue
        else:
            retest = _completed_retest(item, direction, request.horizon_sessions)
            side = "downside" if direction == "long" else "upside"
            near = sorted(_zones(item, side), key=lambda z: (min(abs(close - z["lower_bound"]), abs(close - z["upper_bound"])), z.get("zone_id", "")))
            near = [z for z in near if max(z["lower_bound"] - close, close - z["upper_bound"], 0) / close * 100 <= request.near_structure_pct]
            trend = sign * (ma20 - ma60) >= 0
            ma_near = abs(close - ma20) / close * 100 <= request.near_structure_pct
            if retest is not None:
                setup = "breakout_retest" if direction == "long" else "breakdown_retest"
                mode = "confirmed"
            elif direction == "long" and trend and ma_near:
                setup = "pullback_continuation"
                zone = near[0] if near else None
            elif near and (direction == "long" or trend):
                zone = near[0]
                setup = "support_reversal" if direction == "long" else "resistance_rejection"
            else:
                continue
            boundary = retest.level if retest else (zone["upper_bound"] if direction == "long" else zone["lower_bound"]) if zone else ma20
            if sign * (close - prior) > 0 and sign * (close - float(last.open_price)) > 0 and sign * (close - boundary) >= 0:
                mode = "confirmed"
            targets = _zones(item, "upside" if direction == "long" else "downside")
            spaces = [sign * ((z["lower_bound"] if direction == "long" else z["upper_bound"]) - close) / close * 100 for z in targets]
            space = min((x for x in spaces if x > 0), default=None)
            opportunity = round(space, 6) if space is not None else None
        if request.mode not in {mode, "both"}:
            continue
        candidate_reasons = list(reasons)
        counter = ["Completed daily structure can fail on the next session; no current trade trigger is established."]
        if institutional.status != "qualified":
            candidate_reasons.append(SwingReason.INSTITUTIONAL_UNKNOWN)
        elif sign * institutional.foreign_net_shares < 0 or sign * institutional.trust_net_shares < 0:
            candidate_reasons.append(SwingReason.INSTITUTIONAL_COUNTER_EVIDENCE)
            counter.append("Qualified five-session institutional flow opposes the candidate direction.")
        if direction == "short":
            candidate_reasons.append(SwingReason.CURRENT_PRICE_UNKNOWN)
            counter.append("Current price cap, borrow, regulation, funding and event eligibility remain unverified.")
        rows.append(SwingCandidate(
            stock_id=item.stock_id, stock_name=item.stock_name, market=item.market,
            direction=direction, mode=mode, setup_type=setup, horizon_sessions=request.horizon_sessions,
            stage="discovered" if reasons else "research_qualified",
            evidence_quality="limited" if reasons else "qualified", reference_close=close,
            historical_short_price_cap="satisfied" if direction == "short" else "not_applicable",
            current_short_price_cap="unknown" if direction == "short" else "not_applicable",
            direction_score=round(sign * window_return, 6), opportunity_score=opportunity,
            liquidity_turnover_twd=float(last.turnover_value) if last.turnover_value is not None else None,
            institutional=institutional, zone=zone, retest=retest, reason_codes=tuple(dict.fromkeys(candidate_reasons)),
            counter_evidence=tuple(counter), basis=basis,
        ))
    return rows


def screen_tw_swing_candidates(request: SwingScreenRequest, inputs: tuple[SwingStockEvidence, ...]) -> SwingScreenResult:
    """Deterministic pure screen. Input owner objects must be cutoff-scoped.

    A whole contaminated technical revision is rejected, never truncated into a
    fabricated historical revision. Missing structures or unverified source
    times may produce limited daily-momentum discoveries without exposing exact
    price zones or claiming historical receipt visibility / PIT replay.
    """
    by_id = {item.stock_id: item for item in inputs}
    if len(by_id) != len(inputs) or set(by_id) - set(request.stock_ids):
        raise ValueError("evidence must contain unique requested stock_ids")
    assessments, candidates = [], []
    for stock_id in sorted(request.stock_ids):
        item = by_id.get(stock_id)
        basis = _basis(request, item)
        observed = bool(item and item.bars and item.bars.bars)
        excluded: dict[str, tuple[SwingReason, ...]] = {}
        if item is None or not item.active_ordinary_stock:
            status, reasons, rows = "excluded", [SwingReason.UNIVERSE_MEMBER_UNAVAILABLE], []
        else:
            reasons = _daily_reasons(request, item)
            rows = []
            if any(reason is not SwingReason.SOURCE_TIME_UNKNOWN for reason in reasons):
                status = "not_computed" if reasons == [SwingReason.DAILY_NOT_COMPUTED] else "limited"
            else:
                last = item.bars.bars[-1]
                if request.direction in {"short", "both"} and float(last.close_price) >= request.short_price_cap:
                    excluded["short"] = (SwingReason.SHORT_PRICE_CAP,)
                turnover = _number(last.turnover_value)
                if turnover is None or last.turnover_currency != "TWD" or last.volume is None:
                    reasons.append(SwingReason.LIQUIDITY_UNKNOWN)
                elif turnover < request.minimum_turnover_twd:
                    reasons.append(SwingReason.LIQUIDITY_BELOW_MINIMUM)
                if SwingReason.LIQUIDITY_BELOW_MINIMUM in reasons or (request.direction == "short" and excluded):
                    status = "excluded"
                else:
                    reasons.extend(_structure_reasons(request, item))
                    rows = _stock_candidates(request, item, reasons, basis, excluded)
                    status = "limited" if reasons else "qualified"
            if status == "qualified" and not rows:
                reasons.append(SwingReason.NO_SETUP)
        candidates.extend(rows)
        assessments.append(SwingAssessment(stock_id=stock_id, status=status, observed=observed,
            reason_codes=tuple(dict.fromkeys(reasons)), excluded_directions=excluded, matched=bool(rows), basis=basis))
    candidates.sort(key=lambda row: (
        row.evidence_quality != "qualified", -row.direction_score,
        row.opportunity_score is None, -(row.opportunity_score or 0),
        row.liquidity_turnover_twd is None, -(row.liquidity_turnover_twd or 0),
        row.stock_id, row.direction, row.mode, row.setup_type,
    ))
    ranked = tuple(row.model_copy(update={"rank": rank}) for rank, row in enumerate(candidates, 1))
    selected = ranked[:request.top_n][request.offset:request.offset + request.limit]
    counts = Counter(item.status for item in assessments)
    reasons = Counter(reason.value for item in assessments for reason in set(
        (*item.reason_codes, *(r for rs in item.excluded_directions.values() for r in rs))))
    complete = not counts["limited"] and not counts["not_computed"]
    # Unknown membership is unresolved coverage, whereas known price/liquidity
    # exclusions are fully accounted-for observations.
    complete = complete and not reasons[SwingReason.UNIVERSE_MEMBER_UNAVAILABLE.value] and not reasons[SwingReason.SOURCE_TIME_UNKNOWN.value]
    coverage = SwingCoverage(universe_count=len(assessments), observed=sum(x.observed for x in assessments),
        qualified=counts["qualified"], incomplete=counts["limited"], excluded=counts["excluded"], not_computed=counts["not_computed"],
        matched_symbols=sum(x.matched for x in assessments), no_match=sum(x.status == "qualified" and not x.matched for x in assessments),
        candidate_count=len(ranked), returned_count=len(selected), complete=complete,
        research_qualified_candidate_count=sum(c.stage == "research_qualified" for c in ranked),
        limited_candidate_count=sum(c.evidence_quality == "limited" for c in ranked),
        excluded_reason_counts=dict(sorted(reasons.items())))
    snapshot_id = _digest({"request": request.model_dump(mode="json", exclude={"limit", "offset", "top_n"}),
        "config": request.ranking_config_hash, "assessments": [x.model_dump(mode="json") for x in assessments],
        "candidates": [x.model_dump(mode="json") for x in ranked]})
    return SwingScreenResult(status="ready" if complete else "not_computed" if counts["not_computed"] == len(assessments) else "limited",
        request=request, ranking_config_hash=request.ranking_config_hash, snapshot_id=snapshot_id,
        universe_stock_ids=tuple(sorted(request.stock_ids)), coverage=coverage,
        assessments=tuple(assessments), candidates=selected,
        empty_result_is_valid=complete and not ranked, response_truncated=len(selected) < len(ranked))


def _read_institutional(db: Session, request: SwingScreenRequest, stock_id: str,
                        sessions: tuple[date, ...]) -> SwingInstitutionalEvidence:
    from app.market.service import list_stock_institutional_trade_history

    expected = sessions[-5:]
    if len(expected) != 5:
        return SwingInstitutionalEvidence()
    rows = list_stock_institutional_trade_history(db, stock_id=stock_id,
        from_date=expected[0], to_date=expected[-1], limit=250)
    by_date = {}
    available = []
    refs = []
    for row in sorted(rows, key=lambda x: x.id):
        stamps = [getattr(row, name, None) for name in ("created_at", "updated_at")]
        if any(stamp is None for stamp in stamps):
            continue
        # SQLite strips tzinfo from UTC storage timestamps. These are local
        # persistence visibility bounds, not the original market event time.
        stamps = [stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp for stamp in stamps]
        if max(stamps) > request.requested_at or row.trade_date not in expected:
            continue
        by_date[row.trade_date] = row
        available.extend(stamps)
        refs.append(f"raw_fetch_result:{row.raw_result_id}")
    dates = tuple(sorted(by_date))
    complete = dates == expected and all(row.foreign_investor_net is not None and row.investment_trust_net is not None for row in by_date.values())
    return SwingInstitutionalEvidence(status="qualified" if complete else "partial" if dates else "unknown",
        trade_dates=dates, available_at=max(available, default=None),
        foreign_net_shares=float(sum(row.foreign_investor_net for row in by_date.values())) if complete else None,
        trust_net_shares=float(sum(row.investment_trust_net for row in by_date.values())) if complete else None,
        source_refs=tuple(sorted(set(refs))))


def build_tw_swing_screening_snapshot(db: Session, *, request: SwingScreenRequest) -> SwingScreenResult:
    return screen_tw_swing_candidates(request, read_tw_swing_evidence(db, request=request))


def read_tw_swing_evidence(db: Session, *, request: SwingScreenRequest) -> tuple[SwingStockEvidence, ...]:
    """Actual internal read entry: bounded subset, no writes/network/refresh.

    Uses canonical receipt cutoff + existing technical engine. Published daily
    Price Maps are consumed as-is; missing/partial/stale snapshots stay limited.
    No route/AI/MCP capability is advertised here (G6 owns outward wiring).
    """
    from app.market.price_map_snapshot_repository import (
        read_input_revisions, read_price_map_external_revision, read_price_map_snapshots,
        snapshot_matches, snapshot_storage_available,
    )
    from app.market.technical_parameters import get_technical_analysis_parameters
    from app.market.tw_bar_service import TaiwanBarService
    from app.market.tw_technical_service import TaiwanTechnicalService
    from app.market.tw_universe import list_taiwan_stock_universe

    stocks = list_taiwan_stock_universe(db, stock_ids=request.stock_ids)
    ids = [stock.stock_id for stock in stocks]
    storage = snapshot_storage_available(db)
    snapshots = read_price_map_snapshots(db, ids, "daily") if storage else {}
    revisions = read_input_revisions(db, ids) if storage else {}
    external_revision = read_price_map_external_revision() if snapshots else ""
    parameters = get_technical_analysis_parameters()
    # The daily owner accepts an inclusive to_date derived from to_time.date().
    # Midnight on T+1 would accidentally admit T+1 receipts in a historical read.
    end = datetime.combine(request.as_of_trade_date, time.max, TAIWAN_TZ)
    bar_service, technical_service = TaiwanBarService(db), TaiwanTechnicalService()
    inputs = []
    for stock in stocks:
        bars = bar_service.read_bars(instrument_id=stock.stock_id, interval="1d",
            to_time=end, requested_at=request.requested_at, include_partial=False, limit=300)
        technical = technical_service.calculate(bars, parameters=parameters)
        row = snapshots.get(stock.stock_id)
        pm = None
        if row:
            try:
                payload = json.loads(row.payload_json or "{}")
            except (ValueError, TypeError):
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            matched = snapshot_matches(row, input_revision=revisions.get(stock.stock_id, 0),
                parameter_revision=parameters.revision, corporate_revision=external_revision, basis_date=request.as_of_trade_date)
            published = row.published_at
            if published is not None and published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)
            pm = SwingPriceMapEvidence(status=row.status if row.status in {"ready", "empty", "partial", "missing", "failed", "building"} else "missing",
                payload=payload, published_at=published,
                reason_codes=() if matched else (SwingReason.SNAPSHOT_REVISION_STALE,))
        inputs.append(SwingStockEvidence(stock_id=stock.stock_id, stock_name=stock.stock_name,
            market=stock.market.upper(), active_ordinary_stock=True, bars=bars, technical=technical, price_map=pm,
            institutional=_read_institutional(db, request, stock.stock_id, bars.expected_sessions)))
    return tuple(inputs)
