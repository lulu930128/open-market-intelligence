from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from app.market_data.contracts import (
    AuthorityClass,
    BarFinalization,
    BarObservation,
    BarSeriesCompositionStatus,
    EvidenceFreshness,
    InstrumentKey,
    InstrumentTradability,
    InstrumentType,
    Market,
    MarketSession,
    ObservationState,
    Quantity,
    QuantityUnit,
    QuoteObservation,
    ResolvedEvidenceStatus,
    SourceLineage,
    TradingStatusObservation,
)
from app.market_data.integration_contracts import (
    BarCapabilityRequest,
    BarSeriesResolutionMode,
    DataRequirementV2,
    FreshnessRequirement,
    InstrumentTarget,
    QualityRequirement,
    RequestBounds,
    SnapshotCapabilityRequest,
)
from app.market_data.policies import (
    AcquisitionResult,
    DataPurpose,
    DataRequirement,
    PUBLIC_REALTIME_POLICIES,
    RealtimePolicy,
    allows_external_acquisition,
    parse_realtime_policy,
    requirement_allows_external_acquisition,
)
from app.market_data.resolution import (
    BarSeriesCandidate,
    MAX_CANDIDATE_SUMMARIES,
    ResolutionCandidate,
    resolve_bar_series,
    resolve_quote,
    resolve_trading_status,
)


NOW = datetime(2026, 8, 19, 9, 5, tzinfo=timezone(timedelta(hours=8)))


def _instrument() -> InstrumentKey:
    return InstrumentKey(
        market=Market.TW,
        symbol="2330",
        instrument_type=InstrumentType.STOCK,
        venue="TWSE",
    )


def _lineage(
    provider: str,
    *,
    minutes_old: int = 0,
    authority: AuthorityClass = AuthorityClass.BROKER,
    cache_hit: bool = False,
) -> SourceLineage:
    return SourceLineage(
        provider=provider,
        source=f"{provider}.quote",
        authority=authority,
        event_at=NOW - timedelta(minutes=minutes_old),
        received_at=NOW,
        cache_hit=cache_hit,
    )


def _quote(
    provider: str,
    price: str,
    *,
    minutes_old: int = 0,
    authority: AuthorityClass = AuthorityClass.BROKER,
    cache_hit: bool = False,
) -> QuoteObservation:
    return QuoteObservation(
        instrument=_instrument(),
        lineage=_lineage(
            provider,
            minutes_old=minutes_old,
            authority=authority,
            cache_hit=cache_hit,
        ),
        last_trade_price=Decimal(price),
    )


def _quality_requirement(*, allow_partial: bool = False) -> DataRequirementV2:
    return DataRequirementV2(
        target=InstrumentTarget(instrument=_instrument()),
        request=SnapshotCapabilityRequest(
            capability_id="quote.snapshot",
            required_fields=("last_trade_price",),
        ),
        purpose=DataPurpose.RESEARCH,
        realtime_policy=RealtimePolicy.PREFER_LIVE,
        session=MarketSession.CONTINUOUS,
        requested_at=NOW,
        freshness=FreshnessRequirement(max_age_seconds=300),
        quality=QualityRequirement(allow_partial=allow_partial),
        bounds=RequestBounds(max_provider_attempts=1, max_external_calls=1),
    )


def _bar_requirement(
    *,
    series_resolution: BarSeriesResolutionMode,
    end_at: datetime,
    max_bars: int = 4,
) -> DataRequirementV2:
    return DataRequirementV2(
        target=InstrumentTarget(instrument=_instrument()),
        request=BarCapabilityRequest(
            capability_id="bars.ohlcv.daily",
            interval="1d",
            start_at=NOW,
            end_at=end_at,
            max_bars=max_bars,
            completed_only=True,
            price_basis="raw",
            series_resolution=series_resolution,
        ),
        purpose=DataPurpose.RESEARCH,
        realtime_policy=RealtimePolicy.COMPLETED_SESSION,
        session=MarketSession.CLOSED,
        requested_at=end_at + timedelta(hours=1),
        freshness=FreshnessRequirement(max_age_seconds=86_400),
        quality=QualityRequirement(
            required_fields=("open_price", "high_price", "low_price", "close_price"),
            minimum_authority=AuthorityClass.EXCHANGE,
        ),
        bounds=RequestBounds(
            max_provider_attempts=0,
            max_external_calls=0,
            max_subscriptions=0,
            max_rows=max_bars,
        ),
    )


