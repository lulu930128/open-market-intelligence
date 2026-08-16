from app.market.technical_parameters import get_technical_analysis_parameters
from app.settings.store import (
    get_technical_analysis_setting_payload,
    save_technical_analysis_setting_payload,
)
from app.settings.schemas import (
    TechnicalAnalysisAtrThresholdsRead,
    TechnicalAnalysisBollingerPeriodsRead,
    TechnicalAnalysisIndicatorKeysRead,
    TechnicalAnalysisKdPeriodsRead,
    TechnicalAnalysisKdThresholdsRead,
    TechnicalAnalysisMacdPeriodsRead,
    TechnicalAnalysisMfiThresholdsRead,
    TechnicalAnalysisPeriodsRead,
    TechnicalAnalysisPvoPeriodsRead,
    TechnicalAnalysisQueryDefaultsRead,
    TechnicalAnalysisRsiThresholdsRead,
    TechnicalAnalysisSettingsRead,
    TechnicalAnalysisSettingsWrite,
    TechnicalAnalysisThresholdsRead,
    TechnicalAnalysisWindowsRead,
)
from sqlalchemy.orm import Session


def get_technical_analysis_settings(db: Session | None = None) -> TechnicalAnalysisSettingsRead:
    persisted_settings = get_technical_analysis_setting_payload(db=db)
    parameters = get_technical_analysis_parameters(persisted_settings=persisted_settings)
    source = "database" if persisted_settings is not None else "backend_config"

    return _technical_analysis_settings_response(parameters=parameters, source=source)


def update_technical_analysis_settings(
    db: Session,
    payload: TechnicalAnalysisSettingsWrite,
) -> TechnicalAnalysisSettingsRead:
    settings_payload = _technical_analysis_payload(payload)

    # Validate through the same resolver used by calculations before persisting.
    parameters = get_technical_analysis_parameters(persisted_settings=settings_payload)
    save_technical_analysis_setting_payload(db, settings_payload)

    return _technical_analysis_settings_response(parameters=parameters, source="database")


def _technical_analysis_settings_response(
    *,
    parameters,
    source: str,
) -> TechnicalAnalysisSettingsRead:

    return TechnicalAnalysisSettingsRead(
        kind="technical_analysis_settings",
        version="technical_analysis_settings.v1",
        source=source,
        windows=TechnicalAnalysisWindowsRead(
            ma=list(parameters.ma_windows),
            volume_ma=list(parameters.volume_ma_windows),
            max_gap_days=parameters.max_gap_days,
        ),
        periods=TechnicalAnalysisPeriodsRead(
            macd=TechnicalAnalysisMacdPeriodsRead(
                fast=parameters.macd_fast_period,
                slow=parameters.macd_slow_period,
                signal=parameters.macd_signal_period,
            ),
            pvo=TechnicalAnalysisPvoPeriodsRead(
                fast=parameters.pvo_fast_period,
                slow=parameters.pvo_slow_period,
                signal=parameters.pvo_signal_period,
            ),
            rsi=parameters.rsi_period,
            atr=parameters.atr_period,
            adx=parameters.adx_period,
            roc=parameters.roc_period,
            mfi=parameters.mfi_period,
            donchian=parameters.donchian_period,
            bollinger=TechnicalAnalysisBollingerPeriodsRead(
                period=parameters.bollinger_period,
                std_dev=parameters.bollinger_std_dev,
            ),
            kd=TechnicalAnalysisKdPeriodsRead(
                period=parameters.kd_period,
                smooth=parameters.kd_smooth_period,
            ),
            support_resistance=parameters.support_resistance_period,
        ),
        thresholds=TechnicalAnalysisThresholdsRead(
            volume_ratio=parameters.volume_ratio_threshold,
            breakout_volume_ratio=parameters.breakout_volume_ratio_threshold,
            near_level_pct=parameters.near_level_threshold_pct,
            adx_trend=parameters.adx_trend_threshold,
            rsi=TechnicalAnalysisRsiThresholdsRead(
                bull_min=parameters.rsi_bull_min,
                bull_max=parameters.rsi_bull_max,
                weak_below=parameters.rsi_weak_below,
                overheated_at=parameters.rsi_overheated_at,
            ),
            mfi=TechnicalAnalysisMfiThresholdsRead(
                inflow_min=parameters.mfi_inflow_min,
                inflow_max=parameters.mfi_inflow_max,
                outflow_below=parameters.mfi_outflow_below,
            ),
            kd=TechnicalAnalysisKdThresholdsRead(
                overbought_k=parameters.kd_overbought_k,
                overbought_d=parameters.kd_overbought_d,
                oversold_k=parameters.kd_oversold_k,
                oversold_d=parameters.kd_oversold_d,
            ),
            atr=TechnicalAnalysisAtrThresholdsRead(
                high_volatility_pct=parameters.atr_high_volatility_pct,
                expansion_multiplier=parameters.atr_expansion_multiplier,
                expansion_min_pct=parameters.atr_expansion_min_pct,
            ),
            bollinger_squeeze_bandwidth_pct=parameters.bollinger_squeeze_bandwidth_pct,
        ),
        query_defaults=TechnicalAnalysisQueryDefaultsRead(
            ma_windows=parameters.ma_windows_text,
            volume_ma_windows=parameters.volume_ma_windows_text,
            volume_ratio_threshold=parameters.volume_ratio_threshold,
        ),
        indicator_keys=TechnicalAnalysisIndicatorKeysRead(
            ma_short=parameters.ma_short_key,
            ma_medium=parameters.ma_medium_key,
            ma_long=parameters.ma_long_key,
            volume_ma_short=parameters.volume_ma_short_key,
            volume_ma_medium=parameters.volume_ma_medium_key,
            ema_fast=parameters.ema_fast_key,
            ema_slow=parameters.ema_slow_key,
            rsi=parameters.rsi_key,
            atr=parameters.atr_key,
            plus_di=parameters.plus_di_key,
            minus_di=parameters.minus_di_key,
            adx=parameters.adx_key,
            roc=parameters.roc_key,
            mfi=parameters.mfi_key,
            donchian_upper=parameters.donchian_upper_key,
            donchian_lower=parameters.donchian_lower_key,
            bollinger_upper=parameters.bollinger_upper_key,
            bollinger_middle=parameters.bollinger_middle_key,
            bollinger_lower=parameters.bollinger_lower_key,
            bollinger_bandwidth=parameters.bollinger_bandwidth_key,
            kd_k=parameters.kd_k_key,
            kd_d=parameters.kd_d_key,
            kd_j=parameters.kd_j_key,
            support=parameters.support_key,
            resistance=parameters.resistance_key,
        ),
    )


