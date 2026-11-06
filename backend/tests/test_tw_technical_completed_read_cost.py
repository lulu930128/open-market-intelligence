"""Completed-session evidence avoids redundant forming reads, never gaps."""
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.market import technical_evidence
from app.market.technical_parameters import get_technical_analysis_parameters
from test_tw_technical_service import _series, _series_with_current_partial


@pytest.mark.parametrize("session_offset", [0, 1])
def test_completed_daily_session_reuses_evidence_but_missing_session_still_reads(monkeypatch, session_offset):
    series = _series(count=80)
    series = series.model_copy(update={"bars": tuple(
        bar.model_copy(update={"end_at": bar.start_at + timedelta(hours=13, minutes=30)})
        for bar in series.bars
    )})
    session_date = series.bars[-1].start_at.date() + timedelta(days=session_offset)
    reads = Mock(return_value=series)
    monkeypatch.setattr(technical_evidence, "TaiwanBarService", lambda db: SimpleNamespace(read_bars=reads))
    monkeypatch.setattr(technical_evidence, "taiwan_presentation_session", lambda now: {"trade_date": session_date})
    monkeypatch.setattr(technical_evidence, "get_technical_analysis_parameters",
                        lambda: get_technical_analysis_parameters(persisted_settings={}))
    result = technical_evidence.build_tw_stock_technical_evidence(
        db=object(), stock_id="2330", requested_capabilities={"technical.indicators"},
        corporate_event_history={},
    )
    assert reads.call_count == (3 if session_offset == 0 else 4)
    daily = result["indicators"]["timeframes"]["daily"]
    assert daily["completed"]["close"] == float(series.bars[-1].close_price)
    assert daily["current_partial"] is None
    assert daily["decision_usable"] is False  # Unknown corporate history stays unknown.


def test_equal_length_rolling_window_keeps_current_partial_separate_from_completed(monkeypatch):
    def intraday_end(series):
        return series.model_copy(update={"bars": tuple(
            bar.model_copy(update={"end_at": bar.start_at + timedelta(hours=13, minutes=30)})
            for bar in series.bars
        )})
    completed = intraday_end(_series(count=80))
    forming = intraday_end(_series_with_current_partial())
    forming = forming.model_copy(update={"bars": forming.bars[1:], "bar_states": forming.bar_states[1:]})
    assert len(forming.bars) == len(completed.bars)
    reads = Mock(side_effect=lambda **kw: forming if kw.get("include_partial") else completed)
    monkeypatch.setattr(technical_evidence, "TaiwanBarService", lambda db: SimpleNamespace(read_bars=reads))
    monkeypatch.setattr(technical_evidence, "taiwan_presentation_session",
                        lambda now: {"trade_date": forming.bars[-1].start_at.date()})
    monkeypatch.setattr(technical_evidence, "get_technical_analysis_parameters",
                        lambda: get_technical_analysis_parameters(persisted_settings={}))
    result = technical_evidence.build_tw_stock_technical_evidence(
        db=object(), stock_id="2330", requested_capabilities={"technical.indicators"},
        corporate_event_history={},
    )
    daily = result["indicators"]["timeframes"]["daily"]
    partial = daily["current_partial"]
    assert partial is not None
    assert partial["close"] == float(forming.bars[-1].close_price)
    assert partial["time"] == forming.bars[-1].start_at.date()
    assert partial["decision_usable"] is False
    assert partial["volume_based_observation_usable"] is False
    assert partial["volume"] is None
    assert partial["indicator_semantics"]["volume_based"] == "not_applicable_to_current_partial"
    assert daily["completed"]["close"] == float(completed.bars[-1].close_price)
    assert daily["completed"]["time"] == completed.bars[-1].start_at.date()
