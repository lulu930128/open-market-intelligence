from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.ai import (
    agentic_tools,
    decision_core,
    freshness,
    orchestrator,
    reports,
    response_preferences,
    scope_resolution,
    tools,
)
from app.ai import ask_policy
from app.ai.market_date_request import parse_market_trade_date, requested_us_trade_date
from app.ai.schemas import AiAskRequest
from app.us_market.market_indices import read_us_market_indices


_request_target_id = scope_resolution._request_target_id
_looks_like_stock_id = scope_resolution._looks_like_stock_id
_require_scope_id = ask_policy._require_scope_id
_require_group_id = ask_policy._require_group_id

REGIONAL_MARKET_REFERENCES: dict[str, tuple[str, str]] = {
    "US": ("^GSPC", "S&P 500"),
    "JP": ("^N225", "Nikkei 225"),
    "KR": ("KOSPI", "KOSPI"),
}


def _requests_capability(
    payload: AiAskRequest,
    *,
    capability_id: str,
    policy: dict[str, Any] | None,
) -> bool:
    """Honor the normalized bounded selection before dispatching an extra reader."""

    query_plan = (
        policy.get("query_plan")
        if isinstance(policy, dict) and isinstance(policy.get("query_plan"), dict)
        else {}
    )
    if query_plan and any(
        key in query_plan
        for key in ("selected_capabilities", "optional_selected_capabilities")
    ):
        selected = {
            str(value)
            for key in ("selected_capabilities", "optional_selected_capabilities")
            for value in query_plan.get(key) or []
            if value
        }
        return capability_id in selected

    raw_selection = payload.selection if isinstance(payload.selection, dict) else {}
    explicit_values = [
        str(value)
        for key in ("include", "required", "optional")
        for value in raw_selection.get(key) or []
        if value
    ]
    if explicit_values:
        return capability_id in explicit_values
    return True


