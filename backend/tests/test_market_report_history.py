from datetime import date, datetime
from pathlib import Path
import runpy
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.dispatch import discord_market_report as report
from app.jobs import market_report_history as history
from app.jobs import scheduler

NOW = datetime(2026, 10, 2, 16, tzinfo=ZoneInfo("Asia/Taipei"))
DAY = NOW.date()
START = date(2026, 3, 17)  # Deliberately not an independently calculated lookback.


def chart(status="complete", count=124):
    return {"coverage_status": status, "available_bar_count": count,
            "expected_minimum_bar_count": 90, "from_date": START, "to_date": DAY}


def test_preparation_only_orchestrates_final_selection(monkeypatch):
    selection = SimpleNamespace(model=SimpleNamespace(
        stock_radar=[{"stock_id": str(i)} for i in range(12)],
        evidence_axes={"daily_sample_cap": DAY.isoformat()}), local_now=NOW)
    selector = Mock(return_value=selection)
    readiness = Mock(return_value={"status": "partial", "unresolved": ["1"]})
    monkeypatch.setattr(history, "build_report_selection", selector)
    monkeypatch.setattr(history, "prepare_taiwan_technical_inputs", readiness)
    db = Mock()
    result = history.prepare_discord_market_report_history(db, "postclose", NOW, "replay")
    readiness.assert_called_once_with(db, stock_ids=[str(i) for i in range(8)], to_date=DAY, bars=90)
    selector.assert_called_once()
    assert result["selection"] is selection and result["unresolved"] == ["1"]
    db.query.assert_not_called()


def test_empty_selection_is_noop(monkeypatch):
    selection = SimpleNamespace(model=SimpleNamespace(stock_radar=[], evidence_axes={}), local_now=NOW)
    monkeypatch.setattr(history, "build_report_selection", Mock(return_value=selection))
    readiness = Mock()
    monkeypatch.setattr(history, "prepare_taiwan_technical_inputs", readiness)
    assert history.prepare_discord_market_report_history(Mock(), "postclose", NOW)["status"] == "ready"
    readiness.assert_not_called()


def test_readonly_uses_same_helper_and_frozen_selection_without_reselection(monkeypatch):
    engine = create_engine("sqlite://")
    with Session(engine) as db:
        db.execute(text("CREATE TABLE sentinel (value INTEGER)"))
        db.commit()
        preview = Mock(return_value={"metadata": {"value_leaders": [{"stock_id": "1459"}]}})
        monkeypatch.setattr(report.templates, "build_market_overview_preview", preview)
        selector = Mock(wraps=report.build_report_selection)
        monkeypatch.setattr(report, "build_report_selection", selector)
        monkeypatch.setattr(report, "read_stock_analysis_facts", lambda *a, **kw: ({}, {}))
        monkeypatch.setattr(report, "build_tw_stock_price_map", lambda **kw: {})
        model, _, _ = report.build_readonly_presentation(db, phase="postclose", local_now=NOW, evidence_time_mode="replay")
        selector.assert_called_once()
        frozen = report.build_report_selection(db, phase="postclose", local_now=NOW, evidence_time_mode="replay")
        selector.reset_mock()
        preview.reset_mock()
        again, _, _ = report.build_readonly_presentation(
            db, phase="postclose", local_now=NOW, evidence_time_mode="replay", selection=frozen)
        assert again.stock_radar == model.stock_radar
        selector.assert_not_called()
        preview.assert_not_called()
        with pytest.raises(Exception, match="readonly"):
            db.execute(text("INSERT INTO sentinel VALUES (1)"))
    engine.dispose()


@pytest.mark.parametrize("fails", [False, True])
def test_scheduler_prepares_first_and_failure_still_sends(monkeypatch, caplog, fails):
    events = []
    selection = object()
    def prepare(*args, **kwargs):
        events.append("prepare")
        if fails:
            raise RuntimeError("preparation unavailable")
        return dict(status="partial", selected=["1459"], attempted=["1459"], repaired=[],
                    unresolved=["1459"], selection=selection)
    def send(*args, **kwargs):
        events.append("send")
        assert (kwargs.get("selection") is selection) is (not fails)
        return {"status": "sent", "sent_chunks": 1}
    monkeypatch.setattr(history, "prepare_discord_market_report_history", prepare)
    monkeypatch.setattr(scheduler, "SessionLocal", MagicMock())
    monkeypatch.setattr(report, "run_discord_market_report", send)
    scheduler.send_discord_market_report("postclose")
    assert events == ["prepare", "send"]
    if fails:
        assert "continuing read-only report" in caplog.text
        assert any(record.exc_info for record in caplog.records)


@pytest.mark.parametrize("opt_in", [False, True])
def test_cli_preparation_is_explicit_and_replay_time_is_shared(monkeypatch, capsys, opt_in):
    import sys
    from app.db import session
    cli = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts/run-discord-market-report.py"))
    selection = object()
    prep = Mock(return_value=dict(status="ready", selected=[], attempted=[], repaired=[], unresolved=[], results=[], selection=selection))
    send = Mock(return_value={"status": "sent"})
    monkeypatch.setattr(history, "prepare_discord_market_report_history", prep)
    monkeypatch.setattr(report, "run_discord_market_report", send)
    monkeypatch.setattr(session, "SessionLocal", MagicMock())
    argv = ["report", "--confirm-live-send", "--evidence-time-mode", "replay", "--now", NOW.isoformat()]
    if opt_in:
        argv.append("--prepare-history")
    monkeypatch.setattr(sys, "argv", argv)
    assert cli["main"]() == 0
    assert send.call_args.kwargs["now"] == NOW
    if opt_in:
        assert prep.call_args.args[2] == NOW
        assert prep.call_args.kwargs["evidence_time_mode"] == "replay"
        assert send.call_args.kwargs["selection"] is selection
        assert "history_preparation" in capsys.readouterr().out
    else:
        prep.assert_not_called()


def test_dispatch_read_module_cannot_reach_history_write_owner():
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(report))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith(("app.jobs", "app.market.backfill", "app.sources", "app.market.providers"))
        if isinstance(node, ast.Call):
            name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ""
            assert not name.startswith(("backfill_", "prepare_", "fetch_", "persist_"))
            assert name not in {"commit", "flush", "add", "add_all"}


def test_cli_prepare_only_never_sends(monkeypatch):
    import sys
    from app.db import session
    cli = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts/run-discord-market-report.py"))
    monkeypatch.setattr(history, "prepare_discord_market_report_history", Mock(return_value={
        "status": "partial", "selection": object(), "unresolved": ["fixture"]}))
    sender = Mock(side_effect=AssertionError("must not send"))
    monkeypatch.setattr(report, "run_discord_market_report", sender)
    monkeypatch.setattr(session, "SessionLocal", MagicMock())
    monkeypatch.setattr(sys, "argv", ["report", "--prepare-only", "--evidence-time-mode", "replay", "--now", NOW.isoformat()])
    assert cli["main"]() == 2
    sender.assert_not_called()
