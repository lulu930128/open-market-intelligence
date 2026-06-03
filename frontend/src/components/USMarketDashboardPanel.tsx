"use client";

import USStockDetailPanel from "@/components/USStockDetailPanel";
import USWatchlistRankingPanel from "@/components/USWatchlistRankingPanel";

type Props = {
  selectedSymbol: string | null;
  selectedSecurityName: string | null;
  selectedGroupId: number | null;
  selectedGroupName: string | null;
  watchlistReloadKey: number;
  onSelectSymbol: (symbol: string, securityName: string | null) => void;
};

export default function USMarketDashboardPanel({
  selectedSymbol,
  selectedSecurityName,
  selectedGroupId,
  selectedGroupName,
  watchlistReloadKey,
  onSelectSymbol,
}: Props) {
  const watchlistRankingPanel = (
    <USWatchlistRankingPanel
      selectedGroupId={selectedGroupId}
      selectedGroupName={selectedGroupName}
      selectedSymbol={selectedSymbol}
      reloadKey={watchlistReloadKey}
      onSelectSymbol={onSelectSymbol}
    />
  );

  return (
    <USStockDetailPanel
      selectedSymbol={selectedSymbol}
      selectedSecurityName={selectedSecurityName}
      watchlistRankingPanel={watchlistRankingPanel}
    />
  );
}
