"use client";

import { StateSurface } from "@/components/LoadingPlaceholders";
import {
  formatDashboardTime,
  formatPct,
  formatPrice,
  formatRowTime,
  formatSignedNumber,
  formatTradeValueYi,
  formatWholeNumber,
  valueTone,
  type DashboardLoadState,
} from "@/components/market-dashboard/dashboardFormatters";
import {
  useJpMarketTapeState,
  useKrMarketTapeState,
  useUsMarketTapeState,
  type JPMarketTapeSnapshot,
  type KRMarketTapeSnapshot,
  type USMarketTapeSnapshot,
} from "@/components/market-dashboard/tape/useRegionalMarketTapeState";
import { useT, type TranslationFunction } from "@/i18n";
import type {
  JPStockMasterRead,
  JPMarketSectorBreadthRead,
  KRStockMasterRead,
  MarketBreadth,
  MarketIndexSnapshot,
  MarketIndexSummary,
  USCompanyProfileRead,
} from "@/types/market";

function marketRegimeLabel(t: TranslationFunction, index: MarketIndexSnapshot) {
  if (index.close === null || index.close === undefined) {
    return t("dashboard.marketIndex.insufficient");
  }
  if (index.price_vs_ma20 !== null && index.price_vs_ma20 !== undefined) {
    if (index.price_vs_ma20 > 1) return t("dashboard.marketIndex.aboveMa20");
    if (index.price_vs_ma20 < -1) return t("dashboard.marketIndex.belowMa20");
  }

  if (index.change_pct !== null && index.change_pct !== undefined) {
    if (index.change_pct > 0) return t("dashboard.marketIndex.bullishShort");
    if (index.change_pct < 0) return t("dashboard.marketIndex.weakShort");
  }

  return t("dashboard.marketIndex.neutral");
}

function regionalMarketRegimeLabel(
  t: TranslationFunction,
  snapshot:
    | {
        close: number | null;
        priceVsMa20: number | null;
        changePct: number | null;
      }
    | null
    | undefined
) {
  if (!snapshot || snapshot.close === null) {
    return t("dashboard.marketIndex.insufficient");
  }
  if (snapshot.priceVsMa20 !== null) {
    if (snapshot.priceVsMa20 > 1) return t("dashboard.marketIndex.aboveMa20");
    if (snapshot.priceVsMa20 < -1) return t("dashboard.marketIndex.belowMa20");
  }

  if (snapshot.changePct !== null) {
    if (snapshot.changePct > 0) return t("dashboard.marketIndex.bullishShort");
    if (snapshot.changePct < 0) return t("dashboard.marketIndex.weakShort");
  }

  return t("dashboard.marketIndex.neutral");
}

function taiwanBreadthLabel(t: TranslationFunction, index: MarketIndexSnapshot) {
  const breadth = index.breadth;
  if (!breadth) {
    return t(
      index.index_id === "TPEX"
        ? "dashboard.marketIndex.tpexFullBreadth"
        : "dashboard.marketIndex.twseFullBreadth"
    );
  }
  if (breadth.scope === "registered_universe") {
    return t("dashboard.marketIndex.registeredBreadth");
  }
  if (breadth.scope === "full_market") {
    return t(
      breadth.market === "TPEX" || index.index_id === "TPEX"
        ? "dashboard.marketIndex.tpexFullBreadth"
        : "dashboard.marketIndex.twseFullBreadth"
    );
  }
  if (breadth.scope === "omi_sample") {
    return t("dashboard.marketIndex.sampleBreadth");
  }
  return t("dashboard.marketIndex.localDatasetBreadth");
}

function taiwanBreadthDisplayCounts(breadth: MarketBreadth | null | undefined) {
  if (!breadth) {
    return { classified: 0, unknown: 0 };
  }
  const classified =
    breadth.coverage_count ??
    breadth.classified_count ??
    breadth.advance_count + breadth.decline_count + breadth.unchanged_count;
  const unknown =
    breadth.unknown_count ?? Math.max(breadth.total_count - classified, 0);

  return { classified, unknown };
}

