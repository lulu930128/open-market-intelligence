"""Official Taiwan index Base-1d adapter.

The adapter emits only canonical ``1d`` observations. It never aggregates
provider intraday data, persists rows, or resolves competing candidates.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from typing import Any, Protocol

from app.market.index_parsers import (
    as_float,
    parse_trade_date,
    parse_twse_index_daily_ohlc_rows,
)
from app.market.trading_calendar import TAIWAN_TZ
from app.market.tw_bar_contracts import (
    TAIEX_OFFICIAL_DAILY_PROVIDER,
    TAIEX_OFFICIAL_DAILY_SOURCE,
    TPEX_OFFICIAL_5S_COMPONENT_SOURCE,
    TPEX_OFFICIAL_5S_PARSER_VERSION,
)
from app.market_data.contracts import (
    AuthorityClass,
    BarFinalization,
    BarObservation,
    ConnectionStatus,
    EnablementStatus,
    EntitlementStatus,
    EvidenceFreshness,
    InstrumentKey,
    InstrumentType,
    Market,
    OperationalStatus,
    ProviderResourceHealth,
    SourceLineage,
)
from app.market_data.gateway import BarAcquisitionResult
from app.market_data.integration_contracts import (
    AcquisitionResourceAttempt,
    AcquisitionStatus,
    AcquisitionSummary,
    RawFetchReceiptV1,
)
from app.market_data.provider_catalog import (
    AcquisitionMode,
    DescriptorTargetKind,
    ProviderCapabilityDescriptorV2,
    ProviderResourceRouteV2,
)

from . import tpex, twse


TAIEX_DAILY_RESOURCE_ID = "MI_5MINS_HIST"
TAIEX_DAILY_PARSER_VERSION = "twse.mi_5mins_hist.daily_ohlc.v1"

TAIEX_OFFICIAL_DAILY_DESCRIPTOR = ProviderCapabilityDescriptorV2(
    provider_key=TAIEX_OFFICIAL_DAILY_PROVIDER,
    market=Market.TW,
    capability_id="daily.ohlcv",
    resource_id=TAIEX_DAILY_RESOURCE_ID,
    authority=AuthorityClass.EXCHANGE,
    target_kinds=(DescriptorTargetKind.INSTRUMENT, DescriptorTargetKind.DATASET),
    dataset_ids=("tw.daily.ohlcv",),
    dataset_scope_keys=("TAIEX",),
    venue_scope=("TWSE",),
    instrument_types=(InstrumentType.INDEX,),
    intervals=("1d",),
    acquisition_modes=(AcquisitionMode.FETCH,),
    priority=5,
    can_produce_final=True,
    max_timeout_seconds=30,
    max_external_calls_per_attempt=1,
    max_symbols_per_call=1,
    max_range_days=31,
    allow_unknown_health=True,
    limitations=("TAIEX_ONLY", "OFFICIAL_COMPLETED_SESSION_ONLY"),
)


class HttpResponseLike(Protocol):
    status_code: int
    text: str
    headers: Mapping[str, str]
    url: Any


RouteFetcher = Callable[[ProviderResourceRouteV2], HttpResponseLike]


@dataclass(frozen=True)
class TpexOfficial5sParseResult:
    components: tuple[BarObservation, ...]
    formal_close_component: BarObservation


def parse_tpex_official_5s_series(
    raw_text: str,
    *,
    instrument: InstrumentKey,
    fetched_at: datetime,
    content_hash: str,
    expected_trade_date: date,
) -> TpexOfficial5sParseResult:
    """Parse one complete post-close series and its explicit closing match."""

    if instrument != InstrumentKey(
        market=Market.TW,
        symbol="TPEX",
        instrument_type=InstrumentType.INDEX,
        venue="TPEX",
    ):
        raise ValueError("TPEX 5s adapter requires canonical TPEX identity")
    payload = json.loads(raw_text.lstrip("\ufeff"))
    if not isinstance(payload, dict) or str(payload.get("stat") or "").lower() != "ok":
        raise ValueError("TPEX official 5s payload is unavailable")
    payload_date = parse_trade_date(payload.get("date"))
    if payload_date != expected_trade_date:
        raise ValueError("TPEX official 5s payload trade date mismatch")
    table = next(
        (
            item
            for item in payload.get("tables") or ()
            if isinstance(item, dict)
            and "櫃買指數" in (item.get("fields") or ())
            and isinstance(item.get("data"), list)
        ),
        None,
    )
    if table is None:
        raise ValueError("TPEX official 5s index table is missing")
    fields = table["fields"]
    value_index = fields.index("櫃買指數")
    events: list[tuple[datetime, Decimal]] = []
    closing_summary_value: Decimal | None = None
    for row in table["data"]:
        if not isinstance(row, list) or len(row) <= value_index:
            continue
        raw_time = str(row[0] or "").strip()
        if raw_time == "99:99:99":
            parsed_value = as_float(row[value_index])
            closing_summary_value = (
                Decimal(str(parsed_value)) if parsed_value is not None else None
            )
            continue
        parts = raw_time.split(":")
        value = as_float(row[value_index])
        if len(parts) != 3 or value is None:
            continue
        try:
            event_at = datetime.combine(
                expected_trade_date,
                time(*(int(item) for item in parts)),
                tzinfo=TAIWAN_TZ,
            )
        except ValueError:
            continue
        if time(9, 0) < event_at.timetz().replace(tzinfo=None) <= time(13, 30):
            events.append((event_at, Decimal(str(value))))
    events.sort(key=lambda item: item[0])
    if closing_summary_value is None:
        raise ValueError("TPEX official 5s closing summary is missing")
    expected_first = datetime.combine(expected_trade_date, time(9, 0, 5), tzinfo=TAIWAN_TZ)
    expected_last = datetime.combine(expected_trade_date, time(13, 30), tzinfo=TAIWAN_TZ)
    if not events or events[0][0] != expected_first or events[-1][0] != expected_last:
        raise ValueError("TPEX official 5s session boundary is incomplete")
    if any(
        following_at - current_at != timedelta(seconds=5)
        for (current_at, _), (following_at, _) in zip(events, events[1:])
    ):
        raise ValueError("TPEX official 5s session contains a gap")
    components = tuple(
        BarObservation(
            instrument=instrument,
            lineage=SourceLineage(
                provider=tpex.INDEX_5S_PROVIDER,
                source=TPEX_OFFICIAL_5S_COMPONENT_SOURCE,
                authority=AuthorityClass.EXCHANGE,
                raw_contract_version=TPEX_OFFICIAL_5S_PARSER_VERSION,
                event_at=event_at,
                received_at=fetched_at,
                fetched_at=fetched_at,
                content_hash=content_hash,
            ),
            interval="5s",
            start_at=event_at - timedelta(seconds=5),
            end_at=event_at,
            open_price=value,
            high_price=value,
            low_price=value,
            close_price=value,
            volume=None,
            volume_status="not_applicable",
            price_basis="raw",
            finalization=BarFinalization.FINAL,
        )
        for event_at, value in events
    )
    formal_close_at = datetime.combine(
        expected_trade_date,
        time(13, 30),
        tzinfo=TAIWAN_TZ,
    )
    formal_close_component = BarObservation(
        instrument=instrument,
        lineage=SourceLineage(
            provider=tpex.INDEX_5S_PROVIDER,
            source=TPEX_OFFICIAL_5S_COMPONENT_SOURCE,
            authority=AuthorityClass.EXCHANGE,
            raw_contract_version=TPEX_OFFICIAL_5S_PARSER_VERSION,
            event_at=formal_close_at,
            received_at=fetched_at,
            fetched_at=fetched_at,
            content_hash=content_hash,
        ),
        interval="closing_match",
        start_at=formal_close_at - timedelta(seconds=5),
        end_at=formal_close_at,
        open_price=closing_summary_value,
        high_price=closing_summary_value,
        low_price=closing_summary_value,
        close_price=closing_summary_value,
        volume=None,
        volume_status="not_applicable",
        price_basis="raw",
        finalization=BarFinalization.FINAL,
    )
    return TpexOfficial5sParseResult(
        components=components,
        formal_close_component=formal_close_component,
    )


def _header(response: HttpResponseLike, name: str) -> str | None:
    for key, value in response.headers.items():
        if str(key).casefold() == name.casefold():
            return str(value)
    return None


def _health(
    *,
    checked_at: datetime,
    operational: OperationalStatus,
    freshness: EvidenceFreshness,
    detail_code: str,
) -> ProviderResourceHealth:
    return ProviderResourceHealth(
        provider=TAIEX_OFFICIAL_DAILY_PROVIDER,
        market=Market.TW,
        capability="daily.ohlcv",
        enablement=EnablementStatus.ENABLED,
        connection=ConnectionStatus.CONNECTED,
        entitlement=EntitlementStatus.ENTITLED,
        operational=operational,
        freshness=freshness,
        checked_at=checked_at,
        detail_code=detail_code,
    )


def parse_taiex_official_daily_bars(
    raw_text: str,
    *,
    instrument: InstrumentKey,
    fetched_at: datetime,
    content_hash: str,
    from_date: date | None = None,
    to_date: date | None = None,
) -> tuple[BarObservation, ...]:
    if instrument != InstrumentKey(
        market=Market.TW,
        symbol="TAIEX",
        instrument_type=InstrumentType.INDEX,
        venue="TWSE",
    ):
        raise ValueError("TAIEX official daily adapter requires canonical TAIEX identity")
    payload = json.loads(raw_text.lstrip("\ufeff"))
    rows = parse_twse_index_daily_ohlc_rows(payload)
    bars: list[BarObservation] = []
    for row in rows:
        trade_date = row["trade_date"]
        if from_date is not None and trade_date < from_date:
            continue
        if to_date is not None and trade_date > to_date:
            continue
        start_at = datetime.combine(trade_date, time(9), tzinfo=TAIWAN_TZ)
        end_at = datetime.combine(trade_date, time(13, 30), tzinfo=TAIWAN_TZ)
        bars.append(
            BarObservation(
                instrument=instrument,
                lineage=SourceLineage(
                    provider=TAIEX_OFFICIAL_DAILY_PROVIDER,
                    source=TAIEX_OFFICIAL_DAILY_SOURCE,
                    authority=AuthorityClass.EXCHANGE,
                    raw_contract_version=TAIEX_DAILY_PARSER_VERSION,
                    event_at=end_at,
                    fetched_at=fetched_at,
                    content_hash=content_hash,
                ),
                interval="1d",
                start_at=start_at,
                end_at=end_at,
                open_price=Decimal(str(row["open"])),
                high_price=Decimal(str(row["high"])),
                low_price=Decimal(str(row["low"])),
                close_price=Decimal(str(row["close"])),
                volume=None,
                volume_status="not_applicable",
                price_basis="raw",
                finalization=BarFinalization.FINAL,
            )
        )
    return tuple(bars)


class TaiwanIndexDailyBarAcquisitionExecutor:
    """Execute a shared-planned TAIEX daily route without storage ownership."""

    def __init__(
        self,
        *,
        fetcher: RouteFetcher | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._fetcher = fetcher
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def acquire_routes(
        self,
        instrument: InstrumentKey,
        routes: Sequence[ProviderResourceRouteV2],
        *,
        trade_date: date | None = None,
    ) -> BarAcquisitionResult:
        if len(routes) != 1 or routes[0].resource_id != TAIEX_DAILY_RESOURCE_ID:
            raise ValueError("TAIEX daily acquisition requires one planned official route")
        route = routes[0]
        attempted = AcquisitionResourceAttempt(
            provider=route.provider_key,
            resource_id=route.resource_id,
        )
        fetched_at = self._clock()
        try:
            response = (
                self._fetcher(route)
                if self._fetcher is not None
                else twse.get_response(
                    twse.INDEX_DAILY_OHLC_URL,
                    timeout_seconds=route.timeout_seconds,
                    params={
                        "response": "json",
                        "date": (trade_date or fetched_at.date()).strftime("%Y%m%d"),
                    },
                )
            )
            raw_text = str(response.text or "")
            content_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
            receipt = RawFetchReceiptV1(
                provider=TAIEX_OFFICIAL_DAILY_PROVIDER,
                source=TAIEX_OFFICIAL_DAILY_SOURCE,
                resource_id=TAIEX_DAILY_RESOURCE_ID,
                fetched_at=fetched_at,
                method="GET",
                url=str(response.url or twse.INDEX_DAILY_OHLC_URL),
                status_code=int(response.status_code),
                content_type=_header(response, "content-type"),
                content_hash=content_hash,
                raw_text=raw_text,
                parser_version=TAIEX_DAILY_PARSER_VERSION,
                error_message=(
                    None
                    if 200 <= int(response.status_code) < 300
                    else f"HTTP {response.status_code}"
                ),
            )
            if receipt.error_message is not None:
                raise ValueError(receipt.error_message)
            bars = parse_taiex_official_daily_bars(
                raw_text,
                instrument=instrument,
                fetched_at=fetched_at,
                content_hash=content_hash,
                from_date=trade_date,
                to_date=trade_date,
            )
            if not bars:
                raise ValueError("EXPECTED_TRADE_DATE_NOT_OBSERVED")
        except Exception as exc:
            return BarAcquisitionResult(
                summary=AcquisitionSummary(
                    attempted=True,
                    status=AcquisitionStatus.FAILED,
                    providers_attempted=(route.provider_key,),
                    resource_attempts=(attempted,),
                    external_calls=1,
                    limitations=(
                        "TAIEX_OFFICIAL_DAILY_ACQUISITION_FAILED",
                        f"PROVIDER_ERROR_{type(exc).__name__.upper()}",
                    ),
                ),
                provider_health=(
                    _health(
                        checked_at=fetched_at,
                        operational=OperationalStatus.FAILED,
                        freshness=EvidenceFreshness.MISSING,
                        detail_code="TAIEX_OFFICIAL_DAILY_ACQUISITION_FAILED",
                    ),
                ),
            )
        return BarAcquisitionResult(
            summary=AcquisitionSummary(
                attempted=True,
                status=AcquisitionStatus.COMPLETED,
                providers_attempted=(route.provider_key,),
                resource_attempts=(attempted,),
                external_calls=1,
                limitations=tuple(route.limitations),
            ),
            observations=bars,
            receipts=(receipt,),
            provider_health=(
                _health(
                    checked_at=fetched_at,
                    operational=OperationalStatus.HEALTHY,
                    freshness=EvidenceFreshness.FRESH,
                    detail_code="TAIEX_OFFICIAL_DAILY_OBSERVED",
                ),
            ),
        )


__all__ = [
    "TAIEX_DAILY_PARSER_VERSION",
    "TAIEX_DAILY_RESOURCE_ID",
    "TAIEX_OFFICIAL_DAILY_DESCRIPTOR",
    "TpexOfficial5sParseResult",
    "TaiwanIndexDailyBarAcquisitionExecutor",
    "parse_tpex_official_5s_series",
    "parse_taiex_official_daily_bars",
]
