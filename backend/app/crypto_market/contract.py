from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.crypto_market.assets import (
    CryptoAssetDefinition,
    coin_ids_by_asset,
    list_crypto_assets,
)


CRYPTO_MARKET = "crypto"
BITOPRO_PROVIDER = "bitopro"
BINANCE_PROVIDER = "binance"
OKX_PROVIDER = "okx"
COINGECKO_PROVIDER = "coingecko"
COINGLASS_PROVIDER = "coinglass"
BYBIT_PROVIDER = "bybit"
OMI_LOCAL_PROVIDER = "omi_local"

SPOT = "spot"
PERPETUAL = "perpetual"

OHLCV_INTERVALS_BY_PROVIDER: dict[str, tuple[str, ...]] = {
    BITOPRO_PROVIDER: ("1m", "5m", "15m", "30m", "1h", "3h", "4h", "6h", "12h", "1d", "1w", "1M"),
    BINANCE_PROVIDER: ("1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "1w", "1M"),
    OKX_PROVIDER: ("1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w", "1M"),
}


@dataclass(frozen=True)
class ProviderInstrument:
    provider: str
    exchange: str
    symbol: str
    provider_symbol: str
    base_asset: str
    quote_asset: str
    instrument_type: str
    resources: tuple[str, ...]
    role: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "exchange": self.exchange,
            "symbol": self.symbol,
            "provider_symbol": self.provider_symbol,
            "base_asset": self.base_asset,
            "quote_asset": self.quote_asset,
            "instrument_type": self.instrument_type,
            "resources": list(self.resources),
            "role": self.role,
        }


def _global_symbol(asset: CryptoAssetDefinition) -> str:
    return f"{asset.asset}-USDT"


def _global_spot_resources(asset: CryptoAssetDefinition) -> tuple[str, ...]:
    resources = ["ticker", "order_book", "ohlcv"]
    if asset.taiwan_spread:
        resources.append("spread")
    return tuple(resources)


def _local_twd_resources(asset: CryptoAssetDefinition) -> tuple[str, ...]:
    if asset.asset == "USDT":
        return ("ticker", "order_book", "ohlcv", "fx")
    return ("ticker", "order_book", "ohlcv", "spread")


def _build_supported_instruments() -> tuple[ProviderInstrument, ...]:
    instruments: list[ProviderInstrument] = []
    for asset in list_crypto_assets():
        if asset.local_twd_provider_symbol:
            instruments.append(
                ProviderInstrument(
                    provider=BITOPRO_PROVIDER,
                    exchange="BitoPro",
                    symbol=f"{asset.asset}-TWD",
                    provider_symbol=asset.local_twd_provider_symbol,
                    base_asset=asset.asset,
                    quote_asset="TWD",
                    instrument_type=SPOT,
                    resources=_local_twd_resources(asset),
                    role=(
                        "Local USDT/TWD conversion reference for Taiwan premium calculations."
                        if asset.asset == "USDT"
                        else f"Taiwan-dollar {asset.asset} price and local premium observation."
                    ),
                )
            )
        if asset.binance_spot:
            instruments.append(
                ProviderInstrument(
                    provider=BINANCE_PROVIDER,
                    exchange="Binance",
                    symbol=_global_symbol(asset),
                    provider_symbol=f"{asset.asset}USDT",
                    base_asset=asset.asset,
                    quote_asset="USDT",
                    instrument_type=SPOT,
                    resources=_global_spot_resources(asset),
                    role=f"Global high-liquidity {asset.asset}/USDT spot reference.",
                )
            )
        if asset.binance_perpetual:
            instruments.append(
                ProviderInstrument(
                    provider=BINANCE_PROVIDER,
                    exchange="Binance Futures",
                    symbol=_global_symbol(asset),
                    provider_symbol=f"{asset.asset}USDT",
                    base_asset=asset.asset,
                    quote_asset="USDT",
                    instrument_type=PERPETUAL,
                    resources=("derivatives", "liquidation_event", "long_short_ratio"),
                    role=f"Global {asset.asset} perpetual funding, mark/index price, and open interest.",
                )
            )
        if asset.okx_spot:
            instruments.append(
                ProviderInstrument(
                    provider=OKX_PROVIDER,
                    exchange="OKX",
                    symbol=_global_symbol(asset),
                    provider_symbol=_global_symbol(asset),
                    base_asset=asset.asset,
                    quote_asset="USDT",
                    instrument_type=SPOT,
                    resources=_global_spot_resources(asset),
                    role=f"Secondary global {asset.asset}/USDT spot reference.",
                )
            )
        if asset.okx_perpetual:
            instruments.append(
                ProviderInstrument(
                    provider=OKX_PROVIDER,
                    exchange="OKX Swap",
                    symbol=_global_symbol(asset),
                    provider_symbol=f"{_global_symbol(asset)}-SWAP",
                    base_asset=asset.asset,
                    quote_asset="USDT",
                    instrument_type=PERPETUAL,
                    resources=("derivatives",),
                    role=f"Secondary {asset.asset} perpetual funding and open-interest reference.",
                )
            )
    return tuple(instruments)


SUPPORTED_INSTRUMENTS = _build_supported_instruments()

COINGECKO_COIN_IDS = coin_ids_by_asset()


def normalize_provider(value: str | None) -> str:
    return (value or "").strip().lower()


def normalize_symbol(value: str | None) -> str:
    cleaned = (value or "").strip().upper().replace("/", "-").replace("_", "-")
    parts = [part for part in cleaned.split("-") if part]
    if len(parts) == 2:
        return f"{parts[0]}-{parts[1]}"
    return cleaned


def normalize_instrument_type(value: str | None = None) -> str:
    normalized = (value or SPOT).strip().lower()
    if normalized in {"swap", "perp"}:
        return PERPETUAL
    return normalized or SPOT


