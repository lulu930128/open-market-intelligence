"use client";

import {
  branchDayOptions,
  branchTableSideOptions,
  institutionalDisplayMonths,
  largeHolderLotOptions,
  minimumUsableFinancialRows,
  minimumUsableRevenueRows,
  smallHolderLotOptions,
} from "@/components/stock-detail/StockDetailPanelConstants";
import {
  ChipMetricBlock,
  DataPanelLoadingState,
  DataPanelRefreshRail,
  EarningsTrendChart,
  EmptyDataState,
  InstitutionalFlowChart,
  MetricRow,
  RevenueTrendChart,
  SegmentedNumberButtons,
  ShareholdingMixedChart,
  ShareholdingRatioChart,
  addMonthsToDateText,
  buildEarningsSeries,
  formatCompactDate,
  formatDate,
  formatLotUnits,
  formatMonthDay,
  formatNumber,
  formatPct,
  formatPrice,
  formatRatioPct,
  formatRevenueYiValue,
  formatSignedLots,
  rebuildInstitutionalCumulative,
  toRevenueYi,
  valueTone,
} from "@/components/stock-detail/StockDetailDataViews";
import type {
  BranchTableSide,
  DataPanelTab,
  EarningsSeriesPoint,
  EarningsView,
  InstitutionalSeriesPoint,
  RevenueSeriesPoint,
  RevenueView,
  ShareholdingSeriesPoint,
} from "@/components/stock-detail/StockDetailDataViews";
import type {
  BrokerBranchTradeDailyRead,
  BrokerBranchTradeDailySummaryRead,
  FinancialMetricQuarterlyRead,
  InstitutionalHoldingRatioRead,
  InstitutionalTradeDailyRead,
  MarginTradingDailyRead,
  MonthlyRevenueRead,
  ShareholdingDistributionWeeklyRead,
  StockChipCoverageRead,
} from "@/types/market";
import { useT } from "@/i18n";
import type { Dispatch, SetStateAction } from "react";

type StockDetailDataPanelProps = {
  activeDataTab: DataPanelTab;
  branchDays: number;
  branchTableSide: BranchTableSide;
  brokerBranchSummary: BrokerBranchTradeDailySummaryRead | null;
  chipCoverage: StockChipCoverageRead | null;
  dataPanelLoading: DataPanelTab | null;
  dataPanelMessage: string | null;
  earningsSeries: EarningsSeriesPoint[];
  earningsView: EarningsView;
  financialMetric: FinancialMetricQuarterlyRead | null;
  financialMetricHistory: FinancialMetricQuarterlyRead[];
  institutionalHoldingRatio: InstitutionalHoldingRatioRead | null;
  institutionalHistory: InstitutionalTradeDailyRead[];
  institutionalHoverDate: string | null;
  institutionalSeries: InstitutionalSeriesPoint[];
  largeHolderLots: number;
  margin: MarginTradingDailyRead | null;
  monthlyRevenue: MonthlyRevenueRead | null;
  monthlyRevenueHistory: MonthlyRevenueRead[];
  revenueSeries: RevenueSeriesPoint[];
  revenueView: RevenueView;
  revenueYear: number | null;
  setBranchDays: Dispatch<SetStateAction<number>>;
  setBranchTableSide: Dispatch<SetStateAction<BranchTableSide>>;
  setEarningsView: Dispatch<SetStateAction<EarningsView>>;
  setInstitutionalHoverDate: Dispatch<SetStateAction<string | null>>;
  setLargeHolderLots: Dispatch<SetStateAction<number>>;
  setRevenueView: Dispatch<SetStateAction<RevenueView>>;
  setRevenueYear: Dispatch<SetStateAction<number | null>>;
  setSmallHolderLots: Dispatch<SetStateAction<number>>;
  shareholding: ShareholdingDistributionWeeklyRead[];
  shareholdingSeries: ShareholdingSeriesPoint[];
  smallHolderLots: number;
  stockId: string;
};

