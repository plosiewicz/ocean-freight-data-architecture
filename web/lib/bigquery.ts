// bigquery.ts — the live BigQuery LiveFetcher for UC1/UC2 (DATA-02). SERVER-ONLY:
// imported only by Node-runtime route handlers. It reads the VERSIONED SQL verbatim
// from server-assets/sql/, runs it against live BigQuery under a wall-clock timeout,
// coerces every row field to the EXACT golden primitive type, and returns the
// golden-shaped envelope. On any failure it THROWS so serve()'s catch falls back to
// golden — it never returns a partial envelope.
//
// Trust-boundary discipline (T-11-02..T-11-06):
//   - The base64 SA key is read from an UN-PREFIXED server env var (never NEXT_PUBLIC_),
//     decoded only inside this server module; it never reaches the client bundle, logs,
//     or the response (the envelope carries the SQL PATH string, never the SQL body).
//   - On error we log ONLY err.message — never the decoded creds object, never the full
//     error (which may attach request config with credential-shaped strings).
//   - INT64 is coerced to plain `number` via Number() (wrapIntegers stays default false)
//     so no BigInt/BigQueryInt reaches JSON.stringify.
//   - The query is wall-clock-bounded by Promise.race against LIVE_QUERY_TIMEOUT_MS so
//     the serve() catch fires and falls back to golden before the Vercel ceiling.

import { readFile } from "node:fs/promises";
import { join } from "node:path";

import { BigQuery } from "@google-cloud/bigquery";

import type { Uc1Envelope, Uc1Row, Uc2Envelope, Uc2Row } from "@/lib/golden-types";

/** GCP project for the live query (D-02). Overridable by env; defaults to the team project. */
const PROJECT_ID = process.env.BQ_PROJECT ?? "data-architecture-msds683";

/**
 * Single wall-clock knob bounding the whole live attempt (D-03/D-04). Default 7000ms is
 * conservative under the ~10s Hobby ceiling; widening for Pro/Fluid is a one-line env change.
 */
export const LIVE_QUERY_TIMEOUT_MS = Number(process.env.LIVE_QUERY_TIMEOUT_MS ?? 7000);

// server-assets/sql lives at web/server-assets/sql — the destination copy-server-assets.mjs
// writes to. Runtime cwd is web/, so process.cwd()-relative resolution lands there. Mirror
// serve.ts's GOLDEN_DIR, swapping "golden" -> "sql".
const SQL_DIR = join(process.cwd(), "server-assets", "sql");

/** D-06 gate: live querying is attempted only when the SA credential is present. */
export function hasLiveCreds(): boolean {
  return Boolean(process.env.GCP_SA_KEY_B64);
}

// Module-scoped memoized client (D-01, inline base64 JSON creds — NO file-path ADC, NO
// split private_key var). Created lazily so a missing credential throws at call time
// (caught by serve()), not at import time.
let _client: BigQuery | null = null;

function getClient(): BigQuery {
  if (_client) return _client;
  const b64 = process.env.GCP_SA_KEY_B64;
  if (!b64) throw new Error("GCP_SA_KEY_B64 not set");
  // base64 round-trip preserves the private_key newlines — no manual \n un-escaping (T-11-04).
  const credentials = JSON.parse(Buffer.from(b64, "base64").toString("utf8"));
  _client = new BigQuery({ credentials, projectId: PROJECT_ID });
  return _client;
}

/** Read a versioned SQL file VERBATIM from the staged server-assets dir (DATA-02, T-11-03). */
async function readSql(file: string): Promise<string> {
  return readFile(join(SQL_DIR, file), "utf8");
}

/**
 * Run SQL against live BigQuery, wall-clock-bounded by Promise.race (Pitfall 4). The
 * client's own timeoutMs does not bound auth/network legs reliably, so the race is the
 * authoritative bound; clearTimeout in finally avoids a dangling timer holding the
 * function open. wrapIntegers stays at its default (false) so INT64 arrives as STRING.
 */
