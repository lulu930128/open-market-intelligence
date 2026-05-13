from time import perf_counter
from types import SimpleNamespace

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.connectors.factory import UnsupportedConnectorError, get_connector
from app.db.models import DataQualityCheck, FetchLog, MarketDailyPrice, RawFetchResult, SourceRegistry, utc_now
from app.quality.checker import check_raw_data_quality
from app.sources.service import SourceNotFoundError, get_source
from app.utils.hash import sha256_text


MAX_RAW_TEXT_CHARS = 2_000_000


LATEST_MARKET_TRADE_DATE_PLACEHOLDERS = (
    "{latest_market_trade_date_yyyyMMdd}",
    "{latest_market_trade_date_yyyymmdd}",
)


def _get_latest_market_trade_date_yyyymmdd(db: Session) -> str:
    latest_trade_date = db.query(func.max(MarketDailyPrice.trade_date)).scalar()

    if latest_trade_date is None:
        raise ValueError(
            "Cannot render source endpoint URL: no market_daily_price trade_date found. "
            "Refresh TWSE OpenAPI Daily Trading before TWSE Institutional Trading T86."
        )

    return latest_trade_date.strftime("%Y%m%d")


def _render_endpoint_url_with_db_context(db: Session, endpoint_url: str | None) -> str | None:
    if endpoint_url is None:
        return None

    if not any(placeholder in endpoint_url for placeholder in LATEST_MARKET_TRADE_DATE_PLACEHOLDERS):
        return endpoint_url

    latest_trade_date = _get_latest_market_trade_date_yyyymmdd(db)

    for placeholder in LATEST_MARKET_TRADE_DATE_PLACEHOLDERS:
        endpoint_url = endpoint_url.replace(placeholder, latest_trade_date)

    return endpoint_url


def _build_source_for_fetch(db: Session, source: SourceRegistry) -> SourceRegistry | SimpleNamespace:
    rendered_endpoint_url = _render_endpoint_url_with_db_context(db, source.endpoint_url)

    if rendered_endpoint_url == source.endpoint_url:
        return source

    # Do not mutate the ORM source object. The rendered URL is only for this fetch run;
    # source_registry.endpoint_url should keep the placeholder template.
    return SimpleNamespace(
        id=source.id,
        source_name=source.source_name,
        source_type=source.source_type,
        category=source.category,
        endpoint_url=rendered_endpoint_url,
        enabled=source.enabled,
        fetch_interval_minutes=source.fetch_interval_minutes,
        priority=source.priority,
        parser_type=source.parser_type,
        auth_type=source.auth_type,
        reliability_level=source.reliability_level,
    )


def run_source_fetch(db: Session, source_id: int) -> dict:
    source: SourceRegistry = get_source(db, source_id)

    if not source.enabled:
        return {
            "source_id": source.id,
            "source_name": source.source_name,
            "fetch_log_id": 0,
            "raw_result_id": None,
            "data_quality_status": None,
            "data_quality_message": None,
            "data_quality_row_count": None,
            "is_duplicate": None,
            "status": "skipped",
            "status_code": None,
            "content_hash": None,
            "duration_ms": 0,
            "message": "Source is disabled. Fetch skipped.",
            "error_message": None,
            "fetched_at": utc_now(),
        }

    started_perf = perf_counter()

    fetch_log = FetchLog(
        source_id=source.id,
        job_name=f"manual_run:{source.source_name}",
        status="running",
        started_at=utc_now(),
        message="Manual source fetch started.",
    )

    db.add(fetch_log)
    db.commit()
    db.refresh(fetch_log)

    raw_result: RawFetchResult | None = None

    try:
        connector = get_connector(source)
        fetch_source = _build_source_for_fetch(db=db, source=source)
        result = connector.fetch(fetch_source)

        raw_text = result.raw_text

        if raw_text and len(raw_text) > MAX_RAW_TEXT_CHARS:
            stored_raw_text = raw_text[:MAX_RAW_TEXT_CHARS]
        else:
            stored_raw_text = raw_text

        content_hash = sha256_text(result.raw_text)

        quality_result = check_raw_data_quality(
            db=db,
            source=source,
            raw_text=result.raw_text,
            status_code=result.status_code,
            content_type=result.content_type,
            content_hash=content_hash,
        )

        raw_result = RawFetchResult(
            source_id=source.id,
            fetch_log_id=fetch_log.id,
            fetched_at=result.fetched_at,
            url=result.url,
            method=result.method,
            status_code=result.status_code,
            content_type=result.content_type,
            content_hash=content_hash,
            raw_text=stored_raw_text,
            parser_version=None,
            error_message=result.error_message,
        )

        db.add(raw_result)
        db.flush()

        data_quality_check = DataQualityCheck(
            source_id=source.id,
            fetch_log_id=fetch_log.id,
            raw_result_id=raw_result.id,
            status=quality_result.status,
            check_name=quality_result.check_name,
            message=quality_result.message,
            row_count=quality_result.row_count,
            is_duplicate=quality_result.is_duplicate,
            detail_json=quality_result.detail_json,
        )

        db.add(data_quality_check)

        effective_status = result.status

        if result.status == "success" and quality_result.status == "error":
            effective_status = "error"

        fetch_log.status = effective_status

        fetch_log.message = (
            f"{result.message or 'Fetch completed.'} "
            f"Data quality: {quality_result.status}. {quality_result.message}"
        )

        if result.error_message:
            fetch_log.error_message = result.error_message
        elif quality_result.status == "error":
            fetch_log.error_message = quality_result.message
        else:
            fetch_log.error_message = None

        if effective_status == "success":
            source.last_success_at = utc_now()
            source.last_error_at = None
            source.last_error_message = None
        else:
            source.last_error_at = utc_now()
            source.last_error_message = fetch_log.error_message

        ended_at = utc_now()
        fetch_log.ended_at = ended_at
        fetch_log.duration_ms = int((perf_counter() - started_perf) * 1000)

        db.commit()
        db.refresh(fetch_log)
        db.refresh(raw_result)
        db.refresh(data_quality_check)

        return {
            "source_id": source.id,
            "source_name": source.source_name,
            "fetch_log_id": fetch_log.id,
            "raw_result_id": raw_result.id,
            "status": fetch_log.status,
            "status_code": raw_result.status_code,
            "content_hash": raw_result.content_hash,
            "duration_ms": fetch_log.duration_ms,
            "message": fetch_log.message,
            "error_message": fetch_log.error_message,
            "fetched_at": raw_result.fetched_at,
            "data_quality_status": data_quality_check.status,
            "data_quality_message": data_quality_check.message,
            "data_quality_row_count": data_quality_check.row_count,
            "is_duplicate": data_quality_check.is_duplicate,
        }

    except UnsupportedConnectorError as exc:
        fetch_log.status = "error"
        fetch_log.error_message = str(exc)
        fetch_log.message = "Unsupported connector."

        source.last_error_at = utc_now()
        source.last_error_message = str(exc)

        fetch_log.ended_at = utc_now()
        fetch_log.duration_ms = int((perf_counter() - started_perf) * 1000)

        db.commit()

        return {
            "source_id": source.id,
            "source_name": source.source_name,
            "fetch_log_id": fetch_log.id,
            "raw_result_id": None,
            "status": "error",
            "status_code": None,
            "content_hash": None,
            "duration_ms": fetch_log.duration_ms,
            "message": fetch_log.message,
            "error_message": fetch_log.error_message,
            "fetched_at": fetch_log.started_at,
        }

    except Exception as exc:
        db.rollback()

        fetch_log.status = "error"
        fetch_log.error_message = str(exc)
        fetch_log.message = "Unexpected fetch error."
        fetch_log.ended_at = utc_now()
        fetch_log.duration_ms = int((perf_counter() - started_perf) * 1000)

        source.last_error_at = utc_now()
        source.last_error_message = str(exc)

        db.add(fetch_log)
        db.add(source)
        db.commit()

        raise


