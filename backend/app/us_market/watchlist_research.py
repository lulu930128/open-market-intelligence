"""US watchlist research policy over cache-only canonical evidence.

The Journal owns immutable persistence. This module neither acquires market data
nor infers corporate-action completeness from an empty event table.
"""
from datetime import datetime
from uuid import NAMESPACE_URL, uuid5
import json

from app.db.models import utc_now
from app.market_data.contracts import BarFinalization, InstrumentType, Market
from app.research import trade_journal
from app.research.technical import US_DAILY_PROFILE
from app.research.trade_proposal import (
    EvidenceItem, PaperBar, PaperStrategy, PaperTarget, ProposalEvidence, canonical_json, content_hash,
)
from app.us_market.daily_ohlcv_platform import USDailyOhlcvPlatform
from app.us_market.research_service import build_us_market_research
from app.us_market.research_math import evaluate_us_strategy
from app.us_market.sources import normalize_us_symbol
from app.us_market.trading_calendar import US_MARKET_TIMEZONE, us_daily_price_release_time
from app.us_market.watchlist_store import list_us_watchlist_symbols

SOURCE = "research.us_watchlist_nomination.v1"
STRATEGY = "us.watchlist.daily_pivot_retest.v1"


def read_evidence(db, symbol, day, cutoff):
    research = build_us_market_research(db, symbol=symbol, bars=260, now=cutoff,
                                       to_date=day, include_market_coverage=False)
    quality = research["technical_indicators"].get("quality", {})
    reasons = list(quality.get("reason_codes", []))
    if quality.get("decision_usable") is not True:
        reasons.append("US_TECHNICAL_NOT_DECISION_USABLE")
    coverage = research.get("corporate_action_coverage", {})
    if coverage.get("status") != "complete":
        reasons.extend(coverage.get("reason_codes", []))
        reasons.append("CORPORATE_ACTION_COVERAGE_NOT_COMPLETE")
    # Preserve actual receipts and identity; display projections omit received_at.
    try:
        platform = USDailyOhlcvPlatform(db).read(symbol=symbol, bars=260, now=cutoff, to_date=day)
    except (LookupError, ValueError) as exc:
        return {"research": research, "bars": [], "identity": {}, "reason_codes": list(dict.fromkeys([*reasons, str(exc)]))}
    instrument = platform.identity.instrument
    if instrument.market != Market.US or instrument.symbol != symbol or instrument.instrument_type not in {
        InstrumentType.STOCK, InstrumentType.ETF,
    }:
        reasons.append("US_STOCK_OR_ETF_IDENTITY_REQUIRED")
    rows = []
    for bar in platform.result.resolved.bars:
        lineage = bar.lineage
        trade_date = bar.end_at.astimezone(US_MARKET_TIMEZONE).date()
        receipts = [t for t in (lineage.received_at, lineage.fetched_at) if t is not None]
        revision = lineage.content_hash or lineage.raw_receipt_id
        release = datetime.combine(trade_date, us_daily_price_release_time(trade_date), US_MARKET_TIMEZONE)
        available = max(release, bar.end_at, lineage.event_at or bar.end_at)
        if (bar.instrument != instrument or bar.interval != "1d" or not receipts or not revision
                or bar.price_basis != "raw" or bar.finalization not in {BarFinalization.FINAL, BarFinalization.CORRECTED}
                or trade_date > day or max(available, *receipts) > cutoff):
            reasons.append("US_DAILY_IDENTITY_FINALIZATION_OR_RECEIPT_INVALID")
            continue
        try:
            rows.append(PaperBar(market="US", symbol=symbol, trade_date=trade_date,
                open_price=float(bar.open_price), high_price=float(bar.high_price),
                low_price=float(bar.low_price), close_price=float(bar.close_price),
                source_ref=f"{lineage.provider}:{lineage.source}", data_revision=revision,
                source_available_at=available, received_at=max(receipts), price_basis=bar.price_basis,
                corporate_action="clear" if coverage.get("status") == "complete" else "unknown").model_dump(mode="json"))
        except ValueError:
            reasons.append("US_DAILY_OHLC_INVALID")
    rows.sort(key=lambda row: row["trade_date"])
    if len(rows) < US_DAILY_PROFILE.decision_minimum_bars or not rows or rows[-1]["trade_date"] != day.isoformat():
        reasons.append("US_COMPLETED_DAILY_HISTORY_INCOMPLETE")
    if len({row["trade_date"] for row in rows}) != len(rows):
        reasons.append("US_DAILY_DUPLICATE_SESSIONS")
    projected = research.get("daily_ohlcv", {}).get("bars", [])
    if len(projected) != len(rows) or any(
        any(float(a.get(key, 0)) != b[key] for key in ("open_price", "high_price", "low_price", "close_price"))
        for a, b in zip(projected, rows)
    ):
        reasons.append("US_RESEARCH_CANONICAL_SNAPSHOT_CHANGED")
    return {"research": research, "bars": rows, "identity": {
        "market": "US", "symbol": symbol, "instrument_type": instrument.instrument_type.value,
        "venue": instrument.venue,
    }, "reason_codes": list(dict.fromkeys(reasons))}


