"use client";

import {
  formatDateTime,
  formatLotUnits,
  formatPct,
  formatPrice,
  valueTone,
} from "@/components/stock-detail/StockDetailDataViews";
import { StateSurface } from "@/components/LoadingPlaceholders";
import type {
  TaiwanQuoteContractReplayRead,
  TaiwanQuoteContractReplaySnapshotRead,
  TaiwanStockQuoteDepthLevel,
  TaiwanStockQuoteDepthPreviewMode,
  TaiwanStockQuoteDepthRead,
} from "@/types/market";
import { useMemo, useState } from "react";

type QuoteDepthLoadState = "idle" | "loading" | "success" | "error";

type QuoteDepthPanelProps = {
  quoteDepth: TaiwanStockQuoteDepthRead | null;
  loadState: QuoteDepthLoadState;
  quoteDepthPreviewMode?: TaiwanStockQuoteDepthPreviewMode | null;
  quoteReplay?: TaiwanQuoteContractReplayRead | null;
  replayLoadState?: "idle" | "loading" | "success" | "error";
};

type QuoteDepthViewMode = "live" | "replay";
type QuoteDepthViewSelection = {
  key: string;
  mode: QuoteDepthViewMode;
};

function isAuctionReplaySnapshot(
  snapshot: TaiwanQuoteContractReplaySnapshotRead
) {
  const quote = snapshot.quote;
  return Boolean(
    snapshot.status.startsWith("captured") &&
      quote &&
      (quote.session_phase === "preopen_auction" ||
        quote.session_phase === "closing_auction" ||
        quote.instrument_phase === "preopen_auction" ||
        quote.instrument_phase === "opening_auction_delayed" ||
        quote.instrument_phase === "closing_auction" ||
        quote.instrument_phase === "closing_auction_delayed")
  );
}

function isPreopenReplaySnapshot(
  snapshot: TaiwanQuoteContractReplaySnapshotRead
) {
  const quote = snapshot.quote;
  return Boolean(
    snapshot.status.startsWith("captured") &&
      quote &&
      (quote.session_phase === "preopen_auction" ||
        quote.instrument_phase === "preopen_auction" ||
        quote.instrument_phase === "opening_auction_delayed")
  );
}

