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
    "read_taiwan_bars",
    "read_taiwan_quote_evidence",
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
EVENT_ONLY_PUBLIC_CAPABILITIES = frozenset(
    {
        "events.upcoming",
        "events.history",
        "corporate.actions",
        "regulation.disposition",
        "regulation.trading_restrictions",
    }
)
EVENT_ONLY_EXCLUDED_CAPABILITIES = (
    "live_intraday_bars",
    "daily_ohlc_chart",
    "technical_decision_evidence",
    "tw_chips_and_flows",
    "tw_fundamentals",
    "broker_branch",
    "cross_market_context",
)
EVENT_ONLY_EXCLUDED_READERS = (
    "read_taiwan_latest_daily_evidence",
    *QUOTE_ONLY_EXCLUDED_READERS,
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
    "regulation": (
        "處置股",
        "處置期間",
        "撮合方式",
        "撮合間隔",
        "分盤交易",
        "全額交割",
        "預收款券",
        "交易限制",
        "限制交易",
        "disposition",
        "trading restriction",
    ),
}
SCOPE_DOMAIN_HINTS = {
    "tw_futures": {
        "intraday": (
            "夜盤",
            "夜間盤",
            "after hours",
            "after-hours",
            "after_hours",
            "overnight",
        ),
        "volume": (
            "成交量",
            "交易量",
            "volume",
        ),
    },
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
    "technical.indicators": (
        "rsi",
        "macd",
        "ema",
        "kdj",
        "kd",
        "kd 指標",
        "kd值",
        "kd 值",
        "atr",
        "adx",
        "dmi",
        "mfi",
        "roc",
        "bollinger",
        "布林",
        "pvo",
        "均線數值",
        "均線",
        "moving average",
        "ma5",
        "ma20",
        "ma60",
    ),
    "technical.fibonacci": (
        "fibonacci",
        "fib 位階",
        "費波",
        "斐波",
    ),
    "technical.divergence": (
        "divergence",
        "背離",
    ),
    "technical.breakout": (
        "breakout",
        "突破",
        "假突破",
        "retest",
        "回測突破",
    ),
    "technical.volume_profile": (
        "volume profile",
        "poc",
        "value area",
        "成本區",
        "價值區",
    ),
    "technical.anchored_vwap": (
        "anchored vwap",
        "avwap",
        "錨定 vwap",
        "錨定vwap",
    ),
    "technical.relative_strength": (
        "relative strength",
        "相對強弱",
        "相對大盤",
    ),
    "quote.official_close": (
        "正式收盤價",
        "正式收盤",
        "official close",
        "official closing price",
    ),
    "quote.session_close": (
        "今日收盤",
        "今日的收盤",
        "今天收盤",
        "今天的收盤",
        "當日收盤",
        "盤後收盤",
        "session close",
        "completed session close",
        "today's close",
    ),
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

TW_SCREENING_METRIC_HINTS = {
    "foreign_investor_net_shares": (
        "外資",
        "foreign investor",
        "foreign institutional investor",
    ),
    "investment_trust_net_shares": (
        "投信",
        "investment trust",
    ),
    "margin_balance_change_pct": (
        "融資餘額",
        "融資增減",
        "融資增加",
        "融資減少",
        "margin balance",
    ),
}
TW_SCREENING_ASCENDING_HINTS = (
    "賣超",
    "減少",
    "減幅",
    "下降",
    "bottom",
)
TW_SCREENING_WINDOW_VALUES = frozenset({1, 5, 10, 20})
TW_INTRADAY_SCREENING_METRIC_HINTS = {
    "estimated_trade_value": (
        "成交值排行",
        "成交金額排行",
        "turnover ranking",
    ),
    "cumulative_volume_lots": (
        "成交量排行",
        "爆量排行",
        "volume ranking",
    ),
    "distance_from_high_pct": (
        "高點回落",
        "離高點",
        "pullback from high",
    ),
    "rebound_from_low_pct": (
        "低點反彈",
        "離低點",
        "rebound from low",
    ),
    "five_minute_return": (
        "5分鐘",
        "5 分鐘",
        "五分鐘",
        "急拉",
        "急殺",
        "5-minute",
    ),
    "fifteen_minute_return": (
        "15分鐘",
        "15 分鐘",
        "十五分鐘",
        "15-minute",
    ),
    "intraday_range_pct": (
        "盤中振幅",
        "intraday range",
    ),
    "vwap_deviation_pct": (
        "vwap乖離",
        "vwap 乖離",
        "vwap deviation",
    ),
    "order_book_imbalance": (
        "委買賣失衡",
        "委買賣不平衡",
        "order book imbalance",
    ),
    "change_pct": (
        "盤中漲幅",
        "盤中跌幅",
        "今日漲幅",
        "今日跌幅",
        "漲幅排行",
        "跌幅排行",
        "top gainers",
        "top losers",
    ),
}
TW_HOT_GROUP_HINTS = (
    "熱門族群",
    "強勢族群",
    "族群排行",
    "熱門題材",
    "hot groups",
    "hot sectors",
)
_CHINESE_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "兩": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}

