"use client";

import { useT } from "@/i18n";

type DrawingMetricDirection = "up" | "down" | "flat" | "unknown";

type DrawingMetricLabels = {
  bars?: string | null;
  duration?: string | null;
  high: string;
  low: string;
  percentChange: string;
  priceDiff: string;
  slope?: string | null;
};

type OptionalAnalysis = {
  labels: Record<string, string>;
};

type DrawingMetricsView = {
  anchoredVwapAnalysis?: OptionalAnalysis | null;
  direction: DrawingMetricDirection;
  fibonacciAnalysis?: OptionalAnalysis | null;
  labels: DrawingMetricLabels;
  lineAnalysis?: OptionalAnalysis | null;
  volumeProfileAnalysis?: OptionalAnalysis | null;
  zoneAnalysis?: OptionalAnalysis | null;
};

type SelectedDrawingMetricsCardProps = {
  drawingType: string;
  metrics: DrawingMetricsView;
  summaryText?: string | null;
};

function metricValueClass(direction: DrawingMetricDirection) {
  if (direction === "up") return "text-omi-market-up";
  if (direction === "down") return "text-omi-market-down";
  return "text-omi-text-muted";
}

function MetricRow({ label, value }: { label: string; value: string }) {
  return (
    <>
      <span>{label}</span>
      <span className="text-right font-semibold text-omi-text tabular-nums">
        {value}
      </span>
    </>
  );
}

export default function SelectedDrawingMetricsCard({
  drawingType,
  metrics,
  summaryText,
}: SelectedDrawingMetricsCardProps) {
  const t = useT();
  const labels = metrics.labels;

  return (
    <div className="pointer-events-none absolute left-3 top-3 z-20 w-[15.5rem] border border-omi-border bg-omi-surface/95 px-3 py-2 text-[11px] shadow-sm backdrop-blur">
      <div className="mb-1 flex items-center justify-between gap-2">
        <span className="font-bold text-omi-text-strong">{drawingType}</span>
        <span className={`font-bold tabular-nums ${metricValueClass(metrics.direction)}`}>
          {labels.percentChange}
        </span>
      </div>
      <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-omi-text-muted">
        <MetricRow label={t("chart.selectedDrawing.priceDiff")} value={labels.priceDiff} />
        <MetricRow label={t("chart.selectedDrawing.range")} value={`${labels.low} - ${labels.high}`} />
        <MetricRow
          label={t("chart.selectedDrawing.barsTime")}
          value={[labels.bars, labels.duration].filter(Boolean).join(" / ") || "-"}
        />
        <MetricRow label={t("chart.selectedDrawing.slope")} value={labels.slope ?? "-"} />

        {metrics.lineAnalysis ? (
          <>
            <MetricRow
              label={t("chart.selectedDrawing.lineStatus")}
              value={`${metrics.lineAnalysis.labels.role} · ${metrics.lineAnalysis.labels.status}`}
            />
            <MetricRow
              label={t("chart.selectedDrawing.distanceToLine")}
              value={`${metrics.lineAnalysis.labels.distance} / ${metrics.lineAnalysis.labels.distancePct}`}
            />
            <MetricRow label={t("chart.selectedDrawing.touches")} value={metrics.lineAnalysis.labels.touchCount} />
          </>
        ) : null}

        {metrics.zoneAnalysis ? (
          <>
            <MetricRow
              label={t("chart.selectedDrawing.zoneStatus")}
              value={`${metrics.zoneAnalysis.labels.role} · ${metrics.zoneAnalysis.labels.status}`}
            />
            <MetricRow
              label={t("chart.selectedDrawing.upperMidLower")}
              value={`${metrics.zoneAnalysis.labels.upper} / ${metrics.zoneAnalysis.labels.mid} / ${metrics.zoneAnalysis.labels.lower}`}
            />
            <MetricRow
              label={t("chart.selectedDrawing.positionWidth")}
              value={`${metrics.zoneAnalysis.labels.position} / ${metrics.zoneAnalysis.labels.widthPct}`}
            />
            <MetricRow
              label={t("chart.selectedDrawing.upperLowerTouches")}
              value={`${metrics.zoneAnalysis.labels.upperTouches} / ${metrics.zoneAnalysis.labels.lowerTouches}`}
            />
            <MetricRow label={t("chart.selectedDrawing.zoneCompression")} value={metrics.zoneAnalysis.labels.compression} />
          </>
        ) : null}

        {metrics.fibonacciAnalysis ? (
          <>
            <MetricRow
              label={t("chart.selectedDrawing.fibStatus")}
              value={`${metrics.fibonacciAnalysis.labels.trend} · ${metrics.fibonacciAnalysis.labels.status}`}
            />
            <MetricRow label={t("chart.selectedDrawing.nearestLevel")} value={metrics.fibonacciAnalysis.labels.nearest} />
            <MetricRow
              label={t("chart.selectedDrawing.levelDistance")}
              value={`${metrics.fibonacciAnalysis.labels.nearestDistance} / ${metrics.fibonacciAnalysis.labels.nearestDistancePct}`}
            />
            <MetricRow
              label={t("chart.selectedDrawing.positionExtension")}
              value={`${metrics.fibonacciAnalysis.labels.rangePosition} / ${metrics.fibonacciAnalysis.labels.extension}`}
            />
          </>
        ) : null}

        {metrics.anchoredVwapAnalysis ? (
          <>
            <MetricRow label={t("chart.selectedDrawing.anchoredVwap")} value={metrics.anchoredVwapAnalysis.labels.vwap} />
            <MetricRow label={t("chart.selectedDrawing.vwapStatus")} value={metrics.anchoredVwapAnalysis.labels.status} />
            <MetricRow
              label={t("chart.selectedDrawing.distanceToVwap")}
              value={`${metrics.anchoredVwapAnalysis.labels.distance} / ${metrics.anchoredVwapAnalysis.labels.distancePct}`}
            />
            <MetricRow
              label={t("chart.selectedDrawing.volumeBars")}
              value={`${metrics.anchoredVwapAnalysis.labels.cumulativeVolume} / ${metrics.anchoredVwapAnalysis.labels.barCount}`}
            />
          </>
        ) : null}

        {metrics.volumeProfileAnalysis ? (
          <>
            <MetricRow label="POC" value={metrics.volumeProfileAnalysis.labels.poc} />
            <MetricRow label={t("chart.selectedDrawing.valueArea")} value={metrics.volumeProfileAnalysis.labels.valueArea} />
            <MetricRow label={t("chart.selectedDrawing.latestPosition")} value={metrics.volumeProfileAnalysis.labels.latestPosition} />
            <MetricRow label={t("chart.selectedDrawing.imbalance")} value={metrics.volumeProfileAnalysis.labels.imbalance} />
          </>
        ) : null}
      </div>
      {summaryText ? (
        <div className="mt-2 border-t border-omi-border-subtle pt-1 text-[10px] font-medium leading-relaxed text-omi-text-muted">
          {summaryText}
        </div>
      ) : null}
    </div>
  );
}
