import { NextResponse } from "next/server";

import type { Uc4Envelope } from "@/lib/golden-types";
import { serve } from "@/lib/serve";

// UC4 route handler — returns the golden envelope (+ served_by) verbatim (DATA-01).
// Placed under app/api/uc4/ because app/uc4/ already holds page.tsx. UC4 golden has
// no top-level store key — the loader/serve types do not assume one.
//
// Node runtime is REQUIRED: serve() reads node:fs from server-assets/golden (T-09-01).
export const runtime = "nodejs";

export async function GET() {
  // Phase 9: no liveFetcher → serve() always falls to the frozen golden snapshot.
  const envelope = await serve("uc4");
  return NextResponse.json(envelope satisfies Uc4Envelope & { served_by: string });
}
