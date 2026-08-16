"""Add SEC 13F analytical warehouse metadata and projections.

Revision ID: 20260812_0059
Revises: 20260811_0058
Create Date: 2026-08-12 09:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260812_0059"
down_revision: str | Sequence[str] | None = "20260811_0058"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def _indexes(table: str, columns: tuple[str, ...]) -> None:
    existing = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}
    for column in columns:
        name = f"ix_{table}_{column}"
        if name not in existing:
            op.create_index(name, table, [column], unique=False)


def upgrade() -> None:
    if not _has_table("us_sec_13f_warehouse_partition"):
        op.create_table(
            "us_sec_13f_warehouse_partition",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("dataset_release_id", sa.Integer(), nullable=False),
            sa.Column("period_key", sa.String(40), nullable=False),
            sa.Column("source_sha256", sa.String(64), nullable=False),
            sa.Column("holdings_path", sa.Text(), nullable=False),
            sa.Column("holdings_sha256", sa.String(64), nullable=False),
            sa.Column("row_count", sa.BigInteger(), nullable=False),
            sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
            sa.Column("distinct_cusip_count", sa.Integer(), nullable=False),
            sa.Column("total_reported_value_thousands_text", sa.Text(), nullable=True),
            sa.Column("status", sa.String(30), nullable=False),
            sa.Column("is_current", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["dataset_release_id"], ["us_sec_dataset_release.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("dataset_release_id", name="uq_us_sec_13f_warehouse_partition_release"),
        )
        _indexes("us_sec_13f_warehouse_partition", ("id", "dataset_release_id", "period_key", "source_sha256", "holdings_sha256", "status", "is_current"))

    if not _has_table("us_sec_13f_manager"):
        op.create_table(
            "us_sec_13f_manager",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("cik", sa.String(20), nullable=False),
            sa.Column("name", sa.String(240), nullable=False),
            sa.Column("form13f_file_number", sa.String(30), nullable=True),
            sa.Column("address_json", sa.Text(), nullable=True),
            sa.Column("first_seen_release_id", sa.Integer(), nullable=True),
            sa.Column("last_seen_release_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["first_seen_release_id"], ["us_sec_dataset_release.id"]),
            sa.ForeignKeyConstraint(["last_seen_release_id"], ["us_sec_dataset_release.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("cik", name="uq_us_sec_13f_manager_cik"),
        )
        _indexes("us_sec_13f_manager", ("id", "cik", "name", "form13f_file_number", "first_seen_release_id", "last_seen_release_id"))

    if not _has_table("us_sec_13f_filing"):
        op.create_table(
            "us_sec_13f_filing",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("dataset_release_id", sa.Integer(), nullable=False),
            sa.Column("manager_id", sa.Integer(), nullable=False),
            sa.Column("accession_number", sa.String(40), nullable=False),
            sa.Column("submission_type", sa.String(12), nullable=False),
            sa.Column("filing_date", sa.Date(), nullable=False),
            sa.Column("period_of_report", sa.Date(), nullable=False),
            sa.Column("report_calendar_or_quarter", sa.Date(), nullable=True),
            sa.Column("is_amendment", sa.Boolean(), nullable=False),
            sa.Column("amendment_number", sa.Integer(), nullable=True),
            sa.Column("amendment_type", sa.String(40), nullable=True),
            sa.Column("report_type", sa.String(80), nullable=True),
            sa.Column("form13f_file_number", sa.String(30), nullable=True),
            sa.Column("other_included_managers_count", sa.Integer(), nullable=True),
            sa.Column("table_entry_total", sa.Integer(), nullable=True),
            sa.Column("table_value_total_thousands_text", sa.Text(), nullable=True),
            sa.Column("is_confidential_omitted", sa.Boolean(), nullable=True),
            sa.Column("is_notice_only", sa.Boolean(), nullable=False),
            sa.Column("effective_status", sa.String(30), nullable=False),
            sa.Column("supersedes_accession_number", sa.String(40), nullable=True),
            sa.Column("source_url", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["dataset_release_id"], ["us_sec_dataset_release.id"]),
            sa.ForeignKeyConstraint(["manager_id"], ["us_sec_13f_manager.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("dataset_release_id", "accession_number", name="uq_us_sec_13f_filing_release_accession"),
        )
        _indexes("us_sec_13f_filing", ("id", "dataset_release_id", "manager_id", "accession_number", "submission_type", "filing_date", "period_of_report", "report_calendar_or_quarter", "is_amendment", "report_type", "form13f_file_number", "is_confidential_omitted", "is_notice_only", "effective_status", "supersedes_accession_number"))

    if not _has_table("us_sec_13f_other_manager"):
        op.create_table(
            "us_sec_13f_other_manager",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("filing_id", sa.Integer(), nullable=False),
            sa.Column("sequence_number", sa.Integer(), nullable=False),
            sa.Column("cik", sa.String(20), nullable=True),
            sa.Column("form13f_file_number", sa.String(30), nullable=True),
            sa.Column("name", sa.String(240), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["filing_id"], ["us_sec_13f_filing.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("filing_id", "sequence_number", name="uq_us_sec_13f_other_manager_sequence"),
        )
        _indexes("us_sec_13f_other_manager", ("id", "filing_id", "cik", "name"))

    if not _has_table("us_security_identifier_map"):
        op.create_table(
            "us_security_identifier_map",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("identifier_type", sa.String(20), nullable=False),
            sa.Column("identifier_value", sa.String(80), nullable=False),
            sa.Column("mapping_version", sa.String(80), nullable=False),
            sa.Column("figi", sa.String(20), nullable=True),
            sa.Column("composite_figi", sa.String(20), nullable=True),
            sa.Column("share_class_figi", sa.String(20), nullable=True),
            sa.Column("symbol", sa.String(32), nullable=True),
            sa.Column("issuer_cik", sa.String(20), nullable=True),
            sa.Column("exchange_code", sa.String(20), nullable=True),
            sa.Column("market_sector", sa.String(40), nullable=True),
            sa.Column("security_type", sa.String(80), nullable=True),
            sa.Column("security_type2", sa.String(80), nullable=True),
            sa.Column("mapping_source", sa.String(40), nullable=False),
            sa.Column("status", sa.String(30), nullable=False),
            sa.Column("confidence", sa.String(20), nullable=False),
            sa.Column("manual_override", sa.Boolean(), nullable=False),
            sa.Column("evidence_json", sa.Text(), nullable=True),
            sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("identifier_type", "identifier_value", "mapping_version", name="uq_us_security_identifier_map_version"),
        )
        _indexes("us_security_identifier_map", ("id", "identifier_type", "identifier_value", "mapping_version", "figi", "composite_figi", "share_class_figi", "symbol", "issuer_cik", "mapping_source", "status", "confidence", "manual_override", "checked_at"))

    if not _has_table("us_sec_13f_symbol_quarter"):
        op.create_table(
            "us_sec_13f_symbol_quarter",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("symbol", sa.String(32), nullable=False),
            sa.Column("issuer_cik", sa.String(20), nullable=True),
            sa.Column("report_quarter", sa.String(12), nullable=False),
            sa.Column("report_period_end", sa.Date(), nullable=False),
            sa.Column("mapping_version", sa.String(80), nullable=False),
            sa.Column("source_release_id", sa.Integer(), nullable=False),
            sa.Column("reporting_manager_count", sa.Integer(), nullable=False),
            sa.Column("reported_row_count", sa.Integer(), nullable=False),
            sa.Column("reported_long_shares_text", sa.Text(), nullable=True),
            sa.Column("reported_long_value_thousands_text", sa.Text(), nullable=True),
            sa.Column("reported_put_value_thousands_text", sa.Text(), nullable=True),
            sa.Column("reported_call_value_thousands_text", sa.Text(), nullable=True),
            sa.Column("new_manager_count", sa.Integer(), nullable=True),
            sa.Column("increased_manager_count", sa.Integer(), nullable=True),
            sa.Column("reduced_manager_count", sa.Integer(), nullable=True),
            sa.Column("exited_manager_count", sa.Integer(), nullable=True),
            sa.Column("mapping_row_coverage", sa.Float(), nullable=False),
            sa.Column("mapping_value_coverage", sa.Float(), nullable=False),
            sa.Column("unresolved_row_count", sa.Integer(), nullable=False),
            sa.Column("unresolved_value_thousands_text", sa.Text(), nullable=True),
            sa.Column("status", sa.String(30), nullable=False),
            sa.Column("limitations_json", sa.Text(), nullable=True),
            sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["source_release_id"], ["us_sec_dataset_release.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("symbol", "report_quarter", "mapping_version", "source_release_id", name="uq_us_sec_13f_symbol_quarter_projection"),
        )
        _indexes("us_sec_13f_symbol_quarter", ("id", "symbol", "issuer_cik", "report_quarter", "report_period_end", "mapping_version", "source_release_id", "status", "computed_at"))


def downgrade() -> None:
    for table in (
        "us_sec_13f_symbol_quarter",
        "us_security_identifier_map",
        "us_sec_13f_other_manager",
        "us_sec_13f_filing",
        "us_sec_13f_manager",
        "us_sec_13f_warehouse_partition",
    ):
        if _has_table(table):
            op.drop_table(table)
