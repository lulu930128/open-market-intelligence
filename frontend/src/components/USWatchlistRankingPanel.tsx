"use client";

import PriceUpdatePulse from "@/components/PriceUpdatePulse";
import { fetchJson } from "@/lib/api";
import { emitDataStatusEvent } from "@/lib/dataStatusEvents";
import {
  US_INTRADAY_REFRESH_MS,
  getUsMarketRefreshState,
} from "@/lib/usMarketTime";
import {
  rankByLabel,
  rowStatusLabel,
  trendDirectionLabel,
  usAssetTypeLabel,
  useT,
  type TranslationFunction,
} from "@/i18n";
import type {
  USWatchlistRankingItemRead,
  USWatchlistRankingRead,
} from "@/types/market";
import { useCallback, useEffect, useMemo, useState } from "react";

type LoadState = "idle" | "loading" | "success" | "error";
type USRankBy = "none" | "change_pct" | "volume" | "close";
const WATCHLIST_INTRADAY_LIMIT = 30;

type Props = {
  selectedGroupId: number | null;
  selectedGroupName: string | null;
  selectedSymbol: string | null;
  reloadKey: number;
  onSelectSymbol: (symbol: string, securityName: string | null) => void;
};

function formatNumber(value: number | null | undefined, maximumFractionDigits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";

  return value.toLocaleString("en-US", {
    maximumFractionDigits,
  });
}

function formatVolume(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";

  return value.toLocaleString("en-US");
}

function formatPct(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

function formatDate(value: string | null | undefined) {
  if (!value) return "-";
  return value.slice(0, 10);
}

function valueTone(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "text-omi-text-muted";
  }
  if (value > 0) return "text-omi-market-up";
  if (value < 0) return "text-omi-market-down";
  return "text-omi-text";
}

function trendLabel(t: TranslationFunction, value: number | null | undefined) {
  return trendDirectionLabel(t, value);
}

function trendClass(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "bg-omi-surface-muted text-omi-text-muted";
  }
  if (value > 0) return "bg-omi-market-up-soft text-omi-market-up";
  if (value < 0) return "bg-omi-market-down-soft text-omi-market-down";
  return "bg-omi-surface-muted text-omi-text-muted";
}

function statusLabel(t: TranslationFunction, status: string) {
  if (status === "intraday") return t("statusLabels.intraday");
  if (status === "extended_hours") return t("usStockDetail.extendedHours.scopes.extended");
  if (status === "ready") return t("statusLabels.ready");
  return rowStatusLabel(t, status);
}

function sessionLabel(t: TranslationFunction, session: string | null | undefined) {
  if (!session) return t("statusLabels.intraday");
  return t(`usStockDetail.extendedHours.phases.${session}`);
}

function rankLabel(t: TranslationFunction, rankBy: string) {
  return rankByLabel(t, rankBy);
}

