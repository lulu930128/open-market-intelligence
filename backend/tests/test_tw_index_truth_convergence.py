from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.ai.market_context import taiwan_market
from app.ai.market_context.taiwan_projection import _compact_index_quote
from app.market.index_resolution import (
    TAIWAN_INDEX_HEADLINE_COMPATIBILITY_LIMITATION,
    TAIWAN_INDEX_HEADLINE_COMPATIBILITY_VERSION,
    ResolvedTaiwanIndexTruth,
    project_taiwan_index_headline,
    project_taiwan_index_quote_side,
    resolve_taiwan_index_truth,
)
from app.market.tw_dataset_catalog import TW_DATASET_CATALOG
from app.market import tw_current_market_operations
from app.market.tw_market_dashboard import _build_resolved_indices
from app.market_data.registry import DATASET_REGISTRY


TAIPEI = timezone(timedelta(hours=8))
CHECKED_AT = datetime(2026, 9, 1, 15, 20, tzinfo=TAIPEI)
REPO_ROOT = Path(__file__).resolve().parents[2]


def _calendar() -> dict[str, object]:
    return {
        "market": "tw",
        "timezone": "Asia/Taipei",
        "checked_at": CHECKED_AT.isoformat(),
        "date": CHECKED_AT.date().isoformat(),
        "is_trading_day": True,
        "phase": "post_close",
        "previous_trading_day": "2026-08-31",
        "session": {"open_time": "09:00", "close_time": "13:30"},
    }


def _snapshot() -> dict[str, object]:
    return {
        "index_id": "TAIEX",
        "time": "2026-09-01",
        "as_of": "2026-09-01T13:30:00+08:00",
        "close": 46_221.63,
        "previous_close": 45_900.0,
        "source": "fugle_indices_stream",
        "completed_daily_close": 46_164.72,
        "completed_daily_trade_date": "2026-09-01",
        "completed_daily_event_time": "2026-09-01T13:30:00+08:00",
        "completed_daily_source": "twse_mi_5mins_hist",
        "completed_daily_provider": "twse",
        "completed_daily_authority": "exchange",
        "completed_daily_finalization": "final",
        "completed_daily_official": True,
        "completed_daily_release_status": "released",
        "completed_daily_reconciliation_status": "not_applicable",
        "completed_daily_qualified": True,
        "completed_daily_previous_close": 45_900.0,
        "completed_daily_previous_close_trade_date": "2026-08-31",
        "completed_daily_previous_close_source": "twse_mi_5mins_hist",
        "completed_daily_previous_close_provider": "twse",
        "completed_daily_previous_close_authority": "exchange",
        "completed_daily_previous_close_finalization": "final",
    }


def test_resolved_truth_confirms_release_qualified_completed_daily_close() -> None:
    truth = resolve_taiwan_index_truth(
        intraday=None,
        index_snapshot=_snapshot(),
        calendar_status=_calendar(),
        index_id="TAIEX",
        acquisition_policy="cache_only",
    )

    assert isinstance(truth, ResolvedTaiwanIndexTruth)
    assert truth.selected_candidate == "completed_daily_bar"
    assert truth.selected_value == 46_164.72
    assert truth.selected_authority == "official_exchange"
    assert truth.selected_finalization == "final"
    assert truth.official_source is True
    assert truth.official_close_confirmed is True
    assert truth.official_close_status == "confirmed"
    assert truth.official_close_price == truth.selected_value
    assert truth.decision_usable is True
    assert truth.selected_previous_close == 45_900.0
    assert truth.selected_change == pytest.approx(264.72)
    assert truth.selected_change_pct == pytest.approx(264.72 / 45_900 * 100)
    assert truth.selected_previous_close_source == "twse_mi_5mins_hist"
    assert truth.selected_previous_close_status == "current"
    assert truth.current_observation is not None
    assert truth.current_observation.previous_close_status == "current"


