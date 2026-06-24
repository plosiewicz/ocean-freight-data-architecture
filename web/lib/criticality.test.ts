// criticality.test.ts — Wave-2 contract for the UC3 criticality reader + transit-share
// join helper (MAP-04). Four concerns:
//
//   (1) readCriticality() reads server-assets/golden/criticality.golden.json and returns
//       a Map of chokepoint _key -> criticality number (the frozen betweenness scores).
//   (2) rankChokepoints(transitShare, criticalityMap) joins each transit_share row (by
//       its `chokepoint` key) to the criticality map (by `_key`), returning rows with
//       BOTH transit_share_pct and criticality, sorted by transit_share_pct descending.
//   (3) a transit_share chokepoint whose key is genuinely absent from the criticality map
//       yields a defined criticality of null (no crash) and still ranks by transit share.
//   (4) JOIN-KEY ALIGNMENT GUARD (the MAP-04 under-delivery gate): against the REAL
//       committed data (data/golden/uc3.golden.json transit_share joined to the real
//       criticality.golden.json), the join is NOT all-null — the chokepoint named by
//       criticality.golden.json's `most_critical` resolves a FINITE criticality. This
//       fails loudly if transit_share[].chokepoint and criticality_by_key[]._key ever
//       live in different key spaces, so the panel can never silently degrade to
//       transit-share-only.
//
// node env, runs in the existing `lib/**/*.test.ts` glob.

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { rankChokepoints, readCriticality } from "@/lib/criticality";
import type { Uc3TransitShare } from "@/lib/golden-types";

const GOLDEN_DIR = join(process.cwd(), "server-assets", "golden");

interface CriticalityGolden {
  criticality_by_key: { _key: string; criticality: number }[];
  most_critical: string;
}

function readCriticalityGolden(): CriticalityGolden {
  const raw = readFileSync(join(GOLDEN_DIR, "criticality.golden.json"), "utf8");
  return JSON.parse(raw) as CriticalityGolden;
}

function readUc3TransitShare(): Uc3TransitShare[] {
  const raw = readFileSync(join(GOLDEN_DIR, "uc3.golden.json"), "utf8");
  return (JSON.parse(raw) as { transit_share: Uc3TransitShare[] }).transit_share;
}

describe("readCriticality (server-assets/golden/criticality.golden.json -> key->score map)", () => {
  it("returns a map of every criticality_by_key _key to its criticality number", () => {
    const golden = readCriticalityGolden();
    const map = readCriticality();
    for (const { _key, criticality } of golden.criticality_by_key) {
      expect(map.get(_key)).toBe(criticality);
      expect(typeof map.get(_key)).toBe("number");
    }
    expect(map.size).toBe(golden.criticality_by_key.length);
  });
});

describe("rankChokepoints (join transit_share to criticality, ranked by transit_share_pct desc)", () => {
  it("attaches criticality to each row and sorts by transit_share_pct descending", () => {
    const transitShare: Uc3TransitShare[] = [
      { chokepoint: "SUEZ", total_lanes: 40, transit_share_pct: 30, transiting_lanes: 12 },
      { chokepoint: "PANAMA", total_lanes: 40, transit_share_pct: 50, transiting_lanes: 20 },
      { chokepoint: "GIBRALTAR", total_lanes: 40, transit_share_pct: 40, transiting_lanes: 16 },
    ];
    const crit = new Map<string, number>([
      ["SUEZ", 1.07],
      ["PANAMA", 1.78],
      ["GIBRALTAR", 1.42],
    ]);
    const ranked = rankChokepoints(transitShare, crit);

    // Sorted by transit_share_pct desc: PANAMA(50) > GIBRALTAR(40) > SUEZ(30).
    expect(ranked.map((r) => r.chokepoint)).toEqual(["PANAMA", "GIBRALTAR", "SUEZ"]);
    // Every row carries BOTH metrics.
    for (const row of ranked) {
      expect(typeof row.transit_share_pct).toBe("number");
      expect(typeof row.criticality).toBe("number");
    }
    expect(ranked[0].criticality).toBe(1.78);
  });

  it("a genuinely-absent chokepoint key yields null criticality and still ranks by transit share", () => {
    const transitShare: Uc3TransitShare[] = [
      { chokepoint: "PANAMA", total_lanes: 40, transit_share_pct: 50, transiting_lanes: 20 },
      { chokepoint: "NOWHERE", total_lanes: 40, transit_share_pct: 70, transiting_lanes: 28 },
    ];
    const crit = new Map<string, number>([["PANAMA", 1.78]]);
    const ranked = rankChokepoints(transitShare, crit);

    // NOWHERE has the highest transit share so it ranks first, with null criticality.
    expect(ranked[0].chokepoint).toBe("NOWHERE");
    expect(ranked[0].criticality).toBeNull();
    expect(ranked[1].chokepoint).toBe("PANAMA");
    expect(ranked[1].criticality).toBe(1.78);
  });
});

describe("JOIN-KEY ALIGNMENT GUARD (MAP-04): real data join is NOT all-null", () => {
  it("the most_critical chokepoint resolves a finite criticality after joining the REAL committed files", () => {
    const golden = readCriticalityGolden();
    const transitShare = readUc3TransitShare();
    const ranked = rankChokepoints(transitShare, readCriticality());

    const mostCritical = golden.most_critical;
    const row = ranked.find((r) => r.chokepoint === mostCritical);

    // The gate: most_critical must be present in the ranked output with a FINITE score
    // (not null/undefined/NaN). A UN/LOCODE-vs-slug key-space mismatch trips this.
    expect(row).toBeDefined();
    expect(row?.criticality).not.toBeNull();
    expect(Number.isFinite(row?.criticality as number)).toBe(true);

    // Stronger: the join is not all-null — at least one row has a finite criticality.
    expect(ranked.some((r) => Number.isFinite(r.criticality as number))).toBe(true);
  });
});
