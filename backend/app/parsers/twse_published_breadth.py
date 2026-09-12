"""Pure parsing and typed payloads for TWSE published stock breadth totals."""

import json
import re
from datetime import date
from pydantic import Field, model_validator

from app.market_data.contracts import CanonicalModel, PublishedBreadthLimits


TWSE_AGGREGATE_SCOPE = "twse_published_stock_aggregate"


class PublishedStockBreadth(CanonicalModel):
    trade_date: date
    advance: int = Field(ge=0)
    decline: int = Field(ge=0)
    unchanged: int = Field(ge=0)
    no_trade: int = Field(ge=0)
    no_comparison: int = Field(ge=0)
    limits: PublishedBreadthLimits

    @model_validator(mode="after")
    def _validate_partition(self):
        if (self.advance + self.decline + self.unchanged + self.no_trade + self.no_comparison != self.limits.universe_count
            or self.limits.scope != TWSE_AGGREGATE_SCOPE
            or self.limits.up_count > self.advance or self.limits.down_count > self.decline):
            raise ValueError("TWSE_AGGREGATE_PARTITION_INVALID")
        return self


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
