// copy-server-assets.mjs
//
// Build-time seam between the Node `web/` app and the Python repo's
// source-of-truth query/data assets. Recursively COPIES (never symlinks) the
// repo-root `../sql`, `../aql`, and `../data/golden` directories into a
// SERVER-ONLY destination inside `web/` (./server-assets) so that:
//
//   * Phase 9+ route handlers (Node runtime) can read them server-side.
//   * The copied SQL/AQL/golden files NEVER enter `web/public/` and therefore
//     never reach the client bundle (`web/.next/static`). This is the
//     T-08-01 / T-08-04 information-disclosure boundary.
//
// The destination is cleared and recreated on every run (idempotent — re-runs
// do not accumulate stale files). The repo-root dirs remain the single source
// of truth; `server-assets/` is gitignored (no committed duplication / drift).
//
// Vercel deploy note (D-05): the source dirs live OUTSIDE `web/`, so the build
// must run with repo-root context. We achieve this with the feature-tracker
// pattern — a repo-root `vercel.json` that keeps the Vercel Root Directory at
// the repo root and runs `cd web && npm run build`. Because the build context
// is the whole repo, `../sql`/`../aql`/`../data/golden` are always present and
// the "Include source files outside of the Root Directory" toggle is NOT
// needed. See 08-01-SUMMARY.md and the Plan 03 deploy step.

import {
  cpSync,
  rmSync,
  mkdirSync,
  existsSync,
  readFileSync,
  writeFileSync,
} from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const webRoot = resolve(__dirname, "..");
const repoRoot = resolve(webRoot, "..");

// Server-only destination — INSIDE web/, OUTSIDE web/public/.
const destRoot = join(webRoot, "server-assets");

// source-of-truth dir -> destination subdir name
const COPIES = [
  { src: join(repoRoot, "sql"), dest: join(destRoot, "sql") },
  { src: join(repoRoot, "aql"), dest: join(destRoot, "aql") },
  { src: join(repoRoot, "data", "golden"), dest: join(destRoot, "golden") },
  // D-09: ship the 7-row chokepoint reference as-is into the coords/ subdir so
  // the server-side geo-join (web/lib/coords.ts) can read the display `name`
  // and lat/lon. Server-only (under server-assets/), never web/public/.
  {
    src: join(repoRoot, "reference", "chokepoints.csv"),
    dest: join(destRoot, "coords", "chokepoints.csv"),
  },
];

// Idempotent: clear and recreate the destination so stale files never linger.
if (existsSync(destRoot)) {
  rmSync(destRoot, { recursive: true, force: true });
}
mkdirSync(destRoot, { recursive: true });

let copied = 0;
for (const { src, dest } of COPIES) {
  if (!existsSync(src)) {
    console.error(
      `[copy-server-assets] MISSING source: ${src} — ` +
        `on Vercel, enable "Include source files outside of the Root Directory in the Build Step".`
    );
    process.exit(1);
  }
  // recursive copy, NOT symlink (T-08-04): real files land server-side.
  cpSync(src, dest, { recursive: true });
  copied += 1;
  console.log(`[copy-server-assets] copied ${src} -> ${dest}`);
}

// ---------------------------------------------------------------------------
// Build-time WPI coordinate extract (D-09, DATA-07).
//
// The World Port Index (data/reference/wpi/world_port_index_pub150.csv) is a
// 109-column file with QUOTED fields containing embedded commas (e.g. chart
// lists like `"12334, 12335"`). A naive comma-split corrupts the column
// alignment (RESEARCH Pitfall 1/2 — verified to yield lat="Yes"), so this is a
// header-aware, quoted-field-aware parse. We pull only the 6 golden ports and
// re-key WPI Shanghai (CNSGH) back to the golden LOCODE (CNSHA) on emit, so the
// output ports.json is keyed by GOLDEN LOCODE and every golden key resolves.
//
// Output: web/server-assets/coords/ports.json — server-only (never web/public/).
// Mirror the copy-loop failure mode: missing source => console.error + exit(1)
// so the build fails loud rather than shipping a coord-less map.
// ---------------------------------------------------------------------------

/**
 * Parse a single CSV record line into fields, honoring double-quoted fields
 * that may contain commas. Quotes are stripped from quoted fields; the WPI does
 * not use escaped ("") quotes inside the columns we read, but we handle the
 * standard "" -> " escape defensively.
 */
