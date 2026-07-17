"""add resource currency instruments

Revision ID: 20260715_0034
Revises: 20260709_0033
Create Date: 2026-07-15 00:00:00
"""

from collections.abc import Sequence
from datetime import datetime, timezone
import json

import sqlalchemy as sa
from alembic import op


revision: str = "20260715_0034"
down_revision: str | Sequence[str] | None = "20260709_0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


CURRENCY_INSTRUMENTS = (
    ("twd_to_foreign", "TWD", "USD", "台幣／美元", "TWDUSD=X"),
    ("twd_to_foreign", "TWD", "JPY", "台幣／日圓", "TWDJPY=X"),
    ("twd_to_foreign", "TWD", "KRW", "台幣／韓元", "TWDKRW=X"),
    ("foreign_to_twd", "USD", "TWD", "美元／台幣", "USDTWD=X"),
    ("foreign_to_twd", "JPY", "TWD", "日圓／台幣", "JPYTWD=X"),
    ("foreign_to_twd", "KRW", "TWD", "韓元／台幣", "KRWTWD=X"),
    ("foreign_to_foreign", "USD", "JPY", "美元／日圓", "USDJPY=X"),
    ("foreign_to_foreign", "USD", "KRW", "美元／韓元", "USDKRW=X"),
    ("foreign_to_foreign", "EUR", "USD", "歐元／美元", "EURUSD=X"),
)


def _instrument_table() -> sa.TableClause:
    return sa.table(
        "resource_market_instrument",
        sa.column("key", sa.String),
        sa.column("root_folder", sa.String),
        sa.column("group", sa.String),
        sa.column("asset_class", sa.String),
        sa.column("name", sa.String),
        sa.column("display_name", sa.String),
        sa.column("symbol", sa.String),
        sa.column("provider", sa.String),
        sa.column("exchange", sa.String),
        sa.column("provider_symbol", sa.String),
        sa.column("base_asset", sa.String),
        sa.column("quote_asset", sa.String),
        sa.column("instrument_type", sa.String),
        sa.column("contract_type", sa.String),
        sa.column("tradable", sa.Boolean),
        sa.column("trade_candidate", sa.Boolean),
        sa.column("resources_json", sa.Text),
        sa.column("provider_status", sa.String),
        sa.column("notes", sa.Text),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("resource_market_instrument"):
        return

    table = _instrument_table()
    existing_keys = set(bind.execute(sa.select(table.c.key)).scalars())
    now = datetime.now(timezone.utc)
    rows = []
    for group, base_asset, quote_asset, display_name, provider_symbol in CURRENCY_INSTRUMENTS:
        symbol = f"{base_asset}-{quote_asset}"
        key = f"currency:{group}:{symbol}"
        if key in existing_keys:
            continue
        rows.append(
            {
                "key": key,
                "root_folder": "currency",
                "group": group,
                "asset_class": "foreign_exchange",
                "name": f"{base_asset}/{quote_asset} Foreign Exchange",
                "display_name": display_name,
                "symbol": symbol,
                "provider": "yahoo_chart",
                "exchange": "FX",
                "provider_symbol": provider_symbol,
                "base_asset": base_asset,
                "quote_asset": quote_asset,
                "instrument_type": "spot",
                "contract_type": "spot",
                "tradable": False,
                "trade_candidate": False,
                "resources_json": json.dumps(["quote", "ohlcv"], ensure_ascii=False),
                "provider_status": "best_effort_delayed",
                "notes": (
                    f"{base_asset}/{quote_asset} foreign-exchange watch-only Yahoo chart "
                    "context; delayed/best-effort."
                ),
                "created_at": now,
                "updated_at": now,
            }
        )

    if rows:
        op.bulk_insert(table, rows)


def downgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("resource_market_instrument"):
        return

    table = _instrument_table()
    keys = [
        f"currency:{group}:{base_asset}-{quote_asset}"
        for group, base_asset, quote_asset, _, _ in CURRENCY_INSTRUMENTS
    ]
    bind.execute(sa.delete(table).where(table.c.key.in_(keys)))
