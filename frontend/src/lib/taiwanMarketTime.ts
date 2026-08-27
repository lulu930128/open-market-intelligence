import {
  getMarketCalendarStatusSnapshot,
  msUntilIsoTime,
} from "@/lib/marketCalendarStatus";

export const TAIWAN_INTRADAY_REFRESH_MS = 5_000;
export const TAIWAN_PREOPEN_MINUTES = 8 * 60 + 30;
export const TAIWAN_SESSION_START_MINUTES = 9 * 60;
export const TAIWAN_SESSION_END_MINUTES = 13 * 60 + 30;
export const TAIWAN_MARKET_CHIP_REFRESH_EVENT = "omi:market-chip-refreshed";

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

function taipeiDateKey(year: number, month: number, day: number) {
  return `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

export function getTaipeiDateKey(value = new Date()) {
  const parts = getTaipeiParts(value);
  return taipeiDateKey(parts.year, parts.month, parts.day);
}

export function getTaipeiMinutesOfDay(value: string | Date) {
  const date = typeof value === "string" ? new Date(value) : value;

  if (Number.isNaN(date.getTime())) return null;

  const parts = getTaipeiParts(date);
  return parts.hour * 60 + parts.minute + parts.second / 60;
}

export function getTaiwanMarketRefreshState(now = new Date()) {
  const dateKey = getTaipeiDateKey(now);
  const calendarStatus = getMarketCalendarStatusSnapshot("tw");

  if (calendarStatus?.date === dateKey) {
    const nextPollingMs =
      msUntilIsoTime(calendarStatus.session.next_session_start_at, now) ?? 60_000;
    const dailyPriceRelease = calendarStatus.release_windows.market_daily_price;

    return {
      dateKey,
      isPollingWindow: calendarStatus.session.is_polling_window,
      isAfterClose: calendarStatus.session.is_after_close,
      isDailyPriceReleased: Boolean(dailyPriceRelease?.is_released),
      msUntilNextPollingStart: nextPollingMs,
    };
  }

  // Backend calendar ownership is authoritative. Missing/stale frontend
  // bootstrap state pauses automation instead of recreating market rules here.
  return {
    dateKey,
    isPollingWindow: false,
    isAfterClose: false,
    isDailyPriceReleased: false,
    msUntilNextPollingStart: 60_000,
  };
}

export function getTaiwanMarketChipRefreshState(now = new Date()) {
  const dateKey = getTaipeiDateKey(now);
  const calendarStatus = getMarketCalendarStatusSnapshot("tw");

  if (calendarStatus?.date === dateKey) {
    const marketChipRelease = calendarStatus.release_windows.market_chip_daily;
    const marginRelease =
      calendarStatus.release_windows.market_chip_margin_daily;
    const isReleased = (releaseAt: string | undefined, released: boolean | undefined) =>
      Boolean(
        released ||
          (releaseAt && Date.parse(releaseAt) <= now.getTime())
      );
    const mainReleased = isReleased(
      marketChipRelease?.release_at,
      marketChipRelease?.is_released
    );
    const marginReleased = isReleased(
      marginRelease?.release_at,
      marginRelease?.is_released
    );
    const stage = marginReleased ? "margin" : "main";
    const nextReleaseAt = marginReleased
      ? marketChipRelease?.next_release_at
      : mainReleased
        ? marginRelease?.next_release_at
        : marketChipRelease?.next_release_at;
    const nextRefreshMs = msUntilIsoTime(nextReleaseAt, now) ?? 60_000;

    return {
      dateKey,
      refreshKey: `${dateKey}:${stage}`,
      stage,
      isTradingDay: calendarStatus.is_trading_day,
      shouldRefreshNow:
        calendarStatus.is_trading_day && (stage === "margin" ? marginReleased : mainReleased),
      msUntilNextRefresh: nextRefreshMs,
    };
  }

  return {
    dateKey,
    refreshKey: `${dateKey}:paused`,
    stage: "main",
    isTradingDay: false,
    shouldRefreshNow: false,
    msUntilNextRefresh: 60_000,
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
