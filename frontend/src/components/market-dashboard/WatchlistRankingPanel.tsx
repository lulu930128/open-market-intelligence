"use client";

import {
  LoadingDots,
  StateSurface,
} from "@/components/LoadingPlaceholders";
import PriceUpdatePulse from "@/components/PriceUpdatePulse";
import { rankByLabel, useT } from "@/i18n";
import type { ReactNode } from "react";

export type RankingDisplayRow = {
  key: string;
  rank: number;
  symbol: string;
  name: string | null;
  meta: string | null;
  visual: ReactNode;
  close: string;
  closeValue: number | null | undefined;
  change: string;
  changePct: number | null | undefined;
  trend: string;
  volume: string;
  volumeValue: number | null | undefined;
  selected: boolean;
  loading?: boolean;
  href?: string;
  onSelect: () => void;
};

export type RankingPanelOption = {
  value: string;
  label: string;
};

type RankingPanelLoadState = "idle" | "loading" | "success" | "error";

function valueTone(value: number | null | undefined) {
  if (value === null || value === undefined) return "text-omi-text-muted";
  if (value > 0) return "text-omi-market-up";
  if (value < 0) return "text-omi-market-down";
  return "text-omi-text";
}

function trendClass(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "omi-ranking-trend-neutral";
  }
  if (value > 0) return "omi-ranking-trend-up";
  if (value < 0) return "omi-ranking-trend-down";
  return "omi-ranking-trend-neutral";
}

export function RankingLoadingRows({ rows = 5 }: { rows?: number }) {
  return (
    <div
      className="omi-loading-surface border-t border-omi-border-subtle"
      aria-hidden="true"
    >
      {Array.from({ length: rows }).map((_, index) => (
        <div
          key={index}
          className="omi-ranking-loading-row grid w-full grid-cols-[46px_minmax(120px,1fr)_104px_80px_82px_72px_90px] items-center border-t border-omi-border-subtle px-4 py-2 text-sm first:border-t-0"
        >
          <div className="omi-skeleton h-3 w-7" />
          <div className="min-w-0 space-y-2">
            <div className="omi-skeleton h-3 w-28" />
            <div className="omi-skeleton h-2.5 w-16" />
          </div>
          <div className="mx-auto h-6 w-16">
            <div className="omi-skeleton h-full w-full" />
          </div>
          <div className="ml-auto omi-skeleton h-3 w-14" />
          <div className="ml-auto omi-skeleton h-3 w-12" />
          <div className="ml-auto omi-skeleton h-6 w-12" />
          <div className="ml-auto omi-skeleton h-3 w-16" />
        </div>
      ))}
    </div>
  );
}

export function RankingCellSkeleton({
  className = "h-3 w-14",
}: {
  className?: string;
}) {
  return (
    <span
      aria-hidden="true"
      className={`inline-block align-middle omi-skeleton ${className}`}
    />
  );
}