def _daily_bar(provider: str, day: int, close: str) -> BarObservation:
    start = NOW + timedelta(days=day)
    return BarObservation(
        instrument=_instrument(),
        lineage=_lineage(provider, authority=AuthorityClass.EXCHANGE, cache_hit=True),
        interval="1d",
        start_at=start,
        end_at=start + timedelta(hours=4, minutes=30),
        open_price=Decimal(close) - 1,
        high_price=Decimal(close) + 1,
        low_price=Decimal(close) - 2,
        close_price=Decimal(close),
        volume=Quantity(value=1000, unit=QuantityUnit.SHARE),
        volume_status="observed",
        price_basis="raw",
        finalization=BarFinalization.FINAL,
    )


def _current_minute_bar(
    provider: str,
    minute: int,
    close: str,
) -> BarObservation:
    start = NOW.replace(hour=9, minute=minute, second=0, microsecond=0)
    return BarObservation(
        instrument=_instrument(),
        lineage=_lineage(provider, cache_hit=True),
        interval="1m",
        start_at=start,
        end_at=start + timedelta(minutes=1),
        open_price=Decimal(close) - 1,
        high_price=Decimal(close) + 1,
        low_price=Decimal(close) - 2,
        close_price=Decimal(close),
        volume=Quantity(value=1000, unit=QuantityUnit.SHARE),
        volume_status="observed",
        price_basis="raw",
        finalization=BarFinalization.FINAL,
    )


def _current_bar_requirement() -> DataRequirementV2:
    return DataRequirementV2(
        target=InstrumentTarget(instrument=_instrument()),
        request=BarCapabilityRequest(
            capability_id="bars.ohlcv.intraday",
            interval="1m",
            start_at=NOW.replace(hour=9, minute=0, second=0, microsecond=0),
            end_at=NOW + timedelta(minutes=1),
            max_bars=10,
            completed_only=False,
            price_basis="raw",
            series_resolution=BarSeriesResolutionMode.COMPOSE_BY_TIMESTAMP,
        ),
        purpose=DataPurpose.VIEWER,
        realtime_policy=RealtimePolicy.CACHE_ONLY,
        session=MarketSession.CONTINUOUS,
        requested_at=NOW,
        freshness=FreshnessRequirement(max_age_seconds=300),
        quality=QualityRequirement(
            required_fields=("open_price", "high_price", "low_price", "close_price"),
        ),
        bounds=RequestBounds(max_rows=10),
    )


def test_public_policy_vocabulary_remains_backward_compatible() -> None:
    assert PUBLIC_REALTIME_POLICIES == {
        "cache_only",
        "prefer_live",
        "require_live",
    }
    with pytest.raises(ValueError, match="internal"):
        parse_realtime_policy("completed_session")
    assert (
        parse_realtime_policy("completed_session", allow_internal=True)
        is RealtimePolicy.COMPLETED_SESSION
    )
    assert allows_external_acquisition("cache_only") is False
    assert allows_external_acquisition("completed_session") is False


def test_cache_only_selects_cache_and_rejects_external_candidate() -> None:
    result = resolve_quote(
        [
            ResolutionCandidate(
                _quote("kgi", "100"), EvidenceFreshness.LIVE, provider_priority=0
            ),
            ResolutionCandidate(
                _quote(
                    "sqlite",
                    "99",
                    authority=AuthorityClass.CACHE,
                    cache_hit=True,
                ),
                EvidenceFreshness.FRESH,
                provider_priority=10,
            ),
        ],
        policy="cache_only",
        now=NOW,
        max_age=timedelta(minutes=5),
    )
    assert result.quote is not None
    assert result.quote.lineage.provider == "sqlite"
    assert result.candidates[0].eligible is False
    assert result.candidates[0].reason_code == "NOT_CACHE_EVIDENCE"


