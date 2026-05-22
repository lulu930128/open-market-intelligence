"""Baseline schema.

Revision ID: 20260523_0001
Revises:
Create Date: 2026-05-23 01:14:00

This baseline bootstraps an empty database from the current SQLAlchemy
metadata. For an existing local database, run:

    python -m alembic stamp 20260523_0001

after installing backend requirements.
"""

from collections.abc import Sequence

from alembic import op

from app.db.models import Base


revision: str = "20260523_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