function statusClass(status: string | undefined) {
  if (status === "preview" || status === "replay") {
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
    auction_book_available: mode === "preopen",
    auction_book_status: mode === "preopen" ? "depth_and_indicative_match" : "unavailable",
    auction_book_time: quoteDepth?.quote_time ?? null,
    auction_best_bid: mode === "preopen" ? bestBidPrice : null,
    auction_best_ask: mode === "preopen" ? bestAskPrice : null,
    auction_indicative_available: mode === "preopen",
    auction_indicative_status: mode === "preopen" ? "available" : "not_provided",
    auction_phase: mode === "preopen" ? "preopen_auction" : null,
    auction_event_time: quoteDepth?.quote_time ?? null,
    indicative_match_available: mode === "preopen",
    indicative_match_price: mode === "preopen" ? basePrice : null,
    indicative_match_volume_lots: mode === "preopen" ? 2_046 : null,
    indicative_match_price_source_field: mode === "preopen" ? "pz" : null,
    indicative_match_volume_source_field: mode === "preopen" ? "ps" : null,
    indicative_match_status_source_field: mode === "preopen" ? "ts" : null,
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

function formatVolumeValue(value: number | null | undefined, unit: "張" | "股") {
  if (!isFiniteNumber(value)) return "-";

  return `${new Intl.NumberFormat("zh-TW").format(Math.round(value))} ${unit}`;
}

function formatVolumeDifference(value: number | null | undefined) {
  if (!isFiniteNumber(value)) return null;

  const absoluteShares = Math.round(Math.abs(value));
  if (absoluteShares % 1_000 === 0) {
    return `${new Intl.NumberFormat("zh-TW").format(absoluteShares / 1_000)} 張`;
  }

  return `${new Intl.NumberFormat("zh-TW").format(absoluteShares)} 股`;
}

function formatOfficialVolumeValue(value: number | null | undefined) {
  if (!isFiniteNumber(value)) return "-";

  const shares = Math.round(value);
  return shares % 1_000 === 0
    ? formatVolumeValue(shares / 1_000, "張")
    : formatVolumeValue(shares, "股");
}

function isFiniteNumber(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

type VolumeSummaryStatus = {
  label: string;
  message: string;
  toneClass: string;
};

function volumeSummaryStatus(
  quoteDepth: TaiwanStockQuoteDepthRead,
  isPreview: boolean
): VolumeSummaryStatus {
  if (isPreview) {
    return {
      label: "預覽量能",
      message: "量能數字僅供版型預覽，不供研究判斷。",
      toneClass: "border-omi-info bg-omi-info-soft text-omi-info-strong",
    };
  }

  const reconciliation = quoteDepth.volume_reconciliation;

  if (reconciliation?.status === "scope_different") {
    const differenceShares = formatVolumeDifference(reconciliation.difference_shares);
    const differenceText = differenceShares ? `；目前差額 ${differenceShares}` : "";

    return {
      label: "口徑不同",
      message: `MIS v 是正規盤整張累計，官方日量是較廣的日彙總${differenceText}。兩者都保留，但不可直接對帳。`,
      toneClass: "border-omi-info bg-omi-info-soft text-omi-info-strong",
    };
  }

  if (reconciliation?.status === "reconciled") {
    return {
      label: "已對帳",
      message: "MIS 累計量與正式日量在容許範圍內，可供量能判斷。",
      toneClass: "border-omi-success bg-omi-success-soft text-omi-success-strong",
    };
  }

  if (reconciliation?.status === "mismatch") {
    const differenceShares = formatVolumeDifference(reconciliation.difference_shares);
    const differencePct = isFiniteNumber(reconciliation.difference_pct)
      ? `${Math.abs(reconciliation.difference_pct).toFixed(2)}%`
      : null;
    const differenceText =
      differenceShares && differencePct
        ? `相差 ${differenceShares}（${differencePct}）`
        : "數值未對齊";

    return {
      label: "資料異常",
      message: `同口徑成交量${differenceText}，量能判斷暫不採用。`,
      toneClass: "border-omi-warning bg-omi-warning-soft text-omi-warning-strong",
    };
  }

  if (reconciliation?.reason === "official_daily_volume_not_available") {
    return {
      label: "待正式量",
      message: "盤中先顯示 MIS 成交量，正式日量待收盤資料。",
      toneClass: "border-omi-border-strong bg-omi-surface text-omi-text-muted",
    };
  }

  if (reconciliation?.reason === "trade_dates_do_not_match") {
    return {
      label: "日期不同",
      message: "MIS 快照與正式日量的交易日期不同，暫不對帳。",
      toneClass: "border-omi-warning bg-omi-warning-soft text-omi-warning-strong",
    };
  }

  if (reconciliation?.reason === "trade_date_not_available") {
    return {
      label: "未對帳",
      message: "交易日期資訊不足，量能暫不供研究判斷。",
      toneClass: "border-omi-warning bg-omi-warning-soft text-omi-warning-strong",
    };
  }

  if (reconciliation?.reason === "official_daily_volume_not_positive") {
    return {
      label: "正式量異常",
      message: "正式日量不是有效正值，量能暫不供研究判斷。",
      toneClass: "border-omi-warning bg-omi-warning-soft text-omi-warning-strong",
    };
  }

  const providerVolumeAvailable =
    quoteDepth.provider_volume_available ??
    isFiniteNumber(quoteDepth.cumulative_volume_lots ?? quoteDepth.total_volume_lots);

  return providerVolumeAvailable
    ? {
        label: "未對帳",
        message: "目前僅有 MIS 成交量，尚無可比較的正式日量。",
        toneClass: "border-omi-border-strong bg-omi-surface text-omi-text-muted",
      }
    : {
        label: "量能缺資料",
        message: "TWSE MIS 未提供可用的累計成交量。",
        toneClass: "border-omi-warning bg-omi-warning-soft text-omi-warning-strong",
      };
}

function VolumeMetric({
  label,
  sourceField,
  value,
  testId,
  className = "",
}: {
  label: string;
  sourceField?: string;
  value: string;
  testId: string;
  className?: string;
}) {
  return (
    <div
      className={`min-w-0 px-2.5 py-2 sm:px-3 ${className}`}
      data-testid={testId}
    >
      <dt className="flex items-baseline gap-1 text-[10px] font-bold tracking-[0.08em] text-omi-text-muted">
        <span>{label}</span>
        {sourceField ? (
          <span className="font-mono font-medium normal-case tracking-normal text-omi-text-muted/70">
            {sourceField}
          </span>
        ) : null}
      </dt>
      <dd className="mt-0.5 truncate text-sm font-bold tabular-nums text-omi-text-strong">
        {value}
      </dd>
    </div>
  );
}

function hasQuoteVolumeSummary(quoteDepth: TaiwanStockQuoteDepthRead) {
  if (quoteDepth.session_phase === "preopen_auction") return false;

  const cumulativeLots = quoteDepth.cumulative_volume_lots ?? quoteDepth.total_volume_lots;
  return (
    isFiniteNumber(cumulativeLots) ||
    isFiniteNumber(quoteDepth.last_trade_volume_lots) ||
    isFiniteNumber(quoteDepth.official_daily_volume_shares) ||
    quoteDepth.volume_status !== undefined ||
    quoteDepth.volume_reconciliation !== undefined
  );
}

function QuoteVolumeSummary({
  quoteDepth,
  isPreview,
}: {
  quoteDepth: TaiwanStockQuoteDepthRead;
  isPreview: boolean;
}) {
  if (!hasQuoteVolumeSummary(quoteDepth)) return null;

  const cumulativeLots = quoteDepth.cumulative_volume_lots ?? quoteDepth.total_volume_lots;
  const status = volumeSummaryStatus(quoteDepth, isPreview);

  return (
    <section
      aria-label="成交量摘要"
      className="overflow-hidden border border-omi-border-subtle bg-omi-surface-muted"
      data-testid="quote-volume-summary"
    >
      <div className="flex items-center justify-between gap-3 border-b border-omi-border-subtle px-2.5 py-1.5 sm:px-3">
        <div className="text-[10px] font-bold uppercase tracking-[0.14em] text-omi-text-muted">
          成交量
        </div>
        <span
          className={`inline-flex shrink-0 items-center border px-1.5 py-0.5 text-[10px] font-bold ${status.toneClass}`}
          data-testid="quote-volume-status"
        >
          {status.label}
        </span>
      </div>
      <dl className="grid grid-cols-2">
        <VolumeMetric
          label="最近一筆"
          sourceField={quoteDepth.last_trade_volume_source_field ?? "tv"}
          value={formatVolumeValue(quoteDepth.last_trade_volume_lots, "張")}
          testId="quote-volume-last-trade"
          className="border-r border-omi-border-subtle"
        />
        <VolumeMetric
          label="正規盤累計"
          sourceField={quoteDepth.volume_source_field ?? "v"}
          value={formatVolumeValue(cumulativeLots, "張")}
          testId="quote-volume-cumulative"
        />
        <VolumeMetric
          label="正式日量"
          value={formatOfficialVolumeValue(quoteDepth.official_daily_volume_shares)}
          testId="quote-volume-official"
          className="col-span-2 border-t border-omi-border-subtle"
        />
      </dl>
      <div
        className="border-t border-omi-border-subtle px-2.5 py-1.5 text-[11px] leading-4 text-omi-text-muted sm:px-3"
        data-testid="quote-volume-message"
      >
        {status.message}
      </div>
    </section>
  );
}

function QuoteAuctionSummary({
  quoteDepth,
  isPreview,
}: {
  quoteDepth: TaiwanStockQuoteDepthRead;
  isPreview: boolean;
}) {
  const isAuction =
    quoteDepth.session_phase === "preopen_auction" ||
    quoteDepth.session_phase === "closing_auction";
  if (!isAuction) return null;

  const available =
    quoteDepth.indicative_match_available === true &&
    isFiniteNumber(quoteDepth.indicative_match_price) &&
    isFiniteNumber(quoteDepth.indicative_match_volume_lots);
  const phaseLabel =
    quoteDepth.session_phase === "closing_auction" ? "收盤試撮" : "開盤試撮";
  const statusLabel = isPreview ? "預覽" : available ? "試算揭露" : "來源未提供";
  const statusClassName = isPreview
    ? "border-omi-info bg-omi-info-soft text-omi-info-strong"
    : available
      ? "border-omi-success bg-omi-success-soft text-omi-success-strong"
      : "border-omi-warning bg-omi-warning-soft text-omi-warning-strong";

  return (
    <section
      aria-label={`${phaseLabel}摘要`}
      className="overflow-hidden border border-omi-border-subtle bg-omi-surface-muted"
      data-testid="quote-auction-summary"
    >
      <div className="flex items-center justify-between gap-3 border-b border-omi-border-subtle px-2.5 py-1.5 sm:px-3">
        <div className="text-[10px] font-bold uppercase tracking-[0.14em] text-omi-text-muted">
          {phaseLabel}
        </div>
        <span
          className={`inline-flex shrink-0 items-center border px-1.5 py-0.5 text-[10px] font-bold ${statusClassName}`}
          data-testid="quote-auction-status"
        >
          {statusLabel}
        </span>
      </div>
      <dl className="grid grid-cols-2">
        <VolumeMetric
          label="試算參考價"
          sourceField={quoteDepth.indicative_match_price_source_field ?? "pz"}
          value={formatPrice(quoteDepth.indicative_match_price)}
          testId="quote-auction-price"
          className="border-r border-omi-border-subtle"
        />
        <VolumeMetric
          label="試算參考量"
          sourceField={quoteDepth.indicative_match_volume_source_field ?? "ps"}
          value={formatVolumeValue(quoteDepth.indicative_match_volume_lots, "張")}
          testId="quote-auction-volume"
        />
      </dl>
      <div
        className="border-t border-omi-border-subtle px-2.5 py-1.5 text-[11px] leading-4 text-omi-text-muted sm:px-3"
        data-testid="quote-auction-message"
      >
        {available || isPreview
          ? "試算價量是模擬撮合結果，尚非實際成交；上下五檔張數是未成交委託量。"
          : "TWSE MIS 本次快照未提供有效試算價量；仍可查看已揭露的五檔委託張數。"}
      </div>
    </section>
  );
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
      <div className="min-h-[140px]">
        {levels.length > 0 ? (
          levels.map((level) => (
            <DepthSideRow
              key={`${side}-${level.level}`}
              level={level}
              maxSize={maxSize}
              previousClose={previousClose}
              side={side}
            />
          ))
        ) : (
          <div
            className="flex min-h-[140px] items-center justify-center border-t border-omi-border-subtle px-3 text-center"
            data-testid={`quote-depth-${side}-empty`}
          >
            <div>
              <div className="text-xs font-semibold text-omi-text-strong">
                {side === "bid" ? "目前無有效買價" : "目前無有效賣價"}
              </div>
              <div className="mt-1 text-[10px] leading-4 text-omi-text-muted">
                來源未提供此側五檔
              </div>
            </div>
          </div>
        )}
      </div>
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
  quoteReplay = null,
  replayLoadState = "idle",
}: QuoteDepthPanelProps) {
  const [viewSelection, setViewSelection] =
    useState<QuoteDepthViewSelection | null>(null);
  const replaySnapshot = useMemo(
    () => {
      const snapshots = [...(quoteReplay?.snapshots ?? [])].reverse();
      return (
        snapshots.find(isPreopenReplaySnapshot) ??
        snapshots.find(isAuctionReplaySnapshot) ??
        null
      );
    },
    [quoteReplay]
  );
  const replayQuote = replaySnapshot?.quote ?? null;
  const replayAvailable = replayQuote !== null;
  const viewKey = `${quoteDepth?.stock_id ?? "empty"}:${quoteReplay?.trade_date ?? "none"}`;
  const viewMode =
    viewSelection?.key === viewKey ? viewSelection.mode : "live";

  const activePreviewMode = quoteDepthPreviewMode;
  const replayDisplayQuote = replayQuote
    ? {
        ...replayQuote,
        phase_label: `試撮快照 ${replaySnapshot?.capture_slot ?? ""}`.trim(),
        freshness: {
          ...replayQuote.freshness,
          status: "replay",
          is_live: false,
          message: `保存快照回放 · ${quoteReplay?.trade_date ?? "-"} ${
            replaySnapshot?.capture_slot ?? "-"
          }`,
        },
      }
    : null;
  const displayQuoteDepth =
    activePreviewMode === null && viewMode === "replay"
      ? replayDisplayQuote
      : applyQuoteDepthPreview(quoteDepth, activePreviewMode);
  const isPreview = activePreviewMode !== null;
  const isReplay = activePreviewMode === null && viewMode === "replay";
  const showAuctionSummary = Boolean(
    displayQuoteDepth &&
      (displayQuoteDepth.session_phase === "preopen_auction" ||
        displayQuoteDepth.session_phase === "closing_auction")
  );
  const showVolumeSummary = Boolean(
    displayQuoteDepth && hasQuoteVolumeSummary(displayQuoteDepth)
  );
  const showSummaryColumn = showAuctionSummary || showVolumeSummary;
  const status = displayQuoteDepth?.freshness.status;
  const phaseLabel = displayQuoteDepth?.phase_label ?? "五檔";
  const bidLevels = displayQuoteDepth?.bid_levels ?? [];
  const askLevels = displayQuoteDepth?.ask_levels ?? [];
  const showDepth = bidLevels.length > 0 || askLevels.length > 0;
  const maxSize = depthMaxSize(displayQuoteDepth);
  const indicativePrice =
    displayQuoteDepth?.indicative_match_available &&
    isFiniteNumber(displayQuoteDepth.indicative_match_price)
      ? displayQuoteDepth.indicative_match_price
      : null;
  const headlinePrice = indicativePrice ?? displayQuoteDepth?.last_price;
  const headlineChange =
    indicativePrice !== null && isFiniteNumber(displayQuoteDepth?.previous_close)
      ? indicativePrice - displayQuoteDepth.previous_close
      : displayQuoteDepth?.change;
  const headlineChangePct =
    indicativePrice !== null &&
    isFiniteNumber(displayQuoteDepth?.previous_close) &&
    displayQuoteDepth.previous_close !== 0
      ? (headlineChange! / displayQuoteDepth.previous_close) * 100
      : displayQuoteDepth?.change_pct;
  const message =
    displayQuoteDepth?.freshness.message ??
    (loadState === "loading"
      ? "五檔資料載入中。"
      : loadState === "error"
        ? "五檔資料讀取失敗。"
        : "尚無五檔資料。");
  const isError = loadState === "error" && !displayQuoteDepth;
  const footerStatus = displayQuoteDepth?.freshness.is_stale || showDepth ? message : phaseLabel;
  const observationTimeLabel = displayQuoteDepth?.quote_time
    ? formatDateTime(displayQuoteDepth.quote_time)
    : displayQuoteDepth?.presentation_trade_date
      ? `交易日 ${displayQuoteDepth.presentation_trade_date}`
      : "-";

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
            {isReplay ? (
              <span className="inline-flex items-center border border-omi-info bg-omi-info-soft px-2 py-0.5 text-[11px] font-bold text-omi-info-strong">
                保存回放
              </span>
            ) : null}
            <span className="text-[11px] text-omi-text-muted">
              {sourceLabel(displayQuoteDepth?.source)}
            </span>
          </div>
        </div>
        <div className="shrink-0 text-right">
          <div className={`text-lg font-bold tabular-nums ${valueTone(headlineChange)}`}>
            {formatPrice(headlinePrice)}
          </div>
          <div className={`text-[11px] font-semibold tabular-nums ${valueTone(headlineChangePct)}`}>
            {formatPrice(headlineChange)} / {formatPct(headlineChangePct)}
          </div>
        </div>
      </div>

      {activePreviewMode === null ? (
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-y border-omi-border-subtle py-2">
          <div className="inline-flex border border-omi-border bg-omi-surface-subtle p-0.5">
            <button
              type="button"
              data-testid="quote-depth-mode-live"
              onClick={() => setViewSelection({ key: viewKey, mode: "live" })}
              className={[
                "h-7 px-2.5 text-xs font-semibold transition",
                viewMode === "live"
                  ? "bg-omi-control text-omi-text-inverse"
                  : "text-omi-text-muted hover:bg-omi-surface",
              ].join(" ")}
            >
              即時
            </button>
            <button
              type="button"
              data-testid="quote-depth-mode-replay"
              disabled={!replayAvailable}
              onClick={() => setViewSelection({ key: viewKey, mode: "replay" })}
              className={[
                "h-7 px-2.5 text-xs font-semibold transition",
                viewMode === "replay"
                  ? "bg-omi-control text-omi-text-inverse"
                  : "text-omi-text-muted hover:bg-omi-surface",
                !replayAvailable
                  ? "cursor-not-allowed opacity-45 hover:bg-transparent"
                  : "",
              ].join(" ")}
            >
              試撮快照
            </button>
          </div>
          <span className="text-[11px] text-omi-text-muted" data-testid="quote-depth-replay-coverage">
            {replayLoadState === "loading"
              ? "快照索引讀取中"
              : replayAvailable
                ? `${quoteReplay?.trade_date ?? "-"} · ${quoteReplay?.captured_count ?? 0}/${
                    quoteReplay?.required_count ?? 0
                  } slots`
                : "目前標的無試撮快照"}
          </span>
        </div>
      ) : null}

      <div
        className={[
          "mt-3 grid gap-3",
          showSummaryColumn
            ? "lg:grid-cols-[minmax(0,2fr)_minmax(13rem,1fr)] lg:items-start"
            : "",
        ].join(" ")}
        data-testid="quote-depth-content"
      >
        <div className="min-w-0" data-testid="quote-depth-book-column">
          {showDepth ? (
            <div className="grid grid-cols-2 gap-2" data-testid="quote-depth-book">
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
            <div className="grid grid-cols-2 gap-2">
              <QuoteMetric label="Open" value={formatPrice(displayQuoteDepth?.open_price)} />
              <QuoteMetric label="High" value={formatPrice(displayQuoteDepth?.high_price)} tone="text-omi-market-up" />
              <QuoteMetric label="Low" value={formatPrice(displayQuoteDepth?.low_price)} tone="text-omi-market-down" />
              <QuoteMetric label="Volume" value={formatLotUnits(displayQuoteDepth?.total_volume_lots)} />
            </div>
          )}

          {!showDepth ? (
            <StateSurface
              title={message}
              tone={isError ? "danger" : loadState === "loading" ? "loading" : "empty"}
              busy={loadState === "loading"}
              compact
              className="mt-3"
            />
          ) : null}
        </div>

        {showSummaryColumn && displayQuoteDepth ? (
          <div className="min-w-0 space-y-3" data-testid="quote-depth-summary-column">
            {showAuctionSummary ? (
              <QuoteAuctionSummary quoteDepth={displayQuoteDepth} isPreview={isPreview} />
            ) : null}
            {showVolumeSummary ? (
              <QuoteVolumeSummary quoteDepth={displayQuoteDepth} isPreview={isPreview} />
            ) : null}
          </div>
        ) : null}
      </div>

      {displayQuoteDepth ? (
        <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-[11px] text-omi-text-muted">
          <span>{observationTimeLabel}</span>
          <span className={displayQuoteDepth.freshness.is_stale ? "text-amber-200" : ""}>{footerStatus}</span>
        </div>
      ) : null}
    </div>
  );
}
