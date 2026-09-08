"use client";

import { LoadingDots } from "@/components/LoadingPlaceholders";
import { formatPct, formatPrice } from "@/components/stock-detail/stockDetailFormatters";
import type { LoadState } from "@/components/stock-detail/stockDetailTypes";
import type { StockPriceMapRead, StockPriceMapZoneRead } from "@/types/market";
import { useMemo, useState } from "react";

type PositionedZone = {
  actualTop: number;
  displayTop: number;
  lowerTop: number;
  upperTop: number;
  zone: StockPriceMapZoneRead;
};

type DecisionChange = StockPriceMapRead["decision_changes"][number];

type PositionedTrigger = {
  actualTop: number;
  displayTop: number;
  trigger: DecisionChange;
};

function statusTone(status: StockPriceMapRead["status"]) {
  if (status === "ready") return "border-omi-success-border text-omi-success";
  if (status === "partial" || status === "pending") {
    return "border-omi-warning-border text-omi-warning-strong";
  }
  if (status === "stale") return "border-omi-danger-border text-omi-danger";
  return "border-omi-border text-omi-text-muted";
}

function zoneTone(zone: StockPriceMapZoneRead) {
  if (zone.confidence === "low" || zone.evidence_state === "estimated") {
    return {
      band: "border-omi-border bg-omi-surface-muted/55",
      marker: "border-omi-text-subtle bg-omi-surface",
      text: "text-omi-text-muted",
    };
  }
  if (zone.role === "support_candidate" || zone.role === "support") {
    return {
      band: "border-omi-success-border bg-omi-success-soft/40",
      marker: "border-omi-success bg-omi-surface",
      text: "text-omi-success",
    };
  }
  if (zone.role === "reclaim" || zone.role === "resistance") {
    return {
      band: "border-omi-warning-border bg-omi-warning-soft/45",
      marker: "border-omi-warning bg-omi-surface",
      text: "text-omi-warning-strong",
    };
  }
  return {
    band: "border-omi-accent/45 bg-omi-accent/5",
    marker: "border-omi-accent bg-omi-surface",
    text: "text-omi-accent",
  };
}

function zoneRoleLabel(zone: StockPriceMapZoneRead) {
  if (zone.role === "support_candidate" || zone.role === "support") return "支撐";
  if (zone.role === "reclaim") return "修復";
  if (zone.role === "resistance") return "壓力";
  return "樞紐";
}

function zoneRange(zone: StockPriceMapZoneRead) {
  if (zone.lower_bound === zone.upper_bound) return formatPrice(zone.anchor_price);
  return `${formatPrice(zone.lower_bound)}–${formatPrice(zone.upper_bound)}`;
}

function nearestText(map: StockPriceMapRead | null) {
  if (!map) return "價位結構載入中";
  const current = formatPrice(map.reference.price);
  const up = map.nearest_upside;
  const down = map.nearest_downside;
  return [
    up ? `${up.tier_label} ${formatPrice(up.lower_bound)}–${formatPrice(up.upper_bound)}` : "上方未觀測",
    `現價 ${current}`,
    down ? `${down.tier_label} ${formatPrice(down.lower_bound)}–${formatPrice(down.upper_bound)}` : "下方未觀測",
  ].join(" · ");
}

function axisPosition(price: number, lower: number, upper: number) {
  if (upper <= lower) return 50;
  return Math.max(0, Math.min(100, ((upper - price) / (upper - lower)) * 100));
}

function zonesWithinAxis(map: StockPriceMapRead | null) {
  const lower = map?.axis.lower_bound;
  const upper = map?.axis.upper_bound;
  if (!map || lower === null || lower === undefined || upper === null || upper === undefined) {
    return [];
  }
  return map.zones.filter(
    (zone) => zone.upper_bound >= lower && zone.lower_bound <= upper
  );
}

function zonesOutsideAxis(map: StockPriceMapRead | null) {
  const lower = map?.axis.lower_bound;
  const upper = map?.axis.upper_bound;
  if (!map || lower === null || lower === undefined || upper === null || upper === undefined) {
    return { above: [], below: [] };
  }
  return {
    above: map.zones.filter((zone) => zone.lower_bound > upper),
    below: map.zones.filter((zone) => zone.upper_bound < lower),
  };
}

