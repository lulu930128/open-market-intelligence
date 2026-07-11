"use client";

import type { ReactNode } from "react";
import { useT } from "@/i18n";

export type StateSurfaceTone =
  | "neutral"
  | "loading"
  | "empty"
  | "info"
  | "warning"
  | "danger"
  | "success";

export function LoadingDots({
  label,
  className = "",
}: {
  label?: string;
  className?: string;
}) {
  const t = useT();
  const statusLabel = label ?? t("common.loading");

  return (
    <span
      role="status"
      aria-label={statusLabel}
      className={["omi-loading-dots", className].filter(Boolean).join(" ")}
    >
      <span />
      <span />
      <span />
    </span>
  );
}

export function StateSurface({
  title,
  description,
  eyebrow,
  tone = "neutral",
  busy = false,
  compact = false,
  className = "",
  action,
  children,
}: {
  title: string;
  description?: string;
  eyebrow?: string;
  tone?: StateSurfaceTone;
  busy?: boolean;
  compact?: boolean;
  className?: string;
  action?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div
      role={busy ? "status" : undefined}
      aria-live={busy ? "polite" : undefined}
      aria-busy={busy || undefined}
      className={[
        "omi-state-surface",
        `omi-state-surface-${tone}`,
        compact ? "omi-state-surface-compact" : "",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <span className="omi-state-glyph" aria-hidden="true">
        <span />
      </span>
      <div className="min-w-0">
        {eyebrow ? <div className="omi-state-eyebrow">{eyebrow}</div> : null}
        <div className="omi-state-title">{title}</div>
        {description ? <p className="omi-state-description">{description}</p> : null}
        {children}
        {action ? <div className="omi-state-action">{action}</div> : null}
      </div>
      {busy ? <LoadingDots label={title} className="omi-state-dots" /> : null}
    </div>
  );
}

export function LoadingStateSurface({
  title,
  description,
  className = "",
  compact = false,
}: {
  title: string;
  description?: string;
  className?: string;
  compact?: boolean;
}) {
  return (
    <StateSurface
      title={title}
      description={description}
      tone="loading"
      busy
      compact={compact}
      className={className}
    >
      <span className="omi-state-progress" aria-hidden="true">
        <span />
      </span>
    </StateSurface>
  );
}
