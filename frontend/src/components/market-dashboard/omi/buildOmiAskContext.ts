import type { OmiAskDockContext } from "@/components/OmiAskDock";
import type { MarketRegion } from "@/components/market-dashboard/selection/dashboardRoutes";
import type { TranslationFunction } from "@/i18n";
import { getJpMarketIndexConfig } from "@/lib/jpMarketIndices";
import { getKrMarketIndexConfig } from "@/lib/krMarketIndices";
import type { JPStockMasterRead, KRStockMasterRead } from "@/types/market";

type BuildOmiAskContextInput = {
  activeMarket: MarketRegion;
  activeGroupId: number | null;
  selectedGroupName: string | null;
  selectedStockId: string | null;
  selectedStockName: string | null;
  selectedFuturesSymbol: string | null;
  selectedUsGroupId: number | null;
  selectedUsGroupName: string | null;
  selectedUsSymbol: string | null;
  selectedUsSecurityName: string | null;
  selectedJpGroupId: number | null;
  selectedJpGroupName: string | null;
  selectedJpSymbol: string | null;
  selectedJpStock: JPStockMasterRead | null;
  selectedKrGroupId: number | null;
  selectedKrGroupName: string | null;
  selectedKrSymbol: string | null;
  selectedKrStock: KRStockMasterRead | null;
  t: TranslationFunction;
};

const TAIWAN_INDEX_TARGET_IDS = new Set(["TAIEX", "TPEX"]);

