import asyncio
from datetime import datetime, timezone
import json
from unittest.mock import Mock

import pytest
from fastapi import FastAPI

from app.db.session import get_db
from app.market.indices import INDEX_CONFIGS
from app.routers import tw_market_indices


@pytest.mark.parametrize(
    "estimate_fields,expected",
    [
        ({"trade_value_is_estimate": None}, None),
        ({"trade_value_is_estimate": True}, True),
        ({"trade_value_is_estimate": False}, False),
        ({}, None),
    ],
    ids=["unknown", "estimated", "not-estimated", "legacy-missing-field"],
)
def test_summary_response_preserves_trade_value_estimate_state(
    monkeypatch, estimate_fields, expected
) -> None:
    """Unknown cached metadata must survive the actual HTTP response schema."""
    payload = {
        "as_of": datetime(2026, 9, 14, 14, 0, tzinfo=timezone.utc),
        "source": "shared_market_data_core",
        "cache_status": "canonical_cache",
        "indices": [
            {
                **config,
                "source": "unavailable",
                "breadth_status": {"status": "partial"},
                "breadth": {
                    "market": config["market"],
                    "status": "partial",
                    "advance_count": 1,
                    "decline_count": 0,
                    "unchanged_count": 0,
                    "total_count": 2,
                    "trade_value": None,
                    "trade_value_semantics": None,
                    **estimate_fields,
                },
            }
            for config in INDEX_CONFIGS
        ],
    }
    read_summary = Mock(return_value=payload)
    monkeypatch.setattr(tw_market_indices, "get_market_index_summary", read_summary)
    db = object()
    app = FastAPI()
    app.include_router(tw_market_indices.router, prefix="/api/market")
    app.dependency_overrides[get_db] = lambda: db

    messages = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    # Exercise FastAPI serialization without a live server or extra HTTP client.
    asyncio.run(app({
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/market/indices/summary",
        "query_string": b"",
        "headers": [],
    }, receive, send))

    start = next(message for message in messages if message["type"] == "http.response.start")
    assert start["status"] == 200
    read_summary.assert_called_once_with(db=db, force_refresh=False)
    body = json.loads(b"".join(
        message.get("body", b"")
        for message in messages if message["type"] == "http.response.body"
    ))
    assert body["cache_status"] == "canonical_cache"
    assert body["indices"]
    for index in body["indices"]:
        assert index["breadth"]["trade_value_is_estimate"] is expected
        assert index["breadth"]["trade_value"] is None
        assert index["breadth"]["trade_value_semantics"] is None
        assert index["breadth"]["status"] == "partial"
        assert index["breadth_status"]["status"] == "partial"
