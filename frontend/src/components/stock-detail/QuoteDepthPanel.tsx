"use client";

import {
  formatDateTime,
  formatLotUnits,
  formatPct,
  formatPrice,
  valueTone,
} from "@/components/stock-detail/StockDetailDataViews";
import type {
  TaiwanStockQuoteDepthLevel,
  TaiwanStockQuoteDepthPreviewMode,
  TaiwanStockQuoteDepthRead,
} from "@/types/market";

type QuoteDepthLoadState = "idle" | "loading" | "success" | "error";

type QuoteDepthPanelProps = {
  quoteDepth: TaiwanStockQuoteDepthRead | null;
  loadState: QuoteDepthLoadState;
  quoteDepthPreviewMode?: TaiwanStockQuoteDepthPreviewMode | null;
};

function statusClass(status: string | undefined) {
  if (status === "preview") {
    return "border-sky-500/50 bg-sky-500/10 text-omi-text-strong";
  }
  if (status === "live" || status === "final_snapshot") {
    return "border-omi-market-up/40 bg-omi-market-up/10 text-omi-market-up";
  }
  if (status === "cached" || status === "stale") {
    return "border-amber-400/40 bg-amber-400/10 text-amber-200";
  }
  if (status === "source_unavailable") {
    return "border-omi-market-down/40 bg-omi-market-down/10 text-omi-market-down";
  }
  return "border-omi-border-subtle bg-omi-surface-muted text-omi-text-muted";
}

function sourceLabel(source: string | undefined) {
  if (source === "twse_mis_quote_depth") return "TWSE MIS";
  if (source === "omi_quote_depth_preview") return "PREVIEW / TWSE MIS";

  return source ?? "-";
}

function previewMessage(mode: TaiwanStockQuoteDepthPreviewMode) {
  return mode === "preopen"
    ? "預覽模式：用最近快照示範試撮五檔版型，非真實委託或即時報價。"
    : "預覽模式：用最近快照示範盤中五檔版型，非真實委託或即時報價。";
}

function previewPhaseLabel(mode: TaiwanStockQuoteDepthPreviewMode) {
  return mode === "preopen" ? "試撮預覽" : "盤中預覽";
}

function previewSessionPhase(mode: TaiwanStockQuoteDepthPreviewMode) {
  return mode === "preopen" ? "preopen_auction" : "regular_live";
}

function previewTick(price: number) {
  if (price >= 1000) return 5;
  if (price >= 500) return 1;
  if (price >= 100) return 0.5;
  if (price >= 50) return 0.1;
  if (price >= 10) return 0.05;

  return 0.01;
}

function roundPreviewPrice(price: number) {
  return Number(price.toFixed(2));
}

function previewBasePrice(quoteDepth: TaiwanStockQuoteDepthRead | null) {
  const candidates = [
    quoteDepth?.last_price,
    quoteDepth?.previous_close,
    quoteDepth?.open_price,
    quoteDepth?.high_price,
    quoteDepth?.low_price,
  ];

  return (
    candidates.find((value): value is number => typeof value === "number" && Number.isFinite(value)) ??
    100
  );
}

function buildPreviewLevels(
  quoteDepth: TaiwanStockQuoteDepthRead | null,
  basePrice: number,
  mode: TaiwanStockQuoteDepthPreviewMode,
  side: "bid" | "ask"
): TaiwanStockQuoteDepthLevel[] {
  const sourceLevels = side === "bid" ? quoteDepth?.bid_levels : quoteDepth?.ask_levels;
  const sizes =
    mode === "preopen"
      ? side === "bid"
        ? [468, 320, 210, 144, 92]
        : [382, 275, 198, 132, 86]
      : side === "bid"
        ? [188, 156, 127, 92, 64]
        : [172, 141, 116, 88, 57];
  const tick = previewTick(basePrice);

  return Array.from({ length: 5 }, (_, index) => {
    const level = index + 1;
    const sourceLevel = sourceLevels?.[index];
    const offset = side === "bid" ? -tick * index : tick * (index + 1);
    const fallbackPrice = roundPreviewPrice(Math.max(tick, basePrice + offset));

    return {
      level,
      price: sourceLevel?.price ?? fallbackPrice,
      size_lots: sourceLevel?.size_lots ?? sizes[index],
    };
  });
}

