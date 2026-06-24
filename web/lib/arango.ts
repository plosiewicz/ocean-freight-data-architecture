// arango.ts — the live ArangoDB LiveFetchers for UC3/UC4 (DATA-03). SERVER-ONLY:
// imported only by Node-runtime route handlers. Phase 12 is the graph twin of Phase 11's
// web/lib/bigquery.ts — same structural seam, with two hard parts beyond it:
//   (a) the multi-query assembly — UC3 = 4 AQL runs assembled into one envelope, UC4 = 2
//       runs — fired in PARALLEL under ONE wall-clock budget, with all-or-fall-back: ANY
//       run fail/timeout/JWT-fail throws, so serve() falls back to golden (D-01).
//   (b) the Python -> TS assembly-math port (rounding / sort / leg-sum / closure-total
//       SUM, the ports/-prefixed UC4 endpoints + bare-LOCODE UC3 top-level, the
//       golden-pinned 12-element disabled_lanes) reproducing the committed golden
//       field-for-field. Source of truth: analytics/snapshot_uc.py.
//
// Trust-boundary discipline (T-12-02..T-12-06):
//   - The ARANGO_* creds + the issued JWT are read from UN-PREFIXED server env vars
//     (never NEXT_PUBLIC_), used only inside this server module; they never reach the
//     client bundle, the logs, or the HTTP response (the envelope carries no AQL body
//     and no credential material).
//   - On error we log ONLY err.message — never the arangojs error object (which can carry
//     the request config: a creds-embedded URL or the bearer token), never the creds.
//   - AQL is read VERBATIM from the build-time-staged server-assets/aql/ allow-list and
//     run via db.query({ query, bindVars }) — never the `aql` template tag, never string
//     concatenation (DATA-03 / ASVS V5 / threat T-12-04).
//   - TLS stays verified: NEVER rejectUnauthorized:false (mirror Python verify_override=True).
//   - The whole Promise.all batch is wall-clock-bounded so serve()'s catch falls back to
//     golden before the Vercel function ceiling (T-12-06).

import { readFile } from "node:fs/promises";
import { join } from "node:path";

import { Database } from "arangojs";

import type {
  Uc3ClosureGibraltar,
  Uc3Envelope,
  Uc3RerouteImpactSuez,
  Uc3TransitShare,
  Uc4Envelope,
  Uc4PathHop,
} from "@/lib/golden-types";

/**
 * Single wall-clock knob bounding the whole live attempt (D-01, shared with bigquery.ts).
 * Default 7000ms is conservative under the ~10s Hobby ceiling; widening for Pro/Fluid is a
 * one-line env change.
 */
export const LIVE_QUERY_TIMEOUT_MS = Number(process.env.LIVE_QUERY_TIMEOUT_MS ?? 7000);

// server-assets/aql lives at web/server-assets/aql — the destination copy-server-assets.mjs
// writes to. Runtime cwd is web/, so process.cwd()-relative resolution lands there. Mirror
// bigquery.ts's SQL_DIR, swapping "sql" -> "aql".
const AQL_DIR = join(process.cwd(), "server-assets", "aql");

/**
 * D-05/D-06 gate: live querying is attempted only when all four ARANGO_* creds are present.
 * ARANGO_GRAPH (ocean_network) is NOT required by these route-only AQL queries.
 */
export function hasLiveCreds(): boolean {
  return Boolean(
    process.env.ARANGO_URL &&
      process.env.ARANGO_USERNAME &&
      process.env.ARANGO_PASSWORD &&
      process.env.ARANGO_DATABASE,
  );
}

// ---- Module-scoped singleton client + lazy JWT + retry-once-on-401 ----
// Port of lib/arango_client.py get_db/get_jwt/request_with_retry. The singleton is lazy
// (created at call time so a missing cred throws into serve()'s catch, not at import).

let _db: Database | null = null;
let _loggedIn = false;

function getDb(): Database {
  if (_db) return _db;
  const url = process.env.ARANGO_URL;
  const databaseName = process.env.ARANGO_DATABASE;
  if (!url || !databaseName) throw new Error("ARANGO_URL/ARANGO_DATABASE not set");
  // TLS always on (https url). NEVER rejectUnauthorized:false — mirror Python
  // verify_override=True (arango_client.py); a TLS error means a wrong URL and must surface.
  _db = new Database({ url, databaseName });
  return _db;
}

/** Lazy login: exchanges creds for a JWT (arangojs auto-stores it), guarded by a flag. */
async function ensureLoggedIn(): Promise<void> {
  if (_loggedIn) return;
  const u = process.env.ARANGO_USERNAME;
  const p = process.env.ARANGO_PASSWORD;
  if (!u || !p) throw new Error("ARANGO_USERNAME/ARANGO_PASSWORD not set");
  await getDb().login(u, p);
  _loggedIn = true;
}

