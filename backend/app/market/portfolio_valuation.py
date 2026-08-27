"""Taiwan market-owned cached valuation selection."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.market.taiwan_quote_evidence import read_taiwan_quote_evidence_bundle
from app.market_data.contracts import Market, TradeObservationState
from app.market_data.valuation import ValuationPriceEvidence


def read_taiwan_valuation_price(
    db: Session,
    *,
    symbol: str,
    requested_at: datetime,
) -> ValuationPriceEvidence:
    quote_bundle = read_taiwan_quote_evidence_bundle(
        db,
        stock_id=symbol,
        requested_at=requested_at,
    )
    quote = quote_bundle.quote.resolved.quote
    quote_health = quote_bundle.quote.resolved.health
    if (
        quote is not None
        and quote.trade_state is TradeObservationState.TRADE_OBSERVED
        and quote.last_trade_price is not None
        and quote_health.facts_usable
    ):
        return ValuationPriceEvidence(
            market=Market.TW,
            symbol=symbol,
            price=quote.last_trade_price,
            currency="TWD",
            as_of=quote.lineage.event_at,
            provider=quote.lineage.provider,
            source=quote.lineage.source,
            source_kind="resolved_actual_trade_quote",
            facts_usable=quote_health.facts_usable,
            research_usable=quote_health.research_usable,
            resolved_status=quote_health.status.value,
            limitations=tuple(
                dict.fromkeys(
                    (*quote_bundle.quote.limitations, *quote_health.limitations)
                )
            ),
        )

    daily_result = quote_bundle.official_close
    daily_health = daily_result.resolved.health
    daily_bar = (
        daily_result.resolved.bars[-1]
        if daily_result.resolved.bars
        else None
    )
    if daily_bar is None:
        return ValuationPriceEvidence(
            market=Market.TW,
            symbol=symbol,
            currency="TWD",
            source_kind="missing",
            facts_usable=False,
            research_usable=False,
            resolved_status=daily_health.status.value,
            limitations=tuple(
                dict.fromkeys(
                    (
                        *quote_bundle.quote.limitations,
                        *quote_health.limitations,
                        *daily_result.limitations,
                        *daily_health.limitations,
                        "TW_VALUATION_PRICE_MISSING",
                    )
                )
            ),
        )
    return ValuationPriceEvidence(
        market=Market.TW,
        symbol=symbol,
        price=daily_bar.close_price,
        currency="TWD",
        as_of=daily_bar.end_at,
        provider=daily_bar.lineage.provider,
        source=daily_bar.lineage.source,
        source_kind="resolved_completed_daily_close",
        facts_usable=daily_health.facts_usable,
        research_usable=daily_health.research_usable,
        resolved_status=daily_health.status.value,
        limitations=tuple(
            dict.fromkeys((*daily_result.limitations, *daily_health.limitations))
        ),
    )


__all__ = ["read_taiwan_valuation_price"]
