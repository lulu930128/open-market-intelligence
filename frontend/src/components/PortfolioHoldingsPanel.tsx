"use client";

import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { deleteRequest, fetchJson, requestJson, requireJsonArray } from "@/lib/api";
import { emitDataStatusEvent } from "@/lib/dataStatusEvents";
import type { KgiPortfolioSyncRead, PortfolioHoldingRead, PortfolioMarket } from "@/types/market";

type Message = { type: "success" | "error"; text: string } | null;

type Props = {
  market: PortfolioMarket;
  selectedSymbol: string | null;
  defaultCurrency: string;
  symbolPlaceholder: string;
  normalizeSymbol?: (value: string) => string;
  onSelectSymbol: (symbol: string, symbolName: string | null) => void;
  onChanged?: () => void;
};

function inputClass() {
  return "h-8 min-w-0 border border-omi-border bg-omi-surface px-2 text-xs text-omi-text outline-none transition placeholder:text-omi-text-subtle focus:border-omi-accent";
}

function buttonClass(kind: "primary" | "ghost" | "danger" = "ghost") {
  if (kind === "primary") {
    return "h-8 border border-omi-accent-border bg-omi-accent-soft px-2 text-xs font-semibold text-omi-accent transition hover:border-omi-accent hover:bg-omi-surface-subtle hover:text-omi-accent-hover disabled:cursor-not-allowed disabled:border-omi-border-subtle disabled:bg-omi-surface-strong disabled:text-omi-text-subtle";
  }
  if (kind === "danger") {
    return "h-7 border border-omi-danger-border bg-omi-danger-soft px-2 text-[10px] font-semibold text-omi-danger transition hover:bg-omi-surface disabled:cursor-not-allowed disabled:border-omi-border-subtle disabled:text-omi-text-subtle";
  }
  return "h-8 bg-omi-surface-muted px-2 text-xs font-semibold text-omi-text-muted hover:bg-omi-surface-strong disabled:cursor-not-allowed disabled:text-omi-text-subtle";
}

function parsePositiveNumber(value: string) {
  const number = Number(value.replaceAll(",", "").trim());
  return Number.isFinite(number) && number > 0 ? number : null;
}

function formatNumber(value: number | null | undefined, fractionDigits = 2) {
  if (value === null || value === undefined || !Number.isFinite(value)) return "-";
  return new Intl.NumberFormat(undefined, {
    maximumFractionDigits: fractionDigits,
  }).format(value);
}

function defaultNormalize(value: string) {
  return value.trim().toUpperCase();
}

