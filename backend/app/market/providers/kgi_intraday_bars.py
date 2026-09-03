"""Canonicalize bounded KGI minute-KBar stream snapshots without provider I/O."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from typing import Any

from app.market.trading_calendar import TAIWAN_TZ
from app.market.tw_intraday_capabilities import (
    KGI_INTRADAY_PARSER_VERSION,
    KGI_INTRADAY_PROVIDER,
    KGI_INTRADAY_RESOURCE_ID,
    KGI_INTRADAY_SOURCE,
)
from app.market_data.contracts import (
    AuthorityClass,
    BarFinalization,
    BarObservation,
    ConnectionStatus,
    EnablementStatus,
    EntitlementStatus,
    EvidenceFreshness,
    Market,
    OperationalStatus,
    ProviderResourceHealth,
    Quantity,
    QuantityUnit,
    SourceLineage,
)
from app.market_data.gateway import BarAcquisitionResult
from app.market_data.integration_contracts import (
    AcquisitionResourceAttempt,
    AcquisitionStatus,
    AcquisitionSummary,
    BarCapabilityRequest,
    DataRequirementV2,
    InstrumentTarget,
    RawFetchReceiptV1,
)


KGI_MINUTE_KBAR_STREAM_URL = "kgi-superpy://stream/minute-kbars"
KGI_MINUTE_KBAR_TIMESTAMP_SEMANTICS = (
    "provider_bucket_end_normalized_to_canonical_start"
)
KGI_MINUTE_KBAR_TOTAL_AMOUNT_SEMANTICS = (
    "provider_cumulative_not_minute_turnover"
)


def _datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return parsed.replace(tzinfo=TAIWAN_TZ)
    return parsed.astimezone(TAIWAN_TZ)


def _decimal(value: object, *, positive: bool = False) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not parsed.is_finite() or (positive and parsed <= 0):
        return None
    return parsed


def _volume(value: object) -> Quantity | None:
    lots = _decimal(value)
    if lots is None or lots < 0:
        return None
    shares = lots * Decimal(1000)
    if shares != shares.to_integral_value():
        return None
    return Quantity(
        value=shares,
        unit=QuantityUnit.SHARE,
        original_value=lots,
        original_unit=QuantityUnit.BOARD_LOT,
        scale=Decimal(1000),
    )


def kgi_minute_kbar_bucket_bounds(
    value: object,
) -> tuple[datetime, datetime] | None:
    """Return canonical [start, end) for KGI's end-labelled 1m callback.

    KGI's public documentation names the field only as the KBar datetime. OMI
    production overlap on 2026-09-03 repeatedly showed callback 10:47 matching
    the NStock 10:46 bucket, and the same one-minute relation for later rows.
    Keep this provider defect explicit and versioned; it is not a generic
    timezone or all-provider adjustment.
    """

    provider_bucket_end = _datetime(value)
    if provider_bucket_end is None:
        return None
    return provider_bucket_end - timedelta(minutes=1), provider_bucket_end


def kgi_minute_kbar_acquisition(
    stream: dict[str, Any],
    requirement: DataRequirementV2,
) -> BarAcquisitionResult:
    """Convert the existing bounded manager buffer into canonical observations."""

    if not isinstance(requirement.target, InstrumentTarget) or not isinstance(
        requirement.request,
        BarCapabilityRequest,
    ):
        raise ValueError("KGI minute bars require an instrument bar target")
    if requirement.request.interval != "1m":
        raise ValueError("KGI minute-bar materialization supports 1m only")
    if str(stream.get("stock_id") or "").strip().upper() != (
        requirement.target.instrument.symbol
    ):
        raise ValueError("KGI minute-bar stream crossed requested instrument")
    raw_bars = stream.get("minute_kbars")
    rows = [dict(item) for item in raw_bars or [] if isinstance(item, dict)]
    attempt = AcquisitionResourceAttempt(
        provider=KGI_INTRADAY_PROVIDER,
        resource_id=KGI_INTRADAY_RESOURCE_ID,
    )
    if not rows:
        return BarAcquisitionResult(
            summary=AcquisitionSummary(
                attempted=False,
                status=AcquisitionStatus.NOT_ATTEMPTED,
                limitations=("KGI_MINUTE_KBAR_BUFFER_EMPTY",),
            ),
        )

    raw_text = json.dumps(
        rows,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    content_hash = sha256(raw_text.encode("utf-8")).hexdigest()
    observations: list[BarObservation] = []
    for row in rows:
        bounds = kgi_minute_kbar_bucket_bounds(
            row.get("provider_event_time") or row.get("event_time")
        )
        received_at = _datetime(row.get("received_at"))
        prices = {
            key: _decimal(row.get(key), positive=True)
            for key in ("open", "high", "low", "close")
        }
        if (
            bounds is None
            or received_at is None
            or any(value is None for value in prices.values())
        ):
            continue
        start_at, end_at = bounds
        if not (
            requirement.request.start_at <= start_at < requirement.request.end_at
        ):
            continue
        from app.market.tw_instrument_trading_policy import (
            is_taiwan_continuous_time_bar_start,
        )
        if not is_taiwan_continuous_time_bar_start(start_at):
            continue
        if requirement.requested_at < end_at:
            # KGI labels this callback with the bucket end. Until that instant,
            # the minute remains provider state and cannot be persisted FINAL.
            continue
        volume = _volume(row.get("volume_lots"))
        observations.append(
            BarObservation(
                instrument=requirement.target.instrument,
                lineage=SourceLineage(
                    provider=KGI_INTRADAY_PROVIDER,
                    source=KGI_INTRADAY_SOURCE,
                    authority=AuthorityClass.BROKER,
                    raw_contract_version=KGI_INTRADAY_PARSER_VERSION,
                    # Preserve the provider evidence time (bucket end) while
                    # start_at/end_at carry canonical interval identity.
                    event_at=end_at,
                    received_at=received_at,
                    fetched_at=requirement.requested_at,
                    content_hash=content_hash,
                ),
                interval="1m",
                start_at=start_at,
                end_at=end_at,
                open_price=prices["open"],  # type: ignore[arg-type]
                high_price=prices["high"],  # type: ignore[arg-type]
                low_price=prices["low"],  # type: ignore[arg-type]
                close_price=prices["close"],  # type: ignore[arg-type]
                volume=volume,
                volume_status="observed" if volume is not None else "missing",
                price_basis="raw",
                # KGI documents total_amount as cumulative turnover. It stays
                # in the raw receipt and must not masquerade as minute turnover.
                turnover_value=None,
                turnover_currency=None,
                finalization=BarFinalization.FINAL,
            )
        )
    if not observations:
        return BarAcquisitionResult(
            summary=AcquisitionSummary(
                attempted=True,
                status=AcquisitionStatus.PARTIAL,
                providers_attempted=(KGI_INTRADAY_PROVIDER,),
                resource_attempts=(attempt,),
                limitations=("KGI_MINUTE_KBAR_ROWS_UNUSABLE",),
            ),
        )
    receipt = RawFetchReceiptV1(
        provider=KGI_INTRADAY_PROVIDER,
        source=KGI_INTRADAY_SOURCE,
        resource_id=KGI_INTRADAY_RESOURCE_ID,
        fetched_at=requirement.requested_at,
        method="STREAM_BUFFER",
        url=KGI_MINUTE_KBAR_STREAM_URL,
        status_code=200,
        content_type="application/json",
        content_hash=content_hash,
        raw_text=raw_text,
        parser_version=KGI_INTRADAY_PARSER_VERSION,
    )
    return BarAcquisitionResult(
        summary=AcquisitionSummary(
            attempted=True,
            status=AcquisitionStatus.COMPLETED,
            providers_attempted=(KGI_INTRADAY_PROVIDER,),
            resource_attempts=(attempt,),
            external_calls=0,
            subscriptions_created=0,
            limitations=(
                "MATERIALIZED_FROM_EXISTING_SUBSCRIPTION",
                "KGI_PROVIDER_BUCKET_END_NORMALIZED_TO_CANONICAL_START",
                "KGI_CUMULATIVE_TOTAL_AMOUNT_NOT_PROJECTED_AS_MINUTE_TURNOVER",
            ),
        ),
        observations=tuple(observations),
        receipts=(receipt,),
        provider_health=(
            ProviderResourceHealth(
                provider=KGI_INTRADAY_PROVIDER,
                market=Market.TW,
                capability=requirement.request.capability_id,
                resource_id=KGI_INTRADAY_RESOURCE_ID,
                enablement=EnablementStatus.ENABLED,
                connection=ConnectionStatus.CONNECTED,
                entitlement=EntitlementStatus.ENTITLED,
                operational=OperationalStatus.HEALTHY,
                freshness=EvidenceFreshness.LIVE,
                checked_at=requirement.requested_at,
                detail_code="KGI_MINUTE_KBAR_BUFFER_AVAILABLE",
            ),
        ),
    )


__all__ = [
    "KGI_MINUTE_KBAR_TIMESTAMP_SEMANTICS",
    "KGI_MINUTE_KBAR_TOTAL_AMOUNT_SEMANTICS",
    "kgi_minute_kbar_acquisition",
    "kgi_minute_kbar_bucket_bounds",
]
