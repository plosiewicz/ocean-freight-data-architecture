import { NextResponse } from "next/server";

import type { Uc2Envelope } from "@/lib/golden-types";
import { serve } from "@/lib/serve";

// UC2 route handler — returns the golden envelope (+ served_by) verbatim (DATA-01).
// Placed under app/api/uc2/ because app/uc2/ already holds page.tsx.
//
// Node runtime is REQUIRED: serve() reads node:fs from server-assets/golden (T-09-01).
export const runtime = "nodejs";

export async function GET() {
  // Phase 9: no liveFetcher → serve() always falls to the frozen golden snapshot.
  const envelope = await serve("uc2");
  return NextResponse.json(envelope satisfies Uc2Envelope & { served_by: string });
}
