from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


CAPABILITY_REGISTRY_VERSION = "omi.capability.registry.v3"
CAPABILITY_SELECTION_VERSION = "omi.capability.selection.v2"


@dataclass(frozen=True)
class TargetSpec:
    target_type: str
    title: str
    description: str
    internal_scope: str
    markets: tuple[str, ...] = ()
    requires_id: bool = False
    deprecated: bool = False
    replacement_target: str | None = None

    def as_public_dict(self) -> dict[str, Any]:
        return asdict(self)


TARGET_SPECS = (
    TargetSpec(
        "auto",
        "Automatic target resolution",
        "Let the OMI backend resolve one explicit target from the request.",
        "auto",
    ),
    TargetSpec(
        "market",
        "Market",
        "One market-level context. Taiwan uses market=TW.",
        "market",
        ("TW", "US", "JP", "KR"),
    ),
    TargetSpec(
        "data_freshness",
        "Data freshness",
        "Dataset freshness and expected-date diagnostics for one market or all markets.",
        "data_freshness",
        ("TW", "US", "JP", "KR", "CRYPTO", "ALL"),
    ),
    TargetSpec(
        "tw_stock",
        "Taiwan security",
        "One Taiwan listed or OTC security.",
        "stock",
        ("TW",),
        True,
    ),
    TargetSpec(
        "tw_watchlist",
        "Taiwan watchlist",
        "One private Taiwan watchlist group.",
        "watchlist",
        ("TW",),
        True,
    ),
    TargetSpec(
        "tw_index",
        "Taiwan index",
        "One supported Taiwan market index.",
        "tw_index",
        ("TW",),
        True,
    ),
    TargetSpec(
        "tw_futures",
        "Taiwan futures",
        "One supported Taiwan futures product.",
        "tw_futures",
        ("TW",),
        True,
    ),
    TargetSpec(
        "us_stock",
        "United States security",
        "One United States listed security or supported index symbol.",
        "us_stock",
        ("US",),
        True,
    ),
    TargetSpec(
        "jp_stock",
        "Japan security",
        "One Japan listed security.",
        "jp_stock",
        ("JP",),
        True,
    ),
    TargetSpec(
        "jp_index",
        "Japan index",
        "One supported Japan market index.",
        "jp_index",
        ("JP",),
        True,
    ),
    TargetSpec(
        "kr_stock",
        "Korea security",
        "One Korea listed security.",
        "kr_stock",
        ("KR",),
        True,
    ),
    TargetSpec(
        "kr_index",
        "Korea index",
        "One supported Korea market index.",
        "kr_index",
        ("KR",),
        True,
    ),
    TargetSpec(
        "crypto_market",
        "Crypto market",
        "Aggregate crypto market context.",
        "crypto_market",
        ("CRYPTO",),
    ),
    TargetSpec(
        "crypto_asset",
        "Crypto asset",
        "One supported crypto asset.",
        "crypto_asset",
        ("CRYPTO",),
        True,
    ),
    TargetSpec(
        "resource_asset",
        "Resource asset",
        "One supported commodity, rate, or FX resource.",
        "resource_asset",
        ("RESOURCE",),
        True,
    ),
    TargetSpec(
        "portfolio",
        "Portfolio",
        "The trusted caller's saved OMI portfolio.",
        "portfolio",
    ),
    TargetSpec(
        "us_macro",
        "United States macro series",
        "One supported United States macroeconomic series.",
        "us_macro",
        ("US",),
        True,
    ),
    TargetSpec(
        "us_watchlist",
        "United States watchlist",
        "One private United States watchlist.",
        "us_watchlist",
        ("US",),
        True,
    ),
    TargetSpec(
        "jp_watchlist",
        "Japan watchlist",
        "One private Japan watchlist.",
        "jp_watchlist",
        ("JP",),
        True,
    ),
    TargetSpec(
        "kr_watchlist",
        "Korea watchlist",
        "One private Korea watchlist.",
        "kr_watchlist",
        ("KR",),
        True,
    ),
    TargetSpec(
        "source_health",
        "Source health",
        "Provider and source-health diagnostics.",
        "source_health",
    ),
    TargetSpec(
        "capability_status",
        "Capability status",
        "Public capability registry and readiness diagnostics.",
        "capability_status",
    ),
)

TARGETS = {spec.target_type: spec for spec in TARGET_SPECS}
PUBLIC_TARGET_TYPES = tuple(spec.target_type for spec in TARGET_SPECS)
TARGET_TYPE_TO_INTERNAL_SCOPE = {
    spec.target_type: spec.internal_scope
    for spec in TARGET_SPECS
    if spec.target_type != "auto"
}
INTERNAL_SCOPE_TO_TARGET_TYPE = {
    spec.internal_scope: spec.target_type
    for spec in TARGET_SPECS
    if spec.target_type != "auto"
}


def target_catalog() -> list[dict[str, Any]]:
    return [spec.as_public_dict() for spec in TARGET_SPECS]
