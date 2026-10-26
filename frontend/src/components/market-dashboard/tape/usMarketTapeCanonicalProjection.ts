import type { USMarketIndexItemRead } from "@/types/market";
import type { USMarketIndexConfig } from "@/lib/usMarketIndices";

export type USMarketTapeSnapshot = {
  symbol: string;
  displaySymbol: string;
  name: string;
  exchange: string;
  note: string;
  close: number | null;
  change: number | null;
  changePct: number | null;
  priceVsMa20: number | null;
  volume: number | null;
  pointCount: number;
  asOf: string | null;
  source: "market_truth" | "daily";
  previousClose: number | null;
  referenceTradeDate: string | null;
  truthRevision: string | null;
  marketSession?: string | null;
  freshnessStatus?: string;
  decisionUsable?: boolean;
  limitations?: string[];
  observationKind?: string | null;
  volumeStatus?: "not_applicable";
};

export type USMarketTapeReferenceSnapshot = USMarketTapeSnapshot & {
  ma20: number | null;
};

function finiteNumber(value: number | string | null | undefined) {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function normalizedSymbol(value: string | null | undefined) {
  return value?.trim().toUpperCase() ?? "";
}

export function projectUSMarketTapeSnapshot(
  reference: USMarketTapeReferenceSnapshot | null,
  headline: USMarketIndexItemRead | null,
  marketSession: string | null = null,
  config?: USMarketIndexConfig
): USMarketTapeSnapshot | null {
  const identity = config ?? reference;
  if (
    !headline ||
    (identity && normalizedSymbol(headline.canonical_symbol) !== normalizedSymbol(identity.symbol))
  ) {
    return reference ? { ...reference, volume: null, volumeStatus: "not_applicable", decisionUsable: false } : null;
  }

  const close = finiteNumber(headline.value);
  const change = finiteNumber(headline.change);
  const changePct = finiteNumber(headline.change_pct);
  const previousClose = finiteNumber(headline.previous_close);
  const priceVsMa20 =
    close !== null && reference?.ma20 != null && Number.isFinite(reference.ma20) && reference.ma20 !== 0
      ? ((close - reference.ma20) / reference.ma20) * 100
      : null;

  return {
    symbol: identity?.symbol ?? headline.canonical_symbol,
    displaySymbol: identity?.displaySymbol ?? headline.canonical_symbol,
    name: identity?.name ?? headline.label,
    exchange: identity?.exchange ?? "",
    note: identity?.note ?? "",
    close,
    change,
    changePct,
    priceVsMa20,
    volume: null,
    volumeStatus: "not_applicable",
    pointCount: reference?.pointCount ?? 0,
    asOf: headline.event_at,
    source: "market_truth",
    previousClose,
    referenceTradeDate: headline.reference_trade_date,
    truthRevision: headline.truth_revision,
    marketSession,
    freshnessStatus: headline.freshness_status,
    decisionUsable: headline.decision_usable,
    limitations: headline.limitations,
    observationKind: headline.observation_kind,
  };
}
