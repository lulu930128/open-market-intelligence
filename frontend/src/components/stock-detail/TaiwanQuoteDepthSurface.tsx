"use client";

import QuoteDepthPanel from "@/components/stock-detail/QuoteDepthPanel";
import { useTaiwanQuoteDepth } from "@/components/stock-detail/useTaiwanQuoteDepth";
import type {
  TaiwanQuoteContractReplayRead,
  TaiwanStockQuoteDepthPreviewMode,
  TaiwanStockQuoteDepthRead,
} from "@/types/market";

type QuoteDepthLoadState = "idle" | "loading" | "success" | "error";

type TaiwanQuoteDepthSurfaceProps = {
  stockId: string | null;
  quoteDepth: TaiwanStockQuoteDepthRead | null;
  quoteReplay: TaiwanQuoteContractReplayRead | null;
  loadState: QuoteDepthLoadState;
  replayLoadState: QuoteDepthLoadState;
  quoteDepthPreviewMode?: TaiwanStockQuoteDepthPreviewMode | null;
};

export default function TaiwanQuoteDepthSurface({
  stockId,
  quoteDepth,
  quoteReplay,
  loadState,
  replayLoadState,
  quoteDepthPreviewMode,
}: TaiwanQuoteDepthSurfaceProps) {
  const {
    quoteStream,
    quoteStreamLoadState,
  } = useTaiwanQuoteDepth({
    enabled: true,
    stockId,
    leaseEnabled: false,
    depthEnabled: false,
  });

  return (
    <QuoteDepthPanel
      quoteDepth={quoteDepth}
      quoteReplay={quoteReplay}
      quoteStream={quoteStream}
      loadState={loadState}
      replayLoadState={replayLoadState}
      quoteStreamLoadState={quoteStreamLoadState}
      quoteDepthPreviewMode={quoteDepthPreviewMode}
    />
  );
}
