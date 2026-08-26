"""Explicit ownership/classification for Taiwan outward sidecar surfaces.

The shared dataset registry remains the executable lifecycle authority for
canonical datasets.  This module only closes the inventory gap for outward
surfaces that are either represented by several catalog datasets or still use
an explicitly non-canonical compatibility cache.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TaiwanSidecarClassification(str, Enum):
    DATASET_CATALOG = "dataset_catalog"
    COMPATIBILITY_CACHE = "compatibility_cache"


@dataclass(frozen=True, slots=True)
class TaiwanSidecarContract:
    surface_id: str
    route_paths: tuple[str, ...]
    dataset_ids: tuple[str, ...]
    classification: TaiwanSidecarClassification
    owner: str
    read_operations: tuple[str, ...]
    refresh_operations: tuple[str, ...]
    read_external_io: bool
    read_writes_storage: bool
    refresh_external_io: bool
    storage_owner: str
    lineage_status: str
    health_owner: str
    ai_decision_usable: bool
    limitations: tuple[str, ...] = ()


TAIWAN_SIDECAR_CONTRACTS = (
    TaiwanSidecarContract(
        surface_id="tw.disposition",
        route_paths=(
            "/api/market/tw-dispositions",
            "/api/market/tw-dispositions/refresh",
        ),
        dataset_ids=(),
        classification=TaiwanSidecarClassification.COMPATIBILITY_CACHE,
        owner="app.market.tw_disposition",
        read_operations=("app.market.tw_disposition.list_taiwan_dispositions",),
        refresh_operations=("app.market.tw_disposition.refresh_taiwan_dispositions",),
        read_external_io=False,
        read_writes_storage=False,
        refresh_external_io=True,
        storage_owner="settings.tw_disposition_cache_path",
        lineage_status="source_raw_compatibility",
        health_owner="compatibility_payload.provider_status",
        ai_decision_usable=False,
        limitations=(
            "NOT_SHARED_DATASET_LIFECYCLE",
            "NO_RAW_FETCH_RESULT_LINEAGE",
            "PRESENTATION_AND_EVENT_CONTEXT_ONLY",
        ),
    ),
    TaiwanSidecarContract(
        surface_id="tw.institutional_holding_ratio",
        route_paths=(
            "/api/market/institutional/{stock_id}/holding-ratios",
            "/api/market/institutional/{stock_id}/holding-ratios/refresh",
        ),
        dataset_ids=(),
        classification=TaiwanSidecarClassification.COMPATIBILITY_CACHE,
        owner="app.market.institutional_holding_ratio_cache",
        read_operations=(
            "app.market.institutional_holding_ratio_cache.read_cached_institutional_holding_ratios",
        ),
        refresh_operations=(
            "app.market.institutional_holding_ratio_cache.refresh_cached_institutional_holding_ratios",
        ),
        read_external_io=False,
        read_writes_storage=False,
        refresh_external_io=True,
        storage_owner="settings.tw_institutional_holding_ratio_cache_path",
        lineage_status="raw_receipt_not_persisted",
        health_owner="compatibility_payload.cache_status",
        ai_decision_usable=False,
        limitations=(
            "NOT_SHARED_DATASET_LIFECYCLE",
            "NO_RAW_FETCH_RESULT_LINEAGE",
            "CANONICAL_TRUTH_FALSE",
        ),
    ),
    TaiwanSidecarContract(
        surface_id="tw.corporate_events",
        route_paths=(
            "/api/market/tw-corporate-events",
            "/api/market/tw-corporate-events/history/{stock_id}",
            "/api/market/tw-corporate-events/refresh",
            "/api/market/tw-corporate-events/history/backfill",
        ),
        dataset_ids=("tw.events.corporate",),
        classification=TaiwanSidecarClassification.DATASET_CATALOG,
        owner="app.market.tw_corporate_events",
        read_operations=(
            "app.market.tw_corporate_events.list_taiwan_corporate_events",
            "app.market.tw_corporate_events.get_taiwan_stock_event_history",
        ),
        refresh_operations=(
            "app.market.tw_corporate_events.refresh_taiwan_corporate_events",
            "app.market.tw_corporate_events.backfill_taiwan_corporate_event_history",
        ),
        read_external_io=False,
        read_writes_storage=False,
        refresh_external_io=True,
        storage_owner="TaiwanCorporateEvent",
        lineage_status="lineage_gap",
        health_owner="app.market.tw_dataset_health.read_taiwan_dataset_platform_projection",
        ai_decision_usable=False,
        limitations=("CATALOG_LINEAGE_GAP",),
    ),
    TaiwanSidecarContract(
        surface_id="tw.etf",
        route_paths=(
            "/api/market/etfs/{stock_id}/overview",
            "/api/market/etfs/{stock_id}/refresh",
        ),
        dataset_ids=(
            "tw.etf.profile",
            "tw.etf.nav.daily",
            "tw.etf.pcf.snapshot",
            "tw.etf.inav.snapshot",
        ),
        classification=TaiwanSidecarClassification.DATASET_CATALOG,
        owner="app.market.tw_etf",
        read_operations=("app.market.tw_etf.get_taiwan_etf_overview",),
        refresh_operations=("app.market.tw_etf.refresh_taiwan_etf",),
        read_external_io=False,
        read_writes_storage=False,
        refresh_external_io=True,
        storage_owner="Taiwan ETF typed tables",
        lineage_status="lineage_gap",
        health_owner="app.market.tw_dataset_health.read_taiwan_dataset_platform_projection",
        ai_decision_usable=False,
        limitations=("CATALOG_LINEAGE_GAP", "COMPONENT_HEALTH_MUST_REMAIN_SPLIT"),
    ),
    TaiwanSidecarContract(
        surface_id="tw.futures_derivatives",
        route_paths=(
            "/api/market/tw-futures/products",
            "/api/market/tw-futures/refresh",
            "/api/market/tw-futures/latest",
            "/api/market/tw-futures/derivatives/refresh",
            "/api/market/tw-futures/options-chain",
            "/api/market/tw-futures/large-traders",
            "/api/market/tw-futures/term-structure",
            "/api/market/tw-futures/{symbol}/daily",
            "/api/market/tw-futures/{symbol}/daily/refresh",
            "/api/market/tw-futures/{symbol}/intraday",
            "/api/market/tw-futures/{symbol}/intraday/refresh",
        ),
        dataset_ids=(
            "tw.futures.quote.snapshot",
            "tw.futures.intraday.bars",
            "tw.futures.daily.bars",
            "tw.derivatives.option_chain.daily",
            "tw.derivatives.large_trader.daily",
            "tw.derivatives.term_structure.daily",
        ),
        classification=TaiwanSidecarClassification.DATASET_CATALOG,
        owner="app.market.tw_futures + app.market.tw_derivatives",
        read_operations=(
            "app.market.tw_futures.get_latest_taiwan_futures_quotes",
            "app.market.tw_futures.list_taiwan_futures_intraday_bars",
            "app.market.tw_futures.list_taiwan_futures_daily_bars",
            "app.market.tw_derivatives.list_taiwan_option_chain",
            "app.market.tw_derivatives.list_taiwan_large_traders",
            "app.market.tw_derivatives.list_taiwan_term_structure",
        ),
        refresh_operations=(
            "app.market.tw_futures.refresh_taiwan_futures_quotes",
            "app.market.tw_futures.refresh_taiwan_futures_intraday_bars",
            "app.market.tw_futures.refresh_taiwan_futures_daily_bars",
            "app.market.tw_derivatives.refresh_taiwan_derivatives",
        ),
        read_external_io=False,
        read_writes_storage=False,
        refresh_external_io=True,
        storage_owner="Taiwan futures and derivatives typed tables",
        lineage_status="lineage_gap",
        health_owner="app.market.tw_dataset_health.read_taiwan_dataset_platform_projection",
        ai_decision_usable=False,
        limitations=(
            "CATALOG_LINEAGE_GAP",
            "LEGACY_TRANSACTION_OWNER",
            "PROVIDER_QUERY_PARAMETERS_ARE_DEPRECATED_AND_NON_AUTHORITATIVE",
        ),
    ),
)


TAIWAN_SIDECAR_BY_ID = {
    contract.surface_id: contract for contract in TAIWAN_SIDECAR_CONTRACTS
}


__all__ = [
    "TAIWAN_SIDECAR_BY_ID",
    "TAIWAN_SIDECAR_CONTRACTS",
    "TaiwanSidecarClassification",
    "TaiwanSidecarContract",
]
