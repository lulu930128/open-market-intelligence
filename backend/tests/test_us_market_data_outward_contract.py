from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.ai import agentic_execution, data_quality_contract
from app.ai.capability_contract import normalize_selection, project_selected_data
from app.ai.capability_projection_registry import CAPABILITY_PROJECTION_REGISTRY
from app.ai.market_context.us_context import _latest_tool_result
from app.market_data.contracts import (
    EvidenceFreshness,
    InstrumentKey,
    InstrumentType,
    Market,
    MarketSession,
)
from app.market_data.policies import RealtimePolicy
from app.market_data.resolution import (
    BarSeriesCandidate,
    ResolutionCandidate,
    resolve_bar_series,
    resolve_quote,
)
from app.us_market.market_data_projection import (
    US_BARS_SCHEMA_VERSION,
    US_QUOTE_SCHEMA_VERSION,
    project_resolved_us_bars,
    project_resolved_us_quote,
)
from app.us_market.providers.canonical import canonical_yahoo_chart_payload


NEW_YORK = ZoneInfo("America/New_York")
NOW = datetime(2026, 8, 21, 10, 0, tzinfo=NEW_YORK)


def _batch():
    start = datetime(2026, 8, 21, 9, 30, tzinfo=NEW_YORK)
    payload = {
        "chart": {
            "result": [
                {
                    "meta": {
                        "symbol": "AAPL",
                        "currency": "USD",
                        "chartPreviousClose": 224.5,
                    },
                    "timestamp": [
                        int(start.timestamp()),
                        int((start + timedelta(minutes=1)).timestamp()),
                    ],
                    "indicators": {
                        "quote": [
                            {
                                "open": [225.0, 225.5],
                                "high": [225.8, 226.0],
                                "low": [224.9, 225.4],
                                "close": [225.6, 225.9],
                                "volume": [1200, 900],
                            }
                        ]
                    },
                }
            ],
            "error": None,
        }
    }
    return canonical_yahoo_chart_payload(
        instrument=InstrumentKey(
            market=Market.US,
            symbol="AAPL",
            instrument_type=InstrumentType.STOCK,
            venue="NASDAQ",
        ),
        payload=payload,
        fetched_at=NOW,
        interval="1m",
        session_scope="regular",
    )


def test_us_breadth_is_truthfully_unsupported_before_projection_exists() -> None:
    selection = normalize_selection(
        selection={"include": ["market.breadth"]},
        output="evidence_only",
        realtime_policy="cache_only",
        payload_level="compact",
        scope_type="market",
        question_intent="general",
        target_market="US",
    )
    assert "market.breadth" not in selection["required"]
    assert selection["unsupported_capabilities"][0]["capability"] == "market.breadth"
    assert selection["unsupported_capabilities"][0]["reason_code"] == "unsupported_market"


def test_us_market_aggregates_stay_unsupported_while_coverage_gate_is_closed() -> None:
    selection = normalize_selection(
        selection={
            "include": ["market.breadth", "market.sectors", "market.hot_groups"]
        },
        output="evidence_only",
        realtime_policy="cache_only",
        payload_level="compact",
        scope_type="market",
        question_intent="general",
        target_market="US",
    )

    unsupported = {
        item["capability"]: item["reason_code"]
        for item in selection["unsupported_capabilities"]
    }
    assert unsupported == {
        "market.breadth": "unsupported_market",
        "market.sectors": "unsupported_market",
        "market.hot_groups": "unsupported_market",
    }


def test_resolved_us_quote_uses_neutral_schema_and_lineage() -> None:
    batch = _batch()
    assert batch.snapshot is not None and batch.snapshot.quote is not None
    resolved = resolve_quote(
        [
            ResolutionCandidate(
                observation=batch.snapshot.quote,
                freshness=EvidenceFreshness.FRESH,
                provider_priority=100,
                session=MarketSession.CONTINUOUS,
            )
        ],
        policy=RealtimePolicy.PREFER_LIVE,
        now=NOW,
        max_age=timedelta(minutes=5),
    )
    payload = project_resolved_us_quote(resolved)
    assert payload["schema_version"] == US_QUOTE_SCHEMA_VERSION
    assert payload["selected_provider"] == "yahoo_chart"
    assert payload["selected_session"] == "continuous"
    assert payload["quote"]["currency"] == "USD"
    assert payload["quote"]["event_at"]
    assert payload["quote"]["fetched_at"]


