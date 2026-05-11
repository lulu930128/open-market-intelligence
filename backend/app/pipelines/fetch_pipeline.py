from time import perf_counter

from sqlalchemy.orm import Session

from app.connectors.factory import UnsupportedConnectorError, get_connector
from app.db.models import FetchLog, RawFetchResult, SourceRegistry, utc_now
from app.sources.service import SourceNotFoundError, get_source
from app.utils.hash import sha256_text


MAX_RAW_TEXT_CHARS = 2_000_000


def run_source_fetch(db: Session, source_id: int) -> dict:
    source: SourceRegistry = get_source(db, source_id)

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
        result = connector.fetch(source)

        raw_text = result.raw_text

        if raw_text and len(raw_text) > MAX_RAW_TEXT_CHARS:
            raw_text = raw_text[:MAX_RAW_TEXT_CHARS]

        content_hash = sha256_text(result.raw_text)

        raw_result = RawFetchResult(
            source_id=source.id,
            fetch_log_id=fetch_log.id,
            fetched_at=result.fetched_at,
            url=result.url,
            method=result.method,
            status_code=result.status_code,
            content_type=result.content_type,
            content_hash=content_hash,
            raw_text=raw_text,
            parser_version=None,
            error_message=result.error_message,
        )

        db.add(raw_result)

        fetch_log.status = result.status
        fetch_log.message = result.message
        fetch_log.error_message = result.error_message

        if result.status == "success":
            source.last_success_at = utc_now()
            source.last_error_at = None
            source.last_error_message = None
        else:
            source.last_error_at = utc_now()
            source.last_error_message = result.error_message

        ended_at = utc_now()
        fetch_log.ended_at = ended_at
        fetch_log.duration_ms = int((perf_counter() - started_perf) * 1000)

        db.commit()
        db.refresh(fetch_log)
        db.refresh(raw_result)

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

    if source.parser_type != "twse_daily_trading":
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

    from app.pipelines.parse_pipeline import parse_twse_daily_raw_result

    parse_result = parse_twse_daily_raw_result(db, raw_result_id)

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


__all__ = ["run_source_fetch", "SourceNotFoundError"]