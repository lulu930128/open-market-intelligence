"use client";

import IntradayTrendChart, {
  defaultIntradayIndicators,
  intradayIndicatorOptions,
  type IntradayIndicatorKey,
  type IntradayIndicatorSettings,
  type IntradaySessionConfig,
} from "@/components/IntradayTrendChart";
import { StateSurface } from "@/components/LoadingPlaceholders";
import PriceUpdatePulse from "@/components/PriceUpdatePulse";
import ProfessionalChartPanel, {
  type ProfessionalChartStyle,
} from "@/components/ProfessionalChartPanel";
import StockKLineChart, {
  defaultIndicatorParameters,
  defaultIndicators,
  professionalIndicatorCategoryGroups,
  type IndicatorKey,
  type IndicatorParameters,
  type IndicatorSettings,
} from "@/components/StockKLineChart";
import type { ChartDrawing, ChartDrawingTool } from "@/components/LightweightKLineChart";
import TechnicalIndicatorMenu, {
  indicatorTemplates,
  type IndicatorTemplateKey,
} from "@/components/stock-detail/TechnicalIndicatorMenu";
import USFundamentalWorkspace, {
  type USFundamentalTab,
} from "@/components/us-stock-detail/USFundamentalWorkspace";
import {
  buildChartDrawingSnapshotPayload,
  chartDrawingApiPath,
  chartDrawingSnapshotsEqual,
  chartDrawingSyncDelayMs,
  createChartDrawingSnapshot,
  hasChartDrawingSnapshot,
  loadChartDrawings,
  normalizeChartDrawingSelection,
  normalizeStoredChartDrawings,
  saveChartDrawings,
  serializeChartDrawings,
  type ChartDrawingHistoryState,
  type ChartDrawingStorageState,
} from "@/components/professionalChartDrawing";
import { fetchJson, requestJson } from "@/lib/api";
import { requestBackfillJob } from "@/lib/jobs";
import {
  clearDataStatusFocus,
  emitDataStatusEvent,
  setDataStatusFocus,
} from "@/lib/dataStatusEvents";
import {
  timeframeLabel,
  usAssetTypeLabel,
  useT,
  type TranslationFunction,
} from "@/i18n";
import {
  US_INTRADAY_REFRESH_MS,
  US_EXTENDED_SESSION_END_MINUTES,
  US_EXTENDED_SESSION_START_MINUTES,
  US_SESSION_END_MINUTES,
  US_SESSION_START_MINUTES,
  type USIntradaySessionScope,
  getUsExtendedIntradayXRatio,
  getNewYorkMinutesOfDay,
  getUsIntradayXRatio,
  getUsMarketRefreshState,
  isUsExtendedSessionPoint,
  isUsRegularSessionPoint,
} from "@/lib/usMarketTime";
import { getUsMarketIndexConfig } from "@/lib/usMarketIndices";
import type { USCorporateEventSummaryRead } from "@/types/corporateEvents";
import type {
  USSecDerivedValueRead,
  USSecFinancialContractRead,
} from "@/types/usFinancials";
import type {
  ChartPoint,
  ChartDrawingSnapshotRead,
  IntradayTrendPoint,
  IntradayTrendResponse,
  StockVolumePace,
  USCapabilityExpectation,
  USIntradaySourceStatus,
  USMarketResearchRead,
  USCompanyProfileRead,
  USCorporateActionRead,
  USOhlcChartRead,
  USResolvedQuoteSnapshot,
  USResourceRefreshResultRead,
  USSecCompanyFactRead,
  USSecFactRefreshResultRead,
  USSecFundamentalMetricRead,
  USSecFundamentalSummaryRead,
  USSec13FInstitutionalHoldingsRead,
  USSecInsiderTransactionRead,
  USSecInsiderTransactionsRead,
  USShortVolumeDailyRead,
  USStockMasterRead,
} from "@/types/market";
import {
  type CSSProperties,
  type ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

type LoadState = "idle" | "loading" | "success" | "error";
type SuccessMessage = { text: string } | null;
type USChartTimeframe = "today" | "daily" | "weekly" | "monthly";
type USHistoricalTimeframe = Exclude<USChartTimeframe, "today">;
type USProfessionalIntradayTimeframe = "1m" | "5m" | "15m" | "30m" | "1h" | "4h";
type USProfessionalTimeframe = USProfessionalIntradayTimeframe | USHistoricalTimeframe;
type USProfessionalChartStyle = ProfessionalChartStyle;
type CoverageStatus = "ready" | "partial" | "missing" | "loading" | "stale";

type Props = {
  selectedSymbol: string | null;
  selectedSecurityName: string | null;
  watchlistRankingPanel?: ReactNode;
  onCompanyProfileChange?: (profile: USCompanyProfileRead | null) => void;
  onChartFocusModeChange?: (active: boolean) => void;
  onDailyPricesChanged?: () => void;
};

const timeframeOptions: USChartTimeframe[] = ["today", "daily", "weekly", "monthly"];
const usIntradaySessionScopeOptions: USIntradaySessionScope[] = ["regular", "extended", "all"];

const usProfessionalTimeframeOptions: USProfessionalTimeframe[] = [
  "1m",
  "5m",
  "15m",
  "30m",
  "1h",
  "4h",
  "daily",
  "weekly",
  "monthly",
];

const usProfessionalIntradayMinutes: Record<USProfessionalIntradayTimeframe, number> = {
  "1m": 1,
  "5m": 5,
  "15m": 15,
  "30m": 30,
  "1h": 60,
  "4h": 240,
};

const secFundamentalCards: Array<{ metric: string }> = [
  { metric: "revenue" },
  { metric: "gross_profit" },
  { metric: "operating_income" },
  { metric: "net_income" },
  { metric: "eps_diluted" },
  { metric: "eps_basic" },
  { metric: "assets" },
  { metric: "liabilities" },
  { metric: "equity" },
  { metric: "cash" },
  { metric: "debt_total" },
  { metric: "operating_cash_flow" },
  { metric: "capex" },
  { metric: "shares_outstanding" },
];

const barsByTimeframe: Record<USHistoricalTimeframe, number> = {
  daily: 180,
  weekly: 104,
  monthly: 72,
};

function defaultUsIntradaySessionScope(): USIntradaySessionScope {
  const marketState = getUsMarketRefreshState();

  return marketState.intradaySessionScope as USIntradaySessionScope;
}

function sessionScopeLabel(t: TranslationFunction, scope: USIntradaySessionScope) {
  return t(`usStockDetail.extendedHours.scopes.${scope}`);
}

function sessionPhaseLabel(t: TranslationFunction, phase: string | null | undefined) {
  if (!phase) return t("usStockDetail.extendedHours.phases.unknown");
  return t(`usStockDetail.extendedHours.phases.${phase}`);
}

async function fetchUsIntradayTrend(
  symbol: string,
  sessionScope: USIntradaySessionScope,
  interval: USProfessionalIntradayTimeframe = "1m"
) {
  return fetchJson<IntradayTrendResponse>(
    `/api/us-market/intraday/${encodeURIComponent(symbol)}`,
    { session_scope: sessionScope, interval }
  );
}

const defaultUsChartIndicators: IndicatorSettings = {
  ...defaultIndicators,
  signals: false,
  ma: true,
  volume: true,
  volumeProfile: false,
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

function formatCompactCurrency(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";

  const absValue = Math.abs(value);
  if (absValue >= 1_000_000_000_000) return `$${(value / 1_000_000_000_000).toFixed(2)}T`;
  if (absValue >= 1_000_000_000) return `$${(value / 1_000_000_000).toFixed(2)}B`;
  if (absValue >= 1_000_000) return `$${(value / 1_000_000).toFixed(2)}M`;
  return `$${formatNumber(value, 0)}`;
}

function formatRatioAsPct(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";

  const normalized = Math.abs(value) <= 1 ? value * 100 : value;
  return `${normalized.toFixed(2)}%`;
}

function financialNumber(value: string | null | undefined) {
  if (value === null || value === undefined || value.trim() === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function formatDecimalText(value: string | null | undefined, maximumFractionDigits = 4) {
  const parsed = financialNumber(value);
  return parsed === null ? "-" : formatNumber(parsed, maximumFractionDigits);
}

function formatSignedDecimalText(value: string | null | undefined) {
  const parsed = financialNumber(value);
  if (parsed === null) return "-";
  return `${parsed > 0 ? "+" : ""}${formatNumber(parsed, 0)}`;
}

function insiderCategoryTone(category: string) {
  if (category === "open_market_purchase") {
    return "border-omi-success-border bg-omi-success-soft text-omi-success-strong";
  }
  if (category === "open_market_sale") {
    return "border-omi-danger-border bg-omi-danger-soft text-omi-danger";
  }
  return "border-omi-border-subtle bg-omi-surface-subtle text-omi-text-muted";
}

function insiderOwnerRole(owner: USSecInsiderTransactionRead["owners"][number]) {
  return [
    owner.officer_title,
    owner.is_director ? "Director" : null,
    owner.is_ten_percent_owner ? "10% Owner" : null,
    owner.is_other ? owner.other_text || "Other" : null,
  ]
    .filter(Boolean)
    .join(" / ");
}

function formatDerivedValue(
  value: USSecDerivedValueRead | null | undefined,
  options: { percent?: boolean; perShare?: boolean } = {}
) {
  if (!value || value.status !== "ready") return "-";
  const parsed = financialNumber(value.value);
  if (parsed === null) return "-";
  if (options.percent || value.unit === "percent") return `${parsed.toFixed(2)}%`;
  if (options.perShare || value.unit?.toLowerCase().includes("usd/share")) {
    return `$${formatNumber(parsed, 2)}`;
  }
  if (value.unit === "USD") return formatCompactCurrency(parsed);
  if (value.unit?.toLowerCase().includes("shares")) return formatVolume(parsed);
  return formatNumber(parsed, 2);
}

function latestDerivedValue(
  values: USSecDerivedValueRead[] | null | undefined,
  metricCode?: string
) {
  return (values ?? [])
    .filter((value) => !metricCode || value.metric_code === metricCode)
    .sort((left, right) => {
      return `${right.period_end ?? ""}-${right.period ?? ""}`.localeCompare(
        `${left.period_end ?? ""}-${left.period ?? ""}`
      );
    })[0] ?? null;
}

function formatActionValue(action: USCorporateActionRead) {
  if (action.action_type === "dividend") {
    return action.amount !== null && action.amount !== undefined
      ? `$${formatNumber(action.amount, 4)}`
      : "-";
  }

  if (action.action_type === "split") {
    if (action.split_from !== null && action.split_to !== null) {
      return `${formatNumber(action.split_to, 2)}:${formatNumber(action.split_from, 2)}`;
    }
    return action.split_ratio !== null && action.split_ratio !== undefined
      ? `${formatNumber(action.split_ratio, 4)}x`
      : "-";
  }

  return "-";
}

function corporateEventTone(eventType: string) {
  if (eventType === "dividend") {
    return "border-omi-success bg-omi-success-soft text-omi-success-strong";
  }
  if (eventType === "split") {
    return "border-omi-danger-border bg-omi-danger-soft text-omi-danger";
  }
  return "border-omi-warning bg-omi-warning-soft text-omi-warning-strong";
}

async function fetchOptionalJson<T>(
  path: string,
  params?: Record<string, string | number | boolean>
) {
  try {
    return await fetchJson<T>(path, params);
  } catch (error) {
    if (error instanceof Error && error.message.startsWith("API 404:")) {
      return null;
    }

    throw error;
  }
}

type USSupplementalData = {
  factData?: USSecCompanyFactRead[];
  fundamentalData?: USSecFundamentalSummaryRead | null;
  financialData?: USSecFinancialContractRead | null;
  profileData?: USCompanyProfileRead | null;
  actionData?: USCorporateActionRead[];
  eventSummaryData?: USCorporateEventSummaryRead | null;
  eventSummaryError?: unknown | null;
  shortVolumeData?: USShortVolumeDailyRead[];
  insiderData?: USSecInsiderTransactionsRead | null;
  insiderError?: unknown | null;
  institutionalData?: USSec13FInstitutionalHoldingsRead | null;
  institutionalError?: unknown | null;
};

type USIntradayMeta = {
  sessionPhase: string | null;
  marketPhase: string | null;
  regularPointCount: number;
  extendedPointCount: number;
  hasExtendedHours: boolean;
  warnings: string[];
  volumePace: StockVolumePace | null;
  currentSourceStatus: USIntradaySourceStatus | null;
  barSourceStatus: USIntradaySourceStatus | null;
  currentPrice: number | null;
  currentPreviousClose: number | null;
  currentPreviousCloseTradeDate: string | null;
  changeReferencePrice: number | null;
  changeReferenceTradeDate: string | null;
  changeReferenceType: string | null;
  currentObservedAt: string | null;
  quoteExpectation: USCapabilityExpectation | null;
};

const emptyUsIntradayMeta: USIntradayMeta = {
  sessionPhase: null,
  marketPhase: null,
  regularPointCount: 0,
  extendedPointCount: 0,
  hasExtendedHours: false,
  warnings: [],
  volumePace: null,
  currentSourceStatus: null,
  barSourceStatus: null,
  currentPrice: null,
  currentPreviousClose: null,
  currentPreviousCloseTradeDate: null,
  changeReferencePrice: null,
  changeReferenceTradeDate: null,
  changeReferenceType: null,
  currentObservedAt: null,
  quoteExpectation: null,
};

function intradayMetaFromResponse(response: IntradayTrendResponse): USIntradayMeta {
  const sessionCoverage = response.session_coverage;
  const quoteExpectation =
    response.capability_expectation?.["quote.snapshot"] ?? null;
  const barExpectation =
    response.capability_expectation?.["intraday.bars"] ?? null;
  const currentExpectation =
    response.current_observation?.price_semantics === "resolved_quote_last_trade"
      ? quoteExpectation
      : barExpectation;
  const currentSourceStatus = response.current_source_status ?? null;
  const currentSessionRejected = Boolean(
    currentSourceStatus?.current_session_expected === true &&
      currentSourceStatus.current_session_satisfied !== true
  );
  const historicalTradeRejected = ["old", "historical"].includes(
    currentSourceStatus?.trade_recency ?? ""
  );
  const projectedCurrentPrice =
    currentSessionRejected ||
    historicalTradeRejected ||
    (currentExpectation &&
    !["ready", "stale"].includes(currentExpectation.outcome))
      ? null
      : response.current_observation?.value ?? null;
  return {
    sessionPhase: response.session_phase ?? null,
    marketPhase: response.market_phase ?? null,
    regularPointCount:
      sessionCoverage?.regular_point_count ??
      response.regular_point_count ??
      response.points.length,
    extendedPointCount:
      sessionCoverage?.extended_point_count ?? response.extended_point_count ?? 0,
    hasExtendedHours: Boolean(
      sessionCoverage?.has_extended_hours ?? response.has_extended_hours
    ),
    warnings: response.warnings ?? [],
    volumePace: response.volume_pace ?? null,
    currentSourceStatus,
    barSourceStatus: response.bar_source_status ?? response.source_status ?? null,
    currentPrice: projectedCurrentPrice,
    currentPreviousClose: response.current_observation?.previous_close ?? null,
    currentPreviousCloseTradeDate: response.previous_close_trade_date ?? null,
    changeReferencePrice:
      response.current_observation?.change_reference_price ??
      response.change_reference_price ??
      null,
    changeReferenceTradeDate:
      response.current_observation?.change_reference_trade_date ??
      response.change_reference_trade_date ??
      null,
    changeReferenceType:
      response.current_observation?.change_reference_type ??
      response.change_reference_type ??
      null,
    currentObservedAt: response.current_observation?.observed_at ?? null,
    quoteExpectation,
  };
}

function currentSessionTrendPoints(response: IntradayTrendResponse) {
  const coverage = response.session_coverage;
  if (coverage?.current_session_expected === true) {
    if (
      coverage.current_session_satisfied !== true ||
      !coverage.expected_trade_date ||
      coverage.trade_date !== coverage.expected_trade_date
    ) {
      return [];
    }
  } else if (
    coverage?.current_session_expected === undefined &&
    ["pre_market", "regular", "after_hours"].includes(
      response.market_phase ?? ""
    ) &&
    response.session_date_relation?.current_session_date &&
    coverage?.trade_date !== response.session_date_relation.current_session_date
  ) {
    return [];
  }
  return response.points;
}

function currentQuoteUnavailableMessageKey(
  expectation: USCapabilityExpectation | null
) {
  if (expectation?.outcome === "valid_empty") {
    return "usStockDetail.currentQuote.noTrade";
  }
  if (expectation?.outcome === "not_expected") {
    return "usStockDetail.currentQuote.notExpected";
  }
  if (
    expectation?.outcome === "expected_but_missing" &&
    expectation.expectation === "required"
  ) {
    return "usStockDetail.currentQuote.requiredMissing";
  }
  if (expectation?.outcome === "expected_but_missing") {
    return "usStockDetail.currentQuote.expectedMissing";
  }
  return "usStockDetail.currentQuote.unavailable";
}

function intradayWarningMessage(
  t: TranslationFunction,
  warnings: string[]
) {
  for (const warning of warnings) {
    if (warning === "PRE_RESOLUTION_SATISFIED") continue;
    if (warning === "READ_POLICY_FORBIDS_ACQUISITION") {
      return t("usStockDetail.extendedHours.cacheOnlyPolicy");
    }
    return warning;
  }
  return null;
}

type IntradaySourcePresentation = {
  level: "warning" | "error";
  title: string;
  badge: string;
  message: string;
};

function intradayProviderLabel(status: USIntradaySourceStatus): string {
  const value = status.provider || status.source || "US intraday";
  return value
    .split(/[._-]+/)
    .filter(Boolean)
    .map((part) => `${part.slice(0, 1).toUpperCase()}${part.slice(1)}`)
    .join(" ");
}

function intradaySourcePresentation(
  t: TranslationFunction,
  status: USIntradaySourceStatus | null
): IntradaySourcePresentation | null {
  if (!status) return null;
  const provider = intradayProviderLabel(status);

  if (status.is_fallback && status.has_usable_data) {
    return {
      level: "warning",
      title: t("usStockDetail.sourceStatus.providerErrorTitle", { provider }),
      badge: t("usStockDetail.sourceStatus.fallbackBadge", { provider }),
      message: t("usStockDetail.sourceStatus.fallbackMessage", { provider }),
    };
  }

  if (status.resolved_status === "partial") {
    return {
      level: "warning",
      title: t("usStockDetail.sourceStatus.partialTitle", { provider }),
      badge: t("usStockDetail.sourceStatus.partialBadge", { provider }),
      message: t("usStockDetail.sourceStatus.partialMessage", { provider }),
    };
  }

  if (status.status === "ok") return null;

  const minutes = Math.max(1, Math.ceil((status.lag_seconds ?? 0) / 60));

  if (status.freshness_status === "provider_error" && status.is_fallback) {
    return {
      level: "warning",
      title: t("usStockDetail.sourceStatus.providerErrorTitle", { provider }),
      badge: t("usStockDetail.sourceStatus.fallbackBadge", { provider }),
      message: t("usStockDetail.sourceStatus.fallbackMessage", { provider }),
    };
  }

  if (status.freshness_status === "provider_error") {
    return {
      level: "error",
      title: t("usStockDetail.sourceStatus.providerErrorTitle", { provider }),
      badge: t("usStockDetail.sourceStatus.unavailableBadge", { provider }),
      message: t("usStockDetail.sourceStatus.unavailableMessage", { provider }),
    };
  }

  if (status.freshness_status === "stale") {
    return {
      level: "warning",
      title: t("usStockDetail.sourceStatus.staleTitle", { provider }),
      badge: t("usStockDetail.sourceStatus.staleBadge", { provider, minutes }),
      message: t("usStockDetail.sourceStatus.staleMessage", { provider, minutes }),
    };
  }

  if (status.freshness_status === "delayed") {
    return {
      level: "warning",
      title: t("usStockDetail.sourceStatus.delayedTitle", { provider }),
      badge: t("usStockDetail.sourceStatus.delayedBadge", { provider, minutes }),
      message: t("usStockDetail.sourceStatus.delayedMessage", { provider, minutes }),
    };
  }

  return {
    level: "error",
    title: t("usStockDetail.sourceStatus.providerErrorTitle", { provider }),
    badge: t("usStockDetail.sourceStatus.unavailableBadge", { provider }),
    message: t("usStockDetail.sourceStatus.unavailableMessage", { provider }),
  };
}

async function fetchUsSupplementalData(
  symbol: string,
  tab: USFundamentalTab
): Promise<USSupplementalData> {
  const encodedSymbol = encodeURIComponent(symbol);
  if (tab === "financials") {
    const [factData, fundamentalData, financialData, eventSummaryResult] =
      await Promise.all([
        fetchJson<USSecCompanyFactRead[]>(`/api/us-market/sec/${encodedSymbol}/facts`, {
          limit: 24,
          offset: 0,
        }).catch(() => []),
        fetchOptionalJson<USSecFundamentalSummaryRead>(
          `/api/us-market/sec/${encodedSymbol}/fundamentals`
        ).catch(() => null),
        fetchOptionalJson<USSecFinancialContractRead>(
          `/api/us-market/sec/${encodedSymbol}/financials`,
          { periods: 8 }
        ).catch(() => null),
        fetchJson<USCorporateEventSummaryRead>(
          `/api/us-market/corporate-events/${encodedSymbol}/summary`
        )
          .then((data) => ({ data, error: null }))
          .catch((error: unknown) => ({ data: null, error })),
      ]);
    return {
      factData,
      fundamentalData,
      financialData,
      eventSummaryData: eventSummaryResult.data,
      eventSummaryError: eventSummaryResult.error,
    };
  }
  if (tab === "overview") {
    const [profileData, actionData, eventSummaryResult] = await Promise.all([
      fetchOptionalJson<USCompanyProfileRead>(
        `/api/us-market/profiles/${encodedSymbol}`
      ).catch(() => null),
      fetchJson<USCorporateActionRead[]>(
        `/api/us-market/corporate-actions/${encodedSymbol}`,
        { limit: 8, offset: 0 }
      ).catch(() => []),
      fetchJson<USCorporateEventSummaryRead>(
        `/api/us-market/corporate-events/${encodedSymbol}/summary`
      )
        .then((data) => ({ data, error: null }))
        .catch((error: unknown) => ({ data: null, error })),
    ]);
    return {
      profileData,
      actionData,
      eventSummaryData: eventSummaryResult.data,
      eventSummaryError: eventSummaryResult.error,
    };
  }
  if (tab === "filings") {
    const [factData, actionData, eventSummaryResult] = await Promise.all([
      fetchJson<USSecCompanyFactRead[]>(`/api/us-market/sec/${encodedSymbol}/facts`, {
        limit: 24,
        offset: 0,
      }).catch(() => []),
      fetchJson<USCorporateActionRead[]>(
        `/api/us-market/corporate-actions/${encodedSymbol}`,
        { limit: 8, offset: 0 }
      ).catch(() => []),
      fetchJson<USCorporateEventSummaryRead>(
        `/api/us-market/corporate-events/${encodedSymbol}/summary`
      )
        .then((data) => ({ data, error: null }))
        .catch((error: unknown) => ({ data: null, error })),
    ]);
    return {
      factData,
      actionData,
      eventSummaryData: eventSummaryResult.data,
      eventSummaryError: eventSummaryResult.error,
    };
  }
  if (tab === "short") {
    return {
      shortVolumeData: await fetchJson<USShortVolumeDailyRead[]>(
        `/api/us-market/short-volume/${encodedSymbol}/history`,
        { limit: 8, offset: 0 }
      ).catch(() => []),
    };
  }
  if (tab === "insider") {
    const insiderResult = await fetchJson<USSecInsiderTransactionsRead>(
      `/api/us-market/sec/${encodedSymbol}/insider-transactions`,
      { limit: 100 }
    )
      .then((data) => ({ data, error: null }))
      .catch((error: unknown) => ({ data: null, error }));
    return { insiderData: insiderResult.data, insiderError: insiderResult.error };
  }
  const institutionalResult = await fetchJson<USSec13FInstitutionalHoldingsRead>(
    `/api/us-market/sec/${encodedSymbol}/institutional-holdings`,
    { manager_limit: 100 }
  )
    .then((data) => ({ data, error: null }))
    .catch((error: unknown) => ({ data: null, error }));
  return {
    institutionalData: institutionalResult.data,
    institutionalError: institutionalResult.error,
  };
}

const usIntradaySession: IntradaySessionConfig = {
  startMinutes: US_SESSION_START_MINUTES,
  endMinutes: US_SESSION_END_MINUTES,
  timeTicks: [
    { label: "09:30", minutes: 9 * 60 + 30 },
    { label: "11:00", minutes: 11 * 60 },
    { label: "12:30", minutes: 12 * 60 + 30 },
    { label: "14:00", minutes: 14 * 60 },
    { label: "15:30", minutes: 15 * 60 + 30 },
    { label: "16:00", minutes: 16 * 60 },
  ],
  getMinutesOfDay: getNewYorkMinutesOfDay,
  getXRatio: getUsIntradayXRatio,
  isRegularSessionPoint: isUsRegularSessionPoint,
  volumeFormatter: formatVolume,
};

const usExtendedIntradaySession: IntradaySessionConfig = {
  startMinutes: US_EXTENDED_SESSION_START_MINUTES,
  endMinutes: US_EXTENDED_SESSION_END_MINUTES,
  timeTicks: [
    { label: "04:00", minutes: 4 * 60 },
    { label: "07:00", minutes: 7 * 60 },
    { label: "09:30", minutes: 9 * 60 + 30 },
    { label: "12:00", minutes: 12 * 60 },
    { label: "16:00", minutes: 16 * 60 },
    { label: "18:00", minutes: 18 * 60 },
    { label: "20:00", minutes: 20 * 60 },
  ],
  getMinutesOfDay: getNewYorkMinutesOfDay,
  getXRatio: getUsExtendedIntradayXRatio,
  isRegularSessionPoint: isUsExtendedSessionPoint,
  volumeFormatter: formatVolume,
};

function usIntradaySessionConfigForScope(scope: USIntradaySessionScope) {
  return scope === "regular" ? usIntradaySession : usExtendedIntradaySession;
}

function formatDate(value: string | null | undefined) {
  if (!value) return "-";
  return value.slice(0, 10);
}

function latestDate(values: Array<string | null | undefined>) {
  const validDates = values.filter((value): value is string => Boolean(value));
  if (!validDates.length) return "-";

  const sortedDates = validDates.sort((left, right) => left.localeCompare(right));
  return formatDate(sortedDates[sortedDates.length - 1]);
}

function formatDateTime(value: string | null | undefined) {
  if (!value) return "-";

  const date = new Date(value);

  if (Number.isNaN(date.getTime()) || !value.includes("T")) return value;

  return new Intl.DateTimeFormat("zh-TW", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "America/New_York",
  }).format(date);
}

function chartDrawingStorageKey(symbol: string | null, timeframe: USProfessionalTimeframe) {
  return `omi:us:chart-drawings:v1:${symbol ?? "empty"}:${timeframe}`;
}

function isUsProfessionalIntradayTimeframe(
  value: USProfessionalTimeframe
): value is USProfessionalIntradayTimeframe {
  return value in usProfessionalIntradayMinutes;
}

function chartDrawingTimeMode(timeframe: USProfessionalTimeframe) {
  return isUsProfessionalIntradayTimeframe(timeframe) ? "intraday" : "date";
}

function formatPct(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

function valueTone(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "text-omi-text-muted";
  }
  if (value > 0) return "text-omi-market-up";
  if (value < 0) return "text-omi-market-down";
  return "text-omi-text";
}

function assetTypeLabel(t: TranslationFunction, stock: USStockMasterRead | null) {
  if (!stock) return "-";
  return usAssetTypeLabel(t, stock.asset_type);
}

function stockName(stock: USStockMasterRead | null, fallback: string | null) {
  return stock?.security_name ?? stock?.sec_company_name ?? fallback ?? "";
}

function usSymbolKey(value: unknown) {
  return typeof value === "string" ? value.trim().toUpperCase() : null;
}

function toChartPoint(point: USOhlcChartRead["points"][number]): ChartPoint {
  return {
    time: String(point.time).slice(0, 10),
    open: point.open,
    high: point.high,
    low: point.low,
    close: point.close,
    volume: point.volume,
    trade_value: null,
    transaction_count: null,
  };
}

function intradayToChartPoint(point: IntradayTrendPoint): ChartPoint {
  return {
    time: point.time,
    open: point.open ?? point.price,
    high: point.high ?? point.price,
    low: point.low ?? point.price,
    close: point.price,
    volume: point.volume,
    trade_value: point.trade_value ?? null,
    transaction_count: null,
  };
}

function formatFactValue(fact: USSecCompanyFactRead) {
  if (fact.value_numeric !== null && fact.value_numeric !== undefined) {
    return formatNumber(fact.value_numeric, 0);
  }

  return fact.value_text ?? "-";
}

function formatFundamentalValue(metric: USSecFundamentalMetricRead | null | undefined) {
  if (!metric) return "-";

  const value = metric.value_numeric;
  if (value === null || value === undefined || Number.isNaN(value)) {
    return metric.value_text ?? "-";
  }

  const unit = metric.unit.toLowerCase();
  if (unit.includes("usd/shares")) return `$${formatNumber(value, 2)}`;
  if (unit === "usd") return formatCompactCurrency(value);
  if (unit.includes("shares")) return formatVolume(value);

  return formatNumber(value, 2);
}

function formatFundamentalPeriod(metric: USSecFundamentalMetricRead | null | undefined) {
  if (!metric) return "-";

  const fiscal = [metric.fiscal_year, metric.fiscal_period].filter(Boolean).join(" ");
  const periodEnd = formatDate(metric.period_end_date);
  if (fiscal && periodEnd !== "-") return `${fiscal} · ${periodEnd}`;
  if (fiscal) return fiscal;
  return periodEnd;
}

function daysSince(value: string | null | undefined) {
  if (!value || value === "-") return null;

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return null;

  const today = new Date();
  const todayDate = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  const parsedDate = new Date(
    parsed.getFullYear(),
    parsed.getMonth(),
    parsed.getDate()
  );

  return Math.floor((todayDate.getTime() - parsedDate.getTime()) / 86_400_000);
}

function coverageStatus(
  hasData: boolean,
  loadState: LoadState,
  latestDateValue?: string | null,
  staleAfterDays?: number
): CoverageStatus {
  if (loadState === "loading") return "loading";
  if (!hasData) return "missing";

  const age = daysSince(latestDateValue);
  if (
    staleAfterDays !== undefined &&
    age !== null &&
    age > staleAfterDays
  ) {
    return "stale";
  }

  return "ready";
}

function coverageClass(status: CoverageStatus) {
  const classes: Record<CoverageStatus, string> = {
    ready: "border-omi-success-border bg-omi-success-soft text-omi-success",
    partial: "border-omi-warning-border bg-omi-warning-soft text-omi-warning-strong",
    missing: "border-omi-border-subtle bg-omi-surface-subtle text-omi-text-muted",
    loading: "border-omi-info-border bg-omi-info-soft text-omi-info",
    stale: "border-omi-warning-border bg-omi-warning-soft text-omi-warning",
  };

  return classes[status];
}

function DataCoverageChip({
  label,
  status,
  detail,
}: {
  label: string;
  status: CoverageStatus;
  detail: string;
}) {
  const t = useT();

  return (
    <div className={`border px-3 py-2 ${coverageClass(status)}`}>
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-bold uppercase tracking-wide">{label}</span>
        <span className="text-[11px] font-black">
          {t(`usStockDetail.coverage.status.${status}`)}
        </span>
      </div>
      <div className="mt-1 truncate text-[11px] font-medium opacity-80">{detail}</div>
    </div>
  );
}

function metricBarStyle(value: number | null | undefined): CSSProperties {
  const scale =
    value === null || value === undefined || Number.isNaN(value)
      ? 0
      : Math.max(0, Math.min(100, Math.abs(value))) / 100;
  return { "--omi-technical-bar-scale": scale } as CSSProperties;
}

function metricBarClass(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "bg-omi-border";
  if (value > 0) return "bg-omi-market-up-flash";
  if (value < 0) return "bg-omi-market-down-flash";
  return "bg-omi-border";
}

function EmptyDataState({ message }: { message: string }) {
  return (
    <StateSurface title={message} tone="empty" compact />
  );
}

function MetricCell({
  label,
  value,
  tone = "text-omi-text-strong",
}: {
  label: string;
  value: ReactNode;
  tone?: string;
}) {
  return (
    <div className="bg-omi-surface px-4 py-3">
      <div className="text-xs text-omi-text-muted">{label}</div>
      <div className={`mt-1 break-words text-sm font-bold ${tone}`}>{value}</div>
    </div>
  );
}

function FundamentalMetricCell({
  label,
  metric,
}: {
  label: string;
  metric: USSecFundamentalMetricRead | null | undefined;
}) {
  return (
    <div className="bg-omi-surface px-4 py-3">
      <div className="text-xs text-omi-text-muted">{label}</div>
      <div className="mt-1 break-words text-sm font-bold text-omi-text-strong">
        {formatFundamentalValue(metric)}
      </div>
      <div className="mt-1 truncate text-[11px] font-semibold text-omi-text-subtle">
        {formatFundamentalPeriod(metric)}
      </div>
    </div>
  );
}

export default function USStockDetailPanel({
  selectedSymbol,
  selectedSecurityName,
  watchlistRankingPanel,
  onCompanyProfileChange,
  onChartFocusModeChange,
  onDailyPricesChanged,
}: Props) {
  const t = useT();
  const tRef = useRef(t);
  const [timeframe, setTimeframe] = useState<USChartTimeframe>("daily");
  const [indicatorMenuOpen, setIndicatorMenuOpen] = useState(false);
  const [chartFocusMode, setChartFocusMode] = useState(false);
  const [professionalTimeframe, setProfessionalTimeframe] =
    useState<USProfessionalTimeframe>("daily");
  const [professionalChartStyle, setProfessionalChartStyle] =
    useState<USProfessionalChartStyle>("candlestick");
  const [chartIndicators, setChartIndicators] =
    useState<IndicatorSettings>(defaultUsChartIndicators);
  const [activeIndicatorTemplate, setActiveIndicatorTemplate] =
    useState<IndicatorTemplateKey | null>("basic");
  const [indicatorParameters, setIndicatorParameters] =
    useState<IndicatorParameters>(defaultIndicatorParameters);
  const [chartDrawingTool, setChartDrawingTool] = useState<ChartDrawingTool>("cursor");
  const [chartDrawingState, setChartDrawingState] = useState<ChartDrawingStorageState>({
    key: "",
    drawings: [],
  });
  const [selectedChartDrawingId, setSelectedChartDrawingId] = useState<string | null>(null);
  const [chartDrawingHistoryState, setChartDrawingHistoryState] =
    useState<ChartDrawingHistoryState>({
      key: "",
      past: [],
      future: [],
    });
  const [activeDataTab, setActiveDataTab] = useState<USFundamentalTab>("financials");
  const [selectedStock, setSelectedStock] = useState<USStockMasterRead | null>(null);
  const [chart, setChart] = useState<USOhlcChartRead | null>(null);
  const [headlineQuote, setHeadlineQuote] = useState<USResolvedQuoteSnapshot | null>(null);
  const [marketResearch, setMarketResearch] = useState<USMarketResearchRead | null>(null);
  const [professionalIntraday, setProfessionalIntraday] =
    useState<IntradayTrendResponse | null>(null);
  const [companyProfile, setCompanyProfile] = useState<USCompanyProfileRead | null>(null);
  const [corporateActions, setCorporateActions] = useState<USCorporateActionRead[]>([]);
  const [corporateEventSummary, setCorporateEventSummary] =
    useState<USCorporateEventSummaryRead | null>(null);
  const [shortVolumeRows, setShortVolumeRows] = useState<USShortVolumeDailyRead[]>([]);
  const [insiderTransactions, setInsiderTransactions] =
    useState<USSecInsiderTransactionsRead | null>(null);
  const [institutionalHoldings, setInstitutionalHoldings] =
    useState<USSec13FInstitutionalHoldingsRead | null>(null);
  const [todayTrend, setTodayTrend] = useState<IntradayTrendPoint[]>([]);
  const [todayPreviousClose, setTodayPreviousClose] = useState<number | null>(null);
  const [todayPreviousCloseStatus, setTodayPreviousCloseStatus] =
    useState<string>("unknown");
  const [todaySource, setTodaySource] = useState("unavailable");
  const [todayUpdatedAt, setTodayUpdatedAt] = useState<string | null>(null);
  const [todayIntradayMeta, setTodayIntradayMeta] = useState<USIntradayMeta>(emptyUsIntradayMeta);
  const [todaySymbol, setTodaySymbol] = useState<string | null>(null);
  const [todaySessionScope, setTodaySessionScope] =
    useState<USIntradaySessionScope | null>(null);
  const [intradaySessionScope, setIntradaySessionScope] =
    useState<USIntradaySessionScope>(() => defaultUsIntradaySessionScope());
  const [intradayIndicators, setIntradayIndicators] =
    useState<IntradayIndicatorSettings>(defaultIntradayIndicators);
  const [factRows, setFactRows] = useState<USSecCompanyFactRead[]>([]);
  const [fundamentalSummary, setFundamentalSummary] =
    useState<USSecFundamentalSummaryRead | null>(null);
  const [financialContract, setFinancialContract] =
    useState<USSecFinancialContractRead | null>(null);
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const [factLoadState, setFactLoadState] = useState<LoadState>("idle");
  const [refreshingFacts, setRefreshingFacts] = useState(false);
  const [refreshingProfile, setRefreshingProfile] = useState(false);
  const [refreshingActions, setRefreshingActions] = useState(false);
  const [refreshingInsiders, setRefreshingInsiders] = useState(false);
  const [successMessage, setSuccessMessage] = useState<SuccessMessage>(null);
  const requestSeq = useRef(0);
  const chartRequestSeq = useRef(0);
  const supplementalRequestSeq = useRef(0);
  const supplementalLoadedKeysRef = useRef(new Set<string>());
  const finalIntradayRefreshDate = useRef<string | null>(null);
  const intradaySourceEventStateRef = useRef<Map<string, string>>(new Map());
  const ohlcCoverageEventStateRef = useRef<Map<string, string>>(new Map());
  const onDailyPricesChangedRef = useRef(onDailyPricesChanged);
  const chartDrawingSyncTimerRef = useRef<number | null>(null);
  const chartDrawingLocalRevisionRef = useRef(0);

  useEffect(() => {
    tRef.current = t;
  }, [t]);

  useEffect(() => {
    onDailyPricesChangedRef.current = onDailyPricesChanged;
  }, [onDailyPricesChanged]);

  const chartDrawingKey = chartDrawingStorageKey(selectedSymbol, professionalTimeframe);
  const storedChartDrawings = useMemo(
    () => loadChartDrawings(chartDrawingKey),
    [chartDrawingKey]
  );
  const chartDrawings =
    chartDrawingState.key === chartDrawingKey
      ? chartDrawingState.drawings
      : storedChartDrawings;
  const chartDrawingHistory =
    chartDrawingHistoryState.key === chartDrawingKey
      ? chartDrawingHistoryState
      : { key: chartDrawingKey, past: [], future: [] };
  const canUndoChartDrawing = chartDrawingHistory.past.length > 0;
  const canRedoChartDrawing = chartDrawingHistory.future.length > 0;
  const activeSelectedChartDrawingId = chartDrawings.some(
    (drawing) => drawing.id === selectedChartDrawingId
  )
    ? selectedChartDrawingId
    : null;

  const expectedChartTimeframe = timeframe === "today" ? "daily" : timeframe;
  const chartMatchesSelection = Boolean(
    selectedSymbol &&
      chart &&
      usSymbolKey(chart.symbol) === usSymbolKey(selectedSymbol) &&
      chart.timeframe === expectedChartTimeframe
  );
  const chartLoadState: LoadState =
    selectedSymbol && !chartMatchesSelection && loadState !== "error"
      ? "loading"
      : loadState;
  const visibleSelectedStock =
    usSymbolKey(selectedStock?.symbol) === usSymbolKey(selectedSymbol)
      ? selectedStock
      : null;
  const chartData = useMemo(() => {
    return chartMatchesSelection ? chart?.points.map(toChartPoint) ?? [] : [];
  }, [chart, chartMatchesSelection]);
  const todayMatchesSelection = Boolean(
    selectedSymbol &&
      usSymbolKey(todaySymbol) === usSymbolKey(selectedSymbol) &&
      todaySessionScope === intradaySessionScope
  );
  const visibleTodayTrend = useMemo(
    () => (todayMatchesSelection ? todayTrend : []),
    [todayMatchesSelection, todayTrend]
  );
  const visibleTodayPreviousClose = todayMatchesSelection ? todayPreviousClose : null;
  const visibleTodayPreviousCloseStatus = todayMatchesSelection
    ? todayPreviousCloseStatus
    : "unknown";
  const visibleTodaySource = todayMatchesSelection ? todaySource : "unavailable";
  const visibleTodayUpdatedAt = todayMatchesSelection ? todayUpdatedAt : null;
  const visibleTodayIntradayMeta = todayMatchesSelection
    ? todayIntradayMeta
    : emptyUsIntradayMeta;
  const visibleHeadlineQuote =
    usSymbolKey(headlineQuote?.quote?.symbol) === usSymbolKey(selectedSymbol)
      ? headlineQuote
      : null;
  const headlineQuoteRaw = visibleHeadlineQuote?.quote?.last_trade_price ?? null;
  const headlineQuotePrice =
    visibleHeadlineQuote?.facts_usable &&
    headlineQuoteRaw !== null &&
    Number.isFinite(Number(headlineQuoteRaw))
      ? Number(headlineQuoteRaw)
      : null;
  const professionalIsIntraday = isUsProfessionalIntradayTimeframe(professionalTimeframe);
  const professionalIntradayMatchesSelection = Boolean(
    selectedSymbol &&
      professionalIntraday &&
      usSymbolKey(professionalIntraday.symbol ?? professionalIntraday.stock_id) ===
        usSymbolKey(selectedSymbol) &&
      professionalIntraday.effective_interval === professionalTimeframe
  );
  const professionalChartData = useMemo<ChartPoint[]>(() => {
    if (!isUsProfessionalIntradayTimeframe(professionalTimeframe)) return chartData;

    if (!professionalIntradayMatchesSelection) return [];
    return professionalIntraday?.points.map(intradayToChartPoint) ?? [];
  }, [
    chartData,
    professionalIntraday,
    professionalIntradayMatchesSelection,
    professionalTimeframe,
  ]);
  const latestToday = visibleTodayTrend[visibleTodayTrend.length - 1] ?? null;
  const latestPoint = chartData[chartData.length - 1] ?? null;
  const latestProfessionalPoint = professionalChartData[professionalChartData.length - 1] ?? null;
  const displayDate =
    visibleHeadlineQuote?.quote?.event_at ??
    visibleHeadlineQuote?.selected_event_at ??
    visibleTodayIntradayMeta.currentObservedAt ??
    latestToday?.time ??
    latestPoint?.time ??
    null;
  const latestClose = headlineQuotePrice ?? visibleTodayIntradayMeta.currentPrice;
  const previousClose =
    (chart?.previous_close_status === "current" ? chart.previous_close : null) ??
    visibleTodayIntradayMeta.changeReferencePrice;
  const change =
    latestClose !== null && previousClose !== null
      ? latestClose - previousClose
      : null;
  const changePct =
    change !== null && previousClose !== null && previousClose !== 0
      ? (change / previousClose) * 100
      : null;
  const currentQuoteUnavailable = latestClose === null;
  const todayHistoricalReferencePrice =
    visibleTodayIntradayMeta.changeReferencePrice ??
    visibleTodayIntradayMeta.currentPreviousClose ??
    (visibleTodayPreviousCloseStatus === "current"
      ? visibleTodayPreviousClose
      : null);
  const todayPreviousCloseReferenceDate =
    visibleTodayIntradayMeta.changeReferenceTradeDate ??
    visibleTodayIntradayMeta.currentPreviousCloseTradeDate ??
    latestPoint?.time ??
    null;
  const visibleMarketResearch =
    usSymbolKey(marketResearch?.symbol) === usSymbolKey(selectedSymbol)
      ? marketResearch
      : null;
  const technicalIndicators = visibleMarketResearch?.technical_indicators ?? null;
  const technicalStructure = visibleMarketResearch?.technical_structure ?? null;
  const technicalCurrent = technicalIndicators?.current ?? null;
  const technicalMovingAverages = technicalCurrent?.moving_averages ?? {};
  const ma5 = technicalMovingAverages.ma5 ?? null;
  const ma20 = technicalMovingAverages.ma20 ?? null;
  const ma60 = technicalMovingAverages.ma60 ?? null;
  const priceVsMa20 = technicalStructure?.metrics.price_vs_ma20_pct ?? null;
  const technicalVolumeMetric = technicalStructure?.metrics.volume_vs_ma20_pct ?? null;
  const technicalDayChangePct = technicalStructure?.metrics.day_change_pct ?? null;
  const technicalTitleKey =
    technicalStructure?.trend_state === "bullish_stack"
      ? "usStockDetail.technicalStates.bullishStack"
      : technicalStructure?.trend_state === "below_ma20"
        ? "usStockDetail.technicalStates.belowMa20"
        : technicalStructure?.trend_state === "ma_consolidation"
          ? "usStockDetail.technicalStates.maConsolidation"
          : "usStockDetail.technicalStates.insufficient";
  const technicalTitle = t(technicalTitleKey);
  const technicalQuality = technicalIndicators?.quality ?? null;
  const latestShortVolume = shortVolumeRows[0] ?? null;
  const latestFactFiledDate = latestDate(factRows.map((fact) => fact.filed_date));
  const latestActionDate = latestDate(corporateActions.map((action) => action.event_date));
  const fundamentalMetrics = useMemo(() => {
    return fundamentalSummary?.metrics ?? [];
  }, [fundamentalSummary]);
  const fundamentalMetricMap = useMemo(() => {
    return new Map(fundamentalMetrics.map((metric) => [metric.metric, metric]));
  }, [fundamentalMetrics]);
  const revenueMetric = fundamentalMetricMap.get("revenue") ?? null;
  const epsDilutedMetric = fundamentalMetricMap.get("eps_diluted") ?? null;
  const sharesOutstandingMetric = fundamentalMetricMap.get("shares_outstanding") ?? null;
  const financialDerived = financialContract?.derived;
  const financialQuality = financialContract?.quality;
  const decisionBlockingFinancialIssues =
    financialQuality?.decision_blocking_issues?.length
      ? financialQuality.decision_blocking_issues
      : !financialQuality?.decision_usable
        ? financialQuality?.issues ?? []
        : [];
  const nonBlockingFinancialIssues = financialQuality?.non_blocking_issues ?? [];
  const revenueTtmMetric = financialDerived?.ttm?.revenue ?? null;
  const epsTtmMetric =
    financialDerived?.ttm?.eps_diluted ?? financialDerived?.ttm?.eps_basic ?? null;
  const grossMarginMetric = latestDerivedValue(financialDerived?.ratios, "gross_margin");
  const operatingMarginMetric = latestDerivedValue(
    financialDerived?.ratios,
    "operating_margin"
  );
  const netMarginMetric = latestDerivedValue(financialDerived?.ratios, "net_margin");
  const revenueYoyMetric = latestDerivedValue(
    financialDerived?.growth,
    "revenue_yoy_growth"
  );
  const freeCashFlowMetric = latestDerivedValue(financialDerived?.free_cash_flow);
  const sharesOutstandingContractMetric =
    financialDerived?.latest_balance?.shares_outstanding ?? null;
  const latestFinancialFiling = financialContract?.as_reported.latest_filing;
  const normalizedFacts = financialContract?.normalized.facts ?? [];
  const financialQuarterRows = useMemo(() => {
    const byPeriod = new Map<
      string,
      {
        period: string;
        periodEnd: string | null;
        revenue?: USSecDerivedValueRead;
        netIncome?: USSecDerivedValueRead;
        eps?: USSecDerivedValueRead;
      }
    >();
    const add = (
      metricCode: "revenue" | "net_income" | "eps_diluted",
      value: USSecDerivedValueRead
    ) => {
      if (!value.period) return;
      const row = byPeriod.get(value.period) ?? {
        period: value.period,
        periodEnd: value.period_end,
      };
      if (metricCode === "revenue") row.revenue = value;
      if (metricCode === "net_income") row.netIncome = value;
      if (metricCode === "eps_diluted") row.eps = value;
      byPeriod.set(value.period, row);
    };
    (financialDerived?.quarterly?.revenue ?? []).forEach((value) => add("revenue", value));
    (financialDerived?.quarterly?.net_income ?? []).forEach((value) => add("net_income", value));
    (financialDerived?.quarterly?.eps_diluted ?? []).forEach((value) => add("eps_diluted", value));
    return Array.from(byPeriod.values())
      .sort((left, right) => right.period.localeCompare(left.period))
      .slice(0, 8);
  }, [financialDerived]);
  const latestFundamentalFiledDate = latestDate(
    [latestFinancialFiling?.filed_date, ...fundamentalMetrics.map((metric) => metric.filed_date)]
  );
  const latestFundamentalPeriodEnd = latestDate(
    [
      ...normalizedFacts.map((metric) => metric.period_end),
      ...fundamentalMetrics.map((metric) => metric.period_end_date),
    ]
  );
  const selectedIndexConfig = getUsMarketIndexConfig(selectedSymbol);
  const upcomingCorporateEvents = selectedIndexConfig
    ? []
    : corporateEventSummary?.results ?? [];
  const corporateEventSourceUncertain = Boolean(
    !selectedIndexConfig &&
      !upcomingCorporateEvents.length &&
      corporateEventSummary &&
      corporateEventSummary.cache_status !== "current"
  );
  const selectedDisplaySymbol = selectedIndexConfig?.displaySymbol ?? selectedSymbol ?? "-";
  const selectedDisplayName =
    selectedIndexConfig?.name ?? stockName(visibleSelectedStock, selectedSecurityName);
  const dataStatusContextKey = `us:${selectedSymbol?.toUpperCase() ?? "unknown"}`;
  const dataStatusDisplayName = selectedIndexConfig?.name ?? selectedSecurityName;
  const dataStatusContextLabel = selectedSymbol
    ? [selectedDisplaySymbol, dataStatusDisplayName].filter(Boolean).join(" ")
    : t("watchlist.usHeader");
  const dataStatusSource = t("usStockDetail.statusSource");
  const publishDetailDataStatus = useCallback(
    (title: string, error: unknown) => {
      if (!selectedSymbol) return;

      emitDataStatusEvent({
        market: "us",
        level: "error",
        title,
        message: error instanceof Error ? error.message : title,
        source: dataStatusSource,
        contextKey: dataStatusContextKey,
        contextLabel: dataStatusContextLabel,
        dedupeKey: `${dataStatusContextKey}:${title}:error`,
      });
    },
    [dataStatusContextKey, dataStatusContextLabel, dataStatusSource, selectedSymbol]
  );
  const publishIntradaySourceStatus = useCallback(
    (symbol: string, response: IntradayTrendResponse) => {
      const sourceStatus =
        response.current_source_status ??
        response.bar_source_status ??
        response.source_status;
      if (!sourceStatus) return;

      const normalizedSymbol = symbol.toUpperCase();
      const contextKey = `us:${normalizedSymbol}`;
      const dedupeKey = `${contextKey}:intraday-source`;
      const signature = [
        sourceStatus.provider,
        sourceStatus.source,
        sourceStatus.status,
        sourceStatus.resolved_status,
        sourceStatus.freshness_status,
        sourceStatus.is_fallback,
      ].join(":");
      const sourceLabel = intradayProviderLabel(sourceStatus);
      const previousSignature = intradaySourceEventStateRef.current.get(dedupeKey);
      if (previousSignature === signature) return;

      intradaySourceEventStateRef.current.set(dedupeKey, signature);
      const presentation = intradaySourcePresentation(tRef.current, sourceStatus);
      if (!presentation) {
        if (previousSignature && !previousSignature.startsWith("ok:")) {
          const recovered = sourceStatus.freshness_status === "current";
          emitDataStatusEvent({
            market: "us",
            level: recovered ? "success" : "info",
            title: tRef.current(
              recovered
                ? "usStockDetail.sourceStatus.recoveredTitle"
                : "usStockDetail.sourceStatus.monitoringEndedTitle"
            ),
            message: tRef.current(
              recovered
                ? "usStockDetail.sourceStatus.recoveredMessage"
                : "usStockDetail.sourceStatus.monitoringEndedMessage"
            ),
            source: sourceLabel,
            contextKey,
            contextLabel:
              normalizedSymbol === selectedSymbol?.toUpperCase()
                ? dataStatusContextLabel
                : normalizedSymbol,
            dedupeKey,
          });
        }
        return;
      }

      emitDataStatusEvent({
        market: "us",
        level: presentation.level,
        title: presentation.title,
        message: presentation.message,
        source: sourceLabel,
        contextKey,
        contextLabel:
          normalizedSymbol === selectedSymbol?.toUpperCase()
            ? dataStatusContextLabel
            : normalizedSymbol,
        dedupeKey,
      });
    },
    [dataStatusContextLabel, selectedSymbol]
  );
  const selectedSubtitle = selectedIndexConfig
    ? `${selectedIndexConfig.exchange} · ${usAssetTypeLabel(t, "index")} · ${formatDate(displayDate)}`
    : visibleSelectedStock
      ? `${visibleSelectedStock.exchange ?? "-"} · ${assetTypeLabel(t, visibleSelectedStock)} · ${formatDate(displayDate)}`
      : selectedSymbol
        ? t("usStockDetail.loadingMaster")
        : t("usStockDetail.selectStockPrompt");
  const activeIntradaySession = usIntradaySessionConfigForScope(intradaySessionScope);
  const intradaySessionMetaLine = t("usStockDetail.extendedHours.meta", {
    phase: sessionPhaseLabel(
      t,
      visibleTodayIntradayMeta.sessionPhase ?? visibleTodayIntradayMeta.marketPhase
    ),
    regular: visibleTodayIntradayMeta.regularPointCount,
    extended: visibleTodayIntradayMeta.extendedPointCount,
  });
  const intradayCoverageNotice =
    intradaySessionScope === "regular" &&
    chartLoadState === "success" &&
    visibleTodayTrend.length === 0 &&
    visibleTodayIntradayMeta.extendedPointCount > 0
      ? t("usStockDetail.extendedHours.regularMissingExtendedAvailable", {
          count: visibleTodayIntradayMeta.extendedPointCount,
        })
      : intradaySessionScope === "extended" &&
          chartLoadState === "success" &&
          visibleTodayTrend.length === 0 &&
          visibleTodayIntradayMeta.regularPointCount > 0
        ? t("usStockDetail.extendedHours.extendedMissingRegularAvailable", {
            count: visibleTodayIntradayMeta.regularPointCount,
          })
        : null;
  const intradaySessionWarning =
    intradaySessionScope !== "regular" &&
    chartLoadState === "success" &&
    !visibleTodayIntradayMeta.hasExtendedHours
      ? t("usStockDetail.extendedHours.noExtendedData")
      : intradayWarningMessage(t, visibleTodayIntradayMeta.warnings);
  const visibleCurrentSourcePresentation = intradaySourcePresentation(
    t,
    visibleTodayIntradayMeta.currentSourceStatus
  );
  const visibleBarSourcePresentation = intradaySourcePresentation(
    t,
    visibleTodayIntradayMeta.barSourceStatus
  );
  const professionalTimeframeLabel = timeframeLabel(t, professionalTimeframe);
  const professionalChartReady =
    chartFocusMode &&
    professionalChartData.length > 0 &&
    chartLoadState !== "loading";
  const professionalLatestClose =
    chartFocusMode && professionalIsIntraday
      ? latestProfessionalPoint?.close ?? latestClose
      : latestClose;
  const professionalDrawingContext = useMemo(
    () => ({
      symbol: selectedSymbol,
      market: "US",
      timeframe: professionalTimeframe,
    }),
    [professionalTimeframe, selectedSymbol]
  );

  useEffect(() => {
    onChartFocusModeChange?.(chartFocusMode);
  }, [chartFocusMode, onChartFocusModeChange]);

  useEffect(() => {
    return () => onChartFocusModeChange?.(false);
  }, [onChartFocusModeChange]);

  useEffect(() => {
    if (!selectedSymbol) return;

    setDataStatusFocus({
      market: "us",
      contextKey: dataStatusContextKey,
      label: dataStatusContextLabel,
      source: dataStatusSource,
    });

    return () => clearDataStatusFocus(dataStatusContextKey);
  }, [dataStatusContextKey, dataStatusContextLabel, dataStatusSource, selectedSymbol]);

  useEffect(() => {
    if (
      !selectedSymbol ||
      selectedIndexConfig ||
      !corporateEventSummary ||
      corporateEventSummary.symbol !== selectedSymbol.toUpperCase()
    ) {
      return;
    }

    emitDataStatusEvent({
      market: "us",
      level: corporateEventSummary.warning ? "warning" : "success",
      title: corporateEventSummary.warning
        ? t("settings.calendar.status.warningTitle")
        : t("settings.calendar.status.successTitle"),
      message:
        corporateEventSummary.warning ??
        t("settings.calendar.status.stockSuccessMessage", {
          count: corporateEventSummary.result_count,
          stock: dataStatusContextLabel,
        }),
      source: t("settings.calendar.status.usSource"),
      contextKey: dataStatusContextKey,
      contextLabel: dataStatusContextLabel,
      dedupeKey: `${dataStatusContextKey}:corporate-events`,
    });
  }, [
    corporateEventSummary,
    dataStatusContextKey,
    dataStatusContextLabel,
    selectedIndexConfig,
    selectedSymbol,
    t,
  ]);

  const secCoverageStatus: CoverageStatus =
    factLoadState === "loading"
      ? "loading"
      : financialContract?.quality.freshness === "stale"
        ? "stale"
        : financialContract?.quality.decision_usable
          ? "ready"
          : financialContract || factRows.length > 0 || fundamentalMetrics.length > 0
            ? "partial"
            : "missing";
  const secCoverageDetail = financialContract
    ? `${financialContract.contract_version} / ${financialContract.quality.freshness} / ${latestFundamentalFiledDate}`
    : factRows.length > 0 || fundamentalMetrics.length > 0
      ? t("usStockDetail.coverage.details.secMetrics", {
          count: fundamentalMetrics.length,
          date:
            latestFundamentalFiledDate !== "-"
              ? latestFundamentalFiledDate
              : latestFactFiledDate,
        })
      : t("usStockDetail.coverage.details.noSecFacts");
  const insiderCoverageStatus: CoverageStatus =
    factLoadState === "loading"
      ? "loading"
      : insiderTransactions?.status === "current" ||
          insiderTransactions?.status === "ready_empty"
        ? "ready"
        : insiderTransactions?.status === "stale"
          ? "stale"
          : insiderTransactions?.status === "partial"
            ? "partial"
            : "missing";
  const insiderCoverageDetail = insiderTransactions
    ? t("usStockDetail.coverage.details.form4", {
        count: insiderTransactions.summary.transaction_count,
        date: formatDate(insiderTransactions.freshness.last_checked_at),
      })
    : t("usStockDetail.coverage.details.noForm4Observation");
  const institutionalCoverageStatus: CoverageStatus =
    factLoadState === "loading"
      ? "loading"
      : institutionalHoldings?.quality.decision_usable
        ? institutionalHoldings.status === "partial"
          ? "partial"
          : "ready"
        : institutionalHoldings
          ? "partial"
          : "missing";
  const institutionalCoverageDetail = institutionalHoldings?.quarters.length
    ? t("usStockDetail.institutions.coverage", {
        count: institutionalHoldings.summary.reporting_manager_count ?? 0,
        date: formatDate(institutionalHoldings.summary.report_period_end),
      })
    : t("usStockDetail.institutions.unavailable");

  const dataCoverageItems: Array<{
    label: string;
    status: CoverageStatus;
    detail: string;
  }> = selectedIndexConfig
    ? [
        {
          label: "OHLC",
          status: coverageStatus(chartData.length > 0, chartLoadState, latestPoint?.time, 10),
          detail:
            chartData.length > 0
              ? t("usStockDetail.coverage.details.bars", {
                  count: chartData.length,
                  date: formatDate(latestPoint?.time),
                })
              : t("usStockDetail.coverage.details.noIndexBars"),
        },
        {
          label: t("usStockDetail.coverage.labels.intraday"),
          status:
            timeframe === "today"
              ? coverageStatus(visibleTodayTrend.length > 0, chartLoadState, latestToday?.time, 2)
              : "ready",
          detail:
            timeframe === "today"
              ? t("usStockDetail.coverage.details.points", {
                  count: visibleTodayTrend.length,
                  time: visibleTodayUpdatedAt ?? "-",
                })
              : t("usStockDetail.coverage.details.availableToday"),
        },
        {
          label: t("usStockDetail.coverage.labels.source"),
          status: "ready",
          detail: t("usStockDetail.coverage.details.yahooChartIndex"),
        },
      ]
    : [
        {
          label: t("usStockDetail.coverage.labels.price"),
          status: coverageStatus(chartData.length > 0, chartLoadState, latestPoint?.time, 10),
          detail:
            chartData.length > 0
              ? t("usStockDetail.coverage.details.bars", {
                  count: chartData.length,
                  date: formatDate(latestPoint?.time),
                })
              : t("usStockDetail.coverage.details.noOhlcRows"),
        },
        {
          label: t("usStockDetail.coverage.labels.profile"),
          status: coverageStatus(Boolean(companyProfile), loadState, companyProfile?.fetched_at, 45),
          detail: companyProfile
            ? `${companyProfile.provider} / ${formatDate(companyProfile.fetched_at)}`
            : t("usStockDetail.coverage.details.alphaVantageOverview"),
        },
        {
          label: "SEC",
          status: secCoverageStatus,
          detail: secCoverageDetail,
        },
        {
          label: "Form 4",
          status: insiderCoverageStatus,
          detail: insiderCoverageDetail,
        },
        {
          label: "13F",
          status: institutionalCoverageStatus,
          detail: institutionalCoverageDetail,
        },
        {
          label: t("usStockDetail.coverage.labels.actions"),
          status: coverageStatus(corporateActions.length > 0, loadState),
          detail:
            corporateActions.length > 0
              ? t("usStockDetail.coverage.details.events", {
                  count: corporateActions.length,
                  date: latestActionDate,
                })
              : t("usStockDetail.coverage.details.noDividendSplitRows"),
        },
        {
          label: "Short",
          status: coverageStatus(
            shortVolumeRows.length > 0,
            loadState,
            latestShortVolume?.trade_date,
            10
          ),
          detail: latestShortVolume
            ? `${formatRatioAsPct(latestShortVolume.short_ratio)} / ${formatDate(latestShortVolume.trade_date)}`
            : t("usStockDetail.coverage.details.noFinraRows"),
        },
      ];
  const readyCoverageCount = dataCoverageItems.filter(
    (item) => item.status === "ready"
  ).length;

  const clearSupplementalData = useCallback(() => {
    setFactRows([]);
    setFundamentalSummary(null);
    setFinancialContract(null);
    setCompanyProfile(null);
    onCompanyProfileChange?.(null);
    setCorporateActions([]);
    setCorporateEventSummary(null);
    setShortVolumeRows([]);
    setInsiderTransactions(null);
    setInstitutionalHoldings(null);
  }, [onCompanyProfileChange]);

  const loadStockIdentity = useCallback(
    async (symbol: string, generation: number) => {
      if (getUsMarketIndexConfig(symbol)) {
        if (requestSeq.current === generation) setSelectedStock(null);
        return;
      }
      try {
        const stockData = await fetchJson<USStockMasterRead>(
          `/api/us-market/stocks/${encodeURIComponent(symbol)}`
        );
        if (requestSeq.current === generation) setSelectedStock(stockData);
      } catch (error) {
        if (requestSeq.current !== generation) return;
        setSelectedStock(null);
        publishDetailDataStatus(tRef.current("usStockDetail.errors.loadFailed"), error);
      }
    },
    [publishDetailDataStatus]
  );

  const loadChartData = useCallback(
    async (symbol: string, nextTimeframe: USChartTimeframe) => {
      const generation = requestSeq.current;
      const requestId = chartRequestSeq.current + 1;
      chartRequestSeq.current = requestId;
      setLoadState("loading");

      const historicalTimeframe: USHistoricalTimeframe =
        nextTimeframe === "today" ? "daily" : nextTimeframe;
      const indexConfig = getUsMarketIndexConfig(symbol);
      const requestedBars =
        indexConfig && nextTimeframe === "today" ? 90 : barsByTimeframe[historicalTimeframe];
      const outputsize =
        indexConfig && nextTimeframe !== "today"
          ? "full"
          : historicalTimeframe === "monthly"
            ? "full"
            : "compact";

      try {
        const chartDataResponse = await fetchJson<USOhlcChartRead>(
          `/api/us-market/ohlc/${encodeURIComponent(symbol)}`,
          {
            timeframe: historicalTimeframe,
            bars: requestedBars,
            ensure_history: false,
            outputsize,
          }
        );
        if (
          requestSeq.current !== generation ||
          chartRequestSeq.current !== requestId
        ) {
          return;
        }
        if (chartDataResponse.backfill) onDailyPricesChangedRef.current?.();
        setChart(chartDataResponse);
        setLoadState("success");
      } catch (error) {
        if (
          requestSeq.current !== generation ||
          chartRequestSeq.current !== requestId
        ) {
          return;
        }
        setChart(null);
        setLoadState("error");
        publishDetailDataStatus(tRef.current("usStockDetail.errors.loadFailed"), error);
      }
    },
    [publishDetailDataStatus]
  );

  const loadSupplementalData = useCallback(
    async (symbol: string, generation: number, tab: USFundamentalTab) => {
      const requestId = supplementalRequestSeq.current + 1;
      supplementalRequestSeq.current = requestId;
      const loadKey = `${usSymbolKey(symbol)}:${tab}`;
      if (getUsMarketIndexConfig(symbol)) {
        clearSupplementalData();
        setFactLoadState("success");
        return;
      }

      setFactLoadState("loading");
      try {
        const supplementalData = await fetchUsSupplementalData(symbol, tab);
        if (
          requestSeq.current !== generation ||
          supplementalRequestSeq.current !== requestId
        ) {
          return;
        }
        if (supplementalData.factData !== undefined) setFactRows(supplementalData.factData);
        if (supplementalData.fundamentalData !== undefined) {
          setFundamentalSummary(supplementalData.fundamentalData);
        }
        if (supplementalData.financialData !== undefined) {
          setFinancialContract(supplementalData.financialData);
        }
        if (supplementalData.profileData !== undefined) {
          setCompanyProfile(supplementalData.profileData);
          onCompanyProfileChange?.(supplementalData.profileData);
        }
        if (supplementalData.actionData !== undefined) {
          setCorporateActions(supplementalData.actionData);
        }
        if (supplementalData.eventSummaryData !== undefined) {
          setCorporateEventSummary(supplementalData.eventSummaryData);
        }
        if (supplementalData.shortVolumeData !== undefined) {
          setShortVolumeRows(supplementalData.shortVolumeData);
        }
        if (supplementalData.insiderData !== undefined) {
          setInsiderTransactions(supplementalData.insiderData);
        }
        if (supplementalData.institutionalData !== undefined) {
          setInstitutionalHoldings(supplementalData.institutionalData);
        }
        if (supplementalData.eventSummaryError) {
          publishDetailDataStatus(
            tRef.current("settings.calendar.loadError"),
            supplementalData.eventSummaryError
          );
        }
        if (supplementalData.insiderError) {
          publishDetailDataStatus(
            tRef.current("usStockDetail.errors.insiderLoadFailed"),
            supplementalData.insiderError
          );
        }
        if (supplementalData.institutionalError) {
          publishDetailDataStatus(
            tRef.current("usStockDetail.institutions.loadFailed"),
            supplementalData.institutionalError
          );
        }
        supplementalLoadedKeysRef.current.add(loadKey);
        setFactLoadState("success");
      } catch (error) {
        if (
          requestSeq.current !== generation ||
          supplementalRequestSeq.current !== requestId
        ) {
          return;
        }
        supplementalLoadedKeysRef.current.delete(loadKey);
        setFactLoadState("error");
        publishDetailDataStatus(tRef.current("usStockDetail.errors.loadFailed"), error);
      }
    },
    [clearSupplementalData, onCompanyProfileChange, publishDetailDataStatus]
  );

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const generation = requestSeq.current + 1;
      requestSeq.current = generation;
      chartRequestSeq.current += 1;
      supplementalRequestSeq.current += 1;
      supplementalLoadedKeysRef.current.clear();
      setSuccessMessage(null);
      setSelectedStock(null);
      setChart(null);
      setHeadlineQuote(null);
      setTodayTrend([]);
      setTodayPreviousClose(null);
      setTodayPreviousCloseStatus("unknown");
      setTodaySource("unavailable");
      setTodayUpdatedAt(null);
      setTodayIntradayMeta(emptyUsIntradayMeta);
      setTodaySymbol(null);
      setTodaySessionScope(null);
      clearSupplementalData();

      if (!selectedSymbol) {
        setLoadState("idle");
        setFactLoadState("idle");
        return;
      }

      void loadStockIdentity(selectedSymbol, generation);
    }, 0);

    return () => window.clearTimeout(timer);
  }, [clearSupplementalData, loadStockIdentity, selectedSymbol]);

  useEffect(() => {
    if (
      !selectedSymbol ||
      selectedIndexConfig ||
      !chartMatchesSelection ||
      factLoadState === "loading"
    ) {
      return;
    }
    const loadKey = `${usSymbolKey(selectedSymbol)}:${activeDataTab}`;
    if (supplementalLoadedKeysRef.current.has(loadKey)) return;
    const timer = window.setTimeout(() => {
      void loadSupplementalData(selectedSymbol, requestSeq.current, activeDataTab);
    }, 200);
    return () => window.clearTimeout(timer);
  }, [
    activeDataTab,
    chartMatchesSelection,
    factLoadState,
    loadSupplementalData,
    selectedIndexConfig,
    selectedSymbol,
  ]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      if (!selectedSymbol) return;
      void loadChartData(selectedSymbol, timeframe);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [loadChartData, selectedSymbol, timeframe]);

  useEffect(() => {
    if (!selectedSymbol || !chartMatchesSelection || !chart) return;

    const coverageDedupeKey = `${dataStatusContextKey}:ohlc:${chart.timeframe}`;
    const coverageSignature = [
      chart.coverage_status,
      chart.continuity_status,
      chart.history_status,
      chart.expected_data_date,
      chart.latest_finalized_data_date,
      chart.missing_trade_date_count,
      chart.previous_close_status,
    ].join(":");
    const previousSignature = ohlcCoverageEventStateRef.current.get(coverageDedupeKey);

    if (previousSignature !== coverageSignature) {
      ohlcCoverageEventStateRef.current.set(coverageDedupeKey, coverageSignature);
      if (chart.coverage_status === "best_available") {
        emitDataStatusEvent({
          market: "us",
          level: "info",
          title: t("usStockDetail.ohlcCoverage.bestAvailableTitle"),
          message: t("usStockDetail.ohlcCoverage.bestAvailableMessage", {
            available: chart.available_bar_count,
            requested: chart.requested_bar_count,
          }),
          source: dataStatusSource,
          contextKey: dataStatusContextKey,
          contextLabel: dataStatusContextLabel,
          dedupeKey: coverageDedupeKey,
        });
      } else if (
        chart.continuity_status !== "complete" ||
        (chart.timeframe === "daily" && chart.previous_close_status !== "current")
      ) {
        emitDataStatusEvent({
          market: "us",
          level: "warning",
          title: t("usStockDetail.ohlcCoverage.incompleteTitle"),
          message: t("usStockDetail.ohlcCoverage.incompleteMessage", {
            expected: chart.expected_data_date ?? "-",
            latest: chart.latest_finalized_data_date ?? "-",
            count: chart.missing_trade_date_count,
            dates: (chart.missing_trade_dates ?? []).join(", ") || "-",
          }),
          source: dataStatusSource,
          contextKey: dataStatusContextKey,
          contextLabel: dataStatusContextLabel,
          dedupeKey: coverageDedupeKey,
        });
      } else if (chart.history_status !== "complete") {
        emitDataStatusEvent({
          market: "us",
          level: "warning",
          title: t("usStockDetail.ohlcCoverage.historyIncompleteTitle"),
          message: t("usStockDetail.ohlcCoverage.historyIncompleteMessage", {
            available: chart.available_bar_count,
            requested: chart.requested_bar_count,
          }),
          source: dataStatusSource,
          contextKey: dataStatusContextKey,
          contextLabel: dataStatusContextLabel,
          dedupeKey: coverageDedupeKey,
        });
      } else if (previousSignature && !previousSignature.startsWith("complete:")) {
        emitDataStatusEvent({
          market: "us",
          level: "success",
          title: t("usStockDetail.ohlcCoverage.repairedTitle"),
          message: t("usStockDetail.ohlcCoverage.repairedMessage"),
          source: dataStatusSource,
          contextKey: dataStatusContextKey,
          contextLabel: dataStatusContextLabel,
          dedupeKey: coverageDedupeKey,
        });
      }
    }

  }, [
    chart,
    chartMatchesSelection,
    dataStatusContextKey,
    dataStatusContextLabel,
    dataStatusSource,
    selectedSymbol,
    t,
  ]);

  useEffect(() => {
    if (!selectedSymbol) return;

    let cancelled = false;
    let quoteTimer: number | undefined;
    let quoteRequestInFlight = false;
    const symbol = selectedSymbol;

    async function refreshHeadlineQuote() {
      if (quoteRequestInFlight) return;
      quoteRequestInFlight = true;
      try {
        const snapshot = await fetchJson<USResolvedQuoteSnapshot>(
          `/api/us-market/quote/${encodeURIComponent(symbol)}`
        );
        if (!cancelled) setHeadlineQuote(snapshot);
      } catch (error) {
        if (!cancelled) {
          publishDetailDataStatus(
            tRef.current("usStockDetail.errors.intradayRefreshFailed"),
            error
          );
        }
      } finally {
        quoteRequestInFlight = false;
      }
    }

    function scheduleQuoteRefresh() {
      if (cancelled) return;
      const marketState = getUsMarketRefreshState();
      const delay = marketState.isLiveWindow
        ? US_INTRADAY_REFRESH_MS
        : Math.min(marketState.msUntilNextPollingStart, 60_000);
      quoteTimer = window.setTimeout(() => {
        void refreshHeadlineQuote().finally(scheduleQuoteRefresh);
      }, delay);
    }

    quoteTimer = window.setTimeout(() => {
      void refreshHeadlineQuote().finally(scheduleQuoteRefresh);
    }, 0);
    return () => {
      cancelled = true;
      if (quoteTimer !== undefined) window.clearTimeout(quoteTimer);
    };
  }, [publishDetailDataStatus, selectedSymbol]);

  useEffect(() => {
    if (!selectedSymbol || timeframe !== "today") return;

    let cancelled = false;
    let intradayTimer: number | undefined;
    let intradayRequestInFlight = false;
    const symbol = selectedSymbol;

    function clearIntradayTimer() {
      if (intradayTimer !== undefined) {
        window.clearTimeout(intradayTimer);
        intradayTimer = undefined;
      }
    }

    async function refreshTodayTrend() {
      if (intradayRequestInFlight) return;
      intradayRequestInFlight = true;

      try {
        const today = await fetchUsIntradayTrend(symbol, intradaySessionScope);

        if (cancelled) return;

        const safeTodayPoints = currentSessionTrendPoints(today);
        const latestIntradayPoint =
          safeTodayPoints[safeTodayPoints.length - 1] ?? null;

        setTodayTrend(safeTodayPoints);
        setTodayPreviousClose(today.previous_close);
        setTodayPreviousCloseStatus(today.previous_close_status ?? "unknown");
        setTodaySource(today.source);
        setTodayUpdatedAt(
          latestIntradayPoint ? formatDateTime(latestIntradayPoint.time) : null
        );
        setTodayIntradayMeta(intradayMetaFromResponse(today));
        setTodaySymbol(symbol);
        setTodaySessionScope(intradaySessionScope);
        publishIntradaySourceStatus(symbol, today);
        const marketState = getUsMarketRefreshState();
        if (marketState.isAfterClose) {
          finalIntradayRefreshDate.current = marketState.dateKey;
        }
      } catch (error) {
        if (cancelled) return;

        publishDetailDataStatus(
          tRef.current("usStockDetail.errors.intradayRefreshFailed"),
          error
        );
      } finally {
        intradayRequestInFlight = false;
      }
    }

    function scheduleTodayRefresh() {
      if (cancelled) return;

      const marketState = getUsMarketRefreshState();

      if (marketState.isLiveWindow) {
        intradayTimer = window.setTimeout(() => {
          void refreshTodayTrend().finally(scheduleTodayRefresh);
        }, US_INTRADAY_REFRESH_MS);
        return;
      }

      if (
        marketState.isAfterClose &&
        finalIntradayRefreshDate.current !== marketState.dateKey
      ) {
        finalIntradayRefreshDate.current = marketState.dateKey;
        intradayTimer = window.setTimeout(() => {
          void refreshTodayTrend().finally(scheduleTodayRefresh);
        }, 0);
        return;
      }

      intradayTimer = window.setTimeout(
        scheduleTodayRefresh,
        Math.min(marketState.msUntilNextPollingStart, 60_000)
      );
    }

    intradayTimer = window.setTimeout(() => {
      void refreshTodayTrend().finally(scheduleTodayRefresh);
    }, 0);

    return () => {
      cancelled = true;
      clearIntradayTimer();
    };
  }, [
    intradaySessionScope,
    publishDetailDataStatus,
    publishIntradaySourceStatus,
    selectedSymbol,
    timeframe,
  ]);

  useEffect(() => {
    let cancelled = false;
    if (!selectedSymbol) {
      return;
    }
    const symbol = selectedSymbol;

    void fetchJson<USMarketResearchRead>(
      `/api/us-market/research/${encodeURIComponent(symbol)}`,
      { bars: 260 }
    )
      .then((research) => {
        if (cancelled) return;
        setMarketResearch(research);
      })
      .catch((error) => {
        if (cancelled) return;
        publishDetailDataStatus(
          tRef.current("usStockDetail.errors.technicalResearchLoadFailed"),
          error
        );
      });

    return () => {
      cancelled = true;
    };
  }, [publishDetailDataStatus, selectedSymbol]);

  useEffect(() => {
    let cancelled = false;
    if (
      !selectedSymbol ||
      !chartFocusMode ||
      !isUsProfessionalIntradayTimeframe(professionalTimeframe)
    ) {
      return;
    }
    const symbol = selectedSymbol;

    void fetchUsIntradayTrend(
      symbol,
      intradaySessionScope,
      professionalTimeframe
    )
      .then((response) => {
        if (cancelled) return;
        setProfessionalIntraday(response);
        publishIntradaySourceStatus(symbol, response);
      })
      .catch((error) => {
        if (cancelled) return;
        publishDetailDataStatus(
          tRef.current("usStockDetail.errors.intradayAggregationFailed"),
          error
        );
      });

    return () => {
      cancelled = true;
    };
  }, [
    chartFocusMode,
    intradaySessionScope,
    professionalTimeframe,
    publishDetailDataStatus,
    publishIntradaySourceStatus,
    selectedSymbol,
  ]);

  const queueChartDrawingRemoteSave = useCallback((
    drawingsToSave: ChartDrawing[],
    selectedDrawingIdToSave: string | null
  ) => {
    if (typeof window === "undefined") return;
    if (!selectedSymbol) return;

    const path = chartDrawingApiPath("US", selectedSymbol, professionalTimeframe);
    const payload = buildChartDrawingSnapshotPayload({
      drawings: drawingsToSave,
      market: "US",
      selectedDrawingId: selectedDrawingIdToSave,
      source: "frontend.us_professional_chart",
      stockName: selectedDisplayName,
      symbol: selectedSymbol,
      timeframe: professionalTimeframe,
      timeMode: chartDrawingTimeMode(professionalTimeframe),
    });

    if (chartDrawingSyncTimerRef.current) {
      window.clearTimeout(chartDrawingSyncTimerRef.current);
    }

    chartDrawingSyncTimerRef.current = window.setTimeout(() => {
      void requestJson<ChartDrawingSnapshotRead>(path, {
        method: "PUT",
        body: JSON.stringify(payload),
      }).catch(() => {
        // Best-effort server sync. Local chart drawings remain available via localStorage.
      });
    }, chartDrawingSyncDelayMs);
  }, [professionalTimeframe, selectedDisplayName, selectedSymbol]);

  const storeChartDrawings = useCallback((
    drawingsToSave: ChartDrawing[],
    selectedDrawingIdToSave = activeSelectedChartDrawingId
  ) => {
    chartDrawingLocalRevisionRef.current += 1;
    setChartDrawingState({
      key: chartDrawingKey,
      drawings: drawingsToSave,
    });
    saveChartDrawings(chartDrawingKey, drawingsToSave);
    queueChartDrawingRemoteSave(drawingsToSave, selectedDrawingIdToSave);
  }, [
    activeSelectedChartDrawingId,
    chartDrawingKey,
    queueChartDrawingRemoteSave,
  ]);

  useEffect(() => {
    return () => {
      if (chartDrawingSyncTimerRef.current && typeof window !== "undefined") {
        window.clearTimeout(chartDrawingSyncTimerRef.current);
      }
    };
  }, []);

  useEffect(() => {
    if (!chartFocusMode || !selectedSymbol) {
      return;
    }
    if (chartDrawingState.key === chartDrawingKey) return;

    let cancelled = false;
    const remoteSymbol = selectedSymbol;
    const loadRevision = chartDrawingLocalRevisionRef.current;
    const hasLocalSnapshot = hasChartDrawingSnapshot(chartDrawingKey);
    const localDrawings = loadChartDrawings(chartDrawingKey);
    const normalizedLocalSelection = normalizeChartDrawingSelection(
      localDrawings,
      activeSelectedChartDrawingId
    );

    if (hasLocalSnapshot) {
      void Promise.resolve().then(() => {
        if (cancelled || chartDrawingLocalRevisionRef.current !== loadRevision) return;

        setChartDrawingState({
          key: chartDrawingKey,
          drawings: localDrawings,
        });
        setSelectedChartDrawingId(normalizedLocalSelection);

        if (localDrawings.length > 0) {
          queueChartDrawingRemoteSave(localDrawings, normalizedLocalSelection);
        }
      });

      return () => {
        cancelled = true;
      };
    }

    async function loadRemoteChartDrawings() {
      try {
        const snapshot = await fetchJson<ChartDrawingSnapshotRead>(
          chartDrawingApiPath("US", remoteSymbol, professionalTimeframe)
        );

        if (cancelled || chartDrawingLocalRevisionRef.current !== loadRevision) return;

        const remoteDrawings = normalizeStoredChartDrawings(snapshot.drawings);
        if (remoteDrawings.length === 0) {
          setChartDrawingState({
            key: chartDrawingKey,
            drawings: [],
          });
          setSelectedChartDrawingId(null);
          return;
        }

        const remoteSelection = normalizeChartDrawingSelection(
          remoteDrawings,
          snapshot.selected_drawing_id
        );

        setChartDrawingState({
          key: chartDrawingKey,
          drawings: remoteDrawings,
        });
        saveChartDrawings(chartDrawingKey, remoteDrawings);
        setSelectedChartDrawingId(remoteSelection);
      } catch {
        // A missing remote snapshot simply means this chart has not been saved server-side yet.
      }
    }

    void loadRemoteChartDrawings();

    return () => {
      cancelled = true;
    };
  }, [
    activeSelectedChartDrawingId,
    chartDrawingState.key,
    chartDrawingKey,
    chartFocusMode,
    professionalTimeframe,
    queueChartDrawingRemoteSave,
    selectedSymbol,
  ]);

  function updateChartDrawingState(
    nextValue: ChartDrawing[] | ((current: ChartDrawing[]) => ChartDrawing[]),
    nextSelectedDrawingId?: string | null,
    options: { recordHistory?: boolean } = {}
  ) {
    const nextDrawings =
      typeof nextValue === "function" ? nextValue(chartDrawings) : nextValue;
    const currentSnapshot = createChartDrawingSnapshot(
      chartDrawings,
      activeSelectedChartDrawingId
    );
    const nextSnapshot = createChartDrawingSnapshot(
      nextDrawings,
      nextSelectedDrawingId === undefined
        ? activeSelectedChartDrawingId
        : nextSelectedDrawingId
    );

    if (chartDrawingSnapshotsEqual(currentSnapshot, nextSnapshot)) {
      return;
    }

    if (
      serializeChartDrawings(currentSnapshot.drawings) ===
      serializeChartDrawings(nextSnapshot.drawings)
    ) {
      setSelectedChartDrawingId(nextSnapshot.selectedDrawingId);
      return;
    }

    if (options.recordHistory !== false) {
      const currentPast =
        chartDrawingHistoryState.key === chartDrawingKey ? chartDrawingHistoryState.past : [];

      setChartDrawingHistoryState({
        key: chartDrawingKey,
        past: [...currentPast, currentSnapshot].slice(-50),
        future: [],
      });
    }

    storeChartDrawings(nextSnapshot.drawings, nextSnapshot.selectedDrawingId);
    setSelectedChartDrawingId(nextSnapshot.selectedDrawingId);
  }

  function updateChartDrawings(
    nextValue: ChartDrawing[] | ((current: ChartDrawing[]) => ChartDrawing[]),
    options: { recordHistory?: boolean } = {}
  ) {
    updateChartDrawingState(nextValue, undefined, options);
  }

  const undoChartDrawing = useCallback(() => {
    if (!canUndoChartDrawing) return;

    const past = chartDrawingHistory.past;
    const previousSnapshot = past[past.length - 1];

    if (!previousSnapshot) return;

    setChartDrawingHistoryState({
      key: chartDrawingKey,
      past: past.slice(0, -1),
      future: [
        createChartDrawingSnapshot(chartDrawings, activeSelectedChartDrawingId),
        ...chartDrawingHistory.future,
      ].slice(0, 50),
    });
    storeChartDrawings(previousSnapshot.drawings, previousSnapshot.selectedDrawingId);
    setSelectedChartDrawingId(previousSnapshot.selectedDrawingId);
  }, [
    activeSelectedChartDrawingId,
    canUndoChartDrawing,
    chartDrawingHistory.future,
    chartDrawingHistory.past,
    chartDrawingKey,
    chartDrawings,
    storeChartDrawings,
  ]);

  const redoChartDrawing = useCallback(() => {
    if (!canRedoChartDrawing) return;

    const nextDrawings = chartDrawingHistory.future[0];

    if (!nextDrawings) return;

    setChartDrawingHistoryState({
      key: chartDrawingKey,
      past: [
        ...chartDrawingHistory.past,
        createChartDrawingSnapshot(chartDrawings, activeSelectedChartDrawingId),
      ].slice(-50),
      future: chartDrawingHistory.future.slice(1),
    });
    storeChartDrawings(nextDrawings.drawings, nextDrawings.selectedDrawingId);
    setSelectedChartDrawingId(nextDrawings.selectedDrawingId);
  }, [
    activeSelectedChartDrawingId,
    canRedoChartDrawing,
    chartDrawingHistory.future,
    chartDrawingHistory.past,
    chartDrawingKey,
    chartDrawings,
    storeChartDrawings,
  ]);

  useEffect(() => {
    if (!chartFocusMode) return;

    function handleChartDrawingHistoryKeyDown(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      const tagName = target?.tagName.toLowerCase();

      if (tagName === "input" || tagName === "textarea" || target?.isContentEditable) return;
      if (!event.ctrlKey && !event.metaKey) return;

      const key = event.key.toLowerCase();

      if (key === "z" && !event.shiftKey) {
        if (!canUndoChartDrawing) return;

        event.preventDefault();
        undoChartDrawing();
        return;
      }

      if (key === "y" || (key === "z" && event.shiftKey)) {
        if (!canRedoChartDrawing) return;

        event.preventDefault();
        redoChartDrawing();
      }
    }

    window.addEventListener("keydown", handleChartDrawingHistoryKeyDown);

    return () => window.removeEventListener("keydown", handleChartDrawingHistoryKeyDown);
  }, [
    canRedoChartDrawing,
    canUndoChartDrawing,
    chartFocusMode,
    redoChartDrawing,
    undoChartDrawing,
  ]);

  function toggleIntradayIndicator(key: IntradayIndicatorKey) {
    setIntradayIndicators((current) => ({
      ...current,
      [key]: !current[key],
    }));
  }

  function toggleChartIndicator(key: IndicatorKey) {
    setChartIndicators((current) => ({
      ...current,
      [key]: !current[key],
    }));
    setActiveIndicatorTemplate(null);
  }

  function applyIndicatorTemplate(templateKey: IndicatorTemplateKey) {
    const template = indicatorTemplates.find((item) => item.key === templateKey);
    if (!template) return;

    setActiveIndicatorTemplate(template.key);
    setChartIndicators(template.indicators);
    setIndicatorParameters({
      ...defaultIndicatorParameters,
      ...(template.parameters ?? {}),
    });
  }

  function handleIndicatorParameterChange(
    key: keyof IndicatorParameters,
    value: string,
    min: number,
    max: number
  ) {
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return;

    setActiveIndicatorTemplate(null);
    setIndicatorParameters((current) => ({
      ...current,
      [key]: Math.max(min, Math.min(max, parsed)),
    }));
  }

  function handleProfessionalTimeframeChange(nextTimeframe: USProfessionalTimeframe) {
    setProfessionalTimeframe(nextTimeframe);
    setIndicatorMenuOpen(false);
    setTimeframe(isUsProfessionalIntradayTimeframe(nextTimeframe) ? "today" : nextTimeframe);
  }

  function enterChartFocusMode() {
    const nextTimeframe: USProfessionalTimeframe =
      timeframe === "today" ? "1m" : timeframe;

    setProfessionalTimeframe(nextTimeframe);
    setTimeframe(isUsProfessionalIntradayTimeframe(nextTimeframe) ? "today" : nextTimeframe);
    setIndicatorMenuOpen(false);
    setChartFocusMode(true);
  }

  function deleteSelectedChartDrawing() {
    if (!activeSelectedChartDrawingId) return;

    updateChartDrawings((current) =>
      current.filter((drawing) => drawing.id !== activeSelectedChartDrawingId)
    );
    setSelectedChartDrawingId(null);
  }

  function clearChartDrawings() {
    if (chartDrawings.length === 0) return;
    if (!window.confirm(t("usStockDetail.confirm.clearDrawings"))) return;

    updateChartDrawings([]);
    setSelectedChartDrawingId(null);
  }

  async function refreshFacts() {
    if (!selectedSymbol) return;

    setRefreshingFacts(true);
    setSuccessMessage(null);

    try {
      const result = await requestJson<USSecFactRefreshResultRead>(
        `/api/us-market/sec/${encodeURIComponent(selectedSymbol)}/refresh-facts`,
        { method: "POST" }
      );

      setSuccessMessage({
        text: t("usStockDetail.messages.secFactsRefreshSuccess", {
          symbol: result.symbol,
          fetched: result.fetched_count,
        }),
      });
      await loadSupplementalData(selectedSymbol, requestSeq.current, activeDataTab);
    } catch (error) {
      publishDetailDataStatus(t("usStockDetail.errors.secFactsRefreshFailed"), error);
    } finally {
      setRefreshingFacts(false);
    }
  }

  async function refreshProfile() {
    if (!selectedSymbol) return;

    setRefreshingProfile(true);
    setSuccessMessage(null);

    try {
      const result = await requestJson<USResourceRefreshResultRead>(
        `/api/us-market/profiles/${encodeURIComponent(selectedSymbol)}/refresh`,
        { method: "POST" }
      );

      setSuccessMessage({
        text: t("usStockDetail.messages.profileRefreshSuccess", {
          symbol: result.symbol ?? selectedSymbol,
          fetched: result.fetched_count,
        }),
      });
      await loadSupplementalData(selectedSymbol, requestSeq.current, "overview");
    } catch (error) {
      publishDetailDataStatus(t("usStockDetail.errors.profileRefreshFailed"), error);
    } finally {
      setRefreshingProfile(false);
    }
  }

  async function refreshActions() {
    if (!selectedSymbol) return;

    setRefreshingActions(true);
    setSuccessMessage(null);

    try {
      const result = await requestJson<USResourceRefreshResultRead>(
        `/api/us-market/corporate-actions/${encodeURIComponent(selectedSymbol)}/refresh`,
        { method: "POST" }
      );

      setSuccessMessage({
        text: t("usStockDetail.messages.actionsRefreshSuccess", {
          symbol: result.symbol ?? selectedSymbol,
          fetched: result.fetched_count,
        }),
      });
      await loadSupplementalData(selectedSymbol, requestSeq.current, "filings");
    } catch (error) {
      publishDetailDataStatus(t("usStockDetail.errors.actionsRefreshFailed"), error);
    } finally {
      setRefreshingActions(false);
    }
  }

  async function refreshInsiderTransactions() {
    if (!selectedSymbol) return;

    const symbol = selectedSymbol;
    const requestId = requestSeq.current;
    setRefreshingInsiders(true);
    setSuccessMessage(null);

    try {
      await requestBackfillJob(
        "/api/us-market/sec/ownership/jobs/form4-sync",
        {
          method: "POST",
          body: JSON.stringify({
            scope: "symbol",
            symbol,
            max_symbols: 1,
            max_filings_per_symbol: 50,
          }),
        },
        undefined,
        { intervalMs: 1_000, timeoutMs: 180_000 }
      );
      const contract = await fetchJson<USSecInsiderTransactionsRead>(
        `/api/us-market/sec/${encodeURIComponent(symbol)}/insider-transactions`,
        { limit: 100 }
      );
      if (requestSeq.current !== requestId) return;

      setInsiderTransactions(contract);
      setSuccessMessage({
        text: t("usStockDetail.messages.insiderRefreshSuccess", {
          symbol,
          fetched: contract.summary.transaction_count,
        }),
      });
    } catch (error) {
      publishDetailDataStatus(
        t("usStockDetail.errors.insiderRefreshFailed"),
        error
      );
    } finally {
      setRefreshingInsiders(false);
    }
  }

  function renderDataPanelAction() {
    if (activeDataTab === "overview") {
      return (
        <button
          type="button"
          onClick={() => void refreshProfile()}
          className="h-8 bg-omi-control px-3 text-xs font-semibold text-omi-text-inverse hover:bg-omi-control-border disabled:bg-omi-border"
          disabled={!selectedSymbol || refreshingProfile}
        >
          {refreshingProfile ? t("common.updating") : t("usStockDetail.actions.profile")}
        </button>
      );
    }

    if (activeDataTab === "financials") {
      return (
        <button
          type="button"
          onClick={() => void refreshFacts()}
          className="h-8 bg-omi-control px-3 text-xs font-semibold text-omi-text-inverse hover:bg-omi-control-border disabled:bg-omi-border"
          disabled={!selectedSymbol || refreshingFacts}
        >
          {refreshingFacts ? t("common.updating") : t("usStockDetail.actions.secFacts")}
        </button>
      );
    }

    if (activeDataTab === "filings") {
      return (
        <div className="flex flex-wrap justify-end gap-2">
          <button
            type="button"
            onClick={() => void refreshFacts()}
            className="h-8 bg-omi-control px-3 text-xs font-semibold text-omi-text-inverse hover:bg-omi-control-border disabled:bg-omi-border"
            disabled={!selectedSymbol || refreshingFacts}
          >
            {refreshingFacts ? t("common.updating") : t("usStockDetail.actions.secFacts")}
          </button>
          <button
            type="button"
            onClick={() => void refreshActions()}
            className="h-8 border border-omi-control bg-omi-surface px-3 text-xs font-semibold text-omi-text hover:border-omi-accent hover:text-omi-danger disabled:border-omi-border-subtle disabled:text-omi-text-subtle"
            disabled={!selectedSymbol || refreshingActions}
          >
            {refreshingActions ? t("common.updating") : t("usStockDetail.actions.actions")}
          </button>
        </div>
      );
    }

    if (activeDataTab === "short") {
      return (
        <div className="border border-omi-border-subtle px-3 py-2 text-xs font-semibold text-omi-text-muted">
          FINRA
        </div>
      );
    }

    if (activeDataTab === "institutions") {
      return (
        <div className="border border-omi-border-subtle px-3 py-2 text-xs font-semibold text-omi-text-muted">
          SEC 13F
        </div>
      );
    }

    if (activeDataTab === "insider") {
      return (
        <button
          type="button"
          onClick={() => void refreshInsiderTransactions()}
          className="h-8 bg-omi-control px-3 text-xs font-semibold text-omi-text-inverse hover:bg-omi-control-border disabled:bg-omi-border"
          disabled={!selectedSymbol || refreshingInsiders}
        >
          {refreshingInsiders
            ? t("common.updating")
            : t("usStockDetail.actions.form4")}
        </button>
      );
    }

    return (
      <div className="border border-omi-border-subtle px-3 py-2 text-xs font-semibold text-omi-text-muted">
        {t("usStockDetail.actions.form4")}
      </div>
    );
  }

  function renderOverviewTab() {
    return (
      <div className="space-y-4">
        <div className="overflow-hidden border border-omi-border-subtle">
          <div className="grid grid-cols-2 gap-px bg-omi-surface-strong text-sm">
            <MetricCell label={t("usStockDetail.metrics.exchange")} value={selectedStock?.exchange ?? "-"} />
            <MetricCell label={t("usStockDetail.metrics.type")} value={assetTypeLabel(t, selectedStock)} />
            <MetricCell label={t("usStockDetail.metrics.cik")} value={selectedStock?.cik ?? "-"} />
            <MetricCell
              label={t("usStockDetail.metrics.marketCap")}
              value={formatCompactCurrency(companyProfile?.market_cap)}
            />
            <MetricCell
              label={t("usStockDetail.metrics.shares")}
              value={
                sharesOutstandingContractMetric
                  ? formatDerivedValue(sharesOutstandingContractMetric)
                  : formatFundamentalValue(sharesOutstandingMetric)
              }
            />
            <MetricCell
              label={t("usStockDetail.metrics.pe")}
              value={
                financialContract?.valuation.status === "ready"
                  ? formatNumber(financialNumber(financialContract.valuation.pe_ttm))
                  : "-"
              }
            />
            <MetricCell
              label={t("usStockDetail.metrics.eps")}
              value={
                epsTtmMetric
                  ? formatDerivedValue(epsTtmMetric, { perShare: true })
                  : formatFundamentalValue(epsDilutedMetric)
              }
            />
            <MetricCell
              label={t("usStockDetail.metrics.revenueTtm")}
              value={
                revenueTtmMetric
                  ? formatDerivedValue(revenueTtmMetric)
                  : formatFundamentalValue(revenueMetric)
              }
            />
            <MetricCell
              label={t("usStockDetail.metrics.netMargin")}
              value={formatDerivedValue(netMarginMetric, { percent: true })}
            />
            <MetricCell label={t("usStockDetail.metrics.secPeriod")} value={latestFundamentalPeriodEnd} />
            <MetricCell label={t("usStockDetail.metrics.latestFiled")} value={latestFundamentalFiledDate} />
          </div>
        </div>

        <div className="border border-omi-border-subtle px-4 py-3 text-xs leading-5 text-omi-text-muted">
          {companyProfile ? (
            <>
              <span className="font-semibold text-omi-text">
                {companyProfile.sector ?? "-"}
              </span>
              {" / "}
              {companyProfile.industry ?? "-"}
              {" · "}
              {t("usStockDetail.metrics.latestQuarter")}
              {" "}
              {formatDate(companyProfile.latest_quarter)}
              {" · "}
              {companyProfile.provider}
            </>
          ) : (
            fundamentalSummary ? (
              <>
                <span className="font-semibold text-omi-text">
                  {fundamentalSummary.entity_name ?? selectedStock?.sec_company_name ?? "-"}
                </span>
                {" · "}
                {t("usStockDetail.messages.secFundamentalsSummary", {
                  count: fundamentalSummary.metric_count,
                  date: latestFundamentalFiledDate,
                })}
              </>
            ) : (
              t("usStockDetail.empty.noCompanyProfile")
            )
          )}
        </div>

      </div>
    );
  }

  function renderInstitutionsTab() {
    if (factLoadState === "loading" && !institutionalHoldings) {
      return (
        <StateSurface
          title={t("usStockDetail.institutions.loading")}
          tone="loading"
          busy
          compact
        />
      );
    }

    if (!institutionalHoldings || institutionalHoldings.quarters.length === 0) {
      return (
        <div className="space-y-3">
          <EmptyDataState message={t("usStockDetail.institutions.unavailable")} />
          {institutionalHoldings?.quality.limitations[0] ? (
            <div className="border border-omi-warning bg-omi-warning-soft px-4 py-3 text-xs leading-5 text-omi-warning-strong">
              {institutionalHoldings.quality.limitations[0]}
            </div>
          ) : null}
        </div>
      );
    }

    const summary = institutionalHoldings.summary;
    const latestPeriod = summary.report_period_end ?? "-";
    const managerMovement = [
      `${t("usStockDetail.institutions.newManagers")} ${summary.new_manager_count ?? "-"}`,
      `${t("usStockDetail.institutions.increasedManagers")} ${summary.increased_manager_count ?? "-"}`,
      `${t("usStockDetail.institutions.reducedManagers")} ${summary.reduced_manager_count ?? "-"}`,
      `${t("usStockDetail.institutions.exitedManagers")} ${summary.exited_manager_count ?? "-"}`,
    ].join(" / ");
    return (
      <div className="space-y-4">
        <div className="flex flex-wrap items-start justify-between gap-3 border border-omi-border-subtle bg-omi-surface-subtle px-4 py-3">
          <div>
            <div className="text-xs font-bold uppercase tracking-wide text-omi-text-muted">
              {institutionalHoldings.contract_version} / {institutionalHoldings.status}
            </div>
            <div className="mt-1 text-sm font-bold text-omi-text-strong">
              {t("usStockDetail.institutions.reportedPeriod")} {formatDate(latestPeriod)}
            </div>
          </div>
          <div className="text-right text-xs leading-5 text-omi-text-muted">
            <div>{t("usStockDetail.institutions.releasePeriod")}: {institutionalHoldings.freshness.latest_release_period ?? "-"}</div>
            <div>{t("usStockDetail.institutions.computedAt")}: {formatDateTime(institutionalHoldings.as_of)}</div>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-px overflow-hidden border border-omi-border-subtle bg-omi-surface-strong md:grid-cols-3">
          <MetricCell
            label={t("usStockDetail.institutions.reportingManagers")}
            value={formatNumber(summary.reporting_manager_count, 0)}
          />
          <MetricCell
            label={t("usStockDetail.institutions.reportedLongShares")}
            value={formatDecimalText(summary.reported_long_shares, 0)}
          />
          <MetricCell
            label={t("usStockDetail.institutions.reportedLongValue")}
            value={formatCompactCurrency(financialNumber(summary.reported_long_value_usd))}
          />
          <MetricCell
            label={t("usStockDetail.institutions.reportedPutValue")}
            value={formatCompactCurrency(financialNumber(summary.reported_put_value_usd))}
          />
          <MetricCell
            label={t("usStockDetail.institutions.reportedCallValue")}
            value={formatCompactCurrency(financialNumber(summary.reported_call_value_usd))}
          />
          <MetricCell
            label={t("usStockDetail.institutions.managerMovement")}
            value={<span className="text-xs leading-5">{managerMovement}</span>}
          />
        </div>

        <div className="border border-omi-warning bg-omi-warning-soft px-4 py-3 text-xs leading-5 text-omi-warning-strong">
          {institutionalHoldings.quality.limitations[0] ?? t("usStockDetail.institutions.limitation")}
        </div>

        <div className="overflow-x-auto border border-omi-border-subtle">
          <div className="grid min-w-[620px] grid-cols-[minmax(0,1fr)_120px_120px_96px] bg-omi-surface-subtle px-4 py-2 text-xs font-bold uppercase tracking-wide text-omi-text-muted">
            <span>{t("usStockDetail.tableHeaders.holder13f")}</span>
            <span className="text-right">{t("usStockDetail.tableHeaders.shares")}</span>
            <span className="text-right">{t("usStockDetail.tableHeaders.value")}</span>
            <span className="text-right">{t("usStockDetail.tableHeaders.qoq")}</span>
          </div>
          {institutionalHoldings.managers.length > 0 ? (
            institutionalHoldings.managers.map((manager) => {
              const change = financialNumber(manager.reported_long_shares_change);
              return (
                <div
                  key={`${manager.manager_cik ?? manager.manager_name}-${manager.report_period_end}`}
                  className="grid min-w-[620px] grid-cols-[minmax(0,1fr)_120px_120px_96px] items-center border-t border-omi-border-subtle px-4 py-3 text-xs"
                >
                  <div className="min-w-0 pr-3">
                    <div className="truncate font-bold text-omi-text-strong">{manager.manager_name}</div>
                    <div className="mt-1 truncate text-[11px] text-omi-text-subtle">CIK {manager.manager_cik ?? "-"}</div>
                  </div>
                  <div className="text-right font-semibold text-omi-text">
                    {formatDecimalText(manager.reported_long_shares, 0)}
                  </div>
                  <div className="text-right font-semibold text-omi-text">
                    {formatCompactCurrency(financialNumber(manager.reported_value_usd))}
                  </div>
                  <div
                    className={`text-right font-bold ${
                      change === null || change === 0
                        ? "text-omi-text-muted"
                        : change > 0
                          ? "text-omi-success-strong"
                          : "text-omi-danger"
                    }`}
                  >
                    {formatSignedDecimalText(manager.reported_long_shares_change)}
                    <div className="mt-0.5 text-[10px] font-semibold uppercase">{manager.direction}</div>
                  </div>
                </div>
              );
            })
          ) : (
            <div className="border-t border-omi-border-subtle p-4">
              <EmptyDataState message={t("usStockDetail.institutions.noManagers")} />
            </div>
          )}
        </div>
      </div>
    );
  }

  function renderInsiderTab() {
    if (factLoadState === "loading" && !insiderTransactions) {
      return (
        <StateSurface
          title={t("usStockDetail.insider.loading")}
          tone="loading"
          busy
          compact
        />
      );
    }

    if (!insiderTransactions) {
      return <EmptyDataState message={t("usStockDetail.empty.noForm4Observation")} />;
    }

    const statusTone =
      insiderTransactions.status === "current" ||
      insiderTransactions.status === "ready_empty"
        ? "border-omi-success-border bg-omi-success-soft text-omi-success-strong"
        : insiderTransactions.status === "stale" ||
            insiderTransactions.status === "partial"
          ? "border-omi-warning-border bg-omi-warning-soft text-omi-warning-strong"
          : "border-omi-danger-border bg-omi-danger-soft text-omi-danger";
    const summary = insiderTransactions.summary;

    return (
      <div className="space-y-4">
        <div className={["border px-4 py-3 text-xs leading-5", statusTone].join(" ")}>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="font-bold">
              {insiderTransactions.contract_version} / {insiderTransactions.status}
            </span>
            <span className="font-semibold">
              {t("usStockDetail.insider.lastChecked")}: {formatDateTime(insiderTransactions.as_of)}
            </span>
          </div>
          <div className="mt-1">
            {t("usStockDetail.insider.latestFiling")}: {formatDate(insiderTransactions.freshness.latest_filing_date)}
            {" / "}
            {t("usStockDetail.insider.accession")}: {insiderTransactions.freshness.latest_accession_number ?? "-"}
          </div>
          {insiderTransactions.quality.issue_codes.length > 0 ? (
            <div className="mt-1 break-words font-mono text-[11px]">
              {insiderTransactions.quality.issue_codes.slice(0, 6).join(" / ")}
            </div>
          ) : null}
        </div>

        <div className="overflow-hidden border border-omi-border-subtle">
          <div className="grid grid-cols-2 gap-px bg-omi-surface-strong text-sm md:grid-cols-3">
            <MetricCell
              label={t("usStockDetail.insider.openMarketPurchases")}
              value={`${summary.open_market_purchase_count} / ${formatDecimalText(summary.open_market_purchase_shares, 2)}`}
            />
            <MetricCell
              label={t("usStockDetail.insider.openMarketSales")}
              value={`${summary.open_market_sale_count} / ${formatDecimalText(summary.open_market_sale_shares, 2)}`}
            />
            <MetricCell
              label={t("usStockDetail.insider.otherTransactions")}
              value={formatNumber(summary.other_transaction_count, 0)}
            />
            <MetricCell
              label={t("usStockDetail.insider.filings")}
              value={formatNumber(summary.filing_count, 0)}
            />
            <MetricCell
              label={t("usStockDetail.insider.amendments")}
              value={formatNumber(summary.amendment_count, 0)}
            />
            <MetricCell
              label={t("usStockDetail.insider.latestTransaction")}
              value={formatDate(summary.latest_transaction_date)}
            />
          </div>
        </div>

        <div className="border border-omi-warning-border bg-omi-warning-soft px-4 py-3 text-xs leading-5 text-omi-warning-strong">
          {insiderTransactions.quality.limitations[0] ??
            t("usStockDetail.insider.form4Limitation")}
        </div>

        <div className="overflow-hidden border border-omi-border-subtle">
          <div className="hidden grid-cols-[84px_minmax(170px,1.2fr)_minmax(150px,1fr)_108px_112px] bg-omi-surface-subtle px-4 py-2 text-xs font-bold uppercase tracking-wide text-omi-text-muted md:grid">
            <span>{t("usStockDetail.tableHeaders.date")}</span>
            <span>{t("usStockDetail.tableHeaders.insider")}</span>
            <span>{t("usStockDetail.tableHeaders.type")}</span>
            <span className="text-right">{t("usStockDetail.tableHeaders.shares")}</span>
            <span className="text-right">{t("usStockDetail.insider.priceAfter")}</span>
          </div>
          <div className="max-h-[34rem] overflow-y-auto">
            {insiderTransactions.transactions.length > 0 ? (
              insiderTransactions.transactions.map((row) => {
                const owner = row.owners[0] ?? null;
                const role = owner ? insiderOwnerRole(owner) : "";
                return (
                  <div
                    key={row.transaction_id}
                    className="grid gap-3 border-t border-omi-border-subtle px-4 py-3 text-sm md:grid-cols-[84px_minmax(170px,1.2fr)_minmax(150px,1fr)_108px_112px] md:items-start md:gap-0"
                  >
                    <div className="text-omi-text-muted">
                      <span className="block font-semibold text-omi-text">
                        {formatDate(row.transaction_date)}
                      </span>
                      <span className="block text-[10px]">{row.form_type}</span>
                    </div>
                    <div className="min-w-0">
                      <span className="block truncate font-bold text-omi-text-strong">
                        {owner?.name ?? "-"}
                      </span>
                      <span className="block truncate text-xs text-omi-text-muted">
                        {role || owner?.cik || "-"}
                      </span>
                      {row.owners.length > 1 ? (
                        <span className="block text-[10px] text-omi-text-subtle">
                          +{row.owners.length - 1} {t("usStockDetail.insider.additionalOwners")}
                        </span>
                      ) : null}
                    </div>
                    <div className="min-w-0">
                      <div className="flex flex-wrap gap-1">
                        <span className={["border px-1.5 py-0.5 text-[10px] font-bold", insiderCategoryTone(row.category)].join(" ")}>
                          {row.transaction_code ?? "-"} / {t(`usStockDetail.insider.categories.${row.category}`)}
                        </span>
                        {row.table_type === "derivative" ? (
                          <span className="border border-omi-border-subtle px-1.5 py-0.5 text-[10px] font-semibold text-omi-text-muted">
                            {t("usStockDetail.insider.derivative")}
                          </span>
                        ) : null}
                        {row.aff10b5_one ? (
                          <span className="border border-omi-border-subtle px-1.5 py-0.5 text-[10px] font-semibold text-omi-text-muted">
                            10b5-1
                          </span>
                        ) : null}
                        {row.is_amendment ? (
                          <span className="border border-omi-warning-border px-1.5 py-0.5 text-[10px] font-semibold text-omi-warning-strong">
                            4/A
                          </span>
                        ) : null}
                      </div>
                      <span className="mt-1 block truncate text-xs text-omi-text-muted">
                        {row.security_title ?? row.underlying_security_title ?? "-"}
                      </span>
                    </div>
                    <div className="text-left md:text-right">
                      <span className="font-bold text-omi-text-strong">
                        {row.acquired_disposed_code ?? "-"} {formatDecimalText(row.shares, 2)}
                      </span>
                      <span className="block text-xs text-omi-text-muted">
                        {row.direct_indirect_code ?? "-"} / {t("usStockDetail.insider.after")} {formatDecimalText(row.post_transaction_shares, 2)}
                      </span>
                    </div>
                    <div className="text-left md:text-right">
                      <span className="font-bold text-omi-text-strong">
                        {row.price_per_share ? `$${formatDecimalText(row.price_per_share, 4)}` : "-"}
                      </span>
                      <a
                        href={row.source_url}
                        target="_blank"
                        rel="noreferrer"
                        className="block truncate text-xs font-semibold text-omi-accent hover:underline"
                      >
                        SEC {row.accession_number.slice(-8)}
                      </a>
                    </div>
                  </div>
                );
              })
            ) : (
              <div className="border-t border-omi-border-subtle p-4">
                <EmptyDataState
                  message={
                    insiderTransactions.status === "ready_empty"
                      ? t("usStockDetail.empty.form4CheckedEmpty")
                      : t("usStockDetail.empty.noForm4Rows")
                  }
                />
              </div>
            )}
          </div>
        </div>
      </div>
    );
  }

  function renderShortTab() {
    return (
      <div className="space-y-4">
        <div className="overflow-hidden border border-omi-border-subtle">
          <div className="grid grid-cols-2 gap-px bg-omi-surface-strong text-sm md:grid-cols-4">
            <MetricCell label={t("usStockDetail.metrics.date")} value={formatDate(latestShortVolume?.trade_date)} />
            <MetricCell label={t("usStockDetail.metrics.shortRatio")} value={formatRatioAsPct(latestShortVolume?.short_ratio)} />
            <MetricCell label={t("usStockDetail.metrics.shortVolume")} value={formatVolume(latestShortVolume?.short_volume)} />
            <MetricCell label={t("usStockDetail.metrics.totalVolume")} value={formatVolume(latestShortVolume?.total_volume)} />
          </div>
        </div>

        <div className="border border-omi-warning-border bg-omi-warning-soft px-4 py-3 text-xs leading-5 text-omi-warning-strong">
          {t("usStockDetail.notes.finraShortVolumeOnly")}
        </div>

        <div className="overflow-hidden border border-omi-border-subtle">
          <div className="grid grid-cols-[88px_1fr_92px] bg-omi-surface-subtle px-4 py-2 text-xs font-bold uppercase tracking-wide text-omi-text-muted">
            <span>{t("usStockDetail.tableHeaders.date")}</span>
            <span>{t("usStockDetail.tableHeaders.shortTotal")}</span>
            <span className="text-right">{t("usStockDetail.tableHeaders.ratio")}</span>
          </div>
          <div className="max-h-64 overflow-y-auto">
            {shortVolumeRows.length > 0 ? (
              shortVolumeRows.slice(0, 8).map((row) => (
                <div
                  key={`${row.trade_date}-${row.market_center}-${row.id}`}
                  className="grid grid-cols-[88px_1fr_92px] border-t border-omi-border-subtle px-4 py-2 text-sm"
                >
                  <span className="text-omi-text-muted">{formatDate(row.trade_date)}</span>
                  <span className="min-w-0">
                    <span className="block font-semibold text-omi-text">
                      {formatVolume(row.short_volume)} / {formatVolume(row.total_volume)}
                    </span>
                    <span className="block truncate text-xs text-omi-text-muted">
                      {row.market_center || row.provider}
                    </span>
                  </span>
                  <span className="text-right font-bold text-omi-text-strong">
                    {formatRatioAsPct(row.short_ratio)}
                  </span>
                </div>
              ))
            ) : (
              <div className="border-t border-omi-border-subtle px-5 py-8 text-center text-sm text-omi-text-muted">
                {t("usStockDetail.empty.noShortVolume")}
              </div>
            )}
          </div>
        </div>
      </div>
    );
  }

  function renderFinancialsTab() {
    return (
      <div className="overflow-hidden border border-omi-border-subtle">
        <div className="border-b border-omi-border-subtle bg-omi-surface-subtle px-4 py-2 text-xs font-bold uppercase tracking-wide text-omi-text-muted">
          {t("usStockDetail.sections.secFundamentals")}
        </div>
        {financialContract ? (
          <>
            <div
              className={[
                "border-b px-4 py-3 text-xs leading-5",
                financialQuality?.decision_usable
                  ? "border-omi-success-border bg-omi-success-soft text-omi-success-strong"
                  : "border-omi-warning-border bg-omi-warning-soft text-omi-warning-strong",
              ].join(" ")}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-bold">
                  {financialContract.contract_version} · {financialContract.normalized.status}
                </span>
                <span className="font-semibold">
                  {t("usStockDetail.financialQuality.freshness")}: {financialQuality?.freshness ?? "-"}
                </span>
              </div>
              <div className="mt-1">
                {t("usStockDetail.financialQuality.continuity")}: {financialQuality?.continuity ?? "-"}
                {" · "}
                {t("usStockDetail.financialQuality.semanticValidity")}: {financialQuality?.semantic_validity ?? "-"}
                {" · "}
                {t("usStockDetail.financialQuality.supplementalSemanticValidity")}: {financialQuality?.supplemental_semantic_validity ?? "-"}
              </div>
              {decisionBlockingFinancialIssues.length > 0 ? (
                <div className="mt-1 break-words font-mono text-[11px]">
                  {decisionBlockingFinancialIssues.slice(0, 6).join(" · ")}
                </div>
              ) : null}
              {nonBlockingFinancialIssues.length > 0 ? (
                <div className="mt-1 break-words font-mono text-[11px] text-omi-warning-strong">
                  {nonBlockingFinancialIssues.slice(0, 6).join(" · ")}
                </div>
              ) : null}
            </div>
            <div className="grid grid-cols-2 gap-px bg-omi-surface-strong text-sm md:grid-cols-3">
              <MetricCell label={t("usStockDetail.metrics.revenueTtm")} value={formatDerivedValue(revenueTtmMetric)} />
              <MetricCell label={t("usStockDetail.metrics.epsTtm")} value={formatDerivedValue(epsTtmMetric, { perShare: true })} />
              <MetricCell label={t("usStockDetail.metrics.peTtm")} value={formatNumber(financialNumber(financialContract.valuation.pe_ttm))} />
              <MetricCell label={t("usStockDetail.metrics.grossMargin")} value={formatDerivedValue(grossMarginMetric, { percent: true })} />
              <MetricCell label={t("usStockDetail.metrics.operatingMargin")} value={formatDerivedValue(operatingMarginMetric, { percent: true })} />
              <MetricCell label={t("usStockDetail.metrics.netMargin")} value={formatDerivedValue(netMarginMetric, { percent: true })} />
              <MetricCell label={t("usStockDetail.metrics.revenueYoy")} value={formatDerivedValue(revenueYoyMetric, { percent: true })} />
              <MetricCell label={t("usStockDetail.metrics.freeCashFlow")} value={formatDerivedValue(freeCashFlowMetric)} />
              <MetricCell label={t("usStockDetail.metrics.netDebt")} value={formatDerivedValue(financialDerived?.net_debt)} />
            </div>
            <div className="grid grid-cols-[76px_minmax(94px,1fr)_minmax(94px,1fr)_72px] bg-omi-surface-subtle px-4 py-2 text-xs font-bold uppercase tracking-wide text-omi-text-muted">
              <span>{t("usStockDetail.tableHeaders.period")}</span>
              <span className="text-right">{t("usStockDetail.fundamentals.revenue")}</span>
              <span className="text-right">{t("usStockDetail.fundamentals.net_income")}</span>
              <span className="text-right">EPS</span>
            </div>
            <div className="max-h-72 overflow-y-auto">
              {financialQuarterRows.length > 0 ? (
                financialQuarterRows.map((row) => (
                  <div
                    key={row.period}
                    className="grid grid-cols-[76px_minmax(94px,1fr)_minmax(94px,1fr)_72px] border-t border-omi-border-subtle px-4 py-2 text-sm text-omi-text"
                  >
                    <span>
                      <span className="block font-bold">{row.period}</span>
                      <span className="block text-[10px] text-omi-text-subtle">{formatDate(row.periodEnd)}</span>
                    </span>
                    <span className="text-right font-semibold">{formatDerivedValue(row.revenue)}</span>
                    <span className="text-right font-semibold">{formatDerivedValue(row.netIncome)}</span>
                    <span className="text-right font-semibold">{formatDerivedValue(row.eps, { perShare: true })}</span>
                  </div>
                ))
              ) : (
                <div className="border-t border-omi-border-subtle p-4">
                  <EmptyDataState message={t("usStockDetail.empty.noNormalizedQuarters")} />
                </div>
              )}
            </div>
          </>
        ) : fundamentalMetrics.length > 0 ? (
          <div className="grid grid-cols-2 gap-px bg-omi-surface-strong text-sm md:grid-cols-3">
            {secFundamentalCards.map((card) => (
              <FundamentalMetricCell
                key={card.metric}
                label={t(`usStockDetail.fundamentals.${card.metric}`)}
                metric={fundamentalMetricMap.get(card.metric)}
              />
            ))}
          </div>
        ) : (
          <div className="p-4">
            <EmptyDataState message={t("usStockDetail.empty.noSecFundamentals")} />
          </div>
        )}
      </div>
    );
  }

  function renderFilingsTab() {
    return (
      <div className="space-y-4">
        <div className="overflow-hidden border border-omi-border-subtle">
          <div className="grid grid-cols-2 gap-px bg-omi-surface-strong text-sm md:grid-cols-3">
            <MetricCell label={t("usStockDetail.metrics.cik")} value={selectedStock?.cik ?? "-"} />
            <MetricCell label={t("usStockDetail.metrics.secFacts")} value={factRows.length} />
            <MetricCell label={t("usStockDetail.metrics.fundamentals")} value={fundamentalSummary?.metric_count ?? 0} />
            <MetricCell
              label={t("usStockDetail.metrics.latestFiled")}
              value={
                latestFundamentalFiledDate !== "-"
                  ? latestFundamentalFiledDate
                  : latestFactFiledDate
              }
            />
            <MetricCell label={t("usStockDetail.metrics.periodEnd")} value={latestFundamentalPeriodEnd} />
            <MetricCell label={t("usStockDetail.metrics.actions")} value={corporateActions.length} />
            <MetricCell label={t("usStockDetail.metrics.latestAction")} value={latestActionDate} />
          </div>
        </div>

        <div className="overflow-hidden border border-omi-border-subtle">
          <div className="grid grid-cols-[minmax(120px,1fr)_56px_88px_minmax(86px,0.8fr)] bg-omi-surface-subtle px-4 py-2 text-xs font-bold uppercase tracking-wide text-omi-text-muted">
            <span>{t("usStockDetail.tableHeaders.tag")}</span>
            <span>{t("usStockDetail.tableHeaders.fiscalYear")}</span>
            <span>{t("usStockDetail.tableHeaders.end")}</span>
            <span className="text-right">{t("usStockDetail.tableHeaders.value")}</span>
          </div>
          <div className="max-h-72 overflow-y-auto">
            {factRows.length > 0 ? (
              factRows.slice(0, 12).map((fact) => (
                <div
                  key={fact.fact_key}
                  className="grid grid-cols-[minmax(120px,1fr)_56px_88px_minmax(86px,0.8fr)] border-t border-omi-border-subtle px-4 py-2 text-sm text-omi-text"
                >
                  <span className="min-w-0">
                    <span className="block truncate font-semibold">{fact.tag}</span>
                    <span className="block truncate text-xs text-omi-text-muted">{fact.unit}</span>
                  </span>
                  <span>{fact.fiscal_year ?? "-"}</span>
                  <span>{formatDate(fact.period_end_date)}</span>
                  <span className="truncate text-right font-semibold">{formatFactValue(fact)}</span>
                </div>
              ))
            ) : (
              <div className="border-t border-omi-border-subtle px-5 py-8 text-center text-sm text-omi-text-muted">
                {factLoadState === "loading" ? t("common.loading") : t("usStockDetail.empty.noSecFacts")}
              </div>
            )}
          </div>
        </div>

        <div className="overflow-hidden border border-omi-border-subtle">
          <div className="grid grid-cols-[88px_1fr_88px] bg-omi-surface-subtle px-4 py-2 text-xs font-bold uppercase tracking-wide text-omi-text-muted">
            <span>{t("usStockDetail.tableHeaders.date")}</span>
            <span>{t("usStockDetail.tableHeaders.action")}</span>
            <span className="text-right">{t("usStockDetail.tableHeaders.value")}</span>
          </div>
          <div className="max-h-52 overflow-y-auto">
            {corporateActions.length > 0 ? (
              corporateActions.slice(0, 8).map((action) => (
                <div
                  key={`${action.action_type}-${action.event_date}-${action.id}`}
                  className="grid grid-cols-[88px_1fr_88px] border-t border-omi-border-subtle px-4 py-2 text-sm"
                >
                  <span className="text-omi-text-muted">{formatDate(action.event_date)}</span>
                  <span className="font-semibold text-omi-text">
                    {action.action_type === "dividend"
                      ? t("usStockDetail.actionTypes.dividend")
                      : t("usStockDetail.actionTypes.split")}
                  </span>
                  <span className="text-right font-bold text-omi-text-strong">
                    {formatActionValue(action)}
                  </span>
                </div>
              ))
            ) : (
              <div className="border-t border-omi-border-subtle px-5 py-8 text-center text-sm text-omi-text-muted">
                {t("usStockDetail.empty.noCorporateActions")}
              </div>
            )}
          </div>
        </div>
      </div>
    );
  }

  function renderActiveDataTab() {
    if (activeDataTab === "overview") return renderOverviewTab();
    if (activeDataTab === "financials") return renderFinancialsTab();
    if (activeDataTab === "institutions") return renderInstitutionsTab();
    if (activeDataTab === "insider") return renderInsiderTab();
    if (activeDataTab === "short") return renderShortTab();
    return renderFilingsTab();
  }

  if (!selectedSymbol) {
    return watchlistRankingPanel ? (
      <section className="min-w-0">{watchlistRankingPanel}</section>
    ) : (
      <section className="border border-omi-border-subtle bg-omi-surface px-5 py-10 text-sm text-omi-text-muted">
        {t("usStockDetail.noStockSelected")}
      </section>
    );
  }

  return (
    <section
      className={[
        "grid w-full grid-cols-1 items-start justify-start gap-4",
        chartFocusMode ? "" : "xl:grid-cols-[minmax(0,7fr)_minmax(360px,5fr)]",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <div className={["min-w-0 self-start", chartFocusMode ? "space-y-0" : "space-y-4"].join(" ")}>
        {chartFocusMode ? (
          <ProfessionalChartPanel
            title={`${selectedDisplaySymbol} ${selectedDisplayName}`}
            priceSummary={
              <div className={`flex items-baseline gap-2 ${valueTone(change)}`}>
                <PriceUpdatePulse
                  value={professionalLatestClose}
                  direction={change}
                  resetKey={`${selectedSymbol ?? "empty"}:us-professional:${professionalTimeframe}`}
                  className="text-2xl font-bold leading-none tracking-normal tabular-nums"
                >
                  {formatNumber(professionalLatestClose)}
                </PriceUpdatePulse>
                <span className="text-sm font-semibold tabular-nums">
                  {formatNumber(change)}
                </span>
                <span className="text-sm font-semibold tabular-nums">
                  ({formatPct(changePct)})
                </span>
              </div>
            }
            timeframeOptions={usProfessionalTimeframeOptions.map((option) => ({
              key: option,
              label: timeframeLabel(t, option),
            }))}
            timeframe={professionalTimeframe}
            onTimeframeChange={handleProfessionalTimeframeChange}
            chartStyle={professionalChartStyle}
            onChartStyleChange={setProfessionalChartStyle}
            indicatorMenuOpen={indicatorMenuOpen}
            onToggleIndicatorMenu={() => setIndicatorMenuOpen((value) => !value)}
            onCloseIndicatorMenu={() => setIndicatorMenuOpen(false)}
            indicatorMenu={
              <TechnicalIndicatorMenu
                indicators={chartIndicators}
                activeTemplate={activeIndicatorTemplate}
                onApplyTemplate={applyIndicatorTemplate}
                onToggleIndicator={toggleChartIndicator}
                groups={professionalIndicatorCategoryGroups}
                includeParameters
                parameters={indicatorParameters}
                onUpdateParameter={handleIndicatorParameterChange}
                className="w-[25rem]"
              />
            }
            onClose={() => {
              setIndicatorMenuOpen(false);
              setChartDrawingTool("cursor");
              setChartFocusMode(false);
            }}
            message={
              successMessage ||
              (professionalIsIntraday && visibleBarSourcePresentation) ? (
                <>
                  {successMessage ? (
                    <div className="border-b border-omi-success-border bg-omi-success-soft px-5 py-3 text-sm text-omi-success">
                      {successMessage.text}
                    </div>
                  ) : null}
                  {professionalIsIntraday && visibleBarSourcePresentation ? (
                    <div
                      className={[
                        "border-b px-5 py-3 text-sm",
                        visibleBarSourcePresentation.level === "error"
                          ? "border-omi-danger-border bg-omi-danger-soft text-omi-danger"
                          : "border-omi-warning-border bg-omi-warning-soft text-omi-warning-strong",
                      ].join(" ")}
                    >
                      {visibleBarSourcePresentation.message}
                    </div>
                  ) : null}
                </>
              ) : null
            }
            chartReady={professionalChartReady}
            emptyState={
              <div className="flex h-[640px] items-center justify-center border-t border-omi-border-subtle p-4">
                <StateSurface
                  title={t("usStockDetail.loadingKline", { label: professionalTimeframeLabel })}
                  tone="loading"
                  busy
                  className="w-full max-w-xl"
                />
              </div>
            }
            chartData={professionalChartData}
            label={professionalTimeframeLabel}
            timeMode={professionalIsIntraday ? "intraday" : "date"}
            showMovingAverages={chartIndicators.ma}
            indicators={chartIndicators}
            indicatorParameters={indicatorParameters}
            volumePanelLabel={t("usStockDetail.metrics.volume")}
            drawingTool={chartDrawingTool}
            drawings={chartDrawings}
            selectedDrawingId={activeSelectedChartDrawingId}
            drawingContext={professionalDrawingContext}
            onDrawingToolChange={setChartDrawingTool}
            onDrawingsChange={updateChartDrawings}
            onDrawingStateChange={updateChartDrawingState}
            onSelectedDrawingChange={setSelectedChartDrawingId}
            canUndoDrawing={canUndoChartDrawing}
            canRedoDrawing={canRedoChartDrawing}
            onUndoDrawing={undoChartDrawing}
            onRedoDrawing={redoChartDrawing}
            onDeleteSelectedDrawing={deleteSelectedChartDrawing}
            onClearDrawings={clearChartDrawings}
            historyCounts={{
              past: chartDrawingHistory.past.length,
              future: chartDrawingHistory.future.length,
            }}
          />
        ) : (
          <>
        <section
          className="border border-omi-border-subtle bg-omi-surface"
          data-testid="us-stock-kline-panel"
        >
          <div className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-4 px-5 py-4">
            <div className="min-w-0">
              <div className="text-xs font-semibold uppercase tracking-[0.18em] text-omi-text-muted">
                {selectedIndexConfig ? t("usStockDetail.entity.index") : t("usStockDetail.entity.stock")}
              </div>
              <h2 className="mt-1 text-2xl font-bold text-omi-text-strong">
                {selectedDisplaySymbol} {selectedDisplayName}
              </h2>
              <div className="mt-1 text-sm text-omi-text-muted">
                {selectedSubtitle}
              </div>
              {(visibleCurrentSourcePresentation ||
                upcomingCorporateEvents.length > 0 ||
                corporateEventSourceUncertain) ? (
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  {visibleCurrentSourcePresentation ? (
                    <div
                      data-testid="us-intraday-source-status"
                      data-source-role="current_observation"
                      className={[
                        "inline-flex border px-2 py-1 text-xs font-semibold",
                        visibleCurrentSourcePresentation.level === "error"
                          ? "border-omi-danger-border bg-omi-danger-soft text-omi-danger"
                          : "border-omi-warning-border bg-omi-warning-soft text-omi-warning-strong",
                      ].join(" ")}
                      title={visibleCurrentSourcePresentation.message}
                    >
                      {visibleCurrentSourcePresentation.badge}
                    </div>
                  ) : null}
                  {upcomingCorporateEvents.map((event) => (
                    <span
                      key={event.event_id}
                      data-testid="us-upcoming-corporate-event"
                      className={[
                        "inline-flex items-center border px-2 py-1 text-xs font-bold",
                        corporateEventTone(event.event_type),
                      ].join(" ")}
                      title={[
                        event.title,
                        `${event.event_date}${event.event_time ? ` ${event.event_time}` : ""}`,
                        event.source,
                        ...event.warnings,
                      ]
                        .filter(Boolean)
                        .join("\n")}
                    >
                      {t("usStockDetail.corporateEvents.reminder", {
                        date: event.event_date,
                        type: t(`settings.calendar.eventTypes.${event.event_type}`),
                      })}
                    </span>
                  ))}
                  {corporateEventSourceUncertain ? (
                    <span
                      className="inline-flex items-center border border-omi-warning-border bg-omi-warning-soft px-2 py-1 text-xs font-semibold text-omi-warning-strong"
                      title={corporateEventSummary?.warning ?? undefined}
                    >
                      {t("usStockDetail.corporateEvents.sourceUncertain")}
                    </span>
                  ) : null}
                </div>
              ) : null}
            </div>

            <div className="shrink-0 text-right">
              <div data-testid="us-stock-header-price">
                <PriceUpdatePulse
                  value={latestClose}
                  direction={change}
                  resetKey={`${selectedSymbol ?? "empty"}:current-observation`}
                  className="text-3xl font-black text-omi-text-strong"
                >
                  {formatNumber(latestClose)}
                </PriceUpdatePulse>
              </div>
              {currentQuoteUnavailable ? (
                <div
                  data-testid="us-today-quote-unavailable"
                  className="mt-1 text-xs font-semibold text-omi-text-muted"
                >
                  <div>
                    {t(
                      currentQuoteUnavailableMessageKey(
                        visibleTodayIntradayMeta.quoteExpectation
                      )
                    )}
                  </div>
                  {todayHistoricalReferencePrice !== null ? (
                    <div>
                      {t(
                        visibleTodayIntradayMeta.changeReferenceType ===
                          "current_day_regular_close"
                          ? "usStockDetail.currentQuote.currentDayRegularCloseReference"
                          : "usStockDetail.currentQuote.previousCloseReference",
                        {
                          price: formatNumber(todayHistoricalReferencePrice),
                          date: formatDate(todayPreviousCloseReferenceDate),
                        }
                      )}
                    </div>
                  ) : null}
                </div>
              ) : (
                <div className={`text-sm font-bold ${valueTone(changePct)}`}>
                  {formatNumber(change)} / {formatPct(changePct)}
                </div>
              )}
              <div className="mt-3 inline-flex border border-omi-border-subtle bg-omi-surface-subtle p-1">
                {timeframeOptions.map((option) => (
                  <button
                    key={option}
                    type="button"
                    onClick={() => setTimeframe(option)}
                    className={[
                      "h-8 min-w-12 px-3 text-sm font-semibold transition",
                      timeframe === option
                        ? "omi-timeframe-tab-active"
                        : "text-omi-text-muted hover:bg-omi-surface",
                    ].join(" ")}
                  >
                    {timeframeLabel(t, option)}
                  </button>
                ))}
              </div>
              <div className="mt-2 flex items-start justify-end gap-2">
                {timeframe === "today" ? (
                  <div className="relative">
                    <button
                      type="button"
                      onClick={() => setIndicatorMenuOpen((value) => !value)}
                      className="h-8 border border-omi-control bg-omi-surface px-3 text-sm font-semibold text-omi-text hover:border-omi-accent hover:text-omi-danger"
                    >
                      {t("stockDetail.indicators")}
                    </button>
                    {indicatorMenuOpen ? (
                      <div className="absolute right-0 z-20 mt-2 w-56 border border-omi-border-subtle bg-omi-surface p-3 text-left shadow-lg">
                        <div className="mb-2 text-xs font-bold text-omi-text-muted">
                          {t("stockDetail.displayItems")}
                        </div>
                        {intradayIndicatorOptions.map((option) => (
                          <label
                            key={option.key}
                            className="flex cursor-pointer items-start gap-2 px-2 py-2 text-xs hover:bg-omi-surface-subtle"
                          >
                            <input
                              type="checkbox"
                              checked={intradayIndicators[option.key]}
                              onChange={() => toggleIntradayIndicator(option.key)}
                              className="mt-0.5"
                            />
                            <span>
                              <span className="block font-semibold text-omi-text">
                                {option.label}
                              </span>
                              <span className="block text-omi-text-muted">
                                {t(option.descriptionKey)}
                              </span>
                            </span>
                          </label>
                        ))}
                      </div>
                    ) : null}
                  </div>
                ) : (
                  <div className="relative">
                    <button
                      type="button"
                      onClick={() => setIndicatorMenuOpen((value) => !value)}
                      className="h-8 border border-omi-control bg-omi-surface px-3 text-sm font-semibold text-omi-text hover:border-omi-accent hover:text-omi-danger"
                    >
                      {t("stockDetail.indicators")}
                    </button>
                    {indicatorMenuOpen ? (
                      <TechnicalIndicatorMenu
                        indicators={chartIndicators}
                        activeTemplate={activeIndicatorTemplate}
                        onApplyTemplate={applyIndicatorTemplate}
                        onToggleIndicator={toggleChartIndicator}
                        groups={professionalIndicatorCategoryGroups}
                        includeParameters
                        parameters={indicatorParameters}
                        onUpdateParameter={handleIndicatorParameterChange}
                        className="w-[25rem]"
                      />
                    ) : null}
                  </div>
                )}
                <button
                  type="button"
                  onClick={enterChartFocusMode}
                  className="h-8 border border-omi-control bg-omi-surface px-3 text-sm font-semibold text-omi-text hover:border-omi-accent hover:text-omi-danger"
                >
                  {t("stockDetail.expand")}
                </button>
              </div>
            </div>
          </div>

          {successMessage ? (
            <div className="border-t border-omi-success-border bg-omi-success-soft px-5 py-3 text-sm text-omi-success">
              {successMessage.text}
            </div>
          ) : null}

          {chartLoadState === "loading" ? (
            <div className="border-t border-omi-border-subtle bg-omi-surface p-4">
              <StateSurface
                title={t("usStockDetail.loadingKlineShort")}
                tone="loading"
                busy
                className="h-[428px]"
              />
            </div>
          ) : timeframe === "today" ? (
            <>
              <div className="border-x border-t border-omi-border-subtle bg-omi-surface px-4 py-3">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <div className="text-xs font-semibold uppercase text-omi-text-muted">
                      {t("usStockDetail.extendedHours.title")}
                    </div>
                    <div className="mt-1 text-xs text-omi-text-muted">
                      {intradaySessionMetaLine}
                    </div>
                  </div>
                  <div className="inline-flex border border-omi-border bg-omi-surface">
                    {usIntradaySessionScopeOptions.map((scope) => (
                      <button
                        key={scope}
                        type="button"
                        onClick={() => setIntradaySessionScope(scope)}
                        className={[
                          "h-8 px-3 text-xs font-semibold transition",
                          intradaySessionScope === scope
                            ? "bg-omi-control text-omi-text-inverse"
                            : "text-omi-text-muted hover:bg-omi-surface-muted",
                        ].join(" ")}
                      >
                        {sessionScopeLabel(t, scope)}
                      </button>
                    ))}
                  </div>
                </div>
                {intradaySessionWarning ? (
                  <div className="mt-2 text-xs text-omi-warning">
                    {intradaySessionWarning}
                  </div>
                ) : null}
                {intradayCoverageNotice ? (
                  <div
                    className="mt-2 text-xs text-omi-accent"
                    data-testid="us-intraday-coverage-notice"
                  >
                    {intradayCoverageNotice}
                  </div>
                ) : null}
              </div>
              <IntradayTrendChart
                points={visibleTodayTrend}
                previousClose={visibleTodayPreviousClose}
                label={
                  selectedIndexConfig
                    ? `${selectedDisplaySymbol} ${timeframeLabel(t, "today")}`
                    : timeframeLabel(t, timeframe)
                }
                source={visibleTodaySource}
                indicators={intradayIndicators}
                session={activeIntradaySession}
                revealKey={`${selectedSymbol ?? "empty"}-${timeframe}-${intradaySessionScope}-${visibleTodayTrend.length}`}
                refreshIntervalMs={US_INTRADAY_REFRESH_MS}
                refreshMode="cache_poll"
                updatedAt={visibleTodayUpdatedAt}
                priceLimitEnabled={false}
              />
            </>
          ) : chartData.length > 0 ? (
            <StockKLineChart
              chartData={chartData}
              label={selectedDisplaySymbol}
              indicators={chartIndicators}
              indicatorParameters={indicatorParameters}
              revealKey={`${selectedSymbol ?? "empty"}-${timeframe}-${chartData.length}`}
              volumePanelLabel={t("usStockDetail.metrics.volume")}
              volumeTooltipLabel={t("usStockDetail.metrics.volume")}
              volumeValueFormatter={formatVolume}
            />
          ) : (
            <div className="border-t border-omi-border-subtle bg-omi-surface p-4">
              <StateSurface
                title={
                  selectedSymbol
                    ? selectedIndexConfig
                      ? t("usStockDetail.noIndexKline")
                      : t("usStockDetail.noKline")
                    : t("usStockDetail.noStockSelected")
                }
                tone="empty"
                className="h-[428px]"
              />
            </div>
          )}
        </section>

        {watchlistRankingPanel ? (
          <div className="min-w-0">{watchlistRankingPanel}</div>
        ) : null}
          </>
        )}
      </div>

      {!chartFocusMode ? (
      <aside className="flex min-w-0 flex-col border border-omi-border-subtle bg-omi-surface">
        <section>
          <div className="flex items-start justify-between gap-4 border-b border-omi-border-subtle px-5 py-4">
            <div>
              <div className="text-xs font-semibold uppercase tracking-[0.18em] text-omi-text-muted">
                {t("usStockDetail.sections.technical")}
              </div>
              <h3 className="mt-1 text-xl font-bold text-omi-text-strong">{technicalTitle}</h3>
              <div className="mt-1 text-sm text-omi-text-muted">
                {t("usStockDetail.technicalSubtitle")}
                {technicalIndicators?.as_of
                  ? ` · ${formatDate(technicalIndicators.as_of)}`
                  : ""}
              </div>
              {technicalQuality && !technicalQuality.decision_usable ? (
                <div className="mt-2 border border-omi-warning-border bg-omi-warning-soft px-2 py-1 text-xs font-semibold text-omi-warning-strong">
                  {technicalQuality.facts_usable
                    ? t("usStockDetail.technicalQuality.partial")
                    : t("usStockDetail.technicalQuality.missing")}
                </div>
              ) : null}
            </div>
            <div className={`text-right text-lg font-black ${valueTone(priceVsMa20)}`}>
              <PriceUpdatePulse
                value={priceVsMa20}
                direction={priceVsMa20}
                resetKey={`${selectedSymbol ?? "empty"}:technical-ma20`}
                className="justify-end tabular-nums"
              >
                {formatPct(priceVsMa20)}
              </PriceUpdatePulse>
              <div className="text-xs font-semibold text-omi-text-muted">vs MA20</div>
            </div>
          </div>

          <div className="space-y-3 px-5 py-4 text-sm">
            <div>
              <div className="mb-1 flex justify-between text-xs text-omi-text-muted">
                <span>{t("usStockDetail.technicalMetrics.priceVsMa20")}</span>
                <span className={valueTone(priceVsMa20)}>
                  <PriceUpdatePulse
                    value={priceVsMa20}
                    direction={priceVsMa20}
                    resetKey={`${selectedSymbol ?? "empty"}:technical-price`}
                    className="justify-end tabular-nums"
                  >
                    {formatPct(priceVsMa20)}
                  </PriceUpdatePulse>
                </span>
              </div>
              <div className="h-2 bg-omi-surface-muted">
                <div
                  className={`omi-technical-bar h-2 ${metricBarClass(priceVsMa20)}`}
                  style={metricBarStyle(priceVsMa20)}
                />
              </div>
            </div>
            <div>
              <div className="mb-1 flex justify-between text-xs text-omi-text-muted">
                <span>{t("usStockDetail.technicalMetrics.volumeVsMa20")}</span>
                <span className={valueTone(technicalVolumeMetric)}>
                  <PriceUpdatePulse
                    value={technicalVolumeMetric}
                    direction={technicalVolumeMetric}
                    resetKey={`${selectedSymbol ?? "empty"}:technical-volume`}
                    className="justify-end tabular-nums"
                  >
                    {formatPct(technicalVolumeMetric)}
                  </PriceUpdatePulse>
                </span>
              </div>
              <div className="h-2 bg-omi-surface-muted">
                <div
                  className={`omi-technical-bar h-2 ${metricBarClass(technicalVolumeMetric)}`}
                  style={metricBarStyle(technicalVolumeMetric)}
                />
              </div>
            </div>
            <div>
              <div className="mb-1 flex justify-between text-xs text-omi-text-muted">
                <span>{t("usStockDetail.technicalMetrics.dayChangePct")}</span>
                <span className={valueTone(technicalDayChangePct)}>
                  <PriceUpdatePulse
                    value={technicalDayChangePct}
                    direction={technicalDayChangePct}
                    resetKey={`${selectedSymbol ?? "empty"}:technical-change`}
                    className="justify-end tabular-nums"
                  >
                    {formatPct(technicalDayChangePct)}
                  </PriceUpdatePulse>
                </span>
              </div>
              <div className="h-2 bg-omi-surface-muted">
                <div
                  className={`omi-technical-bar h-2 ${metricBarClass(technicalDayChangePct)}`}
                  style={metricBarStyle(technicalDayChangePct)}
                />
              </div>
            </div>
          </div>

          <div className="grid grid-cols-3 border-t border-omi-border-subtle text-center text-sm">
            <div className="px-4 py-3">
              <div className="text-xs text-omi-text-muted">MA5</div>
              <div className="mt-1 font-bold">{formatNumber(ma5)}</div>
            </div>
            <div className="border-l border-omi-border-subtle px-4 py-3">
              <div className="text-xs text-omi-text-muted">MA20</div>
              <div className="mt-1 font-bold">{formatNumber(ma20)}</div>
            </div>
            <div className="border-l border-omi-border-subtle px-4 py-3">
              <div className="text-xs text-omi-text-muted">MA60</div>
              <div className="mt-1 font-bold">{formatNumber(ma60)}</div>
            </div>
          </div>
        </section>

        <section className="border-t border-omi-border-subtle px-5 py-4">
          <div className="mb-3 flex items-center justify-between gap-3">
            <div>
              <div className="text-xs font-semibold uppercase tracking-[0.18em] text-omi-text-muted">
                {t("usStockDetail.sections.coverage")}
              </div>
              <div className="mt-1 text-sm font-bold text-omi-text-strong">
                {t("usStockDetail.coverage.readiness")}
              </div>
            </div>
            <div className="text-right text-[11px] font-semibold text-omi-text-muted">
              {t("usStockDetail.coverage.readyCount", {
                ready: readyCoverageCount,
                total: dataCoverageItems.length,
              })}
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2">
            {dataCoverageItems.map((item) => (
              <DataCoverageChip
                key={item.label}
                label={item.label}
                status={item.status}
                detail={item.detail}
              />
            ))}
          </div>
        </section>

        {selectedIndexConfig ? (
          <section className="border-t border-omi-border-subtle px-5 py-4">
            <div className="text-xs font-semibold uppercase tracking-[0.18em] text-omi-text-muted">
              {t("usStockDetail.sections.data")}
            </div>
            <h3 className="mt-1 text-lg font-bold text-omi-text-strong">
              {selectedDisplayName}
            </h3>
            <div className="mt-1 text-sm leading-6 text-omi-text-muted">
              {t("usStockDetail.indexDataDescription")}
            </div>
            <div className="mt-4 grid grid-cols-2 gap-px bg-omi-surface-strong text-sm">
              <MetricCell label={t("usStockDetail.metrics.symbol")} value={selectedIndexConfig.symbol} />
              <MetricCell label={t("usStockDetail.metrics.display")} value={selectedIndexConfig.displaySymbol} />
              <MetricCell label={t("usStockDetail.metrics.exchange")} value={selectedIndexConfig.exchange} />
              <MetricCell label={t("usStockDetail.metrics.source")} value="Yahoo chart" />
            </div>
          </section>
        ) : (
          <USFundamentalWorkspace
            activeTab={activeDataTab}
            onTabChange={setActiveDataTab}
            action={renderDataPanelAction()}
          >
            {renderActiveDataTab()}
          </USFundamentalWorkspace>
        )}
      </aside>
      ) : null}
    </section>
  );
}