def test_tpex_official_close_rolls_over_previous_close_without_derived_mix() -> None:
    checked_at = datetime(2026, 9, 2, 15, 20, tzinfo=TAIPEI)
    calendar = {
        **_calendar(),
        "checked_at": checked_at.isoformat(),
        "date": "2026-09-02",
        "previous_trading_day": "2026-09-01",
    }
    truth = resolve_taiwan_index_truth(
        intraday=None,
        index_snapshot={
            "index_id": "TPEX",
            "time": "2026-09-02",
            "as_of": "2026-09-02T13:30:00+08:00",
            "close": 406.96,
            "previous_close": 410.60,
            "change": -3.64,
            "source": "tpex_derived_stock_aggregation",
            "provider": "tpex",
            "official_close_status": "confirmed",
            "official_close_price": 406.96,
            "official_close_trade_date": "2026-09-02",
            "official_close_time": "2026-09-02T14:00:00+08:00",
            "official_close_source": "tpex_official_market_index_daily",
            "official_close_provider": "tpex",
            "official_close_authority": "exchange",
            "official_close_finalization": "final",
            "official_close_change": -3.81,
            "official_close_previous_close": 410.77,
            "official_close_previous_close_trade_date": "2026-09-01",
            "official_close_previous_close_source": (
                "tpex_official_market_index_daily"
            ),
            "official_close_previous_close_provider": "tpex",
            "official_close_previous_close_authority": "exchange",
            "official_close_previous_close_finalization": "final",
        },
        calendar_status=calendar,
        index_id="TPEX",
        acquisition_policy="cache_only",
    )

    assert truth.selected_candidate == "official_close"
    assert truth.selected_value == 406.96
    assert truth.selected_previous_close == 410.77
    assert truth.selected_change == pytest.approx(-3.81)
    assert truth.selected_authority == "official_exchange"
    assert truth.selected_finalization == "final"
    assert truth.official_close_confirmed is True
    assert truth.selected_previous_close_status == "current"


def test_previous_close_with_unexpected_trade_date_is_fail_visible() -> None:
    snapshot = _snapshot()
    snapshot["completed_daily_previous_close_trade_date"] = "2026-08-28"

    truth = resolve_taiwan_index_truth(
        intraday=None,
        index_snapshot=snapshot,
        calendar_status=_calendar(),
        index_id="TAIEX",
        acquisition_policy="cache_only",
    )

    assert truth.selected_previous_close == 45_900.0
    assert truth.selected_previous_close_status == "stale"
    assert any("expected prior trading day" in warning for warning in truth.warnings)


def test_ai_projection_reuses_embedded_truth_when_current_core_conflicts() -> None:
    truth = resolve_taiwan_index_truth(
        intraday=None,
        index_snapshot=_snapshot(),
        calendar_status=_calendar(),
        index_id="TAIEX",
        acquisition_policy="cache_only",
    )
    snapshot = {
        **_snapshot(),
        "resolution": truth.model_dump(mode="json"),
        "current_data_core": {
            "index": {
                "close": 46_221.63,
                "trade_date": "2026-09-01",
                "as_of": "2026-09-01T13:30:00+08:00",
                "source": "fugle_indices_stream",
                "decision_usable": True,
            }
        },
    }

    quote = _compact_index_quote(
        index_id="TAIEX",
        index_snapshot=snapshot,
        intraday=None,
        calendar_status=_calendar(),
    )

    assert quote["latest_price"] == 46_164.72
    assert quote["official_close_price"] == 46_164.72
    assert quote["previous_close"] == 45_900.0
    assert quote["change"] == pytest.approx(264.72)
    assert quote["selected_candidate"] == "completed_daily_bar"
    assert quote["resolution_id"] == truth.resolution_id


