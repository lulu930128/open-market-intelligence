import json
import re
from datetime import date

from app.db.models import RawFetchResult
from app.parsers.twse_common import (
    first_value,
    normalize_text,
    parse_date,
    parse_float,
    parse_int,
    repair_mojibake_text,
)


def _parse_year_month(value: str | None) -> date | None:
    text = normalize_text(value)

    if text is None:
        return None

    digits = re.sub(r"\D", "", text)

    if len(digits) == 6:
        year = int(digits[:4])
        month = int(digits[4:6])
        return date(year, month, 1)

    if len(digits) == 5:
        year = int(digits[:3]) + 1911
        month = int(digits[3:5])
        return date(year, month, 1)

    return None


def _load_rows(raw_text: str | None) -> list[dict]:
    if raw_text is None:
        return []

    cleaned_text = repair_mojibake_text(raw_text).lstrip("\ufeff").strip()

    if not cleaned_text:
        return []

    payload = json.loads(cleaned_text)

    if not isinstance(payload, list):
        raise ValueError("Monthly revenue payload should be a JSON list.")

    return [row for row in payload if isinstance(row, dict)]


def parse_monthly_revenue_raw(
    raw_result: RawFetchResult,
) -> tuple[list[dict], int]:
    payload_rows = _load_rows(raw_result.raw_text)
    rows: list[dict] = []
    skipped_count = 0

    for row in payload_rows:
        period = _parse_year_month(first_value(row, ["資料年月", "YearMonth", "年月"]))
        stock_id = first_value(row, ["公司代號", "SecuritiesCompanyCode", "stock_id"])

        if period is None or stock_id is None:
            skipped_count += 1
            continue

        rows.append(
            {
                "source_id": raw_result.source_id,
                "raw_result_id": raw_result.id,
                "report_date": parse_date(first_value(row, ["出表日期", "Date", "report_date"])),
                "period": period,
                "stock_id": stock_id.strip(),
                "stock_name": first_value(row, ["公司名稱", "CompanyName", "company_name"]),
                "market": None,
                "industry": first_value(row, ["產業別", "Industry", "industry"]),
                "monthly_revenue": parse_int(
                    first_value(row, ["營業收入-當月營收", "CurrentMonthRevenue"])
                ),
                "previous_month_revenue": parse_int(
                    first_value(row, ["營業收入-上月營收", "PreviousMonthRevenue"])
                ),
                "previous_year_month_revenue": parse_int(
                    first_value(row, ["營業收入-去年當月營收", "PreviousYearMonthRevenue"])
                ),
                "month_over_month_pct": parse_float(
                    first_value(
                        row,
                        [
                            "營業收入-上月比較增減(%)",
                            "MonthOverMonthChangePercentage",
                        ],
                    )
                ),
                "year_over_year_pct": parse_float(
                    first_value(
                        row,
                        [
                            "營業收入-去年同月增減(%)",
                            "YearOverYearChangePercentage",
                        ],
                    )
                ),
                "cumulative_revenue": parse_int(
                    first_value(row, ["累計營業收入-當月累計營收", "CumulativeRevenue"])
                ),
                "previous_year_cumulative_revenue": parse_int(
                    first_value(
                        row,
                        [
                            "累計營業收入-去年累計營收",
                            "PreviousYearCumulativeRevenue",
                        ],
                    )
                ),
                "cumulative_year_over_year_pct": parse_float(
                    first_value(
                        row,
                        [
                            "累計營業收入-前期比較增減(%)",
                            "CumulativeYearOverYearChangePercentage",
                        ],
                    )
                ),
                "note": first_value(row, ["備註", "Note", "note"]),
            }
        )

    return rows, skipped_count

