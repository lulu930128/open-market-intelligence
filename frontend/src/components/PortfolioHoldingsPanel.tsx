"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import { deleteRequest, fetchJson, requestJson } from "@/lib/api";
import type { PortfolioHoldingRead, PortfolioMarket } from "@/types/market";

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
  const [message, setMessage] = useState<Message>(null);
  const [symbolInput, setSymbolInput] = useState("");
  const [quantityInput, setQuantityInput] = useState("");
  const [amountInput, setAmountInput] = useState("");
  const [noteInput, setNoteInput] = useState("");

  const selectedSymbolKey = useMemo(
    () => (selectedSymbol ? normalizeSymbol(selectedSymbol) : null),
    [normalizeSymbol, selectedSymbol]
  );

  const reloadHoldings = useCallback(async () => {
    setLoading(true);
    try {
      const rows = await fetchJson<PortfolioHoldingRead[]>("/api/portfolio/holdings", {
        market,
        is_active: true,
        limit: 500,
        offset: 0,
      });
      setHoldings(rows);
    } catch (error) {
      setMessage({
        type: "error",
        text: error instanceof Error ? error.message : "持股讀取失敗",
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
                      {holding.currency} {formatNumber(holding.average_cost)} / {formatNumber(holding.quantity, 4)}
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
              <button type="submit" className={buttonClass("primary")} disabled={loading}>
                + 持股
              </button>
              <button type="button" className={buttonClass("ghost")} disabled={loading} onClick={() => void reloadHoldings()}>
                {loading ? "更新中" : "更新"}
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