def test_shared_headline_projection_keeps_one_selected_lane() -> None:
    truth = resolve_taiwan_index_truth(
        intraday=None,
        index_snapshot=_snapshot(),
        calendar_status=_calendar(),
        index_id="TAIEX",
        acquisition_policy="cache_only",
    )
    headline = project_taiwan_index_headline(
        {
            **_snapshot(),
            "resolution": truth.model_dump(mode="json"),
            "current_data_core": {
                "index": {
                    "index_id": "TAIEX",
                    "close": 46_221.63,
                    "previous_close": 45_900.0,
                    "change": 321.63,
                    "source": "fugle_indices_stream",
                    "provider": "fugle_marketdata",
                }
            },
        }
    )

    assert headline is not None
    assert headline["value"] == 46_164.72
    assert headline["previous_close"] == 45_900.0
    assert headline["change"] == pytest.approx(264.72)
    assert headline["provider"] == "twse"
    assert headline["source"] == "twse_mi_5mins_hist"
    assert headline["resolution_id"] == truth.resolution_id
    assert headline["compatibility_fallback"] is False


def test_index_quote_side_projects_the_same_resolved_lane() -> None:
    truth = resolve_taiwan_index_truth(
        intraday=None,
        index_snapshot=_snapshot(),
        calendar_status=_calendar(),
        index_id="TAIEX",
        acquisition_policy="cache_only",
    )
    quote_side = project_taiwan_index_quote_side(
        {
            **_snapshot(),
            "resolution": truth.model_dump(mode="json"),
        }
    )

    assert quote_side is not None
    assert quote_side["current_observation"]["value"] == 46_164.72
    assert quote_side["previous_close"] == 45_900.0
    assert quote_side["source"] == "twse_mi_5mins_hist"
    assert quote_side["resolution_id"] == truth.resolution_id
    assert quote_side["capabilities"] == {
        "supports_volume": False,
        "supports_vwap": False,
        "supports_price_limit": False,
        "supports_quote_depth": False,
    }


def test_headline_compatibility_fallback_is_explicit_and_never_official() -> None:
    headline = project_taiwan_index_headline(
        {
            "index_id": "TAIEX",
            "resolution": {"resolution_version": "tw.index.resolution.v1"},
            "current_data_core": {
                "index": {
                    "index_id": "TAIEX",
                    "close": 46_221.63,
                    "previous_close": 46_000.0,
                    "source": "fugle_indices_stream",
                    "provider": "fugle_marketdata",
                    "official": True,
                    "decision_usable": True,
                }
            },
        }
    )

    assert headline is not None
    assert headline["compatibility_fallback"] is True
    assert headline["resolution_version"] == TAIWAN_INDEX_HEADLINE_COMPATIBILITY_VERSION
    assert headline["official_close_confirmed"] is False
    assert headline["finalization"] == "unknown"
    assert TAIWAN_INDEX_HEADLINE_COMPATIBILITY_LIMITATION in headline["limitations"]
    assert "INDEX_HEADLINE_RESOLUTION_INVALID" in headline["limitations"]


def test_dashboard_and_ai_consumers_use_market_owned_headline_projection() -> None:
    for relative_path in (
        "backend/app/market/tw_market_dashboard.py",
        "backend/app/ai/market_context/taiwan_market.py",
    ):
        source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        assert "project_taiwan_index_headline" in source
        assert '"canonical_current_index"' not in source
    dashboard_source = (
        REPO_ROOT / "backend/app/market/tw_market_dashboard.py"
    ).read_text(encoding="utf-8")
    assert "if current_index is not None" not in dashboard_source