export function TaiwanMarketTape({
  summary,
  loadState,
}: {
  summary: MarketIndexSummary | null;
  loadState: DashboardLoadState;
}) {
  const t = useT();
  const indices = summary?.indices ?? [];
  const asOf = summary?.as_of ? formatDashboardTime(new Date(summary.as_of)) : null;
  const cacheLabel = summary?.refresh_recommended
    ? t("dashboard.marketIndex.cacheStale")
    : summary?.cache_status && summary.cache_status !== "live"
      ? t("dashboard.marketIndex.cacheReady")
      : null;

  return (
    <section
      className="mb-3 border border-omi-border-subtle bg-omi-surface"
      data-testid="market-tape-tw"
      data-load-state={loadState}
    >
      <div className="grid gap-px bg-omi-surface-strong lg:grid-cols-2">
        {indices.length > 0 ? (
          indices.map((index) => {
            const breadth = index.breadth;
            const breadthStatus = index.breadth_status?.status ?? "ready";
            const breadthCounts = taiwanBreadthDisplayCounts(breadth);
            const advanceRatio =
              breadth &&
              breadthCounts.classified > 0 &&
              breadthStatus !== "pending"
                ? (breadth.advance_count / breadthCounts.classified) * 100
                : null;
            const breadthAsOf = breadth?.snapshot_as_of ?? breadth?.as_of;
            const auction = breadth?.auction_breadth;

            return (
              <div key={index.index_id} className="bg-omi-surface px-4 py-3">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <div className="text-xs font-semibold uppercase tracking-[0.16em] text-omi-text-muted">
                      {t("app.market")}
                    </div>
                    <div className="mt-1 flex flex-wrap items-baseline gap-x-3 gap-y-1">
                      <span className="text-lg font-bold text-omi-text-strong">{index.label}</span>
                      <span className="text-2xl font-black text-omi-text-strong">
                        {formatPrice(index.close)}
                      </span>
                      <span className={`text-sm font-bold ${valueTone(index.change_pct)}`}>
                        {formatSignedNumber(index.change)} / {formatPct(index.change_pct)}
                      </span>
                    </div>
                  </div>
                  <div className="text-right text-xs">
                    <div className="font-semibold text-omi-text">
                      {marketRegimeLabel(t, index)}
                    </div>
                    <div className={valueTone(index.price_vs_ma20)}>
                      {formatPct(index.price_vs_ma20)} vs MA20
                    </div>
                  </div>
                </div>

                <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
                  <div className="border border-omi-border-subtle bg-omi-surface-subtle px-2 py-2">
                    <div className="text-omi-text-muted">
                      {t("dashboard.marketIndex.tradeValueYi")}
                    </div>
                    <div className="mt-1 font-semibold text-omi-text">
                      {formatTradeValueYi(index.trade_value)}
                    </div>
                  </div>
                  <div className="border border-omi-border-subtle bg-omi-surface-subtle px-2 py-2">
                    <div className="text-omi-text-muted">
                      {t("dashboard.marketIndex.advanceDecline")}
                    </div>
                    <div className="mt-1 font-semibold">
                      <span className="text-omi-market-up">{breadth?.advance_count ?? "-"}</span>
                      <span className="px-1 text-omi-text-subtle">/</span>
                      <span className="text-omi-market-down">{breadth?.decline_count ?? "-"}</span>
                    </div>
                  </div>
                  <div className="border border-omi-border-subtle bg-omi-surface-subtle px-2 py-2">
                    <div className="text-omi-text-muted">
                      {taiwanBreadthLabel(t, index)}
                    </div>
                    <div
                      className={`mt-1 font-semibold ${valueTone((advanceRatio ?? 50) - 50)}`}
                      data-testid={`market-tape-${index.index_id.toLowerCase()}-breadth-ratio`}
                    >
                      {breadthStatus === "failed"
                        ? t("dashboard.marketIndex.breadthFailed")
                        : breadthStatus === "pending"
                          ? t("dashboard.marketIndex.breadthPending")
                        : advanceRatio === null
                          ? "-"
                        : t("dashboard.marketIndex.advancePct", {
                            value: advanceRatio.toFixed(0),
                          })}
                      {breadthStatus === "partial"
                        ? ` · ${t("dashboard.marketIndex.breadthPartial")}`
                        : ""}
                    </div>
                  </div>
                </div>
                {breadth ? (
                  <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-omi-text-muted">
                    <span
                      data-testid={`market-tape-${index.index_id.toLowerCase()}-breadth-coverage`}
                    >
                      {t("dashboard.marketIndex.breadthCoverage", {
                        coverage: breadthCounts.classified,
                        total: breadth.total_count,
                        unknown: breadthCounts.unknown,
                      })}
                    </span>
                    {breadthAsOf ? (
                      <span>
                        {t("dashboard.marketIndex.breadthUpdated", {
                          asOf: formatDashboardTime(new Date(breadthAsOf)),
                        })}
                      </span>
                    ) : null}
                    {auction?.status === "provisional" ? (
                      <span>
                        {t("dashboard.marketIndex.auctionProvisional", {
                          advance: auction.advance_count,
                          decline: auction.decline_count,
                          unchanged: auction.unchanged_count,
                        })}
                      </span>
                    ) : null}
                  </div>
                ) : null}
              </div>
            );
          })
        ) : (
          <StateSurface
            title={
              loadState === "loading"
                ? t("dashboard.marketIndex.loading")
                : t("dashboard.marketIndex.empty")
            }
            tone={loadState === "loading" ? "loading" : "empty"}
            busy={loadState === "loading"}
            compact
            className="m-3 lg:col-span-2"
          />
        )}
      </div>
      <div className="border-t border-omi-border-subtle px-4 py-2 text-xs text-omi-text-muted">
        {asOf
          ? t("dashboard.marketIndex.updated", { asOf })
          : t("dashboard.marketIndex.waiting")}
        {cacheLabel ? ` · ${cacheLabel}` : ""}
      </div>
    </section>
  );
}

