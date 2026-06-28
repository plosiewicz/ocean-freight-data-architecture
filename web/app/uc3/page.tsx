import { Uc3MapLoader } from "@/components/uc3-map-loader";
import { UcHeader } from "@/components/uc-header";
import { Uc3Summary } from "@/components/uc3-summary";
import { hasLiveCreds, uc3LiveFetcher, uc4LiveFetcher } from "@/lib/arango";
import { rankChokepoints, readCriticality } from "@/lib/criticality";
import type { ServedBy, Uc3Enriched, Uc4Enriched } from "@/lib/golden-types";
import { cachedLiveFetcher } from "@/lib/page-fetcher";
import { serve } from "@/lib/serve";

// UC3 — Chokepoint risk exposure (ArangoDB / graph). Async Server Component:
// fetches the COORD-ENRICHED golden envelope server-side via serve() (golden-only in
// Phase 9; enrichment runs inside serve()), composes the provenance header, the deck.gl
// map (a "use client" child), then the persisting structured summary BELOW it (D-11).
// The page itself stays an RSC — only the map loader is "use client", so nothing
// sensitive serializes into the bundle.
//
// force-dynamic (APP-05): render per request so served_by reflects reality and the UcHeader
// pill genuinely flips Live<->Snapshot. The live ArangoDB round-trip stays off the per-render
// path via the cachedLiveFetcher data cache (~300s, clear of the ~1h JWT window), so DATA-06
// is not regressed.
export const dynamic = "force-dynamic";

export default async function Uc3Page() {
  // serve()'s static type is the base Uc3Envelope; at runtime serve() enriches uc3/uc4
  // with lat/lon (+ chokepoint names + the explicit ports[]). Narrow to Uc3Enriched for
  // the map loader — the enrichment is the store-agnostic render contract (10-01). The
  // second arg is the SAME creds-gated ArangoDB fetcher /api/uc3 uses, cache-wrapped.
  const envelope = (await serve(
    "uc3",
    cachedLiveFetcher("uc3", hasLiveCreds, uc3LiveFetcher),
  )) as Uc3Enriched & {
    served_by: ServedBy;
  };
  const routeEnvelope = (await serve(
    "uc4",
    cachedLiveFetcher("uc4", hasLiveCreds, uc4LiveFetcher),
  )) as Uc4Enriched & {
    served_by: ServedBy;
  };

  // MAP-04: read the FROZEN betweenness criticality server-side (mirrors serve()'s
  // node:fs read of the golden), then join it to the already-fetched transit_share by
  // chokepoint key. This stays OUT of the serve() envelope (shape-preserving) and adds no
  // client re-query — the ranked rows are computed here and passed down render-only.
  const ranked = rankChokepoints(envelope.transit_share, readCriticality());

  return (
    <main className="mx-auto max-w-5xl px-6 py-16">
      <UcHeader id="uc3" servedBy={envelope.served_by} />
      <Uc3MapLoader envelope={envelope} routeEnvelope={routeEnvelope} />
      <Uc3Summary data={envelope} ranked={ranked} route={routeEnvelope} />
    </main>
  );
}
