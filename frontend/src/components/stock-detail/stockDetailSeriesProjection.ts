import {
  formatPeriodLabel,
  toRevenueYi,
} from "@/components/stock-detail/stockDetailFormatters";
import {
  shareholdingLevelRanges,
  type EarningsSeriesPoint,
  type EarningsView,
  type InstitutionalSeriesPoint,
  type RevenueSeriesPoint,
  type RevenueView,
  type ShareholdingSeriesPoint,
} from "@/components/stock-detail/stockDetailTypes";
import type {
  FinancialMetricQuarterlyRead,
  InstitutionalTradeDailyRead,
  MarginTradingDailyRead,
  MonthlyRevenueRead,
  ShareholdingDistributionWeeklyRead,
  StockIndicatorPoint,
} from "@/types/market";

export type ShareholdingSeriesInput = {
  indicatorData: StockIndicatorPoint[];
  largeHolderLots: number;
  shareholding: ShareholdingDistributionWeeklyRead[];
  smallHolderLots: number;
};

export function buildShareholdingSeries({
  indicatorData,
  largeHolderLots,
  shareholding,
  smallHolderLots,
}: ShareholdingSeriesInput): ShareholdingSeriesPoint[] {
  const closeByDate = new Map(
    indicatorData
      .filter((row) => row.time && row.close !== null && row.close !== undefined)
      .map((row) => [row.time.slice(0, 10), row.close])
  );
  const groups = new Map<string, ShareholdingDistributionWeeklyRead[]>();

  shareholding.forEach((row) => {
    groups.set(row.data_date, [...(groups.get(row.data_date) ?? []), row]);
  });

  const rows = Array.from(groups.entries())
    .sort(([leftDate], [rightDate]) => leftDate.localeCompare(rightDate))
    .map(([dataDate, groupRows]) => {
      const largeRows = groupRows.filter((row) => {
        const range = shareholdingLevelRanges[row.holding_level_order ?? -1];
        return range ? range.minLots >= largeHolderLots : false;
      });
      const smallRows = groupRows.filter((row) => {
        const range = shareholdingLevelRanges[row.holding_level_order ?? -1];
        return range?.maxLots !== null && range?.maxLots !== undefined
          ? range.maxLots <= smallHolderLots
          : false;
      });
      const largeRatio = largeRows.reduce(
        (total, row) => total + (row.share_ratio ?? 0),
        0
      );
      const smallRatio = smallRows.reduce(
        (total, row) => total + (row.share_ratio ?? 0),
        0
      );
      const largeHolders = largeRows.reduce(
        (total, row) => total + (row.holder_count ?? 0),
        0
      );

      return {
        date: dataDate,
        largeRatio: largeRows.length ? largeRatio : null,
        largeRatioChange: null,
        largeHolders: largeRows.length ? largeHolders : null,
        smallRatio: smallRows.length ? smallRatio : null,
        close: closeByDate.get(dataDate.slice(0, 10)) ?? null,
      };
    });

  return rows.map((row, index) => {
    const previous = rows[index - 1];
    const largeRatioChange =
      previous?.largeRatio !== null &&
      previous?.largeRatio !== undefined &&
      row.largeRatio !== null
        ? row.largeRatio - previous.largeRatio
        : null;

    return {
      ...row,
      largeRatioChange,
    };
  });
}