def refresh_source(db: Session, source_id: int) -> dict:
    source = get_source(db, source_id)

    if not source.enabled:
        return {
            "source_id": source.id,
            "source_name": source.source_name,
            "fetch_status": "skipped",
            "fetch_log_id": 0,
            "raw_result_id": None,
            "parse_status": "skipped",
            "parser_type": source.parser_type,
            "parsed_count": None,
            "skipped_count": None,
            "inserted_count": None,
            "data_quality_status": None,
            "data_quality_message": None,
            "data_quality_row_count": None,
            "is_duplicate": None,
            "message": "Source is disabled. Refresh skipped.",
            "error_message": None,
            "fetched_at": utc_now(),
        }

    fetch_result = run_source_fetch(db, source_id)

    if fetch_result["status"] != "success":
        return {
            "source_id": source.id,
            "source_name": source.source_name,
            "fetch_status": fetch_result["status"],
            "fetch_log_id": fetch_result["fetch_log_id"],
            "raw_result_id": fetch_result["raw_result_id"],
            "parse_status": None,
            "parser_type": source.parser_type,
            "parsed_count": None,
            "skipped_count": None,
            "inserted_count": None,
            "message": "Fetch failed. Parse skipped.",
            "error_message": fetch_result["error_message"],
            "fetched_at": fetch_result["fetched_at"],
        }

    raw_result_id = fetch_result["raw_result_id"]

    if raw_result_id is None:
        return {
            "source_id": source.id,
            "source_name": source.source_name,
            "fetch_status": fetch_result["status"],
            "fetch_log_id": fetch_result["fetch_log_id"],
            "raw_result_id": None,
            "parse_status": "skipped",
            "parser_type": source.parser_type,
            "parsed_count": None,
            "skipped_count": None,
            "inserted_count": None,
            "message": "Fetch completed but no raw result was created.",
            "error_message": None,
            "fetched_at": fetch_result["fetched_at"],
        }

    from app.pipelines.parse_pipeline import has_parser, parse_raw_result_by_parser_type

    if not has_parser(source.parser_type):
        return {
            "source_id": source.id,
            "source_name": source.source_name,
            "fetch_status": fetch_result["status"],
            "fetch_log_id": fetch_result["fetch_log_id"],
            "raw_result_id": raw_result_id,
            "parse_status": "skipped",
            "parser_type": source.parser_type,
            "parsed_count": None,
            "skipped_count": None,
            "inserted_count": None,
            "message": f"No auto parser configured for parser_type='{source.parser_type}'.",
            "error_message": None,
            "fetched_at": fetch_result["fetched_at"],
        }

    parse_result = parse_raw_result_by_parser_type(
        db=db,
        raw_result_id=raw_result_id,
        parser_type=source.parser_type,
    )

    return {
        "source_id": source.id,
        "source_name": source.source_name,
        "fetch_status": fetch_result["status"],
        "fetch_log_id": fetch_result["fetch_log_id"],
        "raw_result_id": raw_result_id,
        "parse_status": parse_result["status"],
        "parser_type": parse_result["parser_type"],
        "parsed_count": parse_result["parsed_count"],
        "skipped_count": parse_result["skipped_count"],
        "inserted_count": parse_result["inserted_count"],
        "message": "Source refreshed and parsed successfully.",
        "error_message": None,
        "fetched_at": fetch_result["fetched_at"],
    }


__all__ = ["run_source_fetch", "refresh_source", "SourceNotFoundError"]
