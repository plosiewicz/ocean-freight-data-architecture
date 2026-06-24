import { NextResponse } from "next/server";

import { hasLiveCreds, uc3LiveFetcher } from "@/lib/arango";
import type { Uc3Envelope } from "@/lib/golden-types";
import { serve } from "@/lib/serve";

// UC3 route handler — returns the golden envelope (+ served_by) verbatim (DATA-01).
// Placed under app/api/uc3/ because app/uc3/ already holds page.tsx. UC3 golden has
// no top-level store key — the loader/serve types do not assume one.
//
// Node runtime is REQUIRED: serve() reads node:fs from server-assets/golden (T-09-01).
export const runtime = "nodejs";

export async function GET() {
  // Phase 12: pass the live ArangoDB fetcher only when the ARANGO_* creds are present
  // (D-06 creds gate). Absent creds → undefined → serve() serves golden. FORCE_GOLDEN
  // still overrides to golden, and serve()'s catch still falls back on any throw.
  const envelope = await serve("uc3", hasLiveCreds() ? uc3LiveFetcher : undefined);
  return NextResponse.json(envelope satisfies Uc3Envelope & { served_by: string });
}
