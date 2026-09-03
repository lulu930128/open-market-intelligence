from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.jobs import taiwan_bar_bootstrap as subject
from app.market.tw_bar_contracts import TaiwanCurrentSessionSnapshotPhase


TAIPEI = timezone(timedelta(hours=8))


@pytest.mark.parametrize(
    ("phase", "expected_enqueues"),
    [
        (TaiwanCurrentSessionSnapshotPhase.WARMING, 1),
        (TaiwanCurrentSessionSnapshotPhase.READY, 0),
        (TaiwanCurrentSessionSnapshotPhase.DEGRADED, 0),
    ],
)
def test_viewer_warmup_enqueues_only_for_warming_current_session(
    monkeypatch: pytest.MonkeyPatch,
    phase: TaiwanCurrentSessionSnapshotPhase,
    expected_enqueues: int,
) -> None:
    db = object()
    requested_at = datetime(2026, 9, 1, 9, 5, tzinfo=TAIPEI)
    read_calls: list[dict[str, object]] = []
    enqueue_calls: list[dict[str, object]] = []
    run = SimpleNamespace(id="warmup-run")

    def read_current_session_bars(**kwargs):
        read_calls.append(kwargs)
        return SimpleNamespace(
            current_session_coverage=SimpleNamespace(snapshot_phase=phase)
        )

    monkeypatch.setattr(
        subject,
        "TaiwanBarService",
        lambda received_db: SimpleNamespace(
            read_current_session_bars=read_current_session_bars
        )
        if received_db is db
        else pytest.fail("warmup used another DB session"),
    )

    def enqueue(received_db, **kwargs):
        assert received_db is db
        enqueue_calls.append(kwargs)
        return run, True

    monkeypatch.setattr(subject, "enqueue_taiwan_intraday_bar_bootstrap", enqueue)

    result = subject.enqueue_taiwan_intraday_viewer_warmup(
        db,
        "2330",
        requested_at,
    )

    assert read_calls == [
        {
            "instrument_id": "2330",
            "interval": "1m",
            "limit": 1,
            "requested_at": requested_at,
        }
    ]
    assert len(enqueue_calls) == expected_enqueues
    if expected_enqueues:
        assert enqueue_calls == [
            {
                "symbols": ["2330"],
                "max_symbols": 1,
                "reuse_success_within_seconds": (
                    subject.TAIWAN_VIEWER_WARMUP_SUCCESS_REUSE_SECONDS
                ),
            }
        ]
        assert result == (run, True)
    else:
        assert result == (None, False)


def test_viewer_warmup_skips_non_trading_session_without_read_or_enqueue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        subject,
        "TaiwanBarService",
        lambda _db: pytest.fail("off-session warmup must not read chart coverage"),
    )
    monkeypatch.setattr(
        subject,
        "enqueue_taiwan_intraday_bar_bootstrap",
        lambda *_args, **_kwargs: pytest.fail("off-session warmup must not enqueue"),
    )

    result = subject.enqueue_taiwan_intraday_viewer_warmup(
        object(),
        "2330",
        datetime(2026, 9, 1, 8, 0, tzinfo=TAIPEI),
    )

    assert result == (None, False)


def test_viewer_warmup_requires_timezone_aware_requested_at() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        subject.enqueue_taiwan_intraday_viewer_warmup(
            object(),
            "2330",
            datetime(2026, 9, 1, 9, 5),
        )
