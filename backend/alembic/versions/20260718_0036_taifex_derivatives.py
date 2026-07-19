"""add TAIFEX derivatives cache tables

Revision ID: 20260718_0036
Revises: 20260718_0035
Create Date: 2026-07-18 00:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260718_0036"
down_revision: str | Sequence[str] | None = "20260718_0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("taiwan_option_chain_daily"):
        op.create_table(
            "taiwan_option_chain_daily",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("provider", sa.String(length=60), nullable=False),
            sa.Column("trade_date", sa.Date(), nullable=False),
            sa.Column("product_code", sa.String(length=20), nullable=False),
            sa.Column("contract_month", sa.String(length=20), nullable=False),
            sa.Column("expiry_date", sa.Date(), nullable=True),
            sa.Column("strike_price", sa.Float(), nullable=False),
            sa.Column("option_type", sa.String(length=10), nullable=False),
            sa.Column("session", sa.String(length=20), nullable=False),
            sa.Column("open_price", sa.Float(), nullable=True),
            sa.Column("high_price", sa.Float(), nullable=True),
            sa.Column("low_price", sa.Float(), nullable=True),
            sa.Column("close_price", sa.Float(), nullable=True),
            sa.Column("settlement_price", sa.Float(), nullable=True),
            sa.Column("volume", sa.BigInteger(), nullable=True),
            sa.Column("open_interest", sa.BigInteger(), nullable=True),
            sa.Column("bid_price", sa.Float(), nullable=True),
            sa.Column("ask_price", sa.Float(), nullable=True),
            sa.Column("historical_high_price", sa.Float(), nullable=True),
            sa.Column("historical_low_price", sa.Float(), nullable=True),
            sa.Column("official_delta", sa.Float(), nullable=True),
            sa.Column("implied_volatility_pct", sa.Float(), nullable=True),
            sa.Column("gamma", sa.Float(), nullable=True),
            sa.Column("vega_per_vol_pct", sa.Float(), nullable=True),
            sa.Column("theta_per_day", sa.Float(), nullable=True),
            sa.Column("spot_reference", sa.Float(), nullable=True),
            sa.Column("pricing_source", sa.String(length=40), nullable=True),
            sa.Column("calculation_model", sa.String(length=80), nullable=True),
            sa.Column("calculation_status", sa.String(length=50), nullable=False),
            sa.Column("risk_free_rate", sa.Float(), nullable=True),
            sa.Column("dividend_yield", sa.Float(), nullable=True),
            sa.Column("source", sa.String(length=120), nullable=False),
            sa.Column("source_url", sa.Text(), nullable=True),
            sa.Column("delta_source_url", sa.Text(), nullable=True),
            sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint(
                "provider",
                "trade_date",
                "product_code",
                "contract_month",
                "strike_price",
                "option_type",
                "session",
                name="uq_tw_option_chain_contract_strike_session",
            ),
        )
        op.create_index("ix_taiwan_option_chain_daily_id", "taiwan_option_chain_daily", ["id"])
        op.create_index("ix_taiwan_option_chain_daily_provider", "taiwan_option_chain_daily", ["provider"])
        op.create_index("ix_taiwan_option_chain_daily_trade_date", "taiwan_option_chain_daily", ["trade_date"])
        op.create_index("ix_taiwan_option_chain_daily_product_code", "taiwan_option_chain_daily", ["product_code"])
        op.create_index("ix_taiwan_option_chain_daily_contract_month", "taiwan_option_chain_daily", ["contract_month"])
        op.create_index("ix_taiwan_option_chain_daily_expiry_date", "taiwan_option_chain_daily", ["expiry_date"])
        op.create_index("ix_taiwan_option_chain_daily_strike_price", "taiwan_option_chain_daily", ["strike_price"])
        op.create_index("ix_taiwan_option_chain_daily_option_type", "taiwan_option_chain_daily", ["option_type"])
        op.create_index("ix_taiwan_option_chain_daily_session", "taiwan_option_chain_daily", ["session"])
        op.create_index("ix_taiwan_option_chain_daily_calculation_status", "taiwan_option_chain_daily", ["calculation_status"])
        op.create_index("ix_taiwan_option_chain_daily_source", "taiwan_option_chain_daily", ["source"])
        op.create_index("ix_taiwan_option_chain_daily_fetched_at", "taiwan_option_chain_daily", ["fetched_at"])
        op.create_index(
            "ix_tw_option_chain_date_contract_strike",
            "taiwan_option_chain_daily",
            ["trade_date", "product_code", "contract_month", "strike_price"],
        )

    if not inspector.has_table("taiwan_derivatives_large_trader_daily"):
        op.create_table(
            "taiwan_derivatives_large_trader_daily",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("provider", sa.String(length=60), nullable=False),
            sa.Column("trade_date", sa.Date(), nullable=False),
            sa.Column("instrument_type", sa.String(length=20), nullable=False),
            sa.Column("contract_code", sa.String(length=20), nullable=False),
            sa.Column("contract_name", sa.String(length=160), nullable=True),
            sa.Column("option_type", sa.String(length=20), nullable=False),
            sa.Column("settlement_bucket", sa.String(length=20), nullable=False),
            sa.Column("trader_type", sa.String(length=30), nullable=False),
            sa.Column("top5_buy", sa.BigInteger(), nullable=True),
            sa.Column("top5_sell", sa.BigInteger(), nullable=True),
            sa.Column("top10_buy", sa.BigInteger(), nullable=True),
            sa.Column("top10_sell", sa.BigInteger(), nullable=True),
            sa.Column("market_open_interest", sa.BigInteger(), nullable=True),
            sa.Column("source", sa.String(length=120), nullable=False),
            sa.Column("source_url", sa.Text(), nullable=True),
            sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint(
                "provider",
                "trade_date",
                "instrument_type",
                "contract_code",
                "option_type",
                "settlement_bucket",
                "trader_type",
                name="uq_tw_deriv_large_trader_contract_bucket",
            ),
        )
        for column in (
            "id",
            "provider",
            "trade_date",
            "instrument_type",
            "contract_code",
            "option_type",
            "settlement_bucket",
            "trader_type",
            "source",
            "fetched_at",
        ):
            op.create_index(
                f"ix_taiwan_derivatives_large_trader_daily_{column}",
                "taiwan_derivatives_large_trader_daily",
                [column],
            )

    if not inspector.has_table("taiwan_futures_term_structure_daily"):
        op.create_table(
            "taiwan_futures_term_structure_daily",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("provider", sa.String(length=60), nullable=False),
            sa.Column("trade_date", sa.Date(), nullable=False),
            sa.Column("symbol", sa.String(length=20), nullable=False),
            sa.Column("product_code", sa.String(length=20), nullable=False),
            sa.Column("contract_month", sa.String(length=20), nullable=False),
            sa.Column("expiry_date", sa.Date(), nullable=True),
            sa.Column("last_price", sa.Float(), nullable=True),
            sa.Column("settlement_price", sa.Float(), nullable=True),
            sa.Column("open_interest", sa.BigInteger(), nullable=True),
            sa.Column("spot_close", sa.Float(), nullable=True),
            sa.Column("basis_points", sa.Float(), nullable=True),
            sa.Column("basis_pct", sa.Float(), nullable=True),
            sa.Column("annualized_basis_pct", sa.Float(), nullable=True),
            sa.Column("calculation_status", sa.String(length=50), nullable=False),
            sa.Column("source", sa.String(length=120), nullable=False),
            sa.Column("source_url", sa.Text(), nullable=True),
            sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint(
                "provider",
                "trade_date",
                "symbol",
                "contract_month",
                name="uq_tw_futures_curve_symbol_month_date",
            ),
        )
        for column in (
            "id",
            "provider",
            "trade_date",
            "symbol",
            "product_code",
            "contract_month",
            "expiry_date",
            "calculation_status",
            "source",
            "fetched_at",
        ):
            op.create_index(
                f"ix_taiwan_futures_term_structure_daily_{column}",
                "taiwan_futures_term_structure_daily",
                [column],
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table_name in (
        "taiwan_futures_term_structure_daily",
        "taiwan_derivatives_large_trader_daily",
        "taiwan_option_chain_daily",
    ):
        if inspector.has_table(table_name):
            op.drop_table(table_name)
