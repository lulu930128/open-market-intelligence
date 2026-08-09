from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
import math
from typing import Any

from sqlalchemy.orm import Session

from app.market.adr_parity import build_adr_parity_report
from app.market.calendar_status import expected_us_trade_date
from app.market.cross_market.aggregation import aggregate_cross_market_signals
from app.market.cross_market.proxy_signal_engine import build_proxy_signal
from app.market.cross_market.relation_store import build_relation_registry_read
from app.market.cross_market.schemas import (
    CrossMarketContextSignalRead,
    CrossMarketContextSummaryRead,
    CrossMarketTargetContextRead,
    InstrumentRefRead,
)
from app.market.cross_market.types import taiwan_stock_ref
from app.market.cross_market.types import DIRECT_RELATION_TYPES
from app.market.schemas import AdrParityRead


CONTEXT_SCHEMA_VERSION = "cross_market.context.v1"
METHODOLOGY_VERSION = "cross_market.relation_context.v2"
_PARITY_UNSET = object()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _instrument_from_mapping(mapping: dict[str, Any]) -> InstrumentRefRead:
    return InstrumentRefRead(
        market="US",
        instrument_type="adr",
        canonical_symbol=f"US:{mapping['adr_symbol']}",
        provider_symbol=mapping["adr_symbol"],
        exchange=mapping.get("adr_exchange"),
        currency="USD",
    )


def _direction_from_gap(value: float | None) -> str:
    if value is None or not math.isfinite(value):
        return "unknown"
    if value > 0.35:
        return "supportive"
    if value < -0.35:
        return "adverse"
    return "neutral"


def _summary(
    *,
    direction: str,
    gap: float | None,
    status: str,
    decision_usable: bool,
    has_direct: bool,
    has_proxy: bool,
    proxy_directions: set[str],
) -> CrossMarketContextSummaryRead:
    reason_codes: list[str] = []
    if has_direct:
        reason_codes.append(
            "direct_adr_parity" if gap is not None else "direct_adr_data_missing"
        )
    if has_proxy:
        proxy_direction = (
            "adverse"
            if "adverse" in proxy_directions
            else "supportive"
            if "supportive" in proxy_directions
            else "neutral"
            if "neutral" in proxy_directions
            else "unknown"
        )
        reason_codes.append(
            {
                "supportive": "industry_peer_residual_positive",
                "adverse": "industry_peer_residual_negative",
                "neutral": "industry_peer_residual_neutral",
                "unknown": "industry_peer_residual_unavailable",
            }[proxy_direction]
        )
    if not reason_codes:
        reason_codes.append("cross_market_relation_not_applicable")
    if status == "limited":
        reason_codes.append("mapping_registry_not_primary")
    if has_proxy and not has_direct:
        title = {
            "supportive": "同業代理 residual 偏多（非因果）",
            "adverse": "同業代理 residual 偏弱（非因果）",
            "neutral": "同業代理 residual 接近中性（非因果）",
            "unknown": "同業代理資料不足（非因果）",
        }[direction]
    else:
        title = {
            "supportive": "ADR 隱含價高於台股對齊基準",
            "adverse": "ADR 隱含價低於台股對齊基準",
            "neutral": "ADR 與台股對齊基準接近平價",
            "unknown": "ADR parity 資料不足",
        }[direction]
    if not decision_usable and status not in {"not_applicable", "ready"}:
        title = f"{title}（{status}）"
    return CrossMarketContextSummaryRead(
        stance=direction,
        score=(round(max(-100.0, min(100.0, gap)), 4) if gap is not None else None),
        confidence=("high" if decision_usable else "low"),
        title=title,
        reason_codes=reason_codes,
    )


def _snapshot_id(payload: dict[str, Any]) -> str:
    digest = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    return f"cmctx:{digest[:24]}"


