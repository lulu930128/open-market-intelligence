from __future__ import annotations

from dataclasses import dataclass
from typing import Any


CRYPTO_PRIORITY_CORE = "core"
CRYPTO_PRIORITY_MAJOR = "major"
CRYPTO_PRIORITY_REFERENCE = "reference"

SUBSCRIPTION_ALWAYS_ON = "always_on"
SUBSCRIPTION_ON_SELECT = "on_select"


@dataclass(frozen=True)
class CryptoAssetDefinition:
    asset: str
    name: str
    coin_id: str | None
    priority: str
    default_subscription_mode: str
    local_twd_provider_symbol: str | None = None
    binance_spot: bool = True
    okx_spot: bool = True
    binance_perpetual: bool = True
    okx_perpetual: bool = True
    market_cap: bool = True
    taiwan_spread: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset": self.asset,
            "name": self.name,
            "coin_id": self.coin_id,
            "priority": self.priority,
            "default_subscription_mode": self.default_subscription_mode,
            "local_twd_provider_symbol": self.local_twd_provider_symbol,
            "resources": {
                "local_twd": self.local_twd_provider_symbol is not None,
                "binance_spot": self.binance_spot,
                "okx_spot": self.okx_spot,
                "binance_perpetual": self.binance_perpetual,
                "okx_perpetual": self.okx_perpetual,
                "market_cap": self.market_cap,
                "taiwan_spread": self.taiwan_spread,
            },
        }


CRYPTO_ASSET_REGISTRY: tuple[CryptoAssetDefinition, ...] = (
    CryptoAssetDefinition(
        asset="BTC",
        name="Bitcoin",
        coin_id="bitcoin",
        priority=CRYPTO_PRIORITY_CORE,
        default_subscription_mode=SUBSCRIPTION_ALWAYS_ON,
        local_twd_provider_symbol="btc_twd",
        taiwan_spread=True,
    ),
    CryptoAssetDefinition(
        asset="ETH",
        name="Ethereum",
        coin_id="ethereum",
        priority=CRYPTO_PRIORITY_CORE,
        default_subscription_mode=SUBSCRIPTION_ON_SELECT,
        local_twd_provider_symbol="eth_twd",
        taiwan_spread=True,
    ),
    CryptoAssetDefinition(
        asset="USDT",
        name="Tether",
        coin_id="tether",
        priority=CRYPTO_PRIORITY_REFERENCE,
        default_subscription_mode=SUBSCRIPTION_ON_SELECT,
        local_twd_provider_symbol="usdt_twd",
        binance_spot=False,
        okx_spot=False,
        binance_perpetual=False,
        okx_perpetual=False,
    ),
    CryptoAssetDefinition(
        asset="SOL",
        name="Solana",
        coin_id="solana",
        priority=CRYPTO_PRIORITY_MAJOR,
        default_subscription_mode=SUBSCRIPTION_ON_SELECT,
    ),
    CryptoAssetDefinition(
        asset="BNB",
        name="BNB",
        coin_id="binancecoin",
        priority=CRYPTO_PRIORITY_MAJOR,
        default_subscription_mode=SUBSCRIPTION_ON_SELECT,
    ),
    CryptoAssetDefinition(
        asset="XRP",
        name="XRP",
        coin_id="ripple",
        priority=CRYPTO_PRIORITY_MAJOR,
        default_subscription_mode=SUBSCRIPTION_ON_SELECT,
    ),
    CryptoAssetDefinition(
        asset="DOGE",
        name="Dogecoin",
        coin_id="dogecoin",
        priority=CRYPTO_PRIORITY_MAJOR,
        default_subscription_mode=SUBSCRIPTION_ON_SELECT,
    ),
    CryptoAssetDefinition(
        asset="TON",
        name="Toncoin",
        coin_id="the-open-network",
        priority=CRYPTO_PRIORITY_MAJOR,
        default_subscription_mode=SUBSCRIPTION_ON_SELECT,
        okx_spot=False,
        binance_perpetual=False,
    ),
    CryptoAssetDefinition(
        asset="LINK",
        name="Chainlink",
        coin_id="chainlink",
        priority=CRYPTO_PRIORITY_MAJOR,
        default_subscription_mode=SUBSCRIPTION_ON_SELECT,
    ),
)


def list_crypto_assets() -> list[CryptoAssetDefinition]:
    return list(CRYPTO_ASSET_REGISTRY)


def get_crypto_asset(asset: str) -> CryptoAssetDefinition | None:
    normalized = str(asset or "").strip().upper()
    return next(
        (definition for definition in CRYPTO_ASSET_REGISTRY if definition.asset == normalized),
        None,
    )


def crypto_asset_codes() -> tuple[str, ...]:
    return tuple(definition.asset for definition in CRYPTO_ASSET_REGISTRY)


def coin_ids_by_asset() -> dict[str, str]:
    return {
        definition.asset: definition.coin_id
        for definition in CRYPTO_ASSET_REGISTRY
        if definition.coin_id and definition.market_cap
    }


def taiwan_spread_assets() -> tuple[str, ...]:
    return tuple(
        definition.asset
        for definition in CRYPTO_ASSET_REGISTRY
        if definition.taiwan_spread
    )