def test_quality_requirement_rejects_missing_field_before_ranking() -> None:
    missing_price = _quote("kgi", "100").model_copy(
        update={"last_trade_price": None}
    )
    result = resolve_quote(
        [ResolutionCandidate(missing_price, EvidenceFreshness.LIVE)],
        policy=RealtimePolicy.PREFER_LIVE,
        now=NOW,
        max_age=timedelta(minutes=5),
        requirement=_quality_requirement(),
    )

    assert result.quote is None
    assert result.health.status is ResolvedEvidenceStatus.MISSING
    assert result.health.missing_fields == ("last_trade_price",)
    assert result.candidates[0].reason_code == "QUALITY_REQUIRED_FIELDS_MISSING"


def test_partial_quality_requires_allowance_and_remains_facts_only() -> None:
    partial = _quote("kgi", "100").model_copy(
        update={"state": ObservationState.PARTIAL}
    )
    rejected = resolve_quote(
        [ResolutionCandidate(partial, EvidenceFreshness.LIVE)],
        policy=RealtimePolicy.PREFER_LIVE,
        now=NOW,
        max_age=timedelta(minutes=5),
        requirement=_quality_requirement(allow_partial=False),
    )
    assert rejected.quote is None
    assert rejected.candidates[0].reason_code == "QUALITY_PARTIAL_NOT_ALLOWED"

    allowed = resolve_quote(
        [ResolutionCandidate(partial, EvidenceFreshness.LIVE)],
        policy=RealtimePolicy.PREFER_LIVE,
        now=NOW,
        max_age=timedelta(minutes=5),
        requirement=_quality_requirement(allow_partial=True),
    )
    assert allowed.quote is partial
    assert allowed.health.status is ResolvedEvidenceStatus.PARTIAL
    assert allowed.health.facts_usable is True
    assert allowed.health.research_usable is False
    assert allowed.candidates[0].reason_code == "QUALITY_PARTIAL_ALLOWED"


def test_require_live_fails_closed_when_only_fresh_cache_exists() -> None:
    result = resolve_quote(
        [
            ResolutionCandidate(
                _quote("cache", "99", authority=AuthorityClass.CACHE, cache_hit=True),
                EvidenceFreshness.FRESH,
            )
        ],
        policy="require_live",
        now=NOW,
        max_age=timedelta(minutes=5),
    )
    assert result.quote is None
    assert result.health.status is ResolvedEvidenceStatus.POLICY_UNSATISFIED
    assert result.health.facts_usable is False
    assert result.health.research_usable is False
    assert result.candidates[0].reason_code == "LIVE_REQUIRED"


def test_prefer_live_selects_fresh_fallback_over_stale_primary() -> None:
    result = resolve_quote(
        [
            ResolutionCandidate(
                _quote("kgi", "100", minutes_old=20),
                EvidenceFreshness.LIVE,
                provider_priority=0,
            ),
            ResolutionCandidate(
                _quote("mis", "99"),
                EvidenceFreshness.FRESH,
                provider_priority=10,
            ),
        ],
        policy="prefer_live",
        now=NOW,
        max_age=timedelta(minutes=5),
    )
    assert result.quote is not None
    assert result.quote.lineage.provider == "mis"
    assert result.health.status is ResolvedEvidenceStatus.FALLBACK
    assert result.health.fallback_used is True
    assert result.health.facts_usable is True
    assert result.health.research_usable is True
    assert result.candidates[0].freshness is EvidenceFreshness.STALE


def test_future_timestamp_is_rejected_instead_of_treated_as_fresh() -> None:
    future = _quote("kgi", "100").model_copy(
        update={
            "lineage": SourceLineage(
                provider="kgi",
                source="kgi.quote",
                authority=AuthorityClass.BROKER,
                event_at=NOW + timedelta(minutes=10),
            )
        }
    )
    result = resolve_quote(
        [ResolutionCandidate(future, EvidenceFreshness.LIVE)],
        policy="prefer_live",
        now=NOW,
        max_age=timedelta(minutes=5),
    )
    assert result.quote is None
    assert result.candidates[0].reason_code == "FUTURE_TIMESTAMP"


