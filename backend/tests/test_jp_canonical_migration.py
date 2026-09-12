"""Isolated migration proof; never opens the configured application database."""

from alembic import command
from pathlib import Path
from uuid import uuid4
from sqlalchemy import create_engine, inspect, text

from app.db.migrations import create_alembic_config


def test_jp_evidence_migration_preserves_legacy_and_is_reversible():
    # Avoid pytest's Windows mode-0700 temporary directory ACL behavior.
    # These small isolated fixtures remain under the ignored validation root.
    tmp_path = Path(__file__).resolve().parents[2] / ".tmp" / "jp-migration-tests" / uuid4().hex
    tmp_path.mkdir(parents=True)
    url = f"sqlite:///{(tmp_path / 'jp-migration.db').as_posix()}"
    config = create_alembic_config(url)
    command.upgrade(config, "20260912_0084")
    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO jp_daily_price "
                "(provider,symbol,trade_date,currency,close_price,fetched_at,created_at,updated_at) "
                "VALUES ('yahoo_chart','7203.T','2026-09-10','JPY',105,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            ))
    finally:
        engine.dispose()
    command.upgrade(config, "20260912_0085")
    command.upgrade(config, "20260912_0085")
    engine = create_engine(url)
    try:
        assert inspect(engine).has_table("jp_bar_evidence")
        assert any(item["referred_table"] == "raw_fetch_result" for item in inspect(engine).get_foreign_keys("jp_bar_evidence"))
        with engine.connect() as connection:
            assert connection.execute(text("SELECT close_price FROM jp_daily_price WHERE symbol='7203.T'")).scalar_one() == 105
            assert connection.execute(text("SELECT COUNT(*) FROM jp_bar_evidence")).scalar_one() == 0
    finally:
        engine.dispose()
    command.downgrade(config, "20260912_0084")
    engine = create_engine(url)
    try:
        assert not inspect(engine).has_table("jp_bar_evidence")
        with engine.connect() as connection:
            assert connection.execute(text("SELECT COUNT(*) FROM jp_daily_price WHERE symbol='7203.T'")).scalar_one() == 1
    finally:
        engine.dispose()
    # Baseline migration may create current metadata; replay after downgrade
    # proves this revision's own create-table path as well.
    command.upgrade(config, "20260912_0085")
    engine = create_engine(url)
    try:
        assert inspect(engine).has_table("jp_bar_evidence")
        assert "ix_jp_bar_evidence_read" in {item["name"] for item in inspect(engine).get_indexes("jp_bar_evidence")}
    finally:
        engine.dispose()
