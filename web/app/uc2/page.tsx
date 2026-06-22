import { UcDashboard } from "@/components/uc-dashboard";
import { UcHeader } from "@/components/uc-header";
import type { Uc2Envelope } from "@/lib/golden-types";
import { serve } from "@/lib/serve";

// UC2 — Port dwell & turnaround trend (BigQuery / OLAP). Server Component: fetches the
// envelope via serve("uc2") (golden in Phase 9; live fetcher drops in for Phase 11), then
// hands envelope.rows to the client <UcDashboard> which owns all interactive config
// (D-04 server-fetch / client-reconfigure boundary; CHART-05 no re-query).

export default async function Uc2Page() {
  const envelope = await serve("uc2");

  return (
    <main className="mx-auto max-w-5xl px-6 py-16">
      <UcHeader id="uc2" servedBy={envelope.served_by} />
      <UcDashboard ucId="uc2" rows={(envelope as Uc2Envelope).rows} />
    </main>
  );
}