def pivot_strategy(bars, direction, quantity):
    """Confirmed five-session pivots; candle body is entry, wick is invalidation.

    Two distinct opposite pivots must supply targets. No projected R multiples,
    future pivot bars or Taiwan tick rounding are introduced.
    """
    sign = 1 if direction == "long" else -1
    close = bars[-1]["close_price"]
    lows, highs = [], []
    for index in range(2, len(bars) - 2):
        bar = bars[index]
        neighbors = bars[index - 2:index] + bars[index + 1:index + 3]
        if all(bar["low_price"] < other["low_price"] for other in neighbors):
            lows.append(bar)
        if all(bar["high_price"] > other["high_price"] for other in neighbors):
            highs.append(bar)
    entries = []
    for bar in lows if sign == 1 else highs:
        if bar["trade_date"] < bars[-60]["trade_date"]:
            continue
        entry = (max if sign == 1 else min)(bar["open_price"], bar["close_price"])
        stop = bar["low_price" if sign == 1 else "high_price"]
        if sign * (close - entry) > 0 and sign * (entry - stop) > 0:
            # A pivot invalidated by a later completed close is no longer support/resistance.
            if all(sign * (later["close_price"] - stop) > 0 for later in bars if later["trade_date"] > bar["trade_date"]):
                entries.append((entry, stop, bar))
    if not entries:
        raise ValueError("NO_VALID_DAILY_PIVOT_ENTRY")
    entry, stop, pivot = min(entries, key=lambda item: abs(close - item[0]))
    target_key = "high_price" if sign == 1 else "low_price"
    targets = sorted({bar[target_key] for bar in (highs if sign == 1 else lows)
                      if sign * (bar[target_key] - close) > 0}, reverse=sign == -1)
    if len(targets) < 2:
        raise ValueError("TWO_DISTINCT_DAILY_PIVOT_TARGETS_MISSING")
    strategy = PaperStrategy(version=STRATEGY, direction=sign, mode="aggressive",
        entry_rule="at_or_below" if sign == 1 else "at_or_above", entry_price=entry, stop_price=stop,
        targets=tuple(PaperTarget(price=price, fraction=0.5) for price in targets[:2]), shares=quantity,
        thesis="等待回測已確認日線支撐" if sign == 1 else "等待反彈已確認日線壓力",
        counter_evidence=(f"日線停損界線：{stop}", "公司事件、盤中觸價次序、券源與執行資格另行核對"),
        paper_eligibility="unknown", qualification_refs=(SOURCE,))
    return strategy, {"pivot_date": pivot["trade_date"], "entry": entry, "stop": stop, "targets": targets[:2]}


