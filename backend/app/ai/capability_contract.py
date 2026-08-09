from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
import hashlib
import json
from typing import Any

from app.ai import public_contract


OUTPUT_MODES = {"evidence_only", "decision", "decision_with_evidence"}
REALTIME_POLICIES = {"cache_only", "prefer_live", "require_live"}
DIAGNOSTIC_SCOPES = {
    "capability_status",
    "data_freshness",
    "source_health",
}
MIN_RESPONSE_BYTES = 4_096
MAX_RESPONSE_BYTES = 1_048_576
MAX_CAPABILITY_LIMIT = 500
DEFAULT_RESPONSE_BYTES = {
    "summary": 16_384,
    "compact": 32_768,
    "standard": 131_072,
    "full": 524_288,
}

READY_STATUSES = {
    "available",
    "current",
    "daily_close",
    "fresh",
    "historical",
    "latest_completed_session",
    "latest_session_close",
    "live",
    "ok",
    "ready",
}
LIMITED_STATUSES = {"cached", "delayed", "partial", "pending", "waiting"}
NEUTRAL_STATUSES = {"not_applicable", "not_requested"}
EXECUTABLE_FILL_OPERATIONS = {
    "tw.refresh_daily_price",
    "tw.refresh_institutional",
    "tw.refresh_margin",
    "tw.refresh_broker_branch",
    "tw.refresh_shareholding",
    "tw.refresh_revenue",
    "tw.refresh_financials",
    "us.read_intraday_trend",
    "us.refresh_daily_price",
    "us.refresh_sec_facts",
    "jp.read_intraday_trend",
    "jp.refresh_daily_price",
    "kr.read_stock_intraday_trend",
    "kr.read_index_intraday_trend",
    "kr.refresh_daily_price",
    "kr.refresh_index_daily_price",
    "crypto.refresh_ticker",
    "crypto.refresh_ohlcv",
    "crypto.refresh_order_book",
    "crypto.refresh_derivatives",
}
FILL_OPERATION_PRODUCED_CAPABILITIES: dict[str, tuple[str, ...]] = {
    "tw.refresh_daily_price": ("daily.ohlcv",),
    "tw.refresh_institutional": ("chips.institutional",),
    "tw.refresh_margin": ("chips.margin",),
    "tw.refresh_broker_branch": ("broker_branch.summary",),
    "tw.refresh_shareholding": ("ownership.distribution",),
    "tw.refresh_revenue": ("fundamentals.revenue",),
    "tw.refresh_financials": ("fundamentals.financials",),
    "us.read_intraday_trend": ("quote.snapshot", "intraday.bars"),
    "us.refresh_daily_price": ("daily.ohlcv",),
    "us.refresh_sec_facts": ("fundamentals.financials",),
    "jp.read_intraday_trend": ("quote.snapshot", "intraday.bars"),
    "jp.refresh_daily_price": ("daily.ohlcv",),
    "kr.read_stock_intraday_trend": ("quote.snapshot", "intraday.bars"),
    "kr.read_index_intraday_trend": ("quote.snapshot", "intraday.bars"),
    "kr.refresh_daily_price": ("daily.ohlcv",),
    "kr.refresh_index_daily_price": ("daily.ohlcv",),
    "crypto.refresh_ticker": ("quote.snapshot",),
    "crypto.refresh_ohlcv": ("intraday.bars", "daily.ohlcv"),
    "crypto.refresh_order_book": ("crypto.order_book",),
    "crypto.refresh_derivatives": ("crypto.derivatives",),
}
FILL_OPERATIONS_WRITING_CACHE = {
    "tw.refresh_daily_price",
    "tw.refresh_institutional",
    "tw.refresh_margin",
    "tw.refresh_broker_branch",
    "tw.refresh_shareholding",
    "tw.refresh_revenue",
    "tw.refresh_financials",
    "us.refresh_daily_price",
    "us.refresh_sec_facts",
    "jp.refresh_daily_price",
    "kr.read_stock_intraday_trend",
    "kr.refresh_daily_price",
    "kr.refresh_index_daily_price",
    "crypto.refresh_ticker",
    "crypto.refresh_ohlcv",
    "crypto.refresh_order_book",
    "crypto.refresh_derivatives",
}


@dataclass(frozen=True)
class CapabilitySpec:
    capability_id: str
    domain: str | None
    slot: str | None
    scopes: tuple[str, ...]
    paths: tuple[str, ...]
    fields: tuple[str, ...]
    default_fields: tuple[str, ...]
    default_limit: int
    schema_version: str = "omi.capability.v1"
    fill_operations: tuple[tuple[str, str], ...] = ()
    writes_cache: bool = False
    title: str = ""
    description: str = ""
    markets: tuple[str, ...] = ()
    parameter_schema: dict[str, Any] = field(default_factory=dict)
    frequency: str = "request"
    unit_semantics: str = "field_defined"
    event_time_basis: str = "capability_defined"
    deprecated: bool = False
    replacement_capabilities: tuple[str, ...] = ()
    side_effect_policy: str = "read_only"
    refresh_strategies: tuple[tuple[str, str], ...] = ()
    refresh_requires_market_open_scopes: tuple[str, ...] = ()

    def as_public_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["title"] = self.title or self.capability_id
        payload["description"] = (
            self.description
            or f"Canonical OMI capability {self.capability_id}."
        )
        payload["parameter_schema"] = (
            dict(self.parameter_schema)
            if self.parameter_schema
            else {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            }
        )
        payload["fill_operations"] = {
            scope: operation for scope, operation in self.fill_operations
        }
        payload["refresh_strategies"] = {
            scope: strategy for scope, strategy in self.refresh_strategies
        }
        return payload

    def fill_operation_for_scope(self, scope_type: str) -> str | None:
        return dict(self.fill_operations).get(scope_type)

    def refresh_strategy_for_scope(self, scope_type: str) -> str:
        explicit = dict(self.refresh_strategies).get(scope_type)
        if explicit:
            return explicit
        if self.fill_operation_for_scope(scope_type):
            return "granular_tool"
        if "scheduler_owned" in self.side_effect_policy:
            return "scheduler_owned"
        if "cache" in self.side_effect_policy:
            return "cache_only"
        return "derived"

    def refresh_requires_market_open_for_scope(self, scope_type: str) -> bool:
        return scope_type in self.refresh_requires_market_open_scopes


ALL_STOCK_SCOPES = ("stock", "us_stock", "jp_stock", "kr_stock")
ALL_MARKET_SCOPES = (
    "market",
    "tw_index",
    "tw_futures",
    "us_stock",
    "jp_index",
    "kr_index",
    "crypto_market",
)
ALL_INSTRUMENT_SCOPES = (
    *ALL_STOCK_SCOPES,
    "tw_index",
    "tw_futures",
    "jp_index",
    "kr_index",
    "crypto_asset",
    "resource_asset",
)


