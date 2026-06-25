// arango.test.ts — Wave-0 hermetic contract for the live ArangoDB LiveFetcher seam
// (DATA-03). Phase 12 is the graph twin of bigquery.test.ts; this expands its 4-block
// structure for the UC3 4-run / UC4 2-run multi-query assembly. Concerns:
//
//   (1) uc3 assembly / uc4 assembly — assembleUc3/assembleUc4 fed BQ-free AQL-shaped
//       fixture rows (derived from the committed golden) map field-for-field to the
//       golden envelope with EXACT primitive types (sort, round12, leg-sum, closure
//       reachable-total SUM, ports/-prefixed vs bare-LOCODE endpoints, 12-element
//       disabled_lanes). HERMETIC: no live cluster, no network, no `new Database(...)`.
//   (2) golden parity — JSON.parse(JSON.stringify(assembleUcN(fixture))) deep-equals the
//       committed server-assets/golden/ucN.golden.json MINUS frozen_at_iso (a live
//       timestamp). The authoritative parity check (D-02), for BOTH UC3 and UC4.
//   (3) coerce throws — num(null/undefined/"x"/NaN), str(null/undefined) THROW, never
//       return NaN/null (WR-02/03/04, Pitfall 3).
//   (4) fall-back — a fetcher whose injected runAql rejects (or whose batch exceeds the
//       budget) REJECTS, so serve() falls back: all-or-fall-back, never a partial
//       envelope (D-01).
//   (5) verbatim aql — staged server-assets/aql/*.aql byte-identical to repo ../aql/*.aql
//       (skip cleanly if the staged dir is absent, mirroring bigquery.test.ts/coords.test.ts).
//   (6) creds gate — hasLiveCreds() reflects presence of all four ARANGO_* vars.
//
// RED state: web/lib/arango.ts does not exist yet, so the `@/lib/arango` import fails and
// the whole suite errors. That is the expected failure before Task 2 implements it.

import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import {
  assembleUc3,
  assembleUc4,
  hasLiveCreds,
  num,
  str,
  uc3LiveFetcher,
  uc4LiveFetcher,
} from "@/lib/arango";
import type { Uc3Envelope, Uc4Envelope } from "@/lib/golden-types";

const GOLDEN_DIR = join(process.cwd(), "server-assets", "golden");
const AQL_DIR = join(process.cwd(), "server-assets", "aql");
const REPO_AQL_DIR = join(process.cwd(), "..", "aql");

function readGolden<T>(uc: string): T {
  const raw = readFileSync(join(GOLDEN_DIR, `${uc}.golden.json`), "utf8");
  return JSON.parse(raw) as T;
}

// Type-level assertions only (never run): the fetchers must be LiveFetcher-compatible.
type _Uc3FetcherIsLive = typeof uc3LiveFetcher extends () => Promise<Uc3Envelope>
  ? true
  : false;
type _Uc4FetcherIsLive = typeof uc4LiveFetcher extends () => Promise<Uc4Envelope>
  ? true
  : false;

// ---- AQL-shaped fixtures DERIVED FROM the committed golden (no live cluster). ----
// transit_share rows: {chokepoint, transiting_lanes, total_lanes, transit_share_pct}.
// The share AQL now FILTERs n>0 (260625-lwx scope), so it returns ONLY the 3 active
// chokepoints — the 4 zero-lane reference chokepoints never reach the assembler. Provided
// UNSORTED to prove the assembler sorts by chokepoint.
const SHARE_ROWS = [
  { chokepoint: "SUEZ", transiting_lanes: 12, total_lanes: 40, transit_share_pct: 30.0 },
  { chokepoint: "PANAMA", transiting_lanes: 20, total_lanes: 40, transit_share_pct: 50.0 },
  { chokepoint: "GIBRALTAR", transiting_lanes: 16, total_lanes: 40, transit_share_pct: 40.0 },
];

// reroute_impact / uc4 path rows: {port, leg_hours}.
const BASELINE_PATH_ROWS = [
  { port: "USNYC", leg_hours: 0 },
  { port: "CNSHA", leg_hours: 355.97 },
];
const REROUTE_PATH_ROWS = [
  { port: "USNYC", leg_hours: 0 },
  { port: "USLAX", leg_hours: 118.4 },
  { port: "CNSHA", leg_hours: 313.79 },
];