export function WatchlistRankingPanel({
  groupName,
  lastUpdatedAt,
  statusLabel,
  rankBy,
  rankOptions,
  onRankByChange,
  onReload,
  reloadDisabled,
  secondaryAction,
  loadState,
  loadingLabel,
  rows,
  summary,
  volumeHeader,
  emptyMessage,
}: {
  groupName: string | null;
  lastUpdatedAt: string | null;
  statusLabel?: string;
  rankBy: string;
  rankOptions: RankingPanelOption[];
  onRankByChange: (value: string) => void;
  onReload: () => void;
  reloadDisabled: boolean;
  secondaryAction?: ReactNode;
  loadState: RankingPanelLoadState;
  loadingLabel?: string;
  rows: RankingDisplayRow[];
  summary: {
    stockCount: number;
    upCount: number;
    downCount: number;
  };
  volumeHeader: string;
  emptyMessage: string;
}) {
  const t = useT();
  const hasRows = rows.length > 0;
  const hasLoadingRows = rows.some((row) => row.loading);
  const isLoadingRows = (loadState === "loading" && !hasRows) || hasLoadingRows;
  const showLoadingStatus = loadState === "loading" || hasLoadingRows;

  return (
    <div className="space-y-4">
      <section className="border border-omi-border-subtle bg-omi-surface">
        <div className="flex flex-wrap items-start justify-between gap-4 px-5 py-4">
          <div>
            <div className="text-xs font-semibold uppercase tracking-[0.18em] text-omi-text-muted">
              {t("dashboard.ranking.selectedGroup")}
            </div>
            <h2 className="mt-1 text-2xl font-bold text-omi-text-strong">
              {groupName ?? t("dashboard.ranking.selectedGroupPlaceholder")}
            </h2>
            <div className="mt-1 text-sm text-omi-text-muted">
              {statusLabel ??
                (lastUpdatedAt
                  ? t("dashboard.ranking.updateTime", { time: lastUpdatedAt })
                  : t("dashboard.ranking.groupDataNotLoaded"))}
            </div>
          </div>

          <div className="flex items-center gap-2">
            <select
              value={rankBy}
              onChange={(event) => onRankByChange(event.target.value)}
              className="h-9 border border-omi-border bg-omi-surface px-3 text-sm font-semibold text-omi-text-muted outline-none focus:border-omi-accent"
            >
              {rankOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            {secondaryAction}
            <button
              type="button"
              data-testid="watchlist-ranking-reload"
              onClick={onReload}
              className="h-9 bg-omi-control px-4 text-sm font-semibold text-omi-text-inverse hover:bg-omi-control-border disabled:bg-omi-surface-strong"
              disabled={reloadDisabled}
            >
              {t("common.reload")}
            </button>
          </div>
        </div>

        <div className="grid grid-cols-2 border-t border-omi-border-subtle md:grid-cols-4">
          <div className="px-5 py-3">
            <div className="text-xs text-omi-text-muted">
              {t("dashboard.ranking.stockCount")}
            </div>
            <div className="mt-1 text-xl font-bold">{summary.stockCount}</div>
          </div>
          <div className="border-l border-omi-border-subtle px-5 py-3">
            <div className="text-xs text-omi-text-muted">
              {t("dashboard.ranking.upCount")}
            </div>
            <div className="mt-1 text-xl font-bold text-omi-market-up">
              {isLoadingRows ? (
                <span className="omi-skeleton block h-6 w-8" />
              ) : (
                summary.upCount
              )}
            </div>
          </div>
          <div className="border-l border-omi-border-subtle px-5 py-3">
            <div className="text-xs text-omi-text-muted">
              {t("dashboard.ranking.downCount")}
            </div>
            <div className="mt-1 text-xl font-bold text-omi-market-down">
              {isLoadingRows ? (
                <span className="omi-skeleton block h-6 w-8" />
              ) : (
                summary.downCount
              )}
            </div>
          </div>
          <div className="border-l border-omi-border-subtle px-5 py-3">
            <div className="text-xs text-omi-text-muted">
              {t("dashboard.ranking.sort")}
            </div>
            <div className="mt-1 text-xl font-bold">{rankByLabel(t, rankBy)}</div>
          </div>
        </div>
      </section>

      <section className="border border-omi-border-subtle bg-omi-surface">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-omi-border-subtle px-5 py-3">
          <h3 className="text-sm font-bold text-omi-text-strong">
            {t("dashboard.ranking.listTitle")}
          </h3>
          {showLoadingStatus ? (
            <span className="inline-flex items-center gap-2 text-xs text-omi-text-muted">
              {loadingLabel ?? t("common.loading")}
              <LoadingDots label={t("dashboard.ranking.loadingRanking")} />
            </span>
          ) : (
            <span className="text-xs text-omi-text-muted">
              {rankBy === "none"
                ? t("dashboard.ranking.rowSummaryNormal", { count: rows.length })
                : t("dashboard.ranking.rowSummaryRanked", {
                    count: rows.length,
                    rankLabel: rankByLabel(t, rankBy),
                  })}
            </span>
          )}
        </div>

        <div className="grid grid-cols-[46px_minmax(120px,1fr)_104px_80px_82px_72px_90px] bg-omi-surface-subtle px-4 py-2 text-xs font-bold uppercase tracking-wide text-omi-text-muted">
          <span>{t("dashboard.ranking.rank")}</span>
          <span>{t("dashboard.ranking.stock")}</span>
          <span className="text-center">{t("dashboard.ranking.trend")}</span>
          <span className="text-right">{t("dashboard.ranking.close")}</span>
          <span className="text-right">{t("dashboard.ranking.changePct")}</span>
          <span className="text-right">{t("dashboard.ranking.status")}</span>
          <span className="text-right">{volumeHeader}</span>
        </div>
        {rows.length > 0 ? (
          rows.map((row) => (
            <a
              key={row.key}
              href={row.href ?? "#"}
              data-ranking-symbol={row.symbol}
              onPointerUp={(event) => {
                if (event.button !== 0) return;
                row.onSelect();
              }}
              onMouseDown={(event) => {
                if (event.button !== 0) return;
                row.onSelect();
              }}
              onClick={(event) => {
                event.preventDefault();
                row.onSelect();
              }}
              className={[
                "omi-ranking-row grid w-full grid-cols-[46px_minmax(120px,1fr)_104px_80px_82px_72px_90px] items-center border-t border-omi-border-subtle px-4 py-2 text-left text-sm",
                row.selected
                  ? "omi-ranking-row-selected relative z-10 bg-omi-surface text-omi-text ring-1 ring-omi-market-up-border"
                  : "bg-omi-surface text-omi-text hover:bg-omi-surface-subtle",
              ].join(" ")}
            >
              <span
                className={
                  row.selected
                    ? "font-semibold text-omi-market-up"
                    : "text-omi-text-muted"
                }
              >
                #{row.rank}
              </span>
              <span className="min-w-0">
                <span className="block truncate font-semibold">
                  {row.symbol} {row.name ?? ""}
                </span>
                <span
                  className={
                    row.selected
                      ? "block truncate text-xs font-medium text-omi-text"
                      : "block truncate text-xs text-omi-text-muted"
                  }
                >
                  {row.loading ? (
                    <RankingCellSkeleton className="h-2.5 w-16" />
                  ) : (
                    row.meta ?? "-"
                  )}
                </span>
              </span>
              <span className="flex justify-center">
                {row.loading ? (
                  <RankingCellSkeleton className="h-5 w-16" />
                ) : (
                  row.visual
                )}
              </span>
              <span className="text-right font-semibold">
                {row.loading ? (
                  <RankingCellSkeleton />
                ) : (
                  <PriceUpdatePulse
                    value={row.closeValue}
                    direction={row.changePct}
                    resetKey={row.key}
                    className="justify-end tabular-nums"
                  >
                    {row.close}
                  </PriceUpdatePulse>
                )}
              </span>
              <span
                className={`text-right font-semibold ${valueTone(row.changePct)}`}
              >
                {row.loading ? (
                  <RankingCellSkeleton className="h-3 w-12" />
                ) : (
                  <PriceUpdatePulse
                    value={row.change}
                    direction={row.changePct}
                    resetKey={row.key}
                    className="justify-end tabular-nums"
                  >
                    {row.change}
                  </PriceUpdatePulse>
                )}
              </span>
              <span className="text-right">
                {row.loading ? (
                  <RankingCellSkeleton className="h-6 w-12" />
                ) : (
                  <span
                    className={[
                      "omi-ranking-trend-chip px-2 py-1 text-xs font-semibold",
                      row.selected
                        ? `omi-ranking-trend-chip-selected ${trendClass(row.changePct)}`
                        : trendClass(row.changePct),
                    ].join(" ")}
                  >
                    {row.trend}
                  </span>
                )}
              </span>
              <span className="text-right">
                {row.loading ? (
                  <RankingCellSkeleton className="h-3 w-16" />
                ) : (
                  <PriceUpdatePulse
                    value={row.volumeValue ?? row.volume}
                    direction={null}
                    resetKey={row.key}
                    className="justify-end tabular-nums"
                  >
                    {row.volume}
                  </PriceUpdatePulse>
                )}
              </span>
            </a>
          ))
        ) : isLoadingRows ? (
          <RankingLoadingRows />
        ) : (
          <div className="border-t border-omi-border-subtle p-3">
            <StateSurface title={emptyMessage} tone="empty" compact />
          </div>
        )}
      </section>
    </div>
  );
}
