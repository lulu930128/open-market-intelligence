from __future__ import annotations

import base64
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import inspect
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    DataQualityCheck,
    RawFetchResult,
    SourceRegistry,
    StockMaster,
    TaiwanStockQuoteSnapshot,
)
from app.market import intraday
from app.market.providers.tw_public_quote import (
    TWSE_MIS_PUBLIC_QUOTE_DESCRIPTOR,
    parse_twse_mis_quote_payload,
    quote_observation_from_twse_mis,
)
from app.market.public_quote_acquisition import (
    TaiwanPublicQuoteAcquisitionExecutor,
)
from app.market.public_quote_platform import (
    acquire_taiwan_public_last_trade_quote,
    project_taiwan_public_last_trade_quote,
    read_taiwan_public_last_trade_quote,
)
from app.market.public_quote_repository import TaiwanPublicQuoteRepository
from app.market.trading_calendar import TAIWAN_TZ
from app.market_data.contracts import (
    DatasetHealthStatus,
    EvidenceFreshness,
    InstrumentKey,
    InstrumentType,
    Market,
    MarketSession,
    ObservationState,
    ResolvedEvidenceStatus,
    TradeObservationState,
)
from app.market_data.policies import RealtimePolicy
from app.routers import tw_public_quotes


FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "tw_market_data"
    / "twse_mis_public_quote_actual_20260825.json"
)


class FakeResponse:
    def __init__(self, raw_text: str, *, status_code: int = 200) -> None:
        self.text = raw_text
        self.status_code = status_code
        self.headers = {"content-type": "application/json;charset=UTF-8"}
        self.url = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = Session(engine)
    session.add_all(
        [
            StockMaster(
                stock_id="2330",
                stock_name="台積電",
                market="TWSE",
                instrument_type="stock",
            ),
            StockMaster(
                stock_id="6173",
                stock_name="信昌電",
                market="TPEX",
                instrument_type="stock",
            ),
        ]
    )
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _records() -> dict[str, dict]:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return {item["stock_id"]: item for item in payload["records"]}


def _raw(record: dict) -> str:
    raw = base64.b64decode(record["raw_text_base64"]).decode("utf-8")
    assert hashlib.sha256(raw.encode("utf-8")).hexdigest() == record["sha256"]
    return raw


def _instrument(record: dict) -> InstrumentKey:
    return InstrumentKey(
        market=Market.TW,
        symbol=record["stock_id"],
        instrument_type=InstrumentType.STOCK,
        venue=record["venue"],
    )


def _executor(raw_text: str, received_at: datetime) -> TaiwanPublicQuoteAcquisitionExecutor:
    return TaiwanPublicQuoteAcquisitionExecutor(
        fetchers={
            TWSE_MIS_PUBLIC_QUOTE_DESCRIPTOR.resource_id: (
                lambda _route, _instrument: FakeResponse(raw_text)
            )
        },
        clock=lambda: received_at,
    )


def test_actual_twse_and_tpex_payloads_preserve_trade_vs_indicative_semantics() -> None:
    records = _records()
    twse = records["2330"]
    twse_received = datetime.fromisoformat(twse["received_at"])
    twse_message = parse_twse_mis_quote_payload(
        _raw(twse),
        target_symbol="2330",
    )
    twse_quote = quote_observation_from_twse_mis(
        instrument=_instrument(twse),
        message=twse_message,
        session=MarketSession.POST_CLOSE,
        received_at=twse_received,
        fetched_at=twse_received,
        content_hash=twse["sha256"],
    )
    assert twse_quote.last_trade_price == Decimal("2400.0000")
    assert twse_quote.trade_state is TradeObservationState.TRADE_OBSERVED
    assert twse_quote.last_trade_quantity is not None
    assert twse_quote.last_trade_quantity.original_value == Decimal("2997")
    assert twse_quote.cumulative_quantity is not None
    assert twse_quote.cumulative_quantity.value == Decimal("12789000")
    assert twse_quote.lineage.event_at == datetime.fromisoformat(
        twse["event_time"]
    )
    assert twse_quote.lineage.received_at == twse_received
    assert twse_quote.lineage.content_hash == twse["sha256"]

    tpex = records["6173"]
    tpex_received = datetime.fromisoformat(tpex["received_at"])
    tpex_quote = quote_observation_from_twse_mis(
        instrument=_instrument(tpex),
        message=parse_twse_mis_quote_payload(
            _raw(tpex),
            target_symbol="6173",
        ),
        session=MarketSession.PRE_OPEN,
        received_at=tpex_received,
        fetched_at=tpex_received,
        content_hash=tpex["sha256"],
    )
    assert tpex_quote.state is ObservationState.INDICATIVE
    assert tpex_quote.trade_state is TradeObservationState.INDICATIVE_OBSERVED
    assert tpex_quote.last_trade_price is None
    assert tpex_quote.previous_close == Decimal("221.0000")
    assert tpex_quote.cumulative_quantity is not None
    assert tpex_quote.cumulative_quantity.value == 0


