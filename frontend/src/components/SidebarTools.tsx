"use client";

import Link from "next/link";
import { useT } from "@/i18n";

export default function SidebarTools() {
  const t = useT();
  return (
    <nav aria-label={t("workspaceTools.label")} className="mt-3">
      <Link href="/research" prefetch={false}
        className="flex min-h-9 items-center justify-center border border-omi-accent-border bg-omi-accent-soft px-3 text-xs font-semibold text-omi-accent hover:bg-omi-surface-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-omi-accent">
        {t("workspaceTools.research")}
      </Link>
    </nav>
  );
}
