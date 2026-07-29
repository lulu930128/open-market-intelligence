from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any

from app.ai.market_date_request import requested_us_trade_date


REPORT_HINTS = (
    "ai report",
    "llm",
    "report",
    "generate report",
    "formal report",
    "正式報告",
    "產生報告",
    "生成報告",
    "研究報告",
    "AI報告",
)
ANALYSIS_HINTS = (
    "analysis",
    "analyze",
    "interpret",
    "llm brief",
    "分析",
    "短評",
    "怎麼看",
    "看法",
    "解讀",
    "重點",
    "風險",
)
ENTRY_DECISION_HINTS = (
    "buy",
    "entry",
    "enter",
    "long",
    "accumulate",
    "買嗎",
    "該買",
    "可以買",
    "能買",
    "能不能買",
    "可不可以買",
    "要買",
    "要不要買",
    "適合買",
    "買入",
    "買進",
    "進場",
    "可以進",
    "適合進",
    "追嗎",
    "能追",
    "能不能追",
    "可以追",
    "該追",
    "要不要追",
    "追高",
    "追價",
    "追會不會",
    "加碼",
    "佈局",
    "布局",
    "值得買",
    "進嗎",
    "抄底",
    "低接",
    "可以接",
    "能不能接",
    "可不可以接",
    "拉回",
    "回檔到",
    "買點",
    "進一點",
    "分批買",
    "建倉",
    "哪裡買",
    "哪邊買",
    "哪裡接",
    "哪邊接",
    "接回",
    "回檔買",
    "回測買",
    "撿便宜",
)
EXIT_DECISION_HINTS = (
    "sell",
    "exit",
    "trim",
    "take profit",
    "stop loss",
    "賣嗎",
    "該賣",
    "要賣",
    "停利",
    "停損",
    "止盈",
    "止損",
    "出場",
    "減碼",
    "退場",
    "認賠",
    "砍掉",
    "砍倉",
    "砍",
    "要不要賣",
    "該不該賣",
    "續抱",
    "抱嗎",
)
EXIT_ACTION_HINTS = (
    "sell",
    "exit",
    "trim",
    "take profit",
    "stop loss",
    "賣嗎",
    "該賣",
    "要賣",
    "停利",
    "停損",
    "止盈",
    "止損",
    "出場",
    "減碼",
    "退場",
    "認賠",
    "砍掉",
    "砍倉",
    "砍",
    "要不要賣",
    "該不該賣",
)
RISK_DECISION_HINTS = (
    "risk",
    "downside",
    "hedge",
    "short",
    "風險",
    "危險",
    "崩",
    "風控",
    "跌破",
    "跌到多少",
    "守哪",
    "破哪",
    "避險",
    "空方",
    "轉弱",
    "失效",
)
RISK_PRIORITY_HINTS = (
    "risk",
    "downside",
    "hedge",
    "風險",
    "危險",
    "風控",
    "跌破",
    "守哪",
    "破哪",
    "防守",
    "轉弱",
    "失效",
)
TREND_VIEW_HINTS = (
    "trend",
    "view",
    "direction",
    "走勢",
    "趨勢",
    "多空",
    "怎麼看",
    "看法",
    "方向",
    "強弱",
    "還強嗎",
    "弱嗎",
    "強嗎",
    "短線",
    "波段",
)
TREND_ANALYSIS_REQUEST_HINTS = (
    "trend",
    "direction",
    "走勢",
    "趨勢",
    "多空",
    "方向",
    "強弱",
    "還強嗎",
    "弱嗎",
    "強嗎",
    "波段",
    "中線",
    "中短線",
)
TREND_ANALYSIS_PRIORITY_HINTS = (
    "中線波段",
    "波段角度",
    "支撐壓力",
)
TREND_ANALYSIS_CONTEXT_HINTS = (
    "日k",
    "日K",
    "週k",
    "週K",
    "周k",
    "周K",
    "均線",
    "動能",
    "量能",
    "籌碼",
    "營收",
    "相對市場",
    "支撐",
    "壓力",
    "觀察條件",
)
UI_TREND_VIEW_INTENTS = {"swing"}
UI_RISK_INTENTS = {"risk"}
POSITION_CONTEXT_HINTS = (
    "position",
    "holding",
    "entry price",
    "cost basis",
    "部位",
    "倉位",
    "持股",
    "手上有",
    "買在",
    "買進",
    "成本",
    "持有",
    "均價",
    "套牢",
    "套住",
    "停損",
    "止損",
    "停利",
    "止盈",
    "出場",
    "減碼",
    "續抱",
)
STOP_LOSS_HINTS = (
    "stop loss",
    "停損",
    "止損",
    "砍掉",
    "砍倉",
    "砍",
)
TAKE_PROFIT_HINTS = (
    "take profit",
    "停利",
    "止盈",
)
HOLD_DECISION_HINTS = (
    "hold",
    "續抱",
    "抱嗎",
    "還能抱",
    "該抱",
)
POSITION_ENTRY_PRICE_PATTERNS = (
    re.compile(
        r"(?:買在|買進(?:在|價)?|進場(?:在|價)?|成本(?:價)?(?:是|在|約|大概)?|"
        r"持有成本(?:是|在)?|均價(?:是|在)?|entry(?: price)?(?: at| is)?|"
        r"cost(?: basis)?(?: at| is)?)\s*([0-9][0-9,]*(?:\.[0-9]+)?)",
        flags=re.IGNORECASE,
    ),
    re.compile(
        r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*(?:元|塊)?\s*(?:買的|買進|進場|成本)",
        flags=re.IGNORECASE,
    ),
)
FRESHNESS_HINTS = (
    "freshness",
    "coverage",
    "更新狀態",
    "資料日期",
    "資料新鮮",
    "資料更新",
    "更新到",
    "缺資料",
)
BROKER_BRANCH_QUERY_HINTS = (
    "broker branch",
    "branch flow",
    "分點",
    "券商分點",
    "主要買賣方",
    "分點買賣方",
    "主力買賣",
)
QUOTE_ONLY_HINTS = (
    "latest quote",
    "latest price",
    "closing price",
    "close price",
    "最新報價",
    "最新股價",
    "最新價格",
    "最新收盤價",
    "即時報價",
    "現價",
    "分k",
    "分 K",
    "收盤價多少",
    "股價多少",
    "現在幾塊",
    "現在多少錢",
)
NEGATION_TERMS = (
    "不查",
    "不刷新",
    "不需要",
    "不要",
    "排除",
    "without",
    "except",
)
MARKET_BREADTH_QUERY_HINTS = (
    "market breadth",
    "advance decline",
    "advancers",
    "decliners",
    "市場廣度",
    "漲跌家數",
    "上漲家數",
    "下跌家數",
    "漲停家數",
    "跌停家數",
    "盤面強弱",
)
INTRADAY_HINTS = (
    "intraday",
    "live",
    "realtime",
    "real-time",
    "today",
    "now",
    "opening",
    "盤中",
    "即時",
    "今日",
    "今天",
    "開盤",
    "夜盤",
    "最新",
)
SHORT_HORIZON_HINTS = (
    "short",
    "daily",
    "day trade",
    "next session",
    "日k",
    "日K",
    "短線",
    "明天",
    "隔日",
    "這幾天",
    "1到5天",
    "1-5天",
)
SWING_HORIZON_HINTS = (
    "swing",
    "weekly",
    "week",
    "週k",
    "週K",
    "周k",
    "周K",
    "波段",
    "中短線",
    "這幾週",
    "幾週",
)
LONG_HORIZON_HINTS = (
    "long",
    "monthly",
    "month",
    "valuation",
    "fundamental",
    "月k",
    "月K",
    "長線",
    "投資",
    "基本面",
    "估值",
    "營收",
    "財報",
    "配息",
)
WATCHLIST_HINTS = (
    "watchlist",
    "group",
    "sector",
    "群體",
    "群組",
    "族群",
    "分組",
    "自選",
)
MARKET_HINTS = (
    "market",
    "breadth",
    "大盤",
    "盤面",
    "市場",
    "漲跌家數",
)
ADR_HINTS = (
    "adr",
    "nyse",
    "tsm adr",
    "美股台積電",
    "美股台積",
)
US_SYMBOL_CONTEXT_HINTS = (
    "us stock",
    "u.s. stock",
    "american stock",
    "ticker",
    "symbol",
    "nasdaq",
    "nyse",
    "amex",
    "arca",
    "美股",
    "美國股票",
    "美國上市",
    "那斯達克",
    "納斯達克",
    "紐交所",
    "美國個股",
)
STOCK_REFERENCE_HINTS = (
    "stock",
    "company",
    "ticker",
    "個股",
    "股票",
    "這檔",
    "這支",
    "這家公司",
)
TAIWAN_TSMC_ALIASES = (
    "台積電",
    "台積",
    "tsmc",
)
US_SYMBOL_STOPWORDS = {
    "A",
    "AI",
    "ALL",
    "AND",
    "ANALYZE",
    "ADR",
    "CAN",
    "CEO",
    "ETF",
    "FOR",
    "GENERATE",
    "HOW",
    "IT",
    "LATEST",
    "LLM",
    "LOOK",
    "MAKE",
    "NOW",
    "OK",
    "ON",
    "OR",
    "PLEASE",
    "REPORT",
    "RISK",
    "STOCK",
    "THAT",
    "THE",
    "THIS",
    "TODAY",
    "US",
    "USA",
    "VIEW",
    "WHAT",
    "YOU",
}
US_EXCHANGE_SYMBOL_PATTERN = re.compile(
    r"\b(?:NASDAQ|NYSE|AMEX|NYSEARCA|ARCA|CBOE|OTC|OTCMKTS)[:：]\s*([A-Za-z][A-Za-z0-9.$-]{0,15})\b",
    flags=re.IGNORECASE,
)
US_DOLLAR_SYMBOL_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_$.-])\$([A-Za-z][A-Za-z0-9.$-]{0,15})(?![A-Za-z0-9.$-])"
)
US_PLAIN_SYMBOL_PATTERN = re.compile(
    r"(?<![A-Za-z0-9.$-])([A-Za-z][A-Za-z0-9.$-]{0,15})(?![A-Za-z0-9.$-])"
)

