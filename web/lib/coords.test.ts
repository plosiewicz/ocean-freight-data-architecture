// coords.test.ts — DATA-07 unit coverage for the highest-risk surface of Phase 10:
// the alias bridge, the null-island guard, and the enrichWithCoords JOIN contract.
//
// Two layers:
//   (1) Lookup unit tests — every golden port + chokepoint resolves through the
//       alias maps to finite coords; CNSHA->CNSGH, BABELMANDEB->CHK_BABMANDEB, the
//       "ports/" prefix normalizes, a bogus key returns null (never [0,0]), and
//       GIBRALTAR resolves the display name "Strait of Gibraltar" (BLOCKER 2).
//   (2) JOIN contract test (WARNING 5) — enrichWithCoords('uc3', <real golden>)
//       yields the actual render contract: ports[] = exactly
//       {USNYC, CNSHA, JPTYO, KRPUS, USSAV} (USLAX absent) each with finite coords,
//       and every transit_share chokepoint carries a non-empty name + finite coords.
//
// These read the BUILD-EMITTED server-assets/coords/ assets, so `npm run prebuild`
// must have run first (the verify command chains it).

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import {
  CHOKEPOINT_ALIAS,
  PORT_ALIAS,
  coordFor,
  enrichWithCoords,
  loadChokepoints,
  loadPorts,
  nameFor,
  normKey,
  type ChokepointTable,
  type CoordTable,
} from "@/lib/coords";
import type { Uc3Envelope } from "@/lib/golden-types";

const COORDS_DIR = join(process.cwd(), "server-assets", "coords");
const GOLDEN_DIR = join(process.cwd(), "server-assets", "golden");

function readUc3Golden(): Uc3Envelope {
  const raw = readFileSync(join(GOLDEN_DIR, "uc3.golden.json"), "utf8");
  return JSON.parse(raw) as Uc3Envelope;
}

describe("coords lookup layer (DATA-07 alias + null-island guard)", () => {
  let ports: CoordTable;
  let chk: ChokepointTable;

  // Load the build-emitted lookups once.
  it("loads the build-emitted ports.json and chokepoints.csv", async () => {
    ports = await loadPorts();
    chk = await loadChokepoints();
    expect(Object.keys(ports).length).toBeGreaterThanOrEqual(6);
    expect(Object.keys(chk).length).toBeGreaterThanOrEqual(7);
  });

  it("resolves all 6 golden ports to finite coords", async () => {
    const p = await loadPorts();
    const c = await loadChokepoints();
    for (const key of ["USNYC", "CNSHA", "USLAX", "JPTYO", "KRPUS", "USSAV"]) {
      const coord = coordFor(key, p, c);
      expect(coord, `port ${key}`).not.toBeNull();
      expect(Number.isFinite(coord!.lat)).toBe(true);
      expect(Number.isFinite(coord!.lon)).toBe(true);
    }
  });

  it("resolves all 7 chokepoints via CHOKEPOINT_ALIAS, including BABELMANDEB->CHK_BABMANDEB", async () => {
    const p = await loadPorts();
    const c = await loadChokepoints();
    for (const key of [
      "SUEZ",
      "PANAMA",
      "MALACCA",
      "GIBRALTAR",
      "HORMUZ",
      "GOODHOPE",
      "BABELMANDEB",
    ]) {
      const coord = coordFor(key, p, c);
      expect(coord, `chokepoint ${key}`).not.toBeNull();
      expect(Number.isFinite(coord!.lat)).toBe(true);
      expect(Number.isFinite(coord!.lon)).toBe(true);
    }
    expect(CHOKEPOINT_ALIAS.BABELMANDEB).toBe("CHK_BABMANDEB");
  });

  it("resolves CNSHA through PORT_ALIAS to the WPI CNSGH coordinate (~31.22, 121.50)", async () => {
    const p = await loadPorts();
    const c = await loadChokepoints();
    expect(PORT_ALIAS.CNSHA).toBe("CNSGH");
    const coord = coordFor("CNSHA", p, c);
    expect(coord).not.toBeNull();
    expect(coord!.lat).toBeCloseTo(31.22, 1);
    expect(coord!.lon).toBeCloseTo(121.5, 1);
  });

  it("normalizes a 'ports/' prefixed key and returns null for a bogus key (never [0,0])", async () => {
    const p = await loadPorts();
    const c = await loadChokepoints();
    expect(normKey("ports/USNYC")).toBe("USNYC");
    const prefixed = coordFor("ports/USNYC", p, c);
    const bare = coordFor("USNYC", p, c);
    expect(prefixed).not.toBeNull();
    expect(prefixed).toEqual(bare);
    expect(coordFor("ZZZZZ", p, c)).toBeNull();
  });

  it("resolves GIBRALTAR to the display name 'Strait of Gibraltar' (BLOCKER 2)", async () => {
    const c = await loadChokepoints();
    expect(nameFor("GIBRALTAR", c)).toBe("Strait of Gibraltar");
  });
});

describe("enrichWithCoords JOIN contract (WARNING 5 — the render contract 10-02 reads)", () => {
  it("uc3: ports[] = {USNYC,CNSHA,JPTYO,KRPUS,USSAV} (USLAX absent) with finite coords", async () => {
    const enriched = await enrichWithCoords("uc3", readUc3Golden());
    const got = enriched.ports.map((p) => p.unlocode).sort();
    expect(got).toEqual(["CNSHA", "JPTYO", "KRPUS", "USNYC", "USSAV"]);
    expect(got).not.toContain("USLAX");
    for (const p of enriched.ports) {
      expect(Number.isFinite(p.lat), `${p.unlocode}.lat`).toBe(true);
      expect(Number.isFinite(p.lon), `${p.unlocode}.lon`).toBe(true);
    }
  });

  it("uc3: every transit_share chokepoint carries a non-empty name + finite coords", async () => {
    const enriched = await enrichWithCoords("uc3", readUc3Golden());
    expect(enriched.transit_share.length).toBeGreaterThan(0);
    for (const ts of enriched.transit_share) {
      expect(ts.name, `chokepoint ${ts.chokepoint} name`).toBeTruthy();
      expect(Number.isFinite(ts.lat)).toBe(true);
      expect(Number.isFinite(ts.lon)).toBe(true);
    }
    // The Gibraltar row in particular reads the display name, not the raw key.
    const gib = enriched.transit_share.find((t) => t.chokepoint === "GIBRALTAR");
    expect(gib?.name).toBe("Strait of Gibraltar");
  });
});
