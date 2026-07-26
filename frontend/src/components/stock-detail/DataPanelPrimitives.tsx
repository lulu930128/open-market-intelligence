"use client";

import {
  LoadingStateSurface,
  StateSurface,
  type StateSurfaceTone,
} from "@/components/LoadingPlaceholders";
import type { DataPanelTab } from "@/components/stock-detail/stockDetailTypes";
import type { ReactNode } from "react";

export function MetricRow({
  label,
  value,
  tone = "text-omi-text",
}: {
  label: string;
  value: string;
  tone?: string;
}) {
  return (
    <div className="flex items-center justify-between gap-4 border-t border-omi-border-subtle py-2 text-xs">
      <span className="text-omi-text-muted">{label}</span>
      <span className={`font-semibold ${tone}`}>{value}</span>
    </div>
  );
}

export function ChipMetricBlock({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="border border-omi-border-subtle bg-omi-surface px-3 py-2">
      <div className="text-xs font-bold text-omi-text">{title}</div>
      <div className="mt-1">{children}</div>
    </div>
  );
}

export function DataTabIcon({ type }: { type: DataPanelTab }) {
  if (type === "institutional") {
    return (
      <svg viewBox="0 0 20 20" className="h-5 w-5" aria-hidden="true">
        <path
          d="M3 8h14v2H3V8Zm1 3h2v5H4v-5Zm5 0h2v5H9v-5Zm5 0h2v5h-2v-5ZM2 17h16v1H2v-1ZM10 2l7 4H3l7-4Z"
          fill="currentColor"
        />
      </svg>
    );
  }

  if (type === "branch") {
    return (
      <svg viewBox="0 0 20 20" className="h-5 w-5" aria-hidden="true">
        <path
          d="M3 8.5 10 4l7 4.5V17H3V8.5Zm2 1.1V15h10V9.6L10 6.4 5 9.6ZM7 11h2v4H7v-4Zm4 0h2v4h-2v-4Z"
          fill="currentColor"
        />
      </svg>
    );
  }

  if (type === "revenue") {
    return (
      <svg viewBox="0 0 20 20" className="h-5 w-5" aria-hidden="true">
        <path
          d="M10.8 2v2.1c1.9.3 3.2 1.4 3.2 3.1h-2c0-.8-.8-1.3-2-1.3-1.3 0-2 .5-2 1.2 0 .8.8 1.1 2.6 1.5 2 .5 3.8 1.2 3.8 3.4 0 1.8-1.4 3-3.6 3.3V18H8.9v-2.6c-2.2-.3-3.7-1.5-3.7-3.4h2c0 1 1 1.6 2.4 1.6 1.6 0 2.5-.6 2.5-1.5 0-.8-.7-1.2-2.8-1.7-1.9-.5-3.5-1.2-3.5-3.2 0-1.7 1.3-2.8 3.1-3.1V2h1.9Z"
          fill="currentColor"
        />
      </svg>
    );
  }

  if (type === "earnings") {
    return (
      <svg viewBox="0 0 20 20" className="h-5 w-5" aria-hidden="true">
        <path
          d="M11 2v4h4v2h-4v2h3.5a2.5 2.5 0 0 1 0 5H11v3H9v-3H5v-2h4v-3H5V8h4V6H5V4h4V2h2Zm0 10v1h3.5a.5.5 0 0 0 0-1H11Z"
          fill="currentColor"
        />
      </svg>
    );
  }

  return (
    <svg viewBox="0 0 20 20" className="h-5 w-5" aria-hidden="true">
      <path
        d="M10 2c3.3 0 6 1 6 2.3S13.3 6.6 10 6.6 4 5.6 4 4.3 6.7 2 10 2Zm-6 4.2c1.2 1 3.4 1.5 6 1.5s4.8-.6 6-1.5v2.1c0 1.3-2.7 2.3-6 2.3s-6-1-6-2.3V6.2Zm0 4c1.2 1 3.4 1.5 6 1.5s4.8-.6 6-1.5v2.1c0 1.3-2.7 2.3-6 2.3s-6-1-6-2.3v-2.1Zm0 4c1.2 1 3.4 1.5 6 1.5s4.8-.6 6-1.5v1.5c0 1.3-2.7 2.3-6 2.3s-6-1-6-2.3v-1.5Z"
        fill="currentColor"
      />
    </svg>
  );
}

export function DataTabButton({
  tab,
  active,
  onClick,
}: {
  tab: { key: DataPanelTab; label: string };
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      data-data-tab={tab.key}
      onClick={onClick}
      className={[
        "omi-data-tab flex h-11 min-w-0 flex-1 items-center justify-center gap-2 border-r border-omi-border-subtle text-sm font-semibold transition last:border-r-0",
        active
          ? "omi-data-tab-active bg-omi-surface text-omi-text-strong"
          : "bg-omi-surface-subtle text-omi-text-muted hover:bg-omi-surface hover:text-omi-text",
      ].join(" ")}
    >
      <DataTabIcon type={tab.key} />
      <span>{tab.label}</span>
    </button>
  );
}

export function EmptyDataState({
  message,
  tone = "empty",
  busy = false,
  className = "",
}: {
  message: string;
  tone?: StateSurfaceTone;
  busy?: boolean;
  className?: string;
}) {
  return (
    <StateSurface title={message} tone={tone} busy={busy} compact className={className} />
  );
}

export function DataPanelLoadingState({ message }: { message: string }) {
  return (
    <div className="omi-tab-panel omi-loading-surface border border-omi-border-subtle bg-omi-surface px-4 py-5">
      <LoadingStateSurface title={message} compact className="mb-4" />
      <div className="space-y-3">
        <div className="omi-skeleton h-3 w-2/3" />
        <div className="grid grid-cols-3 gap-3">
          <div className="omi-skeleton h-16" />
          <div className="omi-skeleton h-16" />
          <div className="omi-skeleton h-16" />
        </div>
        <div className="omi-skeleton h-44" />
      </div>
    </div>
  );
}

export function DataPanelRefreshRail({ message }: { message: string | null }) {
  return (
    <div className="pointer-events-none absolute inset-x-0 top-0 z-10">
      <div className="h-0.5 overflow-hidden bg-omi-surface-muted">
        <div className="omi-loading-bar h-full w-1/3 bg-omi-accent" />
      </div>
      {message ? (
        <div className="absolute right-0 top-2 max-w-[70%] truncate bg-omi-surface/90 px-2 py-1 text-[11px] font-medium text-omi-text-muted shadow-sm ring-1 ring-omi-border-subtle">
          {message}
        </div>
      ) : null}
    </div>
  );
}

export function SegmentedNumberButtons({
  label,
  suffix,
  options,
  value,
  onChange,
}: {
  label: string;
  suffix: string;
  options: number[];
  value: number;
  onChange: (value: number) => void;
}) {
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="w-24 shrink-0 text-right font-semibold text-omi-text-muted">{label}</span>
      <div className="grid flex-1 grid-cols-6 overflow-hidden border border-omi-border-strong">
        {options.map((option) => (
          <button
            key={option}
            type="button"
            onClick={() => onChange(option)}
            className={[
              "h-7 border-r border-omi-border-strong text-xs font-semibold last:border-r-0",
              value === option
                ? "bg-omi-control-border text-omi-text-inverse"
                : "bg-omi-surface text-omi-text hover:bg-omi-surface-subtle",
            ].join(" ")}
          >
            {option}
          </button>
        ))}
      </div>
      <span className="w-4 shrink-0 text-omi-text-muted">{suffix}</span>
    </div>
  );
}