VALID_ANALYSIS_HORIZONS = {"auto", "intraday", "short", "swing", "long"}
POSITION_RISK_TOPICS = {"stop_loss", "take_profit", "exit", "hold", "risk", "position"}


@dataclass(frozen=True)
class PositionContext:
    has_position_context: bool
    entry_price: float | None
    entry_price_source: str | None
    decision_topic: str
    position_side: str | None
    kind: str = "position_context"

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class QuestionUnderstanding:
    question: str
    intent: str
    intent_confidence: str
    position_context: PositionContext
    analysis_horizon: str
    analysis_horizon_source: str
    intents: tuple[str, ...] = ()
    matched_hints: tuple[str, ...] = ()

    def as_policy_payload(self) -> dict[str, object]:
        return {
            "intent": self.intent,
            "intents": list(self.intents),
            "intent_confidence": self.intent_confidence,
            "position_context": self.position_context.as_dict(),
            "analysis_horizon": self.analysis_horizon,
            "analysis_horizon_source": self.analysis_horizon_source,
            "matched_hints": list(self.matched_hints),
        }


def contains_hint(question: str, hints: tuple[str, ...]) -> bool:
    lowered = question.lower()
    return any(hint.lower() in lowered for hint in hints)


def matched_hints(question: str, hints: tuple[str, ...], *, limit: int = 6) -> tuple[str, ...]:
    lowered = question.lower()
    matches = [hint for hint in hints if hint.lower() in lowered]
    return tuple(matches[:limit])