CAPABILITY_SPECS: tuple[CapabilitySpec, ...] = (
    CapabilitySpec(
        capability_id="target.identity",
        domain=None,
        slot="identity",
        scopes=("*",),
        paths=("target", "compact.target", "data.target"),
        fields=("type", "id", "label", "market", "exchange", "instrument_type"),
        default_fields=("type", "id", "label", "market", "exchange", "instrument_type"),
        default_limit=1,
    ),
    CapabilitySpec(
        capability_id="quote.snapshot",
        schema_version="tw.quote.snapshot.v2",
        domain="quote",
        slot="quote",
        scopes=(*ALL_INSTRUMENT_SCOPES, "crypto_market"),
        paths=("compact.quote", "data.quote"),
        fields=(
            "kind",
            "status",
            "price",
            "latest_price",
            "last_price",
            "price_available",
            "last_trade_available",
            "last_trade_price",
            "last_trade_time",
            "last_trade_is_current_session",
            "last_trade_before_auction",
            "facts_usable_for_current_session",
            "fallback_quote",
            "fallback_used",
            "previous_close",
            "previous_close_trade_date",
            "open_price",
            "high_price",
            "low_price",
            "change",
            "change_pct",
            "currency",
            "price_unit",
            "volume",
            "volume_unit",
            "volume_semantics",
            "volume_status",
            "canonical_volume_unit",
            "provider_volume_unit",
            "trade_value",
            "trade_value_unit",
            "trade_value_status",
            "trade_value_source",
            "total_volume_lots",
            "total_volume_contracts",
            "cumulative_volume_lots",
            "cumulative_volume_shares",
            "last_trade_volume_lots",
            "last_trade_volume_shares",
            "lot_size",
            "volume_scope",
            "volume_source",
            "volume_source_field",
            "provider_volume_available",
            "last_trade_volume_semantics",
            "last_trade_volume_source_field",
            "last_trade_volume_status",
            "official_daily_volume_shares",
            "official_daily_volume_trade_date",
            "official_daily_volume_source",
            "official_daily_volume_scope",
            "volume_reconciliation",
            "volume_decision_usable",
            "price_decision_usable",
            "volume_includes_odd_lot",
            "volume_includes_after_hours",
            "volume_includes_closing_auction",
            "bid",
            "ask",
            "best_bid_price",
            "best_bid_size_lots",
            "best_ask_price",
            "best_ask_size_lots",
            "spread",
            "spread_pct",
            "bid_levels",
            "ask_levels",
            "bid_depth",
            "ask_depth",
            "top5_bid_volume_lots",
            "top5_ask_volume_lots",
            "top5_imbalance",
            "depth_volume_unit",
            "depth_order_count_status",
            "trade_date",
            "quote_time",
            "quote_time_basis",
            "snapshot_time",
            "snapshot_time_basis",
            "provider_event_time",
            "event_time",
            "release_at",
            "fetched_at",
            "computed_at",
            "refresh_outcome",
            "received_at",
            "served_at",
            "event_age_seconds",
            "provider_delay_ms",
            "network_latency_ms",
            "source",
            "provider",
            "primary_provider",
            "selected_provider",
            "fallback_used",
            "fallback_provider",
            "fallback_reason",
            "provider_attempts",
            "source_grade",
            "cache_hit",
            "cache_written",
            "currency",
            "price_unit",
            "score_unit",
            "market_status",
            "session_phase",
            "quote_semantics",
            "is_historical",
            "requested_trade_date",
            "regular_session_close",
            "regular_session_close_time",
            "regular_session_close_trade_date",
            "delivery_status",
            "is_live",
            "is_realtime",
            "is_current_session_quote",
            "is_latest_session_quote",
            "age_seconds",
            "quote_age_seconds",
            "latency_ms",
            "latency_ms_semantics",
            "depth_available",
            "depth_status",
            "auction_book_available",
            "auction_book_status",
            "auction_book_time",
            "auction_best_bid",
            "auction_best_ask",
            "auction_indicative_available",
            "indicative_match_available",
            "indicative_match_price",
            "indicative_match_volume_lots",
            "indicative_unmatched_buy_volume_lots",
            "indicative_unmatched_sell_volume_lots",
            "indicative_unmatched_status",
            "indicative_price_available",
            "indicative_price",
            "indicative_bid",
            "indicative_ask",
            "official_close_available",
            "official_close_status",
            "official_close_price",
            "official_close_trade_date",
            "official_close_source",
            "official_close_raw",
            "official_close_display",
            "official_close_precision",
            "official_vwap",
            "approx_vwap",
            "vwap_method",
            "vwap_confidence",
            "selected_candidate",
            "selection_reason",
            "quote_candidates",
            "freshness",
            "timezone",
        ),
        default_fields=(
            "status",
            "price",
            "latest_price",
            "last_price",
            "price_available",
            "last_trade_available",
            "last_trade_price",
            "last_trade_time",
            "last_trade_is_current_session",
            "last_trade_before_auction",
            "facts_usable_for_current_session",
            "fallback_quote",
            "fallback_used",
            "previous_close",
            "open_price",
            "high_price",
            "low_price",
            "change",
            "change_pct",
            "currency",
            "price_unit",
            "volume",
            "volume_unit",
            "volume_semantics",
            "volume_status",
            "canonical_volume_unit",
            "provider_volume_unit",
            "trade_value",
            "trade_value_unit",
            "trade_value_status",
            "trade_value_source",
            "total_volume_lots",
            "total_volume_contracts",
            "cumulative_volume_lots",
            "cumulative_volume_shares",
            "last_trade_volume_lots",
            "last_trade_volume_shares",
            "lot_size",
            "volume_scope",
            "volume_source",
            "volume_source_field",
            "provider_volume_available",
            "last_trade_volume_semantics",
            "last_trade_volume_source_field",
            "last_trade_volume_status",
            "official_daily_volume_shares",
            "official_daily_volume_trade_date",
            "official_daily_volume_source",
            "official_daily_volume_scope",
            "volume_reconciliation",
            "volume_decision_usable",
            "price_decision_usable",
            "bid",
            "ask",
            "best_bid_price",
            "best_ask_price",
            "spread",
            "bid_levels",
            "ask_levels",
            "bid_depth",
            "ask_depth",
            "top5_bid_volume_lots",
            "top5_ask_volume_lots",
            "top5_imbalance",
            "depth_volume_unit",
            "depth_order_count_status",
            "trade_date",
            "quote_time",
            "quote_time_basis",
            "snapshot_time",
            "snapshot_time_basis",
            "provider_event_time",
            "event_time",
            "release_at",
            "fetched_at",
            "computed_at",
            "received_at",
            "served_at",
            "event_age_seconds",
            "provider_delay_ms",
            "network_latency_ms",
            "source",
            "provider",
            "primary_provider",
            "selected_provider",
            "fallback_provider",
            "fallback_reason",
            "provider_attempts",
            "source_grade",
            "cache_hit",
            "cache_written",
            "currency",
            "price_unit",
            "score_unit",
            "market_status",
            "session_phase",
            "quote_semantics",
            "is_historical",
            "requested_trade_date",
            "regular_session_close",
            "regular_session_close_time",
            "regular_session_close_trade_date",
            "delivery_status",
            "is_live",
            "is_realtime",
            "is_current_session_quote",
            "is_latest_session_quote",
            "quote_age_seconds",
            "latency_ms",
            "latency_ms_semantics",
            "depth_available",
            "depth_status",
            "auction_book_available",
            "auction_book_status",
            "auction_book_time",
            "auction_best_bid",
            "auction_best_ask",
            "auction_indicative_available",
            "indicative_match_available",
            "indicative_match_price",
            "indicative_match_volume_lots",
            "indicative_unmatched_buy_volume_lots",
            "indicative_unmatched_sell_volume_lots",
            "indicative_unmatched_status",
            "indicative_price_available",
            "indicative_price",
            "indicative_bid",
            "indicative_ask",
            "official_close_available",
            "official_close_status",
            "official_close_price",
            "official_close_trade_date",
            "official_close_source",
            "official_close_raw",
            "official_close_display",
            "official_close_precision",
            "official_vwap",
            "approx_vwap",
            "vwap_method",
            "vwap_confidence",
            "selected_candidate",
            "selection_reason",
            "quote_candidates",
            "freshness",
            "timezone",
        ),
        default_limit=5,
        fill_operations=(
            ("us_stock", "us.read_intraday_trend"),
            ("jp_stock", "jp.read_intraday_trend"),
            ("jp_index", "jp.read_intraday_trend"),
            ("kr_stock", "kr.read_stock_intraday_trend"),
            ("kr_index", "kr.read_index_intraday_trend"),
            ("crypto_asset", "crypto.refresh_ticker"),
        ),
        refresh_strategies=(("stock", "reader_fetch"),),
        refresh_requires_market_open_scopes=("stock",),
    ),
    CapabilitySpec(
        capability_id="quote.order_book",
        domain="quote",
        slot="quote_order_book",
        scopes=("stock",),
        paths=(
            "compact.quote.components.order_book",
            "data.quote.components.order_book",
        ),
        fields=(
            "kind",
            "status",
            "available",
            "best_bid_price",
            "best_bid_size_lots",
            "best_ask_price",
            "best_ask_size_lots",
            "spread",
            "spread_pct",
            "bid_levels",
            "ask_levels",
            "top5_bid_volume_lots",
            "top5_ask_volume_lots",
            "top5_imbalance",
            "volume_unit",
            "order_count_status",
            "snapshot_time",
            "snapshot_time_basis",
            "provider_event_time",
            "fetched_at",
            "latency_ms",
            "provider",
            "source",
            "freshness",
            "quantity_unit",
            "lot_size",
        ),
        default_fields=(
            "status",
            "available",
            "best_bid_price",
            "best_bid_size_lots",
            "best_ask_price",
            "best_ask_size_lots",
            "spread",
            "spread_pct",
            "bid_levels",
            "ask_levels",
            "top5_bid_volume_lots",
            "top5_ask_volume_lots",
            "top5_imbalance",
            "volume_unit",
            "order_count_status",
            "snapshot_time",
            "provider_event_time",
            "latency_ms",
            "provider",
            "source",
            "freshness",
            "quantity_unit",
            "lot_size",
        ),
        default_limit=5,
        refresh_strategies=(("stock", "reader_fetch"),),
        refresh_requires_market_open_scopes=("stock",),
        title="Taiwan quote order book",
        description=(
            "Taiwan five-level order book with provider event time, latency, "
            "spread, and top-five imbalance. Last-trade availability is not "
            "required for this component to be current."
        ),
        markets=("TW",),
        frequency="intraday",
        unit_semantics="prices_and_lots",
        event_time_basis="provider_event_time",
    ),
    CapabilitySpec(
        capability_id="quote.auction",
        domain="quote",
        slot="quote_auction",
        scopes=("stock", "tw_index"),
        paths=(
            "compact.quote.components.auction",
            "data.quote.components.auction",
        ),
        fields=(
            "kind",
            "status",
            "available",
            "applicability_status",
            "availability_status",
            "unavailable_reason_code",
            "market_session_status",
            "refresh_possible_now",
            "refresh_recommended",
            "session_phase",
            "auction_time",
            "best_bid",
            "best_ask",
            "indicative_available",
            "indicative_match_available",
            "indicative_match_price",
            "indicative_match_volume_lots",
            "unmatched_buy_volume_lots",
            "unmatched_sell_volume_lots",
            "unmatched_status",
            "trading_mode",
            "analysis_basis",
            "batch_interval_minutes",
            "next_batch_time",
            "provider_event_time",
            "latency_ms",
            "provider",
            "source",
            "freshness",
            "quantity_unit",
            "lot_size",
        ),
        default_fields=(
            "status",
            "available",
            "applicability_status",
            "availability_status",
            "unavailable_reason_code",
            "market_session_status",
            "refresh_possible_now",
            "refresh_recommended",
            "session_phase",
            "auction_time",
            "best_bid",
            "best_ask",
            "indicative_available",
            "indicative_match_available",
            "indicative_match_price",
            "indicative_match_volume_lots",
            "unmatched_buy_volume_lots",
            "unmatched_sell_volume_lots",
            "unmatched_status",
            "trading_mode",
            "analysis_basis",
            "batch_interval_minutes",
            "next_batch_time",
            "provider_event_time",
            "latency_ms",
            "provider",
            "source",
            "freshness",
            "quantity_unit",
            "lot_size",
        ),
        default_limit=5,
        refresh_strategies=(("stock", "reader_fetch"),),
        refresh_requires_market_open_scopes=("stock",),
        title="Taiwan quote auction state",
        description=(
            "Taiwan pre-open, closing, or disposition batch-auction state. "
            "An auction book can be current while the last trade is unavailable."
        ),
        markets=("TW",),
        frequency="intraday",
        unit_semantics="prices_lots_and_minutes",
        event_time_basis="provider_event_time",
    ),
    CapabilitySpec(
        capability_id="quote.official_close",
        domain="quote",
        slot="quote_official_close",
        scopes=("stock", "tw_index"),
        paths=(
            "compact.quote.components.official_close",
            "data.quote.components.official_close",
        ),
        fields=(
            "kind",
            "status",
            "available",
            "price",
            "trade_date",
            "source",
            "raw",
            "display",
            "precision",
            "quote_semantics",
            "delivery_status",
            "freshness",
        ),
        default_fields=(
            "status",
            "available",
            "price",
            "trade_date",
            "source",
            "raw",
            "display",
            "precision",
            "quote_semantics",
            "delivery_status",
            "freshness",
        ),
        default_limit=1,
        refresh_strategies=(("stock", "reader_fetch"),),
        title="Taiwan official close",
        description=(
            "Confirmed Taiwan stock or index close with explicit availability, "
            "source, display precision, and completed-session date semantics."
        ),
        markets=("TW",),
        frequency="daily",
        unit_semantics="index_or_security_price",
        event_time_basis="taiwan_completed_trade_date",
    ),
    CapabilitySpec(
        capability_id="intraday.bars",
        schema_version="tw.intraday.bars.v2",
        domain="intraday",
        slot="intraday",
        scopes=(*ALL_INSTRUMENT_SCOPES, "market", "crypto_market"),
        paths=(
            "compact.intraday_bars",
            "compact.index_intraday",
            "compact.intraday_chart",
            "data.intraday_bars",
            "data.index_intraday",
            "compact.intraday",
            "data.intraday",
            "data.ohlcv",
        ),
        fields=(
            "as_of",
            "enabled",
            "kind",
            "payload_level",
            "date",
            "interval",
            "requested_interval",
            "source_interval",
            "effective_interval",
            "interval_status",
            "sampling_mode",
            "original_point_count",
            "session",
            "session_scope",
            "session_phase",
            "market_status",
            "official_close_status",
            "delivery_status",
            "is_current_session",
            "point_count",
            "returned_point_count",
            "truncated",
            "bar_limit",
            "index_ids",
            "indices",
            "points",
            "bars",
            "latest_point",
            "series",
            "bar_time",
            "open_price",
            "high_price",
            "low_price",
            "close_price",
            "base_volume",
            "base_volume_unit",
            "volume_unit",
            "volume_contracts",
            "volume_event_time",
            "cumulative_volume",
            "cumulative_volume_unit",
            "cumulative_volume_contracts",
            "lot_size",
            "trade_value_unit",
            "quote_volume",
            "quote_volume_unit",
            "currency",
            "price_unit",
            "event_time",
            "fetched_at",
            "received_at",
            "source",
            "provider",
            "freshness",
            "warnings",
            "is_partial",
            "continuity",
            "volume_semantics",
            "volume_status",
            "volume_shares",
            "volume_lots",
            "canonical_volume_unit",
            "provider_volume_unit",
            "volume_conversion",
            "cumulative_volume_shares",
            "cumulative_volume_lots",
            "cumulative_trade_value",
            "available_cumulative_trade_value",
            "estimated_cumulative_trade_value",
            "trade_value_status",
            "official_vwap",
            "approx_vwap",
            "vwap_method",
            "vwap_confidence",
            "bar_close_time",
            "elapsed_seconds",
            "finalized",
            "bar_type",
            "synthetic",
            "indicator_eligible",
            "session_phase",
            "market_event",
            "source_event_type",
            "gap_reason",
            "partial_bar_count",
            "indicator_eligible_point_count",
            "bar_classification_policy",
            "indicator_policy",
            "partial_bar_policy",
            "aggregation_method",
            "source_point_count",
            "aggregated_point_count",
            "expected_point_count",
            "cache_status",
            "cache_hit",
            "cache_trade_date",
            "cache_latest_time",
            "cached_count",
            "refreshed_count",
            "fallback_used",
            "market_events",
            "sessions",
            "sort_order",
        ),
        default_fields=(
            "as_of",
            "enabled",
            "kind",
            "payload_level",
            "interval",
            "requested_interval",
            "source_interval",
            "effective_interval",
            "interval_status",
            "sampling_mode",
            "original_point_count",
            "session",
            "session_scope",
            "session_phase",
            "market_status",
            "official_close_status",
            "delivery_status",
            "is_current_session",
            "point_count",
            "returned_point_count",
            "truncated",
            "bar_limit",
            "index_ids",
            "indices",
            "points",
            "bars",
            "latest_point",
            "bar_time",
            "open_price",
            "high_price",
            "low_price",
            "close_price",
            "base_volume",
            "base_volume_unit",
            "volume_unit",
            "volume_contracts",
            "volume_event_time",
            "cumulative_volume",
            "cumulative_volume_unit",
            "cumulative_volume_contracts",
            "lot_size",
            "trade_value_unit",
            "quote_volume",
            "quote_volume_unit",
            "currency",
            "price_unit",
            "event_time",
            "fetched_at",
            "received_at",
            "source",
            "provider",
            "freshness",
            "warnings",
            "is_partial",
            "continuity",
            "volume_semantics",
            "volume_status",
            "canonical_volume_unit",
            "provider_volume_unit",
            "volume_conversion",
            "cumulative_volume_shares",
            "cumulative_volume_lots",
            "cumulative_trade_value",
            "available_cumulative_trade_value",
            "estimated_cumulative_trade_value",
            "trade_value_status",
            "official_vwap",
            "approx_vwap",
            "vwap_method",
            "vwap_confidence",
            "bar_type",
            "synthetic",
            "indicator_eligible",
            "market_event",
            "source_event_type",
            "gap_reason",
            "partial_bar_count",
            "indicator_eligible_point_count",
            "bar_classification_policy",
            "indicator_policy",
            "partial_bar_policy",
            "aggregation_method",
            "source_point_count",
            "aggregated_point_count",
            "cache_status",
            "cache_hit",
            "cache_trade_date",
            "cache_latest_time",
            "fallback_used",
            "market_events",
            "sessions",
            "sort_order",
        ),
        default_limit=20,
        fill_operations=(
            ("us_stock", "us.read_intraday_trend"),
            ("jp_stock", "jp.read_intraday_trend"),
            ("jp_index", "jp.read_intraday_trend"),
            ("kr_stock", "kr.read_stock_intraday_trend"),
            ("kr_index", "kr.read_index_intraday_trend"),
            ("crypto_asset", "crypto.refresh_ohlcv"),
        ),
        refresh_strategies=(("stock", "reader_fetch"),),
        refresh_requires_market_open_scopes=("stock",),
    ),
    CapabilitySpec(
        capability_id="daily.ohlcv",
        domain="chart",
        slot="daily_chart",
        scopes=ALL_INSTRUMENT_SCOPES,
        paths=(
            "compact.chart",
            "data.chart",
            "compact.daily_chart",
            "data.daily",
            "data.daily_prices",
            "data.ohlcv",
        ),
        fields=(
            "as_of",
            "latest_data_date",
            "expected_data_date",
            "point_count",
            "returned_point_count",
            "truncated",
            "points",
            "bars",
            "bar_time",
            "open_price",
            "high_price",
            "low_price",
            "close_price",
            "base_volume",
            "base_volume_unit",
            "volume_unit",
            "lot_size",
            "trade_value_unit",
            "quote_volume",
            "quote_volume_unit",
            "volume_semantics",
            "volume_status",
            "currency",
            "price_unit",
            "event_time",
            "fetched_at",
            "received_at",
            "source",
            "provider",
            "freshness",
        ),
        default_fields=(
            "as_of",
            "latest_data_date",
            "expected_data_date",
            "point_count",
            "returned_point_count",
            "truncated",
            "points",
            "bars",
            "bar_time",
            "open_price",
            "high_price",
            "low_price",
            "close_price",
            "base_volume",
            "base_volume_unit",
            "volume_unit",
            "lot_size",
            "trade_value_unit",
            "quote_volume",
            "quote_volume_unit",
            "volume_semantics",
            "volume_status",
            "event_time",
            "fetched_at",
            "received_at",
            "source",
            "provider",
            "freshness",
        ),
        default_limit=30,
        fill_operations=(
            ("stock", "tw.refresh_daily_price"),
            ("us_stock", "us.refresh_daily_price"),
            ("jp_stock", "jp.refresh_daily_price"),
            ("jp_index", "jp.refresh_daily_price"),
            ("kr_stock", "kr.refresh_daily_price"),
            ("kr_index", "kr.refresh_index_daily_price"),
            ("crypto_asset", "crypto.refresh_ohlcv"),
        ),
        writes_cache=True,
    ),
    CapabilitySpec(
        capability_id="technical.structure",
        domain="technical",
        slot="technical",
        scopes=ALL_INSTRUMENT_SCOPES,
        paths=(
            "compact.technical",
            "compact.analysis",
            "data.technical",
            "data.analysis",
            "data.technical_report",
        ),
        fields=(
            "analysis",
            "as_of",
            "trade_date",
            "latest_price",
            "current_price",
            "price_context",
            "daily_indicator_time",
            "intraday_overlay",
            "reports",
            "selected_horizon",
            "effective_horizon",
            "selected_score",
            "selected_title",
            "composite_score_title",
            "selected_summary",
            "selected_confidence",
            "today_state",
            "historical_structure",
            "composite_state",
            "fallback_reason",
            "technical_price_basis",
            "bid_ask_price_used",
            "scores",
            "levels",
            "support",
            "resistance",
            "trend",
            "momentum",
            "volume",
            "freshness",
            "source",
            "provider",
            "currency",
            "price_unit",
            "score_unit",
            "score_contracts",
        ),
        default_fields=(
            "analysis",
            "as_of",
            "trade_date",
            "latest_price",
            "current_price",
            "price_context",
            "daily_indicator_time",
            "intraday_overlay",
            "selected_horizon",
            "effective_horizon",
            "selected_score",
            "selected_title",
            "composite_score_title",
            "selected_summary",
            "selected_confidence",
            "today_state",
            "historical_structure",
            "composite_state",
            "fallback_reason",
            "technical_price_basis",
            "bid_ask_price_used",
            "levels",
            "reports",
            "freshness",
            "source",
            "provider",
            "currency",
            "price_unit",
            "score_unit",
            "score_contracts",
        ),
        default_limit=20,
    ),
    CapabilitySpec(
        capability_id="chips.institutional",
        domain="chips",
        slot="chips_flows",
        scopes=("stock",),
        paths=(
            "compact.chips.institutional",
            "data.institutional",
            "data.institutional_trade",
        ),
        fields=(
            "trade_date",
            "foreign_investor_net",
            "foreign_net",
            "investment_trust_net",
            "dealer_net",
            "total_institutional_net",
            "total_net",
            "source",
            "freshness",
            "quantity_unit",
            "lot_size",
        ),
        default_fields=(
            "trade_date",
            "foreign_investor_net",
            "investment_trust_net",
            "dealer_net",
            "total_institutional_net",
            "source",
            "freshness",
            "quantity_unit",
            "lot_size",
        ),
        default_limit=5,
        fill_operations=(("stock", "tw.refresh_institutional"),),
        writes_cache=True,
    ),
    CapabilitySpec(
        capability_id="chips.margin",
        domain="chips",
        slot="chips_flows",
        scopes=("stock",),
        paths=("compact.chips.margin", "data.margin", "data.margin_trade"),
        fields=(
            "trade_date",
            "margin_buy",
            "margin_sell",
            "margin_today_balance",
            "margin_balance",
            "margin_change",
            "short_sale",
            "short_covering",
            "short_today_balance",
            "short_balance",
            "short_change",
            "source",
            "freshness",
            "quantity_unit",
            "raw_unit",
            "normalized_unit",
            "normalized_quantities",
            "lot_size",
        ),
        default_fields=(
            "trade_date",
            "margin_buy",
            "margin_sell",
            "margin_today_balance",
            "short_sale",
            "short_covering",
            "short_today_balance",
            "source",
            "freshness",
            "quantity_unit",
            "raw_unit",
            "normalized_unit",
            "normalized_quantities",
            "lot_size",
        ),
        default_limit=5,
        fill_operations=(("stock", "tw.refresh_margin"),),
        writes_cache=True,
    ),
    CapabilitySpec(
        capability_id="broker_branch.summary",
        domain="broker_branch",
        slot="broker_branch",
        scopes=("stock",),
        paths=("compact.chips.broker_branch", "data.broker_branch"),
        fields=(
            "trade_date",
            "trade_dates",
            "available_days",
            "requested_days",
            "is_partial",
            "aggregation_window",
            "mode",
            "anchor_trade_date",
            "requested_trading_days",
            "available_trading_days",
            "included_trade_dates",
            "date_semantics",
            "created_at",
            "buy_top",
            "sell_top",
            "source",
            "freshness",
            "currency",
            "price_unit",
            "quantity_unit",
            "lot_size",
        ),
        default_fields=(
            "trade_date",
            "available_days",
            "requested_days",
            "is_partial",
            "aggregation_window",
            "date_semantics",
            "buy_top",
            "sell_top",
            "freshness",
            "currency",
            "price_unit",
            "quantity_unit",
            "lot_size",
        ),
        default_limit=15,
        fill_operations=(("stock", "tw.refresh_broker_branch"),),
        writes_cache=True,
    ),
    CapabilitySpec(
        capability_id="ownership.distribution",
        domain="chips",
        slot="chips_flows",
        scopes=("stock",),
        paths=("compact.chips.shareholding", "data.shareholding_distribution"),
        fields=("trade_date", "distribution", "history", "source", "freshness"),
        default_fields=("trade_date", "distribution", "source", "freshness"),
        default_limit=10,
        fill_operations=(("stock", "tw.refresh_shareholding"),),
        writes_cache=True,
    ),
    CapabilitySpec(
        capability_id="fundamentals.revenue",
        domain="fundamentals",
        slot="fundamentals",
        scopes=("stock", "us_stock", "jp_stock", "kr_stock"),
        paths=("compact.fundamentals", "data"),
        fields=(
            "latest_revenue",
            "revenue_history",
            "period",
            "monthly_revenue",
            "revenue",
            "month_over_month_pct",
            "year_over_year_pct",
            "cumulative_year_over_year_pct",
            "history",
            "source",
            "freshness",
            "currency",
            "source_amount_unit",
            "normalized_amount_unit",
            "amount_scale",
            "ratio_unit",
        ),
        default_fields=(
            "latest_revenue",
            "revenue_history",
            "currency",
            "source_amount_unit",
            "normalized_amount_unit",
            "amount_scale",
            "ratio_unit",
        ),
        default_limit=12,
        fill_operations=(("stock", "tw.refresh_revenue"),),
        writes_cache=True,
    ),
    CapabilitySpec(
        capability_id="fundamentals.financials",
        domain="fundamentals",
        slot="fundamentals",
        scopes=("stock", "us_stock", "jp_stock", "kr_stock"),
        paths=(
            "compact.fundamentals",
            "data.financial_metric",
            "data.financials",
            "data.fundamentals",
            "data.sec_fundamentals",
            "data",
        ),
        fields=(
            "latest_financial",
            "financial_history",
            "financial_contract",
            "sec_fundamentals",
            "period",
            "fiscal_year",
            "quarter",
            "eps",
            "roe",
            "roa",
            "gross_margin",
            "operating_margin",
            "history",
            "source",
            "freshness",
            "currency",
            "source_amount_unit",
            "normalized_amount_unit",
            "amount_scale",
            "ratio_unit",
            "per_share_unit",
        ),
        default_fields=(
            "latest_financial",
            "financial_history",
            "financial_contract",
            "sec_fundamentals",
            "currency",
            "source_amount_unit",
            "normalized_amount_unit",
            "amount_scale",
            "ratio_unit",
            "per_share_unit",
        ),
        default_limit=8,
        fill_operations=(
            ("stock", "tw.refresh_financials"),
            ("us_stock", "us.refresh_sec_facts"),
        ),
        writes_cache=True,
    ),
    CapabilitySpec(
        capability_id="cross_market.overnight",
        domain="cross_market",
        slot="cross_market",
        scopes=("stock",),
        paths=("compact.cross_market", "data.cross_market", "data.us_overnight_impact"),
        fields=(
            "kind",
            "stock_id",
            "stock_name",
            "as_of",
            "generated_at",
            "stance",
            "context_status",
            "decision_usable",
            "summary",
            "signals",
            "bucket_scores",
            "coverage",
            "methodology_version",
            "relation_snapshot_version",
            "snapshot_id",
            "limitations",
            "adr_parity",
            "factors",
            "baskets",
            "source",
            "source_refs",
            "freshness",
            "missing",
            "warnings",
        ),
        default_fields=(
            "as_of",
            "stance",
            "context_status",
            "decision_usable",
            "summary",
            "signals",
            "bucket_scores",
            "coverage",
            "methodology_version",
            "relation_snapshot_version",
            "snapshot_id",
            "limitations",
            "source",
            "freshness",
            "warnings",
        ),
        default_limit=10,
    ),
    CapabilitySpec(
        capability_id="cross_market.relations",
        domain="cross_market",
        slot="cross_market",
        scopes=("stock",),
        paths=(
            "compact.cross_market.cross_market_context",
            "data.cross_market.cross_market_context",
            "data.us_overnight_impact.cross_market_context",
        ),
        fields=(
            "schema_version",
            "target",
            "status",
            "decision_usable",
            "as_of",
            "decision_at",
            "methodology_version",
            "relation_snapshot_version",
            "snapshot_id",
            "summary",
            "signals",
            "coverage",
            "freshness",
            "missing",
            "warnings",
            "limitations",
            "source_refs",
            "evidence_passport",
        ),
        default_fields=(
            "status",
            "decision_usable",
            "as_of",
            "decision_at",
            "methodology_version",
            "relation_snapshot_version",
            "snapshot_id",
            "summary",
            "signals",
            "coverage",
            "warnings",
            "limitations",
        ),
        default_limit=10,
        title="Cross-market target relations",
        description=(
            "Reviewed relation-backed signals and lineage for a Taiwan stock. "
            "This is evidence context and does not imply causality."
        ),
        markets=("TW",),
        frequency="decision_snapshot",
        unit_semantics="field_defined_percent_and_weight",
        event_time_basis="cross_market_decision_at",
    ),
    CapabilitySpec(
        capability_id="cross_market.parity",
        domain="cross_market",
        slot="cross_market",
        scopes=("stock",),
        paths=(
            "compact.cross_market.adr_parity",
            "data.cross_market.adr_parity",
            "data.us_overnight_impact.adr_parity",
        ),
        fields=(
            "kind",
            "status",
            "is_current",
            "stock_id",
            "stock_name",
            "mapping",
            "mapping_resolution",
            "formula",
            "adr_close_usd",
            "adr_trade_date",
            "expected_adr_trade_date",
            "usd_twd",
            "fx_as_of",
            "fx_age_seconds",
            "tw_reference_price_twd",
            "tw_reference_trade_date",
            "implied_tw_price_twd",
            "implied_gap_pct",
            "comparison_mode",
            "remaining_gap_pct",
            "missing",
            "warnings",
            "source_refs",
            "freshness",
        ),
        default_fields=(
            "status",
            "is_current",
            "stock_id",
            "mapping",
            "mapping_resolution",
            "adr_trade_date",
            "expected_adr_trade_date",
            "usd_twd",
            "tw_reference_trade_date",
            "implied_tw_price_twd",
            "implied_gap_pct",
            "comparison_mode",
            "remaining_gap_pct",
            "missing",
            "warnings",
            "freshness",
        ),
        default_limit=10,
        title="ADR parity",
        description=(
            "Ratio- and FX-adjusted direct ADR parity for an eligible Taiwan stock."
        ),
        markets=("TW",),
        frequency="daily",
        unit_semantics="USD_TWD_and_percent",
        event_time_basis="aligned_us_and_taiwan_trade_dates",
    ),
    CapabilitySpec(
        capability_id="company.profile",
        schema_version="tw.company.profile.v1",
        domain=None,
        slot="profile",
        scopes=("stock", "us_stock", "jp_stock", "kr_stock"),
        paths=(
            "compact.company_profile",
            "data.company_profile",
            "data.profile",
            "data.stock",
        ),
        fields=(
            "symbol",
            "stock_id",
            "stock_name",
            "security_name",
            "company_name",
            "exchange",
            "market",
            "asset_type",
            "instrument_type",
            "sector",
            "industry",
            "category",
            "listed_date",
            "established_date",
            "paid_in_capital",
            "issued_shares",
            "is_active",
            "currency",
            "source",
            "status",
            "missing_fields",
            "as_of",
            "cik",
            "sec_company_name",
            "provider",
            "fetched_at",
            "updated_at",
        ),
        default_fields=(
            "symbol",
            "stock_id",
            "stock_name",
            "security_name",
            "company_name",
            "exchange",
            "market",
            "asset_type",
            "instrument_type",
            "sector",
            "industry",
            "category",
            "listed_date",
            "paid_in_capital",
            "issued_shares",
            "is_active",
            "currency",
            "source",
            "status",
            "missing_fields",
            "as_of",
            "provider",
            "fetched_at",
        ),
        default_limit=1,
    ),
    CapabilitySpec(
        capability_id="corporate.actions",
        schema_version="tw.corporate.actions.v1",
        domain=None,
        slot="news_events",
        scopes=("stock", "us_stock"),
        paths=("compact.corporate_actions", "data.corporate_actions"),
        fields=(
            "provider",
            "symbol",
            "stock_id",
            "action_id",
            "action_type",
            "event_date",
            "announce_date",
            "ex_date",
            "record_date",
            "payment_date",
            "effective_date",
            "amount",
            "cash_amount",
            "stock_ratio",
            "split_ratio",
            "currency",
            "source",
            "status",
            "as_of",
            "actions",
            "result_count",
            "total_count",
            "cache_status",
            "empty_result_is_valid",
            "warnings",
            "fetched_at",
        ),
        default_fields=(
            "provider",
            "symbol",
            "stock_id",
            "action_id",
            "action_type",
            "event_date",
            "announce_date",
            "ex_date",
            "effective_date",
            "amount",
            "cash_amount",
            "stock_ratio",
            "split_ratio",
            "currency",
            "source",
            "status",
            "as_of",
            "actions",
            "result_count",
            "total_count",
            "cache_status",
            "empty_result_is_valid",
            "warnings",
        ),
        default_limit=20,
        parameter_schema={
            "type": "object",
            "properties": {
                "years": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 10,
                    "default": 5,
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 200,
                    "default": 20,
                },
            },
            "additionalProperties": False,
        },
    ),
    CapabilitySpec(
        capability_id="market.short_volume",
        domain=None,
        slot="flows_liquidity",
        scopes=("us_stock",),
        paths=("data.short_volume",),
        fields=(
            "provider",
            "symbol",
            "trade_date",
            "market_center",
            "short_volume",
            "total_volume",
            "short_ratio",
            "fetched_at",
        ),
        default_fields=(
            "provider",
            "symbol",
            "trade_date",
            "market_center",
            "short_volume",
            "total_volume",
            "short_ratio",
        ),
        default_limit=20,
    ),
    CapabilitySpec(
        capability_id="market.breadth",
        schema_version="tw.market.breadth.v1",
        domain="breadth",
        slot="market_breadth",
        scopes=ALL_MARKET_SCOPES,
        paths=("compact.breadth", "data.breadth", "data.market_breadth"),
        fields=(
            "as_of",
            "trade_date",
            "status",
            "label",
            "advance",
            "advance_count",
            "decline",
            "decline_count",
            "unchanged",
            "unchanged_count",
            "limit_up",
            "limit_up_count",
            "limit_down",
            "limit_down_count",
            "total_count",
            "trade_value",
            "trade_value_unit",
            "currency",
            "scope",
            "coverage",
            "market",
            "market_segment",
            "index_id",
            "universe_count",
            "coverage_count",
            "coverage_ratio",
            "classified_count",
            "unknown_count",
            "reconciliation_status",
            "reconciliation_formula",
            "universe_definition",
            "authority",
            "inclusion_rule",
            "instrument_type_policy",
            "missing_quote_policy",
            "official_full_market",
            "is_full_market",
            "universe_type",
            "coverage_limitation",
            "direct_market_breadth",
            "proxy_used",
            "coverage_note",
            "included_markets",
            "missing_markets",
            "markets",
            "trade_value_available",
            "trade_value_complete",
            "trade_value_coverage_status",
            "trade_value_authority_status",
            "trade_value_status",
            "trade_value_included_markets",
            "trade_value_missing_markets",
            "trade_value_estimate",
            "trade_value_estimate_method",
            "market_completion_ratio",
            "close_reconciliation",
            "source",
            "freshness",
        ),
        default_fields=(
            "as_of",
            "trade_date",
            "status",
            "label",
            "advance",
            "advance_count",
            "decline",
            "decline_count",
            "unchanged",
            "unchanged_count",
            "limit_up",
            "limit_up_count",
            "limit_down",
            "limit_down_count",
            "total_count",
            "trade_value",
            "trade_value_unit",
            "currency",
            "scope",
            "coverage",
            "market",
            "market_segment",
            "index_id",
            "universe_count",
            "coverage_count",
            "coverage_ratio",
            "classified_count",
            "unknown_count",
            "reconciliation_status",
            "is_full_market",
            "universe_type",
            "coverage_limitation",
            "direct_market_breadth",
            "proxy_used",
            "coverage_note",
            "included_markets",
            "missing_markets",
            "markets",
            "trade_value_complete",
            "trade_value_status",
            "market_completion_ratio",
            "close_reconciliation",
            "source",
            "freshness",
        ),
        default_limit=10,
    ),
    CapabilitySpec(
        capability_id="market.indices",
        domain="indices",
        slot="market_indices",
        scopes=("market",),
        paths=("compact.market.indices", "data.market.indices"),
        fields=(
            "kind",
            "status",
            "as_of",
            "count",
            "items",
            "source",
            "missing",
            "warnings",
        ),
        default_fields=(
            "status",
            "as_of",
            "count",
            "items",
            "source",
            "missing",
            "warnings",
        ),
        default_limit=20,
        title="Taiwan market indices",
        description=(
            "Canonical TAIEX and TPEx index snapshots from the shared Taiwan "
            "market-index summary reader."
        ),
        markets=("TW",),
        frequency="intraday",
        unit_semantics="index_points",
        event_time_basis="index_quote_or_completed_trade_date",
    ),
    CapabilitySpec(
        capability_id="events.upcoming",
        domain="events",
        slot="events_upcoming",
        scopes=("stock",),
        paths=("compact.events.upcoming", "data.events.upcoming"),
        fields=(
            "kind",
            "status",
            "stock_id",
            "as_of",
            "days",
            "limit",
            "result_count",
            "total_count",
            "events",
            "source",
            "cache_policy",
            "cache_status",
            "cache_fetched_at",
            "empty_result_is_valid",
            "missing",
            "warnings",
        ),
        default_fields=(
            "status",
            "stock_id",
            "as_of",
            "days",
            "result_count",
            "events",
            "source",
            "cache_policy",
            "cache_status",
            "empty_result_is_valid",
            "missing",
            "warnings",
        ),
        default_limit=50,
        title="Taiwan stock upcoming events",
        description=(
            "Upcoming official Taiwan stock events from the bounded local "
            "corporate-event cache. A current empty result is distinct from a "
            "missing event cache."
        ),
        markets=("TW",),
        parameter_schema={
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 365,
                    "default": 30,
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "default": 10,
                },
            },
            "additionalProperties": False,
        },
        frequency="daily",
        unit_semantics="event_records",
        event_time_basis="official_event_date",
        side_effect_policy="cache_only",
    ),
    CapabilitySpec(
        capability_id="events.calendar",
        schema_version="tw.events.calendar.v1",
        domain="events",
        slot="events_calendar",
        scopes=("market",),
        paths=(
            "compact.events.calendar",
            "data.events.calendar",
            "data.market.events_calendar",
        ),
        fields=(
            "kind",
            "status",
            "as_of",
            "date_from",
            "date_to",
            "event_types",
            "markets",
            "stock_ids",
            "instrument_types",
            "exclude_instrument_types",
            "industries",
            "financial_report_related",
            "event_statuses",
            "timing_statuses",
            "pagination",
            "result_count",
            "events",
            "source",
            "sources",
            "cache_policy",
            "empty_result_is_valid",
            "missing",
            "warnings",
        ),
        default_fields=(
            "status",
            "as_of",
            "date_from",
            "date_to",
            "event_types",
            "markets",
            "stock_ids",
            "instrument_types",
            "exclude_instrument_types",
            "industries",
            "financial_report_related",
            "event_statuses",
            "timing_statuses",
            "pagination",
            "result_count",
            "events",
            "source",
            "cache_policy",
            "empty_result_is_valid",
            "missing",
            "warnings",
        ),
        default_limit=300,
        title="Taiwan corporate-event calendar",
        description=(
            "Bounded Taiwan market corporate-event calendar over the existing "
            "official cache. The market target replaces a redundant calendar "
            "target while retaining explicit date, market, event-type, stock, "
            "pagination, and freshness semantics."
        ),
        markets=("TW",),
        parameter_schema={
            "type": "object",
            "properties": {
                "date_from": {"type": "string", "format": "date"},
                "date_to": {"type": "string", "format": "date"},
                "event_types": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [
                            "ex_dividend",
                            "financial_report",
                            "investor_conference",
                        ],
                    },
                    "maxItems": 3,
                },
                "markets": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["TWSE", "TPEX"],
                    },
                    "maxItems": 2,
                    "default": ["TWSE", "TPEX"],
                },
                "stock_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 2500,
                },
                "instrument_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 20,
                },
                "exclude_instrument_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 20,
                },
                "industries": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 100,
                },
                "financial_report_related": {"type": "boolean"},
                "status": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["today", "ongoing", "upcoming", "past"],
                    },
                    "maxItems": 4,
                },
                "timing_status": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["actual", "scheduled"],
                    },
                    "maxItems": 2,
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 500,
                    "default": 300,
                },
                "offset": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 5000,
                    "default": 0,
                },
            },
            "additionalProperties": False,
        },
        frequency="daily",
        unit_semantics="event_records",
        event_time_basis="official_event_date",
        side_effect_policy="cache_only",
    ),
    CapabilitySpec(
        capability_id="events.history",
        domain="events",
        slot="events_history",
        scopes=("stock",),
        paths=("compact.events.history", "data.events.history"),
        fields=(
            "kind",
            "status",
            "stock_id",
            "as_of",
            "years",
            "limit",
            "result_count",
            "returned_count",
            "total_count",
            "offset",
            "sort_order",
            "events",
            "source",
            "cache_policy",
            "cache_status",
            "cache_fetched_at",
            "empty_result_is_valid",
            "missing",
            "warnings",
        ),
        default_fields=(
            "status",
            "stock_id",
            "as_of",
            "years",
            "result_count",
            "returned_count",
            "total_count",
            "offset",
            "sort_order",
            "events",
            "source",
            "cache_policy",
            "cache_status",
            "empty_result_is_valid",
            "missing",
            "warnings",
        ),
        default_limit=200,
        title="Taiwan stock event history",
        description=(
            "Official Taiwan stock event history from the bounded archive "
            "cache with explicit coverage and cache freshness."
        ),
        markets=("TW",),
        parameter_schema={
            "type": "object",
            "properties": {
                "years": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 10,
                    "default": 5,
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 200,
                    "default": 20,
                },
            },
            "additionalProperties": False,
        },
        frequency="daily",
        unit_semantics="event_records",
        event_time_basis="official_event_date",
        side_effect_policy="cache_only",
    ),
    CapabilitySpec(
        capability_id="regulation.disposition",
        domain="regulation",
        slot="regulation_disposition",
        scopes=("stock",),
        paths=(
            "compact.regulation.disposition",
            "data.regulation.disposition",
        ),
        fields=(
            "kind",
            "status",
            "stock_id",
            "as_of",
            "is_disposition",
            "is_active",
            "disposition_status",
            "announced_date",
            "start_date",
            "end_date",
            "reason",
            "measure",
            "matching_interval_minutes",
            "requires_full_precollection",
            "margin_trading_suspended",
            "provider",
            "source",
            "source_url",
            "cache_policy",
            "cache_status",
            "cache_fetched_at",
            "missing",
            "warnings",
        ),
        default_fields=(
            "status",
            "stock_id",
            "as_of",
            "is_disposition",
            "is_active",
            "disposition_status",
            "start_date",
            "end_date",
            "reason",
            "measure",
            "matching_interval_minutes",
            "requires_full_precollection",
            "margin_trading_suspended",
            "provider",
            "source",
            "cache_status",
            "missing",
            "warnings",
        ),
        default_limit=1,
        title="Taiwan stock disposition status",
        description=(
            "Official Taiwan disposition status with effective dates, measure "
            "details, cache provenance, and explicit missing semantics."
        ),
        markets=("TW",),
        frequency="daily",
        unit_semantics="regulatory_status",
        event_time_basis="official_disposition_effective_date",
        side_effect_policy="cache_only",
    ),
    CapabilitySpec(
        capability_id="regulation.trading_restrictions",
        domain="regulation",
        slot="regulation_trading_restrictions",
        scopes=("stock",),
        paths=(
            "compact.regulation.trading_restrictions",
            "data.regulation.trading_restrictions",
        ),
        fields=(
            "kind",
            "status",
            "stock_id",
            "as_of",
            "trading_mode",
            "analysis_basis",
            "matching_interval_minutes",
            "requires_full_precollection",
            "margin_trading_suspended",
            "effective_start_date",
            "effective_end_date",
            "upcoming_disposition",
            "source",
            "provider",
            "cache_policy",
            "cache_status",
            "missing",
            "warnings",
        ),
        default_fields=(
            "status",
            "stock_id",
            "as_of",
            "trading_mode",
            "analysis_basis",
            "matching_interval_minutes",
            "requires_full_precollection",
            "margin_trading_suspended",
            "effective_start_date",
            "effective_end_date",
            "upcoming_disposition",
            "source",
            "provider",
            "cache_status",
            "missing",
            "warnings",
        ),
        default_limit=1,
        title="Taiwan stock trading restrictions",
        description=(
            "Backend-derived Taiwan trading mode and restrictions. Unknown "
            "disposition cache state never defaults to unrestricted trading."
        ),
        markets=("TW",),
        frequency="daily",
        unit_semantics="restriction_flags_and_minutes",
        event_time_basis="official_disposition_effective_date",
        side_effect_policy="cache_only",
    ),
    CapabilitySpec(
        capability_id="market.sectors",
        domain="sectors",
        slot="market_sectors",
        scopes=("market",),
        paths=("compact.market.sectors", "data.market.sectors"),
        fields=(
            "kind",
            "version",
            "status",
            "as_of",
            "observed_trade_date",
            "computed_at",
            "data_mode",
            "is_intraday",
            "snapshot_version",
            "snapshot_id",
            "ranking_basis",
            "aggregation_method",
            "currency",
            "trade_value_unit",
            "trade_value_is_estimate",
            "is_full_market",
            "coverage",
            "count",
            "items",
            "missing",
            "coverage_gaps",
            "warnings",
        ),
        default_fields=(
            "status",
            "as_of",
            "observed_trade_date",
            "computed_at",
            "data_mode",
            "is_intraday",
            "snapshot_version",
            "snapshot_id",
            "ranking_basis",
            "aggregation_method",
            "currency",
            "trade_value_unit",
            "trade_value_is_estimate",
            "is_full_market",
            "coverage",
            "count",
            "items",
            "missing",
            "coverage_gaps",
            "warnings",
        ),
        default_limit=100,
        title="Taiwan sector performance",
        description=(
            "Taiwan sector performance with explicit ranking basis and coverage. "
            "The v1 fallback is labeled as an OMI local stock-sample aggregate, "
            "not an official full-market sector-index ranking."
        ),
        markets=("TW",),
        frequency="intraday_or_daily",
        unit_semantics="percent_counts_and_twd",
        event_time_basis=(
            "taiwan_provider_event_time_or_completed_trade_date"
        ),
        side_effect_policy="scheduler_owned_cache_read_or_daily_fallback",
    ),
    CapabilitySpec(
        capability_id="market.index_contributions",
        domain="index_contributions",
        slot="market_index_contributions",
        scopes=("market", "tw_index"),
        paths=(
            "compact.market.index_contributions",
            "data.market.index_contributions",
            "compact.contributions",
            "data.contributions",
        ),
        fields=(
            "kind",
            "status",
            "as_of",
            "index_ids",
            "indices",
            "method",
            "method_version",
            "is_official",
            "currency",
            "price_unit",
            "market_value_unit",
            "trade_value_unit",
            "contribution_unit",
            "component_universe_count",
            "covered_component_count",
            "coverage_ratio",
            "estimated_total_contribution_points",
            "actual_index_change_points",
            "residual_points",
            "residual_pct",
            "reconciliation_status",
            "confidence",
            "component_policy",
            "corporate_action_adjustment",
            "cache_policy",
            "external_fetch",
            "writes_cache",
            "tool_runs",
            "provider_attempts",
            "missing",
            "warnings",
            "index_id",
            "market",
            "source",
            "trade_date",
            "index_close",
            "index_change",
            "total_market_value",
            "positive",
            "negative",
        ),
        default_fields=(
            "status",
            "as_of",
            "index_ids",
            "indices",
            "method",
            "method_version",
            "is_official",
            "currency",
            "trade_value_unit",
            "contribution_unit",
            "reconciliation_status",
            "cache_policy",
            "external_fetch",
            "writes_cache",
            "tool_runs",
            "provider_attempts",
            "missing",
            "warnings",
            "index_id",
            "market",
            "source",
            "trade_date",
            "positive",
            "negative",
        ),
        default_limit=20,
        title="Taiwan index contribution leaders",
        description=(
            "Positive and negative stock contribution leaders for selected "
            "Taiwan indices. The estimated market-cap-weight method and source "
            "are always returned."
        ),
        markets=("TW",),
        parameter_schema={
            "type": "object",
            "properties": {
                "index_ids": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["TAIEX", "TPEX"],
                    },
                    "maxItems": 2,
                    "default": ["TAIEX", "TPEX"],
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 10,
                },
            },
            "additionalProperties": False,
        },
        frequency="intraday",
        unit_semantics="index_points_prices_and_twd",
        event_time_basis="taiwan_market_trade_date",
        side_effect_policy="bounded_external_read_when_authorized",
    ),
    CapabilitySpec(
        capability_id="market.institutional_flow",
        domain="chips",
        slot="market_institutional_flow",
        scopes=("market",),
        paths=(
            "compact.market.institutional_flow",
            "data.market.institutional_flow",
        ),
        fields=(
            "kind",
            "status",
            "trade_date",
            "trade_dates",
            "same_trade_date",
            "markets",
            "rows",
            "source_grade",
            "unit",
            "aggregate",
            "freshness",
            "missing",
            "warnings",
        ),
        default_fields=(
            "status",
            "trade_date",
            "trade_dates",
            "same_trade_date",
            "markets",
            "rows",
            "source_grade",
            "unit",
            "aggregate",
            "freshness",
            "missing",
            "warnings",
        ),
        default_limit=20,
        title="Taiwan market institutional flow",
        description=(
            "Official TWSE/TPEx institutional net-flow values in TWD. Combined "
            "totals are withheld when component market dates do not match."
        ),
        markets=("TW",),
        frequency="daily",
        unit_semantics="TWD",
        event_time_basis="taiwan_completed_trade_date",
    ),
    CapabilitySpec(
        capability_id="market.margin_short",
        domain="chips",
        slot="market_margin_short",
        scopes=("market",),
        paths=(
            "compact.market.margin_short",
            "data.market.margin_short",
        ),
        fields=(
            "kind",
            "status",
            "trade_date",
            "trade_dates",
            "same_trade_date",
            "markets",
            "rows",
            "source_grade",
            "unit_semantics",
            "aggregate",
            "margin_status",
            "freshness",
            "missing",
            "warnings",
        ),
        default_fields=(
            "status",
            "trade_date",
            "trade_dates",
            "same_trade_date",
            "markets",
            "rows",
            "source_grade",
            "unit_semantics",
            "aggregate",
            "margin_status",
            "freshness",
            "missing",
            "warnings",
        ),
        default_limit=20,
        title="Taiwan market margin and short flow",
        description=(
            "Official TWSE/TPEx margin-balance and short-balance changes with "
            "field-level TWD/share units and release status."
        ),
        markets=("TW",),
        frequency="daily",
        unit_semantics="field_defined_twd_or_shares",
        event_time_basis="taiwan_completed_trade_date",
    ),
    CapabilitySpec(
        capability_id="market.sample_ranking",
        domain="sample_ranking",
        slot="sample_distribution",
        scopes=("market",),
        paths=("compact.sample_ranking", "data.sample_ranking"),
        fields=(
            "kind",
            "status",
            "scope",
            "scope_label",
            "is_full_market",
            "as_of",
            "latest_trade_date",
            "source",
            "currency",
            "price_unit",
            "volume_unit",
            "trade_value_unit",
            "unit_semantics",
            "sample_breadth",
            "sample_coverage",
            "distribution",
            "top_gainers",
            "top_losers",
            "value_leaders",
            "top_industries",
            "weak_industries",
            "industry_strength_label",
            "warnings",
        ),
        default_fields=(
            "status",
            "scope",
            "scope_label",
            "is_full_market",
            "as_of",
            "latest_trade_date",
            "source",
            "currency",
            "price_unit",
            "volume_unit",
            "trade_value_unit",
            "unit_semantics",
            "sample_coverage",
            "distribution",
            "top_gainers",
            "top_losers",
            "value_leaders",
            "top_industries",
            "weak_industries",
            "industry_strength_label",
            "warnings",
        ),
        default_limit=20,
        title="Taiwan local sample ranking",
        description=(
            "Ranking over the bounded Taiwan daily sample available in the local "
            "OMI context. It is not a full-market screener."
        ),
        markets=("TW",),
        frequency="daily",
        unit_semantics="TWD_per_share_shares_and_TWD",
        event_time_basis="taiwan_completed_trade_date",
        deprecated=True,
        replacement_capabilities=(
            "screening.ranking",
            "screening.coverage",
        ),
    ),
    CapabilitySpec(
        capability_id="market.cross_market",
        domain="cross_market",
        slot="cross_market",
        scopes=("market",),
        paths=("compact.cross_market", "data.cross_market"),
        fields=(
            "kind",
            "status",
            "as_of",
            "markets",
            "summary",
            "missing",
            "warnings",
            "source_refs",
        ),
        default_fields=(
            "status",
            "as_of",
            "markets",
            "summary",
            "missing",
            "warnings",
        ),
        default_limit=20,
    ),
    CapabilitySpec(
        capability_id="market.chips",
        domain="chips",
        slot="market_chips",
        scopes=("market",),
        paths=("compact.market_chips", "data.market_chips"),
        fields=(
            "kind",
            "status",
            "as_of",
            "institutional",
            "margin",
            "official_market",
            "summary",
            "coverage",
            "missing",
            "warnings",
            "source_refs",
        ),
        default_fields=(
            "status",
            "as_of",
            "institutional",
            "margin",
            "official_market",
            "summary",
            "coverage",
            "missing",
            "warnings",
        ),
        default_limit=20,
        title="Taiwan market chips",
        description=(
            "Taiwan market-level institutional and margin context from completed "
            "official datasets."
        ),
        markets=("TW",),
        frequency="daily",
        unit_semantics="field_defined_shares_or_twd",
        event_time_basis="taiwan_trade_date",
    ),
    CapabilitySpec(
        capability_id="screening.ranking",
        schema_version="tw.screening.ranking.v2",
        domain="screening",
        slot="screening_ranking",
        scopes=("market",),
        paths=("compact.screening.ranking", "data.screening.ranking"),
        fields=(
            "kind",
            "version",
            "snapshot_id",
            "status",
            "metric",
            "unit",
            "frequency",
            "sort_order",
            "tie_policy",
            "window",
            "universe",
            "pagination",
            "require_complete_window",
            "min_observed_periods",
            "incomplete_window_policy",
            "rows",
            "incomplete_rows",
            "as_of",
            "generated_at",
            "cache_policy",
            "missing",
            "warnings",
        ),
        default_fields=(
            "snapshot_id",
            "status",
            "metric",
            "unit",
            "sort_order",
            "tie_policy",
            "window",
            "universe",
            "pagination",
            "require_complete_window",
            "min_observed_periods",
            "incomplete_window_policy",
            "rows",
            "as_of",
            "cache_policy",
            "missing",
            "warnings",
        ),
        default_limit=200,
        title="Taiwan stock screening ranking",
        description=(
            "Deterministic ranking over the cached active TWSE/TPEx ordinary-stock "
            "universe. Reads only local normalized data and never triggers an "
            "implicit full-market refresh."
        ),
        markets=("TW",),
        parameter_schema={
            "type": "object",
            "properties": {
                "metric": {
                    "type": "string",
                    "enum": [
                        "foreign_investor_net_shares",
                        "investment_trust_net_shares",
                        "margin_balance_change_pct",
                    ],
                    "default": "foreign_investor_net_shares",
                },
                "window": {
                    "type": "integer",
                    "enum": [1, 5, 10, 20],
                    "default": 1,
                },
                "sort_order": {
                    "type": "string",
                    "enum": ["asc", "desc"],
                    "default": "desc",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 200,
                    "default": 20,
                },
                "offset": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 5000,
                    "default": 0,
                },
                "require_complete_window": {
                    "type": "boolean",
                    "default": True,
                },
                "min_observed_periods": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20,
                },
                "incomplete_window_policy": {
                    "type": "string",
                    "enum": [
                        "exclude",
                        "include_and_flag",
                        "separate_section",
                    ],
                    "default": "exclude",
                },
                "universe": {
                    "type": "object",
                    "properties": {
                        "markets": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": ["TWSE", "TPEX"],
                            },
                            "maxItems": 2,
                            "default": ["TWSE", "TPEX"],
                        },
                        "stock_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "maxItems": 2500,
                        },
                        "exclude_stock_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "maxItems": 2500,
                        },
                    },
                    "additionalProperties": False,
                },
            },
            "additionalProperties": False,
        },
        frequency="daily",
        unit_semantics="metric_defined_shares_or_percent",
        event_time_basis="taiwan_completed_trade_date",
        side_effect_policy="cache_read_only_no_refresh",
    ),
    CapabilitySpec(
        capability_id="screening.coverage",
        domain="screening",
        slot="screening_coverage",
        scopes=("market",),
        paths=("compact.screening.coverage", "data.screening.coverage"),
        fields=(
            "kind",
            "version",
            "snapshot_id",
            "status",
            "metric",
            "dataset",
            "unit",
            "frequency",
            "requested_window_trade_days",
            "available_window_trade_days",
            "window_start",
            "window_end",
            "universe_count",
            "eligible_count",
            "covered_count",
            "complete_window_count",
            "partial_window_count",
            "missing_count",
            "coverage_ratio",
            "is_full_market_request",
            "is_full_requested_universe",
            "markets",
            "instrument_types",
            "dedupe_policy",
            "cache_policy",
            "as_of",
            "missing",
            "warnings",
        ),
        default_fields=(
            "snapshot_id",
            "status",
            "metric",
            "dataset",
            "unit",
            "requested_window_trade_days",
            "available_window_trade_days",
            "window_start",
            "window_end",
            "universe_count",
            "covered_count",
            "complete_window_count",
            "partial_window_count",
            "missing_count",
            "coverage_ratio",
            "is_full_market_request",
            "is_full_requested_universe",
            "markets",
            "instrument_types",
            "dedupe_policy",
            "cache_policy",
            "as_of",
            "missing",
            "warnings",
        ),
        default_limit=20,
        title="Taiwan stock screening coverage",
        description=(
            "Coverage and provenance for the screening snapshot returned by "
            "screening.ranking, including universe, window, and cache policy."
        ),
        markets=("TW",),
        frequency="daily",
        unit_semantics="counts_and_ratio",
        event_time_basis="taiwan_completed_trade_date",
        side_effect_policy="cache_read_only_no_refresh",
    ),
    CapabilitySpec(
        capability_id="screening.intraday",
        schema_version="tw.screening.intraday.v2",
        domain="screening",
        slot="screening_intraday",
        scopes=("market",),
        paths=(
            "compact.screening.intraday",
            "data.screening.intraday",
        ),
        fields=(
            "kind",
            "version",
            "status",
            "metric",
            "unit",
            "frequency",
            "sort_order",
            "rows",
            "pagination",
            "coverage",
            "observed_trade_date",
            "event_time",
            "computed_at",
            "data_mode",
            "is_intraday",
            "cache_policy",
            "missing",
            "warnings",
        ),
        default_fields=(
            "status",
            "metric",
            "unit",
            "sort_order",
            "rows",
            "pagination",
            "coverage",
            "observed_trade_date",
            "event_time",
            "computed_at",
            "data_mode",
            "cache_policy",
            "missing",
            "warnings",
        ),
        default_limit=200,
        title="Taiwan intraday stock screening",
        description=(
            "Deterministic ranking over scheduler-owned Taiwan rolling "
            "intraday stock state. The read path is cache-only and never "
            "fans out to per-stock providers."
        ),
        markets=("TW",),
        parameter_schema={
            "type": "object",
            "properties": {
                "metric": {
                    "type": "string",
                    "enum": [
                        "change_pct",
                        "estimated_trade_value",
                        "cumulative_volume_lots",
                        "distance_from_high_pct",
                        "rebound_from_low_pct",
                        "five_minute_return",
                        "fifteen_minute_return",
                        "intraday_range_pct",
                        "vwap_deviation_pct",
                        "order_book_imbalance",
                    ],
                    "default": "change_pct",
                },
                "sort_order": {
                    "type": "string",
                    "enum": ["asc", "desc"],
                    "default": "desc",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 200,
                    "default": 20,
                },
                "offset": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 5000,
                    "default": 0,
                },
                "universe": {
                    "type": "object",
                    "properties": {
                        "markets": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": ["TWSE", "TPEX"],
                            },
                            "maxItems": 2,
                        },
                        "stock_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "maxItems": 2500,
                        },
                    },
                    "additionalProperties": False,
                },
            },
            "additionalProperties": False,
        },
        frequency="rolling_minute_state",
        unit_semantics="metric_defined_twd_lots_percent_or_ratio",
        event_time_basis="taiwan_provider_event_time",
        side_effect_policy="scheduler_owned_cache_read_only",
    ),
    CapabilitySpec(
        capability_id="market.hot_groups",
        schema_version="tw.market.hot_groups.v1",
        domain="screening",
        slot="market_hot_groups",
        scopes=("market",),
        paths=(
            "compact.screening.hot_groups",
            "data.screening.hot_groups",
        ),
        fields=(
            "kind",
            "version",
            "status",
            "groups",
            "group_count",
            "exchange_industry_group_count",
            "watchlist_group_count",
            "snapshot_version",
            "snapshot_id",
            "coverage",
            "currency",
            "trade_value_unit",
            "trade_value_is_estimate",
            "membership_provenance",
            "observed_trade_date",
            "event_time",
            "computed_at",
            "data_mode",
            "is_intraday",
            "missing",
            "warnings",
        ),
        default_fields=(
            "status",
            "groups",
            "group_count",
            "exchange_industry_group_count",
            "watchlist_group_count",
            "snapshot_version",
            "snapshot_id",
            "coverage",
            "currency",
            "trade_value_unit",
            "trade_value_is_estimate",
            "membership_provenance",
            "observed_trade_date",
            "event_time",
            "computed_at",
            "data_mode",
            "missing",
            "warnings",
        ),
        default_limit=100,
        title="Taiwan intraday hot groups",
        description=(
            "Intraday industry and user-curated watchlist group metrics with "
            "explicit membership provenance; group membership is never "
            "inferred by the answer model."
        ),
        markets=("TW",),
        parameter_schema={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 20,
                }
            },
            "additionalProperties": False,
        },
        frequency="rolling_minute_state",
        unit_semantics="group_returns_counts_twd_and_ratios",
        event_time_basis="taiwan_provider_event_time",
        side_effect_policy="scheduler_owned_cache_read_only",
    ),
    CapabilitySpec(
        capability_id="market.volume_state",
        domain="volume",
        slot="market_volume",
        scopes=("market",),
        paths=("compact.volume_state", "data.volume_state"),
        fields=(
            "kind",
            "as_of",
            "trade_date",
            "status",
            "session_status",
            "comparison_minute",
            "calculation_basis",
            "currency",
            "trade_value_unit",
            "current_cumulative_trade_value",
            "available_cumulative_trade_value",
            "trade_value_available",
            "trade_value_complete",
            "trade_value_status",
            "included_markets",
            "missing_markets",
            "trade_value_estimate",
            "trade_value_estimate_method",
            "current_value_source",
            "previous_minute_cumulative_trade_value",
            "one_minute_trade_value_change",
            "field_status",
            "same_time_baseline_5d",
            "same_time_baseline_20d",
            "baseline_readiness_status",
            "available_sample_days",
            "expected_5d_ready_after_sessions",
            "expected_20d_ready_after_sessions",
            "next_fill",
            "history_trade_dates",
            "markets",
            "warnings",
            "limitations",
            "source_refs",
        ),
        default_fields=(
            "as_of",
            "trade_date",
            "status",
            "session_status",
            "comparison_minute",
            "calculation_basis",
            "currency",
            "trade_value_unit",
            "current_cumulative_trade_value",
            "available_cumulative_trade_value",
            "trade_value_available",
            "trade_value_complete",
            "trade_value_coverage_status",
            "trade_value_authority_status",
            "trade_value_status",
            "included_markets",
            "missing_markets",
            "current_value_source",
            "previous_minute_cumulative_trade_value",
            "one_minute_trade_value_change",
            "field_status",
            "same_time_baseline_5d",
            "same_time_baseline_20d",
            "baseline_readiness_status",
            "available_sample_days",
            "expected_5d_ready_after_sessions",
            "expected_20d_ready_after_sessions",
            "next_fill",
            "markets",
            "warnings",
            "limitations",
        ),
        default_limit=20,
        title="Taiwan market volume state",
        description=(
            "Taiwan same-time cumulative market trade-value state and historical "
            "pace baselines."
        ),
        markets=("TW",),
        frequency="intraday",
        unit_semantics="TWD",
        event_time_basis="taiwan_market_event_time",
    ),
    CapabilitySpec(
        capability_id="derivatives.positioning",
        domain=None,
        slot="institutional_position",
        scopes=("tw_futures",),
        paths=("compact",),
        fields=(
            "institutional_position",
            "options_sentiment",
            "market_chip_trend",
        ),
        default_fields=(
            "institutional_position",
            "options_sentiment",
            "market_chip_trend",
        ),
        default_limit=20,
    ),
    CapabilitySpec(
        capability_id="derivatives.structure",
        domain=None,
        slot="derivatives",
        scopes=("tw_futures",),
        paths=("compact.derivatives", "data.derivatives"),
        fields=(
            "status",
            "as_of",
            "expected_trade_date",
            "is_stale",
            "options_chain",
            "large_traders",
            "term_structure",
            "missing",
            "warnings",
        ),
        default_fields=(
            "status",
            "as_of",
            "is_stale",
            "options_chain",
            "large_traders",
            "term_structure",
            "missing",
            "warnings",
        ),
        default_limit=20,
    ),
    CapabilitySpec(
        capability_id="watchlist.ranking",
        domain=None,
        slot="ranking",
        scopes=("watchlist", "us_watchlist", "jp_watchlist", "kr_watchlist"),
        paths=("compact.ranking", "data.ranking"),
        fields=(
            "rank_by",
            "sort_order",
            "requested_stock_count",
            "requested_symbol_count",
            "ranked_count",
            "no_data_count",
            "error_count",
            "trade_date",
            "target_trade_date",
            "underlying_trade_date",
            "is_current",
            "is_live",
            "is_full",
            "coverage_ratio",
            "ranking_semantics",
            "current_stock_count",
            "stale_stock_count",
            "result_count",
            "returned_count",
            "results",
        ),
        default_fields=(
            "rank_by",
            "sort_order",
            "requested_stock_count",
            "requested_symbol_count",
            "ranked_count",
            "no_data_count",
            "error_count",
            "trade_date",
            "target_trade_date",
            "underlying_trade_date",
            "is_current",
            "is_live",
            "is_full",
            "coverage_ratio",
            "ranking_semantics",
            "stale_stock_count",
            "returned_count",
            "results",
        ),
        default_limit=20,
    ),
    CapabilitySpec(
        capability_id="watchlist.radar",
        schema_version="omi.watchlist.radar.v2",
        domain=None,
        slot="radar",
        scopes=("watchlist", "us_watchlist", "jp_watchlist", "kr_watchlist"),
        paths=("compact.radar", "data.radar"),
        fields=(
            "mode",
            "requested_stock_count",
            "ranked_count",
            "matched_count",
            "radar_count",
            "no_data_count",
            "error_count",
            "trade_date",
            "target_trade_date",
            "is_current",
            "current_stock_count",
            "stale_stock_count",
            "cache_status",
            "snapshot_id",
            "snapshot_date",
            "calculated_at",
            "data_limitations",
            "radar_engine",
            "radar_v2_summary",
            "buckets",
            "results",
        ),
        default_fields=(
            "mode",
            "ranked_count",
            "matched_count",
            "radar_count",
            "no_data_count",
            "error_count",
            "trade_date",
            "is_current",
            "stale_stock_count",
            "cache_status",
            "snapshot_id",
            "snapshot_date",
            "calculated_at",
            "data_limitations",
            "radar_engine",
            "radar_v2_summary",
            "buckets",
            "results",
        ),
        default_limit=20,
    ),
    CapabilitySpec(
        capability_id="watchlist.coverage",
        domain=None,
        slot="data_quality",
        scopes=("watchlist", "us_watchlist", "jp_watchlist", "kr_watchlist"),
        paths=("compact.evidence_coverage", "compact.resources"),
        fields=(
            "institutional",
            "margin",
            "revenue",
            "financial",
            "broker_branch",
            "requested_symbol_count",
            "ranked_count",
            "no_data_count",
            "radar_result_count",
            "include_intraday",
            "intraday_result_count",
        ),
        default_fields=(
            "institutional",
            "margin",
            "revenue",
            "financial",
            "broker_branch",
            "requested_symbol_count",
            "ranked_count",
            "no_data_count",
            "radar_result_count",
            "include_intraday",
            "intraday_result_count",
        ),
        default_limit=20,
    ),
    CapabilitySpec(
        capability_id="portfolio.summary",
        domain=None,
        slot="data_quality",
        scopes=("portfolio",),
        paths=("data.summary", "compact.resources"),
        fields=(
            "holding_count",
            "priced_holding_count",
            "missing_price_count",
            "stale_price_count",
            "market_counts",
            "currencies",
        ),
        default_fields=(
            "holding_count",
            "priced_holding_count",
            "missing_price_count",
            "stale_price_count",
            "market_counts",
            "currencies",
        ),
        default_limit=20,
    ),
    CapabilitySpec(
        capability_id="portfolio.holdings",
        domain=None,
        slot="holdings",
        scopes=("portfolio",),
        paths=("data.holdings",),
        fields=(
            "id",
            "market",
            "symbol",
            "display_name",
            "quantity",
            "currency",
            "cost_amount",
            "average_cost",
            "latest_price",
            "price_as_of",
            "price_age_days",
            "price_provider",
            "price_source",
            "market_value",
            "unrealized_pnl",
            "unrealized_pnl_pct",
            "weight_within_currency",
        ),
        default_fields=(
            "market",
            "symbol",
            "display_name",
            "quantity",
            "currency",
            "cost_amount",
            "average_cost",
            "latest_price",
            "price_as_of",
            "price_age_days",
            "market_value",
            "unrealized_pnl",
            "unrealized_pnl_pct",
            "weight_within_currency",
        ),
        default_limit=50,
    ),
    CapabilitySpec(
        capability_id="portfolio.valuation",
        domain=None,
        slot="valuation",
        scopes=("portfolio",),
        paths=("data.valuation", "compact.resources.valuation"),
        fields=(
            "cost_by_currency",
            "market_value_by_currency",
            "unrealized_pnl_by_currency",
            "cross_currency_total",
        ),
        default_fields=(
            "cost_by_currency",
            "market_value_by_currency",
            "unrealized_pnl_by_currency",
            "cross_currency_total",
        ),
        default_limit=20,
    ),
    CapabilitySpec(
        capability_id="macro.series",
        domain=None,
        slot="identity",
        scopes=("us_macro",),
        paths=("data.series",),
        fields=(
            "series_id",
            "series_name",
            "unit",
            "frequency",
            "provider",
        ),
        default_fields=(
            "series_id",
            "series_name",
            "unit",
            "frequency",
            "provider",
        ),
        default_limit=1,
    ),
    CapabilitySpec(
        capability_id="macro.observations",
        domain=None,
        slot="observations",
        scopes=("us_macro",),
        paths=("data.observations",),
        fields=(
            "series_id",
            "observation_date",
            "value",
            "unit",
            "frequency",
            "provider",
            "fetched_at",
        ),
        default_fields=(
            "observation_date",
            "value",
            "unit",
            "frequency",
            "provider",
        ),
        default_limit=24,
    ),
    CapabilitySpec(
        capability_id="resource.metadata",
        domain=None,
        slot="identity",
        scopes=("resource_asset",),
        paths=("data.instrument", "compact.resources.instrument"),
        fields=(
            "symbol",
            "display_name",
            "name",
            "asset_class",
            "provider",
            "provider_status",
            "currency",
            "quote_asset",
            "timezone",
            "watch_only",
        ),
        default_fields=(
            "symbol",
            "display_name",
            "asset_class",
            "provider",
            "provider_status",
            "currency",
            "quote_asset",
            "watch_only",
        ),
        default_limit=1,
    ),
    CapabilitySpec(
        capability_id="crypto.order_book",
        domain="order_book",
        slot="flows_liquidity",
        scopes=("crypto_asset", "crypto_market"),
        paths=("compact.order_book", "data.order_book", "data.order_books"),
        fields=(
            "as_of",
            "provider",
            "exchange",
            "symbol",
            "instrument_type",
            "depth_limit",
            "bid",
            "ask",
            "best_bid_price",
            "best_bid_size",
            "best_ask_price",
            "best_ask_size",
            "spread",
            "spread_pct",
            "bids",
            "asks",
            "event_time",
            "fetched_at",
            "source",
            "freshness",
        ),
        default_fields=(
            "provider",
            "symbol",
            "instrument_type",
            "depth_limit",
            "best_bid_price",
            "best_bid_size",
            "best_ask_price",
            "best_ask_size",
            "spread",
            "spread_pct",
            "event_time",
            "fetched_at",
            "freshness",
        ),
        default_limit=10,
        fill_operations=(("crypto_asset", "crypto.refresh_order_book"),),
    ),
    CapabilitySpec(
        capability_id="crypto.derivatives",
        domain="derivatives",
        slot="derivatives",
        scopes=("crypto_asset", "crypto_market"),
        paths=("compact.derivatives", "data.derivatives"),
        fields=(
            "as_of",
            "provider",
            "exchange",
            "symbol",
            "instrument_type",
            "mark_price",
            "index_price",
            "funding_rate",
            "next_funding_time",
            "open_interest",
            "open_interest_value",
            "long_short_ratio",
            "liquidations",
            "event_time",
            "fetched_at",
            "source",
            "freshness",
        ),
        default_fields=(
            "provider",
            "symbol",
            "instrument_type",
            "mark_price",
            "index_price",
            "funding_rate",
            "next_funding_time",
            "open_interest",
            "open_interest_value",
            "event_time",
            "fetched_at",
            "long_short_ratio",
            "liquidations",
            "freshness",
        ),
        default_limit=10,
        fill_operations=(("crypto_asset", "crypto.refresh_derivatives"),),
    ),
    CapabilitySpec(
        capability_id="diagnostics.capabilities",
        domain="capability_status",
        slot="data_quality",
        scopes=("capability_status",),
        paths=("compact",),
        fields=(
            "kind",
            "version",
            "target",
            "summary",
            "capabilities",
            "slots",
            "missing",
            "warnings",
        ),
        default_fields=(
            "kind",
            "version",
            "target",
            "summary",
            "capabilities",
            "missing",
            "warnings",
        ),
        default_limit=50,
    ),
    CapabilitySpec(
        capability_id="diagnostics.data_freshness",
        domain="freshness",
        slot="data_quality",
        scopes=("data_freshness",),
        paths=("compact",),
        fields=(
            "kind",
            "version",
            "target",
            "status",
            "tables",
            "resources",
            "freshness_by_domain",
            "health_dimensions",
            "as_of_by_domain",
            "slots",
        ),
        default_fields=(
            "kind",
            "version",
            "target",
            "status",
            "resources",
            "freshness_by_domain",
            "health_dimensions",
            "as_of_by_domain",
        ),
        default_limit=50,
    ),
    CapabilitySpec(
        capability_id="diagnostics.source_health",
        schema_version="omi.diagnostics.source_health.v1",
        domain="source_health",
        slot="data_quality",
        scopes=("*",),
        paths=(
            "compact.source_health",
            "data.source_health",
            "freshness.source_health",
            "data",
        ),
        fields=(
            "status",
            "as_of",
            "filters",
            "summary",
            "entries",
            "provider_events",
            "warnings",
            "freshness",
            "slots",
            "compact",
            "returned_count",
            "truncated",
            "is_partial",
        ),
        default_fields=(
            "status",
            "as_of",
            "filters",
            "summary",
            "entries",
            "provider_events",
            "warnings",
            "freshness",
            "returned_count",
            "truncated",
            "is_partial",
        ),
        default_limit=200,
    ),
    CapabilitySpec(
        capability_id="source.health",
        domain="source_health",
        slot="data_quality",
        scopes=("*",),
        paths=("compact.source_health", "data.source_health", "freshness.source_health"),
        fields=(
            "status",
            "as_of",
            "entries",
            "summary",
            "provider_events",
            "warnings",
        ),
        default_fields=("status", "as_of", "summary", "warnings"),
        default_limit=20,
        deprecated=True,
        replacement_capabilities=("diagnostics.source_health",),
    ),
    CapabilitySpec(
        capability_id="data.freshness",
        domain=None,
        slot="data_quality",
        scopes=("*",),
        paths=("freshness",),
        fields=(
            "status",
            "as_of",
            "is_current",
            "expected_date",
            "expected_dates",
            "datasets",
            "missing",
            "warnings",
        ),
        default_fields=(
            "status",
            "as_of",
            "is_current",
            "expected_date",
            "expected_dates",
            "datasets",
            "missing",
            "warnings",
        ),
        default_limit=20,
    ),
)

