from __future__ import annotations

from collections.abc import Mapping
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.config import settings
from app.settings.store import get_technical_analysis_setting_payload


MAX_WINDOW = 1000
DEFAULT_MA_WINDOWS = (5, 20, 60)
DEFAULT_VOLUME_MA_WINDOWS = (5, 20)
_PERSISTED_SETTINGS_UNSET = object()


@dataclass(frozen=True)
class TechnicalAnalysisParameters:
    ma_windows: tuple[int, ...]
    volume_ma_windows: tuple[int, ...]
    macd_fast_period: int
    macd_slow_period: int
    macd_signal_period: int
    pvo_fast_period: int
    pvo_slow_period: int
    pvo_signal_period: int
    rsi_period: int
    atr_period: int
    adx_period: int
    roc_period: int
    mfi_period: int
    donchian_period: int
    bollinger_period: int
    bollinger_std_dev: float
    kd_period: int
    kd_smooth_period: int
    kd_overbought_k: float
    kd_overbought_d: float
    kd_oversold_k: float
    kd_oversold_d: float
    support_resistance_period: int
    max_gap_days: int
    volume_ratio_threshold: float
    breakout_volume_ratio_threshold: float
    near_level_threshold_pct: float
    adx_trend_threshold: float
    rsi_bull_min: float
    rsi_bull_max: float
    rsi_weak_below: float
    rsi_overheated_at: float
    mfi_inflow_min: float
    mfi_inflow_max: float
    mfi_outflow_below: float
    atr_high_volatility_pct: float
    atr_expansion_multiplier: float
    atr_expansion_min_pct: float
    bollinger_squeeze_bandwidth_pct: float

    @property
    def ma_windows_text(self) -> str:
        return ",".join(str(window) for window in self.ma_windows)

    @property
    def volume_ma_windows_text(self) -> str:
        return ",".join(str(window) for window in self.volume_ma_windows)

    @property
    def ma_short_window(self) -> int | None:
        return _window_at(self.ma_windows, 0)

    @property
    def ma_medium_window(self) -> int | None:
        return _window_at(self.ma_windows, 1)

    @property
    def ma_long_window(self) -> int | None:
        return _window_at(self.ma_windows, 2)

    @property
    def volume_ma_short_window(self) -> int | None:
        return _window_at(self.volume_ma_windows, 0)

    @property
    def volume_ma_medium_window(self) -> int | None:
        return _window_at(self.volume_ma_windows, 1)

    @property
    def ma_short_key(self) -> str | None:
        return _series_key("ma", self.ma_short_window)

    @property
    def ma_medium_key(self) -> str | None:
        return _series_key("ma", self.ma_medium_window)

    @property
    def ma_long_key(self) -> str | None:
        return _series_key("ma", self.ma_long_window)

    @property
    def volume_ma_short_key(self) -> str | None:
        return _series_key("volume_ma", self.volume_ma_short_window)

    @property
    def volume_ma_medium_key(self) -> str | None:
        return _series_key("volume_ma", self.volume_ma_medium_window)

    @property
    def ema_fast_key(self) -> str:
        return _series_key("ema", self.macd_fast_period) or "ema"

    @property
    def ema_slow_key(self) -> str:
        return _series_key("ema", self.macd_slow_period) or "ema"

    @property
    def rsi_key(self) -> str:
        return _series_key("rsi", self.rsi_period) or "rsi"

    @property
    def atr_key(self) -> str:
        return _series_key("atr", self.atr_period) or "atr"

    @property
    def plus_di_key(self) -> str:
        return _series_key("plus_di", self.adx_period) or "plus_di"

    @property
    def minus_di_key(self) -> str:
        return _series_key("minus_di", self.adx_period) or "minus_di"

    @property
    def adx_key(self) -> str:
        return _series_key("adx", self.adx_period) or "adx"

    @property
    def roc_key(self) -> str:
        return _series_key("roc", self.roc_period) or "roc"

    @property
    def mfi_key(self) -> str:
        return _series_key("mfi", self.mfi_period) or "mfi"

    @property
    def donchian_upper_key(self) -> str:
        return _series_key("upper", self.donchian_period) or "upper"

    @property
    def donchian_lower_key(self) -> str:
        return _series_key("lower", self.donchian_period) or "lower"

    @property
    def bollinger_upper_key(self) -> str:
        return _series_key("upper", self.bollinger_period) or "upper"

    @property
    def bollinger_middle_key(self) -> str:
        return _series_key("middle", self.bollinger_period) or "middle"

    @property
    def bollinger_lower_key(self) -> str:
        return _series_key("lower", self.bollinger_period) or "lower"

    @property
    def bollinger_bandwidth_key(self) -> str:
        return f"bandwidth{self.bollinger_period}_pct"

    @property
    def kd_k_key(self) -> str:
        return _series_key("k", self.kd_period) or "k"

    @property
    def kd_d_key(self) -> str:
        return _series_key("d", self.kd_period) or "d"

    @property
    def kd_j_key(self) -> str:
        return _series_key("j", self.kd_period) or "j"

    @property
    def support_key(self) -> str:
        return _series_key("support", self.support_resistance_period) or "support"

    @property
    def resistance_key(self) -> str:
        return _series_key("resistance", self.support_resistance_period) or "resistance"


