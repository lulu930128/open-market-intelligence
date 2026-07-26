"use client";

import type {
  IndicatorParameters,
  IndicatorSettings,
} from "@/components/stock-k-line/indicatorCatalog";
import {
  chartTimeParts,
  formatChartDate,
  formatChartDateTime,
  pad2,
  type BuiltSeriesData,
  type ChartDisplayStyle,
  type ChartDrawingTool,
  type ChartTimeMode,
  type LineSeriesData,
  type PlotLineData,
  type PriceCoordinateApi,
} from "@/components/chart/lightweight-chart/drawingModel";
import {
  buildDefaultVisibleLogicalRange,
  chartKeyboardBoundaryPaddingBars,
  chartRightPaddingBars,
  formatPrice,
  logicalRange,
} from "@/components/chart/lightweight-chart/indicatorSeriesProjection";
import type { OmiChartColors } from "@/lib/themeColors";
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  createChart,
  type IChartApi,
  type LineData,
  type LogicalRange,
  type Time,
  type TickMarkType,
} from "lightweight-charts";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

type SeriesDataUpdater = (nextSeriesData: BuiltSeriesData) => void;

type UseLightweightChartEngineArgs = {
  activeIndicators: IndicatorSettings;
  benchmarkLabel?: string;
  chartSeriesKey: string;
  chartStyle: ChartDisplayStyle;
  drawingTool: ChartDrawingTool;
  height: number;
  maColors: {
    maShort: string;
    maMiddle: string;
    maLong: string;
  };
  omiChartColors: OmiChartColors;
  params: IndicatorParameters;
  pricePrecision?: number;
  resolvedVolumePanelLabel: string;
  seriesData: BuiltSeriesData;
  timeMode: ChartTimeMode;
};

