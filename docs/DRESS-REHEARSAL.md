# Dress Rehearsal — Kill-the-Store Proof (DEPLOY-03)

> **Purpose:** Prove the demo **cannot hard-fail**. With **both** live stores
> (BigQuery and the ArangoDB cluster) unavailable, all four use-case views must
> still **render fully** — no error page — and each must visibly fall back to the
> frozen snapshot, shown by the amber **"Snapshot"** provenance pill in the page
> header. This is the DEPLOY-03 evidence that the live graded demo is safe even if
> a store is unreachable on demo day.
>
> This runbook is **deliberately a MANUAL checklist** (CONTEXT D-06 tradeoff): it is
> **NOT** an automated/CI assertion and **NOT** `FORCE_GOLDEN`-based. It exercises the
> *real* creds-gated live-else-golden fall-back by making the live stores genuinely
> unreachable (invalid creds), not by flipping a force flag. Automating this as a
> production-build + bogus-creds + `curl /api/uc{1..4}` + assert `served_by:"golden"`
> harness is a recommended but **out-of-scope follow-up**.

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

### 4. Revert the creds to restore live

Undo step 1 — restore the **real** `ARANGO_*` / `GCP_*` values (in your gitignored
`.env` for local, or in Vercel Project Settings → Environment Variables for the
deploy) and restart / redeploy. Reload `/uc1`–`/uc4` and confirm the pill flips back
to the green **`Live`** (`data-served-by="live"`) for the UCs whose store is now
reachable.

> Reminder: never commit the reverted real values. They live only in the gitignored
> `.env` or in Vercel's environment settings.

---

## Why it works (the fall-back rationale)

Each `/api/ucN` handler is **creds-gated** (D-06, Phases 11–12): it attempts the live
query **only** when the relevant store's env vars are present and well-formed, and it
wraps the live call in a sub-ceiling wall-clock budget. When the creds are invalid
(step 1), the live attempt throws / times out, the handler **falls back to the frozen
`data/golden/uc*.json` snapshot**, and stamps `served_by: "golden"` on the response
envelope. The page header reads that field and renders the amber **`Snapshot`** pill
(Plan 02). Because the snapshots are byte-stable, credential-free, and committed, every
view renders fully with no live dependency — which is exactly the "cannot hard-fail"
thesis this rehearsal proves.

This is intentionally proven by a **human** running the steps above rather than by an
automated test, per the CONTEXT D-06 tradeoff. Run this rehearsal once before the
graded demo (and after any change to the creds-gate or the golden seam).