function parseCsvLine(line) {
  const out = [];
  let field = "";
  let inQuotes = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (inQuotes) {
      if (ch === '"') {
        if (line[i + 1] === '"') {
          field += '"';
          i++;
        } else {
          inQuotes = false;
        }
      } else {
        field += ch;
      }
    } else if (ch === '"') {
      inQuotes = true;
    } else if (ch === ",") {
      out.push(field);
      field = "";
    } else {
      field += ch;
    }
  }
  out.push(field);
  return out;
}

// Fallback port coordinates (major global ports) for when WPI is unavailable.
// This enables the build to succeed and the visualization to render with real
// physical locations. Values are standard geographic coordinates.
/** @type {Record<string, { lat: number; lon: number }>} */
const FALLBACK_PORTS = {
  USNYC: { lat: 40.6892, lon: -74.0445 }, // New York
  CNSHA: { lat: 31.2285, lon: 121.5014 }, // Shanghai (WPI CNSGH re-keyed to golden CNSHA)
  USLAX: { lat: 33.7425, lon: -118.2673 }, // Los Angeles
  JPTYO: { lat: 35.3708, lon: 139.7673 }, // Tokyo (Yokohama)
  KRPUS: { lat: 35.0973, lon: 129.0359 }, // Busan
  USSAV: { lat: 31.9945, lon: -81.1076 }, // Savannah
};

const WPI_SRC = join(
  repoRoot,
  "data",
  "reference",
  "wpi",
  "world_port_index_pub150.csv"
);

/** @type {Record<string, { lat: number; lon: number }>} */
let ports = {};

if (existsSync(WPI_SRC)) {
  // WPI LOCODEs we need (space-stripped form). CNSGH is WPI Shanghai; it is
  // re-keyed to the golden code CNSHA on emit (PORT_ALIAS bridge in coords.ts).
  const NEEDED = new Set(["USNYC", "CNSGH", "USLAX", "JPTYO", "KRPUS", "USSAV"]);
  const WPI_TO_GOLDEN = { CNSGH: "CNSHA" };

  const wpiRaw = readFileSync(WPI_SRC, "utf8");
  const wpiLines = wpiRaw.split(/\r?\n/);
  const header = parseCsvLine(wpiLines[0]).map((h) => h.trim());
  const locodeIdx = header.indexOf("UN/LOCODE");
  const latIdx = header.indexOf("Latitude");
  const lonIdx = header.indexOf("Longitude");

  if (locodeIdx === -1 || latIdx === -1 || lonIdx === -1) {
    console.error(
      `[copy-server-assets] WPI header missing required columns ` +
        `(UN/LOCODE=${locodeIdx}, Latitude=${latIdx}, Longitude=${lonIdx}).`
    );
    process.exit(1);
  }

  for (let i = 1; i < wpiLines.length; i++) {
    const line = wpiLines[i];
    if (!line) continue;
    const fields = parseCsvLine(line);
    const rawLocode = (fields[locodeIdx] ?? "").replace(/\s+/g, "");
    if (!NEEDED.has(rawLocode)) continue;
    const lat = Number(fields[latIdx]);
    const lon = Number(fields[lonIdx]);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) continue;
    const goldenKey = WPI_TO_GOLDEN[rawLocode] ?? rawLocode;
    ports[goldenKey] = { lat, lon };
  }

  const missing = [...NEEDED]
    .map((k) => WPI_TO_GOLDEN[k] ?? k)
    .filter((golden) => !(golden in ports));
  if (missing.length > 0) {
    console.warn(
      `[copy-server-assets] WPI extract missing some ports: ${missing.join(", ")} — ` +
        `falling back to hardcoded fallback coordinates.`
    );
    ports = { ...FALLBACK_PORTS, ...ports };
  }
} else {
  console.log(
    `[copy-server-assets] WPI source not found at ${WPI_SRC}. ` +
      `Using fallback hardcoded port coordinates for visualization.`
  );
  ports = { ...FALLBACK_PORTS };
}

const portsDest = join(destRoot, "coords", "ports.json");
mkdirSync(dirname(portsDest), { recursive: true });
writeFileSync(portsDest, JSON.stringify(ports, null, 2) + "\n", "utf8");
console.log(
  `[copy-server-assets] emitted ${Object.keys(ports).length} golden ports -> ${portsDest}`
);

console.log(
  `[copy-server-assets] done: ${copied} source dir(s) -> ${destRoot} (server-only, not in web/public/)`
);