def test_dashboard_and_ai_emit_the_same_embedded_resolution() -> None:
    truth = resolve_taiwan_index_truth(
        intraday=None,
        index_snapshot=_snapshot(),
        calendar_status=_calendar(),
        index_id="TAIEX",
        acquisition_policy="cache_only",
    )
    summary_item = {
        **_snapshot(),
        "market": "TWSE",
        "resolution": truth.model_dump(mode="json"),
        "current_data_core": {
            "index": {
                "index_id": "TAIEX",
                "close": 46_221.63,
                "previous_close": 45_900.0,
                "change": 321.63,
                "as_of": "2026-09-01T13:30:00+08:00",
                "trade_date": "2026-09-01",
                "source": "fugle_indices_stream",
                "provider": "fugle_marketdata",
                "provisional": True,
                "decision_usable": False,
            }
        },
    }
    summary = {
        "source": "shared_market_data_core",
        "acquisition_policy": "cache_only",
        "indices": [summary_item],
    }

    with patch(
        "app.market.tw_market_dashboard.get_market_index_summary",
        return_value=summary,
    ):
        dashboard_items, _breadth, _warnings = _build_resolved_indices(
            SimpleNamespace()
        )
    ai_payload = taiwan_market._market_indices_capability(
        db=SimpleNamespace(),
        dependencies=SimpleNamespace(
            get_market_index_summary=lambda *_args, **_kwargs: summary,
        ),
        generated_at=CHECKED_AT,
    )

    dashboard = dashboard_items[0]
    ai_item = ai_payload["items"][0]
    for field in (
        "value",
        "previous_close",
        "change",
        "change_pct",
        "source",
        "provider",
        "selected_candidate",
        "resolution_version",
        "resolution_id",
    ):
        assert dashboard[field] == ai_item[field]


def test_active_session_resolution_remains_the_dashboard_and_ai_headline() -> None:
    active_calendar = {
        "market": "tw",
        "timezone": "Asia/Taipei",
        "checked_at": "2026-09-01T10:01:00+08:00",
        "date": "2026-09-01",
        "is_trading_day": True,
        "phase": "regular",
        "previous_trading_day": "2026-08-31",
    }
    active_snapshot = {
        "index_id": "TAIEX",
        "market": "TWSE",
        "time": "2026-09-01",
        "as_of": "2026-09-01T10:00:00+08:00",
        "close": 46_100.0,
        "previous_close": 45_900.0,
        "source": "fugle_indices_stream",
        "provider": "fugle_marketdata",
    }
    truth = resolve_taiwan_index_truth(
        intraday=None,
        index_snapshot=active_snapshot,
        calendar_status=active_calendar,
        index_id="TAIEX",
        acquisition_policy="cache_only",
    )
    summary_item = {
        **active_snapshot,
        "resolution": truth.model_dump(mode="json"),
        "current_data_core": {
            "index": {
                "index_id": "TAIEX",
                "close": 46_100.0,
                "previous_close": 45_900.0,
                "change": 200.0,
                "as_of": "2026-09-01T10:00:00+08:00",
                "trade_date": "2026-09-01",
                "source": "fugle_indices_stream",
                "provider": "fugle_marketdata",
                "provisional": True,
                "decision_usable": True,
            }
        },
    }
    summary = {
        "source": "shared_market_data_core",
        "acquisition_policy": "cache_only",
        "indices": [summary_item],
    }

    with patch(
        "app.market.tw_market_dashboard.get_market_index_summary",
        return_value=summary,
    ):
        dashboard_items, _breadth, _warnings = _build_resolved_indices(
            SimpleNamespace()
        )
    ai_payload = taiwan_market._market_indices_capability(
        db=SimpleNamespace(),
        dependencies=SimpleNamespace(
            get_market_index_summary=lambda *_args, **_kwargs: summary,
        ),
        generated_at=datetime.fromisoformat("2026-09-01T10:01:00+08:00"),
    )

    dashboard = dashboard_items[0]
    ai_item = ai_payload["items"][0]
    assert truth.selected_candidate == "index_summary"
    assert dashboard["value"] == 46_100.0
    assert ai_item["value"] == 46_100.0
    assert dashboard["provider"] == "fugle_marketdata"
    assert ai_item["provider"] == "fugle_marketdata"
    assert dashboard["resolution_id"] == truth.resolution_id
    assert ai_item["resolution_id"] == truth.resolution_id
    assert dashboard["compatibility_fallback"] is False
    assert ai_item["compatibility_fallback"] is False


