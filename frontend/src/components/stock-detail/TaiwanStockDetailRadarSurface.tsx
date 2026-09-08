"use client";

import { OvernightImpactPanel } from "@/components/stock-detail/OvernightDataViews";
import StockPriceMap from "@/components/stock-detail/StockPriceMap";
import type {
  TechnicalCurrentState,
  TechnicalReport,
} from "@/components/stock-detail/TechnicalDataViews";
import { formatPct, formatPrice } from "@/components/stock-detail/stockDetailFormatters";
import type { LoadState, Timeframe } from "@/components/stock-detail/stockDetailTypes";
import type {
  StockSignalChip,
  StockSignalTone,
} from "@/components/stock-detail/stockDetailSignalProjection";
import { useTaiwanStockPriceMap } from "@/components/stock-detail/useTaiwanStockPriceMap";
import type { OvernightImpactRead } from "@/types/market";
import { useEffect, useMemo, useState, type ReactNode } from "react";

type SignalGroup = {
  key: string;
  label: string;
  chips: StockSignalChip[];
};

function timeframeLabel(timeframe: Timeframe) {
  if (timeframe === "today") return "今日";
  if (timeframe === "weekly") return "週線";
  if (timeframe === "monthly") return "月線";
  return "日線";
}

function signalToneClass(tone: StockSignalTone) {
  if (tone === "positive") return "omi-signal-chip-positive";
  if (tone === "negative") return "omi-signal-chip-negative";
  if (tone === "warning") return "omi-signal-chip-warning";
  return "omi-signal-chip-neutral";
}

function decisionToneClass(tone: string) {
  if (tone === "positive") return "text-omi-success";
  if (tone === "negative") return "text-omi-danger";
  if (tone === "warning") return "text-omi-warning-strong";
  return "text-omi-text-muted";
}

function RadarSkeletonSummary() {
  return (
    <div className="px-5 py-4" data-testid="tw-stock-detail-radar-summary-skeleton">
      <div className="h-3 w-28 animate-pulse bg-omi-surface-muted" />
      <div className="mt-3 h-5 w-2/3 animate-pulse bg-omi-surface-muted" />
      <div className="mt-2 h-3 w-full animate-pulse bg-omi-surface-muted" />
      <div className="mt-3 flex gap-2">
        {[32, 24, 28].map((width) => (
          <div key={width} className="h-6 animate-pulse bg-omi-surface-muted" style={{ width: `${width}%` }} />
        ))}
      </div>
    </div>
  );
}

function SectionToggle({
  children,
  description,
  onToggle,
  open,
  testId,
  title,
}: {
  children: ReactNode;
  description: string;
  onToggle: (open: boolean) => void;
  open: boolean;
  testId: string;
  title: string;
}) {
  const contentId = `${testId}-content`;
  return (
    <section className="border-t border-omi-border-subtle" data-testid={testId}>
      <button
        type="button"
        className="flex w-full items-start justify-between gap-4 px-5 py-3 text-left outline-none transition hover:bg-omi-surface-subtle focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-omi-accent"
        aria-controls={contentId}
        aria-expanded={open}
        onClick={() => onToggle(!open)}
      >
        <span className="min-w-0">
          <span className="block text-[11px] font-bold uppercase tracking-[0.14em] text-omi-text-muted">
            {title}
          </span>
          <span className="mt-0.5 block text-xs leading-4 text-omi-text-muted">{description}</span>
        </span>
        <span aria-hidden="true" className="shrink-0 text-base text-omi-text-muted">
          {open ? "−" : "+"}
        </span>
      </button>
      {open ? <div id={contentId}>{children}</div> : null}
    </section>
  );
}

function externalSummary(report: OvernightImpactRead | null, loadState: LoadState) {
  if (loadState === "idle") return "展開後讀取隔夜市場與 ADR／FX 背景";
  if (loadState === "loading") return "隔夜背景載入中";
  if (!report) return loadState === "error" ? "隔夜背景讀取失敗" : "隔夜背景資料不足";
  const quality = report.confidence === "high" ? "高完整度" : report.confidence === "medium" ? "部分完整" : "低完整度";
  const change = report.weighted_change_pct === null ? "影響未量化" : formatPct(report.weighted_change_pct);
  return `${report.title} · ${change} · ${quality}`;
}

