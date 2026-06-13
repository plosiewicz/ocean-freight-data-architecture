#!/usr/bin/env bash
#
# verify_m1.sh — Phase 1 (M1) evidence-check.
#
# This is the phase's quick-run validation command (per 01-VALIDATION.md).
# It is EVIDENCE-based, not test-based: each DOM-0x requirement is proven by a
# checkable artifact (a deck-source file, a populated table, or a read-only
# gcloud assertion), since Phase 1 ships documentation/design, not code.
#
# Prints a per-DOM PASS/FAIL line and exits non-zero on any failure.
#
# Secrets discipline (T-1 / T-03-02): the billing account ID is read ONLY from
# the GCP_BILLING_ACCOUNT_ID environment variable — it is NEVER hardcoded here.
#   export GCP_BILLING_ACCOUNT_ID=XXXXXX-XXXXXX-XXXXXX   # format from `gcloud billing accounts list`
#
# Usage:
#   bash scripts/verify_m1.sh
#
set -u

# Resolve the repo root so the script works from any CWD.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

DECK_DIR="docs/deck"
FAILURES=0

pass() { printf '  PASS  %s\n' "$1"; }
fail() { printf '  FAIL  %s\n' "$1"; FAILURES=$((FAILURES + 1)); }
hdr()  { printf '\n[%s] %s\n' "$1" "$2"; }

# ---------------------------------------------------------------------------
# DOM-01 — Team name + members + domain documented; PROJECT.md header no longer TBD.
# ---------------------------------------------------------------------------
hdr DOM-01 "Team identity / domain"
if [ -f "${DECK_DIR}/m1-team-domain.md" ]; then
  pass "deck source ${DECK_DIR}/m1-team-domain.md exists"
else
  fail "missing ${DECK_DIR}/m1-team-domain.md"
fi
if grep -q "Grilled Cheesin" .planning/PROJECT.md 2>/dev/null; then
  pass "PROJECT.md header names the team (Grilled Cheesin)"
else
  fail "PROJECT.md header does not name the team"
fi
# Header line must not still read TBD for the team identity.
if grep -E "^> *Team name" .planning/PROJECT.md 2>/dev/null | grep -qi "TBD"; then
  fail "PROJECT.md team header still contains TBD"
else
  pass "PROJECT.md team header is no longer TBD"
fi

# ---------------------------------------------------------------------------
# DOM-02 — Four analytical use cases stated (deck source exists).
# ---------------------------------------------------------------------------
hdr DOM-02 "Four analytical use cases"
if [ -f "${DECK_DIR}/m1-use-cases.md" ]; then
  pass "deck source ${DECK_DIR}/m1-use-cases.md exists"
else
  fail "missing ${DECK_DIR}/m1-use-cases.md"
fi

# ---------------------------------------------------------------------------
# DOM-03 — Source Inventory names all six access-verified sources.
# ---------------------------------------------------------------------------
hdr DOM-03 "Source Inventory (6 sources access-verified)"
INV="${DECK_DIR}/m1-source-inventory.md"
if [ -f "${INV}" ]; then
  pass "deck source ${INV} exists"
  for src in "MarineCadastre" "World Port Index" "UN/LOCODE" "LSCI" "LPI" "Comtrade"; do
    if grep -q "${src}" "${INV}"; then
      pass "Source Inventory names: ${src}"
    else
      fail "Source Inventory missing: ${src}"
    fi
  done
else
  fail "missing ${INV}"
fi

# ---------------------------------------------------------------------------
# DOM-04 — Real-vs-synthetic strategy deck source exists.
# ---------------------------------------------------------------------------
hdr DOM-04 "Real-vs-synthetic strategy"
if [ -f "${DECK_DIR}/m1-real-vs-synthetic.md" ]; then
  pass "deck source ${DECK_DIR}/m1-real-vs-synthetic.md exists"
else
  fail "missing ${DECK_DIR}/m1-real-vs-synthetic.md"
fi

# ---------------------------------------------------------------------------
# DOM-05 — GCP billing budget ($50/mo, 50/90/100%) exists; NO Composer (D-18).
# ---------------------------------------------------------------------------
hdr DOM-05 "GCP billing guard + no Composer"
GUARD="${DECK_DIR}/m1-billing-guard.md"
if [ -f "${GUARD}" ]; then
  pass "deck source ${GUARD} exists"
else
  fail "missing ${GUARD}"
fi

if ! command -v gcloud >/dev/null 2>&1; then
  fail "gcloud CLI not found — cannot assert the live budget (DOM-05 evidence). Install gcloud or run on a machine with it."
else
  if [ -z "${GCP_BILLING_ACCOUNT_ID:-}" ]; then
    fail "GCP_BILLING_ACCOUNT_ID is not set — export it (never commit it) before asserting the budget. See: gcloud billing accounts list"
  else
    # Assert the $50/mo budget exists on the billing account.
    BUDGETS="$(gcloud billing budgets list --billing-account="${GCP_BILLING_ACCOUNT_ID}" 2>/dev/null || true)"
    if printf '%s' "${BUDGETS}" | grep -qi "MSDS683"; then
      pass "billing budget present on account (matches 'MSDS683')"
    else
      fail "no MSDS683 \$50/mo budget found via 'gcloud billing budgets list'"
    fi
  fi

  # D-18: assert NO Cloud Composer environment exists in any region.
  COMPOSER="$(gcloud composer environments list 2>/dev/null || true)"
  # `gcloud ... list` prints "Listed 0 items." (or nothing) when empty.
  if [ -z "${COMPOSER}" ] || printf '%s' "${COMPOSER}" | grep -qi "Listed 0"; then
    pass "no Cloud Composer environment exists (D-18)"
  else
    fail "a Cloud Composer environment exists — violates D-18 (no compute before the budget guard)"
  fi
fi

# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------
printf '\n'
if [ "${FAILURES}" -eq 0 ]; then
  printf 'ALL DOM EVIDENCE ROWS PASSED\n'
  exit 0
else
  printf '%d EVIDENCE CHECK(S) FAILED\n' "${FAILURES}"
  exit 1
fi
