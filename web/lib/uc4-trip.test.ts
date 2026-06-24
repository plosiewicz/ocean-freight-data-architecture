// uc4-trip.test.ts — MAP-06 Wave-0 unit coverage for the pure toTrip helper.
//
// toTrip is the timestamp analog of uc4-map-loader's toSegments: it turns an enriched
// hop list into the { path, timestamps } shape TripsLayer consumes. Extracting it to lib/
// (instead of inlining in the WebGL component) keeps it unit-testable without WebGL and
// runs in the existing vitest `lib/**/*.test.ts` glob (node env, no jsdom).
//
// CRITICAL (RESEARCH Pitfall 3): timestamps are cumulative leg_hours — small hour-scale
// numbers (0..~480), NEVER epoch-ms. 32-bit float precision loss garbles TripsLayer if the
// magnitude is epoch-scale, so Test 3 guards the magnitude explicitly.

import { describe, expect, it } from "vitest";

import type { Uc4PathHopEnriched } from "@/lib/golden-types";
import { toTrip } from "@/lib/uc4-trip";

// A representative enriched path (USNYC → USLAX → CNSHA, project hour-scale legs).
const HOPS: Uc4PathHopEnriched[] = [
  { port: "USNYC", leg_hours: 120, lon: -74.0, lat: 40.7 },
  { port: "USLAX", leg_hours: 140, lon: -118.2, lat: 33.7 },
  { port: "CNSHA", leg_hours: 220, lon: 121.8, lat: 31.2 },
];

describe("toTrip", () => {
  it("returns the [lon,lat] path and per-point cumulative-leg_hours timestamps", () => {
    const { path, timestamps } = toTrip(HOPS);
    expect(path).toEqual([
      [-74.0, 40.7],
      [-118.2, 33.7],
      [121.8, 31.2],
    ]);
    // cumulative sum: 120, 120+140=260, 260+220=480
    expect(timestamps).toEqual([120, 260, 480]);
  });

  it("produces strictly monotonic non-decreasing timestamps starting at the first leg_hours", () => {
    const { timestamps } = toTrip(HOPS);
    expect(timestamps[0]).toBe(HOPS[0].leg_hours);
    for (let i = 1; i < timestamps.length; i++) {
      expect(timestamps[i]).toBeGreaterThanOrEqual(timestamps[i - 1]);
    }
  });

  it("keeps timestamps small hour-scale (no epoch-ms magnitude)", () => {
    const { timestamps } = toTrip(HOPS);
    const max = Math.max(...timestamps);
    // Project paths are hour-scale (a few hundred). Epoch-ms would be ~1.7e12 — far above
    // this ceiling. A few-thousand bound proves the helper never emits epoch magnitudes.
    expect(max).toBeLessThan(5000);
  });

  it("returns empty path + empty timestamps for an empty hop list (no crash)", () => {
    const { path, timestamps } = toTrip([]);
    expect(path).toEqual([]);
    expect(timestamps).toEqual([]);
  });
});