export default function USWatchlistRankingPanel({
  selectedGroupId,
  selectedGroupName,
  selectedSymbol,
  reloadKey,
  onSelectSymbol,
}: Props) {
  const t = useT();
  const [rankBy, setRankBy] = useState<USRankBy>("none");
  const [ranking, setRanking] = useState<USWatchlistRankingRead | null>(null);
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const [lastUpdatedAt, setLastUpdatedAt] = useState<string | null>(null);

  const sortOrder = rankBy === "none" ? "asc" : "desc";
  const rankingDataStatusContextKey = `us:watchlist:${selectedGroupId ?? "all"}:ranking`;
  const rankingDataStatusContextLabel = selectedGroupName ?? t("watchlist.usHeader");
  const rankingDataStatusSource = t("dashboard.ranking.listTitle");
  const rows = useMemo(() => ranking?.results ?? [], [ranking]);
  const summary = useMemo(() => {
    const upCount = rows.filter((row) => {
      return row.change_pct !== null && row.change_pct !== undefined && row.change_pct > 0;
    }).length;
    const downCount = rows.filter((row) => {
      return row.change_pct !== null && row.change_pct !== undefined && row.change_pct < 0;
    }).length;

    return {
      stockCount: ranking?.requested_symbol_count ?? rows.length,
      upCount,
      downCount,
      noDataCount: ranking?.no_data_count ?? 0,
    };
  }, [ranking?.no_data_count, ranking?.requested_symbol_count, rows]);

  const publishRankingDataStatus = useCallback(
    (title: string, message: string) => {
      emitDataStatusEvent({
        market: "us",
        level: "error",
        title,
        message,
        source: rankingDataStatusSource,
        contextKey: rankingDataStatusContextKey,
        contextLabel: rankingDataStatusContextLabel,
        dedupeKey: `${rankingDataStatusContextKey}:${rankingDataStatusSource}:${title}:error`,
      });
    },
    [
      rankingDataStatusContextKey,
      rankingDataStatusContextLabel,
      rankingDataStatusSource,
    ]
  );

  const loadRanking = useCallback(async (options?: { silent?: boolean }) => {
    if (!options?.silent) {
      setLoadState("loading");
    }
    const marketState = getUsMarketRefreshState();

    const params: Record<string, string | number | boolean> = {
      include_children: true,
      enabled_only: true,
      rank_by: rankBy,
      sort_order: sortOrder,
      use_intraday: marketState.isLiveWindow,
      intraday_limit: WATCHLIST_INTRADAY_LIMIT,
      intraday_session_scope: marketState.intradaySessionScope,
    };

    if (selectedGroupId !== null) {
      params.group_id = selectedGroupId;
    }

    try {
      const data = await fetchJson<USWatchlistRankingRead>(
        "/api/us-market/watchlists/ranking",
        params
      );
      setRanking(data);
      setLastUpdatedAt(new Date().toLocaleString("zh-TW", { hour12: false }));
      setLoadState("success");
    } catch (error) {
      setRanking(null);
      setLoadState("error");
      publishRankingDataStatus(
        t("dashboard.ranking.usReadError"),
        error instanceof Error ? error.message : t("dashboard.ranking.usReadError")
      );
    }
  }, [publishRankingDataStatus, rankBy, selectedGroupId, sortOrder, t]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadRanking();
    }, 0);

    return () => window.clearTimeout(timer);
  }, [loadRanking, reloadKey]);

  useEffect(() => {
    let disposed = false;
    let refreshTimer: number | undefined;

    function scheduleRefresh() {
      if (disposed) return;

      const marketState = getUsMarketRefreshState();

      if (marketState.isLiveWindow) {
        refreshTimer = window.setTimeout(() => {
          void loadRanking({ silent: true }).finally(scheduleRefresh);
        }, US_INTRADAY_REFRESH_MS);
        return;
      }

      refreshTimer = window.setTimeout(
        scheduleRefresh,
        Math.min(marketState.msUntilNextPollingStart, 60_000)
      );
    }

    scheduleRefresh();

    return () => {
      disposed = true;
      if (refreshTimer !== undefined) {
        window.clearTimeout(refreshTimer);
      }
    };
  }, [loadRanking]);

  function renderRow(row: USWatchlistRankingItemRead) {
    const selected = row.symbol === selectedSymbol;

    return (
      <button
        key={`${row.group_id}-${row.symbol}`}
        type="button"
        onClick={() => onSelectSymbol(row.symbol, row.security_name)}
        className={[
          "grid w-full grid-cols-[46px_minmax(160px,1fr)_94px_86px_86px_104px_78px] items-center border-t border-omi-border-subtle px-4 py-2 text-left text-sm",
          selected ? "bg-omi-control text-omi-text-inverse" : "bg-omi-surface text-omi-text hover:bg-omi-surface-subtle",
        ].join(" ")}
      >
        <span className={selected ? "text-omi-text-inverse-muted" : "text-omi-text-muted"}>#{row.rank}</span>
        <span className="min-w-0">
          <span className="block truncate font-semibold">
            {row.symbol} {row.security_name ?? ""}
          </span>
          <span className={selected ? "block truncate text-xs text-omi-text-inverse-muted" : "block truncate text-xs text-omi-text-muted"}>
            {[
              row.time ? `${formatDate(row.time)} ${sessionLabel(t, row.session)}` : null,
              row.exchange,
              row.asset_type ? usAssetTypeLabel(t, row.asset_type) : null,
            ]
              .filter(Boolean)
              .join(" · ") || statusLabel(t, row.status)}
          </span>
        </span>
        <span className={selected ? "text-omi-text-inverse-muted" : "text-omi-text-muted"}>
          {row.time ? sessionLabel(t, row.session) : formatDate(row.trade_date)}
        </span>
        <span className="text-right font-semibold">
          <PriceUpdatePulse
            value={row.close}
            direction={row.change_pct}
            resetKey={`${selectedGroupId ?? "all"}:${row.symbol}`}
            className="justify-end tabular-nums"
          >
            {formatNumber(row.close)}
          </PriceUpdatePulse>
        </span>
        <span className={`text-right font-semibold ${selected ? "" : valueTone(row.change_pct)}`}>
          <PriceUpdatePulse
            value={row.change_pct}
            direction={row.change_pct}
            resetKey={`${selectedGroupId ?? "all"}:${row.symbol}`}
            className="justify-end tabular-nums"
          >
            {formatPct(row.change_pct)}
          </PriceUpdatePulse>
        </span>
        <span className="text-right">
          <PriceUpdatePulse
            value={row.volume}
            direction={null}
            resetKey={`${selectedGroupId ?? "all"}:${row.symbol}`}
            className="justify-end tabular-nums"
          >
            {formatVolume(row.volume)}
          </PriceUpdatePulse>
        </span>
        <span className="text-right">
          <span
            className={[
              "px-2 py-1 text-xs font-semibold",
              selected ? "bg-omi-surface text-omi-text" : trendClass(row.change_pct),
            ].join(" ")}
          >
            {trendLabel(t, row.change_pct)}
          </span>
        </span>
      </button>
    );
  }

  return (
    <div className="space-y-4">
      <section className="border border-omi-border-subtle bg-omi-surface">
        <div className="flex flex-wrap items-start justify-between gap-4 px-5 py-4">
          <div>
            <div className="text-xs font-semibold uppercase tracking-[0.18em] text-omi-text-muted">
              {t("dashboard.ranking.selectedGroup")}
            </div>
            <h2 className="mt-1 text-2xl font-bold text-omi-text-strong">
              {selectedGroupName ?? t("watchlist.usHeader")}
            </h2>
            <div className="mt-1 text-sm text-omi-text-muted">
              {lastUpdatedAt
                ? t("dashboard.ranking.updateTime", { time: lastUpdatedAt })
                : t("dashboard.ranking.groupDataNotLoaded")}
            </div>
          </div>

          <div className="flex items-center gap-2">
            <select
              value={rankBy}
              onChange={(event) => setRankBy(event.target.value as USRankBy)}
              className="h-9 border border-omi-border bg-omi-surface px-3 text-sm font-semibold text-omi-text-muted outline-none focus:border-omi-accent"
            >
              <option value="none">{t("rank.none")}</option>
              <option value="change_pct">{t("rank.changePct")}</option>
              <option value="volume">{t("rank.volume")}</option>
              <option value="close">{t("rank.close")}</option>
            </select>
            <button
              type="button"
              onClick={() => void loadRanking()}
              className="h-9 bg-omi-control px-4 text-sm font-semibold text-omi-text-inverse hover:bg-omi-control-border disabled:bg-omi-surface-strong"
              disabled={loadState === "loading"}
            >
              {t("common.reload")}
            </button>
          </div>
        </div>

        <div className="grid grid-cols-2 border-t border-omi-border-subtle md:grid-cols-4">
          <div className="px-5 py-3">
            <div className="text-xs text-omi-text-muted">{t("dashboard.ranking.stockCount")}</div>
            <div className="mt-1 text-xl font-bold">{summary.stockCount}</div>
          </div>
          <div className="border-l border-omi-border-subtle px-5 py-3">
            <div className="text-xs text-omi-text-muted">{t("dashboard.ranking.upCount")}</div>
            <div className="mt-1 text-xl font-bold text-omi-market-up">{summary.upCount}</div>
          </div>
          <div className="border-l border-omi-border-subtle px-5 py-3">
            <div className="text-xs text-omi-text-muted">{t("dashboard.ranking.downCount")}</div>
            <div className="mt-1 text-xl font-bold text-omi-market-down">{summary.downCount}</div>
          </div>
          <div className="border-l border-omi-border-subtle px-5 py-3">
            <div className="text-xs text-omi-text-muted">{t("dashboard.ranking.sort")}</div>
            <div className="mt-1 text-xl font-bold">{rankLabel(t, ranking?.rank_by ?? rankBy)}</div>
          </div>
        </div>
      </section>

      <section className="border border-omi-border-subtle bg-omi-surface">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-omi-border-subtle px-5 py-3">
          <h3 className="text-sm font-bold text-omi-text-strong">{t("dashboard.ranking.listTitle")}</h3>
          <span className="text-xs text-omi-text-muted">
            {loadState === "loading"
              ? t("common.loading")
              : t("dashboard.ranking.usSummaryWithNoData", {
                  count: rows.length,
                  noDataCount: summary.noDataCount,
                })}
          </span>
        </div>

        <div className="grid grid-cols-[46px_minmax(160px,1fr)_94px_86px_86px_104px_78px] bg-omi-surface-subtle px-4 py-2 text-xs font-bold uppercase tracking-wide text-omi-text-muted">
          <span>{t("dashboard.ranking.rank")}</span>
          <span>{t("dashboard.ranking.stock")}</span>
          <span>{t("dashboard.ranking.date")}</span>
          <span className="text-right">{t("dashboard.ranking.close")}</span>
          <span className="text-right">{t("dashboard.ranking.changePct")}</span>
          <span className="text-right">{t("dashboard.ranking.volume")}</span>
          <span className="text-right">{t("dashboard.ranking.status")}</span>
        </div>
        {rows.length > 0 ? (
          rows.map(renderRow)
        ) : (
          <div className="border-t border-omi-border-subtle px-5 py-10 text-center text-sm text-omi-text-muted">
            {loadState === "loading" ? t("common.loading") : t("dashboard.ranking.usEmpty")}
          </div>
        )}
      </section>
    </div>
  );
}
