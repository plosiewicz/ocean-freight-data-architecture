// bigquery.test.ts — Wave-0 hermetic contract for the live BigQuery LiveFetcher seam
// (DATA-02). Four concerns, mirroring coords.test.ts's structure exactly:
//
//   (1) coercion crux (THE point) — the Node BigQuery client returns INT64 as a STRING
//       and DATE as a `BigQueryDate { value }` wrapper, but the golden rows demand plain
//       `number`s and a plain "YYYY-MM-DD" string. coerceUc1Row/coerceUc2Row must map
//       field-for-field to the EXACT golden primitive types. These tests are HERMETIC:
//       inline BQ-shaped fixture rows, no live BQ, no network.
//   (2) envelope parity — an envelope assembled from coerced rows must carry EXACTLY the
//       golden top-level key set for its UC (read the committed golden as the oracle).
//   (3) verbatim sql — the staged server-assets/sql/*.sql is byte-identical to the
//       repo-root sql/ source. (Inherits the prebuild precondition — skip cleanly if the
//       staged dir is absent, mirroring how coords.test.ts documents its staged-asset dep.)
//   (4) creds gate — hasLiveCreds() reflects presence of GCP_SA_KEY_B64.
//
// RED state: web/lib/bigquery.ts does not exist yet, so the `@/lib/bigquery` import fails
// and the whole suite errors. That is the expected failure before Task 2 implements it.

import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import {
  coerceUc1Row,
  coerceUc2Row,
  hasLiveCreds,
  uc1LiveFetcher,
  uc2LiveFetcher,
} from "@/lib/bigquery";
import type { Uc1Envelope, Uc2Envelope } from "@/lib/golden-types";

const GOLDEN_DIR = join(process.cwd(), "server-assets", "golden");
const SQL_DIR = join(process.cwd(), "server-assets", "sql");
const REPO_SQL_DIR = join(process.cwd(), "..", "sql");

function readGolden<T>(uc: string): T {
  const raw = readFileSync(join(GOLDEN_DIR, `${uc}.golden.json`), "utf8");
  return JSON.parse(raw) as T;
}

// Avoid `void` so the no-unused-expressions / no-floating lints stay quiet; these are
// type-level assertions only — they never run.
type _Uc1FetcherIsLive = typeof uc1LiveFetcher extends () => Promise<Uc1Envelope>
  ? true
  : false;
type _Uc2FetcherIsLive = typeof uc2LiveFetcher extends () => Promise<Uc2Envelope>
  ? true
  : false;

describe("uc1 coerce (INT64-as-STRING -> number, FLOAT64 stays number, strings stay strings)", () => {
  it("maps a BQ-shaped UC1 row to a golden Uc1Row with exact primitive types", () => {
    // INT64 (legs) arrives as a STRING from the Node client; FLOAT64 arrives as number.
    const bqRow = {
      carrier_name: "Carrier CMDU",
      carrier_scac: "CMDU",
      origin_unlocode: "USNYC",
      dest_unlocode: "USSAV",
      lane_key: "USNYC-USSAV",
      legs: "10", // INT64 as STRING
      on_time_pct: 20, // FLOAT64
      avg_delay_hours: -82.8, // FLOAT64
    };
    const r = coerceUc1Row(bqRow);
    expect(r.legs).toBe(10);
    expect(typeof r.legs).toBe("number");
    expect(typeof r.on_time_pct).toBe("number");
    expect(typeof r.avg_delay_hours).toBe("number");
    expect(r.avg_delay_hours).toBe(-82.8);
    expect(r.carrier_name).toBe("Carrier CMDU");
    expect(typeof r.carrier_name).toBe("string");
    expect(typeof r.carrier_scac).toBe("string");
    expect(typeof r.origin_unlocode).toBe("string");
    expect(typeof r.dest_unlocode).toBe("string");
    expect(typeof r.lane_key).toBe("string");
  });
});

describe("uc2 coerce (BigQueryDate.value unwrap, INT64-as-STRING -> number)", () => {
  it("unwraps call_date to a 'YYYY-MM-DD' string and converts calls to number", () => {
    const bqRow = {
      unlocode: "USHOU",
      call_date: { value: "2024-01-01" }, // BigQueryDate wrapper
      calls: "3", // INT64 as STRING
      avg_turnaround_hours: 12.5, // FLOAT64
      max_turnaround_hours: 30, // FLOAT64
    };
    const r = coerceUc2Row(bqRow);
    expect(r.call_date).toBe("2024-01-01");
    expect(typeof r.call_date).toBe("string");
    expect(r.calls).toBe(3);
    expect(typeof r.calls).toBe("number");
    expect(typeof r.avg_turnaround_hours).toBe("number");
    expect(typeof r.max_turnaround_hours).toBe("number");
    expect(typeof r.unlocode).toBe("string");
  });
});

