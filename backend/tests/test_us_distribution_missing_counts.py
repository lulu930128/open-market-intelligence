"""Unmaterialized market evidence is unknown, not an observed zero universe."""
from datetime import datetime, timezone

from app.ai.market_context.us_distribution import merge_us_distribution_context
from app.us_market.sector_distribution import read_us_sector_distribution
from test_us_sector_distribution import db  # noqa: F401


def test_missing_checkpoint_has_no_numeric_market_counts(db):
    snapshot = read_us_sector_distribution(db, now=datetime(2026, 11, 5, 19, tzinfo=timezone.utc))
    assert snapshot.schema_version == "us.market.sector_distribution.v2"
    assert snapshot.status == "unavailable" and snapshot.counts is None
    assert snapshot.coverage["universe_count"] is None
    assert snapshot.coverage["evaluated_count"] == 0
    assert "UNIVERSE_COUNTS_UNKNOWN" in snapshot.limitations
    result = merge_us_distribution_context({}, snapshot, {"market.breadth"})
    evidence = result["data"]["breadth"]
    assert evidence["counts"] is None and evidence["facts_usable"] is False
    assert evidence["schema_version"] == "us.market.breadth.v2"


def test_missing_checkpoint_public_v4_preserves_unknown(db, monkeypatch):
    from app.ai import ask as ai_ask, ask_execution
    from app.ai.schemas import AiAskRequest
    snapshot = read_us_sector_distribution(db, now=datetime(2026, 11, 5, 19, tzinfo=timezone.utc))
    monkeypatch.setattr(ask_execution, "read_us_sector_distribution", lambda *a, **kw: snapshot)
    result = ai_ask.ask(db, AiAskRequest(
        question="美股市場廣度", contract_version="omi.decision.v4",
        target={"type": "market", "market": "US"}, mode="data_only", output="evidence_only",
        selection={"include": ["market.breadth"]}, realtime_policy="cache_only",
        allow_external_fetch=False, allow_write=False, allow_llm=False,
        refresh_policy={"mode": "off", "before_answer": False},
    ))
    assert result["evidence"]["data"]["market.breadth"]["counts"] is None
    assert result["status"]["readiness"]["decision_ready"] is False