function sumPreviewSide(levels: TaiwanStockQuoteDepthLevel[]) {
  const total = sideTotal(levels);

  return total ?? 0;
}

function applyQuoteDepthPreview(
  quoteDepth: TaiwanStockQuoteDepthRead | null,
  mode: TaiwanStockQuoteDepthPreviewMode | null | undefined
): TaiwanStockQuoteDepthRead | null {
  if (!mode) return quoteDepth;

  const basePrice = previewBasePrice(quoteDepth);
  const tick = previewTick(basePrice);
  const bidLevels = buildPreviewLevels(quoteDepth, basePrice, mode, "bid");
  const askLevels = buildPreviewLevels(quoteDepth, basePrice, mode, "ask");
  const bestBidPrice = bidLevels[0]?.price ?? null;
  const bestAskPrice = askLevels[0]?.price ?? null;
  const spread =
    bestBidPrice !== null && bestAskPrice !== null
      ? roundPreviewPrice(Math.max(0, bestAskPrice - bestBidPrice))
      : null;
  const spreadPct =
    spread !== null && basePrice > 0 ? Number(((spread / basePrice) * 100).toFixed(2)) : null;
  const previousClose = quoteDepth?.previous_close ?? basePrice;
  const change =
    quoteDepth?.change ??
    (previousClose > 0 ? roundPreviewPrice(basePrice - previousClose) : null);
  const changePct =
    quoteDepth?.change_pct ??
    (previousClose > 0 ? Number((((basePrice - previousClose) / previousClose) * 100).toFixed(2)) : null);

  // Display-only preview. Do not feed this object back into backend snapshots.
  return {
    stock_id: quoteDepth?.stock_id ?? "PREVIEW",
    stock_name: quoteDepth?.stock_name ?? null,
    market: quoteDepth?.market ?? "TW",
    provider: "preview",
    source: "omi_quote_depth_preview",
    source_url: quoteDepth?.source_url ?? null,
    exchange_channel: quoteDepth?.exchange_channel ?? null,
    session_phase: previewSessionPhase(mode),
    phase_label: previewPhaseLabel(mode),
    trade_date: quoteDepth?.trade_date ?? quoteDepth?.freshness.expected_trade_date ?? null,
    quote_time: quoteDepth?.quote_time ?? null,
    fetched_at: quoteDepth?.fetched_at ?? null,
    last_price: quoteDepth?.last_price ?? basePrice,
    previous_close: previousClose,
    open_price: quoteDepth?.open_price ?? basePrice,
    high_price: quoteDepth?.high_price ?? roundPreviewPrice(basePrice + tick * 4),
    low_price: quoteDepth?.low_price ?? roundPreviewPrice(Math.max(tick, basePrice - tick * 4)),
    change,
    change_pct: changePct,
    total_volume_lots: quoteDepth?.total_volume_lots ?? (mode === "preopen" ? 12_480 : 28_640),
    best_bid_price: bestBidPrice,
    best_bid_size_lots: bidLevels[0]?.size_lots ?? null,
    best_ask_price: bestAskPrice,
    best_ask_size_lots: askLevels[0]?.size_lots ?? null,
    bid_total_size_lots: sumPreviewSide(bidLevels),
    ask_total_size_lots: sumPreviewSide(askLevels),
    spread,
    spread_pct: spreadPct,
    bid_levels: bidLevels,
    ask_levels: askLevels,
    depth_available: true,
    freshness: {
      status: "preview",
      is_live: false,
      is_stale: false,
      age_seconds: quoteDepth?.freshness.age_seconds ?? null,
      expected_trade_date: quoteDepth?.freshness.expected_trade_date ?? quoteDepth?.trade_date ?? null,
      message: previewMessage(mode),
      source_error: null,
    },
  };
}

function depthMaxSize(quoteDepth: TaiwanStockQuoteDepthRead | null) {
  if (!quoteDepth) return 1;
  const sizes = [...quoteDepth.bid_levels, ...quoteDepth.ask_levels]
    .map((level) => level.size_lots)
    .filter((value): value is number => typeof value === "number" && Number.isFinite(value));
  return Math.max(1, ...sizes);
}

function sideTotal(levels: TaiwanStockQuoteDepthLevel[]) {
  const total = levels.reduce((sum, level) => sum + (level.size_lots ?? 0), 0);
  return total > 0 ? total : null;
}

