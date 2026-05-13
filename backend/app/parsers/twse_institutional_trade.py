import json
import re
from datetime import date
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from app.db.models import RawFetchResult

TAIPEI_TZ = ZoneInfo("Asia/Taipei")


def _repair_mojibake_text(value: str) -> str:
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


def _normalize_key(value: str | None) -> str:
    if value is None:
        return ""
    return (
        _repair_mojibake_text(str(value))
        .replace("\ufeff", "")
        .replace("ï»¿", "")
        .replace("嚗?", "")
        .strip()
    )


def _normalize_value(value) -> str | None:
    if value in (None, ""):
        return None
    return _repair_mojibake_text(str(value)).strip()


def _normalize_row(row: dict) -> dict:
    return {_normalize_key(key): value for key, value in row.items()}


def _first_value(row: dict, keys: list[str]) -> str | None:
    normalized = _normalize_row(row)
    for key in keys:
        value = normalized.get(key)
        if value not in (None, ""):
            return _normalize_value(value)
    return None


def _parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    cleaned = value.replace(",", "").replace("+", "").replace("股", "").strip()
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
        return date(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))
    if len(digits) == 7:
        return date(int(digits[:3]) + 1911, int(digits[3:5]), int(digits[5:7]))
    return None


def _fallback_trade_date(raw_result: RawFetchResult) -> date:
    fetched_at = raw_result.fetched_at
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=ZoneInfo("UTC"))
    return fetched_at.astimezone(TAIPEI_TZ).date()


def _date_from_url(url: str | None) -> date | None:
    if not url:
        return None
    parsed = urlparse(url)
    values = parse_qs(parsed.query).get("date")
    if not values:
        return None
    return _parse_date(values[0])


def _payload_trade_date(payload: dict, raw_result: RawFetchResult) -> date:
    for key in ["date", "trade_date", "日期", "stat"]:
        value = payload.get(key)
        if isinstance(value, str):
            parsed = _parse_date(value)
            if parsed is not None:
                return parsed
    return _date_from_url(raw_result.url) or _fallback_trade_date(raw_result)


def _load_payload(raw_text: str) -> dict:
    if not raw_text:
        raise ValueError("raw_text is empty.")
    cleaned_text = _repair_mojibake_text(raw_text).lstrip("\ufeff").strip()
    payload = json.loads(cleaned_text)
    if not isinstance(payload, dict):
        raise ValueError("TWSE T86 payload should be a JSON object.")
    return payload


def _list_row_to_dict(fields: list, row: list) -> dict:
    result = {}
    for index, field in enumerate(fields):
        if index >= len(row):
            break
        result[_normalize_key(str(field))] = row[index]
    return result


def _sum_nullable(*values: int | None) -> int | None:
    valid_values = [value for value in values if value is not None]
    if not valid_values:
        return None
    return sum(valid_values)


def _diff_nullable(buy: int | None, sell: int | None) -> int | None:
    if buy is None or sell is None:
        return None
    return buy - sell


