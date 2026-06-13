# M1 Deck Source — GCP Billing Guard (DOM-05)

> **Manual step:** This file is the repo-side source of truth for the M1 "Billing Guard"
> slide. Placing this content onto a slide in the shared Google Slides deck is a manual
> copy-paste step — do not create a new deck. Slide placement is the only manual follow-up.
>
> **Team:** Grilled Cheesin · **Phase:** 1 (Domain & Dataset Lock, M1) · **Requirement:** DOM-05

## What this is

A GCP **billing budget + alert** is the credit guard for the whole project. It is configured
**before any compute is provisioned** so the team is warned long before GCP credits are at
risk. The budget is **metadata on the billing account** — it provisions no compute and is
**free**.

## The budget (D-16 / D-17)

| Property | Value | Decision |
|----------|-------|----------|
| Monthly budget cap | **$50** (`--budget-amount=50USD`) | D-16 |
| Period | Monthly (`--calendar-period=month`) | D-16 |
| Alert threshold 1 | **50%** of spend (`--threshold-rule=percent=0.50`) — early warning | D-17 |
| Alert threshold 2 | **90%** of spend (`--threshold-rule=percent=0.90`) — near-limit | D-17 |
| Alert threshold 3 | **100%** of spend (`--threshold-rule=percent=1.00`) — at-limit | D-17 |
| Scope | the **billing account**, not project compute | provisions nothing |
| Cost | **free** — a budget object incurs no charge | — |
| Display name | `Grilled Cheesin - MSDS683 $50/mo` | identifies the budget for `budgets list` |

## The exact command (recorded for the deck, not run from this file)

The budget is created on the billing account with the **Cloud Billing Budget API**
(`billingbudgets.googleapis.com`) enabled. The literal flags used are:

`gcloud billing budgets create --billing-account=<ID> --display-name="Grilled Cheesin - MSDS683 $50/mo" --budget-amount=50USD --calendar-period=month --threshold-rule=percent=0.50 --threshold-rule=percent=0.90 --threshold-rule=percent=1.00`

The API is enabled once beforehand with `gcloud services enable billingbudgets.googleapis.com`.
The **Console equivalent** is: Billing -> Budgets & alerts -> Create budget -> $50 monthly ->
thresholds 50% / 90% / 100% (these are the GCP defaults).

> `<ID>` is the billing account ID (format `XXXXXX-XXXXXX-XXXXXX`, found via
> `gcloud billing accounts list`). It is a **secret-adjacent value kept OUT of the repo**
> (T-1 / T-03-02): it is read from the `GCP_BILLING_ACCOUNT_ID` environment variable at run
> time and is never hardcoded in `scripts/verify_m1.sh` or in this deck source.

## Least-privilege note (T-2 / T-03-01)

Budget creation uses only **`roles/billing.admin`** (Billing Account Administrator), plus
**`roles/serviceusage.serviceUsageAdmin`** to enable the API. **Owner is never granted** just
to create a budget — this is the least-privilege control, and it sets the credential-hygiene
precedent (DEL-02) early.

## No Cloud Composer in Phase 1 (D-18)

**No Cloud Composer environment is created in Phase 1** (or until Phase 5, when it is the real
cost driver and is torn down when idle). The billing budget + alert must exist **before** any
compute is provisioned. The evidence-check script (`scripts/verify_m1.sh`) asserts both: that
the `$50/mo` budget is present on the billing account, and that
`gcloud composer environments list` returns empty.

## Verification

Run `bash scripts/verify_m1.sh` and confirm the DOM-05 line reports PASS — it asserts the
budget presence (via `gcloud billing budgets list`) and the empty-Composer condition (via
`gcloud composer environments list`).
