from __future__ import annotations

from typing import Any

from app.ai import ask_response_support, query_plan as query_plan_module, scope_resolution
from app.ai.evidence_passport import build_evidence_passport
from app.ai.question_capabilities import required_capabilities_for_question
from app.ai.schemas import AiAskRequest


_BASE_RESULT_KEYS = (
    "kind",
    "generated_at",
    "as_of",
    "scope",
    "strategy_profile",
    "response_preferences",
    "missing",
    "warnings",
    "source_refs",
    "evidence_passport",
)

_COMPACT_ANALYSIS_KEYS = (
    "kind",
    "as_of",
    "requested_horizon",
    "selected_horizon",
    "horizon_label",
    "selected_timeframe",
    "selected_score",
    "score_display",
    "selected_title",
    "selected_summary",
    "selected_confidence",
    "display",
    "stance",
    "confidence",
    "group_id",
    "group_name",
    "answer_outline",
    "slot_status_counts",
    "ready_slots",
    "problem_slots",
    "key_numbers",
    "scores",
    "source",
    "question_intent",
    "question_understanding",
    "response_preferences",
    "position_context",
    "position_math",
    "position_decision",
    "price_level_validation",
    "reasoning_steps",
    "human_answer",
    "decision_contract",
)

_DATA_ONLY_ANALYSIS_KEYS = (
    "kind",
    "as_of",
    "slot_status_counts",
    "ready_slots",
    "problem_slots",
    "key_numbers",
    "scores",
    "source",
    "question_intent",
    "question_understanding",
    "price_level_validation",
)


def _base_result(result: dict[str, Any]) -> dict[str, Any]:
    return {key: result[key] for key in _BASE_RESULT_KEYS if key in result}


def _public_analysis_for_mode(
    analysis: dict[str, Any],
    *,
    effective_mode: str,
) -> dict[str, Any]:
    if effective_mode not in {"brief", "data_only"}:
        return analysis
    allowed_keys = (
        _DATA_ONLY_ANALYSIS_KEYS
        if effective_mode == "data_only"
        else _COMPACT_ANALYSIS_KEYS
    )
    output = {
        key: analysis[key]
        for key in allowed_keys
        if key in analysis
    }
    if analysis.get("compact_evidence"):
        output["compact_evidence_ref"] = "result.data.compact"
    output["analysis_view"] = {
        "detail": "compact",
        "full_mode": "full",
        "omitted_fields": [
            "compact_evidence",
            "components",
            "decision_evidence",
            "technical_levels",
            "source_health",
            "source_refs",
        ],
    }
    return output


def _brief_summary(summary: dict[str, Any]) -> dict[str, Any]:
    if not summary:
        return {}
    duplicated_detail_keys = {
        "decision_evidence",
        "human_answer",
        "breadth",
        "sample_breadth",
        "distribution",
        "top_gainers",
        "top_losers",
        "value_leaders",
        "top_industries",
        "weak_industries",
        "sample_top_gainers",
        "sample_top_losers",
        "sample_value_leaders",
        "sample_top_industries",
        "sample_weak_industries",
        "index_intraday",
        "slots",
        "compact",
        "data",
    }
    return {
        key: value
        for key, value in summary.items()
        if key not in duplicated_detail_keys
    }


def _trim_brief_intraday_points(
    value: Any,
    *,
    key: str | None = None,
) -> Any:
    if isinstance(value, dict):
        return {
            str(child_key): _trim_brief_intraday_points(
                child_value,
                key=str(child_key),
            )
            for child_key, child_value in value.items()
        }
    if isinstance(value, list):
        selected = value[-1:] if key in {"points", "bars"} else value
        return [
            _trim_brief_intraday_points(item)
            for item in selected
        ]
    return value