function isFiniteNumber(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function depthPriceTone(
  price: number | null,
  previousClose: number | null | undefined
): { textClass: string; barClass: string } {
  if (!isFiniteNumber(price)) {
    return {
      textClass: "text-omi-text-muted",
      barClass: "bg-omi-text-strong/10",
    };
  }

  if (!isFiniteNumber(previousClose)) {
    return {
      textClass: "text-omi-text-strong",
      barClass: "bg-omi-text-strong/10",
    };
  }

  const diff = price - previousClose;

  if (diff > 0.000001) {
    return {
      textClass: "text-omi-market-up",
      barClass: "bg-omi-market-up/10",
    };
  }

  if (diff < -0.000001) {
    return {
      textClass: "text-omi-market-down",
      barClass: "bg-omi-market-down/10",
    };
  }

  return {
    textClass: "text-omi-text-strong",
    barClass: "bg-omi-text-strong/10",
  };
}

function DepthSideRow({
  level,
  maxSize,
  previousClose,
  side,
}: {
  level: TaiwanStockQuoteDepthLevel;
  maxSize: number;
  previousClose: number | null | undefined;
  side: "ask" | "bid";
}) {
  const size = level.size_lots ?? 0;
  const width = `${Math.max(4, Math.min(100, Math.round((size / maxSize) * 100)))}%`;
  const tone = depthPriceTone(level.price, previousClose);
  const barAnchor = side === "ask" ? "left-2" : "right-2";

  return (
    <div className="relative grid min-h-7 grid-cols-2 items-center gap-3 overflow-hidden border-t border-omi-border-subtle px-2 text-xs tabular-nums">
      <div
        aria-hidden="true"
        className={`absolute inset-y-1 ${barAnchor} ${tone.barClass}`}
        style={{ width }}
      />
      {side === "bid" ? (
        <>
          <div className="relative text-left font-semibold text-omi-text-strong">
            {formatLotUnits(level.size_lots)}
          </div>
          <div className={`relative text-right font-bold ${tone.textClass}`}>{formatPrice(level.price)}</div>
        </>
      ) : (
        <>
          <div className={`relative text-left font-bold ${tone.textClass}`}>{formatPrice(level.price)}</div>
          <div className="relative text-right font-semibold text-omi-text-strong">
            {formatLotUnits(level.size_lots)}
          </div>
        </>
      )}
    </div>
  );
}

function DepthSide({
  levels,
  maxSize,
  previousClose,
  side,
}: {
  levels: TaiwanStockQuoteDepthLevel[];
  maxSize: number;
  previousClose: number | null | undefined;
  side: "ask" | "bid";
}) {
  const total = sideTotal(levels);

  return (
    <div className="min-w-0 overflow-hidden border border-omi-border-subtle bg-omi-surface-muted">
      <div className="grid grid-cols-2 gap-3 px-2 py-1.5 text-[10px] font-bold uppercase tracking-[0.12em] text-omi-text-muted">
        {side === "bid" ? (
          <>
            <div className="text-left">張數</div>
            <div className="text-right">買價</div>
          </>
        ) : (
          <>
            <div className="text-left">賣價</div>
            <div className="text-right">張數</div>
          </>
        )}
      </div>
      {levels.map((level) => (
        <DepthSideRow
          key={`${side}-${level.level}`}
          level={level}
          maxSize={maxSize}
          previousClose={previousClose}
          side={side}
        />
      ))}
      <div className="grid min-h-8 grid-cols-2 items-center gap-3 border-t border-omi-border-subtle bg-black/10 px-2 text-sm font-bold tabular-nums text-omi-text-strong">
        {side === "bid" ? (
          <>
            <div className="text-left">{formatLotUnits(total)}</div>
            <div />
          </>
        ) : (
          <>
            <div />
            <div className="text-right">{formatLotUnits(total)}</div>
          </>
        )}
      </div>
    </div>
  );
}

function QuoteMetric({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: string;
}) {
  return (
    <div className="min-w-0 border border-omi-border-subtle bg-omi-surface-muted px-2 py-1.5">
      <div className="truncate text-[10px] font-semibold uppercase tracking-[0.14em] text-omi-text-muted">
        {label}
      </div>
      <div className={`mt-0.5 truncate text-xs font-bold tabular-nums ${tone ?? "text-omi-text-strong"}`}>
        {value}
      </div>
    </div>
  );
}

export default function QuoteDepthPanel({
  quoteDepth,
  loadState,
  quoteDepthPreviewMode = null,
}: QuoteDepthPanelProps) {
  const activePreviewMode = quoteDepthPreviewMode;
  const displayQuoteDepth = applyQuoteDepthPreview(quoteDepth, activePreviewMode);
  const isPreview = activePreviewMode !== null;
  const status = displayQuoteDepth?.freshness.status;
  const phaseLabel = displayQuoteDepth?.phase_label ?? "五檔";
  const bidLevels = displayQuoteDepth?.bid_levels ?? [];
  const askLevels = displayQuoteDepth?.ask_levels ?? [];
  const showDepth = bidLevels.length > 0 || askLevels.length > 0;
  const maxSize = depthMaxSize(displayQuoteDepth);
  const message =
    displayQuoteDepth?.freshness.message ??
    (loadState === "loading"
      ? "五檔資料載入中。"
      : loadState === "error"
        ? "五檔資料讀取失敗。"
        : "尚無五檔資料。");
  const isError = loadState === "error" && !displayQuoteDepth;
  const footerStatus = displayQuoteDepth?.freshness.is_stale || showDepth ? message : phaseLabel;

  return (
    <div className="border-b border-omi-border-subtle px-5 py-3" data-testid="quote-depth-panel">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-omi-text-muted">
            QUOTE DEPTH
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-2">
            <span
              className={`inline-flex items-center border px-2 py-0.5 text-[11px] font-bold ${statusClass(status)}`}
            >
              {phaseLabel}
            </span>
            {isPreview ? (
              <span className="inline-flex items-center border border-sky-500/50 bg-sky-500/10 px-2 py-0.5 text-[11px] font-bold text-omi-text-strong">
                預覽資料
              </span>
            ) : null}
            <span className="text-[11px] text-omi-text-muted">
              {sourceLabel(displayQuoteDepth?.source)}
            </span>
          </div>
        </div>
        <div className="shrink-0 text-right">
          <div className={`text-lg font-bold tabular-nums ${valueTone(displayQuoteDepth?.change)}`}>
            {formatPrice(displayQuoteDepth?.last_price)}
          </div>
          <div className={`text-[11px] font-semibold tabular-nums ${valueTone(displayQuoteDepth?.change_pct)}`}>
            {formatPrice(displayQuoteDepth?.change)} / {formatPct(displayQuoteDepth?.change_pct)}
          </div>
        </div>
      </div>

      {showDepth ? (
        <div className="mt-3 grid grid-cols-2 gap-2">
          <DepthSide
            levels={bidLevels}
            maxSize={maxSize}
            previousClose={displayQuoteDepth?.previous_close}
            side="bid"
          />
          <DepthSide
            levels={askLevels}
            maxSize={maxSize}
            previousClose={displayQuoteDepth?.previous_close}
            side="ask"
          />
        </div>
      ) : (
        <div className="mt-3 grid grid-cols-2 gap-2">
          <QuoteMetric label="Open" value={formatPrice(displayQuoteDepth?.open_price)} />
          <QuoteMetric label="High" value={formatPrice(displayQuoteDepth?.high_price)} tone="text-omi-market-up" />
          <QuoteMetric label="Low" value={formatPrice(displayQuoteDepth?.low_price)} tone="text-omi-market-down" />
          <QuoteMetric label="Volume" value={formatLotUnits(displayQuoteDepth?.total_volume_lots)} />
        </div>
      )}

      {!showDepth ? (
        <div className="mt-3 border border-omi-border-subtle bg-omi-surface-muted px-3 py-3 text-sm text-omi-text-muted">
          <div className={isError ? "text-omi-market-down" : ""}>{message}</div>
        </div>
      ) : null}

      {displayQuoteDepth ? (
        <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-[11px] text-omi-text-muted">
          <span>{formatDateTime(displayQuoteDepth.quote_time)}</span>
          <span className={displayQuoteDepth.freshness.is_stale ? "text-amber-200" : ""}>{footerStatus}</span>
        </div>
      ) : null}
    </div>
  );
}
