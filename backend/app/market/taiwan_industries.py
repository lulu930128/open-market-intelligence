from __future__ import annotations

from typing import Any


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
        return text
    return TAIWAN_INDUSTRY_CODE_LABELS.get(code, f"產業代碼 {code}")
