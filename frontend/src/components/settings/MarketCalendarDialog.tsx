"use client";

import { useI18n, useT } from "@/i18n";
import { fetchJson } from "@/lib/api";
import { emitDataStatusEvent, type DataStatusLevel } from "@/lib/dataStatusEvents";
import type {
  USCorporateEventListRead,
  USCorporateEventRead,
} from "@/types/corporateEvents";
import type {
  TaiwanCorporateEventListRead,
  TaiwanCorporateEventRead,
} from "@/types/market";
import { useCallback, useEffect, useMemo, useState } from "react";


type MarketCalendarDialogProps = {
  open: boolean;
  onClose: () => void;
};

type CalendarMarket = "tw" | "us" | "jp" | "kr";
type EventFilter =
  | "all"
  | "ex_dividend"
  | "financial_report"
  | "investor_conference"
  | "earnings"
  | "dividend"
  | "split";

type CalendarSource = {
  source: string;
  status: string;
  freshness: string | null;
  coverage: string | null;
  warning: string | null;
};

type CalendarEvent = {
  eventId: string;
  eventType: string;
  symbol: string;
  companyName: string | null;
  eventDate: string;
  endDate: string;
  eventTime: string | null;
  title: string;
  summary: string | null;
  location: string | null;
  status: string;
  sourceName: string;
  sourceUrl: string | null;
  companyUrl: string | null;
  videoUrl: string | null;
  cashDividend: number | null;
  stockDividendRatio: number | null;
  dividendAmount: number | null;
  dividendCurrency: string | null;
  splitRatio: number | null;
  estimatedEps: number | null;
  fiscalPeriodEnd: string | null;
  warnings: string[];
};

type CalendarPayload = {
  market: "tw" | "us";
  generatedAt: string;
  dateFrom: string;
  dateTo: string;
  resultCount: number;
  warning: string | null;
  sources: Record<string, CalendarSource>;
  results: CalendarEvent[];
};

const marketOptions: Array<{ key: CalendarMarket; enabled: boolean }> = [
  { key: "tw", enabled: true },
  { key: "us", enabled: true },
  { key: "jp", enabled: false },
  { key: "kr", enabled: false },
];

const filtersByMarket: Record<"tw" | "us", EventFilter[]> = {
  tw: ["all", "ex_dividend", "financial_report", "investor_conference"],
  us: ["all", "earnings", "dividend", "split"],
};

const marketTimezones: Record<"tw" | "us", string> = {
  tw: "Asia/Taipei",
  us: "America/New_York",
};

function eventTone(eventType: string) {
  if (eventType === "ex_dividend" || eventType === "dividend") {
    return "border-omi-success bg-omi-success-soft text-omi-success-strong";
  }
  if (eventType === "financial_report" || eventType === "earnings") {
    return "border-omi-warning bg-omi-warning-soft text-omi-warning-strong";
  }
  if (eventType === "split") {
    return "border-omi-danger-border bg-omi-danger-soft text-omi-danger";
  }
  return "border-omi-info bg-omi-info-soft text-omi-info-strong";
}

function sourceTone(status: string, freshness: string | null) {
  if (status === "current" && freshness !== "stale") return "text-omi-market-up";
  if (
    status === "stale" ||
    status === "degraded" ||
    status === "watchlist_only" ||
    freshness === "stale"
  ) {
    return "text-omi-warning";
  }
  return "text-omi-danger";
}

function normalizeTaiwanEvent(event: TaiwanCorporateEventRead): CalendarEvent {
  return {
    eventId: event.event_id,
    eventType: event.event_type,
    symbol: event.stock_id,
    companyName: event.stock_name,
    eventDate: event.start_date,
    endDate: event.end_date,
    eventTime: event.start_time,
    title: event.title,
    summary: event.summary,
    location: event.location,
    status: event.status,
    sourceName: event.source_name,
    sourceUrl: event.source_url,
    companyUrl: event.company_url,
    videoUrl: event.video_url,
    cashDividend: event.cash_dividend,
    stockDividendRatio: event.stock_dividend_ratio,
    dividendAmount: null,
    dividendCurrency: null,
    splitRatio: null,
    estimatedEps: null,
    fiscalPeriodEnd: null,
    warnings: [],
  };
}

