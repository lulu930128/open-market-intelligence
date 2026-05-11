import json
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.models import RawFetchResult, SourceRegistry


@dataclass
class DataQualityResult:
    status: str
    check_name: str
    message: str

    row_count: int | None = None
    is_duplicate: bool = False
    detail_json: str | None = None


def _is_duplicate_content(
    db: Session,
    source_id: int,
    content_hash: str | None,
) -> bool:
    if not content_hash:
        return False

    existing = (
        db.query(RawFetchResult)
        .filter(RawFetchResult.source_id == source_id)
        .filter(RawFetchResult.content_hash == content_hash)
        .first()
    )

    return existing is not None


def _with_duplicate_status(
    result: DataQualityResult,
    is_duplicate: bool,
) -> DataQualityResult:
    if not is_duplicate:
        return result

    if result.status == "error":
        result.is_duplicate = True
        return result

    result.status = "warning"
    result.is_duplicate = True
    result.message = f"{result.message} Raw content hash already exists for this source."
    return result


def check_raw_data_quality(
    db: Session,
    source: SourceRegistry,
    raw_text: str | None,
    status_code: int | None,
    content_type: str | None,
    content_hash: str | None,
) -> DataQualityResult:
    is_duplicate = _is_duplicate_content(
        db=db,
        source_id=source.id,
        content_hash=content_hash,
    )

    if status_code is None:
        return DataQualityResult(
            status="error",
            check_name="http_response",
            message="No HTTP status code returned.",
            is_duplicate=is_duplicate,
        )

    if status_code < 200 or status_code >= 300:
        return DataQualityResult(
            status="error",
            check_name="http_response",
            message=f"HTTP status code is not successful: {status_code}.",
            is_duplicate=is_duplicate,
        )

    if raw_text is None or raw_text.strip() == "":
        return DataQualityResult(
            status="error",
            check_name="raw_text",
            message="Raw response text is empty.",
            is_duplicate=is_duplicate,
        )

    parser_type = source.parser_type

    if parser_type == "twse_daily_trading":
        result = _check_twse_daily_payload(raw_text)
        return _with_duplicate_status(result, is_duplicate)

    if parser_type == "gdelt_doc":
        result = _check_gdelt_doc_payload(raw_text)
        return _with_duplicate_status(result, is_duplicate)

    result = DataQualityResult(
        status="valid",
        check_name="basic_raw_response",
        message="Raw response is non-empty.",
        row_count=None,
        is_duplicate=is_duplicate,
        detail_json=json.dumps(
            {
                "content_type": content_type,
                "parser_type": parser_type,
            },
            ensure_ascii=False,
        ),
    )

    return _with_duplicate_status(result, is_duplicate)


def _check_twse_daily_payload(raw_text: str) -> DataQualityResult:
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        return DataQualityResult(
            status="error",
            check_name="twse_daily_json",
            message=f"TWSE daily payload is not valid JSON: {exc}.",
        )

    if not isinstance(payload, list):
        return DataQualityResult(
            status="error",
            check_name="twse_daily_shape",
            message="TWSE daily payload should be a JSON list.",
        )

    row_count = len(payload)

    if row_count == 0:
        return DataQualityResult(
            status="error",
            check_name="twse_daily_empty",
            message="TWSE daily payload is an empty list.",
            row_count=0,
        )

    valid_row_count = 0

    for row in payload[:50]:
        if not isinstance(row, dict):
            continue

        if row.get("Code") or row.get("證券代號"):
            valid_row_count += 1

    if valid_row_count == 0:
        return DataQualityResult(
            status="error",
            check_name="twse_daily_required_fields",
            message="TWSE daily payload does not contain expected stock code fields.",
            row_count=row_count,
            detail_json=json.dumps(
                {
                    "sample_keys": list(payload[0].keys()) if isinstance(payload[0], dict) else None,
                },
                ensure_ascii=False,
            ),
        )

    return DataQualityResult(
        status="valid",
        check_name="twse_daily_payload",
        message="TWSE daily payload is valid.",
        row_count=row_count,
        detail_json=json.dumps(
            {
                "sample_checked_rows": min(row_count, 50),
                "valid_sample_rows": valid_row_count,
            },
            ensure_ascii=False,
        ),
    )


def _check_gdelt_doc_payload(raw_text: str) -> DataQualityResult:
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        return DataQualityResult(
            status="error",
            check_name="gdelt_doc_json",
            message=f"GDELT payload is not valid JSON: {exc}.",
        )

    if not isinstance(payload, dict):
        return DataQualityResult(
            status="error",
            check_name="gdelt_doc_shape",
            message="GDELT doc payload should be a JSON object.",
        )

    articles = payload.get("articles")

    if articles is None:
        return DataQualityResult(
            status="warning",
            check_name="gdelt_doc_no_articles_field",
            message="GDELT payload does not contain articles field.",
            row_count=0,
            detail_json=json.dumps(
                {
                    "top_level_keys": list(payload.keys()),
                },
                ensure_ascii=False,
            ),
        )

    if not isinstance(articles, list):
        return DataQualityResult(
            status="error",
            check_name="gdelt_doc_articles_shape",
            message="GDELT articles field should be a list.",
        )

    if len(articles) == 0:
        return DataQualityResult(
            status="warning",
            check_name="gdelt_doc_empty_articles",
            message="GDELT query returned zero articles.",
            row_count=0,
        )

    return DataQualityResult(
        status="valid",
        check_name="gdelt_doc_payload",
        message="GDELT doc payload is valid.",
        row_count=len(articles),
    )