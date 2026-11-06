"""Cache-only universe scan over published geometry and resolved observations."""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timezone
import json
from math import isfinite
from typing import Any

from sqlalchemy.orm import Session

from app.market.price_map_snapshot_repository import (
    read_input_revisions, read_price_map_snapshots, read_price_map_universe, snapshot_storage_available,
    snapshot_matches, read_price_map_external_revision,
)
from app.market.price_map_reaction import price_map_reaction
from app.market.technical_parameters import get_technical_analysis_parameters
from app.market.trading_calendar import TAIWAN_TZ, latest_completed_taiwan_session_date
from app.market.tw_intraday_state import read_tw_price_map_observations
from app.market.daily_price_repository import TaiwanOfficialDailyBarRepository
from app.market_data.contracts import AuthorityClass, BarFinalization
from app.market.taiwan_rules import TAIWAN_DAILY_REGULAR_SCOPE

POSITION_RELATIONS = ("near_zone", "touching", "above_zone", "below_zone")
REACTION_RELATIONS = ("support_reaction", "resistance_reaction", "breakout_retest", "breakdown_retest")
RELATIONS = (*POSITION_RELATIONS, *REACTION_RELATIONS, "within_zone")
STRUCTURE_TIMEFRAMES = ("daily", "weekly", "monthly")
SCANNER_VERSION = "tw.screening.price_map.v1"


def normalize_price_map_scan_parameters(parameters: dict | None) -> dict[str, Any]:
    raw = dict(parameters or {})
    if set(raw) - {"timeframe", "relation", "zone_side", "near_pct", "lane", "limit", "offset", "universe"}:
        raise ValueError("Unknown Price Map scanner parameter")
    timeframe = raw.get("timeframe", "daily")
    relation = raw.get("relation", "near_zone")
    lane = raw.get("lane", "actual")
    zone_side = raw.get("zone_side", "any")
    if zone_side not in {"any", "upside", "downside"}:
        raise ValueError("Invalid Price Map zone_side")
    if timeframe not in STRUCTURE_TIMEFRAMES or relation not in RELATIONS or lane not in {"actual", "indicative", "completed_daily"}:
        raise ValueError("Unsupported Price Map timeframe, relation, or observation lane")
    if lane == "indicative" and relation not in POSITION_RELATIONS:
        raise ValueError("Indicative observations cannot confirm trade reaction events")
    if lane == "completed_daily" and relation not in {"near_zone", "within_zone", "above_zone", "below_zone"}:
        raise ValueError("Completed daily close only supports closing price position, not intraday touch or reaction")
    if relation == "within_zone" and lane != "completed_daily":
        raise ValueError("within_zone requires completed_daily observations")
    limit, offset = raw.get("limit", 20), raw.get("offset", 0)
    if type(limit) is not int or type(offset) is not int or not 1 <= limit <= 200 or not 0 <= offset <= 5000:
        raise ValueError("Price Map scanner pagination is out of range")
    near = raw.get("near_pct", 0.5)
    if isinstance(near, bool) or not isinstance(near, (int, float)) or not isfinite(near) or not 0 <= near <= 5:
        raise ValueError("Price Map near_pct must be between 0 and 5")
    universe = raw.get("universe") or {}
    if not isinstance(universe, dict) or set(universe) - {"markets", "stock_ids"}:
        raise ValueError("Invalid Price Map universe")
    markets, stock_ids = universe.get("markets", ["TWSE", "TPEX"]), universe.get("stock_ids", [])
    if not isinstance(markets, list) or not markets or len(markets) > 2 or any(m not in {"TWSE", "TPEX"} for m in markets):
        raise ValueError("Invalid Price Map markets")
    if not isinstance(stock_ids, list) or len(stock_ids) > 2500 or any(not isinstance(s, str) or not s.strip() or len(s) > 20 for s in stock_ids):
        raise ValueError("Invalid bounded Price Map stock_ids")
    return dict(timeframe=timeframe, relation=relation, lane=lane, zone_side=zone_side, near_pct=float(near),
                limit=limit, offset=offset, markets=tuple(dict.fromkeys(markets)),
                stock_ids=tuple(dict.fromkeys(s.strip() for s in stock_ids)))


