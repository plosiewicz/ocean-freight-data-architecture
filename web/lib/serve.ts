// serve() — the response-serving seam for every UC route handler (DATA-04, DATA-05).
//
// Contract: a route handler calls `serve("uc1")` (optionally with a live fetcher) and
// always gets back a valid golden envelope plus a `served_by` field. The logic is:
//
//   1. If FORCE_GOLDEN is truthy (D-10) OR no live fetcher is supplied, serve golden.
//   2. Otherwise try the live fetcher; on success return {...live, served_by:"live"}.
//   3. If the live fetcher throws/rejects, FALL BACK to golden (D-09) — no error escapes.
//
// In Phase 9 no handler passes a live fetcher, so every response is golden-served. The
// catch/fallback seam already exists and is exercised, so Phases 11/12 drop a real
// BigQuery/ArangoDB fetcher into the `liveFetcher` slot WITHOUT touching this logic.
//
// Server-only discipline (T-09-01/T-09-02): this module reads node:fs and
// process.env.FORCE_GOLDEN, so every importing handler MUST run on the Node runtime
// (`export const runtime = "nodejs"`). FORCE_GOLDEN is deliberately a plain (un-prefixed)
// server env var — a client-exposed prefix would inline it into the client bundle and
// trip the secret-gate; serve.ts must contain no such prefix.

import { readFile } from "node:fs/promises";
import { join } from "node:path";

import type { EnvelopeByUc, ServedBy, UcId } from "@/lib/golden-types";

// server-assets/golden lives at web/server-assets/golden — the same destination
// copy-server-assets.mjs writes to (NOT web/public/). Vercel build context is the
// repo root but the runtime cwd is web/, so resolving from process.cwd() lands on
// web/server-assets/golden. Mirror the copy-server-assets.mjs destRoot convention.
const GOLDEN_DIR = join(process.cwd(), "server-assets", "golden");

/**
 * Read process.env.FORCE_GOLDEN server-side (D-10). Truthy "1"/"true" forces the
 * golden path regardless of any live fetcher. Unset/anything else = normal try-live.
 */
function forceGolden(): boolean {
  const v = process.env.FORCE_GOLDEN;
  return v === "1" || v === "true";
}

/**
 * Read and parse a golden envelope from the server-only assets dir. Works for all four
 * use cases, including UC3/UC4 which carry no top-level `store` key.
 */
async function readGolden<U extends UcId>(uc: U): Promise<EnvelopeByUc[U]> {
  const raw = await readFile(join(GOLDEN_DIR, `${uc}.golden.json`), "utf8");
  return JSON.parse(raw) as EnvelopeByUc[U];
}

/**
 * A live fetcher returns the SAME envelope shape as the golden snapshot for its uc.
 * Phases 11/12 implement these against BigQuery / ArangoDB; in Phase 9 none is passed.
 */
export type LiveFetcher<U extends UcId> = () => Promise<EnvelopeByUc[U]>;

/**
 * Serve a UC envelope: try live (if wired and not force-golden), else fall back to the
 * frozen golden snapshot. The returned object is the envelope plus `served_by` recording
 * which path actually produced it.
 */
export async function serve<U extends UcId>(
  uc: U,
  liveFetcher?: LiveFetcher<U>,
): Promise<EnvelopeByUc[U] & { served_by: ServedBy }> {
  if (!forceGolden() && liveFetcher) {
    try {
      const live = await liveFetcher();
      return { ...live, served_by: "live" satisfies ServedBy };
    } catch {
      // Live path failed (timeout, auth, connection) — fall through to golden (D-09).
      // No error escapes: the graded demo cannot hard-fail.
    }
  }
  const golden = await readGolden(uc);
  return { ...golden, served_by: "golden" satisfies ServedBy };
}
