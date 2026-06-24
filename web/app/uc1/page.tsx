import { UcDashboard } from "@/components/uc-dashboard";
import { UcHeader } from "@/components/uc-header";
import { hasLiveCreds, uc1LiveFetcher } from "@/lib/bigquery";
import type { Uc1Envelope } from "@/lib/golden-types";
import { cachedLiveFetcher } from "@/lib/page-fetcher";
import { serve } from "@/lib/serve";

// UC1 — ETA reliability & delay drivers (BigQuery / OLAP). Server Component: fetches the
// envelope via serve("uc1", cachedLiveFetcher(...)) — the SAME creds-gated BigQuery fetcher
// the sibling /api/uc1 route uses, wrapped in a ~300s data-layer cache (DATA-06) — then
// hands envelope.rows to the client <UcDashboard> which owns all interactive config
// (D-04 server-fetch / client-reconfigure boundary; CHART-05 no re-query).
//
// force-dynamic (APP-05): render per request so served_by reflects reality at request time
// and the UcHeader pill genuinely flips Live<->Snapshot. The live round-trip stays off the
// per-render path via the cachedLiveFetcher data cache, so DATA-06 is not regressed.
export const dynamic = "force-dynamic";

export default async function Uc1Page() {
  const envelope = await serve(
    "uc1",
    cachedLiveFetcher("uc1", hasLiveCreds, uc1LiveFetcher),
  );

  return (
    <main className="mx-auto max-w-5xl px-6 py-16">
      <UcHeader id="uc1" servedBy={envelope.served_by} />
      <UcDashboard ucId="uc1" rows={(envelope as Uc1Envelope).rows} />
    </main>
  );
}
