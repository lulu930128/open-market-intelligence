from __future__ import annotations

import ast
from datetime import datetime, timezone
import inspect
import json
from types import SimpleNamespace
import traceback
from unittest.mock import MagicMock, Mock
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import Settings
from app.dispatch import discord_market_report as report
from app.dispatch import discord_sender as sender
from app.dispatch import market_report_text as renderer
from app.dispatch import market_report_presentation as presentation
from app.jobs import scheduler


@pytest.fixture
def event_output(monkeypatch):
    from io import StringIO
    from app.dispatch.discord_report_events import event_logger
    output = StringIO()
    handler = next(h for h in event_logger().handlers if h.name == "discord_market_report_stderr")
    monkeypatch.setattr(handler, "stream", output)
    return output


def test_event_logger_uvicorn_stderr_and_reload():
    import subprocess
    import sys
    from pathlib import Path
    # Configure real Uvicorn logging without starting a server or any app jobs.
    code = '''
import importlib
import logging
from uvicorn import Config
Config("unused:app").configure_logging()
root = logging.getLogger()
before = (root.level, list(root.handlers))
from app.dispatch import discord_report_events as events
for _ in range(3):
    events = importlib.reload(events)
    events.event_logger()
logger = events.event_logger()
assert len(logger.handlers) == 1
assert not logger.propagate
assert (root.level, root.handlers) == before
logging.getLogger("app.requests").info("must_not_appear")
events.report_event("triggered", phase="preopen")
'''
    result = subprocess.run([sys.executable, "-c", code],
                            cwd=Path(__file__).resolve().parents[1],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert result.stderr.count("stage=triggered") == 1
    assert "INFO" in result.stderr and "phase=preopen" in result.stderr
    assert "must_not_appear" not in result.stderr + result.stdout
    assert not result.stdout


@pytest.mark.parametrize("history_status", ["ready", "partial", "error"])
@pytest.mark.parametrize("send_fails", [False, True])
def test_scheduler_event_stages(monkeypatch, event_output, history_status, send_fails):
    from app.jobs import market_report_history
    secret = "https://discord.com/api/webhooks/123/private-token"
    prepare = Mock(return_value=dict(status=history_status, selection=None,
                                    selected=[], attempted=[], repaired=[], unresolved=[]))
    if history_status == "error":
        prepare.side_effect = RuntimeError(secret)
    monkeypatch.setattr(market_report_history, "prepare_discord_market_report_history", prepare)
    monkeypatch.setattr(scheduler, "SessionLocal", MagicMock())
    failure = RuntimeError(secret)
    runner = Mock(return_value={"status": "sent", "sent_chunks": 1},
                  side_effect=failure if send_fails else None)
    monkeypatch.setattr(report, "run_discord_market_report", runner)
    if send_fails:
        with pytest.raises(RuntimeError) as caught:
            scheduler.send_discord_market_report("postclose")
        assert caught.value is failure
    else:
        scheduler.send_discord_market_report("postclose")
    lines = event_output.getvalue().splitlines()
    assert [line.split("stage=")[1].split()[0] for line in lines] == [
        "triggered", "history_ready" if history_status == "ready" else "history_failed",
        "report_start", "failed" if send_fails else "completed"]
    assert len({line.split("run_id=")[1].split()[0] for line in lines}) == 1
    assert all("phase=postclose" in line for line in lines)
    assert secret not in event_output.getvalue() and "private-token" not in event_output.getvalue()
    runner.assert_called_once()


def test_registered_events(monkeypatch, event_output):
    monkeypatch.setattr(scheduler.settings, "enable_discord_market_report_scheduler", True)
    instance = Mock()
    scheduler._add_discord_market_report_jobs(instance)
    lines = event_output.getvalue().splitlines()
    assert len(lines) == 3
    for line, call in zip(lines, instance.add_job.call_args_list):
        fields = call.kwargs
        assert "stage=registered" in line
        assert f"phase={fields['kwargs']['phase']}" in line
        assert f"job_id={fields['id']}" in line
        assert f"scheduled_time={fields['hour']:02d}:{fields['minute']:02d}" in line
        assert "timezone=Asia/Taipei" in line
        assert "webhook" not in line


NOW = datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc)


@pytest.fixture
def webhook():
    # Synthetic per-test value; no real credential in fixtures or test output.
    return "https://discord.com/api/webhooks/123/" + uuid.uuid4().hex


