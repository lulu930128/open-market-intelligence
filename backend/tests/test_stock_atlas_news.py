from unittest.mock import patch

import pytest
import requests
from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.ai import ask as ai_ask
from app.ai import capability_contract
from app.ai.market_context import atlas_company_news
from app.ai.schemas import AiAskRequest
from app.config import settings
from app.db.models import Base, StockMaster
from app.routers.stocks import read_stock_company_news
from app.stocks import atlas_news


@pytest.fixture
def db():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([StockMaster(stock_id="2330", stock_name="台積電", market="TWSE", is_active=True),
                         StockMaster(stock_id="6488", stock_name="環球晶", market="TPEX", is_active=True)])
        session.commit()
        yield session
    engine.dispose()


def envelope():
    return {
        "contract_version": "1.2", "profile": "company_news_stock_v1", "generated_at": "2026-09-07T00:00:00Z",
        "stock": {"exchange": "TWSE", "symbol": "2330", "company_id": "company-2330", "security_id": "security-2330"},
        "data": [{"id": "document-1", "document_type": "news", "title": "原始新聞標題", "event_eligible": False,
                  "canonical_url": "https://example.test/news", "source_id": "yahoo-tw-stock-news", "source_attribution": "Yahoo股市",
                  "published_at": "2026-09-06T00:00:00Z", "observed_at": "2026-09-06T00:01:00Z",
                  "rights": {"usage_context": "personal_noncommercial", "requires_unmodified_display": True, "attribution_required": True},
                  "companies": [{"id": "company-2330", "securities": [{"id": "security-2330", "exchange": "TWSE", "ticker": "2330"}]}]}],
        "freshness": {"status": "stale", "as_of": "2026-09-06T00:01:00Z"},
        "coverage": {"scope": "stock", "exchange": "TWSE", "symbol": "2330", "status": "stale", "guarantee": "best_effort", "target_count": 1},
        "warnings": [{"code": "COMPANY_TARGET_STALE", "message": "Target stale"}],
        "pagination": {"count": 1, "next_cursor": None},
    }


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    monkeypatch.setattr(settings, "omi_atlas_news_enabled", True)
    monkeypatch.setattr(settings, "omi_atlas_endpoint_mode", "static")


def test_exact_identity_rights_and_read_only(db):
    writes = []
    def check(conn, cursor, statement, parameters, context, many):
        if statement.lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE", "REPLACE"}:
            writes.append(statement)
    event.listen(db.bind, "before_cursor_execute", check)
    payload = envelope()
    with patch.object(atlas_news, "_fetch", return_value=(200, payload)) as fetch:
        result = atlas_news.read_stock_news(db, "2330", limit=3)
    assert result["items"] == payload["data"]
    assert result["freshness"] == payload["freshness"]
    assert result["coverage"] == payload["coverage"]
    assert result["warnings"] == payload["warnings"]
    assert result["decision_usable"] is False
    assert fetch.call_args.args[0].endswith("/stocks/TWSE/2330/news")
    assert writes == []


@pytest.mark.parametrize("error,reason", [(requests.Timeout(), "atlas_timeout"), (requests.ConnectionError(), "atlas_connection_unavailable")])
def test_failure_isolated(db, error, reason):
    with patch.object(atlas_news, "_fetch", side_effect=error):
        result = atlas_news.read_stock_news(db, "2330")
    assert result["status"] == "unavailable"
    assert result["reason_code"] == reason
    assert result["items"] == []


@pytest.mark.parametrize("mutation", [
    lambda p: p.update(contract_version="0"),
    lambda p: p["stock"].update(symbol="2317"),
    lambda p: p["data"][0].update(companies=[]),
    lambda p: p["data"][0]["companies"][0].update(securities=[123]),
    lambda p: p["data"][0]["companies"][0].update(securities=None),
    lambda p: p["data"][0].update(rights=None),
    lambda p: p["data"][0].update(canonical_url="javascript:alert(1)"),
    lambda p: p.update(coverage=None),
    lambda p: p["coverage"].update(status="unsupported-status"),
])
def test_malformed_fails_closed(db, mutation):
    payload = envelope()
    mutation(payload)
    with patch.object(atlas_news, "_fetch", return_value=(200, payload)):
        assert atlas_news.read_stock_news(db, "2330")["status"] == "incompatible"