/** Detect a 401 (stale-JWT) across the shapes arangojs surfaces it in. */
function is401(err: unknown): boolean {
  if (typeof err !== "object" || err === null) return false;
  const e = err as { code?: number; response?: { status?: number; statusCode?: number } };
  return (
    e.code === 401 ||
    e.response?.status === 401 ||
    e.response?.statusCode === 401
  );
}

/**
 * Run the VERBATIM on-disk AQL string against the cluster, bounded by the per-query timeout.
 * On a 401 (the ~1h cluster JWT expired on a warm instance) re-auth ONCE and retry ONCE
 * (port of arango_client.py request_with_retry); any other error bubbles. NEVER the `aql`
 * template tag, NEVER string concat (DATA-03 / T-12-04).
 */
async function runAql<T = Record<string, unknown>>(
  query: string,
  bindVars: Record<string, unknown>,
): Promise<T[]> {
  const db = getDb();
  try {
    const cursor = await db.query({ query, bindVars }, { timeout: LIVE_QUERY_TIMEOUT_MS });
    return (await cursor.all()) as T[];
  } catch (err) {
    if (is401(err)) {
      _loggedIn = false;
      await ensureLoggedIn();
      const cursor = await db.query({ query, bindVars }, { timeout: LIVE_QUERY_TIMEOUT_MS });
      return (await cursor.all()) as T[];
    }
    throw err;
  }
}

/** Read a versioned AQL file VERBATIM from the staged server-assets dir (DATA-03, T-12-04). */
async function readAql(file: string): Promise<string> {
  return readFile(join(AQL_DIR, file), "utf8");
}

/**
 * Wall-clock budget wrapper (port of bigquery.ts runBounded, extended to wrap the whole
 * Promise.all batch). Promise.race against a setTimeout reject; clearTimeout in finally
 * avoids a dangling timer holding the function open. The losing batch gets a .catch(()=>{})
 * so a late rejection after the timeout wins is not an unhandled-rejection warning (WR-01).
 */
function withBudget<T>(work: Promise<T>, budgetMs: number = LIVE_QUERY_TIMEOUT_MS): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<never>((_resolve, reject) => {
    timer = setTimeout(
      () => reject(new Error(`live query exceeded ${budgetMs}ms`)),
      budgetMs,
    );
  });
  // Swallow a late rejection of the work batch once the timeout has already won the race.
  work.catch(() => {});
  return Promise.race([work, timeout]).finally(() => {
    if (timer) clearTimeout(timer);
  });
}

// ---- Ported constants from analytics/snapshot_uc.py (verbatim values). ----
const DEMO_ORIGIN = "USNYC"; // snapshot_uc.py:42
const DEMO_DEST = "CNSHA"; // snapshot_uc.py:43
const REROUTE_IMPACT_CHOKEPOINT = "SUEZ"; // snapshot_uc.py:46
const FRAGMENTING_CHOKEPOINT = "GIBRALTAR"; // snapshot_uc.py:47
const OPEN_SENTINEL = "__NONE_OPEN__"; // snapshot_uc.py:51
const ORIGIN_ID = "ports/USNYC"; // UC4 + reroute_impact endpoint form (snapshot_uc.py:133)
const DEST_ID = "ports/CNSHA"; // snapshot_uc.py:134
const MAXHOPS = 200; // uc3_closure_unreachable.aql @maxhops
// The exact 12-element SUEZ disabled-lanes list, ORDER-SENSITIVE (golden-pinned, Pitfall 4).
// Equivalent to disabled_lane_keys_for_chokepoint(LANES+US_US_LANES, rule, "SUEZ") in
// snapshot_uc.py:135 — reproduce the SAME order; the golden-parity test guards it.
const SUEZ_DISABLED_LANES: string[] = [
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
];

// ---- Coercers that THROW on malformed rows (WR-02/03/04 / Pitfall 3). ----
// bigquery.ts's num(v)=Number(v) silently yields NaN — DO NOT copy that. THROW instead so a
// corrupt row triggers all-or-fall-back to golden rather than a corrupted envelope.

/**
 * Coerce to a finite number, else THROW (never NaN, never a silent 0). null/undefined are
 * rejected explicitly because Number(null)===0 / Number("")===0 would otherwise mask a
 * missing/empty row field as a real zero (WR-02/03/04 lesson, Pitfall 3).
 */
export function num(v: unknown): number {
  if (v === null || v === undefined || v === "") {
    throw new Error("malformed numeric row field");
  }
  const n = Number(v);
  if (!Number.isFinite(n)) throw new Error("malformed numeric row field");
  return n;
}

