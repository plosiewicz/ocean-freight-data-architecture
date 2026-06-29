// reliability.test.ts — contract for the UC4 route-reliability sidecar reader.
//
// Two concerns:
//   (1) readUc4Reliability() reads server-assets/golden/uc4-reliability.json (the REAL
//       copied asset) and returns the parsed Uc4ReliabilitySidecar: baseline has >=1 leg,
//       reroute has exactly 2 legs, and frozen_at_iso aligns with the committed golden
//       timestamp (an alignment guard that fails loudly if the copied asset drifts).
//   (2) NULL-SAFE path: when the sidecar file is absent, readUc4Reliability() returns null
//       (no throw), so a sidecar-less deploy still renders the UC4 page.
//
// node env, runs in the existing `lib/**/*.test.ts` glob. The positive case depends on
// copy-server-assets.mjs having run (the verify block runs it first).

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { afterEach, describe, expect, it, vi } from "vitest";

import { readUc4Reliability } from "@/lib/reliability";
import type { Uc4ReliabilitySidecar } from "@/lib/golden-types";

const GOLDEN_DIR = join(process.cwd(), "server-assets", "golden");

function readSidecarGolden(): Uc4ReliabilitySidecar {
  const raw = readFileSync(join(GOLDEN_DIR, "uc4-reliability.json"), "utf8");
  return JSON.parse(raw) as Uc4ReliabilitySidecar;
}

describe("readUc4Reliability (server-assets/golden/uc4-reliability.json -> sidecar)", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.resetModules();
  });

  it("returns the parsed sidecar with baseline (>=1 leg), reroute (2 legs), aligned ts", () => {
    const sidecar = readUc4Reliability();
    const golden = readSidecarGolden();

    expect(sidecar).not.toBeNull();
    expect(sidecar?.baseline_reliability.legs.length).toBeGreaterThanOrEqual(1);
    expect(sidecar?.reroute_reliability.legs.length).toBe(2);
    // Alignment guard against the real copied asset.
    expect(sidecar?.frozen_at_iso).toBe("2026-06-16T18:00:03.580451Z");
    expect(sidecar?.frozen_at_iso).toBe(golden.frozen_at_iso);
    // Route-level aggregates the page renders are finite numbers (never hardcoded).
    expect(Number.isFinite(sidecar?.baseline_reliability.on_time_pct)).toBe(true);
    expect(Number.isFinite(sidecar?.reroute_reliability.expected_delay_hours)).toBe(true);
  });

  it("returns null (does NOT throw) when the sidecar file is absent (null-safe guard)", async () => {
    // Force the existsSync guard to report the sidecar missing, exercising the
    // null-return branch without touching the real copied asset.
    vi.resetModules();
    vi.doMock("node:fs", async () => {
      const actual = await vi.importActual<typeof import("node:fs")>("node:fs");
      return { ...actual, existsSync: () => false };
    });
    const { readUc4Reliability: read } = await import("@/lib/reliability");
    expect(read()).toBeNull();
    vi.doUnmock("node:fs");
  });
});
