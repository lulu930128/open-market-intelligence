"""Durable cache-only owner for the Taiwan market-index directory."""

from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
from typing import Any, Iterable

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.db.models import (
    RawFetchResult,
    SourceRegistry,
    TaiwanMarketIndexDirectoryItem,
    TaiwanMarketIndexDirectorySnapshot,
)
from app.market.trading_calendar import TAIWAN_TZ
from app.market_data.contracts import AuthorityClass


TW_INDEX_DIRECTORY_DATASET_ID = "tw.market_index.directory"
TW_INDEX_DIRECTORY_CAPABILITY_ID = "market.index.directory"
TW_INDEX_DIRECTORY_CONTRACT_VERSION = "tw.market_index.directory.v1"
TW_INDEX_DIRECTORY_STALE_AFTER_SECONDS = 900


_SOURCE_CONFIG = {
    "TWSE": {
        "provider": "twse",
        "source": "twse_openapi_mi_index",
        "parser_version": "twse.openapi.mi_index.v1",
        "endpoint_url": "https://openapi.twse.com.tw/v1/exchangeReport/MI_INDEX",
    },
    "TPEX": {
        "provider": "tpex",
        "source": "tpex_official_index_directory",
        "parser_version": "tpex.index_directory.composite.v1",
        "endpoint_url": None,
    },
}


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _normalize_item(item: dict[str, Any], *, market: str, rank: int) -> dict[str, Any]:
    name = str(item.get("name") or "").strip()
    if not name:
        raise ValueError("index directory item requires name")
    item_market = str(item.get("market") or market).strip().upper()
    if item_market != market:
        raise ValueError("index directory item crossed market")
    trade_date = item.get("trade_date")
    if isinstance(trade_date, str):
        trade_date = date.fromisoformat(trade_date)
    if trade_date is not None and not isinstance(trade_date, date):
        raise ValueError("index directory trade_date is invalid")
    return {
        "rank": rank,
        "market": market,
        "name": name,
        "close": float(item["close"]) if item.get("close") is not None else None,
        "change": float(item["change"]) if item.get("change") is not None else None,
        "change_pct": (
            float(item["change_pct"])
            if item.get("change_pct") is not None
            else None
        ),
        "trade_date": trade_date,
    }


def _missing_projection(market: str, *, limitation: str) -> dict[str, Any]:
    return {
        "contract_version": TW_INDEX_DIRECTORY_CONTRACT_VERSION,
        "status": "missing",
        "freshness_status": "missing",
        "market": market,
        "source": "unavailable",
        "as_of": None,
        "count": 0,
        "items": [],
        "warnings": [limitation],
    }


class TaiwanIndexDirectoryRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def read(
        self,
        *,
        market: str,
        limit: int,
        requested_at: datetime | None = None,
    ) -> dict[str, Any]:
        normalized_market = str(market or "").strip().upper()
        if normalized_market not in _SOURCE_CONFIG:
            raise ValueError("market must be one of: TWSE, TPEX.")
        if limit <= 0:
            raise ValueError("limit must be greater than 0.")
        bind = self._db.get_bind()
        inspector = inspect(bind)
        if not inspector.has_table(TaiwanMarketIndexDirectorySnapshot.__tablename__):
            return _missing_projection(
                normalized_market,
                limitation="TW_INDEX_DIRECTORY_SCHEMA_UNAVAILABLE",
            )
        snapshot = (
            self._db.query(TaiwanMarketIndexDirectorySnapshot)
            .filter(TaiwanMarketIndexDirectorySnapshot.market == normalized_market)
            .filter(
                TaiwanMarketIndexDirectorySnapshot.observation_state.in_(
                    ("available", "partial")
                )
            )
            .order_by(
                TaiwanMarketIndexDirectorySnapshot.fetched_at.desc(),
                TaiwanMarketIndexDirectorySnapshot.id.desc(),
            )
            .first()
        )
        if snapshot is None:
            return _missing_projection(
                normalized_market,
                limitation="TW_INDEX_DIRECTORY_CANONICAL_CACHE_MISSING",
            )
        items = (
            self._db.query(TaiwanMarketIndexDirectoryItem)
            .filter(TaiwanMarketIndexDirectoryItem.snapshot_id == snapshot.id)
            .order_by(TaiwanMarketIndexDirectoryItem.rank.asc())
            .limit(limit)
            .all()
        )
        now = requested_at or datetime.now(TAIWAN_TZ)
        fetched_at = _aware_utc(snapshot.fetched_at)
        age_seconds = max((now.astimezone(timezone.utc) - fetched_at).total_seconds(), 0)
        stale = age_seconds > TW_INDEX_DIRECTORY_STALE_AFTER_SECONDS
        try:
            decoded_limitations = json.loads(snapshot.limitations_json or "[]")
            limitations = (
                [str(value) for value in decoded_limitations]
                if isinstance(decoded_limitations, list)
                else ["TW_INDEX_DIRECTORY_LIMITATIONS_MALFORMED"]
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            limitations = ["TW_INDEX_DIRECTORY_LIMITATIONS_MALFORMED"]
        if stale:
            limitations.append("TW_INDEX_DIRECTORY_STALE")
        status = "stale" if stale else snapshot.observation_state
        return {
            "contract_version": TW_INDEX_DIRECTORY_CONTRACT_VERSION,
            "status": status,
            "freshness_status": "stale" if stale else "fresh",
            "market": normalized_market,
            "source": snapshot.source,
            "as_of": snapshot.fetched_at,
            "count": len(items),
            "items": [
                {
                    "rank": item.rank,
                    "market": item.market,
                    "name": item.name,
                    "close": item.close_value,
                    "change": item.price_change,
                    "change_pct": item.change_pct,
                    "trade_date": item.trade_date,
                }
                for item in items
            ],
            "warnings": list(dict.fromkeys(str(value) for value in limitations)),
        }


class TaiwanIndexDirectoryTransaction:
    def __init__(self, db: Session) -> None:
        self._db = db

    def persist(
        self,
        *,
        market: str,
        items: Iterable[dict[str, Any]],
        fetched_at: datetime,
        raw_payload: object,
    ) -> dict[str, Any]:
        normalized_market = str(market or "").strip().upper()
        config = _SOURCE_CONFIG.get(normalized_market)
        if config is None:
            raise ValueError("market must be one of: TWSE, TPEX.")
        normalized_items = [
            _normalize_item(item, market=normalized_market, rank=index)
            for index, item in enumerate(items, start=1)
        ]
        if not normalized_items:
            raise ValueError("index directory refresh produced no items")
        normalized_names = [item["name"] for item in normalized_items]
        if len(set(normalized_names)) != len(normalized_names):
            raise ValueError("index directory refresh produced duplicate names")
        if not any(
            item["close"] is not None or item["trade_date"] is not None
            for item in normalized_items
        ):
            raise ValueError(
                "index directory refresh produced no authoritative observations"
            )
        directory_payload = {
            "contract_version": TW_INDEX_DIRECTORY_CONTRACT_VERSION,
            "market": normalized_market,
            "items": [
                {
                    **item,
                    "trade_date": (
                        item["trade_date"].isoformat()
                        if item["trade_date"] is not None
                        else None
                    ),
                }
                for item in normalized_items
            ],
        }
        directory_text = json.dumps(
            directory_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        content_hash = hashlib.sha256(directory_text.encode("utf-8")).hexdigest()
        raw_text = json.dumps(
            raw_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        raw_content_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
        partial = any(item["close"] is None for item in normalized_items)
        limitations = ["TW_INDEX_DIRECTORY_ITEMS_PARTIAL"] if partial else []
        try:
            source = (
                self._db.query(SourceRegistry)
                .filter(SourceRegistry.source_name == config["source"])
                .first()
            )
            if source is None:
                source = SourceRegistry(
                    source_name=config["source"],
                    source_type="api",
                    category="market_data",
                    endpoint_url=config["endpoint_url"],
                    enabled=True,
                    priority=10,
                    parser_type=config["parser_version"],
                    auth_type="none",
                    reliability_level=AuthorityClass.EXCHANGE.value,
                )
                self._db.add(source)
                self._db.flush()
            fetched_at_utc = _aware_utc(fetched_at)
            source.last_success_at = fetched_at_utc
            raw = RawFetchResult(
                source_id=source.id,
                fetched_at=fetched_at_utc,
                url=config["endpoint_url"],
                method="GET",
                status_code=200,
                content_type="application/json",
                content_hash=raw_content_hash,
                raw_text=raw_text,
                parser_version=config["parser_version"],
            )
            self._db.add(raw)
            self._db.flush()
            snapshot = TaiwanMarketIndexDirectorySnapshot(
                source_id=source.id,
                raw_result_id=raw.id,
                provider=config["provider"],
                source=config["source"],
                authority=AuthorityClass.EXCHANGE.value,
                raw_contract_version=config["parser_version"],
                market=normalized_market,
                fetched_at=fetched_at_utc,
                content_hash=content_hash,
                item_count=len(normalized_items),
                observation_state="partial" if partial else "available",
                limitations_json=json.dumps(limitations),
            )
            self._db.add(snapshot)
            self._db.flush()
            self._db.add_all(
                [
                    TaiwanMarketIndexDirectoryItem(
                        snapshot_id=snapshot.id,
                        rank=item["rank"],
                        market=item["market"],
                        name=item["name"],
                        close_value=item["close"],
                        price_change=item["change"],
                        change_pct=item["change_pct"],
                        trade_date=item["trade_date"],
                    )
                    for item in normalized_items
                ]
            )
            self._db.commit()
        except Exception:
            self._db.rollback()
            raise
        return TaiwanIndexDirectoryRepository(self._db).read(
            market=normalized_market,
            limit=len(normalized_items),
            requested_at=fetched_at,
        )


def read_taiwan_index_directory(
    db: Session,
    *,
    market: str,
    limit: int = 80,
    requested_at: datetime | None = None,
) -> dict[str, Any]:
    return TaiwanIndexDirectoryRepository(db).read(
        market=market,
        limit=limit,
        requested_at=requested_at,
    )


__all__ = [
    "TW_INDEX_DIRECTORY_CAPABILITY_ID",
    "TW_INDEX_DIRECTORY_CONTRACT_VERSION",
    "TW_INDEX_DIRECTORY_DATASET_ID",
    "TW_INDEX_DIRECTORY_STALE_AFTER_SECONDS",
    "TaiwanIndexDirectoryRepository",
    "TaiwanIndexDirectoryTransaction",
    "read_taiwan_index_directory",
]
