// coords.ts — the SINGLE auditable server-side coordinate-join (DATA-07, D-08/D-09).
//
// Contract: the serve() seam calls enrichWithCoords(uc, envelope) once, and every
// downstream map consumer (10-02/10-03 render; P11/P12 live BigQuery/ArangoDB
// fetchers later) reads lat/lon off the SAME enriched envelope — this is the single
// store-agnostic contract. There is exactly one alias map (this file) bridging the
// golden keys to the WPI/chokepoint reference keys, so the join is auditable in one
// place rather than scattered across components.
//
// Server-only discipline (mirror serve.ts lines 14-18): this module reads node:fs
// from server-assets/coords/, so every importing module MUST run on the Node runtime.
// Coords are non-sensitive public geography, but the server-asset boundary is kept
// (read from server-assets/, never web/public/) so the secret-gate stays green.
//
// Null-island guard (DATA-07, hard requirement): a missing/non-finite coord resolves
// to null and is OMITTED by callers — an element is NEVER rendered at [0,0].

import { readFile } from "node:fs/promises";
import { join } from "node:path";

import type {
  Coord,
  Uc3Enriched,
  Uc3Envelope,
  Uc3PortEnriched,
  Uc3TransitShareEnriched,
  Uc4Enriched,
  Uc4Envelope,
  UcId,
} from "@/lib/golden-types";

// server-assets/coords lives at web/server-assets/coords — the destination
// copy-server-assets.mjs writes ports.json + chokepoints.csv to. Resolve from
// process.cwd() exactly like serve.ts's GOLDEN_DIR (runtime cwd is web/).
const COORDS_DIR = join(process.cwd(), "server-assets", "coords");

/** A keyed coordinate lookup table (ports.json shape / parsed chokepoints). */
export type CoordTable = Record<string, Coord>;

/** A chokepoint reference row carries a human display name in addition to coords. */
export interface ChokepointRef extends Coord {
  name: string;
}
export type ChokepointTable = Record<string, ChokepointRef>;

// ---- The SINGLE auditable alias bridge (D-09) --------------------------------
// Golden analytics emit bare chokepoint names (e.g. "GIBRALTAR") and golden
// LOCODEs (e.g. "CNSHA"); the reference files key on "CHK_*" and the WPI uses
// "CNSGH" for Shanghai. These two closed allow-lists are the only place those
// two namespaces are reconciled.

export const CHOKEPOINT_ALIAS: Record<string, string> = {
  SUEZ: "CHK_SUEZ",
  PANAMA: "CHK_PANAMA",
  MALACCA: "CHK_MALACCA",
  GIBRALTAR: "CHK_GIBRALTAR",
  HORMUZ: "CHK_HORMUZ",
  GOODHOPE: "CHK_GOODHOPE",
  BABELMANDEB: "CHK_BABMANDEB", // the non-obvious one (golden BABELMANDEB vs ref CHK_BABMANDEB)
};

export const PORT_ALIAS: Record<string, string> = {
  CNSHA: "CNSGH", // golden Shanghai LOCODE vs WPI Shanghai LOCODE
};

/**
 * Strip the golden "ports/" document-id prefix (RESEARCH Pitfall 7). The golden
 * reroute_impact_suez.origin/dest arrive as "ports/USNYC"; path-hop ports are bare.
 */
export function normKey(key: string): string {
  return key.startsWith("ports/") ? key.slice("ports/".length) : key;
}

/**
 * Resolve a golden key to a finite {lat,lon}, or null. Tries the chokepoint table
 * (via CHOKEPOINT_ALIAS) first, then the port table (via PORT_ALIAS). The null-island
 * guard: a missing or non-finite coord returns null so callers OMIT the element —
 * never [0,0].
 */
export function coordFor(
  key: string,
  ports: CoordTable,
  chk: ChokepointTable,
): Coord | null {
  const k = normKey(key);
  const c = chk[CHOKEPOINT_ALIAS[k] ?? k] ?? ports[PORT_ALIAS[k] ?? k];
  return c && Number.isFinite(c.lat) && Number.isFinite(c.lon)
    ? { lat: c.lat, lon: c.lon }
    : null;
}

/**
 * Resolve a chokepoint's display name (e.g. "Strait of Gibraltar") via the alias
 * bridge into the parsed chokepoints.csv. Returns null if the name is absent.
 */
export function nameFor(key: string, chk: ChokepointTable): string | null {
  const k = normKey(key);
  const ref = chk[CHOKEPOINT_ALIAS[k] ?? k];
  return ref && ref.name ? ref.name : null;
}

// ---- Loaders (server-only) ---------------------------------------------------

/** Read + parse the build-emitted golden-keyed port coord lookup. */
export async function loadPorts(): Promise<CoordTable> {
  const raw = await readFile(join(COORDS_DIR, "ports.json"), "utf8");
  return JSON.parse(raw) as CoordTable;
}