def _read_completed_daily_observations(db: Session, *, stock_ids: list[str], basis_date: date,
        now: datetime) -> dict[str, dict[str, Any]]:
    """Compose the existing exact-session official reader; never use intraday state or carry a stale close."""
    repository = TaiwanOfficialDailyBarRepository(db, available_at=now, allow_early_regular=True)
    result = {}
    for start in range(0, len(stock_ids), 500):
        symbols = tuple(stock_ids[start:start + 500])
        daily = repository.load_market_universe(trade_date=basis_date, symbols=symbols,
            max_rows=max(128, len(symbols) * 4))
        metadata = repository.outward_state_metadata(tuple(bar.lineage.observation_id for bar in daily.bars))
        rejected = {}
        for symbol, reason in daily.rejection_reasons:
            rejected.setdefault(symbol, []).append(reason)
        for symbol in symbols:
            result[symbol] = {"research_usable": False,
                "reason_codes": rejected.get(symbol) or ["COMPLETED_DAILY_CLOSE_MISSING"]}
        for bar in daily.bars:
            lineage = bar.lineage
            reasons = []
            if (bar.finalization not in {BarFinalization.FINAL, BarFinalization.CORRECTED}
                    or bar.start_at.astimezone(TAIWAN_TZ).date() != basis_date):
                reasons.append("COMPLETED_DAILY_NOT_FINALIZED")
            if (lineage.authority != AuthorityClass.EXCHANGE or not lineage.raw_receipt_id
                    or not lineage.content_hash or not lineage.observation_id or not lineage.fetched_at
                    or lineage.fetched_at > now or bar.price_basis != "raw"):
                reasons.append("COMPLETED_DAILY_LINEAGE_UNQUALIFIED")
            price = float(bar.close_price)
            early_regular = "OFFICIAL_FINAL_PENDING" in bar.limitations
            if not isfinite(price) or price <= 0:
                reasons.append("COMPLETED_DAILY_CLOSE_INVALID")
            result[bar.instrument.symbol] = {
                "market": bar.instrument.venue, "trade_date": basis_date, "price": price,
                "event_time": bar.end_at, "received_at": lineage.fetched_at,
                "price_semantics": "official_regular_session_research_close" if early_regular else "official_finalized_daily_close", "finalization": bar.finalization.value,
                "trading_scope": "regular_session" if bar.derivation_kind == TAIWAN_DAILY_REGULAR_SCOPE else "official_daily",
                "limitations": list(bar.limitations),
                "authority": lineage.authority.value, "price_basis": bar.price_basis,
                **metadata.get(lineage.observation_id, {}),
                "has_actual_trade": False, "research_usable": not reasons, "decision_usable": not reasons and not early_regular,
                "reason_codes": reasons, "samples": [], "lineage": lineage.model_dump(mode="json"),
                "source_refs": [{"type": "resolved_market_data", "name": "taiwan_official_daily",
                    "provider": lineage.provider, "source": lineage.source,
                    "observation_id": lineage.observation_id, "raw_receipt_id": lineage.raw_receipt_id}],
            }
    return result


