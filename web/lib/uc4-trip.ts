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
 * parallel array of per-point cumulative-`leg_hours` timestamps. `path.length` ALWAYS equals
 * `timestamps.length`.
 *
 * Two modes, keyed per hop on whether it carries baked sea-route `waypoints` (REQ-14-4):
 *
 *  - Hop WITHOUT waypoints (legacy): contributes ONE point at the hop's [lon,lat] with
 *    timestamp = the cumulative sum of `leg_hours` up to and including this hop. (So the
 *    first point lands at its own leg_hours and the last is the total trip hours — the
 *    pre-14-04 behavior, unchanged.)
 *
 *  - Hop WITH waypoints: contributes ONE point per polyline point. The hop's `leg_hours`
 *    (the duration of the leg ARRIVING at this hop) is interpolated LINEARLY across that
 *    leg's `n` waypoint points: point j (0-indexed) lands at `t_start + leg_hours*(j+1)/n`,
 *    where `t_start` is the cumulative time before this leg. The last waypoint therefore
 *    lands exactly on the leg boundary (`t_start + leg_hours`) — no duplicate boundary
 *    timestamp — and the running cumulative advances by exactly `leg_hours`. Timestamps are
 *    monotonic non-decreasing across the whole multi-waypoint path.
 *
 * The timestamps stay HOUR-SCALE — the cumulative sum of `leg_hours` (0..~480 for the
 * project's paths), NEVER epoch-ms (RESEARCH Pitfall 3: TripsLayer carries time in 32-bit
 * floats, so epoch-magnitude values garble the animation). An empty hop list yields empty
 * arrays — no crash.
 */
export function toTrip(hops: Uc4PathHopEnriched[]): {
  path: [number, number][];
  timestamps: number[];
} {
  let t = 0;
  const path: [number, number][] = [];
  const timestamps: number[] = [];
  for (const h of hops) {
    const wps = h.waypoints;
    if (wps && wps.length > 0) {
      const n = wps.length;
      const tStart = t;
      for (let j = 0; j < n; j++) {
        path.push([wps[j][0], wps[j][1]]);
        // Linear interpolation across the leg: point j lands at tStart + leg_hours*(j+1)/n,
        // so the final point lands exactly on the leg boundary.
        timestamps.push(tStart + (h.leg_hours * (j + 1)) / n);
      }
      t = tStart + h.leg_hours;
    } else {
      // Legacy hop-only behavior: one point at the hop, timestamp = cumulative leg_hours.
      t += h.leg_hours;
      path.push([h.lon, h.lat]);
      timestamps.push(t);
    }
  }
  return { path, timestamps };
}
