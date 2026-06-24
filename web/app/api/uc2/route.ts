import { NextResponse } from "next/server";

import { hasLiveCreds, uc2LiveFetcher } from "@/lib/bigquery";
import type { Uc2Envelope } from "@/lib/golden-types";
import { serve } from "@/lib/serve";

// UC2 route handler — returns the golden envelope (+ served_by) verbatim (DATA-01).
// Placed under app/api/uc2/ because app/uc2/ already holds page.tsx.
//
// Node runtime is REQUIRED: serve() reads node:fs from server-assets/golden (T-09-01).
export const runtime = "nodejs";
// DATA-06 (RESEARCH D-01 CORRECTION): `revalidate` alone is INERT here because this GET
// handler calls no fetch() (serve() reads node:fs + process.env), and GET handlers are
// dynamic-by-default since Next 15-RC. `force-static` is what actually opts the route into
// static/ISR caching; pairing it with revalidate=300 regenerates at most every 5 minutes,
// keeping repeated demo clicks off the live BigQuery round-trip.
export const dynamic = "force-static";
export const revalidate = 300;

export async function GET() {
  // Phase 11: pass the live BigQuery fetcher only when the SA credential is present
  // (D-06 creds gate). Absent creds → undefined → serve() serves golden. FORCE_GOLDEN
  // still overrides to golden, and serve()'s catch still falls back on any throw.
  const envelope = await serve("uc2", hasLiveCreds() ? uc2LiveFetcher : undefined);
  return NextResponse.json(envelope satisfies Uc2Envelope & { served_by: string });
}
