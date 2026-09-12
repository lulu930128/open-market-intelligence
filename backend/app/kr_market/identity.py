"""Provider-neutral KR instrument identity resolved from the local master only."""

from dataclasses import dataclass
import re

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.models import KRStockMaster
from app.market_data.contracts import InstrumentKey, InstrumentType, Market


class KRIdentityError(ValueError):
    """An instrument cannot be established without guessing its listing identity."""


@dataclass(frozen=True, slots=True)
class KRInstrumentIdentity:
    instrument: InstrumentKey
    listing_board: str
    storage_symbol: str
    master_id: int
    currency: str

    @property
    def yahoo_symbol(self) -> str:
        suffix = {"KOSPI": "KS", "KOSDAQ": "KQ"}.get(self.listing_board)
        if suffix is None:
            raise KRIdentityError("Yahoo mapping is unavailable for this KR listing board.")
        return f"{self.instrument.symbol}.{suffix}"


def resolve_kr_instrument_identity(db: Session, symbol: str) -> KRInstrumentIdentity:
    token = symbol.strip().upper()
    if token.startswith("KR:"):
        token = token[3:]
    match = re.fullmatch(r"([0-9A-Z]{6})(?:\.(KS|KQ))?", token)
    if match is None:
        raise KRIdentityError("KR identity requires a six-character local code or a known listing alias.")
    code, suffix = match.groups()
    with db.no_autoflush:
        rows = db.query(KRStockMaster).filter(or_(
            KRStockMaster.local_code == code,
            KRStockMaster.symbol.in_((code, f"{code}.KS", f"{code}.KQ")),
        )).limit(3).all()
    if len(rows) != 1:
        raise KRIdentityError("KR instrument master is missing or ambiguous; explicit master reconciliation is required.")
    row = rows[0]
    board = str(row.market_segment or "").strip().upper()
    # Historical Yahoo master rows retain provider exchange codes. Decode only
    # with matching persisted provider provenance and explicit listing suffix.
    # Yahoo suffix reference: https://help.yahoo.com/kb/finance/sln14237.html
    yahoo_board = {"KSC": ("KOSPI", ".KS"), "KOE": ("KOSDAQ", ".KQ")}.get(board)
    if yahoo_board and row.listing_source == "discovered_yahoo_chart" and row.symbol == code + yahoo_board[1]:
        board = yahoo_board[0]
    if board not in {"KOSPI", "KOSDAQ", "KONEX"}:
        raise KRIdentityError("KR listing board is unknown in the instrument master.")
    if suffix and {"KS": "KOSPI", "KQ": "KOSDAQ"}[suffix] != board:
        raise KRIdentityError("KR alias conflicts with the instrument master listing board.")
    expected_suffix = {"KOSPI": ".KS", "KOSDAQ": ".KQ"}.get(board)
    if row.symbol.endswith((".KS", ".KQ")) and not row.symbol.endswith(expected_suffix or ".KN"):
        raise KRIdentityError("KR stored listing alias conflicts with the master board.")
    if not row.is_active:
        raise KRIdentityError("KR instrument is inactive in the instrument master.")
    asset_type = str(row.asset_type or "").lower()
    if asset_type not in {"stock", "etf"}:
        raise KRIdentityError("KR instrument type is not established for canonical market data.")
    if row.local_code and row.local_code != code:
        raise KRIdentityError("KR master local code conflicts with the requested instrument.")
    return KRInstrumentIdentity(
        instrument=InstrumentKey(market=Market.KR, symbol=code,
                                 instrument_type=InstrumentType(asset_type), venue="KRX"),
        listing_board=board, storage_symbol=row.symbol, master_id=row.id,
        currency=row.currency,
    )
