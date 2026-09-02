from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import inspect
from types import SimpleNamespace
from unittest.mock import patch

from app.ai import ask_execution, capability_contract, query_plan
from app.ai.schemas import AiAskRequest
from app.routers import us_market as us_market_router
from app.market_data.contracts import (
    EvidenceFreshness,
    InstrumentKey,
    InstrumentType,
    Market,
)
from app.us_market import market_indices
from app.us_market.market_indices import (
    US_MARKET_INDEX_DEFINITIONS,
    US_MARKET_INDEX_SYMBOLS,
    compose_us_market_indices,
    read_us_market_indices,
)
from app.us_market.market_truth_contracts import (
    USChangeCalculationStatus,
    USCloseEvidenceKind,
    USComparisonPurpose,
    USObservationKind,
)
from app.us_market.temporal_expectedness import USTradeRecency


NOW = datetime(2026, 9, 1, 19, 59, tzinfo=timezone.utc)


def _truth(
    symbol: str,
    *,
    provider: str = "yahoo_chart",
    source: str = "yahoo.chart.1m",
    fallback_used: bool = False,
    available: bool = True,
    freshness: EvidenceFreshness = EvidenceFreshness.FRESH,
    current_for_session: bool = True,
    research_usable: bool | None = None,
):
    instrument = InstrumentKey(
        market=Market.US,
        symbol=symbol,
        instrument_type=InstrumentType.INDEX,
        venue="INDEX",
    )
    revision = hashlib.sha256(symbol.encode("utf-8")).hexdigest()
    if not available:
        return SimpleNamespace(
            instrument=instrument,
            market_phase="regular",
            headline_observation=None,
            current_observation=None,
            change_metrics=(),
            comparison_references=(),
            close_evidence=(),
            truth_revision=revision,
            limitations=("FIXTURE_INDEX_MISSING",),
        )
    observation_id = f"quote:{symbol}:current"
    evidence_id = f"daily:{symbol}:previous"
    value = Decimal("100") + Decimal(str(US_MARKET_INDEX_SYMBOLS.index(symbol)))
    observation_research_usable = (
        freshness is not EvidenceFreshness.STALE
        if research_usable is None
        else research_usable
    )
    observation = SimpleNamespace(
        observation_id=observation_id,
        kind=USObservationKind.QUOTE,
        trade_date=date(2026, 9, 1),
        price=value,
        event_at=NOW,
        selected_provider=provider,
        selected_source=source,
        selection_reason="FIXTURE_SELECTED",
        fallback_used=fallback_used,
        freshness=freshness,
        provider_snapshot_freshness=EvidenceFreshness.FRESH,
        trade_recency=(
            USTradeRecency.OLD
            if freshness is EvidenceFreshness.STALE
            else USTradeRecency.CURRENT
        ),
        current_session_satisfied=current_for_session,
        display_usable=True,
        research_usable=observation_research_usable,
        limitations=(),
    )
    reference = SimpleNamespace(
        purpose=USComparisonPurpose.HEADLINE_CHANGE,
        evidence_id=evidence_id,
        reference_trade_date=date(2026, 8, 31),
        price=value - Decimal("1"),
        limitations=(),
    )
    metric = SimpleNamespace(
        purpose=USComparisonPurpose.HEADLINE_CHANGE,
        calculation_status=USChangeCalculationStatus.CALCULATED,
        absolute_change=Decimal("1"),
        percent_change=Decimal("1"),
        research_usable=observation_research_usable,
    )
    evidence = SimpleNamespace(
        evidence_id=evidence_id,
        evidence_kind=USCloseEvidenceKind.COMPLETED_DAILY,
    )
    return SimpleNamespace(
        instrument=instrument,
        market_phase="regular",
        headline_observation=observation,
        current_observation=observation if current_for_session else None,
        change_metrics=(metric,),
        comparison_references=(reference,),
        close_evidence=(evidence,),
        truth_revision=revision,
        limitations=(),
    )