@pytest.fixture
def transport(monkeypatch):
    factory = Mock()
    factory.return_value.getresponse.return_value.status = 200
    monkeypatch.setattr(sender.http.client, "HTTPSConnection", factory)
    return factory


@pytest.fixture
def prepared(monkeypatch, webhook):
    monkeypatch.setattr(report.settings, "discord_market_report_webhook_url", webhook)
    calendar = Mock(return_value={"is_trading_day": True, "calendar_limit": None})
    monkeypatch.setattr(report, "build_taiwan_calendar_status", calendar)
    sessions = MagicMock()
    sessions.return_value.__enter__.return_value.get_bind.return_value.dialect.name = "sqlite"
    monkeypatch.setattr(report, "SessionLocal", sessions)
    preview = Mock(return_value={
        "as_of": "2026-10-01", "body_text": "原始市場判讀\n第二行",
        "warnings": ["stale: coverage partial"], "missing": ["market.chips"],
    })
    monkeypatch.setattr(report.templates, "build_market_overview_preview", preview)
    send = Mock(return_value={"status": "sent", "sent_chunks": 1, "total_chunks": 1})
    monkeypatch.setattr(report, "send_discord_rich_report", send)
    return SimpleNamespace(calendar=calendar, sessions=sessions, preview=preview, send=send)


