"""Typed read-side wiring to F01/F03/F04; market owners retain all calculations."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import Field, StrictInt
from sqlalchemy.orm import Session

from app.market.tw_swing_screening import SwingScreenRequest, build_tw_swing_screening_snapshot
from app.market.tw_swing_screening import SwingScreenResult
from app.market.tw_swing_prefilter import (
    SwingDiscoveryCoverage, SwingDiscoveryRequest,
    build_tw_swing_discovery_snapshot,
)
from app.market.tw_trade_eligibility import (
    EligibilityRequest, TradeEligibilityResult, evaluate_tw_trade_eligibility, read_tw_trade_eligibility_evidence,
)
from app.market.tw_trade_setup import TradeCosts, TradeSetup, TradeSetupEvaluation, evaluate_tw_trade_setup
from app.market_data.contracts import CanonicalModel


Price = Annotated[Decimal, Field(gt=0, allow_inf_nan=False)]
Cost = Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]


class SetupInput(CanonicalModel):
    symbol: str = Field(min_length=1, max_length=20)
    as_of_trade_date: date
    direction: Literal["long", "short"]
    entry: Price
    stop: Price
    targets: tuple[Price, ...] = Field(min_length=1, max_length=2)
    quantity: int = Field(gt=0, strict=True)
    target_quantities: tuple[StrictInt, ...] | None = Field(default=None, min_length=1, max_length=2)
    price_rounding: Literal["reject", "nearest", "up", "down"] = "reject"


class CostInput(CanonicalModel):
    commission_rate: Cost | None = None
    minimum_commission: Cost | None = None
    sell_tax_rate: Cost | None = None
    entry_slippage_bps: Cost | None = None
    exit_slippage_bps: Cost | None = None
    short_borrow_cost: Cost | None = None
    commission_quantum: Cost | None = None
    tax_quantum: Cost | None = None
    charge_rounding: Literal["nearest", "up", "down"] = "nearest"


class TradeSetupParameters(CanonicalModel):
    setup: SetupInput
    costs: CostInput
    horizon_sessions: Literal[10, 15]


class SwingDiscoveryParameters(SwingDiscoveryRequest):
    """One bounded public read; the native checkpoint remains internal."""
    max_batches: int = Field(default=20, ge=1, le=20, strict=True)
    max_detail_batches: int = Field(default=10, ge=1, le=10, strict=True)
    with_detail: bool = Field(default=True, strict=True)
    limit: int = Field(default=20, ge=1, le=100, strict=True)


class SwingDiscoveryRow(CanonicalModel):
    stock_id: str
    market: str
    status: str
    daily_usable: bool
    reference_close: float | None
    window_return_pct: float | None
    turnover_twd: float | None
    allowed_directions: tuple[str, ...]
    corporate_quality: str
    institutional_policy: str
    source_event_at: str | None
    source_available_at: str | None
    receipt_cutoff_verified: bool
    evidence_revision: str
    reason_codes: tuple[str, ...]


class SwingDiscoveryCandidate(CanonicalModel):
    stock_id: str
    market: str
    direction: str
    mode: str
    setup_type: str
    stage: str
    evidence_quality: str
    reference_close: float
    reason_codes: tuple[str, ...]
    counter_evidence: tuple[str, ...]


class SwingDiscoveryRead(CanonicalModel):
    version: Literal["tw.swing.prefilter.v1"] = "tw.swing.prefilter.v1"
    status: Literal["in_progress", "ready", "limited", "empty"]
    request: SwingDiscoveryParameters
    as_of: date
    feature_revision: str
    snapshot_id: str
    calendar_coverage_known: bool
    canonical_generations_pinned: bool
    coverage: SwingDiscoveryCoverage
    sample_only: bool
    research_sample_only: Literal[True] = True
    top_stock_ids: tuple[str, ...] = Field(max_length=100)
    ranked_prefilter: tuple[SwingDiscoveryRow, ...] = Field(max_length=100)
    candidates: tuple[SwingDiscoveryCandidate, ...] = Field(max_length=100)
    available_count: int
    returned_count: int
    response_truncated: bool
    prefilter_empty_result_is_valid: bool
    empty_result_is_valid: Literal[False] = False
    freshness_status: Literal["ready", "partial"]
    facts_usable: bool
    decision_usable: Literal[False] = False
    trigger_ready: Literal[False] = False
    execution_ready: Literal[False] = False
    limitations: tuple[str, ...]
    missing: tuple[str, ...]
    cache_policy: Literal["cache_only_no_refresh_no_build"] = "cache_only_no_refresh_no_build"


def read_swing_discovery(db: Session, parameters: SwingDiscoveryParameters) -> SwingDiscoveryRead:
    request = SwingDiscoveryRequest.model_validate(parameters.model_dump(exclude={"with_detail", "limit"}))
    result = build_tw_swing_discovery_snapshot(db, request=request, with_detail=parameters.with_detail)
    # No checkpoint, universe rows, OHLCV or full detail batches cross this boundary.
    ranked = tuple(SwingDiscoveryRow.model_validate(row.model_dump(mode="json", include=set(SwingDiscoveryRow.model_fields)))
                   for row in result.ranked_prefilter[:parameters.limit])
    candidates = [candidate for batch in result.detail_batches for candidate in batch.candidates]
    summaries = tuple(SwingDiscoveryCandidate.model_validate(candidate.model_dump(mode="json", include=set(SwingDiscoveryCandidate.model_fields)))
                      for candidate in candidates[:parameters.limit])
    reasons = tuple(result.coverage.excluded_reason_counts) if not result.coverage.quality_complete else ()
    if result.coverage.pending or result.coverage.detail_pending:
        reasons += ("DISCOVERY_BOUNDED_READ_INCOMPLETE",)
    return SwingDiscoveryRead(status=result.status, request=parameters, as_of=request.as_of_trade_date,
        feature_revision=result.feature_revision, snapshot_id=result.snapshot_id,
        calendar_coverage_known=result.calendar_coverage_known, canonical_generations_pinned=result.canonical_generations_pinned,
        coverage=result.coverage, sample_only=result.coverage.sample_only,
        top_stock_ids=result.top_stock_ids[:parameters.limit], ranked_prefilter=ranked, candidates=summaries,
        available_count=len(result.ranked_prefilter), returned_count=len(ranked),
        response_truncated=len(result.ranked_prefilter) > len(ranked) or len(candidates) > len(summaries),
        prefilter_empty_result_is_valid=result.prefilter_empty_result_is_valid,
        freshness_status="ready" if result.status == "ready" else "partial",
        facts_usable=any(row.daily_usable for row in ranked) or bool(result.coverage.detail_qualified),
        limitations=(*result.limitations, "Public discovery is one bounded read; the native checkpoint is not exposed or persisted. Pending work is not a completed scan."),
        missing=reasons)


_QUALITY_FIELDS = ("as_of", "freshness_status", "facts_usable", "decision_usable", "limitations", "missing")
SWING_FIELDS = tuple(dict.fromkeys((*SwingScreenResult.model_fields, *_QUALITY_FIELDS, "sample_only")))
SETUP_FIELDS = tuple(dict.fromkeys((*TradeSetupEvaluation.__dataclass_fields__, *_QUALITY_FIELDS, "horizon_sessions", "trigger_ready")))
ELIGIBILITY_FIELDS = tuple(dict.fromkeys((*TradeEligibilityResult.model_fields, *_QUALITY_FIELDS, "execution_ready", "trigger_ready")))
DISCOVERY_FIELDS = tuple(SwingDiscoveryRead.model_fields)


def parameter_schema(model: type[CanonicalModel]) -> dict[str, Any]:
    """Inline model refs because the catalog embeds schemas below the MCP root."""
    schema = model.model_json_schema()
    definitions = schema.pop("$defs", {})

    def inline(value: Any) -> Any:
        if isinstance(value, list):
            return [inline(item) for item in value]
        if not isinstance(value, dict):
            return value
        if "$ref" in value:
            return inline({**definitions[value["$ref"].rsplit("/", 1)[-1]],
                           **{key: item for key, item in value.items() if key != "$ref"}})
        return {key: inline(item) for key, item in value.items()}

    schema = inline(schema)
    if model is EligibilityRequest:
        for key in ("reference_price", "current_quote"):
            schema["properties"].pop(key, None)
    return schema


def validate_parameters(capability: str, value: dict[str, Any]) -> dict[str, Any]:
    if capability == "screening.swing_discovery":
        request = SwingDiscoveryParameters.model_validate(value)
    elif capability == "screening.swing":
        request = SwingScreenRequest.model_validate(value)
    elif capability == "research.trade_setup":
        request = TradeSetupParameters.model_validate(value)
    elif capability == "research.trade_eligibility":
        # Public callers provide scenario inputs, never broker/quote evidence.
        request = EligibilityRequest.model_validate(value)
        if request.reference_price is not None or request.current_quote is not None:
            raise ValueError("Eligibility quote evidence must come from its backend owner.")
    else:
        raise ValueError(f"Unsupported Taiwan research capability: {capability}")
    return request.model_dump(mode="json", exclude_none=True)


def read_research_capability(db: Session, capability: str, parameters: dict[str, Any]) -> dict[str, Any]:
    if capability == "screening.swing_discovery":
        return read_swing_discovery(db, SwingDiscoveryParameters.model_validate(parameters)).model_dump(mode="json")
    if capability == "screening.swing":
        result = build_tw_swing_screening_snapshot(db, request=SwingScreenRequest.model_validate(parameters))
        payload = result.model_dump(mode="json")
        reasons = sorted({reason.value for row in result.assessments for reason in row.reason_codes})
        payload.update(
            as_of=result.request.as_of_trade_date.isoformat(), sample_only=True,
            freshness_status="ready" if result.coverage.complete else "partial",
            facts_usable=bool(result.coverage.qualified), decision_usable=False,
            limitations=["SELECTED_UNIVERSE_SAMPLE_ONLY", *reasons],
            missing=[] if result.coverage.complete else reasons or ["SWING_COVERAGE_INCOMPLETE"],
        )
        return payload
    if capability == "research.trade_setup":
        request = TradeSetupParameters.model_validate(parameters)
        result = evaluate_tw_trade_setup(TradeSetup(**request.setup.model_dump()), TradeCosts(**request.costs.model_dump()))
        # JSON conversion preserves Decimal precision; unknown costs remain null.
        from fastapi.encoders import jsonable_encoder

        payload = jsonable_encoder(asdict(result), custom_encoder={Decimal: str})
        payload.update(
            horizon_sessions=request.horizon_sessions, as_of=request.setup.as_of_trade_date.isoformat(),
            freshness_status="partial", facts_usable=True, decision_usable=False,
            trigger_ready=False, missing=list(result.missing_costs),
        )
        return payload
    if capability != "research.trade_eligibility":
        raise ValueError(f"Unsupported Taiwan research capability: {capability}")
    request = EligibilityRequest.model_validate(parameters)
    result = evaluate_tw_trade_eligibility(request, read_tw_trade_eligibility_evidence(request, db=db))
    payload = result.model_dump(mode="json")
    reasons = [item.code for item in result.ineligibility_reason]
    payload.update(as_of=request.as_of_trade_date.isoformat(), freshness_status="partial",
                   facts_usable=True, decision_usable=False, execution_ready=False,
                   trigger_ready=False, limitations=reasons, missing=reasons)
    return payload


def project_research_payload(capability: str, payload: dict[str, Any], *, fields: tuple[str, ...], limit: int) -> dict[str, Any]:
    """Limit ranked candidates only; keep request, coverage and reasons intact."""
    value = deepcopy(payload)
    if capability == "screening.swing":
        candidates = value.get("candidates") or []
        value["candidates"] = candidates[:limit]
        value["coverage"]["returned_count"] = len(value["candidates"])
        value["response_truncated"] = bool(value["response_truncated"] or len(candidates) > limit)
    if capability == "screening.swing_discovery":
        for key in ("ranked_prefilter", "top_stock_ids", "candidates"):
            rows = value[key]
            value[key] = rows[:limit]
            value["response_truncated"] = value["response_truncated"] or len(rows) > len(value[key])
        value["returned_count"] = len(value["ranked_prefilter"])
    # Quality/identity cannot disappear when the caller asks for narrow fields.
    protected = {"version", "schema_version", "status", "as_of", "request", "setup", "cost_assumptions",
                 "horizon_sessions", "coverage", "sample_only", "freshness_status", "facts_usable",
                 "decision_usable", "execution_ready", "execution_eligibility", "trigger_ready",
                 "limitations", "missing", "missing_costs", "empty_result_is_valid", "response_truncated",
                 "cache_policy", "ineligibility_reason", "borrow_available", "funding_sufficient",
                 "broker_execution_eligible", "regulation_eligible", "research_eligible", "current_price_eligible",
                 "event_coverage_complete", "research_sample_only", "feature_revision", "snapshot_id",
                 "calendar_coverage_known", "canonical_generations_pinned", "available_count", "returned_count",
                 "prefilter_empty_result_is_valid"}
    return {key: item for key, item in value.items() if key in fields or key in protected}
