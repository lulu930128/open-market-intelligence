import type { USMarketIndexItemRead } from "@/types/market";

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
  headline: USMarketIndexItemRead | null
): USMarketTapeSnapshot | null {
  if (!reference) return null;
  if (
    !headline ||
    normalizedSymbol(headline.canonical_symbol) !== normalizedSymbol(reference.symbol)
  ) {
    return reference;
  }

  const close = finiteNumber(headline.value);
  const change = finiteNumber(headline.change);
  const changePct = finiteNumber(headline.change_pct);
  const previousClose = finiteNumber(headline.previous_close);
  const priceVsMa20 =
    close !== null && reference.ma20 !== null && reference.ma20 !== 0
      ? ((close - reference.ma20) / reference.ma20) * 100
      : null;

  return {
    symbol: reference.symbol,
    displaySymbol: reference.displaySymbol,
    name: reference.name,
    exchange: reference.exchange,
    note: reference.note,
    close,
    change,
    changePct,
    priceVsMa20,
    volume: reference.volume,
    pointCount: reference.pointCount,
    asOf: headline.event_at ?? reference.asOf,
    source: "market_truth",
    previousClose,
    referenceTradeDate: headline.reference_trade_date,
    truthRevision: headline.truth_revision,
  };
}
