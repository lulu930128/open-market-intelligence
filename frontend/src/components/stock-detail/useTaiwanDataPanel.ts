"use client";

import {
  minimumUsableFinancialRows,
  minimumUsableRevenueRows,
} from "@/components/stock-detail/StockDetailPanelConstants";
import {
  fetchOptional,
  formatBackfillOutcome,
  formatDate,
  formatPanelJobProgress,
  type DataPanelTab,
} from "@/components/stock-detail/StockDetailDataViews";
import { fetchJson, requestJson } from "@/lib/api";
import { getJobResultStatus, requestBackfillJob } from "@/lib/jobs";
import {
  getMarketCalendarStatusSnapshot,
  refreshMarketCalendarStatus,
  type MarketCalendarMarketStatus,
} from "@/lib/marketCalendarStatus";
import {
  getTaiwanDataPanelRefreshProfile,
  taiwanSelectionRefreshPath,
  type TaiwanRefreshProfile,
} from "@/lib/taiwanMarketRules";
import type { TranslationFunction } from "@/i18n";
import type {
  BrokerBranchTradeDailySummaryRead,
  FinancialMetricQuarterlyRead,
  InstitutionalHoldingRatioRead,
  InstitutionalTradeDailyRead,
  MarginTradingDailyRead,
  MonthlyRevenueRead,
  ShareholdingDistributionWeeklyRead,
  StockChipCoverageRead,
  StockMasterRead,
  TaiwanFinancialContractRead,
} from "@/types/market";
import { useEffect, useRef, useState } from "react";

const TAIWAN_DATASET_INSTITUTIONAL_TRADE = "institutional_trade_daily";
const TAIWAN_DATASET_MARGIN_TRADING = "margin_trading_daily";
const TAIWAN_DATASET_BROKER_BRANCH = "broker_branch_trade_daily";
const TAIWAN_DATASET_SHAREHOLDING = "shareholding_distribution_weekly";
const TAIWAN_DATASET_MONTHLY_REVENUE = "monthly_revenue";
const TAIWAN_DATASET_FINANCIAL_METRICS = "financial_metric_quarterly";
const institutionalLookbackDays = 100;
const institutionalHistoryLimit = 120;
const revenueHistoryLimit = 120;
const financialHistoryLimit = 40;

function dataPanelCacheKey(stockId: string, tab: DataPanelTab, branchDays = 1) {
  return tab === "branch" ? `${stockId}:${tab}:${branchDays}` : `${stockId}:${tab}`;
}

function normalizeIsoDate(value: string | null | undefined) {
  return value ? value.slice(0, 10) : null;
}

function isIsoDateOnOrAfter(
  value: string | null | undefined,
  expected: string | null | undefined
) {
  const normalizedValue = normalizeIsoDate(value);
  const normalizedExpected = normalizeIsoDate(expected);
  if (!normalizedExpected) return true;
  if (!normalizedValue) return false;
  return normalizedValue >= normalizedExpected;
}

function isDataKeyCurrent(
  value: string | null | undefined,
  expected: string | null | undefined
) {
  if (!value) return false;
  if (!expected) return true;
  return value >= expected;
}

function maxIsoDate(values: Array<string | null | undefined>) {
  let latest: string | null = null;
  for (const value of values) {
    const normalized = normalizeIsoDate(value);
    if (normalized && (!latest || normalized > latest)) latest = normalized;
  }
  return latest;
}

function expectedTaiwanDatasetDate(
  calendarStatus: MarketCalendarMarketStatus | null,
  datasetKey: string
) {
  return normalizeIsoDate(
    calendarStatus?.release_windows?.[datasetKey]?.expected_trade_date ?? null
  );
}

function expectedTaiwanDatasetKey(
  calendarStatus: MarketCalendarMarketStatus | null,
  datasetKey: string
) {
  const window = calendarStatus?.release_windows?.[datasetKey];
  return window?.expected_data_key ?? normalizeIsoDate(window?.expected_trade_date);
}

function taiwanCalendarStatusRefreshKey(
  calendarStatus: MarketCalendarMarketStatus | null
) {
  if (!calendarStatus) return "none";

  return [
    calendarStatus.date,
    expectedTaiwanDatasetDate(calendarStatus, TAIWAN_DATASET_INSTITUTIONAL_TRADE),
    expectedTaiwanDatasetDate(calendarStatus, TAIWAN_DATASET_MARGIN_TRADING),
    expectedTaiwanDatasetDate(calendarStatus, TAIWAN_DATASET_BROKER_BRANCH),
    expectedTaiwanDatasetKey(calendarStatus, TAIWAN_DATASET_SHAREHOLDING),
    expectedTaiwanDatasetKey(calendarStatus, TAIWAN_DATASET_MONTHLY_REVENUE),
    expectedTaiwanDatasetKey(calendarStatus, TAIWAN_DATASET_FINANCIAL_METRICS),
  ].join("|");
}