CAPABILITIES = {spec.capability_id: spec for spec in CAPABILITY_SPECS}
CAPABILITY_ALIASES = {
    "source.health": "diagnostics.source_health",
}

DOMAIN_CAPABILITIES = {
    "quote": ("quote.snapshot",),
    "intraday": ("intraday.bars",),
    "chart": ("daily.ohlcv",),
    "technical": ("technical.structure",),
    "chips": (
        "chips.institutional",
        "chips.margin",
        "ownership.distribution",
        "market.chips",
    ),
    "fundamentals": (
        "fundamentals.revenue",
        "fundamentals.financials",
    ),
    "broker_branch": ("broker_branch.summary",),
    "cross_market": (
        "cross_market.overnight",
        "cross_market.relations",
        "cross_market.parity",
        "market.cross_market",
    ),
    "derivatives": (
        "crypto.derivatives",
        "derivatives.positioning",
        "derivatives.structure",
    ),
    "breadth": ("market.breadth",),
    "indices": ("market.indices",),
    "sectors": ("market.sectors",),
    "index_contributions": ("market.index_contributions",),
    "volume": ("market.volume_state",),
    "sample_ranking": ("market.sample_ranking",),
    "screening": (
        "screening.ranking",
        "screening.coverage",
        "screening.intraday",
        "market.hot_groups",
    ),
    "hot_groups": ("market.hot_groups",),
    "events": (
        "events.upcoming",
        "events.history",
        "events.calendar",
    ),
    "regulation": (
        "regulation.disposition",
        "regulation.trading_restrictions",
    ),
    "source_health": ("source.health",),
    "freshness": ("data.freshness",),
}
SCOPE_DOMAIN_CAPABILITIES = {
    "market": {
        "events": ("events.calendar",),
    },
    "stock": {
        "events": ("events.upcoming", "events.history"),
        "regulation": (
            "regulation.disposition",
            "regulation.trading_restrictions",
        ),
    },
    "tw_futures": {
        # Futures volume is contract-count data. The cumulative session value
        # remains on quote.snapshot, while intraday.bars exposes interval
        # contract volume. It must not fall through to the cash-market
        # market.volume_state capability.
        "volume": ("intraday.bars",),
    },
}


