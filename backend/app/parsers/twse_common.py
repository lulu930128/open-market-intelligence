import json
import re
from datetime import date
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from app.db.models import RawFetchResult


TAIPEI_TZ = ZoneInfo("Asia/Taipei")
EMPTY_VALUES = {"", "-", "--", "NaN", "nan", "null", "None"}


def repair_mojibake_text(value: str | None) -> str:
    if value is None:
        return ""

    if re.search(r"[\u4e00-\u9fff]", value):
        return value

    try:
        return value.encode("latin1").decode("utf-8-sig")
    except UnicodeError:
        try:
            return value.encode("cp1252", errors="ignore").decode("utf-8-sig", errors="replace")
        except UnicodeError:
            return value


def normalize_text(value) -> str | None:
    if value is None:
        return None

    text = repair_mojibake_text(str(value))
    text = text.replace("\ufeff", "").replace("\u3000", " ").strip()

    if text in EMPTY_VALUES:
        return None

    return text


def normalize_key(value: str | None) -> str:
    return normalize_text(value) or ""


def normalize_row(row: dict) -> dict:
    return {normalize_key(str(key)): value for key, value in row.items()}


def first_value(row: dict, keys: list[str]) -> str | None:
    normalized = normalize_row(row)

    for key in keys:
        value = normalize_text(normalized.get(key))

        if value is not None:
            return value

    return None


def parse_int(value) -> int | None:
    text = normalize_text(value)

    if text is None:
        return None

    negative_parentheses = text.startswith("(") and text.endswith(")")
    cleaned = (
        text.replace(",", "")
        .replace("+", "")
        .replace("股", "")
        .replace(" ", "")
        .replace("\u3000", "")
        .strip()
    )

    match = re.search(r"-?\d+", cleaned)

    if match is None:
        return None

    result = int(match.group())

    if negative_parentheses and result > 0:
        return -result

    return result


def parse_float(value) -> float | None:
    text = normalize_text(value)

    if text is None:
        return None

    negative_parentheses = text.startswith("(") and text.endswith(")")
    cleaned = (
        text.replace(",", "")
        .replace("+", "")
        .replace(" ", "")
        .replace("\u3000", "")
        .strip()
    )

    match = re.search(r"-?\d+(?:\.\d+)?", cleaned)

    if match is None:
        return None

    result = float(match.group())

    if negative_parentheses and result > 0:
        return -result

    return result


def parse_date(value: str | None) -> date | None:
    text = normalize_text(value)

    if text is None:
        return None

    separated_match = re.match(r"^(\d{2,4})[/-](\d{1,2})[/-](\d{1,2})$", text)

    if separated_match:
        year = int(separated_match.group(1))
        month = int(separated_match.group(2))
        day = int(separated_match.group(3))

        if year < 1911:
            year += 1911

        return date(year, month, day)

    digits = re.sub(r"\D", "", text)

    if len(digits) == 8:
        return date(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))

    if len(digits) == 7:
        return date(int(digits[:3]) + 1911, int(digits[3:5]), int(digits[5:7]))

    return None


def fallback_trade_date(raw_result: RawFetchResult) -> date:
    fetched_at = raw_result.fetched_at

    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=ZoneInfo("UTC"))

    return fetched_at.astimezone(TAIPEI_TZ).date()


def date_from_url(url: str | None) -> date | None:
    if not url:
        return None

    parsed = urlparse(url)
    values = parse_qs(parsed.query).get("date")

    if not values:
        return None

    return parse_date(values[0])


def payload_trade_date(payload: dict, raw_result: RawFetchResult) -> date:
    for key in ["date", "trade_date", "title", "stat"]:
        value = payload.get(key)

        if isinstance(value, str):
            parsed = parse_date(value)

            if parsed is not None:
                return parsed

    return date_from_url(raw_result.url) or fallback_trade_date(raw_result)


def load_json_payload(raw_text: str | None, payload_name: str) -> dict:
    if not raw_text:
        raise ValueError("raw_text is empty.")

    cleaned_text = repair_mojibake_text(raw_text).lstrip("\ufeff").strip()
    payload = json.loads(cleaned_text)

    if not isinstance(payload, dict):
        raise ValueError(f"{payload_name} payload should be a JSON object.")

    return payload


def list_row_to_dict(fields: list, row: list) -> dict:
    result = {}

    for index, field in enumerate(fields):
        if index >= len(row):
            break

        result[normalize_key(str(field))] = row[index]

    return result


def coalesce_int(*values: int | None) -> int | None:
    for value in values:
        if value is not None:
            return value

    return None


def sum_nullable(*values: int | None) -> int | None:
    valid_values = [value for value in values if value is not None]

    if not valid_values:
        return None

    return sum(valid_values)


def diff_nullable(left: int | None, right: int | None) -> int | None:
    if left is None or right is None:
        return None

    return left - right
