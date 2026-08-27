"use client";

import {
  professionalChartDrawingToolGroups,
  professionalChartDrawingToolOptionMap,
} from "@/components/professionalChartDrawing";
import { LoadingStateSurface } from "@/components/LoadingPlaceholders";
import type { IndicatorParameters, IndicatorSettings } from "@/components/StockKLineChart";
import type {
  ChartDrawing,
  ChartDrawingContext,
  ChartDrawingTool,
  ChartTimeMode,
} from "@/components/LightweightKLineChart";
import type { ChartPoint, StockIndicatorPoint } from "@/types/market";
import type { CanonicalIndicatorAuthority } from "@/components/stock-k-line/indicatorAuthority";
import type { ChartEventMarker } from "@/components/chart/chartEventMarkers";
import { useT } from "@/i18n";
import dynamic from "next/dynamic";
import type { ReactNode } from "react";

function ChartEngineLoading() {
  const t = useT();

  return (
    <div className="flex h-[640px] items-center justify-center border-t border-omi-border-subtle bg-omi-surface p-4">
      <LoadingStateSurface title={t("chart.engineLoading")} className="w-full max-w-xl" />
    </div>
  );
}

const LightweightKLineChart = dynamic(
  () => import("@/components/LightweightKLineChart"),
  {
    ssr: false,
    loading: () => <ChartEngineLoading />,
  }
);

export type ProfessionalChartStyle = "candlestick" | "line";

export type ProfessionalChartTimeframeOption<TTimeframe extends string> = {
  key: TTimeframe;
  label: string;
};

type Props<TTimeframe extends string> = {
  title: ReactNode;
  priceSummary?: ReactNode;
  timeframeOptions: Array<ProfessionalChartTimeframeOption<TTimeframe>>;
  timeframe: TTimeframe;
  onTimeframeChange: (timeframe: TTimeframe) => void;
  chartStyle: ProfessionalChartStyle;
  onChartStyleChange: (style: ProfessionalChartStyle) => void;
  indicatorMenu?: ReactNode;
  indicatorMenuOpen: boolean;
  onToggleIndicatorMenu: () => void;
  onCloseIndicatorMenu?: () => void;
  onClose: () => void;
  message?: ReactNode;
  drawingToolbarStart?: ReactNode;
  chartReady: boolean;
  emptyState?: ReactNode;
  chartData: ChartPoint[];
  indicatorData?: StockIndicatorPoint[];
  label: string;
  timeMode: ChartTimeMode;
  showMovingAverages: boolean;
  indicators: IndicatorSettings;
  indicatorParameters: IndicatorParameters;
  benchmarkData?: ChartPoint[];
  benchmarkLabel?: string;
  eventMarkers?: ChartEventMarker[];
  volumePanelLabel?: string;
  volumeValueKey?: "volume" | "trade_value";
  pricePrecision?: number;
  canonicalIndicatorAuthority?: CanonicalIndicatorAuthority;
  drawingTool: ChartDrawingTool;
  drawings: ChartDrawing[];
  selectedDrawingId: string | null;
  drawingContext: Omit<ChartDrawingContext, "label" | "timeMode" | "updatedAt">;
  onDrawingToolChange: (tool: ChartDrawingTool) => void;
  onDrawingsChange: (drawings: ChartDrawing[]) => void;
  onDrawingStateChange: (drawings: ChartDrawing[], selectedDrawingId: string | null) => void;
  onSelectedDrawingChange: (drawingId: string | null) => void;
  canUndoDrawing: boolean;
  canRedoDrawing: boolean;
  onUndoDrawing: () => void;
  onRedoDrawing: () => void;
  onDeleteSelectedDrawing: () => void;
  onClearDrawings: () => void;
  historyCounts?: {
    past: number;
    future: number;
  };
};

