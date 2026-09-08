from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import StockMaster
from app.market.daily_price_repository import TaiwanOfficialDailyBarRepository


TAIWAN_INDUSTRY_CODE_LABELS: dict[str, str] = {
    "01": "水泥工業",
    "02": "食品工業",
    "03": "塑膠工業",
    "04": "紡織纖維",
    "05": "電機機械",
    "06": "電器電纜",
    "08": "玻璃陶瓷",
    "09": "造紙工業",
    "10": "鋼鐵工業",
    "11": "橡膠工業",
    "12": "汽車工業",
    "14": "建材營造業",
    "15": "航運業",
    "16": "觀光餐旅",
    "17": "金融保險業",
    "18": "貿易百貨業",
    "20": "其他業",
    "21": "化學工業",
    "22": "生技醫療業",
    "23": "油電燃氣業",
    "24": "半導體業",
    "25": "電腦及週邊設備業",
    "26": "光電業",
    "27": "通信網路業",
    "28": "電子零組件業",
    "29": "電子通路業",
    "30": "資訊服務業",
    "31": "其他電子業",
    "32": "文化創意業",
    "33": "農業科技業",
    "34": "電子商務業",
    "35": "綠能環保",
    "36": "數位雲端",
    "37": "運動休閒",
    "38": "居家生活",
}

TAIWAN_INDUSTRY_LABEL_ALIASES: dict[str, str] = {
    "金融業": "金融保險業",
    "金融保險": "金融保險業",
    "建材營造": "建材營造業",
    "貿易百貨": "貿易百貨業",
    "半導體": "半導體業",
}
TAIWAN_INDUSTRY_LABEL_CODES = {
    label: code for code, label in TAIWAN_INDUSTRY_CODE_LABELS.items()
}


def _numeric_code(value: Any) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return f"{value:02d}"
    if isinstance(value, float) and value.is_integer():
        return f"{int(value):02d}"

    text = str(value).strip()
    if text.isdigit():
        return text.zfill(2)
    try:
        parsed = float(text)
    except ValueError:
        return None
    if parsed.is_integer():
        return f"{int(parsed):02d}"
    return None


def normalize_tw_industry_label(value: Any, *, fallback: str = "-") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    if not text:
        return fallback

    code = _numeric_code(value)
    if code is None:
        return TAIWAN_INDUSTRY_LABEL_ALIASES.get(text, text)
    return TAIWAN_INDUSTRY_CODE_LABELS.get(code, "unmapped_raw_industry")


def canonical_tw_sector_identity(value: Any) -> dict[str, Any]:
    raw = str(value or "").strip()
    code = _numeric_code(value)
    canonical_name = normalize_tw_industry_label(value, fallback="未分類")
    canonical_code = (
        code
        if code in TAIWAN_INDUSTRY_CODE_LABELS
        else TAIWAN_INDUSTRY_LABEL_CODES.get(canonical_name)
    )
    if canonical_code is not None:
        return {
            "sector_id": f"tw.sector.{canonical_code}",
            "name": TAIWAN_INDUSTRY_CODE_LABELS[canonical_code],
            "identity_status": "canonical",
            "canonical_code": canonical_code,
            "raw_industry": raw or None,
        }
    if code is not None:
        return {
            "sector_id": f"tw.sector.unmapped.{code}",
            "name": "unmapped_raw_industry",
            "identity_status": "unmapped_raw_industry",
            "canonical_code": None,
            "raw_industry": raw,
            "raw_industry_code": code,
        }
    return {
        "sector_id": f"tw.sector.raw.{canonical_name}",
        "name": canonical_name,
        "identity_status": "unmapped_label",
        "canonical_code": None,
        "raw_industry": raw or None,
    }


def build_tw_sector_benchmark(
    db: Session,
    *,
    stock_id: str,
    trade_dates: list[date],
) -> dict[str, Any]:
    """Build a bounded equal-weight sector index from canonical daily bars."""

    stock = (
        db.query(StockMaster)
        .filter(StockMaster.stock_id == stock_id)
        .filter(StockMaster.is_active.is_(True))
        .first()
    )
    identity = canonical_tw_sector_identity(
        stock.industry or stock.category if stock is not None else None
    )
    if stock is None or identity["identity_status"] != "canonical":
        return {
            "status": "not_available",
            "identity": identity,
            "points": [],
            "reason": "canonical_sector_identity_unavailable",
        }

    members = []
    for candidate in (
        db.query(StockMaster)
        .filter(StockMaster.is_active.is_(True))
        .filter(StockMaster.instrument_type == "stock")
        .filter(StockMaster.market.in_(("TWSE", "TPEX")))
        .all()
    ):
        candidate_identity = canonical_tw_sector_identity(
            candidate.industry or candidate.category
        )
        if candidate_identity["sector_id"] == identity["sector_id"]:
            members.append(str(candidate.stock_id))
    members = sorted(dict.fromkeys(members))
    if not members or len(members) > 500:
        return {
            "status": "not_available",
            "identity": identity,
            "points": [],
            "member_count": len(members),
            "reason": "canonical_sector_membership_out_of_bounds",
        }

    selected_dates = sorted(dict.fromkeys(trade_dates))[-61:]
    repository = TaiwanOfficialDailyBarRepository(db)
    bases: dict[str, float] = {}
    points: list[dict[str, Any]] = []
    coverage: list[dict[str, Any]] = []
    for trade_date in selected_dates:
        snapshot = repository.load_market_universe(
            trade_date=trade_date,
            symbols=tuple(members),
            max_rows=min(20_000, max(5_000, len(members) * 4)),
        )
        normalized_values: list[float] = []
        for bar in snapshot.bars:
            symbol = bar.instrument.symbol
            close = float(bar.close_price)
            bases.setdefault(symbol, close)
            base = bases[symbol]
            if base > 0:
                normalized_values.append(close / base * 100.0)
        if normalized_values:
            points.append(
                {
                    "time": trade_date,
                    "close": sum(normalized_values) / len(normalized_values),
                }
            )
        coverage.append(
            {
                "trade_date": trade_date.isoformat(),
                "observed_count": len(normalized_values),
                "member_count": len(members),
            }
        )
    latest_coverage = coverage[-1] if coverage else None
    return {
        "status": "ready" if len(points) > 60 else "partial",
        "identity": identity,
        "points": points,
        "member_count": len(members),
        "observed_member_count": (
            latest_coverage["observed_count"] if latest_coverage else 0
        ),
        "as_of": points[-1]["time"].isoformat() if points else None,
        "method": "equal_weighted_rebased_canonical_daily_close",
        "source": "TaiwanOfficialDailyBarRepository",
        "coverage": latest_coverage,
    }