def _string_list(value: Any, *, name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple, set)):
        raise ValueError(f"{name} must be an array of strings.")
    output: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if not text:
            continue
        if text not in output:
            output.append(text)
    return tuple(output)


SCOPE_MARKETS = {
    "market": "TW",
    "stock": "TW",
    "watchlist": "TW",
    "tw_index": "TW",
    "tw_futures": "TW",
    "us_stock": "US",
    "us_watchlist": "US",
    "us_macro": "US",
    "jp_stock": "JP",
    "jp_index": "JP",
    "jp_watchlist": "JP",
    "kr_stock": "KR",
    "kr_index": "KR",
    "kr_watchlist": "KR",
    "crypto_market": "CRYPTO",
    "crypto_asset": "CRYPTO",
    "resource_asset": "RESOURCE",
}


def _target_market(scope_type: str, target_market: str | None) -> str | None:
    normalized = str(target_market or "").strip().upper()
    if normalized in {"TWSE", "TPEX", "TAIWAN"}:
        return "TW"
    if normalized:
        return normalized
    return SCOPE_MARKETS.get(scope_type)


def _compatible(
    spec: CapabilitySpec,
    scope_type: str,
    target_market: str | None = None,
) -> bool:
    if "*" not in spec.scopes and scope_type not in spec.scopes:
        return False
    if not spec.markets:
        return True
    normalized_market = _target_market(scope_type, target_market)
    return normalized_market in spec.markets


