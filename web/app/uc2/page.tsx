import { UcDashboard } from "@/components/uc-dashboard";
import { UcHeader } from "@/components/uc-header";
import { hasLiveCreds, uc2LiveFetcher } from "@/lib/bigquery";
import type { Uc2Envelope } from "@/lib/golden-types";
import { cachedLiveFetcher } from "@/lib/page-fetcher";
import { serve } from "@/lib/serve";

// UC2 — Port dwell & turnaround trend (BigQuery / OLAP). Server Component: fetches the
// envelope via serve("uc2", cachedLiveFetcher(...)) — the SAME creds-gated BigQuery fetcher
// the sibling /api/uc2 route uses, wrapped in a ~300s data-layer cache (DATA-06) — then
// hands envelope.rows to the client <UcDashboard> which owns all interactive config
// (D-04 server-fetch / client-reconfigure boundary; CHART-05 no re-query).
//
// force-dynamic (APP-05): render per request so served_by reflects reality and the UcHeader
// pill genuinely flips Live<->Snapshot; the live round-trip stays cached off the per-render
// path so DATA-06 is not regressed.
export const dynamic = "force-dynamic";

export default async function Uc2Page() {
  const envelope = await serve(
    "uc2",
    cachedLiveFetcher("uc2", hasLiveCreds, uc2LiveFetcher),
  );

  return (
    <main className="mx-auto max-w-5xl px-6 py-16">
      <UcHeader id="uc2" servedBy={envelope.served_by} />
      <UcDashboard ucId="uc2" rows={(envelope as Uc2Envelope).rows} />
    </main>
  );
}
