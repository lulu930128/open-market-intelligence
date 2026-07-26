from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any

from app.ai import capability_contract
from app.ai.market_payload_contract import PAYLOAD_LEVELS
from app.ai.schemas import AiAskRequest


DIAGNOSTICS_LEVELS = {"none", "basic", "debug"}
CANONICAL_RESPONSE_MODES = {"data_only", "brief", "full"}
LEGACY_MODE_ALIASES = {
    "auto": "brief",
    "analysis": "full",
    "report": "full",
}

QUOTE_ONLY_REQUIRED_CAPABILITIES = (
    "target_identity",
    "quote_snapshot",
    "quote_freshness",
    "market_daily_price",
)
QUOTE_ONLY_EXCLUDED_CAPABILITIES = (
    "live_intraday_bars",
    "daily_ohlc_chart",
    "technical_decision_evidence",
    "tw_chips_and_flows",
    "tw_fundamentals",
    "broker_branch",
    "cross_market_context",
    "news_and_event_context",
)
QUOTE_ONLY_EXCLUDED_READERS = (
    "get_latest_stock_institutional_trade",
    "get_latest_stock_margin_trade",
    "get_latest_stock_monthly_revenue",
    "get_latest_stock_financial_metric",
    "list_latest_stock_shareholding_distribution",
    "list_stock_monthly_revenue_history",
    "list_stock_financial_metric_history",
    "list_stock_ohlc_chart_data",
    "get_broker_branch_trade_summary",
    "build_stock_technical_report",
    "build_us_overnight_impact_report",
    "get_market_intraday_history",
    "get_taiwan_stock_quote_depth",
)
BROKER_BRANCH_REQUIRED_CAPABILITIES = (
    "target_identity",
    "broker_branch",
    "broker_branch_trade_daily",
)
BROKER_BRANCH_EXCLUDED_CAPABILITIES = (
    "live_intraday_bars",
    "daily_ohlc_chart",
    "technical_decision_evidence",
    "institutional_flow",
    "margin_trading",
    "shareholding_distribution",
    "tw_fundamentals",
    "cross_market_context",
)
BROKER_BRANCH_EXCLUDED_READERS = tuple(
    reader
    for reader in QUOTE_ONLY_EXCLUDED_READERS
    if reader != "get_broker_branch_trade_summary"
)
DOMAIN_HINTS = {
    "chart": ("日K", "日線", "K線", "daily chart", "daily ohlcv", "ohlcv"),
    "technical": (
        "技術面",
        "技術分析",
        "均線",
        "支撐",
        "壓力",
        "technical",
        "support",
        "resistance",
    ),
    "quote": ("即時報價", "報價", "現價", "股價", "latest quote", "latest price"),
    "intraday": ("分k", "分 k", "盤中", "intraday", "realtime", "real-time"),
    "chips": ("法人", "籌碼", "融資", "融券", "chips"),
    "fundamentals": ("營收", "財報", "基本面", "revenue", "fundamental"),
    "broker_branch": ("分點", "券商分點", "broker branch"),
    "cross_market": ("跨市場", "美股影響", "cross market"),
    "volume": (
        "成交值",
        "成交金額",
        "量能速度",
        "量能",
        "market volume",
        "trade value",
    ),
    "breadth": (
        "市場廣度",
        "上漲家數",
        "下跌家數",
        "advance decline",
        "market breadth",
    ),
    "sample_ranking": (
        "排行",
        "漲幅榜",
        "跌幅榜",
        "產業排行",
        "top gainers",
        "top losers",
    ),
}
NEGATION_TERMS = ("不查", "不刷新", "不需要", "不要", "排除", "without", "except")
RESTRICTIVE_CAPABILITY_TERMS = (
    "只查",
    "只要",
    "僅查",
    "僅要",
    "不要其他",
    "only",
    "just",
)
NEGATED_RESTRICTIVE_TERMS = ("不只", "不僅", "not only")


DOMAIN_HINTS["chips"] = (
    *DOMAIN_HINTS["chips"],
    "法人",
    "融資",
    "融券",
    "institutional",
    "margin",
)