// closure rows: {origin, closed, reachable_count, reachable}. 9 rows each; reachable_count
// sums to 29 (OPEN baseline) and 11 (GIBRALTAR-closed). open_origins/closed_origins = 9.
function closureRows(closed: string, counts: number[]): Record<string, unknown>[] {
  return counts.map((c, i) => ({
    origin: `P${i}`,
    closed,
    reachable_count: c,
    reachable: Array.from({ length: c }, (_, j) => `R${j}`),
  }));
}
const OPEN_ROWS = closureRows("__NONE_OPEN__", [5, 4, 4, 4, 3, 3, 2, 2, 2]); // sum 29, len 9
const GIB_ROWS = closureRows("GIBRALTAR", [2, 2, 1, 1, 1, 1, 1, 1, 1]); // sum 11, len 9

// Per-chokepoint closure rows for the 3 ACTIVE chokepoints: GIBRALTAR-closed sums to 11
// (fragmenting); PANAMA/SUEZ stay at the OPEN baseline 29 (resilient — reroute exists).
const CHOKEPOINTS_FIXTURE = ["GIBRALTAR", "PANAMA", "SUEZ"];
const CLOSURE_BY_CP: Record<string, Record<string, unknown>[]> = Object.fromEntries(
  CHOKEPOINTS_FIXTURE.map((cp) => [
    cp,
    cp === "GIBRALTAR" ? GIB_ROWS : closureRows(cp, [5, 4, 4, 4, 3, 3, 2, 2, 2]),
  ]),
);
// Per-chokepoint reroute leg rows: SUEZ/PANAMA take the reroute path (sum 432.19 ->
// delta 76.22 vs baseline 355.97); GIBRALTAR's 16 lanes don't touch the demo pair (delta 0).
const REROUTE_BY_CP: Record<string, Record<string, unknown>[]> = Object.fromEntries(
  CHOKEPOINTS_FIXTURE.map((cp) => [
    cp,
    cp === "SUEZ" || cp === "PANAMA" ? REROUTE_PATH_ROWS : BASELINE_PATH_ROWS,
  ]),
);

function uc3Parts() {
  return {
    share: SHARE_ROWS,
    impactReroute: REROUTE_PATH_ROWS,
    impactBaseline: BASELINE_PATH_ROWS,
    openRows: OPEN_ROWS,
    gibRows: GIB_ROWS,
    closureByCp: CLOSURE_BY_CP,
    rerouteByCp: REROUTE_BY_CP,
  };
}
function uc4Parts() {
  return { baselineRows: BASELINE_PATH_ROWS, rerouteRows: REROUTE_PATH_ROWS };
}