def create_nominations(db, request, *, automatic=False, discovery_context=None):
    from app.research.trade_journal_http_service import JournalHttpError, _proposal_read
    now = utc_now()
    if request.requested_at > now:
        raise JournalHttpError(422, "FUTURE_KNOWLEDGE_TIME", "Knowledge time cannot be in the future.")
    rows = []
    with db.begin():
        membership = set(list_us_watchlist_symbols(db, enabled_only=True))
        for symbol in dict.fromkeys(normalize_us_symbol(s) for s in request.stock_ids):
            evidence = (read_evidence(db, symbol, request.as_of_trade_date, request.requested_at)
                        if symbol in membership else {"reason_codes": ["US_ENABLED_WATCHLIST_MEMBERSHIP_REQUIRED"]})
            for direction in ("long", "short") if request.direction == "both" else (request.direction,):
                row = {"stock_id": symbol, "direction": direction, "status": "DATA_BLOCKED",
                       "reason_codes": evidence["reason_codes"], "proposal": None, "deduplicated": False}
                rows.append(row)
                if row["reason_codes"]:
                    continue
                try:
                    strategy, levels = pivot_strategy(evidence["bars"], direction, request.quantity)
                except ValueError as exc:
                    row.update(status="NO_SETUP", reason_codes=[str(exc)])
                    continue
                creation_id = str(uuid5(NAMESPACE_URL, canonical_json([
                    "omi.research.US.watchlist", symbol, direction, request.as_of_trade_date.isoformat(),
                    STRATEGY, request.horizon_sessions,
                ]))) if automatic else None
                prior = trade_journal.list_versions(db, creation_id=creation_id, as_of=now) if creation_id else ()
                if prior:
                    version = prior[-1]
                    if version.deleted_at is not None:
                        row.update(status="DELETED", reason_codes=["PROPOSAL_DELETED"], deduplicated=True)
                        continue
                    row["deduplicated"] = True
                else:
                    snapshot = {"request": request.model_dump(mode="json"), "identity": evidence["identity"],
                        "assessment": {"status": "qualified", "reason_codes": []}, "selected_levels": levels,
                        "evidence": evidence, "discovery": discovery_context or {"scope": "enabled_us_watchlist"}}
                    bars = [PaperBar.model_validate(bar) for bar in evidence["bars"]]
                    frozen = ProposalEvidence(market="US", as_of_trade_date=request.as_of_trade_date,
                        cutoff=request.requested_at, price_basis="raw", items=(EvidenceItem(source_ref=SOURCE,
                        source_available_at=max(b.source_available_at for b in bars),
                        received_at=max(b.received_at for b in bars), data_revision=content_hash(snapshot),
                        snapshot_json=canonical_json(snapshot)),))
                    version = trade_journal.create_proposal(db, market="US", symbol=symbol, evidence=frozen,
                        strategy=strategy, costs=request.costs, effective_at=now, now=now,
                        change_reason=request.nomination_origin, creation_id=creation_id,
                        horizon_sessions=request.horizon_sessions)
                row.update(status="WAITING_PRICE", proposal=_proposal_read(version, now).model_dump(mode="json"))
    return {"status": "partial" if any(r["status"] == "DATA_BLOCKED" for r in rows) else "ready",
            "nomination_origin": request.nomination_origin, "scenarios": rows,
            "coverage": {"scope": "enabled_us_watchlist", "symbols": len({r["stock_id"] for r in rows}),
                         "full_market": False}, "execution_ready": False}


def proposal_eligibility(version):
    snapshot = next((json.loads(item.snapshot_json) for item in version.evidence.items if item.source_ref == SOURCE), {})
    assessment = snapshot.get("assessment") if isinstance(snapshot, dict) else None
    assessment = assessment if isinstance(assessment, dict) else {}
    return {"research_eligible": assessment.get("status") == "qualified",
            "regulation_eligible": "unknown", "borrow_eligible": "unknown", "execution_eligible": False,
            "reason_codes": ["US_EXECUTION_ELIGIBILITY_NOT_ASSESSED"]}