export function useLightweightChartEngine({
  activeIndicators,
  benchmarkLabel,
  chartSeriesKey,
  chartStyle,
  drawingTool,
  height,
  maColors,
  omiChartColors,
  params,
  pricePrecision,
  resolvedVolumePanelLabel,
  seriesData,
  timeMode,
}: UseLightweightChartEngineArgs) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const mainSeriesRef = useRef<PriceCoordinateApi | null>(null);
  const seriesDataUpdatersRef = useRef<SeriesDataUpdater[]>([]);
  const chartInteractionActiveRef = useRef(false);
  const pendingSeriesDataRef = useRef<BuiltSeriesData | null>(null);
  const chartInteractionEndTimerRef = useRef<number | null>(null);
  const visibleLogicalRangeRef = useRef<LogicalRange | null>(null);
  const visibleLogicalRangeKeyRef = useRef<string | null>(null);
  const overlayRevisionFrameRef = useRef<number | null>(null);
  const latestSeriesDataRef = useRef(seriesData);
  const [overlaySize, setOverlaySize] = useState({ width: 0, height: 0 });
  const [overlayRevision, setOverlayRevision] = useState(0);
  const upColor = omiChartColors.marketUp;
  const downColor = omiChartColors.marketDown;
  const resolvedPricePrecision = Number.isInteger(pricePrecision)
    ? Math.min(8, Math.max(0, pricePrecision as number))
    : 2;
  const priceMinMove = 10 ** -resolvedPricePrecision;

  useLayoutEffect(() => {
    latestSeriesDataRef.current = seriesData;
  }, [seriesData]);

  const rememberVisibleLogicalRange = useCallback(() => {
    const chart = chartRef.current;
    const range = chart?.timeScale().getVisibleLogicalRange();

    if (!range) return null;

    const visibleRange = { from: range.from, to: range.to };
    visibleLogicalRangeRef.current = visibleRange;
    visibleLogicalRangeKeyRef.current = chartSeriesKey;

    return visibleRange;
  }, [chartSeriesKey]);

  const restoreVisibleLogicalRange = useCallback((range: LogicalRange | null | undefined) => {
    if (!range) return;

    window.requestAnimationFrame(() => {
      const chart = chartRef.current;

      if (!chart) return;

      chart.timeScale().setVisibleLogicalRange(range);
      visibleLogicalRangeRef.current = { from: range.from, to: range.to };
      visibleLogicalRangeKeyRef.current = chartSeriesKey;
    });
  }, [chartSeriesKey]);

  const getVisibleLogicalRange = useCallback(
    () => chartRef.current?.timeScale().getVisibleLogicalRange() ?? visibleLogicalRangeRef.current,
    []
  );

  const scheduleOverlayRevision = useCallback(() => {
    if (overlayRevisionFrameRef.current !== null) return;

    overlayRevisionFrameRef.current = window.requestAnimationFrame(() => {
      overlayRevisionFrameRef.current = null;
      setOverlayRevision((value) => value + 1);
    });
  }, []);

  const applySeriesDataToChart = useCallback((nextSeriesData: BuiltSeriesData) => {
    const updaters = seriesDataUpdatersRef.current;

    if (updaters.length === 0) return;

    updaters.forEach((updater) => updater(nextSeriesData));
    scheduleOverlayRevision();
  }, [scheduleOverlayRevision]);

  const flushPendingSeriesData = useCallback(() => {
    const pendingSeriesData = pendingSeriesDataRef.current;

    if (!pendingSeriesData) return;

    pendingSeriesDataRef.current = null;
    applySeriesDataToChart(pendingSeriesData);
  }, [applySeriesDataToChart]);

  const applyChartPointerInteractivity = useCallback((interactive: boolean) => {
    const chart = chartRef.current;

    if (!chart) return;

    chart.applyOptions({
      handleScroll: {
        mouseWheel: interactive,
        pressedMouseMove: interactive,
        horzTouchDrag: interactive,
        vertTouchDrag: false,
      },
      handleScale: {
        mouseWheel: interactive,
        pinch: interactive,
        axisPressedMouseMove: interactive,
      },
    });
  }, []);

  const beginChartInteraction = useCallback(() => {
    chartInteractionActiveRef.current = true;

    if (chartInteractionEndTimerRef.current !== null) {
      window.clearTimeout(chartInteractionEndTimerRef.current);
      chartInteractionEndTimerRef.current = null;
    }
  }, []);

  const endChartInteraction = useCallback(() => {
    if (chartInteractionEndTimerRef.current !== null) {
      window.clearTimeout(chartInteractionEndTimerRef.current);
    }

    chartInteractionEndTimerRef.current = window.setTimeout(() => {
      chartInteractionActiveRef.current = false;
      chartInteractionEndTimerRef.current = null;
      flushPendingSeriesData();
    }, 80);
  }, [flushPendingSeriesData]);

  const restoreChartPointerInteractivity = useCallback(() => {
    applyChartPointerInteractivity(drawingTool === "cursor");
  }, [applyChartPointerInteractivity, drawingTool]);

  const applyVisibleLogicalRange = useCallback((range: LogicalRange) => {
    const chart = chartRef.current;

    if (!chart) return;

    chart.timeScale().setVisibleLogicalRange(range);
    visibleLogicalRangeRef.current = { from: range.from, to: range.to };
    visibleLogicalRangeKeyRef.current = chartSeriesKey;
    scheduleOverlayRevision();
  }, [chartSeriesKey, scheduleOverlayRevision]);

  const resetVisibleLogicalRangeToLatest = useCallback(() => {
    const chart = chartRef.current;

    if (!chart || seriesData.candles.length === 0) return;

    const defaultRange = buildDefaultVisibleLogicalRange(seriesData.candles.length, timeMode);

    if (defaultRange) {
      applyVisibleLogicalRange(defaultRange);
      return;
    }

    chart.timeScale().fitContent();
    const range = chart.timeScale().getVisibleLogicalRange();

    if (range) {
      visibleLogicalRangeRef.current = { from: range.from, to: range.to };
      visibleLogicalRangeKeyRef.current = chartSeriesKey;
    }

    scheduleOverlayRevision();
  }, [
    applyVisibleLogicalRange,
    chartSeriesKey,
    scheduleOverlayRevision,
    seriesData.candles.length,
    timeMode,
  ]);

  const updateVisibleLogicalRange = useCallback((
    transform: (range: { from: number; to: number }) => { from: number; to: number }
  ) => {
    const chart = chartRef.current;
    const currentRange =
      chart?.timeScale().getVisibleLogicalRange() ??
      visibleLogicalRangeRef.current ??
      buildDefaultVisibleLogicalRange(seriesData.candles.length, timeMode);

    if (!currentRange || seriesData.candles.length === 0) return;

    const currentNumericRange = {
      from: Number(currentRange.from),
      to: Number(currentRange.to),
    };
    const lastIndex = seriesData.candles.length - 1;
    const boundaryPadding = chartKeyboardBoundaryPaddingBars(timeMode);
    const minFrom = -Math.min(boundaryPadding, Math.max(seriesData.candles.length, 1));
    const maxTo = lastIndex + boundaryPadding;
    const nextRange = transform(currentNumericRange);
    const width = Math.max(4, nextRange.to - nextRange.from);
    let from = nextRange.from;
    let to = nextRange.to;

    if (to > maxTo) {
      to = maxTo;
      from = to - width;
    }

    if (from < minFrom) {
      from = minFrom;
      to = from + width;
    }

    applyVisibleLogicalRange(logicalRange(from, to));
  }, [applyVisibleLogicalRange, seriesData.candles.length, timeMode]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || latestSeriesDataRef.current.candles.length === 0) return;
    const initialHeight = container.clientHeight || height;

    const chart = createChart(container, {
      autoSize: false,
      width: container.clientWidth,
      height: initialHeight,
      layout: {
        background: { type: ColorType.Solid, color: omiChartColors.surface },
        textColor: omiChartColors.neutralMuted,
        fontSize: 12,
        fontFamily:
          'ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
        attributionLogo: false,
        panes: {
          separatorColor: omiChartColors.grid,
          separatorHoverColor: omiChartColors.tooltipBorder,
          enableResize: true,
        },
      },
      grid: {
        vertLines: { color: omiChartColors.gridSubtle },
        horzLines: { color: omiChartColors.grid },
      },
      rightPriceScale: {
        borderColor: omiChartColors.axisBorder,
        scaleMargins: {
          top: 0.07,
          bottom: activeIndicators.volume ? 0.27 : 0.08,
        },
      },
      timeScale: {
        borderColor: omiChartColors.axisBorder,
        timeVisible: timeMode === "intraday",
        secondsVisible: false,
        rightOffset: chartRightPaddingBars(timeMode),
        barSpacing: timeMode === "intraday" ? 10 : 7,
        fixRightEdge: false,
        rightBarStaysOnScroll: false,
        lockVisibleTimeRangeOnResize: true,
        tickMarkFormatter: (time: Time, tickMarkType: TickMarkType) => {
          if (timeMode === "intraday" && tickMarkType >= 3) {
            const parts = chartTimeParts(time);

            if (parts) return `${pad2(parts.hour)}:${pad2(parts.minute)}`;
          }

          return formatChartDate(time);
        },
      },
      crosshair: {
        mode: CrosshairMode.MagnetOHLC,
        vertLine: {
          color: omiChartColors.crosshair,
          labelBackgroundColor: omiChartColors.text,
          style: 2,
        },
        horzLine: {
          color: omiChartColors.crosshair,
          labelBackgroundColor: omiChartColors.text,
          style: 2,
        },
      },
      handleScroll: {
        mouseWheel: true,
        pressedMouseMove: true,
        horzTouchDrag: true,
        vertTouchDrag: false,
      },
      handleScale: {
        mouseWheel: true,
        pinch: true,
        axisPressedMouseMove: true,
      },
      localization: {
        locale: "zh-TW",
        dateFormat: "yyyy/MM/dd",
        timeFormatter: (time: Time) => formatChartDateTime(time, timeMode),
        priceFormatter: (price: number) => formatPrice(price, pricePrecision),
      },
    });

    chartRef.current = chart;
    const seriesDataUpdaters: SeriesDataUpdater[] = [];
    const registerSeriesDataUpdater = (updater: SeriesDataUpdater) => {
      seriesDataUpdaters.push(updater);
      updater(latestSeriesDataRef.current);
    };
    const lineData = <TKey extends keyof LineSeriesData>(key: TKey) =>
      (nextData: BuiltSeriesData): LineSeriesData[TKey] => nextData.lines[key];

    if (chartStyle === "line") {
      const mainLineSeries = chart.addSeries(LineSeries, {
        title: "Close",
        color: omiChartColors.text,
        lineWidth: 2,
        priceLineVisible: true,
        lastValueVisible: true,
        priceFormat: {
          type: "price",
          precision: resolvedPricePrecision,
          minMove: priceMinMove,
        },
      });
      registerSeriesDataUpdater((nextData) => mainLineSeries.setData(nextData.line));
      mainSeriesRef.current = mainLineSeries;
    } else {
      const candleSeries = chart.addSeries(CandlestickSeries, {
        title: "K",
        upColor,
        downColor,
        borderUpColor: upColor,
        borderDownColor: downColor,
        wickUpColor: upColor,
        wickDownColor: downColor,
        priceFormat: {
          type: "price",
          precision: resolvedPricePrecision,
          minMove: priceMinMove,
        },
      });
      registerSeriesDataUpdater((nextData) => candleSeries.setData(nextData.candles));
      mainSeriesRef.current = candleSeries;
    }

    if (activeIndicators.volume) {
      const volumeSeries = chart.addSeries(HistogramSeries, {
        title: resolvedVolumePanelLabel,
        priceScaleId: "",
        priceFormat: {
          type: "volume",
        },
        color: omiChartColors.volume,
      });
      registerSeriesDataUpdater((nextData) => volumeSeries.setData(nextData.volumes));
      chart.priceScale("").applyOptions({
        scaleMargins: {
          top: 0.82,
          bottom: 0,
        },
      });
    }

    function addMainLine(
      getData: (nextData: BuiltSeriesData) => PlotLineData[],
      title: string,
      color: string,
      options?: { lineWidth?: 1 | 2 | 3 | 4; dashed?: boolean; pointsOnly?: boolean }
    ) {
      const series = chart.addSeries(LineSeries, {
        title,
        color,
        lineWidth: options?.lineWidth ?? 2,
        lineVisible: !options?.pointsOnly,
        pointMarkersVisible: Boolean(options?.pointsOnly),
        pointMarkersRadius: options?.pointsOnly ? 3 : undefined,
        priceLineVisible: false,
        lastValueVisible: false,
        lineStyle: options?.dashed ? 2 : 0,
      });
      registerSeriesDataUpdater((nextData) => series.setData(getData(nextData)));
    }

    function addPaneLine(
      paneIndex: number,
      getData: (nextData: BuiltSeriesData) => LineData<Time>[],
      title: string,
      color: string,
      options?: { lineWidth?: 1 | 2 | 3 | 4; dashed?: boolean }
    ) {
      const series = chart.addSeries(
        LineSeries,
        {
          title,
          color,
          lineWidth: options?.lineWidth ?? 2,
          priceLineVisible: false,
          lastValueVisible: true,
          lineStyle: options?.dashed ? 2 : 0,
        },
        paneIndex
      );
      registerSeriesDataUpdater((nextData) => series.setData(getData(nextData)));
    }

    function addIndicatorPane(heightPx = 92) {
      const pane = chart.addPane();
      pane.setHeight(heightPx);
      return pane.paneIndex();
    }

    if (activeIndicators.ma) {
      addMainLine(lineData("maShort"), `MA${params.maShort}`, maColors.maShort);
      addMainLine(lineData("maMiddle"), `MA${params.maMiddle}`, maColors.maMiddle);
      addMainLine(lineData("maLong"), `MA${params.maLong}`, maColors.maLong, {
        lineWidth: 1,
      });
    }

    if (activeIndicators.ema) {
      addMainLine(lineData("emaFast"), `EMA${params.emaFast}`, omiChartColors.cyan);
      addMainLine(lineData("emaSlow"), `EMA${params.emaSlow}`, omiChartColors.rose);
    }

    if (activeIndicators.wma) {
      addMainLine(lineData("wma"), `WMA${params.wmaPeriod}`, omiChartColors.sky);
    }

    if (activeIndicators.hma) {
      addMainLine(lineData("hma"), `HMA${params.hmaPeriod}`, omiChartColors.roseDark);
    }

    if (activeIndicators.vwma) {
      addMainLine(lineData("vwma"), `VWMA${params.vwmaPeriod}`, omiChartColors.green, {
        dashed: true,
      });
    }

    if (activeIndicators.bollinger) {
      addMainLine(lineData("bollingerUpper"), "BOLL Upper", omiChartColors.indicator.bollinger, { lineWidth: 1 });
      addMainLine(lineData("bollingerMiddle"), "BOLL Mid", omiChartColors.indicator.bollingerMiddle, {
        lineWidth: 1,
        dashed: true,
      });
      addMainLine(lineData("bollingerLower"), "BOLL Lower", omiChartColors.indicator.bollinger, { lineWidth: 1 });
    }

    if (activeIndicators.vwap) {
      addMainLine(lineData("vwap"), "VWAP", omiChartColors.neutralLine, { dashed: true });
    }

    if (activeIndicators.psar) {
      addMainLine(lineData("psar"), "SAR", omiChartColors.purple, { pointsOnly: true, lineWidth: 1 });
    }

    if (activeIndicators.donchian) {
      addMainLine(lineData("donchianUpper"), `DONCH${params.donchianPeriod} U`, omiChartColors.lime, {
        lineWidth: 1,
      });
      addMainLine(lineData("donchianLower"), `DONCH${params.donchianPeriod} L`, omiChartColors.lime, {
        lineWidth: 1,
      });
    }

    if (activeIndicators.ichimoku) {
      addMainLine(
        lineData("ichimokuConversion"),
        `Tenkan${params.ichimokuConversionPeriod}`,
        omiChartColors.marketUp,
        { lineWidth: 1 }
      );
      addMainLine(
        lineData("ichimokuBase"),
        `Kijun${params.ichimokuBasePeriod}`,
        omiChartColors.info,
        { lineWidth: 1 }
      );
      addMainLine(lineData("ichimokuSpanA"), "Senkou A", omiChartColors.marketDown, {
        lineWidth: 1,
        dashed: true,
      });
      addMainLine(lineData("ichimokuSpanB"), "Senkou B", omiChartColors.amberDark, {
        lineWidth: 1,
        dashed: true,
      });
      addMainLine(lineData("ichimokuLagging"), "Chikou", omiChartColors.textMuted, {
        lineWidth: 1,
        dashed: true,
      });
    }

    if (activeIndicators.supertrend) {
      addMainLine(lineData("supertrendUp"), `ST${params.supertrendAtrPeriod}`, omiChartColors.marketDown, {
        lineWidth: 2,
      });
      addMainLine(lineData("supertrendDown"), `ST${params.supertrendAtrPeriod}`, omiChartColors.marketUp, {
        lineWidth: 2,
      });
    }

    if (activeIndicators.keltner) {
      addMainLine(lineData("keltnerUpper"), `KC${params.keltnerPeriod} U`, omiChartColors.teal, {
        lineWidth: 1,
      });
      addMainLine(lineData("keltnerMiddle"), `KC${params.keltnerPeriod} M`, omiChartColors.tealBright, {
        lineWidth: 1,
        dashed: true,
      });
      addMainLine(lineData("keltnerLower"), `KC${params.keltnerPeriod} L`, omiChartColors.teal, {
        lineWidth: 1,
      });
    }

    if (activeIndicators.pivotPoints) {
      addMainLine(lineData("pivot"), "Pivot", omiChartColors.neutralMuted, { lineWidth: 1, dashed: true });
      addMainLine(lineData("pivotR1"), "R1", omiChartColors.marketUp, { lineWidth: 1, dashed: true });
      addMainLine(lineData("pivotS1"), "S1", omiChartColors.marketDown, { lineWidth: 1, dashed: true });
    }

    if (activeIndicators.supportResistance) {
      addMainLine(lineData("resistance"), `R${params.supportResistanceLookback}`, omiChartColors.marketUpFlash, {
        lineWidth: 1,
        dashed: true,
      });
      addMainLine(lineData("support"), `S${params.supportResistanceLookback}`, omiChartColors.marketDownFlash, {
        lineWidth: 1,
        dashed: true,
      });
    }

    if (activeIndicators.gap) {
      addMainLine(lineData("gapUp"), `Gap Up ${params.gapMinPct}%`, omiChartColors.marketUp, {
        pointsOnly: true,
        lineWidth: 1,
      });
      addMainLine(lineData("gapDown"), `Gap Down ${params.gapMinPct}%`, omiChartColors.marketDown, {
        pointsOnly: true,
        lineWidth: 1,
      });
    }

    if (activeIndicators.rsi) {
      const paneIndex = addIndicatorPane();
      addPaneLine(paneIndex, lineData("rsi"), `RSI${params.rsiPeriod}`, omiChartColors.fuchsia);
    }

    if (activeIndicators.macd) {
      const paneIndex = addIndicatorPane(104);
      const histogramSeries = chart.addSeries(
        HistogramSeries,
        {
          title: "MACD H",
          color: omiChartColors.volumeStrong,
          priceLineVisible: false,
          lastValueVisible: true,
          priceFormat: { type: "price", precision: 2, minMove: 0.01 },
        },
        paneIndex
      );
      registerSeriesDataUpdater((nextData) => histogramSeries.setData(nextData.macdHistogram));
      addPaneLine(paneIndex, lineData("macd"), "MACD", omiChartColors.info, { lineWidth: 1 });
      addPaneLine(paneIndex, lineData("macdSignal"), "Signal", omiChartColors.warning, { lineWidth: 1 });
    }

    if (activeIndicators.kd) {
      const paneIndex = addIndicatorPane();
      addPaneLine(paneIndex, lineData("kdK"), `K${params.kdPeriod}`, omiChartColors.info);
      addPaneLine(paneIndex, lineData("kdD"), `D${params.kdPeriod}`, omiChartColors.warning);
    }

    if (activeIndicators.momentum) {
      const paneIndex = addIndicatorPane();
      addPaneLine(paneIndex, lineData("momentum"), `MOM${params.momentumPeriod}`, omiChartColors.indicator.momentum);
    }

    if (activeIndicators.tsi) {
      const paneIndex = addIndicatorPane();
      addPaneLine(paneIndex, lineData("tsi"), `TSI${params.tsiLongPeriod}/${params.tsiShortPeriod}`, omiChartColors.purple);
      addPaneLine(paneIndex, lineData("tsiSignal"), `TSI Sig${params.tsiSignalPeriod}`, omiChartColors.warning, {
        lineWidth: 1,
      });
    }

    if (activeIndicators.awesomeOscillator) {
      const paneIndex = addIndicatorPane();
      addPaneLine(
        paneIndex,
        lineData("awesomeOscillator"),
        `AO${params.awesomeFastPeriod}/${params.awesomeSlowPeriod}`,
        omiChartColors.pink
      );
    }

    if (activeIndicators.ultimateOscillator) {
      const paneIndex = addIndicatorPane();
      addPaneLine(
        paneIndex,
        lineData("ultimateOscillator"),
        `UO${params.ultimateShortPeriod}/${params.ultimateMiddlePeriod}/${params.ultimateLongPeriod}`,
        omiChartColors.purpleAlt
      );
    }

    if (activeIndicators.atr) {
      const paneIndex = addIndicatorPane();
      addPaneLine(paneIndex, lineData("atr"), `ATR${params.atrPeriod}`, omiChartColors.heat);
    }

    if (activeIndicators.bbWidth) {
      const paneIndex = addIndicatorPane();
      addPaneLine(paneIndex, lineData("bbWidth"), `BB Width${params.bbWidthPeriod}`, omiChartColors.indicator.bollinger);
    }

    if (activeIndicators.stdDev) {
      const paneIndex = addIndicatorPane();
      addPaneLine(paneIndex, lineData("stdDev"), `StdDev${params.stdDevPeriod}`, omiChartColors.neutralLine);
    }

    if (activeIndicators.choppiness) {
      const paneIndex = addIndicatorPane();
      addPaneLine(paneIndex, lineData("choppiness"), `CHOP${params.choppinessPeriod}`, omiChartColors.brown);
    }

    if (activeIndicators.adx) {
      const paneIndex = addIndicatorPane(104);
      addPaneLine(paneIndex, lineData("adx"), `ADX${params.adxPeriod}`, omiChartColors.purple);
      addPaneLine(paneIndex, lineData("plusDi"), "+DI", omiChartColors.marketUp, { lineWidth: 1 });
      addPaneLine(paneIndex, lineData("minusDi"), "-DI", omiChartColors.marketDown, { lineWidth: 1 });
    }

    if (activeIndicators.aroon) {
      const paneIndex = addIndicatorPane();
      addPaneLine(paneIndex, lineData("aroonUp"), `Aroon Up${params.aroonPeriod}`, omiChartColors.marketUp);
      addPaneLine(paneIndex, lineData("aroonDown"), `Aroon Down${params.aroonPeriod}`, omiChartColors.marketDown);
    }

    if (activeIndicators.obv) {
      const paneIndex = addIndicatorPane();
      addPaneLine(paneIndex, lineData("obv"), "OBV", omiChartColors.neutralLine);
      addPaneLine(paneIndex, lineData("obvMa"), `OBV MA${params.obvMa}`, omiChartColors.warning, {
        lineWidth: 1,
      });
    }

    if (activeIndicators.mfi) {
      const paneIndex = addIndicatorPane();
      addPaneLine(paneIndex, lineData("mfi"), `MFI${params.mfiPeriod}`, omiChartColors.teal);
    }

    if (activeIndicators.cmf) {
      const paneIndex = addIndicatorPane();
      addPaneLine(paneIndex, lineData("cmf"), `CMF${params.cmfPeriod}`, omiChartColors.marketDown);
    }

    if (activeIndicators.adLine) {
      const paneIndex = addIndicatorPane();
      addPaneLine(paneIndex, lineData("adLine"), "A/D", omiChartColors.neutralMuted);
    }

    if (activeIndicators.pvt) {
      const paneIndex = addIndicatorPane();
      addPaneLine(paneIndex, lineData("pvt"), "PVT", omiChartColors.skyDark);
    }

    if (activeIndicators.relativeStrength) {
      const paneIndex = addIndicatorPane();
      addPaneLine(
        paneIndex,
        lineData("relativeStrength"),
        `RS${params.relativeStrengthLookback}${benchmarkLabel ? ` vs ${benchmarkLabel}` : ""}`,
        omiChartColors.purple
      );
    }

    if (activeIndicators.beta) {
      const paneIndex = addIndicatorPane();
      addPaneLine(
        paneIndex,
        lineData("beta"),
        `Beta${params.betaPeriod}${benchmarkLabel ? ` vs ${benchmarkLabel}` : ""}`,
        omiChartColors.teal
      );
    }

    if (activeIndicators.correlation) {
      const paneIndex = addIndicatorPane();
      addPaneLine(
        paneIndex,
        lineData("correlation"),
        `Corr${params.correlationPeriod}${benchmarkLabel ? ` vs ${benchmarkLabel}` : ""}`,
        omiChartColors.skyDark
      );
    }

    if (activeIndicators.cci) {
      const paneIndex = addIndicatorPane();
      addPaneLine(paneIndex, lineData("cci"), `CCI${params.cciPeriod}`, omiChartColors.indigo);
    }

    if (activeIndicators.williamsR) {
      const paneIndex = addIndicatorPane();
      addPaneLine(paneIndex, lineData("williamsR"), `W%R${params.williamsRPeriod}`, omiChartColors.pink);
    }

    if (activeIndicators.roc) {
      const paneIndex = addIndicatorPane();
      addPaneLine(paneIndex, lineData("roc"), `ROC${params.rocPeriod}`, omiChartColors.indicator.momentum);
    }

    if (activeIndicators.stochRsi) {
      const paneIndex = addIndicatorPane();
      addPaneLine(paneIndex, lineData("stochRsiK"), "StochRSI K", omiChartColors.info);
      addPaneLine(paneIndex, lineData("stochRsiD"), "StochRSI D", omiChartColors.warning);
    }

    if (activeIndicators.trix) {
      const paneIndex = addIndicatorPane();
      addPaneLine(paneIndex, lineData("trix"), `TRIX${params.trixPeriod}`, omiChartColors.purple);
      addPaneLine(paneIndex, lineData("trixSignal"), `Signal${params.trixSignal}`, omiChartColors.warning, {
        lineWidth: 1,
      });
    }

    chart.panes()[0]?.setStretchFactor(4);
    seriesDataUpdatersRef.current = seriesDataUpdaters;

    const savedLogicalRange =
      visibleLogicalRangeKeyRef.current === chartSeriesKey
        ? visibleLogicalRangeRef.current
        : null;
    const defaultLogicalRange = buildDefaultVisibleLogicalRange(
      latestSeriesDataRef.current.candles.length,
      timeMode
    );

    if (savedLogicalRange) {
      chart.timeScale().setVisibleLogicalRange(savedLogicalRange);
    } else if (defaultLogicalRange) {
      chart.timeScale().setVisibleLogicalRange(defaultLogicalRange);
    } else {
      chart.timeScale().fitContent();
    }

    setOverlaySize((current) => {
      const nextSize = { width: container.clientWidth, height: container.clientHeight || height };

      return current.width === nextSize.width && current.height === nextSize.height
        ? current
        : nextSize;
    });

    const syncOverlay = (logicalRange: LogicalRange | null) => {
      if (logicalRange) {
        visibleLogicalRangeRef.current = {
          from: logicalRange.from,
          to: logicalRange.to,
        };
        visibleLogicalRangeKeyRef.current = chartSeriesKey;
      }

      scheduleOverlayRevision();
    };

    chart.timeScale().subscribeVisibleLogicalRangeChange(syncOverlay);

    const syncOverlayFromPointerGesture = (event: PointerEvent) => {
      if (event.buttons !== 0) {
        scheduleOverlayRevision();
      }
    };
    const syncOverlayFromWheel = () => scheduleOverlayRevision();
    const syncOverlayFromDoubleClick = () => scheduleOverlayRevision();

    container.addEventListener("pointermove", syncOverlayFromPointerGesture);
    container.addEventListener("wheel", syncOverlayFromWheel, { passive: true });
    container.addEventListener("dblclick", syncOverlayFromDoubleClick);

    const resizeObserver = new ResizeObserver(() => {
      const nextHeight = container.clientHeight || height;
      chart.applyOptions({
        autoSize: false,
        width: container.clientWidth,
        height: nextHeight,
      });
      setOverlaySize((current) => {
        const nextSize = { width: container.clientWidth, height: nextHeight };

        return current.width === nextSize.width && current.height === nextSize.height
          ? current
          : nextSize;
      });
      scheduleOverlayRevision();
    });
    resizeObserver.observe(container);
    scheduleOverlayRevision();

    return () => {
      const latestLogicalRange = chart.timeScale().getVisibleLogicalRange();

      if (latestLogicalRange) {
        visibleLogicalRangeRef.current = {
          from: latestLogicalRange.from,
          to: latestLogicalRange.to,
        };
        visibleLogicalRangeKeyRef.current = chartSeriesKey;
      }

      if (overlayRevisionFrameRef.current !== null) {
        window.cancelAnimationFrame(overlayRevisionFrameRef.current);
        overlayRevisionFrameRef.current = null;
      }

      chart.timeScale().unsubscribeVisibleLogicalRangeChange(syncOverlay);
      container.removeEventListener("pointermove", syncOverlayFromPointerGesture);
      container.removeEventListener("wheel", syncOverlayFromWheel);
      container.removeEventListener("dblclick", syncOverlayFromDoubleClick);
      resizeObserver.disconnect();
      chart.remove();
      chartRef.current = null;
      mainSeriesRef.current = null;
      seriesDataUpdatersRef.current = [];
    };
  }, [
    activeIndicators,
    benchmarkLabel,
    chartSeriesKey,
    chartStyle,
    downColor,
    height,
    maColors,
    omiChartColors,
    params,
    priceMinMove,
    pricePrecision,
    resolvedPricePrecision,
    scheduleOverlayRevision,
    timeMode,
    upColor,
    resolvedVolumePanelLabel,
  ]);

  useEffect(() => {
    if (chartInteractionActiveRef.current) {
      pendingSeriesDataRef.current = seriesData;
      return;
    }

    applySeriesDataToChart(seriesData);
  }, [applySeriesDataToChart, seriesData]);

  useEffect(() => {
    window.addEventListener("pointerup", endChartInteraction);
    window.addEventListener("pointercancel", endChartInteraction);
    window.addEventListener("blur", endChartInteraction);

    return () => {
      window.removeEventListener("pointerup", endChartInteraction);
      window.removeEventListener("pointercancel", endChartInteraction);
      window.removeEventListener("blur", endChartInteraction);

      if (chartInteractionEndTimerRef.current !== null) {
        window.clearTimeout(chartInteractionEndTimerRef.current);
        chartInteractionEndTimerRef.current = null;
      }

      chartInteractionActiveRef.current = false;
      pendingSeriesDataRef.current = null;
    };
  }, [endChartInteraction]);

  useEffect(() => {
    restoreChartPointerInteractivity();
  }, [restoreChartPointerInteractivity]);

  return {
    applyChartPointerInteractivity,
    beginChartInteraction,
    chartRef,
    containerRef,
    endChartInteraction,
    getVisibleLogicalRange,
    mainSeriesRef,
    overlayRevision,
    overlaySize,
    rememberVisibleLogicalRange,
    resetVisibleLogicalRangeToLatest,
    restoreChartPointerInteractivity,
    restoreVisibleLogicalRange,
    updateVisibleLogicalRange,
  };
}