def test_resolved_us_bars_projection_is_bounded_and_truthful() -> None:
    batch = _batch()
    resolved = resolve_bar_series(
        [
            BarSeriesCandidate(
                bars=batch.bars,
                freshness=EvidenceFreshness.FRESH,
                provider_priority=100,
                session=MarketSession.CONTINUOUS,
            )
        ],
        policy=RealtimePolicy.PREFER_LIVE,
        now=NOW,
        max_age=timedelta(minutes=5),
    )
    payload = project_resolved_us_bars(resolved, max_bars=1)
    assert payload["schema_version"] == US_BARS_SCHEMA_VERSION
    assert payload["available_bar_count"] == 2
    assert payload["returned_bar_count"] == 1
    assert payload["truncated"] is True
    assert payload["bars"][0]["provider"] == "yahoo_chart"
    assert payload["bars"][0]["volume_unit"] == "share"
    assert payload["selected_session"] == "continuous"


def test_us_projection_registry_accepts_resolved_shadow_payloads() -> None:
    quote_spec = CAPABILITY_PROJECTION_REGISTRY[
        ("quote.snapshot", "us_stock", "US")
    ]
    intraday_spec = CAPABILITY_PROJECTION_REGISTRY[
        ("intraday.bars", "us_stock", "US")
    ]
    context = {
        "data": {
            "resolved_market_data": {
                "quote_snapshot": {"schema_version": US_QUOTE_SCHEMA_VERSION},
                "intraday_bars": {"schema_version": US_BARS_SCHEMA_VERSION},
            }
        }
    }
    assert quote_spec.projector(context)["schema_version"] == US_QUOTE_SCHEMA_VERSION
    assert intraday_spec.projector(context)["schema_version"] == US_BARS_SCHEMA_VERSION
    assert quote_spec.canonical_schema_version == US_QUOTE_SCHEMA_VERSION
    assert intraday_spec.canonical_schema_version == US_BARS_SCHEMA_VERSION


def test_us_technical_capabilities_are_registered_on_neutral_daily_evidence() -> None:
    indicator_spec = CAPABILITY_PROJECTION_REGISTRY[
        ("technical.indicators", "us_stock", "US")
    ]
    structure_spec = CAPABILITY_PROJECTION_REGISTRY[
        ("technical.structure", "us_stock", "US")
    ]
    context = {
        "data": {
            "resolved_research": {
                "technical_indicators": {
                    "schema_version": "omi.research.technical.indicators.v1",
                    "status": "partial",
                },
                "technical_structure": {
                    "schema_version": "omi.research.technical.structure.v1",
                    "status": "partial",
                },
            }
        }
    }

    assert indicator_spec.dataset_ids == ("us.daily.ohlcv",)
    assert structure_spec.dataset_ids == ("us.daily.ohlcv",)
    assert indicator_spec.projector(context)["status"] == "partial"
    assert structure_spec.projector(context)["status"] == "partial"


def test_us_default_selection_includes_technical_research() -> None:
    selection = normalize_selection(
        selection={},
        output="decision_with_evidence",
        realtime_policy="cache_only",
        payload_level="compact",
        scope_type="us_stock",
        question_intent="general",
        target_market="US",
    )

    assert "technical.indicators" in selection["required"]
    assert "technical.structure" in selection["required"]
    assert not {
        "technical.indicators",
        "technical.structure",
    }.intersection(
        item["capability"] for item in selection["unsupported_capabilities"]
    )


def test_production_projection_uses_backend_owned_us_technical_research() -> None:
    response = {
        "target": {"type": "us_stock", "id": "AAPL", "market": "US"},
        "result": {
            "data": {
                "resolved_research": {
                    "technical_indicators": {
                        "kind": "technical_indicators",
                        "schema_version": "omi.research.technical.indicators.v1",
                        "status": "partial",
                        "quality": {
                            "facts_usable": True,
                            "decision_usable": False,
                            "reason_codes": ["CORPORATE_ACTION_COVERAGE_INCOMPLETE"],
                        },
                    },
                    "technical_structure": {
                        "kind": "technical_structure",
                        "schema_version": "omi.research.technical.structure.v1",
                        "status": "partial",
                        "trend_state": "bullish_stack",
                        "quality": {
                            "facts_usable": True,
                            "decision_usable": False,
                        },
                    },
                }
            }
        },
    }

    projected, unavailable = project_selected_data(
        response=response,
        selection={
            "required": ["technical.indicators", "technical.structure"],
            "optional": [],
            "fields": {},
            "limits": {},
        },
    )

    assert unavailable == []
    assert projected["technical.indicators"]["schema_version"] == (
        "omi.research.technical.indicators.v1"
    )
    assert projected["technical.indicators"]["quality"]["decision_usable"] is False
    assert projected["technical.structure"]["trend_state"] == "bullish_stack"


