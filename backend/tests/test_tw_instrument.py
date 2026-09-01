from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, StockMaster
from app.market.tw_instrument import (
    TaiwanInstrumentResolutionError,
    resolve_taiwan_instrument,
)
from app.market_data.contracts import InstrumentType, Market


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.add_all(
        (
            StockMaster(
                stock_id="2330",
                stock_name="TSMC",
                market="TWSE",
                instrument_type="stock",
            ),
            StockMaster(
                stock_id="0050",
                stock_name="ETF",
                market="TWSE",
                instrument_type="exchange_traded_fund",
            ),
            StockMaster(
                stock_id="6488",
                stock_name="TPEX stock",
                market="TPEX",
                instrument_type="equity",
            ),
            StockMaster(
                stock_id="0999",
                stock_name="Unknown",
                market="TWSE",
                instrument_type="unknown",
            ),
        )
    )
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.mark.parametrize(
    ("instrument_id", "instrument_type", "venue"),
    (
        ("2330", InstrumentType.STOCK, "TWSE"),
        ("0050", InstrumentType.ETF, "TWSE"),
        ("6488", InstrumentType.STOCK, "TPEX"),
        ("taiex", InstrumentType.INDEX, "TWSE"),
        ("tpex", InstrumentType.INDEX, "TPEX"),
    ),
)
def test_resolve_taiwan_instrument_parity(
    db: Session,
    instrument_id: str,
    instrument_type: InstrumentType,
    venue: str,
) -> None:
    result = resolve_taiwan_instrument(db, instrument_id)

    assert result.market is Market.TW
    assert result.symbol == instrument_id.upper()
    assert result.instrument_type is instrument_type
    assert result.venue == venue


def test_resolver_fails_closed_for_unknown_master_type(db: Session) -> None:
    with pytest.raises(
        TaiwanInstrumentResolutionError,
        match="canonical STOCK/ETF",
    ):
        resolve_taiwan_instrument(db, "0999")


def test_resolver_fails_closed_for_unregistered_symbol(db: Session) -> None:
    with pytest.raises(TaiwanInstrumentResolutionError, match="not registered"):
        resolve_taiwan_instrument(db, "3711")