export default function TaiwanStockDetailRadarSurface({
  enabled,
  loadState,
  onOvernightDemand,
  onRevealSignal,
  overnightImpact,
  overnightLoadState,
  provisionalState,
  signalGroups,
  stockId,
  technicalReport,
  technicalState,
  timeframe,
}: {
  enabled: boolean;
  loadState: LoadState;
  onOvernightDemand: () => void;
  onRevealSignal: (targetId: string, dataTabTarget?: StockSignalChip["dataTabTarget"]) => void;
  overnightImpact: OvernightImpactRead | null;
  overnightLoadState: LoadState;
  provisionalState: TechnicalCurrentState | null;
  signalGroups: SignalGroup[];
  stockId: string;
  technicalReport: TechnicalReport;
  technicalState: TechnicalCurrentState | null;
  timeframe: Timeframe;
}) {
  const [priceMapOpen, setPriceMapOpen] = useState(true);
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const [externalOpen, setExternalOpen] = useState(false);
  const [pendingSignalTarget, setPendingSignalTarget] = useState<string | null>(null);
  const [candidateRequest, setCandidateRequest] = useState<{
    stockId: string;
    value: number | null;
  } | null>(null);
  const candidateClose = candidateRequest?.stockId === stockId ? candidateRequest.value : null;
  const { loadState: priceMapLoadState, map } = useTaiwanStockPriceMap({
    candidateClose,
    enabled,
    stockId,
  });
  const evidenceSummary = useMemo(() => {
    const mapItems = map?.technical.evidence_summary ?? [];
    if (mapItems.length) {
      return mapItems
        .slice(0, 4)
        .map((item) => `${item.label ?? item.key ?? "證據"} ${item.display_value ?? "-"}`)
        .join(" · ");
    }
    if (technicalState?.evidence.length) {
      return technicalState.evidence
        .slice(0, 4)
        .map((item) => `${item.label} ${item.stateLabel}`)
        .join(" · ");
    }
    return "技術證據尚未完成";
  }, [map, technicalState]);
  const positionCount =
    technicalState && technicalState.position.availableCount > 0
      ? `${
          technicalState.position.belowCount > 0
            ? technicalState.position.belowCount
            : technicalState.position.aboveCount
        }/${technicalState.position.availableCount}`
      : "-";
  const decisionChanges = map?.decision_changes.slice(0, 4) ?? [];

  useEffect(() => {
    if (!evidenceOpen || !pendingSignalTarget) return;
    const target = document.getElementById(pendingSignalTarget);
    if (!(target instanceof HTMLElement)) return;
    target.scrollIntoView({ block: "nearest" });
    target.focus({ preventScroll: true });
  }, [evidenceOpen, pendingSignalTarget]);

  return (
    <div
      className="min-w-0 bg-omi-surface"
      data-stock-id={stockId}
      data-timeframe={timeframe}
      data-testid="tw-stock-detail-radar-v2"
    >
      {loadState === "loading" && !technicalState ? (
        <RadarSkeletonSummary />
      ) : (
        <section className="px-5 py-4" data-testid="tw-stock-detail-radar-summary">
          <div data-testid="tw-technical-current-state">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <div className="text-[11px] font-bold uppercase tracking-[0.14em] text-omi-text-muted">
                Stock detail radar · {timeframeLabel(timeframe)}
              </div>
              <div className="mt-1 text-lg font-semibold leading-5 text-omi-text-strong">
                {technicalState?.headline.label ?? technicalReport.title}
              </div>
              <div className="mt-1 text-xs leading-4 text-omi-text-muted">
                {technicalReport.summary}
              </div>
              {technicalReport.basisLabel ? (
                <div className="mt-1 text-[11px] leading-4 text-omi-text-subtle">
                  {technicalReport.basisLabel}
                  {technicalReport.warningCount ? (
                    <span className="ml-1 text-omi-warning">· {technicalReport.warningCount} 項限制</span>
                  ) : null}
                </div>
              ) : null}
            </div>
            <div className="shrink-0 border-l border-omi-border-subtle pl-4 text-right" data-testid="tw-technical-position-count">
              <div className="text-xl font-semibold leading-5 tabular-nums text-omi-text-strong">
                {positionCount}
              </div>
              <div className="mt-1 text-[11px] text-omi-text-muted">
                {technicalState?.position.label ?? technicalReport.valueLabel}
              </div>
              <div className="mt-0.5 max-w-40 text-[10px] leading-4 text-omi-text-subtle">
                {technicalState?.position.orderLabel ?? "完成資料仍在整理"}
              </div>
            </div>
          </div>
          {technicalReport.badges.length ? (
            <div className="mt-3 flex flex-wrap gap-1.5" data-testid="tw-stock-detail-radar-badges">
              {technicalReport.badges.slice(0, 5).map((badge) => (
                <span key={`${badge.label}:${badge.tone}`} className="border border-omi-border px-1.5 py-0.5 text-[11px] font-semibold text-omi-text-muted">
                  {badge.label}
                </span>
              ))}
            </div>
          ) : null}
          {provisionalState ? (
            <div className="mt-3 flex items-start justify-between gap-3 border-y border-omi-warning-border bg-omi-warning-soft px-3 py-2" data-testid="tw-stock-detail-radar-provisional">
              <span className="min-w-0">
                <span className="block text-[10px] font-bold uppercase tracking-[0.12em] text-omi-warning-strong">盤中暫估 · 不可作正式決策</span>
                <span className="mt-0.5 block text-xs text-omi-text-strong">
                  {provisionalState.headline.label} · {formatPrice(provisionalState.position.price)}
                </span>
              </span>
              <span className="shrink-0 text-[11px] text-omi-warning-strong">{provisionalState.qualifier.label}</span>
            </div>
          ) : null}
          </div>
        </section>
      )}

      <StockPriceMap
        key={stockId}
        candidateClose={candidateClose}
        loadState={priceMapLoadState}
        map={map}
        onCandidateClose={(value) => setCandidateRequest({ stockId, value })}
        onOpenChange={setPriceMapOpen}
        open={priceMapOpen}
        stockId={stockId}
      />

      <section className="border-t border-omi-border-subtle" data-testid="tw-stock-detail-radar-decision-changes">
        <div className="px-5 py-3">
          <div className="text-[11px] font-bold uppercase tracking-[0.14em] text-omi-text-muted">Decision changes · 條件變化</div>
          <div className="mt-0.5 text-xs text-omi-text-muted">價位到達後，Backend 認定的結構變化</div>
        </div>
        {priceMapLoadState === "loading" && !map ? (
          <div className="grid gap-px border-t border-omi-border-subtle bg-omi-border-subtle" data-testid="tw-stock-detail-radar-decision-skeleton">
            {[0, 1, 2].map((item) => (
              <div key={item} className="h-10 animate-pulse bg-omi-surface-muted" />
            ))}
          </div>
        ) : decisionChanges.length ? (
          <ol className="divide-y divide-omi-border-subtle border-t border-omi-border-subtle">
            {decisionChanges.map((item) => (
              <li
                key={item.key}
                className="grid grid-cols-[3rem_minmax(0,1fr)_auto] items-center gap-3 px-5 py-2.5 text-xs"
                data-decision-key={item.key}
                data-link-status={item.link_status}
                data-zone-id={item.zone_id ?? ""}
              >
                <span className={`font-bold tabular-nums ${decisionToneClass(item.tone)}`}>
                  {item.tier_label ?? "未連結"}
                </span>
                <span className="min-w-0 leading-5">
                  <span className="block truncate text-omi-text-muted">{item.label}</span>
                  <span className="block truncate text-[10px] text-omi-text-subtle">{item.result_summary}</span>
                </span>
                <span className="text-right text-[10px] font-semibold tabular-nums text-omi-text-subtle">
                  <span className="block">{formatPrice(item.threshold_price)}</span>
                  <span className="block">[{item.timeframe === "daily" ? "日" : item.timeframe}]</span>
                </span>
              </li>
            ))}
          </ol>
        ) : (
          <div className="border-t border-omi-border-subtle px-5 py-3 text-xs text-omi-text-muted">
            目前 Backend 沒有可用的條件變化；不從價位帶自行推導。
          </div>
        )}
      </section>

      <SectionToggle
        description={evidenceSummary}
        onToggle={setEvidenceOpen}
        open={evidenceOpen}
        testId="tw-stock-detail-radar-evidence"
        title="Evidence · 判斷依據"
      >
        <div className="border-t border-omi-border-subtle px-5 pb-3">
          {(map?.technical.evidence_summary ?? []).slice(0, 6).map((item) => (
            <div key={item.key ?? item.label} className="grid grid-cols-[minmax(0,1fr)_auto] gap-3 border-b border-omi-border-subtle py-2 text-xs">
              <span className="text-omi-text-muted">{item.label ?? item.key ?? "證據"}</span>
              <span className="font-semibold text-omi-text-strong">{item.display_value ?? "-"}</span>
            </div>
          ))}
          {!map?.technical.evidence_summary.length && technicalState?.evidence.map((item) => (
            <div
              key={item.key}
              id={`tw-technical-evidence-${item.key}`}
              data-testid={`tw-technical-evidence-${item.key}`}
              tabIndex={-1}
              className="grid gap-1 border-b border-omi-border-subtle py-2 text-xs outline-none sm:grid-cols-[8rem_minmax(0,1fr)]"
            >
              <span className="font-semibold text-omi-text-strong">{item.label} · {item.stateLabel}</span>
              <span className="text-omi-text-muted">{item.summary}</span>
            </div>
          ))}
          {signalGroups.map((group) => (
            <div key={group.key} className="border-b border-omi-border-subtle py-2 last:border-b-0" data-testid={`tw-signal-chip-group-${group.key}`}>
              <div className="text-[10px] font-semibold text-omi-text-subtle">{group.label}</div>
              <div className="mt-1.5 flex flex-wrap gap-1">
                {group.chips.map((signal) => {
                  const content = `${signal.source}：${signal.label}`;
                  const className = `omi-signal-chip border px-1.5 py-0.5 text-[11px] font-semibold ${signalToneClass(signal.tone)} ${signal.detailTarget ? "transition hover:border-omi-control focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-omi-accent" : ""}`;
                  return signal.detailTarget ? (
                    <button
                      key={signal.key}
                      type="button"
                      className={className}
                      data-testid={`tw-signal-chip-${signal.key}`}
                      title={signal.title}
                      onClick={() => {
                        const target = signal.detailTarget ?? "";
                        if (target.startsWith("tw-technical-evidence-")) {
                          setPendingSignalTarget(target);
                          setEvidenceOpen(true);
                          return;
                        }
                        if (target === "tw-technical-context") {
                          setExternalOpen(true);
                          if (overnightLoadState === "idle") onOvernightDemand();
                          return;
                        }
                        onRevealSignal(target, signal.dataTabTarget);
                      }}
                    >
                      {content}
                    </button>
                  ) : (
                    <span key={signal.key} className={className} data-testid={`tw-signal-chip-${signal.key}`} title={signal.title}>{content}</span>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      </SectionToggle>

      <SectionToggle
        description={externalSummary(overnightImpact, overnightLoadState)}
        onToggle={(nextOpen) => {
          setExternalOpen(nextOpen);
          if (nextOpen && overnightLoadState === "idle") onOvernightDemand();
        }}
        open={externalOpen}
        testId="tw-stock-detail-radar-external"
        title="External context · 外部背景"
      >
        <div className="border-t border-omi-border-subtle px-5 pb-3">
          <OvernightImpactPanel
            onDemand={onOvernightDemand}
            report={overnightImpact}
            loadState={overnightLoadState}
          />
        </div>
      </SectionToggle>
    </div>
  );
}