def test_actual_quote_acquires_persists_rereads_and_skips_second_prefer_live_call(
    db: Session,
) -> None:
    record = _records()["2330"]
    raw_text = _raw(record)
    requested_at = datetime(2026, 8, 25, 13, 29, 55, tzinfo=TAIWAN_TZ)
    received_at = datetime(2026, 8, 25, 5, 30, 1, tzinfo=timezone.utc)

    first = acquire_taiwan_public_last_trade_quote(
        db,
        stock_id="2330",
        policy=RealtimePolicy.PREFER_LIVE,
        requested_at=requested_at,
        acquisition=_executor(raw_text, received_at),
    )

    assert first.acquisition.external_calls == 1
    assert first.persistence.committed
    assert first.resolved.health.status is ResolvedEvidenceStatus.SELECTED
    assert first.resolved.quote is not None
    assert first.resolved.quote.last_trade_price == Decimal("2400.0000")
    assert first.resolved.quote.lineage.cache_hit
    assert first.resolved.quote.lineage.raw_receipt_id == "raw_fetch_result:1"
    assert db.query(SourceRegistry).count() == 1
    assert db.query(RawFetchResult).count() == 1
    assert db.query(TaiwanStockQuoteSnapshot).count() == 1
    assert db.query(DataQualityCheck).count() == 1
    row = db.query(TaiwanStockQuoteSnapshot).one()
    assert row.source_id is not None
    assert row.raw_result_id is not None
    assert row.received_at is not None
    assert row.market_session == "closing_auction"
    assert row.observation_state == "available"
    assert row.trade_state == "trade_observed"

    projection = project_taiwan_public_last_trade_quote(first)
    assert projection["contract_version"] == "omi.market.tw_public_quote_projection.v1"
    assert projection["last_trade_price"] == 2400.0
    assert projection["actual_trade_occurred"] is True
    assert projection["last_trade_is_current_session"] is True
    assert projection["cumulative_volume_lots"] == 12789
    assert projection["last_trade_volume_lots"] == 2997
    assert projection["depth_available"] is False
    assert projection["freshness"]["status"] == "live"
    assert projection["resolved_health"]["selected_provider"] == "twse_mis"

    calls = 0

    def forbidden_fetch(_route, _instrument):
        nonlocal calls
        calls += 1
        raise AssertionError("fresh persisted quote must satisfy prefer_live")

    second = acquire_taiwan_public_last_trade_quote(
        db,
        stock_id="2330",
        policy=RealtimePolicy.PREFER_LIVE,
        requested_at=datetime(2026, 8, 25, 13, 29, 56, tzinfo=TAIWAN_TZ),
        acquisition=TaiwanPublicQuoteAcquisitionExecutor(
            fetchers={
                TWSE_MIS_PUBLIC_QUOTE_DESCRIPTOR.resource_id: forbidden_fetch
            }
        ),
    )
    assert calls == 0
    assert not second.acquisition.attempted
    assert second.acquisition.limitations == ("PRE_RESOLUTION_SATISFIED",)
    assert db.query(RawFetchResult).count() == 1


def test_intraday_projection_keeps_bars_and_resolved_current_trade_separate(
    db: Session,
) -> None:
    record = _records()["2330"]
    quote_result = acquire_taiwan_public_last_trade_quote(
        db,
        stock_id="2330",
        policy=RealtimePolicy.PREFER_LIVE,
        requested_at=datetime(2026, 8, 25, 13, 29, 55, tzinfo=TAIWAN_TZ),
        acquisition=_executor(
            _raw(record),
            datetime(2026, 8, 25, 5, 30, 1, tzinfo=timezone.utc),
        ),
    )
    original_points = [
        {
            "time": "2026-08-25T13:29:00+08:00",
            "price": 2395.0,
            "volume": 1000,
        }
    ]
    projected = intraday._apply_platform_quote_contract(
        {
            "stock_id": "2330",
            "symbol": "2330.TW",
            "source": "nstock_minute_stock_data",
            "point_count": 1,
            "points": [dict(original_points[0])],
        },
        quote_result,
    )

    assert projected["points"] == original_points
    assert projected["point_count"] == 1
    assert projected["provider"] == "nstock"
    assert projected["price_provider"] == "nstock"
    assert projected["volume_provider"] == "nstock"
    assert projected["current_trade_available"] is True
    assert projected["latest_actual_trade_price"] == 2400.0
    assert projected["current_price_applied_to_history"] is False
    assert projected["lag_seconds"] == 60.0
    assert [
        item["domain"] for item in projected["source_components"]
    ] == ["price_bars", "bar_volume", "current_trade"]
    assert projected["canonical_observation"]["last_trade_price"] == "2400.0"
    assert projected["resolution"]["health"]["status"] == "selected"
    assert projected["acquisition_policy"] == "prefer_live"