def read_outcome_bars(db, version, as_of):
    from app.us_market.trading_calendar import expected_us_daily_price_date
    day = min(version.planned_trade_dates[-1], expected_us_daily_price_date(now=as_of))
    if day < version.planned_trade_dates[0]:
        return (), ("canonical_window_not_yet_released",)
    evidence = read_evidence(db, version.symbol, day, as_of)
    if evidence["reason_codes"]:
        return (), tuple(evidence["reason_codes"])
    bars = tuple(PaperBar.model_validate(bar) for bar in evidence["bars"]
                 if bar["trade_date"] in {d.isoformat() for d in version.planned_trade_dates})
    return bars, tuple(evidence["reason_codes"])


def read_monitor(db, version, now):
    from app.us_market.trading_calendar import expected_us_daily_price_date
    horizon = version.outcome_horizon_sessions or 10
    first, last = version.planned_trade_dates[0], version.planned_trade_dates[horizon - 1]
    result = {"creation_id": version.creation_id, "revision_id": version.revision_id,
        "checked_at": now.isoformat(), "valid_from_date": first.isoformat(), "valid_until_date": last.isoformat(),
        "status": "DATA_UNKNOWN", "reason_codes": [], "price_condition": "UNKNOWN", "confirmation": "UNKNOWN",
        "confirmation_basis": "us_completed_daily_close", "quote": {}, "setup_evaluation": None,
        "eligibility": proposal_eligibility(version), "execution_ready": False,
        "limitations": ["僅評估最新已完成美股日線收盤；不代表盤中觸發、成交或歷史觸價次序。"],
        "cache_policy": "cache_only_no_refresh_no_write"}

    def finish(status, *reasons):
        result.update(status=status, reason_codes=list(reasons))
        result["observation_id"] = content_hash({k: v for k, v in result.items() if k != "checked_at"})
        return result

    if now.astimezone(US_MARKET_TIMEZONE).date() > last:
        return finish("EXPIRED", "VALID_UNTIL_PASSED")
    if not version.calendar_verified:
        return finish("DATA_UNKNOWN", "US_FROZEN_CALENDAR_UNVERIFIED")
    day = expected_us_daily_price_date(now=now)
    if day < first:
        return finish("WAITING_PRICE", "COMPLETED_SESSION_BEFORE_VALID_FROM")
    evidence = read_evidence(db, version.symbol, day, now)
    if evidence["reason_codes"]:
        return finish("DATA_UNKNOWN", *evidence["reason_codes"])
    bar, strategy = evidence["bars"][-1], version.strategy
    price = bar["close_price"]
    result["quote"] = {"trade_date": bar["trade_date"], "quote_time": bar["source_available_at"],
        "received_at": bar["received_at"], "source": bar["source_ref"], "price_semantics": "completed_daily_close",
        "evidence": {"value": price, "source_at": bar["source_available_at"], "revision": bar["data_revision"]}}
    if strategy.direction * (price - strategy.stop_price) <= 0:
        return finish("INVALIDATED", "COMPLETED_CLOSE_BEYOND_STOP")
    if strategy.mode != "aggressive" or strategy.entry_rule == "next_open":
        return finish("DATA_UNKNOWN", "US_MONITOR_STRATEGY_UNSUPPORTED")
    reached = price >= strategy.entry_price if strategy.entry_rule == "at_or_above" else price <= strategy.entry_price
    result["price_condition"] = "TRUE" if reached else "FALSE"
    result["confirmation"] = "TRUE"
    if not reached:
        return finish("WAITING_PRICE", "COMPLETED_CLOSE_ENTRY_CONDITION_FALSE")
    try:
        result["setup_evaluation"] = evaluate_us_strategy(strategy.model_copy(update={"entry_price": price}), version.costs, horizon)
    except ValueError:
        return finish("INVALIDATED", "CURRENT_PRICE_OUTSIDE_BRACKET")
    return finish("REVIEWABLE", "US_EXECUTION_ELIGIBILITY_NOT_ASSESSED")
