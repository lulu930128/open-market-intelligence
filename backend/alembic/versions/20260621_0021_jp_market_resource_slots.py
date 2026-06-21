"""Add Japan market resource slot tables.

Revision ID: 20260621_0021
Revises: 20260621_0020
Create Date: 2026-06-21 00:21:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260621_0021"
down_revision: str | Sequence[str] | None = "20260621_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _has_index(table_name: str, index_name: str) -> bool:
    return any(
        index["name"] == index_name
        for index in sa.inspect(op.get_bind()).get_indexes(table_name)
    )


def _drop_indexes(table_name: str, index_names: tuple[str, ...]) -> None:
    for index_name in index_names:
        if _has_index(table_name, index_name):
            op.drop_index(op.f(index_name), table_name=table_name)


def upgrade() -> None:
    if not _has_table("jp_margin_interest"):
        op.create_table(
            "jp_margin_interest",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("provider", sa.String(length=40), nullable=False),
            sa.Column("symbol", sa.String(length=32), nullable=False),
            sa.Column("report_date", sa.Date(), nullable=False),
            sa.Column("short_volume", sa.BigInteger(), nullable=True),
            sa.Column("long_volume", sa.BigInteger(), nullable=True),
            sa.Column("short_negotiable_volume", sa.BigInteger(), nullable=True),
            sa.Column("long_negotiable_volume", sa.BigInteger(), nullable=True),
            sa.Column("short_standardized_volume", sa.BigInteger(), nullable=True),
            sa.Column("long_standardized_volume", sa.BigInteger(), nullable=True),
            sa.Column("issue_type", sa.String(length=20), nullable=True),
            sa.Column("source_url", sa.Text(), nullable=True),
            sa.Column("raw_payload_hash", sa.String(length=128), nullable=True),
            sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "provider",
                "symbol",
                "report_date",
                name="uq_jp_margin_interest_provider_symbol_date",
            ),
        )
        op.create_index(op.f("ix_jp_margin_interest_id"), "jp_margin_interest", ["id"], unique=False)
        op.create_index(op.f("ix_jp_margin_interest_issue_type"), "jp_margin_interest", ["issue_type"], unique=False)
        op.create_index(op.f("ix_jp_margin_interest_provider"), "jp_margin_interest", ["provider"], unique=False)
        op.create_index(op.f("ix_jp_margin_interest_raw_payload_hash"), "jp_margin_interest", ["raw_payload_hash"], unique=False)
        op.create_index(op.f("ix_jp_margin_interest_report_date"), "jp_margin_interest", ["report_date"], unique=False)
        op.create_index(op.f("ix_jp_margin_interest_symbol"), "jp_margin_interest", ["symbol"], unique=False)

    if not _has_table("jp_investor_type"):
        op.create_table(
            "jp_investor_type",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("provider", sa.String(length=40), nullable=False),
            sa.Column("section", sa.String(length=80), nullable=False),
            sa.Column("published_date", sa.Date(), nullable=True),
            sa.Column("start_date", sa.Date(), nullable=True),
            sa.Column("end_date", sa.Date(), nullable=True),
            sa.Column("proprietary_sell", sa.BigInteger(), nullable=True),
            sa.Column("proprietary_buy", sa.BigInteger(), nullable=True),
            sa.Column("proprietary_total", sa.BigInteger(), nullable=True),
            sa.Column("proprietary_balance", sa.BigInteger(), nullable=True),
            sa.Column("broker_sell", sa.BigInteger(), nullable=True),
            sa.Column("broker_buy", sa.BigInteger(), nullable=True),
            sa.Column("broker_total", sa.BigInteger(), nullable=True),
            sa.Column("broker_balance", sa.BigInteger(), nullable=True),
            sa.Column("total_sell", sa.BigInteger(), nullable=True),
            sa.Column("total_buy", sa.BigInteger(), nullable=True),
            sa.Column("total_traded", sa.BigInteger(), nullable=True),
            sa.Column("total_balance", sa.BigInteger(), nullable=True),
            sa.Column("individual_sell", sa.BigInteger(), nullable=True),
            sa.Column("individual_buy", sa.BigInteger(), nullable=True),
            sa.Column("individual_total", sa.BigInteger(), nullable=True),
            sa.Column("individual_balance", sa.BigInteger(), nullable=True),
            sa.Column("foreign_sell", sa.BigInteger(), nullable=True),
            sa.Column("foreign_buy", sa.BigInteger(), nullable=True),
            sa.Column("foreign_total", sa.BigInteger(), nullable=True),
            sa.Column("foreign_balance", sa.BigInteger(), nullable=True),
            sa.Column("investment_trust_sell", sa.BigInteger(), nullable=True),
            sa.Column("investment_trust_buy", sa.BigInteger(), nullable=True),
            sa.Column("investment_trust_total", sa.BigInteger(), nullable=True),
            sa.Column("investment_trust_balance", sa.BigInteger(), nullable=True),
            sa.Column("trust_bank_sell", sa.BigInteger(), nullable=True),
            sa.Column("trust_bank_buy", sa.BigInteger(), nullable=True),
            sa.Column("trust_bank_total", sa.BigInteger(), nullable=True),
            sa.Column("trust_bank_balance", sa.BigInteger(), nullable=True),
            sa.Column("source_url", sa.Text(), nullable=True),
            sa.Column("raw_payload_hash", sa.String(length=128), nullable=True),
            sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "provider",
                "section",
                "published_date",
                "start_date",
                "end_date",
                name="uq_jp_investor_type_provider_section_period",
            ),
        )
        op.create_index(op.f("ix_jp_investor_type_end_date"), "jp_investor_type", ["end_date"], unique=False)
        op.create_index(op.f("ix_jp_investor_type_id"), "jp_investor_type", ["id"], unique=False)
        op.create_index(op.f("ix_jp_investor_type_provider"), "jp_investor_type", ["provider"], unique=False)
        op.create_index(op.f("ix_jp_investor_type_published_date"), "jp_investor_type", ["published_date"], unique=False)
        op.create_index(op.f("ix_jp_investor_type_raw_payload_hash"), "jp_investor_type", ["raw_payload_hash"], unique=False)
        op.create_index(op.f("ix_jp_investor_type_section"), "jp_investor_type", ["section"], unique=False)
        op.create_index(op.f("ix_jp_investor_type_start_date"), "jp_investor_type", ["start_date"], unique=False)


def downgrade() -> None:
    if _has_table("jp_investor_type"):
        _drop_indexes(
            "jp_investor_type",
            (
                "ix_jp_investor_type_start_date",
                "ix_jp_investor_type_section",
                "ix_jp_investor_type_raw_payload_hash",
                "ix_jp_investor_type_published_date",
                "ix_jp_investor_type_provider",
                "ix_jp_investor_type_id",
                "ix_jp_investor_type_end_date",
            ),
        )
        op.drop_table("jp_investor_type")

    if _has_table("jp_margin_interest"):
        _drop_indexes(
            "jp_margin_interest",
            (
                "ix_jp_margin_interest_symbol",
                "ix_jp_margin_interest_report_date",
                "ix_jp_margin_interest_raw_payload_hash",
                "ix_jp_margin_interest_provider",
                "ix_jp_margin_interest_issue_type",
                "ix_jp_margin_interest_id",
            ),
        )
        op.drop_table("jp_margin_interest")
