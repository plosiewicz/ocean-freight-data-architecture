import Link from "next/link";

import { USE_CASES, type UseCase } from "@/lib/use-cases";

// Minimal placeholder for a /uc<n> route. No data fetching, no live store, no
// credential — just the UC title, store tag, summary, a "coming in Phase 9"
// note, and a back-link. Phase 9 replaces these stubs with the real views.

export function UcStub({ id }: { id: UseCase["id"] }) {
  const uc = USE_CASES.find((u) => u.id === id)!;
  return (
    <main className="mx-auto max-w-3xl px-6 py-16">
      <Link
        href="/"
        className="text-sm text-muted-foreground underline-offset-4 hover:underline"
      >
        ← Back to overview
      </Link>
      <div className="mt-6">
        <span
          className="text-xs font-semibold uppercase tracking-wide text-muted-foreground"
          data-store-tag={uc.store}
        >
          {uc.id} · answered by {uc.store}
        </span>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight">
          {uc.title}
        </h1>
        <p className="mt-4 text-base leading-relaxed text-muted-foreground">
          {uc.summary}
        </p>
        <p className="mt-8 rounded-lg border border-dashed px-4 py-6 text-sm text-muted-foreground">
          This view is coming in Phase 9 — the routing skeleton is in place; the
          live {uc.store} data and visualization land next.
        </p>
      </div>
    </main>
  );
}
