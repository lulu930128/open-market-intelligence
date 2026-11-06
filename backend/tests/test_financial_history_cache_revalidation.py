"""Explicit quarter repairs must not get stuck on pre-filing batch receipts."""
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import models as m
from app.market import financial_metrics_history_backfill as owner


def statement(symbol):
    return ("<table><tr><th>公司代號</th><th>公司名稱</th><th>營業收入</th></tr>"
            f"<tr><td>{symbol}</td><td>Fixture</td><td>100</td></tr></table>")


@pytest.mark.parametrize(
    "cached_income,cached_balance,fresh_symbol,expected_fetches,expected_status",
    [("2882", "2882", "2882", 0, "inserted"),
     ("2330", "2330", "2882", 2, "inserted"),
     ("2882", "2330", "2882", 2, "inserted"),
     ("2330", "2330", "2330", 2, "no_data"),
     ("2330", "2330", "timeout", 1, "error")],
)
def test_bounded_repair_revalidates_only_incomplete_cache(
    monkeypatch, cached_income, cached_balance, fresh_symbol,
    expected_fetches, expected_status,
):
    engine = create_engine("sqlite://")
    m.Base.metadata.create_all(engine, tables=[model.__table__ for model in (
        m.SourceRegistry, m.RawFetchResult, m.StockMaster, m.FinancialMetricQuarterly,
    )])
    calls, closed = [], []
    monkeypatch.setattr(owner, "new_session", lambda: SimpleNamespace(close=lambda: closed.append(True)))

    def fetch(**kwargs):
        calls.append((kwargs["statement"], kwargs["fiscal_year"], kwargs["quarter"]))
        if fresh_symbol == "timeout":
            raise TimeoutError("fixture timeout")
        return statement(fresh_symbol), 200, "text/html", "https://fixture.invalid"

    monkeypatch.setattr(owner, "_fetch_statement_html", fetch)
    with Session(engine) as db:
        db.add(m.StockMaster(stock_id="2882", stock_name="Fixture", market="TWSE"))
        source = m.SourceRegistry(source_name="TWSE financial", source_type="fixture",
                                  category="financial_metrics", parser_type="financial_metrics")
        db.add(source)
        db.flush()
        original_text = json.dumps({
            "income": {"raw_text": statement(cached_income)},
            "balance": {"raw_text": statement(cached_balance)},
        })
        original = owner._create_raw_result(
            db, source.id, owner._bundle_cache_url("TWSE", 2026, 2),
            original_text, 200, "application/json",
        )
        db.commit()
        original_id, original_hash = original.id, original.content_hash
        result = owner.ensure_stock_financial_metrics_history(
            db, "2882", from_fiscal_year=2026, from_quarter=2,
            to_fiscal_year=2026, to_quarter=2, lookback_quarters=1, sleep_seconds=0,
        )
        assert result["results"][0]["status"] == expected_status
        assert len(calls) == expected_fetches
        assert all((year, quarter) == (2026, 2) for _, year, quarter in calls)
        assert closed == [True]
        preserved = db.get(m.RawFetchResult, original_id)
        assert (preserved.raw_text, preserved.content_hash) == (original_text, original_hash)
        refreshed = expected_fetches == 2
        assert db.query(m.RawFetchResult).count() == (2 if refreshed else 1)
        if refreshed:
            assert result["cached_count"] == result["fetched_count"] == 1
            assert result["results"][0]["raw_result_id"] != original_id
        if expected_status == "inserted":
            metric = db.query(m.FinancialMetricQuarterly).one()
            assert metric.raw_result_id == result["results"][0]["raw_result_id"]
        else:
            assert db.query(m.FinancialMetricQuarterly).count() == 0
    engine.dispose()
