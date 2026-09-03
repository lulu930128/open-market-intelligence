"""Single Backend owner for Taiwan technical series."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from enum import Enum
from hashlib import sha256
import json
from typing import Any, Literal

from pydantic import Field, model_validator

from app.market.technical_evidence import (
    ADVANCED_ALGORITHM_VERSION,
    INDICATOR_ALGORITHM_VERSION,
    build_anchored_vwap,
    build_breakout_evidence,
    build_divergence_evidence,
    build_fibonacci_evidence,
    build_relative_strength,
    build_swing_evidence,
    build_volume_profile,
    calculate_canonical_indicator_points,
    indicator_method_catalog,
)
from app.market.technical_parameters import (
    TechnicalAnalysisParameters,
    build_taiwan_technical_parameter_contract,
    get_technical_analysis_parameters,
)
from app.market.tw_bar_contracts import TaiwanBarSeriesRead
from app.market_data.contracts import (
    AuthorityClass,
    BarFinalization,
    CanonicalModel,
    InstrumentKey,
)


class TaiwanTechnicalStatus(str, Enum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    WARMING_UP = "warming_up"
    MISSING = "missing"
    UNAVAILABLE = "unavailable"


class BarSeriesRevisionConflict(ValueError):
    def __init__(self, *, expected: str, current: str) -> None:
        super().__init__("BAR_SERIES_REVISION_CONFLICT")
        self.expected = expected
        self.current = current


class BarSnapshotRevisionConflict(ValueError):
    def __init__(self, *, expected: str, current: str) -> None:
        super().__init__("BAR_SNAPSHOT_REVISION_CONFLICT")
        self.expected = expected
        self.current = current


class TaiwanTechnicalCurrentPartial(CanonicalModel):
    contract_version: str = "tw.technical.current_partial.v1"
    state: Literal["current_partial"] = "current_partial"
    bar_time: datetime
    point: dict[str, Any]
    decision_usable: Literal[False] = False
    price_based_observation_usable: bool
    volume_based_observation_usable: Literal[False] = False
    indicator_applicability: dict[str, str]
    observation_revision: str = Field(min_length=64, max_length=64)
    limitations: tuple[str, ...] = ()


class TaiwanTechnicalSeriesRead(CanonicalModel):
    contract_version: str = "tw.technical.series.v2"
    instrument: InstrumentKey
    interval: str
    bar_series_fingerprint: str = Field(min_length=64, max_length=64)
    bar_lineage_digest: str = Field(min_length=64, max_length=64)
    bar_state_digest: str = Field(min_length=64, max_length=64)
    bar_series_revision: str = Field(min_length=64, max_length=64)
    bar_snapshot_revision: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
    )
    calculation_bar_count: int = Field(ge=0, le=5000)
    decision_bar_count: int = Field(ge=0, le=5000)
    response_point_count: int = Field(ge=0, le=5000)
    algorithm_version: str
    parameter_contract: dict[str, Any]
    status: TaiwanTechnicalStatus
    warmup: dict[str, dict[str, Any]] = Field(default_factory=dict)
    points: tuple[dict[str, Any], ...] = ()
    current_partial: TaiwanTechnicalCurrentPartial | None = None
    structures: dict[str, Any] = Field(default_factory=dict)
    signals: dict[str, Any] = Field(default_factory=dict)
    relative: dict[str, Any] = Field(default_factory=dict)
    technical_revision: str = Field(min_length=64, max_length=64)
    limitations: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _require_points_for_available(self) -> TaiwanTechnicalSeriesRead:
        if self.status is TaiwanTechnicalStatus.AVAILABLE and not self.points:
            raise ValueError("available technical series requires points")
        if self.response_point_count != len(self.points):
            raise ValueError("response_point_count must match points")
        if self.response_point_count > self.calculation_bar_count:
            raise ValueError("technical response cannot exceed calculation window")
        if self.decision_bar_count > self.calculation_bar_count:
            raise ValueError("technical decision window cannot exceed calculation window")
        return self


def _technical_revision(
    *,
    bar_revision: str,
    parameter_contract: dict[str, Any],
) -> str:
    payload = json.dumps(
        {
            "contract_version": "tw.technical.revision.v1",
            "bar_series_revision": bar_revision,
            "algorithm_version": INDICATOR_ALGORITHM_VERSION,
            "parameter_contract": parameter_contract,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def _bar_subset_revision(
    series: TaiwanBarSeriesRead,
    *,
    stop: int,
) -> str:
    payload = json.dumps(
        {
            "contract_version": "tw.technical.bar_subset_revision.v1",
            "instrument": series.instrument.model_dump(mode="json"),
            "interval": series.requested_interval,
            "bars": [
                bar.model_dump(mode="json") for bar in series.bars[:stop]
            ],
            "bar_states": [
                state.model_dump(mode="json") for state in series.bar_states[:stop]
            ],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def _terminal_current_partial_index(series: TaiwanBarSeriesRead) -> int | None:
    ineligible = [
        index
        for index, state in enumerate(series.bar_states)
        if not state.technical_eligible
    ]
    if not ineligible:
        return None
    if ineligible != [len(series.bar_states) - 1] or series.requested_interval != "1d":
        return -1
    state = series.bar_states[-1]
    bar = series.bars[-1]
    if not (
        bar.finalization is BarFinalization.PROVISIONAL
        and state.finalization is BarFinalization.PROVISIONAL
        and state.authority is AuthorityClass.DERIVED
        and not state.official
        and not state.persisted
        and state.release_status.value == "pending_release"
        and state.source_interval == "1m"
    ):
        return -1
    return len(series.bars) - 1


_VOLUME_BASED_INDICATORS = frozenset(
    {"volume_ma", "pvo", "mfi", "vwap", "obv"}
)


def _current_partial_observation(
    *,
    point: dict[str, Any],
    bar_time: Any,
    observation_revision: str,
    parameters: TechnicalAnalysisParameters,
) -> TaiwanTechnicalCurrentPartial:
    sanitized = dict(point)
    for key in _VOLUME_BASED_INDICATORS:
        sanitized[key] = None
    for key in ("breakout", "divergence"):
        if key in sanitized:
            sanitized[key] = None
    sanitized.update(
        {
            "decision_usable": False,
            "price_based_observation_usable": True,
            "volume_based_observation_usable": False,
            "technical_state": "current_partial",
        }
    )
    applicability = {
        name: (
            "not_applicable_missing_final_volume"
            if name in _VOLUME_BASED_INDICATORS
            else "provisional_observation"
        )
        for name in indicator_method_catalog(parameters).keys()
    }
    return TaiwanTechnicalCurrentPartial(
        bar_time=bar_time,
        point=sanitized,
        price_based_observation_usable=True,
        indicator_applicability=applicability,
        observation_revision=observation_revision,
        limitations=(
            "TW_CURRENT_PARTIAL_NOT_DECISION_USABLE",
            "TW_CURRENT_PARTIAL_VOLUME_INDICATORS_NOT_APPLICABLE",
        ),
    )


def _bar_points(series: TaiwanBarSeriesRead) -> list[dict[str, Any]]:
    return [
        {
            "time": bar.start_at,
            "open": float(bar.open_price),
            "high": float(bar.high_price),
            "low": float(bar.low_price),
            "close": float(bar.close_price),
            "volume": (
                float(bar.volume.value) if bar.volume is not None else None
            ),
            "trade_value": (
                float(bar.turnover_value)
                if bar.turnover_value is not None
                else None
            ),
            "transaction_count": bar.trade_count,
            "finalization": bar.finalization.value,
        }
        for bar in series.bars
    ]


def _warmup(
    parameters: TechnicalAnalysisParameters,
    *,
    available_bars: int,
    interval: str,
) -> dict[str, dict[str, Any]]:
    output = {
        key: {
            "required_bars": int(item.get("warmup_bars") or 1),
            "available_bars": available_bars,
            "status": (
                "ready"
                if available_bars >= int(item.get("warmup_bars") or 1)
                else "warming_up"
            ),
        }
        for key, item in indicator_method_catalog(parameters).items()
    }
    if interval in {"1d", "1w", "1mo"} and "vwap" in output:
        output["vwap"] = {
            **output["vwap"],
            "status": "unavailable",
            "reason": "session_vwap_not_applicable_to_completed_period_bars",
        }
    return output


def build_taiwan_technical_capability_contract() -> dict[str, Any]:
    parameters = get_technical_analysis_parameters()
    available = (
        "ma",
        "volume_ma",
        "ema",
        "macd",
        "rsi",
        "kd",
        "pvo",
        "atr",
        "adx",
        "dmi",
        "roc",
        "mfi",
        "vwap",
        "obv",
        "donchian",
        "bollinger",
        "support_resistance",
        "change",
    )
    available_advanced = (
        "swings",
        "fibonacci",
        "breakout",
        "volume_profile",
        "anchored_vwap",
        "divergence",
        "relative_strength",
    )
    pending = (
        "wma",
        "hma",
        "vwma",
        "psar",
        "supertrend",
        "ichimoku",
        "keltner",
        "cmf",
        "ad",
        "pvt",
        "pivot_points",
        "gap",
        "candlestick_patterns",
        "beta",
        "correlation",
    )
    return {
        "contract_version": "tw.technical.capabilities.v1",
        "algorithm_version": INDICATOR_ALGORITHM_VERSION,
        "calculation_owner": "TaiwanTechnicalService",
        "parameter_contract": build_taiwan_technical_parameter_contract(
            parameters=parameters
        ),
        "indicators": {
            **{name: {"status": "available"} for name in available},
            "vwap": {
                "status": "available",
                "applicable_intervals": ["1m", "5m", "15m", "30m", "1h", "4h"],
                "non_applicable_intervals": ["1d", "1w", "1mo"],
            },
            **{name: {"status": "available"} for name in available_advanced},
            **{name: {"status": "pending"} for name in pending},
        },
        "frontend_fallback_allowed": False,
    }


class TaiwanTechnicalService:
    """Calculate from one exact resolved Bar object; never read DB/provider."""

    def calculate(
        self,
        bars: TaiwanBarSeriesRead,
        *,
        parameters: TechnicalAnalysisParameters | None = None,
        expected_series_revision: str | None = None,
        expected_snapshot_revision: str | None = None,
        response_limit: int | None = None,
    ) -> TaiwanTechnicalSeriesRead:
        if expected_series_revision is not None and expected_snapshot_revision is not None:
            raise ValueError(
                "expected_series_revision and expected_snapshot_revision are mutually exclusive"
            )
        if (
            expected_series_revision is not None
            and expected_series_revision != bars.identity.series_revision
        ):
            raise BarSeriesRevisionConflict(
                expected=expected_series_revision,
                current=bars.identity.series_revision,
            )
        snapshot_revision = (
            bars.current_session_coverage.snapshot_revision
            if bars.current_session_coverage is not None
            else None
        )
        if expected_snapshot_revision is not None:
            if snapshot_revision is None:
                raise ValueError(
                    "expected_snapshot_revision requires current-session coverage"
                )
            if expected_snapshot_revision != snapshot_revision:
                raise BarSnapshotRevisionConflict(
                    expected=expected_snapshot_revision,
                    current=snapshot_revision,
                )
        if response_limit is not None and response_limit < 1:
            raise ValueError("response_limit must be positive")
        resolved = parameters or get_technical_analysis_parameters()
        parameter_contract = {
            "schema_version": "tw.technical.parameters.v1",
            **asdict(resolved),
        }
        partial_index = _terminal_current_partial_index(bars)
        decision_bar_count = (
            partial_index
            if partial_index is not None and partial_index >= 0
            else len(bars.bars)
        )
        warmup = _warmup(
            resolved,
            available_bars=decision_bar_count,
            interval=bars.requested_interval,
        )
        current_partial: TaiwanTechnicalCurrentPartial | None = None
        if not bars.bars:
            status = TaiwanTechnicalStatus.MISSING
            points: tuple[dict[str, Any], ...] = ()
            limitations = ("TW_TECHNICAL_BAR_SERIES_MISSING",)
        elif partial_index == -1:
            status = TaiwanTechnicalStatus.UNAVAILABLE
            points = ()
            limitations = (
                "TW_TECHNICAL_BAR_STATE_NOT_ELIGIBLE",
                *bars.limitations,
            )
        else:
            raw_points = _bar_points(bars)
            decision_points = raw_points[:decision_bar_count]
            calculated = calculate_canonical_indicator_points(
                decision_points,
                parameters=resolved,
                interval=bars.requested_interval,
            )
            points = tuple(calculated)
            if partial_index is not None:
                observation_calculated = calculate_canonical_indicator_points(
                    raw_points,
                    parameters=resolved,
                    interval=bars.requested_interval,
                )
                if observation_calculated:
                    current_partial = _current_partial_observation(
                        point=observation_calculated[-1],
                        bar_time=bars.bars[-1].start_at,
                        observation_revision=(
                            snapshot_revision or bars.identity.series_revision
                        ),
                        parameters=resolved,
                    )
            warming = any(item["status"] == "warming_up" for item in warmup.values())
            if not points and current_partial is not None:
                status = TaiwanTechnicalStatus.PARTIAL
            elif warming:
                status = TaiwanTechnicalStatus.WARMING_UP
            elif current_partial is not None or not bars.history.requested_coverage_satisfied:
                status = TaiwanTechnicalStatus.PARTIAL
            else:
                status = TaiwanTechnicalStatus.AVAILABLE
            limitations = (
                *bars.limitations,
                *(
                    ("TW_VWAP_NOT_APPLICABLE_FOR_INTERVAL",)
                    if bars.requested_interval in {"1d", "1w", "1mo"}
                    else ()
                ),
            )
        calculation_bar_count = len(bars.bars)
        latest = points[-1] if points else {}
        structures = {
            key: latest.get(key)
            for key in ("support_resistance", "donchian", "bollinger")
            if latest.get(key) is not None
        }
        signals = {
            key: latest.get(key)
            for key in ("signals", "crossover", "breakout", "divergence", "patterns")
            if latest.get(key) is not None
        }
        response_points = (
            points[-response_limit:]
            if response_limit is not None
            else points
        )
        technical_input_revision = (
            _bar_subset_revision(bars, stop=decision_bar_count)
            if current_partial is not None
            else snapshot_revision or bars.identity.series_revision
        )
        return TaiwanTechnicalSeriesRead(
            instrument=bars.instrument,
            interval=bars.requested_interval,
            bar_series_fingerprint=bars.identity.series_fingerprint,
            bar_lineage_digest=bars.identity.lineage_digest,
            bar_state_digest=bars.identity.state_digest,
            bar_series_revision=bars.identity.series_revision,
            bar_snapshot_revision=snapshot_revision,
            calculation_bar_count=calculation_bar_count,
            decision_bar_count=decision_bar_count,
            response_point_count=len(response_points),
            algorithm_version=INDICATOR_ALGORITHM_VERSION,
            parameter_contract=parameter_contract,
            status=status,
            warmup=warmup,
            points=response_points,
            current_partial=current_partial,
            structures=structures,
            signals=signals,
            relative={},
            technical_revision=_technical_revision(
                bar_revision=technical_input_revision,
                parameter_contract=parameter_contract,
            ),
            limitations=tuple(dict.fromkeys(limitations)),
            warnings=bars.warnings,
        )

    def calculate_advanced(
        self,
        *,
        points: list[dict[str, Any]],
        canonical_points: list[dict[str, Any]],
        benchmark_points: list[dict[str, Any]],
        parameters: TechnicalAnalysisParameters,
        affected_swing_dates: tuple[str, ...] = (),
        breakout_corporate_action_contract: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Compose all Taiwan advanced technical semantics in one owner.

        The imported builders are pure research primitives.  Consumer evidence
        code supplies exact Bar-derived inputs but no longer chooses the
        algorithm sequence or constructs a parallel outward capability set.
        """

        swing_points = points[-260:]
        canonical_swing = canonical_points[-len(swing_points):]
        swings = build_swing_evidence(
            swing_points,
            affected_dates=affected_swing_dates,
        )
        fibonacci = build_fibonacci_evidence(swings)
        divergence = build_divergence_evidence(
            swings,
            canonical_swing,
            parameters=parameters,
        )
        breakout = build_breakout_evidence(
            points,
            canonical_points,
            corporate_action_contract=(
                breakout_corporate_action_contract
                or {"coverage_status": "missing", "affected_dates": []}
            ),
            parameters=parameters,
        )
        return {
            "algorithm_version": ADVANCED_ALGORITHM_VERSION,
            "swings": swings,
            "fibonacci": fibonacci,
            "divergence": divergence,
            "breakout": breakout,
            "volume_profile": build_volume_profile(points),
            "anchored_vwap": build_anchored_vwap(swing_points, swings),
            "relative_strength": build_relative_strength(
                points,
                benchmark_points,
            ),
        }


__all__ = [
    "BarSeriesRevisionConflict",
    "TaiwanTechnicalSeriesRead",
    "TaiwanTechnicalCurrentPartial",
    "TaiwanTechnicalService",
    "TaiwanTechnicalStatus",
    "build_taiwan_technical_capability_contract",
]
