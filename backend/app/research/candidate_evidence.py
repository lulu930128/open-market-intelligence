"""Cache-only adaptation of existing OMI quote/bar/technical owners."""
from dataclasses import dataclass, field, replace
from datetime import datetime, time, timedelta
from decimal import Decimal

from .conditional_candidate import Evidence, TAIPEI, digest, metrics


@dataclass(frozen=True)
class MarketEvidence:
    values: dict[str, Evidence] = field(default_factory=dict)
    proposed_limit: str | None = None
    price_evidence: dict = field(default_factory=dict)
    trade_date: str | None = None
    lower_limit: str | None = None
    upper_limit: str | None = None
    limits_source: dict = field(default_factory=dict)
    borrow_status: str = "UNKNOWN"
    funding_status: str = "UNKNOWN"
    instrument_status: str = "UNKNOWN"


def _quote_evidence(result, observation, value, now):
    if observation is None or value is None:
        return None
    lineage = observation.lineage
    received = lineage.received_at or lineage.fetched_at
    source_at = lineage.event_at
    if received is None or source_at is None:
        return None
    return Evidence(value=value, source=lineage.source, source_at=source_at, received_at=received,
        available_at=received, valid_until=source_at + timedelta(seconds=result.requirement.freshness.max_age_seconds),
        revision=lineage.content_hash or lineage.observation_id or "", timeframe="snapshot",
        quality="usable" if result.resolved.health.facts_usable else "unknown")


def read_research_price_evidence(db, symbol, now) -> MarketEvidence:
    """Share canonical last-trade adaptation without execution candidate intent."""
    from app.market.public_quote_platform import (
        read_taiwan_public_last_trade_quote, project_taiwan_public_last_trade_quote,
    )
    from .conditional_candidate import Metric

    result = read_taiwan_public_last_trade_quote(db, stock_id=symbol, requested_at=now)
    projected = project_taiwan_public_last_trade_quote(result)
    quote = result.resolved.quote
    metric = Metric(kind="price", field="last_trade", timeframe="snapshot")
    item = _quote_evidence(result, quote, quote.last_trade_price if quote else None, now)
    usable = bool(projected["actual_trade_occurred"] and projected["last_trade_is_current_session"]
        and quote and quote.instrument.symbol == symbol and quote.trade_date == now.astimezone(TAIPEI).date()
        and projected["freshness"]["status"] in {"live", "current"}
        and projected["session_phase"] in {"regular", "closing_auction"})
    if item is not None and not usable:
        item = item.model_copy(update={"quality": "unknown"})
    metadata = {key: projected.get(key) for key in (
        "trade_date", "quote_time", "received_at", "fetched_at", "actual_trade_occurred",
        "last_trade_is_current_session", "session_phase", "freshness", "provider", "source", "limitations")}
    metadata.update(trade_state=quote.trade_state.value if quote else "unknown",
                    market=quote.instrument.venue if quote else None,
                    price_semantics="actual_trade" if projected["actual_trade_occurred"] else
                    "auction_indicative" if quote and quote.trade_state.value == "indicative_observed" else "unknown")
    return MarketEvidence(values={metric.key: item} if item else {},
        trade_date=quote.trade_date.isoformat() if quote and quote.trade_date else None, price_evidence=metadata)


