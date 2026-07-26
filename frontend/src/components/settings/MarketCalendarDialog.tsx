"use client";

import { useI18n, useT } from "@/i18n";
import { fetchJson } from "@/lib/api";
import { emitDataStatusEvent, type DataStatusLevel } from "@/lib/dataStatusEvents";
import type {
  TaiwanCorporateEventListRead,
  TaiwanCorporateEventRead,
} from "@/types/market";
import { useCallback, useEffect, useMemo, useState } from "react";


type MarketCalendarDialogProps = {
  open: boolean;
  onClose: () => void;
};

type EventFilter = "all" | "ex_dividend" | "financial_report" | "investor_conference";

const eventFilters: EventFilter[] = [
  "all",
  "ex_dividend",
  "financial_report",
  "investor_conference",
];

function eventTone(eventType: string) {
  if (eventType === "ex_dividend") {
    return "border-omi-success bg-omi-success-soft text-omi-success-strong";
  }
  if (eventType === "financial_report") {
    return "border-omi-warning bg-omi-warning-soft text-omi-warning-strong";
  }
  return "border-omi-info bg-omi-info-soft text-omi-info-strong";
}

function sourceTone(status: string) {
  if (status === "current") return "text-omi-market-up";
  if (status === "stale" || status === "degraded") return "text-omi-warning";
  return "text-omi-danger";
}

export default function MarketCalendarDialog({
  open,
  onClose,
}: MarketCalendarDialogProps) {
  const t = useT();
  const { locale } = useI18n();
  const [payload, setPayload] = useState<TaiwanCorporateEventListRead | null>(null);
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [filter, setFilter] = useState<EventFilter>("all");
  const [query, setQuery] = useState("");

  const publishCalendarStatus = useCallback(({
    level,
    title,
    message,
  }: {
    level: DataStatusLevel;
    title: string;
    message: string;
  }) => {
    emitDataStatusEvent({
      market: "tw",
      level,
      title,
      message,
      source: t("settings.calendar.status.source"),
      contextKey: "tw:corporate-events",
      contextLabel: t("settings.calendar.title"),
      dedupeKey: "tw:corporate-events:calendar-load",
    });
  }, [t]);

  const loadCalendar = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setErrorMessage(null);
    try {
      const nextPayload = await fetchJson<TaiwanCorporateEventListRead>(
        "/api/market/tw-corporate-events",
        { limit: 1000 },
        { signal }
      );
      setPayload(nextPayload);
      if (nextPayload.warning) {
        publishCalendarStatus({
          level: "warning",
          title: t("settings.calendar.status.warningTitle"),
          message: nextPayload.warning,
        });
      } else {
        publishCalendarStatus({
          level: "success",
          title: t("settings.calendar.status.successTitle"),
          message: t("settings.calendar.status.successMessage", {
            count: nextPayload.result_count,
          }),
        });
      }
    } catch (error) {
      if (signal?.aborted) return;
      const message = error instanceof Error ? error.message : t("settings.calendar.loadError");
      setErrorMessage(message);
      publishCalendarStatus({
        level: "error",
        title: t("settings.calendar.loadError"),
        message,
      });
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [publishCalendarStatus, t]);

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => {
      void loadCalendar(controller.signal);
    }, 0);
    return () => {
      window.clearTimeout(timeoutId);
      controller.abort();
    };
  }, [loadCalendar, open]);

  const filteredEvents = useMemo(() => {
    const normalizedQuery = query.trim().toLocaleLowerCase(locale);
    return (payload?.results ?? []).filter((event) => {
      if (filter !== "all" && event.event_type !== filter) return false;
      if (!normalizedQuery) return true;
      return [
        event.stock_id,
        event.stock_name,
        event.title,
        event.summary,
        event.location,
      ].some((value) => value?.toLocaleLowerCase(locale).includes(normalizedQuery));
    });
  }, [filter, locale, payload?.results, query]);

  const groupedEvents = useMemo(() => {
    const groups = new Map<string, TaiwanCorporateEventRead[]>();
    filteredEvents.forEach((event) => {
      const current = groups.get(event.start_date) ?? [];
      current.push(event);
      groups.set(event.start_date, current);
    });
    return Array.from(groups.entries());
  }, [filteredEvents]);

  if (!open) return null;

  const dateFormatter = new Intl.DateTimeFormat(locale, {
    month: "short",
    day: "numeric",
    weekday: "short",
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
                  from: payload.date_from,
                  to: payload.date_to,
                })}
              </span>
              <span>{t("settings.calendar.count", { count: filteredEvents.length })}</span>
              {Object.entries(payload.sources).map(([key, source]) => (
                <span key={key} className={sourceTone(source.status)} title={source.warning ?? undefined}>
                  {source.source} · {t(`settings.calendar.sourceStatus.${source.status}`)}
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
                      {dateFormatter.format(new Date(`${eventDate}T00:00:00+08:00`))}
                    </div>
                    <div className="mt-1 text-xs text-omi-text-muted">{eventDate}</div>
                  </div>
                  <div className="space-y-2">
                    {events.map((event) => (
                      <article key={event.event_id} className="border border-omi-border-subtle bg-omi-surface-subtle px-4 py-3">
                        <div className="flex flex-wrap items-start justify-between gap-3">
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="font-black text-omi-text-strong">
                                {event.stock_id} {event.stock_name ?? ""}
                              </span>
                              <span className={`border px-2 py-0.5 text-[11px] font-bold ${eventTone(event.event_type)}`}>
                                {t(`settings.calendar.eventTypes.${event.event_type}`)}
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
                              {event.start_time ? <span>{event.start_time}</span> : null}
                              {event.location ? <span>{event.location}</span> : null}
                              {event.cash_dividend !== null ? (
                                <span>{t("settings.calendar.cashDividend", { amount: event.cash_dividend })}</span>
                              ) : null}
                              {event.stock_dividend_ratio !== null && event.stock_dividend_ratio !== 0 ? (
                                <span>{t("settings.calendar.stockDividend", { ratio: event.stock_dividend_ratio })}</span>
                              ) : null}
                            </div>
                          </div>
                          <div className="flex shrink-0 gap-2 text-xs">
                            {event.company_url ? (
                              <a className="text-omi-accent hover:underline" href={event.company_url} target="_blank" rel="noreferrer">
                                {t("settings.calendar.companyLink")}
                              </a>
                            ) : null}
                            {event.video_url ? (
                              <a className="text-omi-accent hover:underline" href={event.video_url} target="_blank" rel="noreferrer">
                                {t("settings.calendar.videoLink")}
                              </a>
                            ) : null}
                            <a className="text-omi-accent hover:underline" href={event.source_url} target="_blank" rel="noreferrer">
                              {t("settings.calendar.sourceLink")}
                            </a>
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
          <span>{t("settings.calendar.footer")}</span>
          {payload ? (
            <span>
              {t("settings.calendar.updatedAt", {
                time: fullDateFormatter.format(new Date(payload.generated_at)),
              })}
            </span>
          ) : null}
        </footer>
      </section>
    </div>
  );
}