INTENT_DOMAINS = {
    "quote": ("quote",),
    "regulation": ("regulation",),
    "broker_branch": ("broker_branch",),
    "cross_market": ("cross_market",),
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


def _query_domains(
    payload: AiAskRequest,
    question_intent: str,
    *,
    scope_type: str,
) -> tuple[
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

    scoped_domain_hints = SCOPE_DOMAIN_HINTS.get(scope_type, {})
    domain_hints = {
        domain: tuple(
            dict.fromkeys(
                (
                    *DOMAIN_HINTS.get(domain, ()),
                    *scoped_domain_hints.get(domain, ()),
                )
            )
        )
        for domain in dict.fromkeys((*DOMAIN_HINTS, *scoped_domain_hints))
    }
    for domain, hints in domain_hints.items():
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


def _parse_natural_number(value: str) -> int | None:
    normalized = value.strip()
    if not normalized:
        return None
    if normalized.isdigit():
        return int(normalized)
    if any(
        character not in {*_CHINESE_DIGITS, "十", "百"}
        for character in normalized
    ):
        return None

    total = 0
    remainder = normalized
    if "百" in remainder:
        hundred_text, remainder = remainder.split("百", 1)
        hundred = _CHINESE_DIGITS.get(hundred_text or "一")
        if hundred is None:
            return None
        total += hundred * 100
        remainder = remainder.lstrip("零〇")
    if "十" in remainder:
        tens_text, ones_text = remainder.split("十", 1)
        tens = _CHINESE_DIGITS.get(tens_text or "一")
        if tens is None:
            return None
        total += tens * 10
        remainder = ones_text.lstrip("零〇")
    if remainder:
        if len(remainder) != 1 or remainder not in _CHINESE_DIGITS:
            return None
        total += _CHINESE_DIGITS[remainder]
    return total


def _infer_tw_screening_selection(
    payload: AiAskRequest,
    *,
    scope_type: str,
    target_market: str | None,
) -> dict[str, Any] | None:
    normalized_market = str(target_market or "TW").strip().upper()
    if (
        scope_type != "market"
        or normalized_market not in {"TW", "TWSE", "TPEX", "TAIWAN"}
    ):
        return None

    question = payload.question.casefold()
    ranking_requested = bool(
        any(
            hint in question
            for hint in ("排行", "排名", "排行榜", "ranking", "rank by", "top ", "bottom ")
        )
        or re.search(
            r"[前後]\s*(?:\d{1,3}|[零〇一二兩三四五六七八九十百]+)\s*名",
            question,
        )
    )
    if not ranking_requested:
        return None

    metric = next(
        (
            metric_id
            for metric_id, hints in TW_SCREENING_METRIC_HINTS.items()
            if any(hint.casefold() in question for hint in hints)
        ),
        None,
    )
    if metric is None:
        return None

    parameters: dict[str, Any] = {
        "metric": metric,
        "sort_order": (
            "asc"
            if any(hint.casefold() in question for hint in TW_SCREENING_ASCENDING_HINTS)
            or re.search(
                r"後\s*(?:\d{1,3}|[零〇一二兩三四五六七八九十百]+)\s*名",
                question,
            )
            else "desc"
        ),
        "offset": 0,
    }

    if any(term in question for term in ("今日", "今天", "當日", "單日")):
        parameters["window"] = 1
    else:
        window_match = re.search(
            r"(?:近|最近|過去)?\s*"
            r"(?P<window>\d{1,3}|[零〇一二兩三四五六七八九十百]+)"
            r"\s*(?:個)?(?:交易)?(?:日|天)",
            question,
        )
        if window_match:
            window = _parse_natural_number(window_match.group("window"))
            if window not in TW_SCREENING_WINDOW_VALUES:
                raise ValueError(
                    "Taiwan screening window inferred from the question must be "
                    "one of 1, 5, 10, or 20 trading days."
                )
            parameters["window"] = window

    limit_match = re.search(
        r"(?:前|後)\s*"
        r"(?P<limit>\d{1,3}|[零〇一二兩三四五六七八九十百]+)"
        r"\s*名",
        question,
    ) or re.search(
        r"(?:top|bottom)\s*(?P<limit>\d{1,3})",
        question,
    )
    if limit_match:
        limit = _parse_natural_number(limit_match.group("limit"))
        if limit is None or not 1 <= limit <= 200:
            raise ValueError(
                "Taiwan screening result limit inferred from the question must "
                "be between 1 and 200."
            )
        parameters["limit"] = limit

    raw_parameters = (
        payload.selection.get("parameters")
        if isinstance(payload.selection, dict)
        and isinstance(payload.selection.get("parameters"), dict)
        else {}
    )
    explicit_ranking_parameters = raw_parameters.get("screening.ranking")
    if isinstance(explicit_ranking_parameters, dict):
        parameters.update(explicit_ranking_parameters)

    return {
        "include": ["screening.ranking", "screening.coverage"],
        "parameters": {
            **raw_parameters,
            "screening.ranking": parameters,
        },
    }


def _infer_tw_intraday_screening_selection(
    payload: AiAskRequest,
    *,
    scope_type: str,
    target_market: str | None,
) -> dict[str, Any] | None:
    normalized_market = str(target_market or "TW").strip().upper()
    if (
        scope_type != "market"
        or normalized_market not in {"TW", "TWSE", "TPEX", "TAIWAN"}
    ):
        return None

    question = payload.question.casefold()
    hot_groups_requested = any(
        hint.casefold() in question for hint in TW_HOT_GROUP_HINTS
    )
    metric = next(
        (
            metric_id
            for metric_id, hints in TW_INTRADAY_SCREENING_METRIC_HINTS.items()
            if any(hint.casefold() in question for hint in hints)
        ),
        None,
    )
    intraday_ranking_requested = metric is not None and any(
        hint in question
        for hint in (
            "排行",
            "前",
            "後",
            "最多",
            "最強",
            "最弱",
            "急拉",
            "急殺",
            "ranking",
            "top ",
            "bottom ",
        )
    )
    if not hot_groups_requested and not intraday_ranking_requested:
        return None

    limit = 20
    limit_match = re.search(
        r"(?:前|後)\s*(?P<limit>\d{1,3})\s*(?:名|檔)?",
        question,
    ) or re.search(r"(?:top|bottom)\s*(?P<limit>\d{1,3})", question)
    if limit_match:
        limit = int(limit_match.group("limit"))
        if not 1 <= limit <= 200:
            raise ValueError(
                "Taiwan intraday screening result limit inferred from the "
                "question must be between 1 and 200."
            )

    raw_parameters = (
        payload.selection.get("parameters")
        if isinstance(payload.selection, dict)
        and isinstance(payload.selection.get("parameters"), dict)
        else {}
    )
    include: list[str] = []
    parameters = dict(raw_parameters)
    if intraday_ranking_requested:
        include.append("screening.intraday")
        intraday_parameters = {
            "metric": metric or "change_pct",
            "sort_order": (
                "asc"
                if any(
                    hint in question
                    for hint in (
                        "跌幅",
                        "跌最多",
                        "最弱",
                        "急殺",
                        "高點回落",
                        "bottom ",
                    )
                )
                else "desc"
            ),
            "limit": limit,
            "offset": 0,
        }
        explicit_parameters = raw_parameters.get("screening.intraday")
        if isinstance(explicit_parameters, dict):
            intraday_parameters.update(explicit_parameters)
        parameters["screening.intraday"] = intraday_parameters
    if hot_groups_requested:
        include.append("market.hot_groups")
        hot_group_parameters = {"limit": min(limit, 100)}
        explicit_parameters = raw_parameters.get("market.hot_groups")
        if isinstance(explicit_parameters, dict):
            hot_group_parameters.update(explicit_parameters)
        parameters["market.hot_groups"] = hot_group_parameters

    return {
        "include": include,
        "parameters": parameters,
    }


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
    target_market: str | None = None,
) -> QueryPlan:
    response_mode = canonical_response_mode(effective_mode)
    payload_level = normalized_payload_level(payload)
    diagnostics_level = payload.diagnostics_level
    params = payload.market_data_params if isinstance(payload.market_data_params, dict) else {}
    requested_domains, excluded_domains, positive_terms, negative_terms = _query_domains(
        payload,
        question_intent,
        scope_type=scope_type,
    )
    raw_selection = payload.selection if isinstance(payload.selection, dict) else {}
    has_explicit_capability_selection = any(
        key in raw_selection
        for key in ("required", "include", "optional", "exclude")
    )
    inferred_screening_selection = (
        None
        if has_explicit_capability_selection
        else (
            _infer_tw_intraday_screening_selection(
                payload,
                scope_type=scope_type,
                target_market=target_market,
            )
            or _infer_tw_screening_selection(
                payload,
                scope_type=scope_type,
                target_market=target_market,
            )
        )
    )
    if has_explicit_capability_selection:
        requested_capabilities: tuple[str, ...] = ()
        excluded_selection_capabilities: tuple[str, ...] = ()
        capability_selection_mode = "explicit"
    elif inferred_screening_selection is not None:
        requested_capabilities = ()
        excluded_selection_capabilities = ()
        capability_selection_mode = "inferred"
        requested_domains = tuple(
            dict.fromkeys(
                (
                    *(
                        domain
                        for domain in requested_domains
                        if domain not in {"chips", "sample_ranking"}
                    ),
                    "screening",
                )
            )
        )
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
    elif inferred_screening_selection is not None:
        selection_input = {
            **raw_selection,
            **inferred_screening_selection,
        }
    selection = capability_contract.normalize_selection(
        selection=selection_input,
        output=payload.output,
        realtime_policy=payload.realtime_policy,
        payload_level=payload_level,
        scope_type=scope_type,
        question_intent=question_intent,
        target_market=target_market,
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

    selected_capability_set = {
        *selection.get("required", ()),
        *selection.get("optional", ()),
    }
    if (
        scope_type == "stock"
        and (
            has_explicit_capability_selection
            or question_intent == "regulation"
        )
        and bool(
            selected_capability_set & EVENT_ONLY_PUBLIC_CAPABILITIES
        )
        and selected_capability_set
        <= {
            "target.identity",
            "data.freshness",
            *EVENT_ONLY_PUBLIC_CAPABILITIES,
        }
    ):
        event_required_readers = ["get_stock"]
        event_required_capabilities = ["stock_master"]
        if "events.upcoming" in selected_capability_set:
            event_required_readers.append(
                "get_taiwan_stock_event_summary"
            )
            event_required_capabilities.append(
                "taiwan_corporate_events"
            )
        if selected_capability_set & {
            "events.history",
            "corporate.actions",
        }:
            event_required_readers.append(
                "get_taiwan_stock_event_history"
            )
            event_required_capabilities.append(
                "taiwan_corporate_event_history"
            )
        if selected_capability_set & {
            "regulation.disposition",
            "regulation.trading_restrictions",
        }:
            event_required_readers.append(
                "get_taiwan_disposition_status"
            )
            event_required_capabilities.append(
                "taiwan_disposition"
            )
        return QueryPlan(
            intent=question_intent,
            intents=intents,
            target_type="tw_stock",
            response_mode=response_mode,
            reader_profile="event_only",
            payload_level=payload_level,
            diagnostics_level=diagnostics_level,
            required_capabilities=tuple(event_required_capabilities),
            optional_capabilities=(),
            excluded_capabilities=EVENT_ONLY_EXCLUDED_CAPABILITIES,
            required_readers=tuple(event_required_readers),
            excluded_readers=EVENT_ONLY_EXCLUDED_READERS,
            freshness_scope=tuple(event_required_capabilities),
            external_refresh_allowed=False,
            requested_domains=requested_domains,
            excluded_domains=excluded_domains,
            matched_positive_terms=positive_terms,
            matched_negative_terms=negative_terms,
            capability_selection_mode=capability_selection_mode,
            selected_action_reason=(
                "Explicit Taiwan event/regulation capabilities use the "
                "cache-only stock event reader and exclude price, chart, "
                "technical, chip, fundamental, and broker-branch domains."
            ),
            requested_provider=requested_provider,
            strict_provider=strict_provider,
            selection=selection,
            selected_capabilities=tuple(selection["required"]),
            optional_selected_capabilities=tuple(selection["optional"]),
            max_response_bytes=int(selection["max_response_bytes"]),
            realtime_policy=str(selection["realtime_policy"]),
        )

    profile_only_selection = bool(
        scope_type == "stock"
        and has_explicit_capability_selection
        and selected_capability_set
        <= {
            "target.identity",
            "company.profile",
            "data.freshness",
        }
        and "company.profile" in selected_capability_set
    )
    if (
        scope_type == "stock"
        and (
            profile_only_selection
            or (
                question_intent == "quote"
                and _is_pure_fast_path(
                    intents=intents,
                    requested_domains=request_domains_before_selection,
                    selection=selection,
                    allowed_intents={"quote", "data_freshness"},
                    allowed_domains={"quote", "intraday", "freshness"},
                    allowed_capabilities={
                        "target.identity",
                        "quote.snapshot",
                        "quote.session_close",
                        "quote.official_close",
                        "intraday.bars",
                        "data.freshness",
                    },
                )
            )
        )
    ):
        required_capabilities = list(QUOTE_ONLY_REQUIRED_CAPABILITIES)
        excluded_capabilities = list(QUOTE_ONLY_EXCLUDED_CAPABILITIES)
        required_readers = ["get_stock", "read_taiwan_latest_daily_evidence"]
        excluded_readers = list(QUOTE_ONLY_EXCLUDED_READERS)
        freshness_scope = ["stock_master", "market_daily_price"]
        domain_reader_contract = {
            "quote": ("quote_snapshot", "read_taiwan_quote_evidence"),
            "intraday": ("live_intraday_bars", "read_taiwan_bars"),
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

    identity_only_selection = bool(
        scope_type == "stock"
        and has_explicit_capability_selection
        and "target.identity" in selected_capability_set
        and selected_capability_set
        <= {"target.identity", "data.freshness", "news.events"}
    )
    if identity_only_selection:
        return QueryPlan(
            intent=question_intent,
            intents=intents,
            target_type="tw_stock",
            response_mode=response_mode,
            reader_profile="identity_only",
            payload_level=payload_level,
            diagnostics_level=diagnostics_level,
            required_capabilities=("stock_master",),
            optional_capabilities=(),
            excluded_capabilities=(),
            required_readers=("get_stock",),
            excluded_readers=(
                "list_stock_ohlc_chart_data",
                "read_cross_market_context",
                "read_market_chips_context",
                "build_stock_technical_report",
                "get_broker_branch_trade_summary",
                "read_taiwan_source_health",
                "read_fundamentals",
            ),
            freshness_scope=("stock_master",),
            external_refresh_allowed=False,
            requested_domains=requested_domains,
            excluded_domains=excluded_domains,
            matched_positive_terms=positive_terms,
            matched_negative_terms=negative_terms,
            capability_selection_mode=capability_selection_mode,
            selected_action_reason=(
                "Explicit Taiwan identity selection executes only the stock "
                "master reader; selected external evidence is attached by its "
                "own outward projection."
            ),
            requested_provider=requested_provider,
            strict_provider=strict_provider,
            selection=selection,
            selected_capabilities=tuple(selection["required"]),
            optional_selected_capabilities=tuple(selection["optional"]),
            max_response_bytes=int(selection["max_response_bytes"]),
            realtime_policy=str(selection["realtime_policy"]),
        )

    technical_capabilities = {
        "technical.structure",
        "technical.indicators",
        "technical.swings",
        "technical.fibonacci",
        "technical.divergence",
        "technical.breakout",
        "technical.volume_profile",
        "technical.anchored_vwap",
        "technical.relative_strength",
    }
    technical_only_selection = bool(
        scope_type == "stock"
        and has_explicit_capability_selection
        and bool(selected_capability_set & technical_capabilities)
        and selected_capability_set
        <= {
            "target.identity",
            "daily.ohlcv",
            "data.freshness",
            *technical_capabilities,
        }
    )
    if technical_only_selection:
        return QueryPlan(
            intent=question_intent,
            intents=intents,
            target_type="tw_stock",
            response_mode=response_mode,
            reader_profile="technical_only",
            payload_level=payload_level,
            diagnostics_level=diagnostics_level,
            required_capabilities=("stock_master", "market_daily_price"),
            optional_capabilities=(),
            excluded_capabilities=(),
            required_readers=(
                "get_stock",
                "list_stock_ohlc_chart_data",
                "build_stock_technical_report",
                "build_tw_stock_technical_evidence",
            ),
            excluded_readers=(
                "read_cross_market_context",
                "read_market_chips_context",
                "get_broker_branch_trade_summary",
                "read_taiwan_source_health",
                "read_fundamentals",
            ),
            freshness_scope=("stock_master", "market_daily_price"),
            external_refresh_allowed=False,
            requested_domains=requested_domains,
            excluded_domains=excluded_domains,
            matched_positive_terms=positive_terms,
            matched_negative_terms=negative_terms,
            capability_selection_mode=capability_selection_mode,
            selected_action_reason=(
                "Explicit Taiwan technical selection executes only identity, "
                "released daily bars, technical derivation, and freshness dependencies."
            ),
            requested_provider=requested_provider,
            strict_provider=strict_provider,
            selection=selection,
            selected_capabilities=tuple(selection["required"]),
            optional_selected_capabilities=tuple(selection["optional"]),
            max_response_bytes=int(selection["max_response_bytes"]),
            realtime_policy=str(selection["realtime_policy"]),
        )

    daily_only_selection = bool(
        scope_type == "stock"
        and has_explicit_capability_selection
        and "daily.ohlcv" in selected_capability_set
        and selected_capability_set
        <= {
            "target.identity",
            "daily.ohlcv",
            "data.freshness",
        }
    )
    if daily_only_selection:
        return QueryPlan(
            intent=question_intent,
            intents=intents,
            target_type="tw_stock",
            response_mode=response_mode,
            reader_profile="daily_only",
            payload_level=payload_level,
            diagnostics_level=diagnostics_level,
            required_capabilities=("stock_master", "market_daily_price"),
            optional_capabilities=(),
            excluded_capabilities=(),
            required_readers=("get_stock", "list_stock_ohlc_chart_data"),
            excluded_readers=(
                "read_cross_market_context",
                "read_market_chips_context",
                "build_stock_technical_report",
                "get_broker_branch_trade_summary",
                "read_taiwan_source_health",
                "read_fundamentals",
            ),
            freshness_scope=("stock_master", "market_daily_price"),
            external_refresh_allowed=False,
            requested_domains=requested_domains,
            excluded_domains=excluded_domains,
            matched_positive_terms=positive_terms,
            matched_negative_terms=negative_terms,
            capability_selection_mode=capability_selection_mode,
            selected_action_reason=(
                "Explicit Taiwan daily selection executes only identity, "
                "canonical daily bars, and freshness dependencies."
            ),
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
        external_refresh_allowed=inferred_screening_selection is None,
        requested_domains=requested_domains,
        excluded_domains=excluded_domains,
        matched_positive_terms=positive_terms,
        matched_negative_terms=negative_terms,
        capability_selection_mode=capability_selection_mode,
        selected_action_reason=(
            "A Taiwan market ranking question uses the cache-only screening "
            "capabilities with backend-validated typed parameters."
            if inferred_screening_selection is not None
            else "General intent uses the standard capability planner."
        ),
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