def _default_capabilities(scope_type: str, question_intent: str) -> tuple[str, ...]:
    if scope_type == "capability_status":
        return ("target.identity", "diagnostics.capabilities")
    if scope_type == "source_health":
        return ("target.identity", "diagnostics.source_health")
    if scope_type == "data_freshness":
        return ("target.identity", "diagnostics.data_freshness")
    if question_intent == "quote":
        return ("target.identity", "quote.snapshot", "data.freshness")
    if question_intent == "regulation":
        return (
            "target.identity",
            "regulation.disposition",
            "regulation.trading_restrictions",
            "data.freshness",
        )
    if question_intent == "broker_branch":
        return (
            "target.identity",
            "quote.snapshot",
            "broker_branch.summary",
            "data.freshness",
        )
    if question_intent == "cross_market" and scope_type == "stock":
        return (
            "target.identity",
            "cross_market.overnight",
            "cross_market.relations",
            "cross_market.parity",
            "data.freshness",
        )
    if scope_type in {"crypto_asset", "crypto_market"}:
        return (
            "target.identity",
            "quote.snapshot",
            "intraday.bars",
            "crypto.order_book",
            "data.freshness",
        )
    if scope_type == "market":
        return (
            "target.identity",
            "market.breadth",
            "market.sample_ranking",
            "market.cross_market",
            "market.chips",
            "market.volume_state",
            "data.freshness",
        )
    if scope_type == "tw_futures":
        return (
            "target.identity",
            "quote.snapshot",
            "daily.ohlcv",
            "technical.structure",
            "derivatives.positioning",
            "derivatives.structure",
            "data.freshness",
        )
    if scope_type in {"watchlist", "us_watchlist", "jp_watchlist", "kr_watchlist"}:
        return (
            "target.identity",
            "watchlist.ranking",
            "watchlist.radar",
            "watchlist.coverage",
            "data.freshness",
        )
    if scope_type == "portfolio":
        return (
            "target.identity",
            "portfolio.summary",
            "portfolio.holdings",
            "portfolio.valuation",
            "data.freshness",
        )
    if scope_type == "us_macro":
        return (
            "target.identity",
            "macro.series",
            "macro.observations",
            "data.freshness",
        )
    if scope_type == "resource_asset":
        return (
            "target.identity",
            "resource.metadata",
            "quote.snapshot",
            "daily.ohlcv",
            "technical.structure",
            "data.freshness",
        )
    if scope_type in {"tw_index", "jp_index", "kr_index"}:
        return (
            "target.identity",
            "quote.snapshot",
            "market.breadth",
            "data.freshness",
        )
    if scope_type == "us_stock":
        return (
            "target.identity",
            "company.profile",
            "quote.snapshot",
            "daily.ohlcv",
            "technical.structure",
            "fundamentals.financials",
            "corporate.actions",
            "market.short_volume",
            "data.freshness",
        )
    if scope_type in ALL_STOCK_SCOPES:
        return (
            "target.identity",
            "quote.snapshot",
            "daily.ohlcv",
            "technical.structure",
            "data.freshness",
        )
    return ("target.identity", "data.freshness")


def _capabilities_from_domains(
    domains: tuple[str, ...],
    *,
    scope_type: str | None = None,
) -> tuple[str, ...]:
    output: list[str] = []
    for domain in domains:
        scoped_capabilities = SCOPE_DOMAIN_CAPABILITIES.get(
            str(scope_type or ""),
            {},
        )
        for capability_id in scoped_capabilities.get(
            domain,
            DOMAIN_CAPABILITIES.get(domain, ()),
        ):
            if capability_id not in output:
                output.append(capability_id)
    return tuple(output)


def _canonical_capability_id(capability_id: Any) -> str:
    normalized = str(capability_id or "").strip()
    return CAPABILITY_ALIASES.get(normalized, normalized)


def _canonicalize_capability_mapping(
    raw_mapping: Any,
    *,
    name: str,
) -> Any:
    if raw_mapping is None or not isinstance(raw_mapping, dict):
        return raw_mapping
    output: dict[str, Any] = {}
    for raw_key, value in raw_mapping.items():
        key = _canonical_capability_id(raw_key)
        if key in output and output[key] != value:
            raise ValueError(
                f"{name} provides conflicting values for capability alias {raw_key} "
                f"and canonical capability {key}."
            )
        output[key] = value
    return output


def _normalized_fields(
    raw_fields: Any,
    *,
    selected: tuple[str, ...],
    ignored_capabilities: frozenset[str] = frozenset(),
) -> dict[str, list[str]]:
    if raw_fields is None:
        return {}
    if not isinstance(raw_fields, dict):
        raise ValueError("selection.fields must be an object keyed by capability id.")
    output: dict[str, list[str]] = {}
    for capability_id, raw_values in raw_fields.items():
        normalized_id = str(capability_id or "").strip()
        spec = CAPABILITIES.get(normalized_id)
        if spec is None:
            raise ValueError(f"Unknown capability in selection.fields: {normalized_id}")
        if normalized_id in ignored_capabilities:
            continue
        if normalized_id not in selected:
            raise ValueError(
                f"selection.fields references unselected capability: {normalized_id}"
            )
        fields = _string_list(
            raw_values,
            name=f"selection.fields.{normalized_id}",
        )
        unknown_fields = [field for field in fields if field not in spec.fields]
        if unknown_fields:
            raise ValueError(
                f"Unsupported field(s) for {normalized_id}: {', '.join(unknown_fields)}"
            )
        output[normalized_id] = list(fields)
    return output


def _normalized_limits(
    raw_limits: Any,
    *,
    ignored_capabilities: frozenset[str] = frozenset(),
    clamp: bool = True,
) -> dict[str, int]:
    if raw_limits is None:
        return {}
    if not isinstance(raw_limits, dict):
        raise ValueError("selection.limits must be an object.")
    output: dict[str, int] = {}
    allowed_aliases = {"intraday.points", "daily.points", "history.points"}
    for raw_key, raw_value in raw_limits.items():
        key = str(raw_key or "").strip()
        if key not in CAPABILITIES and key not in allowed_aliases:
            raise ValueError(f"Unknown selection limit key: {key}")
        if key in ignored_capabilities:
            continue
        if isinstance(raw_value, bool) or not isinstance(raw_value, int):
            raise ValueError(f"selection.limits.{key} must be an integer.")
        output[key] = (
            max(1, min(raw_value, MAX_CAPABILITY_LIMIT))
            if clamp
            else raw_value
        )
    return output


