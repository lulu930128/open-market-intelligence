import type { ReactNode } from "react";

import type {
  MarketResourceSlotStatusValue,
  ResourceSlotTabItem,
} from "@/components/market-detail/types";

type ResourceSlotLabels = {
  eyebrow: string;
  status: string;
  source: string;
  latestDate: string;
  rows: string;
  reserved: string;
};

type Props<TSlotKey extends string> = {
  activeKey: TSlotKey;
  labels: ResourceSlotLabels;
  onActiveKeyChange: (key: TSlotKey) => void;
  slots: Array<ResourceSlotTabItem<TSlotKey>>;
  statusLabel: (status: MarketResourceSlotStatusValue) => string;
  statusToneClass?: (status: MarketResourceSlotStatusValue) => string;
  footer?: ReactNode;
};

function defaultStatusToneClass(status: MarketResourceSlotStatusValue) {
  if (status === "available") return "text-omi-market-down";
  if (status === "empty" || status === "stale") return "text-omi-warning";
  if (status === "error") return "text-omi-danger";
  if (status === "loading") return "text-omi-accent";
  return "text-omi-text-muted";
}

export default function ResourceSlotTabs<TSlotKey extends string>({
  activeKey,
  labels,
  onActiveKeyChange,
  slots,
  statusLabel,
  statusToneClass = defaultStatusToneClass,
  footer,
}: Props<TSlotKey>) {
  const activeSlot = slots.find((slot) => slot.key === activeKey) ?? slots[0];

  if (!activeSlot) return null;

  return (
    <section className="border-t border-omi-border-subtle">
      <div
        className="grid border-b border-omi-border-subtle bg-omi-surface-subtle"
        style={{ gridTemplateColumns: `repeat(${Math.max(slots.length, 1)}, minmax(0, 1fr))` }}
      >
        {slots.map((slot) => (
          <button
            key={slot.key}
            type="button"
            onClick={() => onActiveKeyChange(slot.key)}
            className={[
              "h-11 border-r border-omi-border-subtle text-xs font-bold text-omi-text-muted last:border-r-0 hover:text-omi-text-strong",
              activeKey === slot.key
                ? "border-b-2 border-b-omi-accent bg-omi-surface text-omi-text-strong"
                : "",
            ].join(" ")}
          >
            {slot.label}
          </button>
        ))}
      </div>

      <div className="border-b border-omi-border-subtle px-5 py-4">
        <div className="text-xs font-semibold uppercase tracking-[0.18em] text-omi-text-muted">
          {labels.eyebrow}
        </div>
        <h3 className="mt-1 text-lg font-bold text-omi-text-strong">
          {activeSlot.title}
        </h3>
        <p className="mt-2 text-sm leading-6 text-omi-text-muted">
          {activeSlot.description}
        </p>
      </div>

      <div className="divide-y divide-omi-border-subtle border-b border-omi-border-subtle px-5 text-sm">
        <div className="flex items-center justify-between gap-4 py-3">
          <span className="text-omi-text-muted">{labels.status}</span>
          <span className={`font-bold ${statusToneClass(activeSlot.status)}`}>
            {statusLabel(activeSlot.status)}
          </span>
        </div>
        <div className="flex items-center justify-between gap-4 py-3">
          <span className="text-omi-text-muted">{labels.source}</span>
          <span className="font-bold text-omi-text">{activeSlot.source}</span>
        </div>
        <div className="flex items-center justify-between gap-4 py-3">
          <span className="text-omi-text-muted">{labels.latestDate}</span>
          <span className="font-bold text-omi-text">{activeSlot.latestDate}</span>
        </div>
        <div className="flex items-center justify-between gap-4 py-3">
          <span className="text-omi-text-muted">{labels.rows}</span>
          <span className="font-bold text-omi-text">{activeSlot.rowCount}</span>
        </div>
        <div className="py-3 text-xs leading-5 text-omi-text-muted">
          {labels.reserved}
        </div>
      </div>

      {footer}
    </section>
  );
}
