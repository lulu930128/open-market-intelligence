"""Read-only provider-reported classification over the canonical US universe."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.models import USCompanyProfile, USStockMaster
from app.us_market.catalog_store import us_common_stock_universe_filters
from app.us_market.daily_price_repository import _aware_utc


def _classification_label(value: str | None) -> str | None:
    if value is None or value.strip().lower() in {"", "none", "null", "n/a", "unknown", "-"}:
        return None
    return value.strip()  # Raw text is retained separately; no taxonomy mapping.


def read_us_classification(db: Session, *, now: datetime) -> dict:
    """Select exactly one current profile per symbol, including missing labels.

    Membership effective dates are not stored. This is a current-cache view,
    never a point-in-time taxonomy or an assertion of licensed GICS.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    with db.no_autoflush:
        symbols = [row.symbol for row in db.query(USStockMaster.symbol)
                   .filter(*us_common_stock_universe_filters()).order_by(USStockMaster.symbol).all()]
        rows = (db.query(USCompanyProfile.symbol, USCompanyProfile.provider,
                         USCompanyProfile.sector, USCompanyProfile.industry,
                         USCompanyProfile.fetched_at, USCompanyProfile.id,
                         USCompanyProfile.source_url, USCompanyProfile.raw_payload_hash)
                .join(USStockMaster, USStockMaster.symbol == USCompanyProfile.symbol)
                .filter(*us_common_stock_universe_filters())
                .filter(USCompanyProfile.fetched_at <= now.astimezone(timezone.utc))
                .order_by(USCompanyProfile.symbol, USCompanyProfile.fetched_at.desc(),
                          USCompanyProfile.provider.asc(), USCompanyProfile.id.desc()).all())
    def priority(row):
        valid = bool(_classification_label(row.sector) and _classification_label(row.industry))
        return (0 if row.provider == "alphavantage" and valid else
                1 if row.provider != "sec_edgar_sic" and valid else
                2 if valid else 3)

    # Stable sort retains fetched_at/provider/id tie order within each priority.
    # Never compose sector and industry from separate providers/taxonomies.
    rows.sort(key=priority)
    selected = {}
    for row in rows:
        if row.symbol in selected:
            continue
        selected[row.symbol] = {
            "symbol": row.symbol, "provider": row.provider,
            "sector": _classification_label(row.sector),
            "industry": _classification_label(row.industry),
            "raw_sector": row.sector, "raw_industry": row.industry,
            "fetched_at": _aware_utc(row.fetched_at).isoformat(),
            "effective_date": None, "effective_date_status": "unknown",
            "taxonomy": "SIC" if row.provider == "sec_edgar_sic" else "provider_reported",
            "profile_id": row.id, "source_url": row.source_url,
            "raw_payload_hash": row.raw_payload_hash,
        }
    total = len(symbols)
    sector = sum(item["sector"] is not None for item in selected.values())
    industry = sum(item["industry"] is not None for item in selected.values())
    both = sum(item["sector"] is not None and item["industry"] is not None for item in selected.values())
    latest = max((item["fetched_at"] for item in selected.values()), default=None)
    return {
        "symbols": symbols, "profiles": selected,
        "coverage": {
            "taxonomy_id": "us_company_profile.provider_reported",
            "taxonomy_version": f"us_company_profile.provider_reported.v1@{latest or 'empty'}",
            "source_scope": "provider_reported_company_profile",
            "selection_rule": "valid_alphavantage_then_valid_other_then_sec_sic_then_incomplete;fetched_at_desc_provider_asc_id_desc",
            "taxonomies": sorted({item["taxonomy"] for item in selected.values()}),
            "observed_universe_count": total, "profile_count": len(selected),
            "mapped_count": both, "sector_count": sector, "industry_count": industry,
            "unknown_count": total - both, "sector_unknown_count": total - sector,
            "industry_unknown_count": total - industry,
            "coverage_ratio": both / total if total else None,
            "sector_coverage_ratio": sector / total if total else None,
            "industry_coverage_ratio": industry / total if total else None,
            "as_of": latest, "effective_date": None, "effective_date_status": "unknown",
            "universe_complete": total > 0 and both == total, "decision_usable": False,
            "reason_codes": (["SIC_AND_PROVIDER_TAXONOMIES_NOT_EQUIVALENT"]
                             if any(item["taxonomy"] == "SIC" for item in selected.values())
                             else ["STANDARD_TAXONOMY_NOT_CONFIGURED"]) + ["EFFECTIVE_MEMBERSHIP_DATE_UNKNOWN"],
        },
    }
