"""Stable identities and venue mapping for the Taiwan public quote capability."""

from app.market_data.contracts import InstrumentKey, Market

TW_PUBLIC_QUOTE_DATASET_ID = "tw.quote.snapshot"
TW_PUBLIC_LAST_TRADE_CAPABILITY_ID = "quote.last_trade"
TWSE_MIS_QUOTE_PROVIDER = "twse_mis"
TWSE_MIS_QUOTE_RESOURCE_ID = "twse_mis.stock_info"
TWSE_MIS_QUOTE_SOURCE_NAME = "twse_mis_quote_depth"


def exchange_channel_for_quote(instrument: InstrumentKey) -> str:
    """Return the exchange channel without importing provider I/O into storage."""

    if instrument.market is not Market.TW:
        raise ValueError("Taiwan public quote requires market=TW")
    venue = str(instrument.venue or "").strip().upper()
    if venue == "TWSE":
        exchange = "tse"
    elif venue == "TPEX":
        exchange = "otc"
    else:
        raise ValueError("Taiwan public quote venue must be TWSE or TPEX")
    return f"{exchange}_{instrument.symbol}.tw"


__all__ = [
    "TW_PUBLIC_LAST_TRADE_CAPABILITY_ID",
    "TW_PUBLIC_QUOTE_DATASET_ID",
    "TWSE_MIS_QUOTE_PROVIDER",
    "TWSE_MIS_QUOTE_RESOURCE_ID",
    "TWSE_MIS_QUOTE_SOURCE_NAME",
    "exchange_channel_for_quote",
]