def test_us_market_indices_preserve_order_and_direct_truth_lineage() -> None:
    snapshots = tuple(
        _truth(
            symbol,
            provider="twelve_data" if symbol == "^VIX" else "yahoo_chart",
            source="twelve_data.quote" if symbol == "^VIX" else "yahoo.chart.1m",
            fallback_used=symbol == "^VIX",
        )
        for symbol in US_MARKET_INDEX_SYMBOLS
    )

    aggregate = compose_us_market_indices(
        snapshots=snapshots,
        evaluated_at=NOW,
    )

    assert tuple(item.canonical_symbol for item in aggregate.items) == (
        "^GSPC",
        "^DJI",
        "^IXIC",
        "^NDX",
        "^SOX",
        "^VIX",
    )
    assert aggregate.status == "ready"
    assert aggregate.coverage_status == "complete"
    assert aggregate.count == 6
    assert aggregate.market_session == "regular"
    assert aggregate.current_for_requested_session is True
    assert aggregate.is_current is True
    assert aggregate.is_complete is True
    assert aggregate.observation_mix == (USObservationKind.QUOTE,)
    for item, direct in zip(aggregate.items, snapshots):
        assert item.selected_provider == direct.headline_observation.selected_provider
        assert item.selected_source == direct.headline_observation.selected_source
        assert item.event_at == direct.headline_observation.event_at
        assert item.fallback_used == direct.headline_observation.fallback_used
        assert item.observation_kind is USObservationKind.QUOTE
        assert item.reference_kind is USCloseEvidenceKind.COMPLETED_DAILY
    assert aggregate.items[-1].selected_provider == "twelve_data"
    assert aggregate.items[-1].fallback_used is True


def test_us_market_indices_keep_single_symbol_failure_partial() -> None:
    snapshots = tuple(
        _truth(symbol, available=symbol != "^VIX")
        for symbol in US_MARKET_INDEX_SYMBOLS
    )

    aggregate = compose_us_market_indices(
        snapshots=snapshots,
        evaluated_at=NOW,
    )

    assert aggregate.status == "partial"
    assert aggregate.coverage_status == "partial"
    assert aggregate.count == 5
    assert aggregate.missing == ("^VIX",)
    assert aggregate.facts_usable is True
    assert aggregate.decision_usable is False
    assert aggregate.current_for_requested_session is False
    assert aggregate.is_complete is False
    assert aggregate.items[-1].value is None
    assert aggregate.items[-1].freshness_status is EvidenceFreshness.UNKNOWN


def test_us_market_indices_keep_stale_current_session_identity_separate() -> None:
    snapshots = tuple(
        _truth(
            symbol,
            freshness=(
                EvidenceFreshness.STALE
                if symbol == "^VIX"
                else EvidenceFreshness.FRESH
            ),
        )
        for symbol in US_MARKET_INDEX_SYMBOLS
    )

    aggregate = compose_us_market_indices(
        snapshots=snapshots,
        evaluated_at=NOW,
    )

    assert aggregate.status == "ready"
    assert aggregate.count == 6
    assert aggregate.facts_usable is True
    assert aggregate.current_for_requested_session is True
    assert aggregate.is_current is False
    assert aggregate.decision_usable is False
    assert aggregate.items[-1].freshness_status is EvidenceFreshness.STALE
    assert aggregate.items[-1].provider_snapshot_freshness is EvidenceFreshness.FRESH
    assert aggregate.items[-1].trade_recency is USTradeRecency.OLD
    assert aggregate.items[-1].decision_usable is False
    assert "US_INDEX_OBSERVATION_STALE" in aggregate.items[-1].limitations


def test_us_market_indices_reject_previous_session_identity_for_currentness() -> None:
    snapshots = tuple(
        _truth(symbol, current_for_session=symbol != "^VIX")
        for symbol in US_MARKET_INDEX_SYMBOLS
    )

    aggregate = compose_us_market_indices(
        snapshots=snapshots,
        evaluated_at=NOW,
    )

    assert aggregate.count == 6
    assert aggregate.current_for_requested_session is False
    assert aggregate.is_current is False
    assert aggregate.decision_usable is False
    assert aggregate.items[-1].current_for_requested_session is False
    assert aggregate.items[-1].decision_usable is False


def test_us_market_indices_reader_uses_one_clock_and_six_canonical_truth_reads() -> None:
    calls: list[tuple[str, datetime]] = []

    def read(_db, *, symbol: str, evaluated_at: datetime):
        calls.append((symbol, evaluated_at))
        return _truth(symbol)

    with patch.object(market_indices, "read_us_market_truth_snapshot", side_effect=read):
        aggregate = read_us_market_indices(object(), evaluated_at=NOW)

    assert calls == [(symbol, NOW) for symbol in US_MARKET_INDEX_SYMBOLS]
    assert aggregate.count == 6


def test_us_market_indices_module_has_no_provider_or_write_ownership() -> None:
    source = inspect.getsource(market_indices)

    assert "app.us_market.providers" not in source
    assert "app.us_market.market_data.adapters" not in source
    assert "fetch_" not in source
    assert ".commit(" not in source
    assert ".add(" not in source
    assert "read_us_market_truth_snapshot" in source


def test_market_indices_capability_accepts_us_market_scope() -> None:
    selection = capability_contract.normalize_selection(
        selection={"include": ["market.indices"]},
        output="evidence_only",
        realtime_policy="cache_only",
        payload_level="compact",
        scope_type="market",
        target_market="US",
        question_intent="market_overview",
    )

    assert "market.indices" in selection["required"]
    assert not any(
        item.get("capability") == "market.indices"
        and item.get("reason") == "unsupported_market"
        for item in selection.get("rejected") or []
    )


