"use client";

export function LoadingDots({
  label = "資料讀取中",
  className = "",
}: {
  label?: string;
  className?: string;
}) {
  return (
    <span
      role="status"
      aria-label={label}
      className={["omi-loading-dots", className].filter(Boolean).join(" ")}
    >
      <span />
      <span />
      <span />
    </span>
  );
}