def _relation_snapshot_version(
    relations: list[Any],
    mapping_resolution: dict[str, Any] | None,
) -> str:
    versions = list(
        dict.fromkeys(
            (int(relation.relation_id), int(relation.relation_version))
            for relation in relations
        )
    )
    if versions:
        return "relation_registry:" + ",".join(
            f"{relation_id}:v{relation_version}"
            for relation_id, relation_version in versions
        )
    if mapping_resolution:
        relation_id = mapping_resolution.get("relation_id")
        relation_version = mapping_resolution.get("relation_version")
        if relation_id is not None and relation_version is not None:
            return f"relation_registry:{relation_id}:v{relation_version}"
    if mapping_resolution and mapping_resolution.get("selected_source") == "legacy":
        return "legacy_adr_mapping:v1"
    return "relation_registry:none"


def build_cross_market_target_context(
    db: Session,
    stock_id: str,
    *,
    decision_at: datetime | None = None,
    expected_adr_trade_date: date | None = None,
    adr_parity_payload: dict[str, Any] | None | object = _PARITY_UNSET,
    data_available_at: datetime | None = None,
) -> CrossMarketTargetContextRead:
    target_ref = taiwan_stock_ref(stock_id)
    built_at = decision_at or _now()
    if built_at.tzinfo is None:
        built_at = built_at.replace(tzinfo=timezone.utc)
    expected_date = expected_adr_trade_date or expected_us_trade_date(
        "us_daily_price",
        now=built_at,
    )
    if expected_date is None:
        expected_date = built_at.date()

    registry = build_relation_registry_read(
        db,
        stock_id,
        as_of=built_at.date(),
        generated_at=built_at,
        data_available_at=data_available_at or built_at,
    )
    parity_payload = (
        build_adr_parity_report(
            db,
            stock_id,
            expected_adr_trade_date=expected_date,
            generated_at=built_at,
            mapping_as_of=built_at.date(),
            data_available_at=data_available_at,
        )
        if adr_parity_payload is _PARITY_UNSET
        else adr_parity_payload
    )
    parity = AdrParityRead.model_validate(parity_payload) if parity_payload else None
    mapping_resolution = (
        parity_payload.get("mapping_resolution")
        if isinstance(parity_payload, dict)
        else None
    )
    selected_source = (
        str(mapping_resolution.get("selected_source"))
        if isinstance(mapping_resolution, dict)
        else "none"
    )
    registry_mapping_ready = bool(
        isinstance(mapping_resolution, dict)
        and selected_source == "registry"
        and mapping_resolution.get("registry_status") == "ready"
        and mapping_resolution.get("shadow_status") in {"match", "registry_only"}
    )

    gap = parity.implied_gap_pct if parity is not None else None
    relation_id = (
        mapping_resolution.get("relation_id")
        if isinstance(mapping_resolution, dict)
        else None
    )
    relation_version = (
        mapping_resolution.get("relation_version")
        if isinstance(mapping_resolution, dict)
        else None
    )
    mapping_limitations = (
        list(mapping_resolution.get("limitations") or [])
        if isinstance(mapping_resolution, dict)
        else []
    )
    limitations = _dedupe(
        [
            *mapping_limitations,
            "latest_local_cache_projection_not_materialized_snapshot",
        ]
    )

    signals: list[CrossMarketContextSignalRead] = []
    if parity is not None:
        if not registry_mapping_ready:
            direct_status = "limited"
        elif parity.status in {"ready", "stale", "partial"}:
            direct_status = parity.status
        else:
            direct_status = "blocked"
        direct_decision_usable = bool(
            direct_status == "ready" and gap is not None
        )
        source = _instrument_from_mapping(parity_payload["mapping"])
        quality_multiplier = 1.0 if direct_decision_usable else 0.0
        evidence_ids = (
            list(mapping_resolution.get("evidence_ids") or [])
            if isinstance(mapping_resolution, dict)
            else []
        )
        signals.append(
            CrossMarketContextSignalRead(
                signal_id=(
                    f"adr_parity:{target_ref.canonical_symbol}:"
                    f"{relation_id or 'legacy'}:{relation_version or 1}"
                ),
                relation_id=relation_id,
                relation_version=relation_version,
                source=source,
                target=InstrumentRefRead(**target_ref.__dict__),
                bucket="direct_equivalent",
                relation_type="same_equity_dr",
                calculation={
                    "kind": "adr_implied_gap",
                    "formula": parity.formula,
                    "implied_gap_pct": parity.implied_gap_pct,
                    "remaining_gap_pct": parity.remaining_gap_pct,
                    "adr_trade_date": parity.adr_trade_date,
                    "tw_reference_trade_date": parity.tw_reference_trade_date,
                    "target_tw_trade_date": parity.target_tw_trade_date,
                },
                direction=_direction_from_gap(gap),
                configured_weight=1.0,
                quality_multiplier=quality_multiplier,
                effective_weight=quality_multiplier,
                contribution=(gap if direct_decision_usable else None),
                status=direct_status,
                decision_usable=direct_decision_usable,
                confidence_tier=("A" if registry_mapping_ready else "legacy"),
                freshness=parity.freshness,
                evidence_refs=[f"cross_market_relation_evidence:{item}" for item in evidence_ids],
                source_refs=parity.source_refs,
                warnings=parity.warnings,
                limitations=limitations,
                excluded_reason=(
                    None
                    if direct_decision_usable
                    else f"context_status_{direct_status}"
                ),
            )
        )

    direct_source_symbols = {
        relation.source.canonical_symbol
        for relation in registry.relations
        if relation.relation_type in DIRECT_RELATION_TYPES
    }
    for relation in registry.relations:
        if relation.relation_type in DIRECT_RELATION_TYPES:
            continue
        signal = build_proxy_signal(
            db,
            relation,
            expected_trade_date=expected_date,
            data_available_at=data_available_at,
        )
        if relation.source.canonical_symbol in direct_source_symbols:
            signal = signal.model_copy(
                update={
                    "status": "blocked",
                    "decision_usable": False,
                    "quality_multiplier": 0.0,
                    "effective_weight": 0.0,
                    "normalized_weight": None,
                    "contribution": None,
                    "excluded_reason": "duplicate_direct_source",
                    "warnings": _dedupe(
                        [*signal.warnings, "duplicate_direct_source"]
                    ),
                }
            )
        signals.append(signal)

    signals, bucket_scores, coverage = aggregate_cross_market_signals(
        relations=registry.relations,
        signals=signals,
    )
    usable_signals = [signal for signal in signals if signal.decision_usable]
    signal_statuses = {signal.status for signal in signals}
    if usable_signals:
        status = (
            "ready"
            if len(usable_signals) == coverage.configured_signal_count
            else "partial"
        )
    elif "stale" in signal_statuses:
        status = "stale"
    elif "partial" in signal_statuses:
        status = "partial"
    elif "limited" in signal_statuses:
        status = "limited"
    elif signals or registry.relation_count:
        status = "blocked"
    else:
        status = "not_applicable"
    decision_usable = bool(usable_signals)
    composite_score = (
        round(
            sum(
                float(value)
                for value in bucket_scores.values()
                if value is not None
            ),
            6,
        )
        if usable_signals
        else None
    )
    direction = _direction_from_gap(composite_score)

    missing = _dedupe(
        [
            *registry.missing,
            *(parity.missing if parity is not None else []),
            *(
                warning
                for signal in signals
                for warning in signal.warnings
                if warning.startswith("us_daily_price.")
                or warning == "proxy_benchmark_policy"
            ),
        ]
    )
    warnings = _dedupe(
        [
            *registry.warnings,
            *(parity.warnings if parity is not None else []),
            *(warning for signal in signals for warning in signal.warnings),
        ]
    )
    limitations = _dedupe(
        [
            *limitations,
            *(item for signal in signals for item in signal.limitations),
        ]
    )
    source_refs = [
        *registry.source_refs,
        *(parity.source_refs if parity is not None else []),
        *(source_ref for signal in signals for source_ref in signal.source_refs),
        {"type": "derived", "name": "app.market.cross_market.context"},
    ]
    deduped_source_refs: list[dict[str, str]] = []
    source_ref_keys: set[str] = set()
    for source_ref in source_refs:
        key = json.dumps(source_ref, ensure_ascii=False, sort_keys=True, default=str)
        if key in source_ref_keys:
            continue
        source_ref_keys.add(key)
        deduped_source_refs.append(source_ref)

    relation_snapshot_version = _relation_snapshot_version(
        registry.relations,
        mapping_resolution,
    )
    snapshot_payload = {
        "schema_version": CONTEXT_SCHEMA_VERSION,
        "methodology_version": METHODOLOGY_VERSION,
        "target": target_ref.canonical_symbol,
        "decision_at": built_at.isoformat(),
        "relation_snapshot_version": relation_snapshot_version,
        "adr_trade_date": parity.adr_trade_date if parity is not None else None,
        "tw_reference_trade_date": (
            parity.tw_reference_trade_date if parity is not None else None
        ),
        "implied_gap_pct": gap,
        "signals": [
            {
                "signal_id": signal.signal_id,
                "status": signal.status,
                "calculation": signal.calculation,
                "effective_weight": signal.effective_weight,
                "contribution": signal.contribution,
            }
            for signal in signals
        ],
        "bucket_scores": bucket_scores,
        "status": status,
    }
    snapshot_id = _snapshot_id(snapshot_payload)
    summary = _summary(
        direction=direction,
        gap=composite_score,
        status=status,
        decision_usable=decision_usable,
        has_direct=any(
            signal.bucket == "direct_equivalent" for signal in signals
        ),
        has_proxy=any(
            signal.bucket != "direct_equivalent" for signal in signals
        ),
        proxy_directions={
            signal.direction
            for signal in signals
            if signal.bucket != "direct_equivalent"
            and signal.decision_usable
        },
    )
    evidence_passport = {
        "kind": "cross_market_context_evidence",
        "snapshot_id": snapshot_id,
        "methodology_version": METHODOLOGY_VERSION,
        "relation_snapshot_version": relation_snapshot_version,
        "relation_ids": [
            relation.relation_id for relation in registry.relations
        ],
        "evidence_ids": list(
            dict.fromkeys(
                item.evidence_id
                for relation in registry.relations
                for item in relation.evidence
            )
        ),
        "mapping_source": selected_source,
        "source_refs": deduped_source_refs,
        "missing": missing,
        "warnings": warnings,
        "limitations": limitations,
    }

    return CrossMarketTargetContextRead(
        kind="cross_market_target_context",
        schema_version=CONTEXT_SCHEMA_VERSION,
        target=InstrumentRefRead(**target_ref.__dict__),
        status=status,
        decision_usable=decision_usable,
        as_of=max(
            (
                value
                for signal in signals
                for value in (
                    signal.calculation.get("adr_trade_date"),
                    signal.calculation.get("source_trade_date"),
                )
                if isinstance(value, date)
            ),
            default=None,
        ),
        decision_at=built_at,
        methodology_version=METHODOLOGY_VERSION,
        relation_snapshot_version=relation_snapshot_version,
        snapshot_id=snapshot_id,
        summary=summary,
        direct_equivalents=[parity] if parity is not None else [],
        signals=signals,
        bucket_scores=bucket_scores,
        coverage=coverage,
        freshness={
            "status": status,
            "expected_adr_trade_date": expected_date,
            "latest_adr_trade_date": parity.adr_trade_date if parity is not None else None,
            "relation_governance": registry.freshness,
            "market_data": parity.freshness if parity is not None else {},
            "proxy_market_data": [
                signal.freshness
                for signal in signals
                if signal.bucket != "direct_equivalent"
            ],
            "read_path_provider_refresh": False,
        },
        missing=missing,
        warnings=warnings,
        limitations=limitations,
        source_refs=deduped_source_refs,
        evidence_passport=evidence_passport,
    )
