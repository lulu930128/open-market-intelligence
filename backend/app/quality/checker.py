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

    if parser_type == "twse_institutional_trade":
        result = _check_twse_institutional_trade_payload(raw_text)
        return _with_duplicate_status(result, is_duplicate)

    if parser_type == "twse_margin_trading":
        result = _check_twse_margin_trading_payload(raw_text)
        return _with_duplicate_status(result, is_duplicate)

    if parser_type in {"tpex_daily_quotes", "tpex_company_profile", "tpex_margin_trading"}:
        result = _check_tpex_table_payload(raw_text, parser_type)
        return _with_duplicate_status(result, is_duplicate)

    if parser_type == "tpex_institutional_trade":
        result = _check_tpex_institutional_bundle(raw_text)
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


def _check_twse_institutional_trade_payload(raw_text: str) -> DataQualityResult:
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        return DataQualityResult(
            status="error",
            check_name="twse_institutional_json",
            message=f"TWSE institutional payload is not valid JSON: {exc}.",
        )

    if not isinstance(payload, dict):
        return DataQualityResult(
            status="error",
            check_name="twse_institutional_shape",
            message="TWSE institutional payload should be a JSON object.",
        )

    data = payload.get("data")
    fields = payload.get("fields")

    if not isinstance(data, list):
        return DataQualityResult(
            status="error",
            check_name="twse_institutional_data_shape",
            message="TWSE institutional data field should be a list.",
        )

    row_count = len(data)

    if row_count == 0:
        return DataQualityResult(
            status="warning",
            check_name="twse_institutional_empty",
            message="TWSE institutional payload contains no rows.",
            row_count=0,
        )

    if not isinstance(fields, list) or "證券代號" not in fields:
        return DataQualityResult(
            status="warning",
            check_name="twse_institutional_fields",
            message="TWSE institutional payload does not expose the expected fields list.",
            row_count=row_count,
            detail_json=json.dumps({"fields": fields}, ensure_ascii=False),
        )

    return DataQualityResult(
        status="valid",
        check_name="twse_institutional_payload",
        message="TWSE institutional payload is valid.",
        row_count=row_count,
        detail_json=json.dumps(
            {
                "date": payload.get("date"),
                "title": payload.get("title"),
                "sample_fields": fields[:5],
            },
            ensure_ascii=False,
        ),
    )


def _find_twse_margin_table(payload: dict) -> dict | None:
    tables = payload.get("tables")

    if isinstance(tables, list):
        for table in tables:
            if not isinstance(table, dict):
                continue

            if isinstance(table.get("data"), list) and isinstance(table.get("fields"), list):
                return table

    if isinstance(payload.get("data"), list) and isinstance(payload.get("fields"), list):
        return payload

    return None


def _check_twse_margin_trading_payload(raw_text: str) -> DataQualityResult:
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        return DataQualityResult(
            status="error",
            check_name="twse_margin_json",
            message=f"TWSE margin trading payload is not valid JSON: {exc}.",
        )

    if not isinstance(payload, dict):
        return DataQualityResult(
            status="error",
            check_name="twse_margin_shape",
            message="TWSE margin trading payload should be a JSON object.",
        )

    table = _find_twse_margin_table(payload)

    if table is None:
        return DataQualityResult(
            status="error",
            check_name="twse_margin_table",
            message="TWSE margin trading payload does not contain a table with fields and data.",
        )

    data = table.get("data")
    fields = table.get("fields")

    if not isinstance(data, list):
        return DataQualityResult(
            status="error",
            check_name="twse_margin_data_shape",
            message="TWSE margin trading data field should be a list.",
        )

    row_count = len(data)

    if row_count == 0:
        return DataQualityResult(
            status="warning",
            check_name="twse_margin_empty",
            message="TWSE margin trading payload contains no rows.",
            row_count=0,
        )

    if not isinstance(fields, list) or "代號" not in fields or "名稱" not in fields:
        return DataQualityResult(
            status="warning",
            check_name="twse_margin_fields",
            message="TWSE margin trading payload does not expose the expected fields list.",
            row_count=row_count,
            detail_json=json.dumps({"fields": fields}, ensure_ascii=False),
        )

    return DataQualityResult(
        status="valid",
        check_name="twse_margin_payload",
        message="TWSE margin trading payload is valid.",
        row_count=row_count,
        detail_json=json.dumps(
            {
                "date": payload.get("date"),
                "title": table.get("title"),
                "sample_fields": fields[:8],
            },
            ensure_ascii=False,
        ),
    )


def _find_tpex_table(payload: dict) -> dict | None:
    tables = payload.get("tables")

    if isinstance(tables, list):
        for table in tables:
            if not isinstance(table, dict):
                continue

            if isinstance(table.get("data"), list):
                return table

    if isinstance(payload.get("data"), list):
        return payload

    return None


