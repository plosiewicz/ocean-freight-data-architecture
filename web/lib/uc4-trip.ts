// uc4-trip — the pure cumulative-timestamp helper for the UC4 deck.gl TripsLayer (MAP-06 /
// D-04). It is the timestamp analog of uc4-map-loader's toSegments: where toSegments turns
// an ordered hop list into geometry, toTrip turns it into the { path, timestamps } pair a
// TripsLayer consumes.
//
// Extracted to lib/ (NOT inlined in the WebGL component) so it is unit-testable without
// WebGL and runs in the existing vitest `lib/**/*.test.ts` glob.
//
// CRITICAL (RESEARCH Pitfall 3): the timestamps are the running cumulative sum of
// `leg_hours` — small hour-scale numbers (0..~480 for the project's paths). They must NEVER
// be epoch-ms: TripsLayer carries time in 32-bit floats internally, so epoch-magnitude
// values lose precision and garble the animation. Hour-scale keeps every value far inside
// 32-bit-float-exact integer range.

import type { Uc4PathHopEnriched } from "@/lib/golden-types";

/**
 * Turn an ordered enriched hop list into the TripsLayer datum shape: a [lon,lat] path and a
 * parallel array of per-point cumulative-`leg_hours` timestamps.
 *
 * The timestamp for hop i is the sum of `leg_hours` for hops 0..i (so the first point lands
 * at its own leg_hours and the last point is the total trip hours). An empty hop list yields
 * empty arrays — no crash.
 */
export function toTrip(hops: Uc4PathHopEnriched[]): {
  path: [number, number][];
  timestamps: number[];
} {
  let t = 0;
  const path: [number, number][] = [];
  const timestamps: number[] = [];
  for (const h of hops) {
    t += h.leg_hours;
    path.push([h.lon, h.lat]);
    timestamps.push(t);
  }
  return { path, timestamps };
}