def test_missing_atlas_target_has_explicit_bridge_coverage(db):
    with patch.object(atlas_news, "_fetch", return_value=(404, {})):
        result = atlas_news.read_stock_news(db, "2330")
    assert result["coverage"]["status"] == "missing"
    assert result["coverage"]["symbol"] == "2330"
    assert result["coverage"]["decision_usable"] is False
    assert result["coverage"]["authority"] == "omi_bridge_availability"
    assert result["absence_interpretation"] == "unknown_not_observed"


def test_empty_disabled_and_non_loopback(db, monkeypatch):
    payload = envelope()
    payload["data"] = []
    payload["pagination"]["count"] = 0
    payload["coverage"].update(status="missing", target_count=0)
    with patch.object(atlas_news, "_fetch", return_value=(200, payload)):
        result = atlas_news.read_stock_news(db, "2330")
        assert result["status"] == "ready_empty"
        assert result["coverage"]["target_count"] == 0
        assert result["absence_interpretation"] == "unknown_not_observed"
    with patch.object(atlas_news, "_fetch") as fetch:
        monkeypatch.setattr(settings, "omi_atlas_news_enabled", False)
        assert atlas_news.read_stock_news(db, "2330")["status"] == "disabled"
        monkeypatch.setattr(settings, "omi_atlas_news_enabled", True)
        monkeypatch.setattr(settings, "omi_atlas_api_base_url", "http://example.test:80")
        assert atlas_news.read_stock_news(db, "2330")["reason_code"] == "atlas_base_url_not_loopback"
        fetch.assert_not_called()


def test_rest_contract(db):
    with patch.object(atlas_news, "_fetch", return_value=(200, envelope())):
        response = read_stock_company_news("2330", limit=20, cursor=None, db=db)
        assert atlas_news.StockNewsRead.model_validate(response).items[0].rights["requires_unmodified_display"]
        with pytest.raises(HTTPException) as error:
            read_stock_company_news("9999", limit=20, cursor=None, db=db)
        assert error.value.status_code == 404


def test_omi_ask_v4_reads_company_documents(db):
    with patch.object(atlas_news, "_fetch", return_value=(200, envelope())) as fetch:
        response = ai_ask.ask(db=db, payload=AiAskRequest(
            contract_version="omi.decision.v4", question="2330 的個股新聞文件有哪些？",
            target={"type": "tw_stock", "id": "2330", "market": "TW"},
            mode="data_only", output="evidence_only", realtime_policy="cache_only",
            allow_llm=False, allow_write=False, allow_external_fetch=False,
            selection={"include": ["target.identity", "news.company_documents"], "max_response_bytes": 65536},
        ), server_policy=ai_ask.AiAskServerPolicy())
    assert response["contract_version"] == "omi.decision.v4"
    news = response["evidence"]["data"]["news.company_documents"]
    assert news["items"][0]["title"] == "原始新聞標題"
    assert news["items"][0]["rights"]["requires_unmodified_display"] is True
    assert news["freshness"]["status"] == "stale"
    assert news["decision_usable"] is False
    fetch.assert_called_once()


def test_news_projection_preserves_whole_titles_and_company_context():
    payload = envelope()
    payload["data"][0]["title"] = "原" * 5000
    payload["data"][0]["companies"].append({"id": "other-company", "securities": []})
    context = {"items": payload["data"], "freshness": payload["freshness"], "coverage": payload["coverage"]}
    projected, _ = capability_contract.project_selected_data(
        response={"result": {"data": {"company_news": context}}},
        selection={"required": ["news.company_documents"], "optional": [], "fields": {}, "limits": {"news.company_documents": 1}},
    )
    assert projected["news.company_documents"] == context


def test_news_question_selection_preserves_explicit_intent():
    selection = atlas_company_news.selection_for_question({}, question="2330 個股新聞", scope_type="stock")
    assert "news.company_documents" in selection["optional"]
    for explicit in ({"include": ["quote.snapshot"]}, {"exclude": ["news.company_documents"]}):
        assert atlas_company_news.selection_for_question(explicit, question="2330 個股新聞", scope_type="stock") == explicit


def test_invalid_cursor_is_a_caller_error(db):
    with patch.object(atlas_news, "_fetch", return_value=(400, None)):
        with pytest.raises(HTTPException) as error:
            read_stock_company_news("2330", limit=20, cursor="wrong-stock", db=db)
        assert error.value.status_code == 400
