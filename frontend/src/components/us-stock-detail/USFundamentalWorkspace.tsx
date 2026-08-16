"use client";

import { useT } from "@/i18n";
import type { KeyboardEvent, ReactNode } from "react";

export type USFundamentalTab =
  | "overview"
  | "financials"
  | "institutions"
  | "insider"
  | "short"
  | "filings";

const tabKeys: USFundamentalTab[] = [
  "overview",
  "financials",
  "institutions",
  "insider",
  "short",
  "filings",
];

function TabIcon({ type }: { type: USFundamentalTab }) {
  if (type === "overview") {
    return (
      <svg viewBox="0 0 20 20" className="h-5 w-5" aria-hidden="true">
        <path
          d="M10 2c3.3 0 6 1 6 2.3S13.3 6.6 10 6.6 4 5.6 4 4.3 6.7 2 10 2Zm-6 4.2c1.2 1 3.4 1.5 6 1.5s4.8-.6 6-1.5v2.1c0 1.3-2.7 2.3-6 2.3s-6-1-6-2.3V6.2Zm0 4c1.2 1 3.4 1.5 6 1.5s4.8-.6 6-1.5v2.1c0 1.3-2.7 2.3-6 2.3s-6-1-6-2.3v-2.1Zm0 4c1.2 1 3.4 1.5 6 1.5s4.8-.6 6-1.5v1.5c0 1.3-2.7 2.3-6 2.3s-6-1-6-2.3v-1.5Z"
          fill="currentColor"
        />
      </svg>
    );
  }

  if (type === "financials") {
    return (
      <svg viewBox="0 0 20 20" className="h-5 w-5" aria-hidden="true">
        <path
          d="M3 3h14v14H3V3Zm2 9v3h2v-3H5Zm4-5v8h2V7H9Zm4 3v5h2v-5h-2ZM5 5v2h2V5H5Z"
          fill="currentColor"
        />
      </svg>
    );
  }

  if (type === "institutions") {
    return (
      <svg viewBox="0 0 20 20" className="h-5 w-5" aria-hidden="true">
        <path
          d="M3 8h14v2H3V8Zm1 3h2v5H4v-5Zm5 0h2v5H9v-5Zm5 0h2v5h-2v-5ZM2 17h16v1H2v-1ZM10 2l7 4H3l7-4Z"
          fill="currentColor"
        />
      </svg>
    );
  }

  if (type === "insider") {
    return (
      <svg viewBox="0 0 20 20" className="h-5 w-5" aria-hidden="true">
        <path
          d="M10 2a4 4 0 0 1 2.8 6.8A7 7 0 0 1 17 15.2V18H3v-2.8a7 7 0 0 1 4.2-6.4A4 4 0 0 1 10 2Zm0 2a2 2 0 1 0 0 4 2 2 0 0 0 0-4Zm0 6c-2.8 0-5 2.2-5 5v1h10v-1c0-2.8-2.2-5-5-5Z"
          fill="currentColor"
        />
      </svg>
    );
  }

  if (type === "short") {
    return (
      <svg viewBox="0 0 20 20" className="h-5 w-5" aria-hidden="true">
        <path d="M10 17 3 10l1.4-1.4L9 13.2V3h2v10.2l4.6-4.6L17 10l-7 7Z" fill="currentColor" />
      </svg>
    );
  }

  return (
    <svg viewBox="0 0 20 20" className="h-5 w-5" aria-hidden="true">
      <path
        d="M5 2h7l3 3v13H5V2Zm2 2v12h6V6h-3V4H7Zm1 5h4v1.5H8V9Zm0 3h4v1.5H8V12Z"
        fill="currentColor"
      />
    </svg>
  );
}

export default function USFundamentalWorkspace({
  activeTab,
  action,
  children,
  onTabChange,
}: {
  activeTab: USFundamentalTab;
  action?: ReactNode;
  children: ReactNode;
  onTabChange: (tab: USFundamentalTab) => void;
}) {
  const t = useT();

  function selectAdjacentTab(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    let nextIndex: number | null = null;
    if (event.key === "ArrowRight") nextIndex = (index + 1) % tabKeys.length;
    if (event.key === "ArrowLeft") nextIndex = (index - 1 + tabKeys.length) % tabKeys.length;
    if (event.key === "Home") nextIndex = 0;
    if (event.key === "End") nextIndex = tabKeys.length - 1;
    if (nextIndex === null) return;

    event.preventDefault();
    const nextTab = tabKeys[nextIndex];
    onTabChange(nextTab);
    requestAnimationFrame(() => document.getElementById(`us-fundamental-tab-${nextTab}`)?.focus());
  }

  return (
    <section className="border-t border-omi-border-subtle" aria-labelledby="us-fundamental-title">
      <div aria-hidden="true" className="h-2 border-b border-omi-border-subtle bg-omi-surface-subtle" />
      <div
        role="tablist"
        aria-label={t("usStockDetail.sections.fundamentalWorkspace")}
        className="grid grid-cols-3 border-b border-omi-border-subtle"
      >
        {tabKeys.map((tab, index) => {
          const active = activeTab === tab;
          return (
            <button
              key={tab}
              id={`us-fundamental-tab-${tab}`}
              type="button"
              role="tab"
              aria-controls="us-fundamental-panel"
              aria-selected={active}
              tabIndex={active ? 0 : -1}
              data-data-tab={tab}
              onClick={() => onTabChange(tab)}
              onKeyDown={(event) => selectAdjacentTab(event, index)}
              className={[
                "omi-data-tab flex h-11 min-w-0 items-center justify-center gap-2 px-2 text-sm font-semibold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-omi-accent",
                index % 3 !== 2 ? "border-r border-omi-border-subtle" : "",
                index < 3 ? "border-b border-omi-border-subtle" : "",
                active
                  ? "omi-data-tab-active bg-omi-surface text-omi-text-strong"
                  : "bg-omi-surface-subtle text-omi-text-muted hover:bg-omi-surface hover:text-omi-text",
              ].join(" ")}
            >
              <TabIcon type={tab} />
              <span className="truncate">{t(`usStockDetail.tabs.${tab}.label`)}</span>
            </button>
          );
        })}
      </div>

      <div
        id="us-fundamental-panel"
        role="tabpanel"
        aria-labelledby={`us-fundamental-tab-${activeTab}`}
        className="px-4 py-4 sm:px-5"
      >
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between sm:gap-4">
          <div className="min-w-0">
            <div className="text-xs font-semibold uppercase tracking-[0.18em] text-omi-text-muted">
              {t("usStockDetail.sections.data")}
            </div>
            <h3 id="us-fundamental-title" className="mt-1 text-lg font-bold text-omi-text-strong">
              {t(`usStockDetail.tabs.${activeTab}.title`)}
            </h3>
            <p className="mt-1 text-xs leading-5 text-omi-text-muted">
              {t(`usStockDetail.tabs.${activeTab}.description`)}
            </p>
          </div>
          {action ? <div className="shrink-0 self-start">{action}</div> : null}
        </div>

        <div className="mt-4">{children}</div>
      </div>
    </section>
  );
}