def _compact_result_data(
    result: dict[str, Any],
    *,
    brief: bool = False,
) -> dict[str, Any] | None:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    compact = data.get("compact") if isinstance(data.get("compact"), dict) else {}
    if not compact:
        return None
    if brief:
        compact = _trim_brief_intraday_points(compact)

    output: dict[str, Any] = {"compact": compact}
    payload_level = compact.get("payload_level")
    if payload_level:
        output["payload_level"] = payload_level
    compact_status = compact.get("status")
    if compact_status:
        output["status"] = compact_status
    quote = compact.get("quote") if isinstance(compact.get("quote"), dict) else {}
    if quote:
        output["quote"] = quote
    intraday_bars = compact.get("intraday_bars") if isinstance(compact.get("intraday_bars"), dict) else {}
    if intraday_bars:
        output["intraday_bars"] = intraday_bars
    technical = compact.get("technical") if isinstance(compact.get("technical"), dict) else {}
    if technical:
        output["technical"] = technical
        analysis = technical.get("analysis") if isinstance(technical.get("analysis"), dict) else {}
        if analysis:
            output["analysis"] = analysis
    freshness_by_domain = (
        compact.get("freshness_by_domain")
        if isinstance(compact.get("freshness_by_domain"), dict)
        else {}
    )
    if freshness_by_domain:
        output["freshness_by_domain"] = freshness_by_domain
    slots = compact.get("slots") if isinstance(compact.get("slots"), dict) else {}
    if slots:
        output["slots"] = slots
    for key in (
        "breadth",
        "sample_breadth",
        "distribution",
        "top_gainers",
        "top_losers",
        "value_leaders",
        "top_industries",
        "weak_industries",
        "sample_top_gainers",
        "sample_top_losers",
        "sample_value_leaders",
        "sample_top_industries",
        "sample_weak_industries",
        "index_intraday",
        "cross_market",
        "market_chips",
        "ranking",
        "radar",
        "evidence_coverage",
        "quote_semantics",
        "daily_close",
        "daily_chart",
        "intraday_chart",
        "institutional_position",
        "options_sentiment",
        "market_chip_trend",
        "derivatives",
        "tables",
        "summary",
        "capabilities",
        "provider_contract",
        "refresh_summary",
        "health_dimensions",
        "as_of_by_domain",
    ):
        value = compact.get(key)
        if value not in (None, {}, []):
            output[key] = value
    return output


def _stock_from_compact(compact: dict[str, Any]) -> dict[str, Any]:
    target = compact.get("target") if isinstance(compact.get("target"), dict) else {}
    stock: dict[str, Any] = {}
    if target.get("type"):
        stock["type"] = target.get("type")
    if target.get("id"):
        stock["id"] = target.get("id")
    if target.get("label"):
        stock["name"] = target.get("label")
    if target.get("market"):
        stock["market"] = target.get("market")
    return stock


def _select_intraday_series(series: dict[str, Any]) -> dict[str, Any]:
    for interval in ("1m", "5m"):
        value = series.get(interval)
        if isinstance(value, dict) and (value.get("latest") or value.get("returned_point_count")):
            return value

    for value in series.values():
        if isinstance(value, dict) and (value.get("latest") or value.get("returned_point_count")):
            return value

    for interval in ("1m", "5m"):
        value = series.get(interval)
        if isinstance(value, dict):
            return value

    for value in series.values():
        if isinstance(value, dict):
            return value

    return {}


