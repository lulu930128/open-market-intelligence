"""Bounded read-only Atlas integration; Atlas owns document and coverage semantics."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import urlparse
from urllib.parse import urlparse

import requests
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.orm import Session

from app.config import settings
from app.integrations import atlas_endpoint
from app.db.models import StockMaster
from app.stocks.service import StockNotFoundError

CAPABILITY_ID = "news.company_documents"
SCHEMA_VERSION = "omi.external.company_news.v1"
PROFILE = "company_news_stock_v1"
CONTRACT_VERSION = "1.2"
MAX_BYTES = 768 * 1024


class StockNewsRequestError(ValueError):
    """The upstream exact query rejected the caller's pagination input."""


class StockNewsItemRead(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)
    id: str = Field(min_length=1)
    document_type: Literal["news"]
    title: str = Field(min_length=1)
    canonical_url: str
    source_id: str = Field(min_length=1)
    source_attribution: str | None
    rights: dict[str, Any]
    companies: list[dict[str, Any]]


class StockNewsRead(BaseModel):
    schema_version: str = SCHEMA_VERSION
    status: Literal["available", "ready_empty", "unavailable", "disabled", "incompatible", "not_supported"]
    provider: str = "Open Intel Atlas"
    stock_id: str
    market: str
    stock: dict[str, Any] = Field(default_factory=dict)
    items: list[StockNewsItemRead] = Field(default_factory=list)
    contract_version: str = CONTRACT_VERSION
    profile: str = PROFILE
    generated_at: str
    atlas_generated_at: str | None = None
    freshness: dict[str, Any] = Field(default_factory=dict)
    coverage: dict[str, Any] = Field(default_factory=dict)
    warnings: list[Any] = Field(default_factory=list)
    pagination: dict[str, Any] = Field(default_factory=dict)
    reason_code: str | None = None
    returned_count: int = 0
    facts_usable: bool = False
    decision_usable: bool = False
    absence_interpretation: str = "unknown_not_observed"
    source_refs: list[dict[str, Any]] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=lambda: [
        "Atlas news Documents are supplemental evidence, not verified Events or trading signals.",
        "Preserve original titles, attribution, links and rights; no absence-of-news inference or automatic score changes.",
    ])


_local_base_url = atlas_endpoint.local_base_url
_fetch = atlas_endpoint.fetch_json


