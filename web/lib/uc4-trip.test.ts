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

// REQ-14-4 multi-waypoint coverage: when hops carry baked sea-route `waypoints`, toTrip
// emits ONE timestamp PER POLYLINE POINT (not per hop), interpolating each leg's
// leg_hours linearly across that leg's waypoint count. The hour-scale invariant (Pitfall 3)
// must survive — every timestamp stays far below epoch-ms magnitude.
const WP_HOPS: Uc4PathHopEnriched[] = [
  // Origin leg: 2 polyline points, leg_hours 100.
  {
    port: "USNYC",
    leg_hours: 100,
    lon: -74.0,
    lat: 40.7,
    waypoints: [
      [-74.0, 40.7],
      [-80.0, 35.0],
    ],
  },
  // Second leg: 3 polyline points, leg_hours 300.
  {
    port: "CNSHA",
    leg_hours: 300,
    lon: 121.8,
    lat: 31.2,
    waypoints: [
      [-90.0, 30.0],
      [60.0, 20.0],
      [121.8, 31.2],
    ],
  },
];

describe("toTrip multi-waypoint (REQ-14-4)", () => {
  it("emits one [lon,lat] path point and one timestamp per polyline point (lengths equal)", () => {
    const { path, timestamps } = toTrip(WP_HOPS);
    // 2 + 3 = 5 polyline points across both legs.
    expect(path.length).toBe(5);
    expect(timestamps.length).toBe(path.length);
    // The path is the concatenation of every leg's waypoints, in [lon,lat] order.
    expect(path).toEqual([
      [-74.0, 40.7],
      [-80.0, 35.0],
      [-90.0, 30.0],
      [60.0, 20.0],
      [121.8, 31.2],
    ]);
  });

  it("interpolates each leg's leg_hours linearly across that leg's points and is monotonic", () => {
    const { timestamps } = toTrip(WP_HOPS);
    // Monotonic non-decreasing across the whole multi-waypoint path.
    for (let i = 1; i < timestamps.length; i++) {
      expect(timestamps[i]).toBeGreaterThanOrEqual(timestamps[i - 1]);
    }
    // Rule: each leg's point j (0-indexed, n points, duration d from cumulative t_start)
    // lands at t_start + d*(j+1)/n — points end exactly on the leg boundary, no duplicate
    // boundary timestamp. Leg 1: t_start=0, d=100, n=2 -> 50,100. Leg 2: t_start=100,
    // d=300, n=3 -> 200,300,400. Final point = total trip hours (100+300=400).
    expect(timestamps).toEqual([50, 100, 200, 300, 400]);
    expect(timestamps[timestamps.length - 1]).toBe(400);
  });

  it("keeps multi-waypoint timestamps hour-scale (no epoch-ms magnitude)", () => {
    const { timestamps } = toTrip(WP_HOPS);
    expect(Math.max(...timestamps)).toBeLessThan(5000);
  });

  it("handles a single-point waypoint leg without crashing (point lands at the leg end)", () => {
    const single: Uc4PathHopEnriched[] = [
      { port: "AAA", leg_hours: 50, lon: 1, lat: 1, waypoints: [[1, 1]] },
    ];
    const { path, timestamps } = toTrip(single);
    expect(path).toEqual([[1, 1]]);
    expect(timestamps).toEqual([50]);
  });
});
