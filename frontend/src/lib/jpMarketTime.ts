export const JAPAN_INTRADAY_REFRESH_MS = 70_000;
export const JAPAN_SESSION_START_MINUTES = 9 * 60;
export const JAPAN_LUNCH_START_MINUTES = 11 * 60 + 30;
export const JAPAN_LUNCH_END_MINUTES = 12 * 60 + 30;
export const JAPAN_SESSION_END_MINUTES = 15 * 60 + 30;

type TokyoParts = {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
  second: number;
};

const tokyoFormatter = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Tokyo",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

function getTokyoParts(value: Date): TokyoParts {
  const parts = Object.fromEntries(
    tokyoFormatter.formatToParts(value).map((part) => [part.type, part.value])
  );

  return {
    year: Number(parts.year),
    month: Number(parts.month),
    day: Number(parts.day),
    hour: Number(parts.hour),
    minute: Number(parts.minute),
    second: Number(parts.second),
  };
}

function tokyoDateKey(parts: Pick<TokyoParts, "year" | "month" | "day">) {
  return `${parts.year}-${String(parts.month).padStart(2, "0")}-${String(parts.day).padStart(2, "0")}`;
}

function tokyoBoundaryToUtcMs(
  year: number,
  month: number,
  day: number,
  hour: number,
  minute: number
) {
  return Date.UTC(year, month - 1, day, hour - 9, minute, 0, 0);
}

function isJapanWeekday(parts: Pick<TokyoParts, "year" | "month" | "day">) {
  const weekday = new Date(Date.UTC(parts.year, parts.month - 1, parts.day, 6)).getUTCDay();
  return weekday >= 1 && weekday <= 5;
}

function addTokyoDays(parts: TokyoParts, days: number) {
  const value = new Date(Date.UTC(parts.year, parts.month - 1, parts.day + days, 6));

  return {
    year: value.getUTCFullYear(),
    month: value.getUTCMonth() + 1,
    day: value.getUTCDate(),
  };
}

function nextJapanWeekday(parts: TokyoParts) {
  for (let offset = 1; offset <= 7; offset += 1) {
    const candidate = addTokyoDays(parts, offset);

    if (isJapanWeekday(candidate)) {
      return candidate;
    }
  }

  return addTokyoDays(parts, 1);
}

export function getTokyoDateKey(value = new Date()) {
  return tokyoDateKey(getTokyoParts(value));
}

export function getTokyoMinutesOfDay(value: string | Date) {
  const date = typeof value === "string" ? new Date(value) : value;

  if (Number.isNaN(date.getTime())) return null;

  const parts = getTokyoParts(date);
  return parts.hour * 60 + parts.minute + parts.second / 60;
}

export function getJapanMarketRefreshState(now = new Date()) {
  const parts = getTokyoParts(now);
  const dateKey = tokyoDateKey(parts);
  const calendarSnapshot = getMarketCalendarStatusSnapshot("jp");
  const snapshotMatchesDate = calendarSnapshot?.date === dateKey;
  const snapshotNextStartMs = snapshotMatchesDate
    ? Date.parse(calendarSnapshot.session.next_session_start_at)
    : Number.NaN;
  const snapshotLunchEndMs = tokyoBoundaryToUtcMs(
    parts.year,
    parts.month,
    parts.day,
    12,
    30
  );

  if (calendarSnapshot && snapshotMatchesDate) {
    const nextPollingStartMs =
      calendarSnapshot.phase === "lunch_break"
        ? snapshotLunchEndMs
        : Number.isFinite(snapshotNextStartMs)
          ? snapshotNextStartMs
          : now.getTime() + 60_000;

    return {
      dateKey,
      sessionPhase: calendarSnapshot.phase,
      isPollingWindow: calendarSnapshot.session.is_polling_window,
      isAfterClose: calendarSnapshot.session.is_after_close,
      msUntilNextPollingStart: Math.max(1_000, nextPollingStartMs - now.getTime()),
      calendarSource: calendarSnapshot.calendar_source ?? null,
      calendarLimit: calendarSnapshot.calendar_limit ?? null,
    };
  }

  const isTradingDay = isJapanWeekday(parts);
  const nowMs = now.getTime();
  const openMs = tokyoBoundaryToUtcMs(parts.year, parts.month, parts.day, 9, 0);
  const closeMs = tokyoBoundaryToUtcMs(parts.year, parts.month, parts.day, 15, 30);
  const nextWeekday = nextJapanWeekday(parts);
  const nextOpenMs = tokyoBoundaryToUtcMs(
    nextWeekday.year,
    nextWeekday.month,
    nextWeekday.day,
    9,
    0
  );
  const isPollingWindow = isTradingDay && nowMs >= openMs && nowMs < closeMs;
  const isAfterClose = isTradingDay && nowMs >= closeMs;
  const nextPollingStartMs = isTradingDay && nowMs < openMs ? openMs : nextOpenMs;
  const sessionPhase = !isTradingDay
    ? "market_closed"
    : nowMs < openMs
      ? "pre_market_pending"
      : isPollingWindow
        ? "regular"
        : "post_close";

  return {
    dateKey,
    sessionPhase,
    isPollingWindow,
    isAfterClose,
    msUntilNextPollingStart: Math.max(1_000, nextPollingStartMs - nowMs),
    calendarSource: null,
    calendarLimit: "weekday_fallback",
  };
}

export function getJapanIntradayXRatio(value: string | Date) {
  const minutes = getTokyoMinutesOfDay(value);

  if (minutes === null) return 0;

  const ratio =
    (minutes - JAPAN_SESSION_START_MINUTES) /
    (JAPAN_SESSION_END_MINUTES - JAPAN_SESSION_START_MINUTES);

  return Math.max(0, Math.min(1, ratio));
}

export function isJapanRegularSessionPoint(value: string | Date) {
  const minutes = getTokyoMinutesOfDay(value);

  return (
    minutes !== null &&
    minutes >= JAPAN_SESSION_START_MINUTES &&
    minutes <= JAPAN_SESSION_END_MINUTES &&
    (minutes <= JAPAN_LUNCH_START_MINUTES || minutes >= JAPAN_LUNCH_END_MINUTES)
  );
}
import { getMarketCalendarStatusSnapshot } from "@/lib/marketCalendarStatus";
