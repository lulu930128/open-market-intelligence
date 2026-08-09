"use client";

import { StateSurface } from "@/components/LoadingPlaceholders";
import { useT, type TranslationFunction } from "@/i18n";
import type {
  WatchlistRadarV2OutcomeItemRead,
  WatchlistRadarV2OutcomeSummaryRead,
} from "@/types/market";

type LoadState = "idle" | "loading" | "success" | "error";

type WatchlistRadarV2OutcomePanelProps = {
  history?: WatchlistRadarV2OutcomeSummaryRead[];
  historyOpen?: boolean;
  historyLoadState?: LoadState;
  detailLoadState?: LoadState;
  reconcileLoadState?: LoadState;
  selectedSnapshotDate?: string | null;
  disabled?: boolean;
  onCloseHistory?: () => void;
  onReconcileHistory?: () => void;
  onSelectSnapshot?: (snapshotDate: string) => void;
};

function formatDate(value: string | null | undefined) {
  if (!value) return "-";
  const parsed = new Date(`${value.slice(0, 10)}T00:00:00`);
  return Number.isNaN(parsed.getTime())
    ? value
    : new Intl.DateTimeFormat(undefined, {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
      }).format(parsed);
}

function formatDateTime(value: string | null | undefined) {
  if (!value) return "-";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? value
    : new Intl.DateTimeFormat(undefined, {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      }).format(parsed);
}

function formatPct(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) return "-";
  const prefix = value > 0 ? "+" : "";
  return `${prefix}${value.toFixed(2)}%`;
}

function metricClass(value: number | null | undefined) {
  if (value === null || value === undefined || value === 0) return "text-omi-text-muted";
  return value > 0 ? "text-omi-success" : "text-omi-danger";
}

function formatMagnitudePct(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) return "-";
  return `${Math.abs(value).toFixed(2)}%`;
}

function translatedCode(
  t: TranslationFunction,
  namespace: "states" | "quality" | "status" | "pendingReasons",
  value: string
) {
  const key = `radar.v2.outcomes.${namespace}.${value}`;
  const translated = t(key);
  return translated === key ? value : translated;
}

function limitationCode(value: Record<string, unknown>) {
  const code = typeof value.code === "string" ? value.code : null;
  return code || "unrecognized_outcome_limitation";
}

function limitationText(t: TranslationFunction, value: Record<string, unknown>) {
  const code = limitationCode(value);
  const family = code.split(":", 1)[0];
  const key = `radar.v2.outcomes.limitations.${family}`;
  const translated = t(key);
  return translated === key
    ? t("radar.v2.outcomes.limitations.other")
    : translated;
}

function summaryLimitationText(t: TranslationFunction, code: string) {
  const key = `radar.v2.outcomes.limitations.${code}`;
  const translated = t(key);
  return translated === key
    ? t("radar.v2.outcomes.limitations.other")
    : translated;
}

function StateCounts({
  counts,
  t,
}: {
  counts: Record<string, number>;
  t: TranslationFunction;
}) {
  const entries = Object.entries(counts);
  if (entries.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-2 text-xs" data-testid="watchlist-radar-v2-outcome-states">
      {entries.map(([state, count]) => (
        <span
          key={state}
          className="border border-omi-border-subtle bg-omi-surface-subtle px-2 py-1 text-omi-text-muted"
        >
          {translatedCode(t, "states", state)} {count}
        </span>
      ))}
    </div>
  );
}

function PendingReasonCounts({
  counts,
  t,
}: {
  counts: Record<string, number>;
  t: TranslationFunction;
}) {
  const entries = Object.entries(counts).filter(([, count]) => count > 0);
  if (entries.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-2 text-xs" data-testid="watchlist-radar-v2-pending-reasons">
      {entries.map(([reason, count]) => (
        <span
          key={reason}
          className="border border-omi-warning-border bg-omi-warning-soft px-2 py-1 text-omi-warning"
        >
          {translatedCode(t, "pendingReasons", reason)} {count}
        </span>
      ))}
    </div>
  );
}

