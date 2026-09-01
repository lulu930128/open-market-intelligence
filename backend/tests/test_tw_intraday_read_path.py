from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.db.models import Base
from app.market.intraday_repository import TaiwanIntradayBarRepository
from app.market.tw_intraday_platform import build_taiwan_intraday_requirement
from app.market_data.contracts import InstrumentKey, InstrumentType, Market
from app.market_data.policies import RealtimePolicy


TAIPEI = timezone(timedelta(hours=8))
TW_INTRADAY_READ_INDEX = "ix_market_intraday_bar_stock_market_interval_time"


def test_canonical_intraday_read_uses_existing_market_range_index() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    captured: dict[str, object] = {}

    def capture_intraday_select(
        _connection,
        _cursor,
        statement,
        parameters,
        _context,
        _executemany,
    ) -> None:
        if (
            not captured
            and statement.lstrip().startswith("SELECT")
            and "FROM market_intraday_bar" in statement
            and "JOIN market_intraday_bar_lineage" in statement
        ):
            captured["statement"] = statement
            captured["parameters"] = parameters

    event.listen(engine, "before_cursor_execute", capture_intraday_select)
    try:
        requested_at = datetime(2026, 9, 1, 13, 30, tzinfo=TAIPEI)
        requirement = build_taiwan_intraday_requirement(
            instrument=InstrumentKey(
                market=Market.TW,
                symbol="3711",
                instrument_type=InstrumentType.STOCK,
                venue="TWSE",
            ),
            interval="1m",
            range_value="1d",
            policy=RealtimePolicy.CACHE_ONLY,
            requested_at=requested_at,
            acquiring=False,
        )

        result = TaiwanIntradayBarRepository(db).read_bar_candidates(requirement)

        assert result.candidates == ()
        statement = str(captured["statement"])
        assert "market_intraday_bar.market = ?" in statement
        assert "market_intraday_bar.canonical_market = ?" in statement
        plan = db.connection().exec_driver_sql(
            "EXPLAIN QUERY PLAN " + statement,
            captured["parameters"],
        )
        assert any(TW_INTRADAY_READ_INDEX in str(row[-1]) for row in plan)
    finally:
        event.remove(engine, "before_cursor_execute", capture_intraday_select)
        db.close()
        engine.dispose()
