"use client";

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
        <MetricRow label="價差" value={labels.priceDiff} />
        <MetricRow label="區間" value={`${labels.low} - ${labels.high}`} />
        <MetricRow
          label="K棒 / 時間"
          value={[labels.bars, labels.duration].filter(Boolean).join(" / ") || "-"}
        />
        <MetricRow label="斜率" value={labels.slope ?? "-"} />

        {metrics.lineAnalysis ? (
          <>
            <MetricRow
              label="線位狀態"
              value={`${metrics.lineAnalysis.labels.role} · ${metrics.lineAnalysis.labels.status}`}
            />
            <MetricRow
              label="距線"
              value={`${metrics.lineAnalysis.labels.distance} / ${metrics.lineAnalysis.labels.distancePct}`}
            />
            <MetricRow label="觸碰" value={metrics.lineAnalysis.labels.touchCount} />
          </>
        ) : null}

        {metrics.zoneAnalysis ? (
          <>
            <MetricRow
              label="區間狀態"
              value={`${metrics.zoneAnalysis.labels.role} · ${metrics.zoneAnalysis.labels.status}`}
            />
            <MetricRow
              label="上 / 中 / 下"
              value={`${metrics.zoneAnalysis.labels.upper} / ${metrics.zoneAnalysis.labels.mid} / ${metrics.zoneAnalysis.labels.lower}`}
            />
            <MetricRow
              label="位置 / 寬度"
              value={`${metrics.zoneAnalysis.labels.position} / ${metrics.zoneAnalysis.labels.widthPct}`}
            />
            <MetricRow
              label="上 / 下觸碰"
              value={`${metrics.zoneAnalysis.labels.upperTouches} / ${metrics.zoneAnalysis.labels.lowerTouches}`}
            />
            <MetricRow label="區間波動" value={metrics.zoneAnalysis.labels.compression} />
          </>
        ) : null}

        {metrics.fibonacciAnalysis ? (
          <>
            <MetricRow
              label="Fib 狀態"
              value={`${metrics.fibonacciAnalysis.labels.trend} · ${metrics.fibonacciAnalysis.labels.status}`}
            />
            <MetricRow label="最近位階" value={metrics.fibonacciAnalysis.labels.nearest} />
            <MetricRow
              label="距位階"
              value={`${metrics.fibonacciAnalysis.labels.nearestDistance} / ${metrics.fibonacciAnalysis.labels.nearestDistancePct}`}
            />
            <MetricRow
              label="位置 / 延伸"
              value={`${metrics.fibonacciAnalysis.labels.rangePosition} / ${metrics.fibonacciAnalysis.labels.extension}`}
            />
          </>
        ) : null}

        {metrics.anchoredVwapAnalysis ? (
          <>
            <MetricRow label="錨定 VWAP" value={metrics.anchoredVwapAnalysis.labels.vwap} />
            <MetricRow label="VWAP 狀態" value={metrics.anchoredVwapAnalysis.labels.status} />
            <MetricRow
              label="距 VWAP"
              value={`${metrics.anchoredVwapAnalysis.labels.distance} / ${metrics.anchoredVwapAnalysis.labels.distancePct}`}
            />
            <MetricRow
              label="累積量 / K棒"
              value={`${metrics.anchoredVwapAnalysis.labels.cumulativeVolume} / ${metrics.anchoredVwapAnalysis.labels.barCount}`}
            />
          </>
        ) : null}

        {metrics.volumeProfileAnalysis ? (
          <>
            <MetricRow label="POC" value={metrics.volumeProfileAnalysis.labels.poc} />
            <MetricRow label="價值區間" value={metrics.volumeProfileAnalysis.labels.valueArea} />
            <MetricRow label="現價位置" value={metrics.volumeProfileAnalysis.labels.latestPosition} />
            <MetricRow label="買賣差" value={metrics.volumeProfileAnalysis.labels.imbalance} />
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