function USMarketTapeCard({
  title,
  snapshot,
  loadState,
}: {
  title: string;
  snapshot: USMarketTapeSnapshot | null;
  loadState: DashboardLoadState;
}) {
  const t = useT();

  return (
    <div className="bg-omi-surface px-4 py-3">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="text-xs font-semibold uppercase tracking-[0.16em] text-omi-text-muted">
            {title}
          </div>
          <div className="mt-1 flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className="text-lg font-bold text-omi-text-strong">
              {snapshot ? snapshot.name : loadState === "loading" ? t("common.loading") : "-"}
            </span>
            <span className="text-2xl font-black text-omi-text-strong">
              {formatPrice(snapshot?.close)}
            </span>
            <span className={`text-sm font-bold ${valueTone(snapshot?.changePct)}`}>
              {formatSignedNumber(snapshot?.change)} / {formatPct(snapshot?.changePct)}
            </span>
          </div>
          <div className="mt-1 text-xs text-omi-text-muted">
            {snapshot
              ? `${snapshot.displaySymbol} · ${snapshot.exchange} · ${
                  snapshot.source === "daily"
                    ? t("dashboard.marketIndex.daily")
                    : t("statusLabels.intraday")
                }`
              : t("dashboard.marketIndex.waitingData")}
          </div>
        </div>
        <div className="text-right text-xs">
          <div className="font-semibold text-omi-text">
            {regionalMarketRegimeLabel(t, snapshot)}
          </div>
          <div className={valueTone(snapshot?.priceVsMa20)}>
            {formatPct(snapshot?.priceVsMa20)} vs MA20
          </div>
        </div>
      </div>

      <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
        <div className="border border-omi-border-subtle bg-omi-surface-subtle px-2 py-2">
          <div className="text-omi-text-muted">{t("dashboard.marketIndex.volume")}</div>
          <div className="mt-1 font-semibold text-omi-text">
            {formatWholeNumber(snapshot?.volume)}
          </div>
        </div>
        <div className="border border-omi-border-subtle bg-omi-surface-subtle px-2 py-2">
          <div className="text-omi-text-muted">{t("dashboard.marketIndex.candleCount")}</div>
          <div className="mt-1 font-semibold text-omi-text">{snapshot?.pointCount ?? "-"}</div>
        </div>
        <div className="border border-omi-border-subtle bg-omi-surface-subtle px-2 py-2">
          <div className="text-omi-text-muted">{t("common.update")}</div>
          <div className="mt-1 truncate font-semibold text-omi-text">
            {snapshot?.asOf ? formatRowTime(snapshot.asOf) ?? snapshot.asOf.slice(0, 10) : "-"}
          </div>
        </div>
      </div>
    </div>
  );
}

