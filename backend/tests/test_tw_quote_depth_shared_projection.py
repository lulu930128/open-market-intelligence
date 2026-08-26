from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.ai.market_context.taiwan_projection import _compact_quote_snapshot
from app.ai.market_context.taiwan_stock import (
    _requested_quote_evidence_capabilities,
)
from app.db.models import (
    Base,
    MarketDailyPrice,
    RawFetchResult,
    SourceRegistry,
    StockMaster,
    TaiwanStockQuoteSnapshot,
)
from app.market.providers.kgi_realtime_acquisition import (
    KgiRealtimeAcquisitionAdapter,
    KgiRealtimeProviderSnapshot,
)
from app.market.public_quote_platform import acquire_taiwan_public_last_trade_quote
from app.market.quote_depth import get_taiwan_stock_quote_depth
from app.market.schemas import TaiwanStockQuoteDepthRead
from app.market.taiwan_realtime_platform import (
    acquire_taiwan_auction,
    acquire_taiwan_depth,
)
from app.market.tw_realtime_capabilities import (
    KGI_AUCTION_DESCRIPTOR,
    KGI_ORDER_BOOK_DESCRIPTOR,
    KGI_QUOTE_SNAPSHOT_DESCRIPTOR,
)
from app.market_data.contracts import MarketSession
from app.market_data.policies import RealtimePolicy
from app.sources.defaults import TWSE_DAILY_TRADING_SOURCE_NAME


TAIPEI = timezone(timedelta(hours=8))
NOW = datetime(2026, 8, 26, 10, 0, tzinfo=TAIPEI)


def _db() -> tuple[Session, object]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.add(
        StockMaster(
            stock_id="2330",
            stock_name="台積電",
            market="TWSE",
            instrument_type="stock",
        )
    )
    db.commit()
    return db, engine


def _quote(*, indicative: bool = False) -> dict[str, object]:
    return {
        "symbol": "2330",
        "datetime": "20260826100000",
        "received_at": "2026-08-26T02:00:00+00:00",
        "simtrade": 1 if indicative else 0,
        "close": 1180,
        "volume": 2,
        "total_volume": 100 if not indicative else 0,
        "open": 1170,
        "high": 1185,
        "low": 1165,
        "price_chg": 10,
        "bid_prices": [1175, 1170],
        "bid_volumes": [4, 5],
        "ask_prices": [1180, 1185],
        "ask_volumes": [3, 6],
    }


def _adapter(*, indicative: bool = False) -> KgiRealtimeAcquisitionAdapter:
    return KgiRealtimeAcquisitionAdapter(
        lambda _symbol: KgiRealtimeProviderSnapshot(
            quote=_quote(indicative=indicative),
            status="live",
        ),
        clock=lambda: NOW,
    )


def _persist_quote_and_depth(db: Session) -> None:
    adapter = _adapter()
    acquire_taiwan_public_last_trade_quote(
        db,
        stock_id="2330",
        policy=RealtimePolicy.REQUIRE_LIVE,
        requested_at=NOW,
        acquisition=adapter,
        descriptors=(KGI_QUOTE_SNAPSHOT_DESCRIPTOR,),
    )
    acquire_taiwan_depth(
        db,
        stock_id="2330",
        policy=RealtimePolicy.REQUIRE_LIVE,
        descriptors=(KGI_ORDER_BOOK_DESCRIPTOR,),
        acquisition=adapter,
        requested_at=NOW,
        session=MarketSession.CONTINUOUS,
    )


def _persist_official_daily_close(
    db: Session,
    *,
    trade_date: date,
    close_price: float,
) -> None:
    source = SourceRegistry(
        source_name=TWSE_DAILY_TRADING_SOURCE_NAME,
        source_type="api",
        category="market_data",
        priority=10,
        parser_type="twse_daily_trading",
        reliability_level="official",
    )
    db.add(source)
    db.flush()
    raw = RawFetchResult(
        source_id=source.id,
        fetched_at=datetime(2026, 8, 26, 7, 30, tzinfo=timezone.utc),
        content_hash="quote-bundle-official-close",
        parser_version="twse.stock_day_all.v1",
        raw_text="[]",
    )
    db.add(raw)
    db.flush()
    db.add(
        MarketDailyPrice(
            source_id=source.id,
            raw_result_id=raw.id,
            stock_id="2330",
            trade_date=trade_date,
            open_price=1170,
            high_price=1185,
            low_price=1165,
            close_price=close_price,
            trade_volume=1_000_000,
        )
    )
    db.commit()


def test_quote_depth_get_projects_shared_quote_and_typed_depth_without_io() -> None:
    db, engine = _db()
    try:
        _persist_quote_and_depth(db)
        with patch.object(
            db,
            "commit",
            side_effect=AssertionError("GET must not commit"),
        ):
            result = get_taiwan_stock_quote_depth(
                db=db,
                stock_id="2330",
                refresh=True,
                now=NOW,
            )

        public = TaiwanStockQuoteDepthRead.model_validate(result)
        assert public.provider == "kgi_superpy"
        assert public.last_trade_available is True
        assert public.last_price == 1180
        assert public.depth_available is True
        assert len(public.bid_levels) == 2
        assert len(public.ask_levels) == 2
        assert public.bid_levels[0].size_lots == 4
        assert result["read_policy"] == "cache_only"
        assert result["data_core_result_kinds"] == [
            "quote",
            "depth",
            "auction",
            "bar_series",
        ]
        components = result["data_core_components"]
        assert components["quote.snapshot"]["lineage"]["provider"] == "kgi_superpy"
        assert components["quote.order_book"]["lineage"]["provider"] == "kgi_superpy"
        assert components["quote.order_book"]["dataset_health"]["status"] == "healthy"
        assert components["quote.auction"]["lineage"] is None
        assert components["quote.official_close"]["available"] is False

        ai_quote = _compact_quote_snapshot(
            latest_daily=None,
            quote_depth=result,
            quote_error=None,
            session_phase="regular_live",
            current_session_date="2026-08-26",
            is_trading_day=True,
        )
        order_book = ai_quote["components"]["order_book"]
        assert order_book["provider"] == "kgi_superpy"
        assert order_book["lineage"]["provider"] == "kgi_superpy"
        assert order_book["dataset_health"]["dataset_id"] == (
            "tw.quote.order_book.snapshot"
        )
    finally:
        db.close()
        engine.dispose()


