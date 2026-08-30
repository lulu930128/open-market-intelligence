"""Typed adapters from provider-owned Taiwan current-session payloads."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from typing import Any

from app.market.tw_current_market_capabilities import TaiwanCurrentSourceBinding
from app.market_data.contracts import (
    BarFinalization,
    ConnectionStatus,
    EnablementStatus,
    EntitlementStatus,
    EvidenceFreshness,
    Market,
    MarketBreadthObservation,
    MarketIndexObservation,
    ObservationState,
    OperationalStatus,
    ProviderResourceHealth,
    Quantity,
    QuantityUnit,
    SourceLineage,
)
from app.market_data.gateway import (
    MarketBreadthAcquisitionResult,
    MarketIndexAcquisitionResult,
)
from app.market_data.integration_contracts import (
    AcquisitionResourceAttempt,
    AcquisitionStatus,
    AcquisitionSummary,
    DataRequirementV2,
    DatasetTarget,
    RawFetchReceiptV1,
)
from app.market_data.provider_catalog import ProviderResourceRouteV2


TAIPEI_TZ = timezone(timedelta(hours=8))


@dataclass(frozen=True, slots=True)
class CurrentMarketProviderPayload:
    payload: dict[str, Any] | None
    status: str
    url: str | None = None
    status_code: int | None = 200
    content_type: str | None = "application/json"
    error: str | None = None
    operational_status: OperationalStatus | None = None
    detail_code: str | None = None
    retry_after_seconds: int | None = None
    cooldown_until: datetime | None = None
    external_calls: int = 1
    method: str = "GET"


PayloadReader = Callable[[str, int], CurrentMarketProviderPayload]
Clock = Callable[[], datetime]


def _aware(value: datetime, *, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value


def _datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return _aware(value, label="provider event time")
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return _aware(parsed, label="provider event time")
    return None


def _date(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _decimal(value: Any, *, non_negative: bool = False) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None
    if not parsed.is_finite() or (non_negative and parsed < 0):
        return None
    return parsed


def _integer(value: Any) -> int | None:
    parsed = _decimal(value, non_negative=True)
    if parsed is None or parsed != parsed.to_integral_value():
        return None
    return int(parsed)


def _breadth_partitions(raw: dict[str, Any]) -> tuple[int, int]:
    """Normalize new and legacy breadth payloads into disjoint partitions."""

    legacy_missing = _integer(raw.get("missing_count")) or 0
    if "received_unclassified_count" in raw:
        received_unclassified = (
            _integer(raw.get("received_unclassified_count")) or 0
        )
    else:
        legacy_unknown = _integer(raw.get("unknown_count")) or 0
        received_unclassified = max(legacy_unknown - legacy_missing, 0)

    if "not_received_count" in raw:
        not_received = _integer(raw.get("not_received_count")) or 0
    else:
        not_received = legacy_missing
    return received_unclassified, not_received


def _raw_text(payload: CurrentMarketProviderPayload) -> str:
    if payload.payload is None:
        return ""
    return json.dumps(
        payload.payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=lambda value: value.isoformat()
        if isinstance(value, (date, datetime))
        else str(value),
    )


def _lineage(
    *,
    binding: TaiwanCurrentSourceBinding,
    event_at: datetime,
    fetched_at: datetime,
    content_hash: str,
) -> SourceLineage:
    return SourceLineage(
        provider=binding.descriptor.provider_key,
        source=binding.source,
        authority=binding.descriptor.authority,
        raw_contract_version=binding.parser_version,
        event_at=event_at,
        received_at=fetched_at,
        fetched_at=fetched_at,
        content_hash=content_hash,
    )


def _health(
    requirement: DataRequirementV2,
    *,
    provider: str,
    checked_at: datetime,
    payload: CurrentMarketProviderPayload,
    healthy: bool,
) -> ProviderResourceHealth:
    operational = payload.operational_status or (
        OperationalStatus.HEALTHY if healthy else OperationalStatus.FAILED
    )
    provider_is_live = healthy and operational == OperationalStatus.HEALTHY
    return ProviderResourceHealth(
        provider=provider,
        market=Market.TW,
        capability=requirement.request.capability_id,
        enablement=EnablementStatus.ENABLED,
        connection=(
            ConnectionStatus.CONNECTED
            if provider_is_live
            else ConnectionStatus.DEGRADED
            if healthy
            else ConnectionStatus.DISCONNECTED
        ),
        entitlement=EntitlementStatus.ENTITLED,
        operational=operational,
        freshness=(
            EvidenceFreshness.LIVE
            if provider_is_live
            else EvidenceFreshness.STALE
            if healthy
            else EvidenceFreshness.MISSING
        ),
        checked_at=checked_at,
        detail_code=payload.detail_code or (
            "CURRENT_MARKET_PROVIDER_AVAILABLE"
            if healthy
            else "CURRENT_MARKET_PROVIDER_FAILED"
        ),
        retry_after_seconds=payload.retry_after_seconds,
        cooldown_until=payload.cooldown_until,
    )


def _receipt(
    *,
    binding: TaiwanCurrentSourceBinding,
    route: ProviderResourceRouteV2,
    payload: CurrentMarketProviderPayload,
    fetched_at: datetime,
    raw_text: str,
    parse_error: str | None,
) -> RawFetchReceiptV1:
    return RawFetchReceiptV1(
        provider=binding.descriptor.provider_key,
        source=binding.source,
        resource_id=route.resource_id,
        fetched_at=fetched_at,
        method=payload.method,
        url=payload.url,
        status_code=payload.status_code,
        content_type=payload.content_type,
        content_hash=sha256(raw_text.encode("utf-8")).hexdigest(),
        raw_text=raw_text or None,
        parser_version=binding.parser_version,
        error_message=parse_error or payload.error,
    )


def _summary(
    *,
    binding: TaiwanCurrentSourceBinding,
    route: ProviderResourceRouteV2,
    observation_count: int,
    error: str | None,
    payload: CurrentMarketProviderPayload,
) -> AcquisitionSummary:
    completed = error is None and observation_count > 0
    return AcquisitionSummary(
        attempted=True,
        status=(AcquisitionStatus.COMPLETED if completed else AcquisitionStatus.FAILED),
        providers_attempted=(binding.descriptor.provider_key,),
        resource_attempts=(
            AcquisitionResourceAttempt(
                provider=binding.descriptor.provider_key,
                resource_id=route.resource_id,
            ),
        ),
        external_calls=payload.external_calls,
        limitations=(
            () if completed else ("PROVIDER_REQUEST_OR_PARSE_FAILED",)
        ),
    )


class CurrentIndexAdapter:
    def __init__(
        self,
        binding: TaiwanCurrentSourceBinding,
        reader: PayloadReader,
        *,
        clock: Clock,
    ) -> None:
        self.binding = binding
        self._reader = reader
        self._clock = clock

    def acquire(
        self,
        requirement: DataRequirementV2,
        route: ProviderResourceRouteV2,
    ) -> MarketIndexAcquisitionResult:
        if not isinstance(requirement.target, DatasetTarget):
            raise ValueError("current index adapter requires dataset target")
        fetched_at = _aware(self._clock(), label="current index adapter clock")
        payload = self._reader(requirement.target.scope_key, route.timeout_seconds)
        raw_text = _raw_text(payload)
        content_hash = sha256(raw_text.encode("utf-8")).hexdigest()
        observation: MarketIndexObservation | None = None
        error = payload.error
        try:
            raw = payload.payload or {}
            points = raw.get("points") if isinstance(raw.get("points"), list) else []
            latest = points[-1] if points and isinstance(points[-1], dict) else {}
            event_at = (
                _datetime(raw.get("as_of"))
                or _datetime(latest.get("time"))
                or _datetime(raw.get("event_at"))
            )
            close_value = _decimal(raw.get("close")) or _decimal(latest.get("price"))
            change = _decimal(raw.get("change"))
            previous_close = _decimal(raw.get("previous_close"))
            if change is None and close_value is not None and previous_close is not None:
                change = close_value - previous_close
            if event_at is None or close_value is None or close_value <= 0 or change is None:
                raise ValueError("current index payload lacks event/close/change")
            trade_date = _date(raw.get("trade_date")) or _date(raw.get("time"))
            trade_date = trade_date or event_at.astimezone(TAIPEI_TZ).date()
            volume = _integer(raw.get("volume"))
            trade_value = _decimal(raw.get("trade_value"), non_negative=True)
            transaction_count = _integer(raw.get("transaction_count"))
            incomplete = volume is None or trade_value is None or transaction_count is None
            observation = MarketIndexObservation(
                market=Market.TW,
                index_id=requirement.target.scope_key,
                venue=("TWSE" if requirement.target.scope_key == "TAIEX" else "TPEX"),
                lineage=_lineage(
                    binding=self.binding,
                    event_at=event_at,
                    fetched_at=fetched_at,
                    content_hash=content_hash,
                ),
                session=requirement.session,
                trade_date=trade_date,
                close_value=close_value,
                price_change=change,
                trade_volume=(
                    Quantity(value=Decimal(volume), unit=QuantityUnit.UNIT)
                    if volume is not None
                    else None
                ),
                trade_value=trade_value,
                currency=("TWD" if trade_value is not None else None),
                transaction_count=transaction_count,
                state=(ObservationState.PARTIAL if incomplete else ObservationState.AVAILABLE),
                value_semantics="current_index_snapshot",
                finalization=BarFinalization.PROVISIONAL,
                official=self.binding.descriptor.authority.value == "exchange",
                provisional=True,
            )
        except (TypeError, ValueError) as exc:
            error = str(exc)
        receipt = _receipt(
            binding=self.binding,
            route=route,
            payload=payload,
            fetched_at=fetched_at,
            raw_text=raw_text,
            parse_error=error,
        )
        observations = (observation,) if observation is not None else ()
        return MarketIndexAcquisitionResult(
            summary=_summary(
                binding=self.binding,
                route=route,
                observation_count=len(observations),
                error=error,
                payload=payload,
            ),
            observations=observations,
            receipts=(receipt,),
            provider_health=(
                _health(
                    requirement,
                    provider=self.binding.descriptor.provider_key,
                    checked_at=fetched_at,
                    payload=payload,
                    healthy=observation is not None,
                ),
            ),
        )


class CurrentBreadthAdapter:
    def __init__(
        self,
        binding: TaiwanCurrentSourceBinding,
        reader: PayloadReader,
        *,
        clock: Clock,
    ) -> None:
        self.binding = binding
        self._reader = reader
        self._clock = clock

    def acquire(
        self,
        requirement: DataRequirementV2,
        route: ProviderResourceRouteV2,
    ) -> MarketBreadthAcquisitionResult:
        if not isinstance(requirement.target, DatasetTarget):
            raise ValueError("current breadth adapter requires dataset target")
        fetched_at = _aware(self._clock(), label="current breadth adapter clock")
        payload = self._reader(requirement.target.scope_key, route.timeout_seconds)
        raw_text = _raw_text(payload)
        content_hash = sha256(raw_text.encode("utf-8")).hexdigest()
        observation: MarketBreadthObservation | None = None
        error = payload.error
        try:
            raw = payload.payload or {}
            event_at = (
                _datetime(raw.get("snapshot_as_of"))
                or _datetime(raw.get("as_of"))
                or _datetime(raw.get("event_at"))
            )
            advance = _integer(raw.get("advance_count"))
            decline = _integer(raw.get("decline_count"))
            unchanged = _integer(raw.get("unchanged_count"))
            received_unclassified, not_received = _breadth_partitions(raw)
            if event_at is None or any(
                value is None for value in (advance, decline, unchanged)
            ):
                raise ValueError("current breadth payload lacks event/classified counts")
            classified = int(advance) + int(decline) + int(unchanged)
            universe = _integer(raw.get("universe_count"))
            universe = universe or _integer(raw.get("total_count"))
            universe = universe or classified + received_unclassified + not_received
            if universe < classified + received_unclassified + not_received:
                raise ValueError("current breadth universe is smaller than its partition")
            if universe > classified + received_unclassified + not_received:
                not_received += universe - (
                    classified + received_unclassified + not_received
                )
            trade_value = _decimal(raw.get("trade_value"), non_negative=True)
            incomplete = (
                received_unclassified > 0
                or not_received > 0
                or trade_value is None
            )
            trade_date = _date(raw.get("trade_date"))
            trade_date = trade_date or event_at.astimezone(TAIPEI_TZ).date()
            observation = MarketBreadthObservation(
                market=Market.TW,
                venue=requirement.target.scope_key,
                lineage=_lineage(
                    binding=self.binding,
                    event_at=event_at,
                    fetched_at=fetched_at,
                    content_hash=content_hash,
                ),
                session=requirement.session,
                trade_date=trade_date,
                scope=str(raw.get("scope") or "full_market"),
                universe_source=str(
                    raw.get("universe_source")
                    or raw.get("universe_definition")
                    or f"{requirement.target.scope_key}_listed_universe"
                )[:192],
                universe_count=universe,
                advance_count=int(advance),
                decline_count=int(decline),
                unchanged_count=int(unchanged),
                unknown_count=received_unclassified,
                missing_count=not_received,
                trade_value=trade_value,
                currency=("TWD" if trade_value is not None else None),
                state=(ObservationState.PARTIAL if incomplete else ObservationState.AVAILABLE),
                price_semantics="current_last_trade_vs_reference",
                official=self.binding.descriptor.authority.value == "exchange",
                provisional=True,
            )
        except (TypeError, ValueError) as exc:
            error = str(exc)
        receipt = _receipt(
            binding=self.binding,
            route=route,
            payload=payload,
            fetched_at=fetched_at,
            raw_text=raw_text,
            parse_error=error,
        )
        observations = (observation,) if observation is not None else ()
        return MarketBreadthAcquisitionResult(
            summary=_summary(
                binding=self.binding,
                route=route,
                observation_count=len(observations),
                error=error,
                payload=payload,
            ),
            observations=observations,
            receipts=(receipt,),
            provider_health=(
                _health(
                    requirement,
                    provider=self.binding.descriptor.provider_key,
                    checked_at=fetched_at,
                    payload=payload,
                    healthy=observation is not None,
                ),
            ),
        )


__all__ = [
    "CurrentBreadthAdapter",
    "CurrentIndexAdapter",
    "CurrentMarketProviderPayload",
]