function normalizeUsEvent(event: USCorporateEventRead): CalendarEvent {
  return {
    eventId: event.event_id,
    eventType: event.event_type,
    symbol: event.symbol,
    companyName: event.company_name,
    eventDate: event.event_date,
    endDate: event.event_date,
    eventTime: event.event_time,
    title: event.title,
    summary: event.description,
    location: null,
    status: event.event_status,
    sourceName: event.source,
    sourceUrl: event.source_url,
    companyUrl: null,
    videoUrl: null,
    cashDividend: null,
    stockDividendRatio: null,
    dividendAmount: event.dividend_amount,
    dividendCurrency: event.dividend_currency,
    splitRatio: event.split_ratio,
    estimatedEps: event.estimated_eps,
    fiscalPeriodEnd: event.fiscal_period_end,
    warnings: event.warnings,
  };
}

function normalizeTaiwanPayload(payload: TaiwanCorporateEventListRead): CalendarPayload {
  return {
    market: "tw",
    generatedAt: payload.generated_at,
    dateFrom: payload.date_from,
    dateTo: payload.date_to,
    resultCount: payload.result_count,
    warning: payload.warning,
    sources: Object.fromEntries(
      Object.entries(payload.sources).map(([key, source]) => [
        key,
        {
          source: source.source,
          status: source.status,
          freshness: source.status,
          coverage: null,
          warning: source.warning,
        },
      ])
    ),
    results: payload.results.map(normalizeTaiwanEvent),
  };
}

function normalizeUsPayload(payload: USCorporateEventListRead): CalendarPayload {
  return {
    market: "us",
    generatedAt: payload.generated_at,
    dateFrom: payload.date_from,
    dateTo: payload.date_to,
    resultCount: payload.result_count,
    warning: payload.warning,
    sources: Object.fromEntries(
      Object.entries(payload.sources).map(([key, source]) => [
        key,
        {
          source: source.source,
          status: source.status,
          freshness: source.freshness,
          coverage: source.coverage,
          warning: source.warning,
        },
      ])
    ),
    results: payload.results.map(normalizeUsEvent),
  };
}