def test_intraday_production_path_no_longer_uses_mis_quote_as_bar_fallback() -> None:
    source = inspect.getsource(intraday._load_intraday_trend_uncached)
    attach_source = inspect.getsource(intraday._attach_cached_public_quote)
    assert "_attach_cached_public_quote" in source
    assert "_fetch_mis_message" not in source
    assert "_fetch_mis_snapshot" not in source
    assert "_apply_mis_volume_adjustment" not in source
    assert "read_taiwan_public_last_trade_quote" in attach_source
    assert "acquire_taiwan_public_last_trade_quote" not in attach_source


def test_cache_only_read_never_acquires_and_reports_stale_truthfully(
    db: Session,
) -> None:
    record = _records()["2330"]
    acquire_taiwan_public_last_trade_quote(
        db,
        stock_id="2330",
        policy=RealtimePolicy.PREFER_LIVE,
        requested_at=datetime(2026, 8, 25, 13, 29, 55, tzinfo=TAIWAN_TZ),
        acquisition=_executor(
            _raw(record),
            datetime(2026, 8, 25, 5, 30, 1, tzinfo=timezone.utc),
        ),
    )

    result = read_taiwan_public_last_trade_quote(
        db,
        stock_id="2330",
        requested_at=datetime(2026, 8, 25, 14, 0, tzinfo=TAIWAN_TZ),
    )
    assert result.requirement.realtime_policy is RealtimePolicy.CACHE_ONLY
    assert result.requirement.bounds.max_external_calls == 0
    assert not result.acquisition.attempted
    assert result.resolved.health.status is ResolvedEvidenceStatus.STALE
    assert result.resolved.quote is not None
    assert result.dataset_health is not None
    assert result.dataset_health.status is DatasetHealthStatus.STALE


def test_require_live_post_close_is_zero_io_and_policy_unsatisfied(
    db: Session,
) -> None:
    calls = 0

    def forbidden_fetch(_route, _instrument):
        nonlocal calls
        calls += 1
        raise AssertionError("post-close require_live must not call MIS")

    result = acquire_taiwan_public_last_trade_quote(
        db,
        stock_id="2330",
        policy=RealtimePolicy.REQUIRE_LIVE,
        requested_at=datetime(2026, 8, 25, 14, 0, tzinfo=TAIWAN_TZ),
        acquisition=TaiwanPublicQuoteAcquisitionExecutor(
            fetchers={
                TWSE_MIS_PUBLIC_QUOTE_DESCRIPTOR.resource_id: forbidden_fetch
            }
        ),
    )
    assert calls == 0
    assert result.resolved.health.status is ResolvedEvidenceStatus.POLICY_UNSATISFIED
    assert not result.acquisition.attempted
    assert "SESSION_NOT_SUPPORTED_BY_RESOURCE" in result.acquisition.limitations
    assert db.query(RawFetchResult).count() == 0


def test_preopen_trial_is_persisted_but_cannot_satisfy_last_trade(
    db: Session,
) -> None:
    record = _records()["6173"]
    result = acquire_taiwan_public_last_trade_quote(
        db,
        stock_id="6173",
        policy=RealtimePolicy.REQUIRE_LIVE,
        requested_at=datetime(2026, 8, 21, 8, 59, 25, tzinfo=TAIWAN_TZ),
        acquisition=_executor(
            _raw(record),
            datetime(2026, 8, 21, 0, 59, 25, tzinfo=timezone.utc),
        ),
    )
    assert result.acquisition.status.value == "partial"
    assert result.persistence.committed
    assert result.resolved.health.status is ResolvedEvidenceStatus.POLICY_UNSATISFIED
    assert result.resolved.quote is None
    assert result.candidate_rejections[0].missing_fields == ("last_trade_price",)
    row = db.query(TaiwanStockQuoteSnapshot).one()
    assert row.last_price is None
    assert row.total_volume_lots == 0
    assert row.observation_state == "indicative"
    assert row.trade_state == "indicative_observed"