/**
 * Parse the build-copied chokepoints.csv (header: key,name,lat,lon) into a table
 * keyed by the CHK_* key. The display name lives on each row.
 */
export async function loadChokepoints(): Promise<ChokepointTable> {
  const raw = await readFile(join(COORDS_DIR, "chokepoints.csv"), "utf8");
  const lines = raw.split(/\r?\n/).filter((l) => l.length > 0);
  const header = lines[0].split(",").map((h) => h.trim());
  const keyIdx = header.indexOf("key");
  const nameIdx = header.indexOf("name");
  const latIdx = header.indexOf("lat");
  const lonIdx = header.indexOf("lon");
  const table: ChokepointTable = {};
  for (let i = 1; i < lines.length; i++) {
    const cols = lines[i].split(",");
    const key = (cols[keyIdx] ?? "").trim();
    if (!key) continue;
    const lat = Number(cols[latIdx]);
    const lon = Number(cols[lonIdx]);
    table[key] = { name: (cols[nameIdx] ?? "").trim(), lat, lon };
  }
  return table;
}

// ---- The pure join -----------------------------------------------------------

/**
 * Derive the authoritative UC3 port set from the envelope itself: origin + dest +
 * every port appearing in reroute_impact_suez.disabled_lanes (split each "A__B"
 * pair, strip the "ports/" prefix), de-duplicated. VERIFIED against uc3.golden.json
 * this yields exactly {USNYC, CNSHA, JPTYO, KRPUS, USSAV} — USLAX is NOT in the uc3
 * envelope and is therefore excluded from the UC3 render set.
 */
function deriveUc3PortKeys(env: Uc3Envelope): string[] {
  const keys = new Set<string>();
  keys.add(normKey(env.origin));
  keys.add(normKey(env.dest));
  for (const pair of env.reroute_impact_suez.disabled_lanes) {
    for (const half of pair.split("__")) {
      const k = normKey(half);
      if (k) keys.add(k);
    }
  }
  return [...keys];
}

/**
 * Pure, store-agnostic coordinate join. Given a UC id and its base envelope,
 * returns the enriched envelope the map renders against. Null-coord elements are
 * dropped (omitted from the array) so nothing renders at null island.
 *
 * Overloaded so callers get a precisely-typed enriched envelope per UC.
 */
export async function enrichWithCoords(
  uc: "uc3",
  envelope: Uc3Envelope,
): Promise<Uc3Enriched>;
export async function enrichWithCoords(
  uc: "uc4",
  envelope: Uc4Envelope,
): Promise<Uc4Enriched>;
export async function enrichWithCoords<U extends UcId>(
  uc: U,
  envelope: unknown,
): Promise<unknown>;
export async function enrichWithCoords(
  uc: UcId,
  envelope: unknown,
): Promise<unknown> {
  // UC1/UC2 are tabular OLAP envelopes with no geography — pass through untouched.
  if (uc !== "uc3" && uc !== "uc4") return envelope;

  const [ports, chk] = await Promise.all([loadPorts(), loadChokepoints()]);

  if (uc === "uc3") {
    const env = envelope as Uc3Envelope;

    // (1) Attach name + lat/lon to each transit_share chokepoint; drop any that
    //     fail to resolve a coord (the enriched type requires present coords).
    const transit_share: Uc3TransitShareEnriched[] = [];
    for (const ts of env.transit_share) {
      const coord = coordFor(ts.chokepoint, ports, chk);
      const name = nameFor(ts.chokepoint, chk);
      if (coord && name) {
        transit_share.push({ ...ts, name, lat: coord.lat, lon: coord.lon });
      }
    }

    // (2) Build the explicit derived UC3 ports[] (origin+dest+disabled_lanes);
    //     omit any port whose coord is null (never [0,0]).
    const portsOut: Uc3PortEnriched[] = [];
    for (const unlocode of deriveUc3PortKeys(env)) {
      const coord = coordFor(unlocode, ports, chk);
      if (coord) {
        portsOut.push({ unlocode, lat: coord.lat, lon: coord.lon });
      }
    }

    const enriched: Uc3Enriched = {
      ...env,
      transit_share,
      ports: portsOut,
    };
    return enriched;
  }

  // uc4 — attach lat/lon to each baseline_path + reroute_path hop; drop null-coord hops.
  const env = envelope as Uc4Envelope;
  const enrichHops = (hops: Uc4Envelope["baseline_path"]) => {
    const out: Uc4Enriched["baseline_path"] = [];
    for (const hop of hops) {
      const coord = coordFor(hop.port, ports, chk);
      if (coord) out.push({ ...hop, lat: coord.lat, lon: coord.lon });
    }
    return out;
  };

  const enriched: Uc4Enriched = {
    ...env,
    baseline_path: enrichHops(env.baseline_path),
    reroute_path: enrichHops(env.reroute_path),
  };
  return enriched;
}
