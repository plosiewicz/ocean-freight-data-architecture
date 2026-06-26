# Dress Rehearsal — Kill-the-Store Proof (DEPLOY-03)

> **Purpose:** Prove the demo **cannot hard-fail**. With **both** live stores
> (BigQuery and the ArangoDB cluster) unavailable, all four use-case views must
> still **render fully** — no error page — and each must visibly fall back to the
> frozen snafrjedipshot, shown by the amber **"Snapshot"** provenance pill in the page
> header. This is the DEPLOY-03 evidence that the live graded demo is safe even if
> a store is unreachable on demo day.
>
> This runbook is **deliberately a MANUAL checklist** (CONTEXT D-06 tradeoff): it is
> **NOT** an automated/CI assertion and **NOT** `FORCE_GOLDEN`-based. It exercises the
> *real* creds-gated live-else-golden fall-back by making the live stores genuinely
> unreachable (invalid creds), not by flipping a force flag. Automating this as a
> production-build + bogus-creds + `curl /api/uc{1..4}` + assert `served_by:"golden"`
> harness is a recommended but **out-of-scope follow-up**.
>
> **What this proves end-to-end (the fix this rehearsal now exercises):** the four `/ucN`
> **PAGES** are `export const dynamic = "force-dynamic"` and each passes its creds-gated
> live fetcher into `serve()` (Plan 13-07). So the **page header pill is now truthful**: it
> flips between green **`Live`** and amber **`Snapshot`** per request. Because the pages are
> per-request dynamic, a **plain browser reload re-runs the creds gate** — no rebuild is
> needed to flip a page from Live to Snapshot (step 3) or back to Live (step 4).
>
> **CR-02 — pages vs API surfaces differ.** The `/api/ucN` JSON **routes** are
> `export const dynamic = "force-static"` (+ `revalidate = 300`, DATA-06): they are cached
> static/ISR, so a cred change there is **rebuild-not-reload** (or wait out the 5-minute
> revalidate window) — the API JSON will **not** flip on a mere reload. This runbook
> deliberately asserts on the **PAGES** (which reload-flip), not the static API routes.

---

## ⚠️ Security — read before you start (ASVS V7)

- Set **INVALID placeholder** values only. Use obvious fakes such as
  `https://invalid.example:8529` and `INVALID_PLACEHOLDER`.
- **NEVER** commit this file, your `.env`, or any deploy config with a **real**
  `ARANGO_*` or `GCP_*` value. The real `.env` is gitignored (`*.env*`) and must stay
  that way; live credentials belong **only** in Vercel Project Settings →
  Environment Variables, never in committed git (threats T-13-09 / T-11-01 / T-06-01).
- This document contains **no** real credential, host, JWT, key, or password — and it
  must remain that way. `make secret-gate` (exit-20) enforces the no-committed-secrets
  contract; keep it green.

---

## The checklist (run in order)

### 1. Make both live stores unreachable — set INVALID placeholder creds

Pick **one** of the two ways below. Either way, set **invalid placeholders** — do
**not** use real values.

**Option A — local dev / preview (edit your gitignored `.env`):**

```bash
# Invalidate the live ArangoDB cluster creds (web/lib/arango.ts reads these)
ARANGO_URL=https://invalid.example:8529
ARANGO_USERNAME=INVALID_PLACEHOLDER
ARANGO_PASSWORD=INVALID_PLACEHOLDER
ARANGO_DATABASE=INVALID_PLACEHOLDER

# Invalidate the live BigQuery creds (web/lib/bigquery.ts reads these)
GCP_SA_KEY_B64=INVALID_PLACEHOLDER_NOT_REAL_BASE64
BQ_PROJECT=invalid-placeholder-project
```

Then run the app from the `web/` root:

```bash
cd web && npm run dev    # or: npm run build && npm run start
```

**Option B — Vercel preview:** in the preview deployment's Environment Variables,
overwrite the same `ARANGO_*` and `GCP_SA_KEY_B64` / `BQ_PROJECT` values with the
invalid placeholders above, then redeploy that preview.

> Note: leaving the creds **absent entirely** is the documented fall-back path too
> (D-06), but this rehearsal deliberately sets *invalid* values to prove the seam
> survives an unreachable/auth-failing store, not just a missing one.

### 2. Open all four use-case views

Visit each page in the running app:

- `/uc1`
- `/uc2`
- `/uc3`
- `/uc4`

### 3. Confirm each UC RENDERS FULLY and shows the amber "Snapshot" pill

For **every** one of `/uc1`–`/uc4`, confirm **both**:

- **Full render, no error page** — the dashboard / map / summary loads with real
  numbers (the frozen snapshot values), not a crash, blank, or "something went
  wrong" page.
- **Amber "Snapshot" pill** is visible in the page header (next to the
  "Answered by:" store badge). The pill reads literally **`Snapshot`** and is amber
  (`bg-amber-100`), distinct from the green **`Live`** pill you'd see when the store
  is reachable.

**Visual assert hook:** the pill carries `data-served-by="golden"` in the DOM
(from Plan 02, `web/components/uc-header.tsx`). To confirm precisely, open the
browser dev-tools and check the header for an element with
`data-served-by="golden"` — that is the machine-checkable proof that the view fell
back to the frozen snapshot rather than a live query. (The user-facing **copy** is
always `Snapshot`; the internal word "golden" never renders to the screen.)

A passing rehearsal: **4 of 4** UCs render fully **and** show the amber `Snapshot`
pill (`data-served-by="golden"`).

### 4. Revert the creds to restore live — confirm the pages flip back to green `Live`

Undo step 1 — restore the **real** `ARANGO_*` / `GCP_*` values (in your gitignored
`.env` for local, or in Vercel Project Settings → Environment Variables for the
deploy).

- **Local dev (`npm run dev`):** just **reload** `/uc1`–`/uc4` in the browser. Because the
  pages are `force-dynamic`, the reload re-runs the creds gate per request and the header
  pill flips back to the green **`Live`** (`data-served-by="live"`) for the UCs whose store
  is now reachable. **No rebuild is required for the pages** — this is exactly why the
  flip-to-Live step is now genuinely passable (it was impossible while the pages ignored the
  creds gate and served golden unconditionally).
- **Production (`npm run build && npm run start`) or Vercel:** restart the server (local) or
  redeploy (Vercel) so the new env vars are present, then reload `/uc1`–`/uc4` and confirm
  the pill shows green **`Live`** (`data-served-by="live"`).

> **CR-02 reminder:** the page pill flips on a reload because the **pages** are
> `force-dynamic`. The `/api/ucN` JSON routes are `force-static` (DATA-06), so their
> `served_by` is **rebuild-not-reload** (or wait out the 5-minute `revalidate`) — do **not**
> expect a `curl /api/ucN` response to flip Live on a mere reload. Assert the flip on the
> **page header pill**, not the API JSON.

> Reminder: never commit the reverted real values. They live only in the gitignored
> `.env` or in Vercel's environment settings.

---

## Why it works (the fall-back rationale)

Each `/ucN` **page** is **creds-gated** (D-06, Phases 11–12; wired onto the pages in Plan
13-07): the page passes a creds-gated live fetcher into `serve()` — the SAME fetcher its
sibling `/api/ucN` route uses — and `serve()` attempts the live query **only** when the
relevant store's env vars are present and well-formed, wrapping the live call in a
sub-ceiling wall-clock budget. When the creds are invalid (step 1), the live attempt throws /
times out, `serve()`'s catch **falls back to the frozen `data/golden/uc*.json` snapshot** and
stamps `served_by: "golden"` on the envelope — no error or stack reaches the rendered page.
The page header reads that field and renders the amber **`Snapshot`** pill (Plan 02). Because
the pages are `force-dynamic`, a plain reload re-runs this gate per request, so the pill is
truthful at all times and the Snapshot↔Live flip is genuinely observable.

The live page path is wrapped in a **~300s data-layer cache** (`unstable_cache`, Plan 13-07)
so repeated dynamic renders do **not** re-hit BigQuery/ArangoDB (DATA-06 preserved off the
per-render path); the cache does **not** store rejections, so an invalid-creds reload always
re-attempts and honestly falls back. Because the snapshots are byte-stable, credential-free,
and committed, every view renders fully with no live dependency — which is exactly the
"cannot hard-fail" thesis this rehearsal proves.

This is intentionally proven by a **human** running the steps above rather than by an
automated test, per the CONTEXT D-06 tradeoff. Run this rehearsal once before the
graded demo (and after any change to the creds-gate or the golden seam).
