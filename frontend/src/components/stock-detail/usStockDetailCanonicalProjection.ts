import type {
  IntradayTrendPoint,
  IntradayTrendResponse,
  StockIndicatorPoint,
} from "@/types/market";
import type { USMarketTruthRead } from "@/types/usMarketTruth";

export type USCurrentSessionHeadline = {
  latestPrice: number | null;
  referencePrice: number | null;
  referenceTradeDate: string | null;
  referenceType: string | null;
  change: number | null;
  changePct: number | null;
  tradeDate: string | null;
};

function finiteNumber(value: string | null | undefined) {
  if (value == null || value.trim() === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function projectUSCurrentSessionHeadline(
  snapshot: USMarketTruthRead | null
): USCurrentSessionHeadline {
  const observation = snapshot?.headline_observation;
  const reference = snapshot?.comparison_references.find(
    (item) => item.purpose === "headline_change"
  );
  const metric = snapshot?.change_metrics.find(
    (item) => item.purpose === "headline_change"
      && item.observation_id === observation?.observation_id
      && item.reference_id === reference?.reference_id
      && item.display_usable
  );
  const latestPrice = observation?.display_usable
    ? finiteNumber(observation.price) : null;
  const referencePrice = reference?.display_usable && reference.reference_trade_date
    ? finiteNumber(reference.price) : null;
  const changeUsable = latestPrice !== null && referencePrice !== null
    && reference?.calculation_eligible;
  return {
    latestPrice,
    tradeDate: observation?.trade_date ?? null,
    referencePrice,
    referenceTradeDate: referencePrice !== null ? reference?.reference_trade_date ?? null : null,
    referenceType: referencePrice !== null ? reference?.purpose ?? null : null,
    change: changeUsable ? finiteNumber(metric?.absolute_change) : null,
    changePct: changeUsable ? finiteNumber(metric?.percent_change) : null,
  };
}

/** Opaque backend revisions; the browser does not infer a trading date or freshness. */
export function usDailySnapshotRevision(snapshot: USMarketTruthRead | null) {
  if (!snapshot) return null;
  return `${snapshot.component_revisions.daily_revision ?? "missing"}:${snapshot.component_revisions.calendar_revision}`;
}

export function projectUSIntradayIndicatorPoint(
  point: IntradayTrendPoint,
  response: IntradayTrendResponse
): StockIndicatorPoint {
  return {
    time: point.time,
    algorithm_version:
      point.technical_algorithm_version ??
      response.technical_algorithm_version ??
      null,
    price_basis: point.price_basis ?? null,
    calculation_role: point.calculation_role ?? null,
    parameter_contract: response.technical_parameter_contract,
    bar_status: point.bar_status ?? null,
    event_time: point.time,
    source: point.source ?? point.provider ?? response.source ?? null,
    decision_usable: point.decision_usable,
    volume_based_decision_usable: point.volume_based_decision_usable,
    close: point.price,
    volume: point.volume,
    change: null,
    change_pct: null,
    ma: {},
    volume_ma: {},
    ema: { ema12: point.ema_fast ?? null, ema26: point.ema_slow ?? null },
    macd: {
      line: point.macd_value ?? null,
      signal: point.macd_signal_value ?? null,
      histogram: point.macd_histogram_value ?? null,
    },
    rsi: { rsi14: point.rsi_value ?? null },
    vwap: point.vwap_value ?? null,
    twap: point.twap_value ?? null,
  };
}
