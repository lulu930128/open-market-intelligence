"""Resumable whole-universe cheap discovery -> bounded G2 detailed research.

Canonical completed daily is the same owner beneath market.sample_ranking. We
read exact sessions in <=100-stock batches, never its truncated outward lists.
The caller retains the typed checkpoint (JSON round-trippable); no second cache,
manager, DB writer, provider I/O or implicit background work is introduced.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta
import json
from typing import Literal

from pydantic import AwareDatetime, Field, model_validator
from sqlalchemy.orm import Session

from app.market.daily_price_repository import TaiwanOfficialDailyBarRepository
from app.market.exchange_calendar_cache import exchange_calendar_read_scope
from app.market.price_map_snapshot_repository import (
    read_input_revisions, read_price_map_external_revision, read_price_map_snapshots,
    snapshot_matches, snapshot_storage_available,
)
from app.market.technical_parameters import get_technical_analysis_parameters
from app.market.trading_calendar import (
    TAIWAN_TZ, has_taiwan_calendar_year, is_taiwan_trading_day,
)
from app.market.tw_swing_screening import (
    SwingInstitutionalEvidence, SwingReason, SwingScreenRequest, SwingScreenResult,
    _daily_receipt, _digest, _mapping, _number,
    build_tw_swing_screening_snapshot,
)
from app.market.tw_universe import list_taiwan_stock_universe
from app.market_data.contracts import BarFinalization, CanonicalModel


PREFILTER_VERSION = "tw.swing.prefilter.v1"
PREFILTER_POLICY = "tw.swing.prefilter.eligibility.v2"


class SwingDiscoveryRequest(CanonicalModel):
    as_of_trade_date: date
    requested_at: AwareDatetime
    horizon_sessions: Literal[10, 15] = 10
    direction: Literal["long", "short", "both"] = "both"
    mode: Literal["aggressive", "confirmed", "both"] = "both"
    markets: tuple[Literal["TWSE", "TPEX"], ...] = ("TWSE", "TPEX")
    stock_ids: tuple[str, ...] | None = Field(default=None, min_length=1, max_length=100,
                                             exclude_if=lambda value: value is None)
    top_n: int = Field(default=20, ge=1, le=100, strict=True)
    batch_size: int = Field(default=100, ge=1, le=100, strict=True)
    max_batches: int = Field(default=1, ge=1, le=20, strict=True)
    detail_batch_size: int = Field(default=10, ge=1, le=100, strict=True)
    max_detail_batches: int = Field(default=1, ge=1, le=10, strict=True)
    short_price_cap: float = Field(default=200, gt=0, le=200, allow_inf_nan=False)
    minimum_turnover_twd: float = Field(default=5_000_000, ge=0, allow_inf_nan=False)
    near_structure_pct: float = Field(default=2, gt=0, le=5, allow_inf_nan=False)

    @model_validator(mode="after")
    def _validate(self) -> SwingDiscoveryRequest:
        self.detail_request(self.stock_ids or ("scope_validation",))
        if not self.markets or len(set(self.markets)) != len(self.markets):
            raise ValueError("markets must be a nonempty distinct TWSE/TPEX selection")
        return self

    def detail_request(self, stock_ids: tuple[str, ...]) -> SwingScreenRequest:
        return SwingScreenRequest(stock_ids=stock_ids, as_of_trade_date=self.as_of_trade_date,
            requested_at=self.requested_at, horizon_sessions=self.horizon_sessions,
            direction=self.direction, mode=self.mode, short_price_cap=self.short_price_cap,
            minimum_turnover_twd=self.minimum_turnover_twd, near_structure_pct=self.near_structure_pct,
            top_n=100, limit=200)


class SwingPrefilterRow(CanonicalModel):
    stock_id: str
    market: Literal["TWSE", "TPEX"]
    status: Literal["eligible", "limited", "unknown", "excluded"]
    observed: bool
    daily_usable: bool
    reference_close: float | None = None
    window_return_pct: float | None = None
    turnover_twd: float | None = None
    allowed_directions: tuple[Literal["long", "short"], ...] = ()
    excluded_directions: dict[str, tuple[SwingReason, ...]] = Field(default_factory=dict)
    institutional: SwingInstitutionalEvidence = Field(default_factory=SwingInstitutionalEvidence)
    institutional_policy: Literal["deferred_to_top_n_detail"] = "deferred_to_top_n_detail"
    corporate_quality: Literal["complete", "affected", "unknown"] = "unknown"
    price_map_status: str = "not_computed"
    technical_status: Literal["not_read"] = "not_read"
    source_event_at: AwareDatetime | None = None
    source_available_at: AwareDatetime | None = None
    receipt_cutoff_verified: bool = False
    evidence_revision: str
    reason_codes: tuple[SwingReason, ...] = ()
    canonical_rejections: tuple[str, ...] = ()


class SwingDiscoveryCheckpoint(CanonicalModel):
    version: Literal["tw.swing.prefilter.v1"] = PREFILTER_VERSION
    request_revision: str
    source_revision: str
    universe_stock_ids: tuple[str, ...] = Field(max_length=5000)
    rows: tuple[SwingPrefilterRow, ...] = Field(default=(), max_length=5000)
    detail_batches: tuple[SwingScreenResult, ...] = Field(default=(), max_length=100)

    @model_validator(mode="after")
    def _validate_prefix(self) -> SwingDiscoveryCheckpoint:
        if len(set(self.universe_stock_ids)) != len(self.universe_stock_ids):
            raise ValueError("checkpoint universe contains duplicates")
        if tuple(row.stock_id for row in self.rows) != self.universe_stock_ids[:len(self.rows)]:
            raise ValueError("checkpoint rows must be an exact processed universe prefix")
        if self.detail_batches and len(self.rows) != len(self.universe_stock_ids):
            raise ValueError("checkpoint detail cannot precede completed universe consideration")
        return self


class SwingDiscoveryCoverage(CanonicalModel):
    universe_count: int
    considered: int
    pending: int
    observed: int
    daily_usable: int
    eligible: int
    incomplete: int
    unknown: int
    excluded: int
    corporate_unknown: int
    institutional_unknown: int
    all_considered: bool
    daily_coverage_complete: bool
    sample_only: bool
    is_full_market: bool
    full_market_scope: bool
    quality_complete: bool
    quality_status: Literal["complete", "partial", "unknown"]
    detail_requested: int
    detail_considered: int
    detail_pending: int
    detail_qualified: int
    detail_incomplete: int
    detail_candidate_count: int
    prefilter_selected: int = 0
    prefilter_quality_complete: bool = False
    detail_sample_only: bool = True
    detail_research_qualified_candidates: int = 0
    detail_limited_candidates: int = 0
    deferred_reason_counts: dict[str, int] = Field(default_factory=dict)
    scope: Literal["active_ordinary_stocks", "selected_ordinary_stocks"] = "active_ordinary_stocks"
    excluded_reason_counts: dict[str, int]
    canonical_rejection_counts: dict[str, int]


class SwingDiscoveryResult(CanonicalModel):
    version: Literal["tw.swing.prefilter.v1"] = PREFILTER_VERSION
    status: Literal["in_progress", "ready", "limited", "empty"]
    request: SwingDiscoveryRequest
    feature_revision: str
    snapshot_id: str
    expected_sessions: tuple[date, ...]
    calendar_coverage_known: bool
    canonical_generations_pinned: bool
    universe_basis: Literal["current_active_ordinary_stock_master"] = "current_active_ordinary_stock_master"
    historical_universe_pit_verified: Literal[False] = False
    checkpoint: SwingDiscoveryCheckpoint
    coverage: SwingDiscoveryCoverage
    top_stock_ids: tuple[str, ...]
    ranked_prefilter: tuple[SwingPrefilterRow, ...]
    detail_batches: tuple[SwingScreenResult, ...] = ()
    prefilter_empty_result_is_valid: bool
    # Top-N research is a subset even when every cheap input was considered.
    empty_result_is_valid: Literal[False] = False
    limitations: tuple[str, ...]
    cache_policy: Literal["cache_only_no_refresh_no_build"] = "cache_only_no_refresh_no_build"


def _sessions(request: SwingDiscoveryRequest) -> tuple[tuple[date, ...], bool]:
    days = []
    cursor = request.as_of_trade_date
    known = True
    for _ in range(120):
        known = known and has_taiwan_calendar_year(cursor.year)
        if is_taiwan_trading_day(cursor):
            days.append(cursor)
        if len(days) == request.horizon_sessions:
            return tuple(reversed(days)), known
        cursor -= timedelta(days=1)
    raise ValueError("No bounded completed-session calendar window is available")


def _prefilter_row(request, stock, sessions, bars, snapshot, generation, params, external, rejections, calendar_known):
    reasons = []
    dates = tuple(bar.start_at.astimezone(TAIWAN_TZ).date() for bar in bars)
    by_date = {day: bar for day, bar in zip(dates, bars)}
    last = by_date.get(request.as_of_trade_date)
    if not bars:
        reasons.append(SwingReason.DAILY_NOT_COMPUTED)
    if dates != sessions:
        reasons.append(SwingReason.DAILY_HISTORY_GAP)
    if not calendar_known:
        reasons.append(SwingReason.CALENDAR_COVERAGE_UNKNOWN)
    if any(bar.finalization not in {BarFinalization.FINAL, BarFinalization.CORRECTED} for bar in bars):
        reasons.append(SwingReason.DAILY_NOT_COMPLETED)
    market = stock.market.upper()
    if any(bar.instrument.symbol != stock.stock_id or bar.instrument.venue != market
           or bar.interval != "1d" or bar.instrument.instrument_type.value != "stock" for bar in bars):
        reasons.append(SwingReason.SOURCE_IDENTITY_MISMATCH)
    receipts = [_daily_receipt(bar.lineage)[0] for bar in bars]
    time_unknown = not bars or any(bar.lineage.event_at is None for bar in bars) or any(stamp is None for stamp in receipts)
    after = any(stamp and stamp > request.requested_at for bar in bars for stamp in
                (bar.lineage.event_at, bar.lineage.received_at, bar.lineage.fetched_at)) or any(day > request.as_of_trade_date for day in dates)
    if time_unknown:
        reasons.append(SwingReason.SOURCE_TIME_UNKNOWN)
    if after:
        reasons.append(SwingReason.SOURCE_AFTER_CUTOFF)
    daily_usable = not reasons
    close = float(last.close_price) if last else None
    turnover = _number(last.turnover_value) if last else None
    excluded = {}
    if close is not None and request.direction in {"short", "both"} and close >= request.short_price_cap:
        excluded["short"] = (SwingReason.SHORT_PRICE_CAP,)
    directions = tuple(side for side in ("long", "short") if request.direction in {side, "both"} and side not in excluded)
    low_liquidity = False
    if last:
        if turnover is None or last.turnover_currency != "TWD" or last.volume is None:
            reasons.append(SwingReason.LIQUIDITY_UNKNOWN)
            daily_usable = False
        elif turnover < request.minimum_turnover_twd:
            reasons.append(SwingReason.LIQUIDITY_BELOW_MINIMUM)
            low_liquidity = True
    # Cheap discovery does not run a per-stock institutional query. The existing
    # detailed owner reads it only for the selected Top-N, preserving unknown
    # here rather than inventing neutral/zero flow or a second batch owner.
    institutional = SwingInstitutionalEvidence()
    reasons.append(SwingReason.INSTITUTIONAL_UNKNOWN)
    corporate_quality = "unknown"
    pm_status = "not_computed"
    if snapshot is None:
        reasons.append(SwingReason.SNAPSHOT_NOT_COMPUTED)
    else:
        pm_status = snapshot.status
        try:
            payload = _mapping(json.loads(snapshot.payload_json or "{}"))
        except (ValueError, TypeError):
            payload = {}
        published = snapshot.published_at
        if published is not None and published.tzinfo is None:
            from datetime import timezone
            published = published.replace(tzinfo=timezone.utc)
        if published is None:
            reasons.append(SwingReason.SOURCE_TIME_UNKNOWN)
        elif published > request.requested_at:
            reasons.append(SwingReason.SOURCE_AFTER_CUTOFF)
        matches = snapshot_matches(snapshot, input_revision=generation, parameter_revision=params.revision,
                                   corporate_revision=external, basis_date=request.as_of_trade_date)
        if not matches:
            reasons.append(SwingReason.SNAPSHOT_REVISION_STALE)
        identity_matches = (payload.get("version") == "tw.stock.price_map.v4" and payload.get("stock_id") == stock.stock_id
            and payload.get("structure_timeframe") == "daily"
            and str(_mapping(payload.get("reference")).get("trade_date"))[:10] == request.as_of_trade_date.isoformat()
            and _number(_mapping(payload.get("reference")).get("price")) == close
            and _mapping(payload.get("parameter_contract")).get("parameter_revision") == params.revision)
        if snapshot.status not in {"ready", "empty"} or payload.get("structure_input_usable") is not True or not identity_matches:
            reasons.append(SwingReason.SNAPSHOT_NOT_USABLE)
        corporate = _mapping(payload.get("corporate_action")) if published and published <= request.requested_at and matches and identity_matches else {}
        if corporate.get("coverage_status") != "complete":
            reasons.append(SwingReason.CORPORATE_ACTION_UNKNOWN)
        elif corporate.get("affected_dates") and corporate.get("adjustment_applied") is not True:
            corporate_quality = "affected"
            reasons.append(SwingReason.CORPORATE_ACTION_AFFECTED)
        else:
            corporate_quality = "complete"
    first = by_date.get(sessions[0])
    momentum = (close / float(first.close_price) - 1) * 100 if last and first else None
    # Known future/noncompleted/wrong-identity evidence cannot rank even as
    # discovery. Missing middle sessions stay limited, never filled or zeroed.
    if after or corporate_quality == "affected" or SwingReason.DAILY_NOT_COMPLETED in reasons or SwingReason.SOURCE_IDENTITY_MISMATCH in reasons:
        momentum = None
    blocking_reasons = set(reasons) - {SwingReason.INSTITUTIONAL_UNKNOWN}
    status = "unknown" if last is None else "excluded" if low_liquidity or not directions else "limited" if blocking_reasons else "eligible"
    return SwingPrefilterRow(stock_id=stock.stock_id, market=market, status=status,
        observed=bool(bars), daily_usable=daily_usable, reference_close=close,
        window_return_pct=round(momentum, 6) if momentum is not None else None,
        turnover_twd=turnover, allowed_directions=directions, excluded_directions=excluded,
        institutional=institutional, corporate_quality=corporate_quality, price_map_status=pm_status,
        source_event_at=max((bar.lineage.event_at for bar in bars if bar.lineage.event_at), default=None),
        source_available_at=max((stamp for stamp in receipts if stamp), default=None),
        receipt_cutoff_verified=not time_unknown and not after,
        evidence_revision=_digest([bar.model_dump(mode="json") for bar in bars]),
        reason_codes=tuple(dict.fromkeys(reasons)), canonical_rejections=tuple(sorted(set(rejections))))


def _rank_key(row: SwingPrefilterRow):
    score = max((row.window_return_pct if side == "long" else -row.window_return_pct) for side in row.allowed_directions)
    return (not row.daily_usable, row.status != "eligible", -score, row.turnover_twd is None, -(row.turnover_twd or 0), row.stock_id)


@exchange_calendar_read_scope()
def build_tw_swing_discovery_snapshot(db: Session, *, request: SwingDiscoveryRequest,
    checkpoint: SwingDiscoveryCheckpoint | None = None, with_detail: bool = True) -> SwingDiscoveryResult:
    """Advance a bounded prefix, then rank *all* considered inputs before Top-N.

    Resume with the returned checkpoint and the same as_of/requested_at/policy.
    Batch budgets may change. Universe/config/generation drift invalidates the
    cursor rather than mixing two rankings. Old DBs without generation tracking
    are explicitly unpinned; frozen row receipts remain in the checkpoint.
    """
    stocks = list_taiwan_stock_universe(db, markets=request.markets,
        **({"stock_ids": request.stock_ids} if request.stock_ids is not None else {}))
    if len(stocks) > 5000:
        raise ValueError("Swing discovery universe exceeds 5000")
    ids = tuple(stock.stock_id for stock in stocks)
    params = get_technical_analysis_parameters()
    external = read_price_map_external_revision()
    storage = snapshot_storage_available(db)
    generations = read_input_revisions(db, list(ids)) if storage and ids else {}
    feature_revision = _digest({"feature": PREFILTER_VERSION, "prefilter_policy": PREFILTER_POLICY,
                                "policy": request.detail_request(("scope",)).ranking_config_hash,
                                "technical": params.revision, "external": external})
    request_revision = _digest(request.model_dump(mode="json", exclude={"batch_size", "max_batches", "detail_batch_size", "max_detail_batches"}))
    source_revision = _digest({"feature": feature_revision, "universe": [(s.stock_id, s.market) for s in stocks],
                               "generations": generations if storage else None})
    if checkpoint is not None and (checkpoint.request_revision != request_revision
            or checkpoint.source_revision != source_revision or checkpoint.universe_stock_ids != ids):
        raise ValueError("DISCOVERY_CHECKPOINT_BASIS_CHANGED: restart with the new source/request basis")
    sessions, calendar_known = _sessions(request)
    rows = list(checkpoint.rows) if checkpoint else []
    repository = TaiwanOfficialDailyBarRepository(db, available_at=request.requested_at)
    end = min(len(ids), len(rows) + request.batch_size * request.max_batches)
    for start in range(len(rows), end, request.batch_size):
        batch = stocks[start:min(end, start + request.batch_size)]
        batch_ids = tuple(stock.stock_id for stock in batch)
        history = repository.load_market_universe_history(trade_dates=sessions, include_etf=False,
            symbols=batch_ids, max_rows=max(128, len(batch_ids) * 8))
        by_stock = defaultdict(list)
        rejected = defaultdict(list)
        for day in sessions:
            for bar in history[day].bars:
                by_stock[bar.instrument.symbol].append(bar)
            for symbol, reason in history[day].rejection_reasons:
                rejected[symbol].append(reason)
        snapshots = read_price_map_snapshots(db, list(batch_ids), "daily") if storage else {}
        for stock in batch:
            rows.append(_prefilter_row(request, stock, sessions, tuple(by_stock[stock.stock_id]),
                snapshots.get(stock.stock_id), generations.get(stock.stock_id, 0), params, external,
                rejected[stock.stock_id], calendar_known))
    counts = Counter(row.status for row in rows)
    all_considered = len(rows) == len(ids)
    daily_complete = bool(ids) and all_considered and all(row.daily_usable for row in rows)
    prefilter_complete = bool(ids) and all_considered and not counts["limited"] and not counts["unknown"] and all(
        not (set(row.reason_codes) - {SwingReason.LIQUIDITY_BELOW_MINIMUM, SwingReason.INSTITUTIONAL_UNKNOWN}) for row in rows)
    # Scope/scan progress and evidence quality are orthogonal. Deferred flow or
    # missing canonical history cannot turn a completed whole-universe scan
    # into a claim that only a sample of the universe was considered.
    full_market_scope = request.stock_ids is None and set(request.markets) == {"TWSE", "TPEX"}
    is_full_market = bool(ids) and full_market_scope and all_considered
    reasons = Counter(reason.value for row in rows for reason in set((*row.reason_codes,
        *(r for rs in row.excluded_directions.values() for r in rs))) if reason != SwingReason.INSTITUTIONAL_UNKNOWN)
    rejection_counts = Counter(reason for row in rows for reason in row.canonical_rejections)
    ranked = sorted((row for row in rows if row.status in {"eligible", "limited"}
                     and row.window_return_pct is not None and row.allowed_directions), key=_rank_key)
    top = tuple(row.stock_id for row in ranked[:request.top_n])
    details = list(checkpoint.detail_batches) if checkpoint else []
    detailed_ids = tuple(symbol for result in details for symbol in result.request.stock_ids)
    if (detailed_ids != top[:len(detailed_ids)] or (details and not all_considered)
            or any(result.request != request.detail_request(result.request.stock_ids) for result in details)):
        raise ValueError("DISCOVERY_CHECKPOINT_DETAIL_MISMATCH: detailed stocks must be the final Top-N prefix")
    if all_considered and with_detail:
        detail_end = min(len(top), len(detailed_ids) + request.detail_batch_size * request.max_detail_batches)
        for start in range(len(detailed_ids), detail_end, request.detail_batch_size):
            selected = top[start:min(detail_end, start + request.detail_batch_size)]
            details.append(build_tw_swing_screening_snapshot(db, request=request.detail_request(selected)))
    detail_considered = sum(len(result.request.stock_ids) for result in details)
    research_complete = detail_considered == len(top) and all(result.status == "ready" for result in details)
    detail_sample_only = detail_considered < len(ids)
    complete = prefilter_complete and research_complete and (not ranked or not detail_sample_only)
    state = SwingDiscoveryCheckpoint(request_revision=request_revision, source_revision=source_revision,
        universe_stock_ids=ids, rows=tuple(rows), detail_batches=tuple(details))
    coverage = SwingDiscoveryCoverage(scope="selected_ordinary_stocks" if request.stock_ids is not None else "active_ordinary_stocks",
        universe_count=len(ids), considered=len(rows), pending=len(ids) - len(rows),
        observed=sum(row.observed for row in rows), daily_usable=sum(row.daily_usable for row in rows),
        eligible=counts["eligible"], incomplete=counts["limited"], unknown=counts["unknown"], excluded=counts["excluded"],
        corporate_unknown=sum(row.corporate_quality == "unknown" for row in rows),
        institutional_unknown=sum(row.institutional.status != "qualified" for row in rows),
        all_considered=all_considered, daily_coverage_complete=daily_complete, sample_only=not is_full_market,
        is_full_market=is_full_market, full_market_scope=full_market_scope, quality_complete=complete,
        quality_status="complete" if complete else "partial" if any(row.observed for row in rows) else "unknown",
        excluded_reason_counts=dict(sorted(reasons.items())),
        canonical_rejection_counts=dict(sorted(rejection_counts.items())), detail_requested=len(top) if all_considered else 0,
        detail_considered=detail_considered, detail_pending=len(top) - detail_considered if all_considered else 0,
        detail_qualified=sum(result.coverage.qualified for result in details),
        detail_incomplete=sum(result.coverage.incomplete + result.coverage.not_computed for result in details),
        detail_candidate_count=sum(result.coverage.candidate_count for result in details),
        prefilter_selected=len(top), prefilter_quality_complete=prefilter_complete,
        detail_sample_only=detail_sample_only,
        detail_research_qualified_candidates=sum(result.coverage.research_qualified_candidate_count for result in details),
        detail_limited_candidates=sum(result.coverage.limited_candidate_count for result in details),
        deferred_reason_counts={SwingReason.INSTITUTIONAL_UNKNOWN.value: sum(
            row.institutional.status != "qualified" for row in rows)} if rows else {})
    limitations = ["Cheap completed-daily ranking selects Top-N stocks for research; it is not an exhaustive ranking of all trade setups.",
        "Universe membership is the current active ordinary-stock master pinned for continuation, not a reconstructed historical listing universe.",
        "Momentum compares canonical closes without applying corporate adjustments; unknown corporate coverage stays limited and known affected windows do not rank.",
        "Institutional flow is unknown/deferred in cheap discovery; only Top-N detailed research queries the existing institutional owner.",
        "Corporate/technical/price-map quality, current price, borrow, regulation and funding remain independent gates; no live trigger is inferred."]
    if not storage:
        limitations.append("Canonical generation tracking is unavailable; fixed receipt cutoff and frozen checkpoint rows do not establish immutable PIT replay.")
    if not calendar_known:
        limitations.append("Trading-calendar coverage is unknown; weekday fallback is not verified session continuity.")
    return SwingDiscoveryResult(status="in_progress" if not all_considered or (with_detail and detail_considered < len(top)) else "empty" if not ids else "ready" if prefilter_complete and research_complete else "limited",
        request=request, feature_revision=feature_revision, snapshot_id=_digest({"source": source_revision, "state": state.model_dump(mode="json")}),
        expected_sessions=sessions, calendar_coverage_known=calendar_known, canonical_generations_pinned=storage,
        checkpoint=state, coverage=coverage, top_stock_ids=top, ranked_prefilter=tuple(ranked[:request.top_n]), detail_batches=tuple(details),
        prefilter_empty_result_is_valid=prefilter_complete and not ranked, limitations=tuple(limitations))
