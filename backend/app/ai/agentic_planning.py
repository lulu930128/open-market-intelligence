from __future__ import annotations

from typing import Any

from app.ai import agentic_policy, llm
from app.crypto_market.contract import (
    BINANCE_PROVIDER,
    BITOPRO_PROVIDER,
    OKX_PROVIDER,
    PERPETUAL,
    SPOT,
    list_provider_instruments,
    normalize_symbol as normalize_crypto_symbol,
)
from app.us_market.sources import normalize_us_symbol


TW_STOCK_REFRESH_KEYS = agentic_policy.TW_STOCK_REFRESH_KEYS
TW_CAPABILITY_REFRESH_TOOLS = {
    "daily.ohlcv": ("market_daily_price", "tw.refresh_daily_price"),
    "technical.structure": ("market_daily_price", "tw.refresh_daily_price"),
    "chips.institutional": (
        "institutional_trade_daily",
        "tw.refresh_institutional",
    ),
    "chips.margin": ("margin_trading_daily", "tw.refresh_margin"),
    "broker_branch.summary": (
        "broker_branch_trade_daily",
        "tw.refresh_broker_branch",
    ),
    "ownership.distribution": (
        "shareholding_distribution_weekly",
        "tw.refresh_shareholding",
    ),
    "fundamentals.revenue": ("monthly_revenue", "tw.refresh_revenue"),
    "fundamentals.financials": (
        "financial_metric_quarterly",
        "tw.refresh_financials",
    ),
}
US_CAPABILITY_REQUIREMENTS = {
    "quote.snapshot": ("us_intraday_trend",),
    "intraday.bars": ("us_intraday_trend",),
    "daily.ohlcv": ("us_daily_price",),
    "technical.structure": ("us_daily_price",),
    "company.profile": ("us_company_profile",),
    "corporate.actions": ("us_corporate_action",),
    "fundamentals.financials": ("us_sec_company_fact",),
    "ownership.insider_transactions": ("us_sec_insider_transactions",),
}
CRYPTO_CAPABILITY_REFRESH_TOOLS = {
    "quote.snapshot": ("ticker", "crypto.refresh_ticker", SPOT),
    "intraday.bars": ("ohlcv", "crypto.refresh_ohlcv", SPOT),
    "daily.ohlcv": ("ohlcv", "crypto.refresh_ohlcv", SPOT),
    "crypto.order_book": ("order_book", "crypto.refresh_order_book", SPOT),
    "crypto.derivatives": (
        "derivatives",
        "crypto.refresh_derivatives",
        PERPETUAL,
    ),
}
CRYPTO_PROVIDER_PRIORITY = {
    BINANCE_PROVIDER: 0,
    OKX_PROVIDER: 1,
    BITOPRO_PROVIDER: 2,
}


