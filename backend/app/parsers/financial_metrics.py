import json
from typing import Any

from app.db.models import RawFetchResult
from app.parsers.twse_common import first_value, parse_date, parse_float, parse_int


def _load_json(raw_text: str | None) -> Any:
    if raw_text is None or raw_text.strip() == "":
        return None

    return json.loads(raw_text.lstrip("\ufeff").strip())


def _payload_entries(raw_result: RawFetchResult) -> list[tuple[str, str | None, list[dict]]]:
    payload = _load_json(raw_result.raw_text)

    if isinstance(payload, list):
        return [("direct", raw_result.url, [row for row in payload if isinstance(row, dict)])]

    if not isinstance(payload, dict):
        raise ValueError("Financial metrics payload should be a JSON list or bundle object.")

    entries: list[tuple[str, str | None, list[dict]]] = []

    for entry_name, entry in payload.items():
        if not isinstance(entry, dict):
            continue

        raw_text = entry.get("raw_text")
        entry_payload = _load_json(raw_text if isinstance(raw_text, str) else None)

        if not isinstance(entry_payload, list):
            continue

        entries.append(
            (
                str(entry_name),
                entry.get("url") if isinstance(entry.get("url"), str) else None,
                [row for row in entry_payload if isinstance(row, dict)],
            )
        )

    return entries


def _entry_statement_type(entry_name: str, url: str | None) -> str | None:
    haystack = f"{entry_name} {url or ''}".lower()

    if "t187ap06" in haystack or "income" in haystack:
        return "income"

    if "t187ap07" in haystack or "balance" in haystack:
        return "balance"

    return None


def _parse_fiscal_year(value: str | None) -> int | None:
    parsed = parse_int(value)

    if parsed is None:
        return None

    if parsed < 1911:
        return parsed + 1911

    return parsed


def _safe_pct(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None

    return numerator / denominator * 100


def _row_identity(row: dict) -> tuple[str, int, int] | None:
    stock_id = first_value(row, ["公司代號", "SecuritiesCompanyCode", "stock_id"])
    fiscal_year = _parse_fiscal_year(first_value(row, ["年度", "Year", "fiscal_year"]))
    quarter = parse_int(first_value(row, ["季別", "Season", "quarter"]))

    if stock_id is None or fiscal_year is None or quarter is None:
        return None

    return stock_id.strip(), fiscal_year, quarter


def _base_record(
    raw_result: RawFetchResult,
    row: dict,
    stock_id: str,
    fiscal_year: int,
    quarter: int,
) -> dict:
    return {
        "source_id": raw_result.source_id,
        "raw_result_id": raw_result.id,
        "report_date": parse_date(first_value(row, ["出表日期", "Date", "report_date"])),
        "fiscal_year": fiscal_year,
        "quarter": quarter,
        "period": f"{fiscal_year}Q{quarter}",
        "stock_id": stock_id,
        "stock_name": first_value(row, ["公司名稱", "CompanyName", "company_name"]),
        "market": None,
        "revenue": None,
        "gross_profit": None,
        "operating_income": None,
        "net_income": None,
        "net_income_attributable_parent": None,
        "eps": None,
        "total_assets": None,
        "total_equity": None,
        "parent_equity": None,
        "book_value_per_share": None,
        "roe": None,
        "roa": None,
    }


def _merge_if_present(record: dict, key: str, value) -> None:
    if value is not None:
        record[key] = value


def _apply_income_fields(record: dict, row: dict) -> None:
    _merge_if_present(record, "report_date", parse_date(first_value(row, ["出表日期", "Date"])))
    _merge_if_present(record, "stock_name", first_value(row, ["公司名稱", "CompanyName"]))
    _merge_if_present(record, "revenue", parse_float(first_value(row, ["營業收入"])))
    _merge_if_present(
        record,
        "gross_profit",
        parse_float(
            first_value(
                row,
                [
                    "營業毛利（毛損）淨額",
                    "營業毛利（毛損）",
                    "營業毛利(毛損)淨額",
                    "營業毛利(毛損)",
                ],
            )
        ),
    )
    _merge_if_present(
        record,
        "operating_income",
        parse_float(first_value(row, ["營業利益（損失）", "營業利益(損失)"])),
    )
    _merge_if_present(
        record,
        "net_income",
        parse_float(first_value(row, ["本期淨利（淨損）", "本期淨利(淨損)"])),
    )
    _merge_if_present(
        record,
        "net_income_attributable_parent",
        parse_float(
            first_value(
                row,
                [
                    "淨利（淨損）歸屬於母公司業主",
                    "淨利(淨損)歸屬於母公司業主",
                ],
            )
        ),
    )
    _merge_if_present(
        record,
        "eps",
        parse_float(first_value(row, ["基本每股盈餘（元）", "基本每股盈餘(元)", "EPS"])),
    )


def _apply_balance_fields(record: dict, row: dict) -> None:
    _merge_if_present(record, "report_date", parse_date(first_value(row, ["出表日期", "Date"])))
    _merge_if_present(record, "stock_name", first_value(row, ["公司名稱", "CompanyName"]))
    _merge_if_present(record, "total_assets", parse_float(first_value(row, ["資產總額", "資產總計"])))
    _merge_if_present(record, "total_equity", parse_float(first_value(row, ["權益總額", "權益總計"])))
    _merge_if_present(
        record,
        "parent_equity",
        parse_float(first_value(row, ["歸屬於母公司業主之權益合計"])),
    )
    _merge_if_present(
        record,
        "book_value_per_share",
        parse_float(first_value(row, ["每股參考淨值"])),
    )


def _finalize_record(record: dict) -> dict:
    parent_net_income = record.get("net_income_attributable_parent") or record.get("net_income")
    parent_equity = record.get("parent_equity") or record.get("total_equity")

    if record.get("roe") is None:
        record["roe"] = _safe_pct(parent_net_income, parent_equity)

    if record.get("roa") is None:
        record["roa"] = _safe_pct(parent_net_income, record.get("total_assets"))

    return record


def parse_financial_metrics_raw(
    raw_result: RawFetchResult,
) -> tuple[list[dict], int]:
    records: dict[tuple[str, int, int], dict] = {}
    skipped_count = 0

    for entry_name, url, payload_rows in _payload_entries(raw_result):
        statement_type = _entry_statement_type(entry_name=entry_name, url=url)

        if statement_type is None:
            skipped_count += len(payload_rows)
            continue

        for row in payload_rows:
            identity = _row_identity(row)

            if identity is None:
                skipped_count += 1
                continue

            stock_id, fiscal_year, quarter = identity
            record = records.setdefault(
                identity,
                _base_record(
                    raw_result=raw_result,
                    row=row,
                    stock_id=stock_id,
                    fiscal_year=fiscal_year,
                    quarter=quarter,
                ),
            )

            if statement_type == "income":
                _apply_income_fields(record, row)
            else:
                _apply_balance_fields(record, row)

    return [_finalize_record(record) for record in records.values()], skipped_count