def parse_windows(
    value: str | Sequence[int] | None,
    default: Sequence[int],
    *,
    setting_name: str,
) -> tuple[int, ...]:
    default_windows = tuple(int(item) for item in default)
    if value is None:
        return default_windows

    raw_items: list[str | int]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return default_windows
        raw_items = [item.strip() for item in text.split(",")]
    else:
        raw_items = list(value)

    windows: list[int] = []
    for item in raw_items:
        if item == "":
            continue
        try:
            window = int(item)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{setting_name} contains an invalid window: {item!r}.") from exc
        windows.append(_positive_int(window, setting_name, max_value=MAX_WINDOW))

    if not windows:
        raise ValueError(f"{setting_name} must include at least one window.")

    return tuple(sorted(set(windows)))


def get_technical_analysis_parameters(
    *,
    ma_windows: str | None = None,
    volume_ma_windows: str | None = None,
    volume_ratio_threshold: float | None = None,
    persisted_settings: Mapping[str, Any] | None | object = _PERSISTED_SETTINGS_UNSET,
) -> TechnicalAnalysisParameters:
    if persisted_settings is _PERSISTED_SETTINGS_UNSET:
        persisted_settings = get_technical_analysis_setting_payload()

    base_ma_windows = parse_windows(
        _setting_value(persisted_settings, "ma_windows", settings.technical_ma_windows),
        DEFAULT_MA_WINDOWS,
        setting_name="TECHNICAL_MA_WINDOWS",
    )
    base_volume_ma_windows = parse_windows(
        _setting_value(
            persisted_settings,
            "volume_ma_windows",
            settings.technical_volume_ma_windows,
        ),
        DEFAULT_VOLUME_MA_WINDOWS,
        setting_name="TECHNICAL_VOLUME_MA_WINDOWS",
    )
    resolved = TechnicalAnalysisParameters(
        ma_windows=parse_windows(
            ma_windows,
            base_ma_windows,
            setting_name="ma_windows",
        ),
        volume_ma_windows=parse_windows(
            volume_ma_windows,
            base_volume_ma_windows,
            setting_name="volume_ma_windows",
        ),
        macd_fast_period=_positive_int(
            _setting_value(
                persisted_settings,
                "macd_fast_period",
                settings.technical_macd_fast_period,
            ),
            "TECHNICAL_MACD_FAST_PERIOD",
            max_value=MAX_WINDOW,
        ),
        macd_slow_period=_positive_int(
            _setting_value(
                persisted_settings,
                "macd_slow_period",
                settings.technical_macd_slow_period,
            ),
            "TECHNICAL_MACD_SLOW_PERIOD",
            max_value=MAX_WINDOW,
        ),
        macd_signal_period=_positive_int(
            _setting_value(
                persisted_settings,
                "macd_signal_period",
                settings.technical_macd_signal_period,
            ),
            "TECHNICAL_MACD_SIGNAL_PERIOD",
            max_value=MAX_WINDOW,
        ),
        pvo_fast_period=_positive_int(
            _setting_value(
                persisted_settings,
                "pvo_fast_period",
                settings.technical_pvo_fast_period,
            ),
            "TECHNICAL_PVO_FAST_PERIOD",
            max_value=MAX_WINDOW,
        ),
        pvo_slow_period=_positive_int(
            _setting_value(
                persisted_settings,
                "pvo_slow_period",
                settings.technical_pvo_slow_period,
            ),
            "TECHNICAL_PVO_SLOW_PERIOD",
            max_value=MAX_WINDOW,
        ),
        pvo_signal_period=_positive_int(
            _setting_value(
                persisted_settings,
                "pvo_signal_period",
                settings.technical_pvo_signal_period,
            ),
            "TECHNICAL_PVO_SIGNAL_PERIOD",
            max_value=MAX_WINDOW,
        ),
        rsi_period=_positive_int(
            _setting_value(persisted_settings, "rsi_period", settings.technical_rsi_period),
            "TECHNICAL_RSI_PERIOD",
            max_value=MAX_WINDOW,
        ),
        atr_period=_positive_int(
            _setting_value(persisted_settings, "atr_period", settings.technical_atr_period),
            "TECHNICAL_ATR_PERIOD",
            max_value=MAX_WINDOW,
        ),
        adx_period=_positive_int(
            _setting_value(persisted_settings, "adx_period", settings.technical_adx_period),
            "TECHNICAL_ADX_PERIOD",
            max_value=MAX_WINDOW,
        ),
        roc_period=_positive_int(
            _setting_value(persisted_settings, "roc_period", settings.technical_roc_period),
            "TECHNICAL_ROC_PERIOD",
            max_value=MAX_WINDOW,
        ),
        mfi_period=_positive_int(
            _setting_value(persisted_settings, "mfi_period", settings.technical_mfi_period),
            "TECHNICAL_MFI_PERIOD",
            max_value=MAX_WINDOW,
        ),
        donchian_period=_positive_int(
            _setting_value(
                persisted_settings,
                "donchian_period",
                settings.technical_donchian_period,
            ),
            "TECHNICAL_DONCHIAN_PERIOD",
            max_value=MAX_WINDOW,
        ),
        bollinger_period=_positive_int(
            _setting_value(
                persisted_settings,
                "bollinger_period",
                settings.technical_bollinger_period,
            ),
            "TECHNICAL_BOLLINGER_PERIOD",
            max_value=MAX_WINDOW,
        ),
        bollinger_std_dev=_positive_float(
            _setting_value(
                persisted_settings,
                "bollinger_std_dev",
                settings.technical_bollinger_std_dev,
            ),
            "TECHNICAL_BOLLINGER_STD_DEV",
        ),
        kd_period=_positive_int(
            _setting_value(persisted_settings, "kd_period", settings.technical_kd_period),
            "TECHNICAL_KD_PERIOD",
            max_value=MAX_WINDOW,
        ),
        kd_smooth_period=_positive_int(
            _setting_value(
                persisted_settings,
                "kd_smooth_period",
                settings.technical_kd_smooth_period,
            ),
            "TECHNICAL_KD_SMOOTH_PERIOD",
            max_value=MAX_WINDOW,
        ),
        kd_overbought_k=_positive_float(
            _setting_value(
                persisted_settings,
                "kd_overbought_k",
                settings.technical_kd_overbought_k,
            ),
            "TECHNICAL_KD_OVERBOUGHT_K",
        ),
        kd_overbought_d=_positive_float(
            _setting_value(
                persisted_settings,
                "kd_overbought_d",
                settings.technical_kd_overbought_d,
            ),
            "TECHNICAL_KD_OVERBOUGHT_D",
        ),
        kd_oversold_k=_positive_float(
            _setting_value(
                persisted_settings,
                "kd_oversold_k",
                settings.technical_kd_oversold_k,
            ),
            "TECHNICAL_KD_OVERSOLD_K",
        ),
        kd_oversold_d=_positive_float(
            _setting_value(
                persisted_settings,
                "kd_oversold_d",
                settings.technical_kd_oversold_d,
            ),
            "TECHNICAL_KD_OVERSOLD_D",
        ),
        support_resistance_period=_positive_int(
            _setting_value(
                persisted_settings,
                "support_resistance_period",
                settings.technical_support_resistance_period,
            ),
            "TECHNICAL_SUPPORT_RESISTANCE_PERIOD",
            max_value=MAX_WINDOW,
        ),
        max_gap_days=_positive_int(
            _setting_value(
                persisted_settings,
                "max_gap_days",
                settings.technical_max_gap_days,
            ),
            "TECHNICAL_MAX_GAP_DAYS",
            max_value=MAX_WINDOW,
        ),
        volume_ratio_threshold=_positive_float(
            volume_ratio_threshold
            if volume_ratio_threshold is not None
            else _setting_value(
                persisted_settings,
                "volume_ratio_threshold",
                settings.technical_volume_ratio_threshold,
            ),
            "TECHNICAL_VOLUME_RATIO_THRESHOLD",
        ),
        breakout_volume_ratio_threshold=_positive_float(
            _setting_value(
                persisted_settings,
                "breakout_volume_ratio_threshold",
                settings.technical_breakout_volume_ratio_threshold,
            ),
            "TECHNICAL_BREAKOUT_VOLUME_RATIO_THRESHOLD",
        ),
        near_level_threshold_pct=_positive_float(
            _setting_value(
                persisted_settings,
                "near_level_threshold_pct",
                settings.technical_near_level_threshold_pct,
            ),
            "TECHNICAL_NEAR_LEVEL_THRESHOLD_PCT",
        ),
        adx_trend_threshold=_positive_float(
            _setting_value(
                persisted_settings,
                "adx_trend_threshold",
                settings.technical_adx_trend_threshold,
            ),
            "TECHNICAL_ADX_TREND_THRESHOLD",
        ),
        rsi_bull_min=_positive_float(
            _setting_value(persisted_settings, "rsi_bull_min", settings.technical_rsi_bull_min),
            "TECHNICAL_RSI_BULL_MIN",
        ),
        rsi_bull_max=_positive_float(
            _setting_value(persisted_settings, "rsi_bull_max", settings.technical_rsi_bull_max),
            "TECHNICAL_RSI_BULL_MAX",
        ),
        rsi_weak_below=_positive_float(
            _setting_value(
                persisted_settings,
                "rsi_weak_below",
                settings.technical_rsi_weak_below,
            ),
            "TECHNICAL_RSI_WEAK_BELOW",
        ),
        rsi_overheated_at=_positive_float(
            _setting_value(
                persisted_settings,
                "rsi_overheated_at",
                settings.technical_rsi_overheated_at,
            ),
            "TECHNICAL_RSI_OVERHEATED_AT",
        ),
        mfi_inflow_min=_positive_float(
            _setting_value(
                persisted_settings,
                "mfi_inflow_min",
                settings.technical_mfi_inflow_min,
            ),
            "TECHNICAL_MFI_INFLOW_MIN",
        ),
        mfi_inflow_max=_positive_float(
            _setting_value(
                persisted_settings,
                "mfi_inflow_max",
                settings.technical_mfi_inflow_max,
            ),
            "TECHNICAL_MFI_INFLOW_MAX",
        ),
        mfi_outflow_below=_positive_float(
            _setting_value(
                persisted_settings,
                "mfi_outflow_below",
                settings.technical_mfi_outflow_below,
            ),
            "TECHNICAL_MFI_OUTFLOW_BELOW",
        ),
        atr_high_volatility_pct=_positive_float(
            _setting_value(
                persisted_settings,
                "atr_high_volatility_pct",
                settings.technical_atr_high_volatility_pct,
            ),
            "TECHNICAL_ATR_HIGH_VOLATILITY_PCT",
        ),
        atr_expansion_multiplier=_positive_float(
            _setting_value(
                persisted_settings,
                "atr_expansion_multiplier",
                settings.technical_atr_expansion_multiplier,
            ),
            "TECHNICAL_ATR_EXPANSION_MULTIPLIER",
        ),
        atr_expansion_min_pct=_positive_float(
            _setting_value(
                persisted_settings,
                "atr_expansion_min_pct",
                settings.technical_atr_expansion_min_pct,
            ),
            "TECHNICAL_ATR_EXPANSION_MIN_PCT",
        ),
        bollinger_squeeze_bandwidth_pct=_positive_float(
            _setting_value(
                persisted_settings,
                "bollinger_squeeze_bandwidth_pct",
                settings.technical_bollinger_squeeze_bandwidth_pct,
            ),
            "TECHNICAL_BOLLINGER_SQUEEZE_BANDWIDTH_PCT",
        ),
    )
    if resolved.macd_fast_period >= resolved.macd_slow_period:
        raise ValueError("TECHNICAL_MACD_FAST_PERIOD must be less than TECHNICAL_MACD_SLOW_PERIOD.")
    if resolved.pvo_fast_period >= resolved.pvo_slow_period:
        raise ValueError("TECHNICAL_PVO_FAST_PERIOD must be less than TECHNICAL_PVO_SLOW_PERIOD.")
    if resolved.rsi_bull_min > resolved.rsi_bull_max:
        raise ValueError("TECHNICAL_RSI_BULL_MIN must be less than or equal to TECHNICAL_RSI_BULL_MAX.")
    if resolved.mfi_inflow_min > resolved.mfi_inflow_max:
        raise ValueError("TECHNICAL_MFI_INFLOW_MIN must be less than or equal to TECHNICAL_MFI_INFLOW_MAX.")
    if resolved.kd_oversold_k > resolved.kd_overbought_k:
        raise ValueError("TECHNICAL_KD_OVERSOLD_K must be less than or equal to TECHNICAL_KD_OVERBOUGHT_K.")
    if resolved.kd_oversold_d > resolved.kd_overbought_d:
        raise ValueError("TECHNICAL_KD_OVERSOLD_D must be less than or equal to TECHNICAL_KD_OVERBOUGHT_D.")
    return resolved


def _setting_value(
    persisted_settings: Mapping[str, Any] | None | object,
    key: str,
    fallback: Any,
) -> Any:
    if not isinstance(persisted_settings, Mapping):
        return fallback

    return persisted_settings.get(key, fallback)


def _window_at(windows: Sequence[int], index: int) -> int | None:
    if not windows:
        return None
    if len(windows) > index:
        return int(windows[index])
    return int(windows[-1])


def _series_key(prefix: str, period: int | None) -> str | None:
    return f"{prefix}{period}" if period is not None else None


def _positive_int(value: int, setting_name: str, *, max_value: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{setting_name} must be an integer.") from exc
    if parsed <= 0:
        raise ValueError(f"{setting_name} must be greater than 0.")
    if parsed > max_value:
        raise ValueError(f"{setting_name} must be less than or equal to {max_value}.")
    return parsed


def _positive_float(value: float, setting_name: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{setting_name} must be a number.") from exc
    if parsed <= 0:
        raise ValueError(f"{setting_name} must be greater than 0.")
    return parsed
