// reliability.ts — server-only reader for the frozen UC4 route-reliability sidecar
// (data/golden/uc4-reliability.json, produced by scripts/freeze_uc4_reliability.py).
//
// The reliability aggregates live in a SEPARATE frozen artifact (uc4-reliability.json) —
// they are NOT part of the serve() UC4 envelope (the sidecar adds NO key to
// uc4.golden.json, so the byte-exact parity test in web/lib/arango.test.ts is untouched).
// The UC4 page reads this file server-side, mirroring criticality.ts's GOLDEN_DIR node:fs
// pattern, and passes the result as a prop to Uc4Summary.
//
// Server-only discipline (mirror criticality.ts / serve.ts): this module reads node:fs
// from server-assets/golden/, so every importing module MUST run on the Node runtime. The
// artifact is credential-free public reference data (World Bank LPI / UNCTAD LSCI–derived
// reliability metrics), so it carries only public floats — but the server-asset boundary
// is preserved (it never reaches web/public/ or the client bundle).
//
// Null-safe: when the sidecar asset is absent (e.g. a deploy without the freeze step),
// readUc4Reliability() returns null rather than throwing, so the UC4 page still renders
// the rest of its content (the reliability card is simply omitted).

import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

import type { Uc4ReliabilitySidecar } from "@/lib/golden-types";

// server-assets/golden lives at web/server-assets/golden — the same dir serve.ts /
// criticality.ts read from (copy-server-assets.mjs carries data/golden/ here at build).
// Resolve from process.cwd() exactly like criticality.ts's GOLDEN_DIR (runtime cwd is web/).
const GOLDEN_DIR = join(process.cwd(), "server-assets", "golden");

/**
 * Read the frozen UC4 reliability sidecar server-side and return the parsed
 * `Uc4ReliabilitySidecar`, or `null` when the file is absent (null-safe — no throw, so a
 * sidecar-less deploy still renders the page). Reads synchronously via node:fs from the
 * same GOLDEN_DIR convention serve.ts/criticality.ts use. Server-only (Node runtime).
 */
export function readUc4Reliability(): Uc4ReliabilitySidecar | null {
  const path = join(GOLDEN_DIR, "uc4-reliability.json");
  if (!existsSync(path)) {
    return null;
  }
  return JSON.parse(readFileSync(path, "utf8")) as Uc4ReliabilitySidecar;
}
