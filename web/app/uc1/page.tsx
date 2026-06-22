import { UcDashboard } from "@/components/uc-dashboard";
import { UcHeader } from "@/components/uc-header";
import type { Uc1Envelope } from "@/lib/golden-types";
import { serve } from "@/lib/serve";

// UC1 — ETA reliability & delay drivers (BigQuery / OLAP). Server Component: fetches the
// envelope via serve("uc1") (golden in Phase 9; live fetcher drops in for Phase 11), then
// hands envelope.rows to the client <UcDashboard> which owns all interactive config
// (D-04 server-fetch / client-reconfigure boundary; CHART-05 no re-query).

export default async function Uc1Page() {
  const envelope = await serve("uc1");

  return (
    <main className="mx-auto max-w-5xl px-6 py-16">
      <UcHeader id="uc1" servedBy={envelope.served_by} />
      <UcDashboard ucId="uc1" rows={(envelope as Uc1Envelope).rows} />
    </main>
  );
}
