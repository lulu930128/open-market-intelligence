import type { ChartEventMarker } from "@/components/chart/chartEventMarkers";
import type { ChartTimeframe } from "@/components/stock-detail/StockDetailDataViews";
import type { TranslationFunction } from "@/i18n";
import type { ChartPoint, TaiwanCorporateEventRead } from "@/types/market";

export type CorporateEventMarkerType =
  | "ex_dividend"
  | "financial_report"
  | "investor_conference";

export const corporateEventMarkerOptionKey = "corporate_events";
export const defaultCorporateEventMarkersEnabled = false;

const corporateEventMarkerTypes: CorporateEventMarkerType[] = [
  "ex_dividend",
  "financial_report",
  "investor_conference",
];

function normalizedDate(value: string) {
  return value.slice(0, 10);
}

function dateBucket(value: string, timeframe: ChartTimeframe) {
  const dateText = normalizedDate(value);
  const parsed = new Date(`${dateText}T00:00:00Z`);

  if (Number.isNaN(parsed.getTime())) return null;
  if (timeframe === "monthly") {
    return `${dateText.slice(0, 7)}-01`;
  }
  if (timeframe === "weekly") {
    const weekday = parsed.getUTCDay();
    const offset = weekday === 0 ? -6 : 1 - weekday;
    parsed.setUTCDate(parsed.getUTCDate() + offset);
    return parsed.toISOString().slice(0, 10);
  }
  return dateText;
}

function nextDailyChartTime(eventDate: string, chartData: ChartPoint[]) {
  const target = Date.parse(`${eventDate}T00:00:00Z`);

  if (!Number.isFinite(target)) return null;

  for (const point of chartData) {
    const pointDate = normalizedDate(point.time);
    const pointTimestamp = Date.parse(`${pointDate}T00:00:00Z`);
    const gapDays = (pointTimestamp - target) / 86_400_000;

    if (gapDays >= 0 && gapDays <= 4) return point.time;
    if (gapDays > 4) return null;
  }

  return null;
}

function chartTimeForEvent(
  eventDate: string,
  chartData: ChartPoint[],
  timeframe: ChartTimeframe
) {
  const bucket = dateBucket(eventDate, timeframe);

  if (!bucket) return null;

  const exact = chartData.find(
    (point) => dateBucket(point.time, timeframe) === bucket
  );
  if (exact) return exact.time;

  return timeframe === "daily" ? nextDailyChartTime(eventDate, chartData) : null;
}

function markerTone(eventType: CorporateEventMarkerType): ChartEventMarker["tone"] {
  if (eventType === "ex_dividend") return "success";
  if (eventType === "financial_report") return "warning";
  return "info";
}

export function corporateEventMarkerOption(
  enabled: boolean,
  t: TranslationFunction
) {
  return {
    key: corporateEventMarkerOptionKey,
    label: t("stockDetail.corporateEvents.chartMarkers.label"),
    description: t("stockDetail.corporateEvents.chartMarkers.description"),
    checked: enabled,
    plot: t("stockDetail.corporateEvents.chartMarkers.plot"),
  };
}

export function buildCorporateEventChartMarkers({
  chartData,
  enabled,
  events,
  timeframe,
  t,
}: {
  chartData: ChartPoint[];
  enabled: boolean;
  events: TaiwanCorporateEventRead[];
  timeframe: ChartTimeframe;
  t: TranslationFunction;
}): ChartEventMarker[] {
  if (!enabled || !chartData.length) return [];

  const markers = events.flatMap((event): ChartEventMarker[] => {
    const eventType = corporateEventMarkerTypes.find(
      (candidate) => candidate === event.event_type
    );

    if (!eventType) return [];

    const time = chartTimeForEvent(event.start_date, chartData, timeframe);
    if (!time) return [];

    const typeLabel = t(`stockDetail.corporateEvents.types.${eventType}`);
    const shortLabel = t(
      `stockDetail.corporateEvents.chartMarkers.short.${eventType}`
    );

    return [
      {
        id: event.event_id,
        eventType,
        time,
        label: shortLabel,
        title: `${event.start_date} · ${typeLabel} · ${event.title}`,
        tone: markerTone(eventType),
      },
    ];
  });

  const groupedMarkers = new Map<string, ChartEventMarker>();

  for (const marker of markers) {
    const key = `${marker.time}:${marker.eventType}`;
    const existing = groupedMarkers.get(key);

    if (!existing) {
      groupedMarkers.set(key, marker);
      continue;
    }

    groupedMarkers.set(key, {
      ...existing,
      id: key,
      title: `${existing.title}\n${marker.title}`,
    });
  }

  return [...groupedMarkers.values()].sort(
    (left, right) => left.time.localeCompare(right.time) || left.eventType.localeCompare(right.eventType)
  );
}
