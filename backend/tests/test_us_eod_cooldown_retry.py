"""Real durable EOD admission/catalog/transaction, never external provider IO."""
from datetime import timedelta
import json

import pytest

from app.db.models import JobRun
from app.us_market import intraday_materializer as owner
from app.us_market.intraday_acquisition import USIntradayAcquisitionExecutor
from app.us_market.intraday_platform import USIntradayMarketPlatform
from app.us_market.market_data.descriptors import (
    TWELVE_INTRADAY_DESCRIPTOR, TWELVE_INTRADAY_RESOURCE_ID,
    YAHOO_INTRADAY_DESCRIPTOR, YAHOO_INTRADAY_RESOURCE_ID,
)
from test_us_forming_minute import sessions, BOUNDARY
from test_us_intraday_shared_core import _twelve_bars_payload, _yahoo_bars_payload


@pytest.mark.parametrize("third_complete", [True, False])
def test_two_incomplete_providers_then_bounded_cooldown_reuse(sessions, third_complete):
    calls = []
    end = BOUNDARY.replace(hour=16)
    first = BOUNDARY.replace(hour=21)
    def run(at):
        def factory(db):
            def fetch(route, requirement):
                # The original durable reservation must be committed before IO.
                with sessions() as inspect:
                    job = inspect.query(JobRun).filter_by(job_type="us.intraday_eod_obligation").one()
                    history = json.loads(job.request_json)["attempts"]
                    assert job.status == "running" and len(history) == len(calls) + 1
                    assert history[-1]["planned_resource"]["provider_key"] == route.provider_key
                calls.append(route.provider_key)
                count = 390 if len(calls) == 3 and third_complete else 389
                payload = (_twelve_bars_payload if route.provider_key == "twelve_data" else _yahoo_bars_payload)(end, count=count)
                return payload, "https://fixture.invalid/eod"
            return USIntradayMarketPlatform(db, acquisition=USIntradayAcquisitionExecutor(
                fetchers={TWELVE_INTRADAY_RESOURCE_ID: fetch, YAHOO_INTRADAY_RESOURCE_ID: fetch}, clock=lambda: at),
                bar_descriptors=(YAHOO_INTRADAY_DESCRIPTOR, TWELVE_INTRADAY_DESCRIPTOR))
        return owner.reconcile_us_intraday_session(configured_symbols="AAPL", trade_date=BOUNDARY.date(),
            now=at, max_external_calls=1, session_factory=sessions, platform_factory=factory)
    a = run(first)
    assert a["results"][0]["reason"] == "canonical_reread_incomplete"
    assert run(first + timedelta(minutes=1))["results"][0]["reason"] == "cooldown" and len(calls) == 1
    b = run(first + timedelta(minutes=15))
    assert b["results"][0]["reason"] == "canonical_reread_incomplete" and len(set(calls)) == 2
    c = run(first + timedelta(minutes=30))
    assert len(calls) == 3 and calls[2] == calls[0], c
    assert c["results"][0]["postcondition_satisfied"] is third_complete
    if not third_complete:
        assert c["results"][0]["unfillable_reason"] == "retry_budget_exhausted"
    d = run(first + timedelta(minutes=45))
    assert len(calls) == 3
    assert d["results"][0]["reason"] == ("canonical_cache_already_satisfied" if third_complete else "retry_budget_exhausted")
    with sessions() as db:
        attempts = json.loads(db.query(JobRun).filter_by(job_type="us.intraday_eod_obligation").one().request_json)["attempts"]
        assert len(attempts) == sum(a["external_call_reservation"] for a in attempts) == 3


@pytest.mark.parametrize("outcome,unknown,committed,expected", [
    ("canonical_reread_incomplete", False, True, "reserved"),
    ("unknown", True, None, "provider_already_reserved"),
    ("provider_error", False, True, "provider_already_reserved"),
    ("canonical_reread_failed", False, None, "provider_already_reserved"),
    ("canonical_reread_incomplete", True, True, "provider_already_reserved"),
    ("canonical_reread_incomplete", False, None, "provider_already_reserved"),
])
def test_durable_retry_requires_known_incomplete_and_keeps_accounting(sessions, outcome, unknown, committed, expected):
    from test_us_eod_durable import fixture_route, MISSING
    at = BOUNDARY.replace(hour=21)
    route = fixture_route()
    with sessions() as db:
        item = owner._eod_admit(db, symbol="AAPL", trade_date=BOUNDARY.date(), now=at,
            evidence=MISSING, allow_call=True, planned_resource=route)
        owner._eod_finish(db, {**item, "reason": outcome, "external_call_count_unknown": unknown,
            "external_call_count": None if unknown else 1, "persistence_committed": committed,
            "selected_resources": [{"provider": route.provider_key, "resource_id": route.resource_id}]}, now=at)
    with sessions() as db:
        later = owner._eod_admit(db, symbol="AAPL", trade_date=BOUNDARY.date(), now=at + timedelta(minutes=15),
            evidence=MISSING, allow_call=True, planned_resource=route)
        assert later["reason"] == expected and not later["postcondition_satisfied"]
        attempts = json.loads(db.get(JobRun, item["job_id"]).request_json)["attempts"]
        assert attempts[0]["external_call_reservation"] == 1
        assert attempts[0]["external_call_count_unknown"] is unknown
        assert len(attempts) == (2 if expected == "reserved" else 1)


def test_legacy_known_incomplete_is_revalidated_without_erasing_reservation(sessions):
    from test_us_eod_durable import fixture_route, MISSING
    at = BOUNDARY.replace(hour=21)
    route = fixture_route()
    with sessions() as db:
        item = owner._eod_admit(db, symbol="AAPL", trade_date=BOUNDARY.date(), now=at,
            evidence=MISSING, allow_call=True, planned_resource=route)
        job = db.get(JobRun, item["job_id"])
        request = json.loads(job.request_json)
        request["attempts"][0].update(outcome="canonical_reread_incomplete", error_type=None,
            acquisition_limitations=[], selected_resources=[{"provider": route.provider_key, "resource_id": route.resource_id}])
        job.request_json = json.dumps(request)
        job.status = "error"
        db.commit()
    with sessions() as db:
        later = owner._eod_admit(db, symbol="AAPL", trade_date=BOUNDARY.date(), now=at + timedelta(minutes=15),
            evidence=MISSING, allow_call=True, planned_resource=route)
        assert later["reason"] == "reserved" and later["attempt_count"] == 2