def _validate_parameter_value(
    value: Any,
    *,
    schema: dict[str, Any],
    path: str,
) -> Any:
    expected_type = str(schema.get("type") or "").strip()
    if expected_type == "object":
        if not isinstance(value, dict):
            raise ValueError(f"{path} must be an object.")
        properties = schema.get("properties")
        properties = properties if isinstance(properties, dict) else {}
        required = {
            str(item)
            for item in schema.get("required", [])
            if str(item).strip()
        }
        missing = sorted(required - set(value))
        if missing:
            raise ValueError(
                f"{path} is missing required parameter(s): {', '.join(missing)}"
            )
        if schema.get("additionalProperties") is False:
            unknown = sorted(set(value) - set(properties))
            if unknown:
                raise ValueError(
                    f"{path} contains unsupported parameter(s): "
                    + ", ".join(unknown)
                )
        return {
            key: _validate_parameter_value(
                item,
                schema=(
                    properties.get(key)
                    if isinstance(properties.get(key), dict)
                    else {}
                ),
                path=f"{path}.{key}",
            )
            for key, item in value.items()
        }
    if expected_type == "array":
        if not isinstance(value, list):
            raise ValueError(f"{path} must be an array.")
        max_items = schema.get("maxItems")
        if isinstance(max_items, int) and len(value) > max_items:
            raise ValueError(f"{path} must contain at most {max_items} items.")
        item_schema = schema.get("items")
        item_schema = item_schema if isinstance(item_schema, dict) else {}
        return [
            _validate_parameter_value(
                item,
                schema=item_schema,
                path=f"{path}[{index}]",
            )
            for index, item in enumerate(value)
        ]
    if expected_type == "string":
        if not isinstance(value, str):
            raise ValueError(f"{path} must be a string.")
        normalized = value.strip()
        if schema.get("format") == "date":
            try:
                date.fromisoformat(normalized)
            except ValueError as exc:
                raise ValueError(
                    f"{path} must use YYYY-MM-DD."
                ) from exc
        if "enum" in schema and normalized not in schema["enum"]:
            raise ValueError(
                f"{path} must be one of: "
                + ", ".join(str(item) for item in schema["enum"])
            )
        return normalized
    if expected_type == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{path} must be an integer.")
        if "enum" in schema and value not in schema["enum"]:
            raise ValueError(
                f"{path} must be one of: "
                + ", ".join(str(item) for item in schema["enum"])
            )
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if isinstance(minimum, int) and value < minimum:
            raise ValueError(f"{path} must be at least {minimum}.")
        if isinstance(maximum, int) and value > maximum:
            raise ValueError(f"{path} must be at most {maximum}.")
        return value
    if expected_type == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{path} must be a number.")
        if "enum" in schema and value not in schema["enum"]:
            raise ValueError(
                f"{path} must be one of: "
                + ", ".join(str(item) for item in schema["enum"])
            )
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if isinstance(minimum, (int, float)) and value < minimum:
            raise ValueError(f"{path} must be at least {minimum}.")
        if isinstance(maximum, (int, float)) and value > maximum:
            raise ValueError(f"{path} must be at most {maximum}.")
        return value
    if expected_type == "boolean":
        if not isinstance(value, bool):
            raise ValueError(f"{path} must be a boolean.")
        return value
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(
            f"{path} must be one of: "
            + ", ".join(str(item) for item in schema["enum"])
        )
    return value


def _normalized_parameters(
    raw_parameters: Any,
    *,
    selected: tuple[str, ...],
    ignored_capabilities: frozenset[str] = frozenset(),
) -> dict[str, dict[str, Any]]:
    if raw_parameters is None:
        return {}
    if not isinstance(raw_parameters, dict):
        raise ValueError(
            "selection.parameters must be an object keyed by capability id."
        )
    output: dict[str, dict[str, Any]] = {}
    for capability_id, raw_value in raw_parameters.items():
        normalized_id = str(capability_id or "").strip()
        spec = CAPABILITIES.get(normalized_id)
        if spec is None:
            raise ValueError(
                f"Unknown capability in selection.parameters: {normalized_id}"
            )
        if normalized_id in ignored_capabilities:
            continue
        if normalized_id not in selected:
            raise ValueError(
                "selection.parameters references unselected capability: "
                f"{normalized_id}"
            )
        if not isinstance(raw_value, dict):
            raise ValueError(
                f"selection.parameters.{normalized_id} must be an object."
            )
        if not spec.parameter_schema:
            if raw_value:
                raise ValueError(
                    f"{normalized_id} does not accept parameters."
                )
            output[normalized_id] = {}
            continue
        normalized_parameters = _validate_parameter_value(
            raw_value,
            schema=spec.parameter_schema,
            path=f"selection.parameters.{normalized_id}",
        )
        if normalized_id in {
            "events.calendar",
            "events.history",
            "events.upcoming",
        }:
            date_from = normalized_parameters.get("date_from")
            date_to = normalized_parameters.get("date_to")
            if (
                date_from
                and date_to
                and date.fromisoformat(date_to)
                < date.fromisoformat(date_from)
            ):
                raise ValueError(
                    f"selection.parameters.{normalized_id}.date_to "
                    "must not precede date_from."
                )
        if normalized_id == "screening.ranking":
            window = int(normalized_parameters.get("window") or 1)
            min_observed = normalized_parameters.get(
                "min_observed_periods"
            )
            if min_observed is not None and int(min_observed) > window:
                raise ValueError(
                    "selection.parameters.screening.ranking."
                    "min_observed_periods must not exceed window."
                )
        output[normalized_id] = normalized_parameters
    return output


def normalize_selection(
    *,
    selection: dict[str, Any] | None,
    output: str | None,
    realtime_policy: str | None,
    payload_level: str,
    scope_type: str,
    question_intent: str,
    target_market: str | None = None,
    requested_domains: tuple[str, ...] = (),
    excluded_domains: tuple[str, ...] = (),
    requested_capabilities: tuple[str, ...] = (),
    excluded_capabilities: tuple[str, ...] = (),
) -> dict[str, Any]:
    original_raw = selection if isinstance(selection, dict) else {}
    deprecated_aliases: list[dict[str, str]] = []

    def canonicalize_list(values: Any, *, name: str) -> tuple[str, ...]:
        output: list[str] = []
        for capability_id in _string_list(values, name=name):
            canonical_id = _canonical_capability_id(capability_id)
            if canonical_id != capability_id:
                alias_record = {
                    "alias": capability_id,
                    "canonical_capability": canonical_id,
                    "status": "deprecated_alias",
                }
                if alias_record not in deprecated_aliases:
                    deprecated_aliases.append(alias_record)
            if canonical_id not in output:
                output.append(canonical_id)
        return tuple(output)

    raw = {
        **original_raw,
        "fields": _canonicalize_capability_mapping(
            original_raw.get("fields"),
            name="selection.fields",
        ),
        "limits": _canonicalize_capability_mapping(
            original_raw.get("limits"),
            name="selection.limits",
        ),
        "parameters": _canonicalize_capability_mapping(
            original_raw.get("parameters"),
            name="selection.parameters",
        ),
    }
    explicit_include = canonicalize_list(
        original_raw.get("required") or original_raw.get("include"),
        name="selection.include",
    )
    explicit_optional = canonicalize_list(
        original_raw.get("optional"),
        name="selection.optional",
    )
    explicit_exclude = canonicalize_list(
        original_raw.get("exclude"),
        name="selection.exclude",
    )
    requested_capabilities = canonicalize_list(
        requested_capabilities,
        name="requested_capabilities",
    )
    excluded_capabilities = canonicalize_list(
        excluded_capabilities,
        name="excluded_capabilities",
    )
    if scope_type in DIAGNOSTIC_SCOPES:
        # Diagnostic targets describe OMI itself.  Natural-language mentions of
        # market domains (for example, "法人、融資、技術面") are inventory labels,
        # not a request to attach stock capabilities to the diagnostic target.
        requested_domains = ()
        excluded_domains = ()
        requested_capabilities = ()
        excluded_capabilities = ()
    requested_specific_domains = {
        CAPABILITIES[capability_id].domain
        for capability_id in requested_capabilities
        if capability_id in CAPABILITIES
    }
    legacy_include = (
        ()
        if scope_type in DIAGNOSTIC_SCOPES
        else tuple(
            capability_id
            for capability_id in _capabilities_from_domains(
                tuple(
                    domain
                    for domain in requested_domains
                    if domain not in requested_specific_domains
                ),
                scope_type=scope_type,
            )
            if _compatible(
                CAPABILITIES[capability_id],
                scope_type,
                target_market,
            )
        )
    )
    legacy_exclude = tuple(
        capability_id
        for capability_id in _capabilities_from_domains(
            tuple(
                domain
                for domain in excluded_domains
                if domain not in requested_specific_domains
            ),
            scope_type=scope_type,
        )
        if _compatible(
            CAPABILITIES[capability_id],
            scope_type,
            target_market,
        )
    )
    has_explicit_capability_selection = any(
        key in original_raw
        for key in ("required", "include", "optional")
    )
    auto_planning_requested = original_raw.get("auto_planning") is True
    explicit_selection_locked = (
        has_explicit_capability_selection
        and not auto_planning_requested
    )
    required = list(explicit_include)
    optional = list(explicit_optional)
    if not explicit_selection_locked:
        if not required:
            required.extend(
                capability_id
                for capability_id in _default_capabilities(
                    scope_type,
                    question_intent,
                )
                if _compatible(
                    CAPABILITIES[capability_id],
                    scope_type,
                    target_market,
                )
            )
        required.extend(legacy_include)
        required.extend(
            capability_id
            for capability_id in requested_capabilities
            if capability_id in CAPABILITIES
            and _compatible(
                CAPABILITIES[capability_id],
                scope_type,
                target_market,
            )
        )
    inferred_excluded = (*legacy_exclude, *excluded_capabilities)
    if explicit_selection_locked:
        explicitly_selected = {*explicit_include, *explicit_optional}
        inferred_excluded = tuple(
            capability_id
            for capability_id in inferred_excluded
            if capability_id not in explicitly_selected
        )
    excluded = list(
        dict.fromkeys((*explicit_exclude, *inferred_excluded))
    )

    mandatory_capabilities = (
        ("target.identity",)
        if scope_type in DIAGNOSTIC_SCOPES
        else ("target.identity", "data.freshness")
    )
    for mandatory in mandatory_capabilities:
        if mandatory not in required:
            required.insert(0 if mandatory == "target.identity" else len(required), mandatory)
        if mandatory in excluded:
            excluded.remove(mandatory)

    unknown = [
        capability_id
        for capability_id in (*required, *optional, *excluded)
        if capability_id not in CAPABILITIES
    ]
    if unknown:
        raise ValueError(f"Unknown capability id(s): {', '.join(dict.fromkeys(unknown))}")

    unsupported_capabilities: list[dict[str, Any]] = []

    def record_unsupported(
        capability_id: str,
        *,
        requested_as: str,
        request_source: str,
    ) -> None:
        if capability_id not in CAPABILITIES:
            return
        spec = CAPABILITIES[capability_id]
        if _compatible(spec, scope_type, target_market):
            return
        if any(
            item.get("capability") == capability_id
            for item in unsupported_capabilities
        ):
            return
        scope_supported = (
            "*" in spec.scopes or scope_type in spec.scopes
        )
        normalized_market = _target_market(scope_type, target_market)
        reason_code = (
            "unsupported_market"
            if scope_supported and spec.markets
            else "unsupported_target_scope"
        )
        unsupported_capabilities.append(
            {
                "capability": capability_id,
                "status": "unsupported",
                "reason_code": reason_code,
                "requested_as": requested_as,
                "request_source": request_source,
                "target_scope": scope_type,
                "target_market": normalized_market,
                "supported_scopes": list(spec.scopes),
                "supported_markets": list(spec.markets),
                "message": (
                    f"{capability_id} is not supported for target "
                    f"scope={scope_type}, market={normalized_market or 'unspecified'}."
                ),
            }
        )

    for capability_id in required:
        record_unsupported(
            capability_id,
            requested_as="required",
            request_source=(
                "explicit_selection"
                if capability_id in explicit_include
                else "derived_selection"
            ),
        )
    for capability_id in optional:
        record_unsupported(
            capability_id,
            requested_as="optional",
            request_source=(
                "explicit_selection"
                if capability_id in explicit_optional
                else "nlp_inferred"
            ),
        )
    if not explicit_selection_locked:
        for capability_id in requested_capabilities:
            record_unsupported(
                capability_id,
                requested_as="required",
                request_source="nlp_inferred",
            )
        requested_domain_capabilities = _capabilities_from_domains(
            tuple(
                domain
                for domain in requested_domains
                if domain not in requested_specific_domains
            ),
            scope_type=scope_type,
        )
        for capability_id in requested_domain_capabilities:
            record_unsupported(
                capability_id,
                requested_as="required",
                request_source="nlp_inferred",
            )

    unsupported_ids = frozenset(
        str(item["capability"]) for item in unsupported_capabilities
    )
    unmet_required_capabilities = [
        dict(item)
        for item in unsupported_capabilities
        if item.get("requested_as") == "required"
    ]
    required = [
        capability_id
        for capability_id in required
        if capability_id not in unsupported_ids
    ]
    optional = [
        capability_id
        for capability_id in optional
        if capability_id not in unsupported_ids
    ]

    required = [
        capability_id
        for capability_id in dict.fromkeys(required)
        if capability_id not in excluded
    ]
    optional = [
        capability_id
        for capability_id in dict.fromkeys(optional)
        if capability_id not in excluded and capability_id not in required
    ]
    selected = tuple((*required, *optional))
    fields = _normalized_fields(
        raw.get("fields"),
        selected=selected,
        ignored_capabilities=unsupported_ids,
    )
    limits = _normalized_limits(
        raw.get("limits"),
        ignored_capabilities=unsupported_ids,
    )
    requested_limits = _normalized_limits(
        raw.get("limits"),
        ignored_capabilities=unsupported_ids,
        clamp=False,
    )
    parameters = _normalized_parameters(
        raw.get("parameters"),
        selected=selected,
        ignored_capabilities=unsupported_ids,
    )

    requested_output = str(
        output or raw.get("output") or ""
    ).strip().lower() or None
    if requested_output is not None and requested_output not in OUTPUT_MODES:
        raise ValueError(
            f"output must be one of: {', '.join(sorted(OUTPUT_MODES))}"
        )
    output_mode = requested_output
    output_override_reason = None
    if scope_type in DIAGNOSTIC_SCOPES:
        if requested_output not in {None, "evidence_only"}:
            output_override_reason = "diagnostic_scope_forces_evidence_only"
        output_mode = "evidence_only"
    elif not output_mode:
        output_mode = (
            "evidence_only"
            if question_intent in {"quote", "data_freshness", "regulation"}
            else "decision_with_evidence"
        )

    realtime = str(realtime_policy or raw.get("realtime_policy") or "prefer_live").strip().lower()
    if realtime not in REALTIME_POLICIES:
        raise ValueError(
            "realtime_policy must be one of: "
            + ", ".join(sorted(REALTIME_POLICIES))
        )

    raw_max_bytes = raw.get("max_response_bytes")
    max_response_bytes = DEFAULT_RESPONSE_BYTES.get(payload_level, DEFAULT_RESPONSE_BYTES["compact"])
    if raw_max_bytes is not None:
        if isinstance(raw_max_bytes, bool) or not isinstance(raw_max_bytes, int):
            raise ValueError("selection.max_response_bytes must be an integer.")
        max_response_bytes = max(
            MIN_RESPONSE_BYTES,
            min(raw_max_bytes, MAX_RESPONSE_BYTES),
        )

    capability_origins: dict[str, dict[str, str]] = {}
    for capability_id in (*required, *optional):
        if capability_id in explicit_include:
            origin = "explicit_required"
            requested_as = "required"
        elif capability_id in explicit_optional:
            origin = "explicit_optional"
            requested_as = "optional"
        elif capability_id in mandatory_capabilities:
            origin = "target_required"
            requested_as = "required"
        elif capability_id in (*legacy_include, *requested_capabilities):
            origin = "nlp_inferred"
            requested_as = (
                "optional"
                if explicit_selection_locked
                else "required"
            )
        else:
            origin = "auto_planned"
            requested_as = (
                "required"
                if capability_id in required
                else "optional"
            )
        capability_origins[capability_id] = {
            "origin": origin,
            "requested_as": requested_as,
        }

    return {
        "version": public_contract.CAPABILITY_SELECTION_VERSION,
        "output": output_mode,
        "requested_output": requested_output,
        "effective_output": output_mode,
        "output_override_reason": output_override_reason,
        "realtime_policy": realtime,
        "target_market": _target_market(scope_type, target_market),
        "required": required,
        "optional": optional,
        "excluded": excluded,
        "fields": fields,
        "limits": limits,
        "requested_limits": requested_limits,
        "parameters": parameters,
        "capability_origins": capability_origins,
        "inference_policy": (
            "explicit_selection_locked"
            if explicit_selection_locked
            else "auto_planning_enabled"
            if auto_planning_requested
            else "automatic_selection"
        ),
        "unsupported_capabilities": unsupported_capabilities,
        "unmet_required_capabilities": unmet_required_capabilities,
        "deprecated_aliases": deprecated_aliases,
        "max_response_bytes": max_response_bytes,
    }


def capability_catalog(
    *,
    scope_type: str | None = None,
    target_market: str | None = None,
) -> list[dict[str, Any]]:
    return [
        spec.as_public_dict()
        for spec in CAPABILITY_SPECS
        if scope_type is None
        or _compatible(spec, scope_type, target_market)
    ]


def domains_for_selection(selection: dict[str, Any]) -> tuple[str, ...]:
    output: list[str] = []
    for capability_id in list(selection.get("required") or []) + list(
        selection.get("optional") or []
    ):
        spec = CAPABILITIES.get(str(capability_id))
        if spec is None or spec.domain is None or spec.domain in output:
            continue
        output.append(spec.domain)
    return tuple(output)


def _path_value(source: dict[str, Any], path: str) -> Any:
    value: Any = source
    for key in path.split("."):
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


def _project_fields(
    value: Any,
    *,
    fields: tuple[str, ...],
    limit: int,
) -> Any:
    if isinstance(value, dict):
        selected = (
            {field: value[field] for field in fields if field in value}
            if fields
            else dict(value)
        )
        return {
            key: _bounded_value(item, limit=limit)
            for key, item in selected.items()
        }
    if isinstance(value, list) and fields:
        return [
            {
                field: _bounded_value(item[field], limit=limit)
                for field in fields
                if isinstance(item, dict) and field in item
            }
            if isinstance(item, dict)
            else _bounded_value(item, limit=limit)
            for item in value[-limit:]
        ]
    return _bounded_value(value, limit=limit)