def _check_tpex_table_payload(raw_text: str, parser_type: str) -> DataQualityResult:
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        return DataQualityResult(
            status="error",
            check_name="tpex_json",
            message=f"TPEx payload is not valid JSON: {exc}.",
        )

    if parser_type == "tpex_daily_quotes" and isinstance(payload, list):
        rows = [row for row in payload if isinstance(row, dict)]
        if not rows:
            return DataQualityResult(
                status="warning",
                check_name="tpex_empty",
                message="TPEx OpenAPI payload contains no rows.",
                row_count=0,
            )

        return DataQualityResult(
            status="valid",
            check_name="tpex_openapi_payload",
            message="TPEx OpenAPI list payload is valid.",
            row_count=len(rows),
            detail_json=json.dumps(
                {
                    "parser_type": parser_type,
                    "sample_fields": sorted(rows[0].keys())[:8],
                },
                ensure_ascii=False,
            ),
        )

    if not isinstance(payload, dict):
        return DataQualityResult(
            status="error",
            check_name="tpex_shape",
            message="TPEx payload should be a JSON object.",
        )

    if payload.get("stat") not in {None, "ok"}:
        return DataQualityResult(
            status="error",
            check_name="tpex_stat",
            message=f"TPEx payload status is not ok: {payload.get('stat')}.",
        )

    table = _find_tpex_table(payload)

    if table is None:
        return DataQualityResult(
            status="error",
            check_name="tpex_table",
            message="TPEx payload does not contain a table with data.",
        )

    data = table.get("data")
    row_count = len(data) if isinstance(data, list) else 0

    if row_count == 0:
        return DataQualityResult(
            status="warning",
            check_name="tpex_empty",
            message="TPEx payload contains no rows.",
            row_count=0,
        )

    return DataQualityResult(
        status="valid",
        check_name="tpex_table_payload",
        message="TPEx table payload is valid.",
        row_count=row_count,
        detail_json=json.dumps(
            {
                "date": payload.get("date"),
                "parser_type": parser_type,
                "sample_fields": table.get("fields", [])[:8],
            },
            ensure_ascii=False,
        ),
    )


def _check_tpex_institutional_bundle(raw_text: str) -> DataQualityResult:
    try:
        bundle = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        return DataQualityResult(
            status="error",
            check_name="tpex_institutional_bundle_json",
            message=f"TPEx institutional bundle is not valid JSON: {exc}.",
        )

    if not isinstance(bundle, dict):
        return DataQualityResult(
            status="error",
            check_name="tpex_institutional_bundle_shape",
            message="TPEx institutional bundle should be a JSON object.",
        )

    required_keys = {
        "foreign_buy",
        "foreign_sell",
        "investment_trust_buy",
        "investment_trust_sell",
        "dealer_buy",
        "dealer_sell",
    }
    missing_keys = sorted(required_keys - set(bundle.keys()))

    if missing_keys:
        return DataQualityResult(
            status="error",
            check_name="tpex_institutional_bundle_keys",
            message=f"TPEx institutional bundle is missing keys: {', '.join(missing_keys)}.",
        )

    row_counts: dict[str, int] = {}
    dates: dict[str, str | None] = {}

    for key in sorted(required_keys):
        entry = bundle.get(key)

        if not isinstance(entry, dict):
            return DataQualityResult(
                status="error",
                check_name="tpex_institutional_entry_shape",
                message=f"TPEx institutional bundle entry '{key}' should be an object.",
            )

        if entry.get("status_code") != 200:
            return DataQualityResult(
                status="error",
                check_name="tpex_institutional_entry_http",
                message=f"TPEx institutional bundle entry '{key}' returned HTTP {entry.get('status_code')}.",
            )

        raw_entry_text = entry.get("raw_text")

        if not isinstance(raw_entry_text, str) or raw_entry_text.strip() == "":
            return DataQualityResult(
                status="error",
                check_name="tpex_institutional_entry_empty",
                message=f"TPEx institutional bundle entry '{key}' is empty.",
            )

        try:
            payload = json.loads(raw_entry_text)
        except json.JSONDecodeError as exc:
            return DataQualityResult(
                status="error",
                check_name="tpex_institutional_entry_json",
                message=f"TPEx institutional entry '{key}' is not valid JSON: {exc}.",
            )

        if not isinstance(payload, dict):
            return DataQualityResult(
                status="error",
                check_name="tpex_institutional_entry_payload_shape",
                message=f"TPEx institutional entry '{key}' should be a JSON object.",
            )

        if payload.get("stat") != "ok":
            return DataQualityResult(
                status="error",
                check_name="tpex_institutional_entry_stat",
                message=f"TPEx institutional entry '{key}' status is not ok: {payload.get('stat')}.",
            )

        table = _find_tpex_table(payload)

        if table is None or not isinstance(table.get("data"), list):
            return DataQualityResult(
                status="error",
                check_name="tpex_institutional_entry_table",
                message=f"TPEx institutional entry '{key}' does not contain a data table.",
            )

        row_counts[key] = len(table["data"])
        dates[key] = payload.get("date")

    row_count = sum(row_counts.values())

    if row_count == 0:
        return DataQualityResult(
            status="warning",
            check_name="tpex_institutional_bundle_empty",
            message="TPEx institutional bundle contains no rows.",
            row_count=0,
        )

    return DataQualityResult(
        status="valid",
        check_name="tpex_institutional_bundle",
        message="TPEx institutional bundle is valid.",
        row_count=row_count,
        detail_json=json.dumps(
            {
                "row_counts": row_counts,
                "dates": dates,
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
