from dataclasses import dataclass
from datetime import date

import requests
from sqlalchemy.orm import Session

from app.db.models import BrokerBranchTradeDaily, RawFetchResult, SourceRegistry
from app.parsers.twse_common import parse_date, parse_float, parse_int
from app.utils.hash import sha256_text


NSTOCK_BRANCH_TOP15_URL = "https://shop.nstock.tw/api/v2/branch-data/branch-top15_ad"
NSTOCK_BRANCH_SOURCE_NAME = "nStock Broker Branch Top 15"


class BrokerBranchFetchError(RuntimeError):
    pass


@dataclass(frozen=True)
class BrokerBranchFetchResult:
    url: str
    status_code: int
    content_type: str | None
    raw_text: str
    payload: dict


def _get_or_create_source(db: Session) -> SourceRegistry:
    source = (
        db.query(SourceRegistry)
        .filter(SourceRegistry.source_name == NSTOCK_BRANCH_SOURCE_NAME)
        .first()
    )

    if source is not None:
        return source

    source = SourceRegistry(
        source_name=NSTOCK_BRANCH_SOURCE_NAME,
        source_type="http_api",
        category="broker_branch_trade",
        endpoint_url=NSTOCK_BRANCH_TOP15_URL,
        enabled=True,
        parser_type="nstock_broker_branch_top15",
        reliability_level="third_party",
    )
    db.add(source)
    db.flush()
    return source