export function USMarketTape({
  selectedSymbol,
  selectedSecurityName,
  selectedGroupName,
  companyProfile,
  onError,
}: {
  selectedSymbol: string | null;
  selectedSecurityName: string | null;
  selectedGroupName: string | null;
  companyProfile: USCompanyProfileRead | null;
  onError: (error: unknown) => void;
}) {
  const t = useT();
  const state = useUsMarketTapeState({
    selectedSymbol,
    selectedSecurityName,
    selectedGroupName,
    companyProfile,
    onError,
  });

  return (
    <section
      className="mb-3 border border-omi-border-subtle bg-omi-surface"
      data-testid="market-tape-us"
      data-load-state={state.loadState}
    >
      <div className="grid gap-px bg-omi-surface-strong lg:grid-cols-2">
        <USMarketTapeCard
          title={t("dashboard.marketIndex.market")}
          snapshot={state.primarySnapshot}
          loadState={state.loadState}
        />
        <USMarketTapeCard
          title={t("dashboard.marketIndex.context")}
          snapshot={state.contextSnapshot}
          loadState={state.loadState}
        />
      </div>
      <div className="border-t border-omi-border-subtle px-4 py-2 text-xs text-omi-text-muted">
        {state.asOf
          ? t("dashboard.marketIndex.usUpdated", {
              asOf: formatRowTime(state.asOf) ?? state.asOf.slice(0, 10),
            })
          : t("dashboard.marketIndex.usWaiting")}
      </div>
    </section>
  );
}

function JPMarketTapeCard({
  title,
  snapshot,
  loadState,
}: {
  title: string;
  snapshot: JPMarketTapeSnapshot | null;
  loadState: DashboardLoadState;
}) {
  const t = useT();

  return (
    <div className="bg-omi-surface px-4 py-3">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="text-xs font-semibold uppercase tracking-[0.16em] text-omi-text-muted">
            {title}
          </div>
          <div className="mt-1 flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className="text-lg font-bold text-omi-text-strong">
              {snapshot ? snapshot.name : loadState === "loading" ? t("common.loading") : "-"}
            </span>
            <span className="text-2xl font-black text-omi-text-strong">
              {formatPrice(snapshot?.close)}
            </span>
            <span className={`text-sm font-bold ${valueTone(snapshot?.changePct)}`}>
              {formatSignedNumber(snapshot?.change)} / {formatPct(snapshot?.changePct)}
            </span>
          </div>
          <div className="mt-1 text-xs text-omi-text-muted">
            {snapshot
              ? `${snapshot.displaySymbol} · ${snapshot.exchange} · ${
                  snapshot.source === "intraday"
                    ? t("statusLabels.intraday")
                    : t("dashboard.marketIndex.daily")
                }`
              : t("dashboard.marketIndex.waitingData")}
          </div>
        </div>
        <div className="text-right text-xs">
          <div className="font-semibold text-omi-text">
            {regionalMarketRegimeLabel(t, snapshot)}
          </div>
          <div className={valueTone(snapshot?.priceVsMa20)}>
            {formatPct(snapshot?.priceVsMa20)} vs MA20
          </div>
        </div>
      </div>

      <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
        <div className="border border-omi-border-subtle bg-omi-surface-subtle px-2 py-2">
          <div className="text-omi-text-muted">{t("dashboard.marketIndex.volume")}</div>
          <div className="mt-1 font-semibold text-omi-text">
            {formatWholeNumber(snapshot?.volume)}
          </div>
        </div>
        <div className="border border-omi-border-subtle bg-omi-surface-subtle px-2 py-2">
          <div className="text-omi-text-muted">{t("dashboard.marketIndex.candleCount")}</div>
          <div className="mt-1 font-semibold text-omi-text">{snapshot?.pointCount ?? "-"}</div>
        </div>
        <div className="border border-omi-border-subtle bg-omi-surface-subtle px-2 py-2">
          <div className="text-omi-text-muted">{t("common.update")}</div>
          <div className="mt-1 truncate font-semibold text-omi-text">
            {snapshot?.asOf ? formatRowTime(snapshot.asOf) ?? snapshot.asOf.slice(0, 10) : "-"}
          </div>
        </div>
      </div>
    </div>
  );
}

