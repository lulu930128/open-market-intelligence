"""Add compact job result summaries.

Revision ID: 20260605_0008
Revises: 20260531_0007
Create Date: 2026-06-05 00:00:00
"""

from collections.abc import Sequence
from typing import Any
import json

import sqlalchemy as sa
from alembic import op


revision: str = "20260605_0008"
down_revision: str | Sequence[str] | None = "20260531_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SUMMARY_COUNT_KEYS = (
    "requested_count",
    "requested_stock_count",
    "total_count",
    "symbol_count",
    "success_count",
    "current_count",
    "partial_success_count",
    "warning_count",
    "error_count",
    "failed_count",
    "symbol_error_count",
    "inserted_count",
    "updated_count",
    "fetched_count",
    "skipped_existing_count",
    "skipped_count",
)
FAILED_RESULT_ITEM_LIMIT = 4


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _has_column(table_name: str, column_name: str) -> bool:
    return any(
        column["name"] == column_name
        for column in sa.inspect(op.get_bind()).get_columns(table_name)
    )


def _json_default(value: Any) -> str:
    return str(value)


def _to_json(value: Any) -> str | None:
    if value is None:
        return None

    return json.dumps(value, ensure_ascii=False, default=_json_default, sort_keys=True)


def _from_json(value: str | None) -> Any:
    if value is None:
        return None

    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _summary_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()

    return None


def _summary_number(value: Any) -> int | float | None:
    if isinstance(value, bool):
        return None

    return value if isinstance(value, (int, float)) else None


def _compact_result_item(item: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key in (
        "stock_id",
        "stock_name",
        "symbol",
        "source_name",
        "category",
        "resource",
        "trade_date",
        "status",
        "message",
        "error_message",
    ):
        value = item.get(key)
        if value is not None:
            compact[key] = value

    return compact


def _failed_result_items(rows: Any) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []

    failed: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue

        status_value = _summary_string(row.get("status"))
        error_message = _summary_string(row.get("error_message")) or _summary_string(row.get("message"))
        if status_value not in {"error", "partial_success"} and not _summary_string(row.get("error_message")):
            continue

        compact = _compact_result_item(row)
        if error_message and "error_message" not in compact:
            compact["error_message"] = error_message
        failed.append(compact)

        if len(failed) >= FAILED_RESULT_ITEM_LIMIT:
            break

    return failed


def _error_items(errors: Any) -> list[dict[str, Any]]:
    if not isinstance(errors, list):
        return []

    items: list[dict[str, Any]] = []
    for row in errors[:FAILED_RESULT_ITEM_LIMIT]:
        if not isinstance(row, dict):
            continue

        compact = _compact_result_item({**row, "status": row.get("status") or "error"})
        message = _summary_string(row.get("error_message")) or _summary_string(row.get("message"))
        if message and "error_message" not in compact:
            compact["error_message"] = message
        items.append(compact)

    return items


def _summarize_result(value: Any) -> Any:
    if not isinstance(value, dict):
        return value

    summary: dict[str, Any] = {}
    status_value = _summary_string(value.get("status"))
    message_value = _summary_string(value.get("message"))

    if status_value:
        summary["status"] = status_value
    if message_value:
        summary["message"] = message_value

    for key in SUMMARY_COUNT_KEYS:
        if (number_value := _summary_number(value.get(key))) is not None:
            summary[key] = number_value

    rows = value.get("results")
    if isinstance(rows, list):
        summary["result_count"] = len(rows)
        failed_rows = _failed_result_items(rows)
        if failed_rows:
            summary["results"] = failed_rows

    errors = value.get("errors")
    if isinstance(errors, list):
        summary["errors_count"] = len(errors)
        if "error_count" not in summary and errors:
            summary["error_count"] = len(errors)
        if "results" not in summary:
            error_rows = _error_items(errors)
            if error_rows:
                summary["results"] = error_rows

    return summary or None


def upgrade() -> None:
    if not _has_table("job_run"):
        return

    if not _has_column("job_run", "result_summary_json"):
        op.add_column("job_run", sa.Column("result_summary_json", sa.Text(), nullable=True))

    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            """
            SELECT id, result_json
            FROM job_run
            WHERE result_json IS NOT NULL
              AND (result_summary_json IS NULL OR result_summary_json = '')
            """
        )
    ).mappings()

    for row in rows:
        summary_json = _to_json(_summarize_result(_from_json(row["result_json"])))
        if summary_json is None:
            continue

        connection.execute(
            sa.text(
                """
                UPDATE job_run
                SET result_summary_json = :summary_json
                WHERE id = :id
                """
            ),
            {"id": row["id"], "summary_json": summary_json},
        )


def downgrade() -> None:
    if _has_table("job_run") and _has_column("job_run", "result_summary_json"):
        op.drop_column("job_run", "result_summary_json")