def _technical_analysis_payload(payload: TechnicalAnalysisSettingsWrite) -> dict:
    return {
        "ma_windows": list(payload.windows.ma),
        "volume_ma_windows": list(payload.windows.volume_ma),
        "max_gap_days": payload.windows.max_gap_days,
        "macd_fast_period": payload.periods.macd.fast,
        "macd_slow_period": payload.periods.macd.slow,
        "macd_signal_period": payload.periods.macd.signal,
        "pvo_fast_period": payload.periods.pvo.fast,
        "pvo_slow_period": payload.periods.pvo.slow,
        "pvo_signal_period": payload.periods.pvo.signal,
        "rsi_period": payload.periods.rsi,
        "atr_period": payload.periods.atr,
        "adx_period": payload.periods.adx,
        "roc_period": payload.periods.roc,
        "mfi_period": payload.periods.mfi,
        "donchian_period": payload.periods.donchian,
        "bollinger_period": payload.periods.bollinger.period,
        "bollinger_std_dev": payload.periods.bollinger.std_dev,
        "kd_period": payload.periods.kd.period,
        "kd_smooth_period": payload.periods.kd.smooth,
        "support_resistance_period": payload.periods.support_resistance,
        "volume_ratio_threshold": payload.thresholds.volume_ratio,
        "breakout_volume_ratio_threshold": payload.thresholds.breakout_volume_ratio,
        "near_level_threshold_pct": payload.thresholds.near_level_pct,
        "adx_trend_threshold": payload.thresholds.adx_trend,
        "rsi_bull_min": payload.thresholds.rsi.bull_min,
        "rsi_bull_max": payload.thresholds.rsi.bull_max,
        "rsi_weak_below": payload.thresholds.rsi.weak_below,
        "rsi_overheated_at": payload.thresholds.rsi.overheated_at,
        "mfi_inflow_min": payload.thresholds.mfi.inflow_min,
        "mfi_inflow_max": payload.thresholds.mfi.inflow_max,
        "mfi_outflow_below": payload.thresholds.mfi.outflow_below,
        "kd_overbought_k": payload.thresholds.kd.overbought_k,
        "kd_overbought_d": payload.thresholds.kd.overbought_d,
        "kd_oversold_k": payload.thresholds.kd.oversold_k,
        "kd_oversold_d": payload.thresholds.kd.oversold_d,
        "atr_high_volatility_pct": payload.thresholds.atr.high_volatility_pct,
        "atr_expansion_multiplier": payload.thresholds.atr.expansion_multiplier,
        "atr_expansion_min_pct": payload.thresholds.atr.expansion_min_pct,
        "bollinger_squeeze_bandwidth_pct": payload.thresholds.bollinger_squeeze_bandwidth_pct,
    }
