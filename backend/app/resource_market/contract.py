from __future__ import annotations

from dataclasses import dataclass
from typing import Any


RESOURCE_MARKET = "resource"
COMMODITY_FOLDER = "commodity"
PROVIDER_PENDING = "provider_pending"
YAHOO_CHART_PROVIDER = "yahoo_chart"
PROVIDER_BEST_EFFORT = "best_effort_delayed"
FUTURES = "futures"
SUPPORTED_RESOURCE_OHLCV_INTERVALS = ("1m", "5m", "15m", "30m", "1h", "1d", "1w", "1M")
RESOURCE_CHART_PROFILES = {
    "overview": {
        "default_interval": "1m",
        "intervals": ["1m", "1d", "1w", "1M"],
    },
    "professional": {
        "default_interval": "1m",
        "intervals": list(SUPPORTED_RESOURCE_OHLCV_INTERVALS),
    },
}


@dataclass(frozen=True)
class ResourceInstrument:
    key: str
    root_folder: str
    group: str
    asset_class: str
    name: str
    display_name: str
    symbol: str
    provider: str
    exchange: str
    provider_symbol: str
    base_asset: str
    quote_asset: str
    instrument_type: str
    contract_type: str
    resources: tuple[str, ...]
    tradable: bool
    trade_candidate: bool
    provider_status: str
    role: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "root_folder": self.root_folder,
            "group": self.group,
            "asset_class": self.asset_class,
            "name": self.name,
            "display_name": self.display_name,
            "symbol": self.symbol,
            "provider": self.provider,
            "exchange": self.exchange,
            "provider_symbol": self.provider_symbol,
            "base_asset": self.base_asset,
            "quote_asset": self.quote_asset,
            "instrument_type": self.instrument_type,
            "contract_type": self.contract_type,
            "resources": list(self.resources),
            "tradable": self.tradable,
            "trade_candidate": self.trade_candidate,
            "provider_status": self.provider_status,
            "role": self.role,
        }


SUPPORTED_RESOURCE_INSTRUMENTS: tuple[ResourceInstrument, ...] = (
    ResourceInstrument(
        key="commodity:metals:GC",
        root_folder=COMMODITY_FOLDER,
        group="metals",
        asset_class="commodity_futures",
        name="Gold Futures",
        display_name="黃金",
        symbol="GC",
        provider=YAHOO_CHART_PROVIDER,
        exchange="COMEX",
        provider_symbol="GC=F",
        base_asset="GOLD",
        quote_asset="USD",
        instrument_type=FUTURES,
        contract_type="front_month",
        resources=("quote", "ohlcv"),
        tradable=False,
        trade_candidate=False,
        provider_status=PROVIDER_BEST_EFFORT,
        role="Gold futures watch-only Yahoo chart context; delayed/best-effort.",
    ),
    ResourceInstrument(
        key="commodity:metals:SI",
        root_folder=COMMODITY_FOLDER,
        group="metals",
        asset_class="commodity_futures",
        name="Silver Futures",
        display_name="白銀",
        symbol="SI",
        provider=YAHOO_CHART_PROVIDER,
        exchange="COMEX",
        provider_symbol="SI=F",
        base_asset="SILVER",
        quote_asset="USD",
        instrument_type=FUTURES,
        contract_type="front_month",
        resources=("quote", "ohlcv"),
        tradable=False,
        trade_candidate=False,
        provider_status=PROVIDER_BEST_EFFORT,
        role="Silver futures watch-only Yahoo chart context; delayed/best-effort.",
    ),
    ResourceInstrument(
        key="commodity:metals:HG",
        root_folder=COMMODITY_FOLDER,
        group="metals",
        asset_class="commodity_futures",
        name="Copper Futures",
        display_name="銅",
        symbol="HG",
        provider=YAHOO_CHART_PROVIDER,
        exchange="COMEX",
        provider_symbol="HG=F",
        base_asset="COPPER",
        quote_asset="USD",
        instrument_type=FUTURES,
        contract_type="front_month",
        resources=("quote", "ohlcv"),
        tradable=False,
        trade_candidate=False,
        provider_status=PROVIDER_BEST_EFFORT,
        role="Copper futures watch-only Yahoo chart context; delayed/best-effort.",
    ),
    ResourceInstrument(
        key="commodity:energy:CL",
        root_folder=COMMODITY_FOLDER,
        group="energy",
        asset_class="commodity_futures",
        name="WTI Crude Oil Futures",
        display_name="WTI 原油",
        symbol="CL",
        provider=YAHOO_CHART_PROVIDER,
        exchange="NYMEX",
        provider_symbol="CL=F",
        base_asset="WTI_CRUDE",
        quote_asset="USD",
        instrument_type=FUTURES,
        contract_type="front_month",
        resources=("quote", "ohlcv"),
        tradable=False,
        trade_candidate=False,
        provider_status=PROVIDER_BEST_EFFORT,
        role="WTI crude oil futures watch-only Yahoo chart context; delayed/best-effort.",
    ),
    ResourceInstrument(
        key="commodity:energy:BZ",
        root_folder=COMMODITY_FOLDER,
        group="energy",
        asset_class="commodity_futures",
        name="Brent Crude Oil Futures",
        display_name="Brent 原油",
        symbol="BZ",
        provider=YAHOO_CHART_PROVIDER,
        exchange="NYMEX",
        provider_symbol="BZ=F",
        base_asset="BRENT_CRUDE",
        quote_asset="USD",
        instrument_type=FUTURES,
        contract_type="front_month",
        resources=("quote", "ohlcv"),
        tradable=False,
        trade_candidate=False,
        provider_status=PROVIDER_BEST_EFFORT,
        role="Brent crude oil futures watch-only Yahoo chart context; delayed/best-effort.",
    ),
    ResourceInstrument(
        key="commodity:energy:NG",
        root_folder=COMMODITY_FOLDER,
        group="energy",
        asset_class="commodity_futures",
        name="Henry Hub Natural Gas Futures",
        display_name="天然氣",
        symbol="NG",
        provider=YAHOO_CHART_PROVIDER,
        exchange="NYMEX",
        provider_symbol="NG=F",
        base_asset="NATURAL_GAS",
        quote_asset="USD",
        instrument_type=FUTURES,
        contract_type="front_month",
        resources=("quote", "ohlcv"),
        tradable=False,
        trade_candidate=False,
        provider_status=PROVIDER_BEST_EFFORT,
        role="Natural gas futures watch-only Yahoo chart context; delayed/best-effort.",
    ),
)


