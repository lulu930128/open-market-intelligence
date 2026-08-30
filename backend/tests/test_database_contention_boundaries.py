from __future__ import annotations

from datetime import date
from pathlib import Path
from threading import Event, Thread
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool, QueuePool

from app.db.models import Base
from app.db.session import engine as application_engine
from app.us_market import service as us_market_service


def test_application_sqlite_engine_does_not_use_bounded_connection_pool() -> None:
    assert application_engine.url.get_backend_name() == "sqlite"
    assert isinstance(application_engine.pool, NullPool)


def test_us_ohlc_provider_wait_does_not_hold_sqlite_pool_connection() -> None:
    database_name = f"omi_pool_boundary_{uuid4().hex}"
    engine = create_engine(
        f"sqlite:///file:{database_name}?mode=memory&cache=shared&uri=true",
        connect_args={"check_same_thread": False},
        poolclass=QueuePool,
        pool_size=1,
        max_overflow=0,
        pool_timeout=0.2,
    )
    Base.metadata.create_all(bind=engine)
    provider_entered = Event()
    release_provider = Event()
    worker_errors: list[BaseException] = []

    def blocked_refresh(**_kwargs) -> dict:
        provider_entered.set()
        if not release_provider.wait(timeout=3):
            raise TimeoutError("test provider release was not signaled")
        return {
            "status": "success",
            "provider": "yahoo_chart",
            "fetched_count": 0,
            "inserted_count": 0,
            "updated_count": 0,
            "message": "test refresh completed",
        }

    def load_chart() -> None:
        try:
            with Session(engine) as db:
                us_market_service.list_us_ohlc_chart_data(
                    db=db,
                    symbol="^GSPC",
                    timeframe="daily",
                    bars=60,
                    ensure_history=True,
                    provider="yahoo_chart",
                )
        except BaseException as exc:  # pragma: no cover - surfaced below
            worker_errors.append(exc)

    try:
        with patch.object(
            us_market_service,
            "refresh_us_daily_prices",
            side_effect=blocked_refresh,
        ):
            worker = Thread(target=load_chart, daemon=True)
            worker.start()
            assert provider_entered.wait(timeout=2)
            try:
                with Session(engine) as probe_db:
                    assert probe_db.execute(text("SELECT 1")).scalar_one() == 1
            finally:
                release_provider.set()
            worker.join(timeout=3)

        assert not worker.is_alive()
        assert worker_errors == []
    finally:
        release_provider.set()
        engine.dispose()


def test_us_ohlc_projection_does_not_hold_sqlite_pool_connection_after_read() -> None:
    database_name = f"omi_ohlc_projection_pool_boundary_{uuid4().hex}"
    engine = create_engine(
        f"sqlite:///file:{database_name}?mode=memory&cache=shared&uri=true",
        connect_args={"check_same_thread": False},
        poolclass=QueuePool,
        pool_size=1,
        max_overflow=0,
        pool_timeout=0.2,
    )
    Base.metadata.create_all(bind=engine)
    projection_entered = Event()
    release_projection = Event()
    worker_errors: list[BaseException] = []

    def blocked_projection(**_kwargs) -> list[dict]:
        projection_entered.set()
        if not release_projection.wait(timeout=3):
            raise TimeoutError("test projection release was not signaled")
        return []

    def load_chart() -> None:
        try:
            with Session(engine) as db:
                us_market_service.list_us_ohlc_chart_data(
                    db=db,
                    symbol="^GSPC",
                    timeframe="daily",
                    bars=60,
                    ensure_history=False,
                    include_intraday=False,
                )
        except BaseException as exc:  # pragma: no cover - surfaced below
            worker_errors.append(exc)

    try:
        with patch.object(
            us_market_service,
            "aggregate_ohlc_points",
            side_effect=blocked_projection,
        ):
            worker = Thread(target=load_chart, daemon=True)
            worker.start()
            assert projection_entered.wait(timeout=2)
            try:
                with Session(engine) as probe_db:
                    assert probe_db.execute(text("SELECT 1")).scalar_one() == 1
            finally:
                release_projection.set()
            worker.join(timeout=3)

        assert not worker.is_alive()
        assert worker_errors == []
    finally:
        release_projection.set()
        engine.dispose()


def test_us_intraday_read_is_cache_only_and_releases_sqlite_pool_connection() -> None:
    database_name = f"omi_intraday_pool_boundary_{uuid4().hex}"
    engine = create_engine(
        f"sqlite:///file:{database_name}?mode=memory&cache=shared&uri=true",
        connect_args={"check_same_thread": False},
        poolclass=QueuePool,
        pool_size=1,
        max_overflow=0,
        pool_timeout=0.2,
    )
    Base.metadata.create_all(bind=engine)
    symbol = f"POOL{uuid4().hex[:8].upper()}"

    try:
        with patch.object(
            us_market_service,
            "fetch_yahoo_chart_payload",
        ) as provider_fetch:
            with Session(engine) as db:
                result = us_market_service.get_us_intraday_trend(symbol=symbol, db=db)
            provider_fetch.assert_not_called()
            assert result["point_count"] == 0
        with Session(engine) as probe_db:
            assert probe_db.execute(text("SELECT 1")).scalar_one() == 1
    finally:
        engine.dispose()


