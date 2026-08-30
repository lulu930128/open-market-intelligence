"""Canonical tracked job type names."""

JP_WATCHLIST_RESOURCE_REFRESH_JOB_TYPE = "jp_market.watchlist_resource_refresh"
JP_SCHEDULED_WATCHLIST_RESOURCE_REFRESH_JOB_TYPE = (
    "jp_market.scheduler.watchlist_resource_refresh"
)
KR_WATCHLIST_RESOURCE_REFRESH_JOB_TYPE = "kr_market.watchlist_resource_refresh"
KR_SCHEDULED_WATCHLIST_RESOURCE_REFRESH_JOB_TYPE = (
    "kr_market.scheduler.watchlist_resource_refresh"
)
TAIWAN_DERIVATIVES_SCHEDULED_REFRESH_JOB_TYPE = (
    "scheduler.taiwan_derivatives_refresh"
)
TAIWAN_BROKER_BRANCH_MARKET_REFRESH_JOB_TYPE = (
    "scheduler.tw_broker_branch_market_refresh"
)
TAIWAN_BROKER_BRANCH_BEHAVIOR_SHADOW_JOB_TYPE = (
    "research.tw_broker_branch_behavior_shadow"
)
WATCHLIST_RADAR_AUTO_SNAPSHOT_JOB_TYPE = "watchlist.scheduler.radar_snapshot"
WATCHLIST_RADAR_OUTCOME_RECONCILE_JOB_TYPE = (
    "watchlist.radar_v2.outcome_reconcile"
)
CROSS_MARKET_CONTEXT_REFRESH_JOB_TYPE = "cross_market.context_refresh"
MARKET_EOD_COVERAGE_RECONCILE_JOB_TYPE = "market_data.eod_coverage_reconcile"
US_OHLC_HISTORY_REPAIR_JOB_TYPE = "us_market.ohlc_history_repair"
US_PRIORITY_OHLC_RECONCILE_JOB_TYPE = "us_market.priority_ohlc_reconcile"
US_INDEX_DATA_REPAIR_JOB_TYPE = "us_market.index_data_repair"
US_CURRENT_MARKET_BOOTSTRAP_JOB_TYPE = "us.bootstrap_current_market_cache"
US_SEC_FORM4_SYNC_JOB_TYPE = "us_market.sec_form4_sync"
US_SEC_13F_QUARTER_SYNC_JOB_TYPE = "us_market.sec_13f_quarter_sync"
US_SEC_13F_MAPPING_SYNC_JOB_TYPE = "us_market.sec_13f_mapping_sync"
US_SEC_13F_HISTORY_SYNC_JOB_TYPE = "us_market.sec_13f_history_sync"
