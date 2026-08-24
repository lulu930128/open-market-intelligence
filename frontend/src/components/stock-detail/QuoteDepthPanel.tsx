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
  TaiwanRealtimeMarketStreamRead,
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
  quoteStream?: TaiwanRealtimeMarketStreamRead | null;
  quoteStreamLoadState?: QuoteDepthLoadState;
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

function sourceLabel(
  quoteDepth:
    | Pick<
        TaiwanStockQuoteDepthRead,
        "source" | "primary_provider" | "primary_source_status" | "fallback_used"
      >
    | null
    | undefined
) {
  const source = quoteDepth?.source;
  if (source === "kgi_superpy_quote_all") return "KGI SUPER PY";
  if (source === "twse_mis_quote_depth") {
    if (quoteDepth?.primary_provider === "kgi_superpy" && quoteDepth.fallback_used) {
      const primaryStatus = {
        starting: "連線中",
        subscribing: "訂閱中",
        reconnecting: "重連中",
        resubscribe_requested: "重連中",
        reconnect_failed: "重連失敗",
        stale: "逾時",
        unavailable: "不可用",
        invalid: "格式異常",
      }[quoteDepth.primary_source_status ?? ""];
      return primaryStatus ? `TWSE MIS · KGI ${primaryStatus}` : "TWSE MIS";
    }
    return "TWSE MIS";
  }
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

function depthMaxSize(
  bidLevels: TaiwanStockQuoteDepthLevel[],
  askLevels: TaiwanStockQuoteDepthLevel[]
) {
  const sizes = [...bidLevels, ...askLevels]
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

function isFiniteNumber(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function formatEventClock(value: string | null | undefined) {
  if (!value) return "--:--:--";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "--:--:--";
  return new Intl.DateTimeFormat("zh-TW", {
    timeZone: "Asia/Taipei",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(parsed);
}

function streamStatusLabel(
  quoteStream: TaiwanRealtimeMarketStreamRead | null,
  loadState: QuoteDepthLoadState
) {
  if (loadState === "loading") return "連線中";
  if (loadState === "error") return "串流中斷";
  if (!quoteStream) return "尚無串流";
  return {
    live: "即時",
    starting: "啟動中",
    subscribing: "訂閱中",
    reconnecting: "重連中",
    resubscribe_requested: "重連中",
    stale: "已逾時",
    unavailable: "不可用",
    disabled: "未啟用",
    not_subscribed: "未訂閱",
  }[quoteStream.status] ?? quoteStream.status;
}

function tradeDirectionTone(direction: string) {
  if (direction === "up") return "text-omi-market-up";
  if (direction === "down") return "text-omi-market-down";
  return "text-omi-text-strong";
}

function RecentTradesPanel({
  quoteStream,
  loadState,
}: {
  quoteStream: TaiwanRealtimeMarketStreamRead | null;
  loadState: QuoteDepthLoadState;
}) {
  const trades = quoteStream?.recent_trades ?? [];
  const warning = quoteStream?.warnings[0] ?? null;
  const isLive = quoteStream?.status === "live" && !quoteStream.is_stale;

  return (
    <section
      aria-label="即時成交"
      className="flex h-full flex-col overflow-hidden border border-omi-border-subtle bg-omi-surface-muted"
      data-testid="quote-recent-trades"
    >
      <div className="flex items-center justify-between gap-3 border-b border-omi-border-subtle px-3 py-2">
        <div>
          <div className="text-[10px] font-bold uppercase tracking-[0.14em] text-omi-text-muted">
            即時成交
          </div>
          <div className="mt-0.5 text-[11px] text-omi-text-muted">
            KGI callback · 最近 {quoteStream?.limits.recent_trades ?? 60} 筆記憶體緩衝
          </div>
        </div>
        <span
          className={[
            "inline-flex shrink-0 items-center border px-1.5 py-0.5 text-[10px] font-bold",
            isLive
              ? "border-omi-success bg-omi-success-soft text-omi-success-strong"
              : "border-omi-border-strong bg-omi-surface text-omi-text-muted",
          ].join(" ")}
          data-testid="quote-recent-trades-status"
        >
          {streamStatusLabel(quoteStream, loadState)}
        </span>
      </div>

      <div className="grid grid-cols-[5.25rem_minmax(5rem,1fr)_minmax(4.5rem,0.8fr)_minmax(5rem,0.9fr)] gap-2 border-b border-omi-border-subtle px-3 py-1.5 text-[10px] font-bold tracking-[0.08em] text-omi-text-muted">
        <span>時間</span>
        <span className="text-right">成交價</span>
        <span className="text-right">單量</span>
        <span className="text-right">累計</span>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {trades.length > 0 ? (
          trades.map((trade) => (
            <div
              key={trade.event_id}
              className="grid min-h-8 grid-cols-[5.25rem_minmax(5rem,1fr)_minmax(4.5rem,0.8fr)_minmax(5rem,0.9fr)] items-center gap-2 border-b border-omi-border-subtle/70 px-3 text-xs tabular-nums last:border-b-0"
              data-testid="quote-recent-trade-row"
            >
              <span className="font-mono text-[11px] text-omi-text-muted">
                {formatEventClock(trade.event_time)}
              </span>
              <span className={`text-right font-bold ${tradeDirectionTone(trade.price_direction)}`}>
                {formatPrice(trade.price)}
              </span>
              <span className="text-right font-semibold text-omi-text-strong">
                {formatVolumeValue(trade.volume_lots, "張")}
              </span>
              <span className="text-right text-omi-text-muted">
                {formatVolumeValue(trade.total_volume_lots, "張")}
              </span>
            </div>
          ))
        ) : (
          <div className="flex h-full min-h-[140px] items-center justify-center px-4 text-center">
            <div>
              <div className="text-xs font-semibold text-omi-text-strong">
                {loadState === "loading" ? "等待凱基成交流" : "尚無正式成交事件"}
              </div>
              <div className="mt-1 text-[10px] leading-4 text-omi-text-muted">
                {quoteStream?.status === "not_subscribed"
                  ? "選取標的並建立 viewer lease 後才會開始收集。"
                  : "試撮事件不會混入正式成交列表。"}
              </div>
            </div>
          </div>
        )}
      </div>
      <div className="border-t border-omi-border-subtle px-3 py-1.5 text-[10px] leading-4 text-omi-text-muted">
        {warning ?? "紅綠僅表示相對前一筆觀察價變動，不代表主動買進或賣出。"}
      </div>
    </section>
  );
}

function AuctionDetailsPanel({
  quoteDepth,
  quoteStream,
  loadState,
  isReplay,
  isPreview,
  replayLabel,
  replaySnapshots,
}: {
  quoteDepth: TaiwanStockQuoteDepthRead | null;
  quoteStream: TaiwanRealtimeMarketStreamRead | null;
  loadState: QuoteDepthLoadState;
  isReplay: boolean;
  isPreview: boolean;
  replayLabel: string | null;
  replaySnapshots: TaiwanQuoteContractReplaySnapshotRead[];
}) {
  const observations = !isReplay && !isPreview ? quoteStream?.auction_observations ?? [] : [];
  const replayRows = isReplay
    ? [...replaySnapshots]
        .filter(isAuctionReplaySnapshot)
        .reverse()
        .map((snapshot) => ({
          eventId: `replay:${snapshot.capture_slot}`,
          eventTime:
            snapshot.quote?.auction_event_time ??
            snapshot.quote_time ??
            snapshot.scheduled_at,
          bestBidPrice:
            snapshot.quote?.auction_best_bid ??
            snapshot.quote?.best_bid_price ??
            null,
          bestAskPrice:
            snapshot.quote?.auction_best_ask ??
            snapshot.quote?.best_ask_price ??
            null,
          indicativePrice:
            snapshot.quote?.indicative_match_price ?? null,
          indicativeVolume: snapshot.quote?.indicative_match_volume_lots ?? null,
        }))
    : [];
  const quoteIsAuction = Boolean(
    quoteDepth &&
      (quoteDepth.session_phase === "preopen_auction" ||
        quoteDepth.session_phase === "closing_auction")
  );
  const snapshotAvailable = Boolean(
    quoteIsAuction &&
      quoteDepth &&
      (quoteDepth.indicative_match_available ||
        isFiniteNumber(quoteDepth.indicative_match_price) ||
        isFiniteNumber(quoteDepth.indicative_match_volume_lots))
  );
  const rows =
    replayRows.length > 0
      ? replayRows
      : observations.length > 0
      ? observations.map((observation) => ({
          eventId: observation.event_id,
          eventTime: observation.event_time,
          bestBidPrice: observation.best_bid_price,
          bestAskPrice: observation.best_ask_price,
          indicativePrice: observation.indicative_match_price,
          indicativeVolume: observation.indicative_match_volume_lots,
        }))
      : snapshotAvailable && quoteDepth
        ? [
            {
              eventId: `snapshot:${quoteDepth.stock_id}:${quoteDepth.quote_time ?? "unknown"}`,
              eventTime: quoteDepth.quote_time,
              bestBidPrice: quoteDepth.best_bid_price,
              bestAskPrice: quoteDepth.best_ask_price,
              indicativePrice: quoteDepth.indicative_match_price ?? null,
              indicativeVolume: quoteDepth.indicative_match_volume_lots ?? null,
            },
          ]
        : [];
  const isLive = observations.length > 0 && quoteStream?.status === "live" && !quoteStream.is_stale;
  const statusLabel = isPreview
    ? "預覽"
    : isReplay
      ? "保存快照"
      : isLive
        ? "即時"
        : rows.length > 0
          ? "最近快照"
          : streamStatusLabel(quoteStream, loadState);
  const statusClassName = isPreview || isReplay
    ? "border-omi-info bg-omi-info-soft text-omi-info-strong"
    : isLive
      ? "border-omi-success bg-omi-success-soft text-omi-success-strong"
      : "border-omi-border-strong bg-omi-surface text-omi-text-muted";
  const sourceDescription = isPreview
    ? "版型預覽資料"
    : isReplay
      ? `${replayLabel ?? "保存的試撮快照"} · 全部依時間合併`
      : `KGI callback · 最近 ${quoteStream?.limits.auction_observations ?? 120} 筆記憶體緩衝`;

  return (
    <section
      aria-label="試撮明細"
      className="flex h-full flex-col overflow-hidden border border-omi-border-subtle bg-omi-surface-muted"
      data-testid="quote-auction-details"
    >
      <div className="flex items-center justify-between gap-3 border-b border-omi-border-subtle px-3 py-2">
        <div>
          <div className="text-[10px] font-bold uppercase tracking-[0.14em] text-omi-text-muted">
            試撮明細
          </div>
          <div className="mt-0.5 text-[11px] text-omi-text-muted">
            {sourceDescription}
          </div>
        </div>
        <span
          className={`inline-flex shrink-0 items-center border px-1.5 py-0.5 text-[10px] font-bold ${statusClassName}`}
          data-testid="quote-auction-status"
        >
          {statusLabel}
        </span>
      </div>
      <div className="min-h-0 flex-1 overflow-x-auto">
        <div className="flex h-full min-w-[31rem] flex-col">
          <div className="grid grid-cols-[5.25rem_repeat(4,minmax(4.25rem,1fr))] gap-2 border-b border-omi-border-subtle px-3 py-1.5 text-[10px] font-bold tracking-[0.06em] text-omi-text-muted">
            <span>時間</span>
            <span className="text-right">買進</span>
            <span className="text-right">賣出</span>
            <span className="text-right">試撮價</span>
            <span className="text-right">試撮量</span>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">
            {rows.length > 0 ? (
              rows.map((row) => (
                <div
                  key={row.eventId}
                  className="grid min-h-8 grid-cols-[5.25rem_repeat(4,minmax(4.25rem,1fr))] items-center gap-2 border-b border-omi-border-subtle/70 px-3 text-xs tabular-nums last:border-b-0"
                  data-testid="quote-auction-detail-row"
                >
                  <span className="font-mono text-[11px] text-omi-text-muted">
                    {formatEventClock(row.eventTime)}
                  </span>
                  <span className={`text-right font-semibold ${depthPriceTone(row.bestBidPrice, quoteDepth?.previous_close).textClass}`}>
                    {formatPrice(row.bestBidPrice)}
                  </span>
                  <span className={`text-right font-semibold ${depthPriceTone(row.bestAskPrice, quoteDepth?.previous_close).textClass}`}>
                    {formatPrice(row.bestAskPrice)}
                  </span>
                  <span className={`text-right font-bold ${depthPriceTone(row.indicativePrice, quoteDepth?.previous_close).textClass}`}>
                    {formatPrice(row.indicativePrice)}
                  </span>
                  <span className="text-right font-semibold text-omi-text-strong">
                    {formatVolumeValue(row.indicativeVolume, "張")}
                  </span>
                </div>
              ))
            ) : (
              <div className="flex h-full min-h-[140px] items-center justify-center px-4 text-center">
                <div>
                  <div className="text-xs font-semibold text-omi-text-strong">
                    尚無試撮明細
                  </div>
                  <div className="mt-1 text-[10px] leading-4 text-omi-text-muted">
                    {isReplay
                      ? "目前標的沒有可用的保存快照。"
                      : "試撮時段收到 KGI callback 後會列出試撮價量。"}
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
      <div className="border-t border-omi-border-subtle px-3 py-1.5 text-[10px] leading-4 text-omi-text-muted">
        試撮價量是模擬撮合結果，尚非正式成交；結束後顯示保存快照。
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
    <div className="relative grid min-h-7 flex-1 grid-cols-2 items-center gap-3 overflow-hidden border-t border-omi-border-subtle px-2 text-xs tabular-nums">
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
    <div className="flex h-full min-w-0 flex-col overflow-hidden border border-omi-border-subtle bg-omi-surface-muted">
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
      <div className="flex min-h-0 flex-1 flex-col">
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
            className="flex h-full min-h-[140px] items-center justify-center border-t border-omi-border-subtle px-3 text-center"
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
  quoteStream = null,
  quoteStreamLoadState = "idle",
}: QuoteDepthPanelProps) {
  const [viewSelection, setViewSelection] =
    useState<QuoteDepthViewSelection | null>(null);
  const replayAuctionSnapshots = useMemo(
    () => (quoteReplay?.snapshots ?? []).filter(isAuctionReplaySnapshot),
    [quoteReplay]
  );
  const replaySnapshot = replayAuctionSnapshots.at(-1) ?? null;
  const replayQuote = replaySnapshot?.quote ?? null;
  const replayAvailable = replayQuote !== null;
  const viewKey = quoteDepth?.stock_id ?? quoteStream?.stock_id ?? quoteReplay?.stock_id ?? "empty";
  const viewMode =
    viewSelection?.key === viewKey ? viewSelection.mode : "live";

  const activePreviewMode = quoteDepthPreviewMode;
  const isCurrentAuction = Boolean(
    quoteDepth &&
      (quoteDepth.session_phase === "preopen_auction" ||
        quoteDepth.session_phase === "closing_auction")
  );
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
  const isPreview = activePreviewMode !== null;
  const isAuctionView = activePreviewMode === "preopen" ||
    (activePreviewMode === null && viewMode === "replay");
  const useReplaySnapshot = Boolean(
    activePreviewMode === null &&
      viewMode === "replay" &&
      !isCurrentAuction &&
      replayDisplayQuote
  );
  const isReplay = useReplaySnapshot;
  const displayQuoteDepth = isPreview
    ? applyQuoteDepthPreview(quoteDepth, activePreviewMode)
    : useReplaySnapshot
      ? replayDisplayQuote
      : quoteDepth;
  const streamDepth =
    !isPreview &&
    !isReplay &&
    quoteStream !== null &&
    (quoteDepth === null || quoteStream.stock_id === quoteDepth.stock_id) &&
    quoteStream.status === "live" &&
    !quoteStream.is_stale &&
    quoteStream.capability_status.depth === "available" &&
    quoteStream.depth !== null &&
    !quoteStream.depth.is_stale
      ? quoteStream.depth
      : null;
  const status = streamDepth?.freshness_status ?? displayQuoteDepth?.freshness.status;
  const phaseLabel = displayQuoteDepth?.phase_label ?? "五檔";
  const bidLevels: TaiwanStockQuoteDepthLevel[] = streamDepth
    ? streamDepth.bid_levels.map(({ level, price, size_lots }) => ({
        level,
        price,
        size_lots,
      }))
    : displayQuoteDepth?.bid_levels ?? [];
  const askLevels: TaiwanStockQuoteDepthLevel[] = streamDepth
    ? streamDepth.ask_levels.map(({ level, price, size_lots }) => ({
        level,
        price,
        size_lots,
      }))
    : displayQuoteDepth?.ask_levels ?? [];
  const showDepth = bidLevels.length > 0 || askLevels.length > 0;
  const maxSize = depthMaxSize(bidLevels, askLevels);
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
  const message = streamDepth
    ? `KGI 即時串流五檔 · ${formatEventClock(streamDepth.event_time)}`
    : displayQuoteDepth?.freshness.message ??
    (loadState === "loading"
      ? "五檔資料載入中。"
      : loadState === "error"
        ? "五檔資料讀取失敗。"
        : "尚無五檔資料。");
  const isError = loadState === "error" && !displayQuoteDepth;
  const footerStatus = displayQuoteDepth?.freshness.is_stale || showDepth ? message : phaseLabel;
  const observationTimeLabel = streamDepth?.event_time
    ? formatDateTime(streamDepth.event_time)
    : displayQuoteDepth?.quote_time
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
              {streamDepth ? "KGI SUPER PY · STREAM" : sourceLabel(displayQuoteDepth)}
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
          <div className="grid w-full max-w-[18rem] grid-cols-2 border border-omi-border bg-omi-surface-subtle p-0.5">
            <button
              type="button"
              data-testid="quote-depth-mode-live"
              aria-pressed={viewMode === "live"}
              onClick={() => setViewSelection({ key: viewKey, mode: "live" })}
              className={[
                "h-7 px-2.5 text-xs font-semibold transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-omi-info",
                viewMode === "live"
                  ? "bg-omi-control text-omi-text-inverse"
                  : "text-omi-text-muted hover:bg-omi-surface",
              ].join(" ")}
            >
              即時成交
            </button>
            <button
              type="button"
              data-testid="quote-depth-mode-replay"
              aria-pressed={viewMode === "replay"}
              onClick={() => setViewSelection({ key: viewKey, mode: "replay" })}
              className={[
                "h-7 px-2.5 text-xs font-semibold transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-omi-info",
                viewMode === "replay"
                  ? "bg-omi-control text-omi-text-inverse"
                  : "text-omi-text-muted hover:bg-omi-surface",
              ].join(" ")}
            >
              試撮
            </button>
          </div>
          <span className="text-[11px] text-omi-text-muted" data-testid="quote-depth-replay-coverage">
            {replayLoadState === "loading"
              ? "快照索引讀取中"
              : replayAvailable
                ? `${quoteReplay?.trade_date ?? "-"} · ${replayAuctionSnapshots.length} 筆試撮快照`
                : "目前標的無試撮快照"}
          </span>
        </div>
      ) : null}

      <div
        className="mt-3 grid gap-3 lg:grid-cols-[minmax(18rem,0.88fr)_minmax(22rem,1.12fr)] lg:items-stretch"
        data-testid="quote-depth-content"
      >
        <div className="h-[18rem] min-w-0" data-testid="quote-depth-book-column">
          {showDepth ? (
            <div className="grid h-full grid-cols-2 gap-2" data-testid="quote-depth-book">
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

        <div className="h-[18rem] min-w-0" data-testid="quote-depth-summary-column">
          {isAuctionView ? (
            <AuctionDetailsPanel
              quoteDepth={displayQuoteDepth}
              quoteStream={quoteStream}
              loadState={quoteStreamLoadState}
              isReplay={isReplay}
              isPreview={isPreview}
              replayLabel={
                isReplay
                  ? `${quoteReplay?.trade_date ?? "-"} · ${replayAuctionSnapshots.length} 筆`
                  : null
              }
              replaySnapshots={replayAuctionSnapshots}
            />
          ) : (
            <RecentTradesPanel
              quoteStream={quoteStream}
              loadState={quoteStreamLoadState}
            />
          )}
        </div>
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
