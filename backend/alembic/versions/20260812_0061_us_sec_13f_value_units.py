"""Normalize SEC 13F value units across the 2023 reporting change.

Revision ID: 20260812_0061
Revises: 20260812_0060
Create Date: 2026-08-12 20:30:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260812_0061"
down_revision: str | Sequence[str] | None = "20260812_0060"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _rename(table: str, old: str, new: str) -> None:
    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}
    if old in columns and new not in columns:
        op.alter_column(
            table,
            old,
            new_column_name=new,
            existing_type=sa.Text(),
            existing_nullable=True,
        )


def upgrade() -> None:
    _rename(
        "us_sec_13f_warehouse_partition",
        "total_reported_value_thousands_text",
        "total_reported_value_usd_text",
    )
    _rename(
        "us_sec_13f_filing",
        "table_value_total_thousands_text",
        "table_value_total_raw_text",
    )
    filing_columns = {
        item["name"]
        for item in sa.inspect(op.get_bind()).get_columns("us_sec_13f_filing")
    }
    if "table_value_unit" not in filing_columns:
        op.add_column(
            "us_sec_13f_filing",
            sa.Column("table_value_unit", sa.String(30), nullable=True),
        )
    if "table_value_total_usd_text" not in filing_columns:
        op.add_column(
            "us_sec_13f_filing",
            sa.Column("table_value_total_usd_text", sa.Text(), nullable=True),
        )
    op.execute(
        sa.text(
            "UPDATE us_sec_13f_filing SET "
            "table_value_unit = CASE "
            "WHEN filing_date >= '2023-01-03' THEN 'usd' ELSE 'usd_thousands' END, "
            "table_value_total_usd_text = CASE "
            "WHEN table_value_total_raw_text IS NULL THEN NULL "
            "WHEN filing_date >= '2023-01-03' THEN table_value_total_raw_text "
            "ELSE CAST(CAST(table_value_total_raw_text AS NUMERIC) * 1000 AS TEXT) END"
        )
    )
    for old, new in (
        ("reported_long_value_thousands_text", "reported_long_value_usd_text"),
        ("reported_put_value_thousands_text", "reported_put_value_usd_text"),
        ("reported_call_value_thousands_text", "reported_call_value_usd_text"),
        ("unresolved_value_thousands_text", "unresolved_value_usd_text"),
    ):
        _rename("us_sec_13f_symbol_quarter", old, new)


def downgrade() -> None:
    for new, old in (
        ("reported_long_value_usd_text", "reported_long_value_thousands_text"),
        ("reported_put_value_usd_text", "reported_put_value_thousands_text"),
        ("reported_call_value_usd_text", "reported_call_value_thousands_text"),
        ("unresolved_value_usd_text", "unresolved_value_thousands_text"),
    ):
        _rename("us_sec_13f_symbol_quarter", new, old)
    filing_columns = {
        item["name"]
        for item in sa.inspect(op.get_bind()).get_columns("us_sec_13f_filing")
    }
    if "table_value_total_usd_text" in filing_columns:
        op.drop_column("us_sec_13f_filing", "table_value_total_usd_text")
    if "table_value_unit" in filing_columns:
        op.drop_column("us_sec_13f_filing", "table_value_unit")
    _rename(
        "us_sec_13f_filing",
        "table_value_total_raw_text",
        "table_value_total_thousands_text",
    )
    _rename(
        "us_sec_13f_warehouse_partition",
        "total_reported_value_usd_text",
        "total_reported_value_thousands_text",
    )
