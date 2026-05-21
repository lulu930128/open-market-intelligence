import re

from app.db.models import RawFetchResult
from app.parsers.twse_common import (
    coalesce_int,
    load_json_payload,
    normalize_text,
    parse_int,
    payload_trade_date,
    sum_nullable,
)


LOT_TO_SHARE_MULTIPLIER = 1000


def _extract_first_table(payload: dict) -> dict:
    tables = payload.get("tables") or payload.get("Tables") or []

    if isinstance(tables, list):
        for table in tables:
            if not isinstance(table, dict):
                continue

            if isinstance(table.get("data"), list):
                return table

    if isinstance(payload.get("data"), list):
        return payload

    raise ValueError("TPEx institutional payload does not contain a data table.")


def _row_value(row: list, index: int):
    if index >= len(row):
        return None

    return row[index]


def _parse_lots_as_shares(value) -> int | None:
    lots = parse_int(value)

    if lots is None:
        return None

    return lots * LOT_TO_SHARE_MULTIPLIER


def _is_stock_like_id(stock_id: str | None) -> bool:
    return bool(stock_id and re.search(r"[0-9A-Za-z]", stock_id))


def _load_bundle_payloads(raw_result: RawFetchResult) -> dict[str, dict]:
    bundle = load_json_payload(raw_result.raw_text, "TPEx institutional bundle")
    payloads: dict[str, dict] = {}

    for name, entry in bundle.items():
        if not isinstance(entry, dict):
            continue

        raw_text = entry.get("raw_text")

        if isinstance(raw_text, str) and raw_text.strip():
            payloads[name] = load_json_payload(raw_text, f"TPEx institutional {name}")

    return payloads


def _ensure_record(
    records: dict[str, dict],
    raw_result: RawFetchResult,
    trade_date,
    stock_id: str,
    stock_name: str | None,
) -> dict:
    record = records.get(stock_id)

    if record is None:
        record = {
            "source_id": raw_result.source_id,
            "raw_result_id": raw_result.id,
            "trade_date": trade_date,
            "stock_id": stock_id,
            "stock_name": normalize_text(stock_name),
            "foreign_investor_buy": None,
            "foreign_investor_sell": None,
            "foreign_investor_net": None,
            "foreign_dealer_buy": None,
            "foreign_dealer_sell": None,
            "foreign_dealer_net": None,
            "investment_trust_buy": None,
            "investment_trust_sell": None,
            "investment_trust_net": None,
            "dealer_self_buy": None,
            "dealer_self_sell": None,
            "dealer_self_net": None,
            "dealer_hedge_buy": None,
            "dealer_hedge_sell": None,
            "dealer_hedge_net": None,
            "dealer_buy": None,
            "dealer_sell": None,
            "dealer_net": None,
            "total_institutional_net": None,
        }
        records[stock_id] = record
        return record

    if record.get("stock_name") is None:
        record["stock_name"] = normalize_text(stock_name)

    return record


def _set_when_present(record: dict, key: str, value: int | None) -> None:
    if value is not None:
        record[key] = value


def _merge_foreign_payload(
    records: dict[str, dict],
    raw_result: RawFetchResult,
    payload: dict,
) -> int:
    table = _extract_first_table(payload)
    data = table.get("data") or table.get("Data") or []
    trade_date = payload_trade_date(payload, raw_result)
    skipped_count = 0

    for row in data:
        if not isinstance(row, list):
            skipped_count += 1
            continue

        stock_id = normalize_text(_row_value(row, 1))

        if not _is_stock_like_id(stock_id):
            skipped_count += 1
            continue

        record = _ensure_record(records, raw_result, trade_date, stock_id.strip(), _row_value(row, 2))
        _set_when_present(record, "foreign_investor_buy", _parse_lots_as_shares(_row_value(row, 3)))
        _set_when_present(record, "foreign_investor_sell", _parse_lots_as_shares(_row_value(row, 4)))
        _set_when_present(record, "foreign_investor_net", _parse_lots_as_shares(_row_value(row, 5)))
        _set_when_present(record, "foreign_dealer_buy", _parse_lots_as_shares(_row_value(row, 6)))
        _set_when_present(record, "foreign_dealer_sell", _parse_lots_as_shares(_row_value(row, 7)))
        _set_when_present(record, "foreign_dealer_net", _parse_lots_as_shares(_row_value(row, 8)))

    return skipped_count


