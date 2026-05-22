import csv
from io import StringIO

from app.db.models import RawFetchResult
from app.parsers.twse_common import (
    first_value,
    normalize_text,
    parse_date,
    parse_float,
    parse_int,
    repair_mojibake_text,
)


def _level_order(value: str | None) -> int | None:
    parsed = parse_int(value)

    if parsed is None:
        return None

    return parsed


def parse_shareholding_distribution_raw(
    raw_result: RawFetchResult,
) -> tuple[list[dict], int]:
    raw_text = repair_mojibake_text(raw_result.raw_text).lstrip("\ufeff")

    if not raw_text.strip():
        return [], 0

    reader = csv.DictReader(StringIO(raw_text))
    rows: list[dict] = []
    skipped_count = 0

    for row in reader:
        data_date = parse_date(first_value(row, ["資料日期", "DataDate", "date"]))
        stock_id = first_value(row, ["證券代號", "StockNo", "stock_id"])
        holding_level = first_value(row, ["持股分級", "HoldingSharesLevel", "level"])

        if data_date is None or stock_id is None or holding_level is None:
            skipped_count += 1
            continue

        rows.append(
            {
                "source_id": raw_result.source_id,
                "raw_result_id": raw_result.id,
                "data_date": data_date,
                "stock_id": stock_id.strip(),
                "stock_name": None,
                "holding_level": holding_level,
                "holding_level_order": _level_order(holding_level),
                "holder_count": parse_int(first_value(row, ["人數", "HolderCount", "holders"])),
                "share_count": parse_int(first_value(row, ["股數", "ShareCount", "shares"])),
                "share_ratio": parse_float(
                    first_value(
                        row,
                        [
                            "占集保庫存數比例%",
                            "占集保庫存數比例",
                            "ShareholdingRatio",
                            "ratio",
                        ],
                    )
                ),
            }
        )

    return rows, skipped_count

