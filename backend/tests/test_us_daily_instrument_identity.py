from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, USStockMaster
from app.market_data.contracts import InstrumentType
from app.us_market.daily_market_state import resolve_us_instrument_identity


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_sox_identity_does_not_require_company_or_sec_rows() -> None:
    db = _session()
    try:
        identity = resolve_us_instrument_identity(db, "SOX")
        assert identity.instrument.symbol == "^SOX"
        assert identity.instrument.instrument_type is InstrumentType.INDEX
        assert identity.instrument.venue == "NASDAQ_INDEX"
        assert identity.identity_source == "market_index_registry"
        assert identity.volume_applicability == "not_applicable"
    finally:
        db.close()


def test_stock_identity_uses_market_master_and_missing_venue_fails_visible() -> None:
    db = _session()
    try:
        db.add(USStockMaster(symbol="TSM", exchange="NYSE", is_etf=False))
        db.add(USStockMaster(symbol="NOVENUE", exchange=None, is_etf=False))
        db.commit()

        identity = resolve_us_instrument_identity(db, "TSM")
        assert identity.instrument.instrument_type is InstrumentType.STOCK
        assert identity.instrument.venue == "NYSE"
        assert identity.volume_applicability == "required"

        with pytest.raises(LookupError, match="identity is unavailable"):
            resolve_us_instrument_identity(db, "NOVENUE")
    finally:
        db.close()
