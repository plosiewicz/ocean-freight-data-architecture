import { NextResponse } from "next/server";

import type { Uc1Envelope } from "@/lib/golden-types";
import { serve } from "@/lib/serve";

// UC1 route handler — returns the golden envelope (+ served_by) verbatim (DATA-01).
// Placed under app/api/uc1/ because app/uc1/ already holds page.tsx, and a single
// route segment cannot expose both page.tsx and route.ts.
//
// Node runtime is REQUIRED: serve() reads node:fs from server-assets/golden (T-09-01).
export const runtime = "nodejs";

export async function GET() {
  // Phase 9: no liveFetcher → serve() always falls to the frozen golden snapshot.
  // Phases 11/12 pass the live BigQuery fetcher here without changing the fallback.
  const envelope = await serve("uc1");
  return NextResponse.json(envelope satisfies Uc1Envelope & { served_by: string });
}
