"""Report-slot selection of owner-qualified evidence; no market truth inference.

Date/time checks bind evidence to the requested report, not to a new freshness
policy. All session, authority, finalization and eligibility flags come from the
canonical reader. Rejected evidence remains inspectable in the audit payload.
"""
from __future__ import annotations

from datetime import date, datetime

from app.dispatch.market_report_presentation import _evidence, _map, _rows


DAILY_FIELDS = ("distribution", "top_industries", "weak_industries", "value_leaders",
                "top_gainers", "top_losers", "stock_sector_context", "technology_pulse",
                "sample_coverage", "radar")


def _day(value) -> str | None:
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except (ValueError, TypeError):
        return None


def _in_report(block: dict, now: datetime, *, day: str) -> bool:
    identity = block.get("trade_date") or block.get("observed_trade_date")
    stamp = block.get("as_of") or block.get("event_time") or block.get("snapshot_as_of")
    if _day(identity or stamp) != day:
        return False
    # Do not let a later same-day cached event become evidence at 08:55/10:00.
    if stamp and len(str(stamp)) > 10:
        try:
            event = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
            return (event.tzinfo is not None and event <= now
                    and event.astimezone(now.tzinfo).date().isoformat() == day)
        except ValueError:
            return False
    return not stamp or _day(stamp) == day


def _available_by(value, now: datetime) -> bool:
    """Availability bound only; foreign session/freshness stays with its owner."""
    try:
        event = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return event.tzinfo is not None and event <= now
    except (ValueError, TypeError):
        return False