/** Coerce to a string, else THROW on null/undefined (never null/"undefined"). */
export function str(v: unknown): string {
  if (v === null || v === undefined) throw new Error("malformed string row field");
  return String(v);
}

/** Python round(x, 12) — JS has no built-in; apply at the SAME points Python does (Pitfall 1). */
function round12(x: number): number {
  return Number(x.toFixed(12));
}

function sum(xs: number[]): number {
  return xs.reduce((s, x) => s + x, 0);
}

/** _total_reachable (snapshot_uc.py:54-56): SUM reachable_count across closure rows (Pitfall 5). */
function totalReachable(rows: Record<string, unknown>[]): number {
  return rows.reduce((s, r) => s + num(r.reachable_count), 0);
}

// ---- The AQL-shaped row-list parts the assemblers consume (hermetic-testable). ----
export interface Uc3Parts {
  share: Record<string, unknown>[];
  impactReroute: Record<string, unknown>[];
  impactBaseline: Record<string, unknown>[];
  openRows: Record<string, unknown>[];
  gibRows: Record<string, unknown>[];
}

export interface Uc4Parts {
  baselineRows: Record<string, unknown>[];
  rerouteRows: Record<string, unknown>[];
}

/**
 * Port of snapshot_uc.py::snapshot_uc3 (lines 59-119), field-for-field. The math the AQL
 * does NOT do (and so must live here): sort transit_share by chokepoint, round12 the pct,
 * sum each impact leg list for hours/delta, and SUM reachable_count across closure rows.
 */
export function assembleUc3(parts: Uc3Parts): Uc3Envelope {
  const transit_share: Uc3TransitShare[] = parts.share
    .map((r) => ({
      chokepoint: str(r.chokepoint ?? r._key), // snapshot_uc.py:71
      transiting_lanes: num(r.transiting_lanes), // :72
      total_lanes: num(r.total_lanes), // :73
      transit_share_pct: round12(num(r.transit_share_pct)), // :74-78
    }))
    .sort((a, b) =>
      a.chokepoint < b.chokepoint ? -1 : a.chokepoint > b.chokepoint ? 1 : 0,
    ); // :68/:82 sorted by chokepoint

  // reroute_impact_suez (snapshot_uc.py:85-98): the leg lists are the `leg_hours` column of
  // uc3_reroute_impact.aql; baseline_hours/reroute_hours are SUMs; delta = reroute - baseline.
  const baseline_legs = parts.impactBaseline.map((r) => round12(num(r.leg_hours)));
  const reroute_legs = parts.impactReroute.map((r) => round12(num(r.leg_hours)));
  const baseline_hours = round12(sum(baseline_legs));
  const reroute_hours = round12(sum(reroute_legs));
  const reroute_impact_suez: Uc3RerouteImpactSuez = {
    closed: REROUTE_IMPACT_CHOKEPOINT,
    origin: ORIGIN_ID, // ports/-prefixed (Pitfall 4)
    dest: DEST_ID,
    disabled_lanes: SUEZ_DISABLED_LANES,
    baseline_legs,
    reroute_legs,
    baseline_hours,
    reroute_hours,
    delta: round12(sum(reroute_legs) - sum(baseline_legs)),
  };

  // closure_gibraltar (snapshot_uc.py:102-110): OPEN_SENTINEL baseline vs GIBRALTAR-closed.
  const closure_gibraltar: Uc3ClosureGibraltar = {
    closed: FRAGMENTING_CHOKEPOINT,
    open_reachable_total: totalReachable(parts.openRows), // == 29 (SUM, not one row)
    closed_reachable_total: totalReachable(parts.gibRows), // == 11
    open_origins: parts.openRows.length, // == 9 (row COUNT, not a sum)
    closed_origins: parts.gibRows.length, // == 9
  };

  return {
    use_case: "UC3",
    origin: DEMO_ORIGIN, // bare LOCODE at top level (Pitfall 4)
    dest: DEMO_DEST,
    transit_share,
    reroute_impact_suez,
    closure_gibraltar,
    frozen_at_iso: new Date().toISOString(), // live timestamp (cf. bigquery.ts)
  };
}

/**
 * Port of snapshot_uc.py::snapshot_uc4 (lines 122-170). Path rows are {port, leg_hours} (the
 * AQL output shape). round12 each leg_hours; sum for hours; delta = reroute - baseline.
 */