def test_production_capability_projection_prefers_resolved_us_canary_payloads() -> None:
    batch = _batch()
    assert batch.snapshot is not None and batch.snapshot.quote is not None
    resolved_quote = resolve_quote(
        [
            ResolutionCandidate(
                observation=batch.snapshot.quote,
                freshness=EvidenceFreshness.FRESH,
                provider_priority=100,
                session=MarketSession.CONTINUOUS,
            )
        ],
        policy=RealtimePolicy.PREFER_LIVE,
        now=NOW,
        max_age=timedelta(minutes=5),
    )
    resolved_bars = resolve_bar_series(
        [
            BarSeriesCandidate(
                bars=batch.bars,
                freshness=EvidenceFreshness.FRESH,
                provider_priority=100,
                session=MarketSession.CONTINUOUS,
            )
        ],
        policy=RealtimePolicy.PREFER_LIVE,
        now=NOW,
        max_age=timedelta(minutes=5),
    )
    response = {
        "target": {"type": "us_stock", "id": "AAPL", "market": "US"},
        "result": {
            "data": {
                "resolved_market_data": {
                    "quote_snapshot": project_resolved_us_quote(resolved_quote),
                    "intraday_bars": project_resolved_us_bars(resolved_bars),
                },
                "compact": {
                    "quote": {"status": "legacy", "price": 999},
                    "intraday_bars": {"status": "legacy", "points": []},
                },
            }
        },
    }
    projected, unavailable = project_selected_data(
        response=response,
        selection={
            "required": ["quote.snapshot", "intraday.bars"],
            "optional": [],
            "fields": {},
            "limits": {"intraday.bars": 1},
        },
    )

    assert unavailable == []
    assert projected["quote.snapshot"]["schema_version"] == US_QUOTE_SCHEMA_VERSION
    assert projected["quote.snapshot"]["quote"]["last_trade_price"] == "225.9"
    assert projected["intraday.bars"]["schema_version"] == US_BARS_SCHEMA_VERSION
    assert projected["intraday.bars"]["point_count"] == 2
    assert projected["intraday.bars"]["returned_point_count"] == 1
    assert projected["intraday.bars"]["truncated"] is True
    continuity = data_quality_contract._continuity_summary(
        projected["intraday.bars"],
        market="US",
    )
    assert continuity["declared_point_count"] == 2
    assert "insufficient_series_points" not in continuity["issues"]


def test_production_daily_projection_prefers_resolved_us_canary_payload() -> None:
    batch = _batch()
    resolved_bars = resolve_bar_series(
        [
            BarSeriesCandidate(
                bars=batch.bars,
                freshness=EvidenceFreshness.FRESH,
                provider_priority=100,
                session=MarketSession.CLOSED,
            )
        ],
        policy=RealtimePolicy.COMPLETED_SESSION,
        now=NOW,
        max_age=timedelta(days=7),
    )
    response = {
        "target": {"type": "us_stock", "id": "AAPL", "market": "US"},
        "result": {
            "data": {
                "resolved_market_data": {
                    "daily_ohlcv": project_resolved_us_bars(resolved_bars),
                },
                "chart": {
                    "point_count": 1,
                    "points": [{"time": "2026-08-21", "close": 999}],
                },
            }
        },
    }

    projected, unavailable = project_selected_data(
        response=response,
        selection={
            "required": ["daily.ohlcv"],
            "optional": [],
            "fields": {},
            "limits": {"daily.ohlcv": 1},
        },
    )

    assert unavailable == []
    daily = projected["daily.ohlcv"]
    assert daily["schema_version"] == US_BARS_SCHEMA_VERSION
    assert daily["point_count"] == 2
    assert daily["returned_point_count"] == 1
    assert daily["bars"][0]["close_price"] == "225.9"
    assert "points" not in daily


def test_internal_canary_projection_survives_tool_compaction_then_is_consumed() -> None:
    resolved_market_data = {
        "quote_snapshot": {"schema_version": US_QUOTE_SCHEMA_VERSION},
        "intraday_bars": {"schema_version": US_BARS_SCHEMA_VERSION},
    }
    tool_run = {
        "tool": "us.read_intraday_trend",
        "status": "success",
        "result_summary": agentic_execution._compact_result(
            {
                "symbol": "AAPL",
                "_resolved_market_data": resolved_market_data,
            }
        ),
    }

    selected = _latest_tool_result([tool_run], "us.read_intraday_trend")

    assert selected is not None
    assert selected["_resolved_market_data"] == resolved_market_data
    assert "_resolved_market_data" not in tool_run["result_summary"]