describe("envelope parity (live envelope key set == committed golden key set)", () => {
  it("uc1: an envelope from coerced rows has EXACTLY the golden top-level keys + correct types", () => {
    const golden = readGolden<Uc1Envelope>("uc1");
    const rows = [
      coerceUc1Row({
        carrier_name: "Carrier CMDU",
        carrier_scac: "CMDU",
        origin_unlocode: "USNYC",
        dest_unlocode: "USSAV",
        lane_key: "USNYC-USSAV",
        legs: "10",
        on_time_pct: 20,
        avg_delay_hours: -82.8,
      }),
    ];
    const envelope: Uc1Envelope = {
      frozen_at_iso: new Date().toISOString(),
      query: "sql/uc1_eta_reliability.sql",
      row_count: rows.length,
      rows,
      store: "bigquery",
      use_case: "UC1",
    };
    expect(Object.keys(envelope).sort()).toEqual(Object.keys(golden).sort());
    expect(envelope.store).toBe("bigquery");
    expect(envelope.use_case).toBe(golden.use_case);
    expect(envelope.query).toBe(golden.query);
    expect(envelope.row_count).toBe(envelope.rows.length);
    expect(typeof envelope.row_count).toBe("number");
  });

  it("uc2: envelope has the golden keys incl. distinct_call_dates = count of distinct call_date", () => {
    const golden = readGolden<Uc2Envelope>("uc2");
    const rows = [
      coerceUc2Row({
        unlocode: "USHOU",
        call_date: { value: "2024-01-01" },
        calls: "3",
        avg_turnaround_hours: 12.5,
        max_turnaround_hours: 30,
      }),
      coerceUc2Row({
        unlocode: "USHOU",
        call_date: { value: "2024-01-02" },
        calls: "6",
        avg_turnaround_hours: 13.1,
        max_turnaround_hours: 26.34,
      }),
    ];
    const envelope: Uc2Envelope = {
      frozen_at_iso: new Date().toISOString(),
      query: "sql/uc2_dwell_trend.sql",
      row_count: rows.length,
      rows,
      distinct_call_dates: new Set(rows.map((r) => r.call_date)).size,
      store: "bigquery",
      use_case: "UC2",
    };
    expect(Object.keys(envelope).sort()).toEqual(Object.keys(golden).sort());
    expect(envelope.distinct_call_dates).toBe(2);
    expect(envelope.use_case).toBe(golden.use_case);
    expect(envelope.query).toBe(golden.query);
    expect(envelope.row_count).toBe(envelope.rows.length);
  });
});

describe("verbatim sql (staged server-assets/sql byte-identical to repo sql/)", () => {
  const staged = (f: string) => join(SQL_DIR, f);
  const source = (f: string) => join(REPO_SQL_DIR, f);
  const haveStaged = existsSync(staged("uc1_eta_reliability.sql"));

  it.skipIf(!haveStaged)(
    "uc1: server-assets/sql/uc1_eta_reliability.sql == repo sql/uc1_eta_reliability.sql",
    () => {
      const a = readFileSync(staged("uc1_eta_reliability.sql"), "utf8");
      const b = readFileSync(source("uc1_eta_reliability.sql"), "utf8");
      expect(a).toBe(b);
    },
  );

  it.skipIf(!haveStaged)(
    "uc2: server-assets/sql/uc2_dwell_trend.sql == repo sql/uc2_dwell_trend.sql",
    () => {
      const a = readFileSync(staged("uc2_dwell_trend.sql"), "utf8");
      const b = readFileSync(source("uc2_dwell_trend.sql"), "utf8");
      expect(a).toBe(b);
    },
  );
});

describe("creds gate (hasLiveCreds reflects GCP_SA_KEY_B64)", () => {
  it("returns false when GCP_SA_KEY_B64 is unset and true when set", () => {
    const saved = process.env.GCP_SA_KEY_B64;
    try {
      delete process.env.GCP_SA_KEY_B64;
      expect(hasLiveCreds()).toBe(false);
      process.env.GCP_SA_KEY_B64 = "ZmFrZQ=="; // base64("fake")
      expect(hasLiveCreds()).toBe(true);
    } finally {
      if (saved === undefined) delete process.env.GCP_SA_KEY_B64;
      else process.env.GCP_SA_KEY_B64 = saved;
    }
  });
});