async function runBounded(sql: string): Promise<Record<string, unknown>[]> {
  const client = getClient();
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<never>((_resolve, reject) => {
    timer = setTimeout(
      () => reject(new Error(`live query exceeded ${LIVE_QUERY_TIMEOUT_MS}ms`)),
      LIVE_QUERY_TIMEOUT_MS,
    );
  });
  try {
    const queryRun = client
      .query({ query: sql })
      .then(([rows]) => rows as Record<string, unknown>[]);
    return await Promise.race([queryRun, timeout]);
  } finally {
    if (timer) clearTimeout(timer);
  }
}

// ---- Per-UC coercers: explicit field maps to the EXACT golden primitive types. ----
// Cast-and-trust is forbidden — the Node client returns INT64 as STRING and DATE as a
// BigQueryDate wrapper, which would silently break field-for-field parity (Pitfalls 1-3).

/** INT64-as-STRING or FLOAT64 -> plain number. Counts are tiny (<=~30): no precision loss. */
function num(v: unknown): number {
  return Number(v);
}

export function coerceUc1Row(r: Record<string, unknown>): Uc1Row {
  return {
    carrier_name: String(r.carrier_name),
    carrier_scac: String(r.carrier_scac),
    origin_unlocode: String(r.origin_unlocode),
    dest_unlocode: String(r.dest_unlocode),
    lane_key: String(r.lane_key),
    legs: num(r.legs), // INT64 -> number
    on_time_pct: num(r.on_time_pct), // FLOAT64 -> number
    avg_delay_hours: num(r.avg_delay_hours), // FLOAT64 -> number
  };
}

export function coerceUc2Row(r: Record<string, unknown>): Uc2Row {
  // DATE arrives as BigQueryDate { value: "YYYY-MM-DD" }; unwrap .value (byte-identical
  // to the golden format). Tolerate a plain string too (hermetic-fixture safety).
  const cd = r.call_date;
  const call_date =
    typeof cd === "string" ? cd : String((cd as { value: string }).value);
  return {
    unlocode: String(r.unlocode),
    call_date,
    calls: num(r.calls), // INT64 -> number
    avg_turnaround_hours: num(r.avg_turnaround_hours), // FLOAT64 -> number
    max_turnaround_hours: num(r.max_turnaround_hours), // FLOAT64 -> number
  };
}

/**
 * Live UC1 fetcher (LiveFetcher<"uc1">). Reads the versioned SQL verbatim, runs it
 * bounded, coerces each row, and assembles the golden-shaped Uc1Envelope. The `query`
 * field is the golden PATH STRING (never the SQL body, D-05/T-11-03); `frozen_at_iso` is
 * the live timestamp (D-05). Throws on any failure so serve() falls back to golden.
 */
export async function uc1LiveFetcher(): Promise<Uc1Envelope> {
  try {
    const sql = await readSql("uc1_eta_reliability.sql");
    const raw = await runBounded(sql);
    const rows = raw.map(coerceUc1Row);
    return {
      frozen_at_iso: new Date().toISOString(),
      query: "sql/uc1_eta_reliability.sql",
      row_count: rows.length,
      rows,
      store: "bigquery",
      use_case: "UC1",
    };
  } catch (err) {
    // Scrubbed log only — never the creds object, never the full error (T-11-03/Pitfall 5).
    console.error(
      "[uc1LiveFetcher]",
      err instanceof Error ? err.message : String(err),
    );
    throw err;
  }
}

/**
 * Live UC2 fetcher (LiveFetcher<"uc2">). As UC1, plus the UC2-only `distinct_call_dates`
 * computed from the coerced rows.
 */
export async function uc2LiveFetcher(): Promise<Uc2Envelope> {
  try {
    const sql = await readSql("uc2_dwell_trend.sql");
    const raw = await runBounded(sql);
    const rows = raw.map(coerceUc2Row);
    return {
      frozen_at_iso: new Date().toISOString(),
      query: "sql/uc2_dwell_trend.sql",
      row_count: rows.length,
      rows,
      distinct_call_dates: new Set(rows.map((r) => r.call_date)).size,
      store: "bigquery",
      use_case: "UC2",
    };
  } catch (err) {
    console.error(
      "[uc2LiveFetcher]",
      err instanceof Error ? err.message : String(err),
    );
    throw err;
  }
}
