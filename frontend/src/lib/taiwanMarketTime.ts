export const TAIWAN_INTRADAY_REFRESH_MS = 5_000;
export const TAIWAN_PREOPEN_MINUTES = 8 * 60 + 30;
export const TAIWAN_SESSION_START_MINUTES = 9 * 60;
export const TAIWAN_SESSION_END_MINUTES = 13 * 60 + 30;

type TaipeiParts = {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
  second: number;
};

const taipeiFormatter = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Taipei",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

function getTaipeiParts(value: Date): TaipeiParts {
  const parts = Object.fromEntries(
    taipeiFormatter.formatToParts(value).map((part) => [part.type, part.value])
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

function taipeiBoundaryToUtcMs(
  year: number,
  month: number,
  day: number,
  hour: number,
  minute: number
) {
  return Date.UTC(year, month - 1, day, hour - 8, minute, 0, 0);
}

function taipeiWeekday(year: number, month: number, day: number) {
  return new Date(Date.UTC(year, month - 1, day, 4, 0, 0, 0)).getUTCDay();
}

function isTaiwanWeekday(year: number, month: number, day: number) {
  const weekday = taipeiWeekday(year, month, day);
  return weekday >= 1 && weekday <= 5;
}

function addTaipeiDays(parts: TaipeiParts, days: number) {
  const value = new Date(Date.UTC(parts.year, parts.month - 1, parts.day + days, 4));
  return {
    year: value.getUTCFullYear(),
    month: value.getUTCMonth() + 1,
    day: value.getUTCDate(),
  };
}

function nextTaiwanWeekday(parts: TaipeiParts) {
  for (let offset = 1; offset <= 7; offset += 1) {
    const candidate = addTaipeiDays(parts, offset);

    if (isTaiwanWeekday(candidate.year, candidate.month, candidate.day)) {
      return candidate;
    }
  }

  return addTaipeiDays(parts, 1);
}

export function getTaipeiDateKey(value = new Date()) {
  const parts = getTaipeiParts(value);
  const month = String(parts.month).padStart(2, "0");
  const day = String(parts.day).padStart(2, "0");

  return `${parts.year}-${month}-${day}`;
}

export function getTaipeiMinutesOfDay(value: string | Date) {
  const date = typeof value === "string" ? new Date(value) : value;

  if (Number.isNaN(date.getTime())) return null;

  const parts = getTaipeiParts(date);
  return parts.hour * 60 + parts.minute + parts.second / 60;
}

export function getTaiwanMarketRefreshState(now = new Date()) {
  const parts = getTaipeiParts(now);
  const dateKey = getTaipeiDateKey(now);
  const isWeekday = isTaiwanWeekday(parts.year, parts.month, parts.day);
  const nowMs = now.getTime();
  const preopenMs = taipeiBoundaryToUtcMs(parts.year, parts.month, parts.day, 8, 30);
  const closeMs = taipeiBoundaryToUtcMs(parts.year, parts.month, parts.day, 13, 30);
  const nextWeekday = nextTaiwanWeekday(parts);
  const nextPreopenMs = taipeiBoundaryToUtcMs(
    nextWeekday.year,
    nextWeekday.month,
    nextWeekday.day,
    8,
    30
  );
  const isPollingWindow = isWeekday && nowMs >= preopenMs && nowMs < closeMs;
  const isAfterClose = isWeekday && nowMs >= closeMs;
  const nextPollingStartMs =
    isWeekday && nowMs < preopenMs ? preopenMs : nextPreopenMs;

  return {
    dateKey,
    isPollingWindow,
    isAfterClose,
    msUntilNextPollingStart: Math.max(1_000, nextPollingStartMs - nowMs),
  };
}

export function getTaiwanIntradayXRatio(value: string | Date) {
  const minutes = getTaipeiMinutesOfDay(value);

  if (minutes === null) return 0;

  const ratio =
    (minutes - TAIWAN_SESSION_START_MINUTES) /
    (TAIWAN_SESSION_END_MINUTES - TAIWAN_SESSION_START_MINUTES);

  return Math.max(0, Math.min(1, ratio));
}

export function isTaiwanRegularSessionPoint(value: string | Date) {
  const minutes = getTaipeiMinutesOfDay(value);

  return (
    minutes !== null &&
    minutes >= TAIWAN_SESSION_START_MINUTES &&
    minutes <= TAIWAN_SESSION_END_MINUTES
  );
}
