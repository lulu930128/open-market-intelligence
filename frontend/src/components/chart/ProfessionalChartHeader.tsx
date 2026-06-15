"use client";

type ProfessionalChartHeaderProps = {
  candleCount: number;
  label: string;
  maColors: {
    maShort: string;
    maMiddle: string;
    maLong: string;
  };
  maEnabled: boolean;
  maLong: number;
  maMiddle: number;
  maShort: number;
  volumeEnabled: boolean;
  volumePanelLabel: string;
};

function LegendDot({ color }: { color: string }) {
  return (
    <span
      className="h-1.5 w-1.5 rounded-full"
      style={{ backgroundColor: color }}
    />
  );
}

export default function ProfessionalChartHeader({
  candleCount,
  label,
  maColors,
  maEnabled,
  maLong,
  maMiddle,
  maShort,
  volumeEnabled,
  volumePanelLabel,
}: ProfessionalChartHeaderProps) {
  return (
    <div className="flex min-h-9 flex-wrap items-center justify-between gap-x-4 gap-y-1 border-b border-slate-200 px-4 py-1.5">
      <div className="flex min-w-0 items-baseline gap-2">
        <span className="shrink-0 text-xs font-bold text-slate-950">專業 K 線</span>
        <span className="truncate text-[11px] font-medium text-slate-500">
          {label} · {candleCount.toLocaleString("zh-TW")} 根 · 可拖移縮放
        </span>
      </div>
      <div className="flex shrink-0 flex-wrap items-center justify-end gap-3 text-[11px] font-semibold text-slate-600">
        {maEnabled ? (
          <>
            <span className="inline-flex items-center gap-1">
              <LegendDot color={maColors.maShort} />
              MA{maShort}
            </span>
            <span className="inline-flex items-center gap-1">
              <LegendDot color={maColors.maMiddle} />
              MA{maMiddle}
            </span>
            <span className="inline-flex items-center gap-1">
              <LegendDot color={maColors.maLong} />
              MA{maLong}
            </span>
          </>
        ) : null}
        {volumeEnabled ? <span className="text-slate-400">{volumePanelLabel}</span> : null}
      </div>
    </div>
  );
}