def test_completed_session_only_accepts_completed_evidence() -> None:
    candidates = [
        ResolutionCandidate(
            _quote("kgi", "100"),
            EvidenceFreshness.FRESH,
            session=MarketSession.CONTINUOUS,
        ),
        ResolutionCandidate(
            _quote("cache", "99", authority=AuthorityClass.CACHE, cache_hit=True),
            EvidenceFreshness.FRESH,
            provider_priority=10,
            session=MarketSession.CLOSED,
        ),
    ]
    result = resolve_quote(
        candidates,
        policy=RealtimePolicy.COMPLETED_SESSION,
        now=NOW,
        max_age=timedelta(minutes=5),
    )
    assert result.quote is not None
    assert result.quote.lineage.provider == "cache"
    assert result.candidates[0].reason_code == "SESSION_NOT_COMPLETED"
    assert result.candidates[0].session is MarketSession.CONTINUOUS
    assert result.candidates[1].session is MarketSession.CLOSED
    assert result.health.selected_session is MarketSession.CLOSED


def test_official_exchange_trading_status_wins_broker_hint() -> None:
    broker = TradingStatusObservation(
        instrument=_instrument(),
        lineage=_lineage("kgi"),
        status=InstrumentTradability.SUSPENDED,
        official=False,
    )
    exchange = TradingStatusObservation(
        instrument=_instrument(),
        lineage=_lineage("twse", authority=AuthorityClass.EXCHANGE),
        status=InstrumentTradability.TRADABLE,
        official=True,
    )
    result = resolve_trading_status(
        [
            ResolutionCandidate(broker, EvidenceFreshness.LIVE, provider_priority=0),
            ResolutionCandidate(exchange, EvidenceFreshness.FRESH, provider_priority=10),
        ],
        policy="prefer_live",
        now=NOW,
        max_age=timedelta(minutes=5),
    )
    assert result.trading_status is not None
    assert result.trading_status.official is True
    assert result.trading_status.lineage.provider == "twse"
    assert result.health.research_usable is True
    assert result.health.selection_reason == "PREFER_LIVE_OFFICIAL_CONFLICT"
    assert "conflicts" in result.health.limitations[0]


def test_stale_official_trading_status_cannot_override_live_broker_conflict() -> None:
    broker = TradingStatusObservation(
        instrument=_instrument(),
        lineage=_lineage("kgi"),
        status=InstrumentTradability.SUSPENDED,
        official=False,
    )
    stale_exchange = TradingStatusObservation(
        instrument=_instrument(),
        lineage=_lineage(
            "twse",
            minutes_old=20,
            authority=AuthorityClass.EXCHANGE,
        ),
        status=InstrumentTradability.TRADABLE,
        official=True,
    )
    result = resolve_trading_status(
        [
            ResolutionCandidate(broker, EvidenceFreshness.LIVE, provider_priority=0),
            ResolutionCandidate(
                stale_exchange,
                EvidenceFreshness.FRESH,
                provider_priority=10,
            ),
        ],
        policy="prefer_live",
        now=NOW,
        max_age=timedelta(minutes=5),
    )
    assert result.trading_status is not None
    assert result.trading_status.lineage.provider == "kgi"
    assert result.trading_status.status is InstrumentTradability.SUSPENDED
    assert result.health.status is ResolvedEvidenceStatus.PARTIAL
    assert result.health.facts_usable is True
    assert result.health.research_usable is False
    assert result.health.selection_reason == "PREFER_LIVE_PARTIAL_CONFLICT"
    assert result.candidates[1].freshness is EvidenceFreshness.STALE
    assert "authoritative" in result.health.limitations[0]