def parse_twse_institutional_trade_raw(raw_result: RawFetchResult) -> tuple[list[dict], int]:
    payload = _load_payload(raw_result.raw_text or "")
    fields = payload.get("fields") or payload.get("Field") or []
    data = payload.get("data") or payload.get("Data") or []
    if not isinstance(data, list):
        raise ValueError("TWSE T86 data field should be a list.")
    trade_date = _payload_trade_date(payload, raw_result)
    parsed_rows: list[dict] = []
    skipped_count = 0

    for row in data:
        if isinstance(row, list):
            row_dict = _list_row_to_dict(fields, row)
        elif isinstance(row, dict):
            row_dict = row
        else:
            skipped_count += 1
            continue

        stock_id = _first_value(row_dict, ["證券代號", "stock_id", "Code", "code"])
        if not stock_id:
            skipped_count += 1
            continue

        stock_name = _first_value(row_dict, ["證券名稱", "stock_name", "Name", "name"])

        foreign_investor_buy = _parse_int(_first_value(row_dict, ["外陸資買進股數(不含外資自營商)", "外陸資買進股數(不含自營商)", "外資及陸資買進股數(不含外資自營商)"]))
        foreign_investor_sell = _parse_int(_first_value(row_dict, ["外陸資賣出股數(不含外資自營商)", "外陸資賣出股數(不含自營商)", "外資及陸資賣出股數(不含外資自營商)"]))
        foreign_investor_net = _parse_int(_first_value(row_dict, ["外陸資買賣超股數(不含外資自營商)", "外陸資買賣超股數(不含自營商)", "外資及陸資買賣超股數(不含外資自營商)"])) or _diff_nullable(foreign_investor_buy, foreign_investor_sell)

        foreign_dealer_buy = _parse_int(_first_value(row_dict, ["外資自營商買進股數"]))
        foreign_dealer_sell = _parse_int(_first_value(row_dict, ["外資自營商賣出股數"]))
        foreign_dealer_net = _parse_int(_first_value(row_dict, ["外資自營商買賣超股數"])) or _diff_nullable(foreign_dealer_buy, foreign_dealer_sell)

        investment_trust_buy = _parse_int(_first_value(row_dict, ["投信買進股數"]))
        investment_trust_sell = _parse_int(_first_value(row_dict, ["投信賣出股數"]))
        investment_trust_net = _parse_int(_first_value(row_dict, ["投信買賣超股數"])) or _diff_nullable(investment_trust_buy, investment_trust_sell)

        dealer_self_buy = _parse_int(_first_value(row_dict, ["自營商買進股數(自行買賣)", "自營商(自行買賣)買進股數"]))
        dealer_self_sell = _parse_int(_first_value(row_dict, ["自營商賣出股數(自行買賣)", "自營商(自行買賣)賣出股數"]))
        dealer_self_net = _parse_int(_first_value(row_dict, ["自營商買賣超股數(自行買賣)", "自營商(自行買賣)買賣超股數"])) or _diff_nullable(dealer_self_buy, dealer_self_sell)

        dealer_hedge_buy = _parse_int(_first_value(row_dict, ["自營商買進股數(避險)", "自營商(避險)買進股數"]))
        dealer_hedge_sell = _parse_int(_first_value(row_dict, ["自營商賣出股數(避險)", "自營商(避險)賣出股數"]))
        dealer_hedge_net = _parse_int(_first_value(row_dict, ["自營商買賣超股數(避險)", "自營商(避險)買賣超股數"])) or _diff_nullable(dealer_hedge_buy, dealer_hedge_sell)

        dealer_buy = _parse_int(_first_value(row_dict, ["自營商買進股數"])) or _sum_nullable(dealer_self_buy, dealer_hedge_buy)
        dealer_sell = _parse_int(_first_value(row_dict, ["自營商賣出股數"])) or _sum_nullable(dealer_self_sell, dealer_hedge_sell)
        dealer_net = _parse_int(_first_value(row_dict, ["自營商買賣超股數"])) or _sum_nullable(dealer_self_net, dealer_hedge_net)

        total_institutional_net = _parse_int(_first_value(row_dict, ["三大法人買賣超股數"])) or _sum_nullable(foreign_investor_net, investment_trust_net, dealer_net)

        parsed_rows.append({
            "source_id": raw_result.source_id,
            "raw_result_id": raw_result.id,
            "trade_date": trade_date,
            "stock_id": stock_id,
            "stock_name": stock_name,
            "foreign_investor_buy": foreign_investor_buy,
            "foreign_investor_sell": foreign_investor_sell,
            "foreign_investor_net": foreign_investor_net,
            "foreign_dealer_buy": foreign_dealer_buy,
            "foreign_dealer_sell": foreign_dealer_sell,
            "foreign_dealer_net": foreign_dealer_net,
            "investment_trust_buy": investment_trust_buy,
            "investment_trust_sell": investment_trust_sell,
            "investment_trust_net": investment_trust_net,
            "dealer_self_buy": dealer_self_buy,
            "dealer_self_sell": dealer_self_sell,
            "dealer_self_net": dealer_self_net,
            "dealer_hedge_buy": dealer_hedge_buy,
            "dealer_hedge_sell": dealer_hedge_sell,
            "dealer_hedge_net": dealer_hedge_net,
            "dealer_buy": dealer_buy,
            "dealer_sell": dealer_sell,
            "dealer_net": dealer_net,
            "total_institutional_net": total_institutional_net,
        })

    return parsed_rows, skipped_count