export function buildInstitutionalSeries(
  history: InstitutionalTradeDailyRead[]
): InstitutionalSeriesPoint[] {
  return history
    .slice()
    .sort((leftRow, rightRow) =>
      leftRow.trade_date.localeCompare(rightRow.trade_date)
    )
    .reduce<{
      rows: InstitutionalSeriesPoint[];
      foreignCumulative: number;
      investmentTrustCumulative: number;
      dealerCumulative: number;
      totalCumulative: number;
    }>(
      (accumulator, row) => {
        const foreignNet = row.foreign_investor_net;
        const investmentTrustNet = row.investment_trust_net;
        const dealerNet = row.dealer_net;
        const totalNet = row.total_institutional_net;
        const nextForeignCumulative =
          accumulator.foreignCumulative + (foreignNet ?? 0);
        const nextInvestmentTrustCumulative =
          accumulator.investmentTrustCumulative + (investmentTrustNet ?? 0);
        const nextDealerCumulative =
          accumulator.dealerCumulative + (dealerNet ?? 0);
        const nextTotalCumulative = accumulator.totalCumulative + (totalNet ?? 0);

        return {
          rows: [
            ...accumulator.rows,
            {
              date: row.trade_date,
              foreignNet,
              investmentTrustNet,
              dealerNet,
              totalNet,
              foreignCumulative: nextForeignCumulative,
              investmentTrustCumulative: nextInvestmentTrustCumulative,
              dealerCumulative: nextDealerCumulative,
              totalCumulative: nextTotalCumulative,
            },
          ],
          foreignCumulative: nextForeignCumulative,
          investmentTrustCumulative: nextInvestmentTrustCumulative,
          dealerCumulative: nextDealerCumulative,
          totalCumulative: nextTotalCumulative,
        };
      },
      {
        rows: [],
        foreignCumulative: 0,
        investmentTrustCumulative: 0,
        dealerCumulative: 0,
        totalCumulative: 0,
      }
    ).rows;
}

export type ChipDateGroup = {
  tradeDate: string;
  institutional: InstitutionalTradeDailyRead | null;
  margin: MarginTradingDailyRead | null;
};

export function buildChipDateGroups(
  institutional: InstitutionalTradeDailyRead | null,
  margin: MarginTradingDailyRead | null
): ChipDateGroup[] {
  const groups = new Map<string, ChipDateGroup>();

  if (institutional?.trade_date) {
    groups.set(institutional.trade_date, {
      tradeDate: institutional.trade_date,
      institutional,
      margin: null,
    });
  }

  if (margin?.trade_date) {
    const current = groups.get(margin.trade_date);

    groups.set(margin.trade_date, {
      tradeDate: margin.trade_date,
      institutional: current?.institutional ?? null,
      margin,
    });
  }

  return Array.from(groups.values()).sort((left, right) =>
    right.tradeDate.localeCompare(left.tradeDate)
  );
}

export function quarterFromMonth(month: number) {
  return Math.floor((month - 1) / 3) + 1;
}

export function revenueGrowth(current: number | null, previous: number | null) {
  if (
    current === null ||
    previous === null ||
    previous === 0 ||
    Number.isNaN(current) ||
    Number.isNaN(previous)
  ) {
    return null;
  }

  return ((current - previous) / previous) * 100;
}

export function buildRevenueSeries(rows: MonthlyRevenueRead[], view: RevenueView) {
  const sortedRows = rows
    .slice()
    .sort((a, b) => a.period.localeCompare(b.period));

  if (view === "monthly") {
    return sortedRows.map<RevenueSeriesPoint>((row) => ({
      period: row.period,
      label: formatPeriodLabel(row.period),
      year: Number(row.period.slice(0, 4)),
      revenue: toRevenueYi(row.monthly_revenue),
      previousRevenue: toRevenueYi(row.previous_year_month_revenue),
      growthPct: row.year_over_year_pct,
      cumulativeRevenue: toRevenueYi(row.cumulative_revenue),
      cumulativeGrowthPct: row.cumulative_year_over_year_pct,
      monthCount: 1,
    }));
  }

  const groups = new Map<
    string,
    {
      year: number;
      quarter: number | null;
      revenue: number;
      previousRevenue: number;
      monthCount: number;
      lastPeriod: string;
    }
  >();

  sortedRows.forEach((row) => {
    const year = Number(row.period.slice(0, 4));
    const month = Number(row.period.slice(5, 7));
    const quarter = quarterFromMonth(month);
    const key = view === "quarterly" ? `${year}-Q${quarter}` : String(year);
    const current = groups.get(key) ?? {
      year,
      quarter: view === "quarterly" ? quarter : null,
      revenue: 0,
      previousRevenue: 0,
      monthCount: 0,
      lastPeriod: row.period,
    };

    current.revenue += toRevenueYi(row.monthly_revenue) ?? 0;
    current.previousRevenue += toRevenueYi(row.previous_year_month_revenue) ?? 0;
    current.monthCount += row.monthly_revenue === null || row.monthly_revenue === undefined ? 0 : 1;
    current.lastPeriod = row.period;
    groups.set(key, current);
  });

  return Array.from(groups.entries()).map<RevenueSeriesPoint>(([key, group]) => {
    const previousRevenue = group.previousRevenue || null;
    const revenue = group.monthCount ? group.revenue : null;

    return {
      period: key,
      label: key,
      year: group.year,
      revenue,
      previousRevenue,
      growthPct: revenueGrowth(revenue, previousRevenue),
      cumulativeRevenue: null,
      cumulativeGrowthPct: null,
      monthCount: group.monthCount,
    };
  });
}