def conversation_ui_ask_intent(conversation_context: dict[str, Any] | None) -> str | None:
    if not isinstance(conversation_context, dict):
        return None

    ui_context = conversation_context.get("ui_context")
    if not isinstance(ui_context, dict):
        return None

    intent = ui_context.get("ask_intent")
    if not isinstance(intent, str):
        return None

    normalized = intent.strip().lower()
    return normalized or None


def looks_like_analysis_request(question: str) -> bool:
    return contains_hint(question, ANALYSIS_HINTS) or contains_hint(
        question,
        ("結論", "分析目前標的", "分析目前目標"),
    )


def looks_like_structured_trend_prompt(question: str) -> bool:
    if not looks_like_analysis_request(question):
        return False
    if contains_hint(question, TREND_ANALYSIS_PRIORITY_HINTS):
        return True
    if not contains_hint(question, TREND_ANALYSIS_REQUEST_HINTS):
        return False
    return len(matched_hints(question, TREND_ANALYSIS_CONTEXT_HINTS, limit=6)) >= 2


def parse_number_token(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        number = float(value.replace(",", ""))
    except ValueError:
        return None
    if number <= 0 or number != number:
        return None
    return number


def extract_position_entry_price(question: str) -> tuple[float | None, str | None]:
    for pattern in POSITION_ENTRY_PRICE_PATTERNS:
        match = pattern.search(question)
        if not match:
            continue
        price = parse_number_token(match.group(1))
        if price is not None:
            return price, match.group(0)
    return None, None


def infer_position_context(question: str) -> PositionContext:
    entry_price, entry_price_source = extract_position_entry_price(question)
    has_position_context = entry_price is not None or contains_hint(question, POSITION_CONTEXT_HINTS)

    if contains_hint(question, STOP_LOSS_HINTS):
        decision_topic = "stop_loss"
    elif contains_hint(question, TAKE_PROFIT_HINTS):
        decision_topic = "take_profit"
    elif contains_hint(question, EXIT_ACTION_HINTS):
        decision_topic = "exit"
    elif contains_hint(question, HOLD_DECISION_HINTS):
        decision_topic = "hold"
    elif contains_hint(question, EXIT_DECISION_HINTS):
        decision_topic = "exit"
    elif contains_hint(question, ENTRY_DECISION_HINTS):
        decision_topic = "entry"
    elif contains_hint(question, RISK_DECISION_HINTS):
        decision_topic = "risk"
    else:
        decision_topic = "position" if has_position_context else "none"

    return PositionContext(
        has_position_context=has_position_context,
        entry_price=entry_price,
        entry_price_source=entry_price_source,
        decision_topic=decision_topic,
        position_side="long" if has_position_context else None,
    )


def infer_question_intent(
    question: str,
    *,
    conversation_context: dict[str, Any] | None = None,
) -> str:
    position_context = infer_position_context(question)
    ui_ask_intent = conversation_ui_ask_intent(conversation_context)
    structured_trend_prompt = looks_like_structured_trend_prompt(question)
    if (
        position_context.has_position_context
        and position_context.decision_topic in POSITION_RISK_TOPICS
    ):
        return "position_risk_decision"
    if structured_trend_prompt:
        return "trend_view"
    if ui_ask_intent in UI_TREND_VIEW_INTENTS and looks_like_analysis_request(question):
        return "trend_view"
    if ui_ask_intent in UI_RISK_INTENTS and looks_like_analysis_request(question):
        return "risk_check"
    if contains_hint(question, BROKER_BRANCH_QUERY_HINTS) and not any(
        re.search(
            rf"{re.escape(negation)}[^，,。；;!?]{{0,40}}{re.escape(hint)}",
            question,
            flags=re.IGNORECASE,
        )
        for negation in NEGATION_TERMS
        for hint in BROKER_BRANCH_QUERY_HINTS
    ):
        return "broker_branch"
    if contains_hint(question, MARKET_BREADTH_QUERY_HINTS):
        return "market_breadth"
    if (
        contains_hint(question, QUOTE_ONLY_HINTS)
        or requested_us_trade_date(question) is not None
    ):
        return "quote"
    if contains_hint(question, RISK_PRIORITY_HINTS):
        return "risk_check"
    if contains_hint(question, ENTRY_DECISION_HINTS):
        return "entry_decision"
    if contains_hint(question, EXIT_DECISION_HINTS):
        return "exit_decision"
    if contains_hint(question, RISK_DECISION_HINTS):
        return "risk_check"
    if contains_hint(question, TREND_VIEW_HINTS):
        return "trend_view"
    if contains_hint(question, FRESHNESS_HINTS):
        if looks_like_analysis_request(question):
            return "general"
        return "data_freshness"
    return "general"


def infer_question_intents(
    question: str,
    *,
    conversation_context: dict[str, Any] | None = None,
) -> tuple[str, ...]:
    primary = infer_question_intent(
        question,
        conversation_context=conversation_context,
    )
    intents = [primary]
    intent_hints = (
        ("broker_branch", BROKER_BRANCH_QUERY_HINTS),
        ("market_breadth", MARKET_BREADTH_QUERY_HINTS),
        ("quote", QUOTE_ONLY_HINTS),
        ("risk_check", (*RISK_PRIORITY_HINTS, *RISK_DECISION_HINTS)),
        ("entry_decision", ENTRY_DECISION_HINTS),
        ("exit_decision", EXIT_DECISION_HINTS),
        ("trend_view", TREND_ANALYSIS_REQUEST_HINTS),
        ("data_freshness", FRESHNESS_HINTS),
    )
    for intent, hints in intent_hints:
        if (
            intent in {"risk_check", "entry_decision", "exit_decision"}
            and intent != primary
            and not looks_like_analysis_request(question)
        ):
            continue
        if intent != primary and contains_hint(question, hints):
            intents.append(intent)
    return tuple(dict.fromkeys(intents))


def normalize_analysis_horizon(value: str | None) -> str:
    normalized = (value or "auto").strip().lower()
    if normalized in {"today", "live", "realtime", "real-time", "now"}:
        return "intraday"
    if normalized in {"daily", "day", "short_term", "short-term"}:
        return "short"
    if normalized in {"weekly", "medium", "medium_short", "medium-short"}:
        return "swing"
    if normalized in {"monthly", "fundamental", "investment"}:
        return "long"
    return normalized


def infer_analysis_horizon(
    *,
    question: str,
    requested_horizon: str | None = None,
    strategy_profile: str | None = None,
) -> tuple[str, str]:
    requested = normalize_analysis_horizon(requested_horizon)
    if requested != "auto":
        return requested, "request"

    if contains_hint(question, INTRADAY_HINTS):
        return "intraday", "question_intraday_hint"
    if contains_hint(question, LONG_HORIZON_HINTS):
        return "long", "question_long_hint"
    if contains_hint(question, SWING_HORIZON_HINTS):
        return "swing", "question_swing_hint"
    if contains_hint(question, SHORT_HORIZON_HINTS):
        return "short", "question_short_hint"

    if strategy_profile in {"fundamentals_growth", "dividend_value"}:
        return "long", "strategy_profile"
    if strategy_profile == "technical_swing":
        return "swing", "strategy_profile"

    return "swing", "default"


def include_tw_intraday(
    *,
    question: str,
    requested_horizon: str | None,
    strategy_profile: str | None,
    allow_external_fetch: bool,
) -> bool:
    if not allow_external_fetch:
        return False

    horizon, _ = infer_analysis_horizon(
        question=question,
        requested_horizon=requested_horizon,
        strategy_profile=strategy_profile,
    )
    return horizon == "intraday" or contains_hint(question, INTRADAY_HINTS)


def understand_question(
    *,
    question: str,
    requested_horizon: str | None = None,
    strategy_profile: str | None = None,
    conversation_context: dict[str, Any] | None = None,
) -> QuestionUnderstanding:
    position_context = infer_position_context(question)
    intents = infer_question_intents(
        question,
        conversation_context=conversation_context,
    )
    intent = intents[0]
    horizon, horizon_source = infer_analysis_horizon(
        question=question,
        requested_horizon=requested_horizon,
        strategy_profile=strategy_profile,
    )
    hint_matches: list[str] = []
    for hints in (
        ENTRY_DECISION_HINTS,
        EXIT_DECISION_HINTS,
        RISK_DECISION_HINTS,
        TREND_VIEW_HINTS,
        POSITION_CONTEXT_HINTS,
        FRESHNESS_HINTS,
        BROKER_BRANCH_QUERY_HINTS,
    ):
        hint_matches.extend(matched_hints(question, hints))

    confidence = "high" if intent != "general" else "medium"
    if intent == "general" and not hint_matches:
        confidence = "low"

    return QuestionUnderstanding(
        question=question,
        intent=intent,
        intent_confidence=confidence,
        position_context=position_context,
        analysis_horizon=horizon,
        analysis_horizon_source=horizon_source,
        intents=intents,
        matched_hints=tuple(dict.fromkeys(hint_matches))[:8],
    )
