export const KOREA_INTRADAY_REFRESH_MS = 70_000;
export const KOREA_SESSION_START_MINUTES = 9 * 60;
export const KOREA_SESSION_END_MINUTES = 15 * 60 + 30;

type SeoulParts = {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
  second: number;
};

const seoulFormatter = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Seoul",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

function getSeoulParts(value: Date): SeoulParts {
  const parts = Object.fromEntries(
    seoulFormatter.formatToParts(value).map((part) => [part.type, part.value])
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

function seoulDateKey(parts: Pick<SeoulParts, "year" | "month" | "day">) {
  return `${parts.year}-${String(parts.month).padStart(2, "0")}-${String(parts.day).padStart(2, "0")}`;
}

function seoulBoundaryToUtcMs(
  year: number,
  month: number,
  day: number,
  hour: number,
  minute: number
) {
  return Date.UTC(year, month - 1, day, hour - 9, minute, 0, 0);
}

function isKoreaWeekday(parts: Pick<SeoulParts, "year" | "month" | "day">) {
  const weekday = new Date(Date.UTC(parts.year, parts.month - 1, parts.day, 6)).getUTCDay();
  return weekday >= 1 && weekday <= 5;
}

function addSeoulDays(parts: SeoulParts, days: number) {
  const value = new Date(Date.UTC(parts.year, parts.month - 1, parts.day + days, 6));

  return {
    year: value.getUTCFullYear(),
    month: value.getUTCMonth() + 1,
    day: value.getUTCDate(),
  };
}

function nextKoreaWeekday(parts: SeoulParts) {
  for (let offset = 1; offset <= 7; offset += 1) {
    const candidate = addSeoulDays(parts, offset);

    if (isKoreaWeekday(candidate)) {
      return candidate;
    }
  }

  return addSeoulDays(parts, 1);
}

export function getSeoulDateKey(value = new Date()) {
  return seoulDateKey(getSeoulParts(value));
}

export function getSeoulMinutesOfDay(value: string | Date) {
  const date = typeof value === "string" ? new Date(value) : value;

  if (Number.isNaN(date.getTime())) return null;

  const parts = getSeoulParts(date);
  return parts.hour * 60 + parts.minute + parts.second / 60;
}

export function getKoreaMarketRefreshState(now = new Date()) {
  const parts = getSeoulParts(now);
  const dateKey = seoulDateKey(parts);
  const isTradingDay = isKoreaWeekday(parts);
  const nowMs = now.getTime();
  const openMs = seoulBoundaryToUtcMs(parts.year, parts.month, parts.day, 9, 0);
  const closeMs = seoulBoundaryToUtcMs(parts.year, parts.month, parts.day, 15, 30);
  const nextWeekday = nextKoreaWeekday(parts);
  const nextOpenMs = seoulBoundaryToUtcMs(
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
  };
}

export function getKoreaIntradayXRatio(value: string | Date) {
  const minutes = getSeoulMinutesOfDay(value);

  if (minutes === null) return 0;

  const ratio =
    (minutes - KOREA_SESSION_START_MINUTES) /
    (KOREA_SESSION_END_MINUTES - KOREA_SESSION_START_MINUTES);

  return Math.max(0, Math.min(1, ratio));
}

export function isKoreaRegularSessionPoint(value: string | Date) {
  const minutes = getSeoulMinutesOfDay(value);

  return (
    minutes !== null &&
    minutes >= KOREA_SESSION_START_MINUTES &&
    minutes <= KOREA_SESSION_END_MINUTES
  );
}
