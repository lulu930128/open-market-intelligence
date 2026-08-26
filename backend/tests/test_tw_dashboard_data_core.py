from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.market.tw_dashboard_data_core import (
    attach_taiwan_dashboard_data_core,
    project_taiwan_completed_dashboard_evidence,
)
from app.market_data.contracts import (
    AuthorityClass,
    BarFinalization,
    Market,
    MarketBreadthObservation,
    MarketIndexObservation,
    MarketSession,
    ObservationState,
    Quantity,
    QuantityUnit,
    ResolvedEvidenceHealth,
    ResolvedEvidenceStatus,
    ResolvedMarketBreadth,
    ResolvedMarketIndex,
    SourceLineage,
)


OBSERVED_AT = datetime(2026, 8, 25, 6, 30, tzinfo=timezone.utc)


def _lineage(*, provider: str, source: str) -> SourceLineage:
    return SourceLineage(
        provider=provider,
        source=source,
        authority=AuthorityClass.EXCHANGE,
        event_at=OBSERVED_AT,
        fetched_at=OBSERVED_AT,
        observation_id="observation:1",
        raw_receipt_id="raw_fetch_result:1",
        content_hash="a" * 64,
    )


def _health(provider: str) -> ResolvedEvidenceHealth:
    return ResolvedEvidenceHealth(
        status=ResolvedEvidenceStatus.SELECTED,
        selected_provider=provider,
        selected_source=f"{provider}_source",
        selected_session=MarketSession.CLOSED,
        selected_event_at=OBSERVED_AT,
        selection_reason="official_completed_session_selected",
        facts_usable=True,
        research_usable=True,
    )


def _results() -> tuple[SimpleNamespace, SimpleNamespace]:
    index = MarketIndexObservation(
        market=Market.TW,
        index_id="TAIEX",
        venue="TWSE",
        lineage=_lineage(provider="twse_openapi", source="twse_fmtqik"),
        session=MarketSession.CLOSED,
        trade_date=date(2026, 8, 25),
        close_value=Decimal("24500.25"),
        price_change=Decimal("120.50"),
        trade_volume=Quantity(value=Decimal("123456"), unit=QuantityUnit.SHARE),
        trade_value=Decimal("987654321"),
        currency="TWD",
        transaction_count=1234,
        state=ObservationState.AVAILABLE,
        value_semantics="official_market_index_close",
        finalization=BarFinalization.FINAL,
        official=True,
        provisional=False,
    )
    breadth = MarketBreadthObservation(
        market=Market.TW,
        venue="TWSE",
        lineage=_lineage(provider="twse_openapi", source="twse_stock_day_all"),
        session=MarketSession.CLOSED,
        trade_date=date(2026, 8, 25),
        scope="full_market",
        universe_source="active_stock_master_plus_official_rows",
        universe_count=1000,
        advance_count=500,
        decline_count=400,
        unchanged_count=50,
        unknown_count=40,
        missing_count=10,
        trade_value=None,
        currency=None,
        state=ObservationState.PARTIAL,
        price_semantics="official_session_close",
        official=True,
        provisional=False,
    )
    index_result = SimpleNamespace(
        resolved=ResolvedMarketIndex(market_index=index, health=_health("twse_openapi")),
        dataset_health=None,
        provider_health=(),
        limitations=(),
    )
    breadth_result = SimpleNamespace(
        resolved=ResolvedMarketBreadth(
            breadth=breadth,
            health=_health("twse_openapi"),
        ),
        dataset_health=None,
        provider_health=(),
        limitations=("PARTIAL_UNIVERSE_COVERAGE",),
    )
    return index_result, breadth_result


def test_projection_preserves_completed_component_time_lineage_and_unknowns() -> None:
    index_result, breadth_result = _results()

    projected = project_taiwan_completed_dashboard_evidence(
        index_result=index_result,
        breadth_result=breadth_result,
    )

    official_index = projected["official_index"]["observation"]
    official_breadth = projected["official_breadth"]["observation"]
    assert official_index["trade_date"] == date(2026, 8, 25)
    assert official_index["close"] == 24500.25
    assert official_index["lineage"]["raw_receipt_id"] == "raw_fetch_result:1"
    assert official_breadth["unknown_count"] == 40
    assert official_breadth["missing_count"] == 10
    assert official_breadth["status"] == "partial"
    assert official_breadth["decision_usable"] is False