def _market_data_params(
    payload: AiAskRequest,
    *,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    params = (
        dict(payload.market_data_params)
        if isinstance(payload.market_data_params, dict)
        else {}
    )
    realtime_policy = str(payload.realtime_policy or "prefer_live")
    can_external_fetch = (
        bool(policy.get("can_external_fetch"))
        if isinstance(policy, dict)
        else bool(payload.allow_external_fetch)
    )
    params["realtime_policy"] = realtime_policy
    params["external_fetch_allowed"] = bool(
        can_external_fetch and realtime_policy != "cache_only"
    )
    refresh_policy = (
        policy.get("refresh_policy")
        if isinstance(policy, dict)
        and isinstance(policy.get("refresh_policy"), dict)
        else payload.refresh_policy
        if isinstance(payload.refresh_policy, dict)
        else {}
    )
    params.setdefault(
        "fallback_to_cached",
        bool(refresh_policy.get("fallback_to_cached", True)),
    )
    return params


def _include_tw_intraday(
    payload: AiAskRequest,
    *,
    policy: dict[str, Any] | None = None,
    allow_persisted_cache: bool = True,
) -> bool:
    can_external_fetch = (
        bool(policy.get("can_external_fetch"))
        if isinstance(policy, dict)
        else bool(payload.allow_external_fetch)
    )
    market_data_params = payload.market_data_params if isinstance(payload.market_data_params, dict) else {}
    cache_only = str(payload.realtime_policy or "") == "cache_only"
    refresh_policy = (
        policy.get("refresh_policy")
        if isinstance(policy, dict)
        and isinstance(policy.get("refresh_policy"), dict)
        else payload.refresh_policy
        if isinstance(payload.refresh_policy, dict)
        else {}
    )
    cached_fallback_allowed = allow_persisted_cache and bool(
        market_data_params.get(
            "fallback_to_cached",
            refresh_policy.get("fallback_to_cached", True),
        )
    )
    reader_allowed = bool(
        can_external_fetch or cache_only or cached_fallback_allowed
    )
    if "include_intraday" in market_data_params:
        return bool(market_data_params.get("include_intraday")) and reader_allowed

    query_plan = (
        policy.get("query_plan")
        if isinstance(policy, dict) and isinstance(policy.get("query_plan"), dict)
        else {}
    )
    selected_capabilities = {
        str(value)
        for value in query_plan.get("selected_capabilities") or []
        if value
    }
    if "intraday.bars" in selected_capabilities:
        return reader_allowed

    return decision_core.include_tw_intraday(
        question=payload.question,
        requested_horizon=payload.analysis_horizon,
        strategy_profile=payload.strategy_profile,
        allow_external_fetch=(
            reader_allowed
        ),
    )


def _external_intraday_market_data_params(
    payload: AiAskRequest,
    *,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    params = _market_data_params(payload, policy=policy)
    has_explicit_intraday = "include_intraday" in params
    requested_intraday = bool(params.get("include_intraday")) if has_explicit_intraday else payload.analysis_horizon == "intraday"
    if not requested_intraday or (has_explicit_intraday and not params.get("include_intraday")):
        return params

    params["include_intraday"] = bool(
        params.get("external_fetch_allowed")
        or params.get("realtime_policy") == "cache_only"
    )
    return params


def _us_market_data_params(
    payload: AiAskRequest,
    *,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    params = _external_intraday_market_data_params(payload, policy=policy)
    query_plan = (
        policy.get("query_plan")
        if isinstance(policy, dict) and isinstance(policy.get("query_plan"), dict)
        else {}
    )
    selected_capabilities = list(
        dict.fromkeys(
            [
                *(
                    str(value)
                    for value in query_plan.get("selected_capabilities") or []
                    if value
                ),
                *(
                    str(value)
                    for value in query_plan.get("optional_selected_capabilities") or []
                    if value
                ),
            ]
        )
    )
    if selected_capabilities:
        params["requested_capabilities"] = selected_capabilities
    selection = (
        query_plan.get("selection")
        if isinstance(query_plan.get("selection"), dict)
        else {}
    )
    selection_limits = (
        selection.get("limits")
        if isinstance(selection.get("limits"), dict)
        else {}
    )
    daily_selection_limit = selection_limits.get(
        "daily.ohlcv",
        selection_limits.get("daily.points"),
    )
    if (
        "daily.ohlcv" in selected_capabilities
        and isinstance(daily_selection_limit, int)
        and not isinstance(daily_selection_limit, bool)
        and daily_selection_limit > 0
    ):
        existing_bars = params.get("bars")
        if existing_bars is None:
            params["bars"] = daily_selection_limit
        elif isinstance(existing_bars, int) and not isinstance(existing_bars, bool):
            params["bars"] = max(existing_bars, daily_selection_limit)
    requested_trade_date = requested_us_trade_date(
        payload.question,
        explicit_value=params.get("trade_date"),
    )
    if requested_trade_date is not None:
        params["trade_date"] = requested_trade_date.isoformat()
        # Exact close requests are daily-session facts. Current intraday or
        # extended-hours quotes must not replace the requested close.
        params["include_intraday"] = False
    return params


def _tw_market_data_params(
    payload: AiAskRequest,
    *,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalize explicit Taiwan selection before any reader is dispatched."""

    params = _market_data_params(payload, policy=policy)
    requested_trade_date = parse_market_trade_date(params.get("trade_date"))
    if requested_trade_date is not None:
        params["trade_date"] = requested_trade_date.isoformat()
        params["include_intraday"] = False
    return params


def _watchlist_radar_mode(question_intent: str) -> str:
    if question_intent in {"risk_check", "exit_decision"}:
        return "risk"
    if question_intent == "entry_decision":
        return "momentum"
    return "action"


def _response_preferences(payload: AiAskRequest) -> dict[str, Any]:
    return response_preferences.build_response_preferences(payload.conversation_context)


def _reader_profile(
    payload: AiAskRequest,
    *,
    policy: dict[str, Any] | None = None,
) -> str:
    query_plan = (
        policy.get("query_plan")
        if isinstance(policy, dict) and isinstance(policy.get("query_plan"), dict)
        else {}
    )
    profile = str(query_plan.get("reader_profile") or "").strip()
    if profile:
        return profile
    params = (
        payload.market_data_params
        if isinstance(payload.market_data_params, dict)
        else {}
    )
    return str(params.get("reader_profile") or "").strip()


def _uses_reader_profile(
    payload: AiAskRequest,
    *,
    expected: str,
    question_intent: str,
    policy: dict[str, Any] | None = None,
) -> bool:
    profile = _reader_profile(payload, policy=policy)
    if profile:
        return profile == expected
    return question_intent == {
        "quote_only": "quote",
        "broker_branch_only": "broker_branch",
    }.get(expected)


def _requested_market(payload: AiAskRequest) -> str:
    target = payload.target if isinstance(payload.target, dict) else {}
    return str(target.get("market") or target.get("id") or "TW").strip().upper()


def _as_market_scope(
    result: dict[str, Any],
    *,
    market: str,
    reference_symbol: str,
    reference_label: str,
) -> dict[str, Any]:
    output = deepcopy(result)
    market_target = {
        "type": "market",
        "id": market,
        "market": market,
        "label": f"{market} Market",
    }
    supplemental_reference = {
        "type": "supplemental_reference",
        "role": "representative_index",
        "market": market,
        "id": reference_symbol,
        "label": reference_label,
        "scope_replacement": False,
    }
    output["target"] = market_target
    output["scope"] = {
        "type": "market",
        "market": market,
        "representative_index_is_supplemental": True,
    }
    data = output.get("data")
    if isinstance(data, dict):
        data["representative_index"] = supplemental_reference
        compact = data.get("compact")
        if isinstance(compact, dict):
            compact["target"] = market_target
            compact["representative_index"] = supplemental_reference
            compact["scope_semantics"] = (
                "market_scope_with_supplemental_representative_index"
            )
    limitations = output.get("data_limitations")
    if not isinstance(limitations, list):
        limitations = []
        output["data_limitations"] = limitations
    marker = (
        f"{reference_label} is supplemental market context and does not "
        f"replace the explicit {market} market scope."
    )
    if marker not in limitations:
        limitations.append(marker)
    return output


def _read_market_context(
    db: Session,
    payload: AiAskRequest,
    *,
    tool_runs: list[dict[str, Any]] | None,
    policy: dict[str, Any] | None,
) -> tuple[str, dict[str, Any]]:
    market = _requested_market(payload)
    if market == "TW":
        return "omi.read_market_overview", tools.read_market_overview(
            db=db,
            limit=payload.market_limit,
            include_intraday=_include_tw_intraday(
                payload,
                policy=policy,
                allow_persisted_cache=False,
            ),
            market_data_params=_tw_market_data_params(payload, policy=policy),
        )
    reference = REGIONAL_MARKET_REFERENCES.get(market)
    if reference is None:
        raise ValueError(f"Unsupported market scope: {market}")
    symbol, label = reference
    if market == "US":
        evaluated_at = datetime.now(timezone.utc)
        result = agentic_tools.read_us_stock_context(
            db=db,
            symbol=symbol,
            tool_runs=tool_runs,
            market_data_params=_us_market_data_params(
                payload,
                policy=policy,
            ),
        )
        if _requests_capability(
            payload,
            capability_id="market.indices",
            policy=policy,
        ):
            indices = read_us_market_indices(
                db,
                evaluated_at=evaluated_at,
            ).model_dump(mode="json")
            data = result.setdefault("data", {})
            data.setdefault("market", {})["indices"] = indices
            compact = data.setdefault("compact", {})
            compact.setdefault("market", {})["indices"] = indices
            source_refs = result.setdefault("source_refs", [])
            source_ref = {
                "type": "resolved_market_data",
                "name": "us.market.indices",
            }
            if source_ref not in source_refs:
                source_refs.append(source_ref)
    elif market == "JP":
        result = agentic_tools.read_jp_stock_context(
            db=db,
            symbol=symbol,
            is_index=True,
            tool_runs=tool_runs,
            market_data_params=_external_intraday_market_data_params(
                payload,
                policy=policy,
            ),
        )
    else:
        result = agentic_tools.read_kr_stock_context(
            db=db,
            symbol=symbol,
            is_index=True,
            tool_runs=tool_runs,
            market_data_params=_external_intraday_market_data_params(
                payload,
                policy=policy,
            ),
        )
    return (
        "omi.read_market_overview",
        _as_market_scope(
            result,
            market=market,
            reference_symbol=symbol,
            reference_label=label,
        ),
    )


def _build_market_context_brief(
    db: Session,
    payload: AiAskRequest,
    *,
    tool_runs: list[dict[str, Any]] | None,
    policy: dict[str, Any] | None,
) -> tuple[str, dict[str, Any]]:
    market = _requested_market(payload)
    if market == "TW":
        return "omi.generate_market_brief", reports.build_market_brief(
            db=db,
            limit=payload.market_limit,
            include_intraday=_include_tw_intraday(
                payload,
                policy=policy,
                allow_persisted_cache=False,
            ),
            analysis_horizon=payload.analysis_horizon,
            market_data_params=_market_data_params(payload, policy=policy),
            response_preferences=_response_preferences(payload),
        )
    reference = REGIONAL_MARKET_REFERENCES.get(market)
    if reference is None:
        raise ValueError(f"Unsupported market scope: {market}")
    symbol, label = reference
    if market == "US":
        result = reports.build_us_stock_brief(
            db=db,
            symbol=symbol,
            strategy_profile=payload.strategy_profile,
            analysis_horizon=payload.analysis_horizon,
            tool_runs=tool_runs,
            market_data_params=_us_market_data_params(
                payload,
                policy=policy,
            ),
            response_preferences=_response_preferences(payload),
        )
    elif market == "JP":
        result = reports.build_jp_stock_brief(
            db=db,
            symbol=symbol,
            is_index=True,
            strategy_profile=payload.strategy_profile,
            tool_runs=tool_runs,
            market_data_params=_external_intraday_market_data_params(
                payload,
                policy=policy,
            ),
            response_preferences=_response_preferences(payload),
        )
    else:
        result = reports.build_kr_stock_brief(
            db=db,
            symbol=symbol,
            is_index=True,
            strategy_profile=payload.strategy_profile,
            tool_runs=tool_runs,
            market_data_params=_external_intraday_market_data_params(
                payload,
                policy=policy,
            ),
            response_preferences=_response_preferences(payload),
        )
    return (
        "omi.generate_market_brief",
        _as_market_scope(
            result,
            market=market,
            reference_symbol=symbol,
            reference_label=label,
        ),
    )


def _read_data_only(
    db: Session,
    payload: AiAskRequest,
    scope_type: str,
    *,
    question_intent: str = "general",
    tool_runs: list[dict[str, Any]] | None = None,
    policy: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    if scope_type == "market":
        return _read_market_context(
            db=db,
            payload=payload,
            tool_runs=tool_runs,
            policy=policy,
        )

    if scope_type == "data_freshness":
        target_id = _request_target_id(payload)
        target = payload.target if isinstance(payload.target, dict) else {}
        market = str(target.get("market") or "TW").strip().upper()
        return "omi.read_data_freshness", tools.read_data_freshness(
            db=db,
            stock_id=target_id,
            market=market,
        )

    if scope_type == "stock":
        stock_id = _require_scope_id(payload, "stock")
        if _uses_reader_profile(
            payload,
            expected="identity_only",
            question_intent=question_intent,
            policy=policy,
        ):
            return "omi.read_stock_identity", tools.read_stock_identity_context(
                db=db,
                stock_id=stock_id,
            )
        if _uses_reader_profile(
            payload,
            expected="event_only",
            question_intent=question_intent,
            policy=policy,
        ):
            return (
                "omi.read_stock_events",
                tools.read_stock_event_context(
                    db=db,
                    stock_id=stock_id,
                    market_data_params=_market_data_params(
                        payload,
                        policy=policy,
                    ),
                ),
            )
        if _uses_reader_profile(
            payload,
            expected="quote_only",
            question_intent=question_intent,
            policy=policy,
        ):
            return "omi.read_stock_quote", tools.read_stock_quote_context(
                db=db,
                stock_id=stock_id,
                market_data_params=_market_data_params(payload, policy=policy),
            )
        if _uses_reader_profile(
            payload,
            expected="broker_branch_only",
            question_intent=question_intent,
            policy=policy,
        ):
            return "omi.read_stock_broker_branch", tools.read_stock_broker_branch_context(
                db=db,
                stock_id=stock_id,
                branch_days=payload.branch_days,
                market_data_params=_market_data_params(payload, policy=policy),
            )
        if _uses_reader_profile(
            payload,
            expected="daily_only",
            question_intent=question_intent,
            policy=policy,
        ):
            query_plan = (
                policy.get("query_plan")
                if isinstance(policy, dict)
                and isinstance(policy.get("query_plan"), dict)
                else {}
            )
            selection = (
                query_plan.get("selection")
                if isinstance(query_plan.get("selection"), dict)
                else {}
            )
            limits = (
                selection.get("limits")
                if isinstance(selection.get("limits"), dict)
                else {}
            )
            daily_limit = limits.get(
                "daily.ohlcv",
                limits.get("daily.points", 20),
            )
            return "omi.read_stock_daily", tools.read_stock_daily_context(
                db=db,
                stock_id=stock_id,
                bars=max(int(daily_limit or 20), 1),
                market_data_params=_tw_market_data_params(payload, policy=policy),
            )
        if _uses_reader_profile(
            payload,
            expected="technical_only",
            question_intent=question_intent,
            policy=policy,
        ):
            query_plan = (
                policy.get("query_plan")
                if isinstance(policy, dict)
                and isinstance(policy.get("query_plan"), dict)
                else {}
            )
            selection = (
                query_plan.get("selection")
                if isinstance(query_plan.get("selection"), dict)
                else {}
            )
            limits = (
                selection.get("limits")
                if isinstance(selection.get("limits"), dict)
                else {}
            )
            daily_limit = limits.get(
                "daily.ohlcv",
                limits.get("daily.points", 120),
            )
            return "omi.read_stock_technical", tools.read_stock_technical_context(
                db=db,
                stock_id=stock_id,
                bars=max(int(daily_limit or 120), 1),
                analysis_horizon=payload.analysis_horizon,
                market_data_params=_tw_market_data_params(payload, policy=policy),
            )
        return "omi.read_stock_context", tools.read_stock_context(
            db=db,
            stock_id=stock_id,
            branch_days=payload.branch_days,
            include_intraday=_include_tw_intraday(payload, policy=policy),
            analysis_horizon=payload.analysis_horizon,
            market_data_params=_tw_market_data_params(payload, policy=policy),
        )

    if scope_type == "tw_index":
        index_id = _require_scope_id(payload, "tw_index")
        return "omi.read_tw_index_context", tools.read_tw_index_context(
            db=db,
            index_id=index_id,
            include_intraday=_include_tw_intraday(payload, policy=policy),
            analysis_horizon=payload.analysis_horizon,
            market_data_params=_market_data_params(payload, policy=policy),
        )

    if scope_type == "tw_futures":
        symbol = _require_scope_id(payload, "tw_futures")
        return "omi.read_tw_futures_context", tools.read_tw_futures_context(
            db=db,
            symbol=symbol,
            include_intraday=_include_tw_intraday(payload, policy=policy),
            analysis_horizon=payload.analysis_horizon,
            market_data_params=_market_data_params(payload, policy=policy),
        )

    if scope_type == "us_stock":
        symbol = _require_scope_id(payload, "us_stock")
        return "omi.read_us_stock_context", agentic_tools.read_us_stock_context(
            db=db,
            symbol=symbol,
            tool_runs=tool_runs,
            market_data_params=_us_market_data_params(
                payload,
                policy=policy,
            ),
        )

    if scope_type in {"jp_stock", "jp_index"}:
        symbol = _require_scope_id(payload, scope_type)
        return (
            "omi.read_jp_index_context" if scope_type == "jp_index" else "omi.read_jp_stock_context"
        ), agentic_tools.read_jp_stock_context(
            db=db,
            symbol=symbol,
            is_index=scope_type == "jp_index",
            tool_runs=tool_runs,
            market_data_params=_external_intraday_market_data_params(
                payload,
                policy=policy,
            ),
        )

    if scope_type in {"kr_stock", "kr_index"}:
        symbol = _require_scope_id(payload, scope_type)
        return (
            "omi.read_kr_index_context" if scope_type == "kr_index" else "omi.read_kr_stock_context"
        ), agentic_tools.read_kr_stock_context(
            db=db,
            symbol=symbol,
            is_index=scope_type == "kr_index",
            tool_runs=tool_runs,
            market_data_params=_external_intraday_market_data_params(
                payload,
                policy=policy,
            ),
        )

    if scope_type in {"crypto_market", "crypto_asset"}:
        asset = _require_scope_id(payload, "crypto_asset") if scope_type == "crypto_asset" else None
        return (
            "omi.read_crypto_asset_context" if scope_type == "crypto_asset" else "omi.read_crypto_market_context"
        ), agentic_tools.read_crypto_context(
            db=db,
            asset=asset,
            tool_runs=tool_runs,
            market_data_params=payload.market_data_params,
            context_limit=payload.context_limit,
        )

    if scope_type == "resource_asset":
        symbol = _require_scope_id(payload, scope_type)
        return "omi.read_resource_asset_context", agentic_tools.read_resource_asset_context(
            db=db,
            symbol=symbol,
            market_data_params=payload.market_data_params,
        )

    if scope_type == "us_macro":
        series_id = _require_scope_id(payload, scope_type)
        return "omi.read_us_macro_context", agentic_tools.read_us_macro_context(
            db=db,
            series_id=series_id,
            market_data_params=payload.market_data_params,
        )

    if scope_type == "portfolio":
        trust_source = str((policy or {}).get("server_trust_source") or "untrusted")
        return "omi.read_portfolio_context", agentic_tools.read_portfolio_context(
            db=db,
            market_data_params=payload.market_data_params,
            trusted=trust_source != "untrusted",
        )

    if scope_type == "source_health":
        params = dict(payload.market_data_params)
        target_id = _request_target_id(payload)
        if target_id and "market" not in params:
            params["market"] = target_id
        return "omi.read_unified_source_health_context", agentic_tools.read_unified_source_health_context(
            db=db,
            market_data_params=params,
        )

    if scope_type == "capability_status":
        return "omi.read_capability_status", agentic_tools.read_capability_status(
            capability_id=_request_target_id(payload),
            market_data_params=payload.market_data_params,
        )

    if scope_type in {"us_watchlist", "jp_watchlist", "kr_watchlist"}:
        group_id_text = _require_scope_id(payload, scope_type)
        try:
            group_id = int(group_id_text)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"target.id must be a positive integer for {scope_type}.") from exc
        market = scope_type.split("_", 1)[0]
        params = (
            _us_market_data_params(payload, policy=policy)
            if market == "us"
            else payload.market_data_params
        )
        return f"omi.read_{scope_type}_context", agentic_tools.read_regional_watchlist_context(
            db=db,
            market=market,
            group_id=group_id,
            include_children=payload.include_children,
            enabled_only=payload.enabled_only,
            rank_by=payload.rank_by,
            sort_order=payload.sort_order,
            radar_mode=_watchlist_radar_mode(question_intent),
            market_data_params=params,
            context_limit=payload.context_limit,
        )

    group_id = _require_group_id(payload)
    return "omi.read_watchlist_context", tools.read_watchlist_context(
        db=db,
        group_id=group_id,
        include_children=payload.include_children,
        enabled_only=payload.enabled_only,
        rank_by=payload.rank_by,
        sort_order=payload.sort_order,
        limit=payload.context_limit,
        radar_mode=_watchlist_radar_mode(question_intent),
        market_data_params=payload.market_data_params,
    )


def _build_brief(
    db: Session,
    payload: AiAskRequest,
    scope_type: str,
    *,
    question_intent: str = "general",
    tool_runs: list[dict[str, Any]] | None = None,
    policy: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    if scope_type == "stock" and _uses_reader_profile(
        payload,
        expected="event_only",
        question_intent=question_intent,
        policy=policy,
    ):
        stock_id = _require_scope_id(payload, "stock")
        return "omi.read_stock_events", tools.read_stock_event_context(
            db=db,
            stock_id=stock_id,
            market_data_params=_market_data_params(
                payload,
                policy=policy,
            ),
        )

    if scope_type == "stock" and _uses_reader_profile(
        payload,
        expected="quote_only",
        question_intent=question_intent,
        policy=policy,
    ):
        stock_id = _require_scope_id(payload, "stock")
        return "omi.read_stock_quote", tools.read_stock_quote_context(
            db=db,
            stock_id=stock_id,
            market_data_params=_market_data_params(payload, policy=policy),
        )

    if scope_type == "stock" and _uses_reader_profile(
        payload,
        expected="broker_branch_only",
        question_intent=question_intent,
        policy=policy,
    ):
        stock_id = _require_scope_id(payload, "stock")
        return "omi.read_stock_broker_branch", tools.read_stock_broker_branch_context(
            db=db,
            stock_id=stock_id,
            branch_days=payload.branch_days,
            market_data_params=_market_data_params(payload, policy=policy),
        )

    if scope_type == "market":
        return _build_market_context_brief(
            db=db,
            payload=payload,
            tool_runs=tool_runs,
            policy=policy,
        )

    if scope_type == "stock":
        stock_id = _require_scope_id(payload, "stock")
        return "omi.generate_stock_brief", reports.build_stock_brief(
            db=db,
            stock_id=stock_id,
            strategy_profile=payload.strategy_profile,
            branch_days=payload.branch_days,
            include_intraday=_include_tw_intraday(payload, policy=policy),
            analysis_horizon=payload.analysis_horizon,
            market_data_params=_market_data_params(payload, policy=policy),
            response_preferences=_response_preferences(payload),
        )

    if scope_type == "watchlist":
        group_id = _require_group_id(payload)
        return "omi.generate_watchlist_brief", reports.build_watchlist_brief(
            db=db,
            group_id=group_id,
            strategy_profile=payload.strategy_profile,
            rank_by=payload.rank_by,
            sort_order=payload.sort_order,
            radar_mode=_watchlist_radar_mode(question_intent),
            response_preferences=_response_preferences(payload),
        )

    if scope_type == "us_stock":
        symbol = _require_scope_id(payload, "us_stock")
        return "omi.generate_us_stock_brief", reports.build_us_stock_brief(
            db=db,
            symbol=symbol,
            strategy_profile=payload.strategy_profile,
            analysis_horizon=payload.analysis_horizon,
            tool_runs=tool_runs,
            market_data_params=_us_market_data_params(
                payload,
                policy=policy,
            ),
            response_preferences=_response_preferences(payload),
        )

    if scope_type in {"jp_stock", "jp_index"}:
        symbol = _require_scope_id(payload, scope_type)
        return (
            "omi.generate_jp_index_brief" if scope_type == "jp_index" else "omi.generate_jp_stock_brief"
        ), reports.build_jp_stock_brief(
            db=db,
            symbol=symbol,
            is_index=scope_type == "jp_index",
            strategy_profile=payload.strategy_profile,
            tool_runs=tool_runs,
            market_data_params=_external_intraday_market_data_params(
                payload,
                policy=policy,
            ),
            response_preferences=_response_preferences(payload),
        )

    if scope_type in {"kr_stock", "kr_index"}:
        symbol = _require_scope_id(payload, scope_type)
        return (
            "omi.generate_kr_index_brief" if scope_type == "kr_index" else "omi.generate_kr_stock_brief"
        ), reports.build_kr_stock_brief(
            db=db,
            symbol=symbol,
            is_index=scope_type == "kr_index",
            strategy_profile=payload.strategy_profile,
            tool_runs=tool_runs,
            market_data_params=_external_intraday_market_data_params(
                payload,
                policy=policy,
            ),
            response_preferences=_response_preferences(payload),
        )

    if scope_type in {"crypto_market", "crypto_asset"}:
        asset = _require_scope_id(payload, "crypto_asset") if scope_type == "crypto_asset" else None
        return (
            "omi.generate_crypto_asset_brief" if scope_type == "crypto_asset" else "omi.generate_crypto_market_brief"
        ), reports.build_crypto_brief(
            db=db,
            asset=asset,
            strategy_profile=payload.strategy_profile,
            tool_runs=tool_runs,
            market_data_params=payload.market_data_params,
            context_limit=payload.context_limit,
            response_preferences=_response_preferences(payload),
        )

    return _read_data_only(db, payload, scope_type, tool_runs=tool_runs, policy=policy)


def _generate_report(
    db: Session,
    payload: AiAskRequest,
    scope_type: str,
    *,
    question_intent: str = "general",
    tool_runs: list[dict[str, Any]] | None = None,
    policy: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    if scope_type == "stock" and (
        _uses_reader_profile(
            payload,
            expected="quote_only",
            question_intent=question_intent,
            policy=policy,
        )
        or _uses_reader_profile(
            payload,
            expected="broker_branch_only",
            question_intent=question_intent,
            policy=policy,
        )
        or _uses_reader_profile(
            payload,
            expected="event_only",
            question_intent=question_intent,
            policy=policy,
        )
    ):
        return _read_data_only(
            db,
            payload,
            scope_type,
            question_intent=question_intent,
            tool_runs=tool_runs,
            policy=policy,
        )

    if scope_type == "stock":
        stock_id = _require_scope_id(payload, "stock")
        return "omi.generate_stock_llm_report", orchestrator.generate_stock_llm_report(
            db=db,
            stock_id=stock_id,
            strategy_profile=payload.strategy_profile,
            branch_days=payload.branch_days,
            include_intraday=_include_tw_intraday(payload, policy=policy),
            analysis_horizon=payload.analysis_horizon,
            response_preferences=_response_preferences(payload),
        )

    if scope_type == "watchlist":
        group_id = _require_group_id(payload)
        return "omi.generate_watchlist_llm_report", orchestrator.generate_watchlist_llm_report(
            db=db,
            group_id=group_id,
            strategy_profile=payload.strategy_profile,
            rank_by=payload.rank_by,
            sort_order=payload.sort_order,
            radar_mode=_watchlist_radar_mode(question_intent),
            response_preferences=_response_preferences(payload),
        )

    if scope_type == "us_stock":
        symbol = _require_scope_id(payload, "us_stock")
        return "omi.generate_us_stock_llm_report", orchestrator.generate_us_stock_llm_report(
            db=db,
            symbol=symbol,
            strategy_profile=payload.strategy_profile,
            analysis_horizon=payload.analysis_horizon,
            tool_runs=tool_runs,
            response_preferences=_response_preferences(payload),
        )

    return _read_data_only(db, payload, scope_type, tool_runs=tool_runs, policy=policy)


def _generate_analysis(
    db: Session,
    payload: AiAskRequest,
    scope_type: str,
    *,
    question_intent: str = "general",
    tool_runs: list[dict[str, Any]] | None = None,
    policy: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    if scope_type == "stock" and (
        _uses_reader_profile(
            payload,
            expected="quote_only",
            question_intent=question_intent,
            policy=policy,
        )
        or _uses_reader_profile(
            payload,
            expected="broker_branch_only",
            question_intent=question_intent,
            policy=policy,
        )
        or _uses_reader_profile(
            payload,
            expected="event_only",
            question_intent=question_intent,
            policy=policy,
        )
    ):
        return _read_data_only(
            db,
            payload,
            scope_type,
            question_intent=question_intent,
            tool_runs=tool_runs,
            policy=policy,
        )

    if scope_type == "stock":
        stock_id = _require_scope_id(payload, "stock")
        return "omi.generate_stock_llm_analysis", orchestrator.generate_stock_llm_analysis(
            db=db,
            stock_id=stock_id,
            strategy_profile=payload.strategy_profile,
            branch_days=payload.branch_days,
            include_intraday=_include_tw_intraday(payload, policy=policy),
            analysis_horizon=payload.analysis_horizon,
            response_preferences=_response_preferences(payload),
        )

    if scope_type == "watchlist":
        group_id = _require_group_id(payload)
        return "omi.generate_watchlist_llm_analysis", orchestrator.generate_watchlist_llm_analysis(
            db=db,
            group_id=group_id,
            strategy_profile=payload.strategy_profile,
            rank_by=payload.rank_by,
            sort_order=payload.sort_order,
            radar_mode=_watchlist_radar_mode(question_intent),
            response_preferences=_response_preferences(payload),
        )

    if scope_type == "us_stock":
        symbol = _require_scope_id(payload, "us_stock")
        return "omi.generate_us_stock_llm_analysis", orchestrator.generate_us_stock_llm_analysis(
            db=db,
            symbol=symbol,
            strategy_profile=payload.strategy_profile,
            analysis_horizon=payload.analysis_horizon,
            tool_runs=tool_runs,
            response_preferences=_response_preferences(payload),
        )

    return _read_data_only(db, payload, scope_type, tool_runs=tool_runs, policy=policy)


def _check_freshness(
    db: Session,
    payload: AiAskRequest,
    scope_type: str,
    *,
    question_intent: str = "general",
) -> dict[str, Any]:
    if scope_type == "stock":
        stock_id = _require_scope_id(payload, "stock")
        if _uses_reader_profile(
            payload,
            expected="event_only",
            question_intent=question_intent,
        ):
            result = tools.read_stock_event_context(
                db=db,
                stock_id=stock_id,
                market_data_params=payload.market_data_params,
            )
            freshness_result = result.get("freshness")
            return (
                dict(freshness_result)
                if isinstance(freshness_result, dict)
                else {
                    "scope_profile": "event_only",
                    "status": "unknown",
                    "is_current": False,
                    "missing": list(result.get("missing") or []),
                    "warnings": list(result.get("warnings") or []),
                }
            )
        if _uses_reader_profile(
            payload,
            expected="quote_only",
            question_intent=question_intent,
        ):
            return freshness.check_stock_daily_price_freshness(
                db=db,
                stock_id=stock_id,
            )
        if _uses_reader_profile(
            payload,
            expected="broker_branch_only",
            question_intent=question_intent,
        ):
            return freshness.check_stock_broker_branch_freshness(
                db=db,
                stock_id=stock_id,
            )
        if _uses_reader_profile(
            payload,
            expected="daily_only",
            question_intent=question_intent,
        ) or _uses_reader_profile(
            payload,
            expected="technical_only",
            question_intent=question_intent,
        ):
            return freshness.check_stock_daily_price_freshness(
                db=db,
                stock_id=stock_id,
            )
        stock_freshness = freshness.check_stock_data_freshness(
            db=db,
            stock_id=stock_id,
        )
        return agentic_tools.attach_us_overnight_gaps_to_tw_stock_freshness(
            db,
            stock_id=stock_id,
            stock_freshness=stock_freshness,
        )

    if scope_type == "watchlist":
        return freshness.check_watchlist_data_freshness(
            db=db,
            group_id=_require_group_id(payload),
            include_children=payload.include_children,
            enabled_only=payload.enabled_only,
        )

    if scope_type == "us_stock":
        return agentic_tools.scan_us_stock_gaps(
            db=db,
            symbol=_require_scope_id(payload, "us_stock"),
            question=payload.question,
        )

    if scope_type in {"jp_stock", "jp_index", "kr_stock", "kr_index"}:
        market = "JP" if scope_type.startswith("jp_") else "KR"
        return agentic_tools.scan_regional_market_gaps(
            db,
            market=market,
            target_id=_require_scope_id(payload, scope_type),
            is_index=scope_type.endswith("_index"),
        )

    return {}
