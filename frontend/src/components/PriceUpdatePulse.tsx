"use client";

import { type ReactNode, useEffect, useRef, useState } from "react";

type PulseTone = "up" | "down" | "neutral";

type Props = {
  children: ReactNode;
  className?: string;
  direction?: number | null;
  disabled?: boolean;
  resetKey?: string | number | null;
  value: number | string | null | undefined;
};

function normalizeValue(value: Props["value"]) {
  if (value === null || value === undefined) return null;
  if (typeof value === "number") {
    if (Number.isNaN(value)) return null;
    return String(value);
  }

  return value;
}

function resolvePulseTone(direction: number | null | undefined): PulseTone {
  if (direction !== null && direction !== undefined && !Number.isNaN(direction)) {
    if (direction > 0) return "up";
    if (direction < 0) return "down";
  }

  return "neutral";
}

export default function PriceUpdatePulse({
  children,
  className = "",
  direction,
  disabled = false,
  resetKey = null,
  value,
}: Props) {
  const [pulseTone, setPulseTone] = useState<PulseTone | null>(null);
  const previousRef = useRef<{ resetKey: string | null; value: string | null } | null>(null);
  const timeoutRef = useRef<number | null>(null);
  const frameRef = useRef<number | null>(null);

  useEffect(() => {
    const currentValue = normalizeValue(value);
    const currentResetKey = resetKey === null || resetKey === undefined ? null : String(resetKey);
    const previous = previousRef.current;

    if (!previous || previous.resetKey !== currentResetKey) {
      previousRef.current = { resetKey: currentResetKey, value: currentValue };
      setPulseTone(null);
      return;
    }

    previousRef.current = { resetKey: currentResetKey, value: currentValue };

    if (disabled || previous.value === currentValue || currentValue === null) {
      return;
    }

    const tone = resolvePulseTone(direction);

    if (timeoutRef.current !== null) {
      window.clearTimeout(timeoutRef.current);
    }
    if (frameRef.current !== null) {
      window.cancelAnimationFrame(frameRef.current);
    }

    setPulseTone(null);
    frameRef.current = window.requestAnimationFrame(() => {
      setPulseTone(tone);
      timeoutRef.current = window.setTimeout(() => {
        setPulseTone(null);
        timeoutRef.current = null;
      }, 760);
    });
  }, [direction, disabled, resetKey, value]);

  useEffect(() => {
    return () => {
      if (timeoutRef.current !== null) {
        window.clearTimeout(timeoutRef.current);
      }
      if (frameRef.current !== null) {
        window.cancelAnimationFrame(frameRef.current);
      }
    };
  }, []);

  return (
    <span
      className={[
        "omi-price-pulse inline-flex items-baseline",
        pulseTone ? `omi-price-pulse-${pulseTone}` : "",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <span className="relative z-[1]">{children}</span>
    </span>
  );
}