def test_us_ohlc_intraday_overlay_wait_does_not_hold_sqlite_pool_connection() -> None:
    database_name = f"omi_ohlc_intraday_pool_boundary_{uuid4().hex}"
    engine = create_engine(
        f"sqlite:///file:{database_name}?mode=memory&cache=shared&uri=true",
        connect_args={"check_same_thread": False},
        poolclass=QueuePool,
        pool_size=1,
        max_overflow=0,
        pool_timeout=0.2,
    )
    Base.metadata.create_all(bind=engine)
    provider_entered = Event()
    release_provider = Event()
    worker_errors: list[BaseException] = []

    def blocked_intraday(**_kwargs) -> dict:
        provider_entered.set()
        if not release_provider.wait(timeout=3):
            raise TimeoutError("test provider release was not signaled")
        return {"points": [], "point_count": 0, "source": "test"}

    def load_chart() -> None:
        try:
            with Session(engine) as db:
                us_market_service.list_us_ohlc_chart_data(
                    db=db,
                    symbol="^GSPC",
                    timeframe="daily",
                    bars=60,
                    ensure_history=False,
                    include_intraday=True,
                )
        except BaseException as exc:  # pragma: no cover - surfaced below
            worker_errors.append(exc)

    try:
        with patch.object(
            us_market_service,
            "get_us_intraday_trend",
            side_effect=blocked_intraday,
        ):
            worker = Thread(target=load_chart, daemon=True)
            worker.start()
            assert provider_entered.wait(timeout=2)
            try:
                with Session(engine) as probe_db:
                    assert probe_db.execute(text("SELECT 1")).scalar_one() == 1
            finally:
                release_provider.set()
            worker.join(timeout=3)

        assert not worker.is_alive()
        assert worker_errors == []
    finally:
        release_provider.set()
        engine.dispose()


def test_us_ohlc_repair_provider_wait_does_not_hold_sqlite_pool_connection() -> None:
    database_name = f"omi_ohlc_repair_pool_boundary_{uuid4().hex}"
    engine = create_engine(
        f"sqlite:///file:{database_name}?mode=memory&cache=shared&uri=true",
        connect_args={"check_same_thread": False},
        poolclass=QueuePool,
        pool_size=1,
        max_overflow=0,
        pool_timeout=0.2,
    )
    Base.metadata.create_all(bind=engine)
    provider_entered = Event()
    release_provider = Event()
    worker_errors: list[BaseException] = []

    def blocked_refresh(**_kwargs) -> dict:
        provider_entered.set()
        if not release_provider.wait(timeout=3):
            raise TimeoutError("test provider release was not signaled")
        return {
            "status": "success",
            "provider": "yahoo_chart",
            "fetched_count": 0,
            "inserted_count": 0,
            "updated_count": 0,
            "message": "test refresh completed",
        }

    def repair_chart() -> None:
        try:
            us_market_service.repair_us_ohlc_history(
                symbol="^GSPC",
                timeframe="daily",
                bars=4,
                max_provider_calls=1,
                force_full=True,
                to_date=date(2026, 8, 21),
                session_factory=lambda: Session(engine),
            )
        except BaseException as exc:  # pragma: no cover - surfaced below
            worker_errors.append(exc)

    try:
        with patch.object(
            us_market_service,
            "refresh_us_daily_prices",
            side_effect=blocked_refresh,
        ):
            worker = Thread(target=repair_chart, daemon=True)
            worker.start()
            assert provider_entered.wait(timeout=2)
            try:
                with Session(engine) as probe_db:
                    assert probe_db.execute(text("SELECT 1")).scalar_one() == 1
            finally:
                release_provider.set()
            worker.join(timeout=3)

        assert not worker.is_alive()
        assert worker_errors == []
    finally:
        release_provider.set()
        engine.dispose()


def test_regional_market_tape_polling_is_cache_first() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    tape_path = (
        repo_root
        / "frontend"
        / "src"
        / "components"
        / "market-dashboard"
        / "tape"
        / "useRegionalMarketTapeState.ts"
    )
    tape_source = tape_path.read_text(encoding="utf-8-sig")

    assert "ensure_history: true" not in tape_source
    assert tape_source.count("ensure_history: false") >= 3


def test_us_historical_chart_initial_load_does_not_wait_for_intraday_provider() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    detail_path = (
        repo_root
        / "frontend"
        / "src"
        / "components"
        / "USStockDetailPanel.tsx"
    )
    detail_source = detail_path.read_text(encoding="utf-8-sig")

    assert "shouldIncludeUsOhlcIntraday" not in detail_source
    assert "...(shouldIncludeUsOhlcIntraday() ? { include_intraday: true } : {})" not in detail_source


def test_inactive_us_ranking_preload_does_not_start_provider_refresh() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    hook_path = (
        repo_root
        / "frontend"
        / "src"
        / "components"
        / "market-dashboard"
        / "ranking"
        / "useUsRankingState.ts"
    )
    hook_source = hook_path.read_text(encoding="utf-8-sig")
    preload_start = hook_source.index(
        "if (groupId === null || active || initialPreloadQueuedRef.current) return;"
    )
    active_load_start = hook_source.index(
        "if (!active || groupId === null) return;",
        preload_start,
    )
    inactive_preload = hook_source[preload_start:active_load_start]

    assert "void load(currentGroupId, rankBy, { silent: true });" in inactive_preload
    assert "refreshDailyPrices(" not in inactive_preload