def test_current_broker_wins_stale_official_when_statuses_agree() -> None:
    broker = TradingStatusObservation(
        instrument=_instrument(),
        lineage=_lineage("kgi"),
        status=InstrumentTradability.TRADABLE,
        official=False,
    )
    stale_exchange = TradingStatusObservation(
        instrument=_instrument(),
        lineage=_lineage(
            "twse",
            minutes_old=20,
            authority=AuthorityClass.EXCHANGE,
        ),
        status=InstrumentTradability.TRADABLE,
        official=True,
    )
    result = resolve_trading_status(
        [
            ResolutionCandidate(broker, EvidenceFreshness.LIVE, provider_priority=0),
            ResolutionCandidate(
                stale_exchange,
                EvidenceFreshness.FRESH,
                provider_priority=10,
            ),
        ],
        policy="prefer_live",
        now=NOW,
        max_age=timedelta(minutes=5),
    )
    assert result.trading_status is not None
    assert result.trading_status.lineage.provider == "kgi"
    assert result.health.status is ResolvedEvidenceStatus.SELECTED
    assert result.health.research_usable is True
    assert result.health.limitations == ()


def test_only_stale_official_trading_status_remains_stale() -> None:
    stale_exchange = TradingStatusObservation(
        instrument=_instrument(),
        lineage=_lineage(
            "twse",
            minutes_old=20,
            authority=AuthorityClass.EXCHANGE,
        ),
        status=InstrumentTradability.TRADABLE,
        official=True,
    )
    result = resolve_trading_status(
        [ResolutionCandidate(stale_exchange, EvidenceFreshness.FRESH)],
        policy="prefer_live",
        now=NOW,
        max_age=timedelta(minutes=5),
    )
    assert result.trading_status is not None
    assert result.health.status is ResolvedEvidenceStatus.STALE
    assert result.health.facts_usable is True
    assert result.health.research_usable is False


def test_completed_bar_series_requires_final_or_corrected_bars() -> None:
    def bar(finalization: BarFinalization, minute: int) -> BarObservation:
        start = NOW + timedelta(minutes=minute)
        return BarObservation(
            instrument=_instrument(),
            lineage=_lineage("cache", authority=AuthorityClass.CACHE, cache_hit=True),
            interval="1m",
            start_at=start,
            end_at=start + timedelta(minutes=1),
            open_price=100,
            high_price=102,
            low_price=99,
            close_price=101,
            volume=Quantity(value=1000, unit=QuantityUnit.SHARE),
            finalization=finalization,
        )

    result = resolve_bar_series(
        [
            BarSeriesCandidate(
                bars=(bar(BarFinalization.PROVISIONAL, 0),),
                freshness=EvidenceFreshness.FRESH,
                session=MarketSession.CLOSED,
            ),
            BarSeriesCandidate(
                bars=(bar(BarFinalization.FINAL, 1),),
                freshness=EvidenceFreshness.FRESH,
                provider_priority=10,
                session=MarketSession.CLOSED,
            ),
        ],
        policy=RealtimePolicy.COMPLETED_SESSION,
        now=NOW + timedelta(minutes=3),
        max_age=timedelta(minutes=1),
    )
    assert len(result.bars) == 1
    assert result.bars[0].finalization is BarFinalization.FINAL

    with pytest.raises(ValueError, match="strictly ordered"):
        BarSeriesCandidate(
            bars=(bar(BarFinalization.FINAL, 2), bar(BarFinalization.FINAL, 1)),
            freshness=EvidenceFreshness.FRESH,
            session=MarketSession.CLOSED,
        )

    first = bar(BarFinalization.FINAL, 3)
    mixed = bar(BarFinalization.FINAL, 4).model_copy(
        update={"lineage": _lineage("other", authority=AuthorityClass.CACHE, cache_hit=True)}
    )
    with pytest.raises(ValueError, match="one provider lineage"):
        BarSeriesCandidate(
            bars=(first, mixed),
            freshness=EvidenceFreshness.FRESH,
            session=MarketSession.CLOSED,
        )

    mixed_source = bar(BarFinalization.FINAL, 4).model_copy(
        update={
            "lineage": first.lineage.model_copy(
                update={"source": "cache.alternate"}
            )
        }
    )
    with pytest.raises(ValueError, match="one source lineage"):
        BarSeriesCandidate(
            bars=(first, mixed_source),
            freshness=EvidenceFreshness.FRESH,
            session=MarketSession.CLOSED,
        )

    mixed_authority = bar(BarFinalization.FINAL, 4).model_copy(
        update={
            "lineage": first.lineage.model_copy(
                update={"authority": AuthorityClass.EXCHANGE}
            )
        }
    )
    with pytest.raises(ValueError, match="one authority lineage"):
        BarSeriesCandidate(
            bars=(first, mixed_authority),
            freshness=EvidenceFreshness.FRESH,
            session=MarketSession.CLOSED,
        )


