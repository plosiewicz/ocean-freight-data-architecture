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
// Vercel deploy note (D-05): because the source dirs live OUTSIDE the Vercel
// Root Directory (`web/`), the Vercel project MUST have the setting
// "Include source files outside of the Root Directory in the Build Step"
// ENABLED, or `../sql`/`../aql`/`../data/golden` will not exist at build time.
// See 08-01-SUMMARY.md and the Plan 03 deploy step.

import { cpSync, rmSync, mkdirSync, existsSync } from "node:fs";
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

console.log(
  `[copy-server-assets] done: ${copied} source dir(s) -> ${destRoot} (server-only, not in web/public/)`
);
