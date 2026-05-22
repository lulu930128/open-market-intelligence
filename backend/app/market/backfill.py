import json
import time
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone

import requests
from sqlalchemy.orm import Session

from app.db.models import (
    DataQualityCheck,
    FetchLog,
    MarketDailyPrice,
    RawFetchResult,
    SourceRegistry,
    StockMaster,
    utc_now,
)
from app.parsers.twse_stock_day import (
    parse_twse_stock_day_raw,
    validate_twse_stock_day_payload,
)
from app.parsers.twse_common import parse_float, parse_int
from app.sources.defaults import (
    TPEX_DAILY_QUOTES_SOURCE_NAME,
    TWSE_DAILY_TRADING_SOURCE_NAME,
)
from app.utils.hash import sha256_text


TWSE_STOCK_DAY_URL = "https://www.twse.com.tw/exchangeReport/STOCK_DAY"
TPEX_TRADING_STOCK_URL = "https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingStock"


def _month_starts(start_date: date, end_date: date) -> list[date]:
    months: list[date] = []

    current = date(start_date.year, start_date.month, 1)

    while current <= end_date:
        months.append(current)

        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)

    return months


def _month_end(month_start: date) -> date:
    last_day = monthrange(month_start.year, month_start.month)[1]
    return date(month_start.year, month_start.month, last_day)


def _get_stock_name(db: Session, stock_id: str) -> str | None:
    stock = db.query(StockMaster).filter(StockMaster.stock_id == stock_id).first()

    if stock:
        return stock.stock_name

    latest_market_row = (
        db.query(MarketDailyPrice)
        .filter(MarketDailyPrice.stock_id == stock_id)
        .order_by(MarketDailyPrice.trade_date.desc())
        .first()
    )

    if latest_market_row:
        return latest_market_row.stock_name

    return None


def _get_source(
    db: Session,
    source_id: int | None,
    fallback_source_name: str,
) -> SourceRegistry:
    query = db.query(SourceRegistry)

    if source_id is not None:
        source = query.filter(SourceRegistry.id == source_id).first()

        if source is None:
            raise ValueError(f"Source id={source_id} not found.")

        return source

    source = query.filter(SourceRegistry.source_name == fallback_source_name).first()

    if source is None:
        raise ValueError(f"Source name='{fallback_source_name}' not found.")

    return source


def _build_twse_stock_day_url(stock_id: str, month_start: date) -> str:
    date_param = month_start.strftime("%Y%m%d")

    return (
        f"{TWSE_STOCK_DAY_URL}"
        f"?response=json"
        f"&date={date_param}"
        f"&stockNo={stock_id}"
    )


def _build_tpex_trading_stock_url(stock_id: str, month_start: date) -> str:
    date_param = month_start.strftime("%Y%m%d")

    return (
        f"{TPEX_TRADING_STOCK_URL}"
        f"?response=json"
        f"&code={stock_id}"
        f"&date={date_param}"
    )


def _existing_market_row_stats(
    db: Session,
    stock_id: str,
    start_date: date,
    end_date: date,
) -> tuple[int, date | None]:
    rows = (
        db.query(MarketDailyPrice.trade_date)
        .filter(MarketDailyPrice.stock_id == stock_id)
        .filter(MarketDailyPrice.trade_date >= start_date)
        .filter(MarketDailyPrice.trade_date <= end_date)
        .all()
    )
    dates = [row.trade_date for row in rows]

    return len(dates), max(dates) if dates else None


def _should_skip_existing_month(
    existing_count: int,
    latest_existing_date: date | None,
    month_end: date,
    effective_end: date,
) -> bool:
    if existing_count <= 0 or latest_existing_date is None:
        return False

    if latest_existing_date >= effective_end:
        return True

    is_closed_historical_month = month_end < date.today()

    if not is_closed_historical_month:
        return False

    if latest_existing_date >= effective_end - timedelta(days=4):
        return True

    return False