def test_default_bar_resolution_keeps_whole_series_selection() -> None:
    primary = BarSeriesCandidate(
        bars=(_daily_bar("priority", 2, "202"), _daily_bar("priority", 3, "203")),
        freshness=EvidenceFreshness.FRESH,
        provider_priority=5,
        session=MarketSession.CLOSED,
    )
    history = BarSeriesCandidate(
        bars=tuple(_daily_bar("history", day, str(100 + day)) for day in range(4)),
        freshness=EvidenceFreshness.FRESH,
        provider_priority=10,
        session=MarketSession.CLOSED,
    )

    result = resolve_bar_series(
        [primary, history],
        policy=RealtimePolicy.COMPLETED_SESSION,
        now=NOW + timedelta(days=4),
        max_age=timedelta(days=2),
        requirement=_bar_requirement(
            series_resolution=BarSeriesResolutionMode.SINGLE_CANDIDATE,
            end_at=primary.bars[-1].end_at,
        ),
    )

    assert result.bars == primary.bars
    assert result.composition.status is BarSeriesCompositionStatus.NOT_APPLIED


def test_completed_bar_composition_fills_history_and_reports_conflicts() -> None:
    priority = BarSeriesCandidate(
        bars=(_daily_bar("priority", 2, "202"), _daily_bar("priority", 3, "203")),
        freshness=EvidenceFreshness.FRESH,
        provider_priority=5,
        session=MarketSession.CLOSED,
    )
    history = BarSeriesCandidate(
        bars=tuple(_daily_bar("history", day, str(100 + day)) for day in range(4)),
        freshness=EvidenceFreshness.STALE,
        provider_priority=10,
        session=MarketSession.CLOSED,
    )

    result = resolve_bar_series(
        [priority, history],
        policy=RealtimePolicy.COMPLETED_SESSION,
        now=NOW + timedelta(days=4),
        max_age=timedelta(days=2),
        requirement=_bar_requirement(
            series_resolution=BarSeriesResolutionMode.COMPOSE_BY_TIMESTAMP,
            end_at=priority.bars[-1].end_at,
        ),
    )

    assert [bar.close_price for bar in result.bars] == [
        Decimal("100"),
        Decimal("101"),
        Decimal("202"),
        Decimal("203"),
    ]
    assert [bar.lineage.provider for bar in result.bars] == [
        "history",
        "history",
        "priority",
        "priority",
    ]
    assert result.health.selected_provider is None
    assert result.health.selected_source is None
    assert result.composition.status is BarSeriesCompositionStatus.COMPOSED_WITH_CONFLICTS
    assert result.composition.contributing_providers == ("priority", "history")
    assert result.composition.filled_bucket_count == 2
    assert result.composition.conflict_bucket_count == 2
    assert "BAR_SERIES_COMPOSED_FROM_MULTIPLE_CANDIDATES" in result.composition.limitations
    assert "BAR_SERIES_SAME_TIMESTAMP_CONFLICT_RESOLVED" in result.composition.limitations