export function assembleUc4(parts: Uc4Parts): Uc4Envelope {
  const pathLegs = (rows: Record<string, unknown>[]): Uc4PathHop[] =>
    rows.map((r) => ({ port: str(r.port), leg_hours: round12(num(r.leg_hours)) }));
  const baseline_path = pathLegs(parts.baselineRows);
  const reroute_path = pathLegs(parts.rerouteRows);
  const bh = sum(baseline_path.map((h) => h.leg_hours));
  const rh = sum(reroute_path.map((h) => h.leg_hours));
  return {
    use_case: "UC4",
    origin: ORIGIN_ID, // ports/-prefixed at top level (Pitfall 4)
    dest: DEST_ID,
    disabled_lanes: SUEZ_DISABLED_LANES,
    baseline_path,
    reroute_path,
    baseline_hours: round12(bh),
    reroute_hours: round12(rh),
    delta: round12(rh - bh),
    frozen_at_iso: new Date().toISOString(),
  };
}

// ---- The two fetchers. ----
// Default to the real runAql/ensureLoggedIn; the hermetic fall-back test injects a rejecting
// or slow runAql (and a stub ensureLoggedIn) so the all-or-fall-back path is exercised without
// a live cluster. Each UC's runs fire in PARALLEL under ONE budget (D-01).

type RunAql = (query: string, bindVars: Record<string, unknown>) => Promise<Record<string, unknown>[]>;

interface FetcherDeps {
  runAql?: RunAql;
  ensureLoggedIn?: () => Promise<void>;
  budgetMs?: number;
}

/**
 * Live UC3 fetcher (LiveFetcher<"uc3">). Fires the 5 runs in PARALLEL under one budget:
 *   - uc3_chokepoint_share.aql      {}                                           -> transit_share
 *   - uc3_reroute_impact.aql        {origin, dest, disabled_lanes=SUEZ}          -> reroute legs
 *   - uc3_reroute_impact.aql        {origin, dest, disabled_lanes=[]}            -> baseline legs
 *   - uc3_closure_unreachable.aql   {closed=OPEN_SENTINEL, maxhops}              -> open reachable
 *   - uc3_closure_unreachable.aql   {closed=GIBRALTAR, maxhops}                  -> closed reachable
 * Then assembleUc3. Any run fail/timeout/JWT-fail throws so serve() falls back to golden.
 */
export async function uc3LiveFetcher(deps: FetcherDeps = {}): Promise<Uc3Envelope> {
  const run = deps.runAql ?? runAql;
  const login = deps.ensureLoggedIn ?? ensureLoggedIn;
  try {
    await login();
    const [shareAql, impactAql, closureAql] = await Promise.all([
      readAql("uc3_chokepoint_share.aql"),
      readAql("uc3_reroute_impact.aql"),
      readAql("uc3_closure_unreachable.aql"),
    ]);
    const [share, impactReroute, impactBaseline, openRows, gibRows] = await withBudget(
      Promise.all([
        run(shareAql, {}),
        run(impactAql, {
          origin: ORIGIN_ID,
          dest: DEST_ID,
          disabled_lanes: SUEZ_DISABLED_LANES,
        }),
        run(impactAql, { origin: ORIGIN_ID, dest: DEST_ID, disabled_lanes: [] }),
        run(closureAql, { closed: OPEN_SENTINEL, maxhops: MAXHOPS }),
        run(closureAql, { closed: FRAGMENTING_CHOKEPOINT, maxhops: MAXHOPS }),
      ]),
      deps.budgetMs,
    );
    return assembleUc3({ share, impactReroute, impactBaseline, openRows, gibRows });
  } catch (err) {
    // Scrubbed log only — never the arangojs error object, the creds, or the token (T-12-03).
    console.error("[uc3LiveFetcher]", err instanceof Error ? err.message : String(err));
    throw err;
  }
}

/**
 * Live UC4 fetcher (LiveFetcher<"uc4">). Fires the 2 uc4_reroute_shortest_path.aql runs in
 * PARALLEL under one budget: baseline (disabled_lanes=[]) + reroute (disabled_lanes=SUEZ).
 * Then assembleUc4. Any failure throws so serve() falls back to golden.
 */
export async function uc4LiveFetcher(deps: FetcherDeps = {}): Promise<Uc4Envelope> {
  const run = deps.runAql ?? runAql;
  const login = deps.ensureLoggedIn ?? ensureLoggedIn;
  try {
    await login();
    const pathAql = await readAql("uc4_reroute_shortest_path.aql");
    const [baselineRows, rerouteRows] = await withBudget(
      Promise.all([
        run(pathAql, { origin: ORIGIN_ID, dest: DEST_ID, disabled_lanes: [] }),
        run(pathAql, {
          origin: ORIGIN_ID,
          dest: DEST_ID,
          disabled_lanes: SUEZ_DISABLED_LANES,
        }),
      ]),
      deps.budgetMs,
    );
    return assembleUc4({ baselineRows, rerouteRows });
  } catch (err) {
    console.error("[uc4LiveFetcher]", err instanceof Error ? err.message : String(err));
    throw err;
  }
}
