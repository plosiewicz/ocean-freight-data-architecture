// route-cache-config.test.ts — DATA-06 Wave-0 unit gate (RESEARCH §Validation Architecture).
//
// The authoritative DATA-06 proof is the `npm run build` route table marking /api/ucN as
// static/ISR (Pitfall 1: a route showing `ƒ (Dynamic)` means the cache is inert). This
// unit test is the fast, hermetic guard that the two REQUIRED segment-config exports are
// present in each route source — so a regression that drops `force-static` (re-inerting the
// cache) fails CI before a human ever reads the build table.
//
// It is a SOURCE-TEXT assertion (not a runtime import): route.ts modules pull in
// next/server + the live BQ/Arango fetchers, which are not meant to execute under the bare
// node vitest environment. Reading the file text via node:fs keeps the test hermetic and
// matches the "verbatim sql" source-comparison style already used in bigquery.test.ts.
//
// Placed under lib/ so it falls inside the existing `lib/**/*.test.ts` vitest include glob
// (vitest.config.ts) — no config change needed. cwd at test time is web/, so the route
// paths resolve from process.cwd().

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

// The four param-free GET route handlers that must be opted into static/ISR caching.
const ROUTE_PATHS = [
  "app/api/uc1/route.ts",
  "app/api/uc2/route.ts",
  "app/api/uc3/route.ts",
  "app/api/uc4/route.ts",
] as const;

function readRoute(rel: string): string {
  return readFileSync(join(process.cwd(), rel), "utf8");
}

describe("DATA-06: all four UC routes export the static/ISR cache segment config", () => {
  it.each(ROUTE_PATHS)(
    "%s opts into static rendering with `dynamic = \"force-static\"`",
    (rel) => {
      const src = readRoute(rel);
      // force-static is the load-bearing export — `revalidate` alone is inert for a
      // no-fetch() GET handler (RESEARCH D-01 CORRECTION / Pitfall 1).
      expect(src).toContain('export const dynamic = "force-static"');
    },
  );

  it.each(ROUTE_PATHS)("%s sets the 300s regeneration timer", (rel) => {
    const src = readRoute(rel);
    expect(src).toContain("export const revalidate = 300");
  });

  it.each(ROUTE_PATHS)(
    "%s still runs on the Node runtime (serve() reads node:fs)",
    (rel) => {
      const src = readRoute(rel);
      // Node runtime must be preserved — switching to edge would break serve()'s node:fs read.
      expect(src).toContain('export const runtime = "nodejs"');
    },
  );
});
