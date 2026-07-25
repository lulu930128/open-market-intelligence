from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Any


OUTPUT_MODES = {"evidence_only", "decision", "decision_with_evidence"}
REALTIME_POLICIES = {"cache_only", "prefer_live", "require_live"}
DIAGNOSTIC_SCOPES = {
    "capability_status",
    "data_freshness",
    "source_health",
}
MIN_RESPONSE_BYTES = 4_096
MAX_RESPONSE_BYTES = 1_048_576
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
    "latest_completed_session",
    "latest_session_close",
    "live",
    "ok",
    "ready",
}
LIMITED_STATUSES = {"cached", "delayed", "partial", "pending", "waiting"}
NEUTRAL_STATUSES = {"not_applicable", "not_requested"}
EXECUTABLE_FILL_OPERATIONS = {
    "tw.refresh_quote",
    "tw.refresh_intraday",
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
    fill_operations: tuple[tuple[str, str], ...] = ()
    writes_cache: bool = False

    def as_public_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["fill_operations"] = {
            scope: operation for scope, operation in self.fill_operations
        }
        return payload

    def fill_operation_for_scope(self, scope_type: str) -> str | None:
        return dict(self.fill_operations).get(scope_type)


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
            "trade_value",
            "trade_value_unit",
            "total_volume_lots",
            "bid",
            "ask",
            "best_bid_price",
            "best_bid_size_lots",
            "best_ask_price",
            "best_ask_size_lots",
            "spread",
            "spread_pct",
            "trade_date",
            "quote_time",
            "event_time",
            "fetched_at",
            "refresh_outcome",
            "received_at",
            "source",
            "provider",
            "market_status",
            "session_phase",
            "quote_semantics",
            "delivery_status",
            "is_live",
            "is_realtime",
            "is_current_session_quote",
            "is_latest_session_quote",
            "age_seconds",
            "quote_age_seconds",
            "latency_ms",
            "depth_available",
            "freshness",
            "timezone",
        ),
        default_fields=(
            "status",
            "price",
            "latest_price",
            "last_price",
            "change",
            "change_pct",
            "currency",
            "price_unit",
            "volume",
            "volume_unit",
            "trade_value",
            "trade_value_unit",
            "total_volume_lots",
            "bid",
            "ask",
            "best_bid_price",
            "best_ask_price",
            "spread",
            "trade_date",
            "quote_time",
            "event_time",
            "fetched_at",
            "received_at",
            "source",
            "provider",
            "market_status",
            "session_phase",
            "quote_semantics",
            "delivery_status",
            "is_live",
            "is_realtime",
            "is_current_session_quote",
            "is_latest_session_quote",
            "quote_age_seconds",
            "latency_ms",
            "freshness",
            "timezone",
        ),
        default_limit=1,
        fill_operations=(
            ("stock", "tw.refresh_quote"),
            ("us_stock", "us.read_intraday_trend"),
            ("jp_stock", "jp.read_intraday_trend"),
            ("jp_index", "jp.read_intraday_trend"),
            ("kr_stock", "kr.read_stock_intraday_trend"),
            ("kr_index", "kr.read_index_intraday_trend"),
            ("crypto_asset", "crypto.refresh_ticker"),
        ),
    ),
    CapabilitySpec(
        capability_id="intraday.bars",
        domain="intraday",
        slot="intraday",
        scopes=(*ALL_INSTRUMENT_SCOPES, "market", "crypto_market"),
        paths=(
            "compact.intraday_bars",
            "compact.index_intraday",
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
            "source_interval",
            "effective_interval",
            "sampling_mode",
            "original_point_count",
            "session",
            "session_scope",
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
            "volume_unit",
            "trade_value_unit",
            "quote_volume",
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
        ),
        default_fields=(
            "as_of",
            "enabled",
            "kind",
            "payload_level",
            "interval",
            "source_interval",
            "effective_interval",
            "sampling_mode",
            "original_point_count",
            "session",
            "session_scope",
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
            "volume_unit",
            "trade_value_unit",
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
        ),
        default_limit=20,
        fill_operations=(
            ("stock", "tw.refresh_intraday"),
            ("us_stock", "us.read_intraday_trend"),
            ("jp_stock", "jp.read_intraday_trend"),
            ("jp_index", "jp.read_intraday_trend"),
            ("kr_stock", "kr.read_stock_intraday_trend"),
            ("kr_index", "kr.read_index_intraday_trend"),
            ("crypto_asset", "crypto.refresh_ohlcv"),
        ),
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
            "volume_unit",
            "trade_value_unit",
            "quote_volume",
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
            "volume_unit",
            "trade_value_unit",
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
            "selected_score",
            "selected_title",
            "selected_summary",
            "selected_confidence",
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
            "levels",
            "reports",
            "freshness",
            "source",
            "provider",
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
        ),
        default_fields=(
            "trade_date",
            "foreign_investor_net",
            "investment_trust_net",
            "dealer_net",
            "total_institutional_net",
            "source",
            "freshness",
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
        ),
        default_fields=(
            "latest_revenue",
            "revenue_history",
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
        ),
        default_fields=(
            "latest_financial",
            "financial_history",
            "sec_fundamentals",
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
        fields=("as_of", "summary", "signals", "source", "freshness", "warnings"),
        default_fields=("as_of", "summary", "signals", "source", "freshness", "warnings"),
        default_limit=10,
    ),
    CapabilitySpec(
        capability_id="company.profile",
        domain=None,
        slot="profile",
        scopes=("us_stock", "jp_stock", "kr_stock"),
        paths=("data.profile", "data.stock"),
        fields=(
            "symbol",
            "stock_id",
            "security_name",
            "company_name",
            "exchange",
            "market",
            "asset_type",
            "instrument_type",
            "sector",
            "industry",
            "cik",
            "sec_company_name",
            "provider",
            "fetched_at",
            "updated_at",
        ),
        default_fields=(
            "symbol",
            "stock_id",
            "security_name",
            "company_name",
            "exchange",
            "market",
            "asset_type",
            "instrument_type",
            "sector",
            "industry",
            "provider",
            "fetched_at",
        ),
        default_limit=1,
    ),
    CapabilitySpec(
        capability_id="corporate.actions",
        domain=None,
        slot="news_events",
        scopes=("us_stock",),
        paths=("data.corporate_actions",),
        fields=(
            "provider",
            "symbol",
            "action_type",
            "event_date",
            "amount",
            "split_ratio",
            "currency",
            "fetched_at",
        ),
        default_fields=(
            "provider",
            "symbol",
            "action_type",
            "event_date",
            "amount",
            "split_ratio",
            "currency",
        ),
        default_limit=20,
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
            "universe_definition",
            "authority",
            "inclusion_rule",
            "instrument_type_policy",
            "missing_quote_policy",
            "official_full_market",
            "included_markets",
            "missing_markets",
            "markets",
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
            "included_markets",
            "missing_markets",
            "markets",
            "source",
            "freshness",
        ),
        default_limit=10,
    ),
    CapabilitySpec(
        capability_id="market.sample_ranking",
        domain="sample_ranking",
        slot="sample_distribution",
        scopes=("market",),
        paths=("compact",),
        fields=(
            "as_of",
            "latest_trade_date",
            "sample_breadth",
            "sample_coverage",
            "distribution",
            "top_gainers",
            "top_losers",
            "value_leaders",
            "top_industries",
            "weak_industries",
            "industry_strength_label",
        ),
        default_fields=(
            "as_of",
            "latest_trade_date",
            "sample_coverage",
            "distribution",
            "top_gainers",
            "top_losers",
            "value_leaders",
            "top_industries",
            "weak_industries",
            "industry_strength_label",
        ),
        default_limit=20,
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
            "current_value_source",
            "previous_minute_cumulative_trade_value",
            "one_minute_trade_value_change",
            "field_status",
            "same_time_baseline_5d",
            "same_time_baseline_20d",
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
            "current_value_source",
            "previous_minute_cumulative_trade_value",
            "one_minute_trade_value_change",
            "field_status",
            "same_time_baseline_5d",
            "same_time_baseline_20d",
            "markets",
            "warnings",
            "limitations",
        ),
        default_limit=20,
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
            "is_current",
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
            "is_current",
            "stale_stock_count",
            "returned_count",
            "results",
        ),
        default_limit=20,
    ),
    CapabilitySpec(
        capability_id="watchlist.radar",
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
        domain="source_health",
        slot="data_quality",
        scopes=("source_health",),
        paths=("data",),
        fields=(
            "filters",
            "summary",
            "entries",
            "freshness",
            "slots",
            "compact",
            "returned_count",
            "truncated",
            "is_partial",
        ),
        default_fields=(
            "filters",
            "summary",
            "entries",
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
    "cross_market": ("cross_market.overnight", "market.cross_market"),
    "derivatives": (
        "crypto.derivatives",
        "derivatives.positioning",
        "derivatives.structure",
    ),
    "breadth": ("market.breadth",),
    "volume": ("market.volume_state",),
    "sample_ranking": ("market.sample_ranking",),
    "source_health": ("source.health",),
    "freshness": ("data.freshness",),
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


def _compatible(spec: CapabilitySpec, scope_type: str) -> bool:
    return "*" in spec.scopes or scope_type in spec.scopes


def _default_capabilities(scope_type: str, question_intent: str) -> tuple[str, ...]:
    if scope_type == "capability_status":
        return ("target.identity", "diagnostics.capabilities")
    if scope_type == "source_health":
        return ("target.identity", "diagnostics.source_health")
    if scope_type == "data_freshness":
        return ("target.identity", "diagnostics.data_freshness")
    if question_intent == "quote":
        return ("target.identity", "quote.snapshot", "data.freshness")
    if question_intent == "broker_branch":
        return (
            "target.identity",
            "quote.snapshot",
            "broker_branch.summary",
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


def _capabilities_from_domains(domains: tuple[str, ...]) -> tuple[str, ...]:
    output: list[str] = []
    for domain in domains:
        for capability_id in DOMAIN_CAPABILITIES.get(domain, ()):
            if capability_id not in output:
                output.append(capability_id)
    return tuple(output)


def _normalized_fields(
    raw_fields: Any,
    *,
    selected: tuple[str, ...],
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


def _normalized_limits(raw_limits: Any) -> dict[str, int]:
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
        if isinstance(raw_value, bool) or not isinstance(raw_value, int):
            raise ValueError(f"selection.limits.{key} must be an integer.")
        output[key] = max(1, min(raw_value, 500))
    return output


def normalize_selection(
    *,
    selection: dict[str, Any] | None,
    output: str | None,
    realtime_policy: str | None,
    payload_level: str,
    scope_type: str,
    question_intent: str,
    requested_domains: tuple[str, ...] = (),
    excluded_domains: tuple[str, ...] = (),
    requested_capabilities: tuple[str, ...] = (),
    excluded_capabilities: tuple[str, ...] = (),
) -> dict[str, Any]:
    raw = selection if isinstance(selection, dict) else {}
    explicit_include = _string_list(
        raw.get("required") or raw.get("include"),
        name="selection.include",
    )
    explicit_optional = _string_list(
        raw.get("optional"),
        name="selection.optional",
    )
    explicit_exclude = _string_list(
        raw.get("exclude"),
        name="selection.exclude",
    )
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
                )
            )
            if _compatible(CAPABILITIES[capability_id], scope_type)
        )
    )
    legacy_exclude = tuple(
        capability_id
        for capability_id in _capabilities_from_domains(
            tuple(
                domain
                for domain in excluded_domains
                if domain not in requested_specific_domains
            )
        )
        if _compatible(CAPABILITIES[capability_id], scope_type)
    )
    required = list(explicit_include)
    if not required:
        required.extend(_default_capabilities(scope_type, question_intent))
        required.extend(legacy_include)
        required.extend(
            capability_id
            for capability_id in requested_capabilities
            if capability_id in CAPABILITIES
            and _compatible(CAPABILITIES[capability_id], scope_type)
        )
    optional = list(explicit_optional)
    excluded = list(
        dict.fromkeys(
            (
                *explicit_exclude,
                *legacy_exclude,
                *excluded_capabilities,
            )
        )
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

    incompatible = [
        capability_id
        for capability_id in (*required, *optional)
        if not _compatible(CAPABILITIES[capability_id], scope_type)
    ]
    if incompatible:
        raise ValueError(
            f"Capability not supported for target scope {scope_type}: "
            + ", ".join(dict.fromkeys(incompatible))
        )

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
    fields = _normalized_fields(raw.get("fields"), selected=selected)
    limits = _normalized_limits(raw.get("limits"))

    output_mode = str(output or raw.get("output") or "").strip().lower()
    if scope_type in DIAGNOSTIC_SCOPES:
        output_mode = "evidence_only"
    elif not output_mode:
        output_mode = "evidence_only" if question_intent in {"quote", "data_freshness"} else "decision_with_evidence"
    if output_mode not in OUTPUT_MODES:
        raise ValueError(f"output must be one of: {', '.join(sorted(OUTPUT_MODES))}")

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

    return {
        "version": "omi.capability.selection.v1",
        "output": output_mode,
        "realtime_policy": realtime,
        "required": required,
        "optional": optional,
        "excluded": excluded,
        "fields": fields,
        "limits": limits,
        "max_response_bytes": max_response_bytes,
    }


def capability_catalog(*, scope_type: str | None = None) -> list[dict[str, Any]]:
    return [
        spec.as_public_dict()
        for spec in CAPABILITY_SPECS
        if scope_type is None or _compatible(spec, scope_type)
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


def _canonical_intraday_value(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    series = value.get("series")
    if not isinstance(series, dict):
        return value

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
        "is_current_session",
        "source_interval",
        "effective_interval",
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
        "volume_unit",
        "quote_volume",
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
    ):
        if key not in output and key in selected:
            output[key] = selected[key]
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
        output.setdefault(
            "event_time",
            latest_point.get("event_time")
            or latest_point.get("bar_time")
            or latest_point.get("time"),
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
        value.setdefault(
            "event_time",
            rows[-1].get("event_time")
            or rows[-1].get("bar_time")
            or rows[-1].get("time")
            if isinstance(rows[-1], dict)
            else None,
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
    source = {
        "target": response.get("target") or {},
        "result": result,
        "data": data,
        "compact": compact,
        "freshness": response.get("freshness") or {},
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


def build_manifest(
    *,
    canonical: dict[str, Any],
    selection: dict[str, Any],
    projected_data: dict[str, Any],
    realtime_assessments: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    evidence = canonical.get("evidence") if isinstance(canonical.get("evidence"), dict) else {}
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
        capabilities.append(
            {
                "capability": capability_id,
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
                "payload_included": included,
                "fields": list(
                    (selection.get("fields") or {}).get(capability_id)
                    or spec.default_fields
                ),
                "limit": (selection.get("limits") or {}).get(
                    capability_id,
                    spec.default_limit,
                ),
            }
        )
    return {
        "version": "omi.data.manifest.v1",
        "capabilities": capabilities,
        "ready_count": sum(item["status_class"] == "ready" for item in capabilities),
        "limited_count": sum(item["status_class"] == "limited" for item in capabilities),
        "blocked_count": sum(item["status_class"] == "blocked" for item in capabilities),
    }


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
    if canonical.get("ok") is not True or canonical.get("request_status") != "completed":
        return {
            "version": "omi.fill.plan.v1",
            "plan_id": fill_plan_id(target=target, action_ids=[]),
            "actions": [],
            "deferred_actions": [],
            "action_count": 0,
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
    successfully_attempted = {
        capability
        for run in tool_runs or []
        if isinstance(run, dict)
        and str(run.get("status") or "").strip().lower() == "success"
        for capability in _capabilities_for_tool_run(
            run=run,
            selected=selected,
            scope_type=scope_type,
        )
    }
    for item in manifest.get("capabilities") or []:
        if not isinstance(item, dict):
            continue
        if (
            item.get("status_class") == "ready"
            and item.get("payload_included") is True
        ):
            continue
        capability_id = str(item.get("capability") or "")
        if (
            item.get("payload_included") is True
            and capability_id in successfully_attempted
        ):
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
        if (
            item.get("refresh_recommended") is False
            and item.get("payload_included") is True
        ):
            continue
        spec = CAPABILITIES.get(capability_id)
        if spec is None:
            continue
        operation = spec.fill_operation_for_scope(scope_type)
        if not operation:
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
                "status": "planned",
                "executable": operation in EXECUTABLE_FILL_OPERATIONS,
                "required": bool(item.get("required")),
                "fields": list(item.get("fields") or []),
                "limit": item.get("limit"),
                "reason": (
                    "payload_not_included"
                    if item.get("payload_included") is not True
                    else f"capability_status={item.get('status') or 'unknown'}"
                ),
                "estimated_calls": 1,
                "estimated_timeout_seconds": 8,
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
    return {
        "version": "omi.fill.plan.v1",
        "plan_id": plan_id,
        "actions": actions,
        "deferred_actions": deferred_actions,
        "action_count": len(actions),
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
        result_summary = (
            run.get("result_summary")
            if isinstance(run.get("result_summary"), dict)
            else {}
        )
        refresh_outcome = str(
            result_summary.get("refresh_outcome")
            or (
                "data_returned"
                if status == "success"
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
                if status == "success"
                else status
            )
        ).strip().lower()
        attempt = {
            "run_index": run_index,
            "tool": tool,
            "status": status,
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
        statuses = [str(attempt.get("status") or "") for attempt in related_attempts]
        usable_evidence_available = bool(
            manifest_item.get("payload_included") is True
            and manifest_item.get("status_class") in {"ready", "limited"}
        )
        evidence_payload_available = manifest_item.get("payload_included") is True
        tool_succeeded = "success" in statuses
        if usable_evidence_available:
            reconciliation = "satisfied"
        elif evidence_payload_available and tool_succeeded:
            reconciliation = "evidence_available_with_quality_limits"
        elif tool_succeeded:
            reconciliation = "successful_without_usable_evidence"
        elif any(
            status in {"background_running", "queued", "running", "timeout"}
            for status in statuses
        ):
            reconciliation = "pending_or_incomplete"
        elif related_attempts:
            reconciliation = "attempt_failed_or_blocked"
        else:
            reconciliation = "not_attempted"
        remaining_action = remaining_actions.get(capability)
        capability_outcomes[capability] = {
            "attempted": bool(related_attempts),
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
            "usable_evidence_available": usable_evidence_available,
            "reconciliation": reconciliation,
            "remaining_fill_action": remaining_action.get("action_id")
            if isinstance(remaining_action, dict)
            else None,
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
    selection_version: str = "omi.capability.selection.v1",
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
