"""Add SEC ownership ingestion foundation and Form 4 tables.

Revision ID: 20260811_0058
Revises: 20260809_0057
Create Date: 2026-08-11 22:30:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260811_0058"
down_revision: str | Sequence[str] | None = "20260809_0057"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def _create_indexes(table: str, columns: tuple[str, ...]) -> None:
    existing = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}
    for column in columns:
        name = f"ix_{table}_{column}"
        if name not in existing:
            op.create_index(name, table, [column], unique=False)


def upgrade() -> None:
    if not _has_table("us_sec_dataset_release"):
        op.create_table(
            "us_sec_dataset_release",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("dataset_code", sa.String(60), nullable=False),
            sa.Column("period_key", sa.String(40), nullable=False),
            sa.Column("source_url", sa.Text(), nullable=False),
            sa.Column("source_sha256", sa.String(64), nullable=False),
            sa.Column("source_size_bytes", sa.BigInteger(), nullable=True),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("downloaded_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("schema_version", sa.String(80), nullable=True),
            sa.Column("parser_version", sa.String(80), nullable=True),
            sa.Column("status", sa.String(30), nullable=False),
            sa.Column("source_row_counts_json", sa.Text(), nullable=True),
            sa.Column("persisted_row_counts_json", sa.Text(), nullable=True),
            sa.Column("quarantined_row_counts_json", sa.Text(), nullable=True),
            sa.Column("error_summary", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "dataset_code",
                "period_key",
                "source_sha256",
                name="uq_us_sec_dataset_release_identity",
            ),
        )
        _create_indexes(
            "us_sec_dataset_release",
            ("id", "dataset_code", "period_key", "source_sha256", "published_at", "checked_at", "status"),
        )

    if not _has_table("us_sec_ingestion_checkpoint"):
        op.create_table(
            "us_sec_ingestion_checkpoint",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("dataset_release_id", sa.Integer(), nullable=False),
            sa.Column("stage_code", sa.String(60), nullable=False),
            sa.Column("partition_key", sa.String(120), nullable=False),
            sa.Column("cursor_value", sa.Text(), nullable=True),
            sa.Column("processed_count", sa.Integer(), nullable=False),
            sa.Column("error_count", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(30), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["dataset_release_id"], ["us_sec_dataset_release.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "dataset_release_id",
                "stage_code",
                "partition_key",
                name="uq_us_sec_ingestion_checkpoint_stage",
            ),
        )
        _create_indexes(
            "us_sec_ingestion_checkpoint",
            ("id", "dataset_release_id", "stage_code", "partition_key", "status"),
        )

    if not _has_table("us_sec_ownership_sync_state"):
        op.create_table(
            "us_sec_ownership_sync_state",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("symbol", sa.String(32), nullable=False),
            sa.Column("issuer_cik", sa.String(20), nullable=False),
            sa.Column("status", sa.String(30), nullable=False),
            sa.Column("latest_accession_number", sa.String(40), nullable=True),
            sa.Column("latest_filing_date", sa.Date(), nullable=True),
            sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("fetched_count", sa.Integer(), nullable=False),
            sa.Column("error_count", sa.Integer(), nullable=False),
            sa.Column("warning_json", sa.Text(), nullable=True),
            sa.Column("source_url", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("symbol", name="uq_us_sec_ownership_sync_state_symbol"),
        )
        _create_indexes(
            "us_sec_ownership_sync_state",
            ("id", "symbol", "issuer_cik", "status", "latest_accession_number", "latest_filing_date", "last_checked_at"),
        )

    if not _has_table("us_sec_ownership_filing"):
        op.create_table(
            "us_sec_ownership_filing",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("dataset_release_id", sa.Integer(), nullable=True),
            sa.Column("accession_number", sa.String(40), nullable=False),
            sa.Column("form_type", sa.String(12), nullable=False),
            sa.Column("schema_version", sa.String(40), nullable=True),
            sa.Column("issuer_cik", sa.String(20), nullable=False),
            sa.Column("issuer_name", sa.String(240), nullable=False),
            sa.Column("issuer_trading_symbol", sa.String(32), nullable=True),
            sa.Column("period_of_report", sa.Date(), nullable=True),
            sa.Column("original_submission_date", sa.Date(), nullable=True),
            sa.Column("filing_date", sa.Date(), nullable=True),
            sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("is_amendment", sa.Boolean(), nullable=False),
            sa.Column("supersedes_accession_number", sa.String(40), nullable=True),
            sa.Column("aff10b5_one", sa.Boolean(), nullable=True),
            sa.Column("remarks", sa.Text(), nullable=True),
            sa.Column("source_url", sa.Text(), nullable=False),
            sa.Column("source_sha256", sa.String(64), nullable=False),
            sa.Column("parser_version", sa.String(80), nullable=False),
            sa.Column("issue_codes_json", sa.Text(), nullable=True),
            sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["dataset_release_id"], ["us_sec_dataset_release.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("accession_number", name="uq_us_sec_ownership_filing_accession"),
        )
        _create_indexes(
            "us_sec_ownership_filing",
            (
                "id", "dataset_release_id", "accession_number", "form_type", "issuer_cik",
                "issuer_trading_symbol", "period_of_report", "filing_date", "accepted_at",
                "is_amendment", "supersedes_accession_number", "aff10b5_one", "source_sha256", "fetched_at",
            ),
        )

    if not _has_table("us_sec_reporting_owner"):
        op.create_table(
            "us_sec_reporting_owner",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("cik", sa.String(20), nullable=False),
            sa.Column("name", sa.String(240), nullable=False),
            sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("cik", name="uq_us_sec_reporting_owner_cik"),
        )
        _create_indexes("us_sec_reporting_owner", ("id", "cik", "name", "last_seen_at"))

    if not _has_table("us_sec_filing_reporting_owner"):
        op.create_table(
            "us_sec_filing_reporting_owner",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("filing_id", sa.Integer(), nullable=False),
            sa.Column("reporting_owner_id", sa.Integer(), nullable=False),
            sa.Column("is_director", sa.Boolean(), nullable=False),
            sa.Column("is_officer", sa.Boolean(), nullable=False),
            sa.Column("is_ten_percent_owner", sa.Boolean(), nullable=False),
            sa.Column("is_other", sa.Boolean(), nullable=False),
            sa.Column("officer_title", sa.String(240), nullable=True),
            sa.Column("other_text", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["filing_id"], ["us_sec_ownership_filing.id"]),
            sa.ForeignKeyConstraint(["reporting_owner_id"], ["us_sec_reporting_owner.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("filing_id", "reporting_owner_id", name="uq_us_sec_filing_reporting_owner_link"),
        )
        _create_indexes(
            "us_sec_filing_reporting_owner",
            ("id", "filing_id", "reporting_owner_id", "is_director", "is_officer", "is_ten_percent_owner", "is_other"),
        )

    if not _has_table("us_sec_ownership_transaction"):
        op.create_table(
            "us_sec_ownership_transaction",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("filing_id", sa.Integer(), nullable=False),
            sa.Column("row_sequence", sa.Integer(), nullable=False),
            sa.Column("table_type", sa.String(30), nullable=False),
            sa.Column("security_title", sa.String(320), nullable=True),
            sa.Column("transaction_date", sa.Date(), nullable=True),
            sa.Column("deemed_execution_date", sa.Date(), nullable=True),
            sa.Column("transaction_form_type", sa.String(12), nullable=True),
            sa.Column("transaction_code", sa.String(8), nullable=True),
            sa.Column("equity_swap_involved", sa.Boolean(), nullable=True),
            sa.Column("acquired_disposed_code", sa.String(4), nullable=True),
            sa.Column("shares_text", sa.Text(), nullable=True),
            sa.Column("price_per_share_text", sa.Text(), nullable=True),
            sa.Column("post_transaction_shares_text", sa.Text(), nullable=True),
            sa.Column("direct_indirect_code", sa.String(4), nullable=True),
            sa.Column("nature_of_ownership", sa.Text(), nullable=True),
            sa.Column("conversion_exercise_price_text", sa.Text(), nullable=True),
            sa.Column("exercise_date", sa.Date(), nullable=True),
            sa.Column("expiration_date", sa.Date(), nullable=True),
            sa.Column("underlying_security_title", sa.String(320), nullable=True),
            sa.Column("underlying_shares_text", sa.Text(), nullable=True),
            sa.Column("footnote_ids_json", sa.Text(), nullable=True),
            sa.Column("issue_codes_json", sa.Text(), nullable=True),
            sa.Column("raw_row_hash", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["filing_id"], ["us_sec_ownership_filing.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("filing_id", "row_sequence", name="uq_us_sec_ownership_transaction_row"),
        )
        _create_indexes(
            "us_sec_ownership_transaction",
            ("id", "filing_id", "table_type", "security_title", "transaction_date", "transaction_code", "acquired_disposed_code", "direct_indirect_code", "raw_row_hash"),
        )

    if not _has_table("us_sec_ownership_position"):
        op.create_table(
            "us_sec_ownership_position",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("filing_id", sa.Integer(), nullable=False),
            sa.Column("row_sequence", sa.Integer(), nullable=False),
            sa.Column("table_type", sa.String(30), nullable=False),
            sa.Column("security_title", sa.String(320), nullable=True),
            sa.Column("post_transaction_shares_text", sa.Text(), nullable=True),
            sa.Column("direct_indirect_code", sa.String(4), nullable=True),
            sa.Column("nature_of_ownership", sa.Text(), nullable=True),
            sa.Column("conversion_exercise_price_text", sa.Text(), nullable=True),
            sa.Column("exercise_date", sa.Date(), nullable=True),
            sa.Column("expiration_date", sa.Date(), nullable=True),
            sa.Column("underlying_security_title", sa.String(320), nullable=True),
            sa.Column("underlying_shares_text", sa.Text(), nullable=True),
            sa.Column("footnote_ids_json", sa.Text(), nullable=True),
            sa.Column("issue_codes_json", sa.Text(), nullable=True),
            sa.Column("raw_row_hash", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["filing_id"], ["us_sec_ownership_filing.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("filing_id", "row_sequence", name="uq_us_sec_ownership_position_row"),
        )
        _create_indexes(
            "us_sec_ownership_position",
            ("id", "filing_id", "table_type", "security_title", "direct_indirect_code", "raw_row_hash"),
        )

    if not _has_table("us_sec_ownership_footnote"):
        op.create_table(
            "us_sec_ownership_footnote",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("filing_id", sa.Integer(), nullable=False),
            sa.Column("footnote_id", sa.String(40), nullable=False),
            sa.Column("footnote_text", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["filing_id"], ["us_sec_ownership_filing.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("filing_id", "footnote_id", name="uq_us_sec_ownership_footnote_identity"),
        )
        _create_indexes("us_sec_ownership_footnote", ("id", "filing_id", "footnote_id"))


def downgrade() -> None:
    for table in (
        "us_sec_ownership_footnote",
        "us_sec_ownership_position",
        "us_sec_ownership_transaction",
        "us_sec_filing_reporting_owner",
        "us_sec_reporting_owner",
        "us_sec_ownership_filing",
        "us_sec_ownership_sync_state",
        "us_sec_ingestion_checkpoint",
        "us_sec_dataset_release",
    ):
        if _has_table(table):
            op.drop_table(table)
