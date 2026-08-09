"use client";

import { LoadingDots } from "@/components/LoadingPlaceholders";
import { summarizeIntradayPoints } from "@/components/stock-detail/stockDetailAnalytics";
import {
  formatContributionPoint,
  formatDate,
  formatDateTime,
  formatNumber,
  formatPct,
  formatPrice,
  formatSignedContracts,
  formatSignedLots,
  formatSignedPrice,
  formatSignedTradeValueYi,
  formatTradeValueYi,
  valueTone,
} from "@/components/stock-detail/stockDetailFormatters";
import type {
  LoadState,
  Timeframe,
} from "@/components/stock-detail/stockDetailTypes";
import { useT, type TranslationFunction } from "@/i18n";
import type {
  ChartPoint,
  MarketChipDaily,
  MarketIndexContributionItem,
  MarketIndexContributionResponse,
  MarketIndexListItem,
  MarketIndexSnapshot,
} from "@/types/market";

export function marketRegimeLabel(
  index: MarketIndexSnapshot | null | undefined,
  t?: TranslationFunction
) {
  if (!index || index.close === null || index.close === undefined) {
    return t?.("dashboard.marketIndex.insufficient") ?? "Insufficient data";
  }

  if (index.price_vs_ma20 !== null && index.price_vs_ma20 !== undefined) {
    if (index.price_vs_ma20 > 1) return t?.("dashboard.marketIndex.aboveMa20") ?? "Above MA20";
    if (index.price_vs_ma20 < -1) return t?.("dashboard.marketIndex.belowMa20") ?? "Below MA20";
  }

  if (index.change_pct !== null && index.change_pct !== undefined) {
    if (index.change_pct > 0) return t?.("dashboard.marketIndex.bullishShort") ?? "Short-term bullish";
    if (index.change_pct < 0) return t?.("dashboard.marketIndex.weakShort") ?? "Short-term weak";
  }

  return t?.("dashboard.marketIndex.neutral") ?? "Rangebound";
}

function taiwanBreadthScopeLabel(
  index: MarketIndexSnapshot | null | undefined,
  t: TranslationFunction
) {
  const breadth = index?.breadth;
  if (!breadth) {
    return t(
      index?.index_id === "TPEX"
        ? "dashboard.marketIndex.tpexFullBreadth"
        : "dashboard.marketIndex.twseFullBreadth"
    );
  }
  if (breadth.scope === "registered_universe") {
    return t("dashboard.marketIndex.registeredBreadth");
  }
  if (breadth.scope === "full_market") {
    return t(
      breadth.market === "TPEX" || index?.index_id === "TPEX"
        ? "dashboard.marketIndex.tpexFullBreadth"
        : "dashboard.marketIndex.twseFullBreadth"
    );
  }
  if (breadth.scope === "omi_sample") {
    return t("dashboard.marketIndex.sampleBreadth");
  }
  return t("dashboard.marketIndex.localDatasetBreadth");
}

const marketIndexListNameKeys: Record<string, string> = {
  加權指數: "taiex",
  櫃買指數: "tpex",
  水泥窯製: "cementKiln",
  水泥: "cement",
  食品: "food",
  塑膠化工: "plasticsChemicals",
  塑膠: "plastics",
  紡織纖維: "textiles",
  機電: "electricalMachinery",
  電機機械: "electricMachinery",
  電器電纜: "electricalCable",
  化學生技醫療: "chemicalBiotechMedical",
  化學: "chemical",
  生技醫療: "biotechMedical",
  玻璃陶瓷: "glassCeramics",
  造紙: "paper",
  鋼鐵: "steel",
  橡膠: "rubber",
  汽車: "automobile",
  半導體: "semiconductor",
  電腦及週邊設備: "computerPeripheral",
  光電: "optoelectronics",
  通信網路: "communicationsInternet",
  電子零組件: "electronicParts",
  電子通路: "electronicDistribution",
  資訊服務: "informationService",
  其他電子: "otherElectronics",
  建材營造: "buildingMaterialConstruction",
  航運: "shipping",
  航運業: "shipping",
  觀光: "tourism",
  觀光餐旅: "tourismHospitality",
  金融保險: "financialInsurance",
  貿易百貨: "tradingConsumersGoods",
  油電燃氣: "oilGasElectricity",
  存託憑證: "depositaryReceipts",
  電子: "electronics",
  金融: "financial",
  非金電: "nonFinanceNonElectronics",
  其他: "other",
};