def test_official_close_component_uses_canonical_daily_owner() -> None:
    db, engine = _db()
    try:
        _persist_quote_and_depth(db)
        _persist_official_daily_close(
            db,
            trade_date=date(2026, 8, 26),
            close_price=1182,
        )
        after_release = datetime(2026, 8, 26, 16, 0, tzinfo=TAIPEI)

        with patch.object(
            db,
            "commit",
            side_effect=AssertionError("canonical bundle read must not commit"),
        ):
            result = get_taiwan_stock_quote_depth(
                db=db,
                stock_id="2330",
                now=after_release,
            )

        official = result["data_core_components"]["quote.official_close"]
        assert official["available"] is True
        assert official["provider"] == "twse_openapi"
        assert official["lineage"]["raw_receipt_id"].startswith(
            "raw_fetch_result:"
        )
        assert official["price"] == 1182
        assert official["trade_date"] == date(2026, 8, 26)
        assert result["official_close_available"] is True
        assert result["official_close_source"] == TWSE_DAILY_TRADING_SOURCE_NAME
        assert result["official_close_price"] == 1182

        ai_quote = _compact_quote_snapshot(
            latest_daily=None,
            quote_depth=result,
            quote_error=None,
            session_phase="post_close",
            current_session_date="2026-08-26",
            is_trading_day=True,
        )
        ai_official = ai_quote["components"]["official_close"]
        assert ai_official["available"] is True
        assert ai_official["provider"] == "twse_openapi"
        assert ai_official["lineage"]["raw_receipt_id"].startswith(
            "raw_fetch_result:"
        )
    finally:
        db.close()
        engine.dispose()


def test_trial_auction_projection_never_overwrites_actual_trade() -> None:
    db, engine = _db()
    try:
        _persist_quote_and_depth(db)
        disposition = {"cache_status": "current", "is_active": True}
        with patch(
            "app.market.taiwan_realtime_platform.get_taiwan_disposition_status",
            return_value=disposition,
        ):
            acquire_taiwan_auction(
                db,
                stock_id="2330",
                policy=RealtimePolicy.REQUIRE_LIVE,
                descriptors=(KGI_AUCTION_DESCRIPTOR,),
                acquisition=_adapter(indicative=True),
                requested_at=NOW,
                session=MarketSession.CONTINUOUS,
                disposition_status=disposition,
            )
            result = get_taiwan_stock_quote_depth(
                db=db,
                stock_id="2330",
                now=NOW,
            )

        assert result["last_price"] == 1180
        assert result["actual_trade_occurred"] is True
        assert result["auction_indicative_available"] is True
        assert result["indicative_match_price"] == 1180
        assert db.query(TaiwanStockQuoteSnapshot).count() == 1
    finally:
        db.close()
        engine.dispose()


def test_router_and_shared_core_have_no_kgi_provider_import() -> None:
    root = Path(__file__).resolve().parents[1] / "app"
    router_source = (root / "routers" / "market.py").read_text(encoding="utf-8")
    assert "app.market.providers.kgi_superpy" not in router_source
    assert "app.market.kgi_market_data" not in router_source
    assert "app.market.tw_kgi_data_operations" in router_source
    assert "app.market.tw_realtime_stream_platform" in router_source
    assert "app.market.tw_realtime_lease_platform" in router_source
    for name in ("research_lease.py", "control_plane.py", "gateway.py"):
        source = (root / "market_data" / name).read_text(encoding="utf-8")
        assert "kgi_superpy" not in source


def test_quote_depth_public_owner_is_cache_only_projection() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "app" / "market" / "quote_depth.py"
    ).read_text(encoding="utf-8")
    function_source = source[source.index("def get_taiwan_stock_quote_depth(") :]
    assert "read_taiwan_quote_evidence_projection" in function_source
    assert "acquire_taiwan_quote_evidence_projection" not in function_source
    assert "http_get" not in function_source
    assert "get_kgi_superpy_quote_snapshot" not in function_source
    assert ".commit(" not in function_source
    assert ".rollback(" not in function_source


def test_quote_depth_module_has_no_provider_io_or_transaction_owner() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "app" / "market" / "quote_depth.py"
    ).read_text(encoding="utf-8")

    assert "app.market.providers" not in source
    assert "http_get" not in source
    assert "get_kgi_superpy_quote_snapshot" not in source
    assert "_fetch_mis_quote_depth" not in source
    assert "_upsert_quote_snapshot" not in source
    assert "_run_canonical_quote_shadow" not in source
    assert ".commit(" not in source
    assert ".rollback(" not in source


def test_ai_quote_snapshot_intent_maps_to_the_bounded_quote_bundle_scope() -> None:
    assert _requested_quote_evidence_capabilities(
        {"requested_capabilities": ["quote.snapshot"]}
    ) == ("quote.snapshot",)
    assert _requested_quote_evidence_capabilities(
        {"requested_capabilities": ["quote.last_trade"]}
    ) == ("quote.snapshot",)