def _bounded_value(value: Any, *, limit: int, depth: int = 0) -> Any:
    if depth >= 6:
        return None
    if isinstance(value, list):
        bounded = value[-limit:] if len(value) > limit else value
        return [
            _bounded_value(item, limit=limit, depth=depth + 1)
            for item in bounded
        ]
    if isinstance(value, dict):
        return {
            str(key): _bounded_value(item, limit=limit, depth=depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, str) and len(value) > 4_000:
        return value[:4_000]
    return value


def _series_point_sort_key(point: Any) -> datetime:
    if not isinstance(point, dict):
        return datetime.min.replace(tzinfo=timezone.utc)
    for key in ("bar_time", "event_time", "time", "date", "trade_date"):
        raw_value = point.get(key)
        if isinstance(raw_value, datetime):
            parsed = raw_value
        else:
            text = str(raw_value or "").strip()
            if not text:
                continue
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError:
                continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return datetime.min.replace(tzinfo=timezone.utc)


def _normalize_intraday_order(value: dict[str, Any]) -> dict[str, Any]:
    output = dict(value)
    for key in ("points", "bars"):
        rows = output.get(key)
        if not isinstance(rows, list):
            continue
        output[key] = sorted(rows, key=_series_point_sort_key)
        output["sort_order"] = "asc"
    rows = (
        output.get("points")
        if isinstance(output.get("points"), list)
        else output.get("bars")
        if isinstance(output.get("bars"), list)
        else []
    )
    if rows and isinstance(rows[-1], dict):
        output["latest_point"] = rows[-1]
        output["event_time"] = (
            rows[-1].get("event_time")
            or rows[-1].get("bar_time")
            or rows[-1].get("time")
            or output.get("event_time")
        )
    return output


def _canonical_intraday_value(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    series = value.get("series")
    if not isinstance(series, dict):
        return _normalize_intraday_order(value)

    selected_key: str | None = None
    selected: dict[str, Any] = {}
    for key in ("1m", "5m"):
        candidate = series.get(key)
        if isinstance(candidate, dict) and (
            candidate.get("points")
            or candidate.get("bars")
            or candidate.get("latest")
            or candidate.get("returned_point_count")
        ):
            selected_key = key
            selected = candidate
            break
    if not selected:
        for key, candidate in series.items():
            if isinstance(candidate, dict):
                selected_key = str(key)
                selected = candidate
                break
    if not selected:
        return value

    output = {
        key: item
        for key, item in value.items()
        if key != "series"
    }
    output.setdefault("interval", selected.get("interval") or selected_key)
    for key in (
        "session",
        "session_scope",
        "session_phase",
        "market_status",
        "official_close_status",
        "delivery_status",
        "is_current_session",
        "requested_interval",
        "source_interval",
        "effective_interval",
        "interval_status",
        "sampling_mode",
        "original_point_count",
        "point_count",
        "returned_point_count",
        "points",
        "bars",
        "latest",
        "bar_time",
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "base_volume",
        "base_volume_unit",
        "volume_unit",
        "canonical_volume_unit",
        "provider_volume_unit",
        "volume_conversion",
        "volume_shares",
        "volume_lots",
        "volume_contracts",
        "volume_event_time",
        "cumulative_volume",
        "cumulative_volume_unit",
        "cumulative_volume_contracts",
        "cumulative_volume_shares",
        "cumulative_volume_lots",
        "cumulative_trade_value",
        "available_cumulative_trade_value",
        "estimated_cumulative_trade_value",
        "lot_size",
        "quote_volume",
        "quote_volume_unit",
        "currency",
        "price_unit",
        "event_time",
        "fetched_at",
        "received_at",
        "source",
        "provider",
        "freshness",
        "continuity",
        "volume_semantics",
        "volume_status",
        "trade_value_unit",
        "trade_value_status",
        "official_vwap",
        "approx_vwap",
        "vwap_method",
        "vwap_confidence",
        "aggregation_method",
        "source_point_count",
        "aggregated_point_count",
        "partial_bar_count",
        "cache_status",
        "cache_hit",
        "cache_trade_date",
        "cache_latest_time",
        "cached_count",
        "refreshed_count",
        "fallback_used",
        "market_events",
        "sessions",
        "sort_order",
    ):
        if key not in output and key in selected:
            output[key] = selected[key]
    output = _normalize_intraday_order(output)
    points = output.get("points") if isinstance(output.get("points"), list) else []
    latest_point = (
        selected.get("latest_point")
        if isinstance(selected.get("latest_point"), dict)
        else selected.get("latest")
        if isinstance(selected.get("latest"), dict)
        else points[-1]
        if points
        else None
    )
    if latest_point is not None:
        output["latest_point"] = latest_point
        output["event_time"] = (
            latest_point.get("event_time")
            or latest_point.get("bar_time")
            or latest_point.get("time")
            or output.get("event_time")
        )
    return output


def _canonical_capability_value(
    capability_id: str,
    value: Any,
) -> Any:
    if capability_id == "intraday.bars":
        return _canonical_intraday_value(value)
    return value


def _reconcile_projected_series_counts(
    capability_id: str,
    value: Any,
    *,
    original_value: Any = None,
) -> Any:
    if not isinstance(value, dict):
        return value
    if capability_id == "diagnostics.source_health":
        entries = value.get("entries")
        if not isinstance(entries, list):
            return value
        original_entries = (
            original_value.get("entries")
            if isinstance(original_value, dict)
            and isinstance(original_value.get("entries"), list)
            else []
        )
        summary = (
            dict(value.get("summary"))
            if isinstance(value.get("summary"), dict)
            else {}
        )
        entry_count = summary.get("total_entry_count")
        if not isinstance(entry_count, int):
            entry_count = summary.get("entry_count")
        if not isinstance(entry_count, int):
            entry_count = (
                len(original_entries)
                if original_entries
                else len(entries)
            )
        problem_statuses = {
            "missing",
            "empty",
            "stale",
            "delayed",
            "error",
            "blocked",
            "disabled",
        }
        total_problem_count = summary.get("total_problem_count")
        if not isinstance(total_problem_count, int):
            total_problem_count = summary.get("problem_count")
        if not isinstance(total_problem_count, int):
            total_problem_count = sum(
                1
                for entry in original_entries
                if isinstance(entry, dict)
                and str(entry.get("status") or "") in problem_statuses
            )
        returned_problem_count = sum(
            1
            for entry in entries
            if isinstance(entry, dict)
            and str(entry.get("status") or "") in problem_statuses
        )
        summary["entry_count"] = entry_count
        summary["total_entry_count"] = entry_count
        summary.setdefault("matched_entry_count", entry_count)
        summary["returned_entry_count"] = len(entries)
        summary["problem_count"] = total_problem_count
        summary["total_problem_count"] = total_problem_count
        summary["returned_problem_count"] = returned_problem_count
        value["summary"] = summary
        value["returned_count"] = len(entries)
        value["truncated"] = entry_count > len(entries)
        value["is_partial"] = value["truncated"]
        return value
    if capability_id not in {"intraday.bars", "daily.ohlcv"}:
        return value
    rows = (
        value.get("points")
        if isinstance(value.get("points"), list)
        else value.get("bars")
        if isinstance(value.get("bars"), list)
        else None
    )
    if rows is None:
        return value
    value["returned_point_count"] = len(rows)
    point_count = value.get("point_count")
    value["truncated"] = bool(
        isinstance(point_count, int) and point_count > len(rows)
    )
    if capability_id == "intraday.bars" and rows:
        value["latest_point"] = rows[-1]
        value["event_time"] = (
            rows[-1].get("event_time")
            or rows[-1].get("bar_time")
            or rows[-1].get("time")
            if isinstance(rows[-1], dict)
            else None
        )
    return value


def project_selected_data(
    *,
    response: dict[str, Any],
    selection: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    result = response.get("result") if isinstance(response.get("result"), dict) else {}
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    compact = data.get("compact") if isinstance(data.get("compact"), dict) else {}
    freshness = response.get("freshness")
    if not isinstance(freshness, dict) or not freshness:
        freshness = result.get("freshness")
    if not isinstance(freshness, dict) or not freshness:
        freshness = data.get("freshness")
    freshness = dict(freshness) if isinstance(freshness, dict) else {}
    if freshness:
        freshness.setdefault("as_of", result.get("as_of"))
        if not freshness.get("status"):
            if freshness.get("is_current") is True:
                freshness["status"] = "current"
            elif freshness.get("missing"):
                freshness["status"] = "missing"
            else:
                freshness["status"] = "stale"
    source = {
        "target": response.get("target") or {},
        "result": result,
        "data": data,
        "compact": compact,
        "freshness": freshness,
    }
    projected: dict[str, Any] = {}
    unavailable: list[str] = []
    selected = list(selection.get("required") or []) + list(selection.get("optional") or [])
    field_map = selection.get("fields") if isinstance(selection.get("fields"), dict) else {}
    limit_map = selection.get("limits") if isinstance(selection.get("limits"), dict) else {}
    aliases = {
        "intraday.bars": "intraday.points",
        "daily.ohlcv": "daily.points",
    }
    for capability_id in selected:
        spec = CAPABILITIES[capability_id]
        raw_value = None
        for path in spec.paths:
            raw_value = _path_value(source, path)
            if raw_value not in (None, {}, []):
                break
        if raw_value in (None, {}, []):
            unavailable.append(capability_id)
            continue
        raw_value = _canonical_capability_value(capability_id, raw_value)
        fields = tuple(field_map.get(capability_id) or spec.default_fields)
        raw_limit = limit_map.get(
            capability_id,
            limit_map.get(aliases.get(capability_id, ""), spec.default_limit),
        )
        projected[capability_id] = _reconcile_projected_series_counts(
            capability_id,
            _project_fields(
                raw_value,
                fields=fields,
                limit=int(raw_limit),
            ),
            original_value=raw_value,
        )
    return projected, unavailable


def normalize_status(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("status")
    return str(value or "unknown").strip().lower().replace("-", "_").replace(" ", "_")


def status_class(value: Any) -> str:
    status = normalize_status(value)
    if status in READY_STATUSES:
        return "ready"
    if status in LIMITED_STATUSES:
        return "limited"
    if status in NEUTRAL_STATUSES:
        return "neutral"
    return "blocked"


def _projected_returned_count(value: Any, *, included: bool) -> int:
    if not included:
        return 0
    if isinstance(value, list):
        return len(value)
    if not isinstance(value, dict):
        return 1
    for key in (
        "returned_count",
        "returned_point_count",
        "returned_entry_count",
    ):
        count = value.get(key)
        if isinstance(count, int) and not isinstance(count, bool):
            return max(0, count)
    for key in (
        "rows",
        "items",
        "events",
        "actions",
        "entries",
        "points",
        "bars",
        "results",
    ):
        rows = value.get(key)
        if isinstance(rows, list):
            return len(rows)
    return 1


def build_manifest(
    *,
    canonical: dict[str, Any],
    selection: dict[str, Any],
    projected_data: dict[str, Any],
    realtime_assessments: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    evidence = canonical.get("evidence") if isinstance(canonical.get("evidence"), dict) else {}
    target = canonical.get("target") if isinstance(canonical.get("target"), dict) else {}
    raw_scope_type = str(target.get("type") or "").strip()
    scope_type = {
        "tw_stock": "stock",
    }.get(raw_scope_type, raw_scope_type)
    freshness_by_domain = (
        evidence.get("freshness_by_domain")
        if isinstance(evidence.get("freshness_by_domain"), dict)
        else {}
    )
    freshness_by_capability = (
        evidence.get("freshness_by_capability")
        if isinstance(evidence.get("freshness_by_capability"), dict)
        else {}
    )
    slots = evidence.get("slots") if isinstance(evidence.get("slots"), dict) else {}
    quality = (
        evidence.get("quality")
        if isinstance(evidence.get("quality"), dict)
        else {}
    )
    quality_by_capability = (
        quality.get("capabilities")
        if isinstance(quality.get("capabilities"), dict)
        else {}
    )
    required = set(selection.get("required") or [])
    capabilities: list[dict[str, Any]] = []
    for capability_id in list(selection.get("required") or []) + list(selection.get("optional") or []):
        spec = CAPABILITIES[capability_id]
        slot = slots.get(spec.slot) if spec.slot and isinstance(slots.get(spec.slot), dict) else {}
        capability_freshness = (
            freshness_by_capability.get(capability_id)
            if isinstance(freshness_by_capability.get(capability_id), dict)
            else {}
        )
        raw_status = (
            capability_freshness
            if capability_freshness
            else freshness_by_domain.get(spec.domain)
            if spec.domain
            else slot.get("freshness") or slot.get("status")
        )
        status = normalize_status(raw_status)
        if capability_id == "target.identity":
            status = (
                "unresolved"
                if canonical.get("ok") is not True
                or canonical.get("request_status") != "completed"
                else "ready"
                if canonical.get("target")
                else "missing"
            )
        if capability_id == "data.freshness" and status == "unknown":
            freshness = evidence.get("freshness")
            if isinstance(freshness, dict):
                status = normalize_status(freshness)
        included = capability_id in projected_data
        projected_value = projected_data.get(capability_id)
        capability_quality = (
            quality_by_capability.get(capability_id)
            if isinstance(
                quality_by_capability.get(capability_id),
                dict,
            )
            else {}
        )
        requested_limits = (
            selection.get("requested_limits")
            if isinstance(selection.get("requested_limits"), dict)
            else {}
        )
        effective_limits = (
            selection.get("limits")
            if isinstance(selection.get("limits"), dict)
            else {}
        )
        limit_aliases = {
            "intraday.bars": "intraday.points",
            "daily.ohlcv": "daily.points",
        }
        limit_alias = limit_aliases.get(capability_id)
        requested_limit = requested_limits.get(
            capability_id,
            requested_limits.get(limit_alias) if limit_alias else None,
        )
        effective_limit = effective_limits.get(
            capability_id,
            effective_limits.get(limit_alias, spec.default_limit)
            if limit_alias
            else spec.default_limit,
        )
        returned_count = _projected_returned_count(
            projected_value,
            included=included,
        )
        payload_truncated = bool(
            isinstance(projected_value, dict)
            and projected_value.get("truncated") is True
        )
        realtime = (realtime_assessments or {}).get(capability_id)
        if realtime is None and isinstance(projected_data.get(capability_id), dict):
            realtime = projected_data[capability_id].get("realtime")
        if isinstance(realtime, dict):
            status = normalize_status(realtime.get("state"))
        if status == "unknown" and included:
            status = "available"
        state = (
            str(realtime.get("status_class"))
            if isinstance(realtime, dict)
            else status_class(status)
        )
        fill_operation = spec.fill_operation_for_scope(scope_type)
        refresh_strategy = spec.refresh_strategy_for_scope(scope_type)
        refresh_requires_market_open = (
            spec.refresh_requires_market_open_for_scope(scope_type)
        )
        refresh_possible_now = (
            bool(realtime.get("refresh_possible_now"))
            if isinstance(realtime, dict)
            and "refresh_possible_now" in realtime
            else refresh_strategy in {"reader_fetch", "granular_tool"}
        )
        refresh_metadata: dict[str, Any] = {}
        if refresh_strategy != "derived":
            refresh_metadata = {
                "refresh_strategy": refresh_strategy,
                "fill_operation": fill_operation,
                "refresh_possible_now": refresh_possible_now,
                "refresh_requires_market_open": refresh_requires_market_open,
                "writes_market_cache": bool(
                    spec.writes_cache
                    or fill_operation in FILL_OPERATIONS_WRITING_CACHE
                ),
                "estimated_calls": (
                    1
                    if refresh_strategy in {"reader_fetch", "granular_tool"}
                    else 0
                ),
                "expected_timeout_seconds": (
                    8
                    if refresh_strategy in {"reader_fetch", "granular_tool"}
                    else 0
                ),
            }
        capabilities.append(
            {
                "capability": capability_id,
                "schema_version": spec.schema_version,
                "domain": spec.domain,
                "slot": spec.slot,
                "required": capability_id in required,
                "status": status,
                "status_class": state,
                "decision_usable": (
                    bool(realtime.get("decision_usable"))
                    if isinstance(realtime, dict)
                    else state == "ready"
                    or (state == "neutral" and capability_id not in required)
                ),
                "realtime": realtime,
                "refresh_recommended": (
                    realtime.get("refresh_recommended")
                    if isinstance(realtime, dict)
                    else capability_freshness.get("refresh_recommended")
                    if "refresh_recommended" in capability_freshness
                    else state != "ready"
                ),
                "release_status": capability_freshness.get("release_status"),
                "next_eligible_refresh_at": capability_freshness.get(
                    "next_eligible_refresh_at"
                ),
                **refresh_metadata,
                "payload_included": included,
                "fields": list(
                    (selection.get("fields") or {}).get(capability_id)
                    or spec.default_fields
                ),
                "default_limit": spec.default_limit,
                "maximum_limit": MAX_CAPABILITY_LIMIT,
                "requested_limit": requested_limit,
                "effective_limit": effective_limit,
                "returned_count": returned_count,
                "truncated": payload_truncated,
                "quality_issues": list(
                    capability_quality.get("issues") or []
                ),
                "coverage_status": capability_quality.get(
                    "coverage_status"
                ),
            }
        )
    unsupported_capabilities = [
        dict(item)
        for item in selection.get("unsupported_capabilities") or []
        if isinstance(item, dict)
    ]
    unmet_required_capabilities = [
        dict(item)
        for item in selection.get("unmet_required_capabilities") or []
        if isinstance(item, dict)
    ]
    return {
        "version": "omi.data.manifest.v1",
        "capabilities": capabilities,
        "unsupported_capabilities": unsupported_capabilities,
        "unsupported_count": len(unsupported_capabilities),
        "unmet_required_capabilities": unmet_required_capabilities,
        "unmet_required_count": len(unmet_required_capabilities),
        "ready_count": sum(item["status_class"] == "ready" for item in capabilities),
        "limited_count": sum(item["status_class"] == "limited" for item in capabilities),
        "blocked_count": sum(item["status_class"] == "blocked" for item in capabilities),
    }


def _tool_run_operation_status(run: dict[str, Any]) -> str:
    explicit = str(run.get("operation_status") or "").strip().lower()
    if explicit:
        return explicit
    legacy = str(run.get("status") or "unknown").strip().lower()
    return {
        "success": "succeeded",
        "success_with_fallback": "succeeded",
        "partial_success": "partial",
        "background_running": "pending",
        "queued": "pending",
        "running": "pending",
        "error": "failed",
    }.get(legacy, legacy)


def _fill_resolution_without_operation(
    *,
    capability_id: str,
    item: dict[str, Any],
    refresh_strategy: str,
) -> tuple[str, str]:
    payload_included = item.get("payload_included") is True
    quality_issues = {
        str(issue) for issue in item.get("quality_issues") or []
    }
    if capability_id == "data.freshness":
        return "deferred_action", "dependent_capabilities_unresolved"
    if refresh_strategy == "scheduler_owned":
        return (
            "deferred_action",
            "scheduler_owned_current"
            if payload_included
            else "scheduler_owned",
        )
    if refresh_strategy == "reader_fetch":
        return (
            "already_attempted",
            "reader_fetch_on_primary_request",
        ) if capability_id == "intraday.bars" and payload_included else (
            "deferred_action",
            "reader_fetch_on_primary_request",
        )
    if refresh_strategy == "cache_only":
        return "deferred_action", "cache_only"
    if capability_id == "market.volume_state":
        return "deferred_action", "history_accumulation_required"
    if capability_id == "market.breadth":
        return "deferred_action", "coverage_reconciliation_required"
    if capability_id == "market.sectors":
        return (
            "deferred_action",
            "derived_rebuild_completed_with_quality_limits",
        ) if payload_included else (
            "deferred_action",
            "derived_rebuild_unavailable",
        )
    if capability_id == "market.sample_ranking":
        if quality_issues & {
            "volume_unit_missing",
            "semantic_payload_empty",
        } or not payload_included:
            return "unfillable_action", "contract_schema_fix_required"
        return "deferred_action", "bounded_sample_only"
    if refresh_strategy == "derived":
        return (
            "deferred_action",
            "derived_payload_quality_limited",
        ) if payload_included else (
            "unfillable_action",
            "derived_payload_bug",
        )
    return "unfillable_action", "no_executable_fill_operation"


def build_fill_plan(
    *,
    canonical: dict[str, Any],
    selection: dict[str, Any],
    manifest: dict[str, Any],
    scope_type: str,
    tool_runs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    target = canonical.get("target") if isinstance(canonical.get("target"), dict) else {}
    actions: list[dict[str, Any]] = []
    deferred_actions: list[dict[str, Any]] = []
    unfillable_actions: list[dict[str, Any]] = []
    already_attempted_actions: list[dict[str, Any]] = []
    if canonical.get("ok") is not True or canonical.get("request_status") != "completed":
        return {
            "version": "omi.fill.plan.v1",
            "plan_id": fill_plan_id(target=target, action_ids=[]),
            "actions": [],
            "deferred_actions": [],
            "unfillable_actions": [],
            "already_attempted_actions": [],
            "resolutions": [],
            "action_count": 0,
            "summary": {
                "executable_count": 0,
                "deferred_count": 0,
                "unfillable_count": 0,
                "already_attempted_count": 0,
                "unresolved_count": 0,
            },
            "auto_executed": False,
        }
    selected = {
        str(capability)
        for capability in (
            list(selection.get("required") or [])
            + list(selection.get("optional") or [])
        )
        if str(capability).strip()
    }
    attempted_capabilities = {
        capability
        for run in tool_runs or []
        if isinstance(run, dict)
        for capability in _capabilities_for_tool_run(
            run=run,
            selected=selected,
            scope_type=scope_type,
        )
    }
    for item in manifest.get("capabilities") or []:
        if not isinstance(item, dict):
            continue
        capability_id = str(item.get("capability") or "")
        if capability_id in {"target.identity", "data.freshness"}:
            continue
        if (
            item.get("status_class") == "ready"
            and item.get("payload_included") is True
        ):
            continue
        if (
            capability_id in attempted_capabilities
            and item.get("payload_included") is True
        ):
            already_attempted_actions.append(
                {
                    "capability": capability_id,
                    "status": item.get("status"),
                    "status_class": item.get("status_class"),
                    "payload_included": item.get("payload_included") is True,
                    "resolution_type": "already_attempted",
                    "reason": "already_attempted_primary_reader",
                    "quality_issues": list(
                        item.get("quality_issues") or []
                    ),
                }
            )
            continue
        refresh_is_deferred = bool(
            item.get("refresh_recommended") is False
            and (
                item.get("release_status") == "pending"
                or item.get("next_eligible_refresh_at")
            )
        )
        if refresh_is_deferred:
            deferred_actions.append(
                {
                    "capability": capability_id,
                    "status": item.get("status"),
                    "resolution_type": "deferred_action",
                    "reason": (
                        "release_pending"
                        if item.get("release_status") == "pending"
                        else "refresh_cooldown"
                        if item.get("next_eligible_refresh_at")
                        else "refresh_not_recommended"
                    ),
                    "release_status": item.get("release_status"),
                    "next_eligible_refresh_at": item.get(
                        "next_eligible_refresh_at"
                    ),
                }
            )
            continue
        spec = CAPABILITIES.get(capability_id)
        if spec is None:
            unfillable_actions.append(
                {
                    "capability": capability_id,
                    "status": item.get("status"),
                    "resolution_type": "unfillable_action",
                    "reason": "unsupported_target_scope",
                }
            )
            continue
        refresh_strategy = str(
            item.get("refresh_strategy")
            or spec.refresh_strategy_for_scope(scope_type)
        )
        operation = spec.fill_operation_for_scope(scope_type)
        if not operation:
            if capability_id in attempted_capabilities:
                resolution_type = "already_attempted"
                reason = "already_attempted_primary_reader"
            else:
                resolution_type, reason = _fill_resolution_without_operation(
                    capability_id=capability_id,
                    item=item,
                    refresh_strategy=refresh_strategy,
                )
            resolution = {
                "capability": capability_id,
                "status": item.get("status"),
                "status_class": item.get("status_class"),
                "payload_included": item.get("payload_included") is True,
                "resolution_type": resolution_type,
                "reason": reason,
                "refresh_strategy": refresh_strategy,
                "refresh_possible_now": bool(
                    item.get("refresh_possible_now")
                ),
                "refresh_requires_market_open": bool(
                    item.get("refresh_requires_market_open")
                ),
                "writes_market_cache": bool(
                    item.get("writes_market_cache")
                ),
                "estimated_calls": item.get("estimated_calls", 0),
                "expected_timeout_seconds": item.get(
                    "expected_timeout_seconds",
                    0,
                ),
                "quality_issues": list(item.get("quality_issues") or []),
            }
            if resolution_type == "unfillable_action":
                unfillable_actions.append(resolution)
            elif resolution_type == "already_attempted":
                already_attempted_actions.append(resolution)
            else:
                deferred_actions.append(resolution)
            continue
        if (
            item.get("refresh_recommended") is False
            and item.get("payload_included") is True
        ):
            deferred_actions.append(
                {
                    "capability": capability_id,
                    "status": item.get("status"),
                    "status_class": item.get("status_class"),
                    "payload_included": True,
                    "resolution_type": "deferred_action",
                    "reason": "refresh_not_recommended",
                    "operation": operation,
                    "refresh_strategy": refresh_strategy,
                    "quality_issues": list(
                        item.get("quality_issues") or []
                    ),
                }
            )
            continue
        produced_capabilities = list(
            FILL_OPERATION_PRODUCED_CAPABILITIES.get(operation, ())
        )
        if capability_id not in produced_capabilities:
            deferred_actions.append(
                {
                    "capability": capability_id,
                    "status": item.get("status"),
                    "resolution_type": "deferred_action",
                    "reason": "operation_does_not_produce_capability",
                    "operation": operation,
                    "produced_capabilities": produced_capabilities,
                }
            )
            continue
        action_id = fill_action_id(
            capability_id=capability_id,
            target=target,
            selection_version=str(selection.get("version") or ""),
        )
        actions.append(
            {
                "action_id": action_id,
                "capability": capability_id,
                "target": target,
                "operation": operation,
                "refresh_strategy": refresh_strategy,
                "produced_capabilities": produced_capabilities,
                "status": "planned",
                "resolution_type": "executable_action",
                "executable": operation in EXECUTABLE_FILL_OPERATIONS,
                "required": bool(item.get("required")),
                "fields": list(item.get("fields") or []),
                "limit": item.get("limit"),
                "reason": (
                    "payload_not_included"
                    if item.get("payload_included") is not True
                    else f"capability_status={item.get('status') or 'unknown'}"
                ),
                "primary_reader_attempted": (
                    capability_id in attempted_capabilities
                ),
                "auto_retry_eligible": False,
                "estimated_calls": 1,
                "estimated_timeout_seconds": 8,
                "refresh_possible_now": bool(
                    item.get("refresh_possible_now", True)
                ),
                "refresh_requires_market_open": bool(
                    item.get("refresh_requires_market_open")
                ),
                "writes_cache": (
                    spec.writes_cache
                    or operation in FILL_OPERATIONS_WRITING_CACHE
                ),
                "requires_external_fetch": True,
            }
        )
    plan_id = fill_plan_id(
        target=target,
        action_ids=[str(action["action_id"]) for action in actions],
    )
    plan_action_ids = [str(action["action_id"]) for action in actions]
    for action in actions:
        action["invoke"] = {
            "tool": "omi.ask",
            "arguments": {
                "contract_version": "omi.decision.v4",
                "question": (
                    "Fill selected capability "
                    f"{action['capability']} for target "
                    f"{target.get('id') or target.get('type') or 'unknown'}."
                ),
                "target": _fill_target_identity(target),
                "selection": {
                    "include": [action["capability"]],
                    "fields": {
                        action["capability"]: list(action.get("fields") or [])
                    }
                    if action.get("fields")
                    else {},
                    "limits": {
                        action["capability"]: action.get("limit")
                    }
                    if action.get("limit")
                    else {},
                    "max_response_bytes": selection.get("max_response_bytes"),
                },
                "output": selection.get("output"),
                "realtime_policy": "prefer_live",
                "allow_external_fetch": True,
                "continuation": {
                    "plan_id": plan_id,
                    "plan_action_ids": plan_action_ids,
                    "selected_action_ids": [action["action_id"]],
                },
            },
        }
    resolutions = [
        *actions,
        *deferred_actions,
        *unfillable_actions,
        *already_attempted_actions,
    ]
    return {
        "version": "omi.fill.plan.v1",
        "plan_id": plan_id,
        "actions": actions,
        "deferred_actions": deferred_actions,
        "unfillable_actions": unfillable_actions,
        "already_attempted_actions": already_attempted_actions,
        "resolutions": resolutions,
        "action_count": len(actions),
        "summary": {
            "executable_count": len(actions),
            "deferred_count": len(deferred_actions),
            "unfillable_count": len(unfillable_actions),
            "already_attempted_count": len(already_attempted_actions),
            "unresolved_count": len(resolutions),
        },
        "auto_executed": False,
    }


def _capabilities_for_tool_run(
    *,
    run: dict[str, Any],
    selected: set[str],
    scope_type: str,
) -> list[str]:
    tool = str(run.get("tool") or "").strip()
    arguments = run.get("arguments") if isinstance(run.get("arguments"), dict) else {}
    requested = [
        str(capability)
        for capability in arguments.get("requested_capabilities") or []
        if str(capability) in selected
    ]
    if requested or not tool:
        return list(dict.fromkeys(requested))
    return [
        capability
        for capability in selected
        if (
            CAPABILITIES.get(capability) is not None
            and CAPABILITIES[capability].fill_operation_for_scope(scope_type)
            == tool
        )
    ]


def build_refresh_reconciliation(
    *,
    selection: dict[str, Any],
    manifest: dict[str, Any],
    fill_plan: dict[str, Any],
    tool_runs: list[dict[str, Any]],
    scope_type: str,
) -> dict[str, Any]:
    selected = list(
        dict.fromkeys(
            [
                str(capability)
                for capability in (
                    list(selection.get("required") or [])
                    + list(selection.get("optional") or [])
                )
                if str(capability).strip()
            ]
        )
    )
    selected_set = set(selected)
    manifest_by_capability = {
        str(item.get("capability")): item
        for item in manifest.get("capabilities") or []
        if isinstance(item, dict) and item.get("capability")
    }
    remaining_actions = {
        str(action.get("capability")): action
        for action in fill_plan.get("actions") or []
        if isinstance(action, dict) and action.get("capability")
    }
    deferred_by_capability = {
        str(action.get("capability")): action
        for action in fill_plan.get("deferred_actions") or []
        if isinstance(action, dict) and action.get("capability")
    }
    unfillable_by_capability = {
        str(action.get("capability")): action
        for action in fill_plan.get("unfillable_actions") or []
        if isinstance(action, dict) and action.get("capability")
    }
    already_attempted_by_capability = {
        str(action.get("capability")): action
        for action in fill_plan.get("already_attempted_actions") or []
        if isinstance(action, dict) and action.get("capability")
    }
    attempts: list[dict[str, Any]] = []
    attempt_indexes_by_capability: dict[str, list[int]] = {
        capability: [] for capability in selected
    }

    for run_index, run in enumerate(tool_runs):
        if not isinstance(run, dict):
            continue
        tool = str(run.get("tool") or "").strip()
        requested = _capabilities_for_tool_run(
            run=run,
            selected=selected_set,
            scope_type=scope_type,
        )

        status = str(run.get("status") or "unknown").strip().lower()
        transport_status = str(
            run.get("transport_status") or status
        ).strip().lower()
        operation_status = _tool_run_operation_status(run)
        result_summary = (
            run.get("result_summary")
            if isinstance(run.get("result_summary"), dict)
            else {}
        )
        refresh_outcome = str(
            result_summary.get("refresh_outcome")
            or (
                "data_returned"
                if operation_status == "succeeded"
                and (
                    isinstance(result_summary.get("points"), list)
                    and bool(result_summary.get("points"))
                    or any(
                        isinstance(result_summary.get(key), (int, float))
                        and result_summary.get(key) > 0
                        for key in (
                            "point_count",
                            "returned_point_count",
                            "fetched_count",
                            "refreshed_count",
                            "inserted_count",
                            "updated_count",
                            "changed_row_count",
                        )
                    )
                )
                else "completed"
                if operation_status == "succeeded"
                else operation_status
            )
        ).strip().lower()
        attempt = {
            "run_index": run_index,
            "tool": tool,
            "status": status,
            "transport_status": transport_status,
            "operation_status": operation_status,
            "evidence_status": run.get("evidence_status"),
            "result_status": run.get("result_status"),
            "requested_capabilities": requested,
            "refresh_outcome": refresh_outcome,
            "external_fetch": bool(run.get("external_fetch")),
            "writes_cache": bool(
                run.get("writes_cache") or run.get("writes_market_cache")
            ),
            "duration_ms": run.get("duration_ms"),
            "error": run.get("error"),
        }
        if result_summary.get("refreshed_count") is not None:
            attempt["refreshed_count"] = result_summary.get("refreshed_count")
            attempt["refreshed_count_semantics"] = result_summary.get(
                "refreshed_count_semantics"
            )
        attempts.append(attempt)
        attempt_index = len(attempts) - 1
        for capability in requested:
            attempt_indexes_by_capability[capability].append(attempt_index)

    capability_outcomes: dict[str, dict[str, Any]] = {}
    for capability in selected:
        manifest_item = manifest_by_capability.get(capability) or {}
        indexes = attempt_indexes_by_capability.get(capability) or []
        related_attempts = [attempts[index] for index in indexes]
        statuses = [
            str(attempt.get("operation_status") or "")
            for attempt in related_attempts
        ]
        usable_evidence_available = bool(
            manifest_item.get("payload_included") is True
            and manifest_item.get("status_class") in {"ready", "limited"}
        )
        evidence_payload_available = manifest_item.get("payload_included") is True
        tool_succeeded = any(
            status
            in {
                "succeeded",
                "partial",
            }
            for status in statuses
        )
        if usable_evidence_available:
            reconciliation = "satisfied"
        elif evidence_payload_available and tool_succeeded:
            reconciliation = "evidence_available_with_quality_limits"
        elif tool_succeeded:
            reconciliation = "successful_without_usable_evidence"
        elif any(
            status in {"pending", "timeout"}
            for status in statuses
        ):
            reconciliation = "pending_or_incomplete"
        elif related_attempts:
            reconciliation = "attempt_failed_or_blocked"
        else:
            reconciliation = "not_attempted"
        remaining_action = remaining_actions.get(capability)
        resolution_detail = (
            remaining_action
            or already_attempted_by_capability.get(capability)
            or deferred_by_capability.get(capability)
            or unfillable_by_capability.get(capability)
        )
        resolution_type = (
            "satisfied"
            if manifest_item.get("status_class") == "ready"
            and evidence_payload_available
            else str(
                (resolution_detail or {}).get("resolution_type")
                or "unresolved"
            )
        )
        unresolved_reason = (
            None
            if resolution_type == "satisfied"
            else (resolution_detail or {}).get("reason")
            or "no_resolution_recorded"
        )
        capability_outcomes[capability] = {
            "attempted": bool(related_attempts),
            "primary_reader_attempted": bool(
                related_attempts
                or capability in already_attempted_by_capability
            ),
            "attempt_count": len(related_attempts),
            "attempt_indexes": indexes,
            "tool_succeeded": tool_succeeded,
            "tool_statuses": statuses,
            "refresh_outcomes": list(
                dict.fromkeys(
                    str(attempt.get("refresh_outcome") or "unknown")
                    for attempt in related_attempts
                )
            ),
            "final_status": manifest_item.get("status") or "unknown",
            "final_status_class": manifest_item.get("status_class") or "blocked",
            "payload_included": evidence_payload_available,
            "final_payload_present": evidence_payload_available,
            "final_quality_issue": list(
                manifest_item.get("quality_issues") or []
            ),
            "usable_evidence_available": usable_evidence_available,
            "reconciliation": reconciliation,
            "resolution_type": resolution_type,
            "unresolved_reason": unresolved_reason,
            "remaining_fill_action": remaining_action.get("action_id")
            if isinstance(remaining_action, dict)
            else None,
            "remaining_fill_action_detail": (
                {
                    key: remaining_action.get(key)
                    for key in (
                        "action_id",
                        "capability",
                        "operation",
                        "refresh_strategy",
                        "status",
                        "reason",
                        "executable",
                    )
                }
                if isinstance(remaining_action, dict)
                else None
            ),
        }

    return {
        "version": "omi.refresh.reconciliation.v1",
        "attempted": bool(attempts),
        "attempt_count": len(attempts),
        "attempts": attempts,
        "capabilities": capability_outcomes,
        "remaining_action_count": len(remaining_actions),
        "remaining_action_ids": [
            str(action.get("action_id"))
            for action in fill_plan.get("actions") or []
            if isinstance(action, dict) and action.get("action_id")
        ],
    }


def _fill_target_identity(target: dict[str, Any]) -> dict[str, Any]:
    return {
        key: target[key]
        for key in ("type", "id", "market")
        if target.get(key) not in (None, "")
    }


def fill_action_id(
    *,
    capability_id: str,
    target: dict[str, Any],
    selection_version: str = public_contract.CAPABILITY_SELECTION_VERSION,
) -> str:
    action_seed = json.dumps(
        {
            "capability": capability_id,
            "target": _fill_target_identity(target),
            "selection_version": selection_version,
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return "fill_" + hashlib.sha256(action_seed.encode("utf-8")).hexdigest()[:16]


def fill_plan_id(*, target: dict[str, Any], action_ids: list[str]) -> str:
    plan_seed = json.dumps(
        {
            "target": _fill_target_identity(target),
            "actions": action_ids,
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return "plan_" + hashlib.sha256(plan_seed.encode("utf-8")).hexdigest()[:16]


def selected_fill_capabilities(
    *,
    continuation: dict[str, Any],
    selection: dict[str, Any],
    target: dict[str, Any],
    scope_type: str,
) -> tuple[str, ...]:
    selected_action_ids = {
        str(value).strip()
        for value in continuation.get("selected_action_ids") or []
        if str(value).strip()
    }
    if not selected_action_ids:
        return ()
    plan_id = str(continuation.get("plan_id") or "").strip()
    plan_action_ids = [
        str(value).strip()
        for value in continuation.get("plan_action_ids") or []
        if str(value).strip()
    ]
    if not plan_id or not plan_action_ids:
        raise ValueError(
            "Continuation fill execution requires plan_id and plan_action_ids."
        )
    if selected_action_ids - set(plan_action_ids):
        raise ValueError(
            "Continuation selected_action_ids must be a subset of plan_action_ids."
        )
    expected_plan_id = fill_plan_id(
        target=target,
        action_ids=plan_action_ids,
    )
    if plan_id != expected_plan_id:
        raise ValueError("Continuation plan_id does not match target and plan_action_ids.")
    selected: list[str] = []
    for capability_id in list(selection.get("required") or []) + list(
        selection.get("optional") or []
    ):
        spec = CAPABILITIES.get(str(capability_id))
        if spec is None:
            continue
        operation = spec.fill_operation_for_scope(scope_type)
        if operation not in EXECUTABLE_FILL_OPERATIONS:
            continue
        if str(capability_id) not in FILL_OPERATION_PRODUCED_CAPABILITIES.get(
            operation,
            (),
        ):
            continue
        expected_action_id = fill_action_id(
            capability_id=str(capability_id),
            target=target,
            selection_version=str(selection.get("version") or ""),
        )
        if expected_action_id in selected_action_ids:
            selected.append(str(capability_id))
    unknown_action_ids = selected_action_ids - {
        fill_action_id(
            capability_id=capability_id,
            target=target,
            selection_version=str(selection.get("version") or ""),
        )
        for capability_id in selected
    }
    if unknown_action_ids:
        raise ValueError(
            "Continuation contains unknown or non-executable fill action id(s): "
            + ", ".join(sorted(unknown_action_ids))
        )
    return tuple(selected)