CAPABILITY_HINTS = {
    "chips.institutional": (
        "三大法人",
        "法人",
        "外資",
        "投信",
        "自營商",
        "institutional flow",
        "institutional",
    ),
    "chips.margin": (
        "融資券",
        "融資",
        "融券",
        "信用交易",
        "借券",
        "margin trading",
        "margin",
    ),
    "ownership.distribution": (
        "股權分級",
        "持股分級",
        "股權分散",
        "持股分布",
        "集保",
        "tdcc",
        "集保股權",
        "shareholding distribution",
        "ownership distribution",
    ),
}

INTENT_DOMAINS = {
    "quote": ("quote",),
    "broker_branch": ("broker_branch",),
    "market_breadth": ("breadth",),
    "trend_view": ("chart", "technical"),
    "entry_decision": ("quote", "chart", "technical"),
    "exit_decision": ("quote", "chart", "technical"),
    "risk_check": ("quote", "chart", "technical"),
    "position_risk_decision": ("quote", "chart", "technical"),
    "data_freshness": ("freshness",),
}


@dataclass(frozen=True)
class QueryPlan:
    intent: str
    intents: tuple[str, ...]
    target_type: str
    response_mode: str
    reader_profile: str
    payload_level: str
    diagnostics_level: str
    required_capabilities: tuple[str, ...]
    optional_capabilities: tuple[str, ...]
    excluded_capabilities: tuple[str, ...]
    required_readers: tuple[str, ...]
    excluded_readers: tuple[str, ...]
    freshness_scope: tuple[str, ...]
    external_refresh_allowed: bool
    requested_domains: tuple[str, ...]
    excluded_domains: tuple[str, ...]
    matched_positive_terms: tuple[str, ...]
    matched_negative_terms: tuple[str, ...]
    capability_selection_mode: str
    selected_action_reason: str
    requested_provider: str | None
    strict_provider: bool
    selection: dict[str, Any]
    selected_capabilities: tuple[str, ...]
    optional_selected_capabilities: tuple[str, ...]
    max_response_bytes: int
    realtime_policy: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalized_payload_level(payload: AiAskRequest) -> str:
    explicit = payload.payload_level
    if explicit is None and isinstance(payload.market_data_params, dict):
        explicit = payload.market_data_params.get("payload_level")
    value = str(explicit or "compact").strip().lower()
    return value if value in PAYLOAD_LEVELS else "compact"


def canonical_response_mode(effective_mode: str) -> str:
    if effective_mode in CANONICAL_RESPONSE_MODES:
        return effective_mode
    return LEGACY_MODE_ALIASES.get(effective_mode, "brief")


def _list_param(params: dict[str, Any], key: str) -> tuple[str, ...]:
    raw = params.get(key)
    if not isinstance(raw, (list, tuple, set)):
        return ()
    return tuple(
        dict.fromkeys(
            str(value).strip().lower()
            for value in raw
            if str(value).strip()
        )
    )


def _query_domains(payload: AiAskRequest, question_intent: str) -> tuple[
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
]:
    params = payload.market_data_params if isinstance(payload.market_data_params, dict) else {}
    explicit_requested = _list_param(params, "refresh_domains") or _list_param(params, "requested_domains")
    explicit_excluded = _list_param(params, "excluded_domains")
    question = payload.question.casefold()
    positive_terms: list[str] = []
    negative_terms: list[str] = []
    requested: list[str] = list(explicit_requested)
    excluded: list[str] = list(explicit_excluded)

    for domain, hints in DOMAIN_HINTS.items():
        for hint in hints:
            normalized_hint = hint.casefold()
            if normalized_hint not in question:
                continue
            negated = next(
                (
                    negation
                    for negation in NEGATION_TERMS
                    if re.search(
                        rf"{re.escape(negation.casefold())}[^，,。；;!?]{{0,40}}{re.escape(normalized_hint)}",
                        question,
                    )
                ),
                None,
            )
            if negated:
                excluded.append(domain)
                negative_terms.append(f"{negated}:{hint}")
            else:
                requested.append(domain)
                positive_terms.append(hint)

    if question_intent == "quote" and "quote" not in requested:
        requested.insert(0, "quote")
    requested = [domain for domain in requested if domain not in set(excluded)]
    return (
        tuple(dict.fromkeys(requested)),
        tuple(dict.fromkeys(excluded)),
        tuple(dict.fromkeys(positive_terms)),
        tuple(dict.fromkeys(negative_terms)),
    )