describe("uc3 assembly (4-run AQL fixtures -> golden-shaped Uc3Envelope)", () => {
  it("sorts transit_share by chokepoint, round12s pct, and types each field", () => {
    const env = assembleUc3(uc3Parts());
    expect(env.use_case).toBe("UC3");
    // bare LOCODE at the top level (Pitfall 4)
    expect(env.origin).toBe("USNYC");
    expect(env.dest).toBe("CNSHA");
    // sorted by chokepoint — only the 3 active chokepoints (share AQL FILTERs n>0)
    expect(env.transit_share.map((r) => r.chokepoint)).toEqual([
      "GIBRALTAR",
      "PANAMA",
      "SUEZ",
    ]);
    for (const r of env.transit_share) {
      expect(typeof r.transit_share_pct).toBe("number");
      expect(typeof r.transiting_lanes).toBe("number");
      expect(typeof r.total_lanes).toBe("number");
      expect(typeof r.chokepoint).toBe("string");
    }
    const gib = env.transit_share.find((r) => r.chokepoint === "GIBRALTAR");
    expect(gib?.transit_share_pct).toBe(40.0);
    expect(gib?.transiting_lanes).toBe(16);
  });

  it("assembles reroute_impact_suez with summed hours, delta, ports/-prefixed endpoints, ordered disabled_lanes", () => {
    const env = assembleUc3(uc3Parts());
    const ri = env.reroute_impact_suez;
    expect(ri.closed).toBe("SUEZ");
    expect(ri.origin).toBe("ports/USNYC");
    expect(ri.dest).toBe("ports/CNSHA");
    expect(ri.baseline_legs).toEqual([0, 355.97]);
    expect(ri.reroute_legs).toEqual([0, 118.4, 313.79]);
    expect(ri.baseline_hours).toBe(355.97);
    expect(ri.reroute_hours).toBe(432.19);
    expect(ri.delta).toBe(76.22);
    expect(ri.disabled_lanes).toEqual([
      "USNYC__CNSHA",
      "USNYC__JPTYO",
      "USNYC__KRPUS",
      "USSAV__CNSHA",
      "USSAV__JPTYO",
      "USSAV__KRPUS",
      "CNSHA__USNYC",
      "JPTYO__USNYC",
      "KRPUS__USNYC",
      "CNSHA__USSAV",
      "JPTYO__USSAV",
      "KRPUS__USSAV",
    ]);
    expect(ri.disabled_lanes.length).toBe(12);
    expect(ri.baseline_legs.every((x) => typeof x === "number")).toBe(true);
    expect(ri.reroute_legs.every((x) => typeof x === "number")).toBe(true);
  });

  it("assembles closure_gibraltar by SUMMING reachable_count (29/11) and COUNTING origins (9/9)", () => {
    const env = assembleUc3(uc3Parts());
    const c = env.closure_gibraltar;
    expect(c.closed).toBe("GIBRALTAR");
    expect(c.open_reachable_total).toBe(29); // SUM of reachable_count, not a single row
    expect(c.closed_reachable_total).toBe(11);
    expect(c.open_origins).toBe(9); // row COUNT
    expect(c.closed_origins).toBe(9);
    expect(typeof c.open_reachable_total).toBe("number");
  });

  it("assembles closure_by_chokepoint with 3 sorted active entries, the right per-cp totals/deltas/lane-counts", () => {
    const env = assembleUc3(uc3Parts());
    const entries = env.closure_by_chokepoint;
    // Only the 3 active chokepoints (derived from the n>0-filtered transit_share).
    expect(entries.map((e) => e.chokepoint)).toEqual(["GIBRALTAR", "PANAMA", "SUEZ"]);
    const by = Object.fromEntries(entries.map((e) => [e.chokepoint, e]));
    // GIBRALTAR fragments (29 -> 11); PANAMA/SUEZ stay at the open baseline 29 (resilient).
    expect(by.GIBRALTAR.closed_reachable_total).toBe(11);
    for (const cp of ["PANAMA", "SUEZ"]) {
      expect(by[cp].closed_reachable_total).toBe(29);
    }
    // Every entry shares the open baseline 29 / 9 origins.
    for (const e of entries) {
      expect(e.open_reachable_total).toBe(29);
      expect(e.open_origins).toBe(9);
      expect(e.closed_origins).toBe(9);
      expect(typeof e.reroute_delta_hours).toBe("number");
    }
    // SUEZ/PANAMA add 76.22h on the demo pair; GIBRALTAR's lanes don't touch it (delta 0).
    expect(by.SUEZ.reroute_delta_hours).toBe(76.22);
    expect(by.PANAMA.reroute_delta_hours).toBe(76.22);
    expect(by.SUEZ.reroute_baseline_hours).toBe(355.97);
    expect(by.SUEZ.reroute_reroute_hours).toBe(432.19);
    expect(by.GIBRALTAR.reroute_delta_hours).toBe(0);
    // disabled_lane_count comes from DISABLED_LANES_BY_CHOKEPOINT (SUEZ=12, PANAMA=20, GIBRALTAR=16).
    expect(by.SUEZ.disabled_lane_count).toBe(12);
    expect(by.PANAMA.disabled_lane_count).toBe(20);
    expect(by.GIBRALTAR.disabled_lane_count).toBe(16);
  });
});

describe("uc4 assembly (2-run path fixtures -> golden-shaped Uc4Envelope)", () => {
  it("assembles baseline/reroute paths, summed hours, delta, ports/-prefixed endpoints", () => {
    const env = assembleUc4(uc4Parts());
    expect(env.use_case).toBe("UC4");
    expect(env.origin).toBe("ports/USNYC"); // ports/-prefixed at top level (Pitfall 4)
    expect(env.dest).toBe("ports/CNSHA");
    expect(env.baseline_path).toEqual([
      { port: "USNYC", leg_hours: 0 },
      { port: "CNSHA", leg_hours: 355.97 },
    ]);
    expect(env.reroute_path).toEqual([
      { port: "USNYC", leg_hours: 0 },
      { port: "USLAX", leg_hours: 118.4 },
      { port: "CNSHA", leg_hours: 313.79 },
    ]);
    expect(env.baseline_hours).toBe(355.97);
    expect(env.reroute_hours).toBe(432.19);
    expect(env.delta).toBe(76.22);
    expect(env.disabled_lanes.length).toBe(12);
    for (const h of [...env.baseline_path, ...env.reroute_path]) {
      expect(typeof h.port).toBe("string");
      expect(typeof h.leg_hours).toBe("number");
    }
  });
});