def _fallback_plan(
    *,
    symbol: str,
    gaps: dict[str, Any],
    question: str,
    requested_trade_date: str | None = None,
    session_scope: str = "regular",
    intraday_interval: str = "1m",
) -> dict[str, Any]:
    missing = set(gaps.get("missing") or [])
    required = set(gaps.get("required_capabilities") or missing)
    lowered_question = question.lower()
    steps: list[dict[str, Any]] = []

    if "us_intraday_trend" in missing and requested_trade_date is None:
        if "quote.snapshot" in required:
            steps.append(
                {
                    "tool": "us.refresh_quote",
                    "args": {"symbol": symbol, "max_provider_calls": 2},
                    "reason": "Canonical US quote evidence is missing or stale.",
                }
            )
        if "intraday.bars" in required or "quote.snapshot" not in required:
            steps.append(
                {
                    "tool": "us.refresh_intraday_bars",
                    "args": {
                        "symbol": symbol,
                        "max_provider_calls": 2,
                        "session_scope": session_scope,
                        "interval": intraday_interval,
                    },
                    "reason": "Canonical US intraday bars are missing or stale.",
                }
            )

    if "us_daily_price" in missing:
        steps.append(
            {
                "tool": "us.refresh_daily_price",
                "args": {
                    "symbol": symbol,
                    "provider": "auto",
                    "outputsize": "compact",
                    "adjusted": False,
                },
                "reason": "Local US daily price evidence is missing or stale.",
            }
        )

    if "us_company_profile" in missing and "us_company_profile" in required:
        steps.append(
            {
                "tool": "us.refresh_company_profile",
                "args": {"symbol": symbol},
                "reason": "Local US company profile evidence is missing or stale.",
            }
        )

    if "us_sec_company_fact" in missing and "us_sec_company_fact" in required:
        steps.append(
            {
                "tool": "us.refresh_sec_facts",
                "args": {"symbol": symbol},
                "reason": "Local SEC facts are missing or the question needs fundamentals.",
            }
        )
        steps.append(
            {
                "tool": "us.read_sec_fundamentals",
                "args": {"symbol": symbol},
                "reason": "Read normalized fundamentals after SEC fact refresh.",
            }
        )

    if (
        "us_sec_insider_transactions" in missing
        and "us_sec_insider_transactions" in required
    ):
        steps.append(
            {
                "tool": "us.refresh_insider_transactions",
                "args": {"symbol": symbol, "max_filings": 50},
                "reason": "Local SEC Form 4 observation is missing or stale.",
            }
        )

    if any(hint in lowered_question for hint in ("dividend", "split", "股利", "拆股", "除息")):
        steps.append(
            {
                "tool": "us.refresh_corporate_actions",
                "args": {"symbol": symbol},
                "reason": "The question asks about dividends or splits.",
            }
        )

    return {
        "provider": "fallback",
        "reason": "Deterministic fallback selected tools from local freshness gaps.",
        "tool_plan": steps,
    }


def _selected_us_plan(
    *,
    symbol: str,
    gaps: dict[str, Any],
    requested_capabilities: tuple[str, ...],
    requested_trade_date: str | None = None,
    session_scope: str = "regular",
    intraday_interval: str = "1m",
    force_selected_capabilities: bool = False,
) -> dict[str, Any]:
    missing = set(gaps.get("missing") or [])
    steps: list[dict[str, Any]] = []
    steps_by_tool: dict[str, dict[str, Any]] = {}
    for capability in requested_capabilities:
        requirements = US_CAPABILITY_REQUIREMENTS.get(capability, ())
        if requested_trade_date is not None:
            if capability == "quote.snapshot":
                requirements = ("us_daily_price",)
            else:
                requirements = tuple(
                    requirement
                    for requirement in requirements
                    if requirement != "us_intraday_trend"
                )
        for requirement in requirements:
            if requirement not in missing and not force_selected_capabilities:
                continue
            if requirement == "us_intraday_trend":
                tool_name = (
                    "us.refresh_quote"
                    if capability == "quote.snapshot"
                    else "us.refresh_intraday_bars"
                )
                args = {
                    "symbol": symbol,
                    "max_provider_calls": 2,
                    **(
                        {
                            "session_scope": session_scope,
                            "interval": intraday_interval,
                        }
                        if tool_name == "us.refresh_intraday_bars"
                        else {}
                    ),
                }
            elif requirement == "us_daily_price":
                tool_name = "us.refresh_daily_price"
                args = {
                    "symbol": symbol,
                    "provider": "auto",
                    "outputsize": "compact",
                    "adjusted": False,
                }
            elif requirement == "us_sec_company_fact":
                tool_name = "us.refresh_sec_facts"
                args = {"symbol": symbol}
            elif requirement == "us_sec_insider_transactions":
                tool_name = "us.refresh_insider_transactions"
                args = {"symbol": symbol, "max_filings": 50}
            elif requirement == "us_company_profile":
                tool_name = "us.refresh_company_profile"
                args = {"symbol": symbol}
            elif requirement == "us_corporate_action":
                tool_name = "us.refresh_corporate_actions"
                args = {"symbol": symbol}
            else:
                continue
            existing_step = steps_by_tool.get(tool_name)
            if existing_step is not None:
                merged_capabilities = list(
                    dict.fromkeys(
                        [
                            *list(
                                existing_step["args"].get(
                                    "requested_capabilities",
                                    [],
                                )
                            ),
                            capability,
                        ]
                    )
                )
                existing_step["args"]["requested_capabilities"] = (
                    merged_capabilities
                )
                existing_step["reason"] = (
                    "Selected capabilities "
                    f"{', '.join(merged_capabilities)} require missing "
                    f"US dataset {requirement} through the same bounded tool."
                )
                continue
            step = {
                "tool": tool_name,
                "args": {
                    **args,
                    "requested_capabilities": [capability],
                },
                "reason": (
                    f"Selected capability {capability} requires missing "
                    f"US dataset {requirement}."
                ),
            }
            steps_by_tool[tool_name] = step
            steps.append(step)
    return {
        "provider": "capability_registry",
        "reason": "Deterministic dataset-level refresh for selected US v4 capabilities.",
        "tool_plan": steps,
    }