def _merge_investment_trust_payload(
    records: dict[str, dict],
    raw_result: RawFetchResult,
    payload: dict,
) -> int:
    table = _extract_first_table(payload)
    data = table.get("data") or table.get("Data") or []
    trade_date = payload_trade_date(payload, raw_result)
    skipped_count = 0

    for row in data:
        if not isinstance(row, list):
            skipped_count += 1
            continue

        stock_id = normalize_text(_row_value(row, 1))

        if not _is_stock_like_id(stock_id):
            skipped_count += 1
            continue

        record = _ensure_record(records, raw_result, trade_date, stock_id.strip(), _row_value(row, 2))
        _set_when_present(record, "investment_trust_buy", _parse_lots_as_shares(_row_value(row, 3)))
        _set_when_present(record, "investment_trust_sell", _parse_lots_as_shares(_row_value(row, 4)))
        _set_when_present(record, "investment_trust_net", _parse_lots_as_shares(_row_value(row, 5)))

    return skipped_count


def _merge_dealer_payload(
    records: dict[str, dict],
    raw_result: RawFetchResult,
    payload: dict,
) -> int:
    table = _extract_first_table(payload)
    data = table.get("data") or table.get("Data") or []
    trade_date = payload_trade_date(payload, raw_result)
    skipped_count = 0

    for row in data:
        if not isinstance(row, list):
            skipped_count += 1
            continue

        stock_id = normalize_text(_row_value(row, 1))

        if not _is_stock_like_id(stock_id):
            skipped_count += 1
            continue

        record = _ensure_record(records, raw_result, trade_date, stock_id.strip(), _row_value(row, 2))
        dealer_self_net = _parse_lots_as_shares(_row_value(row, 5))
        dealer_hedge_net = _parse_lots_as_shares(_row_value(row, 8))
        dealer_net = coalesce_int(
            _parse_lots_as_shares(_row_value(row, 9)),
            sum_nullable(dealer_self_net, dealer_hedge_net),
        )

        _set_when_present(record, "dealer_self_net", dealer_self_net)
        _set_when_present(record, "dealer_hedge_net", dealer_hedge_net)
        _set_when_present(record, "dealer_net", dealer_net)

    return skipped_count


def parse_tpex_institutional_trade_raw(raw_result: RawFetchResult) -> tuple[list[dict], int]:
    payloads = _load_bundle_payloads(raw_result)

    if not payloads:
        raise ValueError("TPEx institutional bundle does not contain any payloads.")

    records: dict[str, dict] = {}
    skipped_count = 0

    for key in ("foreign_buy", "foreign_sell"):
        payload = payloads.get(key)
        if payload is not None:
            skipped_count += _merge_foreign_payload(records, raw_result, payload)

    for key in ("investment_trust_buy", "investment_trust_sell"):
        payload = payloads.get(key)
        if payload is not None:
            skipped_count += _merge_investment_trust_payload(records, raw_result, payload)

    for key in ("dealer_buy", "dealer_sell"):
        payload = payloads.get(key)
        if payload is not None:
            skipped_count += _merge_dealer_payload(records, raw_result, payload)

    parsed_rows = list(records.values())

    for record in parsed_rows:
        record["total_institutional_net"] = sum_nullable(
            record.get("foreign_investor_net"),
            record.get("investment_trust_net"),
            record.get("dealer_net"),
        )

    return parsed_rows, skipped_count
