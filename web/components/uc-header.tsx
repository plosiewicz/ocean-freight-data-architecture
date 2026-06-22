import Link from "next/link";

import type { ServedBy } from "@/lib/golden-types";
import { USE_CASES, type UseCase } from "@/lib/use-cases";
import { cn } from "@/lib/utils";

// Reusable per-UC page header — the home of the right-store-per-workload provenance
// (APP-03 "Answered by", APP-04 why-this-store rationale). Rendered at the top of every
// /uc<n> page. The store badge reuses the SAME blue/emerald color map as the landing
// uc-card.tsx so provenance reads identically across the app.
//
// All metadata (title, store, workload rationale) is sourced from USE_CASES — the typed
// source of truth — NEVER from the golden `store` string (which is lowercase "bigquery"
// for UC1/UC2 and absent entirely on UC3/UC4).

// Store-tag color map — kept verbatim in sync with web/components/uc-card.tsx (D-07).
const STORE_TAG_STYLE: Record<UseCase["store"], string> = {
  BigQuery: "bg-blue-100 text-blue-800 ring-blue-200",
  ArangoDB: "bg-emerald-100 text-emerald-800 ring-emerald-200",
};

export interface UcHeaderProps {
  id: UseCase["id"];
  // Reserved Phase-13 slot (APP-05): the live/golden indicator plugs in here without
  // restructuring the header. P9 accepts the prop but renders nothing for it.
  servedBy?: ServedBy;
}

export function UcHeader({ id, servedBy }: UcHeaderProps) {
  const uc = USE_CASES.find((u) => u.id === id)!;

  return (
    <header className="border-b pb-6">
      <Link
        href="/"
        className="text-sm text-muted-foreground underline-offset-4 hover:underline"
      >
        ← Back to overview
      </Link>

      <div className="mt-6 flex flex-wrap items-center gap-3">
        <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          {uc.id}
        </span>
        {/* Store provenance badge — APP-03. Reuses the landing-page color map. */}
        <span
          className={cn(
            "rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ring-inset",
            STORE_TAG_STYLE[uc.store],
          )}
          data-store-tag={uc.store}
        >
          Answered by: {uc.store}
        </span>
        {/* Phase-13 served_by slot — reserved, renders nothing in P9 (D-07/APP-05). */}
        {servedBy ? (
          <span
            className="text-xs font-medium text-muted-foreground"
            data-served-by={servedBy}
          >
            served {servedBy}
          </span>
        ) : null}
      </div>

      <h1 className="mt-3 text-3xl font-semibold tracking-tight">{uc.title}</h1>

      {/* Why-this-store rationale — APP-04. Workload classification from USE_CASES. */}
      <p className="mt-3 max-w-2xl text-sm leading-relaxed text-muted-foreground">
        <span className="font-medium text-foreground">
          Why {uc.store}: {uc.workload}.
        </span>{" "}
        {uc.summary}
      </p>
    </header>
  );
}
