"use client";

import {
  professionalChartDrawingToolGroups,
  professionalChartDrawingToolOptionMap,
} from "@/components/professionalChartDrawing";
import type { IndicatorParameters, IndicatorSettings } from "@/components/StockKLineChart";
import type {
  ChartDrawing,
  ChartDrawingContext,
  ChartDrawingTool,
  ChartTimeMode,
} from "@/components/LightweightKLineChart";
import type { ChartPoint, StockIndicatorPoint } from "@/types/market";
import dynamic from "next/dynamic";
import type { ReactNode } from "react";

const LightweightKLineChart = dynamic(
  () => import("@/components/LightweightKLineChart"),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-[640px] items-center justify-center border-t border-slate-200 bg-white text-sm text-slate-500">
        K 線引擎載入中...
      </div>
    ),
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
  volumePanelLabel?: string;
  volumeValueKey?: "volume" | "trade_value";
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
  drawings,
  emptyState,
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
  return (
    <section className="border border-slate-200 bg-white">
      <div className="border-b border-slate-200 px-4 py-2">
        <div className="flex min-h-9 flex-wrap items-center justify-between gap-x-4 gap-y-2">
          <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
            <div className="truncate text-lg font-bold text-slate-950">{title}</div>
            {priceSummary ? <div className="min-w-0">{priceSummary}</div> : null}
          </div>

          <div className="flex flex-wrap items-center justify-end gap-1.5">
            <div className="flex flex-wrap items-center gap-1.5">
              <div className="flex border border-slate-200 bg-slate-50 p-0.5">
                {timeframeOptions.map((option) => (
                  <button
                    key={option.key}
                    type="button"
                    onClick={() => onTimeframeChange(option.key)}
                    className={[
                      "h-7 px-2 text-xs font-semibold transition",
                      timeframe === option.key
                        ? "bg-slate-900 text-white"
                        : "text-slate-600 hover:bg-white hover:text-slate-950",
                    ].join(" ")}
                  >
                    {option.label}
                  </button>
                ))}
              </div>

              <div className="flex border border-slate-200 bg-slate-50 p-0.5">
                {[
                  ["candlestick", "K線"],
                  ["line", "折線"],
                ].map(([key, labelText]) => (
                  <button
                    key={key}
                    type="button"
                    onClick={() => onChartStyleChange(key as ProfessionalChartStyle)}
                    className={[
                      "h-7 px-2 text-xs font-semibold transition",
                      chartStyle === key
                        ? "bg-slate-900 text-white"
                        : "text-slate-600 hover:bg-white hover:text-slate-950",
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
                onClick={onToggleIndicatorMenu}
                className="h-8 border border-slate-300 bg-white px-3 text-xs font-semibold text-slate-800 hover:border-slate-900 hover:text-slate-950"
              >
                技術指標
              </button>
            </div>

            <button
              type="button"
              onClick={onClose}
              className="h-8 border border-slate-900 bg-slate-900 px-3 text-xs font-semibold text-white hover:bg-slate-800"
            >
              總覽
            </button>
          </div>
        </div>

        <div className="mt-2 flex flex-wrap items-center justify-end gap-1.5 border-t border-slate-100 pt-2">
          <div className="flex max-w-full flex-wrap items-center justify-end gap-1 border border-slate-200 bg-slate-50 p-0.5">
            {professionalChartDrawingToolGroups.map((group, groupIndex) => (
              <div
                key={group.key}
                className={[
                  "flex items-center gap-0.5",
                  groupIndex > 0 ? "border-l border-slate-200 pl-1" : "",
                ].join(" ")}
              >
                {group.tools.map((toolKey) => {
                  const option = professionalChartDrawingToolOptionMap.get(toolKey);
                  if (!option) return null;

                  return (
                    <button
                      key={option.key}
                      type="button"
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
                          ? "bg-slate-900 text-white"
                          : "text-slate-600 hover:bg-white hover:text-slate-950",
                      ].join(" ")}
                    >
                      {option.label}
                    </button>
                  );
                })}
              </div>
            ))}
            <div className="flex items-center gap-0.5 border-l border-slate-200 pl-1">
              <button
                type="button"
                title="Undo (Ctrl+Z)"
                disabled={!canUndoDrawing}
                onClick={onUndoDrawing}
                className={[
                  "h-7 px-2 text-xs font-semibold transition",
                  canUndoDrawing
                    ? "text-slate-600 hover:bg-white hover:text-slate-950"
                    : "cursor-not-allowed text-slate-300",
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
                    ? "text-slate-600 hover:bg-white hover:text-slate-950"
                    : "cursor-not-allowed text-slate-300",
                ].join(" ")}
              >
                Redo
              </button>
              <button
                type="button"
                disabled={!selectedDrawingId}
                onClick={onDeleteSelectedDrawing}
                className={[
                  "h-7 px-2 text-xs font-semibold transition",
                  selectedDrawingId
                    ? "text-red-700 hover:bg-white"
                    : "cursor-not-allowed text-slate-300",
                ].join(" ")}
              >
                刪除
              </button>
              <button
                type="button"
                disabled={drawings.length === 0}
                onClick={onClearDrawings}
                className={[
                  "h-7 px-2 text-xs font-semibold transition",
                  drawings.length > 0
                    ? "text-slate-500 hover:bg-white hover:text-slate-950"
                    : "cursor-not-allowed text-slate-300",
                ].join(" ")}
              >
                畫線 {drawings.length}
              </button>
              {historyCounts ? (
                <span className="hidden h-7 items-center border-l border-slate-200 px-2 text-[11px] font-semibold tabular-nums text-slate-400 min-[1500px]:inline-flex">
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
          volumePanelLabel={volumePanelLabel}
          volumeValueKey={volumeValueKey}
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
          <div className="flex h-[640px] items-center justify-center border-t border-slate-200 text-sm text-slate-500">
            讀取{label} K 線中...
          </div>
        )
      )}
    </section>
  );
}