export default function ProfessionalChartPanel<TTimeframe extends string>({
  benchmarkData,
  benchmarkLabel,
  canRedoDrawing,
  canUndoDrawing,
  chartData,
  chartReady,
  chartStyle,
  drawingContext,
  drawingTool,
  drawingToolbarStart,
  drawings,
  emptyState,
  eventMarkers,
  historyCounts,
  indicatorData,
  indicatorMenu,
  indicatorMenuOpen,
  indicatorParameters,
  indicators,
  label,
  message,
  onChartStyleChange,
  onClearDrawings,
  onClose,
  onCloseIndicatorMenu,
  onDeleteSelectedDrawing,
  onDrawingStateChange,
  onDrawingToolChange,
  onDrawingsChange,
  onRedoDrawing,
  onSelectedDrawingChange,
  onTimeframeChange,
  onToggleIndicatorMenu,
  onUndoDrawing,
  pricePrecision,
  canonicalIndicatorAuthority,
  priceSummary,
  selectedDrawingId,
  showMovingAverages,
  timeframe,
  timeframeOptions,
  timeMode,
  title,
  volumePanelLabel,
  volumeValueKey,
}: Props<TTimeframe>) {
  const t = useT();

  return (
    <section
      className="border border-omi-border-subtle bg-omi-surface"
      data-testid="professional-chart-panel"
    >
      <div className="border-b border-omi-border-subtle px-4 py-2">
        <div className="flex min-h-9 flex-wrap items-center justify-between gap-x-4 gap-y-2">
          <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
            <div className="truncate text-lg font-bold text-omi-text-strong">{title}</div>
            {priceSummary ? <div className="min-w-0">{priceSummary}</div> : null}
          </div>

          <div className="flex flex-wrap items-center justify-end gap-1.5">
            <div className="flex flex-wrap items-center gap-1.5">
              <div className="flex border border-omi-border-subtle bg-omi-surface-subtle p-0.5">
                {timeframeOptions.map((option) => (
                  <button
                    key={option.key}
                    type="button"
                    onClick={() => onTimeframeChange(option.key)}
                    className={[
                      "h-7 px-2 text-xs font-semibold transition",
                      timeframe === option.key
                        ? "bg-omi-control text-omi-text-inverse"
                        : "text-omi-text-muted hover:bg-omi-surface hover:text-omi-text-strong",
                    ].join(" ")}
                  >
                    {option.label}
                  </button>
                ))}
              </div>

              <div className="flex border border-omi-border-subtle bg-omi-surface-subtle p-0.5">
                {[
                  ["candlestick", t("chart.candlestick")],
                  ["line", t("chart.line")],
                ].map(([key, labelText]) => (
                  <button
                    key={key}
                    type="button"
                    onClick={() => onChartStyleChange(key as ProfessionalChartStyle)}
                    className={[
                      "h-7 px-2 text-xs font-semibold transition",
                      chartStyle === key
                        ? "bg-omi-control text-omi-text-inverse"
                        : "text-omi-text-muted hover:bg-omi-surface hover:text-omi-text-strong",
                    ].join(" ")}
                  >
                    {labelText}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <button
                type="button"
                data-testid="chart-indicator-menu-toggle"
                onClick={onToggleIndicatorMenu}
                className="h-8 border border-omi-border bg-omi-surface px-3 text-xs font-semibold text-omi-text hover:border-omi-control hover:text-omi-text-strong"
              >
                {t("chart.indicators")}
              </button>
            </div>

            <button
              type="button"
              onClick={onClose}
              className="h-8 border border-omi-control bg-omi-control px-3 text-xs font-semibold text-omi-text-inverse hover:bg-omi-control-muted"
            >
              {t("common.backToOverview")}
            </button>
          </div>
        </div>

        <div className="mt-2 flex flex-wrap items-center justify-end gap-1.5 border-t border-omi-border-subtle pt-2">
          <div className="flex max-w-full flex-wrap items-center justify-end gap-1 border border-omi-border-subtle bg-omi-surface-subtle p-0.5">
            {drawingToolbarStart ? (
              <div className="flex items-center gap-0.5 border-r border-omi-border-subtle pr-1">
                {drawingToolbarStart}
              </div>
            ) : null}
            {professionalChartDrawingToolGroups.map((group, groupIndex) => (
              <div
                key={group.key}
                className={[
                  "flex items-center gap-0.5",
                  groupIndex > 0 ? "border-l border-omi-border-subtle pl-1" : "",
                ].join(" ")}
              >
                {group.tools.map((toolKey) => {
                  const option = professionalChartDrawingToolOptionMap.get(toolKey);
                  if (!option) return null;

                  return (
                    <button
                      key={option.key}
                      type="button"
                      data-drawing-tool-option={option.key}
                      onClick={() => {
                        onCloseIndicatorMenu?.();
                        onDrawingToolChange(option.key);
                        if (option.key === "cursor") {
                          onSelectedDrawingChange(null);
                        }
                      }}
                      className={[
                        "h-7 px-2 text-xs font-semibold transition",
                        drawingTool === option.key
                          ? "bg-omi-control text-omi-text-inverse"
                          : "text-omi-text-muted hover:bg-omi-surface hover:text-omi-text-strong",
                      ].join(" ")}
                    >
                      {t(option.labelKey)}
                    </button>
                  );
                })}
              </div>
            ))}
            <div className="flex items-center gap-0.5 border-l border-omi-border-subtle pl-1">
              <button
                type="button"
                title="Undo (Ctrl+Z)"
                data-testid="chart-drawing-undo"
                disabled={!canUndoDrawing}
                onClick={onUndoDrawing}
                className={[
                  "h-7 px-2 text-xs font-semibold transition",
                  canUndoDrawing
                    ? "text-omi-text-muted hover:bg-omi-surface hover:text-omi-text-strong"
                    : "cursor-not-allowed text-omi-text-inverse-muted",
                ].join(" ")}
              >
                Undo
              </button>
              <button
                type="button"
                title="Redo (Ctrl+Y)"
                disabled={!canRedoDrawing}
                onClick={onRedoDrawing}
                className={[
                  "h-7 px-2 text-xs font-semibold transition",
                  canRedoDrawing
                    ? "text-omi-text-muted hover:bg-omi-surface hover:text-omi-text-strong"
                    : "cursor-not-allowed text-omi-text-inverse-muted",
                ].join(" ")}
              >
                Redo
              </button>
              <button
                type="button"
                data-testid="chart-drawing-delete"
                disabled={!selectedDrawingId}
                onClick={onDeleteSelectedDrawing}
                className={[
                  "h-7 px-2 text-xs font-semibold transition",
                  selectedDrawingId
                    ? "text-omi-danger hover:bg-omi-surface"
                    : "cursor-not-allowed text-omi-text-inverse-muted",
                ].join(" ")}
              >
                {t("chart.delete")}
              </button>
              <button
                type="button"
                disabled={drawings.length === 0}
                data-testid="chart-drawing-clear"
                onClick={onClearDrawings}
                className={[
                  "h-7 px-2 text-xs font-semibold transition",
                  drawings.length > 0
                    ? "text-omi-text-muted hover:bg-omi-surface hover:text-omi-text-strong"
                    : "cursor-not-allowed text-omi-text-inverse-muted",
                ].join(" ")}
              >
                {t("chart.drawingCount", { count: drawings.length })}
              </button>
              {historyCounts ? (
                <span className="hidden h-7 items-center border-l border-omi-border-subtle px-2 text-[11px] font-semibold tabular-nums text-omi-text-subtle min-[1500px]:inline-flex">
                  {historyCounts.past}/{historyCounts.future}
                </span>
              ) : null}
            </div>
          </div>
        </div>

        {indicatorMenuOpen && indicatorMenu ? (
          <div className="relative h-0">{indicatorMenu}</div>
        ) : null}
      </div>

      {message}

      {chartReady ? (
        <LightweightKLineChart
          key={[
            timeMode,
            drawingContext.market ?? "",
            drawingContext.symbol ?? label,
            drawingContext.timeframe,
          ].join(":")}
          chartData={chartData}
          indicatorData={indicatorData}
          label={label}
          height={780}
          fillViewport
          timeMode={timeMode}
          chartStyle={chartStyle}
          showHeader={false}
          showMovingAverages={showMovingAverages}
          indicators={indicators}
          indicatorParameters={indicatorParameters}
          benchmarkData={benchmarkData}
          benchmarkLabel={benchmarkLabel}
          eventMarkers={eventMarkers}
          volumePanelLabel={volumePanelLabel}
          volumeValueKey={volumeValueKey}
          pricePrecision={pricePrecision}
          canonicalIndicatorAuthority={canonicalIndicatorAuthority}
          drawingTool={drawingTool}
          drawings={drawings}
          selectedDrawingId={selectedDrawingId}
          drawingContext={drawingContext}
          onDrawingsChange={onDrawingsChange}
          onDrawingStateChange={onDrawingStateChange}
          onSelectedDrawingChange={onSelectedDrawingChange}
        />
      ) : (
        emptyState ?? (
          <div className="flex h-[640px] items-center justify-center border-t border-omi-border-subtle p-4">
            <LoadingStateSurface
              title={t("chart.loadingKline", { label })}
              className="w-full max-w-xl"
            />
          </div>
        )
      )}
    </section>
  );
}