def _crypto_refresh_instrument(
    *,
    asset: str,
    resource: str,
    instrument_type: str,
) -> Any | None:
    matches = [
        instrument
        for instrument in list_provider_instruments(
            instrument_type=instrument_type,
            resource=resource,
        )
        if instrument.base_asset == asset
    ]
    if not matches:
        return None
    matches.sort(
        key=lambda item: (
            CRYPTO_PROVIDER_PRIORITY.get(item.provider, 99),
            item.provider,
            item.symbol,
        )
    )
    return matches[0]


def plan_crypto_asset_tools(
    *,
    asset: str,
    target: dict[str, Any],
    requested_capabilities: tuple[str, ...],
    selection: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    del target
    normalized_asset = str(asset or "").strip().upper()
    limits = selection.get("limits") if isinstance(selection.get("limits"), dict) else {}
    warnings: list[str] = []
    steps: list[dict[str, Any]] = []
    seen_steps: set[tuple[str, str]] = set()

    for capability in requested_capabilities:
        mapping = CRYPTO_CAPABILITY_REFRESH_TOOLS.get(capability)
        if mapping is None:
            continue
        resource, tool_name, instrument_type = mapping
        instrument = _crypto_refresh_instrument(
            asset=normalized_asset,
            resource=resource,
            instrument_type=instrument_type,
        )
        if instrument is None:
            warnings.append(
                f"No bounded crypto provider instrument supports {capability} "
                f"for {normalized_asset}."
            )
            continue
        interval = (
            "1d"
            if capability == "daily.ohlcv"
            else "1m"
            if tool_name == "crypto.refresh_ohlcv"
            else ""
        )
        dedupe_key = (tool_name, interval)
        if dedupe_key in seen_steps:
            for step in steps:
                if (
                    step["tool"] == tool_name
                    and str(step["args"].get("interval") or "") == interval
                ):
                    step["args"]["requested_capabilities"] = list(
                        dict.fromkeys(
                            [
                                *step["args"]["requested_capabilities"],
                                capability,
                            ]
                        )
                    )
                    break
            continue
        seen_steps.add(dedupe_key)
        requested_limit = int(limits.get(capability) or 20)
        args: dict[str, Any] = {
            "asset": normalized_asset,
            "provider": instrument.provider,
            "symbol": normalize_crypto_symbol(instrument.symbol),
            "requested_capabilities": [capability],
        }
        if tool_name == "crypto.refresh_order_book":
            args["depth_limit"] = max(1, min(requested_limit, 20))
        elif tool_name == "crypto.refresh_ohlcv":
            args.update(
                {
                    "interval": interval,
                    "limit": max(1, min(requested_limit, 100)),
                }
            )
        steps.append(
            {
                "tool": tool_name,
                "args": args,
                "reason": (
                    f"Refresh only selected crypto capability {capability} for "
                    f"{normalized_asset} through {instrument.provider}."
                ),
            }
        )

    return _normalize_plan(
        {
            "provider": "capability_registry",
            "reason": "Deterministic target-level refresh for selected crypto v4 capabilities.",
            "tool_plan": steps,
        },
        default_symbol=normalized_asset,
        provider="capability_registry",
    ), warnings


def _overnight_daily_refresh_steps(
    overnight_gaps: dict[str, Any] | None,
    *,
    stock_id: str,
    requested_capabilities: tuple[str, ...] = (
        "cross_market.overnight",
    ),
    force: bool = False,
) -> list[dict[str, Any]]:
    if not isinstance(overnight_gaps, dict):
        if not force:
            return []
        overnight_gaps = {}
    refresh_decision = overnight_gaps.get("refresh_decision")
    should_execute = (
        bool(refresh_decision.get("should_execute"))
        if isinstance(refresh_decision, dict)
        else bool(overnight_gaps.get("refresh_recommended"))
    )
    if not should_execute and not force:
        return []
    normalized_stock_id = str(stock_id or "").strip()
    if not normalized_stock_id:
        return []
    return [
        {
            "tool": "cross_market.refresh_context",
            "args": {
                "stock_id": normalized_stock_id,
                "max_symbols": 8,
                "provider": "auto",
                "outputsize": "compact",
                "max_runtime_seconds": 120,
                "requested_capabilities": list(
                    dict.fromkeys(requested_capabilities)
                ),
            },
            "reason": (
                "Refresh the backend-owned bounded cross-market source set, including "
                "required US daily prices, proxy benchmarks, and USD/TWD when applicable."
            ),
        }
    ]


def _fallback_tw_stock_plan(
    *,
    stock_id: str,
    gaps: dict[str, Any],
    overnight_gaps: dict[str, Any] | None = None,
) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    missing = set(gaps.get("refreshable_missing") or gaps.get("missing") or [])
    tw_refresh_needed = bool(missing & TW_STOCK_REFRESH_KEYS)
    if gaps.get("refresh_recommended") and tw_refresh_needed:
        steps.append(
            {
                "tool": "tw.refresh_stock_evidence",
                "args": {
                    "stock_id": stock_id,
                    "include_today": None,
                    "sleep_seconds": 0.05,
                },
                "reason": "Local Taiwan stock evidence is stale or incomplete before answering.",
            }
        )

    steps.extend(
        _overnight_daily_refresh_steps(
            overnight_gaps,
            stock_id=stock_id,
        )
    )
    reason = "Deterministic fallback selected Taiwan stock refresh from local freshness gaps."
    if overnight_gaps and overnight_gaps.get("refresh_recommended"):
        reason = (
            "Deterministic fallback selected Taiwan stock refresh and US overnight factor refresh "
            "from local freshness gaps."
        )

    return {
        "provider": "fallback",
        "reason": reason,
        "tool_plan": steps,
    }


def _fallback_tw_watchlist_plan(
    *,
    group_id: int,
    gaps: dict[str, Any],
    include_children: bool,
    enabled_only: bool,
    requested_capabilities: tuple[str, ...] | None = None,
    force_selected_capabilities: bool = False,
) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    refresh_params = gaps.get("refresh_params") if isinstance(gaps.get("refresh_params"), dict) else {}
    missing = set(gaps.get("missing") or [])
    selected = tuple(
        capability
        for capability in requested_capabilities or ()
        if capability in {"watchlist.ranking", "watchlist.radar"}
    )
    should_refresh = bool(
        gaps.get("refresh_recommended")
        and "market_daily_price" in missing
    ) or bool(force_selected_capabilities and selected)
    if should_refresh:
        args = {
            "group_id": group_id,
            "lookback_days": refresh_params.get("lookback_days", 14),
            "include_today": refresh_params.get("include_today", False),
            "include_children": refresh_params.get("include_children", include_children),
            "enabled_only": refresh_params.get("enabled_only", enabled_only),
            "sleep_seconds": min(
                float(refresh_params.get("sleep_seconds", 0.3) or 0.3),
                0.3,
            ),
            "skip_existing_months": refresh_params.get("skip_existing_months", True),
        }
        if selected:
            args["requested_capabilities"] = list(dict.fromkeys(selected))
        steps.append(
            {
                "tool": "tw.refresh_watchlist_evidence",
                "args": args,
                "reason": (
                    "Execute the caller-selected bounded Taiwan watchlist fill action."
                    if force_selected_capabilities and selected
                    else "Local Taiwan watchlist daily price evidence is stale or incomplete before answering."
                ),
            }
        )

    reason = "Deterministic fallback selected Taiwan watchlist daily refresh from local freshness gaps."
    if gaps.get("refresh_recommended") and not steps:
        reason = (
            "Watchlist freshness gaps do not include daily price; skipped group daily refresh "
            "because full institutional/fundamental evidence is refreshed per stock."
        )

    return {
        "provider": "fallback",
        "reason": reason,
        "tool_plan": steps,
    }


def _planner_input(
    *,
    question: str,
    target: dict[str, Any],
    gaps: dict[str, Any],
    budget: dict[str, int],
    allowed_tool_prefix: str | None = None,
    allowed_tool_names: set[str] | None = None,
) -> dict[str, Any]:
    return {
        "question": question,
        "target": target,
        "freshness_gaps": {
            "missing": gaps.get("missing") or [],
            "warnings": gaps.get("warnings") or [],
            "expected_dates": gaps.get("expected_dates") or {},
        },
        "budget": budget,
        "allowed_tools": agentic_policy.tool_definitions_for_llm(
            prefix=allowed_tool_prefix,
            names=allowed_tool_names,
        ),
        "rules": [
            "Use only allowed tool names.",
            "Prefer local evidence when current enough.",
            "Do not request broad market-wide refreshes from a single-stock question.",
            "Keep tool count within budget and avoid duplicate calls.",
        ],
    }


def _normalize_plan_step(
    step: dict[str, Any],
    *,
    default_symbol: str,
) -> dict[str, Any] | None:
    tool_name = str(step.get("tool") or "").strip()
    if not tool_name:
        return None

    raw_args = step.get("args") if isinstance(step.get("args"), dict) else {}
    args = dict(raw_args)
    symbol_source = args.get("symbol") or step.get("symbol")
    if not symbol_source and tool_name.startswith("us."):
        symbol_source = default_symbol
    symbol = (
        normalize_crypto_symbol(symbol_source)
        if tool_name.startswith("crypto.")
        else normalize_us_symbol(symbol_source)
    )
    if symbol:
        args["symbol"] = symbol
    stock_id = str(args.get("stock_id") or step.get("stock_id") or "").strip()
    if not stock_id and tool_name.startswith("tw.refresh_") and tool_name != "tw.refresh_watchlist_evidence":
        stock_id = str(args.get("symbol") or step.get("symbol") or default_symbol).strip()
    if stock_id:
        args["stock_id"] = stock_id
    group_id = str(args.get("group_id") or step.get("group_id") or "").strip()
    if group_id:
        args["group_id"] = group_id
    if step.get("provider") is not None and "provider" not in args:
        args["provider"] = str(step["provider"])
    if step.get("outputsize") is not None and "outputsize" not in args:
        args["outputsize"] = str(step["outputsize"])
    if step.get("adjusted") is not None and "adjusted" not in args:
        args["adjusted"] = bool(step["adjusted"])
    if step.get("series_id") is not None and "series_id" not in args:
        args["series_id"] = str(step["series_id"])
    if step.get("include_today") is not None and "include_today" not in args:
        args["include_today"] = bool(step["include_today"])
    if step.get("sleep_seconds") is not None and "sleep_seconds" not in args:
        args["sleep_seconds"] = step["sleep_seconds"]

    return {
        "tool": tool_name,
        "args": args,
        "reason": str(step.get("reason") or "").strip(),
    }


def _normalize_plan(
    raw_plan: dict[str, Any],
    *,
    default_symbol: str,
    provider: str,
) -> dict[str, Any]:
    raw_steps = raw_plan.get("tool_plan") if isinstance(raw_plan.get("tool_plan"), list) else []
    steps = [
        normalized
        for step in raw_steps
        if isinstance(step, dict)
        if (normalized := _normalize_plan_step(step, default_symbol=default_symbol)) is not None
    ]
    plan = {
        "provider": raw_plan.get("provider") or provider,
        "reason": str(raw_plan.get("reason") or "").strip(),
        "tool_plan": steps,
    }
    for key in ("response_id", "model", "usage"):
        if key in raw_plan:
            plan[key] = raw_plan[key]
    return plan


def plan_us_stock_tools(
    *,
    question: str,
    symbol: str,
    target: dict[str, Any],
    gaps: dict[str, Any],
    budget: dict[str, int],
    can_call_llm: bool,
    requested_capabilities: tuple[str, ...] | None = None,
    requested_trade_date: str | None = None,
    session_scope: str = "regular",
    intraday_interval: str = "1m",
    force_selected_capabilities: bool = False,
) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    normalized_symbol = normalize_us_symbol(symbol)
    normalized_intraday_interval = str(intraday_interval).strip().lower()
    if normalized_intraday_interval not in {"1m", "5m", "15m", "30m", "1h", "4h"}:
        normalized_intraday_interval = "1m"

    if requested_capabilities is not None:
        return _normalize_plan(
            _selected_us_plan(
                symbol=normalized_symbol,
                gaps=gaps,
                requested_capabilities=requested_capabilities,
                requested_trade_date=requested_trade_date,
                session_scope=session_scope,
                intraday_interval=normalized_intraday_interval,
                force_selected_capabilities=force_selected_capabilities,
            ),
            default_symbol=normalized_symbol,
            provider="capability_registry",
        ), warnings

    if can_call_llm and requested_trade_date is None:
        try:
            raw_plan = llm.generate_tool_plan(
                _planner_input(
                    question=question,
                    target=target,
                    gaps=gaps,
                    budget=budget,
                    allowed_tool_prefix="us.",
                )
            )
            normalized_plan = _normalize_plan(
                raw_plan,
                default_symbol=normalized_symbol,
                provider="openai",
            )
            for step in normalized_plan.get("tool_plan") or []:
                if step.get("tool") == "us.read_intraday_trend":
                    step["tool"] = "us.refresh_intraday_bars"
                    step["args"] = {
                        "symbol": normalized_symbol,
                        "max_provider_calls": 2,
                    }
            return normalized_plan, warnings
        except llm.OpenAILLMError as exc:
            warnings.append(f"OMI LLM tool planner failed; used deterministic fallback. Error: {exc}")

    return _normalize_plan(
        _fallback_plan(
            symbol=normalized_symbol,
            gaps=gaps,
            question=question,
            requested_trade_date=requested_trade_date,
            session_scope=session_scope,
            intraday_interval=normalized_intraday_interval,
        ),
        default_symbol=normalized_symbol,
        provider="fallback",
    ), warnings


def plan_tw_stock_tools(
    *,
    question: str,
    stock_id: str,
    target: dict[str, Any],
    gaps: dict[str, Any],
    overnight_gaps: dict[str, Any] | None = None,
    budget: dict[str, int],
    can_call_llm: bool,
    requested_capabilities: tuple[str, ...] | None = None,
    force_selected_capabilities: bool = False,
) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    normalized_stock_id = str(stock_id or "").strip()

    if requested_capabilities is not None:
        missing = set(gaps.get("refreshable_missing") or gaps.get("missing") or [])
        steps: list[dict[str, Any]] = []
        seen_tools: set[str] = set()
        for capability in requested_capabilities:
            mapping = TW_CAPABILITY_REFRESH_TOOLS.get(capability)
            if mapping is None:
                continue
            dataset, tool_name = mapping
            if (
                dataset not in missing
                and not force_selected_capabilities
            ) or tool_name in seen_tools:
                continue
            seen_tools.add(tool_name)
            steps.append(
                {
                    "tool": tool_name,
                    "args": {
                        "stock_id": normalized_stock_id,
                        "include_today": None,
                        "sleep_seconds": 0.05,
                        "requested_capabilities": [capability],
                    },
                    "reason": (
                        f"Selected capability {capability} is missing or stale; "
                        f"refresh only dataset {dataset}."
                    ),
                }
            )
        cross_market_capabilities = tuple(
            capability
            for capability in requested_capabilities
            if capability
            in {
                "cross_market.overnight",
                "cross_market.relations",
                "cross_market.parity",
            }
        )
        if cross_market_capabilities:
            steps.extend(
                _overnight_daily_refresh_steps(
                    overnight_gaps,
                    stock_id=normalized_stock_id,
                    requested_capabilities=cross_market_capabilities,
                    force=force_selected_capabilities,
                )
            )
        return _normalize_plan(
            {
                "provider": "capability_registry",
                "reason": "Deterministic dataset-level refresh for selected v4 capabilities.",
                "tool_plan": steps,
            },
            default_symbol=normalized_stock_id,
            provider="capability_registry",
        ), warnings

    def with_overnight_steps(plan: dict[str, Any]) -> dict[str, Any]:
        overnight_steps = _overnight_daily_refresh_steps(
            overnight_gaps,
            stock_id=normalized_stock_id,
        )
        if not overnight_steps:
            return plan
        existing = {
            (
                step.get("tool"),
                tuple(sorted((str(k), str(v)) for k, v in (step.get("args") or {}).items())),
            )
            for step in plan.get("tool_plan") or []
            if isinstance(step, dict)
        }
        for step in overnight_steps:
            key = (
                step.get("tool"),
                tuple(sorted((str(k), str(v)) for k, v in (step.get("args") or {}).items())),
            )
            if key not in existing:
                plan.setdefault("tool_plan", []).append(step)
                existing.add(key)
        if overnight_gaps and overnight_gaps.get("refresh_recommended"):
            plan["reason"] = (
                (plan.get("reason") or "Taiwan stock refresh plan.")
                + " Added deterministic US overnight factor refresh."
            )
        return plan

    if can_call_llm:
        try:
            raw_plan = llm.generate_tool_plan(
                _planner_input(
                    question=question,
                    target=target,
                    gaps=gaps,
                    budget=budget,
                    allowed_tool_prefix="tw.",
                    allowed_tool_names={"tw.refresh_stock_evidence"},
                )
            )
            return with_overnight_steps(
                _normalize_plan(
                    raw_plan,
                    default_symbol=normalized_stock_id,
                    provider="openai",
                )
            ), warnings
        except llm.OpenAILLMError as exc:
            warnings.append(f"OMI LLM tool planner failed; used deterministic fallback. Error: {exc}")

    return with_overnight_steps(
        _normalize_plan(
            _fallback_tw_stock_plan(
                stock_id=normalized_stock_id,
                gaps=gaps,
                overnight_gaps=overnight_gaps,
            ),
            default_symbol=normalized_stock_id,
            provider="fallback",
        )
    ), warnings


def plan_tw_watchlist_tools(
    *,
    group_id: int,
    gaps: dict[str, Any],
    budget: dict[str, int],
    include_children: bool,
    enabled_only: bool,
    requested_capabilities: tuple[str, ...] | None = None,
    force_selected_capabilities: bool = False,
) -> tuple[dict[str, Any], list[str]]:
    del budget
    return _normalize_plan(
        _fallback_tw_watchlist_plan(
            group_id=group_id,
            gaps=gaps,
            include_children=include_children,
            enabled_only=enabled_only,
            requested_capabilities=requested_capabilities,
            force_selected_capabilities=force_selected_capabilities,
        ),
        default_symbol=str(group_id),
        provider="fallback",
    ), []