def _intraday_summary_from_compact(
    intraday_bars: dict[str, Any],
    *,
    quote: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not intraday_bars:
        return {}

    series = intraday_bars.get("series") if isinstance(intraday_bars.get("series"), dict) else {}
    selected = _select_intraday_series(series)
    points = selected.get("points") if isinstance(selected.get("points"), list) else []
    latest = selected.get("latest") if isinstance(selected.get("latest"), dict) else None
    enabled = bool(intraday_bars.get("enabled"))
    returned_count = selected.get("returned_point_count")
    if not isinstance(returned_count, int):
        returned_count = len(points)

    if not enabled:
        status = "not_requested"
    elif latest or returned_count > 0:
        status = "ok"
    else:
        status = "missing"

    latest_time = latest.get("time") if isinstance(latest, dict) else None
    source = selected.get("source") or selected.get("provider")
    if not source:
        source = "not_requested" if not enabled else "not_available"

    return {
        "status": status,
        "source": source,
        "interval": selected.get("interval"),
        "point_count": selected.get("point_count") or returned_count,
        "returned_point_count": returned_count,
        "latest_point": latest,
        "last_update": selected.get("to_time") or latest_time,
        "freshness_status": selected.get("freshness_status"),
        "age_seconds": selected.get("age_seconds"),
        "market_status": selected.get("market_status"),
        "is_realtime": bool((quote or {}).get("is_live") or (quote or {}).get("is_realtime")),
        "bars": points,
        "warnings": intraday_bars.get("warnings") or [],
    }


def _intraday_chart_summary(intraday_chart: dict[str, Any]) -> dict[str, Any]:
    if not intraday_chart:
        return {}
    points = intraday_chart.get("points") if isinstance(intraday_chart.get("points"), list) else []
    latest = points[-1] if points and isinstance(points[-1], dict) else None
    point_count = intraday_chart.get("point_count")
    if not isinstance(point_count, int):
        point_count = len(points)
    return {
        "status": "ok" if latest or point_count > 0 else "missing",
        "source": intraday_chart.get("source") or "local_intraday_chart",
        "interval": intraday_chart.get("interval") or "1m",
        "point_count": point_count,
        "returned_point_count": len(points),
        "latest_point": latest,
        "last_update": intraday_chart.get("to_date") or (latest or {}).get("time"),
        "bars": points,
        "warnings": intraday_chart.get("warnings") or [],
    }


def _first_present(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value is not None:
            return value
    return None


def _market_live_summary(
    *,
    compact: dict[str, Any],
    quote: dict[str, Any],
    intraday: dict[str, Any],
) -> dict[str, Any]:
    target = compact.get("target") if isinstance(compact.get("target"), dict) else {}
    freshness = quote.get("freshness") if isinstance(quote.get("freshness"), dict) else {}
    market_status_payload = (
        freshness.get("market_status")
        if isinstance(freshness.get("market_status"), dict)
        else {}
    )
    latest_point = intraday.get("latest_point") if isinstance(intraday.get("latest_point"), dict) else {}
    quote_price = _first_present(
        quote,
        "price",
        "last_price",
        "latest_price",
        "close_price",
    )
    intraday_latest_price = _first_present(
        latest_point,
        "price",
        "close",
        "close_price",
        "last_price",
    )
    quote_time = _first_present(quote, "quote_time", "time", "as_of", "fetched_at")
    intraday_time = intraday.get("last_update") or latest_point.get("time")
    quote_is_live = bool(
        quote.get("is_live")
        if quote.get("is_live") is not None
        else freshness.get("is_live")
        if freshness.get("is_live") is not None
        else quote.get("is_realtime")
    )
    freshness_status = str(freshness.get("status") or "")
    market_status = quote.get("market_status")
    if not isinstance(market_status, str):
        phase = str(
            quote.get("current_session_phase")
            or quote.get("session_phase")
            or market_status_payload.get("current_session")
            or ""
        )
        market_status = {
            "regular": "open",
            "regular_live": "open",
            "preopen": "preopen",
            "preopen_auction": "preopen",
            "lunch_break": "lunch_break",
            "closing_auction": "closing_auction",
            "post_close": "latest_session_close",
            "post_close_snapshot": "latest_session_close",
            "market_closed": "closed_holiday"
            if market_status_payload.get("holiday_name")
            else "closed",
        }.get(phase, "open" if market_status_payload.get("is_open") else "closed")
    is_latest_session_quote = quote.get("is_latest_session_quote")
    if not isinstance(is_latest_session_quote, bool):
        is_latest_session_quote = freshness_status in {
            "live",
            "closed",
            "latest_completed_session",
        }
    intraday_available = intraday.get("status") == "ok"
    has_quote = quote_price is not None or bool(quote)
    quote_is_stale = bool(freshness.get("is_stale")) or freshness_status in {
        "cached",
        "stale",
        "source_unavailable",
        "unavailable",
    }
    latest_point_freshness = (
        latest_point.get("freshness")
        if isinstance(latest_point.get("freshness"), dict)
        else {}
    )
    intraday_freshness = str(
        intraday.get("freshness_status")
        or latest_point_freshness.get("status")
        or ""
    )
    intraday_is_usable = bool(
        intraday_available
        and intraday_latest_price is not None
        and intraday_freshness not in {"stale", "missing", "unavailable"}
    )
    if intraday_is_usable:
        display_price = intraday_latest_price
        display_price_source = "intraday"
        display_price_time = intraday_time
        display_price_freshness = intraday_freshness or "unknown"
    elif quote_price is not None:
        display_price = quote_price
        display_price_source = "quote"
        display_price_time = quote_time
        display_price_freshness = freshness_status or ("live" if quote_is_live else "cached")
    else:
        display_price = None
        display_price_source = None
        display_price_time = None
        display_price_freshness = "missing"
    quote_depth_available = bool(quote.get("depth_available")) and not quote_is_stale

    return {
        "version": "market_live_summary.v1",
        "status": "ready" if has_quote and intraday_available else "partial" if has_quote or intraday_available else "missing",
        "target_type": target.get("type"),
        "symbol": target.get("id") or target.get("symbol"),
        "quote_price": quote_price,
        "quote_time": quote_time,
        "quote_source": quote.get("source"),
        "quote_provider": quote.get("provider"),
        "source_is_intraday": bool(quote.get("source_is_intraday") or intraday_available),
        "is_realtime": display_price_freshness in {"live", "current"},
        "is_live": display_price_freshness in {"live", "current"},
        "is_latest_session_quote": is_latest_session_quote,
        "market_status": market_status,
        "current_session_phase": quote.get("current_session_phase") or market_status_payload.get("current_session"),
        "last_quote_session": quote.get("last_quote_session") or quote.get("session") or market_status_payload.get("last_session"),
        "intraday_available": intraday_available,
        "intraday_interval": intraday.get("interval"),
        "intraday_latest": intraday.get("last_update") or latest_point.get("time"),
        "intraday_latest_price": intraday_latest_price,
        "intraday_point_count": intraday.get("point_count"),
        "display_price": display_price,
        "display_price_source": display_price_source,
        "display_price_time": display_price_time,
        "display_price_freshness": display_price_freshness,
        "quote_is_live": quote_is_live,
        "quote_depth_available": quote_depth_available,
        "quote_depth_status": freshness_status or "missing",
    }


def _apply_stock_compact_fields(output: dict[str, Any], compact: dict[str, Any]) -> None:
    if not compact:
        return

    target = _stock_from_compact(compact)
    if target:
        if target.get("type") in {"tw_stock", "stock"}:
            output["stock"] = target
        else:
            output["target"] = target

    quote = compact.get("quote") if isinstance(compact.get("quote"), dict) else {}
    if quote:
        output["quote"] = quote

    intraday_bars = compact.get("intraday_bars") if isinstance(compact.get("intraday_bars"), dict) else {}
    intraday = _intraday_summary_from_compact(intraday_bars, quote=quote)
    if not intraday:
        intraday_chart = compact.get("intraday_chart") if isinstance(compact.get("intraday_chart"), dict) else {}
        intraday = _intraday_chart_summary(intraday_chart)
    if intraday:
        output["intraday"] = intraday

    live_summary = _market_live_summary(compact=compact, quote=quote, intraday=intraday)
    output["live_summary"] = live_summary
    data = output.get("data") if isinstance(output.get("data"), dict) else None
    if data is not None:
        data["live_summary"] = live_summary

    technical = compact.get("technical") if isinstance(compact.get("technical"), dict) else {}
    analysis = technical.get("analysis") if isinstance(technical.get("analysis"), dict) else {}
    if analysis:
        output["analysis"] = analysis

    freshness = (
        compact.get("freshness_by_domain")
        if isinstance(compact.get("freshness_by_domain"), dict)
        else {}
    )
    if freshness:
        output["freshness"] = freshness

    slots = compact.get("slots") if isinstance(compact.get("slots"), dict) else {}
    if slots:
        output["slots"] = slots


def _apply_market_brief_fields(output: dict[str, Any], result: dict[str, Any]) -> None:
    if result.get("kind") != "market_brief":
        return

    data = output.get("data") if isinstance(output.get("data"), dict) else {}
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    data_summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    summary_source = summary or data_summary

    output["latest_trade_date"] = result.get("as_of") or summary_source.get("as_of")
    for key in (
        "breadth",
        "sample_breadth",
        "distribution",
        "top_gainers",
        "top_losers",
        "value_leaders",
        "top_industries",
        "weak_industries",
        "sample_top_gainers",
        "sample_top_losers",
        "sample_value_leaders",
        "sample_top_industries",
        "sample_weak_industries",
        "index_intraday",
        "slots",
    ):
        if key in data:
            output[key] = data[key]
        elif key in summary_source:
            output[key] = summary_source[key]


def _project_data_only_result(result: dict[str, Any]) -> dict[str, Any]:
    compact_data = _compact_result_data(result)
    if not compact_data:
        output = _base_result(result)
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        slots = data.get("slots") if isinstance(data.get("slots"), dict) else {}
        output["data"] = {
            "compact": {
                "kind": "compact_projection_failure",
                "version": "market_compact_evidence.v1",
                "status": "failed",
                "target": result.get("scope") or {},
                "slots": slots,
                "missing": ["compact_projection"],
                "warnings": [
                    "This target did not provide a bounded compact projection; use mode=full for the legacy evidence pack."
                ],
            },
            "slots": slots,
        }
        warnings = list(output.get("warnings") or [])
        warnings.append(
            "Compact projection unavailable; returned an explicit bounded failure instead of the full legacy payload."
        )
        output["warnings"] = list(dict.fromkeys(warnings))
        output["result_view"] = {
            "mode": "data_only",
            "detail": "compact_projection_failure",
            "full_mode": "full",
            "omitted_fields": ["legacy_full_data"],
        }
        return output

    output = _base_result(result)
    summary = _brief_summary(result.get("summary") if isinstance(result.get("summary"), dict) else {})
    if summary:
        output["summary"] = summary
    output["data"] = compact_data
    compact = compact_data.get("compact") if isinstance(compact_data.get("compact"), dict) else {}
    _apply_stock_compact_fields(output, compact)
    _apply_market_brief_fields(output, result)
    output["result_view"] = {
        "mode": "data_only",
        "detail": "compact_core",
        "full_mode": "full",
        "omitted_fields": [
            "chart",
            "technical_reports",
            "revenue_history",
            "financial_history",
            "broker_branch",
            "prompt",
        ],
    }
    return output


def _project_brief_result(
    result: dict[str, Any],
    *,
    consumer_human_answer: dict[str, Any],
) -> dict[str, Any]:
    output = _base_result(result)
    summary = _brief_summary(result.get("summary") if isinstance(result.get("summary"), dict) else {})
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    compact_data = _compact_result_data(result, brief=True)

    if summary:
        output["summary"] = summary
    if consumer_human_answer:
        output["human_answer"] = consumer_human_answer

    if compact_data:
        output["data"] = compact_data
        compact = compact_data.get("compact") if isinstance(compact_data.get("compact"), dict) else {}
        _apply_stock_compact_fields(output, compact)
        _apply_market_brief_fields(output, result)
    elif result.get("kind") in {"market_brief", "watchlist_brief"}:
        output["data"] = data
        _apply_market_brief_fields(output, result)
    elif summary:
        output["data"] = {"summary": summary}

    output["result_view"] = {
        "mode": "brief",
        "detail": "human_summary_plus_key_numbers",
        "full_mode": "full",
        "omitted_fields": [
            "chart",
            "technical_reports",
            "revenue_history",
            "financial_history",
            "broker_branch",
            "summary.decision_evidence",
            "prompt",
        ],
    }
    return output


def _public_result_for_mode(
    result: dict[str, Any],
    *,
    effective_mode: str,
    consumer_human_answer: dict[str, Any],
) -> dict[str, Any]:
    if effective_mode == "brief":
        return _project_brief_result(
            result,
            consumer_human_answer=consumer_human_answer,
        )
    if effective_mode == "data_only":
        return _project_data_only_result(result)
    return result


def _domain_passport(
    *,
    compact: dict[str, Any],
    query_plan: dict[str, Any],
) -> dict[str, Any]:
    raw_domains = (
        compact.get("freshness_by_domain")
        if isinstance(compact.get("freshness_by_domain"), dict)
        else {}
    )
    domains: dict[str, dict[str, Any]] = {}
    for domain, raw_status in raw_domains.items():
        status_value = (
            raw_status.get("status")
            if isinstance(raw_status, dict)
            else raw_status
        )
        status = str(status_value or "unknown").lower()
        trust_level = (
            "high"
            if status in {"ready", "current", "live", "latest_completed_session"}
            else "medium"
            if status in {"partial", "delayed", "cached", "waiting", "not_requested", "not_applicable"}
            else "low"
            if status in {"stale", "missing", "unavailable", "blocked"}
            else "unknown"
        )
        domains[str(domain)] = {
            "status": status,
            "trust_level": trust_level,
            "usable": trust_level in {"high", "medium"},
        }

    requested_domains = [
        str(value)
        for value in query_plan.get("requested_domains") or []
        if str(value)
    ]
    required_domains = requested_domains or list(domains)
    blocked_domains = [
        domain
        for domain in required_domains
        if domain in domains and not domains[domain]["usable"]
    ]
    missing_domains = [domain for domain in required_domains if domain not in domains]
    decision_status = (
        "blocked"
        if required_domains and len(blocked_domains) + len(missing_domains) == len(required_domains)
        else "partial"
        if blocked_domains or missing_domains
        else "ready"
    )
    explicit_trust = {
        f"{domain}_trust": domains.get(
            domain,
            {"status": "not_requested", "trust_level": "medium", "usable": True},
        )
        for domain in (
            "quote",
            "intraday",
            "technical",
            "chips",
            "fundamentals",
            "cross_market",
        )
    }
    return {
        "domains": domains,
        **explicit_trust,
        "decision_readiness": {
            "status": decision_status,
            "required_domains": required_domains,
            "blocked_domains": blocked_domains,
            "missing_domains": missing_domains,
        },
    }


def finalize_ask_response(
    *,
    payload: AiAskRequest,
    resolution: scope_resolution.ScopeResolution,
    requested_mode: str,
    effective_mode: str,
    action: str,
    result: dict[str, Any],
    response_target: dict[str, Any],
    assembled: Any,
    policy: dict[str, Any],
    tool_plan: dict[str, Any],
    tool_runs: list[dict[str, Any]],
    freshness_result: dict[str, Any],
    progress: Any,
    query_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    query_plan = query_plan or {
        "payload_level": "compact",
        "diagnostics_level": "none",
    }
    planned_required_capabilities = query_plan.get("required_capabilities") or []
    evidence_passport = build_evidence_passport(
        kind="ai_ask",
        as_of=ask_response_support._result_as_of(result, assembled.analysis_digest),
        source_refs=assembled.result_source_refs,
        missing=assembled.combined_missing,
        warnings=assembled.combined_warnings,
        freshness=freshness_result,
        tool_runs=tool_runs,
        analysis=assembled.analysis_digest,
        required_capabilities=(
            tuple(str(value) for value in planned_required_capabilities)
            if planned_required_capabilities
            else required_capabilities_for_question(
                payload.question,
                response_target,
            )
        ),
    )
    result_data_for_passport = result.get("data") if isinstance(result.get("data"), dict) else {}
    compact_for_passport = (
        result_data_for_passport.get("compact")
        if isinstance(result_data_for_passport.get("compact"), dict)
        else {}
    )
    evidence_passport.update(
        _domain_passport(
            compact=compact_for_passport,
            query_plan=query_plan,
        )
    )
    report_level = ask_response_support._report_level(effective_mode, freshness_result)
    progress.evidence_passport(evidence_passport)
    progress.answer_ready(
        answer_ready=assembled.answer_ready,
        report_level=report_level,
    )
    public_result = _public_result_for_mode(
        result,
        effective_mode=effective_mode,
        consumer_human_answer=getattr(assembled, "consumer_human_answer", {}) or {},
    )
    if "live_summary" not in public_result:
        result_data = result.get("data") if isinstance(result.get("data"), dict) else {}
        result_compact = (
            result_data.get("compact")
            if isinstance(result_data.get("compact"), dict)
            else {}
        )
        if result_compact:
            _apply_stock_compact_fields(public_result, result_compact)

    result_kind = str(public_result.get("kind") or result.get("kind") or "")
    compact_result = (
        public_result.get("data", {}).get("compact", {})
        if isinstance(public_result.get("data"), dict)
        and isinstance(public_result.get("data", {}).get("compact"), dict)
        else {}
    )
    facts_ready = bool(
        not assembled.clarification.get("required")
        and result_kind not in {"target_error", "clarification_required"}
        and compact_result.get("status") not in {"failed", "missing"}
    )
    response_mode = query_plan_module.canonical_response_mode(effective_mode)
    legacy_analysis_ready = bool(
        getattr(assembled, "answer_ready", False)
        and isinstance(getattr(assembled, "response_analysis", None), dict)
        and getattr(assembled, "response_analysis", {}).get("human_answer")
    )
    analysis_ready = bool(
        (getattr(assembled, "analysis_ready", False) or legacy_analysis_ready)
        and response_mode != "data_only"
    )
    decision_ready = bool(
        getattr(assembled, "decision_ready", False)
        and response_mode != "data_only"
    )
    answer_ready = facts_ready if response_mode == "data_only" else analysis_ready
    available_sections = list(
        dict.fromkeys(
            list(getattr(assembled, "available_sections", []) or [])
            + ["evidence"]
            + (["human_answer"] if analysis_ready else [])
            + (["decision_contract"] if decision_ready else [])
        )
    )
    diagnostics = query_plan_module.diagnostics_projection(
        level=str(query_plan.get("diagnostics_level") or "none"),
        query_plan=query_plan,
        tool_plan=tool_plan,
        tool_runs=tool_runs,
    )
    timeout_run = next(
        (
            run
            for run in tool_runs
            if str(run.get("status") or "") in {"timeout", "background_running"}
        ),
        None,
    )
    request_status = (
        str(timeout_run.get("request_status") or "deadline_exceeded")
        if isinstance(timeout_run, dict)
        else "completed"
    )
    job = (
        timeout_run.get("job")
        if isinstance(timeout_run, dict) and isinstance(timeout_run.get("job"), dict)
        else {}
    )
    cancellation = (
        timeout_run.get("cancellation")
        if isinstance(timeout_run, dict)
        and isinstance(timeout_run.get("cancellation"), dict)
        else {}
    )

    return {
        "kind": "ai_ask",
        "contract_version": ask_response_support.CONTRACT_VERSION,
        "ok": True,
        "question": payload.question,
        "target": response_target,
        "mode": {
            "requested": requested_mode,
            "effective": effective_mode,
            "response": response_mode,
            "payload_level": query_plan.get("payload_level"),
            "diagnostics_level": query_plan.get("diagnostics_level"),
        },
        "action": action,
        "strategy_profile": result.get("strategy_profile") or payload.strategy_profile,
        "caller_profile": payload.caller_profile,
        "resolution": scope_resolution._scope_resolution_dict(resolution),
        "next_context": scope_resolution._next_conversation_context(resolution),
        "clarification": assembled.clarification,
        "next_actions": assembled.next_actions,
        "answer_ready": answer_ready,
        "facts_ready": facts_ready,
        "analysis_ready": analysis_ready,
        "decision_ready": decision_ready,
        "blocked_sections": getattr(assembled, "blocked_sections", []) or [],
        "available_sections": available_sections,
        "request_status": request_status,
        "fallback_used": bool(
            isinstance(timeout_run, dict) and timeout_run.get("fallback_used")
        ),
        "cached_data_returned": bool(
            isinstance(timeout_run, dict) and timeout_run.get("cached_data_returned")
        ),
        "job": job,
        "cancellation": cancellation,
        "report_level": report_level,
        "analysis": _public_analysis_for_mode(
            assembled.response_analysis,
            effective_mode=effective_mode,
        ),
        "reasoning_steps": assembled.reasoning_steps if response_mode != "data_only" else [],
        "policy": policy,
        "tool_plan": tool_plan,
        "tool_runs": tool_runs,
        "query_plan": query_plan,
        "diagnostics": diagnostics,
        "result": public_result,
        "freshness": freshness_result,
        "missing": assembled.combined_missing,
        "warnings": assembled.combined_warnings,
        "source_refs": assembled.result_source_refs,
        "evidence_passport": evidence_passport,
        "error": {},
    }
