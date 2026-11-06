"""Official price qualification is independent of complete market totals."""
from copy import deepcopy
from datetime import date
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.jobs import scheduler
from app.market import indices
from app.market.official_index_acquisition import TaiwanOfficialIndexAcquisitionExecutor
from app.market.official_index_platform import (
    TaiwanOfficialIndexCandidateReader, TaiwanOfficialIndexPlatform,
    read_taiwan_official_index,
)
from app.market.official_index_repository import TaiwanOfficialIndexRepository
from app.market.official_index_transaction import TaiwanOfficialIndexTransaction
from app.market.providers.tw_official_index import (
    TPEX_HIGHLIGHT_INDEX_DESCRIPTOR, TPEX_HIGHLIGHT_INDEX_RESOURCE_ID,
)
from app.market.tw_dashboard_data_core import attach_taiwan_dashboard_data_core
from app.market_data.contracts import ObservationState, ResolvedEvidenceStatus
from test_tw_index_close_lifecycle import _now, _published_summary
from test_tw_official_index_platform import FakeResponse, REQUESTED_AT, _refresh, db


DAY = date(2026, 8, 25)


def _payload():
    return {"stat": "ok", "date": "20260825", "tables": [{
        "date": "20260825", "fields": ["收市指數", "指數漲跌"],
        "data": [["389.41", "3.31"]],
    }]}


def _acquire(db, payload):
    fetch = Mock(return_value=FakeResponse(text=json.dumps(payload, ensure_ascii=False)))
    platform = TaiwanOfficialIndexPlatform(
        reader=TaiwanOfficialIndexCandidateReader(TaiwanOfficialIndexRepository(db)),
        transaction=TaiwanOfficialIndexTransaction(db),
        acquisition=TaiwanOfficialIndexAcquisitionExecutor(
            fetchers={TPEX_HIGHLIGHT_INDEX_RESOURCE_ID: fetch},
            clock=lambda: REQUESTED_AT, monotonic=lambda: 0.0),
        descriptors=(TPEX_HIGHLIGHT_INDEX_DESCRIPTOR,),
    )
    result = platform.refresh_index(_refresh(index_id="TPEX", trade_date=DAY))
    assert fetch.call_count == 1
    return result


def test_highlight_refresh_read_and_dashboard_confirm_price_keep_totals_partial(db):
    refresh = _acquire(db, _payload())
    assert refresh.persistence.committed and refresh.persistence.observations_written == 1
    assert not refresh.postcondition_satisfied
    result = read_taiwan_official_index(db, index_id="TPEX", trade_date=DAY, requested_at=REQUESTED_AT)
    assert result.acquisition.external_calls == 0
    health, observation = result.resolved.health, result.resolved.market_index
    assert health.status is ResolvedEvidenceStatus.PARTIAL
    assert health.facts_usable and not health.research_usable
    assert observation.state is ObservationState.PARTIAL
    assert observation.official and not observation.provisional
    assert observation.trade_volume is observation.trade_value is observation.transaction_count is None
    assert float(observation.close_value) == 389.41
    assert observation.lineage.raw_receipt_id == f"raw_fetch_result:{refresh.persistence.raw_result_ids[0]}"

    payload = attach_taiwan_dashboard_data_core(db, {"indices": [{"index_id": "TPEX"}]},
        requested_at=REQUESTED_AT, allow_universe_fallback=False)
    item = payload["indices"][0]
    assert item["official_close_status"] == "confirmed"
    assert item["official_close_price"] == 389.41
    component = item["data_core"]["official_index"]
    assert component["status"] == "partial"
    assert component["resolved_health"]["research_usable"] is False
    assert component["observation"]["trade_value"] is None


@pytest.mark.parametrize("defect", ["close", "change", "date", "table_date"])
def test_partial_allowance_does_not_accept_invalid_official_price(db, defect):
    payload = _payload()
    if defect in {"close", "change"}:
        payload["tables"][0]["data"][0][0 if defect == "close" else 1] = "--"
    else:
        payload["tables"][0]["date"] = "20260824"
        if defect == "date":
            payload["date"] = "20260824"
    refresh = _acquire(db, payload)
    assert not refresh.postcondition_satisfied
    assert refresh.result.resolved.market_index is None
    assert not refresh.result.resolved.health.facts_usable


def test_partial_index_totals_keep_reconciliation_pending_with_complete_published_breadth():
    payload = _published_summary()
    payload["indices"][1]["data_core"] = {"official_index": {"status": "partial"}}
    before = deepcopy(payload)
    assert indices.market_index_summary_needs_reconciliation(payload, now=_now(13, 41))
    assert payload == before


@pytest.mark.parametrize("partial", [True, False])
def test_scheduler_repairs_factual_partial_but_skips_complete_index(monkeypatch, partial):
    read = Mock(return_value=SimpleNamespace(resolved=SimpleNamespace(
        market_index=SimpleNamespace(trade_date=DAY),
        health=SimpleNamespace(facts_usable=True,
            status=ResolvedEvidenceStatus.PARTIAL if partial else ResolvedEvidenceStatus.SELECTED))))
    refresh = Mock(return_value=SimpleNamespace(postcondition_satisfied=False,
        persistence=SimpleNamespace(raw_result_ids=(1,))))
    monkeypatch.setattr(scheduler, "read_taiwan_official_index", read)
    monkeypatch.setattr(scheduler, "refresh_taiwan_official_index", refresh)
    result = scheduler._reconcile_taiwan_official_index_rows(Mock(), requested_at=REQUESTED_AT)
    assert refresh.call_count == (2 if partial else 0)
    assert {item["status"] for item in result} == ({"postcondition_unsatisfied"} if partial else {"already_current"})