def _fetch_nstock_branch_top15(stock_id: str) -> BrokerBranchFetchResult:
    try:
        response = requests.get(
            NSTOCK_BRANCH_TOP15_URL,
            params={"stock_id": stock_id},
            headers={
                "User-Agent": "OpenMarketIntelligence/1.1 (+local development)",
                "Accept": "application/json,text/plain,*/*",
            },
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        raise BrokerBranchFetchError(f"分點資料來源連線失敗：{exc}") from exc
    except ValueError as exc:
        raise BrokerBranchFetchError("分點資料來源回傳格式不是有效 JSON。") from exc

    return BrokerBranchFetchResult(
        url=response.url,
        status_code=response.status_code,
        content_type=response.headers.get("content-type"),
        raw_text=response.text,
        payload=payload,
    )


def _source_url(stock_id: str) -> str:
    return f"{NSTOCK_BRANCH_TOP15_URL}?stock_id={stock_id}"


def _source_label(payload_data: dict) -> str:
    return f"nStock branch top15 ({payload_data.get('顯示') or 'net'})"


def _row_key(row: dict) -> str:
    return str(row.get("分點代號") or row.get("分點名稱") or "").strip()


def _parse_branch_rows(payload_data: dict) -> list[dict]:
    trade_date = parse_date(payload_data.get("更新日期"))

    if trade_date is None:
        raise ValueError("Broker branch payload does not contain a valid update date.")

    stock_id = str(payload_data.get("股票代號") or "").strip()

    if not stock_id:
        raise ValueError("Broker branch payload does not contain a stock id.")

    stock_name = str(payload_data.get("股票名稱") or "").strip() or None
    source_label = _source_label(payload_data)
    rows_by_branch: dict[str, dict] = {}

    def ensure_row(row: dict) -> dict | None:
        branch_key = _row_key(row)

        if not branch_key:
            return None

        current = rows_by_branch.get(branch_key)

        if current is None:
            current = {
                "trade_date": trade_date,
                "stock_id": stock_id,
                "stock_name": stock_name,
                "branch_code": str(row.get("分點代號") or "").strip(),
                "branch_name": str(row.get("分點名稱") or "").strip(),
                "buy_lots": parse_int(row.get("買張")),
                "sell_lots": parse_int(row.get("賣張")),
                "net_lots": None,
                "buy_avg_price": parse_float(row.get("買均價")),
                "sell_avg_price": parse_float(row.get("賣均價")),
                "buy_rank": None,
                "sell_rank": None,
                "source_label": source_label,
            }
            rows_by_branch[branch_key] = current

        return current

    for row in payload_data.get("買超top15") or []:
        if not isinstance(row, dict):
            continue

        current = ensure_row(row)

        if current is None:
            continue

        current["buy_rank"] = parse_int(row.get("買超排名"))
        current["net_lots"] = parse_int(row.get("買超"))
        current["buy_lots"] = parse_int(row.get("買張"))
        current["sell_lots"] = parse_int(row.get("賣張"))
        current["buy_avg_price"] = parse_float(row.get("買均價"))
        current["sell_avg_price"] = parse_float(row.get("賣均價"))

    for row in payload_data.get("賣超top15") or []:
        if not isinstance(row, dict):
            continue

        current = ensure_row(row)

        if current is None:
            continue

        current["sell_rank"] = parse_int(row.get("賣超排名"))
        current["net_lots"] = parse_int(row.get("賣超"))
        current["buy_lots"] = parse_int(row.get("買張"))
        current["sell_lots"] = parse_int(row.get("賣張"))
        current["buy_avg_price"] = parse_float(row.get("買均價"))
        current["sell_avg_price"] = parse_float(row.get("賣均價"))

    return list(rows_by_branch.values())


def fetch_and_store_broker_branch_daily(
    db: Session,
    *,
    stock_id: str,
    requested_trade_date: date | None = None,
    force: bool = False,
) -> list[BrokerBranchTradeDaily]:
    source = _get_or_create_source(db)
    fetch_result = _fetch_nstock_branch_top15(stock_id=stock_id)
    payload_data = (
        fetch_result.payload.get("data")
        if isinstance(fetch_result.payload, dict)
        else None
    )

    if not isinstance(payload_data, dict):
        raise BrokerBranchFetchError("分點資料來源回傳格式缺少 data 物件。")

    try:
        rows = _parse_branch_rows(payload_data)
    except ValueError as exc:
        raise BrokerBranchFetchError(str(exc)) from exc

    if not rows:
        return []

    fetched_trade_date = rows[0]["trade_date"]

    if requested_trade_date is not None and requested_trade_date != fetched_trade_date:
        return []

    existing_count = (
        db.query(BrokerBranchTradeDaily)
        .filter(BrokerBranchTradeDaily.source_id == source.id)
        .filter(BrokerBranchTradeDaily.stock_id == stock_id)
        .filter(BrokerBranchTradeDaily.trade_date == fetched_trade_date)
        .count()
    )

    if existing_count and not force:
        return list_broker_branch_trades(
            db=db,
            stock_id=stock_id,
            trade_date=fetched_trade_date,
        )

    raw_result = RawFetchResult(
        source_id=source.id,
        url=fetch_result.url,
        method="GET",
        status_code=fetch_result.status_code,
        content_type=fetch_result.content_type,
        content_hash=sha256_text(fetch_result.raw_text),
        raw_text=fetch_result.raw_text,
        parser_version="nstock_broker_branch_top15_v1",
    )
    db.add(raw_result)
    db.flush()

    (
        db.query(BrokerBranchTradeDaily)
        .filter(BrokerBranchTradeDaily.source_id == source.id)
        .filter(BrokerBranchTradeDaily.stock_id == stock_id)
        .filter(BrokerBranchTradeDaily.trade_date == fetched_trade_date)
        .delete(synchronize_session=False)
    )

    models = [
        BrokerBranchTradeDaily(
            source_id=source.id,
            raw_result_id=raw_result.id,
            **row,
        )
        for row in rows
    ]
    db.add_all(models)
    db.commit()

    return list_broker_branch_trades(
        db=db,
        stock_id=stock_id,
        trade_date=fetched_trade_date,
    )


def latest_broker_branch_trade_date(db: Session, stock_id: str) -> date | None:
    return (
        db.query(BrokerBranchTradeDaily.trade_date)
        .filter(BrokerBranchTradeDaily.stock_id == stock_id)
        .order_by(BrokerBranchTradeDaily.trade_date.desc())
        .limit(1)
        .scalar()
    )


def list_broker_branch_trades(
    db: Session,
    *,
    stock_id: str,
    trade_date: date,
) -> list[BrokerBranchTradeDaily]:
    return (
        db.query(BrokerBranchTradeDaily)
        .filter(BrokerBranchTradeDaily.stock_id == stock_id)
        .filter(BrokerBranchTradeDaily.trade_date == trade_date)
        .order_by(
            BrokerBranchTradeDaily.net_lots.desc().nullslast(),
            BrokerBranchTradeDaily.branch_code.asc(),
        )
        .all()
    )


def get_broker_branch_trade_summary(
    db: Session,
    *,
    stock_id: str,
    trade_date: date | None = None,
    ensure_daily: bool = False,
    force: bool = False,
) -> dict:
    if ensure_daily:
        fetch_and_store_broker_branch_daily(
            db=db,
            stock_id=stock_id,
            requested_trade_date=trade_date,
            force=force,
        )

    target_date = trade_date or latest_broker_branch_trade_date(db=db, stock_id=stock_id)

    if target_date is None:
        return {
            "stock_id": stock_id,
            "stock_name": None,
            "trade_date": None,
            "source_name": NSTOCK_BRANCH_SOURCE_NAME,
            "source_url": _source_url(stock_id),
            "source_label": None,
            "is_latest": False,
            "row_count": 0,
            "buy_top": [],
            "sell_top": [],
        }

    rows = list_broker_branch_trades(db=db, stock_id=stock_id, trade_date=target_date)
    buy_top = sorted(
        [row for row in rows if row.buy_rank is not None],
        key=lambda row: row.buy_rank or 999,
    )
    sell_top = sorted(
        [row for row in rows if row.sell_rank is not None],
        key=lambda row: row.sell_rank or 999,
    )
    first_row = rows[0] if rows else None

    return {
        "stock_id": stock_id,
        "stock_name": first_row.stock_name if first_row else None,
        "trade_date": target_date,
        "source_name": NSTOCK_BRANCH_SOURCE_NAME,
        "source_url": _source_url(stock_id),
        "source_label": first_row.source_label if first_row else None,
        "is_latest": True,
        "row_count": len(rows),
        "buy_top": buy_top,
        "sell_top": sell_top,
    }
