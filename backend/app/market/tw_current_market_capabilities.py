"""Market-owned provider descriptors for Taiwan current-session aggregates."""

from __future__ import annotations

from dataclasses import dataclass

from app.market_data.contracts import AuthorityClass, Market, MarketSession
from app.market_data.provider_catalog import (
    AcquisitionMode,
    DescriptorTargetKind,
    ProviderCapabilityDescriptorV2,
)


TW_CURRENT_INDEX_DATASET_ID = "tw.market_index.current"
TW_CURRENT_BREADTH_DATASET_ID = "tw.market_breadth.current"
TW_CURRENT_INDEX_CAPABILITY_ID = "market.index.snapshot"
TW_CURRENT_BREADTH_CAPABILITY_ID = "market.breadth.current"


@dataclass(frozen=True, slots=True)
class TaiwanCurrentSourceBinding:
    descriptor: ProviderCapabilityDescriptorV2
    source: str
    parser_version: str
    source_type: str = "api"
    auth_type: str = "none"


def _descriptor(
    *,
    provider: str,
    capability: str,
    dataset: str,
    resource: str,
    authority: AuthorityClass,
    scopes: tuple[str, ...],
    priority: int,
    live: bool,
    sessions: tuple[MarketSession, ...],
    limitations: tuple[str, ...],
) -> ProviderCapabilityDescriptorV2:
    return ProviderCapabilityDescriptorV2(
        provider_key=provider,
        market=Market.TW,
        capability_id=capability,
        resource_id=resource,
        authority=authority,
        target_kinds=(DescriptorTargetKind.DATASET,),
        dataset_ids=(dataset,),
        dataset_scope_keys=scopes,
        venue_scope=("TWSE", "TPEX"),
        supported_sessions=sessions,
        acquisition_modes=(AcquisitionMode.FETCH,),
        priority=priority,
        can_produce_live=live,
        can_produce_final=False,
        max_timeout_seconds=20,
        max_external_calls_per_attempt=1,
        max_symbols_per_call=1,
        max_range_days=1,
        health_ttl_seconds=60,
        allow_unknown_health=True,
        limitations=limitations,
    )


_LIVE_SESSIONS = (
    MarketSession.PRE_OPEN,
    MarketSession.OPENING_AUCTION,
    MarketSession.CONTINUOUS,
    MarketSession.CLOSING_AUCTION,
    MarketSession.POST_CLOSE,
    MarketSession.UNKNOWN,
)

TWSE_MIS_CURRENT_INDEX_DESCRIPTOR = _descriptor(
    provider="twse_mis",
    capability=TW_CURRENT_INDEX_CAPABILITY_ID,
    dataset=TW_CURRENT_INDEX_DATASET_ID,
    resource="tw.twse_mis.index.snapshot",
    authority=AuthorityClass.EXCHANGE,
    scopes=("TAIEX", "TPEX"),
    priority=10,
    live=True,
    sessions=_LIVE_SESSIONS,
    limitations=("PUBLIC_BEST_EFFORT_NO_SLA", "SNAPSHOT_NOT_BAR_SERIES"),
)

YAHOO_CURRENT_INDEX_DESCRIPTOR = _descriptor(
    provider="yahoo_finance_chart",
    capability=TW_CURRENT_INDEX_CAPABILITY_ID,
    dataset=TW_CURRENT_INDEX_DATASET_ID,
    resource="tw.yahoo.index.snapshot",
    authority=AuthorityClass.VENDOR,
    scopes=("TAIEX", "TPEX"),
    priority=20,
    live=False,
    sessions=_LIVE_SESSIONS,
    limitations=("VENDOR_DELAY_POSSIBLE", "INDEX_VOLUME_NOT_MARKET_VALUE"),
)

TWSE_MIS_CURRENT_BREADTH_DESCRIPTOR = _descriptor(
    provider="twse_mis",
    capability=TW_CURRENT_BREADTH_CAPABILITY_ID,
    dataset=TW_CURRENT_BREADTH_DATASET_ID,
    resource="tw.twse_mis.breadth.current",
    authority=AuthorityClass.EXCHANGE,
    scopes=("TWSE", "TPEX"),
    priority=10,
    live=True,
    sessions=_LIVE_SESSIONS,
    limitations=("PUBLIC_BEST_EFFORT_NO_SLA", "COVERAGE_MAY_BE_PARTIAL"),
)

TW_CURRENT_INDEX_DESCRIPTORS = (
    TWSE_MIS_CURRENT_INDEX_DESCRIPTOR,
    YAHOO_CURRENT_INDEX_DESCRIPTOR,
)
TW_CURRENT_BREADTH_DESCRIPTORS = (TWSE_MIS_CURRENT_BREADTH_DESCRIPTOR,)

TW_CURRENT_SOURCE_BINDINGS = (
    TaiwanCurrentSourceBinding(
        descriptor=TWSE_MIS_CURRENT_INDEX_DESCRIPTOR,
        source="twse_mis_index_snapshot",
        parser_version="twse_mis.index.snapshot.v1",
    ),
    TaiwanCurrentSourceBinding(
        descriptor=YAHOO_CURRENT_INDEX_DESCRIPTOR,
        source="yahoo_finance_chart",
        parser_version="yahoo.chart.index.snapshot.v1",
    ),
    TaiwanCurrentSourceBinding(
        descriptor=TWSE_MIS_CURRENT_BREADTH_DESCRIPTOR,
        source="twse_mis_live_breadth",
        parser_version="twse_mis.breadth.current.v1",
    ),
)


def current_source_binding(
    *,
    provider: str,
    source: str,
    capability_id: str | None = None,
) -> TaiwanCurrentSourceBinding | None:
    for binding in TW_CURRENT_SOURCE_BINDINGS:
        if (
            binding.descriptor.provider_key == provider
            and binding.source == source
            and (
                capability_id is None
                or binding.descriptor.capability_id == capability_id
            )
        ):
            return binding
    return None


__all__ = [
    "TW_CURRENT_BREADTH_CAPABILITY_ID",
    "TW_CURRENT_BREADTH_DATASET_ID",
    "TW_CURRENT_BREADTH_DESCRIPTORS",
    "TW_CURRENT_INDEX_CAPABILITY_ID",
    "TW_CURRENT_INDEX_DATASET_ID",
    "TW_CURRENT_INDEX_DESCRIPTORS",
    "TWSE_MIS_CURRENT_BREADTH_DESCRIPTOR",
    "TWSE_MIS_CURRENT_INDEX_DESCRIPTOR",
    "TaiwanCurrentSourceBinding",
    "YAHOO_CURRENT_INDEX_DESCRIPTOR",
    "current_source_binding",
]