def select_phase_preview(preview: dict, *, phase: str, now: datetime, daily_cap: date) -> dict:
    if phase not in {"preopen", "intraday", "postclose"}:
        raise ValueError("Unsupported Discord market report phase.")
    result = _evidence(preview)
    data = _map(result.get("metadata"))
    original = _evidence(data)
    day = now.date().isoformat()
    sections = {}
    absent = "unavailable" if phase == "preopen" else "pending"

    def selected(name: str, payload: dict, admitted: bool, reason: str) -> dict:
        sections[name] = {"status": "selected" if admitted else absent, "reason": reason}
        return payload if admitted else {"status": absent, "selection_reason": reason}

    raw_indices = _map(_map(data.get("market")).get("indices"))
    index_rows = []
    for row in _rows(raw_indices.get("items")):
        if phase == "preopen":
            reference = _map(row.get("official_close"))
            if (_in_report(reference, now, day=daily_cap.isoformat())
                    and daily_cap < now.date() and reference.get("value") is not None):
                index_rows.append({**reference, "index_id": row.get("index_id"),
                                   "quote_semantics": "historical_official_close_reference"})
        elif phase == "intraday":
            if (_in_report(row, now, day=day) and row.get("current_for_requested_session") is True
                    and row.get("quote_semantics") == "intraday_last_trade"
                    and _map(row.get("freshness")).get("status") in {"current", "delayed"}):
                index_rows.append(row)
        elif (_in_report(row, now, day=day) and row.get("official_close_confirmed") is True
              and row.get("official_source") is True and row.get("provisional") is False
              and row.get("finalization") == "final"):
            index_rows.append(row)
    data["market"] = {"indices": selected("indices", {**raw_indices, "items": index_rows},
                                         bool(index_rows), "phase-qualified canonical index evidence")}
    # Preserve each missing index explicitly; one venue cannot qualify the other.
    data["market"]["indices"]["items"] = index_rows
    for identity in ("TAIEX", "TPEX"):
        sections[f"index.{identity}"] = {"status": "selected" if any(
            row.get("index_id") == identity for row in index_rows) else absent}

    breadth = _map(data.get("breadth"))
    by_market = _map(data.get("breadth_by_market"))
    if phase == "preopen":
        auction = _map(breadth.get("auction_breadth"))
        admitted = (_in_report(auction, now, day=day)
                    and auction.get("price_semantics") == "auction_indicative"
                    and auction.get("is_provisional") is True and auction.get("decision_usable") is False
                    and auction.get("status") in {"provisional", "partial"})
        data["breadth"] = selected("breadth", auction, admitted, "canonical auction only; not an actual trade")
        data["breadth_by_market"] = _map(auction.get("markets")) if admitted else {}
    elif phase == "intraday":
        admitted = (_in_report(breadth, now, day=day)
                    and breadth.get("session_semantics") == "current_session"
                    and breadth.get("price_semantics") in {"actual_trade_only", "current_last_trade_vs_reference"}
                    and breadth.get("status") in {"ready", "partial"})
        data["breadth"] = selected("breadth", breadth, admitted, "same-day canonical actual breadth required")
        data["breadth_by_market"] = {key: row for key, row in by_market.items()
                                     if isinstance(row, dict) and _in_report(row, now, day=day)} if admitted else {}
    else:
        completed = {key: row for key, row in by_market.items() if isinstance(row, dict)
                     and _in_report(row, now, day=day) and row.get("is_provisional") is False
                     and (row.get("official") is True or
                          row.get("finalization") == "session_final"
                          and row.get("session_semantics") == "latest_completed_session")}
        # Session-final MIS is a valid recap, not proof of an official release.
        # Keep each component's reconciliation; do not aggregate missing venues.
        admitted = bool(completed) and len(completed) == len(by_market) and _in_report(breadth, now, day=day)
        data["breadth"] = selected("breadth", breadth, admitted, "completed-session facts; official release remains independent")
        data["breadth_by_market"] = completed

    volume = _map(data.get("volume_state"))
    volume_ok = (phase in {"intraday", "postclose"} and _in_report(volume, now, day=day)
                 and volume.get("status") in {"ready", "partial"})
    # A same-day recap may include estimates with their original authority;
    # it must not be called official final turnover.
    data["volume_state"] = selected("volume", volume, volume_ok,
                                   "actual current-session volume" if phase == "intraday" else
                                   "auction has no actual turnover" if phase == "preopen" else
                                   "same-day recap; authority and release individually qualified")

    screening = _map(data.get("screening"))
    candidates = _map(screening.get("intraday"))
    groups = _map(screening.get("hot_groups"))
    lane = "indicative" if phase == "preopen" else "actual"

    def current_rank(block: dict) -> bool:
        return (phase != "postclose" and _in_report(block, now, day=day)
                and block.get("lane") == lane and block.get("facts_usable_for_ranking") is True
                and block.get("status") in {"ready", "partial"})

    candidate_rows = [row for row in _rows(candidates.get("rows"))
                      if _in_report(row, now, day=day) and row.get("lane") == lane
                      and row.get("facts_usable_for_ranking") is True][:8]
    candidates = selected("candidates", {**candidates, "rows": candidate_rows},
                          current_rank(candidates) and bool(candidate_rows), "canonical lane-qualified ranking")
    groups = selected("groups", groups, current_rank(groups) and bool(_rows(groups.get("groups"))), "canonical lane-qualified groups")
    # Owner supplies sorted rows. Do not rerank or replace missing current rows
    # with daily leaders, chips or technical signals.
    candidates = {**candidates, "rows": _rows(candidates.get("rows"))}
    groups = {**groups, "groups": _rows(groups.get("groups"))[:8]}
    data["screening"] = {"intraday": candidates, "hot_groups": groups}

    sample_count = _map(data.get("sample_coverage")).get("sample_count")
    has_sample = (any(_rows(data.get(key)) for key in
                      ("value_leaders", "top_gainers", "top_losers", "top_industries", "weak_industries"))
                  and (type(sample_count) is not int or sample_count > 0))
    history_ok = (has_sample and phase == "preopen" and _day(data.get("latest_trade_date")) == daily_cap.isoformat()
                  and daily_cap < now.date())
    recap_ok = (has_sample and phase == "postclose" and daily_cap == now.date()
                and _day(data.get("latest_trade_date")) == day)
    historical = {key: data.get(key) for key in DAILY_FIELDS} if history_ok else {}
    for key in DAILY_FIELDS:
        if not (history_ok or recap_ok):
            data.pop(key, None)
    # Retain date-qualified chips for daily research only. An older institutional
    # release must not seed a same-day recap or any current intraday candidates.
    chips = {}
    if history_ok or recap_ok:
        for key, block in _map(data.get("market_chips")).items():
            if not isinstance(block, dict):
                continue
            if _in_report(block, now, day=daily_cap.isoformat()):
                chips[key] = block
            elif key == "official_market_aggregate":
                rows = [row for row in _rows(block.get("rows"))
                        if _in_report(row, now, day=daily_cap.isoformat())]
                if rows:
                    chips[key] = {**block, "rows": rows}
    data["market_chips"] = chips
    cross = _map(data.get("cross_market"))
    if "markets" in cross:
        data["cross_market"] = {**cross, "markets": {
            market: {**block, "assets": [row for row in _rows(block.get("assets"))
                                        if _available_by(row.get("as_of"), now)]}
            for market, block in _map(cross.get("markets")).items() if isinstance(block, dict)}}
    data["index_intraday"] = selected("index_intraday", _map(data.get("index_intraday")),
        phase == "intraday" and _map(data.get("index_intraday")).get("expected_trade_date") == day,
        "intraday series retains its own coverage and freshness")
    sections["daily_rankings"] = {"status": "historical_reference" if history_ok else "daily_sample" if recap_ok else absent,
        "reason": "daily sample is not official-final ranking evidence"}
    data["stance"] = {"preopen": "歷史基準與試撮分開；試撮非正式成交",
                      "intraday": "本交易日 actual evidence；缺項 pending",
                      "postclose": "官方確認指數＋本交易日樣本回顧；各項發布狀態獨立"}[phase]
    data["phase_selection"] = {
        "phase": phase, "report_date": day, "daily_sample_cap": daily_cap.isoformat(),
        "sections": sections, "candidates": candidates, "groups": groups,
        "historical_daily": historical,
        "preopen_review": {"status": "unavailable", "reason": "immutable preopen snapshot unavailable"},
        "excluded_evidence": original,
    }
    result["metadata"] = data
    return result
