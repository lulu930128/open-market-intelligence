"use client";

import { useT } from "@/i18n";

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