def test_dashboard_completed_components_cut_over_to_resolved_data_core() -> None:
    index_result, breadth_result = _results()
    payload = {
        "indices": [
            {
                "index_id": "TAIEX",
                "breadth": {
                    "scope": "full_market",
                    "advance_count": 999,
                    "decline_count": 0,
                    "unchanged_count": 0,
                    "total_count": 999,
                },
            }
        ]
    }

    with (
        patch(
            "app.market.tw_dashboard_data_core.read_taiwan_official_index",
            return_value=index_result,
        ) as read_index,
        patch(
            "app.market.tw_dashboard_data_core.read_taiwan_official_breadth",
            return_value=breadth_result,
        ) as read_breadth,
    ):
        projected = attach_taiwan_dashboard_data_core(Mock(), payload)

    item = projected["indices"][0]
    read_index.assert_called_once()
    read_breadth.assert_called_once()
    assert item["official_close_price"] == 24500.25
    assert item["official_close_trade_date"] == date(2026, 8, 25)
    assert item["breadth"]["advance_count"] == 500
    assert item["data_core_projection_scope"] == {
        "official_index": "resolved_data_core",
        "official_breadth": "resolved_data_core",
    }


def test_dashboard_fails_closed_when_data_core_is_missing() -> None:
    missing_health = ResolvedEvidenceHealth(
        status=ResolvedEvidenceStatus.MISSING,
        selection_reason="no_eligible_candidate",
        limitations=("NO_ELIGIBLE_CANDIDATE",),
    )
    missing_index = SimpleNamespace(
        resolved=ResolvedMarketIndex(market_index=None, health=missing_health),
        dataset_health=None,
        provider_health=(),
        limitations=("NO_ELIGIBLE_CANDIDATE",),
    )
    missing_breadth = SimpleNamespace(
        resolved=ResolvedMarketBreadth(breadth=None, health=missing_health),
        dataset_health=None,
        provider_health=(),
        limitations=("NO_ELIGIBLE_CANDIDATE",),
    )
    legacy_breadth = {
        "scope": "full_market",
        "advance_count": 10,
        "decline_count": 5,
        "unchanged_count": 1,
        "total_count": 16,
    }

    with (
        patch(
            "app.market.tw_dashboard_data_core.read_taiwan_official_index",
            return_value=missing_index,
        ),
        patch(
            "app.market.tw_dashboard_data_core.read_taiwan_official_breadth",
            return_value=missing_breadth,
        ),
    ):
        projected = attach_taiwan_dashboard_data_core(
            Mock(),
            {
                "indices": [
                    {
                        "index_id": "TAIEX",
                        "official_close_price": 24000.0,
                        "breadth": legacy_breadth,
                    }
                ]
            },
        )

    item = projected["indices"][0]
    assert item["completed_official_index"] is None
    assert item["completed_official_breadth"] is None
    assert item["official_close_price"] is None
    assert item["official_close_status"] == "not_available"
    assert item["breadth"] is None
    assert item["data_core_projection_scope"] == {
        "official_index": "data_core_missing",
        "official_breadth": "data_core_missing",
    }


def test_dashboard_keeps_index_and_breadth_read_failures_independent() -> None:
    _index_result, breadth_result = _results()

    with (
        patch(
            "app.market.tw_dashboard_data_core.read_taiwan_official_index",
            side_effect=RuntimeError("index schema unavailable"),
        ),
        patch(
            "app.market.tw_dashboard_data_core.read_taiwan_official_breadth",
            return_value=breadth_result,
        ),
    ):
        projected = attach_taiwan_dashboard_data_core(
            Mock(),
            {
                "indices": [
                    {
                        "index_id": "TAIEX",
                        "breadth": {"scope": "full_market"},
                    }
                ]
            },
        )

    item = projected["indices"][0]
    assert item["data_core"]["official_index"]["status"] == "unavailable"
    assert item["completed_official_index"] is None
    assert item["completed_official_breadth"]["advance_count"] == 500
    assert item["data_core_projection_scope"] == {
        "official_index": "data_core_missing",
        "official_breadth": "resolved_data_core",
    }
