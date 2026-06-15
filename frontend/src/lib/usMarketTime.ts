import {
  getMarketCalendarStatusSnapshot,
  msUntilIsoTime,
} from "@/lib/marketCalendarStatus";

export const US_INTRADAY_REFRESH_MS = 5_000;
export const US_SESSION_START_MINUTES = 9 * 60 + 30;
export const US_SESSION_END_MINUTES = 16 * 60;

type NewYorkParts = {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
  second: number;
};

const newYorkFormatter = new Intl.DateTimeFormat("en-CA", {
  timeZone: "America/New_York",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

function getNewYorkParts(value: Date): NewYorkParts {
  const parts = Object.fromEntries(
    newYorkFormatter.formatToParts(value).map((part) => [part.type, part.value])
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

function newYorkDateKey(parts: Pick<NewYorkParts, "year" | "month" | "day">) {
  return `${parts.year}-${String(parts.month).padStart(2, "0")}-${String(parts.day).padStart(2, "0")}`;
}

function newYorkBoundaryToUtcMs(
  year: number,
  month: number,
  day: number,
  hour: number,
  minute: number
) {
  const targetLocalMs = Date.UTC(year, month - 1, day, hour, minute, 0, 0);
  let utcMs = Date.UTC(year, month - 1, day, hour + 5, minute, 0, 0);

  for (let index = 0; index < 3; index += 1) {
    const parts = getNewYorkParts(new Date(utcMs));
    const actualLocalMs = Date.UTC(
      parts.year,
      parts.month - 1,
      parts.day,
      parts.hour,
      parts.minute,
      parts.second,
      0
    );

    utcMs += targetLocalMs - actualLocalMs;
  }

  return utcMs;
}

function isUsWeekday(parts: Pick<NewYorkParts, "year" | "month" | "day">) {
  const weekday = new Date(Date.UTC(parts.year, parts.month - 1, parts.day, 17)).getUTCDay();
  return weekday >= 1 && weekday <= 5;
}

function addNewYorkDays(parts: NewYorkParts, days: number) {
  const value = new Date(Date.UTC(parts.year, parts.month - 1, parts.day + days, 17));

  return {
    year: value.getUTCFullYear(),
    month: value.getUTCMonth() + 1,
    day: value.getUTCDate(),
  };
}

function nextUsWeekday(parts: NewYorkParts) {
  for (let offset = 1; offset <= 7; offset += 1) {
    const candidate = addNewYorkDays(parts, offset);

    if (isUsWeekday(candidate)) {
      return candidate;
    }
  }

  return addNewYorkDays(parts, 1);
}

export function getNewYorkDateKey(value = new Date()) {
  return newYorkDateKey(getNewYorkParts(value));
}

export function getNewYorkMinutesOfDay(value: string | Date) {
  const date = typeof value === "string" ? new Date(value) : value;

  if (Number.isNaN(date.getTime())) return null;

  const parts = getNewYorkParts(date);
  return parts.hour * 60 + parts.minute + parts.second / 60;
}

export function getUsMarketRefreshState(now = new Date()) {
  const parts = getNewYorkParts(now);
  const dateKey = newYorkDateKey(parts);
  const calendarStatus = getMarketCalendarStatusSnapshot("us");

  if (calendarStatus?.date === dateKey) {
    const nextPollingMs =
      msUntilIsoTime(calendarStatus.session.next_session_start_at, now) ?? 60_000;

    return {
      dateKey,
      isPollingWindow: calendarStatus.session.is_polling_window,
      isAfterClose: calendarStatus.session.is_after_close,
      msUntilNextPollingStart: nextPollingMs,
    };
  }

  const isTradingDay = isUsWeekday(parts);
  const nowMs = now.getTime();
  const openMs = newYorkBoundaryToUtcMs(parts.year, parts.month, parts.day, 9, 30);
  const closeMs = newYorkBoundaryToUtcMs(parts.year, parts.month, parts.day, 16, 0);
  const nextWeekday = nextUsWeekday(parts);
  const nextOpenMs = newYorkBoundaryToUtcMs(
    nextWeekday.year,
    nextWeekday.month,
    nextWeekday.day,
    9,
    30
  );
  const isPollingWindow = isTradingDay && nowMs >= openMs && nowMs < closeMs;
  const isAfterClose = isTradingDay && nowMs >= closeMs;
  const nextPollingStartMs = isTradingDay && nowMs < openMs ? openMs : nextOpenMs;

  return {
    dateKey,
    isPollingWindow,
    isAfterClose,
    msUntilNextPollingStart: Math.max(1_000, nextPollingStartMs - nowMs),
  };
}

export function getUsIntradayXRatio(value: string | Date) {
  const minutes = getNewYorkMinutesOfDay(value);

  if (minutes === null) return 0;

  const ratio =
    (minutes - US_SESSION_START_MINUTES) /
    (US_SESSION_END_MINUTES - US_SESSION_START_MINUTES);

  return Math.max(0, Math.min(1, ratio));
}

export function isUsRegularSessionPoint(value: string | Date) {
  const minutes = getNewYorkMinutesOfDay(value);

  return (
    minutes !== null &&
    minutes >= US_SESSION_START_MINUTES &&
    minutes <= US_SESSION_END_MINUTES
  );
}
