"""Pure, bounded daily comparison before any KR consumer cutover."""

from decimal import Decimal

from app.kr_market.daily_ohlcv_platform import KRDailyResult
from app.kr_market.trading_calendar import KR_MARKET_TIMEZONE
from app.market_data.comparison import CanonicalComparisonResult, CanonicalMismatch, MismatchCategory


def compare_daily_result(canonical: KRDailyResult, *, legacy_records) -> dict:
    """Compare exact-provider input; empty, truncated or mixed inputs never pass."""
    legacy = tuple(legacy_records)
    bars = canonical.result.resolved.bars
    provider = canonical.projection["selected_provider"]
    if not legacy or not bars:
        return {"status": "limited", "matched": False, "reason": "KR_SHADOW_EVIDENCE_MISSING"}
    if len(legacy) > 16 or len(bars) > 16:
        return {"status": "limited", "matched": False, "reason": "KR_SHADOW_BOUND_EXCEEDED"}
    if any(row.provider != provider or row.symbol != canonical.identity.yahoo_symbol for row in legacy):
        return {"status": "limited", "matched": False, "reason": "KR_SHADOW_IDENTITY_MISMATCH"}
    by_date = {row.trade_date: row for row in legacy}
    if len(by_date) != len(legacy):
        return {"status": "limited", "matched": False, "reason": "KR_SHADOW_DUPLICATE_DATE"}
    current = {bar.end_at.astimezone(KR_MARKET_TIMEZONE).date(): bar for bar in bars}
    mismatches = []
    compared = 0
    for day in sorted(set(by_date) | set(current)):
        old, new = by_date.get(day), current.get(day)
        if old is None or new is None:
            compared += 1
            mismatches.append(CanonicalMismatch(category=MismatchCategory.TIME, field="trade_date",
                reason_code="KR_SHADOW_DATE_COVERAGE_MISMATCH",
                legacy_value=day.isoformat() if old else None, canonical_value=day.isoformat() if new else None))
            continue
        for field in ("open_price", "high_price", "low_price", "close_price", "trade_volume"):
            left = getattr(old, field)
            right = (new.volume.value if new.volume else None) if field == "trade_volume" else getattr(new, field)
            compared += 1
            equal = left is None and right is None or left is not None and right is not None and Decimal(str(left)) == right
            if not equal:
                mismatches.append(CanonicalMismatch(
                    category=MismatchCategory.VOLUME_UNIT if field == "trade_volume" else MismatchCategory.PRICE,
                    field=field, reason_code="KR_SHADOW_VALUE_MISMATCH", legacy_value=left,
                    canonical_value=str(right) if right is not None else None))
    result = CanonicalComparisonResult(provider=provider, compared_fields=compared,
        mismatches=tuple(mismatches[:16]), truncated=len(mismatches) > 16)
    return {"status": "compared", "matched": result.matched and not result.truncated,
            "comparison": result.model_dump(mode="json"),
            "postcondition_satisfied": canonical.postcondition_satisfied}
