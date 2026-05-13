import csv
import json
import re
from datetime import date
from io import StringIO
from zoneinfo import ZoneInfo

from app.db.models import RawFetchResult


TAIPEI_TZ = ZoneInfo("Asia/Taipei")


def _normalize_key(value: str | None) -> str:
    if value is None:
        return ""

    return (
        str(value)
        .replace("\ufeff", "")
        .replace("ï»¿", "")
        .replace("嚗?", "")
        .strip()
    )


def _normalize_row(row: dict) -> dict:
    return {_normalize_key(key): value for key, value in row.items()}


def _first_value(row: dict, keys: list[str]) -> str | None:
    normalized = _normalize_row(row)

    for key in keys:
        value = normalized.get(key)
        if value not in (None, ""):
            return _repair_mojibake_text(str(value)).strip()

    return None


def _parse_int(value: str | None) -> int | None:
    if value is None:
        return None

    cleaned = (
        value.replace(",", "")
        .replace("元", "")
        .replace("股", "")
        .strip()
    )

    if cleaned in {"", "-", "--", "NaN", "null", "None"}:
        return None

    match = re.search(r"-?\d+", cleaned)

    if match is None:
        return None

    return int(match.group())


def _parse_date(value: str | None) -> date | None:
    if value is None:
        return None

    cleaned = value.strip()

    if cleaned in {"", "-", "--", "NaN", "null", "None"}:
        return None

    separated_match = re.match(r"^(\d{2,4})[/-](\d{1,2})[/-](\d{1,2})$", cleaned)
    if separated_match:
        year = int(separated_match.group(1))
        month = int(separated_match.group(2))
        day = int(separated_match.group(3))

        if year < 1911:
            year += 1911

        return date(year, month, day)

    digits = re.sub(r"\D", "", cleaned)

    if len(digits) == 8:
        year = int(digits[:4])
        month = int(digits[4:6])
        day = int(digits[6:8])
        return date(year, month, day)

    if len(digits) == 7:
        year = int(digits[:3]) + 1911
        month = int(digits[3:5])
        day = int(digits[5:7])
        return date(year, month, day)

    return None


def _fallback_report_date(raw_result: RawFetchResult) -> date:
    fetched_at = raw_result.fetched_at

    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=ZoneInfo("UTC"))

    return fetched_at.astimezone(TAIPEI_TZ).date()


def _repair_mojibake_text(raw_text: str) -> str:
    """
    Repair common UTF-8 mojibake.

    Examples:
        å°ç©é» -> 台積電
        å¬å¸ä»£è -> 公司代號
    """
    if raw_text is None:
        return ""

    # If it already contains normal CJK characters, keep it.
    if re.search(r"[\u4e00-\u9fff]", raw_text):
        return raw_text

    try:
        return raw_text.encode("latin1").decode("utf-8-sig")
    except UnicodeError:
        try:
            return raw_text.encode("cp1252", errors="ignore").decode(
                "utf-8-sig",
                errors="replace",
            )
        except UnicodeError:
            return raw_text
    """
    Repair common UTF-8 mojibake.

    Some CSV responses may already be decoded incorrectly before reaching the
    parser, for example:
        åºè¡¨æ¥æ -> 出表日期
        å¬å¸ä»£è -> 公司代號

    In that case, encode the mojibake string back to latin-1 bytes, then decode
    it as UTF-8.
    """
    sample = raw_text[:2000]

    mojibake_markers = [
        "åº",
        "å¬å¸",
        "ç¢æ¥",
        "è¡¨",
    ]

    if not any(marker in sample for marker in mojibake_markers):
        return raw_text

    try:
        return raw_text.encode("latin1").decode("utf-8-sig")
    except UnicodeError:
        try:
            return raw_text.encode("cp1252", errors="ignore").decode(
                "utf-8-sig",
                errors="replace",
            )
        except UnicodeError:
            return raw_text
        

def _load_payload(raw_text: str) -> list[dict]:
    cleaned_text = _repair_mojibake_text(raw_text).lstrip("\ufeff").strip()

    if not cleaned_text:
        return []

    try:
        payload = json.loads(cleaned_text)
        if isinstance(payload, list):
            return [row for row in payload if isinstance(row, dict)]

        if isinstance(payload, dict):
            for key in ["data", "result", "rows"]:
                value = payload.get(key)
                if isinstance(value, list):
                    return [row for row in value if isinstance(row, dict)]

        raise ValueError("JSON payload does not contain a list of rows.")

    except json.JSONDecodeError:
        reader = csv.DictReader(StringIO(cleaned_text))
        return [row for row in reader if isinstance(row, dict)]


def parse_twse_company_profile_raw(raw_result: RawFetchResult) -> tuple[list[dict], int]:
    if not raw_result.raw_text:
        raise ValueError("raw_text is empty.")

    payload = _load_payload(raw_result.raw_text)
    fallback_date = _fallback_report_date(raw_result)

    parsed_rows: list[dict] = []
    skipped_count = 0

    for row in payload:
        if not isinstance(row, dict):
            skipped_count += 1
            continue

        stock_id = _first_value(
            row,
            [
                "公司代號",
                "公司代碼",
                "Code",
                "code",
                "stock_id",
            ],
        )

        if not stock_id:
            skipped_count += 1
            continue

        company_name = _first_value(
            row,
            [
                "公司名稱",
                "Name",
                "name",
                "company_name",
            ],
        )

        short_name = _first_value(
            row,
            [
                "公司簡稱",
                "簡稱",
                "short_name",
            ],
        )

        industry = _first_value(
            row,
            [
                "產業別",
                "industry",
            ],
        )

        listed_date = _parse_date(
            _first_value(
                row,
                [
                    "上市日期",
                    "掛牌日期",
                    "listed_date",
                ],
            )
        )

        established_date = _parse_date(
            _first_value(
                row,
                [
                    "成立日期",
                    "established_date",
                ],
            )
        )

        paid_in_capital = _parse_int(
            _first_value(
                row,
                [
                    "實收資本額",
                    "實收資本額(元)",
                    "paid_in_capital",
                ],
            )
        )

        issued_shares = _parse_int(
            _first_value(
                row,
                [
                    "已發行普通股數或TDR原股發行股數",
                    "已發行普通股數",
                    "issued_shares",
                ],
            )
        )

        parsed_rows.append(
            {
                "source_id": raw_result.source_id,
                "raw_result_id": raw_result.id,
                "report_date": fallback_date,
                "stock_id": stock_id,
                "company_name": company_name,
                "short_name": short_name,
                "market": "TWSE",
                "industry": industry,
                "listed_date": listed_date,
                "established_date": established_date,
                "paid_in_capital": paid_in_capital,
                "issued_shares": issued_shares,
                "private_placement_shares": _parse_int(
                    _first_value(row, ["私募股數", "private_placement_shares"])
                ),
                "preferred_shares": _parse_int(
                    _first_value(row, ["特別股", "preferred_shares"])
                ),
                "chairman": _first_value(row, ["董事長", "chairman"]),
                "general_manager": _first_value(row, ["總經理", "general_manager"]),
                "spokesman": _first_value(row, ["發言人", "spokesman"]),
                "spokesman_title": _first_value(row, ["發言人職稱", "spokesman_title"]),
                "phone": _first_value(row, ["總機電話", "phone"]),
                "address": _first_value(row, ["住址", "地址", "address"]),
                "website": _first_value(row, ["網址", "website"]),
                "email": _first_value(row, ["電子郵件信箱", "email"]),
            }
        )

    return parsed_rows, skipped_count