export function buildEarningsSeries(rows: FinancialMetricQuarterlyRead[], view: EarningsView) {
  const sortedRows = rows
    .slice()
    .sort((a, b) => a.fiscal_year - b.fiscal_year || a.quarter - b.quarter);

  if (view === "quarterly") {
    const byPeriod = new Map(sortedRows.map((row) => [row.period, row]));

    return sortedRows.map<EarningsSeriesPoint>((row) => {
      const previous = byPeriod.get(`${row.fiscal_year - 1}Q${row.quarter}`);
      const periodScope = row.period_scope ?? (row.quarter === 4 ? "annual" : "ytd");
      const monthsCovered = row.months_covered ?? row.quarter * 3;
      const comparable =
        row.normalization_status === "normalized" &&
        previous?.normalization_status === "normalized";

      return {
        period: row.period,
        label:
          periodScope === "annual"
            ? `${row.period} · FY`
            : `${row.period} · ${monthsCovered}M YTD`,
        fiscalYear: row.fiscal_year,
        quarter: row.quarter,
        eps: row.single_quarter_eps ?? row.raw_eps ?? row.eps,
        previousEps: comparable
          ? previous?.single_quarter_eps ?? previous?.raw_eps ?? previous?.eps ?? null
          : null,
        growthPct: comparable
          ? revenueGrowth(
              row.single_quarter_eps ?? row.raw_eps ?? row.eps,
              previous?.single_quarter_eps ?? previous?.raw_eps ?? previous?.eps ?? null
            )
          : null,
        roe: row.normalization_status === "normalized" ? row.roe : null,
        roa: row.normalization_status === "normalized" ? row.roa : null,
        periodCount: 1,
      };
    });
  }

  const rowsByYear = new Map<number, FinancialMetricQuarterlyRead[]>();

  sortedRows.forEach((row) => {
    const list = rowsByYear.get(row.fiscal_year) ?? [];
    list.push(row);
    rowsByYear.set(row.fiscal_year, list);
  });

  return Array.from(rowsByYear.entries()).map<EarningsSeriesPoint>(([year, yearRows]) => {
    const selectedRow = yearRows.find((row) => row.quarter === 4) ?? yearRows[yearRows.length - 1];
    const periodScope =
      selectedRow?.period_scope ?? (selectedRow?.quarter === 4 ? "annual" : "ytd");
    const monthsCovered =
      selectedRow?.months_covered ?? (selectedRow ? selectedRow.quarter * 3 : null);
    const previousRow = (rowsByYear.get(year - 1) ?? []).find(
      (row) => row.quarter === selectedRow?.quarter
    );
    const comparable =
      selectedRow?.normalization_status === "normalized" &&
      previousRow?.normalization_status === "normalized";
    const eps = selectedRow?.raw_eps ?? selectedRow?.eps ?? null;
    const previousEps = comparable
      ? previousRow?.raw_eps ?? previousRow?.eps ?? null
      : null;

    return {
      period: String(year),
      label:
        periodScope === "annual"
          ? String(year)
          : `${year} · ${monthsCovered ?? "?"}M YTD`,
      fiscalYear: year,
      quarter: null,
      eps,
      previousEps,
      growthPct: comparable ? revenueGrowth(eps, previousEps) : null,
      roe: selectedRow?.normalization_status === "normalized" ? selectedRow.roe : null,
      roa: selectedRow?.normalization_status === "normalized" ? selectedRow.roa : null,
      periodCount: selectedRow ? 1 : 0,
    };
  });
}
