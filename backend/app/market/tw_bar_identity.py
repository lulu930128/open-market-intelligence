"""Canonical semantic, provenance, state, and composite identity for TW Bars."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from hashlib import sha256
import json
from typing import Any

from app.market.tw_bar_contracts import (
    BarBucketCoverage,
    TaiwanBarSeriesIdentity,
    TaiwanDerivedBucketCoverage,
)
from app.market_data.contracts import BarObservation, InstrumentKey


TAIWAN_BAR_FINGERPRINT_VERSION = "tw.bar.fingerprint.v1"
TAIWAN_BAR_LINEAGE_DIGEST_VERSION = "tw.bar.lineage_digest.v1"
TAIWAN_BAR_STATE_DIGEST_VERSION = "tw.bar.state_digest.v1"
TAIWAN_BAR_SERIES_REVISION_VERSION = "tw.bar.series_revision.v1"


def _decimal(value: Decimal | None) -> str | None:
    if value is None:
        return None
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("fingerprint timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _canonical(value: Any) -> Any:
    if isinstance(value, Decimal):
        return _decimal(value)
    if isinstance(value, datetime):
        return _timestamp(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _canonical(item) for key, item in sorted(value.items())}
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    return value


def _digest(payload: Any) -> str:
    encoded = json.dumps(
        _canonical(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _instrument(instrument: InstrumentKey) -> dict[str, str | None]:
    return {
        "market": instrument.market.value,
        "symbol": instrument.symbol,
        "instrument_type": instrument.instrument_type.value,
        "venue": instrument.venue,
    }


def _semantic_bar(bar: BarObservation, *, aggregation_version: str | None) -> dict[str, Any]:
    volume_status = bar.volume_status or (
        "observed" if bar.volume is not None else "missing"
    )
    return {
        "start_at": _timestamp(bar.start_at),
        "end_at": _timestamp(bar.end_at),
        "open": _decimal(bar.open_price),
        "high": _decimal(bar.high_price),
        "low": _decimal(bar.low_price),
        "close": _decimal(bar.close_price),
        "volume": _decimal(bar.volume.value) if bar.volume is not None else None,
        "volume_unit": bar.volume.unit.value if bar.volume is not None else None,
        "volume_applicability": volume_status,
        "turnover": _decimal(bar.turnover_value),
        "turnover_currency": bar.turnover_currency,
        "turnover_applicability": (
            "observed" if bar.turnover_value is not None else "missing"
        ),
        "trade_count": bar.trade_count,
        "trade_count_applicability": (
            "observed" if bar.trade_count is not None else "missing"
        ),
        "price_basis": bar.price_basis,
        "aggregation_version": aggregation_version,
    }


def _lineage_bar(bar: BarObservation) -> dict[str, Any]:
    return {
        "provider_binding": bar.lineage.provider,
        "source_binding": bar.lineage.source,
        "raw_contract_version": bar.lineage.raw_contract_version,
        "content_hash": bar.lineage.content_hash,
        "materialization_version": (
            bar.lineage.raw_contract_version
            if bar.lineage.authority.value == "derived"
            else None
        ),
        "event_identity": {
            "start_at": _timestamp(bar.start_at),
            "event_at": _timestamp(bar.lineage.event_at),
        },
    }


def _coverage_state(
    coverage: BarBucketCoverage | TaiwanDerivedBucketCoverage,
) -> dict[str, Any]:
    payload = coverage.model_dump(mode="python")
    payload.pop("evidence_refs", None)
    payload.pop("source_observation_count", None)
    return payload


def build_taiwan_bar_series_identity(
    *,
    instrument: InstrumentKey,
    requested_interval: str,
    base_interval: str,
    bars: tuple[BarObservation, ...],
    coverage: tuple[BarBucketCoverage | TaiwanDerivedBucketCoverage, ...],
    aggregation_version: str | None,
    state: Mapping[str, Any] | None = None,
) -> TaiwanBarSeriesIdentity:
    ordered = tuple(sorted(bars, key=lambda item: item.start_at))
    if bars != ordered:
        raise ValueError("bar identity input must be deterministically ordered")
    semantic_payload = {
        "contract_version": TAIWAN_BAR_FINGERPRINT_VERSION,
        "instrument": _instrument(instrument),
        "requested_interval": requested_interval,
        "base_interval": base_interval,
        "bars": [
            _semantic_bar(item, aggregation_version=aggregation_version)
            for item in ordered
        ],
    }
    lineage_payload = {
        "contract_version": TAIWAN_BAR_LINEAGE_DIGEST_VERSION,
        "instrument": _instrument(instrument),
        "bars": [_lineage_bar(item) for item in ordered],
    }
    state_payload = {
        "contract_version": TAIWAN_BAR_STATE_DIGEST_VERSION,
        "instrument": _instrument(instrument),
        "finalization": [item.finalization.value for item in ordered],
        "coverage": [_coverage_state(item) for item in coverage],
        "state": dict(state or {}),
    }
    series_fingerprint = _digest(semantic_payload)
    lineage_digest = _digest(lineage_payload)
    state_digest = _digest(state_payload)
    series_revision = _digest(
        {
            "contract_version": TAIWAN_BAR_SERIES_REVISION_VERSION,
            "series_fingerprint": series_fingerprint,
            "lineage_digest": lineage_digest,
            "state_digest": state_digest,
        }
    )
    return TaiwanBarSeriesIdentity(
        series_fingerprint=series_fingerprint,
        lineage_digest=lineage_digest,
        state_digest=state_digest,
        series_revision=series_revision,
    )


__all__ = [
    "TAIWAN_BAR_FINGERPRINT_VERSION",
    "TAIWAN_BAR_LINEAGE_DIGEST_VERSION",
    "TAIWAN_BAR_SERIES_REVISION_VERSION",
    "TAIWAN_BAR_STATE_DIGEST_VERSION",
    "build_taiwan_bar_series_identity",
]