export function JPMarketTape({
  selectedSymbol,
  selectedStock,
  selectedGroupName,
  onError,
}: {
  selectedSymbol: string | null;
  selectedStock: JPStockMasterRead | null;
  selectedGroupName: string | null;
  onError: (error: unknown) => void;
}) {
  const t = useT();
  const state = useJpMarketTapeState({
    selectedSymbol,
    selectedStock,
    selectedGroupName,
    onError,
  });
  const overview = state.overview;
  const breadth = overview?.breadth ?? null;
  const breadthComparisonCount = breadth
    ? breadth.advance_count + breadth.decline_count + breadth.unchanged_count
    : 0;
  const advanceRatio =
    breadth && breadthComparisonCount > 0
      ? (breadth.advance_count / breadthComparisonCount) * 100
      : null;
  const strongestSector = (overview?.sectors ?? []).reduce<JPMarketSectorBreadthRead | null>(
    (current, sector) => {
    if (sector.average_change_pct === null) return current;
    if (current?.average_change_pct === null || current === null) return sector;
    return sector.average_change_pct > current.average_change_pct ? sector : current;
    },
    null
  );
  const primaryIndexOverview = overview?.indices.find((item) => item.symbol === "^N225") ?? null;

  return (
    <section
      className="mb-3 border border-omi-border-subtle bg-omi-surface"
      data-testid="market-tape-jp"
      data-load-state={state.loadState}
    >
      <div className="grid gap-px bg-omi-surface-strong lg:grid-cols-2">
        <JPMarketTapeCard
          title={t("dashboard.marketIndex.market")}
          snapshot={state.primarySnapshot}
          loadState={state.loadState}
        />
        <JPMarketTapeCard
          title={t("dashboard.marketIndex.context")}
          snapshot={state.contextSnapshot}
          loadState={state.loadState}
        />
      </div>
      {overview ? (
        <div
          className="grid gap-px border-t border-omi-border-subtle bg-omi-surface-strong sm:grid-cols-2 lg:grid-cols-4"
          data-testid="market-overview-jp"
          data-coverage-status={overview.coverage.status}
        >
          <div className="bg-omi-surface px-4 py-3 text-xs">
            <div className="text-omi-text-muted">
              {t("dashboard.marketIndex.advanceDecline")}
            </div>
            <div className="mt-1 font-semibold">
              <span className="text-omi-market-up">{breadth?.advance_count ?? "-"}</span>
              <span className="px-1 text-omi-text-subtle">/</span>
              <span className="text-omi-market-down">{breadth?.decline_count ?? "-"}</span>
            </div>
          </div>
          <div className="bg-omi-surface px-4 py-3 text-xs">
            <div className="text-omi-text-muted">{t("dashboard.marketIndex.breadth")}</div>
            <div className={`mt-1 font-semibold ${valueTone((advanceRatio ?? 50) - 50)}`}>
              {advanceRatio === null
                ? "-"
                : t("dashboard.marketIndex.advancePct", {
                    value: advanceRatio.toFixed(0),
                  })}
            </div>
          </div>
          <div className="bg-omi-surface px-4 py-3 text-xs">
            <div className="text-omi-text-muted">{t("dashboard.marketIndex.coverage")}</div>
            <div className="mt-1 font-semibold text-omi-text">
              {t("dashboard.marketIndex.coverageValue", {
                current: overview.coverage.current_symbol_count,
                active: overview.coverage.active_stock_count,
              })}
            </div>
            <div className={overview.coverage.is_partial ? "text-omi-warning" : "text-omi-text-muted"}>
              {t(
                overview.coverage.is_partial
                  ? "dashboard.marketIndex.partialCoverage"
                  : "dashboard.marketIndex.currentCoverage"
              )}
            </div>
          </div>
          <div className="bg-omi-surface px-4 py-3 text-xs">
            <div className="text-omi-text-muted">
              {t("dashboard.marketIndex.strongestSector")}
            </div>
            <div className="mt-1 truncate font-semibold text-omi-text">
              {strongestSector?.sector ?? "-"}
            </div>
            <div className={valueTone(strongestSector?.average_change_pct)}>
              {formatPct(strongestSector?.average_change_pct)}
            </div>
          </div>
        </div>
      ) : null}
      <div className="border-t border-omi-border-subtle px-4 py-2 text-xs text-omi-text-muted">
        {state.asOf
          ? t("dashboard.marketIndex.jpUpdated", {
              asOf: formatRowTime(state.asOf) ?? state.asOf.slice(0, 10),
            })
          : t("dashboard.marketIndex.jpWaiting")}
        {state.primarySnapshot?.isCurrent === false ? (
          <span className="ml-2 text-omi-warning">
            {`資料日期 ${state.primarySnapshot.asOf?.slice(0, 10) ?? "-"}，預期 ${
              state.primarySnapshot.expectedTradeDate ?? "-"
            }`}
          </span>
        ) : null}
        {overview ? (
          <span className="ml-2">
            {t("dashboard.marketIndex.expectedDate", {
              date: overview.expected_trade_date,
            })}
          </span>
        ) : null}
        {primaryIndexOverview?.is_current === false ? (
          <span className="ml-2 text-omi-warning">
            {`${primaryIndexOverview.label} ${primaryIndexOverview.latest_data_date ?? "-"}`}
          </span>
        ) : null}
      </div>
    </section>
  );
}