def _parse_roc_date(value: str | None) -> date | None:
    if not value:
        return None

    parts = value.replace(".", "/").replace("-", "/").split("/")

    if len(parts) != 3:
        return None

    try:
        year = int(parts[0]) + 1911
        month = int(parts[1])
        day = int(parts[2])
        return date(year, month, day)
    except ValueError:
        return None


def _row_values(row) -> list:
    if isinstance(row, dict):
        value = row.get("value")
        if isinstance(value, list):
            return value

    if isinstance(row, list):
        return row

    return []


def _parse_tpex_trading_stock_raw(
    raw_text: str,
    stock_id: str,
    stock_name: str | None,
    source_id: int,
    raw_result_id: int,
    start_date: date,
    end_date: date,
) -> tuple[list[dict], int]:
    payload = json.loads(raw_text)
    tables = payload.get("tables") or []
    table = tables[0] if tables else {}
    rows = table.get("data") or []

    parsed_rows: list[dict] = []
    skipped_count = 0

    for row in rows:
        values = _row_values(row)

        if len(values) < 9:
            skipped_count += 1
            continue

        trade_date = _parse_roc_date(str(values[0]))

        if trade_date is None or trade_date < start_date or trade_date > end_date:
            skipped_count += 1
            continue

        trade_volume = parse_int(values[1])
        trade_value = parse_int(values[2])

        parsed_rows.append(
            {
                "source_id": source_id,
                "raw_result_id": raw_result_id,
                "trade_date": trade_date,
                "stock_id": stock_id,
                "stock_name": stock_name,
                "trade_volume": trade_volume * 1000 if trade_volume is not None else None,
                "trade_value": trade_value * 1000 if trade_value is not None else None,
                "open_price": parse_float(values[3]),
                "high_price": parse_float(values[4]),
                "low_price": parse_float(values[5]),
                "close_price": parse_float(values[6]),
                "price_change": parse_float(values[7]),
                "transaction_count": parse_int(values[8]),
            }
        )

    return parsed_rows, skipped_count


def _create_fetch_log(
    db: Session,
    source_id: int,
    stock_id: str,
    month_start: date,
    job_prefix: str = "backfill_twse",
    message: str = "TWSE stock day backfill started.",
) -> FetchLog:
    fetch_log = FetchLog(
        source_id=source_id,
        job_name=f"{job_prefix}:{stock_id}:{month_start.strftime('%Y%m')}",
        status="running",
        started_at=utc_now(),
        message=message,
    )

    db.add(fetch_log)
    db.commit()
    db.refresh(fetch_log)

    return fetch_log


def _save_market_rows(
    db: Session,
    rows: list[dict],
) -> int:
    if not rows:
        return 0

    source_id = rows[0]["source_id"]
    stock_id = rows[0]["stock_id"]
    trade_dates = sorted({row["trade_date"] for row in rows})

    for trade_date in trade_dates:
        (
            db.query(MarketDailyPrice)
            .filter(MarketDailyPrice.source_id == source_id)
            .filter(MarketDailyPrice.stock_id == stock_id)
            .filter(MarketDailyPrice.trade_date == trade_date)
            .delete(synchronize_session=False)
        )

    db.add_all([MarketDailyPrice(**row) for row in rows])

    return len(rows)


