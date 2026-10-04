from datetime import date
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.ai.market_context import tw_market_chips as chips
from app.db.models import (
    InstitutionalTradeDaily, MarginTradingDaily, MarketChipDaily, StockMaster,
)


TRADE_DATE = date(2026, 10, 2)
ELIGIBLE_IDS = ("2330", "6488")
EXCLUDED_IDS = ("0050", "020001", "030001", "9105", "123456", "9999", "8888", "7777")


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    for model in (StockMaster, InstitutionalTradeDaily, MarginTradingDaily, MarketChipDaily):
        model.__table__.create(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def seed_universe(db, *, eligible=True):
    if eligible:
        db.add_all([
            StockMaster(stock_id="2330", market="TWSE", instrument_type="stock"),
            StockMaster(stock_id="6488", market="TPEX", instrument_type="stock"),
        ])
    db.add_all([
        StockMaster(stock_id="0050", market="TWSE", instrument_type="etf"),
        StockMaster(stock_id="020001", market="TWSE", instrument_type="etn"),
        StockMaster(stock_id="030001", market="TWSE", instrument_type="warrant"),
        StockMaster(stock_id="9105", market="TWSE", instrument_type="dr"),
        # Even a misclassified six-digit code remains the universe owner's concern.
        StockMaster(stock_id="123456", market="TWSE", instrument_type="stock"),
        StockMaster(stock_id="8888", market="TWSE", instrument_type="stock", is_active=False),
        StockMaster(stock_id="7777", market="OTHER", instrument_type="stock"),
        # 9999 is deliberately absent from StockMaster.
    ])


def seed_source(db, stock_ids, *, source_id=1, trade_date=TRADE_DATE, value=10):
    for stock_id in stock_ids:
        db.add(InstitutionalTradeDaily(
            source_id=source_id, raw_result_id=1, trade_date=trade_date,
            stock_id=stock_id, foreign_investor_net=value,
            investment_trust_net=2 * value, dealer_net=-value,
            total_institutional_net=2 * value,
        ))
        db.add(MarginTradingDaily(
            source_id=source_id, raw_result_id=1, trade_date=trade_date,
            stock_id=stock_id, margin_today_balance=10 * value,
            margin_previous_balance=9 * value, short_today_balance=3 * value,
            short_previous_balance=2 * value,
        ))


def read_only(db, **kwargs):
    db.commit()
    db.execute(text("PRAGMA query_only=ON"))
    return chips.read_tw_market_chips_context(db, **kwargs)


@pytest.mark.parametrize("covered_ids", [(), ELIGIBLE_IDS[:1], ELIGIBLE_IDS])
def test_canonical_coverage_aggregate_and_rankings_exclude_other_instruments(db, monkeypatch, covered_ids):
    seed_universe(db)
    seed_source(db, covered_ids)
    seed_source(db, EXCLUDED_IDS, value=100_000)
    # Duplicate source rows must not inflate either coverage or excluded-ID count.
    seed_source(db, EXCLUDED_IDS, source_id=2, value=-200_000)
    # A previous date cannot fill current-date coverage.
    seed_source(db, ELIGIBLE_IDS, trade_date=date(2026, 10, 1), value=999)
    owner = Mock(wraps=chips.list_taiwan_stock_ids)
    monkeypatch.setattr(chips, "list_taiwan_stock_ids", owner)

    result = read_only(db, limit=50)
    from app.dispatch.market_report_presentation import build_presentation, stock_radar_items
    presentation = build_presentation({"metadata": {"market_chips": result}}, phase="postclose", report_date=TRADE_DATE)
    assert {row["stock_id"] for row in stock_radar_items(presentation)} == set(covered_ids)
    assert not set(EXCLUDED_IDS) & {row["stock_id"] for row in presentation.stock_radar}
    owner.assert_called_once_with(db)
    count = len(covered_ids)
    for key, rankings in (
        ("institutional_per_stock", ("top_net_buy", "top_net_sell")),
        ("margin_per_stock", ("top_margin_increase", "top_short_increase")),
    ):
        block = result[key]
        coverage = block["coverage"]
        assert block["trade_date"] == TRADE_DATE.isoformat()
        assert block["status"] == ("ready" if count == 2 else "partial")
        assert coverage["universe_class"] == "ordinary_stock"
        assert coverage["eligible_count"] == 2
        assert coverage["covered_eligible_count"] == count
        assert coverage["missing_eligible_count"] == 2 - count
        assert coverage["out_of_universe_source_count"] == len(EXCLUDED_IDS)
        assert coverage["coverage_ratio"] == count / 2
        assert coverage["is_full_eligible_coverage"] is (count == 2)
        assert coverage["full_market_verification"] == "not_asserted"
        for alias, canonical in coverage["compatibility_aliases"].items():
            assert coverage[alias] == coverage[canonical]
        for ranking in rankings:
            assert {row["stock_id"] for row in block[ranking]} == set(covered_ids)
    assert result["institutional_per_stock"]["aggregate"] == ({
        "foreign_investor_net": 10 * count, "investment_trust_net": 20 * count,
        "dealer_net": -10 * count, "total_institutional_net": 20 * count,
    } if count else {})
    assert result["margin_per_stock"]["aggregate"] == ({
        "margin_balance": 100 * count, "margin_balance_change": 10 * count,
        "short_balance": 30 * count, "short_balance_change": 10 * count,
    } if count else {})
    # Raw source data is retained; this read neither deletes nor rewrites it.
    assert db.query(InstitutionalTradeDaily).count() == count + 2 * len(EXCLUDED_IDS) + 2


@pytest.mark.parametrize("eligible", [False, True])
@pytest.mark.parametrize("source_present", [False, True])
def test_empty_universe_and_missing_source_never_become_ready(db, eligible, source_present):
    seed_universe(db, eligible=eligible)
    if source_present:
        seed_source(db, EXCLUDED_IDS)
    result = read_only(db)
    for key in ("institutional_per_stock", "margin_per_stock"):
        block = result[key]
        coverage = block["coverage"]
        assert block["status"] == ("partial" if source_present else "missing")
        assert block["aggregate"] == {}
        assert coverage["eligible_count"] == (2 if eligible else 0)
        assert coverage["covered_eligible_count"] == 0
        assert coverage["missing_eligible_count"] == coverage["eligible_count"]
        assert coverage["coverage_ratio"] == (0 if eligible else None)
        assert coverage["out_of_universe_source_count"] == (len(EXCLUDED_IDS) if source_present else 0)
        assert coverage["is_full_eligible_coverage"] is False


def test_each_dataset_retains_its_latest_date_and_distinct_coverage(db):
    seed_universe(db)
    seed_source(db, ELIGIBLE_IDS, trade_date=date(2026, 10, 1))
    db.add(InstitutionalTradeDaily(
        source_id=1, raw_result_id=1, trade_date=TRADE_DATE,
        stock_id="2330", total_institutional_net=20,
    ))
    db.add(InstitutionalTradeDaily(
        source_id=2, raw_result_id=1, trade_date=TRADE_DATE,
        stock_id="2330", total_institutional_net=30,
    ))
    result = read_only(db)
    institutional = result["institutional_per_stock"]
    margin = result["margin_per_stock"]
    assert institutional["trade_date"] == "2026-10-02"
    assert institutional["coverage"]["coverage_ratio"] == 0.5
    assert institutional["coverage"]["out_of_universe_source_count"] == 0
    assert institutional["aggregate"]["total_institutional_net"] == 50
    assert margin["trade_date"] == "2026-10-01"
    assert margin["coverage"]["coverage_ratio"] == 1


def test_membership_is_delegated_without_local_code_rules(db, monkeypatch):
    # A changed owner result must flow through both readers without reclassification.
    monkeypatch.setattr(chips, "list_taiwan_stock_ids", Mock(return_value=["OWNER-ID"]))
    seed_source(db, ["OWNER-ID", "2330"])
    result = read_only(db)
    for key in ("institutional_per_stock", "margin_per_stock"):
        assert result[key]["coverage"]["eligible_count"] == 1
        assert result[key]["coverage"]["coverage_ratio"] == 1
        assert result[key]["coverage"]["out_of_universe_source_count"] == 1
    assert result["institutional_per_stock"]["top_net_buy"][0]["stock_id"] == "OWNER-ID"
    assert result["margin_per_stock"]["top_margin_increase"][0]["stock_id"] == "OWNER-ID"