describe("golden parity (assembled envelope == committed golden minus frozen_at_iso)", () => {
  it("uc3: deep-equals server-assets/golden/uc3.golden.json field-for-field", () => {
    const golden = readGolden<Uc3Envelope & Record<string, unknown>>("uc3");
    const assembled = JSON.parse(JSON.stringify(assembleUc3(uc3Parts()))) as Record<
      string,
      unknown
    >;
    delete (golden as Record<string, unknown>).frozen_at_iso;
    delete assembled.frozen_at_iso;
    expect(Object.keys(assembled).sort()).toEqual(Object.keys(golden).sort());
    expect(assembled).toEqual(golden);
  });

  it("uc4: deep-equals server-assets/golden/uc4.golden.json field-for-field", () => {
    const golden = readGolden<Uc4Envelope & Record<string, unknown>>("uc4");
    const assembled = JSON.parse(JSON.stringify(assembleUc4(uc4Parts()))) as Record<
      string,
      unknown
    >;
    delete (golden as Record<string, unknown>).frozen_at_iso;
    delete assembled.frozen_at_iso;
    expect(Object.keys(assembled).sort()).toEqual(Object.keys(golden).sort());
    expect(assembled).toEqual(golden);
  });
});

describe("coerce throws (num/str reject malformed rows — no silent NaN/null, WR-02/03/04)", () => {
  it("num throws on null/undefined/non-numeric/NaN", () => {
    expect(() => num(null)).toThrow();
    expect(() => num(undefined)).toThrow();
    expect(() => num("not-a-number")).toThrow();
    expect(() => num(NaN)).toThrow();
  });
  it("str throws on null/undefined", () => {
    expect(() => str(null)).toThrow();
    expect(() => str(undefined)).toThrow();
  });
  it("num/str pass valid values through", () => {
    expect(num("355.97")).toBe(355.97);
    expect(num(12)).toBe(12);
    expect(str("USNYC")).toBe("USNYC");
    expect(str(0)).toBe("0");
  });
});

describe("fall-back (a rejecting/timed-out run makes the fetcher throw — all-or-fall-back, D-01)", () => {
  it("uc3LiveFetcher rejects when an injected runAql rejects", async () => {
    const boom = () => Promise.reject(new Error("simulated AQL failure"));
    await expect(
      uc3LiveFetcher({ runAql: boom, ensureLoggedIn: async () => {} }),
    ).rejects.toThrow();
  });

  it("uc4LiveFetcher rejects when an injected runAql rejects", async () => {
    const boom = () => Promise.reject(new Error("simulated AQL failure"));
    await expect(
      uc4LiveFetcher({ runAql: boom, ensureLoggedIn: async () => {} }),
    ).rejects.toThrow();
  });

  it("a run that exceeds the budget rejects the fetcher", async () => {
    const slow = () => new Promise<Record<string, unknown>[]>(() => {}); // never resolves
    await expect(
      uc3LiveFetcher({ runAql: slow, ensureLoggedIn: async () => {}, budgetMs: 30 }),
    ).rejects.toThrow();
  });
});

describe("verbatim aql (staged server-assets/aql byte-identical to repo ../aql)", () => {
  const staged = (f: string) => join(AQL_DIR, f);
  const source = (f: string) => join(REPO_AQL_DIR, f);
  const FILES = [
    "uc3_chokepoint_share.aql",
    "uc3_reroute_impact.aql",
    "uc3_closure_unreachable.aql",
    "uc4_reroute_shortest_path.aql",
  ];
  const haveStaged = existsSync(staged(FILES[0]));

  for (const f of FILES) {
    it.skipIf(!haveStaged)(`${f}: staged == repo source`, () => {
      const a = readFileSync(staged(f), "utf8");
      const b = readFileSync(source(f), "utf8");
      expect(a).toBe(b);
    });
  }
});

describe("creds gate (hasLiveCreds reflects the four ARANGO_* vars)", () => {
  it("returns false unless ALL of URL/USERNAME/PASSWORD/DATABASE are set", () => {
    const KEYS = [
      "ARANGO_URL",
      "ARANGO_USERNAME",
      "ARANGO_PASSWORD",
      "ARANGO_DATABASE",
    ] as const;
    const saved: Record<string, string | undefined> = {};
    for (const k of KEYS) saved[k] = process.env[k];
    try {
      for (const k of KEYS) delete process.env[k];
      expect(hasLiveCreds()).toBe(false);
      process.env.ARANGO_URL = "https://example.test:8529";
      expect(hasLiveCreds()).toBe(false); // partial — still false
      process.env.ARANGO_USERNAME = "u";
      process.env.ARANGO_PASSWORD = "p";
      expect(hasLiveCreds()).toBe(false); // missing DATABASE
      process.env.ARANGO_DATABASE = "ofa";
      expect(hasLiveCreds()).toBe(true);
    } finally {
      for (const k of KEYS) {
        if (saved[k] === undefined) delete process.env[k];
        else process.env[k] = saved[k] as string;
      }
    }
  });
});