def list_provider_instruments(
    *,
    provider: str | None = None,
    symbol: str | None = None,
    instrument_type: str | None = None,
    resource: str | None = None,
) -> list[ProviderInstrument]:
    normalized_provider = normalize_provider(provider) if provider else None
    normalized_symbol = normalize_symbol(symbol) if symbol else None
    normalized_instrument = normalize_instrument_type(instrument_type) if instrument_type else None
    normalized_resource = (resource or "").strip().lower() or None

    instruments = []
    for instrument in SUPPORTED_INSTRUMENTS:
        if normalized_provider and instrument.provider != normalized_provider:
            continue
        if normalized_symbol and instrument.symbol != normalized_symbol:
            continue
        if normalized_instrument and instrument.instrument_type != normalized_instrument:
            continue
        if normalized_resource and normalized_resource not in instrument.resources:
            continue
        instruments.append(instrument)
    return instruments


def get_provider_instrument(
    *,
    provider: str,
    symbol: str,
    instrument_type: str = SPOT,
    resource: str | None = None,
) -> ProviderInstrument:
    matches = list_provider_instruments(
        provider=provider,
        symbol=symbol,
        instrument_type=instrument_type,
        resource=resource,
    )
    if not matches:
        raise ValueError(
            "Unsupported crypto provider/symbol/instrument combination: "
            f"provider={provider}, symbol={symbol}, instrument_type={instrument_type}, resource={resource or 'any'}."
        )
    return matches[0]


def ohlcv_intervals_for_provider(provider: str) -> tuple[str, ...]:
    return OHLCV_INTERVALS_BY_PROVIDER.get(normalize_provider(provider), ())


def provider_supports_ohlcv_interval(provider: str, interval: str) -> bool:
    normalized_interval = (interval or "").strip()
    return normalized_interval in ohlcv_intervals_for_provider(provider)


def split_symbol(symbol: str) -> tuple[str, str]:
    normalized = normalize_symbol(symbol)
    parts = normalized.split("-", maxsplit=1)
    if len(parts) != 2:
        raise ValueError(f"Invalid crypto symbol: {symbol}")
    return parts[0], parts[1]


def _unique_instrument_symbols(provider: str) -> list[str]:
    symbols: list[str] = []
    for instrument in SUPPORTED_INSTRUMENTS:
        if instrument.provider != provider:
            continue
        if instrument.symbol not in symbols:
            symbols.append(instrument.symbol)
    return symbols


def provider_contract() -> dict[str, Any]:
    return {
        "kind": "crypto_provider_contract",
        "market": CRYPTO_MARKET,
        "execution_enabled": False,
        "ai_execution_enabled": False,
        "notes": [
            "GET endpoints read local cache only; POST refresh endpoints fetch market data and update cache.",
            "No order placement endpoint is part of this contract.",
            "CoinGecko is ranking and market-cap context only, not an execution price source.",
            "Liquidation heatmap, CVD, and long/short ratio resources are backend-ready but disabled until their providers are connected.",
        ],
        "providers": {
            BITOPRO_PROVIDER: {
                "role": "Taiwan-dollar spot prices and Taiwan exchange premium/discount observation.",
                "resources": ["ticker", "order_book", "ohlcv", "spread", "fx"],
                "canonical_symbols": _unique_instrument_symbols(BITOPRO_PROVIDER),
                "ohlcv_intervals": list(ohlcv_intervals_for_provider(BITOPRO_PROVIDER)),
            },
            BINANCE_PROVIDER: {
                "role": "Global high-liquidity spot and USD-M perpetual reference.",
                "resources": [
                    "ticker",
                    "order_book",
                    "ohlcv",
                    "derivatives",
                    "spread",
                    "liquidation_event",
                    "cvd",
                    "long_short_ratio",
                ],
                "canonical_symbols": _unique_instrument_symbols(BINANCE_PROVIDER),
                "ohlcv_intervals": list(ohlcv_intervals_for_provider(BINANCE_PROVIDER)),
            },
            OKX_PROVIDER: {
                "role": "Secondary global spot and swap reference.",
                "resources": ["ticker", "order_book", "ohlcv", "derivatives", "spread"],
                "canonical_symbols": _unique_instrument_symbols(OKX_PROVIDER),
                "ohlcv_intervals": list(ohlcv_intervals_for_provider(OKX_PROVIDER)),
            },
            COINGECKO_PROVIDER: {
                "role": "Coin rank, market cap, and 24h leaderboard context.",
                "resources": ["market_cap", "ranking"],
                "canonical_assets": list(COINGECKO_COIN_IDS),
            },
            COINGLASS_PROVIDER: {
                "role": "Third-party processed liquidation heatmap context. Requires explicit provider setup.",
                "resources": ["liquidation_heatmap"],
                "status": "api_key_required",
            },
            OMI_LOCAL_PROVIDER: {
                "role": "Local fallback for estimated liquidation heatmap buckets built from stored liquidation events.",
                "resources": ["liquidation_heatmap"],
                "status": "fallback",
            },
            BYBIT_PROVIDER: {
                "role": "Optional derivatives confirmation source for account ratio and future liquidation/CVD coverage.",
                "resources": ["long_short_ratio", "liquidation_event", "cvd"],
                "status": "provider_pending",
            },
        },
        "ohlcv_intervals": {
            provider: list(intervals)
            for provider, intervals in OHLCV_INTERVALS_BY_PROVIDER.items()
        },
        "assets": [asset.to_dict() for asset in list_crypto_assets()],
        "instruments": [instrument.to_dict() for instrument in SUPPORTED_INSTRUMENTS],
        "coin_ids": dict(COINGECKO_COIN_IDS),
    }