function Limitations({
  limitations,
  t,
}: {
  limitations: Array<Record<string, unknown>>;
  t: TranslationFunction;
}) {
  if (limitations.length === 0) return null;

  return (
    <details className="mt-2 border-t border-omi-border-subtle pt-2 text-xs text-omi-text-muted">
      <summary className="cursor-pointer select-none font-semibold hover:text-omi-text">
        {t("radar.v2.outcomes.limitationCount", { count: limitations.length })}
      </summary>
      <ul className="mt-2 list-disc space-y-1 pl-5">
        {limitations.map((limitation, index) => (
          <li key={`${limitationCode(limitation)}-${index}`}>
            {limitationText(t, limitation)}
          </li>
        ))}
      </ul>
      <details className="mt-2">
        <summary className="cursor-pointer select-none text-omi-text-subtle">
          {t("radar.v2.outcomes.advancedDiagnostics")}
        </summary>
        <pre className="mt-2 overflow-x-auto whitespace-pre-wrap break-all bg-omi-surface-subtle p-2 text-[11px] text-omi-text-subtle">
          {JSON.stringify(limitations, null, 2)}
        </pre>
      </details>
    </details>
  );
}

function OutcomeItem({
  item,
  t,
}: {
  item: WatchlistRadarV2OutcomeItemRead;
  t: TranslationFunction;
}) {
  return (
    <article
      className="border border-omi-border-subtle bg-omi-surface px-3 py-3"
      data-testid={`watchlist-radar-v2-history-item-${item.source_rank ?? "na"}-${item.stock_id}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="font-semibold text-omi-text">
            {item.source_rank ? `#${item.source_rank} ` : ""}
            {item.stock_name || item.stock_id}
            <span className="ml-1 text-xs font-normal text-omi-text-muted">{item.stock_id}</span>
          </div>
          <div className="mt-1 flex flex-wrap gap-2 text-xs text-omi-text-muted">
            <span>{translatedCode(t, "status", item.status)}</span>
            <span>{translatedCode(t, "states", item.summary_state)}</span>
            <span>{translatedCode(t, "quality", item.outcome_quality)}</span>
            {item.pending_reason ? (
              <span className="text-omi-warning">
                {translatedCode(t, "pendingReasons", item.pending_reason)}
              </span>
            ) : null}
          </div>
        </div>
        <div className="text-right text-xs text-omi-text-muted">
          {t("radar.v2.outcomes.horizon")}: {formatDate(item.horizon_end_trade_date)}
        </div>
      </div>

      <div className="mt-3 grid grid-cols-1 gap-2 text-xs sm:grid-cols-3">
        <div className="border border-omi-border-subtle bg-omi-surface-subtle px-2 py-2">
          <div className="text-omi-text-muted">{t("radar.v2.outcomes.return")}</div>
          <div className={`mt-1 font-bold ${metricClass(item.signal_close_return_pct)}`}>
            {formatPct(item.signal_close_return_pct)}
          </div>
        </div>
        <div className="border border-omi-border-subtle bg-omi-surface-subtle px-2 py-2">
          <div className="text-omi-text-muted">{t("radar.v2.outcomes.mfe")}</div>
          <div
            className={`mt-1 font-bold ${
              item.signal_mfe_pct === null || item.signal_mfe_pct === undefined
                ? "text-omi-text-muted"
                : "text-omi-success"
            }`}
          >
            {formatMagnitudePct(item.signal_mfe_pct)}
          </div>
        </div>
        <div className="border border-omi-border-subtle bg-omi-surface-subtle px-2 py-2">
          <div className="text-omi-text-muted">{t("radar.v2.outcomes.mae")}</div>
          <div
            className={`mt-1 font-bold ${
              item.signal_mae_pct === null || item.signal_mae_pct === undefined
                ? "text-omi-text-muted"
                : "text-omi-danger"
            }`}
          >
            {formatMagnitudePct(item.signal_mae_pct)}
          </div>
        </div>
      </div>

      <Limitations limitations={item.limitations} t={t} />
    </article>
  );
}

export function WatchlistRadarV2OutcomePanel({
  history = [],
  historyOpen = false,
  historyLoadState = "idle",
  detailLoadState = "idle",
  reconcileLoadState = "idle",
  selectedSnapshotDate = null,
  disabled = false,
  onCloseHistory,
  onReconcileHistory,
  onSelectSnapshot,
}: WatchlistRadarV2OutcomePanelProps) {
  const t = useT();
  const selectedSummary =
    history.find((row) => row.snapshot_date === selectedSnapshotDate) ?? history[0] ?? null;
  const historyLoading = historyLoadState === "loading";
  const detailLoading = detailLoadState === "loading";
  const reconcileLoading = reconcileLoadState === "loading";

  if (!historyOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-3"
      role="dialog"
      aria-modal="true"
      aria-label={t("radar.v2.outcomes.historyTitle")}
      data-testid="watchlist-radar-history-dialog"
    >
          <div className="flex max-h-[88vh] w-full max-w-6xl flex-col overflow-hidden border border-omi-border bg-omi-surface shadow-2xl">
            <header className="flex flex-wrap items-start justify-between gap-3 border-b border-omi-border-subtle px-5 py-4">
              <div>
                <div className="text-xs font-semibold uppercase tracking-[0.16em] text-omi-text-muted">
                  {t("radar.v2.outcomes.title")}
                </div>
                <h3 className="mt-1 text-lg font-bold text-omi-text-strong">
                  {t("radar.v2.outcomes.historyTitle")}
                </h3>
              </div>
              <div className="flex gap-2">
                {onReconcileHistory ? (
                  <button
                    type="button"
                    data-testid="watchlist-radar-history-reconcile"
                    onClick={onReconcileHistory}
                    disabled={disabled || historyLoading || reconcileLoading}
                    className="h-8 border border-omi-border bg-omi-surface px-3 text-xs font-semibold text-omi-text-muted hover:border-omi-accent hover:text-omi-accent disabled:text-omi-text-subtle"
                  >
                    {t(
                      reconcileLoading
                        ? "radar.v2.outcomes.checking"
                        : "radar.v2.outcomes.reconcile"
                    )}
                  </button>
                ) : null}
                <button
                  type="button"
                  onClick={onCloseHistory}
                  className="h-8 border border-omi-border bg-omi-surface px-3 text-xs font-semibold text-omi-text-muted hover:border-omi-accent hover:text-omi-accent"
                >
                  {t("radar.v2.outcomes.close")}
                </button>
              </div>
            </header>

            <div className="grid min-h-0 flex-1 grid-cols-1 overflow-hidden md:grid-cols-[280px_minmax(0,1fr)]">
              <aside className="min-h-0 overflow-y-auto border-b border-omi-border-subtle bg-omi-surface-subtle p-3 md:border-b-0 md:border-r">
                {historyLoading && history.length === 0 ? (
                  <StateSurface title={t("radar.v2.outcomes.loading")} tone="loading" busy compact />
                ) : history.length === 0 ? (
                  <StateSurface title={t("radar.v2.outcomes.historyEmpty")} tone="empty" compact />
                ) : (
                  <div className="space-y-2">
                    {history.map((row) => {
                      const date = row.snapshot_date;
                      if (!date) return null;
                      const selected = date === selectedSnapshotDate;
                      return (
                        <button
                          key={date}
                          type="button"
                          data-testid={`watchlist-radar-v2-history-snapshot-${date}`}
                          onClick={() => onSelectSnapshot?.(date)}
                          className={[
                            "w-full border px-3 py-2 text-left transition",
                            selected
                              ? "border-omi-accent bg-omi-surface text-omi-text"
                              : "border-omi-border-subtle bg-omi-surface text-omi-text-muted hover:border-omi-accent",
                          ].join(" ")}
                        >
                          <span className="flex items-center justify-between gap-2">
                            <span className="font-semibold text-omi-text">{formatDate(date)}</span>
                            <span className="text-[11px] font-semibold">
                              {translatedCode(t, "status", row.status)}
                            </span>
                          </span>
                          <span className="mt-1 block text-xs">
                            {t("radar.v2.outcomes.historyCounts", {
                              finalized: row.finalized_count,
                              total: row.total_count,
                            })}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                )}
              </aside>

              <main className="min-h-0 overflow-y-auto p-5">
                {detailLoading ? (
                  <StateSurface title={t("radar.v2.outcomes.loading")} tone="loading" busy compact />
                ) : selectedSummary?.snapshot_date ? (
                  <div className="space-y-4">
                    <div>
                      <div className="text-xs font-semibold uppercase tracking-[0.14em] text-omi-text-muted">
                        {t("radar.v2.outcomes.snapshot")}
                      </div>
                      <h4 className="mt-1 text-xl font-bold text-omi-text-strong">
                        {formatDate(selectedSummary.snapshot_date)}
                      </h4>
                      <p className="mt-1 text-xs text-omi-text-muted">
                        {selectedSummary.rule_version} / {selectedSummary.outcome_contract_version} / T+{selectedSummary.horizon_trading_days}
                      </p>
                      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-omi-text-muted">
                        <span>
                          {t("radar.v2.outcomes.dataThrough")}: {formatDate(selectedSummary.latest_available_trade_date)}
                        </span>
                        <span>
                          {t("radar.v2.outcomes.lastChecked")}: {formatDateTime(selectedSummary.last_reconciled_at)}
                        </span>
                      </div>
                    </div>
                    <div className="grid grid-cols-1 gap-2 text-xs sm:grid-cols-3">
                      <div className="border border-omi-border-subtle bg-omi-surface-subtle px-3 py-2">
                        <div className="text-omi-text-muted">{t("radar.v2.outcomes.total")}</div>
                        <div className="mt-1 text-lg font-bold">{selectedSummary.total_count}</div>
                      </div>
                      <div className="border border-omi-success-border bg-omi-success-soft px-3 py-2">
                        <div className="text-omi-success">{t("radar.v2.outcomes.finalized")}</div>
                        <div className="mt-1 text-lg font-bold text-omi-success">{selectedSummary.finalized_count}</div>
                      </div>
                      <div className="border border-omi-warning-border bg-omi-warning-soft px-3 py-2">
                        <div className="text-omi-warning">{t("radar.v2.outcomes.pendingCount")}</div>
                        <div className="mt-1 text-lg font-bold text-omi-warning">{selectedSummary.pending_count}</div>
                      </div>
                    </div>
                    <StateCounts counts={selectedSummary.summary_state_counts} t={t} />
                    <PendingReasonCounts counts={selectedSummary.pending_reason_counts ?? {}} t={t} />
                    <div className="space-y-2" data-testid="watchlist-radar-v2-history-items">
                      {selectedSummary.items.length > 0 ? (
                        selectedSummary.items.map((item) => (
                          <OutcomeItem
                            key={`${item.evaluation_id ?? "na"}-${item.stock_id}`}
                            item={item}
                            t={t}
                          />
                        ))
                      ) : (
                        <StateSurface title={t("radar.v2.outcomes.empty")} tone="empty" compact />
                      )}
                    </div>
                    {selectedSummary.data_limitations.length > 0 ? (
                      <div className="border border-omi-border-subtle bg-omi-surface-subtle px-3 py-2 text-xs text-omi-text-muted">
                        {selectedSummary.data_limitations
                          .map((code) => summaryLimitationText(t, code))
                          .join("；")}
                      </div>
                    ) : null}
                  </div>
                ) : (
                  <StateSurface title={t("radar.v2.outcomes.historyEmpty")} tone="empty" compact />
                )}
              </main>
            </div>
          </div>
    </div>
  );
}
