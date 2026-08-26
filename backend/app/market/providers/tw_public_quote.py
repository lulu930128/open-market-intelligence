"""TWSE MIS public quote descriptor and pure payload conversion."""

from __future__ import annotations

from datetime import datetime
import json
from typing import Any

from app.market.providers import twse_mis
from app.market.providers.twse_mis_canonical import (
    canonical_snapshot_from_twse_mis,
)
from app.market.tw_public_quote_contract import (
    TW_PUBLIC_LAST_TRADE_CAPABILITY_ID,
    TWSE_MIS_QUOTE_PROVIDER,
    TWSE_MIS_QUOTE_RESOURCE_ID,
    TWSE_MIS_QUOTE_SOURCE_NAME,
    exchange_channel_for_quote,
)
from app.market_data.contracts import (
    AuthorityClass,
    InstrumentKey,
    InstrumentType,
    Market,
    MarketSession,
    QuoteObservation,
)
from app.market_data.provider_catalog import (
    AcquisitionMode,
    DescriptorTargetKind,
    ProviderCapabilityDescriptorV2,
)


TWSE_MIS_QUOTE_PARSER_VERSION = "twse.mis.getStockInfo.v1"


TWSE_MIS_PUBLIC_QUOTE_DESCRIPTOR = ProviderCapabilityDescriptorV2(
    provider_key=TWSE_MIS_QUOTE_PROVIDER,
    market=Market.TW,
    capability_id=TW_PUBLIC_LAST_TRADE_CAPABILITY_ID,
    resource_id=TWSE_MIS_QUOTE_RESOURCE_ID,
    authority=AuthorityClass.EXCHANGE,
    target_kinds=(DescriptorTargetKind.INSTRUMENT,),
    venue_scope=("TWSE", "TPEX"),
    instrument_types=(InstrumentType.STOCK, InstrumentType.ETF),
    supported_sessions=(
        MarketSession.PRE_OPEN,
        MarketSession.OPENING_AUCTION,
        MarketSession.CONTINUOUS,
        MarketSession.CLOSING_AUCTION,
    ),
    acquisition_modes=(AcquisitionMode.FETCH,),
    priority=10,
    can_produce_live=True,
    can_produce_final=False,
    max_timeout_seconds=10,
    max_external_calls_per_attempt=1,
    max_subscriptions_per_attempt=0,
    max_symbols_per_call=1,
    max_range_days=1,
    health_ttl_seconds=30,
    allow_unknown_health=True,
    limitations=(
        "PUBLIC_BEST_EFFORT_NO_SLA",
        "SINGLE_SYMBOL_ONLY",
    ),
)


def exchange_code_for_venue(venue: str | None) -> str:
    normalized = str(venue or "").strip().upper()
    if normalized == "TWSE":
        return "tse"
    if normalized == "TPEX":
        return "otc"
    raise ValueError("TWSE MIS quote venue must be TWSE or TPEX")


def channel_for_instrument(instrument: InstrumentKey) -> str:
    return exchange_channel_for_quote(instrument)


def endpoint_for_instrument(instrument: InstrumentKey) -> str:
    return (
        f"{twse_mis.STOCK_INFO_URL}?ex_ch={channel_for_instrument(instrument)}"
        "&json=1&delay=0"
    )


def parse_twse_mis_quote_payload(
    raw_text: str,
    *,
    target_symbol: str,
) -> dict[str, Any]:
    try:
        payload = json.loads(raw_text)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("TWSE MIS quote payload is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("TWSE MIS quote payload root must be an object")
    rtcode = str(payload.get("rtcode") or "")
    if rtcode not in {"", "0000"}:
        raise ValueError(f"TWSE MIS quote rtcode is not successful: {rtcode}")
    messages = payload.get("msgArray")
    if not isinstance(messages, list):
        raise ValueError("TWSE MIS quote payload msgArray must be a list")
    normalized_symbol = str(target_symbol or "").strip().upper()
    matches = [
        message
        for message in messages
        if isinstance(message, dict)
        and str(message.get("c") or "").strip().upper() == normalized_symbol
    ]
    if not matches:
        raise ValueError("TWSE MIS quote target symbol is missing")
    if len(matches) != 1:
        raise ValueError("TWSE MIS quote target symbol is duplicated")
    return matches[0]


def quote_observation_from_twse_mis(
    *,
    instrument: InstrumentKey,
    message: dict[str, Any],
    session: MarketSession,
    received_at: datetime,
    fetched_at: datetime,
    content_hash: str,
) -> QuoteObservation:
    snapshot = canonical_snapshot_from_twse_mis(
        instrument=instrument,
        message=message,
        session=session,
        fetched_at=fetched_at,
        expected_trade_date=None,
    )
    if snapshot.quote is None:
        raise ValueError("TWSE MIS canonical snapshot did not contain a quote")
    if snapshot.quote.trade_date is None or snapshot.quote.lineage.event_at is None:
        raise ValueError("TWSE MIS quote requires provider trade date and event time")
    return snapshot.quote.model_copy(
        update={
            "lineage": snapshot.quote.lineage.model_copy(
                update={
                    "source": TWSE_MIS_QUOTE_SOURCE_NAME,
                    "raw_contract_version": TWSE_MIS_QUOTE_PARSER_VERSION,
                    "received_at": received_at,
                    "fetched_at": fetched_at,
                    "content_hash": content_hash,
                }
            )
        }
    )


__all__ = [
    "TWSE_MIS_PUBLIC_QUOTE_DESCRIPTOR",
    "TWSE_MIS_QUOTE_PARSER_VERSION",
    "channel_for_instrument",
    "endpoint_for_instrument",
    "exchange_code_for_venue",
    "parse_twse_mis_quote_payload",
    "quote_observation_from_twse_mis",
]