def build_tw_price_map_screening_snapshot(db: Session, *, parameters: dict | None = None, generated_at: datetime | None = None) -> dict[str, Any]:
    request = normalize_price_map_scan_parameters(parameters)
    now = generated_at or datetime.now(TAIWAN_TZ)
    if now.tzinfo is None:
        raise ValueError("Price Map scan requires timezone-aware generated_at")
    universe = read_price_map_universe(db, markets=request["markets"], stock_ids=request["stock_ids"])
    stocks = {stock.stock_id: stock for stock in universe}
    stock_ids = list(request["stock_ids"]) if request["stock_ids"] else list(stocks)
    ready_storage = snapshot_storage_available(db)
    snapshots = read_price_map_snapshots(db, stock_ids, request["timeframe"]) if ready_storage else {}
    revisions = read_input_revisions(db, stock_ids) if ready_storage else {}
    expected_basis = latest_completed_taiwan_session_date(now)
    completed_daily = request["lane"] == "completed_daily"
    observations = (_read_completed_daily_observations(db, stock_ids=stock_ids, basis_date=expected_basis, now=now)
        if completed_daily else read_tw_price_map_observations(db, stock_ids=stock_ids, now=now, lane=request["lane"]))
    params = get_technical_analysis_parameters()
    corporate_revision = read_price_map_external_revision()
    reasons: Counter[str] = Counter()
    counts: Counter[str] = Counter()
    matches = []
    for stock_id in stock_ids:
        stock = stocks.get(stock_id)
        if stock is None:
            reasons["UNIVERSE_MEMBER_UNAVAILABLE"] += 1
            continue
        snapshot = snapshots.get(stock_id)
        if snapshot is None:
            reasons["SNAPSHOT_NOT_COMPUTED" if ready_storage else "SNAPSHOT_MIGRATION_REQUIRED"] += 1
            continue
        counts["computed_symbols"] += 1
        if not snapshot_matches(snapshot, input_revision=revisions.get(stock_id, 0), parameter_revision=params.revision, corporate_revision=corporate_revision, basis_date=expected_basis):
            reasons["SNAPSHOT_REVISION_STALE"] += 1
            continue
        if snapshot.status not in {"ready", "empty"}:
            reasons[f"SNAPSHOT_{snapshot.status.upper()}"] += 1
            continue
        published_at = snapshot.published_at
        if published_at is not None:
            published_at = published_at.replace(tzinfo=timezone.utc) if published_at.tzinfo is None else published_at.astimezone(timezone.utc)
        if published_at is None or published_at > now:
            reasons["SNAPSHOT_PUBLICATION_NOT_AVAILABLE"] += 1
            continue
        try:
            payload = json.loads(snapshot.payload_json or "")
        except (ValueError, TypeError):
            reasons["SNAPSHOT_INVALID"] += 1
            continue
        if not isinstance(payload, dict) or payload.get("structure_input_usable", payload.get("decision_usable")) is not True:
            reasons["SNAPSHOT_NOT_DECISION_USABLE"] += 1
            continue
        corporate = payload.get("corporate_action") or {}
        if corporate.get("affected_dates") and corporate.get("adjustment_applied") is not True:
            reasons["UNADJUSTED_CORPORATE_ACTION_WINDOW"] += 1
            continue
        counts["current_structure_symbols"] += 1
        observation = observations.get(stock_id)
        if not observation or not observation["research_usable"] or observation["market"] != stock.market:
            for reason in (observation or {}).get("reason_codes") or ["OBSERVATION_MISSING"]:
                reasons[reason] += 1
            continue
        counts["eligible_symbols"] += 1
        price = observation["price"]
        candidates = []
        for zone in payload.get("zones", []):
            if request["zone_side"] != "any" and zone.get("side") != request["zone_side"]:
                continue
            if zone.get("scanner_eligible") is not True or zone.get("geometry_status") != "ready":
                continue
            lower, upper = zone.get("lower_bound"), zone.get("upper_bound")
            if not isinstance(lower, (int, float)) or not isinstance(upper, (int, float)) or not 0 < lower < upper or not isfinite(lower + upper):
                continue
            distance = max(lower - price, price - upper, 0) / price * 100
            relation = ("within_zone" if completed_daily else "touching") if lower <= price <= upper else "above_zone" if price > upper else "below_zone"
            wanted = request["relation"]
            reaction = None
            matched = (distance <= request["near_pct"]) if wanted == "near_zone" else relation == wanted
            if wanted in REACTION_RELATIONS:
                published = snapshot.published_at
                if published is None:
                    continue
                if published.tzinfo is None:
                    published = published.replace(tzinfo=timezone.utc)
                reaction = price_map_reaction(observation["samples"], lower=lower, upper=upper,
                    published_at=published, now=now, basis_revision=str(payload.get("basis_revision") or ""))
                matched = reaction["status"] == "confirmed" and reaction["event"] == wanted
            if matched:
                candidates.append(dict(zone=zone, distance_pct=round(distance, 6), relation=relation, reaction=reaction))
        if not candidates:
            counts["no_match_symbols"] += 1
            continue
        selected = min(candidates, key=lambda item: (item["distance_pct"], item["zone"]["zone_id"]))
        matches.append({
            "stock_id": stock_id, "stock_name": stock.stock_name, "market": stock.market,
            "structure_timeframe": request["timeframe"], "basis_revision": payload["basis_revision"],
            "basis_date": snapshot.basis_date, "snapshot_published_at": published_at,
            "parameter_revision": snapshot.parameter_revision, "current_price": price,
            "observation": {key: value for key, value in observation.items() if key != "samples"},
            "decision_usable": bool(observation["decision_usable"]), "execution_grade_usable": False,
            **selected,
        })
    matches.sort(key=lambda row: (row["distance_pct"], row["stock_id"], row["zone"]["zone_id"]))
    total = len(stock_ids)
    complete = counts["eligible_symbols"] == total and ready_storage
    status = "ready" if complete else "partial" if counts["eligible_symbols"] else "missing"
    selected_rows = matches[request["offset"]:request["offset"] + request["limit"]]
    early_research_present = any("OFFICIAL_FINAL_PENDING" in (item.get("limitations") or [])
        for item in observations.values())
    for rank, row in enumerate(selected_rows, request["offset"] + 1):
        row["rank"] = rank
    warnings = [] if complete else ["Requested universe is only partially covered; pagination does not change coverage."]
    if request["lane"] == "indicative":
        warnings.append("Indicative matching prices are not actual trades and are not decision usable.")
    if completed_daily:
        warnings.append("Finalized daily close position only; no intraday touch, reaction or retest sequence is inferred.")
    if early_research_present:
        warnings.append("Regular-session research evidence; official final reconciliation is pending.")
    return {
        "kind": "tw_price_map_screening", "version": SCANNER_VERSION, "status": status,
        "freshness_status": "current" if complete else status, "computed_at": now, "as_of": now,
        "structure_timeframe": request["timeframe"], "relation": request["relation"], "zone_side": request["zone_side"], "lane": request["lane"],
        "expected_basis_date": expected_basis, "rows": selected_rows,
        "coverage": {"requested_symbols": total, "computed_symbols": counts["computed_symbols"],
            "current_structure_symbols": counts["current_structure_symbols"], "eligible_symbols": counts["eligible_symbols"],
            "matched_symbols": len(matches), "no_match_symbols": counts["no_match_symbols"],
            "complete": complete, "excluded_reason_counts": dict(sorted(reasons.items()))},
        "pagination": {"offset": request["offset"], "limit": request["limit"], "total": len(matches), "returned": len(selected_rows)},
        "empty_result_is_valid": complete and not matches,
        "facts_usable": complete or bool(matches), "facts_usable_for_ranking": complete or bool(matches),
        "decision_usable": complete and request["lane"] in {"actual", "completed_daily"}
            and not early_research_present and all(row["decision_usable"] for row in matches),
        "release_status": "regular_research" if early_research_present else "released",
        "intraday_research_usable": bool(matches) and request["lane"] == "actual", "execution_grade_usable": False,
        "cache_policy": "cache_only_no_refresh_no_build", "missing": list(sorted(reasons)), "warnings": warnings,
        "source_refs": [{"type": "derived", "name": "taiwan_price_map_snapshot"},
            {"type": "resolved_market_data", "name": "taiwan_official_daily" if completed_daily else "taiwan_intraday_stock_state"}],
    }