function layoutZones(
  map: StockPriceMapRead | null,
  visibleZones: StockPriceMapZoneRead[]
): PositionedZone[] {
  const lower = map?.axis.lower_bound;
  const upper = map?.axis.upper_bound;
  if (!map || lower === null || lower === undefined || upper === null || upper === undefined) {
    return [];
  }
  const minimumGap = 11;
  const positioned = visibleZones
    .map((zone) => ({
      actualTop: axisPosition(zone.anchor_price, lower, upper),
      displayTop: axisPosition(zone.anchor_price, lower, upper),
      lowerTop: axisPosition(zone.lower_bound, lower, upper),
      upperTop: axisPosition(zone.upper_bound, lower, upper),
      zone,
    }))
    .sort((left, right) => left.actualTop - right.actualTop);

  for (let index = 1; index < positioned.length; index += 1) {
    positioned[index].displayTop = Math.max(
      positioned[index].actualTop,
      positioned[index - 1].displayTop + minimumGap
    );
  }
  const overflow = (positioned.at(-1)?.displayTop ?? 0) - 96;
  if (overflow > 0) {
    for (const item of positioned) item.displayTop -= overflow;
  }
  for (let index = positioned.length - 2; index >= 0; index -= 1) {
    positioned[index].displayTop = Math.min(
      positioned[index].displayTop,
      positioned[index + 1].displayTop - minimumGap
    );
  }
  for (const item of positioned) {
    item.displayTop = Math.max(4, Math.min(96, item.displayTop));
  }
  return positioned;
}

function layoutTriggers(map: StockPriceMapRead | null): PositionedTrigger[] {
  const lower = map?.axis.lower_bound;
  const upper = map?.axis.upper_bound;
  if (!map || lower === null || lower === undefined || upper === null || upper === undefined) {
    return [];
  }
  const positioned = map.decision_changes
    .filter(
      (trigger) =>
        trigger.threshold_price !== null &&
        trigger.threshold_price >= lower &&
        trigger.threshold_price <= upper
    )
    .map((trigger) => {
      const actualTop = axisPosition(trigger.threshold_price as number, lower, upper);
      let displayTop = actualTop;
      if (Math.abs(actualTop - 50) < 5) {
        displayTop = actualTop < 50 ? 40 : 60;
      }
      return { actualTop, displayTop, trigger };
    })
    .sort((left, right) => left.actualTop - right.actualTop);

  const minimumGap = 7;
  for (let index = 1; index < positioned.length; index += 1) {
    positioned[index].displayTop = Math.max(
      positioned[index].displayTop,
      positioned[index - 1].displayTop + minimumGap
    );
  }
  const overflow = (positioned.at(-1)?.displayTop ?? 0) - 96;
  if (overflow > 0) {
    for (const item of positioned) item.displayTop -= overflow;
  }
  for (const item of positioned) {
    item.displayTop = Math.max(4, Math.min(96, item.displayTop));
  }
  return positioned;
}

function PriceMapSkeleton() {
  return (
    <div className="grid min-h-[26rem] grid-cols-[4.5rem_minmax(0,1fr)] gap-4 px-4 py-4" data-testid="tw-stock-price-map-skeleton">
      <div className="space-y-8 pt-1">
        {Array.from({ length: 7 }, (_, index) => (
          <div key={index} className="h-3 animate-pulse bg-omi-surface-muted" />
        ))}
      </div>
      <div className="relative border-l border-omi-border-subtle">
        {[12, 31, 50, 69, 88].map((top) => (
          <div key={top} className="absolute left-4 right-2 h-8 animate-pulse bg-omi-surface-muted" style={{ top: `${top}%` }} />
        ))}
      </div>
    </div>
  );
}

