"""Market-owned cache reader and projection for Taiwan company profiles.

This is intentionally a compatibility seam: acquisition remains owned by the
existing dataset lifecycle while AI and other consumers stop querying the
storage model directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import RawFetchResult, SourceRegistry, StockProfile


@dataclass(frozen=True)
class TaiwanCompanyProfileRead:
    stock_id: str
    company_name: str | None
    market: str
    industry: str | None
    listed_date: date | None
    established_date: date | None
    paid_in_capital: int | None
    issued_shares: int | None
    report_date: date | None
    updated_at: datetime | None
    source_id: int
    raw_result_id: int
    source_name: str | None
    parser_version: str | None
    fetched_at: datetime | None
    content_hash: str | None
    lineage_complete: bool
    limitations: tuple[str, ...]


def read_taiwan_company_profile(
    db: Session,
    stock_id: str,
) -> TaiwanCompanyProfileRead | None:
    """Read one persisted profile without provider IO or mutation."""

    normalized_stock_id = str(stock_id or "").strip().upper()
    if not normalized_stock_id:
        raise ValueError("stock_id is required")
    row = (
        db.query(StockProfile, RawFetchResult, SourceRegistry)
        .outerjoin(RawFetchResult, RawFetchResult.id == StockProfile.raw_result_id)
        .outerjoin(SourceRegistry, SourceRegistry.id == StockProfile.source_id)
        .filter(StockProfile.stock_id == normalized_stock_id)
        .first()
    )
    if row is None:
        return None
    profile, raw, source = row
    lineage_complete = bool(
        raw is not None
        and source is not None
        and raw.source_id == profile.source_id == source.id
        and raw.id == profile.raw_result_id
        and raw.content_hash
        and raw.parser_version
        and raw.fetched_at
    )
    limitations = (
        ()
        if lineage_complete
        else ("TW_COMPANY_PROFILE_CANONICAL_LINEAGE_INCOMPLETE",)
    )
    return TaiwanCompanyProfileRead(
        stock_id=profile.stock_id,
        company_name=profile.company_name,
        market=profile.market,
        industry=profile.industry,
        listed_date=profile.listed_date,
        established_date=profile.established_date,
        paid_in_capital=profile.paid_in_capital,
        issued_shares=profile.issued_shares,
        report_date=profile.report_date,
        updated_at=profile.updated_at,
        source_id=profile.source_id,
        raw_result_id=profile.raw_result_id,
        source_name=source.source_name if source is not None else None,
        parser_version=raw.parser_version if raw is not None else None,
        fetched_at=raw.fetched_at if raw is not None else None,
        content_hash=raw.content_hash if raw is not None else None,
        lineage_complete=lineage_complete,
        limitations=limitations,
    )


def _json_value(value: Any) -> Any:
    isoformat = getattr(value, "isoformat", None)
    return isoformat() if callable(isoformat) else value


def project_taiwan_company_profile(
    stock: Any,
    profile: TaiwanCompanyProfileRead | None,
) -> dict[str, Any]:
    """Project the stable Taiwan company-profile consumer contract."""

    stock_id = str(getattr(stock, "stock_id", "") or "").strip() or None
    stock_name = getattr(stock, "stock_name", None)
    company_name = getattr(profile, "company_name", None) or stock_name
    market = (
        getattr(profile, "market", None)
        or getattr(stock, "market", None)
        or "TW"
    )
    payload = {
        "stock_id": stock_id,
        "stock_name": stock_name,
        "company_name": company_name,
        "market": market,
        "exchange": market,
        "instrument_type": getattr(stock, "instrument_type", None),
        "industry": (
            getattr(profile, "industry", None)
            or getattr(stock, "industry", None)
        ),
        "category": getattr(stock, "category", None),
        "listed_date": _json_value(getattr(profile, "listed_date", None)),
        "established_date": _json_value(
            getattr(profile, "established_date", None)
        ),
        "paid_in_capital": getattr(profile, "paid_in_capital", None),
        "issued_shares": getattr(profile, "issued_shares", None),
        "is_active": getattr(stock, "is_active", None),
        "currency": "TWD",
        "source": (
            "stock_master+stock_profile"
            if profile is not None
            else "stock_master"
        ),
        "as_of": _json_value(
            getattr(profile, "updated_at", None)
            or getattr(stock, "updated_at", None)
            or getattr(stock, "last_seen_at", None)
        ),
        "source_name": getattr(profile, "source_name", None),
        "raw_result_id": getattr(profile, "raw_result_id", None),
        "lineage_complete": bool(
            profile is not None and getattr(profile, "lineage_complete", False)
        ),
        "limitations": list(getattr(profile, "limitations", ()) or ()),
    }
    important_fields = (
        "stock_id",
        "stock_name",
        "company_name",
        "market",
        "instrument_type",
        "industry",
        "listed_date",
        "issued_shares",
    )
    missing_fields = [
        field for field in important_fields if payload.get(field) is None
    ]
    payload["missing_fields"] = missing_fields
    payload["status"] = (
        "missing"
        if stock is None
        else "partial"
        if missing_fields
        else "ready"
    )
    return payload


__all__ = [
    "TaiwanCompanyProfileRead",
    "project_taiwan_company_profile",
    "read_taiwan_company_profile",
]
