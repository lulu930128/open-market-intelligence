from __future__ import annotations

from datetime import date, datetime, timezone
import inspect as python_inspect
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.ai.market_context import taiwan_stock
from app.db.models import Base, RawFetchResult, SourceRegistry, StockProfile
from app.market.tw_company_profile import (
    project_taiwan_company_profile,
    read_taiwan_company_profile,
)


def _db() -> tuple[Session, object]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine), engine


def test_company_profile_reader_preserves_raw_lineage() -> None:
    db, engine = _db()
    now = datetime(2026, 8, 26, 8, 0, tzinfo=timezone.utc)
    try:
        source = SourceRegistry(
            source_name="twse_company_profile",
            source_type="official_exchange",
            category="company_profile",
        )
        db.add(source)
        db.flush()
        raw = RawFetchResult(
            source_id=source.id,
            fetched_at=now,
            url="https://example.test/company-profile",
            status_code=200,
            content_type="application/json",
            content_hash="sha256:company-profile",
            parser_version="tw.company_profile.v1",
        )
        db.add(raw)
        db.flush()
        db.add(
            StockProfile(
                source_id=source.id,
                raw_result_id=raw.id,
                report_date=date(2026, 8, 25),
                stock_id="2330",
                company_name="Taiwan Semiconductor Manufacturing",
                market="TWSE",
                industry="Semiconductor",
                listed_date=date(1994, 9, 5),
                established_date=date(1987, 2, 21),
                paid_in_capital=259_303_804_580,
                issued_shares=25_930_380_458,
                updated_at=now,
            )
        )
        db.commit()

        profile = read_taiwan_company_profile(db, "2330")
        assert profile is not None
        assert profile.source_name == "twse_company_profile"
        assert profile.raw_result_id == raw.id
        assert profile.lineage_complete is True
        assert profile.limitations == ()

        projected = project_taiwan_company_profile(
            SimpleNamespace(
                stock_id="2330",
                stock_name="TSMC",
                market="TWSE",
                instrument_type="common_stock",
                industry="Semiconductor",
                category="listed",
                is_active=True,
            ),
            profile,
        )
        assert projected["status"] == "ready"
        assert projected["source"] == "stock_master+stock_profile"
        assert projected["source_name"] == "twse_company_profile"
        assert projected["raw_result_id"] == raw.id
        assert projected["lineage_complete"] is True
    finally:
        db.close()
        engine.dispose()


def test_company_profile_reader_returns_truthful_missing() -> None:
    db, engine = _db()
    try:
        assert read_taiwan_company_profile(db, "2330") is None
    finally:
        db.close()
        engine.dispose()


def test_ai_taiwan_stock_context_does_not_own_stock_profile_sql() -> None:
    source = python_inspect.getsource(taiwan_stock)
    assert "db.query(StockProfile)" not in source
    assert "from app.db.models import StockProfile" not in source
    assert "read_taiwan_company_profile" in source