export default function StockDetailDataPanel({
  activeDataTab,
  branchDays,
  branchTableSide,
  brokerBranchSummary,
  chipCoverage,
  dataPanelLoading,
  dataPanelMessage,
  earningsSeries,
  earningsView,
  financialMetric,
  financialMetricHistory,
  institutionalHoldingRatio,
  institutionalHistory,
  institutionalHoverDate,
  institutionalSeries,
  largeHolderLots,
  margin,
  monthlyRevenue,
  monthlyRevenueHistory,
  revenueSeries,
  revenueView,
  revenueYear,
  setBranchDays,
  setBranchTableSide,
  setEarningsView,
  setInstitutionalHoverDate,
  setLargeHolderLots,
  setRevenueView,
  setRevenueYear,
  setSmallHolderLots,
  shareholding,
  shareholdingSeries,
  smallHolderLots,
  stockId,
}: StockDetailDataPanelProps) {
  const t = useT();
  const selectedStockId = stockId;
  const lotUnit = t("stockDetail.dataPanel.units.lots");

  function hasRowsFromOtherStock<T extends { stock_id: string }>(rows: T[]) {
    return rows.some((row) => row.stock_id !== selectedStockId);
  }

  function activeDataTabHasStaleData() {
    if (activeDataTab === "chips") {
      return (
        (margin !== null && margin.stock_id !== selectedStockId) ||
        hasRowsFromOtherStock(shareholding)
      );
    }

    if (activeDataTab === "institutional") {
      return hasRowsFromOtherStock(institutionalHistory);
    }

    if (activeDataTab === "branch") {
      return (
        brokerBranchSummary !== null &&
        (brokerBranchSummary.stock_id !== selectedStockId ||
          brokerBranchSummary.requested_days !== branchDays)
      );
    }

    if (activeDataTab === "revenue") {
      return (
        (monthlyRevenue !== null && monthlyRevenue.stock_id !== selectedStockId) ||
        hasRowsFromOtherStock(monthlyRevenueHistory)
      );
    }

    if (activeDataTab === "earnings") {
      return (
        (financialMetric !== null && financialMetric.stock_id !== selectedStockId) ||
        hasRowsFromOtherStock(financialMetricHistory)
      );
    }

    return false;
  }

  function activeDataTabHasRenderableData() {
    if (activeDataTab === "chips") {
      return (
        (margin !== null && margin.stock_id === selectedStockId) ||
        shareholding.some((row) => row.stock_id === selectedStockId)
      );
    }

    if (activeDataTab === "institutional") {
      return institutionalHistory.some((row) => row.stock_id === selectedStockId);
    }

    if (activeDataTab === "branch") {
      return (
        brokerBranchSummary !== null &&
        brokerBranchSummary.stock_id === selectedStockId &&
        brokerBranchSummary.requested_days === branchDays
      );
    }

    if (activeDataTab === "revenue") {
      const currentRows = monthlyRevenueHistory.filter(
        (row) => row.stock_id === selectedStockId
      );

      return currentRows.length >= minimumUsableRevenueRows;
    }

    if (activeDataTab === "earnings") {
      const currentRows = financialMetricHistory.filter(
        (row) => row.stock_id === selectedStockId
      );

      return currentRows.length >= minimumUsableFinancialRows;
    }

    return false;
  }

  function renderChipTab() {
    const hasShareholding = shareholdingSeries.length > 0;
    const hasMargin = margin !== null;
    const currentChipCoverage = chipCoverage?.stock_id === stockId ? chipCoverage : null;

    if (!hasShareholding && !hasMargin) {
      return <EmptyDataState message={t("stockDetail.dataPanel.empty.chips")} />;
    }

    return (
      <div className="space-y-5">
        {currentChipCoverage ? (
          <div className="text-xs leading-5 text-omi-text-muted">
            {t("stockDetail.dataPanel.chipCoverage", {
              shareholdingDate: formatDate(currentChipCoverage.shareholding_latest_date),
              weekCount: currentChipCoverage.shareholding_week_count,
              marginDate: formatDate(currentChipCoverage.margin_latest_trade_date),
              marginRows: currentChipCoverage.margin_row_count,
            })}
          </div>
        ) : null}

        <div className="space-y-2">
          <SegmentedNumberButtons
            label={t("stockDetail.dataPanel.largeHolderLotsGt")}
            suffix=""
            options={largeHolderLotOptions}
            value={largeHolderLots}
            onChange={setLargeHolderLots}
          />
          <SegmentedNumberButtons
            label={t("stockDetail.dataPanel.smallHolderLotsLt")}
            suffix=""
            options={smallHolderLotOptions}
            value={smallHolderLots}
            onChange={setSmallHolderLots}
          />
        </div>

        <ShareholdingMixedChart points={shareholdingSeries} />
        <ShareholdingRatioChart points={shareholdingSeries} />

        <div className="overflow-hidden border border-omi-border-subtle">
          <div className="grid grid-cols-[1.1fr_1fr_1fr_1fr_1fr] bg-omi-surface-subtle text-center text-xs font-semibold text-omi-text-muted">
            <div className="px-2 py-2 text-left">{t("stockDetail.dataPanel.columns.date")}</div>
            <div className="border-l border-omi-border-subtle px-2 py-2">{t("stockDetail.dataPanel.columns.largeHolderRatio")}</div>
            <div className="border-l border-omi-border-subtle px-2 py-2">{t("stockDetail.dataPanel.columns.largeHolderChange")}</div>
            <div className="border-l border-omi-border-subtle px-2 py-2">{t("stockDetail.dataPanel.columns.largeHolderCount")}</div>
            <div className="border-l border-omi-border-subtle px-2 py-2">{t("stockDetail.dataPanel.columns.smallHolderRatio")}</div>
          </div>
          {shareholdingSeries
            .slice()
            .reverse()
            .slice(0, 12)
            .map((row) => (
              <div
                key={row.date}
                className="grid grid-cols-[1.1fr_1fr_1fr_1fr_1fr] border-t border-omi-border-subtle text-center text-xs"
              >
                <div className="bg-omi-surface-subtle px-2 py-2 text-left font-semibold text-omi-text-muted">
                  {formatCompactDate(row.date)}
                </div>
                <div className="border-l border-omi-border-subtle px-2 py-2 text-omi-text-strong">
                  {formatPrice(row.largeRatio)}
                </div>
                <div className={`border-l border-omi-border-subtle px-2 py-2 ${valueTone(row.largeRatioChange)}`}>
                  {formatPct(row.largeRatioChange)}
                </div>
                <div className="border-l border-omi-border-subtle px-2 py-2 text-omi-text-strong">
                  {formatNumber(row.largeHolders)}
                </div>
                <div className="border-l border-omi-border-subtle px-2 py-2 text-omi-text-strong">
                  {formatPrice(row.smallRatio)}
                </div>
              </div>
            ))}
        </div>

        {margin ? (
          <ChipMetricBlock title={t("stockDetail.dataPanel.marginShort")}>
            <MetricRow label={t("stockDetail.dataPanel.marginBalance")} value={formatNumber(margin.margin_today_balance)} />
            <MetricRow label={t("stockDetail.dataPanel.shortBalance")} value={formatNumber(margin.short_today_balance)} />
            <MetricRow label={t("stockDetail.dataPanel.offset")} value={formatNumber(margin.offset)} />
            <MetricRow
              label={t("stockDetail.dataPanel.marginBuySell")}
              value={`${formatNumber(margin.margin_buy)} / ${formatNumber(margin.margin_sell)}`}
            />
          </ChipMetricBlock>
        ) : null}
      </div>
    );
  }

  function renderInstitutionalTab() {
    if (!institutionalSeries.length) {
      return <EmptyDataState message={t("stockDetail.dataPanel.empty.institutional")} />;
    }

    const latestPoint = institutionalSeries[institutionalSeries.length - 1];
    const displayStartDate = addMonthsToDateText(latestPoint.date, -institutionalDisplayMonths);
    const recentPoints = rebuildInstitutionalCumulative(
      institutionalSeries.filter((point) => point.date >= displayStartDate)
    );
    const displayLatestPoint = recentPoints[recentPoints.length - 1] ?? latestPoint;
    const activeDailyPoint =
      recentPoints.find((point) => point.date === institutionalHoverDate) ?? displayLatestPoint;
    const currentHoldingRatio =
      institutionalHoldingRatio?.stock_id === selectedStockId ? institutionalHoldingRatio : null;
    const ratioHistory = currentHoldingRatio?.history ?? [];
    const activeHoldingRatio = institutionalHoverDate
      ? ratioHistory.find((point) => point.trade_date === institutionalHoverDate) ?? null
      : currentHoldingRatio;
    const ratioDate =
      institutionalHoverDate ?? activeHoldingRatio?.trade_date ?? activeDailyPoint.date;
    const tableRows = recentPoints.slice().reverse();
    const handleInstitutionalHoverPoint = (point: InstitutionalSeriesPoint | null) => {
      setInstitutionalHoverDate((current) =>
        current === point?.date ? current : point?.date ?? null
      );
    };

    return (
      <div className="space-y-5">
        <div className="flex items-center justify-between border-b border-omi-border-subtle pb-2">
          <span className="text-xs font-semibold uppercase tracking-[0.16em] text-omi-text-muted">
            Date
          </span>
          <span className="text-sm font-bold text-omi-text">
            {formatDate(latestPoint.date)}
          </span>
        </div>

        <div className="grid grid-cols-3 gap-2 text-center text-xs">
          {[
            { label: t("stockDetail.dataPanel.investors.foreign"), value: displayLatestPoint.foreignCumulative },
            { label: t("stockDetail.dataPanel.investors.investmentTrust"), value: displayLatestPoint.investmentTrustCumulative },
            { label: t("stockDetail.dataPanel.investors.dealer"), value: displayLatestPoint.dealerCumulative },
          ].map((item) => (
            <div key={item.label} className="border border-omi-border-subtle px-3 py-3">
              <div className="font-semibold text-omi-text">{item.label}</div>
              <div className={`mt-2 text-base font-bold ${valueTone(item.value)}`}>
                {formatSignedLots(item.value)}{lotUnit}
              </div>
              <div className="mt-1 text-[11px] text-omi-text-muted">{t("stockDetail.dataPanel.recentThreeMonthsCumulative")}</div>
            </div>
          ))}
        </div>

        <div className="border border-omi-border-subtle bg-omi-surface px-4 py-3">
          <div className="mb-2 text-sm font-bold text-omi-text-strong">{t("stockDetail.dataPanel.institutionalTrend")}</div>
          <InstitutionalFlowChart
            points={recentPoints}
            title={t("stockDetail.dataPanel.investors.foreign")}
            netKey="foreignNet"
            cumulativeKey="foreignCumulative"
            activeDate={institutionalHoverDate}
            onHoverPointChange={handleInstitutionalHoverPoint}
          />
          <InstitutionalFlowChart
            points={recentPoints}
            title={t("stockDetail.dataPanel.investors.investmentTrust")}
            netKey="investmentTrustNet"
            cumulativeKey="investmentTrustCumulative"
            activeDate={institutionalHoverDate}
            onHoverPointChange={handleInstitutionalHoverPoint}
          />
          <InstitutionalFlowChart
            points={recentPoints}
            title={t("stockDetail.dataPanel.investors.dealer")}
            netKey="dealerNet"
            cumulativeKey="dealerCumulative"
            activeDate={institutionalHoverDate}
            showXAxisLabels
            onHoverPointChange={handleInstitutionalHoverPoint}
          />
        </div>

        <div className="border border-omi-border-subtle bg-omi-surface px-4 py-3">
          <div className="mb-3 flex items-center justify-between gap-4">
            <div>
              <div className="text-sm font-bold text-omi-text-strong">{t("stockDetail.dataPanel.institutionalHoldingRatio")}</div>
              <div className="mt-1 text-[11px] text-omi-text-muted">
                {t("stockDetail.dataPanel.actualHoldingRatio")}
              </div>
            </div>
            <div className="text-sm font-bold text-omi-text">
              {formatDate(ratioDate)}
            </div>
          </div>

          <div className="grid grid-cols-3 gap-2 text-center text-xs">
            {[
              {
                label: t("stockDetail.dataPanel.investors.foreign"),
                value: activeHoldingRatio?.foreign_investor_ratio ?? null,
              },
              {
                label: t("stockDetail.dataPanel.investors.investmentTrust"),
                value: activeHoldingRatio?.investment_trust_ratio ?? null,
              },
              {
                label: t("stockDetail.dataPanel.investors.dealer"),
                value: activeHoldingRatio?.dealer_ratio ?? null,
              },
            ].map((item) => (
              <div key={item.label} className="border border-omi-border-subtle px-3 py-3">
                <div className="font-semibold text-omi-text">{item.label}</div>
                <div className="mt-2 text-base font-bold text-omi-text-strong">
                  {formatRatioPct(item.value)}
                </div>
                <div className="mt-1 text-[11px] text-omi-text-muted">{t("stockDetail.dataPanel.holdingRatio")}</div>
              </div>
            ))}
          </div>
        </div>

        <div className="overflow-hidden border border-omi-border-subtle">
          <div className="border-b border-omi-border-subtle bg-omi-surface-subtle px-3 py-2 text-center text-sm font-bold text-omi-text">
            {t("stockDetail.dataPanel.institutionalDetailTitle")}
          </div>
          <div className="grid grid-cols-[0.9fr_1fr_1fr_1fr_1fr] border-b border-omi-border-subtle bg-omi-surface text-center text-xs font-semibold text-omi-text-muted">
            <div className="px-2 py-2">{t("stockDetail.dataPanel.columns.date")}</div>
            <div className="px-2 py-2">{t("stockDetail.dataPanel.columns.foreignLots")}</div>
            <div className="px-2 py-2">{t("stockDetail.dataPanel.columns.investmentTrustLots")}</div>
            <div className="px-2 py-2">{t("stockDetail.dataPanel.columns.dealerLots")}</div>
            <div className="px-2 py-2">{t("stockDetail.dataPanel.columns.totalLots")}</div>
          </div>
          {tableRows.map((row) => (
            <div
              key={row.date}
              className="grid grid-cols-[0.9fr_1fr_1fr_1fr_1fr] border-b border-omi-border-subtle text-center text-xs last:border-b-0"
            >
              <div className="px-2 py-2 text-omi-text">{formatMonthDay(row.date)}</div>
              <div className={`px-2 py-2 ${valueTone(row.foreignNet)}`}>
                {formatSignedLots(row.foreignNet)}
              </div>
              <div className={`px-2 py-2 ${valueTone(row.investmentTrustNet)}`}>
                {formatSignedLots(row.investmentTrustNet)}
              </div>
              <div className={`px-2 py-2 ${valueTone(row.dealerNet)}`}>
                {formatSignedLots(row.dealerNet)}
              </div>
              <div className={`px-2 py-2 ${valueTone(row.totalNet)}`}>
                {formatSignedLots(row.totalNet)}
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  function renderBranchTab() {
    if (!brokerBranchSummary || brokerBranchSummary.row_count === 0) {
      return <EmptyDataState message={t("stockDetail.dataPanel.empty.branch")} />;
    }

    const buyTotal = brokerBranchSummary.buy_top.reduce(
      (sum, row) => sum + (row.net_lots ?? 0),
      0
    );
    const sellTotal = brokerBranchSummary.sell_top.reduce(
      (sum, row) => sum + Math.abs(row.net_lots ?? 0),
      0
    );
    const compareRows = Array.from(
      {
        length: Math.max(
          brokerBranchSummary.buy_top.length,
          brokerBranchSummary.sell_top.length
        ),
      },
      (_, index) => ({
        buy: brokerBranchSummary.buy_top[index] ?? null,
        sell: brokerBranchSummary.sell_top[index] ?? null,
      })
    );
    const maxCompareValue = Math.max(
      1,
      ...compareRows.flatMap((row) => [
        Math.abs(row.buy?.net_lots ?? 0),
        Math.abs(row.sell?.net_lots ?? 0),
      ])
    );
    const detailRows =
      branchTableSide === "buy"
        ? brokerBranchSummary.buy_top
        : brokerBranchSummary.sell_top;
    const detailTotal =
      branchTableSide === "buy" ? buyTotal : sellTotal;
    const detailNetLabel = branchTableSide === "buy"
      ? t("stockDetail.dataPanel.columns.buyNetLots")
      : t("stockDetail.dataPanel.columns.sellNetLots");
    const detailNameLabel = branchTableSide === "buy"
      ? t("stockDetail.dataPanel.buyTop15")
      : t("stockDetail.dataPanel.sellTop15");
    const detailTotalLabel =
      branchTableSide === "buy"
        ? t("stockDetail.dataPanel.totalBuyTop15")
        : t("stockDetail.dataPanel.totalSellTop15");
    const detailTone =
      branchTableSide === "buy" ? "text-omi-market-up" : "text-omi-market-down";

    const branchDisplayName = (row: BrokerBranchTradeDailyRead | null) =>
      row?.branch_name || "-";
    const branchNetAbs = (row: BrokerBranchTradeDailyRead | null) =>
      Math.abs(row?.net_lots ?? 0);
    const branchBarWidth = (row: BrokerBranchTradeDailyRead | null) =>
      `${(branchNetAbs(row) / maxCompareValue) * 100}%`;
    const branchTradeDates = brokerBranchSummary.trade_dates ?? [];
    const branchDateRange =
      branchTradeDates.length > 1
        ? `${formatDate(branchTradeDates[branchTradeDates.length - 1])} - ${formatDate(
            branchTradeDates[0]
          )}`
        : formatDate(brokerBranchSummary.trade_date);
    const branchCoverageText =
      brokerBranchSummary.requested_days > 1
        ? brokerBranchSummary.is_partial
          ? t("stockDetail.dataPanel.branchCoveragePartial", {
              available: brokerBranchSummary.available_days,
              requested: brokerBranchSummary.requested_days,
            })
          : t("stockDetail.dataPanel.branchCoverageFull", {
              available: brokerBranchSummary.available_days,
            })
        : t("stockDetail.dataPanel.branchCoverageOneDay");

    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between gap-4">
          <div className="text-lg font-bold text-omi-text-strong">{t("stockDetail.dataPanel.branch")}</div>
          <div className="text-right text-[11px] text-omi-text-muted">
            <div>{t("stockDetail.dataPanel.branchDate", { date: branchDateRange })}</div>
            <a
              href={brokerBranchSummary.source_url}
              target="_blank"
              rel="noreferrer"
              className="font-semibold text-omi-text underline-offset-2 hover:underline"
            >
              {brokerBranchSummary.source_name ?? "nStock"}
            </a>
          </div>
        </div>

        <div className="flex items-center justify-center gap-3 text-xs">
          <span className="font-semibold text-omi-text-muted">{t("stockDetail.dataPanel.days")}</span>
          <div className="grid grid-cols-8 overflow-hidden border border-omi-control">
            {branchDayOptions.map((option) => {
              const disabled = option.days === null;
              const selected = option.days === branchDays;

              return (
                <button
                  key={option.label}
                  type="button"
                  onClick={() => {
                    if (option.days !== null) setBranchDays(option.days);
                  }}
                  disabled={disabled}
                  className={[
                    "h-7 w-12 border-r border-omi-control text-xs font-semibold last:border-r-0",
                    selected
                      ? "bg-omi-control-border text-omi-text-inverse"
                      : disabled
                        ? "bg-omi-surface-muted text-omi-text-subtle"
                        : "bg-omi-surface text-omi-text hover:bg-omi-surface-subtle",
                  ].join(" ")}
                >
                  {option.days === null ? t("stockDetail.dataPanel.more") : option.label}
                </button>
              );
            })}
          </div>
        </div>

        <div className="space-y-2">
          <div className="grid grid-cols-[1.2fr_1fr_1fr_1.2fr] text-xs font-semibold text-omi-text-muted">
            <div>{t("stockDetail.dataPanel.buyTop15")}</div>
            <div className="text-right">{t("stockDetail.dataPanel.columns.buyNetLots")}</div>
            <div className="text-left">{t("stockDetail.dataPanel.columns.sellNetLots")}</div>
            <div className="text-right">{t("stockDetail.dataPanel.sellTop15")}</div>
          </div>

          <div className="space-y-1">
            {compareRows.map((row, index) => (
              <div
                key={`branch-compare-${index}`}
                className="grid grid-cols-[1.2fr_1fr_1fr_1.2fr] items-center gap-2 text-xs"
              >
                <div className="min-w-0 truncate font-semibold text-omi-text">
                  {branchDisplayName(row.buy)}
                </div>
                <div className="relative h-6 overflow-hidden bg-omi-danger-soft text-right">
                  <div
                    className="absolute bottom-0 right-0 top-0 bg-omi-market-up-soft"
                    style={{ width: branchBarWidth(row.buy) }}
                  />
                  <span className="relative z-10 pr-1 font-semibold text-omi-market-up">
                    {formatLotUnits(branchNetAbs(row.buy))}
                  </span>
                </div>
                <div className="relative h-6 overflow-hidden bg-omi-success-soft text-left">
                  <div
                    className="absolute bottom-0 left-0 top-0 bg-omi-market-down-soft"
                    style={{ width: branchBarWidth(row.sell) }}
                  />
                  <span className="relative z-10 pl-1 font-semibold text-omi-market-down">
                    {formatLotUnits(branchNetAbs(row.sell))}
                  </span>
                </div>
                <div className="min-w-0 truncate text-right font-semibold text-omi-text">
                  {branchDisplayName(row.sell)}
                </div>
              </div>
            ))}
          </div>

          <div className="border-t border-omi-border-subtle pt-2">
            <div className="mb-1 flex items-center justify-between text-xs font-semibold text-omi-text">
              <span>{t("stockDetail.dataPanel.totalBuyTop15")}</span>
              <span>{t("stockDetail.dataPanel.totalSellTop15")}</span>
            </div>
            <div className="grid grid-cols-2 overflow-hidden text-xs">
              <div className="bg-omi-danger-soft px-1 py-1 text-left font-semibold text-omi-market-up">
                {formatLotUnits(buyTotal)}
              </div>
              <div className="bg-omi-success-soft px-1 py-1 text-right font-semibold text-omi-market-down">
                {formatLotUnits(sellTotal)}
              </div>
            </div>
          </div>
        </div>

        <div className="space-y-3 border-t border-omi-border-subtle pt-5">
          <div className="text-center text-sm font-bold text-omi-text-strong">
            {t("stockDetail.dataPanel.brokerTop15Title")}
          </div>

          <div className="flex items-center justify-center text-sm font-semibold">
            <div className="flex overflow-hidden border border-omi-control">
              {branchTableSideOptions.map((item) => (
                <button
                  key={item.key}
                  type="button"
                  onClick={() => setBranchTableSide(item.key as BranchTableSide)}
                  className={[
                    "h-8 w-12 border-r border-omi-control text-sm last:border-r-0",
                    branchTableSide === item.key
                      ? "bg-omi-control-border text-omi-text-inverse"
                      : "bg-omi-surface text-omi-text hover:bg-omi-surface-subtle",
                  ].join(" ")}
                >
                  {t(`stockDetail.dataPanel.branchSide.${item.key}`)}
                </button>
              ))}
            </div>
          </div>

          <div className="overflow-hidden border-t border-omi-border-subtle">
            <div
              className="grid grid-cols-[1.5fr_0.9fr_0.8fr_0.8fr_0.9fr_0.9fr] border-b border-omi-border-subtle text-xs font-semibold text-omi-text-muted"
            >
              <div className="px-1 py-2">{detailNameLabel}</div>
              <div className="px-1 py-2 text-right">{detailNetLabel}</div>
              <div className="px-1 py-2 text-right">{t("stockDetail.dataPanel.columns.buyLots")}</div>
              <div className="px-1 py-2 text-right">{t("stockDetail.dataPanel.columns.sellLots")}</div>
              <div className="px-1 py-2 text-right">{t("stockDetail.dataPanel.columns.buyAvgPrice")}</div>
              <div className="px-1 py-2 text-right">{t("stockDetail.dataPanel.columns.sellAvgPrice")}</div>
            </div>
            {detailRows.map((row) => (
              <div
                key={`${branchTableSide}-${row.branch_code}-${row.branch_name}`}
                className="grid grid-cols-[1.5fr_0.9fr_0.8fr_0.8fr_0.9fr_0.9fr] border-b border-omi-border-subtle text-sm last:border-b-0"
              >
                <div className="min-w-0 truncate px-1 py-2 font-semibold text-omi-text-strong">
                  {row.branch_name || "-"}
                </div>
                <div className={`px-1 py-2 text-right ${detailTone}`}>
                  {formatLotUnits(Math.abs(row.net_lots ?? 0))}
                </div>
                <div className="px-1 py-2 text-right text-omi-text-strong">
                  {formatLotUnits(row.buy_lots)}
                </div>
                <div className="px-1 py-2 text-right text-omi-text-strong">
                  {formatLotUnits(row.sell_lots)}
                </div>
                <div className="px-1 py-2 text-right text-omi-text-strong">
                  {formatPrice(row.buy_avg_price)}
                </div>
                <div className="px-1 py-2 text-right text-omi-text-strong">
                  {formatPrice(row.sell_avg_price)}
                </div>
              </div>
            ))}
            <div
              className="grid grid-cols-[1.5fr_0.9fr_0.8fr_0.8fr_0.9fr_0.9fr] border-t border-omi-border-subtle text-sm font-semibold"
            >
              <div className="px-1 py-2 text-omi-text-strong">{detailTotalLabel}</div>
              <div className={`px-1 py-2 text-right ${detailTone}`}>
                {formatLotUnits(detailTotal)}
              </div>
              <div />
              <div />
              <div />
              <div />
            </div>
          </div>

          <div className="text-right text-[11px] text-omi-text-muted">
            {branchCoverageText}{t("stockDetail.dataPanel.branchSnapshotNote")}
          </div>
        </div>
      </div>
    );
  }

  function renderRevenueTab() {
    return renderRevenueAnalyticsTab();
  }

  function renderRevenueAnalyticsTab() {
    const activeRows = revenueSeries;
    const latestRevenue = monthlyRevenueHistory[monthlyRevenueHistory.length - 1] ?? monthlyRevenue;

    if (!activeRows.length || !latestRevenue) {
      return <EmptyDataState message={t("stockDetail.dataPanel.empty.revenue")} />;
    }

    const latestYear = Number(latestRevenue.period.slice(0, 4));
    const revenueYearOptions = Array.from(
      new Set(
        monthlyRevenueHistory
          .map((row) => Number(row.period.slice(0, 4)))
          .filter((year) => Number.isFinite(year))
      )
    ).sort((left, right) => right - left);

    if (!revenueYearOptions.includes(latestYear)) {
      revenueYearOptions.unshift(latestYear);
    }

    const selectedRevenueYear =
      revenueYear !== null && revenueYearOptions.includes(revenueYear)
        ? revenueYear
        : latestYear;
    const monthlyRowsByMonth = new Map(
      monthlyRevenueHistory
        .filter((row) => Number(row.period.slice(0, 4)) === selectedRevenueYear)
        .map((row) => [Number(row.period.slice(5, 7)), row])
    );
    const latestRows = activeRows.slice().reverse().slice(0, 12);

    return (
      <div className="space-y-5">
        <div className="flex items-center justify-between border-b border-omi-border-subtle pb-2">
          <span className="text-xs font-semibold uppercase tracking-[0.16em] text-omi-text-muted">
            Revenue
          </span>
          <div className="flex overflow-hidden border border-omi-control text-sm font-semibold">
            {[
              { key: "monthly", label: t("stockDetail.dataPanel.views.monthly") },
              { key: "quarterly", label: t("stockDetail.dataPanel.views.quarterly") },
              { key: "yearly", label: t("stockDetail.dataPanel.views.yearly") },
            ].map((item) => (
              <button
                key={item.key}
                type="button"
                onClick={() => setRevenueView(item.key as RevenueView)}
                className={[
                  "h-8 w-12 border-r border-omi-control last:border-r-0",
                  revenueView === item.key
                    ? "bg-omi-control-muted text-omi-text-inverse"
                    : "bg-omi-surface text-omi-text hover:bg-omi-surface-subtle",
                ].join(" ")}
              >
                {item.label}
              </button>
            ))}
          </div>
        </div>

        <RevenueTrendChart points={activeRows} view={revenueView} />

        {revenueView === "monthly" ? (
          <div className="overflow-hidden border border-omi-border-subtle">
            <div className="grid grid-cols-[0.7fr_1fr_1fr_1fr_1fr_1fr] border-b border-omi-border-subtle bg-omi-surface-subtle text-center text-xs font-semibold text-omi-text-muted">
              <div className="px-2 py-1">
                <select
                  value={selectedRevenueYear}
                  onChange={(event) => setRevenueYear(Number(event.target.value))}
                  className="h-8 w-full bg-omi-surface px-2 text-center text-sm font-semibold text-omi-text outline outline-1 outline-slate-200"
                  aria-label={t("stockDetail.dataPanel.selectRevenueYear")}
                >
                  {revenueYearOptions.map((year) => (
                    <option key={year} value={year}>
                      {year}
                    </option>
                  ))}
                </select>
              </div>
              <div className="border-l border-omi-border-subtle px-2 py-2">{t("stockDetail.dataPanel.columns.revenueYi")}</div>
              <div className="border-l border-omi-border-subtle px-2 py-2">{t("stockDetail.dataPanel.columns.yoy")}</div>
              <div className="border-l border-omi-border-subtle px-2 py-2">{t("stockDetail.dataPanel.columns.cumulativeRevenueYi")}</div>
              <div className="border-l border-omi-border-subtle px-2 py-2">{t("stockDetail.dataPanel.columns.cumulativeYoy")}</div>
              <div className="border-l border-omi-border-subtle px-2 py-2">{t("stockDetail.dataPanel.columns.previousYearRevenueYi")}</div>
            </div>
            {Array.from({ length: 12 }, (_, index) => 12 - index).map((month) => {
              const row = monthlyRowsByMonth.get(month);

              return (
                <div
                  key={month}
                  className="grid grid-cols-[0.7fr_1fr_1fr_1fr_1fr_1fr] border-b border-omi-border-subtle text-center text-xs last:border-b-0"
                >
                  <div className="bg-omi-surface-subtle px-2 py-2 font-semibold text-omi-text">
                    {t("stockDetail.dataPanel.monthLabel", { month })}
                  </div>
                  <div className="border-l border-omi-border-subtle px-2 py-2 text-omi-text-strong">
                    {formatRevenueYiValue(toRevenueYi(row?.monthly_revenue))}
                  </div>
                  <div className={`border-l border-omi-border-subtle px-2 py-2 ${valueTone(row?.year_over_year_pct)}`}>
                    {formatPct(row?.year_over_year_pct)}
                  </div>
                  <div className="border-l border-omi-border-subtle px-2 py-2 text-omi-text-strong">
                    {formatRevenueYiValue(toRevenueYi(row?.cumulative_revenue))}
                  </div>
                  <div className={`border-l border-omi-border-subtle px-2 py-2 ${valueTone(row?.cumulative_year_over_year_pct)}`}>
                    {formatPct(row?.cumulative_year_over_year_pct)}
                  </div>
                  <div className="border-l border-omi-border-subtle px-2 py-2 text-omi-text-strong">
                    {formatRevenueYiValue(toRevenueYi(row?.previous_year_month_revenue))}
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="overflow-hidden border border-omi-border-subtle">
            <div className="grid grid-cols-[1fr_1fr_1fr_1fr_0.7fr] border-b border-omi-border-subtle bg-omi-surface-subtle text-center text-xs font-semibold text-omi-text-muted">
              <div className="px-2 py-2 text-left">{t("stockDetail.dataPanel.columns.period")}</div>
              <div className="border-l border-omi-border-subtle px-2 py-2">{t("stockDetail.dataPanel.columns.revenueYi")}</div>
              <div className="border-l border-omi-border-subtle px-2 py-2">{t("stockDetail.dataPanel.columns.yoy")}</div>
              <div className="border-l border-omi-border-subtle px-2 py-2">{t("stockDetail.dataPanel.columns.previousPeriodRevenueYi")}</div>
              <div className="border-l border-omi-border-subtle px-2 py-2">{t("stockDetail.dataPanel.columns.monthCount")}</div>
            </div>
            {latestRows.map((row) => (
              <div
                key={row.period}
                className="grid grid-cols-[1fr_1fr_1fr_1fr_0.7fr] border-b border-omi-border-subtle text-center text-xs last:border-b-0"
              >
                <div className="bg-omi-surface-subtle px-2 py-2 text-left font-semibold text-omi-text">
                  {row.label}
                </div>
                <div className="border-l border-omi-border-subtle px-2 py-2 text-omi-text-strong">
                  {formatRevenueYiValue(row.revenue)}
                </div>
                <div className={`border-l border-omi-border-subtle px-2 py-2 ${valueTone(row.growthPct)}`}>
                  {formatPct(row.growthPct)}
                </div>
                <div className="border-l border-omi-border-subtle px-2 py-2 text-omi-text-strong">
                  {formatRevenueYiValue(row.previousRevenue)}
                </div>
                <div className="border-l border-omi-border-subtle px-2 py-2 text-omi-text-muted">
                  {row.monthCount}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    );
  }

  function renderEarningsTab() {
    const activeRows = earningsSeries.length
      ? earningsSeries
      : financialMetric
        ? buildEarningsSeries([financialMetric], earningsView)
        : [];

    if (!activeRows.length) {
      return <EmptyDataState message={t("stockDetail.dataPanel.empty.earnings")} />;
    }

    const latestRows = activeRows.slice().reverse().slice(0, earningsView === "quarterly" ? 16 : 10);

    return (
      <div className="space-y-5">
        <div className="flex items-center justify-between border-b border-omi-border-subtle pb-2">
          <span className="text-xs font-semibold uppercase tracking-[0.16em] text-omi-text-muted">
            Earnings
          </span>
          <div className="flex overflow-hidden border border-omi-control text-sm font-semibold">
            {[
              { key: "quarterly", label: t("stockDetail.dataPanel.views.quarterly") },
              { key: "yearly", label: t("stockDetail.dataPanel.views.yearly") },
            ].map((item) => (
              <button
                key={item.key}
                type="button"
                onClick={() => setEarningsView(item.key as EarningsView)}
                className={[
                  "h-8 w-12 border-r border-omi-control last:border-r-0",
                  earningsView === item.key
                    ? "bg-omi-control-muted text-omi-text-inverse"
                    : "bg-omi-surface text-omi-text hover:bg-omi-surface-subtle",
                ].join(" ")}
              >
                {item.label}
              </button>
            ))}
          </div>
        </div>

        <EarningsTrendChart points={activeRows} view={earningsView} />

        <div className="overflow-hidden border border-omi-border-subtle">
          <div className="grid grid-cols-[1fr_1fr_1fr_1fr_1fr] border-b border-omi-border-subtle bg-omi-surface-subtle text-center text-xs font-semibold text-omi-text-muted">
            <div className="px-2 py-2 text-left">{t("stockDetail.dataPanel.columns.period")}</div>
            <div className="border-l border-omi-border-subtle px-2 py-2">{t("stockDetail.dataPanel.columns.epsNtd")}</div>
            <div className="border-l border-omi-border-subtle px-2 py-2">{t("stockDetail.dataPanel.columns.yoyGrowth")}</div>
            <div className="border-l border-omi-border-subtle px-2 py-2">ROE</div>
            <div className="border-l border-omi-border-subtle px-2 py-2">ROA</div>
          </div>
          {latestRows.map((row) => (
            <div
              key={row.period}
              className="grid grid-cols-[1fr_1fr_1fr_1fr_1fr] border-b border-omi-border-subtle text-center text-xs last:border-b-0"
            >
              <div className="bg-omi-surface-subtle px-2 py-2 text-left font-semibold text-omi-text">
                {row.label}
              </div>
              <div className="border-l border-omi-border-subtle px-2 py-2 text-omi-text-strong">
                {formatPrice(row.eps)}
              </div>
              <div className={`border-l border-omi-border-subtle px-2 py-2 ${valueTone(row.growthPct)}`}>
                {formatPct(row.growthPct)}
              </div>
              <div className={`border-l border-omi-border-subtle px-2 py-2 ${valueTone(row.roe)}`}>
                {formatRatioPct(row.roe)}
              </div>
              <div className={`border-l border-omi-border-subtle px-2 py-2 ${valueTone(row.roa)}`}>
                {formatRatioPct(row.roa)}
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  function renderActiveDataTab() {
    const loadingActiveTab = dataPanelLoading === activeDataTab;
    const hasRenderableData = activeDataTabHasRenderableData();

    if (activeDataTabHasStaleData()) {
      return <DataPanelLoadingState message={t("stockDetail.dataPanel.backfilling")} />;
    }

    if (loadingActiveTab && !hasRenderableData) {
      return <DataPanelLoadingState message={dataPanelMessage ?? t("stockDetail.dataPanel.backfilling")} />;
    }

    const content =
      activeDataTab === "institutional"
        ? renderInstitutionalTab()
        : activeDataTab === "branch"
          ? renderBranchTab()
          : activeDataTab === "revenue"
            ? renderRevenueTab()
            : activeDataTab === "earnings"
              ? renderEarningsTab()
              : renderChipTab();

    return (
      <div
        key={`${selectedStockId}:${activeDataTab}:${branchDays}`}
        className={[
          "omi-tab-panel relative",
          loadingActiveTab ? "omi-soft-refresh pt-3" : "",
        ]
          .filter(Boolean)
          .join(" ")}
      >
        {loadingActiveTab ? <DataPanelRefreshRail message={dataPanelMessage} /> : null}
        <div className={loadingActiveTab ? "opacity-85 transition-opacity duration-150" : ""}>
          {content}
        </div>
      </div>
    );
  }

  return renderActiveDataTab();
}
