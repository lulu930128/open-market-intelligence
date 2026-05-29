from dataclasses import dataclass


@dataclass(frozen=True)
class StrategyProfile:
    key: str
    label: str
    description: str
    focus_points: tuple[str, ...]
    risk_notes: tuple[str, ...]


STRATEGY_PROFILES: dict[str, StrategyProfile] = {
    "balanced": StrategyProfile(
        key="balanced",
        label="Balanced research",
        description="Combine price, technical signals, chip flow, revenue, and financials.",
        focus_points=(
            "Start from data freshness and missing coverage.",
            "Compare price action with volume and rule-based signals.",
            "Use chip flow, revenue, and financials as confirmation or contradiction.",
            "Separate observable facts from interpretation.",
        ),
        risk_notes=(
            "Do not treat one indicator as a standalone decision.",
            "Call out stale or partial data before drawing conclusions.",
        ),
    ),
    "technical_swing": StrategyProfile(
        key="technical_swing",
        label="Technical swing",
        description="Prioritize price trend, momentum, volume, and watchlist ranking.",
        focus_points=(
            "Prioritize OHLC history, latest change, volume, and signals.",
            "Look for momentum continuation, reversal, and overextension.",
            "Use fundamentals only as context, not as the first filter.",
        ),
        risk_notes=(
            "Momentum signals can fail quickly when data is delayed.",
            "Intraday data should be treated separately from daily data.",
        ),
    ),
    "short_term_momentum": StrategyProfile(
        key="short_term_momentum",
        label="Short-term momentum",
        description=(
            "Prioritize short-term group strength, breakout quality, volume expansion, "
            "and next-session confirmation."
        ),
        focus_points=(
            "Start from watchlist ranking, score, change_pct, volume, and primary signals.",
            "Identify the strongest candidates, early turnarounds, and names that look extended.",
            "For single stocks, focus on the next 1 to 5 sessions instead of long-term valuation.",
            "State observable trigger conditions and failure conditions from the provided data.",
            "Use chips and fundamentals only as confirmation, contradiction, or risk context.",
        ),
        risk_notes=(
            "Do not call a trade if the latest price, volume, or signal data is stale.",
            "Do not infer intraday follow-through from daily-only evidence.",
            "Mention overextension and pullback risk when signals are strong but price is stretched.",
        ),
    ),
    "chip_flow": StrategyProfile(
        key="chip_flow",
        label="Chip flow",
        description="Prioritize institutional, margin, shareholding, and broker branch flow.",
        focus_points=(
            "Start from institutional net flow, margin balance, and broker branch concentration.",
            "Check whether broker branch coverage is complete for the requested window.",
            "Use price only to verify whether chip flow is being confirmed by the market.",
        ),
        risk_notes=(
            "Broker branch data can be partial and should show available_days.",
            "Chip flow is not a trading instruction by itself.",
        ),
    ),
    "fundamentals_growth": StrategyProfile(
        key="fundamentals_growth",
        label="Fundamentals growth",
        description="Prioritize monthly revenue, quarterly financial metrics, and growth quality.",
        focus_points=(
            "Start from monthly revenue trend and YoY/MoM change.",
            "Compare revenue with EPS, margins, ROE, and book value trend.",
            "Use price and chips as timing context after fundamentals are reviewed.",
        ),
        risk_notes=(
            "Financial statements are reported with a lag.",
            "Revenue growth needs margin and EPS confirmation.",
        ),
    ),
    "dividend_value": StrategyProfile(
        key="dividend_value",
        label="Dividend and value",
        description="Prioritize stability, valuation context, book value, and downside risk.",
        focus_points=(
            "Check financial stability before price momentum.",
            "Look for revenue durability, book value, ROE, and earnings trend.",
            "Treat sharp price moves as risk context unless fundamentals also improved.",
        ),
        risk_notes=(
            "This base profile does not calculate dividend yield yet.",
            "Valuation conclusions need dividend and payout data before being definitive.",
        ),
    ),
}


def get_strategy_profile(key: str | None) -> StrategyProfile:
    if not key:
        return STRATEGY_PROFILES["balanced"]

    return STRATEGY_PROFILES.get(key, STRATEGY_PROFILES["balanced"])


def list_strategy_profiles() -> list[dict]:
    return [
        {
            "key": profile.key,
            "label": profile.label,
            "description": profile.description,
            "focus_points": list(profile.focus_points),
            "risk_notes": list(profile.risk_notes),
        }
        for profile in STRATEGY_PROFILES.values()
    ]


def build_system_prompt(profile_key: str | None) -> str:
    profile = get_strategy_profile(profile_key)
    focus = "\n".join(f"- {item}" for item in profile.focus_points)
    risks = "\n".join(f"- {item}" for item in profile.risk_notes)

    return (
        "You are an Open Market Intelligence research assistant.\n"
        "Use only the provided OMI evidence pack. Do not invent missing market data.\n"
        "Always separate facts, interpretation, missing data, and next checks.\n"
        "Always mention the relevant as_of dates when making a claim.\n\n"
        "Output language and style:\n"
        "- Write every report string value in Traditional Chinese.\n"
        "- Keep stock ids, field names, source names, and indicator keys unchanged when needed.\n"
        "- Be concise and decision-oriented; avoid generic market commentary.\n\n"
        f"Strategy profile: {profile.label}\n"
        f"Profile description: {profile.description}\n\n"
        "Focus:\n"
        f"{focus}\n\n"
        "Risk handling:\n"
        f"{risks}\n"
    )
