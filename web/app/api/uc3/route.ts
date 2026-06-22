import { NextResponse } from "next/server";

import type { Uc3Envelope } from "@/lib/golden-types";
import { serve } from "@/lib/serve";

// UC3 route handler — returns the golden envelope (+ served_by) verbatim (DATA-01).
// Placed under app/api/uc3/ because app/uc3/ already holds page.tsx. UC3 golden has
// no top-level store key — the loader/serve types do not assume one.
//
// Node runtime is REQUIRED: serve() reads node:fs from server-assets/golden (T-09-01).
export const runtime = "nodejs";

export async function GET() {
  // Phase 9: no liveFetcher → serve() always falls to the frozen golden snapshot.
  // Phases 12 passes the live ArangoDB fetcher here without changing the fallback.
  const envelope = await serve("uc3");
  return NextResponse.json(envelope satisfies Uc3Envelope & { served_by: string });
}
