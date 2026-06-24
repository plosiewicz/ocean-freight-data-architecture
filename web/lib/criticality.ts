// criticality.ts — server-only reader for the frozen betweenness-criticality golden
// (MAP-04), plus a pure transit-share/criticality join helper.
//
// The criticality scores live in a SEPARATE frozen artifact (criticality.golden.json,
// produced by scripts/freeze_criticality.py and committed by Plan 03) — they are NOT
// part of the serve() UC envelope (deliberately out of scope, RESEARCH §Open Q1). The
// UC3 page reads this file server-side, mirroring serve.ts's GOLDEN_DIR node:fs pattern,
// and passes the resulting map into rankChokepoints to pair the FROZEN criticality with
// the PRESENT transit_share_pct from the (already-fetched) UC3 envelope.
//
// Server-only discipline (mirror serve.ts lines 14-18 / coords.ts lines 11-13): this
// module reads node:fs from server-assets/golden/, so every importing module MUST run on
// the Node runtime. The file is credential-free (verified by Plan 03's secret-gate), so
// it carries only public betweenness scores — but the server-asset boundary is kept.
//
// Key-space note: both transit_share[].chokepoint (uc3.golden.json) and
// criticality_by_key[]._key (criticality.golden.json) use the SAME bare uppercase
// chokepoint name space (e.g. "GIBRALTAR", "PANAMA", "SUEZ") — VERIFIED against the
// committed files. No CHK_/UN-LOCODE normalization is needed (unlike the coords.ts join,
// which bridges golden names to the CHK_* reference keys). The join is therefore a direct
// key lookup. The Task-1 alignment guard test asserts this holds against the real data so
// a future key-space drift fails loudly rather than silently degrading to null criticality.

import { readFileSync } from "node:fs";
import { join } from "node:path";

import type { Uc3TransitShare } from "@/lib/golden-types";

// server-assets/golden lives at web/server-assets/golden — the same dir serve.ts reads
// the UC envelopes from (copy-server-assets.mjs carries data/golden/ here at build).
// Resolve from process.cwd() exactly like serve.ts's GOLDEN_DIR (runtime cwd is web/).
const GOLDEN_DIR = join(process.cwd(), "server-assets", "golden");

/** One frozen criticality row: a chokepoint _key and its betweenness criticality score. */
interface CriticalityRow {
  _key: string;
  criticality: number;
}

/** The criticality.golden.json body shape we consume (other freeze fields are ignored). */
interface CriticalityGolden {
  criticality_by_key: CriticalityRow[];
  most_critical: string;
}

/**
 * A transit_share row joined to its frozen criticality. `criticality` is `null` when the
 * chokepoint key is genuinely absent from the frozen golden (e.g. a chokepoint that was
 * never scored) — this null path is reachable ONLY by a genuinely-missing key, never by a
 * key-space mismatch (the two key spaces are verified-aligned; see the module note).
 */
export type RankedChokepoint = Uc3TransitShare & { criticality: number | null };

/**
 * Read the frozen criticality golden server-side and return a Map of chokepoint
 * `_key` -> `criticality`. Reads synchronously via node:fs from the same GOLDEN_DIR
 * convention serve.ts uses. Server-only (Node runtime).
 */
export function readCriticality(): Map<string, number> {
  const raw = readFileSync(join(GOLDEN_DIR, "criticality.golden.json"), "utf8");
  const golden = JSON.parse(raw) as CriticalityGolden;
  const map = new Map<string, number>();
  for (const { _key, criticality } of golden.criticality_by_key) {
    map.set(_key, criticality);
  }
  return map;
}

/**
 * Pure join helper: pair each transit_share row (keyed by its `chokepoint`) with the
 * frozen criticality (keyed by `_key`), returning rows that carry BOTH metrics, sorted by
 * `transit_share_pct` DESCENDING (the panel's primary ranking axis — "which chokepoint
 * carries the most lanes"). A chokepoint with no matching criticality key gets a `null`
 * criticality but still appears, ranked by its transit share (no crash, no drop).
 *
 * Stable for equal transit shares (sort is non-mutating over a copy; ties retain input
 * order via the toSorted-equivalent map+sort below).
 */
export function rankChokepoints(
  transitShare: Uc3TransitShare[],
  criticalityMap: Map<string, number>,
): RankedChokepoint[] {
  return transitShare
    .map((row) => {
      const c = criticalityMap.get(row.chokepoint);
      return { ...row, criticality: c === undefined ? null : c };
    })
    .sort((a, b) => b.transit_share_pct - a.transit_share_pct);
}