def test_timeout_writes_failure_receipt_without_creating_or_clearing_quote(
    db: Session,
) -> None:
    def timeout(_route, _instrument):
        raise TimeoutError("bounded timeout")

    result = acquire_taiwan_public_last_trade_quote(
        db,
        stock_id="2330",
        policy=RealtimePolicy.PREFER_LIVE,
        requested_at=datetime(2026, 8, 25, 10, 0, tzinfo=TAIWAN_TZ),
        acquisition=TaiwanPublicQuoteAcquisitionExecutor(
            fetchers={TWSE_MIS_PUBLIC_QUOTE_DESCRIPTOR.resource_id: timeout},
            clock=lambda: datetime(2026, 8, 25, 2, 0, tzinfo=timezone.utc),
        ),
    )
    assert result.acquisition.status.value == "failed"
    assert result.persistence.committed
    assert result.persistence.receipts_written == 1
    assert result.resolved.health.status is ResolvedEvidenceStatus.MISSING
    assert db.query(TaiwanStockQuoteSnapshot).count() == 0
    raw = db.query(RawFetchResult).one()
    assert raw.status_code is None
    assert "TimeoutError" in str(raw.error_message)
    assert raw.content_hash == hashlib.sha256(b"").hexdigest()
    source = db.query(SourceRegistry).one()
    assert "TimeoutError" in str(source.last_error_message)


def test_legacy_snapshot_without_lineage_fails_closed(db: Session) -> None:
    db.add(
        TaiwanStockQuoteSnapshot(
            provider="twse_mis",
            market="TWSE",
            stock_id="2330",
            session_phase="regular_live",
            trade_date=datetime(2026, 8, 25).date(),
            quote_time=datetime(2026, 8, 25, 10, 0, tzinfo=TAIWAN_TZ),
            last_price=2400,
            source="twse_mis_quote_depth",
            fetched_at=datetime(2026, 8, 25, 2, 0, tzinfo=timezone.utc),
        )
    )
    db.commit()
    read = TaiwanPublicQuoteRepository(db).load_latest_quote(
        InstrumentKey(
            market=Market.TW,
            symbol="2330",
            instrument_type=InstrumentType.STOCK,
            venue="TWSE",
        )
    )
    assert read.observation is None
    assert read.limitations == ("PUBLIC_QUOTE_LINEAGE_MISSING",)


def test_transaction_commit_failure_rolls_back_raw_and_quote(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _records()["2330"]

    def fail_commit() -> None:
        raise RuntimeError("forced commit failure")

    monkeypatch.setattr(db, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="forced commit failure"):
        acquire_taiwan_public_last_trade_quote(
            db,
            stock_id="2330",
            policy=RealtimePolicy.PREFER_LIVE,
            requested_at=datetime(2026, 8, 25, 13, 29, 55, tzinfo=TAIWAN_TZ),
            acquisition=_executor(
                _raw(record),
                datetime(2026, 8, 25, 5, 30, 1, tzinfo=timezone.utc),
            ),
        )
    assert db.query(SourceRegistry).count() == 0
    assert db.query(RawFetchResult).count() == 0
    assert db.query(TaiwanStockQuoteSnapshot).count() == 0
    assert db.query(DataQualityCheck).count() == 0


def test_public_quote_router_is_provider_neutral() -> None:
    source = (
        Path(__file__).parents[1]
        / "app"
        / "routers"
        / "tw_public_quotes.py"
    ).read_text(encoding="utf-8")
    assert "app.market.providers" not in source
    assert ".commit(" not in source
    assert ".rollback(" not in source
    assert "provider:" not in source


def test_public_quote_get_route_handler_returns_persisted_actual_data_without_io(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _records()["2330"]
    acquire_taiwan_public_last_trade_quote(
        db,
        stock_id="2330",
        policy=RealtimePolicy.PREFER_LIVE,
        requested_at=datetime(2026, 8, 25, 13, 29, 55, tzinfo=TAIWAN_TZ),
        acquisition=_executor(
            _raw(record),
            datetime(2026, 8, 25, 5, 30, 1, tzinfo=timezone.utc),
        ),
    )
    original_read = read_taiwan_public_last_trade_quote
    monkeypatch.setattr(
        tw_public_quotes,
        "read_taiwan_public_last_trade_quote",
        lambda route_db, *, stock_id: original_read(
            route_db,
            stock_id=stock_id,
            requested_at=datetime(2026, 8, 25, 13, 29, 56, tzinfo=TAIWAN_TZ),
        ),
    )

    result = tw_public_quotes.get_public_last_trade_quote("2330", db)
    payload = result.model_dump(mode="json")
    assert payload["contract_version"] == "omi.market.data_result.v1"
    assert payload["result_kind"] == "quote"
    assert payload["requirement"]["realtime_policy"] == "cache_only"
    assert payload["acquisition"]["external_calls"] == 0
    assert payload["resolved"]["health"]["status"] == "selected"
    assert payload["resolved"]["quote"]["last_trade_price"] == "2400.0"
    assert payload["resolved"]["quote"]["lineage"]["cache_hit"] is True
