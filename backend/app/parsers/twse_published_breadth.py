"""Pure parsing and shared typed payloads for official published breadth totals."""

import json
import re
from datetime import date
from typing import Literal
from pydantic import Field, model_validator

from app.market_data.contracts import CanonicalModel, PublishedBreadthLimits


TWSE_AGGREGATE_SCOPE = "twse_published_stock_aggregate"
TPEX_AGGREGATE_SCOPE = "tpex_published_stock_and_share_conversion_rights"
TPEX_STOCK_SCOPE_NOTE = "標的物:等價與鉅額成交之股票、換股權利證書，不含可轉債、認購售權證、認股權憑證及不動產受益憑證"


class PublishedStockBreadth(CanonicalModel):
    venue: Literal["TWSE", "TPEX"] = "TWSE"
    trade_date: date
    advance: int = Field(ge=0)
    decline: int = Field(ge=0)
    unchanged: int = Field(ge=0)
    no_trade: int = Field(ge=0)
    no_comparison: int = Field(ge=0)
    limits: PublishedBreadthLimits

    @model_validator(mode="after")
    def _validate_partition(self):
        expected_scope = TWSE_AGGREGATE_SCOPE if self.venue == "TWSE" else TPEX_AGGREGATE_SCOPE
        if (self.advance + self.decline + self.unchanged + self.no_trade + self.no_comparison != self.limits.universe_count
            or self.limits.scope != expected_scope
            or (self.venue == "TPEX" and self.no_comparison != 0)
            or self.limits.up_count > self.advance or self.limits.down_count > self.decline):
            raise ValueError(f"{self.venue}_AGGREGATE_PARTITION_INVALID")
        return self


def parse_tpex_published_breadth(raw_text: str, *, trade_date: date) -> PublishedStockBreadth:
    """Validate the dated stock/right-certificate aggregate, including suspensions.

    The published no-trade bucket includes suspended securities; callers must
    preserve that mixed category rather than assert ordinary valid_no_trade.
    """
    payload = json.loads(raw_text.lstrip("\ufeff"))
    if not isinstance(payload, dict) or payload.get("stat") != "ok":
        raise ValueError("TPEX_AGGREGATE_RESPONSE_INVALID")
    if payload.get("date") != trade_date.strftime("%Y%m%d"):
        raise ValueError("TPEX_AGGREGATE_DATE_MISMATCH")
    tables = payload.get("tables")
    if not isinstance(tables, list) or len(tables) != 1 or not isinstance(tables[0], dict):
        raise ValueError("TPEX_AGGREGATE_STOCK_SCHEMA_MISSING")
    table = tables[0]
    notes = table.get("notes")
    if (not isinstance(table.get("title"), str)
        or re.sub(r"\s+", "", table["title"]) != "上櫃股票當日彙總資訊"
        or not isinstance(notes, list) or len(notes) != 1
        or not isinstance(notes[0], str) or re.sub(r"\s+", "", notes[0]) != TPEX_STOCK_SCOPE_NOTE):
        raise ValueError("TPEX_AGGREGATE_STOCK_SCOPE_MISMATCH")
    if table.get("date") != f"{trade_date.year - 1911:03d}/{trade_date:%m/%d}":
        raise ValueError("TPEX_AGGREGATE_DATE_MISMATCH")
    fields, rows = table.get("fields"), table.get("data")
    expected = ("上櫃家數", "上漲家數", "漲停家數", "下跌家數", "跌停家數", "平盤家數", "未成交(含暫停交易)家數")
    if (not isinstance(fields, list) or any(fields.count(field) != 1 for field in expected)
        or not isinstance(rows, list) or len(rows) != 1
        or not isinstance(rows[0], list) or len(rows[0]) != len(fields)):
        raise ValueError("TPEX_AGGREGATE_STOCK_SCHEMA_MISSING")
    counts = []
    for field in expected:
        value = rows[0][fields.index(field)]
        if not isinstance(value, str) or re.fullmatch(r"(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)", value) is None:
            raise ValueError("TPEX_AGGREGATE_COUNT_INVALID")
        counts.append(int(value.replace(",", "")))
    total, advance, up, decline, down, unchanged, no_trade = counts
    return PublishedStockBreadth(venue="TPEX", trade_date=trade_date,
        advance=advance, decline=decline, unchanged=unchanged, no_trade=no_trade, no_comparison=0,
        limits=PublishedBreadthLimits(scope=TPEX_AGGREGATE_SCOPE, universe_count=total,
                                     up_count=up, down_count=down))


def parse_twse_published_breadth(raw_text: str, *, trade_date: date) -> PublishedStockBreadth:
    payload = json.loads(raw_text.lstrip("\ufeff"))
    if not isinstance(payload, dict) or payload.get("stat") != "OK":
        raise ValueError("TWSE_AGGREGATE_RESPONSE_INVALID")
    if payload.get("date") != trade_date.strftime("%Y%m%d"):
        raise ValueError("TWSE_AGGREGATE_DATE_MISMATCH")
    tables = [table for table in payload.get("tables", []) if isinstance(table, dict)
              and table.get("title") == "漲跌證券數合計"]
    if len(tables) != 1 or tables[0].get("fields", []).count("股票") != 1:
        raise ValueError("TWSE_AGGREGATE_STOCK_SCHEMA_MISSING")
    column = tables[0]["fields"].index("股票")
    values = {}
    expected = {"上漲(漲停)": "advance", "下跌(跌停)": "decline",
                "持平": "unchanged", "未成交": "no_trade", "無比價": "no_comparison"}
    limits = {}
    for row in tables[0].get("data", []):
        if not isinstance(row, list) or not row:
            raise ValueError("TWSE_AGGREGATE_ROW_INVALID")
        label = str(row[0]).strip()
        if label not in expected:
            raise ValueError("TWSE_AGGREGATE_CATEGORY_UNKNOWN")
        key = expected[label]
        if key in values or len(row) <= column:
            raise ValueError("TWSE_AGGREGATE_DUPLICATE_OR_SHORT_ROW")
        match = re.fullmatch(r"([0-9]+)(?:\(([0-9]+)\))?", str(row[column]).replace(",", "").strip())
        if match is None:
            raise ValueError("TWSE_AGGREGATE_COUNT_INVALID")
        values[key] = int(match[1])
        if key in {"advance", "decline"}:
            if match[2] is None or int(match[2]) > values[key]:
                raise ValueError("TWSE_AGGREGATE_LIMIT_INVALID")
            limits[key] = int(match[2])
        elif match[2] is not None:
            raise ValueError("TWSE_AGGREGATE_UNEXPECTED_LIMIT")
    if set(values) != set(expected.values()):
        raise ValueError("TWSE_AGGREGATE_PARTITION_MISSING")
    return PublishedStockBreadth(trade_date=trade_date, **values, limits=PublishedBreadthLimits(
        scope=TWSE_AGGREGATE_SCOPE, universe_count=sum(values.values()),
        up_count=limits["advance"], down_count=limits["decline"],
    ))