function KRMarketTapeCard({
  title,
  snapshot,
  loadState,
}: {
  title: string;
  snapshot: KRMarketTapeSnapshot | null;
  loadState: DashboardLoadState;
}) {
  const t = useT();
  const breadth = snapshot?.breadth ?? null;
  const advanceRatio =
    breadth && breadth.total_count > 0
      ? (breadth.advance_count / breadth.total_count) * 100
      : null;

  return (
    <div className="bg-omi-surface px-4 py-3">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="text-xs font-semibold uppercase tracking-[0.16em] text-omi-text-muted">
            {title}
          </div>
          <div className="mt-1 flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className="text-lg font-bold text-omi-text-strong">
              {snapshot ? snapshot.name : loadState === "loading" ? t("common.loading") : "-"}
            </span>
            <span className="text-2xl font-black text-omi-text-strong">
              {formatPrice(snapshot?.close)}
            </span>
            <span className={`text-sm font-bold ${valueTone(snapshot?.changePct)}`}>
              {formatSignedNumber(snapshot?.change)} / {formatPct(snapshot?.changePct)}
            </span>
          </div>
          <div className="mt-1 text-xs text-omi-text-muted">
            {snapshot
              ? `${snapshot.displaySymbol} · ${snapshot.exchange} · ${t("dashboard.marketIndex.daily")}`
              : t("dashboard.marketIndex.waitingData")}
          </div>
        </div>
        <div className="text-right text-xs">
          <div className="font-semibold text-omi-text">
            {regionalMarketRegimeLabel(t, snapshot)}
          </div>
          <div className={valueTone(snapshot?.priceVsMa20)}>
            {formatPct(snapshot?.priceVsMa20)} vs MA20
          </div>
        </div>
      </div>

      <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
        <div className="border border-omi-border-subtle bg-omi-surface-subtle px-2 py-2">
          <div className="text-omi-text-muted">{t("dashboard.marketIndex.tradeValueYi")}</div>
          <div className="mt-1 font-semibold text-omi-text">
            {formatTradeValueYi(breadth?.trade_value)}
          </div>
        </div>
        <div className="border border-omi-border-subtle bg-omi-surface-subtle px-2 py-2">
          <div className="text-omi-text-muted">{t("dashboard.marketIndex.advanceDecline")}</div>
          <div className="mt-1 font-semibold">
            <span className="text-omi-market-up">{breadth?.advance_count ?? "-"}</span>
            <span className="px-1 text-omi-text-subtle">/</span>
            <span className="text-omi-market-down">{breadth?.decline_count ?? "-"}</span>
          </div>
        </div>
        <div className="border border-omi-border-subtle bg-omi-surface-subtle px-2 py-2">
          <div className="text-omi-text-muted">{t("dashboard.marketIndex.breadth")}</div>
          <div className={`mt-1 font-semibold ${valueTone((advanceRatio ?? 50) - 50)}`}>
            {advanceRatio === null
              ? "-"
              : t("dashboard.marketIndex.advancePct", { value: advanceRatio.toFixed(0) })}
          </div>
        </div>
      </div>
    </div>
  );
}

export function KRMarketTape({
  selectedSymbol,
  selectedStock,
  selectedGroupName,
  onError,
}: {
  selectedSymbol: string | null;
  selectedStock: KRStockMasterRead | null;
  selectedGroupName: string | null;
  onError: (error: unknown) => void;
}) {
  const t = useT();
  const state = useKrMarketTapeState({
    selectedSymbol,
    selectedStock,
    selectedGroupName,
    onError,
  });

  return (
    <section
      className="mb-3 border border-omi-border-subtle bg-omi-surface"
      data-testid="market-tape-kr"
      data-load-state={state.loadState}
    >
      <div className="grid gap-px bg-omi-surface-strong lg:grid-cols-2">
        <KRMarketTapeCard
          title={t("dashboard.marketIndex.market")}
          snapshot={state.primarySnapshot}
          loadState={state.loadState}
        />
        <KRMarketTapeCard
          title={t("dashboard.marketIndex.context")}
          snapshot={state.contextSnapshot}
          loadState={state.loadState}
        />
      </div>
      <div className="border-t border-omi-border-subtle px-4 py-2 text-xs text-omi-text-muted">
        {state.asOf
          ? t("dashboard.marketIndex.krUpdated", { asOf: state.asOf.slice(0, 10) })
          : t("dashboard.marketIndex.krWaiting")}
      </div>
    </section>
  );
}