def test_index_intraday_registry_has_only_the_unified_bar_owner() -> None:
    shared = DATASET_REGISTRY.get("tw.market_index.intraday")
    market = TW_DATASET_CATALOG.get("tw.market_index.intraday")

    assert shared.schema_version == "tw.bar.series_read.v1"
    assert shared.owner == "app.market.tw_bar_service"
    assert shared.read_operation == "read_taiwan_index_intraday_bars"
    assert shared.refresh_operation == "tw.refresh_index_intraday_bars"
    assert "market_intraday_bar_lineage" in shared.storage_reference
    assert market.payload_contract == "tw.bar.series_read.v1"
    assert market.read_operation.endswith("read_taiwan_index_intraday_bars")
    assert market.refresh_operation == "tw.refresh_index_intraday_bars"
    assert market.projection_operation.endswith(
        "project_taiwan_index_intraday_bars"
    )
    assert "taiwan_current_index_snapshot" not in market.storage_tables
    assert "minute_at" not in market.required_lineage_fields
    assert "calculation_version" in market.required_lineage_fields


def test_production_index_consumers_do_not_call_legacy_truth_resolver() -> None:
    for relative_path in (
        "backend/app/market/indices.py",
        "backend/app/market/index_contract_snapshot.py",
        "backend/app/ai/market_context/taiwan_projection.py",
    ):
        source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        called_names = {
            node.func.id
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert "resolve_taiwan_index_quote_state" not in called_names
        assert "resolve_taiwan_index_truth(" in source
        assert "read_taiwan_index_minute_series" not in source

    summary_source = (
        REPO_ROOT / "backend/app/market/indices.py"
    ).read_text(encoding="utf-8")
    ai_source = (
        REPO_ROOT / "backend/app/ai/market_context/taiwan_market.py"
    ).read_text(encoding="utf-8")
    assert "read_taiwan_index_intraday_bars(" in summary_source
    assert "intraday=intraday" in summary_source
    assert "dependencies.read_taiwan_index_intraday_bars(" in ai_source
    assert 'session_scope="current_session"' in ai_source


def test_registered_index_refresh_materializes_then_rereads_unified_bars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []
    expected = object()

    monkeypatch.setattr(
        tw_current_market_operations,
        "refresh_taiwan_current_index_operation",
        lambda _db, **kwargs: calls.append(("acquire", kwargs["index_id"])),
    )
    monkeypatch.setattr(
        tw_current_market_operations,
        "materialize_index_minute_candidates",
        lambda _db, **kwargs: (
            calls.append(("materialize", kwargs["index_id"])),
            SimpleNamespace(candidates=("candidate",)),
        )[1],
    )

    class _Transaction:
        def __init__(self, _db: object) -> None:
            pass

        def persist_materialized_bars(self, candidates: tuple[object, ...]) -> None:
            calls.append(("persist", candidates))

    monkeypatch.setattr(
        tw_current_market_operations,
        "TaiwanBarMaterializationTransaction",
        _Transaction,
    )
    monkeypatch.setattr(
        tw_current_market_operations,
        "read_taiwan_index_intraday_bars",
        lambda _db, **kwargs: (
            calls.append(("reread", kwargs["index_id"])),
            expected,
        )[1],
    )

    result = (
        tw_current_market_operations.refresh_taiwan_index_intraday_bars_operation(
            object(),
            index_id="TAIEX",
            requested_at=CHECKED_AT,
        )
    )

    assert result is expected
    assert calls == [
        ("acquire", "TAIEX"),
        ("materialize", "TAIEX"),
        ("persist", ("candidate",)),
        ("reread", "TAIEX"),
    ]
