import {
  buildEarningsSeries,
  buildRevenueSeries,
  shareholdingLevelRanges,
} from "@/components/stock-detail/StockDetailDataViews";
import type {
  InstitutionalSeriesPoint,
  ShareholdingSeriesPoint,
} from "@/components/stock-detail/StockDetailDataViews";
import type {
  InstitutionalTradeDailyRead,
  MarginTradingDailyRead,
  ShareholdingDistributionWeeklyRead,
  StockIndicatorPoint,
} from "@/types/market";

export { buildEarningsSeries, buildRevenueSeries };

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
