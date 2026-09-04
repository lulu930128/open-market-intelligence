import type {
  IntradayTrendPoint,
  IntradayTrendResponse,
  StockIndicatorPoint,
  USResolvedQuoteSnapshot,
} from "@/types/market";

export type MonotonicQuoteSelection = {
  snapshot: USResolvedQuoteSnapshot | null;
  acceptedGeneration: number;
};

export type USCurrentSessionHeadline = {
  latestPrice: number | null;
  referencePrice: number | null;
  referenceTradeDate: string | null;
  referenceType: string | null;
  change: number | null;
  changePct: number | null;
};

function symbolKey(value: string | null | undefined) {
  return value?.trim().toUpperCase() ?? "";
}

function quoteEventTime(snapshot: USResolvedQuoteSnapshot) {
  return snapshot.selected_event_at ?? snapshot.quote?.event_at ?? null;
}

function quoteFetchedTime(snapshot: USResolvedQuoteSnapshot) {
  return snapshot.quote?.fetched_at ?? null;
}

function comparableTime(value: string | null) {
  if (!value) return null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function finiteNumber(value: number | null | undefined) {
  return value !== null && value !== undefined && Number.isFinite(value)
    ? value
    : null;
}

export function projectUSCurrentSessionHeadline({
  currentObservationPrice,
  quotePrice,
  changeReferencePrice,
  changeReferenceTradeDate,
  changeReferenceType,
  changeReferenceStatus,
}: {
  currentObservationPrice: number | null;
  quotePrice: number | null;
  changeReferencePrice: number | null;
  changeReferenceTradeDate: string | null;
  changeReferenceType: string | null;
  changeReferenceStatus: string | null;
}): USCurrentSessionHeadline {
  const latestPrice =
    finiteNumber(currentObservationPrice) ?? finiteNumber(quotePrice);
  const referenceRejected =
    changeReferenceStatus === "missing" ||
    changeReferenceType === "unavailable" ||
    !changeReferenceTradeDate;
  const referencePrice = referenceRejected
    ? null
    : finiteNumber(changeReferencePrice);
  const change =
    latestPrice !== null && referencePrice !== null
      ? latestPrice - referencePrice
      : null;
  const changePct =
    change !== null && referencePrice !== null && referencePrice !== 0
      ? (change / referencePrice) * 100
      : null;

  return {
    latestPrice,
    referencePrice,
    referenceTradeDate: referencePrice !== null ? changeReferenceTradeDate : null,
    referenceType: referencePrice !== null ? changeReferenceType : null,
    change,
    changePct,
  };
}

export function selectMonotonicUSHeadlineQuote(
  current: USResolvedQuoteSnapshot | null,
  candidate: USResolvedQuoteSnapshot | null,
  options: {
    expectedSymbol: string;
    currentGeneration: number;
    candidateGeneration: number;
  }
): MonotonicQuoteSelection {
  const expectedSymbol = symbolKey(options.expectedSymbol);
  const currentMatches = symbolKey(current?.quote?.symbol) === expectedSymbol;
  const candidateMatches =
    candidate !== null &&
    (candidate.quote === null || symbolKey(candidate.quote.symbol) === expectedSymbol);

  if (!candidate || !candidateMatches) {
    return {
      snapshot: currentMatches ? current : null,
      acceptedGeneration: currentMatches ? options.currentGeneration : 0,
    };
  }
  if (!current) {
    return {
      snapshot: candidate,
      acceptedGeneration: options.candidateGeneration,
    };
  }
  if (!currentMatches) {
    if (
      current.quote === null &&
      options.candidateGeneration < options.currentGeneration
    ) {
      return { snapshot: current, acceptedGeneration: options.currentGeneration };
    }
    return {
      snapshot: candidate,
      acceptedGeneration: options.candidateGeneration,
    };
  }

  const currentEventTime = comparableTime(quoteEventTime(current));
  const candidateEventTime = comparableTime(quoteEventTime(candidate));
  if (currentEventTime !== null && candidateEventTime === null) {
    if (
      candidate.quote === null &&
      options.candidateGeneration > options.currentGeneration
    ) {
      return {
        snapshot: candidate,
        acceptedGeneration: options.candidateGeneration,
      };
    }
    return { snapshot: current, acceptedGeneration: options.currentGeneration };
  }
  if (currentEventTime !== null && candidateEventTime !== null) {
    if (candidateEventTime < currentEventTime) {
      return { snapshot: current, acceptedGeneration: options.currentGeneration };
    }
    if (candidateEventTime > currentEventTime) {
      return {
        snapshot: candidate,
        acceptedGeneration: options.candidateGeneration,
      };
    }
  } else if (candidateEventTime !== null) {
    return {
      snapshot: candidate,
      acceptedGeneration: options.candidateGeneration,
    };
  }

  const currentFetchedTime = comparableTime(quoteFetchedTime(current));
  const candidateFetchedTime = comparableTime(quoteFetchedTime(candidate));
  if (currentFetchedTime !== null && candidateFetchedTime === null) {
    return { snapshot: current, acceptedGeneration: options.currentGeneration };
  }
  if (currentFetchedTime !== null && candidateFetchedTime !== null) {
    if (candidateFetchedTime < currentFetchedTime) {
      return { snapshot: current, acceptedGeneration: options.currentGeneration };
    }
    if (candidateFetchedTime > currentFetchedTime) {
      return {
        snapshot: candidate,
        acceptedGeneration: options.candidateGeneration,
      };
    }
  } else if (candidateFetchedTime !== null) {
    return {
      snapshot: candidate,
      acceptedGeneration: options.candidateGeneration,
    };
  }

  return options.candidateGeneration >= options.currentGeneration
    ? {
        snapshot: candidate,
        acceptedGeneration: options.candidateGeneration,
      }
    : { snapshot: current, acceptedGeneration: options.currentGeneration };
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