def _query_capabilities(
    payload: AiAskRequest,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    question = payload.question.casefold()
    requested: list[str] = []
    excluded: list[str] = []
    for capability_id, hints in CAPABILITY_HINTS.items():
        for hint in hints:
            normalized_hint = hint.casefold()
            if normalized_hint not in question:
                continue
            negated = any(
                re.search(
                    rf"{re.escape(negation.casefold())}[^，,。；;!?]{{0,40}}{re.escape(normalized_hint)}",
                    question,
                )
                for negation in NEGATION_TERMS
            )
            if negated:
                excluded.append(capability_id)
            else:
                requested.append(capability_id)
    excluded_set = set(excluded)
    return (
        tuple(
            capability_id
            for capability_id in dict.fromkeys(requested)
            if capability_id not in excluded_set
        ),
        tuple(dict.fromkeys(excluded)),
    )


def _domains_for_intents(intents: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            domain
            for intent in intents
            for domain in INTENT_DOMAINS.get(intent, ())
        )
    )


def _is_pure_fast_path(
    *,
    intents: tuple[str, ...],
    requested_domains: tuple[str, ...],
    selection: dict[str, Any],
    allowed_intents: set[str],
    allowed_domains: set[str],
    allowed_capabilities: set[str],
) -> bool:
    selected_capabilities = set(selection.get("required") or ()) | set(
        selection.get("optional") or ()
    )
    return bool(
        set(intents) <= allowed_intents
        and set(requested_domains) <= allowed_domains
        and selected_capabilities <= allowed_capabilities
    )