function portfolioMarketLabel(market: PortfolioMarket) {
  return {
    tw: "台股持股",
    us: "美股持股",
    jp: "日股持股",
    kr: "韓股持股",
  }[market];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

function isNullableNumber(value: unknown): value is number | null {
  return value === null || (typeof value === "number" && Number.isFinite(value));
}

function isPortfolioHolding(value: unknown): value is PortfolioHoldingRead {
  if (!isRecord(value)) return false;

  return (
    typeof value.id === "number" &&
    ["tw", "us", "jp", "kr"].includes(String(value.market)) &&
    typeof value.symbol === "string" &&
    value.symbol.length > 0 &&
    isNullableString(value.symbol_name) &&
    typeof value.quantity === "number" &&
    Number.isFinite(value.quantity) &&
    isNullableNumber(value.cost_amount) &&
    typeof value.currency === "string" &&
    isNullableNumber(value.average_cost) &&
    typeof value.source === "string" &&
    isNullableString(value.source_updated_at) &&
    isNullableString(value.note) &&
    isNullableString(value.tags) &&
    isNullableString(value.strategy_horizon) &&
    isNullableString(value.opened_at) &&
    typeof value.is_active === "boolean" &&
    isRecord(value.position_context) &&
    typeof value.created_at === "string" &&
    typeof value.updated_at === "string"
  );
}

export default function PortfolioHoldingsPanel({
  market,
  selectedSymbol,
  defaultCurrency,
  symbolPlaceholder,
  normalizeSymbol = defaultNormalize,
  onSelectSymbol,
  onChanged,
}: Props) {
  const [expanded, setExpanded] = useState(true);
  const [holdings, setHoldings] = useState<PortfolioHoldingRead[]>([]);
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [message, setMessage] = useState<Message>(null);
  const [symbolInput, setSymbolInput] = useState("");
  const [quantityInput, setQuantityInput] = useState("");
  const [amountInput, setAmountInput] = useState("");
  const [noteInput, setNoteInput] = useState("");
  const loadHadErrorRef = useRef(false);

  const selectedSymbolKey = useMemo(
    () => (selectedSymbol ? normalizeSymbol(selectedSymbol) : null),
    [normalizeSymbol, selectedSymbol]
  );

  const reloadHoldings = useCallback(async () => {
    setLoading(true);
    try {
      const payload = await fetchJson<unknown>("/api/portfolio/holdings", {
        market,
        is_active: true,
        limit: 500,
        offset: 0,
      });
      const rows = requireJsonArray(payload, "持股", isPortfolioHolding);
      setHoldings(rows);
      if (loadHadErrorRef.current) {
        emitDataStatusEvent({
          market,
          level: "success",
          title: "持股資料已恢復",
          message: "持股清單已重新讀取。",
          source: "portfolio_holdings",
          contextKey: `portfolio:${market}`,
          contextLabel: portfolioMarketLabel(market),
          dedupeKey: `portfolio-load:${market}`,
        });
        loadHadErrorRef.current = false;
      }
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : "持股讀取失敗";
      loadHadErrorRef.current = true;
      emitDataStatusEvent({
        market,
        level: "error",
        title: "持股資料讀取失敗",
        message: errorMessage,
        source: "portfolio_holdings",
        contextKey: `portfolio:${market}`,
        contextLabel: portfolioMarketLabel(market),
        dedupeKey: `portfolio-load:${market}`,
      });
      setMessage({
        type: "error",
        text: "持股讀取失敗，詳情請看更新狀態。",
      });
    } finally {
      setLoading(false);
    }
  }, [market]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void reloadHoldings();
  }, [reloadHoldings]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage(null);

    const symbol = normalizeSymbol(symbolInput);
    const quantity = parsePositiveNumber(quantityInput);
    const costAmount = parsePositiveNumber(amountInput);
    if (!symbol || quantity === null || costAmount === null) {
      setMessage({ type: "error", text: "請輸入股票、持股數量與持股金額。" });
      return;
    }

    setLoading(true);
    try {
      const created = await requestJson<PortfolioHoldingRead>("/api/portfolio/holdings", {
        method: "POST",
        body: JSON.stringify({
          market,
          symbol,
          quantity,
          cost_amount: costAmount,
          currency: defaultCurrency,
          note: noteInput.trim() || null,
        }),
      });
      setSymbolInput("");
      setQuantityInput("");
      setAmountInput("");
      setNoteInput("");
      setMessage({ type: "success", text: "已加入持股。" });
      await reloadHoldings();
      onSelectSymbol(created.symbol, created.symbol_name);
      onChanged?.();
    } catch (error) {
      setMessage({
        type: "error",
        text: error instanceof Error ? error.message : "加入持股失敗",
      });
    } finally {
      setLoading(false);
    }
  }

  async function deleteHolding(holding: PortfolioHoldingRead) {
    if (!window.confirm(`刪除持股 ${holding.symbol}?`)) return;

    setLoading(true);
    setMessage(null);
    try {
      await deleteRequest(`/api/portfolio/holdings/${holding.id}`);
      setMessage({ type: "success", text: "已刪除持股。" });
      await reloadHoldings();
      onChanged?.();
    } catch (error) {
      setMessage({
        type: "error",
        text: error instanceof Error ? error.message : "刪除持股失敗",
      });
    } finally {
      setLoading(false);
    }
  }

  async function syncKgiHoldings() {
    const marketLabel = market === "tw" ? "台股" : "美股";
    if (!window.confirm(`將以凱基 API 的${marketLabel}持股覆蓋目前清單，是否繼續？`)) return;

    setSyncing(true);
    setMessage(null);
    try {
      const result = await requestJson<KgiPortfolioSyncRead>("/api/portfolio/holdings/kgi-sync", {
        method: "POST",
        body: JSON.stringify({ market }),
      });
      const missingCost = result.missing_cost_basis_count
        ? `；${result.missing_cost_basis_count} 檔未提供成本`
        : "";
      setMessage({
        type: "success",
        text: `已同步凱基 ${result.holding_count} 檔（新增 ${result.created_count}、更新 ${result.updated_count}、移除 ${result.removed_count}）${missingCost}。`,
      });
      emitDataStatusEvent({
        market,
        level: result.warnings.length ? "warning" : "success",
        title: result.warnings.length ? "凱基持股同步完成但有資料限制" : "凱基持股同步完成",
        message: result.warnings.length
          ? result.warnings.join(" ")
          : `已同步 ${result.holding_count} 檔持股。`,
        source: "kgi_superpy_portfolio",
        contextKey: `portfolio:${market}`,
        contextLabel: marketLabel,
        dedupeKey: `portfolio-kgi-sync:${market}`,
      });
      await reloadHoldings();
      onChanged?.();
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : "凱基持股同步失敗";
      emitDataStatusEvent({
        market,
        level: "error",
        title: "凱基持股同步失敗",
        message: errorMessage,
        source: "kgi_superpy_portfolio",
        contextKey: `portfolio:${market}`,
        contextLabel: marketLabel,
        dedupeKey: `portfolio-kgi-sync:${market}`,
      });
      setMessage({
        type: "error",
        text: "同步失敗，詳情請看更新狀態。",
      });
    } finally {
      setSyncing(false);
    }
  }

  return (
    <div className="border-b border-omi-border-subtle pb-2">
      <button
        type="button"
        className="flex w-full items-center gap-1 py-1 pr-3 text-left text-sm text-omi-text-muted hover:bg-omi-surface-muted"
        onClick={() => setExpanded((value) => !value)}
      >
        <span className="h-6 w-4 text-center text-xs text-omi-text-muted">
          {expanded ? "v" : ">"}
        </span>
        <span className="min-w-0 flex-1 truncate font-semibold">持股中</span>
        <span className="text-xs text-omi-text-subtle">{holdings.length}</span>
      </button>

      {expanded ? (
        <div className="space-y-2">
          <div>
            {holdings.map((holding) => {
              const selected = holding.symbol === selectedSymbolKey;
              return (
                <div
                  key={holding.id}
                  className={[
                    "group flex items-center gap-1 py-1.5 pr-2 text-xs",
                    selected
                      ? "omi-sidebar-selected text-omi-text-strong"
                      : "text-omi-text-muted hover:bg-omi-surface-muted",
                  ].join(" ")}
                  style={{ paddingLeft: "24px" }}
                >
                  <button
                    type="button"
                    className="min-w-0 flex-1 text-left"
                    onClick={() => onSelectSymbol(holding.symbol, holding.symbol_name)}
                  >
                    <div className="truncate font-semibold">
                      {holding.symbol} {holding.symbol_name ?? ""}
                    </div>
                    <div className={selected ? "truncate text-omi-text-muted" : "truncate text-omi-text-subtle"}>
                      {holding.currency} 成本 {formatNumber(holding.average_cost)} / {formatNumber(holding.quantity, 4)}
                      {holding.source === "kgi_superpy" ? (
                        <span
                          title={holding.source_updated_at ? `凱基同步：${new Date(holding.source_updated_at).toLocaleString()}` : "凱基同步"}
                        >
                          {" · 凱基"}
                        </span>
                      ) : null}
                    </div>
                  </button>
                  <button
                    type="button"
                    className="hidden bg-omi-danger-soft px-1.5 py-0.5 text-[10px] font-semibold text-omi-danger group-hover:block"
                    disabled={loading}
                    onClick={() => void deleteHolding(holding)}
                  >
                    x
                  </button>
                </div>
              );
            })}
            {holdings.length === 0 ? (
              <div className="px-6 py-2 text-xs text-omi-text-subtle">尚未加入持股</div>
            ) : null}
          </div>

          <form className="mx-3 space-y-2 border border-omi-border-subtle bg-omi-surface-subtle p-2" onSubmit={handleSubmit}>
            <div className="grid grid-cols-2 gap-2">
              <input
                className={`${inputClass()} col-span-2`}
                placeholder={symbolPlaceholder}
                value={symbolInput}
                onChange={(event) => setSymbolInput(event.target.value)}
              />
              <input
                className={inputClass()}
                inputMode="decimal"
                placeholder="數量"
                value={quantityInput}
                onChange={(event) => setQuantityInput(event.target.value)}
              />
              <input
                className={inputClass()}
                inputMode="decimal"
                placeholder={`金額 ${defaultCurrency}`}
                value={amountInput}
                onChange={(event) => setAmountInput(event.target.value)}
              />
            </div>
            <input
              className={inputClass()}
              placeholder="備註"
              value={noteInput}
              onChange={(event) => setNoteInput(event.target.value)}
            />
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-1">
                <button type="submit" className={buttonClass("primary")} disabled={loading || syncing}>
                  + 持股
                </button>
                {market === "tw" || market === "us" ? (
                  <button type="button" className={buttonClass("ghost")} disabled={loading || syncing} onClick={() => void syncKgiHoldings()}>
                    {syncing ? "同步中" : "同步凱基"}
                  </button>
                ) : null}
              </div>
              <button type="button" className={buttonClass("ghost")} disabled={loading || syncing} onClick={() => void reloadHoldings()}>
                {loading ? "更新中" : "重載"}
              </button>
            </div>
            {message ? (
              <div
                className={[
                  "border px-2 py-1.5 text-xs",
                  message.type === "success"
                    ? "border-omi-market-down-border bg-omi-market-down-soft text-omi-market-down"
                    : "border-omi-danger-border bg-omi-danger-soft text-omi-danger",
                ].join(" ")}
              >
                {message.text}
              </div>
            ) : null}
          </form>
        </div>
      ) : null}
    </div>
  );
}
