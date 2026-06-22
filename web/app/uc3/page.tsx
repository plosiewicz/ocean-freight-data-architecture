import { UcHeader } from "@/components/uc-header";
import { Uc3Summary } from "@/components/uc3-summary";
import { serve } from "@/lib/serve";

// UC3 — Chokepoint risk exposure (ArangoDB / graph). Async Server Component:
// fetches the golden envelope server-side via serve() (golden-only in Phase 9),
// composes the provenance header + the structured summary. No "use client" —
// the summary is render-only, so nothing serializes secrets to the bundle.

export default async function Uc3Page() {
  // serve()'s envelope type is inferred from the "uc3" id (U extends UcId).
  const envelope = await serve("uc3");
  return (
    <main className="mx-auto max-w-3xl px-6 py-16">
      <UcHeader id="uc3" servedBy={envelope.served_by} />
      <Uc3Summary data={envelope} />
    </main>
  );
}