function normalizeMarketIndexListName(name: string) {
  const trimmedName = name.trim();

  if (trimmedName === "發行量加權股價指數") return "加權指數";
  if (trimmedName.endsWith("類指數")) return trimmedName.slice(0, -"類指數".length);

  return trimmedName;
}

function marketIndexListDisplayName(name: string, t: TranslationFunction) {
  const normalizedName = normalizeMarketIndexListName(name);
  const key = marketIndexListNameKeys[normalizedName];

  if (!key) return normalizedName || name;

  return t(`stockDetail.dataViews.indexList.names.${key}`);
}

export function IndexListPanel({
  items,
  loadState,
  marketLabel,
}: {
  items: MarketIndexListItem[];
  loadState: LoadState;
  marketLabel: string;
}) {
  const t = useT();

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="border-b border-omi-border-subtle px-5 py-4">
        <div className="text-xs font-semibold uppercase tracking-[0.18em] text-omi-text-muted">
          Market
        </div>
        <div className="mt-2 flex items-end justify-between gap-4">
          <div>
            <div className="text-xl font-bold text-omi-text-strong">
              {t("stockDetail.dataViews.indexList.title", { marketLabel })}
            </div>
            {loadState === "loading" ? (
              <div className="mt-1 inline-flex items-center gap-2 text-xs text-omi-text-muted">
                {t("stockDetail.dataViews.indexList.loading")}
                <LoadingDots
                  label={t("stockDetail.dataViews.indexList.loadingLabel", {
                    marketLabel,
                  })}
                />
              </div>
            ) : (
              <div className="mt-1 text-xs text-omi-text-muted">
                {t("stockDetail.dataViews.indexList.count", { count: items.length })}
              </div>
            )}
          </div>
          <div className="text-right text-xs font-semibold text-omi-text-muted">
            {marketLabel}
          </div>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-3">
        {items.length > 0 ? (
          items.map((item) => (
            <div
              key={`${item.market}-${item.rank}-${item.name}`}
              className="grid grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-3 border-t border-omi-border-subtle py-2 text-sm first:border-t-0"
            >
              <div className="min-w-0">
                <div className="truncate font-semibold text-omi-text">
                  {item.rank}. {marketIndexListDisplayName(item.name, t)}
                </div>
                <div className="mt-0.5 text-xs text-omi-text-muted">
                  {item.trade_date ?? "-"}
                </div>
              </div>
              <div className="text-right font-semibold text-omi-text-strong">
                {formatPrice(item.close)}
              </div>
              <div className={`min-w-20 text-right font-semibold ${valueTone(item.change_pct)}`}>
                <div>{formatPct(item.change_pct)}</div>
                <div className="text-xs font-medium">{formatSignedPrice(item.change)}</div>
              </div>
            </div>
          ))
        ) : loadState === "loading" ? (
          <div className="space-y-0" aria-hidden="true">
            {Array.from({ length: 6 }).map((_, index) => (
              <div
                key={index}
                className="grid grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-3 border-t border-omi-border-subtle py-2 first:border-t-0"
              >
                <div className="min-w-0 space-y-2">
                  <div className="omi-skeleton h-3.5 w-32" />
                  <div className="omi-skeleton h-2.5 w-20" />
                </div>
                <div className="omi-skeleton h-3.5 w-16" />
                <div className="omi-skeleton h-7 w-20" />
              </div>
            ))}
          </div>
        ) : (
          <div className="py-10 text-center text-sm text-omi-text-muted">
            {t("stockDetail.dataViews.indexList.empty")}
          </div>
        )}
      </div>
    </div>
  );
}
export function IndexDetailDataPanel({
  index,
  timeframe,
  latestChart,
  todayStats,
  todayPreviousClose,
  marketChip,
  marketChipLoadState,
  contributions,
  contributionLoadState,
}: {
  index: MarketIndexSnapshot | null;
  timeframe: Timeframe;
  latestChart: ChartPoint | null;
  todayStats: ReturnType<typeof summarizeIntradayPoints>;
  todayPreviousClose: number | null;
  marketChip: MarketChipDaily | null;
  marketChipLoadState: LoadState;
  contributions: MarketIndexContributionResponse | null;
  contributionLoadState: LoadState;
}) {
  const t = useT();
  const isToday = timeframe === "today";
  const breadth = index?.breadth ?? null;
  const contractsUnit = t("stockDetail.dataViews.indexDetail.contractsUnit");
  const open = isToday
    ? todayStats.open ?? index?.open ?? latestChart?.open ?? null
    : latestChart?.open ?? index?.open ?? null;
  const high = isToday
    ? todayStats.high ?? index?.high ?? latestChart?.high ?? null
    : latestChart?.high ?? index?.high ?? null;
  const low = isToday
    ? todayStats.low ?? index?.low ?? latestChart?.low ?? null
    : latestChart?.low ?? index?.low ?? null;
  const reference = todayPreviousClose ?? index?.previous_close ?? null;
  const tradeValue = index?.trade_value ?? breadth?.trade_value ?? latestChart?.trade_value ?? null;
  const estimatedTradeValue = index?.estimated_trade_value ?? tradeValue;
  const breadthScopeLabel = taiwanBreadthScopeLabel(index, t);
  const breadthCoverageText =
    breadth?.coverage_count !== null &&
    breadth?.coverage_count !== undefined &&
    breadth?.unknown_count !== null &&
    breadth?.unknown_count !== undefined
      ? t("stockDetail.dataViews.indexDetail.breadthCoverage", {
          coverage: formatNumber(breadth.coverage_count),
          total: formatNumber(breadth.total_count),
          unknown: formatNumber(breadth.unknown_count),
        })
      : null;
  const marginStatusText = (() => {
    const status = marketChip?.margin_status;
    if (!status) return null;

    const dataDate = status.data_date ? formatDate(status.data_date) : "-";
    const expectedDate = status.expected_data_date
      ? formatDate(status.expected_data_date)
      : "-";
    if (status.pending_trade_date) {
      return t("stockDetail.dataViews.indexDetail.marginPending", {
        dataDate,
        pendingDate: formatDate(status.pending_trade_date),
      });
    }
    if (status.status === "partial") {
      return t("stockDetail.dataViews.indexDetail.marginPartial", {
        date: dataDate,
      });
    }
    if (status.status === "stale") {
      return t("stockDetail.dataViews.indexDetail.marginStale", {
        dataDate,
        expectedDate,
      });
    }
    if (status.status === "missing") {
      return t("stockDetail.dataViews.indexDetail.marginMissing", {
        date: expectedDate,
      });
    }
    return t("stockDetail.dataViews.indexDetail.marginTradeDate", {
      date: dataDate,
    });
  })();

  return (
    <section className="border border-omi-border-subtle bg-omi-surface">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-omi-border-subtle px-5 py-4">
        <div>
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-omi-text-muted">
            {t("stockDetail.dataViews.indexDetail.eyebrow")}
          </div>
          <div className="mt-1 text-lg font-bold text-omi-text-strong">
            {t("stockDetail.dataViews.indexDetail.title")}
          </div>
        </div>
        <div className="text-right text-xs text-omi-text-muted">
          {t("stockDetail.dataViews.indexDetail.updated", {
            time: formatDateTime(index?.as_of),
          })}
        </div>
      </div>

      <div className="grid gap-2 border-b border-omi-border-subtle p-5 sm:grid-cols-2 xl:grid-cols-4">
        <IndexMetricCard
          label={t("stockDetail.dataViews.indexDetail.open")}
          value={formatPrice(open)}
          tone={valueTone(open !== null && reference !== null ? open - reference : null)}
          testId="index-detail-open"
        />
        <IndexMetricCard
          label={t("stockDetail.dataViews.indexDetail.high")}
          value={formatPrice(high)}
          tone={valueTone(high !== null && reference !== null ? high - reference : null)}
        />
        <IndexMetricCard
          label={t("stockDetail.dataViews.indexDetail.low")}
          value={formatPrice(low)}
          tone={valueTone(low !== null && reference !== null ? low - reference : null)}
        />
        <IndexMetricCard label={t("stockDetail.dataViews.indexDetail.reference")} value={formatPrice(reference)} />
        <IndexMetricCard label={t("stockDetail.dataViews.indexDetail.tradeValueYi")} value={formatTradeValueYi(tradeValue)} />
        <IndexMetricCard label={t("stockDetail.dataViews.indexDetail.estimatedTradeValueYi")} value={formatTradeValueYi(estimatedTradeValue)} />
        <IndexMetricCard label={t("stockDetail.dataViews.indexDetail.advances")} value={formatNumber(breadth?.advance_count)} tone="text-omi-market-up" />
        <IndexMetricCard label={t("stockDetail.dataViews.indexDetail.declines")} value={formatNumber(breadth?.decline_count)} tone="text-omi-market-down" />
        <IndexMetricCard label={t("stockDetail.dataViews.indexDetail.limitUp")} value={formatNumber(breadth?.limit_up_count)} tone="text-omi-market-up" />
        <IndexMetricCard label={t("stockDetail.dataViews.indexDetail.limitDown")} value={formatNumber(breadth?.limit_down_count)} tone="text-omi-market-down" />
        <IndexMetricCard label={t("stockDetail.dataViews.indexDetail.unchanged")} value={formatNumber(breadth?.unchanged_count)} />
        <IndexMetricCard label={t("stockDetail.dataViews.indexDetail.total")} value={formatNumber(breadth?.total_count)} />
      </div>

      <div className="border-b border-omi-border-subtle px-5 py-4">
        <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
          <div>
            <div className="text-xs font-bold text-omi-text-strong">
              {t("stockDetail.dataViews.indexDetail.chipTitle")}
            </div>
            <div className="mt-0.5 text-xs text-omi-text-muted">
              {t("stockDetail.dataViews.indexDetail.chipDescription")}
            </div>
          </div>
          <div className="space-y-0.5 text-right text-xs text-omi-text-muted">
            <div>
              {t("stockDetail.dataViews.indexDetail.tradeDate", {
                date: marketChip?.trade_date ? formatDate(marketChip.trade_date) : "-",
              })}
            </div>
            {marginStatusText ? <div>{marginStatusText}</div> : null}
          </div>
        </div>
        {marketChipLoadState === "loading" ? (
          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4" aria-hidden="true">
            {Array.from({ length: 8 }).map((_, index) => (
              <div key={index} className="border border-omi-border-subtle bg-omi-surface-subtle px-3 py-2">
                <div className="omi-skeleton h-3 w-24" />
                <div className="omi-skeleton mt-2 h-4 w-20" />
              </div>
            ))}
          </div>
        ) : (
          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
            <IndexMetricCard
              label={t("stockDetail.dataViews.indexDetail.foreignNetOi")}
              value={formatSignedContracts(marketChip?.foreign_futures_net_oi, contractsUnit)}
              tone={valueTone(marketChip?.foreign_futures_net_oi)}
            />
            <IndexMetricCard
              label={t("stockDetail.dataViews.indexDetail.foreignNetOiChange")}
              value={formatSignedContracts(
                marketChip?.foreign_futures_net_oi_change,
                contractsUnit
              )}
              tone={valueTone(marketChip?.foreign_futures_net_oi_change)}
            />
            <IndexMetricCard
              label={t("stockDetail.dataViews.indexDetail.retailNetOi")}
              value={formatSignedContracts(marketChip?.retail_futures_net_oi, contractsUnit)}
              tone={valueTone(marketChip?.retail_futures_net_oi)}
            />
            <IndexMetricCard
              label={t("stockDetail.dataViews.indexDetail.retailNetOiChange")}
              value={formatSignedContracts(
                marketChip?.retail_futures_net_oi_change,
                contractsUnit
              )}
              tone={valueTone(marketChip?.retail_futures_net_oi_change)}
            />
            <IndexMetricCard
              label={t("stockDetail.dataViews.indexDetail.totalInstitutionalNetValue")}
              value={formatSignedTradeValueYi(marketChip?.total_institutional_net_value)}
              tone={valueTone(marketChip?.total_institutional_net_value)}
            />
            <IndexMetricCard
              label={t("stockDetail.dataViews.indexDetail.foreignNetValue")}
              value={formatSignedTradeValueYi(marketChip?.foreign_investor_net_value)}
              tone={valueTone(marketChip?.foreign_investor_net_value)}
            />
            <IndexMetricCard
              label={t("stockDetail.dataViews.indexDetail.investmentTrustNetValue")}
              value={formatSignedTradeValueYi(marketChip?.investment_trust_net_value)}
              tone={valueTone(marketChip?.investment_trust_net_value)}
            />
            <IndexMetricCard
              label={t("stockDetail.dataViews.indexDetail.dealerNetValue")}
              value={formatSignedTradeValueYi(marketChip?.dealer_net_value)}
              tone={valueTone(marketChip?.dealer_net_value)}
            />
            <IndexMetricCard
              label={t("stockDetail.dataViews.indexDetail.governmentBankNetValue")}
              value={
                marketChip?.government_bank_status?.status === "not_available"
                  ? t("stockDetail.dataViews.indexDetail.notAvailable")
                  : formatSignedTradeValueYi(marketChip?.government_bank_net_value)
              }
              tone={valueTone(marketChip?.government_bank_net_value)}
            />
            <IndexMetricCard
              label={t("stockDetail.dataViews.indexDetail.marginChangeValue")}
              value={formatSignedTradeValueYi(marketChip?.margin_balance_change_value)}
              tone={valueTone(marketChip?.margin_balance_change_value)}
            />
            <IndexMetricCard
              label={t("stockDetail.dataViews.indexDetail.marginChangeShares")}
              value={formatSignedLots(marketChip?.margin_balance_change_shares)}
              tone={valueTone(marketChip?.margin_balance_change_shares)}
            />
            <IndexMetricCard
              label={t("stockDetail.dataViews.indexDetail.shortChangeShares")}
              value={formatSignedLots(marketChip?.short_balance_change_shares)}
              tone={valueTone(marketChip?.short_balance_change_shares)}
            />
          </div>
        )}
      </div>

      <IndexContributionRanking
        contributions={contributions}
        loadState={contributionLoadState}
      />

      <div className="space-y-1 px-5 py-3 text-xs text-omi-text-muted">
        <div className="font-semibold text-omi-text">{breadthScopeLabel}</div>
        <div>
          {index?.breadth_status?.status === "failed"
            ? t("dashboard.marketIndex.breadthFailed")
            : index?.breadth_status?.status === "pending"
              ? t("dashboard.marketIndex.breadthPending")
            : index?.breadth_status?.status === "partial"
              ? t("dashboard.marketIndex.breadthPartial")
              : breadth?.source
            ? t("stockDetail.dataViews.indexDetail.breadthSource", {
                source: breadth.source,
              })
            : t("stockDetail.dataViews.indexDetail.breadthPending")}
        </div>
        {breadthCoverageText ? <div>{breadthCoverageText}</div> : null}
        {breadth?.snapshot_as_of || breadth?.as_of ? (
          <div>
            {t("dashboard.marketIndex.breadthUpdated", {
              asOf: formatDateTime(breadth.snapshot_as_of ?? breadth.as_of),
            })}
          </div>
        ) : null}
        {breadth?.auction_breadth?.status === "provisional" ? (
          <div>
            {t("dashboard.marketIndex.auctionProvisional", {
              advance: breadth.auction_breadth.advance_count,
              decline: breadth.auction_breadth.decline_count,
              unchanged: breadth.auction_breadth.unchanged_count,
            })}
          </div>
        ) : null}
      </div>
    </section>
  );
}