@pytest.mark.parametrize("content", [
    "單行", "甲\n乙\n" * 1000, "中" * 6001,
    "😀" * 2001, "標題\n" + "a" * 1901 + "\n警告", "a" * 1900,
], ids=["short", "lines", "long-line", "emoji", "mixed", "boundary"])
def test_chunk_limit_order_and_no_loss(content):
    chunks = sender.chunk_content(content)
    assert "".join(chunks) == content
    assert all(0 < len(chunk.encode("utf-16-le")) // 2 <= 1900 for chunk in chunks)


def test_chunk_prefers_complete_lines():
    assert sender.chunk_content("abc\ndef\nghi", limit=8) == ["abc\ndef\n", "ghi"]


@pytest.mark.parametrize("content,limit", [("", 1900), (" \n", 1900), ("x", 2001), ("x", 1)])
def test_chunk_invalid_input(content, limit):
    with pytest.raises(ValueError):
        sender.chunk_content(content, limit=limit)


@pytest.mark.parametrize("status", [200, 201, 204, 299])
def test_transport_2xx_order_and_confirmation(webhook, transport, status):
    transport.return_value.getresponse.return_value.status = status
    content = "標題\nas_of：2026-10-02\n" + "正文\n" * 1200
    result = sender.send_discord_report(webhook + "?wait=false&thread_id=456", content)
    requests = transport.return_value.request.call_args_list
    assert result == {"status": "sent", "sent_chunks": len(requests), "total_chunks": len(requests)}
    assert len(requests) > 1
    assert "".join(json.loads(call.kwargs["body"])["content"] for call in requests) == content
    for call in requests:
        assert call.args[0] == "POST"
        assert "wait=true" in call.args[1] and "thread_id=456" in call.args[1]
        assert json.loads(call.kwargs["body"])["allowed_mentions"] == {"parse": []}
    transport.assert_called_with("discord.com", timeout=30)


@pytest.mark.parametrize("status", [301, 400, 401, 429, 500, 503])
def test_http_failure_stops_without_retry_and_redacts(webhook, transport, status, caplog):
    first, second = Mock(status=200), Mock(status=status)
    second.read.return_value = webhook.encode()
    transport.return_value.getresponse.side_effect = [first, second]
    with pytest.raises(sender.DiscordDeliveryError) as caught:
        sender.send_discord_report(webhook, "中" * 6000)
    error = caught.value
    assert error.sent_chunks == 1 and error.total_chunks == 4
    assert error.status_code == status
    assert error.outcome == ("unknown" if status >= 500 else "failed")
    assert transport.return_value.request.call_count == 2
    diagnostic = "".join(traceback.format_exception(error)) + caplog.text
    assert webhook not in diagnostic and webhook.rsplit("/", 1)[1] not in diagnostic
    second.read.assert_not_called()


@pytest.mark.parametrize("operation", ["request", "getresponse", "close"])
def test_network_exception_is_unknown_without_secret_chain(webhook, transport, operation, caplog):
    getattr(transport.return_value, operation).side_effect = OSError(webhook)
    with pytest.raises(sender.DiscordDeliveryError) as caught:
        sender.send_discord_report(webhook, "報表")
    error = caught.value
    assert error.outcome == "unknown"
    assert error.__context__ is None and error.__cause__ is None
    assert webhook not in "".join(traceback.format_exception(error)) + caplog.text
    assert transport.call_count == 1


@pytest.mark.parametrize("value", [None, "", "   ", "http://discord.com/", "https://example.invalid/"])
def test_invalid_or_missing_webhook_never_connects(value, transport):
    with pytest.raises(sender.DiscordDeliveryError):
        sender.send_discord_report(value, "報表")
    transport.assert_not_called()


def test_report_missing_secret_stops_before_calendar_or_db(prepared, monkeypatch):
    monkeypatch.setattr(report.settings, "discord_market_report_webhook_url", None)
    with pytest.raises(sender.DiscordDeliveryError, match="secret not configured"):
        report.run_discord_market_report("postclose", now=NOW)
    prepared.calendar.assert_not_called()
    prepared.sessions.assert_not_called()
    prepared.send.assert_not_called()


@pytest.mark.parametrize("calendar,reason", [
    ({"is_trading_day": False}, "non_trading_day"),
    ({"is_trading_day": True, "calendar_limit": "unverified year"}, "calendar_unverified"),
    ({}, "calendar_unverified"),
])
def test_calendar_skip_precedes_template_and_transport(prepared, calendar, reason):
    prepared.calendar.return_value = calendar
    result = report.run_discord_market_report("postclose", now=NOW)
    assert result["status"] == "skipped" and result["reason"] == reason
    prepared.sessions.assert_not_called()
    prepared.preview.assert_not_called()
    prepared.send.assert_not_called()


@pytest.mark.parametrize("phase,label", list(report.PHASE_LABELS.items()))
def test_template_reuse_preserves_asof_warnings_missing(prepared, phase, label, webhook):
    result = report.run_discord_market_report(phase, now=NOW, mode="audit")
    assert result["evidence_time_mode"] == "live"
    assert result["semantics"] == "strict_availability"
    db = prepared.sessions.return_value.__enter__.return_value
    prepared.preview.assert_called_once_with(db, market="tw")
    assert str(db.execute.call_args.args[0]) == "PRAGMA query_only=ON"
    db.commit.assert_not_called()
    prepared.sessions.return_value.__exit__.assert_called_once()
    content = next(item.data.decode("utf-8") for item in prepared.send.call_args.kwargs["attachments"] if item.filename == "full_report.txt")
    assert content.startswith(f"# OMI 台股{label}分析｜2026-10-02")
    assert "as_of：2026-10-01" in content
    assert "warning: stale: coverage partial" in content and "missing: market.chips" in content
    assert prepared.preview.return_value["body_text"] not in content
    assert content.index("warning: stale: coverage partial") > content.index("## 資料品質與限制")
    assert result["as_of"] == "2026-10-01" and result["warning_count"] == result["missing_count"] == 1
    assert webhook not in repr(result)
    assert prepared.calendar.call_args.kwargs["now"].hour == 16


def test_empty_preview_discloses_missing_time_and_body():
    content = report.render_market_report({}, phase="preopen", now=NOW)
    assert "as_of：missing" in content and "資料品質：missing" in content
    assert "日線樣本日期 missing" in content


def test_invalid_phase_or_naive_time_has_no_side_effect(prepared):
    with pytest.raises(ValueError):
        report.run_discord_market_report("invalid", now=NOW)
    with pytest.raises(ValueError):
        report.run_discord_market_report("postclose", now=NOW.replace(tzinfo=None))
    prepared.send.assert_not_called()
    prepared.preview.assert_not_called()


def test_template_failure_never_sends(prepared):
    prepared.preview.side_effect = RuntimeError("reader failed")
    with pytest.raises(RuntimeError, match="reader failed"):
        report.run_discord_market_report("postclose", now=NOW)
    prepared.send.assert_not_called()
    prepared.sessions.return_value.__exit__.assert_called_once()


def test_real_template_uses_formal_reader_only(monkeypatch, webhook, transport):
    # Real template/render/transport with an injected canonical reader fixture.
    # No provider, LLM, SMTP or production DB participates.
    monkeypatch.setattr(report.settings, "discord_market_report_webhook_url", webhook)
    monkeypatch.setattr(report, "build_taiwan_calendar_status", Mock(return_value={"is_trading_day": True}))
    engine = create_engine("sqlite://")
    monkeypatch.setattr(report, "SessionLocal", lambda: Session(engine))
    reader = Mock(return_value={
        "kind": "market_overview", "as_of": "2026-10-01",
        "warnings": ["canonical stale"], "missing": ["canonical breadth"], "data": {},
    })
    monkeypatch.setattr(report.templates.tools, "read_market_overview", reader)
    try:
        result = report.run_discord_market_report("postclose", now=NOW, mode="audit")
    finally:
        engine.dispose()
    reader.assert_called_once()
    assert reader.call_args.kwargs["limit"] == 8
    assert reader.call_args.kwargs["market_data_params"] == {"requested_capabilities": ["market.indices"]}
    content = transport.return_value.request.call_args.kwargs["body"].decode("utf-8", errors="replace")
    assert "canonical stale" in content and "canonical breadth" in content
    assert result["status"] == "sent"


def test_discord_modules_cannot_import_market_data_providers_or_ai():
    orchestration_allowed = {
        "__future__", "datetime", "typing", "zoneinfo", "sqlalchemy", "contextlib",
        "http.client", "json", "re", "urllib.parse", "app.config", "app.db.session",
        "app.dispatch", "app.dispatch.discord_sender", "app.market.calendar_status",
        "app.dispatch.market_report_text", "math", "dataclasses", "uuid",
        "app.dispatch.market_report_presentation", "app.dispatch.market_report_discord",
        "app.dispatch.market_report_chart", "time", "app.market.stock_price_map",
        "app.market.service", "app.market.daily_ohlcv_platform", "app.market.technical_report",
        "app.market.taiwan_rules",
    }
    module_boundaries = (
        (report, orchestration_allowed),
        (sender, {"__future__", "http.client", "json", "re", "contextlib", "dataclasses", "uuid", "urllib.parse",
                  "app.dispatch.discord_report_events"}),
        (renderer, {"__future__", "datetime", "app.dispatch.market_report_presentation"}),
        (presentation, {"__future__", "dataclasses", "datetime", "math", "typing", "re"}),
    )
    for module, allowed in module_boundaries:
        tree = ast.parse(inspect.getsource(module))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.module in allowed, (module.__name__, node.module)
            elif isinstance(node, ast.Import):
                assert all(alias.name in allowed for alias in node.names)


def test_settings_defaults_hide_webhook_and_validate_times(webhook):
    settings = Settings(_env_file=None, discord_market_report_webhook_url=webhook,
                        enable_discord_market_report_scheduler=False)
    assert webhook not in repr(settings) and webhook not in settings.model_dump_json()
    assert not settings.enable_discord_market_report_scheduler
    defaults = Settings.model_fields
    assert [defaults[f"scheduler_discord_market_report_{phase}_time"].default for phase in report.PHASE_LABELS] == ["08:55", "10:00", "16:00"]
    with pytest.raises(ValueError):
        Settings(_env_file=None, scheduler_discord_market_report_preopen_time="24:00")


def test_scheduler_exact_three_phases_and_timezone(monkeypatch):
    from apscheduler.schedulers.background import BackgroundScheduler

    monkeypatch.setattr(scheduler.settings, "enable_discord_market_report_scheduler", True)
    for phase, at in zip(report.PHASE_LABELS, ("08:55", "10:00", "16:00")):
        monkeypatch.setattr(scheduler.settings, f"scheduler_discord_market_report_{phase}_time", at)
    instance = BackgroundScheduler(timezone="UTC")
    assert scheduler._add_discord_market_report_jobs(instance)
    jobs = instance.get_jobs()
    assert len(jobs) == 3
    for job, phase, hour, minute in zip(jobs, report.PHASE_LABELS, (8, 10, 16), (55, 0, 0)):
        assert job.kwargs == {"phase": phase}
        assert job.func is scheduler.send_discord_market_report
        assert str(job.trigger.timezone) == "Asia/Taipei"
        fields = {field.name: str(field) for field in job.trigger.fields}
        assert (fields["hour"], fields["minute"], fields["second"], fields["day_of_week"]) == (str(hour), str(minute), "0", "mon-fri")
        assert job.max_instances == 1 and job.coalesce and job.misfire_grace_time == 60


def test_scheduler_disabled_and_dispatch_wrapper(monkeypatch):
    from app.jobs import market_report_history
    monkeypatch.setattr(market_report_history, "prepare_discord_market_report_history", Mock(return_value={
        "status": "ready", "selected": [], "attempted": [], "repaired": [], "unresolved": [], "selection": None}))
    monkeypatch.setattr(scheduler, "SessionLocal", MagicMock())
    assert inspect.signature(report.run_discord_market_report).parameters["evidence_time_mode"].default == "live"
    monkeypatch.setattr(scheduler.settings, "enable_discord_market_report_scheduler", False)
    instance = Mock()
    assert not scheduler._add_discord_market_report_jobs(instance)
    instance.add_job.assert_not_called()
    runner = Mock(return_value={"status": "sent", "sent_chunks": 2})
    monkeypatch.setattr(report, "run_discord_market_report", runner)
    scheduler.send_discord_market_report("intraday")
    runner.assert_called_once()
    assert runner.call_args.args == ("intraday",)
    assert runner.call_args.kwargs["now"].tzinfo is not None


@pytest.mark.parametrize("mode", [None, "live", "replay"])
def test_cli_evidence_time_mode(monkeypatch, capsys, mode):
    import runpy
    from pathlib import Path
    import sys

    cli = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts/run-discord-market-report.py"))
    runner = Mock(return_value={"status": "sent"})
    monkeypatch.setattr(report, "run_discord_market_report", runner)
    argv = ["run-discord-market-report.py", "--confirm-live-send"]
    if mode is not None:
        argv.extend(["--evidence-time-mode", mode])
    monkeypatch.setattr(sys, "argv", argv)
    assert cli["main"]() == 0
    runner.assert_called_once_with("postclose", mode="compact", evidence_time_mode=mode or "live")
    assert json.loads(capsys.readouterr().out)["status"] == "sent"


def test_run_replay_returns_semantics_and_warning(prepared):
    result = report.run_discord_market_report("postclose", now=NOW, evidence_time_mode="replay")
    assert result["evidence_time_mode"] == "replay"
    assert result["semantics"] == "current_cache_bounded_report_date"
    assert any("not an immutable historical snapshot" in value for value in result["presentation_warnings"])
    assert prepared.preview.call_args.kwargs["trade_date"].isoformat() == "2026-10-02"


def test_invalid_evidence_time_mode_fails_before_io(prepared):
    with pytest.raises(ValueError, match="evidence time mode"):
        report.run_discord_market_report("postclose", evidence_time_mode="snapshot")
    prepared.calendar.assert_not_called()
    prepared.sessions.assert_not_called()
    prepared.send.assert_not_called()


def test_scheduler_error_propagates_without_retry(monkeypatch):
    from app.jobs import market_report_history
    monkeypatch.setattr(market_report_history, "prepare_discord_market_report_history", Mock(return_value={
        "status": "ready", "selected": [], "attempted": [], "repaired": [], "unresolved": [], "selection": None}))
    monkeypatch.setattr(scheduler, "SessionLocal", MagicMock())
    runner = Mock(side_effect=sender.DiscordDeliveryError("HTTP failure", status_code=429))
    monkeypatch.setattr(report, "run_discord_market_report", runner)
    with pytest.raises(sender.DiscordDeliveryError):
        scheduler.send_discord_market_report("postclose")
    runner.assert_called_once()


def test_start_scheduler_registers_discord_when_other_jobs_disabled(monkeypatch):
    from apscheduler.schedulers.background import BackgroundScheduler

    for name in type(scheduler.settings).model_fields:
        if name.startswith("enable_"):
            monkeypatch.setattr(scheduler.settings, name, False)
    monkeypatch.setattr(scheduler.settings, "enable_discord_market_report_scheduler", True)
    monkeypatch.setattr(BackgroundScheduler, "start", lambda self: None)
    instance = scheduler.start_scheduler()
    assert instance is not None
    assert {job.kwargs["phase"] for job in instance.get_jobs() if job.id.startswith("discord_market_report_")} == set(report.PHASE_LABELS)


SECTIONS = [
    "一眼看盤", "指數與盤勢", "量能與成交", "市場廣度與漲跌結構", "族群輪動",
    "焦點股與成交值", "籌碼", "跨市場背景", "本時段觀察 / 下一時段觀察", "資料品質與限制",
]


@pytest.fixture
def evidence_preview():
    stock = {"stock_id": "2330", "stock_name": "測試公司", "close_price": 100.0,
             "change_pct": 1.25, "trade_value": 100_000_000}
    breadth = {"advance_count": 60, "decline_count": 30, "unchanged_count": 10,
               "positive_ratio": 2 / 3, "coverage_count": 100, "universe_count": 120,
               "coverage_ratio": 100 / 120, "total_count": 120, "status": "partial",
               "trade_date": "2026-10-02", "as_of": "2026-10-02T10:00:00+08:00",
               "market_session": "regular", "session_semantics": "current_session"}
    return {"as_of": breadth["as_of"], "warnings": ["fixture warning", "fixture warning"],
            "missing": ["fixture missing"], "metadata": {
        "latest_trade_date": "2026-10-01", "stance": "震盪", "breadth": breadth,
        "breadth_by_market": {"TWSE": breadth, "TPEX": breadth},
        "sample_breadth": {"total_count": 100},
        "sample_coverage": {"sample_count": 100, "universe_count": 120, "coverage_ratio": 100 / 120},
        "distribution": {"limit_up_count": 3, "limit_down_count": 1, "strong_up_count": 5,
                         "strong_down_count": 2, "mild_up_count": 52, "mild_down_count": 30, "flat_count": 10},
        "top_gainers": [stock], "top_losers": [{**stock, "change_pct": -2.0}], "value_leaders": [stock],
        "top_industries": [{"industry": "強勢測試族群", "average_change_pct": 2.0,
                            "advance_count": 10, "decline_count": 2, "top_stock_id": "2330"}],
        "weak_industries": [{"industry": "弱勢測試族群", "average_change_pct": -1.0}],
        "index_intraday": {"status": "partial"},
        "market": {"indices": {"status": "partial", "items": [
            {"index_id": "TAIEX", "value": 22000.5, "change": 10.5, "change_pct": 0.05,
             "trade_date": "2026-10-02", "as_of": breadth["as_of"],
             "freshness": {"status": "stale"}, "quote_semantics": "intraday_last_trade"}]}},
        "volume_state": {"status": "partial", "as_of": breadth["as_of"], "trade_date": "2026-10-02",
                         "comparison_minute": "10:00", "current_cumulative_trade_value": 500_000_000,
                         "one_minute_trade_value_change": 10_000_000,
                         "trade_value_authority_status": "estimated", "trade_value_coverage_status": "partial",
                         "same_time_baseline_5d": {"readiness_status": "ready", "sample_days": 5, "pace_ratio": 1.2},
                         "same_time_baseline_20d": {"status": "warming_up", "sample_days": 5}},
        "market_chips": {"status": "partial", "official_market_aggregate": {"status": "ready",
            "rows": [{"index_id": "TAIEX", "trade_date": "2026-10-01", "total_institutional_net_value": 100_000_000}],
            "freshness": [{"index_id": "TAIEX", "status": "current", "release_status": "released"}]},
            "institutional_per_stock": {"status": "partial", "trade_date": "2026-09-30"},
            "margin_per_stock": {"status": "unreleased", "trade_date": "2026-09-29"}},
        "cross_market": {"status": "partial", "markets": {"us": {"status": "partial", "assets": [
            {"label": "fixture SPX", "price": 6000, "currency": "USD", "change_pct": -1,
             "as_of": "2026-09-28", "status": "stale"}]}}},
        "freshness": {"status": "partial"}, "freshness_by_capability": {"market.indices": {"status": "stale"}},
    }}


@pytest.mark.parametrize("phase", report.PHASE_LABELS)
def test_all_eleven_sections_order_and_lossless_chunks(evidence_preview, phase):
    content = report.render_market_report(evidence_preview, phase=phase, now=NOW)
    assert len([line for line in content.splitlines() if line.startswith("# ")]) == 1
    assert [line[3:] for line in content.splitlines() if line.startswith("## ")] == SECTIONS
    assert "證據 session：regular / current_session" in content.split("## 一眼看盤")[0]
    chunks = sender.chunk_content(content)
    assert "".join(chunks) == content
    assert all(len(chunk.encode("utf-16-le")) // 2 <= 1900 for chunk in chunks)


def test_phase_specific_observations(evidence_preview):
    observations = {}
    for phase in report.PHASE_LABELS:
        content = report.render_market_report(evidence_preview, phase=phase, now=NOW)
        observations[phase] = content.split("## 本時段觀察 / 下一時段觀察")[1].split("## 資料品質與限制")[0]
    assert len(set(observations.values())) == 3
    assert "隔夜" in observations["preopen"] and "09:00 後確認" in observations["preopen"]
    assert "交叉確認" in observations["intraday"] and "分歧" in observations["intraday"]
    assert "官方收盤確認" in observations["postclose"] and "下一交易時段" in observations["postclose"]


@pytest.mark.parametrize("phase", ["preopen", "intraday"])
def test_prior_completed_sample_label_in_all_daily_sections(evidence_preview, phase):
    content = report.render_market_report(evidence_preview, phase=phase, now=NOW)
    label = "前一已完成交易日樣本（2026-10-01）"
    for section in ("一眼看盤", "量能與成交", "市場廣度與漲跌結構", "族群輪動", "焦點股與成交值"):
        assert label in content.split("## " + section)[1].split("\n## ")[0]
    assert "本派報未納入當日盤中個股排行" in content
    assert "本交易日日線樣本" not in content


def test_same_day_postclose_daily_label(evidence_preview):
    evidence_preview["metadata"]["latest_trade_date"] = "2026-10-02"
    content = report.render_market_report(evidence_preview, phase="postclose", now=NOW)
    assert "本交易日日線樣本（2026-10-02；非即時排行）" in content
    assert "前一已完成交易日樣本" not in content


@pytest.mark.parametrize("value,expected", [(None, "日期 missing"), ("invalid", "日期 missing"),
                                         ("2026-10-03", "晚於報告日期")])
def test_unknown_or_future_sample_is_not_presented_as_current(evidence_preview, value, expected):
    evidence_preview["metadata"]["latest_trade_date"] = value
    assert expected in report.render_market_report(evidence_preview, phase="intraday", now=NOW)


def test_canonical_values_dates_and_partial_axes_are_preserved(evidence_preview):
    content = report.render_market_report(evidence_preview, phase="intraday", now=NOW)
    for value in ("22,000.50", "+0.05%", "TPEX 櫃買指數：missing", "5.00 億元",
                  "10:00", "10,000,000 元", "1.20 倍", "readiness=warming_up",
                  "authority=estimated", "coverage=partial", "TWSE：上漲 60", "TPEX：上漲 60",
                  "強勢測試族群", "代表 2330", "fixture SPX", "status=stale"):
        assert value in content
    chips = content.split("## 籌碼")[1].split("## 跨市場背景")[0]
    assert "trade_date=2026-10-01" in chips and "發布=released" in chips
    assert "個股法人：status=partial｜trade_date=2026-09-30" in chips
    assert "融資融券：status=unreleased｜trade_date=2026-09-29" in chips
    assert "輔助背景" in content and "as_of=2026-09-28" in content


@pytest.mark.parametrize("key", ["institutional_per_stock", "margin_per_stock"])
def test_chips_text_uses_canonical_ordinary_stock_coverage(key):
    content = "\n".join(renderer._chips_lines({key: {"status": "partial", "coverage": {
        "universe_class": "ordinary_stock", "eligible_count": 2,
        "covered_eligible_count": 1, "missing_eligible_count": 1,
        "out_of_universe_source_count": 50, "coverage_ratio": 0.5,
        # Conflicting legacy counts must never override canonical evidence.
        "covered_stock_count": 51, "active_stock_master_count": 3,
    }}}))
    assert "普通股 canonical coverage 1/2 （50.0%" in content
    assert "母體類別 universe_class=ordinary_stock" in content
    assert "母體外來源代碼 50 檔" in content
    assert "51/3" not in content
    assert "上游資料庫覆蓋" not in content


def test_chips_legacy_only_counts_are_not_relabelled_as_ordinary_stock():
    content = "\n".join(renderer._chips_lines({"institutional_per_stock": {"coverage": {
        "covered_stock_count": 24677, "active_stock_master_count": 2023,
    }}}))
    assert "普通股 canonical coverage missing/missing" in content
    assert "24,677/2,023" not in content


@pytest.mark.parametrize("value", [None, {}, [], "malformed"])
def test_missing_or_malformed_blocks_render_gracefully(evidence_preview, value):
    for key in ("market", "volume_state", "market_chips", "cross_market", "breadth_by_market"):
        evidence_preview["metadata"][key] = value
    content = report.render_market_report(evidence_preview, phase="postclose", now=NOW)
    for fragment in ("TAIEX 加權指數：missing", "TPEX 櫃買指數：missing", "累計成交值：missing",
                     "官方市場彙總：status=missing", "個股法人：status=missing", "融資融券：status=missing",
                     "美國：status=missing", "日本：status=missing", "韓國：status=missing",
                     "原物料：status=missing", "加密資產：status=missing", "TWSE：上漲 missing"):
        assert fragment in content


def test_warning_details_deduplicated_only_at_bottom(evidence_preview):
    evidence_preview["metadata"]["cross_market"]["warnings"] = ["fixture warning", "nested warning"]
    evidence_preview["metadata"]["volume_state"]["missing"] = ["fixture missing", "nested warning"]
    content = report.render_market_report(evidence_preview, phase="preopen", now=NOW)
    before, bottom = content.split("## 資料品質與限制")
    for detail in ("fixture warning", "fixture missing", "nested warning"):
        assert detail not in before
        assert bottom.count(detail) == 1
    assert "資料品質：partial｜2 warnings｜2 missing" in before


def test_template_preserves_canonical_metadata(monkeypatch, evidence_preview):
    data = {key: value for key, value in evidence_preview["metadata"].items() if key not in {"stance", "freshness"}}
    envelope = {"kind": "market_overview", "as_of": evidence_preview["as_of"], "data": data,
                "freshness": {"status": "partial"}, "warnings": [], "missing": []}
    reader = Mock(return_value=envelope)
    monkeypatch.setattr(report.templates.tools, "read_market_overview", reader)
    db = Mock()
    preview = report.templates.build_market_overview_preview(db, market="tw")
    reader.assert_called_once_with(db=db, limit=8, market_data_params={"requested_capabilities": ["market.indices"]})
    for key, value in data.items():
        assert preview["metadata"][key] == value
    assert preview["metadata"]["freshness"] == envelope["freshness"]


def test_indices_request_does_not_suppress_other_canonical_readers(monkeypatch):
    # Exercise the real tools -> Taiwan overview domain selection. Only evidence
    # dependencies are fixtures; the requested-capability/domain routing is real.
    from app.ai.market_context import taiwan_market
    from app.db.models import Base

    tools = report.templates.tools
    monkeypatch.setattr(tools.market_service, "get_latest_trade_date", Mock(return_value=None))
    readers = {
        "cross_market": Mock(return_value={"status": "partial", "fixture_marker": "cross_market"}),
        "market_chips": Mock(return_value={"status": "partial", "fixture_marker": "market_chips"}),
        "volume_state": Mock(return_value={"status": "partial", "fixture_marker": "volume_state"}),
    }
    monkeypatch.setattr(tools.tw_cross_market, "read_tw_cross_market_context", readers["cross_market"])
    monkeypatch.setattr(tools.tw_market_chips, "read_tw_market_chips_context", readers["market_chips"])
    monkeypatch.setattr(tools, "read_taiwan_market_volume_state", readers["volume_state"])
    monkeypatch.setattr(taiwan_market, "_market_indices_capability", Mock(return_value={"items": [], "status": "missing"}))
    monkeypatch.setattr(taiwan_market, "_market_breadth_from_index_summary", Mock(return_value={}))
    monkeypatch.setattr(taiwan_market, "_market_index_intraday_pack", Mock(return_value={}))
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            preview = report.templates.build_market_overview_preview(db, market="tw")
        for key, reader in readers.items():
            reader.assert_called_once()
            assert preview["metadata"][key]["fixture_marker"] == key
            assert preview["metadata"][key]["status"] != "not_requested"
        taiwan_market._market_indices_capability.assert_called_once()
    finally:
        engine.dispose()


def test_renderer_rejects_invalid_phase_and_naive_time():
    with pytest.raises(ValueError):
        report.render_market_report({}, phase="invalid", now=NOW)
    with pytest.raises(ValueError):
        report.render_market_report({}, phase="preopen", now=NOW.replace(tzinfo=None))