def backfill_twse_stock_day(
    db: Session,
    stock_id: str,
    start_date: date,
    end_date: date,
    source_id: int | None = None,
    sleep_seconds: float = 0.8,
    skip_existing_months: bool = False,
) -> dict:
    if end_date < start_date:
        raise ValueError("end_date must be greater than or equal to start_date.")

    source = _get_source(
        db=db,
        source_id=source_id,
        fallback_source_name=TWSE_DAILY_TRADING_SOURCE_NAME,
    )
    stock_name = _get_stock_name(db, stock_id)

    month_starts = _month_starts(start_date, end_date)

    total_parsed_count = 0
    total_inserted_count = 0
    total_skipped_count = 0
    skipped_existing_month_count = 0
    fetched_month_count = 0

    month_results: list[dict] = []

    headers = {
        "User-Agent": "OpenMarketIntelligence/1.1 (+local development)",
        "Accept": "application/json,text/plain,*/*",
    }

    for index, month_start in enumerate(month_starts):
        month_started_perf = time.perf_counter()

        month_label = month_start.strftime("%Y-%m")
        url = _build_twse_stock_day_url(stock_id, month_start)
        month_end = _month_end(month_start)
        effective_start = max(start_date, month_start)
        effective_end = min(end_date, month_end)

        if skip_existing_months:
            existing_count, latest_existing_date = _existing_market_row_stats(
                db=db,
                stock_id=stock_id,
                start_date=effective_start,
                end_date=effective_end,
            )

            if _should_skip_existing_month(
                existing_count=existing_count,
                latest_existing_date=latest_existing_date,
                month_end=month_end,
                effective_end=effective_end,
            ):
                skipped_existing_month_count += 1
                month_results.append(
                    {
                        "month": month_label,
                        "url": url,
                        "fetch_log_id": None,
                        "raw_result_id": None,
                        "http_status_code": None,
                        "data_quality_status": "skipped",
                        "data_quality_message": (
                            f"Skipped because {existing_count} existing daily rows "
                            f"were found in this month."
                        ),
                        "row_count": existing_count,
                        "parsed_count": 0,
                        "skipped_count": 0,
                        "status": "skipped_existing",
                        "error_message": None,
                    }
                )
                continue

        fetch_log = _create_fetch_log(
            db=db,
            source_id=source.id,
            stock_id=stock_id,
            month_start=month_start,
        )

        raw_result: RawFetchResult | None = None

        try:
            response = requests.get(url, headers=headers, timeout=30)
            raw_text = response.text
            content_hash = sha256_text(raw_text)
            content_type = response.headers.get("content-type")

            raw_result = RawFetchResult(
                source_id=source.id,
                fetch_log_id=fetch_log.id,
                fetched_at=datetime.now(timezone.utc),
                url=url,
                method="GET",
                status_code=response.status_code,
                content_type=content_type,
                content_hash=content_hash,
                raw_text=raw_text,
                parser_version="twse_stock_day_v1",
                error_message=None if response.ok else f"HTTP {response.status_code}",
            )

            db.add(raw_result)
            db.flush()

            is_duplicate = False

            duplicate = (
                db.query(RawFetchResult)
                .filter(RawFetchResult.source_id == source.id)
                .filter(RawFetchResult.content_hash == content_hash)
                .filter(RawFetchResult.id != raw_result.id)
                .first()
            )

            if duplicate is not None:
                is_duplicate = True

            quality_status, quality_message, row_count = validate_twse_stock_day_payload(raw_text)

            if is_duplicate and quality_status != "error":
                quality_status = "warning"
                quality_message = (
                    f"{quality_message} Raw content hash already exists for this source."
                )

            quality_check = DataQualityCheck(
                source_id=source.id,
                fetch_log_id=fetch_log.id,
                raw_result_id=raw_result.id,
                status=quality_status,
                check_name="twse_stock_day_payload",
                message=quality_message,
                row_count=row_count,
                is_duplicate=is_duplicate,
                detail_json=None,
            )

            db.add(quality_check)

            parsed_count = 0
            skipped_count = 0
            inserted_count = 0

            if response.ok and quality_status in {"valid", "warning"}:
                parsed_rows, skipped_count = parse_twse_stock_day_raw(
                    raw_text=raw_text,
                    stock_id=stock_id,
                    stock_name=stock_name,
                    source_id=source.id,
                    raw_result_id=raw_result.id,
                    start_date=effective_start,
                    end_date=effective_end,
                )

                parsed_count = len(parsed_rows)
                inserted_count = _save_market_rows(db, parsed_rows)

                total_parsed_count += parsed_count
                total_inserted_count += inserted_count
                total_skipped_count += skipped_count

            effective_status = "success"

            if not response.ok or quality_status == "error":
                effective_status = "error"

            fetch_log.status = effective_status
            fetch_log.ended_at = utc_now()
            fetch_log.duration_ms = int((time.perf_counter() - month_started_perf) * 1000)

            fetch_log.message = (
                f"TWSE stock day backfill completed. "
                f"Data quality: {quality_status}. {quality_message}"
            )
            fetch_log.error_message = None if effective_status == "success" else quality_message

            if effective_status == "success":
                source.last_success_at = utc_now()
                source.last_error_at = None
                source.last_error_message = None
                fetched_month_count += 1
            else:
                source.last_error_at = utc_now()
                source.last_error_message = quality_message

            db.commit()

            month_results.append(
                {
                    "month": month_label,
                    "url": url,
                    "fetch_log_id": fetch_log.id,
                    "raw_result_id": raw_result.id,
                    "http_status_code": response.status_code,
                    "data_quality_status": quality_status,
                    "data_quality_message": quality_message,
                    "row_count": row_count,
                    "parsed_count": parsed_count,
                    "skipped_count": skipped_count,
                    "status": effective_status,
                    "error_message": fetch_log.error_message,
                }
            )

        except Exception as exc:
            db.rollback()

            fetch_log.status = "error"
            fetch_log.ended_at = utc_now()
            fetch_log.duration_ms = int((time.perf_counter() - month_started_perf) * 1000)
            
            fetch_log.message = "TWSE stock day backfill failed."
            fetch_log.error_message = str(exc)

            source.last_error_at = utc_now()
            source.last_error_message = str(exc)

            db.add(fetch_log)
            db.add(source)
            db.commit()

            month_results.append(
                {
                    "month": month_label,
                    "url": url,
                    "fetch_log_id": fetch_log.id,
                    "raw_result_id": raw_result.id if raw_result else None,
                    "http_status_code": None,
                    "data_quality_status": "error",
                    "data_quality_message": str(exc),
                    "row_count": None,
                    "parsed_count": 0,
                    "skipped_count": 0,
                    "status": "error",
                    "error_message": str(exc),
                }
            )

        if index < len(month_starts) - 1 and sleep_seconds > 0:
            time.sleep(sleep_seconds)

    overall_status = "success"

    if any(item["status"] == "error" for item in month_results):
        overall_status = "partial_success" if total_inserted_count > 0 else "error"

    return {
        "stock_id": stock_id,
        "stock_name": stock_name,
        "source_id": source.id,
        "start_date": start_date,
        "end_date": end_date,
        "requested_month_count": len(month_starts),
        "fetched_month_count": fetched_month_count,
        "skipped_existing_month_count": skipped_existing_month_count,
        "parsed_count": total_parsed_count,
        "inserted_count": total_inserted_count,
        "skipped_count": total_skipped_count,
        "status": overall_status,
        "message": "TWSE stock day backfill completed.",
        "months": month_results,
    }


