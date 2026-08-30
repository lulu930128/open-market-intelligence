"""One US-owned eligibility specification for persisted Daily candidates."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import or_

from app.db.models import RawFetchResult, SourceRegistry, USDailyPrice
from app.market_data.contracts import AuthorityClass, BarFinalization, InstrumentType
from app.us_market.market_data.descriptors import US_DAILY_CANDIDATE_DESCRIPTORS


US_DAILY_REGISTERED_PROVIDERS = tuple(
    descriptor.provider_key for descriptor in US_DAILY_CANDIDATE_DESCRIPTORS
)


@dataclass(frozen=True, slots=True)
class USDailyEligibilityIssue:
    reason_code: str
    missing_fields: tuple[str, ...] = ()


def us_daily_candidate_issue(
    row: USDailyPrice,
    raw: RawFetchResult | None,
    source: SourceRegistry | None,
    *,
    instrument_type: InstrumentType,
) -> USDailyEligibilityIssue | None:
    fields = (
        "source_id",
        "raw_result_id",
        "authority",
        "raw_contract_version",
        "event_at",
        "finalization",
        "price_basis",
        "volume_status",
    )
    missing = [name for name in fields if getattr(row, name) in (None, "")]
    if raw is None:
        missing.append("raw_receipt")
    if source is None:
        missing.append("source")
    for name in ("open_price", "high_price", "low_price", "close_price"):
        if getattr(row, name) is None:
            missing.append(name)
    if missing:
        return USDailyEligibilityIssue(
            "US_DAILY_LINEAGE_INCOMPLETE",
            tuple(dict.fromkeys(missing)),
        )

    source_name = str(source.source_name).strip()
    if (
        str(source.source_type or "").strip().lower() == "compatibility_adapter"
        or source_name.lower().startswith("legacy_compat.")
        or "legacy_compat" in str(row.raw_contract_version).lower()
    ):
        return USDailyEligibilityIssue("US_DAILY_LEGACY_COMPAT_LINEAGE_REJECTED")
    provider = str(row.provider or "").strip().lower()
    if provider not in US_DAILY_REGISTERED_PROVIDERS:
        return USDailyEligibilityIssue("US_DAILY_PROVIDER_UNREGISTERED")
    if raw.source_id != row.source_id or raw.source_id != source.id:
        return USDailyEligibilityIssue("US_DAILY_SOURCE_RECEIPT_MISMATCH")
    if raw.parser_version is None or not (
        row.raw_contract_version == raw.parser_version
        or str(row.raw_contract_version).startswith(f"{raw.parser_version}+")
    ):
        return USDailyEligibilityIssue("US_DAILY_PARSER_CONTRACT_MISMATCH")
    if raw.content_hash != row.raw_payload_hash:
        return USDailyEligibilityIssue("US_DAILY_CONTENT_HASH_MISMATCH")
    if instrument_type is InstrumentType.INDEX:
        valid_volume = (
            row.volume_status == "not_applicable"
            and row.trade_volume is None
            and row.volume_unit is None
        )
    else:
        valid_volume = (
            row.volume_status == "observed"
            and row.trade_volume is not None
            and row.trade_volume >= 0
            and row.volume_unit == "shares"
        )
    if not valid_volume:
        return USDailyEligibilityIssue("INVALID_CANONICAL_BAR")
    return None


def us_daily_sql_eligibility_filters(
    *,
    instrument_type: InstrumentType,
) -> tuple:
    """Return the SQL-safe portion of the same canonical eligibility spec."""

    filters = (
        USDailyPrice.source_id.isnot(None),
        USDailyPrice.raw_result_id.isnot(None),
        RawFetchResult.id.isnot(None),
        SourceRegistry.id.isnot(None),
        USDailyPrice.authority.in_(tuple(item.value for item in AuthorityClass)),
        USDailyPrice.raw_contract_version.isnot(None),
        USDailyPrice.event_at.isnot(None),
        USDailyPrice.finalization.in_(
            (BarFinalization.FINAL.value, BarFinalization.CORRECTED.value)
        ),
        USDailyPrice.price_basis.in_(("raw", "adjusted", "provider_default")),
        USDailyPrice.provider.in_(US_DAILY_REGISTERED_PROVIDERS),
        RawFetchResult.source_id == USDailyPrice.source_id,
        RawFetchResult.parser_version.isnot(None),
        or_(
            USDailyPrice.raw_contract_version == RawFetchResult.parser_version,
            USDailyPrice.raw_contract_version.like(
                RawFetchResult.parser_version + "+%"
            ),
        ),
        RawFetchResult.content_hash == USDailyPrice.raw_payload_hash,
        or_(
            SourceRegistry.source_type.is_(None),
            SourceRegistry.source_type != "compatibility_adapter",
        ),
        ~SourceRegistry.source_name.ilike("legacy_compat.%"),
        ~USDailyPrice.raw_contract_version.ilike("%legacy_compat%"),
        USDailyPrice.open_price.isnot(None),
        USDailyPrice.high_price.isnot(None),
        USDailyPrice.low_price.isnot(None),
        USDailyPrice.close_price.isnot(None),
        USDailyPrice.open_price > 0,
        USDailyPrice.high_price > 0,
        USDailyPrice.low_price > 0,
        USDailyPrice.close_price > 0,
        USDailyPrice.high_price >= USDailyPrice.open_price,
        USDailyPrice.high_price >= USDailyPrice.close_price,
        USDailyPrice.high_price >= USDailyPrice.low_price,
        USDailyPrice.low_price <= USDailyPrice.open_price,
        USDailyPrice.low_price <= USDailyPrice.close_price,
    )
    if instrument_type is InstrumentType.INDEX:
        return filters + (
            USDailyPrice.volume_status == "not_applicable",
            USDailyPrice.trade_volume.is_(None),
            USDailyPrice.volume_unit.is_(None),
        )
    return filters + (
        USDailyPrice.volume_status == "observed",
        USDailyPrice.trade_volume.isnot(None),
        USDailyPrice.trade_volume >= 0,
        USDailyPrice.volume_unit == "shares",
    )


__all__ = [
    "US_DAILY_REGISTERED_PROVIDERS",
    "USDailyEligibilityIssue",
    "us_daily_candidate_issue",
    "us_daily_sql_eligibility_filters",
]