export default function MarketCalendarDialog({
  open,
  onClose,
}: MarketCalendarDialogProps) {
  const t = useT();
  const { locale } = useI18n();
  const [activeMarket, setActiveMarket] = useState<CalendarMarket>("tw");
  const [payload, setPayload] = useState<CalendarPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [filter, setFilter] = useState<EventFilter>("all");
  const [query, setQuery] = useState("");

  const publishCalendarStatus = useCallback(({
    level,
    title,
    message,
    market,
  }: {
    level: DataStatusLevel;
    title: string;
    message: string;
    market: "tw" | "us";
  }) => {
    emitDataStatusEvent({
      market,
      level,
      title,
      message,
      source: t(
        market === "tw"
          ? "settings.calendar.status.source"
          : "settings.calendar.status.usSource"
      ),
      contextKey: `${market}:corporate-events`,
      contextLabel: t("settings.calendar.title"),
      dedupeKey: `${market}:corporate-events:calendar-load`,
    });
  }, [t]);

  const loadCalendar = useCallback(async (signal?: AbortSignal) => {
    if (activeMarket !== "tw" && activeMarket !== "us") return;

    const market = activeMarket;
    setLoading(true);
    setErrorMessage(null);
    try {
      const nextPayload = market === "tw"
        ? normalizeTaiwanPayload(
            await fetchJson<TaiwanCorporateEventListRead>(
              "/api/market/tw-corporate-events",
              { limit: 1000 },
              { signal }
            )
          )
        : normalizeUsPayload(
            await fetchJson<USCorporateEventListRead>(
              "/api/us-market/corporate-events",
              { limit: 1000 },
              { signal }
            )
          );
      setPayload(nextPayload);
      if (nextPayload.warning) {
        publishCalendarStatus({
          market,
          level: "warning",
          title: t("settings.calendar.status.warningTitle"),
          message: nextPayload.warning,
        });
      } else {
        publishCalendarStatus({
          market,
          level: "success",
          title: t("settings.calendar.status.successTitle"),
          message: t("settings.calendar.status.successMessage", {
            count: nextPayload.resultCount,
          }),
        });
      }
    } catch (error) {
      if (signal?.aborted) return;
      const message =
        error instanceof Error ? error.message : t("settings.calendar.loadError");
      setErrorMessage(message);
      publishCalendarStatus({
        market,
        level: "error",
        title: t("settings.calendar.loadError"),
        message,
      });
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [activeMarket, publishCalendarStatus, t]);

  useEffect(() => {
    if (!open || (activeMarket !== "tw" && activeMarket !== "us")) return;
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => {
      void loadCalendar(controller.signal);
    }, 0);
    return () => {
      window.clearTimeout(timeoutId);
      controller.abort();
    };
  }, [activeMarket, loadCalendar, open]);

  const handleMarketChange = (market: CalendarMarket) => {
    const option = marketOptions.find((item) => item.key === market);
    if (!option?.enabled || market === activeMarket) return;
    setActiveMarket(market);
    setPayload(null);
    setErrorMessage(null);
    setFilter("all");
  };

  const enabledMarket = activeMarket === "us" ? "us" : "tw";
  const eventFilters = filtersByMarket[enabledMarket];
  const filteredEvents = useMemo(() => {
    const normalizedQuery = query.trim().toLocaleLowerCase(locale);
    return (payload?.results ?? []).filter((event) => {
      if (filter !== "all" && event.eventType !== filter) return false;
      if (!normalizedQuery) return true;
      return [
        event.symbol,
        event.companyName,
        event.title,
        event.summary,
        event.location,
      ].some((value) => value?.toLocaleLowerCase(locale).includes(normalizedQuery));
    });
  }, [filter, locale, payload?.results, query]);

  const groupedEvents = useMemo(() => {
    const groups = new Map<string, CalendarEvent[]>();
    filteredEvents.forEach((event) => {
      const current = groups.get(event.eventDate) ?? [];
      current.push(event);
      groups.set(event.eventDate, current);
    });
    return Array.from(groups.entries());
  }, [filteredEvents]);

  if (!open) return null;

  const dateFormatter = new Intl.DateTimeFormat(locale, {
    month: "short",
    day: "numeric",
    weekday: "short",
    timeZone: marketTimezones[enabledMarket],
  });
  const fullDateFormatter = new Intl.DateTimeFormat(locale, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });

  return (
    <div
      className="fixed inset-0 z-[2147483646] flex items-center justify-center bg-black/60 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="market-calendar-title"
    >
      <section className="flex h-[760px] max-h-[calc(100vh-2rem)] w-[1080px] max-w-[calc(100vw-2rem)] flex-col overflow-hidden border border-omi-control-border bg-omi-surface shadow-2xl">
        <header className="flex shrink-0 items-start justify-between gap-4 border-b border-omi-border-subtle px-5 py-4">
          <div className="min-w-0">
            <div className="text-xs font-bold uppercase tracking-[0.22em] text-omi-accent">
              Corporate Events
            </div>
            <h2 id="market-calendar-title" className="mt-1 text-xl font-black text-omi-text-strong">
              {t("settings.calendar.title")}
            </h2>
            <p className="mt-2 max-w-[760px] text-sm leading-6 text-omi-text-muted">
              {t("settings.calendar.description")}
            </p>
          </div>
          <button
            type="button"
            aria-label={t("settings.calendar.close")}
            className="grid h-8 w-8 shrink-0 place-items-center border border-omi-border text-xl text-omi-text-muted hover:border-omi-control hover:text-omi-text-strong"
            onClick={onClose}
          >
            ×
          </button>
        </header>

        <div className="shrink-0 border-b border-omi-border-subtle bg-omi-surface-subtle px-5 py-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="mr-1 text-xs font-bold uppercase tracking-[0.16em] text-omi-text-muted">
              {t("settings.calendar.marketLabel")}
            </span>
            {marketOptions.map((market) => (
              <button
                key={market.key}
                type="button"
                data-testid={`calendar-market-${market.key}`}
                aria-pressed={activeMarket === market.key}
                disabled={!market.enabled}
                title={!market.enabled ? t("settings.calendar.plannedHint") : undefined}
                className={[
                  "h-8 border px-3 text-xs font-bold",
                  activeMarket === market.key
                    ? "border-omi-accent bg-omi-accent-soft text-omi-accent"
                    : "border-omi-border bg-omi-surface text-omi-text-muted",
                  market.enabled
                    ? "hover:border-omi-control hover:text-omi-text"
                    : "cursor-not-allowed opacity-55",
                ].join(" ")}
                onClick={() => handleMarketChange(market.key)}
              >
                {t(`settings.calendar.markets.${market.key}`)}
                {!market.enabled ? (
                  <span className="ml-1 font-medium">
                    · {t("settings.calendar.planned")}
                  </span>
                ) : null}
              </button>
            ))}
          </div>

          <div className="mt-3 flex flex-wrap items-center gap-2">
            {eventFilters.map((eventFilter) => (
              <button
                key={eventFilter}
                type="button"
                className={[
                  "h-8 border px-3 text-xs font-bold",
                  filter === eventFilter
                    ? "border-omi-accent bg-omi-accent-soft text-omi-accent"
                    : "border-omi-border bg-omi-surface text-omi-text-muted hover:text-omi-text",
                ].join(" ")}
                onClick={() => setFilter(eventFilter)}
              >
                {t(`settings.calendar.filters.${eventFilter}`)}
              </button>
            ))}
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={t("settings.calendar.searchPlaceholder")}
              className="ml-auto h-8 min-w-[220px] border border-omi-border bg-omi-surface px-3 text-sm text-omi-text outline-none focus:border-omi-accent"
            />
            <button
              type="button"
              className="h-8 border border-omi-border bg-omi-surface px-3 text-xs font-bold text-omi-text hover:border-omi-control"
              onClick={() => void loadCalendar()}
              disabled={loading}
            >
              {loading ? t("settings.calendar.loading") : t("settings.calendar.reload")}
            </button>
          </div>

          {payload ? (
            <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-omi-text-muted">
              <span>
                {t("settings.calendar.range", {
                  from: payload.dateFrom,
                  to: payload.dateTo,
                })}
              </span>
              <span>{t("settings.calendar.count", { count: filteredEvents.length })}</span>
              {Object.entries(payload.sources).map(([key, source]) => (
                <span
                  key={key}
                  className={sourceTone(source.status, source.freshness)}
                  title={[source.coverage, source.warning].filter(Boolean).join("\n") || undefined}
                >
                  {source.source} · {t(`settings.calendar.sourceStatus.${source.status}`)}
                  {source.freshness && source.freshness !== source.status
                    ? ` / ${t(`settings.calendar.sourceStatus.${source.freshness}`)}`
                    : ""}
                </span>
              ))}
            </div>
          ) : null}
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-5">
          {errorMessage && !payload ? (
            <div className="border border-dashed border-omi-border px-5 py-12 text-center text-sm text-omi-text-muted">
              <div>{t("settings.calendar.unavailableWithStatus")}</div>
              <button
                type="button"
                className="mt-3 h-8 border border-omi-border bg-omi-surface px-3 text-xs font-bold text-omi-text hover:border-omi-control"
                onClick={() => void loadCalendar()}
                disabled={loading}
              >
                {loading ? t("settings.calendar.loading") : t("settings.calendar.reload")}
              </button>
            </div>
          ) : loading && !payload ? (
            <div className="space-y-3">
              {Array.from({ length: 5 }).map((_, index) => (
                <div key={index} className="omi-skeleton h-24 w-full" />
              ))}
            </div>
          ) : groupedEvents.length === 0 ? (
            <div className="border border-dashed border-omi-border px-5 py-12 text-center text-sm text-omi-text-muted">
              {t("settings.calendar.empty")}
            </div>
          ) : (
            <div className="space-y-6">
              {groupedEvents.map(([eventDate, events]) => (
                <section key={eventDate} className="grid gap-3 md:grid-cols-[130px_minmax(0,1fr)]">
                  <div>
                    <div className="text-lg font-black text-omi-text-strong">
                      {dateFormatter.format(new Date(`${eventDate}T12:00:00Z`))}
                    </div>
                    <div className="mt-1 text-xs text-omi-text-muted">{eventDate}</div>
                  </div>
                  <div className="space-y-2">
                    {events.map((event) => (
                      <article
                        key={event.eventId}
                        className="border border-omi-border-subtle bg-omi-surface-subtle px-4 py-3"
                      >
                        <div className="flex flex-wrap items-start justify-between gap-3">
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="font-black text-omi-text-strong">
                                {event.symbol} {event.companyName ?? ""}
                              </span>
                              <span className={`border px-2 py-0.5 text-[11px] font-bold ${eventTone(event.eventType)}`}>
                                {t(`settings.calendar.eventTypes.${event.eventType}`)}
                              </span>
                              {event.status === "ongoing" ? (
                                <span className="border border-omi-accent-border bg-omi-accent-soft px-2 py-0.5 text-[11px] font-bold text-omi-accent">
                                  {t(`settings.calendar.eventStatus.${event.status}`)}
                                </span>
                              ) : null}
                            </div>
                            <h3 className="mt-2 text-sm font-bold text-omi-text">{event.title}</h3>
                            {event.summary ? (
                              <p className="mt-1 text-sm leading-6 text-omi-text-muted">{event.summary}</p>
                            ) : null}
                            <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-omi-text-muted">
                              {event.eventTime ? <span>{event.eventTime}</span> : null}
                              {event.location ? <span>{event.location}</span> : null}
                              {event.cashDividend !== null ? (
                                <span>{t("settings.calendar.cashDividend", { amount: event.cashDividend })}</span>
                              ) : null}
                              {event.stockDividendRatio !== null && event.stockDividendRatio !== 0 ? (
                                <span>{t("settings.calendar.stockDividend", { ratio: event.stockDividendRatio })}</span>
                              ) : null}
                              {event.dividendAmount !== null ? (
                                <span>
                                  {t("settings.calendar.usDividend", {
                                    amount: event.dividendAmount,
                                    currency: event.dividendCurrency ?? "USD",
                                  })}
                                </span>
                              ) : null}
                              {event.splitRatio !== null ? (
                                <span>{t("settings.calendar.splitRatio", { ratio: event.splitRatio })}</span>
                              ) : null}
                              {event.estimatedEps !== null ? (
                                <span>{t("settings.calendar.estimatedEps", { value: event.estimatedEps })}</span>
                              ) : null}
                              {event.fiscalPeriodEnd ? (
                                <span>{t("settings.calendar.fiscalPeriodEnd", { date: event.fiscalPeriodEnd })}</span>
                              ) : null}
                            </div>
                          </div>
                          <div className="flex shrink-0 gap-2 text-xs">
                            {event.companyUrl ? (
                              <a className="text-omi-accent hover:underline" href={event.companyUrl} target="_blank" rel="noreferrer">
                                {t("settings.calendar.companyLink")}
                              </a>
                            ) : null}
                            {event.videoUrl ? (
                              <a className="text-omi-accent hover:underline" href={event.videoUrl} target="_blank" rel="noreferrer">
                                {t("settings.calendar.videoLink")}
                              </a>
                            ) : null}
                            {event.sourceUrl ? (
                              <a className="text-omi-accent hover:underline" href={event.sourceUrl} target="_blank" rel="noreferrer">
                                {t("settings.calendar.sourceLink")}
                              </a>
                            ) : (
                              <span className="text-omi-text-subtle">{event.sourceName}</span>
                            )}
                          </div>
                        </div>
                      </article>
                    ))}
                  </div>
                </section>
              ))}
            </div>
          )}
        </div>

        <footer className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-t border-omi-border-subtle bg-omi-surface-subtle px-5 py-3 text-xs text-omi-text-muted">
          <span>
            {t(
              payload?.market === "us"
                ? "settings.calendar.footerUs"
                : "settings.calendar.footer"
            )}
          </span>
          {payload ? (
            <span>
              {t("settings.calendar.updatedAt", {
                time: fullDateFormatter.format(new Date(payload.generatedAt)),
              })}
            </span>
          ) : null}
        </footer>
      </section>
    </div>
  );
}