def test_us_market_index_question_infers_market_indices_capability() -> None:
    request = AiAskRequest(
        question="美股市場指數",
        contract_version="omi.decision.v4",
        target={"type": "market", "market": "US"},
        realtime_policy="cache_only",
    )

    plan = query_plan.build_query_plan(
        payload=request,
        scope_type="market",
        question_intent="market_overview",
        effective_mode="data_only",
        target_market="US",
    )

    assert "indices" in plan.requested_domains
    assert "market.indices" in plan.selected_capabilities


def test_us_market_indices_api_is_a_direct_cache_only_projection() -> None:
    aggregate = compose_us_market_indices(
        snapshots=tuple(_truth(symbol) for symbol in US_MARKET_INDEX_SYMBOLS),
        evaluated_at=NOW,
    )

    db = object()
    with patch.object(
        us_market_router,
        "read_us_market_indices",
        return_value=aggregate,
    ) as read:
        result = us_market_router.get_us_market_indices_api(db=db)

    assert result is aggregate
    assert read.call_count == 1
    assert read.call_args.args == (db,)
    assert read.call_args.kwargs["evaluated_at"].tzinfo is not None
    assert any(route.path == "/indices" for route in us_market_router.router.routes)


def test_us_market_context_projects_backend_owned_index_aggregate() -> None:
    aggregate_payload = {
        "kind": "us_market_indices",
        "market": "US",
        "status": "ready",
        "count": 6,
        "items": [
            {"canonical_symbol": symbol, "label": label}
            for symbol, label in US_MARKET_INDEX_DEFINITIONS
        ],
    }
    representative = {
        "target": {"type": "us_index", "id": "^GSPC", "market": "US"},
        "scope": {"target": {"type": "us_index", "id": "^GSPC"}},
        "data": {"compact": {}},
        "source_refs": [],
    }
    aggregate = SimpleNamespace(
        model_dump=lambda **_kwargs: aggregate_payload,
    )
    request = AiAskRequest(
        question="美股市場指數",
        contract_version="omi.decision.v4",
        target={"type": "market", "market": "US"},
        selection={"include": ["market.indices"]},
        realtime_policy="cache_only",
    )

    with (
        patch.object(
            ask_execution.agentic_tools,
            "read_us_stock_context",
            return_value=representative,
        ),
        patch.object(
            ask_execution,
            "read_us_market_indices",
            return_value=aggregate,
        ) as aggregate_read,
    ):
        tool, result = ask_execution._read_market_context(
            object(),
            request,
            tool_runs=[],
            policy={"can_external_fetch": False},
        )

    assert tool == "omi.read_market_overview"
    assert result["data"]["market"]["indices"] == aggregate_payload
    assert result["data"]["compact"]["market"]["indices"] == aggregate_payload
    assert {"type": "resolved_market_data", "name": "us.market.indices"} in result[
        "source_refs"
    ]
    aggregate_read.assert_called_once()

    selection = capability_contract.normalize_selection(
        selection={"include": ["market.indices"]},
        output="evidence_only",
        realtime_policy="cache_only",
        payload_level="compact",
        scope_type="market",
        target_market="US",
        question_intent="market_overview",
    )
    projected, unavailable = capability_contract.project_selected_data(
        response={"target": result.get("target") or {}, "result": result},
        selection=selection,
    )
    assert "market.indices" not in unavailable
    assert projected["market.indices"]["count"] == 6
    assert [
        item["canonical_symbol"]
        for item in projected["market.indices"]["items"]
    ] == list(US_MARKET_INDEX_SYMBOLS)


def test_us_market_context_skips_indices_outside_bounded_selection() -> None:
    representative = {
        "target": {"type": "us_index", "id": "^GSPC", "market": "US"},
        "scope": {"target": {"type": "us_index", "id": "^GSPC"}},
        "data": {"compact": {}},
        "source_refs": [],
    }
    request = AiAskRequest(
        question="美國總經資料",
        contract_version="omi.decision.v4",
        target={"type": "market", "market": "US"},
        selection={},
        realtime_policy="cache_only",
    )
    policy = {
        "can_external_fetch": False,
        "query_plan": {
            "selected_capabilities": ["macro.snapshot"],
            "optional_selected_capabilities": [],
        },
    }

    with (
        patch.object(
            ask_execution.agentic_tools,
            "read_us_stock_context",
            return_value=representative,
        ),
        patch.object(ask_execution, "read_us_market_indices") as aggregate_read,
    ):
        _, result = ask_execution._read_market_context(
            object(),
            request,
            tool_runs=[],
            policy=policy,
        )

    aggregate_read.assert_not_called()
    assert "market" not in result["data"]
