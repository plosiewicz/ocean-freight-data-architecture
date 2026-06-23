import { Uc4MapLoader } from "@/components/uc4-map-loader";
import { UcHeader } from "@/components/uc-header";
import { Uc4Summary } from "@/components/uc4-summary";
import type { ServedBy, Uc4Enriched } from "@/lib/golden-types";
import { serve } from "@/lib/serve";

// UC4 — Disruption rerouting (ArangoDB / graph). Async Server Component:
// fetches the golden envelope server-side via serve() (golden-only in Phase 9), composes
// the provenance header + the baseline-vs-reroute arc map ABOVE the persisting summary.
// No "use client" — the map render lives in the "use client" Uc4MapLoader, so nothing
// serializes secrets to the bundle.
//
// serve("uc4") is statically typed as the base Uc4Envelope but enriches uc4 with coords at
// runtime (the 10-01 design); we narrow to Uc4Enriched the same documented way uc3/page.tsx
// does. The base-shaped fields the summary reads are a subset of the enriched type, so the
// single fetched envelope feeds both the map (enriched) and the summary (base) unchanged.

export default async function Uc4Page() {
  const envelope = (await serve("uc4")) as Uc4Enriched & {
    served_by: ServedBy;
  };

  return (
    <main className="mx-auto max-w-5xl px-6 py-16">
      <UcHeader id="uc4" servedBy={envelope.served_by} />
      <Uc4MapLoader envelope={envelope} />
      <Uc4Summary data={envelope} />
    </main>
  );
}