def read_stock_news(db: Session, stock_id: str, *, limit: int = 20, cursor: str | None = None) -> dict[str, Any]:
    # get_stock() can repair/backfill and commit; this endpoint is strictly read-only.
    with db.no_autoflush:
        stock = db.query(StockMaster).filter(StockMaster.stock_id == stock_id).first()
    if stock is None:
        raise StockNotFoundError(f"Stock {stock_id} not found")
    market = str(stock.market).upper()
    base = StockNewsRead(status="unavailable", stock_id=stock.stock_id, market=market,
                        generated_at=datetime.now(timezone.utc).isoformat()).model_dump()

    def failure(status: str, reason: str) -> dict[str, Any]:
        return {
            **base, "status": status, "reason_code": reason, "missing": [reason],
            "coverage": {
                "status": "missing" if reason == "atlas_stock_or_endpoint_not_found" else "unknown",
                "scope": "stock", "exchange": market, "symbol": stock.stock_id,
                "guarantee": "unknown", "reason_code": reason,
                "authority": "omi_bridge_availability",
                "decision_usable": False,
            },
        }

    if market not in {"TWSE", "TPEX"}:
        return failure("not_supported", "atlas_market_not_supported")
    if not re.fullmatch(r"[A-Z0-9]{4,12}", stock.stock_id):
        return failure("not_supported", "atlas_stock_identifier_not_supported")
    if not settings.omi_atlas_news_enabled:
        return failure("disabled", "atlas_news_disabled")
    url = _local_base_url(settings.omi_atlas_api_base_url)
    if not url:
        return failure("unavailable", "atlas_base_url_not_loopback")
    limit = max(1, min(int(limit), 50))
    try:
        code, payload = atlas_endpoint.request_json(f"/api/v1/stocks/{market}/{stock.stock_id}/news", {"limit": limit, "cursor": cursor}, fetch=_fetch)
    except atlas_endpoint.AtlasEndpointError as exc:
        return failure("unavailable", exc.reason)
    except requests.Timeout:
        return failure("unavailable", "atlas_timeout")
    except requests.RequestException:
        return failure("unavailable", "atlas_connection_unavailable")
    except (ValueError, UnicodeError, RecursionError):
        return failure("incompatible", "atlas_invalid_or_oversized_json")
    if code != 200:
        if code == 400:
            raise StockNewsRequestError("Atlas rejected the stock news query or cursor.")
        if code == 403:
            return failure("disabled", "atlas_content_usage_not_allowed")
        if code == 409:
            return failure("incompatible", "atlas_stock_identity_ambiguous")
        if code == 404:
            return failure("unavailable", "atlas_stock_or_endpoint_not_found")
        return failure("unavailable", f"atlas_http_{code}")
    try:
        if not isinstance(payload, dict) or payload.get("contract_version") != CONTRACT_VERSION or payload.get("profile") != PROFILE:
            return failure("incompatible", "atlas_contract_version_mismatch")
        identity = payload["stock"]
        if (identity["exchange"] != market or identity["symbol"] != stock.stock_id
                or not identity["company_id"] or not identity["security_id"]):
            return failure("incompatible", "atlas_stock_identity_mismatch")
        rows = payload["data"]
        if not isinstance(rows, list) or len(rows) > limit:
            raise ValueError("invalid items")
        items = [StockNewsItemRead.model_validate(row).model_dump() for row in rows]
        for item in items:
            if any(not isinstance(company.get("securities"), list) or any(
                not isinstance(security, dict) for security in company["securities"]
            ) for company in item["companies"]):
                return failure("incompatible", "atlas_document_identity_mismatch")
            if not any(company.get("id") == identity["company_id"] and any(
                security.get("id") == identity["security_id"] and security.get("exchange") == market
                and security.get("ticker") == stock.stock_id for security in company.get("securities", [])
            ) for company in item["companies"]):
                return failure("incompatible", "atlas_document_identity_mismatch")
            if not item["rights"] or (item["rights"].get("attribution_required") and not item["source_attribution"]):
                return failure("incompatible", "atlas_document_rights_missing")
            link = urlparse(item["canonical_url"])
            if link.scheme not in {"http", "https"} or not link.hostname or link.username or link.password:
                return failure("incompatible", "atlas_document_link_invalid")
        for key in ("freshness", "coverage", "pagination"):
            if not isinstance(payload[key], dict):
                raise ValueError(key)
        if not isinstance(payload["warnings"], list) or not isinstance(payload["generated_at"], str):
            raise ValueError("invalid metadata")
        if (payload["freshness"].get("status") not in {"current", "partial", "stale", "missing", "disabled", "failed", "unknown"}
                or payload["coverage"].get("status") not in {"current", "partial", "stale", "missing", "disabled", "failed", "unknown"}
                or payload["coverage"].get("scope") != "stock"
                or payload["coverage"].get("exchange") != market
                or payload["coverage"].get("symbol") != stock.stock_id
                or payload["pagination"].get("count") != len(items)
                or not isinstance(payload["pagination"].get("next_cursor"), (str, type(None)))):
            raise ValueError("invalid stock metadata")
        base.update(status="available" if items else "ready_empty", stock=identity, items=items,
                    returned_count=len(items), facts_usable=bool(items), atlas_generated_at=payload["generated_at"],
                    freshness=payload["freshness"], coverage=payload["coverage"], warnings=payload["warnings"],
                    pagination=payload["pagination"], source_refs=[{
                        "document_id": item["id"], "url": item["canonical_url"], "title": item["title"],
                        "provider": item["source_attribution"], "rights": item["rights"]
                    } for item in items])
        if not items:
            base["missing"] = ["No readable documents returned; target coverage does not establish absence of news."]
        return base
    except (KeyError, TypeError, ValueError, ValidationError):
        return failure("incompatible", "atlas_invalid_envelope")