def read_market_evidence(db, spec, now) -> MarketEvidence:
    from app.market.taiwan_quote_evidence import read_taiwan_quote_evidence_bundle
    from app.market.tw_bar_service import TaiwanBarService
    from app.market.tw_technical_service import TaiwanTechnicalService
    from app.market.technical_parameters import get_technical_analysis_parameters
    from app.market.taiwan_rules import expected_daily_price_date, taiwan_daily_price_release_at
    from app.market.trading_calendar import next_taiwan_trading_day

    bundle = read_taiwan_quote_evidence_bundle(db, stock_id=spec.symbol, requested_at=now)
    quote, depth, auction = bundle.quote.resolved.quote, bundle.depth.resolved.depth, bundle.auction.resolved.auction
    values = {}
    wanted = metrics(spec.conditions)
    for metric in wanted:
        if metric.kind != "price":
            continue
        if metric.field == "last_trade":
            item = _quote_evidence(bundle.quote, quote, quote.last_trade_price if quote else None, now)
        elif metric.field in {"bid", "ask"}:
            levels = getattr(depth, "bids" if metric.field == "bid" else "asks", ())
            item = _quote_evidence(bundle.depth, depth, levels[0].price if levels else None, now)
        elif metric.field == "indicative":
            item = _quote_evidence(bundle.auction, auction, auction.indicative_price if auction else None, now)
        else:
            item = None
        if item:
            values[metric.key] = item

    # The existing technical owner performs all RSI/MACD/support calculations.
    bars = TaiwanBarService(db).read_bars(instrument_id=spec.symbol, interval="1d", limit=400,
                                        include_partial=False, requested_at=now)
    parameters = get_technical_analysis_parameters()
    base = TaiwanTechnicalService().calculate(bars, parameters=parameters)
    price, price_source = None, {}
    if (base.points and base.decision_usable and bars.bars and
        bars.bars[-1].start_at.astimezone(TAIPEI).date() == expected_daily_price_date(now=now)):
        point = base.points[-1]
        key = parameters.support_key if spec.price_basis == "support" else parameters.resistance_key
        level = (point.get("support_resistance") or {}).get(key)
        if level is not None:
            from app.market.taiwan_price_rules import normalize_taiwan_stock_price
            price = str(normalize_taiwan_stock_price(level))
            price_source = {"basis": spec.price_basis, "level": str(level), "key": key,
                            "parameter_revision": parameters.revision,
                            "algorithm_version": point.get("algorithm_version"), "as_of": str(point["time"])}
    if spec.price_basis == "explicit":
        price = str(spec.proposed_limit) if spec.proposed_limit is not None else None
        price_source = {"basis": "explicit"}
    for metric in wanted:
        if metric.kind == "price" or not bars.bars:
            continue
        if metric.kind == "rsi" and len(metric.parameters) == 1 and metric.parameters[0] > 0:
            selected = replace(parameters, rsi_period=metric.parameters[0])
        elif metric.kind == "macd" and len(metric.parameters) == 3 and 0 < metric.parameters[0] < metric.parameters[1] and metric.parameters[2] > 0:
            selected = replace(parameters, macd_fast_period=metric.parameters[0],
                               macd_slow_period=metric.parameters[1], macd_signal_period=metric.parameters[2])
        else:
            continue
        technical = TaiwanTechnicalService().calculate(bars, parameters=selected)
        if not technical.points:
            continue
        point, bar = technical.points[-1], bars.bars[-1]
        value = ((point.get("rsi") or {}).get(selected.rsi_key) if metric.kind == "rsi"
                 else (point.get("macd") or {}).get(metric.field))
        lineage = bar.lineage
        received = lineage.received_at or lineage.fetched_at
        if received is None:
            continue
        day = bar.start_at.astimezone(TAIPEI).date()
        current = day == expected_daily_price_date(now=now)
        values[metric.key] = Evidence(value=value, source=lineage.source, source_at=lineage.event_at or bar.start_at,
            received_at=received, available_at=max(received, taiwan_daily_price_release_at(day)),
            valid_until=taiwan_daily_price_release_at(next_taiwan_trading_day(day)),
            revision=technical.technical_revision,
            quality="usable" if technical.decision_usable and current else "unknown", completed=True,
            timeframe="1d", parameters=metric.parameters, algorithm_version=point.get("algorithm_version"))
    limits = quote.price_limits if quote else None
    return MarketEvidence(values=values, proposed_limit=price, price_evidence=price_source,
        trade_date=limits.trade_date.isoformat() if limits else None,
        lower_limit=str(limits.lower) if limits else None, upper_limit=str(limits.upper) if limits else None,
        limits_source=limits.lineage.model_dump(mode="json") if limits else {},
        instrument_status="OBSERVED" if quote else "UNKNOWN")


def order_qualification(spec, price, market: MarketEvidence, now):
    """Entry admission facts, independent of whether a trade has occurred."""
    from app.market.taiwan_price_rules import normalize_taiwan_stock_price
    from app.market.trading_calendar import (is_taiwan_trading_day, has_taiwan_calendar_year,
        TAIWAN_PREOPEN_TIME, TAIWAN_SESSION_OPEN_TIME, TAIWAN_SESSION_CLOSE_TIME)
    local = now.astimezone(TAIPEI)
    today, clock = local.date(), local.time().replace(tzinfo=None)
    reasons = []
    start = TAIWAN_PREOPEN_TIME if spec.lot == "Common" else TAIWAN_SESSION_OPEN_TIME
    calendar_known = has_taiwan_calendar_year(today.year)
    accepting = calendar_known and is_taiwan_trading_day(today) and start <= clock <= TAIWAN_SESSION_CLOSE_TIME
    matching = accepting and clock >= (TAIWAN_SESSION_OPEN_TIME if spec.lot == "Common" else time(9, 10))
    if not calendar_known:
        reasons.append("CALENDAR_UNKNOWN")
    if not accepting:
        reasons.append("OUTSIDE_ORDER_ACCEPTANCE_WINDOW")
    if price is None:
        reasons.append("WAITING_PRICE")
    else:
        value = Decimal(price)
        if value <= 0 or Decimal(str(normalize_taiwan_stock_price(value))) != value:
            reasons.append("INVALID_PRICE_TICK")
        if market.trade_date != today.isoformat() or not market.limits_source or market.lower_limit is None or market.upper_limit is None:
            reasons.append("DAILY_PRICE_LIMITS_UNKNOWN")
        elif not Decimal(market.lower_limit) <= value <= Decimal(market.upper_limit):
            reasons.append("OUTSIDE_DAILY_PRICE_LIMITS")
        sign = 1 if spec.direction == "long" else -1
        if ((spec.stop_loss is not None and sign * (value - spec.stop_loss) <= 0)
            or (spec.take_profit is not None and sign * (spec.take_profit - value) <= 0)):
            reasons.append("INVALID_LEVEL_DIRECTION")
    if spec.direction == "short" and market.borrow_status != "AVAILABLE":
        reasons.append("BORROW_UNKNOWN")
    if spec.direction == "short" and (spec.stop_loss is not None or spec.take_profit is not None):
        reasons.append("SHORT_COVER_UNVERIFIED")
    if (spec.stop_loss is not None or spec.take_profit is not None) and spec.exit_limit_price is None:
        reasons.append("EXIT_LIMIT_REQUIRED")
    return {"send_ready": not reasons, "reasons": reasons, "order_accepting": accepting,
            "matching_window": matching, "fill_status": "NOT_SUBMITTED", "trade_date": today.isoformat(),
            "borrow_status": market.borrow_status, "funding_status": market.funding_status,
            "instrument_status": market.instrument_status, "price_limits_source": market.limits_source,
            "lower_limit": market.lower_limit, "upper_limit": market.upper_limit}
