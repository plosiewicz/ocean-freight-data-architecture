import { UcHeader } from "@/components/uc-header";
import { Uc4Summary } from "@/components/uc4-summary";
import { serve } from "@/lib/serve";

// UC4 — Disruption rerouting (ArangoDB / graph). Async Server Component:
// fetches the golden envelope server-side via serve() (golden-only in Phase 9),
// composes the provenance header + the baseline-vs-reroute summary. No "use client" —
// the summary is render-only, so nothing serializes secrets to the bundle.

export default async function Uc4Page() {
  // serve()'s envelope type is inferred from the "uc4" id (U extends UcId).
  const envelope = await serve("uc4");
  return (
    <main className="mx-auto max-w-3xl px-6 py-16">
      <UcHeader id="uc4" servedBy={envelope.served_by} />
      <Uc4Summary data={envelope} />
    </main>
  );
}