export function useTaiwanDataPanel({
  autoRefreshEnabled = true,
  enabled = true,
  includeFundamentals = true,
  isIndexProduct,
  onDailyPricesChanged,
  stockId,
  subresourceRefreshSeconds,
  t,
}: {
  autoRefreshEnabled?: boolean | null;
  enabled?: boolean;
  includeFundamentals?: boolean | null;
  isIndexProduct: boolean;
  onDailyPricesChanged?: () => void;
  stockId: string | null;
  subresourceRefreshSeconds: number;
  t: TranslationFunction;
}) {
  const [taiwanCalendarStatus, setTaiwanCalendarStatus] =
    useState<MarketCalendarMarketStatus | null>(() =>
      getMarketCalendarStatusSnapshot("tw")
    );
  const [institutional, setInstitutional] =
    useState<InstitutionalTradeDailyRead | null>(null);
  const [institutionalHistory, setInstitutionalHistory] =
    useState<InstitutionalTradeDailyRead[]>([]);
  const [institutionalHoldingRatio, setInstitutionalHoldingRatio] =
    useState<InstitutionalHoldingRatioRead | null>(null);
  const [margin, setMargin] = useState<MarginTradingDailyRead | null>(null);
  const [brokerBranchSummary, setBrokerBranchSummary] =
    useState<BrokerBranchTradeDailySummaryRead | null>(null);
  const [shareholding, setShareholding] =
    useState<ShareholdingDistributionWeeklyRead[]>([]);
  const [chipCoverage, setChipCoverage] = useState<StockChipCoverageRead | null>(null);
  const [monthlyRevenue, setMonthlyRevenue] = useState<MonthlyRevenueRead | null>(null);
  const [monthlyRevenueHistory, setMonthlyRevenueHistory] =
    useState<MonthlyRevenueRead[]>([]);
  const [financialMetric, setFinancialMetric] =
    useState<FinancialMetricQuarterlyRead | null>(null);
  const [financialMetricHistory, setFinancialMetricHistory] =
    useState<FinancialMetricQuarterlyRead[]>([]);
  const [financialContract, setFinancialContract] =
    useState<TaiwanFinancialContractRead | null>(null);
  const [stockInfo, setStockInfo] = useState<StockMasterRead | null>(null);
  const [activeDataTab, setActiveDataTab] = useState<DataPanelTab>("chips");
  const [dataPanelLoading, setDataPanelLoading] = useState<DataPanelTab | null>(null);
  const [dataPanelMessage, setDataPanelMessage] = useState<string | null>(null);
  const [branchDays, setBranchDays] = useState(1);
  const chartReloadNonce = 0;
  const activeStockIdRef = useRef(stockId);
  const activeDataTabRef = useRef(activeDataTab);
  const branchDaysRef = useRef(branchDays);
  const requestKeyRef = useRef<string | null>(null);
  const resolvedKeysRef = useRef(new Set<string>());
  const branchSummaryCacheRef = useRef(
    new Map<string, BrokerBranchTradeDailySummaryRead>()
  );
  const subresourceRefreshSecondsRef = useRef(subresourceRefreshSeconds);
  const onDailyPricesChangedRef = useRef(onDailyPricesChanged);
  const tRef = useRef(t);
  const resolvedStockInstrumentType =
    stockInfo?.stock_id === stockId
      ? stockInfo.instrument_type?.trim().toLowerCase() ?? "unknown"
      : "unknown";
  const resolvedIncludeFundamentals =
    includeFundamentals ??
    (resolvedStockInstrumentType !== "" &&
      resolvedStockInstrumentType !== "unknown" &&
      resolvedStockInstrumentType !== "etf");
  const resolvedAutoRefreshEnabled =
    autoRefreshEnabled ?? resolvedIncludeFundamentals;

  useEffect(() => {
    let cancelled = false;
    let refreshTimer: number | undefined;

    function setCalendarStatusIfChanged(
      nextStatus: MarketCalendarMarketStatus | null
    ) {
      if (cancelled) return;

      setTaiwanCalendarStatus((currentStatus) =>
        taiwanCalendarStatusRefreshKey(currentStatus) ===
        taiwanCalendarStatusRefreshKey(nextStatus)
          ? currentStatus
          : nextStatus
      );
    }

    async function loadTaiwanCalendarStatus() {
      const cachedStatus = getMarketCalendarStatusSnapshot("tw");
      if (!cancelled && cachedStatus) {
        setCalendarStatusIfChanged(cachedStatus);
      }

      try {
        const envelope = await refreshMarketCalendarStatus("tw");
        const nextStatus =
          envelope.markets.tw ?? getMarketCalendarStatusSnapshot("tw");
        setCalendarStatusIfChanged(nextStatus ?? null);
      } catch {
        if (!cancelled && !cachedStatus) {
          setCalendarStatusIfChanged(null);
        }
      } finally {
        if (!cancelled) {
          refreshTimer = window.setTimeout(loadTaiwanCalendarStatus, 60_000);
        }
      }
    }

    void loadTaiwanCalendarStatus();

    return () => {
      cancelled = true;
      if (refreshTimer !== undefined) {
        window.clearTimeout(refreshTimer);
      }
    };
  }, []);

  useEffect(() => {
    activeStockIdRef.current = stockId;
  }, [stockId]);

  useEffect(() => {
    activeDataTabRef.current = activeDataTab;
  }, [activeDataTab]);

  useEffect(() => {
    branchDaysRef.current = branchDays;
  }, [branchDays]);

  useEffect(() => {
    subresourceRefreshSecondsRef.current = subresourceRefreshSeconds;
  }, [subresourceRefreshSeconds]);

  useEffect(() => {
    onDailyPricesChangedRef.current = onDailyPricesChanged;
  }, [onDailyPricesChanged]);

  useEffect(() => {
    tRef.current = t;
  }, [t]);

  useEffect(() => {
    resolvedKeysRef.current.clear();
    branchSummaryCacheRef.current.clear();

    if (!enabled || !stockId || isIndexProduct) {
      const timer = window.setTimeout(() => {
        setInstitutional(null);
        setInstitutionalHistory([]);
        setInstitutionalHoldingRatio(null);
        setMargin(null);
        setBrokerBranchSummary(null);
        setShareholding([]);
        setChipCoverage(null);
        setMonthlyRevenue(null);
        setMonthlyRevenueHistory([]);
        setFinancialMetric(null);
        setFinancialMetricHistory([]);
        setFinancialContract(null);
        setStockInfo(null);
        setActiveDataTab("chips");
        setDataPanelLoading(null);
        setDataPanelMessage(null);
        setBranchDays(1);
      }, 0);
      return () => window.clearTimeout(timer);
    }

    let cancelled = false;
    const requestedStockId = stockId;
    const resetTimer = window.setTimeout(() => {
      if (cancelled) return;
      setInstitutional(null);
      setInstitutionalHistory([]);
      setInstitutionalHoldingRatio(null);
      setMargin(null);
      setBrokerBranchSummary(null);
      setShareholding([]);
      setChipCoverage(null);
      setMonthlyRevenue(null);
      setMonthlyRevenueHistory([]);
      setFinancialMetric(null);
      setFinancialMetricHistory([]);
      setFinancialContract(null);
      setStockInfo(null);
      setDataPanelLoading(null);
      setDataPanelMessage(null);
      setBranchDays(1);
    }, 0);

    async function loadBasicDetail() {
      try {
        const [institutionalData, marginData, initialRevenueData, stockData] =
          await Promise.all([
            fetchOptional<InstitutionalTradeDailyRead>(
              `/api/market/institutional/${requestedStockId}/latest`,
              { ensure_daily: false }
            ),
            fetchOptional<MarginTradingDailyRead>(
              `/api/market/margin/${requestedStockId}/latest`,
              { ensure_daily: false }
            ),
            includeFundamentals === true
              ? fetchOptional<MonthlyRevenueRead>(
                  `/api/market/revenue/${requestedStockId}/latest`,
                  { ensure_latest: false }
                )
              : Promise.resolve(null),
            fetchOptional<StockMasterRead>(`/api/stocks/${requestedStockId}`),
          ]);
        if (cancelled) return;

        const resolvedStockDataInstrumentType =
          stockData?.instrument_type?.trim().toLowerCase() ?? "unknown";
        const resolvedRevenueData =
          includeFundamentals === null &&
          resolvedStockDataInstrumentType !== "" &&
          resolvedStockDataInstrumentType !== "unknown" &&
          resolvedStockDataInstrumentType !== "etf"
            ? await fetchOptional<MonthlyRevenueRead>(
                `/api/market/revenue/${requestedStockId}/latest`,
                { ensure_latest: false }
              )
            : initialRevenueData;
        if (cancelled) return;

        setInstitutional(institutionalData);
        setMargin(marginData);
        setMonthlyRevenue(resolvedRevenueData);
        setStockInfo(stockData);
      } catch {
        if (cancelled) return;
        setInstitutional(null);
        setMargin(null);
        setMonthlyRevenue(null);
        setStockInfo(null);
      }
    }

    void loadBasicDetail();
    return () => {
      cancelled = true;
      window.clearTimeout(resetTimer);
    };
  }, [enabled, includeFundamentals, isIndexProduct, stockId]);

  function dataTabHasCurrentData(tab: DataPanelTab, targetStockId = stockId) {
    if (!targetStockId) return false;

    if (tab === "chips") {
      const expectedMarginDate = expectedTaiwanDatasetDate(
        taiwanCalendarStatus,
        TAIWAN_DATASET_MARGIN_TRADING
      );
      const latestMarginDate =
        chipCoverage?.stock_id === targetStockId
          ? chipCoverage.margin_latest_trade_date
          : margin?.stock_id === targetStockId
            ? margin.trade_date
            : null;
      if (expectedMarginDate && !isIsoDateOnOrAfter(latestMarginDate, expectedMarginDate)) {
        return false;
      }
      const expectedShareholdingDate = expectedTaiwanDatasetKey(
        taiwanCalendarStatus,
        TAIWAN_DATASET_SHAREHOLDING
      );
      const latestShareholdingDate =
        chipCoverage?.stock_id === targetStockId
          ? chipCoverage.shareholding_latest_date
          : maxIsoDate(
              shareholding
                .filter((row) => row.stock_id === targetStockId)
                .map((row) => row.data_date)
            );
      if (
        expectedShareholdingDate &&
        !isIsoDateOnOrAfter(latestShareholdingDate, expectedShareholdingDate)
      ) {
        return false;
      }
      return (
        resolvedKeysRef.current.has(dataPanelCacheKey(targetStockId, "chips")) &&
        (latestMarginDate !== null ||
          shareholding.some((row) => row.stock_id === targetStockId))
      );
    }

    if (tab === "institutional") {
      const latestInstitutionalDate = maxIsoDate(
        institutionalHistory
          .filter((row) => row.stock_id === targetStockId)
          .map((row) => row.trade_date)
      );
      const expectedInstitutionalDate = expectedTaiwanDatasetDate(
        taiwanCalendarStatus,
        TAIWAN_DATASET_INSTITUTIONAL_TRADE
      );
      return expectedInstitutionalDate
        ? isIsoDateOnOrAfter(latestInstitutionalDate, expectedInstitutionalDate)
        : latestInstitutionalDate !== null;
    }

    if (tab === "branch") {
      const expectedBranchDate = expectedTaiwanDatasetDate(
        taiwanCalendarStatus,
        TAIWAN_DATASET_BROKER_BRANCH
      );
      return (
        brokerBranchSummary !== null &&
        brokerBranchSummary.stock_id === targetStockId &&
        brokerBranchSummary.requested_days === branchDays &&
        isIsoDateOnOrAfter(brokerBranchSummary.trade_date, expectedBranchDate) &&
        resolvedKeysRef.current.has(
          dataPanelCacheKey(targetStockId, "branch", branchDays)
        )
      );
    }

    if (tab === "revenue") {
      const rows = monthlyRevenueHistory.filter(
        (row) => row.stock_id === targetStockId
      );
      const expectedPeriod = expectedTaiwanDatasetKey(
        taiwanCalendarStatus,
        TAIWAN_DATASET_MONTHLY_REVENUE
      );
      const latestPeriod = maxIsoDate(rows.map((row) => row.period));
      return (
        rows.length >= minimumUsableRevenueRows &&
        (!expectedPeriod || isIsoDateOnOrAfter(latestPeriod, expectedPeriod))
      );
    }

    const rows = financialMetricHistory.filter(
      (row) => row.stock_id === targetStockId
    );
    const expectedPeriod = expectedTaiwanDatasetKey(
      taiwanCalendarStatus,
      TAIWAN_DATASET_FINANCIAL_METRICS
    );
    const latestPeriod = rows.reduce<string | null>(
      (latest, row) => (!latest || row.period > latest ? row.period : latest),
      null
    );
    return (
      rows.length >= minimumUsableFinancialRows &&
      (!expectedPeriod || (latestPeriod !== null && latestPeriod >= expectedPeriod))
    );
  }

  async function refreshDataTab(
    tab: DataPanelTab,
    options?: {
      allowProviderRefresh?: boolean;
      skipProviderWhenCurrent?: boolean;
    }
  ) {
    if (!enabled || !stockId) return;
    if (!resolvedIncludeFundamentals && (tab === "revenue" || tab === "earnings")) return;

    const targetStockId = stockId;
    const targetBranchDays = tab === "branch" ? branchDays : 1;
    const requestKey = dataPanelCacheKey(targetStockId, tab, targetBranchDays);
    if (requestKeyRef.current === requestKey) return;

    requestKeyRef.current = requestKey;
    setDataPanelLoading(tab);
    setDataPanelMessage(null);
    const panelRefreshProfile = getTaiwanDataPanelRefreshProfile(tab);
    const panelRefreshLabel = t(`stockDetail.tabs.${tab}`);
    const allowProviderRefresh = options?.allowProviderRefresh === true;
    const skipProviderWhenCurrent = options?.skipProviderWhenCurrent === true;

    const runPanelRefresh = async (profile: TaiwanRefreshProfile, label: string) => {
      const job = await requestBackfillJob(
        taiwanSelectionRefreshPath(targetStockId),
        { method: "POST" },
        { profile, sleep_seconds: subresourceRefreshSecondsRef.current },
        {
          intervalMs: 1_500,
          timeoutMs: 600_000,
          onUpdate: (job) => {
            if (activeStockIdRef.current === targetStockId) {
              setDataPanelMessage(formatPanelJobProgress(label, job, t));
            }
          },
        }
      );
      if (getJobResultStatus(job) === "error") {
        throw new Error(formatBackfillOutcome(job, label, t));
      }
      if (profile === "basic" || profile === "full") {
        onDailyPricesChangedRef.current?.();
      }
      return job;
    };

    const loadCachedChips = async (statusNote?: string) => {
      const [coverageResult, shareholdingResult, marginResult] =
        await Promise.allSettled([
          fetchJson<StockChipCoverageRead>(
            `/api/market/chips/${targetStockId}/coverage`
          ),
          fetchJson<ShareholdingDistributionWeeklyRead[]>(
            `/api/market/shareholding/${targetStockId}/history`,
            { limit: 12_000, ensure_history: false }
          ),
          fetchJson<MarginTradingDailyRead[]>(
            `/api/market/margin/${targetStockId}/history`,
            { lookback_days: 365, limit: 365, ensure_history: false }
          ),
        ]);

      if (activeStockIdRef.current !== targetStockId) {
        return { hasShareholding: false, hasMargin: false };
      }

      const fallbackCoverage =
        chipCoverage?.stock_id === targetStockId ? chipCoverage : null;
      const fallbackShareholding = shareholding.filter(
        (row) => row.stock_id === targetStockId
      );
      const fallbackMargin = margin?.stock_id === targetStockId ? margin : null;
      const nextCoverage =
        coverageResult.status === "fulfilled" ? coverageResult.value : fallbackCoverage;
      const nextShareholding =
        shareholdingResult.status === "fulfilled"
          ? shareholdingResult.value
          : fallbackShareholding;
      const nextMarginRows =
        marginResult.status === "fulfilled" ? marginResult.value : [];
      const nextMargin =
        marginResult.status === "fulfilled"
          ? nextMarginRows[nextMarginRows.length - 1] ?? null
          : fallbackMargin;
      const fallbackShareholdingWeekCount = new Set(
        nextShareholding.map((row) => row.data_date)
      ).size;

      setChipCoverage(nextCoverage);
      setShareholding(nextShareholding);
      setMargin(nextMargin);

      const shareholdingLatest = nextCoverage?.shareholding_latest_date
        ? t("stockDetail.dataPanel.cache.latestDate", {
            date: formatDate(nextCoverage.shareholding_latest_date),
          })
        : "";
      const marginLatest = nextCoverage?.margin_latest_trade_date
        ? t("stockDetail.dataPanel.cache.latestDate", {
            date: formatDate(nextCoverage.margin_latest_trade_date),
          })
        : "";
      const marginRows = nextCoverage
        ? nextCoverage.margin_row_count
        : nextMarginRows.length || (nextMargin ? 1 : 0);
      const coverageText = t("stockDetail.dataPanel.cache.coverageSummary", {
        weekCount: nextCoverage?.shareholding_week_count ?? fallbackShareholdingWeekCount,
        shareholdingLatest,
        marginRows,
        marginLatest,
      });
      const failures = [
        coverageResult.status === "rejected"
          ? t("stockDetail.dataPanel.cache.status")
          : null,
        shareholdingResult.status === "rejected"
          ? t("stockDetail.dataPanel.cache.shareholding")
          : null,
        marginResult.status === "rejected"
          ? t("stockDetail.dataPanel.cache.marginShort")
          : null,
      ].filter(Boolean);
      const panelNotes = [
        statusNote,
        coverageText,
        failures.length
          ? t("stockDetail.dataPanel.cache.readPartialFailed", {
              items: failures.join(t("stockDetail.jobs.outcome.detailSeparator")),
            })
          : null,
      ].filter(Boolean);
      setDataPanelMessage(panelNotes.join("；"));

      return {
        hasShareholding: nextShareholding.length > 0,
        hasMargin: nextMargin !== null,
        latestShareholdingDate:
          nextCoverage?.shareholding_latest_date ??
          maxIsoDate(nextShareholding.map((row) => row.data_date)),
        latestMarginDate:
          nextCoverage?.margin_latest_trade_date ?? nextMargin?.trade_date ?? null,
      };
    };

    try {
      if (tab === "branch") {
        const cachedBranchSummary = await fetchOptional<BrokerBranchTradeDailySummaryRead>(
          `/api/market/broker-branches/${targetStockId}/daily`,
          { ensure_daily: false, days: targetBranchDays }
        );
        if (activeStockIdRef.current !== targetStockId) return;

        resolvedKeysRef.current.add(requestKey);
        if (cachedBranchSummary) {
          branchSummaryCacheRef.current.set(requestKey, cachedBranchSummary);
        }
        setBrokerBranchSummary(cachedBranchSummary);
        if (!allowProviderRefresh) {
          setDataPanelMessage(t("stockDetail.dataPanel.cache.localShown"));
          return;
        }
        if (
          skipProviderWhenCurrent &&
          cachedBranchSummary !== null &&
          isIsoDateOnOrAfter(
            cachedBranchSummary?.trade_date,
            expectedTaiwanDatasetDate(
              taiwanCalendarStatus,
              TAIWAN_DATASET_BROKER_BRANCH
            )
          )
        ) {
          setDataPanelMessage(t("stockDetail.dataPanel.cache.localShown"));
          return;
        }

        const refreshJob = await runPanelRefresh(panelRefreshProfile, panelRefreshLabel);
        const branchSummary = await fetchJson<BrokerBranchTradeDailySummaryRead>(
          `/api/market/broker-branches/${targetStockId}/daily`,
          { ensure_daily: false, days: targetBranchDays }
        );
        if (activeStockIdRef.current !== targetStockId) return;

        resolvedKeysRef.current.add(requestKey);
        branchSummaryCacheRef.current.set(requestKey, branchSummary);
        if (
          activeDataTabRef.current === "branch" &&
          dataPanelCacheKey(targetStockId, "branch", branchDaysRef.current) !== requestKey
        ) {
          return;
        }
        setBrokerBranchSummary(branchSummary);
        setDataPanelMessage(
          branchSummary.trade_date
            ? t("stockDetail.dataPanel.branchLoadedThrough", {
                outcome: formatBackfillOutcome(refreshJob, panelRefreshLabel, t),
                date: formatDate(branchSummary.trade_date),
              })
            : t("stockDetail.dataPanel.empty.branch")
        );
        return;
      }

      if (tab === "chips") {
        const initialCache = await loadCachedChips(
          t("stockDetail.dataPanel.cache.localShown")
        );
        let hasBackfillIssue = false;
        if (initialCache.hasShareholding || initialCache.hasMargin) {
          resolvedKeysRef.current.add(requestKey);
        }
        if (!allowProviderRefresh) {
          resolvedKeysRef.current.add(requestKey);
          return;
        }
        if (
          skipProviderWhenCurrent &&
          isDataKeyCurrent(
            initialCache.latestShareholdingDate,
            expectedTaiwanDatasetKey(
              taiwanCalendarStatus,
              TAIWAN_DATASET_SHAREHOLDING
            )
          ) &&
          isDataKeyCurrent(
            initialCache.latestMarginDate,
            expectedTaiwanDatasetDate(
              taiwanCalendarStatus,
              TAIWAN_DATASET_MARGIN_TRADING
            )
          )
        ) {
          resolvedKeysRef.current.add(requestKey);
          return;
        }

        try {
          const refreshJob = await runPanelRefresh(panelRefreshProfile, panelRefreshLabel);
          if (getJobResultStatus(refreshJob) === "partial_success") {
            hasBackfillIssue = true;
          }
        } catch {
          hasBackfillIssue = true;
        }

        const finalCache = await loadCachedChips(
          hasBackfillIssue
            ? t("stockDetail.dataPanel.cache.partialBackfill")
            : t("stockDetail.dataPanel.cache.chipsReloaded")
        );
        if (activeStockIdRef.current !== targetStockId) return;
        if (finalCache.hasShareholding || finalCache.hasMargin) {
          resolvedKeysRef.current.add(requestKey);
        }
        return;
      }

      if (tab === "institutional") {
        if (!allowProviderRefresh) {
          const [cachedRowsResult, holdingRatioResult] = await Promise.allSettled([
            fetchJson<InstitutionalTradeDailyRead[]>(
              `/api/market/institutional/${targetStockId}/history`,
              {
                lookback_days: institutionalLookbackDays,
                limit: institutionalHistoryLimit,
                ensure_history: false,
              }
            ),
            fetchJson<InstitutionalHoldingRatioRead>(
              `/api/market/institutional/${targetStockId}/holding-ratios`
            ),
          ]);
          if (activeStockIdRef.current !== targetStockId) return;

          if (holdingRatioResult.status === "fulfilled") {
            setInstitutionalHoldingRatio(holdingRatioResult.value);
          } else {
            setInstitutionalHoldingRatio(null);
          }
          if (cachedRowsResult.status === "rejected") {
            throw cachedRowsResult.reason;
          }

          const cachedRows = cachedRowsResult.value;
          resolvedKeysRef.current.add(requestKey);
          setInstitutional(cachedRows[cachedRows.length - 1] ?? null);
          setInstitutionalHistory(cachedRows);
          setDataPanelMessage(
            holdingRatioResult.status === "fulfilled"
              ? t("stockDetail.dataPanel.cache.localShown")
              : t("stockDetail.dataPanel.holdingRatioUnavailable")
          );
          return;
        }

        const [cachedRowsResult, cachedHoldingRatioResult] = await Promise.allSettled([
          fetchJson<InstitutionalTradeDailyRead[]>(
            `/api/market/institutional/${targetStockId}/history`,
            {
              lookback_days: institutionalLookbackDays,
              limit: institutionalHistoryLimit,
              ensure_history: false,
            }
          ),
          fetchJson<InstitutionalHoldingRatioRead>(
            `/api/market/institutional/${targetStockId}/holding-ratios`
          ),
        ]);
        if (activeStockIdRef.current !== targetStockId) return;

        if (cachedHoldingRatioResult.status === "fulfilled") {
          setInstitutionalHoldingRatio(cachedHoldingRatioResult.value);
        } else {
          setInstitutionalHoldingRatio(null);
        }
        if (cachedRowsResult.status === "rejected") {
          throw cachedRowsResult.reason;
        }

        const cachedRows = cachedRowsResult.value;
        resolvedKeysRef.current.add(requestKey);
        setInstitutional(cachedRows[cachedRows.length - 1] ?? null);
        setInstitutionalHistory(cachedRows);
        if (
          skipProviderWhenCurrent &&
          isDataKeyCurrent(
            maxIsoDate(cachedRows.map((row) => row.trade_date)),
            expectedTaiwanDatasetDate(
              taiwanCalendarStatus,
              TAIWAN_DATASET_INSTITUTIONAL_TRADE
            )
          )
        ) {
          setDataPanelMessage(
            cachedHoldingRatioResult.status === "fulfilled"
              ? t("stockDetail.dataPanel.cache.localShown")
              : t("stockDetail.dataPanel.holdingRatioUnavailable")
          );
          return;
        }

        const refreshJob = await runPanelRefresh(panelRefreshProfile, panelRefreshLabel);
        const [rowsResult, holdingRatioResult] = await Promise.allSettled([
          fetchJson<InstitutionalTradeDailyRead[]>(
            `/api/market/institutional/${targetStockId}/history`,
            {
              lookback_days: institutionalLookbackDays,
              limit: institutionalHistoryLimit,
              ensure_history: false,
            }
          ),
          requestJson<InstitutionalHoldingRatioRead>(
            `/api/market/institutional/${targetStockId}/holding-ratios/refresh`,
            { method: "POST" }
          ),
        ]);
        if (activeStockIdRef.current !== targetStockId) return;

        if (holdingRatioResult.status === "fulfilled") {
          setInstitutionalHoldingRatio(holdingRatioResult.value);
        }
        if (rowsResult.status === "rejected") {
          throw rowsResult.reason;
        }

        const rows = rowsResult.value;
        resolvedKeysRef.current.add(requestKey);
        setInstitutional(rows[rows.length - 1] ?? null);
        setInstitutionalHistory(rows);
        const refreshOutcome = formatBackfillOutcome(refreshJob, panelRefreshLabel, t);
        setDataPanelMessage(
          holdingRatioResult.status === "fulfilled"
            ? refreshOutcome
            : `${refreshOutcome}；${t("stockDetail.dataPanel.holdingRatioUnavailable")}`
        );
        return;
      }

      if (tab === "revenue") {
        const cachedRows = await fetchJson<MonthlyRevenueRead[]>(
          `/api/market/revenue/${targetStockId}/history`,
          { limit: revenueHistoryLimit, ensure_history: false }
        );
        if (activeStockIdRef.current !== targetStockId) return;

        resolvedKeysRef.current.add(requestKey);
        setMonthlyRevenue(cachedRows[cachedRows.length - 1] ?? null);
        setMonthlyRevenueHistory(cachedRows);
        if (!allowProviderRefresh) {
          setDataPanelMessage(t("stockDetail.dataPanel.cache.localShown"));
          return;
        }
        if (
          skipProviderWhenCurrent &&
          isDataKeyCurrent(
            maxIsoDate(cachedRows.map((row) => row.period)),
            expectedTaiwanDatasetKey(
              taiwanCalendarStatus,
              TAIWAN_DATASET_MONTHLY_REVENUE
            )
          )
        ) {
          setDataPanelMessage(t("stockDetail.dataPanel.cache.localShown"));
          return;
        }

        const refreshJob = await runPanelRefresh(panelRefreshProfile, panelRefreshLabel);
        const rows = await fetchJson<MonthlyRevenueRead[]>(
          `/api/market/revenue/${targetStockId}/history`,
          { limit: revenueHistoryLimit, ensure_history: false }
        );
        if (activeStockIdRef.current !== targetStockId) return;

        resolvedKeysRef.current.add(requestKey);
        setMonthlyRevenue(rows[rows.length - 1] ?? null);
        setMonthlyRevenueHistory(rows);
        setDataPanelMessage(formatBackfillOutcome(refreshJob, panelRefreshLabel, t));
        return;
      }

      const [cachedRows, cachedContract] = await Promise.all([
        fetchJson<FinancialMetricQuarterlyRead[]>(
          `/api/market/financials/${targetStockId}/history`,
          { limit: financialHistoryLimit, ensure_history: false }
        ),
        fetchOptional<TaiwanFinancialContractRead>(
          `/api/market/financials/${targetStockId}/contract`,
          {
            mode: "current_comparable",
            financial_limit: 8,
            revenue_limit: 24,
          }
        ),
      ]);
      if (activeStockIdRef.current !== targetStockId) return;

      resolvedKeysRef.current.add(requestKey);
      setFinancialMetric(cachedRows[cachedRows.length - 1] ?? null);
      setFinancialMetricHistory(cachedRows);
      setFinancialContract(cachedContract);
      if (!allowProviderRefresh) {
        setDataPanelMessage(t("stockDetail.dataPanel.cache.localShown"));
        return;
      }
      const latestCachedFinancialPeriod = cachedRows.reduce<string | null>(
        (latest, row) => (!latest || row.period > latest ? row.period : latest),
        null
      );
      const expectedFinancialPeriod = expectedTaiwanDatasetKey(
        taiwanCalendarStatus,
        TAIWAN_DATASET_FINANCIAL_METRICS
      );
      if (
        skipProviderWhenCurrent &&
        isDataKeyCurrent(
          latestCachedFinancialPeriod,
          expectedFinancialPeriod
        )
      ) {
        setDataPanelMessage(t("stockDetail.dataPanel.cache.localShown"));
        return;
      }

      const refreshJob = await runPanelRefresh(panelRefreshProfile, panelRefreshLabel);
      const [rows, refreshedContract] = await Promise.all([
        fetchJson<FinancialMetricQuarterlyRead[]>(
          `/api/market/financials/${targetStockId}/history`,
          { limit: financialHistoryLimit, ensure_history: false }
        ),
        fetchOptional<TaiwanFinancialContractRead>(
          `/api/market/financials/${targetStockId}/contract`,
          {
            mode: "current_comparable",
            financial_limit: 8,
            revenue_limit: 24,
          }
        ),
      ]);
      if (activeStockIdRef.current !== targetStockId) return;

      resolvedKeysRef.current.add(requestKey);
      setFinancialMetric(rows[rows.length - 1] ?? null);
      setFinancialMetricHistory(rows);
      setFinancialContract(refreshedContract);
      setDataPanelMessage(formatBackfillOutcome(refreshJob, panelRefreshLabel, t));
    } catch {
      if (activeStockIdRef.current === targetStockId) {
        setDataPanelMessage(t("stockDetail.dataPanel.backfillFailedRetry"));
      }
    } finally {
      if (requestKeyRef.current === requestKey) {
        requestKeyRef.current = null;
        setDataPanelLoading(null);
      }
    }
  }

  useEffect(() => {
    if (!resolvedAutoRefreshEnabled || !enabled || !stockId || isIndexProduct) return;

    const requestKey = dataPanelCacheKey(stockId, activeDataTab, branchDays);
    const cachedBranchSummary =
      activeDataTab === "branch"
        ? branchSummaryCacheRef.current.get(requestKey) ?? null
        : null;
    const cachedBranchSummaryIsCurrent =
      cachedBranchSummary !== null &&
      cachedBranchSummary.stock_id === stockId &&
      cachedBranchSummary.requested_days === branchDays &&
      isIsoDateOnOrAfter(
        cachedBranchSummary.trade_date,
        expectedTaiwanDatasetDate(
          taiwanCalendarStatus,
          TAIWAN_DATASET_BROKER_BRANCH
        )
      );
    const hasCachedResult = resolvedKeysRef.current.has(requestKey);
    const hasCurrentData = dataTabHasCurrentData(activeDataTab);

    if (cachedBranchSummary && cachedBranchSummaryIsCurrent) {
      const timer = window.setTimeout(() => {
        if (requestKeyRef.current === requestKey) return;
        setBrokerBranchSummary(cachedBranchSummary);
        setDataPanelLoading((current) =>
          current === activeDataTab ? null : current
        );
        setDataPanelMessage(tRef.current("stockDetail.dataPanel.cache.cachedData"));
      }, 0);
      return () => window.clearTimeout(timer);
    }

    if (hasCurrentData) {
      const timer = window.setTimeout(() => {
        if (requestKeyRef.current === requestKey) return;
        setDataPanelLoading((current) =>
          current === activeDataTab ? null : current
        );
        setDataPanelMessage(
          hasCachedResult
            ? tRef.current("stockDetail.dataPanel.cache.cachedData")
            : null
        );
      }, 0);
      return () => window.clearTimeout(timer);
    }

    const timer = window.setTimeout(() => {
      void refreshDataTab(activeDataTab, {
        allowProviderRefresh: true,
        skipProviderWhenCurrent: true,
      });
    }, 0);
    return () => window.clearTimeout(timer);
    // refreshDataTab intentionally captures the current data snapshot for cache validation.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    activeDataTab,
    resolvedAutoRefreshEnabled,
    branchDays,
    enabled,
    isIndexProduct,
    stockId,
    taiwanCalendarStatus,
  ]);

  return {
    actions: {
      refreshDataTab: (tab: DataPanelTab) =>
        refreshDataTab(tab, { allowProviderRefresh: true }),
      selectDataTab: setActiveDataTab,
      setBranchDays,
      setStockInfo,
    },
    state: {
      activeDataTab,
      branchDays,
      brokerBranchSummary,
      chartReloadNonce,
      chipCoverage,
      dataPanelLoading,
      dataPanelMessage,
      financialMetric,
      financialMetricHistory,
      financialContract,
      institutional,
      institutionalHoldingRatio,
      institutionalHistory,
      margin,
      monthlyRevenue,
      monthlyRevenueHistory,
      shareholding,
      stockInfo,
    },
  };
}