def build_query_plan(
    *,
    payload: AiAskRequest,
    scope_type: str,
    question_intent: str,
    effective_mode: str,
) -> QueryPlan:
    response_mode = canonical_response_mode(effective_mode)
    payload_level = normalized_payload_level(payload)
    diagnostics_level = payload.diagnostics_level
    params = payload.market_data_params if isinstance(payload.market_data_params, dict) else {}
    requested_domains, excluded_domains, positive_terms, negative_terms = _query_domains(
        payload,
        question_intent,
    )
    raw_selection = payload.selection if isinstance(payload.selection, dict) else {}
    has_explicit_capability_selection = any(
        key in raw_selection
        for key in ("required", "include", "optional", "exclude")
    )
    if has_explicit_capability_selection:
        requested_capabilities: tuple[str, ...] = ()
        excluded_selection_capabilities: tuple[str, ...] = ()
        capability_selection_mode = "explicit"
    else:
        (
            requested_capabilities,
            excluded_selection_capabilities,
        ) = _query_capabilities(payload)
        normalized_question = payload.question.casefold()
        restrictive = bool(
            requested_capabilities
            and any(
                term.casefold() in normalized_question
                for term in RESTRICTIVE_CAPABILITY_TERMS
            )
            and not any(
                term.casefold() in normalized_question
                for term in NEGATED_RESTRICTIVE_TERMS
            )
        )
        capability_selection_mode = (
            "restrictive"
            if restrictive
            else "additive"
            if requested_capabilities
            else "default"
        )
    intents = tuple(
        dict.fromkeys(
            [
                *(
                    str(value).strip()
                    for value in payload.intents
                    if str(value).strip()
                ),
                question_intent,
            ]
        )
    )
    requested_domains = tuple(
        domain
        for domain in dict.fromkeys(
            (*requested_domains, *_domains_for_intents(intents))
        )
        if domain not in set(excluded_domains)
    )
    request_domains_before_selection = requested_domains
    selection_input = payload.selection
    if capability_selection_mode == "restrictive":
        selection_input = {
            **raw_selection,
            "include": list(requested_capabilities),
            "exclude": list(excluded_selection_capabilities),
        }
    selection = capability_contract.normalize_selection(
        selection=selection_input,
        output=payload.output,
        realtime_policy=payload.realtime_policy,
        payload_level=payload_level,
        scope_type=scope_type,
        question_intent=question_intent,
        requested_domains=requested_domains,
        excluded_domains=excluded_domains,
        requested_capabilities=requested_capabilities,
        excluded_capabilities=excluded_selection_capabilities,
    )
    selection["capability_selection_mode"] = capability_selection_mode
    selected_capabilities = {
        *list(selection.get("required") or []),
        *list(selection.get("optional") or []),
    }
    legacy_intraday_limit = params.get("intraday_limit")
    selection_limits = dict(selection.get("limits") or {})
    if (
        legacy_intraday_limit is not None
        and "intraday.bars" in selected_capabilities
        and "intraday.bars" not in selection_limits
        and "intraday.points" not in selection_limits
    ):
        if (
            isinstance(legacy_intraday_limit, bool)
            or not isinstance(legacy_intraday_limit, int)
        ):
            raise ValueError(
                "market_data_params.intraday_limit must be an integer."
            )
        selection_limits["intraday.bars"] = max(
            1,
            min(legacy_intraday_limit, 500),
        )
        selection["limits"] = selection_limits
    selection_domains = capability_contract.domains_for_selection(selection)
    requested_domains = tuple(
        dict.fromkeys((*requested_domains, *selection_domains))
    )
    providers = params.get("providers") if isinstance(params.get("providers"), list) else []
    requested_provider = str(params.get("provider") or (providers[0] if providers else "")).strip() or None
    strict_provider = params.get("strict_provider") is True

    if (
        scope_type == "stock"
        and question_intent == "quote"
        and _is_pure_fast_path(
            intents=intents,
            requested_domains=request_domains_before_selection,
            selection=selection,
            allowed_intents={"quote", "data_freshness"},
            allowed_domains={"quote", "intraday", "freshness"},
            allowed_capabilities={
                "target.identity",
                "quote.snapshot",
                "intraday.bars",
                "data.freshness",
            },
        )
    ):
        required_capabilities = list(QUOTE_ONLY_REQUIRED_CAPABILITIES)
        excluded_capabilities = list(QUOTE_ONLY_EXCLUDED_CAPABILITIES)
        required_readers = ["get_stock", "get_latest_stock_daily_price"]
        excluded_readers = list(QUOTE_ONLY_EXCLUDED_READERS)
        freshness_scope = ["stock_master", "market_daily_price"]
        domain_reader_contract = {
            "quote": ("quote_snapshot", "get_taiwan_stock_quote_depth"),
            "intraday": ("live_intraday_bars", "get_market_intraday_history"),
        }
        for domain in requested_domains:
            contract = domain_reader_contract.get(domain)
            if contract is None:
                continue
            capability, reader = contract
            if capability not in required_capabilities:
                required_capabilities.append(capability)
            if capability in excluded_capabilities:
                excluded_capabilities.remove(capability)
            if reader not in required_readers:
                required_readers.append(reader)
            if reader in excluded_readers:
                excluded_readers.remove(reader)
            if domain not in freshness_scope:
                freshness_scope.append(domain)
        return QueryPlan(
            intent=question_intent,
            intents=intents,
            target_type="tw_stock",
            response_mode=response_mode,
            reader_profile="quote_only",
            payload_level=payload_level,
            diagnostics_level=diagnostics_level,
            required_capabilities=tuple(required_capabilities),
            optional_capabilities=(),
            excluded_capabilities=tuple(excluded_capabilities),
            required_readers=tuple(required_readers),
            excluded_readers=tuple(excluded_readers),
            freshness_scope=tuple(freshness_scope),
            external_refresh_allowed=False,
            requested_domains=requested_domains,
            excluded_domains=excluded_domains,
            matched_positive_terms=positive_terms,
            matched_negative_terms=negative_terms,
            capability_selection_mode=capability_selection_mode,
            selected_action_reason="Quote intent uses the bounded Taiwan quote/intraday read path and excludes unrelated refresh domains.",
            requested_provider=requested_provider,
            strict_provider=strict_provider,
            selection=selection,
            selected_capabilities=tuple(selection["required"]),
            optional_selected_capabilities=tuple(selection["optional"]),
            max_response_bytes=int(selection["max_response_bytes"]),
            realtime_policy=str(selection["realtime_policy"]),
        )

    if (
        scope_type == "stock"
        and question_intent == "broker_branch"
        and _is_pure_fast_path(
            intents=intents,
            requested_domains=request_domains_before_selection,
            selection=selection,
            allowed_intents={"broker_branch", "data_freshness"},
            allowed_domains={"broker_branch", "freshness"},
            allowed_capabilities={
                "target.identity",
                "quote.snapshot",
                "broker_branch.summary",
                "data.freshness",
            },
        )
    ):
        return QueryPlan(
            intent=question_intent,
            intents=intents,
            target_type="tw_stock",
            response_mode=response_mode,
            reader_profile="broker_branch_only",
            payload_level=payload_level,
            diagnostics_level=diagnostics_level,
            required_capabilities=BROKER_BRANCH_REQUIRED_CAPABILITIES,
            optional_capabilities=(),
            excluded_capabilities=BROKER_BRANCH_EXCLUDED_CAPABILITIES,
            required_readers=("get_stock", "get_broker_branch_trade_summary"),
            excluded_readers=BROKER_BRANCH_EXCLUDED_READERS,
            freshness_scope=("stock_master", "broker_branch_trade_daily"),
            external_refresh_allowed=False,
            requested_domains=requested_domains,
            excluded_domains=excluded_domains,
            matched_positive_terms=positive_terms,
            matched_negative_terms=negative_terms,
            capability_selection_mode=capability_selection_mode,
            selected_action_reason="Broker-branch intent explicitly requested broker-branch evidence.",
            requested_provider=requested_provider,
            strict_provider=strict_provider,
            selection=selection,
            selected_capabilities=tuple(selection["required"]),
            optional_selected_capabilities=tuple(selection["optional"]),
            max_response_bytes=int(selection["max_response_bytes"]),
            realtime_policy=str(selection["realtime_policy"]),
        )

    return QueryPlan(
        intent=question_intent,
        intents=intents,
        target_type=scope_type,
        response_mode=response_mode,
        reader_profile="standard",
        payload_level=payload_level,
        diagnostics_level=diagnostics_level,
        required_capabilities=(),
        optional_capabilities=(),
        excluded_capabilities=(),
        required_readers=(),
        excluded_readers=(),
        freshness_scope=(),
        external_refresh_allowed=True,
        requested_domains=requested_domains,
        excluded_domains=excluded_domains,
        matched_positive_terms=positive_terms,
        matched_negative_terms=negative_terms,
        capability_selection_mode=capability_selection_mode,
        selected_action_reason="General intent uses the standard capability planner.",
        requested_provider=requested_provider,
        strict_provider=strict_provider,
        selection=selection,
        selected_capabilities=tuple(selection["required"]),
        optional_selected_capabilities=tuple(selection["optional"]),
        max_response_bytes=int(selection["max_response_bytes"]),
        realtime_policy=str(selection["realtime_policy"]),
    )


