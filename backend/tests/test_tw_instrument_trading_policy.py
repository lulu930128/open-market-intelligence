from app.market.tw_instrument_trading_policy import (
    TaiwanAnalysisBasis,
    TaiwanInstrumentTradingMode,
    resolve_taiwan_auction_applicability,
    resolve_taiwan_instrument_trading_policy,
)
from app.market_data.contracts import AuctionType, MarketSession


def test_missing_or_stale_disposition_cache_keeps_trading_semantics_unknown() -> None:
    for cache_status in ("missing", "stale", "degraded"):
        policy = resolve_taiwan_instrument_trading_policy(
            {"cache_status": cache_status, "is_active": False}
        )

        assert policy.market_semantics_usable is False
        assert policy.disposition_active is None
        assert policy.trading_mode is TaiwanInstrumentTradingMode.UNKNOWN
        assert policy.analysis_basis is TaiwanAnalysisBasis.UNKNOWN


def test_current_cache_without_typed_active_state_fails_closed() -> None:
    policy = resolve_taiwan_instrument_trading_policy(
        {"cache_status": "current", "is_active": None}
    )

    assert policy.market_semantics_usable is False
    assert policy.disposition_active is None
    assert policy.trading_mode is TaiwanInstrumentTradingMode.UNKNOWN
    assert policy.reason_codes == ("DISPOSITION_ACTIVE_UNKNOWN",)


def test_current_disposition_cache_distinguishes_continuous_and_batch_matching() -> None:
    continuous = resolve_taiwan_instrument_trading_policy(
        {"cache_status": "current", "is_active": False}
    )
    batch = resolve_taiwan_instrument_trading_policy(
        {"cache_status": "current", "is_active": True}
    )

    assert continuous.trading_mode is TaiwanInstrumentTradingMode.CONTINUOUS
    assert continuous.analysis_basis is TaiwanAnalysisBasis.TIME_BARS
    assert batch.trading_mode is TaiwanInstrumentTradingMode.DISPOSITION_BATCH_AUCTION
    assert batch.analysis_basis is TaiwanAnalysisBasis.EFFECTIVE_MATCHES


def test_disposition_batch_matching_is_canonical_intraday_auction() -> None:
    applicability = resolve_taiwan_auction_applicability(
        session=MarketSession.CONTINUOUS,
        disposition={"cache_status": "current", "is_active": True},
    )

    assert applicability.applicable is True
    assert applicability.auction_type is AuctionType.INTRADAY
    assert applicability.reason_codes == ("DISPOSITION_INTRADAY_AUCTION",)


def test_continuous_unknown_disposition_fails_closed_but_market_auctions_do_not() -> None:
    unknown = resolve_taiwan_auction_applicability(
        session=MarketSession.CONTINUOUS,
        disposition={"cache_status": "missing", "is_active": False},
    )
    opening = resolve_taiwan_auction_applicability(
        session=MarketSession.OPENING_AUCTION,
        disposition={"cache_status": "missing", "is_active": False},
    )

    assert unknown.applicable is None
    assert unknown.auction_type is None
    assert opening.applicable is True
    assert opening.auction_type is AuctionType.OPENING
