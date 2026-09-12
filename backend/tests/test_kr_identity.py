import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, KRStockMaster
from app.kr_market.identity import KRIdentityError, resolve_kr_instrument_identity


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([
            KRStockMaster(symbol="005930.KS", local_code="005930", market_segment="KOSPI", asset_type="stock"),
            KRStockMaster(symbol="035720.KQ", local_code="035720", market_segment="KOSDAQ", asset_type="stock"),
        ])
        session.commit()
        yield session
    engine.dispose()


def test_alias_and_local_code_resolve_to_same_provider_neutral_identity(db):
    local = resolve_kr_instrument_identity(db, "005930")
    alias = resolve_kr_instrument_identity(db, "005930.KS")
    assert local == alias
    assert local.instrument.symbol == "005930"
    assert local.instrument.venue == "KRX"
    assert local.yahoo_symbol == "005930.KS"
    assert resolve_kr_instrument_identity(db, "035720").yahoo_symbol == "035720.KQ"


@pytest.mark.parametrize("symbol", ["999999", "005930.KQ", "005930/OTHER", "5930", "005930.KS.extra"])
def test_invalid_missing_or_conflicting_identity_never_guesses(db, symbol):
    with pytest.raises(KRIdentityError):
        resolve_kr_instrument_identity(db, symbol)


def test_duplicate_master_and_unknown_board_are_not_silently_selected(db):
    db.add(KRStockMaster(symbol="005930", local_code="005930", market_segment="KOSPI", asset_type="stock"))
    db.commit()
    with pytest.raises(KRIdentityError, match="ambiguous"):
        resolve_kr_instrument_identity(db, "005930")
    row = db.query(KRStockMaster).filter_by(symbol="035720.KQ").one()
    row.market_segment = "unknown"
    db.commit()
    with pytest.raises(KRIdentityError, match="board"):
        resolve_kr_instrument_identity(db, "035720")


def test_provider_master_board_alias_requires_provenance_and_matching_stored_suffix(db):
    row = db.query(KRStockMaster).filter_by(symbol="005930.KS").one()
    row.market_segment = "KSC"
    row.listing_source = "discovered_yahoo_chart"
    db.commit()
    assert resolve_kr_instrument_identity(db, "005930").listing_board == "KOSPI"
    row.listing_source = "unknown"
    db.commit()
    with pytest.raises(KRIdentityError, match="board"):
        resolve_kr_instrument_identity(db, "005930")