def test_current_cache_composition_keeps_baseline_and_overlays_closed_live_tail() -> None:
    baseline = BarSeriesCandidate(
        bars=tuple(
            _current_minute_bar("nstock", minute, str(100 + minute))
            for minute in range(5)
        ),
        freshness=EvidenceFreshness.FRESH,
        provider_priority=20,
        session=MarketSession.CONTINUOUS,
    )
    live_tail = BarSeriesCandidate(
        bars=tuple(
            _current_minute_bar("kgi", minute, str(200 + minute))
            for minute in range(3, 6)
        ),
        freshness=EvidenceFreshness.FRESH,
        provider_priority=5,
        session=MarketSession.CONTINUOUS,
    )

    result = resolve_bar_series(
        [live_tail, baseline],
        policy=RealtimePolicy.CACHE_ONLY,
        now=NOW,
        max_age=timedelta(minutes=5),
        requirement=_current_bar_requirement(),
    )

    assert [bar.start_at.minute for bar in result.bars] == [0, 1, 2, 3, 4]
    assert [bar.lineage.provider for bar in result.bars] == [
        "nstock",
        "nstock",
        "nstock",
        "kgi",
        "kgi",
    ]
    assert result.health.selected_provider is None
    assert result.composition.filled_bucket_count == 3
    assert result.composition.conflict_bucket_count == 2
    assert result.health.selected_session is MarketSession.CONTINUOUS


def test_current_composition_keeps_valid_prefix_when_latest_bar_is_hard_invalid() -> None:
    valid = tuple(
        _current_minute_bar("provider", minute, str(100 + minute))
        for minute in range(4)
    )
    latest = _current_minute_bar("provider", 4, "104")
    latest = latest.model_copy(
        update={
            "lineage": latest.lineage.model_copy(
                update={"event_at": NOW + timedelta(minutes=10)}
            )
        }
    )
    candidate = BarSeriesCandidate(
        bars=(*valid, latest),
        freshness=EvidenceFreshness.FRESH,
        provider_priority=5,
        session=MarketSession.CONTINUOUS,
    )

    result = resolve_bar_series(
        [candidate],
        policy=RealtimePolicy.CACHE_ONLY,
        now=NOW,
        max_age=timedelta(minutes=5),
        requirement=_current_bar_requirement(),
    )

    assert [bar.start_at.minute for bar in result.bars] == [0, 1, 2, 3]
    assert result.candidates[0].eligible is True
    assert result.candidates[0].reason_code == "BAR_PREFIX_PARTIALLY_ELIGIBLE"


def test_candidate_summaries_are_bounded_and_never_include_raw_payloads() -> None:
    candidates = [
        ResolutionCandidate(
            _quote(f"provider-{index}", str(100 + index)),
            EvidenceFreshness.FRESH,
            provider_priority=index,
        )
        for index in range(MAX_CANDIDATE_SUMMARIES + 4)
    ]
    result = resolve_quote(
        candidates,
        policy="prefer_live",
        now=NOW,
        max_age=timedelta(minutes=5),
    )
    assert len(result.candidates) == MAX_CANDIDATE_SUMMARIES
    candidate_payload = [candidate.model_dump() for candidate in result.candidates]
    assert all("raw_payload" not in candidate for candidate in candidate_payload)


def test_resolution_module_has_no_io_or_consumer_imports() -> None:
    module_path = Path(__file__).parents[1] / "app" / "market_data" / "resolution.py"
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imported_modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)
    forbidden_prefixes = (
        "requests",
        "httpx",
        "sqlalchemy",
        "app.us_market",
        "app.ai",
        "app.db",
        "app.frontend",
    )
    assert "app.market" not in imported_modules
    assert not any(module.startswith("app.market.") for module in imported_modules)
    assert not any(
        module.startswith(forbidden_prefixes) for module in imported_modules
    )


def test_acquisition_port_contract_keeps_cache_and_completed_modes_side_effect_free() -> None:
    for policy in (RealtimePolicy.CACHE_ONLY, RealtimePolicy.COMPLETED_SESSION):
        requirement = DataRequirement(
            instrument=_instrument(),
            capability_id="quote.snapshot",
            realtime_policy=policy,
            purpose=DataPurpose.RESEARCH,
            session=MarketSession.CLOSED,
            requested_at=NOW,
            max_age_seconds=300,
        )
        assert requirement_allows_external_acquisition(requirement) is False
    empty = AcquisitionResult()
    assert empty.external_calls == 0
    assert empty.subscriptions_created == 0