export function buildOmiAskContext({
  activeMarket,
  activeGroupId,
  selectedGroupName,
  selectedStockId,
  selectedStockName,
  selectedFuturesSymbol,
  selectedUsGroupId,
  selectedUsGroupName,
  selectedUsSymbol,
  selectedUsSecurityName,
  selectedJpGroupId,
  selectedJpGroupName,
  selectedJpSymbol,
  selectedJpStock,
  selectedKrGroupId,
  selectedKrGroupName,
  selectedKrSymbol,
  selectedKrStock,
  t,
}: BuildOmiAskContextInput): OmiAskDockContext {
  if (activeMarket === "us") {
    if (selectedUsSymbol) {
      return {
        market: "us",
        label: `${selectedUsSymbol}${selectedUsSecurityName ? ` ${selectedUsSecurityName}` : ""}`,
        target: {
          type: "us_stock",
          id: selectedUsSymbol,
          label: selectedUsSecurityName ?? selectedUsSymbol,
          market: "US",
        },
        uiContext: {
          market: "us",
          selected_symbol: selectedUsSymbol,
          selected_security_name: selectedUsSecurityName,
          selected_group_id: selectedUsGroupId,
          selected_group_name: selectedUsGroupName,
        },
      };
    }

    return {
      market: "us",
      label: selectedUsGroupName
        ? t("dashboard.ranking.usLabel", { groupName: selectedUsGroupName })
        : t("dashboard.ranking.usMarket"),
      target: {
        type: "auto",
        market: "US",
        label: selectedUsGroupName ?? t("dashboard.ranking.usMarket"),
      },
      uiContext: {
        market: "us",
        selected_group_id: selectedUsGroupId,
        selected_group_name: selectedUsGroupName,
      },
    };
  }

  if (activeMarket === "jp") {
    if (selectedJpSymbol) {
      const selectedJpIndexConfig = getJpMarketIndexConfig(selectedJpSymbol);

      return {
        market: "jp",
        label: `${selectedJpSymbol}${
          selectedJpStock?.security_name ? ` ${selectedJpStock.security_name}` : ""
        }`,
        target: {
          type: selectedJpIndexConfig ? "jp_index" : "jp_stock",
          id: selectedJpSymbol,
          label:
            selectedJpIndexConfig?.name ??
            selectedJpStock?.security_name ??
            selectedJpSymbol,
          market: "JP",
        },
        uiContext: {
          market: "jp",
          selected_symbol: selectedJpSymbol,
          selected_security_name: selectedJpStock?.security_name ?? null,
          selected_market_segment: selectedJpStock?.market_segment ?? null,
          selected_sector: selectedJpStock?.sector_33_name ?? null,
          selected_group_id: selectedJpGroupId,
          selected_group_name: selectedJpGroupName,
        },
      };
    }

    return {
      market: "jp",
      label: t("jpMarket.askMarketLabel"),
      target: {
        type: "market",
        market: "JP",
        label: t("jpMarket.askMarketLabel"),
      },
      uiContext: {
        market: "jp",
        selected_group_id: selectedJpGroupId,
        selected_group_name: selectedJpGroupName,
      },
    };
  }

  if (activeMarket === "kr") {
    if (selectedKrSymbol) {
      const selectedKrIndexConfig = getKrMarketIndexConfig(selectedKrSymbol);
      return {
        market: "kr",
        label: `${selectedKrSymbol}${
          selectedKrStock?.security_name ? ` ${selectedKrStock.security_name}` : ""
        }`,
        target: {
          type: selectedKrIndexConfig ? "kr_index" : "kr_stock",
          id: selectedKrSymbol,
          label:
            selectedKrIndexConfig?.name ??
            selectedKrStock?.security_name ??
            selectedKrSymbol,
          market: "KR",
        },
        uiContext: {
          market: "kr",
          selected_symbol: selectedKrSymbol,
          selected_security_name: selectedKrStock?.security_name ?? null,
          selected_market_segment: selectedKrStock?.market_segment ?? null,
          selected_sector: selectedKrStock?.sector ?? null,
          selected_group_id: selectedKrGroupId,
          selected_group_name: selectedKrGroupName,
        },
      };
    }

    return {
      market: "kr",
      label: t("krMarket.askMarketLabel"),
      target: {
        type: "market",
        market: "KR",
        label: t("krMarket.askMarketLabel"),
      },
      uiContext: {
        market: "kr",
        selected_group_id: selectedKrGroupId,
        selected_group_name: selectedKrGroupName,
      },
    };
  }

  if (selectedFuturesSymbol) {
    const futuresLabel = `${selectedFuturesSymbol} ${t("futures.productTitle")}`;

    return {
      market: "tw",
      label: futuresLabel,
      target: {
        type: "tw_futures",
        id: selectedFuturesSymbol,
        label: futuresLabel,
        market: "TW",
      },
      uiContext: {
        market: "tw",
        selected_futures_symbol: selectedFuturesSymbol,
        selected_group_id: activeGroupId,
        selected_group_name: selectedGroupName,
      },
    };
  }

  if (selectedStockId) {
    const isIndexTarget = TAIWAN_INDEX_TARGET_IDS.has(selectedStockId);
    return {
      market: "tw",
      label: `${selectedStockId}${selectedStockName ? ` ${selectedStockName}` : ""}`,
      target: {
        type: isIndexTarget ? "tw_index" : "tw_stock",
        id: selectedStockId,
        label: selectedStockName ?? selectedStockId,
        market: "TW",
      },
      uiContext: {
        market: "tw",
        [isIndexTarget ? "selected_index_id" : "selected_stock_id"]: selectedStockId,
        [isIndexTarget ? "selected_index_name" : "selected_stock_name"]:
          selectedStockName,
        selected_group_id: activeGroupId,
        selected_group_name: selectedGroupName,
      },
    };
  }

  if (activeGroupId !== null) {
    const groupLabel = selectedGroupName ?? String(activeGroupId);

    return {
      market: "tw",
      label: t("dashboard.ranking.twLabel", { groupName: groupLabel }),
      target: {
        type: "tw_watchlist",
        id: String(activeGroupId),
        label: groupLabel,
        market: "TW",
      },
      uiContext: {
        market: "tw",
        selected_group_id: activeGroupId,
        selected_group_name: selectedGroupName,
      },
    };
  }

  return {
    market: activeMarket,
    label:
      activeMarket === "tw"
        ? t("dashboard.ranking.twMarket")
        : t("dashboard.ranking.genericMarket", {
            market: activeMarket.toUpperCase(),
          }),
    target: {
      type: "auto",
      market: activeMarket.toUpperCase(),
    },
    uiContext: {
      market: activeMarket,
    },
  };
}
