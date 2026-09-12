"""Bounded comparison of the same acquired JP payload and persisted candidates."""

from decimal import Decimal
from datetime import timedelta

from app.jp_market.bar_transaction import JPBarTransaction
from app.jp_market.daily_platform import JPDailyPlatform
from app.jp_market.market_data.adapters import adapt_yahoo_daily
from app.market_data.comparison import CanonicalComparisonResult, CanonicalMismatch, MismatchCategory


def persist_and_compare_yahoo(db, *, payload, instrument, source_url, fetched_at, legacy_records):
    adapted = adapt_yahoo_daily(payload, instrument=instrument, fetched_at=fetched_at, url=source_url)
    persisted = JPBarTransaction(db).persist_daily(adapted)
    if not adapted.bars:
        return {"status": "limited", "rejections": list(adapted.rejections), "persistence": persisted.model_dump(mode="json")}
    result = JPDailyPlatform(db).read(
        instrument=instrument, start_date=max(adapted.bars[0].start_at.date(), adapted.bars[-1].end_at.date() - timedelta(days=3649)),
        end_date=adapted.bars[-1].end_at.date(), requested_at=fetched_at, max_bars=16,
    )
    legacy = {row.trade_date: row for row in legacy_records}
    mismatches = []
    compared = 0
    for bar in result.resolved.bars:
        row = legacy.get(bar.end_at.date())
        for field in ("open_price", "high_price", "low_price", "close_price"):
            old = getattr(row, field, None)
            new = getattr(bar, field)
            compared += 1
            if old is None or Decimal(str(old)) != new:
                mismatches.append(CanonicalMismatch(
                    category=MismatchCategory.PRICE, field=field, reason_code="DAILY_VALUE_MISMATCH",
                    legacy_value=old, canonical_value=str(new),
                ))
    comparison = CanonicalComparisonResult(
        provider="yahoo_chart", compared_fields=compared,
        mismatches=tuple(mismatches[:16]), truncated=len(mismatches) > 16,
    )
    return {
        "status": "compared" if compared else "limited",
        "matched": comparison.matched if compared else False,
        "comparison": comparison.model_dump(mode="json"),
        "rejections": list(adapted.rejections),
        "persistence": persisted.model_dump(mode="json"),
    }