def backfill_tpex_trading_stock(
    db: Session,
    stock_id: str,
    start_date: date,
    end_date: date,
    source_id: int | None = None,
    sleep_seconds: float = 0.8,
    skip_existing_months: bool = False,
) -> dict:
    if end_date < start_date:
        raise ValueError("end_date must be greater than or equal to start_date.")

    source = _get_source(
        db=db,
        source_id=source_id,
        fallback_source_name=TPEX_DAILY_QUOTES_SOURCE_NAME,
    )
    stock_name = _get_stock_name(db, stock_id)
    month_starts = _month_starts(start_date, end_date)

    total_parsed_count = 0
    total_inserted_count = 0
    total_skipped_count = 0
    skipped_existing_month_count = 0
    fetched_month_count = 0

    month_results: list[dict] = []

    headers = {
        "User-Agent": "OpenMarketIntelligence/1.1 (+local development)",
        "Accept": "application/json,text/plain,*/*",
    }

    for index, month_start in enumerate(month_starts):
        month_started_perf = time.perf_counter()
        month_label = month_start.strftime("%Y-%m")
        url = _build_tpex_trading_stock_url(stock_id, month_start)
        month_end = _month_end(month_start)
        effective_start = max(start_date, month_start)
        effective_end = min(end_date, month_end)

        if skip_existing_months:
            existing_count, latest_existing_date = _existing_market_row_stats(
                db=db,
                stock_id=stock_id,
                start_date=effective_start,
                end_date=effective_end,
            )

            if _should_skip_existing_month(
                existing_count=existing_count,
                latest_existing_date=latest_existing_date,
                month_end=month_end,
                effective_end=effective_end,
            ):
                skipped_existing_month_count += 1
                month_results.append(
                    {
                        "month": month_label,
                        "url": url,
                        "fetch_log_id": None,
                        "raw_result_id": None,
                        "http_status_code": None,
                        "data_quality_status": "skipped",
                        "data_quality_message": (
                            f"Skipped because {existing_count} existing daily rows "
                            f"were found in this month."
                        ),
                        "row_count": existing_count,
                        "parsed_count": 0,
                        "skipped_count": 0,
                        "status": "skipped_existing",
                        "error_message": None,
                    }
                )
                continue

        fetch_log = _create_fetch_log(
            db=db,
            source_id=source.id,
            stock_id=stock_id,
            month_start=month_start,
            job_prefix="backfill_tpex",
            message="TPEx trading stock backfill started.",
        )

        raw_result: RawFetchResult | None = None

        try:
            response = requests.post(
                TPEX_TRADING_STOCK_URL,
                data={
                    "code": stock_id,
                    "date": month_start.strftime("%Y/%m/%d"),
                    "response": "json",
                },
                headers=headers,
                timeout=30,
            )
            raw_text = response.text
            content_hash = sha256_text(raw_text)
            content_type = response.headers.get("content-type")

            raw_result = RawFetchResult(
                source_id=source.id,
                fetch_log_id=fetch_log.id,
                fetched_at=datetime.now(timezone.utc),
                url=url,
                method="POST",
                status_code=response.status_code,
                content_type=content_type,
                content_hash=content_hash,
                raw_text=raw_text,
                parser_version="tpex_trading_stock_v1",
                error_message=None if response.ok else f"HTTP {response.status_code}",
            )

            db.add(raw_result)
            db.flush()

            duplicate = (
                db.query(RawFetchResult)
                .filter(RawFetchResult.source_id == source.id)
                .filter(RawFetchResult.content_hash == content_hash)
                .filter(RawFetchResult.id != raw_result.id)
                .first()
            )
            is_duplicate = duplicate is not None

            quality_status = "error"
            quality_message = "TPEx trading stock payload is invalid."
            row_count = 0

            if response.ok:
                payload = json.loads(raw_text)
                tables = payload.get("tables") or []
                first_table = tables[0] if isinstance(tables, list) and tables else {}
                row_count = len(first_table.get("data") or [])

                if payload.get("stat") == "ok":
                    quality_status = "warning" if row_count == 0 else "valid"
                    quality_message = (
                        "TPEx trading stock payload parsed with zero rows."
                        if row_count == 0
                        else "TPEx trading stock payload is valid."
                    )
                else:
                    quality_message = str(payload.get("stat") or quality_message)

            if is_duplicate and quality_status != "error":
                quality_status = "warning"
                quality_message = (
                    f"{quality_message} Raw content hash already exists for this source."
                )

            quality_check = DataQualityCheck(
                source_id=source.id,
                fetch_log_id=fetch_log.id,
                raw_result_id=raw_result.id,
                status=quality_status,
                check_name="tpex_trading_stock_payload",
                message=quality_message,
                row_count=row_count,
                is_duplicate=is_duplicate,
                detail_json=None,
            )

            db.add(quality_check)

            parsed_count = 0
            skipped_count = 0
            inserted_count = 0

            if response.ok and quality_status in {"valid", "warning"}:
                parsed_rows, skipped_count = _parse_tpex_trading_stock_raw(
                    raw_text=raw_text,
                    stock_id=stock_id,
                    stock_name=stock_name,
                    source_id=source.id,
                    raw_result_id=raw_result.id,
                    start_date=effective_start,
                    end_date=effective_end,
                )

                parsed_count = len(parsed_rows)
                inserted_count = _save_market_rows(db, parsed_rows)

                total_parsed_count += parsed_count
                total_inserted_count += inserted_count
                total_skipped_count += skipped_count

            effective_status = "success"

            if not response.ok or quality_status == "error":
                effective_status = "error"

            fetch_log.status = effective_status
            fetch_log.ended_at = utc_now()
            fetch_log.duration_ms = int((time.perf_counter() - month_started_perf) * 1000)
            fetch_log.message = (
                f"TPEx trading stock backfill completed. "
                f"Data quality: {quality_status}. {quality_message}"
            )
            fetch_log.error_message = None if effective_status == "success" else quality_message

            if effective_status == "success":
                source.last_success_at = utc_now()
                source.last_error_at = None
                source.last_error_message = None
                fetched_month_count += 1
            else:
                source.last_error_at = utc_now()
                source.last_error_message = quality_message

            db.commit()

            month_results.append(
                {
                    "month": month_label,
                    "url": url,
                    "fetch_log_id": fetch_log.id,
                    "raw_result_id": raw_result.id,
                    "http_status_code": response.status_code,
                    "data_quality_status": quality_status,
                    "data_quality_message": quality_message,
                    "row_count": row_count,
                    "parsed_count": parsed_count,
                    "skipped_count": skipped_count,
                    "status": effective_status,
                    "error_message": fetch_log.error_message,
                }
            )

        except Exception as exc:
            db.rollback()

            fetch_log.status = "error"
            fetch_log.ended_at = utc_now()
            fetch_log.duration_ms = int((time.perf_counter() - month_started_perf) * 1000)
            fetch_log.message = "TPEx trading stock backfill failed."
            fetch_log.error_message = str(exc)

            source.last_error_at = utc_now()
            source.last_error_message = str(exc)

            db.add(fetch_log)
            db.add(source)
            db.commit()

            month_results.append(
                {
                    "month": month_label,
                    "url": url,
                    "fetch_log_id": fetch_log.id,
                    "raw_result_id": raw_result.id if raw_result else None,
                    "http_status_code": None,
                    "data_quality_status": "error",
                    "data_quality_message": str(exc),
                    "row_count": None,
                    "parsed_count": 0,
                    "skipped_count": 0,
                    "status": "error",
                    "error_message": str(exc),
                }
            )

        if index < len(month_starts) - 1 and sleep_seconds > 0:
            time.sleep(sleep_seconds)

    overall_status = "success"

    if any(item["status"] == "error" for item in month_results):
        overall_status = "partial_success" if total_inserted_count > 0 else "error"

    return {
        "stock_id": stock_id,
        "stock_name": stock_name,
        "source_id": source.id,
        "start_date": start_date,
        "end_date": end_date,
        "requested_month_count": len(month_starts),
        "fetched_month_count": fetched_month_count,
        "skipped_existing_month_count": skipped_existing_month_count,
        "parsed_count": total_parsed_count,
        "inserted_count": total_inserted_count,
        "skipped_count": total_skipped_count,
        "status": overall_status,
        "message": "TPEx trading stock backfill completed.",
        "months": month_results,
    }