def diagnostics_projection(
    *,
    level: str,
    query_plan: dict[str, Any],
    tool_plan: dict[str, Any],
    tool_runs: list[dict[str, Any]],
) -> dict[str, Any]:
    if level == "none":
        return {}
    output: dict[str, Any] = {
        "level": level,
        "query_scope": {
            "intent": query_plan.get("intent"),
            "required_capabilities": query_plan.get("required_capabilities") or [],
            "excluded_capabilities": query_plan.get("excluded_capabilities") or [],
            "freshness_scope": query_plan.get("freshness_scope") or [],
            "requested_domains": query_plan.get("requested_domains") or [],
            "excluded_domains": query_plan.get("excluded_domains") or [],
            "matched_positive_terms": query_plan.get("matched_positive_terms") or [],
            "matched_negative_terms": query_plan.get("matched_negative_terms") or [],
            "selected_action_reason": query_plan.get("selected_action_reason"),
        },
        "tool_run_counts": {
            "total": len(tool_runs),
            "failed": sum(
                1
                for run in tool_runs
                if str(run.get("status") or "").lower()
                in {"error", "failed", "timeout", "blocked"}
            ),
        },
    }
    if level == "debug":
        output["query_plan"] = query_plan
        output["tool_plan"] = tool_plan
        output["tool_runs"] = tool_runs
    return output