def normalize_resource_symbol(value: str | None) -> str:
    return (value or "").strip().upper().replace("/", "-").replace("_", "-")


def list_resource_instruments(
    *,
    root_folder: str | None = None,
    group: str | None = None,
    symbol: str | None = None,
) -> list[ResourceInstrument]:
    normalized_root = (root_folder or "").strip().lower() or None
    normalized_group = (group or "").strip().lower() or None
    normalized_symbol = normalize_resource_symbol(symbol) if symbol else None

    instruments: list[ResourceInstrument] = []
    for instrument in SUPPORTED_RESOURCE_INSTRUMENTS:
        if normalized_root and instrument.root_folder != normalized_root:
            continue
        if normalized_group and instrument.group != normalized_group:
            continue
        if normalized_symbol and instrument.symbol != normalized_symbol:
            continue
        instruments.append(instrument)
    return instruments


def resource_provider_contract() -> dict[str, Any]:
    return {
        "kind": "resource_market_contract",
        "market": RESOURCE_MARKET,
        "execution_enabled": False,
        "ai_execution_enabled": False,
        "trade_candidate_symbols": [],
        "notes": [
            "Resource/commodity data is watch-only and must not place orders.",
            "BTC is the only current future trade candidate and remains in the isolated crypto domain.",
            "GET endpoints read the local cache or static contract only; Yahoo chart refresh is behind explicit bounded POST routes.",
        ],
        "root_folders": [
            {
                "key": "crypto",
                "label": "虛擬貨幣",
                "notes": "Crypto data domain; BTC is the only future trade candidate.",
            },
            {
                "key": COMMODITY_FOLDER,
                "label": "商品",
                "notes": "Watch-only resource futures context.",
            },
        ],
        "providers": {
            YAHOO_CHART_PROVIDER: {
                "role": "Best-effort delayed commodity futures reference from Yahoo chart.",
                "resources": ["quote", "ohlcv"],
                "ohlcv_intervals": list(SUPPORTED_RESOURCE_OHLCV_INTERVALS),
                "status": PROVIDER_BEST_EFFORT,
            },
        },
        "ohlcv_intervals": {
            YAHOO_CHART_PROVIDER: list(SUPPORTED_RESOURCE_OHLCV_INTERVALS),
        },
        "chart_profiles": RESOURCE_CHART_PROFILES,
        "instruments": [instrument.to_dict() for instrument in SUPPORTED_RESOURCE_INSTRUMENTS],
    }
