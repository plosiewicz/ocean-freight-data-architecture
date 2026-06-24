// page-provenance.test.ts — Wave-7 page-seam contract proving the live/golden provenance
// the /ucN PAGES now surface (APP-05 / SC2). It drives serve() through cachedLiveFetcher
// EXACTLY as the pages do — serve("uc1", cachedLiveFetcher("uc1", credsPredicate, fetcher,
// passthroughCache)) — and asserts the resulting served_by for the three outcomes:
//
//   Test 1 (Live):      creds true  + a fetcher that resolves a valid uc1 envelope -> "live"
//   Test 2 (Snapshot):  creds false                                               -> "golden"
//   Test 3 (Snapshot):  creds true  + a fetcher that REJECTS  (serve()'s catch)    -> "golden",
//                       and no secret/stack text leaks into the returned envelope.
//
// HERMETIC: a passthrough cache-wrapper stands in for next/cache (no Next runtime); golden is
// read by serve()'s own node:fs path from server-assets/golden (cwd = web/, staged by the
// prebuild copy step — the suite skips cleanly if that staged golden is absent, mirroring
// arango.test.ts / coords.test.ts). No live BigQuery / ArangoDB cluster is contacted.

import { existsSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { cachedLiveFetcher, type CacheWrapper } from "@/lib/page-fetcher";
import type { EnvelopeByUc } from "@/lib/golden-types";
import { serve } from "@/lib/serve";

const GOLDEN_DIR = join(process.cwd(), "server-assets", "golden");
const haveGolden = existsSync(join(GOLDEN_DIR, "uc1.golden.json"));

// A passthrough cache-wrapper: returns the underlying fn unwrapped, so the seam's behavior
// (not the cache window) is what these tests exercise. Matches the unstable_cache shape.
const passthrough: CacheWrapper = (cb) => cb;

const credsTrue = () => true;
const credsFalse = () => false;

function liveUc1Env(): EnvelopeByUc["uc1"] {
  return {
    frozen_at_iso: "2026-01-01T00:00:00.000Z",
    query: "sql/uc1_eta_reliability.sql",
    row_count: 1,
    rows: [
      {
        carrier_name: "LIVE CARRIER",
        carrier_scac: "LIVE",
        origin_unlocode: "USNYC",
        dest_unlocode: "CNSHA",
        lane_key: "USNYC-CNSHA",
        legs: 1,
        on_time_pct: 99.9,
        avg_delay_hours: 1.0,
      },
    ],
    store: "bigquery",
    use_case: "UC1",
  };
}

describe("page seam provenance (serve + cachedLiveFetcher, exactly as the /ucN pages call it)", () => {
  it.skipIf(!haveGolden)(
    "Live: creds present + a successful live fetcher -> served_by === 'live'",
    async () => {
      const live = async () => liveUc1Env();
      const envelope = await serve(
        "uc1",
        cachedLiveFetcher("uc1", credsTrue, live, passthrough),
      );
      expect(envelope.served_by).toBe("live");
      // The live rows flowed through (not the golden snapshot).
      expect((envelope as EnvelopeByUc["uc1"]).rows[0].carrier_scac).toBe("LIVE");
    },
  );

  it.skipIf(!haveGolden)(
    "Snapshot via absent creds: creds false -> cachedLiveFetcher undefined -> served_by === 'golden'",
    async () => {
      const live = async () => liveUc1Env();
      const envelope = await serve(
        "uc1",
        cachedLiveFetcher("uc1", credsFalse, live, passthrough),
      );
      expect(envelope.served_by).toBe("golden");
    },
  );

  it.skipIf(!haveGolden)(
    "Snapshot via thrown fetcher: creds true + rejecting fetcher -> serve() catch -> 'golden', no secret leaks",
    async () => {
      const SECRET = "SUPER_SECRET_TOKEN_abc123";
      const boom = async (): Promise<EnvelopeByUc["uc1"]> => {
        throw new Error(`live auth failed with ${SECRET} at https://invalid.example:8529`);
      };
      const envelope = await serve(
        "uc1",
        cachedLiveFetcher("uc1", credsTrue, boom, passthrough),
      );
      expect(envelope.served_by).toBe("golden");
      // No secret / stack / error text leaks into the returned envelope (T-13-04).
      const serialized = JSON.stringify(envelope);
      expect(serialized).not.toContain(SECRET);
      expect(serialized).not.toContain("invalid.example");
      expect(serialized).not.toContain("live auth failed");
    },
  );
});
