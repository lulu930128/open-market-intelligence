"use client";

import { useT } from "@/i18n";

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
  const t = useT();

  return (
    <div className="flex min-h-9 flex-wrap items-center justify-between gap-x-4 gap-y-1 border-b border-omi-border-subtle px-4 py-1.5">
      <div className="flex min-w-0 items-baseline gap-2">
        <span className="shrink-0 text-xs font-bold text-omi-text-strong">{t("chart.professionalKline")}</span>
        <span className="truncate text-[11px] font-medium text-omi-text-muted">
          {t("chart.draggableZoomable", {
            label,
            count: candleCount.toLocaleString("zh-TW"),
          })}
        </span>
      </div>
      <div className="flex shrink-0 flex-wrap items-center justify-end gap-3 text-[11px] font-semibold text-omi-text-muted">
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
        {volumeEnabled ? <span className="text-omi-text-subtle">{volumePanelLabel}</span> : null}
      </div>
    </div>
  );
}