export default function StockPriceMap({
  candidateClose,
  loadState,
  map,
  onCandidateClose,
  onOpenChange,
  open,
  stockId,
}: {
  candidateClose: number | null;
  loadState: LoadState;
  map: StockPriceMapRead | null;
  onCandidateClose: (value: number | null) => void;
  onOpenChange: (open: boolean) => void;
  open: boolean;
  stockId: string;
}) {
  const [candidateInput, setCandidateInput] = useState("");
  const [scenarioOpen, setScenarioOpen] = useState(false);
  const visibleZones = useMemo(() => zonesWithinAxis(map), [map]);
  const outsideZones = useMemo(() => zonesOutsideAxis(map), [map]);
  const zones = useMemo(() => layoutZones(map, visibleZones), [map, visibleZones]);
  const triggers = useMemo(() => layoutTriggers(map), [map]);
  const outsideLinkedTriggers = useMemo(() => {
    const lower = map?.axis.lower_bound;
    const upper = map?.axis.upper_bound;
    if (!map || lower === null || lower === undefined || upper === null || upper === undefined) {
      return [];
    }
    return map.decision_changes.filter(
      (trigger) =>
        trigger.threshold_price !== null &&
        (trigger.threshold_price < lower || trigger.threshold_price > upper)
    );
  }, [map]);
  const axisReady = Boolean(
    map &&
      map.axis.range_kind === "display_range" &&
      map.axis.lower_bound !== null &&
      map.axis.upper_bound !== null
  );

  const submitCandidate = () => {
    const parsed = Number(candidateInput);
    if (Number.isFinite(parsed) && parsed > 0) onCandidateClose(parsed);
  };

  return (
    <section
      className="border-t border-omi-border-subtle bg-omi-surface"
      data-decision-usable={map?.decision_usable ?? false}
      data-reference-price={map?.reference.price ?? ""}
      data-stock-id={map?.stock_id ?? stockId}
      data-version={map?.version ?? "pending"}
      data-testid="tw-stock-price-map"
    >
      <div className="flex items-start justify-between gap-4 px-5 py-3">
        <button
          type="button"
          className="min-w-0 flex-1 text-left outline-none focus-visible:ring-2 focus-visible:ring-omi-accent"
          aria-controls="tw-stock-price-map-content"
          aria-expanded={open}
          onClick={() => onOpenChange(!open)}
          data-testid="tw-stock-price-map-toggle"
        >
          <span className="block text-[11px] font-bold uppercase tracking-[0.14em] text-omi-text-muted">
            Price map · 完成日線
          </span>
          <span className="mt-0.5 block text-sm font-semibold text-omi-text-strong">
            {nearestText(map)}
          </span>
          <span className="mt-0.5 block text-[11px] leading-4 text-omi-text-subtle">
            {map?.reference.trade_date
              ? `${map.reference.trade_date} · ${map.reference.freshness_status}`
              : "等待完成日線參考價"}
          </span>
        </button>
        <span className="flex shrink-0 items-center gap-2">
          {map ? (
            <span className={`border px-2 py-1 text-[10px] font-semibold ${statusTone(map.status)}`} data-testid="tw-stock-price-map-status">
              {map.status === "ready"
                ? "可判讀"
                : map.status === "partial"
                  ? "部分證據"
                  : map.status === "stale"
                    ? "資料過期"
                    : map.status === "pending"
                      ? "等待更新"
                      : "資料不足"}
            </span>
          ) : loadState === "loading" ? (
            <LoadingDots label="載入價位地圖" />
          ) : null}
          <span aria-hidden="true" className="text-base text-omi-text-muted">
            {open ? "−" : "+"}
          </span>
        </span>
      </div>

      {open ? (
        <div id="tw-stock-price-map-content" className="border-t border-omi-border-subtle">
          {loadState === "error" && !map ? (
            <div className="px-5 py-4 text-xs leading-5 text-omi-danger">
              價位地圖讀取失敗；其他技術證據仍可獨立使用。
            </div>
          ) : null}
          {!map && loadState !== "error" ? <PriceMapSkeleton /> : null}

          {map && axisReady ? (
            <div className="px-4 pb-3 pt-4">
              <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
                <div>
                  <div className="text-[11px] font-semibold text-omi-text-muted">研究顯示範圍</div>
                  <div className="mt-0.5 text-xs text-omi-text-subtle">
                    完成日線區間由 Backend 定義；不是交易所法定漲跌停報價
                  </div>
                </div>
                <button
                  type="button"
                  className="border border-omi-border px-2.5 py-1.5 text-xs font-semibold text-omi-text-muted transition hover:border-omi-control hover:text-omi-text-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-omi-accent"
                  aria-expanded={scenarioOpen}
                  onClick={() => setScenarioOpen((current) => !current)}
                  data-testid="tw-stock-price-map-scenario-toggle"
                >
                  自訂收盤情境
                </button>
              </div>

              {scenarioOpen ? (
                <div className="mb-4 border-y border-omi-border-subtle bg-omi-surface-muted px-3 py-3" data-testid="tw-stock-price-map-scenario-tool">
                  <div className="text-xs font-semibold text-omi-text-strong">下一交易日收盤情境</div>
                  <div className="mt-0.5 text-[11px] leading-4 text-omi-text-muted">
                    Backend 依有效 tick 重算 projected MA；不是盤中觸價預測。
                  </div>
                  <div className="mt-2 flex gap-2">
                    <input
                      className="min-w-0 flex-1 border border-omi-border bg-omi-surface px-2.5 py-2 text-sm tabular-nums text-omi-text-strong outline-none focus:border-omi-accent"
                      inputMode="decimal"
                      aria-label="候選收盤價"
                      placeholder={formatPrice(map.reference.price)}
                      value={candidateInput}
                      onChange={(event) => setCandidateInput(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") submitCandidate();
                      }}
                      data-testid="tw-stock-price-map-candidate-input"
                    />
                    <button
                      type="button"
                      className="border border-omi-accent bg-omi-accent px-3 py-2 text-xs font-semibold text-white transition hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-omi-accent"
                      onClick={submitCandidate}
                      disabled={!candidateInput.trim()}
                      data-testid="tw-stock-price-map-candidate-submit"
                    >
                      試算
                    </button>
                  </div>
                  {map.candidate.projections.length ? (
                    <div className="mt-3 grid gap-px bg-omi-border-subtle sm:grid-cols-3" data-testid="tw-stock-price-map-candidate-results">
                      {map.candidate.projections.map((projection) => (
                        <div key={projection.period} className="bg-omi-surface px-3 py-2 text-xs">
                          <div className="text-omi-text-muted">MA{projection.period}</div>
                          <div className="mt-0.5 font-semibold tabular-nums text-omi-text-strong">
                            {formatPrice(projection.projected_ma)}
                          </div>
                          <div className="text-[10px] tabular-nums text-omi-text-subtle">
                            門檻 {formatPrice(projection.transition_price)}
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : candidateClose !== null && loadState === "loading" ? (
                    <div className="mt-2 text-xs text-omi-text-muted">情境重算中…</div>
                  ) : null}
                </div>
              ) : null}

              {outsideZones.above.length || outsideZones.below.length || outsideLinkedTriggers.length ? (
                <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1 border-y border-omi-border-subtle bg-omi-surface-muted px-3 py-2 text-[10px] leading-4" data-testid="tw-stock-price-map-outside-axis">
                  <span className="font-semibold text-omi-text-muted">軸外證據</span>
                  {outsideZones.above.length ? (
                    <span className="text-omi-warning-strong" data-testid="tw-stock-price-map-outside-above">
                      上方尚有 {outsideZones.above.length} 區
                    </span>
                  ) : null}
                  {outsideZones.below.length ? (
                    <span className="text-omi-success" data-testid="tw-stock-price-map-outside-below">
                      下方尚有 {outsideZones.below.length} 區
                    </span>
                  ) : null}
                  {outsideLinkedTriggers.map((trigger) => (
                    <span key={trigger.key} className="font-semibold text-omi-danger" data-testid={`tw-stock-price-map-outside-trigger-${trigger.key}`}>
                      {trigger.tier_label ? `${trigger.tier_label} · ` : ""}{formatPrice(trigger.threshold_price)} {trigger.result_summary}
                    </span>
                  ))}
                </div>
              ) : null}

              <figure className="relative h-[26rem] overflow-hidden border-y border-omi-border-subtle bg-omi-surface-subtle" aria-label={`${map.stock_id} 完成日線分層價位地圖`} data-testid="tw-stock-price-axis">
                <figcaption className="sr-only">
                  現價 {formatPrice(map.reference.price)}。{nearestText(map)}。共有 {map.zones.length} 個研究價位區與 {map.decision_changes.length} 個條件觸發點。
                </figcaption>
                {map.axis.ticks.map((tick) => {
                  const lower = map.axis.lower_bound as number;
                  const upper = map.axis.upper_bound as number;
                  const top = axisPosition(tick.price, lower, upper);
                  const isReference = tick.percent === 0;
                  return (
                    <div key={tick.percent} className="absolute left-0 right-0" style={{ top: `${top}%` }} data-axis-percent={tick.percent} data-axis-price={tick.price}>
                      <div className={`absolute left-[4.65rem] right-0 border-t ${isReference ? "border-omi-accent/60" : "border-omi-border-subtle"}`} />
                      <div className="absolute left-0 top-[-0.65rem] grid w-[4.15rem] grid-cols-[2rem_minmax(0,1fr)] items-center gap-1 text-[10px] tabular-nums">
                        <span className={isReference ? "font-bold text-omi-accent" : "text-omi-text-subtle"}>
                          {tick.percent > 0 ? `+${tick.percent}` : tick.percent}%
                        </span>
                        <span className="text-right text-omi-text-muted">{formatPrice(tick.price)}</span>
                      </div>
                    </div>
                  );
                })}

                <div className="absolute bottom-0 left-[4.65rem] top-0 border-l border-omi-border" />

                {!zones.length ? (
                  <div className="absolute left-[5.75rem] top-4 border-y border-omi-border-subtle bg-omi-surface/90 px-2 py-1 text-[10px] text-omi-text-muted" data-testid="tw-stock-price-map-no-zones">
                    軸內尚未形成顯著價位區；比例軸與完成日線參考仍保留。
                  </div>
                ) : null}

                {zones.map((item) => {
                  const tone = zoneTone(item.zone);
                  const bandTop = Math.min(item.lowerTop, item.upperTop);
                  const bandHeight = Math.max(1, Math.abs(item.lowerTop - item.upperTop));
                  const connectorTop = Math.min(item.actualTop, item.displayTop);
                  const connectorHeight = Math.abs(item.actualTop - item.displayTop);
                  return (
                    <div
                      key={item.zone.zone_id}
                      data-testid={`tw-stock-price-zone-${item.zone.zone_id}`}
                      data-axis-position={item.actualTop.toFixed(3)}
                      data-evidence-bounds={`${item.zone.evidence_lower_bound}:${item.zone.evidence_upper_bound}`}
                      data-tier={item.zone.tier_label}
                      data-zone-bounds={`${item.zone.lower_bound}:${item.zone.upper_bound}`}
                    >
                      <div className={`absolute left-[4.65rem] right-0 border-y ${tone.band}`} style={{ top: `${bandTop}%`, height: `${bandHeight}%` }} />
                      <span className={`absolute left-[4.3rem] z-10 h-3 w-3 border-2 ${tone.marker}`} style={{ top: `calc(${item.actualTop}% - 0.375rem)` }} />
                      {connectorHeight > 0.5 ? (
                        <span className="absolute left-[5.35rem] w-px bg-omi-border" style={{ top: `${connectorTop}%`, height: `${connectorHeight}%` }} />
                      ) : null}
                      <div
                        className="absolute left-[5.75rem] right-[6.75rem] z-20 -translate-y-1/2"
                        style={{ top: `${item.displayTop}%` }}
                        data-testid={`tw-stock-price-zone-label-${item.zone.zone_id}`}
                      >
                        <div className="grid w-full grid-cols-[2.25rem_minmax(0,1fr)] items-stretch border-y border-omi-border-subtle bg-omi-surface/95">
                          <span className={`grid place-items-center border-r border-omi-border-subtle px-1.5 text-[11px] font-bold tabular-nums ${tone.text}`}>
                            {item.zone.tier_label}
                          </span>
                          <span
                            className="min-w-0 truncate px-2 py-1 text-[10px] font-semibold tabular-nums text-omi-text-strong"
                            title={`${item.zone.tier_label} ${zoneRoleLabel(item.zone)} ${zoneRange(item.zone)} · ${item.zone.primary_label} · ${item.zone.evidence_count} 證據 / ${item.zone.method_family_count} 方法 · ${formatPct(item.zone.distance_pct)}`}
                          >
                            {zoneRange(item.zone)} · {zoneRoleLabel(item.zone)}
                          </span>
                        </div>
                      </div>
                    </div>
                  );
                })}

                {triggers.map((item) => {
                  const connectorTop = Math.min(item.actualTop, item.displayTop);
                  const connectorHeight = Math.abs(item.actualTop - item.displayTop);
                  return (
                    <div key={item.trigger.key} data-testid={`tw-stock-price-map-trigger-${item.trigger.key}`} data-trigger-price={item.trigger.threshold_price} data-trigger-tier={item.trigger.tier_label ?? "unlinked"}>
                      <div className="absolute left-[4.65rem] right-0 z-20 border-t border-dashed border-omi-text-subtle/70" style={{ top: `${item.actualTop}%` }} />
                      <span className="absolute right-[1.25rem] z-30 h-2 w-2 rotate-45 border border-omi-text-strong bg-omi-surface" style={{ top: `calc(${item.actualTop}% - 0.25rem)` }} />
                      {connectorHeight > 0.5 ? (
                        <span className="absolute right-[1.45rem] z-20 w-px bg-omi-border" style={{ top: `${connectorTop}%`, height: `${connectorHeight}%` }} />
                      ) : null}
                      <div className="absolute right-2 z-30 max-w-[17rem] -translate-y-1/2" style={{ top: `${item.displayTop}%` }} data-testid={`tw-stock-price-map-trigger-label-${item.trigger.key}`}>
                        <div
                          className="border-y border-omi-border-subtle bg-omi-surface/95 px-2 py-1 text-right text-[10px] font-semibold tabular-nums text-omi-text-strong"
                          title={`${item.trigger.label} → ${item.trigger.result_summary}`}
                        >
                          {item.trigger.tier_label ? `${item.trigger.tier_label} · ` : ""}{formatPrice(item.trigger.threshold_price)}
                        </div>
                      </div>
                    </div>
                  );
                })}

                {map.markers.map((marker) => {
                  const lower = map.axis.lower_bound as number;
                  const upper = map.axis.upper_bound as number;
                  const top = axisPosition(marker.price, lower, upper);
                  return (
                    <div key={`${marker.kind}:${marker.price}`} className="absolute left-[4.65rem] right-0 z-40" style={{ top: `${top}%` }} data-marker-kind={marker.kind} data-marker-price={marker.price} data-testid={`tw-stock-price-map-marker-${marker.kind}`}>
                      <div className="border-t-2 border-omi-accent" />
                      <div className="absolute right-2 top-[-1.35rem] bg-omi-accent px-2 py-0.5 text-[10px] font-semibold text-white" data-testid="tw-stock-price-map-current-label">
                        現價 · {formatPrice(marker.price)}
                      </div>
                    </div>
                  );
                })}
              </figure>

              <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-[10px] leading-4 text-omi-text-subtle">
                <span>{map.levels.length} 個精確價位 → {map.zones.length} 個研究區 · {map.version}</span>
                <span>{map.basis_revision}</span>
              </div>
              {map.axis.limitations[0] ? (
                <div className="mt-1 text-[10px] leading-4 text-omi-warning">
                  研究軸固定為完成日線參考價上下 10%；不是交易所法定漲跌停報價。
                </div>
              ) : null}
              <details className="mt-2 border-y border-omi-border-subtle text-[10px] text-omi-text-muted" data-testid="tw-stock-price-map-accessible-details">
                <summary className="cursor-pointer px-2 py-1.5 font-semibold outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-omi-accent">
                  價位區與觸發條件明細
                </summary>
                <ol className="divide-y divide-omi-border-subtle border-t border-omi-border-subtle">
                  {map.zones.map((zone) => (
                    <li key={zone.zone_id} className="grid gap-1 px-2 py-2 sm:grid-cols-[3rem_8rem_minmax(0,1fr)_auto]">
                      <span className="font-bold text-omi-text-strong">{zone.tier_label}</span>
                      <span className="tabular-nums">{zoneRange(zone)}</span>
                      <span>{zone.primary_label} · {zone.labels.join("、")}</span>
                      <span className="tabular-nums">{zone.evidence_count} 證據 / {zone.method_family_count} 方法</span>
                    </li>
                  ))}
                  {map.decision_changes.map((trigger) => (
                    <li key={trigger.key} className="grid gap-1 px-2 py-2 sm:grid-cols-[3rem_8rem_minmax(0,1fr)]">
                      <span className="font-bold text-omi-text-strong">{trigger.tier_label ?? "—"}</span>
                      <span className="tabular-nums">{formatPrice(trigger.threshold_price)}</span>
                      <span>{trigger.label} → {trigger.result_summary}</span>
                    </li>
                  ))}
                </ol>
              </details>
            </div>
          ) : map ? (
            <div className="px-5 py-6 text-xs leading-5 text-omi-text-muted">
              缺少完成日線參考價，比例價位軸暫不可用。
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