export function IndexMetricCard({
  label,
  value,
  tone = "text-omi-text",
  testId,
}: {
  label: string;
  value: string;
  tone?: string;
  testId?: string;
}) {
  return (
    <div
      className="border border-omi-border-subtle bg-omi-surface-subtle px-3 py-2"
      data-testid={testId}
    >
      <div className="text-xs font-semibold text-omi-text-muted">{label}</div>
      <div className={`mt-1 text-base font-bold ${tone}`}>{value}</div>
    </div>
  );
}

export function ContributionColumn({
  title,
  items,
  tone,
}: {
  title: string;
  items: MarketIndexContributionItem[];
  tone: string;
}) {
  const t = useT();

  return (
    <div className="min-w-0">
      <div className="mb-2 text-xs font-bold uppercase tracking-[0.14em] text-omi-text-muted">
        {title}
      </div>
      <div className="overflow-hidden border border-omi-border-subtle">
        {items.length > 0 ? (
          items.map((item) => (
            <div
              key={`${title}-${item.stock_id}`}
              className="grid grid-cols-[34px_minmax(0,1fr)_82px_88px] items-center border-b border-omi-border-subtle px-3 py-2 text-xs last:border-b-0"
            >
              <div className="text-omi-text-muted">#{item.rank}</div>
              <div className="min-w-0">
                <div className="truncate font-semibold text-omi-text-strong">
                  {item.stock_id} {item.stock_name ?? ""}
                </div>
                <div className="mt-0.5 text-omi-text-muted">
                  {formatPrice(item.close)} / {formatPct(item.change_pct)}
                </div>
              </div>
              <div className={`text-right font-bold ${tone}`}>
                {formatContributionPoint(item.contribution_points)}
              </div>
              <div className="text-right text-omi-text-muted">
                {formatTradeValueYi(item.trade_value)}
              </div>
            </div>
          ))
        ) : (
          <div className="px-3 py-8 text-center text-sm text-omi-text-muted">
            {t("stockDetail.dataViews.contribution.empty")}
          </div>
        )}
      </div>
    </div>
  );
}

export function IndexContributionRanking({
  contributions,
  loadState,
}: {
  contributions: MarketIndexContributionResponse | null;
  loadState: LoadState;
}) {
  const t = useT();

  return (
    <div className="border-b border-omi-border-subtle px-5 py-4">
      <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-omi-text-muted">
            {t("stockDetail.dataViews.contribution.eyebrow")}
          </div>
          <div className="mt-1 text-base font-bold text-omi-text-strong">
            {t("stockDetail.dataViews.contribution.title")}
          </div>
        </div>
        <div className="text-right text-xs text-omi-text-muted">
          {loadState === "loading"
            ? t("stockDetail.dataViews.contribution.loading")
            : contributions?.trade_date
              ? t("stockDetail.dataViews.contribution.tradeDatePoints", {
                  date: contributions.trade_date,
                })
              : t("stockDetail.dataViews.contribution.pointsEstimated")}
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <ContributionColumn
          title={t("stockDetail.dataViews.contribution.positive")}
          items={contributions?.positive ?? []}
          tone="text-omi-market-up"
        />
        <ContributionColumn
          title={t("stockDetail.dataViews.contribution.negative")}
          items={contributions?.negative ?? []}
          tone="text-omi-market-down"
        />
      </div>
    </div>
  );
}
